"""One cover record and a PNG; the Host owns style decisions and real generation."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import zlib

from .approved_direction import canonical_digest
from .artifact_store import ArtifactStore
from .distribution_contract import validate_saved_receipt
from .obsidian_adapter import SaveAdapterError, split_cover
from .run_store import RunStore
from .save_contract import is_protected_segment
from .save_service import SaveService

LAYOUT_VERSION = "wide-balanced-square-v2"
STYLES = ("consulting", "retro-ink", "raster-tech")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("cover must be a real PNG")
    position, size, compressed, kind = 8, None, bytearray(), None
    while position + 12 <= len(data):
        length = struct.unpack(">I", data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        end = position + 8 + length
        if end + 4 > len(data) or zlib.crc32(data[position + 4:end]) != struct.unpack(">I", data[end:end + 4])[0]:
            raise ValueError("PNG is damaged")
        if kind == b"IHDR":
            if size is not None or length != 13:
                raise ValueError("invalid PNG header")
            size = struct.unpack(">II", data[position + 8:position + 16])
        if kind == b"IDAT":
            compressed.extend(data[position + 8:end])
        position = end + 4
        if kind == b"IEND":
            break
    if size is None or kind != b"IEND" or not compressed or position != len(data):
        raise ValueError("incomplete PNG")
    width, height = size
    if width < 900 or height < 380 or width * height > 20_000_000 or abs(width / height - 2.35) > 0.035:
        raise ValueError("cover must be a readable horizontal image near 2.35:1")
    # A bounded decoder checks actual compressed pixel content without an image dependency.
    decoder = zlib.decompressobj()
    raw = decoder.decompress(bytes(compressed), width * height * 8 + height + 1)
    if not decoder.eof or not raw:
        raise ValueError("invalid PNG pixel data")
    return size


class CoverService:
    def __init__(self, root, adapter):
        self.store = RunStore(root)
        self.artifacts = ArtifactStore(root)
        self.adapter = adapter

    def _load(self, run_id):
        run = self.store.load(run_id)
        if run["status"] not in {"saved", "distribution_optional"}:
            raise ValueError("cover requires a saved article")
        if len(run["gate_approvals"]) != 2:
            raise ValueError("cover requires the existing two writing approvals")
        approved = self.artifacts.read_json(run_id, "approved_final.json")
        receipt = self.artifacts.read_json(run_id, "save_receipt.json")
        context = self.artifacts.read_json(run_id, "article_context_v1.json")
        validate_saved_receipt(run, approved, receipt)
        if approved["context_digest"] != canonical_digest(context):
            raise ValueError("cover Context mismatch")
        if approved["knowledge_base_identity"] != run["knowledge_base_identity"] or approved["ip_identity"] != run["ip_identity"]:
            raise ValueError("cover knowledge base or IP mismatch")
        if self.adapter.backend != receipt["backend"]:
            raise ValueError("cover adapter mismatch")
        live = self.adapter.read_back(receipt["target"])
        SaveService._verify_readback(approved, receipt["target"], live)
        if self.adapter.backend == "obsidian":
            expected = self.adapter._directory(approved["save_target"]["target_ref"])
            if Path(live["object_ref"]).parent != expected:
                raise ValueError("article escaped its Manifest output directory")
        return run, approved, receipt, context, live

    def context(self, run_id, style):
        if style not in STYLES:
            raise ValueError("choose exactly one supported cover style")
        run, approved, receipt, context, live = self._load(run_id)
        raw_digest = digest(Path(live["object_ref"]).read_bytes()) if self.adapter.backend == "obsidian" else canonical_digest(live)
        existing = []
        for path in self.artifacts.boundary.child("runs", run_id).glob("cover-*.json"):
            value = json.loads(path.read_text())
            if value.get("approved_final_digest") == canonical_digest(approved) and value.get("style") == style and value.get("layout_version") == LAYOUT_VERSION:
                image = Path(value["image_path"])
                if image.is_file() and digest(image.read_bytes()) == value["image_sha256"]:
                    value["currently_applied"] = bool(value.get("apply") and raw_digest == value.get("article_after_digest"))
                    existing.append(value)
        return {
            "run_id": run_id, "style": style, "layout_version": LAYOUT_VERSION, "square_crop_rule": "left: x=0,y=0,width=image_height,height=image_height", "title": live["title"], "body": live["body"],
            "approved_final_digest": canonical_digest(approved), "article_digest": raw_digest,
            "must_avoid": context.get("must_avoid", []),
            "profile": context.get("selected_05_profile_context", {}),
            "existing": existing, "backend": self.adapter.backend,
        }

    def save(self, run_id, candidate):
        directory = self.artifacts.boundary.child("runs", run_id)
        with (directory / ".cover.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self._save(run_id, candidate, directory)

    def _save(self, run_id, candidate, directory):
        style = candidate.get("style")
        if style not in STYLES or candidate.get("visual_checked") is not True:
            raise ValueError("one supported style and actual visual check are required")
        if candidate.get("layout_version") != LAYOUT_VERSION:
            raise ValueError("cover requires the current square-title layout and crop check")
        for key in ("cover_title", "prompt", "generator", "image_path", "article_digest"):
            if not isinstance(candidate.get(key), str) or not candidate[key].strip():
                raise ValueError(f"missing cover {key}")
        run, approved, receipt, context, live = self._load(run_id)
        approved_hash = canonical_digest(approved)
        if candidate.get("approved_final_digest") != approved_hash:
            raise ValueError("cover was made for another approved article")
        for phrase in context.get("must_avoid", []):
            if phrase.strip() and phrase.casefold() in candidate["cover_title"].casefold():
                raise ValueError("cover title contains a forbidden phrase")
        apply = candidate.get("apply", self.adapter.backend == "obsidian")
        if not isinstance(apply, bool) or (apply and self.adapter.backend != "obsidian"):
            raise ValueError("remote image writeback is not implemented; use apply=false")
        data = Path(candidate["image_path"]).expanduser().read_bytes()
        width, height = png_size(data)
        image_hash = digest(data)
        key = canonical_digest([approved_hash, style, candidate["prompt"], candidate["cover_title"], image_hash, apply, LAYOUT_VERSION])[:24]
        record_path = directory / f"cover-{key}.json"
        article = Path(live["object_ref"]) if self.adapter.backend == "obsidian" else None
        raw = article.read_bytes() if article else None
        current = digest(raw) if raw is not None else canonical_digest(live)
        if record_path.exists():
            record = json.loads(record_path.read_text())
            image = Path(record["image_path"])
            if not image.is_file() or digest(image.read_bytes()) != record["image_sha256"]:
                raise ValueError("saved cover image changed or disappeared")
            if apply and current == record["article_after_digest"]:
                record["applied"] = True
                atomic_write(record_path, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode())
                return {"cover": record, "resumed": True}
            if not apply:
                if candidate["article_digest"] != current:
                    raise ValueError("article changed since cover generation")
                return {"cover": record, "resumed": True}
        if candidate["article_digest"] != current:
            raise ValueError("article changed since cover generation")
        if apply:
            root = self.adapter.boundary.root
            conventional = root / "A.系统" / "附件"
            default = conventional / "content-gzh-cover" if conventional.is_dir() else article.parent / (article.stem + "_配图")
            target_dir = Path(candidate.get("asset_directory") or default).expanduser().resolve()
            if not target_dir.is_relative_to(root) or any(is_protected_segment(x) for x in target_dir.relative_to(root).parts):
                raise ValueError("cover asset directory escapes output boundaries")
        else:
            target_dir = directory
        target = target_dir / f"cover-{style}-{key}.png"
        if target.is_symlink():
            raise ValueError("cover target cannot be a symlink")
        if target.exists():
            if digest(target.read_bytes()) != image_hash:
                raise ValueError("cover filename conflict")
        result = {
            "run_id": run_id, "approved_final_digest": approved_hash, "style": style,
            "layout_version": LAYOUT_VERSION, "square_crop": [0, 0, height, height],
            "cover_title": candidate["cover_title"], "prompt": candidate["prompt"],
            "generator": candidate["generator"], "visual_checked": True,
            "image_path": str(target), "image_sha256": image_hash, "width": width, "height": height,
            "apply": apply, "applied": False, "article_before_digest": current,
            "draftbox": False, "published": False,
        }
        if apply:
            base, _, _ = split_cover(raw.decode("utf-8"))
            relative = target.relative_to(self.adapter.boundary.root).as_posix()
            metadata = f'cover: {json.dumps(relative, ensure_ascii=False)}\ncontent_gzh_cover_sha256: {image_hash}\n'
            block = f'<!-- content-gzh:cover -->\n![[{relative}]]\n<!-- /content-gzh:cover -->\n'
            updated = base.replace('\n---\n# ', '\n' + metadata + '---\n' + block + '# ', 1).encode()
            if updated == raw:
                raise ValueError("cover insertion point missing")
            if split_cover(updated.decode("utf-8")) != (base, relative, image_hash):
                raise ValueError("cover writeback preflight failed")
            result.update({"previous_document": raw.decode(), "article_after_digest": digest(updated)})
        target_dir.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with target.open("xb") as handle:
                handle.write(data)
        if digest(target.read_bytes()) != image_hash:
            raise ValueError("cover image readback failed")
        atomic_write(record_path, (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
        if apply:
            with article.open("rb") as article_lock:
                fcntl.flock(article_lock, fcntl.LOCK_EX)
                if digest(article.read_bytes()) != current:
                    raise ValueError("article changed during cover save")
                atomic_write(article, updated)
            SaveService._verify_readback(approved, receipt["target"], self.adapter.read_back(receipt["target"]))
            result["applied"] = True
            atomic_write(record_path, (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
        return {"cover": result, "resumed": False}

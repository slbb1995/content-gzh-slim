"""One cover record and a PNG; the Host owns style decisions and real generation."""
from __future__ import annotations

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
from .file_lock import exclusive_lock
from .obsidian_adapter import SaveAdapterError, split_cover
from .path_boundary import PathBoundary
from .run_store import RunStore
from .save_contract import is_protected_segment
from .save_service import SaveService

LAYOUT_VERSION = "wide-balanced-square-v2"
STYLES = ("consulting", "real-photo", "retro-blueprint")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    PathBoundary(path.parent).child(path.name)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.read_bytes() != data:
            raise ValueError("cover staging readback failed")
        temporary.chmod(mode)
        os.replace(temporary, path)
        if path.read_bytes() != data:
            raise ValueError("cover final readback failed")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def create_once(path: Path, data: bytes) -> None:
    """Publish complete bytes create-only; a failed staging write cannot poison retry."""
    PathBoundary(path.parent).child(path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("cover artifact conflicts with existing content")
        return
    descriptor, name = tempfile.mkstemp(prefix=".cover-part-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.read_bytes() != data:
            raise ValueError("cover staging readback failed")
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError("cover artifact conflicts with existing content")
        if path.read_bytes() != data:
            raise ValueError("cover artifact readback failed")
    finally:
        temporary.unlink(missing_ok=True)


def inspect_images(image_path, crop_path):
    """Verify actual PNG opacity and exact same-image left square pixels."""
    from PIL import Image
    def read(path):
        path = Path(path).expanduser()
        PathBoundary(path.parent).child(path.name)
        with Image.open(path) as image:
            if image.format != "PNG" or getattr(image, "n_frames", 1) != 1:
                raise ValueError("cover requires one real PNG frame")
            if image.width * image.height > 20_000_000:
                raise ValueError("cover exceeds pixel budget")
            image.load()
            rgba = image.convert("RGBA")
            if rgba.getextrema()[3] != (255, 255):
                raise ValueError("cover must be fully opaque")
            return path.read_bytes(), rgba
    wide_bytes, wide = read(image_path)
    crop_bytes, crop = read(crop_path)
    width, height = png_size(wide_bytes)
    expected = wide.crop((0, 0, height, height))
    if crop.size != expected.size or crop.tobytes() != expected.tobytes():
        raise ValueError("crop must be actual same-image left [0,0,H,H] square")
    return {"image_sha256": digest(wide_bytes), "crop_sha256": digest(crop_bytes),
            "crop_pixels_sha256": digest(expected.tobytes()), "width": width,
            "height": height, "square_crop": [0, 0, height, height]}


def validate_visual(candidate, pixels):
    """Trace references and visual judgments are host attestations, not independent proof."""
    evidence = candidate.get("visual_evidence")
    generation = candidate.get("generation_evidence")
    if candidate.get("visual_checked") is not True or not isinstance(evidence, dict) or not isinstance(generation, dict):
        raise ValueError("actual generation and wide/crop viewing evidence are required")
    for key in ("wide_checked", "crop_checked", "all_text_readable", "style_matches"):
        if evidence.get(key) is not True:
            raise ValueError("incomplete visual evidence: " + key)
    for key, legacy in (("reviewer", "reviewer"), ("wide_trace_ref", "wide_view_call_id"), ("crop_trace_ref", "crop_view_call_id")):
        value = evidence.get(key) or evidence.get(legacy)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("missing visual trace: " + key)
    if evidence.get("image_sha256") != pixels["image_sha256"] or evidence.get("crop_pixels_sha256") != pixels["crop_pixels_sha256"]:
        raise ValueError("visual evidence is bound to another image or crop")
    trace = generation.get("trace_ref") or generation.get("call_id")
    if not isinstance(trace, str) or not trace.strip() or generation.get("tool") != candidate.get("generator") or generation.get("image_sha256") != pixels["image_sha256"]:
        raise ValueError("generation receipt does not match this PNG")
    if candidate.get("generator") not in {"image_gen.imagegen", "image_gen__imagegen", "imagegen", "openai-image-cli"}:
        raise ValueError("unsupported image generator")


def verify_record(record):
    pixels = inspect_images(record["image_path"], record["crop_path"])
    if any(record.get(key) != value for key, value in pixels.items()):
        raise ValueError("saved cover files differ from their receipt")
    validate_visual(record, pixels)
    return pixels


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
        existing, unverified = [], []
        for path in self.artifacts.boundary.child("runs", run_id).glob("cover-*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("approved_final_digest") == canonical_digest(approved) and value.get("style") == style and value.get("layout_version") == LAYOUT_VERSION:
                try:
                    verify_record(value)
                    value["currently_applied"] = bool(value.get("apply") and raw_digest == value.get("article_after_digest"))
                    existing.append(value)
                except (KeyError, OSError, ValueError) as exc:
                    unverified.append({"record": str(path), "image_path": value.get("image_path"), "reason": str(exc)})
        return {
            "run_id": run_id, "style": style, "layout_version": LAYOUT_VERSION, "square_crop_rule": "left: x=0,y=0,width=image_height,height=image_height", "title": live["title"], "body": live["body"],
            "approved_final_digest": canonical_digest(approved), "article_digest": raw_digest,
            "must_avoid": context.get("must_avoid", []),
            "profile": context.get("selected_05_profile_context", {}),
            "existing": existing, "unverified_existing": unverified, "backend": self.adapter.backend,
            "cover_required": True,
        }

    def delivery_status(self, run_id):
        """A saved article is complete only with a valid saved cover and current readback."""
        errors = []
        try:
            _, approved, _, _, live = self._load(run_id)
            current = digest(Path(live["object_ref"]).read_bytes()) if self.adapter.backend == "obsidian" else canonical_digest(live)
            for path in self.artifacts.boundary.child("runs", run_id).glob("cover-*.json"):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                    if record.get("run_id") != run_id or record.get("approved_final_digest") != canonical_digest(approved) or record.get("layout_version") != LAYOUT_VERSION or record.get("style") not in STYLES:
                        continue
                    verify_record(record)
                    if self.adapter.backend == "obsidian" and (not record.get("apply") or current != record.get("article_after_digest")):
                        continue
                    if self.adapter.backend == "feishu" and current != record.get("article_before_digest"):
                        continue
                    return {"complete": True, "cover_required": True, "image_path": record["image_path"],
                            "style": record["style"], "readback_status": "verified", "remote_inserted": False,
                            "evidence_boundary": "visual/tool judgments attested by host"}
                except (KeyError, OSError, ValueError) as exc:
                    errors.append(str(exc))
        except (OSError, ValueError, RuntimeError, ImportError) as exc:
            errors.append(str(exc))
        return {"complete": False, "cover_required": True, "reason": "valid_saved_cover_required", "errors": errors}

    def save(self, run_id, candidate):
        directory = self.artifacts.boundary.child("runs", run_id)
        with (directory / ".cover.lock").open("a") as lock:
            with exclusive_lock(lock):
                return self._save(run_id, candidate, directory)

    def _save(self, run_id, candidate, directory):
        style = candidate.get("style")
        if style not in STYLES or candidate.get("visual_checked") is not True:
            raise ValueError("one supported style and actual visual check are required")
        if candidate.get("layout_version") != LAYOUT_VERSION:
            raise ValueError("cover requires the current square-title layout and crop check")
        for key in ("cover_title", "prompt", "generator", "image_path", "crop_path", "article_digest"):
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
        pixels = inspect_images(candidate["image_path"], candidate["crop_path"])
        validate_visual(candidate, pixels)
        data = Path(candidate["image_path"]).expanduser().read_bytes()
        crop_data = Path(candidate["crop_path"]).expanduser().read_bytes()
        image_hash = pixels["image_sha256"]
        width, height = pixels["width"], pixels["height"]
        key = canonical_digest([approved_hash, style, candidate["prompt"], candidate["cover_title"], image_hash, apply, LAYOUT_VERSION, "pixel-evidence-v1"])[:24]
        record_path = directory / f"cover-{key}.json"
        article = Path(live["object_ref"]) if self.adapter.backend == "obsidian" else None
        raw = article.read_bytes() if article else None
        current = digest(raw) if raw is not None else canonical_digest(live)
        record = None
        if record_path.exists():
            record = json.loads(record_path.read_text(encoding="utf-8"))
            verify_record(record)
            if any(record.get(name) != value for name, value in pixels.items()):
                raise ValueError("candidate differs from existing cover receipt")
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
            requested = Path(candidate.get("asset_directory") or default).expanduser()
            if not requested.is_absolute():
                requested = root / requested
            target_dir = PathBoundary(requested).root
            if record is not None:
                # A retry may omit the original custom directory; preserve the recorded target.
                recorded_dir = PathBoundary(Path(record["image_path"]).parent).root
                if candidate.get("asset_directory") and target_dir != recorded_dir:
                    raise ValueError("retry asset directory differs from existing cover record")
                target_dir = recorded_dir
            if not target_dir.is_relative_to(root) or any(is_protected_segment(x) for x in target_dir.relative_to(root).parts):
                raise ValueError("cover asset directory escapes output boundaries")
        else:
            target_dir = directory
        target = target_dir / f"cover-{style}-{key}.png"
        PathBoundary(target_dir).child(target.name)
        crop_target = directory / f"cover-{style}-{key}-crop.png"
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
            "generation_evidence": candidate["generation_evidence"], "visual_evidence": candidate["visual_evidence"],
            "crop_path": str(crop_target), "crop_sha256": pixels["crop_sha256"],
            "crop_pixels_sha256": pixels["crop_pixels_sha256"],
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
        create_once(target, data)
        create_once(crop_target, crop_data)
        if digest(target.read_bytes()) != image_hash:
            raise ValueError("cover image readback failed")
        atomic_write(record_path, (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
        if apply:
            article_lock_path = article.with_name(f".{article.name}.content-gzh.lock")
            with article_lock_path.open("a") as article_lock:
                with exclusive_lock(article_lock):
                    if digest(article.read_bytes()) != current:
                        raise ValueError("article changed during cover save")
                    atomic_write(article, updated)
            SaveService._verify_readback(approved, receipt["target"], self.adapter.read_back(receipt["target"]))
            result["applied"] = True
            atomic_write(record_path, (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
        return {"cover": result, "resumed": False}

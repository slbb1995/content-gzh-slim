"""Real content-source-v1 resolution for Obsidian and Feishu knowledge bases."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .contracts import validate_task_input


CONTRACT_VERSION = "content-source-v1"
WORKFLOW = "content-gzh-slim"
MANIFEST_RELATIVE = "06-Agent与Workflow/content-source-manifest.json"
PROFILE_INDEX_RELATIVE = "06-Agent与Workflow/content-profile-index.json"
PROFILE_ID = re.compile(r"^PRF-[A-F0-9]{16}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CREDENTIAL_KEYS = {
    "token", "cookie", "password", "access" + "_token", "refresh" + "_token",
    "secret", "api_key", "apikey", "authorization", "credential", "session",
}


class ContentSourceError(RuntimeError):
    """Raised when a real source cannot be resolved and frozen safely."""


def _lark_cli_environment() -> dict[str, str]:
    """Avoid inheriting the known dead local proxy while retaining valid proxies."""
    environment = dict(os.environ)
    for name in (
        "ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "GIT_HTTP_PROXY", "GIT_HTTPS_PROXY",
        "all_proxy", "http_proxy", "https_proxy", "git_http_proxy", "git_https_proxy",
    ):
        value = environment.get(name)
        if not value:
            continue
        try:
            parsed = urlsplit(value)
            is_dead_proxy = parsed.hostname in {"127.0.0.1", "localhost", "::1"} and parsed.port == 9
        except ValueError:
            is_dead_proxy = False
        if is_dead_proxy:
            environment.pop(name, None)
    return environment


def default_registry_path() -> Path:
    configured = os.environ.get("CODEX_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return root / ".content-workflows" / "knowledge-base-registry.json"


def default_runs_root() -> Path:
    configured = os.environ.get("CODEX_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return root / ".content-gzh-slim" / "runs"


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable_ref(prefix: str, *parts: str) -> str:
    return f"{prefix}://{hashlib.sha256(chr(10).join(parts).encode()).hexdigest()[:24]}"


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{hashlib.sha256(chr(10).join(parts).encode()).hexdigest()[:16].upper()}"


def _relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ContentSourceError(f"{field} must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ContentSourceError(f"{field} escapes the knowledge base")
    return path.as_posix()


def _no_credentials(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold().replace("-", "_") in _CREDENTIAL_KEYS:
                raise ContentSourceError("locator must not contain credentials")
            _no_credentials(child)
    elif isinstance(value, list):
        for child in value:
            _no_credentials(child)
    elif isinstance(value, str):
        parsed = urlsplit(value)
        pairs = (*parse_qsl(parsed.query, keep_blank_values=True), *parse_qsl(parsed.fragment, keep_blank_values=True))
        if any(key.casefold().replace("-", "_") in _CREDENTIAL_KEYS for key, _ in pairs):
            raise ContentSourceError("locator URL must not contain credentials")


def _read_regular(path: Path) -> tuple[bytes, str]:
    if path.is_symlink() or not path.is_file():
        raise ContentSourceError(f"source is not a regular file: {path}")
    raw = path.read_bytes()
    return raw, _digest(raw)


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    raw, digest = _read_regular(path)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContentSourceError(f"JSON source is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ContentSourceError(f"JSON source is not an object: {path}")
    return value, digest


def validate_registry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"contract_version", "bindings", "workflow_defaults", "revision"}:
        raise ContentSourceError("content-source Registry fields are invalid")
    if value["contract_version"] != CONTRACT_VERSION or not isinstance(value["bindings"], dict):
        raise ContentSourceError("content-source Registry version or bindings are invalid")
    for binding_id, binding in value["bindings"].items():
        fields = {"binding_id", "client_id", "knowledge_base_id", "backend", "locator", "manifest_ref", "profile_index_ref", "supported_workflows", "workflow_defaults", "status"}
        if not isinstance(binding, dict) or set(binding) != fields or binding.get("binding_id") != binding_id:
            raise ContentSourceError("content-source Registry binding is invalid")
        if binding["backend"] not in {"obsidian", "feishu"} or binding["status"] not in {"active", "disabled"}:
            raise ContentSourceError("content-source binding backend or status is invalid")
        if not isinstance(binding["locator"], dict) or not binding["locator"]:
            raise ContentSourceError("content-source binding locator is invalid")
        _no_credentials(binding["locator"])
        if not isinstance(binding["supported_workflows"], list) or not isinstance(binding["workflow_defaults"], dict):
            raise ContentSourceError("content-source binding workflow fields are invalid")
        for default in binding["workflow_defaults"].values():
            if not isinstance(default, dict) or set(default) != {"profile_id", "use_no_ip"}:
                raise ContentSourceError("content-source workflow default entry is invalid")
            if not isinstance(default["use_no_ip"], bool) or default["use_no_ip"] and default["profile_id"] is not None:
                raise ContentSourceError("content-source workflow default IP policy is invalid")
    defaults = value["workflow_defaults"]
    if not isinstance(defaults, dict):
        raise ContentSourceError("content-source workflow defaults are invalid")
    for workflow, binding_id in defaults.items():
        if binding_id not in value["bindings"] or workflow not in value["bindings"][binding_id]["supported_workflows"]:
            raise ContentSourceError("content-source workflow default is invalid")
    return value


def validate_manifest(value: Any, *, binding: dict[str, Any] | None = None) -> dict[str, Any]:
    fields = {"contract_version", "knowledge_base_id", "client_id", "knowledge_base_name", "backend", "locator", "asset_roots", "profile_index_ref", "workflow_outputs", "supported_workflows", "revision"}
    if not isinstance(value, dict) or set(value) != fields or value["contract_version"] != CONTRACT_VERSION:
        raise ContentSourceError("content-source Manifest fields or version are invalid")
    if value["backend"] not in {"obsidian", "feishu"} or WORKFLOW not in value["supported_workflows"]:
        raise ContentSourceError("Manifest does not support content-gzh-slim")
    _no_credentials(value["locator"])
    roots = value["asset_roots"]
    if not isinstance(roots, dict) or set(roots) != {"knowledge", "content", "profiles", "workflow", "output"}:
        raise ContentSourceError("Manifest asset roots are invalid")
    if value["backend"] == "obsidian":
        for key, child in roots.items():
            _relative(child, f"asset_roots.{key}")
        _relative(value["profile_index_ref"], "profile_index_ref")
    elif any(not isinstance(child, str) or not child.strip() for child in roots.values()):
        raise ContentSourceError("Feishu asset root refs are invalid")
    outputs = value["workflow_outputs"]
    if not isinstance(outputs, dict) or WORKFLOW not in outputs:
        raise ContentSourceError("Manifest has no公众号 output template")
    if value["backend"] == "obsidian":
        _relative(outputs[WORKFLOW], "workflow output")
    elif not isinstance(outputs[WORKFLOW], str) or not outputs[WORKFLOW].strip():
        raise ContentSourceError("Feishu workflow output ref is invalid")
    if binding and any(value.get(key) != binding.get(key) for key in ("client_id", "knowledge_base_id", "backend")):
        raise ContentSourceError("Registry and Manifest identities differ")
    return value


def validate_profile_index(value: Any, knowledge_base_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"contract_version", "knowledge_base_id", "profiles", "revision"}:
        raise ContentSourceError("Profile index fields are invalid")
    if value["contract_version"] != CONTRACT_VERSION or value["knowledge_base_id"] != knowledge_base_id:
        raise ContentSourceError("Profile index belongs to another knowledge base")
    if not isinstance(value["profiles"], list):
        raise ContentSourceError("Profile index profiles must be a list")
    seen: set[str] = set()
    aliases: dict[str, str] = {}
    primary = 0
    for profile in value["profiles"]:
        fields = {"profile_id", "display_name", "aliases", "object_ref", "status", "is_primary", "content_sha256"}
        if not isinstance(profile, dict) or set(profile) != fields:
            raise ContentSourceError("Profile index entry fields are invalid")
        profile_id = profile["profile_id"]
        if not isinstance(profile_id, str) or not PROFILE_ID.fullmatch(profile_id) or profile_id in seen:
            raise ContentSourceError("Profile id is invalid or duplicated")
        seen.add(profile_id)
        if profile["status"] not in {"active", "disabled"} or not isinstance(profile["is_primary"], bool):
            raise ContentSourceError("Profile status is invalid")
        if not isinstance(profile["display_name"], str) or not profile["display_name"].strip():
            raise ContentSourceError("Profile display name is invalid")
        if not isinstance(profile["aliases"], list) or any(not isinstance(alias, str) or not alias.strip() for alias in profile["aliases"]):
            raise ContentSourceError("Profile aliases are invalid")
        if not isinstance(profile["object_ref"], str) or not profile["object_ref"].strip() or not HEX64.fullmatch(str(profile["content_sha256"])):
            raise ContentSourceError("Profile object ref or hash is invalid")
        if profile["status"] == "active":
            primary += int(profile["is_primary"])
            for name in (profile["display_name"], *profile["aliases"]):
                folded = name.casefold()
                if folded in aliases and aliases[folded] != profile_id:
                    raise ContentSourceError("active Profile name or alias is ambiguous")
                aliases[folded] = profile_id
    if primary > 1:
        raise ContentSourceError("more than one active Profile is primary")
    return value


class LarkContentSourceClient:
    def __init__(self, *, binary: str | None = None, identity: str = "user") -> None:
        resolved = binary or shutil.which("lark-cli")
        if not resolved:
            raise ContentSourceError("lark-cli is not installed")
        if identity not in {"user", "bot"}:
            raise ContentSourceError("lark identity is invalid")
        self.binary = resolved
        self.identity = identity

    @staticmethod
    def _json(output: str) -> dict[str, Any]:
        decoder = json.JSONDecoder()
        for index, character in enumerate(output):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(output[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                data = value.get("data", value)
                return data if isinstance(data, dict) else value
        raise ContentSourceError("lark-cli returned no JSON object")

    def _call(self, arguments: list[str]) -> dict[str, Any]:
        completed = subprocess.run(
            [self.binary, "--as", self.identity, "--format", "json", *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=_lark_cli_environment(),
        )
        if completed.returncode != 0:
            raise ContentSourceError(f"lark-cli read failed: {(completed.stderr or completed.stdout).strip()}")
        return self._json(completed.stdout)

    def fetch_markdown(self, object_ref: str) -> str:
        document = self._call(["docs", "+fetch", "--api-version", "v2", "--doc", object_ref, "--doc-format", "markdown", "--detail", "simple"]).get("document", {})
        content = document.get("content") if isinstance(document, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ContentSourceError("Feishu document contains no Markdown")
        return content.replace("\r\n", "\n").strip() + "\n"

    def list_children(self, *, space_id: str, parent_node_token: str) -> list[dict[str, Any]]:
        data = self._call(["wiki", "nodes", "list", "--space-id", space_id, "--parent-node-token", parent_node_token, "--page-all"])
        items = data.get("items") or []
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ContentSourceError("Feishu child list is invalid")
        return items

    def list_roots(self, *, space_id: str) -> list[dict[str, Any]]:
        data = self._call(["wiki", "nodes", "list", "--space-id", space_id, "--page-all"])
        items = data.get("items") or []
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ContentSourceError("Feishu root list is invalid")
        return items

    def resolve_space_id(self, locator: str) -> str:
        try:
            return _space_id(locator)
        except ContentSourceError:
            parts = [part for part in urlsplit(locator).path.split("/") if part]
            if len(parts) != 2 or parts[0] != "wiki":
                raise
            data = self._call(["wiki", "spaces", "get_node", "--params", json.dumps({"token": parts[1]}, separators=(",", ":"))])
            node = data.get("node", {})
            space_id = node.get("space_id") if isinstance(node, dict) else None
            if not isinstance(space_id, str) or not space_id:
                raise ContentSourceError("Feishu Wiki node could not resolve a space_id")
            return space_id


def _json_from_markdown(text: str) -> dict[str, Any]:
    match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    candidate = match.group(1) if match else text.lstrip()
    if not match and candidate.startswith("# "):
        candidate = "\n".join(candidate.splitlines()[1:]).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ContentSourceError("Feishu contract document contains invalid JSON") from exc
    if not isinstance(value, dict):
        raise ContentSourceError("Feishu contract JSON must be an object")
    return value


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        return {}, normalized
    end = normalized.find("\n---\n", 4)
    if end < 0:
        raise ContentSourceError("Markdown frontmatter is not closed")
    metadata: dict[str, Any] = {}
    active: str | None = None
    for line in normalized[4:end].splitlines():
        item = re.fullmatch(r"\s*-\s+(.+?)\s*", line)
        if item and active:
            metadata[active].append(_scalar(item.group(1)))
            continue
        pair = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*):\s*(.*?)\s*", line)
        if not pair:
            active = None
            continue
        key, raw = pair.groups()
        value = _scalar(raw)
        if value is None:
            metadata[key] = []
            active = key
        else:
            metadata[key] = value
            active = None
    return metadata, normalized[end + 5 :]


def _scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return None
    if value in {"true", "false", "null"}:
        return {"true": True, "false": False, "null": None}[value]
    if value.startswith(("[", "{", '"')):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    return value.strip("'")


def _title(metadata: dict[str, Any], body: str, fallback: str) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", body)
    return str(metadata.get("title") or (match.group(1) if match else fallback)).strip()


def _excerpt(body: str, limit: int = 1200) -> str:
    clean = re.sub(r"(?m)^#{1,6}\s+", "", body).strip()
    return clean[:limit].rstrip()


def _keywords(metadata: dict[str, Any], title: str) -> list[str]:
    value = metadata.get("keywords")
    if isinstance(value, list):
        result = [str(item).strip() for item in value if str(item).strip()]
    else:
        result = []
    return result or [part for part in re.split(r"[\s、，,：:]+", title) if len(part) >= 2][:6] or [title]


def _profile_payload(profile: dict[str, Any], text: str, ref: str) -> dict[str, Any]:
    _metadata, body = _split_frontmatter(text)
    section_type = "identity_fact"
    typed_fragments: list[tuple[str, str]] = []
    section_aliases = (
        (("表达方式", "表达风格", "语言风格", "说话方式"), "expression_style"),
        (("专业判断", "核心观点", "稳定判断", "价值判断"), "professional_judgment"),
        (("读者连接", "读者理解", "用户理解", "客户理解"), "reader_empathy"),
        (("业务边界", "表达边界", "事实边界", "承诺边界", "禁区"), "business_boundary"),
        (("真实经历", "确认经历", "个人经历"), "experience_fact"),
        (("确认事实", "身份", "定位", "基本信息"), "identity_fact"),
    )
    per_type_counts: dict[str, int] = {}
    for line in body.splitlines():
        heading = re.fullmatch(r"\s*#{2,6}\s+(.+?)\s*", line)
        if heading:
            title = heading.group(1).strip()
            section_type = next(
                (
                    fragment_type
                    for aliases, fragment_type in section_aliases
                    if any(alias in title for alias in aliases)
                ),
                "identity_fact",
            )
            continue
        bullet = re.fullmatch(r"\s*-\s+(.+?)\s*", line)
        if not bullet:
            continue
        if per_type_counts.get(section_type, 0) >= 4 or len(typed_fragments) >= 20:
            continue
        typed_fragments.append((section_type, bullet.group(1).strip()))
        per_type_counts[section_type] = per_type_counts.get(section_type, 0) + 1

    grouped: dict[str, list[str]] = {}
    for fragment_type, value in typed_fragments:
        grouped.setdefault(fragment_type, []).append(value)

    def joined(fragment_type: str, fallback: str = "") -> str:
        values = grouped.get(fragment_type, [])
        return "；".join(values) if values else fallback

    anchors = {
        "identity": profile["display_name"],
        "confirmed_profile": joined("identity_fact", "仅确认名称，暂无可靠个人事实"),
        "expression_style": joined("expression_style"),
        "professional_judgments": joined("professional_judgment"),
        "reader_empathy": joined("reader_empathy"),
        "business_boundary": joined("business_boundary", "不得补造个人经历、案例或结果"),
        "style_boundary": joined("business_boundary", "不得补造个人经历、案例或结果"),
    }
    fragments = [
        {
            "fragment_id": hashlib.sha256(f"{profile['profile_id']}\n{index}\n{text_value}".encode()).hexdigest()[:16],
            "fragment_type": fragment_type,
            "text": text_value,
            "status": "confirmed",
        }
        for index, (fragment_type, text_value) in enumerate(typed_fragments, 1)
    ]
    return {
        "name": profile["display_name"],
        "ref": ref,
        "status": "full" if len(typed_fragments) >= 3 else "limited",
        "anchors": anchors,
        "confirmed_fragments": fragments,
    }


def _select_profile(index: dict[str, Any], requested: str | None, configured: Any) -> dict[str, Any] | None:
    active = [item for item in index["profiles"] if item["status"] == "active"]
    if requested in {"none", "无IP"}:
        return None
    if requested:
        folded = requested.casefold()
        matches = [item for item in active if folded in {item["profile_id"].casefold(), item["display_name"].casefold(), *(alias.casefold() for alias in item["aliases"])}]
        return matches[0] if len(matches) == 1 else None
    if isinstance(configured, dict) and "profile_id" in configured:
        if configured.get("use_no_ip") is True:
            return None
        profile_id = configured["profile_id"]
        if profile_id is not None:
            matches = [item for item in active if item["profile_id"] == profile_id]
            if len(matches) == 1:
                return matches[0]
            raise ContentSourceError("configured default IP is unavailable")
    primary = [item for item in active if item["is_primary"]]
    if len(primary) == 1:
        return primary[0]
    if len(active) == 1:
        return active[0]
    raise ContentSourceError("multiple active IP Profiles require an explicit selection")


def _select_binding(registry: dict[str, Any], requested: str | None) -> dict[str, Any]:
    active = [binding for binding in registry["bindings"].values() if binding["status"] == "active" and WORKFLOW in binding["supported_workflows"]]
    if requested:
        matches = [binding for binding in active if requested in {binding["binding_id"], binding["client_id"], binding["knowledge_base_id"], *binding["locator"].values()}]
        if len(matches) != 1:
            raise ContentSourceError("knowledge base does not resolve to one content-gzh-slim binding")
        return matches[0]
    default_id = registry["workflow_defaults"].get(WORKFLOW)
    matches = [binding for binding in active if binding["binding_id"] == default_id]
    if len(matches) == 1:
        return matches[0]
    if len(active) == 1:
        return active[0]
    raise ContentSourceError("multiple or zero knowledge-base bindings require an explicit selection")


def _safe_obsidian_path(vault: Path, relative: str) -> Path:
    root = vault.resolve(strict=True)
    current = root
    for part in PurePosixPath(_relative(relative, "object_ref")).parts:
        current /= part
        if current.is_symlink():
            raise ContentSourceError("Obsidian source path contains a symlink")
    resolved = current.resolve(strict=True)
    resolved.relative_to(root)
    return resolved


def _search_score(title: str, keywords: list[str], query: str) -> int:
    folded = query.casefold()
    score = 0
    for keyword in {title, *keywords}:
        candidate = keyword.casefold().strip()
        if not candidate:
            continue
        if candidate in folded:
            score += 4
            continue
        score += sum(1 for index in range(max(0, len(candidate) - 1)) if candidate[index : index + 2] in folded)
    return score


def _obsidian_documents(vault: Path, relative_root: str, *, query: str, limit: int) -> list[tuple[str, str, str]]:
    root = _safe_obsidian_path(vault, relative_root)
    if not root.is_dir():
        raise ContentSourceError("Manifest asset root is not a directory")
    ranked: list[tuple[int, str, Path]] = []
    for path in sorted(root.rglob("*.md")):
        if path.is_symlink() or not path.is_file():
            raise ContentSourceError("Obsidian source path is unsafe")
        try:
            with path.open("r", encoding="utf-8") as handle:
                prefix = handle.read(32768)
        except (OSError, UnicodeError) as exc:
            raise ContentSourceError("Obsidian source metadata is unreadable") from exc
        metadata, body = _split_frontmatter(prefix)
        title = _title(metadata, body, path.stem)
        score = _search_score(title, _keywords(metadata, title), query)
        if score:
            ranked.append((score, path.relative_to(vault).as_posix(), path))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    documents = []
    for _score, relative, path in ranked[:limit]:
        raw, digest = _read_regular(path)
        documents.append((relative, raw.decode("utf-8"), digest))
    return documents


def _space_id(locator: str) -> str:
    parts = [part for part in urlsplit(locator).path.split("/") if part]
    if len(parts) == 3 and parts[:2] == ["wiki", "space"] and parts[2].isdigit():
        return parts[2]
    raise ContentSourceError("Feishu locator must be a stable wiki space URL")


def _feishu_documents(client: LarkContentSourceClient, *, space_id: str, parent_ref: str, query: str, limit: int, max_depth: int = 2) -> list[tuple[str, str, str]]:
    documents = []
    nodes = []
    pending = [(parent_ref, 0)]
    visited = {parent_ref}
    while pending:
        current_ref, current_depth = pending.pop(0)
        for node in client.list_children(space_id=space_id, parent_node_token=current_ref):
            node_depth = current_depth + 1
            has_child = node.get("has_child") is True
            node_ref = node.get("node_token")
            if has_child and node_depth < max_depth and isinstance(node_ref, str) and node_ref not in visited:
                visited.add(node_ref)
                pending.append((node_ref, node_depth))
            if has_child or node.get("obj_type") != "docx" or not isinstance(node.get("obj_token"), str):
                continue
            title = str(node.get("title") or "")
            score = _search_score(title, [title], query)
            if score:
                nodes.append((score, title, node))
    nodes.sort(key=lambda item: (-item[0], item[1]))
    for _score, _title_value, node in nodes[:limit]:
        token = node["obj_token"]
        text = client.fetch_markdown(token)
        documents.append((token, text, _digest(text.encode("utf-8"))))
    return documents


def _asset_catalog(documents: list[tuple[str, str, str]], *, backend: str, role: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    business: list[dict[str, Any]] = []
    peer: list[dict[str, Any]] = []
    methods: list[dict[str, Any]] = []
    objects: list[dict[str, str]] = []
    for object_ref, text, digest in documents:
        metadata, body = _split_frontmatter(text)
        title = _title(metadata, body, Path(object_ref).stem)
        ref = _stable_ref(backend, object_ref, digest)
        objects.append({"backend": backend, "object_ref": object_ref, "content_sha256": digest})
        if role == "03":
            status = metadata.get("status", "confirmed")
            business.append({"ref": ref, "title": title, "keywords": _keywords(metadata, title), "excerpt": _excerpt(body), "fact_status": "confirmed" if status in {"active", "confirmed"} else "candidate", "content_sha256": digest})
            continue
        asset_type = metadata.get("type")
        workflows = metadata.get("applicable_workflows", [])
        if asset_type in {"benchmark_deconstruction", "peer_content_asset"}:
            target = peer
        elif asset_type == "content_method_asset" and isinstance(workflows, list) and WORKFLOW in workflows:
            target = methods
        else:
            continue
        target.append({"ref": ref, "title": title, "keywords": _keywords(metadata, title), "excerpt": _excerpt(body), "content_sha256": digest})
    return business, peer, methods, objects


def resolve_real_source(
    raw_task: dict[str, Any],
    *,
    registry_path: str | Path | None = None,
    lark_binary: str | None = None,
    lark_identity: str = "user",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Resolve defaults, read 05→03→04, and return one frozen catalog/snapshot."""

    if not isinstance(raw_task, dict):
        raise ContentSourceError("task input must be an object")
    requested_kb = raw_task.get("knowledge_base")
    requested_ip = raw_task.get("ip")
    registry_file = Path(registry_path) if registry_path else default_registry_path()
    registry = None
    registry_digest = None
    binding = None
    if registry_file.exists():
        registry, registry_digest = _read_json(registry_file)
        validate_registry(registry)
        try:
            binding = _select_binding(registry, requested_kb if isinstance(requested_kb, str) and requested_kb.strip() else None)
        except ContentSourceError:
            if not (
                isinstance(requested_kb, str)
                and (Path(requested_kb).is_absolute() or requested_kb.startswith("https://"))
            ):
                raise
    client: LarkContentSourceClient | None = None
    if binding is None:
        if not isinstance(requested_kb, str) or not requested_kb.strip():
            raise ContentSourceError("knowledge_base is required when no default binding exists")
        if requested_kb.startswith("https://"):
            client = LarkContentSourceClient(binary=lark_binary, identity=lark_identity)
            manifest_ref, profile_ref = _feishu_contract_refs(client, requested_kb)
            discovered = _json_from_markdown(client.fetch_markdown(manifest_ref))
            validate_manifest(discovered)
            binding = {
                "binding_id": _stable_id("BND", discovered["client_id"], discovered["knowledge_base_id"]),
                "client_id": discovered["client_id"],
                "knowledge_base_id": discovered["knowledge_base_id"],
                "backend": "feishu",
                "locator": {"knowledge_base_ref": requested_kb},
                "manifest_ref": manifest_ref,
                "profile_index_ref": profile_ref,
                "supported_workflows": [WORKFLOW],
                "workflow_defaults": {},
                "status": "active",
            }
        else:
            candidate = Path(requested_kb).expanduser()
            if not candidate.is_absolute() or candidate.is_symlink() or not candidate.is_dir():
                raise ContentSourceError("standalone real mode requires an absolute compatible Obsidian path or Feishu space URL")
            vault = candidate.resolve(strict=True)
            manifest_path = vault / MANIFEST_RELATIVE
            manifest, manifest_digest = _read_json(manifest_path)
            validate_manifest(manifest)
            binding = {
                "binding_id": _stable_id("BND", manifest["client_id"], manifest["knowledge_base_id"]),
                "client_id": manifest["client_id"],
                "knowledge_base_id": manifest["knowledge_base_id"],
                "backend": "obsidian",
                "locator": {"vault_root": str(vault)},
                "manifest_ref": MANIFEST_RELATIVE,
                "profile_index_ref": manifest["profile_index_ref"],
                "supported_workflows": [WORKFLOW],
                "workflow_defaults": {},
                "status": "active",
            }
    backend = binding["backend"]
    if backend == "obsidian":
        vault = Path(binding["locator"]["vault_root"])
        if not vault.is_absolute() or vault.is_symlink() or not vault.is_dir():
            raise ContentSourceError("Obsidian binding root is unsafe or missing")
        vault = vault.resolve(strict=True)
        manifest_path = _safe_obsidian_path(vault, binding["manifest_ref"])
        manifest, manifest_digest = _read_json(manifest_path)
        validate_manifest(manifest, binding=binding)
        index_path = _safe_obsidian_path(vault, binding["profile_index_ref"])
        profile_index, index_digest = _read_json(index_path)
        validate_profile_index(profile_index, manifest["knowledge_base_id"])
    else:
        client = LarkContentSourceClient(binary=lark_binary, identity=lark_identity)
        locator = binding["locator"].get("knowledge_base_ref")
        if not isinstance(locator, str):
            raise ContentSourceError("Feishu binding has no knowledge_base_ref")
        space_id = client.resolve_space_id(locator)
        manifest_text = client.fetch_markdown(binding["manifest_ref"])
        manifest_digest = _digest(manifest_text.encode("utf-8"))
        manifest = _json_from_markdown(manifest_text)
        validate_manifest(manifest, binding=binding)
        index_text = client.fetch_markdown(binding["profile_index_ref"])
        index_digest = _digest(index_text.encode("utf-8"))
        profile_index = _json_from_markdown(index_text)
        validate_profile_index(profile_index, manifest["knowledge_base_id"])

    configured = binding.get("workflow_defaults", {}).get(WORKFLOW)
    normalized_ip = None
    if isinstance(requested_ip, str) and requested_ip.strip():
        normalized_ip = "none" if requested_ip.strip() in {"none", "无IP"} else requested_ip.strip()
    profile = _select_profile(profile_index, normalized_ip, configured)
    if normalized_ip not in {None, "none"} and profile is None:
        canonical_ip = normalized_ip
        ip_identity = {"requested_name": canonical_ip, "resolved_ref": None, "status": "unused", "profile_id": None}
        profile_catalog = []
        profile_objects: list[dict[str, str]] = []
    elif profile is None:
        canonical_ip = "none"
        ip_identity = {"requested_name": "none", "resolved_ref": None, "status": "none", "profile_id": None}
        profile_catalog = []
        profile_objects = []
    else:
        canonical_ip = profile["display_name"]
        if backend == "obsidian":
            profile_path = _safe_obsidian_path(vault, profile["object_ref"])
            raw_profile, actual_hash = _read_regular(profile_path)
            profile_text = raw_profile.decode("utf-8")
            profile_object_ref = profile_path.relative_to(vault).as_posix()
        else:
            profile_text = client.fetch_markdown(profile["object_ref"])
            actual_hash = _digest(profile_text.encode("utf-8"))
            profile_object_ref = profile["object_ref"]
        if actual_hash != profile["content_sha256"]:
            raise ContentSourceError("selected Profile hash differs from the Profile index")
        resolved_profile_ref = _stable_ref(backend, profile_object_ref, actual_hash)
        payload = _profile_payload(profile, profile_text, resolved_profile_ref)
        profile_catalog = [payload]
        profile_objects = [{"backend": backend, "object_ref": profile_object_ref, "content_sha256": actual_hash}]
        ip_identity = {"requested_name": canonical_ip, "resolved_ref": resolved_profile_ref, "status": payload["status"], "profile_id": profile["profile_id"]}

    query = " ".join(
        str(value or "")
        for value in (
            raw_task.get("topic"),
            raw_task.get("user_thoughts"),
            raw_task.get("target_audience_override"),
            profile_catalog[0]["anchors"] if profile_catalog else "",
        )
    )
    if backend == "obsidian":
        documents_03 = _obsidian_documents(vault, manifest["asset_roots"]["knowledge"], query=query, limit=5)
        documents_04 = _obsidian_documents(vault, manifest["asset_roots"]["content"], query=query, limit=5)
    else:
        documents_03 = _feishu_documents(client, space_id=space_id, parent_ref=manifest["asset_roots"]["knowledge"], query=query, limit=5, max_depth=1)
        documents_04 = _feishu_documents(client, space_id=space_id, parent_ref=manifest["asset_roots"]["content"], query=query, limit=5, max_depth=2)
    business, _unused_peer, _unused_method, objects_03 = _asset_catalog(documents_03, backend=backend, role="03")
    _unused_business, peer, methods, objects_04 = _asset_catalog(documents_04, backend=backend, role="04")

    references = []
    reference_objects = []
    rewritten_refs = []
    for raw_ref in raw_task.get("references") or []:
        path = Path(raw_ref).expanduser()
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ContentSourceError("real explicit references must be absolute regular local text or Markdown files")
        raw, digest = _read_regular(path)
        try:
            content = raw.decode("utf-8")
        except UnicodeError as exc:
            raise ContentSourceError("real explicit reference is not UTF-8 text") from exc
        ref = _stable_ref("reference", str(path.resolve()), digest)
        rewritten_refs.append(ref)
        references.append({"ref": ref, "title": path.stem, "source_type": "local_full_text", "completeness": "full", "content": content.strip(), "content_sha256": digest})
        reference_objects.append({"backend": "local", "object_ref": str(path.resolve()), "content_sha256": digest})

    completed = dict(raw_task)
    completed["knowledge_base"] = binding["knowledge_base_id"]
    completed["ip"] = canonical_ip
    completed["references"] = rewritten_refs
    task = validate_task_input(completed)
    source_ref = _stable_ref("content-source", binding["knowledge_base_id"], manifest_digest)
    knowledge_base_identity = {
        "backend": backend,
        "ref": source_ref,
        "manifest_revision": f"r{manifest['revision']}:{manifest_digest}",
        "binding_id": binding["binding_id"],
        "knowledge_base_id": binding["knowledge_base_id"],
    }
    save_target_ref = "content-source-output"
    catalog = {
        "fixture_version": 3,
        "knowledge_bases": [{
            "alias": binding["knowledge_base_id"],
            "backend": backend,
            "ref": source_ref,
            "manifest_revision": knowledge_base_identity["manifest_revision"],
            "ips": {item["name"]: item["ref"] for item in profile_catalog},
            "profiles": profile_catalog,
            "business_assets": business,
            "peer_content_assets": peer,
            "content_method_assets": methods,
            "save_target": {"backend": backend, "target_ref": save_target_ref, "status": "preview_only_not_writable"},
        }],
        "references": references,
    }
    snapshot = {
        "contract_version": "content-gzh-source-snapshot-v1",
        "backend": backend,
        "binding_id": binding["binding_id"],
        "knowledge_base_id": binding["knowledge_base_id"],
        "registry_path": str(registry_file.resolve()) if registry is not None else None,
        "registry_sha256": registry_digest,
        "manifest_ref": str(manifest_path) if backend == "obsidian" else binding["manifest_ref"],
        "manifest_sha256": manifest_digest,
        "profile_index_ref": str(index_path) if backend == "obsidian" else binding["profile_index_ref"],
        "profile_index_sha256": index_digest,
        "knowledge_base_locator": str(vault) if backend == "obsidian" else binding["locator"]["knowledge_base_ref"],
        "output_locator": manifest["asset_roots"]["output"],
        "output_template": manifest["workflow_outputs"][WORKFLOW],
        "save_target_ref": save_target_ref,
        "objects": [*profile_objects, *objects_03, *objects_04, *reference_objects],
    }
    knowledge_base_identity["source_snapshot_sha256"] = "sha256:" + _digest(_canonical(snapshot))
    return task, knowledge_base_identity, ip_identity, catalog, snapshot


def verify_source_snapshot(snapshot: dict[str, Any], *, lark_binary: str | None = None, lark_identity: str = "user") -> None:
    if snapshot.get("contract_version") != "content-gzh-source-snapshot-v1":
        raise ContentSourceError("source snapshot is invalid")
    registry_path = snapshot.get("registry_path")
    if registry_path:
        raw, digest = _read_regular(Path(registry_path))
        if digest != snapshot.get("registry_sha256"):
            raise ContentSourceError("Registry changed after Gate A")
        validate_registry(json.loads(raw.decode("utf-8")))
    backend = snapshot.get("backend")
    if backend == "obsidian":
        for key in ("manifest", "profile_index"):
            _raw, digest = _read_regular(Path(snapshot[f"{key}_ref"]))
            if digest != snapshot[f"{key}_sha256"]:
                raise ContentSourceError(f"{key} changed after Gate A")
        for item in snapshot.get("objects", []):
            if item.get("backend") not in {"obsidian", "local"}:
                continue
            path = Path(item["object_ref"])
            if item["backend"] == "obsidian":
                path = Path(snapshot["knowledge_base_locator"]) / path
            _raw, digest = _read_regular(path)
            if digest != item.get("content_sha256"):
                raise ContentSourceError("a frozen source changed after Gate A")
        return
    if backend != "feishu":
        raise ContentSourceError("source snapshot backend is invalid")
    client = LarkContentSourceClient(binary=lark_binary, identity=lark_identity)
    for key in ("manifest", "profile_index"):
        text = client.fetch_markdown(snapshot[f"{key}_ref"])
        if _digest(text.encode("utf-8")) != snapshot[f"{key}_sha256"]:
            raise ContentSourceError(f"Feishu {key} changed after Gate A")
    for item in snapshot.get("objects", []):
        if item.get("backend") == "local":
            _raw, digest = _read_regular(Path(item["object_ref"]))
        elif item.get("backend") == "feishu":
            digest = _digest(client.fetch_markdown(item["object_ref"]).encode("utf-8"))
        else:
            continue
        if digest != item.get("content_sha256"):
            raise ContentSourceError("a frozen source changed after Gate A")


def _feishu_contract_refs(client: LarkContentSourceClient, locator: str) -> tuple[str, str]:
    space_id = client.resolve_space_id(locator)
    roots = [item for item in client.list_roots(space_id=space_id) if item.get("title") == "06-Agent与Workflow"]
    if len(roots) != 1 or not isinstance(roots[0].get("node_token"), str):
        raise ContentSourceError("Feishu 06 root is missing or ambiguous")
    children = client.list_children(space_id=space_id, parent_node_token=roots[0]["node_token"])
    manifest = [item for item in children if item.get("title") == "content-source-manifest"]
    profiles = [item for item in children if item.get("title") == "content-profile-index"]
    if len(manifest) != 1 or len(profiles) != 1:
        raise ContentSourceError("Feishu 06 must contain one Manifest and one Profile index")
    manifest_ref = manifest[0].get("obj_token")
    profile_ref = profiles[0].get("obj_token")
    if not isinstance(manifest_ref, str) or not isinstance(profile_ref, str):
        raise ContentSourceError("Feishu contract documents have no stable refs")
    return manifest_ref, profile_ref


def plan_configuration(
    knowledge_base: str | Path,
    *,
    registry_path: str | Path | None = None,
    lark_binary: str | None = None,
    lark_identity: str = "user",
    default_profile: str | None = None,
    default_no_ip: bool = False,
) -> dict[str, Any]:
    """Prepare a zero-write Registry binding for one already compatible knowledge base."""

    raw = str(knowledge_base)
    path = Path(raw).expanduser()
    if path.is_absolute() and path.is_dir() and not path.is_symlink():
        vault = path.resolve(strict=True)
        manifest_ref = MANIFEST_RELATIVE
        manifest, _manifest_hash = _read_json(_safe_obsidian_path(vault, manifest_ref))
        validate_manifest(manifest)
        profile_ref = manifest["profile_index_ref"]
        index, _index_hash = _read_json(_safe_obsidian_path(vault, profile_ref))
        validate_profile_index(index, manifest["knowledge_base_id"])
        locator = {"vault_root": str(vault)}
    elif raw.startswith("https://"):
        client = LarkContentSourceClient(binary=lark_binary, identity=lark_identity)
        manifest_ref, profile_ref = _feishu_contract_refs(client, raw)
        manifest = _json_from_markdown(client.fetch_markdown(manifest_ref))
        validate_manifest(manifest)
        index = _json_from_markdown(client.fetch_markdown(profile_ref))
        validate_profile_index(index, manifest["knowledge_base_id"])
        locator = {"knowledge_base_ref": raw}
    else:
        raise ContentSourceError("configuration requires an absolute Obsidian path or Feishu space URL")
    registry_file = Path(registry_path) if registry_path else default_registry_path()
    if not registry_file.is_absolute():
        raise ContentSourceError("Registry path must be absolute")
    current = {"contract_version": CONTRACT_VERSION, "bindings": {}, "workflow_defaults": {}, "revision": 1}
    if registry_file.exists():
        current, _ = _read_json(registry_file)
        validate_registry(current)
    binding_id = _stable_id("BND", manifest["client_id"], manifest["knowledge_base_id"])
    old = current["bindings"].get(binding_id, {})
    workflows = sorted(set(old.get("supported_workflows", [])) | {WORKFLOW})
    if default_profile and default_no_ip:
        raise ContentSourceError("default_profile and default_no_ip are mutually exclusive")
    active = [item for item in index["profiles"] if item["status"] == "active"]
    primary = [item for item in active if item["is_primary"]]
    selected_default = None
    if default_no_ip:
        selected_default = None
    elif default_profile:
        folded = default_profile.casefold()
        matches = [item for item in active if folded in {item["profile_id"].casefold(), item["display_name"].casefold(), *(alias.casefold() for alias in item["aliases"])}]
        if len(matches) != 1:
            raise ContentSourceError("configured default Profile is missing or ambiguous")
        selected_default = matches[0]["profile_id"]
    elif len(primary) == 1:
        selected_default = primary[0]["profile_id"]
    defaults = dict(old.get("workflow_defaults", {}))
    defaults[WORKFLOW] = {
        "profile_id": selected_default,
        "use_no_ip": default_no_ip,
    }
    binding = {
        "binding_id": binding_id,
        "client_id": manifest["client_id"],
        "knowledge_base_id": manifest["knowledge_base_id"],
        "backend": manifest["backend"],
        "locator": locator,
        "manifest_ref": manifest_ref,
        "profile_index_ref": profile_ref,
        "supported_workflows": workflows,
        "workflow_defaults": defaults,
        "status": "active",
    }
    if old and any(old.get(key) != binding.get(key) for key in ("client_id", "knowledge_base_id", "backend", "locator", "manifest_ref", "profile_index_ref")):
        raise ContentSourceError("existing Registry binding points elsewhere")
    updated = json.loads(json.dumps(current))
    updated["bindings"][binding_id] = binding
    updated["workflow_defaults"].setdefault(WORKFLOW, binding_id)
    if updated != current:
        updated["revision"] = int(current.get("revision", 0)) + 1
    validate_registry(updated)
    preview = {
        "workflow": WORKFLOW,
        "backend": manifest["backend"],
        "knowledge_base_id": manifest["knowledge_base_id"],
        "binding_id": binding_id,
        "registry_path": str(registry_file),
        "registry_action": "reuse" if updated == current else "merge",
        "profile_count": len(index["profiles"]),
        "wrote": False,
    }
    token = hashlib.sha256(("content-gzh-config\0" + _digest(_canonical({"preview": preview, "registry": updated}))).encode()).hexdigest()[:24]
    return {"preview": preview, "confirmation": token, "registry": updated}


def apply_configuration(
    knowledge_base: str | Path,
    *,
    confirmation: str,
    registry_path: str | Path | None = None,
    lark_binary: str | None = None,
    lark_identity: str = "user",
    default_profile: str | None = None,
    default_no_ip: bool = False,
) -> dict[str, Any]:
    plan = plan_configuration(
        knowledge_base,
        registry_path=registry_path,
        lark_binary=lark_binary,
        lark_identity=lark_identity,
        default_profile=default_profile,
        default_no_ip=default_no_ip,
    )
    if confirmation != plan["confirmation"]:
        raise ContentSourceError("confirmation does not match the current zero-write preview")
    path = Path(plan["preview"]["registry_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ContentSourceError("Registry parent must not be a symlink")
    payload = _canonical(plan["registry"])
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".content-registry-", suffix=".tmp", delete=False) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    try:
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        if path.read_bytes() != payload:
            raise ContentSourceError("Registry readback mismatch")
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"status": "configured", **plan["preview"], "wrote": True, "readback": "verified"}

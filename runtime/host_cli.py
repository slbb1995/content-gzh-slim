"""Unified installed-host CLI for one content-gzh-slim candidate bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from .artifact_store import ArtifactStore, ArtifactStoreError
from .content_source import (
    ContentSourceError,
    apply_configuration,
    default_runs_root,
    plan_configuration,
    resolve_real_source,
    verify_source_snapshot,
)
from .contracts import validate_task_input
from .distribution_service import DistributionService
from .feishu_adapter import FeishuAdapter
from .fixture_adapter import FixtureAdapter
from .lark_cli_client import LarkCliFeishuClient
from .obsidian_adapter import ObsidianAdapter
from .p2_pipeline import P2Pipeline
from .p3_pipeline import P3Pipeline
from .p4_pipeline import P4Pipeline
from .run_store import RunStore
from .save_service import SaveService


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return value


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _bundle_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _store(args: argparse.Namespace) -> Path:
    return args.store or default_runs_root()


def _run_artifact_path(store: Path, run_id: str, name: str) -> Path:
    return ArtifactStore(store).boundary.child("runs", run_id, name)


def _start_or_resume(args: argparse.Namespace) -> tuple[dict[str, Any], Path, bool]:
    store = _store(args)
    raw = _read_json(args.input)
    if args.catalog is not None:
        task = validate_task_input(raw)
        knowledge_base, ip = FixtureAdapter(args.catalog).resolve(
            task["knowledge_base"], task["ip"]
        )
        result = RunStore(store).create_or_resume(task, knowledge_base, ip)
        return result.run, args.catalog, result.created
    task, knowledge_base, ip, catalog, snapshot = resolve_real_source(
        raw,
        registry_path=args.registry,
        lark_identity=args.identity,
    )
    result = RunStore(store).create_or_resume(task, knowledge_base, ip)
    artifacts = ArtifactStore(store)
    artifacts.write_json_once_or_verify(result.run["run_id"], "source_catalog.json", catalog)
    artifacts.write_json_once_or_verify(result.run["run_id"], "source_snapshot.json", snapshot)
    return result.run, _run_artifact_path(store, result.run["run_id"], "source_catalog.json"), result.created


def _real_snapshot(store: Path, run_id: str) -> dict[str, Any] | None:
    try:
        return ArtifactStore(store).read_json(run_id, "source_snapshot.json")
    except ArtifactStoreError:
        return None


def _verify_real_run(store: Path, run_id: str, *, identity: str) -> dict[str, Any] | None:
    snapshot = _real_snapshot(store, run_id)
    if snapshot is not None:
        expected = RunStore(store).load(run_id).get("knowledge_base_identity", {}).get("source_snapshot_sha256")
        actual = "sha256:" + hashlib.sha256(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        ).hexdigest()
        if expected != actual:
            raise ContentSourceError("source snapshot does not match the frozen Run identity")
        verify_source_snapshot(snapshot, lark_identity=identity)
    return snapshot


def _derived_adapter(store: Path, run_id: str, *, identity: str) -> dict[str, Any]:
    run = RunStore(store).load(run_id)
    snapshot = _verify_real_run(store, run_id, identity=identity)
    if snapshot is None:
        raise ContentSourceError("legacy fixture Run requires its explicit isolated save adapter")
    target_ref = snapshot["save_target_ref"]
    backend = snapshot["backend"]
    if backend == "obsidian":
        profile_id = run.get("ip_identity", {}).get("profile_id") or "none"
        rendered = snapshot["output_template"].replace("{profile_id}", profile_id)
        if "{" in rendered or "}" in rendered:
            raise ContentSourceError("Manifest output template contains an unsupported placeholder")
        relative_dir = (PurePosixPath(snapshot["output_locator"]) / PurePosixPath(rendered)).as_posix()
        return {"obsidian": ObsidianAdapter(snapshot["knowledge_base_locator"], {target_ref: relative_dir})}
    if backend == "feishu":
        client = LarkCliFeishuClient(store / "feishu-idempotency.json", identity=identity)
        return {"feishu": FeishuAdapter(client, {target_ref: snapshot["output_locator"]})}
    raise ContentSourceError("frozen source backend is unsupported")


def _probe() -> dict[str, Any]:
    root = _bundle_root()
    manifest_path = root / "PACKAGE-MANIFEST.json"
    manifest = _read_json(manifest_path)
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("package manifest contains no files")
    for relative, expected in files.items():
        path = root / relative
        if not path.is_file():
            raise ValueError(f"package file is missing: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"package checksum mismatch: {relative}")
    skill_root_value = manifest.get("skill_root", ".agents/skills")
    skill_root_path = Path(skill_root_value)
    if skill_root_path.is_absolute() or ".." in skill_root_path.parts:
        raise ValueError("package manifest skill root is unsafe")
    skill_root = root / skill_root_path
    names = sorted(path.parent.name for path in skill_root.glob("*/SKILL.md"))
    if names != sorted(manifest.get("skills", [])):
        raise ValueError("installed skill list differs from package manifest")
    return {
        "status": "ready",
        "package": manifest.get("package"),
        "source_revision": manifest.get("source_revision"),
        "skills": names,
        "credentials_copied": False,
        "legacy_v1_replaced": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="content-gzh-slim installed-host runtime")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("probe")

    configure = commands.add_parser("configure")
    configure.add_argument("--knowledge-base", required=True)
    configure.add_argument("--registry", type=Path)
    configure.add_argument("--confirmation")
    configure.add_argument("--identity", choices=("user", "bot"), default="user")
    configure.add_argument("--default-profile")
    configure.add_argument("--default-no-ip", action="store_true")

    start = commands.add_parser("start")
    start.add_argument("--input", required=True, type=Path)
    start.add_argument("--catalog", type=Path, help="test fixtures only")
    start.add_argument("--registry", type=Path)
    start.add_argument("--identity", choices=("user", "bot"), default="user")
    start.add_argument("--store", type=Path)

    gate_a = commands.add_parser("prepare-gate-a")
    gate_a.add_argument("--input", required=True, type=Path)
    gate_a.add_argument("--catalog", type=Path, help="test fixtures only")
    gate_a.add_argument("--registry", type=Path)
    gate_a.add_argument("--identity", choices=("user", "bot"), default="user")
    gate_a.add_argument("--analysis", required=True, type=Path)
    gate_a.add_argument("--direction", required=True, type=Path)
    gate_a.add_argument("--store", type=Path)

    approve_a = commands.add_parser("approve-gate-a")
    approve_a.add_argument("--run-id", required=True)
    approve_a.add_argument("--store", type=Path)
    approve_a.add_argument("--option-id", required=True)
    approve_a.add_argument("--decision", required=True)

    context = commands.add_parser("build-context")
    context.add_argument("--run-id", required=True)
    context.add_argument("--catalog", type=Path, help="test fixtures only")
    context.add_argument("--selection", required=True, type=Path)
    context.add_argument("--store", type=Path)
    context.add_argument("--identity", choices=("user", "bot"), default="user")

    gate_b = commands.add_parser("prepare-gate-b")
    gate_b.add_argument("--run-id", required=True)
    gate_b.add_argument("--draft-output", required=True, type=Path)
    gate_b.add_argument("--headline-output", required=True, type=Path)
    gate_b.add_argument("--store", type=Path)

    approve_b = commands.add_parser("approve-gate-b")
    approve_b.add_argument("--run-id", required=True)
    approve_b.add_argument("--store", type=Path)
    approve_b.add_argument("--decision", required=True)

    obsidian = commands.add_parser("save-obsidian")
    obsidian.add_argument("--run-id", required=True)
    obsidian.add_argument("--store", type=Path)
    obsidian.add_argument("--isolated-root", required=True, type=Path)
    obsidian.add_argument("--target-ref", required=True)
    obsidian.add_argument("--relative-dir", required=True)

    feishu = commands.add_parser("save-feishu")
    feishu.add_argument("--run-id", required=True)
    feishu.add_argument("--store", type=Path)
    feishu.add_argument("--target-ref", required=True)
    feishu.add_argument("--parent-ref", required=True)
    feishu.add_argument("--client-state", required=True, type=Path)
    feishu.add_argument("--identity", choices=("user", "bot"), default="user")

    save = commands.add_parser("save")
    save.add_argument("--run-id", required=True)
    save.add_argument("--store", type=Path)
    save.add_argument("--identity", choices=("user", "bot"), default="user")

    distribution = commands.add_parser("generate-distribution")
    distribution.add_argument("--run-id", required=True)
    distribution.add_argument("--store", type=Path)
    distribution.add_argument("--candidate", required=True, type=Path)
    distribution.add_argument("--request", required=True)

    status = commands.add_parser("status")
    status.add_argument("--run-id", required=True)
    status.add_argument("--store", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "probe":
            _emit(_probe())
        elif args.command == "configure":
            if args.confirmation:
                _emit(
                    apply_configuration(
                        args.knowledge_base,
                        confirmation=args.confirmation,
                        registry_path=args.registry,
                        lark_identity=args.identity,
                        default_profile=args.default_profile,
                        default_no_ip=args.default_no_ip,
                    )
                )
            else:
                plan = plan_configuration(
                    args.knowledge_base,
                    registry_path=args.registry,
                    lark_identity=args.identity,
                    default_profile=args.default_profile,
                    default_no_ip=args.default_no_ip,
                )
                _emit(
                    {
                        "status": "confirmation_required",
                        "message": "配置预览已生成；当前零写入。确认后才登记知识库。",
                        "preview": plan["preview"],
                        "confirmation": plan["confirmation"],
                    }
                )
        elif args.command == "start":
            run, _catalog, created = _start_or_resume(args)
            _emit(
                {
                    "outcome": "created" if created else "resumed",
                    "run_id": run["run_id"],
                    "status": run["status"],
                }
            )
        elif args.command == "prepare-gate-a":
            run, catalog, _created = _start_or_resume(args)
            result = P2Pipeline(_store(args), catalog).run(
                run["run_id"], args.analysis, args.direction
            )
            print(result["gate_a"])
        elif args.command == "approve-gate-a":
            store = RunStore(_store(args))
            store.select_gate_a_option(args.run_id, args.option_id)
            run = store.approve_gate(args.run_id, "A", args.decision)
            _emit({"run_id": args.run_id, "status": run["status"]})
        elif args.command == "build-context":
            store_root = _store(args)
            _verify_real_run(store_root, args.run_id, identity=args.identity)
            catalog = args.catalog or _run_artifact_path(store_root, args.run_id, "source_catalog.json")
            result = P3Pipeline(store_root, catalog).run(args.run_id, args.selection)
            _emit(
                {
                    "run_id": args.run_id,
                    "status": "context_ready",
                    "context_file": "article_context_v1.json",
                    "writer_input_files": 1,
                    "resumed": result["resumed"],
                }
            )
        elif args.command == "prepare-gate-b":
            result = P4Pipeline(_store(args)).run_initial(
                args.run_id,
                args.draft_output.read_text(encoding="utf-8"),
                _read_json(args.headline_output),
            )
            print(result["gate_b"])
        elif args.command == "approve-gate-b":
            run = RunStore(_store(args)).approve_gate(args.run_id, "B", args.decision)
            _emit({"run_id": args.run_id, "status": run["status"]})
        elif args.command == "save-obsidian":
            if _real_snapshot(_store(args), args.run_id) is not None:
                raise ContentSourceError("real Runs must use save so the target comes from the frozen Manifest")
            adapter = ObsidianAdapter(
                args.isolated_root, {args.target_ref: args.relative_dir}
            )
            result = SaveService(_store(args), {"obsidian": adapter}).save(args.run_id)
            _emit(result["save_receipt"])
        elif args.command == "save-feishu":
            if _real_snapshot(_store(args), args.run_id) is not None:
                raise ContentSourceError("real Runs must use save so the target comes from the frozen Manifest")
            client = LarkCliFeishuClient(
                args.client_state, identity=args.identity
            )
            adapter = FeishuAdapter(client, {args.target_ref: args.parent_ref})
            result = SaveService(_store(args), {"feishu": adapter}).save(args.run_id)
            _emit(result["save_receipt"])
        elif args.command == "save":
            store_root = _store(args)
            adapters = _derived_adapter(store_root, args.run_id, identity=args.identity)
            result = SaveService(store_root, adapters).save(args.run_id)
            _emit(result["save_receipt"])
        elif args.command == "generate-distribution":
            result = DistributionService(_store(args)).generate(
                args.run_id,
                explicit_request=args.request,
                candidate=_read_json(args.candidate),
            )
            _emit(result["distribution"])
        elif args.command == "status":
            run = RunStore(_store(args)).load(args.run_id)
            _emit(
                {
                    "run_id": args.run_id,
                    "status": run["status"],
                    "gate_count": len(run.get("gate_approvals", [])),
                    "draftbox": False,
                    "published": False,
                }
            )
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"content-gzh-slim failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

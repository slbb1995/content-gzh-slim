"""Deterministic create-or-resume storage for one frozen P1 Run identity."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .path_boundary import PathBoundary
from .state_machine import StateMachine


class RunStoreError(RuntimeError):
    """Raised when an existing Run cannot be safely resumed or updated."""


@dataclass(frozen=True)
class RunResult:
    run: dict[str, Any]
    created: bool


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RunStore:
    def __init__(self, root: str | Path) -> None:
        self.boundary = PathBoundary(root)
        self.boundary.root.mkdir(parents=True, exist_ok=True)
        self.runs_root = self.boundary.child("runs")
        self.runs_root.mkdir(exist_ok=True)

    @staticmethod
    def identity_digest(
        task_input: dict[str, Any],
        knowledge_base_identity: dict[str, Any],
        ip_identity: dict[str, Any],
    ) -> str:
        frozen_identity = {
            "schema_version": 1,
            "knowledge_base_identity": knowledge_base_identity,
            "ip_identity": ip_identity,
            "task_input": task_input,
        }
        return hashlib.sha256(_canonical_json(frozen_identity).encode("utf-8")).hexdigest()

    def _run_file(self, run_id: str) -> Path:
        return self.boundary.child("runs", run_id, "run.json")

    def load(self, run_id: str) -> dict[str, Any]:
        run = self._read_json(self._run_file(run_id))
        if run.get("run_id") != run_id:
            raise RunStoreError("Run identity mismatch; refusing to load")
        return run

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RunStoreError("existing Run is unreadable; refusing to replace it") from exc
        if not isinstance(value, dict):
            raise RunStoreError("existing Run is not an object; refusing to replace it")
        return value

    @staticmethod
    def _write_create_only(path: Path, value: dict[str, Any]) -> None:
        payload = (_canonical_json(value) + "\n").encode("utf-8")
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise RunStoreError("Run already exists during create-only write") from exc
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)

    @staticmethod
    def _replace(path: Path, value: dict[str, Any]) -> None:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=".run-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write((_canonical_json(value) + "\n").encode("utf-8"))
            temporary = Path(handle.name)
        os.replace(temporary, path)

    def create_or_resume(
        self,
        task_input: dict[str, Any],
        knowledge_base_identity: dict[str, Any],
        ip_identity: dict[str, Any],
    ) -> RunResult:
        digest = self.identity_digest(task_input, knowledge_base_identity, ip_identity)
        run_id = f"run_{digest[:24]}"
        run_dir = self.boundary.child("runs", run_id)
        run_file = self._run_file(run_id)

        try:
            run_dir.mkdir()
            created = True
        except FileExistsError:
            created = False

        if not created:
            existing = self._read_json(run_file)
            if existing.get("input_digest") != digest or existing.get("run_id") != run_id:
                raise RunStoreError("existing Run identity mismatch; refusing to overwrite")
            return RunResult(existing, created=False)

        now = _utc_now()
        run = {
            "schema_version": 1,
            "run_id": run_id,
            "input_digest": digest,
            "knowledge_base_identity": knowledge_base_identity,
            "ip_identity": ip_identity,
            "task_input": task_input,
            "status": "created",
            "status_history": [{"status": "created", "at": now}],
            "gate_approvals": [],
            "created_at": now,
            "updated_at": now,
        }
        self._write_create_only(run_file, run)
        return RunResult(run, created=True)

    def advance(self, run_id: str, target: str) -> dict[str, Any]:
        run_file = self._run_file(run_id)
        run = self._read_json(run_file)
        if run.get("run_id") != run_id:
            raise RunStoreError("Run identity mismatch; refusing to update")
        StateMachine.require_transition(run.get("status"), target)
        now = _utc_now()
        run["status"] = target
        run["updated_at"] = now
        run["status_history"] = [*run.get("status_history", []), {"status": target, "at": now}]
        self._replace(run_file, run)
        return run

    def approve_gate(self, run_id: str, gate: str, decision: str) -> dict[str, Any]:
        transitions = {
            "A": ("waiting_direction", "direction_approved"),
            "B": ("waiting_final", "final_approved"),
        }
        if gate not in transitions:
            raise RunStoreError("gate must be A or B")
        current, target = transitions[gate]
        exact_approval = gate == "A" and decision == "确认方向"
        exact_approval = exact_approval or (
            gate == "B"
            and isinstance(decision, str)
            and (
                decision == "确认正文和标题"
                or (
                    decision.startswith("使用标题：")
                    and decision.removeprefix("使用标题：").strip()
                )
            )
        )
        if not exact_approval:
            raise RunStoreError("gate decision is not an explicit approval")

        run_file = self._run_file(run_id)
        run = self._read_json(run_file)
        if run.get("run_id") != run_id:
            raise RunStoreError("Run identity mismatch; refusing to update")
        if run.get("status") != current:
            raise RunStoreError(f"Gate {gate} is not waiting for approval")
        StateMachine.require_gate_approval(current, target)

        now = _utc_now()
        run["status"] = target
        run["updated_at"] = now
        run["status_history"] = [*run.get("status_history", []), {"status": target, "at": now}]
        run["gate_approvals"] = [
            *run.get("gate_approvals", []),
            {"gate": gate, "decision": decision, "at": now},
        ]
        self._replace(run_file, run)
        return run

    def select_gate_a_option(self, run_id: str, option_id: str) -> dict[str, Any]:
        if not isinstance(option_id, str) or not option_id.strip():
            raise RunStoreError("Gate A option_id must be explicit")
        run_file = self._run_file(run_id)
        run = self._read_json(run_file)
        if run.get("run_id") != run_id:
            raise RunStoreError("Run identity mismatch; refusing to update")
        if run.get("status") != "waiting_direction":
            raise RunStoreError("Gate A option selection requires waiting_direction")
        existing = run.get("gate_a_selection")
        if existing is not None:
            if existing.get("option_id") != option_id.strip():
                raise RunStoreError("Gate A option is already bound and cannot be replaced")
            return run
        now = _utc_now()
        run["updated_at"] = now
        run["gate_a_selection"] = {"option_id": option_id.strip(), "at": now}
        self._replace(run_file, run)
        return run

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Mapping

from .artifact_io import write_json_atomic
from .candidate_contracts import file_sha256


_SCHEMA = "torii.tum_style_closed_loop.v1"
_DECISIONS = {"accepted", "rejected", "review_required"}
_ACTION_KINDS = {"inspect", "join", "connection", "tls", "geometry"}


def start_tum_style_closed_loop(*, baseline_net_file: Path, output_dir: Path, source_net_file: Path | None = None) -> dict[str, Any]:
    baseline = baseline_net_file.resolve()
    if not baseline.is_file():
        raise FileNotFoundError(f"baseline network does not exist: {baseline}")
    output = output_dir.resolve()
    state_file = output / "state.json"
    if state_file.exists():
        raise ValueError(f"closed loop already exists: {state_file}")
    canonical = output / "canonical" / "baseline.net.xml"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(baseline, canonical)
    source = (source_net_file or baseline).resolve()
    state = {
        "schema": _SCHEMA,
        "status": "open",
        "claim_status": "diagnostic-demo",
        "automatic_promotion_gate": "blocked",
        "canonical_baseline": _artifact(canonical),
        "source_reference": _artifact(source) if source.is_file() else {"path": str(source), "sha256": ""},
        "current_candidate": _artifact(canonical),
        "iterations": [],
        "pending_iteration": None,
        "next_action": _next_action({}, reason="start with an observed baseline"),
    }
    write_json_atomic(state_file, state, sort_keys=True)
    return {**state, "state_file": str(state_file)}


def begin_tum_style_iteration(*, state_file: Path) -> dict[str, Any]:
    state_path, state = _load_state(state_file)
    if state.get("pending_iteration"):
        raise ValueError("an iteration is already pending")
    current = _require_artifact(state.get("current_candidate"), "current_candidate")
    current_path = Path(current["path"])
    iteration_id = f"{len(state.get('iterations', [])) + 1:04d}"
    iteration_dir = state_path.parent / "iterations" / iteration_id
    iteration_dir.mkdir(parents=True, exist_ok=False)
    before = iteration_dir / "before.net.xml"
    shutil.copy2(current_path, before)
    pending = {
        "iteration_id": iteration_id,
        "status": "observed",
        "parent_candidate": _artifact(before),
        "started_from": current,
        "iteration_dir": str(iteration_dir),
    }
    state["pending_iteration"] = pending
    state["next_action"] = _next_action({}, reason="observe the immutable before snapshot")
    _write_state(state_path, state)
    return {**pending, "state_file": str(state_path), "before_net_file": str(before)}


def complete_tum_style_iteration(
    *,
    state_file: Path,
    iteration_id: str,
    after_net_file: Path,
    action: Mapping[str, Any],
    audit: Mapping[str, Any],
    mcp_evidence: Mapping[str, Any],
    decision: str,
) -> dict[str, Any]:
    state_path, state = _load_state(state_file)
    pending = state.get("pending_iteration")
    if not isinstance(pending, Mapping) or str(pending.get("iteration_id")) != str(iteration_id):
        raise ValueError(f"iteration {iteration_id} is not pending")
    before = _require_artifact(pending.get("parent_candidate"), "parent_candidate")
    if file_sha256(Path(before["path"])) != before["sha256"]:
        raise ValueError("parent candidate changed after begin")
    if decision not in _DECISIONS:
        raise ValueError(f"decision must be one of {sorted(_DECISIONS)}")
    visual_gate = audit.get("visual_connection_gate")
    if decision == "accepted" and (
        not isinstance(visual_gate, Mapping) or visual_gate.get("status") != "pass"
    ):
        raise ValueError("visual Connection gate must pass before accepting a candidate")
    normalized_action = _validate_action(action)
    after_source = Path(after_net_file).resolve()
    if not after_source.is_file():
        raise FileNotFoundError(f"after network does not exist: {after_source}")
    iteration_dir = Path(str(pending["iteration_dir"]))
    after = iteration_dir / "after.net.xml"
    shutil.copy2(after_source, after)
    iteration = {
        "iteration_id": str(iteration_id),
        "status": "closed",
        "decision": decision,
        "parent_candidate": before,
        "after_candidate": _artifact(after),
        "action": normalized_action,
        "mcp_evidence": dict(mcp_evidence),
        "audit": dict(audit),
        "rollback_file": str(iteration_dir / "rollback.json"),
    }
    current = state["current_candidate"]
    if decision == "accepted":
        current = iteration["after_candidate"]
    state["current_candidate"] = current
    state["iterations"].append(iteration)
    state["pending_iteration"] = None
    state["next_action"] = _next_action(audit, reason=f"after iteration {iteration_id}: {decision}")
    rollback = {
        "schema": "torii.tum_style_closed_loop.rollback.v1",
        "iteration_id": str(iteration_id),
        "restore_candidate": before,
        "safe_to_apply": decision == "accepted",
        "reason": "restore the parent artifact without mutating the canonical baseline",
    }
    write_json_atomic(iteration_dir / "action.json", normalized_action, sort_keys=True)
    write_json_atomic(iteration_dir / "audit.json", dict(audit), sort_keys=True)
    write_json_atomic(iteration_dir / "mcp-session.json", dict(mcp_evidence), sort_keys=True)
    write_json_atomic(iteration_dir / "decision.json", {"decision": decision}, sort_keys=True)
    write_json_atomic(iteration_dir / "rollback.json", rollback, sort_keys=True)
    _write_state(state_path, state)
    return {**state, "state_file": str(state_path), "iteration": iteration, "rollback_file": str(iteration_dir / "rollback.json")}


def rollback_tum_style_iteration(*, state_file: Path, iteration_id: str) -> dict[str, Any]:
    state_path, state = _load_state(state_file)
    match = next((item for item in state.get("iterations", []) if str(item.get("iteration_id")) == str(iteration_id)), None)
    if not isinstance(match, Mapping):
        raise ValueError(f"iteration {iteration_id} does not exist")
    parent = _require_artifact(match.get("parent_candidate"), "parent_candidate")
    state["current_candidate"] = parent
    match["status"] = "rolled_back"
    state["next_action"] = _next_action(match.get("audit", {}), reason=f"iteration {iteration_id} rolled back")
    rollback_file = state_path.parent / "iterations" / str(iteration_id) / "rollback.json"
    rollback = {
        "schema": "torii.tum_style_closed_loop.rollback.v1",
        "iteration_id": str(iteration_id),
        "restore_candidate": parent,
        "safe_to_apply": True,
        "reason": "explicit closed-loop rollback",
    }
    write_json_atomic(rollback_file, rollback, sort_keys=True)
    _write_state(state_path, state)
    return {**state, "state_file": str(state_path), "rollback_file": str(rollback_file)}


def next_tum_style_action(*, state_file: Path, audit: Mapping[str, Any] | None = None) -> dict[str, Any]:
    state_path, state = _load_state(state_file)
    action = _next_action(audit or {}, reason="audit evidence is incomplete or the last gate failed")
    state["next_action"] = action
    _write_state(state_path, state)
    return {"status": "review_required", "action": action, "state_file": str(state_path)}


def _next_action(audit: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    if not audit:
        return {
            "kind": "inspect",
            "mode": "inspect_mode",
            "count": 1,
            "requires_evidence": True,
            "reason": reason,
        }
    # The matrix gap is derived from incoming*outgoing and can grow when an
    # approach is split.  Do not turn an exact TLS movement match into a
    # spurious connection edit.
    tls_movement_parity = audit.get("tls_movement_parity")
    matrix_gap_is_actionable = audit.get("vehicle_movement_matrix_missing_count") and tls_movement_parity != "pass"
    if audit.get("movement_missing_count") or matrix_gap_is_actionable:
        return {"kind": "connection", "mode": "connection_mode", "count": 1, "requires_evidence": False, "reason": "repair one missing movement"}
    if audit.get("tls_mismatch_count") or audit.get("tls_logic_parity") == "fail":
        return {"kind": "tls", "mode": "tls_mode", "count": 1, "requires_evidence": False, "reason": "inspect or correct one TLS cell"}
    if audit.get("surface_overlap_status") == "fail" or audit.get("short_internal_lane_count"):
        return {"kind": "join", "mode": "inspect_mode", "count": 1, "requires_evidence": True, "reason": "inspect one overlapping or micro-lane junction before joining"}
    if audit.get("approach_integrity_status") == "fail":
        return {"kind": "geometry", "mode": "edge_mode", "count": 1, "requires_evidence": False, "reason": "repair one approach endpoint or shape"}
    return {"kind": "inspect", "mode": "inspect_mode", "count": 1, "requires_evidence": True, "reason": reason}


def _validate_action(action: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(action)
    kind = str(normalized.get("kind", "")).strip().lower()
    if kind not in _ACTION_KINDS:
        raise ValueError(f"action kind must be one of {sorted(_ACTION_KINDS)}")
    if int(normalized.get("count", 1)) != 1:
        raise ValueError("one iteration may contain exactly one semantic action")
    normalized["kind"] = kind
    normalized["count"] = 1
    return normalized


def _artifact(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"artifact does not exist: {resolved}")
    return {"path": str(resolved), "sha256": file_sha256(resolved)}


def _require_artifact(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value.get("path") or not value.get("sha256"):
        raise ValueError(f"state is missing {name}")
    return {"path": str(value["path"]), "sha256": str(value["sha256"])}


def _load_state(state_file: Path) -> tuple[Path, dict[str, Any]]:
    state_path = state_file.resolve()
    if not state_path.is_file():
        raise FileNotFoundError(f"closed-loop state does not exist: {state_path}")
    import json

    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("schema") != _SCHEMA:
        raise ValueError("unsupported closed-loop state schema")
    return state_path, state


def _write_state(state_path: Path, state: Mapping[str, Any]) -> None:
    write_json_atomic(state_path, dict(state), sort_keys=True)

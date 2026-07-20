"""Resumable stage ledger for the Hamburg named-corridor digital twin.

The domain stages already live in focused modules.  This module is deliberately
small: it does not rebuild a network or reinterpret official data.  It records
which stage artifacts are present, verifies their bytes, derives dependency
readiness, and invalidates downstream stages when an upstream manifest changes.
That makes the Codex loop (plan -> run -> audit -> revise -> rerun) executable
instead of relying on conversational memory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .artifact_io import write_json_atomic
from .candidate_contracts import file_sha256


HAMBURG_EXECUTION_WORKFLOW_SCHEMA = "torii.hamburg-sandtorkai-execution-workflow/v1"
HAMBURG_EXECUTION_WORKFLOW_ID = "hamburg_sandtorkai_2349_2394_2403"

STAGE_DEPENDENCIES: Mapping[str, tuple[str, ...]] = {
    "W0": (),
    "W1": ("W0",),
    "W2": ("W1",),
    # Counts are independently observable once W0 fixes the named scope.
    "W3": ("W0",),
    "W4": ("W1", "W2", "W3"),
    "W5": ("W0", "W1", "W2", "W3", "W4"),
}

STAGE_NAMES: Mapping[str, str] = {
    "W0": "scope_and_evidence",
    "W1": "official_road_reconstruction",
    "W2": "official_signal_binding",
    "W3": "detectors_and_demand",
    "W4": "sumo_replay_comparison",
    "W5": "reusable_product_workflow",
}

# This is the small, stable design contract for the Codex loop.  It tells a
# resumed run where to look first and what a stage must verify before adding
# new code.  The actual artifacts remain caller-supplied and hash-bound.
STAGE_CONTRACTS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "W0": {
        "code_surfaces": ("core/hamburg_named_scope.py", "core/hamburg_official.py"),
        "entrypoints": ("scripts/freeze_hamburg_named_scope.py",),
        "verification": ("official identity", "road-arm scope", "source hashes"),
    },
    "W1": {
        "code_surfaces": (
            "core/hamburg_official_corridor_geometry.py",
            "core/road_network/official_plainxml.py",
            "core/road_network/official_lane_stitch.py",
            "core/road_network/official_splice_plan.py",
            "core/connection_mode_audit.py",
        ),
        "entrypoints": ("scripts/build_hamburg_official_corridor_geometry.py",),
        "verification": (
            "official MAP/HH-SIB lane-axis match",
            "official merge-point splice plan",
            "netconvert",
            "SUMO load",
            "lane-surface overlap",
            "connection graph",
        ),
    },
    "W2": {
        "code_surfaces": (
            "core/hamburg_named_signal_binding.py",
            "core/hamburg_named_signal_observations.py",
            "core/ocit_c.py",
        ),
        "entrypoints": (
            "scripts/build_hamburg_named_signal_binding.py",
            "scripts/build_hamburg_named_signal_observations.py",
        ),
        "verification": ("MAP/OCIT identity", "TLS link coverage", "complete t=0/history"),
    },
    "W3": {
        "code_surfaces": (
            "core/hamburg_named_count_scope.py",
            "core/hamburg_named_detector_bindings.py",
            "core/digital_twin_mapping.py",
        ),
        "entrypoints": (
            "scripts/build_hamburg_named_counts.py",
            "scripts/build_hamburg_named_detector_bindings.py",
        ),
        "verification": ("complete official bins", "explicit CRS", "unique lane binding", "same-location E1/E2"),
    },
    "W4": {
        "code_surfaces": ("core/hamburg_named_replay.py", "core/route_sampler.py"),
        "entrypoints": ("scripts/build_hamburg_named_replay.py",),
        "verification": ("routeability", "zero teleports", "zero collisions", "formal comparison"),
    },
    "W5": {
        "code_surfaces": ("core/hamburg_execution_workflow.py", "server.py"),
        "entrypoints": ("scripts/run_hamburg_execution_plan.py",),
        "verification": ("hash-bound rerun", "downstream invalidation", "full regression"),
    },
}


class HamburgExecutionWorkflowError(ValueError):
    """Raised when a workflow plan cannot be made hash-safe."""


def materialize_hamburg_execution_plan(
    *,
    output_dir: Path,
    stage_manifests: Mapping[str, Path],
    stage_feedback: Mapping[str, Path | Sequence[Path]] | None = None,
    workflow_id: str = HAMBURG_EXECUTION_WORKFLOW_ID,
    resume: bool = True,
) -> dict[str, Any]:
    """Write a hash-bound, resumable plan from existing stage manifests.

    ``stage_manifests`` is intentionally caller-supplied.  This keeps the
    planner reusable across dated runs and prevents it from guessing which
    generated network or official snapshot is authoritative.  Missing stages
    are represented as ``not_run``; a blocked dependency is never treated as a
    successful prerequisite.
    """

    if workflow_id != HAMBURG_EXECUTION_WORKFLOW_ID:
        raise HamburgExecutionWorkflowError(f"unsupported workflow_id: {workflow_id}")
    normalized = _normalize_stage_paths(stage_manifests)
    normalized_feedback = _normalize_feedback_paths(stage_feedback or {})
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    plan_file = output / "execution-plan.manifest.json"
    previous = _read_previous_plan(plan_file) if resume and plan_file.is_file() else None

    stage_records: dict[str, dict[str, Any]] = {}
    for stage_id in STAGE_DEPENDENCIES:
        path = normalized.get(stage_id)
        feedback_paths = normalized_feedback.get(stage_id, ())
        record = _read_stage_record(stage_id, path, feedback_paths=feedback_paths)
        record["contract"] = _stage_contract(stage_id)
        stage_records[stage_id] = record

    changed = _changed_stage_ids(previous, stage_records)
    invalidated = _downstream_closure(changed)
    for stage_id in sorted(invalidated, key=_stage_sort_key):
        if stage_id == "W0" or stage_id not in stage_records:
            continue
        record = stage_records[stage_id]
        if record["status"] == "not_run":
            continue
        record["resume_decision"] = "invalidate_and_rerun"
        record["invalidation_reason"] = "upstream_stage_manifest_changed"
        record["effective_status"] = "not_run"

    for stage_id, record in stage_records.items():
        if "effective_status" not in record:
            record["effective_status"] = record["status"]
        dependencies = STAGE_DEPENDENCIES[stage_id]
        dependency_rows = [stage_records[dependency] for dependency in dependencies]
        dependency_decisions = {
            dependency: _stage_gate(stage_records[dependency])
            for dependency in dependencies
        }
        record["dependencies"] = list(dependencies)
        record["dependency_gate"] = dependency_decisions
        failed = {
            dependency: decision
            for dependency, decision in dependency_decisions.items()
            if decision != "pass"
        }
        if record["effective_status"] == "not_run":
            if failed:
                record["readiness"] = "blocked"
                record["blocked_by"] = failed
            else:
                record["readiness"] = "ready"
        elif record.get("execution_gate") != "pass":
            record["readiness"] = "blocked"
            record["blocked_by"] = {stage_id: record.get("decision", "blocked")}
        elif failed:
            # An already-produced diagnostic artifact remains visible, but it
            # cannot make a downstream stage eligible for execution.
            record["readiness"] = "blocked"
            record["blocked_by"] = failed
        else:
            record["readiness"] = "complete"
        del dependency_rows

    next_action = _next_action(stage_records)
    plan_revision = int(previous.get("plan_revision", 0)) + 1 if previous else 1
    first_invalid_stage = _first_invalid_stage(stage_records)
    replan = _replan_summary(
        stage_records,
        next_action=next_action,
        changed=changed,
        invalidated=invalidated,
        first_invalid_stage=first_invalid_stage,
    )
    plan: dict[str, Any] = {
        "schema": HAMBURG_EXECUTION_WORKFLOW_SCHEMA,
        "workflow_id": workflow_id,
        "plan_revision": plan_revision,
        "execution_mode": "resumable_fail_closed",
        "loop": [
            "plan",
            "inspect_existing_torii_code_and_sources",
            "implement_minimally",
            "unit_test",
            "run_real_inputs",
            "audit",
            "revise_plan_on_failure",
            "rerun_from_first_invalid_stage",
        ],
        "stages": stage_records,
        "next_action": next_action,
        "first_invalid_stage": first_invalid_stage,
        "replan": replan,
        "changed_stages": sorted(changed, key=_stage_sort_key),
        "invalidated_downstream_stages": sorted(invalidated, key=_stage_sort_key),
        "promotion": {
            "decision": "pass" if next_action["status"] == "complete" else "blocked",
            "automatic": True,
            "requires": "W0-W4 all have automatic_promotion_gate=pass",
        },
        "claim_boundary": {
            "proves": [
                "which dated Torii stage artifacts are being reused",
                "that each referenced manifest is byte-hash stable",
                "which stage is eligible or blocked next",
            ],
            "does_not_prove": [
                "road, signal, demand, or field correctness by a manifest existing",
                "historical signal timing when official observations are absent",
                "a unique OD matrix from detector counts",
            ],
        },
    }
    write_json_atomic(plan_file, plan, ensure_ascii=False, sort_keys=True)
    plan["plan_file"] = str(plan_file)
    plan["plan_sha256"] = file_sha256(plan_file)
    return plan


def _normalize_stage_paths(stage_manifests: Mapping[str, Path]) -> dict[str, Path]:
    if not isinstance(stage_manifests, Mapping):
        raise HamburgExecutionWorkflowError("stage_manifests must be a mapping")
    result: dict[str, Path] = {}
    for raw_stage, raw_path in stage_manifests.items():
        stage_id = str(raw_stage).strip().upper()
        if stage_id not in STAGE_DEPENDENCIES:
            raise HamburgExecutionWorkflowError(f"unknown stage id: {raw_stage!r}")
        path = Path(raw_path).expanduser().resolve()
        if stage_id in result and result[stage_id] != path:
            raise HamburgExecutionWorkflowError(f"duplicate stage id: {stage_id}")
        result[stage_id] = path
    return result


def _stage_contract(stage_id: str) -> dict[str, list[str]]:
    contract = STAGE_CONTRACTS[stage_id]
    return {key: list(values) for key, values in contract.items()}


def _normalize_feedback_paths(
    stage_feedback: Mapping[str, Path | Sequence[Path]],
) -> dict[str, tuple[Path, ...]]:
    if not isinstance(stage_feedback, Mapping):
        raise HamburgExecutionWorkflowError("stage_feedback must be a mapping")
    result: dict[str, tuple[Path, ...]] = {}
    for raw_stage, raw_paths in stage_feedback.items():
        stage_id = str(raw_stage).strip().upper()
        if stage_id not in STAGE_DEPENDENCIES:
            raise HamburgExecutionWorkflowError(f"unknown stage id: {raw_stage!r}")
        if isinstance(raw_paths, (str, bytes, Path)):
            values = (Path(raw_paths),)
        else:
            try:
                values = tuple(Path(value) for value in raw_paths)
            except TypeError as exc:
                raise HamburgExecutionWorkflowError(
                    f"feedback paths for {stage_id} must be a path or sequence of paths"
                ) from exc
        if not values:
            raise HamburgExecutionWorkflowError(f"feedback paths for {stage_id} cannot be empty")
        result[stage_id] = tuple(path.expanduser().resolve() for path in values)
    return result


def _read_stage_record(
    stage_id: str,
    path: Path | None,
    *,
    feedback_paths: Sequence[Path] = (),
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "stage_id": stage_id,
        "name": STAGE_NAMES[stage_id],
        "manifest": None,
        "status": "not_run",
        "automatic_promotion_gate": "blocked",
        "decision": "not_run",
        "execution_gate": "blocked",
    }
    if path is None:
        return base
    base["manifest"] = str(path)
    if not path.is_file():
        base.update({"status": "blocked", "decision": "blocked", "reason": "manifest_missing"})
        return base
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        base.update({"status": "blocked", "decision": "blocked", "reason": f"manifest_invalid: {exc}"})
        return base
    if not isinstance(payload, Mapping):
        base.update({"status": "blocked", "decision": "blocked", "reason": "manifest_not_object"})
        return base
    raw_status = str(payload.get("status", "unknown"))
    gate = str(payload.get("automatic_promotion_gate", "blocked"))
    decision = _manifest_decision(raw_status, gate)
    declared_execution_gate = str(payload.get("execution_gate", "")).strip().lower()
    execution_gate = (
        declared_execution_gate
        if declared_execution_gate in {"pass", "blocked"}
        else _execution_gate(stage_id, payload, decision)
    )
    feedback = _manifest_feedback(payload)
    base.update(
        {
            "status": raw_status,
            "automatic_promotion_gate": gate,
            "decision": decision,
            "execution_gate": execution_gate,
            "manifest_sha256": file_sha256(path),
            "manifest_bytes": path.stat().st_size,
            "reported_schema": payload.get("schema") or payload.get("schema_id"),
            "reason": _manifest_reason(payload),
            "feedback": feedback,
        }
    )
    for feedback_path in feedback_paths:
        _merge_feedback_manifest(base, feedback_path)
    if not base["reason"]:
        base.pop("reason")
    if not base["feedback"]:
        base.pop("feedback")
    return base


def _merge_feedback_manifest(record: dict[str, Any], path: Path) -> None:
    """Attach an auxiliary diagnostic manifest without changing stage status."""

    metadata = {
        "path": str(path),
    }
    feedback_manifests = record.setdefault("feedback_manifests", [])
    if not isinstance(feedback_manifests, list):
        feedback_manifests = []
        record["feedback_manifests"] = feedback_manifests
    feedback_manifests.append(metadata)
    if len(feedback_manifests) == 1:
        record["feedback_manifest"] = metadata
    else:
        record.pop("feedback_manifest", None)
    if not path.is_file():
        record.setdefault("feedback", {})["feedback_manifest_error"] = "manifest_missing"
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        record.setdefault("feedback", {})["feedback_manifest_error"] = f"manifest_invalid: {exc}"
        return
    if not isinstance(payload, Mapping):
        record.setdefault("feedback", {})["feedback_manifest_error"] = "manifest_not_object"
        return
    metadata.update(
        {
            "sha256": file_sha256(path),
            "bytes": path.stat().st_size,
        }
    )
    record["feedback"] = _merge_feedback(
        record.get("feedback", {}),
        _manifest_feedback(payload),
    )


def _merge_feedback(left: Any, right: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(left) if isinstance(left, Mapping) else {}
    for key, value in right.items():
        if isinstance(merged.get(key), Mapping) and isinstance(value, Mapping):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def _execution_gate(stage_id: str, payload: Mapping[str, Any], decision: str) -> str:
    """Return whether this artifact may feed its declared downstream stage.

    W0 deliberately contains signal-asset discovery as evidence, but its
    downstream scope contract is still usable when the discovery says 2403 is
    unresolved.  Signal completeness remains W2's promotion gate.
    """

    if stage_id == "W0" and payload.get("schema") == "torii.hamburg-named-corridor-scope/v1":
        nodes = payload.get("nodes")
        road_scope = payload.get("official_road_scope")
        if isinstance(nodes, list) and len(nodes) == 3 and isinstance(road_scope, Mapping):
            return "pass"
    return "pass" if decision == "pass" else "blocked"


def _manifest_decision(status: str, gate: str) -> str:
    if gate == "pass" and status in {"pass", "ready", "complete"}:
        return "pass"
    if status in {"blocked", "fail", "error"} or gate == "blocked":
        return "blocked"
    if status in {"partial", "review_ready", "review_required"}:
        return "review_required"
    return "blocked"


def _stage_gate(record: Mapping[str, Any]) -> str:
    return "pass" if record.get("execution_gate") == "pass" else "blocked"


def _manifest_reason(payload: Mapping[str, Any]) -> str | None:
    for key in ("execution_gate_reason", "reason", "error", "next_stage", "next_action"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    missing_nodes = payload.get("missing_required_node_ids")
    if isinstance(missing_nodes, list) and missing_nodes:
        return f"missing_required_node_ids={missing_nodes}"
    incomplete_streams = payload.get("incomplete_stream_ids")
    if isinstance(incomplete_streams, list) and incomplete_streams:
        return f"incomplete_stream_ids={incomplete_streams}"
    publication_gap = payload.get("publication_gap")
    if isinstance(publication_gap, Mapping):
        decision = publication_gap.get("decision")
        if isinstance(decision, str) and decision.strip():
            return f"publication_gap.decision={decision.strip()}"
    for container_key in ("gates", "signal_assets", "scope_evidence"):
        container = payload.get(container_key)
        if isinstance(container, Mapping):
            for key in ("reason", "decision", "missing_count_node_ids", "unresolved_node_ids"):
                value = container.get(key)
                if value not in (None, [], {}, ""):
                    return f"{container_key}.{key}={value}"
    return None


def _manifest_feedback(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Extract bounded machine feedback for the next Codex re-plan.

    Stage manifests are deliberately not copied wholesale into the ledger:
    large event inventories and source payloads belong beside their stage.  The
    ledger keeps only the fields that tell the next run why it stopped and what
    evidence must be resolved.
    """

    feedback: dict[str, Any] = {}
    for key in (
        "execution_gate_reason",
        "reason",
        "error",
        "next_stage",
        "next_action",
        "missing_required_node_ids",
        "unresolved_node_ids",
        "resolved_node_ids",
        "incomplete_stream_ids",
        "failed_stream_ids",
    ):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            feedback[key] = value
    for key in ("publication_gap", "gates", "quality_gate"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            selected = {
                subkey: value[subkey]
                for subkey in ("decision", "reason", "next_action", "missing_required_node_ids", "status")
                if subkey in value and value[subkey] not in (None, "", [], {})
            }
            if selected:
                feedback[key] = selected
    selections = payload.get("selections")
    if isinstance(selections, list):
        selected_node_ids = [
            str(row.get("selected_node", {}).get("node_id"))
            for row in selections
            if isinstance(row, Mapping)
            and isinstance(row.get("selected_node"), Mapping)
            and row["selected_node"].get("node_id") not in (None, "")
        ]
        if selected_node_ids:
            feedback["official_node_identity"] = {
                "decision": payload.get("decision"),
                "human_action_required": payload.get("human_action_required"),
                "selected_node_ids": selected_node_ids,
            }
    return feedback


def _first_invalid_stage(stages: Mapping[str, Mapping[str, Any]]) -> str | None:
    for stage_id in STAGE_DEPENDENCIES:
        record = stages[stage_id]
        if record.get("execution_gate") != "pass":
            return stage_id
        if record.get("effective_status") == "not_run":
            return stage_id
    return None


def _replan_summary(
    stages: Mapping[str, Mapping[str, Any]],
    *,
    next_action: Mapping[str, Any],
    changed: set[str],
    invalidated: set[str],
    first_invalid_stage: str | None,
) -> dict[str, Any]:
    """Describe the smallest safe resume action after the current audit."""

    feedback = stages.get(first_invalid_stage, {}) if first_invalid_stage else {}
    return {
        "required": bool(first_invalid_stage or changed or invalidated),
        "first_invalid_stage": first_invalid_stage,
        "resume_action": next_action.get("action"),
        "changed_stages": sorted(changed, key=_stage_sort_key),
        "invalidated_downstream_stages": sorted(invalidated, key=_stage_sort_key),
        "feedback": feedback.get("feedback", {}),
    }


def _read_previous_plan(path: Path) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HamburgExecutionWorkflowError(f"cannot read previous execution plan: {path}") from exc
    if not isinstance(payload, Mapping) or payload.get("schema") != HAMBURG_EXECUTION_WORKFLOW_SCHEMA:
        raise HamburgExecutionWorkflowError("previous execution plan has an incompatible schema")
    return payload


def _changed_stage_ids(previous: Mapping[str, Any] | None, current: Mapping[str, Mapping[str, Any]]) -> set[str]:
    if previous is None:
        return set()
    old_stages = previous.get("stages")
    if not isinstance(old_stages, Mapping):
        return set(current)
    changed: set[str] = set()
    for stage_id, record in current.items():
        old = old_stages.get(stage_id)
        if not isinstance(old, Mapping):
            if record.get("status") != "not_run":
                changed.add(stage_id)
            continue
        if (
            old.get("manifest_sha256") != record.get("manifest_sha256")
            or _feedback_manifest_sha256(old) != _feedback_manifest_sha256(record)
        ):
            changed.add(stage_id)
    return changed


def _feedback_manifest_sha256(
    record: Mapping[str, Any],
) -> tuple[tuple[str, str | None], ...] | None:
    """Return the hash identity of every auxiliary feedback manifest.

    A stage may collect several independent audits (for example, a historical
    asset census and an official-node identity refresh).  Comparing only the
    legacy singular ``feedback_manifest`` silently ignored changes once the
    second audit was attached.  Keep the input order deterministic and include
    missing-file entries as ``None`` so that a later materialization also
    invalidates the plan.
    """

    manifests = record.get("feedback_manifests")
    if isinstance(manifests, list):
        identities: list[tuple[str, str | None]] = []
        for manifest in manifests:
            if not isinstance(manifest, Mapping) or not manifest.get("path"):
                continue
            value = manifest.get("sha256")
            identities.append((str(manifest["path"]), str(value) if value else None))
        if identities:
            return tuple(identities)

    # Backwards compatibility for plans written before the plural field was
    # introduced.
    feedback_manifest = record.get("feedback_manifest")
    if not isinstance(feedback_manifest, Mapping) or not feedback_manifest.get("path"):
        return None
    value = feedback_manifest.get("sha256")
    return ((str(feedback_manifest["path"]), str(value) if value else None),)


def _downstream_closure(changed: set[str]) -> set[str]:
    invalidated = set(changed)
    changed_again = True
    while changed_again:
        changed_again = False
        for stage_id, dependencies in STAGE_DEPENDENCIES.items():
            if stage_id not in invalidated and any(dependency in invalidated for dependency in dependencies):
                invalidated.add(stage_id)
                changed_again = True
    return invalidated


def _next_action(stages: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    for stage_id in STAGE_DEPENDENCIES:
        record = stages[stage_id]
        if record.get("execution_gate") != "pass" and record.get("effective_status") != "not_run":
            return {
                "stage_id": stage_id,
                "status": "blocked",
                "action": "resolve_stage_gate",
                "blocked_by": record.get("blocked_by", {stage_id: record.get("decision")}),
            }
        if record.get("effective_status") == "not_run":
            if record.get("readiness") == "ready":
                return {
                    "stage_id": stage_id,
                    "status": "ready",
                    "action": f"run_{STAGE_NAMES[stage_id]}",
                }
            return {
                "stage_id": stage_id,
                "status": "blocked",
                "action": "resolve_dependency_gate",
                "blocked_by": record.get("blocked_by", {}),
            }
    return {"stage_id": None, "status": "complete", "action": "none"}


def _stage_sort_key(stage_id: str) -> tuple[int, str]:
    return (int(stage_id[1:]), stage_id)


__all__ = [
    "HAMBURG_EXECUTION_WORKFLOW_ID",
    "HAMBURG_EXECUTION_WORKFLOW_SCHEMA",
    "HamburgExecutionWorkflowError",
    "materialize_hamburg_execution_plan",
]

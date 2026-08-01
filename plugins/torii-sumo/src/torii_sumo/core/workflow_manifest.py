from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifact_io import relative_or_absolute_path, write_json_atomic

WORKFLOW_MANIFEST_SCHEMA = "torii.workflow-manifest/v1"
WORKFLOW_LATEST_SCHEMA = "torii.workflow-latest/v1"
WORKFLOW_RESULT_SCHEMA = "torii.workflow-result/v1"

WORKFLOW_STATUSES = (
    "complete",
    "incomplete",
    "blocked",
    "invalid",
    "review_required",
    "unsupported",
    "failed",
    "stale",
)

EVIDENCE_SECTIONS = (
    "source_evidence",
    "parsed_observations",
    "inferred_facts",
    "repair_candidates",
    "accepted_changes",
    "rejected_changes",
    "unresolved_uncertainty",
    "simulation_diagnostics",
    "product_acceptance_gates",
)

REASONING_CHAIN = (
    "source",
    "observation",
    "interpretation",
    "candidate",
    "check",
    "decision",
    "applied_change",
    "validation",
    "claim",
)

STAGE_CONTRACTS: tuple[dict[str, Any], ...] = (
    {
        "stage_id": "intake",
        "version": 1,
        "inputs": ["user_request", "workflow_config", "source_artifacts"],
        "output_schema": "torii.workflow-intake/v1",
        "preconditions": ["user_request is non-empty", "output directory is writable"],
        "postconditions": ["request fingerprint is recorded", "source artifact identities are recorded"],
        "evidence_consumed": ["source_evidence"],
        "evidence_produced": ["request_fingerprint"],
        "allowed_side_effects": ["create the workflow run directory"],
        "failure_status": "invalid",
        "retry_policy": "retry after correcting invalid input",
        "cache_policy": "content-addressed by request fingerprint",
    },
    {
        "stage_id": "plan",
        "version": 1,
        "inputs": ["request_fingerprint", "user_request"],
        "output_schema": "torii.workflow-plan/v1",
        "preconditions": ["intake is complete"],
        "postconditions": ["detected workflow and tool chain are explicit"],
        "evidence_consumed": ["request_fingerprint"],
        "evidence_produced": ["workflow_plan"],
        "allowed_side_effects": [],
        "failure_status": "unsupported",
        "retry_policy": "retry after changing the request or adding a workflow recipe",
        "cache_policy": "reuse when the request fingerprint is unchanged",
    },
    {
        "stage_id": "execute",
        "version": 1,
        "inputs": ["workflow_plan", "source_artifacts"],
        "output_schema": WORKFLOW_RESULT_SCHEMA,
        "preconditions": ["plan is complete", "required source evidence is available"],
        "postconditions": ["the executor result is persisted", "generated artifact identities are recorded"],
        "evidence_consumed": ["source_evidence", "workflow_plan"],
        "evidence_produced": [
            "parsed_observations",
            "inferred_facts",
            "repair_candidates",
            "simulation_diagnostics",
        ],
        "allowed_side_effects": ["write only within declared output and work directories"],
        "failure_status": "failed",
        "retry_policy": "retry failed or incomplete execution with the same request fingerprint",
        "cache_policy": "reuse a fresh terminal result unless force is true",
    },
    {
        "stage_id": "assess",
        "version": 1,
        "inputs": ["executor result", "artifact identities"],
        "output_schema": "torii.workflow-assessment/v1",
        "preconditions": ["an executor result or executor failure is persisted"],
        "postconditions": ["workflow status, blockers, review items, and claim boundary are explicit"],
        "evidence_consumed": [
            "parsed_observations",
            "inferred_facts",
            "repair_candidates",
            "simulation_diagnostics",
        ],
        "evidence_produced": [
            "accepted_changes",
            "rejected_changes",
            "unresolved_uncertainty",
            "product_acceptance_gates",
        ],
        "allowed_side_effects": [],
        "failure_status": "invalid",
        "retry_policy": "rerun after evidence or contract correction",
        "cache_policy": "recompute when the executor result identity changes",
    },
    {
        "stage_id": "publish",
        "version": 1,
        "inputs": ["workflow assessment", "executor result"],
        "output_schema": WORKFLOW_MANIFEST_SCHEMA,
        "preconditions": ["assessment is complete"],
        "postconditions": ["manifest and latest pointer are written atomically"],
        "evidence_consumed": ["all evidence sections"],
        "evidence_produced": ["workflow manifest"],
        "allowed_side_effects": ["write manifest, result, and latest pointer"],
        "failure_status": "failed",
        "retry_policy": "retry the atomic write",
        "cache_policy": "do not rewrite a fresh terminal manifest on resume",
    },
)

_TERMINAL_CACHE_STATUSES = {
    "complete",
    "blocked",
    "invalid",
    "review_required",
    "unsupported",
}
_GATE_FAILURE_VALUES = {"fail", "failed", "blocked", "invalid", "rejected", "unsafe"}
_REVIEW_VALUES = {"review_required", "review-required", "pending_review", "review_pending", "pending"}
_PATH_KEY_SUFFIXES = ("_file", "_path", "_files", "_paths")
_EXPLICIT_PATH_KEYS = {
    "net_file",
    "osm_file",
    "sumocfg_file",
    "json_path",
    "markdown_path",
    "artifacts",
    "evidence_files",
    "input_artifacts",
    "output_artifacts",
    "official_inventory_csv",
    "signal_plan_csv",
    "field_evidence_csv",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_managed_workflow(
    *,
    user_request: str,
    output_dir: Path,
    workflow_name: str,
    tool_chain: Sequence[str],
    request_config: Mapping[str, Any],
    executor: Callable[..., Mapping[str, Any]],
    executor_kwargs: Mapping[str, Any],
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Run one existing Torii executor behind a content-addressed workflow manifest.

    The wrapper does not reinterpret SUMO evidence or authorize repairs. It
    records the existing result, verifies artifact identity, and maps the
    result to one shared status model.
    """

    request_text = " ".join(user_request.split())
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_artifacts = collect_config_artifacts(request_config, output)
    missing_source_artifacts = [
        dict(item) for item in source_artifacts if item.get("state") == "missing"
    ]
    fingerprint_payload = {
        "user_request": request_text,
        "workflow_name": workflow_name,
        "tool_chain": list(tool_chain),
        "request_config": _json_safe(request_config),
        "source_artifacts": [
            {
                "label": item["label"],
                "path": item["path"],
                "state": item["state"],
                "sha256": item.get("sha256"),
                "bytes": item.get("bytes"),
            }
            for item in source_artifacts
        ],
    }
    request_fingerprint = _sha256_json(fingerprint_payload)
    run_id = request_fingerprint[:16]
    workflow_root = output / "torii-workflow"
    run_dir = workflow_root / run_id
    manifest_file = run_dir / "manifest.json"
    result_file = run_dir / "result.json"
    latest_file = workflow_root / "latest.json"

    previous_manifest: dict[str, Any] | None = None
    if manifest_file.is_file():
        try:
            previous_manifest = _read_json_object(manifest_file)
        except (OSError, ValueError, json.JSONDecodeError):
            if not force:
                return _invalid_manifest_outcome(manifest_file, run_id)

    if previous_manifest is not None and resume and not force:
        inspection = inspect_workflow_manifest(manifest_file)
        if inspection["status"] == "stale":
            return _outcome_from_manifest(
                previous_manifest,
                manifest_file=manifest_file,
                result_file=result_file,
                execution="not_run",
                status_override="stale",
                blockers=inspection["blockers"],
                next_actions=["Rerun torii_workflow_run with force=true after reviewing the stale artifacts."],
            )
        if inspection["status"] == "invalid":
            return _outcome_from_manifest(
                previous_manifest,
                manifest_file=manifest_file,
                result_file=result_file,
                execution="not_run",
                status_override="invalid",
                blockers=inspection["blockers"],
                next_actions=["Correct or remove the invalid manifest before retrying."],
            )
        if str(previous_manifest.get("status")) in _TERMINAL_CACHE_STATUSES:
            return _outcome_from_manifest(
                previous_manifest,
                manifest_file=manifest_file,
                result_file=result_file,
                execution="resumed",
            )

    run_dir.mkdir(parents=True, exist_ok=True)
    history = _attempt_history(previous_manifest)
    if previous_manifest is not None:
        history.append(
            {
                "attempt": int(previous_manifest.get("attempt", 1)),
                "status": str(previous_manifest.get("status", "invalid")),
                "blockers": list(previous_manifest.get("blockers", [])),
            }
        )
    attempt = int(previous_manifest.get("attempt", 0)) + 1 if previous_manifest else 1

    initial_manifest = _build_manifest(
        run_id=run_id,
        request_fingerprint=request_fingerprint,
        workflow_name=workflow_name,
        user_request=request_text,
        tool_chain=tool_chain,
        request_config=request_config,
        source_artifacts=source_artifacts,
        output_dir=output,
        result_file=result_file,
        status="incomplete",
        claim_status="blocked",
        legacy_result={},
        evidence=_empty_evidence(source_artifacts),
        blockers=["execute stage has not completed"],
        review_items=[],
        next_actions=["Run the planned executor."],
        attempt=attempt,
        history=history,
        stage_runs=_stage_runs("incomplete", initial=True),
    )
    write_json_atomic(manifest_file, initial_manifest, ensure_ascii=False, sort_keys=True)
    _write_latest(latest_file, manifest_file, run_id, request_fingerprint, output)

    try:
        raw_result = executor(**dict(executor_kwargs))
        if not isinstance(raw_result, Mapping):
            raise TypeError("workflow executor must return a mapping")
        legacy_result = _json_safe(dict(raw_result))
    except Exception as exc:  # The manifest is the failure handoff for MCP callers.
        legacy_result = {
            "status": "failed",
            "claim_status": "blocked",
            "execution_status": "executor_exception",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        write_json_atomic(
            result_file,
            {"schema": WORKFLOW_RESULT_SCHEMA, "result": legacy_result},
            ensure_ascii=False,
            sort_keys=True,
        )
        result_identity = artifact_identity(
            result_file,
            base_dir=output,
            label="workflow_result",
            role="output",
            evidence_kind="parsed_observation",
            producer_stage="execute",
        )
        evidence = classify_evidence(legacy_result, source_artifacts, result_identity)
        manifest = _build_manifest(
            run_id=run_id,
            request_fingerprint=request_fingerprint,
            workflow_name=workflow_name,
            user_request=request_text,
            tool_chain=tool_chain,
            request_config=request_config,
            source_artifacts=source_artifacts,
            output_dir=output,
            result_file=result_file,
            status="failed",
            claim_status="blocked",
            legacy_result=legacy_result,
            evidence=evidence,
            blockers=[f"executor_exception: {type(exc).__name__}: {exc}"],
            review_items=[],
            next_actions=["Correct the executor failure, then rerun with the same inputs."],
            attempt=attempt,
            history=history,
            stage_runs=_stage_runs("failed"),
        )
        write_json_atomic(manifest_file, manifest, ensure_ascii=False, sort_keys=True)
        _write_latest(latest_file, manifest_file, run_id, request_fingerprint, output)
        return _outcome_from_manifest(
            manifest,
            manifest_file=manifest_file,
            result_file=result_file,
            execution="failed",
        )

    write_json_atomic(
        result_file,
        {"schema": WORKFLOW_RESULT_SCHEMA, "result": legacy_result},
        ensure_ascii=False,
        sort_keys=True,
    )
    result_identity = artifact_identity(
        result_file,
        base_dir=output,
        label="workflow_result",
        role="output",
        evidence_kind="parsed_observation",
        producer_stage="execute",
    )
    output_artifacts, missing_references = collect_result_artifacts(legacy_result, output)
    output_artifacts.append(result_identity)
    output_artifacts = _deduplicate_artifacts(output_artifacts)

    all_missing_references = [*missing_source_artifacts, *missing_references]
    status, blockers, review_items, next_actions = assess_result(
        legacy_result,
        missing_references=all_missing_references,
    )
    evidence = classify_evidence(legacy_result, source_artifacts, result_identity)
    claim_status = _normalized_claim_status(status, legacy_result.get("claim_status"))
    manifest = _build_manifest(
        run_id=run_id,
        request_fingerprint=request_fingerprint,
        workflow_name=workflow_name,
        user_request=request_text,
        tool_chain=tool_chain,
        request_config=request_config,
        source_artifacts=source_artifacts,
        output_dir=output,
        result_file=result_file,
        status=status,
        claim_status=claim_status,
        legacy_result=legacy_result,
        evidence=evidence,
        blockers=blockers,
        review_items=review_items,
        next_actions=next_actions,
        attempt=attempt,
        history=history,
        stage_runs=_stage_runs(status),
        output_artifacts=output_artifacts,
        missing_references=all_missing_references,
    )
    write_json_atomic(manifest_file, manifest, ensure_ascii=False, sort_keys=True)
    _write_latest(latest_file, manifest_file, run_id, request_fingerprint, output)
    return _outcome_from_manifest(
        manifest,
        manifest_file=manifest_file,
        result_file=result_file,
        execution="executed",
    )


def inspect_workflow_manifest(manifest_file: Path) -> dict[str, Any]:
    path = Path(manifest_file).expanduser().resolve()
    try:
        manifest = _read_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "schema": WORKFLOW_MANIFEST_SCHEMA,
            "status": "invalid",
            "manifest_file": str(path),
            "blockers": [f"manifest_invalid: {exc}"],
            "stale_artifacts": [],
            "next_actions": ["Correct or replace the invalid manifest."],
        }
    errors = validate_manifest_structure(manifest)
    if errors:
        return {
            "schema": WORKFLOW_MANIFEST_SCHEMA,
            "status": "invalid",
            "manifest_file": str(path),
            "run_id": str(manifest.get("run_id", "")),
            "blockers": errors,
            "stale_artifacts": [],
            "next_actions": ["Correct or replace the invalid manifest."],
        }

    base_dir = _resolve_stored_path(str(manifest["artifact_base_dir"]), path.parent)
    stale: list[dict[str, Any]] = []
    for identity in manifest.get("artifacts", []):
        artifact_path = _resolve_identity_path(identity, base_dir)
        reason = ""
        actual_sha256 = ""
        actual_bytes: int | None = None
        if not artifact_path.is_file():
            reason = "missing"
        else:
            try:
                actual_sha256 = file_sha256(artifact_path)
                actual_bytes = artifact_path.stat().st_size
            except OSError as exc:
                reason = f"unreadable: {exc}"
            else:
                if actual_sha256 != identity.get("sha256"):
                    reason = "sha256_mismatch"
                elif actual_bytes != identity.get("bytes"):
                    reason = "size_mismatch"
        if reason:
            stale.append(
                {
                    "label": identity.get("label", ""),
                    "path": str(artifact_path),
                    "reason": reason,
                    "expected_sha256": identity.get("sha256", ""),
                    "actual_sha256": actual_sha256,
                    "expected_bytes": identity.get("bytes"),
                    "actual_bytes": actual_bytes,
                }
            )
    if stale:
        return {
            "schema": WORKFLOW_MANIFEST_SCHEMA,
            "status": "stale",
            "manifest_file": str(path),
            "run_id": str(manifest.get("run_id", "")),
            "claim_status": "blocked",
            "blockers": ["one or more hash-bound artifacts changed or disappeared"],
            "stale_artifacts": stale,
            "next_actions": ["Review the stale artifacts, then rerun with force=true."],
        }
    return {
        "schema": WORKFLOW_MANIFEST_SCHEMA,
        "status": str(manifest["status"]),
        "manifest_file": str(path),
        "run_id": str(manifest["run_id"]),
        "workflow_name": str(manifest["workflow_name"]),
        "claim_status": str(manifest["claim_status"]),
        "blockers": list(manifest.get("blockers", [])),
        "review_items": list(manifest.get("review_items", [])),
        "stale_artifacts": [],
        "next_actions": list(manifest.get("next_actions", [])),
        "result_file": str(_resolve_stored_path(str(manifest["result_file"]), base_dir)),
        "evidence_summary": {
            name: len(manifest.get("evidence", {}).get(name, []))
            for name in EVIDENCE_SECTIONS
        },
    }


def resolve_latest_manifest(workflow_dir: Path) -> Path:
    root = Path(workflow_dir).expanduser().resolve()
    latest_file = root / "torii-workflow" / "latest.json"
    latest = _read_json_object(latest_file)
    if latest.get("schema") != WORKFLOW_LATEST_SCHEMA:
        raise ValueError(f"latest pointer schema must be {WORKFLOW_LATEST_SCHEMA}")
    stored = str(latest.get("manifest_file", ""))
    if not stored:
        raise ValueError("latest pointer does not name a manifest")
    return _resolve_stored_path(stored, root)


def validate_manifest_structure(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema") != WORKFLOW_MANIFEST_SCHEMA:
        errors.append(f"manifest schema must be {WORKFLOW_MANIFEST_SCHEMA}")
    if str(manifest.get("status")) not in WORKFLOW_STATUSES:
        errors.append("manifest status is invalid")
    for key in ("run_id", "request_fingerprint", "workflow_name", "claim_status", "artifact_base_dir", "result_file"):
        if not isinstance(manifest.get(key), str) or not str(manifest.get(key)).strip():
            errors.append(f"manifest field {key} must be a non-empty string")
    stages = manifest.get("stage_runs")
    if not isinstance(stages, list) or [item.get("stage_id") for item in stages if isinstance(item, Mapping)] != [
        contract["stage_id"] for contract in STAGE_CONTRACTS
    ]:
        errors.append("manifest stage_runs do not match the canonical stage order")
    evidence = manifest.get("evidence")
    if not isinstance(evidence, Mapping):
        errors.append("manifest evidence must be an object")
    else:
        for name in EVIDENCE_SECTIONS:
            if not isinstance(evidence.get(name), list):
                errors.append(f"manifest evidence section {name} must be a list")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("manifest artifacts must be a list")
    else:
        for index, identity in enumerate(artifacts):
            if not isinstance(identity, Mapping):
                errors.append(f"artifact {index} must be an object")
                continue
            sha256 = identity.get("sha256")
            if not isinstance(sha256, str) or len(sha256) != 64:
                errors.append(f"artifact {index} has an invalid sha256")
            if not isinstance(identity.get("bytes"), int) or int(identity.get("bytes", -1)) < 0:
                errors.append(f"artifact {index} has invalid bytes")
            if not isinstance(identity.get("path"), str) or not identity.get("path"):
                errors.append(f"artifact {index} has an invalid path")
    return errors


def assess_result(
    result: Mapping[str, Any],
    *,
    missing_references: Sequence[Mapping[str, Any]] = (),
) -> tuple[str, list[str], list[dict[str, Any]], list[str]]:
    legacy_status = str(result.get("status", "incomplete")).strip().lower().replace("-", "_")
    execution_status = str(result.get("execution_status", "")).strip().lower()
    claim_status = str(result.get("claim_status", "")).strip().lower().replace("-", "_")
    blockers = _collect_blockers(result)
    for item in missing_references:
        blockers.append(f"missing_artifact: {item.get('label')}: {item.get('path')}")
    review_items = _collect_review_items(result)
    gate_items = _collect_gate_items(result)
    gate_failures = [item for item in gate_items if item["value"] in _GATE_FAILURE_VALUES]
    gate_reviews = [item for item in gate_items if item["value"] in _REVIEW_VALUES]
    evidence_conflicts = _as_list(result.get("evidence_conflicts")) or _as_list(result.get("conflicting_evidence"))

    if missing_references and legacy_status in {"pass", "complete", "success"}:
        blockers.append("executor reported success but one or more declared artifacts are missing")
        status = "invalid"
    elif evidence_conflicts:
        blockers.extend(f"conflicting_evidence: {item}" for item in evidence_conflicts)
        status = "invalid"
    elif "invalid" in execution_status or legacy_status == "invalid":
        status = "invalid"
    elif legacy_status in {"unsupported", "not_supported"}:
        status = "unsupported"
    elif legacy_status in {"fail", "failed", "error"}:
        status = "failed"
    elif legacy_status in {"incomplete", "partial", "not_run", "unknown", ""}:
        status = "incomplete"
    elif legacy_status == "blocked" or claim_status in {"blocked", "construction_invalid", "claim_overreach"}:
        status = "blocked"
    elif gate_failures:
        status = "blocked"
        blockers.extend(f"gate_failed: {item['key']}={item['value']}" for item in gate_failures)
    elif review_items or gate_reviews or claim_status in {"review_required", "review_pending"}:
        status = "review_required"
    elif legacy_status in {"pass", "complete", "success"}:
        status = "complete"
    else:
        status = "incomplete"

    blockers = _deduplicate_strings(blockers)
    if status == "complete":
        next_actions = ["Use the recorded claim boundary. Do not extend the claim beyond the manifest evidence."]
    elif status == "review_required":
        next_actions = ["Complete the listed human review items, record decisions, then rerun the blocked gate."]
    elif status == "blocked":
        next_actions = ["Resolve the listed blockers before continuing to a dependent stage."]
    elif status == "invalid":
        next_actions = ["Correct the inconsistent configuration, result, or artifact contract before rerunning."]
    elif status == "failed":
        next_actions = ["Correct the failed executor stage, then rerun with the same inputs."]
    elif status == "unsupported":
        next_actions = ["Use a supported workflow or add an explicit workflow recipe and contract."]
    else:
        next_actions = ["Resume the first incomplete stage."]
    return status, blockers, review_items, next_actions


def classify_evidence(
    result: Mapping[str, Any],
    source_artifacts: Sequence[Mapping[str, Any]],
    result_identity: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    evidence = _empty_evidence(source_artifacts)
    evidence["parsed_observations"].append(
        {
            "id": "executor-result",
            "source": "execute",
            "artifact": dict(result_identity),
            "description": "Persisted raw executor result. Interpretation remains separate.",
        }
    )
    for key in ("detected_workflow", "network_plan", "resolved_spec", "workflow_description"):
        if key in result:
            evidence["inferred_facts"].append({"key": key, "value": _json_safe(result[key]), "source": "executor_result"})

    candidate_items = _candidate_items(result)
    evidence["repair_candidates"].extend(candidate_items)
    promotion_items = _promotion_items(result)
    accepted = [item for item in promotion_items if item["decision"] in {"pass", "promote", "promoted", "accepted"}]
    rejected = [item for item in promotion_items if item["decision"] in _GATE_FAILURE_VALUES | {"reject", "rejected"}]
    evidence["accepted_changes"].extend(accepted)
    evidence["rejected_changes"].extend(rejected)

    for key, value in _walk_mapping(result):
        folded = key.casefold()
        if any(token in folded for token in ("warning", "missing", "blocker", "uncertainty", "manual_review")):
            if value not in (None, "", [], {}, 0, False):
                evidence["unresolved_uncertainty"].append({"key": key, "value": _json_safe(value)})
        if any(token in folded for token in ("sumo", "routeability", "teleport", "collision", "tripinfo")):
            if value not in (None, "", [], {}):
                evidence["simulation_diagnostics"].append({"key": key, "value": _json_safe(value)})
        if _is_gate_key(folded):
            if value not in (None, "", [], {}):
                evidence["product_acceptance_gates"].append({"key": key, "value": _json_safe(value)})
    for section in EVIDENCE_SECTIONS:
        evidence[section] = _deduplicate_records(evidence[section])
    return evidence


def collect_config_artifacts(config: Mapping[str, Any], base_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for key, value in _walk_mapping(config):
        if not _is_path_key(key.casefold()):
            continue
        for path_text in _path_values(value):
            if not path_text or _looks_like_url(path_text):
                continue
            path = Path(path_text).expanduser()
            if path.is_file():
                records.append(
                    artifact_identity(
                        path,
                        base_dir=base_dir,
                        label=key,
                        role="input",
                        evidence_kind="source_evidence",
                        producer_stage="external",
                    )
                    | {"state": "present"}
                )
            else:
                records.append(
                    {
                        "label": key,
                        "path": path_text,
                        "state": "missing",
                        "role": "input",
                        "evidence_kind": "source_evidence",
                        "producer_stage": "external",
                    }
                )
    return _deduplicate_artifacts(records, include_missing=True)


def collect_result_artifacts(
    result: Mapping[str, Any],
    base_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for key, value in _walk_mapping(result):
        if not _is_path_key(key.casefold()):
            continue
        for path_text in _path_values(value):
            if not path_text or _looks_like_url(path_text):
                continue
            path = Path(path_text).expanduser()
            if not path.is_absolute():
                candidates = (base_dir / path, path)
                path = next((candidate for candidate in candidates if candidate.is_file()), path)
            if path.is_file():
                records.append(
                    artifact_identity(
                        path,
                        base_dir=base_dir,
                        label=key,
                        role="output",
                        evidence_kind="generated_artifact",
                        producer_stage="execute",
                    )
                )
            else:
                missing.append({"label": key, "path": path_text})
    return _deduplicate_artifacts(records), _deduplicate_records(missing)


def artifact_identity(
    path: Path,
    *,
    base_dir: Path,
    label: str,
    role: str,
    evidence_kind: str,
    producer_stage: str,
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve(strict=True)
    return {
        "label": label,
        "path": relative_or_absolute_path(resolved, base_dir),
        "sha256": file_sha256(resolved),
        "bytes": resolved.stat().st_size,
        "role": role,
        "evidence_kind": evidence_kind,
        "producer_stage": producer_stage,
    }


def _build_manifest(
    *,
    run_id: str,
    request_fingerprint: str,
    workflow_name: str,
    user_request: str,
    tool_chain: Sequence[str],
    request_config: Mapping[str, Any],
    source_artifacts: Sequence[Mapping[str, Any]],
    output_dir: Path,
    result_file: Path,
    status: str,
    claim_status: str,
    legacy_result: Mapping[str, Any],
    evidence: Mapping[str, Sequence[Mapping[str, Any]]],
    blockers: Sequence[str],
    review_items: Sequence[Mapping[str, Any]],
    next_actions: Sequence[str],
    attempt: int,
    history: Sequence[Mapping[str, Any]],
    stage_runs: Sequence[Mapping[str, Any]],
    output_artifacts: Sequence[Mapping[str, Any]] = (),
    missing_references: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    input_artifacts = [dict(item) for item in source_artifacts if item.get("state") == "present"]
    artifacts = _deduplicate_artifacts([*input_artifacts, *output_artifacts])
    return {
        "schema": WORKFLOW_MANIFEST_SCHEMA,
        "schema_file": "schemas/torii.workflow-manifest.v1.schema.json",
        "status": status,
        "run_id": run_id,
        "request_fingerprint": request_fingerprint,
        "workflow_name": workflow_name,
        "claim_status": claim_status,
        "artifact_base_dir": relative_or_absolute_path(output_dir, result_file.parent),
        "result_file": relative_or_absolute_path(result_file, output_dir),
        "attempt": attempt,
        "attempt_history": [dict(item) for item in history],
        "request": {
            "user_request": user_request,
            "config": _json_safe(request_config),
            "source_artifacts": [dict(item) for item in source_artifacts],
        },
        "plan": {
            "workflow_name": workflow_name,
            "tool_chain": list(tool_chain),
            "execution_model": "managed compatibility adapter",
            "migration_boundary": "legacy executors remain behind the execute stage",
        },
        "reasoning_model": {
            "chain": list(REASONING_CHAIN),
            "rule": "No later simulation success erases missing, rejected, unsafe, or review-required evidence.",
        },
        "stage_contracts": [dict(item) for item in STAGE_CONTRACTS],
        "stage_runs": [dict(item) for item in stage_runs],
        "artifacts": artifacts,
        "missing_referenced_artifacts": [dict(item) for item in missing_references],
        "evidence": {name: [dict(item) for item in evidence.get(name, ())] for name in EVIDENCE_SECTIONS},
        "blockers": _deduplicate_strings(blockers),
        "review_items": [dict(item) for item in review_items],
        "next_actions": list(next_actions),
        "legacy_result_summary": {
            "status": legacy_result.get("status"),
            "execution_status": legacy_result.get("execution_status"),
            "claim_status": legacy_result.get("claim_status"),
            "detected_workflow": legacy_result.get("detected_workflow"),
        },
    }


def _stage_runs(workflow_status: str, *, initial: bool = False) -> list[dict[str, Any]]:
    if initial:
        plan_status = "complete"
        execute_status = "incomplete"
        assess_status = "incomplete"
    elif workflow_status == "unsupported":
        plan_status = "unsupported"
        execute_status = "blocked"
        assess_status = "unsupported"
    else:
        plan_status = "complete"
        execute_status = {
            "failed": "failed",
            "incomplete": "incomplete",
        }.get(workflow_status, "complete")
        assess_status = (
            workflow_status
            if workflow_status in {"blocked", "invalid", "review_required"}
            else "complete"
        )
    return [
        {"stage_id": "intake", "status": "complete"},
        {"stage_id": "plan", "status": plan_status},
        {"stage_id": "execute", "status": execute_status},
        {"stage_id": "assess", "status": assess_status},
        {"stage_id": "publish", "status": "complete"},
    ]


def _write_latest(latest_file: Path, manifest_file: Path, run_id: str, fingerprint: str, output_dir: Path) -> None:
    write_json_atomic(
        latest_file,
        {
            "schema": WORKFLOW_LATEST_SCHEMA,
            "run_id": run_id,
            "request_fingerprint": fingerprint,
            "manifest_file": relative_or_absolute_path(manifest_file, output_dir),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _outcome_from_manifest(
    manifest: Mapping[str, Any],
    *,
    manifest_file: Path,
    result_file: Path,
    execution: str,
    status_override: str | None = None,
    blockers: Sequence[str] | None = None,
    next_actions: Sequence[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if result_file.is_file():
        try:
            payload = _read_json_object(result_file)
            raw = payload.get("result", {})
            if isinstance(raw, Mapping):
                result = dict(raw)
        except (OSError, ValueError, json.JSONDecodeError):
            result = {}
    status = status_override or str(manifest.get("status", "invalid"))
    claim_status = (
        str(manifest.get("claim_status", "blocked"))
        if status == "complete"
        else "blocked"
    )
    return {
        "schema": WORKFLOW_MANIFEST_SCHEMA,
        "status": status,
        "claim_status": claim_status,
        "run_id": str(manifest.get("run_id", "")),
        "workflow_name": str(manifest.get("workflow_name", "")),
        "execution": execution,
        "manifest_file": str(manifest_file),
        "result_file": str(result_file),
        "blockers": list(blockers if blockers is not None else manifest.get("blockers", [])),
        "review_items": list(manifest.get("review_items", [])),
        "next_actions": list(next_actions if next_actions is not None else manifest.get("next_actions", [])),
        "evidence_summary": {
            name: len(manifest.get("evidence", {}).get(name, []))
            for name in EVIDENCE_SECTIONS
        },
        "result": result,
    }


def _invalid_manifest_outcome(manifest_file: Path, run_id: str) -> dict[str, Any]:
    return {
        "schema": WORKFLOW_MANIFEST_SCHEMA,
        "status": "invalid",
        "claim_status": "blocked",
        "run_id": run_id,
        "workflow_name": "",
        "execution": "not_run",
        "manifest_file": str(manifest_file),
        "result_file": str(manifest_file.parent / "result.json"),
        "blockers": ["existing workflow manifest is invalid"],
        "review_items": [],
        "next_actions": ["Correct or remove the invalid manifest before retrying."],
        "evidence_summary": {name: 0 for name in EVIDENCE_SECTIONS},
        "result": {},
    }


def _normalized_claim_status(status: str, legacy_claim_status: Any) -> str:
    if status != "complete":
        return "blocked"
    claim = str(legacy_claim_status or "diagnostic-demo").strip()
    return claim or "diagnostic-demo"


def _empty_evidence(source_artifacts: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    evidence = {name: [] for name in EVIDENCE_SECTIONS}
    evidence["source_evidence"] = [dict(item) for item in source_artifacts]
    return evidence


def _collect_blockers(result: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    for key in ("missing_blockers", "blockers", "blocked_reasons", "errors", "validation_errors"):
        for item in _as_list(result.get(key)):
            blockers.append(f"{key}: {item}")
    reason = result.get("reason") or result.get("blocked_reason") or result.get("error")
    if reason:
        blockers.append(str(reason))
    return blockers


def _collect_review_items(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in ("review_items", "required_manual_reviews", "manual_review_items"):
        for index, value in enumerate(_as_list(result.get(key)), start=1):
            if isinstance(value, Mapping):
                item = _json_safe(dict(value))
            else:
                item = {"description": str(value)}
            item.setdefault("source", key)
            item.setdefault("review_id", f"{key}:{index}")
            items.append(item)
    count = result.get("human_review_required_count")
    if isinstance(count, int) and count > 0 and not items:
        items.append(
            {
                "review_id": "human_review_required_count",
                "source": "human_review_required_count",
                "description": f"The executor reported {count} unresolved human review item(s).",
                "count": count,
            }
        )
    return _deduplicate_records(items)


def _collect_gate_items(result: Mapping[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for key, value in _walk_mapping(result):
        folded = key.casefold()
        if not _is_gate_key(folded):
            continue
        if isinstance(value, str):
            items.append({"key": key, "value": value.strip().lower().replace("-", "_")})
    return _deduplicate_records(items)


def _candidate_items(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key, value in _walk_mapping(result):
        folded = key.casefold()
        if not any(token in folded for token in ("candidate", "variant", "repair")):
            continue
        if any(token in folded for token in ("count", "status", "reason", "gate")):
            continue
        if value not in (None, "", [], {}):
            items.append({"key": key, "value": _json_safe(value), "basis": "executor_result"})
    return _deduplicate_records(items)


def _promotion_items(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key, value in _walk_mapping(result):
        if not isinstance(value, str) or not value.strip():
            continue
        folded = key.casefold()
        normalized = value.strip().lower().replace("-", "_")
        if "promoted_variant" in folded or "accepted_change" in folded or "applied_change" in folded:
            decision = "promoted"
        elif "rejected_change" in folded:
            decision = "rejected"
        elif "promotion" in folded and normalized in _GATE_FAILURE_VALUES | {"reject", "rejected"}:
            decision = "rejected"
        elif "promotion" in folded and normalized in {"promote", "promoted", "accepted"}:
            decision = normalized
        else:
            continue
        item = {"key": key, "decision": decision, "value": value, "basis": "executor_result"}
        if decision == "rejected":
            item["reason"] = normalized
        items.append(item)
    return _deduplicate_records(items)


def _is_gate_key(key: str) -> bool:
    return (
        key == "gate_status"
        or key.endswith("_gate")
        or key.endswith("_gate_status")
        or key.endswith("_promotion_status")
        or key.endswith("automatic_promotion_gate")
        or key.endswith("execution_gate")
    )


def _is_path_key(key: str) -> bool:
    return key in _EXPLICIT_PATH_KEYS or key.endswith(_PATH_KEY_SUFFIXES)


def _path_values(value: Any) -> list[str]:
    if isinstance(value, Path):
        return [str(value)]
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        values: list[str] = []
        for nested in value.values():
            values.extend(_path_values(nested))
        return values
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = []
        for nested in value:
            values.extend(_path_values(nested))
        return values
    return []


def _looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://", "file://"))


def _walk_mapping(value: Mapping[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    for key, nested in value.items():
        current = f"{prefix}.{key}" if prefix else str(key)
        items.append((current, nested))
        if isinstance(nested, Mapping):
            items.extend(_walk_mapping(nested, current))
    return items


def _attempt_history(previous: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not previous:
        return []
    history = previous.get("attempt_history", [])
    return [dict(item) for item in history if isinstance(item, Mapping)] if isinstance(history, list) else []


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _resolve_identity_path(identity: Mapping[str, Any], base_dir: Path) -> Path:
    return _resolve_stored_path(str(identity.get("path", "")), base_dir)


def _resolve_stored_path(value: str, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _deduplicate_strings(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _deduplicate_records(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        record = dict(value)
        key = _canonical_json(record)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def _deduplicate_artifacts(
    values: Sequence[Mapping[str, Any]],
    *,
    include_missing: bool = False,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for value in values:
        record = dict(value)
        if not include_missing and "sha256" not in record:
            continue
        key = (str(record.get("role", "")), str(record.get("label", "")), str(record.get("path", "")))
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]

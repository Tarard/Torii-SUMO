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
import re
from typing import Any, Mapping, Sequence

from .artifact_io import relative_or_absolute_path, write_json_atomic
from .candidate_contracts import file_sha256
from .complete_way_audit import audit_complete_osm_way_filter
from .external_micro_junction_audit import audit_external_micro_junctions


HAMBURG_EXECUTION_WORKFLOW_SCHEMA = "torii.hamburg-sandtorkai-execution-workflow/v2"
HAMBURG_EXECUTION_CONFIG_SCHEMA = "torii.hamburg-digital-twin-workflow-config/v2"
HAMBURG_EXECUTION_WORKFLOW_ID = "hamburg_sandtorkai_2349_2394_2403"

STAGE_DEPENDENCIES: Mapping[str, tuple[str, ...]] = {
    "W0": (),
    "W1": ("W0",),
    "W3a": ("W0",),
    "W2": ("W1",),
    "W3b": ("W1", "W3a"),
    # Route incidence and demand are still produced inside the existing W4
    # replay implementation. Split them only when they have real producers.
    "W4": ("W1", "W2", "W3a", "W3b"),
}

STAGE_NAMES: Mapping[str, str] = {
    "W0": "scope_and_evidence",
    "W1": "official_road_reconstruction",
    "W3a": "count_acquisition",
    "W2": "official_signal_binding",
    "W3b": "detector_binding",
    "W4": "route_demand_and_sumo_replay",
    "W5": "workflow_summary",
}

STAGE_SCHEMAS: Mapping[str, frozenset[str]] = {
    "W0": frozenset({"torii.hamburg-named-corridor-scope/v1"}),
    "W1": frozenset({"torii.hamburg-official-corridor-geometry/v1"}),
    "W3a": frozenset({"torii.hamburg-named-corridor-count-scope/v1"}),
    "W2": frozenset({"torii.hamburg-named-signal-binding/v1"}),
    "W3b": frozenset({"torii.hamburg-named-detector-binding/v1"}),
    "W4": frozenset({"torii.hamburg-named-replay/v2"}),
}

NETWORK_BOUND_STAGES = frozenset({"W1", "W2", "W3b", "W4"})
STAGE_ORDER = (*STAGE_DEPENDENCIES, "W5")
_STAGE_INDEX = {stage_id: index for index, stage_id in enumerate(STAGE_ORDER)}
_STAGE_ID_BY_CASEFOLD = {stage_id.casefold(): stage_id for stage_id in STAGE_ORDER}

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
    "W3a": {
        "code_surfaces": ("core/hamburg_named_count_scope.py",),
        "entrypoints": ("scripts/build_hamburg_named_counts.py",),
        "verification": ("complete official bins", "explicit time window", "source hashes"),
    },
    "W3b": {
        "code_surfaces": (
            "core/hamburg_named_detector_bindings.py",
            "core/digital_twin_mapping.py",
        ),
        "entrypoints": ("scripts/build_hamburg_named_detector_bindings.py",),
        "verification": (
            "W1 network SHA",
            "W3a count-stream SHA",
            "detector-mapping artifact SHA",
            "explicit CRS",
            "unique lane binding",
            "same-location E1/E2",
        ),
    },
    "W4": {
        "code_surfaces": (
            "core/hamburg_named_replay.py",
            "core/route_sampler.py",
            "core/route_sensor_matrix.py",
        ),
        "entrypoints": ("scripts/build_hamburg_named_replay.py",),
        "verification": (
            "W1 network SHA",
            "selected W2, W3a, and W3b manifest identities",
            "W3a simulation-count SHA",
            "approved detector aggregation semantics",
            "signal-event artifact SHA",
            "route incidence and demand",
            "routeability",
            "zero teleports",
            "zero collisions",
            "formal comparison",
        ),
    },
    "W5": {
        "code_surfaces": ("core/hamburg_execution_workflow.py", "server.py"),
        "entrypoints": ("scripts/run_hamburg_execution_plan.py",),
        "verification": ("derived capability matrix", "hash-bound rerun", "downstream invalidation"),
    },
}


class HamburgExecutionWorkflowError(ValueError):
    """Raised when a workflow plan cannot be made hash-safe."""


def _canonical_stage_id(value: object) -> str:
    raw = str(value).strip()
    if raw.casefold() == "w3":
        raise HamburgExecutionWorkflowError(
            "legacy stage W3 was split; provide W3a count acquisition and W3b detector binding manifests"
        )
    stage_id = _STAGE_ID_BY_CASEFOLD.get(raw.casefold())
    if stage_id is None:
        raise HamburgExecutionWorkflowError(f"unknown workflow stage {raw!r}")
    if stage_id == "W5":
        raise HamburgExecutionWorkflowError("W5 is generated automatically and does not accept a manifest")
    return stage_id


def materialize_hamburg_execution_plan_from_config(
    config_file: Path,
    *,
    output_dir: Path | None = None,
    resume: bool | None = None,
) -> dict[str, Any]:
    """Run the existing Hamburg stage ledger from one portable JSON configuration.

    Paths are resolved relative to the configuration file. Focused Hamburg
    modules remain responsible for producing each stage artifact; this facade
    only unifies their evidence, dependencies, and downstream invalidation.
    """

    config_path = Path(config_file).expanduser().resolve(strict=True)
    payload = _read_json_mapping(config_path)
    if payload.get("schema") != HAMBURG_EXECUTION_CONFIG_SCHEMA:
        raise HamburgExecutionWorkflowError(
            f"workflow config schema must be {HAMBURG_EXECUTION_CONFIG_SCHEMA!r}"
        )
    base_dir = config_path.parent
    configured_output = payload.get("output_dir")
    if output_dir is None:
        if not isinstance(configured_output, str) or not configured_output.strip():
            raise HamburgExecutionWorkflowError("workflow config requires output_dir")
        output_dir = _resolve_config_path(base_dir, configured_output)

    raw_stages = payload.get("stages", {})
    if not isinstance(raw_stages, Mapping):
        raise HamburgExecutionWorkflowError("workflow config stages must be an object")
    stage_manifests: dict[str, Path] = {}
    stage_feedback: dict[str, tuple[Path, ...]] = {}
    for raw_stage_id, raw_stage in raw_stages.items():
        stage_id = _canonical_stage_id(raw_stage_id)
        if not isinstance(raw_stage, Mapping):
            raise HamburgExecutionWorkflowError(f"workflow stage {stage_id} must be an object")
        manifest = raw_stage.get("manifest")
        if manifest is not None:
            if not isinstance(manifest, str) or not manifest.strip():
                raise HamburgExecutionWorkflowError(f"workflow stage {stage_id} manifest is invalid")
            if stage_id in stage_manifests:
                raise HamburgExecutionWorkflowError(f"duplicate workflow stage {stage_id}")
            stage_manifests[stage_id] = _resolve_config_path(base_dir, manifest)
        feedback = raw_stage.get("feedback", ())
        if not isinstance(feedback, Sequence) or isinstance(feedback, (str, bytes)):
            raise HamburgExecutionWorkflowError(f"workflow stage {stage_id} feedback must be a list")
        resolved_feedback = tuple(_resolve_config_path(base_dir, str(item)) for item in feedback)
        if resolved_feedback:
            stage_feedback[stage_id] = resolved_feedback

    configured_resume = payload.get("resume", True)
    if resume is None:
        if not isinstance(configured_resume, bool):
            raise HamburgExecutionWorkflowError("workflow config resume must be boolean")
        resume = configured_resume
    return materialize_hamburg_execution_plan(
        output_dir=Path(output_dir),
        stage_manifests=stage_manifests,
        stage_feedback=stage_feedback,
        resume=resume,
        workflow_id=str(payload.get("workflow_id", HAMBURG_EXECUTION_WORKFLOW_ID)),
    )


def _resolve_config_path(base_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base_dir / path).resolve()


def materialize_hamburg_w1_topology_handoff(
    *,
    output_dir: Path,
    candidate_net_file: Path,
    build_spec_file: Path,
    topology_audit_file: Path,
    scope_ledger_file: Path,
    turnaround_audit_file: Path,
    movement_authority_file: Path,
    surface_comparison_file: Path,
    connection_mode_manifest_file: Path,
    sumo_load_report_file: Path,
    movement_smoke_file: Path,
    netedit_review_files: Sequence[Path],
    expected_review_junction_ids: Sequence[str],
) -> dict[str, Any]:
    """Adopt an audited OSM-derived topology as W1 without rebuilding it."""

    candidate = Path(candidate_net_file).expanduser().resolve(strict=True)
    candidate_hash = file_sha256(candidate)
    evidence_paths = {
        "build_spec": Path(build_spec_file).expanduser().resolve(strict=True),
        "topology_feedback": Path(topology_audit_file).expanduser().resolve(strict=True),
        "scope_edge_preservation": Path(scope_ledger_file).expanduser().resolve(strict=True),
        "turnaround_audit": Path(turnaround_audit_file).expanduser().resolve(strict=True),
        "movement_authority": Path(movement_authority_file).expanduser().resolve(strict=True),
        "surface_comparison": Path(surface_comparison_file).expanduser().resolve(strict=True),
        "connection_mode": Path(connection_mode_manifest_file).expanduser().resolve(strict=True),
        "sumo_load": Path(sumo_load_report_file).expanduser().resolve(strict=True),
        "movement_smoke": Path(movement_smoke_file).expanduser().resolve(strict=True),
    }
    evidence = {name: _read_json_mapping(path) for name, path in evidence_paths.items()}
    errors: list[str] = []

    _validate_w1_build_spec(
        evidence["build_spec"],
        spec_path=evidence_paths["build_spec"],
        candidate=candidate,
        candidate_hash=candidate_hash,
        errors=errors,
    )

    topology = evidence["topology_feedback"]
    if topology.get("schema") != "torii.junction-aggregation-preservation/v1" or topology.get("status") != "pass":
        errors.append("topology preservation is not pass")
    _check_candidate_binding(
        topology,
        candidate,
        candidate_hash,
        errors,
        prefix="variant",
        base_dir=evidence_paths["topology_feedback"].parent,
    )
    try:
        topology_source = Path(str(topology.get("source_net_file", ""))).expanduser()
        if not topology_source.is_absolute():
            topology_source = evidence_paths["topology_feedback"].parent / topology_source
        topology_source = topology_source.resolve(strict=True)
    except (OSError, RuntimeError):
        errors.append("topology preservation source path is invalid")
    else:
        if topology.get("source_sha256") != file_sha256(topology_source):
            errors.append("topology preservation source hash mismatch")
    for key in (
        "unexpected_removed_normal_edge_count",
        "lost_shared_connection_count",
        "new_dangling_shared_normal_edge_count",
    ):
        if topology.get(key) != 0:
            errors.append(f"topology preservation {key} is not zero")
    boundary = topology.get("boundary_movement_preservation")
    if (
        not isinstance(boundary, Mapping)
        or boundary.get("status") not in {"pass", "not_applicable"}
        or boundary.get("lost_boundary_movement_count") != 0
        or boundary.get("added_boundary_movement_count") != 0
    ):
        errors.append("topology boundary-movement preservation is not pass")

    scope_ledger = evidence["scope_edge_preservation"]
    scope_final = scope_ledger.get("final_candidate")
    if (
        scope_ledger.get("schema") != "torii.scope-edge-preservation/v1"
        or scope_ledger.get("status") != "pass"
    ):
        errors.append("scope edge-preservation ledger is not pass")
    if not isinstance(scope_final, Mapping):
        errors.append("scope edge-preservation final candidate is missing")
    else:
        try:
            scope_final_path = Path(str(scope_final.get("path", ""))).expanduser()
            if not scope_final_path.is_absolute():
                scope_final_path = (
                    evidence_paths["scope_edge_preservation"].parent / scope_final_path
                )
            scope_final_path = scope_final_path.resolve()
        except (OSError, RuntimeError):
            errors.append("scope edge-preservation final candidate path is invalid")
        else:
            if scope_final_path != candidate:
                errors.append("scope edge-preservation final candidate path mismatch")
        if scope_final.get("sha256") != candidate_hash:
            errors.append("scope edge-preservation final candidate hash mismatch")
    scope_counts = scope_ledger.get("classification_counts")
    if (
        scope_ledger.get("unaccounted_edge_count") != 0
        or not isinstance(scope_counts, Mapping)
        or scope_counts.get("unaccounted") != 0
    ):
        errors.append("scope edge-preservation ledger has unaccounted edges")
    if scope_ledger.get("empty_exclusion_reason_count") != 0:
        errors.append("scope edge-preservation ledger has exclusions without reasons")
    _validate_scope_baseline_binding(
        evidence["build_spec"],
        spec_path=evidence_paths["build_spec"],
        scope_ledger=scope_ledger,
        scope_path=evidence_paths["scope_edge_preservation"],
        errors=errors,
    )

    turnaround = evidence["turnaround_audit"]
    turnaround_scope = turnaround.get("scope")
    if (
        turnaround.get("schema_id") != "torii.external-micro-junction-audit/v2"
        or turnaround.get("status") != "pass"
        or turnaround.get("automatic_promotion_gate") != "pass"
        or not isinstance(turnaround_scope, Mapping)
        or turnaround_scope.get("mode") != "whole_network"
        or turnaround_scope.get("junction_ids") != []
        or turnaround.get("dir_t_turnaround_count") != 0
        or turnaround.get("dir_t_turnarounds") != []
        or turnaround.get("unsupported_turnaround_count") != 0
        or turnaround.get("unused_turnaround_authority_count") != 0
    ):
        errors.append("turnaround audit is not a whole-network zero-turnaround pass")
    try:
        turnaround_source = Path(str(turnaround.get("source_net_file", ""))).expanduser()
        if not turnaround_source.is_absolute():
            turnaround_source = evidence_paths["turnaround_audit"].parent / turnaround_source
        turnaround_source = turnaround_source.resolve()
    except (OSError, RuntimeError):
        errors.append("turnaround audit source path is invalid")
    else:
        if turnaround_source != candidate:
            errors.append("turnaround audit source path mismatch")
    if turnaround.get("source_net_sha256") != candidate_hash:
        errors.append("turnaround audit source hash mismatch")
    try:
        observed_turnaround = audit_external_micro_junctions(candidate)
    except (OSError, ValueError):
        errors.append("independent turnaround rescan failed")
    else:
        observed_scope = observed_turnaround.get("scope")
        if (
            observed_turnaround.get("schema_id")
            != "torii.external-micro-junction-audit/v2"
            or observed_turnaround.get("status") != "pass"
            or observed_turnaround.get("automatic_promotion_gate") != "pass"
            or not isinstance(observed_scope, Mapping)
            or observed_scope.get("mode") != "whole_network"
            or observed_scope.get("junction_ids") != []
            or observed_turnaround.get("dir_t_turnaround_count") != 0
            or observed_turnaround.get("dir_t_turnarounds") != []
            or observed_turnaround.get("unsupported_turnaround_count") != 0
            or observed_turnaround.get("unused_turnaround_authority_count") != 0
        ):
            errors.append(
                "independent turnaround rescan is not a whole-network zero-turnaround pass"
            )

    authority = evidence["movement_authority"]
    authority_id = authority.get("authority_id")
    authority_movements = authority.get("movements")
    authority_evidence = authority.get("source_evidence")
    if (
        authority.get("schema") != "torii.hamburg-movement-authority/v1"
        or authority.get("status") != "review_required"
        or not isinstance(authority_id, str)
        or not authority_id.strip()
        or authority.get("generated_from_candidate") is not False
    ):
        errors.append("movement authority is not an independent review-required ledger")
    evidence_ids: set[str] = set()
    if not isinstance(authority_evidence, list) or not authority_evidence:
        errors.append("movement authority source evidence is empty")
    else:
        for artifact in authority_evidence:
            if not isinstance(artifact, Mapping):
                errors.append("movement authority source evidence artifact is invalid")
                continue
            evidence_id = str(artifact.get("evidence_id", "")).strip()
            if not evidence_id or evidence_id in evidence_ids:
                errors.append("movement authority source evidence IDs are empty or duplicated")
                continue
            evidence_ids.add(evidence_id)
            try:
                artifact_path = Path(str(artifact.get("path", ""))).expanduser()
                if not artifact_path.is_absolute():
                    artifact_path = evidence_paths["movement_authority"].parent / artifact_path
                artifact_path = artifact_path.resolve(strict=True)
            except (OSError, RuntimeError):
                errors.append(f"movement authority source evidence path is invalid: {evidence_id}")
                continue
            if artifact_path == candidate:
                errors.append(f"movement authority source evidence is the candidate: {evidence_id}")
            if artifact.get("sha256") != file_sha256(artifact_path):
                errors.append(f"movement authority source evidence hash mismatch: {evidence_id}")

    expected_movement_keys: list[str] = []
    if not isinstance(authority_movements, list) or not authority_movements:
        errors.append("movement authority movements are empty")
    else:
        for movement in authority_movements:
            if not isinstance(movement, Mapping):
                errors.append("movement authority movement is invalid")
                continue
            movement_key = str(movement.get("movement_key", "")).strip()
            movement_evidence_ids = movement.get("evidence_ids")
            if not movement_key:
                errors.append("movement authority movement key is empty")
            else:
                expected_movement_keys.append(movement_key)
            if (
                not isinstance(movement_evidence_ids, list)
                or not movement_evidence_ids
                or any(str(value) not in evidence_ids for value in movement_evidence_ids)
            ):
                errors.append(f"movement authority evidence binding is invalid: {movement_key}")
    if not expected_movement_keys or len(set(expected_movement_keys)) != len(expected_movement_keys):
        errors.append("movement authority keys are empty or duplicated")

    surface = evidence["surface_comparison"]
    surface_count_keys = (
        "geometry_error_count",
        "junction_junction_overlap_count",
        "external_lane_non_owner_junction_overlap_count",
    )
    surface_counts = [surface.get(key) for key in surface_count_keys]
    surface_has_findings = any(type(value) is int and value > 0 for value in surface_counts)
    expected_surface_status = "fail" if surface_has_findings else "pass"
    if (
        surface.get("schema") != "torii.sumo-surface-overlap-audit/v1"
        or surface.get("audit_engine") != "torii.bevel-strip-and-junction-polygon-area/v2"
        or surface.get("status") != expected_surface_status
        or surface.get("error")
        or any(type(value) is not int or value < 0 for value in surface_counts)
    ):
        errors.append("surface audit is invalid")
    _check_candidate_binding(
        surface,
        candidate,
        candidate_hash,
        errors,
        prefix="source",
        base_dir=evidence_paths["surface_comparison"].parent,
    )
    if surface.get("source_network_mutation") is not False:
        errors.append("surface audit did not preserve the candidate")
    surface_gate = "review_required" if surface_has_findings else "pass"

    connection = evidence["connection_mode"]
    connection_pass = (
        connection.get("schema") == "torii.connection_mode_regression_manifest.v1"
        and connection.get("status") == "pass"
        and connection.get("gate_status") == "pass"
        and connection.get("automatic_promotion_gate") == "pass"
    )
    target_review_only = (
        connection.get("schema") == "torii.connection_mode_regression_manifest.v1"
        and connection.get("status") == "fail"
        and connection.get("gate_status") == "fail"
        and connection.get("automatic_promotion_gate") == "blocked"
        and set(connection.get("blockers") or ()) == {"new_target_scope_review_findings"}
        and not (connection.get("outside_scope_regression_junction_ids") or ())
        and connection.get("outside_scope_new_structural_finding_count") == 0
        and connection.get("target_scope_new_structural_finding_count") == 0
        and connection.get("outside_scope_new_review_finding_count") == 0
        and isinstance(connection.get("target_scope_new_review_finding_count"), int)
        and connection.get("target_scope_new_review_finding_count", 0) > 0
        and set(connection.get("target_scope_flagged_junction_ids") or ()).issubset(
            set(connection.get("requested_target_candidate_junction_ids") or ())
        )
    )
    if not connection_pass and not target_review_only:
        errors.append("connection-mode regression is not pass")
    _check_candidate_binding(
        connection,
        candidate,
        candidate_hash,
        errors,
        prefix="candidate",
        base_dir=evidence_paths["connection_mode"].parent,
    )
    if connection.get("source_network_mutation") is not False:
        errors.append("connection-mode regression did not preserve the source")
    connection_gate = "review_required" if target_review_only else "pass"

    load = evidence["sumo_load"]
    if load.get("schema") != "torii.sumo-load-audit/v1" or load.get("status") != "pass":
        errors.append("SUMO load audit is not pass")
    _check_candidate_binding(
        load,
        candidate,
        candidate_hash,
        errors,
        prefix="source",
        base_dir=evidence_paths["sumo_load"].parent,
    )
    if load.get("source_network_mutation") is not False:
        errors.append("SUMO load audit did not preserve the candidate")

    smoke = evidence["movement_smoke"]
    movement_keys = smoke.get("movement_keys")
    smoke_inputs = smoke.get("inputs")
    smoke_outputs = smoke.get("outputs")
    if (
        smoke.get("schema") != "torii.hamburg-2403-movement-smoke/v1"
        or smoke.get("status") != "pass"
        or smoke.get("automatic_promotion_gate") != "blocked"
        or smoke.get("authority_review_status") != "review_required"
        or smoke.get("vehicle_count") != len(expected_movement_keys)
        or smoke.get("movement_count") != len(expected_movement_keys)
        or smoke.get("vehicle_count") != smoke.get("ended")
        or smoke.get("vehicle_count") != smoke.get("inserted")
        or smoke.get("vehicle_count") != smoke.get("loaded")
        or smoke.get("running") != 0
        or smoke.get("waiting") != 0
        or smoke.get("teleports") != 0
        or smoke.get("collisions") != 0
        or smoke.get("movement_keys_unique") is not True
        or not isinstance(movement_keys, list)
        or set(map(str, movement_keys or ())) != set(expected_movement_keys)
    ):
        errors.append("movement smoke is not a complete zero-error authority run")
    _check_candidate_binding(
        smoke,
        candidate,
        candidate_hash,
        errors,
        prefix="candidate",
        base_dir=evidence_paths["movement_smoke"].parent,
    )
    inspection = smoke.get("inspection")
    if not isinstance(inspection, Mapping) or inspection.get("status") != "pass":
        errors.append("movement smoke output inspection is not pass")
    else:
        inspected_summary = inspection.get("summary")
        inspected_tripinfo = inspection.get("tripinfo")
        if (
            not isinstance(inspected_summary, Mapping)
            or not isinstance(inspected_tripinfo, Mapping)
            or inspected_summary.get("loaded") != smoke.get("vehicle_count")
            or inspected_summary.get("inserted") != smoke.get("vehicle_count")
            or inspected_summary.get("arrived") != smoke.get("vehicle_count")
            or inspected_summary.get("running") != 0
            or inspected_summary.get("waiting") != 0
            or inspected_summary.get("teleports") != 0
            or inspected_summary.get("collisions") != 0
            or inspected_tripinfo.get("trip_count") != smoke.get("vehicle_count")
        ):
            errors.append("movement smoke inspection counts do not match the declared run")
    if not isinstance(smoke_inputs, Mapping) or not isinstance(smoke_outputs, Mapping):
        errors.append("movement smoke artifacts are missing")
    else:
        smoke_artifacts = {
            "route": smoke_inputs.get("route"),
            "movement_authority": smoke_inputs.get("movement_authority"),
            "summary": smoke_outputs.get("summary"),
            "tripinfo": smoke_outputs.get("tripinfo"),
        }
        for name, artifact in smoke_artifacts.items():
            if not isinstance(artifact, Mapping):
                errors.append(f"movement smoke artifact is missing: {name}")
                continue
            try:
                artifact_path = Path(str(artifact.get("path", ""))).expanduser()
                if not artifact_path.is_absolute():
                    artifact_path = evidence_paths["movement_smoke"].parent / artifact_path
                artifact_path = artifact_path.resolve(strict=True)
            except (OSError, RuntimeError):
                errors.append(f"movement smoke artifact path is invalid: {name}")
                continue
            if artifact.get("sha256") != file_sha256(artifact_path):
                errors.append(f"movement smoke artifact hash mismatch: {name}")
        authority_artifact = smoke_artifacts["movement_authority"]
        if isinstance(authority_artifact, Mapping):
            try:
                authority_path = Path(str(authority_artifact.get("path", ""))).expanduser()
                if not authority_path.is_absolute():
                    authority_path = evidence_paths["movement_smoke"].parent / authority_path
                authority_path = authority_path.resolve(strict=True)
            except (OSError, RuntimeError):
                authority_path = Path()
            if (
                authority_path != evidence_paths["movement_authority"]
                or authority_artifact.get("sha256") != file_sha256(evidence_paths["movement_authority"])
            ):
                errors.append("movement smoke is not bound to the independent movement authority")

    review_paths = tuple(Path(path).expanduser().resolve(strict=True) for path in netedit_review_files)
    expected_ids = {str(value) for value in expected_review_junction_ids if str(value)}
    if not review_paths or not expected_ids:
        errors.append("NetEdit review owners are empty")
    actual_review_ids: list[str] = []
    for path in review_paths:
        review = _read_json_mapping(path)
        target = review.get("target_junction")
        target_id = str(target.get("id", "")) if isinstance(target, Mapping) else ""
        actual_review_ids.append(target_id)
        if (
            review.get("schema") != "torii.netedit-background-review.direct/v1"
            or review.get("status") != "review_material_ready"
            or review.get("automatic_promotion_gate") != "blocked"
            or review.get("candidate_unchanged") is not True
            or review.get("candidate_sha256_before") != candidate_hash
            or review.get("candidate_sha256_after") != candidate_hash
            or review.get("mode_images_distinct") is not True
            or review.get("global_keyboard_or_mouse_input_used") is not False
            or review.get("foreground_context_restored") is not True
        ):
            errors.append(f"NetEdit review is not current and non-mutating: {path}")
        try:
            review_candidate = Path(str(review.get("candidate_file", ""))).expanduser()
            if not review_candidate.is_absolute():
                review_candidate = path.parent / review_candidate
            if review_candidate.resolve() != candidate:
                errors.append(f"NetEdit review candidate path mismatch: {path}")
        except (OSError, RuntimeError):
            errors.append(f"NetEdit review candidate path invalid: {path}")
    if len(review_paths) != len(expected_ids) or set(actual_review_ids) != expected_ids:
        errors.append(
            f"NetEdit owner coverage mismatch: expected={sorted(expected_ids)}, actual={sorted(set(actual_review_ids))}"
        )
    if file_sha256(candidate) != candidate_hash:
        errors.append("candidate changed while W1 handoff evidence was checked")
    if errors:
        raise HamburgExecutionWorkflowError("W1 topology handoff rejected: " + "; ".join(errors))

    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_file = output / "hamburg_official_corridor_geometry.manifest.json"
    if manifest_file.exists():
        raise HamburgExecutionWorkflowError(f"W1 topology handoff already exists: {manifest_file}")
    manifest: dict[str, Any] = {
        "schema": "torii.hamburg-official-corridor-geometry/v1",
        "status": "review_ready",
        "execution_gate": "pass",
        "execution_gate_reason": "hash-bound scope, topology, turnaround, movement-authority, SUMO, connection, movement-smoke, and NetEdit-material checks pass; surface findings remain an explicit review gate",
        "claim_status": "osm-continuous-official-evidence-road-topology-review-candidate",
        "automatic_promotion_gate": "blocked",
        "network": {
            "path": relative_or_absolute_path(candidate, manifest_file.parent),
            "sha256": candidate_hash,
        },
        "evidence": {
            name: {
                "path": relative_or_absolute_path(path, manifest_file.parent),
                "sha256": file_sha256(path),
            }
            for name, path in evidence_paths.items()
        },
        "netedit_review": {
            "status": "review_material_ready",
            "junction_ids": sorted(expected_ids),
            "report_count": len(review_paths),
            "reports": [
                {
                    "path": relative_or_absolute_path(path, manifest_file.parent),
                    "sha256": file_sha256(path),
                }
                for path in review_paths
            ],
            "automatic_promotion_gate": "blocked",
        },
        "gates": {
            "scope_edge_preservation": "pass",
            "topology_feedback": "pass",
            "unsupported_turnarounds": "pass",
            "movement_authority": "review_required",
            "surface_overlap": surface_gate,
            "connection_mode": connection_gate,
            "sumo_load": "pass",
            "movement_smoke": "pass",
            "netedit_review_material": "pass",
            "official_2403_signal_assets": "blocked",
            "automatic_promotion": "blocked",
        },
        "routeability": {
            "status": "pass",
            "evidence_status": "review_required",
            "scope": f"{len(expected_movement_keys)} declared evidence-bound lane-level movements",
            "authority_id": authority_id,
            "movement_count": len(expected_movement_keys),
            "teleports": 0,
            "collisions": 0,
        },
        "artifacts": {
            "network": relative_or_absolute_path(candidate, manifest_file.parent),
            "manifest": manifest_file.name,
        },
        "claim_boundary": {
            "proves": [
                "the exact candidate passes the recorded road-topology machine gates",
                "the candidate is reproducible from the recorded build spec and patch hashes",
                "every complete-way scope edge is preserved, internalized, or excluded with a reason",
                "the candidate has no unsupported turnaround or unused turnaround authority",
                "the smoke routes match a hash-bound movement review ledger",
                "all declared physical review owners have current non-mutating NetEdit review material",
                "the candidate may feed fail-closed signal and detector diagnostics",
            ],
            "does_not_prove": [
                "official 2403 signal topology or historical signal timing",
                "that detector streams sharing a SUMO lane are additive or redundant",
                "full corridor demand calibration or final digital-twin promotion",
                "human approval from NetEdit screenshots alone",
                "that inherited surface-overlap findings are geometrically correct",
                "that a machine check alone proves the semantic relationship between the CAD/aerial evidence and every declared movement",
                "movement legality outside the explicitly reviewed 2403 conflict core",
            ],
        },
    }
    write_json_atomic(manifest_file, manifest, ensure_ascii=False, sort_keys=True)
    return {**manifest, "manifest_file": str(manifest_file)}


def _validate_w1_build_spec(
    spec: Mapping[str, Any],
    *,
    spec_path: Path,
    candidate: Path,
    candidate_hash: str,
    errors: list[str],
) -> None:
    if (
        spec.get("schema") != "torii.hamburg-canonical-w1-build/v1"
        or spec.get("status") != "frozen"
    ):
        errors.append("canonical W1 build spec is not frozen")
        return
    scope_policy = spec.get("scope_policy")
    required_scope_policy = {
        "authority": [
            "Hamburg 2024 aerial imagery",
            "Hamburg 2022 road CAD",
        ],
        "osm_role": "continuous road geometry and base topology",
        "acquisition_bbox": [
            9.980106927466423,
            53.540533691913986,
            10.003689463043568,
            53.54865291573397,
        ],
        "clip_source_ways_to_bbox": False,
        "selection_rule": (
            "retain each complete OSM way intersecting the buffered aerial/CAD scope; "
            "never truncate a selected way at the bbox"
        ),
    }
    if not isinstance(scope_policy, Mapping):
        errors.append("canonical W1 build scope policy is missing")
    else:
        for name, expected in required_scope_policy.items():
            if scope_policy.get(name) != expected:
                errors.append(f"canonical W1 build scope policy {name} mismatch")

    output = spec.get("output")
    if not isinstance(output, Mapping):
        errors.append("canonical W1 build spec output is missing")
    else:
        _check_build_spec_identity(
            output,
            spec_path=spec_path,
            expected_path=candidate,
            expected_sha256=candidate_hash,
            label="output",
            errors=errors,
        )

    inputs = spec.get("inputs")
    if not isinstance(inputs, Mapping) or not inputs:
        errors.append("canonical W1 build spec inputs are empty")
    else:
        for name, identity in inputs.items():
            if not isinstance(identity, Mapping):
                errors.append(f"canonical W1 build input is invalid: {name}")
                continue
            _check_build_spec_identity(
                identity,
                spec_path=spec_path,
                expected_path=None,
                expected_sha256=None,
                label=f"input {name}",
                errors=errors,
            )
        _validate_w1_osm_build_provenance(
            inputs,
            scope_policy=scope_policy,
            spec_path=spec_path,
            errors=errors,
        )

    steps = spec.get("materialization")
    if not isinstance(steps, list) or not steps:
        errors.append("canonical W1 build materialization steps are empty")
        return
    for index, step in enumerate(steps):
        if not isinstance(step, Mapping):
            errors.append(f"canonical W1 build step is invalid: {index}")
            continue
        command = step.get("command")
        output_sha256 = step.get("output_sha256")
        if (
            not isinstance(command, list)
            or not all(isinstance(argument, str) for argument in command)
            or not command
            or Path(command[0]).name.lower() not in {"netconvert", "netconvert.exe"}
        ):
            errors.append(f"canonical W1 build step is not netconvert: {index}")
            continue
        required_turnaround_flags = {
            "--no-turnarounds",
            "--no-turnarounds.tls",
            "--no-turnarounds.geometry",
            "--no-turnarounds.fringe",
        }
        missing_turnaround_flags = required_turnaround_flags.difference(command)
        if missing_turnaround_flags:
            errors.append(f"canonical W1 build step is missing no-turnaround flags: {index}")
        crop_options = [
            argument
            for argument in command
            if argument.startswith("--")
            and ("bbox" in argument.split("=", 1)[0].lower() or "keep-edges" in argument.split("=", 1)[0].lower())
        ]
        if crop_options:
            errors.append(f"canonical W1 build step uses edge-cropping options: {index}")
        if "--output-file" not in command:
            errors.append(f"canonical W1 build step has no output: {index}")
            continue
        output_index = command.index("--output-file") + 1
        if output_index >= len(command):
            errors.append(f"canonical W1 build step has no output path: {index}")
            continue
        _check_build_spec_identity(
            {"path": command[output_index], "sha256": output_sha256},
            spec_path=spec_path,
            expected_path=candidate if index == len(steps) - 1 else None,
            expected_sha256=candidate_hash if index == len(steps) - 1 else None,
            label=f"step {index} output",
            errors=errors,
        )


def _validate_w1_osm_build_provenance(
    inputs: Mapping[str, Any],
    *,
    scope_policy: object,
    spec_path: Path,
    errors: list[str],
) -> None:
    required_inputs = {
        "source_osm_snapshot",
        "filtered_complete_ways",
        "baseline_network",
        "build_provenance",
        "complete_way_acquisition",
    }
    missing_inputs = required_inputs.difference(inputs)
    if missing_inputs:
        errors.append("canonical W1 build provenance inputs are incomplete")
        return
    identities = {
        name: inputs.get(name)
        for name in required_inputs
    }
    if any(not isinstance(identity, Mapping) for identity in identities.values()):
        errors.append("canonical W1 build provenance input identity is invalid")
        return
    provenance_identity = identities["build_provenance"]
    assert isinstance(provenance_identity, Mapping)
    provenance_path = _resolve_identity_path(provenance_identity, base_dir=spec_path.parent)
    if provenance_path is None:
        errors.append("canonical W1 OSM build provenance path is unreadable")
        return
    try:
        provenance = _read_json_mapping(provenance_path)
    except HamburgExecutionWorkflowError:
        errors.append("canonical W1 OSM build provenance is invalid")
        return
    if (
        provenance.get("schema") != "torii.osm-sumo-build-provenance/v1"
        or provenance.get("status") != "pass"
    ):
        errors.append("canonical W1 OSM build provenance is not pass")

    build_scope = provenance.get("build_scope")
    acquisition_bbox = (
        scope_policy.get("acquisition_bbox")
        if isinstance(scope_policy, Mapping)
        else None
    )
    if (
        not isinstance(build_scope, Mapping)
        or build_scope.get("clip_source_ways_to_bbox") is not False
        or build_scope.get("allowed_way_ids_count") is not None
        or "forced_way_ids_count" not in build_scope
        or build_scope.get("forced_way_ids_count") is not None
        or not _same_bbox(build_scope.get("bbox"), acquisition_bbox)
    ):
        errors.append("canonical W1 OSM build provenance used a cropped or different scope")

    source_identity = identities["source_osm_snapshot"]
    assert isinstance(source_identity, Mapping)
    source_acquisition = provenance.get("source_acquisition")
    acquisition_query = (
        source_acquisition.get("query")
        if isinstance(source_acquisition, Mapping)
        else None
    )
    acquisition_response = (
        source_acquisition.get("response_snapshot")
        if isinstance(source_acquisition, Mapping)
        else None
    )
    acquisition_query_path = (
        _resolve_identity_path(acquisition_query, base_dir=provenance_path.parent)
        if isinstance(acquisition_query, Mapping)
        else None
    )
    if (
        not isinstance(source_acquisition, Mapping)
        or source_acquisition.get("mode") != "provided_snapshot"
        or source_acquisition.get("overpass") is not None
        or acquisition_query_path is None
        or acquisition_query.get("sha256") != file_sha256(acquisition_query_path)
        or not _is_complete_way_overpass_query(
            acquisition_query_path,
            expected_bbox=acquisition_bbox,
        )
        or not isinstance(acquisition_response, Mapping)
        or not _identities_match(
            acquisition_response,
            provenance_base=provenance_path.parent,
            expected=source_identity,
            expected_base=spec_path.parent,
        )
    ):
        errors.append(
            "canonical W1 OSM build provenance source acquisition is invalid"
        )

    for provenance_name, input_name in (
        ("source_osm_snapshot", "source_osm_snapshot"),
        ("netconvert_input_osm_snapshot", "filtered_complete_ways"),
        ("sumo_net_snapshot", "baseline_network"),
    ):
        provenance_artifact = provenance.get(provenance_name)
        input_artifact = identities[input_name]
        assert isinstance(input_artifact, Mapping)
        if (
            not isinstance(provenance_artifact, Mapping)
            or not _identities_match(
                provenance_artifact,
                provenance_base=provenance_path.parent,
                expected=input_artifact,
                expected_base=spec_path.parent,
            )
        ):
            errors.append(
                f"canonical W1 OSM build provenance {provenance_name} mismatch"
            )

    netconvert = provenance.get("netconvert")
    command = netconvert.get("command") if isinstance(netconvert, Mapping) else None
    required_turnaround_flags = {
        "--no-turnarounds",
        "--no-turnarounds.tls",
        "--no-turnarounds.geometry",
        "--no-turnarounds.fringe",
    }
    if (
        not isinstance(command, list)
        or not all(isinstance(argument, str) for argument in command)
        or not command
        or Path(command[0]).name.lower() not in {"netconvert", "netconvert.exe"}
        or not required_turnaround_flags.issubset(command)
        or any(
            argument.startswith("--")
            and (
                "bbox" in argument.split("=", 1)[0].lower()
                or "keep-edges" in argument.split("=", 1)[0].lower()
            )
            for argument in command
        )
    ):
        errors.append("canonical W1 OSM build provenance netconvert command is unsafe")
    elif not (
        _command_option_matches_identity(
            command,
            "--osm-files",
            identity=identities["filtered_complete_ways"],
            identity_base=spec_path.parent,
            command_base=provenance_path.parent.parent,
        )
        and _command_option_matches_identity(
            command,
            "--output-file",
            identity=identities["baseline_network"],
            identity_base=spec_path.parent,
            command_base=provenance_path.parent.parent,
        )
    ):
        errors.append(
            "canonical W1 OSM build provenance command is not bound to the declared baseline"
        )
    _validate_complete_way_acquisition(
        identities,
        main_provenance=provenance,
        scope_policy=scope_policy,
        spec_path=spec_path,
        errors=errors,
    )


def _validate_scope_baseline_binding(
    spec: Mapping[str, Any],
    *,
    spec_path: Path,
    scope_ledger: Mapping[str, Any],
    scope_path: Path,
    errors: list[str],
) -> None:
    inputs = spec.get("inputs")
    baseline = inputs.get("baseline_network") if isinstance(inputs, Mapping) else None
    ledger_baseline = scope_ledger.get("full_way_baseline")
    if (
        not isinstance(baseline, Mapping)
        or not isinstance(ledger_baseline, Mapping)
        or not _identities_match(
            ledger_baseline,
            provenance_base=scope_path.parent,
            expected=baseline,
            expected_base=spec_path.parent,
        )
    ):
        errors.append(
            "scope edge-preservation full-way baseline does not match the canonical build"
        )


def _validate_complete_way_acquisition(
    identities: Mapping[str, object],
    *,
    main_provenance: Mapping[str, Any],
    scope_policy: object,
    spec_path: Path,
    errors: list[str],
) -> None:
    acquisition_identity = identities.get("complete_way_acquisition")
    if not isinstance(acquisition_identity, Mapping):
        errors.append("canonical W1 complete-way acquisition identity is invalid")
        return
    acquisition_path = _resolve_identity_path(
        acquisition_identity,
        base_dir=spec_path.parent,
    )
    if acquisition_path is None:
        errors.append("canonical W1 complete-way acquisition path is unreadable")
        return
    try:
        acquisition = _read_json_mapping(acquisition_path)
    except HamburgExecutionWorkflowError:
        errors.append("canonical W1 complete-way acquisition is invalid")
        return
    expected_bbox = (
        scope_policy.get("acquisition_bbox")
        if isinstance(scope_policy, Mapping)
        else None
    )
    if (
        acquisition.get("schema")
        != "torii.hamburg-complete-way-acquisition/v1"
        or acquisition.get("status") != "pass"
        or acquisition.get("authority_review_status") != "review_required"
        or acquisition.get("acquisition_mode") != "overpass_download"
        or acquisition.get("clip_source_ways_to_bbox") is not False
        or acquisition.get("allowed_way_ids_count") is not None
        or acquisition.get("forced_way_ids_count") is not None
        or acquisition.get("acquisition_bbox") != expected_bbox
        or acquisition.get("selection_rule")
        != (
            "retain each complete OSM way intersecting the buffered aerial/CAD scope; "
            "never truncate a selected way at the bbox"
        )
    ):
        errors.append("canonical W1 complete-way acquisition policy is invalid")

    source_identity = identities.get("source_osm_snapshot")
    filtered_identity = identities.get("filtered_complete_ways")
    if not isinstance(source_identity, Mapping) or not isinstance(
        filtered_identity,
        Mapping,
    ):
        errors.append("canonical W1 complete-way source identities are invalid")
        return
    for field, expected_identity in (
        ("source_osm_snapshot", source_identity),
        ("filtered_osm_snapshot", filtered_identity),
    ):
        artifact = acquisition.get(field)
        if (
            not isinstance(artifact, Mapping)
            or not _identities_match(
                artifact,
                provenance_base=acquisition_path.parent,
                expected=expected_identity,
                expected_base=spec_path.parent,
            )
        ):
            errors.append(f"canonical W1 complete-way acquisition {field} mismatch")

    scope_evidence = acquisition.get("scope_authority_evidence")
    expected_scope_hashes = {
        "hamburg_2024_aerial": (
            "8c65a45c5b86d2a7077c321bb1fff8108651f0f8a7fd3ffc62091c17de5be948"
        ),
        "hamburg_2022_road_cad": (
            "2dd292e00ee0d522a5c8f0c4e0a4b95b47f4afcc34db12b5d69c47501e70d8ec"
        ),
    }
    if not isinstance(scope_evidence, list):
        errors.append("canonical W1 complete-way scope authority evidence is missing")
    else:
        actual_scope_hashes: dict[str, str] = {}
        for artifact in scope_evidence:
            if not isinstance(artifact, Mapping):
                continue
            evidence_id = str(artifact.get("evidence_id", ""))
            path = _resolve_identity_path(artifact, base_dir=acquisition_path.parent)
            if path is not None and artifact.get("sha256") == file_sha256(path):
                actual_scope_hashes[evidence_id] = str(artifact["sha256"])
        if actual_scope_hashes != expected_scope_hashes:
            errors.append(
                "canonical W1 complete-way scope authority evidence mismatch"
            )

    query = acquisition.get("overpass_query")
    query_path = (
        _resolve_identity_path(query, base_dir=acquisition_path.parent)
        if isinstance(query, Mapping)
        else None
    )
    if (
        query_path is None
        or query.get("sha256") != file_sha256(query_path)
        or not _is_complete_way_overpass_query(
            query_path,
            expected_bbox=expected_bbox,
        )
    ):
        errors.append("canonical W1 complete-way Overpass query is invalid")

    source_build_identity = acquisition.get("source_build_provenance")
    source_build_path = (
        _resolve_identity_path(
            source_build_identity,
            base_dir=acquisition_path.parent,
        )
        if isinstance(source_build_identity, Mapping)
        else None
    )
    source_build: Mapping[str, Any] = {}
    source_scope: object = None
    if source_build_path is None:
        errors.append("canonical W1 complete-way source build provenance is missing")
    else:
        try:
            source_build = _read_json_mapping(source_build_path)
        except HamburgExecutionWorkflowError:
            source_build = {}
        source_scope = source_build.get("build_scope")
        source_snapshot = source_build.get("source_osm_snapshot")
        if (
            source_build.get("schema") != "torii.osm-sumo-build-provenance/v1"
            or source_build.get("status") != "pass"
            or not isinstance(source_scope, Mapping)
            or source_scope.get("clip_source_ways_to_bbox") is not False
            or source_scope.get("allowed_way_ids_count") is not None
            or source_scope.get("forced_way_ids_count") is not None
            or not _same_bbox(source_scope.get("bbox"), expected_bbox)
            or not isinstance(source_snapshot, Mapping)
            or not _identities_match(
                source_snapshot,
                provenance_base=source_build_path.parent,
                expected=source_identity,
                expected_base=spec_path.parent,
            )
        ):
            errors.append(
                "canonical W1 complete-way source build provenance is invalid"
            )

    source_acquisition = source_build.get("source_acquisition")
    source_query = (
        source_acquisition.get("query")
        if isinstance(source_acquisition, Mapping)
        else None
    )
    source_response = (
        source_acquisition.get("response_snapshot")
        if isinstance(source_acquisition, Mapping)
        else None
    )
    overpass = (
        source_acquisition.get("overpass")
        if isinstance(source_acquisition, Mapping)
        else None
    )
    if (
        not isinstance(source_acquisition, Mapping)
        or source_acquisition.get("mode") != "overpass_download"
        or not isinstance(source_query, Mapping)
        or not _identities_match(
            source_query,
            provenance_base=source_build_path.parent if source_build_path else Path(),
            expected=query,
            expected_base=acquisition_path.parent,
        )
        or not isinstance(source_response, Mapping)
        or not _identities_match(
            source_response,
            provenance_base=source_build_path.parent if source_build_path else Path(),
            expected=source_identity,
            expected_base=spec_path.parent,
        )
        or not isinstance(overpass, Mapping)
        or overpass.get("strategy") != "tiled-retry-merge"
        or type(overpass.get("tile_count")) is not int
        or overpass.get("tile_count", 0) <= 0
        or type(overpass.get("retry_count")) is not int
        or overpass.get("retry_count", -1) < 0
    ):
        errors.append(
            "canonical W1 complete-way source acquisition is not a bound Overpass download"
        )

    command_identity = acquisition.get("source_command_record")
    command_path = (
        _resolve_identity_path(command_identity, base_dir=acquisition_path.parent)
        if isinstance(command_identity, Mapping)
        else None
    )
    command_record = (
        _read_key_value_record(command_path)
        if command_path is not None
        and command_identity.get("sha256") == file_sha256(command_path)
        else None
    )
    if (
        command_record is None
        or not _same_bbox(command_record.get("bbox"), expected_bbox)
        or command_record.get("source_osm_sha256") != source_identity.get("sha256")
        or command_record.get("clip_source_ways_to_bbox") != "False"
        or command_record.get("allowed_way_ids_count") != "not_applied"
        or command_record.get("overpass_strategy") != "tiled-retry-merge"
        or not isinstance(overpass, Mapping)
        or command_record.get("overpass_tile_count")
        != str(overpass.get("tile_count"))
        or command_record.get("overpass_retry_count")
        != str(overpass.get("retry_count"))
        or any(
            key.startswith("forced_way_ids_")
            for key in command_record
        )
    ):
        errors.append(
            "canonical W1 complete-way source command record is invalid"
        )

    allowed_highways = acquisition.get("allowed_highways")
    main_scope = main_provenance.get("build_scope")
    if (
        not isinstance(allowed_highways, list)
        or not allowed_highways
        or not isinstance(main_scope, Mapping)
        or sorted(map(str, allowed_highways))
        != sorted(map(str, main_scope.get("road_classes") or ()))
        or not isinstance(source_scope, Mapping)
        or sorted(map(str, allowed_highways))
        != sorted(map(str, source_scope.get("road_classes") or ()))
        or command_record is None
        or command_record.get("allowed_highways")
        != ",".join(sorted(map(str, allowed_highways)))
    ):
        errors.append("canonical W1 complete-way road classes mismatch")
        return
    source_path = _resolve_identity_path(source_identity, base_dir=spec_path.parent)
    filtered_path = _resolve_identity_path(
        filtered_identity,
        base_dir=spec_path.parent,
    )
    if (
        source_path is None
        or filtered_path is None
        or not isinstance(expected_bbox, list)
    ):
        errors.append("canonical W1 complete-way audit inputs are unreadable")
        return
    try:
        observed_audit = audit_complete_osm_way_filter(
            source_osm_file=source_path,
            filtered_osm_file=filtered_path,
            acquisition_bbox=expected_bbox,
            allowed_highways=allowed_highways,
        )
    except (OSError, ValueError):
        errors.append("canonical W1 complete-way filter audit could not run")
        return
    if (
        observed_audit.get("status") != "pass"
        or acquisition.get("complete_way_filter_audit") != observed_audit
    ):
        errors.append(
            "canonical W1 complete-way filter audit is not a hash-bound pass"
        )


def _is_complete_way_overpass_query(
    query_path: Path,
    *,
    expected_bbox: object,
) -> bool:
    if not isinstance(expected_bbox, list) or len(expected_bbox) != 4:
        return False
    try:
        text = query_path.read_text(encoding="utf-8")
    except OSError:
        return False
    normalized = re.sub(r"\s+", "", text)
    try:
        expected_west, expected_south, expected_east, expected_north = (
            float(value)
            for value in expected_bbox
        )
    except (TypeError, ValueError):
        return False
    overpass_bbox = ",".join(
        f"{value:g}"
        for value in (
            expected_south,
            expected_west,
            expected_north,
            expected_east,
        )
    )
    expected = (
        f'[out:xml][timeout:300];(way["highway"]({overpass_bbox});'
        f'relation["type"="restriction"]({overpass_bbox}););'
        "(._;>;);outbody;"
    )
    return normalized == expected


def _read_key_value_record(path: Path) -> dict[str, str] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    record: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        key, separator, value = line.partition("=")
        if not separator or not key or key in record:
            return None
        record[key] = value
    return record


def _identities_match(
    provenance: Mapping[str, Any],
    *,
    provenance_base: Path,
    expected: Mapping[str, Any],
    expected_base: Path,
) -> bool:
    provenance_path = _resolve_identity_path(provenance, base_dir=provenance_base)
    expected_path = _resolve_identity_path(expected, base_dir=expected_base)
    return (
        provenance_path is not None
        and expected_path is not None
        and provenance_path == expected_path
        and provenance.get("sha256") == expected.get("sha256")
        and provenance.get("sha256") == file_sha256(provenance_path)
    )


def _resolve_identity_path(
    identity: Mapping[str, Any],
    *,
    base_dir: Path,
) -> Path | None:
    raw_path = identity.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def _same_bbox(raw_bbox: object, expected_bbox: object) -> bool:
    if (
        not isinstance(raw_bbox, str)
        or not isinstance(expected_bbox, list)
        or len(expected_bbox) != 4
    ):
        return False
    try:
        actual = [float(value.strip()) for value in raw_bbox.split(",")]
        expected = [float(value) for value in expected_bbox]
    except (TypeError, ValueError):
        return False
    return len(actual) == 4 and actual == expected


def _command_option_matches_identity(
    command: list[str],
    option: str,
    *,
    identity: object,
    identity_base: Path,
    command_base: Path,
) -> bool:
    if not isinstance(identity, Mapping) or option not in command:
        return False
    value_index = command.index(option) + 1
    if value_index >= len(command):
        return False
    command_path = Path(command[value_index]).expanduser()
    if not command_path.is_absolute():
        command_path = command_base / command_path
    try:
        command_path = command_path.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    return command_path == _resolve_identity_path(identity, base_dir=identity_base)


def _check_build_spec_identity(
    identity: Mapping[str, Any],
    *,
    spec_path: Path,
    expected_path: Path | None,
    expected_sha256: str | None,
    label: str,
    errors: list[str],
) -> None:
    raw_path = identity.get("path")
    declared_sha256 = identity.get("sha256")
    if not isinstance(raw_path, str) or not raw_path.strip():
        errors.append(f"canonical W1 build {label} path is missing")
        return
    if (
        not isinstance(declared_sha256, str)
        or len(declared_sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in declared_sha256)
    ):
        errors.append(f"canonical W1 build {label} SHA-256 is invalid")
        return
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = spec_path.parent / path
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError):
        errors.append(f"canonical W1 build {label} path is unreadable")
        return
    actual_sha256 = file_sha256(path)
    if actual_sha256 != declared_sha256.lower():
        errors.append(f"canonical W1 build {label} SHA-256 mismatch")
    if expected_path is not None and path != expected_path:
        errors.append(f"canonical W1 build {label} path mismatch")
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        errors.append(f"canonical W1 build {label} candidate mismatch")


def _read_json_mapping(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HamburgExecutionWorkflowError(f"cannot read W1 evidence: {path}") from exc
    if not isinstance(payload, Mapping):
        raise HamburgExecutionWorkflowError(f"W1 evidence is not an object: {path}")
    return payload


def _check_candidate_binding(
    payload: Mapping[str, Any],
    candidate: Path,
    candidate_hash: str,
    errors: list[str],
    *,
    prefix: str,
    base_dir: Path | None = None,
) -> None:
    try:
        bound_path = Path(str(payload.get(f"{prefix}_net_file", ""))).expanduser()
        if not bound_path.is_absolute() and base_dir is not None:
            bound_path = base_dir / bound_path
        bound_path = bound_path.resolve()
    except OSError:
        bound_path = Path()
    if bound_path != candidate or payload.get(f"{prefix}_sha256") != candidate_hash:
        errors.append(f"{prefix} candidate binding mismatch")


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

    _relative_execution_plan_paths(stage_records, plan_file.parent)
    _apply_network_binding_contract(stage_records)
    _apply_stage_dependency_contract(stage_records)
    changed = _changed_stage_ids(previous, stage_records)
    invalidated = {
        stage_id
        for stage_id in _downstream_closure(changed)
        if _stage_was_materialized(previous, stage_id)
    }
    invalidated.update(_pending_invalidated_stage_ids(previous, changed))
    for stage_id in sorted(invalidated, key=_stage_sort_key):
        if stage_id not in stage_records:
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

    next_action = _next_action(stage_records)
    plan_revision = int(previous.get("plan_revision", 0)) + 1 if previous else 1
    first_invalid_stage = next_action.get("stage_id")
    replan = _replan_summary(
        stage_records,
        next_action=next_action,
        changed=changed,
        invalidated=invalidated,
        first_invalid_stage=first_invalid_stage,
    )
    capabilities = _capability_matrix(stage_records)
    promotion_pass = all(_stage_promotable(record) for record in stage_records.values())
    stage_records["W5"] = _summary_stage_record(stage_records, capabilities)
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
        "capabilities": capabilities,
        "promotion": {
            "decision": "pass" if promotion_pass else "blocked",
            "automatic": True,
            "execution_complete": next_action["status"] == "complete",
            "requires": (
                "W0, W1, W2, W3a, W3b, and W4 are materialized with "
                "execution_gate=pass, decision=pass, and automatic_promotion_gate=pass"
            ),
        },
        "claim_boundary": {
            "proves": [
                "which dated Torii stage artifacts are being reused",
                "that each referenced manifest and network binding is byte-hash stable",
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
        stage_id = _canonical_stage_id(raw_stage)
        path = Path(raw_path).expanduser().resolve()
        if stage_id in result and result[stage_id] != path:
            raise HamburgExecutionWorkflowError(f"duplicate stage id: {stage_id}")
        result[stage_id] = path
    return result


def _relative_execution_plan_paths(
    stage_records: Mapping[str, dict[str, Any]],
    base_dir: Path,
) -> None:
    """Keep every plan-owned reference portable from the plan manifest."""

    for record in stage_records.values():
        manifest = record.get("manifest")
        manifest_path = Path(manifest) if isinstance(manifest, str) and manifest else None
        if manifest_path is not None and manifest_path.is_absolute():
            record["manifest"] = relative_or_absolute_path(manifest_path, base_dir)
        identities: list[object] = [record.get("network_binding")]
        for container_name in ("artifact_bindings", "stage_bindings"):
            container = record.get(container_name)
            if isinstance(container, Mapping):
                identities.extend(container.values())
        feedback_manifests = record.get("feedback_manifests")
        if isinstance(feedback_manifests, list):
            identities.extend(feedback_manifests)
        else:
            identities.append(record.get("feedback_manifest"))
        for identity in identities:
            if not isinstance(identity, dict):
                continue
            raw_path = identity.get("path")
            path = Path(raw_path) if isinstance(raw_path, str) and raw_path else None
            if path is not None and path.is_absolute():
                identity["path"] = relative_or_absolute_path(path, base_dir)


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
        stage_id = _canonical_stage_id(raw_stage)
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
    reported_schema = payload.get("schema") or payload.get("schema_id")
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
            "reported_schema": reported_schema,
            "reason": _manifest_reason(payload),
            "feedback": feedback,
        }
    )
    if stage_id == "W3b":
        gates = payload.get("gates")
        base["sensor_aggregation_semantics"] = (
            gates.get("sensor_aggregation_semantics")
            if isinstance(gates, Mapping)
            else None
        )
    if reported_schema not in STAGE_SCHEMAS[stage_id]:
        expected = ", ".join(sorted(STAGE_SCHEMAS[stage_id]))
        _block_stage_record(
            base,
            f"manifest_schema_mismatch: expected {expected}; got {reported_schema!r}",
        )
    else:
        if stage_id in NETWORK_BOUND_STAGES:
            binding, error = _network_binding_from_manifest(stage_id, payload, path)
            if binding:
                base["network_binding"] = binding
            if error:
                _block_stage_record(base, error)
        if stage_id in {"W3a", "W3b"}:
            bindings, errors = _stage_artifact_bindings_from_manifest(stage_id, payload, path)
            base["artifact_bindings"] = bindings
            if errors:
                _block_stage_record(base, "; ".join(errors))
        if stage_id in {"W2", "W3b", "W4"}:
            bindings, errors = _stage_dependency_bindings_from_manifest(stage_id, payload, path)
            base["stage_bindings"] = bindings
            if errors:
                _block_stage_record(base, "; ".join(errors))
    for feedback_path in feedback_paths:
        _merge_feedback_manifest(base, feedback_path)
    if not base["reason"]:
        base.pop("reason")
    if not base["feedback"]:
        base.pop("feedback")
    return base


def _network_binding_from_manifest(
    stage_id: str,
    payload: Mapping[str, Any],
    manifest_path: Path,
) -> tuple[dict[str, Any], str | None]:
    paths: Mapping[str, tuple[tuple[str, ...], ...]] = {
        "W1": (("network_binding",), ("network",)),
        "W2": (("network_binding",), ("source", "candidate_net")),
        "W3b": (("network_binding",), ("source", "candidate_net"), ("network",)),
        "W4": (("network_binding",), ("source", "net")),
    }
    raw_binding: Mapping[str, Any] | None = None
    for keys in paths[stage_id]:
        value: Any = payload
        for key in keys:
            value = value.get(key) if isinstance(value, Mapping) else None
        if isinstance(value, Mapping):
            raw_binding = value
            break
    if raw_binding is None:
        return {}, "network_binding_missing"

    raw_path = raw_binding.get("path")
    raw_sha256 = raw_binding.get("sha256")
    binding: dict[str, Any] = {
        "path": str(raw_path or ""),
        "sha256": str(raw_sha256 or "").lower(),
        "validation": "blocked",
    }
    if not isinstance(raw_path, str) or not raw_path.strip():
        return binding, "network_binding_path_missing"
    if (
        not isinstance(raw_sha256, str)
        or len(raw_sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in raw_sha256)
    ):
        return binding, "network_binding_sha256_invalid"
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = manifest_path.parent / candidate
    try:
        candidate = candidate.resolve(strict=True)
        actual_sha256 = file_sha256(candidate)
    except (OSError, RuntimeError) as exc:
        return binding, f"network_binding_unreadable: {exc}"
    binding.update(
        {
            "path": str(candidate),
            "actual_sha256": actual_sha256,
        }
    )
    if actual_sha256 != str(raw_sha256).lower():
        return binding, "network_binding_sha256_mismatch"
    binding["validation"] = "pass"
    return binding, None


def _apply_network_binding_contract(stages: Mapping[str, dict[str, Any]]) -> None:
    expected = stages["W1"].get("network_binding")
    if not isinstance(expected, Mapping) or expected.get("validation") != "pass":
        return
    expected_sha256 = str(expected["sha256"])
    for stage_id in ("W2", "W3b", "W4"):
        record = stages[stage_id]
        if record.get("status") == "not_run":
            continue
        binding = record.get("network_binding")
        if not isinstance(binding, dict) or binding.get("validation") != "pass":
            continue
        binding["expected_w1_sha256"] = expected_sha256
        if binding.get("sha256") != expected_sha256:
            binding["validation"] = "blocked"
            _block_stage_record(record, "network_binding_does_not_match_W1")


def _stage_dependency_bindings_from_manifest(
    stage_id: str,
    payload: Mapping[str, Any],
    manifest_path: Path,
) -> tuple[dict[str, Any], list[str]]:
    source = payload.get("source")
    if not isinstance(source, Mapping):
        return {}, ["stage_binding_source_missing"]
    bindings: dict[str, Any] = {}
    errors: list[str] = []
    required_names = {
        "W2": ("w1_manifest",),
        "W3b": ("w1_manifest", "count_stream_snapshot"),
        "W4": (
            "w1_manifest",
            "signal_binding_manifest",
            "detector_binding_manifest",
            "count_scope_manifest",
            "count_stream_snapshot",
            "canonical_count_file",
        ),
    }[stage_id]
    for name in required_names:
        binding, error = _file_identity_from_manifest(
            source.get(name),
            manifest_path,
            label=name,
        )
        if binding:
            bindings[name] = binding
        if error:
            errors.append(error)
    if stage_id == "W4":
        optional_names = ("signal_observation_manifest", "tls_link_events")
        present = [name for name in optional_names if source.get(name) is not None]
        if present and len(present) != len(optional_names):
            errors.append("stage_binding_signal_history_incomplete")
        for name in present:
            binding, error = _file_identity_from_manifest(
                source.get(name),
                manifest_path,
                label=name,
            )
            if binding:
                bindings[name] = binding
            if error:
                errors.append(error)
    return bindings, errors


def _stage_artifact_bindings_from_manifest(
    stage_id: str,
    payload: Mapping[str, Any],
    manifest_path: Path,
) -> tuple[dict[str, Any], list[str]]:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return {}, ["artifact_binding_source_missing"]
    names = {
        "W3a": ("count_streams_raw", "counts_simulation_15min"),
        "W3b": ("detector_mapping",),
    }[stage_id]
    bindings: dict[str, Any] = {}
    errors: list[str] = []
    for name in names:
        binding, error = _file_identity_from_manifest(
            artifacts.get(name),
            manifest_path,
            label=name,
        )
        if binding:
            bindings[name] = binding
        if error:
            errors.append(error)
    return bindings, errors


def _file_identity_from_manifest(
    raw_identity: object,
    manifest_path: Path,
    *,
    label: str,
) -> tuple[dict[str, Any], str | None]:
    if not isinstance(raw_identity, Mapping):
        return {}, f"stage_binding_{label}_missing"
    raw_path = raw_identity.get("path")
    raw_sha256 = raw_identity.get("sha256")
    binding: dict[str, Any] = {
        "path": str(raw_path or ""),
        "sha256": str(raw_sha256 or "").lower(),
        "validation": "blocked",
    }
    if not isinstance(raw_path, str) or not raw_path.strip():
        return binding, f"stage_binding_{label}_path_missing"
    if (
        not isinstance(raw_sha256, str)
        or len(raw_sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in raw_sha256)
    ):
        return binding, f"stage_binding_{label}_sha256_invalid"
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = manifest_path.parent / path
    try:
        path = path.resolve(strict=True)
        actual_sha256 = file_sha256(path)
    except (OSError, RuntimeError) as exc:
        return binding, f"stage_binding_{label}_unreadable: {exc}"
    binding.update({"path": str(path), "actual_sha256": actual_sha256})
    if actual_sha256 != raw_sha256.lower():
        return binding, f"stage_binding_{label}_sha256_mismatch"
    binding["validation"] = "pass"
    return binding, None


def _apply_stage_dependency_contract(stages: Mapping[str, dict[str, Any]]) -> None:
    checks = (
        ("W2", "w1_manifest", "W1", None, None),
        ("W3b", "w1_manifest", "W1", None, None),
        ("W3b", "count_stream_snapshot", "W3a", "artifact_bindings", "count_streams_raw"),
        ("W4", "w1_manifest", "W1", None, None),
        ("W4", "signal_binding_manifest", "W2", None, None),
        ("W4", "detector_binding_manifest", "W3b", None, None),
        ("W4", "count_scope_manifest", "W3a", None, None),
        ("W4", "count_stream_snapshot", "W3a", "artifact_bindings", "count_streams_raw"),
        (
            "W4",
            "canonical_count_file",
            "W3a",
            "artifact_bindings",
            "counts_simulation_15min",
        ),
    )
    for record_id, name, expected_stage_id, expected_container, expected_name in checks:
        record = stages[record_id]
        if record.get("status") == "not_run":
            continue
        bindings = record.get("stage_bindings")
        if not isinstance(bindings, Mapping):
            continue
        expected_record = stages[expected_stage_id]
        if expected_container is None:
            expected_sha256 = expected_record.get("manifest_sha256")
        else:
            expected_bindings = expected_record.get(expected_container)
            expected_binding = (
                expected_bindings.get(expected_name)
                if isinstance(expected_bindings, Mapping)
                else None
            )
            expected_sha256 = (
                expected_binding.get("sha256")
                if isinstance(expected_binding, Mapping)
                else None
            )
        if not isinstance(expected_sha256, str):
            continue
        binding = bindings.get(name)
        if not isinstance(binding, dict) or binding.get("validation") != "pass":
            continue
        binding["expected_stage_id"] = expected_stage_id
        binding["expected_sha256"] = expected_sha256
        if binding.get("sha256") != expected_sha256:
            binding["validation"] = "blocked"
            _block_stage_record(
                record,
                f"stage_binding_{name}_does_not_match_{expected_stage_id}",
            )
    w4 = stages["W4"]
    w3b = stages["W3b"]
    if (
        w4.get("status") != "not_run"
        and isinstance(w3b.get("manifest_sha256"), str)
        and w3b.get("sensor_aggregation_semantics") != "pass"
    ):
        _block_stage_record(w4, "W3b_sensor_aggregation_semantics_not_pass")


def _block_stage_record(record: dict[str, Any], reason: str) -> None:
    existing = record.get("contract_error")
    if isinstance(existing, str) and existing and reason not in existing.split("; "):
        reason = f"{existing}; {reason}"
    record["decision"] = "blocked"
    record["execution_gate"] = "blocked"
    record["contract_error"] = reason
    record["reason"] = reason


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
    return (
        "pass"
        if record.get("execution_gate") == "pass"
        and record.get("effective_status", record.get("status")) != "not_run"
        else "blocked"
    )


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
    stages = payload.get("stages")
    if isinstance(stages, dict):
        _relative_execution_plan_paths(stages, path.parent)
    return payload


def _stage_was_materialized(previous: Mapping[str, Any] | None, stage_id: str) -> bool:
    if previous is None:
        return False
    stages = previous.get("stages")
    record = stages.get(stage_id) if isinstance(stages, Mapping) else None
    return (
        isinstance(record, Mapping)
        and record.get("manifest") is not None
        and record.get("effective_status", record.get("status")) != "not_run"
    )


def _pending_invalidated_stage_ids(
    previous: Mapping[str, Any] | None,
    changed: set[str],
) -> set[str]:
    """Keep invalidation active until the downstream manifest identity changes."""

    if previous is None:
        return set()
    stages = previous.get("stages")
    if not isinstance(stages, Mapping):
        return set()
    return {
        stage_id
        for stage_id in STAGE_DEPENDENCIES
        if stage_id not in changed
        and isinstance(stages.get(stage_id), Mapping)
        and stages[stage_id].get("resume_decision") == "invalidate_and_rerun"
    }


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
            or (
                stage_id == "W1"
                and old.get("network_binding") != record.get("network_binding")
            )
            or old.get("artifact_bindings") != record.get("artifact_bindings")
            or _w4_signal_history_binding_state(old)
            != _w4_signal_history_binding_state(record)
        ):
            changed.add(stage_id)
    return changed


def _w4_signal_history_binding_state(
    record: Mapping[str, Any],
) -> tuple[object, object] | None:
    if record.get("stage_id") != "W4":
        return None
    bindings = record.get("stage_bindings")
    if not isinstance(bindings, Mapping):
        return (None, None)
    return (
        bindings.get("signal_observation_manifest"),
        bindings.get("tls_link_events"),
    )


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


def _capability_matrix(stages: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    stage_by_capability = {
        "road_topology": "W1",
        "official_signal_control": "W2",
        "official_counts": "W3a",
        "detector_binding": "W3b",
        "demand_inference_and_replay": "W4",
    }
    capabilities = {
        capability: {
            "stage_id": stage_id,
            "status": _capability_status(capability, stages[stage_id]),
            "stage_status": stages[stage_id].get(
                "effective_status",
                stages[stage_id].get("status"),
            ),
            "decision": stages[stage_id].get("decision"),
            "execution_gate": stages[stage_id].get("execution_gate"),
            "automatic_promotion_gate": stages[stage_id].get("automatic_promotion_gate"),
            "promotion_status": (
                "pass"
                if _stage_promotable(stages[stage_id])
                else (
                    "review_required"
                    if stages[stage_id].get("execution_gate") == "pass"
                    else "blocked"
                )
            ),
        }
        for capability, stage_id in stage_by_capability.items()
    }
    capabilities["field_faithful_digital_twin"] = {
        "status": "pass" if all(_stage_promotable(record) for record in stages.values()) else "blocked"
    }
    return capabilities


def _capability_status(capability: str, record: Mapping[str, Any]) -> str:
    if record.get("execution_gate") != "pass":
        return "blocked"
    if _stage_promotable(record):
        return "pass"
    if capability == "road_topology":
        return "pass"
    if capability in {"official_counts", "demand_inference_and_replay"}:
        return "diagnostic"
    return "review_required"


def _stage_promotable(record: Mapping[str, Any]) -> bool:
    return (
        record.get("effective_status", record.get("status")) != "not_run"
        and record.get("execution_gate") == "pass"
        and record.get("automatic_promotion_gate") == "pass"
        and record.get("decision") == "pass"
    )


def _summary_stage_record(
    stages: Mapping[str, Mapping[str, Any]],
    capabilities: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "stage_id": "W5",
        "name": STAGE_NAMES["W5"],
        "generated": True,
        "manifest": None,
        "status": "complete",
        "effective_status": "complete",
        "automatic_promotion_gate": "pass",
        "decision": "pass",
        "execution_gate": "pass",
        "readiness": "complete",
        "dependencies": list(STAGE_DEPENDENCIES),
        "dependency_gate": {
            stage_id: _stage_gate(record)
            for stage_id, record in stages.items()
        },
        "summarized_capabilities": list(capabilities),
        "contract": _stage_contract("W5"),
    }


def _downstream_closure(changed: set[str]) -> set[str]:
    invalidated: set[str] = set()
    changed_again = True
    while changed_again:
        changed_again = False
        for stage_id, dependencies in STAGE_DEPENDENCIES.items():
            if (
                stage_id not in changed
                and stage_id not in invalidated
                and any(dependency in changed or dependency in invalidated for dependency in dependencies)
            ):
                invalidated.add(stage_id)
                changed_again = True
    return invalidated


def _next_action(stages: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    for stage_id in STAGE_DEPENDENCIES:
        record = stages[stage_id]
        if record.get("effective_status") == "not_run" and record.get("readiness") == "ready":
            return {
                "stage_id": stage_id,
                "status": "ready",
                "action": f"run_{STAGE_NAMES[stage_id]}",
            }
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
            return {
                "stage_id": stage_id,
                "status": "blocked",
                "action": "resolve_dependency_gate",
                "blocked_by": record.get("blocked_by", {}),
            }
    return {"stage_id": None, "status": "complete", "action": "none"}


def _stage_sort_key(stage_id: str) -> tuple[int, str]:
    return (_STAGE_INDEX.get(stage_id, len(_STAGE_INDEX)), stage_id)


__all__ = [
    "HAMBURG_EXECUTION_CONFIG_SCHEMA",
    "HAMBURG_EXECUTION_WORKFLOW_ID",
    "HAMBURG_EXECUTION_WORKFLOW_SCHEMA",
    "HamburgExecutionWorkflowError",
    "materialize_hamburg_w1_topology_handoff",
    "materialize_hamburg_execution_plan",
    "materialize_hamburg_execution_plan_from_config",
]

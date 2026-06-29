from __future__ import annotations

import csv
import hashlib
import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Mapping

from .osm_area import osm_map_url_bbox, osm_preview_url, resolve_osm_place
from .connectivity import extract_largest_passenger_component_core, summarize_passenger_connectivity
from .command_runner import run_command
from .junction_aggregation import build_junction_aggregation_variant
from .junction_rebuild_candidate import (
    build_teacher_guided_repair_queue,
    build_tls_connection_repair_variant,
    run_teacher_guided_repair_queue,
)
from .netedit import launch_netedit
from .network_permissions import apply_service_passenger_permissions
from .network_plan import NETWORK_PLAN_QUESTION, derive_network_plan
from .osm_network import audit_tls, build_osm_network, build_routeability_probe, regional_map_baseline_for_bbox
from .reference_bbox import derive_reference_net_bbox
from .reference_hierarchy import audit_reference_hierarchy
from .reference_join_audit import audit_reference_join_patterns
from .reference_scope import audit_reference_scope, build_scope_pruning_variant
from .road_scope import (
    ROAD_LEVEL_SCOPE_OPTIONS,
    RECOMMENDED_ROAD_LEVEL_SCOPE,
)
from .routeability_audit import run_routeability_audit
from .sumo_gui import launch_sumo_gui
from .tls_aggregation import (
    build_tls_aggregation_variant,
    build_tls_low_vehicle_control_variant,
    build_tls_signal_grouping_variant,
)
from .topology_audit import audit_topology_fragmentation
from .workflow_review_html import build_workflow_review_html


PARTIAL_MAIN_COMPONENT_RATIO = 0.98
TLS_SEMANTIC_DELTA_KEYS = {
    "tl_logic_count",
    "traffic_light_junction_count",
    "tls_controlled_connection_count",
    "multi_junction_tl_logic_count",
    "traffic_light_junction_without_tls_connection_count",
    "tls_shared_linkindex_group_count",
    "tls_sparse_linkindex_tl_logic_count",
}


def _candidate_fields(place_report: Mapping[str, Any] | None) -> dict[str, Any]:
    if place_report is None:
        return {
            "candidate_display_name": "",
            "candidate_osm_type": "",
            "candidate_osm_id": "",
            "candidate_bbox": "",
            "candidate_lat": "",
            "candidate_lon": "",
            "candidate_osm_url": "",
        }
    return {
        "candidate_display_name": str(place_report.get("candidate_display_name", "")),
        "candidate_osm_type": str(place_report.get("candidate_osm_type", "")),
        "candidate_osm_id": str(place_report.get("candidate_osm_id", "")),
        "candidate_bbox": str(place_report.get("candidate_bbox", "")),
        "candidate_lat": str(place_report.get("candidate_lat", "")),
        "candidate_lon": str(place_report.get("candidate_lon", "")),
        "candidate_osm_url": str(place_report.get("candidate_osm_url", "")),
    }


def _blocked_place_report(
    place_name: str,
    output_dir: Path,
    place_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "claim_status": "blocked",
        "area_input": place_name,
        "area_resolution_status": "needs_user_confirmation",
        **_candidate_fields(place_report),
        "osm_preview_url": str(
            place_report.get("osm_preview_url", osm_preview_url(place_name))
            if place_report is not None
            else osm_preview_url(place_name)
        ),
        "user_confirmed_area": "no",
        "output_dir": str(output_dir),
        "gate_status": {
            "area_confirmation": "blocked",
            "road_level_scope": "not_started",
            "network_build": "not_started",
            "tls_reality_audit": "not_started",
            "connectivity": "not_started",
            "routeability_audit": "not_started",
            "netedit": "not_started",
            "sumo_gui": "not_started",
        },
        "warnings": list(place_report.get("warnings", []) if place_report is not None else [])
        + ["place-name input requires OSM preview and user confirmation before network construction"],
    }


def _road_level_scope_fields() -> dict[str, Any]:
    return {
        "road_level_options": list(ROAD_LEVEL_SCOPE_OPTIONS),
        "recommended_road_level": RECOMMENDED_ROAD_LEVEL_SCOPE,
    }


def _blocked_road_level_scope_report(
    *,
    area_input: str,
    area_status: str,
    place_report: Mapping[str, Any] | None,
    cleaned_place_name: str,
    bbox: str,
    network_plan: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "claim_status": "blocked",
        "area_input": area_input,
        "area_resolution_status": area_status,
        **(
            _candidate_fields(place_report)
            if place_report is not None
            else {**_candidate_fields(None), "candidate_bbox": bbox}
        ),
        "osm_preview_url": (
            str(place_report.get("osm_preview_url", osm_preview_url(cleaned_place_name)))
            if place_report is not None
            else (osm_preview_url(cleaned_place_name) if cleaned_place_name else "")
        ),
        "user_confirmed_area": "yes" if area_status == "confirmed_by_user" else "confirmed_by_input",
        "road_level_scope_status": "needs_user_confirmation",
        "network_plan_status": str(network_plan.get("network_plan_status", "needs_user_confirmation")),
        **_road_level_scope_fields(),
        "traffic_layer_options": list(network_plan.get("traffic_layer_options", [])),
        "network_detail_options": list(network_plan.get("network_detail_options", [])),
        "recommended_network_detail": str(network_plan.get("recommended_network_detail", "")),
        "missing_blockers": list(network_plan.get("missing_blockers", ["network_plan"])),
        "next_question": str(network_plan.get("next_question", NETWORK_PLAN_QUESTION)),
        "gate_status": {
            "area_confirmation": "pass",
            "road_level_scope": "blocked",
            "network_build": "not_started",
            "tls_reality_audit": "not_started",
            "connectivity": "not_started",
            "routeability_audit": "not_started",
            "netedit": "not_started",
            "sumo_gui": "not_started",
        },
        "warnings": ["road level scope must be confirmed before OSM network construction"],
    }


def _gate_value(report: Mapping[str, Any]) -> str:
    status = str(report.get("status", "fail"))
    if status == "pass":
        return "pass"
    if status == "blocked":
        return "blocked"
    return "fail"


def _int_field(report: Mapping[str, Any], key: str) -> int:
    try:
        return int(report.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _list_field_count(report: Mapping[str, Any] | None, key: str) -> int:
    if report is None:
        return 0
    value = report.get(key, [])
    return len(value) if isinstance(value, list) else 0


def _teacher_guided_exemplar_ready_stats(report: Mapping[str, Any] | None) -> tuple[int, int]:
    if report is None:
        return 0, 0
    ready_count = 0
    signature_count = 0
    for candidate in report.get("repair_candidates", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        movement_exemplar = candidate.get("movement_exemplar", {})
        signatures = movement_exemplar.get("movement_signatures", []) if isinstance(movement_exemplar, Mapping) else []
        if (
            candidate.get("candidate_status") != "ready_for_teacher_guided_variant"
            or not candidate.get("slot_edge_map")
            or not isinstance(signatures, list)
            or not signatures
        ):
            continue
        ready_count += 1
        signature_count += len(signatures)
    return ready_count, signature_count


def _teacher_guided_movement_gap_stats(report: Mapping[str, Any] | None) -> tuple[int, int, int, list[dict[str, Any]]]:
    if report is None:
        return 0, 0, 0, []
    gaps = []
    missing_plan_total = 0
    for candidate in report.get("repair_candidates", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        gap = _int_field(candidate, "vehicle_movement_matrix_missing_count")
        missing_plan = candidate.get("missing_teacher_movement_plan", []) or []
        missing_plan_count = _int_field(candidate, "missing_teacher_movement_plan_count")
        if missing_plan_count <= 0 and isinstance(missing_plan, list):
            missing_plan_count = len(missing_plan)
        if gap <= 0 and missing_plan_count <= 0:
            continue
        missing_plan_total += missing_plan_count
        first_missing = (
            missing_plan[0]
            if isinstance(missing_plan, list) and missing_plan and isinstance(missing_plan[0], Mapping)
            else {}
        )
        gap_summary = {
            "reference_id": str(candidate.get("reference_id", "")),
            "junction_id": str(candidate.get("junction_id", "")),
            "candidate_status": str(candidate.get("candidate_status", "")),
            "vehicle_movement_matrix_missing_count": gap,
            "missing_teacher_movement_plan_count": missing_plan_count,
            "netedit_review_actions": [str(item) for item in candidate.get("netedit_review_actions", []) or []],
        }
        if first_missing:
            gap_summary["first_missing_teacher_movement"] = dict(first_missing)
        gaps.append(gap_summary)
    gaps.sort(key=lambda item: (-int(item["vehicle_movement_matrix_missing_count"]), item["reference_id"]))
    return len(gaps), int(gaps[0]["vehicle_movement_matrix_missing_count"]) if gaps else 0, missing_plan_total, gaps[:5]


def _intish(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _junction_pattern_residual_stats(report: Mapping[str, Any] | None) -> dict[str, Any]:
    if report is None:
        return {
            "case_count": 0,
            "failed_case_count": 0,
            "mismatch_field_counts": {},
            "internal_function_count_deficits": {},
            "top_junction_pattern_mismatches": [],
        }
    comparisons = report.get("junction_pattern_comparisons", []) or []
    if not isinstance(comparisons, list):
        comparisons = []
    field_counts = report.get("junction_pattern_mismatch_field_counts", {}) or {}
    mismatch_field_counts = (
        {str(key): _intish(value) for key, value in field_counts.items()} if isinstance(field_counts, Mapping) else {}
    )
    internal_deficits: dict[str, int] = {}
    failed_examples: list[dict[str, Any]] = []
    for comparison in comparisons:
        if not isinstance(comparison, Mapping) or comparison.get("status") != "fail":
            continue
        fields = comparison.get("mismatch_fields", []) or []
        mismatch_fields = (
            [field for field in fields.split(";") if field]
            if isinstance(fields, str)
            else [str(field) for field in fields]
        )
        if not mismatch_field_counts:
            for field in mismatch_fields:
                mismatch_field_counts[field] = mismatch_field_counts.get(field, 0) + 1

        teacher = comparison.get("teacher", {})
        candidate = comparison.get("candidate", {})
        teacher_counts = teacher.get("internal_function_counts", {}) if isinstance(teacher, Mapping) else {}
        candidate_counts = candidate.get("internal_function_counts", {}) if isinstance(candidate, Mapping) else {}
        if not isinstance(teacher_counts, Mapping):
            teacher_counts = {}
        if not isinstance(candidate_counts, Mapping):
            candidate_counts = {}
        example_deficits = {}
        for function_name, teacher_count in teacher_counts.items():
            deficit = _intish(teacher_count) - _intish(candidate_counts.get(function_name, 0))
            if deficit <= 0:
                continue
            key = str(function_name)
            example_deficits[key] = deficit
            internal_deficits[key] = internal_deficits.get(key, 0) + deficit

        failed_examples.append(
            {
                "junction_id": str(comparison.get("junction_id", "")),
                "mismatch_fields": mismatch_fields,
                "teacher_control_type": teacher.get("control_type", "") if isinstance(teacher, Mapping) else "",
                "candidate_control_type": candidate.get("control_type", "") if isinstance(candidate, Mapping) else "",
                "teacher_has_tls": teacher.get("has_tls", "") if isinstance(teacher, Mapping) else "",
                "candidate_has_tls": candidate.get("has_tls", "") if isinstance(candidate, Mapping) else "",
                "internal_function_count_deficits": example_deficits,
            }
        )

    failed_case_count = _int_field(report, "junction_pattern_mismatch_count")
    return {
        "case_count": len(comparisons),
        "failed_case_count": failed_case_count if failed_case_count > 0 else len(failed_examples),
        "mismatch_field_counts": mismatch_field_counts,
        "internal_function_count_deficits": internal_deficits,
        "top_junction_pattern_mismatches": failed_examples[:5],
    }


def _class_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {item.strip() for item in value.replace(";", ",").split(",") if item.strip()}
    return {str(item) for item in value if str(item)}


def _connectivity_quality(connectivity_report: Mapping[str, Any]) -> dict[str, Any]:
    passenger_count = _int_field(connectivity_report, "passenger_edge_count")
    largest_count = _int_field(connectivity_report, "largest_component_edge_count")
    ratio = round(largest_count / passenger_count, 3) if passenger_count else 0.0
    strict_status = str(connectivity_report.get("connectivity_status", connectivity_report.get("status", "fail")))

    if strict_status == "pass":
        return {
            "connectivity_gate": "pass",
            "network_quality": "strict-connected",
            "strict_connectivity_status": "pass",
            "connectivity_main_component_ratio": ratio,
            "quality_warning": "",
        }
    if passenger_count and ratio >= PARTIAL_MAIN_COMPONENT_RATIO:
        return {
            "connectivity_gate": "partial",
            "network_quality": "partial-main-component",
            "strict_connectivity_status": "fail",
            "connectivity_main_component_ratio": ratio,
            "quality_warning": (
                f"strict connectivity failed; largest passenger component covers {ratio:.2%}; "
                "demote to diagnostic-demo and do not treat as experiment-ready"
            ),
        }
    return {
        "connectivity_gate": "fail",
        "network_quality": "construction-invalid",
        "strict_connectivity_status": "fail",
        "connectivity_main_component_ratio": ratio,
        "quality_warning": "",
    }


def _tls_review_summary(tls_report: Mapping[str, Any]) -> dict[str, Any]:
    cluster_count = int(tls_report.get("tls_cluster_count", 0) or 0)
    candidate_count = int(tls_report.get("tls_candidate_count", 0) or 0)
    review_required = cluster_count > 0 or candidate_count > 0
    return {
        "tls_candidate_count": candidate_count,
        "tls_cluster_count": cluster_count,
        "tls_review_file": str(tls_report.get("clusters_file", "")),
        "tls_review_complete": "yes" if cluster_count == 0 and candidate_count == 0 else "no",
        "tls_google_maps_review_required": "yes" if review_required else "no",
        "tls_google_maps_review_status": "needs_google_review" if review_required else "not_required",
        "tls_keep_count": 0,
        "tls_remove_count": 0,
        "tls_downgrade_count": 0,
        "tls_needs_review_count": cluster_count,
    }


def _tls_gate_value(tls_report: Mapping[str, Any], tls_summary: Mapping[str, Any]) -> str:
    base_gate = _gate_value(tls_report)
    if base_gate != "pass":
        return base_gate
    if tls_summary.get("tls_google_maps_review_required") == "yes":
        return "blocked"
    return "pass"


def _routeability_scale_profile(
    connectivity_report: Mapping[str, Any],
    *,
    requested_vehicle_count: int | None,
    requested_initial_end: int | None,
    requested_max_end: int | None,
) -> dict[str, Any]:
    passenger_edge_count = _int_field(connectivity_report, "passenger_edge_count")
    if passenger_edge_count <= 1500:
        profile = "small"
        floor_vehicle_count = 50
        floor_initial_end = 180
        floor_max_end = 1200
    elif passenger_edge_count <= 6000:
        profile = "medium"
        floor_vehicle_count = 100
        floor_initial_end = 300
        floor_max_end = 2400
    elif passenger_edge_count <= 15000:
        profile = "large"
        floor_vehicle_count = 200
        floor_initial_end = 600
        floor_max_end = 3600
    else:
        profile = "metro"
        floor_vehicle_count = 300
        floor_initial_end = 900
        floor_max_end = 5400

    vehicle_count = max(requested_vehicle_count or 0, floor_vehicle_count)
    initial_end = max(requested_initial_end or 0, floor_initial_end)
    max_end = max(requested_max_end or 0, floor_max_end)
    requested = {
        "vehicle_count": requested_vehicle_count,
        "initial_end": requested_initial_end,
        "max_end": requested_max_end,
    }
    floor_applied = (
        requested_vehicle_count is not None
        and requested_vehicle_count < floor_vehicle_count
        or requested_initial_end is not None
        and requested_initial_end < floor_initial_end
        or requested_max_end is not None
        and requested_max_end < floor_max_end
    )
    if all(value is None for value in requested.values()):
        profile_status = "scale_profile_selected"
    elif floor_applied:
        profile_status = "scale_floor_applied"
    else:
        profile_status = "caller_values_confirmed"
    return {
        "routeability_audit_profile": profile,
        "routeability_audit_profile_status": profile_status,
        "routeability_audit_scale_basis": f"passenger_edge_count={passenger_edge_count}",
        "routeability_audit_vehicle_count": vehicle_count,
        "routeability_audit_initial_end": initial_end,
        "routeability_audit_max_end": max_end,
        "routeability_audit_floor_vehicle_count": floor_vehicle_count,
        "routeability_audit_floor_initial_end": floor_initial_end,
        "routeability_audit_floor_max_end": floor_max_end,
        "routeability_audit_requested_vehicle_count": requested_vehicle_count if requested_vehicle_count is not None else "",
        "routeability_audit_requested_initial_end": requested_initial_end if requested_initial_end is not None else "",
        "routeability_audit_requested_max_end": requested_max_end if requested_max_end is not None else "",
    }


def _reference_join_gate(report: Mapping[str, Any] | None) -> str:
    if report is None:
        return "skipped"
    if _int_field(report, "reference_case_count") == 0:
        return "skipped"
    return _gate_value(report)


def _junction_pattern_index_gate(report: Mapping[str, Any] | None) -> str:
    if report is None:
        return "skipped"
    if report.get("status") != "pass":
        return _gate_value(report)
    if report.get("junction_pattern_index"):
        return "pass"
    if _int_field(report, "reference_case_count") == 0:
        return "skipped"
    return "blocked"


def _teacher_guided_parity_gate(report: Mapping[str, Any] | None) -> str:
    if report is None:
        return "skipped"
    if report.get("status") != "pass":
        return _gate_value(report)
    if report.get("parity_gate_status") == "pass":
        return "pass"
    if _int_field(report, "repair_candidate_count") == 0:
        return "skipped"
    return "blocked"


def _teacher_guided_best_variant_file(report: Mapping[str, Any] | None) -> Path | None:
    if report is None:
        return None
    composite_net_file = str(report.get("composite_net_file", ""))
    has_accepted_composite = _int_field(report, "composite_applied_candidate_count") > 0 or (
        report.get("status") == "pass" and report.get("parity_gate_status") == "pass"
    )
    if has_accepted_composite and composite_net_file and Path(composite_net_file).exists():
        return Path(composite_net_file)
    if report.get("status") != "pass" or report.get("parity_gate_status") != "pass":
        return None
    for variant in report.get("variant_reports", []) or []:
        if not isinstance(variant, Mapping):
            continue
        if variant.get("status") != "pass" or variant.get("parity_gate_status") != "pass":
            continue
        sumo_load = variant.get("sumo_load", {})
        if isinstance(sumo_load, Mapping) and sumo_load.get("status") != "pass":
            continue
        final_net_file = str(variant.get("final_net_file", ""))
        if final_net_file and Path(final_net_file).exists():
            return Path(final_net_file)
    return None


def _teacher_guided_application_stats(
    report: Mapping[str, Any] | None, best_variant_file: Path | None
) -> dict[str, str | int]:
    pass_count = 0 if report is None else _int_field(report, "pass_candidate_count")
    composite_applied_count = 0 if report is None else _int_field(report, "composite_applied_candidate_count")
    applied_count = composite_applied_count if composite_applied_count and best_variant_file is not None else 0
    if not applied_count and best_variant_file is not None:
        applied_count = 1
    if report is None:
        scope = "skipped"
    elif composite_applied_count > 1 and best_variant_file is not None:
        scope = "sequential_composite"
    elif applied_count:
        scope = "single_best_variant"
    else:
        scope = "none"
    return {
        "teacher_guided_repair_application_scope": scope,
        "teacher_guided_repair_applied_candidate_count": applied_count,
        "teacher_guided_repair_unapplied_pass_candidate_count": max(0, pass_count - applied_count),
    }


def _teacher_guided_equivalent_approach_edge_map(report: Mapping[str, Any] | None) -> dict[str, str]:
    if report is None:
        return {}
    edge_map: dict[str, str] = {}
    for variant in report.get("variant_reports", []) or []:
        if not isinstance(variant, Mapping):
            continue
        if variant.get("status") != "pass" or variant.get("parity_gate_status") != "pass":
            continue
        replay = variant.get("target_internal_replay", {})
        effective = replay.get("effective_edge_map", {}) if isinstance(replay, Mapping) else {}
        if isinstance(effective, Mapping):
            edge_map.update({str(key): str(value) for key, value in effective.items() if str(key) and str(value)})
    return edge_map


def export_plain_net_for_teacher_guided_repair(
    *,
    net_file: Path,
    output_dir: Path,
    prefix: str,
    netconvert_binary: str = "netconvert",
    timeout_seconds: float = 240.0,
    command_runner: Callable[..., Any] = run_command,
) -> dict[str, Any]:
    net_file = net_file.resolve()
    output_dir = output_dir.resolve()
    if not net_file.exists():
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "error": f"net file does not exist: {net_file}",
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    plain_prefix, plain_prefix_shortened, plain_prefix_digest = _plain_output_prefix(output_dir, prefix)
    command = [
        netconvert_binary,
        "--sumo-net-file",
        str(net_file),
        "--plain-output-prefix",
        str(plain_prefix),
    ]
    result = command_runner(command, cwd=output_dir, timeout_seconds=timeout_seconds)
    if hasattr(result, "to_dict"):
        netconvert_report = result.to_dict()
    elif isinstance(result, dict):
        netconvert_report = dict(result)
    else:
        netconvert_report = {
            "status": getattr(result, "status", "fail"),
            "returncode": getattr(result, "returncode", None),
        }
    if "status" not in netconvert_report:
        netconvert_report["status"] = "pass" if netconvert_report.get("returncode") == 0 else "fail"

    raw_node_file = Path(f"{plain_prefix}.nod.xml")
    raw_edge_file = Path(f"{plain_prefix}.edg.xml")
    raw_connection_file = Path(f"{plain_prefix}.con.xml")
    raw_type_file = Path(f"{plain_prefix}.typ.xml")
    raw_tllogic_file = Path(f"{plain_prefix}.tll.xml")
    synthesized_edge_type_ids = _synthesize_missing_plain_edge_types(raw_edge_file, raw_type_file)
    missing_required = [
        str(path)
        for path in (raw_node_file, raw_edge_file, raw_connection_file)
        if not path.exists()
    ]
    status = "pass" if netconvert_report.get("status") == "pass" and not missing_required else "fail"
    return {
        "status": status,
        "claim_status": "diagnostic-demo" if status == "pass" else "construction-invalid",
        "net_file": str(net_file),
        "plain_output_prefix": str(plain_prefix),
        "requested_plain_output_prefix": str(output_dir / prefix),
        "plain_output_prefix_shortened": plain_prefix_shortened,
        "plain_output_prefix_digest": plain_prefix_digest,
        "raw_node_file": str(raw_node_file),
        "raw_edge_file": str(raw_edge_file),
        "raw_connection_file": str(raw_connection_file),
        "raw_type_file": str(raw_type_file) if raw_type_file.exists() else "",
        "raw_tllogic_file": str(raw_tllogic_file) if raw_tllogic_file.exists() else "",
        "synthesized_edge_type_count": len(synthesized_edge_type_ids),
        "synthesized_edge_type_ids": synthesized_edge_type_ids,
        "missing_required_plain_files": missing_required,
        "netconvert": netconvert_report,
    }


def _plain_output_prefix(output_dir: Path, prefix: str) -> tuple[Path, bool, str]:
    digest = hashlib.sha1(prefix.encode("utf-8")).hexdigest()[:8]
    plain_prefix = output_dir / prefix
    suffix_reserve = len(".nod.xml")
    path_limit = 239
    if len(str(plain_prefix.resolve())) + suffix_reserve < path_limit:
        return plain_prefix, False, digest

    output_dir_text = str(output_dir.resolve())
    max_name_len = path_limit - suffix_reserve - len(output_dir_text) - 1
    if max_name_len <= len(digest) + 2:
        return output_dir / f"p_{digest}", True, digest

    head_len = max_name_len - len(digest) - 1
    head = prefix[:head_len].strip("._-") or "plain"
    shortened = f"{head}_{digest}"
    if len(shortened) > max_name_len:
        shortened = f"p_{digest}"
    return output_dir / shortened, True, digest


def _synthesize_missing_plain_edge_types(raw_edge_file: Path, raw_type_file: Path) -> list[str]:
    if not raw_edge_file.exists():
        return []
    try:
        edge_root = ET.parse(raw_edge_file).getroot()
        if raw_type_file.exists():
            type_tree = ET.parse(raw_type_file)
            type_root = type_tree.getroot()
        else:
            type_root = ET.Element("types")
            type_tree = ET.ElementTree(type_root)
    except ET.ParseError:
        return []

    known_type_ids = {str(item.get("id")) for item in type_root.findall("type") if item.get("id")}
    synthesized = []
    for edge in edge_root.findall("edge"):
        type_id = str(edge.get("type") or "")
        if not type_id or type_id in known_type_ids:
            continue
        attrs = {"id": type_id}
        for attr in ("priority", "numLanes", "speed", "allow", "disallow", "oneway", "width"):
            value = edge.get(attr)
            if value:
                attrs[attr] = value
        if "numLanes" not in attrs:
            lane_count = len(edge.findall("lane"))
            if lane_count:
                attrs["numLanes"] = str(lane_count)
        if "speed" not in attrs:
            first_lane = edge.find("lane")
            if first_lane is not None and first_lane.get("speed"):
                attrs["speed"] = str(first_lane.get("speed"))
        ET.SubElement(type_root, "type", attrs)
        known_type_ids.add(type_id)
        synthesized.append(type_id)

    if synthesized:
        raw_type_file.parent.mkdir(parents=True, exist_ok=True)
        type_tree.write(raw_type_file, encoding="utf-8", xml_declaration=True)
    return synthesized


def _reference_join_aggregation_gate(report: Mapping[str, Any] | None) -> str:
    if report is None:
        return "skipped"
    if report.get("junction_aggregation_status") == "not_needed":
        return "skipped"
    if report.get("status") != "pass":
        return _gate_value(report)
    if _int_field(report, "junction_aggregation_candidate_count") > 0:
        return "blocked"
    return "pass"


def _reference_scope_gate(report: Mapping[str, Any] | None) -> str:
    if report is None:
        return "skipped"
    return _gate_value(report)


def _reference_scope_pruning_gate(report: Mapping[str, Any] | None) -> str:
    if report is None:
        return "skipped"
    if report.get("scope_pruning_status") == "not_needed":
        return "skipped"
    if report.get("status") != "pass":
        return _gate_value(report)
    if report.get("scope_pruning_status") == "variant_created_for_review":
        return "blocked"
    return "pass"


def _reference_hierarchy_gate(report: Mapping[str, Any] | None) -> str:
    if report is None:
        return "skipped"
    return _gate_value(report)


def _should_run_tls_aggregation(
    tls_report: Mapping[str, Any],
    tls_aggregation_func: Callable[..., dict[str, Any]],
) -> bool:
    if _int_field(tls_report, "tls_cluster_count") <= 0:
        return False
    clusters_file = Path(str(tls_report.get("clusters_file", "")))
    return clusters_file.exists() or tls_aggregation_func is not build_tls_aggregation_variant


def _tls_aggregation_preserves_controlled_connections(report: Mapping[str, Any]) -> bool:
    return str(report.get("tls_controlled_connection_preservation_status", "pass")) != "fail"


def _tls_semantic_delta_score(report: Mapping[str, Any] | None) -> int:
    if report is None:
        return 0
    return _delta_count_score(report.get("network_structural_missing_counts", {})) + _delta_count_score(
        report.get("network_structural_extra_counts", {})
    )


def _reference_visual_tls_guess_signal_distances(
    *,
    reference_net_file: Path | None,
    network_profile: str,
) -> tuple[float | None, ...]:
    if reference_net_file is not None and network_profile == "reference_matched":
        return (35.0, 20.0, None)
    return (35.0,)


def _tls_guess_signal_distance_label(distance_m: float | None) -> str:
    if distance_m is None:
        return "default"
    if float(distance_m).is_integer():
        return f"guess{int(distance_m)}"
    return "guess" + str(distance_m).replace(".", "p")


def _command_result_report(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        report = result.to_dict()
    elif isinstance(result, Mapping):
        report = dict(result)
    else:
        report = {
            "status": getattr(result, "status", "fail"),
            "returncode": getattr(result, "returncode", None),
            "stdout": getattr(result, "stdout", ""),
            "stderr": getattr(result, "stderr", ""),
            "error": getattr(result, "error", ""),
        }
    if "status" not in report:
        report["status"] = "pass" if report.get("returncode") == 0 else "fail"
    return report


def _sumo_load_net(
    net_file: Path,
    *,
    output_dir: Path,
    sumo_binary: str,
    timeout_seconds: float,
    command_runner: Callable[..., Any],
) -> dict[str, Any]:
    if not net_file.exists():
        return {"status": "fail", "error": f"net file does not exist: {net_file}"}
    output_dir.mkdir(parents=True, exist_ok=True)
    load_net_file = output_dir / "sumo_load_candidate.net.xml"
    try:
        if load_net_file.resolve() != net_file.resolve():
            shutil.copyfile(net_file, load_net_file)
    except OSError as exc:
        return {"status": "fail", "error": f"{type(exc).__name__}: {exc}"}
    command = [
        sumo_binary,
        "-n",
        _command_path_for_cwd(load_net_file, output_dir),
        "--no-step-log",
        "true",
        "--duration-log.disable",
        "true",
        "--begin",
        "0",
        "--end",
        "1",
    ]
    report = _command_result_report(command_runner(command, cwd=output_dir, timeout_seconds=timeout_seconds))
    report["source_net_file"] = str(net_file)
    report["load_net_file"] = str(load_net_file)
    return report


def _has_tls_incompatibility_warning(report: Mapping[str, Any] | None) -> bool:
    if report is None:
        return False
    text = "\n".join(str(report.get(field, "")) for field in ("stdout", "stderr", "error")).lower()
    return "tllogic" in text and "incompatible with logic" in text


def _command_path_for_cwd(path: Path, cwd: Path) -> str:
    try:
        return str(Path(os.path.relpath(path.resolve(), cwd.resolve())))
    except ValueError:
        return str(path)


def _tls_connection_repair_promotion_decision(
    *,
    repair_report: Mapping[str, Any] | None,
    sumo_load_report: Mapping[str, Any] | None,
    repair_delta_report: Mapping[str, Any] | None,
    rejected_delta_report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if repair_report is None or repair_report.get("status") != "pass":
        return {"status": "blocked", "reason": "repair_not_pass"}
    variant_file = Path(str(repair_report.get("variant_file", "")))
    if not variant_file.exists():
        return {"status": "blocked", "reason": "repair_variant_missing"}
    if _int_field(repair_report, "skipped_invalid_mapped_linkindex_connection_count") > 0:
        return {"status": "blocked", "reason": "invalid_mapped_linkindex_skipped"}
    if sumo_load_report is None or sumo_load_report.get("status") != "pass":
        return {"status": "blocked", "reason": "sumo_load_not_pass"}
    if _has_tls_incompatibility_warning(sumo_load_report):
        return {"status": "blocked", "reason": "sumo_load_tls_incompatible"}
    if repair_delta_report is None or repair_delta_report.get("status") != "pass":
        return {"status": "blocked", "reason": "repair_reference_delta_not_pass"}
    repair_score = _tls_semantic_delta_score(repair_delta_report)
    rejected_score = _tls_semantic_delta_score(rejected_delta_report)
    if repair_score > rejected_score:
        return {
            "status": "blocked",
            "reason": "reference_tls_semantic_delta_regressed",
            "repair_tls_semantic_delta_score": repair_score,
            "rejected_tls_semantic_delta_score": rejected_score,
        }
    return {
        "status": "pass",
        "reason": "tls_connection_repair_promoted_after_sumo_load_and_reference_delta",
        "repair_tls_semantic_delta_score": repair_score,
        "rejected_tls_semantic_delta_score": rejected_score,
    }


def _reference_delta_promotion_decision(
    *,
    candidate_delta_report: Mapping[str, Any] | None,
    baseline_delta_report: Mapping[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    if candidate_delta_report is None or candidate_delta_report.get("status") != "pass":
        return {"status": "blocked", "reason": "candidate_reference_delta_not_pass"}
    if baseline_delta_report is None or baseline_delta_report.get("status") != "pass":
        return {"status": "blocked", "reason": "baseline_reference_delta_not_pass"}
    candidate_score = _tls_semantic_delta_score(candidate_delta_report)
    baseline_score = _tls_semantic_delta_score(baseline_delta_report)
    if candidate_score > baseline_score:
        return {
            "status": "blocked",
            "reason": "reference_tls_semantic_delta_regressed",
            "candidate_tls_semantic_delta_score": candidate_score,
            "baseline_tls_semantic_delta_score": baseline_score,
        }
    return {
        "status": "pass",
        "reason": reason,
        "candidate_tls_semantic_delta_score": candidate_score,
        "baseline_tls_semantic_delta_score": baseline_score,
    }


def _low_vehicle_control_candidate_limits(delta_report: Mapping[str, Any] | None) -> list[dict[str, int | str | None]]:
    if delta_report is None:
        return []
    queue = [
        item
        for item in delta_report.get("tls_control_review_queue", []) or []
        if isinstance(item, Mapping) and item.get("review_type") == "downgrade_low_vehicle_approach_tls"
    ]
    if not queue:
        return []
    extra_counts = delta_report.get("network_structural_extra_counts", {})
    if not isinstance(extra_counts, Mapping):
        extra_counts = {}
    limits: list[dict[str, int | str | None]] = []
    seen: set[tuple[int | None, int | None]] = set()

    def add_limit(label: str, *, max_removed: int | None = None, max_selected: int | None = None) -> None:
        if max_removed is not None and max_removed <= 0:
            return
        if max_selected is not None:
            if max_selected <= 0:
                return
            max_selected = min(max_selected, len(queue))
        key = (max_removed, max_selected)
        if key in seen:
            return
        seen.add(key)
        limits.append(
            {
                "label": label,
                "max_removed_controlled_connections": max_removed,
                "max_selected_tllogic_count": max_selected,
            }
        )

    extra_controlled = int(extra_counts.get("tls_controlled_connection_count", 0) or 0)
    add_limit(f"controlled{extra_controlled}", max_removed=extra_controlled)

    extra_tllogic = int(extra_counts.get("tl_logic_count", 0) or 0)
    extra_junctions = int(extra_counts.get("traffic_light_junction_count", 0) or 0)
    extra_tls = min(count for count in (extra_tllogic, extra_junctions) if count > 0) if any(
        count > 0 for count in (extra_tllogic, extra_junctions)
    ) else 0
    if extra_tls > 0:
        add_limit(f"tls{max(1, extra_tls // 4)}", max_selected=max(1, extra_tls // 4))
        add_limit(f"tls{max(1, extra_tls // 2)}", max_selected=max(1, extra_tls // 2))
        add_limit(f"tls{extra_tls}", max_selected=extra_tls)
    return limits[:3]


def _tls_control_review_category_counts(report: Mapping[str, Any] | None) -> dict[str, int]:
    if report is None:
        return {}
    counts: dict[str, int] = {}
    for entry in report.get("tls_control_review_queue", []) or []:
        if not isinstance(entry, Mapping):
            continue
        category = str(entry.get("repair_category", ""))
        if category:
            counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))


def _tls_representative_id_map(report: Mapping[str, Any] | None) -> dict[str, str]:
    if report is None:
        return {}
    representatives_file = Path(str(report.get("tls_aggregation_representatives_file", "")))
    if not representatives_file.exists():
        return {}
    tls_id_map: dict[str, str] = {}
    with representatives_file.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            representative = str(row.get("representative_node_id", ""))
            if not representative:
                continue
            for tls_id in str(row.get("tls_ids", "")).split(";"):
                if tls_id:
                    tls_id_map[tls_id] = representative
    return tls_id_map


def _delta_count_score(counts: Any) -> int:
    if not isinstance(counts, Mapping):
        return 0
    return sum(int(value or 0) for key, value in counts.items() if key in TLS_SEMANTIC_DELTA_KEYS)


def _junction_aggregation_summary(topology_audit_report: Mapping[str, Any] | None) -> dict[str, Any]:
    if topology_audit_report is None:
        return {
            "junction_aggregation_candidate_count": 0,
            "junction_aggregation_join_candidate_count": 0,
            "junction_aggregation_needs_map_review_count": 0,
            "junction_aggregation_do_not_join_count": 0,
            "junction_aggregation_blocked_by_corridor_count": 0,
            "junction_aggregation_candidates_file": "",
            "junction_aggregation_decision_counts": {},
        }
    clusters = list(topology_audit_report.get("suspicious_clusters", []))
    decision_counts = {
        "join": 0,
        "needs_map_review": 0,
        "do_not_join": 0,
    }
    for cluster in clusters:
        decision = str(cluster.get("aggregation_decision", "needs_map_review"))
        if decision not in decision_counts:
            decision = "needs_map_review"
        if cluster.get("corridor_decision") == "reject" and decision in {"join", "needs_map_review"}:
            decision_counts["blocked_by_corridor"] = decision_counts.get("blocked_by_corridor", 0) + 1
            continue
        decision_counts[decision] += 1
    return {
        "junction_aggregation_candidate_count": decision_counts["join"] + decision_counts["needs_map_review"],
        "junction_aggregation_join_candidate_count": decision_counts["join"],
        "junction_aggregation_needs_map_review_count": decision_counts["needs_map_review"],
        "junction_aggregation_do_not_join_count": decision_counts["do_not_join"],
        "junction_aggregation_blocked_by_corridor_count": decision_counts.get("blocked_by_corridor", 0),
        "junction_aggregation_candidates_file": str(topology_audit_report.get("clusters_file", "")),
        "junction_aggregation_decision_counts": decision_counts,
    }


def _reference_bbox_fields(reference_bbox_report: Mapping[str, Any] | None) -> dict[str, Any]:
    if reference_bbox_report is None:
        return {
            "reference_bbox_status": "not_used",
            "reference_bbox": "",
            "reference_bbox_source": "",
            "reference_bbox_padding_m": "",
            "reference_orig_boundary": "",
            "reference_conv_boundary": "",
            "reference_bbox_report": {},
        }
    return {
        "reference_bbox_status": str(reference_bbox_report.get("reference_bbox_status", "not_used")),
        "reference_bbox": str(reference_bbox_report.get("reference_bbox", "")),
        "reference_bbox_source": str(reference_bbox_report.get("reference_bbox_source", "")),
        "reference_bbox_padding_m": reference_bbox_report.get("reference_bbox_padding_m", ""),
        "reference_orig_boundary": str(reference_bbox_report.get("reference_orig_boundary", "")),
        "reference_conv_boundary": str(reference_bbox_report.get("reference_conv_boundary", "")),
        "reference_bbox_report": dict(reference_bbox_report),
    }


def run_osm_cleanup_workflow(
    *,
    output_dir: Path,
    bbox: str | None = None,
    place_name: str | None = None,
    confirmed_area: bool = False,
    prefix: str = "sumo_osm_cleanup",
    source_osm_path: Path | None = None,
    highway_classes: set[str] | None = None,
    traffic_layers: str | set[str] | None = None,
    network_profile: str | None = None,
    reference_net_file: Path | None = None,
    reference_policy_report: str | Path | Mapping[str, Any] | None = None,
    service_passenger_policy: str | None = None,
    historical_date: str | None = None,
    overpass_url: str = "https://overpass-api.de/api/interpreter",
    timeout_seconds: float = 240.0,
    netconvert_binary: str = "netconvert",
    sumo_binary: str = "sumo",
    max_tile_area_km2: float = 2500.0,
    max_retries: int = 2,
    retry_pause_seconds: float = 5.0,
    map_temporal_scope: str = "current",
    map_target_date: str | None = None,
    launch_netedit_after_build: bool = True,
    launch_netedit_review_after_build: bool | None = None,
    launch_sumo_gui_after_build: bool = True,
    run_topology_audit_after_build: bool = True,
    topology_cluster_radius_m: float = 30.0,
    topology_min_cluster_nodes: int = 3,
    run_routeability_audit_after_build: bool = True,
    routeability_vehicle_count: int | None = None,
    routeability_initial_end: int | None = None,
    routeability_max_end: int | None = None,
    run_tls_aggregation_after_build: bool = True,
    run_junction_aggregation_after_build: bool = True,
    run_reference_join_audit_after_build: bool = True,
    reference_join_audit_structural_only: bool = True,
    run_reference_join_aggregation_after_build: bool = True,
    run_reference_hierarchy_audit_after_build: bool = True,
    run_reference_scope_audit_after_build: bool = True,
    run_scope_pruning_after_build: bool = False,
    teacher_guided_repair_max_ready_candidates: int | None = 80,
    key_edge_queries: list[Mapping[str, Any]] | None = None,
    build_func: Callable[..., dict[str, Any]] = build_osm_network,
    tls_audit_func: Callable[..., dict[str, Any]] = audit_tls,
    connectivity_func: Callable[[Path], dict[str, Any]] = summarize_passenger_connectivity,
    connected_core_func: Callable[..., dict[str, Any]] = extract_largest_passenger_component_core,
    routeability_func: Callable[..., dict[str, Any]] = build_routeability_probe,
    topology_audit_func: Callable[..., dict[str, Any]] = audit_topology_fragmentation,
    routeability_audit_func: Callable[..., dict[str, Any]] = run_routeability_audit,
    tls_aggregation_func: Callable[..., dict[str, Any]] = build_tls_aggregation_variant,
    tls_signal_grouping_func: Callable[..., dict[str, Any]] = build_tls_signal_grouping_variant,
    tls_low_vehicle_control_func: Callable[..., dict[str, Any]] = build_tls_low_vehicle_control_variant,
    tls_connection_repair_func: Callable[..., dict[str, Any]] = build_tls_connection_repair_variant,
    junction_aggregation_func: Callable[..., dict[str, Any]] = build_junction_aggregation_variant,
    reference_hierarchy_audit_func: Callable[..., dict[str, Any]] = audit_reference_hierarchy,
    reference_join_audit_func: Callable[..., dict[str, Any]] = audit_reference_join_patterns,
    reference_join_aggregation_func: Callable[..., dict[str, Any]] = build_junction_aggregation_variant,
    teacher_guided_repair_queue_func: Callable[..., dict[str, Any]] = build_teacher_guided_repair_queue,
    teacher_guided_plain_export_func: Callable[..., dict[str, Any]] = export_plain_net_for_teacher_guided_repair,
    teacher_guided_repair_run_func: Callable[..., dict[str, Any]] = run_teacher_guided_repair_queue,
    reference_scope_audit_func: Callable[..., dict[str, Any]] = audit_reference_scope,
    scope_pruning_func: Callable[..., dict[str, Any]] = build_scope_pruning_variant,
    netedit_func: Callable[[Path], dict[str, Any]] = launch_netedit,
    netedit_review_func: Callable[[Path], dict[str, Any]] | None = None,
    sumo_gui_func: Callable[..., dict[str, Any]] = launch_sumo_gui,
    place_resolver: Callable[[str], dict[str, Any]] = resolve_osm_place,
    reference_bbox_func: Callable[[Path], dict[str, Any]] = derive_reference_net_bbox,
    service_permission_func: Callable[..., dict[str, Any]] = apply_service_passenger_permissions,
    review_html_func: Callable[..., dict[str, Any]] = build_workflow_review_html,
    command_runner: Callable[..., Any] = run_command,
) -> dict[str, Any]:
    cleaned_place_name = (place_name or "").strip()
    bbox_input = (bbox or "").strip()
    bbox_from_url = osm_map_url_bbox(bbox_input)
    if bbox_from_url:
        cleaned_place_name = bbox_input
        bbox = bbox_from_url
    else:
        bbox_from_url = osm_map_url_bbox(cleaned_place_name)
        if bbox_from_url:
            bbox = bbox_from_url

    place_report = None
    reference_bbox_report: dict[str, Any] | None = None
    if not bbox and source_osm_path is None and reference_net_file is not None:
        reference_bbox_report = reference_bbox_func(reference_net_file)
        derived_bbox = str(reference_bbox_report.get("reference_bbox", "")).strip()
        if reference_bbox_report.get("status") == "pass" and derived_bbox:
            bbox = derived_bbox
    if cleaned_place_name and not bbox and source_osm_path is None:
        place_report = place_resolver(cleaned_place_name)
        if not confirmed_area:
            return _blocked_place_report(cleaned_place_name, output_dir, place_report)
        resolved_bbox = str(place_report.get("candidate_bbox", ""))
        if place_report.get("status") != "pass" or not resolved_bbox:
            return {
                "status": "fail",
                "claim_status": "construction-invalid",
                "area_input": cleaned_place_name,
                "area_resolution_status": str(place_report.get("area_resolution_status", "blocked")),
                **_candidate_fields(place_report),
                "osm_preview_url": str(place_report.get("osm_preview_url", osm_preview_url(cleaned_place_name))),
                "user_confirmed_area": "yes",
                "gate_status": {
                    "area_confirmation": "fail",
                    "road_level_scope": "not_started",
                    "network_build": "not_started",
                    "tls_reality_audit": "not_started",
                    "connectivity": "not_started",
                    "routeability_audit": "not_started",
                    "netedit": "not_started",
                    "sumo_gui": "not_started",
                },
                "warnings": list(place_report.get("warnings", [])) + ["confirmed place_name could not be resolved to a bbox"],
            }
        bbox = resolved_bbox
    if not bbox:
        reference_bbox_status = (
            str(reference_bbox_report.get("reference_bbox_status", "blocked"))
            if reference_bbox_report is not None
            else "blocked"
        )
        reference_bbox_warnings = list(reference_bbox_report.get("warnings", [])) if reference_bbox_report else []
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "area_input": cleaned_place_name,
            "area_resolution_status": reference_bbox_status,
            **_candidate_fields(place_report),
            **_reference_bbox_fields(reference_bbox_report),
            "gate_status": {
                "area_confirmation": "fail",
                "road_level_scope": "not_started",
                "network_build": "not_started",
                "tls_reality_audit": "not_started",
                "connectivity": "not_started",
                "routeability_audit": "not_started",
                "netedit": "not_started",
                "sumo_gui": "not_started",
            },
            "warnings": reference_bbox_warnings + ["bbox is required for OSM network construction"],
        }

    area_status = "confirmed_by_user" if cleaned_place_name and confirmed_area else "confirmed_by_input"
    network_plan = derive_network_plan(
        highway_classes=highway_classes,
        traffic_layers=traffic_layers,
        network_profile=network_profile,
        reference_net_file=reference_net_file,
        reference_policy_report=reference_policy_report,
        service_passenger_policy=service_passenger_policy,
    )
    if network_plan.get("status") == "blocked":
        return _blocked_road_level_scope_report(
            area_input=cleaned_place_name or bbox,
            area_status=area_status,
            place_report=place_report,
            cleaned_place_name=cleaned_place_name,
            bbox=bbox,
            network_plan=network_plan,
        )
    if network_plan.get("status") != "pass":
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "area_input": cleaned_place_name or bbox,
            "area_resolution_status": area_status,
            **(_candidate_fields(place_report) if place_report is not None else {**_candidate_fields(None), "candidate_bbox": bbox}),
            "user_confirmed_area": "yes" if area_status == "confirmed_by_user" else "confirmed_by_input",
            "network_plan_status": network_plan.get("network_plan_status", "failed"),
            "network_profile": network_plan.get("network_profile", ""),
            "reference_target": network_plan.get("reference_target", ""),
            "reference_net_file": network_plan.get("reference_net_file", ""),
            "network_detail_target": network_plan.get("network_detail_target", ""),
            "movement_layers": network_plan.get("movement_layers", []),
            "selected_highway_classes": network_plan.get("highway_classes", []),
            "service_passenger_policy": network_plan.get("service_passenger_policy", "sumo_default"),
            "network_plan": network_plan,
            "gate_status": {
                "area_confirmation": "pass",
                "road_level_scope": "fail",
                "network_build": "not_started",
                "tls_reality_audit": "not_started",
                "connectivity": "not_started",
                "routeability_audit": "not_started",
                "netedit": "not_started",
                "sumo_gui": "not_started",
            },
            "warnings": list(network_plan.get("warnings", [])),
        }
    selected_highway_classes = set(network_plan.get("highway_classes", []))
    reference_source_way_ids = {
        str(item)
        for item in network_plan.get("reference_source_way_ids", [])
        if str(item).strip()
    }
    reference_source_way_scope = reference_source_way_ids or None
    build_report = build_func(
        bbox=bbox,
        output_dir=output_dir,
        prefix=prefix,
        source_osm_path=source_osm_path,
        allowed_highways=selected_highway_classes,
        allowed_way_ids=reference_source_way_scope,
        historical_date=historical_date,
        overpass_url=overpass_url,
        timeout_seconds=timeout_seconds,
        max_tile_area_km2=max_tile_area_km2,
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
        netconvert_profile="vehicle_core",
    )
    if build_report.get("status") != "pass":
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "area_input": cleaned_place_name or bbox,
            "area_resolution_status": area_status,
            **_candidate_fields(place_report),
            "user_confirmed_area": "yes" if area_status == "confirmed_by_user" else "confirmed_by_input",
            "network_plan_status": network_plan.get("network_plan_status", "confirmed"),
            "network_profile": network_plan.get("network_profile", ""),
            "reference_target": network_plan.get("reference_target", ""),
            "reference_net_file": network_plan.get("reference_net_file", ""),
            "network_detail_target": network_plan.get("network_detail_target", ""),
            "primary_network_layer": network_plan.get("primary_network_layer", ""),
            "auxiliary_modal_layers": network_plan.get("auxiliary_modal_layers", []),
            "movement_layers": network_plan.get("movement_layers", []),
            "selected_highway_classes": network_plan.get("highway_classes", []),
            "service_passenger_policy": network_plan.get("service_passenger_policy", "sumo_default"),
            "reference_policy": network_plan.get("reference_policy", {}),
            "build": build_report,
            "gate_status": {
                "area_confirmation": "pass",
                "road_level_scope": "pass",
                "network_build": _gate_value(build_report),
                "tls_reality_audit": "not_started",
                "connectivity": "not_started",
                "routeability_audit": "not_started",
                "netedit": "not_started",
                "sumo_gui": "not_started",
            },
            "warnings": list(build_report.get("warnings", [])),
        }

    raw_net_file = Path(str(build_report["net_file"]))
    service_permission_report = service_permission_func(
        raw_net_file,
        policy=str(network_plan.get("service_passenger_policy", "sumo_default")),
    )
    if service_permission_report.get("status") != "pass":
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "area_input": cleaned_place_name or bbox,
            "area_resolution_status": area_status,
            **_candidate_fields(place_report),
            "user_confirmed_area": "yes" if area_status == "confirmed_by_user" else "confirmed_by_input",
            "network_plan_status": network_plan.get("network_plan_status", "confirmed"),
            "network_profile": network_plan.get("network_profile", ""),
            "reference_target": network_plan.get("reference_target", ""),
            "reference_net_file": network_plan.get("reference_net_file", ""),
            "network_detail_target": network_plan.get("network_detail_target", ""),
            "primary_network_layer": network_plan.get("primary_network_layer", ""),
            "auxiliary_modal_layers": network_plan.get("auxiliary_modal_layers", []),
            "movement_layers": network_plan.get("movement_layers", []),
            "selected_highway_classes": network_plan.get("highway_classes", []),
            "service_passenger_policy": network_plan.get("service_passenger_policy", "sumo_default"),
            "reference_policy": network_plan.get("reference_policy", {}),
            "build": build_report,
            "service_passenger_permissions": service_permission_report,
            "gate_status": {
                "area_confirmation": "pass",
                "road_level_scope": "pass",
                "network_build": _gate_value(build_report),
                "tls_reality_audit": "not_started",
                "connectivity": "not_started",
                "routeability_audit": "not_started",
                "netedit": "not_started",
                "sumo_gui": "not_started",
            },
            "warnings": list(build_report.get("warnings", [])) + list(service_permission_report.get("warnings", [])),
        }
    net_file = raw_net_file
    reference_visual_detail_status = "not_applicable"
    reference_visual_detail_net_file: Path | None = None
    reference_visual_detail_comparison_net_file: Path | None = None
    reference_visual_detail_comparison_selection_reason = "not_applicable"
    reference_visual_detail_build_report: dict[str, Any] = {}
    reference_visual_detail_service_permission_report: dict[str, Any] = {}
    reference_visual_detail_netedit_report: dict[str, Any] = {}
    reference_visual_detail_tls_report: dict[str, Any] | None = None
    reference_visual_detail_tls_aggregation_report: dict[str, Any] | None = None
    reference_visual_detail_tls_aggregation_candidates: list[dict[str, Any]] = []
    reference_visual_detail_tls_signal_grouping_report: dict[str, Any] | None = None
    reference_visual_detail_tls_low_vehicle_control_report: dict[str, Any] | None = None
    reference_visual_detail_tls_low_vehicle_control_candidates: list[dict[str, Any]] = []
    reference_visual_detail_tls_connection_repair_report: dict[str, Any] | None = None
    reference_visual_detail_raw_reference_delta_report: dict[str, Any] | None = None
    reference_visual_detail_tls_aggregation_reference_delta_report: dict[str, Any] | None = None
    reference_visual_detail_tls_aggregation_reference_promotion_report: dict[str, Any] = {
        "status": "skipped",
        "reason": "not_run",
    }
    reference_visual_detail_tls_signal_grouping_reference_delta_report: dict[str, Any] | None = None
    reference_visual_detail_tls_signal_grouping_reference_promotion_report: dict[str, Any] = {
        "status": "skipped",
        "reason": "not_run",
    }
    reference_visual_detail_tls_low_vehicle_control_sumo_load_report: dict[str, Any] | None = None
    reference_visual_detail_tls_low_vehicle_control_reference_delta_report: dict[str, Any] | None = None
    reference_visual_detail_tls_low_vehicle_control_reference_promotion_report: dict[str, Any] = {
        "status": "skipped",
        "reason": "not_run",
    }
    reference_visual_detail_tls_signal_grouping_sumo_load_report: dict[str, Any] | None = None
    reference_visual_detail_tls_connection_repair_reference_delta_report: dict[str, Any] | None = None
    reference_visual_detail_tls_connection_repair_sumo_load_report: dict[str, Any] | None = None
    reference_visual_detail_tls_connection_repair_promotion_report: dict[str, Any] = {
        "status": "skipped",
        "reason": "not_run",
    }
    junction_aggregation_report: dict[str, Any] | None = None
    reference_join_audit_report: dict[str, Any] | None = None
    reference_join_post_teacher_audit_report: dict[str, Any] | None = None
    post_teacher_tls_low_vehicle_control_report: dict[str, Any] | None = None
    post_teacher_tls_low_vehicle_control_candidates: list[dict[str, Any]] = []
    post_teacher_tls_low_vehicle_control_sumo_load_report: dict[str, Any] | None = None
    post_teacher_tls_low_vehicle_control_reference_delta_report: dict[str, Any] | None = None
    post_teacher_tls_low_vehicle_control_reference_promotion_report: dict[str, Any] = {
        "status": "skipped",
        "reason": "not_run",
    }
    post_teacher_tls_signal_grouping_report: dict[str, Any] | None = None
    post_teacher_tls_signal_grouping_sumo_load_report: dict[str, Any] | None = None
    post_teacher_tls_signal_grouping_reference_delta_report: dict[str, Any] | None = None
    post_teacher_tls_signal_grouping_reference_promotion_report: dict[str, Any] = {
        "status": "skipped",
        "reason": "not_run",
    }
    post_teacher_tls_connection_repair_report: dict[str, Any] | None = None
    post_teacher_tls_connection_repair_sumo_load_report: dict[str, Any] | None = None
    post_teacher_tls_connection_repair_reference_delta_report: dict[str, Any] | None = None
    post_teacher_tls_connection_repair_reference_promotion_report: dict[str, Any] = {
        "status": "skipped",
        "reason": "not_run",
    }
    post_teacher_tls_connection_repair_movement_rebuild_queue_report: dict[str, Any] | None = None
    post_teacher_tls_connection_repair_movement_rebuild_plain_export_report: dict[str, Any] | None = None
    post_teacher_tls_connection_repair_movement_rebuild_run_report: dict[str, Any] | None = None
    post_teacher_tls_connection_repair_movement_rebuild_best_variant_file: Path | None = None
    reference_join_aggregation_report: dict[str, Any] | None = None
    teacher_guided_repair_queue_report: dict[str, Any] | None = None
    teacher_guided_plain_export_report: dict[str, Any] | None = None
    teacher_guided_repair_run_report: dict[str, Any] | None = None
    teacher_guided_repair_best_variant_file: Path | None = None
    teacher_guided_repair_best_expanded_scope_net_file: Path | None = None
    reference_hierarchy_audit_report: dict[str, Any] | None = None
    reference_hierarchy_audit_candidate_layer = "not_applicable"
    reference_hierarchy_audit_candidate_net_file: Path | None = None
    reference_scope_audit_report: dict[str, Any] | None = None
    reference_scope_pruning_report: dict[str, Any] | None = None
    reference_scope_candidate_layer = "not_applicable"
    reference_scope_candidate_net_file: Path | None = None
    reference_join_audit_candidate_layer = "not_applicable"
    reference_join_audit_candidate_net_file: Path | None = None
    tls_aggregation_report: dict[str, Any] | None = None
    vehicle_core_highway_classes = _class_set(
        network_plan.get("vehicle_core_highway_classes", network_plan.get("highway_classes", []))
    )
    reference_visual_detail_highway_classes = _class_set(
        network_plan.get("reference_visual_detail_highway_classes", [])
    )
    should_build_reference_visual_detail = (
        str(network_plan.get("network_profile", "")) == "reference_matched"
        and bool(reference_visual_detail_highway_classes)
        and reference_visual_detail_highway_classes != vehicle_core_highway_classes
    )
    if str(network_plan.get("network_profile", "")) == "reference_matched":
        reference_visual_detail_status = "same_as_vehicle_core"
    if should_build_reference_visual_detail:
        visual_source_osm_value = build_report.get("source_osm_file") or source_osm_path
        if not visual_source_osm_value:
            return {
                "status": "fail",
                "claim_status": "construction-invalid",
                "area_input": cleaned_place_name or bbox,
                "area_resolution_status": area_status,
                **_candidate_fields(place_report),
                "user_confirmed_area": "yes" if area_status == "confirmed_by_user" else "confirmed_by_input",
                "network_plan_status": network_plan.get("network_plan_status", "confirmed"),
                "network_profile": network_plan.get("network_profile", ""),
                "reference_target": network_plan.get("reference_target", ""),
                "reference_net_file": network_plan.get("reference_net_file", ""),
                "network_detail_target": network_plan.get("network_detail_target", ""),
                "selected_highway_classes": network_plan.get("highway_classes", []),
                "vehicle_core_highway_classes": sorted(vehicle_core_highway_classes),
                "reference_visual_detail_highway_classes": sorted(reference_visual_detail_highway_classes),
                "reference_visual_detail_status": "failed",
                "network_plan": network_plan,
                "reference_policy": network_plan.get("reference_policy", {}),
                "build": build_report,
                "service_passenger_permissions": service_permission_report,
                "gate_status": {
                    "area_confirmation": "pass",
                    "road_level_scope": "pass",
                    "network_build": _gate_value(build_report),
                    "reference_visual_detail": "fail",
                    "tls_reality_audit": "not_started",
                    "connectivity": "not_started",
                    "routeability_audit": "not_started",
                    "netedit": "not_started",
                    "sumo_gui": "not_started",
                },
                "warnings": list(build_report.get("warnings", []))
                + ["reference visual-detail network requires a reusable source OSM file"],
            }
        reference_visual_detail_build_report = build_func(
            bbox=bbox,
            output_dir=output_dir,
            prefix=f"{prefix}_reference_visual_detail",
            source_osm_path=Path(str(visual_source_osm_value)),
            allowed_highways=reference_visual_detail_highway_classes,
            allowed_way_ids=reference_source_way_scope,
            historical_date=historical_date,
            overpass_url=overpass_url,
            timeout_seconds=timeout_seconds,
            max_tile_area_km2=max_tile_area_km2,
            max_retries=max_retries,
            retry_pause_seconds=retry_pause_seconds,
            netconvert_profile="reference_visual_detail",
        )
        if reference_visual_detail_build_report.get("status") != "pass":
            return {
                "status": "fail",
                "claim_status": "construction-invalid",
                "area_input": cleaned_place_name or bbox,
                "area_resolution_status": area_status,
                **_candidate_fields(place_report),
                "user_confirmed_area": "yes" if area_status == "confirmed_by_user" else "confirmed_by_input",
                "network_plan_status": network_plan.get("network_plan_status", "confirmed"),
                "network_profile": network_plan.get("network_profile", ""),
                "reference_target": network_plan.get("reference_target", ""),
                "reference_net_file": network_plan.get("reference_net_file", ""),
                "network_detail_target": network_plan.get("network_detail_target", ""),
                "selected_highway_classes": network_plan.get("highway_classes", []),
                "vehicle_core_highway_classes": sorted(vehicle_core_highway_classes),
                "reference_visual_detail_highway_classes": sorted(reference_visual_detail_highway_classes),
                "reference_visual_detail_status": "failed",
                "network_plan": network_plan,
                "reference_policy": network_plan.get("reference_policy", {}),
                "build": build_report,
                "reference_visual_detail_build": reference_visual_detail_build_report,
                "service_passenger_permissions": service_permission_report,
                "gate_status": {
                    "area_confirmation": "pass",
                    "road_level_scope": "pass",
                    "network_build": _gate_value(build_report),
                    "reference_visual_detail": _gate_value(reference_visual_detail_build_report),
                    "tls_reality_audit": "not_started",
                    "connectivity": "not_started",
                    "routeability_audit": "not_started",
                    "netedit": "not_started",
                    "sumo_gui": "not_started",
                },
                "warnings": list(build_report.get("warnings", []))
                + list(reference_visual_detail_build_report.get("warnings", [])),
            }
        reference_visual_detail_net_file = Path(str(reference_visual_detail_build_report["net_file"]))
        reference_visual_detail_service_permission_report = service_permission_func(
            reference_visual_detail_net_file,
            policy=str(network_plan.get("service_passenger_policy", "sumo_default")),
        )
        if reference_visual_detail_service_permission_report.get("status") != "pass":
            return {
                "status": "fail",
                "claim_status": "construction-invalid",
                "area_input": cleaned_place_name or bbox,
                "area_resolution_status": area_status,
                **_candidate_fields(place_report),
                "user_confirmed_area": "yes" if area_status == "confirmed_by_user" else "confirmed_by_input",
                "network_plan_status": network_plan.get("network_plan_status", "confirmed"),
                "network_profile": network_plan.get("network_profile", ""),
                "reference_target": network_plan.get("reference_target", ""),
                "reference_net_file": network_plan.get("reference_net_file", ""),
                "network_detail_target": network_plan.get("network_detail_target", ""),
                "selected_highway_classes": network_plan.get("highway_classes", []),
                "vehicle_core_highway_classes": sorted(vehicle_core_highway_classes),
                "reference_visual_detail_highway_classes": sorted(reference_visual_detail_highway_classes),
                "reference_visual_detail_status": "failed",
                "network_plan": network_plan,
                "reference_policy": network_plan.get("reference_policy", {}),
                "build": build_report,
                "reference_visual_detail_build": reference_visual_detail_build_report,
                "service_passenger_permissions": service_permission_report,
                "reference_visual_detail_service_passenger_permissions": reference_visual_detail_service_permission_report,
                "gate_status": {
                    "area_confirmation": "pass",
                    "road_level_scope": "pass",
                    "network_build": _gate_value(build_report),
                    "reference_visual_detail": "fail",
                    "tls_reality_audit": "not_started",
                    "connectivity": "not_started",
                    "routeability_audit": "not_started",
                    "netedit": "not_started",
                    "sumo_gui": "not_started",
                },
                "warnings": list(build_report.get("warnings", []))
                + list(reference_visual_detail_build_report.get("warnings", []))
                + list(reference_visual_detail_service_permission_report.get("warnings", [])),
            }
        reference_visual_detail_status = "built"
        reference_visual_detail_comparison_net_file = reference_visual_detail_net_file
        reference_visual_detail_comparison_selection_reason = "raw_visual_detail"
    filtered_osm_value = build_report.get("filtered_osm_file") or build_report.get("source_osm_file")
    osm_file = Path(str(filtered_osm_value)) if filtered_osm_value else None
    tls_report = tls_audit_func(
        net_file=raw_net_file,
        output_dir=output_dir / "tls_audit",
        prefix=f"{prefix}_tls_audit",
        osm_file=osm_file,
        google_maps_temporal_scope=map_temporal_scope,
        google_maps_target_date=map_target_date,
    )
    if run_tls_aggregation_after_build and _should_run_tls_aggregation(tls_report, tls_aggregation_func):
        tls_aggregation_report = tls_aggregation_func(
            net_file=raw_net_file,
            tls_audit_report=tls_report,
            output_dir=output_dir / "tls_aggregation",
            prefix=f"{prefix}_tls_aggregation",
            timeout_seconds=timeout_seconds,
        )
        tls_variant_value = tls_aggregation_report.get("tls_aggregation_variant_file", "") if tls_aggregation_report else ""
        if (
            tls_aggregation_report.get("status") == "pass"
            and tls_variant_value
            and _tls_aggregation_preserves_controlled_connections(tls_aggregation_report)
        ):
            candidate_tls_net_file = Path(str(tls_variant_value))
            if candidate_tls_net_file.exists():
                net_file = candidate_tls_net_file
    if reference_visual_detail_net_file is not None and run_tls_aggregation_after_build:
        reference_visual_detail_tls_report = tls_audit_func(
            net_file=reference_visual_detail_net_file,
            output_dir=output_dir / "reference_visual_detail_tls_audit",
            prefix=f"{prefix}_reference_visual_detail_tls_audit",
            osm_file=osm_file,
            google_maps_temporal_scope=map_temporal_scope,
            google_maps_target_date=map_target_date,
        )
        if _should_run_tls_aggregation(reference_visual_detail_tls_report, tls_aggregation_func):
            reference_matched_tls_delta = (
                reference_net_file is not None and str(network_plan.get("network_profile", "")) == "reference_matched"
            )
            selected_tls_candidate: tuple[
                dict[str, Any],
                dict[str, Any] | None,
                dict[str, Any],
                Path,
            ] | None = None
            best_scored_tls_candidate: tuple[
                int,
                dict[str, Any],
                dict[str, Any],
                dict[str, Any],
                Path,
            ] | None = None
            first_tls_aggregation_report: dict[str, Any] | None = None
            rejected_controlled_connection_variant_file: Path | None = None
            tls_guess_signal_distances = _reference_visual_tls_guess_signal_distances(
                reference_net_file=reference_net_file,
                network_profile=str(network_plan.get("network_profile", "")),
            )
            for index, tls_guess_signals_dist_m in enumerate(tls_guess_signal_distances):
                candidate_label = _tls_guess_signal_distance_label(tls_guess_signals_dist_m)
                primary_candidate = index == 0
                aggregation_output_dir = (
                    output_dir / "reference_visual_detail_tls_aggregation"
                    if primary_candidate
                    else output_dir / f"reference_visual_detail_tls_aggregation_{candidate_label}"
                )
                aggregation_prefix = (
                    f"{prefix}_reference_visual_detail_tls_aggregation"
                    if primary_candidate
                    else f"{prefix}_reference_visual_detail_tls_aggregation_{candidate_label}"
                )
                tls_aggregation_report = tls_aggregation_func(
                    net_file=reference_visual_detail_net_file,
                    tls_audit_report=reference_visual_detail_tls_report,
                    output_dir=aggregation_output_dir,
                    prefix=aggregation_prefix,
                    timeout_seconds=timeout_seconds,
                    tls_guess_signals_dist_m=tls_guess_signals_dist_m,
                )
                if first_tls_aggregation_report is None:
                    first_tls_aggregation_report = tls_aggregation_report
                visual_tls_variant_value = tls_aggregation_report.get("tls_aggregation_variant_file", "")
                candidate_record: dict[str, Any] = {
                    "tls_guess_signals_dist_m": tls_guess_signals_dist_m,
                    "candidate_label": candidate_label,
                    "status": tls_aggregation_report.get("status", "fail"),
                    "tls_aggregation_status": tls_aggregation_report.get("tls_aggregation_status", "fail"),
                    "tls_aggregation_variant_file": visual_tls_variant_value,
                }
                netconvert_report = tls_aggregation_report.get("tls_aggregation_netconvert", {})
                if isinstance(netconvert_report, Mapping):
                    candidate_record["netconvert_returncode"] = netconvert_report.get("returncode")
                candidate_visual_tls_net_file = Path(str(visual_tls_variant_value)) if visual_tls_variant_value else None
                if (
                    tls_aggregation_report.get("status") == "pass"
                    and candidate_visual_tls_net_file is not None
                    and candidate_visual_tls_net_file.exists()
                ):
                    if reference_matched_tls_delta:
                        if reference_visual_detail_raw_reference_delta_report is None:
                            reference_visual_detail_raw_reference_delta_report = reference_join_audit_func(
                                reference_net_file=reference_net_file,
                                candidate_net_file=reference_visual_detail_net_file,
                                output_dir=output_dir / "reference_visual_detail_raw_reference_delta",
                                prefix=f"{prefix}_reference_visual_detail_raw_reference_delta",
                                candidate_cluster_radius_m=topology_cluster_radius_m,
                                candidate_min_cluster_nodes=topology_min_cluster_nodes,
                                structural_only=True,
                            )
                        delta_output_dir = (
                            output_dir / "reference_visual_detail_tls_aggregation_reference_delta"
                            if primary_candidate
                            else output_dir / f"reference_visual_detail_tls_aggregation_reference_delta_{candidate_label}"
                        )
                        delta_prefix = (
                            f"{prefix}_reference_visual_detail_tls_aggregation_reference_delta"
                            if primary_candidate
                            else f"{prefix}_reference_visual_detail_tls_aggregation_reference_delta_{candidate_label}"
                        )
                        tls_aggregation_delta_report = reference_join_audit_func(
                            reference_net_file=reference_net_file,
                            candidate_net_file=candidate_visual_tls_net_file,
                            output_dir=delta_output_dir,
                            prefix=delta_prefix,
                            candidate_cluster_radius_m=topology_cluster_radius_m,
                            candidate_min_cluster_nodes=topology_min_cluster_nodes,
                            structural_only=True,
                        )
                        tls_aggregation_promotion_report = _reference_delta_promotion_decision(
                            candidate_delta_report=tls_aggregation_delta_report,
                            baseline_delta_report=reference_visual_detail_raw_reference_delta_report,
                            reason="tls_aggregation_promoted_by_reference_delta",
                        )
                        candidate_score = _tls_semantic_delta_score(tls_aggregation_delta_report)
                        candidate_record.update(
                            {
                                "reference_tls_semantic_delta_score": candidate_score,
                                "reference_delta_file": tls_aggregation_delta_report.get("summary_file", ""),
                                "reference_promotion_status": tls_aggregation_promotion_report.get("status", ""),
                            }
                        )
                        if best_scored_tls_candidate is None or candidate_score < best_scored_tls_candidate[0]:
                            best_scored_tls_candidate = (
                                candidate_score,
                                tls_aggregation_report,
                                tls_aggregation_delta_report,
                                tls_aggregation_promotion_report,
                                candidate_visual_tls_net_file,
                            )
                        if tls_aggregation_promotion_report.get("status") == "pass" and (
                            selected_tls_candidate is None
                            or candidate_score
                            < _tls_semantic_delta_score(selected_tls_candidate[1])
                        ):
                            selected_tls_candidate = (
                                tls_aggregation_report,
                                tls_aggregation_delta_report,
                                tls_aggregation_promotion_report,
                                candidate_visual_tls_net_file,
                            )
                    elif _tls_aggregation_preserves_controlled_connections(tls_aggregation_report):
                        selected_tls_candidate = (
                            tls_aggregation_report,
                            None,
                            {
                                "status": "pass",
                                "reason": "tls_aggregation_preserved_controlled_connections",
                            },
                            candidate_visual_tls_net_file,
                        )
                        candidate_record["reference_promotion_status"] = "not_applicable"
                        reference_visual_detail_tls_aggregation_candidates.append(candidate_record)
                        break
                    else:
                        rejected_controlled_connection_variant_file = candidate_visual_tls_net_file
                reference_visual_detail_tls_aggregation_candidates.append(candidate_record)

            if selected_tls_candidate is not None:
                (
                    reference_visual_detail_tls_aggregation_report,
                    reference_visual_detail_tls_aggregation_reference_delta_report,
                    reference_visual_detail_tls_aggregation_reference_promotion_report,
                    candidate_visual_tls_net_file,
                ) = selected_tls_candidate
                reference_visual_detail_comparison_net_file = candidate_visual_tls_net_file
                reference_visual_detail_comparison_selection_reason = str(
                    reference_visual_detail_tls_aggregation_reference_promotion_report.get("reason", "")
                )
            elif best_scored_tls_candidate is not None:
                (
                    _best_tls_score,
                    reference_visual_detail_tls_aggregation_report,
                    reference_visual_detail_tls_aggregation_reference_delta_report,
                    reference_visual_detail_tls_aggregation_reference_promotion_report,
                    candidate_visual_tls_net_file,
                ) = best_scored_tls_candidate
                reference_visual_detail_comparison_net_file = candidate_visual_tls_net_file
                reference_visual_detail_comparison_selection_reason = (
                    "tls_aggregation_rejected_controlled_connection_regression"
                )
            else:
                reference_visual_detail_tls_aggregation_report = first_tls_aggregation_report
                candidate_visual_tls_net_file = rejected_controlled_connection_variant_file
                if rejected_controlled_connection_variant_file is not None:
                    reference_visual_detail_comparison_selection_reason = (
                        "tls_aggregation_rejected_controlled_connection_regression"
                    )

            if (
                selected_tls_candidate is not None
                and reference_visual_detail_tls_aggregation_reference_delta_report is not None
            ):
                missing_counts = reference_visual_detail_tls_aggregation_reference_delta_report.get(
                    "network_structural_missing_counts", {}
                )
                missing_shared_groups = int(missing_counts.get("tls_shared_linkindex_group_count", 0) or 0)
                if missing_shared_groups > 0:
                    reference_visual_detail_tls_signal_grouping_report = tls_signal_grouping_func(
                        source_net_file=candidate_visual_tls_net_file,
                        output_dir=output_dir / "reference_visual_detail_tls_signal_grouping",
                        prefix=f"{prefix}_reference_visual_detail_tls_signal_grouping",
                        max_shared_linkindex_groups=missing_shared_groups,
                    )
                    signal_grouping_variant_value = reference_visual_detail_tls_signal_grouping_report.get(
                        "tls_signal_grouping_variant_file", ""
                    )
                    signal_grouping_variant_file = (
                        Path(str(signal_grouping_variant_value)) if signal_grouping_variant_value else None
                    )
                    if signal_grouping_variant_file is not None and signal_grouping_variant_file.exists():
                        reference_visual_detail_tls_signal_grouping_sumo_load_report = _sumo_load_net(
                            signal_grouping_variant_file,
                            output_dir=output_dir / "reference_visual_detail_tls_signal_grouping",
                            sumo_binary=sumo_binary,
                            timeout_seconds=timeout_seconds,
                            command_runner=command_runner,
                        )
                        if reference_visual_detail_tls_signal_grouping_sumo_load_report.get("status") == "pass":
                            reference_visual_detail_tls_signal_grouping_reference_delta_report = (
                                reference_join_audit_func(
                                    reference_net_file=reference_net_file,
                                    candidate_net_file=signal_grouping_variant_file,
                                    output_dir=output_dir
                                    / "reference_visual_detail_tls_signal_grouping_reference_delta",
                                    prefix=f"{prefix}_reference_visual_detail_tls_signal_grouping_reference_delta",
                                    candidate_cluster_radius_m=topology_cluster_radius_m,
                                    candidate_min_cluster_nodes=topology_min_cluster_nodes,
                                    structural_only=True,
                                )
                            )
                            reference_visual_detail_tls_signal_grouping_reference_promotion_report = (
                                _reference_delta_promotion_decision(
                                    candidate_delta_report=reference_visual_detail_tls_signal_grouping_reference_delta_report,
                                    baseline_delta_report=reference_visual_detail_tls_aggregation_reference_delta_report,
                                    reason="tls_signal_grouping_promoted_by_reference_delta",
                                )
                            )
                        else:
                            reference_visual_detail_tls_signal_grouping_reference_promotion_report = {
                                "status": "blocked",
                                "reason": "sumo_load_not_pass",
                            }
                        if (
                            reference_visual_detail_tls_signal_grouping_reference_promotion_report.get("status")
                            == "pass"
                        ):
                            reference_visual_detail_comparison_net_file = signal_grouping_variant_file
                            reference_visual_detail_comparison_selection_reason = str(
                                reference_visual_detail_tls_signal_grouping_reference_promotion_report.get(
                                    "reason", ""
                                )
                            )
            low_vehicle_baseline_delta_report = (
                reference_visual_detail_tls_signal_grouping_reference_delta_report
                if reference_visual_detail_tls_signal_grouping_reference_promotion_report.get("status") == "pass"
                else reference_visual_detail_tls_aggregation_reference_delta_report
            )
            low_vehicle_source_net_file = reference_visual_detail_comparison_net_file
            if (
                low_vehicle_source_net_file is not None
                and low_vehicle_baseline_delta_report is not None
                and reference_matched_tls_delta
            ):
                low_vehicle_queue = low_vehicle_baseline_delta_report.get("tls_control_review_queue", [])
                selected_low_vehicle_candidate: tuple[
                    int,
                    dict[str, Any],
                    dict[str, Any],
                    dict[str, Any],
                    dict[str, Any],
                    Path,
                ] | None = None
                for low_vehicle_limit in _low_vehicle_control_candidate_limits(low_vehicle_baseline_delta_report):
                    low_vehicle_label = str(low_vehicle_limit["label"])
                    low_vehicle_output_dir = output_dir / f"reference_visual_detail_tls_low_vehicle_control_{low_vehicle_label}"
                    low_vehicle_report = tls_low_vehicle_control_func(
                        source_net_file=low_vehicle_source_net_file,
                        tls_control_review_queue=low_vehicle_queue,
                        output_dir=low_vehicle_output_dir,
                        prefix=f"{prefix}_reference_visual_detail_tls_low_vehicle_control_{low_vehicle_label}",
                        max_removed_controlled_connections=low_vehicle_limit["max_removed_controlled_connections"],
                        max_selected_tllogic_count=low_vehicle_limit["max_selected_tllogic_count"],
                    )
                    low_vehicle_candidate_record = {
                        "candidate_label": low_vehicle_label,
                        "status": low_vehicle_report.get("status", "fail"),
                        "max_removed_controlled_connections": low_vehicle_limit[
                            "max_removed_controlled_connections"
                        ],
                        "max_selected_tllogic_count": low_vehicle_limit["max_selected_tllogic_count"],
                        "selected_tllogic_count": low_vehicle_report.get(
                            "tls_low_vehicle_control_selected_tllogic_count", 0
                        ),
                        "removed_connection_count": low_vehicle_report.get(
                            "tls_low_vehicle_control_removed_connection_count", 0
                        ),
                    }
                    low_vehicle_variant_value = low_vehicle_report.get("tls_low_vehicle_control_variant_file", "")
                    low_vehicle_variant_file = Path(str(low_vehicle_variant_value)) if low_vehicle_variant_value else None
                    if low_vehicle_variant_file is not None and low_vehicle_variant_file.exists():
                        low_vehicle_sumo_load_report = _sumo_load_net(
                            low_vehicle_variant_file,
                            output_dir=low_vehicle_output_dir,
                            sumo_binary=sumo_binary,
                            timeout_seconds=timeout_seconds,
                            command_runner=command_runner,
                        )
                        low_vehicle_candidate_record["sumo_load_status"] = low_vehicle_sumo_load_report.get(
                            "status", "fail"
                        )
                        if low_vehicle_sumo_load_report.get("status") == "pass":
                            low_vehicle_delta_report = reference_join_audit_func(
                                reference_net_file=reference_net_file,
                                candidate_net_file=low_vehicle_variant_file,
                                output_dir=output_dir
                                / f"reference_visual_detail_tls_low_vehicle_control_reference_delta_{low_vehicle_label}",
                                prefix=f"{prefix}_reference_visual_detail_tls_low_vehicle_control_reference_delta_{low_vehicle_label}",
                                candidate_cluster_radius_m=topology_cluster_radius_m,
                                candidate_min_cluster_nodes=topology_min_cluster_nodes,
                                structural_only=True,
                            )
                            low_vehicle_promotion_report = _reference_delta_promotion_decision(
                                candidate_delta_report=low_vehicle_delta_report,
                                baseline_delta_report=low_vehicle_baseline_delta_report,
                                reason="tls_low_vehicle_control_promoted_by_reference_delta",
                            )
                            low_vehicle_score = _tls_semantic_delta_score(low_vehicle_delta_report)
                            low_vehicle_candidate_record.update(
                                {
                                    "reference_tls_semantic_delta_score": low_vehicle_score,
                                    "reference_delta_file": low_vehicle_delta_report.get("summary_file", ""),
                                    "reference_promotion_status": low_vehicle_promotion_report.get("status", ""),
                                }
                            )
                            if low_vehicle_promotion_report.get("status") == "pass" and (
                                selected_low_vehicle_candidate is None
                                or low_vehicle_score < selected_low_vehicle_candidate[0]
                            ):
                                selected_low_vehicle_candidate = (
                                    low_vehicle_score,
                                    low_vehicle_report,
                                    low_vehicle_sumo_load_report,
                                    low_vehicle_delta_report,
                                    low_vehicle_promotion_report,
                                    low_vehicle_variant_file,
                                )
                        else:
                            low_vehicle_candidate_record["reference_promotion_status"] = "blocked"
                    reference_visual_detail_tls_low_vehicle_control_candidates.append(low_vehicle_candidate_record)
                if selected_low_vehicle_candidate is not None:
                    (
                        _low_vehicle_score,
                        reference_visual_detail_tls_low_vehicle_control_report,
                        reference_visual_detail_tls_low_vehicle_control_sumo_load_report,
                        reference_visual_detail_tls_low_vehicle_control_reference_delta_report,
                        reference_visual_detail_tls_low_vehicle_control_reference_promotion_report,
                        low_vehicle_variant_file,
                    ) = selected_low_vehicle_candidate
                    reference_visual_detail_comparison_net_file = low_vehicle_variant_file
                    reference_visual_detail_comparison_selection_reason = str(
                        reference_visual_detail_tls_low_vehicle_control_reference_promotion_report.get("reason", "")
                    )
            if candidate_visual_tls_net_file is not None and reference_matched_tls_delta:
                tls_id_map = (
                    {}
                    if reference_visual_detail_tls_aggregation_reference_promotion_report.get("status") == "pass"
                    else _tls_representative_id_map(reference_visual_detail_tls_aggregation_report or {})
                )
                if tls_id_map:
                    reference_visual_detail_tls_connection_repair_report = tls_connection_repair_func(
                        source_net_file=reference_visual_detail_net_file,
                        candidate_net_file=candidate_visual_tls_net_file,
                        output_dir=output_dir / "reference_visual_detail_tls_connection_repair",
                        prefix=f"{prefix}_reference_visual_detail_tls_connection_repair",
                        tls_id_map=tls_id_map,
                        copy_unmapped_tls=False,
                        require_target_link_index_capacity=True,
                    )
                    repair_variant_value = reference_visual_detail_tls_connection_repair_report.get(
                        "variant_file", ""
                    )
                    repair_variant_file = Path(str(repair_variant_value)) if repair_variant_value else None
                    if repair_variant_file is not None and repair_variant_file.exists():
                        reference_visual_detail_tls_connection_repair_sumo_load_report = _sumo_load_net(
                            repair_variant_file,
                            output_dir=output_dir / "reference_visual_detail_tls_connection_repair",
                            sumo_binary=sumo_binary,
                            timeout_seconds=timeout_seconds,
                            command_runner=command_runner,
                        )
                        reference_visual_detail_tls_connection_repair_reference_delta_report = (
                            reference_join_audit_func(
                                reference_net_file=reference_net_file,
                                candidate_net_file=repair_variant_file,
                                output_dir=output_dir
                                / "reference_visual_detail_tls_connection_repair_reference_delta",
                                prefix=f"{prefix}_reference_visual_detail_tls_connection_repair_reference_delta",
                                candidate_cluster_radius_m=topology_cluster_radius_m,
                                candidate_min_cluster_nodes=topology_min_cluster_nodes,
                                structural_only=True,
                            )
                        )
                    reference_visual_detail_tls_connection_repair_promotion_report = (
                        _tls_connection_repair_promotion_decision(
                            repair_report=reference_visual_detail_tls_connection_repair_report,
                            sumo_load_report=reference_visual_detail_tls_connection_repair_sumo_load_report,
                            repair_delta_report=reference_visual_detail_tls_connection_repair_reference_delta_report,
                            rejected_delta_report=reference_visual_detail_tls_aggregation_reference_delta_report,
                        )
                    )
                    if (
                        reference_visual_detail_tls_connection_repair_promotion_report.get("status") == "pass"
                        and repair_variant_file is not None
                    ):
                        reference_visual_detail_comparison_net_file = repair_variant_file
                        reference_visual_detail_comparison_selection_reason = str(
                            reference_visual_detail_tls_connection_repair_promotion_report.get("reason", "")
                        )
    raw_connectivity_report = connectivity_func(net_file)
    connectivity_report = raw_connectivity_report
    connectivity_quality = _connectivity_quality(connectivity_report)
    connected_core_report = None
    connected_core_connectivity_report = None
    if connectivity_quality["strict_connectivity_status"] != "pass":
        connected_core_report = connected_core_func(
            net_file,
            output_dir=output_dir / "connected_core",
            prefix=prefix,
            timeout_seconds=timeout_seconds,
        )
        core_file_value = connected_core_report.get("connected_core_file", "") if connected_core_report else ""
        if connected_core_report.get("status") == "pass" and core_file_value:
            candidate_core_file = Path(str(core_file_value))
            connected_core_connectivity_report = connectivity_func(candidate_core_file)
            connected_core_quality = _connectivity_quality(connected_core_connectivity_report)
            if connected_core_quality["strict_connectivity_status"] == "pass":
                net_file = candidate_core_file
                connectivity_report = connected_core_connectivity_report
                connectivity_quality = dict(connected_core_quality)
                connectivity_quality["network_quality"] = "connected-core"
    topology_audit_report = None
    if run_topology_audit_after_build:
        topology_audit_report = topology_audit_func(
            net_file=net_file,
            output_dir=output_dir / "topology_audit",
            prefix=f"{prefix}_topology_audit",
            cluster_radius_m=topology_cluster_radius_m,
            min_cluster_nodes=topology_min_cluster_nodes,
            osm_file=osm_file,
        )
    if (
        topology_audit_report is not None
        and run_junction_aggregation_after_build
        and str(network_plan.get("network_profile", "")) != "reference_matched"
        and _junction_aggregation_summary(topology_audit_report)["junction_aggregation_candidate_count"] > 0
    ):
        junction_aggregation_report = junction_aggregation_func(
            net_file=net_file,
            output_dir=output_dir / "junction_aggregation",
            prefix=f"{prefix}_junction_aggregation",
            topology_audit_report=topology_audit_report,
            reference_join_audit_report=None,
            join_dist_m=topology_cluster_radius_m,
            timeout_seconds=timeout_seconds,
        )
    if (
        str(network_plan.get("network_profile", "")) == "reference_matched"
        and reference_net_file is not None
        and run_reference_hierarchy_audit_after_build
    ):
        reference_hierarchy_audit_candidate_net_file = reference_visual_detail_comparison_net_file or reference_visual_detail_net_file or net_file
        reference_hierarchy_audit_candidate_layer = (
            "reference_visual_detail"
            if reference_visual_detail_comparison_net_file is not None or reference_visual_detail_net_file is not None
            else "vehicle_core"
        )
        reference_hierarchy_audit_report = reference_hierarchy_audit_func(
            reference_net_file=reference_net_file,
            candidate_net_file=reference_hierarchy_audit_candidate_net_file,
            output_dir=output_dir / "reference_hierarchy_audit",
            prefix=f"{prefix}_reference_hierarchy_audit",
        )
    if (
        str(network_plan.get("network_profile", "")) == "reference_matched"
        and reference_net_file is not None
        and run_reference_scope_audit_after_build
    ):
        reference_scope_candidate_net_file = reference_visual_detail_comparison_net_file or reference_visual_detail_net_file or net_file
        reference_scope_candidate_layer = (
            "reference_visual_detail"
            if reference_visual_detail_comparison_net_file is not None or reference_visual_detail_net_file is not None
            else "vehicle_core"
        )
        reference_scope_audit_report = reference_scope_audit_func(
            reference_net_file=reference_net_file,
            candidate_net_file=reference_scope_candidate_net_file,
            output_dir=output_dir / "reference_scope_audit",
            prefix=f"{prefix}_reference_scope_audit",
        )
        if run_scope_pruning_after_build and _int_field(reference_scope_audit_report, "prune_candidate_count") > 0:
            reference_scope_pruning_report = scope_pruning_func(
                net_file=reference_scope_candidate_net_file,
                reference_scope_report=reference_scope_audit_report,
                output_dir=output_dir / "reference_scope_pruning",
                prefix=f"{prefix}_reference_scope_pruning",
                timeout_seconds=timeout_seconds,
            )
    if (
        str(network_plan.get("network_profile", "")) == "reference_matched"
        and reference_net_file is not None
        and run_reference_join_audit_after_build
    ):
        reference_join_audit_candidate_net_file = reference_visual_detail_comparison_net_file or reference_visual_detail_net_file or net_file
        reference_join_audit_candidate_layer = (
            "reference_visual_detail" if reference_visual_detail_comparison_net_file is not None or reference_visual_detail_net_file is not None else "vehicle_core"
        )
        reference_join_audit_report = reference_join_audit_func(
            reference_net_file=reference_net_file,
            candidate_net_file=reference_join_audit_candidate_net_file,
            output_dir=output_dir / "reference_join_audit",
            prefix=f"{prefix}_reference_join_audit",
            candidate_cluster_radius_m=topology_cluster_radius_m,
            candidate_min_cluster_nodes=topology_min_cluster_nodes,
            structural_only=reference_join_audit_structural_only,
        )
        reference_join_audit_is_structural_only = reference_join_audit_report.get("audit_mode") == "structural_only"
        if run_reference_join_aggregation_after_build and not reference_join_audit_is_structural_only:
            reference_join_aggregation_report = reference_join_aggregation_func(
                net_file=reference_join_audit_candidate_net_file,
                output_dir=output_dir / "reference_join_aggregation",
                prefix=f"{prefix}_reference_join_aggregation",
                topology_audit_report=topology_audit_report,
                reference_join_audit_report=reference_join_audit_report,
                join_dist_m=topology_cluster_radius_m,
                timeout_seconds=timeout_seconds,
            )
            joined_value = reference_join_aggregation_report.get("junction_aggregation_variant_file", "")
            if reference_join_aggregation_report.get("status") == "pass" and joined_value:
                candidate_joined_net_file = Path(str(joined_value))
                if candidate_joined_net_file.exists():
                    reference_visual_detail_comparison_net_file = candidate_joined_net_file
        if not reference_join_audit_is_structural_only:
            teacher_guided_repair_queue_report = teacher_guided_repair_queue_func(
                teacher_net_file=reference_net_file,
                candidate_net_file=reference_visual_detail_comparison_net_file or reference_join_audit_candidate_net_file,
                reference_join_audit_report=reference_join_audit_report,
                output_dir=output_dir / "teacher_guided_repair_queue",
                prefix=f"{prefix}_teacher_guided_repair",
                max_ready_candidates=teacher_guided_repair_max_ready_candidates,
            )
            if (
                _int_field(teacher_guided_repair_queue_report, "ready_candidate_count") > 0
                or _int_field(teacher_guided_repair_queue_report, "expanded_scope_candidate_count") > 0
            ):
                teacher_guided_plain_export_report = teacher_guided_plain_export_func(
                    net_file=reference_visual_detail_comparison_net_file or reference_join_audit_candidate_net_file,
                    output_dir=output_dir / "teacher_guided_repair_plain",
                    prefix=f"{prefix}_teacher_guided_repair",
                    netconvert_binary=netconvert_binary,
                    timeout_seconds=timeout_seconds,
                )
                if teacher_guided_plain_export_report.get("status") == "pass":
                    raw_type_value = str(teacher_guided_plain_export_report.get("raw_type_file", ""))
                    queue_file_value = str(teacher_guided_repair_queue_report.get("queue_file", ""))
                    teacher_guided_repair_run_report = teacher_guided_repair_run_func(
                        queue_report=teacher_guided_repair_queue_report,
                        raw_node_file=Path(str(teacher_guided_plain_export_report["raw_node_file"])),
                        raw_edge_file=Path(str(teacher_guided_plain_export_report["raw_edge_file"])),
                        raw_connection_file=Path(str(teacher_guided_plain_export_report["raw_connection_file"])),
                        raw_type_file=Path(raw_type_value) if raw_type_value else None,
                        output_dir=output_dir / "teacher_guided_repair_execution",
                        prefix=f"{prefix}_teacher_guided_repair",
                        queue_base_dir=Path(queue_file_value).resolve().parent if queue_file_value else None,
                        replay_target_internal_subgraph=True,
                        max_ready_candidates=teacher_guided_repair_max_ready_candidates,
                        netconvert_binary=netconvert_binary,
                        sumo_binary=sumo_binary,
                        timeout_seconds=timeout_seconds,
                        sequential_accept_passed_variants=True,
                        plain_exporter=teacher_guided_plain_export_func,
                    )
                    teacher_guided_repair_best_variant_file = _teacher_guided_best_variant_file(
                        teacher_guided_repair_run_report
                    )
                    expanded_scope_value = str(teacher_guided_repair_run_report.get("best_expanded_scope_net_file", ""))
                    if expanded_scope_value:
                        expanded_scope_file = Path(expanded_scope_value)
                        if expanded_scope_file.exists():
                            teacher_guided_repair_best_expanded_scope_net_file = expanded_scope_file
                    if teacher_guided_repair_best_variant_file is not None:
                        reference_visual_detail_comparison_net_file = teacher_guided_repair_best_variant_file
                        reference_join_post_teacher_audit_report = reference_join_audit_func(
                            reference_net_file=reference_net_file,
                            candidate_net_file=teacher_guided_repair_best_variant_file,
                            output_dir=output_dir / "post_teacher_reference_join_audit",
                            prefix=f"{prefix}_post_teacher_reference_join_audit",
                            candidate_cluster_radius_m=topology_cluster_radius_m,
                            candidate_min_cluster_nodes=topology_min_cluster_nodes,
                            structural_only=reference_join_audit_structural_only,
                        )
                        if run_tls_aggregation_after_build:
                            selected_low_vehicle_candidate: tuple[
                                int,
                                dict[str, Any],
                                dict[str, Any],
                                dict[str, Any],
                                dict[str, Any],
                                Path,
                            ] | None = None
                            for low_vehicle_limit in _low_vehicle_control_candidate_limits(
                                reference_join_post_teacher_audit_report
                            ):
                                low_vehicle_label = str(low_vehicle_limit["label"])
                                low_vehicle_output_dir = (
                                    output_dir / f"post_teacher_tls_low_vehicle_control_{low_vehicle_label}"
                                )
                                low_vehicle_report = tls_low_vehicle_control_func(
                                    source_net_file=teacher_guided_repair_best_variant_file,
                                    tls_control_review_queue=reference_join_post_teacher_audit_report.get(
                                        "tls_control_review_queue", []
                                    ),
                                    output_dir=low_vehicle_output_dir,
                                    prefix=f"{prefix}_post_teacher_tls_low_vehicle_control_{low_vehicle_label}",
                                    max_removed_controlled_connections=low_vehicle_limit[
                                        "max_removed_controlled_connections"
                                    ],
                                    max_selected_tllogic_count=low_vehicle_limit["max_selected_tllogic_count"],
                                )
                                low_vehicle_candidate_record = {
                                    "candidate_label": low_vehicle_label,
                                    "status": low_vehicle_report.get("status", "fail"),
                                    "max_removed_controlled_connections": low_vehicle_limit[
                                        "max_removed_controlled_connections"
                                    ],
                                    "max_selected_tllogic_count": low_vehicle_limit["max_selected_tllogic_count"],
                                    "selected_tllogic_count": low_vehicle_report.get(
                                        "tls_low_vehicle_control_selected_tllogic_count", 0
                                    ),
                                    "removed_connection_count": low_vehicle_report.get(
                                        "tls_low_vehicle_control_removed_connection_count", 0
                                    ),
                                }
                                low_vehicle_variant_value = low_vehicle_report.get(
                                    "tls_low_vehicle_control_variant_file", ""
                                )
                                low_vehicle_variant_file = (
                                    Path(str(low_vehicle_variant_value)) if low_vehicle_variant_value else None
                                )
                                if low_vehicle_variant_file is not None and low_vehicle_variant_file.exists():
                                    low_vehicle_sumo_load_report = _sumo_load_net(
                                        low_vehicle_variant_file,
                                        output_dir=low_vehicle_output_dir,
                                        sumo_binary=sumo_binary,
                                        timeout_seconds=timeout_seconds,
                                        command_runner=command_runner,
                                    )
                                    low_vehicle_candidate_record["sumo_load_status"] = (
                                        low_vehicle_sumo_load_report.get("status", "fail")
                                    )
                                    if low_vehicle_sumo_load_report.get("status") == "pass":
                                        low_vehicle_delta_report = reference_join_audit_func(
                                            reference_net_file=reference_net_file,
                                            candidate_net_file=low_vehicle_variant_file,
                                            output_dir=output_dir
                                            / f"post_teacher_tls_low_vehicle_control_reference_delta_{low_vehicle_label}",
                                            prefix=(
                                                f"{prefix}_post_teacher_tls_low_vehicle_control_reference_delta_"
                                                f"{low_vehicle_label}"
                                            ),
                                            candidate_cluster_radius_m=topology_cluster_radius_m,
                                            candidate_min_cluster_nodes=topology_min_cluster_nodes,
                                            structural_only=True,
                                        )
                                        low_vehicle_promotion_report = _reference_delta_promotion_decision(
                                            candidate_delta_report=low_vehicle_delta_report,
                                            baseline_delta_report=reference_join_post_teacher_audit_report,
                                            reason="post_teacher_tls_low_vehicle_promoted_by_reference_delta",
                                        )
                                        low_vehicle_score = _tls_semantic_delta_score(low_vehicle_delta_report)
                                        low_vehicle_candidate_record.update(
                                            {
                                                "reference_tls_semantic_delta_score": low_vehicle_score,
                                                "reference_delta_file": low_vehicle_delta_report.get(
                                                    "summary_file", ""
                                                ),
                                                "reference_promotion_status": low_vehicle_promotion_report.get(
                                                    "status", ""
                                                ),
                                            }
                                        )
                                        if low_vehicle_promotion_report.get("status") == "pass" and (
                                            selected_low_vehicle_candidate is None
                                            or low_vehicle_score < selected_low_vehicle_candidate[0]
                                        ):
                                            selected_low_vehicle_candidate = (
                                                low_vehicle_score,
                                                low_vehicle_report,
                                                low_vehicle_sumo_load_report,
                                                low_vehicle_delta_report,
                                                low_vehicle_promotion_report,
                                                low_vehicle_variant_file,
                                            )
                                    else:
                                        low_vehicle_candidate_record["reference_promotion_status"] = "blocked"
                                post_teacher_tls_low_vehicle_control_candidates.append(low_vehicle_candidate_record)
                            if selected_low_vehicle_candidate is not None:
                                (
                                    _low_vehicle_score,
                                    post_teacher_tls_low_vehicle_control_report,
                                    post_teacher_tls_low_vehicle_control_sumo_load_report,
                                    post_teacher_tls_low_vehicle_control_reference_delta_report,
                                    post_teacher_tls_low_vehicle_control_reference_promotion_report,
                                    low_vehicle_variant_file,
                                ) = selected_low_vehicle_candidate
                                reference_visual_detail_comparison_net_file = low_vehicle_variant_file
                                reference_visual_detail_comparison_selection_reason = str(
                                    post_teacher_tls_low_vehicle_control_reference_promotion_report.get("reason", "")
                                )
                            signal_grouping_baseline_report = (
                                post_teacher_tls_low_vehicle_control_reference_delta_report
                                or reference_join_post_teacher_audit_report
                            )
                            signal_grouping_source_net_file = (
                                reference_visual_detail_comparison_net_file or teacher_guided_repair_best_variant_file
                            )
                            signal_grouping_missing_counts = signal_grouping_baseline_report.get(
                                "network_structural_missing_counts", {}
                            )
                            if not isinstance(signal_grouping_missing_counts, Mapping):
                                signal_grouping_missing_counts = {}
                            missing_shared_groups = int(
                                signal_grouping_missing_counts.get("tls_shared_linkindex_group_count", 0) or 0
                            )
                            if missing_shared_groups > 0 and signal_grouping_source_net_file is not None:
                                signal_grouping_output_dir = output_dir / "post_teacher_tls_signal_grouping"
                                post_teacher_tls_signal_grouping_report = tls_signal_grouping_func(
                                    source_net_file=signal_grouping_source_net_file,
                                    output_dir=signal_grouping_output_dir,
                                    prefix=f"{prefix}_post_teacher_tls_signal_grouping",
                                    max_shared_linkindex_groups=missing_shared_groups,
                                )
                                signal_grouping_variant_value = post_teacher_tls_signal_grouping_report.get(
                                    "tls_signal_grouping_variant_file", ""
                                )
                                signal_grouping_variant_file = (
                                    Path(str(signal_grouping_variant_value)) if signal_grouping_variant_value else None
                                )
                                if signal_grouping_variant_file is not None and signal_grouping_variant_file.exists():
                                    post_teacher_tls_signal_grouping_sumo_load_report = _sumo_load_net(
                                        signal_grouping_variant_file,
                                        output_dir=signal_grouping_output_dir,
                                        sumo_binary=sumo_binary,
                                        timeout_seconds=timeout_seconds,
                                        command_runner=command_runner,
                                    )
                                    if post_teacher_tls_signal_grouping_sumo_load_report.get("status") == "pass":
                                        post_teacher_tls_signal_grouping_reference_delta_report = reference_join_audit_func(
                                            reference_net_file=reference_net_file,
                                            candidate_net_file=signal_grouping_variant_file,
                                            output_dir=output_dir
                                            / "post_teacher_tls_signal_grouping_reference_delta",
                                            prefix=f"{prefix}_post_teacher_tls_signal_grouping_reference_delta",
                                            candidate_cluster_radius_m=topology_cluster_radius_m,
                                            candidate_min_cluster_nodes=topology_min_cluster_nodes,
                                            structural_only=True,
                                        )
                                        post_teacher_tls_signal_grouping_reference_promotion_report = (
                                            _reference_delta_promotion_decision(
                                                candidate_delta_report=post_teacher_tls_signal_grouping_reference_delta_report,
                                                baseline_delta_report=signal_grouping_baseline_report,
                                                reason="post_teacher_tls_signal_grouping_promoted_by_reference_delta",
                                            )
                                        )
                                        if (
                                            post_teacher_tls_signal_grouping_reference_promotion_report.get("status")
                                            == "pass"
                                        ):
                                            reference_visual_detail_comparison_net_file = signal_grouping_variant_file
                                            reference_visual_detail_comparison_selection_reason = str(
                                                post_teacher_tls_signal_grouping_reference_promotion_report.get(
                                                    "reason", ""
                                                )
                                            )
                                    else:
                                        post_teacher_tls_signal_grouping_reference_promotion_report = {
                                            "status": "blocked",
                                            "reason": "sumo_load_not_pass",
                                        }
                            connection_repair_baseline_report = (
                                post_teacher_tls_signal_grouping_reference_delta_report
                                or post_teacher_tls_low_vehicle_control_reference_delta_report
                                or reference_join_post_teacher_audit_report
                            )
                            connection_repair_source_net_file = (
                                reference_visual_detail_comparison_net_file or teacher_guided_repair_best_variant_file
                            )
                            connection_repair_missing_counts = connection_repair_baseline_report.get(
                                "network_structural_missing_counts", {}
                            )
                            if not isinstance(connection_repair_missing_counts, Mapping):
                                connection_repair_missing_counts = {}
                            missing_controlled_connections = int(
                                connection_repair_missing_counts.get("tls_controlled_connection_count", 0) or 0
                            )
                            missing_sparse_tllogics = int(
                                connection_repair_missing_counts.get("tls_sparse_linkindex_tl_logic_count", 0) or 0
                            )
                            if (
                                reference_net_file is not None
                                and connection_repair_source_net_file is not None
                                and (missing_controlled_connections > 0 or missing_sparse_tllogics > 0)
                            ):
                                connection_repair_output_dir = output_dir / "post_teacher_tls_connection_repair"
                                post_teacher_tls_connection_repair_report = tls_connection_repair_func(
                                    source_net_file=reference_net_file,
                                    candidate_net_file=connection_repair_source_net_file,
                                    output_dir=connection_repair_output_dir,
                                    prefix=f"{prefix}_post_teacher_tls_connection_repair",
                                    copy_unmapped_tls=True,
                                    require_target_link_index_capacity=False,
                                )
                                connection_repair_variant_value = post_teacher_tls_connection_repair_report.get(
                                    "variant_file", ""
                                )
                                connection_repair_variant_file = (
                                    Path(str(connection_repair_variant_value))
                                    if connection_repair_variant_value
                                    else None
                                )
                                if (
                                    connection_repair_variant_file is not None
                                    and connection_repair_variant_file.exists()
                                ):
                                    post_teacher_tls_connection_repair_sumo_load_report = _sumo_load_net(
                                        connection_repair_variant_file,
                                        output_dir=connection_repair_output_dir,
                                        sumo_binary=sumo_binary,
                                        timeout_seconds=timeout_seconds,
                                        command_runner=command_runner,
                                    )
                                    if post_teacher_tls_connection_repair_sumo_load_report.get("status") == "pass":
                                        post_teacher_tls_connection_repair_reference_delta_report = (
                                            reference_join_audit_func(
                                                reference_net_file=reference_net_file,
                                                candidate_net_file=connection_repair_variant_file,
                                                output_dir=output_dir
                                                / "post_teacher_tls_connection_repair_reference_delta",
                                                prefix=f"{prefix}_post_teacher_tls_connection_repair_reference_delta",
                                                candidate_cluster_radius_m=topology_cluster_radius_m,
                                                candidate_min_cluster_nodes=topology_min_cluster_nodes,
                                                structural_only=True,
                                            )
                                        )
                                        post_teacher_tls_connection_repair_reference_promotion_report = (
                                            _reference_delta_promotion_decision(
                                                candidate_delta_report=post_teacher_tls_connection_repair_reference_delta_report,
                                                baseline_delta_report=connection_repair_baseline_report,
                                                reason="post_teacher_tls_connection_repair_promoted_by_reference_delta",
                                            )
                                        )
                                        if (
                                            _int_field(
                                                post_teacher_tls_connection_repair_reference_delta_report,
                                                "junction_pattern_mismatch_count",
                                            )
                                            > 0
                                        ):
                                            post_teacher_tls_connection_repair_movement_rebuild_queue_report = (
                                                teacher_guided_repair_queue_func(
                                                    teacher_net_file=reference_net_file,
                                                    candidate_net_file=connection_repair_variant_file,
                                                    reference_join_audit_report=(
                                                        post_teacher_tls_connection_repair_reference_delta_report
                                                    ),
                                                    output_dir=output_dir
                                                    / "post_teacher_tls_connection_repair_movement_rebuild_queue",
                                                    prefix=(
                                                        f"{prefix}_post_teacher_tls_connection_repair_"
                                                        "movement_rebuild"
                                                    ),
                                                    max_ready_candidates=teacher_guided_repair_max_ready_candidates,
                                                )
                                            )
                                        if (
                                            post_teacher_tls_connection_repair_reference_promotion_report.get("status")
                                            == "pass"
                                        ):
                                            reference_visual_detail_comparison_net_file = (
                                                connection_repair_variant_file
                                            )
                                            reference_visual_detail_comparison_selection_reason = str(
                                                post_teacher_tls_connection_repair_reference_promotion_report.get(
                                                    "reason", ""
                                                )
                                            )
                                            if (
                                                post_teacher_tls_connection_repair_movement_rebuild_queue_report
                                                is not None
                                            ):
                                                if (
                                                    _int_field(
                                                        post_teacher_tls_connection_repair_movement_rebuild_queue_report,
                                                        "ready_candidate_count",
                                                    )
                                                    > 0
                                                    or _int_field(
                                                        post_teacher_tls_connection_repair_movement_rebuild_queue_report,
                                                        "expanded_scope_candidate_count",
                                                    )
                                                    > 0
                                                ):
                                                    post_teacher_tls_connection_repair_movement_rebuild_plain_export_report = (
                                                        teacher_guided_plain_export_func(
                                                            net_file=connection_repair_variant_file,
                                                            output_dir=output_dir
                                                            / "post_teacher_tls_connection_repair_movement_rebuild_plain",
                                                            prefix=(
                                                                f"{prefix}_post_teacher_tls_connection_repair_"
                                                                "movement_rebuild"
                                                            ),
                                                            netconvert_binary=netconvert_binary,
                                                            timeout_seconds=timeout_seconds,
                                                        )
                                                    )
                                                    if (
                                                        post_teacher_tls_connection_repair_movement_rebuild_plain_export_report.get(
                                                            "status"
                                                        )
                                                        == "pass"
                                                    ):
                                                        raw_type_value = str(
                                                            post_teacher_tls_connection_repair_movement_rebuild_plain_export_report.get(
                                                                "raw_type_file", ""
                                                            )
                                                        )
                                                        queue_file_value = str(
                                                            post_teacher_tls_connection_repair_movement_rebuild_queue_report.get(
                                                                "queue_file", ""
                                                            )
                                                        )
                                                        post_teacher_tls_connection_repair_movement_rebuild_run_report = (
                                                            teacher_guided_repair_run_func(
                                                                queue_report=post_teacher_tls_connection_repair_movement_rebuild_queue_report,
                                                                raw_node_file=Path(
                                                                    str(
                                                                        post_teacher_tls_connection_repair_movement_rebuild_plain_export_report[
                                                                            "raw_node_file"
                                                                        ]
                                                                    )
                                                                ),
                                                                raw_edge_file=Path(
                                                                    str(
                                                                        post_teacher_tls_connection_repair_movement_rebuild_plain_export_report[
                                                                            "raw_edge_file"
                                                                        ]
                                                                    )
                                                                ),
                                                                raw_connection_file=Path(
                                                                    str(
                                                                        post_teacher_tls_connection_repair_movement_rebuild_plain_export_report[
                                                                            "raw_connection_file"
                                                                        ]
                                                                    )
                                                                ),
                                                                raw_type_file=Path(raw_type_value)
                                                                if raw_type_value
                                                                else None,
                                                                output_dir=output_dir
                                                                / "post_teacher_tls_connection_repair_movement_rebuild_execution",
                                                                prefix=(
                                                                    f"{prefix}_post_teacher_tls_connection_repair_"
                                                                    "movement_rebuild"
                                                                ),
                                                                queue_base_dir=Path(queue_file_value).resolve().parent
                                                                if queue_file_value
                                                                else None,
                                                                replay_target_internal_subgraph=True,
                                                                max_ready_candidates=teacher_guided_repair_max_ready_candidates,
                                                                netconvert_binary=netconvert_binary,
                                                                sumo_binary=sumo_binary,
                                                                timeout_seconds=timeout_seconds,
                                                                sequential_accept_passed_variants=True,
                                                                plain_exporter=teacher_guided_plain_export_func,
                                                            )
                                                        )
                                                        post_teacher_tls_connection_repair_movement_rebuild_best_variant_file = (
                                                            _teacher_guided_best_variant_file(
                                                                post_teacher_tls_connection_repair_movement_rebuild_run_report
                                                            )
                                                        )
                                                        if (
                                                            post_teacher_tls_connection_repair_movement_rebuild_best_variant_file
                                                            is not None
                                                        ):
                                                            reference_visual_detail_comparison_net_file = (
                                                                post_teacher_tls_connection_repair_movement_rebuild_best_variant_file
                                                            )
                                                            reference_visual_detail_comparison_selection_reason = (
                                                                "post_teacher_tls_connection_repair_movement_rebuild_promoted"
                                                            )
                                                            reference_join_post_teacher_audit_report = (
                                                                reference_join_audit_func(
                                                                    reference_net_file=reference_net_file,
                                                                    candidate_net_file=post_teacher_tls_connection_repair_movement_rebuild_best_variant_file,
                                                                    output_dir=output_dir
                                                                    / "post_teacher_tls_connection_repair_movement_rebuild_reference_delta",
                                                                    prefix=(
                                                                        f"{prefix}_post_teacher_tls_connection_repair_"
                                                                        "movement_rebuild_reference_delta"
                                                                    ),
                                                                    candidate_cluster_radius_m=topology_cluster_radius_m,
                                                                    candidate_min_cluster_nodes=topology_min_cluster_nodes,
                                                                    structural_only=True,
                                                                    equivalent_approach_edge_map=_teacher_guided_equivalent_approach_edge_map(
                                                                        post_teacher_tls_connection_repair_movement_rebuild_run_report
                                                                    ),
                                                                )
                                                            )
                                    else:
                                        post_teacher_tls_connection_repair_reference_promotion_report = {
                                            "status": "blocked",
                                            "reason": "sumo_load_not_pass",
                                        }
    routeability_report = None
    if key_edge_queries:
        routeability_report = routeability_func(
            net_file=net_file,
            output_dir=output_dir / "routeability",
            prefix=f"{prefix}_routeability",
            key_edge_queries=key_edge_queries,
        )
    routeability_audit_report = None
    routeability_profile = _routeability_scale_profile(
        connectivity_report,
        requested_vehicle_count=routeability_vehicle_count,
        requested_initial_end=routeability_initial_end,
        requested_max_end=routeability_max_end,
    )
    if run_routeability_audit_after_build:
        routeability_audit_report = routeability_audit_func(
            net_file=net_file,
            output_dir=output_dir / "routeability_audit",
            prefix=f"{prefix}_routeability_audit",
            vehicle_count=routeability_profile["routeability_audit_vehicle_count"],
            initial_end=routeability_profile["routeability_audit_initial_end"],
            max_end=routeability_profile["routeability_audit_max_end"],
            timeout_seconds=timeout_seconds,
        )
    if launch_netedit_after_build:
        netedit_report = netedit_func(net_file)
    else:
        netedit_report = {
            "status": "blocked",
            "claim_status": "diagnostic-demo",
            "netedit_status": "skipped",
            "netedit_network_file": str(net_file),
            "warnings": ["netedit launch disabled by caller"],
        }
    if reference_visual_detail_comparison_net_file is not None:
        if launch_netedit_after_build:
            reference_visual_detail_netedit_report = netedit_func(reference_visual_detail_comparison_net_file)
        else:
            reference_visual_detail_netedit_report = {
                "status": "blocked",
                "claim_status": "diagnostic-demo",
                "netedit_status": "skipped",
                "netedit_network_file": str(reference_visual_detail_comparison_net_file),
                "warnings": ["reference visual-detail netedit launch disabled by caller"],
            }
    if launch_sumo_gui_after_build:
        sumo_gui_report = sumo_gui_func(
            net_file,
            output_dir=output_dir / "sumo_gui",
            prefix=f"{prefix}_sumo_gui",
        )
    else:
        sumo_gui_report = {
            "status": "blocked",
            "claim_status": "diagnostic-demo",
            "sumo_gui_status": "skipped",
            "sumo_gui_binary": None,
            "sumo_gui_process_id": None,
            "sumo_gui_config_file": "",
            "sumo_gui_network_file": str(net_file),
            "warnings": ["sumo-gui launch disabled by caller"],
        }

    tls_summary = _tls_review_summary(tls_report)
    junction_aggregation_summary = _junction_aggregation_summary(topology_audit_report)
    warnings = []
    for child in (
        reference_bbox_report or {},
        build_report,
        service_permission_report,
        reference_visual_detail_build_report,
        reference_visual_detail_service_permission_report,
        tls_report,
        tls_aggregation_report or {},
        reference_visual_detail_tls_report or {},
        reference_visual_detail_tls_aggregation_report or {},
        reference_visual_detail_tls_signal_grouping_report or {},
        reference_visual_detail_tls_low_vehicle_control_report or {},
        post_teacher_tls_low_vehicle_control_report or {},
        post_teacher_tls_signal_grouping_report or {},
        post_teacher_tls_connection_repair_report or {},
        reference_visual_detail_tls_connection_repair_report or {},
        reference_visual_detail_raw_reference_delta_report or {},
        reference_visual_detail_tls_signal_grouping_sumo_load_report or {},
        reference_visual_detail_tls_low_vehicle_control_sumo_load_report or {},
        post_teacher_tls_low_vehicle_control_sumo_load_report or {},
        post_teacher_tls_signal_grouping_sumo_load_report or {},
        post_teacher_tls_connection_repair_sumo_load_report or {},
        reference_visual_detail_tls_connection_repair_sumo_load_report or {},
        reference_visual_detail_tls_low_vehicle_control_reference_delta_report or {},
        post_teacher_tls_low_vehicle_control_reference_delta_report or {},
        post_teacher_tls_signal_grouping_reference_delta_report or {},
        post_teacher_tls_connection_repair_reference_delta_report or {},
        post_teacher_tls_connection_repair_movement_rebuild_queue_report or {},
        post_teacher_tls_connection_repair_movement_rebuild_plain_export_report or {},
        post_teacher_tls_connection_repair_movement_rebuild_run_report or {},
        reference_visual_detail_tls_connection_repair_reference_delta_report or {},
        raw_connectivity_report,
        connected_core_report or {},
        connected_core_connectivity_report or {},
        connectivity_report,
        topology_audit_report or {},
        junction_aggregation_report or {},
        reference_hierarchy_audit_report or {},
        reference_scope_audit_report or {},
        reference_scope_pruning_report or {},
        reference_join_audit_report or {},
        reference_join_aggregation_report or {},
        routeability_audit_report or {},
        netedit_report,
        reference_visual_detail_netedit_report,
        sumo_gui_report,
    ):
        warnings.extend(str(item) for item in child.get("warnings", []))
    if tls_summary["tls_review_complete"] == "no":
        warnings.append("TLS reality review still requires human Google Maps/current-or-user-targeted map inspection")
    if tls_aggregation_report is not None and tls_aggregation_report.get("tls_aggregation_status") == "variant_created_for_review":
        warnings.append(
            "TLS aggregation created a separate review variant; compare physical TLS clusters in Netedit and Google Maps "
            "before adopting it as the clean signal network"
        )
    if (
        reference_visual_detail_tls_aggregation_report is not None
        and reference_visual_detail_tls_aggregation_report.get("tls_aggregation_status") == "variant_created_for_review"
    ):
        warnings.append(
            "reference visual-detail TLS aggregation created a separate comparison variant; use it for TUM/manual-reference "
            "Netedit comparison before adopting signal cleanup"
        )
    if reference_visual_detail_tls_connection_repair_report is not None:
        warnings.append(
            "reference visual-detail TLS connection repair created a diagnostic variant; use SUMO load, reference audit, "
            "and Netedit connection mode before adopting any copied signal semantics"
        )
    if post_teacher_tls_connection_repair_report is not None:
        warnings.append(
            "post-teacher TLS connection repair copied reference signal-control semantics into a diagnostic variant; "
            "use SUMO load, reference audit, and Netedit connection mode before treating it as clean"
        )
    if connectivity_quality["quality_warning"]:
        warnings.append(str(connectivity_quality["quality_warning"]))
    if topology_audit_report is not None and topology_audit_report.get("topology_fragmentation_status") == "needs_review":
        warnings.append("topology fragmentation audit needs human review before treating the network as clean")
    if (
        reference_hierarchy_audit_report is not None
        and _int_field(reference_hierarchy_audit_report, "high_hierarchy_issue_count") > 0
    ):
        warnings.append(
            "reference hierarchy audit found high-road review cases; inspect over-split corridors, out-of-scope roads, "
            "hierarchy mismatches, and link/slip-lane cases before pruning or merging high-level roads"
        )
    if junction_aggregation_summary["junction_aggregation_candidate_count"]:
        warnings.append(
            "junction aggregation audit identified "
            f"{junction_aggregation_summary['junction_aggregation_candidate_count']} possible physical-intersection "
            "aggregation candidate(s); inspect the candidate CSV and map-review links before destructive joining"
        )
    if junction_aggregation_report is not None and junction_aggregation_report.get(
        "junction_aggregation_status"
    ) == "variant_created_for_review":
        warnings.append(
            "junction aggregation created a separate plain-nodes join patch review variant; inspect it in Netedit "
            "and map context before adopting any physical-intersection join"
        )
    if reference_join_aggregation_report is not None and reference_join_aggregation_report.get(
        "junction_aggregation_status"
    ) == "variant_created_for_review":
        warnings.append(
            "reference join aggregation created a separate review variant; compare it in Netedit and Google Maps "
            "before adopting it as the clean network"
        )
    if reference_scope_audit_report is not None and _int_field(reference_scope_audit_report, "prune_candidate_count") > 0:
        warnings.append(
            "reference scope audit found over-included short detail fragments; inspect the candidate CSV and "
            "the map context before adopting any pruning"
        )
    if (
        reference_scope_pruning_report is not None
        and reference_scope_pruning_report.get("scope_pruning_status") == "variant_created_for_review"
    ):
        warnings.append(
            "reference scope pruning created a separate review variant; compare it in Netedit and map imagery "
            "before adopting it as the clean network"
        )
    warnings = list(dict.fromkeys(warnings))

    gate_status = {
        "area_confirmation": "pass",
        "road_level_scope": "pass",
        "network_build": _gate_value(build_report),
        "tls_reality_audit": _tls_gate_value(tls_report, tls_summary),
        "connectivity": str(connectivity_quality["connectivity_gate"]),
        "netedit": _gate_value(netedit_report),
        "sumo_gui": _gate_value(sumo_gui_report),
    }
    if tls_aggregation_report is not None:
        gate_status["tls_aggregation"] = "blocked" if tls_aggregation_report.get("status") == "pass" else _gate_value(tls_aggregation_report)
    if str(network_plan.get("network_profile", "")) == "reference_matched":
        gate_status["reference_visual_detail"] = "pass" if reference_visual_detail_status in {"built", "same_as_vehicle_core"} else "fail"
        gate_status["reference_hierarchy_audit"] = _reference_hierarchy_gate(reference_hierarchy_audit_report)
        gate_status["reference_scope_audit"] = _reference_scope_gate(reference_scope_audit_report)
        gate_status["reference_scope_pruning"] = _reference_scope_pruning_gate(reference_scope_pruning_report)
        gate_status["reference_join_audit"] = _reference_join_gate(reference_join_audit_report)
        gate_status["reference_join_aggregation"] = _reference_join_aggregation_gate(reference_join_aggregation_report)
        gate_status["junction_pattern_index"] = _junction_pattern_index_gate(reference_join_audit_report)
        gate_status["connection_semantics_parity"] = "blocked"
        gate_status["tls_semantics_parity"] = "blocked"
        gate_status["internal_junction_parity"] = "blocked"
        gate_status["netedit_connection_mode_review"] = "blocked"
        gate_status["teacher_guided_junction_parity"] = _teacher_guided_parity_gate(
            teacher_guided_repair_run_report or teacher_guided_plain_export_report or teacher_guided_repair_queue_report
        )
    if topology_audit_report is not None:
        gate_status["topology_audit"] = _gate_value(topology_audit_report)
    if junction_aggregation_report is not None:
        gate_status["junction_aggregation"] = (
            "blocked" if junction_aggregation_report.get("status") == "pass" else _gate_value(junction_aggregation_report)
        )
    if routeability_audit_report is not None:
        gate_status["routeability_audit"] = _gate_value(routeability_audit_report)
    workflow_ok = (
        gate_status["network_build"] == "pass"
        and gate_status["tls_reality_audit"] == "pass"
        and gate_status["connectivity"] in {"pass", "partial"}
        and gate_status.get("topology_audit", "skipped") in {"pass", "skipped"}
        and gate_status.get("routeability_audit", "skipped") in {"pass", "blocked", "skipped"}
        and gate_status.get("reference_visual_detail", "skipped") in {"pass", "skipped"}
        and gate_status.get("reference_hierarchy_audit", "skipped") in {"pass", "skipped"}
        and gate_status.get("reference_scope_audit", "skipped") in {"pass", "skipped"}
        and gate_status.get("reference_scope_pruning", "skipped") in {"pass", "skipped"}
        and gate_status.get("reference_join_audit", "skipped") in {"pass", "skipped"}
        and gate_status.get("reference_join_aggregation", "skipped") in {"pass", "skipped"}
        and gate_status.get("teacher_guided_junction_parity", "skipped") in {"pass", "blocked", "skipped"}
        and gate_status["netedit"] in {"pass", "blocked"}
        and gate_status["sumo_gui"] in {"pass", "blocked"}
    )
    bbox_regional_map_baseline = regional_map_baseline_for_bbox(bbox, label=cleaned_place_name or "SUMO network area")
    tls_regional_map_baseline = dict(tls_summary.get("regional_map_baseline") or {})
    provider_counts = tls_regional_map_baseline.get("regional_map_provider_counts")
    has_tls_regional_rows = not isinstance(provider_counts, dict) or any(int(count) > 0 for count in provider_counts.values())
    regional_map_baseline = tls_regional_map_baseline if tls_regional_map_baseline and has_tls_regional_rows else bbox_regional_map_baseline
    (
        teacher_guided_exemplar_ready_candidate_count,
        teacher_guided_exemplar_movement_signature_count,
    ) = _teacher_guided_exemplar_ready_stats(teacher_guided_repair_queue_report)
    (
        teacher_guided_movement_gap_candidate_count,
        teacher_guided_max_vehicle_movement_matrix_missing_count,
        teacher_guided_missing_movement_plan_count,
        teacher_guided_top_movement_gaps,
    ) = _teacher_guided_movement_gap_stats(teacher_guided_repair_queue_report)
    post_teacher_tls_connection_repair_residual_stats = _junction_pattern_residual_stats(
        post_teacher_tls_connection_repair_reference_delta_report
    )
    (
        post_teacher_tls_connection_repair_movement_gap_candidate_count,
        post_teacher_tls_connection_repair_movement_max_gap_count,
        _post_teacher_tls_connection_repair_missing_movement_plan_count,
        _post_teacher_tls_connection_repair_top_movement_gaps,
    ) = _teacher_guided_movement_gap_stats(post_teacher_tls_connection_repair_movement_rebuild_queue_report)
    report = {
        "status": "pass" if workflow_ok else "fail",
        "claim_status": "diagnostic-demo" if workflow_ok else "construction-invalid",
        "area_input": cleaned_place_name or bbox,
        "area_resolution_status": area_status,
        **(_candidate_fields(place_report) if place_report is not None else {**_candidate_fields(None), "candidate_bbox": bbox}),
        **_reference_bbox_fields(reference_bbox_report),
        "osm_preview_url": str(place_report.get("osm_preview_url", osm_preview_url(cleaned_place_name))) if place_report is not None else (osm_preview_url(cleaned_place_name) if cleaned_place_name else ""),
        "user_confirmed_area": "yes" if area_status == "confirmed_by_user" else "confirmed_by_input",
        "road_level_scope_status": "confirmed",
        "network_plan_status": network_plan.get("network_plan_status", "confirmed"),
        "network_profile": network_plan.get("network_profile", ""),
        "reference_target": network_plan.get("reference_target", ""),
        "reference_net_file": network_plan.get("reference_net_file", ""),
        "network_detail_target": network_plan.get("network_detail_target", ""),
        "primary_network_layer": network_plan.get("primary_network_layer", ""),
        "default_routeability_layer": network_plan.get("default_routeability_layer", ""),
        "default_netedit_comparison_layer": network_plan.get("default_netedit_comparison_layer", ""),
        "comparison_scope_mode": network_plan.get("comparison_scope_mode", ""),
        "auxiliary_modal_layers": network_plan.get("auxiliary_modal_layers", []),
        "auxiliary_modal_highway_classes": network_plan.get("auxiliary_modal_highway_classes", {}),
        "movement_layers": network_plan.get("movement_layers", []),
        "selected_highway_classes": network_plan.get("highway_classes", []),
        "vehicle_core_highway_classes": network_plan.get("vehicle_core_highway_classes", network_plan.get("highway_classes", [])),
        "reference_visual_detail_highway_classes": network_plan.get("reference_visual_detail_highway_classes", []),
        "reference_visual_detail_only_highway_classes": network_plan.get("reference_visual_detail_only_highway_classes", []),
        "reference_source_way_scope": "reference_source_way_ids"
        if reference_source_way_scope is not None
        else "not_applied",
        "reference_source_way_id_count": len(reference_source_way_ids),
        "service_passenger_policy": network_plan.get("service_passenger_policy", "sumo_default"),
        "network_plan": network_plan,
        "reference_policy": network_plan.get("reference_policy", {}),
        **_road_level_scope_fields(),
        "map_baseline_source": regional_map_baseline["regional_map_provider"],
        "regional_map_baseline": regional_map_baseline,
        "map_temporal_scope": map_temporal_scope,
        "map_target_date": map_target_date or "",
        **tls_summary,
        "tls_physical_cluster_count": tls_aggregation_report.get("tls_physical_cluster_count", tls_summary["tls_cluster_count"])
        if tls_aggregation_report is not None
        else tls_summary["tls_cluster_count"],
        "tls_aggregation_status": "skipped"
        if tls_aggregation_report is None
        else tls_aggregation_report.get("tls_aggregation_status", tls_aggregation_report.get("status", "fail")),
        "tls_aggregation_variant_file": ""
        if tls_aggregation_report is None
        else str(tls_aggregation_report.get("tls_aggregation_variant_file", "")),
        "tls_aggregation_plan_file": ""
        if tls_aggregation_report is None
        else str(tls_aggregation_report.get("tls_aggregation_plan_file", "")),
        "tls_aggregation_representatives_file": ""
        if tls_aggregation_report is None
        else str(tls_aggregation_report.get("tls_aggregation_representatives_file", "")),
        "tls_aggregated_traffic_light_junction_count": ""
        if tls_aggregation_report is None
        else tls_aggregation_report.get("tls_aggregated_traffic_light_junction_count", ""),
        "tls_aggregated_tl_logic_count": ""
        if tls_aggregation_report is None
        else tls_aggregation_report.get("tls_aggregated_tl_logic_count", ""),
        "tls_aggregated_controlled_connection_count": ""
        if tls_aggregation_report is None
        else tls_aggregation_report.get("tls_aggregated_controlled_connection_count", ""),
        "tls_aggregated_tl_connection_missing_linkindex_count": ""
        if tls_aggregation_report is None
        else tls_aggregation_report.get("tls_aggregated_tl_connection_missing_linkindex_count", ""),
        "tls_controlled_connection_preservation_status": "skipped"
        if tls_aggregation_report is None
        else str(tls_aggregation_report.get("tls_controlled_connection_preservation_status", "pass")),
        "tls_controlled_connection_regression_count": 0
        if tls_aggregation_report is None
        else tls_aggregation_report.get("tls_controlled_connection_regression_count", 0),
        "connectivity_status": connectivity_report.get("connectivity_status", connectivity_report.get("status", "fail")),
        "raw_connectivity_status": raw_connectivity_report.get("connectivity_status", raw_connectivity_report.get("status", "fail")),
        "strict_connectivity_status": connectivity_quality["strict_connectivity_status"],
        "connectivity_main_component_ratio": connectivity_quality["connectivity_main_component_ratio"],
        "network_quality": connectivity_quality["network_quality"],
        "experiment_readiness": "no",
        "passenger_edge_count": connectivity_report.get("passenger_edge_count", 0),
        "passenger_component_count": connectivity_report.get("passenger_component_count", 0),
        "largest_component_edge_count": connectivity_report.get("largest_component_edge_count", 0),
        "small_component_count": connectivity_report.get("small_component_count", 0),
        "isolated_passenger_edge_count": connectivity_report.get("isolated_passenger_edge_count", 0),
        "raw_passenger_edge_count": raw_connectivity_report.get("passenger_edge_count", 0),
        "raw_passenger_component_count": raw_connectivity_report.get("passenger_component_count", 0),
        "raw_largest_component_edge_count": raw_connectivity_report.get("largest_component_edge_count", 0),
        "raw_isolated_passenger_edge_count": raw_connectivity_report.get("isolated_passenger_edge_count", 0),
        "topology_fragmentation_status": "skipped" if topology_audit_report is None else topology_audit_report.get("topology_fragmentation_status", topology_audit_report.get("status", "fail")),
        "suspicious_topology_cluster_count": 0 if topology_audit_report is None else topology_audit_report.get("suspicious_cluster_count", 0),
        "max_topology_cluster_node_count": 0 if topology_audit_report is None else topology_audit_report.get("max_cluster_node_count", 0),
        "topology_audit_clusters_file": "" if topology_audit_report is None else str(topology_audit_report.get("clusters_file", "")),
        **junction_aggregation_summary,
        "junction_aggregation_variant_status": "skipped"
        if junction_aggregation_report is None
        else junction_aggregation_report.get(
            "junction_aggregation_status", junction_aggregation_report.get("status", "fail")
        ),
        "junction_aggregation_variant_file": ""
        if junction_aggregation_report is None
        else str(junction_aggregation_report.get("junction_aggregation_variant_file", "")),
        "junction_aggregation_plan_file": ""
        if junction_aggregation_report is None
        else str(junction_aggregation_report.get("junction_aggregation_plan_file", "")),
        "junction_aggregation_variant_candidates_file": ""
        if junction_aggregation_report is None
        else str(junction_aggregation_report.get("junction_aggregation_candidates_file", "")),
        "junction_join_nodes_patch_file": ""
        if junction_aggregation_report is None
        else str(junction_aggregation_report.get("junction_join_nodes_patch_file", "")),
        "junction_join_definition_file": ""
        if junction_aggregation_report is None
        else str(junction_aggregation_report.get("junction_join_definition_file", "")),
        "junction_join_definition_csv": ""
        if junction_aggregation_report is None
        else str(junction_aggregation_report.get("junction_join_definition_csv", "")),
        "junction_join_explicit_join_count": 0
        if junction_aggregation_report is None
        else junction_aggregation_report.get("junction_join_explicit_join_count", 0),
        "junction_join_exclude_count": 0
        if junction_aggregation_report is None
        else junction_aggregation_report.get("junction_join_exclude_count", 0),
        "junction_join_needs_map_review_count": 0
        if junction_aggregation_report is None
        else junction_aggregation_report.get("junction_join_needs_map_review_count", 0),
        "reference_join_audit_status": "skipped"
        if reference_join_audit_report is None
        else reference_join_audit_report.get("status", "fail"),
        "reference_join_audit_mode": "skipped"
        if reference_join_audit_report is None
        else str(reference_join_audit_report.get("audit_mode", "full")),
        "reference_join_audit_candidate_layer": reference_join_audit_candidate_layer,
        "reference_join_audit_candidate_net_file": ""
        if reference_join_audit_candidate_net_file is None
        else str(reference_join_audit_candidate_net_file),
        "reference_join_reference_case_count": 0
        if reference_join_audit_report is None
        else reference_join_audit_report.get("reference_case_count", 0),
        "reference_join_matched_case_count": 0
        if reference_join_audit_report is None
        else reference_join_audit_report.get("matched_case_count", 0),
        "reference_join_unmatched_case_count": 0
        if reference_join_audit_report is None
        else reference_join_audit_report.get("unmatched_case_count", 0),
        "reference_join_audit_report_file": ""
        if reference_join_audit_report is None
        else str(reference_join_audit_report.get("summary_file", "")),
        "reference_join_audit_cases_file": ""
        if reference_join_audit_report is None
        else str(reference_join_audit_report.get("cases_file", "")),
        "reference_join_junction_teacher_delta_file": ""
        if reference_join_audit_report is None
        else str(reference_join_audit_report.get("junction_teacher_delta_file", "")),
        "reference_join_junction_pattern_comparisons_file": ""
        if reference_join_audit_report is None
        else str(reference_join_audit_report.get("junction_pattern_comparisons_file", "")),
        "reference_join_junction_pattern_templates_file": ""
        if reference_join_audit_report is None
        else str(reference_join_audit_report.get("junction_pattern_templates_file", "")),
        "reference_join_junction_pattern_comparison_status": "skipped"
        if reference_join_audit_report is None
        else str(reference_join_audit_report.get("junction_pattern_comparison_status", "skipped")),
        "reference_join_junction_pattern_mismatch_count": 0
        if reference_join_audit_report is None
        else _int_field(reference_join_audit_report, "junction_pattern_mismatch_count"),
        "reference_join_junction_pattern_comparison_sample_count": _list_field_count(
            reference_join_audit_report,
            "junction_pattern_comparisons",
        ),
        "reference_join_junction_pattern_mismatch_field_counts": {}
        if reference_join_audit_report is None
        else reference_join_audit_report.get("junction_pattern_mismatch_field_counts", {}),
        "reference_join_structural_signature_status": "skipped"
        if reference_join_audit_report is None
        else str(reference_join_audit_report.get("junction_structural_signature_status", "skipped")),
        "reference_join_structural_signature_missing_counts": {}
        if reference_join_audit_report is None
        else reference_join_audit_report.get("junction_structural_signature_missing_counts", {}),
        "reference_join_reference_structural_signature_summary": {}
        if reference_join_audit_report is None
        else reference_join_audit_report.get("reference_structural_signature_summary", {}),
        "reference_join_candidate_structural_signature_summary": {}
        if reference_join_audit_report is None
        else reference_join_audit_report.get("candidate_structural_signature_summary", {}),
        "reference_join_network_structural_delta_status": "skipped"
        if reference_join_audit_report is None
        else str(reference_join_audit_report.get("network_structural_delta_status", "skipped")),
        "reference_join_network_structural_missing_counts": {}
        if reference_join_audit_report is None
        else reference_join_audit_report.get("network_structural_missing_counts", {}),
        "reference_join_network_structural_extra_counts": {}
        if reference_join_audit_report is None
        else reference_join_audit_report.get("network_structural_extra_counts", {}),
        "reference_join_post_teacher_audit_status": "skipped"
        if reference_join_post_teacher_audit_report is None
        else reference_join_post_teacher_audit_report.get("status", "fail"),
        "reference_join_post_teacher_audit_report_file": ""
        if reference_join_post_teacher_audit_report is None
        else str(reference_join_post_teacher_audit_report.get("summary_file", "")),
        "reference_join_post_teacher_junction_pattern_mismatch_count": 0
        if reference_join_post_teacher_audit_report is None
        else _int_field(reference_join_post_teacher_audit_report, "junction_pattern_mismatch_count"),
        "reference_join_post_teacher_junction_pattern_mismatch_field_counts": {}
        if reference_join_post_teacher_audit_report is None
        else reference_join_post_teacher_audit_report.get("junction_pattern_mismatch_field_counts", {}),
        "reference_join_post_teacher_network_structural_missing_counts": {}
        if reference_join_post_teacher_audit_report is None
        else reference_join_post_teacher_audit_report.get("network_structural_missing_counts", {}),
        "reference_join_post_teacher_network_structural_extra_counts": {}
        if reference_join_post_teacher_audit_report is None
        else reference_join_post_teacher_audit_report.get("network_structural_extra_counts", {}),
        "post_teacher_tls_low_vehicle_control_status": "skipped"
        if post_teacher_tls_low_vehicle_control_report is None
        else str(post_teacher_tls_low_vehicle_control_report.get("status", "fail")),
        "post_teacher_tls_low_vehicle_control_variant_file": ""
        if post_teacher_tls_low_vehicle_control_report is None
        else str(post_teacher_tls_low_vehicle_control_report.get("tls_low_vehicle_control_variant_file", "")),
        "post_teacher_tls_low_vehicle_control_selected_tllogic_count": 0
        if post_teacher_tls_low_vehicle_control_report is None
        else post_teacher_tls_low_vehicle_control_report.get("tls_low_vehicle_control_selected_tllogic_count", 0),
        "post_teacher_tls_low_vehicle_control_removed_connection_count": 0
        if post_teacher_tls_low_vehicle_control_report is None
        else post_teacher_tls_low_vehicle_control_report.get("tls_low_vehicle_control_removed_connection_count", 0),
        "post_teacher_tls_low_vehicle_control_candidate_count": len(post_teacher_tls_low_vehicle_control_candidates),
        "post_teacher_tls_low_vehicle_control_candidates": post_teacher_tls_low_vehicle_control_candidates,
        "post_teacher_tls_low_vehicle_control_sumo_load_status": "skipped"
        if post_teacher_tls_low_vehicle_control_sumo_load_report is None
        else str(post_teacher_tls_low_vehicle_control_sumo_load_report.get("status", "fail")),
        "post_teacher_tls_low_vehicle_control_reference_tls_semantic_delta_score": _tls_semantic_delta_score(
            post_teacher_tls_low_vehicle_control_reference_delta_report
        ),
        "post_teacher_tls_low_vehicle_control_reference_delta_file": ""
        if post_teacher_tls_low_vehicle_control_reference_delta_report is None
        else str(post_teacher_tls_low_vehicle_control_reference_delta_report.get("summary_file", "")),
        "post_teacher_tls_low_vehicle_control_reference_promotion_status": str(
            post_teacher_tls_low_vehicle_control_reference_promotion_report.get("status", "skipped")
        ),
        "post_teacher_tls_low_vehicle_control_reference_promotion_reason": str(
            post_teacher_tls_low_vehicle_control_reference_promotion_report.get("reason", "")
        ),
        "post_teacher_tls_signal_grouping_status": "skipped"
        if post_teacher_tls_signal_grouping_report is None
        else str(post_teacher_tls_signal_grouping_report.get("status", "fail")),
        "post_teacher_tls_signal_grouping_variant_file": ""
        if post_teacher_tls_signal_grouping_report is None
        else str(post_teacher_tls_signal_grouping_report.get("tls_signal_grouping_variant_file", "")),
        "post_teacher_tls_signal_grouping_merged_group_count": 0
        if post_teacher_tls_signal_grouping_report is None
        else post_teacher_tls_signal_grouping_report.get("tls_signal_grouping_merged_group_count", 0),
        "post_teacher_tls_signal_grouping_remapped_connection_count": 0
        if post_teacher_tls_signal_grouping_report is None
        else post_teacher_tls_signal_grouping_report.get("tls_signal_grouping_remapped_connection_count", 0),
        "post_teacher_tls_signal_grouping_sumo_load_status": "skipped"
        if post_teacher_tls_signal_grouping_sumo_load_report is None
        else str(post_teacher_tls_signal_grouping_sumo_load_report.get("status", "fail")),
        "post_teacher_tls_signal_grouping_reference_tls_semantic_delta_score": _tls_semantic_delta_score(
            post_teacher_tls_signal_grouping_reference_delta_report
        ),
        "post_teacher_tls_signal_grouping_reference_delta_file": ""
        if post_teacher_tls_signal_grouping_reference_delta_report is None
        else str(post_teacher_tls_signal_grouping_reference_delta_report.get("summary_file", "")),
        "post_teacher_tls_signal_grouping_reference_promotion_status": str(
            post_teacher_tls_signal_grouping_reference_promotion_report.get("status", "skipped")
        ),
        "post_teacher_tls_signal_grouping_reference_promotion_reason": str(
            post_teacher_tls_signal_grouping_reference_promotion_report.get("reason", "")
        ),
        "post_teacher_tls_connection_repair_status": "skipped"
        if post_teacher_tls_connection_repair_report is None
        else str(post_teacher_tls_connection_repair_report.get("status", "fail")),
        "post_teacher_tls_connection_repair_variant_file": ""
        if post_teacher_tls_connection_repair_report is None
        else str(post_teacher_tls_connection_repair_report.get("variant_file", "")),
        "post_teacher_tls_connection_repair_controlled_connection_count_before": ""
        if post_teacher_tls_connection_repair_report is None
        else post_teacher_tls_connection_repair_report.get(
            "candidate_tls_controlled_connection_count_before", ""
        ),
        "post_teacher_tls_connection_repair_controlled_connection_count_after": ""
        if post_teacher_tls_connection_repair_report is None
        else post_teacher_tls_connection_repair_report.get("candidate_tls_controlled_connection_count_after", ""),
        "post_teacher_tls_connection_repair_updated_connection_count": 0
        if post_teacher_tls_connection_repair_report is None
        else post_teacher_tls_connection_repair_report.get("updated_connection_count", 0),
        "post_teacher_tls_connection_repair_skipped_invalid_mapped_linkindex_count": 0
        if post_teacher_tls_connection_repair_report is None
        else post_teacher_tls_connection_repair_report.get(
            "skipped_invalid_mapped_linkindex_connection_count", 0
        ),
        "post_teacher_tls_connection_repair_sumo_load_status": "skipped"
        if post_teacher_tls_connection_repair_sumo_load_report is None
        else str(post_teacher_tls_connection_repair_sumo_load_report.get("status", "fail")),
        "post_teacher_tls_connection_repair_reference_tls_semantic_delta_score": _tls_semantic_delta_score(
            post_teacher_tls_connection_repair_reference_delta_report
        ),
        "post_teacher_tls_connection_repair_reference_delta_file": ""
        if post_teacher_tls_connection_repair_reference_delta_report is None
        else str(post_teacher_tls_connection_repair_reference_delta_report.get("summary_file", "")),
        "post_teacher_tls_connection_repair_junction_pattern_case_count": post_teacher_tls_connection_repair_residual_stats[
            "case_count"
        ],
        "post_teacher_tls_connection_repair_junction_pattern_mismatch_count": post_teacher_tls_connection_repair_residual_stats[
            "failed_case_count"
        ],
        "post_teacher_tls_connection_repair_junction_pattern_mismatch_field_counts": post_teacher_tls_connection_repair_residual_stats[
            "mismatch_field_counts"
        ],
        "post_teacher_tls_connection_repair_internal_function_count_deficits": post_teacher_tls_connection_repair_residual_stats[
            "internal_function_count_deficits"
        ],
        "post_teacher_tls_connection_repair_top_junction_pattern_mismatches": post_teacher_tls_connection_repair_residual_stats[
            "top_junction_pattern_mismatches"
        ],
        "post_teacher_tls_connection_repair_movement_rebuild_queue_status": "skipped"
        if post_teacher_tls_connection_repair_movement_rebuild_queue_report is None
        else str(post_teacher_tls_connection_repair_movement_rebuild_queue_report.get("status", "fail")),
        "post_teacher_tls_connection_repair_movement_rebuild_candidate_count": 0
        if post_teacher_tls_connection_repair_movement_rebuild_queue_report is None
        else post_teacher_tls_connection_repair_movement_rebuild_queue_report.get("repair_candidate_count", 0),
        "post_teacher_tls_connection_repair_movement_rebuild_ready_candidate_count": 0
        if post_teacher_tls_connection_repair_movement_rebuild_queue_report is None
        else post_teacher_tls_connection_repair_movement_rebuild_queue_report.get("ready_candidate_count", 0),
        "post_teacher_tls_connection_repair_movement_rebuild_expanded_scope_candidate_count": 0
        if post_teacher_tls_connection_repair_movement_rebuild_queue_report is None
        else post_teacher_tls_connection_repair_movement_rebuild_queue_report.get("expanded_scope_candidate_count", 0),
        "post_teacher_tls_connection_repair_movement_rebuild_gap_candidate_count": post_teacher_tls_connection_repair_movement_gap_candidate_count,
        "post_teacher_tls_connection_repair_movement_rebuild_max_gap_count": post_teacher_tls_connection_repair_movement_max_gap_count,
        "post_teacher_tls_connection_repair_movement_rebuild_queue_file": ""
        if post_teacher_tls_connection_repair_movement_rebuild_queue_report is None
        else str(post_teacher_tls_connection_repair_movement_rebuild_queue_report.get("queue_file", "")),
        "post_teacher_tls_connection_repair_movement_rebuild_plain_export_status": "skipped"
        if post_teacher_tls_connection_repair_movement_rebuild_plain_export_report is None
        else str(post_teacher_tls_connection_repair_movement_rebuild_plain_export_report.get("status", "fail")),
        "post_teacher_tls_connection_repair_movement_rebuild_run_status": "skipped"
        if post_teacher_tls_connection_repair_movement_rebuild_run_report is None
        else str(post_teacher_tls_connection_repair_movement_rebuild_run_report.get("status", "fail")),
        "post_teacher_tls_connection_repair_movement_rebuild_parity_gate_status": "skipped"
        if post_teacher_tls_connection_repair_movement_rebuild_run_report is None
        else str(post_teacher_tls_connection_repair_movement_rebuild_run_report.get("parity_gate_status", "fail")),
        "post_teacher_tls_connection_repair_movement_rebuild_best_variant_file": ""
        if post_teacher_tls_connection_repair_movement_rebuild_best_variant_file is None
        else str(post_teacher_tls_connection_repair_movement_rebuild_best_variant_file),
        "post_teacher_tls_connection_repair_movement_rebuild_applied_candidate_count": 0
        if post_teacher_tls_connection_repair_movement_rebuild_run_report is None
        else post_teacher_tls_connection_repair_movement_rebuild_run_report.get("composite_applied_candidate_count", 0),
        "post_teacher_tls_connection_repair_reference_promotion_status": str(
            post_teacher_tls_connection_repair_reference_promotion_report.get("status", "skipped")
        ),
        "post_teacher_tls_connection_repair_reference_promotion_reason": str(
            post_teacher_tls_connection_repair_reference_promotion_report.get("reason", "")
        ),
        "reference_join_tls_semantic_delta_score": _tls_semantic_delta_score(reference_join_audit_report),
        "reference_join_tls_control_review_status": "skipped"
        if reference_join_audit_report is None
        else str(reference_join_audit_report.get("tls_control_review_status", "skipped")),
        "reference_join_tls_control_review_queue_count": 0
        if reference_join_audit_report is None
        else int(reference_join_audit_report.get("tls_control_review_queue_count", 0) or 0),
        "reference_join_tls_control_review_category_counts": _tls_control_review_category_counts(
            reference_join_audit_report
        ),
        "reference_join_network_structural_junction_type_missing_counts": {}
        if reference_join_audit_report is None
        else reference_join_audit_report.get("network_structural_junction_type_missing_counts", {}),
        "reference_join_network_structural_junction_type_extra_counts": {}
        if reference_join_audit_report is None
        else reference_join_audit_report.get("network_structural_junction_type_extra_counts", {}),
        "reference_join_reference_network_structural_summary": {}
        if reference_join_audit_report is None
        else reference_join_audit_report.get("reference_network_structural_summary", {}),
        "reference_join_candidate_network_structural_summary": {}
        if reference_join_audit_report is None
        else reference_join_audit_report.get("candidate_network_structural_summary", {}),
        "reference_join_aggregation_status": "skipped"
        if reference_join_aggregation_report is None
        else reference_join_aggregation_report.get("junction_aggregation_status", reference_join_aggregation_report.get("status", "fail")),
        "reference_join_aggregation_candidate_count": 0
        if reference_join_aggregation_report is None
        else reference_join_aggregation_report.get("junction_aggregation_candidate_count", 0),
        "reference_join_aggregation_plan_file": ""
        if reference_join_aggregation_report is None
        else str(reference_join_aggregation_report.get("junction_aggregation_plan_file", "")),
        "reference_join_aggregation_candidates_file": ""
        if reference_join_aggregation_report is None
        else str(reference_join_aggregation_report.get("junction_aggregation_candidates_file", "")),
        "reference_join_aggregation_variant_file": ""
        if reference_join_aggregation_report is None
        else str(reference_join_aggregation_report.get("junction_aggregation_variant_file", "")),
        "reference_join_aggregation_preservation_status": "skipped"
        if reference_join_aggregation_report is None
        else str(reference_join_aggregation_report.get("junction_aggregation_preservation_status", "not_run")),
        "reference_join_aggregation_preservation_audit_file": ""
        if reference_join_aggregation_report is None
        else str(reference_join_aggregation_report.get("junction_aggregation_preservation_audit_file", "")),
        "reference_join_aggregation_removed_normal_edge_count": 0
        if reference_join_aggregation_report is None
        else reference_join_aggregation_report.get("junction_aggregation_removed_normal_edge_count", 0),
        "reference_join_aggregation_removed_normal_edge_type_counts": {}
        if reference_join_aggregation_report is None
        else reference_join_aggregation_report.get("junction_aggregation_removed_normal_edge_type_counts", {}),
        "reference_join_aggregation_removed_normal_edge_mode_counts": {}
        if reference_join_aggregation_report is None
        else reference_join_aggregation_report.get("junction_aggregation_removed_normal_edge_mode_counts", {}),
        "reference_join_aggregation_lost_shared_connection_count": 0
        if reference_join_aggregation_report is None
        else reference_join_aggregation_report.get("junction_aggregation_lost_shared_connection_count", 0),
        "reference_join_aggregation_new_dangling_shared_normal_edge_count": 0
        if reference_join_aggregation_report is None
        else reference_join_aggregation_report.get("junction_aggregation_new_dangling_shared_normal_edge_count", 0),
        "teacher_guided_repair_queue_status": "skipped"
        if teacher_guided_repair_queue_report is None
        else teacher_guided_repair_queue_report.get("status", "fail"),
        "teacher_guided_repair_candidate_count": 0
        if teacher_guided_repair_queue_report is None
        else teacher_guided_repair_queue_report.get("repair_candidate_count", 0),
        "teacher_guided_repair_ready_candidate_count": 0
        if teacher_guided_repair_queue_report is None
        else teacher_guided_repair_queue_report.get("ready_candidate_count", 0),
        "teacher_guided_repair_expanded_scope_candidate_count": 0
        if teacher_guided_repair_run_report is None
        else teacher_guided_repair_run_report.get("expanded_scope_candidate_count", 0),
        "teacher_guided_repair_expanded_scope_pass_candidate_count": 0
        if teacher_guided_repair_run_report is None
        else teacher_guided_repair_run_report.get("expanded_scope_pass_candidate_count", 0),
        "teacher_guided_repair_exemplar_ready_candidate_count": teacher_guided_exemplar_ready_candidate_count,
        "teacher_guided_repair_exemplar_movement_signature_count": teacher_guided_exemplar_movement_signature_count,
        "teacher_guided_repair_movement_gap_candidate_count": teacher_guided_movement_gap_candidate_count,
        "teacher_guided_repair_max_vehicle_movement_matrix_missing_count": teacher_guided_max_vehicle_movement_matrix_missing_count,
        "teacher_guided_repair_missing_movement_plan_count": teacher_guided_missing_movement_plan_count,
        "teacher_guided_repair_top_movement_gaps": teacher_guided_top_movement_gaps,
        "teacher_guided_repair_queued_case_count": 0
        if teacher_guided_repair_queue_report is None
        else teacher_guided_repair_queue_report.get("queued_case_count", 0),
        "teacher_guided_repair_tls_candidate_count": 0
        if teacher_guided_repair_queue_report is None
        else teacher_guided_repair_queue_report.get("tls_repair_candidate_count", 0),
        "teacher_guided_repair_tls_category_counts": {}
        if teacher_guided_repair_queue_report is None
        else teacher_guided_repair_queue_report.get("tls_repair_category_counts", {}),
        "teacher_guided_repair_queue_truncated": False
        if teacher_guided_repair_queue_report is None
        else bool(teacher_guided_repair_queue_report.get("queue_truncated", False)),
        "teacher_guided_repair_max_ready_candidates": ""
        if teacher_guided_repair_queue_report is None
        else teacher_guided_repair_queue_report.get("max_ready_candidates", ""),
        "teacher_guided_repair_queue_file": ""
        if teacher_guided_repair_queue_report is None
        else str(teacher_guided_repair_queue_report.get("queue_file", "")),
        "teacher_guided_repair_queue_csv_file": ""
        if teacher_guided_repair_queue_report is None
        else str(teacher_guided_repair_queue_report.get("queue_csv_file", "")),
        "teacher_guided_repair_plain_export_status": "skipped"
        if teacher_guided_plain_export_report is None
        else teacher_guided_plain_export_report.get("status", "fail"),
        "teacher_guided_repair_raw_node_file": ""
        if teacher_guided_plain_export_report is None
        else str(teacher_guided_plain_export_report.get("raw_node_file", "")),
        "teacher_guided_repair_raw_edge_file": ""
        if teacher_guided_plain_export_report is None
        else str(teacher_guided_plain_export_report.get("raw_edge_file", "")),
        "teacher_guided_repair_raw_connection_file": ""
        if teacher_guided_plain_export_report is None
        else str(teacher_guided_plain_export_report.get("raw_connection_file", "")),
        "teacher_guided_repair_raw_type_file": ""
        if teacher_guided_plain_export_report is None
        else str(teacher_guided_plain_export_report.get("raw_type_file", "")),
        "teacher_guided_repair_run_status": "skipped"
        if teacher_guided_repair_run_report is None
        else teacher_guided_repair_run_report.get("status", "fail"),
        "teacher_guided_repair_parity_gate_status": "skipped"
        if teacher_guided_repair_run_report is None
        else teacher_guided_repair_run_report.get("parity_gate_status", "fail"),
        "teacher_guided_repair_semantic_failure_counts": {}
        if teacher_guided_repair_run_report is None
        else teacher_guided_repair_run_report.get("semantic_failure_counts", {}),
        "teacher_guided_repair_approach_integrity_status": "skipped"
        if teacher_guided_repair_run_report is None
        else teacher_guided_repair_run_report.get("approach_integrity_status", "blocked"),
        "teacher_guided_repair_approach_integrity_failure_counts": {}
        if teacher_guided_repair_run_report is None
        else teacher_guided_repair_run_report.get("approach_integrity_failure_counts", {}),
        "teacher_guided_repair_template_contexts": []
        if teacher_guided_repair_run_report is None
        else teacher_guided_repair_run_report.get("teacher_pattern_contexts", []),
        "teacher_guided_repair_attempted_candidate_count": 0
        if teacher_guided_repair_run_report is None
        else teacher_guided_repair_run_report.get("attempted_candidate_count", 0),
        "teacher_guided_repair_pass_candidate_count": 0
        if teacher_guided_repair_run_report is None
        else teacher_guided_repair_run_report.get("pass_candidate_count", 0),
        **_teacher_guided_application_stats(
            teacher_guided_repair_run_report, teacher_guided_repair_best_variant_file
        ),
        "teacher_guided_repair_run_report_file": ""
        if teacher_guided_repair_run_report is None
        else str(teacher_guided_repair_run_report.get("run_report_file", "")),
        "teacher_guided_repair_best_variant_file": ""
        if teacher_guided_repair_best_variant_file is None
        else str(teacher_guided_repair_best_variant_file),
        "teacher_guided_repair_best_expanded_scope_net_file": ""
        if teacher_guided_repair_best_expanded_scope_net_file is None
        else str(teacher_guided_repair_best_expanded_scope_net_file),
        "reference_hierarchy_status": "skipped"
        if reference_hierarchy_audit_report is None
        else reference_hierarchy_audit_report.get(
            "reference_hierarchy_status", reference_hierarchy_audit_report.get("status", "fail")
        ),
        "reference_hierarchy_audit_candidate_layer": reference_hierarchy_audit_candidate_layer,
        "reference_hierarchy_audit_candidate_net_file": ""
        if reference_hierarchy_audit_candidate_net_file is None
        else str(reference_hierarchy_audit_candidate_net_file),
        "reference_hierarchy_issue_count": 0
        if reference_hierarchy_audit_report is None
        else reference_hierarchy_audit_report.get("high_hierarchy_issue_count", 0),
        "reference_hierarchy_decision_counts": {}
        if reference_hierarchy_audit_report is None
        else reference_hierarchy_audit_report.get("decision_counts", {}),
        "reference_hierarchy_corridor_match_basis_counts": {}
        if reference_hierarchy_audit_report is None
        else reference_hierarchy_audit_report.get("corridor_match_basis_counts", {}),
        "reference_hierarchy_same_name_match_status_counts": {}
        if reference_hierarchy_audit_report is None
        else reference_hierarchy_audit_report.get("same_name_match_status_counts", {}),
        "reference_hierarchy_cases_file": ""
        if reference_hierarchy_audit_report is None
        else str(reference_hierarchy_audit_report.get("cases_file", "")),
        "reference_hierarchy_type_comparison_file": ""
        if reference_hierarchy_audit_report is None
        else str(reference_hierarchy_audit_report.get("type_comparison_file", "")),
        "reference_hierarchy_audit_report_file": ""
        if reference_hierarchy_audit_report is None
        else str(reference_hierarchy_audit_report.get("summary_file", "")),
        "reference_scope_status": "skipped"
        if reference_scope_audit_report is None
        else reference_scope_audit_report.get("reference_scope_status", reference_scope_audit_report.get("status", "fail")),
        "reference_scope_audit_candidate_layer": reference_scope_candidate_layer,
        "reference_scope_audit_candidate_net_file": ""
        if reference_scope_candidate_net_file is None
        else str(reference_scope_candidate_net_file),
        "reference_scope_prune_candidate_count": 0
        if reference_scope_audit_report is None
        else reference_scope_audit_report.get("prune_candidate_count", 0),
        "reference_scope_audit_report_file": ""
        if reference_scope_audit_report is None
        else str(reference_scope_audit_report.get("report_file", "")),
        "reference_scope_prune_candidates_file": ""
        if reference_scope_audit_report is None
        else str(reference_scope_audit_report.get("prune_candidates_file", "")),
        "reference_scope_pruning_status": "skipped"
        if reference_scope_pruning_report is None
        else reference_scope_pruning_report.get("scope_pruning_status", reference_scope_pruning_report.get("status", "fail")),
        "reference_scope_pruning_removed_edge_count": 0
        if reference_scope_pruning_report is None
        else reference_scope_pruning_report.get("scope_pruning_removed_edge_count", 0),
        "reference_scope_pruning_variant_file": ""
        if reference_scope_pruning_report is None
        else str(reference_scope_pruning_report.get("scope_pruning_variant_file", "")),
        "reference_scope_pruning_plan_file": ""
        if reference_scope_pruning_report is None
        else str(reference_scope_pruning_report.get("scope_pruning_plan_file", "")),
        "routeability_probe_file": "" if routeability_report is None else str(routeability_report.get("sumocfg_file", "")),
        "missing_key_edges": [] if routeability_report is None else routeability_report.get("missing_key_edges", []),
        "routeability_probe_status": "skipped" if routeability_report is None else routeability_report.get("status", "fail"),
        **routeability_profile,
        "routeability_audit_status": "skipped" if routeability_audit_report is None else routeability_audit_report.get("routeability_status", routeability_audit_report.get("status", "fail")),
        "routeability_audit_report_file": "" if routeability_audit_report is None else str(routeability_audit_report.get("report_file", "")),
        "netedit_status": netedit_report.get("netedit_status", "failed"),
        "netedit_binary": netedit_report.get("netedit_binary"),
        "netedit_process_id": netedit_report.get("netedit_process_id"),
        "netedit_window_title": netedit_report.get("netedit_window_title", ""),
        "netedit_network_file": netedit_report.get("netedit_network_file", str(net_file)),
        "reference_visual_detail_status": reference_visual_detail_status,
        "reference_visual_detail_net_file": "" if reference_visual_detail_net_file is None else str(reference_visual_detail_net_file),
        "reference_visual_detail_comparison_net_file": ""
        if reference_visual_detail_comparison_net_file is None
        else str(reference_visual_detail_comparison_net_file),
        "reference_visual_detail_comparison_selection_reason": reference_visual_detail_comparison_selection_reason,
        "reference_visual_detail_tls_candidate_count": ""
        if reference_visual_detail_tls_report is None
        else reference_visual_detail_tls_report.get("tls_candidate_count", ""),
        "reference_visual_detail_tls_cluster_count": ""
        if reference_visual_detail_tls_report is None
        else reference_visual_detail_tls_report.get("tls_cluster_count", ""),
        "reference_visual_detail_tls_aggregation_status": "skipped"
        if reference_visual_detail_tls_aggregation_report is None
        else reference_visual_detail_tls_aggregation_report.get(
            "tls_aggregation_status", reference_visual_detail_tls_aggregation_report.get("status", "fail")
        ),
        "reference_visual_detail_tls_aggregation_variant_file": ""
        if reference_visual_detail_tls_aggregation_report is None
        else str(reference_visual_detail_tls_aggregation_report.get("tls_aggregation_variant_file", "")),
        "reference_visual_detail_tls_aggregation_candidate_count": len(
            reference_visual_detail_tls_aggregation_candidates
        ),
        "reference_visual_detail_tls_aggregation_candidates": reference_visual_detail_tls_aggregation_candidates,
        "reference_visual_detail_tls_aggregated_traffic_light_junction_count": ""
        if reference_visual_detail_tls_aggregation_report is None
        else reference_visual_detail_tls_aggregation_report.get("tls_aggregated_traffic_light_junction_count", ""),
        "reference_visual_detail_tls_aggregated_tl_logic_count": ""
        if reference_visual_detail_tls_aggregation_report is None
        else reference_visual_detail_tls_aggregation_report.get("tls_aggregated_tl_logic_count", ""),
        "reference_visual_detail_tls_aggregated_controlled_connection_count": ""
        if reference_visual_detail_tls_aggregation_report is None
        else reference_visual_detail_tls_aggregation_report.get("tls_aggregated_controlled_connection_count", ""),
        "reference_visual_detail_tls_aggregated_tl_connection_missing_linkindex_count": ""
        if reference_visual_detail_tls_aggregation_report is None
        else reference_visual_detail_tls_aggregation_report.get("tls_aggregated_tl_connection_missing_linkindex_count", ""),
        "reference_visual_detail_tls_controlled_connection_preservation_status": "skipped"
        if reference_visual_detail_tls_aggregation_report is None
        else str(
            reference_visual_detail_tls_aggregation_report.get("tls_controlled_connection_preservation_status", "pass")
        ),
        "reference_visual_detail_tls_controlled_connection_regression_count": 0
        if reference_visual_detail_tls_aggregation_report is None
        else reference_visual_detail_tls_aggregation_report.get("tls_controlled_connection_regression_count", 0),
        "reference_visual_detail_tls_aggregation_reference_delta_status": "skipped"
        if reference_visual_detail_tls_aggregation_reference_delta_report is None
        else reference_visual_detail_tls_aggregation_reference_delta_report.get("network_structural_delta_status", "fail"),
        "reference_visual_detail_tls_aggregation_reference_tls_semantic_delta_score": _tls_semantic_delta_score(
            reference_visual_detail_tls_aggregation_reference_delta_report
        ),
        "reference_visual_detail_tls_aggregation_reference_delta_missing_counts": {}
        if reference_visual_detail_tls_aggregation_reference_delta_report is None
        else reference_visual_detail_tls_aggregation_reference_delta_report.get("network_structural_missing_counts", {}),
        "reference_visual_detail_tls_aggregation_reference_delta_extra_counts": {}
        if reference_visual_detail_tls_aggregation_reference_delta_report is None
        else reference_visual_detail_tls_aggregation_reference_delta_report.get("network_structural_extra_counts", {}),
        "reference_visual_detail_tls_aggregation_reference_delta_file": ""
        if reference_visual_detail_tls_aggregation_reference_delta_report is None
        else str(reference_visual_detail_tls_aggregation_reference_delta_report.get("summary_file", "")),
        "reference_visual_detail_raw_reference_tls_semantic_delta_score": _tls_semantic_delta_score(
            reference_visual_detail_raw_reference_delta_report
        ),
        "reference_visual_detail_raw_reference_delta_file": ""
        if reference_visual_detail_raw_reference_delta_report is None
        else str(reference_visual_detail_raw_reference_delta_report.get("summary_file", "")),
        "reference_visual_detail_tls_aggregation_reference_promotion_status": str(
            reference_visual_detail_tls_aggregation_reference_promotion_report.get("status", "skipped")
        ),
        "reference_visual_detail_tls_aggregation_reference_promotion_reason": str(
            reference_visual_detail_tls_aggregation_reference_promotion_report.get("reason", "")
        ),
        "reference_visual_detail_tls_signal_grouping_status": "skipped"
        if reference_visual_detail_tls_signal_grouping_report is None
        else str(reference_visual_detail_tls_signal_grouping_report.get("tls_signal_grouping_status", "failed")),
        "reference_visual_detail_tls_signal_grouping_reference_tls_semantic_delta_score": _tls_semantic_delta_score(
            reference_visual_detail_tls_signal_grouping_reference_delta_report
        ),
        "reference_visual_detail_tls_signal_grouping_reference_delta_file": ""
        if reference_visual_detail_tls_signal_grouping_reference_delta_report is None
        else str(reference_visual_detail_tls_signal_grouping_reference_delta_report.get("summary_file", "")),
        "reference_visual_detail_tls_signal_grouping_sumo_load_status": "skipped"
        if reference_visual_detail_tls_signal_grouping_sumo_load_report is None
        else str(reference_visual_detail_tls_signal_grouping_sumo_load_report.get("status", "fail")),
        "reference_visual_detail_tls_signal_grouping_reference_promotion_status": str(
            reference_visual_detail_tls_signal_grouping_reference_promotion_report.get("status", "skipped")
        ),
        "reference_visual_detail_tls_signal_grouping_reference_promotion_reason": str(
            reference_visual_detail_tls_signal_grouping_reference_promotion_report.get("reason", "")
        ),
        "reference_visual_detail_tls_low_vehicle_control_status": "skipped"
        if reference_visual_detail_tls_low_vehicle_control_report is None
        else str(
            reference_visual_detail_tls_low_vehicle_control_report.get(
                "tls_low_vehicle_control_status",
                reference_visual_detail_tls_low_vehicle_control_report.get("status", "fail"),
            )
        ),
        "reference_visual_detail_tls_low_vehicle_control_variant_file": ""
        if reference_visual_detail_tls_low_vehicle_control_report is None
        else str(reference_visual_detail_tls_low_vehicle_control_report.get("tls_low_vehicle_control_variant_file", "")),
        "reference_visual_detail_tls_low_vehicle_control_selected_tllogic_count": 0
        if reference_visual_detail_tls_low_vehicle_control_report is None
        else reference_visual_detail_tls_low_vehicle_control_report.get(
            "tls_low_vehicle_control_selected_tllogic_count", 0
        ),
        "reference_visual_detail_tls_low_vehicle_control_removed_connection_count": 0
        if reference_visual_detail_tls_low_vehicle_control_report is None
        else reference_visual_detail_tls_low_vehicle_control_report.get(
            "tls_low_vehicle_control_removed_connection_count", 0
        ),
        "reference_visual_detail_tls_low_vehicle_control_candidate_count": len(
            reference_visual_detail_tls_low_vehicle_control_candidates
        ),
        "reference_visual_detail_tls_low_vehicle_control_candidates": reference_visual_detail_tls_low_vehicle_control_candidates,
        "reference_visual_detail_tls_low_vehicle_control_sumo_load_status": "skipped"
        if reference_visual_detail_tls_low_vehicle_control_sumo_load_report is None
        else str(reference_visual_detail_tls_low_vehicle_control_sumo_load_report.get("status", "fail")),
        "reference_visual_detail_tls_low_vehicle_control_reference_tls_semantic_delta_score": _tls_semantic_delta_score(
            reference_visual_detail_tls_low_vehicle_control_reference_delta_report
        ),
        "reference_visual_detail_tls_low_vehicle_control_reference_delta_file": ""
        if reference_visual_detail_tls_low_vehicle_control_reference_delta_report is None
        else str(reference_visual_detail_tls_low_vehicle_control_reference_delta_report.get("summary_file", "")),
        "reference_visual_detail_tls_low_vehicle_control_reference_promotion_status": str(
            reference_visual_detail_tls_low_vehicle_control_reference_promotion_report.get("status", "skipped")
        ),
        "reference_visual_detail_tls_low_vehicle_control_reference_promotion_reason": str(
            reference_visual_detail_tls_low_vehicle_control_reference_promotion_report.get("reason", "")
        ),
        "reference_visual_detail_tls_connection_repair_status": "skipped"
        if reference_visual_detail_tls_connection_repair_report is None
        else str(reference_visual_detail_tls_connection_repair_report.get("status", "fail")),
        "reference_visual_detail_tls_connection_repair_variant_file": ""
        if reference_visual_detail_tls_connection_repair_report is None
        else str(reference_visual_detail_tls_connection_repair_report.get("variant_file", "")),
        "reference_visual_detail_tls_connection_repair_controlled_connection_count_before": ""
        if reference_visual_detail_tls_connection_repair_report is None
        else reference_visual_detail_tls_connection_repair_report.get(
            "candidate_tls_controlled_connection_count_before", ""
        ),
        "reference_visual_detail_tls_connection_repair_controlled_connection_count_after": ""
        if reference_visual_detail_tls_connection_repair_report is None
        else reference_visual_detail_tls_connection_repair_report.get(
            "candidate_tls_controlled_connection_count_after", ""
        ),
        "reference_visual_detail_tls_connection_repair_updated_connection_count": 0
        if reference_visual_detail_tls_connection_repair_report is None
        else reference_visual_detail_tls_connection_repair_report.get("updated_connection_count", 0),
        "reference_visual_detail_tls_connection_repair_skipped_invalid_mapped_linkindex_count": 0
        if reference_visual_detail_tls_connection_repair_report is None
        else reference_visual_detail_tls_connection_repair_report.get(
            "skipped_invalid_mapped_linkindex_connection_count", 0
        ),
        "reference_visual_detail_tls_connection_repair_promotion_status": str(
            reference_visual_detail_tls_connection_repair_promotion_report.get("status", "skipped")
        ),
        "reference_visual_detail_tls_connection_repair_promotion_reason": str(
            reference_visual_detail_tls_connection_repair_promotion_report.get("reason", "")
        ),
        "reference_visual_detail_tls_connection_repair_sumo_load_status": "skipped"
        if reference_visual_detail_tls_connection_repair_sumo_load_report is None
        else str(reference_visual_detail_tls_connection_repair_sumo_load_report.get("status", "fail")),
        "reference_visual_detail_tls_connection_repair_reference_delta_status": "skipped"
        if reference_visual_detail_tls_connection_repair_reference_delta_report is None
        else reference_visual_detail_tls_connection_repair_reference_delta_report.get(
            "network_structural_delta_status", "fail"
        ),
        "reference_visual_detail_tls_connection_repair_reference_tls_semantic_delta_score": _tls_semantic_delta_score(
            reference_visual_detail_tls_connection_repair_reference_delta_report
        ),
        "reference_visual_detail_tls_connection_repair_reference_delta_missing_counts": {}
        if reference_visual_detail_tls_connection_repair_reference_delta_report is None
        else reference_visual_detail_tls_connection_repair_reference_delta_report.get(
            "network_structural_missing_counts", {}
        ),
        "reference_visual_detail_tls_connection_repair_reference_delta_extra_counts": {}
        if reference_visual_detail_tls_connection_repair_reference_delta_report is None
        else reference_visual_detail_tls_connection_repair_reference_delta_report.get(
            "network_structural_extra_counts", {}
        ),
        "reference_visual_detail_tls_connection_repair_reference_delta_file": ""
        if reference_visual_detail_tls_connection_repair_reference_delta_report is None
        else str(reference_visual_detail_tls_connection_repair_reference_delta_report.get("summary_file", "")),
        "reference_visual_detail_tls_connection_repair_summary_file": ""
        if reference_visual_detail_tls_connection_repair_report is None
        else str(reference_visual_detail_tls_connection_repair_report.get("summary_file", "")),
        "reference_visual_detail_netedit_status": reference_visual_detail_netedit_report.get("netedit_status", "not_started"),
        "reference_visual_detail_netedit_network_file": reference_visual_detail_netedit_report.get("netedit_network_file", ""),
        "sumo_gui_status": sumo_gui_report.get("sumo_gui_status", "failed"),
        "sumo_gui_binary": sumo_gui_report.get("sumo_gui_binary"),
        "sumo_gui_process_id": sumo_gui_report.get("sumo_gui_process_id"),
        "sumo_gui_config_file": sumo_gui_report.get("sumo_gui_config_file", ""),
        "sumo_gui_network_file": sumo_gui_report.get("sumo_gui_network_file", str(net_file)),
        "net_file": str(net_file),
        "raw_net_file": str(raw_net_file),
        "connected_core_file": "" if connected_core_report is None else str(connected_core_report.get("connected_core_file", "")),
        "filtered_osm_file": str(filtered_osm_value) if filtered_osm_value else "",
        "build": build_report,
        "reference_visual_detail_build": reference_visual_detail_build_report,
        "service_passenger_permissions": service_permission_report,
        "reference_visual_detail_service_passenger_permissions": reference_visual_detail_service_permission_report,
        "tls_audit": tls_report,
        "tls_aggregation": tls_aggregation_report or {},
        "reference_visual_detail_tls_audit": reference_visual_detail_tls_report or {},
        "reference_visual_detail_tls_aggregation": reference_visual_detail_tls_aggregation_report or {},
        "reference_visual_detail_tls_connection_repair": reference_visual_detail_tls_connection_repair_report or {},
        "reference_visual_detail_tls_signal_grouping": reference_visual_detail_tls_signal_grouping_report or {},
        "reference_visual_detail_raw_reference_delta": reference_visual_detail_raw_reference_delta_report or {},
        "reference_visual_detail_tls_aggregation_reference_delta": reference_visual_detail_tls_aggregation_reference_delta_report
        or {},
        "reference_visual_detail_tls_aggregation_reference_promotion": reference_visual_detail_tls_aggregation_reference_promotion_report,
        "reference_visual_detail_tls_signal_grouping_reference_delta": reference_visual_detail_tls_signal_grouping_reference_delta_report
        or {},
        "reference_visual_detail_tls_signal_grouping_sumo_load": reference_visual_detail_tls_signal_grouping_sumo_load_report
        or {},
        "reference_visual_detail_tls_signal_grouping_reference_promotion": reference_visual_detail_tls_signal_grouping_reference_promotion_report,
        "reference_visual_detail_tls_low_vehicle_control": reference_visual_detail_tls_low_vehicle_control_report
        or {},
        "reference_visual_detail_tls_low_vehicle_control_sumo_load": reference_visual_detail_tls_low_vehicle_control_sumo_load_report
        or {},
        "reference_visual_detail_tls_low_vehicle_control_reference_delta": reference_visual_detail_tls_low_vehicle_control_reference_delta_report
        or {},
        "reference_visual_detail_tls_low_vehicle_control_reference_promotion": reference_visual_detail_tls_low_vehicle_control_reference_promotion_report,
        "post_teacher_tls_low_vehicle_control": post_teacher_tls_low_vehicle_control_report or {},
        "post_teacher_tls_low_vehicle_control_sumo_load": post_teacher_tls_low_vehicle_control_sumo_load_report or {},
        "post_teacher_tls_low_vehicle_control_reference_delta": post_teacher_tls_low_vehicle_control_reference_delta_report
        or {},
        "post_teacher_tls_low_vehicle_control_reference_promotion": post_teacher_tls_low_vehicle_control_reference_promotion_report,
        "post_teacher_tls_signal_grouping": post_teacher_tls_signal_grouping_report or {},
        "post_teacher_tls_signal_grouping_sumo_load": post_teacher_tls_signal_grouping_sumo_load_report or {},
        "post_teacher_tls_signal_grouping_reference_delta": post_teacher_tls_signal_grouping_reference_delta_report
        or {},
        "post_teacher_tls_signal_grouping_reference_promotion": post_teacher_tls_signal_grouping_reference_promotion_report,
        "post_teacher_tls_connection_repair": post_teacher_tls_connection_repair_report or {},
        "post_teacher_tls_connection_repair_sumo_load": post_teacher_tls_connection_repair_sumo_load_report or {},
        "post_teacher_tls_connection_repair_reference_delta": post_teacher_tls_connection_repair_reference_delta_report
        or {},
        "post_teacher_tls_connection_repair_reference_promotion": post_teacher_tls_connection_repair_reference_promotion_report,
        "post_teacher_tls_connection_repair_movement_rebuild_queue": (
            post_teacher_tls_connection_repair_movement_rebuild_queue_report or {}
        ),
        "post_teacher_tls_connection_repair_movement_rebuild_plain_export": (
            post_teacher_tls_connection_repair_movement_rebuild_plain_export_report or {}
        ),
        "post_teacher_tls_connection_repair_movement_rebuild_run": (
            post_teacher_tls_connection_repair_movement_rebuild_run_report or {}
        ),
        "reference_visual_detail_tls_connection_repair_sumo_load": reference_visual_detail_tls_connection_repair_sumo_load_report
        or {},
        "reference_visual_detail_tls_connection_repair_reference_delta": reference_visual_detail_tls_connection_repair_reference_delta_report
        or {},
        "reference_visual_detail_tls_connection_repair_promotion": reference_visual_detail_tls_connection_repair_promotion_report,
        "raw_connectivity": raw_connectivity_report,
        "connected_core": connected_core_report or {},
        "connected_core_connectivity": connected_core_connectivity_report or {},
        "connectivity": connectivity_report,
        "topology_audit": topology_audit_report or {},
        "junction_aggregation": junction_aggregation_report or {},
        "reference_hierarchy_audit": reference_hierarchy_audit_report or {},
        "reference_scope_audit": reference_scope_audit_report or {},
        "reference_scope_pruning": reference_scope_pruning_report or {},
        "reference_join_audit": reference_join_audit_report or {},
        "reference_join_post_teacher_audit": reference_join_post_teacher_audit_report or {},
        "reference_join_aggregation": reference_join_aggregation_report or {},
        "teacher_guided_repair_queue": teacher_guided_repair_queue_report or {},
        "teacher_guided_repair_plain_export": teacher_guided_plain_export_report or {},
        "teacher_guided_repair_run": teacher_guided_repair_run_report or {},
        "routeability_audit": routeability_audit_report or {},
        "netedit": netedit_report,
        "reference_visual_detail_netedit": reference_visual_detail_netedit_report,
        "sumo_gui": sumo_gui_report,
        "gate_status": gate_status,
        "warnings": warnings,
    }
    workflow_review_html_report = review_html_func(
        output_dir=output_dir / "review",
        prefix=f"{prefix}_workflow_review",
        title="SUMO Network Review",
        claim_status=str(report["claim_status"]),
        summary=report,
        net_file=reference_visual_detail_comparison_net_file or report.get("net_file"),
        raw_net_file=report.get("raw_net_file"),
        connected_core_file=report.get("connected_core_file"),
        reference_net_file=report.get("reference_net_file"),
        tls_review_file=report.get("tls_review_file"),
        topology_audit_report=topology_audit_report,
        topology_audit_report_file=report.get("topology_audit_clusters_file"),
        junction_aggregation_report=junction_aggregation_report,
        junction_aggregation_report_file=report.get("junction_aggregation_plan_file"),
        routeability_audit_report=routeability_audit_report,
        routeability_audit_report_file=report.get("routeability_audit_report_file"),
        gate_status=gate_status,
        warnings=warnings,
    )
    netedit_review_sumocfg = workflow_review_html_report.get("netedit_review_sumocfg_file", "")
    should_launch_netedit_review = (
        launch_netedit_after_build
        if launch_netedit_review_after_build is None
        else launch_netedit_review_after_build
    )
    review_launcher = netedit_review_func
    if review_launcher is None and netedit_func is launch_netedit:
        review_launcher = netedit_func
    elif review_launcher is None:
        should_launch_netedit_review = False
    if should_launch_netedit_review and netedit_review_sumocfg:
        netedit_review_launch_report = review_launcher(Path(str(netedit_review_sumocfg)))
    elif not netedit_review_sumocfg:
        netedit_review_launch_report = {
            "status": "blocked",
            "claim_status": "diagnostic-demo",
            "netedit_status": "skipped",
            "netedit_input_file": "",
            "netedit_open_mode": "sumocfg",
            "warnings": ["netedit review config was not generated"],
        }
    else:
        netedit_review_launch_report = {
            "status": "blocked",
            "claim_status": "diagnostic-demo",
            "netedit_status": "skipped",
            "netedit_input_file": str(netedit_review_sumocfg),
            "netedit_open_mode": "sumocfg",
            "warnings": ["netedit review launch disabled by caller"],
        }
    report.update(
        {
            "workflow_review_html_status": workflow_review_html_report.get("workflow_review_html_status", "fail"),
            "workflow_review_html_file": workflow_review_html_report.get("workflow_review_html_file", ""),
            "workflow_review_net_file": workflow_review_html_report.get("workflow_review_net_file", ""),
            "workflow_report_file": workflow_review_html_report.get("workflow_report_file", ""),
            "review_manifest_file": workflow_review_html_report.get("review_manifest_file", ""),
            "network_overview_png": workflow_review_html_report.get("network_overview_png", ""),
            "problem_overlay_png": workflow_review_html_report.get("problem_overlay_png", ""),
            "reference_comparison_png": workflow_review_html_report.get("reference_comparison_png", ""),
            "cluster_zoom_pngs": workflow_review_html_report.get("cluster_zoom_pngs", []),
            "netedit_review_additional_file": workflow_review_html_report.get("netedit_review_additional_file", ""),
            "netedit_review_sumocfg_file": workflow_review_html_report.get("netedit_review_sumocfg_file", ""),
            "netedit_review_command": workflow_review_html_report.get("netedit_review_command", ""),
            "netedit_review_selection_files": workflow_review_html_report.get("netedit_review_selection_files", []),
            "netedit_review_launch_status": netedit_review_launch_report.get("netedit_status", "not_started"),
            "netedit_review_launch_process_id": netedit_review_launch_report.get("netedit_process_id"),
            "netedit_review_launch_file": netedit_review_launch_report.get("netedit_input_file", ""),
            "netedit_review_launch": netedit_review_launch_report,
            "human_review_required_count": workflow_review_html_report.get("human_review_required_count", 0),
            "workflow_review_html": workflow_review_html_report,
        }
    )
    return report

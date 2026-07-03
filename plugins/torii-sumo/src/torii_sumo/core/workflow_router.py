from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from .network_plan import derive_network_plan
from .osm_area import osm_map_url_bbox, resolve_osm_place
from .osm_network import audit_tls_multisource
from .osm_workflow import run_osm_cleanup_workflow
from ..intersection.clean import clean_intersection
from .workflow_review_html import build_workflow_review_html
from .workflow_state import NetworkQualityVector, StageResult, build_promotion_trace, summarize_workflow_stages


AUTONOMY_MODES = {"ask-first", "safe-autopilot", "inspect-only", "full-local-run"}


WORKFLOW_RECIPES: dict[str, dict[str, Any]] = {
    "osm_to_sumo": {
        "description": "Resolve or infer a place/bbox, build an OSM-derived SUMO network with conservative defaults, audit TLS, check connectivity, and collect launch evidence.",
        "tool_chain": [
            "sumo_osm_resolve_place",
            "sumo_osm_cleanup_workflow",
            "sumo_tls_multisource_review",
            "sumo_network_topology_audit",
            "sumo_network_routeability_probe",
            "sumo_network_routeability_audit",
            "sumo_collect_evidence",
        ],
    },
    "tls_review": {
        "description": "Create a region-aware TLS review table with supporting OSM, street-level imagery, inventory, signal-plan, and field-evidence columns.",
        "tool_chain": ["sumo_tls_audit", "sumo_tls_multisource_review", "sumo_collect_evidence"],
    },
    "network_review": {
        "description": "Create an HTML human-review cockpit for a generated or partial SUMO network and available audit artifacts.",
        "tool_chain": ["sumo_network_review_html", "sumo_collect_evidence"],
    },
    "intersection_clean": {
        "description": "Compile a local OSM T3/X4 intersection patch into IntersectionIR, SUMO plain files, .net.xml when available, and validation artifacts.",
        "tool_chain": ["sumo_intersection_clean", "sumo_intersection_validate"],
    },
    "routeability": {
        "description": "Snap named route endpoints to passenger-accessible SUMO edges, generate routes, run a bounded smoke check, and report completion before claims.",
        "tool_chain": ["sumo_network_routeability_probe", "sumo_network_routeability_audit", "sumo_compare_outputs"],
    },
    "debug_bad_run": {
        "description": "Treat bad metrics as model feedback, inspect outputs, classify the likely issue, and propose the smallest next probe.",
        "tool_chain": ["sumo_compare_outputs", "sumo_config_pair_preflight", "sumo_collect_evidence"],
    },
    "experiment_audit": {
        "description": "Audit paired controller comparisons before reporting results.",
        "tool_chain": ["sumo_config_pair_preflight", "sumo_compare_outputs", "sumo_collect_evidence"],
    },
    "general": {
        "description": "Build a project-control screen and ask for the minimum missing SUMO artifact before execution.",
        "tool_chain": ["sumo_preflight", "sumo_collect_evidence"],
    },
}


REFERENCE_MATCHED_TOOL_CHAIN = [
    "sumo_network_reference_hierarchy_audit",
    "sumo_network_reference_scope_audit",
    "sumo_network_tls_aggregation_variant",
    "sumo_network_reference_join_audit",
    "sumo_network_junction_aggregation_variant",
    "sumo_network_teacher_guided_repair_queue",
    "sumo_network_teacher_guided_junction_variant",
    "sumo_network_tls_warning_parity",
    "sumo_network_review_html",
]

REFERENCE_MATCHED_SEMANTICS_WORKFLOW = {
    "claim_status": "diagnostic-demo",
    "reference_policy": "learn road layers and service/passenger permissions from a manual reference net",
    "junction_policy": "learn reusable junction patterns from the reference net before proposing aggregation",
    "connection_policy": "audit connection, TLS, crossing, walkingarea, and internal-junction parity before adoption",
    "batch_repair_tool": "sumo_network_teacher_guided_repair_queue",
    "per_junction_repair_tool": "sumo_network_teacher_guided_junction_variant",
    "warning_parity_tool": "sumo_network_tls_warning_parity",
    "required_manual_reviews": ["netedit_connection_mode_review", "map_or_field_imagery"],
}

MANUAL_REVIEW_GATES = {
    "junction_aggregation",
    "netedit_connection_mode_review",
    "reference_join_aggregation",
    "tls_aggregation",
    "topology_audit",
}

OSM_WORKFLOW_SUMMARY_KEYS = (
    "workflow_review_html_status",
    "workflow_review_html_file",
    "workflow_report_file",
    "review_manifest_file",
    "reference_join_audit_mode",
    "teacher_guided_repair_queue_status",
    "teacher_guided_repair_max_ready_candidates",
    "run_teacher_guided_repair_after_build",
    "teacher_guided_repair_run_status",
    "teacher_guided_repair_parity_gate_status",
    "teacher_guided_repair_promotion_gate_status",
    "teacher_guided_repair_promotion_gate_file",
    "teacher_guided_repair_application_scope",
    "teacher_guided_repair_best_variant_file",
    "teacher_guided_repair_run_report_file",
    "teacher_guided_repair_applied_candidate_count",
    "teacher_guided_repair_unapplied_pass_candidate_count",
    "teacher_guided_repair_semantic_layer_gate_counts",
    "teacher_guided_probe_matrix_status",
    "teacher_guided_probe_matrix_file",
    "teacher_guided_probe_matrix_probe_count",
    "teacher_guided_probe_matrix_all_parity_gate_pass",
    "teacher_guided_probe_matrix_all_promotion_gate_pass",
    "teacher_guided_probe_matrix_all_road_continuity_gate_pass",
    "teacher_guided_probe_matrix_missing_junction_ids",
    "road_connectivity_replay_status",
    "road_connectivity_replay_gate_status",
    "road_connectivity_replay_sumo_load_status",
    "road_connectivity_replay_best_variant_file",
    "road_connectivity_promoted_variant_file",
    "road_connectivity_promoted_variant_reason",
    "road_connectivity_replay_run_report_file",
    "road_connectivity_replay_gate_counts",
    "road_connectivity_seed_probe_status",
    "road_connectivity_seed_probe_file",
    "road_connectivity_seed_probe_edge_delta_count",
    "road_connectivity_seed_probe_connection_delta_count",
    "road_connectivity_seed_probe_candidate_missing_seed_edge_ids",
    "road_connectivity_split_root_alias_repair_status",
    "road_connectivity_split_root_alias_repair_file",
    "road_connectivity_split_root_alias_repair_report_file",
    "road_connection_topology_replay_status",
    "road_connection_topology_replay_file",
    "road_connection_topology_replay_report_file",
    "post_teacher_tls_connection_repair_movement_rebuild_run_status",
    "post_teacher_tls_connection_repair_movement_rebuild_parity_gate_status",
    "post_teacher_tls_connection_repair_movement_rebuild_best_variant_file",
    "post_teacher_tls_connection_repair_movement_rebuild_applied_candidate_count",
    "post_teacher_tls_connection_repair_movement_rebuild_semantic_layer_gate_counts",
    "final_movement_rebuild_run_status",
    "final_movement_rebuild_parity_gate_status",
    "final_movement_rebuild_sumo_load_status",
    "final_movement_rebuild_best_variant_file",
    "final_movement_rebuild_applied_candidate_count",
    "final_movement_rebuild_semantic_layer_gate_counts",
    "reference_join_post_teacher_audit_status",
    "routeability_audit_status",
)


def _normalized(value: str) -> str:
    return " ".join(value.lower().split())


def _looks_like_osm_generation(text: str) -> bool:
    generation_terms = (
        "build",
        "download",
        "generate",
        "netconvert",
        "open it in sumo",
        "from osm",
    )
    network_terms = ("osm", "map", "network", "sumo network", "net.xml")
    return any(token in text for token in generation_terms) and any(token in text for token in network_terms)


def _looks_like_intersection_clean(text: str) -> bool:
    intersection_terms = ("intersection", "junction", "crossroad", "t3", "x4")
    patch_terms = ("patch", "local osm", "osm file", "osm extract")
    build_terms = ("clean", "compile", "generate", "build")
    return (
        any(token in text for token in intersection_terms)
        and any(token in text for token in patch_terms)
        and any(token in text for token in build_terms)
    )


def detect_workflow(user_request: str) -> str:
    text = _normalized(user_request)
    if any(token in text for token in ("waiting time", "got worse", "teleport", "tripinfo", "summary disagree", "debug")):
        return "debug_bad_run"
    if _looks_like_intersection_clean(text):
        return "intersection_clean"
    if _looks_like_osm_generation(text):
        return "osm_to_sumo"
    if any(token in text for token in ("compare", "baseline", "fixed-time", "fixed time", "max-pressure", "controller")):
        return "experiment_audit"
    if (
        any(token in text for token in ("html", "review cockpit", "human review", "review"))
        and any(token in text for token in ("sumo network", "partial sumo network", "network", ".net.xml", "net.xml"))
    ):
        return "network_review"
    if any(token in text for token in ("traffic light", "traffic lights", "tls", "signal")):
        return "tls_review"
    if any(token in text for token in ("osm", "map", "network", "netconvert", "open it in sumo", "build a sumo")):
        return "osm_to_sumo"
    if any(token in text for token in ("route", "from ", " to ", "connected", "routeability", "reachable")):
        return "routeability"
    return "general"


def infer_place_name(user_request: str) -> str:
    text = " ".join(user_request.strip().split())
    patterns = [
        r"download\s+the\s+(?P<area>.+?)\s+map\s+in\s+(?P<city>.+?)\s+from\s+OSM",
        r"build\s+(?:a\s+)?SUMO\s+network\s+for\s+(?P<area>.+?)\s+from\s+OSM",
        r"download\s+(?P<area>.+?)\s+from\s+OSM",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        area = match.groupdict().get("area", "").strip(" .,")
        city = match.groupdict().get("city", "").strip(" .,")
        if area and city:
            return f"{area}, {city}"
        if area:
            return area
    return ""


def _base_report(
    *,
    user_request: str,
    detected_workflow: str,
    autonomy_mode: str,
) -> dict[str, Any]:
    recipe = WORKFLOW_RECIPES[detected_workflow]
    return {
        "detected_workflow": detected_workflow,
        "workflow_description": recipe["description"],
        "autonomy_mode": autonomy_mode,
        "user_request": user_request,
        "tool_chain": list(recipe["tool_chain"]),
    }


def _annotate_reference_matched_semantics(report: dict[str, Any], workflow_report: Mapping[str, Any] | None = None) -> None:
    for tool_name in REFERENCE_MATCHED_TOOL_CHAIN:
        if tool_name not in report["tool_chain"]:
            report["tool_chain"].append(tool_name)
    semantics = {
        **REFERENCE_MATCHED_SEMANTICS_WORKFLOW,
        "tool_chain": list(REFERENCE_MATCHED_TOOL_CHAIN),
    }
    configured_max_ready_candidates = report.get("teacher_guided_repair_configured_max_ready_candidates", "")
    if configured_max_ready_candidates != "":
        semantics["configured_max_ready_candidates"] = configured_max_ready_candidates
    if workflow_report is not None:
        semantics["required_manual_reviews"] = _required_manual_reviews_from_gates(workflow_report.get("gate_status"))
        post_repair_movement_best_variant_file = str(
            workflow_report.get("post_teacher_tls_connection_repair_movement_rebuild_best_variant_file", "")
        )
        final_movement_best_variant_file = str(workflow_report.get("final_movement_rebuild_best_variant_file", ""))
        movement_best_variant_file = final_movement_best_variant_file or post_repair_movement_best_variant_file
        road_topology_best_variant_file = (
            str(workflow_report.get("road_connection_topology_replay_file", ""))
            if workflow_report.get("road_connection_topology_replay_status") == "pass"
            else ""
        )
        road_alias_best_variant_file = (
            str(workflow_report.get("road_connectivity_split_root_alias_repair_file", ""))
            if workflow_report.get("road_connectivity_split_root_alias_repair_status") == "pass"
            else ""
        )
        road_replay_best_variant_file = str(workflow_report.get("road_connectivity_replay_best_variant_file", ""))
        road_connectivity_best_variant_file = (
            road_topology_best_variant_file or road_alias_best_variant_file or road_replay_best_variant_file
        )
        semantic_layer_gate_counts = (
            workflow_report.get("final_movement_rebuild_semantic_layer_gate_counts")
            or workflow_report.get("post_teacher_tls_connection_repair_movement_rebuild_semantic_layer_gate_counts")
            or workflow_report.get("teacher_guided_repair_semantic_layer_gate_counts")
            or {}
        )
        semantics.update(
            {
                "best_variant_file": movement_best_variant_file
                or str(workflow_report.get("teacher_guided_repair_best_variant_file", "")),
                "comparison_net_file": movement_best_variant_file
                or str(workflow_report.get("reference_visual_detail_comparison_net_file", "")),
                "run_report_file": str(workflow_report.get("teacher_guided_repair_run_report_file", "")),
                "promotion_gate_status": str(workflow_report.get("teacher_guided_repair_promotion_gate_status", "")),
                "promotion_gate_file": str(workflow_report.get("teacher_guided_repair_promotion_gate_file", "")),
                "application_scope": str(workflow_report.get("teacher_guided_repair_application_scope", "")),
                "applied_candidate_count": workflow_report.get("teacher_guided_repair_applied_candidate_count", 0),
                "unapplied_pass_candidate_count": workflow_report.get(
                    "teacher_guided_repair_unapplied_pass_candidate_count", 0
                ),
                "movement_rebuild_best_variant_file": movement_best_variant_file,
                "movement_rebuild_run_status": str(
                    workflow_report.get("final_movement_rebuild_run_status")
                    or workflow_report.get("post_teacher_tls_connection_repair_movement_rebuild_run_status", "")
                ),
                "movement_rebuild_parity_gate_status": str(
                    workflow_report.get("final_movement_rebuild_parity_gate_status")
                    or workflow_report.get("post_teacher_tls_connection_repair_movement_rebuild_parity_gate_status", "")
                ),
                "movement_rebuild_applied_candidate_count": workflow_report.get(
                    "final_movement_rebuild_applied_candidate_count"
                )
                or workflow_report.get(
                    "post_teacher_tls_connection_repair_movement_rebuild_applied_candidate_count",
                    0,
                ),
                "semantic_layer_gate_counts": semantic_layer_gate_counts,
            }
        )
        if "road_connectivity_replay_status" in workflow_report:
            semantics["road_connectivity_layer"] = {
                "run_status": str(workflow_report.get("road_connectivity_replay_status", "")),
                "gate_status": str(workflow_report.get("road_connectivity_replay_gate_status", "")),
                "sumo_load_status": str(workflow_report.get("road_connectivity_replay_sumo_load_status", "")),
                "best_variant_file": road_connectivity_best_variant_file,
                "owner_replay_variant_file": road_replay_best_variant_file,
                "split_root_alias_repair_file": road_alias_best_variant_file,
                "topology_replay_file": road_topology_best_variant_file,
                "run_report_file": str(workflow_report.get("road_connectivity_replay_run_report_file", "")),
                "gate_counts": workflow_report.get("road_connectivity_replay_gate_counts", {}),
            }
        if "road_connectivity_seed_probe_status" in workflow_report:
            semantics["road_connectivity_seed_probe"] = {
                "status": str(workflow_report.get("road_connectivity_seed_probe_status", "")),
                "report_file": str(workflow_report.get("road_connectivity_seed_probe_file", "")),
                "edge_delta_count": workflow_report.get("road_connectivity_seed_probe_edge_delta_count", 0),
                "connection_delta_count": workflow_report.get(
                    "road_connectivity_seed_probe_connection_delta_count", 0
                ),
                "candidate_missing_seed_edge_ids": workflow_report.get(
                    "road_connectivity_seed_probe_candidate_missing_seed_edge_ids", []
                ),
            }
        if "road_connectivity_split_root_alias_repair_status" in workflow_report:
            semantics["road_connectivity_split_root_alias_repair"] = {
                "status": str(workflow_report.get("road_connectivity_split_root_alias_repair_status", "")),
                "output_file": str(workflow_report.get("road_connectivity_split_root_alias_repair_file", "")),
                "report_file": str(
                    workflow_report.get("road_connectivity_split_root_alias_repair_report_file", "")
                ),
            }
        if "road_connection_topology_replay_status" in workflow_report:
            semantics["road_connection_topology_replay"] = {
                "status": str(workflow_report.get("road_connection_topology_replay_status", "")),
                "output_file": str(workflow_report.get("road_connection_topology_replay_file", "")),
                "report_file": str(workflow_report.get("road_connection_topology_replay_report_file", "")),
            }
        if "teacher_guided_probe_matrix_status" in workflow_report:
            semantics["probe_matrix"] = {
                "status": str(workflow_report.get("teacher_guided_probe_matrix_status", "")),
                "matrix_file": str(workflow_report.get("teacher_guided_probe_matrix_file", "")),
                "probe_count": workflow_report.get("teacher_guided_probe_matrix_probe_count", 0),
                "all_parity_gate_pass": bool(
                    workflow_report.get("teacher_guided_probe_matrix_all_parity_gate_pass", False)
                ),
                "all_promotion_gate_pass": bool(
                    workflow_report.get("teacher_guided_probe_matrix_all_promotion_gate_pass", False)
                ),
                "all_road_continuity_gate_pass": bool(
                    workflow_report.get("teacher_guided_probe_matrix_all_road_continuity_gate_pass", False)
                ),
                "missing_junction_ids": workflow_report.get("teacher_guided_probe_matrix_missing_junction_ids", []),
            }
    report["reference_matched_semantics_workflow"] = semantics


def _required_manual_reviews_from_gates(gate_status: Any) -> list[str]:
    if not isinstance(gate_status, Mapping):
        return list(REFERENCE_MATCHED_SEMANTICS_WORKFLOW["required_manual_reviews"])
    blocked = [
        str(gate)
        for gate, status in sorted(gate_status.items())
        if gate in MANUAL_REVIEW_GATES and str(status) == "blocked"
    ]
    return blocked or list(REFERENCE_MATCHED_SEMANTICS_WORKFLOW["required_manual_reviews"])


def _invalid_mode(user_request: str, autonomy_mode: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "claim_status": "construction-invalid",
        "detected_workflow": detect_workflow(user_request),
        "execution_status": "invalid_autonomy_mode",
        "error": f"autonomy_mode must be one of: {', '.join(sorted(AUTONOMY_MODES))}",
    }


def _plan_only(user_request: str, workflow: str, autonomy_mode: str) -> dict[str, Any]:
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "execution_status": "plan-only",
        **_base_report(user_request=user_request, detected_workflow=workflow, autonomy_mode=autonomy_mode),
    }


def _blocked(report: dict[str, Any], *, execution_status: str, missing: list[str], next_question: str) -> dict[str, Any]:
    report.update(
        {
            "status": "blocked",
            "claim_status": "blocked",
            "execution_status": execution_status,
            "missing_blockers": missing,
            "next_question": next_question,
        }
    )
    return report


def run_auto_workflow(
    *,
    user_request: str,
    output_dir: Path,
    work_dir: Path | None = None,
    autonomy_mode: str = "safe-autopilot",
    place_name: str | None = None,
    bbox: str | None = None,
    confirmed_area: bool = False,
    highway_classes: str | None = None,
    traffic_layers: str | None = None,
    network_profile: str | None = None,
    reference_net_file: Path | None = None,
    reference_policy_report: str | Path | dict[str, Any] | None = None,
    service_passenger_policy: str | None = None,
    teacher_guided_repair_max_ready_candidates: int | None = 80,
    run_teacher_guided_repair_after_build: bool = True,
    road_connectivity_replay_max_owners: int | None = 4,
    road_connectivity_probe_edge_ids: list[str] | None = None,
    teacher_guided_probe_matrix_junction_ids: list[str] | None = None,
    launch_netedit_after_build: bool | None = None,
    launch_sumo_gui_after_build: bool | None = None,
    net_file: Path | None = None,
    osm_file: Path | None = None,
    official_inventory_csv: Path | None = None,
    signal_plan_csv: Path | None = None,
    field_evidence_csv: Path | None = None,
    place_resolver: Callable[[str], dict[str, Any]] = resolve_osm_place,
    cleanup_workflow_func: Callable[..., dict[str, Any]] = run_osm_cleanup_workflow,
    intersection_clean_func: Callable[..., dict[str, Any]] = clean_intersection,
    tls_review_func: Callable[..., dict[str, Any]] = audit_tls_multisource,
    review_html_func: Callable[..., dict[str, Any]] = build_workflow_review_html,
) -> dict[str, Any]:
    if autonomy_mode not in AUTONOMY_MODES:
        return _invalid_mode(user_request, autonomy_mode)

    workflow = detect_workflow(user_request)
    if autonomy_mode == "inspect-only":
        return _plan_only(user_request, workflow, autonomy_mode)

    report = _base_report(user_request=user_request, detected_workflow=workflow, autonomy_mode=autonomy_mode)
    report["output_dir"] = str(output_dir)
    if work_dir is not None:
        report["work_dir"] = str(work_dir)

    if workflow == "osm_to_sumo":
        return _run_osm_to_sumo(
            report=report,
            user_request=user_request,
            output_dir=output_dir,
            place_name=place_name,
            bbox=bbox,
            confirmed_area=confirmed_area,
            highway_classes=highway_classes,
            traffic_layers=traffic_layers,
            network_profile=network_profile,
            reference_net_file=reference_net_file,
            reference_policy_report=reference_policy_report,
            service_passenger_policy=service_passenger_policy,
            teacher_guided_repair_max_ready_candidates=teacher_guided_repair_max_ready_candidates,
            run_teacher_guided_repair_after_build=run_teacher_guided_repair_after_build,
            road_connectivity_replay_max_owners=road_connectivity_replay_max_owners,
            road_connectivity_probe_edge_ids=road_connectivity_probe_edge_ids,
            teacher_guided_probe_matrix_junction_ids=teacher_guided_probe_matrix_junction_ids,
            launch_netedit_after_build=launch_netedit_after_build,
            launch_sumo_gui_after_build=launch_sumo_gui_after_build,
            source_osm_path=osm_file,
            autonomy_mode=autonomy_mode,
            place_resolver=place_resolver,
            cleanup_workflow_func=cleanup_workflow_func,
        )
    if workflow == "intersection_clean":
        return _run_intersection_clean(
            report=report,
            output_dir=output_dir,
            osm_file=osm_file,
            intersection_clean_func=intersection_clean_func,
        )
    if workflow == "tls_review":
        return _run_tls_review(
            report=report,
            output_dir=output_dir,
            net_file=net_file,
            osm_file=osm_file,
            official_inventory_csv=official_inventory_csv,
            signal_plan_csv=signal_plan_csv,
            field_evidence_csv=field_evidence_csv,
            tls_review_func=tls_review_func,
        )
    if workflow == "network_review":
        return _run_network_review(
            report=report,
            output_dir=output_dir,
            net_file=net_file,
            review_html_func=review_html_func,
        )
    if workflow == "routeability":
        return _blocked(
            report,
            execution_status="needs_route_endpoints",
            missing=["net_file", "route_endpoint_spec"],
            next_question="Which origin and destination should Torii snap to passenger-accessible SUMO edges?",
        )
    if workflow == "debug_bad_run":
        return _blocked(
            report,
            execution_status="needs_outputs",
            missing=["summary_or_tripinfo_or_log"],
            next_question="Which SUMO summary, tripinfo, log, or config should Torii inspect first?",
        )
    if workflow == "experiment_audit":
        return _blocked(
            report,
            execution_status="needs_experiment_pair",
            missing=["baseline_config_or_outputs", "variant_config_or_outputs"],
            next_question="Which baseline and variant configs or outputs should Torii audit as a paired comparison?",
        )
    return _blocked(
        report,
        execution_status="needs_sumo_artifact",
        missing=["sumo_config_or_network_or_outputs"],
        next_question="Which SUMO config, network, route, output, or log should Torii inspect?",
    )


def _run_intersection_clean(
    *,
    report: dict[str, Any],
    output_dir: Path,
    osm_file: Path | None,
    intersection_clean_func: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if osm_file is None:
        return _blocked(
            report,
            execution_status="needs_osm_intersection_patch",
            missing=["osm_file"],
            next_question="Which local OSM intersection patch should Torii compile?",
        )
    result = intersection_clean_func(osm_file=osm_file, output_dir=output_dir, compile_net=True)
    report.update(
        {
            "status": result.get("status", "fail"),
            "claim_status": result.get("claim_status", "diagnostic-demo"),
            "execution_status": "executed",
            "tool_called": "sumo_intersection_clean",
            "workflow_result": result,
        }
    )
    for key in (
        "intersection_id",
        "topology_type",
        "approach_count",
        "movement_count",
        "sumo_load_status",
        "route_probe_status",
        "tls_linkindex_status",
        "missing_movement_count",
        "disconnected_edge_count",
        "internal_fragment_count",
        "net_file",
        "intersection_ir_file",
        "validation_file",
    ):
        if key in result:
            report[key] = result[key]
    stage = StageResult(
        stage_name="intersection_compile_validate",
        status=str(result.get("status", "fail")),
        input_artifacts={"osm": str(osm_file)},
        output_artifacts={
            key: str(result[key])
            for key in ("net_file", "intersection_ir_file", "validation_file")
            if result.get(key)
        },
        after_quality=NetworkQualityVector(
            connectivity={
                "missing_movement_count": result.get("missing_movement_count", 0),
                "disconnected_edge_count": result.get("disconnected_edge_count", 0),
            },
            routeability={"route_probe_status": result.get("route_probe_status", "skipped")},
            topology_fragmentation={"internal_fragment_count": result.get("internal_fragment_count", 0)},
            tls_semantic_delta={"tls_linkindex_status": result.get("tls_linkindex_status", "skipped")},
        ),
        promotion_decision=str(result.get("status", "fail")),
        claim_status=str(result.get("claim_status", "diagnostic-demo")),
        evidence_files=[str(result[key]) for key in ("intersection_ir_file", "validation_file") if result.get(key)],
        warnings=list(result.get("warnings", [])) if isinstance(result.get("warnings"), list) else [],
    )
    report["workflow_stage_results"] = [stage.as_dict()]
    report["workflow_promotion_trace"] = build_promotion_trace(
        case_id="intersection_clean",
        claim_status=str(result.get("claim_status", "diagnostic-demo")),
        source_artifact=str(result.get("validation_file", "")),
        stages=[stage],
    )
    return report


def _run_osm_to_sumo(
    *,
    report: dict[str, Any],
    user_request: str,
    output_dir: Path,
    place_name: str | None,
    bbox: str | None,
    confirmed_area: bool,
    highway_classes: str | None,
    traffic_layers: str | None,
    network_profile: str | None,
    reference_net_file: Path | None,
    reference_policy_report: str | Path | dict[str, Any] | None,
    service_passenger_policy: str | None,
    teacher_guided_repair_max_ready_candidates: int | None,
    run_teacher_guided_repair_after_build: bool,
    road_connectivity_replay_max_owners: int | None,
    road_connectivity_probe_edge_ids: list[str] | None,
    teacher_guided_probe_matrix_junction_ids: list[str] | None,
    launch_netedit_after_build: bool | None,
    launch_sumo_gui_after_build: bool | None,
    source_osm_path: Path | None,
    autonomy_mode: str,
    place_resolver: Callable[[str], dict[str, Any]],
    cleanup_workflow_func: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    explicit_bbox = (bbox or "").strip()
    url_bbox = osm_map_url_bbox(explicit_bbox)
    if not explicit_bbox:
        url_bbox = osm_map_url_bbox(place_name or "") or osm_map_url_bbox(user_request)
    if url_bbox:
        bbox = url_bbox
        report["area_resolution_status"] = "osm_map_url_bbox"
        report["candidate_bbox"] = url_bbox

    inferred = (place_name or "").strip() or infer_place_name(user_request)
    if inferred:
        report["inferred_place_name"] = inferred

    network_plan = derive_network_plan(
        user_request=user_request,
        highway_classes=highway_classes,
        traffic_layers=traffic_layers,
        network_profile=network_profile,
        reference_net_file=reference_net_file,
        reference_policy_report=reference_policy_report,
        service_passenger_policy=service_passenger_policy,
    )
    if network_plan.get("network_profile") == "reference_matched":
        report["teacher_guided_repair_configured_max_ready_candidates"] = (
            teacher_guided_repair_max_ready_candidates if teacher_guided_repair_max_ready_candidates is not None else ""
        )
    reference_matched_with_net = network_plan.get("network_profile") == "reference_matched" and reference_net_file is not None
    if not bbox and not inferred and source_osm_path is None and not reference_matched_with_net:
        return _blocked(
            report,
            execution_status="needs_area",
            missing=["place_name_or_bbox"],
            next_question="Which OSM place name or bbox should Torii use?",
        )
    candidate: dict[str, Any] | None = None
    if not confirmed_area and not bbox and source_osm_path is None and not reference_matched_with_net:
        candidate = place_resolver(inferred)
        report.update(candidate)
        if autonomy_mode != "ask-first":
            resolved_bbox = str(candidate.get("candidate_bbox", ""))
            if candidate.get("status") == "pass" and resolved_bbox:
                bbox = resolved_bbox
                report["execution_status"] = "auto_area_candidate"
            else:
                report["execution_status"] = "needs_user_confirmation"
                report["status"] = "blocked"
                report["claim_status"] = "blocked"
                report["next_question"] = "Which OSM area or bbox should Torii use?"
                return report
        else:
            report["execution_status"] = "needs_user_confirmation"
            report["status"] = "blocked"
            report["claim_status"] = "blocked"
            report["next_question"] = "Confirm this OSM area and bbox before network construction?"
            return report
    if network_plan.get("status") == "blocked":
        report.update(network_plan)
        if network_plan.get("network_profile") == "reference_matched":
            _annotate_reference_matched_semantics(report)
        report["execution_status"] = "needs_network_plan"
        return report
    if network_plan.get("status") != "pass":
        report.update(network_plan)
        if network_plan.get("network_profile") == "reference_matched":
            _annotate_reference_matched_semantics(report)
        report["status"] = "fail"
        report["claim_status"] = "construction-invalid"
        report["execution_status"] = "network_plan_failed"
        return report
    if network_plan.get("network_profile") == "reference_matched":
        _annotate_reference_matched_semantics(report)
    selected_highway_classes = set(network_plan.get("highway_classes", []))

    cleanup_kwargs = {
        "output_dir": output_dir,
        "bbox": bbox,
        "place_name": inferred or None,
        "confirmed_area": confirmed_area,
    }
    if _supports_keyword(cleanup_workflow_func, "source_osm_path"):
        cleanup_kwargs["source_osm_path"] = source_osm_path
    if _supports_keyword(cleanup_workflow_func, "highway_classes"):
        cleanup_kwargs["highway_classes"] = selected_highway_classes
    if _supports_keyword(cleanup_workflow_func, "traffic_layers"):
        cleanup_kwargs["traffic_layers"] = ",".join(network_plan.get("movement_layers", []))
    if _supports_keyword(cleanup_workflow_func, "network_profile"):
        cleanup_kwargs["network_profile"] = network_plan.get("network_profile") or network_profile
    if _supports_keyword(cleanup_workflow_func, "reference_net_file"):
        cleanup_kwargs["reference_net_file"] = reference_net_file
    if _supports_keyword(cleanup_workflow_func, "reference_policy_report"):
        cleanup_kwargs["reference_policy_report"] = reference_policy_report
    if _supports_keyword(cleanup_workflow_func, "service_passenger_policy"):
        cleanup_kwargs["service_passenger_policy"] = network_plan.get("service_passenger_policy")
    if _supports_keyword(cleanup_workflow_func, "teacher_guided_repair_max_ready_candidates"):
        cleanup_kwargs["teacher_guided_repair_max_ready_candidates"] = teacher_guided_repair_max_ready_candidates
    if _supports_keyword(cleanup_workflow_func, "run_teacher_guided_repair_after_build"):
        cleanup_kwargs["run_teacher_guided_repair_after_build"] = run_teacher_guided_repair_after_build
    if _supports_keyword(cleanup_workflow_func, "road_connectivity_replay_max_owners"):
        cleanup_kwargs["road_connectivity_replay_max_owners"] = road_connectivity_replay_max_owners
    if _supports_keyword(cleanup_workflow_func, "road_connectivity_probe_edge_ids"):
        cleanup_kwargs["road_connectivity_probe_edge_ids"] = road_connectivity_probe_edge_ids
    if _supports_keyword(cleanup_workflow_func, "teacher_guided_probe_matrix_junction_ids"):
        cleanup_kwargs["teacher_guided_probe_matrix_junction_ids"] = teacher_guided_probe_matrix_junction_ids
    if launch_netedit_after_build is not None and _supports_keyword(cleanup_workflow_func, "launch_netedit_after_build"):
        cleanup_kwargs["launch_netedit_after_build"] = launch_netedit_after_build
    if launch_sumo_gui_after_build is not None and _supports_keyword(cleanup_workflow_func, "launch_sumo_gui_after_build"):
        cleanup_kwargs["launch_sumo_gui_after_build"] = launch_sumo_gui_after_build
    if (
        network_plan.get("network_profile") == "reference_matched"
        and _supports_keyword(cleanup_workflow_func, "reference_join_audit_structural_only")
    ):
        cleanup_kwargs["reference_join_audit_structural_only"] = False
    if _supports_keyword(cleanup_workflow_func, "run_routeability_audit_after_build"):
        cleanup_kwargs["run_routeability_audit_after_build"] = True
    workflow_report = cleanup_workflow_func(**cleanup_kwargs)
    report.update(
        {
            "status": workflow_report.get("status", "fail"),
            "claim_status": workflow_report.get("claim_status", "diagnostic-demo"),
            "execution_status": "executed",
            "tool_called": "sumo_osm_cleanup_workflow",
            "network_plan": network_plan,
            "workflow_result": workflow_report,
        }
    )
    for key in OSM_WORKFLOW_SUMMARY_KEYS:
        if key in workflow_report:
            report[key] = workflow_report[key]
    stage_results = summarize_workflow_stages(workflow_report)
    if stage_results:
        report["workflow_stage_results"] = [stage.as_dict() for stage in stage_results]
        report["workflow_promotion_trace"] = build_promotion_trace(
            case_id=str(network_plan.get("network_profile") or "osm_to_sumo"),
            claim_status=str(workflow_report.get("claim_status") or "diagnostic-demo"),
            source_artifact=str(workflow_report.get("workflow_report_file") or ""),
            stages=stage_results,
        )
    if network_plan.get("network_profile") == "reference_matched":
        _annotate_reference_matched_semantics(report, workflow_report)
    return report


def _supports_keyword(func: Callable[..., Any], name: str) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        or (parameter.name == name and parameter.kind in {inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD})
        for parameter in signature.parameters.values()
    )


def _run_tls_review(
    *,
    report: dict[str, Any],
    output_dir: Path,
    net_file: Path | None,
    osm_file: Path | None,
    official_inventory_csv: Path | None,
    signal_plan_csv: Path | None,
    field_evidence_csv: Path | None,
    tls_review_func: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if net_file is None:
        return _blocked(
            report,
            execution_status="needs_network",
            missing=["net_file"],
            next_question="Which SUMO .net.xml should Torii use for the TLS review?",
        )
    review = tls_review_func(
        net_file=net_file,
        output_dir=output_dir,
        osm_file=osm_file,
        official_inventory_csv=official_inventory_csv,
        signal_plan_csv=signal_plan_csv,
        field_evidence_csv=field_evidence_csv,
    )
    report.update(
        {
            "status": review.get("status", "fail"),
            "claim_status": review.get("claim_status", "diagnostic-demo"),
            "execution_status": "executed",
            "tool_called": "sumo_tls_multisource_review",
            "workflow_result": review,
        }
    )
    return report


def _run_network_review(
    *,
    report: dict[str, Any],
    output_dir: Path,
    net_file: Path | None,
    review_html_func: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if net_file is None:
        return _blocked(
            report,
            execution_status="needs_network",
            missing=["net_file"],
            next_question="Which partial SUMO .net.xml should Torii use for the HTML review cockpit?",
        )
    review = review_html_func(
        output_dir=output_dir,
        net_file=net_file,
        title="SUMO Network Review",
        claim_status="diagnostic-demo",
    )
    report.update(
        {
            "status": review.get("status", "fail"),
            "claim_status": review.get("claim_status", "diagnostic-demo"),
            "execution_status": "executed",
            "tool_called": "sumo_network_review_html",
            "workflow_result": review,
        }
    )
    return report

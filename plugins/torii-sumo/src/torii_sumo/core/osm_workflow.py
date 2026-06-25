from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from .osm_area import osm_preview_url, resolve_osm_place
from .connectivity import extract_largest_passenger_component_core, summarize_passenger_connectivity
from .junction_aggregation import build_junction_aggregation_variant
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
from .tls_aggregation import build_tls_aggregation_variant
from .topology_audit import audit_topology_fragmentation
from .workflow_review_html import build_workflow_review_html


PARTIAL_MAIN_COMPONENT_RATIO = 0.98


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
    max_tile_area_km2: float = 2500.0,
    max_retries: int = 2,
    retry_pause_seconds: float = 5.0,
    map_temporal_scope: str = "current",
    map_target_date: str | None = None,
    launch_netedit_after_build: bool = True,
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
    run_reference_join_aggregation_after_build: bool = True,
    run_reference_hierarchy_audit_after_build: bool = True,
    run_reference_scope_audit_after_build: bool = True,
    run_scope_pruning_after_build: bool = True,
    key_edge_queries: list[Mapping[str, Any]] | None = None,
    build_func: Callable[..., dict[str, Any]] = build_osm_network,
    tls_audit_func: Callable[..., dict[str, Any]] = audit_tls,
    connectivity_func: Callable[[Path], dict[str, Any]] = summarize_passenger_connectivity,
    connected_core_func: Callable[..., dict[str, Any]] = extract_largest_passenger_component_core,
    routeability_func: Callable[..., dict[str, Any]] = build_routeability_probe,
    topology_audit_func: Callable[..., dict[str, Any]] = audit_topology_fragmentation,
    routeability_audit_func: Callable[..., dict[str, Any]] = run_routeability_audit,
    tls_aggregation_func: Callable[..., dict[str, Any]] = build_tls_aggregation_variant,
    junction_aggregation_func: Callable[..., dict[str, Any]] = build_junction_aggregation_variant,
    reference_hierarchy_audit_func: Callable[..., dict[str, Any]] = audit_reference_hierarchy,
    reference_join_audit_func: Callable[..., dict[str, Any]] = audit_reference_join_patterns,
    reference_join_aggregation_func: Callable[..., dict[str, Any]] = build_junction_aggregation_variant,
    reference_scope_audit_func: Callable[..., dict[str, Any]] = audit_reference_scope,
    scope_pruning_func: Callable[..., dict[str, Any]] = build_scope_pruning_variant,
    netedit_func: Callable[[Path], dict[str, Any]] = launch_netedit,
    sumo_gui_func: Callable[..., dict[str, Any]] = launch_sumo_gui,
    place_resolver: Callable[[str], dict[str, Any]] = resolve_osm_place,
    reference_bbox_func: Callable[[Path], dict[str, Any]] = derive_reference_net_bbox,
    service_permission_func: Callable[..., dict[str, Any]] = apply_service_passenger_permissions,
    review_html_func: Callable[..., dict[str, Any]] = build_workflow_review_html,
) -> dict[str, Any]:
    cleaned_place_name = (place_name or "").strip()
    place_report = None
    reference_bbox_report: dict[str, Any] | None = None
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
    if not bbox and not cleaned_place_name and source_osm_path is None and reference_net_file is not None:
        reference_bbox_report = reference_bbox_func(reference_net_file)
        derived_bbox = str(reference_bbox_report.get("reference_bbox", "")).strip()
        if reference_bbox_report.get("status") == "pass" and derived_bbox:
            bbox = derived_bbox
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
    build_report = build_func(
        bbox=bbox,
        output_dir=output_dir,
        prefix=prefix,
        source_osm_path=source_osm_path,
        allowed_highways=selected_highway_classes,
        historical_date=historical_date,
        overpass_url=overpass_url,
        timeout_seconds=timeout_seconds,
        max_tile_area_km2=max_tile_area_km2,
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
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
    reference_visual_detail_build_report: dict[str, Any] = {}
    reference_visual_detail_service_permission_report: dict[str, Any] = {}
    reference_visual_detail_netedit_report: dict[str, Any] = {}
    reference_visual_detail_tls_report: dict[str, Any] | None = None
    reference_visual_detail_tls_aggregation_report: dict[str, Any] | None = None
    junction_aggregation_report: dict[str, Any] | None = None
    reference_join_audit_report: dict[str, Any] | None = None
    reference_join_aggregation_report: dict[str, Any] | None = None
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
            historical_date=historical_date,
            overpass_url=overpass_url,
            timeout_seconds=timeout_seconds,
            max_tile_area_km2=max_tile_area_km2,
            max_retries=max_retries,
            retry_pause_seconds=retry_pause_seconds,
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
        if tls_aggregation_report.get("status") == "pass" and tls_variant_value:
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
            reference_visual_detail_tls_aggregation_report = tls_aggregation_func(
                net_file=reference_visual_detail_net_file,
                tls_audit_report=reference_visual_detail_tls_report,
                output_dir=output_dir / "reference_visual_detail_tls_aggregation",
                prefix=f"{prefix}_reference_visual_detail_tls_aggregation",
                timeout_seconds=timeout_seconds,
            )
            visual_tls_variant_value = reference_visual_detail_tls_aggregation_report.get(
                "tls_aggregation_variant_file", ""
            )
            if reference_visual_detail_tls_aggregation_report.get("status") == "pass" and visual_tls_variant_value:
                candidate_visual_tls_net_file = Path(str(visual_tls_variant_value))
                if candidate_visual_tls_net_file.exists():
                    reference_visual_detail_comparison_net_file = candidate_visual_tls_net_file
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
        )
        if run_reference_join_aggregation_after_build:
            reference_join_aggregation_report = reference_join_aggregation_func(
                net_file=reference_join_audit_candidate_net_file,
                output_dir=output_dir / "reference_join_aggregation",
                prefix=f"{prefix}_reference_join_aggregation",
                topology_audit_report=topology_audit_report,
                reference_join_audit_report=reference_join_audit_report,
                join_dist_m=topology_cluster_radius_m,
                timeout_seconds=timeout_seconds,
            )
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
        and gate_status["netedit"] in {"pass", "blocked"}
        and gate_status["sumo_gui"] in {"pass", "blocked"}
    )
    bbox_regional_map_baseline = regional_map_baseline_for_bbox(bbox, label=cleaned_place_name or "SUMO network area")
    tls_regional_map_baseline = dict(tls_summary.get("regional_map_baseline") or {})
    provider_counts = tls_regional_map_baseline.get("regional_map_provider_counts")
    has_tls_regional_rows = not isinstance(provider_counts, dict) or any(int(count) > 0 for count in provider_counts.values())
    regional_map_baseline = tls_regional_map_baseline if tls_regional_map_baseline and has_tls_regional_rows else bbox_regional_map_baseline
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
        "reference_visual_detail_tls_aggregated_traffic_light_junction_count": ""
        if reference_visual_detail_tls_aggregation_report is None
        else reference_visual_detail_tls_aggregation_report.get("tls_aggregated_traffic_light_junction_count", ""),
        "reference_visual_detail_tls_aggregated_tl_logic_count": ""
        if reference_visual_detail_tls_aggregation_report is None
        else reference_visual_detail_tls_aggregation_report.get("tls_aggregated_tl_logic_count", ""),
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
        "reference_join_aggregation": reference_join_aggregation_report or {},
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
        net_file=report.get("net_file"),
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
    report.update(
        {
            "workflow_review_html_status": workflow_review_html_report.get("workflow_review_html_status", "fail"),
            "workflow_review_html_file": workflow_review_html_report.get("workflow_review_html_file", ""),
            "workflow_report_file": workflow_review_html_report.get("workflow_report_file", ""),
            "review_manifest_file": workflow_review_html_report.get("review_manifest_file", ""),
            "network_overview_png": workflow_review_html_report.get("network_overview_png", ""),
            "problem_overlay_png": workflow_review_html_report.get("problem_overlay_png", ""),
            "reference_comparison_png": workflow_review_html_report.get("reference_comparison_png", ""),
            "cluster_zoom_pngs": workflow_review_html_report.get("cluster_zoom_pngs", []),
            "human_review_required_count": workflow_review_html_report.get("human_review_required_count", 0),
            "workflow_review_html": workflow_review_html_report,
        }
    )
    return report

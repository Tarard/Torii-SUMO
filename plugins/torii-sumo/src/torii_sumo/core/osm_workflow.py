from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from .osm_area import osm_preview_url, resolve_osm_place
from .connectivity import extract_largest_passenger_component_core, summarize_passenger_connectivity
from .netedit import launch_netedit
from .osm_network import audit_tls, build_osm_network, build_routeability_probe, regional_map_baseline_for_bbox
from .routeability_audit import run_routeability_audit
from .sumo_gui import launch_sumo_gui


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
            "network_build": "not_started",
            "tls_reality_audit": "not_started",
            "connectivity": "not_started",
            "netedit": "not_started",
            "sumo_gui": "not_started",
        },
        "warnings": list(place_report.get("warnings", []) if place_report is not None else [])
        + ["place-name input requires OSM preview and user confirmation before network construction"],
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
    return {
        "tls_candidate_count": candidate_count,
        "tls_cluster_count": cluster_count,
        "tls_review_file": str(tls_report.get("clusters_file", "")),
        "tls_review_complete": "yes" if cluster_count == 0 and candidate_count == 0 else "no",
        "tls_keep_count": 0,
        "tls_remove_count": 0,
        "tls_downgrade_count": 0,
        "tls_needs_review_count": cluster_count,
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
    run_routeability_audit_after_build: bool = False,
    routeability_vehicle_count: int = 100,
    routeability_initial_end: int = 300,
    routeability_max_end: int = 2400,
    key_edge_queries: list[Mapping[str, Any]] | None = None,
    build_func: Callable[..., dict[str, Any]] = build_osm_network,
    tls_audit_func: Callable[..., dict[str, Any]] = audit_tls,
    connectivity_func: Callable[[Path], dict[str, Any]] = summarize_passenger_connectivity,
    connected_core_func: Callable[..., dict[str, Any]] = extract_largest_passenger_component_core,
    routeability_func: Callable[..., dict[str, Any]] = build_routeability_probe,
    routeability_audit_func: Callable[..., dict[str, Any]] = run_routeability_audit,
    netedit_func: Callable[[Path], dict[str, Any]] = launch_netedit,
    sumo_gui_func: Callable[[Path, Path, str], dict[str, Any]] = launch_sumo_gui,
    place_resolver: Callable[[str], dict[str, Any]] = resolve_osm_place,
) -> dict[str, Any]:
    cleaned_place_name = (place_name or "").strip()
    place_report = None
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
                    "network_build": "not_started",
                    "tls_reality_audit": "not_started",
                    "connectivity": "not_started",
                    "netedit": "not_started",
                    "sumo_gui": "not_started",
                },
                "warnings": list(place_report.get("warnings", [])) + ["confirmed place_name could not be resolved to a bbox"],
            }
        bbox = resolved_bbox
    if not bbox:
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "area_input": cleaned_place_name,
            "area_resolution_status": "blocked",
            **_candidate_fields(place_report),
            "warnings": ["bbox is required for OSM network construction"],
        }

    area_status = "confirmed_by_user" if cleaned_place_name and confirmed_area else "confirmed_by_input"
    build_report = build_func(
        bbox=bbox,
        output_dir=output_dir,
        prefix=prefix,
        source_osm_path=source_osm_path,
        allowed_highways=highway_classes,
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
            "build": build_report,
            "gate_status": {
                "area_confirmation": "pass",
                "network_build": _gate_value(build_report),
                "tls_reality_audit": "not_started",
                "connectivity": "not_started",
                "netedit": "not_started",
                "sumo_gui": "not_started",
            },
            "warnings": list(build_report.get("warnings", [])),
        }

    raw_net_file = Path(str(build_report["net_file"]))
    net_file = raw_net_file
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
    raw_connectivity_report = connectivity_func(raw_net_file)
    connectivity_report = raw_connectivity_report
    connectivity_quality = _connectivity_quality(connectivity_report)
    connected_core_report = None
    connected_core_connectivity_report = None
    if connectivity_quality["strict_connectivity_status"] != "pass":
        connected_core_report = connected_core_func(
            raw_net_file,
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
    routeability_report = None
    if key_edge_queries:
        routeability_report = routeability_func(
            net_file=net_file,
            output_dir=output_dir / "routeability",
            prefix=f"{prefix}_routeability",
            key_edge_queries=key_edge_queries,
        )
    routeability_audit_report = None
    if run_routeability_audit_after_build:
        routeability_audit_report = routeability_audit_func(
            net_file=net_file,
            output_dir=output_dir / "routeability_audit",
            prefix=f"{prefix}_routeability_audit",
            vehicle_count=routeability_vehicle_count,
            initial_end=routeability_initial_end,
            max_end=routeability_max_end,
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
    if launch_sumo_gui_after_build:
        sumo_gui_report = sumo_gui_func(net_file, output_dir / "sumo_gui", f"{prefix}_sumo_gui")
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
    warnings = []
    for child in (
        build_report,
        tls_report,
        raw_connectivity_report,
        connected_core_report or {},
        connected_core_connectivity_report or {},
        connectivity_report,
        routeability_audit_report or {},
        netedit_report,
        sumo_gui_report,
    ):
        warnings.extend(str(item) for item in child.get("warnings", []))
    if tls_summary["tls_review_complete"] == "no":
        warnings.append("TLS reality review still requires human Google Maps/current-or-user-targeted map inspection")
    if connectivity_quality["quality_warning"]:
        warnings.append(str(connectivity_quality["quality_warning"]))
    warnings = list(dict.fromkeys(warnings))

    gate_status = {
        "area_confirmation": "pass",
        "network_build": _gate_value(build_report),
        "tls_reality_audit": _gate_value(tls_report),
        "connectivity": str(connectivity_quality["connectivity_gate"]),
        "netedit": _gate_value(netedit_report),
        "sumo_gui": _gate_value(sumo_gui_report),
    }
    if routeability_audit_report is not None:
        gate_status["routeability_audit"] = _gate_value(routeability_audit_report)
    workflow_ok = (
        gate_status["network_build"] == "pass"
        and gate_status["tls_reality_audit"] == "pass"
        and gate_status["connectivity"] in {"pass", "partial"}
        and gate_status.get("routeability_audit", "skipped") in {"pass", "blocked", "skipped"}
        and gate_status["netedit"] in {"pass", "blocked"}
        and gate_status["sumo_gui"] in {"pass", "blocked"}
    )
    bbox_regional_map_baseline = regional_map_baseline_for_bbox(bbox, label=cleaned_place_name or "SUMO network area")
    tls_regional_map_baseline = dict(tls_summary.get("regional_map_baseline") or {})
    provider_counts = tls_regional_map_baseline.get("regional_map_provider_counts")
    has_tls_regional_rows = not isinstance(provider_counts, dict) or any(int(count) > 0 for count in provider_counts.values())
    regional_map_baseline = tls_regional_map_baseline if tls_regional_map_baseline and has_tls_regional_rows else bbox_regional_map_baseline
    return {
        "status": "pass" if workflow_ok else "fail",
        "claim_status": "diagnostic-demo" if workflow_ok else "construction-invalid",
        "area_input": cleaned_place_name or bbox,
        "area_resolution_status": area_status,
        **(_candidate_fields(place_report) if place_report is not None else {**_candidate_fields(None), "candidate_bbox": bbox}),
        "osm_preview_url": str(place_report.get("osm_preview_url", osm_preview_url(cleaned_place_name))) if place_report is not None else (osm_preview_url(cleaned_place_name) if cleaned_place_name else ""),
        "user_confirmed_area": "yes" if area_status == "confirmed_by_user" else "confirmed_by_input",
        "map_baseline_source": regional_map_baseline["regional_map_provider"],
        "regional_map_baseline": regional_map_baseline,
        "map_temporal_scope": map_temporal_scope,
        "map_target_date": map_target_date or "",
        **tls_summary,
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
        "routeability_probe_file": "" if routeability_report is None else str(routeability_report.get("sumocfg_file", "")),
        "missing_key_edges": [] if routeability_report is None else routeability_report.get("missing_key_edges", []),
        "routeability_probe_status": "skipped" if routeability_report is None else routeability_report.get("status", "fail"),
        "routeability_audit_status": "skipped" if routeability_audit_report is None else routeability_audit_report.get("routeability_status", routeability_audit_report.get("status", "fail")),
        "routeability_audit_report_file": "" if routeability_audit_report is None else str(routeability_audit_report.get("report_file", "")),
        "netedit_status": netedit_report.get("netedit_status", "failed"),
        "netedit_binary": netedit_report.get("netedit_binary"),
        "netedit_process_id": netedit_report.get("netedit_process_id"),
        "netedit_window_title": netedit_report.get("netedit_window_title", ""),
        "netedit_network_file": netedit_report.get("netedit_network_file", str(net_file)),
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
        "tls_audit": tls_report,
        "raw_connectivity": raw_connectivity_report,
        "connected_core": connected_core_report or {},
        "connected_core_connectivity": connected_core_connectivity_report or {},
        "connectivity": connectivity_report,
        "routeability_audit": routeability_audit_report or {},
        "netedit": netedit_report,
        "sumo_gui": sumo_gui_report,
        "gate_status": gate_status,
        "warnings": warnings,
    }

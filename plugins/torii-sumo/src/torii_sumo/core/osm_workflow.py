from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping
from urllib import parse

from .connectivity import summarize_passenger_connectivity
from .netedit import launch_netedit
from .osm_network import audit_tls, build_osm_network, build_routeability_probe


def _osm_preview_url(place_name: str) -> str:
    return "https://www.openstreetmap.org/search?" + parse.urlencode({"query": place_name})


def _blocked_place_report(place_name: str, output_dir: Path) -> dict[str, Any]:
    return {
        "status": "blocked",
        "claim_status": "blocked",
        "area_input": place_name,
        "area_resolution_status": "needs_user_confirmation",
        "candidate_display_name": "",
        "candidate_osm_type": "",
        "candidate_osm_id": "",
        "candidate_bbox": "",
        "osm_preview_url": _osm_preview_url(place_name),
        "user_confirmed_area": "no",
        "output_dir": str(output_dir),
        "gate_status": {
            "area_confirmation": "blocked",
            "network_build": "not_started",
            "tls_reality_audit": "not_started",
            "connectivity": "not_started",
            "netedit": "not_started",
        },
        "warnings": ["place-name input requires OSM preview and user confirmation before network construction"],
    }


def _gate_value(report: Mapping[str, Any]) -> str:
    status = str(report.get("status", "fail"))
    if status == "pass":
        return "pass"
    if status == "blocked":
        return "blocked"
    return "fail"


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
    key_edge_queries: list[Mapping[str, Any]] | None = None,
    build_func: Callable[..., dict[str, Any]] = build_osm_network,
    tls_audit_func: Callable[..., dict[str, Any]] = audit_tls,
    connectivity_func: Callable[[Path], dict[str, Any]] = summarize_passenger_connectivity,
    routeability_func: Callable[..., dict[str, Any]] = build_routeability_probe,
    netedit_func: Callable[[Path], dict[str, Any]] = launch_netedit,
) -> dict[str, Any]:
    cleaned_place_name = (place_name or "").strip()
    if cleaned_place_name and not confirmed_area and not bbox and source_osm_path is None:
        return _blocked_place_report(cleaned_place_name, output_dir)
    if not bbox:
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "area_input": cleaned_place_name,
            "area_resolution_status": "blocked",
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
            "user_confirmed_area": "yes" if area_status == "confirmed_by_user" else "confirmed_by_input",
            "build": build_report,
            "gate_status": {
                "area_confirmation": "pass",
                "network_build": _gate_value(build_report),
                "tls_reality_audit": "not_started",
                "connectivity": "not_started",
                "netedit": "not_started",
            },
            "warnings": list(build_report.get("warnings", [])),
        }

    net_file = Path(str(build_report["net_file"]))
    filtered_osm_value = build_report.get("filtered_osm_file") or build_report.get("source_osm_file")
    osm_file = Path(str(filtered_osm_value)) if filtered_osm_value else None
    tls_report = tls_audit_func(
        net_file=net_file,
        output_dir=output_dir / "tls_audit",
        prefix=f"{prefix}_tls_audit",
        osm_file=osm_file,
        google_maps_temporal_scope=map_temporal_scope,
        google_maps_target_date=map_target_date,
    )
    connectivity_report = connectivity_func(net_file)
    routeability_report = None
    if key_edge_queries:
        routeability_report = routeability_func(
            net_file=net_file,
            output_dir=output_dir / "routeability",
            prefix=f"{prefix}_routeability",
            key_edge_queries=key_edge_queries,
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

    tls_summary = _tls_review_summary(tls_report)
    warnings = []
    for child in (build_report, tls_report, connectivity_report, netedit_report):
        warnings.extend(str(item) for item in child.get("warnings", []))
    if tls_summary["tls_review_complete"] == "no":
        warnings.append("TLS reality review still requires human Google Maps/current-or-user-targeted map inspection")

    gate_status = {
        "area_confirmation": "pass",
        "network_build": _gate_value(build_report),
        "tls_reality_audit": _gate_value(tls_report),
        "connectivity": _gate_value(connectivity_report),
        "netedit": _gate_value(netedit_report),
    }
    workflow_ok = (
        gate_status["network_build"] == "pass"
        and gate_status["tls_reality_audit"] == "pass"
        and gate_status["connectivity"] == "pass"
        and gate_status["netedit"] in {"pass", "blocked"}
    )
    return {
        "status": "pass" if workflow_ok else "fail",
        "claim_status": "diagnostic-demo" if workflow_ok else "construction-invalid",
        "area_input": cleaned_place_name or bbox,
        "area_resolution_status": area_status,
        "candidate_display_name": "",
        "candidate_osm_type": "",
        "candidate_osm_id": "",
        "candidate_bbox": bbox,
        "osm_preview_url": _osm_preview_url(cleaned_place_name) if cleaned_place_name else "",
        "user_confirmed_area": "yes" if area_status == "confirmed_by_user" else "confirmed_by_input",
        "map_baseline_source": "Google Maps",
        "map_temporal_scope": map_temporal_scope,
        "map_target_date": map_target_date or "",
        **tls_summary,
        "connectivity_status": connectivity_report.get("connectivity_status", connectivity_report.get("status", "fail")),
        "passenger_edge_count": connectivity_report.get("passenger_edge_count", 0),
        "passenger_component_count": connectivity_report.get("passenger_component_count", 0),
        "largest_component_edge_count": connectivity_report.get("largest_component_edge_count", 0),
        "small_component_count": connectivity_report.get("small_component_count", 0),
        "isolated_passenger_edge_count": connectivity_report.get("isolated_passenger_edge_count", 0),
        "routeability_probe_file": "" if routeability_report is None else str(routeability_report.get("sumocfg_file", "")),
        "missing_key_edges": [] if routeability_report is None else routeability_report.get("missing_key_edges", []),
        "routeability_probe_status": "skipped" if routeability_report is None else routeability_report.get("status", "fail"),
        "netedit_status": netedit_report.get("netedit_status", "failed"),
        "netedit_binary": netedit_report.get("netedit_binary"),
        "netedit_process_id": netedit_report.get("netedit_process_id"),
        "netedit_window_title": netedit_report.get("netedit_window_title", ""),
        "netedit_network_file": netedit_report.get("netedit_network_file", str(net_file)),
        "net_file": str(net_file),
        "filtered_osm_file": str(filtered_osm_value) if filtered_osm_value else "",
        "build": build_report,
        "tls_audit": tls_report,
        "connectivity": connectivity_report,
        "netedit": netedit_report,
        "gate_status": gate_status,
        "warnings": warnings,
    }

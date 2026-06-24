from __future__ import annotations

from pathlib import Path
from typing import Any

from torii_sumo.core.connectivity import extract_largest_passenger_component_core
from torii_sumo.core.osm_network import (
    audit_tls,
    audit_tls_multisource,
    build_osm_network,
    build_routeability_probe,
)
from torii_sumo.core.osm_area import resolve_osm_place
from torii_sumo.core.osm_workflow import run_osm_cleanup_workflow
from torii_sumo.core.road_scope import (
    HIGHWAY_CLASS_PRESETS,
    resolve_highway_classes as resolve_highway_classes_from_scope,
)
from torii_sumo.core.routeability_audit import run_routeability_audit
from torii_sumo.core.topology_audit import audit_topology_fragmentation


def resolve_highway_classes(value: str | None) -> set[str]:
    resolved = resolve_highway_classes_from_scope(value, default_to_recommended=True)
    assert resolved is not None
    return resolved


def sumo_osm_build_network(
    bbox: str,
    output_dir: str,
    prefix: str = "sumo_osm_network",
    source_osm_path: str | None = None,
    highway_classes: str | None = None,
    historical_date: str | None = None,
    overpass_url: str = "https://overpass-api.de/api/interpreter",
    timeout_seconds: float = 240.0,
    max_tile_area_km2: float = 2500.0,
    max_retries: int = 2,
    retry_pause_seconds: float = 5.0,
) -> dict[str, Any]:
    return build_osm_network(
        bbox=bbox,
        output_dir=Path(output_dir),
        prefix=prefix,
        source_osm_path=Path(source_osm_path) if source_osm_path else None,
        allowed_highways=resolve_highway_classes(highway_classes),
        historical_date=historical_date,
        overpass_url=overpass_url,
        timeout_seconds=timeout_seconds,
        max_tile_area_km2=max_tile_area_km2,
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
    )


def sumo_tls_audit(
    net_file: str,
    output_dir: str,
    prefix: str = "sumo_tls_audit",
    osm_file: str | None = None,
    min_connections: int = 1,
    cluster_radius_m: float = 60.0,
    google_maps_temporal_scope: str = "unspecified",
    google_maps_target_date: str | None = None,
) -> dict[str, Any]:
    return audit_tls(
        net_file=Path(net_file),
        output_dir=Path(output_dir),
        prefix=prefix,
        osm_file=Path(osm_file) if osm_file else None,
        min_connections=min_connections,
        cluster_radius_m=cluster_radius_m,
        google_maps_temporal_scope=google_maps_temporal_scope,
        google_maps_target_date=google_maps_target_date,
    )


def sumo_tls_multisource_review(
    net_file: str,
    output_dir: str,
    prefix: str = "sumo_tls_multisource_review",
    osm_file: str | None = None,
    official_inventory_csv: str | None = None,
    signal_plan_csv: str | None = None,
    field_evidence_csv: str | None = None,
    min_connections: int = 1,
    google_maps_temporal_scope: str = "unspecified",
    google_maps_target_date: str | None = None,
) -> dict[str, Any]:
    return audit_tls_multisource(
        net_file=Path(net_file),
        output_dir=Path(output_dir),
        prefix=prefix,
        osm_file=Path(osm_file) if osm_file else None,
        official_inventory_csv=Path(official_inventory_csv) if official_inventory_csv else None,
        signal_plan_csv=Path(signal_plan_csv) if signal_plan_csv else None,
        field_evidence_csv=Path(field_evidence_csv) if field_evidence_csv else None,
        min_connections=min_connections,
        google_maps_temporal_scope=google_maps_temporal_scope,
        google_maps_target_date=google_maps_target_date,
    )


def sumo_network_routeability_probe(
    net_file: str,
    output_dir: str,
    key_edge_queries: list[dict[str, Any]],
    prefix: str = "routeability_probe",
    seed: int = 42,
    end: int = 180,
) -> dict[str, Any]:
    return build_routeability_probe(
        net_file=Path(net_file),
        output_dir=Path(output_dir),
        prefix=prefix,
        key_edge_queries=key_edge_queries,
        seed=seed,
        end=end,
    )


def sumo_network_routeability_audit(
    net_file: str,
    output_dir: str,
    prefix: str = "routeability_audit",
    vehicle_count: int = 100,
    seed: int = 42,
    initial_end: int = 300,
    max_end: int = 2400,
    timeout_seconds: float = 240.0,
) -> dict[str, Any]:
    return run_routeability_audit(
        net_file=Path(net_file),
        output_dir=Path(output_dir),
        prefix=prefix,
        vehicle_count=vehicle_count,
        seed=seed,
        initial_end=initial_end,
        max_end=max_end,
        timeout_seconds=timeout_seconds,
    )


def sumo_network_topology_audit(
    net_file: str,
    output_dir: str,
    prefix: str = "topology_audit",
    cluster_radius_m: float = 30.0,
    min_cluster_nodes: int = 3,
) -> dict[str, Any]:
    return audit_topology_fragmentation(
        net_file=Path(net_file),
        output_dir=Path(output_dir),
        prefix=prefix,
        cluster_radius_m=cluster_radius_m,
        min_cluster_nodes=min_cluster_nodes,
    )


def sumo_network_connected_core(
    net_file: str,
    output_dir: str,
    prefix: str = "sumo_network",
    timeout_seconds: float = 240.0,
) -> dict[str, Any]:
    return extract_largest_passenger_component_core(
        Path(net_file),
        output_dir=Path(output_dir),
        prefix=prefix,
        timeout_seconds=timeout_seconds,
    )


def sumo_osm_resolve_place(
    place_name: str,
    limit: int = 1,
    nominatim_url: str = "https://nominatim.openstreetmap.org/search",
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    return resolve_osm_place(
        place_name,
        limit=limit,
        nominatim_url=nominatim_url,
        timeout_seconds=timeout_seconds,
    )


def sumo_osm_cleanup_workflow(
    output_dir: str,
    bbox: str | None = None,
    place_name: str | None = None,
    confirmed_area: bool = False,
    prefix: str = "sumo_osm_cleanup",
    source_osm_path: str | None = None,
    highway_classes: str | None = None,
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
    routeability_vehicle_count: int = 100,
    routeability_initial_end: int = 300,
    routeability_max_end: int = 2400,
    key_edge_queries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    selected_highway_classes = resolve_highway_classes_from_scope(highway_classes, default_to_recommended=False)
    return run_osm_cleanup_workflow(
        output_dir=Path(output_dir),
        bbox=bbox,
        place_name=place_name,
        confirmed_area=confirmed_area,
        prefix=prefix,
        source_osm_path=Path(source_osm_path) if source_osm_path else None,
        highway_classes=selected_highway_classes,
        historical_date=historical_date,
        overpass_url=overpass_url,
        timeout_seconds=timeout_seconds,
        max_tile_area_km2=max_tile_area_km2,
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
        map_temporal_scope=map_temporal_scope,
        map_target_date=map_target_date,
        launch_netedit_after_build=launch_netedit_after_build,
        launch_sumo_gui_after_build=launch_sumo_gui_after_build,
        run_topology_audit_after_build=run_topology_audit_after_build,
        topology_cluster_radius_m=topology_cluster_radius_m,
        topology_min_cluster_nodes=topology_min_cluster_nodes,
        run_routeability_audit_after_build=run_routeability_audit_after_build,
        routeability_vehicle_count=routeability_vehicle_count,
        routeability_initial_end=routeability_initial_end,
        routeability_max_end=routeability_max_end,
        key_edge_queries=key_edge_queries,
    )

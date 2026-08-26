"""Typed request model for the legacy OSM cleanup workflow.

The legacy :func:`torii_sumo.core.osm_workflow.run_osm_cleanup_workflow`
accepts 95 keyword-only arguments.  This module groups the 55 non-service
arguments into small frozen specifications so callers, tools, and tests can
construct one validated request instead of passing dozens of loose keyword
arguments.

The old function remains the compatibility implementation for now.  New
callers should use
:func:`torii_sumo.core.osm_workflow_api.run_osm_cleanup_workflow_with_request`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class OsmWorkflowScope:
    """Area, source, and road-class scope for one OSM cleanup run."""

    bbox: str | None = None
    place_name: str | None = None
    confirmed_area: bool = False
    prefix: str = "sumo_osm_cleanup"
    source_osm_path: Path | None = None
    clip_source_ways_to_bbox: bool = True
    highway_classes: set[str] | None = None
    traffic_layers: str | set[str] | None = None
    network_profile: str | None = None
    reference_net_file: Path | None = None
    reference_policy_report: str | Path | Mapping[str, Any] | None = None
    service_passenger_policy: str | None = None
    historical_date: str | None = None
    map_temporal_scope: str = "current"
    map_target_date: str | None = None


@dataclass(frozen=True)
class OsmWorkflowRuntime:
    """External binaries, network timeouts, and retry policy."""

    overpass_url: str = "https://overpass-api.de/api/interpreter"
    timeout_seconds: float = 240.0
    netconvert_binary: str = "netconvert"
    sumo_binary: str = "sumo"
    max_tile_area_km2: float = 2500.0
    max_retries: int = 2
    retry_pause_seconds: float = 5.0


@dataclass(frozen=True)
class OsmWorkflowStageToggles:
    """Which optional launch/audit/materialization stages are enabled."""

    launch_netedit_after_build: bool = True
    launch_netedit_review_after_build: bool | None = None
    launch_sumo_gui_after_build: bool = True
    run_topology_audit_after_build: bool = True
    run_routeability_audit_after_build: bool = True
    run_connection_mode_audit_after_build: bool = True
    run_standard_nema_scan_after_build: bool = True
    run_tls_aggregation_after_build: bool = True
    run_junction_aggregation_after_build: bool = True
    run_reference_join_audit_after_build: bool = True
    reference_join_audit_structural_only: bool = True
    run_reference_join_aggregation_after_build: bool = True
    run_reference_hierarchy_audit_after_build: bool = True
    run_reference_scope_audit_after_build: bool = True
    run_reference_bbox_scope_after_build: bool = True
    run_road_connectivity_parity_audit_after_build: bool = True
    run_scope_pruning_after_build: bool = False
    run_corridor_geometry_simplification_after_build: bool = False
    run_corridor_edit_ledger_after_build: bool = False
    run_teacher_guided_repair_after_build: bool = True


@dataclass(frozen=True)
class OsmWorkflowStageSettings:
    """Stage-specific numerical settings and review-bound inputs."""

    topology_cluster_radius_m: float = 30.0
    topology_min_cluster_nodes: int = 3
    routeability_vehicle_count: int | None = None
    routeability_initial_end: int | None = None
    routeability_max_end: int | None = None
    review_decisions_file: Path | None = None
    teacher_guided_repair_max_ready_candidates: int | None = 80
    teacher_guided_probe_matrix_junction_ids: list[str] | None = None
    road_connectivity_replay_max_owners: int | None = 4
    road_connectivity_probe_edge_ids: list[str] | None = None
    key_edge_queries: list[Mapping[str, Any]] | None = None


@dataclass(frozen=True)
class OsmWorkflowRequest:
    """Complete non-service request for the legacy OSM cleanup workflow.

    Service callables are intentionally not part of this model.  They belong
    to ``OsmWorkflowServices`` and are resolved by the workflow API layer.
    """

    output_dir: Path
    scope: OsmWorkflowScope = field(default_factory=OsmWorkflowScope)
    runtime: OsmWorkflowRuntime = field(default_factory=OsmWorkflowRuntime)
    stage_toggles: OsmWorkflowStageToggles = field(default_factory=OsmWorkflowStageToggles)
    stage_settings: OsmWorkflowStageSettings = field(default_factory=OsmWorkflowStageSettings)

    def to_legacy_kwargs(self) -> dict[str, Any]:
        """Return exactly the non-service keyword arguments used by the legacy entry point."""

        scope = self.scope
        runtime = self.runtime
        toggles = self.stage_toggles
        settings = self.stage_settings
        return {
            "output_dir": self.output_dir,
            "bbox": scope.bbox,
            "place_name": scope.place_name,
            "confirmed_area": scope.confirmed_area,
            "prefix": scope.prefix,
            "source_osm_path": scope.source_osm_path,
            "clip_source_ways_to_bbox": scope.clip_source_ways_to_bbox,
            "highway_classes": scope.highway_classes,
            "traffic_layers": scope.traffic_layers,
            "network_profile": scope.network_profile,
            "reference_net_file": scope.reference_net_file,
            "reference_policy_report": scope.reference_policy_report,
            "service_passenger_policy": scope.service_passenger_policy,
            "historical_date": scope.historical_date,
            "overpass_url": runtime.overpass_url,
            "timeout_seconds": runtime.timeout_seconds,
            "netconvert_binary": runtime.netconvert_binary,
            "sumo_binary": runtime.sumo_binary,
            "max_tile_area_km2": runtime.max_tile_area_km2,
            "max_retries": runtime.max_retries,
            "retry_pause_seconds": runtime.retry_pause_seconds,
            "map_temporal_scope": scope.map_temporal_scope,
            "map_target_date": scope.map_target_date,
            "review_decisions_file": settings.review_decisions_file,
            "launch_netedit_after_build": toggles.launch_netedit_after_build,
            "launch_netedit_review_after_build": toggles.launch_netedit_review_after_build,
            "launch_sumo_gui_after_build": toggles.launch_sumo_gui_after_build,
            "run_topology_audit_after_build": toggles.run_topology_audit_after_build,
            "topology_cluster_radius_m": settings.topology_cluster_radius_m,
            "topology_min_cluster_nodes": settings.topology_min_cluster_nodes,
            "run_routeability_audit_after_build": toggles.run_routeability_audit_after_build,
            "run_connection_mode_audit_after_build": toggles.run_connection_mode_audit_after_build,
            "run_standard_nema_scan_after_build": toggles.run_standard_nema_scan_after_build,
            "routeability_vehicle_count": settings.routeability_vehicle_count,
            "routeability_initial_end": settings.routeability_initial_end,
            "routeability_max_end": settings.routeability_max_end,
            "run_tls_aggregation_after_build": toggles.run_tls_aggregation_after_build,
            "run_junction_aggregation_after_build": toggles.run_junction_aggregation_after_build,
            "run_reference_join_audit_after_build": toggles.run_reference_join_audit_after_build,
            "reference_join_audit_structural_only": toggles.reference_join_audit_structural_only,
            "run_reference_join_aggregation_after_build": toggles.run_reference_join_aggregation_after_build,
            "run_reference_hierarchy_audit_after_build": toggles.run_reference_hierarchy_audit_after_build,
            "run_reference_scope_audit_after_build": toggles.run_reference_scope_audit_after_build,
            "run_reference_bbox_scope_after_build": toggles.run_reference_bbox_scope_after_build,
            "run_road_connectivity_parity_audit_after_build": toggles.run_road_connectivity_parity_audit_after_build,
            "run_scope_pruning_after_build": toggles.run_scope_pruning_after_build,
            "run_corridor_geometry_simplification_after_build": toggles.run_corridor_geometry_simplification_after_build,
            "run_corridor_edit_ledger_after_build": toggles.run_corridor_edit_ledger_after_build,
            "teacher_guided_repair_max_ready_candidates": settings.teacher_guided_repair_max_ready_candidates,
            "run_teacher_guided_repair_after_build": toggles.run_teacher_guided_repair_after_build,
            "teacher_guided_probe_matrix_junction_ids": settings.teacher_guided_probe_matrix_junction_ids,
            "road_connectivity_replay_max_owners": settings.road_connectivity_replay_max_owners,
            "road_connectivity_probe_edge_ids": settings.road_connectivity_probe_edge_ids,
            "key_edge_queries": settings.key_edge_queries,
        }

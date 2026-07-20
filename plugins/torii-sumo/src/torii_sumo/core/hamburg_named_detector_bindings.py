"""Fail-closed W3 detector-to-lane binding for the named Hamburg corridor.

The official detector service gives WGS84 points, while the official-first
candidate network is stored in ETRS89 / UTM 32N metres.  This stage performs
that explicit conversion, records every nearby passenger-lane candidate, and
promotes a geometry-only binding only when the nearest lane is both close and
separated from the runner-up.  A parallel-lane tie is evidence of missing lane
identity, not permission to guess.
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Any

from .artifact_io import write_json_atomic
from .cached_detector_demand import read_hamburg_count_stream_snapshot
from .candidate_contracts import file_sha256
from .digital_twin_mapping import (
    DetectorMapping,
    _convert_network_lonlat2xy,
    bind_count_streams_to_network,
    project_point_to_polyline,
    read_network_lanes,
    write_detector_mapping,
)


DETECTOR_BINDING_SCHEMA = "torii.hamburg-named-detector-binding/v1"
DEFAULT_NETWORK_PROJECTION = "EPSG:25832"


class HamburgDetectorBindingError(ValueError):
    """Raised when the detector-binding inputs are not deterministic."""


def materialize_hamburg_named_detector_bindings(
    *,
    net_file: Path,
    count_stream_file: Path,
    output_dir: Path,
    network_projection: str = DEFAULT_NETWORK_PROJECTION,
    period: int = 900,
    max_distance_m: float = 5.0,
    ambiguity_margin_m: float = 1.0,
) -> dict[str, Any]:
    """Write an auditable detector mapping and its automatic quality gate.

    The function never creates SUMO E1/E2 sensors from an incomplete mapping.
    A later stage may consume the mapping only when every stream is active.  A
    partial result is still useful: it records why a particular field is
    blocked and which lane candidates the next plan must improve.
    """

    if period <= 0:
        raise HamburgDetectorBindingError("period must be positive")
    if not network_projection.strip():
        raise HamburgDetectorBindingError("network_projection is required")
    if not math.isfinite(max_distance_m) or max_distance_m <= 0:
        raise HamburgDetectorBindingError("max_distance_m must be finite and positive")
    if not math.isfinite(ambiguity_margin_m) or ambiguity_margin_m < 0:
        raise HamburgDetectorBindingError("ambiguity_margin_m must be finite and non-negative")

    net_path = Path(net_file).expanduser().resolve(strict=True)
    stream_path = Path(count_stream_file).expanduser().resolve(strict=True)
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise HamburgDetectorBindingError("output_dir must be empty; choose a new versioned run")

    streams = read_hamburg_count_stream_snapshot(stream_path)
    if not streams:
        raise HamburgDetectorBindingError("count stream snapshot is empty")
    net, network_lanes = read_network_lanes(net_path)
    mappings = bind_count_streams_to_network(
        net_path,
        streams,
        (),
        (),
        period=period,
        network_projection=network_projection,
    )

    candidate_rows: list[dict[str, Any]] = []
    final_mappings: list[DetectorMapping] = []
    for stream, mapping in zip(streams, mappings, strict=True):
        candidates = _candidate_rows(net, network_lanes, stream.longitude, stream.latitude, network_projection)
        nearest = candidates[0] if candidates else None
        second = candidates[1] if len(candidates) > 1 else None
        distance = float(nearest["distance_m"]) if nearest else math.inf
        separation = (
            float(second["distance_m"]) - distance
            if second is not None
            else math.inf
        )
        active = (
            nearest is not None
            and distance <= max_distance_m
            and separation >= ambiguity_margin_m
        )
        reason = (
            "strict geometry-only binding; explicit EPSG:25832 conversion; no official MAP lane identity"
            if active
            else (
                "nearest lane is outside strict detector-distance gate"
                if nearest is None or distance > max_distance_m
                else "nearest and runner-up lanes are geometrically ambiguous"
            )
        )
        if active:
            mapping = replace(
                mapping,
                mapping_confidence="high" if distance <= 2.0 else "medium",
                mapping_status="active",
                mapping_reason=reason,
            )
        else:
            mapping = replace(mapping, mapping_status="needs_review", mapping_reason=reason)
        final_mappings.append(mapping)
        candidate_rows.append(
            {
                "stream_id": stream.stream_id,
                "detector_id": stream.detector_id,
                "node_id": stream.node_id,
                "asset_id": stream.asset_id,
                "longitude": stream.longitude,
                "latitude": stream.latitude,
                "selected_lane": nearest["lane_id"] if nearest else "",
                "selected_edge": nearest["edge_id"] if nearest else "",
                "selected_distance_m": round(distance, 3) if math.isfinite(distance) else None,
                "runner_up_distance_m": round(float(second["distance_m"]), 3) if second else None,
                "separation_m": round(separation, 3) if math.isfinite(separation) else None,
                "candidate_status": "active" if active else "needs_review",
                "reason": reason,
                "candidates": candidates[:8],
            }
        )

    mapping_file = destination / "detector_mapping.csv"
    candidate_file = destination / "detector_lane_candidates.json"
    manifest_file = destination / "detector-binding.manifest.json"
    write_detector_mapping(mapping_file, final_mappings)
    candidate_payload = {
        "schema": f"{DETECTOR_BINDING_SCHEMA}/candidates",
        "network_projection": network_projection,
        "thresholds": {
            "max_distance_m": max_distance_m,
            "ambiguity_margin_m": ambiguity_margin_m,
        },
        "rows": candidate_rows,
    }
    write_json_atomic(candidate_file, candidate_payload, ensure_ascii=False, sort_keys=True)

    active_count = sum(item.mapping_status == "active" for item in final_mappings)
    incomplete = [item.stream_id for item in final_mappings if item.mapping_status != "active"]
    unmapped = [item.stream_id for item in final_mappings if not item.sumo_lane]
    execution_gate = "pass" if not unmapped else "blocked"
    promotion_gate = "pass" if active_count == len(final_mappings) else "blocked"
    status = "pass" if promotion_gate == "pass" else "partial"
    node_reports: dict[str, dict[str, Any]] = {}
    for node_id in sorted({item.node_id for item in final_mappings}):
        node_items = [item for item in final_mappings if item.node_id == node_id]
        node_reports[node_id] = {
            "stream_count": len(node_items),
            "active_count": sum(item.mapping_status == "active" for item in node_items),
            "blocked_stream_ids": [item.stream_id for item in node_items if item.mapping_status != "active"],
            "status": "pass" if all(item.mapping_status == "active" for item in node_items) else "blocked",
        }
    manifest: dict[str, Any] = {
        "schema": DETECTOR_BINDING_SCHEMA,
        "status": status,
        "execution_gate": execution_gate,
        "execution_gate_reason": (
            "all detector points have a structurally valid lane candidate"
            if execution_gate == "pass"
            else "one or more detector points have no passenger-lane candidate"
        ),
        "automatic_promotion_gate": promotion_gate,
        "automatic_promotion_reason": (
            "every official stream passed strict distance and parallel-lane ambiguity gates"
            if promotion_gate == "pass"
            else "E1/E2 materialization is withheld until every official stream has a unique strict lane binding"
        ),
        "required_node_ids": sorted({stream.node_id for stream in streams}),
        "stream_count": len(streams),
        "active_mapping_count": active_count,
        "incomplete_stream_ids": incomplete,
        "unmapped_stream_ids": unmapped,
        "source": {
            "candidate_net": {"path": str(net_path), "sha256": file_sha256(net_path)},
            "count_stream_snapshot": {"path": str(stream_path), "sha256": file_sha256(stream_path)},
        },
        "parameters": {
            "network_projection": network_projection,
            "period": period,
            "max_distance_m": max_distance_m,
            "ambiguity_margin_m": ambiguity_margin_m,
        },
        "node_reports": node_reports,
        "artifacts": {
            "detector_mapping": {"path": str(mapping_file), "sha256": file_sha256(mapping_file)},
            "detector_lane_candidates": {"path": str(candidate_file), "sha256": file_sha256(candidate_file)},
            "e1_e2_additional": {
                "status": "withheld_pending_complete_lane_mapping",
                "reason": "partial or ambiguous bindings must not create same-location SUMO sensors",
            },
        },
        "gates": {
            "coordinate_projection": "pass",
            "detector_stream_identity": "pass",
            "candidate_geometry": execution_gate,
            "unique_lane_binding": promotion_gate,
            "sumo_sensor_materialization": promotion_gate,
            "automatic_promotion": promotion_gate,
        },
        "claim_boundary": {
            "proves": [
                "the explicit WGS84-to-network CRS conversion used for each detector",
                "all nearby passenger-lane candidates and the reason for each active or blocked mapping",
                "that ambiguous parallel lanes are rejected automatically",
            ],
            "does_not_prove": [
                "official MAP lane identity when the MAP cell is absent",
                "complete three-node detector coverage",
                "that SUMO E1/E2 sensors can be materialized before all mappings are active",
            ],
        },
        "next_action": (
            "materialize_same_location_sumo_sensors"
            if promotion_gate == "pass"
            else "repair_official_first_lane_geometry_or_supply_official_map_lane_identity"
        ),
        "artifacts_manifest": str(manifest_file),
    }
    write_json_atomic(manifest_file, manifest, ensure_ascii=False, sort_keys=True)
    return {**manifest, "manifest_file": str(manifest_file)}


def _candidate_rows(
    net: object,
    network_lanes: list[Any],
    longitude: float,
    latitude: float,
    network_projection: str,
) -> list[dict[str, Any]]:
    x, y = _convert_network_lonlat2xy(
        net,
        longitude,
        latitude,
        network_projection=network_projection,
    )
    rows: list[dict[str, Any]] = []
    for lane in network_lanes:
        position, distance, heading = project_point_to_polyline((x, y), lane.shape)
        rows.append(
            {
                "lane_id": lane.lane_id,
                "edge_id": lane.edge_id,
                "lane_position_m": round(float(position), 3),
                "distance_m": round(float(distance), 3),
                "lane_heading_deg": round(float(heading), 3),
            }
        )
    rows.sort(key=lambda item: (item["distance_m"], item["edge_id"], item["lane_id"]))
    return rows


__all__ = [
    "DEFAULT_NETWORK_PROJECTION",
    "DETECTOR_BINDING_SCHEMA",
    "HamburgDetectorBindingError",
    "materialize_hamburg_named_detector_bindings",
]

"""Hash-bound evidence contract for screening a Hamburg corridor candidate.

This module deliberately stops before network stitching.  It answers a smaller
question first: do the requested official LSA cells, static MAP/OCIT topology,
motor-vehicle count streams, and official HH-SIB axis links form a credible
candidate for the next stage?  Local MAP cells still need an explicit
HH-SIB-to-cell anchor and lane-transition proof before a combined SUMO network
may be materialized.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .artifact_io import write_json_atomic
from .candidate_contracts import file_sha256


HAMBURG_CORRIDOR_CANDIDATE_SCHEMA = "torii.hamburg-corridor-candidate-evidence/v1"


class HamburgCorridorCandidateError(ValueError):
    """Raised when a corridor evidence package is malformed."""


def build_hamburg_corridor_candidate_evidence(
    *,
    candidate_id: str,
    ordered_node_ids: Sequence[str],
    lsa_identity_manifest: Path,
    static_signal_manifest: Path,
    count_manifest: Path,
    plainxml_manifests: Mapping[str, Path],
    official_road_snapshot: Path | None = None,
    axis_paths: Sequence[Mapping[str, Any]] = (),
    signal_fetch_manifest: Path | None = None,
    map_lane_axis_stitch_plan: Path | None = None,
    official_splice_plan: Path | None = None,
    output_file: Path | None = None,
) -> dict[str, Any]:
    """Build and optionally write a corridor screening manifest.

    ``axis_paths`` contains one directed path per consecutive pair of LSA
    nodes.  Each path entry has ``start_network_node``, ``end_network_node``
    and ``links``.  A link is ``{"feature_id": "...", "direction":
    "forward"|"reverse"}``.  The function validates only exact source
    records and graph continuity; it intentionally does not infer the local
    MAP-cell anchor or lane-to-lane transitions.
    """

    candidate = str(candidate_id).strip()
    if not candidate:
        raise HamburgCorridorCandidateError("candidate_id must not be empty")
    node_ids = tuple(str(value).strip() for value in ordered_node_ids)
    if len(node_ids) < 2 or any(not value for value in node_ids):
        raise HamburgCorridorCandidateError("at least two non-empty ordered_node_ids are required")
    if len(set(node_ids)) != len(node_ids):
        raise HamburgCorridorCandidateError("ordered_node_ids must be unique")

    lsa_path = _existing_file(lsa_identity_manifest, "lsa_identity_manifest")
    static_path = _existing_file(static_signal_manifest, "static_signal_manifest")
    count_path = _existing_file(count_manifest, "count_manifest")
    lsa = _read_object(lsa_path, "LSA identity manifest")
    static = _read_object(static_path, "static signal manifest")
    counts = _read_object(count_path, "count manifest")

    selections = lsa.get("selections")
    if not isinstance(selections, list):
        raise HamburgCorridorCandidateError("LSA identity manifest has no selections list")
    selected_by_id = {
        str(item.get("expected_node_id", "")): item
        for item in selections
        if isinstance(item, Mapping)
    }
    missing_lsa = [node_id for node_id in node_ids if node_id not in selected_by_id]
    lsa_gate = "pass" if str(lsa.get("decision", "")) == "pass" and not missing_lsa else "blocked"

    static_nodes = {str(value) for value in static.get("node_ids", [])}
    static_gate = (
        "pass"
        if str(static.get("status", "")) == "pass"
        and str(static.get("execution_gate", "")) == "pass"
        and set(node_ids) == static_nodes
        and all(str(node_id) in static.get("nodes", {}) for node_id in node_ids)
        else "blocked"
    )

    requested_count_nodes = {
        str(value) for value in counts.get("parameters", {}).get("requested_count_node_ids", [])
    }
    count_gates = counts.get("gates") if isinstance(counts.get("gates"), Mapping) else {}
    count_gate = (
        "pass"
        if str(counts.get("status", "")) == "pass"
        and str(counts.get("execution_gate", "")) == "pass"
        and requested_count_nodes == set(node_ids)
        and all(str(count_gates.get(name, "")) == "pass" for name in (
            "full_named_node_coverage",
            "official_observation_window",
        ))
        else "blocked"
    )

    plainxml_status: dict[str, str] = {}
    for node_id in node_ids:
        path = plainxml_manifests.get(node_id)
        if path is None:
            plainxml_status[node_id] = "blocked"
            continue
        payload = _read_object(_existing_file(path, f"PlainXML manifest {node_id}"), f"PlainXML manifest {node_id}")
        plainxml_status[node_id] = (
            "pass"
            if str(payload.get("status", "")) == "pass"
            and str(payload.get("compiled_network_audit", {}).get("status", "")) == "pass"
            else "blocked"
        )
    plainxml_gate = "pass" if all(value == "pass" for value in plainxml_status.values()) else "blocked"

    axis_report: dict[str, Any]
    if official_road_snapshot is None:
        axis_report = {
            "status": "blocked",
            "reason": "official_road_snapshot_not_supplied",
            "segments": [],
        }
    else:
        road_path = _existing_file(official_road_snapshot, "official_road_snapshot")
        axis_report = _validate_axis_paths(road_path, node_ids, axis_paths)

    signal_fetch_report: dict[str, Any] | None = None
    signal_history_gate = "not_run"
    if signal_fetch_manifest is not None:
        signal_fetch_path = _existing_file(signal_fetch_manifest, "signal_fetch_manifest")
        signal_fetch_report = _read_object(signal_fetch_path, "signal fetch manifest")
        signal_history_gate = (
            "pass"
            if str(signal_fetch_report.get("status", "")) == "pass"
            and str(signal_fetch_report.get("execution_gate", "")) == "pass"
            else "blocked"
        )

    lane_stitch_report: dict[str, Any] | None = None
    lane_stitch_gate = "not_run"
    lane_geometry_gate = "not_run"
    lane_geometry_report: dict[str, Any] | None = None
    if map_lane_axis_stitch_plan is not None:
        lane_stitch_path = _existing_file(map_lane_axis_stitch_plan, "MAP-to-HH-SIB lane-axis stitch plan")
        lane_stitch_report = _read_object(lane_stitch_path, "MAP-to-HH-SIB lane-axis stitch plan")
        if lane_stitch_report.get("schema") != "torii.hamburg-official-map-hh-sib-lane-axis-stitch-plan/v1":
            raise HamburgCorridorCandidateError("MAP-to-HH-SIB lane-axis stitch plan schema is invalid")
        lane_stitch_gate = (
            "pass"
            if str(lane_stitch_report.get("status")) == "pass"
            else "review_required"
            if str(lane_stitch_report.get("status")) == "review_required"
            else "blocked"
        )
        raw_conflicts = lane_stitch_report.get("approach_geometry_conflicts")
        if isinstance(raw_conflicts, list):
            conflicts = [
                dict(item)
                for item in raw_conflicts
                if isinstance(item, Mapping)
            ]
            lane_geometry_gate = (
                "pass"
                if all(str(item.get("status", "")) == "pass" for item in conflicts)
                else "review_required"
            )
            lane_geometry_report = {
                "status": lane_geometry_gate,
                "approach_count": len(conflicts),
                "conflict_count": sum(
                    str(item.get("status", "")) != "pass" for item in conflicts
                ),
                "approaches": conflicts,
                "decision": (
                    "materialize_boundary_join"
                    if lane_geometry_gate == "pass"
                    else "split_official_map_merge_points_before_boundary_join"
                ),
            }

    splice_report: dict[str, Any] | None = None
    splice_gate = "not_run"
    if official_splice_plan is not None:
        splice_path = _existing_file(official_splice_plan, "official MAP-to-HH-SIB splice plan")
        splice_report = _read_object(splice_path, "official MAP-to-HH-SIB splice plan")
        if splice_report.get("schema") != "torii.hamburg-official-map-hh-sib-splice-plan/v1":
            raise HamburgCorridorCandidateError("official MAP-to-HH-SIB splice plan schema is invalid")
        splice_gate = (
            "pass"
            if str(splice_report.get("status")) == "pass"
            else "review_required"
            if str(splice_report.get("status")) == "review_required"
            else "blocked"
        )

    ordered_nodes = [_node_record(selected_by_id[node_id], node_id) for node_id in node_ids if node_id in selected_by_id]
    distances = [
        {
            "from_node_id": node_ids[index],
            "to_node_id": node_ids[index + 1],
            "distance_m": round(_haversine_m(
                ordered_nodes[index]["coordinates"],
                ordered_nodes[index + 1]["coordinates"],
            ), 3),
        }
        for index in range(len(ordered_nodes) - 1)
    ]

    gates = {
        "official_lsa_identity": lsa_gate,
        "official_static_map_kml_ocit": static_gate,
        "per_node_official_plainxml": plainxml_gate,
        "official_motor_vehicle_counts": count_gate,
        "official_axis_link_chain": str(axis_report.get("status", "blocked")),
        "official_axis_anchor_binding": "review_required" if axis_report.get("status") == "pass" else "blocked",
        "official_map_hh_sib_lane_axis_stitch": lane_stitch_gate,
        "official_map_boundary_geometry": lane_geometry_gate,
        "official_map_hh_sib_splice_plan": splice_gate,
        "historical_signal_observations": signal_history_gate,
        "combined_corridor_network": "not_run",
        "same_location_virtual_detectors": "not_run",
        "route_generation_and_completion": "not_run",
        "automatic_promotion": "blocked",
    }
    preflight_pass = all(
        gates[name] == "pass"
        for name in (
            "official_lsa_identity",
            "official_static_map_kml_ocit",
            "per_node_official_plainxml",
            "official_motor_vehicle_counts",
            "official_axis_link_chain",
        )
    )
    status = "review_required" if preflight_pass else "blocked"
    input_paths: dict[str, dict[str, Any]] = {
        "lsa_identity_manifest": _artifact_identity(lsa_path),
        "static_signal_manifest": _artifact_identity(static_path),
        "count_manifest": _artifact_identity(count_path),
    }
    if official_road_snapshot is not None:
        input_paths["official_road_snapshot"] = _artifact_identity(_existing_file(official_road_snapshot, "official_road_snapshot"))
    if signal_fetch_manifest is not None:
        input_paths["signal_fetch_manifest"] = _artifact_identity(_existing_file(signal_fetch_manifest, "signal_fetch_manifest"))
    if map_lane_axis_stitch_plan is not None:
        input_paths["map_lane_axis_stitch_plan"] = _artifact_identity(
            _existing_file(map_lane_axis_stitch_plan, "MAP-to-HH-SIB lane-axis stitch plan")
        )
    if official_splice_plan is not None:
        input_paths["official_splice_plan"] = _artifact_identity(
            _existing_file(official_splice_plan, "official MAP-to-HH-SIB splice plan")
        )
    input_paths["plainxml_manifests"] = {
        node_id: _artifact_identity(_existing_file(plainxml_manifests[node_id], f"PlainXML manifest {node_id}"))
        for node_id in node_ids
        if node_id in plainxml_manifests
    }
    manifest: dict[str, Any] = {
        "schema": HAMBURG_CORRIDOR_CANDIDATE_SCHEMA,
        "candidate_id": candidate,
        "status": status,
        "claim_status": "official_static_corridor_candidate" if status == "review_required" else "blocked",
        "automatic_promotion_gate": "blocked",
        "ordered_node_ids": list(node_ids),
        "nodes": ordered_nodes,
        "distances": distances,
        "inputs": input_paths,
        "axis_connector": axis_report,
        "signal_history_fetch": signal_fetch_report,
        "map_lane_axis_stitch": lane_stitch_report,
        "map_lane_axis_conflicts": lane_geometry_report,
        "official_map_hh_sib_splice_plan": splice_report,
        "plainxml_status_by_node": plainxml_status,
        "gates": gates,
        "claim_boundary": {
            "proves": [
                "official LSA identity and ordered node coordinates",
                "current official MAP/KML/OCIT assets and per-node static PlainXML compilation when the gates pass",
                "complete official motor-vehicle detector inventory and the selected Saturday count window when the count gate passes",
                "directed continuity of the selected HH-SIB feature path",
            ],
            "does_not_prove": [
                "local MAP cell to HH-SIB axis anchor identity",
                "corridor lane-transition legality or SUMO junction connections",
                "historical Saturday signal states when the TLD fetch gate is blocked",
                "a combined SUMO network, route files, or same-location virtual sensors",
            ],
        },
        "autonomous_action": (
            "continue_to_official_axis_anchor_and_lane_transition_stage"
            if status == "review_required"
            else "abstain_until_required_official_evidence_is_complete"
        ),
    }
    if output_file is not None:
        destination = Path(output_file).expanduser().resolve()
        if any(Path(identity["path"]).resolve() == destination for identity in input_paths.values() if isinstance(identity, Mapping) and "path" in identity):
            raise HamburgCorridorCandidateError("output_file must be separate from input artifacts")
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(destination, manifest, sort_keys=True)
        manifest["manifest_file"] = str(destination)
        manifest["manifest_sha256"] = file_sha256(destination)
    return manifest


def _validate_axis_paths(
    snapshot_path: Path,
    node_ids: Sequence[str],
    axis_paths: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"status": "blocked", "reason": f"invalid_official_road_snapshot:{type(exc).__name__}", "segments": []}
    features = payload.get("features") if isinstance(payload, Mapping) else None
    if not isinstance(features, list):
        return {"status": "blocked", "reason": "official_road_feature_collection_required", "segments": []}
    by_id = {str(feature.get("id")): feature for feature in features if isinstance(feature, Mapping) and feature.get("id") is not None}
    expected_segments = len(node_ids) - 1
    if len(axis_paths) != expected_segments:
        return {
            "status": "blocked",
            "reason": f"axis_path_segment_count_mismatch:{len(axis_paths)}:{expected_segments}",
            "segments": [],
        }
    segments: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, raw_segment in enumerate(axis_paths):
        segment = raw_segment if isinstance(raw_segment, Mapping) else {}
        from_node = str(segment.get("from_node_id", ""))
        to_node = str(segment.get("to_node_id", ""))
        links = segment.get("links") if isinstance(segment.get("links"), list) else []
        expected_from = node_ids[index]
        expected_to = node_ids[index + 1]
        if (from_node, to_node) != (expected_from, expected_to):
            errors.append(f"segment_endpoint_mismatch:{from_node}:{to_node}")
        current = str(segment.get("start_network_node", ""))
        link_records: list[dict[str, Any]] = []
        for raw_link in links:
            link = raw_link if isinstance(raw_link, Mapping) else {}
            feature_id = str(link.get("feature_id", ""))
            direction = str(link.get("direction", "forward")).lower()
            feature = by_id.get(feature_id)
            if feature is None:
                errors.append(f"axis_feature_missing:{feature_id}")
                continue
            properties = feature.get("properties") if isinstance(feature.get("properties"), Mapping) else {}
            required = ("von_netzknoten", "nach_netzknoten", "strassenname", "abschnittslaenge")
            missing = [name for name in required if name not in properties]
            if missing:
                errors.append(f"axis_feature_missing_property:{feature_id}:{','.join(missing)}")
                continue
            raw_from = str(properties["von_netzknoten"])
            raw_to = str(properties["nach_netzknoten"])
            if direction not in {"forward", "reverse"}:
                errors.append(f"axis_direction_invalid:{feature_id}:{direction}")
                continue
            oriented_from, oriented_to = (raw_from, raw_to) if direction == "forward" else (raw_to, raw_from)
            if current and oriented_from != current:
                errors.append(f"axis_chain_break:{feature_id}:{current}:{oriented_from}")
            current = oriented_to
            link_records.append({
                "feature_id": feature_id,
                "direction": direction,
                "road_name": str(properties.get("strassenname", "")),
                "from_network_node": raw_from,
                "to_network_node": raw_to,
                "length_m": properties.get("abschnittslaenge"),
            })
        expected_end = str(segment.get("end_network_node", ""))
        if expected_end and current != expected_end:
            errors.append(f"axis_end_mismatch:{from_node}:{current}:{expected_end}")
        segments.append({
            "from_node_id": from_node,
            "to_node_id": to_node,
            "start_network_node": str(segment.get("start_network_node", "")),
            "end_network_node": expected_end,
            "links": link_records,
            "status": "pass" if not errors else "review_required",
        })
    return {
        "status": "pass" if not errors and all(item["links"] for item in segments) else "blocked",
        "reason": "exact_feature_chain_validated" if not errors else "axis_path_validation_failed",
        "errors": errors,
        "snapshot": _artifact_identity(snapshot_path),
        "segments": segments,
    }


def _node_record(selection: Mapping[str, Any], node_id: str) -> dict[str, Any]:
    selected = selection.get("selected_node") if isinstance(selection.get("selected_node"), Mapping) else {}
    point = selected.get("point_geometry") if isinstance(selected.get("point_geometry"), Mapping) else {}
    coordinates = point.get("coordinates") if isinstance(point.get("coordinates"), list) else []
    if len(coordinates) != 2:
        coordinates = [None, None]
    return {
        "node_id": node_id,
        "official_name": str(selected.get("official_name", "")),
        "signal_type": str(selected.get("signal_type", "")),
        "coordinates": [coordinates[0], coordinates[1]],
    }


def _haversine_m(first: Sequence[Any], second: Sequence[Any]) -> float:
    if len(first) != 2 or len(second) != 2 or any(value is None for value in (*first, *second)):
        return float("nan")
    lon1, lat1, lon2, lat2 = map(float, (first[0], first[1], second[0], second[1]))
    radius = 6371008.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _existing_file(value: Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise HamburgCorridorCandidateError(f"{label} must be an existing file: {path}")
    return path


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HamburgCorridorCandidateError(f"invalid {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise HamburgCorridorCandidateError(f"{label} must contain a JSON object: {path}")
    return payload


def _artifact_identity(path: Path) -> dict[str, Any]:
    resolved = Path(path).resolve()
    return {"path": str(resolved), "sha256": file_sha256(resolved), "bytes": resolved.stat().st_size}


__all__ = [
    "HAMBURG_CORRIDOR_CANDIDATE_SCHEMA",
    "HamburgCorridorCandidateError",
    "build_hamburg_corridor_candidate_evidence",
]

"""Compatibility tail extracted from ``junction_rebuild_candidate``.

This module contains the signature, report, and geometry-restore helpers from
the legacy 15k-line implementation.  The original module re-exports these
names so existing callers and tests keep working while the monolith shrinks.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from typing import Any
import xml.etree.ElementTree as ET
from pathlib import Path
from .command_runner import run_command
from .junction_connection_audit import (
    build_connection_signature,
    write_connection_signature,
)
from .junction_join_definition import build_junction_join_definition
from .junction_movement_model import (
    audit_movement_graph,
    build_movement_graph,
    write_movement_review,
)
from .junction_teacher_model import (
    _extract_teacher_junction_model,
    materialize_exemplar_movement_signatures,
    slot_edge_map_from_exemplar,
)
from .junction_rebuild_helpers import (
    _approach_edges,
    _candidate_edge_by_exact_or_unsplit_id,
    _candidate_lane_counts,
    _connection_edges_are_adjacent,
    _connection_lane_indices_valid,
    _edge_file_lane_counts,
    _endpoint_rewrites,
    _first_junction_index,
    _int_count,
    _map_internal_ref,
    _net_lane_counts,
    _plain_crossing_node_id,
    _plain_edge_endpoints,
    _should_emit,
    _stage_file,
    _sumo_cluster_member_ids,
    _sumo_joined_cluster_id,
    _teacher_junction_has_tls,
    _touches_target_internal_subgraph,
    _valid_edge_map,
    _write_connections,
)

GEOMETRY_RESTORE_LANE_ATTRS = (
    "speed",
    "shape",
    "length",
    "width",
    "endOffset",
    "customShape",
    "outlineShape",
)

ROAD_CONTINUITY_COUNT_FIELDS = (
    "same_family_continuation_edge_map_count",
    "copied_boundary_continuation_edge_count",
    "copied_boundary_continuation_connection_count",
    "replayed_stale_split_continuation_edge_count",
    "replayed_stale_split_followup_edge_count",
    "rewired_stale_split_fragment_connection_count",
    "removed_teacher_absent_same_family_continuation_edge_count",
)

ROAD_CONTINUITY_FAILURE_FIELDS = (
    "removed_stale_boundary_edge_connection_count",
    "removed_stale_replaced_edge_connection_count",
    "removed_invalid_lane_connection_count",
    "skipped_connection_count",
)

TLS_CONNECTION_REPAIR_ATTRS = (
    "tl",
    "linkIndex",
    "linkIndex2",
    "dir",
    "state",
    "pass",
    "allow",
    "disallow",
    "keepClear",
    "contPos",
)



TURNAROUND_DIR = "t"

def _split(value: str) -> list[str]:
    return [part for part in value.split() if part]

def _approaches(model: dict[str, object], direction: str) -> list[dict[str, Any]]:
    approaches = model.get("approaches", {})
    if not isinstance(approaches, dict):
        return []
    return [edge for edge in approaches.get(direction, []) or [] if isinstance(edge, dict)]

def _remove_teacher_non_tls_tllogics(
    *,
    teacher_net_file: Path,
    target_file: Path,
) -> dict[str, object]:
    if not teacher_net_file.exists():
        return _failure(f"teacher net file does not exist: {teacher_net_file}")
    if not target_file.exists():
        return _failure(f"target net file does not exist: {target_file}")

    teacher_root = ET.parse(teacher_net_file).getroot()
    target_tree = ET.parse(target_file)
    target_root = target_tree.getroot()
    teacher_tl_logic_ids = {
        tl_logic.attrib.get("id", "")
        for tl_logic in teacher_root.findall("tlLogic")
        if tl_logic.attrib.get("id")
    }
    teacher_non_tls_types = {
        junction.attrib.get("id", ""): junction.attrib.get("type", "")
        for junction in teacher_root.findall("junction")
        if junction.attrib.get("id")
        and not junction.attrib.get("id", "").startswith(":")
        and junction.attrib.get("id", "") not in teacher_tl_logic_ids
        and junction.attrib.get("type") not in {"", "traffic_light"}
    }
    removed_ids = []
    for tl_logic in list(target_root.findall("tlLogic")):
        tls_id = tl_logic.attrib.get("id", "")
        if tls_id not in teacher_non_tls_types:
            continue
        target_root.remove(tl_logic)
        removed_ids.append(tls_id)

    uncontrolled_connections = []
    removed_id_set = set(removed_ids)
    for connection in target_root.findall("connection"):
        if connection.attrib.get("tl") not in removed_id_set:
            continue
        uncontrolled_connections.append(dict(connection.attrib))
        for attr in ("tl", "linkIndex", "linkIndex2"):
            connection.attrib.pop(attr, None)
        connection.set("uncontrolled", "true")

    restored_junction_ids = []
    for junction_id in removed_ids:
        junction = target_root.find(f"junction[@id='{junction_id}']")
        if junction is None:
            continue
        teacher_type = teacher_non_tls_types[junction_id]
        if junction.attrib.get("type") == teacher_type:
            continue
        junction.set("type", teacher_type)
        restored_junction_ids.append(junction_id)

    if removed_ids or uncontrolled_connections or restored_junction_ids:
        ET.indent(target_root, space="    ")
        target_tree.write(target_file, encoding="utf-8", xml_declaration=True)

    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "teacher_net_file": str(teacher_net_file),
        "target_file": str(target_file),
        "removed_teacher_non_tls_tllogic_count": len(removed_ids),
        "removed_teacher_non_tls_tllogic_ids": removed_ids,
        "uncontrolled_teacher_non_tls_connection_count": len(uncontrolled_connections),
        "uncontrolled_teacher_non_tls_connections": uncontrolled_connections,
        "restored_teacher_non_tls_junction_type_count": len(restored_junction_ids),
        "restored_teacher_non_tls_junction_type_ids": restored_junction_ids,
    }

def _restore_false_traffic_light_junction_types(
    *,
    source_file: Path,
    target_file: Path,
    fallback_node_file: Path | None = None,
    exclude_junction_ids: set[str] | None = None,
) -> dict[str, object]:
    if not source_file.exists():
        return _failure(f"source net file does not exist: {source_file}")
    if not target_file.exists():
        return _failure(f"target net file does not exist: {target_file}")
    if fallback_node_file is not None and not fallback_node_file.exists():
        return _failure(f"fallback node file does not exist: {fallback_node_file}")

    source_root = ET.parse(source_file).getroot()
    target_tree = ET.parse(target_file)
    target_root = target_tree.getroot()
    source_types = {
        junction.attrib.get("id", ""): junction.attrib.get("type", "")
        for junction in source_root.findall("junction")
        if junction.attrib.get("id") and not junction.attrib.get("id", "").startswith(":")
    }
    fallback_types = {}
    if fallback_node_file is not None:
        fallback_types = {
            node.attrib.get("id", ""): node.attrib.get("type", "")
            for node in ET.parse(fallback_node_file).getroot().findall("node")
            if node.attrib.get("id")
        }
    tl_logic_ids = {tl.attrib.get("id", "") for tl in target_root.findall("tlLogic") if tl.attrib.get("id")}
    controlled_tls_ids = {
        connection.attrib.get("tl", "")
        for connection in target_root.findall("connection")
        if connection.attrib.get("tl")
    }
    exclude_junction_ids = exclude_junction_ids or set()
    restored_ids = []
    for junction in target_root.findall("junction"):
        junction_id = junction.attrib.get("id", "")
        source_type = source_types.get(junction_id, "")
        if source_type in {"", "traffic_light"}:
            source_type = fallback_types.get(junction_id, source_type)
        if (
            not junction_id
            or junction_id.startswith(":")
            or junction_id in exclude_junction_ids
            or junction.attrib.get("type") != "traffic_light"
            or source_type in {"", "traffic_light"}
            or junction_id in tl_logic_ids
            or junction_id in controlled_tls_ids
        ):
            continue
        junction.set("type", source_type)
        restored_ids.append(junction_id)

    if restored_ids:
        ET.indent(target_root, space="    ")
        target_tree.write(target_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "source_file": str(source_file),
        "target_file": str(target_file),
        "fallback_node_file": str(fallback_node_file) if fallback_node_file is not None else "",
        "restored_false_traffic_light_junction_type_count": len(restored_ids),
        "restored_false_traffic_light_junction_ids": restored_ids,
    }

def _via_lane_edge_id(via_lane_id: str) -> str:
    if not via_lane_id:
        return ""
    if via_lane_id.startswith(":") and "_" in via_lane_id:
        return via_lane_id.rsplit("_", 1)[0]
    return via_lane_id

def _translate_shape(shape: str, dx: float, dy: float) -> str:
    translated = []
    for point in _split(shape):
        coords = point.split(",")
        if len(coords) < 2:
            translated.append(point)
            continue
        coords[0] = _format_xy(float(coords[0]) + dx)
        coords[1] = _format_xy(float(coords[1]) + dy)
        translated.append(",".join(coords))
    return " ".join(translated)

def _format_xy(value: float) -> str:
    return f"{value:.2f}"

def _pedestrian_tl_pairs_from_records(records: object, junction_id: str) -> dict[str, tuple[str, str]]:
    pairs: dict[str, tuple[str, str]] = {}
    internal_prefix = f":{junction_id}_"
    items = records if isinstance(records, list) else []
    for record in items:
        if not isinstance(record, dict) or str(record.get("tl", "")) != junction_id:
            continue
        source = str(record.get("from", ""))
        target = str(record.get("to", ""))
        if source.startswith(f"{internal_prefix}w") and target.startswith(f"{internal_prefix}c") and record.get("linkIndex"):
            pairs[str(record["linkIndex"])] = (source, target)
    return pairs

def _pedestrian_tl_pairs_from_connections(connections: list[ET.Element], junction_id: str) -> dict[str, tuple[str, str]]:
    pairs: dict[str, tuple[str, str]] = {}
    internal_prefix = f":{junction_id}_"
    for connection in connections:
        if connection.attrib.get("tl") != junction_id:
            continue
        source = connection.attrib.get("from", "")
        target = connection.attrib.get("to", "")
        if source.startswith(f"{internal_prefix}w") and target.startswith(f"{internal_prefix}c") and connection.attrib.get("linkIndex"):
            pairs[connection.attrib["linkIndex"]] = (source, target)
    return pairs

def _touches_target_pedestrian_ring(connection: ET.Element, internal_prefix: str) -> bool:
    source = connection.attrib.get("from", "")
    target = connection.attrib.get("to", "")
    return source.startswith(f"{internal_prefix}w") or source.startswith(f"{internal_prefix}c") or target.startswith(f"{internal_prefix}w") or target.startswith(f"{internal_prefix}c")

def _map_teacher_pedestrian_endpoint(
    edge_id: str,
    walkingarea_map: dict[str, str],
    crossing_map: dict[str, str],
    edge_map: dict[str, str],
) -> str | None:
    if edge_id in walkingarea_map:
        return walkingarea_map[edge_id]
    if edge_id in crossing_map:
        return crossing_map[edge_id]
    if edge_id.startswith(":"):
        return None
    return edge_map.get(edge_id, edge_id)

def _command_report(result: Any) -> dict[str, object]:
    if hasattr(result, "to_dict"):
        payload = result.to_dict()
    elif isinstance(result, dict):
        payload = dict(result)
    else:
        payload = {
            "status": getattr(result, "status", "fail"),
            "returncode": getattr(result, "returncode", None),
        }
    if "status" not in payload:
        payload["status"] = "pass" if payload.get("returncode") == 0 else "fail"
    return payload

def _endpoint_rewrite_old_endpoint_ids(lane_patch_report: dict[str, object]) -> set[str]:
    old_ids: set[str] = set()
    for field in ("endpoint_rewritten_existing_mapped_edges", "endpoint_rewritten_missing_mapped_edges"):
        entries = lane_patch_report.get(field, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for attr in ("from", "to"):
                change = entry.get(attr)
                if not isinstance(change, dict):
                    continue
                old = str(change.get("old", ""))
                new = str(change.get("new", ""))
                if old and old != new and not old.startswith(":"):
                    old_ids.add(old)
    return old_ids

def _compare_teacher_models(
    teacher_model: dict[str, Any],
    candidate_model: dict[str, Any],
    *,
    edge_map: dict[str, str] | None = None,
    teacher_junction_id: str = "",
    candidate_junction_id: str = "",
) -> dict[str, object]:
    teacher_summary = _teacher_parity_summary(teacher_model)
    candidate_summary = _teacher_parity_summary(candidate_model)
    keys = sorted(set(teacher_summary) | set(candidate_summary))
    delta: dict[str, int] = {}
    for key in keys:
        candidate_value = candidate_summary.get(key, 0)
        teacher_value = teacher_summary.get(key, 0)
        if isinstance(candidate_value, int) and isinstance(teacher_value, int):
            delta[key] = candidate_value - teacher_value
        elif candidate_value != teacher_value:
            delta[f"{key}_mismatch_count"] = 1
    if edge_map is not None:
        teacher_signatures = _controlled_vehicle_link_signatures(
            teacher_model,
            edge_map=edge_map,
            source_junction_id=teacher_junction_id or str(teacher_model.get("junction_id", "")),
            target_junction_id=candidate_junction_id or str(candidate_model.get("junction_id", "")),
        )
        candidate_signatures = _controlled_vehicle_link_signatures(candidate_model)
        mismatch_count = _dict_mismatch_count(teacher_signatures, candidate_signatures)
        teacher_summary["controlled_vehicle_link_signatures"] = teacher_signatures
        candidate_summary["controlled_vehicle_link_signatures"] = candidate_signatures
        if mismatch_count:
            delta["controlled_vehicle_link_signature_mismatch_count"] = mismatch_count
        teacher_pedestrian_signatures = _controlled_pedestrian_link_signatures(
            teacher_model,
            edge_map=edge_map,
            source_junction_id=teacher_junction_id or str(teacher_model.get("junction_id", "")),
            target_junction_id=candidate_junction_id or str(candidate_model.get("junction_id", "")),
        )
        candidate_pedestrian_signatures = _controlled_pedestrian_link_signatures(candidate_model)
        pedestrian_mismatch_count = _dict_mismatch_count(teacher_pedestrian_signatures, candidate_pedestrian_signatures)
        teacher_summary["controlled_pedestrian_link_signatures"] = teacher_pedestrian_signatures
        candidate_summary["controlled_pedestrian_link_signatures"] = candidate_pedestrian_signatures
        if pedestrian_mismatch_count:
            delta["controlled_pedestrian_link_signature_mismatch_count"] = pedestrian_mismatch_count
        teacher_pedestrian_ring_signatures = _uncontrolled_pedestrian_connection_signatures(
            teacher_model,
            edge_map=edge_map,
            source_junction_id=teacher_junction_id or str(teacher_model.get("junction_id", "")),
            target_junction_id=candidate_junction_id or str(candidate_model.get("junction_id", "")),
        )
        candidate_pedestrian_ring_signatures = _uncontrolled_pedestrian_connection_signatures(candidate_model)
        pedestrian_ring_mismatch_count = _dict_mismatch_count(
            teacher_pedestrian_ring_signatures, candidate_pedestrian_ring_signatures
        )
        teacher_summary["uncontrolled_pedestrian_connection_signatures"] = teacher_pedestrian_ring_signatures
        candidate_summary["uncontrolled_pedestrian_connection_signatures"] = candidate_pedestrian_ring_signatures
        if pedestrian_ring_mismatch_count:
            delta["uncontrolled_pedestrian_connection_signature_mismatch_count"] = pedestrian_ring_mismatch_count
        teacher_junction_signature = _junction_signature(
            teacher_model,
            edge_map=edge_map,
            source_junction_id=teacher_junction_id or str(teacher_model.get("junction_id", "")),
            target_junction_id=candidate_junction_id or str(candidate_model.get("junction_id", "")),
        )
        candidate_junction_signature = _junction_signature(candidate_model)
        teacher_summary["junction_signature"] = teacher_junction_signature
        candidate_summary["junction_signature"] = candidate_junction_signature
        if teacher_junction_signature != candidate_junction_signature:
            delta["junction_signature_mismatch_count"] = 1
        teacher_approach_signatures = _approach_edge_signatures(
            teacher_model,
            edge_map=edge_map,
            source_junction_id=teacher_junction_id or str(teacher_model.get("junction_id", "")),
            target_junction_id=candidate_junction_id or str(candidate_model.get("junction_id", "")),
        )
        candidate_approach_signatures = _approach_edge_signatures(candidate_model)
        approach_mismatch_count = _dict_mismatch_count(teacher_approach_signatures, candidate_approach_signatures)
        teacher_summary["approach_edge_signatures"] = teacher_approach_signatures
        candidate_summary["approach_edge_signatures"] = candidate_approach_signatures
        if approach_mismatch_count:
            delta["approach_edge_signature_mismatch_count"] = approach_mismatch_count
        teacher_approach_endpoint_signatures = _approach_endpoint_signatures(
            teacher_model,
            edge_map=edge_map,
            source_junction_id=teacher_junction_id or str(teacher_model.get("junction_id", "")),
            target_junction_id=candidate_junction_id or str(candidate_model.get("junction_id", "")),
        )
        candidate_approach_endpoint_signatures = _approach_endpoint_signatures(candidate_model)
        approach_endpoint_mismatch_count = _dict_mismatch_count(
            teacher_approach_endpoint_signatures, candidate_approach_endpoint_signatures
        )
        teacher_summary["approach_endpoint_signatures"] = teacher_approach_endpoint_signatures
        candidate_summary["approach_endpoint_signatures"] = candidate_approach_endpoint_signatures
        if approach_endpoint_mismatch_count:
            delta["approach_endpoint_signature_mismatch_count"] = approach_endpoint_mismatch_count
        teacher_crossing_signatures = _crossing_signatures(
            teacher_model,
            edge_map=edge_map,
            source_junction_id=teacher_junction_id or str(teacher_model.get("junction_id", "")),
            target_junction_id=candidate_junction_id or str(candidate_model.get("junction_id", "")),
        )
        candidate_crossing_signatures = _crossing_signatures(candidate_model)
        crossing_mismatch_count = _dict_mismatch_count(teacher_crossing_signatures, candidate_crossing_signatures)
        teacher_summary["crossing_signatures"] = teacher_crossing_signatures
        candidate_summary["crossing_signatures"] = candidate_crossing_signatures
        if crossing_mismatch_count:
            delta["crossing_signature_mismatch_count"] = crossing_mismatch_count
        teacher_crossing_geometry_signatures = _crossing_geometry_signatures(
            teacher_model,
            source_junction_id=teacher_junction_id or str(teacher_model.get("junction_id", "")),
            target_junction_id=candidate_junction_id or str(candidate_model.get("junction_id", "")),
        )
        candidate_crossing_geometry_signatures = _crossing_geometry_signatures(candidate_model)
        crossing_geometry_mismatch_count = _dict_mismatch_count(
            teacher_crossing_geometry_signatures, candidate_crossing_geometry_signatures
        )
        teacher_summary["crossing_geometry_signatures"] = teacher_crossing_geometry_signatures
        candidate_summary["crossing_geometry_signatures"] = candidate_crossing_geometry_signatures
        if crossing_geometry_mismatch_count:
            delta["crossing_geometry_signature_mismatch_count"] = crossing_geometry_mismatch_count
        teacher_walking_area_signatures = _walking_area_signatures(
            teacher_model,
            source_junction_id=teacher_junction_id or str(teacher_model.get("junction_id", "")),
            target_junction_id=candidate_junction_id or str(candidate_model.get("junction_id", "")),
        )
        candidate_walking_area_signatures = _walking_area_signatures(candidate_model)
        walking_area_mismatch_count = _dict_mismatch_count(
            teacher_walking_area_signatures, candidate_walking_area_signatures
        )
        teacher_summary["walking_area_signatures"] = teacher_walking_area_signatures
        candidate_summary["walking_area_signatures"] = candidate_walking_area_signatures
        if walking_area_mismatch_count:
            delta["walking_area_signature_mismatch_count"] = walking_area_mismatch_count
        teacher_internal_edge_signatures = _internal_edge_signatures(
            teacher_model,
            source_junction_id=teacher_junction_id or str(teacher_model.get("junction_id", "")),
            target_junction_id=candidate_junction_id or str(candidate_model.get("junction_id", "")),
        )
        candidate_internal_edge_signatures = _internal_edge_signatures(candidate_model)
        internal_edge_mismatch_count = _dict_mismatch_count(
            teacher_internal_edge_signatures, candidate_internal_edge_signatures
        )
        teacher_summary["internal_edge_signatures"] = teacher_internal_edge_signatures
        candidate_summary["internal_edge_signatures"] = candidate_internal_edge_signatures
        if internal_edge_mismatch_count:
            delta["internal_edge_signature_mismatch_count"] = internal_edge_mismatch_count
        teacher_internal_junction_signatures = _internal_junction_signatures(
            teacher_model,
            edge_map=edge_map,
            source_junction_id=teacher_junction_id or str(teacher_model.get("junction_id", "")),
            target_junction_id=candidate_junction_id or str(candidate_model.get("junction_id", "")),
        )
        candidate_internal_junction_signatures = _internal_junction_signatures(candidate_model)
        internal_junction_mismatch_count = _dict_mismatch_count(
            teacher_internal_junction_signatures, candidate_internal_junction_signatures
        )
        teacher_summary["internal_junction_signatures"] = teacher_internal_junction_signatures
        candidate_summary["internal_junction_signatures"] = candidate_internal_junction_signatures
        if internal_junction_mismatch_count:
            delta["internal_junction_signature_mismatch_count"] = internal_junction_mismatch_count
        teacher_internal_connection_signatures = _internal_connection_signatures(
            teacher_model,
            edge_map=edge_map,
            source_junction_id=teacher_junction_id or str(teacher_model.get("junction_id", "")),
            target_junction_id=candidate_junction_id or str(candidate_model.get("junction_id", "")),
        )
        candidate_internal_connection_signatures = _internal_connection_signatures(candidate_model)
        internal_connection_mismatch_count = _dict_mismatch_count(
            teacher_internal_connection_signatures, candidate_internal_connection_signatures
        )
        teacher_summary["internal_connection_signatures"] = teacher_internal_connection_signatures
        candidate_summary["internal_connection_signatures"] = candidate_internal_connection_signatures
        if internal_connection_mismatch_count:
            delta["internal_connection_signature_mismatch_count"] = internal_connection_mismatch_count
    return {
        "teacher": teacher_summary,
        "candidate": candidate_summary,
        "delta": delta,
    }

def _hybrid_osm_approach_authority_policy(
    raw_semantic_gate: dict[str, Any],
    *,
    replay_target_internal_subgraph: bool,
    preserve_teacher_lane_shapes: bool,
    edge_map: dict[str, str],
    lane_patch: dict[str, Any],
    target_internal_replay: dict[str, Any],
    tls_movement_parity: dict[str, Any],
    pedestrian_crossing_parity: dict[str, Any],
) -> dict[str, Any]:
    """Allow a deliberate OSM-approach/official-core authority split.

    Strict teacher parity remains the default.  The hybrid policy is active
    only when the caller explicitly preserves OSM lane shapes while replaying
    the complete teacher internal subgraph.  It may waive only the expected
    approach-edge and remote-endpoint signature deltas; every lane count,
    movement, internal/via path, TLS/linkIndex, pedestrian crossing, and mapped
    boundary invariant must still match.
    """

    active = replay_target_internal_subgraph and not preserve_teacher_lane_shapes
    if not active:
        return {
            "schema": "torii.hybrid_osm_approach_authority_policy.v1",
            "status": "not_applied",
            "policy": "strict_teacher_parity",
            "effective_semantic_gate": dict(raw_semantic_gate),
            "waived_raw_failures": [],
            "invariant_failures": [],
        }

    mapped_pairs = {
        str(teacher_edge): str(candidate_edge)
        for teacher_edge, candidate_edge in edge_map.items()
        if str(teacher_edge) and str(candidate_edge)
    }
    mapped_candidate_edges = set(mapped_pairs.values())
    invariant_failures: list[str] = []
    if not mapped_pairs:
        invariant_failures.append("edge_map_empty")
    if len(mapped_candidate_edges) != len(mapped_pairs):
        invariant_failures.append("edge_map_not_bijective")

    patched_pairs = {
        (str(item.get("teacher_edge_id", "")), str(item.get("candidate_edge_id", "")))
        for item in lane_patch.get("patched_edges", [])
        if isinstance(item, dict)
    }
    if lane_patch.get("status") != "pass":
        invariant_failures.append("lane_patch_not_pass")
    if patched_pairs != set(mapped_pairs.items()):
        invariant_failures.append("lane_patch_edge_map_mismatch")
    for field in (
        "added_missing_mapped_edge_count",
        "rebased_missing_mapped_edge_count",
        "endpoint_rewritten_missing_mapped_edge_count",
        "skipped_rebased_self_loop_edge_count",
        "pruned_boundary_edge_count",
    ):
        if int(lane_patch.get(field, 0) or 0):
            invariant_failures.append(f"lane_patch_{field}")
    if lane_patch.get("preserve_lane_shapes") is not False:
        invariant_failures.append("lane_patch_did_not_preserve_osm_shape_policy")

    preserved_endpoint_edges = {
        str(item.get("candidate_edge_id", ""))
        for item in target_internal_replay.get("preserved_mapped_boundary_endpoints", [])
        if isinstance(item, dict) and str(item.get("candidate_edge_id", ""))
    }
    blended_edges = {
        str(edge_id)
        for edge_id in target_internal_replay.get("blended_geometry_anchor_edge_ids", [])
        if str(edge_id)
    }
    if target_internal_replay.get("status") != "pass":
        invariant_failures.append("target_internal_replay_not_pass")
    if int(target_internal_replay.get("skipped_connection_count", 0) or 0):
        invariant_failures.append("target_internal_replay_skipped_connections")
    if target_internal_replay.get("copy_unmapped_boundary_edges") is not False:
        invariant_failures.append("target_internal_replay_copied_unmapped_boundary_edges")
    if target_internal_replay.get("preserve_mapped_boundary_endpoints") is not True:
        invariant_failures.append("mapped_boundary_endpoints_not_preserved")
    if target_internal_replay.get("blend_geometry_anchor_at_target") is not True:
        invariant_failures.append("local_target_geometry_blend_not_applied")
    if preserved_endpoint_edges != mapped_candidate_edges:
        invariant_failures.append("preserved_boundary_endpoint_set_mismatch")
    if blended_edges != mapped_candidate_edges:
        invariant_failures.append("blended_geometry_anchor_set_mismatch")
    if int(target_internal_replay.get("copied_boundary_edge_count", 0) or 0) != len(
        mapped_pairs
    ):
        invariant_failures.append("copied_boundary_edge_count_mismatch")
    if tls_movement_parity.get("status") != "pass":
        invariant_failures.append("tls_movement_parity_not_pass")
    if pedestrian_crossing_parity.get("status") != "pass":
        invariant_failures.append("pedestrian_crossing_parity_not_pass")

    allowed_fields = {
        "approach_edge_signature_mismatch_count",
        "approach_endpoint_signature_mismatch_count",
    }
    waived_raw_failures: list[dict[str, Any]] = []
    retained_raw_failures: list[dict[str, Any]] = []
    for failure in raw_semantic_gate.get("failures", []):
        if not isinstance(failure, dict):
            retained_raw_failures.append(
                {"report": "semantic_replay_gate", "field": "malformed_failure", "count": 1}
            )
            continue
        field = str(failure.get("field", ""))
        count = int(failure.get("count", 0) or 0)
        if (
            failure.get("report") == "parity"
            and field in allowed_fields
            and count == len(mapped_pairs)
        ):
            waived_raw_failures.append(dict(failure))
        else:
            retained_raw_failures.append(dict(failure))

    effective_failures = [
        *retained_raw_failures,
        *(
            {
                "report": "hybrid_osm_approach_authority_policy",
                "field": failure,
                "count": 1,
            }
            for failure in invariant_failures
        ),
    ]
    effective_gate = {
        "status": "fail" if effective_failures else "pass",
        "failures": effective_failures,
    }
    return {
        "schema": "torii.hybrid_osm_approach_authority_policy.v1",
        "status": "pass" if not effective_failures else "fail",
        "policy": "osm_remote_approaches_official_internal_core",
        "mapped_approach_edge_count": len(mapped_pairs),
        "mapped_candidate_edge_ids": sorted(mapped_candidate_edges),
        "waived_raw_failures": waived_raw_failures,
        "retained_raw_failures": retained_raw_failures,
        "invariant_failures": invariant_failures,
        "effective_semantic_gate": effective_gate,
    }

def _teacher_guided_semantics_gate(parity: dict[str, Any], **reports: dict[str, Any] | None) -> dict[str, object]:
    failures: list[dict[str, object]] = []
    for field, count in (parity.get("delta", {}) if isinstance(parity.get("delta"), dict) else {}).items():
        if isinstance(count, int) and count != 0:
            failures.append({"report": "parity", "field": str(field), "count": count})

    target_internal_replay = reports.get("target_internal_replay")
    internal_replay_complete = (
        isinstance(target_internal_replay, dict)
        and target_internal_replay.get("status") == "pass"
        and int(target_internal_replay.get("skipped_connection_count", 0) or 0) == 0
    )
    for report_name, report in reports.items():
        if not isinstance(report, dict):
            continue
        for field in (
            "skipped_pedestrian_connection_count",
            "skipped_vehicle_connection_count",
            "skipped_connection_count",
            "removed_stale_replaced_edge_connection_count",
        ):
            if internal_replay_complete and report_name in {"pedestrian_ring", "vehicle_connection_attrs"}:
                continue
            count = (
                _blocking_removed_stale_connection_count(report)
                if field == "removed_stale_replaced_edge_connection_count"
                else int(report.get(field, 0) or 0)
            )
            if count:
                failures.append({"report": report_name, "field": field, "count": count})

    return {"status": "fail" if failures else "pass", "failures": failures}

def _blocking_removed_stale_connection_count(report: dict[str, Any]) -> int:
    count = int(report.get("removed_stale_replaced_edge_connection_count", 0) or 0)
    removed = report.get("removed_stale_replaced_edge_connections", [])
    if not isinstance(removed, list):
        return count
    copied_boundary_edges = {
        str(item)
        for field in ("copied_boundary_edges", "copied_boundary_candidate_edges")
        for item in report.get(field, []) or []
        if str(item)
    }
    blocking = [
        connection
        for connection in removed
        if isinstance(connection, dict)
        and not _connection_touches_walkingarea_internal(connection)
        and not _connection_touches_any_edge(connection, copied_boundary_edges)
    ]
    return len(blocking)

def _blocking_removed_stale_boundary_connection_count(report: dict[str, Any]) -> int:
    count = int(report.get("removed_stale_boundary_edge_connection_count", 0) or 0)
    removed = report.get("removed_stale_boundary_edge_connections", [])
    if not isinstance(removed, list):
        return count
    return sum(
        1
        for connection in removed
        if isinstance(connection, dict) and str(connection.get("dir", "")).lower() != TURNAROUND_DIR
    )

def _connection_touches_walkingarea_internal(connection: dict[str, Any]) -> bool:
    return any(
        ref.startswith(":") and "_w" in ref
        for ref in (str(connection.get(field, "")) for field in ("from", "to", "via"))
    )

def _connection_touches_any_edge(connection: dict[str, Any], edge_ids: set[str]) -> bool:
    return bool(edge_ids) and any(str(connection.get(field, "")) in edge_ids for field in ("from", "to"))

def _semantic_layer_gates(
    semantic_gate: dict[str, Any],
    tls_movement_parity: dict[str, Any],
    pedestrian_crossing_parity: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    layers: dict[str, dict[str, Any]] = {
        name: {"status": "pass", "failure_count": 0, "failures": []}
        for name in ("topology", "movement_tls", "pedestrian_bike", "internal", "uncategorized")
    }
    for failure in semantic_gate.get("failures", []) if isinstance(semantic_gate, dict) else []:
        if not isinstance(failure, dict):
            continue
        layers[_semantic_layer_for_field(str(failure.get("field", "")))]["failures"].append(dict(failure))
    if isinstance(tls_movement_parity, dict) and tls_movement_parity.get("status") != "pass":
        layers["movement_tls"]["failures"].append(
            {"report": "tls_movement_parity", "field": "status", "count": 1}
        )
    if isinstance(pedestrian_crossing_parity, dict) and pedestrian_crossing_parity.get("status") != "pass":
        layers["pedestrian_bike"]["failures"].append(
            {
                "report": "pedestrian_crossing_parity",
                "field": "status",
                "count": _pedestrian_crossing_delta_count(pedestrian_crossing_parity),
            }
        )
    for layer in layers.values():
        layer["failure_count"] = len(layer["failures"])
        layer["status"] = "fail" if layer["failure_count"] else "pass"
    return layers

def _semantic_layer_for_field(field: str) -> str:
    if field.startswith(("crossing", "walking")) or "pedestrian" in field:
        return "pedestrian_bike"
    if field.startswith(("internal", "request")):
        return "internal"
    if field.startswith(("tl_", "controlled_", "vehicle_connection", "vehicle_movement")):
        return "movement_tls"
    if field.startswith("removed_stale_replaced_edge_connection"):
        return "topology"
    if field.startswith(("approach", "junction", "incoming_vehicle_edge", "outgoing_vehicle_edge")):
        return "topology"
    return "uncategorized"

def _pedestrian_crossing_delta_count(report: dict[str, Any]) -> int:
    count = 0
    for field in (
        "teacher_only_normalized_edge_signatures",
        "candidate_only_normalized_edge_signatures",
        "teacher_only_normalized_connection_signatures",
        "candidate_only_normalized_connection_signatures",
    ):
        values = report.get(field, [])
        count += len(values) if isinstance(values, list) else 0
    return max(1, count)

def _teacher_parity_summary(model: dict[str, Any]) -> dict[str, object]:
    summary = dict(model.get("summary", {}) if isinstance(model.get("summary"), dict) else {})
    traffic_light = model.get("traffic_light", {})
    attributes = traffic_light.get("attributes", {}) if isinstance(traffic_light, dict) else {}
    phases = traffic_light.get("phases", []) if isinstance(traffic_light, dict) else []
    phase_states = [str(phase.get("state", "")) for phase in phases if isinstance(phase, dict)]
    requests = model.get("requests", []) if isinstance(model.get("requests"), list) else []
    vehicle_connections = model.get("vehicle_connections", []) if isinstance(model.get("vehicle_connections"), list) else []
    pedestrian_connections = model.get("pedestrian_connections", []) if isinstance(model.get("pedestrian_connections"), list) else []
    incoming_count = int(summary.get("incoming_vehicle_edge_count", 0) or 0)
    outgoing_count = int(summary.get("outgoing_vehicle_edge_count", 0) or 0)
    vehicle_connection_count = int(summary.get("vehicle_connection_count", 0) or 0)
    expected_vehicle_movements = incoming_count * outgoing_count
    summary["vehicle_movement_matrix_expected_count"] = expected_vehicle_movements
    summary["vehicle_movement_matrix_missing_count"] = max(0, expected_vehicle_movements - vehicle_connection_count)
    target_tls_id = str(attributes.get("id", "") or model.get("junction_id", ""))
    summary["tl_type"] = str(attributes.get("type", "")) if isinstance(attributes, dict) else ""
    summary["tl_programID"] = str(attributes.get("programID", "")) if isinstance(attributes, dict) else ""
    summary["tl_offset"] = str(attributes.get("offset", "")) if isinstance(attributes, dict) else ""
    summary["tl_phase_state_lengths"] = sorted({len(state) for state in phase_states})
    summary["tl_phase_signatures"] = _tl_phase_signatures(phases)
    summary["request_signatures"] = _request_signatures(requests)
    summary["controlled_vehicle_link_count"] = _controlled_link_count(vehicle_connections, target_tls_id)
    summary["controlled_pedestrian_link_count"] = _controlled_link_count(pedestrian_connections, target_tls_id)
    summary["controlled_link_count"] = summary["controlled_vehicle_link_count"] + summary["controlled_pedestrian_link_count"]
    summary.update(_controlled_link_index_stats(vehicle_connections + pedestrian_connections, target_tls_id))
    return summary

def _model_tls_id(model: dict[str, Any], *, fallback: str) -> str:
    traffic_light = model.get("traffic_light", {})
    attributes = traffic_light.get("attributes", {}) if isinstance(traffic_light, dict) else {}
    return str(attributes.get("id", "") or fallback)

def _controlled_link_count(connections: list[object], tls_id: str) -> int:
    return sum(
        1
        for connection in connections
        if isinstance(connection, dict) and connection.get("tl") == tls_id and connection.get("linkIndex")
    )

def _controlled_link_index_stats(connections: list[object], tls_id: str) -> dict[str, int]:
    link_indexes = Counter(
        str(connection["linkIndex"])
        for connection in connections
        if isinstance(connection, dict) and connection.get("tl") == tls_id and connection.get("linkIndex")
    )
    numeric_indexes = []
    for link_index in link_indexes:
        try:
            numeric_indexes.append(int(link_index))
        except ValueError:
            continue
    return {
        "controlled_link_index_count": len(link_indexes),
        "controlled_link_index_span": max(numeric_indexes) + 1 if numeric_indexes else 0,
        "controlled_duplicate_link_index_count": sum(1 for count in link_indexes.values() if count > 1),
    }

def _tl_phase_signatures(phases: list[object]) -> list[str]:
    fields = ("state", "duration", "minDur", "maxDur", "next")
    return [
        "|".join(f"{field}={phase.get(field, '')}" for field in fields)
        for phase in phases
        if isinstance(phase, dict)
    ]

def _request_signatures(requests: list[object]) -> list[str]:
    fields = ("index", "response", "foes", "cont")
    return [
        "|".join(f"{field}={request.get(field, '')}" for field in fields)
        for request in requests
        if isinstance(request, dict)
    ]

def _controlled_vehicle_link_signatures(
    model: dict[str, Any],
    *,
    edge_map: dict[str, str] | None = None,
    source_junction_id: str = "",
    target_junction_id: str = "",
) -> dict[str, str]:
    return _controlled_link_signatures(
        model,
        "vehicle_connections",
        edge_map=edge_map,
        source_junction_id=source_junction_id,
        target_junction_id=target_junction_id,
    )

def _controlled_pedestrian_link_signatures(
    model: dict[str, Any],
    *,
    edge_map: dict[str, str] | None = None,
    source_junction_id: str = "",
    target_junction_id: str = "",
) -> dict[str, str]:
    return _controlled_link_signatures(
        model,
        "pedestrian_connections",
        edge_map=edge_map,
        source_junction_id=source_junction_id,
        target_junction_id=target_junction_id,
    )

def _controlled_link_signatures(
    model: dict[str, Any],
    connection_key: str,
    *,
    edge_map: dict[str, str] | None = None,
    source_junction_id: str = "",
    target_junction_id: str = "",
) -> dict[str, str]:
    traffic_light = model.get("traffic_light", {})
    attributes = traffic_light.get("attributes", {}) if isinstance(traffic_light, dict) else {}
    tls_id = str(attributes.get("id", "") or model.get("junction_id", "")) if isinstance(attributes, dict) else ""
    connections = model.get(connection_key, []) if isinstance(model.get(connection_key), list) else []
    origin_x, origin_y = _model_junction_origin(model)
    signatures_by_link_index: dict[str, list[str]] = {}
    for connection in connections:
        if not isinstance(connection, dict) or connection.get("tl") != tls_id or not connection.get("linkIndex"):
            continue
        link_index = str(connection["linkIndex"])
        signatures_by_link_index.setdefault(link_index, []).append(
            _vehicle_connection_signature(
                connection,
                edge_map=edge_map,
                source_junction_id=source_junction_id,
                target_junction_id=target_junction_id,
                origin_x=origin_x,
                origin_y=origin_y,
            )
        )
    return {
        link_index: _controlled_link_signature_group(signatures)
        for link_index, signatures in sorted(signatures_by_link_index.items())
    }

def _controlled_link_signature_group(signatures: list[str]) -> str:
    if len(signatures) == 1:
        return signatures[0]
    counts = Counter(signatures)
    return " || ".join(f"{counts[signature]}x {signature}" for signature in sorted(counts))

def _uncontrolled_pedestrian_connection_signatures(
    model: dict[str, Any],
    *,
    edge_map: dict[str, str] | None = None,
    source_junction_id: str = "",
    target_junction_id: str = "",
) -> dict[str, str]:
    connections = model.get("pedestrian_connections", []) if isinstance(model.get("pedestrian_connections"), list) else []
    counts: Counter[str] = Counter()
    for connection in connections:
        if not isinstance(connection, dict):
            continue
        if connection.get("tl") and connection.get("linkIndex"):
            continue
        counts.update(
            [
                _vehicle_connection_signature(
                    connection,
                    edge_map=edge_map,
                    source_junction_id=source_junction_id,
                    target_junction_id=target_junction_id,
                )
            ]
        )
    return {signature: str(counts[signature]) for signature in sorted(counts)}

def _junction_signature(
    model: dict[str, Any],
    *,
    edge_map: dict[str, str] | None = None,
    source_junction_id: str = "",
    target_junction_id: str = "",
) -> str:
    junction = model.get("junction", {}) if isinstance(model.get("junction"), dict) else {}
    inc_lanes = _mapped_lane_refs(str(junction.get("incLanes", "")), edge_map, source_junction_id, target_junction_id)
    int_lanes = _mapped_lane_refs(str(junction.get("intLanes", "")), edge_map, source_junction_id, target_junction_id)
    shape = _relative_shape(
        str(junction.get("shape", "")),
        str(junction.get("x", "")),
        str(junction.get("y", "")),
    )
    return f"type={junction.get('type', '')}|incLanes={inc_lanes}|intLanes={int_lanes}|shape={shape}"

def _approach_edge_signatures(
    model: dict[str, Any],
    *,
    edge_map: dict[str, str] | None = None,
    source_junction_id: str = "",
    target_junction_id: str = "",
) -> dict[str, str]:
    approaches = model.get("approaches", {}) if isinstance(model.get("approaches"), dict) else {}
    origin_x, origin_y = _model_junction_origin(model)
    origin_x = origin_x or "0"
    origin_y = origin_y or "0"
    signatures: dict[str, str] = {}
    for direction in ("incoming", "outgoing"):
        for edge in approaches.get(direction, []) or []:
            if not isinstance(edge, dict):
                continue
            edge_id = _mapped_endpoint(str(edge.get("edge_id", "")), edge_map)
            if not edge_id:
                continue
            signatures[f"{direction}:{edge_id}"] = _approach_edge_signature(
                edge,
                source_junction_id=source_junction_id,
                target_junction_id=target_junction_id,
                origin_x=origin_x,
                origin_y=origin_y,
            )
    return signatures

def _approach_endpoint_signatures(
    model: dict[str, Any],
    *,
    edge_map: dict[str, str] | None = None,
    source_junction_id: str = "",
    target_junction_id: str = "",
) -> dict[str, str]:
    approaches = model.get("approaches", {}) if isinstance(model.get("approaches"), dict) else {}
    signatures: dict[str, str] = {}
    for direction in ("incoming", "outgoing"):
        for edge in approaches.get(direction, []) or []:
            if not isinstance(edge, dict):
                continue
            edge_id = _mapped_endpoint(str(edge.get("edge_id", "")), edge_map)
            if not edge_id:
                continue
            source = _mapped_junction_ref(str(edge.get("from", "")), source_junction_id, target_junction_id)
            target = _mapped_junction_ref(str(edge.get("to", "")), source_junction_id, target_junction_id)
            signatures[f"{direction}:{edge_id}"] = f"from={source}|to={target}"
    return signatures

def _approach_endpoint_rebuild_plan(
    teacher_model: dict[str, Any],
    candidate_model: dict[str, Any],
    *,
    edge_map: dict[str, str] | None = None,
    teacher_junction_id: str = "",
    candidate_junction_id: str = "",
    candidate_junction_ids: set[str] | None = None,
) -> dict[str, Any]:
    candidate_junction_ids = candidate_junction_ids or set()
    edge_rebuilds = []
    for direction in ("incoming", "outgoing"):
        candidate_by_edge = {str(edge.get("edge_id", "")): edge for edge in _approaches(candidate_model, direction)}
        for teacher_edge in _approaches(teacher_model, direction):
            mapped_edge_id = _mapped_endpoint(str(teacher_edge.get("edge_id", "")), edge_map)
            candidate_edge = candidate_by_edge.get(mapped_edge_id)
            if not mapped_edge_id or candidate_edge is None:
                continue
            candidate_from = str(candidate_edge.get("from", ""))
            candidate_to = str(candidate_edge.get("to", ""))
            desired_from = _mapped_junction_ref(
                str(teacher_edge.get("from", "")), teacher_junction_id, candidate_junction_id
            )
            desired_to = _mapped_junction_ref(str(teacher_edge.get("to", "")), teacher_junction_id, candidate_junction_id)
            if (candidate_from, candidate_to) == (desired_from, desired_to):
                continue
            desired_external = {
                endpoint for endpoint in (desired_from, desired_to) if endpoint and endpoint != candidate_junction_id
            }
            candidate_external = {
                endpoint for endpoint in (candidate_from, candidate_to) if endpoint and endpoint != candidate_junction_id
            }
            missing_desired = sorted(endpoint for endpoint in desired_external if endpoint not in candidate_junction_ids)
            edge_rebuilds.append(
                {
                    "approach_key": f"{direction}:{mapped_edge_id}",
                    "edge_id": mapped_edge_id,
                    "direction": direction,
                    "candidate_from": candidate_from,
                    "candidate_to": candidate_to,
                    "desired_from": desired_from,
                    "desired_to": desired_to,
                    "affected_neighbor_junction_ids": sorted(candidate_external | desired_external),
                    "missing_desired_endpoint_ids": missing_desired,
                    "unsafe_direct_rewrite": True,
                    "reason": "endpoint change affects neighboring junction connections and tlLogic; rebuild expanded scope",
                }
            )

    affected = sorted({junction for item in edge_rebuilds for junction in item["affected_neighbor_junction_ids"]})
    missing = sorted({junction for item in edge_rebuilds for junction in item["missing_desired_endpoint_ids"]})
    return {
        "status": "review" if edge_rebuilds else "pass",
        "claim_status": "diagnostic-demo",
        "recommended_action": "expand_rebuild_scope" if edge_rebuilds else "none",
        "mismatch_count": len(edge_rebuilds),
        "affected_neighbor_junction_ids": affected,
        "missing_desired_endpoint_ids": missing,
        "edge_rebuilds": edge_rebuilds,
    }

def _approach_edge_signature(
    edge: dict[str, Any],
    *,
    source_junction_id: str = "",
    target_junction_id: str = "",
    origin_x: str = "0",
    origin_y: str = "0",
) -> str:
    lanes = edge.get("lanes", []) if isinstance(edge.get("lanes"), list) else []
    lane_signatures = [
        f"{lane.get('index', '')}:{lane.get('allow', '')}:{lane.get('disallow', '')}:"
        f"{lane.get('speed', '')}:{_lane_length_signature(lane)}:{lane.get('width', '')}:"
        f"{_relative_shape(str(lane.get('shape', '')), origin_x, origin_y)}:"
        f"{_relative_shape(str(lane.get('outlineShape', '')), origin_x, origin_y)}"
        for lane in lanes
        if isinstance(lane, dict)
    ]
    source = _mapped_junction_ref(str(edge.get("from", "")), source_junction_id, target_junction_id)
    target = _mapped_junction_ref(str(edge.get("to", "")), source_junction_id, target_junction_id)
    return (
        f"from={source}|to={target}|type={edge.get('type', '')}|"
        f"function={edge.get('function', '')}|lanes={' '.join(lane_signatures)}"
    )

def _lane_length_signature(lane: dict[str, Any]) -> str:
    if str(lane.get("shape", "")).strip():
        return ""
    return str(lane.get("length", ""))

def _mapped_junction_ref(value: str, source_junction_id: str, target_junction_id: str) -> str:
    if source_junction_id and target_junction_id and value == source_junction_id:
        return target_junction_id
    return value

def _relative_shape(shape: str, x: str, y: str) -> str:
    if not shape or not x or not y:
        return shape
    try:
        origin_x = float(x)
        origin_y = float(y)
    except ValueError:
        return shape
    translated = []
    for point in shape.split():
        coords = point.split(",")
        if len(coords) < 2:
            translated.append(point)
            continue
        try:
            coords[0] = _format_xy(float(coords[0]) - origin_x)
            coords[1] = _format_xy(float(coords[1]) - origin_y)
        except ValueError:
            translated.append(point)
            continue
        translated.append(",".join(coords))
    return " ".join(translated)

def _internal_connection_signatures(
    model: dict[str, Any],
    *,
    edge_map: dict[str, str] | None = None,
    source_junction_id: str = "",
    target_junction_id: str = "",
) -> dict[str, str]:
    connections = model.get("internal_connections", []) if isinstance(model.get("internal_connections"), list) else []
    counts: Counter[str] = Counter(
        _vehicle_connection_signature(
            connection,
            edge_map=edge_map,
            source_junction_id=source_junction_id,
            target_junction_id=target_junction_id,
        )
        for connection in connections
        if isinstance(connection, dict)
    )
    return {signature: str(counts[signature]) for signature in sorted(counts)}

def _vehicle_connection_signature(
    connection: dict[str, Any],
    *,
    edge_map: dict[str, str] | None,
    source_junction_id: str,
    target_junction_id: str,
    origin_x: str = "",
    origin_y: str = "",
) -> str:
    source = _mapped_internal_ref(
        _mapped_endpoint(str(connection.get("from", "")), edge_map), source_junction_id, target_junction_id
    )
    target = _mapped_internal_ref(
        _mapped_endpoint(str(connection.get("to", "")), edge_map), source_junction_id, target_junction_id
    )
    via = _mapped_internal_ref(str(connection.get("via", "")), source_junction_id, target_junction_id)
    return (
        f"from={source}|to={target}|fromLane={connection.get('fromLane', '')}|"
        f"toLane={connection.get('toLane', '')}|dir={connection.get('dir', '')}|"
        f"state={connection.get('state', '')}|via={via}|pass={connection.get('pass', '')}|"
        f"uncontrolled={connection.get('uncontrolled', '')}|allow={connection.get('allow', '')}|"
        f"disallow={connection.get('disallow', '')}|keepClear={connection.get('keepClear', '')}|"
        f"contPos={connection.get('contPos', '')}|linkIndex2={connection.get('linkIndex2', '')}|"
        f"shape={_relative_shape(str(connection.get('shape', '')), origin_x, origin_y)}"
    )

def _crossing_signatures(
    model: dict[str, Any],
    *,
    edge_map: dict[str, str] | None = None,
    source_junction_id: str = "",
    target_junction_id: str = "",
) -> dict[str, str]:
    crossings = model.get("crossings", []) if isinstance(model.get("crossings"), list) else []
    signatures: dict[str, str] = {}
    for crossing in crossings:
        if not isinstance(crossing, dict):
            continue
        crossing_id = _mapped_internal_ref(str(crossing.get("edge_id", "")), source_junction_id, target_junction_id)
        if not crossing_id:
            continue
        edges = sorted(_mapped_endpoint(str(edge), edge_map) for edge in crossing.get("crossingEdges", []) or [])
        signatures[crossing_id] = f"edges={' '.join(edges)}"
    return signatures

def _crossing_geometry_signatures(
    model: dict[str, Any],
    *,
    source_junction_id: str = "",
    target_junction_id: str = "",
) -> dict[str, str]:
    crossings = model.get("crossings", []) if isinstance(model.get("crossings"), list) else []
    origin_x, origin_y = _model_junction_origin(model)
    signatures: dict[str, str] = {}
    for edge in crossings:
        if not isinstance(edge, dict):
            continue
        edge_id = _mapped_internal_ref(str(edge.get("edge_id", "")), source_junction_id, target_junction_id)
        if not edge_id:
            continue
        signatures[edge_id] = _internal_edge_signature(edge, origin_x=origin_x, origin_y=origin_y)
    return signatures

def _internal_edge_signatures(
    model: dict[str, Any],
    *,
    source_junction_id: str = "",
    target_junction_id: str = "",
) -> dict[str, str]:
    internal_edges = model.get("internal_edges", []) if isinstance(model.get("internal_edges"), list) else []
    origin_x, origin_y = _model_junction_origin(model)
    signatures: dict[str, str] = {}
    for edge in internal_edges:
        if not isinstance(edge, dict):
            continue
        edge_id = _mapped_internal_ref(str(edge.get("edge_id", "")), source_junction_id, target_junction_id)
        if not edge_id:
            continue
        signatures[edge_id] = _internal_edge_signature(edge, origin_x=origin_x, origin_y=origin_y)
    return signatures

def _walking_area_signatures(
    model: dict[str, Any],
    *,
    source_junction_id: str = "",
    target_junction_id: str = "",
) -> dict[str, str]:
    walking_areas = model.get("walking_areas", []) if isinstance(model.get("walking_areas"), list) else []
    origin_x, origin_y = _model_junction_origin(model)
    signatures: dict[str, str] = {}
    for edge in walking_areas:
        if not isinstance(edge, dict):
            continue
        edge_id = _mapped_internal_ref(str(edge.get("edge_id", "")), source_junction_id, target_junction_id)
        if not edge_id:
            continue
        signatures[edge_id] = _internal_edge_signature(edge, origin_x=origin_x, origin_y=origin_y)
    return signatures

def _internal_edge_signature(edge: dict[str, Any], *, origin_x: str = "", origin_y: str = "") -> str:
    lanes = edge.get("lanes", []) if isinstance(edge.get("lanes"), list) else []
    lane_signatures = [
        f"{lane.get('index', '')}:{lane.get('allow', '')}:{lane.get('disallow', '')}:"
        f"{lane.get('speed', '')}:{lane.get('length', '')}:{lane.get('width', '')}:"
        f"{_relative_shape(str(lane.get('shape', '')), origin_x, origin_y)}:"
        f"{_relative_shape(str(lane.get('outlineShape', '')), origin_x, origin_y)}"
        for lane in lanes
        if isinstance(lane, dict)
    ]
    return f"function={edge.get('function', '')}|lanes={' '.join(lane_signatures)}"

def _model_junction_origin(model: dict[str, Any]) -> tuple[str, str]:
    junction = model.get("junction", {}) if isinstance(model.get("junction"), dict) else {}
    return str(junction.get("x", "")), str(junction.get("y", ""))

def _model_shape_delta(teacher_model: dict[str, Any], candidate_model: dict[str, Any]) -> tuple[float, float] | None:
    teacher_x, teacher_y = _model_junction_origin(teacher_model)
    candidate_x, candidate_y = _model_junction_origin(candidate_model)
    try:
        return float(candidate_x) - float(teacher_x), float(candidate_y) - float(teacher_y)
    except ValueError:
        return None

def _internal_junction_signatures(
    model: dict[str, Any],
    *,
    edge_map: dict[str, str] | None = None,
    source_junction_id: str = "",
    target_junction_id: str = "",
) -> dict[str, str]:
    junctions = model.get("internal_junctions", []) if isinstance(model.get("internal_junctions"), list) else []
    origin_x, origin_y = _model_junction_origin(model)
    signatures: dict[str, str] = {}
    for junction in junctions:
        if not isinstance(junction, dict):
            continue
        junction_id = _mapped_internal_ref(str(junction.get("junction_id", "")), source_junction_id, target_junction_id)
        if not junction_id:
            continue
        inc_lanes = _mapped_lane_refs(str(junction.get("incLanes", "")), edge_map, source_junction_id, target_junction_id)
        int_lanes = _mapped_lane_refs(str(junction.get("intLanes", "")), edge_map, source_junction_id, target_junction_id)
        shape = _relative_shape(str(junction.get("shape", "")), origin_x, origin_y)
        custom_shape = _relative_shape(str(junction.get("customShape", "")), origin_x, origin_y)
        signatures[junction_id] = (
            f"type={junction.get('type', '')}|incLanes={inc_lanes}|"
            f"intLanes={int_lanes}|shape={shape}|customShape={custom_shape}"
        )
    return signatures

def _mapped_lane_refs(
    value: str,
    edge_map: dict[str, str] | None,
    source_junction_id: str,
    target_junction_id: str,
) -> str:
    return " ".join(
        _mapped_lane_ref(lane, edge_map, source_junction_id, target_junction_id)
        for lane in value.split()
    )

def _mapped_lane_ref(
    lane_id: str,
    edge_map: dict[str, str] | None,
    source_junction_id: str,
    target_junction_id: str,
) -> str:
    mapped = _mapped_internal_ref(lane_id, source_junction_id, target_junction_id)
    if mapped != lane_id or "_" not in lane_id:
        return mapped
    edge_id, lane_index = lane_id.rsplit("_", 1)
    mapped_edge = _mapped_endpoint(edge_id, edge_map)
    return f"{mapped_edge}_{lane_index}"

def _mapped_endpoint(edge_id: str, edge_map: dict[str, str] | None) -> str:
    return edge_map.get(edge_id, edge_id) if edge_map is not None else edge_id

def _net_junction_ids(net_file: Path) -> set[str]:
    return {
        junction.attrib["id"]
        for junction in ET.parse(net_file).getroot().findall("junction")
        if junction.attrib.get("id")
    }

def _target_internal_replay_input_file(
    *,
    vehicle_attrs_net_file: Path,
    candidate_net_file: Path,
    junction_id: str,
) -> Path:
    if junction_id in _net_junction_ids(vehicle_attrs_net_file):
        return vehicle_attrs_net_file
    if junction_id in _net_junction_ids(candidate_net_file):
        return candidate_net_file
    return vehicle_attrs_net_file

def _unique_connections_by_key(root: ET.Element) -> tuple[dict[tuple[str, str, str, str], ET.Element], set[tuple[str, str, str, str]]]:
    connections_by_key: dict[tuple[str, str, str, str], list[ET.Element]] = {}
    for connection in root.findall("connection"):
        key = _connection_key(connection)
        connections_by_key.setdefault(key, []).append(connection)
    duplicate_keys = {key for key, connections in connections_by_key.items() if len(connections) > 1}
    return (
        {key: connections[0] for key, connections in connections_by_key.items() if len(connections) == 1},
        duplicate_keys,
    )

def _connection_key(connection: ET.Element) -> tuple[str, str, str, str]:
    return (
        connection.attrib.get("from", ""),
        connection.attrib.get("to", ""),
        connection.attrib.get("fromLane", "0"),
        connection.attrib.get("toLane", "0"),
    )

def _connection_key_record(key: tuple[str, str, str, str]) -> dict[str, str]:
    return {"from": key[0], "to": key[1], "fromLane": key[2], "toLane": key[3]}

def _controlled_tls_connection_count(root: ET.Element) -> int:
    return sum(
        1
        for connection in root.findall("connection")
        if connection.attrib.get("tl") and connection.attrib.get("linkIndex")
    )

def _tllogic_min_state_length_by_id(root: ET.Element) -> dict[str, int]:
    lengths_by_id = {}
    for tl_logic in root.findall("tlLogic"):
        tls_id = tl_logic.attrib.get("id", "")
        lengths = [
            len(phase.attrib.get("state", ""))
            for phase in tl_logic.findall("phase")
            if phase.attrib.get("state")
        ]
        if tls_id and lengths:
            lengths_by_id[tls_id] = min(lengths)
    return lengths_by_id

def _connection_link_indices_fit(connection: ET.Element, capacity: int | None) -> bool:
    if capacity is None:
        return False
    for attr in ("linkIndex", "linkIndex2"):
        value = connection.attrib.get(attr, "")
        if not value:
            continue
        try:
            if int(value) >= capacity:
                return False
        except ValueError:
            return False
    return True

def _record_linkindex_capacity_gap(
    gaps: dict[str, dict[str, object]],
    *,
    source_connection: ET.Element,
    source_tls_id: str,
    target_tls_id: str,
    capacity: int | None,
) -> None:
    record = gaps.setdefault(
        target_tls_id,
        {
            "target_tls": target_tls_id,
            "target_capacity": capacity if capacity is not None else 0,
            "max_required_link_index": 0,
            "skipped_connection_count": 0,
            "source_tls_ids": set(),
        },
    )
    record["skipped_connection_count"] = int(record["skipped_connection_count"]) + 1
    record["max_required_link_index"] = max(
        int(record["max_required_link_index"]),
        _connection_max_link_index(source_connection),
    )
    source_ids = record["source_tls_ids"]
    if isinstance(source_ids, set):
        source_ids.add(source_tls_id)

def _connection_max_link_index(connection: ET.Element) -> int:
    values = []
    for attr in ("linkIndex", "linkIndex2"):
        value = connection.attrib.get(attr, "")
        if value:
            try:
                values.append(int(value))
            except ValueError:
                pass
    return max(values) if values else 0

def _connection_link_indices(connection: ET.Element) -> set[int]:
    indices = set()
    for attr in ("linkIndex", "linkIndex2"):
        value = connection.attrib.get(attr, "")
        if value:
            try:
                indices.add(int(value))
            except ValueError:
                pass
    return indices

def _capacity_gap_records(gaps: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    records = []
    for record in gaps.values():
        max_required = int(record["max_required_link_index"])
        source_ids = record["source_tls_ids"]
        records.append(
            {
                "target_tls": str(record["target_tls"]),
                "target_capacity": int(record["target_capacity"]),
                "required_state_length": max_required + 1,
                "max_required_link_index": max_required,
                "skipped_connection_count": int(record["skipped_connection_count"]),
                "source_tls_ids": sorted(source_ids) if isinstance(source_ids, set) else [],
            }
        )
    return sorted(records, key=lambda item: (-int(item["skipped_connection_count"]), str(item["target_tls"])))

def _add_green_phases_for_links(
    root: ET.Element,
    indices_by_tls: dict[str, set[int]],
    *,
    add_yellow_phases: bool = False,
) -> dict[str, object]:
    added_by_tls = []
    added_count = 0
    added_yellow_by_tls = []
    added_yellow_count = 0
    for tl_logic in root.findall("tlLogic"):
        tls_id = tl_logic.attrib.get("id", "")
        indices = sorted(indices_by_tls.get(tls_id, set()))
        if not indices:
            continue
        phases = tl_logic.findall("phase")
        state_length = max((len(phase.attrib.get("state", "")) for phase in phases), default=0)
        added_for_tls = 0
        added_yellow_for_tls = 0
        for index in indices:
            if index < 0 or index >= state_length or _phase_has_green_for_index(phases, index):
                continue
            state = "r" * index + "G" + "r" * (state_length - index - 1)
            ET.SubElement(tl_logic, "phase", {"duration": "4", "state": state})
            added_for_tls += 1
            if add_yellow_phases:
                yellow_state = "r" * index + "y" + "r" * (state_length - index - 1)
                ET.SubElement(tl_logic, "phase", {"duration": "3", "state": yellow_state})
                added_yellow_for_tls += 1
        if added_for_tls:
            added_by_tls.append({"tls": tls_id, "added_green_phase_count": added_for_tls})
            added_count += added_for_tls
        if added_yellow_for_tls:
            added_yellow_by_tls.append({"tls": tls_id, "added_yellow_phase_count": added_yellow_for_tls})
            added_yellow_count += added_yellow_for_tls
    return {
        "added_green_phase_count": added_count,
        "added_green_phase_tllogic_count": len(added_by_tls),
        "added_green_phase_tllogics": added_by_tls,
        "added_yellow_phase_count": added_yellow_count,
        "added_yellow_phase_tllogic_count": len(added_yellow_by_tls),
        "added_yellow_phase_tllogics": added_yellow_by_tls,
    }

def _phase_has_green_for_index(phases: list[ET.Element], index: int) -> bool:
    return any(
        len(phase.attrib.get("state", "")) > index and phase.attrib.get("state", "")[index] in {"G", "g"}
        for phase in phases
    )

def _pad_tllogic_state_lengths(root: ET.Element, required_lengths: dict[str, int]) -> dict[str, object]:
    padded_tls = []
    padded_phases = 0
    if not required_lengths:
        return {"padded_tllogic_count": 0, "padded_tllogic_phase_count": 0, "padded_tllogics": []}
    for tl_logic in root.findall("tlLogic"):
        tls_id = tl_logic.attrib.get("id", "")
        required_length = required_lengths.get(tls_id, 0)
        if required_length <= 0:
            continue
        phase_count = 0
        for phase in tl_logic.findall("phase"):
            state = phase.attrib.get("state", "")
            if state and len(state) < required_length:
                phase.set("state", state + ("r" * (required_length - len(state))))
                phase_count += 1
        if phase_count:
            padded_tls.append({"tls": tls_id, "required_state_length": required_length, "padded_phase_count": phase_count})
            padded_phases += phase_count
    return {
        "padded_tllogic_count": len(padded_tls),
        "padded_tllogic_phase_count": padded_phases,
        "padded_tllogics": padded_tls,
    }

def _copy_referenced_tllogics(
    source_root: ET.Element,
    candidate_root: ET.Element,
    tls_ids: set[str],
) -> dict[str, object]:
    source_by_id = {
        tl_logic.attrib["id"]: tl_logic
        for tl_logic in source_root.findall("tlLogic")
        if tl_logic.attrib.get("id")
    }
    copied = 0
    replaced = 0
    missing: list[str] = []
    insert_index = _tl_logic_insert_index(candidate_root)
    for tls_id in sorted(tls_ids):
        source = source_by_id.get(tls_id)
        if source is None:
            missing.append(tls_id)
            continue
        replacement = copy.deepcopy(source)
        target = next(
            (tl_logic for tl_logic in candidate_root.findall("tlLogic") if tl_logic.attrib.get("id") == tls_id),
            None,
        )
        if target is None:
            candidate_root.insert(insert_index, replacement)
            insert_index += 1
            copied += 1
            continue
        target_index = list(candidate_root).index(target)
        candidate_root.remove(target)
        candidate_root.insert(target_index, replacement)
        replaced += 1
    return {
        "copied_tllogic_count": copied,
        "replaced_tllogic_count": replaced,
        "missing_source_tllogic_count": len(missing),
        "missing_source_tllogic_ids": missing,
    }

def _tl_logic_insert_index(root: ET.Element) -> int:
    children = list(root)
    for index, child in enumerate(children):
        if child.tag == "tlLogic":
            return index
    for index, child in enumerate(children):
        if child.tag == "connection":
            return index
    return len(children)

def _mapped_internal_ref(value: str, source_junction_id: str, target_junction_id: str) -> str:
    source_prefix = f":{source_junction_id}_"
    target_prefix = f":{target_junction_id}_"
    if source_junction_id and target_junction_id and value.startswith(source_prefix):
        return f"{target_prefix}{value[len(source_prefix):]}"
    return value

def _dict_mismatch_count(left: dict[str, str], right: dict[str, str]) -> int:
    return sum(1 for key in set(left) | set(right) if left.get(key) != right.get(key))

def _write_teacher_guided_report(path: Path, report: dict[str, object]) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["report_file"] = str(path)
    return report

def _failure(error: str) -> dict[str, object]:
    return {
        "status": "fail",
        "claim_status": "construction-invalid",
        "error": error,
    }

def _variant_exception_report(exc: Exception, junction_id: str) -> dict[str, object]:
    return {
        "status": "fail",
        "claim_status": "construction-invalid",
        "junction_id": junction_id,
        "reason": str(exc),
        "error": str(exc),
        "exception_type": type(exc).__name__,
    }


def build_rebuild_candidate(
    *,
    net_file: Path,
    junction_id: str,
    output_dir: Path,
    prefix: str = "junction_movement_rebuild",
    movement_exemplar: dict[str, Any] | None = None,
    slot_edge_map: dict[str, str] | None = None,
    teacher_edge_map: dict[str, str] | None = None,
) -> dict[str, object]:
    if not net_file.exists():
        return _failure(f"net file does not exist: {net_file}")
    output_dir.mkdir(parents=True, exist_ok=True)

    graph = build_movement_graph(net_file, junction_id)
    audit = audit_movement_graph(graph)
    review = write_movement_review(graph, audit, output_dir, prefix)
    signature = build_connection_signature(net_file, junction_id)
    signature_report = write_connection_signature(signature, output_dir, prefix)
    connections_file = output_dir / f"{prefix}.con.xml"
    summary_file = output_dir / f"{prefix}_rebuild_candidate.json"
    command_file = output_dir / f"{prefix}_netconvert.cmd.txt"
    variant_file = output_dir / f"{prefix}_rebuilt.net.xml"

    if movement_exemplar is not None and slot_edge_map is None and teacher_edge_map is not None:
        slot_edge_map = slot_edge_map_from_exemplar(movement_exemplar, teacher_edge_map)
    if movement_exemplar is not None and slot_edge_map is not None:
        emitted = materialize_exemplar_movement_signatures(movement_exemplar, slot_edge_map)
        emitted_pairs = {
            (str(movement.get("from_edge_id", "")), str(movement.get("to_edge_id", ""))) for movement in emitted
        }
        skipped = [
            movement
            for movement in graph.get("movements", []) or []
            if (str(movement.get("source_edge_id", "")), str(movement.get("target_edge_id", ""))) not in emitted_pairs
        ]
        movement_source = "exemplar_signatures"
    else:
        emitted = [movement for movement in graph.get("movements", []) or [] if _should_emit(movement)]
        skipped = [movement for movement in graph.get("movements", []) or [] if not _should_emit(movement)]
        movement_source = "movement_graph"
    _write_connections(connections_file, emitted)
    command = [
        "netconvert",
        "--sumo-net-file",
        str(net_file),
        "--connection-files",
        str(connections_file),
        "--output-file",
        str(variant_file),
    ]
    command_file.write_text(" ".join(command) + "\n", encoding="utf-8")

    report = {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "junction_id": junction_id,
        "net_file": str(net_file),
        "connections_file": str(connections_file),
        "variant_file": str(variant_file),
        "netconvert_command_file": str(command_file),
        "movement_review": review,
        "connection_signature": signature_report,
        "movement_audit_status": audit["status"],
        "movement_source": movement_source,
        "slot_edge_map": slot_edge_map or {},
        "emitted_connection_count": len(emitted),
        "skipped_movement_count": len(skipped),
        "review_policy": "run netconvert and inspect NetEdit connection mode before adoption",
    }
    summary_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["summary_file"] = str(summary_file)
    return report
def build_tls_connection_repair_variant(
    *,
    source_net_file: Path,
    candidate_net_file: Path,
    output_dir: Path,
    prefix: str = "tls_connection_repair",
    tls_id_map: dict[str, str] | None = None,
    copy_unmapped_tls: bool = True,
    require_target_link_index_capacity: bool = False,
    pad_mapped_tllogic_capacity: bool = False,
    add_green_phases_for_padded_links: bool = False,
    add_yellow_phases_for_generated_green: bool = False,
) -> dict[str, object]:
    if not source_net_file.exists():
        return _failure(f"source net file does not exist: {source_net_file}")
    if not candidate_net_file.exists():
        return _failure(f"candidate net file does not exist: {candidate_net_file}")

    source_net_file = source_net_file.resolve()
    candidate_net_file = candidate_net_file.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    variant_file = _stage_file(output_dir, prefix, "tls_connection_repaired.net.xml")
    summary_file = _stage_file(output_dir, prefix, "tls_connection_repair.json")

    source_root = ET.parse(source_net_file).getroot()
    candidate_tree = ET.parse(candidate_net_file)
    candidate_root = candidate_tree.getroot()
    tls_id_map = tls_id_map or {}
    candidate_tllogic_ids = {
        tl_logic.attrib["id"]
        for tl_logic in candidate_root.findall("tlLogic")
        if tl_logic.attrib.get("id")
    }
    target_tllogic_capacities = _tllogic_min_state_length_by_id(candidate_root)
    source_unique, source_duplicate_keys = _unique_connections_by_key(source_root)
    candidate_unique, candidate_duplicate_keys = _unique_connections_by_key(candidate_root)
    source_controlled = _controlled_tls_connection_count(source_root)
    candidate_controlled_before = _controlled_tls_connection_count(candidate_root)
    matched_connections = 0
    updated_connections = 0
    missing_candidate_connections = 0
    ambiguous_connections = 0
    skipped_unmapped_tls_connections = 0
    skipped_missing_mapped_tllogic_connections = 0
    skipped_invalid_mapped_linkindex_connections = 0
    invalid_mapped_linkindex_capacity_gaps: dict[str, dict[str, object]] = {}
    required_tllogic_lengths: dict[str, int] = {}
    padded_tllogic_link_indices: dict[str, set[int]] = {}
    copied_tls_ids: set[str] = set()
    updated_keys: list[dict[str, str]] = []

    for key, source_connection in sorted(source_unique.items()):
        tls_id = source_connection.attrib.get("tl", "")
        if not tls_id or not source_connection.attrib.get("linkIndex"):
            continue
        target_tls_id = tls_id_map.get(tls_id, tls_id)
        if tls_id not in tls_id_map and not copy_unmapped_tls:
            skipped_unmapped_tls_connections += 1
            continue
        if tls_id in tls_id_map and target_tls_id not in candidate_tllogic_ids:
            skipped_missing_mapped_tllogic_connections += 1
            continue
        if (
            require_target_link_index_capacity
            and tls_id in tls_id_map
            and not _connection_link_indices_fit(
                source_connection,
                target_tllogic_capacities.get(target_tls_id),
            )
        ):
            _record_linkindex_capacity_gap(
                invalid_mapped_linkindex_capacity_gaps,
                source_connection=source_connection,
                source_tls_id=tls_id,
                target_tls_id=target_tls_id,
                capacity=target_tllogic_capacities.get(target_tls_id),
            )
            capacity = target_tllogic_capacities.get(target_tls_id)
            if not pad_mapped_tllogic_capacity or capacity is None:
                skipped_invalid_mapped_linkindex_connections += 1
                continue
            required_tllogic_lengths[target_tls_id] = max(
                required_tllogic_lengths.get(target_tls_id, 0),
                _connection_max_link_index(source_connection) + 1,
            )
            padded_tllogic_link_indices.setdefault(target_tls_id, set()).update(_connection_link_indices(source_connection))
        if key in source_duplicate_keys or key in candidate_duplicate_keys:
            ambiguous_connections += 1
            continue
        candidate_connection = candidate_unique.get(key)
        if candidate_connection is None:
            missing_candidate_connections += 1
            continue
        matched_connections += 1
        before = dict(candidate_connection.attrib)
        for attr in TLS_CONNECTION_REPAIR_ATTRS:
            if attr in source_connection.attrib:
                candidate_connection.set(attr, source_connection.attrib[attr])
            else:
                candidate_connection.attrib.pop(attr, None)
        candidate_connection.set("tl", target_tls_id)
        candidate_connection.attrib.pop("uncontrolled", None)
        if target_tls_id == tls_id:
            copied_tls_ids.add(tls_id)
        if dict(candidate_connection.attrib) != before:
            updated_connections += 1
            updated_keys.append(_connection_key_record(key))

    tl_logic_report = _copy_referenced_tllogics(source_root, candidate_root, copied_tls_ids)
    padding_report = _pad_tllogic_state_lengths(candidate_root, required_tllogic_lengths)
    green_phase_report = (
        _add_green_phases_for_links(
            candidate_root,
            padded_tllogic_link_indices,
            add_yellow_phases=add_yellow_phases_for_generated_green,
        )
        if add_green_phases_for_padded_links
        else {
            "added_green_phase_count": 0,
            "added_green_phase_tllogic_count": 0,
            "added_green_phase_tllogics": [],
            "added_yellow_phase_count": 0,
            "added_yellow_phase_tllogic_count": 0,
            "added_yellow_phase_tllogics": [],
        }
    )
    candidate_controlled_after = _controlled_tls_connection_count(candidate_root)
    ET.indent(candidate_root, space="    ")
    candidate_tree.write(variant_file, encoding="utf-8", xml_declaration=True)

    report: dict[str, object] = {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "source_net_file": str(source_net_file),
        "candidate_net_file": str(candidate_net_file),
        "variant_file": str(variant_file),
        "summary_file": str(summary_file),
        "source_tls_controlled_connection_count": source_controlled,
        "candidate_tls_controlled_connection_count_before": candidate_controlled_before,
        "candidate_tls_controlled_connection_count_after": candidate_controlled_after,
        "matched_connection_count": matched_connections,
        "updated_connection_count": updated_connections,
        "missing_candidate_connection_count": missing_candidate_connections,
        "skipped_ambiguous_connection_count": ambiguous_connections,
        "skipped_unmapped_tls_connection_count": skipped_unmapped_tls_connections,
        "skipped_missing_mapped_tllogic_connection_count": skipped_missing_mapped_tllogic_connections,
        "skipped_invalid_mapped_linkindex_connection_count": skipped_invalid_mapped_linkindex_connections,
        "invalid_mapped_linkindex_capacity_gaps": _capacity_gap_records(invalid_mapped_linkindex_capacity_gaps),
        "source_duplicate_connection_key_count": len(source_duplicate_keys),
        "candidate_duplicate_connection_key_count": len(candidate_duplicate_keys),
        "tls_id_map_count": len(tls_id_map),
        "copy_unmapped_tls": copy_unmapped_tls,
        "require_target_link_index_capacity": require_target_link_index_capacity,
        "pad_mapped_tllogic_capacity": pad_mapped_tllogic_capacity,
        "add_green_phases_for_padded_links": add_green_phases_for_padded_links,
        "updated_connection_keys": updated_keys,
        **tl_logic_report,
        **padding_report,
        **green_phase_report,
        "review_policy": (
            "diagnostic variant only: run SUMO load and NetEdit connection-mode review before adoption; "
            "this repair copies TLS control attributes without changing edge, junction, via, or shape geometry"
        ),
    }
    summary_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
def write_teacher_connection_plan(
    *,
    raw_connection_file: Path,
    output_file: Path,
    junction_id: str,
    teacher_model: dict[str, object],
    candidate_model: dict[str, object],
    edge_map: dict[str, str],
    crossing_edge_overrides: dict[str, str | list[str]] | None = None,
    candidate_edge_file: Path | None = None,
    crossing_node_ids: set[str] | None = None,
    emit_crossings: bool = True,
    teacher_internal_scope_id: str | None = None,
) -> dict[str, object]:
    crossing_edge_overrides = crossing_edge_overrides or {}
    crossing_node_ids = crossing_node_ids or set()
    output_file.parent.mkdir(parents=True, exist_ok=True)

    incoming = _approach_edges(candidate_model, "incoming")
    outgoing = _approach_edges(candidate_model, "outgoing")
    target_incoming_edges = set(incoming)
    target_outgoing_edges = set(outgoing)
    candidate_lane_counts = _candidate_lane_counts(candidate_model)
    present_candidate_edges: set[str] | None = None
    if candidate_edge_file is not None:
        patched_lane_counts = _edge_file_lane_counts(candidate_edge_file)
        candidate_lane_counts.update(patched_lane_counts)
        present_candidate_edges = set(patched_lane_counts)
        incoming = [edge for edge in incoming if edge in present_candidate_edges]
        outgoing = [edge for edge in outgoing if edge in present_candidate_edges]
    patched_edge_endpoints = _plain_edge_endpoints(candidate_edge_file) if candidate_edge_file is not None else {}

    root = ET.Element("connections")
    kept = 0
    removed = 0
    removed_invalid_lane_connections = []
    removed_nonadjacent_connections = []
    for child in ET.parse(raw_connection_file).getroot():
        if (
            child.tag == "connection"
            and present_candidate_edges is not None
            and (
                child.attrib.get("from", "") not in present_candidate_edges
                or child.attrib.get("to", "") not in present_candidate_edges
            )
        ):
            removed += 1
            continue
        if (
            child.tag == "connection"
            and present_candidate_edges is not None
            and not _connection_lane_indices_valid(child, candidate_lane_counts)
        ):
            removed_invalid_lane_connections.append(dict(child.attrib))
            removed += 1
            continue
        if (
            child.tag == "connection"
            and present_candidate_edges is not None
            and not _connection_edges_are_adjacent(child, patched_edge_endpoints)
        ):
            removed_nonadjacent_connections.append(dict(child.attrib))
            removed += 1
            continue
        if child.tag == "connection" and (
            child.attrib.get("from", "") in target_incoming_edges
            and child.attrib.get("to", "") in target_outgoing_edges
        ):
            removed += 1
            continue
        if child.tag == "crossing" and present_candidate_edges is not None:
            crossing_edges = set(_split(child.attrib.get("edges", "")))
            if crossing_edges and not crossing_edges <= present_candidate_edges:
                removed += 1
                continue
        if child.tag == "crossing" and child.attrib.get("node") == junction_id:
            removed += 1
            continue
        root.append(child)
        kept += 1

    emitted_connections = 0
    emitted_uncontrolled_connections = 0
    allowed_pairs: set[tuple[str, str]] = set()
    skipped_off_scope_pairs: set[tuple[str, str]] = set()
    seen_connections: set[tuple[str, str, str, str]] = set()
    lane_clamps = []
    skipped_off_scope_internal_connections = []
    teacher_internal_scope_prefix = f":{teacher_internal_scope_id}_" if teacher_internal_scope_id else ""
    for connection in teacher_model.get("vehicle_connections", []) or []:
        if not isinstance(connection, dict):
            continue
        source = edge_map.get(str(connection.get("from", "")))
        target = edge_map.get(str(connection.get("to", "")))
        if not source or not target:
            continue
        via = str(connection.get("via", ""))
        if teacher_internal_scope_prefix and via.startswith(":") and not via.startswith(teacher_internal_scope_prefix):
            skipped_off_scope_pairs.add((source, target))
            skipped_off_scope_internal_connections.append(dict(connection))
            continue
        if present_candidate_edges is not None and (source not in present_candidate_edges or target not in present_candidate_edges):
            continue
        original_from_lane = int(connection.get("fromLane") or 0)
        original_to_lane = int(connection.get("toLane") or 0)
        from_lane = min(original_from_lane, candidate_lane_counts.get(source, 1) - 1)
        to_lane = min(original_to_lane, candidate_lane_counts.get(target, 1) - 1)
        if (from_lane, to_lane) != (original_from_lane, original_to_lane):
            lane_clamps.append(
                {
                    "candidate_from": source,
                    "candidate_to": target,
                    "fromLane": original_from_lane,
                    "toLane": original_to_lane,
                    "clamped_fromLane": from_lane,
                    "clamped_toLane": to_lane,
                }
            )
        key = (source, target, str(from_lane), str(to_lane))
        allowed_pairs.add((source, target))
        if key in seen_connections:
            continue
        seen_connections.add(key)
        attributes = {"from": source, "to": target, "fromLane": str(from_lane), "toLane": str(to_lane)}
        if not str(connection.get("tl", "")):
            attributes["uncontrolled"] = "true"
            emitted_uncontrolled_connections += 1
        ET.SubElement(root, "connection", attributes)
        emitted_connections += 1

    emitted_deletes = 0
    for source in sorted(incoming):
        for target in sorted(outgoing):
            if (source, target) in allowed_pairs:
                continue
            if (source, target) in skipped_off_scope_pairs:
                continue
            ET.SubElement(root, "delete", {"from": source, "to": target})
            emitted_deletes += 1

    emitted_crossings = 0
    skipped_crossings = []
    crossing_node_rewrites = []
    if emit_crossings:
        for crossing in teacher_model.get("crossings", []) or []:
            if not isinstance(crossing, dict):
                continue
            crossing_id = str(crossing.get("edge_id", ""))
            crossing_edges = crossing_edge_overrides.get(crossing_id)
            if crossing_edges is None:
                crossing_edges = [edge_map.get(str(edge), "") for edge in crossing.get("crossingEdges", []) or []]
            if isinstance(crossing_edges, str):
                crossing_edges = [crossing_edges]
            crossing_edges = [edge for edge in crossing_edges if edge]
            if present_candidate_edges is not None:
                crossing_edges = [edge for edge in crossing_edges if edge in present_candidate_edges]
            if not crossing_edges:
                skipped_crossings.append(crossing_id)
                continue
            crossing_node_id = _plain_crossing_node_id(
                junction_id,
                crossing_edges,
                patched_edge_endpoints,
                crossing_node_ids,
            )
            if crossing_node_id != junction_id:
                crossing_node_rewrites.append(
                    {
                        "crossing_id": crossing_id,
                        "from": junction_id,
                        "to": crossing_node_id,
                        "edges": crossing_edges,
                    }
                )
            ET.SubElement(
                root,
                "crossing",
                {"node": crossing_node_id, "edges": " ".join(crossing_edges), "priority": "1", "width": "4.00"},
            )
            emitted_crossings += 1

    ET.indent(root, space="    ")
    ET.ElementTree(root).write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "connection_file": str(output_file),
        "kept_non_target_children": kept,
        "removed_target_children": removed,
        "removed_invalid_lane_connection_count": len(removed_invalid_lane_connections),
        "removed_invalid_lane_connections": removed_invalid_lane_connections,
        "removed_nonadjacent_connection_count": len(removed_nonadjacent_connections),
        "removed_nonadjacent_connections": removed_nonadjacent_connections,
        "emitted_connection_count": emitted_connections,
        "emitted_uncontrolled_connection_count": emitted_uncontrolled_connections,
        "emitted_delete_count": emitted_deletes,
        "emitted_crossing_count": emitted_crossings,
        "emit_crossings": emit_crossings,
        "skipped_crossings": skipped_crossings,
        "crossing_node_rewrite_count": len(crossing_node_rewrites),
        "crossing_node_rewrites": crossing_node_rewrites,
        "lane_clamp_count": len(lane_clamps),
        "lane_clamps": lane_clamps,
        "skipped_off_scope_internal_connection_count": len(skipped_off_scope_internal_connections),
        "skipped_off_scope_internal_connections": skipped_off_scope_internal_connections,
    }
def write_teacher_lane_patch_edges(
    *,
    raw_edge_file: Path,
    teacher_edge_file: Path,
    output_file: Path,
    edge_map: dict[str, str],
    junction_id: str | None = None,
    teacher_junction_id: str | None = None,
    boundary_node_ids: set[str] | None = None,
    prune_unmapped_boundary_edges: bool = False,
    approach_endpoint_rebuild_plan: object | None = None,
    lane_shape_delta: tuple[float, float] | None = None,
    preserve_lane_shapes: bool = True,
) -> dict[str, object]:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    teacher_edges = {
        edge.attrib["id"]: edge
        for edge in ET.parse(teacher_edge_file).getroot().findall("edge")
        if edge.attrib.get("id")
    }
    teacher_by_candidate = {candidate_id: teacher_edges[teacher_id] for teacher_id, candidate_id in edge_map.items() if teacher_id in teacher_edges}

    tree = ET.parse(raw_edge_file)
    root = tree.getroot()
    patched = []
    added_missing_mapped_edges = []
    pruned_boundary_edges = []
    retained_unmapped_boundary_edges = []
    remapped_teacher_edges = set(edge_map)
    teacher_same_junction_edges = {
        edge_id
        for edge_id, edge in teacher_edges.items()
        if junction_id and junction_id in (edge.attrib.get("from"), edge.attrib.get("to")) and edge_id not in remapped_teacher_edges
    }
    allowed_boundary_edges = set(edge_map.values()) | teacher_same_junction_edges
    boundary_node_ids = boundary_node_ids or set()
    join_source_node_id = (
        sorted(boundary_node_ids)[0]
        if teacher_junction_id and junction_id and teacher_junction_id != junction_id and boundary_node_ids
        else ""
    )
    rebased_missing_mapped_edges = []
    rebased_existing_mapped_edges = []
    endpoint_rewritten_existing_mapped_edges = []
    endpoint_rewritten_missing_mapped_edges = []
    skipped_rebased_self_loop_edges = []
    endpoint_rewrites = _endpoint_rewrites(approach_endpoint_rebuild_plan)
    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id", "")
        touches_target = (
            edge.attrib.get("from") == junction_id
            or edge.attrib.get("to") == junction_id
            or edge.attrib.get("from") in boundary_node_ids
            or edge.attrib.get("to") in boundary_node_ids
        )
        if junction_id and touches_target and edge_id not in allowed_boundary_edges:
            if prune_unmapped_boundary_edges:
                root.remove(edge)
                pruned_boundary_edges.append(edge_id)
                continue
            retained_unmapped_boundary_edges.append(edge_id)
        teacher_edge = teacher_by_candidate.get(edge.attrib.get("id", ""))
        if teacher_edge is None:
            continue
        teacher_lanes = teacher_edge.findall("lane")
        if not teacher_lanes:
            continue
        rebased_endpoints = {}
        endpoint_rewritten = {}
        endpoint_rewrite = endpoint_rewrites.get(edge_id)
        if endpoint_rewrite is not None:
            for attr, desired_endpoint in (("from", endpoint_rewrite[0]), ("to", endpoint_rewrite[1])):
                current_endpoint = edge.attrib.get(attr, "")
                if current_endpoint != desired_endpoint:
                    edge.set(attr, desired_endpoint)
                    endpoint_rewritten[attr] = {"old": current_endpoint, "new": desired_endpoint}
        elif join_source_node_id:
            for attr in ("from", "to"):
                teacher_endpoint = teacher_edge.attrib.get(attr, "")
                if teacher_endpoint == teacher_junction_id:
                    edge.set(attr, join_source_node_id)
                    rebased_endpoints[attr] = {"teacher": teacher_endpoint, "candidate": join_source_node_id}
        if (rebased_endpoints or endpoint_rewritten) and edge.attrib.get("from") and edge.attrib.get("from") == edge.attrib.get("to"):
            skipped_rebased_self_loop_edges.append(
                {
                    "candidate_edge_id": edge.attrib.get("id", ""),
                    "teacher_edge_id": teacher_edge.attrib.get("id", ""),
                    "node": edge.attrib["from"],
                }
            )
            root.remove(edge)
            continue
        existing_lane_shapes = (
            {}
            if endpoint_rewrite is not None
            else {
                lane.attrib.get("index", ""): lane.attrib["shape"]
                for lane in edge.findall("lane")
                if lane.attrib.get("index", "") and lane.attrib.get("shape")
            }
        )
        for lane in list(edge.findall("lane")):
            edge.remove(lane)
        edge.attrib.pop("allow", None)
        edge.attrib.pop("disallow", None)
        edge.attrib.pop("width", None)
        edge.set("numLanes", str(len(teacher_lanes)))
        for attr in ("allow", "disallow", "width"):
            if teacher_edge.attrib.get(attr):
                edge.set(attr, teacher_edge.attrib[attr])
        if not preserve_lane_shapes:
            edge.attrib.pop("shape", None)
        for lane in teacher_lanes:
            lane_attrs = {"index": lane.attrib.get("index", "0")}
            for attr in ("allow", "disallow", "width", "speed"):
                if lane.attrib.get(attr):
                    lane_attrs[attr] = lane.attrib[attr]
            if preserve_lane_shapes:
                if lane.attrib.get("index", "") in existing_lane_shapes:
                    lane_attrs["shape"] = existing_lane_shapes[lane.attrib.get("index", "")]
                elif lane.attrib.get("shape"):
                    lane_attrs["shape"] = (
                        _translate_shape(lane.attrib["shape"], lane_shape_delta[0], lane_shape_delta[1])
                        if lane_shape_delta is not None
                        else lane.attrib["shape"]
                    )
            ET.SubElement(edge, "lane", lane_attrs)
        patched.append({"candidate_edge_id": edge.attrib.get("id", ""), "teacher_edge_id": teacher_edge.attrib.get("id", ""), "lane_count": len(teacher_lanes)})
        if endpoint_rewritten:
            endpoint_rewritten_existing_mapped_edges.append(
                {
                    "candidate_edge_id": edge.attrib.get("id", ""),
                    "teacher_edge_id": teacher_edge.attrib.get("id", ""),
                    **endpoint_rewritten,
                }
            )
        if rebased_endpoints:
            rebased_existing_mapped_edges.append(
                {
                    "candidate_edge_id": edge.attrib.get("id", ""),
                    "teacher_edge_id": teacher_edge.attrib.get("id", ""),
                    **rebased_endpoints,
                }
            )

    existing_edge_ids = {edge.attrib.get("id", "") for edge in root.findall("edge")}
    for teacher_id, candidate_id in sorted(edge_map.items()):
        if candidate_id in existing_edge_ids:
            continue
        teacher_edge = teacher_edges.get(teacher_id)
        if teacher_edge is None:
            continue
        teacher_lanes = teacher_edge.findall("lane")
        edge_attrs = dict(teacher_edge.attrib)
        edge_attrs["id"] = candidate_id
        edge_attrs["numLanes"] = str(len(teacher_lanes))
        rebased_endpoints = {}
        endpoint_rewritten = {}
        endpoint_rewrite = endpoint_rewrites.get(candidate_id)
        if endpoint_rewrite is not None:
            for attr, desired_endpoint in (("from", endpoint_rewrite[0]), ("to", endpoint_rewrite[1])):
                current_endpoint = edge_attrs.get(attr, "")
                if current_endpoint != desired_endpoint:
                    edge_attrs[attr] = desired_endpoint
                    endpoint_rewritten[attr] = {"old": current_endpoint, "new": desired_endpoint}
        elif join_source_node_id:
            for attr in ("from", "to"):
                teacher_endpoint = edge_attrs.get(attr, "")
                if teacher_endpoint == teacher_junction_id:
                    edge_attrs[attr] = join_source_node_id
                    rebased_endpoints[attr] = {"teacher": teacher_endpoint, "candidate": join_source_node_id}
        if (rebased_endpoints or endpoint_rewritten) and edge_attrs.get("from") and edge_attrs.get("from") == edge_attrs.get("to"):
            skipped_rebased_self_loop_edges.append(
                {"candidate_edge_id": candidate_id, "teacher_edge_id": teacher_id, "node": edge_attrs["from"]}
            )
            continue
        if lane_shape_delta is not None and edge_attrs.get("shape"):
            edge_attrs["shape"] = _translate_shape(edge_attrs["shape"], lane_shape_delta[0], lane_shape_delta[1])
        edge = ET.SubElement(root, "edge", edge_attrs)
        for lane in teacher_lanes:
            lane_attrs = {"index": lane.attrib.get("index", "0")}
            for attr in ("allow", "disallow", "width", "speed"):
                if lane.attrib.get(attr):
                    lane_attrs[attr] = lane.attrib[attr]
            if preserve_lane_shapes and lane.attrib.get("shape"):
                lane_attrs["shape"] = (
                    _translate_shape(lane.attrib["shape"], lane_shape_delta[0], lane_shape_delta[1])
                    if lane_shape_delta is not None
                    else lane.attrib["shape"]
                )
            ET.SubElement(edge, "lane", lane_attrs)
        added_missing_mapped_edges.append(
            {"candidate_edge_id": candidate_id, "teacher_edge_id": teacher_id, "lane_count": len(teacher_lanes)}
        )
        if rebased_endpoints:
            rebased_missing_mapped_edges.append(
                {"candidate_edge_id": candidate_id, "teacher_edge_id": teacher_id, **rebased_endpoints}
            )
        if endpoint_rewritten:
            endpoint_rewritten_missing_mapped_edges.append(
                {"candidate_edge_id": candidate_id, "teacher_edge_id": teacher_id, **endpoint_rewritten}
            )
        patched.append(added_missing_mapped_edges[-1])
        existing_edge_ids.add(candidate_id)

    ET.indent(root, space="    ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "edge_file": str(output_file),
        "patched_edge_count": len(patched),
        "patched_edges": patched,
        "added_missing_mapped_edge_count": len(added_missing_mapped_edges),
        "added_missing_mapped_edges": added_missing_mapped_edges,
        "rebased_existing_mapped_edge_count": len(rebased_existing_mapped_edges),
        "rebased_existing_mapped_edges": rebased_existing_mapped_edges,
        "rebased_missing_mapped_edge_count": len(rebased_missing_mapped_edges),
        "rebased_missing_mapped_edges": rebased_missing_mapped_edges,
        "endpoint_rewritten_existing_mapped_edge_count": len(endpoint_rewritten_existing_mapped_edges),
        "endpoint_rewritten_existing_mapped_edges": endpoint_rewritten_existing_mapped_edges,
        "endpoint_rewritten_missing_mapped_edge_count": len(endpoint_rewritten_missing_mapped_edges),
        "endpoint_rewritten_missing_mapped_edges": endpoint_rewritten_missing_mapped_edges,
        "skipped_rebased_self_loop_edge_count": len(skipped_rebased_self_loop_edges),
        "skipped_rebased_self_loop_edges": skipped_rebased_self_loop_edges,
        "pruned_boundary_edge_count": len(pruned_boundary_edges),
        "pruned_boundary_edges": pruned_boundary_edges,
        "retained_unmapped_boundary_edge_count": len(retained_unmapped_boundary_edges),
        "retained_unmapped_boundary_edges": retained_unmapped_boundary_edges,
        "lane_shape_translation_applied": lane_shape_delta is not None,
        "preserve_lane_shapes": preserve_lane_shapes,
    }
def write_missing_edge_type_patch(
    *,
    raw_type_file: Path | None,
    edge_file: Path,
    output_file: Path,
) -> dict[str, object]:
    try:
        edge_root = ET.parse(edge_file).getroot()
        if raw_type_file is not None and raw_type_file.exists():
            type_tree = ET.parse(raw_type_file)
            type_root = type_tree.getroot()
        else:
            type_root = ET.Element("types")
            type_tree = ET.ElementTree(type_root)
    except (ET.ParseError, OSError) as exc:
        return _failure(f"could not patch edge types: {exc}")

    known_type_ids = {edge_type.attrib["id"] for edge_type in type_root.findall("type") if edge_type.attrib.get("id")}
    synthesized = []
    for edge in edge_root.findall("edge"):
        type_id = edge.attrib.get("type", "")
        if not type_id or type_id in known_type_ids:
            continue
        attrs = {"id": type_id}
        for attr in ("priority", "numLanes", "speed", "allow", "disallow", "oneway", "width"):
            if edge.attrib.get(attr):
                attrs[attr] = edge.attrib[attr]
        if "numLanes" not in attrs:
            lane_count = len(edge.findall("lane"))
            if lane_count:
                attrs["numLanes"] = str(lane_count)
        if "speed" not in attrs:
            first_lane = edge.find("lane")
            if first_lane is not None and first_lane.attrib.get("speed"):
                attrs["speed"] = first_lane.attrib["speed"]
        ET.SubElement(type_root, "type", attrs)
        known_type_ids.add(type_id)
        synthesized.append(type_id)

    removed_lane_synthesis_attributes = []
    for edge_type in type_root.findall("type"):
        type_id = str(edge_type.attrib.get("id", ""))
        for attribute in ("sidewalkWidth", "bikeLaneWidth"):
            value = edge_type.attrib.pop(attribute, None)
            if value is not None:
                removed_lane_synthesis_attributes.append(
                    {"type_id": type_id, "attribute": attribute, "value": value}
                )

    patched = bool(synthesized or removed_lane_synthesis_attributes)
    if patched:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        ET.indent(type_root, space="    ")
        type_tree.write(output_file, encoding="utf-8", xml_declaration=True)
        type_file = output_file
    else:
        type_file = raw_type_file if raw_type_file is not None and raw_type_file.exists() else None
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "raw_type_file": str(raw_type_file) if raw_type_file is not None else "",
        "type_file": str(type_file) if type_file is not None else "",
        "patched_type_file": str(output_file) if patched else "",
        "synthesized_edge_type_count": len(synthesized),
        "synthesized_edge_type_ids": synthesized,
        "roundtrip_lane_synthesis_attribute_removal_count": len(
            removed_lane_synthesis_attributes
        ),
        "roundtrip_lane_synthesis_attribute_removals": removed_lane_synthesis_attributes,
    }
def write_teacher_endpoint_patch_nodes(
    *,
    raw_node_file: Path,
    teacher_net_file: Path,
    edge_file: Path,
    output_file: Path,
    lane_shape_delta: tuple[float, float] | None = None,
) -> dict[str, object]:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(raw_node_file)
    root = tree.getroot()
    existing_node_ids = {node.attrib.get("id", "") for node in root.findall("node") if node.attrib.get("id")}
    needed_node_ids = {
        endpoint
        for edge in ET.parse(edge_file).getroot().findall("edge")
        for endpoint in (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
        if endpoint and not endpoint.startswith(":")
    }
    missing_node_ids = sorted(needed_node_ids - existing_node_ids)
    teacher_nodes = {
        junction.attrib["id"]: junction
        for junction in ET.parse(teacher_net_file).getroot().findall("junction")
        if junction.attrib.get("id") and junction.attrib.get("type") != "internal"
    }
    added_node_ids = []
    unresolved_node_ids = []
    safe_attrs = ("id", "x", "y", "type", "shape", "radius", "keepClear", "rightOfWay", "fringe", "tl")
    dx, dy = lane_shape_delta if lane_shape_delta is not None else (0.0, 0.0)

    for node_id in missing_node_ids:
        teacher_node = teacher_nodes.get(node_id)
        if teacher_node is None:
            unresolved_node_ids.append(node_id)
            continue
        attrs = {attr: teacher_node.attrib[attr] for attr in safe_attrs if teacher_node.attrib.get(attr)}
        attrs["id"] = node_id
        if lane_shape_delta is not None:
            if attrs.get("x"):
                attrs["x"] = _format_xy(float(attrs["x"]) + dx)
            if attrs.get("y"):
                attrs["y"] = _format_xy(float(attrs["y"]) + dy)
            if attrs.get("shape"):
                attrs["shape"] = _translate_shape(attrs["shape"], dx, dy)
        ET.SubElement(root, "node", attrs)
        added_node_ids.append(node_id)

    ET.indent(root, space="    ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass" if not unresolved_node_ids else "review",
        "claim_status": "diagnostic-demo",
        "node_file": str(output_file),
        "added_missing_endpoint_node_count": len(added_node_ids),
        "added_missing_endpoint_node_ids": added_node_ids,
        "unresolved_missing_endpoint_node_ids": unresolved_node_ids,
        "node_shape_translation_applied": lane_shape_delta is not None,
    }
def _copy_teacher_walkingareas(
    root: ET.Element,
    *,
    junction_id: str,
    teacher_junction_id: str,
    teacher_junction: object,
    teacher_walkingareas: object,
) -> tuple[list[tuple[str, str]], int]:
    candidate_junction = root.find(f"junction[@id='{junction_id}']")
    if candidate_junction is None or not isinstance(teacher_junction, dict) or not isinstance(teacher_walkingareas, list):
        return [], 0
    try:
        dx = float(candidate_junction.attrib.get("x", "0")) - float(str(teacher_junction.get("x", "0")))
        dy = float(candidate_junction.attrib.get("y", "0")) - float(str(teacher_junction.get("y", "0")))
    except ValueError:
        dx = dy = 0.0

    copied = []
    copied_count = 0
    copied_edge_ids = []
    existing_edge_ids = {edge.attrib.get("id", "") for edge in root.findall("edge")}
    insert_index = _first_junction_index(root)
    for walkingarea in teacher_walkingareas:
        if not isinstance(walkingarea, dict):
            continue
        teacher_edge_id = str(walkingarea.get("edge_id", ""))
        candidate_edge_id = _mapped_internal_ref(teacher_edge_id, teacher_junction_id, junction_id)
        if not teacher_edge_id or not candidate_edge_id or candidate_edge_id in existing_edge_ids:
            if teacher_edge_id and candidate_edge_id and candidate_edge_id in existing_edge_ids:
                copied.append((teacher_edge_id, candidate_edge_id))
            continue
        edge = ET.Element("edge", {"id": candidate_edge_id, "function": "walkingarea"})
        for lane in walkingarea.get("lanes", []) or []:
            if not isinstance(lane, dict):
                continue
            lane_attrs = {str(key): str(value) for key, value in lane.items() if value not in (None, "")}
            if lane_attrs.get("id"):
                lane_attrs["id"] = _mapped_internal_ref(lane_attrs["id"], teacher_junction_id, junction_id)
            for attr in ("shape", "outlineShape", "customShape"):
                if lane_attrs.get(attr):
                    lane_attrs[attr] = _translate_shape(lane_attrs[attr], dx, dy)
            ET.SubElement(edge, "lane", lane_attrs)
        root.insert(insert_index, edge)
        insert_index += 1
        existing_edge_ids.add(candidate_edge_id)
        copied_edge_ids.append(candidate_edge_id)
        copied_count += 1
        copied.append((teacher_edge_id, candidate_edge_id))

    copied_lane_ids = [
        lane.attrib["id"]
        for candidate_edge_id in copied_edge_ids
        for edge in root.findall(f"edge[@id='{candidate_edge_id}']")
        for lane in edge.findall("lane")
        if lane.attrib.get("id")
    ]
    if copied_lane_ids:
        inc_lanes = _split(candidate_junction.attrib.get("incLanes", ""))
        candidate_junction.set("incLanes", " ".join([*inc_lanes, *copied_lane_ids]))
    return copied, copied_count
def _translated_lane_attrs(
    lane: dict[str, Any],
    teacher_junction_id: str,
    junction_id: str,
    dx: float,
    dy: float,
) -> dict[str, str]:
    lane_attrs = {str(key): str(value) for key, value in lane.items() if value not in (None, "")}
    if lane_attrs.get("id"):
        lane_attrs["id"] = _mapped_internal_ref(lane_attrs["id"], teacher_junction_id, junction_id)
    for attr in ("shape", "outlineShape", "customShape"):
        if lane_attrs.get(attr):
            lane_attrs[attr] = _translate_shape(lane_attrs[attr], dx, dy)
    return lane_attrs
def write_teacher_vehicle_connection_attrs_net(
    *,
    candidate_net_file: Path,
    output_file: Path,
    junction_id: str,
    teacher_model: dict[str, object],
    edge_map: dict[str, str],
) -> dict[str, object]:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(candidate_net_file)
    root = tree.getroot()
    lane_counts = _net_lane_counts(root)
    shape_delta = None
    teacher_junction = teacher_model.get("junction", {}) if isinstance(teacher_model.get("junction"), dict) else {}
    candidate_junction = next((item for item in root.findall("junction") if item.attrib.get("id") == junction_id), None)
    if candidate_junction is not None:
        try:
            shape_delta = (
                float(candidate_junction.attrib.get("x", "")) - float(teacher_junction.get("x", "")),
                float(candidate_junction.attrib.get("y", "")) - float(teacher_junction.get("y", "")),
            )
        except (TypeError, ValueError):
            shape_delta = None

    connections_by_key: dict[tuple[str, str, str, str], list[ET.Element]] = {}
    for connection in root.findall("connection"):
        key = (
            connection.attrib.get("from", ""),
            connection.attrib.get("to", ""),
            connection.attrib.get("fromLane", "0"),
            connection.attrib.get("toLane", "0"),
        )
        connections_by_key.setdefault(key, []).append(connection)

    updated = 0
    skipped = []
    for teacher_connection in teacher_model.get("vehicle_connections", []) or []:
        if not isinstance(teacher_connection, dict):
            continue
        source = edge_map.get(str(teacher_connection.get("from", "")))
        target = edge_map.get(str(teacher_connection.get("to", "")))
        if not source or not target:
            skipped.append({"reason": "unmapped_edge", "connection": teacher_connection})
            continue
        from_lane = min(int(teacher_connection.get("fromLane") or 0), lane_counts.get(source, 1) - 1)
        to_lane = min(int(teacher_connection.get("toLane") or 0), lane_counts.get(target, 1) - 1)
        matches = connections_by_key.get((source, target, str(from_lane), str(to_lane)), [])
        if not matches:
            skipped.append({"reason": "missing_candidate_connection", "connection": teacher_connection})
            continue
        for connection in matches:
            for attr in ("dir", "state"):
                if teacher_connection.get(attr):
                    connection.set(attr, str(teacher_connection[attr]))
            for attr in ("linkIndex2", "pass", "allow", "disallow", "keepClear", "contPos"):
                if teacher_connection.get(attr):
                    connection.set(attr, str(teacher_connection[attr]))
                else:
                    connection.attrib.pop(attr, None)
            if teacher_connection.get("shape") and shape_delta is not None:
                connection.set("shape", _translate_shape(str(teacher_connection["shape"]), shape_delta[0], shape_delta[1]))
            if teacher_connection.get("tl"):
                connection.set("tl", junction_id)
                connection.set("linkIndex", str(teacher_connection.get("linkIndex", "")))
                if teacher_connection.get("uncontrolled"):
                    connection.set("uncontrolled", str(teacher_connection["uncontrolled"]))
                else:
                    connection.attrib.pop("uncontrolled", None)
            else:
                connection.attrib.pop("tl", None)
                connection.attrib.pop("linkIndex", None)
                connection.set("uncontrolled", "true")
            updated += 1

    ET.indent(root, space="    ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "net_file": str(output_file),
        "updated_vehicle_connection_count": updated,
        "skipped_vehicle_connection_count": len(skipped),
        "skipped_vehicle_connections": skipped,
    }
def write_teacher_tllogic_net(
    *,
    candidate_net_file: Path,
    output_file: Path,
    junction_id: str,
    teacher_model: dict[str, object],
) -> dict[str, object]:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(candidate_net_file)
    root = tree.getroot()
    traffic_light = teacher_model.get("traffic_light", {})
    if not isinstance(traffic_light, dict):
        return _failure("teacher_model.traffic_light is missing")
    attributes = traffic_light.get("attributes", {})
    phases = traffic_light.get("phases", [])
    if not isinstance(attributes, dict) or not isinstance(phases, list):
        return _failure("teacher_model.traffic_light is invalid")
    target_tl = next((tl for tl in root.findall("tlLogic") if tl.attrib.get("id") == junction_id), None)
    if not attributes and not phases:
        if target_tl is not None:
            root.remove(target_tl)
        valid_tls_ids = {tl.attrib["id"] for tl in root.findall("tlLogic") if tl.attrib.get("id")}
        uncontrolled_count = 0
        for connection in root.findall("connection"):
            if connection.attrib.get("tl") == junction_id or (
                connection.attrib.get("tl") and connection.attrib.get("tl") not in valid_tls_ids
            ):
                connection.attrib.pop("tl", None)
                connection.attrib.pop("linkIndex", None)
                connection.set("uncontrolled", "true")
                uncontrolled_count += 1
        ET.indent(root, space="    ")
        tree.write(output_file, encoding="utf-8", xml_declaration=True)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "net_file": str(output_file),
            "tl_phase_count": 0,
            "tl_phase_state_lengths": [],
            "controlled_link_count": 0,
            "removed_controlled_link_count": uncontrolled_count,
            "tls_replay_status": "not_applicable_no_teacher_tllogic",
        }
    root_children = list(root)
    candidate_indexes = [
        idx for idx, child in enumerate(root_children) if child.tag == "tlLogic" or child.tag in {"junction", "connection"}
    ]
    index = min(candidate_indexes) if candidate_indexes else len(root_children)
    if target_tl is not None:
        root.remove(target_tl)
    replacement = ET.Element("tlLogic", {str(key): str(value) for key, value in attributes.items()})
    replacement.set("id", junction_id)
    for phase in phases:
        if isinstance(phase, dict):
            ET.SubElement(replacement, "phase", {str(key): str(value) for key, value in phase.items()})
    root.insert(index, replacement)

    ET.indent(root, space="    ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    controlled_links = [
        connection
        for connection in root.findall("connection")
        if connection.attrib.get("tl") == junction_id and connection.attrib.get("linkIndex")
    ]
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "net_file": str(output_file),
        "tl_phase_count": len(replacement.findall("phase")),
        "tl_phase_state_lengths": sorted({len(phase.attrib.get("state", "")) for phase in replacement.findall("phase")}),
        "controlled_link_count": len(controlled_links),
    }
def restore_teacher_tls_connection_semantics_after_normalize(
    *,
    source_net_file: Path,
    target_net_file: Path,
    junction_id: str,
) -> dict[str, object]:
    """Restore teacher TLS attributes after netconvert rebuilds internal links.

    netconvert is authoritative for legal internal geometry and may recompute
    ``dir``/``state`` while assigning a different internal ``via`` suffix.  A
    scoped teacher replay needs the teacher control semantics on the resulting
    candidate connection, keyed by the stable ``linkIndex``.  This function
    refuses partial rebinding and reports every rewrite; it never creates a
    missing connection or changes the candidate's endpoints/lanes/via path.
    """

    if not source_net_file.exists() or not target_net_file.exists():
        return _failure("source or target normalized net file is missing")
    try:
        source_root = ET.parse(source_net_file).getroot()
        target_tree = ET.parse(target_net_file)
        target_root = target_tree.getroot()
    except (ET.ParseError, OSError, ValueError) as exc:
        return _failure(f"TLS semantic restore parse failed: {type(exc).__name__}: {exc}")

    source_connections = [
        connection
        for connection in source_root.findall("connection")
        if connection.attrib.get("tl") == junction_id and connection.attrib.get("linkIndex")
    ]
    target_connections = [
        connection
        for connection in target_root.findall("connection")
        if connection.attrib.get("tl") == junction_id and connection.attrib.get("linkIndex")
    ]

    def connection_semantic_key(connection: ET.Element) -> tuple[str, str, str, str, str]:
        """Identify a controlled movement without depending on the internal via id."""

        attrs = connection.attrib
        return (
            attrs.get("from", ""),
            attrs.get("to", ""),
            attrs.get("fromLane", ""),
            attrs.get("toLane", ""),
            attrs.get("linkIndex", ""),
        )

    source_semantic_key_counts = Counter(connection_semantic_key(connection) for connection in source_connections)
    retained_semantic_key_counts: Counter[tuple[str, str, str, str, str]] = Counter()
    removed_stale_target_connections: list[dict[str, str]] = []
    retained_target_connections: list[ET.Element] = []
    for target_connection in target_connections:
        semantic_key = connection_semantic_key(target_connection)
        if retained_semantic_key_counts[semantic_key] >= source_semantic_key_counts.get(semantic_key, 0):
            target_root.remove(target_connection)
            removed_stale_target_connections.append(
                {
                    "from": target_connection.attrib.get("from", ""),
                    "to": target_connection.attrib.get("to", ""),
                    "fromLane": target_connection.attrib.get("fromLane", ""),
                    "toLane": target_connection.attrib.get("toLane", ""),
                    "linkIndex": target_connection.attrib.get("linkIndex", ""),
                }
            )
            continue
        retained_semantic_key_counts[semantic_key] += 1
        retained_target_connections.append(target_connection)
    target_connections = retained_target_connections

    source_by_link_index: dict[str, list[ET.Element]] = {}
    target_by_link_index: dict[str, list[ET.Element]] = {}
    for connection in source_connections:
        source_by_link_index.setdefault(connection.attrib["linkIndex"], []).append(connection)
    for connection in target_connections:
        target_by_link_index.setdefault(connection.attrib["linkIndex"], []).append(connection)

    rewritten: list[dict[str, str]] = []
    missing_source_link_indices: list[str] = []
    extra_target_link_indices: list[str] = []
    used_source_counts: dict[str, int] = {}
    for link_index, target_items in sorted(target_by_link_index.items()):
        source_items = source_by_link_index.get(link_index, [])
        if len(target_items) > len(source_items):
            extra_target_link_indices.extend([link_index] * (len(target_items) - len(source_items)))
        for position, target_connection in enumerate(target_items):
            if position >= len(source_items):
                continue
            source_connection = source_items[position]
            before = dict(target_connection.attrib)
            for attr in TLS_CONNECTION_REPAIR_ATTRS:
                if attr in source_connection.attrib:
                    target_connection.set(attr, source_connection.attrib[attr])
                else:
                    target_connection.attrib.pop(attr, None)
            target_connection.set("tl", junction_id)
            target_connection.set("linkIndex", link_index)
            used_source_counts[link_index] = used_source_counts.get(link_index, 0) + 1
            if target_connection.attrib != before:
                rewritten.append(
                    {
                        "linkIndex": link_index,
                        "from": target_connection.attrib.get("from", ""),
                        "to": target_connection.attrib.get("to", ""),
                    }
                )
    for link_index, source_items in sorted(source_by_link_index.items()):
        if used_source_counts.get(link_index, 0) < len(source_items):
            missing_source_link_indices.extend(
                [link_index] * (len(source_items) - used_source_counts.get(link_index, 0))
            )

    source_tl_logic = next(
        (tl_logic for tl_logic in source_root.findall("tlLogic") if tl_logic.attrib.get("id") == junction_id),
        None,
    )
    target_tl_logic = next(
        (tl_logic for tl_logic in target_root.findall("tlLogic") if tl_logic.attrib.get("id") == junction_id),
        None,
    )
    tl_logic_status = "skipped"
    restored_tl_logic_phase_count = 0
    phase_state_length_mismatches: list[dict[str, int]] = []
    phase_state_extra_slot_warnings: list[dict[str, int]] = []
    if source_tl_logic is not None:
        if target_tl_logic is None:
            tl_logic_status = "blocked"
        else:
            source_phases = list(source_tl_logic.findall("phase"))
            numeric_link_indices = [
                int(connection.attrib["linkIndex"])
                for connection in source_connections
                if connection.attrib.get("linkIndex", "").isdigit()
            ]
            expected_phase_state_length = max(numeric_link_indices, default=-1) + 1
            for phase in source_phases:
                state = phase.attrib.get("state")
                if state is not None and len(state) != expected_phase_state_length:
                    evidence = {
                        "source_state_length": len(state),
                        "expected_phase_state_length": expected_phase_state_length,
                        "target_controlled_connection_count": len(target_connections),
                    }
                    if len(state) < expected_phase_state_length:
                        phase_state_length_mismatches.append(evidence)
                    else:
                        phase_state_extra_slot_warnings.append(evidence)
            for attr in ("type", "programID", "offset"):
                if attr in source_tl_logic.attrib:
                    target_tl_logic.set(attr, source_tl_logic.attrib[attr])
                else:
                    target_tl_logic.attrib.pop(attr, None)
            for phase in list(target_tl_logic.findall("phase")):
                target_tl_logic.remove(phase)
            for phase in source_phases:
                target_tl_logic.append(copy.deepcopy(phase))
            restored_tl_logic_phase_count = len(source_phases)
            tl_logic_status = "pass" if not phase_state_length_mismatches else "blocked"

    status = (
        "pass"
        if not missing_source_link_indices
        and not extra_target_link_indices
        and tl_logic_status != "blocked"
        else "blocked"
    )
    if rewritten or removed_stale_target_connections or (source_tl_logic is not None and target_tl_logic is not None):
        ET.indent(target_root, space="    ")
        target_tree.write(target_net_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": status,
        "claim_status": "diagnostic-demo",
        "source_net_file": str(source_net_file),
        "target_net_file": str(target_net_file),
        "junction_id": junction_id,
        "source_controlled_connection_count": len(source_connections),
        "target_controlled_connection_count": len(target_connections),
        "removed_stale_target_connection_count": len(removed_stale_target_connections),
        "removed_stale_target_connections": removed_stale_target_connections,
        "rewritten_connection_count": len(rewritten),
        "rewritten_connections": rewritten,
        "missing_source_link_indices": missing_source_link_indices,
        "extra_target_link_indices": extra_target_link_indices,
        "tl_logic_status": tl_logic_status,
        "restored_tl_logic": source_tl_logic is not None and target_tl_logic is not None,
        "restored_tl_logic_phase_count": restored_tl_logic_phase_count,
        "phase_state_length_mismatches": phase_state_length_mismatches,
        "phase_state_extra_slot_warnings": phase_state_extra_slot_warnings,
        "policy": "restore teacher TLS attrs by linkIndex; preserve candidate endpoints/lanes/via",
    }
def restore_scoped_pedestrian_internal_semantics_after_normalize(
    *,
    source_net_file: Path,
    target_net_file: Path,
    junction_id: str,
    edge_map: dict[str, str] | None = None,
) -> dict[str, object]:
    """Restore scoped crossing/walkingarea edges dropped by netconvert.

    SUMO may discard a crossing whose OSM-side boundary edge was remapped or
    whose geometry is not reconstructible from plain vehicle links.  The
    teacher replay already contains the audited pedestrian layer, so this
    function overlays only the target cell's crossing/walkingarea edges and
    their connections, then verifies that every source element is represented.
    It never copies pedestrian infrastructure outside the target prefix.
    """

    if not source_net_file.exists() or not target_net_file.exists():
        return _failure("source or target normalized net file is missing")
    try:
        source_root = ET.parse(source_net_file).getroot()
        target_tree = ET.parse(target_net_file)
        target_root = target_tree.getroot()
    except (ET.ParseError, OSError, ValueError) as exc:
        return _failure(f"pedestrian semantic restore parse failed: {type(exc).__name__}: {exc}")

    edge_map = {str(key): str(value) for key, value in (edge_map or {}).items() if str(key) and str(value)}
    internal_prefix = f":{junction_id}_"
    pedestrian_functions = {"crossing", "walkingarea"}
    source_pedestrian_edges = {
        edge.attrib.get("id", ""): edge
        for edge in source_root.findall("edge")
        if edge.attrib.get("id", "").startswith(internal_prefix)
        and edge.attrib.get("function") in pedestrian_functions
    }
    target_edges = {
        edge.attrib.get("id", ""): edge
        for edge in target_root.findall("edge")
        if edge.attrib.get("id")
    }
    replaced_edge_ids: list[str] = []
    added_edge_ids: list[str] = []

    def mapped_pedestrian_edge(source_edge: ET.Element) -> ET.Element:
        clone = copy.deepcopy(source_edge)
        if clone.attrib.get("crossingEdges"):
            clone.set(
                "crossingEdges",
                " ".join(
                    edge_map.get(value, value)
                    for value in clone.attrib.get("crossingEdges", "").split()
                    if value
                ),
            )
        return clone

    for edge_id, source_edge in sorted(source_pedestrian_edges.items()):
        replacement = mapped_pedestrian_edge(source_edge)
        existing = target_edges.get(edge_id)
        if existing is None:
            target_root.append(replacement)
            target_edges[edge_id] = replacement
            added_edge_ids.append(edge_id)
            continue
        index = list(target_root).index(existing)
        target_root.remove(existing)
        target_root.insert(index, replacement)
        target_edges[edge_id] = replacement
        replaced_edge_ids.append(edge_id)

    source_pedestrian_connections = [
        connection
        for connection in source_root.findall("connection")
        if connection.attrib.get("from", "") in source_pedestrian_edges
        or connection.attrib.get("to", "") in source_pedestrian_edges
    ]

    def mapped_connection(source_connection: ET.Element) -> ET.Element:
        attrs = dict(source_connection.attrib)
        for attr in ("from", "to"):
            value = attrs.get(attr, "")
            if value and not value.startswith(":"):
                attrs[attr] = edge_map.get(value, value)
        return ET.Element("connection", attrs)

    def connection_key(connection: ET.Element) -> tuple[str, ...]:
        return tuple(
            connection.attrib.get(attr, "")
            for attr in ("from", "to", "fromLane", "toLane", "via", "tl", "linkIndex")
        )

    target_connections = {connection_key(connection): connection for connection in target_root.findall("connection")}
    added_connection_count = 0
    updated_connection_count = 0
    for source_connection in source_pedestrian_connections:
        mapped = mapped_connection(source_connection)
        key = connection_key(mapped)
        existing = target_connections.get(key)
        if existing is None:
            target_root.append(mapped)
            target_connections[key] = mapped
            added_connection_count += 1
            continue
        before = dict(existing.attrib)
        existing.attrib.clear()
        existing.attrib.update(mapped.attrib)
        if before != existing.attrib:
            updated_connection_count += 1

    missing_edge_ids = sorted(set(source_pedestrian_edges) - set(target_edges))
    missing_connection_keys = sorted(
        set(connection_key(mapped_connection(connection)) for connection in source_pedestrian_connections)
        - set(target_connections)
    )
    missing_crossing_edge_refs = []
    target_edge_ids = set(target_edges)
    for edge in target_edges.values():
        if edge.attrib.get("id") not in source_pedestrian_edges or not edge.attrib.get("crossingEdges"):
            continue
        for referenced_edge_id in edge.attrib.get("crossingEdges", "").split():
            if referenced_edge_id not in target_edge_ids:
                missing_crossing_edge_refs.append(
                    {"crossing_edge_id": edge.attrib.get("id", ""), "referenced_edge_id": referenced_edge_id}
                )
    status = "pass" if not missing_edge_ids and not missing_connection_keys and not missing_crossing_edge_refs else "blocked"
    if source_pedestrian_edges or source_pedestrian_connections:
        ET.indent(target_root, space="    ")
        target_tree.write(target_net_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": status,
        "claim_status": "diagnostic-demo",
        "source_net_file": str(source_net_file),
        "target_net_file": str(target_net_file),
        "junction_id": junction_id,
        "source_pedestrian_edge_count": len(source_pedestrian_edges),
        "source_pedestrian_connection_count": len(source_pedestrian_connections),
        "replaced_pedestrian_edge_count": len(replaced_edge_ids),
        "replaced_pedestrian_edge_ids": replaced_edge_ids,
        "added_pedestrian_edge_count": len(added_edge_ids),
        "added_pedestrian_edge_ids": added_edge_ids,
        "added_pedestrian_connection_count": added_connection_count,
        "updated_pedestrian_connection_count": updated_connection_count,
        "missing_pedestrian_edge_ids": missing_edge_ids,
        "missing_pedestrian_connection_keys": missing_connection_keys,
        "missing_crossing_edge_refs": missing_crossing_edge_refs,
        "policy": "scoped teacher crossing/walkingarea overlay; no outside-cell pedestrian copy",
    }
def _final_composite_parity_gate(
    *,
    teacher_net_file: Path,
    composite_net_file: Path | None,
    accepted_internal_replays: list[dict[str, object]],
    enabled: bool,
) -> dict[str, object]:
    if not enabled:
        return {"status": "skipped", "reason": "disabled"}
    if composite_net_file is None or not composite_net_file.exists():
        return {"status": "skipped", "reason": "missing_composite_net_file"}
    if not accepted_internal_replays:
        return {"status": "skipped", "reason": "no_accepted_internal_replays"}
    try:
        teacher_root = ET.parse(teacher_net_file).getroot()
        composite_root = ET.parse(composite_net_file).getroot()
    except (OSError, ET.ParseError) as exc:
        return {"status": "fail", "reason": f"parse_error: {exc}", "reports": []}

    reports: list[dict[str, object]] = []
    for replay in accepted_internal_replays:
        junction_id = str(replay.get("junction_id", ""))
        teacher_junction_id = str(replay.get("teacher_junction_id", ""))
        edge_map = _valid_edge_map(replay.get("edge_map", {}))
        if not junction_id or not teacher_junction_id or not edge_map:
            reports.append(
                {
                    "status": "fail",
                    "junction_id": junction_id,
                    "teacher_junction_id": teacher_junction_id,
                    "reason": "missing_final_parity_inputs",
                }
            )
            continue
        try:
            teacher_model = _extract_teacher_junction_model(teacher_root, teacher_net_file, teacher_junction_id)
            candidate_model = _extract_teacher_junction_model(composite_root, composite_net_file, junction_id)
            parity = _compare_teacher_models(
                teacher_model,
                candidate_model,
                edge_map=edge_map,
                teacher_junction_id=teacher_junction_id,
                candidate_junction_id=junction_id,
            )
            semantic_replay_gate = _teacher_guided_semantics_gate(parity)
            reports.append(
                {
                    "status": semantic_replay_gate["status"],
                    "junction_id": junction_id,
                    "teacher_junction_id": teacher_junction_id,
                    "semantic_replay_gate": semantic_replay_gate,
                    "parity": parity,
                }
            )
        except (ET.ParseError, OSError, KeyError, TypeError, ValueError) as exc:
            reports.append(
                {
                    "status": "fail",
                    "junction_id": junction_id,
                    "teacher_junction_id": teacher_junction_id,
                    "reason": f"extract_error: {exc}",
                }
            )
    return {
        "status": "pass" if reports and all(report.get("status") == "pass" for report in reports) else "fail",
        "checked_junction_count": len(reports),
        "reports": reports,
    }
def _shape_points(shape: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for token in shape.split():
        if "," not in token:
            continue
        x_value, y_value = token.split(",", 1)
        try:
            points.append((float(x_value), float(y_value)))
        except ValueError:
            continue
    return points
def _road_continuity_probe_summary(run_report: dict[str, Any]) -> dict[str, object]:
    counts: dict[str, int] = {}
    failure_counts: dict[str, int] = {}
    replay_count = 0
    for variant in run_report.get("variant_reports", []) or []:
        if not isinstance(variant, dict) or variant.get("expanded_scope_followup_emitted"):
            continue
        replay = variant.get("target_internal_replay")
        if not isinstance(replay, dict):
            continue
        replay_count += 1
        if replay.get("status") != "pass":
            failure_counts["status_not_pass"] = failure_counts.get("status_not_pass", 0) + 1
        for field in ROAD_CONTINUITY_COUNT_FIELDS:
            value = _int_count(replay.get(field, 0))
            if value:
                counts[field] = counts.get(field, 0) + value
        for field in ROAD_CONTINUITY_FAILURE_FIELDS:
            value = (
                _blocking_removed_stale_connection_count(replay)
                if field == "removed_stale_replaced_edge_connection_count"
                else _blocking_removed_stale_boundary_connection_count(replay)
                if field == "removed_stale_boundary_edge_connection_count"
                else _int_count(replay.get(field, 0))
            )
            if value:
                failure_counts[field] = failure_counts.get(field, 0) + value
    if not replay_count:
        status = "skipped"
    elif failure_counts:
        status = "fail"
    else:
        status = "pass"
    return {
        "road_continuity_gate_status": status,
        "road_continuity_replay_count": replay_count,
        "road_continuity_counts": dict(sorted(counts.items())),
        "road_continuity_failure_counts": dict(sorted(failure_counts.items())),
    }
def write_expanded_scope_plain_inputs(
    *,
    raw_node_file: Path,
    raw_edge_file: Path,
    raw_connection_file: Path,
    output_dir: Path,
    expanded_rebuild_scope: object,
    approach_endpoint_rebuild_plan: object | None = None,
    teacher_join_groups_by_cluster: dict[str, list[str]] | None = None,
    netconvert_binary: str = "netconvert",
    sumo_binary: str = "sumo",
    timeout_seconds: float = 240.0,
    command_runner: Any = run_command,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    node_file = output_dir / "expanded_scope.nod.xml"
    edge_file = output_dir / "expanded_scope.edg.xml"
    connection_file = output_dir / "expanded_scope.con.xml"
    net_file = output_dir / "expanded_scope.net.xml"

    scope = expanded_rebuild_scope if isinstance(expanded_rebuild_scope, dict) else {}
    raw_scope_junction_ids = [str(item) for item in scope.get("junction_ids", []) or [] if str(item)]
    core_junction_id = str(scope.get("core_junction_id", ""))
    requested_join_ids = scope.get("join_junction_ids", None)
    default_join_ids = [core_junction_id] if core_junction_id else raw_scope_junction_ids
    requested_join_ids_list = [
        str(item)
        for item in (requested_join_ids if requested_join_ids is not None else default_join_ids)
        if str(item)
    ]
    blocked_edge_ids = {str(item) for item in scope.get("blocked_teacher_edge_ids", []) or [] if str(item)}
    teacher_join_groups_by_cluster = teacher_join_groups_by_cluster or {}

    raw_nodes = {
        node.attrib["id"]: node
        for node in ET.parse(raw_node_file).getroot()
        if node.tag == "node" and node.attrib.get("id")
    }

    def expand_scope_ids(values: list[str]) -> set[str]:
        expanded: set[str] = set()
        for value in values:
            members = _sumo_cluster_member_ids(value)
            # Generated cluster ids are only expanded when their member ids
            # are present in the current plain source.  Otherwise retain the
            # id so the report can explain the missing teacher endpoint.
            present_members = [member for member in members if member in raw_nodes]
            if value.startswith("cluster_") and len(present_members) >= 2:
                expanded.update(present_members)
            elif value in raw_nodes:
                expanded.add(value)
            else:
                expanded.add(value)
        return expanded

    seed_node_ids = expand_scope_ids(raw_scope_junction_ids)
    join_seed_node_ids = expand_scope_ids(requested_join_ids_list)

    # A teacher expanded scope may list a generated cluster as context rather
    # than in join_junction_ids.  Recreate that cluster as a separate join;
    # do not merge it with the core junction.  Explicit join groups remain
    # authoritative when supplied by the caller.
    explicit_join_groups: list[list[str]] = []
    explicit_group = sorted(node_id for node_id in join_seed_node_ids if node_id in raw_nodes)
    if len(explicit_group) >= 2:
        explicit_join_groups.append(explicit_group)
    join_groups = list(explicit_join_groups)
    auto_cluster_join_count = 0
    for cluster_id in raw_scope_junction_ids:
        if not cluster_id.startswith("cluster_"):
            continue
        mapped_cluster_members = teacher_join_groups_by_cluster.get(cluster_id, [])
        cluster_members = sorted(
            member
            for member in (
                mapped_cluster_members
                if mapped_cluster_members
                else _sumo_cluster_member_ids(cluster_id)
            )
            if member in raw_nodes
        )
        if len(cluster_members) < 2:
            continue
        cluster_set = set(cluster_members)
        if any(cluster_set <= set(group) for group in join_groups):
            continue
        join_groups.append(cluster_members)
        auto_cluster_join_count += 1

    cluster_aliases: dict[str, str] = {}
    for group in join_groups:
        generated_id = _sumo_joined_cluster_id(group)
        if not generated_id:
            continue
        for source_cluster_id in raw_scope_junction_ids:
            if not source_cluster_id.startswith("cluster_"):
                continue
            mapped_source_members = teacher_join_groups_by_cluster.get(source_cluster_id, [])
            source_members = {
                member
                for member in (
                    mapped_source_members
                    if mapped_source_members
                    else _sumo_cluster_member_ids(source_cluster_id)
                )
                if member in raw_nodes
            }
            if source_members and source_members == set(group):
                cluster_aliases[source_cluster_id] = generated_id
        cluster_aliases.setdefault(generated_id, generated_id)

    def resolve_scope_endpoint(value: str) -> str:
        return cluster_aliases.get(value, value)

    joined_scope_junction_ids = [
        joined_id
        for joined_id in (_sumo_joined_cluster_id(group) for group in join_groups)
        if joined_id
    ]

    raw_edges = [edge for edge in ET.parse(raw_edge_file).getroot() if edge.tag == "edge"]
    selected_edges = [
        edge
        for edge in raw_edges
        if edge.attrib.get("id", "") in blocked_edge_ids
        or edge.attrib.get("from", "") in seed_node_ids
        or edge.attrib.get("to", "") in seed_node_ids
    ]
    selected_edge_ids = {edge.attrib.get("id", "") for edge in selected_edges if edge.attrib.get("id")}
    selected_node_ids = set(seed_node_ids)
    for edge in selected_edges:
        selected_node_ids.update(endpoint for endpoint in (edge.attrib.get("from", ""), edge.attrib.get("to", "")) if endpoint)

    edge_root = ET.Element("edges")
    endpoint_rewrites = _endpoint_rewrites(approach_endpoint_rebuild_plan)
    rewritten_endpoint_count = 0
    skipped_endpoint_rewrites = []
    for edge in selected_edges:
        copied_edge = copy.deepcopy(edge)
        edge_id = copied_edge.attrib.get("id", "")
        for endpoint_attr in ("from", "to"):
            original_endpoint = copied_edge.attrib.get(endpoint_attr, "")
            resolved_endpoint = resolve_scope_endpoint(original_endpoint)
            if resolved_endpoint != original_endpoint:
                copied_edge.set(endpoint_attr, resolved_endpoint)
                rewritten_endpoint_count += 1
        rewrite = endpoint_rewrites.get(edge_id)
        if rewrite is not None:
            desired_from, desired_to = rewrite
            desired_from = resolve_scope_endpoint(desired_from)
            desired_to = resolve_scope_endpoint(desired_to)
            missing_endpoint_ids = [
                node_id
                for node_id in (desired_from, desired_to)
                if node_id not in raw_nodes and node_id not in set(cluster_aliases.values())
            ]
            if missing_endpoint_ids:
                skipped_endpoint_rewrites.append(
                    {
                        "edge_id": edge_id,
                        "desired_from": desired_from,
                        "desired_to": desired_to,
                        "missing_endpoint_ids": missing_endpoint_ids,
                    }
                )
            else:
                copied_edge.set("from", desired_from)
                copied_edge.set("to", desired_to)
                selected_node_ids.update((desired_from, desired_to))
                rewritten_endpoint_count += 1
        edge_root.append(copied_edge)

    join_node_ids = sorted({node_id for group in join_groups for node_id in group})
    if len(join_groups) == 1 and joined_scope_junction_ids:
        joined_scope_junction_id = joined_scope_junction_ids[0]
    elif core_junction_id in raw_nodes:
        joined_scope_junction_id = core_junction_id
    elif joined_scope_junction_ids:
        joined_scope_junction_id = joined_scope_junction_ids[0]
    else:
        joined_scope_junction_id = ""

    node_root = ET.Element("nodes")
    stale_joined_node_ids = set(joined_scope_junction_ids)
    # Remove a source cluster node only when this invocation recreated it as a
    # join group.  If the current plain source contains only the already
    # materialized cluster node (without all source members), preserve it;
    # deleting it would turn a later sequential export into a split cluster.
    stale_joined_node_ids.update(
        cluster_id
        for cluster_id in raw_scope_junction_ids
        if cluster_id.startswith("cluster_") and cluster_id in cluster_aliases
    )
    for node_id in sorted(node_id for node_id in selected_node_ids if node_id in raw_nodes):
        if node_id in stale_joined_node_ids:
            continue
        node_root.append(copy.deepcopy(raw_nodes[node_id]))
    if join_groups:
        join_definition = build_junction_join_definition(
            [
                {
                    "source": "teacher_guided_expanded_scope",
                    "candidate_id": _sumo_joined_cluster_id(group),
                    "decision": "join",
                    # The expanded scope is not a radius guess: it is the
                    # explicit, already selected teacher target for this
                    # materialization.  Mark that narrow decision as confirmed
                    # so the generic join writer does not downgrade it back to
                    # <joinExclude>.
                    "confidence": "target_evidence_confirmed",
                    "node_ids": group,
                    "reason": "teacher-guided expanded scope restores an explicit reference cluster",
                }
                for group in join_groups
            ],
            output_dir=output_dir,
            prefix="expanded_scope",
        )
    elif core_junction_id in raw_nodes:
        join_definition = {}
    else:
        join_definition = {}

    connection_root = ET.Element("connections")
    selected_edge_endpoints = {
        edge.attrib.get("id", ""): (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
        for edge in edge_root.findall("edge")
        if edge.attrib.get("id")
    }
    dropped_connection_count = 0
    for connection in ET.parse(raw_connection_file).getroot():
        if (
            connection.tag == "connection"
            and connection.attrib.get("from", "") in selected_edge_ids
            and connection.attrib.get("to", "") in selected_edge_ids
            and _connection_edges_are_adjacent(connection, selected_edge_endpoints)
        ):
            connection_root.append(copy.deepcopy(connection))
        elif connection.tag == "connection" and (
            connection.attrib.get("from", "") in selected_edge_ids or connection.attrib.get("to", "") in selected_edge_ids
        ):
            dropped_connection_count += 1

    ET.indent(node_root, space="    ")
    ET.indent(edge_root, space="    ")
    ET.indent(connection_root, space="    ")
    ET.ElementTree(node_root).write(node_file, encoding="utf-8", xml_declaration=True)
    ET.ElementTree(edge_root).write(edge_file, encoding="utf-8", xml_declaration=True)
    ET.ElementTree(connection_root).write(connection_file, encoding="utf-8", xml_declaration=True)

    command = [
        netconvert_binary,
        "--node-files",
        ",".join(
            [node_file.name]
            + ([Path(str(join_definition["nodes_patch_file"])).name] if join_definition.get("nodes_patch_file") else [])
        ),
        "--edge-files",
        edge_file.name,
        "--connection-files",
        connection_file.name,
        "--output-file",
        net_file.name,
    ]
    missing_node_ids = sorted(
        node_id
        for node_id in selected_node_ids
        if node_id not in raw_nodes and node_id not in set(joined_scope_junction_ids)
    )
    missing_blocked_edge_ids = sorted(edge_id for edge_id in blocked_edge_ids if edge_id not in selected_edge_ids)
    missing_desired_endpoint_ids = {
        resolve_scope_endpoint(str(item))
        for item in scope.get("missing_desired_endpoint_ids", []) or []
        if str(item)
    }
    blocking_missing_node_ids = sorted(
        node_id
        for node_id in missing_node_ids
        if node_id not in join_node_ids
        and node_id not in join_seed_node_ids
        and node_id not in set(joined_scope_junction_ids)
        and node_id not in missing_desired_endpoint_ids
    )
    netconvert_report = _command_report(command_runner(command, cwd=output_dir, timeout_seconds=timeout_seconds))
    sumo_command = [
        sumo_binary,
        "-n",
        net_file.name,
        "--no-step-log",
        "true",
        "--duration-log.disable",
        "true",
        "--begin",
        "0",
        "--end",
        "1",
    ]
    if netconvert_report.get("status") == "pass":
        sumo_report = _command_report(command_runner(sumo_command, cwd=output_dir, timeout_seconds=timeout_seconds))
    else:
        sumo_report = {"status": "skipped", "reason": "netconvert_failed"}
    joined_scope_junction_missing_from_net = False
    if netconvert_report.get("status") == "pass" and joined_scope_junction_id:
        try:
            joined_scope_junction_missing_from_net = joined_scope_junction_id not in _net_junction_ids(net_file)
        except (ET.ParseError, OSError):
            joined_scope_junction_missing_from_net = True
    blocking_missing_joined_scope_junction_ids = (
        [joined_scope_junction_id] if joined_scope_junction_missing_from_net else []
    )
    probe_status = "pass" if netconvert_report.get("status") == "pass" and sumo_report.get("status") == "pass" else "fail"
    return {
        "status": "review"
        if blocking_missing_node_ids or missing_blocked_edge_ids or blocking_missing_joined_scope_junction_ids
        else probe_status,
        "claim_status": "diagnostic-demo",
        "recommended_action": "run_netconvert_scope_probe",
        "node_file": str(node_file),
        "edge_file": str(edge_file),
        "connection_file": str(connection_file),
        "net_file": str(net_file),
        "netconvert_command": command,
        "sumo_command": sumo_command,
        "netconvert": netconvert_report,
        "sumo_load": sumo_report,
        "join_nodes_patch_file": str(join_definition.get("nodes_patch_file", "")),
        "join_definition_file": str(join_definition.get("definition_file", "")),
        "join_definition_csv": str(join_definition.get("definition_csv", "")),
        "join_explicit_join_count": join_definition.get("explicit_join_count", 0),
        "joined_scope_junction_id": joined_scope_junction_id,
        "joined_scope_junction_ids": joined_scope_junction_ids,
        "seed_node_ids": sorted(seed_node_ids),
        "join_node_ids": sorted({*join_seed_node_ids, *join_node_ids}),
        "join_groups": join_groups,
        "auto_cluster_join_count": auto_cluster_join_count,
        "cluster_aliases": cluster_aliases,
        "blocked_edge_ids": sorted(blocked_edge_ids),
        "missing_node_ids": missing_node_ids,
        "blocking_missing_node_ids": blocking_missing_node_ids,
        "missing_blocked_edge_ids": missing_blocked_edge_ids,
        "joined_scope_junction_missing_from_net": joined_scope_junction_missing_from_net,
        "blocking_missing_joined_scope_junction_ids": blocking_missing_joined_scope_junction_ids,
        "rewritten_endpoint_count": rewritten_endpoint_count,
        "skipped_endpoint_rewrites": skipped_endpoint_rewrites,
        "dropped_connection_count": dropped_connection_count,
        "node_count": len(node_root.findall("node")),
        "edge_count": len(edge_root.findall("edge")),
        "connection_count": len(connection_root.findall("connection")),
    }
def _same_id_tls_matches_teacher(
    teacher_root: ET.Element,
    candidate_root: ET.Element,
    teacher_net_file: Path,
    candidate_net_file: Path,
    junction_id: str,
    candidate_junction: ET.Element,
) -> bool:
    if not _teacher_junction_has_tls(candidate_root, junction_id, candidate_junction):
        return False
    try:
        teacher_model = _extract_teacher_junction_model(teacher_root, teacher_net_file, junction_id)
        candidate_model = _extract_teacher_junction_model(candidate_root, candidate_net_file, junction_id)
    except (ET.ParseError, OSError, KeyError, TypeError, ValueError):
        return False
    teacher = _teacher_parity_summary(teacher_model)
    candidate = _teacher_parity_summary(candidate_model)
    fields = (
        "incoming_vehicle_edge_count",
        "outgoing_vehicle_edge_count",
        "vehicle_connection_count",
        "controlled_vehicle_link_count",
        "controlled_link_index_count",
        "controlled_duplicate_link_index_count",
    )
    return all(teacher.get(field) == candidate.get(field) for field in fields)
def _candidate_nodes_from_exact_teacher_approach_edges(
    teacher_model: dict[str, object],
    candidate_edges_by_id: dict[str, ET.Element],
    candidate_junction_ids: set[str],
) -> tuple[list[str], dict[str, str]]:
    node_ids = []
    edge_map = {}
    for direction, endpoint_attr in (("incoming", "to"), ("outgoing", "from")):
        for approach in _approaches(teacher_model, direction):
            edge_id = str(approach.get("edge_id", ""))
            candidate_edge_id, candidate_edge = _candidate_edge_by_exact_or_unsplit_id(edge_id, candidate_edges_by_id)
            if candidate_edge is None:
                continue
            edge_map[edge_id] = candidate_edge_id
            node_id = candidate_edge.attrib.get(endpoint_attr, "")
            if node_id in candidate_junction_ids:
                node_ids.append(node_id)
    return sorted(dict.fromkeys(node_ids)), dict(sorted(edge_map.items()))
def _stale_case_edge_map_entries(
    case_edge_map: dict[str, str],
    teacher_model: dict[str, object],
    candidate_model: dict[str, object],
    approach_edge_map: dict[str, str],
) -> dict[str, str]:
    stale: dict[str, str] = {}
    for direction in ("incoming", "outgoing"):
        teacher_edge_ids = {str(edge.get("edge_id", "")) for edge in _approaches(teacher_model, direction)}
        candidate_edge_ids = {str(edge.get("edge_id", "")) for edge in _approaches(candidate_model, direction)}
        for teacher_edge_id, candidate_edge_id in case_edge_map.items():
            if teacher_edge_id in approach_edge_map:
                continue
            if teacher_edge_id in teacher_edge_ids and candidate_edge_id not in candidate_edge_ids:
                stale[teacher_edge_id] = candidate_edge_id
    return dict(sorted(stale.items()))
def _edge_map_from_approach_endpoint_rebuild_plan(
    teacher_model: dict[str, object],
    approach_endpoint_rebuild_plan: object,
    *,
    teacher_junction_id: str = "",
    candidate_junction_id: str = "",
    plan_junction_id: str = "",
) -> dict[str, str]:
    if not isinstance(approach_endpoint_rebuild_plan, dict):
        return {}
    candidates_by_endpoint: dict[tuple[str, str, str], list[str]] = {}
    for item in approach_endpoint_rebuild_plan.get("edge_rebuilds", []) or []:
        if not isinstance(item, dict):
            continue
        edge_id = str(item.get("edge_id", "")).strip()
        direction = str(item.get("direction", "")).strip()
        if not direction and ":" in str(item.get("approach_key", "")):
            direction = str(item.get("approach_key", "")).split(":", 1)[0]
        desired_from = str(item.get("desired_from", "")).strip()
        desired_to = str(item.get("desired_to", "")).strip()
        if direction not in {"incoming", "outgoing"} or not edge_id or not desired_from or not desired_to:
            continue
        candidates_by_endpoint.setdefault((direction, desired_from, desired_to), []).append(edge_id)

    edge_map: dict[str, str] = {}
    target_junction_ids = list(dict.fromkeys(item for item in (candidate_junction_id, plan_junction_id) if item))
    for direction in ("incoming", "outgoing"):
        for teacher_edge in _approaches(teacher_model, direction):
            teacher_edge_id = str(teacher_edge.get("edge_id", "")).strip()
            if not teacher_edge_id:
                continue
            matches = []
            for target_junction_id in target_junction_ids or [""]:
                desired_from = _mapped_junction_ref(
                    str(teacher_edge.get("from", "")), teacher_junction_id, target_junction_id
                )
                desired_to = _mapped_junction_ref(str(teacher_edge.get("to", "")), teacher_junction_id, target_junction_id)
                matches.extend(candidates_by_endpoint.get((direction, desired_from, desired_to), []))
            unique_matches = sorted(set(matches))
            if len(unique_matches) == 1:
                edge_map[teacher_edge_id] = unique_matches[0]
    return dict(sorted(edge_map.items()))
def _drop_endpoint_mismatched_edge_map_entries(
    teacher_model: dict[str, object],
    candidate_model: dict[str, object],
    edge_map: dict[str, str],
    *,
    teacher_junction_id: str,
    candidate_junction_id: str,
) -> dict[str, str]:
    teacher_signatures = _approach_endpoint_signatures(
        teacher_model,
        edge_map=edge_map,
        source_junction_id=teacher_junction_id,
        target_junction_id=candidate_junction_id,
    )
    candidate_signatures = _approach_endpoint_signatures(candidate_model)
    keep: dict[str, str] = {}
    for teacher_edge_id, candidate_edge_id in edge_map.items():
        keys = [key for key in teacher_signatures if key.endswith(f":{candidate_edge_id}")]
        if keys and any(teacher_signatures[key] != candidate_signatures.get(key) for key in keys):
            continue
        keep[teacher_edge_id] = candidate_edge_id
    return keep
def _missing_teacher_movement_plan(
    teacher_model: dict[str, object],
    candidate_model: dict[str, object],
    *,
    edge_map: dict[str, str],
    teacher_junction_id: str,
    candidate_junction_id: str,
) -> list[dict[str, object]]:
    candidate_signatures = Counter(
        _vehicle_connection_signature(connection, edge_map=None, source_junction_id="", target_junction_id="")
        for connection in candidate_model.get("vehicle_connections", []) or []
        if isinstance(connection, dict)
    )
    missing = []
    for connection in teacher_model.get("vehicle_connections", []) or []:
        if not isinstance(connection, dict):
            continue
        teacher_from = str(connection.get("from", ""))
        teacher_to = str(connection.get("to", ""))
        source = edge_map.get(teacher_from)
        target = edge_map.get(teacher_to)
        if not source or not target:
            continue
        signature = _vehicle_connection_signature(
            connection,
            edge_map=edge_map,
            source_junction_id=teacher_junction_id,
            target_junction_id=candidate_junction_id,
        )
        if candidate_signatures[signature] > 0:
            candidate_signatures[signature] -= 1
            continue
        via = _mapped_internal_ref(str(connection.get("via", "")), teacher_junction_id, candidate_junction_id)
        missing.append(
            {
                "teacher_from_edge_id": teacher_from,
                "teacher_to_edge_id": teacher_to,
                "from_edge_id": source,
                "to_edge_id": target,
                "fromLane": str(connection.get("fromLane", "")),
                "toLane": str(connection.get("toLane", "")),
                "dir": str(connection.get("dir", "")),
                "state": str(connection.get("state", "")),
                "tl": _mapped_junction_ref(str(connection.get("tl", "")), teacher_junction_id, candidate_junction_id),
                "linkIndex": str(connection.get("linkIndex", "")),
                "via": via,
                "controlled": bool(connection.get("tl") and connection.get("linkIndex")),
                "has_internal_via": bool(via),
                "match_status": "missing_candidate_connection",
            }
        )
    return missing
def _shape_endpoints(shape: str) -> tuple[tuple[float, float], tuple[float, float]] | None:
    points = _split(shape)
    if not points:
        return None
    try:
        first_x, first_y = points[0].split(",")[:2]
        last_x, last_y = points[-1].split(",")[:2]
        return (float(first_x), float(first_y)), (float(last_x), float(last_y))
    except ValueError:
        return None
def _shape_points(shape: str) -> list[tuple[float, float]]:
    points = []
    for point in _split(shape):
        try:
            x, y = point.split(",")[:2]
            points.append((float(x), float(y)))
        except ValueError:
            continue
    return points
def _join_shape_text(first: str, second: str) -> str:
    joined: list[str] = []
    for shape in (first, second):
        for point in _split(shape):
            if not joined or joined[-1] != point:
                joined.append(point)
    return " ".join(joined)
def _mapped_spatial_attrs(
    attrs: dict[str, str],
    dx: float,
    dy: float,
    edge_map: dict[str, str],
    teacher_junction_id: str | None = None,
    candidate_junction_id: str | None = None,
) -> dict[str, str]:
    mapped = dict(attrs)
    teacher_internal_prefix = f":{teacher_junction_id}_" if teacher_junction_id else ""
    candidate_internal_prefix = f":{candidate_junction_id}_" if candidate_junction_id else ""
    for attr in ("id", "from", "to", "via"):
        if attr in mapped:
            mapped[attr] = _map_internal_ref(mapped[attr], teacher_internal_prefix, candidate_internal_prefix)
    if teacher_junction_id and candidate_junction_id:
        for attr in ("id", "from", "to", "tl"):
            if mapped.get(attr) == teacher_junction_id:
                mapped[attr] = candidate_junction_id
    if "x" in mapped:
        mapped["x"] = _format_xy(float(mapped["x"]) + dx)
    if "y" in mapped:
        mapped["y"] = _format_xy(float(mapped["y"]) + dy)
    for attr in ("shape", "outlineShape", "customShape"):
        if attr in mapped:
            mapped[attr] = _translate_shape(mapped[attr], dx, dy)
    if "crossingEdges" in mapped:
        mapped_edges = [
            edge_map.get(edge, _map_internal_ref(edge, teacher_internal_prefix, candidate_internal_prefix) if edge.startswith(":") else "")
            for edge in _split(mapped["crossingEdges"])
        ]
        mapped["crossingEdges"] = " ".join(edge for edge in mapped_edges if edge)
    return mapped
def _teacher_boundary_edge_ids_touching_internal_subgraph(
    connections: list[ET.Element],
    teacher_edges: dict[str, ET.Element],
    teacher_junction_id: str,
) -> list[str]:
    teacher_internal_prefix = f":{teacher_junction_id}_"
    edge_ids = []
    for connection in connections:
        if not _touches_target_internal_subgraph(connection, teacher_internal_prefix, teacher_junction_id):
            continue
        for attr in ("from", "to"):
            edge_id = connection.attrib.get(attr, "")
            teacher_edge = teacher_edges.get(edge_id)
            if (
                edge_id
                and not edge_id.startswith(teacher_internal_prefix)
                and teacher_edge is not None
                and teacher_junction_id in (teacher_edge.attrib.get("from"), teacher_edge.attrib.get("to"))
            ):
                edge_ids.append(edge_id)
    # A crossing can reference a roadway edge that has no vehicle connection
    # directly touching the target internal graph.  It is still part of the
    # cell boundary and must survive a scoped replay; otherwise the pedestrian
    # overlay would retain a dangling ``crossingEdges`` reference.
    for crossing in teacher_edges.values():
        if crossing.attrib.get("function") != "crossing":
            continue
        if not crossing.attrib.get("id", "").startswith(teacher_internal_prefix):
            continue
        for edge_id in _split(crossing.attrib.get("crossingEdges", "")):
            teacher_edge = teacher_edges.get(edge_id)
            if (
                edge_id
                and teacher_edge is not None
                and teacher_junction_id in (teacher_edge.attrib.get("from"), teacher_edge.attrib.get("to"))
            ):
                edge_ids.append(edge_id)
    return list(dict.fromkeys(edge_ids))
def _edge_lane_shapes(edge: ET.Element) -> list[str]:
    shapes = (lane.attrib.get("shape", "") for lane in edge.findall("lane"))
    return [_translate_shape(shape, 0.0, 0.0) if shape else "" for shape in shapes]
def _append_edge_lanes_to_destination_junction(root: ET.Element, edge: ET.Element) -> None:
    destination = edge.attrib.get("to", "")
    if not destination:
        return
    junction = next((item for item in root.findall("junction") if item.attrib.get("id") == destination), None)
    if junction is None:
        return
    lanes = [lane.attrib["id"] for lane in edge.findall("lane") if lane.attrib.get("id")]
    if not lanes:
        return
    inc_lanes = _split(junction.attrib.get("incLanes", ""))
    for lane in lanes:
        if lane not in inc_lanes:
            inc_lanes.append(lane)
    junction.set("incLanes", " ".join(inc_lanes))
def _remove_edge_lanes_from_destination_junction(
    root: ET.Element,
    edge: ET.Element,
    *,
    all_junctions: bool = False,
) -> None:
    lanes = {lane.attrib["id"] for lane in edge.findall("lane") if lane.attrib.get("id")}
    if not lanes:
        return
    if all_junctions:
        junctions = root.findall("junction")
    else:
        destination = edge.attrib.get("to", "")
        if not destination:
            return
        junction = next((item for item in root.findall("junction") if item.attrib.get("id") == destination), None)
        if junction is None:
            return
        junctions = [junction]
    for junction in junctions:
        inc_lanes = _split(junction.attrib.get("incLanes", ""))
        if not inc_lanes:
            continue
        filtered = [lane for lane in inc_lanes if lane not in lanes]
        if len(filtered) != len(inc_lanes):
            junction.set("incLanes", " ".join(filtered))
def _restore_non_target_internal_artifacts(
    *,
    source_file: Path,
    target_file: Path,
    exclude_junction_ids: set[str],
) -> dict[str, object]:
    if not source_file.exists():
        return _failure(f"source net file does not exist: {source_file}")
    if not target_file.exists():
        return _failure(f"target net file does not exist: {target_file}")

    source_root = ET.parse(source_file).getroot()
    target_tree = ET.parse(target_file)
    target_root = target_tree.getroot()
    junction_ids = {
        junction.attrib["id"]
        for root in (source_root, target_root)
        for junction in root.findall("junction")
        if junction.attrib.get("id") and not junction.attrib["id"].startswith(":")
    }
    junction_prefixes = [(f":{junction_id}_", junction_id) for junction_id in sorted(junction_ids, key=len, reverse=True)]
    owner_cache: dict[str, str] = {}

    def owner(value: str) -> str:
        if value in owner_cache:
            return owner_cache[value]
        candidates = (value, _via_lane_edge_id(value))
        if not any(edge_id.startswith(":") for edge_id in candidates):
            owner_cache[value] = ""
            return ""
        internal_owner = next(
            (
                junction_id
                for edge_id in candidates
                for prefix, junction_id in junction_prefixes
                if edge_id.startswith(prefix)
            ),
            "",
        )
        owner_cache[value] = internal_owner
        return internal_owner

    def is_restored_owner(value: str) -> bool:
        internal_owner = owner(value)
        return bool(internal_owner and internal_owner not in exclude_junction_ids)

    def connection_restored(connection: ET.Element) -> bool:
        return any(
            is_restored_owner(connection.attrib.get(attr, ""))
            for attr in ("from", "to", "via")
        )

    target_normal_junction_ids = {
        junction.attrib["id"]
        for junction in target_root.findall("junction")
        if junction.attrib.get("id") and not junction.attrib["id"].startswith(":")
    }

    def has_valid_normal_endpoints(edge: ET.Element) -> bool:
        internal_owner = owner(edge.attrib.get("id", ""))
        if internal_owner and internal_owner not in target_normal_junction_ids:
            return False
        return all(
            not node_id or node_id.startswith(":") or node_id in target_normal_junction_ids
            for node_id in (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
        )

    skipped_internal_edges_missing_junctions = []
    source_internal_edges = []
    for edge in source_root.findall("edge"):
        if not is_restored_owner(edge.attrib.get("id", "")):
            continue
        if not has_valid_normal_endpoints(edge):
            skipped_internal_edges_missing_junctions.append(
                {key: edge.attrib.get(key, "") for key in ("id", "from", "to")}
            )
            continue
        source_internal_edges.append(edge)
    target_internal_edge_index = None
    removed_internal_edges = 0
    for child in list(target_root):
        if child.tag == "edge" and is_restored_owner(child.attrib.get("id", "")):
            if target_internal_edge_index is None:
                target_internal_edge_index = list(target_root).index(child)
            target_root.remove(child)
            removed_internal_edges += 1
    if target_internal_edge_index is None:
        target_internal_edge_index = _first_junction_index(target_root)
    for offset, edge in enumerate(source_internal_edges):
        target_root.insert(target_internal_edge_index + offset, copy.deepcopy(edge))

    source_internal_junctions = [
        junction for junction in source_root.findall("junction") if is_restored_owner(junction.attrib.get("id", ""))
    ]
    target_internal_junction_index = None
    removed_internal_junctions = 0
    for child in list(target_root):
        if child.tag == "junction" and is_restored_owner(child.attrib.get("id", "")):
            if target_internal_junction_index is None:
                target_internal_junction_index = list(target_root).index(child)
            target_root.remove(child)
            removed_internal_junctions += 1
    if target_internal_junction_index is None:
        target_internal_junction_index = next(
            (index for index, child in enumerate(list(target_root)) if child.tag == "connection"),
            len(list(target_root)),
        )
    for offset, junction in enumerate(source_internal_junctions):
        target_root.insert(target_internal_junction_index + offset, copy.deepcopy(junction))

    removed_connections = 0
    retained_children = []
    for child in list(target_root):
        if child.tag == "connection" and connection_restored(child):
            removed_connections += 1
            continue
        retained_children.append(child)
    if removed_connections:
        target_root[:] = retained_children
    target_edge_ids = {edge.attrib["id"] for edge in target_root.findall("edge") if edge.attrib.get("id")}
    target_lane_counts = _net_lane_counts(target_root)
    lane_ids = {
        lane.attrib["id"]
        for edge in target_root.findall("edge")
        for lane in edge.findall("lane")
        if lane.attrib.get("id")
    }
    source_connections = []
    skipped_missing_edge_connections = []
    skipped_invalid_lane_connections = []
    skipped_missing_via_lane_connections = []
    for connection in source_root.findall("connection"):
        if not connection_restored(connection):
            continue
        from_edge = connection.attrib.get("from", "")
        to_edge = connection.attrib.get("to", "")
        if from_edge not in target_edge_ids or to_edge not in target_edge_ids:
            skipped_missing_edge_connections.append(
                {key: connection.attrib.get(key, "") for key in ("from", "to", "via")}
            )
            continue
        if not _connection_lane_indices_valid(connection, target_lane_counts):
            skipped_invalid_lane_connections.append(
                {key: connection.attrib.get(key, "") for key in ("from", "to", "fromLane", "toLane", "via")}
            )
            continue
        via_lane = connection.attrib.get("via", "")
        if via_lane and via_lane not in lane_ids:
            skipped_missing_via_lane_connections.append(
                {key: connection.attrib.get(key, "") for key in ("from", "to", "via")}
            )
            continue
        source_connections.append(connection)
    for connection in source_connections:
        target_root.append(copy.deepcopy(connection))
    restored_tls_ids = {
        connection.attrib.get("tl", "")
        for connection in source_connections
        if connection.attrib.get("tl") and connection.attrib.get("tl") not in exclude_junction_ids
    }
    tl_logic_report = _copy_referenced_tllogics(source_root, target_root, restored_tls_ids)

    restored_normal_junction_attr_count = 0
    restored_request_count = 0
    target_junctions = {
        junction.attrib["id"]: junction
        for junction in target_root.findall("junction")
        if junction.attrib.get("id") and not junction.attrib["id"].startswith(":")
    }
    restored_source_normal_junction_ids = set()
    for source_junction in source_root.findall("junction"):
        junction_id = source_junction.attrib.get("id", "")
        target_junction = target_junctions.get(junction_id)
        if not junction_id or junction_id in exclude_junction_ids or target_junction is None:
            continue
        restored_source_normal_junction_ids.add(junction_id)

        source_inc_lanes = source_junction.attrib.get("incLanes", "").split()
        source_int_lanes = source_junction.attrib.get("intLanes", "").split()
        source_requests = list(source_junction.findall("request"))
        source_inc_lanes_are_valid = all(lane in lane_ids for lane in source_inc_lanes)
        source_matrix_is_valid = all(lane in lane_ids for lane in source_int_lanes) and len(source_requests) in {
            0,
            len(source_int_lanes),
        }
        filtered_target_inc_lanes = [
            lane for lane in target_junction.attrib.get("incLanes", "").split() if lane in lane_ids
        ]
        filtered_target_int_lanes = [
            lane for lane in target_junction.attrib.get("intLanes", "").split() if lane in lane_ids
        ]
        new_attrs = dict(target_junction.attrib)
        for attr in ("type", "x", "y", "z", "shape", "customShape"):
            if attr in source_junction.attrib:
                new_attrs[attr] = source_junction.attrib[attr]
            elif attr == "customShape":
                new_attrs.pop(attr, None)
        new_attrs["incLanes"] = (
            source_junction.attrib.get("incLanes", "")
            if source_inc_lanes_are_valid
            else " ".join(filtered_target_inc_lanes)
        )
        if source_matrix_is_valid:
            new_attrs["intLanes"] = source_junction.attrib.get("intLanes", "")
            requests_to_copy = source_requests
        else:
            new_attrs["intLanes"] = " ".join(filtered_target_int_lanes)
            target_requests = list(target_junction.findall("request"))
            requests_to_copy = target_requests if len(target_requests) in {0, len(filtered_target_int_lanes)} else []
        if dict(target_junction.attrib) != new_attrs:
            target_junction.attrib.clear()
            target_junction.attrib.update(new_attrs)
            restored_normal_junction_attr_count += 1
        for request in list(target_junction.findall("request")):
            target_junction.remove(request)
        for request in requests_to_copy:
            target_junction.append(ET.Element("request", dict(request.attrib)))
            restored_request_count += 1

    for junction_id, target_junction in target_junctions.items():
        if junction_id in exclude_junction_ids or junction_id in restored_source_normal_junction_ids:
            continue
        current_inc_lanes = target_junction.attrib.get("incLanes", "").split()
        current_int_lanes = target_junction.attrib.get("intLanes", "").split()
        current_requests = list(target_junction.findall("request"))
        filtered_inc_lanes = [lane for lane in current_inc_lanes if lane in lane_ids]
        filtered_int_lanes = [lane for lane in current_int_lanes if lane in lane_ids]
        current_matrix_is_valid = all(lane in lane_ids for lane in current_int_lanes) and len(current_requests) in {
            0,
            len(current_int_lanes),
        }
        requests_to_keep = (
            current_requests
            if current_matrix_is_valid or len(current_requests) in {0, len(filtered_int_lanes)}
            else []
        )
        new_attrs = dict(target_junction.attrib)
        new_attrs["incLanes"] = " ".join(filtered_inc_lanes)
        new_attrs["intLanes"] = (
            target_junction.attrib.get("intLanes", "") if current_matrix_is_valid else " ".join(filtered_int_lanes)
        )
        attrs_changed = dict(target_junction.attrib) != new_attrs
        requests_changed = len(requests_to_keep) != len(current_requests)
        if not attrs_changed and not requests_changed:
            continue
        target_junction.attrib.clear()
        target_junction.attrib.update(new_attrs)
        for request in current_requests:
            target_junction.remove(request)
        for request in requests_to_keep:
            target_junction.append(ET.Element("request", dict(request.attrib)))
        restored_normal_junction_attr_count += 1

    if (
        removed_internal_edges
        or removed_internal_junctions
        or removed_connections
        or restored_normal_junction_attr_count
        or restored_request_count
        or tl_logic_report["copied_tllogic_count"]
        or tl_logic_report["replaced_tllogic_count"]
    ):
        ET.indent(target_root, space="    ")
        target_tree.write(target_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "source_file": str(source_file),
        "target_file": str(target_file),
        "exclude_junction_ids": sorted(exclude_junction_ids),
        "removed_non_target_internal_edge_count": removed_internal_edges,
        "restored_non_target_internal_edge_count": len(source_internal_edges),
        "skipped_non_target_internal_edge_missing_junction_count": len(skipped_internal_edges_missing_junctions),
        "skipped_non_target_internal_edge_missing_junctions": skipped_internal_edges_missing_junctions,
        "removed_non_target_internal_junction_count": removed_internal_junctions,
        "restored_non_target_internal_junction_count": len(source_internal_junctions),
        "removed_non_target_internal_connection_count": removed_connections,
        "restored_non_target_internal_connection_count": len(source_connections),
        "skipped_non_target_internal_connection_missing_edge_count": len(skipped_missing_edge_connections),
        "skipped_non_target_internal_connection_missing_edges": skipped_missing_edge_connections,
        "skipped_non_target_internal_connection_invalid_lane_count": len(skipped_invalid_lane_connections),
        "skipped_non_target_internal_connection_invalid_lanes": skipped_invalid_lane_connections,
        "skipped_non_target_internal_connection_missing_via_lane_count": len(skipped_missing_via_lane_connections),
        "skipped_non_target_internal_connection_missing_via_lanes": skipped_missing_via_lane_connections,
        "restored_non_target_normal_junction_attr_count": restored_normal_junction_attr_count,
        "restored_non_target_request_count": restored_request_count,
        "restored_non_target_tllogic_count": (
            tl_logic_report["copied_tllogic_count"] + tl_logic_report["replaced_tllogic_count"]
        ),
        "missing_non_target_tllogic_count": tl_logic_report["missing_source_tllogic_count"],
        "missing_non_target_tllogic_ids": tl_logic_report["missing_source_tllogic_ids"],
    }
def _restore_replayed_geometry_attrs(*, source_file: Path, target_file: Path, junction_id: str) -> dict[str, object]:
    if not source_file.exists():
        return _failure(f"source net file does not exist: {source_file}")
    if not target_file.exists():
        return _failure(f"target net file does not exist: {target_file}")

    internal_prefix = f":{junction_id}_"
    source_root = ET.parse(source_file).getroot()
    target_tree = ET.parse(target_file)
    target_root = target_tree.getroot()
    source_internal_edges = [
        edge
        for edge in source_root.findall("edge")
        if edge.attrib.get("id", "").startswith(internal_prefix)
    ]
    internal_edge_insert_index = None
    for child in list(target_root):
        if child.tag == "edge" and child.attrib.get("id", "").startswith(internal_prefix):
            if internal_edge_insert_index is None:
                internal_edge_insert_index = list(target_root).index(child)
            target_root.remove(child)
    if internal_edge_insert_index is None:
        internal_edge_insert_index = _first_junction_index(target_root)
    for offset, edge in enumerate(source_internal_edges):
        target_root.insert(internal_edge_insert_index + offset, copy.deepcopy(edge))

    source_internal_junctions = [
        junction
        for junction in source_root.findall("junction")
        if junction.attrib.get("id", "").startswith(internal_prefix)
    ]
    internal_junction_insert_index = None
    for child in list(target_root):
        if child.tag == "junction" and child.attrib.get("id", "").startswith(internal_prefix):
            if internal_junction_insert_index is None:
                internal_junction_insert_index = list(target_root).index(child)
            target_root.remove(child)
    if internal_junction_insert_index is None:
        internal_junction_insert_index = next(
            (index for index, child in enumerate(list(target_root)) if child.tag == "connection"),
            len(list(target_root)),
        )
    for offset, junction in enumerate(source_internal_junctions):
        target_root.insert(internal_junction_insert_index + offset, copy.deepcopy(junction))

    removed_connection_count = 0
    for connection in list(target_root.findall("connection")):
        if _touches_target_internal_subgraph(connection, internal_prefix, junction_id):
            target_root.remove(connection)
            removed_connection_count += 1
    restored_connection_count = 0
    for connection in source_root.findall("connection"):
        if _touches_target_internal_subgraph(connection, internal_prefix, junction_id):
            target_root.append(copy.deepcopy(connection))
            restored_connection_count += 1

    restored_edge_ids = {
        edge.attrib.get("id", "")
        for edge in source_root.findall("edge")
        if edge.attrib.get("id", "").startswith(internal_prefix)
    }
    for connection in source_root.findall("connection"):
        if not _touches_target_internal_subgraph(connection, internal_prefix, junction_id):
            continue
        for attr in ("from", "to"):
            edge_id = connection.attrib.get(attr, "")
            if edge_id:
                restored_edge_ids.add(edge_id)
        via_edge_id = _via_lane_edge_id(connection.attrib.get("via", ""))
        if via_edge_id:
            restored_edge_ids.add(via_edge_id)

    source_edges = {edge.attrib.get("id", ""): edge for edge in source_root.findall("edge") if edge.attrib.get("id")}
    target_edges = {edge.attrib.get("id", ""): edge for edge in target_root.findall("edge") if edge.attrib.get("id")}
    missing_edge_ids = []
    restored_lane_count = 0
    for edge_id in sorted(edge_id for edge_id in restored_edge_ids if edge_id):
        source_edge = source_edges.get(edge_id)
        target_edge = target_edges.get(edge_id)
        if source_edge is None or target_edge is None:
            missing_edge_ids.append(edge_id)
            continue
        target_lanes = {lane.attrib.get("index", ""): lane for lane in target_edge.findall("lane")}
        for source_lane in source_edge.findall("lane"):
            target_lane = target_lanes.get(source_lane.attrib.get("index", ""))
            if target_lane is None:
                continue
            before = {attr: target_lane.attrib.get(attr) for attr in GEOMETRY_RESTORE_LANE_ATTRS}
            for attr in GEOMETRY_RESTORE_LANE_ATTRS:
                if attr in source_lane.attrib:
                    target_lane.set(attr, source_lane.attrib[attr])
                else:
                    target_lane.attrib.pop(attr, None)
            after = {attr: target_lane.attrib.get(attr) for attr in GEOMETRY_RESTORE_LANE_ATTRS}
            if before != after:
                restored_lane_count += 1
    restored_request_count = 0
    restored_junction_attr_count = 0
    source_junction = source_root.find(f"junction[@id='{junction_id}']")
    target_junction = target_root.find(f"junction[@id='{junction_id}']")
    if source_junction is not None and target_junction is not None:
        before_attrs = dict(target_junction.attrib)
        target_junction.attrib.clear()
        target_junction.attrib.update(dict(source_junction.attrib))
        restored_junction_attr_count = 1 if before_attrs != target_junction.attrib else 0
    source_requests = source_junction.findall("request") if source_junction is not None else []
    if source_requests and target_junction is not None:
        for request in list(target_junction.findall("request")):
            target_junction.remove(request)
        for request in source_requests:
            target_junction.append(ET.Element("request", dict(request.attrib)))
        restored_request_count = len(source_requests)

    ET.indent(target_root, space="    ")
    target_tree.write(target_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "source_file": str(source_file),
        "target_file": str(target_file),
        "restored_internal_edge_count": len(source_internal_edges),
        "restored_internal_junction_count": len(source_internal_junctions),
        "removed_connection_count": removed_connection_count,
        "restored_connection_count": restored_connection_count,
        "restored_edge_count": len(restored_edge_ids) - len(missing_edge_ids),
        "restored_lane_count": restored_lane_count,
        "restored_junction_attr_count": restored_junction_attr_count,
        "restored_request_count": restored_request_count,
        "missing_edge_count": len(missing_edge_ids),
        "missing_edge_ids": missing_edge_ids,
    }

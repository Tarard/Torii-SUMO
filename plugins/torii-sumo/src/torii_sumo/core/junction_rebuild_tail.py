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

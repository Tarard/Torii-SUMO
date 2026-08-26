from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
from collections import Counter
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .command_runner import run_command
from .corridor_simplification import audit_alias_normalized_connections
from .junction_connection_audit import (
    compare_pedestrian_crossing_signatures,
    compare_tls_movement_signatures,
)
from .junction_teacher_model import (
    _extract_teacher_junction_model,
    extract_junction_pattern_exemplar,
    extract_teacher_junction_model,
    match_teacher_approaches,
    slot_edge_map_from_exemplar,
)
from .official_tls_rebuild import edge_lane_signature
from .junction_rebuild_tail import (  # noqa: F401 - compatibility re-export
    _add_green_phases_for_links,
    _append_edge_lanes_to_destination_junction,
    _approach_edge_signature,
    _approach_edge_signatures,
    _approach_endpoint_rebuild_plan,
    _approach_endpoint_signatures,
    _approaches,
    _blocking_removed_stale_boundary_connection_count,
    _blocking_removed_stale_connection_count,
    _candidate_nodes_from_exact_teacher_approach_edges,
    _capacity_gap_records,
    _command_report,
    _compare_teacher_models,
    _connection_key,
    _connection_key_record,
    _connection_link_indices,
    _connection_link_indices_fit,
    _connection_max_link_index,
    _connection_touches_any_edge,
    _connection_touches_walkingarea_internal,
    _controlled_link_count,
    _controlled_link_index_stats,
    _controlled_link_signature_group,
    _controlled_link_signatures,
    _controlled_pedestrian_link_signatures,
    _controlled_tls_connection_count,
    _controlled_vehicle_link_signatures,
    _copy_referenced_tllogics,
    _copy_teacher_walkingareas,
    _crossing_geometry_signatures,
    _crossing_signatures,
    _dict_mismatch_count,
    _drop_endpoint_mismatched_edge_map_entries,
    _edge_lane_shapes,
    _edge_map_from_approach_endpoint_rebuild_plan,
    _endpoint_rewrite_old_endpoint_ids,
    _failure,
    _final_composite_parity_gate,
    _format_xy,
    _hybrid_osm_approach_authority_policy,
    _internal_connection_signatures,
    _internal_edge_signature,
    _internal_edge_signatures,
    _internal_junction_signatures,
    _join_shape_text,
    _junction_signature,
    _lane_length_signature,
    _map_teacher_pedestrian_endpoint,
    _mapped_endpoint,
    _mapped_internal_ref,
    _mapped_junction_ref,
    _mapped_lane_ref,
    _mapped_lane_refs,
    _mapped_spatial_attrs,
    _missing_teacher_movement_plan,
    _model_junction_origin,
    _model_shape_delta,
    _model_tls_id,
    _net_junction_ids,
    _pad_tllogic_state_lengths,
    _pedestrian_crossing_delta_count,
    _pedestrian_tl_pairs_from_connections,
    _pedestrian_tl_pairs_from_records,
    _phase_has_green_for_index,
    _record_linkindex_capacity_gap,
    _relative_shape,
    _remove_edge_lanes_from_destination_junction,
    _remove_teacher_non_tls_tllogics,
    _request_signatures,
    _restore_false_traffic_light_junction_types,
    _restore_non_target_internal_artifacts,
    _restore_replayed_geometry_attrs,
    _road_continuity_probe_summary,
    _same_id_tls_matches_teacher,
    _semantic_layer_for_field,
    _semantic_layer_gates,
    _shape_endpoints,
    _shape_points,
    _split,
    _stale_case_edge_map_entries,
    _target_internal_replay_input_file,
    _teacher_boundary_edge_ids_touching_internal_subgraph,
    _teacher_guided_semantics_gate,
    _teacher_parity_summary,
    _tl_logic_insert_index,
    _tl_phase_signatures,
    _tllogic_min_state_length_by_id,
    _touches_target_pedestrian_ring,
    _translate_shape,
    _translated_lane_attrs,
    _uncontrolled_pedestrian_connection_signatures,
    _unique_connections_by_key,
    _variant_exception_report,
    _vehicle_connection_signature,
    _via_lane_edge_id,
    _walking_area_signatures,
    _write_teacher_guided_report,
    build_rebuild_candidate,
    build_tls_connection_repair_variant,
    restore_scoped_pedestrian_internal_semantics_after_normalize,
    restore_teacher_tls_connection_semantics_after_normalize,
    write_expanded_scope_plain_inputs,
    write_missing_edge_type_patch,
    write_teacher_connection_plan,
    write_teacher_endpoint_patch_nodes,
    write_teacher_lane_patch_edges,
    write_teacher_tllogic_net,
    write_teacher_vehicle_connection_attrs_net,
)
from .junction_rebuild_helpers import (  # noqa: F401 - compatibility re-export
    _approach_edges,
    _approach_integrity_failure_counts,
    _approach_integrity_status,
    _attach_candidate_template_context,
    _attach_teacher_pattern_template,
    _blocking_sequential_overlap_edge_ids,
    _candidate_connection_mode_scope_ids,
    _candidate_edge_by_exact_or_unsplit_id,
    _candidate_lane_counts,
    _command_path,
    _connection_edges_are_adjacent,
    _connection_lane_indices_valid,
    _conservative_join_node_ids,
    _convex_hull,
    _edge_drop_requires_review,
    _edge_family_id,
    _edge_file_ids,
    _edge_file_lane_counts,
    _edge_is_pedestrian_only,
    _edge_lane_count,
    _edge_type_signature,
    _endpoint_rewrites,
    _expand_fragmented_tls_join_scope_candidate,
    _expanded_rebuild_scope,
    _first_junction_index,
    _geometry_anchor_junctions_by_id,
    _int_count,
    _is_turnaround_connection,
    _joined_lane_length,
    _junction_pattern_delta_by_id,
    _junction_pattern_delta_keys,
    _junction_pattern_record_by_id,
    _junction_pattern_template_by_key,
    _junction_within_radius,
    _junction_xy,
    _lanes_by_index,
    _limit_ready_repair_candidates,
    _load_geometry_anchor_edges,
    _map_internal_ref,
    _missing_teacher_edge_endpoint_ids,
    _net_contains_normal_junctions,
    _net_lane_counts,
    _netedit_review_actions,
    _normalize_joined_junction_ids,
    _opposite_direction_edge_id,
    _plain_crossing_node_id,
    _plain_edge_endpoints,
    _plain_node_ids,
    _polygon_area,
    _prefer_existing_exact_edge_ids,
    _preserve_boundary_operational_attributes,
    _primary_edge_shape,
    _prune_plain_node_controlled_inner_edges,
    _prune_plain_tls_against_teacher,
    _queue_path,
    _real_junction_ids,
    _report_used_unrestored_normalized_replay,
    _restore_geometry_anchor_junctions,
    _semantic_failure_counts,
    _semantic_layer_gate_counts,
    _should_emit,
    _signed_edge_family_id,
    _split_cluster_member_residuals,
    _stable_digest,
    _stage_file,
    _string_list,
    _sumo_cluster_member_ids,
    _sumo_joined_cluster_id,
    _teacher_boundary_edge_has_target_junction,
    _teacher_guided_candidate_sort_key,
    _teacher_junction_has_tls,
    _teacher_pattern_contexts,
    _teacher_pattern_metric_is_positive,
    _teacher_template_count_for_case,
    _teacher_to_candidate_delta,
    _tls_repair_actions,
    _touches_other_internal_owner,
    _touches_target_internal_owner,
    _touches_target_internal_subgraph,
    _valid_edge_map,
    _write_connections,
    _write_join_scope_connection_file,
    _write_join_scope_tllogic_file,
    _write_teacher_guided_promotion_gate,
    _write_teacher_guided_queue_csv,
)


APPROACH_INTEGRITY_FAILURE_FIELDS = {
    "approach_edge_signature_mismatch_count",
    "approach_endpoint_signature_mismatch_count",
    "incoming_vehicle_edge_count",
    "outgoing_vehicle_edge_count",
}

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

GEOMETRY_RESTORE_LANE_ATTRS = (
    "speed",
    "shape",
    "length",
    "width",
    "endOffset",
    "customShape",
    "outlineShape",
)

BOUNDARY_EDGE_OPERATIONAL_ATTRS = (
    "type",
    "priority",
    "name",
    "spreadType",
    "allow",
    "disallow",
    "speed",
    "width",
)

BOUNDARY_LANE_OPERATIONAL_ATTRS = (
    "speed",
    "width",
    "allow",
    "disallow",
    "endOffset",
    "acceleration",
    "changeLeft",
    "changeRight",
    "stopOffset",
)

TURNAROUND_DIR = "t"




def build_teacher_guided_repair_queue(
    *,
    teacher_net_file: Path,
    candidate_net_file: Path,
    reference_join_audit_report: dict[str, Any],
    output_dir: Path,
    prefix: str = "teacher_guided_repair",
    max_ready_candidates: int | None = None,
) -> dict[str, object]:
    if not teacher_net_file.exists():
        return _failure(f"teacher net file does not exist: {teacher_net_file}")
    if not candidate_net_file.exists():
        return _failure(f"candidate net file does not exist: {candidate_net_file}")
    teacher_net_file = teacher_net_file.resolve()
    candidate_net_file = candidate_net_file.resolve()
    output_dir = output_dir.resolve()

    output_dir.mkdir(parents=True, exist_ok=True)
    teacher_root = ET.parse(teacher_net_file).getroot()
    candidate_root = ET.parse(candidate_net_file).getroot()
    teacher_edges = {edge.attrib["id"]: edge for edge in teacher_root.findall("edge") if edge.attrib.get("id")}
    candidate_edges_by_id = {edge.attrib["id"]: edge for edge in candidate_root.findall("edge") if edge.attrib.get("id")}
    candidate_edge_ids = set(candidate_edges_by_id)
    matched_cases = [
        case
        for case in reference_join_audit_report.get("matched_cases", []) or []
        if isinstance(case, dict)
    ]
    pattern_deltas = _junction_pattern_delta_by_id(reference_join_audit_report)
    pattern_records = _junction_pattern_record_by_id(reference_join_audit_report)
    pattern_templates = _junction_pattern_template_by_key(reference_join_audit_report)
    same_id_pattern_cases = _same_id_pattern_cases(
        pattern_deltas,
        matched_cases,
        teacher_root,
        candidate_root,
    )
    same_id_tls_cases = _same_id_tls_mismatch_cases(
        [*matched_cases, *same_id_pattern_cases],
        teacher_root,
        candidate_root,
        teacher_net_file,
        candidate_net_file,
    )
    matched_cases = [*matched_cases, *same_id_pattern_cases, *same_id_tls_cases]
    topology_fragmented_tls_cases = _topology_fragmented_tls_cases(
        matched_cases,
        teacher_root,
        candidate_root,
        teacher_net_file,
        candidate_edges_by_id,
    )
    matched_cases = [*matched_cases, *topology_fragmented_tls_cases]
    topology_fragmented_non_tls_cases = _topology_fragmented_non_tls_cases(
        matched_cases,
        teacher_root,
        candidate_root,
        teacher_net_file,
        candidate_edges_by_id,
    )
    matched_cases = [*matched_cases, *topology_fragmented_non_tls_cases]
    turnaround_only_lane_cases = _turnaround_only_lane_cases(matched_cases, teacher_root, candidate_root)
    matched_cases = [*matched_cases, *turnaround_only_lane_cases]
    matched_cases.sort(
        key=lambda case: _teacher_guided_case_sort_key(case, pattern_records, pattern_templates)
    )
    repair_candidates = []
    tls_alignment_by_reference_id = {
        str(pair.get("reference_tl_id", "")): pair
        for pair in (
            (reference_join_audit_report.get("tls_controller_alignment", {}) or {}).get("pairs", [])
            if isinstance(reference_join_audit_report.get("tls_controller_alignment", {}), dict)
            else []
        )
        if isinstance(pair, dict) and str(pair.get("reference_tl_id", ""))
    }
    for case in matched_cases:
        candidate = _attach_teacher_pattern_template(
            _attach_junction_pattern_delta(
                _teacher_guided_repair_candidate(
                    case=case,
                    teacher_net_file=teacher_net_file,
                    candidate_net_file=candidate_net_file,
                    teacher_root=teacher_root,
                    candidate_root=candidate_root,
                    teacher_edges=teacher_edges,
                    candidate_edges_by_id=candidate_edges_by_id,
                    candidate_edge_ids=candidate_edge_ids,
                ),
                pattern_deltas,
            ),
            pattern_records,
            pattern_templates,
        )
        tls_alignment = tls_alignment_by_reference_id.get(str(candidate.get("reference_id", "")))
        if isinstance(tls_alignment, dict):
            candidate = {
                **candidate,
                "tls_reference_tl_id": str(tls_alignment.get("reference_tl_id", "")),
                "tls_candidate_tl_id": str(tls_alignment.get("candidate_tl_id", "")),
                "tls_candidate_junction_ids": [
                    str(item) for item in tls_alignment.get("candidate_junction_ids", []) or [] if str(item)
                ],
                "tls_approach_pairs": [
                    dict(item)
                    for item in tls_alignment.get("approach_pairs", []) or []
                    if isinstance(item, dict)
                ],
                "tls_reference_controlled_connection_count": int(
                    tls_alignment.get("reference_controlled_connection_count", 0) or 0
                ),
                "tls_candidate_controlled_connection_count": int(
                    tls_alignment.get("candidate_controlled_connection_count", 0) or 0
                ),
            }
        repair_candidates.append(candidate)
    repair_candidates.sort(key=_teacher_guided_candidate_sort_key)
    tls_repair_candidates = _tls_repair_candidates(reference_join_audit_report)
    if max_ready_candidates is not None and max_ready_candidates > 0:
        repair_candidates = _limit_ready_repair_candidates(repair_candidates, max_ready_candidates)
    ready_count = sum(
        1 for candidate in repair_candidates if candidate["candidate_status"] == "ready_for_teacher_guided_variant"
    )
    expanded_scope_count = sum(
        1 for candidate in repair_candidates if candidate["candidate_status"] == "needs_expanded_rebuild_scope"
    )
    queue_file = output_dir / f"{prefix}_queue.json"
    queue_csv_file = output_dir / f"{prefix}_queue.csv"
    report = {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "teacher_net_file": str(teacher_net_file),
        "candidate_net_file": str(candidate_net_file),
        "matched_case_count": len(matched_cases),
        "same_id_pattern_candidate_count": len(same_id_pattern_cases),
        "same_id_tls_candidate_count": len(same_id_tls_cases),
        "topology_fragmented_tls_candidate_count": len(topology_fragmented_tls_cases),
        "topology_fragmented_non_tls_candidate_count": len(topology_fragmented_non_tls_cases),
        "turnaround_only_lane_candidate_count": len(turnaround_only_lane_cases),
        "queued_case_count": len(repair_candidates),
        "queue_truncated": len(repair_candidates) < len(matched_cases),
        "queue_order_policy": "ready_then_same_id_tls_low_gap_then_largest_vehicle_movement_gap_then_highest_teacher_template_count",
        "max_ready_candidates": max_ready_candidates if max_ready_candidates is not None else "",
        "repair_candidate_count": len(repair_candidates),
        "ready_candidate_count": ready_count,
        "expanded_scope_candidate_count": expanded_scope_count,
        "blocked_candidate_count": len(repair_candidates) - ready_count - expanded_scope_count,
        "tls_repair_candidate_count": len(tls_repair_candidates),
        "tls_repair_category_counts": dict(
            sorted(Counter(str(candidate.get("repair_category", "")) for candidate in tls_repair_candidates).items())
        ),
        "tls_repair_candidates": tls_repair_candidates,
        "junction_pattern_mismatch_field_counts": reference_join_audit_report.get(
            "junction_pattern_mismatch_field_counts", {}
        ),
        "queue_file": str(queue_file),
        "queue_csv_file": str(queue_csv_file),
        "repair_candidates": repair_candidates,
        "review_policy": "queue only; run teacher-guided variants and inspect NetEdit connection mode before adoption",
    }
    queue_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_teacher_guided_queue_csv(queue_csv_file, repair_candidates)
    return report














def write_teacher_pedestrian_ring_net(
    *,
    candidate_net_file: Path,
    output_file: Path,
    junction_id: str,
    teacher_model: dict[str, object],
    edge_map: dict[str, str],
    teacher_junction_id: str | None = None,
    crossing_edge_overrides: dict[str, str | list[str]] | None = None,
) -> dict[str, object]:
    teacher_junction_id = teacher_junction_id or junction_id
    crossing_edge_overrides = crossing_edge_overrides or {}
    output_file.parent.mkdir(parents=True, exist_ok=True)

    tree = ET.parse(candidate_net_file)
    root = tree.getroot()
    internal_prefix = f":{junction_id}_"
    candidate_crossings = {
        frozenset(_split(edge.attrib.get("crossingEdges", ""))): edge.attrib["id"]
        for edge in root.findall("edge")
        if edge.attrib.get("id", "").startswith(internal_prefix) and edge.attrib.get("function") == "crossing"
    }

    crossing_map: dict[str, str] = {}
    for crossing in teacher_model.get("crossings", []) or []:
        if not isinstance(crossing, dict):
            continue
        teacher_crossing_id = str(crossing.get("edge_id", ""))
        mapped_edges = crossing_edge_overrides.get(teacher_crossing_id)
        if mapped_edges is None:
            mapped_edges = [edge_map.get(str(edge), "") for edge in crossing.get("crossingEdges", []) or []]
        if isinstance(mapped_edges, str):
            mapped_edges = [mapped_edges]
        candidate_crossing_id = candidate_crossings.get(frozenset(edge for edge in mapped_edges if edge))
        if candidate_crossing_id:
            crossing_map[teacher_crossing_id] = candidate_crossing_id

    teacher_link_pairs = _pedestrian_tl_pairs_from_records(teacher_model.get("pedestrian_connections", []) or [], teacher_junction_id)
    candidate_link_pairs = _pedestrian_tl_pairs_from_connections(root.findall("connection"), junction_id)
    walkingarea_map: dict[str, str] = {}
    for link_index, (teacher_walkingarea, teacher_crossing) in teacher_link_pairs.items():
        candidate_pair = candidate_link_pairs.get(link_index)
        if not candidate_pair:
            continue
        walkingarea_map[teacher_walkingarea] = candidate_pair[0]
        crossing_map.setdefault(teacher_crossing, candidate_pair[1])

    copied_walkingareas = []
    copied_walkingarea_count = 0
    if not walkingarea_map:
        copied_walkingareas, copied_walkingarea_count = _copy_teacher_walkingareas(
            root,
            junction_id=junction_id,
            teacher_junction_id=teacher_junction_id,
            teacher_junction=teacher_model.get("junction", {}),
            teacher_walkingareas=teacher_model.get("walking_areas", []),
        )
        for teacher_edge_id, candidate_edge_id in copied_walkingareas:
            walkingarea_map[teacher_edge_id] = candidate_edge_id

    pedestrian_geometry_update_count = _apply_teacher_pedestrian_internal_geometry(
        root,
        junction_id=junction_id,
        teacher_junction_id=teacher_junction_id,
        teacher_junction=teacher_model.get("junction", {}),
        edge_maps=(crossing_map, walkingarea_map),
        teacher_edges=(
            *(teacher_model.get("crossings", []) or []),
            *(teacher_model.get("walking_areas", []) or []),
        ),
    )

    kept_walkingareas = set(walkingarea_map.values())
    removed_walkingareas = []
    for edge in list(root.findall("edge")):
        edge_id = edge.attrib.get("id", "")
        if edge_id.startswith(internal_prefix) and edge.attrib.get("function") == "walkingarea" and edge_id not in kept_walkingareas:
            root.remove(edge)
            removed_walkingareas.append(edge_id)

    removed_connections = 0
    for connection in list(root.findall("connection")):
        if _touches_target_pedestrian_ring(connection, internal_prefix):
            root.remove(connection)
            removed_connections += 1

    edge_ids = {edge.attrib["id"] for edge in root.findall("edge") if edge.attrib.get("id")}
    lane_counts = _net_lane_counts(root)
    inserted_connections = 0
    skipped_connections = []
    skipped_missing_edge_connections = []
    skipped_invalid_lane_connections = []
    for connection in teacher_model.get("pedestrian_connections", []) or []:
        if not isinstance(connection, dict):
            continue
        mapped_from = _map_teacher_pedestrian_endpoint(str(connection.get("from", "")), walkingarea_map, crossing_map, edge_map)
        mapped_to = _map_teacher_pedestrian_endpoint(str(connection.get("to", "")), walkingarea_map, crossing_map, edge_map)
        if not mapped_from or not mapped_to:
            skipped_connections.append(connection)
            continue
        if mapped_from not in edge_ids or mapped_to not in edge_ids:
            skipped_connections.append(connection)
            skipped_missing_edge_connections.append(
                {
                    "from": mapped_from,
                    "to": mapped_to,
                    "teacher_from": str(connection.get("from", "")),
                    "teacher_to": str(connection.get("to", "")),
                }
            )
            continue
        attributes = {
            "from": mapped_from,
            "to": mapped_to,
            "fromLane": str(connection.get("fromLane", "0") or "0"),
            "toLane": str(connection.get("toLane", "0") or "0"),
            "dir": str(connection.get("dir", "s") or "s"),
            "state": str(connection.get("state", "M") or "M"),
        }
        if connection.get("tl"):
            attributes["tl"] = junction_id
        if connection.get("linkIndex"):
            attributes["linkIndex"] = str(connection["linkIndex"])
        if not _connection_lane_indices_valid(ET.Element("connection", attributes), lane_counts):
            skipped_connections.append(connection)
            skipped_invalid_lane_connections.append(attributes)
            continue
        root.append(ET.Element("connection", attributes))
        inserted_connections += 1

    existing_lane_ids = {
        lane.attrib["id"]
        for edge in root.findall("edge")
        for lane in edge.findall("lane")
        if lane.attrib.get("id")
    }
    for junction in root.findall("junction"):
        if junction.attrib.get("id") != junction_id:
            continue
        for attr in ("incLanes", "intLanes"):
            junction.set(attr, " ".join(lane for lane in _split(junction.attrib.get(attr, "")) if lane in existing_lane_ids))

    ET.indent(root, space="    ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "net_file": str(output_file),
        "crossing_map_count": len(crossing_map),
        "walkingarea_map_count": len(walkingarea_map),
        "copied_walkingarea_count": copied_walkingarea_count,
        "pedestrian_geometry_update_count": pedestrian_geometry_update_count,
        "kept_walkingarea_count": len(kept_walkingareas),
        "removed_walkingarea_count": len(removed_walkingareas),
        "removed_pedestrian_connection_count": removed_connections,
        "inserted_pedestrian_connection_count": inserted_connections,
        "skipped_pedestrian_connection_count": len(skipped_connections),
        "skipped_pedestrian_connections": skipped_connections,
        "skipped_pedestrian_connection_missing_edge_count": len(skipped_missing_edge_connections),
        "skipped_pedestrian_connection_missing_edges": skipped_missing_edge_connections,
        "skipped_pedestrian_connection_invalid_lane_count": len(skipped_invalid_lane_connections),
        "skipped_pedestrian_connection_invalid_lanes": skipped_invalid_lane_connections,
    }




def _apply_teacher_pedestrian_internal_geometry(
    root: ET.Element,
    *,
    junction_id: str,
    teacher_junction_id: str,
    teacher_junction: object,
    edge_maps: tuple[dict[str, str], ...],
    teacher_edges: object,
) -> int:
    if not isinstance(teacher_edges, tuple):
        return 0
    dx, dy = _teacher_to_candidate_delta(root, junction_id, teacher_junction)
    updated = 0
    for teacher_edge in teacher_edges:
        if not isinstance(teacher_edge, dict):
            continue
        teacher_edge_id = str(teacher_edge.get("edge_id", ""))
        candidate_edge_id = next((edge_map[teacher_edge_id] for edge_map in edge_maps if teacher_edge_id in edge_map), "")
        if not candidate_edge_id:
            candidate_edge_id = _mapped_internal_ref(teacher_edge_id, teacher_junction_id, junction_id)
        edge = root.find(f"edge[@id='{candidate_edge_id}']")
        lanes = teacher_edge.get("lanes", [])
        if edge is None or not isinstance(lanes, list):
            continue
        for lane in list(edge.findall("lane")):
            edge.remove(lane)
        for lane in lanes:
            if not isinstance(lane, dict):
                continue
            lane_attrs = _translated_lane_attrs(lane, teacher_junction_id, junction_id, dx, dy)
            ET.SubElement(edge, "lane", lane_attrs)
        updated += 1
    return updated








def write_teacher_target_internal_replay_net(
    *,
    candidate_net_file: Path,
    teacher_net_file: Path,
    output_file: Path,
    junction_id: str,
    edge_map: dict[str, str],
    teacher_junction_id: str | None = None,
    geometry_anchor_edge_file: Path | None = None,
    blend_geometry_anchor_at_target: bool = False,
    copy_unmapped_boundary_edges: bool = True,
    preserve_mapped_boundary_endpoints: bool = False,
    preserve_target_junction_shape: bool = False,
) -> dict[str, object]:
    teacher_junction_id = teacher_junction_id or junction_id
    output_file.parent.mkdir(parents=True, exist_ok=True)

    candidate_tree = ET.parse(candidate_net_file)
    candidate_root = candidate_tree.getroot()
    source_candidate_root = copy.deepcopy(candidate_root)
    teacher_root = ET.parse(teacher_net_file).getroot()
    internal_prefix = f":{junction_id}_"
    teacher_internal_prefix = f":{teacher_junction_id}_"
    candidate_edges_by_id = {edge.attrib["id"]: edge for edge in candidate_root.findall("edge") if edge.attrib.get("id")}
    candidate_edge_ids = set(candidate_edges_by_id)
    replay_edge_map = dict(edge_map)
    geometry_anchor_edges_by_id = _load_geometry_anchor_edges(geometry_anchor_edge_file)
    geometry_anchor_edge_ids = set(geometry_anchor_edges_by_id)

    target_candidate_junction = candidate_root.find(f"junction[@id='{junction_id}']")
    teacher_junction = teacher_root.find(f"junction[@id='{teacher_junction_id}']")
    if target_candidate_junction is None:
        return _failure(f"candidate junction not found: {junction_id}")
    if teacher_junction is None:
        return _failure(f"teacher junction not found: {junction_id}")
    original_target_junction_shape = target_candidate_junction.attrib.get("shape")
    original_target_custom_shape = target_candidate_junction.attrib.get("customShape")

    dx = float(target_candidate_junction.attrib.get("x", "0") or 0) - float(
        teacher_junction.attrib.get("x", "0") or 0
    )
    dy = float(target_candidate_junction.attrib.get("y", "0") or 0) - float(
        teacher_junction.attrib.get("y", "0") or 0
    )

    removed_internal_edges = []
    insert_index = None
    for child in list(candidate_root):
        if child.tag == "edge" and child.attrib.get("id", "").startswith(internal_prefix):
            if insert_index is None:
                insert_index = list(candidate_root).index(child)
            removed_internal_edges.append(child.attrib.get("id", ""))
            candidate_root.remove(child)
    if insert_index is None:
        insert_index = _first_junction_index(candidate_root)

    teacher_internal_edges = [
        edge
        for edge in teacher_root.findall("edge")
        if edge.attrib.get("id", "").startswith(teacher_internal_prefix)
    ]
    copied_boundary_edges = []
    copied_boundary_candidate_edges = []
    blended_geometry_anchor_edge_ids = []
    skipped_boundary_edges = []
    preserved_mapped_boundary_endpoints = []
    replaced_boundary_edge_ids: set[str] = set()
    boundary_insert_offset = 0
    teacher_edges = {edge.attrib["id"]: edge for edge in teacher_root.findall("edge") if edge.attrib.get("id")}
    teacher_junctions = {
        junction.attrib["id"]: junction
        for junction in teacher_root.findall("junction")
        if junction.attrib.get("id")
    }
    candidate_junctions_by_id = {
        junction.attrib["id"]: junction for junction in candidate_root.findall("junction") if junction.attrib.get("id")
    }
    candidate_junction_ids = set(candidate_junctions_by_id)
    geometry_anchor_junctions_by_id: dict[str, ET.Element] = {}
    copied_boundary_junctions = []
    replaced_boundary_source_edges: dict[str, ET.Element] = {}
    needed_boundary_edge_ids = _needed_unmapped_teacher_boundary_edges(
        teacher_root.findall("connection"),
        teacher_edges,
        replay_edge_map,
        candidate_edges_by_id,
        teacher_internal_prefix,
        teacher_junction_id,
        junction_id,
        dx,
        dy,
    )
    teacher_boundary_edge_ids = _teacher_boundary_edge_ids_touching_internal_subgraph(
        teacher_root.findall("connection"),
        teacher_edges,
        teacher_junction_id,
    )
    teacher_boundary_edge_ids = list(
        dict.fromkeys(
            [
                *teacher_boundary_edge_ids,
                *[
                    edge_id
                    for edge_id, edge in teacher_edges.items()
                    if teacher_junction_id in (edge.attrib.get("from"), edge.attrib.get("to"))
                ],
            ]
        )
    )
    for edge_id in teacher_boundary_edge_ids:
        teacher_edge = teacher_edges.get(edge_id)
        if (
            edge_id not in replay_edge_map
            and teacher_edge is not None
            and edge_id in candidate_edges_by_id
            and not _teacher_boundary_edge_needs_replay(
                teacher_edge,
                replay_edge_map,
                candidate_edges_by_id,
                teacher_junction_id,
                junction_id,
                dx,
                dy,
            )
        ):
            replay_edge_map[edge_id] = edge_id
    teacher_boundary_edge_id_set = set(teacher_boundary_edge_ids)
    teacher_boundary_mapped_counts = Counter(replay_edge_map.get(edge_id, edge_id) for edge_id in teacher_boundary_edge_ids)
    needed_boundary_edge_ids = list(
        dict.fromkeys(
            [
                *needed_boundary_edge_ids,
                *[
                    edge_id
                    for edge_id in teacher_boundary_edge_ids
                    if _teacher_boundary_edge_needs_replay(
                        teacher_edges[edge_id],
                        replay_edge_map,
                        candidate_edges_by_id,
                        teacher_junction_id,
                        junction_id,
                        dx,
                        dy,
                    )
                ],
                *[
                    edge_id
                    for edge_id in teacher_boundary_edge_ids
                    if (
                        replay_edge_map.get(edge_id, edge_id) in teacher_boundary_edge_id_set
                        and replay_edge_map.get(edge_id, edge_id) != edge_id
                    )
                    or teacher_boundary_mapped_counts[replay_edge_map.get(edge_id, edge_id)] > 1
                ],
            ]
        )
    )
    skipped_unmapped_teacher_boundary_edges = []
    if not copy_unmapped_boundary_edges:
        skipped_unmapped_teacher_boundary_edges = [
            edge_id
            for edge_id in needed_boundary_edge_ids
            if edge_id not in replay_edge_map
        ]
        needed_boundary_edge_ids = [
            edge_id
            for edge_id in needed_boundary_edge_ids
            if edge_id in replay_edge_map
        ]
    needed_boundary_edge_id_set = set(needed_boundary_edge_ids)
    mapped_boundary_counts = Counter(replay_edge_map.get(edge_id, edge_id) for edge_id in needed_boundary_edge_ids)
    preserved_colliding_boundary_edges = []
    for edge_id in needed_boundary_edge_ids:
        mapped_edge_id = replay_edge_map.get(edge_id, edge_id)
        if mapped_edge_id == edge_id:
            continue
        if mapped_edge_id in needed_boundary_edge_id_set or mapped_boundary_counts[mapped_edge_id] > 1:
            replay_edge_map[edge_id] = edge_id
            preserved_colliding_boundary_edges.append(edge_id)
    same_family_continuation_edge_map = _same_family_continuation_edge_map(
        teacher_edges,
        candidate_edges_by_id,
        replay_edge_map,
        teacher_junction_id=teacher_junction_id,
        candidate_junction_id=junction_id,
    )
    replay_edge_map.update(same_family_continuation_edge_map)
    for edge_id in needed_boundary_edge_ids:
        teacher_edge = teacher_edges[edge_id]
        mapped_from = junction_id if teacher_edge.attrib.get("from") == teacher_junction_id else teacher_edge.attrib.get("from", "")
        mapped_to = junction_id if teacher_edge.attrib.get("to") == teacher_junction_id else teacher_edge.attrib.get("to", "")
        mapped_candidate_edge_id = replay_edge_map.get(edge_id, edge_id)
        mapped_candidate_edge = candidate_edges_by_id.get(mapped_candidate_edge_id)
        if (
            mapped_candidate_edge is not None
            and not copy_unmapped_boundary_edges
            and preserve_mapped_boundary_endpoints
            and junction_id
            in (
            mapped_candidate_edge.attrib.get("from"),
            mapped_candidate_edge.attrib.get("to"),
            )
            and (
                (
                    teacher_edge.attrib.get("from") == teacher_junction_id
                    and mapped_candidate_edge.attrib.get("from") == junction_id
                )
                or (
                    teacher_edge.attrib.get("to") == teacher_junction_id
                    and mapped_candidate_edge.attrib.get("to") == junction_id
                )
            )
        ):
            candidate_from = mapped_candidate_edge.attrib.get("from", "")
            candidate_to = mapped_candidate_edge.attrib.get("to", "")
            if (mapped_from, mapped_to) != (candidate_from, candidate_to):
                preserved_mapped_boundary_endpoints.append(
                    {
                        "teacher_edge_id": edge_id,
                        "candidate_edge_id": mapped_candidate_edge_id,
                        "teacher_mapped_from": mapped_from,
                        "teacher_mapped_to": mapped_to,
                        "candidate_from": candidate_from,
                        "candidate_to": candidate_to,
                    }
                )
            mapped_from = candidate_from
            mapped_to = candidate_to
        for teacher_endpoint, mapped_endpoint in (
            (teacher_edge.attrib.get("from", ""), mapped_from),
            (teacher_edge.attrib.get("to", ""), mapped_to),
        ):
            if mapped_endpoint in candidate_junction_ids:
                continue
            teacher_endpoint_junction = teacher_junctions.get(teacher_endpoint)
            if teacher_endpoint_junction is None:
                continue
            copied_junction = _clone_transformed_boundary_junction(
                teacher_endpoint_junction,
                dx,
                dy,
                replay_edge_map,
                teacher_junction_id,
                junction_id,
            )
            candidate_root.insert(list(candidate_root).index(target_candidate_junction), copied_junction)
            candidate_junction_ids.add(mapped_endpoint)
            copied_boundary_junctions.append(mapped_endpoint)
        if mapped_from not in candidate_junction_ids or mapped_to not in candidate_junction_ids:
            skipped_boundary_edges.append(edge_id)
            continue
        copied_edge_id = replay_edge_map.get(edge_id, edge_id)
        copied_edge = _clone_transformed_boundary_edge(
            teacher_edge,
            copied_edge_id,
            dx,
            dy,
            replay_edge_map,
            teacher_junction_id,
            junction_id,
        )
        copied_edge.set("from", mapped_from)
        copied_edge.set("to", mapped_to)
        copied_edge_id = copied_edge.attrib.get("id", "")
        if not copied_edge_id:
            skipped_boundary_edges.append(edge_id)
            continue
        replaced_edge = candidate_edges_by_id.get(copied_edge_id)
        insert_at = insert_index + boundary_insert_offset
        if replaced_edge is not None:
            replaced_boundary_source_edges[copied_edge_id] = copy.deepcopy(replaced_edge)
            if copied_edge_id in geometry_anchor_edge_ids:
                geometry_source_edge = geometry_anchor_edges_by_id.get(
                    copied_edge_id,
                    replaced_edge,
                )
                if blend_geometry_anchor_at_target and _blend_geometry_anchor_at_target(
                    copied_edge,
                    geometry_source_edge,
                    junction_id,
                ):
                    blended_geometry_anchor_edge_ids.append(copied_edge_id)
                else:
                    _restore_existing_edge_geometry(
                        copied_edge,
                        geometry_source_edge,
                        candidate_root,
                        max_endpoint_delta=None,
                    )
            insert_at = list(candidate_root).index(replaced_edge)
            _remove_edge_lanes_from_destination_junction(candidate_root, replaced_edge)
            candidate_root.remove(replaced_edge)
            candidate_edge_ids.remove(copied_edge_id)
            replaced_boundary_edge_ids.add(copied_edge_id)
        candidate_root.insert(insert_at, copied_edge)
        if replaced_edge is None:
            boundary_insert_offset += 1
        candidate_edge_ids.add(copied_edge_id)
        candidate_edges_by_id[copied_edge_id] = copied_edge
        replay_edge_map[edge_id] = copied_edge_id
        _append_edge_lanes_to_destination_junction(candidate_root, copied_edge)
        copied_boundary_edges.append(edge_id)
        copied_boundary_candidate_edges.append(copied_edge_id)

    removed_stale_split_fragment_edges = []
    rewired_stale_split_fragment_connections = []
    stale_split_replacements: dict[str, tuple[str, str]] = {}
    stale_split_continuation_replacements: dict[str, str] = {}
    stale_split_remote_junction_ids: set[str] = set()
    stale_split_stale_junction_ids: set[str] = set()
    teacher_connections_by_via = {
        connection.attrib["via"]: connection
        for connection in teacher_root.findall("connection")
        if connection.attrib.get("via")
    }
    teacher_tllogic_ids = {tllogic.attrib.get("id", "") for tllogic in teacher_root.findall("tlLogic")}
    replay_boundary_candidate_edge_ids = list(
        dict.fromkeys(
            [
                *copied_boundary_candidate_edges,
                *[
                    replay_edge_map.get(edge_id, edge_id)
                    for edge_id in teacher_boundary_edge_ids
                    if replay_edge_map.get(edge_id, edge_id) in candidate_edges_by_id
                ],
            ]
        )
    )
    for edge_id in replay_boundary_candidate_edge_ids:
        copied_edge = candidate_edges_by_id.get(edge_id)
        if copied_edge is None:
            continue
        remote_attr = "to" if copied_edge.attrib.get("from") == junction_id else "from"
        remote_junction_id = copied_edge.attrib.get(remote_attr, "")
        if not remote_junction_id:
            continue
        copied_family = _signed_edge_family_id(edge_id)
        for candidate_edge_id, candidate_edge in list(candidate_edges_by_id.items()):
            if (
                candidate_edge_id == edge_id
                or candidate_edge_id.startswith(":")
                or _signed_edge_family_id(candidate_edge_id) != copied_family
                or candidate_edge.attrib.get(remote_attr) != remote_junction_id
            ):
                continue
            stale_split_replacements[candidate_edge_id] = (edge_id, remote_junction_id)
            source_edge = replaced_boundary_source_edges.get(edge_id)
            source_anchor_edge = geometry_anchor_edges_by_id.get(edge_id)
            if source_edge is not None and source_anchor_edge is not None:
                source_edge = copy.deepcopy(source_edge)
                _restore_existing_edge_geometry(
                    source_edge,
                    source_anchor_edge,
                    candidate_root,
                    max_endpoint_delta=None,
                )
            stale_split_edge = candidate_edge
            stale_split_anchor_edge = geometry_anchor_edges_by_id.get(
                candidate_edge_id
            )
            if stale_split_anchor_edge is not None:
                stale_split_edge = copy.deepcopy(candidate_edge)
                _restore_existing_edge_geometry(
                    stale_split_edge,
                    stale_split_anchor_edge,
                    candidate_root,
                    max_endpoint_delta=None,
                )
            if (
                source_edge is not None
                and {candidate_edge_id, edge_id} & geometry_anchor_edge_ids
                and _restore_joined_split_edge_geometry(
                    copied_edge,
                    stale_split_edge,
                    source_edge,
                )
            ):
                geometry_anchor_junctions_by_id.update(
                    _geometry_anchor_junctions_by_id(
                        {
                            candidate_edge_id: candidate_edge,
                            edge_id: source_edge,
                        },
                        candidate_junctions_by_id,
                        {candidate_edge_id, edge_id} & geometry_anchor_edge_ids,
                        target_junction_id=junction_id,
                    )
                )
            stale_split_remote_junction_ids.add(remote_junction_id)
            stale_endpoint_attr = "to" if remote_attr == "from" else "from"
            stale_junction_id = candidate_edge.attrib.get(stale_endpoint_attr, "")
            if stale_junction_id:
                stale_split_stale_junction_ids.add(stale_junction_id)
    for connection in list(candidate_root.findall("connection")):
        touched_stale_edge_ids = {
            edge_id
            for edge_id in (connection.attrib.get("from", ""), connection.attrib.get("to", ""))
            if edge_id in stale_split_replacements
        }
        if not touched_stale_edge_ids:
            continue
        if len(touched_stale_edge_ids) != 1:
            candidate_root.remove(connection)
            continue
        stale_edge_id = next(iter(touched_stale_edge_ids))
        replacement_edge_id, remote_junction_id = stale_split_replacements[stale_edge_id]
        original_from = connection.attrib.get("from", "")
        original_to = connection.attrib.get("to", "")
        stale_was_from = original_from == stale_edge_id
        stale_was_to = original_to == stale_edge_id
        if not connection.attrib.get("via", "").startswith(f":{remote_junction_id}_"):
            candidate_root.remove(connection)
            continue
        if stale_was_from:
            connection.set("from", replacement_edge_id)
        if stale_was_to:
            connection.set("to", replacement_edge_id)
        teacher_connection = teacher_connections_by_via.get(connection.attrib.get("via", ""))
        if teacher_connection is not None:
            candidate_continuation_edge_id = original_to if stale_was_from else original_from if stale_was_to else ""
            teacher_continuation_edge_id = (
                teacher_connection.attrib.get("to", "")
                if stale_was_from
                else teacher_connection.attrib.get("from", "")
                if stale_was_to
                else ""
            )
            existing_continuation_mapping = replay_edge_map.get(teacher_continuation_edge_id)
            if (
                candidate_continuation_edge_id
                and teacher_continuation_edge_id
                and candidate_continuation_edge_id != replacement_edge_id
                and candidate_continuation_edge_id not in stale_split_replacements
                and not candidate_continuation_edge_id.startswith(":")
                and candidate_continuation_edge_id in candidate_edges_by_id
                and teacher_continuation_edge_id in teacher_edges
                and _signed_edge_family_id(candidate_continuation_edge_id)
                == _signed_edge_family_id(teacher_continuation_edge_id)
                and (
                    existing_continuation_mapping is None
                    or existing_continuation_mapping == candidate_continuation_edge_id
                )
            ):
                stale_split_continuation_replacements[candidate_continuation_edge_id] = teacher_continuation_edge_id
                replay_edge_map[teacher_continuation_edge_id] = candidate_continuation_edge_id
            rewritten_from = connection.attrib.get("from", "")
            rewritten_to = connection.attrib.get("to", "")
            connection.attrib.clear()
            connection.attrib.update(dict(teacher_connection.attrib))
            connection.set("from", rewritten_from)
            connection.set("to", rewritten_to)
        rewired_stale_split_fragment_connections.append(dict(connection.attrib))
    for stale_edge_id in stale_split_replacements:
        stale_edge = candidate_edges_by_id.get(stale_edge_id)
        if stale_edge is None:
            continue
        _remove_edge_lanes_from_destination_junction(candidate_root, stale_edge, all_junctions=True)
        candidate_root.remove(stale_edge)
        candidate_edge_ids.discard(stale_edge_id)
        candidate_edges_by_id.pop(stale_edge_id, None)
        removed_stale_split_fragment_edges.append(stale_edge_id)
    stale_split_spatial_junction_ids = set(stale_split_remote_junction_ids)
    removed_cluster_member_residual_edges = []
    removed_cluster_member_residual_connections = []
    removed_cluster_member_residual_junctions = []
    cluster_member_residual_junction_ids = set()
    if junction_id.startswith("cluster_"):
        cluster_member_residual_junction_ids = {
            member_id
            for member_id in junction_id.removeprefix("cluster_").split("_")
            if member_id and member_id in candidate_junction_ids and member_id not in teacher_junctions
        }
    if cluster_member_residual_junction_ids:
        covered_boundary_families = {
            _signed_edge_family_id(edge_id)
            for edge_id in replay_boundary_candidate_edge_ids
            if edge_id and not edge_id.startswith(":")
        }
        protected_replay_edge_ids = {edge_id for edge_id in replay_edge_map.values() if edge_id}
        removable_member_edges = [
            edge_id
            for edge_id, edge in sorted(candidate_edges_by_id.items())
            if (
                edge_id not in protected_replay_edge_ids
                and edge_id not in teacher_edges
                and not edge_id.startswith(":")
                and edge.attrib.get("function") not in {"internal", "crossing", "walkingarea"}
                and _signed_edge_family_id(edge_id) in covered_boundary_families
                and (
                    edge.attrib.get("from", "") in cluster_member_residual_junction_ids
                    or edge.attrib.get("to", "") in cluster_member_residual_junction_ids
                )
            )
        ]
        for edge_id in removable_member_edges:
            edge = candidate_edges_by_id.get(edge_id)
            if edge is None:
                continue
            for connection in list(candidate_root.findall("connection")):
                if edge_id in (connection.attrib.get("from", ""), connection.attrib.get("to", "")):
                    removed_cluster_member_residual_connections.append(dict(connection.attrib))
                    candidate_root.remove(connection)
            _remove_edge_lanes_from_destination_junction(candidate_root, edge, all_junctions=True)
            candidate_root.remove(edge)
            candidate_edge_ids.discard(edge_id)
            candidate_edges_by_id.pop(edge_id, None)
            removed_cluster_member_residual_edges.append(edge_id)
        if removed_cluster_member_residual_edges:
            stale_split_spatial_junction_ids.update(cluster_member_residual_junction_ids)
    replayed_stale_split_continuation_edges = []
    replayed_stale_split_teacher_edge_ids: set[str] = set()

    def replay_stale_split_edge_geometry(candidate_edge_id: str, teacher_edge_id: str) -> bool:
        existing_edge = candidate_edges_by_id.get(candidate_edge_id)
        teacher_edge = teacher_edges.get(teacher_edge_id)
        if existing_edge is None or teacher_edge is None:
            return False
        copied_edge = _clone_transformed_boundary_edge(
            teacher_edge,
            candidate_edge_id,
            dx,
            dy,
            replay_edge_map,
            teacher_junction_id,
            junction_id,
        )
        if candidate_edge_id in geometry_anchor_edge_ids:
            _restore_existing_edge_geometry(
                copied_edge,
                geometry_anchor_edges_by_id.get(candidate_edge_id, existing_edge),
                candidate_root,
                max_endpoint_delta=None,
            )
        insert_at = list(candidate_root).index(existing_edge)
        _remove_edge_lanes_from_destination_junction(candidate_root, existing_edge, all_junctions=True)
        candidate_root.remove(existing_edge)
        candidate_root.insert(insert_at, copied_edge)
        candidate_edge_ids.add(candidate_edge_id)
        candidate_edges_by_id[candidate_edge_id] = copied_edge
        _append_edge_lanes_to_destination_junction(candidate_root, copied_edge)
        for endpoint in (copied_edge.attrib.get("from", ""), copied_edge.attrib.get("to", "")):
            if endpoint and endpoint != junction_id:
                stale_split_spatial_junction_ids.add(endpoint)
        return True

    for candidate_edge_id, teacher_edge_id in sorted(stale_split_continuation_replacements.items()):
        if replay_stale_split_edge_geometry(candidate_edge_id, teacher_edge_id):
            replayed_stale_split_continuation_edges.append(candidate_edge_id)
            replayed_stale_split_teacher_edge_ids.add(teacher_edge_id)
    replayed_stale_split_followup_edges = []
    for teacher_edge_id in sorted(replayed_stale_split_teacher_edge_ids):
        for teacher_connection in teacher_root.findall("connection"):
            if teacher_connection.attrib.get("dir") == "t":
                continue
            from_edge_id = teacher_connection.attrib.get("from", "")
            to_edge_id = teacher_connection.attrib.get("to", "")
            if from_edge_id == teacher_edge_id:
                followup_teacher_edge_id = to_edge_id
            elif to_edge_id == teacher_edge_id:
                followup_teacher_edge_id = from_edge_id
            else:
                continue
            if (
                not followup_teacher_edge_id
                or followup_teacher_edge_id in replay_edge_map
                or followup_teacher_edge_id in teacher_boundary_edge_id_set
                or followup_teacher_edge_id.startswith(":")
            ):
                continue
            followup_teacher_edge = teacher_edges.get(followup_teacher_edge_id)
            followup_candidate_edge_id = followup_teacher_edge_id
            followup_candidate_edge = candidate_edges_by_id.get(followup_candidate_edge_id)
            if (
                followup_teacher_edge is None
                or followup_candidate_edge is None
                or not (
                    {
                        followup_candidate_edge.attrib.get("from", ""),
                        followup_candidate_edge.attrib.get("to", ""),
                    }
                    & stale_split_spatial_junction_ids
                )
                or not _edge_is_vehicle_continuation_candidate(followup_teacher_edge)
            ):
                continue
            replay_edge_map[followup_teacher_edge_id] = followup_candidate_edge_id
            if replay_stale_split_edge_geometry(followup_candidate_edge_id, followup_teacher_edge_id):
                replayed_stale_split_followup_edges.append(followup_candidate_edge_id)
    removed_teacher_absent_same_family_continuation_edges = []
    removed_teacher_absent_same_family_continuation_connections = []
    removed_teacher_absent_same_family_continuation_junctions = []
    replayed_stale_split_family_ids = {
        _edge_family_id(edge_id)
        for edge_id in [*replayed_stale_split_continuation_edges, *replayed_stale_split_followup_edges]
    }
    protected_candidate_edge_ids = set(replay_edge_map.values()) | {
        edge_id for edge_id in candidate_edges_by_id if edge_id in teacher_edges
    }
    stale_split_frontier_junction_ids = set(stale_split_spatial_junction_ids)
    removed_stale_split_dead_end_edges = []
    removed_stale_split_dead_end_connections = []
    teacher_dead_end_junction_ids = {
        endpoint
        for endpoint in stale_split_spatial_junction_ids
        if teacher_junctions.get(endpoint) is not None and teacher_junctions[endpoint].attrib.get("type") == "dead_end"
    }
    for edge_id, edge in list(candidate_edges_by_id.items()):
        if (
            edge_id in protected_candidate_edge_ids
            or edge_id.startswith(":")
            or edge_id in teacher_edges
            or _edge_family_id(edge_id) in replayed_stale_split_family_ids
            or not (
                edge.attrib.get("from", "") in teacher_dead_end_junction_ids
                or edge.attrib.get("to", "") in teacher_dead_end_junction_ids
            )
        ):
            continue
        for connection in list(candidate_root.findall("connection")):
            if edge_id in (connection.attrib.get("from", ""), connection.attrib.get("to", "")):
                removed_stale_split_dead_end_connections.append(dict(connection.attrib))
                candidate_root.remove(connection)
        _remove_edge_lanes_from_destination_junction(candidate_root, edge, all_junctions=True)
        candidate_root.remove(edge)
        candidate_edge_ids.discard(edge_id)
        candidate_edges_by_id.pop(edge_id, None)
        removed_stale_split_dead_end_edges.append(edge_id)
        for endpoint in (edge.attrib.get("from", ""), edge.attrib.get("to", "")):
            if endpoint:
                stale_split_frontier_junction_ids.add(endpoint)
                stale_split_spatial_junction_ids.add(endpoint)
    for endpoint in teacher_dead_end_junction_ids:
        teacher_dead_end_junction = teacher_junctions.get(endpoint)
        candidate_dead_end_junction = candidate_root.find(f"junction[@id='{endpoint}']")
        if teacher_dead_end_junction is not None and candidate_dead_end_junction is not None:
            candidate_dead_end_junction.set("intLanes", teacher_dead_end_junction.attrib.get("intLanes", ""))
    while replayed_stale_split_family_ids:
        removable_edge_ids = [
            edge_id
            for edge_id, edge in sorted(candidate_edges_by_id.items())
            if (
                edge_id not in protected_candidate_edge_ids
                and not edge_id.startswith(":")
                and _edge_family_id(edge_id) in replayed_stale_split_family_ids
                and (
                    edge.attrib.get("from", "") in stale_split_frontier_junction_ids
                    or edge.attrib.get("to", "") in stale_split_frontier_junction_ids
                )
            )
        ]
        if not removable_edge_ids:
            break
        for edge_id in removable_edge_ids:
            edge = candidate_edges_by_id.get(edge_id)
            if edge is None:
                continue
            for connection in list(candidate_root.findall("connection")):
                if edge_id in (connection.attrib.get("from", ""), connection.attrib.get("to", "")):
                    removed_teacher_absent_same_family_continuation_connections.append(dict(connection.attrib))
                    candidate_root.remove(connection)
            _remove_edge_lanes_from_destination_junction(candidate_root, edge, all_junctions=True)
            candidate_root.remove(edge)
            candidate_edge_ids.discard(edge_id)
            candidate_edges_by_id.pop(edge_id, None)
            removed_teacher_absent_same_family_continuation_edges.append(edge_id)
            for endpoint in (edge.attrib.get("from", ""), edge.attrib.get("to", "")):
                if endpoint:
                    stale_split_frontier_junction_ids.add(endpoint)
                    stale_split_spatial_junction_ids.add(endpoint)
    replayed_stale_split_context_edges = []
    replayed_stale_split_context_edge_ids = {
        *replayed_stale_split_continuation_edges,
        *replayed_stale_split_followup_edges,
    }
    context_frontier_junction_ids = set(teacher_dead_end_junction_ids)
    while context_frontier_junction_ids:
        replayed_context_this_pass = False
        for teacher_edge_id, teacher_edge in sorted(teacher_edges.items()):
            candidate_edge_id = replay_edge_map.get(teacher_edge_id, teacher_edge_id)
            context_candidate_edge = candidate_edges_by_id.get(candidate_edge_id)
            if (
                candidate_edge_id in replayed_stale_split_context_edge_ids
                or context_candidate_edge is None
                or teacher_edge_id.startswith(":")
                or teacher_edge.attrib.get("function") in {"internal", "crossing", "walkingarea"}
                or not (
                    teacher_edge.attrib.get("from", "") in context_frontier_junction_ids
                    or teacher_edge.attrib.get("to", "") in context_frontier_junction_ids
                )
                or not (
                    {
                        context_candidate_edge.attrib.get("from", ""),
                        context_candidate_edge.attrib.get("to", ""),
                    }
                    & context_frontier_junction_ids
                )
            ):
                continue
            replay_edge_map[teacher_edge_id] = candidate_edge_id
            if replay_stale_split_edge_geometry(candidate_edge_id, teacher_edge_id):
                replayed_stale_split_context_edge_ids.add(candidate_edge_id)
                replayed_stale_split_context_edges.append(candidate_edge_id)
                copied_edge = candidate_edges_by_id.get(candidate_edge_id)
                if copied_edge is not None:
                    for endpoint in (copied_edge.attrib.get("from", ""), copied_edge.attrib.get("to", "")):
                        if endpoint:
                            context_frontier_junction_ids.add(endpoint)
                            stale_split_frontier_junction_ids.add(endpoint)
                            stale_split_spatial_junction_ids.add(endpoint)
                replayed_context_this_pass = True
        if not replayed_context_this_pass:
            break
    for local_candidate_junction in list(candidate_root.findall("junction")):
        candidate_junction_id = local_candidate_junction.attrib.get("id", "")
        if (
            not candidate_junction_id
            or candidate_junction_id == junction_id
            or candidate_junction_id in teacher_junctions
            or candidate_junction_id not in stale_split_frontier_junction_ids
            or any(
                edge.attrib.get("from") == candidate_junction_id or edge.attrib.get("to") == candidate_junction_id
                for edge in candidate_edges_by_id.values()
            )
        ):
            continue
        orphan_internal_prefix = f":{candidate_junction_id}_"
        for connection in list(candidate_root.findall("connection")):
            if connection.attrib.get("via", "").startswith(orphan_internal_prefix) or any(
                value.startswith(orphan_internal_prefix)
                for value in (connection.attrib.get("from", ""), connection.attrib.get("to", ""))
            ):
                candidate_root.remove(connection)
        for edge_id, edge in list(candidate_edges_by_id.items()):
            if edge_id.startswith(orphan_internal_prefix):
                candidate_root.remove(edge)
                candidate_edge_ids.discard(edge_id)
                candidate_edges_by_id.pop(edge_id, None)
        candidate_root.remove(local_candidate_junction)
        candidate_junction_ids.discard(candidate_junction_id)
        removed_teacher_absent_same_family_continuation_junctions.append(candidate_junction_id)
        if candidate_junction_id in cluster_member_residual_junction_ids:
            removed_cluster_member_residual_junctions.append(candidate_junction_id)
    retuned_stale_split_junction_ids = []
    for remote_junction_id in sorted(stale_split_spatial_junction_ids):
        remote_teacher_junction = teacher_junctions.get(remote_junction_id)
        remote_candidate_junction = candidate_root.find(f"junction[@id='{remote_junction_id}']")
        if remote_teacher_junction is None or remote_candidate_junction is None:
            continue
        mapped_spatial_attrs = _mapped_spatial_attrs(
            remote_teacher_junction.attrib,
            dx,
            dy,
            replay_edge_map,
            remote_junction_id,
            remote_junction_id,
        )
        changed = False
        for attr in (
            "type",
            "x",
            "y",
            "z",
            "shape",
            "outlineShape",
            "customShape",
            "radius",
            "keepClear",
            "rightOfWay",
            "fringe",
            "roundabout",
            "name",
            "tlType",
            "tlLayout",
        ):
            if attr not in mapped_spatial_attrs:
                continue
            if remote_candidate_junction.attrib.get(attr) != mapped_spatial_attrs[attr]:
                remote_candidate_junction.set(attr, mapped_spatial_attrs[attr])
                changed = True
        if changed:
            retuned_stale_split_junction_ids.append(remote_junction_id)
    stripped_stale_split_tls_connections = []
    for connection in candidate_root.findall("connection"):
        tl_id = connection.attrib.get("tl", "")
        if tl_id not in stale_split_stale_junction_ids or tl_id in teacher_tllogic_ids:
            continue
        connection.attrib.pop("tl", None)
        connection.attrib.pop("linkIndex", None)
        if connection.attrib.get("state") == "O":
            connection.set("state", "M")
        elif connection.attrib.get("state") == "o":
            connection.set("state", "m")
        stripped_stale_split_tls_connections.append(dict(connection.attrib))
    removed_stale_split_tllogic_ids = []
    for tllogic in list(candidate_root.findall("tlLogic")):
        tllogic_id = tllogic.attrib.get("id", "")
        if tllogic_id in stale_split_stale_junction_ids and tllogic_id not in teacher_tllogic_ids:
            candidate_root.remove(tllogic)
            removed_stale_split_tllogic_ids.append(tllogic_id)

    copied_boundary_continuation_edges = []
    copied_boundary_continuation_connections = []
    if copied_boundary_edges:
        copied_boundary_edge_ids = set(copied_boundary_edges)
        continuation_edge_ids = []
        for connection in teacher_root.findall("connection"):
            from_edge_id = connection.attrib.get("from", "")
            to_edge_id = connection.attrib.get("to", "")
            for boundary_edge_id, continuation_edge_id in (
                (from_edge_id, to_edge_id),
                (to_edge_id, from_edge_id),
            ):
                if boundary_edge_id not in copied_boundary_edge_ids:
                    continue
                continuation_edge = teacher_edges.get(continuation_edge_id)
                boundary_edge = teacher_edges.get(boundary_edge_id)
                if (
                    continuation_edge is None
                    or boundary_edge is None
                    or continuation_edge_id in stale_split_replacements
                    or continuation_edge_id in candidate_edges_by_id
                    or continuation_edge_id in teacher_boundary_edge_id_set
                    or continuation_edge_id.startswith(":")
                    or not _edge_is_vehicle_continuation_candidate(continuation_edge)
                ):
                    continue
                shared_endpoints = {
                    boundary_edge.attrib.get("from", ""),
                    boundary_edge.attrib.get("to", ""),
                } & {
                    continuation_edge.attrib.get("from", ""),
                    continuation_edge.attrib.get("to", ""),
                }
                if not shared_endpoints or teacher_junction_id in shared_endpoints:
                    continue
                continuation_edge_ids.append(continuation_edge_id)
        continuation_edge_ids = list(dict.fromkeys(continuation_edge_ids))
        continuation_insert_at = _first_junction_index(candidate_root)
        for edge_id in continuation_edge_ids:
            teacher_edge = teacher_edges[edge_id]
            for endpoint in (teacher_edge.attrib.get("from", ""), teacher_edge.attrib.get("to", "")):
                if not endpoint or endpoint in candidate_junction_ids:
                    continue
                teacher_endpoint_junction = teacher_junctions.get(endpoint)
                if teacher_endpoint_junction is None:
                    continue
                candidate_root.insert(
                    list(candidate_root).index(target_candidate_junction),
                    _clone_transformed_boundary_junction(
                        teacher_endpoint_junction,
                        dx,
                        dy,
                        replay_edge_map,
                        teacher_junction_id,
                        junction_id,
                    ),
                )
                candidate_junction_ids.add(endpoint)
                copied_boundary_junctions.append(endpoint)
            if any(
                endpoint not in candidate_junction_ids
                for endpoint in (teacher_edge.attrib.get("from", ""), teacher_edge.attrib.get("to", ""))
            ):
                continue
            copied_edge = _clone_transformed_boundary_edge(
                teacher_edge,
                edge_id,
                dx,
                dy,
                replay_edge_map,
                teacher_junction_id,
                junction_id,
            )
            candidate_root.insert(continuation_insert_at, copied_edge)
            continuation_insert_at += 1
            candidate_edge_ids.add(edge_id)
            candidate_edges_by_id[edge_id] = copied_edge
            replay_edge_map[edge_id] = edge_id
            _append_edge_lanes_to_destination_junction(candidate_root, copied_edge)
            copied_boundary_continuation_edges.append(edge_id)
        continuation_edge_id_set = set(copied_boundary_continuation_edges)
        existing_connection_keys = {
            (
                connection.attrib.get("from", ""),
                connection.attrib.get("to", ""),
                connection.attrib.get("fromLane", "0"),
                connection.attrib.get("toLane", "0"),
            )
            for connection in candidate_root.findall("connection")
        }
        for connection in teacher_root.findall("connection"):
            from_edge_id = connection.attrib.get("from", "")
            to_edge_id = connection.attrib.get("to", "")
            if not (
                {from_edge_id, to_edge_id} & copied_boundary_edge_ids
                and {from_edge_id, to_edge_id} & continuation_edge_id_set
            ):
                continue
            mapped = dict(connection.attrib)
            mapped["from"] = replay_edge_map.get(from_edge_id, from_edge_id)
            mapped["to"] = replay_edge_map.get(to_edge_id, to_edge_id)
            if mapped["from"] not in candidate_edge_ids or mapped["to"] not in candidate_edge_ids:
                continue
            mapped.pop("via", None)
            for attr in ("tl", "linkIndex", "linkIndex2"):
                mapped.pop(attr, None)
            if mapped.get("shape"):
                mapped["shape"] = _translate_shape(mapped["shape"], dx, dy)
            key = (
                mapped.get("from", ""),
                mapped.get("to", ""),
                mapped.get("fromLane", "0"),
                mapped.get("toLane", "0"),
            )
            if key in existing_connection_keys:
                continue
            candidate_root.append(ET.Element("connection", mapped))
            existing_connection_keys.add(key)
            copied_boundary_continuation_connections.append(mapped)

    removed_stale_boundary_edges = []
    if teacher_boundary_edge_ids:
        expected_boundary_edge_ids = {
            replay_edge_map.get(edge_id, edge_id)
            for edge_id in teacher_boundary_edge_ids
            if replay_edge_map.get(edge_id, edge_id)
        }
        for edge in list(candidate_root.findall("edge")):
            edge_id = edge.attrib.get("id", "")
            if (
                not edge_id
                or edge_id in expected_boundary_edge_ids
                or edge_id.startswith(":")
                or edge.attrib.get("function") in {"internal", "crossing", "walkingarea"}
                or junction_id not in (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
            ):
                continue
            _remove_edge_lanes_from_destination_junction(candidate_root, edge, all_junctions=True)
            candidate_root.remove(edge)
            candidate_edge_ids.discard(edge_id)
            candidate_edges_by_id.pop(edge_id, None)
            removed_stale_boundary_edges.append(edge_id)
    removed_stale_boundary_edge_connections = []
    if removed_stale_boundary_edges:
        removed_stale_boundary_edge_id_set = set(removed_stale_boundary_edges)
        for connection in list(candidate_root.findall("connection")):
            if {connection.attrib.get("from", ""), connection.attrib.get("to", "")} & removed_stale_boundary_edge_id_set:
                removed_stale_boundary_edge_connections.append(dict(connection.attrib))
                candidate_root.remove(connection)

    for offset, edge in enumerate(teacher_internal_edges):
        candidate_root.insert(
            insert_index + boundary_insert_offset + offset,
            _clone_transformed_net_element(edge, dx, dy, replay_edge_map, teacher_junction_id, junction_id),
        )

    removed_internal_junctions = []
    junction_insert_index = None
    for child in list(candidate_root):
        if child.tag == "junction" and child.attrib.get("id", "").startswith(internal_prefix):
            if junction_insert_index is None:
                junction_insert_index = list(candidate_root).index(child)
            removed_internal_junctions.append(child.attrib.get("id", ""))
            candidate_root.remove(child)
    if junction_insert_index is None:
        junction_insert_index = list(candidate_root).index(target_candidate_junction) + 1

    teacher_internal_junctions = [
        junction
        for junction in teacher_root.findall("junction")
        if junction.attrib.get("id", "").startswith(teacher_internal_prefix)
    ]
    for offset, junction in enumerate(teacher_internal_junctions):
        candidate_root.insert(
            junction_insert_index + offset,
            _clone_transformed_junction(junction, dx, dy, replay_edge_map, teacher_internal_prefix, internal_prefix),
        )

    mapped_target_attrs = _mapped_junction_attrs(
        teacher_junction,
        dx,
        dy,
        replay_edge_map,
        teacher_internal_prefix,
        internal_prefix,
    )
    if preserve_target_junction_shape and original_target_junction_shape:
        mapped_target_attrs["shape"] = original_target_junction_shape
        if original_target_custom_shape is not None:
            mapped_target_attrs["customShape"] = original_target_custom_shape
        else:
            mapped_target_attrs.pop("customShape", None)
    target_candidate_junction.attrib.clear()
    target_candidate_junction.attrib.update(mapped_target_attrs)
    for child in list(target_candidate_junction):
        target_candidate_junction.remove(child)
    for request in teacher_junction.findall("request"):
        target_candidate_junction.append(ET.Element("request", dict(request.attrib)))

    edge_endpoints = {
        edge.attrib.get("id", ""): (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
        for edge in candidate_root.findall("edge")
        if edge.attrib.get("id")
    }
    edge_lane_counts = _net_lane_counts(candidate_root)
    removed_stale_replaced_edge_connections = []
    for connection in list(candidate_root.findall("connection")):
        from_edge_id = connection.attrib.get("from", "")
        to_edge_id = connection.attrib.get("to", "")
        connection_edge_ids = {from_edge_id, to_edge_id}
        source_endpoint = edge_endpoints.get(from_edge_id)
        target_endpoint = edge_endpoints.get(to_edge_id)
        shared_endpoint = (
            source_endpoint[1]
            if source_endpoint and target_endpoint and source_endpoint[1] and source_endpoint[1] == target_endpoint[0]
            else ""
        )
        via_edge_id = connection.attrib.get("via", "")
        stale_via = bool(via_edge_id and shared_endpoint and not via_edge_id.startswith(f":{shared_endpoint}_"))
        if (
            not _touches_target_replay_scope(connection, internal_prefix, junction_id, candidate_edges_by_id)
            and connection_edge_ids & replaced_boundary_edge_ids
            and (
                not shared_endpoint
                or stale_via
                or not _connection_lane_indices_valid(connection, edge_lane_counts)
            )
        ):
            removed_stale_replaced_edge_connections.append(dict(connection.attrib))
            candidate_root.remove(connection)

    removed_connections = 0
    for connection in list(candidate_root.findall("connection")):
        if _touches_target_replay_scope(connection, internal_prefix, junction_id, candidate_edges_by_id):
            candidate_root.remove(connection)
            removed_connections += 1

    copied_connections = 0
    skipped_connections = []
    ignored_off_scope_tls_connections = []
    for connection in teacher_root.findall("connection"):
        if not _touches_target_replay_scope(connection, teacher_internal_prefix, teacher_junction_id, teacher_edges):
            if connection.attrib.get("tl") == teacher_junction_id:
                ignored_off_scope_tls_connections.append(dict(connection.attrib))
            continue
        mapped = _mapped_connection_attrs(
            connection,
            replay_edge_map,
            teacher_internal_prefix,
            teacher_junction_id,
            internal_prefix,
            junction_id,
            candidate_edge_ids,
            dx,
            dy,
        )
        if mapped is None:
            skipped_connections.append(dict(connection.attrib))
            continue
        candidate_root.append(ET.Element("connection", mapped))
        copied_connections += 1

    teacher_tls_ids = [
        connection.attrib.get("tl", "")
        for connection in teacher_root.findall("connection")
        if _touches_target_replay_scope(connection, teacher_internal_prefix, teacher_junction_id, teacher_edges)
        and connection.attrib.get("tl")
        and connection.attrib.get("linkIndex")
    ]
    teacher_tllogic = teacher_root.find(f"tlLogic[@id='{teacher_junction_id}']")
    if teacher_tllogic is None:
        teacher_tllogic = next(
            (tl for tl in teacher_root.findall("tlLogic") if tl.attrib.get("id") in teacher_tls_ids),
            None,
        )
    removed_stale_tllogic_ids = []
    uncontrolled_stale_tls_connections = []
    removed_stale_tls_connections = []
    if teacher_tllogic is not None:
        target_tllogic = candidate_root.find(f"tlLogic[@id='{junction_id}']")
        root_children = list(candidate_root)
        target_index = (
            root_children.index(target_tllogic)
            if target_tllogic is not None
            else next(
                (index for index, child in enumerate(root_children) if child.tag == "connection"),
                len(root_children),
            )
        )
        if target_tllogic is not None:
            candidate_root.remove(target_tllogic)
        copied_tllogic = _clone_transformed_net_element(teacher_tllogic, dx, dy, replay_edge_map, teacher_junction_id, junction_id)
        copied_tllogic.set("id", junction_id)
        candidate_root.insert(target_index, copied_tllogic)
        teacher_link_capacity = max(
            (len(phase.attrib.get("state", "")) for phase in copied_tllogic.findall("phase")),
            default=0,
        )
        for connection in list(candidate_root.findall("connection")):
            if connection.attrib.get("tl") != junction_id or not teacher_link_capacity:
                continue
            link_indices = _connection_link_indices(connection)
            if (
                link_indices
                and max(link_indices) >= teacher_link_capacity
                and not _touches_target_replay_scope(connection, internal_prefix, junction_id, candidate_edges_by_id)
            ):
                removed_stale_tls_connections.append(dict(connection.attrib))
                candidate_root.remove(connection)
    else:
        target_tllogic = candidate_root.find(f"tlLogic[@id='{junction_id}']")
        if target_tllogic is not None:
            candidate_root.remove(target_tllogic)
            removed_stale_tllogic_ids.append(junction_id)
        for connection in candidate_root.findall("connection"):
            if connection.attrib.get("tl") != junction_id:
                continue
            uncontrolled_stale_tls_connections.append(dict(connection.attrib))
            for attr in ("tl", "linkIndex", "linkIndex2"):
                connection.attrib.pop(attr, None)
            connection.set("uncontrolled", "true")

    removed_invalid_lane_connections = []
    edge_lane_counts = _net_lane_counts(candidate_root)
    for connection in list(candidate_root.findall("connection")):
        if not _connection_lane_indices_valid(connection, edge_lane_counts):
            removed_invalid_lane_connections.append(dict(connection.attrib))
            candidate_root.remove(connection)

    added_missing_teacher_endpoint_junctions = []
    for edge in candidate_root.findall("edge"):
        for endpoint in (edge.attrib.get("from", ""), edge.attrib.get("to", "")):
            if not endpoint or endpoint in candidate_junction_ids:
                continue
            teacher_endpoint_junction = teacher_junctions.get(endpoint)
            if teacher_endpoint_junction is None or teacher_endpoint_junction.attrib.get("type") == "internal":
                continue
            candidate_root.insert(
                _first_junction_index(candidate_root),
                _clone_transformed_boundary_junction(
                    teacher_endpoint_junction,
                    dx,
                    dy,
                    replay_edge_map,
                    teacher_junction_id,
                    junction_id,
                ),
            )
            candidate_junction_ids.add(endpoint)
            added_missing_teacher_endpoint_junctions.append(endpoint)

    restored_geometry_anchor_junctions = _restore_geometry_anchor_junctions(candidate_root, geometry_anchor_junctions_by_id)
    external_boundary_connection_report: dict[str, object] = {
        "status": "skipped",
        "restored_connection_count": 0,
        "restored_connections": [],
        "preserved_existing_connection_count": 0,
        "preserved_existing_connections": [],
        "skipped_connection_count": 0,
        "skipped_connections": [],
    }
    if preserve_mapped_boundary_endpoints:
        external_boundary_connection_report = _restore_external_boundary_connections(
            source_root=source_candidate_root,
            target_root=candidate_root,
            boundary_edge_ids=set(replaced_boundary_edge_ids),
            source_local_junction_ids={junction_id},
        )

    unblended_geometry_anchor_edge_ids = geometry_anchor_edge_ids - set(
        blended_geometry_anchor_edge_ids
    )
    if geometry_anchor_edge_ids and not unblended_geometry_anchor_edge_ids:
        target_shape_anchor_report = {
            "status": "skipped",
            "reason": "all_geometry_anchor_edges_blended_at_target",
            "blended_approach_edge_ids": sorted(set(blended_geometry_anchor_edge_ids)),
        }
    else:
        target_shape_anchor_report = _expand_junction_shape_to_approach_endpoints(
            candidate_root,
            junction_id,
            unblended_geometry_anchor_edge_ids,
        )

    ET.indent(candidate_root, space="    ")
    candidate_tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "net_file": str(output_file),
        "dx": round(dx, 6),
        "dy": round(dy, 6),
        "removed_internal_edge_count": len(removed_internal_edges),
        "copied_internal_edge_count": len(teacher_internal_edges),
        "copied_boundary_edge_count": len(copied_boundary_edges),
        "copied_boundary_edges": copied_boundary_edges,
        "copied_boundary_candidate_edges": copied_boundary_candidate_edges,
        "copy_unmapped_boundary_edges": copy_unmapped_boundary_edges,
        "preserve_mapped_boundary_endpoints": preserve_mapped_boundary_endpoints,
        "preserve_target_junction_shape": preserve_target_junction_shape,
        "skipped_unmapped_teacher_boundary_edge_count": len(
            skipped_unmapped_teacher_boundary_edges
        ),
        "skipped_unmapped_teacher_boundary_edges": skipped_unmapped_teacher_boundary_edges,
        "preserved_mapped_boundary_endpoint_count": len(
            preserved_mapped_boundary_endpoints
        ),
        "preserved_mapped_boundary_endpoints": preserved_mapped_boundary_endpoints,
        "restored_external_boundary_connection_count": external_boundary_connection_report[
            "restored_connection_count"
        ],
        "restored_external_boundary_connections": external_boundary_connection_report[
            "restored_connections"
        ],
        "preserved_existing_external_boundary_connection_count": (
            external_boundary_connection_report["preserved_existing_connection_count"]
        ),
        "preserved_existing_external_boundary_connections": (
            external_boundary_connection_report["preserved_existing_connections"]
        ),
        "skipped_external_boundary_connection_count": external_boundary_connection_report[
            "skipped_connection_count"
        ],
        "skipped_external_boundary_connections": external_boundary_connection_report[
            "skipped_connections"
        ],
        "copied_boundary_continuation_edge_count": len(copied_boundary_continuation_edges),
        "copied_boundary_continuation_edges": copied_boundary_continuation_edges,
        "copied_boundary_continuation_connection_count": len(copied_boundary_continuation_connections),
        "copied_boundary_continuation_connections": copied_boundary_continuation_connections,
        "removed_stale_split_fragment_edge_count": len(removed_stale_split_fragment_edges),
        "removed_stale_split_fragment_edges": removed_stale_split_fragment_edges,
        "rewired_stale_split_fragment_connection_count": len(rewired_stale_split_fragment_connections),
        "rewired_stale_split_fragment_connections": rewired_stale_split_fragment_connections,
        "replayed_stale_split_continuation_edge_count": len(replayed_stale_split_continuation_edges),
        "replayed_stale_split_continuation_edges": replayed_stale_split_continuation_edges,
        "replayed_stale_split_followup_edge_count": len(replayed_stale_split_followup_edges),
        "replayed_stale_split_followup_edges": replayed_stale_split_followup_edges,
        "removed_stale_split_dead_end_edge_count": len(removed_stale_split_dead_end_edges),
        "removed_stale_split_dead_end_edges": removed_stale_split_dead_end_edges,
        "removed_stale_split_dead_end_connection_count": len(removed_stale_split_dead_end_connections),
        "removed_stale_split_dead_end_connections": removed_stale_split_dead_end_connections,
        "removed_teacher_absent_same_family_continuation_edge_count": len(
            removed_teacher_absent_same_family_continuation_edges
        ),
        "removed_teacher_absent_same_family_continuation_edges": removed_teacher_absent_same_family_continuation_edges,
        "removed_teacher_absent_same_family_continuation_connection_count": len(
            removed_teacher_absent_same_family_continuation_connections
        ),
        "removed_teacher_absent_same_family_continuation_connections": (
            removed_teacher_absent_same_family_continuation_connections
        ),
        "removed_teacher_absent_same_family_continuation_junctions": (
            removed_teacher_absent_same_family_continuation_junctions
        ),
        "removed_cluster_member_residual_edge_count": len(removed_cluster_member_residual_edges),
        "removed_cluster_member_residual_edges": removed_cluster_member_residual_edges,
        "removed_cluster_member_residual_connection_count": len(removed_cluster_member_residual_connections),
        "removed_cluster_member_residual_connections": removed_cluster_member_residual_connections,
        "removed_cluster_member_residual_junctions": removed_cluster_member_residual_junctions,
        "replayed_stale_split_context_edge_count": len(replayed_stale_split_context_edges),
        "replayed_stale_split_context_edges": replayed_stale_split_context_edges,
        "retuned_stale_split_junction_ids": retuned_stale_split_junction_ids,
        "stripped_stale_split_tls_connection_count": len(stripped_stale_split_tls_connections),
        "stripped_stale_split_tls_connections": stripped_stale_split_tls_connections,
        "removed_stale_split_tllogic_ids": removed_stale_split_tllogic_ids,
        "preserved_colliding_boundary_edge_count": len(preserved_colliding_boundary_edges),
        "preserved_colliding_boundary_edges": preserved_colliding_boundary_edges,
        "same_family_continuation_edge_map_count": len(same_family_continuation_edge_map),
        "same_family_continuation_edge_map": dict(sorted(same_family_continuation_edge_map.items())),
        "removed_stale_boundary_edge_count": len(removed_stale_boundary_edges),
        "removed_stale_boundary_edges": removed_stale_boundary_edges,
        "removed_stale_boundary_edge_connection_count": len(removed_stale_boundary_edge_connections),
        "removed_stale_boundary_edge_connections": removed_stale_boundary_edge_connections,
        "removed_stale_replaced_edge_connection_count": len(removed_stale_replaced_edge_connections),
        "removed_stale_replaced_edge_connections": removed_stale_replaced_edge_connections,
        "removed_invalid_lane_connection_count": len(removed_invalid_lane_connections),
        "removed_invalid_lane_connections": removed_invalid_lane_connections,
        "added_missing_teacher_endpoint_junction_count": len(added_missing_teacher_endpoint_junctions),
        "added_missing_teacher_endpoint_junction_ids": added_missing_teacher_endpoint_junctions,
        "geometry_anchor_edge_count": len(geometry_anchor_edge_ids),
        "blend_geometry_anchor_at_target": blend_geometry_anchor_at_target,
        "blended_geometry_anchor_edge_count": len(
            blended_geometry_anchor_edge_ids
        ),
        "blended_geometry_anchor_edge_ids": sorted(
            set(blended_geometry_anchor_edge_ids)
        ),
        "restored_geometry_anchor_junction_count": len(restored_geometry_anchor_junctions),
        "restored_geometry_anchor_junctions": restored_geometry_anchor_junctions,
        "target_shape_anchor": target_shape_anchor_report,
        "copied_boundary_junction_count": len(copied_boundary_junctions),
        "copied_boundary_junctions": copied_boundary_junctions,
        "skipped_boundary_edge_count": len(skipped_boundary_edges),
        "skipped_boundary_edges": skipped_boundary_edges,
        "removed_internal_junction_count": len(removed_internal_junctions),
        "copied_internal_junction_count": len(teacher_internal_junctions),
        "removed_connection_count": removed_connections,
        "copied_connection_count": copied_connections,
        "skipped_connection_count": len(skipped_connections),
        "skipped_connections": skipped_connections,
        "ignored_off_scope_tls_connection_count": len(ignored_off_scope_tls_connections),
        "ignored_off_scope_tls_connections": ignored_off_scope_tls_connections,
        "removed_stale_tllogic_count": len(removed_stale_tllogic_ids),
        "removed_stale_tllogic_ids": removed_stale_tllogic_ids,
        "uncontrolled_stale_tls_connection_count": len(uncontrolled_stale_tls_connections),
        "uncontrolled_stale_tls_connections": uncontrolled_stale_tls_connections,
        "removed_stale_tls_connection_count": len(removed_stale_tls_connections),
        "removed_stale_tls_connections": removed_stale_tls_connections,
        "copied_request_count": len(teacher_junction.findall("request")),
        "effective_edge_map": dict(sorted(replay_edge_map.items())),
    }


def write_scoped_teacher_tls_cell_replay_net(
    *,
    candidate_net_file: Path,
    teacher_net_file: Path,
    output_file: Path,
    junction_id: str,
    edge_map: dict[str, str],
    teacher_junction_id: str | None = None,
    collapse_junction_ids: set[str] | None = None,
    junction_map: dict[str, str] | None = None,
) -> dict[str, object]:
    """Replay one reference TLS cell while collapsing a split OSM junction group.

    ``write_teacher_target_internal_replay_net`` is intentionally permissive: it
    can copy teacher continuation edges so that a small synthetic example stays
    connected.  That is useful for diagnostics, but it is unsafe for a real
    split TLS cell because those copied continuations leave the old split graph
    beside the new teacher cell.  This wrapper adds an explicit cell boundary:
    boundary edges are mapped/reused, non-boundary edges touching the supplied
    candidate members are removed, and teacher endpoint junctions may be mapped
    back to existing candidate endpoints.  No inference is made when a mapping
    is absent; the teacher boundary is copied and remains visible in the
    returned report for review.
    """

    teacher_junction_id = teacher_junction_id or junction_id
    collapse_ids = {str(value) for value in (collapse_junction_ids or set()) if str(value)}
    collapse_ids.add(junction_id)
    ordinary_junction_map = {
        str(key): str(value)
        for key, value in (junction_map or {}).items()
        if str(key) and str(value)
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if not candidate_net_file.exists():
        return _failure(f"candidate net file does not exist: {candidate_net_file}")
    if not teacher_net_file.exists():
        return _failure(f"teacher net file does not exist: {teacher_net_file}")

    # Keep the permissive writer as the well-tested semantic replay primitive;
    # the scoped cleanup below is the only layer that changes its boundary.
    # Keep the intermediate name deliberately short; the caller already
    # allocates one directory per candidate and Windows path limits apply
    # before the final artifact manifest is written.
    unscoped_file = output_file.parent / "unscoped.net.xml"
    unscoped_file.parent.mkdir(parents=True, exist_ok=True)
    replay_report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net_file,
        teacher_net_file=teacher_net_file,
        output_file=unscoped_file,
        junction_id=junction_id,
        teacher_junction_id=teacher_junction_id,
        edge_map=edge_map,
    )
    if replay_report.get("status") != "pass":
        return {
            **replay_report,
            "scoped_replay_status": "blocked",
            "scoped_replay_reason": "unscoped_teacher_replay_failed",
        }

    try:
        source_root = ET.parse(candidate_net_file).getroot()
        teacher_root = ET.parse(teacher_net_file).getroot()
        candidate_tree = ET.parse(unscoped_file)
        candidate_root = candidate_tree.getroot()
    except (ET.ParseError, OSError, KeyError, ValueError) as exc:
        return _failure(f"scoped TLS cell replay parse failed: {type(exc).__name__}: {exc}")

    target_candidate_junction = candidate_root.find(f"junction[@id='{junction_id}']")
    teacher_junction = teacher_root.find(f"junction[@id='{teacher_junction_id}']")
    if target_candidate_junction is None:
        return _failure(f"candidate junction not found: {junction_id}")
    if teacher_junction is None:
        return _failure(f"teacher junction not found: {teacher_junction_id}")

    teacher_edges = {
        edge.attrib["id"]: edge
        for edge in teacher_root.findall("edge")
        if edge.attrib.get("id")
    }
    source_edges = {
        edge.attrib["id"]: edge
        for edge in source_root.findall("edge")
        if edge.attrib.get("id")
    }
    source_junction_ids = {
        junction.attrib["id"]
        for junction in source_root.findall("junction")
        if junction.attrib.get("id")
    }
    teacher_boundary_edge_ids = _teacher_boundary_edge_ids_touching_internal_subgraph(
        teacher_root.findall("connection"),
        teacher_edges,
        teacher_junction_id,
    )
    effective_edge_map = {str(key): str(value) for key, value in edge_map.items()}
    for teacher_edge_id in teacher_boundary_edge_ids:
        effective_edge_map.setdefault(teacher_edge_id, teacher_edge_id)
    protected_edge_ids = {
        effective_edge_map.get(edge_id, edge_id)
        for edge_id in teacher_boundary_edge_ids
        if effective_edge_map.get(edge_id, edge_id)
    }
    old_member_ids = collapse_ids - {junction_id}
    old_member_prefixes = tuple(f":{member_id}_" for member_id in sorted(old_member_ids))

    target_x = float(target_candidate_junction.attrib.get("x", "0") or 0)
    target_y = float(target_candidate_junction.attrib.get("y", "0") or 0)
    teacher_x = float(teacher_junction.attrib.get("x", "0") or 0)
    teacher_y = float(teacher_junction.attrib.get("y", "0") or 0)
    dx = target_x - teacher_x
    dy = target_y - teacher_y

    def map_junction_id(value: str) -> str:
        if value == teacher_junction_id:
            return junction_id
        return ordinary_junction_map.get(value, value)

    def map_boundary_junction(teacher_endpoint_id: str) -> str:
        mapped_id = map_junction_id(teacher_endpoint_id)
        if mapped_id in source_junction_ids:
            return mapped_id
        if candidate_root.find(f"junction[@id='{mapped_id}']") is not None:
            return mapped_id
        teacher_endpoint = teacher_root.find(f"junction[@id='{teacher_endpoint_id}']")
        if teacher_endpoint is None:
            return mapped_id
        attrs = _mapped_spatial_attrs(
            teacher_endpoint.attrib,
            dx,
            dy,
            effective_edge_map,
            teacher_junction_id,
            junction_id,
        )
        for attr in ("id", "from", "to", "tl"):
            if attr in attrs:
                attrs[attr] = map_junction_id(attrs[attr])
        attrs["id"] = mapped_id
        attrs["incLanes"] = ""
        attrs["intLanes"] = ""
        candidate_root.insert(_first_junction_index(candidate_root), ET.Element("junction", attrs))
        return mapped_id

    def edge_lane_ids(edge: ET.Element) -> set[str]:
        return {
            lane.attrib["id"]
            for lane in edge.findall("lane")
            if lane.attrib.get("id")
        }

    def remove_lane_refs(lane_ids: set[str]) -> None:
        if not lane_ids:
            return
        for junction in candidate_root.findall("junction"):
            inc_lanes = _split(junction.attrib.get("incLanes", ""))
            if inc_lanes:
                junction.set("incLanes", " ".join(lane for lane in inc_lanes if lane not in lane_ids))

    def append_lane_refs(junction_id_value: str, lane_ids: set[str]) -> None:
        junction = candidate_root.find(f"junction[@id='{junction_id_value}']")
        if junction is None or not lane_ids:
            return
        inc_lanes = _split(junction.attrib.get("incLanes", ""))
        for lane_id in sorted(lane_ids):
            if lane_id not in inc_lanes:
                inc_lanes.append(lane_id)
        junction.set("incLanes", " ".join(inc_lanes))

    removed_edge_ids: set[str] = set()
    removed_non_boundary_edge_ids: list[str] = []
    removed_non_boundary_edges_added_by_replay: list[str] = []
    candidate_edges = {
        edge.attrib["id"]: edge
        for edge in candidate_root.findall("edge")
        if edge.attrib.get("id")
    }
    # First remove the old split road graph around the supplied physical cell.
    # Internal/crossing/walkingarea elements are handled separately so the
    # teacher cell can remain intact.
    for edge_id, edge in list(candidate_edges.items()):
        if edge_id in protected_edge_ids or edge_id.startswith(":"):
            continue
        if edge.attrib.get("from") in collapse_ids or edge.attrib.get("to") in collapse_ids:
            remove_lane_refs(edge_lane_ids(edge))
            candidate_root.remove(edge)
            removed_edge_ids.add(edge_id)
            removed_non_boundary_edge_ids.append(edge_id)
    # The permissive writer may have copied a continuation edge that was not in
    # the candidate at all.  Keep only the explicit teacher cell boundary.
    for edge in list(candidate_root.findall("edge")):
        edge_id = edge.attrib.get("id", "")
        if (
            not edge_id
            or edge_id in protected_edge_ids
            or edge_id in source_edges
            or edge_id.startswith(":")
            or edge.attrib.get("function") in {"internal", "crossing", "walkingarea"}
        ):
            continue
        remove_lane_refs(edge_lane_ids(edge))
        candidate_root.remove(edge)
        removed_edge_ids.add(edge_id)
        removed_non_boundary_edges_added_by_replay.append(edge_id)

    # Remove member-owned internal artifacts but retain the newly replayed
    # target prefix.  This is the actual split-junction collapse.
    removed_member_internal_edge_ids: list[str] = []
    removed_member_internal_junction_ids: list[str] = []
    for edge in list(candidate_root.findall("edge")):
        edge_id = edge.attrib.get("id", "")
        if edge_id.startswith(old_member_prefixes):
            remove_lane_refs(edge_lane_ids(edge))
            candidate_root.remove(edge)
            removed_edge_ids.add(edge_id)
            removed_member_internal_edge_ids.append(edge_id)
    for junction in list(candidate_root.findall("junction")):
        junction_id_value = junction.attrib.get("id", "")
        if junction_id_value.startswith(old_member_prefixes):
            candidate_root.remove(junction)
            removed_member_internal_junction_ids.append(junction_id_value)

    # Map/reuse each explicit teacher boundary edge.  A candidate edge with a
    # different lane cardinality is replaced by the teacher edge under the
    # mapped candidate ID; otherwise a 1-lane continuation can silently drop
    # several controlled linkIndexes during netconvert.
    remapped_boundary_edge_count = 0
    replaced_lane_cardinality_edge_ids: list[str] = []
    replayed_boundary_geometry_edge_ids: list[str] = []
    preserved_mapped_boundary_geometry_edge_ids: list[str] = []
    boundary_geometry_preservation_failures: list[dict[str, object]] = []
    candidate_edges = {
        edge.attrib["id"]: edge
        for edge in candidate_root.findall("edge")
        if edge.attrib.get("id")
    }
    for teacher_edge_id in teacher_boundary_edge_ids:
        teacher_edge = teacher_edges.get(teacher_edge_id)
        if teacher_edge is None:
            continue
        candidate_edge_id = effective_edge_map.get(teacher_edge_id, teacher_edge_id)
        candidate_edge = candidate_edges.get(candidate_edge_id)
        if candidate_edge is None:
            candidate_edge = _clone_transformed_boundary_edge(
                teacher_edge,
                candidate_edge_id,
                dx,
                dy,
                effective_edge_map,
                teacher_junction_id,
                junction_id,
            )
            candidate_root.insert(0, candidate_edge)
            candidate_edges[candidate_edge_id] = candidate_edge
        else:
            replacement = _clone_transformed_boundary_edge(
                teacher_edge,
                candidate_edge_id,
                dx,
                dy,
                effective_edge_map,
                teacher_junction_id,
                junction_id,
            )
            lane_cardinality_changed = len(candidate_edge.findall("lane")) != len(teacher_edge.findall("lane"))
            remove_lane_refs(edge_lane_ids(candidate_edge))
            insert_at = list(candidate_root).index(candidate_edge)
            candidate_root.remove(candidate_edge)
            candidate_root.insert(insert_at, replacement)
            candidate_edge = replacement
            candidate_edges[candidate_edge_id] = candidate_edge
            replayed_boundary_geometry_edge_ids.append(candidate_edge_id)
            if lane_cardinality_changed:
                replaced_lane_cardinality_edge_ids.append(candidate_edge_id)
        mapped_from = map_boundary_junction(teacher_edge.attrib.get("from", ""))
        mapped_to = map_boundary_junction(teacher_edge.attrib.get("to", ""))
        remove_lane_refs(edge_lane_ids(candidate_edge))
        candidate_edge.set("from", mapped_from)
        candidate_edge.set("to", mapped_to)
        geometry_source_edge = source_edges.get(candidate_edge_id)
        if geometry_source_edge is not None:
            geometry_report = _preserve_mapped_boundary_geometry(
                candidate_edge,
                geometry_source_edge,
                target_junction_ids={junction_id},
                source_local_junction_ids=collapse_ids,
            )
            if geometry_report.get("status") == "pass":
                preserved_mapped_boundary_geometry_edge_ids.append(candidate_edge_id)
            elif geometry_report.get("status") == "blocked":
                boundary_geometry_preservation_failures.append(
                    {
                        "teacher_edge_id": teacher_edge_id,
                        "candidate_edge_id": candidate_edge_id,
                        **geometry_report,
                    }
                )
        append_lane_refs(mapped_to, edge_lane_ids(candidate_edge))
        remapped_boundary_edge_count += 1

    # Rewrite connection edge aliases before removing stale member references.
    remapped_connection_count = 0
    for connection in list(candidate_root.findall("connection")):
        for attr in ("from", "to"):
            value = connection.attrib.get(attr, "")
            mapped_value = effective_edge_map.get(value, value)
            if mapped_value != value:
                connection.set(attr, mapped_value)
                remapped_connection_count += 1
        values = tuple(connection.attrib.get(attr, "") for attr in ("from", "to", "via"))
        if any(value in removed_edge_ids for value in values) or any(
            value.startswith(old_member_prefixes) for value in values if value
        ):
            candidate_root.remove(connection)
            continue

    # Drop member junctions that are no longer endpoints.  Do not remove an
    # unrelated external junction merely because the teacher supplied a new
    # boundary endpoint for review.
    for junction in list(candidate_root.findall("junction")):
        junction_id_value = junction.attrib.get("id", "")
        if junction_id_value not in old_member_ids:
            continue
        if not any(
            junction_id_value in (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
            for edge in candidate_root.findall("edge")
        ):
            candidate_root.remove(junction)

    external_boundary_connection_report = _restore_external_boundary_connections(
        source_root=source_root,
        target_root=candidate_root,
        boundary_edge_ids={
            effective_edge_map.get(edge_id, edge_id)
            for edge_id in teacher_boundary_edge_ids
            if effective_edge_map.get(edge_id, edge_id) in source_edges
        },
        source_local_junction_ids=collapse_ids,
    )

    # Clean stale lane references left by removed split fragments and reject
    # dangling connections before netconvert sees the variant.
    remaining_edge_ids = {
        edge.attrib["id"]
        for edge in candidate_root.findall("edge")
        if edge.attrib.get("id")
    }
    for junction in candidate_root.findall("junction"):
        inc_lanes = [
            lane
            for lane in _split(junction.attrib.get("incLanes", ""))
            if lane.rsplit("_", 1)[0] in remaining_edge_ids
            and not lane.startswith(old_member_prefixes)
        ]
        junction.set("incLanes", " ".join(inc_lanes))
        int_lanes = [
            lane
            for lane in _split(junction.attrib.get("intLanes", ""))
            if not lane.startswith(old_member_prefixes)
        ]
        junction.set("intLanes", " ".join(int_lanes))
    # Replacing a mapped boundary edge with the teacher lane cardinality can
    # invalidate stale connections that belonged to the former split graph.
    # Remove those connections before netconvert/SUMO sees the scoped variant;
    # silently retaining them would turn a safe replay into a construction
    # failure or, worse, a lane-index reinterpretation.
    edge_lane_counts = _net_lane_counts(candidate_root)
    removed_invalid_lane_connection_count = 0
    removed_invalid_lane_connections: list[dict[str, str]] = []
    for connection in list(candidate_root.findall("connection")):
        if _connection_lane_indices_valid(connection, edge_lane_counts):
            continue
        removed_invalid_lane_connections.append(dict(connection.attrib))
        candidate_root.remove(connection)
        removed_invalid_lane_connection_count += 1
    removed_dangling_connection_count = 0
    seen_connection_keys: set[tuple[str, ...]] = set()
    for connection in list(candidate_root.findall("connection")):
        if connection.attrib.get("from") not in remaining_edge_ids or connection.attrib.get("to") not in remaining_edge_ids:
            candidate_root.remove(connection)
            removed_dangling_connection_count += 1
            continue
        key = tuple(
            connection.attrib.get(attr, "")
            for attr in ("from", "to", "fromLane", "toLane", "via", "tl", "linkIndex", "dir", "state")
        )
        if key in seen_connection_keys:
            candidate_root.remove(connection)
            removed_dangling_connection_count += 1
            continue
        seen_connection_keys.add(key)

    ET.indent(candidate_root, space="    ")
    candidate_tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "blocked" if boundary_geometry_preservation_failures else "pass",
        "claim_status": "diagnostic-demo",
        "scoped_replay_status": "pass",
        "net_file": str(output_file),
        "unscoped_net_file": str(unscoped_file),
        "junction_id": junction_id,
        "teacher_junction_id": teacher_junction_id,
        "collapse_junction_ids": sorted(collapse_ids),
        "old_member_ids": sorted(old_member_ids),
        "teacher_boundary_edge_ids": teacher_boundary_edge_ids,
        "protected_boundary_edge_ids": sorted(protected_edge_ids),
        "effective_edge_map": dict(sorted(effective_edge_map.items())),
        "junction_map": dict(sorted(ordinary_junction_map.items())),
        "remapped_boundary_edge_count": remapped_boundary_edge_count,
        "remapped_connection_endpoint_count": remapped_connection_count,
        "replaced_lane_cardinality_edge_ids": sorted(replaced_lane_cardinality_edge_ids),
        "replayed_boundary_geometry_edge_ids": sorted(set(replayed_boundary_geometry_edge_ids)),
        "preserved_mapped_boundary_geometry_edge_ids": sorted(
            set(preserved_mapped_boundary_geometry_edge_ids)
        ),
        "boundary_geometry_preservation_failure_count": len(boundary_geometry_preservation_failures),
        "boundary_geometry_preservation_failures": boundary_geometry_preservation_failures,
        "restored_external_boundary_connection_count": external_boundary_connection_report[
            "restored_connection_count"
        ],
        "restored_external_boundary_connections": external_boundary_connection_report[
            "restored_connections"
        ],
        "preserved_existing_external_boundary_connection_count": external_boundary_connection_report[
            "preserved_existing_connection_count"
        ],
        "preserved_existing_external_boundary_connections": external_boundary_connection_report[
            "preserved_existing_connections"
        ],
        "skipped_external_boundary_connection_count": external_boundary_connection_report[
            "skipped_connection_count"
        ],
        "skipped_external_boundary_connections": external_boundary_connection_report[
            "skipped_connections"
        ],
        "removed_non_boundary_edge_count": len(removed_non_boundary_edge_ids),
        "removed_non_boundary_edge_ids": sorted(removed_non_boundary_edge_ids),
        "removed_replay_continuation_edge_count": len(removed_non_boundary_edges_added_by_replay),
        "removed_replay_continuation_edge_ids": sorted(removed_non_boundary_edges_added_by_replay),
        "removed_member_internal_edge_count": len(removed_member_internal_edge_ids),
        "removed_member_internal_edge_ids": sorted(removed_member_internal_edge_ids),
        "removed_member_internal_junction_count": len(removed_member_internal_junction_ids),
        "removed_member_internal_junction_ids": sorted(removed_member_internal_junction_ids),
        "removed_invalid_lane_connection_count": removed_invalid_lane_connection_count,
        "removed_invalid_lane_connections": removed_invalid_lane_connections,
        "removed_dangling_or_duplicate_connection_count": removed_dangling_connection_count,
        "base_replay_report": replay_report,
    }


def write_shared_teacher_tls_controller_replay_net(
    *,
    candidate_net_file: Path,
    teacher_net_file: Path,
    output_file: Path,
    candidate_controller_id: str,
    teacher_controller_id: str,
    owner_map: dict[str, str],
    edge_map: dict[str, str],
    junction_map: dict[str, str] | None = None,
    collapse_junction_ids: set[str] | list[str] | None = None,
) -> dict[str, object]:
    """Replay a TLS whose link indexes span more than one internal owner.

    SUMO permits several physical junctions to use one ``tlLogic``.  The
    single-owner writer above deliberately rejects that shape because mapping
    a secondary ``via`` prefix into the primary prefix would silently change
    topology.  This writer requires an explicit reference-owner to
    candidate-owner map and an explicit boundary-edge map, then replays all
    owner-local internal artifacts and connections in one variant.

    The function is intentionally local to a repair variant.  It never edits
    the source network and it reports every teacher boundary that was copied
    under a generated candidate edge id, so a later semantic gate can decide
    whether the copy is acceptable.
    """

    output_file.parent.mkdir(parents=True, exist_ok=True)
    if not candidate_net_file.exists():
        return _failure(f"candidate net file does not exist: {candidate_net_file}")
    if not teacher_net_file.exists():
        return _failure(f"teacher net file does not exist: {teacher_net_file}")
    try:
        candidate_tree = ET.parse(candidate_net_file)
        candidate_root = candidate_tree.getroot()
        candidate_source_root = copy.deepcopy(candidate_root)
        teacher_root = ET.parse(teacher_net_file).getroot()
    except (ET.ParseError, OSError, ValueError) as exc:
        return _failure(f"shared TLS controller replay parse failed: {type(exc).__name__}: {exc}")

    clean_owner_map = {
        str(key): str(value)
        for key, value in (owner_map or {}).items()
        if str(key) and str(value)
    }
    clean_owner_map.setdefault(teacher_controller_id, candidate_controller_id)
    clean_junction_map = {
        str(key): str(value)
        for key, value in (junction_map or {}).items()
        if str(key) and str(value)
    }
    collapse_ids = {
        str(value)
        for value in (collapse_junction_ids or set())
        if str(value)
    }
    collapse_ids.update(clean_owner_map.values())
    candidate_owner_ids = set(clean_owner_map.values())
    teacher_owner_ids = sorted(clean_owner_map, key=len, reverse=True)
    teacher_edges = {
        edge.attrib["id"]: edge
        for edge in teacher_root.findall("edge")
        if edge.attrib.get("id")
    }
    candidate_edges = {
        edge.attrib["id"]: edge
        for edge in candidate_root.findall("edge")
        if edge.attrib.get("id")
    }
    teacher_junctions = {
        junction.attrib["id"]: junction
        for junction in teacher_root.findall("junction")
        if junction.attrib.get("id")
    }
    candidate_junctions = {
        junction.attrib["id"]: junction
        for junction in candidate_root.findall("junction")
        if junction.attrib.get("id")
    }
    if candidate_controller_id not in candidate_junctions:
        return _failure(f"candidate controller junction not found: {candidate_controller_id}")
    if teacher_controller_id not in teacher_junctions:
        return _failure(f"teacher controller junction not found: {teacher_controller_id}")
    missing_owner_ids = [
        owner_id
        for owner_id in teacher_owner_ids
        if owner_id not in teacher_junctions or clean_owner_map[owner_id] not in candidate_junctions
    ]
    if missing_owner_ids:
        return {
            **_failure("shared TLS owner closure is incomplete"),
            "missing_owner_ids": missing_owner_ids,
            "owner_map": dict(sorted(clean_owner_map.items())),
        }

    def teacher_owner_for(value: str) -> str:
        for owner_id in teacher_owner_ids:
            if value.startswith(f":{owner_id}_"):
                return owner_id
        return ""

    def candidate_internal_ref(value: str) -> str:
        owner_id = teacher_owner_for(value)
        if not owner_id:
            return value
        prefix = f":{owner_id}_"
        return f":{clean_owner_map[owner_id]}_{value[len(prefix):]}"

    def teacher_edge_owner(edge: ET.Element) -> str:
        for endpoint in (edge.attrib.get("from", ""), edge.attrib.get("to", "")):
            if endpoint in teacher_owner_ids:
                return endpoint
        return ""

    def point_delta(owner_id: str = "") -> tuple[float, float]:
        anchor_owner = owner_id if owner_id in clean_owner_map else teacher_controller_id
        teacher_anchor = teacher_junctions.get(anchor_owner)
        candidate_anchor = candidate_junctions.get(clean_owner_map.get(anchor_owner, candidate_controller_id))
        if teacher_anchor is None or candidate_anchor is None:
            return (0.0, 0.0)
        try:
            return (
                float(candidate_anchor.attrib.get("x", "0") or 0)
                - float(teacher_anchor.attrib.get("x", "0") or 0),
                float(candidate_anchor.attrib.get("y", "0") or 0)
                - float(teacher_anchor.attrib.get("y", "0") or 0),
            )
        except (TypeError, ValueError):
            return (0.0, 0.0)

    def map_junction_id(value: str) -> str:
        if value in clean_owner_map:
            return clean_owner_map[value]
        if value in clean_junction_map:
            return clean_junction_map[value]
        return value

    def map_edge_ref(value: str, resolved_edge_map: dict[str, str]) -> str:
        if not value:
            return ""
        if value.startswith(":"):
            return candidate_internal_ref(value)
        return resolved_edge_map.get(value, value if value in candidate_edges else "")

    def map_crossing_edges(value: str, resolved_edge_map: dict[str, str]) -> str:
        mapped: list[str] = []
        for edge_id in _split(value):
            if edge_id.startswith(":"):
                mapped_id = candidate_internal_ref(edge_id)
            else:
                mapped_id = resolved_edge_map.get(edge_id, edge_id if edge_id in candidate_edges else "")
            if mapped_id:
                mapped.append(mapped_id)
        return " ".join(mapped)

    def relevant_connection(connection: ET.Element) -> bool:
        if any(teacher_owner_for(connection.attrib.get(attr, "")) for attr in ("from", "to", "via")):
            return True
        if connection.attrib.get("tl") != teacher_controller_id:
            return False
        for attr in ("from", "to"):
            edge = teacher_edges.get(connection.attrib.get(attr, ""))
            if edge is not None and teacher_edge_owner(edge):
                return True
        return False

    relevant_connections = [
        connection for connection in teacher_root.findall("connection") if relevant_connection(connection)
    ]
    controlled_connections = [
        connection
        for connection in relevant_connections
        if connection.attrib.get("tl") == teacher_controller_id and connection.attrib.get("linkIndex") is not None
    ]
    teacher_link_indices = {
        str(connection.attrib.get("linkIndex", "")) for connection in controlled_connections
    }
    if not controlled_connections:
        return _failure("shared TLS controller has no controlled connections")

    boundary_edge_ids: list[str] = []
    seen_boundary_edge_ids: set[str] = set()
    for connection in relevant_connections:
        for attr in ("from", "to"):
            edge_id = connection.attrib.get(attr, "")
            if not edge_id or edge_id.startswith(":") or edge_id not in teacher_edges:
                continue
            if edge_id not in seen_boundary_edge_ids:
                seen_boundary_edge_ids.add(edge_id)
                boundary_edge_ids.append(edge_id)
    for edge in teacher_edges.values():
        edge_id = edge.attrib.get("id", "")
        owner_id = teacher_owner_for(edge_id)
        if not owner_id:
            continue
        for crossing_edge_id in _split(edge.attrib.get("crossingEdges", "")):
            if crossing_edge_id in teacher_edges and crossing_edge_id not in seen_boundary_edge_ids:
                seen_boundary_edge_ids.add(crossing_edge_id)
                boundary_edge_ids.append(crossing_edge_id)

    resolved_edge_map: dict[str, str] = {}
    generated_boundary_edge_ids: list[str] = []
    edge_mapping_sources: dict[str, str] = {}
    reverse_edge_map: dict[str, str] = {}
    for teacher_edge_id in boundary_edge_ids:
        mapped_edge_id = str((edge_map or {}).get(teacher_edge_id, "")).strip()
        if not mapped_edge_id:
            if teacher_edge_id in candidate_edges:
                mapped_edge_id = teacher_edge_id
                edge_mapping_sources[teacher_edge_id] = "candidate_identity"
            else:
                safe_id = "".join(
                    character if character.isalnum() or character in "_.-" else "_"
                    for character in teacher_edge_id
                ).strip("_") or "edge"
                mapped_edge_id = f"torii_shared_{safe_id}"
                edge_mapping_sources[teacher_edge_id] = "explicit_teacher_boundary_copy"
                generated_boundary_edge_ids.append(teacher_edge_id)
        else:
            edge_mapping_sources[teacher_edge_id] = "explicit_edge_map"
        previous_teacher_edge_id = reverse_edge_map.get(mapped_edge_id)
        if previous_teacher_edge_id and previous_teacher_edge_id != teacher_edge_id:
            return {
                **_failure("shared TLS boundary edge map is not one-to-one"),
                "edge_mapping_conflict": {
                    "candidate_edge_id": mapped_edge_id,
                    "teacher_edge_ids": [previous_teacher_edge_id, teacher_edge_id],
                },
            }
        reverse_edge_map[mapped_edge_id] = teacher_edge_id
        resolved_edge_map[teacher_edge_id] = mapped_edge_id

    unanchored_boundary_edge_ids = sorted(
        teacher_edge_id
        for teacher_edge_id, mapped_edge_id in resolved_edge_map.items()
        if mapped_edge_id not in candidate_edges
    )
    if unanchored_boundary_edge_ids:
        return {
            **_failure("shared TLS boundary geometry anchor is missing"),
            "status": "blocked",
            "shared_controller_replay_status": "blocked",
            "candidate_controller_id": candidate_controller_id,
            "teacher_controller_id": teacher_controller_id,
            "owner_map": dict(sorted(clean_owner_map.items())),
            "junction_map": dict(sorted(clean_junction_map.items())),
            "effective_edge_map": dict(sorted(resolved_edge_map.items())),
            "edge_mapping_sources": dict(sorted(edge_mapping_sources.items())),
            "generated_boundary_edge_ids": sorted(generated_boundary_edge_ids),
            "unanchored_boundary_edge_count": len(unanchored_boundary_edge_ids),
            "unanchored_boundary_edge_ids": unanchored_boundary_edge_ids,
            "replay_policy": "mapped shared boundaries require existing candidate geometry anchors",
        }

    # Remove only the local candidate cell.  Existing normal edges that are
    # explicitly mapped are replaced below; all other network edges remain.
    candidate_internal_prefixes = tuple(f":{owner_id}_" for owner_id in sorted(collapse_ids, key=len, reverse=True))
    removed_internal_edge_ids: list[str] = []
    for edge in list(candidate_root.findall("edge")):
        edge_id = edge.attrib.get("id", "")
        if edge_id.startswith(candidate_internal_prefixes):
            _remove_edge_lanes_from_destination_junction(candidate_root, edge, all_junctions=True)
            candidate_root.remove(edge)
            removed_internal_edge_ids.append(edge_id)
    removed_internal_junction_ids: list[str] = []
    for junction in list(candidate_root.findall("junction")):
        junction_id = junction.attrib.get("id", "")
        if junction_id.startswith(candidate_internal_prefixes):
            candidate_root.remove(junction)
            removed_internal_junction_ids.append(junction_id)

    protected_edge_ids = set(resolved_edge_map.values())
    removed_member_edge_ids: list[str] = []
    for edge in list(candidate_root.findall("edge")):
        edge_id = edge.attrib.get("id", "")
        if (
            not edge_id
            or edge_id.startswith(":")
            or edge_id in protected_edge_ids
            or edge.attrib.get("function") in {"internal", "crossing", "walkingarea"}
            or not ({edge.attrib.get("from", ""), edge.attrib.get("to", "")} & collapse_ids)
        ):
            continue
        _remove_edge_lanes_from_destination_junction(candidate_root, edge, all_junctions=True)
        candidate_root.remove(edge)
        removed_member_edge_ids.append(edge_id)

    removed_connection_count = 0
    removed_edge_id_set = set(removed_member_edge_ids)
    for connection in list(candidate_root.findall("connection")):
        values = tuple(connection.attrib.get(attr, "") for attr in ("from", "to", "via"))
        if (
            connection.attrib.get("tl") in candidate_owner_ids | {candidate_controller_id}
            or any(value.startswith(candidate_internal_prefixes) for value in values if value)
            or any(value in removed_edge_id_set for value in values if value)
            or any(value in protected_edge_ids for value in values if value)
        ):
            candidate_root.remove(connection)
            removed_connection_count += 1

    # Existing mapped boundary edges can carry connections outside the local
    # cell.  They must be removed with the old edge before the teacher edge is
    # inserted, otherwise lane indices from the old split survive silently.
    removed_mapped_edge_connection_count = 0
    for connection in list(candidate_root.findall("connection")):
        if any(connection.attrib.get(attr, "") in protected_edge_ids for attr in ("from", "to")):
            candidate_root.remove(connection)
            removed_mapped_edge_connection_count += 1

    candidate_edges = {
        edge.attrib["id"]: edge
        for edge in candidate_root.findall("edge")
        if edge.attrib.get("id")
    }
    candidate_junctions = {
        junction.attrib["id"]: junction
        for junction in candidate_root.findall("junction")
        if junction.attrib.get("id")
    }

    def ensure_boundary_junction(teacher_junction_id: str, owner_hint: str) -> str:
        mapped_id = map_junction_id(teacher_junction_id)
        if mapped_id in candidate_junctions:
            return mapped_id
        source_junction = teacher_junctions.get(teacher_junction_id)
        if source_junction is None:
            return mapped_id
        dx, dy = point_delta(owner_hint)
        attrs = dict(source_junction.attrib)
        if "x" in attrs:
            attrs["x"] = _format_xy(float(attrs["x"]) + dx)
        if "y" in attrs:
            attrs["y"] = _format_xy(float(attrs["y"]) + dy)
        for attr in ("shape", "outlineShape", "customShape"):
            if attr in attrs:
                attrs[attr] = _translate_shape(attrs[attr], dx, dy)
        attrs["id"] = mapped_id
        for attr in ("from", "to", "tl"):
            if attr in attrs:
                attrs[attr] = map_junction_id(attrs[attr])
        if "crossingEdges" in attrs:
            attrs["crossingEdges"] = map_crossing_edges(attrs["crossingEdges"], resolved_edge_map)
        attrs["incLanes"] = ""
        attrs["intLanes"] = ""
        candidate_root.insert(_first_junction_index(candidate_root), ET.Element("junction", attrs))
        candidate_junctions[mapped_id] = candidate_root.find(f"junction[@id='{mapped_id}']")
        return mapped_id

    # Add all normal teacher boundaries first so every mapped connection has a
    # concrete edge endpoint.  A copied boundary is a deliberate artifact, not
    # a nearest-family guess.
    copied_boundary_edge_ids: list[str] = []
    replaced_boundary_edge_ids: list[str] = []
    preserved_mapped_boundary_geometry_edge_ids: list[str] = []
    boundary_geometry_preservation_failures: list[dict[str, object]] = []
    for teacher_edge_id in boundary_edge_ids:
        teacher_edge = teacher_edges[teacher_edge_id]
        mapped_edge_id = resolved_edge_map[teacher_edge_id]
        owner_hint = teacher_edge_owner(teacher_edge)
        mapped_from = ensure_boundary_junction(teacher_edge.attrib.get("from", ""), owner_hint)
        mapped_to = ensure_boundary_junction(teacher_edge.attrib.get("to", ""), owner_hint)
        dx, dy = point_delta(owner_hint)
        clone = _clone_transformed_net_element(
            teacher_edge,
            dx,
            dy,
            resolved_edge_map,
        )
        clone.set("id", mapped_edge_id)
        clone.set("from", mapped_from)
        clone.set("to", mapped_to)
        geometry_source_edge = candidate_source_root.find(f"edge[@id='{mapped_edge_id}']")
        if geometry_source_edge is not None:
            geometry_report = _preserve_mapped_boundary_geometry(
                clone,
                geometry_source_edge,
                target_junction_ids=candidate_owner_ids,
                source_local_junction_ids=collapse_ids,
            )
            if geometry_report.get("status") == "pass":
                preserved_mapped_boundary_geometry_edge_ids.append(mapped_edge_id)
            elif geometry_report.get("status") == "blocked":
                boundary_geometry_preservation_failures.append(
                    {
                        "teacher_edge_id": teacher_edge_id,
                        "candidate_edge_id": mapped_edge_id,
                        **geometry_report,
                    }
                )
        clone.attrib.pop("tl", None)
        for attr in ("crossingEdges",):
            if attr in clone.attrib:
                clone.set(attr, map_crossing_edges(clone.attrib[attr], resolved_edge_map))
        teacher_edge_prefix = f"{teacher_edge_id}_"
        mapped_edge_prefix = f"{mapped_edge_id}_"
        for lane_index, lane in enumerate(clone.findall("lane")):
            old_lane_id = lane.attrib.get("id", "")
            suffix = old_lane_id[len(teacher_edge_prefix):] if old_lane_id.startswith(teacher_edge_prefix) else str(
                lane.attrib.get("index", lane_index)
            )
            lane.set("id", f"{mapped_edge_prefix}{suffix}")
        existing = candidate_edges.get(mapped_edge_id)
        if existing is not None:
            _remove_edge_lanes_from_destination_junction(candidate_root, existing, all_junctions=True)
            insert_at = list(candidate_root).index(existing)
            candidate_root.remove(existing)
            candidate_root.insert(insert_at, clone)
            replaced_boundary_edge_ids.append(teacher_edge_id)
        else:
            candidate_root.insert(_first_junction_index(candidate_root), clone)
            copied_boundary_edge_ids.append(teacher_edge_id)
        candidate_edges[mapped_edge_id] = clone

    # Rebuild every owner-local internal edge and junction under its explicit
    # candidate owner prefix.  This includes non-vehicle movement artifacts.
    copied_internal_edge_count = 0
    copied_internal_junction_count = 0
    for teacher_owner_id in teacher_owner_ids:
        candidate_owner_id = clean_owner_map[teacher_owner_id]
        dx, dy = point_delta(teacher_owner_id)
        teacher_prefix = f":{teacher_owner_id}_"
        candidate_prefix = f":{candidate_owner_id}_"
        for edge in teacher_root.findall("edge"):
            # Owner ids may themselves share prefixes (for example ``tls``
            # and ``tls__owner_01``).  A plain ``startswith`` check would
            # replay the secondary owner's internal artifacts a second time
            # under the primary owner, yielding ids such as
            # ``:candidate__owner_01_0`` whose implicit SUMO junction does
            # not exist.  Resolve ownership with the same longest-prefix
            # rule used for connection and ``via`` mapping.
            if teacher_owner_for(edge.attrib.get("id", "")) != teacher_owner_id:
                continue
            clone = _clone_transformed_net_element(
                edge,
                dx,
                dy,
                resolved_edge_map,
                teacher_owner_id,
                candidate_owner_id,
            )
            if "crossingEdges" in clone.attrib:
                clone.set("crossingEdges", map_crossing_edges(clone.attrib["crossingEdges"], resolved_edge_map))
            candidate_root.insert(_first_junction_index(candidate_root), clone)
            candidate_edges[clone.attrib.get("id", "")] = clone
            copied_internal_edge_count += 1
        for junction in teacher_root.findall("junction"):
            if teacher_owner_for(junction.attrib.get("id", "")) != teacher_owner_id:
                continue
            candidate_root.insert(
                _first_junction_index(candidate_root),
                _clone_transformed_junction(
                    junction,
                    dx,
                    dy,
                    resolved_edge_map,
                    teacher_prefix,
                    candidate_prefix,
                ),
            )
            copied_internal_junction_count += 1

        teacher_normal_junction = teacher_junctions.get(teacher_owner_id)
        candidate_normal_junction = candidate_root.find(f"junction[@id='{candidate_owner_id}']")
        if teacher_normal_junction is None or candidate_normal_junction is None:
            continue
        attrs = _mapped_junction_attrs(
            teacher_normal_junction,
            dx,
            dy,
            resolved_edge_map,
            teacher_prefix,
            candidate_prefix,
        )
        attrs["id"] = candidate_owner_id
        candidate_normal_junction.attrib.clear()
        candidate_normal_junction.attrib.update(attrs)
        for child in list(candidate_normal_junction):
            candidate_normal_junction.remove(child)
        for request in teacher_normal_junction.findall("request"):
            candidate_normal_junction.append(ET.Element("request", dict(request.attrib)))

    # Replace any old local tlLogics with one shared controller logic.  The
    # controller id intentionally remains the primary candidate id while its
    # connections may originate at either physical candidate owner.
    removed_tllogic_ids: list[str] = []
    for tl_logic in list(candidate_root.findall("tlLogic")):
        if tl_logic.attrib.get("id") in candidate_owner_ids | {candidate_controller_id}:
            removed_tllogic_ids.append(tl_logic.attrib.get("id", ""))
            candidate_root.remove(tl_logic)
    teacher_tllogic = teacher_root.find(f"tlLogic[@id='{teacher_controller_id}']")
    if teacher_tllogic is None:
        return _failure(f"teacher tlLogic not found: {teacher_controller_id}")
    controller_dx, controller_dy = point_delta(teacher_controller_id)
    copied_tllogic = _clone_transformed_net_element(
        teacher_tllogic,
        controller_dx,
        controller_dy,
        resolved_edge_map,
    )
    copied_tllogic.set("id", candidate_controller_id)
    candidate_root.insert(
        next(
            (index for index, child in enumerate(list(candidate_root)) if child.tag == "connection"),
            len(list(candidate_root)),
        ),
        copied_tllogic,
    )

    copied_connection_count = 0
    copied_controlled_connection_count = 0
    skipped_connections: list[dict[str, str]] = []
    copied_connections: list[dict[str, str]] = []
    for connection in relevant_connections:
        mapped = dict(connection.attrib)
        owner_hint = teacher_owner_for(connection.attrib.get("via", ""))
        if not owner_hint:
            for attr in ("from", "to"):
                owner_hint = teacher_edge_owner(teacher_edges.get(connection.attrib.get(attr, ""), ET.Element("edge")))
                if owner_hint:
                    break
        for attr in ("from", "to"):
            mapped_value = map_edge_ref(connection.attrib.get(attr, ""), resolved_edge_map)
            if not mapped_value:
                skipped_connections.append(dict(connection.attrib))
                break
            mapped[attr] = mapped_value
        else:
            if mapped.get("via"):
                mapped["via"] = candidate_internal_ref(mapped["via"])
            if mapped.get("tl") == teacher_controller_id:
                mapped["tl"] = candidate_controller_id
            if mapped.get("shape"):
                dx, dy = point_delta(owner_hint)
                mapped["shape"] = _translate_shape(mapped["shape"], dx, dy)
            via_value = mapped.get("via", "")
            if via_value:
                via_edge_id = via_value.rsplit("_", 1)[0]
                if via_edge_id not in candidate_edges:
                    skipped_connections.append(dict(connection.attrib))
                    continue
            if mapped["from"] not in candidate_edges or mapped["to"] not in candidate_edges:
                skipped_connections.append(dict(connection.attrib))
                continue
            candidate_root.append(ET.Element("connection", mapped))
            copied_connections.append(mapped)
            copied_connection_count += 1
            if mapped.get("tl") == candidate_controller_id and mapped.get("linkIndex") is not None:
                copied_controlled_connection_count += 1

    external_boundary_connection_report = _restore_external_boundary_connections(
        source_root=candidate_source_root,
        target_root=candidate_root,
        boundary_edge_ids=protected_edge_ids,
        source_local_junction_ids=collapse_ids,
    )

    # Remove member junctions that no longer have an edge endpoint, then clean
    # lane references and invalid connections before the external SUMO gates.
    candidate_edge_ids = {
        edge.attrib["id"] for edge in candidate_root.findall("edge") if edge.attrib.get("id")
    }
    for junction in list(candidate_root.findall("junction")):
        junction_id = junction.attrib.get("id", "")
        if junction_id not in collapse_ids or junction_id in candidate_owner_ids:
            continue
        if not any(
            junction_id in (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
            for edge in candidate_root.findall("edge")
        ):
            candidate_root.remove(junction)

    for junction in candidate_root.findall("junction"):
        inc_lanes = [
            lane
            for lane in _split(junction.attrib.get("incLanes", ""))
            if lane.rsplit("_", 1)[0] in candidate_edge_ids
        ]
        junction.set("incLanes", " ".join(inc_lanes))
    for owner_id in candidate_owner_ids:
        junction = candidate_root.find(f"junction[@id='{owner_id}']")
        if junction is None:
            continue
        incoming_lanes = [
            lane.attrib["id"]
            for edge in candidate_root.findall("edge")
            if edge.attrib.get("to") == owner_id
            for lane in edge.findall("lane")
            if lane.attrib.get("id")
        ]
        existing_inc_lanes = _split(junction.attrib.get("incLanes", ""))
        junction.set("incLanes", " ".join(dict.fromkeys([*existing_inc_lanes, *incoming_lanes])))

    invalid_connections: list[dict[str, str]] = []
    dangling_connections: list[dict[str, str]] = []
    edge_lane_counts = _net_lane_counts(candidate_root)
    for connection in list(candidate_root.findall("connection")):
        if connection.attrib.get("from") not in candidate_edge_ids or connection.attrib.get("to") not in candidate_edge_ids:
            dangling_connections.append(dict(connection.attrib))
            candidate_root.remove(connection)
            continue
        if not _connection_lane_indices_valid(connection, edge_lane_counts):
            invalid_connections.append(dict(connection.attrib))
            candidate_root.remove(connection)

    actual_controlled_connections = [
        connection
        for connection in candidate_root.findall("connection")
        if connection.attrib.get("tl") == candidate_controller_id and connection.attrib.get("linkIndex") is not None
    ]
    actual_link_indices = {str(connection.attrib.get("linkIndex", "")) for connection in actual_controlled_connections}
    invalid_controlled_connections = [
        connection
        for connection in [*invalid_connections, *dangling_connections]
        if connection.get("tl") == candidate_controller_id and connection.get("linkIndex") is not None
    ]
    missing_link_indices = sorted(teacher_link_indices - actual_link_indices, key=lambda value: int(value) if value.isdigit() else value)
    unexpected_link_indices = sorted(actual_link_indices - teacher_link_indices, key=lambda value: int(value) if value.isdigit() else value)
    status = "pass"
    if (
        skipped_connections
        or invalid_controlled_connections
        or missing_link_indices
        or unexpected_link_indices
        or copied_controlled_connection_count != len(controlled_connections)
        or boundary_geometry_preservation_failures
        or not output_file.parent.exists()
    ):
        status = "blocked"

    ET.indent(candidate_root, space="    ")
    candidate_tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": status,
        "claim_status": "diagnostic-demo",
        "net_file": str(output_file),
        "candidate_controller_id": candidate_controller_id,
        "teacher_controller_id": teacher_controller_id,
        "owner_map": dict(sorted(clean_owner_map.items())),
        "junction_map": dict(sorted(clean_junction_map.items())),
        "collapse_junction_ids": sorted(collapse_ids),
        "teacher_owner_ids": teacher_owner_ids,
        "candidate_owner_ids": sorted(candidate_owner_ids),
        "teacher_boundary_edge_ids": boundary_edge_ids,
        "effective_edge_map": dict(sorted(resolved_edge_map.items())),
        "edge_mapping_sources": dict(sorted(edge_mapping_sources.items())),
        "generated_boundary_edge_ids": sorted(generated_boundary_edge_ids),
        "unanchored_boundary_edge_count": 0,
        "unanchored_boundary_edge_ids": [],
        "copied_boundary_edge_ids": sorted(copied_boundary_edge_ids),
        "replaced_boundary_edge_ids": sorted(replaced_boundary_edge_ids),
        "preserved_mapped_boundary_geometry_edge_ids": sorted(
            set(preserved_mapped_boundary_geometry_edge_ids)
        ),
        "boundary_geometry_preservation_failure_count": len(boundary_geometry_preservation_failures),
        "boundary_geometry_preservation_failures": boundary_geometry_preservation_failures,
        "restored_external_boundary_connection_count": external_boundary_connection_report[
            "restored_connection_count"
        ],
        "restored_external_boundary_connections": external_boundary_connection_report[
            "restored_connections"
        ],
        "preserved_existing_external_boundary_connection_count": external_boundary_connection_report[
            "preserved_existing_connection_count"
        ],
        "preserved_existing_external_boundary_connections": external_boundary_connection_report[
            "preserved_existing_connections"
        ],
        "skipped_external_boundary_connection_count": external_boundary_connection_report[
            "skipped_connection_count"
        ],
        "skipped_external_boundary_connections": external_boundary_connection_report[
            "skipped_connections"
        ],
        "removed_internal_edge_count": len(removed_internal_edge_ids),
        "removed_internal_junction_count": len(removed_internal_junction_ids),
        "removed_member_edge_count": len(removed_member_edge_ids),
        "removed_connection_count": removed_connection_count,
        "removed_mapped_edge_connection_count": removed_mapped_edge_connection_count,
        "copied_internal_edge_count": copied_internal_edge_count,
        "copied_internal_junction_count": copied_internal_junction_count,
        "removed_tllogic_ids": sorted(removed_tllogic_ids),
        "teacher_controlled_connection_count": len(controlled_connections),
        "teacher_link_indices": sorted(teacher_link_indices, key=lambda value: int(value) if value.isdigit() else value),
        "copied_connection_count": copied_connection_count,
        "copied_controlled_connection_count": copied_controlled_connection_count,
        "actual_controlled_connection_count": len(actual_controlled_connections),
        "actual_link_indices": sorted(actual_link_indices, key=lambda value: int(value) if value.isdigit() else value),
        "missing_link_indices": missing_link_indices,
        "unexpected_link_indices": unexpected_link_indices,
        "skipped_connections": skipped_connections,
        "invalid_connection_count": len(invalid_connections),
        "invalid_connections": invalid_connections,
        "dangling_connection_count": len(dangling_connections),
        "dangling_connections": dangling_connections,
        "invalid_controlled_connection_count": len(invalid_controlled_connections),
        "policy": "explicit multi-owner closure; generated boundary edges remain reviewable artifacts",
    }


def build_scoped_teacher_tls_cell_replay_plan(
    *,
    candidate_net_file: Path,
    teacher_net_file: Path,
    teacher_junction_id: str,
    candidate_junction_id: str,
    candidate_junction_ids: set[str] | list[str] | None = None,
    approach_pairs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Derive an auditable boundary map for a split TLS cell.

    The plan follows same-way edge chains through the candidate member nodes.
    It does not invent a destination edge: a reference boundary with no
    candidate family is left as an explicit identity/copy boundary and marked
    for review in the returned evidence.
    """

    if not candidate_net_file.exists() or not teacher_net_file.exists():
        return _failure("candidate or teacher net file is missing")
    try:
        candidate_root = ET.parse(candidate_net_file).getroot()
        teacher_root = ET.parse(teacher_net_file).getroot()
    except (ET.ParseError, OSError, KeyError, ValueError) as exc:
        return _failure(f"TLS cell replay plan parse failed: {type(exc).__name__}: {exc}")
    teacher_edges = {
        edge.attrib["id"]: edge
        for edge in teacher_root.findall("edge")
        if edge.attrib.get("id")
    }
    candidate_edges = {
        edge.attrib["id"]: edge
        for edge in candidate_root.findall("edge")
        if edge.attrib.get("id")
    }
    teacher_junction = teacher_root.find(f"junction[@id='{teacher_junction_id}']")
    candidate_junction = candidate_root.find(f"junction[@id='{candidate_junction_id}']")
    if teacher_junction is None or candidate_junction is None:
        return _failure("TLS cell replay plan target junction is missing")
    member_ids = {
        str(value)
        for value in (candidate_junction_ids or set())
        if str(value)
    }
    member_ids.add(candidate_junction_id)
    teacher_boundary_edge_ids = _teacher_boundary_edge_ids_touching_internal_subgraph(
        teacher_root.findall("connection"),
        teacher_edges,
        teacher_junction_id,
    )
    pair_edge_map = {
        str(pair.get("reference_edge_id", "")): str(pair.get("candidate_edge_id", ""))
        for pair in (approach_pairs or [])
        if isinstance(pair, dict)
        and str(pair.get("reference_edge_id", ""))
        and str(pair.get("candidate_edge_id", ""))
    }

    def lane_count(edge: ET.Element | None) -> int:
        return len(edge.findall("lane")) if edge is not None else 0

    def boundary_direction(edge: ET.Element) -> str:
        return "outgoing" if edge.attrib.get("from") == teacher_junction_id else "incoming"

    def candidate_boundary_side_matches(edge: ET.Element, direction: str) -> bool:
        """Require the candidate edge to leave/enter the split cell correctly.

        An OSM split often contains an edge with the same signed id as a
        teacher boundary edge, but on the opposite side of the physical cell.
        Treating that id as an identity mapping silently reverses the approach
        and can create duplicate candidate boundary aliases.
        """

        member_endpoint = edge.attrib.get("from" if direction == "outgoing" else "to", "")
        return member_endpoint in member_ids

    def family_candidates(
        teacher_edge: ET.Element,
        direction: str,
        *,
        excluded_candidate_ids: set[str] | None = None,
        family_override: str | None = None,
    ) -> list[tuple[int, str, ET.Element]]:
        teacher_id = teacher_edge.attrib.get("id", "")
        teacher_family = family_override or _signed_edge_family_id(teacher_id)
        expected_lane_count = lane_count(teacher_edge)
        excluded_candidate_ids = excluded_candidate_ids or set()
        ranked: list[tuple[int, str, ET.Element]] = []
        for candidate_id, candidate_edge in candidate_edges.items():
            if candidate_id.startswith(":") or candidate_edge.attrib.get("function") in {
                "internal",
                "crossing",
                "walkingarea",
            }:
                continue
            if candidate_id in excluded_candidate_ids:
                continue
            if _signed_edge_family_id(candidate_id) != teacher_family:
                continue
            if not candidate_boundary_side_matches(candidate_edge, direction):
                continue
            score = abs(lane_count(candidate_edge) - expected_lane_count) * 100
            frontier_endpoint = candidate_edge.attrib.get("from" if direction == "incoming" else "to", "")
            if frontier_endpoint not in member_ids:
                score -= 50
            if candidate_id == teacher_id:
                score -= 1000
            ranked.append((score, candidate_id, candidate_edge))
        return sorted(ranked, key=lambda item: (item[0], item[1]))

    effective_edge_map: dict[str, str] = {}
    inferred_boundary_edge_ids: list[str] = []
    copied_boundary_edge_ids: list[str] = []
    mapping_conflicts: list[dict[str, object]] = []
    used_candidate_boundary_ids: set[str] = set()

    def counterpart_candidate_for_teacher_edge(teacher_edge_id: str, direction: str) -> str:
        """Use a paired approach's opposite candidate edge when OSM renamed a way."""

        opposite_teacher_id = _opposite_direction_edge_id(teacher_edge_id)
        paired_candidate_id = pair_edge_map.get(opposite_teacher_id, "")
        if not paired_candidate_id:
            return ""
        opposite_candidate_id = _opposite_direction_edge_id(paired_candidate_id)
        opposite_candidate = candidate_edges.get(opposite_candidate_id)
        if opposite_candidate is not None and candidate_boundary_side_matches(opposite_candidate, direction):
            return opposite_candidate_id
        candidate_family = _edge_family_id(paired_candidate_id)
        alternatives = [
            (candidate_id, edge)
            for candidate_id, edge in candidate_edges.items()
            if _edge_family_id(candidate_id) == candidate_family
            and candidate_boundary_side_matches(edge, direction)
            and candidate_id not in used_candidate_boundary_ids
        ]
        alternatives.sort(key=lambda item: item[0])
        return alternatives[0][0] if alternatives else ""

    for teacher_edge_id in teacher_boundary_edge_ids:
        teacher_edge = teacher_edges[teacher_edge_id]
        direction = boundary_direction(teacher_edge)
        candidate_edge_id = pair_edge_map.get(teacher_edge_id, "")
        if candidate_edge_id and (
            candidate_edge_id not in candidate_edges
            or not candidate_boundary_side_matches(candidate_edges[candidate_edge_id], direction)
        ):
            mapping_conflicts.append(
                {
                    "teacher_edge_id": teacher_edge_id,
                    "candidate_edge_id": candidate_edge_id,
                    "reason": "approach_pair_candidate_is_not_on_expected_boundary_side",
                    "direction": direction,
                }
            )
            candidate_edge_id = ""
        if not candidate_edge_id:
            candidate_edge_id = counterpart_candidate_for_teacher_edge(teacher_edge_id, direction)
        if not candidate_edge_id:
            exact_candidate = candidate_edges.get(teacher_edge_id)
            if exact_candidate is not None and candidate_boundary_side_matches(exact_candidate, direction):
                candidate_edge_id = teacher_edge_id
            else:
                ranked = family_candidates(
                    teacher_edge,
                    direction,
                    excluded_candidate_ids=used_candidate_boundary_ids,
                )
                candidate_edge_id = ranked[0][1] if ranked else ""
        if candidate_edge_id and candidate_edge_id in used_candidate_boundary_ids:
            mapping_conflicts.append(
                {
                    "teacher_edge_id": teacher_edge_id,
                    "candidate_edge_id": candidate_edge_id,
                    "reason": "candidate_boundary_edge_reused",
                    "direction": direction,
                }
            )
        if candidate_edge_id:
            effective_edge_map[teacher_edge_id] = candidate_edge_id
            inferred_boundary_edge_ids.append(teacher_edge_id)
            used_candidate_boundary_ids.add(candidate_edge_id)
        else:
            effective_edge_map[teacher_edge_id] = teacher_edge_id
            copied_boundary_edge_ids.append(teacher_edge_id)

    def follow_chain_endpoint(
        candidate_edge: ET.Element,
        direction: str,
        family: str,
    ) -> str:
        endpoint = candidate_edge.attrib.get("to" if direction == "outgoing" else "from", "")
        visited = {candidate_edge.attrib.get("id", "")}
        while endpoint in member_ids:
            if direction == "outgoing":
                next_edges = [
                    edge
                    for edge in candidate_edges.values()
                    if edge.attrib.get("id") not in visited
                    and not edge.attrib.get("id", "").startswith(":")
                    and _signed_edge_family_id(edge.attrib.get("id", "")) == family
                    and edge.attrib.get("from") == endpoint
                ]
                next_edges.sort(key=lambda edge: edge.attrib.get("id", ""))
                if not next_edges:
                    break
                next_edge = next_edges[0]
                visited.add(next_edge.attrib.get("id", ""))
                endpoint = next_edge.attrib.get("to", "")
            else:
                previous_edges = [
                    edge
                    for edge in candidate_edges.values()
                    if edge.attrib.get("id") not in visited
                    and not edge.attrib.get("id", "").startswith(":")
                    and _signed_edge_family_id(edge.attrib.get("id", "")) == family
                    and edge.attrib.get("to") == endpoint
                ]
                previous_edges.sort(key=lambda edge: edge.attrib.get("id", ""))
                if not previous_edges:
                    break
                previous_edge = previous_edges[0]
                visited.add(previous_edge.attrib.get("id", ""))
                endpoint = previous_edge.attrib.get("from", "")
        return endpoint

    junction_map: dict[str, str] = {}
    for teacher_edge_id in teacher_boundary_edge_ids:
        teacher_edge = teacher_edges[teacher_edge_id]
        candidate_edge = candidate_edges.get(effective_edge_map.get(teacher_edge_id, ""))
        if candidate_edge is None:
            continue
        direction = boundary_direction(teacher_edge)
        teacher_external_endpoint = (
            teacher_edge.attrib.get("to", "")
            if direction == "outgoing"
            else teacher_edge.attrib.get("from", "")
        )
        candidate_external_endpoint = follow_chain_endpoint(
            candidate_edge,
            direction,
            _signed_edge_family_id(candidate_edge.attrib.get("id", "")),
        )
        if (
            teacher_external_endpoint
            and teacher_external_endpoint != teacher_junction_id
            and candidate_external_endpoint
            and candidate_external_endpoint not in member_ids
        ):
            junction_map[teacher_external_endpoint] = candidate_external_endpoint

    teacher_junctions_by_id = {
        junction.attrib["id"]: junction
        for junction in teacher_root.findall("junction")
        if junction.attrib.get("id")
    }
    candidate_junctions_by_id = {
        junction.attrib["id"]: junction
        for junction in candidate_root.findall("junction")
        if junction.attrib.get("id")
    }

    def internal_owner(value: str) -> str:
        for junction_id in sorted(teacher_junctions_by_id, key=len, reverse=True):
            if value.startswith(f":{junction_id}_"):
                return junction_id
        return ""

    controller_connections = [
        connection
        for connection in teacher_root.findall("connection")
        if connection.attrib.get("tl") == teacher_junction_id and connection.attrib.get("linkIndex")
    ]
    teacher_controller_owner_ids = sorted(
        {
            owner
            for connection in controller_connections
            for owner in [internal_owner(connection.attrib.get("via", ""))]
            if owner
        }
    )
    owner_connection_counts = Counter(
        internal_owner(connection.attrib.get("via", ""))
        for connection in controller_connections
        if internal_owner(connection.attrib.get("via", ""))
    )
    try:
        controller_dx = float(candidate_junction.attrib.get("x", "0") or 0) - float(
            teacher_junction.attrib.get("x", "0") or 0
        )
        controller_dy = float(candidate_junction.attrib.get("y", "0") or 0) - float(
            teacher_junction.attrib.get("y", "0") or 0
        )
    except (TypeError, ValueError):
        controller_dx = controller_dy = 0.0

    controller_owner_candidates: dict[str, list[dict[str, object]]] = {}
    controller_owner_map: dict[str, str] = {}
    for owner_id in teacher_controller_owner_ids:
        if owner_id == teacher_junction_id:
            controller_owner_map[owner_id] = candidate_junction_id
            continue
        teacher_owner = teacher_junctions_by_id.get(owner_id)
        if teacher_owner is None:
            continue
        try:
            expected_x = float(teacher_owner.attrib.get("x", "0") or 0) + controller_dx
            expected_y = float(teacher_owner.attrib.get("y", "0") or 0) + controller_dy
        except (TypeError, ValueError):
            expected_x = expected_y = 0.0
        candidates: list[dict[str, object]] = []
        for candidate_owner_id, candidate_owner in candidate_junctions_by_id.items():
            try:
                distance_m = math.hypot(
                    float(candidate_owner.attrib.get("x", "0") or 0) - expected_x,
                    float(candidate_owner.attrib.get("y", "0") or 0) - expected_y,
                )
            except (TypeError, ValueError):
                continue
            candidates.append(
                {
                    "candidate_junction_id": candidate_owner_id,
                    "candidate_type": candidate_owner.attrib.get("type", ""),
                    "distance_m": round(distance_m, 3),
                    "candidate_is_traffic_light": candidate_owner.attrib.get("type") == "traffic_light",
                    "candidate_is_declared_cell_member": candidate_owner_id in member_ids,
                }
            )
        candidates.sort(
            key=lambda item: (
                not bool(item["candidate_is_traffic_light"]),
                not bool(item["candidate_is_declared_cell_member"]),
                float(item["distance_m"]),
                str(item["candidate_junction_id"]),
            )
        )
        controller_owner_candidates[owner_id] = candidates[:10]
        if candidates and float(candidates[0]["distance_m"]) <= 100.0:
            controller_owner_map[owner_id] = str(candidates[0]["candidate_junction_id"])

    teacher_controller_edge_ids = sorted(
        {
            edge_id
            for connection in controller_connections
            for edge_id in (connection.attrib.get("from", ""), connection.attrib.get("to", ""))
            if edge_id and not edge_id.startswith(":")
        }
    )
    identity_available_controller_edge_ids = sorted(
        edge_id
        for edge_id in teacher_controller_edge_ids
        if edge_id not in effective_edge_map and edge_id in candidate_edges
    )
    unmapped_controller_edge_ids = sorted(
        edge_id
        for edge_id in teacher_controller_edge_ids
        if edge_id not in effective_edge_map and edge_id not in candidate_edges
    )
    extra_controller_owner_ids = [
        owner_id for owner_id in teacher_controller_owner_ids if owner_id != teacher_junction_id
    ]
    shared_controller_scope = {
        "status": "pass" if not extra_controller_owner_ids else "needs_expanded_scope",
        "teacher_controller_id": teacher_junction_id,
        "teacher_controller_connection_count": len(controller_connections),
        "teacher_controller_link_indices": sorted(
            {str(connection.attrib["linkIndex"]) for connection in controller_connections},
            key=lambda value: int(value) if value.isdigit() else value,
        ),
        "teacher_internal_owner_ids": teacher_controller_owner_ids,
        "extra_teacher_internal_owner_ids": extra_controller_owner_ids,
        "teacher_internal_owner_connection_counts": dict(sorted(owner_connection_counts.items())),
        "candidate_owner_map": dict(sorted(controller_owner_map.items())),
        "candidate_owner_candidates": controller_owner_candidates,
        "teacher_controller_edge_ids": teacher_controller_edge_ids,
        "identity_available_controller_edge_ids": identity_available_controller_edge_ids,
        "unmapped_controller_edge_ids": unmapped_controller_edge_ids,
        "policy": (
            "shared TLS controllers require an explicit owner closure and boundary edge mapping; "
            "nearest candidate junctions are evidence only and do not authorize adoption"
        ),
    }

    return {
        "status": "pass" if teacher_boundary_edge_ids else "blocked",
        "claim_status": "diagnostic-demo",
        "teacher_junction_id": teacher_junction_id,
        "candidate_junction_id": candidate_junction_id,
        "candidate_junction_ids": sorted(member_ids),
        "teacher_boundary_edge_ids": teacher_boundary_edge_ids,
        "edge_map": dict(sorted(effective_edge_map.items())),
        "junction_map": dict(sorted(junction_map.items())),
        "approach_edge_map": dict(sorted(pair_edge_map.items())),
        "inferred_boundary_edge_ids": sorted(inferred_boundary_edge_ids),
        "copied_boundary_edge_ids": sorted(copied_boundary_edge_ids),
        "mapping_conflicts": mapping_conflicts,
        "candidate_boundary_edge_reuse_count": sum(
            1
            for value, count in Counter(effective_edge_map.values()).items()
            if count > 1
        ),
        "shared_controller_scope": shared_controller_scope,
        "mapping_policy": "approach-pair_then_same_signed_family_then_explicit_teacher_boundary_copy",
    }


def build_shared_teacher_tls_controller_replay_plan(
    *,
    candidate_net_file: Path,
    teacher_net_file: Path,
    teacher_controller_id: str,
    candidate_controller_id: str,
    candidate_junction_ids: set[str] | list[str] | None = None,
    approach_pairs: list[dict[str, object]] | None = None,
    collapse_junction_ids: set[str] | list[str] | None = None,
    candidate_owner_map: dict[str, str] | None = None,
) -> dict[str, object]:
    """Build an explicit replay plan for a shared TLS controller.

    The ordinary scoped planner intentionally reports a shared controller as
    ``needs_expanded_scope``.  This planner closes that scope only when every
    teacher internal owner has a concrete candidate owner.  Boundary matching
    prefers the queue's approach pair, then an exact signed edge family with
    compatible owner-side topology.  A missing family is represented by a
    deterministic teacher-boundary copy id; it is never silently reused from a
    nearby road.
    """

    if not candidate_net_file.exists() or not teacher_net_file.exists():
        return _failure("candidate or teacher net file is missing")
    try:
        candidate_root = ET.parse(candidate_net_file).getroot()
        teacher_root = ET.parse(teacher_net_file).getroot()
    except (ET.ParseError, OSError, ValueError) as exc:
        return _failure(f"shared TLS replay plan parse failed: {type(exc).__name__}: {exc}")

    candidate_edges = {
        edge.attrib["id"]: edge
        for edge in candidate_root.findall("edge")
        if edge.attrib.get("id")
    }
    teacher_edges = {
        edge.attrib["id"]: edge
        for edge in teacher_root.findall("edge")
        if edge.attrib.get("id")
    }
    candidate_junctions = {
        junction.attrib["id"]: junction
        for junction in candidate_root.findall("junction")
        if junction.attrib.get("id")
    }
    teacher_junctions = {
        junction.attrib["id"]: junction
        for junction in teacher_root.findall("junction")
        if junction.attrib.get("id")
    }
    base_candidate_ids = {
        str(item)
        for item in (candidate_junction_ids or set())
        if str(item)
    }
    base_candidate_ids.add(candidate_controller_id)
    base_plan = build_scoped_teacher_tls_cell_replay_plan(
        candidate_net_file=candidate_net_file,
        teacher_net_file=teacher_net_file,
        teacher_junction_id=teacher_controller_id,
        candidate_junction_id=candidate_controller_id,
        candidate_junction_ids=base_candidate_ids,
        approach_pairs=approach_pairs,
    )
    if base_plan.get("status") != "pass":
        return {
            **base_plan,
            "shared_controller_replay_status": "blocked",
            "shared_controller_replay_reason": "base_boundary_plan_not_pass",
        }
    shared_scope = base_plan.get("shared_controller_scope", {})
    if not isinstance(shared_scope, dict):
        return _failure("base plan did not provide shared_controller_scope evidence")
    inferred_owner_map = {
        str(key): str(value)
        for key, value in (shared_scope.get("candidate_owner_map", {}) or {}).items()
        if str(key) and str(value)
    }
    if candidate_owner_map:
        inferred_owner_map.update(
            {
                str(key): str(value)
                for key, value in candidate_owner_map.items()
                if str(key) and str(value)
            }
        )
    inferred_owner_map.setdefault(teacher_controller_id, candidate_controller_id)
    # A reference owner can be represented by a pre-joined candidate cluster.
    # The base planner prefers declared cell members for stability, which is
    # correct for a single-owner cell but wrong for a shared controller when a
    # nearby traffic-light cluster is present.  Prefer that explicit cluster
    # representation when it is available; otherwise retain the base planner
    # evidence (for example the unjoined OSM source).
    for owner_id in list(inferred_owner_map):
        if owner_id == teacher_controller_id:
            continue
        candidates = [
            item
            for item in (shared_scope.get("candidate_owner_candidates", {}).get(owner_id, []) or [])
            if isinstance(item, dict)
            and str(item.get("candidate_junction_id", "")) in candidate_junctions
            and str(item.get("candidate_junction_id", "")).startswith("cluster_")
            and item.get("candidate_type") == "traffic_light"
        ]
        if candidates:
            candidates.sort(
                key=lambda item: (
                    float(item.get("distance_m", float("inf"))),
                    str(item.get("candidate_junction_id", "")),
                )
            )
            inferred_owner_map[owner_id] = str(candidates[0]["candidate_junction_id"])
    missing_owner_ids = [
        owner_id
        for owner_id, candidate_owner_id in inferred_owner_map.items()
        if owner_id not in teacher_junctions or candidate_owner_id not in candidate_junctions
    ]
    if missing_owner_ids:
        return {
            **base_plan,
            "status": "blocked",
            "shared_controller_replay_status": "blocked",
            "shared_controller_replay_reason": "owner_closure_missing",
            "owner_map": dict(sorted(inferred_owner_map.items())),
            "missing_owner_ids": missing_owner_ids,
        }

    teacher_owner_ids = sorted(inferred_owner_map, key=len, reverse=True)

    def owner_for(value: str) -> str:
        for owner_id in teacher_owner_ids:
            if value.startswith(f":{owner_id}_"):
                return owner_id
        return ""

    def edge_owner(edge: ET.Element) -> str:
        for endpoint in (edge.attrib.get("from", ""), edge.attrib.get("to", "")):
            if endpoint in teacher_owner_ids:
                return endpoint
        return ""

    def has_owner_side(edge: ET.Element, owner_id: str, side: str) -> bool:
        endpoint = edge.attrib.get("from" if side == "from" else "to", "")
        return endpoint == owner_id or endpoint in {
            inferred_owner_map.get(owner_id, ""),
            *{
                str(item)
                for item in (collapse_junction_ids or set())
                if str(item)
            },
        }

    relevant_connections = [
        connection
        for connection in teacher_root.findall("connection")
        if (
            owner_for(connection.attrib.get("from", ""))
            or owner_for(connection.attrib.get("to", ""))
            or owner_for(connection.attrib.get("via", ""))
            or connection.attrib.get("tl") == teacher_controller_id
        )
    ]
    boundary_edge_ids: list[str] = []
    seen_boundary_edge_ids: set[str] = set()
    for connection in relevant_connections:
        for attr in ("from", "to"):
            edge_id = connection.attrib.get(attr, "")
            if not edge_id or edge_id.startswith(":") or edge_id not in teacher_edges:
                continue
            if edge_id not in seen_boundary_edge_ids:
                seen_boundary_edge_ids.add(edge_id)
                boundary_edge_ids.append(edge_id)
    for edge in teacher_edges.values():
        if not owner_for(edge.attrib.get("id", "")):
            continue
        for edge_id in _split(edge.attrib.get("crossingEdges", "")):
            if edge_id in teacher_edges and edge_id not in seen_boundary_edge_ids:
                seen_boundary_edge_ids.add(edge_id)
                boundary_edge_ids.append(edge_id)

    pair_map = {
        str(pair.get("reference_edge_id", "")): str(pair.get("candidate_edge_id", ""))
        for pair in (approach_pairs or [])
        if isinstance(pair, dict)
        and str(pair.get("reference_edge_id", ""))
        and str(pair.get("candidate_edge_id", ""))
    }
    requested_edge_map = {
        str(key): str(value)
        for key, value in (base_plan.get("edge_map", {}) or {}).items()
        if str(key) and str(value)
    }
    base_edge_map = dict(requested_edge_map)
    requested_edge_map.update(pair_map)
    resolved_edge_map: dict[str, str] = {}
    edge_mapping_sources: dict[str, str] = {}
    mapping_conflicts: list[dict[str, object]] = []
    mapping_rejections: list[dict[str, object]] = []
    used_candidate_edge_ids: set[str] = set()
    target_candidate_ids = {
        str(item)
        for item in (collapse_junction_ids or base_candidate_ids)
        if str(item)
    }
    target_candidate_ids.update(inferred_owner_map.values())

    def compatible_pair(teacher_edge_id: str, candidate_edge_id: str) -> bool:
        teacher_edge = teacher_edges.get(teacher_edge_id)
        candidate_edge = candidate_edges.get(candidate_edge_id)
        if teacher_edge is None or candidate_edge is None:
            return False
        if candidate_edge_id.startswith(":") or candidate_edge.attrib.get("function") in {
            "internal",
            "crossing",
            "walkingarea",
        }:
            return False
        teacher_local_at_start = teacher_edge.attrib.get("from", "") in teacher_owner_ids
        teacher_local_at_end = teacher_edge.attrib.get("to", "") in teacher_owner_ids
        candidate_local_at_start = candidate_edge.attrib.get("from", "") in target_candidate_ids
        candidate_local_at_end = candidate_edge.attrib.get("to", "") in target_candidate_ids
        # An explicit approach pair is topology evidence and commonly maps a
        # synthetic teacher id to a differently named OSM way.  Validate its
        # directed cell side, not an impossible signed-id family equality.
        return (
            teacher_local_at_start != teacher_local_at_end
            and candidate_local_at_start != candidate_local_at_end
            and teacher_local_at_start == candidate_local_at_start
        )

    def generated_edge_id(teacher_edge_id: str) -> str:
        safe = "".join(
            character if character.isalnum() or character in "_.-" else "_"
            for character in teacher_edge_id
        ).strip("_") or "edge"
        candidate = f"torii_shared_{safe}"
        suffix = 2
        while candidate in candidate_edges or candidate in used_candidate_edge_ids:
            candidate = f"torii_shared_{safe}_{suffix}"
            suffix += 1
        return candidate

    for teacher_edge_id in boundary_edge_ids:
        teacher_edge = teacher_edges[teacher_edge_id]
        chosen = requested_edge_map.get(teacher_edge_id, "")
        requested_source = (
            "explicit_approach_pair"
            if teacher_edge_id in pair_map
            else "base_plan_edge_map"
            if teacher_edge_id in base_edge_map
            else ""
        )
        if (
            chosen
            and compatible_pair(teacher_edge_id, chosen)
            and (
                teacher_edge_id in pair_map
                or (requested_source == "base_plan_edge_map" and chosen == teacher_edge_id)
            )
        ):
            edge_mapping_sources[teacher_edge_id] = (
                "explicit_approach_pair" if teacher_edge_id in pair_map else "base_plan_edge_map"
            )
        else:
            if chosen and chosen in candidate_edges:
                mapping_rejections.append(
                    {
                        "teacher_edge_id": teacher_edge_id,
                        "candidate_edge_id": chosen,
                        "reason": "explicit_candidate_missing_or_boundary_side_mismatch",
                    }
                )
            chosen = ""
        if not chosen:
            candidates: list[tuple[int, str]] = []
            teacher_from_owner = teacher_edge.attrib.get("from", "") in teacher_owner_ids
            teacher_to_owner = teacher_edge.attrib.get("to", "") in teacher_owner_ids
            for candidate_edge_id, candidate_edge in candidate_edges.items():
                if (
                    candidate_edge_id.startswith(":")
                    or candidate_edge.attrib.get("function") in {"internal", "crossing", "walkingarea"}
                    or candidate_edge_id in used_candidate_edge_ids
                    or _signed_edge_family_id(candidate_edge_id) != _signed_edge_family_id(teacher_edge_id)
                ):
                    continue
                score = abs(len(candidate_edge.findall("lane")) - len(teacher_edge.findall("lane"))) * 100
                if candidate_edge_id == teacher_edge_id:
                    score -= 1000
                if teacher_from_owner:
                    score += 0 if has_owner_side(candidate_edge, inferred_owner_map[teacher_edge.attrib["from"]], "from") else 1000
                if teacher_to_owner:
                    score += 0 if has_owner_side(candidate_edge, inferred_owner_map[teacher_edge.attrib["to"]], "to") else 1000
                candidates.append((score, candidate_edge_id))
            if candidates:
                candidates.sort()
                best_score, best_id = candidates[0]
                owner_side_match = (
                    (teacher_from_owner and has_owner_side(candidate_edges[best_id], inferred_owner_map[teacher_edge.attrib["from"]], "from"))
                    or (teacher_to_owner and has_owner_side(candidate_edges[best_id], inferred_owner_map[teacher_edge.attrib["to"]], "to"))
                )
                if best_score < 1000 or (best_score == 1000 and owner_side_match):
                    chosen = best_id
                    edge_mapping_sources[teacher_edge_id] = "signed_family_owner_side"
                elif (
                    requested_source == "base_plan_edge_map"
                    and len(candidates) == 1
                    and _signed_edge_family_id(best_id) == _signed_edge_family_id(teacher_edge_id)
                ):
                    # The OSM network may contain one split fragment with the
                    # same signed family but no endpoint at the collapsed
                    # owner.  Replacing that exact family edge with the
                    # teacher boundary is still explicit and auditable; a
                    # different-family nearest edge is never accepted here.
                    chosen = best_id
                    edge_mapping_sources[teacher_edge_id] = "base_plan_signed_family_identity"
        if not chosen:
            chosen = generated_edge_id(teacher_edge_id)
            edge_mapping_sources[teacher_edge_id] = "explicit_teacher_boundary_copy"
        if chosen in used_candidate_edge_ids and chosen != resolved_edge_map.get(teacher_edge_id):
            # Bridges may legitimately be shared by two owners, but a single
            # teacher boundary id must still have one deterministic target.
            previous = next(
                (source for source, target in resolved_edge_map.items() if target == chosen),
                "",
            )
            if previous and previous != teacher_edge_id:
                mapping_conflicts.append(
                    {
                        "teacher_edge_id": teacher_edge_id,
                        "candidate_edge_id": chosen,
                        "reason": "candidate_boundary_edge_reused",
                    }
                )
        used_candidate_edge_ids.add(chosen)
        resolved_edge_map[teacher_edge_id] = chosen

    resolved_junction_map: dict[str, str] = {}
    # Use a selected candidate edge to map the remote endpoint of an approach
    # pair.  This is especially important for a way whose OSM id differs from
    # the teacher edge id (for example gneE18 -> 816287496#0).
    def add_endpoint_evidence(teacher_edge: ET.Element, candidate_edge: ET.Element | None) -> None:
        if candidate_edge is None:
            return
        for side in ("from", "to"):
            teacher_endpoint = teacher_edge.attrib.get(side, "")
            if not teacher_endpoint or teacher_endpoint in teacher_owner_ids:
                continue
            candidate_endpoint = candidate_edge.attrib.get(side, "")
            if candidate_endpoint and candidate_endpoint not in target_candidate_ids:
                resolved_junction_map.setdefault(teacher_endpoint, candidate_endpoint)

    for teacher_edge_id, candidate_edge_id in resolved_edge_map.items():
        add_endpoint_evidence(teacher_edges[teacher_edge_id], candidate_edges.get(candidate_edge_id))
    # Preserve endpoint evidence from a queue approach pair even if the edge
    # family itself is rejected and the teacher edge is copied.  This is a
    # valid topology hint for a renamed OSM way, not permission to reuse that
    # candidate edge as the teacher boundary.
    for teacher_edge_id, candidate_edge_id in pair_map.items():
        if teacher_edge_id in teacher_edges and candidate_edge_id in candidate_edges:
            pair_teacher_edge = teacher_edges[teacher_edge_id]
            pair_candidate_edge = candidate_edges[candidate_edge_id]
            for side in ("from", "to"):
                teacher_endpoint = pair_teacher_edge.attrib.get(side, "")
                candidate_endpoint = pair_candidate_edge.attrib.get(side, "")
                if (
                    teacher_endpoint
                    and teacher_endpoint not in teacher_owner_ids
                    and candidate_endpoint
                    and candidate_endpoint not in target_candidate_ids
                ):
                    resolved_junction_map[teacher_endpoint] = candidate_endpoint

    teacher_link_indices = sorted(
        {
            str(connection.attrib.get("linkIndex", ""))
            for connection in teacher_root.findall("connection")
            if connection.attrib.get("tl") == teacher_controller_id and connection.attrib.get("linkIndex") is not None
        },
        key=lambda value: int(value) if value.isdigit() else value,
    )
    generated_boundary_edge_ids = sorted(
        teacher_edge_id
        for teacher_edge_id, source in edge_mapping_sources.items()
        if source == "explicit_teacher_boundary_copy"
    )
    status = "pass" if not missing_owner_ids and not mapping_conflicts and set(resolved_edge_map) == set(boundary_edge_ids) else "blocked"
    return {
        "status": status,
        "claim_status": "diagnostic-demo",
        "shared_controller_replay_status": status,
        "teacher_controller_id": teacher_controller_id,
        "candidate_controller_id": candidate_controller_id,
        "owner_map": dict(sorted(inferred_owner_map.items())),
        "candidate_junction_ids": sorted(target_candidate_ids),
        "teacher_owner_ids": teacher_owner_ids,
        "teacher_boundary_edge_ids": boundary_edge_ids,
        "edge_map": dict(sorted(resolved_edge_map.items())),
        "edge_mapping_sources": dict(sorted(edge_mapping_sources.items())),
        "generated_boundary_edge_ids": generated_boundary_edge_ids,
        "junction_map": dict(sorted(resolved_junction_map.items())),
        "teacher_controller_link_indices": teacher_link_indices,
        "teacher_controller_connection_count": len(
            [
                connection
                for connection in teacher_root.findall("connection")
                if connection.attrib.get("tl") == teacher_controller_id and connection.attrib.get("linkIndex") is not None
            ]
        ),
        "mapping_conflicts": mapping_conflicts,
        "mapping_rejections": mapping_rejections,
        "base_plan": base_plan,
        "mapping_policy": "explicit_owner_closure_then_topology_checked_approach_pair_then_signed_family_owner_side_then_teacher_boundary_copy",
    }








def build_teacher_guided_junction_variant(
    *,
    raw_node_file: Path,
    raw_edge_file: Path,
    raw_connection_file: Path,
    teacher_net_file: Path,
    candidate_net_file: Path,
    junction_id: str,
    output_dir: Path,
    edge_map: dict[str, str],
    prefix: str = "teacher_guided_junction",
    teacher_junction_id: str | None = None,
    raw_type_file: Path | None = None,
    raw_tllogic_file: Path | None = None,
    crossing_edge_overrides: dict[str, str | list[str]] | None = None,
    approach_endpoint_rebuild_plan: object | None = None,
    source_conflict_core_node_ids: list[str] | None = None,
    replay_target_internal_subgraph: bool = False,
    preserve_teacher_lane_shapes: bool = True,
    emit_teacher_crossings: bool = True,
    prune_unmapped_boundary_edges: bool = False,
    netconvert_binary: str = "netconvert",
    sumo_binary: str = "sumo",
    timeout_seconds: float = 240.0,
    command_runner: Any = run_command,
) -> dict[str, object]:
    teacher_junction_id = teacher_junction_id or junction_id
    missing = [
        str(path)
        for path in (raw_node_file, raw_edge_file, raw_connection_file, teacher_net_file, candidate_net_file)
        if not path.exists()
    ]
    if raw_type_file is not None and not raw_type_file.exists():
        missing.append(str(raw_type_file))
    if raw_tllogic_file is not None and not raw_tllogic_file.exists():
        missing.append(str(raw_tllogic_file))
    if missing:
        return _failure(f"missing input file(s): {', '.join(missing)}")

    # Downstream netconvert stages run from candidate-specific working
    # directories.  Keep every caller-supplied path absolute so a valid plain
    # XML input cannot become unreachable after the working directory changes.
    teacher_net_file = teacher_net_file.resolve()
    candidate_net_file = candidate_net_file.resolve()
    raw_node_file = raw_node_file.resolve()
    raw_edge_file = raw_edge_file.resolve()
    raw_connection_file = raw_connection_file.resolve()
    raw_type_file = raw_type_file.resolve() if raw_type_file is not None else None
    raw_tllogic_file = raw_tllogic_file.resolve() if raw_tllogic_file is not None else None
    output_dir = output_dir.resolve()

    output_dir.mkdir(parents=True, exist_ok=True)
    teacher_model = extract_teacher_junction_model(teacher_net_file, teacher_junction_id)
    candidate_model = extract_teacher_junction_model(candidate_net_file, junction_id)
    inferred_joined_source_node_ids = _joined_source_node_ids(raw_node_file, junction_id)
    joined_source_node_ids = (
        {str(node_id) for node_id in source_conflict_core_node_ids if str(node_id)}
        if source_conflict_core_node_ids is not None
        else inferred_joined_source_node_ids
    )
    source_conflict_core_source = (
        "declared_estimator_evidence"
        if source_conflict_core_node_ids is not None
        else "plain_join_definition"
    )

    lane_shape_delta = _model_shape_delta(teacher_model, candidate_model)
    patched_node_file = _stage_file(output_dir, prefix, "nodes.nod.xml")
    patched_edge_file = _stage_file(output_dir, prefix, "lanes.edg.xml")
    patched_type_file = _stage_file(output_dir, prefix, "types.typ.xml")
    connection_file = _stage_file(output_dir, prefix, "connections.con.xml")
    sidewalks_net_file = _stage_file(output_dir, prefix, "sidewalks.net.xml")
    pedring_net_file = _stage_file(output_dir, prefix, "pedring.net.xml")
    vehicle_attrs_net_file = _stage_file(output_dir, prefix, "vehicle_attrs.net.xml")
    target_internal_replay_file = _stage_file(output_dir, prefix, "target_internal_replay.net.xml")
    target_internal_normalized_net_file = _stage_file(output_dir, prefix, "target_internal_normalized.net.xml")
    target_internal_normalized_unrestored_net_file = _stage_file(
        output_dir, prefix, "target_internal_normalized_unrestored.net.xml"
    )
    target_internal_pedring_net_file = _stage_file(output_dir, prefix, "target_internal_pedring.net.xml")
    target_internal_vehicle_attrs_net_file = _stage_file(output_dir, prefix, "target_internal_vehicle_attrs.net.xml")
    final_net_file = _stage_file(output_dir, prefix, "teacher_guided.net.xml")
    teacher_guided_normalized_net_file = _stage_file(output_dir, "tg", "norm.net.xml")
    fallback_net_file = _stage_file(output_dir, prefix, "teacher_guided_fallback.net.xml")
    report_file = _stage_file(output_dir, prefix, "teacher_guided_report.json")

    lane_patch_report = write_teacher_lane_patch_edges(
        raw_edge_file=raw_edge_file,
        teacher_edge_file=teacher_net_file,
        output_file=patched_edge_file,
        edge_map=edge_map,
        junction_id=junction_id,
        teacher_junction_id=teacher_junction_id,
        boundary_node_ids=joined_source_node_ids,
        prune_unmapped_boundary_edges=prune_unmapped_boundary_edges,
        approach_endpoint_rebuild_plan=approach_endpoint_rebuild_plan,
        lane_shape_delta=lane_shape_delta,
        preserve_lane_shapes=preserve_teacher_lane_shapes,
    )
    internal_restore_exclude_junction_ids = {
        junction_id,
        *_endpoint_rewrite_old_endpoint_ids(lane_patch_report),
    }
    node_patch_report = write_teacher_endpoint_patch_nodes(
        raw_node_file=raw_node_file,
        teacher_net_file=teacher_net_file,
        edge_file=patched_edge_file,
        output_file=patched_node_file,
        lane_shape_delta=lane_shape_delta,
    )
    type_patch_report = write_missing_edge_type_patch(
        raw_type_file=raw_type_file,
        edge_file=patched_edge_file,
        output_file=patched_type_file,
    )
    if type_patch_report.get("status") != "pass":
        return _write_teacher_guided_report(
            report_file,
            {
                "status": "fail",
                "claim_status": "construction-invalid",
                "junction_id": junction_id,
                "teacher_net_file": str(teacher_net_file),
                "candidate_net_file": str(candidate_net_file),
                "node_patch": node_patch_report,
                "lane_patch": lane_patch_report,
                "type_patch": type_patch_report,
            },
        )
    connection_report = write_teacher_connection_plan(
        raw_connection_file=raw_connection_file,
        output_file=connection_file,
        junction_id=junction_id,
        teacher_model=teacher_model,
        candidate_model=candidate_model,
        edge_map=edge_map,
        crossing_edge_overrides=crossing_edge_overrides,
        candidate_edge_file=patched_edge_file,
        crossing_node_ids=joined_source_node_ids,
        emit_crossings=emit_teacher_crossings and not replay_target_internal_subgraph,
        teacher_internal_scope_id=teacher_junction_id if replay_target_internal_subgraph else None,
    )

    netconvert_command = [
        netconvert_binary,
        "--node-files",
        str(patched_node_file),
        "--edge-files",
        _command_path(patched_edge_file, output_dir),
        "--connection-files",
        _command_path(connection_file, output_dir),
        "--output-file",
        _command_path(sidewalks_net_file, output_dir),
        "--walkingareas",
        "true",
        "--tls.ignore-internal-junction-jam",
    ]
    type_file = Path(str(type_patch_report.get("type_file", ""))) if type_patch_report.get("type_file") else None
    if type_file is not None:
        netconvert_command[5:5] = ["--type-files", _command_path(type_file, output_dir)]
    netconvert_result = command_runner(netconvert_command, cwd=output_dir, timeout_seconds=timeout_seconds)
    netconvert_report = _command_report(netconvert_result)
    if netconvert_report.get("status") != "pass":
        return _write_teacher_guided_report(
            report_file,
            {
                "status": "fail",
                "claim_status": "construction-invalid",
                "junction_id": junction_id,
                "teacher_net_file": str(teacher_net_file),
                "candidate_net_file": str(candidate_net_file),
                "netconvert": netconvert_report,
                "node_patch": node_patch_report,
                "lane_patch": lane_patch_report,
                "type_patch": type_patch_report,
                "connection_plan": connection_report,
            },
        )

    non_target_internal_restore_report = restore_off_scope_netconvert_artifacts(
        source_file=candidate_net_file,
        target_file=sidewalks_net_file,
        mutable_junction_ids=internal_restore_exclude_junction_ids,
        mutable_edge_ids=set(edge_map.values()),
        expand_mutable_edge_endpoints=False,
    )
    if non_target_internal_restore_report.get("status") != "pass":
        return _write_teacher_guided_report(
            report_file,
            {
                "status": "fail",
                "claim_status": "construction-invalid",
                "junction_id": junction_id,
                "teacher_net_file": str(teacher_net_file),
                "candidate_net_file": str(candidate_net_file),
                "netconvert": netconvert_report,
                "node_patch": node_patch_report,
                "lane_patch": lane_patch_report,
                "type_patch": type_patch_report,
                "connection_plan": connection_report,
                "non_target_internal_restore": non_target_internal_restore_report,
            },
        )

    pedestrian_ring_report = write_teacher_pedestrian_ring_net(
        candidate_net_file=sidewalks_net_file,
        output_file=pedring_net_file,
        junction_id=junction_id,
        teacher_model=teacher_model,
        edge_map=edge_map,
        teacher_junction_id=teacher_junction_id,
        crossing_edge_overrides=crossing_edge_overrides,
    )
    vehicle_attrs_report = write_teacher_vehicle_connection_attrs_net(
        candidate_net_file=pedring_net_file,
        output_file=vehicle_attrs_net_file,
        junction_id=junction_id,
        teacher_model=teacher_model,
        edge_map=edge_map,
    )
    target_internal_replay_report = None
    target_internal_replay_fallback = False
    target_internal_replay_fallback_tl_logic_report = None
    target_internal_replay_fallback_sumo_report = None
    target_internal_normalize_report = None
    teacher_guided_normalize_report = None
    target_internal_pedestrian_ring_report = None
    target_internal_vehicle_attrs_report = None
    tl_logic_input_file = vehicle_attrs_net_file
    target_internal_replay_input_file = vehicle_attrs_net_file
    if replay_target_internal_subgraph:
        target_internal_replay_input_file = _target_internal_replay_input_file(
            vehicle_attrs_net_file=vehicle_attrs_net_file,
            candidate_net_file=candidate_net_file,
            junction_id=junction_id,
        )
        target_internal_replay_report = write_teacher_target_internal_replay_net(
            candidate_net_file=target_internal_replay_input_file,
            teacher_net_file=teacher_net_file,
            output_file=target_internal_replay_file,
            junction_id=junction_id,
            edge_map=edge_map,
            teacher_junction_id=teacher_junction_id,
            # A joined OSM cell may keep real remote endpoints that do not
            # coincide with the teacher network.  In that case teacher lane
            # geometry is only a semantic template: retain the candidate
            # boundary shapes so every lane still reaches its real endpoint.
            # Single-junction replay keeps teacher geometry for parity.
            geometry_anchor_edge_file=(
                candidate_net_file if len(joined_source_node_ids) > 1 else None
            ),
            blend_geometry_anchor_at_target=len(joined_source_node_ids) > 1,
            copy_unmapped_boundary_edges=False,
            preserve_mapped_boundary_endpoints=True,
        )
        if target_internal_replay_report.get("status") != "pass":
            return _write_teacher_guided_report(
                report_file,
                {
                    "status": "fail",
                    "claim_status": "construction-invalid",
                    "junction_id": junction_id,
                    "teacher_net_file": str(teacher_net_file),
                    "candidate_net_file": str(candidate_net_file),
                    "netconvert": netconvert_report,
                    "node_patch": node_patch_report,
                    "lane_patch": lane_patch_report,
                    "type_patch": type_patch_report,
                    "connection_plan": connection_report,
                    "pedestrian_ring": pedestrian_ring_report,
                    "vehicle_connection_attrs": vehicle_attrs_report,
                    "target_internal_replay_input_file": str(target_internal_replay_input_file),
                    "target_internal_replay": target_internal_replay_report,
                    "target_internal_replay_fallback": target_internal_replay_fallback,
                },
            )
        tl_logic_input_file = target_internal_replay_file

    tl_logic_report = write_teacher_tllogic_net(
        candidate_net_file=tl_logic_input_file,
        output_file=final_net_file,
        junction_id=junction_id,
        teacher_model=teacher_model,
    )
    if tl_logic_report.get("status") != "pass":
        return _write_teacher_guided_report(
            report_file,
            {
                "status": "fail",
                "claim_status": "construction-invalid",
                "junction_id": junction_id,
                "teacher_net_file": str(teacher_net_file),
                "candidate_net_file": str(candidate_net_file),
                "netconvert": netconvert_report,
                "node_patch": node_patch_report,
                "lane_patch": lane_patch_report,
                "type_patch": type_patch_report,
                "connection_plan": connection_report,
                "pedestrian_ring": pedestrian_ring_report,
                "vehicle_connection_attrs": vehicle_attrs_report,
                "target_internal_replay": target_internal_replay_report,
                "target_internal_replay_fallback": target_internal_replay_fallback,
                "target_internal_normalize": target_internal_normalize_report,
                "target_internal_pedestrian_ring": target_internal_pedestrian_ring_report,
                "target_internal_vehicle_connection_attrs": target_internal_vehicle_attrs_report,
                "tl_logic": tl_logic_report,
            },
        )

    sumo_command = [
        sumo_binary,
        "-n",
        _command_path(final_net_file, output_dir),
        "--no-step-log",
        "true",
        "--duration-log.disable",
        "true",
        "--begin",
        "0",
        "--end",
        "1",
    ]
    sumo_report = _command_report(command_runner(sumo_command, cwd=output_dir, timeout_seconds=timeout_seconds))
    if (
        sumo_report.get("status") != "pass"
        and replay_target_internal_subgraph
        and isinstance(target_internal_replay_report, dict)
        and target_internal_replay_report.get("status") == "pass"
    ):
        target_internal_normalize_command = [
            netconvert_binary,
            "--sumo-net-file",
            _command_path(target_internal_replay_file, output_dir),
            "--output-file",
            _command_path(target_internal_normalized_net_file, output_dir),
        ]
        target_internal_normalize_report = _command_report(
            command_runner(target_internal_normalize_command, cwd=output_dir, timeout_seconds=timeout_seconds)
        )
        if target_internal_normalize_report.get("status") == "pass":
            shutil.copyfile(target_internal_normalized_net_file, target_internal_normalized_unrestored_net_file)
            target_internal_normalize_report["unrestored_net_file"] = str(target_internal_normalized_unrestored_net_file)
            target_internal_normalize_report["non_target_internal_restore"] = restore_off_scope_netconvert_artifacts(
                source_file=target_internal_replay_file,
                target_file=target_internal_normalized_net_file,
                mutable_junction_ids=internal_restore_exclude_junction_ids,
                mutable_edge_ids=set(edge_map.values()),
                expand_mutable_edge_endpoints=False,
            )
        if (
            target_internal_normalize_report.get("status") == "pass"
            and target_internal_normalize_report["non_target_internal_restore"].get("status") == "pass"
        ):
            target_internal_normalize_report["false_traffic_light_type_restore"] = (
                _restore_false_traffic_light_junction_types(
                    source_file=target_internal_replay_file,
                    target_file=target_internal_normalized_net_file,
                    fallback_node_file=raw_node_file,
                    exclude_junction_ids=internal_restore_exclude_junction_ids,
                )
            )
            target_internal_normalize_report["geometry_restore"] = _restore_replayed_geometry_attrs(
                source_file=target_internal_replay_file,
                target_file=target_internal_normalized_net_file,
                junction_id=junction_id,
            )
            normalized_tl_logic_report = write_teacher_tllogic_net(
                candidate_net_file=target_internal_normalized_net_file,
                output_file=final_net_file,
                junction_id=junction_id,
                teacher_model=teacher_model,
            )
            target_internal_normalize_report["tl_logic"] = normalized_tl_logic_report
            if normalized_tl_logic_report.get("status") == "pass":
                normalized_sumo_report = _command_report(
                    command_runner(sumo_command, cwd=output_dir, timeout_seconds=timeout_seconds)
                )
                target_internal_normalize_report["sumo_load"] = normalized_sumo_report
                if normalized_sumo_report.get("status") == "pass":
                    tl_logic_report = normalized_tl_logic_report
                    sumo_report = normalized_sumo_report
                elif _non_target_internal_restore_changed(
                    target_internal_normalize_report["non_target_internal_restore"]
                ):
                    target_internal_normalize_report["unrestored_false_traffic_light_type_restore"] = (
                        _restore_false_traffic_light_junction_types(
                            source_file=target_internal_replay_file,
                            target_file=target_internal_normalized_unrestored_net_file,
                            fallback_node_file=raw_node_file,
                            exclude_junction_ids=internal_restore_exclude_junction_ids,
                        )
                    )
                    target_internal_normalize_report["unrestored_geometry_restore"] = _restore_replayed_geometry_attrs(
                        source_file=target_internal_replay_file,
                        target_file=target_internal_normalized_unrestored_net_file,
                        junction_id=junction_id,
                    )
                    unrestored_tl_logic_report = write_teacher_tllogic_net(
                        candidate_net_file=target_internal_normalized_unrestored_net_file,
                        output_file=final_net_file,
                        junction_id=junction_id,
                        teacher_model=teacher_model,
                    )
                    target_internal_normalize_report["unrestored_tl_logic"] = unrestored_tl_logic_report
                    if unrestored_tl_logic_report.get("status") == "pass":
                        unrestored_sumo_report = _command_report(
                            command_runner(sumo_command, cwd=output_dir, timeout_seconds=timeout_seconds)
                        )
                        target_internal_normalize_report["unrestored_sumo_load"] = unrestored_sumo_report
                        if unrestored_sumo_report.get("status") == "pass":
                            tl_logic_report = unrestored_tl_logic_report
                            sumo_report = unrestored_sumo_report
    if (
        sumo_report.get("status") != "pass"
        and replay_target_internal_subgraph
        and isinstance(target_internal_replay_report, dict)
        and target_internal_replay_report.get("status") == "pass"
    ):
        teacher_guided_normalize_command = [
            netconvert_binary,
            "--sumo-net-file",
            _command_path(final_net_file, output_dir),
            "--output-file",
            _command_path(teacher_guided_normalized_net_file, output_dir),
        ]
        teacher_guided_normalize_report = _command_report(
            command_runner(teacher_guided_normalize_command, cwd=output_dir, timeout_seconds=timeout_seconds)
        )
        if teacher_guided_normalize_report.get("status") == "pass":
            teacher_guided_normalize_report["non_target_internal_restore"] = restore_off_scope_netconvert_artifacts(
                source_file=final_net_file,
                target_file=teacher_guided_normalized_net_file,
                mutable_junction_ids=internal_restore_exclude_junction_ids,
                mutable_edge_ids=set(edge_map.values()),
                expand_mutable_edge_endpoints=False,
            )
        if (
            teacher_guided_normalize_report.get("status") == "pass"
            and teacher_guided_normalize_report["non_target_internal_restore"].get("status") == "pass"
        ):
            teacher_guided_normalize_report["false_traffic_light_type_restore"] = (
                _restore_false_traffic_light_junction_types(
                    source_file=final_net_file,
                    target_file=teacher_guided_normalized_net_file,
                    fallback_node_file=raw_node_file,
                    exclude_junction_ids=internal_restore_exclude_junction_ids,
                )
            )
            teacher_guided_normalize_report["geometry_restore"] = _restore_replayed_geometry_attrs(
                source_file=final_net_file,
                target_file=teacher_guided_normalized_net_file,
                junction_id=junction_id,
            )
            normalized_final_sumo_command = [
                sumo_binary,
                "-n",
                _command_path(teacher_guided_normalized_net_file, output_dir),
                "--no-step-log",
                "true",
                "--duration-log.disable",
                "true",
                "--begin",
                "0",
                "--end",
                "1",
            ]
            normalized_final_sumo_report = _command_report(
                command_runner(normalized_final_sumo_command, cwd=output_dir, timeout_seconds=timeout_seconds)
            )
            teacher_guided_normalize_report["sumo_load"] = normalized_final_sumo_report
            if normalized_final_sumo_report.get("status") == "pass":
                final_net_file = teacher_guided_normalized_net_file
                sumo_report = normalized_final_sumo_report
    if (
        sumo_report.get("status") != "pass"
        and replay_target_internal_subgraph
        and isinstance(target_internal_replay_report, dict)
        and target_internal_replay_report.get("status") == "pass"
    ):
        target_internal_replay_fallback_tl_logic_report = write_teacher_tllogic_net(
            candidate_net_file=vehicle_attrs_net_file,
            output_file=fallback_net_file,
            junction_id=junction_id,
            teacher_model=teacher_model,
        )
        if target_internal_replay_fallback_tl_logic_report.get("status") == "pass":
            fallback_sumo_command = [
                sumo_binary,
                "-n",
                _command_path(fallback_net_file, output_dir),
                "--no-step-log",
                "true",
                "--duration-log.disable",
                "true",
                "--begin",
                "0",
                "--end",
                "1",
            ]
            target_internal_replay_fallback_sumo_report = _command_report(
                command_runner(fallback_sumo_command, cwd=output_dir, timeout_seconds=timeout_seconds)
            )
            if target_internal_replay_fallback_sumo_report.get("status") == "pass":
                target_internal_replay_fallback = True
                final_net_file = fallback_net_file
                tl_logic_report = target_internal_replay_fallback_tl_logic_report
                sumo_report = target_internal_replay_fallback_sumo_report
    final_model = extract_teacher_junction_model(final_net_file, junction_id)
    comparison_edge_map = edge_map
    if (
        replay_target_internal_subgraph
        and not target_internal_replay_fallback
        and isinstance(target_internal_replay_report, dict)
    ):
        comparison_edge_map = _valid_edge_map(target_internal_replay_report.get("effective_edge_map", {})) or edge_map
    parity = _compare_teacher_models(
        teacher_model,
        final_model,
        edge_map=comparison_edge_map,
        teacher_junction_id=teacher_junction_id,
        candidate_junction_id=junction_id,
    )
    target_internal_replay_gate_report = None if target_internal_replay_fallback else target_internal_replay_report
    approach_endpoint_rebuild_plan = _approach_endpoint_rebuild_plan(
        teacher_model,
        final_model,
        edge_map=comparison_edge_map,
        teacher_junction_id=teacher_junction_id,
        candidate_junction_id=junction_id,
        candidate_junction_ids=_net_junction_ids(final_net_file),
    )
    semantic_gate = _teacher_guided_semantics_gate(
        parity,
        pedestrian_ring=pedestrian_ring_report,
        vehicle_connection_attrs=vehicle_attrs_report,
        target_internal_replay=target_internal_replay_gate_report,
        target_internal_pedestrian_ring=target_internal_pedestrian_ring_report,
        target_internal_vehicle_connection_attrs=target_internal_vehicle_attrs_report,
    )
    teacher_tls_id = _model_tls_id(teacher_model, fallback=teacher_junction_id)
    candidate_tls_id = _model_tls_id(final_model, fallback=junction_id)
    tls_movement_parity = compare_tls_movement_signatures(
        teacher_net_file,
        final_net_file,
        teacher_tls_id,
        candidate_tls_id,
        teacher_edge_map=comparison_edge_map,
        teacher_internal_scope_id=teacher_junction_id if replay_target_internal_subgraph else None,
        candidate_internal_scope_id=junction_id if replay_target_internal_subgraph else None,
    )
    pedestrian_crossing_parity = compare_pedestrian_crossing_signatures(
        teacher_net_file,
        final_net_file,
        teacher_junction_id,
        junction_id,
        teacher_edge_map=comparison_edge_map,
    )
    approach_authority_policy = _hybrid_osm_approach_authority_policy(
        semantic_gate,
        replay_target_internal_subgraph=replay_target_internal_subgraph,
        preserve_teacher_lane_shapes=preserve_teacher_lane_shapes,
        edge_map=comparison_edge_map,
        lane_patch=lane_patch_report,
        target_internal_replay=target_internal_replay_gate_report,
        tls_movement_parity=tls_movement_parity,
        pedestrian_crossing_parity=pedestrian_crossing_parity,
    )
    effective_semantic_gate = approach_authority_policy["effective_semantic_gate"]
    semantic_layer_gates = _semantic_layer_gates(
        effective_semantic_gate,
        tls_movement_parity,
        pedestrian_crossing_parity,
    )
    parity_gate_status = (
        "pass"
        if effective_semantic_gate["status"] == "pass"
        and tls_movement_parity["status"] == "pass"
        and pedestrian_crossing_parity["status"] == "pass"
        else "fail"
    )
    status = "pass" if sumo_report.get("status") == "pass" else "fail"
    return _write_teacher_guided_report(
        report_file,
        {
            "status": status,
            "claim_status": "diagnostic-demo" if status == "pass" else "construction-invalid",
            "parity_gate_status": parity_gate_status,
            "junction_id": junction_id,
            "source_conflict_core_node_ids": sorted(joined_source_node_ids),
            "source_conflict_core_source": source_conflict_core_source,
            "teacher_net_file": str(teacher_net_file),
            "candidate_net_file": str(candidate_net_file),
            "final_net_file": str(final_net_file),
            "patched_node_file": str(patched_node_file),
            "patched_edge_file": str(patched_edge_file),
            "connection_file": str(connection_file),
            "sidewalks_net_file": str(sidewalks_net_file),
            "pedring_net_file": str(pedring_net_file),
            "vehicle_attrs_net_file": str(vehicle_attrs_net_file),
            "target_internal_replay_input_file": str(target_internal_replay_input_file)
            if replay_target_internal_subgraph
            else "",
            "target_internal_replay_file": str(target_internal_replay_file) if replay_target_internal_subgraph else "",
            "target_internal_replay_fallback": target_internal_replay_fallback,
            "target_internal_replay_fallback_net_file": str(fallback_net_file) if target_internal_replay_fallback else "",
            "target_internal_normalized_net_file": str(target_internal_normalized_net_file)
            if target_internal_normalize_report
            else "",
            "teacher_guided_normalized_net_file": str(teacher_guided_normalized_net_file)
            if teacher_guided_normalize_report
            else "",
            "target_internal_pedring_net_file": str(target_internal_pedring_net_file)
            if target_internal_pedestrian_ring_report
            else "",
            "target_internal_vehicle_attrs_net_file": str(target_internal_vehicle_attrs_net_file)
            if target_internal_vehicle_attrs_report
            else "",
            "report_file": str(report_file),
            "node_patch": node_patch_report,
            "lane_patch": lane_patch_report,
            "type_patch": type_patch_report,
            "connection_plan": connection_report,
            "netconvert": netconvert_report,
            "non_target_internal_restore": non_target_internal_restore_report,
            "pedestrian_ring": pedestrian_ring_report,
            "vehicle_connection_attrs": vehicle_attrs_report,
            "target_internal_replay": target_internal_replay_report,
            "target_internal_replay_fallback_tl_logic": target_internal_replay_fallback_tl_logic_report,
            "target_internal_replay_fallback_sumo": target_internal_replay_fallback_sumo_report,
            "target_internal_normalize": target_internal_normalize_report,
            "teacher_guided_normalize": teacher_guided_normalize_report,
            "target_internal_pedestrian_ring": target_internal_pedestrian_ring_report,
            "target_internal_vehicle_connection_attrs": target_internal_vehicle_attrs_report,
            "tl_logic": tl_logic_report,
            "sumo_load": sumo_report,
            "parity": parity,
            "approach_endpoint_rebuild_plan": approach_endpoint_rebuild_plan,
            "semantic_replay_gate": semantic_gate,
            "semantic_replay_effective_gate": effective_semantic_gate,
            "approach_authority_policy": approach_authority_policy,
            "tls_movement_parity": tls_movement_parity,
            "pedestrian_crossing_parity": pedestrian_crossing_parity,
            "semantic_layer_gates": semantic_layer_gates,
            "review_policy": "diagnostic teacher-guided variant; inspect in NetEdit connection mode before adoption",
        },
    )




def _expanded_scope_skip_entry(
    *,
    index: int,
    junction_id: str,
    candidate_status: str,
    scope_report: dict[str, Any],
    replay_edge_map: dict[str, str],
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "index": index,
        "junction_id": junction_id,
        "candidate_status": candidate_status,
    }
    missing_joined = _string_list(scope_report.get("blocking_missing_joined_scope_junction_ids"))
    missing_nodes = _string_list(scope_report.get("blocking_missing_node_ids"))
    missing_blocked = _string_list(scope_report.get("blocking_missing_blocked_edge_ids"))
    if missing_joined:
        entry["skip_reason"] = "scope_insufficient_joined_junction_missing"
        entry["blocking_missing_joined_scope_junction_ids"] = missing_joined
    elif missing_nodes:
        entry["skip_reason"] = "scope_insufficient_missing_nodes"
        entry["blocking_missing_node_ids"] = missing_nodes
    elif missing_blocked:
        entry["skip_reason"] = "missing_blocked_edges_uncopyable"
        entry["blocking_missing_blocked_edge_ids"] = missing_blocked
    elif not replay_edge_map:
        entry["skip_reason"] = "edge_map_derivation_gap"
    else:
        entry["skip_reason"] = "expanded_scope_review"
    return entry


def _accepted_target_internal_replay_entry(
    report: dict[str, Any],
    *,
    junction_id: str,
    teacher_junction_id: str,
) -> dict[str, object] | None:
    replay = report.get("target_internal_replay", {})
    if not isinstance(replay, dict) or replay.get("status") != "pass":
        return None
    edge_map = _valid_edge_map(replay.get("effective_edge_map", {}))
    if not edge_map:
        return None
    return {
        "junction_id": junction_id,
        "teacher_junction_id": teacher_junction_id,
        "edge_map": edge_map,
        "prefer_clean_replay_base": _report_used_unrestored_normalized_replay(report),
    }






def _candidate_requests_target_internal_replay(candidate: dict[str, Any]) -> bool:
    learned_rule = str(candidate.get("learned_rule", ""))
    if learned_rule in {
        "tum_like_topology_fragmented_tls_candidate",
        "tum_like_topology_fragmented_cluster_candidate",
    }:
        return True
    if learned_rule == "tum_like_join_candidate":
        teacher_pattern_key = str(candidate.get("teacher_pattern_key", ""))
        return "control=traffic_light" in teacher_pattern_key or any(
            _teacher_pattern_metric_is_positive(teacher_pattern_key, metric)
            for metric in ("tls", "ped", "internal", "requests")
        )
    if learned_rule == "tum_like_same_id_pattern_candidate":
        mismatch_fields = {str(item) for item in candidate.get("junction_pattern_mismatch_fields", []) or []}
        return bool(mismatch_fields & {"internal_function_counts", "request_signatures", "junction_signature"})
    if learned_rule == "tum_like_same_id_tls_candidate":
        teacher_pattern_key = str(candidate.get("teacher_pattern_key", ""))
        return any(
            _teacher_pattern_metric_is_positive(teacher_pattern_key, metric)
            for metric in ("internal", "requests")
        )
    if learned_rule == "tum_like_turnaround_only_lane_candidate":
        teacher_pattern_key = str(candidate.get("teacher_pattern_key", ""))
        return any(
            _teacher_pattern_metric_is_positive(teacher_pattern_key, metric)
            for metric in ("internal", "requests")
        )
    return False




def _load_teacher_join_groups_by_cluster(
    definition_value: object,
    *,
    queue_base_dir: Path | None = None,
) -> dict[str, list[str]]:
    """Load authoritative source members for teacher-side joined junctions.

    A SUMO joined junction id is only a generated label; its numeric suffixes
    are not guaranteed to be the complete source-node list.  The join
    definition emitted by the reference aggregation stage is therefore the
    source of truth whenever it is available.
    """
    if not definition_value:
        return {}
    definition_path = Path(str(definition_value))
    if not definition_path.is_absolute() and queue_base_dir is not None:
        definition_path = queue_base_dir / definition_path
    try:
        payload = json.loads(definition_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    groups: dict[str, list[str]] = {}
    for record in payload.get("records", []) or []:
        if not isinstance(record, dict):
            continue
        cluster_id = str(record.get("candidate_id", "")).strip()
        decision = str(record.get("decision", record.get("action", ""))).strip().lower()
        node_ids = sorted({str(node_id) for node_id in record.get("node_ids", []) or [] if str(node_id)})
        encoded_member_ids = set(_sumo_cluster_member_ids(cluster_id))
        # The aggregation report is a candidate repair suggestion, not an
        # authoritative decomposition of an existing teacher cluster.  Accept
        # it only when its source members agree with the generated cluster
        # label; otherwise the label-based fallback remains authoritative.
        if (
            cluster_id.startswith("cluster_")
            and decision == "join"
            and len(node_ids) >= 2
            and encoded_member_ids
            and encoded_member_ids <= set(node_ids)
        ):
            groups[cluster_id] = node_ids
    return groups




def run_teacher_guided_repair_queue(
    *,
    queue_report: dict[str, Any],
    raw_node_file: Path,
    raw_edge_file: Path,
    raw_connection_file: Path,
    output_dir: Path,
    prefix: str = "teacher_guided_repair",
    queue_base_dir: Path | None = None,
    raw_type_file: Path | None = None,
    raw_tllogic_file: Path | None = None,
    teacher_join_definition_file: Path | None = None,
    teacher_join_groups_by_cluster: dict[str, list[str]] | None = None,
    crossing_edge_overrides_by_junction: dict[str, dict[str, str | list[str]]] | None = None,
    replay_target_internal_subgraph: bool = False,
    max_ready_candidates: int | None = None,
    netconvert_binary: str = "netconvert",
    sumo_binary: str = "sumo",
    timeout_seconds: float = 240.0,
    command_runner: Any = run_command,
    variant_builder: Any = build_teacher_guided_junction_variant,
    connection_mode_regression_builder: Any | None = None,
    expand_fragmented_tls_join_scope: bool = False,
    sequential_accept_passed_variants: bool = False,
    plain_exporter: Any | None = None,
    final_internal_replay_writer: Any = write_teacher_target_internal_replay_net,
) -> dict[str, object]:
    teacher_net_value = queue_report.get("teacher_net_file")
    candidate_net_value = queue_report.get("candidate_net_file")
    missing_fields = [
        field
        for field, value in (
            ("teacher_net_file", teacher_net_value),
            ("candidate_net_file", candidate_net_value),
        )
        if not value
    ]
    if missing_fields:
        return _failure(f"queue report missing field(s): {', '.join(missing_fields)}")

    teacher_net_file = _queue_path(teacher_net_value, queue_base_dir)
    candidate_net_file = _queue_path(candidate_net_value, queue_base_dir)
    missing = [
        str(path)
        for path in (raw_node_file, raw_edge_file, raw_connection_file, teacher_net_file, candidate_net_file)
        if not path.exists()
    ]
    if raw_type_file is not None and not raw_type_file.exists():
        missing.append(str(raw_type_file))
    if raw_tllogic_file is not None and not raw_tllogic_file.exists():
        missing.append(str(raw_tllogic_file))
    if missing:
        return _failure(f"missing input file(s): {', '.join(missing)}")

    teacher_net_file = teacher_net_file.resolve()
    candidate_net_file = candidate_net_file.resolve()
    raw_node_file = raw_node_file.resolve()
    raw_edge_file = raw_edge_file.resolve()
    raw_connection_file = raw_connection_file.resolve()
    raw_type_file = raw_type_file.resolve() if raw_type_file is not None else None
    raw_tllogic_file = raw_tllogic_file.resolve() if raw_tllogic_file is not None else None
    output_dir = output_dir.resolve()

    candidates = queue_report.get("repair_candidates", []) or []
    if not isinstance(candidates, list):
        return _failure("queue report repair_candidates must be a list")
    candidates = list(candidates)

    if teacher_join_groups_by_cluster is None:
        teacher_join_definition_value = teacher_join_definition_file or queue_report.get(
            "teacher_join_definition_file", ""
        )
        teacher_join_groups_by_cluster = _load_teacher_join_groups_by_cluster(
            teacher_join_definition_value,
            queue_base_dir=queue_base_dir,
        )
    else:
        teacher_join_groups_by_cluster = {
            str(cluster_id): sorted(
                {str(node_id) for node_id in node_ids if str(node_id)}
            )
            for cluster_id, node_ids in teacher_join_groups_by_cluster.items()
            if str(cluster_id) and isinstance(node_ids, (list, tuple, set))
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    crossing_edge_overrides_by_junction = crossing_edge_overrides_by_junction or {}
    variant_reports = []
    expanded_scope_reports = []
    expanded_scope_followup_candidates = []
    skipped_candidates = []
    sequential_plain_export_reports = []
    current_raw_node_file = raw_node_file
    current_raw_edge_file = raw_edge_file
    current_raw_connection_file = raw_connection_file
    current_raw_type_file = raw_type_file
    current_raw_tllogic_file = raw_tllogic_file
    current_candidate_net_file = candidate_net_file
    composite_applied_candidate_count = 0
    composite_net_file = ""
    applied_candidate_edge_ids: set[str] = set()
    applied_candidate_node_ids: set[str] = set()
    sequential_blocked_reason = ""
    attempted_ready_count = 0
    accepted_internal_replays: list[dict[str, object]] = []
    refresh_teacher_root: ET.Element | None = None
    refresh_candidate_root: ET.Element | None = None
    refresh_candidate_net_file: Path | None = None
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            skipped_candidates.append({"index": index, "candidate_status": "invalid_candidate"})
            continue
        if (
            sequential_accept_passed_variants
            and composite_applied_candidate_count > 0
            and current_candidate_net_file != candidate_net_file
            and current_candidate_net_file.exists()
        ):
            try:
                if refresh_teacher_root is None:
                    refresh_teacher_root = ET.parse(teacher_net_file).getroot()
                if refresh_candidate_root is None or refresh_candidate_net_file != current_candidate_net_file:
                    refresh_candidate_root = ET.parse(current_candidate_net_file).getroot()
                    refresh_candidate_net_file = current_candidate_net_file
                refresh_teacher_edges = {
                    edge.attrib["id"]: edge
                    for edge in refresh_teacher_root.findall("edge")
                    if edge.attrib.get("id")
                }
                refresh_candidate_edges = {
                    edge.attrib["id"]: edge
                    for edge in refresh_candidate_root.findall("edge")
                    if edge.attrib.get("id")
                }
                refreshed_candidate = _teacher_guided_repair_candidate(
                    case=candidate,
                    teacher_net_file=teacher_net_file,
                    candidate_net_file=current_candidate_net_file,
                    teacher_root=refresh_teacher_root,
                    candidate_root=refresh_candidate_root,
                    teacher_edges=refresh_teacher_edges,
                    candidate_edges_by_id=refresh_candidate_edges,
                    candidate_edge_ids=set(refresh_candidate_edges),
                )
                if refreshed_candidate.get("candidate_status") in {
                    "ready_for_teacher_guided_variant",
                    "needs_expanded_rebuild_scope",
                }:
                    original_expanded_scope = candidate.get("expanded_rebuild_scope", {})
                    original_scope_ids = {
                        str(item)
                        for item in (
                            original_expanded_scope.get("junction_ids", [])
                            if isinstance(original_expanded_scope, dict)
                            else []
                        )
                        if str(item)
                    }
                    original_cluster_scope_ids = {
                        item for item in original_scope_ids if item.startswith("cluster_")
                    }
                    refreshed_expanded_scope = refreshed_candidate.get("expanded_rebuild_scope", {})
                    # A sequential refresh can make the core junction look
                    # individually repairable after an earlier candidate was
                    # applied.  Preserve the teacher's explicit split-cluster
                    # context in that case; otherwise the next replay silently
                    # downgrades a context repair into a single-node repair and
                    # the final composite regresses to the split cluster.
                    if original_cluster_scope_ids:
                        merged_scope = dict(
                            refreshed_expanded_scope
                            if isinstance(refreshed_expanded_scope, dict)
                            else {}
                        )
                        merged_scope.update(
                            {
                                key: value
                                for key, value in original_expanded_scope.items()
                                if key in {
                                    "core_junction_id",
                                    "blocked_teacher_edge_ids",
                                    "missing_desired_endpoint_ids",
                                    "reason",
                                }
                            }
                        )
                        merged_scope["junction_ids"] = sorted(
                            original_scope_ids
                            | {
                                str(item)
                                for item in merged_scope.get("junction_ids", []) or []
                                if str(item)
                            }
                        )
                        original_join_ids = {
                            str(item)
                            for item in original_expanded_scope.get("join_junction_ids", []) or []
                            if str(item)
                        }
                        refreshed_join_ids = {
                            str(item)
                            for item in merged_scope.get("join_junction_ids", []) or []
                            if str(item)
                        }
                        merged_scope["join_junction_ids"] = sorted(original_join_ids | refreshed_join_ids)
                        merged_scope["status"] = "review"
                        merged_scope["recommended_action"] = "rebuild_plain_xml_scope"
                        merged_scope["sequential_cluster_context_preserved"] = True
                        merged_scope["sequential_cluster_context_ids"] = sorted(original_cluster_scope_ids)
                        refreshed_candidate = {
                            **refreshed_candidate,
                            "candidate_status": "needs_expanded_rebuild_scope",
                            "expanded_rebuild_scope": merged_scope,
                            "sequential_cluster_context_preserved": True,
                        }
                    candidate = {
                        **candidate,
                        **refreshed_candidate,
                        "sequential_refreshed_candidate": True,
                        "sequential_refresh_source_net_file": str(current_candidate_net_file),
                    }
                else:
                    candidate = {
                        **candidate,
                        "sequential_refresh_status": "skipped_unusable",
                        "sequential_refresh_candidate_status": str(refreshed_candidate.get("candidate_status", "")),
                    }
            except (ET.ParseError, OSError, KeyError, TypeError, ValueError) as exc:
                candidate = {
                    **candidate,
                    "sequential_refresh_status": "fail",
                    "sequential_refresh_error": f"{type(exc).__name__}: {exc}",
                }
        is_followup_candidate = bool(candidate.get("followup_reason"))
        if (
            expand_fragmented_tls_join_scope
            and candidate.get("candidate_status") == "needs_expanded_rebuild_scope"
        ):
            candidate = _expand_fragmented_tls_join_scope_candidate(
                candidate,
                current_raw_node_file,
            )
            tls_scope_expansion = candidate.get("tls_join_scope_expansion", {})
            if isinstance(tls_scope_expansion, dict) and tls_scope_expansion.get(
                "automatic_expansion_applied"
            ):
                candidate = _augment_candidate_edge_map_from_tls_approach_pairs(candidate)
        junction_id = str(candidate.get("junction_id") or candidate.get("reference_id") or "")
        teacher_junction_id = str(candidate.get("reference_id") or junction_id)
        edge_map = _valid_edge_map(candidate.get("edge_map", {}))
        candidate_replay_target_internal_subgraph = (
            replay_target_internal_subgraph or _candidate_requests_target_internal_replay(candidate)
        )
        candidate_node_ids = {str(item) for item in candidate.get("matched_candidate_node_ids", []) or [] if str(item)}
        if junction_id:
            candidate_node_ids.add(junction_id)
        candidate_edge_ids = {str(item) for item in edge_map.values() if str(item)}
        overlap_edge_ids = candidate_edge_ids & applied_candidate_edge_ids
        overlap_node_ids = candidate_node_ids & applied_candidate_node_ids
        blocking_overlap_edge_ids = _blocking_sequential_overlap_edge_ids(
            overlap_edge_ids,
            current_raw_edge_file,
            candidate_node_ids,
            applied_candidate_node_ids,
        )
        allowed_boundary_overlap_edge_ids = sorted(overlap_edge_ids - set(blocking_overlap_edge_ids))
        if allowed_boundary_overlap_edge_ids:
            candidate = {
                **candidate,
                "sequential_allowed_boundary_overlap_edge_ids": allowed_boundary_overlap_edge_ids,
            }
        if sequential_accept_passed_variants and sequential_blocked_reason:
            skipped_candidates.append(
                {
                    "index": index,
                    "junction_id": junction_id,
                    "candidate_status": "sequential_plain_export_failed",
                    "reason": sequential_blocked_reason,
                }
            )
            continue
        if (
            sequential_accept_passed_variants
            and is_followup_candidate
            and (blocking_overlap_edge_ids or overlap_node_ids)
        ):
            candidate = {
                **candidate,
                "sequential_followup_overlap_replay": True,
                "sequential_followup_overlap_edge_ids": blocking_overlap_edge_ids,
                "sequential_followup_overlap_node_ids": sorted(overlap_node_ids),
            }
        if sequential_accept_passed_variants and not is_followup_candidate and (blocking_overlap_edge_ids or overlap_node_ids):
            skipped_candidates.append(
                {
                    "index": index,
                    "junction_id": junction_id,
                    "candidate_status": "sequential_candidate_overlap",
                    "overlap_edge_ids": blocking_overlap_edge_ids,
                    "allowed_boundary_overlap_edge_ids": allowed_boundary_overlap_edge_ids,
                    "overlap_node_ids": sorted(overlap_node_ids),
                }
            )
            continue
        if candidate.get("candidate_status") == "needs_expanded_rebuild_scope" and junction_id:
            if (
                max_ready_candidates is not None
                and max_ready_candidates > 0
                and attempted_ready_count >= max_ready_candidates
                and not is_followup_candidate
            ):
                skipped_candidates.append(
                    {"index": index, "junction_id": junction_id, "candidate_status": "max_ready_candidates_reached"}
                )
                continue
            safe_junction_id = _queue_candidate_dir(index, junction_id)
            scope_report = _attach_candidate_template_context(
                write_expanded_scope_plain_inputs(
                    raw_node_file=current_raw_node_file,
                    raw_edge_file=current_raw_edge_file,
                    raw_connection_file=current_raw_connection_file,
                    output_dir=output_dir / safe_junction_id,
                    expanded_rebuild_scope=candidate.get("expanded_rebuild_scope", {}),
                    approach_endpoint_rebuild_plan=candidate.get("approach_endpoint_rebuild_plan", {}),
                    teacher_join_groups_by_cluster=teacher_join_groups_by_cluster,
                    netconvert_binary=netconvert_binary,
                    sumo_binary=sumo_binary,
                    timeout_seconds=timeout_seconds,
                    command_runner=command_runner,
                ),
                candidate,
            )
            expanded_scope_reports.append(scope_report)
            joined_scope_junction_id = str(scope_report.get("joined_scope_junction_id", ""))
            rewrite_joined_endpoints = bool(scope_report.get("auto_cluster_join_count", 0))
            joined_scope_junction_ids = [
                str(item)
                for item in scope_report.get("joined_scope_junction_ids", []) or []
                if str(item)
            ] or ([joined_scope_junction_id] if joined_scope_junction_id else [])
            replay_edge_map = edge_map
            if not replay_edge_map and joined_scope_junction_id:
                try:
                    teacher_model = extract_teacher_junction_model(teacher_net_file, teacher_junction_id)
                    replay_edge_map = _teacher_candidate_edge_map(
                        teacher_model,
                        extract_teacher_junction_model(Path(str(scope_report.get("net_file", ""))), joined_scope_junction_id),
                        teacher_junction_id=teacher_junction_id,
                        candidate_junction_id=joined_scope_junction_id,
                        drop_endpoint_mismatches=False,
                        max_bearing_delta=45.0,
                    )
                    if not replay_edge_map:
                        replay_edge_map = _edge_map_from_approach_endpoint_rebuild_plan(
                            teacher_model,
                            candidate.get("approach_endpoint_rebuild_plan", {}),
                            teacher_junction_id=teacher_junction_id,
                            candidate_junction_id=joined_scope_junction_id,
                            plan_junction_id=junction_id,
                        )
                    scope_report["derived_edge_map"] = replay_edge_map
                except (ET.ParseError, OSError, KeyError, TypeError, ValueError):
                    replay_edge_map = {}
            missing_node_ids = {str(item) for item in scope_report.get("missing_node_ids", []) or [] if str(item)}
            skipped_endpoint_missing_ids = {
                str(node_id)
                for item in scope_report.get("skipped_endpoint_rewrites", []) or []
                if isinstance(item, dict)
                for node_id in item.get("missing_endpoint_ids", []) or []
                if str(node_id)
            }
            use_full_network_replay = (
                not str(scope_report.get("join_nodes_patch_file", ""))
                and (not missing_node_ids or missing_node_ids <= skipped_endpoint_missing_ids)
                and not scope_report.get("blocking_missing_node_ids")
                and not scope_report.get("missing_blocked_edge_ids")
            )
            join_patch_file = Path(str(scope_report.get("join_nodes_patch_file", "")))
            if replay_edge_map:
                missing_blocked_edge_ids = [
                    str(edge_id) for edge_id in scope_report.get("missing_blocked_edge_ids", []) or [] if str(edge_id)
                ]
                resolved_missing_blocked_edge_ids = [
                    edge_id for edge_id in missing_blocked_edge_ids if edge_id in replay_edge_map
                ]
                unresolved_missing_blocked_edge_ids = [
                    edge_id for edge_id in missing_blocked_edge_ids if edge_id not in replay_edge_map
                ]
                copyable_missing_blocked_edge_ids: list[str] = []
                if unresolved_missing_blocked_edge_ids:
                    try:
                        teacher_root = ET.parse(teacher_net_file).getroot()
                        teacher_edges = {
                            edge.attrib["id"]: edge for edge in teacher_root.findall("edge") if edge.attrib.get("id")
                        }
                        teacher_boundary_edge_ids = set(
                            _teacher_boundary_edge_ids_touching_internal_subgraph(
                                teacher_root.findall("connection"),
                                teacher_edges,
                                teacher_junction_id,
                            )
                        )
                        teacher_boundary_edge_ids.update(
                            edge_id
                            for edge_id, edge in teacher_edges.items()
                            if teacher_junction_id in (edge.attrib.get("from"), edge.attrib.get("to"))
                            and not _edge_is_pedestrian_only(edge)
                        )
                        copyable_missing_blocked_edge_ids = [
                            edge_id
                            for edge_id in unresolved_missing_blocked_edge_ids
                            if edge_id in teacher_boundary_edge_ids
                        ]
                    except (ET.ParseError, OSError, KeyError, TypeError, ValueError):
                        copyable_missing_blocked_edge_ids = []
                blocking_missing_blocked_edge_ids = [
                    edge_id
                    for edge_id in unresolved_missing_blocked_edge_ids
                    if edge_id not in set(copyable_missing_blocked_edge_ids)
                ]
                scope_report["resolved_missing_blocked_edge_ids"] = resolved_missing_blocked_edge_ids
                scope_report["unresolved_missing_blocked_edge_ids"] = unresolved_missing_blocked_edge_ids
                scope_report["copyable_missing_blocked_edge_ids"] = copyable_missing_blocked_edge_ids
                scope_report["blocking_missing_blocked_edge_ids"] = blocking_missing_blocked_edge_ids
                if copyable_missing_blocked_edge_ids:
                    replay_edge_map = {
                        **replay_edge_map,
                        **{edge_id: edge_id for edge_id in copyable_missing_blocked_edge_ids},
                    }
                    scope_report["derived_edge_map"] = replay_edge_map
                if (
                    scope_report.get("status") == "review"
                    and missing_blocked_edge_ids
                    and not blocking_missing_blocked_edge_ids
                    and not scope_report.get("blocking_missing_node_ids")
                    and not scope_report.get("blocking_missing_joined_scope_junction_ids")
                ):
                    scope_report["status"] = "pass"
                    scope_report["missing_blocked_edge_resolution"] = (
                        "copyable_by_teacher_replay"
                        if copyable_missing_blocked_edge_ids
                        else "mapped_by_replay_edge_map"
                    )
            join_self_loop_edge_ids, join_blocking_self_loop_edge_ids = _joined_endpoint_self_loop_edge_ids(
                current_raw_edge_file,
                join_patch_file,
                joined_scope_junction_ids,
            )
            expanded_rebuild_scope = candidate.get("expanded_rebuild_scope", {})
            blocked_teacher_edge_ids = (
                expanded_rebuild_scope.get("blocked_teacher_edge_ids", [])
                if isinstance(expanded_rebuild_scope, dict)
                else []
            )
            protected_self_loop_edge_ids = {
                *{str(edge_id) for edge_id in replay_edge_map.values() if str(edge_id)},
                *{
                    str(edge_id)
                    for edge_id in blocked_teacher_edge_ids
                    if str(edge_id)
                },
            }
            if join_self_loop_edge_ids:
                scope_report["full_network_join_self_loop_edge_drop_candidates"] = join_self_loop_edge_ids
            if join_blocking_self_loop_edge_ids:
                scope_report["full_network_join_blocking_self_loop_edge_drop_candidates"] = (
                    join_blocking_self_loop_edge_ids
                )
            full_network_join_edge_file = current_raw_edge_file
            full_network_join_dropped_self_loop_edges: list[str] = []
            full_network_join_absorbed_self_loop_edge_ids: list[str] = []
            full_network_join_blocking_self_loop_edge_ids = list(join_blocking_self_loop_edge_ids)
            if join_patch_file.is_file() and join_self_loop_edge_ids:
                (
                    candidate_full_network_join_edge_file,
                    _full_network_join_edge_endpoint_rewrite_count,
                    candidate_full_network_join_dropped_self_loop_edges,
                    candidate_full_network_join_blocking_self_loop_edge_ids,
                ) = _write_joined_endpoint_edge_file(
                    current_raw_edge_file,
                    join_patch_file,
                    joined_scope_junction_ids,
                    output_dir / safe_junction_id / "full_network_join_replay.edg.xml",
                )
                surviving_edge_ids = _edge_file_ids(candidate_full_network_join_edge_file)
                absorbable_self_loop_edge_ids = [
                    edge_id
                    for edge_id in candidate_full_network_join_blocking_self_loop_edge_ids
                    if (
                        edge_id not in protected_self_loop_edge_ids
                        or _join_internal_self_loop_drop_has_witness(
                            edge_id,
                            candidate_full_network_join_dropped_self_loop_edges,
                            surviving_edge_ids,
                        )
                        or _teacher_boundary_edge_has_target_junction(
                            teacher_net_file,
                            teacher_junction_id,
                            edge_id,
                        )
                    )
                ]
                absorbable_self_loop_edge_id_set = set(absorbable_self_loop_edge_ids)
                full_network_join_blocking_self_loop_edge_ids = [
                    edge_id
                    for edge_id in candidate_full_network_join_blocking_self_loop_edge_ids
                    if edge_id not in absorbable_self_loop_edge_id_set
                ]
                if not full_network_join_blocking_self_loop_edge_ids:
                    full_network_join_edge_file = candidate_full_network_join_edge_file
                    full_network_join_dropped_self_loop_edges = candidate_full_network_join_dropped_self_loop_edges
                    full_network_join_absorbed_self_loop_edge_ids = list(
                        dict.fromkeys(candidate_full_network_join_dropped_self_loop_edges)
                    )
            use_full_network_join_patch_replay = (
                join_patch_file.is_file()
                and (
                    not scope_report.get("rewritten_endpoint_count")
                    or rewrite_joined_endpoints
                )
                and not full_network_join_blocking_self_loop_edge_ids
                and not scope_report.get("blocking_missing_node_ids")
                and not scope_report.get("blocking_missing_blocked_edge_ids")
                and not scope_report.get("blocking_missing_joined_scope_junction_ids")
            )
            join_patch_joined_node_ids = _join_patch_joined_node_ids(join_patch_file)
            can_replace_stale_joined_node = (
                joined_scope_junction_id == junction_id
                and joined_scope_junction_id in join_patch_joined_node_ids
            )
            if (
                use_full_network_join_patch_replay
                and joined_scope_junction_id in _plain_node_ids(current_raw_node_file)
                and joined_scope_junction_id in join_patch_joined_node_ids
                and not can_replace_stale_joined_node
            ):
                skipped_candidates.append(
                    {
                        "index": index,
                        "junction_id": junction_id,
                        "candidate_status": "sequential_candidate_overlap",
                        "overlap_edge_ids": [],
                        "overlap_node_ids": [joined_scope_junction_id],
                    }
                )
                continue
            replaced_stale_joined_node_ids = sorted(
                join_patch_joined_node_ids & _plain_node_ids(current_raw_node_file)
            )
            if can_replace_stale_joined_node and replaced_stale_joined_node_ids:
                scope_report["full_network_join_replaced_stale_joined_node_ids"] = replaced_stale_joined_node_ids
            if (
                scope_report.get("status") == "pass"
                and (scope_report.get("netconvert") or {}).get("status") == "pass"
                and (scope_report.get("sumo_load") or {}).get("status") == "pass"
                and joined_scope_junction_id
                and replay_edge_map
                and not (
                    max_ready_candidates is not None
                    and max_ready_candidates > 0
                    and attempted_ready_count >= max_ready_candidates
                    and not is_followup_candidate
                )
            ):
                variant_prefix = f"{_safe_stage_name(prefix, max_len=12)}_{index + 1:03d}"
                replay_tllogic_file = current_raw_tllogic_file
                if use_full_network_replay:
                    replay_node_file = current_raw_node_file
                    replay_edge_file = current_raw_edge_file
                    replay_connection_file = current_raw_connection_file
                    replay_candidate_net_file = current_candidate_net_file
                    replay_blocking_self_loop_edge_drops = []
                    replay_dropped_self_loop_edges = []
                    preabsorbed_join_internal_edge_ids = []
                    replay_edge_endpoint_rewrite_count = 0
                    scope_report["replay_scope"] = "full_network"
                elif use_full_network_join_patch_replay:
                    replay_node_file = _write_replay_node_file(
                        current_raw_node_file,
                        join_patch_file,
                        output_dir / safe_junction_id / "full_network_join_replay.nod.xml",
                    )
                    controlled_inner_prune = _prune_plain_node_controlled_inner_edges(
                        replay_node_file,
                        set(full_network_join_dropped_self_loop_edges),
                    )
                    scope_report["full_network_join_controlled_inner_prune"] = (
                        controlled_inner_prune
                    )
                    replay_edge_file = full_network_join_edge_file
                    replay_connection_file, dead_end_drop_count, dead_end_drop_edge_ids = _write_join_scope_connection_file(
                        replay_edge_file,
                        current_raw_connection_file,
                        {str(node_id) for node_id in scope_report.get("join_node_ids", []) or [] if str(node_id)},
                        output_dir / safe_junction_id / "full_network_join_replay.con.xml",
                        drop_edge_ids=set(full_network_join_dropped_self_loop_edges),
                    )
                    rewritten_replay_edge_file, rewritten_endpoint_count, rewritten_self_loop_edges, rewritten_blocking_self_loops = (
                        _write_joined_endpoint_edge_file(
                            replay_edge_file,
                            join_patch_file,
                            joined_scope_junction_ids,
                            output_dir / safe_junction_id / "full_network_join_replay_rewritten.edg.xml",
                            rewrite_endpoints=rewrite_joined_endpoints,
                        )
                    )
                    if rewrite_joined_endpoints:
                        rewritten_replay_connection_file, crossing_rewrite_count = _write_joined_endpoint_connection_file(
                            replay_connection_file,
                            join_patch_file,
                            output_dir / safe_junction_id / "full_network_join_replay_rewritten.con.xml",
                        )
                    else:
                        rewritten_replay_connection_file, crossing_rewrite_count = replay_connection_file, 0
                    if rewritten_replay_edge_file != replay_edge_file:
                        replay_edge_file = rewritten_replay_edge_file
                    if rewritten_replay_connection_file != replay_connection_file:
                        replay_connection_file = rewritten_replay_connection_file
                    scope_report["full_network_join_endpoint_rewrite_count"] = rewritten_endpoint_count
                    scope_report["full_network_join_crossing_node_rewrite_count"] = crossing_rewrite_count
                    scope_report["full_network_join_rewritten_self_loop_edges"] = rewritten_self_loop_edges
                    scope_report["full_network_join_rewritten_blocking_self_loop_edges"] = rewritten_blocking_self_loops
                    scope_report["full_network_join_dead_end_connection_drop_count"] = dead_end_drop_count
                    scope_report["full_network_join_dead_end_connection_drop_edge_ids"] = dead_end_drop_edge_ids
                    if current_raw_tllogic_file is not None:
                        (
                            replay_tllogic_file,
                            tllogic_drop_count,
                            tllogic_drop_edge_ids,
                        ) = _write_join_scope_tllogic_file(
                            current_raw_tllogic_file,
                            set(full_network_join_dropped_self_loop_edges),
                            output_dir / safe_junction_id / "full_network_join_replay.tll.xml",
                        )
                        scope_report["full_network_join_tllogic_connection_drop_count"] = (
                            tllogic_drop_count
                        )
                        scope_report["full_network_join_tllogic_connection_drop_edge_ids"] = (
                            tllogic_drop_edge_ids
                        )
                    replay_edge_endpoint_rewrite_count = 0
                    replay_dropped_self_loop_edges = full_network_join_dropped_self_loop_edges
                    replay_blocking_self_loop_edge_drops = full_network_join_blocking_self_loop_edge_ids
                    preabsorbed_join_internal_edge_ids = full_network_join_absorbed_self_loop_edge_ids
                    replay_candidate_net_file = output_dir / safe_junction_id / "full_network_join_replay.net.xml"
                    replay_type_file = current_raw_type_file
                    if current_raw_type_file is not None:
                        replay_type_report = write_missing_edge_type_patch(
                            raw_type_file=current_raw_type_file,
                            edge_file=replay_edge_file,
                            output_file=output_dir
                            / safe_junction_id
                            / "full_network_join_replay.typ.xml",
                        )
                        scope_report["full_network_join_type_patch"] = replay_type_report
                        if replay_type_report.get("status") != "pass":
                            scope_report["status"] = "review"
                            skipped_candidates.append(
                                {
                                    "index": index,
                                    "junction_id": junction_id,
                                    "candidate_status": "full_network_join_type_patch_failed",
                                }
                            )
                            continue
                        replay_type_value = str(replay_type_report.get("type_file", ""))
                        replay_type_file = Path(replay_type_value) if replay_type_value else None
                    seed_command = [
                        netconvert_binary,
                        "--node-files",
                        _command_path(replay_node_file, output_dir / safe_junction_id),
                        "--edge-files",
                        _command_path(replay_edge_file, output_dir / safe_junction_id),
                        "--connection-files",
                        _command_path(replay_connection_file, output_dir / safe_junction_id),
                        "--output-file",
                        replay_candidate_net_file.name,
                        "--walkingareas",
                        "true",
                        "--tls.ignore-internal-junction-jam",
                    ]
                    if replay_type_file is not None:
                        seed_command[5:5] = [
                            "--type-files",
                            _command_path(replay_type_file, output_dir / safe_junction_id),
                        ]
                    if replay_tllogic_file is not None:
                        seed_command[5:5] = [
                            "--tllogic-files",
                            _command_path(replay_tllogic_file, output_dir / safe_junction_id),
                        ]
                    seed_report = _command_report(
                        command_runner(seed_command, cwd=output_dir / safe_junction_id, timeout_seconds=timeout_seconds)
                    )
                    scope_report["full_network_join_seed_netconvert"] = seed_report
                    if seed_report.get("status") != "pass":
                        scope_report["status"] = "review"
                        skipped_candidates.append(
                            {
                                "index": index,
                                "junction_id": junction_id,
                                "candidate_status": "full_network_join_seed_failed",
                            }
                        )
                        continue
                    try:
                        refreshed_edge_map = _teacher_candidate_edge_map(
                            extract_teacher_junction_model(teacher_net_file, teacher_junction_id),
                            extract_teacher_junction_model(replay_candidate_net_file, joined_scope_junction_id),
                            teacher_junction_id=teacher_junction_id,
                            candidate_junction_id=joined_scope_junction_id,
                            drop_endpoint_mismatches=False,
                            max_bearing_delta=45.0,
                        )
                    except (ET.ParseError, OSError, KeyError, TypeError, ValueError) as exc:
                        refreshed_edge_map = {}
                        scope_report["full_network_join_refreshed_edge_map_error"] = f"{type(exc).__name__}: {exc}"
                    if refreshed_edge_map:
                        replacements = {
                            teacher_edge_id: {
                                "old": replay_edge_map.get(teacher_edge_id, ""),
                                "new": candidate_edge_id,
                            }
                            for teacher_edge_id, candidate_edge_id in refreshed_edge_map.items()
                            if replay_edge_map.get(teacher_edge_id) != candidate_edge_id
                        }
                        replay_edge_map = dict(sorted({**replay_edge_map, **refreshed_edge_map}.items()))
                        scope_report["full_network_join_refreshed_edge_map"] = refreshed_edge_map
                        scope_report["full_network_join_refreshed_edge_map_replacements"] = replacements
                    scope_report["replay_scope"] = "full_network_join_patch"
                else:
                    replay_node_file = _write_replay_node_file(
                        Path(str(scope_report.get("node_file", ""))),
                        join_patch_file,
                        output_dir / safe_junction_id / "expanded_scope_replay.nod.xml",
                    )
                    (
                        replay_edge_file,
                        replay_edge_endpoint_rewrite_count,
                        replay_dropped_self_loop_edges,
                        replay_blocking_self_loop_edge_drops,
                    ) = _write_joined_endpoint_edge_file(
                        Path(str(scope_report.get("edge_file", ""))),
                        join_patch_file,
                        joined_scope_junction_ids,
                        output_dir / safe_junction_id / "expanded_scope_replay.edg.xml",
                        rewrite_endpoints=rewrite_joined_endpoints,
                    )
                    if rewrite_joined_endpoints:
                        replay_connection_file, crossing_rewrite_count = _write_joined_endpoint_connection_file(
                            Path(str(scope_report.get("connection_file", ""))),
                            join_patch_file,
                            output_dir / safe_junction_id / "expanded_scope_replay.con.xml",
                        )
                    else:
                        replay_connection_file, crossing_rewrite_count = (
                            Path(str(scope_report.get("connection_file", ""))),
                            0,
                        )
                    scope_report["expanded_scope_crossing_node_rewrite_count"] = crossing_rewrite_count
                    replay_candidate_net_file = Path(str(scope_report.get("net_file", "")))
                    preabsorbed_join_internal_edge_ids = []
                    scope_report["replay_scope"] = "expanded_scope"
                replay_absorbed_join_internal_edge_ids = list(
                    dict.fromkeys(
                        [
                            *preabsorbed_join_internal_edge_ids,
                            *[
                                edge_id
                                for edge_id in replay_blocking_self_loop_edge_drops
                                if edge_id not in protected_self_loop_edge_ids
                            ],
                        ]
                    )
                )
                replay_blocking_self_loop_edge_drops = [
                    edge_id
                    for edge_id in replay_blocking_self_loop_edge_drops
                    if edge_id in protected_self_loop_edge_ids
                ]
                if candidate_replay_target_internal_subgraph and replay_blocking_self_loop_edge_drops:
                    surviving_edge_ids = _edge_file_ids(replay_edge_file)
                    deferred_self_loop_edge_ids = [
                        edge_id
                        for edge_id in replay_blocking_self_loop_edge_drops
                        if (
                            _join_internal_self_loop_drop_has_witness(
                                edge_id,
                                replay_dropped_self_loop_edges,
                                surviving_edge_ids,
                            )
                            or _teacher_boundary_edge_has_target_junction(
                                teacher_net_file,
                                teacher_junction_id,
                                edge_id,
                            )
                        )
                    ]
                    if deferred_self_loop_edge_ids:
                        replay_absorbed_join_internal_edge_ids = [
                            *replay_absorbed_join_internal_edge_ids,
                            *deferred_self_loop_edge_ids,
                        ]
                        deferred_self_loop_edge_id_set = set(deferred_self_loop_edge_ids)
                        replay_blocking_self_loop_edge_drops = [
                            edge_id
                            for edge_id in replay_blocking_self_loop_edge_drops
                            if edge_id not in deferred_self_loop_edge_id_set
                        ]
                scope_report["replay_node_file"] = str(replay_node_file)
                scope_report["replay_edge_file"] = str(replay_edge_file)
                scope_report["replay_edge_endpoint_rewrite_count"] = replay_edge_endpoint_rewrite_count
                scope_report["replay_self_loop_edge_drop_count"] = len(replay_dropped_self_loop_edges)
                scope_report["replay_dropped_self_loop_edges"] = replay_dropped_self_loop_edges
                scope_report["replay_absorbed_join_internal_edge_ids"] = replay_absorbed_join_internal_edge_ids
                scope_report["replay_blocking_self_loop_edge_drops"] = replay_blocking_self_loop_edge_drops
                if replay_blocking_self_loop_edge_drops:
                    scope_report["status"] = "review"
                    skipped_candidates.append(
                        {
                            "index": index,
                            "junction_id": junction_id,
                            "candidate_status": "unsafe_replay_self_loop_edge_drop",
                            "skip_reason": "singleton_or_no_witness_self_loop_drop"
                            if candidate_replay_target_internal_subgraph
                            else "protected_self_loop_edge_drop",
                            "replay_blocking_self_loop_edge_drops": replay_blocking_self_loop_edge_drops,
                        }
                    )
                    continue
                attempted_ready_count += 1
                try:
                    variant_report = variant_builder(
                        raw_node_file=replay_node_file,
                        raw_edge_file=replay_edge_file,
                        raw_connection_file=replay_connection_file,
                        raw_type_file=current_raw_type_file,
                        raw_tllogic_file=replay_tllogic_file,
                        teacher_net_file=teacher_net_file,
                        candidate_net_file=replay_candidate_net_file,
                        junction_id=joined_scope_junction_id,
                        output_dir=output_dir / safe_junction_id / "teacher_replay",
                        edge_map=replay_edge_map,
                        prefix=variant_prefix,
                        teacher_junction_id=teacher_junction_id,
                        crossing_edge_overrides=crossing_edge_overrides_by_junction.get(joined_scope_junction_id)
                        or crossing_edge_overrides_by_junction.get(junction_id)
                        or crossing_edge_overrides_by_junction.get(teacher_junction_id),
                        approach_endpoint_rebuild_plan=candidate.get("approach_endpoint_rebuild_plan", {}),
                        replay_target_internal_subgraph=candidate_replay_target_internal_subgraph,
                        preserve_teacher_lane_shapes=not use_full_network_join_patch_replay,
                        emit_teacher_crossings=not use_full_network_join_patch_replay,
                        netconvert_binary=netconvert_binary,
                        sumo_binary=sumo_binary,
                        timeout_seconds=timeout_seconds,
                    )
                except Exception as exc:  # noqa: BLE001 - isolate one injected variant builder failure.
                    variant_report = _variant_exception_report(exc, joined_scope_junction_id)
                attached_report = _attach_candidate_template_context(variant_report, candidate)
                attached_report.setdefault("teacher_junction_id", teacher_junction_id)
                if scope_report.get("replay_scope") == "expanded_scope":
                    attached_report["candidate_scope_status"] = "local_scope"
                    attached_report["global_candidate_eligible"] = False
                    attached_report["candidate_scope_reason"] = "expanded_scope_replay_uses_local_plain_net"
                else:
                    attached_report["candidate_scope_status"] = "full_network"
                    attached_report["global_candidate_eligible"] = True
                variant_reports.append(attached_report)
                followup_candidate = _expanded_scope_followup_candidate_for_unsafe_internal_replay(
                    candidate,
                    attached_report,
                    replay_edge_file,
                    junction_id=junction_id,
                )
                if followup_candidate is not None:
                    attached_report["expanded_scope_followup_emitted"] = True
                    expanded_scope_followup_candidates.append(followup_candidate)
                    candidates.append(followup_candidate)
                final_net_file = Path(str(attached_report.get("final_net_file", "")))
                if (
                    (use_full_network_replay or use_full_network_join_patch_replay)
                    and sequential_accept_passed_variants
                    and attached_report.get("status") == "pass"
                    and attached_report.get("parity_gate_status") == "pass"
                    and final_net_file.exists()
                ):
                    attached_report["composite_applied"] = True
                    composite_applied_candidate_count += 1
                    composite_net_file = str(final_net_file)
                    replay_entry = _accepted_target_internal_replay_entry(
                        attached_report,
                        junction_id=joined_scope_junction_id,
                        teacher_junction_id=teacher_junction_id,
                    )
                    if replay_entry is not None:
                        accepted_internal_replays.append(replay_entry)
                    applied_candidate_edge_ids.update(candidate_edge_ids)
                    applied_candidate_node_ids.update(candidate_node_ids)
                    current_candidate_net_file = final_net_file
                    if plain_exporter is not None and index < len(candidates) - 1:
                        export_report = plain_exporter(
                            net_file=final_net_file,
                            output_dir=output_dir / safe_junction_id / "sequential_plain",
                            prefix=f"{variant_prefix}_sequential",
                            netconvert_binary=netconvert_binary,
                            timeout_seconds=timeout_seconds,
                        )
                        sequential_plain_export_reports.append(export_report)
                        if export_report.get("status") == "pass":
                            export_report["teacher_plain_tls_cleanup"] = _prune_plain_tls_against_teacher(
                                teacher_net_file=teacher_net_file,
                                node_file=Path(str(export_report["raw_node_file"])),
                                connection_file=Path(str(export_report["raw_connection_file"])),
                                tllogic_file=(
                                    Path(str(export_report["raw_tllogic_file"]))
                                    if export_report.get("raw_tllogic_file")
                                    else None
                                ),
                            )
                            current_raw_node_file = Path(str(export_report["raw_node_file"]))
                            current_raw_edge_file = Path(str(export_report["raw_edge_file"]))
                            current_raw_connection_file = Path(str(export_report["raw_connection_file"]))
                            raw_type_value = str(export_report.get("raw_type_file", ""))
                            current_raw_type_file = Path(raw_type_value) if raw_type_value else None
                            raw_tllogic_value = str(export_report.get("raw_tllogic_file", ""))
                            current_raw_tllogic_file = Path(raw_tllogic_value) if raw_tllogic_value else None
                        else:
                            sequential_blocked_reason = str(
                                export_report.get("error", "plain export failed after accepted variant")
                            )
            else:
                skipped_candidates.append(
                    _expanded_scope_skip_entry(
                        index=index,
                        junction_id=junction_id,
                        candidate_status=str(candidate.get("candidate_status", "skipped")),
                        scope_report=scope_report,
                        replay_edge_map=replay_edge_map,
                    )
                )
            continue
        if candidate.get("candidate_status") != "ready_for_teacher_guided_variant" or not junction_id:
            candidate_status = str(candidate.get("candidate_status", "skipped"))
            skipped_candidates.append(
                {
                    "index": index,
                    "junction_id": junction_id,
                    "candidate_status": candidate_status,
                    **({"skip_reason": candidate_status} if candidate_status == "no_vehicle_reference_context" else {}),
                }
            )
            continue
        if not edge_map:
            skipped_candidates.append(
                {"index": index, "junction_id": junction_id, "candidate_status": "invalid_edge_map"}
            )
            continue
        if (
            max_ready_candidates is not None
            and max_ready_candidates > 0
            and attempted_ready_count >= max_ready_candidates
            and not is_followup_candidate
        ):
            skipped_candidates.append(
                {"index": index, "junction_id": junction_id, "candidate_status": "max_ready_candidates_reached"}
            )
            continue

        safe_junction_id = _queue_candidate_dir(index, junction_id)
        variant_prefix = f"{_safe_stage_name(prefix, max_len=12)}_{index + 1:03d}"
        attempted_ready_count += 1
        try:
            variant_report = variant_builder(
                raw_node_file=current_raw_node_file,
                raw_edge_file=current_raw_edge_file,
                raw_connection_file=current_raw_connection_file,
                raw_type_file=current_raw_type_file,
                raw_tllogic_file=current_raw_tllogic_file,
                teacher_net_file=teacher_net_file,
                candidate_net_file=current_candidate_net_file,
                junction_id=junction_id,
                output_dir=output_dir / safe_junction_id,
                edge_map=edge_map,
                prefix=variant_prefix,
                teacher_junction_id=teacher_junction_id,
                crossing_edge_overrides=crossing_edge_overrides_by_junction.get(junction_id)
                or crossing_edge_overrides_by_junction.get(teacher_junction_id),
                replay_target_internal_subgraph=candidate_replay_target_internal_subgraph,
                netconvert_binary=netconvert_binary,
                sumo_binary=sumo_binary,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - isolate one injected variant builder failure.
            variant_report = _variant_exception_report(exc, junction_id)
        attached_report = _attach_candidate_template_context(variant_report, candidate)
        attached_report.setdefault("teacher_junction_id", teacher_junction_id)
        variant_reports.append(attached_report)
        followup_candidate = _expanded_scope_followup_candidate_for_unsafe_internal_replay(
            candidate,
            attached_report,
            current_raw_edge_file,
            junction_id=junction_id,
        )
        if followup_candidate is not None:
            attached_report["expanded_scope_followup_emitted"] = True
            expanded_scope_followup_candidates.append(followup_candidate)
            candidates.append(followup_candidate)
        final_net_file = Path(str(attached_report.get("final_net_file", "")))
        if (
            sequential_accept_passed_variants
            and attached_report.get("status") == "pass"
            and attached_report.get("parity_gate_status") == "pass"
            and final_net_file.exists()
        ):
            attached_report["composite_applied"] = True
            composite_applied_candidate_count += 1
            composite_net_file = str(final_net_file)
            replay_entry = _accepted_target_internal_replay_entry(
                attached_report,
                junction_id=junction_id,
                teacher_junction_id=teacher_junction_id,
            )
            if replay_entry is not None:
                accepted_internal_replays.append(replay_entry)
            applied_candidate_edge_ids.update(candidate_edge_ids)
            applied_candidate_node_ids.update(candidate_node_ids)
            current_candidate_net_file = final_net_file
            if plain_exporter is not None and index < len(candidates) - 1:
                export_report = plain_exporter(
                    net_file=final_net_file,
                    output_dir=output_dir / safe_junction_id / "sequential_plain",
                    prefix=f"{variant_prefix}_sequential",
                    netconvert_binary=netconvert_binary,
                    timeout_seconds=timeout_seconds,
                )
                sequential_plain_export_reports.append(export_report)
                if export_report.get("status") == "pass":
                    export_report["teacher_plain_tls_cleanup"] = _prune_plain_tls_against_teacher(
                        teacher_net_file=teacher_net_file,
                        node_file=Path(str(export_report["raw_node_file"])),
                        connection_file=Path(str(export_report["raw_connection_file"])),
                        tllogic_file=(
                            Path(str(export_report["raw_tllogic_file"]))
                            if export_report.get("raw_tllogic_file")
                            else None
                        ),
                    )
                    current_raw_node_file = Path(str(export_report["raw_node_file"]))
                    current_raw_edge_file = Path(str(export_report["raw_edge_file"]))
                    current_raw_connection_file = Path(str(export_report["raw_connection_file"]))
                    raw_type_value = str(export_report.get("raw_type_file", ""))
                    current_raw_type_file = Path(raw_type_value) if raw_type_value else None
                    raw_tllogic_value = str(export_report.get("raw_tllogic_file", ""))
                    current_raw_tllogic_file = Path(raw_tllogic_value) if raw_tllogic_value else None
                else:
                    sequential_blocked_reason = str(
                        export_report.get("error", "plain export failed after accepted variant")
                    )

    connection_mode_regression_reports: list[dict[str, object]] = []
    if connection_mode_regression_builder is not None:
        for regression_index, variant_report in enumerate(variant_reports, start=1):
            if not bool(variant_report.get("global_candidate_eligible", True)):
                variant_report["connection_mode_regression"] = {
                    "status": "skipped",
                    "automatic_promotion_gate": "not_applicable",
                    "reason": "local-scope candidate cannot be compared with the full source network",
                }
                continue
            final_net_file = Path(str(variant_report.get("final_net_file", "")))
            if not final_net_file.is_file():
                if variant_report.get("status") != "pass":
                    variant_report["connection_mode_regression"] = {
                        "status": "skipped",
                        "automatic_promotion_gate": "not_applicable",
                        "reason": "failed variant did not produce a candidate network",
                    }
                    continue
                regression_report: dict[str, object] = {
                    "status": "fail",
                    "claim_status": "construction-invalid",
                    "automatic_promotion_gate": "blocked",
                    "error": f"candidate network missing: {final_net_file}",
                }
            else:
                source_scope_ids, candidate_scope_ids = _candidate_connection_mode_scope_ids(
                    variant_report
                )
                try:
                    regression_report = dict(
                        connection_mode_regression_builder(
                            source_net_file=candidate_net_file,
                            candidate_net_file=final_net_file,
                            output_dir=final_net_file.parent / "connection_mode_regression",
                            prefix=f"{_safe_stage_name(prefix, max_len=24)}_{regression_index:03d}",
                            target_source_junction_ids=source_scope_ids,
                            target_candidate_junction_ids=candidate_scope_ids,
                        )
                    )
                except (ET.ParseError, OSError, RuntimeError, TypeError, ValueError) as exc:
                    regression_report = {
                        "status": "fail",
                        "claim_status": "construction-invalid",
                        "automatic_promotion_gate": "blocked",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
            variant_report["connection_mode_regression"] = regression_report
            connection_mode_regression_reports.append(regression_report)
    if connection_mode_regression_builder is None:
        connection_mode_regression_status = "skipped"
    elif not connection_mode_regression_reports:
        connection_mode_regression_status = "not_run"
    elif all(report.get("status") == "pass" for report in connection_mode_regression_reports):
        connection_mode_regression_status = "pass"
    else:
        connection_mode_regression_status = "fail"
    connection_mode_regression_failed = connection_mode_regression_status == "fail"

    attempted_count = len(variant_reports)
    pass_count = sum(1 for report in variant_reports if report.get("status") == "pass")
    failed_count = attempted_count - pass_count
    parity_pass_count = sum(1 for report in variant_reports if report.get("parity_gate_status") == "pass")
    local_scope_candidate_count = sum(
        1 for report in variant_reports if report.get("candidate_scope_status") == "local_scope"
    )
    global_candidate_eligible_count = sum(
        1 for report in variant_reports if report.get("global_candidate_eligible", True)
    )
    semantic_failure_counts = _semantic_failure_counts(variant_reports)
    semantic_layer_gate_counts = _semantic_layer_gate_counts(variant_reports)
    approach_integrity_failure_counts = _approach_integrity_failure_counts(semantic_failure_counts)
    expanded_scope_pass_count = sum(1 for report in expanded_scope_reports if report.get("status") == "pass")
    best_expanded_scope_net_file = ""
    for expanded_report in expanded_scope_reports:
        if expanded_report.get("status") != "pass":
            continue
        net_file = Path(str(expanded_report.get("net_file", "")))
        if net_file.exists():
            best_expanded_scope_net_file = str(net_file)
            break
    final_internal_replay_reports = []
    final_internal_replay_status = "skipped"
    final_internal_replay_normalize_report = None
    final_internal_replay_normalized_net_file = ""
    if (
        sequential_accept_passed_variants
        and composite_applied_candidate_count > 0
        and composite_net_file
        and Path(composite_net_file).exists()
        and accepted_internal_replays
    ):
        final_internal_replay_status = "pass"
        replay_junction_ids = {str(entry["junction_id"]) for entry in accepted_internal_replays}
        use_clean_replay_base = (
            any(entry.get("prefer_clean_replay_base") for entry in accepted_internal_replays)
            and _net_contains_normal_junctions(candidate_net_file, replay_junction_ids)
        )
        current_composite_net_file = (
            candidate_net_file
            if use_clean_replay_base
            else Path(composite_net_file)
        )
        restore_dir = output_dir / "final_internal_replay"
        restore_dir.mkdir(parents=True, exist_ok=True)
        for restore_index, replay_entry in enumerate(accepted_internal_replays, start=1):
            restore_junction_id = str(replay_entry["junction_id"])
            restore_file = (
                restore_dir
                / f"{restore_index:03d}_{_safe_stage_name(restore_junction_id, max_len=32)}_target_internal_replay.net.xml"
            )
            replay_report = final_internal_replay_writer(
                candidate_net_file=current_composite_net_file,
                teacher_net_file=teacher_net_file,
                output_file=restore_file,
                junction_id=restore_junction_id,
                teacher_junction_id=str(replay_entry["teacher_junction_id"]),
                edge_map=dict(replay_entry["edge_map"]),
            )
            final_internal_replay_reports.append(replay_report)
            restored_net_file = Path(str(replay_report.get("net_file", "")))
            if replay_report.get("status") != "pass" or not restored_net_file.exists():
                final_internal_replay_status = "fail"
                break
            current_composite_net_file = restored_net_file
        if final_internal_replay_status == "pass":
            normalized_composite_net_file = _stage_file(
                restore_dir,
                prefix,
                "final_internal_replay_normalized.net.xml",
            )
            final_internal_replay_normalize_command = [
                netconvert_binary,
                "--sumo-net-file",
                _command_path(current_composite_net_file, restore_dir),
                "--output-file",
                _command_path(normalized_composite_net_file, restore_dir),
            ]
            final_internal_replay_normalize_report = _command_report(
                command_runner(
                    final_internal_replay_normalize_command,
                    cwd=restore_dir,
                    timeout_seconds=timeout_seconds,
                )
            )
            final_internal_replay_normalize_report["output_file"] = str(normalized_composite_net_file)
            geometry_restore_reports = []
            if (
                final_internal_replay_normalize_report.get("status") == "pass"
                and normalized_composite_net_file.exists()
            ):
                excluded_replay_junction_ids = {
                    str(replay_entry["junction_id"]) for replay_entry in accepted_internal_replays
                }
                final_internal_replay_normalize_report["non_target_internal_restore"] = (
                    _restore_non_target_internal_artifacts(
                        source_file=current_composite_net_file,
                        target_file=normalized_composite_net_file,
                        exclude_junction_ids=excluded_replay_junction_ids,
                    )
                )
                final_internal_replay_normalize_report["teacher_non_tls_tllogic_cleanup"] = (
                    _remove_teacher_non_tls_tllogics(
                        teacher_net_file=teacher_net_file,
                        target_file=normalized_composite_net_file,
                    )
                )
                final_internal_replay_normalize_report["false_traffic_light_type_restore"] = (
                    _restore_false_traffic_light_junction_types(
                        source_file=current_composite_net_file,
                        target_file=normalized_composite_net_file,
                        fallback_node_file=current_raw_node_file,
                        exclude_junction_ids=excluded_replay_junction_ids,
                    )
                )
                final_internal_replay_normalize_report["teacher_absent_context_tls_cleanup"] = (
                    _demote_teacher_absent_context_tls(
                        teacher_net_file=teacher_net_file,
                        target_file=normalized_composite_net_file,
                        accepted_internal_replays=accepted_internal_replays,
                    )
                )
                for replay_entry, replay_report in zip(accepted_internal_replays, final_internal_replay_reports):
                    restored_net_file = Path(str(replay_report.get("net_file", "")))
                    if replay_report.get("status") != "pass" or not restored_net_file.exists():
                        continue
                    geometry_restore_report = _restore_replayed_geometry_attrs(
                        source_file=restored_net_file,
                        target_file=normalized_composite_net_file,
                        junction_id=str(replay_entry["junction_id"]),
                    )
                    geometry_restore_reports.append(geometry_restore_report)
                    if geometry_restore_report.get("status") != "pass":
                        break
                final_internal_replay_normalize_report["geometry_restore"] = geometry_restore_reports
                if all(report.get("status") == "pass" for report in geometry_restore_reports):
                    canonical_composite_net_file = _stage_file(
                        restore_dir,
                        prefix,
                        "final_internal_replay_canonical.net.xml",
                    )
                    final_internal_replay_canonical_command = [
                        netconvert_binary,
                        "--sumo-net-file",
                        _command_path(normalized_composite_net_file, restore_dir),
                        "--output-file",
                        _command_path(canonical_composite_net_file, restore_dir),
                    ]
                    final_internal_replay_canonical_report = _command_report(
                        command_runner(
                            final_internal_replay_canonical_command,
                            cwd=restore_dir,
                            timeout_seconds=timeout_seconds,
                        )
                    )
                    final_internal_replay_canonical_report["output_file"] = str(canonical_composite_net_file)
                    final_internal_replay_normalize_report["canonicalize"] = final_internal_replay_canonical_report
                    if (
                        final_internal_replay_canonical_report.get("status") == "pass"
                        and canonical_composite_net_file.exists()
                    ):
                        canonical_geometry_restore_reports = []
                        for replay_entry, replay_report in zip(accepted_internal_replays, final_internal_replay_reports):
                            restored_net_file = Path(str(replay_report.get("net_file", "")))
                            if replay_report.get("status") != "pass" or not restored_net_file.exists():
                                continue
                            canonical_geometry_restore_report = _restore_replayed_geometry_attrs(
                                source_file=restored_net_file,
                                target_file=canonical_composite_net_file,
                                junction_id=str(replay_entry["junction_id"]),
                            )
                            canonical_geometry_restore_reports.append(canonical_geometry_restore_report)
                            if canonical_geometry_restore_report.get("status") != "pass":
                                break
                        final_internal_replay_canonical_report["geometry_restore"] = canonical_geometry_restore_reports
                        final_internal_replay_canonical_report["teacher_absent_context_tls_cleanup"] = (
                            _demote_teacher_absent_context_tls(
                                teacher_net_file=teacher_net_file,
                                target_file=canonical_composite_net_file,
                                accepted_internal_replays=accepted_internal_replays,
                            )
                        )
                        if all(report.get("status") == "pass" for report in canonical_geometry_restore_reports):
                            final_internal_replay_normalized_net_file = str(canonical_composite_net_file)
                            composite_net_file = final_internal_replay_normalized_net_file
                        else:
                            final_internal_replay_status = "fail"
                            final_internal_replay_normalize_report["status"] = "fail"
                            final_internal_replay_normalize_report["error"] = (
                                "geometry restore failed after canonicalization"
                            )
                    else:
                        final_internal_replay_status = "fail"
                        final_internal_replay_normalize_report["status"] = "fail"
                        final_internal_replay_normalize_report["error"] = "canonicalize failed after geometry restore"
                else:
                    final_internal_replay_status = "fail"
                    final_internal_replay_normalize_report["status"] = "fail"
                    final_internal_replay_normalize_report["error"] = "geometry restore failed after normalization"
            else:
                final_internal_replay_status = "fail"
                if final_internal_replay_normalize_report.get("status") == "pass":
                    final_internal_replay_normalize_report["status"] = "fail"
                    final_internal_replay_normalize_report["error"] = (
                        f"normalized output missing: {normalized_composite_net_file}"
                    )
    final_composite_parity = _final_composite_parity_gate(
        teacher_net_file=teacher_net_file,
        composite_net_file=Path(composite_net_file) if composite_net_file else None,
        accepted_internal_replays=accepted_internal_replays,
        enabled=sequential_accept_passed_variants and final_internal_replay_status != "fail",
    )
    final_composite_parity_failed = final_composite_parity.get("status") == "fail"
    final_context_parity = _final_context_parity_gate(
        teacher_net_file=teacher_net_file,
        composite_net_file=Path(composite_net_file) if composite_net_file else None,
        accepted_internal_replays=accepted_internal_replays,
        teacher_join_groups_by_cluster=teacher_join_groups_by_cluster,
        enabled=sequential_accept_passed_variants and final_internal_replay_status != "fail",
    )
    final_context_parity_failed = final_context_parity.get("status") == "fail"
    context_gate_status = str(final_context_parity.get("status", "skipped"))
    sequential_composite_ready = (
        sequential_accept_passed_variants
        and composite_applied_candidate_count > 0
        and bool(composite_net_file)
        and Path(composite_net_file).exists()
        and final_internal_replay_status != "fail"
        and not final_composite_parity_failed
        and not final_context_parity_failed
    )
    if attempted_count == 0:
        status = "blocked"
        claim_status = "blocked"
        parity_gate_status = "blocked"
    elif final_composite_parity_failed:
        status = "fail"
        claim_status = "construction-invalid"
        parity_gate_status = "fail"
    elif final_context_parity_failed:
        status = "fail"
        claim_status = "construction-invalid"
        parity_gate_status = "pass" if parity_pass_count == attempted_count else "fail"
    elif connection_mode_regression_failed:
        status = "fail"
        claim_status = "construction-invalid"
        parity_gate_status = "pass" if parity_pass_count == attempted_count else "fail"
    elif sequential_composite_ready and failed_count == 0:
        status = "pass"
        claim_status = "diagnostic-demo"
        parity_gate_status = "pass"
    else:
        status = "pass" if failed_count == 0 and parity_pass_count == attempted_count else "fail"
        claim_status = "construction-invalid" if failed_count else "diagnostic-demo"
        parity_gate_status = "pass" if parity_pass_count == attempted_count else "fail"

    approach_integrity_status = _approach_integrity_status(
        parity_gate_status=parity_gate_status,
        attempted_count=attempted_count,
        semantic_failure_counts=semantic_failure_counts,
        approach_failure_counts=approach_integrity_failure_counts,
    )
    promotion_gate_file = output_dir / f"{prefix}_promotion_gate.json"
    promotion_gate = _write_teacher_guided_promotion_gate(
        output_file=promotion_gate_file,
        status=status,
        claim_status=claim_status,
        parity_gate_status=parity_gate_status,
        context_gate_status=context_gate_status,
        connection_mode_regression_status=connection_mode_regression_status,
        approach_integrity_status=approach_integrity_status,
        variant_reports=variant_reports,
    )

    run_report_file = output_dir / f"{prefix}_run_report.json"
    report = {
        "status": status,
        "claim_status": claim_status,
        "parity_gate_status": parity_gate_status,
        "teacher_net_file": str(teacher_net_file),
        "candidate_net_file": str(candidate_net_file),
        "raw_node_file": str(raw_node_file),
        "raw_edge_file": str(raw_edge_file),
        "raw_connection_file": str(raw_connection_file),
        "raw_type_file": str(raw_type_file) if raw_type_file is not None else "",
        "raw_tllogic_file": str(raw_tllogic_file) if raw_tllogic_file is not None else "",
        "candidate_count": len(candidates),
        "max_ready_candidates": max_ready_candidates if max_ready_candidates is not None else "",
        "attempted_candidate_count": attempted_count,
        "skipped_candidate_count": len(skipped_candidates),
        "pass_candidate_count": pass_count,
        "failed_candidate_count": failed_count,
        "parity_pass_candidate_count": parity_pass_count,
        "local_scope_candidate_count": local_scope_candidate_count,
        "global_candidate_eligible_count": global_candidate_eligible_count,
        "semantic_failure_counts": semantic_failure_counts,
        "semantic_layer_gate_counts": semantic_layer_gate_counts,
        "approach_integrity_status": approach_integrity_status,
        "approach_integrity_failure_counts": approach_integrity_failure_counts,
        "context_gate_status": context_gate_status,
        "connection_mode_regression_status": connection_mode_regression_status,
        "connection_mode_regression_reports": connection_mode_regression_reports,
        "promotion_gate_status": promotion_gate["status"],
        "promotion_gate_file": str(promotion_gate_file),
        "expanded_scope_candidate_count": len(expanded_scope_reports),
        "expanded_scope_pass_candidate_count": expanded_scope_pass_count,
        "best_expanded_scope_net_file": best_expanded_scope_net_file,
        "expanded_scope_followup_candidate_count": len(expanded_scope_followup_candidates),
        "expanded_scope_followup_candidates": expanded_scope_followup_candidates,
        "expand_fragmented_tls_join_scope": expand_fragmented_tls_join_scope,
        "sequential_accept_passed_variants": sequential_accept_passed_variants,
        "sequential_plain_export_status": "skipped"
        if not sequential_accept_passed_variants or not sequential_plain_export_reports
        else ("pass" if all(report.get("status") == "pass" for report in sequential_plain_export_reports) else "fail"),
        "sequential_plain_export_reports": sequential_plain_export_reports,
        "composite_applied_candidate_count": composite_applied_candidate_count,
        "composite_net_file": composite_net_file,
        "final_internal_replay_status": final_internal_replay_status,
        "final_internal_replay_normalize": final_internal_replay_normalize_report,
        "final_internal_replay_normalized_net_file": final_internal_replay_normalized_net_file,
        "final_composite_parity": final_composite_parity,
        "final_context_parity": final_context_parity,
        "final_internal_replay_restored_count": sum(
            1 for report in final_internal_replay_reports if report.get("status") == "pass"
        ),
        "final_internal_replay_reports": final_internal_replay_reports,
        "expanded_scope_reports": expanded_scope_reports,
        "run_report_file": str(run_report_file),
        "variant_reports": variant_reports,
        "teacher_pattern_contexts": _teacher_pattern_contexts(variant_reports + expanded_scope_reports),
        "skipped_candidates": skipped_candidates,
        "review_policy": (
            "code-native Connection Mode regression must pass; use NetEdit only as optional visual review"
        ),
    }
    run_report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report






def _final_context_parity_gate(
    *,
    teacher_net_file: Path,
    composite_net_file: Path | None,
    accepted_internal_replays: list[dict[str, object]],
    teacher_join_groups_by_cluster: dict[str, list[str]] | None = None,
    enabled: bool,
    radius_m: float = 100.0,
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
    split_cluster_repair_seeds: list[dict[str, object]] = []
    seen_split_cluster_repair_seed_keys: set[tuple[str, tuple[str, ...]]] = set()
    for replay in accepted_internal_replays:
        junction_id = str(replay.get("junction_id", ""))
        teacher_junction_id = str(replay.get("teacher_junction_id", ""))
        if not junction_id or not teacher_junction_id:
            reports.append(
                {
                    "status": "fail",
                    "junction_id": junction_id,
                    "teacher_junction_id": teacher_junction_id,
                    "reason": "missing_context_inputs",
                }
            )
            continue
        teacher_context = _local_junction_context_summary(
            teacher_root,
            teacher_junction_id,
            radius_m=radius_m,
        )
        candidate_context = _local_junction_context_summary(
            composite_root,
            junction_id,
            radius_m=radius_m,
        )
        if teacher_context.get("status") != "pass" or candidate_context.get("status") != "pass":
            reports.append(
                {
                    "status": "fail",
                    "junction_id": junction_id,
                    "teacher_junction_id": teacher_junction_id,
                    "reason": "context_extract_failed",
                    "teacher_context": teacher_context,
                    "candidate_context": candidate_context,
                }
            )
            continue
        delta = _context_count_delta(teacher_context, candidate_context)
        split_cluster_residuals = _split_cluster_member_residuals(
            teacher_context,
            candidate_context,
            teacher_join_groups_by_cluster=teacher_join_groups_by_cluster,
        )
        report_repair_seeds = []
        for residual in split_cluster_residuals:
            reference_id = str(residual.get("teacher_cluster_junction_id", ""))
            member_ids = [
                str(member_id)
                for member_id in residual.get("candidate_member_junction_ids", []) or []
                if str(member_id)
            ]
            seed_key = (reference_id, tuple(member_ids))
            if not reference_id or seed_key in seen_split_cluster_repair_seed_keys:
                continue
            seen_split_cluster_repair_seed_keys.add(seed_key)
            seed = {
                "reference_id": reference_id,
                "candidate_member_junction_ids": member_ids,
                "triggering_junction_id": junction_id,
                "triggering_teacher_junction_id": teacher_junction_id,
                "seed_reason": "final_context_split_cluster_residual",
            }
            split_cluster_repair_seeds.append(seed)
            report_repair_seeds.append(seed)
        hard_failures = [
            {"field": field, "count": count}
            for field, count in delta.items()
            if field in {"traffic_light_junction_count", "tl_logic_count"} and count > 0
        ]
        if split_cluster_residuals:
            hard_failures.append(
                {
                    "field": "split_cluster_member_junction_count",
                    "count": len(split_cluster_residuals),
                }
            )
        reports.append(
            {
                "status": "fail" if hard_failures else "pass",
                "junction_id": junction_id,
                "teacher_junction_id": teacher_junction_id,
                "radius_m": radius_m,
                "teacher_context": teacher_context,
                "candidate_context": candidate_context,
                "delta_candidate_minus_teacher": delta,
                "split_cluster_member_residuals": split_cluster_residuals,
                "context_split_cluster_repair_seeds": report_repair_seeds,
                "hard_failures": hard_failures,
            }
        )
    return {
        "status": "pass" if reports and all(report.get("status") == "pass" for report in reports) else "fail",
        "checked_junction_count": len(reports),
        "radius_m": radius_m,
        "hard_failure_fields": [
            "traffic_light_junction_count",
            "tl_logic_count",
            "split_cluster_member_junction_count",
        ],
        "context_split_cluster_repair_seed_count": len(split_cluster_repair_seeds),
        "context_split_cluster_repair_seeds": split_cluster_repair_seeds,
        "reports": reports,
    }




def _demote_teacher_absent_context_tls(
    *,
    teacher_net_file: Path,
    target_file: Path,
    accepted_internal_replays: list[dict[str, object]],
    radius_m: float = 100.0,
) -> dict[str, object]:
    if not teacher_net_file.exists():
        return _failure(f"teacher net file does not exist: {teacher_net_file}")
    if not target_file.exists():
        return _failure(f"target net file does not exist: {target_file}")
    if not accepted_internal_replays:
        return {"status": "pass", "claim_status": "diagnostic-demo", "demoted_context_tls_count": 0}
    try:
        teacher_root = ET.parse(teacher_net_file).getroot()
        target_tree = ET.parse(target_file)
    except (OSError, ET.ParseError) as exc:
        return _failure(f"parse_error: {exc}")
    target_root = target_tree.getroot()
    protected_candidate_tls_ids = {
        str(replay.get("junction_id", "")) for replay in accepted_internal_replays if str(replay.get("junction_id", ""))
    }

    candidate_tls_to_demote: set[str] = set()
    skipped_contexts: list[dict[str, object]] = []
    for replay in accepted_internal_replays:
        teacher_junction_id = str(replay.get("teacher_junction_id", ""))
        junction_id = str(replay.get("junction_id", ""))
        if not teacher_junction_id or not junction_id:
            continue
        teacher_context = _local_junction_context_summary(
            teacher_root,
            teacher_junction_id,
            radius_m=radius_m,
        )
        candidate_context = _local_junction_context_summary(
            target_root,
            junction_id,
            radius_m=radius_m,
        )
        if teacher_context.get("status") != "pass" or candidate_context.get("status") != "pass":
            skipped_contexts.append(
                {
                    "junction_id": junction_id,
                    "teacher_junction_id": teacher_junction_id,
                    "reason": "context_extract_failed",
                }
            )
            continue
        teacher_extra_tls_ids = (
            set(str(item) for item in teacher_context.get("traffic_light_junction_ids", []) if str(item))
            | set(str(item) for item in teacher_context.get("tl_logic_ids", []) if str(item))
        ) - {teacher_junction_id}
        if teacher_extra_tls_ids:
            skipped_contexts.append(
                {
                    "junction_id": junction_id,
                    "teacher_junction_id": teacher_junction_id,
                    "reason": "teacher_has_extra_context_tls",
                    "teacher_extra_tls_ids": sorted(teacher_extra_tls_ids),
                }
            )
            continue
        candidate_tls_to_demote.update(
            (
                set(str(item) for item in candidate_context.get("traffic_light_junction_ids", []) if str(item))
                | set(str(item) for item in candidate_context.get("tl_logic_ids", []) if str(item))
            )
            - protected_candidate_tls_ids
        )

    demoted_junction_ids = []
    for junction in target_root.findall("junction"):
        junction_id = str(junction.attrib.get("id", ""))
        if junction_id in candidate_tls_to_demote and junction.attrib.get("type") == "traffic_light":
            junction.set("type", "priority")
            demoted_junction_ids.append(junction_id)

    removed_tllogic_ids = []
    for tllogic in list(target_root.findall("tlLogic")):
        tls_id = str(tllogic.attrib.get("id", ""))
        if tls_id in candidate_tls_to_demote:
            target_root.remove(tllogic)
            removed_tllogic_ids.append(tls_id)

    uncontrolled_connections = []
    for connection in target_root.findall("connection"):
        if str(connection.attrib.get("tl", "")) not in candidate_tls_to_demote:
            continue
        uncontrolled_connections.append(dict(connection.attrib))
        for attr in ("tl", "linkIndex", "linkIndex2"):
            connection.attrib.pop(attr, None)
        connection.set("uncontrolled", "true")

    if demoted_junction_ids or removed_tllogic_ids or uncontrolled_connections:
        ET.indent(target_root, space="    ")
        target_tree.write(target_file, encoding="utf-8", xml_declaration=True)

    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "radius_m": radius_m,
        "candidate_context_tls_ids": sorted(candidate_tls_to_demote),
        "demoted_context_tls_count": len(candidate_tls_to_demote),
        "demoted_context_tls_junction_count": len(demoted_junction_ids),
        "demoted_context_tls_junction_ids": sorted(demoted_junction_ids),
        "removed_context_tllogic_count": len(removed_tllogic_ids),
        "removed_context_tllogic_ids": sorted(removed_tllogic_ids),
        "uncontrolled_context_tls_connection_count": len(uncontrolled_connections),
        "uncontrolled_context_tls_connections": uncontrolled_connections,
        "skipped_contexts": skipped_contexts,
    }


def _local_junction_context_summary(root: ET.Element, junction_id: str, *, radius_m: float) -> dict[str, object]:
    target = root.find(f"junction[@id='{junction_id}']")
    if target is None:
        return {"status": "fail", "reason": "missing_target_junction", "junction_id": junction_id}
    try:
        center = (float(target.attrib.get("x", "")), float(target.attrib.get("y", "")))
    except ValueError:
        return {"status": "fail", "reason": "invalid_target_coordinate", "junction_id": junction_id}

    junctions = {
        str(junction.attrib.get("id", "")): junction
        for junction in root.findall("junction")
        if junction.attrib.get("id")
    }
    local_junction_ids = {
        jid
        for jid, junction in junctions.items()
        if _junction_within_radius(junction, center=center, radius_m=radius_m)
    }
    local_edges: dict[str, ET.Element] = {}
    for edge in root.findall("edge"):
        edge_id = str(edge.attrib.get("id", ""))
        if not edge_id:
            continue
        if _edge_touches_context(edge, local_junction_ids, center=center, radius_m=radius_m):
            local_edges[edge_id] = edge
    local_edge_ids = set(local_edges)
    local_connections = [
        connection
        for connection in root.findall("connection")
        if connection.attrib.get("from", "") in local_edge_ids or connection.attrib.get("to", "") in local_edge_ids
    ]
    local_tls_ids = {
        str(jid)
        for jid in local_junction_ids
        if junctions.get(jid) is not None and junctions[jid].attrib.get("type") == "traffic_light"
    }
    local_tls_ids.update(
        str(connection.attrib.get("tl", ""))
        for connection in local_connections
        if connection.attrib.get("tl")
    )
    edge_function_counts = Counter(
        str(edge.attrib.get("function", "normal") or "normal") for edge in local_edges.values()
    )
    junction_type_counts = Counter(
        str(junctions[jid].attrib.get("type", "")) for jid in local_junction_ids if jid in junctions
    )
    crossing_elements = [
        crossing
        for crossing in root.findall("crossing")
        if str(crossing.attrib.get("node", "")) in local_junction_ids
        or any(edge_id in local_edge_ids for edge_id in str(crossing.attrib.get("edges", "")).split())
    ]
    local_tllogics = [
        tllogic
        for tllogic in root.findall("tlLogic")
        if str(tllogic.attrib.get("id", "")) in local_tls_ids
    ]
    return {
        "status": "pass",
        "junction_id": junction_id,
        "radius_m": radius_m,
        "junction_ids": sorted(local_junction_ids),
        "junction_count": len(local_junction_ids),
        "traffic_light_junction_count": sum(
            1 for jid in local_junction_ids if junctions[jid].attrib.get("type") == "traffic_light"
        ),
        "traffic_light_junction_ids": sorted(
            jid for jid in local_junction_ids if junctions[jid].attrib.get("type") == "traffic_light"
        ),
        "tl_logic_count": len(local_tllogics),
        "tl_logic_ids": sorted(str(tllogic.attrib.get("id", "")) for tllogic in local_tllogics),
        "edge_count": len(local_edges),
        "edge_function_counts": dict(sorted(edge_function_counts.items())),
        "normal_edge_count": edge_function_counts.get("normal", 0),
        "internal_edge_count": edge_function_counts.get("internal", 0),
        "walkingarea_edge_count": edge_function_counts.get("walkingarea", 0),
        "crossing_edge_count": edge_function_counts.get("crossing", 0),
        "crossing_element_count": len(crossing_elements),
        "connection_count": len(local_connections),
        "tls_controlled_connection_count": sum(1 for connection in local_connections if connection.attrib.get("tl")),
        "turnaround_connection_count": sum(
            1 for connection in local_connections if connection.attrib.get("dir") == TURNAROUND_DIR
        ),
        "junction_type_counts": dict(sorted(junction_type_counts.items())),
    }


def _context_count_delta(
    teacher_context: dict[str, object],
    candidate_context: dict[str, object],
) -> dict[str, int]:
    fields = (
        "junction_count",
        "traffic_light_junction_count",
        "tl_logic_count",
        "edge_count",
        "normal_edge_count",
        "internal_edge_count",
        "walkingarea_edge_count",
        "crossing_edge_count",
        "crossing_element_count",
        "connection_count",
        "tls_controlled_connection_count",
        "turnaround_connection_count",
    )
    return {
        field: _int_count(candidate_context.get(field, 0)) - _int_count(teacher_context.get(field, 0))
        for field in fields
    }




def _edge_touches_context(
    edge: ET.Element,
    local_junction_ids: set[str],
    *,
    center: tuple[float, float],
    radius_m: float,
) -> bool:
    if edge.attrib.get("from", "") in local_junction_ids or edge.attrib.get("to", "") in local_junction_ids:
        return True
    edge_id = str(edge.attrib.get("id", ""))
    if edge_id.startswith(":") and any(edge_id.startswith(f":{junction_id}_") for junction_id in local_junction_ids):
        return True
    for lane in edge.findall("lane"):
        for x, y in _shape_points(str(lane.attrib.get("shape", ""))):
            if math.hypot(x - center[0], y - center[1]) <= radius_m:
                return True
    return False






def run_teacher_guided_repair_matrix(
    *,
    queue_report: dict[str, Any],
    target_junction_ids: list[str],
    raw_node_file: Path,
    raw_edge_file: Path,
    raw_connection_file: Path,
    output_dir: Path,
    prefix: str = "teacher_guided_probe_matrix",
    queue_base_dir: Path | None = None,
    raw_type_file: Path | None = None,
    raw_tllogic_file: Path | None = None,
    crossing_edge_overrides_by_junction: dict[str, dict[str, str | list[str]]] | None = None,
    replay_target_internal_subgraph: bool = True,
    netconvert_binary: str = "netconvert",
    sumo_binary: str = "sumo",
    timeout_seconds: float = 240.0,
    command_runner: Any = run_command,
    repair_queue_runner: Any = run_teacher_guided_repair_queue,
    sequential_accept_passed_variants: bool = False,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = queue_report.get("repair_candidates", []) or []
    if not isinstance(candidates, list):
        return _failure("queue report repair_candidates must be a list")

    candidates_by_id: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in (str(candidate.get("reference_id", "")), str(candidate.get("junction_id", ""))):
            if key and key not in candidates_by_id:
                candidates_by_id[key] = candidate

    probes = []
    missing_junction_ids = []
    for index, junction_id in enumerate(target_junction_ids):
        candidate = candidates_by_id.get(str(junction_id))
        if candidate is None:
            missing_junction_ids.append(str(junction_id))
            continue
        probe_dir = output_dir / _queue_candidate_dir(index, str(junction_id))
        single_queue = dict(queue_report)
        single_queue["repair_candidates"] = [candidate]
        single_queue["repair_candidate_count"] = 1
        candidate_status = candidate.get("candidate_status")
        single_queue["ready_candidate_count"] = 1 if candidate_status == "ready_for_teacher_guided_variant" else 0
        single_queue["expanded_scope_candidate_count"] = (
            1 if candidate_status == "needs_expanded_rebuild_scope" else 0
        )
        single_queue["blocked_candidate_count"] = (
            0 if single_queue["ready_candidate_count"] or single_queue["expanded_scope_candidate_count"] else 1
        )
        single_queue_file = probe_dir / "single_queue.json"
        probe_dir.mkdir(parents=True, exist_ok=True)
        single_queue["queue_file"] = str(single_queue_file)
        single_queue_file.write_text(json.dumps(single_queue, indent=2, ensure_ascii=False), encoding="utf-8")
        run_report = repair_queue_runner(
            queue_report=single_queue,
            raw_node_file=raw_node_file,
            raw_edge_file=raw_edge_file,
            raw_connection_file=raw_connection_file,
            raw_type_file=raw_type_file,
            raw_tllogic_file=raw_tllogic_file,
            crossing_edge_overrides_by_junction=crossing_edge_overrides_by_junction,
            output_dir=probe_dir,
            prefix=f"{prefix}_{index + 1:03d}",
            queue_base_dir=queue_base_dir,
            replay_target_internal_subgraph=replay_target_internal_subgraph,
            max_ready_candidates=1,
            netconvert_binary=netconvert_binary,
            sumo_binary=sumo_binary,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
            sequential_accept_passed_variants=sequential_accept_passed_variants,
        )
        road_continuity_summary = _road_continuity_probe_summary(run_report)
        probes.append(
            {
                "junction_id": str(junction_id),
                "status": str(run_report.get("status", "")),
                "parity_gate_status": str(run_report.get("parity_gate_status", "")),
                "promotion_gate_status": str(run_report.get("promotion_gate_status", "")),
                "approach_integrity_status": str(run_report.get("approach_integrity_status", "")),
                "context_gate_status": str(run_report.get("context_gate_status", "")),
                **road_continuity_summary,
                "semantic_failure_counts": run_report.get("semantic_failure_counts", {})
                if isinstance(run_report.get("semantic_failure_counts"), dict)
                else {},
                "semantic_layer_gate_counts": run_report.get("semantic_layer_gate_counts", {})
                if isinstance(run_report.get("semantic_layer_gate_counts"), dict)
                else {},
                "best_expanded_scope_net_file": str(run_report.get("best_expanded_scope_net_file", "")),
                "composite_applied_candidate_count": run_report.get("composite_applied_candidate_count", 0),
                "composite_net_file": str(run_report.get("composite_net_file", "")),
                "run_report_file": str(run_report.get("run_report_file", "")),
                "single_queue_file": str(single_queue_file),
            }
        )

    all_parity_pass = bool(probes) and all(probe["parity_gate_status"] == "pass" for probe in probes)
    all_promotion_pass = bool(probes) and all(probe["promotion_gate_status"] == "pass" for probe in probes)
    all_context_pass = bool(probes) and all(probe["context_gate_status"] != "fail" for probe in probes)
    all_road_continuity_pass = bool(probes) and all(
        probe["road_continuity_gate_status"] == "pass" for probe in probes
    )
    status = (
        "pass"
        if all_parity_pass
        and all_promotion_pass
        and all_context_pass
        and all_road_continuity_pass
        and not missing_junction_ids
        else "fail"
    )
    matrix_file = output_dir / f"{prefix}.json"
    report = {
        "status": status,
        "claim_status": "diagnostic-demo",
        "requested_junction_count": len(target_junction_ids),
        "probe_count": len(probes),
        "missing_junction_ids": missing_junction_ids,
        "all_parity_gate_pass": all_parity_pass,
        "all_promotion_gate_pass": all_promotion_pass,
        "all_context_gate_pass": all_context_pass,
        "all_road_continuity_gate_pass": all_road_continuity_pass,
        "matrix_file": str(matrix_file),
        "probes": probes,
        "review_policy": "probe matrix only; promote to workflow evidence after full OSM workflow replay uses the same gate",
    }
    matrix_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report






def _write_replay_node_file(node_file: Path, join_patch_file: Path, output_file: Path) -> Path:
    if not join_patch_file.is_file():
        return node_file
    node_root = ET.parse(node_file).getroot()
    join_root = ET.parse(join_patch_file).getroot()
    joins = [copy.deepcopy(join) for join in join_root.findall("join")]
    if not joins:
        return node_file
    stale_joined_node_ids = _join_patch_joined_node_ids(join_patch_file)
    for node in list(node_root.findall("node")):
        if node.attrib.get("id") in stale_joined_node_ids:
            node_root.remove(node)
    for join in joins:
        node_root.append(join)
    ET.indent(node_root, space="    ")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(node_root).write(output_file, encoding="utf-8", xml_declaration=True)
    return output_file


def _join_patch_joined_node_ids(join_patch_file: Path) -> set[str]:
    try:
        join_root = ET.parse(join_patch_file).getroot()
    except (ET.ParseError, OSError):
        return set()
    joined_node_ids = set()
    for join in join_root.findall("join"):
        node_ids = [node_id for node_id in join.attrib.get("nodes", "").split() if node_id]
        if len(node_ids) >= 2:
            joined_node_ids.add(_sumo_joined_cluster_id(node_ids))
    return joined_node_ids








def _joined_endpoint_self_loop_edge_ids(
    edge_file: Path,
    join_patch_file: Path,
    joined_junction_id: object,
) -> tuple[list[str], list[str]]:
    if not join_patch_file.is_file() or not _normalize_joined_junction_ids(joined_junction_id):
        return [], []
    source_node_ids = _joined_source_node_ids(join_patch_file, joined_junction_id)
    if not source_node_ids:
        return [], []
    dropped_self_loop_edges = []
    blocking_self_loop_edge_drops = []
    edge_root = ET.parse(edge_file).getroot()
    for edge in edge_root.findall("edge"):
        from_is_join_source = edge.attrib.get("from", "") in source_node_ids
        to_is_join_source = edge.attrib.get("to", "") in source_node_ids
        if from_is_join_source and to_is_join_source:
            edge_id = edge.attrib.get("id", "")
            dropped_self_loop_edges.append(edge_id)
            if _edge_drop_requires_review(edge):
                blocking_self_loop_edge_drops.append(edge_id)
    return dropped_self_loop_edges, blocking_self_loop_edge_drops


def _write_joined_endpoint_edge_file(
    edge_file: Path,
    join_patch_file: Path,
    joined_junction_id: object,
    output_file: Path,
    *,
    rewrite_endpoints: bool = False,
) -> tuple[Path, int, list[str], list[str]]:
    if not join_patch_file.is_file() or not _normalize_joined_junction_ids(joined_junction_id):
        return edge_file, 0, [], []
    source_node_ids = _joined_source_node_ids(join_patch_file, joined_junction_id)
    if not source_node_ids:
        return edge_file, 0, [], []
    endpoint_rewrites = _join_patch_endpoint_rewrites(join_patch_file) if rewrite_endpoints else {}

    edge_root = ET.parse(edge_file).getroot()
    rewrite_count = 0
    dropped_self_loop_edges = []
    blocking_self_loop_edge_drops = []
    for edge in list(edge_root.findall("edge")):
        from_is_join_source = edge.attrib.get("from", "") in source_node_ids
        to_is_join_source = edge.attrib.get("to", "") in source_node_ids
        if from_is_join_source and to_is_join_source:
            edge_id = edge.attrib.get("id", "")
            dropped_self_loop_edges.append(edge_id)
            if _edge_drop_requires_review(edge):
                blocking_self_loop_edge_drops.append(edge_id)
            edge_root.remove(edge)
            continue
        if rewrite_endpoints:
            old_from = edge.attrib.get("from", "")
            old_to = edge.attrib.get("to", "")
            new_from = endpoint_rewrites.get(old_from, old_from)
            new_to = endpoint_rewrites.get(old_to, old_to)
            if new_from != old_from:
                edge.set("from", new_from)
                rewrite_count += 1
            if new_to != old_to:
                edge.set("to", new_to)
                rewrite_count += 1
        # With the default mode netconvert applies the <join> patch after
        # reading node ids.  Teacher replay inputs can opt into explicit
        # endpoint rewriting above.
    if rewrite_count == 0 and not dropped_self_loop_edges:
        return edge_file, 0, [], []

    ET.indent(edge_root, space="    ")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(edge_root).write(output_file, encoding="utf-8", xml_declaration=True)
    return output_file, rewrite_count, dropped_self_loop_edges, blocking_self_loop_edge_drops


def _write_joined_endpoint_connection_file(
    connection_file: Path,
    join_patch_file: Path,
    output_file: Path,
) -> tuple[Path, int]:
    if not join_patch_file.is_file():
        return connection_file, 0
    endpoint_rewrites = _join_patch_endpoint_rewrites(join_patch_file)
    try:
        connection_root = ET.parse(connection_file).getroot()
    except (ET.ParseError, OSError):
        return connection_file, 0
    rewrite_count = 0
    sanitized_crossing_count = 0
    for crossing in connection_root.findall("crossing"):
        old_node = crossing.attrib.get("node", "")
        new_node = endpoint_rewrites.get(old_node, old_node)
        if new_node != old_node:
            crossing.set("node", new_node)
            rewrite_count += 1
        # netconvert plain-output can emit non-finite outlineShape values for
        # crossings.  They are not valid SUMO XML geometry and can abort a
        # later full-network join replay.  Dropping only that optional
        # geometry keeps the crossing semantics and lets SUMO rebuild it.
        for attr in ("outlineShape", "shape"):
            value = crossing.attrib.get(attr, "")
            if value and any(token in value.lower() for token in ("nan", "inf")):
                crossing.attrib.pop(attr, None)
                sanitized_crossing_count += 1
    if not rewrite_count and not sanitized_crossing_count:
        return connection_file, 0
    ET.indent(connection_root, space="    ")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(connection_root).write(output_file, encoding="utf-8", xml_declaration=True)
    return output_file, rewrite_count








def _join_internal_self_loop_drop_has_witness(
    edge_id: str,
    dropped_edge_ids: list[str],
    surviving_edge_ids: set[str],
) -> bool:
    if _opposite_direction_edge_id(edge_id) in set(dropped_edge_ids):
        return True
    edge_family = _edge_family_id(edge_id)
    return any(_edge_family_id(surviving_edge_id) == edge_family for surviving_edge_id in surviving_edge_ids)














def _join_patch_endpoint_rewrites(join_patch_file: Path) -> dict[str, str]:
    try:
        joins = ET.parse(join_patch_file).getroot().findall("join")
    except (ET.ParseError, OSError):
        return {}
    rewrites: dict[str, str] = {}
    for join in joins:
        node_ids = [node_id for node_id in join.attrib.get("nodes", "").split() if node_id]
        joined_id = _sumo_joined_cluster_id(node_ids)
        if len(node_ids) < 2 or not joined_id:
            continue
        for node_id in node_ids:
            rewrites[node_id] = joined_id
    return rewrites


def _joined_source_node_ids(node_file: Path, junction_id: object) -> set[str]:
    target_junction_ids = _normalize_joined_junction_ids(junction_id)
    if not target_junction_ids:
        return set()
    source_node_ids: set[str] = set()
    for join in ET.parse(node_file).getroot().findall("join"):
        node_ids = [node_id for node_id in join.attrib.get("nodes", "").split() if node_id]
        if _sumo_joined_cluster_id(node_ids) in target_junction_ids:
            source_node_ids.update(node_ids)
    return source_node_ids






def _expanded_scope_followup_candidate_for_unsafe_internal_replay(
    candidate: dict[str, Any],
    variant_report: dict[str, object],
    raw_edge_file: Path,
    *,
    junction_id: str,
) -> dict[str, object] | None:
    followup_depth = int(candidate.get("followup_depth", 0) or 0)
    if followup_depth >= 1:
        return None
    replay = variant_report.get("target_internal_replay")
    if not isinstance(replay, dict):
        return None
    removed_count = int(replay.get("removed_stale_replaced_edge_connection_count", 0) or 0)
    if not removed_count:
        return None
    removed_connections = [
        connection
        for connection in replay.get("removed_stale_replaced_edge_connections", []) or []
        if isinstance(connection, dict)
    ]
    removed_edge_ids = sorted(
        {
            str(connection.get(field, ""))
            for connection in removed_connections
            for field in ("from", "to")
            if str(connection.get(field, "")) and not str(connection.get(field, "")).startswith(":")
        }
    )
    endpoints_by_edge = _plain_edge_endpoints(raw_edge_file)
    raw_endpoint_ids = {endpoint for endpoints in endpoints_by_edge.values() for endpoint in endpoints if endpoint}
    matched_candidate_node_ids = {
        str(item)
        for item in candidate.get("matched_candidate_node_ids", []) or []
        if str(item)
    }
    junction_ids = set(matched_candidate_node_ids)
    join_junction_ids = set(matched_candidate_node_ids)
    existing_scope = candidate.get("expanded_rebuild_scope", {})
    if isinstance(existing_scope, dict):
        junction_ids.update(str(item) for item in existing_scope.get("junction_ids", []) or [] if str(item))
        join_junction_ids.update(str(item) for item in existing_scope.get("join_junction_ids", []) or [] if str(item))
        missing_desired_endpoint_ids = sorted(
            {str(item) for item in existing_scope.get("missing_desired_endpoint_ids", []) or [] if str(item)}
        )
    else:
        missing_desired_endpoint_ids = []
    if junction_id and (not raw_endpoint_ids or junction_id in raw_endpoint_ids):
        junction_ids.add(junction_id)
        join_junction_ids.add(junction_id)
    for edge_id in removed_edge_ids:
        junction_ids.update(endpoint for endpoint in endpoints_by_edge.get(edge_id, ()) if endpoint)
    edge_map = _valid_edge_map(candidate.get("edge_map", {}))
    blocked_teacher_edge_ids = sorted(
        teacher_edge_id for teacher_edge_id, candidate_edge_id in edge_map.items() if candidate_edge_id in removed_edge_ids
    )
    followup = copy.deepcopy(candidate)
    followup.update(
        {
            "candidate_status": "needs_expanded_rebuild_scope",
            "followup_reason": "target_internal_replay_removed_non_target_connections",
            "followup_depth": followup_depth + 1,
            "unsafe_removed_connection_count": removed_count,
            "unsafe_removed_connections": removed_connections,
            "unsafe_removed_edge_ids": removed_edge_ids,
            "expanded_rebuild_scope": {
                "status": "review",
                "recommended_action": "rebuild_plain_xml_scope",
                "core_junction_id": junction_id,
                "junction_ids": sorted(junction_ids),
                "join_junction_ids": sorted(join_junction_ids),
                "blocked_teacher_edge_ids": blocked_teacher_edge_ids,
                "missing_desired_endpoint_ids": missing_desired_endpoint_ids,
                "reason": "target internal replay removed non-target boundary connections; rebuild expanded scope before movement replay",
            },
        }
    )
    return followup






def _augment_candidate_edge_map_from_tls_approach_pairs(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    pair_map: dict[str, str] = {}
    for pair in candidate.get("tls_approach_pairs", []) or []:
        if not isinstance(pair, dict):
            continue
        teacher_edge_id = str(pair.get("reference_edge_id", ""))
        candidate_edge_id = str(pair.get("candidate_edge_id", ""))
        if teacher_edge_id and candidate_edge_id:
            pair_map[teacher_edge_id] = candidate_edge_id
    existing = _valid_edge_map(candidate.get("edge_map", {}))
    merged = {**existing, **pair_map}
    return {
        **candidate,
        "edge_map": dict(sorted(merged.items())),
        "tls_approach_edge_map_evidence": {
            "status": "pass" if pair_map else "review",
            "pair_edge_map": dict(sorted(pair_map.items())),
            "added_or_overridden_count": sum(
                1 for key, value in pair_map.items() if existing.get(key) != value
            ),
            "reason": "bearing-matched TLS approach evidence applied to full controller-cell variant",
        },
    }


















def _teacher_guided_case_sort_key(
    case: dict[str, Any],
    pattern_records: dict[str, dict[str, Any]] | None = None,
    pattern_templates: dict[str, dict[str, Any]] | None = None,
) -> tuple[int, int, int, str]:
    template_count = _teacher_template_count_for_case(case, pattern_records or {}, pattern_templates or {})
    candidate_nodes = case.get("matched_candidate_node_ids")
    candidate_node_count = len(candidate_nodes) if isinstance(candidate_nodes, list) else 1_000_000
    reference_id = str(case.get("reference_id", ""))
    reference_node_count = len(reference_id.removeprefix("cluster_").split("_")) if reference_id else 1_000_000
    return (-template_count, candidate_node_count, reference_node_count, reference_id)






def _tls_repair_candidates(reference_join_audit_report: dict[str, Any]) -> list[dict[str, object]]:
    candidates = []
    for entry in reference_join_audit_report.get("tls_control_review_queue", []) or []:
        if not isinstance(entry, dict):
            continue
        repair_category = str(entry.get("repair_category", "tls_controller_cardinality_repair"))
        candidates.append(
            {
                **entry,
                "candidate_status": "needs_tls_semantic_repair",
                "repair_category": repair_category,
                "netedit_review_actions": _tls_repair_actions(repair_category),
                "tls_review_index": len(candidates),
            }
        )
    return candidates










def _case_boundary_edge_map(
    case: dict[str, Any],
    candidate_edges_by_id: dict[str, ET.Element],
) -> dict[str, str]:
    teacher_edge_ids = [
        str(edge_id)
        for edge_id in [
            *(case.get("reference_approach_edge_ids") or []),
            *(case.get("matched_reference_source_boundary_edge_ids") or []),
        ]
        if str(edge_id)
    ]
    candidate_edge_ids = [
        str(edge_id)
        for edge_id in case.get("matched_candidate_boundary_edge_ids") or []
        if str(edge_id) in candidate_edges_by_id
    ]
    candidates_by_family: dict[str, list[str]] = {}
    for edge_id in candidate_edge_ids:
        candidates_by_family.setdefault(_signed_edge_family_id(edge_id), []).append(edge_id)

    edge_map = {}
    for teacher_edge_id in teacher_edge_ids:
        if teacher_edge_id in candidate_edge_ids:
            edge_map[teacher_edge_id] = teacher_edge_id
            continue
        matches = sorted(set(candidates_by_family.get(_signed_edge_family_id(teacher_edge_id), [])))
        if len(matches) == 1:
            edge_map[teacher_edge_id] = matches[0]
    return dict(sorted(edge_map.items()))










def _same_id_pattern_cases(
    pattern_deltas: dict[str, dict[str, Any]],
    matched_cases: list[dict[str, Any]],
    teacher_root: ET.Element,
    candidate_root: ET.Element,
) -> list[dict[str, Any]]:
    covered_ids = {
        key
        for case in matched_cases
        for key in _junction_pattern_delta_keys(case)
    }
    teacher_junction_ids = _real_junction_ids(teacher_root)
    candidate_junction_ids = _real_junction_ids(candidate_root)
    cases = []
    for junction_id, delta in sorted(pattern_deltas.items()):
        if delta.get("status") == "pass" or junction_id in covered_ids:
            continue
        if junction_id not in teacher_junction_ids or junction_id not in candidate_junction_ids:
            continue
        cases.append(
            {
                "reference_id": junction_id,
                "reference_joined_source_nodes": [],
                "matched_reference_source_node_ids": [],
                "matched_candidate_node_ids": [junction_id],
                "learned_rule_basis": "same_id_junction_pattern",
                "learned_rule": "tum_like_same_id_pattern_candidate",
            }
        )
    return cases


def _same_id_tls_mismatch_cases(
    matched_cases: list[dict[str, Any]],
    teacher_root: ET.Element,
    candidate_root: ET.Element,
    teacher_net_file: Path,
    candidate_net_file: Path,
) -> list[dict[str, Any]]:
    covered_ids = {key for case in matched_cases for key in _junction_pattern_delta_keys(case)}
    candidate_junctions = {
        junction.attrib["id"]: junction
        for junction in candidate_root.findall("junction")
        if junction.attrib.get("id") and not junction.attrib["id"].startswith(":")
    }
    cases = []
    for junction in teacher_root.findall("junction"):
        reference_id = junction.attrib.get("id", "")
        candidate_junction = candidate_junctions.get(reference_id)
        if (
            not reference_id
            or reference_id.startswith(":")
            or reference_id in covered_ids
            or candidate_junction is None
            or not _teacher_junction_has_tls(teacher_root, reference_id, junction)
        ):
            continue
        if _same_id_tls_matches_teacher(
            teacher_root,
            candidate_root,
            teacher_net_file,
            candidate_net_file,
            reference_id,
            candidate_junction,
        ):
            continue
        cases.append(
            {
                "reference_id": reference_id,
                "reference_joined_source_nodes": [],
                "matched_reference_source_node_ids": [],
                "matched_candidate_node_ids": [reference_id],
                "learned_rule_basis": "same_id_tls_semantic_mismatch",
                "learned_rule": "tum_like_same_id_tls_candidate",
            }
        )
    return cases




def _topology_fragmented_tls_cases(
    matched_cases: list[dict[str, Any]],
    teacher_root: ET.Element,
    candidate_root: ET.Element,
    teacher_net_file: Path,
    candidate_edges_by_id: dict[str, ET.Element],
) -> list[dict[str, Any]]:
    covered_ids = {key for case in matched_cases for key in _junction_pattern_delta_keys(case)}
    candidate_junction_ids = _real_junction_ids(candidate_root)
    cases = []
    for junction in teacher_root.findall("junction"):
        reference_id = junction.attrib.get("id", "")
        if (
            not reference_id
            or reference_id.startswith(":")
            or reference_id in covered_ids
            or reference_id in candidate_junction_ids
            or not _teacher_junction_has_tls(teacher_root, reference_id, junction)
        ):
            continue
        try:
            teacher_model = _extract_teacher_junction_model(teacher_root, teacher_net_file, reference_id)
        except (ET.ParseError, OSError, KeyError, TypeError, ValueError):
            continue
        candidate_node_ids, edge_map = _candidate_nodes_from_exact_teacher_approach_edges(
            teacher_model,
            candidate_edges_by_id,
            candidate_junction_ids,
        )
        if len(candidate_node_ids) < 2:
            continue
        cases.append(
            {
                "reference_id": reference_id,
                "matched_candidate_node_ids": candidate_node_ids,
                "join_all_candidate_node_ids": True,
                "edge_map": edge_map,
                "learned_rule_basis": "topology_fragmented_tls_approach_edges",
                "learned_rule": "tum_like_topology_fragmented_tls_candidate",
            }
        )
    return cases


def _topology_fragmented_non_tls_cases(
    matched_cases: list[dict[str, Any]],
    teacher_root: ET.Element,
    candidate_root: ET.Element,
    teacher_net_file: Path,
    candidate_edges_by_id: dict[str, ET.Element],
) -> list[dict[str, Any]]:
    covered_ids = {key for case in matched_cases for key in _junction_pattern_delta_keys(case)}
    candidate_junction_ids = _real_junction_ids(candidate_root)
    cases = []
    for junction in teacher_root.findall("junction"):
        reference_id = junction.attrib.get("id", "")
        if (
            not reference_id
            or not reference_id.startswith("cluster_")
            or reference_id in covered_ids
            or reference_id in candidate_junction_ids
            or _teacher_junction_has_tls(teacher_root, reference_id, junction)
        ):
            continue
        try:
            teacher_model = _extract_teacher_junction_model(teacher_root, teacher_net_file, reference_id)
        except (ET.ParseError, OSError, KeyError, TypeError, ValueError):
            continue
        candidate_node_ids, edge_map = _candidate_nodes_from_exact_teacher_approach_edges(
            teacher_model,
            candidate_edges_by_id,
            candidate_junction_ids,
        )
        if len(candidate_node_ids) < 2:
            continue
        cases.append(
            {
                "reference_id": reference_id,
                "matched_candidate_node_ids": candidate_node_ids,
                "join_all_candidate_node_ids": True,
                "edge_map": edge_map,
                "learned_rule_basis": "topology_fragmented_non_tls_approach_edges",
                "learned_rule": "tum_like_topology_fragmented_cluster_candidate",
            }
        )
    return cases


def _turnaround_only_lane_cases(
    matched_cases: list[dict[str, Any]],
    teacher_root: ET.Element,
    candidate_root: ET.Element,
) -> list[dict[str, Any]]:
    covered_ids = {key for case in matched_cases for key in _junction_pattern_delta_keys(case)}
    teacher_junction_ids = _real_junction_ids(teacher_root)
    candidate_junction_ids = _real_junction_ids(candidate_root)
    teacher_by_lane = _root_vehicle_outgoing_by_lane(teacher_root)
    candidate_by_lane = _root_vehicle_outgoing_by_lane(candidate_root)
    candidate_edges = {
        edge.attrib["id"]: edge
        for edge in candidate_root.findall("edge")
        if edge.attrib.get("id") and not edge.attrib["id"].startswith(":")
    }
    teacher_edges = {
        edge.attrib["id"]: edge
        for edge in teacher_root.findall("edge")
        if edge.attrib.get("id") and not edge.attrib["id"].startswith(":")
    }
    teacher_lane_keys_by_family: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for edge_id, from_lane in teacher_by_lane:
        teacher_lane_keys_by_family.setdefault((_signed_edge_family_id(edge_id), from_lane), []).append(
            (edge_id, from_lane)
        )
    cases: dict[str, dict[str, object]] = {}
    for (edge_id, from_lane), candidate_stats in candidate_by_lane.items():
        if candidate_stats["non_turnaround_count"] or not candidate_stats["turnaround_count"]:
            continue
        candidate_edge = candidate_edges.get(edge_id)
        junction_id = candidate_edge.attrib.get("to", "") if candidate_edge is not None else ""
        if (
            not junction_id
            or junction_id in covered_ids
            or junction_id not in candidate_junction_ids
        ):
            continue
        teacher_lane_keys = [(edge_id, from_lane)] if (edge_id, from_lane) in teacher_by_lane else []
        teacher_lane_keys.extend(
            key
            for key in teacher_lane_keys_by_family.get((_signed_edge_family_id(edge_id), from_lane), [])
            if key not in teacher_lane_keys
        )
        matched_teacher_edge_id = ""
        matched_teacher_stats: dict[str, object] | None = None
        for teacher_edge_id, teacher_from_lane in teacher_lane_keys:
            teacher_stats = teacher_by_lane.get((teacher_edge_id, teacher_from_lane))
            if not teacher_stats or not teacher_stats["non_turnaround_count"]:
                continue
            teacher_edge = teacher_edges.get(teacher_edge_id)
            if (
                teacher_edge is None
                or teacher_edge.attrib.get("to") != junction_id
                or teacher_edge.attrib.get("to") not in teacher_junction_ids
            ):
                continue
            matched_teacher_edge_id = teacher_edge_id
            matched_teacher_stats = teacher_stats
            break
        if not matched_teacher_edge_id or matched_teacher_stats is None:
            continue
        case = cases.setdefault(junction_id, {"source_lanes": set(), "edge_map": {}})
        source_lanes = case["source_lanes"]
        if isinstance(source_lanes, set):
            source_lanes.add(f"{edge_id}_{from_lane}")
        edge_map = case["edge_map"]
        if isinstance(edge_map, dict):
            edge_map[matched_teacher_edge_id] = edge_id
            for teacher_target in sorted(matched_teacher_stats["non_turnaround_targets"]):
                candidate_target_id, _candidate_target = _candidate_edge_by_exact_or_unsplit_id(
                    str(teacher_target),
                    candidate_edges,
                )
                if candidate_target_id:
                    edge_map[str(teacher_target)] = candidate_target_id
    return [
        {
            "reference_id": junction_id,
            "reference_joined_source_nodes": [],
            "matched_reference_source_node_ids": [],
            "matched_candidate_node_ids": [junction_id],
            "edge_map": dict(sorted(case_data["edge_map"].items()))
            if isinstance(case_data.get("edge_map"), dict)
            else {},
            "turnaround_only_source_lanes": sorted(case_data["source_lanes"])
            if isinstance(case_data.get("source_lanes"), set)
            else [],
            "learned_rule_basis": "turnaround_only_lane_gap",
            "learned_rule": "tum_like_turnaround_only_lane_candidate",
        }
        for junction_id, case_data in sorted(cases.items())
    ]












def _attach_junction_pattern_delta(
    candidate: dict[str, object],
    deltas: dict[str, dict[str, Any]],
) -> dict[str, object]:
    matches = [deltas[key] for key in _junction_pattern_delta_keys(candidate) if key in deltas]
    if not matches:
        return candidate
    mismatch_fields = list(
        dict.fromkeys(field for delta in matches for field in delta.get("mismatch_fields", []))
    )
    review_actions = list(
        dict.fromkeys(
            [str(item) for item in candidate.get("netedit_review_actions", []) or []]
            + _netedit_review_actions(mismatch_fields)
        )
    )
    return {
        **candidate,
        "junction_pattern_delta_count": len(matches),
        "junction_pattern_deltas": matches,
        "junction_pattern_mismatch_fields": mismatch_fields,
        "netedit_review_actions": review_actions,
        "review_priority": "high" if review_actions else str(candidate.get("review_priority", "normal") or "normal"),
    }






def _queue_candidate_dir(index: int, junction_id: str) -> str:
    return f"candidate_{index + 1:03d}_{_stable_digest(junction_id)}"




def _safe_stage_name(value: str, max_len: int = 64) -> str:
    safe = "".join(char if char.isascii() and (char.isalnum() or char in "._-") else "_" for char in value.strip())
    safe = safe.strip("._-")
    safe = safe or "candidate"
    if len(safe) <= max_len:
        return safe
    head_len = max(1, max_len - 9)
    return f"{safe[:head_len]}_{_stable_digest(safe)}"














def _teacher_guided_repair_candidate(
    *,
    case: dict[str, Any],
    teacher_net_file: Path,
    candidate_net_file: Path,
    teacher_root: ET.Element,
    candidate_root: ET.Element,
    teacher_edges: dict[str, ET.Element],
    candidate_edges_by_id: dict[str, ET.Element],
    candidate_edge_ids: set[str],
) -> dict[str, object]:
    reference_id = str(case.get("reference_id", ""))
    reference_source_node_ids = [str(item) for item in case.get("reference_joined_source_nodes") or []]
    matched_reference_source_node_ids = [str(item) for item in case.get("matched_reference_source_node_ids") or []]
    candidate_node_ids = [str(item) for item in case.get("matched_candidate_node_ids") or case.get("candidate_node_ids") or []]
    candidate_junction_ids = _candidate_junction_id_candidates(reference_id, candidate_node_ids)
    matched_source_node_set = set(matched_reference_source_node_ids or reference_source_node_ids)
    case_edge_map = {
        **_case_boundary_edge_map(case, candidate_edges_by_id),
        **_valid_edge_map(case.get("edge_map", {})),
    }
    case_edge_map = _prefer_existing_exact_edge_ids(case_edge_map, candidate_edges_by_id)
    scope_node_ids = [node_id for node_id in candidate_node_ids if node_id in matched_source_node_set]
    if len(scope_node_ids) < 2:
        scope_node_ids = candidate_node_ids
    unique_candidate_node_ids = list(dict.fromkeys(candidate_node_ids))
    join_all_candidate_node_ids = bool(case.get("join_all_candidate_node_ids")) or (
        str(case.get("learned_rule_basis", "")) == "spatial_cluster" and len(unique_candidate_node_ids) > 2
    )
    join_node_ids = (
        unique_candidate_node_ids
        if join_all_candidate_node_ids
        else _conservative_join_node_ids(candidate_node_ids, matched_source_node_set)
    )
    base = {
        "reference_id": reference_id,
        "junction_id": candidate_junction_ids[0] if candidate_junction_ids else reference_id,
        "reference_joined_source_nodes": reference_source_node_ids,
        "matched_reference_source_node_ids": matched_reference_source_node_ids,
        "matched_candidate_node_ids": candidate_node_ids,
        "learned_rule_basis": str(case.get("learned_rule_basis", "")),
        "learned_rule": str(case.get("learned_rule", "")),
    }
    if not reference_id:
        return {**base, "candidate_status": "invalid_reference_id", "edge_map": {}, "missing_teacher_edge_ids": []}

    try:
        teacher_model = _extract_teacher_junction_model(teacher_root, teacher_net_file, reference_id)
    except (ET.ParseError, OSError, KeyError, TypeError, ValueError) as exc:
        return {
            **base,
            "candidate_status": "teacher_model_failed",
            "edge_map": {},
            "missing_teacher_edge_ids": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    teacher_summary = teacher_model.get("summary", {}) if isinstance(teacher_model.get("summary"), dict) else {}
    if not any(
        int(teacher_summary.get(field, 0) or 0)
        for field in ("incoming_vehicle_edge_count", "outgoing_vehicle_edge_count", "vehicle_connection_count")
    ):
        return {
            **base,
            "candidate_status": "no_vehicle_reference_context",
            "edge_map": {},
            "missing_teacher_edge_ids": [],
            "pedestrian_connection_count": int(teacher_summary.get("pedestrian_connection_count", 0) or 0),
            "walkingarea_count": int(teacher_summary.get("walkingarea_count", 0) or 0),
        }
    candidate_model = None
    candidate_error = None
    candidate_junction_id = ""
    for candidate_id in candidate_junction_ids:
        try:
            candidate_model = _extract_teacher_junction_model(candidate_root, candidate_net_file, candidate_id)
            candidate_junction_id = candidate_id
            break
        except (ET.ParseError, OSError, KeyError, TypeError, ValueError) as exc:
            candidate_error = exc
    if candidate_model is None:
        missing_teacher_edge_ids = [
            edge_id for edge_id in _teacher_approach_edge_ids(teacher_model) if edge_id not in case_edge_map
        ]
        missing_endpoint_ids = (
            _missing_teacher_edge_endpoint_ids(teacher_edges, missing_teacher_edge_ids, reference_id)
            if case.get("reference_approach_edge_ids") or case.get("matched_reference_source_boundary_edge_ids")
            else []
        )
        if candidate_node_ids:
            return {
                **base,
                "candidate_status": "needs_expanded_rebuild_scope",
                "edge_map": case_edge_map,
                "missing_teacher_edge_ids": missing_teacher_edge_ids,
                "copyable_missing_teacher_edge_ids": [],
                "uncopyable_missing_teacher_edge_ids": missing_teacher_edge_ids,
                "approach_endpoint_rebuild_plan": {"status": "review", "edge_rebuilds": []},
                "expanded_rebuild_scope": {
                    "status": "review",
                    "recommended_action": "rebuild_plain_xml_scope",
                    "core_junction_id": base["junction_id"],
                    "junction_ids": sorted(dict.fromkeys([*scope_node_ids, *missing_endpoint_ids])),
                    "join_junction_ids": list(dict.fromkeys(join_node_ids)),
                    "blocked_teacher_edge_ids": missing_teacher_edge_ids,
                    "missing_desired_endpoint_ids": missing_endpoint_ids,
                    "reason": "candidate joined junction not found; rebuild from matched candidate source nodes",
                },
                "error": f"{type(candidate_error).__name__}: {candidate_error}",
            }
        return {
            **base,
            "candidate_status": "needs_joined_candidate_junction",
            "edge_map": case_edge_map,
            "missing_teacher_edge_ids": missing_teacher_edge_ids,
            "error": f"{type(candidate_error).__name__}: {candidate_error}",
        }

    provisional_edge_map = _teacher_candidate_edge_map(teacher_model, candidate_model, drop_endpoint_mismatches=False)
    approach_endpoint_rebuild_plan = _approach_endpoint_rebuild_plan(
        teacher_model,
        candidate_model,
        edge_map=provisional_edge_map,
        teacher_junction_id=reference_id,
        candidate_junction_id=candidate_junction_id,
        candidate_junction_ids={
            junction.attrib["id"]
            for junction in candidate_root.findall("junction")
            if junction.attrib.get("id")
        },
    )
    stale_case_edge_map = _stale_case_edge_map_entries(
        case_edge_map,
        teacher_model,
        candidate_model,
        provisional_edge_map,
    )
    edge_map = _teacher_candidate_edge_map(
        teacher_model,
        candidate_model,
        teacher_junction_id=reference_id,
        candidate_junction_id=candidate_junction_id,
    )
    edge_map = dict(sorted({**case_edge_map, **edge_map}.items()))
    missing = [edge_id for edge_id in _teacher_approach_edge_ids(teacher_model) if edge_id not in edge_map]
    copyable_missing = _copyable_missing_teacher_edge_ids(
        teacher_root.findall("connection"),
        teacher_edges,
        candidate_edges_by_id,
        teacher_junction_id=reference_id,
        candidate_junction_id=candidate_junction_id,
        edge_map=edge_map,
    )
    uncopyable_missing = [edge_id for edge_id in missing if edge_id not in set(copyable_missing)]
    movement_exemplar = extract_junction_pattern_exemplar(teacher_net_file, reference_id)
    expanded_rebuild_scope = _expanded_rebuild_scope(
        candidate_junction_id,
        approach_endpoint_rebuild_plan,
        blocked_teacher_edge_ids=uncopyable_missing,
        fallback_junction_ids=scope_node_ids,
    )
    if stale_case_edge_map:
        stale_endpoint_ids = sorted(
            {
                endpoint
                for edge_id in stale_case_edge_map.values()
                if (edge := candidate_edges_by_id.get(edge_id)) is not None
                for endpoint in (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
                if endpoint and endpoint != candidate_junction_id
            }
        )
        existing_scope = case.get("expanded_rebuild_scope", {})
        if isinstance(existing_scope, dict) and existing_scope:
            existing_junction_ids = [
                str(item) for item in existing_scope.get("junction_ids", []) or [] if str(item)
            ]
            existing_join_junction_ids = [
                str(item) for item in existing_scope.get("join_junction_ids", []) or [] if str(item)
            ]
            expanded_rebuild_scope = {
                **existing_scope,
                "status": "review",
                "junction_ids": sorted(dict.fromkeys([candidate_junction_id, *existing_junction_ids])),
                "join_junction_ids": sorted(dict.fromkeys([candidate_junction_id, *existing_join_junction_ids])),
                "reason": "case edge map points outside candidate junction approaches",
                "stale_case_edge_map_ids": stale_case_edge_map,
            }
        else:
            expanded_rebuild_scope = {
                "status": "review",
                "recommended_action": "rebuild_plain_xml_scope",
                "core_junction_id": candidate_junction_id,
                "junction_ids": sorted(dict.fromkeys([candidate_junction_id, *scope_node_ids, *stale_endpoint_ids])),
                "join_junction_ids": list(dict.fromkeys(join_node_ids or [candidate_junction_id])),
                "blocked_teacher_edge_ids": sorted(stale_case_edge_map),
                "missing_desired_endpoint_ids": [],
                "reason": "case edge map points outside candidate junction approaches",
                "stale_case_edge_map_ids": stale_case_edge_map,
            }
    if str(case.get("learned_rule", "")) == "tum_like_turnaround_only_lane_candidate" and missing:
        missing_endpoint_ids = sorted(
            {
                endpoint
                for edge_id in missing
                if (edge := teacher_edges.get(edge_id)) is not None
                for endpoint in (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
                if endpoint and endpoint != reference_id
            }
        )
        expanded_rebuild_scope = {
            "status": "review",
            "recommended_action": "rebuild_plain_xml_scope",
            "core_junction_id": candidate_junction_id,
            "junction_ids": sorted({candidate_junction_id, *missing_endpoint_ids}) if candidate_junction_id else missing_endpoint_ids,
            "join_junction_ids": [candidate_junction_id] if candidate_junction_id else [],
            "blocked_teacher_edge_ids": missing,
            "missing_desired_endpoint_ids": missing_endpoint_ids,
            "reason": "turnaround-only lane is missing a normal teacher movement target edge",
        }
    candidate_status = "ready_for_teacher_guided_variant"
    if expanded_rebuild_scope["status"] == "review":
        candidate_status = "needs_expanded_rebuild_scope"
    elif uncopyable_missing:
        candidate_status = "edge_map_incomplete"
    teacher_parity = _teacher_parity_summary(teacher_model)
    candidate_parity = _teacher_parity_summary(candidate_model)
    missing_teacher_movement_plan = _missing_teacher_movement_plan(
        teacher_model,
        candidate_model,
        edge_map=edge_map,
        teacher_junction_id=reference_id,
        candidate_junction_id=candidate_junction_id,
    )
    turnaround_only_lane_gaps = _turnaround_only_lane_gaps(
        teacher_model,
        candidate_model,
        edge_map=edge_map,
    )
    movement_matrix_missing_count = max(
        0,
        int(candidate_parity.get("vehicle_movement_matrix_missing_count", 0) or 0)
        - int(teacher_parity.get("vehicle_movement_matrix_missing_count", 0) or 0),
        len(missing_teacher_movement_plan),
        len(turnaround_only_lane_gaps),
    )
    review_actions = ["rebuild_vehicle_movement_matrix"] if movement_matrix_missing_count else []
    return {
        **base,
        "junction_id": candidate_junction_id,
        "candidate_status": candidate_status,
        "edge_map": edge_map,
        "slot_edge_map": slot_edge_map_from_exemplar(movement_exemplar, edge_map),
        "movement_exemplar": movement_exemplar,
        "approach_endpoint_rebuild_plan": approach_endpoint_rebuild_plan,
        "expanded_rebuild_scope": expanded_rebuild_scope,
        "stale_case_edge_map_ids": stale_case_edge_map,
        "missing_teacher_edge_ids": missing,
        "copyable_missing_teacher_edge_ids": copyable_missing,
        "uncopyable_missing_teacher_edge_ids": uncopyable_missing,
        "vehicle_movement_matrix_missing_count": movement_matrix_missing_count,
        "missing_teacher_movement_plan_count": len(missing_teacher_movement_plan),
        "missing_teacher_movement_plan": missing_teacher_movement_plan,
        "turnaround_only_lane_gap_count": len(turnaround_only_lane_gaps),
        "turnaround_only_lane_gaps": turnaround_only_lane_gaps,
        "netedit_review_actions": review_actions,
        "review_priority": "high" if review_actions else "normal",
        "teacher_incoming_edge_count": len(_approach_edges(teacher_model, "incoming")),
        "teacher_outgoing_edge_count": len(_approach_edges(teacher_model, "outgoing")),
        "candidate_incoming_edge_count": len(_approach_edges(candidate_model, "incoming")),
        "candidate_outgoing_edge_count": len(_approach_edges(candidate_model, "outgoing")),
    }


def _candidate_junction_id_candidates(reference_id: str, node_ids: list[str]) -> list[str]:
    candidates = [reference_id] if reference_id else []
    joined_id = _sumo_joined_cluster_id(node_ids)
    if joined_id and joined_id not in candidates:
        candidates.append(joined_id)
    return candidates










def _teacher_candidate_edge_map(
    teacher_model: dict[str, object],
    candidate_model: dict[str, object],
    *,
    teacher_junction_id: str = "",
    candidate_junction_id: str = "",
    drop_endpoint_mismatches: bool = True,
    max_bearing_delta: float = 30.0,
) -> dict[str, str]:
    edge_map: dict[str, str] = {}
    for direction in ("incoming", "outgoing"):
        edge_map.update(
            match_teacher_approaches(
                _approaches(teacher_model, direction),
                _approaches(candidate_model, direction),
                max_bearing_delta=max_bearing_delta,
            )
        )
    if drop_endpoint_mismatches and teacher_junction_id and candidate_junction_id:
        edge_map = _drop_endpoint_mismatched_edge_map_entries(
            teacher_model,
            candidate_model,
            edge_map,
            teacher_junction_id=teacher_junction_id,
            candidate_junction_id=candidate_junction_id,
        )
    return dict(sorted((source, target) for source, target in edge_map.items() if source and target))






def _teacher_approach_edge_ids(teacher_model: dict[str, object]) -> list[str]:
    return sorted(dict.fromkeys(_approach_edges(teacher_model, "incoming") + _approach_edges(teacher_model, "outgoing")))


def _copyable_missing_teacher_edge_ids(
    teacher_connections: list[ET.Element],
    teacher_edges: dict[str, ET.Element],
    candidate_edges_by_id: dict[str, ET.Element],
    *,
    teacher_junction_id: str,
    candidate_junction_id: str,
    edge_map: dict[str, str],
) -> list[str]:
    return _needed_unmapped_teacher_boundary_edges(
        teacher_connections,
        teacher_edges,
        edge_map,
        candidate_edges_by_id,
        f":{teacher_junction_id}_",
        teacher_junction_id,
        candidate_junction_id,
        0.0,
        0.0,
        compare_lane_shapes=False,
        replay_existing_edges=False,
    )




def _turnaround_only_lane_gaps(
    teacher_model: dict[str, object],
    candidate_model: dict[str, object],
    *,
    edge_map: dict[str, str],
) -> list[dict[str, object]]:
    teacher_by_lane = _vehicle_outgoing_by_lane(teacher_model)
    candidate_by_lane = _vehicle_outgoing_by_lane(candidate_model)
    teacher_by_candidate_edge = {candidate: teacher for teacher, candidate in edge_map.items()}
    gaps = []
    for (candidate_edge_id, from_lane), candidate_stats in sorted(candidate_by_lane.items()):
        if candidate_stats["non_turnaround_count"]:
            continue
        if not candidate_stats["turnaround_count"]:
            continue
        teacher_edge_id = teacher_by_candidate_edge.get(candidate_edge_id)
        if not teacher_edge_id and (candidate_edge_id, from_lane) in teacher_by_lane:
            teacher_edge_id = candidate_edge_id
        if not teacher_edge_id:
            continue
        teacher_stats = teacher_by_lane.get((teacher_edge_id, from_lane))
        if not teacher_stats or not teacher_stats["non_turnaround_count"]:
            continue
        gaps.append(
            {
                "teacher_from_edge_id": teacher_edge_id,
                "from_edge_id": candidate_edge_id,
                "fromLane": from_lane,
                "candidate_turnaround_outgoing_count": candidate_stats["turnaround_count"],
                "candidate_non_turnaround_outgoing_count": candidate_stats["non_turnaround_count"],
                "teacher_turnaround_outgoing_count": teacher_stats["turnaround_count"],
                "teacher_non_turnaround_outgoing_count": teacher_stats["non_turnaround_count"],
                "teacher_non_turnaround_targets": sorted(teacher_stats["non_turnaround_targets"]),
                "match_status": "candidate_turnaround_only_teacher_has_normal_vehicle_movement",
            }
        )
    return gaps


def _vehicle_outgoing_by_lane(model: dict[str, object]) -> dict[tuple[str, str], dict[str, object]]:
    by_lane: dict[tuple[str, str], dict[str, object]] = {}
    for connection in model.get("vehicle_connections", []) or []:
        if not isinstance(connection, dict):
            continue
        source = str(connection.get("from", ""))
        if not source:
            continue
        lane = str(connection.get("fromLane", ""))
        stats = by_lane.setdefault(
            (source, lane),
            {
                "turnaround_count": 0,
                "non_turnaround_count": 0,
                "non_turnaround_targets": set(),
            },
        )
        if _is_turnaround_connection(connection):
            stats["turnaround_count"] = int(stats["turnaround_count"]) + 1
        else:
            stats["non_turnaround_count"] = int(stats["non_turnaround_count"]) + 1
            target = str(connection.get("to", ""))
            if target:
                stats["non_turnaround_targets"].add(target)
    return by_lane


def _root_vehicle_outgoing_by_lane(root: ET.Element) -> dict[tuple[str, str], dict[str, object]]:
    edges = {
        edge.attrib["id"]: edge
        for edge in root.findall("edge")
        if edge.attrib.get("id") and not edge.attrib["id"].startswith(":")
    }
    by_lane: dict[tuple[str, str], dict[str, object]] = {}
    for connection in root.findall("connection"):
        source = connection.attrib.get("from", "")
        target = connection.attrib.get("to", "")
        if source not in edges or target not in edges:
            continue
        if _edge_is_pedestrian_only(edges[source]) or _edge_is_pedestrian_only(edges[target]):
            continue
        lane = connection.attrib.get("fromLane", "")
        stats = by_lane.setdefault(
            (source, lane),
            {"turnaround_count": 0, "non_turnaround_count": 0, "non_turnaround_targets": set()},
        )
        if _is_turnaround_connection(connection.attrib):
            stats["turnaround_count"] = int(stats["turnaround_count"]) + 1
        else:
            stats["non_turnaround_count"] = int(stats["non_turnaround_count"]) + 1
            stats["non_turnaround_targets"].add(target)
    return by_lane
















def _edge_is_vehicle_continuation_candidate(edge: ET.Element) -> bool:
    if edge.attrib.get("function") in {"internal", "crossing", "walkingarea"} or _edge_is_pedestrian_only(edge):
        return False
    edge_types = edge.attrib.get("type", "").split("|")
    return any(edge_type.startswith("highway.") for edge_type in edge_types) or any(
        set((lane.attrib.get("allow") or "").split())
        & {"passenger", "private", "bus", "coach", "truck", "motorcycle", "moped", "taxi", "delivery", "emergency"}
        for lane in edge.findall("lane")
    )


def _same_family_continuation_edge_map(
    teacher_edges: dict[str, ET.Element],
    candidate_edges_by_id: dict[str, ET.Element],
    edge_map: dict[str, str],
    *,
    teacher_junction_id: str,
    candidate_junction_id: str,
) -> dict[str, str]:
    frontier_endpoints_by_family: dict[str, set[str]] = {}
    used_candidate_edge_ids = {candidate_id for candidate_id in edge_map.values() if candidate_id}
    for teacher_edge_id, candidate_edge_id in edge_map.items():
        teacher_edge = teacher_edges.get(teacher_edge_id)
        candidate_edge = candidate_edges_by_id.get(candidate_edge_id)
        if (
            teacher_edge is None
            or candidate_edge is None
            or teacher_edge_id.startswith(":")
            or _signed_edge_family_id(teacher_edge_id) != _signed_edge_family_id(candidate_edge_id)
            or not _edge_is_vehicle_continuation_candidate(teacher_edge)
            or not _edge_is_vehicle_continuation_candidate(candidate_edge)
        ):
            continue
        family_id = _signed_edge_family_id(teacher_edge_id)
        frontier_endpoints_by_family.setdefault(family_id, set()).update(
            {
                _mapped_junction_ref(teacher_edge.attrib.get("from", ""), teacher_junction_id, candidate_junction_id),
                _mapped_junction_ref(teacher_edge.attrib.get("to", ""), teacher_junction_id, candidate_junction_id),
            }
        )
    if not frontier_endpoints_by_family:
        return {}

    candidate_edges_by_signature: dict[tuple[str, str, str], list[str]] = {}
    for candidate_edge_id, candidate_edge in candidate_edges_by_id.items():
        if candidate_edge_id.startswith(":") or not _edge_is_vehicle_continuation_candidate(candidate_edge):
            continue
        candidate_edges_by_signature.setdefault(
            (
                _signed_edge_family_id(candidate_edge_id),
                candidate_edge.attrib.get("from", ""),
                candidate_edge.attrib.get("to", ""),
            ),
            [],
        ).append(candidate_edge_id)

    additions: dict[str, str] = {}
    for teacher_edge_id, teacher_edge in sorted(teacher_edges.items()):
        if (
            teacher_edge_id in edge_map
            or teacher_edge_id.startswith(":")
            or not _edge_is_vehicle_continuation_candidate(teacher_edge)
        ):
            continue
        family_id = _signed_edge_family_id(teacher_edge_id)
        frontier_endpoints = frontier_endpoints_by_family.get(family_id, set())
        if not frontier_endpoints:
            continue
        desired_from = _mapped_junction_ref(teacher_edge.attrib.get("from", ""), teacher_junction_id, candidate_junction_id)
        desired_to = _mapped_junction_ref(teacher_edge.attrib.get("to", ""), teacher_junction_id, candidate_junction_id)
        if not desired_from or not desired_to or not ({desired_from, desired_to} & frontier_endpoints):
            continue
        candidate_ids = [
            candidate_edge_id
            for candidate_edge_id in candidate_edges_by_signature.get((family_id, desired_from, desired_to), [])
            if candidate_edge_id not in used_candidate_edge_ids
            and _edge_type_signature(candidate_edges_by_id[candidate_edge_id]) == _edge_type_signature(teacher_edge)
            and _edge_lane_count(candidate_edges_by_id[candidate_edge_id]) == _edge_lane_count(teacher_edge)
        ]
        unique_candidate_ids = sorted(set(candidate_ids))
        if len(unique_candidate_ids) != 1:
            continue
        candidate_edge_id = unique_candidate_ids[0]
        additions[teacher_edge_id] = candidate_edge_id
        used_candidate_edge_ids.add(candidate_edge_id)
    return additions










def _clone_transformed_net_element(
    element: ET.Element,
    dx: float,
    dy: float,
    edge_map: dict[str, str],
    teacher_junction_id: str | None = None,
    candidate_junction_id: str | None = None,
) -> ET.Element:
    clone = ET.Element(
        element.tag,
        _mapped_spatial_attrs(element.attrib, dx, dy, edge_map, teacher_junction_id, candidate_junction_id),
    )
    clone.text = element.text
    clone.tail = element.tail
    for child in list(element):
        clone.append(
            _clone_transformed_net_element(child, dx, dy, edge_map, teacher_junction_id, candidate_junction_id)
        )
    return clone


def _clone_transformed_boundary_edge(
    edge: ET.Element,
    edge_id: str,
    dx: float,
    dy: float,
    edge_map: dict[str, str],
    teacher_junction_id: str,
    candidate_junction_id: str,
) -> ET.Element:
    clone = _clone_transformed_net_element(edge, dx, dy, edge_map, teacher_junction_id, candidate_junction_id)
    teacher_edge_id = edge.attrib.get("id", "")
    if edge_id and edge_id != teacher_edge_id:
        clone.set("id", edge_id)
        teacher_prefix = f"{teacher_edge_id}_"
        candidate_prefix = f"{edge_id}_"
        for lane in clone.findall("lane"):
            lane_id = lane.attrib.get("id", "")
            if lane_id.startswith(teacher_prefix):
                lane.set("id", f"{candidate_prefix}{lane_id[len(teacher_prefix):]}")
            elif lane.attrib.get("index"):
                lane.set("id", f"{candidate_prefix}{lane.attrib['index']}")
    return clone






def _edge_geometry_matches_current_junctions(
    root: ET.Element,
    edge: ET.Element,
    existing_edge: ET.Element,
    max_endpoint_delta: float,
) -> bool:
    edge_endpoints = _shape_endpoints(_primary_edge_shape(edge))
    existing_endpoints = _shape_endpoints(_primary_edge_shape(existing_edge))
    from_xy = _junction_xy(root, edge.attrib.get("from", ""))
    to_xy = _junction_xy(root, edge.attrib.get("to", ""))
    if edge_endpoints is None or existing_endpoints is None or from_xy is None or to_xy is None:
        return False
    matches_replay = all(
        ((actual[0] - expected[0]) ** 2 + (actual[1] - expected[1]) ** 2) ** 0.5 <= max_endpoint_delta
        for actual, expected in zip(existing_endpoints, edge_endpoints)
    )
    matches_current_endpoints = all(
        ((actual[0] - expected[0]) ** 2 + (actual[1] - expected[1]) ** 2) ** 0.5 <= max_endpoint_delta
        for actual, expected in zip(existing_endpoints, (from_xy, to_xy))
    )
    return matches_replay and matches_current_endpoints


def _restore_existing_edge_geometry(
    edge: ET.Element,
    geometry_source_edge: ET.Element,
    root: ET.Element,
    *,
    max_endpoint_delta: float | None = None,
) -> None:
    if max_endpoint_delta is not None and not _edge_geometry_matches_current_junctions(
        root,
        edge,
        geometry_source_edge,
        max_endpoint_delta,
    ):
        return
    source_edge_shape = geometry_source_edge.attrib.get("shape", "")
    if source_edge_shape:
        edge.set("shape", source_edge_shape)
    source_lane_shapes = {
        lane.attrib.get("index", ""): lane.attrib["shape"]
        for lane in geometry_source_edge.findall("lane")
        if lane.attrib.get("index", "") and lane.attrib.get("shape")
    }
    for lane in edge.findall("lane"):
        lane_shape = source_lane_shapes.get(lane.attrib.get("index", ""))
        if lane_shape:
            lane.set("shape", lane_shape)
        elif source_edge_shape:
            # Plain ``.edg.xml`` anchors often carry one centerline shape on
            # the edge and no explicit lane children.  It is still better
            # evidence than geometry translated from an unrelated teacher
            # endpoint, and preserves the legacy marker-file behaviour.
            lane.set("shape", source_edge_shape)
        restored_shape = lane.attrib.get("shape", "")
        if restored_shape and "length" in lane.attrib:
            rendered_length = _polyline_length(restored_shape)
            if rendered_length is not None:
                lane.set("length", f"{rendered_length:.2f}")


def _blend_geometry_anchor_at_target(
    edge: ET.Element,
    geometry_source_edge: ET.Element,
    target_junction_id: str,
) -> bool:
    """Keep the anchor's remote endpoint and the teacher's target endpoint.

    A joined OSM cell and a hand-modelled teacher intersection rarely place
    the junction boundary at exactly the same coordinate.  Copying either
    complete shape creates a gap at one end.  This blend smoothly warps the
    anchor polyline from zero displacement at the untouched remote junction
    to the teacher displacement at the rebuilt target junction.
    """

    target_at_start = edge.attrib.get("from") == target_junction_id
    target_at_end = edge.attrib.get("to") == target_junction_id
    if target_at_start == target_at_end:
        return False
    if target_at_start and geometry_source_edge.attrib.get("from") != target_junction_id:
        return False
    if target_at_end and geometry_source_edge.attrib.get("to") != target_junction_id:
        return False

    return _blend_geometry_anchor_at_endpoint(
        edge,
        geometry_source_edge,
        target_at_start=target_at_start,
    )


def _blend_geometry_anchor_at_endpoint(
    edge: ET.Element,
    geometry_source_edge: ET.Element,
    *,
    target_at_start: bool,
) -> bool:
    """Blend a replayed local endpoint into an existing boundary edge.

    The source boundary may end at an OSM split member while the replayed
    boundary ends at the newly collapsed owner.  The endpoint ids therefore
    need not match even though their directed side does.  This lower-level
    primitive keeps the source's remote endpoint exactly and warps only toward
    the replayed teacher endpoint.
    """

    blended = False
    # SUMO nets commonly keep geometry only on lane children.  Falling back
    # to the first lane is essential here: leaving a translated teacher
    # centerline on the edge while blending only lane shapes makes netconvert
    # recreate the same remote-endpoint gap from the stale edge-level shape.
    teacher_edge_shape = _primary_edge_shape(edge)
    anchor_edge_shape = _primary_edge_shape(geometry_source_edge)
    if teacher_edge_shape and anchor_edge_shape:
        shape = _warp_anchor_shape_to_teacher_endpoint(
            anchor_edge_shape,
            teacher_edge_shape,
            target_at_start=target_at_start,
        )
        if shape:
            edge.set("shape", shape)
            blended = True

    anchor_lanes = {
        lane.attrib.get("index", ""): lane
        for lane in geometry_source_edge.findall("lane")
        if lane.attrib.get("index", "")
    }
    for lane in edge.findall("lane"):
        teacher_lane_shape = lane.attrib.get("shape", "")
        anchor_lane = anchor_lanes.get(lane.attrib.get("index", ""))
        anchor_lane_shape = (
            anchor_lane.attrib.get("shape", "")
            if anchor_lane is not None
            else anchor_edge_shape
        )
        if not teacher_lane_shape or not anchor_lane_shape:
            continue
        shape = _warp_anchor_shape_to_teacher_endpoint(
            anchor_lane_shape,
            teacher_lane_shape,
            target_at_start=target_at_start,
        )
        if shape:
            lane.set("shape", shape)
            # ``lane.length`` in a SUMO ``.net.xml`` is operational geometry,
            # not a teacher semantic.  The replayed lane was cloned before its
            # centre-line was warped and may therefore still carry the
            # teacher's (often much longer) declared length.  NetEdit renders
            # the new shape while SUMO positions vehicles using ``length``;
            # keeping the stale value makes the two views disagree.  Plain XML
            # conversion normally recomputes this field.  For the native net
            # replay path, recompute it whenever the cloned lane declared one.
            if "length" in lane.attrib:
                rendered_length = _polyline_length(shape)
                if rendered_length is not None:
                    lane.set("length", f"{rendered_length:.2f}")
            blended = True
    return blended


def _preserve_mapped_boundary_geometry(
    replayed_edge: ET.Element,
    geometry_source_edge: ET.Element,
    *,
    target_junction_ids: set[str],
    source_local_junction_ids: set[str],
) -> dict[str, object]:
    """Preserve a mapped candidate boundary while moving its local endpoint.

    A teacher boundary is a local intersection model, not evidence for the
    complete public-road segment outside the rebuilt cell.  Replacing a mapped
    candidate edge with the complete translated teacher shape can therefore
    move its remote endpoint by tens of metres.  Require the teacher and source
    to address the same directed side, keep the source remote endpoint, and
    blend only toward the replayed local endpoint.
    """

    source_has_geometry = bool(_primary_edge_shape(geometry_source_edge))
    replay_has_geometry = bool(_primary_edge_shape(replayed_edge))
    if not source_has_geometry or not replay_has_geometry:
        return {
            "status": "skipped",
            "reason": "source_or_replay_geometry_missing",
        }

    target_at_start = replayed_edge.attrib.get("from", "") in target_junction_ids
    target_at_end = replayed_edge.attrib.get("to", "") in target_junction_ids
    source_local_at_start = geometry_source_edge.attrib.get("from", "") in source_local_junction_ids
    source_local_at_end = geometry_source_edge.attrib.get("to", "") in source_local_junction_ids
    if target_at_start == target_at_end:
        return {
            "status": "blocked",
            "reason": "replayed_boundary_does_not_have_one_local_endpoint",
        }
    if source_local_at_start == source_local_at_end:
        return {
            "status": "blocked",
            "reason": "source_boundary_does_not_have_one_local_endpoint",
        }
    if target_at_start != source_local_at_start:
        return {
            "status": "blocked",
            "reason": "source_and_replayed_boundary_orientation_mismatch",
        }

    source_remote_id = geometry_source_edge.attrib.get("to" if source_local_at_start else "from", "")
    replayed_remote_id = replayed_edge.attrib.get("to" if target_at_start else "from", "")
    if source_remote_id != replayed_remote_id:
        return {
            "status": "blocked",
            "reason": "source_and_replayed_boundary_remote_endpoint_mismatch",
            "source_remote_junction_id": source_remote_id,
            "replayed_remote_junction_id": replayed_remote_id,
        }

    operational_restore = _preserve_boundary_operational_attributes(
        replayed_edge,
        geometry_source_edge,
    )
    if not _blend_geometry_anchor_at_endpoint(
        replayed_edge,
        geometry_source_edge,
        target_at_start=target_at_start,
    ):
        return {
            "status": "blocked",
            "reason": "boundary_geometry_blend_failed",
        }
    return {
        "status": "pass",
        "target_at_start": target_at_start,
        "source_remote_junction_id": source_remote_id,
        **operational_restore,
    }




def _restore_external_boundary_connections(
    *,
    source_root: ET.Element,
    target_root: ET.Element,
    boundary_edge_ids: set[str],
    source_local_junction_ids: set[str],
) -> dict[str, object]:
    """Restore only the source connections on the remote side of boundaries."""

    source_edges = {
        edge.attrib["id"]: edge
        for edge in source_root.findall("edge")
        if edge.attrib.get("id")
    }
    target_edge_ids = {
        edge.attrib["id"]
        for edge in target_root.findall("edge")
        if edge.attrib.get("id")
    }
    target_lane_counts = _net_lane_counts(target_root)
    target_lane_ids = {
        lane.attrib["id"]
        for edge in target_root.findall("edge")
        for lane in edge.findall("lane")
        if lane.attrib.get("id")
    }
    existing_keys = {
        tuple(sorted(connection.attrib.items()))
        for connection in target_root.findall("connection")
    }
    restored: list[dict[str, str]] = []
    preserved_existing: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    source_connections = list(source_root.findall("connection"))
    considered_connection_keys: set[tuple[tuple[str, str], ...]] = set()

    def remote_connection_chain(seed: ET.Element) -> list[ET.Element]:
        """Return a remote connection and its compiled internal continuations."""

        chain: list[ET.Element] = []
        queue = [seed]
        queued_keys = {tuple(sorted(seed.attrib.items()))}
        while queue:
            connection = queue.pop(0)
            chain.append(connection)
            via_lane = connection.attrib.get("via", "")
            if not via_lane:
                continue
            via_edge_id = via_lane.rsplit("_", 1)[0]
            for continuation in source_connections:
                if continuation.attrib.get("from", "") != via_edge_id:
                    continue
                key = tuple(sorted(continuation.attrib.items()))
                if key not in queued_keys:
                    queued_keys.add(key)
                    queue.append(continuation)
        return chain

    for boundary_edge_id in sorted(boundary_edge_ids):
        source_edge = source_edges.get(boundary_edge_id)
        if source_edge is None:
            continue
        local_at_start = source_edge.attrib.get("from", "") in source_local_junction_ids
        local_at_end = source_edge.attrib.get("to", "") in source_local_junction_ids
        if local_at_start == local_at_end:
            skipped.append(
                {
                    "boundary_edge_id": boundary_edge_id,
                    "reason": "source_boundary_does_not_have_one_local_endpoint",
                }
            )
            continue
        # At the remote junction an outgoing boundary is the source of the
        # continuation; an incoming boundary is its destination.
        boundary_attr = "from" if local_at_start else "to"
        for seed_connection in source_connections:
            if seed_connection.attrib.get(boundary_attr, "") != boundary_edge_id:
                continue
            for connection in remote_connection_chain(seed_connection):
                connection_key = tuple(sorted(connection.attrib.items()))
                if connection_key in considered_connection_keys:
                    continue
                considered_connection_keys.add(connection_key)
                record = dict(connection.attrib)
                if (
                    connection.attrib.get("from", "") not in target_edge_ids
                    or connection.attrib.get("to", "") not in target_edge_ids
                ):
                    skipped.append({**record, "reason": "missing_target_edge"})
                    continue
                if not _connection_lane_indices_valid(connection, target_lane_counts):
                    skipped.append({**record, "reason": "invalid_target_lane_index"})
                    continue
                via_lane = connection.attrib.get("via", "")
                if via_lane and via_lane not in target_lane_ids:
                    skipped.append({**record, "reason": "missing_target_via_lane"})
                    continue
                if connection_key in existing_keys:
                    preserved_existing.append(record)
                    continue
                target_root.append(copy.deepcopy(connection))
                existing_keys.add(connection_key)
                restored.append(record)

    return {
        "status": "pass",
        "restored_connection_count": len(restored),
        "restored_connections": restored,
        "preserved_existing_connection_count": len(preserved_existing),
        "preserved_existing_connections": preserved_existing,
        "skipped_connection_count": len(skipped),
        "skipped_connections": skipped,
    }


def _warp_anchor_shape_to_teacher_endpoint(
    anchor_shape: str,
    teacher_shape: str,
    *,
    target_at_start: bool,
) -> str:
    anchor_tokens = _split(anchor_shape)
    teacher_points = _shape_points(teacher_shape)
    parsed: list[tuple[float, float, list[str]]] = []
    for token in anchor_tokens:
        coords = token.split(",")
        if len(coords) < 2:
            return ""
        try:
            parsed.append((float(coords[0]), float(coords[1]), coords[2:]))
        except ValueError:
            return ""
    if not parsed or not teacher_points:
        return ""

    desired_x, desired_y = teacher_points[0 if target_at_start else -1]
    anchor_x, anchor_y, _ = parsed[0 if target_at_start else -1]
    delta_x = desired_x - anchor_x
    delta_y = desired_y - anchor_y
    displacement = math.hypot(delta_x, delta_y)
    cumulative = [0.0]
    for (left_x, left_y, _), (right_x, right_y, _) in zip(
        parsed,
        parsed[1:],
    ):
        cumulative.append(
            cumulative[-1] + math.hypot(right_x - left_x, right_y - left_y)
        )
    total = cumulative[-1]
    if total <= 1e-9:
        weights = [1.0 for _ in parsed]
    else:
        # The teacher owns the local conflict core, not the complete OSM
        # approach.  A full-edge linear warp can drag a lane across a nearby
        # junction.  Taper the correction inside a bounded local splice and
        # preserve the remote public-road geometry exactly.
        blend_extent = min(total, max(15.0, displacement * 4.0))
        distances_from_target = (
            cumulative
            if target_at_start
            else [total - distance for distance in cumulative]
        )
        weights = []
        for distance in distances_from_target:
            linear_weight = max(0.0, 1.0 - distance / blend_extent)
            weights.append(linear_weight * linear_weight * (3.0 - 2.0 * linear_weight))

    output = []
    for (x, y, extra), weight in zip(parsed, weights):
        coords = [
            _format_xy(x + delta_x * weight),
            _format_xy(y + delta_y * weight),
            *extra,
        ]
        output.append(",".join(coords))
    return " ".join(output)




def _load_geometry_anchor_edge_ids(edge_file: Path | None) -> set[str]:
    return set(_load_geometry_anchor_edges(edge_file))






def _expand_junction_shape_to_approach_endpoints(
    root: ET.Element,
    junction_id: str,
    geometry_anchor_edge_ids: set[str],
) -> dict[str, object]:
    if not geometry_anchor_edge_ids:
        return {"status": "skipped", "reason": "no_geometry_anchor_edges"}
    junction = root.find(f"junction[@id='{junction_id}']")
    if junction is None:
        return {"status": "skipped", "reason": "junction_not_found"}
    shape_points = _shape_points(junction.attrib.get("shape", ""))
    endpoint_points: list[tuple[float, float]] = []
    endpoint_edge_ids: list[str] = []
    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id", "")
        if (
            edge_id not in geometry_anchor_edge_ids
            or edge.attrib.get("function") == "internal"
            or junction_id not in (edge.attrib.get("from"), edge.attrib.get("to"))
        ):
            continue
        use_first = edge.attrib.get("from") == junction_id
        for lane in edge.findall("lane"):
            points = _shape_points(lane.attrib.get("shape", "") or edge.attrib.get("shape", ""))
            if not points:
                continue
            endpoint_points.append(points[0] if use_first else points[-1])
            endpoint_edge_ids.append(edge_id)
    if not endpoint_points:
        return {"status": "skipped", "reason": "no_approach_endpoints"}
    hull_points = _convex_hull([*shape_points, *endpoint_points])
    if len(hull_points) < 3:
        return {"status": "skipped", "reason": "insufficient_hull_points"}
    old_shape = junction.attrib.get("shape", "")
    new_shape = " ".join(f"{x:.2f},{y:.2f}" for x, y in hull_points)
    if new_shape == old_shape:
        return {
            "status": "unchanged",
            "approach_endpoint_count": len(endpoint_points),
            "approach_edge_ids": sorted(set(endpoint_edge_ids)),
        }
    junction.set("shape", new_shape)
    return {
        "status": "pass",
        "approach_endpoint_count": len(endpoint_points),
        "approach_edge_ids": sorted(set(endpoint_edge_ids)),
        "old_shape_point_count": len(shape_points),
        "new_shape_point_count": len(hull_points),
    }




def _polyline_length(shape: str) -> float | None:
    points = _shape_points(shape)
    if len(points) < 2:
        return None
    return sum(
        math.hypot(right[0] - left[0], right[1] - left[1])
        for left, right in zip(points, points[1:])
    )










def _restore_joined_split_edge_geometry(
    edge: ET.Element,
    stale_edge: ET.Element,
    source_edge: ET.Element,
) -> bool:
    if (
        stale_edge.attrib.get("to") == source_edge.attrib.get("from")
        and edge.attrib.get("from") == stale_edge.attrib.get("from")
        and edge.attrib.get("to") == source_edge.attrib.get("to")
    ):
        first_edge, second_edge = stale_edge, source_edge
    elif (
        source_edge.attrib.get("to") == stale_edge.attrib.get("from")
        and edge.attrib.get("from") == source_edge.attrib.get("from")
        and edge.attrib.get("to") == stale_edge.attrib.get("to")
    ):
        first_edge, second_edge = source_edge, stale_edge
    else:
        return False

    edge_shape = _join_shape_text(_primary_edge_shape(first_edge), _primary_edge_shape(second_edge))
    if edge_shape:
        edge.set("shape", edge_shape)
    first_lanes = _lanes_by_index(first_edge)
    second_lanes = _lanes_by_index(second_edge)
    changed = bool(edge_shape)
    for lane in edge.findall("lane"):
        lane_index = lane.attrib.get("index", "")
        first_lane = first_lanes.get(lane_index)
        second_lane = second_lanes.get(lane_index)
        if first_lane is None or second_lane is None:
            continue
        shape = _join_shape_text(first_lane.attrib.get("shape", ""), second_lane.attrib.get("shape", ""))
        if shape:
            lane.set("shape", shape)
            changed = True
        length = _joined_lane_length(first_lane, second_lane)
        if length is not None:
            lane.set("length", length)
    return changed




def _clone_transformed_junction(
    junction: ET.Element,
    dx: float,
    dy: float,
    edge_map: dict[str, str],
    teacher_internal_prefix: str,
    candidate_internal_prefix: str,
) -> ET.Element:
    clone = ET.Element(
        "junction",
        _mapped_junction_attrs(junction, dx, dy, edge_map, teacher_internal_prefix, candidate_internal_prefix),
    )
    clone.text = junction.text
    clone.tail = junction.tail
    for child in list(junction):
        clone.append(ET.Element(child.tag, dict(child.attrib)))
    return clone


def _clone_transformed_boundary_junction(
    junction: ET.Element,
    dx: float,
    dy: float,
    edge_map: dict[str, str],
    teacher_junction_id: str,
    candidate_junction_id: str,
) -> ET.Element:
    attrs = _mapped_spatial_attrs(junction.attrib, dx, dy, edge_map, teacher_junction_id, candidate_junction_id)
    attrs["incLanes"] = ""
    attrs["intLanes"] = ""
    return ET.Element("junction", attrs)




def _mapped_junction_attrs(
    teacher_junction: ET.Element,
    dx: float,
    dy: float,
    edge_map: dict[str, str],
    teacher_internal_prefix: str,
    candidate_internal_prefix: str,
) -> dict[str, str]:
    teacher_junction_id = teacher_internal_prefix[1:-1] if teacher_internal_prefix.startswith(":") else None
    candidate_junction_id = candidate_internal_prefix[1:-1] if candidate_internal_prefix.startswith(":") else None
    attrs = _mapped_spatial_attrs(teacher_junction.attrib, dx, dy, edge_map, teacher_junction_id, candidate_junction_id)
    if "incLanes" in attrs:
        attrs["incLanes"] = " ".join(
            lane
            for lane in (
                _map_lane_ref(lane, edge_map, teacher_internal_prefix, candidate_internal_prefix)
                for lane in _split(attrs["incLanes"])
            )
            if lane
        )
    if "intLanes" in attrs:
        attrs["intLanes"] = " ".join(
            lane
            for lane in (
                _map_lane_ref(lane, edge_map, teacher_internal_prefix, candidate_internal_prefix)
                for lane in _split(attrs["intLanes"])
            )
            if lane
        )
    return attrs


def _map_lane_ref(
    lane_id: str,
    edge_map: dict[str, str],
    teacher_internal_prefix: str,
    candidate_internal_prefix: str,
) -> str:
    if lane_id.startswith(teacher_internal_prefix):
        return _map_internal_ref(lane_id, teacher_internal_prefix, candidate_internal_prefix)
    if "_" not in lane_id:
        return ""
    edge_id, lane_index = lane_id.rsplit("_", 1)
    mapped_edge = edge_map.get(edge_id)
    return f"{mapped_edge}_{lane_index}" if mapped_edge else ""


def _mapped_connection_attrs(
    connection: ET.Element,
    edge_map: dict[str, str],
    teacher_internal_prefix: str,
    teacher_junction_id: str,
    candidate_internal_prefix: str,
    candidate_junction_id: str,
    candidate_edge_ids: set[str],
    dx: float,
    dy: float,
) -> dict[str, str] | None:
    mapped = dict(connection.attrib)
    for attr in ("from", "to"):
        endpoint = _map_connection_endpoint(
            mapped.get(attr, ""), edge_map, teacher_internal_prefix, candidate_internal_prefix, candidate_edge_ids
        )
        if not endpoint:
            return None
        mapped[attr] = endpoint
    if mapped.get("tl") and mapped.get("linkIndex"):
        mapped["tl"] = candidate_junction_id
    if mapped.get("via"):
        mapped["via"] = _map_internal_ref(mapped["via"], teacher_internal_prefix, candidate_internal_prefix)
        if not mapped["via"].startswith(candidate_internal_prefix):
            return None
    if mapped.get("shape"):
        mapped["shape"] = _translate_shape(mapped["shape"], dx, dy)
    return mapped


def _needed_unmapped_teacher_boundary_edges(
    connections: list[ET.Element],
    teacher_edges: dict[str, ET.Element],
    edge_map: dict[str, str],
    candidate_edges_by_id: dict[str, ET.Element],
    teacher_internal_prefix: str,
    teacher_junction_id: str,
    candidate_junction_id: str,
    dx: float,
    dy: float,
    *,
    compare_lane_shapes: bool = True,
    replay_existing_edges: bool = True,
) -> list[str]:
    needed = []
    seen = set()
    for connection in connections:
        if not _touches_target_internal_subgraph(connection, teacher_internal_prefix, teacher_junction_id):
            continue
        for attr in ("from", "to"):
            edge_id = connection.attrib.get(attr, "")
            if (
                not edge_id
                or edge_id.startswith(teacher_internal_prefix)
                or edge_id in seen
            ):
                continue
            teacher_edge = teacher_edges.get(edge_id)
            if teacher_edge is None:
                continue
            if teacher_junction_id not in (teacher_edge.attrib.get("from"), teacher_edge.attrib.get("to")):
                continue
            mapped_from = candidate_junction_id if teacher_edge.attrib.get("from") == teacher_junction_id else teacher_edge.attrib.get("from", "")
            mapped_to = candidate_junction_id if teacher_edge.attrib.get("to") == teacher_junction_id else teacher_edge.attrib.get("to", "")
            if not mapped_from or not mapped_to:
                continue
            candidate_edge = candidate_edges_by_id.get(edge_map.get(edge_id, edge_id))
            if candidate_edge is not None and not replay_existing_edges:
                continue
            if (
                candidate_edge is not None
                and candidate_edge.attrib.get("from") == mapped_from
                and candidate_edge.attrib.get("to") == mapped_to
                and (
                    not compare_lane_shapes
                    or _edge_lane_shapes(candidate_edge) == _translated_edge_lane_shapes(teacher_edge, dx, dy)
                )
            ):
                continue
            seen.add(edge_id)
            needed.append(edge_id)
    return needed




def _teacher_boundary_edge_needs_replay(
    teacher_edge: ET.Element,
    edge_map: dict[str, str],
    candidate_edges_by_id: dict[str, ET.Element],
    teacher_junction_id: str,
    candidate_junction_id: str,
    dx: float,
    dy: float,
) -> bool:
    edge_id = teacher_edge.attrib.get("id", "")
    mapped_from = candidate_junction_id if teacher_edge.attrib.get("from") == teacher_junction_id else teacher_edge.attrib.get("from", "")
    mapped_to = candidate_junction_id if teacher_edge.attrib.get("to") == teacher_junction_id else teacher_edge.attrib.get("to", "")
    candidate_edge = candidate_edges_by_id.get(edge_map.get(edge_id, edge_id))
    return not (
        candidate_edge is not None
        and candidate_edge.attrib.get("from") == mapped_from
        and candidate_edge.attrib.get("to") == mapped_to
        and candidate_edge.attrib.get("type", "") == teacher_edge.attrib.get("type", "")
        and _edge_lane_shapes(candidate_edge) == _translated_edge_lane_shapes(teacher_edge, dx, dy)
    )




def _translated_edge_lane_shapes(edge: ET.Element, dx: float, dy: float) -> list[str]:
    return [_translate_shape(shape, dx, dy) if shape else "" for shape in _edge_lane_shapes(edge)]








def _map_connection_endpoint(
    value: str,
    edge_map: dict[str, str],
    teacher_internal_prefix: str,
    candidate_internal_prefix: str,
    candidate_edge_ids: set[str],
) -> str:
    if value.startswith(teacher_internal_prefix):
        return _map_internal_ref(value, teacher_internal_prefix, candidate_internal_prefix)
    return edge_map.get(value, value if value in candidate_edge_ids else "")






def _touches_target_replay_scope(
    connection: ET.Element,
    internal_prefix: str,
    junction_id: str,
    edges_by_id: dict[str, ET.Element],
) -> bool:
    if _touches_target_internal_owner(connection, internal_prefix):
        return True
    if connection.attrib.get("tl") != junction_id:
        return False
    if _touches_other_internal_owner(connection, internal_prefix):
        return False
    return any(
        junction_id in (edge.attrib.get("from"), edge.attrib.get("to"))
        for edge_id in (connection.attrib.get("from", ""), connection.attrib.get("to", ""))
        for edge in [edges_by_id.get(edge_id)]
        if edge is not None
    )






def _non_target_internal_restore_changed(report: dict[str, object]) -> bool:
    changed = any(
        int(report.get(key, 0) or 0)
        for key in (
            "removed_non_target_internal_edge_count",
            "restored_non_target_internal_edge_count",
            "removed_non_target_internal_junction_count",
            "restored_non_target_internal_junction_count",
            "removed_non_target_internal_connection_count",
            "restored_non_target_internal_connection_count",
            "restored_non_target_normal_junction_attr_count",
            "restored_non_target_request_count",
        )
    )
    if (
        changed
        or int(report.get("restored_external_lane_count", 0) or 0)
        or int(report.get("restored_external_edge_centerline_count", 0) or 0)
    ):
        return True
    internal_report = report.get("internal_artifact_restore")
    return isinstance(internal_report, dict) and _non_target_internal_restore_changed(internal_report)


def restore_off_scope_netconvert_artifacts(
    *,
    source_file: Path,
    target_file: Path,
    mutable_junction_ids: set[str],
    mutable_edge_ids: set[str],
    expand_mutable_edge_endpoints: bool = True,
    junction_aliases: dict[str, str] | None = None,
    declared_absorbed_edge_ids: set[str] | None = None,
) -> dict[str, object]:
    """Restore the network outside one explicitly mutable replay scope.

    ``netconvert --sumo-net-file`` normalizes the complete network even when a
    replay changes only one junction cell.  This helper preserves the current
    cell and its boundary edges while restoring every other internal subgraph,
    traffic-light program, junction shape, and external-lane geometry from the
    immutable pre-normalization network.  Topology or lane-cardinality drift
    outside the declared scope is reported as a hard failure rather than being
    silently repaired.  ``junction_aliases`` is the narrow exception needed
    after a declared SUMO junction join: a surviving public-road edge may keep
    its source geometry while one endpoint changes from an absorbed member to
    the joined cluster id.  When ``declared_absorbed_edge_ids`` is supplied,
    only those source edges may disappear and each must collapse completely
    inside one alias target.
    """

    if not source_file.exists():
        return _failure(f"source net file does not exist: {source_file}")
    if not target_file.exists():
        return _failure(f"target net file does not exist: {target_file}")

    source_root = ET.parse(source_file).getroot()
    target_root = ET.parse(target_file).getroot()
    source_edges = {
        edge.attrib["id"]: edge
        for edge in source_root.findall("edge")
        if edge.attrib.get("id") and not edge.attrib["id"].startswith(":")
    }
    target_edges = {
        edge.attrib["id"]: edge
        for edge in target_root.findall("edge")
        if edge.attrib.get("id") and not edge.attrib["id"].startswith(":")
    }
    normalized_junction_aliases = {
        str(source_id): str(target_id)
        for source_id, target_id in (junction_aliases or {}).items()
        if str(source_id) and str(target_id) and str(source_id) != str(target_id)
    }
    source_junction_ids = {
        junction.attrib.get("id", "")
        for junction in source_root.findall("junction")
        if junction.attrib.get("id", "") and not junction.attrib.get("id", "").startswith(":")
    }
    target_junction_ids = {
        junction.attrib.get("id", "")
        for junction in target_root.findall("junction")
        if junction.attrib.get("id", "") and not junction.attrib.get("id", "").startswith(":")
    }
    invalid_aliases = [
        {
            "source_junction_id": source_id,
            "target_junction_id": target_id,
            "source_exists": source_id in source_junction_ids,
            "target_exists": target_id in target_junction_ids,
        }
        for source_id, target_id in sorted(normalized_junction_aliases.items())
        if source_id not in source_junction_ids or target_id not in target_junction_ids
    ]
    if invalid_aliases:
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "reason": "junction_alias_validation_failed",
            "source_file": str(source_file),
            "target_file": str(target_file),
            "invalid_junction_aliases": invalid_aliases,
        }
    expected_absorbed_edge_ids = (
        {str(edge_id) for edge_id in declared_absorbed_edge_ids if str(edge_id)}
        if declared_absorbed_edge_ids is not None
        else None
    )
    effective_mutable_junction_ids = {
        str(value) for value in mutable_junction_ids if str(value)
    }
    effective_mutable_junction_ids.update(normalized_junction_aliases)
    effective_mutable_junction_ids.update(normalized_junction_aliases.values())
    effective_mutable_edge_ids = {str(value) for value in mutable_edge_ids if str(value)}
    if expand_mutable_edge_endpoints:
        for edge_id in sorted(effective_mutable_edge_ids):
            for edge in (source_edges.get(edge_id), target_edges.get(edge_id)):
                if edge is None:
                    continue
                effective_mutable_junction_ids.update(
                    value
                    for value in (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
                    if value
                )

    internal_report = _restore_non_target_internal_artifacts(
        source_file=source_file,
        target_file=target_file,
        exclude_junction_ids=effective_mutable_junction_ids,
    )
    if internal_report.get("status") != "pass":
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "reason": "off_scope_internal_artifact_restore_not_pass",
            "source_file": str(source_file),
            "target_file": str(target_file),
            "internal_artifact_restore": internal_report,
        }

    target_tree = ET.parse(target_file)
    target_root = target_tree.getroot()
    target_edges = {
        edge.attrib["id"]: edge
        for edge in target_root.findall("edge")
        if edge.attrib.get("id") and not edge.attrib["id"].startswith(":")
    }
    failures: list[dict[str, object]] = []
    authorized_absorbed_edge_ids: list[str] = []
    restored_join_boundary_edge_ids: list[str] = []
    restored_edge_ids: list[str] = []
    restored_edge_centerline_ids: list[str] = []
    restored_lane_count = 0
    for edge_id, source_edge in sorted(source_edges.items()):
        if edge_id in effective_mutable_edge_ids:
            continue
        target_edge = target_edges.get(edge_id)
        source_endpoints = (
            source_edge.attrib.get("from", ""),
            source_edge.attrib.get("to", ""),
        )
        aliased_source_endpoints = tuple(
            normalized_junction_aliases.get(endpoint, endpoint)
            for endpoint in source_endpoints
        )
        if target_edge is None:
            if expected_absorbed_edge_ids is not None:
                authorized = (
                    edge_id in expected_absorbed_edge_ids
                    and aliased_source_endpoints[0]
                    and aliased_source_endpoints[0] == aliased_source_endpoints[1]
                )
            else:
                authorized = all(
                    endpoint and endpoint in effective_mutable_junction_ids
                    for endpoint in source_endpoints
                )
            if authorized:
                authorized_absorbed_edge_ids.append(edge_id)
            else:
                failures.append(
                    {
                        "edge_id": edge_id,
                        "reason": "off_scope_edge_missing",
                        "source_endpoints": source_endpoints,
                        "aliased_source_endpoints": aliased_source_endpoints,
                        "declared_absorbed": (
                            edge_id in expected_absorbed_edge_ids
                            if expected_absorbed_edge_ids is not None
                            else None
                        ),
                    }
                )
            continue
        target_endpoints = (
            target_edge.attrib.get("from", ""),
            target_edge.attrib.get("to", ""),
        )
        join_boundary_endpoint_change = (
            source_endpoints != target_endpoints
            and bool(normalized_junction_aliases)
            and aliased_source_endpoints == target_endpoints
        )
        if source_endpoints != target_endpoints and not join_boundary_endpoint_change:
            failures.append(
                {
                    "edge_id": edge_id,
                    "reason": "off_scope_edge_endpoints_changed",
                    "source_endpoints": source_endpoints,
                    "target_endpoints": target_endpoints,
                }
            )
            continue
        if join_boundary_endpoint_change:
            restored_join_boundary_edge_ids.append(edge_id)
        source_lanes = {
            lane.attrib.get("index", ""): lane for lane in source_edge.findall("lane")
        }
        target_lanes = {
            lane.attrib.get("index", ""): lane for lane in target_edge.findall("lane")
        }
        if source_lanes.keys() != target_lanes.keys():
            failures.append(
                {
                    "edge_id": edge_id,
                    "reason": "off_scope_lane_cardinality_changed",
                    "source_lane_indices": sorted(source_lanes),
                    "target_lane_indices": sorted(target_lanes),
                }
            )
            continue
        before_edge_shape = target_edge.attrib.get("shape")
        before_lanes = {
            lane_index: {
                attr: target_lane.attrib.get(attr)
                for attr in GEOMETRY_RESTORE_LANE_ATTRS
            }
            for lane_index, target_lane in target_lanes.items()
        }
        _restore_existing_edge_geometry(target_edge, source_edge, target_root)
        if before_edge_shape != target_edge.attrib.get("shape"):
            restored_edge_centerline_ids.append(edge_id)
        edge_changed = False
        for lane_index, source_lane in source_lanes.items():
            target_lane = target_lanes[lane_index]
            for attr in GEOMETRY_RESTORE_LANE_ATTRS:
                if attr in source_lane.attrib:
                    target_lane.set(attr, source_lane.attrib[attr])
                else:
                    target_lane.attrib.pop(attr, None)
            after = {attr: target_lane.attrib.get(attr) for attr in GEOMETRY_RESTORE_LANE_ATTRS}
            if before_lanes[lane_index] != after:
                edge_changed = True
                restored_lane_count += 1
        if edge_changed:
            restored_edge_ids.append(edge_id)

    undeleted_declared_absorbed_edge_ids: list[str] = []
    if expected_absorbed_edge_ids is not None:
        undeleted_declared_absorbed_edge_ids = sorted(
            expected_absorbed_edge_ids - set(authorized_absorbed_edge_ids)
        )
        failures.extend(
            {
                "edge_id": edge_id,
                "reason": "declared_absorbed_edge_not_absorbed",
            }
            for edge_id in undeleted_declared_absorbed_edge_ids
        )

    if restored_lane_count or restored_edge_centerline_ids:
        ET.indent(target_root, space="    ")
        target_tree.write(target_file, encoding="utf-8", xml_declaration=True)

    internal_failures = {
        key: int(internal_report.get(key, 0) or 0)
        for key in (
            "skipped_non_target_internal_edge_missing_junction_count",
            "skipped_non_target_internal_connection_missing_edge_count",
            "skipped_non_target_internal_connection_invalid_lane_count",
            "skipped_non_target_internal_connection_missing_via_lane_count",
            "missing_non_target_tllogic_count",
        )
        if int(internal_report.get(key, 0) or 0)
    }
    status = "pass" if not failures and not internal_failures else "fail"
    return {
        "status": status,
        "claim_status": "diagnostic-demo" if status == "pass" else "construction-invalid",
        "source_file": str(source_file),
        "target_file": str(target_file),
        "mutable_junction_ids": sorted(effective_mutable_junction_ids),
        "mutable_edge_ids": sorted(effective_mutable_edge_ids),
        "junction_aliases": dict(sorted(normalized_junction_aliases.items())),
        "declared_absorbed_edge_ids": (
            sorted(expected_absorbed_edge_ids)
            if expected_absorbed_edge_ids is not None
            else None
        ),
        "expanded_mutable_edge_endpoints": expand_mutable_edge_endpoints,
        "authorized_absorbed_external_edge_ids": authorized_absorbed_edge_ids,
        "undeleted_declared_absorbed_edge_ids": undeleted_declared_absorbed_edge_ids,
        "restored_join_boundary_edge_count": len(restored_join_boundary_edge_ids),
        "restored_join_boundary_edge_ids": restored_join_boundary_edge_ids,
        "restored_external_edge_count": len(restored_edge_ids),
        "restored_external_edge_ids": restored_edge_ids,
        "restored_external_edge_centerline_count": len(restored_edge_centerline_ids),
        "restored_external_edge_centerline_ids": restored_edge_centerline_ids,
        "restored_external_lane_count": restored_lane_count,
        "failure_count": len(failures) + sum(internal_failures.values()),
        "failures": failures,
        "internal_failure_counts": internal_failures,
        "internal_artifact_restore": internal_report,
    }


def write_reanchored_normal_junction_movements(
    *,
    source_net_file: Path,
    candidate_net_file: Path,
    output_file: Path,
    junction_id: str,
    declared_added_movement_shapes: dict[tuple[str, str, str, str], str],
) -> dict[str, object]:
    """Reanchor one normal junction's internal movement lanes, and nothing else.

    The candidate may add only the explicitly declared external movements.  An
    existing movement reuses its accepted source via-lane geometry; a declared
    movement uses the supplied endpoint-bound polyline.  This helper is meant
    to run after global ``netconvert`` geometry has already been restored.
    """

    missing = [str(path) for path in (source_net_file, candidate_net_file) if not path.exists()]
    if missing:
        return _failure(f"missing input file(s): {', '.join(missing)}")
    junction_id = str(junction_id).strip()
    if not junction_id or junction_id.startswith(":"):
        return _failure("one normal junction id is required")
    if not declared_added_movement_shapes:
        return _failure("at least one declared added movement shape is required")

    source_net_file = source_net_file.resolve()
    candidate_net_file = candidate_net_file.resolve()
    output_file = output_file.resolve()
    if output_file in {source_net_file, candidate_net_file}:
        return _failure("output file must differ from source and candidate inputs")

    source_sha256 = hashlib.sha256(source_net_file.read_bytes()).hexdigest()
    candidate_sha256 = hashlib.sha256(candidate_net_file.read_bytes()).hexdigest()
    source_root = ET.parse(source_net_file).getroot()
    candidate_tree = ET.parse(candidate_net_file)
    candidate_root = candidate_tree.getroot()
    internal_prefix = f":{junction_id}_"

    def fail(reason: str, failures: list[dict[str, object]]) -> dict[str, object]:
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "reason": reason,
            "source_net_file": str(source_net_file),
            "source_sha256": source_sha256,
            "candidate_net_file": str(candidate_net_file),
            "candidate_sha256": candidate_sha256,
            "output_file": str(output_file),
            "junction_id": junction_id,
            "failure_count": len(failures),
            "failures": failures,
        }

    def strict_polyline(shape: str) -> tuple[list[tuple[float, ...]], float] | None:
        points: list[tuple[float, ...]] = []
        try:
            for token in shape.split():
                coordinates = tuple(float(value) for value in token.split(","))
                if len(coordinates) not in {2, 3} or not all(math.isfinite(value) for value in coordinates):
                    return None
                points.append(coordinates)
        except ValueError:
            return None
        if len(points) < 2 or any(len(point) != len(points[0]) for point in points):
            return None
        length = sum(math.dist(left, right) for left, right in zip(points, points[1:]))
        return (points, length) if math.isfinite(length) and length > 0 else None

    def external_connections(root: ET.Element) -> dict[tuple[str, str, str, str], list[ET.Element]]:
        grouped: dict[tuple[str, str, str, str], list[ET.Element]] = {}
        for connection in root.findall("connection"):
            if connection.attrib.get("from", "").startswith(":") or connection.attrib.get("to", "").startswith(":"):
                continue
            grouped.setdefault(_connection_key(connection), []).append(connection)
        return grouped

    def lane_index(root: ET.Element) -> dict[str, list[ET.Element]]:
        indexed: dict[str, list[ET.Element]] = {}
        for lane in root.findall("edge/lane"):
            lane_id = lane.attrib.get("id", "")
            if lane_id:
                indexed.setdefault(lane_id, []).append(lane)
        return indexed

    def external_lane(root: ET.Element, edge_id: str, lane_index_value: str) -> ET.Element | None:
        edge = root.find(f"edge[@id='{edge_id}']")
        if edge is None or edge_id.startswith(":"):
            return None
        lanes = [lane for lane in edge.findall("lane") if lane.attrib.get("index", "0") == lane_index_value]
        return lanes[0] if len(lanes) == 1 else None

    def invariant_hashes(root: ET.Element) -> dict[str, str]:
        external_edges = [
            _xml_element_semantic_payload(edge)
            for edge in root.findall("edge")
            if not edge.attrib.get("id", "").startswith(":")
        ]
        connections = [_xml_element_semantic_payload(connection) for connection in root.findall("connection")]
        tls = [_xml_element_semantic_payload(logic) for logic in root.findall("tlLogic")]
        requests = [
            {
                "junction_id": junction.attrib.get("id", ""),
                "intLanes": junction.attrib.get("intLanes", ""),
                "requests": [_xml_element_semantic_payload(request) for request in junction.findall("request")],
            }
            for junction in root.findall("junction")
            if not junction.attrib.get("id", "").startswith(":")
        ]

        def digest(payload: object) -> str:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            return hashlib.sha256(encoded).hexdigest()

        return {
            "external_lanes_sha256": digest(external_edges),
            "connections_sha256": digest(connections),
            "tls_sha256": digest(tls),
            "request_matrix_sha256": digest(requests),
        }

    failures: list[dict[str, object]] = []
    source_junctions = source_root.findall(f"junction[@id='{junction_id}']")
    candidate_junctions = candidate_root.findall(f"junction[@id='{junction_id}']")
    if len(source_junctions) != 1 or len(candidate_junctions) != 1:
        failures.append(
            {
                "reason": "target_normal_junction_not_unique",
                "source_count": len(source_junctions),
                "candidate_count": len(candidate_junctions),
            }
        )
        return fail("target junction validation failed", failures)
    source_junction = source_junctions[0]
    candidate_junction = candidate_junctions[0]
    if source_junction.attrib.get("shape", "") != candidate_junction.attrib.get("shape", ""):
        failures.append(
            {
                "reason": "target_junction_shape_changed",
                "source_shape": source_junction.attrib.get("shape", ""),
                "candidate_shape": candidate_junction.attrib.get("shape", ""),
            }
        )

    declared_shapes: dict[tuple[str, str, str, str], str] = {}
    for raw_key, raw_shape in declared_added_movement_shapes.items():
        if not isinstance(raw_key, tuple) or len(raw_key) != 4:
            failures.append({"reason": "declared_movement_key_invalid", "key": repr(raw_key)})
            continue
        key = tuple(str(value) for value in raw_key)
        if not key[0] or not key[1] or not key[2] or not key[3]:
            failures.append({"reason": "declared_movement_key_has_empty_value", "key": _connection_key_record(key)})
            continue
        shape = str(raw_shape).strip()
        if key in declared_shapes:
            failures.append({"reason": "declared_movement_key_duplicate", "key": _connection_key_record(key)})
            continue
        declared_shapes[key] = shape

    source_connections = external_connections(source_root)
    candidate_connections = external_connections(candidate_root)
    duplicate_source_keys = sorted(key for key, values in source_connections.items() if len(values) != 1)
    duplicate_candidate_keys = sorted(key for key, values in candidate_connections.items() if len(values) != 1)
    if duplicate_source_keys or duplicate_candidate_keys:
        failures.append(
            {
                "reason": "external_movement_key_not_unique",
                "source_keys": [_connection_key_record(key) for key in duplicate_source_keys],
                "candidate_keys": [_connection_key_record(key) for key in duplicate_candidate_keys],
            }
        )
    source_keys = set(source_connections)
    candidate_keys = set(candidate_connections)
    declared_keys = set(declared_shapes)
    added_keys = candidate_keys - source_keys
    removed_keys = source_keys - candidate_keys
    if added_keys != declared_keys or removed_keys:
        failures.append(
            {
                "reason": "external_movement_delta_not_declared",
                "declared_additions": [_connection_key_record(key) for key in sorted(declared_keys)],
                "actual_additions": [_connection_key_record(key) for key in sorted(added_keys)],
                "actual_removals": [_connection_key_record(key) for key in sorted(removed_keys)],
            }
        )

    source_lane_index = lane_index(source_root)
    candidate_lane_index = lane_index(candidate_root)

    def target_via_lane(
        connection: ET.Element,
        lanes: dict[str, list[ET.Element]],
        *,
        key: tuple[str, str, str, str],
        side: str,
    ) -> ET.Element | None:
        via_lane_id = connection.attrib.get("via", "")
        matches = lanes.get(via_lane_id, []) if via_lane_id.startswith(internal_prefix) else []
        if len(matches) != 1:
            failures.append(
                {
                    "reason": "target_owned_via_lane_not_unique",
                    "side": side,
                    "key": _connection_key_record(key),
                    "via_lane_id": via_lane_id,
                    "lane_count": len(matches),
                }
            )
            return None
        return matches[0]

    source_target_keys = {
        key
        for key, values in source_connections.items()
        if len(values) == 1 and values[0].attrib.get("via", "").startswith(internal_prefix)
    }
    candidate_target_keys = {
        key
        for key, values in candidate_connections.items()
        if len(values) == 1 and values[0].attrib.get("via", "").startswith(internal_prefix)
    }
    if candidate_target_keys != source_target_keys | declared_keys:
        failures.append(
            {
                "reason": "target_junction_movement_ownership_mismatch",
                "source_keys": [_connection_key_record(key) for key in sorted(source_target_keys)],
                "candidate_keys": [_connection_key_record(key) for key in sorted(candidate_target_keys)],
                "declared_additions": [_connection_key_record(key) for key in sorted(declared_keys)],
            }
        )

    lane_updates: list[tuple[ET.Element, dict[str, str], dict[str, object]]] = []
    target_via_ids: set[str] = set()
    for key in sorted(source_target_keys):
        if len(source_connections.get(key, [])) != 1 or len(candidate_connections.get(key, [])) != 1:
            continue
        source_lane = target_via_lane(source_connections[key][0], source_lane_index, key=key, side="source")
        candidate_lane = target_via_lane(candidate_connections[key][0], candidate_lane_index, key=key, side="candidate")
        if source_lane is None or candidate_lane is None:
            continue
        via_lane_id = candidate_connections[key][0].attrib.get("via", "")
        if via_lane_id in target_via_ids:
            failures.append(
                {
                    "reason": "candidate_via_lane_reused_by_multiple_movements",
                    "key": _connection_key_record(key),
                    "via_lane_id": via_lane_id,
                }
            )
            continue
        target_via_ids.add(via_lane_id)
        attrs = {attr: source_lane.attrib.get(attr, "") for attr in ("speed", "length", "shape")}
        parsed_shape = strict_polyline(attrs["shape"])
        try:
            valid_scalars = all(math.isfinite(float(attrs[attr])) and float(attrs[attr]) > 0 for attr in ("speed", "length"))
        except ValueError:
            valid_scalars = False
        if parsed_shape is None or not valid_scalars:
            failures.append(
                {
                    "reason": "accepted_source_via_lane_geometry_invalid",
                    "key": _connection_key_record(key),
                    "via_lane_id": source_connections[key][0].attrib.get("via", ""),
                }
            )
            continue
        lane_updates.append(
            (
                candidate_lane,
                attrs,
                {
                    "kind": "existing",
                    "key": _connection_key_record(key),
                    "source_via_lane_id": source_connections[key][0].attrib.get("via", ""),
                    "candidate_via_lane_id": via_lane_id,
                },
            )
        )

    for key in sorted(declared_keys):
        if len(candidate_connections.get(key, [])) != 1:
            continue
        connection = candidate_connections[key][0]
        candidate_lane = target_via_lane(connection, candidate_lane_index, key=key, side="candidate")
        if candidate_lane is None:
            continue
        via_lane_id = connection.attrib.get("via", "")
        if via_lane_id in target_via_ids:
            failures.append(
                {
                    "reason": "candidate_via_lane_reused_by_multiple_movements",
                    "key": _connection_key_record(key),
                    "via_lane_id": via_lane_id,
                }
            )
            continue
        target_via_ids.add(via_lane_id)
        parsed = strict_polyline(declared_shapes[key])
        from_lane = external_lane(candidate_root, key[0], key[2])
        to_lane = external_lane(candidate_root, key[1], key[3])
        from_shape = strict_polyline(from_lane.attrib.get("shape", "")) if from_lane is not None else None
        to_shape = strict_polyline(to_lane.attrib.get("shape", "")) if to_lane is not None else None
        if parsed is None or from_shape is None or to_shape is None:
            failures.append(
                {
                    "reason": "declared_movement_or_external_lane_shape_invalid",
                    "key": _connection_key_record(key),
                }
            )
            continue
        points, length = parsed
        expected_start = from_shape[0][-1]
        expected_end = to_shape[0][0]
        if points[0] != expected_start or points[-1] != expected_end:
            failures.append(
                {
                    "reason": "declared_movement_shape_endpoint_mismatch",
                    "key": _connection_key_record(key),
                    "provided_start": list(points[0]),
                    "expected_start": list(expected_start),
                    "provided_end": list(points[-1]),
                    "expected_end": list(expected_end),
                }
            )
            continue
        lane_updates.append(
            (
                candidate_lane,
                {"shape": declared_shapes[key], "length": f"{length:.12g}"},
                {
                    "kind": "added",
                    "key": _connection_key_record(key),
                    "candidate_via_lane_id": via_lane_id,
                    "polyline_length": length,
                },
            )
        )

    if failures:
        return fail("scoped internal movement validation failed", failures)

    invariants_before = invariant_hashes(candidate_root)
    mutations: list[dict[str, object]] = []
    for lane, attrs, record in lane_updates:
        before = {attr: lane.attrib.get(attr) for attr in attrs}
        for attr, value in attrs.items():
            lane.set(attr, value)
        mutations.append({**record, "before": before, "after": attrs})
    candidate_junction.set("shape", source_junction.attrib.get("shape", ""))
    if "customShape" in source_junction.attrib:
        candidate_junction.set("customShape", source_junction.attrib["customShape"])
    else:
        candidate_junction.attrib.pop("customShape", None)

    invariants_after = invariant_hashes(candidate_root)
    changed_invariants = sorted(
        key for key, before in invariants_before.items() if invariants_after.get(key) != before
    )
    if changed_invariants:
        return fail(
            "scoped internal movement repair changed immutable network semantics",
            [{"reason": "immutable_semantic_hash_changed", "fields": changed_invariants}],
        )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(candidate_root, space="    ")
    candidate_tree.write(output_file, encoding="utf-8", xml_declaration=True)
    source_sha256_after = hashlib.sha256(source_net_file.read_bytes()).hexdigest()
    candidate_sha256_after = hashlib.sha256(candidate_net_file.read_bytes()).hexdigest()
    source_mutated = source_sha256_after != source_sha256
    candidate_mutated = candidate_sha256_after != candidate_sha256
    status = "pass" if not source_mutated and not candidate_mutated else "fail"
    return {
        "status": status,
        "claim_status": "diagnostic-demo" if status == "pass" else "construction-invalid",
        "promotion_status": "review_required",
        "source_net_file": str(source_net_file),
        "source_sha256": source_sha256,
        "source_sha256_after": source_sha256_after,
        "source_network_mutation": source_mutated,
        "candidate_net_file": str(candidate_net_file),
        "candidate_sha256": candidate_sha256,
        "candidate_sha256_after": candidate_sha256_after,
        "candidate_network_mutation": candidate_mutated,
        "output_file": str(output_file),
        "output_sha256": hashlib.sha256(output_file.read_bytes()).hexdigest(),
        "junction_id": junction_id,
        "declared_added_movement_count": len(declared_keys),
        "reanchored_existing_movement_count": len(source_target_keys),
        "reanchored_added_movement_count": len(declared_keys),
        "mutation_count": len(mutations),
        "mutations": mutations,
        "junction_shape": source_junction.attrib.get("shape", ""),
        "junction_custom_shape": source_junction.attrib.get("customShape"),
        "immutable_hashes_before": invariants_before,
        "immutable_hashes_after": invariants_after,
        "failure_count": 0,
        "failures": [],
        "policy": (
            "reanchor only the target normal junction's uniquely owned internal movement lanes; "
            "preserve external lanes, connections, TLS, and request matrices"
        ),
    }


def write_authorized_lane_transition_junction_shapes(
    *,
    candidate_net_file: Path,
    output_file: Path,
    junction_ids: set[str],
    evidence_net_file: Path | None = None,
    excluded_branch_edge_ids_by_junction: dict[str, list[str]] | None = None,
) -> dict[str, object]:
    """Tighten only evidence-authorized linear lane-transition junctions.

    A human-cleaned network normally keeps a real lane-drop or lane-gain node
    separate from the upstream conflict core.  The node polygon can still be
    over-wide after OSM import, so this controller replaces only its ``shape``
    with the convex hull of the adjacent lane endpoints.  Edge geometry,
    lane cardinality, connections, via lanes, and TLS programs are immutable.

    ``evidence_net_file`` should be the pre-rebuild OSM/SUMO baseline.  It is
    used to prove that the selected cell was already a one-in/one-out straight
    road transition before a teacher replay changed boundary edge metadata.
    Selection remains explicit: this writer never scans the whole network and
    never applies SUMO's global ``--junctions.minimal-shape`` option.
    """

    missing = [
        str(path)
        for path in (candidate_net_file, evidence_net_file)
        if path is not None and not path.exists()
    ]
    if missing:
        return _failure(f"missing input file(s): {', '.join(missing)}")
    if not junction_ids:
        return _failure("at least one evidence-authorized junction id is required")

    candidate_net_file = candidate_net_file.resolve()
    output_file = output_file.resolve()
    evidence_net_file = evidence_net_file.resolve() if evidence_net_file is not None else candidate_net_file
    source_sha256 = hashlib.sha256(candidate_net_file.read_bytes()).hexdigest()
    candidate_tree = ET.parse(candidate_net_file)
    candidate_root = candidate_tree.getroot()
    evidence_root = ET.parse(evidence_net_file).getroot()
    excluded_branch_edge_ids_by_junction = excluded_branch_edge_ids_by_junction or {}

    topology_before = _junction_shape_repair_topology_sha256(candidate_root)
    repairs: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    all_edge_ids = {
        edge.attrib.get("id", "")
        for edge in candidate_root.findall("edge")
        if edge.attrib.get("id")
    }
    for junction_id in sorted(str(value) for value in junction_ids if str(value)):
        candidate_estimate = _estimate_linear_lane_transition_shape(candidate_root, junction_id)
        evidence_estimate = _estimate_linear_lane_transition_shape(evidence_root, junction_id)
        excluded_branch_edge_ids = sorted(
            {
                str(value)
                for value in excluded_branch_edge_ids_by_junction.get(junction_id, [])
                if str(value)
            }
        )
        present_excluded_branch_edge_ids = sorted(set(excluded_branch_edge_ids) & all_edge_ids)
        if candidate_estimate.get("status") != "pass":
            failures.append(
                {
                    "junction_id": junction_id,
                    "reason": "candidate_not_linear_lane_transition",
                    "estimate": candidate_estimate,
                }
            )
            continue
        if evidence_estimate.get("status") != "pass":
            failures.append(
                {
                    "junction_id": junction_id,
                    "reason": "evidence_not_linear_lane_transition",
                    "estimate": evidence_estimate,
                }
            )
            continue
        candidate_edges = (
            candidate_estimate.get("incoming_edge_id"),
            candidate_estimate.get("outgoing_edge_id"),
        )
        evidence_edges = (
            evidence_estimate.get("incoming_edge_id"),
            evidence_estimate.get("outgoing_edge_id"),
        )
        if candidate_edges != evidence_edges:
            failures.append(
                {
                    "junction_id": junction_id,
                    "reason": "candidate_evidence_boundary_edge_mismatch",
                    "candidate_edges": candidate_edges,
                    "evidence_edges": evidence_edges,
                }
            )
            continue
        if present_excluded_branch_edge_ids:
            failures.append(
                {
                    "junction_id": junction_id,
                    "reason": "declared_excluded_branch_is_present_in_candidate",
                    "edge_ids": present_excluded_branch_edge_ids,
                }
            )
            continue

        junction = candidate_root.find(f"junction[@id='{junction_id}']")
        if junction is None:  # defensive; the estimator already checks this
            failures.append({"junction_id": junction_id, "reason": "junction_not_found"})
            continue
        old_shape = junction.attrib.get("shape", "")
        new_shape = str(candidate_estimate["estimated_shape"])
        junction.set("shape", new_shape)
        junction.set("customShape", "true")
        repairs.append(
            {
                "junction_id": junction_id,
                "old_shape": old_shape,
                "new_shape": new_shape,
                "polygon_area_m2": candidate_estimate["polygon_area_m2"],
                "incoming_edge_id": candidate_estimate["incoming_edge_id"],
                "outgoing_edge_id": candidate_estimate["outgoing_edge_id"],
                "incoming_lane_count": candidate_estimate["incoming_lane_count"],
                "outgoing_lane_count": candidate_estimate["outgoing_lane_count"],
                "straight_connection_signatures": candidate_estimate["straight_connection_signatures"],
                "evidence_road_identity": evidence_estimate["road_identity"],
                "declared_excluded_branch_edge_ids": excluded_branch_edge_ids,
            }
        )

    if failures:
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "candidate_net_file": str(candidate_net_file),
            "evidence_net_file": str(evidence_net_file),
            "output_file": str(output_file),
            "requested_junction_ids": sorted(junction_ids),
            "repair_count": len(repairs),
            "failure_count": len(failures),
            "failures": failures,
            "policy": "fail closed; no output written when any selected transition lacks evidence",
        }

    topology_after = _junction_shape_repair_topology_sha256(candidate_root)
    if topology_before != topology_after:
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "reason": "junction_shape_repair_changed_network_topology",
            "topology_sha256_before": topology_before,
            "topology_sha256_after": topology_after,
        }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(candidate_root, space="    ")
    candidate_tree.write(output_file, encoding="utf-8", xml_declaration=True)
    source_sha256_after = hashlib.sha256(candidate_net_file.read_bytes()).hexdigest()
    status = "pass" if source_sha256_after == source_sha256 else "fail"
    return {
        "status": status,
        "claim_status": "diagnostic-demo" if status == "pass" else "construction-invalid",
        "candidate_net_file": str(candidate_net_file),
        "candidate_sha256": source_sha256,
        "candidate_sha256_after": source_sha256_after,
        "source_network_mutation": source_sha256_after != source_sha256,
        "evidence_net_file": str(evidence_net_file),
        "output_file": str(output_file),
        "output_sha256": hashlib.sha256(output_file.read_bytes()).hexdigest(),
        "topology_sha256_before": topology_before,
        "topology_sha256_after": topology_after,
        "repair_count": len(repairs),
        "repairs": repairs,
        "failure_count": 0,
        "failures": [],
        "policy": (
            "Ingolstadt-style boundary repair: retain the linear lane transition and all movements; "
            "replace only the authorized junction polygon with the adjacent-lane endpoint hull"
        ),
    }


def write_authorized_junction_shapes_from_reference(
    *,
    candidate_net_file: Path,
    reference_net_file: Path,
    output_file: Path,
    junction_ids: set[str],
) -> dict[str, object]:
    """Copy only explicitly authorized junction polygons from a reference net.

    The reference must describe the same external edges, lanes, movements,
    junction owners, and TLS programs.  Geometry-only values that SUMO may
    recalculate (lane ``shape``/``length``, junction ``shape``/``intLanes``,
    connection ``via``/``state``) are deliberately excluded from that
    reference identity check.  The output still preserves every candidate
    edge, lane, connection, internal artifact, and TLS byte-for-byte at the
    XML attribute level; only the selected normal junction ``shape`` and
    ``customShape`` attributes may change.

    This is a scoped controller primitive, not an automatic topology repair.
    It never scans for targets and does not authorize joins or movements.
    """

    missing = [
        str(path)
        for path in (candidate_net_file, reference_net_file)
        if not path.exists()
    ]
    if missing:
        return _failure(f"missing input file(s): {', '.join(missing)}")
    requested_junction_ids = sorted({str(value) for value in junction_ids if str(value)})
    if not requested_junction_ids:
        return _failure("at least one evidence-authorized junction id is required")
    if any(junction_id.startswith(":") for junction_id in requested_junction_ids):
        return _failure("internal junction ids are not valid shape-copy targets")

    candidate_net_file = candidate_net_file.resolve()
    reference_net_file = reference_net_file.resolve()
    output_file = output_file.resolve()
    if output_file in {candidate_net_file, reference_net_file}:
        return _failure("output file must differ from candidate and reference inputs")
    candidate_sha256 = hashlib.sha256(candidate_net_file.read_bytes()).hexdigest()
    reference_sha256 = hashlib.sha256(reference_net_file.read_bytes()).hexdigest()
    candidate_tree = ET.parse(candidate_net_file)
    candidate_root = candidate_tree.getroot()
    reference_root = ET.parse(reference_net_file).getroot()

    candidate_junctions = {
        junction.attrib["id"]: junction
        for junction in candidate_root.findall("junction")
        if junction.attrib.get("id") and not junction.attrib["id"].startswith(":")
    }
    reference_junctions = {
        junction.attrib["id"]: junction
        for junction in reference_root.findall("junction")
        if junction.attrib.get("id") and not junction.attrib["id"].startswith(":")
    }
    candidate_edge_lane_signature = edge_lane_signature(candidate_net_file)
    reference_edge_lane_signature = edge_lane_signature(reference_net_file)
    connection_audit = audit_alias_normalized_connections(
        candidate_net_file,
        reference_net_file,
    )
    candidate_tls_sha256 = _junction_shape_tls_sha256(candidate_root)
    reference_tls_sha256 = _junction_shape_tls_sha256(reference_root)
    reference_failures: list[dict[str, object]] = []
    if candidate_edge_lane_signature != reference_edge_lane_signature:
        reference_failures.append(
            {
                "reason": "external_edge_lane_signature_mismatch",
                "candidate": candidate_edge_lane_signature,
                "reference": reference_edge_lane_signature,
            }
        )
    connection_failure_fields = (
        "normal_missing_count",
        "normal_extra_count",
        "controlled_missing_count",
        "controlled_extra_count",
    )
    if any(int(connection_audit.get(field, 0) or 0) for field in connection_failure_fields):
        reference_failures.append(
            {
                "reason": "external_movement_signature_mismatch",
                "connection_audit": connection_audit,
            }
        )
    if candidate_tls_sha256 != reference_tls_sha256:
        reference_failures.append(
            {
                "reason": "tls_program_signature_mismatch",
                "candidate_tls_sha256": candidate_tls_sha256,
                "reference_tls_sha256": reference_tls_sha256,
            }
        )
    selected_junction_identity_attrs = ("id", "type", "x", "y", "tl", "incLanes")
    for junction_id in requested_junction_ids:
        candidate_junction = candidate_junctions.get(junction_id)
        reference_junction = reference_junctions.get(junction_id)
        if candidate_junction is None or reference_junction is None:
            reference_failures.append(
                {
                    "junction_id": junction_id,
                    "reason": "junction_missing_from_candidate_or_reference",
                    "candidate_present": candidate_junction is not None,
                    "reference_present": reference_junction is not None,
                }
            )
            continue
        candidate_identity = {
            attr: candidate_junction.attrib.get(attr, "")
            for attr in selected_junction_identity_attrs
        }
        reference_identity = {
            attr: reference_junction.attrib.get(attr, "")
            for attr in selected_junction_identity_attrs
        }
        if candidate_identity != reference_identity:
            reference_failures.append(
                {
                    "junction_id": junction_id,
                    "reason": "selected_junction_identity_mismatch",
                    "candidate": candidate_identity,
                    "reference": reference_identity,
                }
            )
    if reference_failures:
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "reason": "candidate_reference_topology_mismatch",
            "candidate_net_file": str(candidate_net_file),
            "candidate_sha256": candidate_sha256,
            "reference_net_file": str(reference_net_file),
            "reference_sha256": reference_sha256,
            "output_file": str(output_file),
            "candidate_edge_lane_signature": candidate_edge_lane_signature,
            "reference_edge_lane_signature": reference_edge_lane_signature,
            "connection_audit": connection_audit,
            "candidate_tls_sha256": candidate_tls_sha256,
            "reference_tls_sha256": reference_tls_sha256,
            "reference_failure_count": len(reference_failures),
            "reference_failures": reference_failures,
            "policy": "fail closed; reference geometry must come from the same external topology",
        }

    failures: list[dict[str, object]] = []
    repairs: list[dict[str, object]] = []
    topology_before = _junction_shape_repair_topology_sha256(candidate_root)
    for junction_id in requested_junction_ids:
        candidate_junction = candidate_junctions.get(junction_id)
        reference_junction = reference_junctions.get(junction_id)
        if candidate_junction is None or reference_junction is None:  # proven above
            raise AssertionError("selected junction identity validation was bypassed")
        reference_shape = str(reference_junction.attrib.get("shape", "")).strip()
        reference_points = _shape_points(reference_shape)
        if len(set(reference_points)) < 2 or any(
            not math.isfinite(value) for point in reference_points for value in point
        ):
            failures.append(
                {
                    "junction_id": junction_id,
                    "reason": "reference_junction_shape_has_fewer_than_two_points",
                    "reference_shape": reference_shape,
                }
            )
            continue
        old_shape = str(candidate_junction.attrib.get("shape", ""))
        old_custom_shape = candidate_junction.attrib.get("customShape")
        candidate_junction.set("shape", reference_shape)
        candidate_junction.set("customShape", "true")
        repairs.append(
            {
                "junction_id": junction_id,
                "old_shape": old_shape,
                "new_shape": reference_shape,
                "old_custom_shape": old_custom_shape,
                "new_custom_shape": "true",
            }
        )

    if failures:
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "candidate_net_file": str(candidate_net_file),
            "reference_net_file": str(reference_net_file),
            "output_file": str(output_file),
            "requested_junction_ids": requested_junction_ids,
            "repair_count": len(repairs),
            "failure_count": len(failures),
            "failures": failures,
            "policy": "fail closed; no output written when any selected junction lacks a usable shape",
        }

    topology_after = _junction_shape_repair_topology_sha256(candidate_root)
    if topology_before != topology_after:
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "reason": "junction_shape_copy_changed_network_topology",
            "topology_sha256_before": topology_before,
            "topology_sha256_after": topology_after,
        }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(candidate_root, space="    ")
    candidate_tree.write(output_file, encoding="utf-8", xml_declaration=True)
    candidate_sha256_after = hashlib.sha256(candidate_net_file.read_bytes()).hexdigest()
    reference_sha256_after = hashlib.sha256(reference_net_file.read_bytes()).hexdigest()
    source_network_mutation = (
        candidate_sha256_after != candidate_sha256 or reference_sha256_after != reference_sha256
    )
    status = "pass" if not source_network_mutation else "fail"
    return {
        "status": status,
        "claim_status": "diagnostic-demo" if status == "pass" else "construction-invalid",
        "promotion_status": "review_required",
        "candidate_net_file": str(candidate_net_file),
        "candidate_sha256": candidate_sha256,
        "candidate_sha256_after": candidate_sha256_after,
        "reference_net_file": str(reference_net_file),
        "reference_sha256": reference_sha256,
        "reference_sha256_after": reference_sha256_after,
        "source_network_mutation": source_network_mutation,
        "output_file": str(output_file),
        "output_sha256": hashlib.sha256(output_file.read_bytes()).hexdigest(),
        "requested_junction_ids": requested_junction_ids,
        "candidate_edge_lane_signature": candidate_edge_lane_signature,
        "reference_edge_lane_signature": reference_edge_lane_signature,
        "connection_audit": connection_audit,
        "candidate_tls_sha256": candidate_tls_sha256,
        "reference_tls_sha256": reference_tls_sha256,
        "topology_sha256_before": topology_before,
        "topology_sha256_after": topology_after,
        "repair_count": len(repairs),
        "repairs": repairs,
        "failure_count": 0,
        "failures": [],
        "policy": (
            "copy only explicitly authorized normal-junction shapes from a hash-bound "
            "same-topology reference; preserve every candidate edge, lane, movement, and TLS"
        ),
    }


def _estimate_linear_lane_transition_shape(root: ET.Element, junction_id: str) -> dict[str, object]:
    junction = root.find(f"junction[@id='{junction_id}']")
    if junction is None:
        return {"status": "fail", "reason": "junction_not_found"}
    junction_type = junction.attrib.get("type", "")
    if junction_type.startswith("traffic_light") or junction.attrib.get("tl"):
        return {"status": "fail", "reason": "junction_is_signal_controlled", "junction_type": junction_type}

    external_edges = [
        edge
        for edge in root.findall("edge")
        if edge.attrib.get("id")
        and edge.attrib.get("function") not in {"internal", "crossing", "walkingarea"}
        and junction_id in (edge.attrib.get("from"), edge.attrib.get("to"))
        and _edge_is_vehicle_continuation_candidate(edge)
    ]
    incoming = [edge for edge in external_edges if edge.attrib.get("to") == junction_id]
    outgoing = [edge for edge in external_edges if edge.attrib.get("from") == junction_id]
    if len(incoming) != 1 or len(outgoing) != 1:
        return {
            "status": "fail",
            "reason": "transition_requires_one_vehicle_incoming_and_one_vehicle_outgoing_edge",
            "incoming_edge_ids": sorted(edge.attrib.get("id", "") for edge in incoming),
            "outgoing_edge_ids": sorted(edge.attrib.get("id", "") for edge in outgoing),
        }
    incoming_edge = incoming[0]
    outgoing_edge = outgoing[0]
    incoming_lanes = incoming_edge.findall("lane")
    outgoing_lanes = outgoing_edge.findall("lane")
    if not incoming_lanes or not outgoing_lanes or len(incoming_lanes) == len(outgoing_lanes):
        return {
            "status": "fail",
            "reason": "transition_requires_nonzero_lane_count_change",
            "incoming_lane_count": len(incoming_lanes),
            "outgoing_lane_count": len(outgoing_lanes),
        }

    incoming_edge_id = incoming_edge.attrib["id"]
    outgoing_edge_id = outgoing_edge.attrib["id"]
    relevant_connections = [
        connection
        for connection in root.findall("connection")
        if connection.attrib.get("from") == incoming_edge_id
    ]
    straight_connections = [
        connection
        for connection in relevant_connections
        if connection.attrib.get("to") == outgoing_edge_id
        and connection.attrib.get("dir", "s") == "s"
        and not connection.attrib.get("tl")
    ]
    if len(straight_connections) != min(len(incoming_lanes), len(outgoing_lanes)) or len(
        straight_connections
    ) != len(relevant_connections):
        return {
            "status": "fail",
            "reason": "transition_movements_are_not_complete_uncontrolled_straight_connections",
            "relevant_connection_count": len(relevant_connections),
            "straight_connection_count": len(straight_connections),
        }

    endpoint_points: list[tuple[float, float]] = []
    for lane in incoming_lanes:
        points = _shape_points(lane.attrib.get("shape", "") or incoming_edge.attrib.get("shape", ""))
        if points:
            endpoint_points.append(points[-1])
    for lane in outgoing_lanes:
        points = _shape_points(lane.attrib.get("shape", "") or outgoing_edge.attrib.get("shape", ""))
        if points:
            endpoint_points.append(points[0])
    hull = _convex_hull(endpoint_points)
    polygon_area = _polygon_area(hull)
    if len(endpoint_points) != len(incoming_lanes) + len(outgoing_lanes) or len(hull) < 3 or polygon_area <= 0:
        return {
            "status": "fail",
            "reason": "adjacent_lane_endpoints_do_not_form_nonzero_polygon",
            "endpoint_count": len(endpoint_points),
            "hull_point_count": len(hull),
            "polygon_area_m2": polygon_area,
        }

    return {
        "status": "pass",
        "junction_id": junction_id,
        "junction_type": junction_type,
        "incoming_edge_id": incoming_edge_id,
        "outgoing_edge_id": outgoing_edge_id,
        "incoming_lane_count": len(incoming_lanes),
        "outgoing_lane_count": len(outgoing_lanes),
        "straight_connection_signatures": sorted(
            (
                connection.attrib.get("fromLane", "0"),
                connection.attrib.get("toLane", "0"),
                connection.attrib.get("dir", "s"),
            )
            for connection in straight_connections
        ),
        "road_identity": {
            attr: (incoming_edge.attrib.get(attr), outgoing_edge.attrib.get(attr))
            for attr in ("name", "type", "priority", "spreadType")
        },
        "endpoint_count": len(endpoint_points),
        "estimated_shape": " ".join(f"{x:.2f},{y:.2f}" for x, y in hull),
        "polygon_area_m2": round(polygon_area, 6),
    }




def _junction_shape_repair_topology_sha256(root: ET.Element) -> str:
    payload = {
        "edges": [
            {
                "attributes": sorted(edge.attrib.items()),
                "lanes": [sorted(lane.attrib.items()) for lane in edge.findall("lane")],
            }
            for edge in root.findall("edge")
        ],
        "connections": [sorted(connection.attrib.items()) for connection in root.findall("connection")],
        "junctions": [
            {
                "attributes": sorted(
                    (key, value)
                    for key, value in junction.attrib.items()
                    if key not in {"shape", "outlineShape", "customShape"}
                ),
                "children": [_xml_element_semantic_payload(child) for child in list(junction)],
            }
            for junction in root.findall("junction")
        ],
        "tlLogic": [_xml_element_semantic_payload(logic) for logic in root.findall("tlLogic")],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _junction_shape_tls_sha256(root: ET.Element) -> str:
    payload = sorted(
        (_xml_element_semantic_payload(logic) for logic in root.findall("tlLogic")),
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
    )
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _xml_element_semantic_payload(element: ET.Element) -> dict[str, object]:
    """Return an XML semantic payload that ignores indentation and tail text."""

    return {
        "tag": element.tag,
        "attributes": sorted(element.attrib.items()),
        "children": [_xml_element_semantic_payload(child) for child in list(element)],
    }

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
from .junction_teacher_model import extract_teacher_junction_model
from .official_tls_rebuild import edge_lane_signature
from .junction_rebuild_tail import (  # noqa: F401 - compatibility re-export
    _accepted_target_internal_replay_entry,
    _add_green_phases_for_links,
    _append_edge_lanes_to_destination_junction,
    _apply_teacher_pedestrian_internal_geometry,
    _approach_edge_signature,
    _approach_edge_signatures,
    _approach_endpoint_rebuild_plan,
    _approach_endpoint_signatures,
    _approaches,
    _attach_junction_pattern_delta,
    _augment_candidate_edge_map_from_tls_approach_pairs,
    _blend_geometry_anchor_at_endpoint,
    _blend_geometry_anchor_at_target,
    _blocking_removed_stale_boundary_connection_count,
    _blocking_removed_stale_connection_count,
    _candidate_junction_id_candidates,
    _candidate_nodes_from_exact_teacher_approach_edges,
    _candidate_requests_target_internal_replay,
    _capacity_gap_records,
    _case_boundary_edge_map,
    _clone_transformed_boundary_junction,
    _clone_transformed_junction,
    _command_report,
    _compare_teacher_models,
    _connection_key,
    _connection_key_record,
    _connection_link_indices,
    _connection_link_indices_fit,
    _connection_max_link_index,
    _connection_touches_any_edge,
    _connection_touches_walkingarea_internal,
    _context_count_delta,
    _controlled_link_count,
    _controlled_link_index_stats,
    _controlled_link_signature_group,
    _controlled_link_signatures,
    _controlled_pedestrian_link_signatures,
    _controlled_tls_connection_count,
    _controlled_vehicle_link_signatures,
    _copy_referenced_tllogics,
    _copy_teacher_walkingareas,
    _copyable_missing_teacher_edge_ids,
    _crossing_geometry_signatures,
    _crossing_signatures,
    _demote_teacher_absent_context_tls,
    _dict_mismatch_count,
    _drop_endpoint_mismatched_edge_map_entries,
    _edge_geometry_matches_current_junctions,
    _edge_is_vehicle_continuation_candidate,
    _edge_lane_shapes,
    _edge_map_from_approach_endpoint_rebuild_plan,
    _edge_touches_context,
    _endpoint_rewrite_old_endpoint_ids,
    _estimate_linear_lane_transition_shape,
    _expand_junction_shape_to_approach_endpoints,
    _expanded_scope_followup_candidate_for_unsafe_internal_replay,
    _expanded_scope_skip_entry,
    _failure,
    _final_composite_parity_gate,
    _final_context_parity_gate,
    _format_xy,
    _hybrid_osm_approach_authority_policy,
    _internal_connection_signatures,
    _internal_edge_signature,
    _internal_edge_signatures,
    _internal_junction_signatures,
    _join_internal_self_loop_drop_has_witness,
    _join_patch_endpoint_rewrites,
    _join_patch_joined_node_ids,
    _join_shape_text,
    _joined_endpoint_self_loop_edge_ids,
    _joined_source_node_ids,
    _junction_signature,
    _lane_length_signature,
    _load_geometry_anchor_edge_ids,
    _load_teacher_join_groups_by_cluster,
    _local_junction_context_summary,
    _map_connection_endpoint,
    _map_lane_ref,
    _map_teacher_pedestrian_endpoint,
    _mapped_connection_attrs,
    _mapped_endpoint,
    _mapped_internal_ref,
    _mapped_junction_attrs,
    _mapped_junction_ref,
    _mapped_lane_ref,
    _mapped_lane_refs,
    _mapped_spatial_attrs,
    _missing_teacher_movement_plan,
    _model_junction_origin,
    _model_shape_delta,
    _model_tls_id,
    _needed_unmapped_teacher_boundary_edges,
    _net_junction_ids,
    _pad_tllogic_state_lengths,
    _pedestrian_crossing_delta_count,
    _pedestrian_tl_pairs_from_connections,
    _pedestrian_tl_pairs_from_records,
    _phase_has_green_for_index,
    _polyline_length,
    _preserve_mapped_boundary_geometry,
    _queue_candidate_dir,
    _record_linkindex_capacity_gap,
    _relative_shape,
    _remove_edge_lanes_from_destination_junction,
    _remove_teacher_non_tls_tllogics,
    _request_signatures,
    _restore_existing_edge_geometry,
    _restore_external_boundary_connections,
    _restore_false_traffic_light_junction_types,
    _restore_joined_split_edge_geometry,
    _restore_non_target_internal_artifacts,
    _restore_replayed_geometry_attrs,
    _road_continuity_probe_summary,
    _root_vehicle_outgoing_by_lane,
    _safe_stage_name,
    _same_family_continuation_edge_map,
    _same_id_pattern_cases,
    _same_id_tls_matches_teacher,
    _same_id_tls_mismatch_cases,
    _semantic_layer_for_field,
    _semantic_layer_gates,
    _shape_endpoints,
    _shape_points,
    _split,
    _stale_case_edge_map_entries,
    _target_internal_replay_input_file,
    _teacher_approach_edge_ids,
    _teacher_boundary_edge_ids_touching_internal_subgraph,
    _teacher_boundary_edge_needs_replay,
    _teacher_candidate_edge_map,
    _teacher_guided_case_sort_key,
    _teacher_guided_repair_candidate,
    _teacher_guided_semantics_gate,
    _teacher_parity_summary,
    _tl_logic_insert_index,
    _tl_phase_signatures,
    _tllogic_min_state_length_by_id,
    _tls_repair_candidates,
    _topology_fragmented_non_tls_cases,
    _topology_fragmented_tls_cases,
    _touches_target_pedestrian_ring,
    _touches_target_replay_scope,
    _translate_shape,
    _translated_edge_lane_shapes,
    _translated_lane_attrs,
    _turnaround_only_lane_cases,
    _turnaround_only_lane_gaps,
    _uncontrolled_pedestrian_connection_signatures,
    _unique_connections_by_key,
    _variant_exception_report,
    _vehicle_connection_signature,
    _vehicle_outgoing_by_lane,
    _via_lane_edge_id,
    _walking_area_signatures,
    _warp_anchor_shape_to_teacher_endpoint,
    _write_joined_endpoint_connection_file,
    _write_joined_endpoint_edge_file,
    _write_replay_node_file,
    _write_teacher_guided_report,
    build_rebuild_candidate,
    build_scoped_teacher_tls_cell_replay_plan,
    build_shared_teacher_tls_controller_replay_plan,
    build_tls_connection_repair_variant,
    restore_off_scope_netconvert_artifacts,
    restore_scoped_pedestrian_internal_semantics_after_normalize,
    restore_teacher_tls_connection_semantics_after_normalize,
    write_expanded_scope_plain_inputs,
    write_missing_edge_type_patch,
    write_teacher_connection_plan,
    write_teacher_endpoint_patch_nodes,
    write_teacher_lane_patch_edges,
    write_teacher_pedestrian_ring_net,
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

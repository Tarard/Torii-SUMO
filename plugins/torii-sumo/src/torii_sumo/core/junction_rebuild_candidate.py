from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import shutil
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from shapely import concave_hull
from shapely.geometry import MultiPoint, Point, Polygon
from sumolib.net.lane import get_allowed as _sumo_get_allowed

from .command_runner import run_command
from .corridor_simplification import (
    audit_alias_normalized_connections,
    build_corridor_geometry_simplification_variant,
)
from .external_micro_junction_audit import audit_external_micro_junctions
from .junction_connection_audit import (
    build_connection_signature,
    compare_pedestrian_crossing_signatures,
    compare_tls_movement_signatures,
    write_connection_signature,
)
from .junction_join_definition import build_junction_join_definition
from .junction_movement_model import audit_movement_graph, build_movement_graph, write_movement_review
from .junction_teacher_model import (
    _extract_teacher_junction_model,
    extract_junction_pattern_exemplar,
    extract_teacher_junction_model,
    match_teacher_approaches,
    materialize_exemplar_movement_signatures,
    slot_edge_map_from_exemplar,
)
from .official_tls_rebuild import edge_lane_signature
from .surface_overlap_audit import (
    SURFACE_OVERLAP_AUDIT_SCHEMA,
    audit_sumo_lane_junction_surface_overlaps,
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
ROAD_MOTORIZED_CLASSES = frozenset(
    {
        "passenger",
        "private",
        "hov",
        "bus",
        "coach",
        "truck",
        "trailer",
        "motorcycle",
        "moped",
        "taxi",
        "delivery",
        "emergency",
        "authority",
        "army",
        "vip",
        "evehicle",
    }
)


def _sumo_allowed_classes(attrs: dict[str, object]) -> set[str]:
    allow = str(attrs.get("allow", "")).strip()
    disallow = str(attrs.get("disallow", "")).strip()
    classes = set(
        _sumo_get_allowed(
            None if not allow or allow.lower() == "all" else allow,
            None,
        )
    )
    if disallow.lower() == "all":
        return set()
    return classes - set(disallow.split())


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


def build_teacher_guided_repair_queue(
    *,
    teacher_net_file: Path,
    candidate_net_file: Path,
    reference_join_audit_report: dict[str, Any],
    output_dir: Path,
    prefix: str = "teacher_guided_repair",
    max_ready_candidates: int | None = None,
    target_junction_ids: list[str] | None = None,
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
    candidate_edges_by_id = {
        edge.attrib["id"]: edge for edge in candidate_root.findall("edge") if edge.attrib.get("id")
    }
    candidate_edge_ids = set(candidate_edges_by_id)
    target_ids = {str(item).strip() for item in target_junction_ids or [] if str(item).strip()}
    matched_cases = [
        case for case in reference_join_audit_report.get("matched_cases", []) or [] if isinstance(case, dict)
    ]
    if target_ids:
        matched_cases = [
            case
            for case in matched_cases
            if str(case.get("reference_id", "")) in target_ids
            or str(case.get("junction_id", "")) in target_ids
        ]
    pattern_deltas = _junction_pattern_delta_by_id(reference_join_audit_report)
    pattern_records = _junction_pattern_record_by_id(reference_join_audit_report)
    pattern_templates = _junction_pattern_template_by_key(reference_join_audit_report)
    same_id_pattern_cases = _same_id_pattern_cases(
        pattern_deltas,
        matched_cases,
        teacher_root,
        candidate_root,
        target_ids,
    )
    same_id_tls_cases = _same_id_tls_mismatch_cases(
        [*matched_cases, *same_id_pattern_cases],
        teacher_root,
        candidate_root,
        teacher_net_file,
        candidate_net_file,
        target_ids,
    )
    matched_cases = [*matched_cases, *same_id_pattern_cases, *same_id_tls_cases]
    topology_fragmented_tls_cases = _topology_fragmented_tls_cases(
        matched_cases,
        teacher_root,
        candidate_root,
        teacher_net_file,
        candidate_edges_by_id,
        target_ids,
    )
    matched_cases = [*matched_cases, *topology_fragmented_tls_cases]
    topology_fragmented_non_tls_cases = _topology_fragmented_non_tls_cases(
        matched_cases,
        teacher_root,
        candidate_root,
        teacher_net_file,
        candidate_edges_by_id,
        target_ids,
    )
    matched_cases = [*matched_cases, *topology_fragmented_non_tls_cases]
    turnaround_only_lane_cases = _turnaround_only_lane_cases(
        matched_cases,
        teacher_root,
        candidate_root,
        target_ids,
    )
    matched_cases = [*matched_cases, *turnaround_only_lane_cases]
    matched_cases.sort(key=lambda case: _teacher_guided_case_sort_key(case, pattern_records, pattern_templates))
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
                    dict(item) for item in tls_alignment.get("approach_pairs", []) or [] if isinstance(item, dict)
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
        tl_logic.attrib["id"] for tl_logic in candidate_root.findall("tlLogic") if tl_logic.attrib.get("id")
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
            padded_tllogic_link_indices.setdefault(target_tls_id, set()).update(
                _connection_link_indices(source_connection)
            )
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
    generate_structural_connections: bool = False,
    structural_junction_ids: Sequence[str] = (),
) -> dict[str, object]:
    crossing_edge_overrides = crossing_edge_overrides or {}
    crossing_node_ids = crossing_node_ids or set()
    output_file.parent.mkdir(parents=True, exist_ok=True)

    incoming = _approach_edges(candidate_model, "incoming")
    outgoing = _approach_edges(candidate_model, "outgoing")
    candidate_lane_counts = _candidate_lane_counts(candidate_model)
    candidate_vehicle_lane_indices: dict[str, set[int]] | None = None
    candidate_lane_classes: dict[str, dict[int, set[str]]] = {}
    present_candidate_edges: set[str] | None = None
    if candidate_edge_file is not None:
        patched_lane_counts = _edge_file_lane_counts(candidate_edge_file)
        candidate_vehicle_lane_indices = _edge_file_vehicle_lane_indices(candidate_edge_file)
        candidate_lane_classes = _edge_file_lane_classes(candidate_edge_file)
        candidate_lane_counts.update(patched_lane_counts)
        present_candidate_edges = set(patched_lane_counts)
        incoming = [edge for edge in incoming if edge in present_candidate_edges]
        outgoing = [edge for edge in outgoing if edge in present_candidate_edges]
    patched_edge_endpoints = _plain_edge_endpoints(candidate_edge_file) if candidate_edge_file is not None else {}
    teacher_evidence_edge_ids = {
        str(row.get("edge_id", ""))
        for direction in ("incoming", "outgoing")
        for row in (teacher_model.get("approaches", {}).get(direction, []) if isinstance(teacher_model.get("approaches"), dict) else [])
        if isinstance(row, dict) and str(row.get("edge_id", ""))
    }
    teacher_evidence_edge_ids.update(
        str(connection.get(endpoint, ""))
        for connection in (teacher_model.get("vehicle_connections", []) or [])
        if isinstance(connection, dict)
        for endpoint in ("from", "to")
        if str(connection.get(endpoint, ""))
    )
    teacher_authority_candidate_edges = {
        edge_map.get(edge_id, edge_id) for edge_id in teacher_evidence_edge_ids if edge_map.get(edge_id, edge_id)
    }
    structural_scope = {junction_id, *(str(value) for value in structural_junction_ids if str(value))}
    if generate_structural_connections and structural_junction_ids and patched_edge_endpoints:
        incoming = [
            edge_id
            for edge_id, (_, target) in patched_edge_endpoints.items()
            if target in structural_scope and edge_id in teacher_authority_candidate_edges
        ]
        outgoing = [
            edge_id
            for edge_id, (source, _) in patched_edge_endpoints.items()
            if source in structural_scope and edge_id in teacher_authority_candidate_edges
        ]
    target_incoming_edges = set(incoming)
    target_outgoing_edges = set(outgoing)
    teacher_vehicle_lane_indices = _model_vehicle_lane_indices(teacher_model)

    raw_root = ET.parse(raw_connection_file).getroot()
    connected_lanes_by_source: dict[str, set[int]] = {}
    connected_lanes_by_target: dict[str, set[int]] = {}
    if generate_structural_connections:
        for child in raw_root.findall("connection"):
            source = child.attrib.get("from", "")
            target = child.attrib.get("to", "")
            if source not in target_incoming_edges or target not in target_outgoing_edges:
                continue
            if target == _opposite_direction_edge_id(source):
                continue
            if present_candidate_edges is not None and (
                source not in present_candidate_edges
                or target not in present_candidate_edges
                or not _connection_lane_indices_valid(child, candidate_lane_counts)
                or not _connection_edges_are_adjacent(child, patched_edge_endpoints)
            ):
                continue
            source_lane = int(child.attrib.get("fromLane", "0") or 0)
            target_lane = int(child.attrib.get("toLane", "0") or 0)
            if not (
                candidate_lane_classes.get(source, {}).get(source_lane, set())
                & candidate_lane_classes.get(target, {}).get(target_lane, set())
                & _sumo_allowed_classes(dict(child.attrib))
                & ROAD_MOTORIZED_CLASSES
            ):
                continue
            connected_lanes_by_source.setdefault(source, set()).add(source_lane)
            connected_lanes_by_target.setdefault(target, set()).add(target_lane)
    structural_missing_lanes_by_source = {
        source: (
            candidate_vehicle_lane_indices.get(source, set())
            if candidate_vehicle_lane_indices is not None
            else set(range(candidate_lane_counts.get(source, 0)))
        )
        - connected_lanes_by_source.get(source, set())
        for source in target_incoming_edges
    }
    structural_missing_lanes_by_source = {
        source: lanes for source, lanes in structural_missing_lanes_by_source.items() if lanes
    }
    structural_missing_lanes_by_target = {
        target: (
            candidate_vehicle_lane_indices.get(target, set())
            if candidate_vehicle_lane_indices is not None
            else set(range(candidate_lane_counts.get(target, 0)))
        )
        - connected_lanes_by_target.get(target, set())
        for target in target_outgoing_edges
    }
    structural_missing_lanes_by_target = {
        target: lanes for target, lanes in structural_missing_lanes_by_target.items() if lanes
    }
    structural_regenerated_source_edges = set(structural_missing_lanes_by_source)

    root = ET.Element("connections")
    kept = 0
    removed = 0
    removed_invalid_lane_connections = []
    removed_nonadjacent_connections = []
    removed_nonadjacent_crossings = []
    removed_incompatible_lane_connections = []
    lane_compatibility_repairs = []
    kept_connection_keys: set[tuple[str, str, str, str]] = set()
    for child in raw_root:
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
            (
                generate_structural_connections
                and child.attrib.get("from", "") in structural_regenerated_source_edges
                and not child.attrib.get("to")
            )
            or (
                not generate_structural_connections
                and child.attrib.get("from", "") in target_incoming_edges
                and child.attrib.get("to", "") in target_outgoing_edges
            )
        ):
            removed += 1
            continue
        if child.tag == "crossing" and present_candidate_edges is not None:
            crossing_edges = set(_split(child.attrib.get("edges", "")))
            if crossing_edges and not crossing_edges <= present_candidate_edges:
                removed += 1
                continue
            crossing_node = child.attrib.get("node", "")
            nonadjacent_edges = sorted(
                edge_id
                for edge_id in crossing_edges
                if crossing_node not in patched_edge_endpoints.get(edge_id, ())
            )
            if nonadjacent_edges:
                removed_nonadjacent_crossings.append(
                    {"node": crossing_node, "edges": child.attrib.get("edges", ""), "nonadjacent_edges": nonadjacent_edges}
                )
                removed += 1
                continue
        if child.tag == "crossing" and child.attrib.get("node") == junction_id:
            removed += 1
            continue
        if child.tag == "crossing" and child.attrib.get("node") in crossing_node_ids:
            removed += 1
            continue
        if (
            child.tag == "connection"
            and generate_structural_connections
            and not child.attrib.get("tl")
            and candidate_lane_classes
            and patched_edge_endpoints
            and (
                set(patched_edge_endpoints.get(child.attrib.get("from", ""), ())) & structural_scope
                or set(patched_edge_endpoints.get(child.attrib.get("to", ""), ())) & structural_scope
            )
        ):
            source_edge_id = child.attrib.get("from", "")
            target_edge_id = child.attrib.get("to", "")
            try:
                source_lane = int(child.attrib.get("fromLane", "0"))
                target_lane = int(child.attrib.get("toLane", "0"))
            except ValueError:
                source_lane = target_lane = -1
            source_classes = candidate_lane_classes.get(source_edge_id, {}).get(source_lane, set())
            target_classes = candidate_lane_classes.get(target_edge_id, {}).get(target_lane, set())
            connection_classes = _sumo_allowed_classes(dict(child.attrib))
            if source_classes and target_classes and not source_classes & target_classes & connection_classes:
                compatible_pairs = [
                    (source_index, target_index)
                    for source_index, source_lane_classes in candidate_lane_classes.get(source_edge_id, {}).items()
                    for target_index, target_lane_classes in candidate_lane_classes.get(target_edge_id, {}).items()
                    if source_lane_classes & target_lane_classes & connection_classes
                ]
                if compatible_pairs:
                    replacement_from_lane, replacement_to_lane = min(
                        compatible_pairs,
                        key=lambda pair: (
                            abs(pair[0] - source_lane) + abs(pair[1] - target_lane),
                            pair,
                        ),
                    )
                    child.set("fromLane", str(replacement_from_lane))
                    child.set("toLane", str(replacement_to_lane))
                    lane_compatibility_repairs.append(
                        {
                            "from": source_edge_id,
                            "to": target_edge_id,
                            "fromLane": source_lane,
                            "toLane": target_lane,
                            "repaired_fromLane": replacement_from_lane,
                            "repaired_toLane": replacement_to_lane,
                        }
                    )
                else:
                    removed_incompatible_lane_connections.append(dict(child.attrib))
                    removed += 1
                    continue
        root.append(child)
        if child.tag == "connection" and child.attrib.get("to"):
            kept_connection_keys.add(
                (
                    child.attrib.get("from", ""),
                    child.attrib.get("to", ""),
                    child.attrib.get("fromLane", "0"),
                    child.attrib.get("toLane", "0"),
                )
            )
        kept += 1

    emitted_connections = 0
    emitted_uncontrolled_connections = 0
    expanded_unmapped_continuation_connections = []
    if generate_structural_connections and candidate_lane_classes and patched_edge_endpoints:
        existing_keys = {
            (
                connection.attrib.get("from", ""),
                connection.attrib.get("to", ""),
                connection.attrib.get("fromLane", "0"),
                connection.attrib.get("toLane", "0"),
            )
            for connection in root.findall("connection")
        }
        for connection in list(root.findall("connection")):
            source_edge_id = connection.attrib.get("from", "")
            target_edge_id = connection.attrib.get("to", "")
            if target_edge_id in teacher_authority_candidate_edges or connection.attrib.get("tl"):
                continue
            if not (
                set(patched_edge_endpoints.get(source_edge_id, ())) & structural_scope
                or set(patched_edge_endpoints.get(target_edge_id, ())) & structural_scope
            ):
                continue
            try:
                source_lane = int(connection.attrib.get("fromLane", "0"))
                target_lane = int(connection.attrib.get("toLane", "0"))
            except ValueError:
                continue
            source_classes = candidate_lane_classes.get(source_edge_id, {}).get(source_lane, set())
            target_classes_by_lane = candidate_lane_classes.get(target_edge_id, {})
            if not source_classes & ROAD_MOTORIZED_CLASSES:
                continue
            compatible_target_lanes = [
                lane_index
                for lane_index, lane_classes in target_classes_by_lane.items()
                if lane_classes & source_classes & ROAD_MOTORIZED_CLASSES
            ]
            if len(compatible_target_lanes) < 2 or target_lane not in compatible_target_lanes:
                continue
            for replacement_lane in sorted(compatible_target_lanes):
                if replacement_lane == target_lane:
                    continue
                expanded = copy.deepcopy(connection)
                expanded.set("toLane", str(replacement_lane))
                key = (
                    expanded.attrib.get("from", ""),
                    expanded.attrib.get("to", ""),
                    expanded.attrib.get("fromLane", "0"),
                    expanded.attrib.get("toLane", "0"),
                )
                if key in existing_keys:
                    continue
                root.append(expanded)
                existing_keys.add(key)
                expanded_unmapped_continuation_connections.append(dict(expanded.attrib))
    allowed_pairs: set[tuple[str, str]] = set()
    skipped_off_scope_pairs: set[tuple[str, str]] = set()
    seen_connections = set(kept_connection_keys)
    structural_emitted_lanes_by_source: dict[str, set[int]] = {}
    structural_emitted_lanes_by_target: dict[str, set[int]] = {}
    lane_clamps = []
    skipped_nonadjacent_teacher_connections = []
    skipped_incompatible_teacher_connections = []
    skipped_off_scope_internal_connections = []
    teacher_internal_scope_prefix = f":{teacher_internal_scope_id}_" if teacher_internal_scope_id else ""
    for connection in teacher_model.get("vehicle_connections", []) or []:
        if not isinstance(connection, dict):
            continue
        teacher_source = str(connection.get("from", ""))
        teacher_target = str(connection.get("to", ""))
        source = edge_map.get(teacher_source, teacher_source)
        target = edge_map.get(teacher_target, teacher_target)
        if not source or not target:
            continue
        via = str(connection.get("via", ""))
        if teacher_internal_scope_prefix and via.startswith(":") and not via.startswith(teacher_internal_scope_prefix):
            skipped_off_scope_pairs.add((source, target))
            skipped_off_scope_internal_connections.append(dict(connection))
            continue
        if present_candidate_edges is not None and (
            source not in present_candidate_edges or target not in present_candidate_edges
        ):
            continue
        if generate_structural_connections and present_candidate_edges is not None:
            probe = ET.Element("connection", {"from": source, "to": target})
            if not _connection_edges_are_adjacent(probe, patched_edge_endpoints):
                skipped_nonadjacent_teacher_connections.append(
                    {"from": source, "to": target, "teacher_from": teacher_source, "teacher_to": teacher_target}
                )
                continue
        original_from_lane = int(connection.get("fromLane") or 0)
        original_to_lane = int(connection.get("toLane") or 0)
        from_lane = _mapped_vehicle_lane_index(
            teacher_source,
            source,
            original_from_lane,
            teacher_vehicle_lane_indices,
            candidate_vehicle_lane_indices or {},
            candidate_lane_counts,
        )
        to_lane = _mapped_vehicle_lane_index(
            teacher_target,
            target,
            original_to_lane,
            teacher_vehicle_lane_indices,
            candidate_vehicle_lane_indices or {},
            candidate_lane_counts,
        )
        if generate_structural_connections:
            source_classes = candidate_lane_classes.get(source, {}).get(from_lane, set())
            target_classes = candidate_lane_classes.get(target, {}).get(to_lane, set())
            if source_classes and target_classes and not source_classes & target_classes:
                skipped_incompatible_teacher_connections.append(
                    {
                        "from": source,
                        "to": target,
                        "fromLane": from_lane,
                        "toLane": to_lane,
                        "teacher_from": teacher_source,
                        "teacher_to": teacher_target,
                    }
                )
                continue
        if generate_structural_connections and not (
            from_lane in structural_missing_lanes_by_source.get(source, set())
            or to_lane in structural_missing_lanes_by_target.get(target, set())
        ):
            continue
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
        structural_emitted_lanes_by_source.setdefault(source, set()).add(from_lane)
        structural_emitted_lanes_by_target.setdefault(target, set()).add(to_lane)

    unresolved_structural_lanes = {
        source: sorted(lanes - structural_emitted_lanes_by_source.get(source, set()))
        for source, lanes in structural_missing_lanes_by_source.items()
        if lanes - structural_emitted_lanes_by_source.get(source, set())
    }
    unresolved_structural_target_lanes = {
        target: sorted(lanes - structural_emitted_lanes_by_target.get(target, set()))
        for target, lanes in structural_missing_lanes_by_target.items()
        if lanes - structural_emitted_lanes_by_target.get(target, set())
    }

    emitted_deletes = 0
    if not generate_structural_connections:
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
        "status": ("fail" if unresolved_structural_lanes or unresolved_structural_target_lanes else "pass"),
        "claim_status": (
            "construction-invalid"
            if unresolved_structural_lanes or unresolved_structural_target_lanes
            else "diagnostic-demo"
        ),
        "connection_file": str(output_file),
        "kept_non_target_children": kept,
        "removed_target_children": removed,
        "removed_invalid_lane_connection_count": len(removed_invalid_lane_connections),
        "removed_invalid_lane_connections": removed_invalid_lane_connections,
        "removed_nonadjacent_connection_count": len(removed_nonadjacent_connections),
        "removed_nonadjacent_connections": removed_nonadjacent_connections,
        "removed_nonadjacent_crossing_count": len(removed_nonadjacent_crossings),
        "removed_nonadjacent_crossings": removed_nonadjacent_crossings,
        "removed_incompatible_lane_connection_count": len(removed_incompatible_lane_connections),
        "removed_incompatible_lane_connections": removed_incompatible_lane_connections,
        "lane_compatibility_repair_count": len(lane_compatibility_repairs),
        "lane_compatibility_repairs": lane_compatibility_repairs,
        "expanded_unmapped_continuation_connection_count": len(expanded_unmapped_continuation_connections),
        "expanded_unmapped_continuation_connections": expanded_unmapped_continuation_connections,
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
        "skipped_nonadjacent_teacher_connection_count": len(skipped_nonadjacent_teacher_connections),
        "skipped_nonadjacent_teacher_connections": skipped_nonadjacent_teacher_connections,
        "skipped_incompatible_teacher_connection_count": len(skipped_incompatible_teacher_connections),
        "skipped_incompatible_teacher_connections": skipped_incompatible_teacher_connections,
        "structural_connection_generation": generate_structural_connections,
        "structural_regenerated_source_edge_count": len(structural_regenerated_source_edges),
        "structural_regenerated_source_edge_ids": sorted(structural_regenerated_source_edges),
        "structural_missing_lanes_by_source": {
            source: sorted(lanes) for source, lanes in sorted(structural_missing_lanes_by_source.items())
        },
        "structural_missing_lanes_by_target": {
            target: sorted(lanes) for target, lanes in sorted(structural_missing_lanes_by_target.items())
        },
        "unresolved_structural_lanes": dict(sorted(unresolved_structural_lanes.items())),
        "unresolved_structural_target_lanes": dict(sorted(unresolved_structural_target_lanes.items())),
        "connection_authority": (
            "current OSM lane geometry plus same-bbox teacher movement audit"
            if generate_structural_connections
            else "mapped teacher movement plan"
        ),
    }


def _plain_crossing_node_id(
    default_junction_id: str,
    crossing_edges: list[str],
    edge_endpoints: dict[str, tuple[str, str]],
    crossing_node_ids: set[str],
) -> str:
    if not crossing_edges or not edge_endpoints or not crossing_node_ids:
        return default_junction_id
    shared_node_ids: set[str] | None = None
    for edge_id in crossing_edges:
        endpoints = set(edge_endpoints.get(edge_id, ())) & crossing_node_ids
        if not endpoints:
            return default_junction_id
        shared_node_ids = endpoints if shared_node_ids is None else shared_node_ids & endpoints
        if not shared_node_ids:
            return default_junction_id
    return sorted(shared_node_ids)[0] if shared_node_ids else default_junction_id


def write_teacher_lane_patch_edges(
    *,
    raw_edge_file: Path,
    teacher_edge_file: Path,
    output_file: Path,
    edge_map: dict[str, str],
    junction_id: str | None = None,
    teacher_junction_id: str | None = None,
    boundary_node_ids: set[str] | None = None,
    rebase_teacher_target_to_join_source: bool = True,
    prune_unmapped_boundary_edges: bool = False,
    approach_endpoint_rebuild_plan: object | None = None,
    lane_shape_delta: tuple[float, float] | None = None,
    preserve_lane_shapes: bool = True,
    preserve_osm_lane_profiles: bool = False,
) -> dict[str, object]:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if preserve_osm_lane_profiles:
        shutil.copyfile(raw_edge_file, output_file)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "edge_file": str(output_file),
            "patched_edge_count": 0,
            "patched_edges": [],
            "added_missing_mapped_edge_count": 0,
            "added_missing_mapped_edges": [],
            "rebased_existing_mapped_edge_count": 0,
            "rebased_existing_mapped_edges": [],
            "rebased_missing_mapped_edge_count": 0,
            "rebased_missing_mapped_edges": [],
            "endpoint_rewritten_existing_mapped_edge_count": 0,
            "endpoint_rewritten_existing_mapped_edges": [],
            "endpoint_rewritten_missing_mapped_edge_count": 0,
            "endpoint_rewritten_missing_mapped_edges": [],
            "skipped_rebased_self_loop_edge_count": 0,
            "skipped_rebased_self_loop_edges": [],
            "pruned_boundary_edge_count": 0,
            "pruned_boundary_edges": [],
            "retained_unmapped_boundary_edge_count": 0,
            "retained_unmapped_boundary_edges": [],
            "lane_cardinality_changed_edge_ids": [],
            "lane_cardinality_changed_endpoint_junction_ids": [],
            "lane_shape_translation_applied": False,
            "preserve_lane_shapes": True,
            "preserve_osm_lane_profiles": True,
            "policy": (
                "structural teacher replay preserves current OSM lane count, access, width, speed, and geometry"
            ),
        }
    teacher_edges = {
        edge.attrib["id"]: edge
        for edge in ET.parse(teacher_edge_file).getroot().findall("edge")
        if edge.attrib.get("id")
    }
    teacher_by_candidate = {
        candidate_id: teacher_edges[teacher_id]
        for teacher_id, candidate_id in edge_map.items()
        if teacher_id in teacher_edges
    }

    tree = ET.parse(raw_edge_file)
    root = tree.getroot()
    patched = []
    lane_cardinality_changed_edge_ids = []
    lane_cardinality_changed_endpoint_junction_ids: set[str] = set()
    added_missing_mapped_edges = []
    pruned_boundary_edges = []
    retained_unmapped_boundary_edges = []
    remapped_teacher_edges = set(edge_map)
    teacher_same_junction_edges = {
        edge_id
        for edge_id, edge in teacher_edges.items()
        if junction_id
        and junction_id in (edge.attrib.get("from"), edge.attrib.get("to"))
        and edge_id not in remapped_teacher_edges
    }
    allowed_boundary_edges = set(edge_map.values()) | teacher_same_junction_edges
    boundary_node_ids = boundary_node_ids or set()
    join_source_node_id = (
        sorted(boundary_node_ids)[0]
        if rebase_teacher_target_to_join_source
        and teacher_junction_id
        and junction_id
        and teacher_junction_id != junction_id
        and boundary_node_ids
        else ""
    )
    teacher_junction_endpoint_policy = (
        "join_source"
        if join_source_node_id
        else "candidate_junction"
        if teacher_junction_id and junction_id and teacher_junction_id != junction_id
        else "unchanged"
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
        if len(edge.findall("lane")) != len(teacher_lanes):
            lane_cardinality_changed_edge_ids.append(edge_id)
            lane_cardinality_changed_endpoint_junction_ids.update(
                endpoint for endpoint in (edge.attrib.get("from", ""), edge.attrib.get("to", "")) if endpoint
            )
        rebased_endpoints = {}
        endpoint_rewritten = {}
        endpoint_rewrite = endpoint_rewrites.get(edge_id)
        if endpoint_rewrite is not None:
            for attr, desired_endpoint in (("from", endpoint_rewrite[0]), ("to", endpoint_rewrite[1])):
                current_endpoint = edge.attrib.get(attr, "")
                if current_endpoint != desired_endpoint:
                    edge.set(attr, desired_endpoint)
                    endpoint_rewritten[attr] = {"old": current_endpoint, "new": desired_endpoint}
        elif teacher_junction_id and junction_id and teacher_junction_id != junction_id:
            for attr in ("from", "to"):
                teacher_endpoint = teacher_edge.attrib.get(attr, "")
                if teacher_endpoint == teacher_junction_id:
                    candidate_endpoint = join_source_node_id or junction_id
                    edge.set(attr, candidate_endpoint)
                    rebased_endpoints[attr] = {"teacher": teacher_endpoint, "candidate": candidate_endpoint}
        if (
            (rebased_endpoints or endpoint_rewritten)
            and edge.attrib.get("from")
            and edge.attrib.get("from") == edge.attrib.get("to")
        ):
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
        patched.append(
            {
                "candidate_edge_id": edge.attrib.get("id", ""),
                "teacher_edge_id": teacher_edge.attrib.get("id", ""),
                "lane_count": len(teacher_lanes),
            }
        )
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
        elif teacher_junction_id and junction_id and teacher_junction_id != junction_id:
            for attr in ("from", "to"):
                teacher_endpoint = edge_attrs.get(attr, "")
                if teacher_endpoint == teacher_junction_id:
                    candidate_endpoint = join_source_node_id or junction_id
                    edge_attrs[attr] = candidate_endpoint
                    rebased_endpoints[attr] = {"teacher": teacher_endpoint, "candidate": candidate_endpoint}
        if (
            (rebased_endpoints or endpoint_rewritten)
            and edge_attrs.get("from")
            and edge_attrs.get("from") == edge_attrs.get("to")
        ):
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
        "teacher_junction_endpoint_policy": teacher_junction_endpoint_policy,
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
        "lane_cardinality_changed_edge_ids": sorted(lane_cardinality_changed_edge_ids),
        "lane_cardinality_changed_endpoint_junction_ids": sorted(lane_cardinality_changed_endpoint_junction_ids),
        "lane_shape_translation_applied": lane_shape_delta is not None,
        "preserve_lane_shapes": preserve_lane_shapes,
        "preserve_osm_lane_profiles": False,
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
                removed_lane_synthesis_attributes.append({"type_id": type_id, "attribute": attribute, "value": value})

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
        "roundtrip_lane_synthesis_attribute_removal_count": len(removed_lane_synthesis_attributes),
        "roundtrip_lane_synthesis_attribute_removals": removed_lane_synthesis_attributes,
    }


def write_teacher_endpoint_patch_nodes(
    *,
    raw_node_file: Path,
    teacher_net_file: Path,
    candidate_net_file: Path | None = None,
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
    candidate_nodes = (
        {
            junction.attrib["id"]: junction
            for junction in ET.parse(candidate_net_file).getroot().findall("junction")
            if junction.attrib.get("id") and junction.attrib.get("type") != "internal"
        }
        if candidate_net_file is not None and candidate_net_file.exists()
        else {}
    )
    added_node_ids = []
    unresolved_node_ids = []
    safe_attrs = ("id", "x", "y", "type", "shape", "radius", "keepClear", "rightOfWay", "fringe", "tl")
    dx, dy = lane_shape_delta if lane_shape_delta is not None else (0.0, 0.0)

    for node_id in missing_node_ids:
        source_node = teacher_nodes.get(node_id)
        source_is_teacher = source_node is not None
        if source_node is None:
            source_node = candidate_nodes.get(node_id)
        if source_node is None:
            unresolved_node_ids.append(node_id)
            continue
        attrs = {attr: source_node.attrib[attr] for attr in safe_attrs if source_node.attrib.get(attr)}
        attrs["id"] = node_id
        if lane_shape_delta is not None and source_is_teacher:
            if attrs.get("x"):
                attrs["x"] = _format_xy(float(attrs["x"]) + dx)
            if attrs.get("y"):
                attrs["y"] = _format_xy(float(attrs["y"]) + dy)
            if attrs.get("shape"):
                attrs["shape"] = _translate_shape(attrs["shape"], dx, dy)
        ET.SubElement(root, "node", attrs)
        added_node_ids.append(node_id)

    added_node_id_set = set(added_node_ids)
    for join in list(root.findall("join")):
        joined_node_id = _sumo_joined_cluster_id(_split(join.attrib.get("nodes", "")))
        if joined_node_id in added_node_id_set:
            root.remove(join)

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

    teacher_link_pairs = _pedestrian_tl_pairs_from_records(
        teacher_model.get("pedestrian_connections", []) or [], teacher_junction_id
    )
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
        if (
            edge_id.startswith(internal_prefix)
            and edge.attrib.get("function") == "walkingarea"
            and edge_id not in kept_walkingareas
        ):
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
        mapped_from = _map_teacher_pedestrian_endpoint(
            str(connection.get("from", "")), walkingarea_map, crossing_map, edge_map
        )
        mapped_to = _map_teacher_pedestrian_endpoint(
            str(connection.get("to", "")), walkingarea_map, crossing_map, edge_map
        )
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
        lane.attrib["id"] for edge in root.findall("edge") for lane in edge.findall("lane") if lane.attrib.get("id")
    }
    for junction in root.findall("junction"):
        if junction.attrib.get("id") != junction_id:
            continue
        for attr in ("incLanes", "intLanes"):
            junction.set(
                attr, " ".join(lane for lane in _split(junction.attrib.get(attr, "")) if lane in existing_lane_ids)
            )

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


def _copy_teacher_walkingareas(
    root: ET.Element,
    *,
    junction_id: str,
    teacher_junction_id: str,
    teacher_junction: object,
    teacher_walkingareas: object,
) -> tuple[list[tuple[str, str]], int]:
    candidate_junction = root.find(f"junction[@id='{junction_id}']")
    if (
        candidate_junction is None
        or not isinstance(teacher_junction, dict)
        or not isinstance(teacher_walkingareas, list)
    ):
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
        candidate_edge_id = next(
            (edge_map[teacher_edge_id] for edge_map in edge_maps if teacher_edge_id in edge_map), ""
        )
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


def _teacher_to_candidate_delta(root: ET.Element, junction_id: str, teacher_junction: object) -> tuple[float, float]:
    candidate_junction = root.find(f"junction[@id='{junction_id}']")
    if candidate_junction is None or not isinstance(teacher_junction, dict):
        return 0.0, 0.0
    try:
        return (
            float(candidate_junction.attrib.get("x", "0")) - float(str(teacher_junction.get("x", "0"))),
            float(candidate_junction.attrib.get("y", "0")) - float(str(teacher_junction.get("y", "0"))),
        )
    except ValueError:
        return 0.0, 0.0


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
    teacher_vehicle_lane_indices = _model_vehicle_lane_indices(teacher_model)
    candidate_vehicle_lane_indices = _root_vehicle_lane_indices(root)
    candidate_road_lane_indices = {
        edge.attrib["id"]: {
            int(lane.attrib.get("index", position))
            for position, lane in enumerate(edge.findall("lane"))
            if _sumo_allowed_classes({**edge.attrib, **lane.attrib}) & (ROAD_MOTORIZED_CLASSES | {"bicycle"})
        }
        for edge in root.findall("edge")
        if edge.attrib.get("id") and not edge.attrib.get("function")
    }
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

    def _candidate_key(
        teacher_connection: dict[str, object],
    ) -> tuple[str, str, str, str] | None:
        teacher_source = str(teacher_connection.get("from", ""))
        teacher_target = str(teacher_connection.get("to", ""))
        source = edge_map.get(teacher_source)
        target = edge_map.get(teacher_target)
        if not source or not target:
            return None
        from_lane = _mapped_vehicle_lane_index(
            teacher_source,
            source,
            int(teacher_connection.get("fromLane") or 0),
            teacher_vehicle_lane_indices,
            candidate_vehicle_lane_indices,
            lane_counts,
        )
        to_lane = _mapped_vehicle_lane_index(
            teacher_target,
            target,
            int(teacher_connection.get("toLane") or 0),
            teacher_vehicle_lane_indices,
            candidate_vehicle_lane_indices,
            lane_counts,
        )
        return source, target, str(from_lane), str(to_lane)

    teacher_connections = [
        connection for connection in teacher_model.get("vehicle_connections", []) or [] if isinstance(connection, dict)
    ]
    teacher_controlled_candidate_keys = {
        key
        for connection in teacher_connections
        if connection.get("tl") and (key := _candidate_key(connection)) is not None
    }
    updated = 0
    skipped = []
    skipped_motorized = []
    for teacher_connection in teacher_model.get("vehicle_connections", []) or []:
        if not isinstance(teacher_connection, dict):
            continue
        teacher_source = str(teacher_connection.get("from", ""))
        teacher_target = str(teacher_connection.get("to", ""))
        source = edge_map.get(teacher_source)
        target = edge_map.get(teacher_target)
        if not source or not target:
            skipped.append({"reason": "unmapped_edge", "connection": teacher_connection})
            continue
        from_lane = _mapped_vehicle_lane_index(
            teacher_source,
            source,
            int(teacher_connection.get("fromLane") or 0),
            teacher_vehicle_lane_indices,
            candidate_vehicle_lane_indices,
            lane_counts,
        )
        to_lane = _mapped_vehicle_lane_index(
            teacher_target,
            target,
            int(teacher_connection.get("toLane") or 0),
            teacher_vehicle_lane_indices,
            candidate_vehicle_lane_indices,
            lane_counts,
        )
        key = (source, target, str(from_lane), str(to_lane))
        matches = connections_by_key.get(key, [])
        if not matches:
            record = {
                "reason": "missing_candidate_connection",
                "connection": teacher_connection,
            }
            skipped.append(record)
            if int(teacher_connection.get("fromLane") or 0) in teacher_vehicle_lane_indices.get(teacher_source, []):
                skipped_motorized.append(record)
            continue
        if not teacher_connection.get("tl") and key in teacher_controlled_candidate_keys:
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
                connection.set(
                    "shape", _translate_shape(str(teacher_connection["shape"]), shape_delta[0], shape_delta[1])
                )
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

    detached_unmapped_controlled = []
    for connection in root.findall("connection"):
        if connection.attrib.get("tl") != junction_id:
            continue
        source = connection.attrib.get("from", "")
        try:
            from_lane = int(connection.attrib.get("fromLane", "0"))
        except ValueError:
            continue
        if from_lane not in candidate_road_lane_indices.get(source, set()):
            continue
        key = (
            source,
            connection.attrib.get("to", ""),
            str(from_lane),
            connection.attrib.get("toLane", "0"),
        )
        if key in teacher_controlled_candidate_keys:
            continue
        detached_unmapped_controlled.append(dict(connection.attrib))
        connection.attrib.pop("tl", None)
        connection.attrib.pop("linkIndex", None)
        connection.set("uncontrolled", "true")

    ET.indent(root, space="    ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "net_file": str(output_file),
        "updated_vehicle_connection_count": updated,
        "skipped_vehicle_connection_count": len(skipped),
        "skipped_vehicle_connections": skipped,
        "skipped_motorized_vehicle_connection_count": len(skipped_motorized),
        "skipped_motorized_vehicle_connections": skipped_motorized,
        "detached_unmapped_controlled_vehicle_connection_count": len(detached_unmapped_controlled),
        "detached_unmapped_controlled_vehicle_connections": (detached_unmapped_controlled),
    }


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
    preserve_unmapped_boundary_edges: bool = False,
    prune_unmapped_micro_boundary_edges: bool = False,
    prune_strict_unmapped_outgoing_boundary_edges: bool = False,
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
    candidate_edges_by_id = {
        edge.attrib["id"]: edge for edge in candidate_root.findall("edge") if edge.attrib.get("id")
    }
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

    dx = float(target_candidate_junction.attrib.get("x", "0") or 0) - float(teacher_junction.attrib.get("x", "0") or 0)
    dy = float(target_candidate_junction.attrib.get("y", "0") or 0) - float(teacher_junction.attrib.get("y", "0") or 0)
    translation_source = "junction_position"
    candidate_location = candidate_root.find("location")
    teacher_location = teacher_root.find("location")
    try:
        candidate_offset = [float(value) for value in candidate_location.attrib["netOffset"].split(",")[:2]]
        teacher_offset = [float(value) for value in teacher_location.attrib["netOffset"].split(",")[:2]]
        offset_dx = candidate_offset[0] - teacher_offset[0]
        offset_dy = candidate_offset[1] - teacher_offset[1]
        if math.hypot(dx - offset_dx, dy - offset_dy) > 100.0:
            dx, dy = offset_dx, offset_dy
            translation_source = "network_location_offset"
    except (AttributeError, KeyError, TypeError, ValueError, IndexError):
        pass

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
        edge for edge in teacher_root.findall("edge") if edge.attrib.get("id", "").startswith(teacher_internal_prefix)
    ]
    copied_boundary_edges = []
    copied_boundary_candidate_edges = []
    blended_geometry_anchor_edge_ids = []
    skipped_boundary_edges = []
    preserved_mapped_boundary_endpoints = []
    replaced_boundary_edge_ids: set[str] = set()
    boundary_insert_offset = 0
    teacher_edges = {edge.attrib["id"]: edge for edge in teacher_root.findall("edge") if edge.attrib.get("id")}
    invalid_edge_map_entries = [
        {"teacher_edge_id": teacher_edge_id, "candidate_edge_id": candidate_edge_id}
        for teacher_edge_id, candidate_edge_id in replay_edge_map.items()
        if teacher_edge_id not in teacher_edges or candidate_edge_id not in candidate_edges_by_id
    ]
    # The queue is allowed to carry stale candidate-side hints.  They are not
    # teacher authority and must not make an unmapped micro edge look mapped.
    replay_edge_map = {
        teacher_edge_id: candidate_edge_id
        for teacher_edge_id, candidate_edge_id in replay_edge_map.items()
        if teacher_edge_id in teacher_edges and candidate_edge_id in candidate_edges_by_id
    }
    teacher_junctions = {
        junction.attrib["id"]: junction for junction in teacher_root.findall("junction") if junction.attrib.get("id")
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
    teacher_boundary_mapped_counts = Counter(
        replay_edge_map.get(edge_id, edge_id) for edge_id in teacher_boundary_edge_ids
    )
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
            edge_id for edge_id in needed_boundary_edge_ids if edge_id not in replay_edge_map
        ]
        needed_boundary_edge_ids = [edge_id for edge_id in needed_boundary_edge_ids if edge_id in replay_edge_map]
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
    restored_teacher_split_boundary_edges = []
    for edge_id in needed_boundary_edge_ids:
        mapped_edge_id = replay_edge_map.get(edge_id, edge_id)
        teacher_boundary_edge = teacher_edges.get(edge_id)
        teacher_continuation_edge = teacher_edges.get(mapped_edge_id)
        candidate_unsplit_edge = candidate_edges_by_id.get(mapped_edge_id)
        if (
            mapped_edge_id == edge_id
            or teacher_boundary_edge is None
            or teacher_continuation_edge is None
            or candidate_unsplit_edge is None
            or _signed_edge_family_id(edge_id) != _signed_edge_family_id(mapped_edge_id)
            or teacher_junction_id
            not in (
                teacher_boundary_edge.attrib.get("from", ""),
                teacher_boundary_edge.attrib.get("to", ""),
            )
            or teacher_junction_id
            in (
                teacher_continuation_edge.attrib.get("from", ""),
                teacher_continuation_edge.attrib.get("to", ""),
            )
            or len(
                {
                    teacher_boundary_edge.attrib.get("from", ""),
                    teacher_boundary_edge.attrib.get("to", ""),
                }
                & {
                    teacher_continuation_edge.attrib.get("from", ""),
                    teacher_continuation_edge.attrib.get("to", ""),
                }
            )
            != 1
        ):
            continue
        replay_edge_map[edge_id] = edge_id
        restored_teacher_split_boundary_edges.append(edge_id)
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
        mapped_from = (
            junction_id
            if teacher_edge.attrib.get("from") == teacher_junction_id
            else teacher_edge.attrib.get("from", "")
        )
        mapped_to = (
            junction_id if teacher_edge.attrib.get("to") == teacher_junction_id else teacher_edge.attrib.get("to", "")
        )
        mapped_candidate_edge_id = replay_edge_map.get(edge_id, edge_id)
        mapped_candidate_edge = candidate_edges_by_id.get(mapped_candidate_edge_id)
        if (
            mapped_candidate_edge is not None
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
            stale_split_anchor_edge = geometry_anchor_edges_by_id.get(candidate_edge_id)
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
                    or (
                        continuation_edge_id in candidate_edges_by_id
                        and boundary_edge_id not in restored_teacher_split_boundary_edges
                    )
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
            replaced_continuation_edge = candidate_edges_by_id.get(edge_id)
            if replaced_continuation_edge is not None:
                _remove_edge_lanes_from_destination_junction(
                    candidate_root,
                    replaced_continuation_edge,
                    all_junctions=True,
                )
                candidate_root.remove(replaced_continuation_edge)
                candidate_edge_ids.discard(edge_id)
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
    if teacher_boundary_edge_ids and not preserve_unmapped_boundary_edges:
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
            if {
                connection.attrib.get("from", ""),
                connection.attrib.get("to", ""),
            } & removed_stale_boundary_edge_id_set:
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
    preserved_target_shape = _safe_junction_shape(original_target_junction_shape or "")
    if preserve_target_junction_shape and preserved_target_shape:
        mapped_target_attrs["shape"] = preserved_target_shape
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
            and (not shared_endpoint or stale_via or not _connection_lane_indices_valid(connection, edge_lane_counts))
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
        copied_tllogic = _clone_transformed_net_element(
            teacher_tllogic, dx, dy, replay_edge_map, teacher_junction_id, junction_id
        )
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

    restored_geometry_anchor_junctions = _restore_geometry_anchor_junctions(
        candidate_root, geometry_anchor_junctions_by_id
    )
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

    micro_boundary_prune_report = {
        "status": "skipped",
        "policy": "strict replay only: remove unmapped motorized boundary edges <= 5m when they only connect to other unmapped short edges",
        "removed_edge_ids": [],
        "removed_connection_count": 0,
    }
    if prune_unmapped_micro_boundary_edges:
        micro_boundary_prune_report = _prune_unmapped_micro_boundary_edges(
            candidate_root,
            junction_id=junction_id,
            mapped_candidate_edge_ids=set(replay_edge_map.values()),
        )
    strict_unmapped_boundary_prune_report = {
        "status": "skipped",
        "policy": "strict replay only: remove unmapped non-motorized outgoing boundary edges with movement evidence absent from the teacher",
        "removed_edge_ids": [],
        "removed_connection_count": 0,
    }
    if prune_strict_unmapped_outgoing_boundary_edges:
        strict_unmapped_boundary_prune_report = _prune_strict_unmapped_outgoing_boundary_edges(
            candidate_root,
            junction_id=junction_id,
            mapped_candidate_edge_ids=set(replay_edge_map.values()),
            teacher_edge_ids=set(teacher_edges),
        )

    unblended_geometry_anchor_edge_ids = geometry_anchor_edge_ids - set(blended_geometry_anchor_edge_ids)
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

    final_connection_keys = {_connection_key(connection) for connection in candidate_root.findall("connection")}
    removed_stale_replaced_edge_connections = [
        connection
        for connection in removed_stale_replaced_edge_connections
        if (
            str(connection.get("from", "")),
            str(connection.get("to", "")),
            str(connection.get("fromLane", "0")),
            str(connection.get("toLane", "0")),
        )
        not in final_connection_keys
    ]
    junction_shape_sanitization = _sanitize_junction_shapes(candidate_root)

    ET.indent(candidate_root, space="    ")
    candidate_tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "net_file": str(output_file),
        "dx": round(dx, 6),
        "dy": round(dy, 6),
        "translation_source": translation_source,
        "removed_internal_edge_count": len(removed_internal_edges),
        "copied_internal_edge_count": len(teacher_internal_edges),
        "copied_boundary_edge_count": len(copied_boundary_edges),
        "copied_boundary_edges": copied_boundary_edges,
        "copied_boundary_candidate_edges": copied_boundary_candidate_edges,
        "copy_unmapped_boundary_edges": copy_unmapped_boundary_edges,
        "preserve_mapped_boundary_endpoints": preserve_mapped_boundary_endpoints,
        "preserve_unmapped_boundary_edges": preserve_unmapped_boundary_edges,
        "prune_unmapped_micro_boundary_edges": prune_unmapped_micro_boundary_edges,
        "prune_strict_unmapped_outgoing_boundary_edges": prune_strict_unmapped_outgoing_boundary_edges,
        "invalid_edge_map_entry_count": len(invalid_edge_map_entries),
        "invalid_edge_map_entries": invalid_edge_map_entries,
        "micro_boundary_prune": micro_boundary_prune_report,
        "strict_unmapped_boundary_prune": strict_unmapped_boundary_prune_report,
        "preserve_target_junction_shape": preserve_target_junction_shape,
        "skipped_unmapped_teacher_boundary_edge_count": len(skipped_unmapped_teacher_boundary_edges),
        "skipped_unmapped_teacher_boundary_edges": skipped_unmapped_teacher_boundary_edges,
        "preserved_mapped_boundary_endpoint_count": len(preserved_mapped_boundary_endpoints),
        "preserved_mapped_boundary_endpoints": preserved_mapped_boundary_endpoints,
        "restored_external_boundary_connection_count": external_boundary_connection_report["restored_connection_count"],
        "restored_external_boundary_connections": external_boundary_connection_report["restored_connections"],
        "preserved_existing_external_boundary_connection_count": (
            external_boundary_connection_report["preserved_existing_connection_count"]
        ),
        "preserved_existing_external_boundary_connections": (
            external_boundary_connection_report["preserved_existing_connections"]
        ),
        "skipped_external_boundary_connection_count": external_boundary_connection_report["skipped_connection_count"],
        "skipped_external_boundary_connections": external_boundary_connection_report["skipped_connections"],
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
        "restored_teacher_split_boundary_edge_count": len(restored_teacher_split_boundary_edges),
        "restored_teacher_split_boundary_edges": restored_teacher_split_boundary_edges,
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
        "blended_geometry_anchor_edge_count": len(blended_geometry_anchor_edge_ids),
        "blended_geometry_anchor_edge_ids": sorted(set(blended_geometry_anchor_edge_ids)),
        "restored_geometry_anchor_junction_count": len(restored_geometry_anchor_junctions),
        "restored_geometry_anchor_junctions": restored_geometry_anchor_junctions,
        "target_shape_anchor": target_shape_anchor_report,
        "junction_shape_sanitization": junction_shape_sanitization,
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
        str(key): str(value) for key, value in (junction_map or {}).items() if str(key) and str(value)
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

    teacher_edges = {edge.attrib["id"]: edge for edge in teacher_root.findall("edge") if edge.attrib.get("id")}
    source_edges = {edge.attrib["id"]: edge for edge in source_root.findall("edge") if edge.attrib.get("id")}
    source_junction_ids = {
        junction.attrib["id"] for junction in source_root.findall("junction") if junction.attrib.get("id")
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
        return {lane.attrib["id"] for lane in edge.findall("lane") if lane.attrib.get("id")}

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
    candidate_edges = {edge.attrib["id"]: edge for edge in candidate_root.findall("edge") if edge.attrib.get("id")}
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
    candidate_edges = {edge.attrib["id"]: edge for edge in candidate_root.findall("edge") if edge.attrib.get("id")}
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
    remaining_edge_ids = {edge.attrib["id"] for edge in candidate_root.findall("edge") if edge.attrib.get("id")}
    for junction in candidate_root.findall("junction"):
        inc_lanes = [
            lane
            for lane in _split(junction.attrib.get("incLanes", ""))
            if lane.rsplit("_", 1)[0] in remaining_edge_ids and not lane.startswith(old_member_prefixes)
        ]
        junction.set("incLanes", " ".join(inc_lanes))
        int_lanes = [
            lane for lane in _split(junction.attrib.get("intLanes", "")) if not lane.startswith(old_member_prefixes)
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
        if (
            connection.attrib.get("from") not in remaining_edge_ids
            or connection.attrib.get("to") not in remaining_edge_ids
        ):
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
        "preserved_mapped_boundary_geometry_edge_ids": sorted(set(preserved_mapped_boundary_geometry_edge_ids)),
        "boundary_geometry_preservation_failure_count": len(boundary_geometry_preservation_failures),
        "boundary_geometry_preservation_failures": boundary_geometry_preservation_failures,
        "restored_external_boundary_connection_count": external_boundary_connection_report["restored_connection_count"],
        "restored_external_boundary_connections": external_boundary_connection_report["restored_connections"],
        "preserved_existing_external_boundary_connection_count": external_boundary_connection_report[
            "preserved_existing_connection_count"
        ],
        "preserved_existing_external_boundary_connections": external_boundary_connection_report[
            "preserved_existing_connections"
        ],
        "skipped_external_boundary_connection_count": external_boundary_connection_report["skipped_connection_count"],
        "skipped_external_boundary_connections": external_boundary_connection_report["skipped_connections"],
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

    clean_owner_map = {str(key): str(value) for key, value in (owner_map or {}).items() if str(key) and str(value)}
    clean_owner_map.setdefault(teacher_controller_id, candidate_controller_id)
    clean_junction_map = {
        str(key): str(value) for key, value in (junction_map or {}).items() if str(key) and str(value)
    }
    collapse_ids = {str(value) for value in (collapse_junction_ids or set()) if str(value)}
    collapse_ids.update(clean_owner_map.values())
    candidate_owner_ids = set(clean_owner_map.values())
    teacher_owner_ids = sorted(clean_owner_map, key=len, reverse=True)
    teacher_edges = {edge.attrib["id"]: edge for edge in teacher_root.findall("edge") if edge.attrib.get("id")}
    candidate_edges = {edge.attrib["id"]: edge for edge in candidate_root.findall("edge") if edge.attrib.get("id")}
    teacher_junctions = {
        junction.attrib["id"]: junction for junction in teacher_root.findall("junction") if junction.attrib.get("id")
    }
    candidate_junctions = {
        junction.attrib["id"]: junction for junction in candidate_root.findall("junction") if junction.attrib.get("id")
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
        return f":{clean_owner_map[owner_id]}_{value[len(prefix) :]}"

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
                float(candidate_anchor.attrib.get("x", "0") or 0) - float(teacher_anchor.attrib.get("x", "0") or 0),
                float(candidate_anchor.attrib.get("y", "0") or 0) - float(teacher_anchor.attrib.get("y", "0") or 0),
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
    teacher_link_indices = {str(connection.attrib.get("linkIndex", "")) for connection in controlled_connections}
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
                safe_id = (
                    "".join(
                        character if character.isalnum() or character in "_.-" else "_" for character in teacher_edge_id
                    ).strip("_")
                    or "edge"
                )
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

    candidate_edges = {edge.attrib["id"]: edge for edge in candidate_root.findall("edge") if edge.attrib.get("id")}
    candidate_junctions = {
        junction.attrib["id"]: junction for junction in candidate_root.findall("junction") if junction.attrib.get("id")
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
            suffix = (
                old_lane_id[len(teacher_edge_prefix) :]
                if old_lane_id.startswith(teacher_edge_prefix)
                else str(lane.attrib.get("index", lane_index))
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
    candidate_edge_ids = {edge.attrib["id"] for edge in candidate_root.findall("edge") if edge.attrib.get("id")}
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
            lane for lane in _split(junction.attrib.get("incLanes", "")) if lane.rsplit("_", 1)[0] in candidate_edge_ids
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
        if (
            connection.attrib.get("from") not in candidate_edge_ids
            or connection.attrib.get("to") not in candidate_edge_ids
        ):
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
    missing_link_indices = sorted(
        teacher_link_indices - actual_link_indices, key=lambda value: int(value) if value.isdigit() else value
    )
    unexpected_link_indices = sorted(
        actual_link_indices - teacher_link_indices, key=lambda value: int(value) if value.isdigit() else value
    )
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
        "preserved_mapped_boundary_geometry_edge_ids": sorted(set(preserved_mapped_boundary_geometry_edge_ids)),
        "boundary_geometry_preservation_failure_count": len(boundary_geometry_preservation_failures),
        "boundary_geometry_preservation_failures": boundary_geometry_preservation_failures,
        "restored_external_boundary_connection_count": external_boundary_connection_report["restored_connection_count"],
        "restored_external_boundary_connections": external_boundary_connection_report["restored_connections"],
        "preserved_existing_external_boundary_connection_count": external_boundary_connection_report[
            "preserved_existing_connection_count"
        ],
        "preserved_existing_external_boundary_connections": external_boundary_connection_report[
            "preserved_existing_connections"
        ],
        "skipped_external_boundary_connection_count": external_boundary_connection_report["skipped_connection_count"],
        "skipped_external_boundary_connections": external_boundary_connection_report["skipped_connections"],
        "removed_internal_edge_count": len(removed_internal_edge_ids),
        "removed_internal_junction_count": len(removed_internal_junction_ids),
        "removed_member_edge_count": len(removed_member_edge_ids),
        "removed_connection_count": removed_connection_count,
        "removed_mapped_edge_connection_count": removed_mapped_edge_connection_count,
        "copied_internal_edge_count": copied_internal_edge_count,
        "copied_internal_junction_count": copied_internal_junction_count,
        "removed_tllogic_ids": sorted(removed_tllogic_ids),
        "teacher_controlled_connection_count": len(controlled_connections),
        "teacher_link_indices": sorted(
            teacher_link_indices, key=lambda value: int(value) if value.isdigit() else value
        ),
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
    teacher_edges = {edge.attrib["id"]: edge for edge in teacher_root.findall("edge") if edge.attrib.get("id")}
    candidate_edges = {edge.attrib["id"]: edge for edge in candidate_root.findall("edge") if edge.attrib.get("id")}
    teacher_junction = teacher_root.find(f"junction[@id='{teacher_junction_id}']")
    candidate_junction = candidate_root.find(f"junction[@id='{candidate_junction_id}']")
    if teacher_junction is None or candidate_junction is None:
        return _failure("TLS cell replay plan target junction is missing")
    member_ids = {str(value) for value in (candidate_junction_ids or set()) if str(value)}
    member_ids.add(candidate_junction_id)
    teacher_boundary_edge_ids = _teacher_boundary_edge_ids_touching_internal_subgraph(
        teacher_root.findall("connection"),
        teacher_edges,
        teacher_junction_id,
    )
    pair_edge_map = {
        str(pair.get("reference_edge_id", "")): str(pair.get("candidate_edge_id", ""))
        for pair in (approach_pairs or [])
        if isinstance(pair, dict) and str(pair.get("reference_edge_id", "")) and str(pair.get("candidate_edge_id", ""))
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

    def endpoint_candidates(teacher_edge: ET.Element, direction: str) -> list[tuple[int, str, ET.Element]]:
        """Match a renamed boundary edge before falling back to its way family.

        TUM's cleaned net can retain the same boundary nodes while OSM splits
        the way into a different signed edge id.  Endpoint identity is the
        smallest safe evidence for that case; it avoids copying a teacher edge
        merely because its bearing or lane count looks similar.
        """

        def mapped_endpoint(endpoint: str) -> str:
            return candidate_junction_id if endpoint == teacher_junction_id else endpoint

        expected_from = mapped_endpoint(teacher_edge.attrib.get("from", ""))
        expected_to = mapped_endpoint(teacher_edge.attrib.get("to", ""))
        expected_lane_count = lane_count(teacher_edge)
        ranked: list[tuple[int, str, ET.Element]] = []
        for candidate_id, candidate_edge in candidate_edges.items():
            if candidate_id in used_candidate_boundary_ids:
                continue
            if candidate_id.startswith(":") or candidate_edge.attrib.get("function") in {
                "internal",
                "crossing",
                "walkingarea",
            }:
                continue
            if candidate_edge.attrib.get("from") != expected_from or candidate_edge.attrib.get("to") != expected_to:
                continue
            if not candidate_boundary_side_matches(candidate_edge, direction):
                continue
            ranked.append((abs(lane_count(candidate_edge) - expected_lane_count) * 100, candidate_id, candidate_edge))
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
                ranked = endpoint_candidates(teacher_edge, direction)
                if not ranked:
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
            teacher_edge.attrib.get("to", "") if direction == "outgoing" else teacher_edge.attrib.get("from", "")
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
        junction.attrib["id"]: junction for junction in teacher_root.findall("junction") if junction.attrib.get("id")
    }
    candidate_junctions_by_id = {
        junction.attrib["id"]: junction for junction in candidate_root.findall("junction") if junction.attrib.get("id")
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
            1 for value, count in Counter(effective_edge_map.values()).items() if count > 1
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

    candidate_edges = {edge.attrib["id"]: edge for edge in candidate_root.findall("edge") if edge.attrib.get("id")}
    teacher_edges = {edge.attrib["id"]: edge for edge in teacher_root.findall("edge") if edge.attrib.get("id")}
    candidate_junctions = {
        junction.attrib["id"]: junction for junction in candidate_root.findall("junction") if junction.attrib.get("id")
    }
    teacher_junctions = {
        junction.attrib["id"]: junction for junction in teacher_root.findall("junction") if junction.attrib.get("id")
    }
    base_candidate_ids = {str(item) for item in (candidate_junction_ids or set()) if str(item)}
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
            {str(key): str(value) for key, value in candidate_owner_map.items() if str(key) and str(value)}
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
            *{str(item) for item in (collapse_junction_ids or set()) if str(item)},
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
        if isinstance(pair, dict) and str(pair.get("reference_edge_id", "")) and str(pair.get("candidate_edge_id", ""))
    }
    requested_edge_map = {
        str(key): str(value) for key, value in (base_plan.get("edge_map", {}) or {}).items() if str(key) and str(value)
    }
    base_edge_map = dict(requested_edge_map)
    requested_edge_map.update(pair_map)
    resolved_edge_map: dict[str, str] = {}
    edge_mapping_sources: dict[str, str] = {}
    mapping_conflicts: list[dict[str, object]] = []
    mapping_rejections: list[dict[str, object]] = []
    used_candidate_edge_ids: set[str] = set()
    target_candidate_ids = {str(item) for item in (collapse_junction_ids or base_candidate_ids) if str(item)}
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
        safe = (
            "".join(
                character if character.isalnum() or character in "_.-" else "_" for character in teacher_edge_id
            ).strip("_")
            or "edge"
        )
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
            and requested_source in {"explicit_approach_pair", "base_plan_edge_map"}
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
                    score += (
                        0
                        if has_owner_side(candidate_edge, inferred_owner_map[teacher_edge.attrib["from"]], "from")
                        else 1000
                    )
                if teacher_to_owner:
                    score += (
                        0
                        if has_owner_side(candidate_edge, inferred_owner_map[teacher_edge.attrib["to"]], "to")
                        else 1000
                    )
                candidates.append((score, candidate_edge_id))
            if candidates:
                candidates.sort()
                best_score, best_id = candidates[0]
                owner_side_match = (
                    teacher_from_owner
                    and has_owner_side(
                        candidate_edges[best_id], inferred_owner_map[teacher_edge.attrib["from"]], "from"
                    )
                ) or (
                    teacher_to_owner
                    and has_owner_side(candidate_edges[best_id], inferred_owner_map[teacher_edge.attrib["to"]], "to")
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
    status = (
        "pass"
        if not missing_owner_ids and not mapping_conflicts and set(resolved_edge_map) == set(boundary_edge_ids)
        else "blocked"
    )
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
                if connection.attrib.get("tl") == teacher_controller_id
                and connection.attrib.get("linkIndex") is not None
            ]
        ),
        "mapping_conflicts": mapping_conflicts,
        "mapping_rejections": mapping_rejections,
        "base_plan": base_plan,
        "mapping_policy": "explicit_owner_closure_then_topology_checked_approach_pair_then_signed_family_owner_side_then_teacher_boundary_copy",
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
        idx
        for idx, child in enumerate(root_children)
        if child.tag == "tlLogic" or child.tag in {"junction", "connection"}
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
        "tl_phase_state_lengths": sorted(
            {len(phase.attrib.get("state", "")) for phase in replacement.findall("phase")}
        ),
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
        if not missing_source_link_indices and not extra_target_link_indices and tl_logic_status != "blocked"
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
    source_junction_id: str | None = None,
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
    source_junction_id = source_junction_id or junction_id
    source_internal_prefix = f":{source_junction_id}_"
    pedestrian_functions = {"crossing", "walkingarea"}
    source_pedestrian_edges = {
        edge.attrib.get("id", ""): edge
        for edge in source_root.findall("edge")
        if edge.attrib.get("id", "").startswith(source_internal_prefix)
        and edge.attrib.get("function") in pedestrian_functions
    }
    target_edges = {edge.attrib.get("id", ""): edge for edge in target_root.findall("edge") if edge.attrib.get("id")}
    mapped_source_edge_ids = {
        _mapped_internal_ref(edge_id, source_junction_id, junction_id) for edge_id in source_pedestrian_edges
    }
    replaced_edge_ids: list[str] = []
    added_edge_ids: list[str] = []

    def mapped_pedestrian_edge(source_edge: ET.Element) -> ET.Element:
        clone = copy.deepcopy(source_edge)
        source_edge_id = clone.attrib.get("id", "")
        clone.set("id", _mapped_internal_ref(source_edge_id, source_junction_id, junction_id))
        for lane in clone.findall("lane"):
            lane_id = lane.attrib.get("id", "")
            if lane_id:
                lane.set("id", _mapped_internal_ref(lane_id, source_junction_id, junction_id))
        if clone.attrib.get("crossingEdges"):
            clone.set(
                "crossingEdges",
                " ".join(
                    edge_map.get(
                        value,
                        _mapped_internal_ref(value, source_junction_id, junction_id),
                    )
                    for value in clone.attrib.get("crossingEdges", "").split()
                    if value
                ),
            )
        return clone

    for edge_id, source_edge in sorted(source_pedestrian_edges.items()):
        replacement = mapped_pedestrian_edge(source_edge)
        target_edge_id = replacement.attrib.get("id", "")
        existing = target_edges.get(target_edge_id)
        if existing is None:
            target_root.insert(_first_junction_index(target_root), replacement)
            target_edges[target_edge_id] = replacement
            added_edge_ids.append(target_edge_id)
            continue
        index = list(target_root).index(existing)
        target_root.remove(existing)
        target_root.insert(index, replacement)
        target_edges[target_edge_id] = replacement
        replaced_edge_ids.append(target_edge_id)

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
            if value.startswith(source_internal_prefix):
                attrs[attr] = _mapped_internal_ref(value, source_junction_id, junction_id)
            elif value:
                attrs[attr] = edge_map.get(value, value)
        via = attrs.get("via", "")
        if via.startswith(source_internal_prefix):
            attrs["via"] = _mapped_internal_ref(via, source_junction_id, junction_id)
        if attrs.get("tl") == source_junction_id:
            attrs["tl"] = junction_id
        return ET.Element("connection", attrs)

    def connection_key(connection: ET.Element) -> tuple[str, ...]:
        return tuple(
            connection.attrib.get(attr, "") for attr in ("from", "to", "fromLane", "toLane", "via", "tl", "linkIndex")
        )

    removed_target_pedestrian_connections = []
    for connection in list(target_root.findall("connection")):
        if connection.attrib.get("from", "") in mapped_source_edge_ids or connection.attrib.get(
            "to", ""
        ) in mapped_source_edge_ids:
            removed_target_pedestrian_connections.append(dict(connection.attrib))
            target_root.remove(connection)
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

    target_junction = target_root.find(f"junction[@id='{junction_id}']")
    if target_junction is not None:
        mapped_pedestrian_lane_ids = [
            lane.attrib["id"]
            for edge_id, edge in target_edges.items()
            if edge_id in mapped_source_edge_ids
            for lane in edge.findall("lane")
            if lane.attrib.get("id")
        ]
        for attr in ("incLanes", "intLanes"):
            existing_lanes = _split(target_junction.attrib.get(attr, ""))
            target_junction.set(
                attr,
                " ".join(dict.fromkeys([*existing_lanes, *mapped_pedestrian_lane_ids])),
            )

    missing_edge_ids = sorted(mapped_source_edge_ids - set(target_edges))
    missing_connection_keys = sorted(
        set(connection_key(mapped_connection(connection)) for connection in source_pedestrian_connections)
        - set(target_connections)
    )
    missing_crossing_edge_refs = []
    target_edge_ids = set(target_edges)
    for edge in target_edges.values():
        if edge.attrib.get("id") not in mapped_source_edge_ids or not edge.attrib.get("crossingEdges"):
            continue
        for referenced_edge_id in edge.attrib.get("crossingEdges", "").split():
            if referenced_edge_id not in target_edge_ids:
                missing_crossing_edge_refs.append(
                    {"crossing_edge_id": edge.attrib.get("id", ""), "referenced_edge_id": referenced_edge_id}
                )
    status = (
        "pass" if not missing_edge_ids and not missing_connection_keys and not missing_crossing_edge_refs else "blocked"
    )
    if source_pedestrian_edges or source_pedestrian_connections:
        ET.indent(target_root, space="    ")
        target_tree.write(target_net_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": status,
        "claim_status": "diagnostic-demo",
        "source_net_file": str(source_net_file),
        "target_net_file": str(target_net_file),
        "junction_id": junction_id,
        "source_junction_id": source_junction_id,
        "source_pedestrian_edge_count": len(source_pedestrian_edges),
        "source_pedestrian_connection_count": len(source_pedestrian_connections),
        "replaced_pedestrian_edge_count": len(replaced_edge_ids),
        "replaced_pedestrian_edge_ids": replaced_edge_ids,
        "added_pedestrian_edge_count": len(added_edge_ids),
        "added_pedestrian_edge_ids": added_edge_ids,
        "added_pedestrian_connection_count": added_connection_count,
        "updated_pedestrian_connection_count": updated_connection_count,
        "removed_target_pedestrian_connection_count": len(removed_target_pedestrian_connections),
        "removed_target_pedestrian_connections": removed_target_pedestrian_connections,
        "missing_pedestrian_edge_ids": missing_edge_ids,
        "missing_pedestrian_connection_keys": missing_connection_keys,
        "missing_crossing_edge_refs": missing_crossing_edge_refs,
        "policy": "scoped teacher crossing/walkingarea overlay; no outside-cell pedestrian copy",
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
    preserve_target_junction_shape: bool = False,
    structural_osm_boundary_authority: bool = False,
    safety_junction_ids: Sequence[str] = (),
    teacher_absent_tls_junction_ids: Sequence[str] = (),
    emit_teacher_crossings: bool = True,
    prune_unmapped_boundary_edges: bool = False,
    strict_teacher_replay: bool = False,
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
        "declared_estimator_evidence" if source_conflict_core_node_ids is not None else "plain_join_definition"
    )
    compound_junction_ids = sorted({junction_id, *(str(value) for value in safety_junction_ids if str(value))})
    movement_replay_junction_ids = [junction_id] if strict_teacher_replay else compound_junction_ids
    control_cleanup_junction_ids = sorted(
        {
            *compound_junction_ids,
            *(str(value) for value in teacher_absent_tls_junction_ids if str(value)),
        }
    )
    strict_structural_replay = strict_teacher_replay and bool(compound_junction_ids)
    strict_structural_edge_map_additions: list[str] = []
    strict_structural_boundary_ids: set[str] = set()
    if strict_structural_replay:
        edge_map, strict_structural_boundary_ids, strict_structural_edge_map_additions = (
            _strict_teacher_structural_context(
                teacher_net_file=teacher_net_file,
                candidate_net_file=candidate_net_file,
                edge_map=edge_map,
                safety_junction_ids=movement_replay_junction_ids,
            )
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
        boundary_node_ids=joined_source_node_ids | strict_structural_boundary_ids,
        rebase_teacher_target_to_join_source=not strict_structural_replay,
        prune_unmapped_boundary_edges=prune_unmapped_boundary_edges,
        approach_endpoint_rebuild_plan=approach_endpoint_rebuild_plan,
        lane_shape_delta=lane_shape_delta,
        preserve_lane_shapes=preserve_teacher_lane_shapes,
        preserve_osm_lane_profiles=structural_osm_boundary_authority,
    )
    lane_cardinality_neighbor_junction_ids = {
        str(value)
        for value in lane_patch_report.get("lane_cardinality_changed_endpoint_junction_ids", []) or []
        if str(value)
    }
    lane_cardinality_geometry_anchor_junction_ids = lane_cardinality_neighbor_junction_ids - {junction_id}
    compound_junction_ids = sorted({*compound_junction_ids, *lane_cardinality_neighbor_junction_ids})
    internal_restore_exclude_junction_ids = {
        *compound_junction_ids,
        *(str(value) for value in teacher_absent_tls_junction_ids if str(value)),
        *_endpoint_rewrite_old_endpoint_ids(lane_patch_report),
    }
    restore_mutable_edge_ids = set() if structural_osm_boundary_authority else set(edge_map.values())
    expand_restore_scope = not (structural_osm_boundary_authority or strict_teacher_replay)
    node_patch_report = write_teacher_endpoint_patch_nodes(
        raw_node_file=raw_node_file,
        teacher_net_file=teacher_net_file,
        candidate_net_file=candidate_net_file,
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
    connection_teacher_model = teacher_model
    connection_edge_map = edge_map
    structural_teacher_junction_ids = [teacher_junction_id]
    if (structural_osm_boundary_authority or strict_structural_replay) and movement_replay_junction_ids:
        connection_teacher_model = copy.deepcopy(teacher_model)
        connection_edge_map = dict(edge_map)
        teacher_junction_ids = {
            row.attrib["id"] for row in ET.parse(teacher_net_file).getroot().findall("junction") if row.attrib.get("id")
        }
        candidate_edge_ids = set(_edge_file_lane_counts(patched_edge_file))
        for compound_junction_id in movement_replay_junction_ids:
            if compound_junction_id == teacher_junction_id or compound_junction_id not in teacher_junction_ids:
                continue
            partition_model = extract_teacher_junction_model(
                teacher_net_file,
                compound_junction_id,
            )
            structural_teacher_junction_ids.append(compound_junction_id)
            connection_teacher_model.setdefault("vehicle_connections", []).extend(
                partition_model.get("vehicle_connections", []) or []
            )
            connection_approaches = connection_teacher_model.setdefault(
                "approaches",
                {"incoming": [], "outgoing": []},
            )
            partition_approaches = partition_model.get("approaches", {})
            if not isinstance(connection_approaches, dict) or not isinstance(partition_approaches, dict):
                continue
            for direction in ("incoming", "outgoing"):
                rows = partition_approaches.get(direction, []) or []
                connection_approaches.setdefault(direction, []).extend(rows)
                for row in rows:
                    if isinstance(row, dict) and str(row.get("edge_id", "")) in candidate_edge_ids:
                        edge_id = str(row["edge_id"])
                        connection_edge_map.setdefault(edge_id, edge_id)
    connection_report = write_teacher_connection_plan(
        raw_connection_file=raw_connection_file,
        output_file=connection_file,
        junction_id=junction_id,
        teacher_model=connection_teacher_model,
        candidate_model=candidate_model,
        edge_map=connection_edge_map,
        crossing_edge_overrides=crossing_edge_overrides,
        candidate_edge_file=patched_edge_file,
        crossing_node_ids=joined_source_node_ids,
        emit_crossings=emit_teacher_crossings and not replay_target_internal_subgraph,
        teacher_internal_scope_id=(
            teacher_junction_id if replay_target_internal_subgraph and not strict_structural_replay else None
        ),
        generate_structural_connections=structural_osm_boundary_authority or strict_structural_replay,
        structural_junction_ids=movement_replay_junction_ids,
    )
    connection_report["structural_teacher_junction_ids"] = sorted(structural_teacher_junction_ids)
    if connection_report.get("status") != "pass":
        return _write_teacher_guided_report(
            report_file,
            {
                "status": "fail",
                "claim_status": "construction-invalid",
                "junction_id": junction_id,
                "teacher_net_file": str(teacher_net_file),
                "candidate_net_file": str(candidate_net_file),
                "reason": "missing independent movement evidence for disconnected lanes",
                "connection_plan": connection_report,
            },
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
        "--offset.disable-normalization",
        "true",
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
    seed_turnaround_scope = [
        identifier for identifier in control_cleanup_junction_ids if identifier in _net_junction_ids(sidewalks_net_file)
    ]
    seed_turnaround_authority = _compound_teacher_turnaround_evidence(
        teacher_model=teacher_model,
        final_net_file=sidewalks_net_file,
        junction_id=junction_id,
        edge_map=edge_map,
        teacher_net_file=teacher_net_file,
        teacher_junction_id=teacher_junction_id,
        compound_junction_ids=seed_turnaround_scope,
        teacher_absent_junction_ids=teacher_absent_tls_junction_ids,
    )
    seed_turnaround_audit = audit_external_micro_junctions(
        sidewalks_net_file,
        junction_ids=seed_turnaround_scope,
        turnaround_authority=seed_turnaround_authority["authority_records"],
    )
    control_node_overlay = _write_teacher_absent_tls_node_overlay(
        output_dir / f"{prefix}_teacher_absent_tls.nod.xml",
        candidate_net_file=sidewalks_net_file,
        teacher_net_file=teacher_net_file,
        teacher_partition_map=seed_turnaround_authority["teacher_partition_map"],
        teacher_absent_junction_ids=teacher_absent_tls_junction_ids,
    )
    turnaround_prune_overlay = _write_unsupported_turnaround_delete_overlay(
        output_dir / f"{prefix}_unsupported_turnarounds.con.xml",
        seed_turnaround_audit,
        negative_teacher_evidence=seed_turnaround_authority["negative_movement_evidence"],
    )
    turnaround_prune_overlay["control_node_overlay"] = control_node_overlay
    if turnaround_prune_overlay["deleted_connection_count"] or control_node_overlay["demoted_tls_junction_count"]:
        turnaround_pruned_net_file = _stage_file(
            output_dir,
            prefix,
            "turnaround_pruned.net.xml",
        )
        prune_command = [
            netconvert_binary,
            "--sumo-net-file",
            _command_path(sidewalks_net_file, output_dir),
        ]
        if turnaround_prune_overlay["deleted_connection_count"]:
            prune_command.extend(
                [
                    "--connection-files",
                    _command_path(
                        Path(str(turnaround_prune_overlay["overlay_file"])),
                        output_dir,
                    ),
                ]
            )
        if control_node_overlay["demoted_tls_junction_count"]:
            demoted_tls_junction_ids = sorted(
                str(row["candidate_junction_id"]) for row in control_node_overlay["demoted_tls_junctions"]
            )
            prune_command.extend(
                [
                    "--node-files",
                    _command_path(
                        Path(str(control_node_overlay["overlay_file"])),
                        output_dir,
                    ),
                    "--tls.unset",
                    ",".join(demoted_tls_junction_ids),
                ]
            )
        prune_command.extend(
            [
                "--output-file",
                _command_path(turnaround_pruned_net_file, output_dir),
                "--offset.disable-normalization",
                "true",
            ]
        )
        prune_netconvert_report = _command_report(
            command_runner(
                prune_command,
                cwd=output_dir,
                timeout_seconds=timeout_seconds,
            )
        )
        turnaround_prune_overlay["netconvert"] = prune_netconvert_report
        if prune_netconvert_report.get("status") != "pass":
            return _write_teacher_guided_report(
                report_file,
                {
                    "status": "fail",
                    "claim_status": "construction-invalid",
                    "junction_id": junction_id,
                    "teacher_net_file": str(teacher_net_file),
                    "candidate_net_file": str(candidate_net_file),
                    "netconvert": netconvert_report,
                    "turnaround_prune": turnaround_prune_overlay,
                    "node_patch": node_patch_report,
                    "lane_patch": lane_patch_report,
                    "type_patch": type_patch_report,
                    "connection_plan": connection_report,
                },
            )
        sidewalks_net_file = turnaround_pruned_net_file

    non_target_internal_restore_report = restore_off_scope_netconvert_artifacts(
        source_file=candidate_net_file,
        target_file=sidewalks_net_file,
        mutable_junction_ids=internal_restore_exclude_junction_ids,
        mutable_edge_ids=restore_mutable_edge_ids,
        expand_mutable_edge_endpoints=expand_restore_scope,
        geometry_anchor_junction_ids=lane_cardinality_geometry_anchor_junction_ids,
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
    target_internal_pedestrian_ring_report = None
    structural_pedestrian_normalize_report = None
    if structural_osm_boundary_authority and not replay_target_internal_subgraph:
        target_internal_pedestrian_ring_report = restore_scoped_pedestrian_internal_semantics_after_normalize(
            source_net_file=teacher_net_file,
            target_net_file=pedring_net_file,
            junction_id=junction_id,
            source_junction_id=teacher_junction_id,
            edge_map=edge_map,
        )
        structural_pedestrian_normalize_report = _command_report(
            command_runner(
                [
                    netconvert_binary,
                    "--sumo-net-file",
                    _command_path(pedring_net_file, output_dir),
                    "--output-file",
                    _command_path(target_internal_pedring_net_file, output_dir),
                    "--offset.disable-normalization",
                    "true",
                ],
                cwd=output_dir,
                timeout_seconds=timeout_seconds,
            )
        )
        if structural_pedestrian_normalize_report.get("status") != "pass":
            return _write_teacher_guided_report(
                report_file,
                {
                    "status": "fail",
                    "claim_status": "construction-invalid",
                    "junction_id": junction_id,
                    "teacher_net_file": str(teacher_net_file),
                    "candidate_net_file": str(candidate_net_file),
                    "pedestrian_ring": pedestrian_ring_report,
                    "target_internal_pedestrian_ring": target_internal_pedestrian_ring_report,
                    "structural_pedestrian_normalize": structural_pedestrian_normalize_report,
                },
            )
        target_internal_pedestrian_ring_report = restore_scoped_pedestrian_internal_semantics_after_normalize(
            source_net_file=teacher_net_file,
            target_net_file=target_internal_pedring_net_file,
            junction_id=junction_id,
            source_junction_id=teacher_junction_id,
            edge_map=edge_map,
        )
        pedring_net_file = target_internal_pedring_net_file
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
                candidate_net_file
                if (
                    len(joined_source_node_ids) > 1
                    and not preserve_target_junction_shape
                    and not strict_teacher_replay
                )
                else None
            ),
            blend_geometry_anchor_at_target=(
                len(joined_source_node_ids) > 1
                and not preserve_target_junction_shape
                and not strict_teacher_replay
            ),
            # Strict TUM replay retains teacher-only modal boundary edges when
            # their transformed endpoints exist; default hybrid replay keeps
            # the candidate boundary and reports unmapped edges instead.
            copy_unmapped_boundary_edges=strict_teacher_replay,
            preserve_mapped_boundary_endpoints=True,
            preserve_unmapped_boundary_edges=strict_teacher_replay,
            prune_unmapped_micro_boundary_edges=strict_teacher_replay,
            prune_strict_unmapped_outgoing_boundary_edges=strict_teacher_replay,
            preserve_target_junction_shape=preserve_target_junction_shape,
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

    teacher_absent_geometry_contraction_report = None
    if teacher_absent_tls_junction_ids:
        contraction_scope_not_needed = False
        expected_contraction_ids = {str(value) for value in teacher_absent_tls_junction_ids if str(value)}
        contraction_source_file = final_net_file
        contraction_source_root = ET.parse(contraction_source_file).getroot()
        contraction_mutable_edge_ids = {
            edge.attrib["id"]
            for edge in contraction_source_root.findall("edge")
            if edge.attrib.get("id")
            and not edge.attrib["id"].startswith(":")
            and {
                edge.attrib.get("from", ""),
                edge.attrib.get("to", ""),
            }
            & expected_contraction_ids
        }
        contraction_mutable_junction_ids = {
            endpoint
            for edge in contraction_source_root.findall("edge")
            if edge.attrib.get("id") in contraction_mutable_edge_ids
            for endpoint in (
                edge.attrib.get("from", ""),
                edge.attrib.get("to", ""),
            )
            if endpoint
        }
        contraction_neighbor_junction_ids = contraction_mutable_junction_ids - expected_contraction_ids
        teacher_absent_geometry_contraction_report = build_corridor_geometry_simplification_variant(
            net_file=final_net_file,
            output_dir=output_dir / "geometry",
            prefix="absent",
            reference_net_file=teacher_net_file,
            candidate_node_ids=expected_contraction_ids,
            netconvert_binary=netconvert_binary,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
        contraction_variant_file = Path(str(teacher_absent_geometry_contraction_report.get("variant_file", "")))
        contraction_scope_valid = (
            int(teacher_absent_geometry_contraction_report.get("candidate_node_count", 0) or 0)
            == len(expected_contraction_ids)
            and set(teacher_absent_geometry_contraction_report.get("removed_node_ids", []) or [])
            == expected_contraction_ids
            and not teacher_absent_geometry_contraction_report.get("unexpected_removed_node_ids", [])
            and contraction_variant_file.is_file()
        )
        contraction_has_motorized_edge = any(
            _sumo_allowed_classes({**edge.attrib, **lane.attrib}) & ROAD_MOTORIZED_CLASSES
            for edge in contraction_source_root.findall("edge")
            if edge.attrib.get("id") in contraction_mutable_edge_ids
            for lane in edge.findall("lane")
        )
        if (
            not contraction_scope_valid
            and not contraction_has_motorized_edge
            and int(teacher_absent_geometry_contraction_report.get("candidate_node_count", 0) or 0) == 0
            and not teacher_absent_geometry_contraction_report.get("unexpected_removed_node_ids", [])
        ):
            teacher_absent_geometry_contraction_report["scope_not_needed"] = True
            teacher_absent_geometry_contraction_report["scope_not_needed_reason"] = (
                "expected fringe junctions were already absent after replay or have no motorized boundary edge"
            )
            contraction_scope_valid = True
            contraction_scope_not_needed = True
        if contraction_scope_valid and not contraction_scope_not_needed:
            scoped_restore = restore_off_scope_netconvert_artifacts(
                source_file=contraction_source_file,
                target_file=contraction_variant_file,
                mutable_junction_ids=contraction_mutable_junction_ids,
                mutable_edge_ids=contraction_mutable_edge_ids,
                expand_mutable_edge_endpoints=False,
            )
            neighbor_internal_restore = _restore_non_target_internal_artifacts(
                source_file=contraction_source_file,
                target_file=contraction_variant_file,
                exclude_junction_ids=expected_contraction_ids,
            )
            contraction_edge_aliases = {
                str(source): str(target)
                for source, target in (teacher_absent_geometry_contraction_report.get("edge_aliases", {}) or {}).items()
            }
            modal_restore = _restore_contraction_neighbor_modal_edges(
                source_file=contraction_source_file,
                target_file=contraction_variant_file,
                junction_ids=contraction_neighbor_junction_ids,
                edge_aliases=contraction_edge_aliases,
            )
            alias_connection_restore = _restore_contraction_edge_alias_connections(
                source_file=contraction_source_file,
                target_file=contraction_variant_file,
                edge_aliases=contraction_edge_aliases,
                source_modal_edge_ids=set(modal_restore.get("source_edge_ids", [])),
                source_boundary_edge_ids={
                    edge.attrib["id"]
                    for edge in contraction_source_root.findall("edge")
                    if edge.attrib.get("id")
                    and edge.attrib.get("function") not in {"internal", "crossing", "walkingarea"}
                    and any(
                        endpoint in {*contraction_mutable_junction_ids, junction_id}
                        for endpoint in (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
                    )
                },
            )
            post_restore_alias_audit = audit_alias_normalized_connections(
                contraction_source_file,
                contraction_variant_file,
                ignored_source_via_junction_ids=expected_contraction_ids,
            )
            pre_restore_modal_deltas = _contraction_modal_preservation_deltas(
                teacher_absent_geometry_contraction_report
            )
            post_restore_neighbor_request_restore = _restore_contraction_neighbor_requests(
                source_file=contraction_source_file,
                target_file=contraction_variant_file,
                junction_ids=contraction_neighbor_junction_ids,
                edge_aliases=contraction_edge_aliases,
            )
            post_restore_neighbor_semantic_audit = _audit_contraction_neighbor_semantics(
                source_file=contraction_source_file,
                target_file=contraction_variant_file,
                junction_ids=contraction_neighbor_junction_ids,
                edge_aliases=contraction_edge_aliases,
            )
            post_restore_modal_preservation = _audit_contraction_modal_preservation(
                contraction_source_file,
                contraction_variant_file,
            )
            teacher_absent_geometry_contraction_report["off_scope_restore"] = scoped_restore
            teacher_absent_geometry_contraction_report["post_restore_alias_normalized_connection_audit"] = (
                post_restore_alias_audit
            )
            teacher_absent_geometry_contraction_report["post_restore_neighbor_modal_restore"] = modal_restore
            teacher_absent_geometry_contraction_report["post_restore_neighbor_internal_restore"] = (
                neighbor_internal_restore
            )
            teacher_absent_geometry_contraction_report["post_restore_edge_alias_connection_restore"] = (
                alias_connection_restore
            )
            teacher_absent_geometry_contraction_report["post_restore_neighbor_request_restore"] = (
                post_restore_neighbor_request_restore
            )
            teacher_absent_geometry_contraction_report["post_restore_neighbor_semantic_audit"] = (
                post_restore_neighbor_semantic_audit
            )
            teacher_absent_geometry_contraction_report["pre_restore_modal_preservation_deltas"] = (
                pre_restore_modal_deltas
            )
            teacher_absent_geometry_contraction_report["post_restore_modal_preservation"] = (
                post_restore_modal_preservation
            )
            if (
                scoped_restore.get("status") == "pass"
                and neighbor_internal_restore.get("status") == "pass"
                and post_restore_alias_audit.get("status") == "pass"
                and post_restore_neighbor_request_restore.get("status") == "pass"
                and post_restore_neighbor_semantic_audit.get("status") == "pass"
                and post_restore_modal_preservation.get("status") == "pass"
                and not post_restore_alias_audit.get("normal_missing_count", 0)
                and not post_restore_alias_audit.get("normal_extra_count", 0)
            ):
                teacher_absent_geometry_contraction_report["pre_restore_status"] = (
                    teacher_absent_geometry_contraction_report.get("status")
                )
                teacher_absent_geometry_contraction_report["pre_restore_claim_status"] = (
                    teacher_absent_geometry_contraction_report.get("claim_status")
                )
                teacher_absent_geometry_contraction_report["status"] = "pass"
                teacher_absent_geometry_contraction_report["claim_status"] = "diagnostic-demo"
                teacher_absent_geometry_contraction_report["corridor_geometry_simplification_status"] = (
                    "pass_after_off_scope_restore"
                )
                teacher_absent_geometry_contraction_report["semantic_preservation_status"] = (
                    "pass_after_off_scope_restore"
                )
        if teacher_absent_geometry_contraction_report.get("status") != "pass" or not contraction_scope_valid:
            return _write_teacher_guided_report(
                report_file,
                {
                    "status": "fail",
                    "claim_status": "construction-invalid",
                    "junction_id": junction_id,
                    "teacher_net_file": str(teacher_net_file),
                    "candidate_net_file": str(candidate_net_file),
                    "final_net_file": str(final_net_file),
                    "teacher_absent_geometry_contraction": (teacher_absent_geometry_contraction_report),
                },
            )
        if not contraction_scope_not_needed:
            final_net_file = contraction_variant_file

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
            target_internal_normalize_report["unrestored_net_file"] = str(
                target_internal_normalized_unrestored_net_file
            )
            target_internal_normalize_report["non_target_internal_restore"] = restore_off_scope_netconvert_artifacts(
                source_file=target_internal_replay_file,
                target_file=target_internal_normalized_net_file,
                mutable_junction_ids=internal_restore_exclude_junction_ids,
                mutable_edge_ids=restore_mutable_edge_ids,
                expand_mutable_edge_endpoints=expand_restore_scope,
                geometry_anchor_junction_ids=lane_cardinality_geometry_anchor_junction_ids,
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
                mutable_edge_ids=restore_mutable_edge_ids,
                expand_mutable_edge_endpoints=expand_restore_scope,
                geometry_anchor_junction_ids=lane_cardinality_geometry_anchor_junction_ids,
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
    final_junction_ids = _net_junction_ids(final_net_file)
    missing_compound_junction_ids = sorted(set(compound_junction_ids) - final_junction_ids)
    contraction_edge_aliases = {}
    if isinstance(teacher_absent_geometry_contraction_report, dict):
        alias_audit = teacher_absent_geometry_contraction_report.get(
            "post_restore_alias_normalized_connection_audit", {}
        )
        if isinstance(alias_audit, dict):
            contraction_edge_aliases = dict(alias_audit.get("edge_aliases", {}) or {})
    boundary_edge_preservation_by_junction = {}
    boundary_vehicle_connectivity_by_junction = {}
    micro_boundary_excluded_edge_ids = set()
    strict_unmapped_boundary_excluded_edge_ids = set()
    if isinstance(target_internal_replay_report, dict):
        micro_report = target_internal_replay_report.get("micro_boundary_prune", {})
        if isinstance(micro_report, dict):
            micro_boundary_excluded_edge_ids = {
                str(edge_id) for edge_id in micro_report.get("removed_edge_ids", []) if str(edge_id)
            }
        strict_report = target_internal_replay_report.get("strict_unmapped_boundary_prune", {})
        if isinstance(strict_report, dict):
            strict_unmapped_boundary_excluded_edge_ids = {
                str(edge_id) for edge_id in strict_report.get("removed_edge_ids", []) if str(edge_id)
            }
    for compound_junction_id in compound_junction_ids:
        if compound_junction_id not in final_junction_ids:
            continue
        source_boundary_edge_ids = _external_boundary_edge_ids(candidate_net_file, compound_junction_id)
        final_boundary_edge_ids = _external_boundary_edge_ids(final_net_file, compound_junction_id)
        raw_missing_boundary_edge_ids = source_boundary_edge_ids - final_boundary_edge_ids
        internalized_boundary_edge_aliases = {
            edge_id: contraction_edge_aliases[edge_id]
            for edge_id in raw_missing_boundary_edge_ids
            if contraction_edge_aliases.get(edge_id) in final_boundary_edge_ids
        }
        replaced_boundary_edge_aliases = _boundary_edge_replacement_aliases(
            candidate_net_file,
            final_net_file,
            source_boundary_edge_ids=source_boundary_edge_ids,
            final_boundary_edge_ids=final_boundary_edge_ids,
            missing_boundary_edge_ids=raw_missing_boundary_edge_ids - set(internalized_boundary_edge_aliases),
        )
        micro_boundary_exclusions = {
            edge_id: "unmapped_motorized_boundary_micro_edge"
            for edge_id in sorted(raw_missing_boundary_edge_ids & micro_boundary_excluded_edge_ids)
        }
        strict_unmapped_boundary_exclusions = {
            edge_id: "unmapped_non_motorized_outgoing_boundary_edge"
            for edge_id in sorted(raw_missing_boundary_edge_ids & strict_unmapped_boundary_excluded_edge_ids)
        }
        missing_boundary_edge_ids = sorted(
            raw_missing_boundary_edge_ids
            - set(internalized_boundary_edge_aliases)
            - set(replaced_boundary_edge_aliases)
            - set(micro_boundary_exclusions)
            - set(strict_unmapped_boundary_exclusions)
        )
        boundary_edge_preservation_by_junction[compound_junction_id] = {
            "status": "pass" if not missing_boundary_edge_ids else "fail",
            "source_boundary_edge_count": len(source_boundary_edge_ids),
            "final_boundary_edge_count": len(final_boundary_edge_ids),
            "raw_missing_boundary_edge_ids": sorted(raw_missing_boundary_edge_ids),
            "missing_boundary_edge_ids": missing_boundary_edge_ids,
            "internalized_boundary_edge_aliases": dict(sorted(internalized_boundary_edge_aliases.items())),
            "replaced_boundary_edge_aliases": dict(sorted(replaced_boundary_edge_aliases.items())),
            "excluded_with_reason": {
                **micro_boundary_exclusions,
                **strict_unmapped_boundary_exclusions,
            },
            "added_boundary_edge_ids": sorted(final_boundary_edge_ids - source_boundary_edge_ids),
        }
        boundary_vehicle_connectivity_by_junction[compound_junction_id] = _boundary_vehicle_connectivity(
            final_net_file, compound_junction_id
        )
    boundary_edge_preservation = {
        "status": (
            "pass"
            if not missing_compound_junction_ids
            and all(row.get("status") == "pass" for row in boundary_edge_preservation_by_junction.values())
            else "fail"
        ),
        "junction_ids": compound_junction_ids,
        "missing_junction_ids": missing_compound_junction_ids,
        "junction_reports": boundary_edge_preservation_by_junction,
    }
    boundary_vehicle_connectivity = {
        "status": (
            "pass"
            if not missing_compound_junction_ids
            and all(row.get("status") == "pass" for row in boundary_vehicle_connectivity_by_junction.values())
            else "fail"
        ),
        "junction_ids": compound_junction_ids,
        "missing_junction_ids": missing_compound_junction_ids,
        "junction_reports": boundary_vehicle_connectivity_by_junction,
    }
    short_internal_lane_gate = _short_internal_lane_gate(final_net_file, compound_junction_ids)
    surface_overlap_report_file = output_dir / f"{prefix}_target_surface_overlap.json"
    surface_overlap_report = audit_sumo_lane_junction_surface_overlaps(
        final_net_file,
        report_file=surface_overlap_report_file,
    )
    target_related_surface_overlaps = [
        item
        for item in surface_overlap_report.get("external_lane_non_owner_junction_overlaps", []) or []
        if isinstance(item, dict)
        and _lane_surface_overlap_touches_junctions(item, set(compound_junction_ids))
    ]
    baseline_surface_overlap_report_file = output_dir / f"{prefix}_baseline_surface_overlap.json"
    baseline_surface_overlap_report = (
        audit_sumo_lane_junction_surface_overlaps(
            candidate_net_file,
            report_file=baseline_surface_overlap_report_file,
        )
        if target_related_surface_overlaps
        else None
    )
    target_junction_surface_overlaps = [
        item
        for item in surface_overlap_report.get("junction_junction_overlaps", []) or []
        if isinstance(item, dict)
        and set(compound_junction_ids)
        & {
            item.get("first_junction_id", ""),
            item.get("second_junction_id", ""),
        }
    ]
    reference_surface_overlap_report_file = output_dir / f"{prefix}_reference_surface_overlap.json"
    reference_surface_overlap_report = (
        audit_sumo_lane_junction_surface_overlaps(
            teacher_net_file,
            report_file=reference_surface_overlap_report_file,
        )
        if target_junction_surface_overlaps
        else None
    )
    target_surface_overlap_gates = {
        compound_junction_id: _target_surface_overlap_gate(
            surface_overlap_report,
            compound_junction_id,
            report_file=surface_overlap_report_file,
            expected_net_file=final_net_file,
            baseline_report=baseline_surface_overlap_report,
            baseline_report_file=baseline_surface_overlap_report_file,
            baseline_expected_net_file=candidate_net_file,
            reference_report=reference_surface_overlap_report,
            reference_report_file=reference_surface_overlap_report_file,
            reference_expected_net_file=teacher_net_file,
            lane_edge_aliases=contraction_edge_aliases,
            allow_non_motorized_lane_overlaps=strict_teacher_replay,
        )
        for compound_junction_id in compound_junction_ids
        if compound_junction_id in final_junction_ids
    }
    target_surface_overlap_gate = {
        "status": (
            "pass"
            if not missing_compound_junction_ids
            and all(row.get("status") == "pass" for row in target_surface_overlap_gates.values())
            else "fail"
        ),
        "junction_ids": compound_junction_ids,
        "missing_junction_ids": missing_compound_junction_ids,
        "junction_gates": target_surface_overlap_gates,
    }
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
    final_turnaround_scope = [
        identifier for identifier in control_cleanup_junction_ids if identifier in final_junction_ids
    ]
    turnaround_authority = _compound_teacher_turnaround_evidence(
        teacher_model=teacher_model,
        final_net_file=final_net_file,
        junction_id=junction_id,
        edge_map=comparison_edge_map,
        teacher_net_file=teacher_net_file,
        teacher_junction_id=teacher_junction_id,
        compound_junction_ids=final_turnaround_scope,
        teacher_absent_junction_ids=teacher_absent_tls_junction_ids,
    )
    turnaround_audit = audit_external_micro_junctions(
        final_net_file,
        junction_ids=final_turnaround_scope,
        turnaround_authority=turnaround_authority["authority_records"],
    )
    turnaround_audit["authority_mapping"] = turnaround_authority
    approach_authority_policy = _hybrid_osm_approach_authority_policy(
        semantic_gate,
        replay_target_internal_subgraph=replay_target_internal_subgraph,
        preserve_teacher_lane_shapes=preserve_teacher_lane_shapes,
        structural_osm_boundary_authority=structural_osm_boundary_authority,
        edge_map=comparison_edge_map,
        lane_patch=lane_patch_report,
        target_internal_replay=target_internal_replay_gate_report,
        target_internal_pedestrian_ring=target_internal_pedestrian_ring_report,
        tls_movement_parity=tls_movement_parity,
        pedestrian_crossing_parity=pedestrian_crossing_parity,
        connection_plan=connection_report,
        vehicle_connection_attrs=vehicle_attrs_report,
        boundary_edge_preservation=boundary_edge_preservation,
        boundary_vehicle_connectivity=boundary_vehicle_connectivity,
        target_surface_overlap_gate=target_surface_overlap_gate,
        turnaround_audit=turnaround_audit,
        strict_teacher_replay=strict_teacher_replay,
        preserved_target_shape_only_mismatch=(
            preserve_target_junction_shape
            and _junction_signature_mismatch_fields(parity) == {"shape"}
        ),
    )
    effective_semantic_gate = approach_authority_policy["effective_semantic_gate"]
    semantic_layer_gates = _semantic_layer_gates(
        effective_semantic_gate,
        tls_movement_parity,
        pedestrian_crossing_parity,
    )
    safety_gate = {
        "status": (
            "pass"
            if boundary_edge_preservation.get("status") == "pass"
            and boundary_vehicle_connectivity.get("status") == "pass"
            and target_surface_overlap_gate.get("status") == "pass"
            and turnaround_audit.get("automatic_promotion_gate") == "pass"
            and short_internal_lane_gate.get("status") == "pass"
            else "fail"
        ),
        "boundary_edge_preservation_status": boundary_edge_preservation.get("status"),
        "boundary_vehicle_connectivity_status": boundary_vehicle_connectivity.get("status"),
        "target_surface_overlap_status": target_surface_overlap_gate.get("status"),
        "turnaround_status": turnaround_audit.get("automatic_promotion_gate"),
        "short_internal_lane_status": short_internal_lane_gate.get("status"),
    }
    parity_gate_status = (
        "pass"
        if effective_semantic_gate["status"] == "pass"
        and safety_gate["status"] == "pass"
        and (
            not approach_authority_policy.get("requires_exact_tls_parity", True)
            or tls_movement_parity["status"] == "pass"
        )
        and (
            not approach_authority_policy.get("requires_exact_pedestrian_parity", True)
            or pedestrian_crossing_parity["status"] == "pass"
        )
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
            "preserve_target_junction_shape": preserve_target_junction_shape,
            "target_internal_replay_fallback_net_file": str(fallback_net_file)
            if target_internal_replay_fallback
            else "",
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
            "turnaround_prune": turnaround_prune_overlay,
            "teacher_absent_geometry_contraction": (teacher_absent_geometry_contraction_report),
            "non_target_internal_restore": non_target_internal_restore_report,
            "pedestrian_ring": pedestrian_ring_report,
            "vehicle_connection_attrs": vehicle_attrs_report,
            "target_internal_replay": target_internal_replay_report,
            "target_internal_replay_fallback_tl_logic": target_internal_replay_fallback_tl_logic_report,
            "target_internal_replay_fallback_sumo": target_internal_replay_fallback_sumo_report,
            "target_internal_normalize": target_internal_normalize_report,
            "teacher_guided_normalize": teacher_guided_normalize_report,
            "structural_pedestrian_normalize": structural_pedestrian_normalize_report,
            "target_internal_pedestrian_ring": target_internal_pedestrian_ring_report,
            "target_internal_vehicle_connection_attrs": target_internal_vehicle_attrs_report,
            "tl_logic": tl_logic_report,
            "sumo_load": sumo_report,
            "parity": parity,
            "approach_endpoint_rebuild_plan": approach_endpoint_rebuild_plan,
            "strict_structural_replay": strict_structural_replay,
            "strict_structural_junction_ids": movement_replay_junction_ids if strict_structural_replay else [],
            "strict_structural_edge_map_additions": strict_structural_edge_map_additions,
            "semantic_replay_gate": semantic_gate,
            "semantic_replay_effective_gate": effective_semantic_gate,
            "approach_authority_policy": approach_authority_policy,
            "boundary_edge_preservation": boundary_edge_preservation,
            "boundary_vehicle_connectivity": boundary_vehicle_connectivity,
            "target_surface_overlap_gate": target_surface_overlap_gate,
            "turnaround_authority": turnaround_authority,
            "turnaround_audit": turnaround_audit,
            "short_internal_lane_gate": short_internal_lane_gate,
            "safety_gate": safety_gate,
            "tls_movement_parity": tls_movement_parity,
            "pedestrian_crossing_parity": pedestrian_crossing_parity,
            "semantic_layer_gates": semantic_layer_gates,
            "review_policy": "diagnostic teacher-guided variant; inspect in NetEdit connection mode before adoption",
        },
    )


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value or [] if str(item)]


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
        "collapsed_source_junction_ids": sorted(
            set(_string_list(report.get("source_conflict_core_node_ids"))) - {junction_id}
        ),
    }


def _report_used_unrestored_normalized_replay(report: dict[str, Any]) -> bool:
    target_internal_normalize = report.get("target_internal_normalize", {})
    if not isinstance(target_internal_normalize, dict):
        return False
    unrestored_sumo_load = target_internal_normalize.get("unrestored_sumo_load", {})
    return isinstance(unrestored_sumo_load, dict) and unrestored_sumo_load.get("status") == "pass"


def _net_contains_normal_junctions(net_file: Path, junction_ids: set[str]) -> bool:
    if not junction_ids:
        return True
    try:
        root = ET.parse(net_file).getroot()
    except (OSError, ET.ParseError):
        return False
    net_junction_ids = {
        junction.attrib["id"]
        for junction in root.findall("junction")
        if junction.attrib.get("id") and not junction.attrib["id"].startswith(":")
    }
    return junction_ids <= net_junction_ids


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
            _teacher_pattern_metric_is_positive(teacher_pattern_key, metric) for metric in ("internal", "requests")
        )
    if learned_rule == "tum_like_turnaround_only_lane_candidate":
        teacher_pattern_key = str(candidate.get("teacher_pattern_key", ""))
        return any(
            _teacher_pattern_metric_is_positive(teacher_pattern_key, metric) for metric in ("internal", "requests")
        )
    return False


def _teacher_pattern_metric_is_positive(pattern_key: str, metric: str) -> bool:
    prefix = f"{metric}="
    for part in pattern_key.split("|"):
        if not part.startswith(prefix):
            continue
        for token in part[len(prefix) :].replace("/", ":").split(":"):
            try:
                if int(token) > 0:
                    return True
            except ValueError:
                continue
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


def _prune_plain_tls_against_teacher(
    *,
    teacher_net_file: Path,
    node_file: Path,
    connection_file: Path,
    tllogic_file: Path | None,
) -> dict[str, object]:
    """Keep sequential plain inputs from reviving TLS absent in the teacher.

    netconvert plain export can materialize a stale traffic-light program from
    an intermediate candidate.  That stale program later makes a valid join
    fail because the joined source junction is no longer a controller.  The
    teacher reference is authoritative for this cleanup; the main candidate
    network is not edited here.
    """
    if not all(path.exists() for path in (teacher_net_file, node_file, connection_file)):
        return {"status": "skipped", "reason": "plain_input_missing", "demoted_junction_count": 0}
    try:
        teacher_root = ET.parse(teacher_net_file).getroot()
        node_tree = ET.parse(node_file)
        connection_tree = ET.parse(connection_file)
        tllogic_tree = ET.parse(tllogic_file) if tllogic_file is not None and tllogic_file.exists() else None
    except (OSError, ET.ParseError) as exc:
        return {"status": "fail", "reason": f"parse_error: {exc}", "demoted_junction_count": 0}

    teacher_junction_types = {
        str(junction.attrib.get("id", "")): str(junction.attrib.get("type", ""))
        for junction in teacher_root.findall("junction")
        if junction.attrib.get("id")
    }
    teacher_tls_ids = {
        junction_id
        for junction_id, junction_type in teacher_junction_types.items()
        if junction_type.startswith("traffic_light")
    }
    for junction in teacher_root.findall("junction"):
        if not str(junction.attrib.get("type", "")).startswith("traffic_light"):
            continue
        teacher_tls_ids.update(str(item) for item in junction.attrib.get("tl", "").split() if str(item))
    teacher_tls_ids.update(
        str(logic.attrib.get("id", "")) for logic in teacher_root.findall("tlLogic") if logic.attrib.get("id")
    )

    demoted_junction_ids: list[str] = []
    invalid_tls_ids: set[str] = set()
    for node in node_tree.getroot().findall("node"):
        node_id = str(node.attrib.get("id", ""))
        if not node_id or not str(node.attrib.get("type", "")).startswith("traffic_light"):
            continue
        node_tls_ids = {node_id, *[str(item) for item in node.attrib.get("tl", "").split() if str(item)]}
        teacher_type = teacher_junction_types.get(node_id, "")
        valid = teacher_type.startswith("traffic_light") and bool(node_tls_ids & teacher_tls_ids)
        if valid:
            continue
        invalid_tls_ids.update(node_tls_ids)
        node.set("type", teacher_type or "priority")
        node.attrib.pop("tl", None)
        node.attrib.pop("tlType", None)
        demoted_junction_ids.append(node_id)

    removed_tllogic_ids: list[str] = []
    removed_tllogic_connection_count = 0
    if tllogic_tree is not None:
        tllogic_root = tllogic_tree.getroot()
        for child in list(tllogic_root):
            child_tls_id = str(child.attrib.get("id", child.attrib.get("tl", "")))
            if child_tls_id and child_tls_id in invalid_tls_ids:
                tllogic_root.remove(child)
                if child.tag == "tlLogic":
                    removed_tllogic_ids.append(child_tls_id)
                else:
                    removed_tllogic_connection_count += 1

    uncontrolled_connection_count = 0
    for connection in connection_tree.getroot().findall("connection"):
        tls_id = str(connection.attrib.get("tl", ""))
        if not tls_id or tls_id not in invalid_tls_ids:
            continue
        for attr in ("tl", "linkIndex", "linkIndex2"):
            connection.attrib.pop(attr, None)
        connection.set("uncontrolled", "true")
        uncontrolled_connection_count += 1

    if demoted_junction_ids:
        ET.indent(node_tree.getroot(), space="    ")
        node_tree.write(node_file, encoding="utf-8", xml_declaration=True)
    if tllogic_tree is not None and (removed_tllogic_ids or removed_tllogic_connection_count):
        ET.indent(tllogic_tree.getroot(), space="    ")
        tllogic_tree.write(tllogic_file, encoding="utf-8", xml_declaration=True)
    if uncontrolled_connection_count:
        ET.indent(connection_tree.getroot(), space="    ")
        connection_tree.write(connection_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "demoted_junction_count": len(demoted_junction_ids),
        "demoted_junction_ids": sorted(demoted_junction_ids),
        "removed_tllogic_count": len(removed_tllogic_ids),
        "removed_tllogic_ids": sorted(set(removed_tllogic_ids)),
        "removed_tllogic_connection_count": removed_tllogic_connection_count,
        "uncontrolled_connection_count": uncontrolled_connection_count,
    }


def _sequential_candidate_node_ids(candidate: Mapping[str, Any], junction_id: str) -> set[str]:
    matched = {str(item) for item in candidate.get("matched_candidate_node_ids", []) or [] if str(item)}
    exact = {
        str(item)
        for item in candidate.get("matched_reference_source_node_ids", []) or []
        if str(item)
    }
    node_ids = exact if exact and exact <= matched else matched
    if junction_id:
        node_ids.add(junction_id)
    return node_ids


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
    strict_teacher_replay: bool = False,
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
            str(cluster_id): sorted({str(node_id) for node_id in node_ids if str(node_id)})
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
                    edge.attrib["id"]: edge for edge in refresh_teacher_root.findall("edge") if edge.attrib.get("id")
                }
                refresh_candidate_edges = {
                    edge.attrib["id"]: edge for edge in refresh_candidate_root.findall("edge") if edge.attrib.get("id")
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
                    original_cluster_scope_ids = {item for item in original_scope_ids if item.startswith("cluster_")}
                    refreshed_expanded_scope = refreshed_candidate.get("expanded_rebuild_scope", {})
                    # A sequential refresh can make the core junction look
                    # individually repairable after an earlier candidate was
                    # applied.  Preserve the teacher's explicit split-cluster
                    # context in that case; otherwise the next replay silently
                    # downgrades a context repair into a single-node repair and
                    # the final composite regresses to the split cluster.
                    if original_cluster_scope_ids:
                        merged_scope = dict(
                            refreshed_expanded_scope if isinstance(refreshed_expanded_scope, dict) else {}
                        )
                        merged_scope.update(
                            {
                                key: value
                                for key, value in original_expanded_scope.items()
                                if key
                                in {
                                    "core_junction_id",
                                    "blocked_teacher_edge_ids",
                                    "missing_desired_endpoint_ids",
                                    "reason",
                                }
                            }
                        )
                        merged_scope["junction_ids"] = sorted(
                            original_scope_ids
                            | {str(item) for item in merged_scope.get("junction_ids", []) or [] if str(item)}
                        )
                        original_join_ids = {
                            str(item)
                            for item in original_expanded_scope.get("join_junction_ids", []) or []
                            if str(item)
                        }
                        refreshed_join_ids = {
                            str(item) for item in merged_scope.get("join_junction_ids", []) or [] if str(item)
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
        if expand_fragmented_tls_join_scope and candidate.get("candidate_status") == "needs_expanded_rebuild_scope":
            candidate = _expand_fragmented_tls_join_scope_candidate(
                candidate,
                current_raw_node_file,
                raw_edge_file=current_raw_edge_file,
                reference_net_file=teacher_net_file,
            )
            tls_scope_expansion = candidate.get("tls_join_scope_expansion", {})
            if isinstance(tls_scope_expansion, dict) and tls_scope_expansion.get("automatic_expansion_applied"):
                candidate = _augment_candidate_edge_map_from_tls_approach_pairs(candidate)
        junction_id = str(candidate.get("junction_id") or candidate.get("reference_id") or "")
        teacher_junction_id = str(candidate.get("reference_id") or junction_id)
        edge_map = _valid_edge_map(candidate.get("edge_map", {}))
        candidate_replay_target_internal_subgraph = (
            replay_target_internal_subgraph
            or strict_teacher_replay
            or _candidate_requests_target_internal_replay(candidate)
        )
        candidate_node_ids = _sequential_candidate_node_ids(candidate, junction_id)
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
        if (
            sequential_accept_passed_variants
            and not is_followup_candidate
            and (blocking_overlap_edge_ids or overlap_node_ids)
        ):
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
            # Strict teacher replay must materialize one explicit endpoint for
            # every joined member.  Letting netconvert infer this from the
            # <join> leaves boundary edges attached to different member nodes
            # after the connection file is replayed.
            rewrite_joined_endpoints = strict_teacher_replay
            joined_scope_junction_ids = [
                str(item) for item in scope_report.get("joined_scope_junction_ids", []) or [] if str(item)
            ] or ([joined_scope_junction_id] if joined_scope_junction_id else [])
            replay_edge_map = edge_map
            if not replay_edge_map and joined_scope_junction_id:
                try:
                    teacher_model = extract_teacher_junction_model(teacher_net_file, teacher_junction_id)
                    replay_edge_map = _teacher_candidate_edge_map(
                        teacher_model,
                        extract_teacher_junction_model(
                            Path(str(scope_report.get("net_file", ""))), joined_scope_junction_id
                        ),
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
            existing_joined_scope_materialized = (
                joined_scope_junction_id == junction_id
                and joined_scope_junction_id in _plain_node_ids(current_raw_node_file)
            )
            use_full_network_replay = (
                not str(scope_report.get("join_nodes_patch_file", ""))
                and (
                    existing_joined_scope_materialized
                    or not missing_node_ids
                    or missing_node_ids <= skipped_endpoint_missing_ids
                )
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
                *{str(edge_id) for edge_id in blocked_teacher_edge_ids if str(edge_id)},
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
                and (not scope_report.get("rewritten_endpoint_count") or rewrite_joined_endpoints)
                and not full_network_join_blocking_self_loop_edge_ids
                and not scope_report.get("blocking_missing_node_ids")
                and not scope_report.get("blocking_missing_blocked_edge_ids")
                and not scope_report.get("blocking_missing_joined_scope_junction_ids")
            )
            join_patch_joined_node_ids = _join_patch_joined_node_ids(join_patch_file)
            can_replace_stale_joined_node = (
                joined_scope_junction_id == junction_id and joined_scope_junction_id in join_patch_joined_node_ids
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
            replaced_stale_joined_node_ids = sorted(join_patch_joined_node_ids & _plain_node_ids(current_raw_node_file))
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
                replay_type_file = current_raw_type_file
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
                    (
                        aligned_raw_node_file,
                        full_network_join_edge_file,
                        coordinate_alignment,
                    ) = _write_candidate_aligned_plain_geometry(
                        node_file=current_raw_node_file,
                        edge_file=full_network_join_edge_file,
                        candidate_net_file=current_candidate_net_file,
                        output_node_file=output_dir / safe_junction_id / "full_network_join_aligned.nod.xml",
                        output_edge_file=output_dir / safe_junction_id / "full_network_join_aligned.edg.xml",
                    )
                    scope_report["full_network_join_coordinate_alignment"] = coordinate_alignment
                    if coordinate_alignment.get("status") != "pass":
                        scope_report["status"] = "review"
                        skipped_candidates.append(
                            {
                                "index": index,
                                "junction_id": junction_id,
                                "candidate_status": "full_network_join_coordinate_alignment_failed",
                            }
                        )
                        continue
                    replay_node_file = _write_replay_node_file(
                        aligned_raw_node_file,
                        join_patch_file,
                        output_dir / safe_junction_id / "full_network_join_replay.nod.xml",
                    )
                    controlled_inner_prune = _prune_plain_node_controlled_inner_edges(
                        replay_node_file,
                        set(full_network_join_dropped_self_loop_edges),
                    )
                    scope_report["full_network_join_controlled_inner_prune"] = controlled_inner_prune
                    replay_edge_file = full_network_join_edge_file
                    replay_connection_file, dead_end_drop_count, dead_end_drop_edge_ids = (
                        _write_join_scope_connection_file(
                            replay_edge_file,
                            current_raw_connection_file,
                            {str(node_id) for node_id in scope_report.get("join_node_ids", []) or [] if str(node_id)},
                            output_dir / safe_junction_id / "full_network_join_replay.con.xml",
                            drop_edge_ids=set(full_network_join_dropped_self_loop_edges),
                        )
                    )
                    (
                        rewritten_replay_edge_file,
                        rewritten_endpoint_count,
                        rewritten_self_loop_edges,
                        rewritten_blocking_self_loops,
                    ) = _write_joined_endpoint_edge_file(
                        replay_edge_file,
                        join_patch_file,
                        joined_scope_junction_ids,
                        output_dir / safe_junction_id / "full_network_join_replay_rewritten.edg.xml",
                        rewrite_endpoints=rewrite_joined_endpoints,
                    )
                    if rewrite_joined_endpoints:
                        rewritten_replay_connection_file, crossing_rewrite_count = (
                            _write_joined_endpoint_connection_file(
                                replay_connection_file,
                                join_patch_file,
                                output_dir / safe_junction_id / "full_network_join_replay_rewritten.con.xml",
                            )
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
                        scope_report["full_network_join_tllogic_connection_drop_count"] = tllogic_drop_count
                        scope_report["full_network_join_tllogic_connection_drop_edge_ids"] = tllogic_drop_edge_ids
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
                            output_file=output_dir / safe_junction_id / "full_network_join_replay.typ.xml",
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
                        "--offset.disable-normalization",
                        "true",
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
                    edge_map_candidate_net_file = replay_candidate_net_file
                    if rewrite_joined_endpoints:
                        mapping_candidate_net_file = (
                            output_dir / safe_junction_id / "full_network_join_mapping.net.xml"
                        )
                        mapping_command = [
                            netconvert_binary,
                            "--node-files",
                            _command_path(replay_node_file, output_dir / safe_junction_id),
                            "--edge-files",
                            _command_path(full_network_join_edge_file, output_dir / safe_junction_id),
                            "--output-file",
                            mapping_candidate_net_file.name,
                            "--walkingareas",
                            "true",
                            "--tls.ignore-internal-junction-jam",
                            "--offset.disable-normalization",
                            "true",
                        ]
                        if replay_type_file is not None:
                            mapping_command[5:5] = [
                                "--type-files",
                                _command_path(replay_type_file, output_dir / safe_junction_id),
                            ]
                        mapping_report = _command_report(
                            command_runner(
                                mapping_command,
                                cwd=output_dir / safe_junction_id,
                                timeout_seconds=timeout_seconds,
                            )
                        )
                        scope_report["full_network_join_mapping_netconvert"] = mapping_report
                        if mapping_report.get("status") == "pass":
                            edge_map_candidate_net_file = mapping_candidate_net_file
                    try:
                        refreshed_edge_map = _teacher_candidate_edge_map(
                            extract_teacher_junction_model(teacher_net_file, teacher_junction_id),
                            extract_teacher_junction_model(edge_map_candidate_net_file, joined_scope_junction_id),
                            teacher_junction_id=teacher_junction_id,
                            candidate_junction_id=joined_scope_junction_id,
                            drop_endpoint_mismatches=False,
                            max_bearing_delta=45.0,
                        )
                    except (ET.ParseError, OSError, KeyError, TypeError, ValueError) as exc:
                        refreshed_edge_map = {}
                        scope_report["full_network_join_refreshed_edge_map_error"] = f"{type(exc).__name__}: {exc}"
                    if refreshed_edge_map:
                        refreshed_edge_map = {
                            teacher_edge_id: (
                                teacher_edge_id
                                if replay_edge_map.get(teacher_edge_id) == teacher_edge_id
                                else candidate_edge_id
                            )
                            for teacher_edge_id, candidate_edge_id in refreshed_edge_map.items()
                        }
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
                    if plain_exporter is not None:
                        join_plain_report = plain_exporter(
                            net_file=replay_candidate_net_file,
                            output_dir=output_dir / safe_junction_id / "full_network_join_plain",
                            prefix=f"{variant_prefix}_join",
                            netconvert_binary=netconvert_binary,
                            timeout_seconds=timeout_seconds,
                        )
                        scope_report["full_network_join_plain_export"] = join_plain_report
                        if join_plain_report.get("status") != "pass":
                            scope_report["status"] = "review"
                            skipped_candidates.append(
                                {
                                    "index": index,
                                    "junction_id": junction_id,
                                    "candidate_status": "full_network_join_plain_export_failed",
                                }
                            )
                            continue
                        replay_node_file = Path(str(join_plain_report["raw_node_file"]))
                        replay_edge_file = Path(str(join_plain_report["raw_edge_file"]))
                        replay_connection_file = Path(str(join_plain_report["raw_connection_file"]))
                        raw_type_value = str(join_plain_report.get("raw_type_file", ""))
                        replay_type_file = Path(raw_type_value) if raw_type_value else None
                        raw_tllogic_value = str(join_plain_report.get("raw_tllogic_file", ""))
                        replay_tllogic_file = Path(raw_tllogic_value) if raw_tllogic_value else None
                        join_plain_tls_cleanup = _prune_plain_tls_against_teacher(
                            teacher_net_file=teacher_net_file,
                            node_file=replay_node_file,
                            connection_file=replay_connection_file,
                            tllogic_file=replay_tllogic_file,
                        )
                        scope_report["full_network_join_plain_teacher_tls_cleanup"] = join_plain_tls_cleanup
                        if join_plain_tls_cleanup.get("status") == "fail":
                            scope_report["status"] = "review"
                            skipped_candidates.append(
                                {
                                    "index": index,
                                    "junction_id": junction_id,
                                    "candidate_status": "full_network_join_plain_tls_cleanup_failed",
                                }
                            )
                            continue
                        partition_shape_report = _write_partition_aware_joined_junction_shapes(
                            joined_node_file=replay_node_file,
                            source_node_file=current_raw_node_file,
                            reference_net_file=replay_candidate_net_file,
                            join_groups=scope_report.get("join_groups", []),
                            output_file=(
                                output_dir
                                / safe_junction_id
                                / "full_network_join_plain"
                                / f"{variant_prefix}_partition_shapes.nod.xml"
                            ),
                        )
                        scope_report["partition_aware_join_shapes"] = partition_shape_report
                        if partition_shape_report.get("status") != "pass":
                            scope_report["status"] = "review"
                            skipped_candidates.append(
                                {
                                    "index": index,
                                    "junction_id": junction_id,
                                    "candidate_status": "partition_aware_join_shape_failed",
                                }
                            )
                            continue
                        replay_node_file = Path(str(partition_shape_report["output_file"]))
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
                variant_replay_target_internal_subgraph = (
                    candidate_replay_target_internal_subgraph
                    and (strict_teacher_replay or not use_full_network_join_patch_replay)
                )
                scope_report["full_network_join_structural_replay"] = (
                    use_full_network_join_patch_replay
                    and candidate_replay_target_internal_subgraph
                    and not variant_replay_target_internal_subgraph
                )
                expanded_scope_value = candidate.get("expanded_rebuild_scope", {})
                tls_scope_expansion = candidate.get("tls_join_scope_expansion", {})
                compound_teacher_junction_ids = _teacher_cluster_ids_for_join_groups(
                    scope_report.get("join_groups", []),
                    teacher_join_groups_by_cluster,
                    expanded_scope_value.get("junction_ids", [])
                    if isinstance(expanded_scope_value, dict)
                    else [],
                )
                teacher_absent_tls_junction_ids = sorted(
                    {
                        str(value)
                        for value in (
                            tls_scope_expansion.get(
                                "unjoined_reference_partition_fringe_node_ids",
                                [],
                            )
                            if isinstance(tls_scope_expansion, dict)
                            else []
                        )
                        if str(value)
                    }
                )
                compound_safety_junction_ids = sorted(
                    {
                        *joined_scope_junction_ids,
                        *(
                            str(value)
                            for value in (
                                expanded_scope_value.get("missing_desired_endpoint_ids", [])
                                if isinstance(expanded_scope_value, dict)
                                else []
                            )
                            if str(value)
                        ),
                    }
                )
                scope_report["compound_safety_junction_ids"] = compound_safety_junction_ids
                scope_report["compound_teacher_junction_ids"] = compound_teacher_junction_ids
                try:
                    variant_report = variant_builder(
                        raw_node_file=replay_node_file,
                        raw_edge_file=replay_edge_file,
                        raw_connection_file=replay_connection_file,
                        raw_type_file=replay_type_file,
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
                        replay_target_internal_subgraph=variant_replay_target_internal_subgraph,
                        preserve_teacher_lane_shapes=(
                            False if strict_teacher_replay else not use_full_network_join_patch_replay
                        ),
                        preserve_target_junction_shape=False,
                        structural_osm_boundary_authority=(
                            use_full_network_join_patch_replay and not strict_teacher_replay
                        ),
                        safety_junction_ids=compound_safety_junction_ids,
                        teacher_absent_tls_junction_ids=(teacher_absent_tls_junction_ids),
                        emit_teacher_crossings=(not use_full_network_join_patch_replay or strict_teacher_replay),
                        strict_teacher_replay=strict_teacher_replay,
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
                    strict_teacher_replay=strict_teacher_replay,
                    teacher_join_groups_by_cluster=teacher_join_groups_by_cluster,
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
                strict_teacher_replay=strict_teacher_replay,
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
            strict_teacher_replay=strict_teacher_replay,
            teacher_join_groups_by_cluster=teacher_join_groups_by_cluster,
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
                source_scope_ids, candidate_scope_ids = _candidate_connection_mode_scope_ids(variant_report)
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
        use_clean_replay_base = any(
            entry.get("prefer_clean_replay_base") for entry in accepted_internal_replays
        ) and not any(
            entry.get("collapsed_source_junction_ids") for entry in accepted_internal_replays
        ) and _net_contains_normal_junctions(candidate_net_file, replay_junction_ids)
        current_composite_net_file = candidate_net_file if use_clean_replay_base else Path(composite_net_file)
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
                        for replay_entry, replay_report in zip(
                            accepted_internal_replays, final_internal_replay_reports
                        ):
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
    final_composite_sumo_load: dict[str, object] = {
        "status": "skipped",
        "reason": "no_applied_composite",
    }
    final_composite_build_failed = sequential_accept_passed_variants and final_internal_replay_status == "fail"
    final_composite_runtime_required = sequential_accept_passed_variants and pass_count > 0
    if final_composite_build_failed:
        final_composite_sumo_load = {
            "status": "fail",
            "reason": "final_internal_replay_failed",
            "net_file": "",
        }
    elif final_composite_runtime_required:
        final_composite_path = Path(composite_net_file) if composite_net_file else None
        if final_composite_path is None or not final_composite_path.is_file():
            final_composite_sumo_load = {
                "status": "fail",
                "reason": "applied composite network is missing",
                "net_file": str(final_composite_path or ""),
            }
        else:
            final_composite_sumo_load = _command_report(
                command_runner(
                    [
                        sumo_binary,
                        "-n",
                        _command_path(final_composite_path, output_dir),
                        "--no-step-log",
                        "true",
                        "--duration-log.disable",
                        "true",
                        "--begin",
                        "0",
                        "--end",
                        "1",
                    ],
                    cwd=output_dir,
                    timeout_seconds=timeout_seconds,
                )
            )
            final_composite_sumo_load["net_file"] = str(final_composite_path)
            final_composite_sumo_load["network_sha256"] = hashlib.sha256(final_composite_path.read_bytes()).hexdigest()
    final_composite_sumo_load["runtime_required"] = final_composite_runtime_required
    final_composite_sumo_load_failed = final_composite_build_failed or (
        final_composite_runtime_required and final_composite_sumo_load.get("status") != "pass"
    )
    sequential_composite_ready = (
        sequential_accept_passed_variants
        and composite_applied_candidate_count > 0
        and bool(composite_net_file)
        and Path(composite_net_file).exists()
        and final_internal_replay_status != "fail"
        and not final_composite_parity_failed
        and not final_context_parity_failed
        and not final_composite_sumo_load_failed
    )
    if attempted_count == 0:
        status = "blocked"
        claim_status = "blocked"
        parity_gate_status = "blocked"
    elif final_composite_build_failed:
        status = "fail"
        claim_status = "construction-invalid"
        parity_gate_status = "fail"
    elif final_composite_parity_failed:
        status = "fail"
        claim_status = "construction-invalid"
        parity_gate_status = "fail"
    elif final_context_parity_failed:
        status = "fail"
        claim_status = "construction-invalid"
        parity_gate_status = "pass" if parity_pass_count == attempted_count else "fail"
    elif final_composite_sumo_load_failed:
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
        final_composite_sumo_load_status=str(final_composite_sumo_load.get("status", "skipped")),
        final_composite_sumo_load_required=final_composite_runtime_required,
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
        "final_composite_sumo_load": final_composite_sumo_load,
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


def _int_count(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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


def _split_cluster_member_residuals(
    teacher_context: dict[str, object],
    candidate_context: dict[str, object],
    *,
    teacher_join_groups_by_cluster: dict[str, list[str]] | None = None,
) -> list[dict[str, object]]:
    candidate_junction_ids = {str(item) for item in candidate_context.get("junction_ids", []) or [] if str(item)}
    residuals: list[dict[str, object]] = []
    for teacher_junction_id in teacher_context.get("junction_ids", []) or []:
        teacher_junction_id = str(teacher_junction_id)
        if not teacher_junction_id.startswith("cluster_"):
            continue
        member_ids = list((teacher_join_groups_by_cluster or {}).get(teacher_junction_id, []))
        if not member_ids:
            member_ids = [item for item in teacher_junction_id.removeprefix("cluster_").split("_") if item]
        residual_members = sorted(member_id for member_id in member_ids if member_id in candidate_junction_ids)
        if residual_members:
            residuals.append(
                {
                    "teacher_cluster_junction_id": teacher_junction_id,
                    "candidate_member_junction_ids": residual_members,
                }
            )
    return residuals


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
        str(connection.attrib.get("tl", "")) for connection in local_connections if connection.attrib.get("tl")
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
        tllogic for tllogic in root.findall("tlLogic") if str(tllogic.attrib.get("id", "")) in local_tls_ids
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


def _junction_within_radius(junction: ET.Element, *, center: tuple[float, float], radius_m: float) -> bool:
    try:
        x = float(junction.attrib.get("x", ""))
        y = float(junction.attrib.get("y", ""))
    except ValueError:
        return False
    return math.hypot(x - center[0], y - center[1]) <= radius_m


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


def _safe_junction_shape(shape: str) -> str | None:
    """Keep finite valid points; repair SUMO sentinel/self-intersecting shapes."""

    tokens = [token for token in shape.split() if "," in token]
    points = [
        (x, y)
        for x, y in _shape_points(shape)
        if math.isfinite(x) and math.isfinite(y) and abs(x) <= 1_000_000 and abs(y) <= 1_000_000
    ]
    if len(points) < 3:
        return None
    polygon = Polygon(points)
    if polygon.is_valid and polygon.area > 0 and len(points) == len(tokens):
        return " ".join(tokens)
    points = _convex_hull(points)
    if len(points) < 3:
        return None
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def _sanitize_junction_shapes(root: ET.Element) -> dict[str, object]:
    """Prevent one invalid SUMO shape from making the whole GUI viewport unusable."""

    repaired_ids: list[str] = []
    invalid_shape_count = 0
    for junction in root.findall("junction"):
        junction_id = str(junction.attrib.get("id", ""))
        try:
            center_x = float(junction.attrib.get("x", ""))
            center_y = float(junction.attrib.get("y", ""))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(center_x) and math.isfinite(center_y)):
            continue
        changed = False
        for attribute in ("shape", "customShape"):
            original = junction.attrib.get(attribute)
            if not original or (attribute == "customShape" and "," not in original):
                continue
            tokens = [token for token in original.split() if "," in token]
            points = _shape_points(original)
            has_unusable_coordinate = (
                len(points) != len(tokens)
                or not points
                or any(
                    not (math.isfinite(x) and math.isfinite(y))
                    or abs(x) > 1_000_000
                    or abs(y) > 1_000_000
                    for x, y in points
                )
            )
            if not has_unusable_coordinate:
                continue
            if has_unusable_coordinate:
                invalid_shape_count += 1
                radius = 0.5
                safe = (
                    f"{center_x - radius:.2f},{center_y - radius:.2f} "
                    f"{center_x + radius:.2f},{center_y - radius:.2f} "
                    f"{center_x + radius:.2f},{center_y + radius:.2f} "
                    f"{center_x - radius:.2f},{center_y + radius:.2f}"
                )
            if safe != original:
                junction.attrib[attribute] = safe
                changed = True
        if changed:
            repaired_ids.append(junction_id)
    return {
        "status": "pass",
        "repaired_count": len(repaired_ids),
        "repaired_junction_ids": repaired_ids,
        "invalid_shape_count": invalid_shape_count,
    }


def _road_continuity_probe_summary(run_report: dict[str, Any]) -> dict[str, object]:
    counts: dict[str, int] = {}
    failure_counts: dict[str, int] = {}
    replay_count = 0
    for variant in run_report.get("variant_reports", []) or []:
        if not isinstance(variant, dict) or variant.get("expanded_scope_followup_emitted"):
            continue
        replay = variant.get("target_internal_replay")
        if not isinstance(replay, dict):
            policy = variant.get("approach_authority_policy")
            preservation = variant.get("boundary_edge_preservation")
            if (
                isinstance(policy, dict)
                and policy.get("policy") == "osm_boundary_teacher_vehicle_movements"
                and isinstance(preservation, dict)
            ):
                replay_count += 1
                source_count = _int_count(preservation.get("source_boundary_edge_count", 0))
                missing_count = len(preservation.get("missing_boundary_edge_ids", []) or [])
                counts["preserved_boundary_edge_count"] = (
                    counts.get("preserved_boundary_edge_count", 0) + source_count - missing_count
                )
                if policy.get("status") != "pass" or preservation.get("status") != "pass":
                    failure_counts["boundary_edge_preservation"] = failure_counts.get(
                        "boundary_edge_preservation", 0
                    ) + max(1, missing_count)
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
    plain_exporter: Any | None = None,
    sequential_accept_passed_variants: bool = False,
    strict_teacher_replay: bool = False,
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
        single_queue["expanded_scope_candidate_count"] = 1 if candidate_status == "needs_expanded_rebuild_scope" else 0
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
            expand_fragmented_tls_join_scope=True,
            sequential_accept_passed_variants=sequential_accept_passed_variants,
            strict_teacher_replay=strict_teacher_replay,
            plain_exporter=plain_exporter,
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
    all_road_continuity_pass = bool(probes) and all(probe["road_continuity_gate_status"] == "pass" for probe in probes)
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
        str(item) for item in (requested_join_ids if requested_join_ids is not None else default_join_ids) if str(item)
    ]
    blocked_edge_ids = {str(item) for item in scope.get("blocked_teacher_edge_ids", []) or [] if str(item)}
    teacher_join_groups_by_cluster = teacher_join_groups_by_cluster or {}
    cluster_members_by_alias = {
        _canonical_sumo_cluster_id(cluster_id): _sumo_cluster_member_ids(cluster_id)
        for cluster_id in raw_scope_junction_ids
        if cluster_id.startswith("cluster_") and len(_sumo_cluster_member_ids(cluster_id)) > 4
    }
    cluster_members_by_alias.update(
        {
            _canonical_sumo_cluster_id(cluster_id): members
            for cluster_id, members in teacher_join_groups_by_cluster.items()
        }
    )

    def resolved_cluster_members(value: str) -> list[str]:
        return (
            teacher_join_groups_by_cluster.get(value)
            or cluster_members_by_alias.get(_canonical_sumo_cluster_id(value))
            or _sumo_cluster_member_ids(value)
        )

    raw_nodes = {
        node.attrib["id"]: node
        for node in ET.parse(raw_node_file).getroot()
        if node.tag == "node" and node.attrib.get("id")
    }

    def expand_scope_ids(values: list[str]) -> set[str]:
        expanded: set[str] = set()
        for value in values:
            members = resolved_cluster_members(value)
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
        cluster_members = sorted(
            member
            for member in resolved_cluster_members(cluster_id)
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
            source_members = {
                member
                for member in resolved_cluster_members(source_cluster_id)
                if member in raw_nodes
            }
            if source_members and source_members == set(group):
                cluster_aliases[source_cluster_id] = generated_id
        cluster_aliases.setdefault(generated_id, generated_id)

    def resolve_scope_endpoint(value: str) -> str:
        return cluster_aliases.get(value, value)

    joined_scope_junction_ids = [
        joined_id for joined_id in (_sumo_joined_cluster_id(group) for group in join_groups) if joined_id
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
        selected_node_ids.update(
            endpoint for endpoint in (edge.attrib.get("from", ""), edge.attrib.get("to", "")) if endpoint
        )

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
    if explicit_join_groups and len(join_groups) == 1 and joined_scope_junction_ids:
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
            connection.attrib.get("from", "") in selected_edge_ids
            or connection.attrib.get("to", "") in selected_edge_ids
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
        resolve_scope_endpoint(str(item)) for item in scope.get("missing_desired_endpoint_ids", []) or [] if str(item)
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
    probe_status = (
        "pass" if netconvert_report.get("status") == "pass" and sumo_report.get("status") == "pass" else "fail"
    )
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


def _connection_edges_are_adjacent(connection: ET.Element, edge_endpoints: dict[str, tuple[str, str]]) -> bool:
    source = edge_endpoints.get(connection.attrib.get("from", ""))
    target = edge_endpoints.get(connection.attrib.get("to", ""))
    return bool(source and target and source[1] == target[0])


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


def _write_partition_aware_joined_junction_shapes(
    *,
    joined_node_file: Path,
    source_node_file: Path,
    reference_net_file: Path | None = None,
    join_groups: object,
    output_file: Path,
    margin_m: float = 1.0,
) -> dict[str, object]:
    """Bound each joined junction to its evidence-authorized source partition."""

    if not joined_node_file.is_file() or not source_node_file.is_file():
        return _failure("joined and source plain-node files are required")
    if not math.isfinite(margin_m) or margin_m <= 0:
        return _failure("junction shape margin must be a positive finite number")
    normalized_groups = [
        sorted({str(node_id) for node_id in group if str(node_id)})
        for group in (join_groups if isinstance(join_groups, (list, tuple)) else [])
        if isinstance(group, (list, tuple, set))
    ]
    normalized_groups = [group for group in normalized_groups if len(group) >= 2]
    if not normalized_groups:
        return _failure("at least one joined source-node partition is required")

    try:
        joined_tree = ET.parse(joined_node_file)
        source_root = ET.parse(source_node_file).getroot()
        reference_root = ET.parse(reference_net_file).getroot() if reference_net_file is not None else None
    except (ET.ParseError, OSError) as exc:
        return _failure(f"plain-node XML is unreadable: {type(exc).__name__}: {exc}")
    joined_root = joined_tree.getroot()
    joined_nodes = {node.attrib["id"]: node for node in joined_root.findall("node") if node.attrib.get("id")}
    source_nodes = {node.attrib["id"]: node for node in source_root.findall("node") if node.attrib.get("id")}
    reference_junctions = {
        junction.attrib["id"]: junction
        for junction in (reference_root.findall("junction") if reference_root is not None else [])
        if junction.attrib.get("id") and junction.attrib.get("shape")
    }
    source_sha256 = hashlib.sha256(source_node_file.read_bytes()).hexdigest()
    joined_sha256 = hashlib.sha256(joined_node_file.read_bytes()).hexdigest()
    repairs: list[dict[str, object]] = []
    polygons: list[tuple[str, Polygon]] = []
    failures: list[dict[str, object]] = []

    for group in normalized_groups:
        joined_id = _sumo_joined_cluster_id(group)
        joined_node = joined_nodes.get(joined_id)
        missing_source_ids = sorted(set(group) - set(source_nodes))
        if joined_node is None or missing_source_ids:
            failures.append(
                {
                    "joined_junction_id": joined_id,
                    "reason": "joined_or_source_node_missing",
                    "joined_node_present": joined_node is not None,
                    "missing_source_node_ids": missing_source_ids,
                }
            )
            continue
        try:
            source_points = [
                (float(source_nodes[node_id].attrib["x"]), float(source_nodes[node_id].attrib["y"]))
                for node_id in group
            ]
            joined_point = Point(float(joined_node.attrib["x"]), float(joined_node.attrib["y"]))
        except (KeyError, TypeError, ValueError) as exc:
            failures.append(
                {
                    "joined_junction_id": joined_id,
                    "reason": "source_or_joined_node_coordinate_invalid",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        if any(not math.isfinite(value) for point in source_points for value in point) or not all(
            math.isfinite(value) for value in joined_point.coords[0]
        ):
            failures.append(
                {
                    "joined_junction_id": joined_id,
                    "reason": "source_or_joined_node_coordinate_non_finite",
                }
            )
            continue

        source_partition = concave_hull(
            MultiPoint(source_points),
            ratio=0.0,
            allow_holes=False,
        ).buffer(
            margin_m,
            quad_segs=1,
            cap_style="square",
            join_style="bevel",
        )
        reference_partition = reference_junctions.get(joined_id)
        shape_authority = "source_partition_concave_hull"
        polygon = Polygon()
        if reference_partition is not None:
            try:
                delta_x = joined_point.x - float(reference_partition.attrib["x"])
                delta_y = joined_point.y - float(reference_partition.attrib["y"])
                reference_polygon = Polygon(
                    (
                        float(token.split(",")[0]) + delta_x,
                        float(token.split(",")[1]) + delta_y,
                    )
                    for token in reference_partition.attrib["shape"].split()
                )
                reference_covers_partition = reference_polygon.covers(joined_point) and all(
                    reference_polygon.covers(Point(point)) for point in source_points
                )
                if reference_polygon.is_valid and not reference_polygon.is_empty and reference_covers_partition:
                    polygon = reference_polygon
                    shape_authority = "current_osm_joined_partition_shape"
            except (KeyError, TypeError, ValueError):
                polygon = Polygon()
        if polygon.is_empty:
            polygon = source_partition
        if not isinstance(polygon, Polygon) or polygon.is_empty or not polygon.is_valid:
            failures.append(
                {
                    "joined_junction_id": joined_id,
                    "reason": "source_partition_did_not_form_one_valid_polygon",
                    "geometry_type": polygon.geom_type,
                }
            )
            continue
        rounded_points = [
            (
                0.0 if abs(x) < 0.005 else round(x, 2),
                0.0 if abs(y) < 0.005 else round(y, 2),
            )
            for x, y in list(polygon.exterior.coords)[:-1]
        ]
        rounded_polygon = Polygon(rounded_points)
        uncovered_source_ids = [
            node_id for node_id, point in zip(group, source_points) if not rounded_polygon.covers(Point(point))
        ]
        if (
            len(set(rounded_points)) < 3
            or rounded_polygon.is_empty
            or not rounded_polygon.is_valid
            or rounded_polygon.interiors
            or not rounded_polygon.covers(joined_point)
            or uncovered_source_ids
        ):
            failures.append(
                {
                    "joined_junction_id": joined_id,
                    "reason": "rounded_partition_shape_failed_containment_or_validity",
                    "joined_point_covered": rounded_polygon.covers(joined_point),
                    "uncovered_source_node_ids": uncovered_source_ids,
                }
            )
            continue
        new_shape = " ".join(f"{x:.2f},{y:.2f}" for x, y in rounded_points)
        repairs.append(
            {
                "joined_junction_id": joined_id,
                "source_node_ids": group,
                "old_shape": joined_node.attrib.get("shape", ""),
                "new_shape": new_shape,
                "polygon_area_m2": round(rounded_polygon.area, 6),
                "polygon_point_count": len(rounded_points),
                "margin_m": margin_m,
                "shape_authority": shape_authority,
            }
        )
        joined_node.set("shape", new_shape)
        polygons.append((joined_id, rounded_polygon))

    for index, (left_id, left_polygon) in enumerate(polygons):
        for right_id, right_polygon in polygons[index + 1 :]:
            overlap_area = left_polygon.intersection(right_polygon).area
            if overlap_area > 1e-6:
                failures.append(
                    {
                        "reason": "authorized_partition_shapes_overlap",
                        "left_junction_id": left_id,
                        "right_junction_id": right_id,
                        "overlap_area_m2": round(overlap_area, 6),
                    }
                )

    if failures:
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "joined_node_file": str(joined_node_file),
            "source_node_file": str(source_node_file),
            "output_file": str(output_file),
            "repair_count": len(repairs),
            "failure_count": len(failures),
            "failures": failures,
            "policy": "fail closed; source partitions must produce separate valid joined-junction shapes",
        }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(joined_root, space="    ")
    joined_tree.write(output_file, encoding="utf-8", xml_declaration=True)
    source_sha256_after = hashlib.sha256(source_node_file.read_bytes()).hexdigest()
    joined_sha256_after = hashlib.sha256(joined_node_file.read_bytes()).hexdigest()
    source_network_mutation = source_sha256_after != source_sha256 or joined_sha256_after != joined_sha256
    status = "pass" if not source_network_mutation else "fail"
    return {
        "status": status,
        "claim_status": "diagnostic-demo" if status == "pass" else "construction-invalid",
        "joined_node_file": str(joined_node_file),
        "joined_node_sha256": joined_sha256,
        "joined_node_sha256_after": joined_sha256_after,
        "source_node_file": str(source_node_file),
        "source_node_sha256": source_sha256,
        "source_node_sha256_after": source_sha256_after,
        "source_network_mutation": source_network_mutation,
        "output_file": str(output_file),
        "output_sha256": hashlib.sha256(output_file.read_bytes()).hexdigest(),
        "repair_count": len(repairs),
        "repairs": repairs,
        "failure_count": 0,
        "failures": [],
        "policy": (
            "derive each joined-junction polygon only from its TUM-authorized source-node partition; "
            "keep adjacent partitions separate and preserve all edge, lane, movement, and TLS inputs"
        ),
    }


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


def _write_join_scope_connection_file(
    edge_file: Path,
    connection_file: Path,
    join_node_ids: set[str],
    output_file: Path,
    *,
    drop_edge_ids: set[str] | None = None,
) -> tuple[Path, int, list[str]]:
    drop_edge_ids = drop_edge_ids or set()
    if not join_node_ids and not drop_edge_ids:
        return connection_file, 0, []
    incident_edge_ids = {
        edge.attrib["id"]
        for edge in ET.parse(edge_file).getroot().findall("edge")
        if edge.attrib.get("id")
        and (edge.attrib.get("from") in join_node_ids or edge.attrib.get("to") in join_node_ids)
    }
    if not incident_edge_ids and not drop_edge_ids:
        return connection_file, 0, []
    connection_root = ET.parse(connection_file).getroot()
    filtered_root = ET.Element(connection_root.tag, connection_root.attrib)
    dropped_edge_ids = []
    for connection in connection_root:
        if connection.tag == "crossing":
            crossing_edge_ids = set(connection.attrib.get("edges", "").split())
            if crossing_edge_ids & drop_edge_ids:
                dropped_edge_ids.extend(sorted(edge_id for edge_id in crossing_edge_ids & drop_edge_ids if edge_id))
                continue
        connection_edge_ids = {connection.attrib.get("from", ""), connection.attrib.get("to", "")}
        if connection.tag == "connection" and connection_edge_ids & drop_edge_ids:
            dropped_edge_ids.extend(sorted(edge_id for edge_id in connection_edge_ids & drop_edge_ids if edge_id))
            continue
        if (
            connection.tag == "connection"
            and connection.attrib.get("from", "") in incident_edge_ids
            and not connection.attrib.get("to")
        ):
            dropped_edge_ids.append(connection.attrib.get("from", ""))
            continue
        filtered_root.append(copy.deepcopy(connection))
    if not dropped_edge_ids:
        return connection_file, 0, []
    ET.indent(filtered_root, space="    ")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(filtered_root).write(output_file, encoding="utf-8", xml_declaration=True)
    return output_file, len(dropped_edge_ids), dropped_edge_ids


def _prune_plain_node_controlled_inner_edges(
    node_file: Path,
    drop_edge_ids: set[str],
) -> dict[str, object]:
    """Remove absorbed join-internal edges from plain-node TLS hints.

    ``netconvert --plain-output-prefix`` repeats ``controlledInner`` on every
    node that belongs to a joined controller.  Once a physical micro-edge is
    absorbed by an explicit junction join, leaving that id in the staged node
    file can revive a reference to an edge that no longer exists.
    """

    if not drop_edge_ids:
        return {
            "status": "pass",
            "updated_node_count": 0,
            "removed_edge_reference_count": 0,
            "removed_edge_ids": [],
        }
    try:
        node_tree = ET.parse(node_file)
    except (ET.ParseError, OSError) as exc:
        return {
            "status": "fail",
            "updated_node_count": 0,
            "removed_edge_reference_count": 0,
            "removed_edge_ids": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    updated_node_count = 0
    removed_edge_reference_count = 0
    removed_edge_ids: list[str] = []
    for node in node_tree.getroot().findall("node"):
        raw_value = node.attrib.get("controlledInner", "")
        if not raw_value:
            continue
        edge_ids = raw_value.split()
        kept = [edge_id for edge_id in edge_ids if edge_id not in drop_edge_ids]
        removed = [edge_id for edge_id in edge_ids if edge_id in drop_edge_ids]
        if not removed:
            continue
        updated_node_count += 1
        removed_edge_reference_count += len(removed)
        removed_edge_ids.extend(removed)
        if kept:
            node.set("controlledInner", " ".join(kept))
        else:
            node.attrib.pop("controlledInner", None)

    if updated_node_count:
        ET.indent(node_tree.getroot(), space="    ")
        node_tree.write(node_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "updated_node_count": updated_node_count,
        "removed_edge_reference_count": removed_edge_reference_count,
        "removed_edge_ids": sorted(set(removed_edge_ids)),
    }


def _write_join_scope_tllogic_file(
    tllogic_file: Path,
    drop_edge_ids: set[str],
    output_file: Path,
) -> tuple[Path, int, list[str]]:
    """Stage TLS definitions without bindings to absorbed micro-edges."""

    if not drop_edge_ids:
        return tllogic_file, 0, []
    tllogic_tree = ET.parse(tllogic_file)
    root = tllogic_tree.getroot()
    dropped_edge_ids: list[str] = []
    for child in list(root):
        if child.tag != "connection":
            continue
        connection_edge_ids = {
            child.attrib.get("from", ""),
            child.attrib.get("to", ""),
        }
        removed = sorted(edge_id for edge_id in connection_edge_ids & drop_edge_ids if edge_id)
        if not removed:
            continue
        root.remove(child)
        dropped_edge_ids.extend(removed)

    if not dropped_edge_ids:
        return tllogic_file, 0, []
    ET.indent(root, space="    ")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    tllogic_tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return output_file, len(dropped_edge_ids), dropped_edge_ids


def _joined_endpoint_self_loop_edge_ids(
    edge_file: Path,
    join_patch_file: Path,
    joined_junction_id: object,
) -> tuple[list[str], list[str]]:
    if not join_patch_file.is_file() or not _normalize_joined_junction_ids(joined_junction_id):
        return [], []
    endpoint_rewrites = _selected_join_endpoint_rewrites(join_patch_file, joined_junction_id)
    if not endpoint_rewrites:
        return [], []
    dropped_self_loop_edges = []
    blocking_self_loop_edge_drops = []
    edge_root = ET.parse(edge_file).getroot()
    for edge in edge_root.findall("edge"):
        joined_from = endpoint_rewrites.get(edge.attrib.get("from", ""))
        joined_to = endpoint_rewrites.get(edge.attrib.get("to", ""))
        if joined_from and joined_from == joined_to:
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
    selected_endpoint_rewrites = _selected_join_endpoint_rewrites(join_patch_file, joined_junction_id)
    if not selected_endpoint_rewrites:
        return edge_file, 0, [], []
    endpoint_rewrites = selected_endpoint_rewrites if rewrite_endpoints else {}

    edge_root = ET.parse(edge_file).getroot()
    rewrite_count = 0
    dropped_self_loop_edges = []
    blocking_self_loop_edge_drops = []
    for edge in list(edge_root.findall("edge")):
        joined_from = selected_endpoint_rewrites.get(edge.attrib.get("from", ""))
        joined_to = selected_endpoint_rewrites.get(edge.attrib.get("to", ""))
        if joined_from and joined_from == joined_to:
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


def _edge_file_ids(edge_file: Path) -> set[str]:
    try:
        return {edge.attrib["id"] for edge in ET.parse(edge_file).getroot().findall("edge") if edge.attrib.get("id")}
    except (ET.ParseError, OSError):
        return set()


def _external_boundary_edge_ids(net_file: Path, junction_id: str) -> set[str]:
    return {
        edge.attrib["id"]
        for edge in ET.parse(net_file).getroot().findall("edge")
        if edge.attrib.get("id")
        and not edge.attrib.get("function")
        and not edge.attrib["id"].startswith(":")
        and junction_id in (edge.attrib.get("from"), edge.attrib.get("to"))
    }


def _boundary_edge_replacement_aliases(
    source_net_file: Path,
    final_net_file: Path,
    *,
    source_boundary_edge_ids: set[str],
    final_boundary_edge_ids: set[str],
    missing_boundary_edge_ids: set[str],
) -> dict[str, str]:
    source_edges = {
        edge.attrib["id"]: edge
        for edge in ET.parse(source_net_file).getroot().findall("edge")
        if edge.attrib.get("id")
    }
    final_edges = {
        edge.attrib["id"]: edge
        for edge in ET.parse(final_net_file).getroot().findall("edge")
        if edge.attrib.get("id")
    }
    aliases: dict[str, str] = {}
    for source_edge_id in sorted(missing_boundary_edge_ids):
        source_edge = source_edges.get(source_edge_id)
        if source_edge is None:
            continue
        source_type = source_edge.attrib.get("type", "")
        opposite_edge_id = _opposite_direction_edge_id(source_edge_id)
        opposite_edge = final_edges.get(opposite_edge_id)
        if (
            opposite_edge_id in final_boundary_edge_ids
            and opposite_edge_id not in source_boundary_edge_ids
            and opposite_edge is not None
            and opposite_edge.attrib.get("type", "") == source_type
        ):
            aliases[source_edge_id] = opposite_edge_id
            continue
        source_endpoints = {
            source_edge.attrib.get("from", ""),
            source_edge.attrib.get("to", ""),
        }
        if not all(source_endpoints):
            continue
        split_candidates = [
            final_edge_id
            for final_edge_id in sorted(final_boundary_edge_ids - source_boundary_edge_ids)
            if (
                (final_edge := final_edges.get(final_edge_id)) is not None
                and _signed_edge_family_id(final_edge_id) == _signed_edge_family_id(source_edge_id)
                and final_edge.attrib.get("type", "") == source_type
                and (
                    final_edge.attrib.get("from", "") == source_edge.attrib.get("from", "")
                    or final_edge.attrib.get("to", "") == source_edge.attrib.get("to", "")
                )
            )
        ]
        if len(split_candidates) == 1:
            aliases[source_edge_id] = split_candidates[0]
            continue
        candidates = [
            final_edge_id
            for final_edge_id in sorted(final_boundary_edge_ids - source_boundary_edge_ids)
            if (
                (final_edge := final_edges.get(final_edge_id)) is not None
                and final_edge.attrib.get("type", "") == source_type
                and {
                    final_edge.attrib.get("from", ""),
                    final_edge.attrib.get("to", ""),
                }
                == source_endpoints
            )
        ]
        if len(candidates) == 1:
            aliases[source_edge_id] = candidates[0]
    return aliases


def _reference_teacher_turnaround_authority(
    *,
    teacher_model: dict[str, object],
    final_net_file: Path,
    junction_id: str,
    edge_map: dict[str, str],
    teacher_net_file: Path,
    teacher_junction_id: str,
) -> dict[str, object]:
    root = ET.parse(final_net_file).getroot()
    teacher_root = ET.parse(teacher_net_file).getroot()
    edges = {
        edge.attrib["id"]: edge
        for edge in root.findall("edge")
        if edge.attrib.get("id") and not edge.attrib["id"].startswith(":")
    }
    observed_connections = {
        (
            connection.attrib.get("from", ""),
            connection.attrib.get("to", ""),
            connection.attrib.get("fromLane", "0"),
            connection.attrib.get("toLane", "0"),
        ): connection
        for connection in root.findall("connection")
        if connection.attrib.get("dir", "").lower() == TURNAROUND_DIR
    }
    observed_signatures = set(observed_connections)
    teacher_edges = {
        edge.attrib["id"]: edge
        for edge in teacher_root.findall("edge")
        if edge.attrib.get("id") and not edge.attrib["id"].startswith(":")
    }

    def teacher_lane_classes(edge_id: str, lane_index: str) -> set[str] | None:
        edge = teacher_edges.get(edge_id)
        if edge is None:
            return None
        lane = next(
            (item for item in edge.findall("lane") if item.attrib.get("index", "0") == lane_index),
            None,
        )
        return _sumo_allowed_classes(dict(lane.attrib)) if lane is not None else None

    def candidate_lane_classes(edge_id: str, lane_index: str) -> set[str] | None:
        edge = edges.get(edge_id)
        if edge is None:
            return None
        lane = next(
            (item for item in edge.findall("lane") if item.attrib.get("index", "0") == lane_index),
            None,
        )
        return _sumo_allowed_classes(dict(lane.attrib)) if lane is not None else None

    def connection_classes(
        source_classes: set[str],
        target_classes: set[str],
        attrs: dict[str, object],
    ) -> set[str]:
        return source_classes & target_classes & _sumo_allowed_classes(attrs)

    teacher_sha256 = hashlib.sha256(teacher_net_file.read_bytes()).hexdigest()
    authority: list[dict[str, object]] = []
    unmapped: list[dict[str, object]] = []
    mapped_signatures: list[tuple[str, str, str, str]] = []
    teacher_turnarounds = [
        connection
        for connection in teacher_model.get("vehicle_connections", []) or []
        if isinstance(connection, dict) and _is_turnaround_connection(connection)
    ]
    for connection in teacher_turnarounds:
        teacher_source = str(connection.get("from", ""))
        teacher_target = str(connection.get("to", ""))
        source = edge_map.get(teacher_source, "")
        target = edge_map.get(teacher_target, "")
        from_lane = str(connection.get("fromLane", "0"))
        to_lane = str(connection.get("toLane", "0"))
        reason = ""
        if not source or not target:
            reason = "unmapped_edge"
        elif source not in edges or target not in edges:
            reason = "mapped_edge_missing"
        elif edges[source].attrib.get("to") != junction_id or edges[target].attrib.get("from") != junction_id:
            reason = "mapped_edge_not_on_target_boundary"
        else:
            try:
                source_lane_exists = int(from_lane) < len(edges[source].findall("lane"))
                target_lane_exists = int(to_lane) < len(edges[target].findall("lane"))
            except ValueError:
                source_lane_exists = target_lane_exists = False
            if not source_lane_exists or not target_lane_exists:
                reason = "exact_lane_index_missing"
        teacher_source_classes = teacher_lane_classes(teacher_source, from_lane)
        teacher_target_classes = teacher_lane_classes(teacher_target, to_lane)
        candidate_source_classes = candidate_lane_classes(source, from_lane)
        candidate_target_classes = candidate_lane_classes(target, to_lane)
        mapped_signature = (source, target, from_lane, to_lane)
        observed_connection = observed_connections.get(mapped_signature)
        teacher_movement_classes = (
            connection_classes(
                teacher_source_classes,
                teacher_target_classes,
                connection,
            )
            if teacher_source_classes is not None and teacher_target_classes is not None
            else None
        )
        candidate_movement_classes = (
            connection_classes(
                candidate_source_classes,
                candidate_target_classes,
                dict(observed_connection.attrib) if observed_connection is not None else {},
            )
            if candidate_source_classes is not None and candidate_target_classes is not None
            else None
        )
        if not reason and (
            teacher_movement_classes is None
            or candidate_movement_classes is None
            or not candidate_movement_classes
            or not candidate_movement_classes <= teacher_movement_classes
        ):
            reason = "lane_vclass_mismatch"
        teacher_signature = {
            "from_edge_id": teacher_source,
            "to_edge_id": teacher_target,
            "from_lane": from_lane,
            "to_lane": to_lane,
        }
        if reason:
            unmapped.append(
                {
                    **teacher_signature,
                    "reason": reason,
                    "teacher_road_vclasses": sorted(teacher_movement_classes or ()),
                    "candidate_road_vclasses": sorted(candidate_movement_classes or ()),
                }
            )
            continue
        mapped_signatures.append(mapped_signature)
        authority.append(
            {
                "from_edge_id": source,
                "to_edge_id": target,
                "from_lane": from_lane,
                "to_lane": to_lane,
                "evidence_kind": "reference_teacher_movement",
                "evidence_ids": [
                    (f"{teacher_sha256}:{teacher_junction_id}:{teacher_source}:{from_lane}>{teacher_target}:{to_lane}")
                ],
                "teacher_signature": teacher_signature,
                "road_vclasses": sorted(teacher_movement_classes or ()),
            }
        )
    supported = sorted(signature for signature in mapped_signatures if signature in observed_signatures)
    return {
        "status": "pass" if not unmapped else "fail",
        "teacher_net_sha256": teacher_sha256,
        "teacher_junction_id": teacher_junction_id,
        "teacher_turnaround_signature_count": len(teacher_turnarounds),
        "mapped_exact_signature_count": len(authority),
        "unmapped_teacher_turnaround_signatures": unmapped,
        "candidate_supported_signature_count": len(supported),
        "candidate_supported_signatures": [
            {
                "from_edge_id": source,
                "to_edge_id": target,
                "from_lane": from_lane,
                "to_lane": to_lane,
            }
            for source, target, from_lane, to_lane in supported
        ],
        "authority_records": authority,
    }


def _compound_teacher_turnaround_evidence(
    *,
    teacher_model: dict[str, object],
    final_net_file: Path,
    junction_id: str,
    edge_map: dict[str, str],
    teacher_net_file: Path,
    teacher_junction_id: str,
    compound_junction_ids: Sequence[str],
    teacher_absent_junction_ids: Sequence[str] = (),
) -> dict[str, object]:
    main = _reference_teacher_turnaround_authority(
        teacher_model=teacher_model,
        final_net_file=final_net_file,
        junction_id=junction_id,
        edge_map=edge_map,
        teacher_net_file=teacher_net_file,
        teacher_junction_id=teacher_junction_id,
    )
    candidate_root = ET.parse(final_net_file).getroot()
    teacher_root = ET.parse(teacher_net_file).getroot()
    teacher_junction_ids = {
        row.attrib["id"]
        for row in teacher_root.findall("junction")
        if row.attrib.get("id") and not row.attrib["id"].startswith(":")
    }
    partition_map = {}
    for candidate_junction_id in compound_junction_ids:
        if candidate_junction_id == junction_id:
            partition_map[candidate_junction_id] = teacher_junction_id
            continue
        if candidate_junction_id in teacher_junction_ids:
            partition_map[candidate_junction_id] = candidate_junction_id
            continue
        candidate_members = set(_sumo_cluster_member_ids(candidate_junction_id))
        matches = [
            teacher_id
            for teacher_id in teacher_junction_ids
            if teacher_id.startswith("cluster_")
            and set(_sumo_cluster_member_ids(teacher_id))
            and (
                _canonical_sumo_cluster_id(teacher_id) == candidate_junction_id
                or set(_sumo_cluster_member_ids(teacher_id)) <= candidate_members
            )
        ]
        if len(matches) == 1:
            partition_map[candidate_junction_id] = matches[0]
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

    def lane_classes(
        edges: dict[str, ET.Element],
        edge_id: str,
        lane_index: str,
    ) -> set[str] | None:
        edge = edges.get(edge_id)
        if edge is None:
            return None
        lane = next(
            (item for item in edge.findall("lane") if item.attrib.get("index", "0") == lane_index),
            None,
        )
        return _sumo_allowed_classes(dict(lane.attrib)) if lane is not None else None

    teacher_connections = {
        (
            row.attrib.get("from", ""),
            row.attrib.get("to", ""),
            row.attrib.get("fromLane", "0"),
            row.attrib.get("toLane", "0"),
        ): row
        for row in teacher_root.findall("connection")
        if row.attrib.get("from", "") in teacher_edges and row.attrib.get("to", "") in teacher_edges
    }
    authority = list(main["authority_records"])
    authorized_signatures = {
        (
            str(row["from_edge_id"]),
            str(row["to_edge_id"]),
            str(row["from_lane"]),
            str(row["to_lane"]),
        )
        for row in authority
    }
    teacher_sha256 = hashlib.sha256(teacher_net_file.read_bytes()).hexdigest()
    scope = set(compound_junction_ids)
    teacher_absent_scope = {str(value) for value in teacher_absent_junction_ids if str(value)}
    negative_evidence = []
    unresolved = []
    for row in candidate_root.findall("connection"):
        if row.attrib.get("dir", "").lower() != TURNAROUND_DIR:
            continue
        source = row.attrib.get("from", "")
        target = row.attrib.get("to", "")
        source_edge = candidate_edges.get(source)
        candidate_owner = source_edge.attrib.get("to", "") if source_edge is not None else ""
        if source_edge is None or candidate_owner not in scope:
            continue
        signature = (
            source,
            target,
            row.attrib.get("fromLane", "0"),
            row.attrib.get("toLane", "0"),
        )
        if signature in authorized_signatures:
            continue
        teacher_connection = teacher_connections.get(signature)
        teacher_source_classes = lane_classes(teacher_edges, source, signature[2])
        teacher_target_classes = lane_classes(teacher_edges, target, signature[3])
        candidate_source_classes = lane_classes(candidate_edges, source, signature[2])
        candidate_target_classes = lane_classes(candidate_edges, target, signature[3])
        teacher_classes = (
            teacher_source_classes & teacher_target_classes & _sumo_allowed_classes(dict(teacher_connection.attrib))
            if teacher_connection is not None
            and teacher_source_classes is not None
            and teacher_target_classes is not None
            else None
        )
        candidate_classes = (
            candidate_source_classes & candidate_target_classes & _sumo_allowed_classes(dict(row.attrib))
            if candidate_source_classes is not None and candidate_target_classes is not None
            else None
        )
        record = {
            "from_edge_id": source,
            "to_edge_id": target,
            "from_lane": signature[2],
            "to_lane": signature[3],
            "candidate_junction_id": candidate_owner,
            "teacher_junction_id": partition_map.get(candidate_owner, ""),
            "teacher_net_sha256": teacher_sha256,
        }
        if (
            teacher_connection is not None
            and teacher_connection.attrib.get("dir", "").lower() == TURNAROUND_DIR
            and candidate_classes
            and teacher_classes is not None
            and candidate_classes <= teacher_classes
        ):
            authority.append(
                {
                    "from_edge_id": source,
                    "to_edge_id": target,
                    "from_lane": signature[2],
                    "to_lane": signature[3],
                    "evidence_kind": "reference_teacher_movement",
                    "evidence_ids": [f"{teacher_sha256}:{teacher_edges[source].attrib.get('to', '')}"],
                }
            )
            authorized_signatures.add(signature)
        elif teacher_connection is None and (
            candidate_owner in partition_map or candidate_owner in teacher_absent_scope
        ):
            negative_evidence.append(
                {
                    **record,
                    "evidence_kind": (
                        "reference_teacher_partition_turnaround_absence"
                        if candidate_owner in partition_map
                        else "same_bbox_reference_partition_and_turnaround_absence"
                    ),
                    "teacher_edge_lane_identity": (
                        "exact"
                        if teacher_source_classes is not None and teacher_target_classes is not None
                        else "partition_mapped"
                    ),
                }
            )
        else:
            unresolved.append(
                {
                    **record,
                    "reason": (
                        "teacher_direction_or_vclass_mismatch"
                        if teacher_connection is not None
                        else "teacher_partition_unresolved"
                    ),
                }
            )
    return {
        **main,
        "status": ("pass" if main.get("status") == "pass" and not unresolved else "review"),
        "compound_junction_ids": sorted(scope),
        "teacher_partition_map": dict(sorted(partition_map.items())),
        "authority_records": authority,
        "negative_movement_evidence": negative_evidence,
        "unresolved_candidate_turnaround_count": len(unresolved),
        "unresolved_candidate_turnarounds": unresolved,
    }


def _write_teacher_absent_tls_node_overlay(
    output_file: Path,
    *,
    candidate_net_file: Path,
    teacher_net_file: Path,
    teacher_partition_map: Mapping[str, str],
    teacher_absent_junction_ids: Sequence[str] = (),
) -> dict[str, object]:
    candidate_root = ET.parse(candidate_net_file).getroot()
    teacher_root = ET.parse(teacher_net_file).getroot()
    candidate_junctions = {
        row.attrib["id"]: row
        for row in candidate_root.findall("junction")
        if row.attrib.get("id") and not row.attrib["id"].startswith(":")
    }
    teacher_junctions = {
        row.attrib["id"]: row
        for row in teacher_root.findall("junction")
        if row.attrib.get("id") and not row.attrib["id"].startswith(":")
    }
    teacher_tls_ids = {row.attrib.get("id", "") for row in teacher_root.findall("tlLogic")} | {
        row.attrib.get("tl", "") for row in teacher_root.findall("connection") if row.attrib.get("tl")
    }
    root = ET.Element("nodes")
    demotions = []
    for candidate_id, teacher_id in sorted(teacher_partition_map.items()):
        candidate = candidate_junctions.get(candidate_id)
        teacher = teacher_junctions.get(teacher_id)
        if (
            candidate is None
            or teacher is None
            or candidate.attrib.get("type") != "traffic_light"
            or teacher.attrib.get("type") == "traffic_light"
            or teacher_id in teacher_tls_ids
        ):
            continue
        teacher_type = teacher.attrib.get("type", "priority")
        ET.SubElement(
            root,
            "node",
            {"id": candidate_id, "type": teacher_type},
        )
        demotions.append(
            {
                "candidate_junction_id": candidate_id,
                "teacher_junction_id": teacher_id,
                "candidate_type_before": "traffic_light",
                "teacher_type": teacher_type,
                "evidence_kind": "resolved_reference_partition_non_tls",
            }
        )
    already_demoted = {str(row["candidate_junction_id"]) for row in demotions}
    for candidate_id in sorted({str(value) for value in teacher_absent_junction_ids if str(value)} - already_demoted):
        candidate = candidate_junctions.get(candidate_id)
        if (
            candidate is None
            or candidate_id in teacher_junctions
            or not candidate.attrib.get("type", "").startswith("traffic_light")
        ):
            continue
        ET.SubElement(root, "node", {"id": candidate_id, "type": "priority"})
        demotions.append(
            {
                "candidate_junction_id": candidate_id,
                "teacher_junction_id": "",
                "candidate_type_before": candidate.attrib.get("type", ""),
                "teacher_type": "priority",
                "evidence_kind": "same_bbox_reference_partition_absence",
            }
        )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "policy": (
            "retire only a compound road-segment TLS whose resolved same-bbox "
            "teacher partition has no TLS, or an explicitly identified shared-"
            "controller fringe absent from every same-bbox teacher partition"
        ),
        "candidate_net_sha256": hashlib.sha256(candidate_net_file.read_bytes()).hexdigest(),
        "teacher_net_sha256": hashlib.sha256(teacher_net_file.read_bytes()).hexdigest(),
        "overlay_file": str(output_file.resolve()),
        "overlay_sha256": hashlib.sha256(output_file.read_bytes()).hexdigest(),
        "demoted_tls_junction_count": len(demotions),
        "demoted_tls_junctions": demotions,
    }


def _write_unsupported_turnaround_delete_overlay(
    output_file: Path,
    audit: dict[str, Any],
    *,
    negative_teacher_evidence: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    negatively_proven = {
        (
            str(row.get("from_edge_id", "")),
            str(row.get("to_edge_id", "")),
            str(row.get("from_lane", "")),
            str(row.get("to_lane", "")),
        )
        for row in negative_teacher_evidence
    }
    unsupported = [
        row
        for row in audit.get("dir_t_turnarounds", []) or []
        if isinstance(row, dict)
        and row.get("audit_disposition") == "review_required_unsupported_turnaround"
        and (
            str(row.get("from_edge_id", "")),
            str(row.get("to_edge_id", "")),
            str(row.get("from_lane", "")),
            str(row.get("to_lane", "")),
        )
        in negatively_proven
    ]
    root = ET.Element("connections")
    for row in unsupported:
        ET.SubElement(
            root,
            "delete",
            {
                "from": str(row["from_edge_id"]),
                "to": str(row["to_edge_id"]),
                "fromLane": str(row["from_lane"]),
                "toLane": str(row["to_lane"]),
            },
        )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "policy": (
            "delete only compiled dir='t' movements proven absent from the "
            "same-bbox reference teacher at the exact edge/lane signature"
        ),
        "seed_net_file": str(audit.get("source_net_file", "")),
        "seed_net_sha256": str(audit.get("source_net_sha256", "")),
        "overlay_file": str(output_file.resolve()),
        "overlay_sha256": hashlib.sha256(output_file.read_bytes()).hexdigest(),
        "deleted_connection_count": len(unsupported),
        "negative_teacher_evidence_count": len(negative_teacher_evidence),
        "negative_teacher_evidence": list(negative_teacher_evidence),
        "deleted_connections": [
            {
                "from_edge_id": str(row["from_edge_id"]),
                "to_edge_id": str(row["to_edge_id"]),
                "from_lane": str(row["from_lane"]),
                "to_lane": str(row["to_lane"]),
                "owner_junction_id": str(row.get("owner_junction_id", "")),
            }
            for row in unsupported
        ],
    }


def _short_internal_lane_gate(
    net_file: Path,
    junction_ids: Sequence[str],
    *,
    minimum_length_m: float = 0.5,
) -> dict[str, object]:
    root = ET.parse(net_file).getroot()
    traffic_light_junction_ids = {
        junction.attrib["id"]
        for junction in root.findall("junction")
        if junction.attrib.get("id") and junction.attrib.get("type", "").startswith("traffic_light")
    } | {logic.attrib["id"] for logic in root.findall("tlLogic") if logic.attrib.get("id")}
    connections = root.findall("connection")
    rows = []
    for junction_id in junction_ids:
        prefix = f":{junction_id}_"
        for edge in root.findall("edge"):
            if not edge.attrib.get("id", "").startswith(prefix):
                continue
            for lane in edge.findall("lane"):
                if not (_sumo_allowed_classes(dict(lane.attrib)) & (ROAD_MOTORIZED_CLASSES | {"bicycle"})):
                    continue
                try:
                    declared_length = float(lane.attrib.get("length", "nan"))
                except ValueError:
                    declared_length = math.nan
                rendered_length = _polyline_length(lane.attrib.get("shape", ""))
                measurements = [
                    value
                    for value in (declared_length, rendered_length)
                    if value is not None and math.isfinite(value) and value > 0
                ]
                if not measurements or min(measurements) >= minimum_length_m:
                    continue
                edge_id = edge.attrib.get("id", "")
                lane_id = lane.attrib.get("id", "")
                chained_internal_segment = any(
                    (connection.attrib.get("from") == edge_id and connection.attrib.get("via", "").startswith(prefix))
                    or (
                        connection.attrib.get("via") == lane_id and connection.attrib.get("from", "").startswith(prefix)
                    )
                    for connection in connections
                )
                rows.append(
                    {
                        "junction_id": junction_id,
                        "edge_id": edge_id,
                        "lane_id": lane_id,
                        "declared_length_m": (declared_length if math.isfinite(declared_length) else None),
                        "rendered_length_m": rendered_length,
                        "chained_internal_segment": chained_internal_segment,
                        "blocking_compound_tls_fragment": (
                            junction_id in traffic_light_junction_ids and not chained_internal_segment
                        ),
                    }
                )
    blocking_rows = [row for row in rows if row["blocking_compound_tls_fragment"]]
    return {
        "status": "pass" if not blocking_rows else "fail",
        "policy": (
            "standalone sub-0.5m internal bicycle/motorized movements block "
            "automatic promotion inside a compound traffic-light fragment; "
            "short pieces of a longer SUMO internal chain and non-TLS fused "
            "turns remain diagnostic"
        ),
        "junction_ids": list(junction_ids),
        "minimum_internal_vehicle_lane_length_m": minimum_length_m,
        "short_internal_vehicle_lane_count": len(rows),
        "short_internal_vehicle_lanes": rows,
        "blocking_compound_tls_short_lane_count": len(blocking_rows),
        "blocking_compound_tls_short_lanes": blocking_rows,
    }


def _boundary_vehicle_connectivity(net_file: Path, junction_id: str) -> dict[str, object]:
    root = ET.parse(net_file).getroot()
    edges = {
        edge.attrib["id"]: edge
        for edge in root.findall("edge")
        if edge.attrib.get("id") and not edge.attrib.get("function") and not edge.attrib["id"].startswith(":")
    }

    def allowed_vehicle_classes(lane: ET.Element) -> set[str]:
        return _sumo_allowed_classes(dict(lane.attrib)) & ROAD_MOTORIZED_CLASSES

    lanes_by_id = {
        lane.attrib["id"]: lane
        for edge in root.findall("edge")
        for lane in edge.findall("lane")
        if lane.attrib.get("id")
    }
    incoming = {
        (edge_id, str(index)): allowed_vehicle_classes(lane)
        for edge_id, edge in edges.items()
        if edge.attrib.get("to") == junction_id
        for index, lane in enumerate(edge.findall("lane"))
        if allowed_vehicle_classes(lane)
    }
    outgoing = {
        (edge_id, str(index)): allowed_vehicle_classes(lane)
        for edge_id, edge in edges.items()
        if edge.attrib.get("from") == junction_id
        for index, lane in enumerate(edge.findall("lane"))
        if allowed_vehicle_classes(lane)
    }
    connected_incoming: dict[tuple[str, str], set[str]] = {key: set() for key in incoming}
    connected_outgoing: dict[tuple[str, str], set[str]] = {key: set() for key in outgoing}
    class_disjoint: list[dict[str, str]] = []
    for connection in root.findall("connection"):
        source_id = connection.attrib.get("from", "")
        target_id = connection.attrib.get("to", "")
        source_lane = connection.attrib.get("fromLane", "0")
        target_lane = connection.attrib.get("toLane", "0")
        source_key = (source_id, source_lane)
        target_key = (target_id, target_lane)
        if source_key not in incoming or target_key not in outgoing:
            continue
        shared_classes = incoming[source_key] & outgoing[target_key]
        shared_classes &= _sumo_allowed_classes(dict(connection.attrib))
        via_lane_id = connection.attrib.get("via", "")
        if via_lane_id:
            via_lane = lanes_by_id.get(via_lane_id)
            shared_classes &= allowed_vehicle_classes(via_lane) if via_lane is not None else set()
        if not shared_classes:
            class_disjoint.append(
                {
                    "from_edge_id": source_id,
                    "to_edge_id": target_id,
                    "from_lane": source_lane,
                    "to_lane": target_lane,
                }
            )
            continue
        connected_incoming[source_key].update(shared_classes)
        connected_outgoing[target_key].update(shared_classes)
    missing_incoming_classes = {
        key: sorted(classes - connected_incoming[key])
        for key, classes in incoming.items()
        if classes - connected_incoming[key]
    }
    missing_outgoing_classes = {
        key: sorted(classes - connected_outgoing[key])
        for key, classes in outgoing.items()
        if classes - connected_outgoing[key]
    }
    missing_incoming = sorted(missing_incoming_classes)
    missing_outgoing = sorted(missing_outgoing_classes)
    passenger_incoming = {key for key, classes in incoming.items() if "passenger" in classes}
    passenger_outgoing = {key for key, classes in outgoing.items() if "passenger" in classes}
    missing_passenger_incoming = sorted(key for key in passenger_incoming if "passenger" not in connected_incoming[key])
    missing_passenger_outgoing = sorted(key for key in passenger_outgoing if "passenger" not in connected_outgoing[key])
    passenger_status = (
        "not_applicable"
        if not passenger_incoming and not passenger_outgoing
        else "pass"
        if not missing_passenger_incoming and not missing_passenger_outgoing
        else "fail"
    )
    status = (
        "pass"
        if not missing_incoming and not missing_outgoing and not class_disjoint and passenger_status != "fail"
        else "fail"
    )

    def lane_ids(rows: list[tuple[str, str]]) -> list[str]:
        return [f"{edge_id}_{lane}" for edge_id, lane in rows]

    def class_gaps(rows: dict[tuple[str, str], list[str]]) -> dict[str, list[str]]:
        return {f"{edge_id}_{lane}": classes for (edge_id, lane), classes in sorted(rows.items())}

    return {
        "status": status,
        "incoming_vehicle_lane_count": len(incoming),
        "outgoing_vehicle_lane_count": len(outgoing),
        "connected_incoming_vehicle_lane_count": len(incoming) - len(missing_incoming),
        "connected_outgoing_vehicle_lane_count": len(outgoing) - len(missing_outgoing),
        "unconnected_incoming_vehicle_lane_ids": lane_ids(missing_incoming),
        "unconnected_outgoing_vehicle_lane_ids": lane_ids(missing_outgoing),
        "unconnected_incoming_vclasses_by_lane": class_gaps(missing_incoming_classes),
        "unconnected_outgoing_vclasses_by_lane": class_gaps(missing_outgoing_classes),
        "class_disjoint_connection_signatures": class_disjoint,
        "passenger_connectivity_status": passenger_status,
        "unconnected_passenger_incoming_lane_ids": lane_ids(missing_passenger_incoming),
        "unconnected_passenger_outgoing_lane_ids": lane_ids(missing_passenger_outgoing),
    }


def _lane_surface_overlap_touches_junctions(overlap: dict[str, Any], junction_ids: set[str]) -> bool:
    return bool(
        junction_ids
        & {
            str(overlap.get("from_junction_id", "")),
            str(overlap.get("to_junction_id", "")),
            str(overlap.get("non_owner_junction_id", "")),
        }
    )


def _target_surface_overlap_gate(
    report: dict[str, Any],
    junction_id: str,
    *,
    report_file: Path,
    expected_net_file: Path,
    baseline_report: dict[str, Any] | None = None,
    baseline_report_file: Path | None = None,
    baseline_expected_net_file: Path | None = None,
    reference_report: dict[str, Any] | None = None,
    reference_report_file: Path | None = None,
    reference_expected_net_file: Path | None = None,
    lane_edge_aliases: dict[str, str] | None = None,
    allow_non_motorized_lane_overlaps: bool = False,
) -> dict[str, object]:
    report_identity, audited_report = _surface_report_identity(
        report,
        report_file,
        expected_net_file,
    )
    non_area_exclusions = [
        item
        for item in audited_report.get("non_area_junction_exclusions", []) or []
        if isinstance(item, dict) and item.get("junction_id") == junction_id
    ]
    geometry_errors = [
        item
        for item in audited_report.get("geometry_errors", []) or []
        if isinstance(item, dict)
        and junction_id
        in {
            item.get("junction_id", ""),
            item.get("from_junction_id", ""),
            item.get("to_junction_id", ""),
        }
    ]
    junction_overlaps = [
        item
        for item in audited_report.get("junction_junction_overlaps", []) or []
        if isinstance(item, dict)
        and junction_id
        in {
            item.get("first_junction_id", ""),
            item.get("second_junction_id", ""),
        }
    ]
    lane_overlap_candidates = [
        item
        for item in audited_report.get("external_lane_non_owner_junction_overlaps", []) or []
        if isinstance(item, dict)
        and (
            item.get("non_owner_junction_id") == junction_id
            or junction_id
            in {
                item.get("from_junction_id", ""),
                item.get("to_junction_id", ""),
            }
        )
    ]
    lane_classes_by_id: dict[str, set[str]] = {}
    if allow_non_motorized_lane_overlaps:
        try:
            expected_root = ET.parse(expected_net_file).getroot()
        except (ET.ParseError, OSError):
            expected_root = None
        if expected_root is not None:
            for edge in expected_root.findall("edge"):
                for lane in edge.findall("lane"):
                    lane_id = str(lane.attrib.get("id", ""))
                    if lane_id:
                        lane_classes_by_id[lane_id] = _sumo_allowed_classes({**edge.attrib, **lane.attrib})

    def is_authorized_non_motorized_overlap(item: dict[str, Any]) -> bool:
        if not allow_non_motorized_lane_overlaps:
            return False
        classes = lane_classes_by_id.get(str(item.get("lane_id", "")), set())
        return bool(classes) and not classes & ROAD_MOTORIZED_CLASSES and classes <= {"bicycle", "pedestrian"}

    authorized_non_motorized_overlaps = [
        item for item in lane_overlap_candidates if is_authorized_non_motorized_overlap(item)
    ]
    authorized_non_motorized_overlap_keys = {
        (
            str(item.get("lane_id", "")),
            str(item.get("non_owner_junction_id", "")),
            str(item.get("from_junction_id", "")),
            str(item.get("to_junction_id", "")),
        )
        for item in authorized_non_motorized_overlaps
    }
    lane_non_owner_overlaps = [
        item
        for item in lane_overlap_candidates
        if item.get("non_owner_junction_id") == junction_id
        and (
            str(item.get("lane_id", "")),
            str(item.get("non_owner_junction_id", "")),
            str(item.get("from_junction_id", "")),
            str(item.get("to_junction_id", "")),
        )
        not in authorized_non_motorized_overlap_keys
    ]
    lane_target_owner_overlaps = [
        item
        for item in lane_overlap_candidates
        if junction_id
        in {
            item.get("from_junction_id", ""),
            item.get("to_junction_id", ""),
        }
        and (
            str(item.get("lane_id", "")),
            str(item.get("non_owner_junction_id", "")),
            str(item.get("from_junction_id", "")),
            str(item.get("to_junction_id", "")),
        )
        not in authorized_non_motorized_overlap_keys
    ]
    if baseline_report is not None and baseline_report_file is not None and baseline_expected_net_file is not None:
        baseline_identity, audited_baseline_report = _surface_report_identity(
            baseline_report,
            baseline_report_file,
            baseline_expected_net_file,
        )
    else:
        baseline_identity = {"status": "not_required", "failures": []}
        audited_baseline_report = {}
    baseline_valid = baseline_identity.get("status") == "pass"
    if reference_report is not None and reference_report_file is not None and reference_expected_net_file is not None:
        reference_identity, audited_reference_report = _surface_report_identity(
            reference_report,
            reference_report_file,
            reference_expected_net_file,
        )
    else:
        reference_identity = {"status": "not_required", "failures": []}
        audited_reference_report = {}
    reference_valid = reference_identity.get("status") == "pass"
    lane_edge_aliases = lane_edge_aliases or {}

    def normalized_lane_id(lane_id: object) -> str:
        value = str(lane_id or "")
        for source_edge_id, target_edge_id in sorted(
            lane_edge_aliases.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if value.startswith(f"{source_edge_id}_"):
                return f"{target_edge_id}{value[len(source_edge_id) :]}"
        return value

    baseline_owner_overlap_areas: dict[tuple[str, str], float] = {}
    baseline_junction_overlap_areas: dict[tuple[str, str], float] = {}
    reference_junction_overlap_areas: dict[tuple[str, str], float] = {}
    if baseline_valid:
        for item in audited_baseline_report.get("junction_junction_overlaps", []) or []:
            if not isinstance(item, dict):
                continue
            key = tuple(
                sorted(
                    (
                        str(item.get("first_junction_id", "")),
                        str(item.get("second_junction_id", "")),
                    )
                )
            )
            if not all(key):
                continue
            try:
                area = float(item.get("overlap_area_m2", 0) or 0)
            except (TypeError, ValueError):
                continue
            baseline_junction_overlap_areas[key] = max(area, baseline_junction_overlap_areas.get(key, 0.0))
        for item in audited_baseline_report.get("external_lane_non_owner_junction_overlaps", []) or []:
            if not isinstance(item, dict):
                continue
            key = (
                normalized_lane_id(item.get("lane_id", "")),
                str(item.get("non_owner_junction_id", "")),
            )
            if not all(key):
                continue
            try:
                area = float(item.get("overlap_area_m2", 0) or 0)
            except (TypeError, ValueError):
                continue
            baseline_owner_overlap_areas[key] = max(
                area,
                baseline_owner_overlap_areas.get(key, 0.0),
            )
    if reference_valid:
        for item in audited_reference_report.get("junction_junction_overlaps", []) or []:
            if not isinstance(item, dict):
                continue
            key = tuple(
                sorted(
                    (
                        str(item.get("first_junction_id", "")),
                        str(item.get("second_junction_id", "")),
                    )
                )
            )
            if not all(key):
                continue
            try:
                area = float(item.get("overlap_area_m2", 0) or 0)
            except (TypeError, ValueError):
                continue
            reference_junction_overlap_areas[key] = max(
                area,
                reference_junction_overlap_areas.get(key, 0.0),
            )
    inherited_junction_overlaps = []
    reference_authorized_junction_overlaps = []
    regressed_junction_overlaps = []
    for item in junction_overlaps:
        key = tuple(
            sorted(
                (
                    str(item.get("first_junction_id", "")),
                    str(item.get("second_junction_id", "")),
                )
            )
        )
        try:
            final_area = float(item.get("overlap_area_m2", 0) or 0)
        except (TypeError, ValueError):
            final_area = math.inf
        baseline_area = baseline_junction_overlap_areas.get(key)
        reference_area = reference_junction_overlap_areas.get(key)
        record = {
            **item,
            "baseline_overlap_area_m2": baseline_area,
            "reference_overlap_area_m2": reference_area,
            "overlap_area_delta_m2": (
                round(final_area - baseline_area, 6)
                if baseline_area is not None and math.isfinite(final_area)
                else None
            ),
        }
        if baseline_area is not None and final_area <= baseline_area + 1e-4:
            inherited_junction_overlaps.append(record)
        elif reference_area is not None and final_area <= reference_area + 1e-4:
            reference_authorized_junction_overlaps.append(record)
        else:
            regressed_junction_overlaps.append(record)

    def classify_overlap_regressions(
        overlaps: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        inherited = []
        regressed = []
        for item in overlaps:
            key = (
                normalized_lane_id(item.get("lane_id", "")),
                str(item.get("non_owner_junction_id", "")),
            )
            try:
                final_area = float(item.get("overlap_area_m2", 0) or 0)
            except (TypeError, ValueError):
                final_area = math.inf
            baseline_area = baseline_owner_overlap_areas.get(key)
            record = {
                **item,
                "baseline_overlap_area_m2": baseline_area,
                "overlap_area_delta_m2": (
                    round(final_area - baseline_area, 6)
                    if baseline_area is not None and math.isfinite(final_area)
                    else None
                ),
            }
            if baseline_valid and baseline_area is not None and final_area <= baseline_area + 1e-4:
                inherited.append(record)
            else:
                regressed.append(record)
        return inherited, regressed

    (
        inherited_lane_non_owner_overlaps,
        regressed_lane_non_owner_overlaps,
    ) = classify_overlap_regressions(lane_non_owner_overlaps)
    (
        inherited_lane_target_owner_overlaps,
        regressed_lane_target_owner_overlaps,
    ) = classify_overlap_regressions(lane_target_owner_overlaps)
    blocked = bool(
        report_identity.get("status") != "pass"
        or non_area_exclusions
        or geometry_errors
        or regressed_junction_overlaps
        or regressed_lane_non_owner_overlaps
        or regressed_lane_target_owner_overlaps
    )
    return {
        "status": "fail" if blocked else "pass",
        "junction_id": junction_id,
        "report_file": str(report_file),
        "source_net_sha256": str(audited_report.get("source_sha256", "")),
        "report_identity": report_identity,
        "non_area_exclusion_count": len(non_area_exclusions),
        "non_area_exclusions": non_area_exclusions,
        "geometry_error_count": len(geometry_errors),
        "geometry_errors": geometry_errors,
        "junction_overlap_count": len(junction_overlaps),
        "junction_overlaps": junction_overlaps,
        "junction_overlap_regression_count": len(regressed_junction_overlaps),
        "junction_overlap_regressions": regressed_junction_overlaps,
        "junction_overlap_inherited_count": len(inherited_junction_overlaps),
        "junction_overlap_inherited": inherited_junction_overlaps,
        "junction_overlap_reference_authorized_count": len(reference_authorized_junction_overlaps),
        "junction_overlap_reference_authorized": reference_authorized_junction_overlaps,
        "authorized_non_motorized_overlap_count": len(authorized_non_motorized_overlap_keys),
        "authorized_non_motorized_overlaps": authorized_non_motorized_overlaps,
        "lane_non_owner_overlap_count": len(lane_non_owner_overlaps),
        "lane_non_owner_overlaps": lane_non_owner_overlaps,
        "lane_non_owner_regression_count": len(regressed_lane_non_owner_overlaps),
        "lane_non_owner_regressions": regressed_lane_non_owner_overlaps,
        "lane_non_owner_inherited_count": len(inherited_lane_non_owner_overlaps),
        "lane_non_owner_inherited": inherited_lane_non_owner_overlaps,
        "lane_target_owner_overlap_count": len(lane_target_owner_overlaps),
        "lane_target_owner_regression_count": len(regressed_lane_target_owner_overlaps),
        "lane_target_owner_regressions": regressed_lane_target_owner_overlaps,
        "lane_target_owner_inherited_count": len(inherited_lane_target_owner_overlaps),
        "lane_target_owner_inherited": inherited_lane_target_owner_overlaps,
        "baseline_report_file": (str(baseline_report_file) if baseline_report_file is not None else ""),
        "baseline_source_net_sha256": str(audited_baseline_report.get("source_sha256", "")),
        "baseline_audit_status": (str(audited_baseline_report.get("status", "not_required"))),
        "baseline_audit_valid": baseline_valid,
        "baseline_report_identity": baseline_identity,
        "reference_report_file": (str(reference_report_file) if reference_report_file is not None else ""),
        "reference_source_net_sha256": str(audited_reference_report.get("source_sha256", "")),
        "reference_audit_status": str(audited_reference_report.get("status", "not_required")),
        "reference_audit_valid": reference_valid,
        "reference_report_identity": reference_identity,
        "audit_error": str(audited_report.get("error", "")),
    }


def _surface_report_identity(
    report: dict[str, Any],
    report_file: Path,
    expected_net_file: Path,
) -> tuple[dict[str, object], dict[str, Any]]:
    failures = []
    declared_report_file = str(report.get("report_file", ""))
    expected_report_sha256 = str(report.get("report_sha256", ""))
    resolved_report_file = report_file.resolve()
    expected_source_file = expected_net_file.resolve()
    audited_report: dict[str, Any] = {}
    if not declared_report_file or Path(declared_report_file).resolve() != resolved_report_file:
        failures.append("report_file_identity_mismatch")
    if not resolved_report_file.is_file():
        failures.append("report_file_missing")
    else:
        report_bytes = resolved_report_file.read_bytes()
        if not expected_report_sha256 or hashlib.sha256(report_bytes).hexdigest() != expected_report_sha256:
            failures.append("report_sha256_mismatch")
        try:
            parsed = json.loads(report_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            failures.append("report_json_invalid")
        else:
            if isinstance(parsed, dict):
                audited_report = parsed
            else:
                failures.append("report_payload_not_object")
    declared_source_file = str(audited_report.get("source_net_file", ""))
    expected_source_sha256 = str(audited_report.get("source_sha256", ""))
    source_file = Path(declared_source_file).resolve() if declared_source_file else None
    if audited_report.get("schema") != SURFACE_OVERLAP_AUDIT_SCHEMA:
        failures.append("schema_mismatch")
    if audited_report.get("error"):
        failures.append("audit_error")
    if audited_report.get("source_network_mutation") is not False:
        failures.append("source_network_mutation_not_false")
    if source_file != expected_source_file:
        failures.append("source_net_file_identity_mismatch")
    if source_file is None or not source_file.is_file():
        failures.append("source_net_file_missing")
    elif not expected_source_sha256 or hashlib.sha256(source_file.read_bytes()).hexdigest() != expected_source_sha256:
        failures.append("source_net_sha256_mismatch")
    return (
        {
            "status": "fail" if failures else "pass",
            "failures": sorted(set(failures)),
            "report_file": str(resolved_report_file),
            "source_net_file": str(source_file) if source_file is not None else "",
            "expected_source_net_file": str(expected_source_file),
        },
        audited_report,
    )


def _blocking_sequential_overlap_edge_ids(
    edge_ids: set[str],
    edge_file: Path,
    candidate_node_ids: set[str],
    applied_node_ids: set[str],
) -> list[str]:
    if not edge_ids:
        return []
    try:
        edges = {
            edge.attrib["id"]: edge for edge in ET.parse(edge_file).getroot().findall("edge") if edge.attrib.get("id")
        }
    except (ET.ParseError, OSError):
        return sorted(edge_ids)
    blocking = []
    for edge_id in sorted(edge_ids):
        edge = edges.get(edge_id)
        if edge is None:
            blocking.append(edge_id)
            continue
        endpoints = {edge.attrib.get("from", ""), edge.attrib.get("to", "")}
        if endpoints & candidate_node_ids and endpoints & applied_node_ids:
            continue
        blocking.append(edge_id)
    return blocking


def _plain_node_ids(node_file: Path) -> set[str]:
    try:
        return {node.attrib["id"] for node in ET.parse(node_file).getroot().findall("node") if node.attrib.get("id")}
    except (ET.ParseError, OSError):
        return set()


def _write_candidate_aligned_plain_geometry(
    *,
    node_file: Path,
    edge_file: Path,
    candidate_net_file: Path,
    output_node_file: Path,
    output_edge_file: Path,
) -> tuple[Path, Path, dict[str, object]]:
    try:
        node_tree = ET.parse(node_file)
        edge_tree = ET.parse(edge_file)
        candidate_root = ET.parse(candidate_net_file).getroot()
    except (ET.ParseError, OSError):
        return node_file, edge_file, {"status": "fail", "reason": "coordinate_alignment_parse_failed"}
    candidate_junctions = {
        junction.attrib["id"]: junction
        for junction in candidate_root.findall("junction")
        if junction.attrib.get("id") and not junction.attrib["id"].startswith(":")
    }
    repaired_node_ids = set()
    for node in node_tree.getroot().findall("node"):
        candidate_junction = candidate_junctions.get(node.attrib.get("id", ""))
        if candidate_junction is None:
            continue
        changed = False
        for attr in ("x", "y", "z"):
            value = candidate_junction.attrib.get(attr)
            if value is not None and node.attrib.get(attr) != value:
                node.set(attr, value)
                changed = True
        if changed:
            repaired_node_ids.add(node.attrib.get("id", ""))
    candidate_edges = {
        edge.attrib["id"]: edge for edge in candidate_root.findall("edge") if edge.attrib.get("id")
    }
    repaired_edge_count = 0
    for edge in edge_tree.getroot().findall("edge"):
        if not repaired_node_ids.intersection((edge.attrib.get("from", ""), edge.attrib.get("to", ""))):
            continue
        candidate_edge = candidate_edges.get(edge.attrib.get("id", ""))
        if candidate_edge is None:
            continue
        changed = False
        candidate_shape = _primary_edge_shape(candidate_edge)
        if candidate_shape and edge.attrib.get("shape") != candidate_shape:
            edge.set("shape", candidate_shape)
            changed = True
        candidate_lanes = {
            lane.attrib.get("index", ""): lane
            for lane in candidate_edge.findall("lane")
            if lane.attrib.get("index") is not None
        }
        for lane in edge.findall("lane"):
            candidate_lane = candidate_lanes.get(lane.attrib.get("index", ""))
            candidate_lane_shape = candidate_lane.attrib.get("shape", "") if candidate_lane is not None else ""
            if candidate_lane_shape and lane.attrib.get("shape") != candidate_lane_shape:
                lane.set("shape", candidate_lane_shape)
                changed = True
        repaired_edge_count += int(changed)
    output_node_file.parent.mkdir(parents=True, exist_ok=True)
    output_edge_file.parent.mkdir(parents=True, exist_ok=True)
    node_tree.write(output_node_file, encoding="utf-8", xml_declaration=True)
    edge_tree.write(output_edge_file, encoding="utf-8", xml_declaration=True)
    return output_node_file, output_edge_file, {
        "status": "pass",
        "repaired_node_count": len(repaired_node_ids),
        "repaired_node_ids": sorted(repaired_node_ids),
        "repaired_edge_count": repaired_edge_count,
        "node_file": str(output_node_file),
        "edge_file": str(output_edge_file),
    }


def _join_internal_self_loop_drop_has_witness(
    edge_id: str,
    dropped_edge_ids: list[str],
    surviving_edge_ids: set[str],
) -> bool:
    if _opposite_direction_edge_id(edge_id) in set(dropped_edge_ids):
        return True
    edge_family = _edge_family_id(edge_id)
    return any(_edge_family_id(surviving_edge_id) == edge_family for surviving_edge_id in surviving_edge_ids)


def _teacher_boundary_edge_has_target_junction(teacher_net_file: Path, teacher_junction_id: str, edge_id: str) -> bool:
    try:
        edge = ET.parse(teacher_net_file).getroot().find(f"edge[@id='{edge_id}']")
    except (ET.ParseError, OSError):
        return False
    return edge is not None and teacher_junction_id in (edge.attrib.get("from"), edge.attrib.get("to"))


def _opposite_direction_edge_id(edge_id: str) -> str:
    return edge_id[1:] if edge_id.startswith("-") else f"-{edge_id}"


def _edge_family_id(edge_id: str) -> str:
    return edge_id.lstrip("-").split("#", 1)[0]


def _signed_edge_family_id(edge_id: str) -> str:
    return edge_id.split("#", 1)[0]


def _edge_drop_requires_review(edge: ET.Element) -> bool:
    edge_id = edge.attrib.get("id", "")
    if edge_id.startswith(":") or edge.attrib.get("function") in {"internal", "crossing", "walkingarea"}:
        return False
    if edge.attrib.get("type", "").startswith("highway."):
        return True
    vehicle_classes = {
        "passenger",
        "private",
        "bus",
        "coach",
        "truck",
        "trailer",
        "motorcycle",
        "moped",
        "taxi",
        "delivery",
        "emergency",
    }
    for lane in edge.findall("lane"):
        if set(lane.attrib.get("allow", "").split()) & vehicle_classes:
            return True
    return False


def _normalize_joined_junction_ids(value: object) -> set[str]:
    if isinstance(value, (list, tuple, set, frozenset)):
        return {str(item) for item in value if str(item)}
    return {str(value)} if str(value) else set()


def _join_patch_endpoint_rewrites(join_patch_file: Path) -> dict[str, str]:
    try:
        joins = ET.parse(join_patch_file).getroot().findall("join")
    except (ET.ParseError, OSError):
        return {}
    rewrites: dict[str, str] = {}
    for join in joins:
        node_ids = sorted({node_id for node_id in join.attrib.get("nodes", "").split() if node_id})
        joined_id = _sumo_joined_cluster_id(node_ids)
        if len(node_ids) < 2 or not joined_id:
            continue
        for node_id in node_ids:
            rewrites[node_id] = joined_id
        full_joined_id = f"cluster_{'_'.join(node_ids)}"
        if full_joined_id != joined_id:
            rewrites[full_joined_id] = joined_id
    return rewrites


def _selected_join_endpoint_rewrites(node_file: Path, junction_id: object) -> dict[str, str]:
    target_junction_ids = _normalize_joined_junction_ids(junction_id)
    return {
        node_id: joined_id
        for node_id, joined_id in _join_patch_endpoint_rewrites(node_file).items()
        if joined_id in target_junction_ids
    }


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


def _endpoint_rewrites(approach_endpoint_rebuild_plan: object | None) -> dict[str, tuple[str, str]]:
    if not isinstance(approach_endpoint_rebuild_plan, dict):
        return {}
    rewrites = {}
    for item in approach_endpoint_rebuild_plan.get("edge_rebuilds", []) or []:
        if not isinstance(item, dict):
            continue
        edge_id = str(item.get("edge_id", ""))
        desired_from = str(item.get("desired_from", ""))
        desired_to = str(item.get("desired_to", ""))
        if edge_id and desired_from and desired_to:
            rewrites[edge_id] = (
                _canonical_sumo_cluster_id(desired_from),
                _canonical_sumo_cluster_id(desired_to),
            )
    return rewrites


def _semantic_failure_counts(variant_reports: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for report in variant_reports:
        if report.get("expanded_scope_followup_emitted"):
            continue
        gate = report.get("semantic_replay_effective_gate") or report.get("semantic_replay_gate")
        failures = gate.get("failures", []) if isinstance(gate, dict) else []
        for failure in failures:
            if not isinstance(failure, dict):
                continue
            key = f"{failure.get('report', '')}:{failure.get('field', '')}"
            if key != ":":
                counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _expanded_scope_followup_candidate_for_unsafe_internal_replay(
    candidate: dict[str, Any],
    variant_report: dict[str, object],
    raw_edge_file: Path,
    *,
    junction_id: str,
    strict_teacher_replay: bool = False,
    teacher_join_groups_by_cluster: dict[str, list[str]] | None = None,
) -> dict[str, object] | None:
    if strict_teacher_replay and variant_report.get("parity_gate_status") == "pass":
        return None
    followup_depth = int(candidate.get("followup_depth", 0) or 0)
    if followup_depth >= 1:
        return None
    replay = variant_report.get("target_internal_replay")
    removed_connections = []
    followup_reason = "target_internal_replay_removed_non_target_connections"
    if isinstance(replay, dict):
        removed_connections = [
            connection
            for connection in replay.get("removed_stale_replaced_edge_connections", []) or []
            if isinstance(connection, dict)
        ]
    if not removed_connections:
        restore = variant_report.get("non_target_internal_restore", {})
        internal_restore = restore.get("internal_artifact_restore", {}) if isinstance(restore, dict) else {}
        removed_connections = [
            connection
            for connection in (
                internal_restore.get("skipped_non_target_internal_connection_invalid_lanes", [])
                if isinstance(internal_restore, dict)
                else []
            )
            if isinstance(connection, dict)
        ]
        followup_reason = "non_target_internal_restore_invalid_lane"
    removed_count = len(removed_connections)
    if not removed_count:
        return None
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
        str(item) for item in candidate.get("matched_candidate_node_ids", []) or [] if str(item)
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
    approach_plan = variant_report.get("approach_endpoint_rebuild_plan") or candidate.get(
        "approach_endpoint_rebuild_plan", {}
    )
    if isinstance(approach_plan, dict):
        approach_missing_endpoint_ids = {
            str(item)
            for item in approach_plan.get("missing_desired_endpoint_ids", []) or []
            if str(item)
        }
        junction_ids.update(approach_missing_endpoint_ids)
        missing_desired_endpoint_ids = sorted(
            set(missing_desired_endpoint_ids) | approach_missing_endpoint_ids
        )
    if junction_id and (not raw_endpoint_ids or junction_id in raw_endpoint_ids):
        junction_ids.add(junction_id)
        join_junction_ids.add(junction_id)
    for edge_id in removed_edge_ids:
        junction_ids.update(endpoint for endpoint in endpoints_by_edge.get(edge_id, ()) if endpoint)
    candidate_net_value = str(variant_report.get("candidate_net_file", ""))
    candidate_junction_ids = _net_junction_ids(Path(candidate_net_value)) if candidate_net_value else set()
    affected_internal_junction_ids = {
        owner
        for connection in removed_connections
        for owner in [
            next(
                (
                    candidate_id
                    for candidate_id in sorted(candidate_junction_ids, key=len, reverse=True)
                    if str(connection.get("via", "")).startswith(f":{candidate_id}_")
                ),
                "",
            )
        ]
        if owner
    }
    junction_ids.update(affected_internal_junction_ids)
    for cluster_id, member_ids in (teacher_join_groups_by_cluster or {}).items():
        if affected_internal_junction_ids & set(member_ids):
            junction_ids.add(cluster_id)
    edge_map = _valid_edge_map(candidate.get("edge_map", {}))
    blocked_teacher_edge_ids = sorted(
        teacher_edge_id
        for teacher_edge_id, candidate_edge_id in edge_map.items()
        if candidate_edge_id in removed_edge_ids
    )
    followup = copy.deepcopy(candidate)
    followup.update(
        {
            "candidate_status": "needs_expanded_rebuild_scope",
            "followup_reason": followup_reason,
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


def _plain_edge_endpoints(edge_file: Path) -> dict[str, tuple[str, str]]:
    try:
        root = ET.parse(edge_file).getroot()
    except (ET.ParseError, OSError):
        return {}
    return {
        edge.attrib["id"]: (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
        for edge in root.findall("edge")
        if edge.attrib.get("id")
    }


def _semantic_layer_gate_counts(variant_reports: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for report in variant_reports:
        if report.get("expanded_scope_followup_emitted"):
            continue
        layers = report.get("semantic_layer_gates")
        if not isinstance(layers, dict):
            continue
        for layer_name, layer in layers.items():
            if not isinstance(layer, dict):
                continue
            layer_counts = counts.setdefault(str(layer_name), {"pass": 0, "fail": 0, "failure_count": 0})
            status = "pass" if layer.get("status") == "pass" else "fail"
            layer_counts[status] += 1
            try:
                layer_counts["failure_count"] += int(layer.get("failure_count", 0) or 0)
            except (TypeError, ValueError):
                layer_counts["failure_count"] += 1 if status == "fail" else 0
    return {key: counts[key] for key in sorted(counts)}


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
            "added_or_overridden_count": sum(1 for key, value in pair_map.items() if existing.get(key) != value),
            "reason": "bearing-matched TLS approach evidence applied to full controller-cell variant",
        },
    }


def _expand_fragmented_tls_join_scope_candidate(
    candidate: dict[str, Any],
    raw_node_file: Path,
    *,
    raw_edge_file: Path | None = None,
    reference_net_file: Path | None = None,
    max_controller_span_m: float = 120.0,
    max_controller_node_count: int = 20,
) -> dict[str, Any]:
    """Expand a partial OSM signal cluster to its compact shared controller cell."""

    if candidate.get("learned_rule") not in {
        "tum_like_join_candidate",
        "tum_like_topology_fragmented_tls_candidate",
    }:
        return candidate
    scope_value = candidate.get("expanded_rebuild_scope", {})
    if not isinstance(scope_value, dict):
        return candidate
    requested_ids = {str(value) for value in scope_value.get("join_junction_ids", []) or [] if str(value)}
    original_requested_ids = set(requested_ids)
    exact_reference_ids = {
        str(value) for value in candidate.get("matched_reference_source_node_ids", []) or [] if str(value)
    }
    preserve_exact_reference_membership = len(exact_reference_ids) >= 2 and exact_reference_ids <= requested_ids
    if preserve_exact_reference_membership:
        requested_ids = exact_reference_ids
    report: dict[str, object] = {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "requested_join_junction_ids": sorted(original_requested_ids),
        "automatic_expansion_applied": False,
        "max_controller_span_m": max_controller_span_m,
    }
    if preserve_exact_reference_membership:
        report["exact_reference_join_membership_preserved"] = True
        report["exact_reference_join_junction_ids"] = sorted(exact_reference_ids)
        report["excluded_non_reference_join_junction_ids"] = sorted(original_requested_ids - exact_reference_ids)
    if not requested_ids:
        report["reason"] = "no_requested_join_junction_ids"
        return {**candidate, "tls_join_scope_expansion": report}
    try:
        root = ET.parse(raw_node_file).getroot()
    except (ET.ParseError, OSError) as exc:
        report.update(
            {
                "status": "review",
                "reason": "raw_node_file_unreadable",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return {**candidate, "tls_join_scope_expansion": report}

    nodes = {str(node.attrib.get("id", "")): node for node in root.findall("node") if node.attrib.get("id")}
    missing_ids = sorted(requested_ids - set(nodes))
    requested_controller_node_ids = {
        node_id for node_id in requested_ids & set(nodes) if nodes[node_id].attrib.get("tl")
    }
    controller_ids = {str(nodes[node_id].attrib.get("tl", "")) for node_id in requested_controller_node_ids}
    report["missing_requested_join_junction_ids"] = missing_ids
    report["controller_ids"] = sorted(controller_ids)
    if (
        missing_ids
        or len(controller_ids) != 1
        or (candidate.get("learned_rule") == "tum_like_join_candidate" and len(requested_controller_node_ids) < 2)
    ):
        report.update(
            {
                "status": "review",
                "reason": "requested join nodes do not resolve to one shared TLS controller",
            }
        )
        return {**candidate, "tls_join_scope_expansion": report}

    controller_id = next(iter(controller_ids))
    controller_node_ids = sorted(
        node_id for node_id, node in nodes.items() if node.attrib.get("tl", "") == controller_id
    )
    positions = []
    for node_id in controller_node_ids:
        node = nodes[node_id]
        try:
            positions.append((float(node.attrib["x"]), float(node.attrib["y"])))
        except (KeyError, TypeError, ValueError):
            report.update(
                {
                    "status": "review",
                    "reason": "shared TLS controller node lacks finite coordinates",
                    "controller_node_ids": controller_node_ids,
                }
            )
            return {**candidate, "tls_join_scope_expansion": report}
    span_m = max(
        (math.hypot(ax - bx, ay - by) for index, (ax, ay) in enumerate(positions) for bx, by in positions[index + 1 :]),
        default=0.0,
    )
    report.update(
        {
            "controller_node_ids": controller_node_ids,
            "controller_node_count": len(controller_node_ids),
            "controller_span_m": round(span_m, 3),
        }
    )
    if len(controller_node_ids) > max_controller_node_count or span_m > max_controller_span_m:
        report.update(
            {
                "status": "review",
                "reason": "shared TLS controller is too broad for automatic physical junction joining",
            }
        )
        return {**candidate, "tls_join_scope_expansion": report}

    expansion_node_ids = set(controller_node_ids)
    adjacent_partition_cluster_ids: list[str] = []
    if candidate.get("learned_rule") == "tum_like_join_candidate":
        if raw_edge_file is None:
            report.update(
                {
                    "status": "review",
                    "reason": "raw edge topology is required for TUM core expansion",
                }
            )
            return {**candidate, "tls_join_scope_expansion": report}
        try:
            edge_root = ET.parse(raw_edge_file).getroot()
        except (ET.ParseError, OSError) as exc:
            report.update(
                {
                    "status": "review",
                    "reason": "raw_edge_file_unreadable",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            return {**candidate, "tls_join_scope_expansion": report}
        raw_edges = list(edge_root.findall("edge"))
        directly_adjacent_controller_ids: set[str] = set()
        adjacency_evidence: list[dict[str, str]] = []
        controller_node_id_set = set(controller_node_ids)
        for edge in raw_edges:
            edge_id = edge.attrib.get("id", "")
            source = edge.attrib.get("from", "")
            target = edge.attrib.get("to", "")
            if source in controller_node_id_set and source not in requested_ids and target in requested_ids:
                directly_adjacent_controller_ids.add(source)
                adjacency_evidence.append({"node_id": source, "core_node_id": target, "edge_id": edge_id})
            if target in controller_node_id_set and target not in requested_ids and source in requested_ids:
                directly_adjacent_controller_ids.add(target)
                adjacency_evidence.append({"node_id": target, "core_node_id": source, "edge_id": edge_id})
        other_reference_partition_node_ids: set[str] = set()
        other_reference_partition_groups: dict[str, set[str]] = {}
        if reference_net_file is not None:
            try:
                reference_root = ET.parse(reference_net_file).getroot()
            except (ET.ParseError, OSError) as exc:
                report.update(
                    {
                        "status": "review",
                        "reason": "reference_net_file_unreadable",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                return {**candidate, "tls_join_scope_expansion": report}
            target_reference_id = str(candidate.get("reference_id", ""))
            for junction in reference_root.findall("junction"):
                reference_id = junction.attrib.get("id", "")
                if not reference_id or reference_id.startswith(":") or reference_id == target_reference_id:
                    continue
                if reference_id.startswith("cluster_"):
                    partition_node_ids = {
                        part
                        for part in reference_id.removeprefix("cluster_").split("_")
                        if part and not part.startswith("#")
                    }
                    other_reference_partition_node_ids.update(partition_node_ids)
                    if len(partition_node_ids) >= 2:
                        other_reference_partition_groups[reference_id] = partition_node_ids
                else:
                    other_reference_partition_node_ids.add(reference_id)
            directly_adjacent_controller_ids -= other_reference_partition_node_ids
        if preserve_exact_reference_membership:
            directly_adjacent_controller_ids.clear()
        expansion_node_ids = requested_ids | directly_adjacent_controller_ids
        main_partition_node_ids = set(expansion_node_ids)
        unpartitioned_controller_node_ids = (
            controller_node_id_set - main_partition_node_ids - other_reference_partition_node_ids
        )
        unjoined_partition_fringe_node_ids: set[str] = set()
        absorbed_non_motorized_fringe_node_ids: set[str] = set()
        for reference_id, partition_node_ids in sorted(other_reference_partition_groups.items()):
            present_partition_node_ids = partition_node_ids & set(nodes)
            if len(present_partition_node_ids) < 2:
                continue
            directly_touches_main = any(
                {
                    edge.attrib.get("from", ""),
                    edge.attrib.get("to", ""),
                }
                & present_partition_node_ids
                and {
                    edge.attrib.get("from", ""),
                    edge.attrib.get("to", ""),
                }
                & main_partition_node_ids
                for edge in raw_edges
            )
            if not directly_touches_main:
                continue
            fringe_node_ids = {
                endpoint
                for edge in raw_edges
                for endpoint, other in (
                    (edge.attrib.get("from", ""), edge.attrib.get("to", "")),
                    (edge.attrib.get("to", ""), edge.attrib.get("from", "")),
                )
                if endpoint in unpartitioned_controller_node_ids and other in present_partition_node_ids
            }
            if not fringe_node_ids:
                continue
            unjoined_partition_fringe_node_ids.update(fringe_node_ids)
            eligible_fringe_node_ids = set()
            for fringe_node_id in sorted(fringe_node_ids - absorbed_non_motorized_fringe_node_ids):
                incident_edges = [
                    edge
                    for edge in raw_edges
                    if fringe_node_id in {edge.attrib.get("from", ""), edge.attrib.get("to", "")}
                ]
                if incident_edges and all(
                    not (_sumo_allowed_classes(edge.attrib) & ROAD_MOTORIZED_CLASSES) for edge in incident_edges
                ):
                    eligible_fringe_node_ids.add(fringe_node_id)
            absorbed_non_motorized_fringe_node_ids.update(eligible_fringe_node_ids)
            partition_join_ids = sorted(present_partition_node_ids | eligible_fringe_node_ids)
            if len(partition_join_ids) > max_controller_node_count:
                report.update(
                    {
                        "status": "review",
                        "reason": "adjacent teacher partition exceeds automatic node-count limit",
                        "adjacent_reference_partition_id": reference_id,
                        "adjacent_partition_join_ids": partition_join_ids,
                    }
                )
                return {**candidate, "tls_join_scope_expansion": report}
            adjacent_partition_cluster_ids.append(_sumo_joined_cluster_id(partition_join_ids))
        report["adjacent_teacher_partition_cluster_ids"] = sorted(adjacent_partition_cluster_ids)
        unjoined_partition_fringe_node_ids -= absorbed_non_motorized_fringe_node_ids
        report["absorbed_non_motorized_fringe_node_ids"] = sorted(absorbed_non_motorized_fringe_node_ids)
        report["unjoined_reference_partition_fringe_node_ids"] = sorted(unjoined_partition_fringe_node_ids)
        report["directly_adjacent_controller_node_ids"] = sorted(directly_adjacent_controller_ids - requested_ids)
        report["direct_core_adjacency_evidence"] = sorted(
            [row for row in adjacency_evidence if row["node_id"] in directly_adjacent_controller_ids],
            key=lambda row: (row["node_id"], row["core_node_id"], row["edge_id"]),
        )
        report["excluded_other_reference_partition_node_ids"] = sorted(
            controller_node_id_set & other_reference_partition_node_ids
        )
        if reference_net_file is not None:
            report["reference_net_sha256"] = hashlib.sha256(reference_net_file.read_bytes()).hexdigest()

    expanded_scope = copy.deepcopy(scope_value)
    expanded_join_ids = sorted(requested_ids | expansion_node_ids)
    if len(expanded_join_ids) > max_controller_node_count:
        report.update(
            {
                "status": "review",
                "reason": "expanded physical junction exceeds automatic node-count limit",
                "proposed_join_junction_ids": expanded_join_ids,
                "expanded_join_node_count": len(expanded_join_ids),
                "max_expanded_join_node_count": max_controller_node_count,
            }
        )
        return {**candidate, "tls_join_scope_expansion": report}
    expanded_scope["join_junction_ids"] = expanded_join_ids
    expanded_scope["junction_ids"] = sorted(
        {
            *expansion_node_ids,
            *(str(value) for value in expanded_scope.get("junction_ids", []) or [] if str(value)),
            *adjacent_partition_cluster_ids,
        }
    )
    added_ids = sorted(expansion_node_ids - requested_ids)
    report.update(
        {
            "automatic_expansion_applied": bool(added_ids),
            "added_join_junction_ids": added_ids,
            "expanded_join_junction_ids": expanded_join_ids,
            "expanded_join_node_count": len(expanded_join_ids),
            "max_expanded_join_node_count": max_controller_node_count,
            "reason": (
                "same-controller nodes directly adjacent to the TUM source-node core expanded before join"
                if candidate.get("learned_rule") == "tum_like_join_candidate"
                else "compact shared TLS controller cell expanded before physical junction join"
            ),
        }
    )
    return {
        **candidate,
        "expanded_rebuild_scope": expanded_scope,
        "tls_join_scope_expansion": report,
    }


def _candidate_connection_mode_scope_ids(
    report: dict[str, object],
) -> tuple[list[str], list[str]]:
    """Return equivalent source/candidate scopes for a differential audit.

    A plain-XML junction join removes several source junction IDs and creates a
    new cluster ID.  Unchanged boundary junctions can also be part of the
    intended edit scope.  Excluding the complete scope on both sides prevents
    those expected identity changes from being mistaken for global collateral
    damage while every other junction remains subject to the regression gate.
    """

    source_ids: set[str] = set()
    matched_ids = report.get("matched_candidate_node_ids", [])
    if isinstance(matched_ids, (list, tuple, set)):
        source_ids.update(str(value) for value in matched_ids if str(value))
    expanded_scope = report.get("expanded_rebuild_scope", {})
    if isinstance(expanded_scope, dict):
        for field in ("junction_ids", "join_junction_ids"):
            values = expanded_scope.get(field, [])
            if isinstance(values, (list, tuple, set)):
                source_ids.update(str(value) for value in values if str(value))
        if not source_ids:
            core_junction_id = str(expanded_scope.get("core_junction_id", ""))
            if core_junction_id:
                source_ids.add(core_junction_id)
    if not source_ids:
        original_junction_id = str(report.get("candidate_original_junction_id", ""))
        if original_junction_id:
            source_ids.add(original_junction_id)

    candidate_ids = set(source_ids)
    candidate_junction_id = str(report.get("junction_id", ""))
    if candidate_junction_id:
        candidate_ids.add(candidate_junction_id)
    return sorted(source_ids), sorted(candidate_ids)


def _write_teacher_guided_promotion_gate(
    *,
    output_file: Path,
    status: str,
    claim_status: str,
    parity_gate_status: str,
    approach_integrity_status: str,
    variant_reports: list[dict[str, object]],
    context_gate_status: str = "skipped",
    connection_mode_regression_status: str = "skipped",
    final_composite_sumo_load_status: str = "skipped",
    final_composite_sumo_load_required: bool = False,
) -> dict[str, object]:
    applied_reports = [report for report in variant_reports if report.get("composite_applied")]
    effective_final_composite_sumo_load_required = final_composite_sumo_load_required or bool(applied_reports)
    global_candidate_reports = [
        report for report in variant_reports if bool(report.get("global_candidate_eligible", True))
    ]
    gate_reports = (
        applied_reports
        or [report for report in global_candidate_reports if not report.get("expanded_scope_followup_emitted")]
        or global_candidate_reports
        or [report for report in variant_reports if not report.get("expanded_scope_followup_emitted")]
    )
    items = [
        {
            "junction_id": str(report.get("junction_id", "")),
            "teacher_junction_id": str(report.get("teacher_junction_id", "")),
            "status": str(report.get("status", "")),
            "parity_gate_status": str(report.get("parity_gate_status", "")),
            "connection_mode_regression_status": str(
                report.get("connection_mode_regression", {}).get("status", "not_run")
            )
            if isinstance(report.get("connection_mode_regression"), dict)
            else "not_run",
            "final_net_file": str(report.get("final_net_file", "")),
            "candidate_scope_status": str(report.get("candidate_scope_status") or "full_network"),
            "global_candidate_eligible": bool(report.get("global_candidate_eligible", True)),
            "semantic_layer_gates": report.get("semantic_layer_gates", {})
            if isinstance(report.get("semantic_layer_gates"), dict)
            else {},
        }
        for report in gate_reports
    ]
    gate_status = (
        "pass"
        if status == "pass"
        and parity_gate_status == "pass"
        and context_gate_status != "fail"
        and connection_mode_regression_status != "fail"
        and (not effective_final_composite_sumo_load_required or final_composite_sumo_load_status == "pass")
        and approach_integrity_status == "pass"
        and items
        and all(item["status"] == "pass" and item["parity_gate_status"] == "pass" for item in items)
        else ("blocked" if not items else "fail")
    )
    report = {
        "status": gate_status,
        "claim_status": claim_status,
        "parity_gate_status": parity_gate_status,
        "context_gate_status": context_gate_status,
        "connection_mode_regression_status": connection_mode_regression_status,
        "final_composite_sumo_load_status": final_composite_sumo_load_status,
        "final_composite_sumo_load_required": (effective_final_composite_sumo_load_required),
        "approach_integrity_status": approach_integrity_status,
        "candidate_count": len(items),
        "pass_candidate_count": sum(1 for item in items if item["status"] == "pass"),
        "items": items,
    }
    output_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def _approach_integrity_failure_counts(semantic_failure_counts: dict[str, int]) -> dict[str, int]:
    counts = {
        key: value
        for key, value in semantic_failure_counts.items()
        if key.split(":", 1)[-1] in APPROACH_INTEGRITY_FAILURE_FIELDS
    }
    return dict(sorted(counts.items()))


def _approach_integrity_status(
    *,
    parity_gate_status: str,
    attempted_count: int,
    semantic_failure_counts: dict[str, int],
    approach_failure_counts: dict[str, int],
) -> str:
    if approach_failure_counts:
        return "fail"
    if attempted_count == 0 or parity_gate_status == "blocked":
        return "blocked"
    if semantic_failure_counts or parity_gate_status == "pass":
        return "pass"
    return "blocked"


def _teacher_pattern_contexts(variant_reports: list[dict[str, object]]) -> list[dict[str, object]]:
    contexts = []
    seen_keys = set()
    for report in variant_reports:
        pattern_key = str(report.get("teacher_pattern_key", ""))
        if not pattern_key or pattern_key in seen_keys:
            continue
        seen_keys.add(pattern_key)
        try:
            template_count = int(report.get("teacher_pattern_template_count", 0) or 0)
        except (TypeError, ValueError):
            template_count = 0
        examples = report.get("teacher_pattern_template_examples", [])
        contexts.append(
            {
                "teacher_pattern_key": pattern_key,
                "teacher_pattern_family": str(report.get("teacher_pattern_family", "")),
                "teacher_pattern_template_count": template_count,
                "teacher_pattern_template_examples": [str(item) for item in examples]
                if isinstance(examples, list)
                else [],
            }
        )
    return contexts


def _attach_candidate_template_context(
    report: dict[str, object],
    candidate: dict[str, Any],
) -> dict[str, object]:
    context = {
        key: candidate[key]
        for key in (
            "teacher_pattern_key",
            "teacher_pattern_family",
            "teacher_pattern_template_count",
            "teacher_pattern_template_examples",
            "matched_candidate_node_ids",
            "expanded_rebuild_scope",
            "tls_join_scope_expansion",
            "tls_approach_edge_map_evidence",
            "sequential_refreshed_candidate",
            "sequential_refresh_source_net_file",
            "sequential_refresh_status",
            "sequential_refresh_error",
            "sequential_allowed_boundary_overlap_edge_ids",
        )
        if key in candidate
    }
    candidate_original_junction_id = str(candidate.get("junction_id", ""))
    if candidate_original_junction_id:
        context["candidate_original_junction_id"] = candidate_original_junction_id
    if not context:
        return report
    merged = {**report, **context}
    report_file = str(report.get("report_file", ""))
    if report_file:
        try:
            path = Path(report_file)
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                path.write_text(json.dumps({**existing, **context}, indent=2, ensure_ascii=False), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass
    return merged


def _should_emit(movement: dict[str, object]) -> bool:
    return movement.get("status") == "emit" and float(movement.get("confidence", 0.0)) >= 0.5


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


def _teacher_guided_candidate_sort_key(candidate: dict[str, object]) -> tuple[int, int, int, int, int, str]:
    movement_gap = int(candidate.get("vehicle_movement_matrix_missing_count", 0) or 0)
    template_count = int(candidate.get("teacher_pattern_template_count", 0) or 0)
    candidate_nodes = candidate.get("matched_candidate_node_ids")
    candidate_node_count = len(candidate_nodes) if isinstance(candidate_nodes, list) else 1_000_000
    status_rank = (
        0
        if candidate.get("candidate_status") in {"ready_for_teacher_guided_variant", "needs_expanded_rebuild_scope"}
        else 1
    )
    is_same_id_tls = candidate.get("learned_rule") == "tum_like_same_id_tls_candidate"
    semantic_rank = 0 if is_same_id_tls else 1
    movement_rank = movement_gap if is_same_id_tls else -movement_gap
    return (
        status_rank,
        semantic_rank,
        movement_rank,
        -template_count,
        candidate_node_count,
        str(candidate.get("reference_id", "")),
    )


def _limit_ready_repair_candidates(
    candidates: list[dict[str, object]], max_ready_candidates: int
) -> list[dict[str, object]]:
    ready = [
        candidate for candidate in candidates if candidate.get("candidate_status") == "ready_for_teacher_guided_variant"
    ][:max_ready_candidates]
    if len(ready) >= max_ready_candidates:
        return ready
    ready_ids = {id(candidate) for candidate in ready}
    selected = list(ready)
    for candidate in candidates:
        if id(candidate) in ready_ids:
            continue
        selected.append(candidate)
    return selected


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


def _tls_repair_actions(repair_category: str) -> list[str]:
    if repair_category == "tls_linkindex_phase_repair":
        return ["inspect_tls_linkindex_phase"]
    return ["inspect_tls_control"]


def _queue_path(value: object, base_dir: Path | None) -> Path:
    path = Path(str(value))
    if path.is_absolute() or base_dir is None:
        return path
    return base_dir / path


def _valid_edge_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        return {}
    result: dict[str, str] = {}
    for source, target in value.items():
        if not isinstance(source, str) or not source.strip():
            return {}
        if not isinstance(target, str) or not target.strip():
            return {}
        result[source] = target
    return result


def _prefer_existing_exact_edge_ids(
    edge_map: dict[str, str],
    candidate_edges_by_id: dict[str, ET.Element],
) -> dict[str, str]:
    return {
        teacher_edge_id: teacher_edge_id if teacher_edge_id in candidate_edges_by_id else candidate_edge_id
        for teacher_edge_id, candidate_edge_id in edge_map.items()
    }


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


def _junction_pattern_record_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = {}
    for record in report.get("junction_pattern_index", []) or []:
        if not isinstance(record, dict):
            continue
        junction_id = str(record.get("junction_id", ""))
        if junction_id:
            records[junction_id] = record
    return records


def _junction_pattern_template_by_key(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    templates = {}
    for template in report.get("junction_pattern_templates", []) or []:
        if not isinstance(template, dict):
            continue
        pattern_key = str(template.get("pattern_key", ""))
        if pattern_key:
            templates[pattern_key] = template
    return templates


def _teacher_template_count_for_case(
    case: dict[str, Any],
    pattern_records: dict[str, dict[str, Any]],
    pattern_templates: dict[str, dict[str, Any]],
) -> int:
    reference_id = str(case.get("reference_id", ""))
    pattern_key = str(pattern_records.get(reference_id, {}).get("pattern_key", ""))
    if not pattern_key:
        return 0
    return int(pattern_templates.get(pattern_key, {}).get("count", 0) or 0)


def _junction_pattern_delta_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    deltas = {}
    for comparison in report.get("junction_pattern_comparisons", []) or []:
        if not isinstance(comparison, dict):
            continue
        junction_id = str(comparison.get("junction_id", ""))
        if not junction_id:
            continue
        deltas[junction_id] = {
            "junction_id": junction_id,
            "status": str(comparison.get("status", "")),
            "mismatch_fields": [str(field) for field in comparison.get("mismatch_fields", []) or []],
            "teacher": comparison.get("teacher", {}) if isinstance(comparison.get("teacher"), dict) else {},
            "candidate": comparison.get("candidate", {}) if isinstance(comparison.get("candidate"), dict) else {},
        }
    return deltas


def _same_id_pattern_cases(
    pattern_deltas: dict[str, dict[str, Any]],
    matched_cases: list[dict[str, Any]],
    teacher_root: ET.Element,
    candidate_root: ET.Element,
    target_reference_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    covered_ids = {key for case in matched_cases for key in _junction_pattern_delta_keys(case)}
    teacher_junction_ids = _real_junction_ids(teacher_root)
    candidate_junction_ids = _real_junction_ids(candidate_root)
    cases = []
    for junction_id, delta in sorted(pattern_deltas.items()):
        if target_reference_ids and junction_id not in target_reference_ids:
            continue
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
    target_reference_ids: set[str] | None = None,
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
        if target_reference_ids and reference_id not in target_reference_ids:
            continue
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


def _topology_fragmented_tls_cases(
    matched_cases: list[dict[str, Any]],
    teacher_root: ET.Element,
    candidate_root: ET.Element,
    teacher_net_file: Path,
    candidate_edges_by_id: dict[str, ET.Element],
    target_reference_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    covered_ids = {key for case in matched_cases for key in _junction_pattern_delta_keys(case)}
    candidate_junction_ids = _real_junction_ids(candidate_root)
    cases = []
    for junction in teacher_root.findall("junction"):
        reference_id = junction.attrib.get("id", "")
        if target_reference_ids and reference_id not in target_reference_ids:
            continue
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
    target_reference_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    covered_ids = {key for case in matched_cases for key in _junction_pattern_delta_keys(case)}
    candidate_junction_ids = _real_junction_ids(candidate_root)
    cases = []
    for junction in teacher_root.findall("junction"):
        reference_id = junction.attrib.get("id", "")
        if target_reference_ids and reference_id not in target_reference_ids:
            continue
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
    target_reference_ids: set[str] | None = None,
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
        if target_reference_ids and junction_id not in target_reference_ids:
            continue
        if not junction_id or junction_id in covered_ids or junction_id not in candidate_junction_ids:
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


def _teacher_junction_has_tls(
    root: ET.Element,
    junction_id: str,
    junction: ET.Element,
) -> bool:
    return (
        junction.attrib.get("type") == "traffic_light"
        or any(tl.attrib.get("id") == junction_id for tl in root.findall("tlLogic"))
        or any(connection.attrib.get("tl") == junction_id for connection in root.findall("connection"))
    )


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


def _candidate_edge_by_exact_or_unsplit_id(
    edge_id: str,
    candidate_edges_by_id: dict[str, ET.Element],
) -> tuple[str, ET.Element | None]:
    candidate_edge = candidate_edges_by_id.get(edge_id)
    if candidate_edge is not None:
        return edge_id, candidate_edge
    if "#" not in edge_id:
        return "", None
    base_edge_id = edge_id.split("#", 1)[0]
    candidate_edge = candidate_edges_by_id.get(base_edge_id)
    if candidate_edge is None:
        return "", None
    return base_edge_id, candidate_edge


def _real_junction_ids(root: ET.Element) -> set[str]:
    return {
        junction.attrib["id"]
        for junction in root.findall("junction")
        if junction.attrib.get("id")
        and not junction.attrib["id"].startswith(":")
        and junction.attrib.get("type") != "internal"
    }


def _attach_teacher_pattern_template(
    candidate: dict[str, object],
    pattern_records: dict[str, dict[str, Any]],
    pattern_templates: dict[str, dict[str, Any]],
) -> dict[str, object]:
    reference_id = str(candidate.get("reference_id", ""))
    record = pattern_records.get(reference_id, {})
    movement_exemplar = candidate.get("movement_exemplar", {})
    exemplar_pattern_key = str(movement_exemplar.get("pattern_key", "")) if isinstance(movement_exemplar, dict) else ""
    pattern_key = str(record.get("pattern_key", "")) or exemplar_pattern_key
    if not pattern_key:
        return candidate
    template = pattern_templates.get(pattern_key, {})
    return {
        **candidate,
        "teacher_pattern_key": pattern_key,
        "teacher_pattern_family": str(template.get("pattern_family", record.get("pattern_family", ""))),
        "teacher_pattern_template_count": int(template.get("count", 0) or 0),
        "teacher_pattern_template_examples": [str(item) for item in template.get("example_junction_ids", []) or []],
    }


def _attach_junction_pattern_delta(
    candidate: dict[str, object],
    deltas: dict[str, dict[str, Any]],
) -> dict[str, object]:
    matches = [deltas[key] for key in _junction_pattern_delta_keys(candidate) if key in deltas]
    if not matches:
        return candidate
    mismatch_fields = list(dict.fromkeys(field for delta in matches for field in delta.get("mismatch_fields", [])))
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


def _netedit_review_actions(mismatch_fields: list[str]) -> list[str]:
    action_by_field = {
        "internal_function_counts": "inspect_internal_edges_crossings_walkingareas",
        "approach_edge_ids": "verify_approach_membership",
        "control_type": "inspect_tls_control",
        "has_tls": "inspect_tls_control",
        "movement_signature_counts": "rebuild_vehicle_movement_matrix",
        "request_bit_lengths_ok": "inspect_request_foes_response",
    }
    return list(
        dict.fromkeys(action_by_field.get(field, "inspect_junction_pattern_delta") for field in mismatch_fields)
    )


def _junction_pattern_delta_keys(candidate: dict[str, object]) -> list[str]:
    keys = [str(candidate.get("reference_id", "")), str(candidate.get("junction_id", ""))]
    for field in ("reference_joined_source_nodes", "matched_reference_source_node_ids", "matched_candidate_node_ids"):
        keys.extend(str(item) for item in candidate.get(field, []) or [])
    return [key for key in dict.fromkeys(keys) if key]


def _queue_candidate_dir(index: int, junction_id: str) -> str:
    return f"candidate_{index + 1:03d}_{_stable_digest(junction_id)}"


def _stable_digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def _safe_stage_name(value: str, max_len: int = 64) -> str:
    safe = "".join(char if char.isascii() and (char.isalnum() or char in "._-") else "_" for char in value.strip())
    safe = safe.strip("._-")
    safe = safe or "candidate"
    if len(safe) <= max_len:
        return safe
    head_len = max(1, max_len - 9)
    return f"{safe[:head_len]}_{_stable_digest(safe)}"


def _split(value: str) -> list[str]:
    return [part for part in value.split() if part]


def _write_connections(
    path: Path,
    movements: list[dict[str, object]],
) -> None:
    root = ET.Element("connections")
    for movement in movements:
        ET.SubElement(
            root,
            "connection",
            {
                "from": str(movement.get("source_edge_id") or movement.get("from_edge_id") or ""),
                "to": str(movement.get("target_edge_id") or movement.get("to_edge_id") or ""),
                "fromLane": str(movement.get("fromLane", "0") or "0"),
                "toLane": str(movement.get("toLane", "0") or "0"),
            },
        )
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _approach_edges(candidate_model: dict[str, object], direction: str) -> list[str]:
    approaches = candidate_model.get("approaches", {})
    if not isinstance(approaches, dict):
        return []
    return [
        str(edge.get("edge_id", ""))
        for edge in approaches.get(direction, []) or []
        if isinstance(edge, dict) and edge.get("edge_id")
    ]


def _approaches(model: dict[str, object], direction: str) -> list[dict[str, Any]]:
    approaches = model.get("approaches", {})
    if not isinstance(approaches, dict):
        return []
    return [edge for edge in approaches.get(direction, []) or [] if isinstance(edge, dict)]


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


def _conservative_join_node_ids(candidate_node_ids: list[str], matched_source_node_ids: set[str]) -> list[str]:
    matched = [node_id for node_id in candidate_node_ids if node_id in matched_source_node_ids]
    if len(matched) >= 2:
        return matched
    if len(matched) == 1:
        first_other = next((node_id for node_id in candidate_node_ids if node_id != matched[0]), "")
        return [first_other, matched[0]] if first_other else matched
    return candidate_node_ids[:2]


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
    candidate_node_ids = [
        str(item) for item in case.get("matched_candidate_node_ids") or case.get("candidate_node_ids") or []
    ]
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
    conservative_candidate_junction_id = _sumo_joined_cluster_id(join_node_ids)
    if conservative_candidate_junction_id and conservative_candidate_junction_id not in candidate_junction_ids:
        candidate_junction_ids.append(conservative_candidate_junction_id)
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
    teacher_approach_edge_ids = {
        edge_id
        for edge_id, edge in teacher_edges.items()
        if reference_id in {edge.attrib.get("from", ""), edge.attrib.get("to", "")}
    }
    case_edge_map = {
        teacher_edge_id: candidate_edge_id
        for teacher_edge_id, candidate_edge_id in case_edge_map.items()
        if teacher_edge_id in teacher_approach_edge_ids
    }
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
        _approach_nodes, exact_or_unsplit_edge_map = _candidate_nodes_from_exact_teacher_approach_edges(
            teacher_model,
            candidate_edges_by_id,
            _real_junction_ids(candidate_root),
        )
        case_edge_map = dict(sorted({**exact_or_unsplit_edge_map, **case_edge_map}.items()))
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
            junction.attrib["id"] for junction in candidate_root.findall("junction") if junction.attrib.get("id")
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
    joined_source_node_ids = list(dict.fromkeys(reference_source_node_ids or matched_reference_source_node_ids))
    candidate_normal_junction_ids = _real_junction_ids(candidate_root)
    if (
        expanded_rebuild_scope["status"] != "review"
        and candidate_junction_id == reference_id
        and len(joined_source_node_ids) >= 2
        and set(joined_source_node_ids) <= candidate_normal_junction_ids
    ):
        expanded_rebuild_scope = {
            "status": "review",
            "recommended_action": "rebuild_plain_xml_scope",
            "core_junction_id": candidate_junction_id,
            "junction_ids": sorted([candidate_junction_id, *joined_source_node_ids]),
            "join_junction_ids": [candidate_junction_id],
            "blocked_teacher_edge_ids": [],
            "missing_desired_endpoint_ids": [],
            "reason": "joined cluster still has all source member junctions",
        }
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
            existing_junction_ids = [str(item) for item in existing_scope.get("junction_ids", []) or [] if str(item)]
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
            "junction_ids": sorted({candidate_junction_id, *missing_endpoint_ids})
            if candidate_junction_id
            else missing_endpoint_ids,
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
    current_candidate_node_ids = (
        joined_source_node_ids
        if candidate_junction_id == reference_id and len(joined_source_node_ids) >= 2
        else candidate_node_ids
    )
    return {
        **base,
        "junction_id": candidate_junction_id,
        "matched_candidate_node_ids": current_candidate_node_ids,
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


def _sumo_joined_cluster_id(node_ids: list[str]) -> str:
    ids = sorted(dict.fromkeys(node_id for node_id in node_ids if node_id))
    if not ids:
        return ""
    head = "_".join(ids[:4])
    suffix = "" if len(ids) <= 4 else f"_#{len(ids) - 4}more"
    return f"cluster_{head}{suffix}"


def _canonical_sumo_cluster_id(value: str) -> str:
    members = _sumo_cluster_member_ids(value)
    return _sumo_joined_cluster_id(members) if len(members) > 4 else value


def _sumo_cluster_member_ids(node_id: str) -> list[str]:
    """Expand the lossless part of a SUMO joined-cluster id.

    ``netconvert`` names an explicit join from its source node ids as
    ``cluster_<id>_<id>...``.  Expanded teacher scopes carry those generated
    ids in ``junction_ids`` even though the plain OSM source still contains
    the member nodes.  The ``_#Nmore`` suffix is deliberately ignored: it is
    a display-only truncation and must never be treated as a real node id.
    """

    value = str(node_id or "")
    if not value.startswith("cluster_"):
        return [value] if value else []
    members = [token for token in value.removeprefix("cluster_").split("_") if token and not token.startswith("#")]
    return members


def _expanded_rebuild_scope(
    core_junction_id: str,
    approach_endpoint_rebuild_plan: dict[str, Any],
    *,
    blocked_teacher_edge_ids: list[str],
    fallback_junction_ids: list[str] | None = None,
) -> dict[str, Any]:
    if approach_endpoint_rebuild_plan.get("status") == "review":
        neighbor_ids = [
            str(item) for item in approach_endpoint_rebuild_plan.get("affected_neighbor_junction_ids", []) or []
        ]
        missing_ids = [
            str(item) for item in approach_endpoint_rebuild_plan.get("missing_desired_endpoint_ids", []) or []
        ]
        reason = (
            "approach endpoints differ and at least one missing teacher edge cannot be copied safely"
            if blocked_teacher_edge_ids
            else "approach endpoints differ; rebuild expanded scope before teacher movement replay"
        )
        return {
            "status": "review",
            "recommended_action": "rebuild_plain_xml_scope",
            "core_junction_id": core_junction_id,
            "junction_ids": sorted({core_junction_id, *neighbor_ids, *missing_ids}),
            "join_junction_ids": [core_junction_id] if core_junction_id else [],
            "blocked_teacher_edge_ids": blocked_teacher_edge_ids,
            "missing_desired_endpoint_ids": missing_ids,
            "reason": reason,
        }
    if not blocked_teacher_edge_ids:
        return {"status": "pass", "recommended_action": "none", "junction_ids": []}
    fallback_ids = sorted({str(item) for item in fallback_junction_ids or [] if str(item)})
    if len(fallback_ids) < 2:
        return {"status": "pass", "recommended_action": "none", "junction_ids": []}
    return {
        "status": "review",
        "recommended_action": "rebuild_plain_xml_scope",
        "core_junction_id": core_junction_id,
        "junction_ids": fallback_ids,
        "join_junction_ids": fallback_ids,
        "blocked_teacher_edge_ids": blocked_teacher_edge_ids,
        "missing_desired_endpoint_ids": [],
        "reason": "missing teacher approach edge cannot be copied safely; rebuild from matched candidate source nodes",
    }


def _missing_teacher_edge_endpoint_ids(
    teacher_edges: dict[str, ET.Element],
    missing_teacher_edge_ids: list[str],
    reference_id: str,
) -> list[str]:
    return sorted(
        {
            endpoint
            for edge_id in missing_teacher_edge_ids
            if (edge := teacher_edges.get(edge_id)) is not None
            for endpoint in (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
            if endpoint and endpoint != reference_id
        }
    )


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
                desired_to = _mapped_junction_ref(
                    str(teacher_edge.get("to", "")), teacher_junction_id, target_junction_id
                )
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


def _teacher_approach_edge_ids(teacher_model: dict[str, object]) -> list[str]:
    return sorted(
        dict.fromkeys(_approach_edges(teacher_model, "incoming") + _approach_edges(teacher_model, "outgoing"))
    )


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


def _is_turnaround_connection(connection: dict[str, object]) -> bool:
    return str(connection.get("dir", "")).lower() == TURNAROUND_DIR


def _write_teacher_guided_queue_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "reference_id",
                "junction_id",
                "candidate_status",
                "junction_pattern_delta_count",
                "junction_pattern_mismatch_fields",
                "netedit_review_actions",
                "review_priority",
                "teacher_pattern_key",
                "teacher_pattern_template_count",
                "vehicle_movement_matrix_missing_count",
                "missing_teacher_movement_plan_count",
                "turnaround_only_lane_gap_count",
                "edge_map_size",
                "missing_teacher_edge_ids",
                "copyable_missing_teacher_edge_ids",
                "uncopyable_missing_teacher_edge_ids",
                "matched_candidate_node_ids",
                "learned_rule",
                "error",
            ],
        )
        writer.writeheader()
        for row in rows:
            edge_map = row.get("edge_map", {})
            writer.writerow(
                {
                    "reference_id": row.get("reference_id", ""),
                    "junction_id": row.get("junction_id", ""),
                    "candidate_status": row.get("candidate_status", ""),
                    "junction_pattern_delta_count": row.get("junction_pattern_delta_count", 0),
                    "junction_pattern_mismatch_fields": ";".join(
                        str(item) for item in row.get("junction_pattern_mismatch_fields", []) or []
                    ),
                    "netedit_review_actions": ";".join(
                        str(item) for item in row.get("netedit_review_actions", []) or []
                    ),
                    "review_priority": row.get("review_priority", ""),
                    "teacher_pattern_key": row.get("teacher_pattern_key", ""),
                    "teacher_pattern_template_count": row.get("teacher_pattern_template_count", 0),
                    "vehicle_movement_matrix_missing_count": row.get("vehicle_movement_matrix_missing_count", 0),
                    "missing_teacher_movement_plan_count": row.get("missing_teacher_movement_plan_count", 0),
                    "turnaround_only_lane_gap_count": row.get("turnaround_only_lane_gap_count", 0),
                    "edge_map_size": len(edge_map) if isinstance(edge_map, dict) else 0,
                    "missing_teacher_edge_ids": ";".join(
                        str(item) for item in row.get("missing_teacher_edge_ids", []) or []
                    ),
                    "copyable_missing_teacher_edge_ids": ";".join(
                        str(item) for item in row.get("copyable_missing_teacher_edge_ids", []) or []
                    ),
                    "uncopyable_missing_teacher_edge_ids": ";".join(
                        str(item) for item in row.get("uncopyable_missing_teacher_edge_ids", []) or []
                    ),
                    "matched_candidate_node_ids": ";".join(
                        str(item) for item in row.get("matched_candidate_node_ids", []) or []
                    ),
                    "learned_rule": row.get("learned_rule", ""),
                    "error": row.get("error", ""),
                }
            )


def _candidate_lane_counts(candidate_model: dict[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for direction in ("incoming", "outgoing"):
        approaches = candidate_model.get("approaches", {})
        if not isinstance(approaches, dict):
            continue
        for edge in approaches.get(direction, []) or []:
            if isinstance(edge, dict) and edge.get("edge_id"):
                counts[str(edge["edge_id"])] = max(1, int(edge.get("lane_count", 1) or 1))
    return counts


def _model_vehicle_lane_indices(model: dict[str, object]) -> dict[str, list[int]]:
    indices: dict[str, list[int]] = {}
    approaches = model.get("approaches", {})
    if not isinstance(approaches, dict):
        return indices
    for direction in ("incoming", "outgoing"):
        for edge in approaches.get(direction, []) or []:
            if not isinstance(edge, dict) or not edge.get("edge_id"):
                continue
            indices[str(edge["edge_id"])] = sorted(
                int(lane.get("index", position))
                for position, lane in enumerate(edge.get("lanes", []) or [])
                if isinstance(lane, dict) and _sumo_allowed_classes(lane) & ROAD_MOTORIZED_CLASSES
            )
    return indices


def _mapped_vehicle_lane_index(
    teacher_edge_id: str,
    candidate_edge_id: str,
    teacher_lane_index: int,
    teacher_indices_by_edge: Mapping[str, Sequence[int]],
    candidate_indices_by_edge: Mapping[str, Sequence[int]],
    candidate_lane_counts: Mapping[str, int],
) -> int:
    teacher_indices = list(teacher_indices_by_edge.get(teacher_edge_id, ()))
    candidate_indices = sorted(candidate_indices_by_edge.get(candidate_edge_id, ()))
    if teacher_lane_index in teacher_indices and candidate_indices:
        ordinal = teacher_indices.index(teacher_lane_index)
        return candidate_indices[min(ordinal, len(candidate_indices) - 1)]
    return min(teacher_lane_index, candidate_lane_counts.get(candidate_edge_id, 1) - 1)


def _edge_file_lane_counts(edge_file: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in ET.parse(edge_file).getroot().findall("edge"):
        edge_id = edge.attrib.get("id")
        if not edge_id:
            continue
        lanes = edge.findall("lane")
        if lanes:
            counts[edge_id] = len(lanes)
        elif edge.attrib.get("numLanes"):
            counts[edge_id] = max(1, int(edge.attrib["numLanes"]))
    return counts


def _edge_file_vehicle_lane_indices(edge_file: Path) -> dict[str, set[int]]:
    indices: dict[str, set[int]] = {}
    for edge in ET.parse(edge_file).getroot().findall("edge"):
        edge_id = edge.attrib.get("id")
        if not edge_id:
            continue
        lanes = edge.findall("lane")
        if lanes:
            indices[edge_id] = {
                int(lane.attrib.get("index", position))
                for position, lane in enumerate(lanes)
                if _sumo_allowed_classes({**edge.attrib, **lane.attrib}) & ROAD_MOTORIZED_CLASSES
            }
        elif edge.attrib.get("numLanes"):
            indices[edge_id] = set(range(max(1, int(edge.attrib["numLanes"]))))
    return indices


def _edge_file_lane_classes(edge_file: Path) -> dict[str, dict[int, set[str]]]:
    classes: dict[str, dict[int, set[str]]] = {}
    for edge in ET.parse(edge_file).getroot().findall("edge"):
        edge_id = edge.attrib.get("id")
        if not edge_id:
            continue
        lane_classes: dict[int, set[str]] = {}
        for position, lane in enumerate(edge.findall("lane")):
            try:
                lane_index = int(lane.attrib.get("index", position))
            except ValueError:
                continue
            lane_classes[lane_index] = _sumo_allowed_classes({**edge.attrib, **lane.attrib})
        if lane_classes:
            classes[edge_id] = lane_classes
    return classes


def _root_vehicle_lane_indices(root: ET.Element) -> dict[str, set[int]]:
    return {
        edge.attrib["id"]: {
            int(lane.attrib.get("index", position))
            for position, lane in enumerate(edge.findall("lane"))
            if _sumo_allowed_classes({**edge.attrib, **lane.attrib}) & ROAD_MOTORIZED_CLASSES
        }
        for edge in root.findall("edge")
        if edge.attrib.get("id") and not edge.attrib.get("function")
    }


def _net_lane_counts(root: ET.Element) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id")
        if edge_id:
            counts[edge_id] = max(1, len(edge.findall("lane")))
    return counts


def _connection_lane_indices_valid(connection: ET.Element, lane_counts: dict[str, int]) -> bool:
    def _valid(edge_id: str, lane_index: str) -> bool:
        try:
            index = int(lane_index or "0")
        except ValueError:
            return False
        return 0 <= index < lane_counts.get(edge_id, 0)

    return _valid(connection.attrib.get("from", ""), connection.attrib.get("fromLane", "0")) and _valid(
        connection.attrib.get("to", ""),
        connection.attrib.get("toLane", "0"),
    )


def _edge_is_pedestrian_only(edge: ET.Element) -> bool:
    lanes = edge.findall("lane")
    return bool(lanes) and all(set((lane.attrib.get("allow") or "").split()) == {"pedestrian"} for lane in lanes)


def _edge_is_vehicle_continuation_candidate(edge: ET.Element) -> bool:
    if edge.attrib.get("function") in {"internal", "crossing", "walkingarea"} or _edge_is_pedestrian_only(edge):
        return False
    edge_types = edge.attrib.get("type", "").split("|")
    return any(edge_type.startswith("highway.") for edge_type in edge_types) or any(
        set((lane.attrib.get("allow") or "").split())
        & {"passenger", "private", "bus", "coach", "truck", "motorcycle", "moped", "taxi", "delivery", "emergency"}
        for lane in edge.findall("lane")
    )


def _strict_teacher_structural_context(
    *,
    teacher_net_file: Path,
    candidate_net_file: Path,
    edge_map: dict[str, str],
    safety_junction_ids: set[str] | list[str] | tuple[str, ...],
) -> tuple[dict[str, str], set[str], list[str]]:
    """Extend strict replay to existing teacher edges at adjacent safety cells."""

    safety_ids = {str(value) for value in safety_junction_ids if str(value)}
    if not safety_ids:
        return dict(edge_map), set(), []
    teacher_root = ET.parse(teacher_net_file).getroot()
    candidate_root = ET.parse(candidate_net_file).getroot()
    teacher_edges = {
        edge.attrib.get("id", ""): edge
        for edge in teacher_root.findall("edge")
        if edge.attrib.get("id")
    }
    candidate_edge_ids = {
        edge.attrib.get("id", "")
        for edge in candidate_root.findall("edge")
        if edge.attrib.get("id")
    }
    candidate_lane_counts = {
        edge.attrib.get("id", ""): len(edge.findall("lane"))
        for edge in candidate_root.findall("edge")
        if edge.attrib.get("id")
    }
    resolved = dict(edge_map)
    mapped_candidate_ids = set(resolved.values())
    additions: list[str] = []
    for teacher_edge_id, teacher_edge in sorted(teacher_edges.items()):
        if (
            teacher_edge_id in resolved
            or teacher_edge_id not in candidate_edge_ids
            or teacher_edge_id.startswith(":")
            or not _edge_is_vehicle_continuation_candidate(teacher_edge)
            or not (
                teacher_edge.attrib.get("from", "") in safety_ids
                or teacher_edge.attrib.get("to", "") in safety_ids
            )
            or len(teacher_edge.findall("lane")) <= candidate_lane_counts.get(teacher_edge_id, 0)
            or teacher_edge_id in mapped_candidate_ids
        ):
            continue
        resolved[teacher_edge_id] = teacher_edge_id
        mapped_candidate_ids.add(teacher_edge_id)
        additions.append(teacher_edge_id)
    return resolved, safety_ids, additions


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
        desired_from = _mapped_junction_ref(
            teacher_edge.attrib.get("from", ""), teacher_junction_id, candidate_junction_id
        )
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


def _edge_lane_count(edge: ET.Element) -> int:
    return max(1, len(edge.findall("lane")))


def _edge_type_signature(edge: ET.Element) -> str:
    return edge.attrib.get("type", "")


def _command_path(path: Path, cwd: Path) -> str:
    try:
        return str(path.resolve().relative_to(cwd.resolve()))
    except ValueError:
        return str(path)


def _stage_file(output_dir: Path, prefix: str, suffix: str) -> Path:
    def candidate(name: str) -> Path | None:
        path = output_dir / name
        return path if len(str(path.resolve())) < 260 else None

    if path := candidate(f"{prefix}_{suffix}"):
        return path
    short_prefix = prefix[:16].strip("_") or "tg"
    if path := candidate(f"{short_prefix}_{suffix}"):
        return path
    if path := candidate(suffix):
        return path
    suffix_aliases = {
        "nodes.nod.xml": "n.nod.xml",
        "connections.con.xml": "c.con.xml",
        "lanes.edg.xml": "e.edg.xml",
        "sidewalks.net.xml": "sw.net.xml",
        "pedring.net.xml": "pr.net.xml",
        "vehicle_attrs.net.xml": "va.net.xml",
        "target_internal_replay.net.xml": "tir.net.xml",
        "target_internal_normalized.net.xml": "tin.net.xml",
        "target_internal_normalized_unrestored.net.xml": "tin_raw.net.xml",
        "target_internal_pedring.net.xml": "tip.net.xml",
        "target_internal_vehicle_attrs.net.xml": "tva.net.xml",
        "teacher_guided.net.xml": "tg.net.xml",
        "teacher_guided_fallback.net.xml": "tgfb.net.xml",
        "teacher_guided_report.json": "tgr.json",
    }
    return output_dir / suffix_aliases.get(suffix, suffix)


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
                lane.set("id", f"{candidate_prefix}{lane_id[len(teacher_prefix) :]}")
            elif lane.attrib.get("index"):
                lane.set("id", f"{candidate_prefix}{lane.attrib['index']}")
    return clone


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


def _primary_edge_shape(edge: ET.Element) -> str:
    if edge.attrib.get("shape"):
        return edge.attrib["shape"]
    lane = edge.find("lane")
    return lane.attrib.get("shape", "") if lane is not None else ""


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
        anchor_lane_shape = anchor_lane.attrib.get("shape", "") if anchor_lane is not None else anchor_edge_shape
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


def _preserve_boundary_operational_attributes(
    replayed_edge: ET.Element,
    source_edge: ET.Element,
) -> dict[str, object]:
    """Keep OSM road semantics while MAP/teacher owns only local topology.

    Official MAP evidence can authorize a lane-count expansion and the movement
    matrix, but it does not reclassify the complete boundary segment or restrict
    its vehicle classes.  Existing lanes retain their source operational fields;
    a newly added lane clones the nearest source lane's fields.
    """

    changed_edge_attrs = 0
    for attr in BOUNDARY_EDGE_OPERATIONAL_ATTRS:
        before = replayed_edge.attrib.get(attr)
        if attr in source_edge.attrib:
            replayed_edge.set(attr, source_edge.attrib[attr])
        else:
            replayed_edge.attrib.pop(attr, None)
        if before != replayed_edge.attrib.get(attr):
            changed_edge_attrs += 1

    source_lanes = {int(lane.attrib.get("index", "0") or 0): lane for lane in source_edge.findall("lane")}
    changed_lane_attrs = 0
    cloned_lane_indices: list[int] = []
    for replayed_lane in replayed_edge.findall("lane"):
        replayed_index = int(replayed_lane.attrib.get("index", "0") or 0)
        source_lane = source_lanes.get(replayed_index)
        if source_lane is None and source_lanes:
            source_index = min(source_lanes, key=lambda index: (abs(index - replayed_index), index))
            source_lane = source_lanes[source_index]
            cloned_lane_indices.append(replayed_index)
        if source_lane is None:
            continue
        for attr in BOUNDARY_LANE_OPERATIONAL_ATTRS:
            before = replayed_lane.attrib.get(attr)
            if attr in source_lane.attrib:
                replayed_lane.set(attr, source_lane.attrib[attr])
            else:
                replayed_lane.attrib.pop(attr, None)
            if before != replayed_lane.attrib.get(attr):
                changed_lane_attrs += 1
    return {
        "preserved_boundary_edge_operational_attr_count": changed_edge_attrs,
        "preserved_boundary_lane_operational_attr_count": changed_lane_attrs,
        "operational_attrs_cloned_to_new_lane_indices": sorted(cloned_lane_indices),
    }


def _restore_external_boundary_connections(
    *,
    source_root: ET.Element,
    target_root: ET.Element,
    boundary_edge_ids: set[str],
    source_local_junction_ids: set[str],
) -> dict[str, object]:
    """Restore only the source connections on the remote side of boundaries."""

    source_edges = {edge.attrib["id"]: edge for edge in source_root.findall("edge") if edge.attrib.get("id")}
    target_edge_ids = {edge.attrib["id"] for edge in target_root.findall("edge") if edge.attrib.get("id")}
    target_lane_counts = _net_lane_counts(target_root)
    target_lane_ids = {
        lane.attrib["id"]
        for edge in target_root.findall("edge")
        for lane in edge.findall("lane")
        if lane.attrib.get("id")
    }
    existing_keys = {tuple(sorted(connection.attrib.items())) for connection in target_root.findall("connection")}
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
        cumulative.append(cumulative[-1] + math.hypot(right_x - left_x, right_y - left_y))
    total = cumulative[-1]
    if total <= 1e-9:
        weights = [1.0 for _ in parsed]
    else:
        # The teacher owns the local conflict core, not the complete OSM
        # approach.  A full-edge linear warp can drag a lane across a nearby
        # junction.  Taper the correction inside a bounded local splice and
        # preserve the remote public-road geometry exactly.
        blend_extent = min(total, max(15.0, displacement * 4.0))
        distances_from_target = cumulative if target_at_start else [total - distance for distance in cumulative]
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


def _load_geometry_anchor_edges(edge_file: Path | None) -> dict[str, ET.Element]:
    if edge_file is None:
        return {}
    try:
        root = ET.parse(edge_file).getroot()
    except (ET.ParseError, OSError):
        return {}
    return {
        edge.attrib["id"]: copy.deepcopy(edge)
        for edge in root.findall("edge")
        if edge.attrib.get("id")
        and edge.attrib.get("function") != "internal"
        and (edge.attrib.get("shape") or any(lane.attrib.get("shape") for lane in edge.findall("lane")))
    }


def _load_geometry_anchor_edge_ids(edge_file: Path | None) -> set[str]:
    return set(_load_geometry_anchor_edges(edge_file))


def _geometry_anchor_junctions_by_id(
    candidate_edges_by_id: dict[str, ET.Element],
    candidate_junctions_by_id: dict[str, ET.Element],
    geometry_anchor_edge_ids: set[str],
    *,
    target_junction_id: str,
) -> dict[str, ET.Element]:
    anchored: dict[str, ET.Element] = {}
    for edge_id in geometry_anchor_edge_ids:
        edge = candidate_edges_by_id.get(edge_id)
        if edge is None:
            continue
        for endpoint_id in (edge.attrib.get("from", ""), edge.attrib.get("to", "")):
            if not endpoint_id or endpoint_id == target_junction_id:
                continue
            junction = candidate_junctions_by_id.get(endpoint_id)
            if junction is not None:
                anchored[endpoint_id] = copy.deepcopy(junction)
    return anchored


def _restore_geometry_anchor_junctions(
    root: ET.Element,
    geometry_anchor_junctions_by_id: dict[str, ET.Element],
) -> list[str]:
    restored = []
    for junction_id, source_junction in sorted(geometry_anchor_junctions_by_id.items()):
        junction = root.find(f"junction[@id='{junction_id}']")
        if junction is None:
            continue
        for attr in ("x", "y", "z", "shape"):
            if source_junction.attrib.get(attr):
                junction.set(attr, source_junction.attrib[attr])
            else:
                junction.attrib.pop(attr, None)
        restored.append(junction_id)
    return restored


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


def _shape_points(shape: str) -> list[tuple[float, float]]:
    points = []
    for point in _split(shape):
        try:
            x, y = point.split(",")[:2]
            points.append((float(x), float(y)))
        except ValueError:
            continue
    return points


def _polyline_length(shape: str) -> float | None:
    points = _shape_points(shape)
    if len(points) < 2:
        return None
    return sum(math.hypot(right[0] - left[0], right[1] - left[1]) for left, right in zip(points, points[1:]))


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return unique

    def cross(origin: tuple[float, float], left: tuple[float, float], right: tuple[float, float]) -> float:
        return (left[0] - origin[0]) * (right[1] - origin[1]) - (left[1] - origin[1]) * (right[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _join_shape_text(first: str, second: str) -> str:
    joined: list[str] = []
    for shape in (first, second):
        for point in _split(shape):
            if not joined or joined[-1] != point:
                joined.append(point)
    return " ".join(joined)


def _lanes_by_index(edge: ET.Element) -> dict[str, ET.Element]:
    return {lane.attrib.get("index", ""): lane for lane in edge.findall("lane") if lane.attrib.get("index", "")}


def _joined_lane_length(first_lane: ET.Element, second_lane: ET.Element) -> str | None:
    try:
        return f"{float(first_lane.attrib['length']) + float(second_lane.attrib['length']):.2f}"
    except (KeyError, ValueError):
        return None


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


def _junction_xy(root: ET.Element, junction_id: str) -> tuple[float, float] | None:
    junction = next((item for item in root.findall("junction") if item.attrib.get("id") == junction_id), None)
    if junction is None:
        return None
    try:
        return float(junction.attrib["x"]), float(junction.attrib["y"])
    except (KeyError, ValueError):
        return None


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
    for attr in ("id", "from", "to", "tl"):
        if attr in mapped:
            mapped[attr] = _canonical_sumo_cluster_id(mapped[attr])
    if "x" in mapped:
        mapped["x"] = _format_xy(float(mapped["x"]) + dx)
    if "y" in mapped:
        mapped["y"] = _format_xy(float(mapped["y"]) + dy)
    for attr in ("shape", "outlineShape", "customShape"):
        if attr in mapped:
            mapped[attr] = _translate_shape(mapped[attr], dx, dy)
    if "crossingEdges" in mapped:
        mapped_edges = [
            edge_map.get(
                edge,
                _map_internal_ref(edge, teacher_internal_prefix, candidate_internal_prefix)
                if edge.startswith(":")
                else "",
            )
            for edge in _split(mapped["crossingEdges"])
        ]
        mapped["crossingEdges"] = " ".join(edge for edge in mapped_edges if edge)
    return mapped


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
            if not edge_id or edge_id.startswith(teacher_internal_prefix) or edge_id in seen:
                continue
            teacher_edge = teacher_edges.get(edge_id)
            if teacher_edge is None:
                continue
            if teacher_junction_id not in (teacher_edge.attrib.get("from"), teacher_edge.attrib.get("to")):
                continue
            mapped_from = (
                candidate_junction_id
                if teacher_edge.attrib.get("from") == teacher_junction_id
                else teacher_edge.attrib.get("from", "")
            )
            mapped_to = (
                candidate_junction_id
                if teacher_edge.attrib.get("to") == teacher_junction_id
                else teacher_edge.attrib.get("to", "")
            )
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
    mapped_from = (
        candidate_junction_id
        if teacher_edge.attrib.get("from") == teacher_junction_id
        else teacher_edge.attrib.get("from", "")
    )
    mapped_to = (
        candidate_junction_id
        if teacher_edge.attrib.get("to") == teacher_junction_id
        else teacher_edge.attrib.get("to", "")
    )
    candidate_edge = candidate_edges_by_id.get(edge_map.get(edge_id, edge_id))
    return not (
        candidate_edge is not None
        and candidate_edge.attrib.get("from") == mapped_from
        and candidate_edge.attrib.get("to") == mapped_to
        and candidate_edge.attrib.get("type", "") == teacher_edge.attrib.get("type", "")
        and _edge_lane_semantic_attrs(candidate_edge) == _edge_lane_semantic_attrs(teacher_edge)
        and _edge_lane_shapes(candidate_edge) == _translated_edge_lane_shapes(teacher_edge, dx, dy)
    )


def _edge_lane_semantic_attrs(edge: ET.Element) -> list[tuple[str, ...]]:
    attrs = ("index", "allow", "disallow", "speed", "width")
    return [tuple(lane.attrib.get(attr, "") for attr in attrs) for lane in edge.findall("lane")]


def _edge_lane_shapes(edge: ET.Element) -> list[str]:
    shapes = (lane.attrib.get("shape", "") for lane in edge.findall("lane"))
    return [_translate_shape(shape, 0.0, 0.0) if shape else "" for shape in shapes]


def _translated_edge_lane_shapes(edge: ET.Element, dx: float, dy: float) -> list[str]:
    return [_translate_shape(shape, dx, dy) if shape else "" for shape in _edge_lane_shapes(edge)]


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


def _prune_unmapped_micro_boundary_edges(
    root: ET.Element,
    *,
    junction_id: str,
    mapped_candidate_edge_ids: set[str],
) -> dict[str, object]:
    """Drop OSM-only motorized stubs that cannot carry a teacher movement."""

    max_length_m = 5.0
    edges_by_id = {
        edge.attrib["id"]: edge
        for edge in root.findall("edge")
        if edge.attrib.get("id") and not edge.attrib.get("function") and not edge.attrib["id"].startswith(":")
    }
    boundary_edges = {
        edge_id: edge
        for edge_id, edge in edges_by_id.items()
        if junction_id in (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
    }

    def motorized_length(edge: ET.Element) -> float | None:
        lengths = []
        for lane in edge.findall("lane"):
            if not (_sumo_allowed_classes({**edge.attrib, **lane.attrib}) & ROAD_MOTORIZED_CLASSES):
                continue
            try:
                length = float(lane.attrib.get("length", ""))
            except (TypeError, ValueError):
                return None
            if math.isfinite(length):
                lengths.append(length)
        return min(lengths) if lengths else None

    unmapped_short = {
        edge_id
        for edge_id, edge in boundary_edges.items()
        if edge_id not in mapped_candidate_edge_ids
        and (length := motorized_length(edge)) is not None
        and length <= max_length_m
    }
    if not unmapped_short:
        return {
            "status": "pass",
            "policy": "strict replay only: remove unmapped motorized boundary edges <= 5m when they only connect to other unmapped short edges",
            "max_length_m": max_length_m,
            "removed_edge_ids": [],
            "removed_connection_count": 0,
        }

    protected = set()
    for connection in root.findall("connection"):
        endpoints = {connection.attrib.get("from", ""), connection.attrib.get("to", "")}
        short_edge_ids = endpoints & unmapped_short
        if not short_edge_ids:
            continue
        other_edge_ids = endpoints - short_edge_ids
        if any(
            edge_id in boundary_edges
            and edge_id not in unmapped_short
            and motorized_length(boundary_edges[edge_id]) is not None
            for edge_id in other_edge_ids
        ):
            protected.update(short_edge_ids)

    removed_edge_ids = sorted(unmapped_short - protected)
    removed_connections = 0
    removed_edge_set = set(removed_edge_ids)
    for connection in list(root.findall("connection")):
        if {
            connection.attrib.get("from", ""),
            connection.attrib.get("to", ""),
        } & removed_edge_set:
            root.remove(connection)
            removed_connections += 1
    for edge_id in removed_edge_ids:
        edge = edges_by_id[edge_id]
        _remove_edge_lanes_from_destination_junction(root, edge, all_junctions=True)
        root.remove(edge)
    return {
        "status": "pass",
        "policy": "strict replay only: remove unmapped motorized boundary edges <= 5m when they only connect to other unmapped short edges",
        "max_length_m": max_length_m,
        "removed_edge_ids": removed_edge_ids,
        "removed_connection_count": removed_connections,
        "protected_edge_ids": sorted(protected),
    }


def _teacher_cluster_ids_for_join_groups(
    join_groups: object,
    teacher_join_groups_by_cluster: Mapping[str, Sequence[str]] | None,
    scope_junction_ids: Sequence[str] = (),
) -> list[str]:
    joined_member_sets = {
        frozenset(str(item) for item in group if str(item))
        for group in (join_groups if isinstance(join_groups, list) else [])
        if isinstance(group, list)
    }
    known_groups = {
        str(cluster_id): frozenset(str(item) for item in members if str(item))
        for cluster_id, members in (teacher_join_groups_by_cluster or {}).items()
    }
    known_groups.update(
        {
            str(cluster_id): frozenset(_sumo_cluster_member_ids(str(cluster_id)))
            for cluster_id in scope_junction_ids
            if str(cluster_id).startswith("cluster_")
        }
    )
    return sorted(cluster_id for cluster_id, members in known_groups.items() if members in joined_member_sets)


def _prune_strict_unmapped_outgoing_boundary_edges(
    root: ET.Element,
    *,
    junction_id: str,
    mapped_candidate_edge_ids: set[str],
    teacher_edge_ids: set[str] | None = None,
) -> dict[str, object]:
    """Remove modal outgoing approaches that have no teacher movement mapping."""

    edges_by_id = {
        edge.attrib["id"]: edge
        for edge in root.findall("edge")
        if edge.attrib.get("id")
        and not edge.attrib["id"].startswith(":")
        and not edge.attrib.get("function")
    }
    candidate_edge_ids = set(mapped_candidate_edge_ids)
    teacher_family_ids = {_edge_family_id(edge_id) for edge_id in teacher_edge_ids or set()}
    removable_edge_ids = []
    for edge_id, edge in edges_by_id.items():
        if edge_id in candidate_edge_ids or edge.attrib.get("from") != junction_id:
            continue
        lane_classes = set().union(
            *(
                _sumo_allowed_classes({**edge.attrib, **lane.attrib})
                for lane in edge.findall("lane")
            )
        ) if edge.findall("lane") else set()
        if not lane_classes or lane_classes & ROAD_MOTORIZED_CLASSES or "bicycle" not in lane_classes:
            continue
        if not any(connection.attrib.get("from") == edge_id for connection in root.findall("connection")):
            continue
        removable_edge_ids.append(edge_id)

    for edge_id, edge in edges_by_id.items():
        if edge_id in candidate_edge_ids or edge.attrib.get("from") != junction_id:
            continue
        reverse_edge_id = edge_id.removeprefix("-") if edge_id.startswith("-") else f"-{edge_id}"
        reverse_edge = edges_by_id.get(reverse_edge_id)
        family_id = _edge_family_id(edge_id)
        if (
            not teacher_edge_ids
            or edge_id in teacher_edge_ids
            or reverse_edge_id in teacher_edge_ids
            or family_id not in teacher_family_ids
            or reverse_edge is None
            or reverse_edge_id in candidate_edge_ids
            or reverse_edge.attrib.get("from") != edge.attrib.get("to")
            or reverse_edge.attrib.get("to") != junction_id
        ):
            continue
        removable_edge_ids.extend((edge_id, reverse_edge_id))

    removed_connection_count = 0
    removable_edge_ids = sorted(set(removable_edge_ids))
    removable = set(removable_edge_ids)
    for connection in list(root.findall("connection")):
        if {connection.attrib.get("from", ""), connection.attrib.get("to", "")} & removable:
            root.remove(connection)
            removed_connection_count += 1
    for edge_id in removable_edge_ids:
        edge = edges_by_id[edge_id]
        _remove_edge_lanes_from_destination_junction(root, edge, all_junctions=True)
        root.remove(edge)
    return {
        "status": "pass",
        "policy": "strict replay only: remove unmapped non-motorized outgoing boundary edges with movement evidence absent from the teacher",
        "removed_edge_ids": sorted(removable_edge_ids),
        "removed_connection_count": removed_connection_count,
    }


def _first_junction_index(root: ET.Element) -> int:
    for index, child in enumerate(list(root)):
        if child.tag == "junction":
            return index
    return len(list(root))


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


def _map_internal_ref(value: str, teacher_internal_prefix: str, candidate_internal_prefix: str) -> str:
    if teacher_internal_prefix and candidate_internal_prefix and value.startswith(teacher_internal_prefix):
        return f"{candidate_internal_prefix}{value[len(teacher_internal_prefix) :]}"
    return value


def _touches_target_internal_subgraph(connection: ET.Element, internal_prefix: str, junction_id: str) -> bool:
    return (
        connection.attrib.get("from", "").startswith(internal_prefix)
        or connection.attrib.get("to", "").startswith(internal_prefix)
        or connection.attrib.get("via", "").startswith(internal_prefix)
        or connection.attrib.get("tl", "") == junction_id
    )


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


def _touches_target_internal_owner(connection: ET.Element, internal_prefix: str) -> bool:
    return any(connection.attrib.get(attr, "").startswith(internal_prefix) for attr in ("from", "to", "via"))


def _touches_other_internal_owner(connection: ET.Element, internal_prefix: str) -> bool:
    return any(
        value.startswith(":") and not value.startswith(internal_prefix)
        for value in (connection.attrib.get(attr, "") for attr in ("from", "to", "via"))
        if value
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
    geometry_anchor_junction_ids: set[str] | None = None,
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
    inside one alias target.  ``geometry_anchor_junction_ids`` restores only
    x/y/z/shape for mutable boundary junctions whose connections must remain
    regenerated after a lane-cardinality change.
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
    effective_mutable_junction_ids = {str(value) for value in mutable_junction_ids if str(value)}
    declared_mutable_junction_ids = set(effective_mutable_junction_ids)
    effective_mutable_junction_ids.update(normalized_junction_aliases)
    effective_mutable_junction_ids.update(normalized_junction_aliases.values())
    effective_mutable_edge_ids = {str(value) for value in mutable_edge_ids if str(value)}
    if expand_mutable_edge_endpoints:
        effective_mutable_edge_ids.update(
            edge_id
            for edge_id, edge in source_edges.items()
            if {
                edge.attrib.get("from", ""),
                edge.attrib.get("to", ""),
            }
            & declared_mutable_junction_ids
        )
        for edge_id in sorted(effective_mutable_edge_ids):
            for edge in (source_edges.get(edge_id), target_edges.get(edge_id)):
                if edge is None:
                    continue
                effective_mutable_junction_ids.update(
                    value for value in (edge.attrib.get("from", ""), edge.attrib.get("to", "")) if value
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
    source_junctions = {
        junction.attrib["id"]: junction
        for junction in source_root.findall("junction")
        if junction.attrib.get("id")
    }
    geometry_anchor_ids = {
        str(value) for value in (geometry_anchor_junction_ids or set()) if str(value)
    }
    restored_geometry_anchor_junction_ids = _restore_geometry_anchor_junctions(
        target_root,
        {
            junction_id: source_junctions[junction_id]
            for junction_id in geometry_anchor_ids
            if junction_id in source_junctions
        },
    )
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
            normalized_junction_aliases.get(endpoint, endpoint) for endpoint in source_endpoints
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
                    endpoint and endpoint in effective_mutable_junction_ids for endpoint in source_endpoints
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
                            edge_id in expected_absorbed_edge_ids if expected_absorbed_edge_ids is not None else None
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
        source_lanes = {lane.attrib.get("index", ""): lane for lane in source_edge.findall("lane")}
        target_lanes = {lane.attrib.get("index", ""): lane for lane in target_edge.findall("lane")}
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
            lane_index: {attr: target_lane.attrib.get(attr) for attr in GEOMETRY_RESTORE_LANE_ATTRS}
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

    unauthorized_added_edge_ids = sorted(
        edge_id for edge_id in target_edges.keys() - source_edges.keys() if edge_id not in effective_mutable_edge_ids
    )
    failures.extend(
        {
            "edge_id": edge_id,
            "reason": "off_scope_edge_added",
            "target_endpoints": (
                target_edges[edge_id].attrib.get("from", ""),
                target_edges[edge_id].attrib.get("to", ""),
            ),
        }
        for edge_id in unauthorized_added_edge_ids
    )

    undeleted_declared_absorbed_edge_ids: list[str] = []
    if expected_absorbed_edge_ids is not None:
        undeleted_declared_absorbed_edge_ids = sorted(expected_absorbed_edge_ids - set(authorized_absorbed_edge_ids))
        failures.extend(
            {
                "edge_id": edge_id,
                "reason": "declared_absorbed_edge_not_absorbed",
            }
            for edge_id in undeleted_declared_absorbed_edge_ids
        )

    if restored_lane_count or restored_edge_centerline_ids or restored_geometry_anchor_junction_ids:
        ET.indent(target_root, space="    ")
        target_tree.write(target_file, encoding="utf-8", xml_declaration=True)

    internal_failures = {
        key: int(internal_report.get(key, 0) or 0)
        for key in (
            "skipped_non_target_internal_edge_missing_junction_count",
            "skipped_non_target_internal_connection_missing_edge_count",
            "skipped_non_target_internal_connection_invalid_lane_count",
            "skipped_non_target_internal_connection_missing_via_lane_count",
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
            sorted(expected_absorbed_edge_ids) if expected_absorbed_edge_ids is not None else None
        ),
        "expanded_mutable_edge_endpoints": expand_mutable_edge_endpoints,
        "authorized_absorbed_external_edge_ids": authorized_absorbed_edge_ids,
        "unauthorized_added_external_edge_ids": unauthorized_added_edge_ids,
        "undeleted_declared_absorbed_edge_ids": undeleted_declared_absorbed_edge_ids,
        "restored_join_boundary_edge_count": len(restored_join_boundary_edge_ids),
        "restored_join_boundary_edge_ids": restored_join_boundary_edge_ids,
        "restored_external_edge_count": len(restored_edge_ids),
        "restored_external_edge_ids": restored_edge_ids,
        "restored_external_edge_centerline_count": len(restored_edge_centerline_ids),
        "restored_external_edge_centerline_ids": restored_edge_centerline_ids,
        "restored_external_lane_count": restored_lane_count,
        "restored_geometry_anchor_junction_ids": restored_geometry_anchor_junction_ids,
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
            valid_scalars = all(
                math.isfinite(float(attrs[attr])) and float(attrs[attr]) > 0 for attr in ("speed", "length")
            )
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
    changed_invariants = sorted(key for key, before in invariants_before.items() if invariants_after.get(key) != before)
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

    missing = [str(path) for path in (candidate_net_file, evidence_net_file) if path is not None and not path.exists()]
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
    all_edge_ids = {edge.attrib.get("id", "") for edge in candidate_root.findall("edge") if edge.attrib.get("id")}
    for junction_id in sorted(str(value) for value in junction_ids if str(value)):
        candidate_estimate = _estimate_linear_lane_transition_shape(candidate_root, junction_id)
        evidence_estimate = _estimate_linear_lane_transition_shape(evidence_root, junction_id)
        excluded_branch_edge_ids = sorted(
            {str(value) for value in excluded_branch_edge_ids_by_junction.get(junction_id, []) if str(value)}
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

    missing = [str(path) for path in (candidate_net_file, reference_net_file) if not path.exists()]
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
            attr: candidate_junction.attrib.get(attr, "") for attr in selected_junction_identity_attrs
        }
        reference_identity = {
            attr: reference_junction.attrib.get(attr, "") for attr in selected_junction_identity_attrs
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
    source_network_mutation = candidate_sha256_after != candidate_sha256 or reference_sha256_after != reference_sha256
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
        connection for connection in root.findall("connection") if connection.attrib.get("from") == incoming_edge_id
    ]
    straight_connections = [
        connection
        for connection in relevant_connections
        if connection.attrib.get("to") == outgoing_edge_id
        and connection.attrib.get("dir", "s") == "s"
        and not connection.attrib.get("tl")
    ]
    if len(straight_connections) != min(len(incoming_lanes), len(outgoing_lanes)) or len(straight_connections) != len(
        relevant_connections
    ):
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


def _polygon_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    return (
        abs(sum(left[0] * right[1] - right[0] * left[1] for left, right in zip(points, [*points[1:], points[0]]))) / 2.0
    )


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


def _contraction_modal_preservation_deltas(
    report: Mapping[str, object],
) -> dict[str, int]:
    raw_deltas = report.get("semantic_preservation_deltas", {})
    if not isinstance(raw_deltas, Mapping):
        return {}
    return {
        field: int(raw_deltas.get(field, 0) or 0)
        for field in ("crossing_edge_count", "walkingarea_edge_count")
        if int(raw_deltas.get(field, 0) or 0)
    }


def _restore_contraction_neighbor_modal_edges(
    *,
    source_file: Path,
    target_file: Path,
    junction_ids: set[str],
    edge_aliases: dict[str, str],
) -> dict[str, object]:
    source_root = ET.parse(source_file).getroot()
    target_tree = ET.parse(target_file)
    target_root = target_tree.getroot()
    target_edge_ids = {
        edge.attrib.get("id", "") for edge in target_root.findall("edge") if edge.attrib.get("id")
    }
    source_edge_ids: set[str] = set()
    restored_edge_ids: list[str] = []
    for junction_id in sorted(junction_ids):
        owner_prefix = f":{junction_id}_"
        for source_edge in source_root.findall("edge"):
            edge_id = source_edge.attrib.get("id", "")
            if (
                not edge_id.startswith(owner_prefix)
                or source_edge.attrib.get("function") not in {"crossing", "walkingarea"}
            ):
                continue
            source_edge_ids.add(edge_id)
            if edge_id in target_edge_ids:
                continue
            copied = copy.deepcopy(source_edge)
            if copied.attrib.get("function") == "crossing":
                copied.set(
                    "crossingEdges",
                    " ".join(edge_aliases.get(edge_id, edge_id) for edge_id in copied.attrib.get("crossingEdges", "").split()),
                )
            target_root.append(copied)
            target_edge_ids.add(edge_id)
            restored_edge_ids.append(edge_id)
    if restored_edge_ids:
        ET.indent(target_root, space="    ")
        target_tree.write(target_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "junction_ids": sorted(junction_ids),
        "source_edge_ids": sorted(source_edge_ids),
        "restored_edge_ids": sorted(restored_edge_ids),
        "restored_edge_count": len(restored_edge_ids),
    }


def _restore_contraction_edge_alias_connections(
    *,
    source_file: Path,
    target_file: Path,
    edge_aliases: dict[str, str],
    source_modal_edge_ids: set[str] | None = None,
    source_boundary_edge_ids: set[str] | None = None,
) -> dict[str, object]:
    source_root = ET.parse(source_file).getroot()
    target_tree = ET.parse(target_file)
    target_root = target_tree.getroot()
    target_edge_ids = {
        edge.attrib.get("id", "") for edge in target_root.findall("edge") if edge.attrib.get("id")
    }
    target_lane_ids = {
        lane.attrib.get("id", "")
        for edge in target_root.findall("edge")
        for lane in edge.findall("lane")
        if lane.attrib.get("id")
    }
    modal_ids = source_modal_edge_ids or set()
    boundary_ids = source_boundary_edge_ids or set()

    def key(connection: ET.Element) -> tuple[str, ...]:
        return tuple(connection.attrib.get(field, "") for field in ("from", "to", "fromLane", "toLane", "via"))

    target_by_key = {key(connection): connection for connection in target_root.findall("connection")}
    target_by_base_key: dict[tuple[str, ...], list[ET.Element]] = {}
    for connection in target_root.findall("connection"):
        base_key = tuple(
            connection.attrib.get(field, "") for field in ("from", "to", "fromLane", "toLane")
        )
        target_by_base_key.setdefault(base_key, []).append(connection)
    restored_count = 0
    skipped_count = 0
    for source_connection in source_root.findall("connection"):
        source_from = source_connection.attrib.get("from", "")
        source_to = source_connection.attrib.get("to", "")
        if not (
            source_from in edge_aliases
            or source_to in edge_aliases
            or source_from in modal_ids
            or source_to in modal_ids
            or source_from in boundary_ids
            or source_to in boundary_ids
        ):
            continue
        attrs = dict(source_connection.attrib)
        attrs["from"] = edge_aliases.get(source_from, source_from)
        attrs["to"] = edge_aliases.get(source_to, source_to)
        if attrs["from"] not in target_edge_ids or attrs["to"] not in target_edge_ids:
            skipped_count += 1
            continue
        via = attrs.get("via", "")
        if via and via not in target_lane_ids:
            matching_targets = target_by_base_key.get(
                tuple(attrs.get(field, "") for field in ("from", "to", "fromLane", "toLane")),
                [],
            )
            if len(matching_targets) != 1 or not matching_targets[0].attrib.get("via"):
                skipped_count += 1
                continue
            attrs["via"] = matching_targets[0].attrib["via"]
        mapped_key = key(ET.Element("connection", attrs))
        existing = target_by_key.get(mapped_key)
        base_key = tuple(attrs.get(field, "") for field in ("from", "to", "fromLane", "toLane"))
        stale_connections = [connection for connection in target_by_base_key.get(base_key, []) if connection is not existing]
        if stale_connections:
            for stale in stale_connections:
                target_root.remove(stale)
                target_by_key.pop(key(stale), None)
            target_by_base_key[base_key] = [connection for connection in target_by_base_key.get(base_key, []) if connection not in stale_connections]
            existing = None
        if existing is None:
            existing = ET.Element("connection", attrs)
            target_root.append(existing)
            target_by_key[mapped_key] = existing
            target_by_base_key.setdefault(base_key, []).append(existing)
            restored_count += 1
            continue
        if existing.attrib != attrs:
            existing.attrib.clear()
            existing.attrib.update(attrs)
            restored_count += 1
    if restored_count:
        ET.indent(target_root, space="    ")
        target_tree.write(target_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "edge_alias_count": len(edge_aliases),
        "restored_connection_count": restored_count,
        "skipped_connection_count": skipped_count,
    }


def _audit_contraction_modal_preservation(
    source_file: Path,
    target_file: Path,
) -> dict[str, object]:
    try:
        roots = [ET.parse(path).getroot() for path in (source_file, target_file)]
    except (ET.ParseError, OSError) as exc:
        return {
            "status": "fail",
            "error": f"{type(exc).__name__}: {exc}",
        }
    functions = ("crossing", "walkingarea")
    counts = [
        Counter(
            edge.attrib.get("function", "")
            for edge in root.findall("edge")
            if edge.attrib.get("function") in functions
        )
        for root in roots
    ]
    deltas = {
        function: counts[1][function] - counts[0][function]
        for function in functions
        if counts[1][function] != counts[0][function]
    }
    return {
        "status": "pass" if not deltas else "fail",
        "source_counts": {function: counts[0][function] for function in functions},
        "target_counts": {function: counts[1][function] for function in functions},
        "deltas": deltas,
    }


def _normalized_junction_request_model(
    root: ET.Element,
    junction_id: str,
    edge_aliases: dict[str, str],
) -> dict[str, object]:
    junction = root.find(f"junction[@id='{junction_id}']")
    if junction is None:
        return {
            "junction": None,
            "lane_keys": [],
            "rows": {},
            "failures": [
                {
                    "reason": "contraction_neighbor_junction_missing",
                    "junction_id": junction_id,
                }
            ],
        }

    internal_lanes = junction.attrib.get("intLanes", "").split()
    connections = list(root.findall("connection"))
    edges_by_id = {edge.attrib["id"]: edge for edge in root.findall("edge") if edge.attrib.get("id")}
    lane_locations = {
        lane.attrib["id"]: (edge, lane)
        for edge in edges_by_id.values()
        for lane in edge.findall("lane")
        if lane.attrib.get("id")
    }

    def normalized_edge_id(edge_id: str) -> str:
        return edge_aliases.get(edge_id, edge_id)

    def crossing_anchor(edge: ET.Element) -> str | None:
        crossed_edges = sorted(
            normalized_edge_id(edge_id) for edge_id in edge.attrib.get("crossingEdges", "").split() if edge_id
        )
        if not crossed_edges:
            return None
        return json.dumps(
            ["crossing", crossed_edges],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def modal_endpoint_anchor(edge_id: str, lane_index: str) -> str | None:
        edge = edges_by_id.get(edge_id)
        if edge is None:
            return None
        function = edge.attrib.get("function", "")
        if function == "crossing":
            anchor = crossing_anchor(edge)
            return f"crossing:{lane_index}:{anchor}" if anchor else None
        if function in {"walkingarea", "internal"} or edge_id.startswith(":"):
            return None
        return json.dumps(
            ["normal", normalized_edge_id(edge_id), lane_index],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def modal_lane_key(lane_id: str) -> tuple[str, ...] | None:
        location = lane_locations.get(lane_id)
        if location is None:
            return None
        edge, lane = location
        function = edge.attrib.get("function", "")
        lane_index = lane.attrib.get("index", "0")
        if function == "crossing":
            anchor = crossing_anchor(edge)
            return (
                (
                    "__torii_modal_internal__",
                    "crossing",
                    lane_index,
                    anchor,
                )
                if anchor
                else None
            )
        if function != "walkingarea":
            return None

        edge_id = edge.attrib.get("id", "")
        anchors: set[str] = set()
        for connection in connections:
            if connection.attrib.get("from", "") == edge_id and connection.attrib.get("fromLane", "0") == lane_index:
                anchor = modal_endpoint_anchor(
                    connection.attrib.get("to", ""),
                    connection.attrib.get("toLane", "0"),
                )
                if anchor:
                    anchors.add(f"out:{anchor}")
            if connection.attrib.get("to", "") == edge_id and connection.attrib.get("toLane", "0") == lane_index:
                anchor = modal_endpoint_anchor(
                    connection.attrib.get("from", ""),
                    connection.attrib.get("fromLane", "0"),
                )
                if anchor:
                    anchors.add(f"in:{anchor}")
        if not anchors:
            return None
        return (
            "__torii_modal_internal__",
            "walkingarea",
            lane_index,
            *sorted(anchors),
        )

    keys_by_via: dict[str, set[tuple[str, ...]]] = {}
    for connection in connections:
        from_edge = connection.attrib.get("from", "")
        to_edge = connection.attrib.get("to", "")
        via_lane = connection.attrib.get("via", "")
        if (
            not from_edge
            or not to_edge
            or from_edge.startswith(":")
            or to_edge.startswith(":")
            or via_lane not in internal_lanes
        ):
            continue
        mapped_from = edge_aliases.get(from_edge, from_edge)
        mapped_to = edge_aliases.get(to_edge, to_edge)
        if mapped_from == mapped_to:
            continue
        keys_by_via.setdefault(via_lane, set()).add(
            (
                mapped_from,
                mapped_to,
                connection.attrib.get("fromLane", ""),
                connection.attrib.get("toLane", ""),
                connection.attrib.get("tl", ""),
                connection.attrib.get("linkIndex", ""),
                connection.attrib.get("linkIndex2", ""),
                connection.attrib.get("dir", ""),
            )
        )

    failures: list[dict[str, object]] = []
    lane_keys: list[tuple[str, ...] | None] = []
    for lane_id in internal_lanes:
        keys = keys_by_via.get(lane_id, set())
        if not keys:
            modal_key = modal_lane_key(lane_id)
            if modal_key is not None:
                keys = {modal_key}
        if len(keys) > 1:
            failures.append(
                {
                    "reason": "contraction_neighbor_request_lane_ambiguous",
                    "junction_id": junction_id,
                    "lane_id": lane_id,
                    "movement_count": len(keys),
                }
            )
        lane_keys.append(next(iter(keys)) if len(keys) == 1 else None)
    duplicate_lane_keys = {
        key: count for key, count in Counter(key for key in lane_keys if key is not None).items() if count > 1
    }
    failures.extend(
        {
            "reason": "contraction_neighbor_request_movement_not_unique",
            "junction_id": junction_id,
            "movement": movement,
            "lane_count": count,
        }
        for movement, count in sorted(duplicate_lane_keys.items())
    )

    requests = junction.findall("request")
    if len(requests) != len(internal_lanes):
        failures.append(
            {
                "reason": "contraction_neighbor_request_count_invalid",
                "junction_id": junction_id,
                "request_count": len(requests),
                "internal_lane_count": len(internal_lanes),
            }
        )
    rows: dict[tuple[str, ...], dict[str, object]] = {}
    for request in requests:
        try:
            row_index = int(request.attrib.get("index", ""))
        except ValueError:
            row_index = -1
        if row_index < 0 or row_index >= len(lane_keys):
            failures.append(
                {
                    "reason": "contraction_neighbor_request_index_invalid",
                    "junction_id": junction_id,
                    "request_index": request.attrib.get("index", ""),
                }
            )
            continue
        row_key = lane_keys[row_index]
        if row_key is None:
            continue
        row = rows.setdefault(
            row_key,
            {
                "cont": request.attrib.get("cont", "0"),
                "response": set(),
                "foes": set(),
            },
        )
        if row["cont"] != request.attrib.get("cont", "0"):
            failures.append(
                {
                    "reason": "contraction_neighbor_request_cont_ambiguous",
                    "junction_id": junction_id,
                    "movement": row_key,
                }
            )
        for attr in ("response", "foes"):
            bits = request.attrib.get(attr, "")
            if len(bits) != len(lane_keys) or set(bits) - {"0", "1"}:
                failures.append(
                    {
                        "reason": "contraction_neighbor_request_bits_invalid",
                        "junction_id": junction_id,
                        "request_index": row_index,
                        "attribute": attr,
                        "actual_width": len(bits),
                        "expected_width": len(lane_keys),
                    }
                )
                continue
            related = row[attr]
            assert isinstance(related, set)
            for position, bit in enumerate(bits):
                if bit != "1":
                    continue
                related_key = lane_keys[len(bits) - 1 - position]
                if related_key is not None:
                    related.add(related_key)
    return {
        "junction": junction,
        "lane_keys": lane_keys,
        "rows": rows,
        "failures": failures,
    }


def _request_semantics_sha256(rows: dict[tuple[str, ...], dict[str, object]]) -> str:
    payload = [
        {
            "movement": movement,
            "cont": row["cont"],
            "response": sorted(row["response"]),
            "foes": sorted(row["foes"]),
        }
        for movement, row in sorted(rows.items())
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _restore_contraction_neighbor_requests(
    *,
    source_file: Path,
    target_file: Path,
    junction_ids: set[str],
    edge_aliases: dict[str, str],
) -> dict[str, object]:
    source_root = ET.parse(source_file).getroot()
    target_tree = ET.parse(target_file)
    target_root = target_tree.getroot()
    failures: list[dict[str, object]] = []
    restored_request_count = 0
    for junction_id in sorted(junction_ids):
        source_model = _normalized_junction_request_model(
            source_root,
            junction_id,
            edge_aliases,
        )
        target_model = _normalized_junction_request_model(
            target_root,
            junction_id,
            {},
        )
        failures.extend(source_model["failures"])
        failures.extend(target_model["failures"])
        if source_model["failures"] or target_model["failures"]:
            continue
        source_rows = source_model["rows"]
        target_rows = target_model["rows"]
        assert isinstance(source_rows, dict)
        assert isinstance(target_rows, dict)
        if source_rows.keys() != target_rows.keys():
            failures.append(
                {
                    "reason": "contraction_neighbor_movement_set_changed",
                    "junction_id": junction_id,
                    "source_movement_count": len(source_rows),
                    "target_movement_count": len(target_rows),
                }
            )
            continue
        target_junction = target_model["junction"]
        target_lane_keys = target_model["lane_keys"]
        assert isinstance(target_junction, ET.Element)
        assert isinstance(target_lane_keys, list)
        if any(key is None for key in target_lane_keys):
            continue
        target_indices = {key: index for index, key in enumerate(target_lane_keys) if key is not None}
        if len(target_indices) != len(target_lane_keys):
            failures.append(
                {
                    "reason": "contraction_neighbor_target_movement_not_unique",
                    "junction_id": junction_id,
                }
            )
            continue
        new_request_attrs: list[dict[str, str]] = []
        for index, movement in enumerate(target_lane_keys):
            assert movement is not None
            row = source_rows[movement]
            attrs = {
                "index": str(index),
                "response": "0" * len(target_lane_keys),
                "foes": "0" * len(target_lane_keys),
                "cont": str(row["cont"]),
            }
            for attr in ("response", "foes"):
                bits = ["0"] * len(target_lane_keys)
                related = row[attr]
                assert isinstance(related, set)
                for related_movement in related:
                    related_index = target_indices.get(related_movement)
                    if related_index is not None:
                        bits[len(bits) - 1 - related_index] = "1"
                attrs[attr] = "".join(bits)
            new_request_attrs.append(attrs)
        old_request_attrs = [dict(request.attrib) for request in target_junction.findall("request")]
        if old_request_attrs == new_request_attrs:
            continue
        for request in list(target_junction.findall("request")):
            target_junction.remove(request)
        for attrs in new_request_attrs:
            target_junction.append(ET.Element("request", attrs))
        restored_request_count += len(new_request_attrs)
    if failures:
        return {
            "status": "fail",
            "junction_ids": sorted(junction_ids),
            "restored_request_count": 0,
            "failure_count": len(failures),
            "failures": failures,
        }
    if restored_request_count:
        ET.indent(target_root, space="    ")
        target_tree.write(target_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "junction_ids": sorted(junction_ids),
        "restored_request_count": restored_request_count,
        "failure_count": 0,
        "failures": [],
    }


def _audit_contraction_neighbor_semantics(
    *,
    source_file: Path,
    target_file: Path,
    junction_ids: set[str],
    edge_aliases: dict[str, str],
) -> dict[str, object]:
    source_root = ET.parse(source_file).getroot()
    target_root = ET.parse(target_file).getroot()
    source_tls_sha256 = _junction_shape_tls_sha256(source_root)
    target_tls_sha256 = _junction_shape_tls_sha256(target_root)
    failures: list[dict[str, object]] = []
    if source_tls_sha256 != target_tls_sha256:
        failures.append(
            {
                "reason": "tllogic_semantics_changed",
                "source_tls_sha256": source_tls_sha256,
                "target_tls_sha256": target_tls_sha256,
            }
        )
    request_semantics: dict[str, dict[str, str]] = {}
    for junction_id in sorted(junction_ids):
        source_model = _normalized_junction_request_model(
            source_root,
            junction_id,
            edge_aliases,
        )
        target_model = _normalized_junction_request_model(
            target_root,
            junction_id,
            {},
        )
        failures.extend(source_model["failures"])
        failures.extend(target_model["failures"])
        source_rows = source_model["rows"]
        target_rows = target_model["rows"]
        assert isinstance(source_rows, dict)
        assert isinstance(target_rows, dict)
        source_sha256 = _request_semantics_sha256(source_rows)
        target_sha256 = _request_semantics_sha256(target_rows)
        request_semantics[junction_id] = {
            "source_sha256": source_sha256,
            "target_sha256": target_sha256,
        }
        if source_rows != target_rows:
            failures.append(
                {
                    "reason": "contraction_neighbor_request_semantics_changed",
                    "junction_id": junction_id,
                    "source_request_semantics_sha256": source_sha256,
                    "target_request_semantics_sha256": target_sha256,
                }
            )
    return {
        "status": "pass" if not failures else "fail",
        "junction_ids": sorted(junction_ids),
        "source_tls_sha256": source_tls_sha256,
        "target_tls_sha256": target_tls_sha256,
        "request_semantics": request_semantics,
        "failure_count": len(failures),
        "failures": failures,
    }


def _xml_element_semantic_payload(element: ET.Element) -> dict[str, object]:
    """Return an XML semantic payload that ignores indentation and tail text."""

    return {
        "tag": element.tag,
        "attributes": sorted(element.attrib.items()),
        "children": [_xml_element_semantic_payload(child) for child in list(element)],
    }


def _internal_artifact_owner(value: str, junction_ids: set[str]) -> str:
    if not value.startswith(":"):
        return ""
    body = value[1:]
    end = len(body)
    while (separator := body.rfind("_", 0, end)) >= 0:
        candidate = body[:separator]
        if candidate in junction_ids:
            return candidate
        end = separator
    return ""


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
    owner_cache: dict[str, str] = {}

    def owner(value: str) -> str:
        if value in owner_cache:
            return owner_cache[value]
        internal_owner = _internal_artifact_owner(value, junction_ids)
        owner_cache[value] = internal_owner
        return internal_owner

    def is_restored_owner(value: str) -> bool:
        internal_owner = owner(value)
        return bool(internal_owner and internal_owner not in exclude_junction_ids)

    def connection_restored(connection: ET.Element) -> bool:
        return any(is_restored_owner(connection.attrib.get(attr, "")) for attr in ("from", "to", "via"))

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

    def replace_owned_children(
        tag: str,
        replacements: list[ET.Element],
        fallback_index: int,
    ) -> int:
        children = list(target_root)
        matched_indices = [
            index
            for index, child in enumerate(children)
            if child.tag == tag and is_restored_owner(child.attrib.get("id", ""))
        ]
        insert_index = matched_indices[0] if matched_indices else fallback_index
        retained = [
            child
            for child in children
            if child.tag != tag or not is_restored_owner(child.attrib.get("id", ""))
        ]
        target_root[:] = [
            *retained[:insert_index],
            *(copy.deepcopy(child) for child in replacements),
            *retained[insert_index:],
        ]
        return len(matched_indices)

    removed_internal_edges = replace_owned_children(
        "edge",
        source_internal_edges,
        _first_junction_index(target_root),
    )

    source_internal_junctions = [
        junction for junction in source_root.findall("junction") if is_restored_owner(junction.attrib.get("id", ""))
    ]
    target_children = list(target_root)
    removed_internal_junctions = replace_owned_children(
        "junction",
        source_internal_junctions,
        next(
            (index for index, child in enumerate(target_children) if child.tag == "connection"),
            len(target_children),
        ),
    )

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
            current_requests if current_matrix_is_valid or len(current_requests) in {0, len(filtered_int_lanes)} else []
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
        edge for edge in source_root.findall("edge") if edge.attrib.get("id", "").startswith(internal_prefix)
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
    source_junctions = {
        junction.attrib.get("id", ""): junction
        for junction in source_root.findall("junction")
        if junction.attrib.get("id")
    }
    adjacent_junctions = {
        endpoint_id: source_junctions[endpoint_id]
        for edge_id in restored_edge_ids
        for edge in [source_edges.get(edge_id)]
        if edge is not None
        for endpoint_id in (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
        if endpoint_id and endpoint_id != junction_id and endpoint_id in source_junctions
    }
    restored_adjacent_junctions = _restore_geometry_anchor_junctions(target_root, adjacent_junctions)
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
        "restored_adjacent_junction_count": len(restored_adjacent_junctions),
        "restored_adjacent_junction_ids": restored_adjacent_junctions,
        "restored_request_count": restored_request_count,
        "missing_edge_count": len(missing_edge_ids),
        "missing_edge_ids": missing_edge_ids,
    }


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
        tl_logic.attrib.get("id", "") for tl_logic in teacher_root.findall("tlLogic") if tl_logic.attrib.get("id")
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
        if (
            source.startswith(f"{internal_prefix}w")
            and target.startswith(f"{internal_prefix}c")
            and record.get("linkIndex")
        ):
            pairs[str(record["linkIndex"])] = (source, target)
    return pairs


def _pedestrian_tl_pairs_from_connections(
    connections: list[ET.Element], junction_id: str
) -> dict[str, tuple[str, str]]:
    pairs: dict[str, tuple[str, str]] = {}
    internal_prefix = f":{junction_id}_"
    for connection in connections:
        if connection.attrib.get("tl") != junction_id:
            continue
        source = connection.attrib.get("from", "")
        target = connection.attrib.get("to", "")
        if (
            source.startswith(f"{internal_prefix}w")
            and target.startswith(f"{internal_prefix}c")
            and connection.attrib.get("linkIndex")
        ):
            pairs[connection.attrib["linkIndex"]] = (source, target)
    return pairs


def _touches_target_pedestrian_ring(connection: ET.Element, internal_prefix: str) -> bool:
    source = connection.attrib.get("from", "")
    target = connection.attrib.get("to", "")
    return (
        source.startswith(f"{internal_prefix}w")
        or source.startswith(f"{internal_prefix}c")
        or target.startswith(f"{internal_prefix}w")
        or target.startswith(f"{internal_prefix}c")
    )


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


def _junction_signature_mismatch_fields(parity: dict[str, Any]) -> set[str]:
    def fields(summary: object) -> dict[str, str]:
        if not isinstance(summary, dict):
            return {}
        signature = str(summary.get("junction_signature", ""))
        return {
            key: value
            for item in signature.split("|")
            if "=" in item
            for key, value in [item.split("=", 1)]
        }

    teacher = fields(parity.get("teacher"))
    candidate = fields(parity.get("candidate"))
    if not teacher or not candidate:
        return set()
    return {key for key in teacher.keys() | candidate.keys() if teacher.get(key) != candidate.get(key)}


def _hybrid_osm_approach_authority_policy(
    raw_semantic_gate: dict[str, Any],
    *,
    replay_target_internal_subgraph: bool,
    preserve_teacher_lane_shapes: bool,
    strict_teacher_replay: bool = False,
    preserved_target_shape_only_mismatch: bool = False,
    structural_osm_boundary_authority: bool = False,
    edge_map: dict[str, str],
    lane_patch: dict[str, Any],
    target_internal_replay: dict[str, Any] | None,
    tls_movement_parity: dict[str, Any],
    pedestrian_crossing_parity: dict[str, Any],
    connection_plan: dict[str, Any] | None = None,
    vehicle_connection_attrs: dict[str, Any] | None = None,
    boundary_edge_preservation: dict[str, Any] | None = None,
    boundary_vehicle_connectivity: dict[str, Any] | None = None,
    target_surface_overlap_gate: dict[str, Any] | None = None,
    turnaround_audit: dict[str, Any] | None = None,
    target_internal_pedestrian_ring: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Allow a deliberate OSM-approach/official-core authority split.

    Strict teacher parity remains the default.  A joined full-network replay
    may instead retain every current OSM boundary edge while importing the
    teacher vehicle-movement pattern; exact TLS and pedestrian parity remain
    separate review capabilities.
    """

    if strict_teacher_replay:
        target_internal_replay = target_internal_replay or {}
        target_surface_overlap_gate = target_surface_overlap_gate or {}
        all_raw_failures = [
            dict(failure) for failure in raw_semantic_gate.get("failures", []) if isinstance(failure, dict)
        ]
        if raw_semantic_gate.get("status") != "pass" and not all_raw_failures:
            all_raw_failures.append(
                {
                    "report": "semantic_replay_gate",
                    "field": "status_not_pass",
                    "count": 1,
                }
            )
        waived_raw_failures = [
            failure
            for failure in all_raw_failures
            if preserved_target_shape_only_mismatch
            and failure.get("report") == "parity"
            and failure.get("field") == "junction_signature_mismatch_count"
        ]
        raw_failures = [failure for failure in all_raw_failures if failure not in waived_raw_failures]
        invariant_failures = []
        if target_internal_replay.get("status") != "pass":
            invariant_failures.append("target_internal_replay_not_pass")
        if int(target_internal_replay.get("skipped_connection_count", 0) or 0):
            invariant_failures.append("target_internal_replay_skipped_connections")
        if tls_movement_parity.get("status") != "pass":
            invariant_failures.append("tls_movement_parity_not_pass")
        if pedestrian_crossing_parity.get("status") != "pass":
            invariant_failures.append("pedestrian_crossing_parity_not_pass")
        if preserved_target_shape_only_mismatch and target_surface_overlap_gate.get("status") != "pass":
            invariant_failures.append("preserved_target_shape_surface_overlap_not_pass")
        effective_failures = [
            *raw_failures,
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
            "status": effective_gate["status"],
            "policy": "strict_teacher_replay",
            "requires_exact_tls_parity": True,
            "requires_exact_pedestrian_parity": True,
            "waived_raw_failures": waived_raw_failures,
            "retained_raw_failures": effective_failures,
            "invariant_failures": invariant_failures,
            "effective_semantic_gate": effective_gate,
        }

    structural = structural_osm_boundary_authority and not replay_target_internal_subgraph
    if structural:
        connection_plan = connection_plan or {}
        vehicle_connection_attrs = vehicle_connection_attrs or {}
        boundary_edge_preservation = boundary_edge_preservation or {}
        boundary_vehicle_connectivity = boundary_vehicle_connectivity or {}
        target_surface_overlap_gate = target_surface_overlap_gate or {}
        turnaround_audit = turnaround_audit or {}
        target_internal_pedestrian_ring = target_internal_pedestrian_ring or {}
        invariant_failures = []
        if lane_patch.get("status") != "pass":
            invariant_failures.append("lane_patch_not_pass")
        if lane_patch.get("preserve_osm_lane_profiles") is not True:
            invariant_failures.append("lane_patch_did_not_preserve_osm_lane_profiles")
        if lane_patch.get("preserve_lane_shapes") is not True:
            invariant_failures.append("lane_patch_did_not_preserve_osm_shapes")
        if int(lane_patch.get("pruned_boundary_edge_count", 0) or 0):
            invariant_failures.append("lane_patch_pruned_boundary_edges")
        if boundary_edge_preservation.get("status") != "pass":
            invariant_failures.append("boundary_edge_preservation_not_pass")
        if boundary_vehicle_connectivity.get("status") != "pass":
            invariant_failures.append("boundary_vehicle_connectivity_not_pass")
        if target_surface_overlap_gate.get("status") != "pass":
            invariant_failures.append("target_surface_overlap_gate_not_pass")
        if turnaround_audit.get("automatic_promotion_gate") != "pass":
            invariant_failures.append("turnaround_audit_not_pass")
        if connection_plan.get("status") != "pass":
            invariant_failures.append("connection_plan_not_pass")
        if connection_plan.get("structural_connection_generation") is not True:
            invariant_failures.append("structural_connection_generation_not_applied")
        if vehicle_connection_attrs.get("status") != "pass":
            invariant_failures.append("vehicle_connection_attrs_not_pass")
        if target_internal_pedestrian_ring.get("status") != "pass":
            invariant_failures.append("target_internal_pedestrian_ring_not_pass")
        if int(
            vehicle_connection_attrs.get(
                "skipped_motorized_vehicle_connection_count",
                vehicle_connection_attrs.get("skipped_vehicle_connection_count", 0),
            )
            or 0
        ):
            invariant_failures.append("vehicle_connection_attrs_skipped_connections")
        if tls_movement_parity.get("tl_logic_phase_states_equal") is False:
            invariant_failures.append("tls_phase_states_mismatch")

        blocking_fields: set[str] = set()
        retained_raw_failures = [
            dict(failure)
            for failure in raw_semantic_gate.get("failures", [])
            if isinstance(failure, dict) and str(failure.get("field", "")) in blocking_fields
        ]
        waived_raw_failures = [
            dict(failure)
            for failure in raw_semantic_gate.get("failures", [])
            if isinstance(failure, dict) and str(failure.get("field", "")) not in blocking_fields
        ]
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
        return {
            "schema": "torii.hybrid_osm_approach_authority_policy.v1",
            "status": "fail" if effective_failures else "pass",
            "policy": "osm_boundary_teacher_vehicle_movements",
            "requires_exact_tls_parity": False,
            "requires_exact_pedestrian_parity": False,
            "capabilities": {
                "topology": "pass" if not effective_failures else "fail",
                "vehicle_movements": "pass" if not effective_failures else "fail",
                "signal_control": "review_required",
                "pedestrian_crossings": "review_required",
            },
            "waived_raw_failures": waived_raw_failures,
            "retained_raw_failures": retained_raw_failures,
            "invariant_failures": invariant_failures,
            "effective_semantic_gate": {
                "status": "fail" if effective_failures else "pass",
                "failures": effective_failures,
            },
        }

    active = replay_target_internal_subgraph and not preserve_teacher_lane_shapes
    if not active:
        return {
            "schema": "torii.hybrid_osm_approach_authority_policy.v1",
            "status": "not_applied",
            "policy": "strict_teacher_parity",
            "requires_exact_tls_parity": True,
            "requires_exact_pedestrian_parity": True,
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
    target_internal_replay = target_internal_replay or {}
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
        str(edge_id) for edge_id in target_internal_replay.get("blended_geometry_anchor_edge_ids", []) if str(edge_id)
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
    if int(target_internal_replay.get("copied_boundary_edge_count", 0) or 0) != len(mapped_pairs):
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
            retained_raw_failures.append({"report": "semantic_replay_gate", "field": "malformed_failure", "count": 1})
            continue
        field = str(failure.get("field", ""))
        count = int(failure.get("count", 0) or 0)
        if failure.get("report") == "parity" and field in allowed_fields and count == len(mapped_pairs):
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
        "requires_exact_tls_parity": True,
        "requires_exact_pedestrian_parity": True,
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
        layers["movement_tls"]["failures"].append({"report": "tls_movement_parity", "field": "status", "count": 1})
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
    vehicle_connections = (
        model.get("vehicle_connections", []) if isinstance(model.get("vehicle_connections"), list) else []
    )
    pedestrian_connections = (
        model.get("pedestrian_connections", []) if isinstance(model.get("pedestrian_connections"), list) else []
    )
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
    summary["controlled_link_count"] = (
        summary["controlled_vehicle_link_count"] + summary["controlled_pedestrian_link_count"]
    )
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
        "|".join(f"{field}={phase.get(field, '')}" for field in fields) for phase in phases if isinstance(phase, dict)
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
    connections = (
        model.get("pedestrian_connections", []) if isinstance(model.get("pedestrian_connections"), list) else []
    )
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
            source = _canonical_sumo_cluster_id(
                _mapped_junction_ref(str(edge.get("from", "")), source_junction_id, target_junction_id)
            )
            target = _canonical_sumo_cluster_id(
                _mapped_junction_ref(str(edge.get("to", "")), source_junction_id, target_junction_id)
            )
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
            candidate_from = _canonical_sumo_cluster_id(str(candidate_edge.get("from", "")))
            candidate_to = _canonical_sumo_cluster_id(str(candidate_edge.get("to", "")))
            desired_from = _mapped_junction_ref(
                str(teacher_edge.get("from", "")), teacher_junction_id, candidate_junction_id
            )
            desired_to = _mapped_junction_ref(
                str(teacher_edge.get("to", "")), teacher_junction_id, candidate_junction_id
            )
            if (candidate_from, candidate_to) == (desired_from, desired_to):
                continue
            desired_external = {
                endpoint for endpoint in (desired_from, desired_to) if endpoint and endpoint != candidate_junction_id
            }
            candidate_external = {
                endpoint
                for endpoint in (candidate_from, candidate_to)
                if endpoint and endpoint != candidate_junction_id
            }
            missing_desired = sorted(
                endpoint for endpoint in desired_external if endpoint not in candidate_junction_ids
            )
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
    source = _canonical_sumo_cluster_id(
        _mapped_junction_ref(str(edge.get("from", "")), source_junction_id, target_junction_id)
    )
    target = _canonical_sumo_cluster_id(
        _mapped_junction_ref(str(edge.get("to", "")), source_junction_id, target_junction_id)
    )
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
    return _canonical_sumo_cluster_id(value)


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
        inc_lanes = _mapped_lane_refs(
            str(junction.get("incLanes", "")), edge_map, source_junction_id, target_junction_id
        )
        int_lanes = _mapped_lane_refs(
            str(junction.get("intLanes", "")), edge_map, source_junction_id, target_junction_id
        )
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
    return " ".join(_mapped_lane_ref(lane, edge_map, source_junction_id, target_junction_id) for lane in value.split())


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


def _unique_connections_by_key(
    root: ET.Element,
) -> tuple[dict[tuple[str, str, str, str], ET.Element], set[tuple[str, str, str, str]]]:
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
            len(phase.attrib.get("state", "")) for phase in tl_logic.findall("phase") if phase.attrib.get("state")
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
            padded_tls.append(
                {"tls": tls_id, "required_state_length": required_length, "padded_phase_count": phase_count}
            )
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
        tl_logic.attrib["id"]: tl_logic for tl_logic in source_root.findall("tlLogic") if tl_logic.attrib.get("id")
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
        return f"{target_prefix}{value[len(source_prefix) :]}"
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

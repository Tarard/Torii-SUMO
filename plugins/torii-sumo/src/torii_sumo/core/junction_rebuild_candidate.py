from __future__ import annotations

import copy
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .command_runner import run_command
from .junction_connection_audit import build_connection_signature, write_connection_signature
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


APPROACH_INTEGRITY_FAILURE_FIELDS = {
    "approach_edge_signature_mismatch_count",
    "approach_endpoint_signature_mismatch_count",
    "incoming_vehicle_edge_count",
    "outgoing_vehicle_edge_count",
}

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
    matched_cases = [*matched_cases, *same_id_pattern_cases]
    matched_cases.sort(
        key=lambda case: _teacher_guided_case_sort_key(case, pattern_records, pattern_templates)
    )
    repair_candidates = []
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
        "queued_case_count": len(repair_candidates),
        "queue_truncated": len(repair_candidates) < len(matched_cases),
        "queue_order_policy": "largest_vehicle_movement_gap_then_highest_teacher_template_count",
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
    variant_file = output_dir / f"{prefix}_tls_connection_repaired.net.xml"
    summary_file = output_dir / f"{prefix}_tls_connection_repair.json"

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
) -> dict[str, object]:
    crossing_edge_overrides = crossing_edge_overrides or {}
    output_file.parent.mkdir(parents=True, exist_ok=True)

    incoming = _approach_edges(candidate_model, "incoming")
    outgoing = _approach_edges(candidate_model, "outgoing")
    candidate_edges_for_cleanup = set(incoming) | set(outgoing)
    candidate_lane_counts = _candidate_lane_counts(candidate_model)
    present_candidate_edges: set[str] | None = None
    if candidate_edge_file is not None:
        patched_lane_counts = _edge_file_lane_counts(candidate_edge_file)
        candidate_lane_counts.update(patched_lane_counts)
        present_candidate_edges = set(patched_lane_counts)
        incoming = [edge for edge in incoming if edge in present_candidate_edges]
        outgoing = [edge for edge in outgoing if edge in present_candidate_edges]

    root = ET.Element("connections")
    kept = 0
    removed = 0
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
        if child.tag == "connection" and (
            child.attrib.get("from", "") in candidate_edges_for_cleanup or child.attrib.get("to", "") in candidate_edges_for_cleanup
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
    seen_connections: set[tuple[str, str, str, str]] = set()
    lane_clamps = []
    for connection in teacher_model.get("vehicle_connections", []) or []:
        if not isinstance(connection, dict):
            continue
        source = edge_map.get(str(connection.get("from", "")))
        target = edge_map.get(str(connection.get("to", "")))
        if not source or not target:
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
            ET.SubElement(root, "delete", {"from": source, "to": target})
            emitted_deletes += 1

    emitted_crossings = 0
    skipped_crossings = []
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
        ET.SubElement(root, "crossing", {"node": junction_id, "edges": " ".join(crossing_edges), "priority": "1", "width": "4.00"})
        emitted_crossings += 1

    ET.indent(root, space="    ")
    ET.ElementTree(root).write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "connection_file": str(output_file),
        "kept_non_target_children": kept,
        "removed_target_children": removed,
        "emitted_connection_count": emitted_connections,
        "emitted_uncontrolled_connection_count": emitted_uncontrolled_connections,
        "emitted_delete_count": emitted_deletes,
        "emitted_crossing_count": emitted_crossings,
        "skipped_crossings": skipped_crossings,
        "lane_clamp_count": len(lane_clamps),
        "lane_clamps": lane_clamps,
    }


def write_teacher_lane_patch_edges(
    *,
    raw_edge_file: Path,
    teacher_edge_file: Path,
    output_file: Path,
    edge_map: dict[str, str],
    junction_id: str | None = None,
    boundary_node_ids: set[str] | None = None,
    prune_unmapped_boundary_edges: bool = False,
    lane_shape_delta: tuple[float, float] | None = None,
) -> dict[str, object]:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    teacher_edges = {
        edge.attrib["id"]: edge
        for edge in ET.parse(teacher_edge_file).getroot().findall("edge")
        if edge.attrib.get("id")
    }
    teacher_by_candidate = {candidate_id: teacher_edges[teacher_id] for teacher_id, candidate_id in edge_map.items() if teacher_id in teacher_edges}

    tree = ET.parse(raw_edge_file)
    patched = []
    pruned_boundary_edges = []
    remapped_teacher_edges = set(edge_map)
    teacher_same_junction_edges = {
        edge_id
        for edge_id, edge in teacher_edges.items()
        if junction_id and junction_id in (edge.attrib.get("from"), edge.attrib.get("to")) and edge_id not in remapped_teacher_edges
    }
    allowed_boundary_edges = set(edge_map.values()) | teacher_same_junction_edges
    boundary_node_ids = boundary_node_ids or set()
    for edge in tree.getroot().findall("edge"):
        edge_id = edge.attrib.get("id", "")
        touches_target = (
            edge.attrib.get("from") == junction_id
            or edge.attrib.get("to") == junction_id
            or edge.attrib.get("from") in boundary_node_ids
            or edge.attrib.get("to") in boundary_node_ids
        )
        if (
            prune_unmapped_boundary_edges
            and junction_id
            and touches_target
            and edge_id not in allowed_boundary_edges
        ):
            tree.getroot().remove(edge)
            pruned_boundary_edges.append(edge_id)
            continue
        teacher_edge = teacher_by_candidate.get(edge.attrib.get("id", ""))
        if teacher_edge is None:
            continue
        teacher_lanes = teacher_edge.findall("lane")
        if not teacher_lanes:
            continue
        for lane in list(edge.findall("lane")):
            edge.remove(lane)
        edge.attrib.pop("allow", None)
        edge.attrib.pop("disallow", None)
        edge.attrib.pop("width", None)
        edge.set("numLanes", str(len(teacher_lanes)))
        for attr in ("allow", "disallow", "width"):
            if teacher_edge.attrib.get(attr):
                edge.set(attr, teacher_edge.attrib[attr])
        for lane in teacher_lanes:
            lane_attrs = {"index": lane.attrib.get("index", "0")}
            for attr in ("allow", "disallow", "width", "speed"):
                if lane.attrib.get(attr):
                    lane_attrs[attr] = lane.attrib[attr]
            if lane_shape_delta is not None and lane.attrib.get("shape"):
                lane_attrs["shape"] = _translate_shape(lane.attrib["shape"], lane_shape_delta[0], lane_shape_delta[1])
            ET.SubElement(edge, "lane", lane_attrs)
        patched.append({"candidate_edge_id": edge.attrib.get("id", ""), "teacher_edge_id": teacher_edge.attrib.get("id", ""), "lane_count": len(teacher_lanes)})

    ET.indent(tree.getroot(), space="    ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "edge_file": str(output_file),
        "patched_edge_count": len(patched),
        "patched_edges": patched,
        "pruned_boundary_edge_count": len(pruned_boundary_edges),
        "pruned_boundary_edges": pruned_boundary_edges,
        "lane_shape_translation_applied": lane_shape_delta is not None,
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

    teacher_link_pairs = _pedestrian_tl_pairs_from_records(teacher_model.get("pedestrian_connections", []) or [], teacher_junction_id)
    candidate_link_pairs = _pedestrian_tl_pairs_from_connections(root.findall("connection"), junction_id)
    walkingarea_map: dict[str, str] = {}
    for link_index, (teacher_walkingarea, teacher_crossing) in teacher_link_pairs.items():
        candidate_pair = candidate_link_pairs.get(link_index)
        if not candidate_pair:
            continue
        walkingarea_map[teacher_walkingarea] = candidate_pair[0]
        crossing_map.setdefault(teacher_crossing, candidate_pair[1])

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

    inserted_connections = 0
    skipped_connections = []
    for connection in teacher_model.get("pedestrian_connections", []) or []:
        if not isinstance(connection, dict):
            continue
        mapped_from = _map_teacher_pedestrian_endpoint(str(connection.get("from", "")), walkingarea_map, crossing_map, edge_map)
        mapped_to = _map_teacher_pedestrian_endpoint(str(connection.get("to", "")), walkingarea_map, crossing_map, edge_map)
        if not mapped_from or not mapped_to:
            skipped_connections.append(connection)
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
        "kept_walkingarea_count": len(kept_walkingareas),
        "removed_walkingarea_count": len(removed_walkingareas),
        "removed_pedestrian_connection_count": removed_connections,
        "inserted_pedestrian_connection_count": inserted_connections,
        "skipped_pedestrian_connection_count": len(skipped_connections),
        "skipped_pedestrian_connections": skipped_connections,
    }


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


def write_teacher_target_internal_replay_net(
    *,
    candidate_net_file: Path,
    teacher_net_file: Path,
    output_file: Path,
    junction_id: str,
    edge_map: dict[str, str],
    teacher_junction_id: str | None = None,
) -> dict[str, object]:
    teacher_junction_id = teacher_junction_id or junction_id
    output_file.parent.mkdir(parents=True, exist_ok=True)

    candidate_tree = ET.parse(candidate_net_file)
    candidate_root = candidate_tree.getroot()
    teacher_root = ET.parse(teacher_net_file).getroot()
    internal_prefix = f":{junction_id}_"
    teacher_internal_prefix = f":{teacher_junction_id}_"
    candidate_edges_by_id = {edge.attrib["id"]: edge for edge in candidate_root.findall("edge") if edge.attrib.get("id")}
    candidate_edge_ids = set(candidate_edges_by_id)
    replay_edge_map = dict(edge_map)

    candidate_junction = candidate_root.find(f"junction[@id='{junction_id}']")
    teacher_junction = teacher_root.find(f"junction[@id='{teacher_junction_id}']")
    if candidate_junction is None:
        return _failure(f"candidate junction not found: {junction_id}")
    if teacher_junction is None:
        return _failure(f"teacher junction not found: {junction_id}")

    dx = float(candidate_junction.attrib.get("x", "0") or 0) - float(teacher_junction.attrib.get("x", "0") or 0)
    dy = float(candidate_junction.attrib.get("y", "0") or 0) - float(teacher_junction.attrib.get("y", "0") or 0)

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
    skipped_boundary_edges = []
    replaced_boundary_edge_ids: set[str] = set()
    boundary_insert_offset = 0
    teacher_edges = {edge.attrib["id"]: edge for edge in teacher_root.findall("edge") if edge.attrib.get("id")}
    teacher_junctions = {
        junction.attrib["id"]: junction
        for junction in teacher_root.findall("junction")
        if junction.attrib.get("id")
    }
    candidate_junction_ids = {
        junction.attrib["id"] for junction in candidate_root.findall("junction") if junction.attrib.get("id")
    }
    copied_boundary_junctions = []
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
    for edge_id in needed_boundary_edge_ids:
        teacher_edge = teacher_edges[edge_id]
        mapped_from = junction_id if teacher_edge.attrib.get("from") == teacher_junction_id else teacher_edge.attrib.get("from", "")
        mapped_to = junction_id if teacher_edge.attrib.get("to") == teacher_junction_id else teacher_edge.attrib.get("to", "")
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
            candidate_root.insert(list(candidate_root).index(candidate_junction), copied_junction)
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
        copied_edge_id = copied_edge.attrib.get("id", "")
        if not copied_edge_id:
            skipped_boundary_edges.append(edge_id)
            continue
        replaced_edge = candidate_edges_by_id.get(copied_edge_id)
        insert_at = insert_index + boundary_insert_offset
        if replaced_edge is not None:
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
            _remove_edge_lanes_from_destination_junction(candidate_root, edge)
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
        junction_insert_index = list(candidate_root).index(candidate_junction) + 1

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

    candidate_junction.attrib.clear()
    candidate_junction.attrib.update(
        _mapped_junction_attrs(teacher_junction, dx, dy, replay_edge_map, teacher_internal_prefix, internal_prefix)
    )
    for child in list(candidate_junction):
        candidate_junction.remove(child)
    for request in teacher_junction.findall("request"):
        candidate_junction.append(ET.Element("request", dict(request.attrib)))

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
            not _touches_target_internal_subgraph(connection, internal_prefix, junction_id)
            and not from_edge_id.startswith(":")
            and not to_edge_id.startswith(":")
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
        if _touches_target_internal_subgraph(connection, internal_prefix, junction_id):
            candidate_root.remove(connection)
            removed_connections += 1

    copied_connections = 0
    skipped_connections = []
    for connection in teacher_root.findall("connection"):
        if not _touches_target_internal_subgraph(connection, teacher_internal_prefix, teacher_junction_id):
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
        if _touches_target_internal_subgraph(connection, teacher_internal_prefix, teacher_junction_id)
        and connection.attrib.get("tl")
        and connection.attrib.get("linkIndex")
    ]
    teacher_tllogic = teacher_root.find(f"tlLogic[@id='{teacher_junction_id}']")
    if teacher_tllogic is None:
        teacher_tllogic = next(
            (tl for tl in teacher_root.findall("tlLogic") if tl.attrib.get("id") in teacher_tls_ids),
            None,
        )
    if teacher_tllogic is not None:
        target_tllogic = candidate_root.find(f"tlLogic[@id='{junction_id}']")
        target_index = list(candidate_root).index(target_tllogic) if target_tllogic is not None else len(list(candidate_root))
        if target_tllogic is not None:
            candidate_root.remove(target_tllogic)
        copied_tllogic = _clone_transformed_net_element(teacher_tllogic, dx, dy, replay_edge_map, teacher_junction_id, junction_id)
        copied_tllogic.set("id", junction_id)
        candidate_root.insert(target_index, copied_tllogic)

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
        "preserved_colliding_boundary_edge_count": len(preserved_colliding_boundary_edges),
        "preserved_colliding_boundary_edges": preserved_colliding_boundary_edges,
        "removed_stale_boundary_edge_count": len(removed_stale_boundary_edges),
        "removed_stale_boundary_edges": removed_stale_boundary_edges,
        "removed_stale_boundary_edge_connection_count": len(removed_stale_boundary_edge_connections),
        "removed_stale_boundary_edge_connections": removed_stale_boundary_edge_connections,
        "removed_stale_replaced_edge_connection_count": len(removed_stale_replaced_edge_connections),
        "removed_stale_replaced_edge_connections": removed_stale_replaced_edge_connections,
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
        "copied_request_count": len(teacher_junction.findall("request")),
        "effective_edge_map": dict(sorted(replay_edge_map.items())),
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
    crossing_edge_overrides: dict[str, str | list[str]] | None = None,
    replay_target_internal_subgraph: bool = False,
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
    if missing:
        return _failure(f"missing input file(s): {', '.join(missing)}")

    raw_node_file = raw_node_file.resolve()
    raw_edge_file = raw_edge_file.resolve()
    raw_connection_file = raw_connection_file.resolve()
    teacher_net_file = teacher_net_file.resolve()
    candidate_net_file = candidate_net_file.resolve()
    raw_type_file = raw_type_file.resolve() if raw_type_file is not None else None
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    teacher_model = extract_teacher_junction_model(teacher_net_file, teacher_junction_id)
    candidate_model = extract_teacher_junction_model(candidate_net_file, junction_id)

    patched_edge_file = _stage_file(output_dir, prefix, "lanes.edg.xml")
    connection_file = _stage_file(output_dir, prefix, "connections.con.xml")
    sidewalks_net_file = _stage_file(output_dir, prefix, "sidewalks.net.xml")
    pedring_net_file = _stage_file(output_dir, prefix, "pedring.net.xml")
    vehicle_attrs_net_file = _stage_file(output_dir, prefix, "vehicle_attrs.net.xml")
    target_internal_replay_file = _stage_file(output_dir, prefix, "target_internal_replay.net.xml")
    target_internal_normalized_net_file = _stage_file(output_dir, prefix, "target_internal_normalized.net.xml")
    target_internal_pedring_net_file = _stage_file(output_dir, prefix, "target_internal_pedring.net.xml")
    target_internal_vehicle_attrs_net_file = _stage_file(output_dir, prefix, "target_internal_vehicle_attrs.net.xml")
    final_net_file = _stage_file(output_dir, prefix, "teacher_guided.net.xml")
    fallback_net_file = _stage_file(output_dir, prefix, "teacher_guided_fallback.net.xml")
    report_file = _stage_file(output_dir, prefix, "teacher_guided_report.json")

    lane_patch_report = write_teacher_lane_patch_edges(
        raw_edge_file=raw_edge_file,
        teacher_edge_file=teacher_net_file,
        output_file=patched_edge_file,
        edge_map=edge_map,
        junction_id=junction_id,
        boundary_node_ids=_joined_source_node_ids(raw_node_file, junction_id),
        prune_unmapped_boundary_edges=True,
        lane_shape_delta=_model_shape_delta(teacher_model, candidate_model),
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
    )

    netconvert_command = [
        netconvert_binary,
        "--node-files",
        _command_path(raw_node_file, output_dir),
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
    if raw_type_file is not None:
        netconvert_command[5:5] = ["--type-files", _command_path(raw_type_file, output_dir)]
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
                "lane_patch": lane_patch_report,
                "connection_plan": connection_report,
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
    target_internal_pedestrian_ring_report = None
    target_internal_vehicle_attrs_report = None
    tl_logic_input_file = vehicle_attrs_net_file
    if replay_target_internal_subgraph:
        target_internal_replay_report = write_teacher_target_internal_replay_net(
            candidate_net_file=vehicle_attrs_net_file,
            teacher_net_file=teacher_net_file,
            output_file=target_internal_replay_file,
            junction_id=junction_id,
            edge_map=edge_map,
            teacher_junction_id=teacher_junction_id,
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
                    "lane_patch": lane_patch_report,
                    "connection_plan": connection_report,
                    "pedestrian_ring": pedestrian_ring_report,
                    "vehicle_connection_attrs": vehicle_attrs_report,
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
                "lane_patch": lane_patch_report,
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
    parity_gate_status = semantic_gate["status"]
    status = "pass" if sumo_report.get("status") == "pass" else "fail"
    return _write_teacher_guided_report(
        report_file,
        {
            "status": status,
            "claim_status": "diagnostic-demo" if status == "pass" else "construction-invalid",
            "parity_gate_status": parity_gate_status,
            "junction_id": junction_id,
            "teacher_net_file": str(teacher_net_file),
            "candidate_net_file": str(candidate_net_file),
            "final_net_file": str(final_net_file),
            "patched_edge_file": str(patched_edge_file),
            "connection_file": str(connection_file),
            "sidewalks_net_file": str(sidewalks_net_file),
            "pedring_net_file": str(pedring_net_file),
            "vehicle_attrs_net_file": str(vehicle_attrs_net_file),
            "target_internal_replay_file": str(target_internal_replay_file) if replay_target_internal_subgraph else "",
            "target_internal_replay_fallback": target_internal_replay_fallback,
            "target_internal_replay_fallback_net_file": str(fallback_net_file) if target_internal_replay_fallback else "",
            "target_internal_normalized_net_file": str(target_internal_normalized_net_file)
            if target_internal_normalize_report
            else "",
            "target_internal_pedring_net_file": str(target_internal_pedring_net_file)
            if target_internal_pedestrian_ring_report
            else "",
            "target_internal_vehicle_attrs_net_file": str(target_internal_vehicle_attrs_net_file)
            if target_internal_vehicle_attrs_report
            else "",
            "report_file": str(report_file),
            "lane_patch": lane_patch_report,
            "connection_plan": connection_report,
            "netconvert": netconvert_report,
            "pedestrian_ring": pedestrian_ring_report,
            "vehicle_connection_attrs": vehicle_attrs_report,
            "target_internal_replay": target_internal_replay_report,
            "target_internal_replay_fallback_tl_logic": target_internal_replay_fallback_tl_logic_report,
            "target_internal_replay_fallback_sumo": target_internal_replay_fallback_sumo_report,
            "target_internal_normalize": target_internal_normalize_report,
            "target_internal_pedestrian_ring": target_internal_pedestrian_ring_report,
            "target_internal_vehicle_connection_attrs": target_internal_vehicle_attrs_report,
            "tl_logic": tl_logic_report,
            "sumo_load": sumo_report,
            "parity": parity,
            "approach_endpoint_rebuild_plan": approach_endpoint_rebuild_plan,
            "semantic_replay_gate": semantic_gate,
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
    crossing_edge_overrides_by_junction: dict[str, dict[str, str | list[str]]] | None = None,
    replay_target_internal_subgraph: bool = False,
    max_ready_candidates: int | None = None,
    netconvert_binary: str = "netconvert",
    sumo_binary: str = "sumo",
    timeout_seconds: float = 240.0,
    command_runner: Any = run_command,
    variant_builder: Any = build_teacher_guided_junction_variant,
    sequential_accept_passed_variants: bool = False,
    plain_exporter: Any | None = None,
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
    if missing:
        return _failure(f"missing input file(s): {', '.join(missing)}")

    candidates = queue_report.get("repair_candidates", []) or []
    if not isinstance(candidates, list):
        return _failure("queue report repair_candidates must be a list")

    output_dir.mkdir(parents=True, exist_ok=True)
    crossing_edge_overrides_by_junction = crossing_edge_overrides_by_junction or {}
    variant_reports = []
    expanded_scope_reports = []
    skipped_candidates = []
    sequential_plain_export_reports = []
    current_raw_node_file = raw_node_file
    current_raw_edge_file = raw_edge_file
    current_raw_connection_file = raw_connection_file
    current_raw_type_file = raw_type_file
    current_candidate_net_file = candidate_net_file
    composite_applied_candidate_count = 0
    composite_net_file = ""
    applied_candidate_edge_ids: set[str] = set()
    applied_candidate_node_ids: set[str] = set()
    sequential_blocked_reason = ""
    attempted_ready_count = 0
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            skipped_candidates.append({"index": index, "candidate_status": "invalid_candidate"})
            continue
        junction_id = str(candidate.get("junction_id") or candidate.get("reference_id") or "")
        teacher_junction_id = str(candidate.get("reference_id") or junction_id)
        edge_map = _valid_edge_map(candidate.get("edge_map", {}))
        candidate_node_ids = {str(item) for item in candidate.get("matched_candidate_node_ids", []) or [] if str(item)}
        if junction_id:
            candidate_node_ids.add(junction_id)
        candidate_edge_ids = {str(item) for item in edge_map.values() if str(item)}
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
        if sequential_accept_passed_variants and (
            candidate_edge_ids & applied_candidate_edge_ids or candidate_node_ids & applied_candidate_node_ids
        ):
            skipped_candidates.append(
                {
                    "index": index,
                    "junction_id": junction_id,
                    "candidate_status": "sequential_candidate_overlap",
                    "overlap_edge_ids": sorted(candidate_edge_ids & applied_candidate_edge_ids),
                    "overlap_node_ids": sorted(candidate_node_ids & applied_candidate_node_ids),
                }
            )
            continue
        if candidate.get("candidate_status") == "needs_expanded_rebuild_scope" and junction_id:
            if (
                max_ready_candidates is not None
                and max_ready_candidates > 0
                and attempted_ready_count >= max_ready_candidates
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
                    netconvert_binary=netconvert_binary,
                    sumo_binary=sumo_binary,
                    timeout_seconds=timeout_seconds,
                    command_runner=command_runner,
                ),
                candidate,
            )
            expanded_scope_reports.append(scope_report)
            joined_scope_junction_id = str(scope_report.get("joined_scope_junction_id", ""))
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
                )
            ):
                variant_prefix = f"{_safe_stage_name(prefix, max_len=12)}_{index + 1:03d}"
                if use_full_network_replay:
                    replay_node_file = current_raw_node_file
                    replay_edge_file = current_raw_edge_file
                    replay_connection_file = current_raw_connection_file
                    replay_candidate_net_file = current_candidate_net_file
                    replay_blocking_self_loop_edge_drops = []
                    replay_dropped_self_loop_edges = []
                    replay_edge_endpoint_rewrite_count = 0
                    scope_report["replay_scope"] = "full_network"
                else:
                    replay_node_file = _write_replay_node_file(
                        Path(str(scope_report.get("node_file", ""))),
                        Path(str(scope_report.get("join_nodes_patch_file", ""))),
                        output_dir / safe_junction_id / "expanded_scope_replay.nod.xml",
                    )
                    (
                        replay_edge_file,
                        replay_edge_endpoint_rewrite_count,
                        replay_dropped_self_loop_edges,
                        replay_blocking_self_loop_edge_drops,
                    ) = _write_joined_endpoint_edge_file(
                        Path(str(scope_report.get("edge_file", ""))),
                        Path(str(scope_report.get("join_nodes_patch_file", ""))),
                        joined_scope_junction_id,
                        output_dir / safe_junction_id / "expanded_scope_replay.edg.xml",
                    )
                    replay_connection_file = Path(str(scope_report.get("connection_file", "")))
                    replay_candidate_net_file = Path(str(scope_report.get("net_file", "")))
                    scope_report["replay_scope"] = "expanded_scope"
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
                replay_absorbed_join_internal_edge_ids = [
                    edge_id
                    for edge_id in replay_blocking_self_loop_edge_drops
                    if edge_id not in protected_self_loop_edge_ids
                ]
                replay_blocking_self_loop_edge_drops = [
                    edge_id
                    for edge_id in replay_blocking_self_loop_edge_drops
                    if edge_id in protected_self_loop_edge_ids
                ]
                if replay_target_internal_subgraph and replay_blocking_self_loop_edge_drops:
                    mapped_edge_ids = {str(edge_id) for edge_id in replay_edge_map.values() if str(edge_id)}
                    surviving_edge_ids = _edge_file_ids(replay_edge_file)
                    deferred_self_loop_edge_ids = [
                        edge_id
                        for edge_id in replay_blocking_self_loop_edge_drops
                        if edge_id not in mapped_edge_ids
                        and (
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
                            if replay_target_internal_subgraph
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
                        replay_target_internal_subgraph=replay_target_internal_subgraph,
                        netconvert_binary=netconvert_binary,
                        sumo_binary=sumo_binary,
                        timeout_seconds=timeout_seconds,
                    )
                except Exception as exc:
                    variant_report = _variant_exception_report(exc, joined_scope_junction_id)
                attached_report = _attach_candidate_template_context(variant_report, candidate)
                variant_reports.append(attached_report)
                final_net_file = Path(str(attached_report.get("final_net_file", "")))
                if (
                    use_full_network_replay
                    and sequential_accept_passed_variants
                    and attached_report.get("status") == "pass"
                    and attached_report.get("parity_gate_status") == "pass"
                    and final_net_file.exists()
                ):
                    composite_applied_candidate_count += 1
                    composite_net_file = str(final_net_file)
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
                            current_raw_node_file = Path(str(export_report["raw_node_file"]))
                            current_raw_edge_file = Path(str(export_report["raw_edge_file"]))
                            current_raw_connection_file = Path(str(export_report["raw_connection_file"]))
                            raw_type_value = str(export_report.get("raw_type_file", ""))
                            current_raw_type_file = Path(raw_type_value) if raw_type_value else None
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
        if max_ready_candidates is not None and max_ready_candidates > 0 and attempted_ready_count >= max_ready_candidates:
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
                teacher_net_file=teacher_net_file,
                candidate_net_file=current_candidate_net_file,
                junction_id=junction_id,
                output_dir=output_dir / safe_junction_id,
                edge_map=edge_map,
                prefix=variant_prefix,
                teacher_junction_id=teacher_junction_id,
                crossing_edge_overrides=crossing_edge_overrides_by_junction.get(junction_id)
                or crossing_edge_overrides_by_junction.get(teacher_junction_id),
                replay_target_internal_subgraph=replay_target_internal_subgraph,
                netconvert_binary=netconvert_binary,
                sumo_binary=sumo_binary,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            variant_report = _variant_exception_report(exc, junction_id)
        attached_report = _attach_candidate_template_context(variant_report, candidate)
        variant_reports.append(attached_report)
        final_net_file = Path(str(attached_report.get("final_net_file", "")))
        if (
            sequential_accept_passed_variants
            and attached_report.get("status") == "pass"
            and attached_report.get("parity_gate_status") == "pass"
            and final_net_file.exists()
        ):
            composite_applied_candidate_count += 1
            composite_net_file = str(final_net_file)
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
                    current_raw_node_file = Path(str(export_report["raw_node_file"]))
                    current_raw_edge_file = Path(str(export_report["raw_edge_file"]))
                    current_raw_connection_file = Path(str(export_report["raw_connection_file"]))
                    raw_type_value = str(export_report.get("raw_type_file", ""))
                    current_raw_type_file = Path(raw_type_value) if raw_type_value else None
                else:
                    sequential_blocked_reason = str(
                        export_report.get("error", "plain export failed after accepted variant")
                    )

    attempted_count = len(variant_reports)
    pass_count = sum(1 for report in variant_reports if report.get("status") == "pass")
    failed_count = attempted_count - pass_count
    parity_pass_count = sum(1 for report in variant_reports if report.get("parity_gate_status") == "pass")
    semantic_failure_counts = _semantic_failure_counts(variant_reports)
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
    sequential_composite_ready = (
        sequential_accept_passed_variants
        and composite_applied_candidate_count > 0
        and bool(composite_net_file)
        and Path(composite_net_file).exists()
    )
    if attempted_count == 0:
        status = "blocked"
        claim_status = "blocked"
        parity_gate_status = "blocked"
    elif sequential_composite_ready and failed_count == 0:
        status = "pass"
        claim_status = "diagnostic-demo"
        parity_gate_status = "pass"
    else:
        status = "pass" if failed_count == 0 and parity_pass_count == attempted_count else "fail"
        claim_status = "construction-invalid" if failed_count else "diagnostic-demo"
        parity_gate_status = "pass" if parity_pass_count == attempted_count else "fail"

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
        "candidate_count": len(candidates),
        "max_ready_candidates": max_ready_candidates if max_ready_candidates is not None else "",
        "attempted_candidate_count": attempted_count,
        "skipped_candidate_count": len(skipped_candidates),
        "pass_candidate_count": pass_count,
        "failed_candidate_count": failed_count,
        "parity_pass_candidate_count": parity_pass_count,
        "semantic_failure_counts": semantic_failure_counts,
        "approach_integrity_status": _approach_integrity_status(
            parity_gate_status=parity_gate_status,
            attempted_count=attempted_count,
            semantic_failure_counts=semantic_failure_counts,
            approach_failure_counts=approach_integrity_failure_counts,
        ),
        "approach_integrity_failure_counts": approach_integrity_failure_counts,
        "expanded_scope_candidate_count": len(expanded_scope_reports),
        "expanded_scope_pass_candidate_count": expanded_scope_pass_count,
        "best_expanded_scope_net_file": best_expanded_scope_net_file,
        "sequential_accept_passed_variants": sequential_accept_passed_variants,
        "sequential_plain_export_status": "skipped"
        if not sequential_accept_passed_variants or not sequential_plain_export_reports
        else ("pass" if all(report.get("status") == "pass" for report in sequential_plain_export_reports) else "fail"),
        "sequential_plain_export_reports": sequential_plain_export_reports,
        "composite_applied_candidate_count": composite_applied_candidate_count,
        "composite_net_file": composite_net_file,
        "expanded_scope_reports": expanded_scope_reports,
        "run_report_file": str(run_report_file),
        "variant_reports": variant_reports,
        "teacher_pattern_contexts": _teacher_pattern_contexts(variant_reports + expanded_scope_reports),
        "skipped_candidates": skipped_candidates,
        "review_policy": "queue execution only; inspect each final net in NetEdit connection mode before adoption",
    }
    run_report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def write_expanded_scope_plain_inputs(
    *,
    raw_node_file: Path,
    raw_edge_file: Path,
    raw_connection_file: Path,
    output_dir: Path,
    expanded_rebuild_scope: object,
    approach_endpoint_rebuild_plan: object | None = None,
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
    seed_node_ids = {str(item) for item in scope.get("junction_ids", []) or [] if str(item)}
    core_junction_id = str(scope.get("core_junction_id", ""))
    requested_join_ids = scope.get("join_junction_ids", None)
    default_join_ids = [core_junction_id] if core_junction_id else scope.get("junction_ids", []) or []
    join_seed_node_ids = {
        str(item)
        for item in (requested_join_ids if requested_join_ids is not None else default_join_ids)
        if str(item)
    }
    blocked_edge_ids = {str(item) for item in scope.get("blocked_teacher_edge_ids", []) or [] if str(item)}

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

    raw_nodes = {
        node.attrib["id"]: node
        for node in ET.parse(raw_node_file).getroot()
        if node.tag == "node" and node.attrib.get("id")
    }
    edge_root = ET.Element("edges")
    endpoint_rewrites = _endpoint_rewrites(approach_endpoint_rebuild_plan)
    rewritten_endpoint_count = 0
    skipped_endpoint_rewrites = []
    for edge in selected_edges:
        copied_edge = copy.deepcopy(edge)
        edge_id = copied_edge.attrib.get("id", "")
        rewrite = endpoint_rewrites.get(edge_id)
        if rewrite is not None:
            desired_from, desired_to = rewrite
            missing_endpoint_ids = [node_id for node_id in (desired_from, desired_to) if node_id not in raw_nodes]
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

    node_root = ET.Element("nodes")
    for node_id in sorted(node_id for node_id in selected_node_ids if node_id in raw_nodes):
        node_root.append(copy.deepcopy(raw_nodes[node_id]))
    join_node_ids = sorted(node_id for node_id in join_seed_node_ids if node_id in raw_nodes)
    if len(join_node_ids) >= 2:
        join_definition = build_junction_join_definition(
            [
                {
                    "source": "teacher_guided_expanded_scope",
                    "candidate_id": core_junction_id,
                    "decision": "join",
                    "confidence": "reference_matched",
                    "node_ids": join_node_ids,
                    "reason": "teacher-guided expanded scope needs a joined candidate junction for semantic replay",
                }
            ],
            output_dir=output_dir,
            prefix="expanded_scope",
        )
        joined_scope_junction_id = _sumo_joined_cluster_id(join_node_ids)
    elif core_junction_id in raw_nodes:
        join_definition = {}
        joined_scope_junction_id = core_junction_id
    else:
        join_definition = {}
        joined_scope_junction_id = ""

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
    missing_node_ids = sorted(node_id for node_id in selected_node_ids if node_id not in raw_nodes)
    missing_blocked_edge_ids = sorted(edge_id for edge_id in blocked_edge_ids if edge_id not in selected_edge_ids)
    missing_desired_endpoint_ids = {
        str(item) for item in scope.get("missing_desired_endpoint_ids", []) or [] if str(item)
    }
    blocking_missing_node_ids = sorted(
        node_id
        for node_id in missing_node_ids
        if not (joined_scope_junction_id == core_junction_id and node_id in join_seed_node_ids)
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
        "seed_node_ids": sorted(seed_node_ids),
        "join_node_ids": sorted(join_seed_node_ids),
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
    for join in joins:
        node_root.append(join)
    ET.indent(node_root, space="    ")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(node_root).write(output_file, encoding="utf-8", xml_declaration=True)
    return output_file


def _write_joined_endpoint_edge_file(
    edge_file: Path,
    join_patch_file: Path,
    joined_junction_id: str,
    output_file: Path,
) -> tuple[Path, int, list[str], list[str]]:
    if not join_patch_file.is_file() or not joined_junction_id:
        return edge_file, 0, [], []
    source_node_ids = _joined_source_node_ids(join_patch_file, joined_junction_id)
    if not source_node_ids:
        return edge_file, 0, [], []

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
        if from_is_join_source:
            edge.set("from", joined_junction_id)
            rewrite_count += 1
        if to_is_join_source:
            edge.set("to", joined_junction_id)
            rewrite_count += 1
    if rewrite_count == 0 and not dropped_self_loop_edges:
        return edge_file, 0, [], []

    ET.indent(edge_root, space="    ")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(edge_root).write(output_file, encoding="utf-8", xml_declaration=True)
    return output_file, rewrite_count, dropped_self_loop_edges, blocking_self_loop_edge_drops


def _edge_file_ids(edge_file: Path) -> set[str]:
    try:
        return {
            edge.attrib["id"]
            for edge in ET.parse(edge_file).getroot().findall("edge")
            if edge.attrib.get("id")
        }
    except (ET.ParseError, OSError):
        return set()


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


def _joined_source_node_ids(node_file: Path, junction_id: str) -> set[str]:
    if not junction_id:
        return set()
    source_node_ids: set[str] = set()
    for join in ET.parse(node_file).getroot().findall("join"):
        node_ids = [node_id for node_id in join.attrib.get("nodes", "").split() if node_id]
        if _sumo_joined_cluster_id(node_ids) == junction_id:
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
            rewrites[edge_id] = (desired_from, desired_to)
    return rewrites


def _semantic_failure_counts(variant_reports: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for report in variant_reports:
        gate = report.get("semantic_replay_gate")
        failures = gate.get("failures", []) if isinstance(gate, dict) else []
        for failure in failures:
            if not isinstance(failure, dict):
                continue
            key = f"{failure.get('report', '')}:{failure.get('field', '')}"
            if key != ":":
                counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


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
        )
        if key in candidate
    }
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


def _teacher_guided_candidate_sort_key(candidate: dict[str, object]) -> tuple[int, int, int, int, str]:
    movement_gap = int(candidate.get("vehicle_movement_matrix_missing_count", 0) or 0)
    template_count = int(candidate.get("teacher_pattern_template_count", 0) or 0)
    candidate_nodes = candidate.get("matched_candidate_node_ids")
    candidate_node_count = len(candidate_nodes) if isinstance(candidate_nodes, list) else 1_000_000
    status_rank = 0 if candidate.get("candidate_status") in {"ready_for_teacher_guided_variant", "needs_expanded_rebuild_scope"} else 1
    return (-movement_gap, status_rank, -template_count, candidate_node_count, str(candidate.get("reference_id", "")))


def _limit_ready_repair_candidates(candidates: list[dict[str, object]], max_ready_candidates: int) -> list[dict[str, object]]:
    selected = []
    ready_count = 0
    for candidate in candidates:
        selected.append(candidate)
        if candidate.get("candidate_status") == "ready_for_teacher_guided_variant":
            ready_count += 1
        if ready_count >= max_ready_candidates:
            break
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
    exemplar_pattern_key = (
        str(movement_exemplar.get("pattern_key", ""))
        if isinstance(movement_exemplar, dict)
        else ""
    )
    pattern_key = str(record.get("pattern_key", "")) or exemplar_pattern_key
    if not pattern_key:
        return candidate
    template = pattern_templates.get(pattern_key, {})
    return {
        **candidate,
        "teacher_pattern_key": pattern_key,
        "teacher_pattern_family": str(
            template.get("pattern_family", record.get("pattern_family", ""))
        ),
        "teacher_pattern_template_count": int(template.get("count", 0) or 0),
        "teacher_pattern_template_examples": [
            str(item) for item in template.get("example_junction_ids", []) or []
        ],
    }


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
        dict.fromkeys(
            action_by_field.get(field, "inspect_junction_pattern_delta") for field in mismatch_fields
        )
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
    candidate_node_ids = [str(item) for item in case.get("matched_candidate_node_ids") or case.get("candidate_node_ids") or []]
    candidate_junction_ids = _candidate_junction_id_candidates(reference_id, candidate_node_ids)
    matched_source_node_set = set(matched_reference_source_node_ids or reference_source_node_ids)
    scope_node_ids = [node_id for node_id in candidate_node_ids if node_id in matched_source_node_set]
    if len(scope_node_ids) < 2:
        scope_node_ids = candidate_node_ids
    join_node_ids = _conservative_join_node_ids(candidate_node_ids, matched_source_node_set)
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
        missing_teacher_edge_ids = _teacher_approach_edge_ids(teacher_model)
        if candidate_node_ids:
            return {
                **base,
                "candidate_status": "needs_expanded_rebuild_scope",
                "edge_map": {},
                "missing_teacher_edge_ids": missing_teacher_edge_ids,
                "copyable_missing_teacher_edge_ids": [],
                "uncopyable_missing_teacher_edge_ids": missing_teacher_edge_ids,
                "approach_endpoint_rebuild_plan": {"status": "review", "edge_rebuilds": []},
                "expanded_rebuild_scope": {
                    "status": "review",
                    "recommended_action": "rebuild_plain_xml_scope",
                    "core_junction_id": base["junction_id"],
                    "junction_ids": sorted(dict.fromkeys(scope_node_ids)),
                    "join_junction_ids": list(dict.fromkeys(join_node_ids)),
                    "blocked_teacher_edge_ids": missing_teacher_edge_ids,
                    "missing_desired_endpoint_ids": [],
                    "reason": "candidate joined junction not found; rebuild from matched candidate source nodes",
                },
                "error": f"{type(candidate_error).__name__}: {candidate_error}",
            }
        return {
            **base,
            "candidate_status": "needs_joined_candidate_junction",
            "edge_map": {},
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
    edge_map = _teacher_candidate_edge_map(
        teacher_model,
        candidate_model,
        teacher_junction_id=reference_id,
        candidate_junction_id=candidate_junction_id,
    )
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
    movement_matrix_missing_count = max(
        0,
        int(candidate_parity.get("vehicle_movement_matrix_missing_count", 0) or 0)
        - int(teacher_parity.get("vehicle_movement_matrix_missing_count", 0) or 0),
        len(missing_teacher_movement_plan),
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
        "missing_teacher_edge_ids": missing,
        "copyable_missing_teacher_edge_ids": copyable_missing,
        "uncopyable_missing_teacher_edge_ids": uncopyable_missing,
        "vehicle_movement_matrix_missing_count": movement_matrix_missing_count,
        "missing_teacher_movement_plan_count": len(missing_teacher_movement_plan),
        "missing_teacher_movement_plan": missing_teacher_movement_plan,
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
        missing_ids = [str(item) for item in approach_endpoint_rebuild_plan.get("missing_desired_endpoint_ids", []) or []]
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
                    "edge_map_size": len(edge_map) if isinstance(edge_map, dict) else 0,
                    "missing_teacher_edge_ids": ";".join(str(item) for item in row.get("missing_teacher_edge_ids", []) or []),
                    "copyable_missing_teacher_edge_ids": ";".join(
                        str(item) for item in row.get("copyable_missing_teacher_edge_ids", []) or []
                    ),
                    "uncopyable_missing_teacher_edge_ids": ";".join(
                        str(item) for item in row.get("uncopyable_missing_teacher_edge_ids", []) or []
                    ),
                    "matched_candidate_node_ids": ";".join(str(item) for item in row.get("matched_candidate_node_ids", []) or []),
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


def _command_path(path: Path, cwd: Path) -> str:
    try:
        return str(path.resolve().relative_to(cwd.resolve()))
    except ValueError:
        return str(path)


def _stage_file(output_dir: Path, prefix: str, suffix: str) -> Path:
    path = output_dir / f"{prefix}_{suffix}"
    if len(str(path.resolve())) < 240:
        return path
    short_prefix = (prefix[:16].strip("_") or "tg")
    return output_dir / f"{short_prefix}_{suffix}"


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


def _remove_edge_lanes_from_destination_junction(root: ET.Element, edge: ET.Element) -> None:
    destination = edge.attrib.get("to", "")
    if not destination:
        return
    junction = next((item for item in root.findall("junction") if item.attrib.get("id") == destination), None)
    if junction is None:
        return
    lanes = {lane.attrib["id"] for lane in edge.findall("lane") if lane.attrib.get("id")}
    if not lanes:
        return
    inc_lanes = [lane for lane in _split(junction.attrib.get("incLanes", "")) if lane not in lanes]
    junction.set("incLanes", " ".join(inc_lanes))


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
        return f"{candidate_internal_prefix}{value[len(teacher_internal_prefix):]}"
    return value


def _touches_target_internal_subgraph(connection: ET.Element, internal_prefix: str, junction_id: str) -> bool:
    return (
        connection.attrib.get("from", "").startswith(internal_prefix)
        or connection.attrib.get("to", "").startswith(internal_prefix)
        or connection.attrib.get("via", "").startswith(internal_prefix)
        or connection.attrib.get("tl", "") == junction_id
    )


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
        ):
            if internal_replay_complete and report_name in {"pedestrian_ring", "vehicle_connection_attrs"}:
                continue
            count = int(report.get(field, 0) or 0)
            if count:
                failures.append({"report": report_name, "field": field, "count": count})

    return {"status": "fail" if failures else "pass", "failures": failures}


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

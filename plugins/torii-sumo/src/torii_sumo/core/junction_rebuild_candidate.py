from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .command_runner import run_command
from .junction_connection_audit import build_connection_signature, write_connection_signature
from .junction_movement_model import audit_movement_graph, build_movement_graph, write_movement_review
from .junction_teacher_model import extract_teacher_junction_model, match_teacher_approaches


def build_rebuild_candidate(
    *,
    net_file: Path,
    junction_id: str,
    output_dir: Path,
    prefix: str = "junction_movement_rebuild",
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

    emitted = [movement for movement in graph.get("movements", []) or [] if _should_emit(movement)]
    skipped = [movement for movement in graph.get("movements", []) or [] if not _should_emit(movement)]
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
) -> dict[str, object]:
    if not teacher_net_file.exists():
        return _failure(f"teacher net file does not exist: {teacher_net_file}")
    if not candidate_net_file.exists():
        return _failure(f"candidate net file does not exist: {candidate_net_file}")

    output_dir.mkdir(parents=True, exist_ok=True)
    repair_candidates = [
        _teacher_guided_repair_candidate(
            case=case,
            teacher_net_file=teacher_net_file,
            candidate_net_file=candidate_net_file,
        )
        for case in reference_join_audit_report.get("matched_cases", []) or []
        if isinstance(case, dict)
    ]
    ready_count = sum(
        1 for candidate in repair_candidates if candidate["candidate_status"] == "ready_for_teacher_guided_variant"
    )
    queue_file = output_dir / f"{prefix}_queue.json"
    queue_csv_file = output_dir / f"{prefix}_queue.csv"
    report = {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "teacher_net_file": str(teacher_net_file),
        "candidate_net_file": str(candidate_net_file),
        "repair_candidate_count": len(repair_candidates),
        "ready_candidate_count": ready_count,
        "blocked_candidate_count": len(repair_candidates) - ready_count,
        "queue_file": str(queue_file),
        "queue_csv_file": str(queue_csv_file),
        "repair_candidates": repair_candidates,
        "review_policy": "queue only; run teacher-guided variants and inspect NetEdit connection mode before adoption",
    }
    queue_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_teacher_guided_queue_csv(queue_csv_file, repair_candidates)
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
        if child.tag == "connection" and (
            child.attrib.get("from", "") in candidate_edges_for_cleanup or child.attrib.get("to", "") in candidate_edges_for_cleanup
        ):
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
    for edge in tree.getroot().findall("edge"):
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
    }


def write_teacher_pedestrian_ring_net(
    *,
    candidate_net_file: Path,
    output_file: Path,
    junction_id: str,
    teacher_model: dict[str, object],
    edge_map: dict[str, str],
    crossing_edge_overrides: dict[str, str | list[str]] | None = None,
) -> dict[str, object]:
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

    teacher_link_pairs = _pedestrian_tl_pairs_from_records(teacher_model.get("pedestrian_connections", []) or [], junction_id)
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
            if teacher_connection.get("tl"):
                connection.set("tl", junction_id)
                connection.set("linkIndex", str(teacher_connection.get("linkIndex", "")))
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
) -> dict[str, object]:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    candidate_tree = ET.parse(candidate_net_file)
    candidate_root = candidate_tree.getroot()
    teacher_root = ET.parse(teacher_net_file).getroot()
    internal_prefix = f":{junction_id}_"

    candidate_junction = candidate_root.find(f"junction[@id='{junction_id}']")
    teacher_junction = teacher_root.find(f"junction[@id='{junction_id}']")
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
        insert_index = list(candidate_root).index(candidate_junction)

    teacher_internal_edges = [
        edge
        for edge in teacher_root.findall("edge")
        if edge.attrib.get("id", "").startswith(internal_prefix)
    ]
    for offset, edge in enumerate(teacher_internal_edges):
        candidate_root.insert(insert_index + offset, _clone_transformed_net_element(edge, dx, dy, edge_map))

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
        if junction.attrib.get("id", "").startswith(internal_prefix)
    ]
    for offset, junction in enumerate(teacher_internal_junctions):
        candidate_root.insert(
            junction_insert_index + offset,
            _clone_transformed_junction(junction, dx, dy, edge_map, internal_prefix),
        )

    candidate_junction.attrib.clear()
    candidate_junction.attrib.update(_mapped_junction_attrs(teacher_junction, dx, dy, edge_map, internal_prefix))
    for child in list(candidate_junction):
        candidate_junction.remove(child)
    for request in teacher_junction.findall("request"):
        candidate_junction.append(ET.Element("request", dict(request.attrib)))

    removed_connections = 0
    for connection in list(candidate_root.findall("connection")):
        if _touches_target_internal_subgraph(connection, internal_prefix, junction_id):
            candidate_root.remove(connection)
            removed_connections += 1

    copied_connections = 0
    skipped_connections = []
    for connection in teacher_root.findall("connection"):
        if not _touches_target_internal_subgraph(connection, internal_prefix, junction_id):
            continue
        mapped = _mapped_connection_attrs(connection, edge_map, internal_prefix, junction_id)
        if mapped is None:
            skipped_connections.append(dict(connection.attrib))
            continue
        candidate_root.append(ET.Element("connection", mapped))
        copied_connections += 1

    teacher_tllogic = teacher_root.find(f"tlLogic[@id='{junction_id}']")
    if teacher_tllogic is not None:
        target_tllogic = candidate_root.find(f"tlLogic[@id='{junction_id}']")
        target_index = list(candidate_root).index(target_tllogic) if target_tllogic is not None else len(list(candidate_root))
        if target_tllogic is not None:
            candidate_root.remove(target_tllogic)
        candidate_root.insert(target_index, _clone_transformed_net_element(teacher_tllogic, dx, dy, edge_map))

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
        "removed_internal_junction_count": len(removed_internal_junctions),
        "copied_internal_junction_count": len(teacher_internal_junctions),
        "removed_connection_count": removed_connections,
        "copied_connection_count": copied_connections,
        "skipped_connection_count": len(skipped_connections),
        "skipped_connections": skipped_connections,
        "copied_request_count": len(teacher_junction.findall("request")),
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
    target_tl = next((tl for tl in root.findall("tlLogic") if tl.attrib.get("id") == junction_id), None)
    if target_tl is None:
        return _failure(f"tlLogic not found: {junction_id}")

    traffic_light = teacher_model.get("traffic_light", {})
    if not isinstance(traffic_light, dict):
        return _failure("teacher_model.traffic_light is missing")
    attributes = traffic_light.get("attributes", {})
    phases = traffic_light.get("phases", [])
    if not isinstance(attributes, dict) or not isinstance(phases, list):
        return _failure("teacher_model.traffic_light is invalid")

    index = list(root).index(target_tl)
    root.remove(target_tl)
    replacement = ET.Element("tlLogic", {str(key): str(value) for key, value in attributes.items()})
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
    raw_type_file: Path | None = None,
    crossing_edge_overrides: dict[str, str | list[str]] | None = None,
    replay_target_internal_subgraph: bool = False,
    netconvert_binary: str = "netconvert",
    sumo_binary: str = "sumo",
    timeout_seconds: float = 240.0,
    command_runner: Any = run_command,
) -> dict[str, object]:
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
    teacher_model = extract_teacher_junction_model(teacher_net_file, junction_id)
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
    report_file = _stage_file(output_dir, prefix, "teacher_guided_report.json")

    lane_patch_report = write_teacher_lane_patch_edges(
        raw_edge_file=raw_edge_file,
        teacher_edge_file=teacher_net_file,
        output_file=patched_edge_file,
        edge_map=edge_map,
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
        "--sidewalks.guess",
        "true",
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
    final_model = extract_teacher_junction_model(final_net_file, junction_id)
    parity = _compare_teacher_models(teacher_model, final_model)
    parity_gate_status = "pass" if all(value == 0 for value in parity["delta"].values()) else "fail"
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
            "target_internal_normalize": target_internal_normalize_report,
            "target_internal_pedestrian_ring": target_internal_pedestrian_ring_report,
            "target_internal_vehicle_connection_attrs": target_internal_vehicle_attrs_report,
            "tl_logic": tl_logic_report,
            "sumo_load": sumo_report,
            "parity": parity,
            "review_policy": "diagnostic teacher-guided variant; inspect in NetEdit connection mode before adoption",
        },
    )


def _should_emit(movement: dict[str, object]) -> bool:
    return movement.get("status") == "emit" and float(movement.get("confidence", 0.0)) >= 0.5


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
                "from": str(movement.get("source_edge_id", "")),
                "to": str(movement.get("target_edge_id", "")),
                "fromLane": "0",
                "toLane": "0",
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


def _teacher_guided_repair_candidate(
    *,
    case: dict[str, Any],
    teacher_net_file: Path,
    candidate_net_file: Path,
) -> dict[str, object]:
    junction_id = str(case.get("reference_id", ""))
    base = {
        "reference_id": junction_id,
        "junction_id": junction_id,
        "matched_candidate_node_ids": list(case.get("matched_candidate_node_ids") or case.get("candidate_node_ids") or []),
        "learned_rule": str(case.get("learned_rule", "")),
    }
    if not junction_id:
        return {**base, "candidate_status": "invalid_reference_id", "edge_map": {}, "missing_teacher_edge_ids": []}

    try:
        teacher_model = extract_teacher_junction_model(teacher_net_file, junction_id)
    except (ET.ParseError, OSError, KeyError, TypeError, ValueError) as exc:
        return {
            **base,
            "candidate_status": "teacher_model_failed",
            "edge_map": {},
            "missing_teacher_edge_ids": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        candidate_model = extract_teacher_junction_model(candidate_net_file, junction_id)
    except (ET.ParseError, OSError, KeyError, TypeError, ValueError) as exc:
        return {
            **base,
            "candidate_status": "needs_joined_candidate_junction",
            "edge_map": {},
            "missing_teacher_edge_ids": _teacher_approach_edge_ids(teacher_model),
            "error": f"{type(exc).__name__}: {exc}",
        }

    edge_map = _teacher_candidate_edge_map(teacher_model, candidate_model)
    missing = [edge_id for edge_id in _teacher_approach_edge_ids(teacher_model) if edge_id not in edge_map]
    return {
        **base,
        "candidate_status": "ready_for_teacher_guided_variant" if not missing else "edge_map_incomplete",
        "edge_map": edge_map,
        "missing_teacher_edge_ids": missing,
        "teacher_incoming_edge_count": len(_approach_edges(teacher_model, "incoming")),
        "teacher_outgoing_edge_count": len(_approach_edges(teacher_model, "outgoing")),
        "candidate_incoming_edge_count": len(_approach_edges(candidate_model, "incoming")),
        "candidate_outgoing_edge_count": len(_approach_edges(candidate_model, "outgoing")),
    }


def _teacher_candidate_edge_map(teacher_model: dict[str, object], candidate_model: dict[str, object]) -> dict[str, str]:
    edge_map: dict[str, str] = {}
    for direction in ("incoming", "outgoing"):
        edge_map.update(match_teacher_approaches(_approaches(teacher_model, direction), _approaches(candidate_model, direction)))
    return dict(sorted((source, target) for source, target in edge_map.items() if source and target))


def _teacher_approach_edge_ids(teacher_model: dict[str, object]) -> list[str]:
    return sorted(dict.fromkeys(_approach_edges(teacher_model, "incoming") + _approach_edges(teacher_model, "outgoing")))


def _write_teacher_guided_queue_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "reference_id",
                "junction_id",
                "candidate_status",
                "edge_map_size",
                "missing_teacher_edge_ids",
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
                    "edge_map_size": len(edge_map) if isinstance(edge_map, dict) else 0,
                    "missing_teacher_edge_ids": ";".join(str(item) for item in row.get("missing_teacher_edge_ids", []) or []),
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


def _clone_transformed_net_element(element: ET.Element, dx: float, dy: float, edge_map: dict[str, str]) -> ET.Element:
    clone = ET.Element(element.tag, _mapped_spatial_attrs(element.attrib, dx, dy, edge_map))
    clone.text = element.text
    clone.tail = element.tail
    for child in list(element):
        clone.append(_clone_transformed_net_element(child, dx, dy, edge_map))
    return clone


def _clone_transformed_junction(
    junction: ET.Element,
    dx: float,
    dy: float,
    edge_map: dict[str, str],
    internal_prefix: str,
) -> ET.Element:
    clone = ET.Element("junction", _mapped_junction_attrs(junction, dx, dy, edge_map, internal_prefix))
    clone.text = junction.text
    clone.tail = junction.tail
    for child in list(junction):
        clone.append(ET.Element(child.tag, dict(child.attrib)))
    return clone


def _mapped_spatial_attrs(attrs: dict[str, str], dx: float, dy: float, edge_map: dict[str, str]) -> dict[str, str]:
    mapped = dict(attrs)
    if "x" in mapped:
        mapped["x"] = _format_xy(float(mapped["x"]) + dx)
    if "y" in mapped:
        mapped["y"] = _format_xy(float(mapped["y"]) + dy)
    if "shape" in mapped:
        mapped["shape"] = _translate_shape(mapped["shape"], dx, dy)
    if "crossingEdges" in mapped:
        mapped_edges = [edge_map.get(edge, edge if edge.startswith(":") else "") for edge in _split(mapped["crossingEdges"])]
        mapped["crossingEdges"] = " ".join(edge for edge in mapped_edges if edge)
    return mapped


def _mapped_junction_attrs(
    teacher_junction: ET.Element,
    dx: float,
    dy: float,
    edge_map: dict[str, str],
    internal_prefix: str,
) -> dict[str, str]:
    attrs = _mapped_spatial_attrs(teacher_junction.attrib, dx, dy, edge_map)
    if "incLanes" in attrs:
        attrs["incLanes"] = " ".join(
            lane for lane in (_map_lane_ref(lane, edge_map, internal_prefix) for lane in _split(attrs["incLanes"])) if lane
        )
    if "intLanes" in attrs:
        attrs["intLanes"] = " ".join(
            lane for lane in (_map_lane_ref(lane, edge_map, internal_prefix) for lane in _split(attrs["intLanes"])) if lane
        )
    return attrs


def _map_lane_ref(lane_id: str, edge_map: dict[str, str], internal_prefix: str) -> str:
    if lane_id.startswith(internal_prefix):
        return lane_id
    if "_" not in lane_id:
        return ""
    edge_id, lane_index = lane_id.rsplit("_", 1)
    mapped_edge = edge_map.get(edge_id)
    return f"{mapped_edge}_{lane_index}" if mapped_edge else ""


def _mapped_connection_attrs(
    connection: ET.Element,
    edge_map: dict[str, str],
    internal_prefix: str,
    junction_id: str,
) -> dict[str, str] | None:
    mapped = dict(connection.attrib)
    for attr in ("from", "to"):
        endpoint = _map_connection_endpoint(mapped.get(attr, ""), edge_map, internal_prefix)
        if not endpoint:
            return None
        mapped[attr] = endpoint
    if mapped.get("tl") == junction_id:
        mapped["tl"] = junction_id
    if mapped.get("via") and not mapped["via"].startswith(internal_prefix):
        return None
    return mapped


def _map_connection_endpoint(value: str, edge_map: dict[str, str], internal_prefix: str) -> str:
    if value.startswith(internal_prefix):
        return value
    return edge_map.get(value, "")


def _touches_target_internal_subgraph(connection: ET.Element, internal_prefix: str, junction_id: str) -> bool:
    return (
        connection.attrib.get("from", "").startswith(internal_prefix)
        or connection.attrib.get("to", "").startswith(internal_prefix)
        or connection.attrib.get("via", "").startswith(internal_prefix)
        or connection.attrib.get("tl", "") == junction_id
    )


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


def _compare_teacher_models(teacher_model: dict[str, Any], candidate_model: dict[str, Any]) -> dict[str, object]:
    teacher_summary = _teacher_parity_summary(teacher_model)
    candidate_summary = _teacher_parity_summary(candidate_model)
    keys = sorted(set(teacher_summary) | set(candidate_summary))
    return {
        "teacher": teacher_summary,
        "candidate": candidate_summary,
        "delta": {
            key: candidate_summary.get(key, 0) - teacher_summary.get(key, 0)
            for key in keys
            if isinstance(candidate_summary.get(key, 0), int) and isinstance(teacher_summary.get(key, 0), int)
        },
    }


def _teacher_parity_summary(model: dict[str, Any]) -> dict[str, object]:
    summary = dict(model.get("summary", {}) if isinstance(model.get("summary"), dict) else {})
    traffic_light = model.get("traffic_light", {})
    phases = traffic_light.get("phases", []) if isinstance(traffic_light, dict) else []
    phase_states = [str(phase.get("state", "")) for phase in phases if isinstance(phase, dict)]
    vehicle_connections = model.get("vehicle_connections", []) if isinstance(model.get("vehicle_connections"), list) else []
    pedestrian_connections = model.get("pedestrian_connections", []) if isinstance(model.get("pedestrian_connections"), list) else []
    summary["tl_phase_state_lengths"] = sorted({len(state) for state in phase_states})
    summary["controlled_vehicle_link_count"] = _controlled_link_count(vehicle_connections)
    summary["controlled_pedestrian_link_count"] = _controlled_link_count(pedestrian_connections)
    summary["controlled_link_count"] = summary["controlled_vehicle_link_count"] + summary["controlled_pedestrian_link_count"]
    return summary


def _controlled_link_count(connections: list[object]) -> int:
    return sum(1 for connection in connections if isinstance(connection, dict) and connection.get("tl") and connection.get("linkIndex"))


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

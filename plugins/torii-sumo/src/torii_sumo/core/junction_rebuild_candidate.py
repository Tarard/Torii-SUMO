from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

from .junction_connection_audit import build_connection_signature, write_connection_signature
from .junction_movement_model import audit_movement_graph, build_movement_graph, write_movement_review


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
    candidate_edges = set(incoming) | set(outgoing)
    candidate_lane_counts = _candidate_lane_counts(candidate_model)
    if candidate_edge_file is not None:
        candidate_lane_counts.update(_edge_file_lane_counts(candidate_edge_file))

    root = ET.Element("connections")
    kept = 0
    removed = 0
    for child in ET.parse(raw_connection_file).getroot():
        if child.tag == "connection" and (
            child.attrib.get("from", "") in candidate_edges or child.attrib.get("to", "") in candidate_edges
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


def _failure(error: str) -> dict[str, object]:
    return {
        "status": "fail",
        "claim_status": "construction-invalid",
        "error": error,
    }

from __future__ import annotations

from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


def canonical_road_connectivity_bundle(
    net_file: Path,
    *,
    seed_edge_ids: list[str],
    hop_radius: int = 1,
) -> dict[str, Any]:
    root = ET.parse(net_file).getroot()
    edges = {edge.attrib["id"]: edge for edge in root.findall("edge") if edge.attrib.get("id")}
    selected = {edge_id for edge_id in seed_edge_ids if edge_id in edges and not edge_id.startswith(":")}
    for _ in range(max(0, hop_radius)):
        endpoints = {
            value
            for edge_id in selected
            for value in (edges[edge_id].attrib.get("from", ""), edges[edge_id].attrib.get("to", ""))
            if value
        }
        selected.update(
            edge_id
            for edge_id, edge in edges.items()
            if not edge_id.startswith(":")
            and (edge.attrib.get("from", "") in endpoints or edge.attrib.get("to", "") in endpoints)
        )

    selected_junction_ids = {
        value
        for edge_id in selected
        for value in (edges[edge_id].attrib.get("from", ""), edges[edge_id].attrib.get("to", ""))
        if value
    }
    selected_lane_ids = {
        lane.attrib["id"]
        for edge_id in selected
        for lane in edges[edge_id].findall("lane")
        if lane.attrib.get("id")
    }
    junctions = {
        junction.attrib["id"]: junction
        for junction in root.findall("junction")
        if junction.attrib.get("id")
    }
    connections = [
        _sorted_attrs(connection)
        for connection in root.findall("connection")
        if connection.attrib.get("from", "") in selected and connection.attrib.get("to", "") in selected
    ]
    bundle = {
        "net": _sorted_attrs(root),
        "location": _sorted_attrs(root.find("location")),
        "edges": [_canonical_edge_record(edges[edge_id]) for edge_id in sorted(selected)],
        "junctions": [
            _canonical_junction_record(junctions[junction_id], selected_lane_ids)
            for junction_id in sorted(selected_junction_ids)
            if junction_id in junctions
        ],
        "connections": sorted(connections, key=_canonical_connection_sort_key),
    }
    bundle["summary"] = {
        "edge_count": len(bundle["edges"]),
        "junction_count": len(bundle["junctions"]),
        "connection_count": len(bundle["connections"]),
        "missing_reference_count": _missing_reference_count(bundle),
    }
    return bundle


def write_road_connectivity_self_replay_net(
    teacher_net_file: Path,
    seed_edge_ids: list[str],
    output_file: Path,
    *,
    hop_radius: int = 1,
) -> dict[str, Any]:
    bundle = canonical_road_connectivity_bundle(
        teacher_net_file,
        seed_edge_ids=seed_edge_ids,
        hop_radius=hop_radius,
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root = ET.Element("net", bundle.get("net", {}))
    if bundle["location"]:
        ET.SubElement(root, "location", bundle["location"])
    for edge in bundle["edges"]:
        edge_node = ET.SubElement(root, "edge", _record_attrs(edge, "lanes"))
        for lane in edge.get("lanes", []):
            ET.SubElement(edge_node, "lane", dict(lane))
    for junction in bundle["junctions"]:
        ET.SubElement(root, "junction", dict(junction))
    for connection in bundle["connections"]:
        ET.SubElement(root, "connection", dict(connection))

    ET.indent(root, space="  ")
    ET.ElementTree(root).write(output_file, encoding="utf-8", xml_declaration=True)
    replay_bundle = canonical_road_connectivity_bundle(
        output_file,
        seed_edge_ids=seed_edge_ids,
        hop_radius=hop_radius,
    )
    parity_delta = {} if bundle == replay_bundle else {"canonical_bundle": 1}
    return {
        "status": "pass" if not parity_delta else "fail",
        "output_file": str(output_file),
        "parity_delta": parity_delta,
    }


def _canonical_edge_record(edge: ET.Element) -> dict[str, Any]:
    return {
        **_sorted_attrs(edge),
        "lanes": [_sorted_attrs(lane) for lane in sorted(edge.findall("lane"), key=_lane_sort_key)],
    }


def _canonical_junction_record(junction: ET.Element, selected_lane_ids: set[str]) -> dict[str, str]:
    record = _sorted_attrs(junction)
    record["incLanes"] = " ".join(lane_id for lane_id in record.get("incLanes", "").split() if lane_id in selected_lane_ids)
    record["intLanes"] = " ".join(lane_id for lane_id in record.get("intLanes", "").split() if lane_id in selected_lane_ids)
    return record


def _sorted_attrs(element: ET.Element | None) -> dict[str, str]:
    return {} if element is None else dict(sorted(element.attrib.items()))


def _record_attrs(record: dict[str, Any], child_key: str) -> dict[str, str]:
    return {str(key): str(value) for key, value in record.items() if key != child_key}


def _missing_reference_count(bundle: dict[str, Any]) -> int:
    edge_ids = {edge["id"] for edge in bundle["edges"]}
    lane_ids = {lane["id"] for edge in bundle["edges"] for lane in edge.get("lanes", [])}
    junction_ids = {junction["id"] for junction in bundle["junctions"]}
    missing = 0
    for edge in bundle["edges"]:
        missing += int(edge.get("from", "") not in junction_ids)
        missing += int(edge.get("to", "") not in junction_ids)
    for junction in bundle["junctions"]:
        missing += sum(1 for lane_id in str(junction.get("incLanes", "")).split() if lane_id not in lane_ids)
        missing += sum(1 for lane_id in str(junction.get("intLanes", "")).split() if lane_id not in lane_ids)
    for connection in bundle["connections"]:
        missing += int(connection.get("from", "") not in edge_ids)
        missing += int(connection.get("to", "") not in edge_ids)
    return missing


def _lane_sort_key(lane: ET.Element) -> tuple[int, str]:
    try:
        index = int(lane.attrib.get("index", "0"))
    except ValueError:
        index = 0
    return (index, lane.attrib.get("id", ""))


def _canonical_connection_sort_key(connection: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        connection.get("from", ""),
        connection.get("fromLane", ""),
        connection.get("to", ""),
        connection.get("toLane", ""),
    )

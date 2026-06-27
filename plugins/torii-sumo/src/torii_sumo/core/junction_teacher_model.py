from __future__ import annotations

from collections import Counter
import math
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


def extract_teacher_junction_model(net_file: Path, junction_id: str) -> dict[str, Any]:
    root = ET.parse(net_file).getroot()
    junction = next((node for node in root.findall("junction") if node.attrib.get("id") == junction_id), None)
    if junction is None:
        raise ValueError(f"junction not found: {junction_id}")

    edges = {edge.attrib["id"]: edge for edge in root.findall("edge") if edge.attrib.get("id")}
    lane_to_edge: dict[str, tuple[str, ET.Element, ET.Element]] = {}
    for edge_id, edge in edges.items():
        for lane in edge.findall("lane"):
            lane_id = lane.attrib.get("id")
            if lane_id:
                lane_to_edge[lane_id] = (edge_id, edge, lane)

    internal_prefix = f":{junction_id}_"
    incoming_edges = sorted(
        {
            edge_id
            for lane_id in _split(junction.attrib.get("incLanes", ""))
            if (lane_entry := lane_to_edge.get(lane_id))
            for edge_id, _edge, _lane in [lane_entry]
            if not edge_id.startswith(":")
        }
    )
    outgoing_edges = {
        edge_id
        for edge_id, edge in edges.items()
        if not edge_id.startswith(":")
        and edge.attrib.get("from") == junction_id
        and _edge_allows_non_pedestrian(edge)
    }
    for connection in root.findall("connection"):
        source = connection.attrib.get("from", "")
        target = connection.attrib.get("to", "")
        target_edge = edges.get(target)
        if source in incoming_edges and target_edge is not None and not target.startswith(":"):
            if _edge_allows_non_pedestrian(target_edge):
                outgoing_edges.add(target)

    crossings = [
        _internal_edge_record(edge, crossing=True)
        for edge in edges.values()
        if edge.attrib.get("id", "").startswith(internal_prefix) and edge.attrib.get("function") == "crossing"
    ]
    walking_areas = [
        _internal_edge_record(edge)
        for edge in edges.values()
        if edge.attrib.get("id", "").startswith(internal_prefix) and edge.attrib.get("function") == "walkingarea"
    ]
    outgoing_edges_sorted = sorted(outgoing_edges)

    vehicle_connections = []
    pedestrian_connections = []
    for connection in root.findall("connection"):
        source = connection.attrib.get("from", "")
        target = connection.attrib.get("to", "")
        if source in incoming_edges and target in outgoing_edges_sorted:
            vehicle_connections.append(_connection_record(connection))
        elif _is_pedestrian_connection(connection, edges, internal_prefix):
            pedestrian_connections.append(_connection_record(connection))

    tl_logic = next((tl for tl in root.findall("tlLogic") if tl.attrib.get("id") == junction_id), None)
    phases = [dict(phase.attrib) for phase in tl_logic.findall("phase")] if tl_logic is not None else []

    return {
        "net_file": str(net_file),
        "junction_id": junction_id,
        "approaches": {
            "incoming": [_edge_record(edges[edge_id]) for edge_id in incoming_edges],
            "outgoing": [_edge_record(edges[edge_id]) for edge_id in outgoing_edges_sorted],
        },
        "vehicle_connections": vehicle_connections,
        "crossings": crossings,
        "walking_areas": walking_areas,
        "pedestrian_connections": pedestrian_connections,
        "traffic_light": {"attributes": dict(tl_logic.attrib) if tl_logic is not None else {}, "phases": phases},
        "summary": {
            "incoming_vehicle_edge_count": len(incoming_edges),
            "outgoing_vehicle_edge_count": len(outgoing_edges_sorted),
            "vehicle_connection_count": len(vehicle_connections),
            "pedestrian_connection_count": len(pedestrian_connections),
            "crossing_count": len(crossings),
            "walkingarea_count": len(walking_areas),
            "tl_phase_count": len(phases),
            "vehicle_connection_dirs": dict(Counter(record["dir"] or "blank" for record in vehicle_connections)),
            "internal_mode_counts": _internal_mode_counts(edges.values(), internal_prefix),
        },
    }


def extract_junction_pattern_index(
    net_file: Path,
    *,
    min_approaches: int = 3,
    max_approaches: int = 4,
) -> list[dict[str, Any]]:
    root = ET.parse(net_file).getroot()
    tl_by_id = {tl.attrib["id"]: tl for tl in root.findall("tlLogic") if tl.attrib.get("id")}
    records: list[dict[str, Any]] = []
    for junction in root.findall("junction"):
        junction_id = junction.attrib.get("id", "")
        if not junction_id or junction_id.startswith(":") or junction.attrib.get("type") == "internal":
            continue

        model = extract_teacher_junction_model(net_file, junction_id)
        summary = model["summary"]
        in_edge_count = int(summary["incoming_vehicle_edge_count"])
        out_edge_count = int(summary["outgoing_vehicle_edge_count"])
        arm_count = min(in_edge_count, out_edge_count)
        if arm_count < min_approaches or arm_count > max_approaches:
            continue

        vehicle_connections = model["vehicle_connections"]
        pedestrian_connections = model["pedestrian_connections"]
        all_connections = vehicle_connections + pedestrian_connections
        controlled_connections = [
            connection for connection in all_connections if connection["tl"] and connection["linkIndex"]
        ]
        controlled_tl_ids = {connection["tl"] for connection in controlled_connections}
        dir_counts = dict(summary["vehicle_connection_dirs"])
        records.append(
            {
                "junction_id": junction_id,
                "arm_count": arm_count,
                "control_type": junction.attrib.get("type", ""),
                "in_edge_count": in_edge_count,
                "out_edge_count": out_edge_count,
                "vehicle_connection_count": int(summary["vehicle_connection_count"]),
                "dir_counts": dict(sorted(dir_counts.items())),
                "crossing_count": int(summary["crossing_count"]),
                "walkingarea_count": int(summary["walkingarea_count"]),
                "request_count": len(junction.findall("request")),
                "tl_phase_count": sum(
                    len(tl_by_id[tl_id].findall("phase")) for tl_id in controlled_tl_ids if tl_id in tl_by_id
                ),
                "controlled_link_count": len(controlled_connections),
            }
        )
    return records


def match_teacher_approaches(
    teacher_approaches: list[dict[str, Any]],
    candidate_approaches: list[dict[str, Any]],
    max_bearing_delta: float = 30.0,
) -> dict[str, str]:
    matches: dict[str, str] = {}
    used_candidates: set[str] = set()

    for teacher in sorted(teacher_approaches, key=lambda item: item.get("edge_id", "")):
        teacher_id = teacher.get("edge_id", "")
        if not teacher_id:
            continue
        exact = _find_same_source_candidate(teacher, candidate_approaches, used_candidates)
        if exact is not None:
            matches[teacher_id] = exact.get("edge_id", "")
            used_candidates.add(exact.get("edge_id", ""))
            continue

        scored = []
        for candidate in candidate_approaches:
            candidate_id = candidate.get("edge_id", "")
            if not candidate_id or candidate_id in used_candidates:
                continue
            bearing_delta = _bearing_delta(teacher.get("bearing"), candidate.get("bearing"))
            if bearing_delta is None or bearing_delta > max_bearing_delta:
                continue
            lane_delta = abs(int(teacher.get("lane_count", 0) or 0) - int(candidate.get("lane_count", 0) or 0))
            type_penalty = 25.0 if _type_mismatch(teacher, candidate) else 0.0
            scored.append((bearing_delta + lane_delta * 10.0 + type_penalty, bearing_delta, candidate_id))
        if scored:
            _score, _bearing_delta_value, candidate_id = min(scored)
            matches[teacher_id] = candidate_id
            used_candidates.add(candidate_id)

    return matches


def _split(value: str) -> list[str]:
    return [part for part in value.split() if part]


def _lane_allows_non_pedestrian(lane: ET.Element) -> bool:
    allow = set(_split(lane.attrib.get("allow", "")))
    return not allow or allow != {"pedestrian"}


def _edge_allows_non_pedestrian(edge: ET.Element) -> bool:
    lanes = edge.findall("lane")
    return not lanes or any(_lane_allows_non_pedestrian(lane) for lane in lanes)


def _edge_record(edge: ET.Element) -> dict[str, Any]:
    lanes = [_lane_record(lane) for lane in edge.findall("lane")]
    return {
        "edge_id": edge.attrib.get("id", ""),
        "from": edge.attrib.get("from", ""),
        "to": edge.attrib.get("to", ""),
        "type": edge.attrib.get("type", ""),
        "function": edge.attrib.get("function", ""),
        "bearing": _shape_bearing(lanes[0]["shape"] if lanes else ""),
        "lane_count": len(lanes),
        "lanes": lanes,
    }


def _internal_edge_record(edge: ET.Element, crossing: bool = False) -> dict[str, Any]:
    record = _edge_record(edge)
    if crossing:
        record["crossingEdges"] = _split(edge.attrib.get("crossingEdges", ""))
    return record


def _lane_record(lane: ET.Element) -> dict[str, str]:
    return {
        "id": lane.attrib.get("id", ""),
        "index": lane.attrib.get("index", ""),
        "allow": lane.attrib.get("allow", ""),
        "width": lane.attrib.get("width", ""),
        "shape": lane.attrib.get("shape", ""),
    }


def _connection_record(connection: ET.Element) -> dict[str, str]:
    return {
        "from": connection.attrib.get("from", ""),
        "to": connection.attrib.get("to", ""),
        "fromLane": connection.attrib.get("fromLane", ""),
        "toLane": connection.attrib.get("toLane", ""),
        "via": connection.attrib.get("via", ""),
        "tl": connection.attrib.get("tl", ""),
        "linkIndex": connection.attrib.get("linkIndex", ""),
        "dir": connection.attrib.get("dir", ""),
        "state": connection.attrib.get("state", ""),
    }


def _is_pedestrian_connection(
    connection: ET.Element,
    edges: dict[str, ET.Element],
    internal_prefix: str,
) -> bool:
    source = connection.attrib.get("from", "")
    target = connection.attrib.get("to", "")
    if not (source.startswith(internal_prefix) or target.startswith(internal_prefix)):
        return False
    return any(_is_pedestrian_edge(edges.get(edge_id)) for edge_id in (source, target))


def _is_pedestrian_edge(edge: ET.Element | None) -> bool:
    if edge is None:
        return False
    if edge.attrib.get("function") in {"crossing", "walkingarea"}:
        return True
    return not _edge_allows_non_pedestrian(edge)


def _internal_mode_counts(edges: Any, internal_prefix: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for edge in edges:
        if not edge.attrib.get("id", "").startswith(internal_prefix):
            continue
        for lane in edge.findall("lane"):
            modes = _split(lane.attrib.get("allow", "")) or ["all"]
            counts.update(modes)
    return dict(counts)


def _find_same_source_candidate(
    teacher: dict[str, Any],
    candidates: list[dict[str, Any]],
    used_candidates: set[str],
) -> dict[str, Any] | None:
    teacher_source = teacher.get("source_node_id")
    if not teacher_source:
        return None
    for candidate in candidates:
        candidate_id = candidate.get("edge_id", "")
        candidate_source = candidate.get("source_node_id")
        if candidate_id and candidate_id not in used_candidates and candidate_source == teacher_source:
            return candidate
    return None


def _bearing_delta(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    delta = abs(float(left) - float(right)) % 360.0
    return min(delta, 360.0 - delta)


def _type_mismatch(teacher: dict[str, Any], candidate: dict[str, Any]) -> bool:
    teacher_type = teacher.get("type")
    candidate_type = candidate.get("type")
    return bool(teacher_type and candidate_type and teacher_type != candidate_type)


def _shape_bearing(shape: str) -> float | None:
    points = []
    for point in _split(shape):
        parts = point.split(",")
        if len(parts) < 2:
            continue
        points.append((float(parts[0]), float(parts[1])))
    if len(points) < 2:
        return None
    x0, y0 = points[0]
    x1, y1 = points[-1]
    return round(math.degrees(math.atan2(y1 - y0, x1 - x0)) % 360.0, 6)

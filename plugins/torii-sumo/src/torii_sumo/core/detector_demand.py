from __future__ import annotations

import csv
import math
import re
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class EdgeInfo:
    edge_id: str
    from_node: str
    to_node: str
    allows_passenger: bool
    length: float


@dataclass(frozen=True)
class CandidateRoute:
    route_id: str
    source_edge: str
    sink_edge: str
    edges: tuple[str, ...]


@dataclass(frozen=True)
class Detector:
    detector_id: str
    source_system: str
    direction: str
    edge_id: str
    lane_id: str
    lane_position: float
    period: str
    mapping_confidence: str
    mapping_status: str


@dataclass(frozen=True)
class EdgeCount:
    edge_id: str
    entered: int
    detector_ids: tuple[str, ...]
    lane_ids: tuple[str, ...]
    begin: float
    end: float


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("_") or "unnamed"


def _row_value(row: dict[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value)
    return default


def _float_value(value: str | float | int | None, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(value: str | float | int | None, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _time_key(value: str | float | int | None) -> str:
    if value in (None, ""):
        return ""
    numeric = _float_value(value)
    return f"{numeric:g}"


def lane_allows_passenger(lane: ET.Element) -> bool:
    allow = lane.attrib.get("allow")
    disallow = lane.attrib.get("disallow", "")
    if allow:
        classes = set(allow.split())
        return bool(classes & {"passenger", "private"})
    return "passenger" not in disallow.split()


def connection_allows_passenger(connection: ET.Element) -> bool:
    allow = connection.attrib.get("allow")
    disallow = connection.attrib.get("disallow", "")
    if allow:
        classes = set(allow.split())
        return bool(classes & {"passenger", "private"})
    return "passenger" not in disallow.split()


def read_net(path: Path) -> tuple[dict[str, EdgeInfo], dict[str, set[str]]]:
    root = ET.parse(path).getroot()
    edges: dict[str, EdgeInfo] = {}
    connections: dict[str, set[str]] = {}

    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id", "")
        if not edge_id or edge.attrib.get("function") or edge_id.startswith(":"):
            continue
        passenger_lanes = [lane for lane in edge.findall("lane") if lane_allows_passenger(lane)]
        length = max((_float_value(lane.attrib.get("length")) for lane in passenger_lanes), default=0.0)
        edges[edge_id] = EdgeInfo(
            edge_id=edge_id,
            from_node=edge.attrib.get("from", ""),
            to_node=edge.attrib.get("to", ""),
            allows_passenger=bool(passenger_lanes),
            length=length,
        )

    for connection in root.findall("connection"):
        from_edge = connection.attrib.get("from", "")
        to_edge = connection.attrib.get("to", "")
        if (
            from_edge in edges
            and to_edge in edges
            and edges[from_edge].allows_passenger
            and edges[to_edge].allows_passenger
            and connection_allows_passenger(connection)
        ):
            connections.setdefault(from_edge, set()).add(to_edge)

    return edges, connections


def incoming_outgoing(connections: dict[str, set[str]]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    incoming: dict[str, set[str]] = {}
    outgoing: dict[str, set[str]] = {}
    for from_edge, to_edges in connections.items():
        outgoing.setdefault(from_edge, set()).update(to_edges)
        for to_edge in to_edges:
            incoming.setdefault(to_edge, set()).add(from_edge)
    return incoming, outgoing


def boundary_edges(edges: dict[str, EdgeInfo], connections: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    incoming, outgoing = incoming_outgoing(connections)
    passenger_edges = [edge_id for edge_id, edge in edges.items() if edge.allows_passenger]
    sources = sorted(edge_id for edge_id in passenger_edges if not incoming.get(edge_id) and outgoing.get(edge_id))
    sinks = sorted(edge_id for edge_id in passenger_edges if incoming.get(edge_id) and not outgoing.get(edge_id))
    return sources, sinks


def reverse_connections(connections: dict[str, set[str]]) -> dict[str, set[str]]:
    reversed_graph: dict[str, set[str]] = {}
    for from_edge, to_edges in connections.items():
        for to_edge in to_edges:
            reversed_graph.setdefault(to_edge, set()).add(from_edge)
    return reversed_graph


def shortest_route_to_any(
    adjacency: dict[str, set[str]],
    start_edge: str,
    target_edges: set[str],
    max_hops: int,
) -> list[str]:
    queue = deque([(start_edge, [start_edge])])
    seen = {start_edge}
    while queue:
        edge_id, route = queue.popleft()
        if edge_id in target_edges:
            return route
        if len(route) >= max_hops:
            continue
        for next_edge in sorted(adjacency.get(edge_id, set())):
            if next_edge in seen:
                continue
            seen.add(next_edge)
            queue.append((next_edge, [*route, next_edge]))
    return []


def shortest_route(
    connections: dict[str, set[str]],
    source_edge: str,
    sink_edge: str,
    max_hops: int,
) -> list[str]:
    path = shortest_route_to_any(connections, source_edge, {sink_edge}, max_hops=max_hops)
    return path if path and path[-1] == sink_edge else []


def read_detector_mapping(path: Path) -> list[Detector]:
    detectors: list[Detector] = []
    for row in read_csv_rows(path):
        status = _row_value(row, "mapping_status", "status", default="active").lower()
        edge_id = _row_value(row, "sumo_edge", "edge_id", "edge", default="")
        detector_id = _row_value(row, "detector_id", "s_idx", "id", default="")
        if not detector_id or not edge_id:
            continue
        detectors.append(
            Detector(
                detector_id=safe_id(detector_id),
                source_system=_row_value(row, "source_system", default=""),
                direction=_row_value(row, "real_direction", "direction", default=""),
                edge_id=edge_id,
                lane_id=_row_value(row, "sumo_lane", "lane_id", "lane", default=""),
                lane_position=_float_value(_row_value(row, "lane_position", "lane_pos", "pos", default="0")),
                period=_row_value(row, "period", default=""),
                mapping_confidence=_row_value(row, "mapping_confidence", "confidence", default=""),
                mapping_status=status or "active",
            )
        )
    return detectors


def active_detectors(detectors: Iterable[Detector]) -> list[Detector]:
    return [detector for detector in detectors if detector.mapping_status not in {"inactive", "out_of_scope", "ignored"}]


def build_detector_anchored_routes(
    detectors: list[Detector],
    sources: list[str],
    sinks: list[str],
    connections: dict[str, set[str]],
    max_hops: int,
) -> list[CandidateRoute]:
    reverse = reverse_connections(connections)
    source_set = set(sources)
    sink_set = set(sinks)
    routes: list[CandidateRoute] = []
    seen: set[tuple[str, ...]] = set()

    for detector in sorted(detectors, key=lambda item: item.detector_id):
        reverse_path = shortest_route_to_any(reverse, detector.edge_id, source_set, max_hops=max_hops)
        forward_path = shortest_route_to_any(connections, detector.edge_id, sink_set, max_hops=max_hops)
        if not reverse_path or not forward_path:
            continue
        route_edges = tuple([*reversed(reverse_path), *forward_path[1:]])
        if route_edges in seen:
            continue
        seen.add(route_edges)
        routes.append(
            CandidateRoute(
                route_id=f"detector_route_{detector.detector_id}",
                source_edge=route_edges[0],
                sink_edge=route_edges[-1],
                edges=route_edges,
            )
        )
    return routes


def build_boundary_routes(
    sources: list[str],
    sinks: list[str],
    connections: dict[str, set[str]],
    max_routes: int,
    max_hops: int,
    min_edges: int,
) -> list[CandidateRoute]:
    routes: list[CandidateRoute] = []
    seen: set[tuple[str, ...]] = set()
    for source_edge in sources:
        for sink_edge in sinks:
            route_edges = tuple(shortest_route(connections, source_edge, sink_edge, max_hops=max_hops))
            if len(route_edges) < min_edges or route_edges in seen:
                continue
            seen.add(route_edges)
            routes.append(
                CandidateRoute(
                    route_id=f"od_route_{len(routes):04d}",
                    source_edge=source_edge,
                    sink_edge=sink_edge,
                    edges=route_edges,
                )
            )
            if len(routes) >= max_routes:
                return routes
    return routes


def merge_routes(primary: list[CandidateRoute], secondary: list[CandidateRoute], max_routes: int) -> list[CandidateRoute]:
    routes: list[CandidateRoute] = []
    seen: set[tuple[str, ...]] = set()
    for route in [*primary, *secondary]:
        if route.edges in seen:
            continue
        seen.add(route.edges)
        routes.append(route)
        if len(routes) >= max_routes:
            return routes
    return routes


def source_sink_rows(edges: dict[str, EdgeInfo], sources: list[str], sinks: list[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for role, edge_ids in (("source", sources), ("sink", sinks)):
        for edge_id in edge_ids:
            edge = edges[edge_id]
            rows.append(
                {
                    "role": role,
                    "edge_id": edge.edge_id,
                    "from_node": edge.from_node,
                    "to_node": edge.to_node,
                    "length": f"{edge.length:.2f}",
                    "reason": "network_boundary",
                }
            )
    return rows


def route_rows(routes: list[CandidateRoute], edges: dict[str, EdgeInfo]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for route in routes:
        route_length = sum(edges[edge_id].length for edge_id in route.edges if edge_id in edges)
        rows.append(
            {
                "route_id": route.route_id,
                "source_edge": route.source_edge,
                "sink_edge": route.sink_edge,
                "edge_count": len(route.edges),
                "route_length": f"{route_length:.2f}",
                "edges": " ".join(route.edges),
            }
        )
    return rows


def route_detector_incidence(routes: list[CandidateRoute], detectors: list[Detector]) -> list[dict[str, object]]:
    detectors_by_edge: dict[str, list[Detector]] = {}
    for detector in detectors:
        detectors_by_edge.setdefault(detector.edge_id, []).append(detector)

    rows: list[dict[str, object]] = []
    for route in routes:
        route_edges = set(route.edges)
        for edge_id in route.edges:
            for detector in detectors_by_edge.get(edge_id, []):
                rows.append(
                    {
                        "route_id": route.route_id,
                        "source_edge": route.source_edge,
                        "sink_edge": route.sink_edge,
                        "detector_id": detector.detector_id,
                        "detector_edge": detector.edge_id,
                        "detector_direction": detector.direction,
                        "incidence": 1 if detector.edge_id in route_edges else 0,
                    }
                )
    return rows


def aggregate_edge_counts(rows: list[dict[str, str]], begin: float, end: float) -> list[EdgeCount]:
    totals: dict[str, int] = {}
    detector_ids: dict[str, set[str]] = {}
    lane_ids: dict[str, set[str]] = {}

    for row in rows:
        row_begin = _float_value(_row_value(row, "begin", default=str(begin)))
        row_end = _float_value(_row_value(row, "end", default=str(end)))
        if row_begin < begin or row_end > end:
            continue
        edge_id = _row_value(row, "edge_id", "sumo_edge", "edge", default="")
        if not edge_id:
            continue
        total = _int_value(_row_value(row, "expected_total", "entered", "count", "total", default="0"))
        totals[edge_id] = totals.get(edge_id, 0) + total
        detector_id = _row_value(row, "detector_id", "s_idx", "id", default="")
        if detector_id:
            detector_ids.setdefault(edge_id, set()).add(safe_id(detector_id))
        lane_id = _row_value(row, "lane_id", "sumo_lane", "lane", default="")
        if lane_id:
            lane_ids.setdefault(edge_id, set()).add(lane_id)

    edge_counts = [
        EdgeCount(
            edge_id=edge_id,
            entered=totals[edge_id],
            detector_ids=tuple(sorted(detector_ids.get(edge_id, set()))),
            lane_ids=tuple(sorted(lane_ids.get(edge_id, set()))),
            begin=begin,
            end=end,
        )
        for edge_id in sorted(totals)
    ]
    return edge_counts


def constraint_rows(edge_counts: list[EdgeCount]) -> list[dict[str, object]]:
    return [
        {
            "begin": f"{edge_count.begin:g}",
            "end": f"{edge_count.end:g}",
            "edge_id": edge_count.edge_id,
            "lane_ids": " ".join(edge_count.lane_ids),
            "detector_ids": " ".join(edge_count.detector_ids),
            "expected_total": edge_count.entered,
        }
        for edge_count in edge_counts
    ]


def write_edge_data(path: Path, edge_counts: list[EdgeCount]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("data")
    if edge_counts:
        begin = min(edge_count.begin for edge_count in edge_counts)
        end = max(edge_count.end for edge_count in edge_counts)
    else:
        begin = 0.0
        end = 0.0
    interval = ET.SubElement(root, "interval", id="detector_demand_counts", begin=f"{begin:g}", end=f"{end:g}")
    for edge_count in edge_counts:
        attrs = {
            "id": edge_count.edge_id,
            "entered": str(int(edge_count.entered)),
        }
        if edge_count.detector_ids:
            attrs["detector_ids"] = " ".join(edge_count.detector_ids)
        ET.SubElement(interval, "edge", attrs)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def e1_counts_by_detector_interval(detector_xml: Path) -> dict[tuple[str, str, str], int]:
    root = ET.parse(detector_xml).getroot()
    counts: dict[tuple[str, str, str], int] = {}
    for interval in root.findall(".//interval"):
        detector_id = safe_id(interval.attrib.get("id", ""))
        if not detector_id:
            continue
        key = (detector_id, _time_key(interval.attrib.get("begin")), _time_key(interval.attrib.get("end")))
        counts[key] = counts.get(key, 0) + _int_value(interval.attrib.get("nVehEntered"))
    return counts


def compare_expected_to_e1(
    expected_rows: list[dict[str, str]],
    detector_counts: dict[tuple[str, str, str], int],
) -> list[dict[str, object]]:
    comparisons: list[dict[str, object]] = []
    for row in expected_rows:
        detector_id = safe_id(_row_value(row, "detector_id", "s_idx", "id", default=""))
        if not detector_id:
            continue
        begin = _time_key(_row_value(row, "begin", default=""))
        end = _time_key(_row_value(row, "end", default=""))
        expected = _int_value(_row_value(row, "expected_total", "entered", "count", "total", default="0"))
        if begin or end:
            measured = detector_counts.get((detector_id, begin, end), 0)
        else:
            measured = sum(value for (current_id, _begin, _end), value in detector_counts.items() if current_id == detector_id)
        comparisons.append(
            {
                "detector_id": detector_id,
                "edge_id": _row_value(row, "edge_id", "sumo_edge", "edge", default=""),
                "begin": begin,
                "end": end,
                "expected_total": expected,
                "measured_nVehEntered": measured,
                "diff_entered_minus_expected": measured - expected,
            }
        )
    return comparisons


def geh_value(expected: float, measured: float) -> float:
    denominator = expected + measured
    if denominator <= 0:
        return 0.0
    return math.sqrt(2.0 * (measured - expected) ** 2 / denominator)


def summarize_comparison(rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows:
        return {
            "edge_rows": 0,
            "expected_total": 0,
            "measured_total": 0,
            "MAE": 0.0,
            "RMSE": 0.0,
            "max_abs_error": 0,
            "signed_bias": 0.0,
            "GEH_lt5_percent": 100.0,
        }

    expected = [float(row["expected_total"]) for row in rows]
    measured = [float(row["measured_nVehEntered"]) for row in rows]
    diffs = [m - e for e, m in zip(expected, measured)]
    abs_diffs = [abs(diff) for diff in diffs]
    squared = [diff * diff for diff in diffs]
    geh_lt5 = sum(1 for e, m in zip(expected, measured) if geh_value(e, m) < 5)
    return {
        "edge_rows": len(rows),
        "expected_total": int(sum(expected)),
        "measured_total": int(sum(measured)),
        "MAE": sum(abs_diffs) / len(rows),
        "RMSE": math.sqrt(sum(squared) / len(rows)),
        "max_abs_error": int(max(abs_diffs)),
        "signed_bias": sum(diffs) / len(rows),
        "GEH_lt5_percent": 100.0 * geh_lt5 / len(rows),
    }

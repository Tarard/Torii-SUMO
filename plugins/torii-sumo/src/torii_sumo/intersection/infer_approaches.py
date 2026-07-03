from __future__ import annotations

from collections import defaultdict, deque

from .geometry import bearing_between_xy
from .infer_core import _adjacent_highway_nodes
from .schema import Approach, IntersectionCore, OSMWay, OSMPatch


def infer_approaches(patch: OSMPatch, core: IntersectionCore) -> list[Approach]:
    highway_ways = [way for way in patch.ways.values() if "highway" in way.tags]
    adjacent = _adjacent_highway_nodes(highway_ways, core.core_osm_node_ids)
    rows = []
    used_way_ids = set()
    for neighbor_id, way_ids in adjacent.items():
        way = patch.ways[sorted(way_ids)[0]]
        terminal_id, source_way_ids, edge_way_id = _extended_vehicle_corridor_endpoint(
            patch,
            highway_ways,
            core,
            neighbor_id,
            way,
        )
        terminal = patch.nodes[terminal_id]
        endpoint_xy = (terminal.x or 0.0, terminal.y or 0.0)
        bearing = bearing_between_xy(core.center_xy, endpoint_xy)
        source_shape_xy = _approach_shape_xy(patch, core, terminal_id, source_way_ids)
        used_way_ids.update(source_way_ids)
        rows.append((bearing, neighbor_id, way, terminal_id, source_way_ids, edge_way_id, endpoint_xy, source_shape_xy, []))
    rows = _fuse_support_path_rows(
        rows,
        _crossing_support_path_rows(patch, highway_ways, core, set(adjacent), used_way_ids),
    )
    rows.sort()

    roles = _roles_for_bearings([row[0] for row in rows])
    approaches = []
    for index, ((bearing, neighbor_id, way, terminal_id, source_way_ids, edge_way_id, endpoint_xy, source_shape_xy, extra_lane_modes), role) in enumerate(
        zip(rows, roles, strict=True),
        start=1,
    ):
        lane_count = _lane_count(way.tags)
        approaches.append(
            Approach(
                approach_id=f"leg_{index}",
                role=role,
                source_way_ids=source_way_ids,
                road_name=way.tags.get("name"),
                highway_class=way.tags.get("highway", "road"),
                bearing_to_core=(bearing + 180) % 360,
                bearing_from_core=bearing,
                endpoint_xy=endpoint_xy,
                source_shape_xy=source_shape_xy,
                incoming_lane_count=lane_count,
                outgoing_lane_count=lane_count,
                incoming_extra_lane_modes=extra_lane_modes,
                outgoing_extra_lane_modes=extra_lane_modes,
                incoming_edge_ids=[f"{edge_way_id}_{terminal_id}_to_{core.core_id}"],
                outgoing_edge_ids=[f"{edge_way_id}_{core.core_id}_to_{terminal_id}"],
                oneway=way.tags.get("oneway") in {"yes", "true", "1"},
                allowed_modes=_allowed_modes(way.tags),
                turn_lanes_raw=way.tags.get("turn:lanes"),
                access_tags={key: value for key, value in way.tags.items() if key in {"access", "vehicle", "bicycle", "foot"}},
            )
        )
    return approaches


def _approach_shape_xy(
    patch: OSMPatch,
    core: IntersectionCore,
    terminal_id: str,
    source_way_ids: list[str],
) -> list[tuple[float, float]]:
    graph = _way_graph(patch, source_way_ids)
    path = _shortest_path_to_core(graph, terminal_id, set(core.core_osm_node_ids))
    if not path:
        return [_node_xy(patch, terminal_id), core.center_xy]

    points = [_node_xy(patch, node_id) for node_id in path[:-1]]
    points.append(core.center_xy)
    return _dedupe_adjacent_points(points)


def _crossing_support_path_rows(
    patch: OSMPatch,
    highway_ways: list[OSMWay],
    core: IntersectionCore,
    adjacent_node_ids: set[str],
    used_way_ids: set[str],
) -> list[tuple[float, str, OSMWay, str, list[str], str, tuple[float, float], list[tuple[float, float]], list[set[str]]]]:
    rows = []
    for way in highway_ways:
        if way.id in used_way_ids or "passenger" in _allowed_modes(way.tags):
            continue
        anchors = [
            node_id
            for node_id in way.node_refs
            if node_id in adjacent_node_ids and _is_crossing_terminal(patch.nodes[node_id].tags)
        ]
        if not anchors:
            continue
        anchor_id = min(anchors, key=lambda node_id: _distance_to_center(patch, node_id, core.center_xy))
        for terminal_id in _support_terminal_ids(patch, way, anchor_id, core.center_xy):
            if terminal_id == anchor_id:
                continue
            endpoint_xy = _node_xy(patch, terminal_id)
            bearing = bearing_between_xy(core.center_xy, endpoint_xy)
            rows.append(
                (
                    bearing,
                    anchor_id,
                    way,
                    terminal_id,
                    [way.id],
                    way.id,
                    endpoint_xy,
                    _support_shape_xy(patch, core, terminal_id, anchor_id, way.id),
                    [],
                )
            )
    return rows


def _fuse_support_path_rows(
    rows: list[tuple[float, str, OSMWay, str, list[str], str, tuple[float, float], list[tuple[float, float]], list[set[str]]]],
    support_rows: list[tuple[float, str, OSMWay, str, list[str], str, tuple[float, float], list[tuple[float, float]], list[set[str]]]],
) -> list[tuple[float, str, OSMWay, str, list[str], str, tuple[float, float], list[tuple[float, float]], list[set[str]]]]:
    fused = list(rows)
    for support in support_rows:
        support_modes = _allowed_modes(support[2].tags)
        match_index = _support_lane_match_index(fused, support)
        if match_index is None:
            fused.append(support)
            continue
        row = fused[match_index]
        fused[match_index] = (*row[:8], [_merged_support_modes(row[8], support_modes)])
    return fused


def _merged_support_modes(extra_modes: list[set[str]], support_modes: set[str]) -> set[str]:
    merged = set(support_modes)
    for modes in extra_modes:
        merged.update(modes)
    return merged


def _support_lane_match_index(
    rows: list[tuple[float, str, OSMWay, str, list[str], str, tuple[float, float], list[tuple[float, float]], list[set[str]]]],
    support: tuple[float, str, OSMWay, str, list[str], str, tuple[float, float], list[tuple[float, float]], list[set[str]]],
) -> int | None:
    return next(
        (
            index
            for index, row in enumerate(rows)
            if row[1] == support[1] and "passenger" in _allowed_modes(row[2].tags)
        ),
        None,
    )


def _support_terminal_ids(
    patch: OSMPatch,
    way: OSMWay,
    anchor_id: str,
    center_xy: tuple[float, float],
) -> list[str]:
    endpoints = [way.node_refs[0], way.node_refs[-1]]
    if anchor_id in endpoints:
        return [_far_endpoint_id(patch, way, anchor_id, center_xy)]
    return list(dict.fromkeys(endpoints))


def _support_shape_xy(
    patch: OSMPatch,
    core: IntersectionCore,
    terminal_id: str,
    anchor_id: str,
    way_id: str,
) -> list[tuple[float, float]]:
    path = _shortest_path_to_core(_way_graph(patch, [way_id]), terminal_id, {anchor_id})
    if not path:
        return [_node_xy(patch, terminal_id), core.center_xy]
    points = [_node_xy(patch, node_id) for node_id in path]
    points.append(core.center_xy)
    return _dedupe_adjacent_points(points)


def _way_graph(patch: OSMPatch, way_ids: list[str]) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = defaultdict(list)
    for way_id in way_ids:
        way = patch.ways.get(way_id)
        if way is None:
            continue
        refs = [node_id for node_id in way.node_refs if node_id in patch.nodes]
        for first, second in zip(refs, refs[1:], strict=False):
            graph[first].append(second)
            graph[second].append(first)
    return graph


def _is_crossing_terminal(tags: dict[str, str]) -> bool:
    return tags.get("highway") in {"crossing", "traffic_signals"} or "crossing" in tags


def _shortest_path_to_core(graph: dict[str, list[str]], terminal_id: str, core_ids: set[str]) -> list[str]:
    queue = deque([(terminal_id, [terminal_id])])
    seen = {terminal_id}
    while queue:
        node_id, path = queue.popleft()
        if node_id in core_ids:
            return path
        for neighbor_id in graph.get(node_id, []):
            if neighbor_id in seen:
                continue
            seen.add(neighbor_id)
            queue.append((neighbor_id, [*path, neighbor_id]))
    return []


def _node_xy(patch: OSMPatch, node_id: str) -> tuple[float, float]:
    node = patch.nodes[node_id]
    return (node.x or 0.0, node.y or 0.0)


def _dedupe_adjacent_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    deduped = []
    for point in points:
        if point != (deduped[-1] if deduped else None):
            deduped.append(point)
    return deduped


def _extended_vehicle_corridor_endpoint(
    patch: OSMPatch,
    highway_ways: list[OSMWay],
    core: IntersectionCore,
    neighbor_id: str,
    way: OSMWay,
) -> tuple[str, list[str], str]:
    if "passenger" not in _allowed_modes(way.tags):
        return neighbor_id, [way.id], way.id
    continuations = [
        candidate
        for candidate in highway_ways
        if candidate.id != way.id
        and neighbor_id in candidate.node_refs
        and "passenger" in _allowed_modes(candidate.tags)
        and _same_vehicle_corridor(way, candidate)
    ]
    if len(continuations) != 1:
        return neighbor_id, [way.id], way.id
    continuation = continuations[0]
    return _far_endpoint_id(patch, continuation, neighbor_id, core.center_xy), [way.id, continuation.id], continuation.id


def _same_vehicle_corridor(first: OSMWay, second: OSMWay) -> bool:
    if first.tags.get("highway") != second.tags.get("highway"):
        return False
    if first.tags.get("ref") and first.tags.get("ref") == second.tags.get("ref"):
        return True
    return bool(first.tags.get("name") and first.tags.get("name") == second.tags.get("name"))


def _far_endpoint_id(patch: OSMPatch, way: OSMWay, from_node_id: str, center_xy: tuple[float, float]) -> str:
    endpoints = [way.node_refs[0], way.node_refs[-1]]
    if from_node_id in endpoints and len(set(endpoints)) == 2:
        return endpoints[1] if endpoints[0] == from_node_id else endpoints[0]
    return max(endpoints, key=lambda node_id: _distance_to_center(patch, node_id, center_xy))


def _distance_to_center(patch: OSMPatch, node_id: str, center_xy: tuple[float, float]) -> float:
    node = patch.nodes[node_id]
    return ((node.x or 0.0) - center_xy[0]) ** 2 + ((node.y or 0.0) - center_xy[1]) ** 2


def _roles_for_bearings(bearings: list[float]) -> list[str]:
    if len(bearings) != 4:
        return [f"leg_{index}" for index in range(1, len(bearings) + 1)]
    return [_cardinal_role(bearing) for bearing in bearings]


def _cardinal_role(bearing: float) -> str:
    roles = ["north", "east", "south", "west"]
    return roles[int((bearing + 45) // 90) % 4]


def _lane_count(tags: dict[str, str]) -> int:
    try:
        return max(1, int(tags.get("lanes", "1")))
    except ValueError:
        return 1


def _allowed_modes(tags: dict[str, str]) -> set[str]:
    highway = tags.get("highway", "road")
    if highway == "cycleway":
        modes = {"bicycle"}
        if tags.get("foot") in {"yes", "designated", "permissive"}:
            modes.add("pedestrian")
        return modes
    if highway in {"footway", "pedestrian", "steps", "crossing"}:
        modes = {"pedestrian"}
        if tags.get("bicycle") in {"yes", "designated", "permissive"}:
            modes.add("bicycle")
        return modes
    if highway == "path":
        modes = set()
        if tags.get("foot") != "no":
            modes.add("pedestrian")
        if tags.get("bicycle") != "no":
            modes.add("bicycle")
        return modes or {"pedestrian"}
    return {"passenger"}

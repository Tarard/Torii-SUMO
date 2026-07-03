from __future__ import annotations

from .geometry import bearing_between_xy
from .infer_core import _adjacent_highway_nodes
from .schema import Approach, IntersectionCore, OSMWay, OSMPatch


def infer_approaches(patch: OSMPatch, core: IntersectionCore) -> list[Approach]:
    highway_ways = [way for way in patch.ways.values() if "highway" in way.tags]
    adjacent = _adjacent_highway_nodes(highway_ways, core.core_osm_node_ids)
    rows = []
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
        rows.append((bearing, neighbor_id, way, terminal_id, source_way_ids, edge_way_id, endpoint_xy))
    rows.sort()

    roles = _roles_for_bearings([row[0] for row in rows])
    approaches = []
    for index, ((bearing, neighbor_id, way, terminal_id, source_way_ids, edge_way_id, endpoint_xy), role) in enumerate(
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
                incoming_lane_count=lane_count,
                outgoing_lane_count=lane_count,
                incoming_edge_ids=[f"{edge_way_id}_{terminal_id}_to_{core.core_id}"],
                outgoing_edge_ids=[f"{edge_way_id}_{core.core_id}_to_{terminal_id}"],
                oneway=way.tags.get("oneway") in {"yes", "true", "1"},
                allowed_modes=_allowed_modes(way.tags),
                turn_lanes_raw=way.tags.get("turn:lanes"),
                access_tags={key: value for key, value in way.tags.items() if key in {"access", "vehicle", "bicycle", "foot"}},
            )
        )
    return approaches


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

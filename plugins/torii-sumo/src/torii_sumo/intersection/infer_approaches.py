from __future__ import annotations

from .geometry import bearing_between_xy
from .infer_core import _adjacent_highway_nodes
from .schema import Approach, IntersectionCore, OSMPatch


def infer_approaches(patch: OSMPatch, core: IntersectionCore) -> list[Approach]:
    center_id = core.core_osm_node_ids[0]
    center = patch.nodes[center_id]
    highway_ways = [way for way in patch.ways.values() if "highway" in way.tags]
    adjacent = _adjacent_highway_nodes(highway_ways, center_id)
    rows = []
    for neighbor_id, way_ids in adjacent.items():
        neighbor = patch.nodes[neighbor_id]
        bearing = bearing_between_xy((center.x or 0.0, center.y or 0.0), (neighbor.x or 0.0, neighbor.y or 0.0))
        way = patch.ways[sorted(way_ids)[0]]
        rows.append((bearing, neighbor_id, way))
    rows.sort()

    roles = _roles_for_bearings([row[0] for row in rows])
    approaches = []
    for index, ((bearing, neighbor_id, way), role) in enumerate(zip(rows, roles, strict=True), start=1):
        lane_count = _lane_count(way.tags)
        approaches.append(
            Approach(
                approach_id=f"leg_{index}",
                role=role,
                source_way_ids=[way.id],
                road_name=way.tags.get("name"),
                highway_class=way.tags.get("highway", "road"),
                bearing_to_core=(bearing + 180) % 360,
                bearing_from_core=bearing,
                incoming_lane_count=lane_count,
                outgoing_lane_count=lane_count,
                incoming_edge_ids=[f"{way.id}_{neighbor_id}_to_{center_id}"],
                outgoing_edge_ids=[f"{way.id}_{center_id}_to_{neighbor_id}"],
                oneway=way.tags.get("oneway") in {"yes", "true", "1"},
                allowed_modes={"passenger"},
                turn_lanes_raw=way.tags.get("turn:lanes"),
                access_tags={key: value for key, value in way.tags.items() if key in {"access", "vehicle", "bicycle", "foot"}},
            )
        )
    return approaches


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

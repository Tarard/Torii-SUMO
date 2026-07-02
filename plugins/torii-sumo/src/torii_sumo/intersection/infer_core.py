from __future__ import annotations

from collections import Counter, defaultdict

from .schema import IntersectionCore, OSMPatch, PatchSeed


def infer_intersection_core(patch: OSMPatch, seed: PatchSeed | None = None) -> IntersectionCore:
    highway_ways = [way for way in patch.ways.values() if "highway" in way.tags]
    incident = Counter(ref for way in highway_ways for ref in way.node_refs)
    center_id = seed.osm_node_id if seed and seed.osm_node_id else incident.most_common(1)[0][0]
    center = patch.nodes[center_id]
    adjacent = _adjacent_highway_nodes(highway_ways, center_id)
    topology_type = "T3" if len(adjacent) == 3 else ("X4" if len(adjacent) == 4 else "unknown")
    core_way_ids = sorted(
        way.id for way in highway_ways if center_id in way.node_refs
    )
    return IntersectionCore(
        core_id=f"core_{center_id}",
        center_xy=(center.x or 0.0, center.y or 0.0),
        center_latlon=(center.lat, center.lon),
        core_osm_node_ids=[center_id],
        core_way_ids=core_way_ids,
        core_radius_m=20.0,
        topology_type=topology_type,
        internal_fragment_count=max(0, len(adjacent) - 4),
        short_internal_edge_count=0,
        confidence=0.9 if topology_type in {"T3", "X4"} else 0.4,
    )


def _adjacent_highway_nodes(highway_ways, center_id: str) -> dict[str, list[str]]:
    adjacent: dict[str, list[str]] = defaultdict(list)
    for way in highway_ways:
        refs = way.node_refs
        for index, ref in enumerate(refs):
            if ref != center_id:
                continue
            for neighbor_index in (index - 1, index + 1):
                if 0 <= neighbor_index < len(refs):
                    adjacent[refs[neighbor_index]].append(way.id)
    return dict(adjacent)

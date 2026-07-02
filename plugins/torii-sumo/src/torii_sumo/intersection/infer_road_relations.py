from __future__ import annotations

from itertools import combinations

from .geometry import (
    abs_angle_between,
    classify_angle_relation,
    euclidean_distance,
    normalize_signed_angle,
    segment_distance,
    segment_intersection,
)
from .schema import (
    Approach,
    IntersectionCore,
    OSMPatch,
    RoadPairAngle,
    RoadPairDistance,
    RoadPairRelation,
    RoadPairRelationGraph,
)


def build_road_pair_relation_graph(
    patch: OSMPatch,
    core: IntersectionCore,
    approaches: list[Approach],
) -> RoadPairRelationGraph:
    relations = [_relation_for_pair(patch, core, a, b) for a, b in combinations(approaches, 2)]
    return RoadPairRelationGraph(
        relations=relations,
        missing_connection_count=sum(r.error_type == "missing_connection" for r in relations),
        wrong_connection_count=sum(r.error_type == "wrong_connection" for r in relations),
        overlap_conflict_count=sum(r.error_type == "topology_overlap" for r in relations),
        near_miss_count=sum(r.geometry_relation == "near_miss" for r in relations),
        duplicate_parallel_count=sum(r.error_type == "duplicate_parallel_edge" for r in relations),
        blocking_error_count=sum(r.error_type not in {"none"} for r in relations),
    )


def _relation_for_pair(
    patch: OSMPatch,
    core: IntersectionCore,
    road_a: Approach,
    road_b: Approach,
) -> RoadPairRelation:
    way_a = patch.ways[road_a.source_way_ids[0]]
    way_b = patch.ways[road_b.source_way_ids[0]]
    shared_nodes = sorted(set(way_a.node_refs) & set(way_b.node_refs))
    segment_a = _representative_segment(patch, way_a.node_refs, core.center_xy)
    segment_b = _representative_segment(patch, way_b.node_refs, core.center_xy)
    crossing = segment_intersection(*segment_a, *segment_b)
    min_distance = segment_distance(*segment_a, *segment_b)
    endpoint_gap = min(euclidean_distance(a, b) for a in segment_a for b in segment_b)

    signed_delta = normalize_signed_angle(road_b.bearing_from_core - road_a.bearing_from_core)
    abs_delta = abs_angle_between(road_a.bearing_from_core, road_b.bearing_from_core)
    angle_class = classify_angle_relation(abs_delta)

    if shared_nodes:
        geometry_relation = "shared_node"
        topology_relation = "connected"
        expected_relation = "should_connect"
        error_type = "none"
        suggested_fix = "none"
    elif crossing is not None:
        geometry_relation = "crossing_without_node"
        topology_relation = "disconnected"
        expected_relation = "maybe_connect"
        error_type = "topology_overlap"
        suggested_fix = "split_edge_at_crossing"
    elif endpoint_gap <= 5:
        geometry_relation = "near_miss"
        topology_relation = "disconnected"
        expected_relation = "should_connect"
        error_type = "missing_connection"
        suggested_fix = "join_nodes"
    elif angle_class in {"same_direction", "opposite_direction"} and min_distance <= 5:
        geometry_relation = "parallel"
        topology_relation = "ambiguous"
        expected_relation = "unknown"
        error_type = "duplicate_parallel_edge"
        suggested_fix = "merge_duplicate_edges"
    else:
        geometry_relation = "disjoint"
        topology_relation = "disconnected"
        expected_relation = "unknown"
        error_type = "none"
        suggested_fix = "none"

    return RoadPairRelation(
        relation_id=f"{road_a.approach_id}__{road_b.approach_id}",
        road_a_id=road_a.approach_id,
        road_b_id=road_b.approach_id,
        road_a_source_way_ids=road_a.source_way_ids,
        road_b_source_way_ids=road_b.source_way_ids,
        geometry_relation=geometry_relation,
        topology_relation=topology_relation,
        expected_relation=expected_relation,
        angle=RoadPairAngle(
            road_a_bearing_deg=road_a.bearing_from_core,
            road_b_bearing_deg=road_b.bearing_from_core,
            signed_delta_deg=signed_delta,
            abs_delta_deg=abs_delta,
            relation_class=angle_class,
            turn_angle_from_a_to_b_deg=signed_delta,
        ),
        distance=RoadPairDistance(
            endpoint_gap_m=endpoint_gap,
            min_geometry_distance_m=min_distance,
            projected_intersection_xy=crossing,
            overlap_length_m=0.0,
            overlap_ratio_a=0.0,
            overlap_ratio_b=0.0,
            crossing_point_inside_segments=crossing is not None,
            nearest_point_a_xy=segment_a[0],
            nearest_point_b_xy=segment_b[0],
        ),
        inferred_turn=_turn_from_signed_delta(signed_delta),
        error_type=error_type,
        suggested_fix=suggested_fix,
        confidence=0.9 if geometry_relation in {"shared_node", "near_miss", "crossing_without_node"} else 0.5,
        evidence=_evidence(geometry_relation, shared_nodes, endpoint_gap, crossing),
    )


def _representative_segment(patch: OSMPatch, node_refs: list[str], center_xy: tuple[float, float]):
    points = [(patch.nodes[ref].x or 0.0, patch.nodes[ref].y or 0.0) for ref in node_refs]
    if len(points) == 1:
        return (points[0], points[0])
    return max(combinations(points, 2), key=lambda pair: euclidean_distance(pair[0], pair[1]))


def _turn_from_signed_delta(delta: float) -> str:
    if abs(delta) > 155:
        return "uturn"
    if abs(delta) < 25:
        return "straight"
    return "right" if delta > 0 else "left"


def _evidence(geometry_relation: str, shared_nodes: list[str], endpoint_gap: float, crossing):
    if geometry_relation == "shared_node":
        return [f"shared_node:{node_id}" for node_id in shared_nodes]
    if geometry_relation == "near_miss":
        return [f"endpoint_gap_m:{endpoint_gap:.2f}"]
    if geometry_relation == "crossing_without_node":
        return [f"crossing_xy:{crossing[0]:.2f},{crossing[1]:.2f}"]
    return [f"geometry_relation:{geometry_relation}"]

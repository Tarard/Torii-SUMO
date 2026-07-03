from __future__ import annotations

from .geometry import normalize_signed_angle
from .schema import Approach, IntersectionCore, Movement, MovementMatrix, RoadPairRelationGraph


def core_connection_movements(movements: list[Movement]) -> list[Movement]:
    allowed = [movement for movement in movements if movement.allowed]
    vehicle = [movement for movement in allowed if "passenger" in movement.allowed_modes]
    return vehicle or allowed


def infer_movement_matrix(
    core: IntersectionCore,
    approaches: list[Approach],
    road_pair_graph: RoadPairRelationGraph,
) -> MovementMatrix:
    by_pair = {
        frozenset((relation.road_a_id, relation.road_b_id)): relation
        for relation in road_pair_graph.relations
    }
    movements: list[Movement] = []
    for source in approaches:
        for target in approaches:
            if source.approach_id == target.approach_id:
                continue
            relation = by_pair[frozenset((source.approach_id, target.approach_id))]
            allowed_modes = source.allowed_modes & target.allowed_modes
            allowed = relation.expected_relation != "should_not_connect" and bool(allowed_modes)
            signed_delta = normalize_signed_angle(target.bearing_from_core - ((source.bearing_from_core + 180) % 360))
            turn = _turn_from_signed_delta(signed_delta)
            from_lane_indices = _source_lane_indices(source, turn)
            to_lane_indices = _target_lane_indices(target, len(from_lane_indices))
            movements.append(
                Movement(
                    movement_id=f"{source.approach_id}_to_{target.approach_id}",
                    from_approach_id=source.approach_id,
                    to_approach_id=target.approach_id,
                    road_pair_relation_id=relation.relation_id,
                    turn=turn,
                    allowed=allowed,
                    from_lane_indices=from_lane_indices,
                    to_lane_indices=to_lane_indices,
                    allowed_modes=allowed_modes,
                    evidence=[f"road_pair_relation:{relation.relation_id}", "inferred_default"],
                    confidence=min(source.incoming_lane_count, target.outgoing_lane_count, 1) * relation.confidence,
                    notes=[],
                )
            )
    legal_count = sum(movement.allowed for movement in movements)
    return MovementMatrix(
        movements=movements,
        legal_movement_count=legal_count,
        forbidden_movement_count=len(movements) - legal_count,
        inferred_movement_count=len(movements),
        restriction_blocked_count=0,
    )


def _turn_from_signed_delta(delta: float) -> str:
    if abs(delta) > 155:
        return "uturn"
    if abs(delta) < 25:
        return "straight"
    return "right" if delta > 0 else "left"


def _source_lane_indices(source: Approach, turn: str) -> list[int]:
    if not source.turn_lanes_raw:
        return list(range(source.incoming_lane_count))
    matching = [
        index
        for index, raw_lane in enumerate(source.turn_lanes_raw.split("|"))
        if _lane_allows_turn(raw_lane, turn)
    ]
    return matching or list(range(source.incoming_lane_count))


def _target_lane_indices(target: Approach, source_lane_count: int) -> list[int]:
    return list(range(min(target.outgoing_lane_count, max(1, source_lane_count))))


def _lane_allows_turn(raw_lane: str, turn: str) -> bool:
    tokens = {token.strip() for token in raw_lane.split(";") if token.strip()}
    if turn == "straight":
        return bool(tokens & {"through", "straight"})
    if turn == "uturn":
        return bool(tokens & {"reverse", "uturn"})
    return turn in tokens

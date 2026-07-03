from __future__ import annotations

import math

from .schema import Approach, ControlModel, IntersectionCore, Movement, MovementMatrix, OSMPatch, TLSPhase
from .infer_movements import core_connection_movements


def infer_control_model(
    patch: OSMPatch,
    core: IntersectionCore,
    approaches: list[Approach],
    movements: MovementMatrix,
) -> ControlModel:
    signal_source = _traffic_signal_source(patch, core)
    has_signal = bool(signal_source)
    if not has_signal:
        return ControlModel(
            control_type="priority",
            source=["inferred:no_traffic_signal_tag"],
            priority_approach_ids=[approach.approach_id for approach in approaches[:1]],
            tls_id=None,
            phases=[],
            link_index_map={},
            confidence=0.6,
        )

    allowed_movements = _controlled_movements(movements.movements, approaches)
    link_index_map = {
        movement.movement_id: index for index, movement in enumerate(allowed_movements)
    }
    phase_a = "".join("G" if index % 2 == 0 else "r" for index in range(len(allowed_movements)))
    phase_b = "".join("r" if char == "G" else "G" for char in phase_a)
    return ControlModel(
        control_type="traffic_light",
        source=[signal_source],
        priority_approach_ids=[],
        tls_id=core.core_id,
        phases=[
            TLSPhase(phase_id="p0", duration=30.0, state=phase_a, movement_ids=list(link_index_map)),
            TLSPhase(phase_id="p1", duration=30.0, state=phase_b, movement_ids=list(link_index_map)),
        ],
        link_index_map=link_index_map,
        confidence=0.9,
    )


def _controlled_movements(movements: list[Movement], approaches: list[Approach]) -> list[Movement]:
    vehicle_movements = core_connection_movements(movements)
    vehicle_ids = {movement.movement_id for movement in vehicle_movements}
    approaches_by_id = {approach.approach_id: approach for approach in approaches}
    support_movements = [
        movement
        for movement in movements
        if movement.allowed
        and movement.movement_id not in vehicle_ids
        and "bicycle" in movement.allowed_modes
        and "passenger" not in movement.allowed_modes
        and _is_support_only(approaches_by_id.get(movement.from_approach_id))
        and _is_support_only(approaches_by_id.get(movement.to_approach_id))
    ]
    return [*vehicle_movements, *support_movements]


def _is_support_only(approach: Approach | None) -> bool:
    return approach is not None and "passenger" not in approach.allowed_modes


def _traffic_signal_source(patch: OSMPatch, core: IntersectionCore) -> str:
    if any(
        patch.nodes[node_id].tags.get("highway") == "traffic_signals"
        for node_id in core.core_osm_node_ids
        if node_id in patch.nodes
    ):
        return "osm:highway=traffic_signals"

    center_x, center_y = core.center_xy
    for node in patch.nodes.values():
        if node.tags.get("highway") != "traffic_signals" or node.x is None or node.y is None:
            continue
        if math.hypot(node.x - center_x, node.y - center_y) <= core.core_radius_m:
            return "osm:nearby_highway=traffic_signals"
    return ""

from pathlib import Path

from torii_sumo.intersection.infer_approaches import infer_approaches
from torii_sumo.intersection.infer_control import infer_control_model
from torii_sumo.intersection.infer_core import infer_intersection_core
from torii_sumo.intersection.infer_movements import infer_movement_matrix
from torii_sumo.intersection.infer_road_relations import build_road_pair_relation_graph
from torii_sumo.intersection.osm_patch import parse_osm_xml
from torii_sumo.intersection.schema import Movement, OSMNode, OSMWay, PatchSeed


FIXTURES = Path(__file__).parent / "fixtures"


def test_infer_movement_matrix_references_road_pair_relations() -> None:
    patch = parse_osm_xml(FIXTURES / "t3_priority.osm.xml")
    core = infer_intersection_core(patch)
    approaches = infer_approaches(patch, core)
    graph = build_road_pair_relation_graph(patch, core, approaches)

    matrix = infer_movement_matrix(core, approaches, graph)

    assert matrix.legal_movement_count == 6
    assert matrix.forbidden_movement_count == 0
    assert all(movement.road_pair_relation_id for movement in matrix.movements)
    assert all(movement.evidence for movement in matrix.movements)
    assert all(movement.confidence > 0 for movement in matrix.movements)


def test_infer_control_model_uses_osm_traffic_signal_tag() -> None:
    patch = parse_osm_xml(FIXTURES / "x4_signalized.osm.xml")
    core = infer_intersection_core(patch)
    approaches = infer_approaches(patch, core)
    graph = build_road_pair_relation_graph(patch, core, approaches)
    matrix = infer_movement_matrix(core, approaches, graph)

    control = infer_control_model(patch, core, approaches, matrix)

    assert control.control_type == "traffic_light"
    assert control.tls_id == core.core_id
    assert len(control.link_index_map) == matrix.legal_movement_count
    assert len(control.phases) == 2
    assert {len(phase.state) for phase in control.phases} == {matrix.legal_movement_count}


def test_infer_control_model_uses_nearby_osm_traffic_signal_node() -> None:
    patch = parse_osm_xml(FIXTURES / "x4_signalized.osm.xml")
    patch.nodes["1"].tags = {}
    core_x = patch.nodes["1"].x or 0.0
    core_y = patch.nodes["1"].y or 0.0
    patch.nodes["signal_near_core"] = OSMNode(
        id="signal_near_core",
        lat=48.0005,
        lon=11.0005,
        x=core_x + 10.0,
        y=core_y,
        tags={"highway": "traffic_signals"},
    )
    core = infer_intersection_core(patch)
    approaches = infer_approaches(patch, core)
    graph = build_road_pair_relation_graph(patch, core, approaches)
    matrix = infer_movement_matrix(core, approaches, graph)

    control = infer_control_model(patch, core, approaches, matrix)

    assert control.control_type == "traffic_light"
    assert "osm:nearby_highway=traffic_signals" in control.source


def test_infer_control_model_excludes_support_path_movements_from_tls() -> None:
    patch = parse_osm_xml(FIXTURES / "clustered_signalized_crossing.osm.xml")
    patch.nodes["seed"].tags = {"highway": "traffic_signals"}
    core = infer_intersection_core(patch, PatchSeed(osm_node_id="seed"))
    approaches = infer_approaches(patch, core)
    graph = build_road_pair_relation_graph(patch, core, approaches)
    matrix = infer_movement_matrix(core, approaches, graph)
    support = Movement(
        movement_id="support_path_to_support_path",
        from_approach_id="path_a",
        to_approach_id="path_b",
        road_pair_relation_id="support_pair",
        turn="straight",
        allowed=True,
        from_lane_indices=[0],
        to_lane_indices=[0],
        allowed_modes={"bicycle"},
        evidence=["fixture:support_path"],
        confidence=1.0,
    )
    matrix = matrix.model_copy(
        update={
            "movements": [*matrix.movements, support],
            "legal_movement_count": matrix.legal_movement_count + 1,
            "inferred_movement_count": matrix.inferred_movement_count + 1,
        }
    )

    control = infer_control_model(patch, core, approaches, matrix)

    indexed = {movement.movement_id: movement for movement in matrix.movements if movement.movement_id in control.link_index_map}
    assert indexed
    assert all("passenger" in movement.allowed_modes for movement in indexed.values())


def test_infer_movement_matrix_does_not_allow_cross_mode_movements() -> None:
    patch = parse_osm_xml(FIXTURES / "clustered_signalized_crossing.osm.xml")
    patch.nodes["bike"] = OSMNode(id="bike", lat=48.00075, lon=11.00035, x=100.0, y=100.0)
    patch.ways["cycleway_extra"] = OSMWay(
        id="cycleway_extra",
        node_refs=["bike", "vehicle_core"],
        tags={"highway": "cycleway", "foot": "no"},
    )
    core = infer_intersection_core(patch, PatchSeed(osm_node_id="seed"))
    approaches = infer_approaches(patch, core)
    graph = build_road_pair_relation_graph(patch, core, approaches)

    matrix = infer_movement_matrix(core, approaches, graph)
    movements_by_pair = {(movement.from_approach_id, movement.to_approach_id): movement for movement in matrix.movements}
    by_way = {approach.source_way_ids[0]: approach.approach_id for approach in approaches}
    road_id = by_way["road_ew"]
    bike_id = by_way["cycleway_extra"]

    assert movements_by_pair[(road_id, bike_id)].allowed_modes == set()
    assert movements_by_pair[(road_id, bike_id)].allowed is False

from pathlib import Path

from torii_sumo.intersection.infer_approaches import infer_approaches
from torii_sumo.intersection.infer_control import infer_control_model
from torii_sumo.intersection.infer_core import infer_intersection_core
from torii_sumo.intersection.infer_movements import infer_movement_matrix
from torii_sumo.intersection.infer_road_relations import build_road_pair_relation_graph
from torii_sumo.intersection.osm_patch import parse_osm_xml
from torii_sumo.intersection.schema import Approach, BBox, IntersectionCore, Movement, OSMNode, OSMPatch, OSMWay, PatchSeed


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


def test_infer_movement_matrix_labels_turns_from_incoming_heading() -> None:
    patch = parse_osm_xml(FIXTURES / "x4_signalized.osm.xml")
    core = infer_intersection_core(patch)
    approaches = infer_approaches(patch, core)
    graph = build_road_pair_relation_graph(patch, core, approaches)
    source = next(approach for approach in approaches if approach.endpoint_xy and approach.endpoint_xy[1] > 0)
    south = next(approach for approach in approaches if approach.endpoint_xy and approach.endpoint_xy[1] < 0)
    east = next(approach for approach in approaches if approach.endpoint_xy and approach.endpoint_xy[0] > 1)
    west = next(approach for approach in approaches if approach.endpoint_xy and approach.endpoint_xy[0] < -1)

    matrix = infer_movement_matrix(core, approaches, graph)
    by_target = {
        movement.to_approach_id: movement
        for movement in matrix.movements
        if movement.from_approach_id == source.approach_id and movement.allowed
    }

    assert by_target[south.approach_id].turn == "straight"
    assert by_target[east.approach_id].turn == "left"
    assert by_target[west.approach_id].turn == "right"


def test_infer_movement_matrix_uses_turn_lanes_for_source_lane_indices() -> None:
    patch = parse_osm_xml(FIXTURES / "x4_signalized.osm.xml")
    patch.ways["10"].tags.update({"lanes": "3", "turn:lanes": "left|through|right"})
    core = infer_intersection_core(patch)
    approaches = infer_approaches(patch, core)
    graph = build_road_pair_relation_graph(patch, core, approaches)
    source = next(approach for approach in approaches if approach.endpoint_xy and approach.endpoint_xy[1] > 0)

    matrix = infer_movement_matrix(core, approaches, graph)
    by_turn = {
        movement.turn: movement
        for movement in matrix.movements
        if movement.from_approach_id == source.approach_id and movement.allowed
    }

    assert by_turn["left"].from_lane_indices == [0]
    assert by_turn["straight"].from_lane_indices == [1]
    assert by_turn["right"].from_lane_indices == [2]


def test_infer_control_model_uses_osm_traffic_signal_tag() -> None:
    patch = parse_osm_xml(FIXTURES / "x4_signalized.osm.xml")
    core = infer_intersection_core(patch)
    approaches = infer_approaches(patch, core)
    graph = build_road_pair_relation_graph(patch, core, approaches)
    matrix = infer_movement_matrix(core, approaches, graph)

    control = infer_control_model(patch, core, approaches, matrix)

    assert control.control_type == "traffic_light"
    assert control.tls_id == core.core_id
    assert "synthetic:alternating_placeholder" in control.source
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


def test_infer_control_model_includes_known_bicycle_support_movements() -> None:
    patch = parse_osm_xml(FIXTURES / "x4_signalized.osm.xml")
    core = infer_intersection_core(patch)
    approaches = infer_approaches(patch, core)
    graph = build_road_pair_relation_graph(patch, core, approaches)
    matrix = infer_movement_matrix(core, approaches, graph)
    support_a = approaches[0].model_copy(update={"approach_id": "support_a", "allowed_modes": {"bicycle"}})
    support_b = approaches[1].model_copy(update={"approach_id": "support_b", "allowed_modes": {"bicycle"}})
    support = Movement(
        movement_id="support_a_to_support_b",
        from_approach_id="support_a",
        to_approach_id="support_b",
        road_pair_relation_id="support_pair",
        turn="straight",
        allowed=True,
        from_lane_indices=[0],
        to_lane_indices=[0],
        allowed_modes={"bicycle"},
        evidence=["fixture:signalized_support_path"],
        confidence=1.0,
    )
    matrix = matrix.model_copy(
        update={
            "movements": [*matrix.movements, support],
            "legal_movement_count": matrix.legal_movement_count + 1,
            "inferred_movement_count": matrix.inferred_movement_count + 1,
        }
    )

    control = infer_control_model(patch, core, [*approaches, support_a, support_b], matrix)

    assert support.movement_id in control.link_index_map


def test_infer_control_model_keeps_one_same_way_bicycle_support_turnaround() -> None:
    patch = parse_osm_xml(FIXTURES / "x4_signalized.osm.xml")
    core = infer_intersection_core(patch)
    approaches = infer_approaches(patch, core)
    graph = build_road_pair_relation_graph(patch, core, approaches)
    matrix = infer_movement_matrix(core, approaches, graph)
    support_a = approaches[0].model_copy(
        update={"approach_id": "support_a", "source_way_ids": ["cycleway_1"], "allowed_modes": {"bicycle"}}
    )
    support_b = approaches[1].model_copy(
        update={"approach_id": "support_b", "source_way_ids": ["cycleway_1"], "allowed_modes": {"bicycle"}}
    )
    support_ab = Movement(
        movement_id="support_a_to_support_b",
        from_approach_id="support_a",
        to_approach_id="support_b",
        road_pair_relation_id="support_pair",
        turn="straight",
        allowed=True,
        from_lane_indices=[0],
        to_lane_indices=[0],
        allowed_modes={"bicycle"},
        evidence=["fixture:same_way_support_path"],
        confidence=1.0,
    )
    support_ba = support_ab.model_copy(
        update={
            "movement_id": "support_b_to_support_a",
            "from_approach_id": "support_b",
            "to_approach_id": "support_a",
        }
    )
    matrix = matrix.model_copy(
        update={
            "movements": [*matrix.movements, support_ab, support_ba],
            "legal_movement_count": matrix.legal_movement_count + 2,
            "inferred_movement_count": matrix.inferred_movement_count + 2,
        }
    )

    control = infer_control_model(patch, core, [*approaches, support_a, support_b], matrix)

    controlled_support = {support_ab.movement_id, support_ba.movement_id} & set(control.link_index_map)
    assert controlled_support == {support_ab.movement_id}


def test_infer_control_model_keeps_one_mixed_support_feeder_to_same_bike_corridor() -> None:
    patch = parse_osm_xml(FIXTURES / "x4_signalized.osm.xml")
    core = infer_intersection_core(patch)
    approaches = infer_approaches(patch, core)
    graph = build_road_pair_relation_graph(patch, core, approaches)
    matrix = infer_movement_matrix(core, approaches, graph)
    feeder = approaches[0].model_copy(
        update={"approach_id": "feeder", "source_way_ids": ["feeder_path"], "allowed_modes": {"bicycle", "pedestrian"}}
    )
    bike_a = approaches[1].model_copy(
        update={"approach_id": "bike_a", "source_way_ids": ["cycleway_1"], "allowed_modes": {"bicycle"}}
    )
    bike_b = approaches[2].model_copy(
        update={"approach_id": "bike_b", "source_way_ids": ["cycleway_1"], "allowed_modes": {"bicycle"}}
    )
    feeder_to_a = Movement(
        movement_id="feeder_to_bike_a",
        from_approach_id="feeder",
        to_approach_id="bike_a",
        road_pair_relation_id="support_pair_a",
        turn="right",
        allowed=True,
        from_lane_indices=[0],
        to_lane_indices=[0],
        allowed_modes={"bicycle"},
        evidence=["fixture:mixed_support_feeder"],
        confidence=1.0,
    )
    feeder_to_b = feeder_to_a.model_copy(
        update={
            "movement_id": "feeder_to_bike_b",
            "to_approach_id": "bike_b",
            "road_pair_relation_id": "support_pair_b",
        }
    )
    matrix = matrix.model_copy(
        update={
            "movements": [*matrix.movements, feeder_to_a, feeder_to_b],
            "legal_movement_count": matrix.legal_movement_count + 2,
            "inferred_movement_count": matrix.inferred_movement_count + 2,
        }
    )

    control = infer_control_model(patch, core, [*approaches, feeder, bike_a, bike_b], matrix)

    controlled_support = {feeder_to_a.movement_id, feeder_to_b.movement_id} & set(control.link_index_map)
    assert controlled_support == {feeder_to_a.movement_id}


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


def test_infer_movement_matrix_blocks_disjoint_same_mode_movements() -> None:
    patch = OSMPatch(
        nodes={
            "a": OSMNode(id="a", lat=0, lon=0, x=0, y=0, tags={}),
            "b": OSMNode(id="b", lat=0, lon=0, x=100, y=0, tags={}),
        },
        ways={
            "wa": OSMWay(id="wa", node_refs=["a"], tags={"highway": "residential"}),
            "wb": OSMWay(id="wb", node_refs=["b"], tags={"highway": "residential"}),
        },
        relations={},
        bbox=BBox(min_lon=0, min_lat=0, max_lon=0, max_lat=0),
    )
    core = IntersectionCore(
        core_id="core",
        center_xy=(0, 0),
        core_osm_node_ids=[],
        core_way_ids=["wa", "wb"],
        core_radius_m=20,
        topology_type="unknown",
        internal_fragment_count=0,
        short_internal_edge_count=0,
        confidence=0.5,
    )
    approaches = [
        _approach("a", "wa", 0),
        _approach("b", "wb", 90),
    ]
    graph = build_road_pair_relation_graph(patch, core, approaches)

    matrix = infer_movement_matrix(core, approaches, graph)

    assert {relation.expected_relation for relation in graph.relations} == {"unknown"}
    assert [movement.allowed for movement in matrix.movements] == [False, False]


def _approach(approach_id: str, way_id: str, bearing: float) -> Approach:
    return Approach(
        approach_id=approach_id,
        role=approach_id,
        source_way_ids=[way_id],
        road_name=None,
        highway_class="residential",
        bearing_to_core=(bearing + 180) % 360,
        bearing_from_core=bearing,
        incoming_lane_count=1,
        outgoing_lane_count=1,
        incoming_edge_ids=[f"{approach_id}_in"],
        outgoing_edge_ids=[f"{approach_id}_out"],
        oneway=False,
        allowed_modes={"passenger"},
        access_tags={},
    )

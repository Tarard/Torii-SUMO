from pathlib import Path

from torii_sumo.intersection.infer_approaches import infer_approaches
from torii_sumo.intersection.infer_control import infer_control_model
from torii_sumo.intersection.infer_core import infer_intersection_core
from torii_sumo.intersection.infer_movements import infer_movement_matrix
from torii_sumo.intersection.infer_road_relations import build_road_pair_relation_graph
from torii_sumo.intersection.osm_patch import parse_osm_xml


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

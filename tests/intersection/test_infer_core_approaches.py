from pathlib import Path

from torii_sumo.intersection.infer_approaches import infer_approaches
from torii_sumo.intersection.infer_core import infer_intersection_core
from torii_sumo.intersection.osm_patch import parse_osm_xml


FIXTURES = Path(__file__).parent / "fixtures"


def test_infer_core_and_approaches_for_t3_priority_fixture() -> None:
    patch = parse_osm_xml(FIXTURES / "t3_priority.osm.xml")
    core = infer_intersection_core(patch)
    approaches = infer_approaches(patch, core)

    assert core.core_osm_node_ids == ["1"]
    assert core.topology_type == "T3"
    assert len(approaches) == 3
    assert [approach.role for approach in approaches] == ["leg_1", "leg_2", "leg_3"]


def test_infer_core_and_approaches_for_x4_priority_fixture() -> None:
    patch = parse_osm_xml(FIXTURES / "x4_priority.osm.xml")
    core = infer_intersection_core(patch)
    approaches = infer_approaches(patch, core)

    assert core.core_osm_node_ids == ["1"]
    assert core.topology_type == "X4"
    assert {approach.role for approach in approaches} == {"north", "east", "south", "west"}
    assert {approach.highway_class for approach in approaches} == {"primary", "secondary"}

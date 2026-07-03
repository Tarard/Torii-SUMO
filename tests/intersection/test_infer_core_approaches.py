from pathlib import Path

from torii_sumo.intersection.infer_approaches import infer_approaches
from torii_sumo.intersection.infer_core import infer_intersection_core
from torii_sumo.intersection.osm_patch import parse_osm_xml
from torii_sumo.intersection.schema import OSMNode, OSMWay, PatchSeed


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


def test_infer_core_expands_seed_to_nearby_connected_cluster_boundary() -> None:
    patch = parse_osm_xml(FIXTURES / "clustered_signalized_crossing.osm.xml")
    core = infer_intersection_core(patch, PatchSeed(osm_node_id="seed"))
    approaches = infer_approaches(patch, core)

    assert set(core.core_osm_node_ids) == {"seed", "crossing", "vehicle_core"}
    assert core.topology_type == "X4"
    assert len(approaches) == 4
    assert {approach.highway_class for approach in approaches} == {"secondary", "tertiary", "residential"}
    assert all("path_a" not in approach.source_way_ids for approach in approaches)


def test_infer_approaches_represents_complex_cluster_boundary_without_crashing() -> None:
    patch = parse_osm_xml(FIXTURES / "clustered_signalized_crossing.osm.xml")
    patch.nodes["extra"] = OSMNode(id="extra", lat=48.00075, lon=11.00035, x=100.0, y=100.0)
    patch.ways["road_extra"] = OSMWay(
        id="road_extra",
        node_refs=["extra", "vehicle_core"],
        tags={"highway": "service"},
    )

    core = infer_intersection_core(patch, PatchSeed(osm_node_id="seed"))
    approaches = infer_approaches(patch, core)

    assert core.topology_type == "complex"
    assert len(approaches) == 5
    assert approaches[-1].role == "leg_5"


def test_infer_approaches_preserves_pedestrian_and_bicycle_modes() -> None:
    patch = parse_osm_xml(FIXTURES / "clustered_signalized_crossing.osm.xml")
    patch.nodes["bike"] = OSMNode(id="bike", lat=48.00075, lon=11.00035, x=100.0, y=100.0)
    patch.ways["cycleway_extra"] = OSMWay(
        id="cycleway_extra",
        node_refs=["bike", "vehicle_core"],
        tags={"highway": "cycleway", "foot": "no"},
    )
    patch.nodes["foot"] = OSMNode(id="foot", lat=48.00025, lon=11.00035, x=-100.0, y=-100.0)
    patch.ways["footway_extra"] = OSMWay(
        id="footway_extra",
        node_refs=["foot", "vehicle_core"],
        tags={"highway": "footway", "bicycle": "yes"},
    )

    core = infer_intersection_core(patch, PatchSeed(osm_node_id="seed"))
    approaches = infer_approaches(patch, core)
    modes_by_way = {approach.source_way_ids[0]: approach.allowed_modes for approach in approaches}

    assert modes_by_way["cycleway_extra"] == {"bicycle"}
    assert modes_by_way["footway_extra"] == {"bicycle", "pedestrian"}
    assert modes_by_way["road_ew"] == {"passenger"}

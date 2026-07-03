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


def test_infer_approaches_extends_vehicle_corridor_across_short_split_node() -> None:
    patch = parse_osm_xml(FIXTURES / "clustered_signalized_crossing.osm.xml")
    patch.nodes["outer"] = OSMNode(id="outer", lat=48.00055, lon=10.99950, x=-90.0, y=0.0)
    patch.ways["road_west_outer"] = OSMWay(
        id="road_west_outer",
        node_refs=["outer", "west"],
        tags={"highway": "secondary", "name": "Ring Road", "ref": "B 13", "lanes": "4"},
    )
    patch.ways["road_ew"].tags.update({"name": "Ring Road", "ref": "B 13"})

    core = infer_intersection_core(patch, PatchSeed(osm_node_id="seed"))
    approaches = infer_approaches(patch, core)
    west = next(approach for approach in approaches if "road_west_outer" in approach.source_way_ids)

    assert west.source_way_ids == ["road_ew", "road_west_outer"]
    assert west.incoming_edge_ids == ["road_west_outer_outer_to_core_seed"]
    assert west.outgoing_edge_ids == ["road_west_outer_core_seed_to_outer"]
    assert west.endpoint_xy == (-90.0, 0.0)
    assert west.source_shape_xy == [(-90.0, 0.0), (patch.nodes["west"].x, patch.nodes["west"].y), core.center_xy]


def test_infer_approaches_fuses_support_path_at_crossing_terminal() -> None:
    patch = parse_osm_xml(FIXTURES / "clustered_signalized_crossing.osm.xml")
    patch.nodes["west"].tags = {"highway": "crossing", "crossing": "traffic_signals"}
    patch.nodes["side_path"] = OSMNode(id="side_path", lat=48.00055, lon=10.99950, x=-90.0, y=0.0)
    patch.ways["path_side"] = OSMWay(
        id="path_side",
        node_refs=["side_path", "west"],
        tags={"highway": "path", "foot": "designated", "bicycle": "designated"},
    )

    core = infer_intersection_core(patch, PatchSeed(osm_node_id="seed"))
    approaches = infer_approaches(patch, core)
    west = next(
        approach
        for approach in approaches
        if "road_ew" in approach.source_way_ids and approach.endpoint_xy and approach.endpoint_xy[0] < 0
    )

    assert not [approach for approach in approaches if approach.source_way_ids == ["path_side"]]
    assert west.incoming_extra_lane_modes == [{"bicycle", "pedestrian"}]
    assert west.outgoing_extra_lane_modes == [{"bicycle", "pedestrian"}]


def test_infer_approaches_fuses_both_sides_of_support_path_crossing() -> None:
    patch = parse_osm_xml(FIXTURES / "clustered_signalized_crossing.osm.xml")
    patch.nodes["west"].tags = {"highway": "crossing", "crossing": "traffic_signals"}
    patch.nodes["side_a"] = OSMNode(id="side_a", lat=48.00055, lon=10.99950, x=-90.0, y=0.0)
    patch.nodes["side_b"] = OSMNode(id="side_b", lat=48.00055, lon=10.99980, x=-40.0, y=0.0)
    patch.ways["path_crossing"] = OSMWay(
        id="path_crossing",
        node_refs=["side_a", "west", "side_b"],
        tags={"highway": "path", "foot": "designated", "bicycle": "designated"},
    )

    core = infer_intersection_core(patch, PatchSeed(osm_node_id="seed"))
    approaches = infer_approaches(patch, core)
    west = next(
        approach
        for approach in approaches
        if "road_ew" in approach.source_way_ids and approach.endpoint_xy and approach.endpoint_xy[0] < 0
    )

    assert not [approach for approach in approaches if approach.source_way_ids == ["path_crossing"]]
    assert west.incoming_extra_lane_modes == [{"bicycle", "pedestrian"}]
    assert west.outgoing_extra_lane_modes == [{"bicycle", "pedestrian"}]


def test_infer_approaches_fuses_crossing_support_path_into_vehicle_lanes() -> None:
    patch = parse_osm_xml(FIXTURES / "clustered_signalized_crossing.osm.xml")
    patch.nodes["west"].tags = {"highway": "crossing", "crossing": "traffic_signals"}
    patch.nodes["side_path"] = OSMNode(id="side_path", lat=48.00055, lon=10.99950, x=-90.0, y=0.0)
    patch.ways["path_side"] = OSMWay(
        id="path_side",
        node_refs=["side_path", "west"],
        tags={"highway": "path", "foot": "designated", "bicycle": "designated"},
    )

    core = infer_intersection_core(patch, PatchSeed(osm_node_id="seed"))
    approaches = infer_approaches(patch, core)
    west = next(
        approach
        for approach in approaches
        if "road_ew" in approach.source_way_ids and approach.endpoint_xy and approach.endpoint_xy[0] < 0
    )

    assert not [approach for approach in approaches if approach.source_way_ids == ["path_side"]]
    assert {"bicycle", "pedestrian"} in west.incoming_extra_lane_modes
    assert {"bicycle", "pedestrian"} in west.outgoing_extra_lane_modes

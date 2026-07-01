from pathlib import Path

from torii_sumo.core.road_connectivity_teacher_model import (
    canonical_road_connectivity_bundle,
    compare_road_connectivity_bundles,
    summarize_net_road_lane_model_templates,
    summarize_road_lane_model_templates,
    write_road_connectivity_self_replay_net,
)


def test_canonical_road_connectivity_bundle_extracts_edge_chain_and_connections(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net version="1.20">
  <edge id="west" from="w" to="j1" name="Main"><lane id="west_0" index="0" allow="passenger" speed="13.89" shape="-20,0 -10,0"/></edge>
  <edge id="mid" from="j1" to="j2" name="Main"><lane id="mid_0" index="0" allow="passenger" speed="13.89" shape="-10,0 0,0"/></edge>
  <edge id="east" from="j2" to="e" name="Main"><lane id="east_0" index="0" allow="passenger" speed="13.89" shape="0,0 10,0"/></edge>
  <edge id="sidewalk" from="w" to="j2" type="highway.footway"><lane id="sidewalk_0" index="0" allow="pedestrian" shape="-20,2 0,2"/></edge>
  <edge id=":j1_0" function="internal"><lane id=":j1_0_0" index="0" shape="-10,0 -9,0"/></edge>
  <junction id="w" type="dead_end" x="-20" y="0" incLanes="" intLanes=""/>
  <junction id="j1" type="priority" x="-10" y="0" incLanes="west_0" intLanes=":j1_0_0"/>
  <junction id="j2" type="priority" x="0" y="0" incLanes="mid_0 sidewalk_0" intLanes=""/>
  <junction id="e" type="dead_end" x="10" y="0" incLanes="east_0" intLanes=""/>
  <connection from="west" to="mid" fromLane="0" toLane="0" dir="s"/>
  <connection from="mid" to="east" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )

    bundle = canonical_road_connectivity_bundle(net_file, seed_edge_ids=["mid"], hop_radius=1)

    assert [edge["id"] for edge in bundle["edges"]] == ["east", "mid", "sidewalk", "west"]
    assert bundle["connections"] == [
        {"dir": "s", "from": "mid", "fromLane": "0", "to": "east", "toLane": "0"},
        {"dir": "s", "from": "west", "fromLane": "0", "to": "mid", "toLane": "0"},
    ]
    assert bundle["summary"] == {
        "edge_count": 4,
        "junction_count": 4,
        "connection_count": 2,
        "missing_reference_count": 0,
        "seed_edge_count": 1,
        "missing_seed_edge_ids": [],
    }


def test_canonical_road_connectivity_bundle_reports_missing_seed_edges(tmp_path: Path) -> None:
    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a" from="n1" to="n2"><lane id="a_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="n1" type="dead_end" x="0" y="0" incLanes="" intLanes=""/>
  <junction id="n2" type="dead_end" x="10" y="0" incLanes="a_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    bundle = canonical_road_connectivity_bundle(net_file, seed_edge_ids=["a", "missing"], hop_radius=1)

    assert bundle["summary"]["seed_edge_count"] == 2
    assert bundle["summary"]["missing_seed_edge_ids"] == ["missing"]


def test_compare_road_connectivity_bundles_reports_exact_edge_and_connection_delta(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="a" from="n1" to="n2"><lane id="a_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="b" from="n2" to="n3"><lane id="b_0" index="0" allow="passenger" shape="10,0 20,0"/></edge>
  <junction id="n1" type="dead_end" x="0" y="0" incLanes="" intLanes=""/>
  <junction id="n2" type="priority" x="10" y="0" incLanes="a_0" intLanes=""/>
  <junction id="n3" type="dead_end" x="20" y="0" incLanes="b_0" intLanes=""/>
  <connection from="a" to="b" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net.write_text(
        """<net>
  <edge id="a" from="n1" to="n2"><lane id="a_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="c" from="n2" to="n4"><lane id="c_0" index="0" allow="passenger" shape="10,0 20,1"/></edge>
  <junction id="n1" type="dead_end" x="0" y="0" incLanes="" intLanes=""/>
  <junction id="n2" type="priority" x="10" y="0" incLanes="a_0" intLanes=""/>
  <junction id="n4" type="dead_end" x="20" y="1" incLanes="c_0" intLanes=""/>
  <connection from="a" to="c" fromLane="0" toLane="0" dir="r"/>
</net>""",
        encoding="utf-8",
    )
    teacher = canonical_road_connectivity_bundle(teacher_net, seed_edge_ids=["a", "b"], hop_radius=1)
    candidate = canonical_road_connectivity_bundle(candidate_net, seed_edge_ids=["a", "b"], hop_radius=1)

    report = compare_road_connectivity_bundles(teacher, candidate)

    assert report == {
        "status": "fail",
        "candidate_missing_seed_edge_ids": ["b"],
        "edge_ids": {"missing_in_candidate": ["b"], "extra_in_candidate": ["c"]},
        "common_edge_geometry_mismatches": [],
        "connections": {
            "missing_in_candidate": [{"dir": "s", "from": "a", "fromLane": "0", "to": "b", "toLane": "0"}],
            "extra_in_candidate": [{"dir": "r", "from": "a", "fromLane": "0", "to": "c", "toLane": "0"}],
        },
        "summary": {
            "teacher_edge_count": 2,
            "candidate_edge_count": 2,
            "common_edge_count": 1,
            "common_edge_geometry_mismatch_count": 0,
            "teacher_connection_count": 1,
            "candidate_connection_count": 1,
        },
    }


def test_compare_road_connectivity_bundles_reports_same_id_geometry_mismatch(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    teacher_net.write_text(
        """<net>
  <location netOffset="-100,-100"/>
  <edge id="a" from="n1" to="n2" type="highway.tertiary"><lane id="a_0" index="0" allow="pedestrian" disallow="truck" shape="100,100 110,100"/></edge>
  <junction id="n1" type="dead_end" x="100" y="100" incLanes="" intLanes=""/>
  <junction id="n2" type="dead_end" x="110" y="100" incLanes="a_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )
    candidate_net.write_text(
        """<net>
  <location netOffset="-200,-200"/>
  <edge id="a" from="n3" to="n4" type="highway.service">
    <lane id="a_0" index="0" shape="0,0 11,4"/>
    <lane id="a_1" index="1" allow="bicycle" shape="0,1 11,5"/>
  </edge>
  <junction id="n3" type="dead_end" x="0" y="0" incLanes="" intLanes=""/>
  <junction id="n4" type="dead_end" x="11" y="4" incLanes="a_0 a_1" intLanes=""/>
</net>""",
        encoding="utf-8",
    )
    teacher = canonical_road_connectivity_bundle(teacher_net, seed_edge_ids=["a"], hop_radius=1)
    candidate = canonical_road_connectivity_bundle(candidate_net, seed_edge_ids=["a"], hop_radius=1)

    report = compare_road_connectivity_bundles(teacher, candidate, geometry_tolerance=0.5)

    assert report["status"] == "fail"
    assert report["common_edge_geometry_mismatches"] == [
        {
            "edge_id": "a",
            "endpoint_delta": 4.123106,
            "teacher_from": "n1",
            "candidate_from": "n3",
            "teacher_to": "n2",
            "candidate_to": "n4",
            "teacher_type": "highway.tertiary",
            "candidate_type": "highway.service",
            "teacher_lane_count": 1,
            "candidate_lane_count": 2,
            "teacher_lane_signature": ["index=0|allow=pedestrian|disallow=truck"],
            "candidate_lane_signature": ["index=0|allow=|disallow=", "index=1|allow=bicycle|disallow="],
        }
    ]
    assert report["summary"]["common_edge_geometry_mismatch_count"] == 1


def test_summarize_road_lane_model_templates_groups_type_and_lane_signature(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a" from="n1" to="n2" type="cycleway.track|highway.tertiary">
    <lane id="a_0" index="0" allow="pedestrian" shape="0,0 10,0"/>
    <lane id="a_1" index="1" allow="bicycle" shape="0,1 10,1"/>
  </edge>
  <edge id="b" from="n2" to="n3" type="cycleway.track|highway.tertiary">
    <lane id="b_0" index="0" allow="pedestrian" shape="10,0 20,0"/>
    <lane id="b_1" index="1" allow="bicycle" shape="10,1 20,1"/>
  </edge>
  <edge id="c" from="n3" to="n4" type="highway.service">
    <lane id="c_0" index="0" disallow="tram" shape="20,0 30,0"/>
  </edge>
  <junction id="n1" type="dead_end" x="0" y="0" incLanes="" intLanes=""/>
  <junction id="n2" type="priority" x="10" y="0" incLanes="a_0 a_1" intLanes=""/>
  <junction id="n3" type="priority" x="20" y="0" incLanes="b_0 b_1" intLanes=""/>
  <junction id="n4" type="dead_end" x="30" y="0" incLanes="c_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )
    bundle = canonical_road_connectivity_bundle(net_file, seed_edge_ids=["b"], hop_radius=1)

    templates = summarize_road_lane_model_templates(bundle)

    assert templates == [
        {
            "type": "cycleway.track|highway.tertiary",
            "lane_signature": [
                "index=0|allow=pedestrian|disallow=",
                "index=1|allow=bicycle|disallow=",
            ],
            "count": 2,
            "example_edge_ids": ["a", "b"],
        },
        {
            "type": "highway.service",
            "lane_signature": ["index=0|allow=|disallow=tram"],
            "count": 1,
            "example_edge_ids": ["c"],
        },
    ]


def test_summarize_net_road_lane_model_templates_excludes_internal_edges(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a" from="n1" to="n2" type="cycleway.track|highway.tertiary">
    <lane id="a_0" index="0" allow="pedestrian" shape="0,0 10,0"/>
    <lane id="a_1" index="1" allow="bicycle" shape="0,1 10,1"/>
  </edge>
  <edge id="b" from="n2" to="n3" type="cycleway.track|highway.tertiary">
    <lane id="b_0" index="0" allow="pedestrian" shape="10,0 20,0"/>
    <lane id="b_1" index="1" allow="bicycle" shape="10,1 20,1"/>
  </edge>
  <edge id=":n2_0" function="internal">
    <lane id=":n2_0_0" index="0" allow="passenger" shape="10,0 11,0"/>
  </edge>
  <edge id="c" from="n3" to="n4" type="highway.residential">
    <lane id="c_0" index="0" allow="passenger" shape="20,0 30,0"/>
  </edge>
</net>""",
        encoding="utf-8",
    )

    templates = summarize_net_road_lane_model_templates(net_file)

    assert templates == [
        {
            "type": "cycleway.track|highway.tertiary",
            "lane_signature": [
                "index=0|allow=pedestrian|disallow=",
                "index=1|allow=bicycle|disallow=",
            ],
            "count": 2,
            "example_edge_ids": ["a", "b"],
        },
        {
            "type": "highway.residential",
            "lane_signature": ["index=0|allow=passenger|disallow="],
            "count": 1,
            "example_edge_ids": ["c"],
        },
    ]


def test_write_road_connectivity_self_replay_net_round_trips_bundle(tmp_path: Path) -> None:
    teacher = tmp_path / "teacher.net.xml"
    replay = tmp_path / "replay.net.xml"
    teacher.write_text(
        """<net version="1.20" junctionCornerDetail="5">
  <edge id="a" from="n1" to="n2"><lane id="a_0" index="0" allow="passenger" speed="13.89" length="10" shape="0,0 10,0"/></edge>
  <edge id="b" from="n2" to="n3"><lane id="b_0" index="0" allow="passenger" speed="13.89" length="10" shape="10,0 20,0"/></edge>
  <junction id="n1" type="dead_end" x="0" y="0" incLanes="" intLanes=""/>
  <junction id="n2" type="priority" x="10" y="0" incLanes="a_0" intLanes=""/>
  <junction id="n3" type="dead_end" x="20" y="0" incLanes="b_0" intLanes=""/>
  <connection from="a" to="b" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )

    report = write_road_connectivity_self_replay_net(teacher, ["a"], replay, hop_radius=1)

    assert report["status"] == "pass"
    assert replay.exists()
    assert canonical_road_connectivity_bundle(
        teacher,
        seed_edge_ids=["a"],
        hop_radius=1,
    ) == canonical_road_connectivity_bundle(replay, seed_edge_ids=["a"], hop_radius=1)


def test_road_connectivity_bundle_projects_connections_to_road_level_attrs(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a" from="n1" to="n2"><lane id="a_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="b" from="n2" to="n3"><lane id="b_0" index="0" allow="passenger" shape="10,0 20,0"/></edge>
  <edge id=":n2_0" function="internal"><lane id=":n2_0_0" index="0" allow="passenger" shape="10,0 11,0"/></edge>
  <junction id="n1" type="dead_end" x="0" y="0" incLanes="" intLanes=""/>
  <junction id="n2" type="traffic_light" x="10" y="0" incLanes="a_0" intLanes=":n2_0_0"/>
  <junction id="n3" type="dead_end" x="20" y="0" incLanes="b_0" intLanes=""/>
  <tlLogic id="n2" type="static" programID="0" offset="0"><phase duration="30" state="G"/></tlLogic>
  <connection from="a" to="b" fromLane="0" toLane="0" via=":n2_0_0" tl="n2" linkIndex="0" state="O" dir="s"/>
</net>""",
        encoding="utf-8",
    )

    bundle = canonical_road_connectivity_bundle(net_file, seed_edge_ids=["a"], hop_radius=1)

    assert bundle["connections"] == [
        {"dir": "s", "from": "a", "fromLane": "0", "state": "O", "to": "b", "toLane": "0"}
    ]
    junctions = {junction["id"]: junction for junction in bundle["junctions"]}
    assert junctions["n2"]["requests"] == [{"cont": "0", "foes": "0", "index": "0", "response": "0"}]

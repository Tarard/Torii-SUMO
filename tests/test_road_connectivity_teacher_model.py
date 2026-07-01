from pathlib import Path
import xml.etree.ElementTree as ET

from torii_sumo.core.road_connectivity_teacher_model import (
    build_road_lane_template_edge_subset_repair_candidates,
    build_road_lane_template_repair_candidates,
    build_road_template_repair_queue,
    canonical_road_connectivity_bundle,
    compare_net_road_template_parity,
    compare_road_template_summaries,
    compare_road_connectivity_bundles,
    evaluate_road_template_repair_promotion,
    run_road_lane_template_repair_probe,
    summarize_net_road_connection_templates,
    summarize_net_road_lane_model_templates,
    summarize_road_lane_model_templates,
    write_road_lane_template_repair_candidate,
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


def test_summarize_net_road_connection_templates_groups_road_level_movements(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a" from="n1" to="n2" type="highway.tertiary">
    <lane id="a_0" index="0" allow="passenger" shape="0,0 10,0"/>
  </edge>
  <edge id="b" from="n2" to="n3" type="highway.residential">
    <lane id="b_0" index="0" allow="passenger" shape="10,0 20,0"/>
  </edge>
  <edge id="c" from="n4" to="n2" type="highway.tertiary">
    <lane id="c_0" index="0" allow="passenger" shape="0,5 10,0"/>
  </edge>
  <edge id=":n2_0" function="internal">
    <lane id=":n2_0_0" index="0" allow="passenger" shape="10,0 11,0"/>
  </edge>
  <connection from="a" to="b" fromLane="0" toLane="0" dir="s" via=":n2_0_0" tl="n2" linkIndex="0"/>
  <connection from="c" to="b" fromLane="0" toLane="0" dir="s"/>
  <connection from="b" to="a" fromLane="0" toLane="0" dir="t"/>
  <connection from="a" to=":n2_0" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )

    templates = summarize_net_road_connection_templates(net_file)

    assert templates == [
        {
            "dir": "s",
            "from_type": "highway.tertiary",
            "from_lane": "0",
            "from_lane_signature": ["index=0|allow=passenger|disallow="],
            "to_type": "highway.residential",
            "to_lane": "0",
            "to_lane_signature": ["index=0|allow=passenger|disallow="],
            "count": 2,
            "example_connections": ["a[0]->b[0]", "c[0]->b[0]"],
        },
        {
            "dir": "t",
            "from_type": "highway.residential",
            "from_lane": "0",
            "from_lane_signature": ["index=0|allow=passenger|disallow="],
            "to_type": "highway.tertiary",
            "to_lane": "0",
            "to_lane_signature": ["index=0|allow=passenger|disallow="],
            "count": 1,
            "example_connections": ["b[0]->a[0]"],
        },
    ]


def test_compare_road_template_summaries_reports_key_level_parity() -> None:
    teacher_templates = [
        {"type": "highway.service", "lane_signature": ["vehicle"], "count": 10},
        {"type": "highway.footway", "lane_signature": ["pedestrian"], "count": 4},
    ]
    candidate_templates = [
        {"type": "highway.service", "lane_signature": ["vehicle"], "count": 7},
        {"type": "highway.path", "lane_signature": ["pedestrian bicycle"], "count": 3},
    ]

    report = compare_road_template_summaries(
        teacher_templates,
        candidate_templates,
        key_fields=["type", "lane_signature"],
    )

    assert report == {
        "status": "fail",
        "missing_template_count": 1,
        "extra_template_count": 1,
        "common_template_count": 1,
        "common_count_delta_sum": 3,
        "missing_templates": [
            {"type": "highway.footway", "lane_signature": ["pedestrian"], "count": 4}
        ],
        "extra_templates": [
            {"type": "highway.path", "lane_signature": ["pedestrian bicycle"], "count": 3}
        ],
    }


def test_compare_net_road_template_parity_reports_lane_and_connection_delta(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="a" from="n1" to="n2" type="highway.service">
    <lane id="a_0" index="0" allow="passenger" shape="0,0 10,0"/>
  </edge>
  <edge id="b" from="n2" to="n3" type="highway.service">
    <lane id="b_0" index="0" allow="passenger" shape="10,0 20,0"/>
  </edge>
  <edge id="foot" from="n2" to="n4" type="highway.footway">
    <lane id="foot_0" index="0" allow="pedestrian" shape="10,0 10,5"/>
  </edge>
  <connection from="a" to="b" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net.write_text(
        """<net>
  <edge id="a" from="n1" to="n2" type="highway.service">
    <lane id="a_0" index="0" allow="passenger" shape="0,0 10,0"/>
  </edge>
  <edge id="b" from="n2" to="n3" type="highway.residential">
    <lane id="b_0" index="0" allow="passenger" shape="10,0 20,0"/>
  </edge>
  <connection from="a" to="b" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )

    report = compare_net_road_template_parity(teacher_net, candidate_net)

    assert report["status"] == "fail"
    assert report["gate"] == {
        "road_layer_status": "fail",
        "can_enter_junction_replay": False,
        "blocking_reason": "road_template_parity_failed",
        "lane_missing_template_count": 1,
        "connection_missing_template_count": 1,
        "lane_extra_template_count": 1,
        "connection_extra_template_count": 1,
        "lane_common_count_delta_sum": 1,
        "connection_common_count_delta_sum": 0,
    }
    assert report["lane_template_summary"]["teacher_edge_count"] == 3
    assert report["lane_template_summary"]["candidate_edge_count"] == 2
    assert report["lane_template_summary"]["parity"]["missing_template_count"] == 1
    assert report["lane_template_summary"]["parity"]["extra_template_count"] == 1
    assert report["lane_template_summary"]["parity"]["common_count_delta_sum"] == 1
    assert report["connection_template_summary"]["teacher_connection_count"] == 1
    assert report["connection_template_summary"]["candidate_connection_count"] == 1
    assert report["connection_template_summary"]["parity"]["missing_template_count"] == 1
    assert report["connection_template_summary"]["parity"]["extra_template_count"] == 1
    assert report["connection_template_summary"]["parity"]["common_template_count"] == 0
    assert {item["layer"] for item in report["repair_queue"]} == {"lane", "connection"}
    assert {item["difference"] for item in report["repair_queue"]} == {
        "missing_teacher_template",
        "extra_candidate_template",
    }


def test_build_road_template_repair_queue_prioritizes_road_layer_deltas() -> None:
    parity_report = {
        "lane_template_summary": {
            "parity": {
                "missing_templates": [
                    {"type": "highway.footway", "lane_signature": ["pedestrian"], "count": 4}
                ],
                "extra_templates": [
                    {"type": "highway.path", "lane_signature": ["bicycle"], "count": 2}
                ],
            }
        },
        "connection_template_summary": {
            "parity": {
                "missing_templates": [
                    {"dir": "s", "from_type": "highway.service", "to_type": "highway.service", "count": 6}
                ],
                "extra_templates": [
                    {"dir": "t", "from_type": "highway.service", "to_type": "highway.service", "count": 1}
                ],
            }
        },
    }

    queue = build_road_template_repair_queue(parity_report, max_items=3)

    assert queue == [
        {
            "layer": "connection",
            "difference": "missing_teacher_template",
            "priority": 6,
            "template": {
                "dir": "s",
                "from_type": "highway.service",
                "to_type": "highway.service",
                "count": 6,
            },
        },
        {
            "layer": "lane",
            "difference": "missing_teacher_template",
            "priority": 4,
            "template": {
                "type": "highway.footway",
                "lane_signature": ["pedestrian"],
                "count": 4,
            },
        },
        {
            "layer": "lane",
            "difference": "extra_candidate_template",
            "priority": 2,
            "template": {
                "type": "highway.path",
                "lane_signature": ["bicycle"],
                "count": 2,
            },
        },
    ]


def test_build_road_lane_template_repair_candidates_pairs_same_type_lane_signatures() -> None:
    parity_report = {
        "lane_template_summary": {
            "parity": {
                "missing_templates": [
                    {
                        "type": "highway.service",
                        "lane_signature": [
                            "index=0|allow=|disallow=pedestrian tram rail_urban rail rail_electric rail_fast ship cable_car subway"
                        ],
                        "count": 944,
                    }
                ],
                "extra_templates": [
                    {
                        "type": "highway.service",
                        "lane_signature": [
                            "index=0|allow=pedestrian passenger delivery bicycle|disallow="
                        ],
                        "count": 1288,
                    }
                ],
            }
        }
    }

    candidates = build_road_lane_template_repair_candidates(parity_report)

    assert candidates == [
        {
            "action": "replace_lane_signature",
            "type": "highway.service",
            "priority": 944,
            "candidate_count": 1288,
            "teacher_count": 944,
            "from_lane_signature": [
                "index=0|allow=pedestrian passenger delivery bicycle|disallow="
            ],
            "to_lane_signature": [
                "index=0|allow=|disallow=pedestrian tram rail_urban rail rail_electric rail_fast ship cable_car subway"
            ],
        }
    ]


def test_write_road_lane_template_repair_candidate_applies_teacher_lane_signature(
    tmp_path: Path,
) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    output_net = tmp_path / "candidate.repaired.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="service_a" type="highway.service">
    <lane id="service_a_0" index="0" allow="pedestrian passenger delivery bicycle" speed="5.0" length="25.0"/>
  </edge>
  <edge id="service_b" type="highway.service">
    <lane id="service_b_0" index="0" allow="pedestrian passenger delivery bicycle" speed="5.0" length="25.0"/>
  </edge>
  <edge id="residential" type="highway.residential">
    <lane id="residential_0" index="0" allow="pedestrian passenger delivery bicycle" speed="5.0" length="25.0"/>
  </edge>
</net>""",
        encoding="utf-8",
    )
    repair_candidates = [
        {
            "action": "replace_lane_signature",
            "type": "highway.service",
            "from_lane_signature": [
                "index=0|allow=pedestrian passenger delivery bicycle|disallow="
            ],
            "to_lane_signature": [
                "index=0|allow=|disallow=pedestrian tram rail_urban rail rail_electric rail_fast ship cable_car subway"
            ],
        }
    ]

    report = write_road_lane_template_repair_candidate(
        candidate_net,
        output_net,
        repair_candidates,
    )

    root = ET.parse(output_net).getroot()
    service_lane = root.find("./edge[@id='service_a']/lane")
    residential_lane = root.find("./edge[@id='residential']/lane")
    assert report["status"] == "pass"
    assert report["changed_edge_count"] == 2
    assert report["changed_lane_count"] == 2
    assert service_lane.attrib.get("allow") is None
    assert service_lane.attrib["disallow"].startswith("pedestrian tram")
    assert residential_lane.attrib["allow"] == "pedestrian passenger delivery bicycle"


def test_edge_subset_lane_template_repair_only_changes_teacher_confirmed_edges(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    output_net = tmp_path / "candidate.edge_subset.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="fix_me" type="highway.service">
    <lane id="fix_me_0" index="0" allow="passenger" speed="5.0" length="25.0"/>
  </edge>
</net>""",
        encoding="utf-8",
    )
    candidate_net.write_text(
        """<net>
  <edge id="fix_me" type="highway.service">
    <lane id="fix_me_0" index="0" allow="pedestrian passenger" speed="5.0" length="25.0"/>
  </edge>
  <edge id="leave_me" type="highway.service">
    <lane id="leave_me_0" index="0" allow="pedestrian passenger" speed="5.0" length="25.0"/>
  </edge>
</net>""",
        encoding="utf-8",
    )
    parity_report = compare_net_road_template_parity(teacher_net, candidate_net)

    repair_candidates = build_road_lane_template_edge_subset_repair_candidates(
        teacher_net,
        candidate_net,
        parity_report,
    )
    report = write_road_lane_template_repair_candidate(
        candidate_net,
        output_net,
        [repair_candidates[0]],
    )

    root = ET.parse(output_net).getroot()
    fixed_lane = root.find("./edge[@id='fix_me']/lane")
    untouched_lane = root.find("./edge[@id='leave_me']/lane")
    assert repair_candidates[0]["edge_ids"] == ["fix_me"]
    assert repair_candidates[0]["edge_count"] == 1
    assert report["changed_edge_count"] == 1
    assert report["changed_lane_count"] == 1
    assert fixed_lane.attrib["allow"] == "passenger"
    assert untouched_lane.attrib["allow"] == "pedestrian passenger"


def test_evaluate_road_template_repair_promotion_blocks_worsened_common_delta() -> None:
    before = {
        "gate": {
            "lane_missing_template_count": 104,
            "lane_extra_template_count": 49,
            "lane_common_count_delta_sum": 1759,
            "connection_missing_template_count": 1282,
            "connection_extra_template_count": 822,
            "connection_common_count_delta_sum": 1388,
        }
    }
    after = {
        "gate": {
            "lane_missing_template_count": 103,
            "lane_extra_template_count": 48,
            "lane_common_count_delta_sum": 2103,
            "connection_missing_template_count": 1263,
            "connection_extra_template_count": 803,
            "connection_common_count_delta_sum": 1899,
        }
    }

    report = evaluate_road_template_repair_promotion(before, after)

    assert report == {
        "status": "fail",
        "claim_status": "diagnostic-demo",
        "metric_scope": "road",
        "promotion_status": "blocked",
        "reason": "road_template_gate_metric_worsened",
        "before_score": 5404,
        "after_score": 6219,
        "score_delta": 815,
        "improved_metrics": {
            "lane_missing_template_count": -1,
            "lane_extra_template_count": -1,
            "connection_missing_template_count": -19,
            "connection_extra_template_count": -19,
        },
        "worsened_metrics": {
            "lane_common_count_delta_sum": 344,
            "connection_common_count_delta_sum": 511,
        },
    }


def test_evaluate_road_template_repair_promotion_passes_non_worsening_improvement() -> None:
    before = {
        "gate": {
            "lane_missing_template_count": 2,
            "lane_extra_template_count": 1,
            "lane_common_count_delta_sum": 0,
            "connection_missing_template_count": 3,
            "connection_extra_template_count": 0,
            "connection_common_count_delta_sum": 0,
        }
    }
    after = {
        "gate": {
            "lane_missing_template_count": 1,
            "lane_extra_template_count": 1,
            "lane_common_count_delta_sum": 0,
            "connection_missing_template_count": 3,
            "connection_extra_template_count": 0,
            "connection_common_count_delta_sum": 0,
        }
    }

    report = evaluate_road_template_repair_promotion(before, after)

    assert report["status"] == "pass"
    assert report["promotion_status"] == "pass"
    assert report["reason"] == "road_template_gate_improved"
    assert report["before_score"] == 6
    assert report["after_score"] == 5
    assert report["improved_metrics"] == {"lane_missing_template_count": -1}
    assert report["worsened_metrics"] == {}


def test_evaluate_road_template_repair_promotion_lane_scope_ignores_connection_regression() -> None:
    before = {
        "gate": {
            "lane_missing_template_count": 2,
            "lane_extra_template_count": 1,
            "lane_common_count_delta_sum": 0,
            "connection_missing_template_count": 1,
            "connection_extra_template_count": 0,
            "connection_common_count_delta_sum": 0,
        }
    }
    after = {
        "gate": {
            "lane_missing_template_count": 1,
            "lane_extra_template_count": 1,
            "lane_common_count_delta_sum": 0,
            "connection_missing_template_count": 1,
            "connection_extra_template_count": 0,
            "connection_common_count_delta_sum": 5,
        }
    }

    road_report = evaluate_road_template_repair_promotion(before, after)
    lane_report = evaluate_road_template_repair_promotion(before, after, metric_scope="lane")

    assert road_report["promotion_status"] == "blocked"
    assert road_report["reason"] == "road_template_gate_metric_worsened"
    assert lane_report["metric_scope"] == "lane"
    assert lane_report["status"] == "pass"
    assert lane_report["promotion_status"] == "pass"
    assert lane_report["reason"] == "road_template_gate_improved"
    assert lane_report["before_score"] == 3
    assert lane_report["after_score"] == 2
    assert lane_report["improved_metrics"] == {"lane_missing_template_count": -1}
    assert lane_report["worsened_metrics"] == {}


def test_run_road_lane_template_repair_probe_promotes_safe_candidate(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="service_a" type="highway.service">
    <lane id="service_a_0" index="0" allow="passenger" speed="5.0" length="25.0"/>
  </edge>
</net>""",
        encoding="utf-8",
    )
    candidate_net.write_text(
        """<net>
  <edge id="service_a" type="highway.service">
    <lane id="service_a_0" index="0" allow="pedestrian passenger" speed="5.0" length="25.0"/>
  </edge>
</net>""",
        encoding="utf-8",
    )

    report = run_road_lane_template_repair_probe(
        teacher_net,
        candidate_net,
        tmp_path / "probe",
        prefix="demo",
    )

    best_variant = Path(report["best_variant_file"])
    repaired_lane = ET.parse(best_variant).getroot().find("./edge[@id='service_a']/lane")
    assert report["status"] == "pass"
    assert report["road_lane_template_repair_status"] == "evaluated"
    assert report["repair_scope"] == "teacher_edge_subset"
    assert report["promotion_metric_scope"] == "lane"
    assert report["candidate_count"] == 1
    assert report["pass_candidate_count"] == 1
    assert report["blocked_candidate_count"] == 0
    assert report["best_candidate_index"] == 1
    assert best_variant.name == "demo_001.net.xml"
    assert repaired_lane.attrib["allow"] == "passenger"
    assert report["candidates"][0]["promotion_gate"]["promotion_status"] == "pass"
    assert report["candidates"][0]["promotion_gate"]["before_score"] == 2
    assert report["candidates"][0]["promotion_gate"]["after_score"] == 0


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

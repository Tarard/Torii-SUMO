import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from torii_sumo.core.junction_rebuild_candidate import (
    _approach_endpoint_rebuild_plan,
    _compare_teacher_models,
    _netedit_review_actions,
    _teacher_guided_semantics_gate,
    _stage_file,
    build_rebuild_candidate,
    build_teacher_guided_repair_queue,
    build_teacher_guided_junction_variant,
    build_tls_connection_repair_variant,
    run_teacher_guided_repair_queue,
    write_expanded_scope_plain_inputs,
    write_teacher_target_internal_replay_net,
    write_teacher_connection_plan,
    write_teacher_lane_patch_edges,
    write_teacher_pedestrian_ring_net,
    write_teacher_tllogic_net,
    write_teacher_vehicle_connection_attrs_net,
)
from torii_sumo.core.reference_join_audit import audit_reference_join_patterns


def test_build_tls_connection_repair_variant_restores_unique_connection_control_attrs(tmp_path: Path) -> None:
    source_net = tmp_path / "source.net.xml"
    source_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <edge id="right" from="j" to="c"><lane id="right_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0" tl="tlsA" linkIndex="3" linkIndex2="9" dir="s" state="O" pass="true" allow="passenger"/>
  <connection from="in" to="right" fromLane="0" toLane="0" dir="r" state="M"/>
  <tlLogic id="tlsA" type="actuated" programID="0" offset="5">
    <phase duration="4" minDur="2" maxDur="7" state="G"/>
  </tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <edge id="right" from="j" to="c"><lane id="right_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0" uncontrolled="true"/>
  <connection from="in" to="right" fromLane="0" toLane="0" uncontrolled="true"/>
  <tlLogic id="old" type="static" programID="0"><phase duration="1" state="r"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )

    report = build_tls_connection_repair_variant(
        source_net_file=source_net,
        candidate_net_file=candidate_net,
        output_dir=tmp_path / "out",
        prefix="demo",
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["source_tls_controlled_connection_count"] == 1
    assert report["candidate_tls_controlled_connection_count_before"] == 0
    assert report["candidate_tls_controlled_connection_count_after"] == 1
    assert report["updated_connection_count"] == 1
    assert report["copied_tllogic_count"] == 1
    root = ET.parse(report["variant_file"]).getroot()
    repaired = root.find("connection[@from='in'][@to='out']")
    assert repaired.attrib["tl"] == "tlsA"
    assert repaired.attrib["linkIndex"] == "3"
    assert repaired.attrib["linkIndex2"] == "9"
    assert repaired.attrib["dir"] == "s"
    assert repaired.attrib["state"] == "O"
    assert repaired.attrib["pass"] == "true"
    assert repaired.attrib["allow"] == "passenger"
    assert "uncontrolled" not in repaired.attrib
    untouched = root.find("connection[@from='in'][@to='right']")
    assert untouched.attrib["uncontrolled"] == "true"
    target_tls = root.find("tlLogic[@id='tlsA']")
    assert target_tls.attrib["type"] == "actuated"
    assert target_tls.find("phase").attrib["minDur"] == "2"


def test_build_tls_connection_repair_variant_can_remap_tls_without_copying_raw_tllogic(tmp_path: Path) -> None:
    source_net = tmp_path / "source.net.xml"
    source_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0" tl="rawTls" linkIndex="4" dir="l" state="o"/>
  <tlLogic id="rawTls" type="actuated" programID="0"><phase duration="4" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <tlLogic id="aggTls" type="static" programID="0"><phase duration="1" state="r"/></tlLogic>
  <connection from="in" to="out" fromLane="0" toLane="0" uncontrolled="true"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_tls_connection_repair_variant(
        source_net_file=source_net,
        candidate_net_file=candidate_net,
        output_dir=tmp_path / "out",
        prefix="demo",
        tls_id_map={"rawTls": "aggTls"},
        copy_unmapped_tls=False,
    )

    root = ET.parse(report["variant_file"]).getroot()
    repaired = root.find("connection[@from='in'][@to='out']")
    assert repaired.attrib["tl"] == "aggTls"
    assert repaired.attrib["linkIndex"] == "4"
    assert root.find("tlLogic[@id='rawTls']") is None
    assert root.find("tlLogic[@id='aggTls']").attrib["type"] == "static"
    assert report["copied_tllogic_count"] == 0
    assert report["replaced_tllogic_count"] == 0
    assert report["skipped_unmapped_tls_connection_count"] == 0


def test_build_tls_connection_repair_variant_can_require_target_link_index_capacity(tmp_path: Path) -> None:
    source_net = tmp_path / "source.net.xml"
    source_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0" tl="rawTls" linkIndex="4" dir="l" state="o"/>
  <tlLogic id="rawTls" type="actuated" programID="0"><phase duration="4" state="GGGGG"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <tlLogic id="aggTls" type="static" programID="0"><phase duration="1" state="r"/></tlLogic>
  <connection from="in" to="out" fromLane="0" toLane="0" uncontrolled="true"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_tls_connection_repair_variant(
        source_net_file=source_net,
        candidate_net_file=candidate_net,
        output_dir=tmp_path / "out",
        prefix="demo",
        tls_id_map={"rawTls": "aggTls"},
        copy_unmapped_tls=False,
        require_target_link_index_capacity=True,
    )

    root = ET.parse(report["variant_file"]).getroot()
    connection = root.find("connection[@from='in'][@to='out']")
    assert connection.attrib["uncontrolled"] == "true"
    assert "tl" not in connection.attrib
    assert report["updated_connection_count"] == 0
    assert report["skipped_invalid_mapped_linkindex_connection_count"] == 1


def test_netedit_review_actions_routes_movement_signature_delta_to_vehicle_matrix_rebuild() -> None:
    assert _netedit_review_actions(["movement_signature_counts"]) == ["rebuild_vehicle_movement_matrix"]


def test_approach_endpoint_rebuild_plan_requires_neighbor_scope_for_endpoint_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "approaches": {
            "incoming": [
                {"edge_id": "teacher_in", "from": "teacher_boundary", "to": "teacher_j"},
            ],
            "outgoing": [
                {"edge_id": "teacher_out", "from": "teacher_j", "to": "teacher_exit"},
            ],
        },
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "approaches": {
            "incoming": [
                {"edge_id": "cand_in", "from": "candidate_boundary", "to": "candidate_j"},
            ],
            "outgoing": [
                {"edge_id": "cand_out", "from": "candidate_j", "to": "teacher_exit"},
            ],
        },
    }

    plan = _approach_endpoint_rebuild_plan(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
        candidate_junction_ids={"candidate_j", "candidate_boundary", "teacher_boundary", "teacher_exit"},
    )

    assert plan["status"] == "review"
    assert plan["mismatch_count"] == 1
    assert plan["recommended_action"] == "expand_rebuild_scope"
    assert plan["affected_neighbor_junction_ids"] == ["candidate_boundary", "teacher_boundary"]
    assert plan["missing_desired_endpoint_ids"] == []
    assert plan["edge_rebuilds"] == [
        {
            "approach_key": "incoming:cand_in",
            "edge_id": "cand_in",
            "direction": "incoming",
            "candidate_from": "candidate_boundary",
            "candidate_to": "candidate_j",
            "desired_from": "teacher_boundary",
            "desired_to": "candidate_j",
            "affected_neighbor_junction_ids": ["candidate_boundary", "teacher_boundary"],
            "missing_desired_endpoint_ids": [],
            "unsafe_direct_rewrite": True,
            "reason": "endpoint change affects neighboring junction connections and tlLogic; rebuild expanded scope",
        }
    ]


def test_build_rebuild_candidate_emits_only_high_confidence_vehicle_connections(tmp_path: Path) -> None:
    net_file = tmp_path / "fixture.net.xml"
    net_file.write_text(
        """<net>
  <edge id="west_in" from="w" to="j" type="highway.primary" name="Main Street">
    <lane id="west_in_0" index="0" allow="passenger" length="10" shape="-10,0 0,0"/>
  </edge>
  <edge id="east_out" from="j" to="e" type="highway.primary" name="Main Street">
    <lane id="east_out_0" index="0" allow="passenger" length="10" shape="0,0 10,0"/>
  </edge>
  <edge id="south_out" from="j" to="s" type="highway.secondary" name="South Road">
    <lane id="south_out_0" index="0" allow="passenger" length="10" shape="0,0 0,-10"/>
  </edge>
  <edge id="west_out" from="j" to="w2" type="highway.primary" name="Main Street">
    <lane id="west_out_0" index="0" allow="passenger" length="10" shape="0,0 -10,0"/>
  </edge>
  <edge id="foot_out" from="j" to="p" type="highway.footway">
    <lane id="foot_out_0" index="0" allow="pedestrian" length="5" shape="0,0 0,5"/>
  </edge>
  <junction id="w" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="e" x="10" y="0" type="priority"/>
  <junction id="s" x="0" y="-10" type="priority"/>
  <junction id="w2" x="-10" y="0" type="priority"/>
  <junction id="p" x="0" y="5" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_rebuild_candidate(net_file=net_file, junction_id="j", output_dir=tmp_path / "candidate", prefix="demo")

    assert report["status"] == "pass"
    assert report["emitted_connection_count"] == 2
    assert report["skipped_movement_count"] == 1
    root = ET.parse(report["connections_file"]).getroot()
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("connection")] == [
        ("west_in", "east_out"),
        ("west_in", "south_out"),
    ]
    assert "--connection-files" in Path(report["netconvert_command_file"]).read_text(encoding="utf-8")


def test_build_rebuild_candidate_can_filter_with_exemplar_movement_signatures(tmp_path: Path) -> None:
    net_file = tmp_path / "fixture.net.xml"
    net_file.write_text(
        """<net>
  <edge id="west_in" from="w" to="j" type="highway.primary" name="Main Street">
    <lane id="west_in_0" index="0" allow="passenger" length="10" shape="-10,0 0,0"/>
  </edge>
  <edge id="east_out" from="j" to="e" type="highway.primary" name="Main Street">
    <lane id="east_out_0" index="0" allow="passenger" length="10" shape="0,0 10,0"/>
  </edge>
  <edge id="south_out" from="j" to="s" type="highway.secondary" name="South Road">
    <lane id="south_out_0" index="0" allow="passenger" length="10" shape="0,0 0,-10"/>
  </edge>
  <junction id="w" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="e" x="10" y="0" type="priority"/>
  <junction id="s" x="0" y="-10" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_rebuild_candidate(
        net_file=net_file,
        junction_id="j",
        output_dir=tmp_path / "candidate",
        prefix="demo",
        movement_exemplar={
            "movement_signatures": [
                {
                    "from_slot": "slot_0",
                    "to_slot": "slot_1",
                    "fromLane": "0",
                    "toLane": "0",
                    "dir": "s",
                    "state": "O",
                }
            ]
        },
        slot_edge_map={"slot_0": "west_in", "slot_1": "east_out"},
    )

    root = ET.parse(report["connections_file"]).getroot()
    assert report["movement_source"] == "exemplar_signatures"
    assert report["emitted_connection_count"] == 1
    assert report["skipped_movement_count"] == 1
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("connection")] == [
        ("west_in", "east_out"),
    ]


def test_build_rebuild_candidate_can_filter_with_teacher_edge_map(tmp_path: Path) -> None:
    net_file = tmp_path / "fixture.net.xml"
    net_file.write_text(
        """<net>
  <edge id="west_in" from="w" to="j" type="highway.primary" name="Main Street">
    <lane id="west_in_0" index="0" allow="passenger" length="10" shape="-10,0 0,0"/>
  </edge>
  <edge id="east_out" from="j" to="e" type="highway.primary" name="Main Street">
    <lane id="east_out_0" index="0" allow="passenger" length="10" shape="0,0 10,0"/>
  </edge>
  <edge id="south_out" from="j" to="s" type="highway.secondary" name="South Road">
    <lane id="south_out_0" index="0" allow="passenger" length="10" shape="0,0 0,-10"/>
  </edge>
  <junction id="w" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="e" x="10" y="0" type="priority"/>
  <junction id="s" x="0" y="-10" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_rebuild_candidate(
        net_file=net_file,
        junction_id="j",
        output_dir=tmp_path / "candidate",
        prefix="demo",
        movement_exemplar={
            "approach_slots": [
                {"slot_id": "slot_0", "members": ["teacher_in"]},
                {"slot_id": "slot_1", "members": ["teacher_out"]},
            ],
            "movement_signatures": [
                {"from_slot": "slot_0", "to_slot": "slot_1", "fromLane": "0", "toLane": "0", "dir": "s"}
            ],
        },
        teacher_edge_map={"teacher_in": "west_in", "teacher_out": "east_out"},
    )

    root = ET.parse(report["connections_file"]).getroot()
    assert report["slot_edge_map"] == {"slot_0": "west_in", "slot_1": "east_out"}
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("connection")] == [
        ("west_in", "east_out"),
    ]


def test_rebuild_candidate_writes_connection_signature(tmp_path: Path) -> None:
    net_file = tmp_path / "fixture.net.xml"
    net_file.write_text(
        """<net>
  <edge id="west_in" from="w" to="j" type="highway.primary" name="Main"><lane id="west_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="east_out" from="j" to="e" type="highway.primary" name="Main"><lane id="east_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="w" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="e" x="10" y="0" type="priority"/>
  <connection from="west_in" to="east_out" fromLane="0" toLane="0" dir="s" state="o"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_rebuild_candidate(net_file=net_file, junction_id="j", output_dir=tmp_path / "candidate", prefix="demo")

    assert Path(report["connection_signature"]["signature_file"]).is_file()
    assert report["connection_signature"]["status"] == "pass"


def test_build_teacher_guided_repair_queue_maps_ready_reference_join(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_a_b" type="highway.primary"><lane id="teacher_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_a_b" to="b" type="highway.primary"><lane id="teacher_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="traffic_light" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="cluster_a_b" linkIndex="0" dir="s"/>
  <tlLogic id="cluster_a_b" type="actuated" programID="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="cluster_a_b" type="highway.primary"><lane id="cand_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="cluster_a_b" to="b" type="highway.primary"><lane id="cand_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="traffic_light" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": "cluster_a_b",
                    "learned_rule": "tum_like_join_candidate",
                    "reference_joined_source_nodes": ["a", "b"],
                }
            ],
            "junction_pattern_comparisons": [
                {
                    "junction_id": "a",
                    "status": "fail",
                    "mismatch_fields": ["internal_function_counts", "has_tls"],
                    "teacher": {
                        "has_tls": True,
                        "internal_function_counts": {"crossing": 1, "internal": 3, "walkingarea": 1},
                    },
                    "candidate": {
                        "has_tls": False,
                        "internal_function_counts": {"crossing": 0, "internal": 1, "walkingarea": 0},
                    },
                }
            ],
            "junction_pattern_mismatch_field_counts": {"internal_function_counts": 1, "has_tls": 1},
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    assert report["status"] == "pass"
    assert report["teacher_net_file"] == str(teacher_net.resolve())
    assert report["candidate_net_file"] == str(candidate_net.resolve())
    assert report["repair_candidate_count"] == 1
    assert report["ready_candidate_count"] == 1
    candidate = report["repair_candidates"][0]
    assert candidate["candidate_status"] == "ready_for_teacher_guided_variant"
    assert candidate["junction_id"] == "cluster_a_b"
    assert candidate["junction_pattern_mismatch_fields"] == ["internal_function_counts", "has_tls"]
    assert candidate["netedit_review_actions"] == [
        "rebuild_vehicle_movement_matrix",
        "inspect_internal_edges_crossings_walkingareas",
        "inspect_tls_control",
    ]
    assert candidate["vehicle_movement_matrix_missing_count"] == 1
    assert candidate["review_priority"] == "high"
    assert candidate["junction_pattern_delta_count"] == 1
    assert candidate["junction_pattern_deltas"][0]["junction_id"] == "a"
    assert candidate["junction_pattern_deltas"][0]["teacher"]["has_tls"] is True
    assert candidate["junction_pattern_deltas"][0]["candidate"]["has_tls"] is False
    assert candidate["edge_map"] == {"teacher_in": "cand_in", "teacher_out": "cand_out"}
    assert candidate["slot_edge_map"] == {"slot_0": "cand_in", "slot_1": "cand_out"}
    assert candidate["movement_exemplar"]["movement_signatures"] == [
        {
            "from_slot": "slot_0",
            "to_slot": "slot_1",
            "fromLane": "0",
            "toLane": "0",
            "dir": "s",
            "state": "",
            "controlled": True,
            "linkIndex": "0",
            "has_internal_via": False,
        }
    ]
    assert Path(report["queue_file"]).is_file()
    assert report["junction_pattern_mismatch_field_counts"] == {"internal_function_counts": 1, "has_tls": 1}
    rows = list(csv.DictReader(Path(report["queue_csv_file"]).read_text(encoding="utf-8").splitlines()))
    assert rows[0]["junction_pattern_delta_count"] == "1"
    assert rows[0]["junction_pattern_mismatch_fields"] == "internal_function_counts;has_tls"
    assert (
        rows[0]["netedit_review_actions"]
        == "rebuild_vehicle_movement_matrix;inspect_internal_edges_crossings_walkingareas;inspect_tls_control"
    )
    assert rows[0]["vehicle_movement_matrix_missing_count"] == "1"
    assert rows[0]["review_priority"] == "high"


def test_build_teacher_guided_repair_queue_carries_tls_semantic_repairs(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text("<net/>", encoding="utf-8")
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text("<net/>", encoding="utf-8")

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [],
            "tls_control_review_queue": [
                {
                    "repair_category": "tls_controller_cardinality_repair",
                    "review_type": "restore_tls_controlled_connections",
                    "reference_count": 550,
                    "candidate_count": 160,
                    "missing_count": 390,
                },
                {
                    "repair_category": "tls_linkindex_phase_repair",
                    "review_type": "restore_shared_linkindex_groups",
                    "reference_count": 40,
                    "candidate_count": 0,
                    "missing_count": 40,
                },
            ],
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    assert report["repair_candidate_count"] == 0
    assert report["tls_repair_candidate_count"] == 2
    assert report["tls_repair_category_counts"] == {
        "tls_controller_cardinality_repair": 1,
        "tls_linkindex_phase_repair": 1,
    }
    assert [candidate["candidate_status"] for candidate in report["tls_repair_candidates"]] == [
        "needs_tls_semantic_repair",
        "needs_tls_semantic_repair",
    ]
    assert report["tls_repair_candidates"][0]["netedit_review_actions"] == ["inspect_tls_control"]
    assert report["tls_repair_candidates"][1]["netedit_review_actions"] == ["inspect_tls_linkindex_phase"]
    assert json.loads(Path(report["queue_file"]).read_text(encoding="utf-8"))["tls_repair_candidate_count"] == 2


def test_build_teacher_guided_repair_queue_flags_vehicle_movement_matrix_gap(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_w_in" from="w" to="cluster_j" type="highway.primary"><lane id="teacher_w_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="teacher_s_in" from="s" to="cluster_j" type="highway.primary"><lane id="teacher_s_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="teacher_e_out" from="cluster_j" to="e" type="highway.primary"><lane id="teacher_e_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="teacher_n_out" from="cluster_j" to="n" type="highway.primary"><lane id="teacher_n_out_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <junction id="cluster_j" type="priority" x="0" y="0" incLanes="teacher_w_in_0 teacher_s_in_0" intLanes=""/>
  <connection from="teacher_w_in" to="teacher_e_out" fromLane="0" toLane="0"/>
  <connection from="teacher_w_in" to="teacher_n_out" fromLane="0" toLane="0"/>
  <connection from="teacher_s_in" to="teacher_e_out" fromLane="0" toLane="0"/>
  <connection from="teacher_s_in" to="teacher_n_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="teacher_w_in" from="w" to="cluster_j" type="highway.primary"><lane id="teacher_w_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="teacher_s_in" from="s" to="cluster_j" type="highway.primary"><lane id="teacher_s_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="teacher_e_out" from="cluster_j" to="e" type="highway.primary"><lane id="teacher_e_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="teacher_n_out" from="cluster_j" to="n" type="highway.primary"><lane id="teacher_n_out_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <junction id="cluster_j" type="priority" x="0" y="0" incLanes="teacher_w_in_0 teacher_s_in_0" intLanes=""/>
  <connection from="teacher_w_in" to="teacher_e_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": "cluster_j",
                    "learned_rule": "tum_like_join_candidate",
                    "reference_joined_source_nodes": ["w", "s"],
                }
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert candidate["candidate_status"] == "ready_for_teacher_guided_variant"
    assert candidate["vehicle_movement_matrix_missing_count"] == 3
    assert candidate["netedit_review_actions"] == ["rebuild_vehicle_movement_matrix"]
    assert candidate["review_priority"] == "high"
    rows = list(csv.DictReader(Path(report["queue_csv_file"]).read_text(encoding="utf-8").splitlines()))
    assert rows[0]["vehicle_movement_matrix_missing_count"] == "3"
    assert rows[0]["netedit_review_actions"] == "rebuild_vehicle_movement_matrix"


def test_build_teacher_guided_repair_queue_marks_copyable_missing_boundary_edge_ready(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_a_b"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_missing" from="cluster_a_b" to="p"><lane id="teacher_missing_0" index="0" shape="0,0 10,0"/></edge>
  <edge id=":cluster_a_b_0" function="internal"><lane id=":cluster_a_b_0_0" index="0" shape="0,0 1,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=":cluster_a_b_0_0"/>
  <connection from="teacher_in" to="teacher_missing" via=":cluster_a_b_0_0" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="cluster_a_b"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [{"reference_id": "cluster_a_b", "learned_rule": "tum_like_join_candidate"}]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert report["ready_candidate_count"] == 1
    assert candidate["candidate_status"] == "ready_for_teacher_guided_variant"
    assert candidate["missing_teacher_edge_ids"] == ["teacher_missing"]
    assert candidate["copyable_missing_teacher_edge_ids"] == ["teacher_missing"]
    assert candidate["uncopyable_missing_teacher_edge_ids"] == []


def test_build_teacher_guided_repair_queue_leaves_endpoint_mismatched_approach_copyable(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_a_b"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_a_b" to="e"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <edge id=":cluster_a_b_0" function="internal"><lane id=":cluster_a_b_0_0" index="0" shape="0,0 1,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=":cluster_a_b_0_0"/>
  <connection from="teacher_in" to="teacher_out" via=":cluster_a_b_0_0" fromLane="0" toLane="0" tl="cluster_a_b"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="cluster_a_b"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="cand_short" from="cluster_a_b" to="c"><lane id="cand_short_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [{"reference_id": "cluster_a_b", "learned_rule": "tum_like_join_candidate"}]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert candidate["candidate_status"] == "ready_for_teacher_guided_variant"
    assert candidate["edge_map"] == {"teacher_in": "cand_in"}
    assert candidate["missing_teacher_edge_ids"] == ["teacher_out"]
    assert candidate["copyable_missing_teacher_edge_ids"] == ["teacher_out"]
    assert candidate["uncopyable_missing_teacher_edge_ids"] == []
    assert candidate["approach_endpoint_rebuild_plan"]["mismatch_count"] == 1
    assert candidate["approach_endpoint_rebuild_plan"]["affected_neighbor_junction_ids"] == ["c", "e"]


def test_build_teacher_guided_repair_queue_scopes_missing_joined_candidate_junction(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_j1_j2"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_j1_j2" to="b"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="cluster_j1_j2" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j1"><lane id="cand_in_0" index="0" shape="-10,0 -1,0"/></edge>
  <edge id="cand_mid" from="j1" to="j2"><lane id="cand_mid_0" index="0" shape="-1,0 1,0"/></edge>
  <edge id="cand_out" from="j2" to="b"><lane id="cand_out_0" index="0" shape="1,0 10,0"/></edge>
  <junction id="j1" type="priority" x="-1" y="0" incLanes="cand_in_0" intLanes=""/>
  <junction id="j2" type="priority" x="1" y="0" incLanes="cand_mid_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": "cluster_j1_j2",
                    "matched_candidate_node_ids": ["j1", "j2", "support_node"],
                    "matched_reference_source_node_ids": ["j1", "j2"],
                    "learned_rule": "tum_like_join_candidate",
                }
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert report["ready_candidate_count"] == 0
    assert report["expanded_scope_candidate_count"] == 1
    assert report["blocked_candidate_count"] == 0
    assert candidate["candidate_status"] == "needs_expanded_rebuild_scope"
    assert candidate["edge_map"] == {}
    assert candidate["missing_teacher_edge_ids"] == ["teacher_in", "teacher_out"]
    assert candidate["expanded_rebuild_scope"] == {
        "status": "review",
        "recommended_action": "rebuild_plain_xml_scope",
        "core_junction_id": "cluster_j1_j2",
        "junction_ids": ["j1", "j2"],
        "blocked_teacher_edge_ids": ["teacher_in", "teacher_out"],
        "missing_desired_endpoint_ids": [],
        "reason": "candidate joined junction not found; rebuild from matched candidate source nodes",
    }


def test_build_teacher_guided_repair_queue_marks_existing_endpoint_mismatch_as_expanded_scope(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_a_b"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_a_b" to="e"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <edge id=":cluster_a_b_0" function="internal"><lane id=":cluster_a_b_0_0" index="0" shape="0,0 1,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=":cluster_a_b_0_0"/>
  <connection from="teacher_in" to="teacher_out" via=":cluster_a_b_0_0" fromLane="0" toLane="0" tl="cluster_a_b"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="cluster_a_b"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_a_b" to="c"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
  <junction id="c" type="priority" x="10" y="0" incLanes="teacher_out_0" intLanes=""/>
  <junction id="e" type="priority" x="12" y="0" incLanes="" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [{"reference_id": "cluster_a_b", "learned_rule": "tum_like_join_candidate"}]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert report["ready_candidate_count"] == 0
    assert report["expanded_scope_candidate_count"] == 1
    assert report["blocked_candidate_count"] == 0
    assert candidate["candidate_status"] == "needs_expanded_rebuild_scope"
    assert candidate["edge_map"] == {"teacher_in": "cand_in"}
    assert candidate["missing_teacher_edge_ids"] == ["teacher_out"]
    assert candidate["copyable_missing_teacher_edge_ids"] == []
    assert candidate["uncopyable_missing_teacher_edge_ids"] == ["teacher_out"]
    assert candidate["expanded_rebuild_scope"] == {
        "status": "review",
        "recommended_action": "rebuild_plain_xml_scope",
        "core_junction_id": "cluster_a_b",
        "junction_ids": ["c", "cluster_a_b", "e"],
        "blocked_teacher_edge_ids": ["teacher_out"],
        "missing_desired_endpoint_ids": [],
        "reason": "approach endpoints differ and at least one missing teacher edge cannot be copied safely",
    }


def test_build_teacher_guided_repair_queue_scopes_uncopyable_missing_edge_without_endpoint_mismatch(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_a_b"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_a_b" to="e"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="cluster_a_b"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": "cluster_a_b",
                    "matched_reference_source_node_ids": ["a", "b"],
                    "matched_candidate_node_ids": ["a", "b"],
                    "learned_rule": "tum_like_join_candidate",
                }
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert report["ready_candidate_count"] == 0
    assert report["expanded_scope_candidate_count"] == 1
    assert report["blocked_candidate_count"] == 0
    assert candidate["candidate_status"] == "needs_expanded_rebuild_scope"
    assert candidate["edge_map"] == {"teacher_in": "cand_in"}
    assert candidate["missing_teacher_edge_ids"] == ["teacher_out"]
    assert candidate["copyable_missing_teacher_edge_ids"] == []
    assert candidate["uncopyable_missing_teacher_edge_ids"] == ["teacher_out"]
    assert candidate["expanded_rebuild_scope"] == {
        "status": "review",
        "recommended_action": "rebuild_plain_xml_scope",
        "core_junction_id": "cluster_a_b",
        "junction_ids": ["a", "b"],
        "blocked_teacher_edge_ids": ["teacher_out"],
        "missing_desired_endpoint_ids": [],
        "reason": "missing teacher approach edge cannot be copied safely; rebuild from matched candidate source nodes",
    }


def test_build_teacher_guided_repair_queue_limits_ready_candidates(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_a_b" type="highway.primary"><lane id="teacher_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_a_b" to="b" type="highway.primary"><lane id="teacher_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="traffic_light" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="cluster_a_b" linkIndex="0" dir="s"/>
  <tlLogic id="cluster_a_b" type="actuated" programID="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="cluster_a_b" type="highway.primary"><lane id="cand_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="cluster_a_b" to="b" type="highway.primary"><lane id="cand_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="traffic_light" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": "cluster_a_b",
                    "matched_candidate_node_ids": ["a", "b", "c"],
                    "learned_rule": "tum_like_join_candidate",
                },
                {
                    "reference_id": "cluster_a_b",
                    "matched_candidate_node_ids": ["a"],
                    "learned_rule": "tum_like_join_candidate",
                },
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
        max_ready_candidates=1,
    )

    assert report["matched_case_count"] == 2
    assert report["queued_case_count"] == 1
    assert report["queue_truncated"] is True
    assert report["queue_order_policy"] == "largest_vehicle_movement_gap_then_highest_teacher_template_count"
    assert report["ready_candidate_count"] == 1
    assert report["max_ready_candidates"] == 1
    assert report["repair_candidates"][0]["matched_candidate_node_ids"] == ["a"]


def test_build_teacher_guided_repair_queue_prioritizes_reusable_teacher_templates(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="low_in" from="a" to="cluster_a_low"><lane id="low_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="low_out" from="cluster_a_low" to="b"><lane id="low_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="high_in" from="c" to="cluster_z_high"><lane id="high_in_0" index="0" allow="passenger" shape="-10,10 0,10"/></edge>
  <edge id="high_out" from="cluster_z_high" to="d"><lane id="high_out_0" index="0" allow="passenger" shape="0,10 10,10"/></edge>
  <junction id="cluster_a_low" type="priority" x="0" y="0" incLanes="low_in_0" intLanes=""/>
  <junction id="cluster_z_high" type="priority" x="0" y="10" incLanes="high_in_0" intLanes=""/>
  <connection from="low_in" to="low_out" fromLane="0" toLane="0" dir="s"/>
  <connection from="high_in" to="high_out" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(teacher_net.read_text(encoding="utf-8"), encoding="utf-8")

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {"reference_id": "cluster_a_low", "learned_rule": "tum_like_join_candidate"},
                {"reference_id": "cluster_z_high", "learned_rule": "tum_like_join_candidate"},
            ],
            "junction_pattern_index": [
                {"junction_id": "cluster_a_low", "pattern_key": "low_template"},
                {"junction_id": "cluster_z_high", "pattern_key": "high_template"},
            ],
            "junction_pattern_templates": [
                {"pattern_key": "low_template", "pattern_family": "one_arm", "count": 1},
                {
                    "pattern_key": "high_template",
                    "pattern_family": "one_arm",
                    "count": 127,
                    "example_junction_ids": ["cluster_z_high"],
                },
            ],
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
        max_ready_candidates=1,
    )

    candidate = report["repair_candidates"][0]
    assert report["queue_order_policy"] == "largest_vehicle_movement_gap_then_highest_teacher_template_count"
    assert candidate["reference_id"] == "cluster_z_high"
    assert candidate["teacher_pattern_key"] == "high_template"
    assert candidate["teacher_pattern_template_count"] == 127
    rows = list(csv.DictReader(Path(report["queue_csv_file"]).read_text(encoding="utf-8").splitlines()))
    assert rows[0]["teacher_pattern_template_count"] == "127"
    assert rows[0]["teacher_pattern_key"] == "high_template"


def test_build_teacher_guided_repair_queue_prioritizes_movement_gap_when_limited(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="low_in" from="a" to="cluster_a_low"><lane id="low_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="low_out" from="cluster_a_low" to="b"><lane id="low_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_low" type="priority" x="0" y="0" incLanes="low_in_0" intLanes=""/>
  <connection from="low_in" to="low_out" fromLane="0" toLane="0"/>
  <edge id="high_w_in" from="w" to="cluster_z_high"><lane id="high_w_in_0" index="0" allow="passenger" shape="-10,10 0,10"/></edge>
  <edge id="high_s_in" from="s" to="cluster_z_high"><lane id="high_s_in_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <edge id="high_e_out" from="cluster_z_high" to="e"><lane id="high_e_out_0" index="0" allow="passenger" shape="0,10 10,10"/></edge>
  <edge id="high_n_out" from="cluster_z_high" to="n"><lane id="high_n_out_0" index="0" allow="passenger" shape="0,10 0,20"/></edge>
  <junction id="cluster_z_high" type="priority" x="0" y="10" incLanes="high_w_in_0 high_s_in_0" intLanes=""/>
  <connection from="high_w_in" to="high_e_out" fromLane="0" toLane="0"/>
  <connection from="high_w_in" to="high_n_out" fromLane="0" toLane="0"/>
  <connection from="high_s_in" to="high_e_out" fromLane="0" toLane="0"/>
  <connection from="high_s_in" to="high_n_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="low_in" from="a" to="cluster_a_low"><lane id="low_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="low_out" from="cluster_a_low" to="b"><lane id="low_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_low" type="priority" x="0" y="0" incLanes="low_in_0" intLanes=""/>
  <connection from="low_in" to="low_out" fromLane="0" toLane="0"/>
  <edge id="high_w_in" from="w" to="cluster_z_high"><lane id="high_w_in_0" index="0" allow="passenger" shape="-10,10 0,10"/></edge>
  <edge id="high_s_in" from="s" to="cluster_z_high"><lane id="high_s_in_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <edge id="high_e_out" from="cluster_z_high" to="e"><lane id="high_e_out_0" index="0" allow="passenger" shape="0,10 10,10"/></edge>
  <edge id="high_n_out" from="cluster_z_high" to="n"><lane id="high_n_out_0" index="0" allow="passenger" shape="0,10 0,20"/></edge>
  <junction id="cluster_z_high" type="priority" x="0" y="10" incLanes="high_w_in_0 high_s_in_0" intLanes=""/>
  <connection from="high_w_in" to="high_e_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {"reference_id": "cluster_a_low", "learned_rule": "tum_like_join_candidate"},
                {"reference_id": "cluster_z_high", "learned_rule": "tum_like_join_candidate"},
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
        max_ready_candidates=1,
    )

    assert report["queued_case_count"] == 1
    assert report["repair_candidates"][0]["reference_id"] == "cluster_z_high"
    assert report["repair_candidates"][0]["vehicle_movement_matrix_missing_count"] == 3


def test_build_teacher_guided_repair_queue_resolves_sumo_short_joined_candidate_id(tmp_path: Path) -> None:
    reference_id = "cluster_a_b_c_d_e_f"
    candidate_id = "cluster_a_b_c_d_#2more"
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        f"""<net>
  <edge id="teacher_in" from="w" to="{reference_id}" type="highway.primary"><lane id="teacher_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="{reference_id}" to="e" type="highway.primary"><lane id="teacher_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="{reference_id}" type="traffic_light" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="{reference_id}" linkIndex="0" dir="s"/>
  <tlLogic id="{reference_id}" type="actuated" programID="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        f"""<net>
  <edge id="cand_in" from="w" to="{candidate_id}" type="highway.primary"><lane id="cand_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="{candidate_id}" to="e" type="highway.primary"><lane id="cand_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="{candidate_id}" type="traffic_light" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": reference_id,
                    "matched_candidate_node_ids": ["f", "e", "d", "c", "b", "a"],
                    "learned_rule": "tum_like_join_candidate",
                }
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert report["ready_candidate_count"] == 1
    assert candidate["reference_id"] == reference_id
    assert candidate["junction_id"] == candidate_id
    assert candidate["edge_map"] == {"teacher_in": "cand_in", "teacher_out": "cand_out"}


def test_teacher_guided_repair_queue_uses_real_reference_join_case_after_joined_candidate(tmp_path: Path) -> None:
    reference_net = tmp_path / "reference.net.xml"
    reference_net.write_text(
        """<net>
  <edge id="teacher_in" from="w" to="cluster_a_b" type="highway.primary"><lane id="teacher_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_a_b" to="e" type="highway.primary"><lane id="teacher_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="traffic_light" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="cluster_a_b" linkIndex="0" dir="s"/>
  <tlLogic id="cluster_a_b" type="actuated" programID="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    pre_join_candidate = tmp_path / "pre_join.net.xml"
    pre_join_candidate.write_text(
        """<net>
  <edge id="ab" from="a" to="b" type="highway.residential"><lane id="ab_0" index="0" length="5" shape="-1,0 1,0"/></edge>
  <junction id="a" x="-1" y="0" type="traffic_light"/>
  <junction id="b" x="1" y="0" type="traffic_light"/>
</net>""",
        encoding="utf-8",
    )
    joined_candidate = tmp_path / "joined_candidate.net.xml"
    joined_candidate.write_text(
        """<net>
  <edge id="cand_in" from="w" to="cluster_a_b" type="highway.primary"><lane id="cand_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="cluster_a_b" to="e" type="highway.primary"><lane id="cand_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="traffic_light" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    reference_join = audit_reference_join_patterns(
        reference_net_file=reference_net,
        candidate_net_file=pre_join_candidate,
        output_dir=tmp_path / "reference_join",
        candidate_cluster_radius_m=5,
        candidate_min_cluster_nodes=2,
    )
    queue = build_teacher_guided_repair_queue(
        teacher_net_file=reference_net,
        candidate_net_file=joined_candidate,
        reference_join_audit_report=reference_join,
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    assert reference_join["matched_case_count"] == 1
    assert reference_join["matched_cases"][0]["learned_rule"] == "tum_like_join_candidate"
    assert queue["ready_candidate_count"] == 1
    assert queue["repair_candidates"][0]["edge_map"] == {"teacher_in": "cand_in", "teacher_out": "cand_out"}


def test_run_teacher_guided_repair_queue_executes_ready_candidates(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")
    calls = []

    def fake_variant(**kwargs):
        calls.append(kwargs)
        variant_report = kwargs["output_dir"] / "variant_report.json"
        variant_report.parent.mkdir(parents=True, exist_ok=True)
        variant_report.write_text('{"status": "pass"}', encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "final_net_file": str(kwargs["output_dir"] / "final.net.xml"),
            "parity_gate_status": "pass",
            "report_file": str(variant_report),
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "cluster_a_b",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                    "teacher_pattern_key": "three_way|control=right_before_left",
                    "teacher_pattern_family": "three_way",
                    "teacher_pattern_template_count": 127,
                    "teacher_pattern_template_examples": ["cluster_template_1"],
                    "missing_teacher_edge_ids": ["teacher_copyable"],
                    "copyable_missing_teacher_edge_ids": ["teacher_copyable"],
                    "uncopyable_missing_teacher_edge_ids": [],
                },
                {
                    "junction_id": "cluster_c_d",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                },
                {"junction_id": "cluster_c_d", "candidate_status": "needs_joined_candidate_junction", "edge_map": {}},
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        max_ready_candidates=1,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert report["attempted_candidate_count"] == 1
    assert report["skipped_candidate_count"] == 2
    assert report["max_ready_candidates"] == 1
    assert calls[0]["junction_id"] == "cluster_a_b"
    assert calls[0]["teacher_junction_id"] == "cluster_a_b"
    assert report["variant_reports"][0]["teacher_pattern_key"] == "three_way|control=right_before_left"
    assert report["variant_reports"][0]["teacher_pattern_family"] == "three_way"
    assert report["variant_reports"][0]["teacher_pattern_template_count"] == 127
    assert report["variant_reports"][0]["teacher_pattern_template_examples"] == ["cluster_template_1"]
    assert report["teacher_pattern_contexts"] == [
        {
            "teacher_pattern_key": "three_way|control=right_before_left",
            "teacher_pattern_family": "three_way",
            "teacher_pattern_template_count": 127,
            "teacher_pattern_template_examples": ["cluster_template_1"],
        }
    ]
    variant_report = json.loads(Path(report["variant_reports"][0]["report_file"]).read_text(encoding="utf-8"))
    assert variant_report["teacher_pattern_key"] == "three_way|control=right_before_left"
    assert variant_report["teacher_pattern_template_count"] == 127


def test_run_teacher_guided_repair_queue_passes_reference_id_as_teacher_junction_id(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")
    calls = []

    def fake_variant(**kwargs):
        calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "cluster_a_b_c_d_e_f",
                    "junction_id": "cluster_a_b_c_d_#2more",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert calls[0]["junction_id"] == "cluster_a_b_c_d_#2more"
    assert calls[0]["teacher_junction_id"] == "cluster_a_b_c_d_e_f"
    assert report["parity_gate_status"] == "pass"
    assert calls[0]["edge_map"] == {"teacher_in": "cand_in"}


def test_run_teacher_guided_repair_queue_blocks_without_ready_candidates(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")

    def fail_if_called(**_kwargs):
        raise AssertionError("variant builder must not run for blocked candidates")

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {"junction_id": "cluster_c_d", "candidate_status": "needs_joined_candidate_junction", "edge_map": {}},
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        variant_builder=fail_if_called,
    )

    assert report["status"] == "blocked"
    assert report["claim_status"] == "blocked"
    assert report["attempted_candidate_count"] == 0
    assert report["skipped_candidate_count"] == 1
    assert Path(report["run_report_file"]).is_file()


def test_run_teacher_guided_repair_queue_writes_expanded_scope_plain_inputs(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="10" y="0"/>
  <node id="e" x="12" y="0"/>
  <node id="x" x="99" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="approach_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="teacher_out" from="j" to="c"><lane index="0"/></edge>
  <edge id="old_downstream" from="c" to="e"><lane index="0"/></edge>
  <edge id="outside" from="x" to="a"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="approach_in" to="teacher_out" fromLane="0" toLane="0"/>
  <connection from="teacher_out" to="old_downstream" fromLane="0" toLane="0"/>
  <connection from="outside" to="approach_in" fromLane="0" toLane="0"/>
</connections>""",
        encoding="utf-8",
    )
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    variant_calls = []

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "parity_gate_status": "pass",
        }

    commands: list[list[str]] = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        commands.append(command)
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_c_e_j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "approach_in"},
                    "teacher_pattern_key": "three_way|control=right_before_left",
                    "teacher_pattern_family": "three_way",
                    "teacher_pattern_template_count": 127,
                    "teacher_pattern_template_examples": ["cluster_template_1"],
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["c", "e", "j"],
                        "blocked_teacher_edge_ids": ["teacher_out"],
                    },
                    "approach_endpoint_rebuild_plan": {
                        "status": "review",
                        "edge_rebuilds": [
                            {
                                "edge_id": "teacher_out",
                                "candidate_from": "j",
                                "candidate_to": "c",
                                "desired_from": "j",
                                "desired_to": "e",
                            }
                        ],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert report["attempted_candidate_count"] == 1
    assert report["expanded_scope_candidate_count"] == 1
    scope_report = report["expanded_scope_reports"][0]
    assert scope_report["status"] == "pass"
    assert scope_report["teacher_pattern_key"] == "three_way|control=right_before_left"
    assert scope_report["teacher_pattern_template_count"] == 127
    assert report["teacher_pattern_contexts"] == [
        {
            "teacher_pattern_key": "three_way|control=right_before_left",
            "teacher_pattern_family": "three_way",
            "teacher_pattern_template_count": 127,
            "teacher_pattern_template_examples": ["cluster_template_1"],
        }
    ]
    assert scope_report["node_count"] == 4
    assert scope_report["edge_count"] == 3
    assert scope_report["connection_count"] == 1
    assert scope_report["rewritten_endpoint_count"] == 1
    assert scope_report["netconvert"]["status"] == "pass"
    assert scope_report["sumo_load"]["status"] == "pass"
    assert scope_report["joined_scope_junction_id"] == "cluster_c_e_j"
    assert Path(scope_report["join_nodes_patch_file"]).is_file()
    assert commands[0][commands[0].index("--node-files") + 1] == (
        "expanded_scope.nod.xml,expanded_scope_junction_join.nod.xml"
    )
    assert scope_report["netconvert_command"][-2:] == ["--output-file", "expanded_scope.net.xml"]
    assert report["expanded_scope_pass_candidate_count"] == 1
    assert report["parity_gate_status"] == "pass"
    assert Path(report["best_expanded_scope_net_file"]).name == "expanded_scope.net.xml"
    scope_nodes = ET.parse(scope_report["node_file"]).getroot()
    scope_edges = ET.parse(scope_report["edge_file"]).getroot()
    scope_connections = ET.parse(scope_report["connection_file"]).getroot()
    scope_join_patch = ET.parse(scope_report["join_nodes_patch_file"]).getroot()
    assert [node.attrib["id"] for node in scope_nodes] == ["a", "c", "e", "j"]
    assert [edge.attrib["id"] for edge in scope_edges] == ["approach_in", "teacher_out", "old_downstream"]
    assert scope_edges.find("edge[@id='teacher_out']").attrib["to"] == "e"
    assert [connection.attrib["from"] for connection in scope_connections] == ["approach_in"]
    assert [join.attrib["nodes"] for join in scope_join_patch.findall("join")] == ["c e j"]
    assert [command[0] for command in commands] == ["netconvert-test", "sumo-test"]
    replay_node_file = variant_calls[0]["raw_node_file"]
    assert replay_node_file != Path(scope_report["node_file"])
    assert replay_node_file == Path(scope_report["replay_node_file"])
    replay_nodes = ET.parse(replay_node_file).getroot()
    assert [join.attrib["nodes"] for join in replay_nodes.findall("join")] == ["c e j"]
    replay_edge_file = variant_calls[0]["raw_edge_file"]
    assert replay_edge_file != Path(scope_report["edge_file"])
    assert replay_edge_file == Path(scope_report["replay_edge_file"])
    replay_edges = ET.parse(replay_edge_file).getroot()
    assert replay_edges.find("edge[@id='approach_in']").attrib["to"] == "cluster_c_e_j"
    assert replay_edges.find("edge[@id='teacher_out']") is None
    assert replay_edges.find("edge[@id='old_downstream']") is None
    assert scope_report["replay_edge_endpoint_rewrite_count"] == 1
    assert scope_report["replay_self_loop_edge_drop_count"] == 2
    assert scope_report["replay_dropped_self_loop_edges"] == ["teacher_out", "old_downstream"]
    assert variant_calls[0]["raw_connection_file"] == Path(scope_report["connection_file"])
    assert variant_calls[0]["candidate_net_file"] == Path(scope_report["net_file"])
    assert variant_calls[0]["junction_id"] == "cluster_c_e_j"
    assert variant_calls[0]["teacher_junction_id"] == "j"
    assert variant_calls[0]["edge_map"] == {"teacher_in": "approach_in"}


def test_run_teacher_guided_repair_queue_replays_existing_joined_expanded_scope(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="cluster_a_b" x="0" y="0"/>
  <node id="e" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="teacher_out" from="cluster_a_b" to="e"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "cluster_a_b",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_out": "teacher_out"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "cluster_a_b",
                        "junction_ids": ["a", "b"],
                        "blocked_teacher_edge_ids": ["teacher_out"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    scope_report = report["expanded_scope_reports"][0]
    assert scope_report["status"] == "pass"
    assert scope_report["joined_scope_junction_id"] == "cluster_a_b"
    assert scope_report["missing_node_ids"] == ["a", "b"]
    assert report["attempted_candidate_count"] == 1
    assert report["skipped_candidate_count"] == 0
    assert variant_calls[0]["junction_id"] == "cluster_a_b"
    assert variant_calls[0]["raw_node_file"] == Path(scope_report["node_file"])


def test_run_teacher_guided_repair_queue_blocks_replay_that_would_drop_joined_vehicle_edge(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="approach_in" from="a" to="j" type="highway.primary"><lane index="0"/></edge>
  <edge id="between_join_sources" from="j" to="c" type="highway.primary"><lane index="0" allow="passenger"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="approach_in" to="between_join_sources" fromLane="0" toLane="0"/>
</connections>""",
        encoding="utf-8",
    )
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_c_j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "approach_in"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["c", "j"],
                        "blocked_teacher_edge_ids": ["between_join_sources"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "blocked"
    assert report["attempted_candidate_count"] == 0
    assert variant_calls == []
    scope_report = report["expanded_scope_reports"][0]
    assert scope_report["status"] == "review"
    assert scope_report["replay_self_loop_edge_drop_count"] == 1
    assert scope_report["replay_blocking_self_loop_edge_drops"] == ["between_join_sources"]
    assert report["skipped_candidates"] == [
        {
            "index": 0,
            "junction_id": "j",
            "candidate_status": "unsafe_replay_self_loop_edge_drop",
            "replay_blocking_self_loop_edge_drops": ["between_join_sources"],
        }
    ]


def test_target_internal_replay_preserves_replaced_boundary_edge_order(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="teacher_out" from="candidate_j" to="b"><lane id="teacher_out_0" index="0" shape="0,0 5,0"/></edge>
  <edge id="teacher_in" from="a" to="candidate_j"><lane id="teacher_in_0" index="0"/></edge>
  <junction id="b" type="priority" x="10" y="0" incLanes="teacher_out_0" intLanes=""/>
  <junction id="a" type="priority" x="-10" y="0" incLanes="" intLanes=""/>
  <junction id="candidate_j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="candidate_j" linkIndex="0"/>
</net>""",
        encoding="utf-8",
    )
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_out" from="teacher_j" to="b"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="teacher_in" from="a" to="teacher_j"><lane id="teacher_in_0" index="0"/></edge>
  <junction id="b" type="priority" x="10" y="0" incLanes="teacher_out_0" intLanes=""/>
  <junction id="a" type="priority" x="-10" y="0" incLanes="" intLanes=""/>
  <junction id="teacher_j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="teacher_j" linkIndex="0"/>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replay.net.xml",
        junction_id="candidate_j",
        teacher_junction_id="teacher_j",
        edge_map={"teacher_in": "teacher_in"},
    )

    assert report["status"] == "pass"
    assert report["copied_boundary_edge_count"] == 1
    children = [(child.tag, child.attrib.get("id", "")) for child in ET.parse(report["net_file"]).getroot()]
    assert children.index(("edge", "teacher_out")) < children.index(("junction", "b"))


def test_run_teacher_guided_repair_queue_skips_review_expanded_scope(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="c" x="0" y="0"/>
  <node id="e" x="1" y="0"/>
  <node id="b" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="c" type="highway.primary"><lane index="0" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="e" to="b" type="highway.primary"><lane index="0" shape="0,0 10,0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="teacher_j" type="highway.primary"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="teacher_j" to="b" type="highway.primary"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="teacher_j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text("<net/>", encoding="utf-8")
    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="cluster_c_e" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="cluster_c_e" to="b" type="highway.primary"><lane id="cand_out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="cluster_c_e" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0"/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**_kwargs):
        raise AssertionError("variant builder must not run for review-only expanded scopes")

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "missing_joined_candidate",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "missing_joined_candidate",
                        "junction_ids": ["c", "e"],
                        "blocked_teacher_edge_ids": ["teacher_missing"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "blocked"
    assert report["expanded_scope_reports"][0]["status"] == "review"
    assert report["attempted_candidate_count"] == 0
    assert report["skipped_candidate_count"] == 1
    assert report["skipped_candidates"][0]["candidate_status"] == "needs_expanded_rebuild_scope"


def test_expanded_scope_reviews_when_joined_junction_missing_from_probe_net(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="cluster_a_b" x="0" y="0"/>
  <node id="x" x="-10" y="0"/>
  <node id="y" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="blocked" from="x" to="y"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="x" type="priority" x="-10" y="0" incLanes="" intLanes=""/>
  <junction id="y" type="priority" x="10" y="0" incLanes="blocked_0" intLanes=""/>
  <edge id="blocked" from="x" to="y"><lane id="blocked_0" index="0"/></edge>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    report = write_expanded_scope_plain_inputs(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "scope",
        expanded_rebuild_scope={
            "core_junction_id": "cluster_a_b",
            "junction_ids": ["a", "b"],
            "blocked_teacher_edge_ids": ["blocked"],
        },
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
    )

    assert report["joined_scope_junction_id"] == "cluster_a_b"
    assert report["status"] == "review"
    assert report["joined_scope_junction_missing_from_net"] is True
    assert report["blocking_missing_joined_scope_junction_ids"] == ["cluster_a_b"]


def test_run_teacher_guided_repair_queue_records_expanded_variant_exception(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="c"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_c_j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**_kwargs):
        raise ValueError("candidate junction not found: cluster_c_j")

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "cand_in"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["c", "j"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "fail"
    assert report["attempted_candidate_count"] == 1
    assert report["failed_candidate_count"] == 1
    assert report["variant_reports"][0]["status"] == "fail"
    assert report["variant_reports"][0]["exception_type"] == "ValueError"
    assert "candidate junction not found" in report["variant_reports"][0]["reason"]


def test_run_teacher_guided_repair_queue_fails_when_parity_fails(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")

    def fake_variant(**kwargs):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "parity_gate_status": "fail",
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "cluster_a_b",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                },
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        variant_builder=fake_variant,
    )

    assert report["status"] == "fail"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["parity_gate_status"] == "fail"


def test_run_teacher_guided_repair_queue_summarizes_semantic_failures(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")

    def fake_variant(**kwargs):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "parity_gate_status": "fail",
            "semantic_replay_gate": {
                "status": "fail",
                "failures": [
                    {"report": "parity", "field": "approach_endpoint_signature_mismatch_count", "count": 1},
                    {"report": "parity", "field": "crossing_count", "count": -4},
                    {"report": "parity", "field": "tl_type_mismatch_count", "count": 1},
                ],
            },
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "cluster_a_b",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                },
                {
                    "junction_id": "cluster_c_d",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                },
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        variant_builder=fake_variant,
    )

    assert report["semantic_failure_counts"] == {
        "parity:approach_endpoint_signature_mismatch_count": 2,
        "parity:crossing_count": 2,
        "parity:tl_type_mismatch_count": 2,
    }
    assert report["approach_integrity_status"] == "fail"
    assert report["approach_integrity_failure_counts"] == {
        "parity:approach_endpoint_signature_mismatch_count": 2,
    }


def test_run_teacher_guided_repair_queue_resolves_relative_queue_paths(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    teacher_net = queue_dir / "teacher.net.xml"
    candidate_net = queue_dir / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")
    calls = []

    def fake_variant(**kwargs):
        calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": "teacher.net.xml",
            "candidate_net_file": "candidate.net.xml",
            "repair_candidates": [
                {
                    "junction_id": "cluster_a_b",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                },
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        queue_base_dir=queue_dir,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert calls[0]["teacher_net_file"] == teacher_net
    assert calls[0]["candidate_net_file"] == candidate_net


def test_run_teacher_guided_repair_queue_uses_short_output_names_for_long_junction_ids(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")
    long_junction_id = "cluster_" + "_".join(str(1000000000 + index) for index in range(20))
    calls = []

    def fake_variant(**kwargs):
        calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": long_junction_id,
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                },
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        prefix="probe",
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert calls[0]["junction_id"] == long_junction_id
    assert len(calls[0]["output_dir"].name) <= 24
    assert len(calls[0]["prefix"]) <= 16
    assert long_junction_id not in calls[0]["prefix"]


def test_run_teacher_guided_repair_queue_skips_invalid_edge_map(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")

    def fail_if_called(**_kwargs):
        raise AssertionError("variant builder must not run for malformed edge maps")

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "cluster_a_b",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": ["cand_in"]},
                },
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        variant_builder=fail_if_called,
    )

    assert report["status"] == "blocked"
    assert report["skipped_candidates"][0]["candidate_status"] == "invalid_edge_map"


def test_write_teacher_connection_plan_preserves_non_target_and_blocks_unlisted_targets(tmp_path: Path) -> None:
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="other_in" to="other_out" fromLane="0" toLane="0"/>
  <connection from="cand_in" to="old_out" fromLane="0" toLane="0"/>
  <crossing node="j" edges="old_edge"/>
</connections>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "vehicle_connections": [{"from": "teacher_in", "to": "teacher_out", "fromLane": "1", "toLane": "0"}],
        "crossings": [{"edge_id": ":j_c0", "crossingEdges": ["teacher_out"]}],
    }
    candidate_model = {
        "approaches": {
            "incoming": [{"edge_id": "cand_in", "lane_count": 2}],
            "outgoing": [{"edge_id": "cand_out", "lane_count": 1}, {"edge_id": "old_out", "lane_count": 1}],
        }
    }

    report = write_teacher_connection_plan(
        raw_connection_file=raw_connections,
        output_file=tmp_path / "teacher.con.xml",
        junction_id="j",
        teacher_model=teacher_model,
        candidate_model=candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["connection_file"]).getroot()
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("connection")] == [
        ("other_in", "other_out"),
        ("cand_in", "cand_out"),
    ]
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("delete")] == [("cand_in", "old_out")]
    assert root.find("crossing").attrib["edges"] == "cand_out"
    assert report["kept_non_target_children"] == 1
    assert report["removed_target_children"] == 2


def test_write_teacher_connection_plan_marks_teacher_uncontrolled_movements(tmp_path: Path) -> None:
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_model = {
        "vehicle_connections": [
            {"from": "teacher_in", "to": "teacher_out", "fromLane": "0", "toLane": "0", "tl": "j"},
            {"from": "teacher_bike", "to": "teacher_path", "fromLane": "0", "toLane": "0", "tl": ""},
        ],
        "crossings": [],
    }
    candidate_model = {
        "approaches": {
            "incoming": [{"edge_id": "cand_in", "lane_count": 1}, {"edge_id": "cand_bike", "lane_count": 1}],
            "outgoing": [{"edge_id": "cand_out", "lane_count": 1}, {"edge_id": "cand_path", "lane_count": 1}],
        }
    }

    report = write_teacher_connection_plan(
        raw_connection_file=raw_connections,
        output_file=tmp_path / "teacher.con.xml",
        junction_id="j",
        teacher_model=teacher_model,
        candidate_model=candidate_model,
        edge_map={
            "teacher_in": "cand_in",
            "teacher_out": "cand_out",
            "teacher_bike": "cand_bike",
            "teacher_path": "cand_path",
        },
    )

    connections = ET.parse(report["connection_file"]).getroot().findall("connection")
    attrs_by_pair = {(item.attrib["from"], item.attrib["to"]): item.attrib for item in connections}
    assert "uncontrolled" not in attrs_by_pair[("cand_in", "cand_out")]
    assert attrs_by_pair[("cand_bike", "cand_path")]["uncontrolled"] == "true"
    assert report["emitted_uncontrolled_connection_count"] == 1


def test_write_teacher_connection_plan_can_use_patched_edge_lane_counts(tmp_path: Path) -> None:
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    candidate_edges = tmp_path / "candidate.edg.xml"
    candidate_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j">
    <lane index="0"/>
    <lane index="1"/>
  </edge>
  <edge id="cand_out" from="j" to="b">
    <lane index="0"/>
    <lane index="1"/>
  </edge>
</edges>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "vehicle_connections": [{"from": "teacher_in", "to": "teacher_out", "fromLane": "1", "toLane": "1", "tl": "j"}],
        "crossings": [],
    }
    stale_candidate_model = {
        "approaches": {
            "incoming": [{"edge_id": "cand_in", "lane_count": 1}],
            "outgoing": [{"edge_id": "cand_out", "lane_count": 1}],
        }
    }

    report = write_teacher_connection_plan(
        raw_connection_file=raw_connections,
        output_file=tmp_path / "teacher.con.xml",
        junction_id="j",
        teacher_model=teacher_model,
        candidate_model=stale_candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        candidate_edge_file=candidate_edges,
    )

    connection = ET.parse(report["connection_file"]).getroot().find("connection")
    assert connection.attrib["fromLane"] == "1"
    assert connection.attrib["toLane"] == "1"
    assert report["lane_clamp_count"] == 0


def test_write_teacher_connection_plan_ignores_edges_missing_from_patched_edge_file(tmp_path: Path) -> None:
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="stale_in" to="stale_out" fromLane="0" toLane="0"/>
  <connection from="ghost" to="other" fromLane="0" toLane="0"/>
</connections>
""",
        encoding="utf-8",
    )
    candidate_edges = tmp_path / "candidate.edg.xml"
    candidate_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane index="0"/></edge>
  <edge id="other" from="x" to="y"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "vehicle_connections": [{"from": "teacher_in", "to": "teacher_out", "fromLane": "0", "toLane": "0"}],
        "crossings": [],
    }
    stale_candidate_model = {
        "approaches": {
            "incoming": [{"edge_id": "cand_in", "lane_count": 1}, {"edge_id": "stale_in", "lane_count": 1}],
            "outgoing": [{"edge_id": "cand_out", "lane_count": 1}, {"edge_id": "stale_out", "lane_count": 1}],
        }
    }

    report = write_teacher_connection_plan(
        raw_connection_file=raw_connections,
        output_file=tmp_path / "teacher.con.xml",
        junction_id="j",
        teacher_model=teacher_model,
        candidate_model=stale_candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        candidate_edge_file=candidate_edges,
    )

    root = ET.parse(report["connection_file"]).getroot()
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("connection")] == [("cand_in", "cand_out")]
    assert root.findall("delete") == []
    assert report["removed_target_children"] == 2


def test_write_teacher_lane_patch_edges_copies_lane_permissions_and_geometry_without_replacing_edge_geometry(
    tmp_path: Path,
) -> None:
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand" from="a" to="j" numLanes="1" speed="13.89" shape="0,0 1,0">
    <lane index="0" speed="13.89" shape="0,0 1,0"/>
  </edge>
</edges>
""",
        encoding="utf-8",
    )
    teacher_edges = tmp_path / "teacher.net.xml"
    teacher_edges.write_text(
        """<net>
  <edge id="teacher" from="x" to="j" numLanes="2" speed="13.89" shape="5,5 6,5">
    <lane index="0" allow="pedestrian" width="3.00" speed="13.89" length="1.00" shape="5,5 6,5"/>
    <lane index="1" disallow="pedestrian bicycle" speed="13.89" length="1.50" shape="5,6 6,6" outlineShape="5,5.5 6,5.5"/>
  </edge>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_lane_patch_edges(
        raw_edge_file=raw_edges,
        teacher_edge_file=teacher_edges,
        output_file=tmp_path / "patched.edg.xml",
        edge_map={"teacher": "cand"},
        lane_shape_delta=(-5.0, -5.0),
    )

    edge = ET.parse(report["edge_file"]).getroot().find("edge")
    assert edge.attrib["shape"] == "0,0 1,0"
    assert edge.attrib["numLanes"] == "2"
    lanes = edge.findall("lane")
    assert [lane.attrib.get("allow", "") for lane in lanes] == ["pedestrian", ""]
    assert [lane.attrib.get("disallow", "") for lane in lanes] == ["", "pedestrian bicycle"]
    assert [lane.attrib.get("shape", "") for lane in lanes] == ["0.00,0.00 1.00,0.00", "0.00,1.00 1.00,1.00"]
    assert "length" not in lanes[0].attrib
    assert "outlineShape" not in lanes[1].attrib
    assert report["patched_edge_count"] == 1
    assert report["lane_shape_translation_applied"] is True


def test_write_teacher_lane_patch_edges_prunes_unmapped_target_boundary_edges(tmp_path: Path) -> None:
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j" numLanes="1"><lane index="0"/></edge>
  <edge id="same_support" from="j" to="p" numLanes="1"><lane index="0"/></edge>
  <edge id="cand_remapped" from="j" to="z" numLanes="1"><lane index="0"/></edge>
  <edge id="teacher_remapped" from="j" to="z" numLanes="1"><lane index="0"/></edge>
  <edge id="extra_in" from="x" to="j" numLanes="1"><lane index="0"/></edge>
  <edge id="extra_out" from="j" to="y" numLanes="1"><lane index="0"/></edge>
  <edge id="other" from="x" to="y" numLanes="1"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    teacher_edges = tmp_path / "teacher.net.xml"
    teacher_edges.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j" numLanes="2">
    <lane index="0" speed="13.89"/>
    <lane index="1" speed="13.89"/>
  </edge>
  <edge id="same_support" from="j" to="p" numLanes="1"><lane index="0"/></edge>
  <edge id="teacher_remapped" from="j" to="z" numLanes="1"><lane index="0"/></edge>
  <edge id="extra_out" from="q" to="r" numLanes="1"><lane index="0"/></edge>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_lane_patch_edges(
        raw_edge_file=raw_edges,
        teacher_edge_file=teacher_edges,
        output_file=tmp_path / "patched.edg.xml",
        edge_map={"teacher_in": "cand_in", "teacher_remapped": "cand_remapped"},
        junction_id="j",
        prune_unmapped_boundary_edges=True,
    )

    root = ET.parse(report["edge_file"]).getroot()
    edge_ids = [edge.attrib["id"] for edge in root.findall("edge")]
    assert edge_ids == ["cand_in", "same_support", "cand_remapped", "other"]
    assert root.find("edge[@id='cand_in']").attrib["numLanes"] == "2"
    assert report["patched_edge_count"] == 2
    assert report["pruned_boundary_edges"] == ["teacher_remapped", "extra_in", "extra_out"]


def test_write_teacher_lane_patch_edges_prunes_edges_touching_join_source_nodes(tmp_path: Path) -> None:
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j1" numLanes="1"><lane index="0"/></edge>
  <edge id="cand_out" from="j2" to="b" numLanes="1"><lane index="0"/></edge>
  <edge id="teacher_out" from="j1" to="x" numLanes="1"><lane index="0"/></edge>
  <edge id="other" from="x" to="y" numLanes="1"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    teacher_edges = tmp_path / "teacher.net.xml"
    teacher_edges.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_j1_j2" numLanes="1"><lane index="0"/></edge>
  <edge id="teacher_out" from="cluster_j1_j2" to="b" numLanes="1"><lane index="0"/></edge>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_lane_patch_edges(
        raw_edge_file=raw_edges,
        teacher_edge_file=teacher_edges,
        output_file=tmp_path / "patched.edg.xml",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        junction_id="cluster_j1_j2",
        boundary_node_ids={"j1", "j2"},
        prune_unmapped_boundary_edges=True,
    )

    edge_ids = [edge.attrib["id"] for edge in ET.parse(report["edge_file"]).getroot().findall("edge")]
    assert edge_ids == ["cand_in", "cand_out", "other"]
    assert report["pruned_boundary_edges"] == ["teacher_out"]


def test_write_teacher_pedestrian_ring_net_replays_teacher_ring_and_removes_extra_walkingareas(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0"/></edge>
  <edge id="cand_ped" from="p" to="j"><lane id="cand_ped_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_cA" function="crossing" crossingEdges="cand_in"><lane id=":j_cA_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_cB" function="crossing" crossingEdges="cand_out"><lane id=":j_cB_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_wKeep0" function="walkingarea"><lane id=":j_wKeep0_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_wKeep1" function="walkingarea"><lane id=":j_wKeep1_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_wExtra" function="walkingarea"><lane id=":j_wExtra_0" index="0" allow="pedestrian"/></edge>
  <junction id="j" incLanes="cand_in_0 :j_wKeep0_0 :j_wKeep1_0 :j_wExtra_0" intLanes=":j_cA_0 :j_cB_0 :j_wKeep0_0 :j_wKeep1_0 :j_wExtra_0"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="GrG"/></tlLogic>
  <connection from=":j_wKeep1" to=":j_cA" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="s" state="M"/>
  <connection from=":j_wKeep0" to=":j_cB" fromLane="0" toLane="0" tl="j" linkIndex="2" dir="s" state="M"/>
  <connection from=":j_cA" to=":j_wExtra" fromLane="0" toLane="0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "crossings": [
            {"edge_id": ":j_c0", "crossingEdges": ["teacher_in"]},
            {"edge_id": ":j_c1", "crossingEdges": ["teacher_out"]},
        ],
        "pedestrian_connections": [
            {"from": ":j_c0", "to": ":j_w0", "fromLane": "0", "toLane": "0", "dir": "s", "state": "M"},
            {"from": ":j_w1", "to": ":j_c0", "fromLane": "0", "toLane": "0", "tl": "j", "linkIndex": "1", "dir": "s", "state": "M"},
            {"from": ":j_c1", "to": ":j_w1", "fromLane": "0", "toLane": "0", "dir": "s", "state": "M"},
            {"from": ":j_w0", "to": ":j_c1", "fromLane": "0", "toLane": "0", "tl": "j", "linkIndex": "2", "dir": "s", "state": "M"},
            {"from": "teacher_ped", "to": ":j_w0", "fromLane": "0", "toLane": "0", "dir": "s", "state": "M"},
        ],
    }

    report = write_teacher_pedestrian_ring_net(
        candidate_net_file=candidate_net,
        output_file=tmp_path / "pedring.net.xml",
        junction_id="j",
        teacher_model=teacher_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out", "teacher_ped": "cand_ped"},
    )

    root = ET.parse(report["net_file"]).getroot()
    assert root.find("edge[@id=':j_wExtra']") is None
    assert report["kept_walkingarea_count"] == 2
    assert report["inserted_pedestrian_connection_count"] == 5
    assert report["skipped_pedestrian_connection_count"] == 0
    assert all(":j_wExtra" not in " ".join(item.attrib.values()) for item in root.findall("connection"))
    junction = root.find("junction[@id='j']")
    assert ":j_wExtra_0" not in junction.attrib["incLanes"]
    assert ":j_wExtra_0" not in junction.attrib["intLanes"]


def test_write_teacher_tllogic_net_replaces_only_target_program(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="Gr"/></tlLogic>
  <tlLogic id="other" type="static" programID="0" offset="0"><phase duration="1" state="r"/></tlLogic>
  <connection from="a" to="b" tl="j" linkIndex="0"/>
  <connection from="c" to="d" tl="j" linkIndex="1"/>
</net>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "traffic_light": {
            "attributes": {"id": "j", "type": "actuated", "programID": "0", "offset": "0"},
            "phases": [{"duration": "3", "state": "GG"}, {"duration": "4", "state": "rr"}],
        }
    }

    report = write_teacher_tllogic_net(
        candidate_net_file=candidate_net,
        output_file=tmp_path / "teacher_tls.net.xml",
        junction_id="j",
        teacher_model=teacher_model,
    )

    root = ET.parse(report["net_file"]).getroot()
    target_tls = root.find("tlLogic[@id='j']")
    assert target_tls.attrib["type"] == "actuated"
    assert [phase.attrib["state"] for phase in target_tls.findall("phase")] == ["GG", "rr"]
    assert root.find("tlLogic[@id='other']").attrib["type"] == "static"
    assert report["tl_phase_count"] == 2
    assert report["controlled_link_count"] == 2


def test_write_teacher_tllogic_net_inserts_missing_target_program(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <tlLogic id="other" type="static" programID="0" offset="0"><phase duration="1" state="r"/></tlLogic>
  <connection from="a" to="b" tl="j" linkIndex="0"/>
</net>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "traffic_light": {
            "attributes": {"id": "teacher_j", "type": "actuated", "programID": "0", "offset": "5"},
            "phases": [{"duration": "30", "minDur": "10", "maxDur": "60", "state": "G"}],
        }
    }

    report = write_teacher_tllogic_net(
        candidate_net_file=candidate_net,
        output_file=tmp_path / "teacher_tls.net.xml",
        junction_id="j",
        teacher_model=teacher_model,
    )

    root = ET.parse(report["net_file"]).getroot()
    target_tls = root.find("tlLogic[@id='j']")
    assert report["status"] == "pass"
    assert target_tls.attrib == {"id": "j", "type": "actuated", "programID": "0", "offset": "5"}
    assert target_tls.find("phase").attrib == {"duration": "30", "minDur": "10", "maxDur": "60", "state": "G"}
    assert root.find("tlLogic[@id='other']").attrib["type"] == "static"
    assert report["controlled_link_count"] == 1


def test_write_teacher_tllogic_net_allows_no_teacher_program(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="Gr"/></tlLogic>
  <tlLogic id="other" type="static" programID="0" offset="0"><phase duration="1" state="r"/></tlLogic>
  <connection from="a" to="b" tl="j" linkIndex="0"/>
  <connection from="c" to="d" tl="other" linkIndex="1"/>
  <connection from="e" to="f" tl="missing" linkIndex="2"/>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_tllogic_net(
        candidate_net_file=candidate_net,
        output_file=tmp_path / "teacher_no_tls.net.xml",
        junction_id="j",
        teacher_model={"traffic_light": {"attributes": {}, "phases": []}},
    )

    root = ET.parse(report["net_file"]).getroot()
    target_connection = root.find("connection[@from='a']")
    assert report["status"] == "pass"
    assert report["tls_replay_status"] == "not_applicable_no_teacher_tllogic"
    assert root.find("tlLogic[@id='j']") is None
    assert root.find("tlLogic[@id='other']").attrib["type"] == "static"
    assert "tl" not in target_connection.attrib
    assert "linkIndex" not in target_connection.attrib
    assert target_connection.attrib["uncontrolled"] == "true"
    dangling_connection = root.find("connection[@from='e']")
    assert "tl" not in dangling_connection.attrib
    assert "linkIndex" not in dangling_connection.attrib
    assert dangling_connection.attrib["uncontrolled"] == "true"
    assert root.find("connection[@from='c']").attrib["tl"] == "other"
    assert report["tl_phase_count"] == 0
    assert report["controlled_link_count"] == 0
    assert report["removed_controlled_link_count"] == 2


def test_write_teacher_vehicle_connection_attrs_net_preserves_teacher_connection_attrs(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out"><lane id="cand_out_0" index="0"/></edge>
  <junction id="candidate_tls" x="10" y="20"/>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0"/>
</net>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "vehicle_connections": [
            {
                "from": "teacher_in",
                "to": "teacher_out",
                "fromLane": "0",
                "toLane": "0",
                "tl": "teacher_tls",
                "linkIndex": "3",
                "linkIndex2": "12",
                "dir": "s",
                "state": "O",
                "pass": "true",
                "uncontrolled": "true",
                "allow": "bicycle",
                "disallow": "truck",
                "keepClear": "0",
                "contPos": "43.00",
                "shape": "100,200 101,201",
            }
        ],
        "junction": {"x": "100", "y": "200"},
    }

    report = write_teacher_vehicle_connection_attrs_net(
        candidate_net_file=candidate_net,
        output_file=tmp_path / "attrs.net.xml",
        junction_id="candidate_tls",
        teacher_model=teacher_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    connection = ET.parse(report["net_file"]).getroot().find("connection")
    assert connection.attrib["tl"] == "candidate_tls"
    assert connection.attrib["linkIndex"] == "3"
    assert connection.attrib["linkIndex2"] == "12"
    assert connection.attrib["dir"] == "s"
    assert connection.attrib["state"] == "O"
    assert connection.attrib["pass"] == "true"
    assert connection.attrib["uncontrolled"] == "true"
    assert connection.attrib["allow"] == "bicycle"
    assert connection.attrib["disallow"] == "truck"
    assert connection.attrib["keepClear"] == "0"
    assert connection.attrib["contPos"] == "43.00"
    assert connection.attrib["shape"] == "10.00,20.00 11.00,21.00"


def test_teacher_parity_counts_only_target_tls_controlled_links() -> None:
    teacher_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [
            {"from": "a", "to": "b", "tl": "external_tls", "linkIndex": "1"},
            {"from": "a", "to": "c", "tl": "j", "linkIndex": "2"},
        ],
        "pedestrian_connections": [],
        "traffic_light": {"phases": []},
    }
    candidate_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [{"from": "a", "to": "c", "tl": "j", "linkIndex": "2"}],
        "pedestrian_connections": [],
        "traffic_light": {"phases": []},
    }

    parity = _compare_teacher_models(teacher_model, candidate_model)

    assert parity["teacher"]["controlled_vehicle_link_count"] == 1
    assert parity["candidate"]["controlled_vehicle_link_count"] == 1
    assert parity["delta"]["controlled_vehicle_link_count"] == 0


def test_teacher_parity_counts_referenced_tls_id_controlled_links() -> None:
    teacher_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [{"from": "a", "to": "b", "tl": "cluster_tls", "linkIndex": "1"}],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "cluster_tls"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [{"from": "a", "to": "b", "tl": "cluster_tls", "linkIndex": "1"}],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "cluster_tls"}, "phases": []},
    }

    parity = _compare_teacher_models(teacher_model, candidate_model)

    assert parity["teacher"]["controlled_vehicle_link_count"] == 1
    assert parity["candidate"]["controlled_vehicle_link_count"] == 1
    assert parity["delta"]["controlled_vehicle_link_count"] == 0


def test_teacher_parity_reports_vehicle_movement_matrix_completeness_delta() -> None:
    teacher_model = {
        "junction_id": "j",
        "summary": {
            "incoming_vehicle_edge_count": 4,
            "outgoing_vehicle_edge_count": 4,
            "vehicle_connection_count": 16,
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"phases": []},
    }
    candidate_model = {
        "junction_id": "j",
        "summary": {
            "incoming_vehicle_edge_count": 4,
            "outgoing_vehicle_edge_count": 4,
            "vehicle_connection_count": 4,
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"phases": []},
    }

    parity = _compare_teacher_models(teacher_model, candidate_model)
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["vehicle_movement_matrix_expected_count"] == 16
    assert parity["teacher"]["vehicle_movement_matrix_missing_count"] == 0
    assert parity["candidate"]["vehicle_movement_matrix_expected_count"] == 16
    assert parity["candidate"]["vehicle_movement_matrix_missing_count"] == 12
    assert parity["delta"]["vehicle_movement_matrix_missing_count"] == 12
    assert {
        "report": "parity",
        "field": "vehicle_movement_matrix_missing_count",
        "count": 12,
    } in gate["failures"]


def test_teacher_parity_fails_on_tls_type_mismatch() -> None:
    teacher_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "actuated"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "static"}, "phases": []},
    }

    parity = _compare_teacher_models(teacher_model, candidate_model)

    assert parity["teacher"]["tl_type"] == "actuated"
    assert parity["candidate"]["tl_type"] == "static"
    assert parity["delta"]["tl_type_mismatch_count"] == 1


def test_teacher_parity_fails_on_main_junction_signature_mismatch_after_translation() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "junction": {
            "id": "teacher_j",
            "type": "traffic_light",
            "x": "100",
            "y": "200",
            "incLanes": "teacher_in_0 :teacher_j_0_0",
            "intLanes": ":teacher_j_0_0",
            "shape": "99,199 101,199",
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "junction": {
            "id": "candidate_j",
            "type": "traffic_light",
            "x": "10",
            "y": "20",
            "incLanes": "cand_in_0 :candidate_j_0_0",
            "intLanes": ":candidate_j_0_0",
            "shape": "8,18 12,18",
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["junction_signature"] == (
        "type=traffic_light|incLanes=cand_in_0 :candidate_j_0_0|"
        "intLanes=:candidate_j_0_0|shape=-1.00,-1.00 1.00,-1.00"
    )
    assert parity["candidate"]["junction_signature"] == (
        "type=traffic_light|incLanes=cand_in_0 :candidate_j_0_0|"
        "intLanes=:candidate_j_0_0|shape=-2.00,-2.00 2.00,-2.00"
    )
    assert parity["delta"]["junction_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "junction_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_approach_lane_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "approaches": {
            "incoming": [
                    {
                        "edge_id": "teacher_in",
                        "from": "shared_source",
                        "to": "teacher_j",
                        "type": "highway.primary",
                        "function": "",
                    "lanes": [
                        {
                            "index": "0",
                            "allow": "passenger",
                            "disallow": "pedestrian bicycle",
                            "speed": "13.89",
                            "length": "10.50",
                            "width": "3.20",
                            "shape": "0,0 1,1",
                        }
                    ],
                }
            ],
            "outgoing": [],
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "approaches": {
            "incoming": [
                    {
                        "edge_id": "cand_in",
                        "from": "shared_source",
                        "to": "candidate_j",
                        "type": "highway.primary",
                        "function": "",
                    "lanes": [
                        {
                            "index": "0",
                            "allow": "passenger",
                            "disallow": "pedestrian",
                            "speed": "8.33",
                            "length": "8.50",
                            "width": "3.20",
                            "shape": "0,0 1,1",
                        }
                    ],
                }
            ],
            "outgoing": [],
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["approach_edge_signatures"] == {
        "incoming:cand_in": "from=shared_source|to=candidate_j|type=highway.primary|function=|lanes=0:passenger:pedestrian bicycle:13.89::3.20:0.00,0.00 1.00,1.00:"
    }
    assert parity["candidate"]["approach_edge_signatures"] == {
        "incoming:cand_in": "from=shared_source|to=candidate_j|type=highway.primary|function=|lanes=0:passenger:pedestrian:8.33::3.20:0.00,0.00 1.00,1.00:"
    }
    assert parity["delta"]["approach_edge_signature_mismatch_count"] == 1
    assert "approach_endpoint_signature_mismatch_count" not in parity["delta"]
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "approach_edge_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_normalizes_mapped_approach_shape_by_junction_origin() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "junction": {"id": "teacher_j", "x": "100", "y": "200"},
        "approaches": {
            "incoming": [
                {
                    "edge_id": "teacher_in",
                    "from": "shared_source",
                    "to": "teacher_j",
                    "type": "highway.primary",
                    "function": "",
                    "lanes": [{"index": "0", "speed": "13.89", "shape": "99,199 100,200"}],
                }
            ],
            "outgoing": [],
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "junction": {"id": "candidate_j", "x": "10", "y": "20"},
        "approaches": {
            "incoming": [
                {
                    "edge_id": "cand_in",
                    "from": "shared_source",
                    "to": "candidate_j",
                    "type": "highway.primary",
                    "function": "",
                    "lanes": [{"index": "0", "speed": "13.89", "shape": "9,19 10,20"}],
                }
            ],
            "outgoing": [],
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )

    assert "approach_edge_signature_mismatch_count" not in parity["delta"]
    assert parity["teacher"]["approach_edge_signatures"] == parity["candidate"]["approach_edge_signatures"]


def test_teacher_parity_ignores_approach_lane_length_rounding_when_shape_matches() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "approaches": {
            "incoming": [
                {
                    "edge_id": "teacher_in",
                    "from": "shared_source",
                    "to": "teacher_j",
                    "type": "highway.primary",
                    "function": "",
                    "lanes": [
                        {
                            "index": "0",
                            "allow": "passenger",
                            "speed": "13.89",
                            "length": "80.05",
                            "width": "3.20",
                            "shape": "0,0 80,0",
                        }
                    ],
                }
            ],
            "outgoing": [],
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "approaches": {
            "incoming": [
                {
                    "edge_id": "cand_in",
                    "from": "shared_source",
                    "to": "candidate_j",
                    "type": "highway.primary",
                    "function": "",
                    "lanes": [
                        {
                            "index": "0",
                            "allow": "passenger",
                            "speed": "13.89",
                            "length": "80.06",
                            "width": "3.20",
                            "shape": "0,0 80,0",
                        }
                    ],
                }
            ],
            "outgoing": [],
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )

    assert "approach_edge_signature_mismatch_count" not in parity["delta"]


def test_teacher_parity_fails_on_mapped_approach_endpoint_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "approaches": {
            "incoming": [
                {
                    "edge_id": "teacher_in",
                    "from": "teacher_boundary",
                    "to": "teacher_j",
                    "type": "highway.primary",
                    "lanes": [{"index": "0", "allow": "passenger", "shape": "0,0 1,1"}],
                }
            ]
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "approaches": {
            "incoming": [
                {
                    "edge_id": "cand_in",
                    "from": "candidate_boundary",
                    "to": "candidate_j",
                    "type": "highway.primary",
                    "lanes": [{"index": "0", "allow": "passenger", "shape": "0,0 1,1"}],
                }
            ]
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )

    assert parity["teacher"]["approach_edge_signatures"]["incoming:cand_in"].startswith(
        "from=teacher_boundary|to=candidate_j|"
    )
    assert parity["candidate"]["approach_edge_signatures"]["incoming:cand_in"].startswith(
        "from=candidate_boundary|to=candidate_j|"
    )
    assert parity["teacher"]["approach_endpoint_signatures"] == {"incoming:cand_in": "from=teacher_boundary|to=candidate_j"}
    assert parity["candidate"]["approach_endpoint_signatures"] == {"incoming:cand_in": "from=candidate_boundary|to=candidate_j"}
    assert parity["delta"]["approach_endpoint_signature_mismatch_count"] == 1
    assert parity["delta"]["approach_edge_signature_mismatch_count"] == 1


def test_teacher_parity_fails_on_tls_program_and_offset_mismatch() -> None:
    teacher_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "actuated", "programID": "0", "offset": "0"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "actuated", "programID": "1", "offset": "5"}, "phases": []},
    }

    parity = _compare_teacher_models(teacher_model, candidate_model)
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["tl_programID"] == "0"
    assert parity["candidate"]["tl_programID"] == "1"
    assert parity["teacher"]["tl_offset"] == "0"
    assert parity["candidate"]["tl_offset"] == "5"
    assert parity["delta"]["tl_programID_mismatch_count"] == 1
    assert parity["delta"]["tl_offset_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "tl_offset_mismatch_count", "count": 1},
        {"report": "parity", "field": "tl_programID_mismatch_count", "count": 1},
    ]


def test_teacher_parity_fails_on_tls_phase_state_mismatch() -> None:
    teacher_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "actuated"}, "phases": [{"duration": "30", "state": "Gr"}]},
    }
    candidate_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "actuated"}, "phases": [{"duration": "30", "state": "rG"}]},
    }

    parity = _compare_teacher_models(teacher_model, candidate_model)
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["tl_phase_signatures"] == ["state=Gr|duration=30|minDur=|maxDur=|next="]
    assert parity["candidate"]["tl_phase_signatures"] == ["state=rG|duration=30|minDur=|maxDur=|next="]
    assert parity["delta"]["tl_phase_signatures_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "tl_phase_signatures_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_request_matrix_mismatch() -> None:
    teacher_model = {
        "junction_id": "j",
        "summary": {"request_count": 1},
        "requests": [{"index": "0", "response": "0", "foes": "10", "cont": "0"}],
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "actuated"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "j",
        "summary": {"request_count": 1},
        "requests": [{"index": "0", "response": "0", "foes": "01", "cont": "0"}],
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "actuated"}, "phases": []},
    }

    parity = _compare_teacher_models(teacher_model, candidate_model)
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["request_signatures"] == ["index=0|response=0|foes=10|cont=0"]
    assert parity["candidate"]["request_signatures"] == ["index=0|response=0|foes=01|cont=0"]
    assert parity["delta"]["request_signatures_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "request_signatures_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_controlled_link_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [
            {
                "from": "teacher_in",
                "to": "teacher_out",
                "fromLane": "0",
                "toLane": "0",
                "via": ":teacher_j_0_0",
                "tl": "teacher_j",
                "linkIndex": "3",
                "dir": "s",
                "state": "O",
            }
        ],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [
            {
                "from": "cand_in",
                "to": "cand_left",
                "fromLane": "0",
                "toLane": "0",
                "via": ":candidate_j_0_0",
                "tl": "candidate_j",
                "linkIndex": "3",
                "dir": "s",
                "state": "O",
            }
        ],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["controlled_vehicle_link_signatures"] == {
        "3": "from=cand_in|to=cand_out|fromLane=0|toLane=0|dir=s|state=O|via=:candidate_j_0_0|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape="
    }
    assert parity["candidate"]["controlled_vehicle_link_signatures"] == {
        "3": "from=cand_in|to=cand_left|fromLane=0|toLane=0|dir=s|state=O|via=:candidate_j_0_0|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape="
    }
    assert parity["delta"]["controlled_vehicle_link_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "controlled_vehicle_link_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_duplicate_controlled_link_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [
            {
                "from": "teacher_in",
                "to": "teacher_out",
                "fromLane": "0",
                "toLane": "0",
                "via": ":teacher_j_0_0",
                "tl": "teacher_j",
                "linkIndex": "5",
                "dir": "s",
                "state": "O",
            },
            {
                "from": "teacher_in",
                "to": "teacher_right",
                "fromLane": "1",
                "toLane": "0",
                "via": ":teacher_j_1_0",
                "tl": "teacher_j",
                "linkIndex": "5",
                "dir": "r",
                "state": "O",
            },
        ],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [
            {
                "from": "cand_in",
                "to": "cand_wrong",
                "fromLane": "0",
                "toLane": "0",
                "via": ":candidate_j_0_0",
                "tl": "candidate_j",
                "linkIndex": "5",
                "dir": "s",
                "state": "O",
            },
            {
                "from": "cand_in",
                "to": "cand_right",
                "fromLane": "1",
                "toLane": "0",
                "via": ":candidate_j_1_0",
                "tl": "candidate_j",
                "linkIndex": "5",
                "dir": "r",
                "state": "O",
            },
        ],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out", "teacher_right": "cand_right"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["delta"]["controlled_vehicle_link_count"] == 0
    assert parity["teacher"]["controlled_link_count"] == 2
    assert parity["teacher"]["controlled_link_index_count"] == 1
    assert parity["teacher"]["controlled_duplicate_link_index_count"] == 1
    assert parity["delta"]["controlled_vehicle_link_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "controlled_vehicle_link_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_controlled_link_attribute_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [
            {
                "from": "teacher_in",
                "to": "teacher_out",
                "fromLane": "0",
                "toLane": "0",
                "via": ":teacher_j_0_0",
                "tl": "teacher_j",
                "linkIndex": "3",
                "dir": "s",
                "state": "O",
                "pass": "true",
                "uncontrolled": "",
                "allow": "bicycle",
                "disallow": "",
                "keepClear": "0",
                "contPos": "43.00",
                "linkIndex2": "12",
                "shape": "0,0 1,1",
            }
        ],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [
            {
                "from": "cand_in",
                "to": "cand_out",
                "fromLane": "0",
                "toLane": "0",
                "via": ":candidate_j_0_0",
                "tl": "candidate_j",
                "linkIndex": "3",
                "dir": "s",
                "state": "O",
                "pass": "",
                "uncontrolled": "",
                "allow": "",
                "disallow": "",
                "keepClear": "",
                "contPos": "",
                "linkIndex2": "",
                "shape": "",
            }
        ],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["controlled_vehicle_link_signatures"] == {
        "3": "from=cand_in|to=cand_out|fromLane=0|toLane=0|dir=s|state=O|via=:candidate_j_0_0|pass=true|uncontrolled=|allow=bicycle|disallow=|keepClear=0|contPos=43.00|linkIndex2=12|shape=0,0 1,1"
    }
    assert parity["candidate"]["controlled_vehicle_link_signatures"] == {
        "3": "from=cand_in|to=cand_out|fromLane=0|toLane=0|dir=s|state=O|via=:candidate_j_0_0|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape="
    }
    assert parity["delta"]["controlled_vehicle_link_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "controlled_vehicle_link_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_pedestrian_link_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [
            {
                "from": ":teacher_j_w0",
                "to": ":teacher_j_c0",
                "fromLane": "0",
                "toLane": "0",
                "tl": "teacher_j",
                "linkIndex": "7",
                "dir": "s",
                "state": "M",
            }
        ],
        "traffic_light": {"attributes": {"id": "teacher_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [
            {
                "from": ":candidate_j_w0",
                "to": ":candidate_j_c_wrong",
                "fromLane": "0",
                "toLane": "0",
                "tl": "candidate_j",
                "linkIndex": "7",
                "dir": "s",
                "state": "M",
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["controlled_pedestrian_link_signatures"] == {
        "7": "from=:candidate_j_w0|to=:candidate_j_c0|fromLane=0|toLane=0|dir=s|state=M|via=|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape="
    }
    assert parity["candidate"]["controlled_pedestrian_link_signatures"] == {
        "7": "from=:candidate_j_w0|to=:candidate_j_c_wrong|fromLane=0|toLane=0|dir=s|state=M|via=|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape="
    }
    assert parity["delta"]["controlled_pedestrian_link_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "controlled_pedestrian_link_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_crossing_edge_set_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "crossings": [{"edge_id": ":teacher_j_c0", "crossingEdges": ["teacher_in", "teacher_out"]}],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "crossings": [{"edge_id": ":candidate_j_c0", "crossingEdges": ["cand_in", "cand_wrong"]}],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["crossing_signatures"] == {":candidate_j_c0": "edges=cand_in cand_out"}
    assert parity["candidate"]["crossing_signatures"] == {":candidate_j_c0": "edges=cand_in cand_wrong"}
    assert parity["delta"]["crossing_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "crossing_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_crossing_geometry_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "crossings": [
            {
                "edge_id": ":teacher_j_c0",
                "function": "crossing",
                "crossingEdges": ["teacher_in", "teacher_out"],
                "lanes": [
                    {"index": "0", "allow": "pedestrian", "width": "4.00", "shape": "0,0 1,1", "outlineShape": "0,0 1,0"}
                ],
            }
        ],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "crossings": [
            {
                "edge_id": ":candidate_j_c0",
                "function": "crossing",
                "crossingEdges": ["cand_in", "cand_out"],
                "lanes": [
                    {"index": "0", "allow": "pedestrian", "width": "2.00", "shape": "0,0 2,2", "outlineShape": "0,0 2,0"}
                ],
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["crossing_geometry_signatures"] == {
        ":candidate_j_c0": "function=crossing|lanes=0:pedestrian::::4.00:0,0 1,1:0,0 1,0"
    }
    assert parity["candidate"]["crossing_geometry_signatures"] == {
        ":candidate_j_c0": "function=crossing|lanes=0:pedestrian::::2.00:0,0 2,2:0,0 2,0"
    }
    assert parity["delta"]["crossing_geometry_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "crossing_geometry_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_normalizes_internal_pedestrian_geometry_by_junction_origin() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "junction": {"id": "teacher_j", "x": "100", "y": "200"},
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_edges": [
            {
                "edge_id": ":teacher_j_0",
                "function": "internal",
                "lanes": [{"index": "0", "shape": "101,200 102,201"}],
            }
        ],
        "crossings": [
            {
                "edge_id": ":teacher_j_c0",
                "function": "crossing",
                "lanes": [{"index": "0", "allow": "pedestrian", "shape": "99,199 101,199"}],
            }
        ],
        "walking_areas": [
            {
                "edge_id": ":teacher_j_w0",
                "function": "walkingarea",
                "lanes": [{"index": "0", "allow": "pedestrian", "outlineShape": "99,199 101,199 101,201"}],
            }
        ],
        "internal_junctions": [
            {
                "junction_id": ":teacher_j_0_0",
                "type": "internal",
                "incLanes": "",
                "intLanes": "",
                "shape": "101,200 102,201",
                "customShape": "99,199 101,199 101,201",
            }
        ],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "junction": {"id": "candidate_j", "x": "10", "y": "20"},
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_edges": [
            {
                "edge_id": ":candidate_j_0",
                "function": "internal",
                "lanes": [{"index": "0", "shape": "11,20 12,21"}],
            }
        ],
        "crossings": [
            {
                "edge_id": ":candidate_j_c0",
                "function": "crossing",
                "lanes": [{"index": "0", "allow": "pedestrian", "shape": "9,19 11,19"}],
            }
        ],
        "walking_areas": [
            {
                "edge_id": ":candidate_j_w0",
                "function": "walkingarea",
                "lanes": [{"index": "0", "allow": "pedestrian", "outlineShape": "9,19 11,19 11,21"}],
            }
        ],
        "internal_junctions": [
            {
                "junction_id": ":candidate_j_0_0",
                "type": "internal",
                "incLanes": "",
                "intLanes": "",
                "shape": "11,20 12,21",
                "customShape": "9,19 11,19 11,21",
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )

    assert "internal_edge_signature_mismatch_count" not in parity["delta"]
    assert "crossing_geometry_signature_mismatch_count" not in parity["delta"]
    assert "walking_area_signature_mismatch_count" not in parity["delta"]
    assert "internal_junction_signature_mismatch_count" not in parity["delta"]


def test_teacher_parity_fails_on_mapped_internal_edge_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_edges": [
            {
                "edge_id": ":teacher_j_0",
                "function": "internal",
                "lanes": [
                    {
                        "index": "0",
                        "allow": "passenger",
                        "disallow": "pedestrian",
                        "speed": "13.89",
                        "length": "10.50",
                        "width": "",
                        "shape": "0,0 1,1",
                    }
                ],
            }
        ],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_edges": [
            {
                "edge_id": ":candidate_j_0",
                "function": "internal",
                "lanes": [
                    {
                        "index": "0",
                        "allow": "passenger",
                        "disallow": "",
                        "speed": "8.33",
                        "length": "8.50",
                        "width": "",
                        "shape": "0,0 1,1",
                    }
                ],
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["internal_edge_signatures"] == {
        ":candidate_j_0": "function=internal|lanes=0:passenger:pedestrian:13.89:10.50::0,0 1,1:"
    }
    assert parity["candidate"]["internal_edge_signatures"] == {
        ":candidate_j_0": "function=internal|lanes=0:passenger::8.33:8.50::0,0 1,1:"
    }
    assert parity["delta"]["internal_edge_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "internal_edge_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_internal_junction_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_junctions": [
            {
                "junction_id": ":teacher_j_0_0",
                "type": "internal",
                "incLanes": "teacher_in_0 :teacher_j_0_0",
                "intLanes": "",
                "shape": "0,0 1,1",
                "customShape": "0,0 1,0 1,1",
            }
        ],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_junctions": [
            {
                "junction_id": ":candidate_j_0_0",
                "type": "internal",
                "incLanes": "cand_wrong_0 :candidate_j_0_0",
                "intLanes": "",
                "shape": "0,0 1,1",
                "customShape": "0,0 2,0 2,2",
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["internal_junction_signatures"] == {
        ":candidate_j_0_0": "type=internal|incLanes=cand_in_0 :candidate_j_0_0|intLanes=|shape=0,0 1,1|customShape=0,0 1,0 1,1"
    }
    assert parity["candidate"]["internal_junction_signatures"] == {
        ":candidate_j_0_0": "type=internal|incLanes=cand_wrong_0 :candidate_j_0_0|intLanes=|shape=0,0 1,1|customShape=0,0 2,0 2,2"
    }
    assert parity["delta"]["internal_junction_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "internal_junction_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_walking_area_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "walking_areas": [
            {
                "edge_id": ":teacher_j_w0",
                "function": "walkingarea",
                "lanes": [
                    {"index": "0", "allow": "pedestrian", "width": "4.00", "shape": "0,0 1,1", "outlineShape": "0,0 1,0"}
                ],
            }
        ],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "walking_areas": [
            {
                "edge_id": ":candidate_j_w0",
                "function": "walkingarea",
                "lanes": [
                    {"index": "0", "allow": "pedestrian", "width": "2.00", "shape": "0,0 2,2", "outlineShape": "0,0 2,0"}
                ],
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["walking_area_signatures"] == {
        ":candidate_j_w0": "function=walkingarea|lanes=0:pedestrian::::4.00:0,0 1,1:0,0 1,0"
    }
    assert parity["candidate"]["walking_area_signatures"] == {
        ":candidate_j_w0": "function=walkingarea|lanes=0:pedestrian::::2.00:0,0 2,2:0,0 2,0"
    }
    assert parity["delta"]["walking_area_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "walking_area_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_internal_connection_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_connections": [
            {
                "from": ":teacher_j_0",
                "to": "teacher_out",
                "fromLane": "0",
                "toLane": "1",
                "via": "",
                "dir": "s",
                "state": "M",
            }
        ],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_connections": [
            {
                "from": ":candidate_j_0",
                "to": "cand_wrong",
                "fromLane": "0",
                "toLane": "1",
                "via": "",
                "dir": "s",
                "state": "M",
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_out": "cand_out"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["internal_connection_signatures"] == {
        "from=:candidate_j_0|to=cand_out|fromLane=0|toLane=1|dir=s|state=M|via=|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape=": "1"
    }
    assert parity["candidate"]["internal_connection_signatures"] == {
        "from=:candidate_j_0|to=cand_wrong|fromLane=0|toLane=1|dir=s|state=M|via=|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape=": "1"
    }
    assert parity["delta"]["internal_connection_signature_mismatch_count"] == 2
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "internal_connection_signature_mismatch_count", "count": 2}
    ]


def test_teacher_parity_fails_on_uncontrolled_pedestrian_ring_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [
            {"from": ":teacher_j_w0", "to": ":teacher_j_w1", "fromLane": "0", "toLane": "0", "dir": "s", "state": "M"}
        ],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [
            {
                "from": ":candidate_j_w0",
                "to": ":candidate_j_w_wrong",
                "fromLane": "0",
                "toLane": "0",
                "dir": "s",
                "state": "M",
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["uncontrolled_pedestrian_connection_signatures"] == {
        "from=:candidate_j_w0|to=:candidate_j_w1|fromLane=0|toLane=0|dir=s|state=M|via=|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape=": "1"
    }
    assert parity["candidate"]["uncontrolled_pedestrian_connection_signatures"] == {
        "from=:candidate_j_w0|to=:candidate_j_w_wrong|fromLane=0|toLane=0|dir=s|state=M|via=|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape=": "1"
    }
    assert parity["delta"]["uncontrolled_pedestrian_connection_signature_mismatch_count"] == 2
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "uncontrolled_pedestrian_connection_signature_mismatch_count", "count": 2}
    ]


def test_teacher_guided_semantics_gate_fails_on_skipped_pedestrian_connections() -> None:
    gate = _teacher_guided_semantics_gate(
        {"delta": {"vehicle_connection_count": 0, "pedestrian_connection_count": 0}},
        pedestrian_ring={"skipped_pedestrian_connection_count": 1},
        vehicle_connection_attrs={"skipped_vehicle_connection_count": 0},
    )

    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {
            "report": "pedestrian_ring",
            "field": "skipped_pedestrian_connection_count",
            "count": 1,
        }
    ]


def test_teacher_guided_semantics_gate_ignores_interim_pedestrian_skips_after_internal_replay() -> None:
    gate = _teacher_guided_semantics_gate(
        {"delta": {"vehicle_connection_count": 0, "pedestrian_connection_count": 0}},
        pedestrian_ring={"skipped_pedestrian_connection_count": 21},
        vehicle_connection_attrs={"skipped_vehicle_connection_count": 0},
        target_internal_replay={"status": "pass", "skipped_connection_count": 0},
    )

    assert gate == {"status": "pass", "failures": []}


def test_write_teacher_target_internal_replay_net_maps_and_translates_teacher_subgraph(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="90,20 100,20"/></edge>
  <edge id="teacher_out" from="j" to="b"><lane id="teacher_out_0" index="0" shape="100,20 110,20"/></edge>
  <edge id="foot_same" from="j" to="p"><lane id="foot_same_0" index="0" allow="pedestrian" shape="100,20 100,25"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="100,200 101,201" outlineShape="99,199 102,202"/></edge>
  <edge id=":j_c0" function="crossing" crossingEdges="teacher_in"><lane id=":j_c0_0" index="0" allow="pedestrian" shape="99,199 101,199" outlineShape="98,198 102,200"/></edge>
  <edge id=":j_w0" function="walkingarea"><lane id=":j_w0_0" index="0" allow="pedestrian" shape="98,198 99,199" outlineShape="97,197 100,200"/></edge>
  <junction id="j" type="traffic_light" x="100" y="200" shape="99,199 101,199 101,201 99,201" customShape="98,198 102,198 102,202 98,202" incLanes="teacher_in_0" intLanes=":j_0_0 :j_c0_0 :j_w0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <junction id=":j_0_0" type="internal" x="100" y="200" incLanes="teacher_in_0" intLanes=":j_0_0" customShape="99,199 101,201"/>
  <junction id=":j_w0_0" type="internal" x="98" y="198" incLanes="teacher_in_0" intLanes=":j_c0_0"/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="s" state="O" shape="100,200 101,201"/>
  <connection from=":j_w0" to=":j_c0" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="s" state="M"/>
  <connection from=":j_w0" to="foot_same" fromLane="0" toLane="0" dir="s" state="M"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="GM"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,20 10,20"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0" shape="10,20 20,20"/></edge>
  <edge id="foot_same" from="j" to="p"><lane id="foot_same_0" index="0" allow="pedestrian" shape="10,20 10,25"/></edge>
  <edge id=":j_old" function="internal"><lane id=":j_old_0" index="0" shape="10,20 11,20"/></edge>
  <junction id="j" type="traffic_light" x="10" y="20" shape="9,19 11,19 11,21 9,21" incLanes="cand_in_0" intLanes=":j_old_0"/>
  <junction id=":j_old_0" type="internal" x="10" y="20" incLanes="cand_in_0" intLanes=":j_old_0"/>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0" via=":j_old_0"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="r"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    assert root.find("edge[@id=':j_old']") is None
    assert root.find("junction[@id=':j_old_0']") is None
    assert root.find("edge[@id=':j_0']/lane").attrib["shape"] == "10.00,20.00 11.00,21.00"
    assert root.find("edge[@id=':j_0']/lane").attrib["outlineShape"] == "9.00,19.00 12.00,22.00"
    assert root.find("edge[@id=':j_c0']/lane").attrib["outlineShape"] == "8.00,18.00 12.00,20.00"
    assert root.find("edge[@id=':j_w0']/lane").attrib["outlineShape"] == "7.00,17.00 10.00,20.00"
    assert root.find("edge[@id=':j_c0']").attrib["crossingEdges"] == "cand_in"
    junction = root.find("junction[@id='j']")
    assert junction.attrib["x"] == "10.00"
    assert junction.attrib["y"] == "20.00"
    assert junction.attrib["shape"] == "9.00,19.00 11.00,19.00 11.00,21.00 9.00,21.00"
    assert junction.attrib["customShape"] == "8.00,18.00 12.00,18.00 12.00,22.00 8.00,22.00"
    assert junction.attrib["incLanes"] == "cand_in_0"
    assert junction.attrib["intLanes"] == ":j_0_0 :j_c0_0 :j_w0_0"
    internal_junction = root.find("junction[@id=':j_0_0']")
    assert internal_junction.attrib["x"] == "10.00"
    assert internal_junction.attrib["y"] == "20.00"
    assert internal_junction.attrib["incLanes"] == "cand_in_0"
    assert internal_junction.attrib["intLanes"] == ":j_0_0"
    assert internal_junction.attrib["customShape"] == "9.00,19.00 11.00,21.00"
    walkingarea_junction = root.find("junction[@id=':j_w0_0']")
    assert walkingarea_junction.attrib["x"] == "8.00"
    assert walkingarea_junction.attrib["y"] == "18.00"
    vehicle_connection = root.find("connection[@from='cand_in'][@to='cand_out']")
    assert vehicle_connection.attrib["via"] == ":j_0_0"
    assert vehicle_connection.attrib["shape"] == "10.00,20.00 11.00,21.00"
    assert root.find("connection[@from=':j_w0'][@to=':j_c0']").attrib["tl"] == "j"
    assert root.find("connection[@from=':j_w0'][@to='foot_same']") is not None
    assert report["removed_internal_edge_count"] == 1
    assert report["removed_internal_junction_count"] == 1
    assert report["copied_internal_edge_count"] == 3
    assert report["copied_internal_junction_count"] == 2
    assert report["copied_connection_count"] == 3


def test_write_teacher_target_internal_replay_net_maps_referenced_tls_logic(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="teacher_out" from="j" to="b"><lane id="teacher_out_0" index="0" shape="10,0 20,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="10,0 11,0"/></edge>
  <junction id="j" type="traffic_light" x="10" y="0" incLanes="teacher_in_0" intLanes=":j_0_0"/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":j_0_0" tl="cluster_tls" linkIndex="0" dir="s"/>
  <tlLogic id="cluster_tls" type="actuated" programID="0" offset="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0" shape="10,0 20,0"/></edge>
  <junction id="j" type="traffic_light" x="10" y="0" incLanes="cand_in_0" intLanes=""/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="r"/></tlLogic>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    connection = root.find("connection[@from='cand_in'][@to='cand_out']")
    assert connection.attrib["tl"] == "j"
    target_tls = root.find("tlLogic[@id='j']")
    assert target_tls.attrib["type"] == "actuated"
    assert target_tls.find("phase").attrib["state"] == "G"


def test_write_teacher_target_internal_replay_net_copies_missing_boundary_edge(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="90,20 100,20"/></edge>
  <edge id="teacher_out" from="j" to="b"><lane id="teacher_out_0" index="0" shape="100,20 110,20"/></edge>
  <edge id="foot_missing" from="j" to="p"><lane id="foot_missing_0" index="0" allow="pedestrian" shape="100,20 100,25"/></edge>
  <edge id=":j_w0" function="walkingarea"><lane id=":j_w0_0" index="0" allow="pedestrian" shape="98,198 99,199"/></edge>
  <junction id="j" type="priority" x="100" y="200" shape="99,199 101,199" incLanes="teacher_in_0" intLanes=":j_w0_0"/>
  <junction id="p" type="dead_end" x="100" y="25" incLanes="foot_missing_0" intLanes=""/>
  <connection from=":j_w0" to="foot_missing" fromLane="0" toLane="0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,20 10,20"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0" shape="10,20 20,20"/></edge>
  <junction id="p" type="dead_end" x="10" y="-155" incLanes="" intLanes=""/>
  <junction id="j" type="priority" x="10" y="20" shape="9,19 11,19" incLanes="cand_in_0" intLanes=":j_old_0"/>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    copied_edge = root.find("edge[@id='foot_missing']")
    assert copied_edge is not None
    assert copied_edge.attrib["from"] == "j"
    assert copied_edge.attrib["to"] == "p"
    assert copied_edge.find("lane").attrib["shape"] == "10.00,-160.00 10.00,-155.00"
    assert root.find("connection[@from=':j_w0'][@to='foot_missing']") is not None
    assert "foot_missing_0" in root.find("junction[@id='p']").attrib["incLanes"]
    children = list(root)
    assert children.index(copied_edge) < children.index(root.find("junction[@id='p']"))
    assert report["copied_boundary_edge_count"] == 1
    assert report["copied_boundary_edges"] == ["foot_missing"]
    assert report["skipped_connection_count"] == 0


def test_write_teacher_target_internal_replay_net_replays_same_id_boundary_edge_endpoint(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="90,20 100,20"/></edge>
  <edge id="teacher_out" from="j" to="neighbor_cluster"><lane id="teacher_out_0" index="0" shape="100,20 120,20"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="100,20 101,20"/></edge>
  <junction id="j" type="priority" x="100" y="20" incLanes="teacher_in_0" intLanes=":j_0_0"/>
  <junction id="neighbor_cluster" type="priority" x="120" y="20" incLanes="teacher_out_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":j_0_0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,20 10,20"/></edge>
  <edge id="teacher_out" from="j" to="stale_neighbor"><lane id="teacher_out_0" index="0" shape="10,20 11,20"/></edge>
  <edge id=":j_old" function="internal"><lane id=":j_old_0" index="0" shape="10,20 11,20"/></edge>
  <junction id="j" type="priority" x="10" y="20" incLanes="cand_in_0" intLanes=":j_old_0"/>
  <junction id="stale_neighbor" type="priority" x="11" y="20" incLanes="teacher_out_0" intLanes=""/>
  <connection from="cand_in" to="teacher_out" fromLane="0" toLane="0" via=":j_old_0"/>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in"},
    )

    root = ET.parse(report["net_file"]).getroot()
    replayed_edge = root.find("edge[@id='teacher_out']")
    assert replayed_edge is not None
    assert replayed_edge.attrib["from"] == "j"
    assert replayed_edge.attrib["to"] == "neighbor_cluster"
    assert replayed_edge.find("lane").attrib["shape"] == "10.00,20.00 30.00,20.00"
    assert "teacher_out_0" in root.find("junction[@id='neighbor_cluster']").attrib["incLanes"]
    assert root.find("junction[@id='stale_neighbor']").attrib["incLanes"] == ""
    assert root.find("connection[@from='cand_in'][@to='teacher_out']").attrib["via"] == ":j_0_0"
    assert report["copied_boundary_edges"] == ["teacher_out"]
    assert report["skipped_boundary_edges"] == []


def test_write_teacher_target_internal_replay_net_replays_mapped_boundary_edge_shape(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="90,20 100,20"/></edge>
  <edge id="teacher_out" from="j" to="b"><lane id="teacher_out_0" index="0" shape="100,20 120,20"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="100,20 101,20"/></edge>
  <junction id="j" type="priority" x="100" y="20" incLanes="teacher_in_0" intLanes=":j_0_0"/>
  <junction id="b" type="priority" x="120" y="20" incLanes="teacher_out_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":j_0_0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,20 10,20"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0" shape="-1000,-1000 -990,-1000"/></edge>
  <edge id=":j_old" function="internal"><lane id=":j_old_0" index="0" shape="10,20 11,20"/></edge>
  <junction id="j" type="priority" x="10" y="20" incLanes="cand_in_0" intLanes=":j_old_0"/>
  <junction id="b" type="priority" x="30" y="20" incLanes="cand_out_0" intLanes=""/>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0" via=":j_old_0"/>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    replayed_edge = root.find("edge[@id='cand_out']")
    assert replayed_edge is not None
    assert replayed_edge.attrib["from"] == "j"
    assert replayed_edge.attrib["to"] == "b"
    assert replayed_edge.find("lane").attrib["id"] == "cand_out_0"
    assert replayed_edge.find("lane").attrib["shape"] == "10.00,20.00 30.00,20.00"
    assert root.find("connection[@from='cand_in'][@to='cand_out']").attrib["via"] == ":j_0_0"
    assert report["copied_boundary_edges"] == ["teacher_out"]
    assert report["skipped_boundary_edges"] == []


def test_stage_file_shortens_long_output_names(tmp_path: Path) -> None:
    output_dir = tmp_path / ("x" * 120)
    output_dir.mkdir()
    path = _stage_file(output_dir, "very_long_teacher_guided_prefix", "target_internal_normalized.net.xml")

    assert path.name == "very_long_teache_target_internal_normalized.net.xml"


def test_build_teacher_guided_junction_variant_replays_teacher_chain(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    teacher_net = Path("teacher.net.xml")
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j" type="highway.primary" numLanes="1">
    <lane id="teacher_in_0" index="0" disallow="pedestrian" shape="-10,0 0,0"/>
  </edge>
  <edge id="teacher_out" from="j" to="b" type="highway.primary" numLanes="1">
    <lane id="teacher_out_0" index="0" disallow="pedestrian" shape="0,0 10,0"/>
  </edge>
  <edge id="teacher_ped" from="p" to="j" type="highway.footway" numLanes="1">
    <lane id="teacher_ped_0" index="0" allow="pedestrian" shape="-2,2 0,0"/>
  </edge>
  <edge id=":j_c0" function="crossing" crossingEdges="teacher_in">
    <lane id=":j_c0_0" index="0" allow="pedestrian"/>
  </edge>
  <edge id=":j_w0" function="walkingarea">
    <lane id=":j_w0_0" index="0" allow="pedestrian"/>
  </edge>
  <junction id="j" type="traffic_light" incLanes="teacher_in_0 teacher_ped_0" intLanes=":j_c0_0 :j_w0_0"/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="j" linkIndex="0" dir="s" state="O"/>
  <connection from="teacher_ped" to=":j_w0" fromLane="0" toLane="0" dir="s" state="M"/>
  <connection from=":j_w0" to=":j_c0" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="s" state="M"/>
  <connection from=":j_c0" to=":j_w0" fromLane="0" toLane="0" dir="s" state="M"/>
  <tlLogic id="j" type="actuated" programID="0" offset="0">
    <phase duration="4" state="GM"/>
  </tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = Path("candidate.net.xml")
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="cand_ped" from="p" to="j" type="highway.footway"><lane id="cand_ped_0" index="0" allow="pedestrian" shape="-2,2 0,0"/></edge>
  <junction id="j" type="traffic_light" incLanes="cand_in_0 cand_ped_0" intLanes=""/>
</net>
""",
        encoding="utf-8",
    )
    raw_nodes = Path("raw.nod.xml")
    raw_nodes.write_text('<nodes><node id="a" x="-10" y="0"/><node id="j" x="0" y="0"/><node id="b" x="10" y="0"/></nodes>', encoding="utf-8")
    raw_edges = Path("raw.edg.xml")
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j" numLanes="1"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b" numLanes="1"><lane index="0"/></edge>
  <edge id="cand_ped" from="p" to="j" numLanes="1"><lane index="0" allow="pedestrian"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    raw_connections = Path("raw.con.xml")
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        calls.append(command)
        if command[0] == "netconvert":
            assert Path(command[command.index("--node-files") + 1]).is_absolute()
            for flag in ("--edge-files", "--connection-files", "--output-file"):
                assert not Path(command[command.index(flag) + 1]).is_absolute()

            def command_path(flag: str) -> Path:
                value = Path(command[command.index(flag) + 1])
                return value if value.is_absolute() else Path(cwd) / value

            output_file = command_path("--output-file")
            connection_file = command_path("--connection-files")
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0" disallow="pedestrian" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0" disallow="pedestrian" shape="0,0 10,0"/></edge>
  <edge id="cand_ped" from="p" to="j" type="highway.footway"><lane id="cand_ped_0" index="0" allow="pedestrian" shape="-2,2 0,0"/></edge>
  <edge id=":j_cA" function="crossing" crossingEdges="cand_in"><lane id=":j_cA_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_wKeep" function="walkingarea"><lane id=":j_wKeep_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_wExtra" function="walkingarea"><lane id=":j_wExtra_0" index="0" allow="pedestrian"/></edge>
  <junction id="j" type="traffic_light" incLanes="cand_in_0 cand_ped_0 :j_wKeep_0 :j_wExtra_0" intLanes=":j_cA_0 :j_wKeep_0 :j_wExtra_0"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="rr"/></tlLogic>
  <connection from=":j_wKeep" to=":j_cA" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="s" state="M"/>
</net>
""",
                encoding="utf-8",
            )
            net_root = ET.parse(output_file).getroot()
            for connection in ET.parse(connection_file).getroot().findall("connection"):
                net_root.append(connection)
            ET.ElementTree(net_root).write(output_file, encoding="utf-8", xml_declaration=True)

        class Result:
            status = "pass"
            returncode = 0

            def to_dict(self):
                return {"command": command, "cwd": str(cwd) if cwd else None, "status": "pass", "returncode": 0}

        return Result()

    report = build_teacher_guided_junction_variant(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        junction_id="j",
        output_dir=Path("out"),
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out", "teacher_ped": "cand_ped"},
        prefix="demo",
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["final_net_file"].endswith("demo_teacher_guided.net.xml")
    assert report["parity"]["delta"]["vehicle_connection_count"] == 0
    assert report["parity"]["delta"]["pedestrian_connection_count"] == 0
    assert report["parity"]["delta"]["walkingarea_count"] == 0
    assert report["parity"]["delta"]["tl_phase_count"] == 0
    root = ET.parse(report["final_net_file"]).getroot()
    assert root.find("tlLogic[@id='j']").attrib["type"] == "actuated"
    assert root.find("edge[@id=':j_wExtra']") is None
    vehicle_connection = root.find("connection[@from='cand_in'][@to='cand_out']")
    assert vehicle_connection.attrib["tl"] == "j"
    assert vehicle_connection.attrib["linkIndex"] == "0"
    assert vehicle_connection.attrib["dir"] == "s"
    assert vehicle_connection.attrib["state"] == "O"
    assert [call[0] for call in calls] == ["netconvert", "sumo"]


def test_build_teacher_guided_junction_variant_can_replay_and_normalize_target_internal_subgraph(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    teacher_net = Path("teacher.net.xml")
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j" type="highway.primary" numLanes="1">
    <lane id="teacher_in_0" index="0" disallow="pedestrian" shape="-10,0 0,0"/>
  </edge>
  <edge id="teacher_out" from="j" to="b" type="highway.primary" numLanes="1">
    <lane id="teacher_out_0" index="0" disallow="pedestrian" shape="0,0 10,0"/>
  </edge>
  <edge id="teacher_ped" from="p" to="j" type="highway.footway" numLanes="1">
    <lane id="teacher_ped_0" index="0" allow="pedestrian" shape="-2,2 0,0"/>
  </edge>
  <edge id=":j_c0" function="crossing" crossingEdges="teacher_in">
    <lane id=":j_c0_0" index="0" allow="pedestrian"/>
  </edge>
  <edge id=":j_w0" function="walkingarea">
    <lane id=":j_w0_0" index="0" allow="pedestrian"/>
  </edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="teacher_in_0 teacher_ped_0" intLanes=":j_c0_0 :j_w0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="j" linkIndex="0" dir="s" state="O"/>
  <connection from="teacher_ped" to=":j_w0" fromLane="0" toLane="0" dir="s" state="M"/>
  <connection from=":j_w0" to=":j_c0" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="s" state="M"/>
  <connection from=":j_c0" to=":j_w0" fromLane="0" toLane="0" dir="s" state="M"/>
  <tlLogic id="j" type="actuated" programID="0" offset="0">
    <phase duration="4" state="GM"/>
  </tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = Path("candidate.net.xml")
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="cand_ped" from="p" to="j" type="highway.footway"><lane id="cand_ped_0" index="0" allow="pedestrian" shape="-2,2 0,0"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="cand_in_0 cand_ped_0" intLanes=""/>
</net>
""",
        encoding="utf-8",
    )
    raw_nodes = Path("raw.nod.xml")
    raw_nodes.write_text('<nodes><node id="a" x="-10" y="0"/><node id="j" x="0" y="0"/><node id="b" x="10" y="0"/></nodes>', encoding="utf-8")
    raw_edges = Path("raw.edg.xml")
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j" numLanes="1"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b" numLanes="1"><lane index="0"/></edge>
  <edge id="cand_ped" from="p" to="j" numLanes="1"><lane index="0" allow="pedestrian"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    raw_connections = Path("raw.con.xml")
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        calls.append(command)
        if command[0] == "netconvert" and "--node-files" in command:
            assert Path(command[command.index("--node-files") + 1]).is_absolute()
            for flag in ("--edge-files", "--connection-files", "--output-file"):
                assert not Path(command[command.index(flag) + 1]).is_absolute()

            def command_path(flag: str) -> Path:
                value = Path(command[command.index(flag) + 1])
                return value if value.is_absolute() else Path(cwd) / value

            output_file = command_path("--output-file")
            connection_file = command_path("--connection-files")
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0" disallow="pedestrian" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0" disallow="pedestrian" shape="0,0 10,0"/></edge>
  <edge id="cand_ped" from="p" to="j" type="highway.footway"><lane id="cand_ped_0" index="0" allow="pedestrian" shape="-2,2 0,0"/></edge>
  <edge id=":j_cA" function="crossing" crossingEdges="cand_in"><lane id=":j_cA_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_wKeep" function="walkingarea"><lane id=":j_wKeep_0" index="0" allow="pedestrian"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="cand_in_0 cand_ped_0 :j_wKeep_0" intLanes=":j_cA_0 :j_wKeep_0"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="rr"/></tlLogic>
  <connection from=":j_wKeep" to=":j_cA" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="s" state="M"/>
</net>
""",
                encoding="utf-8",
            )
            net_root = ET.parse(output_file).getroot()
            for connection in ET.parse(connection_file).getroot().findall("connection"):
                net_root.append(connection)
            ET.ElementTree(net_root).write(output_file, encoding="utf-8", xml_declaration=True)
        elif command[0] == "netconvert" and "--sumo-net-file" in command:
            assert not Path(command[command.index("--sumo-net-file") + 1]).is_absolute()
            assert not Path(command[command.index("--output-file") + 1]).is_absolute()

            def command_path(flag: str) -> Path:
                value = Path(command[command.index(flag) + 1])
                return value if value.is_absolute() else Path(cwd) / value

            input_file = command_path("--sumo-net-file")
            output_file = command_path("--output-file")
            output_file.write_text(input_file.read_text(encoding="utf-8"), encoding="utf-8")

        class Result:
            status = "pass"
            returncode = 0

            def to_dict(self):
                return {"command": command, "cwd": str(cwd) if cwd else None, "status": "pass", "returncode": 0}

        return Result()

    report = build_teacher_guided_junction_variant(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        junction_id="j",
        output_dir=Path("out"),
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out", "teacher_ped": "cand_ped"},
        prefix="demo",
        replay_target_internal_subgraph=True,
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["parity_gate_status"] == "pass"
    assert report["review_policy"].startswith("diagnostic")
    assert report["target_internal_replay"]["copied_internal_edge_count"] == 2
    assert report["target_internal_replay"]["copied_internal_junction_count"] == 0
    assert report["target_internal_normalize"] is None
    assert report["target_internal_pedestrian_ring"] is None
    assert report["target_internal_vehicle_connection_attrs"] is None
    assert report["parity"]["delta"]["vehicle_connection_count"] == 0
    assert report["parity"]["delta"]["pedestrian_connection_count"] == 0
    root = ET.parse(report["final_net_file"]).getroot()
    assert root.find("edge[@id=':j_c0']") is not None
    assert [call[0] for call in calls] == ["netconvert", "sumo"]


def test_build_teacher_guided_junction_variant_falls_back_when_target_internal_replay_fails_load(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    teacher_net = Path("teacher.net.xml")
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j" type="highway.primary"><lane id="teacher_in_0" index="0"/></edge>
  <edge id="teacher_out" from="j" to="b" type="highway.primary"><lane id="teacher_out_0" index="0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = Path("candidate.net.xml")
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>
""",
        encoding="utf-8",
    )
    raw_nodes = Path("raw.nod.xml")
    raw_nodes.write_text('<nodes><node id="a" x="-10" y="0"/><node id="j" x="0" y="0"/><node id="b" x="10" y="0"/></nodes>', encoding="utf-8")
    raw_edges = Path("raw.edg.xml")
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    raw_connections = Path("raw.con.xml")
    raw_connections.write_text("<connections/>\n", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            connection_file = Path(cwd) / command[command.index("--connection-files") + 1]
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>
""",
                encoding="utf-8",
            )
            root = ET.parse(output_file).getroot()
            for connection in ET.parse(connection_file).getroot().findall("connection"):
                root.append(connection)
            ET.ElementTree(root).write(output_file, encoding="utf-8", xml_declaration=True)

        class Result:
            status = "pass"
            returncode = 0

            def to_dict(self):
                net_file = command[command.index("-n") + 1] if command[0] == "sumo" else ""
                status = "fail" if net_file.endswith("teacher_guided.net.xml") else "pass"
                return {
                    "command": command,
                    "cwd": str(cwd) if cwd else None,
                    "status": status,
                    "returncode": 1 if status == "fail" else 0,
                    "stderr": "final replay load failed" if status == "fail" else "",
                }

        return Result()

    report = build_teacher_guided_junction_variant(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        junction_id="j",
        output_dir=Path("out"),
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        prefix="demo",
        replay_target_internal_subgraph=True,
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["target_internal_replay_fallback"] is True
    assert report["target_internal_replay_fallback_sumo"]["status"] == "pass"
    assert report["final_net_file"].endswith("demo_teacher_guided_fallback.net.xml")
    assert report["tl_logic"]["net_file"] == report["final_net_file"]

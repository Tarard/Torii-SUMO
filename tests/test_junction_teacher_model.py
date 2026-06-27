from pathlib import Path

from torii_sumo.core.junction_teacher_model import (
    evaluate_netedit_semantics_gate,
    extract_junction_pattern_exemplar,
    extract_junction_pattern_index,
    extract_teacher_junction_model,
    materialize_exemplar_movement_signatures,
    match_teacher_approaches,
    slot_edge_map_from_exemplar,
)


def test_netedit_semantics_gate_fails_on_non_same_statuses() -> None:
    summary = {
        "status_counts": {
            "tls_linkIndex_diff": {"same": 23},
            "phase_diff": {"same": 10},
            "request_diff": {"same": 41},
            "internal_lane_diff": {"same": 59},
            "crossing_walkingarea_diff": {"same": 10},
            "junction_attrs_diff": {"same": 8},
            "connection_exact_diff": {"same": 108, "candidate_extra": 1},
        }
    }

    result = evaluate_netedit_semantics_gate(summary)

    assert result == {
        "status": "fail",
        "failed_tables": ["connection_exact_diff"],
        "reason": "non_same_rows_present",
    }


def test_netedit_semantics_gate_passes_when_all_tables_are_same() -> None:
    summary = {
        "status_counts": {
            "tls_linkIndex_diff": {"same": 23},
            "phase_diff": {"same": 10},
            "request_diff": {"same": 41},
        }
    }

    assert evaluate_netedit_semantics_gate(summary) == {"status": "pass", "failed_tables": [], "reason": ""}


def test_teacher_model_extracts_multimodal_junction(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" allow="passenger" shape="0,0 5,0"/></edge>
  <edge id=":j_c0" function="crossing" crossingEdges="in out"><lane id=":j_c0_0" index="0" allow="pedestrian" width="4.00" shape="0,-2 0,2"/></edge>
  <edge id=":j_w0" function="walkingarea"><lane id=":j_w0_0" index="0" allow="pedestrian" width="4.00" shape="0,2 2,2"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="in_0 :j_w0_0" intLanes=":j_0_0 :j_c0_0"/>
  <tlLogic id="j" type="actuated" programID="0"><phase duration="30" state="Gr"/></tlLogic>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="s"/>
  <connection from=":j_w0" to=":j_c0" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="s"/>
</net>
""",
        encoding="utf-8",
    )

    model = extract_teacher_junction_model(net_file, "j")

    assert model["summary"]["vehicle_connection_count"] == 1
    assert model["summary"]["crossing_count"] == 1
    assert model["summary"]["walkingarea_count"] == 1
    assert model["summary"]["pedestrian_connection_count"] == 1
    assert model["summary"]["tl_phase_count"] == 1
    assert model["approaches"]["incoming"][0]["bearing"] == 0.0
    assert model["vehicle_connections"][0]["linkIndex"] == "0"
    assert model["crossings"][0]["crossingEdges"] == ["in", "out"]


def test_teacher_model_keeps_junction_requests_internal_connections_and_referenced_tls(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" allow="passenger" shape="0,0 5,0"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="in_0" intLanes=":j_0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":j_0_0" tl="cluster_tls" linkIndex="0" dir="s"/>
  <connection from=":j_0" to="out" fromLane="0" toLane="0" dir="s"/>
  <tlLogic id="cluster_tls" type="actuated" programID="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )

    model = extract_teacher_junction_model(net_file, "j")

    assert model["junction"]["type"] == "traffic_light"
    assert model["requests"] == [{"index": "0", "response": "0", "foes": "0", "cont": "0"}]
    assert model["internal_connections"] == [
        {"from": ":j_0", "to": "out", "fromLane": "0", "toLane": "0", "via": "", "tl": "", "linkIndex": "", "dir": "s", "state": ""}
    ]
    assert model["traffic_light"]["attributes"]["id"] == "cluster_tls"
    assert model["summary"]["junction_type"] == "traffic_light"
    assert model["summary"]["internal_connection_count"] == 1
    assert model["summary"]["tl_phase_count"] == 1


def test_extract_junction_pattern_index_groups_by_reusable_counts(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a_in" from="a" to="j"><lane id="a_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="b_in" from="b" to="j"><lane id="b_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="c_in" from="c" to="j"><lane id="c_in_0" index="0" allow="passenger" shape="10,0 0,0"/></edge>
  <edge id="a_out" from="j" to="a2"><lane id="a_out_0" index="0" allow="passenger" shape="0,0 -10,0"/></edge>
  <edge id="b_out" from="j" to="b2"><lane id="b_out_0" index="0" allow="passenger" shape="0,0 0,-10"/></edge>
  <edge id="c_out" from="j" to="c2"><lane id="c_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="0,0 1,1"/></edge>
  <junction id="j" type="right_before_left" x="0" y="0" incLanes="a_in_0 b_in_0 c_in_0" intLanes=":j_0_0">
    <request index="0" response="0" foes="0" cont="0"/>
    <request index="1" response="0" foes="0" cont="0"/>
    <request index="2" response="0" foes="0" cont="0"/>
  </junction>
  <connection from="a_in" to="a_out" fromLane="0" toLane="0" dir="t"/>
  <connection from="a_in" to="b_out" fromLane="0" toLane="0" dir="r"/>
  <connection from="a_in" to="c_out" fromLane="0" toLane="0" dir="l"/>
</net>""",
        encoding="utf-8",
    )

    records = extract_junction_pattern_index(net_file, min_approaches=3, max_approaches=4)

    assert records == [
        {
            "junction_id": "j",
            "arm_count": 3,
            "control_type": "right_before_left",
            "in_edge_count": 3,
            "out_edge_count": 3,
            "vehicle_connection_count": 3,
            "dir_counts": {"l": 1, "r": 1, "t": 1},
            "movement_signature_counts": {
                "dir=l|state=blank|fromLane=0|toLane=0|controlled=false|via=false": 1,
                "dir=r|state=blank|fromLane=0|toLane=0|controlled=false|via=false": 1,
                "dir=t|state=blank|fromLane=0|toLane=0|controlled=false|via=false": 1,
            },
            "crossing_count": 0,
            "walkingarea_count": 0,
            "request_count": 3,
            "tl_phase_count": 0,
            "controlled_link_count": 0,
        }
    ]


def test_extract_junction_pattern_index_keeps_blank_connection_dir(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a_in" from="a" to="j"><lane id="a_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="b_in" from="b" to="j"><lane id="b_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="c_in" from="c" to="j"><lane id="c_in_0" index="0" allow="passenger" shape="10,0 0,0"/></edge>
  <edge id="a_out" from="j" to="a2"><lane id="a_out_0" index="0" allow="passenger" shape="0,0 -10,0"/></edge>
  <edge id="b_out" from="j" to="b2"><lane id="b_out_0" index="0" allow="passenger" shape="0,0 0,-10"/></edge>
  <edge id="c_out" from="j" to="c2"><lane id="c_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="j" type="right_before_left" x="0" y="0" incLanes="a_in_0 b_in_0 c_in_0" intLanes=""/>
  <connection from="a_in" to="a_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )

    records = extract_junction_pattern_index(net_file)

    assert records[0]["dir_counts"] == {"blank": 1}


def test_extract_junction_pattern_index_counts_non_matching_tls_id(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a_in" from="a" to="j"><lane id="a_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="b_in" from="b" to="j"><lane id="b_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="c_in" from="c" to="j"><lane id="c_in_0" index="0" allow="passenger" shape="10,0 0,0"/></edge>
  <edge id="a_out" from="j" to="a2"><lane id="a_out_0" index="0" allow="passenger" shape="0,0 -10,0"/></edge>
  <edge id="b_out" from="j" to="b2"><lane id="b_out_0" index="0" allow="passenger" shape="0,0 0,-10"/></edge>
  <edge id="c_out" from="j" to="c2"><lane id="c_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="a_in_0 b_in_0 c_in_0" intLanes=""/>
  <connection from="a_in" to="a_out" fromLane="0" toLane="0" tl="cluster_tls" linkIndex="0" dir="s"/>
  <tlLogic id="cluster_tls" type="actuated" programID="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )

    records = extract_junction_pattern_index(net_file)

    assert records[0]["controlled_link_count"] == 1
    assert records[0]["tl_phase_count"] == 1


def test_extract_junction_pattern_index_parses_net_once(tmp_path: Path, monkeypatch) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a_in" from="a" to="j"><lane id="a_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="b_in" from="b" to="j"><lane id="b_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="c_in" from="c" to="j"><lane id="c_in_0" index="0" allow="passenger" shape="10,0 0,0"/></edge>
  <edge id="a_out" from="j" to="a2"><lane id="a_out_0" index="0" allow="passenger" shape="0,0 -10,0"/></edge>
  <edge id="b_out" from="j" to="b2"><lane id="b_out_0" index="0" allow="passenger" shape="0,0 0,-10"/></edge>
  <edge id="c_out" from="j" to="c2"><lane id="c_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="j" type="right_before_left" x="0" y="0" incLanes="a_in_0 b_in_0 c_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )
    from torii_sumo.core import junction_teacher_model

    parse_calls = 0
    original_parse = junction_teacher_model.ET.parse

    def counted_parse(path):
        nonlocal parse_calls
        parse_calls += 1
        return original_parse(path)

    monkeypatch.setattr(junction_teacher_model.ET, "parse", counted_parse)

    extract_junction_pattern_index(net_file)

    assert parse_calls == 1


def test_extract_junction_pattern_exemplar_uses_slots_not_edge_ids(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="north_in" from="n" to="j"><lane id="north_in_0" index="0" allow="passenger" speed="13.89" shape="0,10 0,0"/></edge>
  <edge id="east_out" from="j" to="e"><lane id="east_out_0" index="0" allow="passenger" speed="13.89" shape="0,0 10,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" speed="10.0" shape="0,0 2,0"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="north_in_0" intLanes=":j_0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <tlLogic id="j" type="actuated" programID="0" offset="0"><phase duration="30" state="G"/></tlLogic>
  <connection from="north_in" to="east_out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="r" state="O"/>
</net>""",
        encoding="utf-8",
    )

    exemplar = extract_junction_pattern_exemplar(net_file, "j")

    assert exemplar["junction_id"] == "j"
    assert exemplar["approach_slots"][0]["slot_id"] == "slot_0"
    assert exemplar["approach_slots"][0]["members"] == ["north_in"]
    assert exemplar["vehicle_connections"] == [
        {
            "from_slot": "slot_0",
            "to_slot": "slot_1",
            "fromLane": "0",
            "toLane": "0",
            "via": ":j_0_0",
            "tl": "j",
            "linkIndex": "0",
            "dir": "r",
            "state": "O",
        }
    ]
    assert exemplar["movement_signatures"] == [
        {
            "from_slot": "slot_0",
            "to_slot": "slot_1",
            "fromLane": "0",
            "toLane": "0",
            "dir": "r",
            "state": "O",
            "controlled": True,
            "linkIndex": "0",
            "has_internal_via": True,
        }
    ]
    assert exemplar["traffic_light"]["phases"][0]["state"] == "G"
    assert exemplar["requests"][0]["foes"] == "0"


def test_materialize_exemplar_movement_signatures_filters_four_way_cross_product() -> None:
    exemplar = {
        "movement_signatures": [
            {
                "from_slot": "slot_0",
                "to_slot": "slot_2",
                "fromLane": "0",
                "toLane": "0",
                "dir": "s",
                "state": "O",
                "controlled": True,
                "linkIndex": "0",
                "has_internal_via": True,
            },
            {
                "from_slot": "slot_1",
                "to_slot": "slot_3",
                "fromLane": "0",
                "toLane": "0",
                "dir": "r",
                "state": "o",
                "controlled": True,
                "linkIndex": "1",
                "has_internal_via": True,
            },
        ]
    }

    movements = materialize_exemplar_movement_signatures(
        exemplar,
        {"slot_0": "west_in", "slot_1": "south_in", "slot_2": "east_out", "slot_3": "west_out"},
    )

    assert [(movement["from_edge_id"], movement["to_edge_id"]) for movement in movements] == [
        ("west_in", "east_out"),
        ("south_in", "west_out"),
    ]
    assert {movement["dir"] for movement in movements} == {"s", "r"}
    assert len(movements) == 2


def test_slot_edge_map_from_exemplar_uses_teacher_edge_map() -> None:
    exemplar = {
        "approach_slots": [
            {"slot_id": "slot_0", "members": ["teacher_in"]},
            {"slot_id": "slot_1", "members": ["teacher_out", "teacher_out_alt"]},
            {"slot_id": "slot_2", "members": ["unmatched"]},
        ]
    }

    slot_edge_map = slot_edge_map_from_exemplar(
        exemplar,
        {"teacher_in": "cand_in", "teacher_out_alt": "cand_out"},
    )

    assert slot_edge_map == {"slot_0": "cand_in", "slot_1": "cand_out"}


def test_match_teacher_edges_by_bearing_and_lane_count() -> None:
    teacher = [{"edge_id": "t1", "bearing": 90.0, "lane_count": 2}]
    candidate = [{"edge_id": "c1", "bearing": 92.0, "lane_count": 2}]

    matches = match_teacher_approaches(teacher, candidate, max_bearing_delta=10.0)

    assert matches == {"t1": "c1"}


def test_match_teacher_edges_does_not_treat_shared_junction_from_as_external_source() -> None:
    teacher = [{"edge_id": "t1", "from": "junction", "bearing": 90.0, "lane_count": 1}]
    candidate = [
        {"edge_id": "wrong", "from": "junction", "bearing": 250.0, "lane_count": 1},
        {"edge_id": "right", "from": "other", "bearing": 91.0, "lane_count": 1},
    ]

    matches = match_teacher_approaches(teacher, candidate, max_bearing_delta=10.0)

    assert matches == {"t1": "right"}


def test_match_teacher_edges_prefers_same_type_over_slightly_closer_bearing() -> None:
    teacher = [{"edge_id": "cycle", "bearing": 304.0, "lane_count": 1, "type": "highway.cycleway"}]
    candidate = [
        {"edge_id": "footway", "bearing": 297.0, "lane_count": 1, "type": "highway.footway"},
        {"edge_id": "cycleway", "bearing": 319.0, "lane_count": 1, "type": "highway.cycleway"},
    ]

    matches = match_teacher_approaches(teacher, candidate, max_bearing_delta=35.0)

    assert matches == {"cycle": "cycleway"}

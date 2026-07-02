from pathlib import Path

from torii_sumo.core.junction_connection_audit import (
    build_connection_signature,
    build_teacher_guided_owner_semantics_probe,
    compare_tls_movement_signatures,
    write_connection_signature,
)


def test_connection_signature_separates_top_level_and_internal(tmp_path: Path) -> None:
    net_file = tmp_path / "connection.net.xml"
    net_file.write_text(
        """<net>
  <edge id="in" from="a" to="j" type="highway.primary">
    <lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/>
  </edge>
  <edge id="out" from="j" to="b" type="highway.primary">
    <lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/>
  </edge>
  <edge id=":j_0" function="internal">
    <lane id=":j_0_0" index="0" allow="passenger" shape="0,0 4,0"/>
  </edge>
  <junction id="a" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="b" x="10" y="0" type="priority"/>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":j_0_0" dir="s" state="o"/>
  <connection from=":j_0" to="out" fromLane="0" toLane="0" dir="s" state="o"/>
</net>
""",
        encoding="utf-8",
    )

    signature = build_connection_signature(net_file, "j")

    assert signature["top_external_connection_count"] == 1
    assert signature["top_external_pair_count"] == 1
    assert signature["category_counts"]["internal_or_other_to_outgoing"] == 1
    assert signature["top_external_dir_counts"] == {"s": 1}
    assert signature["top_external_turnaround_connection_count"] == 0
    assert signature["top_external_non_turnaround_connection_count"] == 1


def test_connection_signature_counts_turnaround_separately_from_normal_movements(tmp_path: Path) -> None:
    net_file = tmp_path / "turnaround.net.xml"
    net_file.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="back" from="j" to="a"><lane id="back_0" index="0" allow="passenger" shape="0,0 -10,0"/></edge>
  <junction id="j" x="0" y="0" type="priority"/>
  <connection from="in" to="out" fromLane="0" toLane="0" dir="s"/>
  <connection from="in" to="back" fromLane="0" toLane="0" dir="t"/>
</net>
""",
        encoding="utf-8",
    )

    signature = build_connection_signature(net_file, "j")

    assert signature["top_external_dir_counts"] == {"s": 1, "t": 1}
    assert signature["top_external_turnaround_connection_count"] == 1
    assert signature["top_external_non_turnaround_connection_count"] == 1


def test_owner_semantics_probe_keeps_road_connectivity_separate_from_turnaround_junction_signature(
    tmp_path: Path,
) -> None:
    teacher = tmp_path / "teacher.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    teacher.write_text(
        """<net>
  <edge id="in#1" from="a" to="j"><lane id="in#1_0" index="0" allow="passenger"/></edge>
  <edge id="-in#1" from="j" to="a"><lane id="-in#1_0" index="0" allow="passenger"/></edge>
  <edge id="out#1" from="j" to="b"><lane id="out#1_0" index="0" allow="passenger"/></edge>
  <junction id="a" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="priority"/>
  <junction id="b" x="10" y="0" type="priority"/>
  <connection from="in#1" to="out#1" fromLane="0" toLane="0" dir="s"/>
  <connection from="in#1" to="-in#1" fromLane="0" toLane="0" dir="t"/>
</net>
""",
        encoding="utf-8",
    )
    candidate.write_text(
        """<net>
  <edge id="in#3" from="a" to="j"><lane id="in#3_0" index="0" allow="passenger"/></edge>
  <edge id="-in#3" from="j" to="a"><lane id="-in#3_0" index="0" allow="passenger"/></edge>
  <edge id="out#3" from="j" to="b"><lane id="out#3_0" index="0" allow="passenger"/></edge>
  <junction id="a" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="priority"/>
  <junction id="b" x="10" y="0" type="priority"/>
  <connection from="in#3" to="-in#3" fromLane="0" toLane="0" dir="t"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_teacher_guided_owner_semantics_probe(
        teacher,
        candidate,
        owner_id="j",
        teacher_edge_map={"in#1": "in#3", "-in#1": "-in#3", "out#1": "out#3"},
    )

    assert report["status"] == "fail"
    assert report["layer_statuses"] == {
        "edge_mapping": "pass",
        "road_connectivity": "fail",
        "junction_connection": "fail",
        "tls_movement": "skipped",
    }
    assert report["road_connectivity_layer"]["gate"]["missing_non_turnaround_outgoing_count"] == 1
    assert report["road_connectivity_layer"]["gate"]["turnaround_only_outgoing_count"] == 1
    assert report["junction_connection_layer"]["teacher"]["top_external_non_turnaround_connection_count"] == 1
    assert report["junction_connection_layer"]["candidate"]["top_external_non_turnaround_connection_count"] == 0
    assert report["junction_connection_layer"]["candidate_turnaround_only_top_external"] is True


def test_owner_semantics_probe_reuses_inferred_edge_map_for_tls_compare(tmp_path: Path) -> None:
    teacher = tmp_path / "teacher.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    teacher.write_text(
        """<net>
  <edge id="in#1" from="a" to="j"><lane id="in#1_0" index="0" allow="passenger"/></edge>
  <edge id="out#1" from="j" to="b"><lane id="out#1_0" index="0" allow="passenger"/></edge>
  <junction id="a" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="b" x="10" y="0" type="priority"/>
  <connection from="in#1" to="out#1" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="s" state="M"/>
  <tlLogic id="j"><phase duration="10" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate.write_text(
        """<net>
  <edge id="in#3" from="a" to="j"><lane id="in#3_0" index="0" allow="passenger"/></edge>
  <edge id="out#3" from="j" to="b"><lane id="out#3_0" index="0" allow="passenger"/></edge>
  <junction id="a" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="b" x="10" y="0" type="priority"/>
  <connection from="in#3" to="out#3" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="s" state="M"/>
  <tlLogic id="j"><phase duration="10" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )

    report = build_teacher_guided_owner_semantics_probe(teacher, candidate, owner_id="j")

    assert report["layer_statuses"]["tls_movement"] == "pass"
    assert report["teacher_edge_map"] == {"in#1": "in#3", "out#1": "out#3"}
    assert report["tls_movement_layer"]["teacher_only_normalized_movement_signatures"] == []
    assert report["tls_movement_layer"]["candidate_only_normalized_movement_signatures"] == []


def test_owner_semantics_probe_reports_ambiguous_edge_mapping(tmp_path: Path) -> None:
    teacher = tmp_path / "teacher.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    teacher.write_text(
        """<net>
  <edge id="road#0" from="j" to="b"><lane id="road#0_0" index="0" allow="passenger"/></edge>
  <junction id="j" x="0" y="0" type="priority"/>
  <junction id="b" x="10" y="0" type="priority"/>
</net>
""",
        encoding="utf-8",
    )
    candidate.write_text(
        """<net>
  <edge id="road#1" from="j" to="b"><lane id="road#1_0" index="0" allow="passenger"/></edge>
  <edge id="road#2" from="j" to="b"><lane id="road#2_0" index="0" allow="passenger"/></edge>
  <junction id="j" x="0" y="0" type="priority"/>
  <junction id="b" x="10" y="0" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_teacher_guided_owner_semantics_probe(teacher, candidate, owner_id="j")

    assert report["status"] == "fail"
    assert report["layer_statuses"]["edge_mapping"] == "fail"
    assert report["edge_mapping_layer"]["ambiguous_teacher_edges"] == ["road#0"]
    assert report["teacher_edge_map"] == {}


def test_connection_signature_records_tls_link_indices(tmp_path: Path) -> None:
    net_file = tmp_path / "tls.net.xml"
    net_file.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <connection from="in" to="out" fromLane="0" toLane="0" tl="j" linkIndex="7" linkIndex2="12" dir="s" state="O" pass="true" uncontrolled="true" allow="bicycle" disallow="truck" keepClear="0" contPos="43.00" shape="0,0 1,1"/>
</net>
""",
        encoding="utf-8",
    )

    signature = build_connection_signature(net_file, "j")

    assert signature["controlled_link_count"] == 1
    record = signature["connection_records"][0]
    assert record["tl"] == "j"
    assert record["linkIndex"] == "7"
    assert record["linkIndex2"] == "12"
    assert record["pass"] == "true"
    assert record["uncontrolled"] == "true"
    assert record["allow"] == "bicycle"
    assert record["disallow"] == "truck"
    assert record["keepClear"] == "0"
    assert record["contPos"] == "43.00"
    assert record["shape"] == "0,0 1,1"


def test_connection_signature_counts_crossings_and_walkingareas(tmp_path: Path) -> None:
    net_file = tmp_path / "modal.net.xml"
    net_file.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id=":j_c0" function="crossing"><lane id=":j_c0_0" index="0" allow="pedestrian" shape="0,-2 0,2"/></edge>
  <edge id=":j_w0" function="walkingarea"><lane id=":j_w0_0" index="0" allow="pedestrian" shape="0,2 2,2"/></edge>
  <junction id="j" x="0" y="0" type="traffic_light" incLanes="in_0 :j_w0_0" intLanes=":j_c0_0"/>
  <connection from="in" to="out" fromLane="0" toLane="0"/>
</net>
""",
        encoding="utf-8",
    )

    signature = build_connection_signature(net_file, "j")

    assert signature["crossing_count"] == 1
    assert signature["walkingarea_count"] == 1


def test_write_connection_signature_outputs_review_files(tmp_path: Path) -> None:
    net_file = tmp_path / "connection.net.xml"
    net_file.write_text(
        """<net>
  <edge id="in" from="a" to="j" type="highway.primary"><lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b" type="highway.primary"><lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="a" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="b" x="10" y="0" type="priority"/>
  <connection from="in" to="out" fromLane="0" toLane="0" dir="s" state="o" keepClear="0" shape="0,0 1,1"/>
</net>
""",
        encoding="utf-8",
    )
    signature = build_connection_signature(net_file, "j")

    report = write_connection_signature(signature, tmp_path / "review", "demo")

    assert Path(report["signature_file"]).is_file()
    records_header = Path(report["records_file"]).read_text(encoding="utf-8").splitlines()[0]
    top_external_header = Path(report["top_external_file"]).read_text(encoding="utf-8").splitlines()[0]
    for field in ("linkIndex2", "pass", "uncontrolled", "allow", "disallow", "keepClear", "contPos", "shape"):
        assert field in records_header
        assert field in top_external_header


def test_tls_movement_compare_ignores_internal_id_prefix_when_linkindex_and_phases_match(
    tmp_path: Path,
) -> None:
    teacher = tmp_path / "teacher.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    teacher.write_text(
        """<net>
  <connection from="in" to="out" fromLane="0" toLane="1" via=":teacher_tls_0_0" tl="teacher_tls" linkIndex="3" dir="l" state="m"/>
  <tlLogic id="teacher_tls" type="static" programID="0" offset="0">
    <phase duration="42" state="Gr"/>
    <phase duration="3" state="yr"/>
  </tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate.write_text(
        """<net>
  <connection from="in" to="out" fromLane="0" toLane="1" via=":candidate_tls_0_0" tl="candidate_tls" linkIndex="3" dir="l" state="m"/>
  <tlLogic id="candidate_tls" type="static" programID="0" offset="0">
    <phase duration="42" state="Gr"/>
    <phase duration="3" state="yr"/>
  </tlLogic>
</net>
""",
        encoding="utf-8",
    )

    report = compare_tls_movement_signatures(teacher, candidate, "teacher_tls", "candidate_tls")

    assert report["status"] == "pass"
    assert report["teacher_connection_count"] == 1
    assert report["candidate_connection_count"] == 1
    assert report["movement_signature_equal_after_internal_id_normalization"] is True
    assert report["tl_logic_phase_states_equal"] is True
    assert report["teacher_only_normalized_movement_signatures"] == []
    assert report["candidate_only_normalized_movement_signatures"] == []


def test_tls_movement_compare_maps_teacher_external_edges(tmp_path: Path) -> None:
    teacher = tmp_path / "teacher.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    teacher.write_text(
        """<net>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="teacher_tls" linkIndex="0" dir="s" state="O"/>
  <tlLogic id="teacher_tls"><phase duration="10" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate.write_text(
        """<net>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0" tl="candidate_tls" linkIndex="0" dir="s" state="O"/>
  <tlLogic id="candidate_tls"><phase duration="10" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )

    report = compare_tls_movement_signatures(
        teacher,
        candidate,
        "teacher_tls",
        "candidate_tls",
        teacher_edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    assert report["status"] == "pass"
    assert report["teacher_only_normalized_movement_signatures"] == []
    assert report["candidate_only_normalized_movement_signatures"] == []


def test_tls_movement_compare_can_scope_multi_junction_tls_to_target_internal_owner(
    tmp_path: Path,
) -> None:
    teacher = tmp_path / "teacher.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    teacher.write_text(
        """<net>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":teacher_j_0_0" tl="teacher_tls" linkIndex="0" dir="s" state="O"/>
  <connection from="neighbor_in" to="neighbor_out" fromLane="0" toLane="0" via=":neighbor_j_0_0" tl="teacher_tls" linkIndex="1" dir="s" state="O"/>
  <tlLogic id="teacher_tls"><phase duration="10" state="GG"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate.write_text(
        """<net>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0" via=":candidate_j_0_0" tl="candidate_tls" linkIndex="0" dir="s" state="O"/>
  <tlLogic id="candidate_tls"><phase duration="10" state="GG"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )

    report = compare_tls_movement_signatures(
        teacher,
        candidate,
        "teacher_tls",
        "candidate_tls",
        teacher_edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        teacher_internal_scope_id="teacher_j",
        candidate_internal_scope_id="candidate_j",
    )

    assert report["status"] == "pass"
    assert report["teacher_connection_count"] == 1
    assert report["candidate_connection_count"] == 1
    assert report["teacher_only_normalized_movement_signatures"] == []
    assert report["candidate_only_normalized_movement_signatures"] == []
    assert report["scoped_internal_ids"] == {"teacher": "teacher_j", "candidate": "candidate_j"}


def test_tls_movement_compare_flags_linkindex_delta(tmp_path: Path) -> None:
    teacher = tmp_path / "teacher.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    teacher.write_text(
        """<net>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":teacher_tls_0_0" tl="teacher_tls" linkIndex="0" dir="s" state="M"/>
  <tlLogic id="teacher_tls"><phase duration="10" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate.write_text(
        """<net>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":candidate_tls_0_0" tl="candidate_tls" linkIndex="1" dir="s" state="M"/>
  <tlLogic id="candidate_tls"><phase duration="10" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )

    report = compare_tls_movement_signatures(teacher, candidate, "teacher_tls", "candidate_tls")

    assert report["status"] == "fail"
    assert report["movement_signature_equal_after_internal_id_normalization"] is False
    assert report["tl_logic_phase_states_equal"] is True
    assert report["teacher_only_normalized_movement_signatures"] == [
        "from=in|to=out|fromLane=0|toLane=0|via=:TARGET_0_0|linkIndex=0|dir=s|state=M"
    ]
    assert report["candidate_only_normalized_movement_signatures"] == [
        "from=in|to=out|fromLane=0|toLane=0|via=:TARGET_0_0|linkIndex=1|dir=s|state=M"
    ]


def test_tls_movement_compare_flags_phase_state_delta(tmp_path: Path) -> None:
    teacher = tmp_path / "teacher.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    teacher.write_text(
        """<net>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":teacher_tls_0_0" tl="teacher_tls" linkIndex="0" dir="s" state="M"/>
  <tlLogic id="teacher_tls"><phase duration="10" state="G"/><phase duration="3" state="y"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate.write_text(
        """<net>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":candidate_tls_0_0" tl="candidate_tls" linkIndex="0" dir="s" state="M"/>
  <tlLogic id="candidate_tls"><phase duration="10" state="G"/><phase duration="3" state="r"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )

    report = compare_tls_movement_signatures(teacher, candidate, "teacher_tls", "candidate_tls")

    assert report["status"] == "fail"
    assert report["movement_signature_equal_after_internal_id_normalization"] is True
    assert report["tl_logic_phase_states_equal"] is False
    assert report["teacher_phase_states"] == ["G", "y"]
    assert report["candidate_phase_states"] == ["G", "r"]

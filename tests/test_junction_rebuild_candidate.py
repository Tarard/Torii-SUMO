from pathlib import Path
import xml.etree.ElementTree as ET

from torii_sumo.core.junction_rebuild_candidate import (
    build_rebuild_candidate,
    build_teacher_guided_junction_variant,
    write_teacher_target_internal_replay_net,
    write_teacher_connection_plan,
    write_teacher_lane_patch_edges,
    write_teacher_pedestrian_ring_net,
    write_teacher_tllogic_net,
)


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
</connections>
""",
        encoding="utf-8",
    )
    candidate_edges = tmp_path / "candidate.edg.xml"
    candidate_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane index="0"/></edge>
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
    assert report["removed_target_children"] == 1


def test_write_teacher_lane_patch_edges_copies_lane_permissions_without_replacing_edge_geometry(tmp_path: Path) -> None:
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
    <lane index="0" allow="pedestrian" width="3.00" speed="13.89" shape="5,5 6,5"/>
    <lane index="1" disallow="pedestrian bicycle" speed="13.89" shape="5,6 6,6"/>
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
    )

    edge = ET.parse(report["edge_file"]).getroot().find("edge")
    assert edge.attrib["shape"] == "0,0 1,0"
    assert edge.attrib["numLanes"] == "2"
    lanes = edge.findall("lane")
    assert [lane.attrib.get("allow", "") for lane in lanes] == ["pedestrian", ""]
    assert [lane.attrib.get("disallow", "") for lane in lanes] == ["", "pedestrian bicycle"]
    assert report["patched_edge_count"] == 1


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


def test_write_teacher_target_internal_replay_net_maps_and_translates_teacher_subgraph(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="90,20 100,20"/></edge>
  <edge id="teacher_out" from="j" to="b"><lane id="teacher_out_0" index="0" shape="100,20 110,20"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="100,200 101,201"/></edge>
  <edge id=":j_c0" function="crossing" crossingEdges="teacher_in"><lane id=":j_c0_0" index="0" allow="pedestrian" shape="99,199 101,199"/></edge>
  <edge id=":j_w0" function="walkingarea"><lane id=":j_w0_0" index="0" allow="pedestrian" shape="98,198 99,199"/></edge>
  <junction id="j" type="traffic_light" x="100" y="200" shape="99,199 101,199 101,201 99,201" incLanes="teacher_in_0" intLanes=":j_0_0 :j_c0_0 :j_w0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="s" state="O"/>
  <connection from=":j_w0" to=":j_c0" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="s" state="M"/>
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
  <edge id=":j_old" function="internal"><lane id=":j_old_0" index="0" shape="10,20 11,20"/></edge>
  <junction id="j" type="traffic_light" x="10" y="20" shape="9,19 11,19 11,21 9,21" incLanes="cand_in_0" intLanes=":j_old_0"/>
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
    assert root.find("edge[@id=':j_0']/lane").attrib["shape"] == "10.00,20.00 11.00,21.00"
    assert root.find("edge[@id=':j_c0']").attrib["crossingEdges"] == "cand_in"
    junction = root.find("junction[@id='j']")
    assert junction.attrib["x"] == "10.00"
    assert junction.attrib["y"] == "20.00"
    assert junction.attrib["shape"] == "9.00,19.00 11.00,19.00 11.00,21.00 9.00,21.00"
    assert junction.attrib["incLanes"] == "cand_in_0"
    assert junction.attrib["intLanes"] == ":j_0_0 :j_c0_0 :j_w0_0"
    vehicle_connection = root.find("connection[@from='cand_in'][@to='cand_out']")
    assert vehicle_connection.attrib["via"] == ":j_0_0"
    assert root.find("connection[@from=':j_w0'][@to=':j_c0']").attrib["tl"] == "j"
    assert report["removed_internal_edge_count"] == 1
    assert report["copied_internal_edge_count"] == 3
    assert report["copied_connection_count"] == 2


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
            for flag in ("--node-files", "--edge-files", "--connection-files", "--output-file"):
                assert Path(command[command.index(flag) + 1]).is_absolute()
            output_file = Path(command[command.index("--output-file") + 1])
            connection_file = Path(command[command.index("--connection-files") + 1])
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0" shape="0,0 10,0"/></edge>
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
            output_file = Path(command[command.index("--output-file") + 1])
            connection_file = Path(command[command.index("--connection-files") + 1])
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0" shape="0,0 10,0"/></edge>
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
            input_file = Path(command[command.index("--sumo-net-file") + 1])
            output_file = Path(command[command.index("--output-file") + 1])
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
    assert report["target_internal_replay"]["copied_internal_edge_count"] == 2
    assert report["target_internal_normalize"]["status"] == "pass"
    assert report["target_internal_pedestrian_ring"]["status"] == "pass"
    assert report["parity"]["delta"]["vehicle_connection_count"] == 0
    assert report["parity"]["delta"]["pedestrian_connection_count"] == 0
    root = ET.parse(report["final_net_file"]).getroot()
    assert root.find("edge[@id=':j_cA']") is None
    assert root.find("edge[@id=':j_c0']") is not None
    assert [call[0] for call in calls] == ["netconvert", "netconvert", "sumo"]

from pathlib import Path
import xml.etree.ElementTree as ET

from torii_sumo.core.junction_rebuild_candidate import (
    build_rebuild_candidate,
    write_teacher_connection_plan,
    write_teacher_lane_patch_edges,
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

from pathlib import Path

from torii_sumo.core.junction_teacher_model import extract_teacher_junction_model, match_teacher_approaches


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

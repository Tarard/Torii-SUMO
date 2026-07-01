from pathlib import Path

from torii_sumo.core.road_connectivity_teacher_model import (
    canonical_road_connectivity_bundle,
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
    }


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

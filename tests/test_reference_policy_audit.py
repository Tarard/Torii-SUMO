from pathlib import Path

from torii_sumo.core.reference_policy_audit import build_reference_policy_report


def test_reference_policy_report_extracts_teacher_rules(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="main_in" from="a" to="cluster_1_2" type="highway.primary"><lane id="main_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="service" from="s" to="cluster_1_2" type="highway.service"><lane id="service_0" index="0" allow="delivery" shape="0,-10 0,0"/></edge>
  <edge id="main_out" from="cluster_1_2" to="b" type="highway.primary"><lane id="main_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="a" x="-10" y="0" type="priority"/>
  <junction id="s" x="0" y="-10" type="priority"/>
  <junction id="cluster_1_2" x="0" y="0" type="traffic_light"/>
  <junction id="b" x="10" y="0" type="priority"/>
  <tlLogic id="cluster_1_2" type="static" programID="0" offset="0"><phase duration="30" state="G"/></tlLogic>
  <connection from="main_in" to="main_out" fromLane="0" toLane="0" dir="s" state="O"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_reference_policy_report(net_file)

    assert report["road_type_counts"]["highway.primary"] == 2
    assert report["passenger_drivable_type_counts"] == {"highway.primary": 2}
    assert report["cluster_source_node_count_histogram"] == {"2": 1}
    assert report["tls_logic_count"] == 1
    assert report["top_level_connection_count"] == 1

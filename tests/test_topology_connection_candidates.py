from pathlib import Path

from torii_sumo.core.topology_audit import audit_topology_fragmentation


def test_topology_audit_flags_compact_connection_cell(tmp_path: Path) -> None:
    net_file = tmp_path / "cell.net.xml"
    net_file.write_text(
        """<net>
  <edge id="west_in" from="w" to="a" type="highway.primary"><lane id="west_in_0" index="0" allow="passenger" length="20" shape="-20,0 0,0"/></edge>
  <edge id="east_out" from="b" to="e" type="highway.primary"><lane id="east_out_0" index="0" allow="passenger" length="20" shape="6,0 26,0"/></edge>
  <edge id="north_in" from="n" to="c" type="highway.secondary"><lane id="north_in_0" index="0" allow="passenger" length="20" shape="3,20 3,4"/></edge>
  <edge id="south_out" from="a" to="s" type="highway.secondary"><lane id="south_out_0" index="0" allow="passenger" length="20" shape="0,0 0,-20"/></edge>
  <edge id="ab" from="a" to="b" type="highway.primary"><lane id="ab_0" index="0" allow="passenger" length="6" shape="0,0 6,0"/></edge>
  <edge id="bc" from="b" to="c" type="highway.secondary"><lane id="bc_0" index="0" allow="passenger" length="5" shape="6,0 3,4"/></edge>
  <junction id="w" x="-20" y="0" type="priority"/>
  <junction id="a" x="0" y="0" type="traffic_light"/>
  <junction id="b" x="6" y="0" type="priority"/>
  <junction id="c" x="3" y="4" type="priority"/>
  <junction id="e" x="26" y="0" type="priority"/>
  <junction id="n" x="3" y="20" type="priority"/>
  <junction id="s" x="0" y="-20" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = audit_topology_fragmentation(
        net_file=net_file,
        output_dir=tmp_path / "audit",
        cluster_radius_m=8,
        min_cluster_nodes=3,
    )

    assert report["topology_connection_cell_candidate_count"] == 1
    cell = report["topology_connection_cell_candidates"][0]
    assert set(cell["node_ids"]) == {"a", "b", "c"}
    assert cell["external_vehicle_approach_count"] == 4
    assert cell["connection_cell_decision"] == "needs_review"


def test_topology_audit_rejects_long_connector_between_close_intersections(tmp_path: Path) -> None:
    net_file = tmp_path / "pair.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a_in" from="a0" to="a" type="highway.primary"><lane id="a_in_0" index="0" allow="passenger" length="20" shape="-20,0 0,0"/></edge>
  <edge id="a_to_b" from="a" to="b" type="highway.primary"><lane id="a_to_b_0" index="0" allow="passenger" length="45" shape="0,0 45,0"/></edge>
  <edge id="b_out" from="b" to="b1" type="highway.primary"><lane id="b_out_0" index="0" allow="passenger" length="20" shape="45,0 65,0"/></edge>
  <junction id="a0" x="-20" y="0" type="priority"/>
  <junction id="a" x="0" y="0" type="traffic_light"/>
  <junction id="b" x="45" y="0" type="traffic_light"/>
  <junction id="b1" x="65" y="0" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = audit_topology_fragmentation(
        net_file=net_file,
        output_dir=tmp_path / "audit",
        cluster_radius_m=50,
        min_cluster_nodes=2,
    )

    assert report["topology_connection_cell_candidate_count"] == 0

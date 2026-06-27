from pathlib import Path

from torii_sumo.core.reference_join_audit import audit_reference_join_patterns


def test_reference_join_audit_matches_tum_cluster_to_torii_fragment(tmp_path: Path) -> None:
    reference_net = tmp_path / "tum_reference.net.xml"
    reference_net.write_text(
        """<net>
  <edge id="west" from="w" to="cluster_a_b">
    <lane id="west_0" index="0" length="30" shape="-30,0 0,0"/>
  </edge>
  <edge id="east" from="cluster_a_b" to="e">
    <lane id="east_0" index="0" length="30" shape="0,0 30,0"/>
  </edge>
  <junction id="w" x="-30" y="0" type="priority"/>
  <junction id="e" x="30" y="0" type="priority"/>
  <junction id="cluster_a_b" x="0" y="0" type="traffic_light" incLanes="west_0" intLanes=":cluster_a_b_0_0 :cluster_a_b_1_0" shape="-4,-4 4,-4 4,4 -4,4"/>
</net>
""",
        encoding="utf-8",
    )
    torii_net = tmp_path / "torii_fragmented.net.xml"
    torii_net.write_text(
        """<net>
  <edge id="internal_ab" from="a" to="b">
    <lane id="internal_ab_0" index="0" length="7" shape="-3,0 4,0"/>
  </edge>
  <edge id="internal_bc" from="b" to="c">
    <lane id="internal_bc_0" index="0" length="6" shape="4,0 8,2"/>
  </edge>
  <edge id="west_in" from="w" to="a">
    <lane id="west_in_0" index="0" length="30" shape="-30,0 -3,0"/>
  </edge>
  <edge id="east_out" from="c" to="e">
    <lane id="east_out_0" index="0" length="30" shape="8,2 30,0"/>
  </edge>
  <junction id="w" x="-30" y="0" type="priority"/>
  <junction id="e" x="30" y="0" type="priority"/>
  <junction id="a" x="-3" y="0" type="traffic_light"/>
  <junction id="b" x="4" y="0" type="traffic_light"/>
  <junction id="c" x="8" y="2" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = audit_reference_join_patterns(
        reference_net_file=reference_net,
        candidate_net_file=torii_net,
        output_dir=tmp_path / "audit",
        prefix="case",
        reference_cluster_prefix="cluster_",
        candidate_cluster_radius_m=20,
        match_radius_m=20,
    )

    assert report["status"] == "pass"
    assert report["reference_case_count"] == 1
    assert report["matched_case_count"] == 1
    case = report["matched_cases"][0]
    assert case["reference_joined_source_node_count"] == 2
    assert case["reference_type"] == "traffic_light"
    assert case["matched_reference_source_node_count"] == 2
    assert case["reference_source_node_match_ratio"] == 1.0
    assert case["matched_reference_source_internal_edge_count"] == 1
    assert case["matched_reference_source_internal_edge_ids"] == ["internal_ab"]
    assert case["matched_candidate_node_count"] == 3
    assert case["matched_candidate_internal_edge_count"] == 2
    assert case["matched_candidate_internal_edge_ids"] == ["internal_ab", "internal_bc"]
    assert case["learned_rule_basis"] == "reference_source_nodes"
    assert case["learned_rule"] == "tum_like_join_candidate"
    assert report["pattern_stats"]["reference_joined_source_node_counts"] == {"2": 1}
    assert report["pattern_stats"]["reference_approach_edge_counts"] == {"1": 1}
    assert report["pattern_stats"]["matched_reference_source_node_counts"] == {"2": 1}
    assert report["pattern_stats"]["matched_reference_source_internal_edge_counts"] == {"1": 1}
    assert report["pattern_stats"]["matched_candidate_node_counts"] == {"3": 1}
    assert report["pattern_stats"]["matched_candidate_internal_edge_counts"] == {"2": 1}
    assert report["pattern_stats"]["learned_rule_basis_counts"] == {"reference_source_nodes": 1}
    assert Path(report["cases_file"]).is_file()
    assert Path(report["summary_file"]).is_file()
    assert "matched_candidate_internal_edge_count" in Path(report["cases_file"]).read_text(encoding="utf-8").splitlines()[0]


def test_reference_join_audit_reports_reusable_junction_patterns(tmp_path: Path) -> None:
    reference = tmp_path / "reference.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    reference.write_text(
        """<net>
  <edge id="west_in" from="w" to="cluster_a_b"><lane id="west_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="south_in" from="s" to="cluster_a_b"><lane id="south_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="north_in" from="n" to="cluster_a_b"><lane id="north_in_0" index="0" allow="passenger" shape="0,10 0,0"/></edge>
  <edge id="east_out" from="cluster_a_b" to="e"><lane id="east_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="south_out" from="cluster_a_b" to="so"><lane id="south_out_0" index="0" allow="passenger" shape="0,0 0,-10"/></edge>
  <edge id="north_out" from="cluster_a_b" to="no"><lane id="north_out_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <junction id="cluster_a_b" type="right_before_left" x="0" y="0" incLanes="west_in_0 south_in_0 north_in_0" intLanes="">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <connection from="west_in" to="east_out" fromLane="0" toLane="0" dir="s"/>
  <connection from="south_in" to="south_out" fromLane="0" toLane="0" dir="s"/>
  <connection from="north_in" to="north_out" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )
    candidate.write_text(
        """<net>
  <edge id="internal_ab" from="a" to="b"><lane id="internal_ab_0" index="0" length="7" shape="-3,0 4,0"/></edge>
  <edge id="internal_bc" from="b" to="c"><lane id="internal_bc_0" index="0" length="6" shape="4,0 8,2"/></edge>
  <junction id="a" x="-3" y="0" type="traffic_light"/>
  <junction id="b" x="4" y="0" type="traffic_light"/>
  <junction id="c" x="8" y="2" type="priority"/>
</net>""",
        encoding="utf-8",
    )

    report = audit_reference_join_patterns(
        reference_net_file=reference,
        candidate_net_file=candidate,
        output_dir=tmp_path / "audit",
        reference_cluster_prefix="cluster_",
        candidate_cluster_radius_m=20,
        match_radius_m=20,
    )

    assert report["junction_pattern_index"][0]["junction_id"] == "cluster_a_b"
    assert report["junction_pattern_index"][0]["control_type"] == "right_before_left"
    assert report["junction_pattern_index"][0]["arm_count"] == 3


def test_reference_join_audit_keeps_audit_when_pattern_extraction_fails(tmp_path: Path) -> None:
    reference = tmp_path / "reference.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    reference.write_text(
        """<net>
  <edge id="west_in" from="w" to="cluster_a_b"><lane id="west_in_0" index="0" allow="passenger" shape="bad,0 0,0"/></edge>
  <edge id="east_out" from="cluster_a_b" to="e"><lane id="east_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="west_in_0" intLanes=""/>
  <connection from="west_in" to="east_out" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )
    candidate.write_text(
        """<net>
  <edge id="internal_ab" from="a" to="b"><lane id="internal_ab_0" index="0" length="7" shape="-3,0 4,0"/></edge>
  <junction id="a" x="-3" y="0" type="traffic_light"/>
  <junction id="b" x="4" y="0" type="traffic_light"/>
</net>""",
        encoding="utf-8",
    )

    report = audit_reference_join_patterns(
        reference_net_file=reference,
        candidate_net_file=candidate,
        output_dir=tmp_path / "audit",
        reference_cluster_prefix="cluster_",
        candidate_cluster_radius_m=20,
        candidate_min_cluster_nodes=2,
        match_radius_m=20,
    )

    assert report["status"] == "pass"
    assert report["junction_pattern_index"] == []
    assert any("junction pattern extraction failed" in warning for warning in report["warnings"])

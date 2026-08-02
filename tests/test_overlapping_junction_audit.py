from pathlib import Path

import torii_sumo.core.overlapping_junction_audit as overlapping_audit
from torii_sumo.core.overlapping_junction_audit import audit_overlapping_junctions
from torii_sumo.core.surface_overlap_audit import audit_sumo_lane_junction_surface_overlaps


def test_overlap_groups_only_compare_nearby_grid_cells(monkeypatch) -> None:
    junctions = {
        str(index): {"id": str(index), "type": "priority", "x": index * 100.0, "y": 0.0}
        for index in range(1_000)
    }
    calls = 0
    real_distance = overlapping_audit._distance

    def counted_distance(left, right):
        nonlocal calls
        calls += 1
        return real_distance(left, right)

    monkeypatch.setattr(overlapping_audit, "_distance", counted_distance)

    assert overlapping_audit._overlap_groups(junctions, [], 12.0, 20.0, 2) == []
    assert calls < 10


def test_overlapping_junction_audit_flags_close_top_level_junctions(tmp_path: Path) -> None:
    net_file = tmp_path / "overlap.net.xml"
    net_file.write_text(
        """<net>
  <edge id="main_a" from="a" to="b" type="highway.unclassified">
    <lane id="main_a_0" index="0" length="5" shape="0,0 5,0"/>
  </edge>
  <edge id="main_b" from="b" to="c" type="highway.unclassified">
    <lane id="main_b_0" index="0" length="6" shape="5,0 11,0"/>
  </edge>
  <edge id="foot" from="b" to="p" type="highway.footway">
    <lane id="foot_0" index="0" length="4" allow="pedestrian" shape="5,0 5,4"/>
  </edge>
  <junction id="a" x="0" y="0" type="priority"/>
  <junction id="b" x="5" y="0" type="traffic_light"/>
  <junction id="c" x="11" y="0" type="priority"/>
  <junction id="p" x="5" y="4" type="priority"/>
  <junction id="far" x="80" y="80" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = audit_overlapping_junctions(
        net_file=net_file,
        output_dir=tmp_path / "audit",
        prefix="demo",
        overlap_radius_m=12,
        short_edge_length_m=15,
        min_group_nodes=3,
    )

    assert report["status"] == "pass"
    assert report["overlapping_junction_group_count"] == 1
    group = report["overlapping_junction_groups"][0]
    assert set(group["node_ids"]) == {"a", "b", "c", "p"}
    assert group["recommendation"] == "same_physical_intersection_review"
    assert group["has_vehicle_edges"] is True
    assert group["has_pedestrian_or_bike_edges"] is True
    assert group["direct_edge_ids"] == ["foot", "main_a", "main_b"]
    assert Path(report["groups_file"]).is_file()
    assert Path(report["summary_file"]).is_file()


def test_overlapping_junction_audit_ignores_internal_crossing_layers(tmp_path: Path) -> None:
    net_file = tmp_path / "single_joined.net.xml"
    net_file.write_text(
        """<net>
  <edge id=":joined_0" function="internal">
    <lane id=":joined_0_0" index="0" length="5" shape="0,0 5,0"/>
  </edge>
  <edge id=":joined_c0" function="crossing">
    <lane id=":joined_c0_0" index="0" length="4" allow="pedestrian" shape="0,1 5,1"/>
  </edge>
  <edge id=":joined_w0" function="walkingarea">
    <lane id=":joined_w0_0" index="0" length="4" allow="pedestrian" shape="0,2 5,2"/>
  </edge>
  <junction id="joined" x="0" y="0" type="traffic_light"/>
  <junction id=":joined_0_0" x="1" y="1" type="internal"/>
</net>
""",
        encoding="utf-8",
    )

    report = audit_overlapping_junctions(
        net_file=net_file,
        output_dir=tmp_path / "audit",
        prefix="joined",
    )

    assert report["status"] == "pass"
    assert report["top_level_junction_count"] == 1
    assert report["overlapping_junction_group_count"] == 0
    assert report["ignored_internal_layer_count"] == 3


def test_overlapping_junction_audit_does_not_chain_whole_corridors(tmp_path: Path) -> None:
    net_file = tmp_path / "chain.net.xml"
    net_file.write_text(
        """<net>
  <edge id="ab" from="a" to="b"><lane id="ab_0" index="0" length="10" shape="0,0 10,0"/></edge>
  <edge id="bc" from="b" to="c"><lane id="bc_0" index="0" length="10" shape="10,0 20,0"/></edge>
  <edge id="cd" from="c" to="d"><lane id="cd_0" index="0" length="10" shape="20,0 30,0"/></edge>
  <edge id="de" from="d" to="e"><lane id="de_0" index="0" length="10" shape="30,0 40,0"/></edge>
  <junction id="a" x="0" y="0" type="priority"/>
  <junction id="b" x="10" y="0" type="priority"/>
  <junction id="c" x="20" y="0" type="traffic_light"/>
  <junction id="d" x="30" y="0" type="priority"/>
  <junction id="e" x="40" y="0" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = audit_overlapping_junctions(
        net_file=net_file,
        output_dir=tmp_path / "audit",
        prefix="chain",
        overlap_radius_m=12,
        short_edge_length_m=12,
        min_group_nodes=2,
    )

    assert report["overlapping_junction_group_count"] > 0
    assert all(group["max_pair_distance_m"] <= 24 for group in report["overlapping_junction_groups"])
    assert all(set(group["node_ids"]) != {"a", "b", "c", "d", "e"} for group in report["overlapping_junction_groups"])


def test_overlapping_junction_audit_marks_reference_join_supported_group(tmp_path: Path) -> None:
    net_file = tmp_path / "torii.net.xml"
    net_file.write_text(
        """<net>
  <edge id="ab" from="a" to="b" type="highway.unclassified">
    <lane id="ab_0" index="0" length="5" shape="0,0 5,0"/>
  </edge>
  <edge id="bc" from="b" to="c" type="highway.unclassified">
    <lane id="bc_0" index="0" length="6" shape="5,0 11,0"/>
  </edge>
  <junction id="a" x="0" y="0" type="priority"/>
  <junction id="b" x="5" y="0" type="traffic_light"/>
  <junction id="c" x="11" y="0" type="priority"/>
</net>
""",
        encoding="utf-8",
    )
    reference_join_report = {
        "matched_cases": [
            {
                "reference_id": "cluster_a_b_c",
                "matched_candidate_node_ids": ["a", "b", "c"],
                "learned_rule": "tum_like_join_candidate",
            }
        ]
    }

    report = audit_overlapping_junctions(
        net_file=net_file,
        output_dir=tmp_path / "audit",
        prefix="reference",
        overlap_radius_m=12,
        reference_join_audit_report=reference_join_report,
    )

    group = report["overlapping_junction_groups"][0]
    assert group["reference_join_status"] == "reference_join_supported"
    assert group["reference_join_ids"] == ["cluster_a_b_c"]
    assert group["recommendation"] == "reference_join_supported"


def test_overlapping_junction_audit_skips_plain_vehicle_pairs_without_review_signal(tmp_path: Path) -> None:
    net_file = tmp_path / "plain_pairs.net.xml"
    net_file.write_text(
        """<net>
  <edge id="ab" from="a" to="b" type="highway.residential">
    <lane id="ab_0" index="0" length="5" shape="0,0 5,0"/>
  </edge>
  <junction id="a" x="0" y="0" type="priority"/>
  <junction id="b" x="5" y="0" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = audit_overlapping_junctions(
        net_file=net_file,
        output_dir=tmp_path / "audit",
        prefix="plain",
        overlap_radius_m=12,
    )

    assert report["overlapping_junction_group_count"] == 0


def test_compound_core_requires_micro_edge_exact_overlap_and_explicit_authority(
    tmp_path: Path,
) -> None:
    net_file = tmp_path / "compound.net.xml"
    net_file.write_text(
        """<net>
  <edge id="micro" from="a" to="b"><lane id="micro_0" length="0.2" shape="0,0 0.2,0"/></edge>
  <edge id="in_w" from="w" to="a"><lane id="in_w_0" length="20" shape="-20,0 0,0"/></edge>
  <edge id="out_e" from="b" to="e"><lane id="out_e_0" length="20" shape="0.2,0 20,0"/></edge>
  <edge id="in_n" from="n" to="a"><lane id="in_n_0" length="20" shape="0,20 0,0"/></edge>
  <edge id="out_s" from="b" to="s"><lane id="out_s_0" length="20" shape="0.2,0 0,-20"/></edge>
  <junction id="a" x="0" y="0" type="traffic_light" shape="-1,-1 1,-1 1,1 -1,1"/>
  <junction id="b" x="0.2" y="0" type="traffic_light" shape="-0.8,-1 1.2,-1 1.2,1 -0.8,1"/>
  <junction id="w" x="-20" y="0" type="priority"/>
  <junction id="e" x="20" y="0" type="priority"/>
  <junction id="n" x="0" y="20" type="priority"/>
  <junction id="s" x="0" y="-20" type="priority"/>
</net>""",
        encoding="utf-8",
    )
    topology = {
        "suspicious_clusters": [
            {
                "cluster_id": "C001",
                "node_count": 6,
                "traffic_light_node_count": 2,
                "approach_count": 4,
                "physical_intersection_shape": "cross",
            }
        ]
    }
    reference = {
        "all_cases": [
            {
                "reference_id": "cluster_a_b",
                "match_status": "matched",
                "matched_candidate_cluster_id": "C001",
                "matched_reference_source_junction_ids": ["a", "b"],
                "reference_joined_source_node_count": 2,
                "reference_source_identity_complete": True,
                "matched_reference_source_internal_edge_count": 1,
                "matched_reference_source_boundary_edge_count": 4,
            }
        ]
    }
    surface = audit_sumo_lane_junction_surface_overlaps(net_file)

    report = audit_overlapping_junctions(
        net_file=net_file,
        output_dir=tmp_path / "audit",
        topology_audit_report=topology,
        surface_overlap_audit_report=surface,
        reference_join_audit_report=reference,
        reference_is_authority=True,
        authorized_reference_ids={"cluster_a_b"},
    )

    assert report["compound_core_candidate_count"] == 1
    candidate = report["compound_core_candidates"][0]
    assert candidate["micro_exact_overlap_edge_ids"] == ["micro"]
    assert candidate["target_evidence_status"] == "pass"
    assert candidate["transfer_gate_status"] == "pass"
    assert candidate["reference_join_node_ids"] == ["a", "b"]

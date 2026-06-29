from pathlib import Path
import xml.etree.ElementTree as ET

from torii_sumo.core.network_permissions import apply_service_passenger_permissions
from torii_sumo.core.network_plan import derive_network_plan
from torii_sumo.core.osm_workflow import (
    _low_vehicle_control_candidate_limits,
    _reference_delta_promotion_decision,
    _teacher_guided_application_stats,
    _teacher_guided_best_variant_file,
    _tls_connection_repair_promotion_decision,
    export_plain_net_for_teacher_guided_repair,
    run_osm_cleanup_workflow,
)
from torii_sumo.core.reference_bbox import derive_reference_net_bbox


def _write_reference_net(path: Path) -> None:
    path.write_text(
        """<net>
    <edge id="primary_a" type="highway.primary">
        <lane id="primary_a_0" index="0" allow="passenger bus" speed="13.9" length="25.0"/>
    </edge>
    <edge id="residential_a" type="highway.residential">
        <lane id="residential_a_0" index="0" speed="13.9" length="25.0"/>
    </edge>
    <edge id="service_a" type="highway.service">
        <lane id="service_a_0" index="0" allow="delivery passenger pedestrian" speed="5.0" length="25.0"/>
    </edge>
    <edge id="service_b" type="highway.service">
        <lane id="service_b_0" index="0" allow="delivery passenger" speed="5.0" length="25.0"/>
    </edge>
    <edge id="cycle_a" type="highway.cycleway">
        <lane id="cycle_a_0" index="0" allow="bicycle" speed="5.0" length="25.0"/>
    </edge>
    <edge id="foot_a" type="highway.footway">
        <lane id="foot_a_0" index="0" allow="pedestrian" speed="5.0" length="25.0"/>
    </edge>
    <edge id="path_rare" type="highway.path">
        <lane id="path_rare_0" index="0" allow="passenger pedestrian" speed="5.0" length="25.0"/>
    </edge>
</net>""",
        encoding="utf-8",
    )


def test_teacher_guided_application_stats_reports_single_variant_scope(tmp_path: Path) -> None:
    best_net = tmp_path / "candidate_001_teacher_guided.net.xml"
    best_net.write_text("<net/>", encoding="utf-8")

    stats = _teacher_guided_application_stats(
        {
            "status": "pass",
            "parity_gate_status": "pass",
            "pass_candidate_count": 3,
        },
        best_net,
    )

    assert stats == {
        "teacher_guided_repair_application_scope": "single_best_variant",
        "teacher_guided_repair_applied_candidate_count": 1,
        "teacher_guided_repair_unapplied_pass_candidate_count": 2,
    }


def test_teacher_guided_application_stats_reports_sequential_composite_scope(tmp_path: Path) -> None:
    composite_net = tmp_path / "composite_teacher_guided.net.xml"
    composite_net.write_text("<net/>", encoding="utf-8")

    stats = _teacher_guided_application_stats(
        {
            "status": "pass",
            "parity_gate_status": "pass",
            "pass_candidate_count": 5,
            "composite_applied_candidate_count": 3,
            "composite_net_file": str(composite_net),
        },
        composite_net,
    )

    assert stats == {
        "teacher_guided_repair_application_scope": "sequential_composite",
        "teacher_guided_repair_applied_candidate_count": 3,
        "teacher_guided_repair_unapplied_pass_candidate_count": 2,
    }


def test_teacher_guided_best_variant_file_prefers_composite_net(tmp_path: Path) -> None:
    first_variant = tmp_path / "candidate_001_teacher_guided.net.xml"
    composite_net = tmp_path / "candidate_002_teacher_guided.net.xml"
    first_variant.write_text("<net/>", encoding="utf-8")
    composite_net.write_text("<net/>", encoding="utf-8")

    best = _teacher_guided_best_variant_file(
        {
            "status": "pass",
            "parity_gate_status": "pass",
            "composite_net_file": str(composite_net),
            "variant_reports": [
                {
                    "status": "pass",
                    "parity_gate_status": "pass",
                    "final_net_file": str(first_variant),
                }
            ],
        }
    )

    assert best == composite_net


def test_teacher_guided_best_variant_file_uses_partial_sequential_composite(tmp_path: Path) -> None:
    composite_net = tmp_path / "partial_composite_teacher_guided.net.xml"
    composite_net.write_text("<net/>", encoding="utf-8")

    best = _teacher_guided_best_variant_file(
        {
            "status": "fail",
            "parity_gate_status": "fail",
            "pass_candidate_count": 33,
            "parity_pass_candidate_count": 26,
            "composite_applied_candidate_count": 26,
            "composite_net_file": str(composite_net),
        }
    )

    assert best == composite_net


def test_reference_matched_workflow_uses_teacher_guided_composite_for_review(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-composite_filtered.osm.xml.gz"
    composite_net = tmp_path / "teacher_guided_composite.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_reference_join_audit(**kwargs):
        calls.setdefault("reference_join_candidate_net_files", []).append(kwargs["candidate_net_file"])
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "full",
            "reference_case_count": 1,
            "matched_case_count": 1,
            "unmatched_case_count": 0,
            "junction_pattern_index": [{"junction_id": "cluster_a_b"}],
            "summary_file": str(tmp_path / "reference_join_audit.json"),
            "warnings": [],
        }

    def fake_teacher_guided_queue(**kwargs):
        calls["teacher_guided_candidate_net_file"] = kwargs["candidate_net_file"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "repair_candidate_count": 4,
            "ready_candidate_count": 0,
            "expanded_scope_candidate_count": 4,
            "queue_file": str(tmp_path / "teacher_guided_queue.json"),
            "warnings": [],
        }

    def fake_teacher_guided_plain_export(**kwargs):
        calls["teacher_guided_plain_net_file"] = kwargs["net_file"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "raw_node_file": str(tmp_path / "plain.nod.xml"),
            "raw_edge_file": str(tmp_path / "plain.edg.xml"),
            "raw_connection_file": str(tmp_path / "plain.con.xml"),
            "warnings": [],
        }

    def fake_teacher_guided_run(**kwargs):
        calls["teacher_guided_run_sequential_accept_passed_variants"] = kwargs["sequential_accept_passed_variants"]
        composite_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "parity_gate_status": "pass",
            "attempted_candidate_count": 4,
            "pass_candidate_count": 4,
            "composite_applied_candidate_count": 4,
            "composite_net_file": str(composite_net),
            "run_report_file": str(tmp_path / "teacher_guided_run.json"),
            "warnings": [],
        }

    def fake_review_html(**kwargs):
        calls["workflow_review_net_file"] = kwargs["net_file"]
        return {
            "status": "pass",
            "workflow_review_html_status": "pass",
            "workflow_review_html_file": str(tmp_path / "review.html"),
            "workflow_review_net_file": str(kwargs["net_file"]),
            "workflow_report_file": str(tmp_path / "workflow_report.json"),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-composite",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        run_tls_aggregation_after_build=False,
        run_routeability_audit_after_build=False,
        run_reference_join_aggregation_after_build=False,
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {"status": "pass", "tls_candidate_count": 0, "warnings": []},
        connectivity_func=lambda _path: {"status": "pass", "connectivity_status": "pass", "passenger_edge_count": 1},
        topology_audit_func=lambda **_kwargs: {"status": "pass", "topology_fragmentation_status": "pass", "warnings": []},
        netedit_func=lambda _path: {"status": "blocked", "netedit_status": "skipped", "warnings": []},
        sumo_gui_func=lambda _path, **_kwargs: {"status": "blocked", "sumo_gui_status": "skipped", "warnings": []},
        reference_join_audit_func=fake_reference_join_audit,
        teacher_guided_repair_queue_func=fake_teacher_guided_queue,
        teacher_guided_plain_export_func=fake_teacher_guided_plain_export,
        teacher_guided_repair_run_func=fake_teacher_guided_run,
        review_html_func=fake_review_html,
    )

    assert calls["teacher_guided_run_sequential_accept_passed_variants"] is True
    assert calls["workflow_review_net_file"] == composite_net
    assert report["reference_visual_detail_comparison_net_file"] == str(composite_net)
    assert report["teacher_guided_repair_best_variant_file"] == str(composite_net)
    assert report["teacher_guided_repair_application_scope"] == "sequential_composite"
    assert report["teacher_guided_repair_applied_candidate_count"] == 4
    assert report["teacher_guided_repair_unapplied_pass_candidate_count"] == 0
    assert calls["reference_join_candidate_net_files"][-1] == composite_net


def test_tls_connection_repair_promotion_blocks_reference_delta_regression(tmp_path: Path) -> None:
    variant_file = tmp_path / "repaired.net.xml"
    variant_file.write_text("<net/>", encoding="utf-8")

    decision = _tls_connection_repair_promotion_decision(
        repair_report={
            "status": "pass",
            "variant_file": str(variant_file),
            "skipped_invalid_mapped_linkindex_connection_count": 0,
        },
        sumo_load_report={"status": "pass"},
        rejected_delta_report={
            "network_structural_missing_counts": {"tls_controlled_connection_count": 10},
            "network_structural_extra_counts": {},
        },
        repair_delta_report={
            "status": "pass",
            "network_structural_missing_counts": {"tls_controlled_connection_count": 20},
            "network_structural_extra_counts": {},
        },
    )

    assert decision["status"] == "blocked"
    assert decision["reason"] == "reference_tls_semantic_delta_regressed"


def test_tls_connection_repair_promotion_blocks_incompatible_tllogic_warning(tmp_path: Path) -> None:
    variant_file = tmp_path / "repaired.net.xml"
    variant_file.write_text("<net/>", encoding="utf-8")

    decision = _tls_connection_repair_promotion_decision(
        repair_report={
            "status": "pass",
            "variant_file": str(variant_file),
            "skipped_invalid_mapped_linkindex_connection_count": 0,
        },
        sumo_load_report={
            "status": "pass",
            "stderr": (
                "Warning: Program '0' at tlLogic 'joinedS_10176312934_7881057697' "
                "is incompatible with logic at junction '7881057697'."
            ),
        },
        rejected_delta_report={
            "network_structural_missing_counts": {"tls_controlled_connection_count": 10},
            "network_structural_extra_counts": {},
        },
        repair_delta_report={
            "status": "pass",
            "network_structural_missing_counts": {},
            "network_structural_extra_counts": {},
        },
    )

    assert decision["status"] == "blocked"
    assert decision["reason"] == "sumo_load_tls_incompatible"


def test_reference_delta_promotion_prefers_candidate_with_lower_tls_semantic_score() -> None:
    decision = _reference_delta_promotion_decision(
        candidate_delta_report={
            "status": "pass",
            "network_structural_missing_counts": {"tls_controlled_connection_count": 165},
            "network_structural_extra_counts": {"traffic_light_junction_count": 46},
        },
        baseline_delta_report={
            "status": "pass",
            "network_structural_missing_counts": {"tls_shared_linkindex_group_count": 40},
            "network_structural_extra_counts": {"traffic_light_junction_count": 354},
        },
        reason="tls_aggregation_promoted_by_reference_delta",
    )

    assert decision["status"] == "pass"
    assert decision["reason"] == "tls_aggregation_promoted_by_reference_delta"
    assert decision["candidate_tls_semantic_delta_score"] == 211
    assert decision["baseline_tls_semantic_delta_score"] == 394


def test_low_vehicle_control_candidate_limits_include_tls_count_fallback() -> None:
    limits = _low_vehicle_control_candidate_limits(
        {
            "network_structural_extra_counts": {
                "tl_logic_count": 41,
                "traffic_light_junction_count": 46,
            },
            "tls_control_review_queue": [
                {
                    "review_type": "downgrade_low_vehicle_approach_tls",
                    "tl_id": str(index),
                }
                for index in range(60)
            ],
        }
    )

    assert limits == [
        {
            "label": "tls10",
            "max_removed_controlled_connections": None,
            "max_selected_tllogic_count": 10,
        },
        {
            "label": "tls20",
            "max_removed_controlled_connections": None,
            "max_selected_tllogic_count": 20,
        },
    ]


def test_network_plan_blocks_when_layers_and_reference_are_missing() -> None:
    plan = derive_network_plan()

    assert plan["status"] == "blocked"
    assert plan["network_plan_status"] == "needs_user_confirmation"
    assert plan["missing_blockers"] == ["network_plan"]
    assert "traffic layers" in plan["next_question"]
    assert "reference_matched" in plan["network_detail_options"]


def test_network_plan_blocks_named_reference_without_reference_artifact() -> None:
    plan = derive_network_plan(
        user_request="Generate a city-center SUMO network matching a manually cleaned reference network",
    )

    assert plan["status"] == "blocked"
    assert plan["network_plan_status"] == "needs_reference_artifact"
    assert plan["network_detail_target"] == "reference_matched"
    assert plan["reference_target"] == "manually cleaned reference network"
    assert plan["missing_blockers"] == ["reference_network_or_policy"]
    assert "reference SUMO .net.xml" in plan["next_question"]


def test_network_plan_derives_reference_policy_from_reference_net(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "manual-reference.net.xml"
    _write_reference_net(reference_net_file)

    plan = derive_network_plan(
        user_request="Generate an OSM network that matches a manually cleaned reference network",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
    )

    assert plan["status"] == "pass"
    assert plan["network_plan_status"] == "inferred_from_reference_policy"
    assert plan["network_profile"] == "reference_matched"
    assert plan["reference_net_file"] == str(reference_net_file)
    assert plan["network_detail_target"] == "reference_matched"
    assert plan["primary_network_layer"] == "passenger_vehicle"
    assert plan["default_routeability_layer"] == "vehicle_core"
    assert plan["default_netedit_comparison_layer"] == "reference_visual_detail"
    assert plan["vehicle_core_highway_classes"] == plan["highway_classes"]
    assert "service" not in plan["highway_classes"]
    assert "service" in plan["reference_visual_detail_highway_classes"]
    assert "service" in plan["reference_visual_detail_only_highway_classes"]
    assert "primary" in plan["highway_classes"]
    assert "residential" in plan["highway_classes"]
    assert "cycleway" not in plan["highway_classes"]
    assert "footway" not in plan["highway_classes"]
    assert "path" not in plan["highway_classes"]
    assert {"cycleway", "footway", "path"} <= set(plan["reference_visual_detail_highway_classes"])
    assert {"cycleway", "footway", "path"} <= set(plan["reference_visual_detail_only_highway_classes"])
    assert {"passenger", "bicycle", "pedestrian", "bus"} <= set(plan["movement_layers"])
    assert set(plan["auxiliary_modal_layers"]) == {"bicycle", "pedestrian", "bus"}
    assert plan["reference_policy"]["reference_policy_status"] == "analyzed"
    assert plan["reference_policy"]["passenger_edge_type_counts"]["highway.service"] == 2
    assert plan["reference_policy"]["visual_detail_edge_type_counts"]["highway.footway"] == 1
    assert plan["service_passenger_policy"] == "reference_match"
    assert "routeability_audit" in plan["validation_gates"]
    assert "scope_matched_reference_comparison" in plan["validation_gates"]
    assert "reference_join_audit" in plan["validation_gates"]
    assert "junction_pattern_index" in plan["validation_gates"]
    assert "connection_semantics_parity" in plan["validation_gates"]
    assert "tls_semantics_parity" in plan["validation_gates"]
    assert "internal_junction_parity" in plan["validation_gates"]
    assert "netedit_connection_mode_review" in plan["validation_gates"]
    assert "teacher_guided_junction_parity" in plan["validation_gates"]


def test_reference_matched_plan_keeps_service_out_of_vehicle_core(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "manual-reference.net.xml"
    _write_reference_net(reference_net_file)

    plan = derive_network_plan(
        user_request="Generate an OSM network that mimics a manually cleaned TUM reference network",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
    )

    assert plan["status"] == "pass"
    assert "service" not in plan["highway_classes"]
    assert "service" not in plan["vehicle_core_highway_classes"]
    assert "service" in plan["reference_visual_detail_highway_classes"]
    assert "service" in plan["reference_visual_detail_only_highway_classes"]
    assert plan["service_passenger_policy"] == "reference_match"


def test_reference_bbox_uses_reference_geometry_not_stale_orig_boundary(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "clipped-reference.net.xml"
    reference_net_file.write_text(
        """<net>
    <location netOffset="0.00,0.00" convBoundary="100.00,300.00,200.00,400.00" origBoundary="0.000000,0.000000,99.000000,99.000000"/>
    <junction id="left" type="priority" x="100.00" y="300.00"/>
    <junction id="right" type="priority" x="200.00" y="400.00"/>
    <edge id="e0" from="left" to="right" type="highway.primary">
        <lane id="e0_0" index="0" speed="13.9" length="141.0" shape="100.00,300.00 200.00,400.00"/>
    </edge>
</net>""",
        encoding="utf-8",
    )

    report = derive_reference_net_bbox(
        reference_net_file,
        padding_m=0.0,
        xy_to_latlon_func=lambda x, y: (y / 100.0, x / 100.0),
    )

    assert report["status"] == "pass"
    assert report["reference_bbox_status"] == "derived_from_reference_geometry"
    assert report["reference_bbox"] == "1.0000000,3.0000000,2.0000000,4.0000000"
    assert report["reference_bbox_source"] == "junction_and_lane_geometry"
    assert report["reference_orig_boundary"] == "0.000000,0.000000,99.000000,99.000000"


def test_apply_service_passenger_permissions_adds_passenger_to_service_lanes(tmp_path: Path) -> None:
    net_file = tmp_path / "network.net.xml"
    net_file.write_text(
        """<net>
    <edge id="service_a" type="highway.service">
        <lane id="service_a_0" index="0" allow="bicycle delivery pedestrian" speed="5.0" length="25.0"/>
    </edge>
    <edge id="residential_b" type="highway.residential">
        <lane id="residential_b_0" index="0" allow="passenger" speed="13.9" length="25.0"/>
    </edge>
</net>""",
        encoding="utf-8",
    )

    report = apply_service_passenger_permissions(net_file, policy="allow_vehicle_service")

    root = ET.parse(net_file).getroot()
    service_lane = root.find("./edge[@id='service_a']/lane")
    residential_lane = root.find("./edge[@id='residential_b']/lane")
    assert report["status"] == "pass"
    assert report["service_passenger_permission_status"] == "applied"
    assert report["service_edge_count"] == 1
    assert report["changed_lane_count"] == 1
    assert "passenger" in service_lane.attrib["allow"].split()
    assert residential_lane.attrib["allow"] == "passenger"


def test_export_plain_net_for_teacher_guided_repair_resolves_relative_output_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")
    calls: dict[str, object] = {}

    def fake_command(command, **kwargs):
        calls["command"] = command
        calls["cwd"] = kwargs["cwd"]
        plain_prefix = Path(command[-1])
        for suffix in (".nod.xml", ".edg.xml", ".con.xml"):
            Path(f"{plain_prefix}{suffix}").write_text("<xml/>", encoding="utf-8")
        return {"status": "pass", "returncode": 0}

    report = export_plain_net_for_teacher_guided_repair(
        net_file=Path("candidate.net.xml"),
        output_dir=Path("plain"),
        prefix="demo",
        command_runner=fake_command,
    )

    expected_prefix = tmp_path / "plain" / "demo"
    assert report["status"] == "pass"
    assert calls["command"][-1] == str(expected_prefix)
    assert calls["cwd"] == tmp_path / "plain"
    assert report["raw_node_file"] == str(expected_prefix) + ".nod.xml"


def test_export_plain_net_for_teacher_guided_repair_synthesizes_missing_used_edge_types(
    tmp_path: Path,
) -> None:
    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    def fake_command(command, **_kwargs):
        plain_prefix = Path(command[-1])
        Path(f"{plain_prefix}.nod.xml").write_text("<nodes/>", encoding="utf-8")
        Path(f"{plain_prefix}.con.xml").write_text("<connections/>", encoding="utf-8")
        Path(f"{plain_prefix}.typ.xml").write_text(
            '<types><type id="highway.residential" priority="3" numLanes="1" speed="13.89"/></types>',
            encoding="utf-8",
        )
        Path(f"{plain_prefix}.edg.xml").write_text(
            """<edges>
    <edge id="753083363" from="a" to="b" type="cycleway.lane|highway.unclassified"
          priority="4" numLanes="4" speed="8.33">
        <lane index="0" allow="pedestrian" width="2.00"/>
        <lane index="1" allow="bicycle" width="1.00"/>
    </edge>
</edges>""",
            encoding="utf-8",
        )
        return {"status": "pass", "returncode": 0}

    report = export_plain_net_for_teacher_guided_repair(
        net_file=net_file,
        output_dir=tmp_path / "plain",
        prefix="demo",
        command_runner=fake_command,
    )

    type_root = ET.parse(report["raw_type_file"]).getroot()
    synthesized = type_root.find("./type[@id='cycleway.lane|highway.unclassified']")
    assert report["status"] == "pass"
    assert report["synthesized_edge_type_count"] == 1
    assert report["synthesized_edge_type_ids"] == ["cycleway.lane|highway.unclassified"]
    assert synthesized is not None
    assert synthesized.attrib["priority"] == "4"
    assert synthesized.attrib["numLanes"] == "4"
    assert synthesized.attrib["speed"] == "8.33"


def test_export_plain_net_for_teacher_guided_repair_shortens_long_plain_prefix(
    tmp_path: Path,
) -> None:
    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")
    long_prefix = "sumo_osm_cleanup_post_teacher_tls_connection_repair_movement_rebuild_" + ("x" * 160)

    def fake_command(command, **_kwargs):
        plain_prefix = Path(command[-1])
        assert len(str(plain_prefix.resolve())) + len(".nod.xml") < 240
        for suffix in (".nod.xml", ".edg.xml", ".con.xml"):
            Path(f"{plain_prefix}{suffix}").write_text("<xml/>", encoding="utf-8")
        return {"status": "pass", "returncode": 0}

    report = export_plain_net_for_teacher_guided_repair(
        net_file=net_file,
        output_dir=tmp_path / "plain",
        prefix=long_prefix,
        command_runner=fake_command,
    )

    assert report["status"] == "pass"
    assert report["plain_output_prefix_shortened"] is True
    assert Path(report["plain_output_prefix"]).name.endswith("_" + report["plain_output_prefix_digest"])


def test_osm_cleanup_workflow_uses_reference_net_policy_and_service_policy(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    net_file = tmp_path / "sumo" / "reference-matched.net.xml"
    filtered_osm = tmp_path / "osm" / "reference-matched_filtered.osm.xml.gz"
    build_calls: list[dict[str, object]] = []

    def fake_build(**kwargs):
        build_calls.append(
            {
                "prefix": kwargs["prefix"],
                "allowed_highways": set(kwargs["allowed_highways"]),
                "source_osm_path": kwargs.get("source_osm_path"),
                "netconvert_profile": kwargs.get("netconvert_profile"),
            }
        )
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        if "service" in kwargs["allowed_highways"]:
            net_xml = """<net>
    <edge id="service_a" type="highway.service">
        <lane id="service_a_0" index="0" allow="bicycle delivery pedestrian" speed="5.0" length="25.0"/>
    </edge>
</net>"""
        else:
            net_xml = """<net>
    <edge id="primary_a" type="highway.primary">
        <lane id="primary_a_0" index="0" allow="passenger" speed="13.9" length="25.0"/>
    </edge>
</net>"""
        current_net_file.write_text(net_xml, encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-matched",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        },
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 1,
            "passenger_component_count": 1,
            "largest_component_edge_count": 1,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
    )

    visual_detail_net_file = tmp_path / "sumo" / "reference-matched_reference_visual_detail.net.xml"
    service_lane = ET.parse(net_file).getroot().find("./edge[@id='service_a']/lane")
    visual_service_lane = ET.parse(visual_detail_net_file).getroot().find("./edge[@id='service_a']/lane")
    assert report["status"] == "pass"
    assert report["network_profile"] == "reference_matched"
    assert report["network_plan_status"] == "inferred_from_reference_policy"
    assert report["reference_net_file"] == str(reference_net_file)
    assert report["service_passenger_policy"] == "reference_match"
    assert len(build_calls) == 2
    assert build_calls[0]["prefix"] == "reference-matched"
    assert build_calls[1]["prefix"] == "reference-matched_reference_visual_detail"
    assert build_calls[0]["netconvert_profile"] == "vehicle_core"
    assert build_calls[1]["netconvert_profile"] == "reference_visual_detail"
    assert "service" not in build_calls[0]["allowed_highways"]
    assert "service" in build_calls[1]["allowed_highways"]
    assert "cycleway" not in build_calls[0]["allowed_highways"]
    assert "footway" not in build_calls[0]["allowed_highways"]
    assert "path" not in build_calls[0]["allowed_highways"]
    assert {"cycleway", "footway", "path"} <= build_calls[1]["allowed_highways"]
    assert build_calls[1]["source_osm_path"] == filtered_osm
    assert service_lane is None
    assert "passenger" in visual_service_lane.attrib["allow"].split()
    assert report["service_passenger_permissions"]["changed_lane_count"] == 0
    assert report["reference_visual_detail_service_passenger_permissions"]["changed_lane_count"] == 1
    assert report["reference_visual_detail_status"] == "built"
    assert report["reference_visual_detail_net_file"] == str(visual_detail_net_file)
    assert report["reference_visual_detail_build"]["road_classes"] == sorted(build_calls[1]["allowed_highways"])


def test_reference_matched_workflow_audits_reference_join_on_visual_detail_layer(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-join_filtered.osm.xml.gz"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text(
            """<net>
    <edge id="service_a" type="highway.service">
        <lane id="service_a_0" index="0" allow="passenger" speed="5.0" length="25.0"/>
    </edge>
</net>""",
            encoding="utf-8",
        )
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_reference_join_audit(**kwargs):
        calls["reference_join_candidate_net_file"] = kwargs["candidate_net_file"]
        calls["reference_join_structural_only"] = kwargs["structural_only"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "reference_case_count": 3,
            "matched_case_count": 2,
            "unmatched_case_count": 1,
            "junction_pattern_index": [{"junction_id": "cluster_a_b"}],
            "summary_file": str(tmp_path / "reference_join_audit.json"),
            "cases_file": str(tmp_path / "reference_join_cases.csv"),
            "junction_teacher_delta_file": str(tmp_path / "junction_teacher_delta.json"),
            "junction_pattern_comparisons_file": str(tmp_path / "junction_pattern_comparisons.csv"),
            "junction_pattern_templates_file": str(tmp_path / "junction_pattern_templates.json"),
            "junction_pattern_comparison_status": "fail",
            "junction_pattern_mismatch_count": 2,
            "junction_pattern_mismatch_field_counts": {"internal_function_counts": 2},
            "junction_pattern_comparisons": [
                {"junction_id": "j1", "status": "fail"},
                {"junction_id": "j2", "status": "pass"},
            ],
            "junction_structural_signature_status": "fail",
            "junction_structural_signature_missing_counts": {"tls_pattern_count": 1},
            "reference_structural_signature_summary": {
                "pattern_count": 2,
                "tls_pattern_count": 1,
            },
            "candidate_structural_signature_summary": {
                "pattern_count": 2,
                "tls_pattern_count": 0,
            },
            "network_structural_delta_status": "fail",
            "network_structural_missing_counts": {"crossing_edge_count": 620, "walkingarea_edge_count": 1648},
            "network_structural_extra_counts": {"tl_logic_count": 35, "traffic_light_junction_count": 41},
            "network_structural_junction_type_missing_counts": {"traffic_light": 1},
            "network_structural_junction_type_extra_counts": {"priority": 22},
            "reference_network_structural_summary": {
                "crossing_edge_count": 620,
                "walkingarea_edge_count": 1648,
            },
            "candidate_network_structural_summary": {
                "crossing_edge_count": 0,
                "walkingarea_edge_count": 0,
            },
            "tls_control_review_status": "needs_review",
            "tls_control_review_queue_count": 2,
            "tls_control_review_queue": [
                {"repair_category": "tls_controller_cardinality_repair", "review_type": "split_multi_junction_tls"},
                {"repair_category": "tls_linkindex_phase_repair", "review_type": "restore_shared_linkindex_groups"},
            ],
            "warnings": [],
        }

    def fake_reference_join_aggregation(**kwargs):
        calls["aggregation_candidate_net_file"] = kwargs["net_file"]
        calls["aggregation_audit_report"] = kwargs["reference_join_audit_report"]
        aggregated_net = tmp_path / "aggregated.net.xml"
        aggregated_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "junction_aggregation_status": "variant_created_for_review",
            "junction_aggregation_variant_file": str(aggregated_net),
            "junction_aggregation_plan_file": str(tmp_path / "aggregation_plan.json"),
            "junction_aggregation_candidate_count": 2,
            "junction_aggregation_preservation_status": "review",
            "junction_aggregation_preservation_audit_file": str(tmp_path / "aggregation_preservation.json"),
            "junction_aggregation_removed_normal_edge_count": 5,
            "junction_aggregation_removed_normal_edge_type_counts": {"highway.service": 3, "highway.primary": 2},
            "junction_aggregation_removed_normal_edge_mode_counts": {"passenger": 4, "bicycle": 1},
            "junction_aggregation_lost_shared_connection_count": 2,
            "junction_aggregation_new_dangling_shared_normal_edge_count": 1,
            "warnings": ["junction aggregation variant requires Google Maps review before adoption"],
        }

    def fake_teacher_guided_repair_queue(**kwargs):
        calls["teacher_guided_candidate_net_file"] = kwargs["candidate_net_file"]
        calls["teacher_guided_queue_max_ready_candidates"] = kwargs["max_ready_candidates"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "repair_candidate_count": 1,
            "ready_candidate_count": 0,
            "expanded_scope_candidate_count": 1,
            "queue_file": str(tmp_path / "teacher_guided_queue.json"),
            "queue_csv_file": str(tmp_path / "teacher_guided_queue.csv"),
            "tls_repair_candidate_count": 2,
            "tls_repair_category_counts": {
                "tls_controller_cardinality_repair": 1,
                "tls_linkindex_phase_repair": 1,
            },
            "repair_candidates": [
                {
                    "reference_id": "cluster_a_b",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "vehicle_movement_matrix_missing_count": 12,
                    "missing_teacher_movement_plan_count": 2,
                    "missing_teacher_movement_plan": [
                        {
                            "from_edge_id": "cand_in",
                            "to_edge_id": "cand_out",
                            "fromLane": "0",
                            "toLane": "0",
                            "dir": "s",
                            "tl": "tlsA",
                            "linkIndex": "3",
                        },
                        {
                            "from_edge_id": "cand_in",
                            "to_edge_id": "cand_left",
                            "fromLane": "1",
                            "toLane": "0",
                            "dir": "l",
                            "tl": "tlsA",
                            "linkIndex": "4",
                        },
                    ],
                    "netedit_review_actions": ["rebuild_vehicle_movement_matrix"],
                    "slot_edge_map": {"slot_0": "cand_in", "slot_1": "cand_out"},
                    "movement_exemplar": {
                        "movement_signatures": [
                            {"from_slot": "slot_0", "to_slot": "slot_1"},
                            {"from_slot": "slot_0", "to_slot": "slot_2"},
                        ]
                    },
                }
            ],
            "warnings": [],
        }

    def fake_teacher_guided_plain_export(**kwargs):
        calls["teacher_guided_plain_net_file"] = kwargs["net_file"]
        calls["teacher_guided_plain_netconvert_binary"] = kwargs["netconvert_binary"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "raw_node_file": str(tmp_path / "plain.nod.xml"),
            "raw_edge_file": str(tmp_path / "plain.edg.xml"),
            "raw_connection_file": str(tmp_path / "plain.con.xml"),
            "raw_type_file": str(tmp_path / "plain.typ.xml"),
            "warnings": [],
        }

    def fake_teacher_guided_repair_run(**kwargs):
        calls["teacher_guided_run_queue_report"] = kwargs["queue_report"]
        calls["teacher_guided_run_raw_node_file"] = kwargs["raw_node_file"]
        calls["teacher_guided_run_replay_target_internal_subgraph"] = kwargs["replay_target_internal_subgraph"]
        calls["teacher_guided_run_netconvert_binary"] = kwargs["netconvert_binary"]
        calls["teacher_guided_run_sumo_binary"] = kwargs["sumo_binary"]
        calls["teacher_guided_run_max_ready_candidates"] = kwargs["max_ready_candidates"]
        calls["teacher_guided_run_sequential_accept_passed_variants"] = kwargs["sequential_accept_passed_variants"]
        calls["teacher_guided_run_plain_exporter"] = kwargs["plain_exporter"]
        best_expanded = tmp_path / "expanded_scope.net.xml"
        best_expanded.write_text("<net/>", encoding="utf-8")
        return {
            "status": "blocked",
            "claim_status": "blocked",
            "parity_gate_status": "blocked",
            "attempted_candidate_count": 0,
            "pass_candidate_count": 0,
            "expanded_scope_candidate_count": 1,
            "expanded_scope_pass_candidate_count": 1,
            "best_expanded_scope_net_file": str(best_expanded),
            "semantic_failure_counts": {},
            "approach_integrity_status": "blocked",
            "approach_integrity_failure_counts": {},
            "teacher_pattern_contexts": [
                {
                    "teacher_pattern_key": "three_way|control=right_before_left",
                    "teacher_pattern_family": "three_way",
                    "teacher_pattern_template_count": 127,
                    "teacher_pattern_template_examples": ["cluster_template_1"],
                }
            ],
            "variant_reports": [],
            "run_report_file": str(tmp_path / "teacher_guided_run.json"),
            "warnings": [],
        }

    def fake_review_html(**kwargs):
        calls["workflow_review_net_file"] = kwargs["net_file"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "workflow_review_html_status": "pass",
            "workflow_review_html_file": str(tmp_path / "review.html"),
            "workflow_review_net_file": str(kwargs["net_file"]),
            "workflow_report_file": str(tmp_path / "workflow_report.json"),
            "review_manifest_file": str(tmp_path / "review_manifest.json"),
            "netedit_review_sumocfg_file": str(tmp_path / "review.sumocfg"),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-join",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        },
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 100,
            "passenger_component_count": 1,
            "largest_component_edge_count": 100,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=fake_reference_join_aggregation,
        teacher_guided_repair_queue_func=fake_teacher_guided_repair_queue,
        teacher_guided_plain_export_func=fake_teacher_guided_plain_export,
        teacher_guided_repair_run_func=fake_teacher_guided_repair_run,
        review_html_func=fake_review_html,
    )

    visual_detail_net_file = tmp_path / "sumo" / "reference-join_reference_visual_detail.net.xml"
    assert calls["reference_join_candidate_net_file"] == visual_detail_net_file
    assert calls["reference_join_structural_only"] is True
    assert calls["aggregation_candidate_net_file"] == visual_detail_net_file
    assert calls["teacher_guided_candidate_net_file"] == tmp_path / "aggregated.net.xml"
    assert calls["teacher_guided_queue_max_ready_candidates"] == 80
    assert calls["teacher_guided_plain_net_file"] == tmp_path / "aggregated.net.xml"
    assert calls["teacher_guided_plain_netconvert_binary"] == "netconvert-test"
    assert calls["teacher_guided_run_queue_report"]["ready_candidate_count"] == 0
    assert calls["teacher_guided_run_queue_report"]["expanded_scope_candidate_count"] == 1
    assert calls["teacher_guided_run_raw_node_file"] == tmp_path / "plain.nod.xml"
    assert calls["teacher_guided_run_replay_target_internal_subgraph"] is True
    assert calls["teacher_guided_run_netconvert_binary"] == "netconvert-test"
    assert calls["teacher_guided_run_sumo_binary"] == "sumo-test"
    assert calls["teacher_guided_run_max_ready_candidates"] == 80
    assert calls["teacher_guided_run_sequential_accept_passed_variants"] is True
    assert calls["teacher_guided_run_plain_exporter"] is fake_teacher_guided_plain_export
    assert Path(calls["workflow_review_net_file"]) == tmp_path / "aggregated.net.xml"
    assert calls["aggregation_audit_report"]["matched_case_count"] == 2
    assert report["reference_join_audit_candidate_layer"] == "reference_visual_detail"
    assert report["reference_join_audit_mode"] == "full"
    assert report["reference_join_audit_candidate_net_file"] == str(visual_detail_net_file)
    assert report["reference_join_audit"]["junction_pattern_index"] == [{"junction_id": "cluster_a_b"}]
    assert report["reference_join_junction_teacher_delta_file"] == str(tmp_path / "junction_teacher_delta.json")
    assert report["reference_join_junction_pattern_comparisons_file"] == str(tmp_path / "junction_pattern_comparisons.csv")
    assert report["reference_join_junction_pattern_templates_file"] == str(tmp_path / "junction_pattern_templates.json")
    assert report["reference_join_junction_pattern_comparison_status"] == "fail"
    assert report["reference_join_junction_pattern_mismatch_count"] == 2
    assert report["reference_join_junction_pattern_comparison_sample_count"] == 2
    assert report["reference_join_junction_pattern_mismatch_field_counts"] == {"internal_function_counts": 2}
    assert report["reference_join_structural_signature_status"] == "fail"
    assert report["reference_join_structural_signature_missing_counts"] == {"tls_pattern_count": 1}
    assert report["reference_join_reference_structural_signature_summary"] == {
        "pattern_count": 2,
        "tls_pattern_count": 1,
    }
    assert report["reference_join_candidate_structural_signature_summary"] == {
        "pattern_count": 2,
        "tls_pattern_count": 0,
    }
    assert report["reference_join_network_structural_delta_status"] == "fail"
    assert report["reference_join_network_structural_missing_counts"] == {
        "crossing_edge_count": 620,
        "walkingarea_edge_count": 1648,
    }
    assert report["reference_join_network_structural_extra_counts"] == {
        "tl_logic_count": 35,
        "traffic_light_junction_count": 41,
    }
    assert report["reference_join_network_structural_junction_type_missing_counts"] == {"traffic_light": 1}
    assert report["reference_join_network_structural_junction_type_extra_counts"] == {"priority": 22}
    assert report["reference_join_reference_network_structural_summary"] == {
        "crossing_edge_count": 620,
        "walkingarea_edge_count": 1648,
    }
    assert report["reference_join_candidate_network_structural_summary"] == {
        "crossing_edge_count": 0,
        "walkingarea_edge_count": 0,
    }
    assert report["reference_join_tls_control_review_status"] == "needs_review"
    assert report["reference_join_tls_control_review_queue_count"] == 2
    assert report["reference_join_tls_control_review_category_counts"] == {
        "tls_controller_cardinality_repair": 1,
        "tls_linkindex_phase_repair": 1,
    }
    assert report["reference_join_matched_case_count"] == 2
    assert report["reference_join_unmatched_case_count"] == 1
    assert report["reference_join_aggregation_status"] == "variant_created_for_review"
    assert report["reference_join_aggregation_variant_file"] == str(tmp_path / "aggregated.net.xml")
    assert report["reference_join_aggregation_preservation_status"] == "review"
    assert report["reference_join_aggregation_removed_normal_edge_count"] == 5
    assert report["reference_join_aggregation_removed_normal_edge_type_counts"] == {
        "highway.service": 3,
        "highway.primary": 2,
    }
    assert report["reference_join_aggregation_removed_normal_edge_mode_counts"] == {
        "passenger": 4,
        "bicycle": 1,
    }
    assert report["reference_join_aggregation_lost_shared_connection_count"] == 2
    assert report["reference_join_aggregation_new_dangling_shared_normal_edge_count"] == 1
    assert report["reference_join_aggregation_preservation_audit_file"] == str(tmp_path / "aggregation_preservation.json")
    assert report["teacher_guided_repair_best_variant_file"] == ""
    assert report["teacher_guided_repair_best_expanded_scope_net_file"] == str(tmp_path / "expanded_scope.net.xml")
    assert report["reference_visual_detail_comparison_net_file"] == str(tmp_path / "aggregated.net.xml")
    assert report["teacher_guided_repair_queue_status"] == "pass"
    assert report["teacher_guided_repair_tls_candidate_count"] == 2
    assert report["teacher_guided_repair_tls_category_counts"] == {
        "tls_controller_cardinality_repair": 1,
        "tls_linkindex_phase_repair": 1,
    }
    assert report["teacher_guided_repair_ready_candidate_count"] == 0
    assert report["teacher_guided_repair_expanded_scope_candidate_count"] == 1
    assert report["teacher_guided_repair_expanded_scope_pass_candidate_count"] == 1
    assert report["teacher_guided_repair_exemplar_ready_candidate_count"] == 0
    assert report["teacher_guided_repair_exemplar_movement_signature_count"] == 0
    assert report["teacher_guided_repair_movement_gap_candidate_count"] == 1
    assert report["teacher_guided_repair_max_vehicle_movement_matrix_missing_count"] == 12
    assert report["teacher_guided_repair_missing_movement_plan_count"] == 2
    assert report["teacher_guided_repair_top_movement_gaps"] == [
        {
            "reference_id": "cluster_a_b",
            "junction_id": "",
            "candidate_status": "needs_expanded_rebuild_scope",
            "vehicle_movement_matrix_missing_count": 12,
            "missing_teacher_movement_plan_count": 2,
            "first_missing_teacher_movement": {
                "from_edge_id": "cand_in",
                "to_edge_id": "cand_out",
                "fromLane": "0",
                "toLane": "0",
                "dir": "s",
                "tl": "tlsA",
                "linkIndex": "3",
            },
            "netedit_review_actions": ["rebuild_vehicle_movement_matrix"],
        }
    ]
    assert report["teacher_guided_repair_queue_file"] == str(tmp_path / "teacher_guided_queue.json")
    assert report["teacher_guided_repair_plain_export_status"] == "pass"
    assert report["teacher_guided_repair_raw_node_file"] == str(tmp_path / "plain.nod.xml")
    assert report["teacher_guided_repair_run_status"] == "blocked"
    assert report["teacher_guided_repair_parity_gate_status"] == "blocked"
    assert report["teacher_guided_repair_application_scope"] == "none"
    assert report["teacher_guided_repair_applied_candidate_count"] == 0
    assert report["teacher_guided_repair_unapplied_pass_candidate_count"] == 0
    assert report["teacher_guided_repair_semantic_failure_counts"] == {}
    assert report["teacher_guided_repair_approach_integrity_status"] == "blocked"
    assert report["teacher_guided_repair_approach_integrity_failure_counts"] == {}
    assert report["teacher_guided_repair_template_contexts"] == [
        {
            "teacher_pattern_key": "three_way|control=right_before_left",
            "teacher_pattern_family": "three_way",
            "teacher_pattern_template_count": 127,
            "teacher_pattern_template_examples": ["cluster_template_1"],
        }
    ]
    assert report["teacher_guided_repair_run_report_file"] == str(tmp_path / "teacher_guided_run.json")
    assert report["workflow_review_net_file"] == str(tmp_path / "aggregated.net.xml")
    assert report["gate_status"]["junction_pattern_index"] == "pass"
    assert report["gate_status"]["connection_semantics_parity"] == "blocked"
    assert report["gate_status"]["tls_semantics_parity"] == "blocked"
    assert report["gate_status"]["internal_junction_parity"] == "blocked"
    assert report["gate_status"]["netedit_connection_mode_review"] == "blocked"
    assert report["gate_status"]["teacher_guided_junction_parity"] == "blocked"


def test_reference_matched_workflow_audits_post_teacher_comparison_net(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-post-teacher_filtered.osm.xml.gz"
    low_vehicle_net = tmp_path / "post_teacher_tls_low_vehicle" / "tls_low_vehicle_control_review.net.xml"
    signal_grouped_net = tmp_path / "post_teacher_tls_signal_grouping" / "tls_signal_grouped.net.xml"
    tls_connection_repaired_net = tmp_path / "post_teacher_tls_connection_repair" / "repaired.net.xml"
    post_repair_movement_composite_net = tmp_path / "post_repair_movement_composite.net.xml"
    calls: dict[str, object] = {
        "reference_join_candidate_net_files": [],
        "teacher_guided_queue_calls": [],
        "teacher_guided_queue_reports": [],
        "teacher_guided_run_calls": [],
    }

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_reference_join_audit(**kwargs):
        calls["reference_join_candidate_net_files"].append(kwargs["candidate_net_file"])
        base = {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "full",
            "reference_case_count": 3,
            "matched_case_count": 2,
            "unmatched_case_count": 1,
            "junction_pattern_index": [{"junction_id": "cluster_a_b"}],
            "summary_file": str(tmp_path / "reference_join_audit.json"),
            "cases_file": str(tmp_path / "reference_join_cases.csv"),
            "junction_pattern_comparison_status": "fail",
            "junction_pattern_mismatch_count": 2,
            "junction_pattern_mismatch_field_counts": {"movement_signature_counts": 2},
            "junction_pattern_comparisons": [{"junction_id": "j1", "status": "fail"}],
            "network_structural_delta_status": "fail",
            "network_structural_missing_counts": {"connection_count": 10, "crossing_edge_count": 2},
            "network_structural_extra_counts": {"walkingarea_edge_count": 1},
            "warnings": [],
        }
        if kwargs["prefix"].endswith("_post_teacher_reference_join_audit"):
            return {
                **base,
                "summary_file": str(tmp_path / "post_teacher_reference_join_audit.json"),
                "junction_pattern_mismatch_count": 1,
                "junction_pattern_mismatch_field_counts": {"movement_signature_counts": 1},
                "network_structural_missing_counts": {"connection_count": 4, "crossing_edge_count": 3},
                "network_structural_extra_counts": {
                    "tl_logic_count": 6,
                    "tls_controlled_connection_count": 10,
                    "traffic_light_junction_count": 9,
                    "walkingarea_edge_count": 5,
                },
                "tls_control_review_queue": [
                    {
                        "repair_category": "tls_reality_review",
                        "review_type": "downgrade_low_vehicle_approach_tls",
                        "tl_id": "low_tls",
                        "controlled_connection_count": 10,
                        "controlled_passenger_from_edge_count": 1,
                    }
                ],
            }
        if kwargs["candidate_net_file"] == low_vehicle_net:
            return {
                **base,
                "summary_file": str(tmp_path / "post_teacher_tls_low_vehicle_delta.json"),
                "network_structural_missing_counts": {
                    "connection_count": 4,
                    "crossing_edge_count": 3,
                    "tls_shared_linkindex_group_count": 2,
                    "tls_controlled_connection_count": 6,
                },
                "network_structural_extra_counts": {"walkingarea_edge_count": 5},
            }
        if kwargs["candidate_net_file"] == signal_grouped_net:
            return {
                **base,
                "summary_file": str(tmp_path / "post_teacher_tls_signal_grouping_delta.json"),
                "network_structural_missing_counts": {
                    "connection_count": 4,
                    "crossing_edge_count": 3,
                    "tls_controlled_connection_count": 5,
                },
                "network_structural_extra_counts": {"walkingarea_edge_count": 5},
            }
        if kwargs["candidate_net_file"] == tls_connection_repaired_net:
            return {
                **base,
                "summary_file": str(tmp_path / "post_teacher_tls_connection_repair_delta.json"),
                "junction_pattern_mismatch_count": 2,
                "junction_pattern_mismatch_field_counts": {
                    "control_type": 1,
                    "internal_function_counts": 2,
                    "movement_signature_counts": 2,
                },
                "junction_pattern_comparisons": [
                    {
                        "junction_id": "tls_repair_j1",
                        "status": "fail",
                        "mismatch_fields": ["internal_function_counts", "movement_signature_counts"],
                        "teacher": {
                            "control_type": "traffic_light",
                            "has_tls": True,
                            "internal_function_counts": {
                                "crossing": 2,
                                "internal": 8,
                                "walkingarea": 2,
                            },
                        },
                        "candidate": {
                            "control_type": "traffic_light",
                            "has_tls": True,
                            "internal_function_counts": {
                                "crossing": 0,
                                "internal": 5,
                                "walkingarea": 1,
                            },
                        },
                    },
                    {
                        "junction_id": "tls_repair_j2",
                        "status": "fail",
                        "mismatch_fields": [
                            "control_type",
                            "internal_function_counts",
                            "movement_signature_counts",
                        ],
                        "teacher": {
                            "control_type": "traffic_light",
                            "has_tls": True,
                            "internal_function_counts": {
                                "crossing": 3,
                                "internal": 7,
                                "walkingarea": 2,
                            },
                        },
                        "candidate": {
                            "control_type": "priority",
                            "has_tls": True,
                            "internal_function_counts": {
                                "crossing": 2,
                                "internal": 4,
                                "walkingarea": 1,
                            },
                        },
                    },
                ],
                "network_structural_missing_counts": {"connection_count": 4, "crossing_edge_count": 3},
                "network_structural_extra_counts": {"walkingarea_edge_count": 5},
            }
        if kwargs["candidate_net_file"] == post_repair_movement_composite_net:
            return {
                **base,
                "summary_file": str(tmp_path / "post_repair_movement_delta.json"),
                "junction_pattern_mismatch_count": 0,
                "junction_pattern_mismatch_field_counts": {},
                "junction_pattern_comparisons": [],
                "network_structural_missing_counts": {"connection_count": 2, "crossing_edge_count": 1},
                "network_structural_extra_counts": {"walkingarea_edge_count": 2},
            }
        return base

    def fake_teacher_guided_repair_queue(**kwargs):
        calls["teacher_guided_queue_calls"].append(kwargs)
        if kwargs["prefix"].endswith("_post_teacher_tls_connection_repair_movement_rebuild"):
            report = {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "repair_candidate_count": 2,
                "ready_candidate_count": 1,
                "expanded_scope_candidate_count": 1,
                "queue_file": str(tmp_path / "post_repair_movement_queue.json"),
                "queue_csv_file": str(tmp_path / "post_repair_movement_queue.csv"),
                "repair_candidates": [
                    {
                        "reference_id": "tls_repair_j1",
                        "junction_id": "tls_repair_j1",
                        "candidate_status": "ready_for_teacher_guided_variant",
                        "vehicle_movement_matrix_missing_count": 3,
                        "missing_teacher_movement_plan_count": 2,
                        "netedit_review_actions": ["rebuild_vehicle_movement_matrix"],
                    }
                ],
                "warnings": [],
            }
        else:
            report = {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "repair_candidate_count": 1,
                "ready_candidate_count": 1,
                "expanded_scope_candidate_count": 0,
                "queue_file": str(tmp_path / "teacher_guided_queue.json"),
                "repair_candidates": [],
                "warnings": [],
            }
        calls["teacher_guided_queue_reports"].append(report)
        return report

    def fake_teacher_guided_plain_export(**_kwargs):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "raw_node_file": str(tmp_path / "plain.nod.xml"),
            "raw_edge_file": str(tmp_path / "plain.edg.xml"),
            "raw_connection_file": str(tmp_path / "plain.con.xml"),
            "raw_type_file": str(tmp_path / "plain.typ.xml"),
            "warnings": [],
        }

    def fake_teacher_guided_repair_run(**kwargs):
        calls["teacher_guided_run_calls"].append(kwargs)
        is_post_repair_movement = kwargs["prefix"].endswith("_post_teacher_tls_connection_repair_movement_rebuild")
        composite_net = post_repair_movement_composite_net if is_post_repair_movement else tmp_path / "teacher_guided_composite.net.xml"
        composite_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "parity_gate_status": "pass",
            "attempted_candidate_count": 2,
            "pass_candidate_count": 2,
            "composite_applied_candidate_count": 2,
            "composite_net_file": str(composite_net),
            "variant_reports": [],
            "run_report_file": str(tmp_path / "teacher_guided_run.json"),
            "warnings": [],
        }

    def fake_low_vehicle_control(**kwargs):
        calls["post_teacher_low_vehicle_source_net_file"] = kwargs["source_net_file"]
        calls["post_teacher_low_vehicle_queue_count"] = len(kwargs["tls_control_review_queue"])
        low_vehicle_net.parent.mkdir(parents=True, exist_ok=True)
        low_vehicle_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_low_vehicle_control_status": "variant_created_for_review",
            "tls_low_vehicle_control_variant_file": str(low_vehicle_net),
            "tls_low_vehicle_control_selected_tllogic_count": 1,
            "tls_low_vehicle_control_removed_connection_count": 10,
            "warnings": [],
        }

    def fake_signal_grouping(**kwargs):
        calls["post_teacher_signal_grouping_source_net_file"] = kwargs["source_net_file"]
        calls["post_teacher_signal_grouping_max_shared_groups"] = kwargs["max_shared_linkindex_groups"]
        signal_grouped_net.parent.mkdir(parents=True, exist_ok=True)
        signal_grouped_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_signal_grouping_status": "variant_created_for_review",
            "tls_signal_grouping_variant_file": str(signal_grouped_net),
            "tls_signal_grouping_merged_group_count": 2,
            "tls_signal_grouping_remapped_connection_count": 4,
            "warnings": [],
        }

    def fake_tls_connection_repair(**kwargs):
        calls["post_teacher_tls_connection_repair_source_net_file"] = kwargs["source_net_file"]
        calls["post_teacher_tls_connection_repair_candidate_net_file"] = kwargs["candidate_net_file"]
        calls["post_teacher_tls_connection_repair_copy_unmapped_tls"] = kwargs["copy_unmapped_tls"]
        tls_connection_repaired_net.parent.mkdir(parents=True, exist_ok=True)
        tls_connection_repaired_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "variant_file": str(tls_connection_repaired_net),
            "candidate_tls_controlled_connection_count_before": 10,
            "candidate_tls_controlled_connection_count_after": 15,
            "updated_connection_count": 5,
            "skipped_invalid_mapped_linkindex_connection_count": 0,
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-post-teacher",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {"status": "pass", "tls_candidate_count": 0, "warnings": []},
        connectivity_func=lambda _path: {"status": "pass", "connectivity_status": "pass", "passenger_edge_count": 1},
        topology_audit_func=lambda **_kwargs: {"status": "pass", "topology_fragmentation_status": "pass", "warnings": []},
        routeability_audit_func=lambda **_kwargs: {"status": "pass", "routeability_status": "pass", "warnings": []},
        netedit_func=lambda _path: {"status": "blocked", "netedit_status": "skipped", "warnings": []},
        sumo_gui_func=lambda _path, **_kwargs: {"status": "blocked", "sumo_gui_status": "skipped", "warnings": []},
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=lambda **_kwargs: {"status": "blocked", "warnings": []},
        teacher_guided_repair_queue_func=fake_teacher_guided_repair_queue,
        teacher_guided_plain_export_func=fake_teacher_guided_plain_export,
        teacher_guided_repair_run_func=fake_teacher_guided_repair_run,
        tls_low_vehicle_control_func=fake_low_vehicle_control,
        tls_signal_grouping_func=fake_signal_grouping,
        tls_connection_repair_func=fake_tls_connection_repair,
        command_runner=lambda command, **_kwargs: {"status": "pass", "returncode": 0, "stdout": "", "stderr": ""},
        review_html_func=lambda **kwargs: {
            "status": "pass",
            "workflow_review_html_status": "pass",
            "workflow_review_html_file": str(tmp_path / "review.html"),
            "workflow_review_net_file": str(kwargs["net_file"]),
            "workflow_report_file": str(tmp_path / "workflow_report.json"),
            "warnings": [],
        },
    )

    assert tmp_path / "teacher_guided_composite.net.xml" in calls["reference_join_candidate_net_files"]
    assert low_vehicle_net in calls["reference_join_candidate_net_files"]
    assert signal_grouped_net in calls["reference_join_candidate_net_files"]
    assert tls_connection_repaired_net in calls["reference_join_candidate_net_files"]
    assert post_repair_movement_composite_net in calls["reference_join_candidate_net_files"]
    assert calls["reference_join_candidate_net_files"].index(tmp_path / "teacher_guided_composite.net.xml") < calls[
        "reference_join_candidate_net_files"
    ].index(low_vehicle_net)
    assert calls["reference_join_candidate_net_files"].index(low_vehicle_net) < calls[
        "reference_join_candidate_net_files"
    ].index(signal_grouped_net)
    assert calls["reference_join_candidate_net_files"].index(signal_grouped_net) < calls[
        "reference_join_candidate_net_files"
    ].index(tls_connection_repaired_net)
    assert calls["post_teacher_low_vehicle_source_net_file"] == tmp_path / "teacher_guided_composite.net.xml"
    assert calls["post_teacher_low_vehicle_queue_count"] == 1
    assert calls["post_teacher_signal_grouping_source_net_file"] == low_vehicle_net
    assert calls["post_teacher_signal_grouping_max_shared_groups"] == 2
    assert calls["post_teacher_tls_connection_repair_source_net_file"] == reference_net_file
    assert calls["post_teacher_tls_connection_repair_candidate_net_file"] == signal_grouped_net
    assert calls["post_teacher_tls_connection_repair_copy_unmapped_tls"] is True
    assert len(calls["teacher_guided_queue_calls"]) == 2
    assert len(calls["teacher_guided_queue_reports"]) == 2
    assert len(calls["teacher_guided_run_calls"]) == 2
    post_repair_queue_call = calls["teacher_guided_queue_calls"][1]
    post_repair_queue_report = calls["teacher_guided_queue_reports"][1]
    assert post_repair_queue_call["candidate_net_file"] == tls_connection_repaired_net
    assert post_repair_queue_call["reference_join_audit_report"]["summary_file"] == str(
        tmp_path / "post_teacher_tls_connection_repair_delta.json"
    )
    post_repair_run_call = calls["teacher_guided_run_calls"][1]
    assert post_repair_run_call["queue_report"] is post_repair_queue_report
    assert post_repair_run_call["prefix"].endswith("_post_teacher_tls_connection_repair_movement_rebuild")
    assert report["reference_visual_detail_comparison_net_file"] == str(post_repair_movement_composite_net)
    assert report["reference_visual_detail_comparison_selection_reason"] == (
        "post_teacher_tls_connection_repair_movement_rebuild_promoted"
    )
    assert report["reference_join_post_teacher_audit_status"] == "pass"
    assert report["reference_join_post_teacher_junction_pattern_mismatch_count"] == 0
    assert report["reference_join_post_teacher_junction_pattern_mismatch_field_counts"] == {}
    assert report["reference_join_post_teacher_network_structural_missing_counts"] == {
        "connection_count": 2,
        "crossing_edge_count": 1,
    }
    assert report["reference_join_post_teacher_network_structural_extra_counts"] == {
        "walkingarea_edge_count": 2,
    }
    assert report["post_teacher_tls_low_vehicle_control_status"] == "pass"
    assert report["post_teacher_tls_low_vehicle_control_reference_promotion_status"] == "pass"
    assert report["post_teacher_tls_low_vehicle_control_reference_tls_semantic_delta_score"] == 8
    assert report["post_teacher_tls_signal_grouping_status"] == "pass"
    assert report["post_teacher_tls_signal_grouping_reference_promotion_status"] == "pass"
    assert report["post_teacher_tls_signal_grouping_reference_tls_semantic_delta_score"] == 5
    assert report["post_teacher_tls_connection_repair_status"] == "pass"
    assert report["post_teacher_tls_connection_repair_reference_promotion_status"] == "pass"
    assert report["post_teacher_tls_connection_repair_reference_tls_semantic_delta_score"] == 0
    assert report["post_teacher_tls_connection_repair_junction_pattern_mismatch_count"] == 2
    assert report["post_teacher_tls_connection_repair_junction_pattern_mismatch_field_counts"] == {
        "control_type": 1,
        "internal_function_counts": 2,
        "movement_signature_counts": 2,
    }
    assert report["post_teacher_tls_connection_repair_internal_function_count_deficits"] == {
        "crossing": 3,
        "internal": 6,
        "walkingarea": 2,
    }
    assert report["post_teacher_tls_connection_repair_top_junction_pattern_mismatches"][0] == {
        "junction_id": "tls_repair_j1",
        "mismatch_fields": ["internal_function_counts", "movement_signature_counts"],
        "teacher_control_type": "traffic_light",
        "candidate_control_type": "traffic_light",
        "teacher_has_tls": True,
        "candidate_has_tls": True,
        "internal_function_count_deficits": {
            "crossing": 2,
            "internal": 3,
            "walkingarea": 1,
        },
    }
    assert report["post_teacher_tls_connection_repair_movement_rebuild_queue_status"] == "pass"
    assert report["post_teacher_tls_connection_repair_movement_rebuild_candidate_count"] == 2
    assert report["post_teacher_tls_connection_repair_movement_rebuild_ready_candidate_count"] == 1
    assert report["post_teacher_tls_connection_repair_movement_rebuild_expanded_scope_candidate_count"] == 1
    assert report["post_teacher_tls_connection_repair_movement_rebuild_gap_candidate_count"] == 1
    assert report["post_teacher_tls_connection_repair_movement_rebuild_max_gap_count"] == 3
    assert report["post_teacher_tls_connection_repair_movement_rebuild_queue_file"] == str(
        tmp_path / "post_repair_movement_queue.json"
    )
    assert report["post_teacher_tls_connection_repair_movement_rebuild_run_status"] == "pass"
    assert report["post_teacher_tls_connection_repair_movement_rebuild_parity_gate_status"] == "pass"
    assert report["post_teacher_tls_connection_repair_movement_rebuild_best_variant_file"] == str(
        post_repair_movement_composite_net
    )


def test_reference_matched_workflow_prefers_tls_aggregated_visual_detail_for_reference_join(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-tls_filtered.osm.xml.gz"
    visual_tls_net_file = tmp_path / "tls_aggregation" / "reference_visual_detail_tls.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_tls(**kwargs):
        net_file = Path(kwargs["net_file"])
        if "reference_visual_detail" in net_file.name:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "tls_candidate_count": 4,
                "tls_cluster_count": 2,
                "clusters_file": str(tmp_path / "visual_tls_clusters.csv"),
                "warnings": [],
            }
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        }

    def fake_tls_aggregation(**kwargs):
        assert "reference_visual_detail" in Path(kwargs["net_file"]).name
        visual_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        visual_tls_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_physical_cluster_count": 2,
            "tls_aggregation_variant_file": str(visual_tls_net_file),
            "tls_aggregated_traffic_light_junction_count": 2,
            "tls_aggregated_tl_logic_count": 2,
            "tls_aggregated_controlled_connection_count": 7,
            "tls_aggregated_tl_connection_missing_linkindex_count": 1,
            "tls_controlled_connection_preservation_status": "pass",
            "tls_controlled_connection_regression_count": 0,
            "warnings": ["TLS aggregation variant requires Google Maps and Netedit review before adoption"],
        }

    def fake_reference_join_audit(**kwargs):
        calls["reference_join_candidate_net_file"] = kwargs["candidate_net_file"]
        calls["reference_join_structural_only"] = kwargs["structural_only"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "structural_only",
            "reference_case_count": 1,
            "matched_case_count": 1,
            "unmatched_case_count": 0,
            "summary_file": str(tmp_path / "reference_join_audit.json"),
            "cases_file": str(tmp_path / "reference_join_cases.csv"),
            "warnings": [],
        }

    def fail_reference_join_aggregation(**_kwargs):
        raise AssertionError("structural-only audit should not trigger reference join aggregation")

    def fail_teacher_guided_repair_queue(**_kwargs):
        raise AssertionError("structural-only audit should not trigger teacher-guided repair queue")

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-tls",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 100,
            "passenger_component_count": 1,
            "largest_component_edge_count": 100,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=fail_reference_join_aggregation,
        teacher_guided_repair_queue_func=fail_teacher_guided_repair_queue,
    )

    assert calls["reference_join_candidate_net_file"] == visual_tls_net_file
    assert calls["reference_join_structural_only"] is True
    assert report["reference_join_audit_mode"] == "structural_only"
    assert report["reference_visual_detail_net_file"] == str(tmp_path / "sumo" / "reference-tls_reference_visual_detail.net.xml")
    assert report["reference_visual_detail_comparison_net_file"] == str(visual_tls_net_file)
    assert report["reference_visual_detail_tls_aggregation_status"] == "variant_created_for_review"
    assert report["reference_visual_detail_tls_aggregated_tl_logic_count"] == 2
    assert report["reference_visual_detail_tls_aggregated_controlled_connection_count"] == 7
    assert report["reference_visual_detail_tls_aggregated_tl_connection_missing_linkindex_count"] == 1
    assert report["reference_visual_detail_tls_controlled_connection_preservation_status"] == "pass"
    assert report["reference_visual_detail_tls_controlled_connection_regression_count"] == 0


def test_reference_matched_workflow_promotes_repaired_tls_variant_when_gates_pass(
    tmp_path: Path,
) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-regression_filtered.osm.xml.gz"
    visual_tls_net_file = tmp_path / "tls_aggregation" / "reference_visual_detail_tls.net.xml"
    representatives_file = tmp_path / "tls_aggregation" / "representatives.csv"
    repaired_tls_net_file = tmp_path / "tls_connection_repair" / "repaired.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_tls(**kwargs):
        if "reference_visual_detail" in Path(kwargs["net_file"]).name:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "tls_candidate_count": 4,
                "tls_cluster_count": 2,
                "clusters_file": str(tmp_path / "visual_tls_clusters.csv"),
                "warnings": [],
            }
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        }

    def fake_tls_aggregation(**_kwargs):
        calls["tls_aggregation_guess_signals_dist"] = _kwargs.get("tls_guess_signals_dist_m")
        visual_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        visual_tls_net_file.write_text("<net/>", encoding="utf-8")
        representatives_file.write_text(
            "cluster_id,representative_node_id,tls_ids,tls_count,google_maps_url\n"
            "G001,agg_tls,raw_tls;agg_tls,2,https://example.invalid\n",
            encoding="utf-8",
        )
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_aggregation_variant_file": str(visual_tls_net_file),
            "tls_aggregation_representatives_file": str(representatives_file),
            "tls_controlled_connection_preservation_status": "fail",
            "tls_controlled_connection_regression_count": 12,
            "warnings": [],
        }

    def fake_reference_join_audit(**kwargs):
        if Path(kwargs["candidate_net_file"]) == visual_tls_net_file:
            calls["rejected_tls_delta_candidate_net_file"] = kwargs["candidate_net_file"]
            calls["rejected_tls_delta_structural_only"] = kwargs["structural_only"]
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_delta_status": "fail",
                "network_structural_missing_counts": {"tls_controlled_connection_count": 337},
                "network_structural_extra_counts": {"tl_logic_count": 12, "traffic_light_junction_count": 41},
                "network_structural_junction_type_missing_counts": {},
                "network_structural_junction_type_extra_counts": {"traffic_light": 41},
                "summary_file": str(tmp_path / "rejected_tls_delta.json"),
                "warnings": [],
            }
        if Path(kwargs["candidate_net_file"]) == repaired_tls_net_file and "tls_connection_repair_reference_delta" in str(
            kwargs["output_dir"]
        ):
            calls["repair_tls_delta_candidate_net_file"] = kwargs["candidate_net_file"]
            calls["repair_tls_delta_structural_only"] = kwargs["structural_only"]
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_delta_status": "fail",
                "network_structural_missing_counts": {"tls_controlled_connection_count": 90},
                "network_structural_extra_counts": {"tl_logic_count": 0, "traffic_light_junction_count": 41},
                "network_structural_junction_type_missing_counts": {},
                "network_structural_junction_type_extra_counts": {"traffic_light": 41},
                "summary_file": str(tmp_path / "repair_tls_delta.json"),
                "warnings": [],
            }
        calls["reference_join_candidate_net_file"] = kwargs["candidate_net_file"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "structural_only",
            "reference_case_count": 0,
            "matched_case_count": 0,
            "unmatched_case_count": 0,
            "network_structural_delta_status": "fail",
            "network_structural_missing_counts": {},
            "network_structural_extra_counts": {"tl_logic_count": 35},
            "network_structural_junction_type_missing_counts": {},
            "network_structural_junction_type_extra_counts": {"traffic_light": 186},
            "warnings": [],
        }

    def fake_tls_connection_repair(**kwargs):
        calls["tls_connection_repair_source_net_file"] = kwargs["source_net_file"]
        calls["tls_connection_repair_candidate_net_file"] = kwargs["candidate_net_file"]
        calls["tls_connection_repair_tls_id_map"] = kwargs["tls_id_map"]
        calls["tls_connection_repair_copy_unmapped_tls"] = kwargs["copy_unmapped_tls"]
        calls["tls_connection_repair_require_capacity"] = kwargs["require_target_link_index_capacity"]
        calls["tls_connection_repair_pad_capacity"] = kwargs.get("pad_mapped_tllogic_capacity", False)
        calls["tls_connection_repair_add_green"] = kwargs.get("add_green_phases_for_padded_links", False)
        calls["tls_connection_repair_add_yellow"] = kwargs.get("add_yellow_phases_for_generated_green", False)
        repaired_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        repaired_tls_net_file.write_text("<net/>", encoding="utf-8")
        summary_file = tmp_path / "tls_connection_repair" / "summary.json"
        summary_file.write_text("{}", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "variant_file": str(repaired_tls_net_file),
            "summary_file": str(summary_file),
            "candidate_tls_controlled_connection_count_before": 7,
            "candidate_tls_controlled_connection_count_after": 9,
            "updated_connection_count": 2,
            "skipped_invalid_mapped_linkindex_connection_count": 0,
            "added_green_phase_count": 3,
            "added_yellow_phase_count": 3,
            "warnings": ["diagnostic repair"],
        }

    def fake_command_runner(command, **_kwargs):
        calls["tls_connection_repair_sumo_command"] = command
        return {"status": "pass", "returncode": 0, "stdout": "", "stderr": ""}

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-regression",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        tls_connection_repair_func=fake_tls_connection_repair,
        command_runner=fake_command_runner,
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 100,
            "passenger_component_count": 1,
            "largest_component_edge_count": 100,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structural-only audit should not trigger aggregation")
        ),
        teacher_guided_repair_queue_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structural-only audit should not trigger teacher queue")
        ),
    )

    raw_visual_detail_net_file = tmp_path / "sumo" / "reference-regression_reference_visual_detail.net.xml"
    assert calls["rejected_tls_delta_candidate_net_file"] == visual_tls_net_file
    assert calls["rejected_tls_delta_structural_only"] is True
    assert calls["tls_connection_repair_source_net_file"] == raw_visual_detail_net_file
    assert calls["tls_connection_repair_candidate_net_file"] == visual_tls_net_file
    assert calls["tls_connection_repair_tls_id_map"] == {"raw_tls": "agg_tls", "agg_tls": "agg_tls"}
    assert calls["tls_connection_repair_copy_unmapped_tls"] is False
    assert calls["tls_connection_repair_require_capacity"] is True
    assert calls["tls_connection_repair_pad_capacity"] is False
    assert calls["tls_connection_repair_add_green"] is False
    assert calls["tls_connection_repair_add_yellow"] is False
    assert calls["repair_tls_delta_candidate_net_file"] == repaired_tls_net_file
    assert calls["repair_tls_delta_structural_only"] is True
    assert calls["reference_join_candidate_net_file"] == repaired_tls_net_file
    assert calls["tls_connection_repair_sumo_command"][0] == "sumo"
    assert calls["tls_connection_repair_sumo_command"][1:3] == ["-n", "sumo_load_candidate.net.xml"]
    assert report["reference_visual_detail_comparison_net_file"] == str(repaired_tls_net_file)
    assert report["reference_visual_detail_comparison_selection_reason"] == (
        "tls_connection_repair_promoted_after_sumo_load_and_reference_delta"
    )
    assert report["reference_visual_detail_tls_controlled_connection_preservation_status"] == "fail"
    assert report["reference_visual_detail_tls_controlled_connection_regression_count"] == 12
    assert report["reference_join_tls_semantic_delta_score"] == 35
    assert report["reference_visual_detail_tls_aggregation_reference_delta_status"] == "fail"
    assert report["reference_visual_detail_tls_aggregation_reference_tls_semantic_delta_score"] == 390
    assert report["reference_visual_detail_tls_aggregation_reference_delta_missing_counts"] == {
        "tls_controlled_connection_count": 337
    }
    assert report["reference_visual_detail_tls_aggregation_reference_delta_extra_counts"] == {
        "tl_logic_count": 12,
        "traffic_light_junction_count": 41,
    }
    assert report["reference_visual_detail_tls_connection_repair_status"] == "pass"
    assert report["reference_visual_detail_tls_connection_repair_controlled_connection_count_before"] == 7
    assert report["reference_visual_detail_tls_connection_repair_controlled_connection_count_after"] == 9
    assert report["reference_visual_detail_tls_connection_repair_updated_connection_count"] == 2
    assert report["reference_visual_detail_tls_connection_repair_skipped_invalid_mapped_linkindex_count"] == 0
    assert report["reference_visual_detail_tls_connection_repair_promotion_status"] == "pass"
    assert report["reference_visual_detail_tls_connection_repair_sumo_load_status"] == "pass"
    assert report["reference_visual_detail_tls_connection_repair_reference_tls_semantic_delta_score"] == 131
    assert report["reference_visual_detail_tls_connection_repair_reference_delta_missing_counts"] == {
        "tls_controlled_connection_count": 90
    }


def test_reference_matched_workflow_promotes_tls_aggregation_when_reference_delta_improves(
    tmp_path: Path,
) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-delta_filtered.osm.xml.gz"
    best_visual_tls_net_file = tmp_path / "reference_visual_detail_tls_aggregation_guess20" / "tls_aggregated.net.xml"
    low_vehicle_net_file = tmp_path / "reference_visual_detail_tls_low_vehicle_control" / "tls_low_vehicle_control_review.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_tls(**kwargs):
        if "reference_visual_detail" in Path(kwargs["net_file"]).name:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "tls_candidate_count": 4,
                "tls_cluster_count": 2,
                "clusters_file": str(tmp_path / "visual_tls_clusters.csv"),
                "warnings": [],
            }
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        }

    def fake_tls_aggregation(**_kwargs):
        calls.setdefault("tls_aggregation_guess_signal_dists", []).append(_kwargs.get("tls_guess_signals_dist_m"))
        visual_tls_net_file = Path(_kwargs["output_dir"]) / "tls_aggregated.net.xml"
        visual_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        visual_tls_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_aggregation_variant_file": str(visual_tls_net_file),
            "tls_controlled_connection_preservation_status": "fail",
            "tls_controlled_connection_regression_count": 12,
            "warnings": [],
        }

    raw_visual_detail_net_file = tmp_path / "sumo" / "reference-delta_reference_visual_detail.net.xml"

    def fake_reference_join_audit(**kwargs):
        candidate_net_file = Path(kwargs["candidate_net_file"])
        output_dir = str(kwargs["output_dir"])
        if "tls_aggregation_reference_delta" in output_dir:
            calls.setdefault("aggregation_delta_candidate_net_files", []).append(kwargs["candidate_net_file"])
            score_counts = (
                {"traffic_light_junction_count": 30, "tls_controlled_connection_count": 77}
                if "guess20" in str(candidate_net_file.parent)
                else {"traffic_light_junction_count": 300}
            )
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_delta_status": "fail",
                "network_structural_missing_counts": {"tls_controlled_connection_count": 90},
                "network_structural_extra_counts": score_counts,
                "network_structural_junction_type_missing_counts": {},
                "network_structural_junction_type_extra_counts": {"traffic_light": score_counts["traffic_light_junction_count"]},
                "tls_control_review_queue": [
                    {
                        "repair_category": "tls_reality_review",
                        "review_type": "downgrade_low_vehicle_approach_tls",
                        "tl_id": "lowTls",
                        "controlled_connection_count": 77,
                        "controlled_passenger_from_edge_count": 1,
                    }
                ]
                if "guess20" in str(candidate_net_file.parent)
                else [],
                "summary_file": str(tmp_path / "aggregation_delta.json"),
                "warnings": [],
            }
        if candidate_net_file == raw_visual_detail_net_file and "raw_reference_delta" in output_dir:
            calls["raw_delta_candidate_net_file"] = kwargs["candidate_net_file"]
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_delta_status": "fail",
                "network_structural_missing_counts": {"tls_shared_linkindex_group_count": 40},
                "network_structural_extra_counts": {"traffic_light_junction_count": 354},
                "network_structural_junction_type_missing_counts": {},
                "network_structural_junction_type_extra_counts": {"traffic_light": 354},
                "summary_file": str(tmp_path / "raw_delta.json"),
                "warnings": [],
            }
        if candidate_net_file == best_visual_tls_net_file:
            calls["reference_join_candidate_net_file"] = kwargs["candidate_net_file"]
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_delta_status": "fail",
                "network_structural_missing_counts": {"tls_controlled_connection_count": 90},
                "network_structural_extra_counts": {"traffic_light_junction_count": 30},
                "network_structural_junction_type_missing_counts": {},
                "network_structural_junction_type_extra_counts": {"traffic_light": 30},
                "warnings": [],
            }
        if candidate_net_file == low_vehicle_net_file:
            calls["reference_join_candidate_net_file"] = kwargs["candidate_net_file"]
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_delta_status": "fail",
                "network_structural_missing_counts": {"tls_controlled_connection_count": 90},
                "network_structural_extra_counts": {"traffic_light_junction_count": 5},
                "network_structural_junction_type_missing_counts": {},
                "network_structural_junction_type_extra_counts": {"traffic_light": 5},
                "summary_file": str(tmp_path / "low_vehicle_delta.json"),
                "warnings": [],
            }
        calls["reference_join_candidate_net_file"] = kwargs["candidate_net_file"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "structural_only",
            "network_structural_delta_status": "fail",
            "network_structural_missing_counts": {"tls_controlled_connection_count": 165},
            "network_structural_extra_counts": {"traffic_light_junction_count": 46},
            "network_structural_junction_type_missing_counts": {},
            "network_structural_junction_type_extra_counts": {"traffic_light": 46},
            "warnings": [],
        }

    def fake_low_vehicle_control(**kwargs):
        calls["low_vehicle_source_net_file"] = kwargs["source_net_file"]
        calls.setdefault("low_vehicle_budgets", []).append(kwargs["max_removed_controlled_connections"])
        calls.setdefault("low_vehicle_max_selected_counts", []).append(kwargs["max_selected_tllogic_count"])
        calls.setdefault("low_vehicle_queue_counts", []).append(len(kwargs["tls_control_review_queue"]))
        low_vehicle_net_file.parent.mkdir(parents=True, exist_ok=True)
        low_vehicle_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_low_vehicle_control_status": "variant_created_for_review",
            "tls_low_vehicle_control_variant_file": str(low_vehicle_net_file),
            "tls_low_vehicle_control_selected_tllogic_count": 1,
            "tls_low_vehicle_control_removed_connection_count": 77,
            "warnings": [],
        }

    def fake_command_runner(command, **_kwargs):
        calls["low_vehicle_sumo_command"] = command
        return {"status": "pass", "returncode": 0, "stdout": "", "stderr": ""}

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-delta",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        tls_low_vehicle_control_func=fake_low_vehicle_control,
        command_runner=fake_command_runner,
        tls_connection_repair_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("reference-delta promotion should skip TLS repair")
        ),
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 100,
            "passenger_component_count": 1,
            "largest_component_edge_count": 100,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structural-only audit should not trigger aggregation")
        ),
        teacher_guided_repair_queue_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structural-only audit should not trigger teacher queue")
        ),
    )

    assert calls["tls_aggregation_guess_signal_dists"] == [35.0, 20.0, None]
    assert best_visual_tls_net_file in [Path(str(path)) for path in calls["aggregation_delta_candidate_net_files"]]
    assert calls["raw_delta_candidate_net_file"] == raw_visual_detail_net_file
    assert calls["low_vehicle_source_net_file"] == best_visual_tls_net_file
    assert 77 in calls["low_vehicle_budgets"]
    assert calls["low_vehicle_queue_counts"] == [1, 1]
    assert calls["reference_join_candidate_net_file"] == low_vehicle_net_file
    assert report["reference_visual_detail_comparison_net_file"] == str(low_vehicle_net_file)
    assert report["reference_visual_detail_comparison_selection_reason"] == (
        "tls_low_vehicle_control_promoted_by_reference_delta"
    )
    assert report["reference_visual_detail_tls_aggregation_reference_promotion_status"] == "pass"
    assert report["reference_visual_detail_tls_aggregation_reference_tls_semantic_delta_score"] == 197
    assert report["reference_visual_detail_tls_low_vehicle_control_reference_promotion_status"] == "pass"
    assert report["reference_visual_detail_tls_low_vehicle_control_reference_tls_semantic_delta_score"] == 95
    assert report["reference_visual_detail_tls_low_vehicle_control_sumo_load_status"] == "pass"
    assert report["reference_visual_detail_raw_reference_tls_semantic_delta_score"] == 394
    assert report["reference_join_tls_semantic_delta_score"] == 95
    assert report["reference_visual_detail_tls_aggregation_candidate_count"] == 3


def test_reference_matched_workflow_promotes_signal_grouping_when_reference_delta_improves(
    tmp_path: Path,
) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-signal_filtered.osm.xml.gz"
    visual_tls_net_file = tmp_path / "tls_aggregation" / "reference_visual_detail_tls.net.xml"
    signal_grouped_net_file = tmp_path / "tls_signal_grouping" / "signal_grouped.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_tls(**kwargs):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 2,
            "tls_cluster_count": 1 if "reference_visual_detail" in Path(kwargs["net_file"]).name else 0,
            "clusters_file": str(tmp_path / "visual_tls_clusters.csv"),
            "warnings": [],
        }

    def fake_tls_aggregation(**_kwargs):
        calls.setdefault("tls_aggregation_guess_signal_dists", []).append(_kwargs.get("tls_guess_signals_dist_m"))
        if _kwargs.get("tls_guess_signals_dist_m") != 35.0:
            return {
                "status": "fail",
                "claim_status": "construction-invalid",
                "tls_aggregation_status": "failed",
                "tls_aggregation_variant_file": "",
                "warnings": [],
            }
        visual_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        visual_tls_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_aggregation_variant_file": str(visual_tls_net_file),
            "tls_controlled_connection_preservation_status": "fail",
            "warnings": [],
        }

    def fake_signal_grouping(**kwargs):
        calls["signal_grouping_max_shared_linkindex_groups"] = kwargs["max_shared_linkindex_groups"]
        signal_grouped_net_file.parent.mkdir(parents=True, exist_ok=True)
        signal_grouped_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_signal_grouping_status": "variant_created_for_review",
            "tls_signal_grouping_variant_file": str(signal_grouped_net_file),
            "tls_signal_grouping_merged_group_count": kwargs["max_shared_linkindex_groups"],
            "warnings": [],
        }

    def fake_command_runner(command, **_kwargs):
        calls["signal_grouping_sumo_command"] = command
        return {"status": "pass", "returncode": 0, "stdout": "", "stderr": ""}

    raw_visual_detail_net_file = tmp_path / "sumo" / "reference-signal_reference_visual_detail.net.xml"

    def fake_reference_join_audit(**kwargs):
        candidate_net_file = Path(kwargs["candidate_net_file"])
        output_dir = str(kwargs["output_dir"])
        if candidate_net_file == visual_tls_net_file and "tls_aggregation_reference_delta" in output_dir:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_missing_counts": {
                    "tls_controlled_connection_count": 160,
                    "tls_shared_linkindex_group_count": 40,
                },
                "network_structural_extra_counts": {"traffic_light_junction_count": 46, "tl_logic_count": 41},
                "summary_file": str(tmp_path / "aggregation_delta.json"),
                "warnings": [],
            }
        if candidate_net_file == raw_visual_detail_net_file and "raw_reference_delta" in output_dir:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_missing_counts": {"tls_shared_linkindex_group_count": 40},
                "network_structural_extra_counts": {"traffic_light_junction_count": 354},
                "summary_file": str(tmp_path / "raw_delta.json"),
                "warnings": [],
            }
        if candidate_net_file == signal_grouped_net_file and "tls_signal_grouping_reference_delta" in output_dir:
            calls["signal_grouping_delta_candidate_net_file"] = kwargs["candidate_net_file"]
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_missing_counts": {"tls_controlled_connection_count": 160},
                "network_structural_extra_counts": {
                    "traffic_light_junction_count": 46,
                    "tl_logic_count": 41,
                    "multi_junction_tl_logic_count": 5,
                    "tls_sparse_linkindex_tl_logic_count": 3,
                },
                "summary_file": str(tmp_path / "signal_grouping_delta.json"),
                "warnings": [],
            }
        calls["reference_join_candidate_net_file"] = kwargs["candidate_net_file"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "structural_only",
            "network_structural_missing_counts": {"tls_controlled_connection_count": 160},
            "network_structural_extra_counts": {
                "traffic_light_junction_count": 46,
                "tl_logic_count": 41,
                "multi_junction_tl_logic_count": 5,
                "tls_sparse_linkindex_tl_logic_count": 3,
            },
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-signal",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        tls_signal_grouping_func=fake_signal_grouping,
        command_runner=fake_command_runner,
        tls_connection_repair_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("signal grouping promotion should skip TLS repair")
        ),
        connectivity_func=lambda _path: {"status": "pass", "connectivity_status": "pass", "warnings": []},
        topology_audit_func=lambda **_kwargs: {"status": "pass", "topology_fragmentation_status": "pass", "warnings": []},
        routeability_audit_func=lambda **_kwargs: {"status": "pass", "routeability_status": "pass", "warnings": []},
        netedit_func=lambda _path: {"status": "blocked", "netedit_status": "skipped", "warnings": []},
        sumo_gui_func=lambda _path, **_kwargs: {"status": "blocked", "sumo_gui_status": "skipped", "warnings": []},
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structural-only audit should not trigger aggregation")
        ),
        teacher_guided_repair_queue_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structural-only audit should not trigger teacher queue")
        ),
    )

    assert calls["signal_grouping_max_shared_linkindex_groups"] == 40
    assert calls["tls_aggregation_guess_signal_dists"] == [35.0, 20.0, None]
    assert calls["signal_grouping_sumo_command"][0] == "sumo"
    assert calls["signal_grouping_delta_candidate_net_file"] == signal_grouped_net_file
    assert calls["reference_join_candidate_net_file"] == signal_grouped_net_file
    assert report["reference_visual_detail_comparison_net_file"] == str(signal_grouped_net_file)
    assert report["reference_visual_detail_comparison_selection_reason"] == (
        "tls_signal_grouping_promoted_by_reference_delta"
    )
    assert report["reference_visual_detail_tls_signal_grouping_reference_promotion_status"] == "pass"
    assert report["reference_visual_detail_tls_signal_grouping_sumo_load_status"] == "pass"
    assert report["reference_visual_detail_tls_signal_grouping_reference_tls_semantic_delta_score"] == 255
    assert report["reference_join_tls_semantic_delta_score"] == 255


def test_reference_matched_workflow_runs_reference_scope_audit_without_default_pruning_variant(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-scope_filtered.osm.xml.gz"
    visual_tls_net_file = tmp_path / "tls_aggregation" / "reference_visual_detail_tls.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_tls(**kwargs):
        net_file = Path(kwargs["net_file"])
        if "reference_visual_detail" in net_file.name:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "tls_candidate_count": 2,
                "tls_cluster_count": 1,
                "clusters_file": str(tmp_path / "visual_tls_clusters.csv"),
                "warnings": [],
            }
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        }

    def fake_tls_aggregation(**kwargs):
        visual_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        visual_tls_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_aggregation_variant_file": str(visual_tls_net_file),
            "warnings": [],
        }

    def fake_reference_scope_audit(**kwargs):
        calls["scope_reference_net_file"] = kwargs["reference_net_file"]
        calls["scope_candidate_net_file"] = kwargs["candidate_net_file"]
        return {
            "status": "blocked",
            "claim_status": "blocked",
            "reference_scope_status": "needs_pruning_review",
            "prune_candidate_count": 4,
            "report_file": str(tmp_path / "scope_audit.json"),
            "prune_candidates_file": str(tmp_path / "scope_candidates.csv"),
            "warnings": ["reference scope audit found 4 prune candidate edge(s)"],
        }

    def fake_scope_pruning(**kwargs):
        raise AssertionError("scope pruning variant should require an explicit workflow opt-in")

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-scope",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 100,
            "passenger_component_count": 1,
            "largest_component_edge_count": 100,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        reference_join_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "reference_case_count": 0,
            "matched_case_count": 0,
            "unmatched_case_count": 0,
            "warnings": [],
        },
        reference_join_aggregation_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_aggregation_status": "not_needed",
            "junction_aggregation_candidate_count": 0,
            "warnings": [],
        },
        reference_scope_audit_func=fake_reference_scope_audit,
        scope_pruning_func=fake_scope_pruning,
    )

    assert calls["scope_reference_net_file"] == reference_net_file
    assert calls["scope_candidate_net_file"] == visual_tls_net_file
    assert report["reference_scope_status"] == "needs_pruning_review"
    assert report["reference_scope_prune_candidate_count"] == 4
    assert report["reference_scope_pruning_status"] == "skipped"
    assert report["reference_scope_pruning_variant_file"] == ""
    assert report["gate_status"]["reference_scope_audit"] == "blocked"
    assert report["gate_status"]["reference_scope_pruning"] == "skipped"


def test_reference_matched_workflow_runs_reference_hierarchy_audit_on_visual_detail_layer(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-hierarchy_filtered.osm.xml.gz"
    visual_tls_net_file = tmp_path / "tls_aggregation" / "reference_visual_detail_tls.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_tls(**kwargs):
        net_file = Path(kwargs["net_file"])
        if "reference_visual_detail" in net_file.name:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "tls_candidate_count": 2,
                "tls_cluster_count": 1,
                "clusters_file": str(tmp_path / "visual_tls_clusters.csv"),
                "warnings": [],
            }
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        }

    def fake_tls_aggregation(**_kwargs):
        visual_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        visual_tls_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_aggregation_variant_file": str(visual_tls_net_file),
            "warnings": [],
        }

    def fake_reference_hierarchy_audit(**kwargs):
        calls["hierarchy_reference_net_file"] = kwargs["reference_net_file"]
        calls["hierarchy_candidate_net_file"] = kwargs["candidate_net_file"]
        return {
            "status": "blocked",
            "claim_status": "blocked",
            "reference_hierarchy_status": "needs_review",
            "high_hierarchy_issue_count": 5,
            "decision_counts": {"matched_but_oversplit": 3, "out_of_reference_scope": 2},
            "corridor_match_basis_counts": {"same_name": 2, "same_type_distance": 3},
            "same_name_match_status_counts": {"matched_by_name": 4, "no_same_name_reference": 1},
            "cases_file": str(tmp_path / "hierarchy_cases.csv"),
            "type_comparison_file": str(tmp_path / "hierarchy_types.csv"),
            "summary_file": str(tmp_path / "hierarchy_summary.json"),
            "warnings": ["reference hierarchy audit found 5 high-road review case(s)"],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-hierarchy",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 100,
            "passenger_component_count": 1,
            "largest_component_edge_count": 100,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        reference_scope_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "reference_scope_status": "pass",
            "prune_candidate_count": 0,
            "warnings": [],
        },
        reference_join_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "reference_case_count": 0,
            "matched_case_count": 0,
            "unmatched_case_count": 0,
            "warnings": [],
        },
        reference_join_aggregation_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_aggregation_status": "not_needed",
            "junction_aggregation_candidate_count": 0,
            "warnings": [],
        },
        reference_hierarchy_audit_func=fake_reference_hierarchy_audit,
    )

    assert calls["hierarchy_reference_net_file"] == reference_net_file
    assert calls["hierarchy_candidate_net_file"] == visual_tls_net_file
    assert report["reference_hierarchy_status"] == "needs_review"
    assert report["reference_hierarchy_issue_count"] == 5
    assert report["reference_hierarchy_audit_candidate_layer"] == "reference_visual_detail"
    assert report["reference_hierarchy_audit_candidate_net_file"] == str(visual_tls_net_file)
    assert report["reference_hierarchy_decision_counts"] == {
        "matched_but_oversplit": 3,
        "out_of_reference_scope": 2,
    }
    assert report["reference_hierarchy_corridor_match_basis_counts"] == {
        "same_name": 2,
        "same_type_distance": 3,
    }
    assert report["reference_hierarchy_same_name_match_status_counts"] == {
        "matched_by_name": 4,
        "no_same_name_reference": 1,
    }
    assert report["reference_hierarchy_cases_file"] == str(tmp_path / "hierarchy_cases.csv")
    assert report["gate_status"]["reference_hierarchy_audit"] == "blocked"


def test_reference_matched_workflow_derives_bbox_from_reference_geometry(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    derived_bbox = "11.413800,48.755391,11.433800,48.775391"
    build_calls: list[dict[str, object]] = []

    def fake_build(**kwargs):
        build_calls.append({"bbox": kwargs["bbox"], "prefix": kwargs["prefix"]})
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        source_osm_file = tmp_path / "osm" / f"{kwargs['prefix']}.osm.xml.gz"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        source_osm_file.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text(
            """<net>
    <edge id="primary_a" type="highway.primary">
        <lane id="primary_a_0" index="0" allow="passenger" speed="13.9" length="25.0"/>
    </edge>
</net>""",
            encoding="utf-8",
        )
        source_osm_file.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(source_osm_file),
            "source_osm_file": str(source_osm_file),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        output_dir=tmp_path,
        prefix="reference-derived-bbox",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        reference_bbox_func=lambda _path: {
            "status": "pass",
            "reference_bbox_status": "derived_from_reference_geometry",
            "reference_bbox": derived_bbox,
            "reference_bbox_source": "junction_geometry",
            "reference_bbox_padding_m": 75.0,
            "warnings": [],
        },
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        },
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 1,
            "passenger_component_count": 1,
            "largest_component_edge_count": 1,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
    )

    assert report["status"] == "pass"
    assert report["area_input"] == derived_bbox
    assert report["candidate_bbox"] == derived_bbox
    assert report["reference_bbox_status"] == "derived_from_reference_geometry"
    assert report["reference_bbox"] == derived_bbox
    assert report["reference_bbox_source"] == "junction_geometry"
    assert report["reference_bbox_padding_m"] == 75.0
    assert build_calls[0]["bbox"] == derived_bbox


def test_reference_matched_workflow_prefers_reference_bbox_over_place_resolution(
    tmp_path: Path,
) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    derived_bbox = "11.4062777,48.7483625,11.4382247,48.7803406"
    build_calls: list[dict[str, object]] = []

    def fake_build(**kwargs):
        build_calls.append({"bbox": kwargs["bbox"]})
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        source_osm_file = tmp_path / "osm" / f"{kwargs['prefix']}.osm.xml.gz"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        source_osm_file.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text(
            """<net>
    <edge id="primary_a" type="highway.primary">
        <lane id="primary_a_0" index="0" allow="passenger" speed="13.9" length="25.0"/>
    </edge>
</net>""",
            encoding="utf-8",
        )
        source_osm_file.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(source_osm_file),
            "source_osm_file": str(source_osm_file),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        place_name="Ingolstadt city center",
        output_dir=tmp_path,
        prefix="reference-place-derived-bbox",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        place_resolver=lambda _place: (_ for _ in ()).throw(AssertionError("place resolver should not run")),
        reference_bbox_func=lambda _path: {
            "status": "pass",
            "reference_bbox_status": "derived_from_reference_geometry",
            "reference_bbox": derived_bbox,
            "reference_bbox_source": "junction_geometry",
            "reference_bbox_padding_m": 75.0,
            "warnings": [],
        },
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {"status": "pass", "tls_candidate_count": 0, "warnings": []},
        connectivity_func=lambda _path: {"status": "pass", "connectivity_status": "pass", "warnings": []},
        topology_audit_func=lambda **_kwargs: {"status": "pass", "topology_fragmentation_status": "pass", "warnings": []},
        routeability_audit_func=lambda **_kwargs: {"status": "pass", "routeability_status": "pass", "warnings": []},
        netedit_func=lambda _path: {"status": "blocked", "netedit_status": "skipped", "warnings": []},
        sumo_gui_func=lambda _path, **_kwargs: {"status": "blocked", "sumo_gui_status": "skipped", "warnings": []},
    )

    assert report["status"] == "pass"
    assert report["area_input"] == "Ingolstadt city center"
    assert report["candidate_bbox"] == derived_bbox
    assert report["reference_bbox_status"] == "derived_from_reference_geometry"
    assert build_calls[0]["bbox"] == derived_bbox

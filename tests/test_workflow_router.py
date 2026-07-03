from pathlib import Path

from torii_sumo.core.workflow_router import (
    detect_workflow,
    infer_place_name,
    run_auto_workflow,
)
from torii_sumo.tools.workflow_tools import torii_auto_workflow
from torii_sumo.core.osm_network import parse_bbox


def _write_reference_net(path: Path) -> None:
    path.write_text(
        """<net>
    <edge id="primary_a" type="highway.primary">
        <lane id="primary_a_0" index="0" allow="passenger bus" speed="13.9" length="25.0"/>
    </edge>
    <edge id="service_a" type="highway.service">
        <lane id="service_a_0" index="0" allow="delivery passenger" speed="5.0" length="25.0"/>
    </edge>
    <edge id="cycle_a" type="highway.cycleway">
        <lane id="cycle_a_0" index="0" allow="bicycle" speed="5.0" length="25.0"/>
    </edge>
</net>""",
        encoding="utf-8",
    )


def test_infer_place_name_from_one_prompt_osm_request() -> None:
    request = "Use Torii to download the Altstadt map in Dresden from OSM, clean it up and open it in SUMO"

    assert infer_place_name(request) == "Altstadt, Dresden"


def test_detect_workflow_routes_common_one_sentence_requests() -> None:
    assert detect_workflow("download the Altstadt map from OSM and open it in SUMO") == "osm_to_sumo"
    assert detect_workflow("generate a TUM-like SUMO network from OSM with TLS and connection semantics") == "osm_to_sumo"
    assert (
        detect_workflow(
            "clean the Ingolstadt city-center network from OSM, compare it with the TUM cleaned network, and open it in Netedit"
        )
        == "osm_to_sumo"
    )
    assert detect_workflow("audit the traffic lights in this SUMO network") == "tls_review"
    assert detect_workflow("create a TLS audit for this SUMO network") == "tls_review"
    assert detect_workflow("create an HTML review cockpit for this partial SUMO network") == "network_review"
    assert detect_workflow("check whether this route from station to museum is connected") == "routeability"
    assert detect_workflow("my waiting time got worse after cleanup") == "debug_bad_run"
    assert detect_workflow("compare fixed-time and max-pressure controllers") == "experiment_audit"


def test_auto_workflow_blocks_osm_place_until_area_confirmation(tmp_path: Path) -> None:
    def fake_resolver(_place_name: str):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "area_resolution_status": "candidate_found",
            "candidate_display_name": "Altstadt, Dresden, Sachsen, Deutschland",
            "candidate_osm_type": "relation",
            "candidate_osm_id": "192900",
            "candidate_bbox": "13.6864402,51.0280799,13.7872926,51.0766681",
            "osm_preview_url": "https://www.openstreetmap.org/search?query=Altstadt%2C+Dresden",
            "candidate_osm_url": "https://www.openstreetmap.org/relation/192900",
            "warnings": [],
        }

    report = run_auto_workflow(
        user_request="Use Torii to download the Altstadt map in Dresden from OSM, clean it up and open it in SUMO",
        output_dir=tmp_path,
        autonomy_mode="ask-first",
        place_resolver=fake_resolver,
    )

    assert report["status"] == "blocked"
    assert report["claim_status"] == "blocked"
    assert report["detected_workflow"] == "osm_to_sumo"
    assert report["execution_status"] == "needs_user_confirmation"
    assert report["inferred_place_name"] == "Altstadt, Dresden"
    assert report["candidate_bbox"] == "13.6864402,51.0280799,13.7872926,51.0766681"
    assert report["next_question"] == "Confirm this OSM area and bbox before network construction?"
    assert report["tool_chain"][:2] == ["sumo_osm_resolve_place", "sumo_osm_cleanup_workflow"]


def test_auto_workflow_safe_autopilot_uses_resolved_bbox_without_confirmation(tmp_path: Path) -> None:
    captured = {}

    def fake_resolver(_place_name: str):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "area_resolution_status": "candidate_found",
            "candidate_display_name": "Altstadt, Dresden, Sachsen, Deutschland",
            "candidate_osm_type": "relation",
            "candidate_osm_id": "192900",
            "candidate_bbox": "13.6864402,51.0280799,13.7872926,51.0766681",
            "osm_preview_url": "https://www.openstreetmap.org/search?query=Altstadt%2C+Dresden",
            "candidate_osm_url": "https://www.openstreetmap.org/relation/192900",
            "warnings": [],
        }

    def fake_cleanup(**kwargs):
        captured.update(kwargs)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "net_file": str(tmp_path / "resolved.net.xml"),
            "warnings": ["regional map/TLS reality evidence still needs manual strengthening"],
        }

    report = run_auto_workflow(
        user_request="Use Torii to download the Altstadt map in Dresden from OSM, clean it up and open it in SUMO",
        output_dir=tmp_path,
        highway_classes="arterial",
        teacher_guided_repair_max_ready_candidates=1,
        run_teacher_guided_repair_after_build=False,
        place_resolver=fake_resolver,
        cleanup_workflow_func=fake_cleanup,
    )

    assert report["status"] == "pass"
    assert report["execution_status"] == "executed"
    assert report["tool_called"] == "sumo_osm_cleanup_workflow"
    assert captured["bbox"] == "13.6864402,51.0280799,13.7872926,51.0766681"
    assert captured["place_name"] == "Altstadt, Dresden"
    assert {"primary", "tertiary"} <= captured["highway_classes"]
    assert captured["run_routeability_audit_after_build"] is True
    assert captured["teacher_guided_repair_max_ready_candidates"] == 1
    assert captured["run_teacher_guided_repair_after_build"] is False
    assert report["area_resolution_status"] == "candidate_found"


def test_auto_workflow_extracts_bbox_from_osm_map_url(tmp_path: Path) -> None:
    captured = {}

    def fake_cleanup(**kwargs):
        captured.update(kwargs)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "workflow_review_html_status": "pass",
            "workflow_review_html_file": str(tmp_path / "workflow_review.html"),
        }

    report = run_auto_workflow(
        user_request=(
            "Use Torii-SUMO workflow from "
            "https://www.openstreetmap.org/#map=18/48.768610/11.422681 "
            "to generate a SUMO network"
        ),
        output_dir=tmp_path,
        highway_classes="arterial",
        cleanup_workflow_func=fake_cleanup,
    )

    parsed = parse_bbox(captured["bbox"])
    assert report["status"] == "pass"
    assert report["tool_called"] == "sumo_osm_cleanup_workflow"
    assert report["area_resolution_status"] == "osm_map_url_bbox"
    assert parsed.west < 11.422681 < parsed.east
    assert parsed.south < 48.768610 < parsed.north
    assert captured["place_name"] is None


def test_auto_workflow_prefers_explicit_bbox_over_prompt_osm_url(tmp_path: Path) -> None:
    captured = {}
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)

    def fake_cleanup(**kwargs):
        captured.update(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo"}

    report = run_auto_workflow(
        user_request=(
            "Use Torii to clean the Ingolstadt city-center network around "
            "https://www.openstreetmap.org/#map=17/48.765391/11.423800 from OSM"
        ),
        output_dir=tmp_path,
        bbox="11.413800,48.755391,11.433800,48.775391",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        cleanup_workflow_func=fake_cleanup,
    )

    assert report["status"] == "pass"
    assert captured["bbox"] == "11.413800,48.755391,11.433800,48.775391"


def test_auto_workflow_can_disable_gui_launches_for_headless_reference_promotion(tmp_path: Path) -> None:
    captured = {}
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)

    def fake_cleanup(**kwargs):
        captured.update(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo"}

    report = run_auto_workflow(
        user_request="Use Torii to generate a TUM-like SUMO network from OSM using the reference net",
        output_dir=tmp_path,
        bbox="11.413800,48.755391,11.433800,48.775391",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        launch_netedit_after_build=False,
        launch_sumo_gui_after_build=False,
        cleanup_workflow_func=fake_cleanup,
    )

    assert report["status"] == "pass"
    assert captured["launch_netedit_after_build"] is False
    assert captured["launch_sumo_gui_after_build"] is False


def test_auto_workflow_passes_local_osm_file_to_cleanup(tmp_path: Path) -> None:
    captured = {}
    reference_net_file = tmp_path / "reference.net.xml"
    osm_file = tmp_path / "local.osm.xml"
    _write_reference_net(reference_net_file)
    osm_file.write_text("<osm/>", encoding="utf-8")

    def fake_cleanup(**kwargs):
        captured.update(kwargs)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "net_file": str(tmp_path / "local.net.xml"),
        }

    report = run_auto_workflow(
        user_request="Use Torii to generate a TUM-like SUMO network from this local OSM extract",
        output_dir=tmp_path,
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        osm_file=osm_file,
        cleanup_workflow_func=fake_cleanup,
    )

    assert report["status"] == "pass"
    assert report["execution_status"] == "executed"
    assert captured["source_osm_path"] == osm_file
    assert captured["bbox"] is None


def test_auto_workflow_routes_local_osm_intersection_patch_to_intersection_cleaner(tmp_path: Path) -> None:
    captured = {}
    osm_file = tmp_path / "intersection.osm.xml"
    osm_file.write_text("<osm/>", encoding="utf-8")

    def fake_cleanup(**_kwargs):
        raise AssertionError("full OSM cleanup must not run for a local intersection patch")

    def fake_intersection_clean(**kwargs):
        captured.update(kwargs)
        return {
            "status": "pass",
            "claim_status": "intersection-cleaned",
            "intersection_id": "core_1",
            "topology_type": "X4",
            "approach_count": 4,
            "movement_count": 12,
            "net_file": str(tmp_path / "intersection.net.xml"),
            "intersection_ir_file": str(tmp_path / "intersection_ir.json"),
            "validation_file": str(tmp_path / "validation.json"),
            "sumo_load_status": "pass",
            "route_probe_status": "skipped",
            "tls_linkindex_status": "pass",
            "missing_movement_count": 0,
            "disconnected_edge_count": 0,
            "internal_fragment_count": 1,
        }

    report = run_auto_workflow(
        user_request="Clean this local OSM intersection patch into a SUMO intersection net",
        output_dir=tmp_path,
        osm_file=osm_file,
        cleanup_workflow_func=fake_cleanup,
        intersection_clean_func=fake_intersection_clean,
    )

    assert report["status"] == "pass"
    assert report["detected_workflow"] == "intersection_clean"
    assert report["tool_called"] == "sumo_intersection_clean"
    assert report["execution_status"] == "executed"
    assert report["workflow_result"]["topology_type"] == "X4"
    assert report["sumo_load_status"] == "pass"
    assert report["tls_linkindex_status"] == "pass"
    assert report["missing_movement_count"] == 0
    assert report["workflow_stage_results"][0]["stage_name"] == "intersection_compile_validate"
    assert report["workflow_stage_results"][0]["after_quality"]["connectivity"]["disconnected_edge_count"] == 0
    assert report["workflow_promotion_trace"]["case_id"] == "intersection_clean"
    assert report["workflow_promotion_trace"]["stages"][0]["promotion_decision"] == "pass"
    assert captured["osm_file"] == osm_file
    assert captured["output_dir"] == tmp_path
    assert captured["compile_net"] is True


def test_auto_workflow_blocks_intersection_clean_without_local_osm_patch(tmp_path: Path) -> None:
    report = run_auto_workflow(
        user_request="Clean this local OSM intersection patch into a SUMO intersection net",
        output_dir=tmp_path,
    )

    assert report["status"] == "blocked"
    assert report["detected_workflow"] == "intersection_clean"
    assert report["execution_status"] == "needs_osm_intersection_patch"
    assert report["missing_blockers"] == ["osm_file"]


def test_auto_workflow_blocks_osm_generation_until_road_level_scope_selected(tmp_path: Path) -> None:
    def fake_resolver(_place_name: str):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "area_resolution_status": "candidate_found",
            "candidate_display_name": "Altstadt, Dresden, Sachsen, Deutschland",
            "candidate_osm_type": "relation",
            "candidate_osm_id": "192900",
            "candidate_bbox": "13.6864402,51.0280799,13.7872926,51.0766681",
            "osm_preview_url": "https://www.openstreetmap.org/search?query=Altstadt%2C+Dresden",
            "candidate_osm_url": "https://www.openstreetmap.org/relation/192900",
            "warnings": [],
        }

    report = run_auto_workflow(
        user_request="Use Torii to download the Altstadt map in Dresden from OSM, clean it up and open it in SUMO",
        output_dir=tmp_path,
        place_resolver=fake_resolver,
    )

    assert report["status"] == "blocked"
    assert report["claim_status"] == "blocked"
    assert report["execution_status"] == "needs_network_plan"
    assert report["missing_blockers"] == ["network_plan"]
    assert "traffic layers" in report["next_question"]
    assert "reference_matched" in report["network_detail_options"]


def test_auto_workflow_blocks_reference_match_without_reference_artifact(tmp_path: Path) -> None:
    def fake_cleanup(**_kwargs):
        raise AssertionError("cleanup must not run without a reference network or policy report")

    report = run_auto_workflow(
        user_request="Use Torii to build this city-center SUMO network with the same layer policy as a manually cleaned reference network",
        output_dir=tmp_path,
        bbox="11.413800,48.755391,11.433800,48.775391",
        cleanup_workflow_func=fake_cleanup,
    )

    assert report["status"] == "blocked"
    assert report["execution_status"] == "needs_network_plan"
    assert report["network_plan_status"] == "needs_reference_artifact"
    assert report["missing_blockers"] == ["reference_network_or_policy"]


def test_auto_workflow_uses_reference_net_file_for_reference_matched_plan(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "manual-reference.net.xml"
    _write_reference_net(reference_net_file)
    captured = {}

    def fake_cleanup(**kwargs):
        captured.update(kwargs)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "network_profile": "reference_matched",
            "service_passenger_policy": "reference_match",
            "routeability_audit_status": "pass",
        }

    report = run_auto_workflow(
        user_request="Use Torii to build this city-center SUMO network with the same layer policy as a manually cleaned reference network",
        output_dir=tmp_path,
        bbox="11.413800,48.755391,11.433800,48.775391",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        cleanup_workflow_func=fake_cleanup,
    )

    assert report["status"] == "pass"
    assert report["execution_status"] == "executed"
    assert captured["network_profile"] == "reference_matched"
    assert captured["reference_net_file"] == reference_net_file
    assert captured["service_passenger_policy"] == "reference_match"
    assert captured["reference_join_audit_structural_only"] is False
    assert "service" not in captured["highway_classes"]
    assert "cycleway" not in captured["highway_classes"]


def test_auto_workflow_reference_match_does_not_pre_resolve_place_bbox(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "manual-reference.net.xml"
    _write_reference_net(reference_net_file)
    captured = {}

    def fake_cleanup(**kwargs):
        captured.update(kwargs)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "network_profile": "reference_matched",
            "candidate_bbox": "11.4062777,48.7483625,11.4382247,48.7803406",
            "reference_bbox_status": "derived_from_reference_geometry",
        }

    report = run_auto_workflow(
        user_request="Clean the Ingolstadt city-center network from OSM, compare it with the TUM cleaned network, and generate a TUM-like SUMO network",
        output_dir=tmp_path,
        place_name="Ingolstadt city center",
        reference_net_file=reference_net_file,
        place_resolver=lambda _place: (_ for _ in ()).throw(AssertionError("place resolver should not run")),
        cleanup_workflow_func=fake_cleanup,
    )

    assert report["status"] == "pass"
    assert report["network_plan"]["network_profile"] == "reference_matched"
    assert captured["bbox"] is None
    assert captured["place_name"] == "Ingolstadt city center"
    assert captured["network_profile"] == "reference_matched"
    assert captured["reference_net_file"] == reference_net_file


def test_torii_auto_workflow_uses_cleanup_tool_wrapper(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_run_auto_workflow(**kwargs):
        captured.update(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo"}

    monkeypatch.setattr("torii_sumo.tools.workflow_tools.run_auto_workflow", fake_run_auto_workflow)

    report = torii_auto_workflow(
        user_request="Generate a TUM-like SUMO network from OSM using the reference net",
        output_dir=str(tmp_path),
        bbox="11.413800,48.755391,11.433800,48.775391",
        network_profile="reference_matched",
        reference_net_file=str(tmp_path / "reference.net.xml"),
        teacher_guided_repair_max_ready_candidates=2,
        run_teacher_guided_repair_after_build=False,
        road_connectivity_replay_max_owners=3,
        road_connectivity_probe_edge_ids=["road#0"],
        teacher_guided_probe_matrix_junction_ids=["j1", "j2"],
        launch_netedit_after_build=False,
        launch_sumo_gui_after_build=False,
    )

    assert report["status"] == "pass"
    assert captured["cleanup_workflow_func"].__name__ == "sumo_osm_cleanup_workflow"
    assert captured["teacher_guided_repair_max_ready_candidates"] == 2
    assert captured["run_teacher_guided_repair_after_build"] is False
    assert captured["road_connectivity_replay_max_owners"] == 3
    assert captured["road_connectivity_probe_edge_ids"] == ["road#0"]
    assert captured["teacher_guided_probe_matrix_junction_ids"] == ["j1", "j2"]
    assert captured["launch_netedit_after_build"] is False
    assert captured["launch_sumo_gui_after_build"] is False


def test_auto_workflow_exposes_reference_matched_semantics_chain(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "tum-reference.net.xml"
    _write_reference_net(reference_net_file)
    captured = {}

    def fake_cleanup(**kwargs):
        captured.update(kwargs)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "network_profile": "reference_matched",
            "reference_visual_detail_comparison_net_file": str(tmp_path / "teacher_guided_best.net.xml"),
            "teacher_guided_repair_best_variant_file": str(tmp_path / "teacher_guided_best.net.xml"),
            "teacher_guided_repair_run_report_file": str(tmp_path / "teacher_guided_run.json"),
            "teacher_guided_repair_run_status": "pass",
            "teacher_guided_repair_parity_gate_status": "pass",
            "teacher_guided_repair_promotion_gate_status": "pass",
            "teacher_guided_repair_promotion_gate_file": str(tmp_path / "teacher_guided_promotion_gate.json"),
            "teacher_guided_repair_application_scope": "single_best_variant",
            "teacher_guided_repair_applied_candidate_count": 1,
            "teacher_guided_repair_unapplied_pass_candidate_count": 4,
            "teacher_guided_probe_matrix_status": "pass",
            "teacher_guided_probe_matrix_file": str(tmp_path / "probe_matrix.json"),
            "teacher_guided_probe_matrix_probe_count": 2,
            "teacher_guided_probe_matrix_all_parity_gate_pass": True,
            "teacher_guided_probe_matrix_all_promotion_gate_pass": True,
            "teacher_guided_probe_matrix_all_road_continuity_gate_pass": True,
            "teacher_guided_probe_matrix_missing_junction_ids": [],
            "post_teacher_tls_connection_repair_movement_rebuild_run_status": "pass",
            "post_teacher_tls_connection_repair_movement_rebuild_parity_gate_status": "pass",
            "post_teacher_tls_connection_repair_movement_rebuild_best_variant_file": str(
                tmp_path / "movement_rebuild_best.net.xml"
            ),
            "post_teacher_tls_connection_repair_movement_rebuild_applied_candidate_count": 4,
            "final_movement_rebuild_run_status": "pass",
            "final_movement_rebuild_parity_gate_status": "pass",
            "final_movement_rebuild_sumo_load_status": "pass",
            "final_movement_rebuild_best_variant_file": str(tmp_path / "final_movement_best.net.xml"),
            "final_movement_rebuild_applied_candidate_count": 1,
            "final_movement_rebuild_semantic_layer_gate_counts": {
                "topology": {"pass": 1, "fail": 0, "failure_count": 0},
                "movement_tls": {"pass": 1, "fail": 0, "failure_count": 0},
                "pedestrian_bike": {"pass": 0, "fail": 1, "failure_count": 2},
            },
            "road_connectivity_replay_status": "pass",
            "road_connectivity_replay_gate_status": "pass",
            "road_connectivity_replay_sumo_load_status": "pass",
            "road_connectivity_replay_best_variant_file": str(tmp_path / "road_connectivity_best.net.xml"),
            "road_connectivity_replay_run_report_file": str(tmp_path / "road_connectivity_run.json"),
            "road_connectivity_replay_gate_counts": {
                "owner_road_connectivity": {"pass": 1, "fail": 0, "failure_count": 0},
            },
            "road_connectivity_seed_probe_status": "pass",
            "road_connectivity_seed_probe_file": str(tmp_path / "road_seed.json"),
            "road_connectivity_seed_probe_edge_delta_count": 0,
            "road_connectivity_seed_probe_connection_delta_count": 0,
            "road_connectivity_seed_probe_candidate_missing_seed_edge_ids": [],
            "road_connectivity_split_root_alias_repair_status": "pass",
            "road_connectivity_split_root_alias_repair_file": str(tmp_path / "road_connectivity_alias.net.xml"),
            "road_connectivity_split_root_alias_repair_report_file": str(tmp_path / "road_connectivity_alias.json"),
            "road_connection_topology_replay_status": "pass",
            "road_connection_topology_replay_file": str(tmp_path / "road_connection_topology.net.xml"),
            "road_connection_topology_replay_report_file": str(tmp_path / "road_connection_topology.json"),
            "workflow_review_html_status": "pass",
            "workflow_review_html_file": str(tmp_path / "workflow_review.html"),
            "workflow_report_file": str(tmp_path / "workflow_report.json"),
            "review_manifest_file": str(tmp_path / "review_manifest.json"),
            "reference_join_post_teacher_audit_status": "pass",
            "routeability_audit_status": "pass",
            "reference_join_audit": {"junction_pattern_index": [{"junction_id": "cluster_a_b"}]},
            "gate_status": {
                "reference_join_audit": "pass",
                "reference_join_aggregation": "blocked",
                "netedit_connection_mode_review": "blocked",
                "netedit": "blocked",
            },
        }

    report = run_auto_workflow(
        user_request="Use Torii to generate a TUM-like SUMO network from OSM and mimic the manually cleaned reference connection and TLS semantics",
        output_dir=tmp_path,
        bbox="11.413800,48.755391,11.433800,48.775391",
        reference_net_file=reference_net_file,
        teacher_guided_repair_max_ready_candidates=1,
        road_connectivity_replay_max_owners=3,
        road_connectivity_probe_edge_ids=["road#0"],
        teacher_guided_probe_matrix_junction_ids=["j1", "j2"],
        cleanup_workflow_func=fake_cleanup,
    )

    assert report["status"] == "pass"
    assert report["network_plan"]["network_profile"] == "reference_matched"
    assert "sumo_network_reference_join_audit" in report["tool_chain"]
    assert "sumo_network_junction_aggregation_variant" in report["tool_chain"]
    assert "sumo_network_teacher_guided_repair_queue" in report["tool_chain"]
    assert "sumo_network_teacher_guided_junction_variant" in report["tool_chain"]
    assert "sumo_network_tls_warning_parity" in report["tool_chain"]
    assert report["reference_matched_semantics_workflow"]["claim_status"] == "diagnostic-demo"
    assert report["reference_matched_semantics_workflow"]["batch_repair_tool"] == "sumo_network_teacher_guided_repair_queue"
    assert report["reference_matched_semantics_workflow"]["per_junction_repair_tool"] == "sumo_network_teacher_guided_junction_variant"
    assert (
        report["reference_matched_semantics_workflow"]["warning_parity_tool"]
        == "sumo_network_tls_warning_parity"
    )
    assert report["reference_matched_semantics_workflow"]["best_variant_file"] == str(tmp_path / "final_movement_best.net.xml")
    assert report["reference_matched_semantics_workflow"]["comparison_net_file"] == str(
        tmp_path / "final_movement_best.net.xml"
    )
    assert report["reference_matched_semantics_workflow"]["movement_rebuild_best_variant_file"] == str(
        tmp_path / "final_movement_best.net.xml"
    )
    assert report["reference_matched_semantics_workflow"]["movement_rebuild_applied_candidate_count"] == 1
    assert report["reference_matched_semantics_workflow"]["configured_max_ready_candidates"] == 1
    assert captured["road_connectivity_replay_max_owners"] == 3
    assert captured["road_connectivity_probe_edge_ids"] == ["road#0"]
    assert captured["teacher_guided_probe_matrix_junction_ids"] == ["j1", "j2"]
    assert report["teacher_guided_repair_configured_max_ready_candidates"] == 1
    assert report["reference_matched_semantics_workflow"]["probe_matrix"] == {
        "status": "pass",
        "matrix_file": str(tmp_path / "probe_matrix.json"),
        "probe_count": 2,
        "all_parity_gate_pass": True,
        "all_promotion_gate_pass": True,
        "all_road_continuity_gate_pass": True,
        "missing_junction_ids": [],
    }
    assert report["reference_matched_semantics_workflow"]["semantic_layer_gate_counts"] == {
        "topology": {"pass": 1, "fail": 0, "failure_count": 0},
        "movement_tls": {"pass": 1, "fail": 0, "failure_count": 0},
        "pedestrian_bike": {"pass": 0, "fail": 1, "failure_count": 2},
    }
    assert report["reference_matched_semantics_workflow"]["road_connectivity_layer"] == {
        "run_status": "pass",
        "gate_status": "pass",
        "sumo_load_status": "pass",
        "best_variant_file": str(tmp_path / "road_connection_topology.net.xml"),
        "owner_replay_variant_file": str(tmp_path / "road_connectivity_best.net.xml"),
        "split_root_alias_repair_file": str(tmp_path / "road_connectivity_alias.net.xml"),
        "topology_replay_file": str(tmp_path / "road_connection_topology.net.xml"),
        "run_report_file": str(tmp_path / "road_connectivity_run.json"),
        "gate_counts": {
            "owner_road_connectivity": {"pass": 1, "fail": 0, "failure_count": 0},
        },
    }
    assert report["reference_matched_semantics_workflow"]["road_connectivity_seed_probe"] == {
        "status": "pass",
        "report_file": str(tmp_path / "road_seed.json"),
        "edge_delta_count": 0,
        "connection_delta_count": 0,
        "candidate_missing_seed_edge_ids": [],
    }
    assert report["reference_matched_semantics_workflow"]["road_connectivity_split_root_alias_repair"] == {
        "status": "pass",
        "output_file": str(tmp_path / "road_connectivity_alias.net.xml"),
        "report_file": str(tmp_path / "road_connectivity_alias.json"),
    }
    assert report["reference_matched_semantics_workflow"]["road_connection_topology_replay"] == {
        "status": "pass",
        "output_file": str(tmp_path / "road_connection_topology.net.xml"),
        "report_file": str(tmp_path / "road_connection_topology.json"),
    }
    assert report["reference_matched_semantics_workflow"]["run_report_file"] == str(tmp_path / "teacher_guided_run.json")
    assert report["reference_matched_semantics_workflow"]["promotion_gate_status"] == "pass"
    assert report["reference_matched_semantics_workflow"]["promotion_gate_file"] == str(
        tmp_path / "teacher_guided_promotion_gate.json"
    )
    assert report["reference_matched_semantics_workflow"]["application_scope"] == "single_best_variant"
    assert report["reference_matched_semantics_workflow"]["applied_candidate_count"] == 1
    assert report["reference_matched_semantics_workflow"]["unapplied_pass_candidate_count"] == 4
    assert report["workflow_review_html_status"] == "pass"
    assert report["workflow_review_html_file"] == str(tmp_path / "workflow_review.html")
    assert report["workflow_report_file"] == str(tmp_path / "workflow_report.json")
    assert report["review_manifest_file"] == str(tmp_path / "review_manifest.json")
    assert report["teacher_guided_repair_run_status"] == "pass"
    assert report["teacher_guided_repair_parity_gate_status"] == "pass"
    assert report["teacher_guided_repair_promotion_gate_status"] == "pass"
    assert report["teacher_guided_repair_promotion_gate_file"] == str(tmp_path / "teacher_guided_promotion_gate.json")
    assert report["teacher_guided_repair_application_scope"] == "single_best_variant"
    assert report["teacher_guided_repair_best_variant_file"] == str(tmp_path / "teacher_guided_best.net.xml")
    assert report["teacher_guided_repair_run_report_file"] == str(tmp_path / "teacher_guided_run.json")
    assert report["post_teacher_tls_connection_repair_movement_rebuild_run_status"] == "pass"
    assert report["post_teacher_tls_connection_repair_movement_rebuild_parity_gate_status"] == "pass"
    assert report["post_teacher_tls_connection_repair_movement_rebuild_best_variant_file"] == str(
        tmp_path / "movement_rebuild_best.net.xml"
    )
    assert report["post_teacher_tls_connection_repair_movement_rebuild_applied_candidate_count"] == 4
    assert report["final_movement_rebuild_sumo_load_status"] == "pass"
    assert report["final_movement_rebuild_semantic_layer_gate_counts"]["pedestrian_bike"]["failure_count"] == 2
    assert report["road_connectivity_replay_gate_status"] == "pass"
    assert report["reference_join_post_teacher_audit_status"] == "pass"
    assert report["routeability_audit_status"] == "pass"
    stage_results = {stage["stage_name"]: stage for stage in report["workflow_stage_results"]}
    assert list(stage_results) == [
        "reference_comparison",
        "teacher_guided_repair",
        "road_connectivity",
        "routeability",
        "review_html",
    ]
    assert stage_results["teacher_guided_repair"]["promotion_decision"] == "pass"
    assert stage_results["teacher_guided_repair"]["output_artifacts"]["best_variant"] == str(
        tmp_path / "teacher_guided_best.net.xml"
    )
    assert (
        stage_results["road_connectivity"]["after_quality"]["connectivity"]["road_connectivity_replay_gate_status"]
        == "pass"
    )
    assert stage_results["routeability"]["after_quality"]["routeability"] == {"status": "pass"}
    promotion_trace = report["workflow_promotion_trace"]
    assert promotion_trace["case_id"] == "reference_matched"
    assert promotion_trace["claim_status"] == "diagnostic-demo"
    assert [stage["stage_id"] for stage in promotion_trace["stages"]] == list(stage_results)
    assert promotion_trace["stages"][1]["promotion_decision"] == "pass"
    assert "netedit_connection_mode_review" in report["reference_matched_semantics_workflow"]["required_manual_reviews"]
    assert "netedit_connection_mode" not in report["reference_matched_semantics_workflow"]["required_manual_reviews"]
    assert "connection_semantics_parity" in report["network_plan"]["validation_gates"]
    assert "road_connectivity_parity" in report["network_plan"]["validation_gates"]
    assert "tls_semantics_parity" in report["network_plan"]["validation_gates"]
    assert "internal_junction_parity" in report["network_plan"]["validation_gates"]


def test_auto_workflow_keeps_road_only_variant_in_road_layer(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "tum-reference.net.xml"
    _write_reference_net(reference_net_file)
    raw_net_file = tmp_path / "raw_visual.net.xml"
    road_net_file = tmp_path / "road_connectivity.net.xml"

    def fake_cleanup(**_kwargs):
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "network_profile": "reference_matched",
            "reference_visual_detail_comparison_net_file": str(raw_net_file),
            "road_connectivity_replay_status": "pass",
            "road_connectivity_replay_gate_status": "pass",
            "road_connectivity_replay_sumo_load_status": "pass",
            "road_connectivity_replay_best_variant_file": str(road_net_file),
            "road_connectivity_seed_probe_status": "pass",
            "road_connectivity_seed_probe_edge_delta_count": 0,
            "road_connectivity_seed_probe_connection_delta_count": 0,
        }

    report = run_auto_workflow(
        user_request="Use Torii to generate a TUM-like SUMO network from OSM with TLS and connection semantics",
        output_dir=tmp_path,
        bbox="11.413800,48.755391,11.433800,48.775391",
        reference_net_file=reference_net_file,
        cleanup_workflow_func=fake_cleanup,
    )

    semantics = report["reference_matched_semantics_workflow"]
    assert semantics["best_variant_file"] == ""
    assert semantics["comparison_net_file"] == str(raw_net_file)
    assert semantics["road_connectivity_layer"]["best_variant_file"] == str(road_net_file)


def test_auto_workflow_can_call_tls_multisource_review(tmp_path: Path) -> None:
    calls = {}

    def fake_tls_review(**kwargs):
        calls.update(kwargs)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 2,
            "needs_manual_review_count": 2,
            "review_file": str(tmp_path / "review.csv"),
            "warnings": ["human review aid"],
        }

    report = run_auto_workflow(
        user_request="Audit the traffic lights in this SUMO network",
        output_dir=tmp_path,
        net_file=Path("network.net.xml"),
        osm_file=Path("network.osm.xml"),
        tls_review_func=fake_tls_review,
    )

    assert report["status"] == "pass"
    assert report["detected_workflow"] == "tls_review"
    assert report["execution_status"] == "executed"
    assert report["tool_called"] == "sumo_tls_multisource_review"
    assert calls["net_file"] == Path("network.net.xml")
    assert calls["osm_file"] == Path("network.osm.xml")


def test_auto_workflow_can_route_partial_network_to_review_html(tmp_path: Path) -> None:
    calls = {}

    def fake_review_html(**kwargs):
        calls.update(kwargs)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "workflow_review_html_status": "pass",
            "workflow_review_html_file": str(tmp_path / "partial_review.html"),
        }

    report = run_auto_workflow(
        user_request="Create an HTML review cockpit for this partial SUMO network",
        output_dir=tmp_path,
        net_file=Path("partial.net.xml"),
        review_html_func=fake_review_html,
    )

    assert report["status"] == "pass"
    assert report["detected_workflow"] == "network_review"
    assert report["execution_status"] == "executed"
    assert report["tool_called"] == "sumo_network_review_html"
    assert calls["net_file"] == Path("partial.net.xml")
    assert calls["title"] == "SUMO Network Review"


def test_auto_workflow_enables_routeability_audit_when_cleanup_supports_it(tmp_path: Path) -> None:
    captured = {}

    def fake_cleanup(**kwargs):
        captured.update(kwargs)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_audit_status": "pass",
        }

    report = run_auto_workflow(
        user_request="Build a SUMO network for Altstadt, Dresden from OSM",
        output_dir=tmp_path,
        bbox="13.6,50.9,13.9,51.1",
        highway_classes="arterial",
        cleanup_workflow_func=fake_cleanup,
    )

    assert report["status"] == "pass"
    assert {"primary", "tertiary"} <= captured["highway_classes"]
    assert captured["run_routeability_audit_after_build"] is True


def test_auto_workflow_keeps_legacy_cleanup_fake_compatible(tmp_path: Path) -> None:
    def fake_cleanup(output_dir, bbox, place_name, confirmed_area):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "received": {
                "output_dir": str(output_dir),
                "bbox": bbox,
                "place_name": place_name,
                "confirmed_area": confirmed_area,
            },
        }

    report = run_auto_workflow(
        user_request="Build a SUMO network for Altstadt, Dresden from OSM",
        output_dir=tmp_path,
        bbox="13.6,50.9,13.9,51.1",
        highway_classes="arterial",
        cleanup_workflow_func=fake_cleanup,
    )

    assert report["status"] == "pass"
    assert report["workflow_result"]["received"]["bbox"] == "13.6,50.9,13.9,51.1"


def test_auto_workflow_inspect_only_returns_plan_without_running_tools(tmp_path: Path) -> None:
    report = run_auto_workflow(
        user_request="Compare fixed-time and max-pressure controllers",
        output_dir=tmp_path,
        autonomy_mode="inspect-only",
    )

    assert report["status"] == "pass"
    assert report["detected_workflow"] == "experiment_audit"
    assert report["execution_status"] == "plan-only"
    assert report["tool_chain"] == ["sumo_config_pair_preflight", "sumo_compare_outputs", "sumo_collect_evidence"]

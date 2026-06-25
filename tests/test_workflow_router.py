from pathlib import Path

from torii_sumo.core.workflow_router import (
    detect_workflow,
    infer_place_name,
    run_auto_workflow,
)


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
    assert detect_workflow("audit the traffic lights in this SUMO network") == "tls_review"
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
    assert report["area_resolution_status"] == "candidate_found"


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
    assert "service" in captured["highway_classes"]
    assert "cycleway" not in captured["highway_classes"]


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

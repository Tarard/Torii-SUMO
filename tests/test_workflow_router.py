from pathlib import Path

from torii_sumo.core.workflow_router import (
    detect_workflow,
    infer_place_name,
    run_auto_workflow,
)


def test_infer_place_name_from_one_prompt_osm_request() -> None:
    request = "Use Torii to download the Altstadt map in Dresden from OSM, clean it up and open it in SUMO"

    assert infer_place_name(request) == "Altstadt, Dresden"


def test_detect_workflow_routes_common_one_sentence_requests() -> None:
    assert detect_workflow("download the Altstadt map from OSM and open it in SUMO") == "osm_to_sumo"
    assert detect_workflow("audit the traffic lights in this SUMO network") == "tls_review"
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
        cleanup_workflow_func=fake_cleanup,
    )

    assert report["status"] == "pass"
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

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmarks" / "ingolstadt_reference_matched"
EXAMPLE = ROOT / "examples" / "02_one_prompt_osm_network"


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_ingolstadt_reference_matched_benchmark_files_are_present() -> None:
    expected = {
        "cases.yaml",
        "baseline_raw_netconvert.json",
        "torii_vehicle_core.json",
        "torii_reference_visual_detail.json",
        "promotion_trace.json",
        "review_load.json",
        "summary_table.json",
    }

    assert expected <= {path.name for path in BENCHMARK.iterdir()}

    case_text = (BENCHMARK / "cases.yaml").read_text(encoding="utf-8")
    assert "11.413800,48.755391,11.433800,48.775391" in case_text
    assert "network_profile: reference_matched" in case_text
    assert "claim_status: diagnostic-demo" in case_text


def test_ingolstadt_summary_table_matches_committed_example_counts() -> None:
    example_summary = _read_json(EXAMPLE / "validation" / "run_2026-06-24_5_5" / "summary.json")
    summary_table = _read_json(BENCHMARK / "summary_table.json")

    by_stage = {stage["stage_id"]: stage for stage in summary_table["stages"]}

    assert list(by_stage) == [
        "raw_netconvert",
        "torii_scoped_build",
        "tls_aggregated",
        "junction_candidate_review",
        "teacher_guided_repair",
        "final_review_html",
    ]
    assert by_stage["raw_netconvert"]["counts"] == example_summary["counts"]["torii_raw_vehicle"]
    assert by_stage["torii_scoped_build"]["counts"] == example_summary["counts"]["torii_connected_core"]
    assert by_stage["tls_aggregated"]["counts"] == example_summary["counts"][
        "torii_tls_aggregated_reference_visual_detail"
    ]
    assert by_stage["final_review_html"]["review_artifact"] == (
        "examples/02_one_prompt_osm_network/validation/"
        "run_2026-06-25_review_html/ingolstadt_workflow_review.html"
    )
    for artifact in summary_table["source_artifacts"]:
        assert (ROOT / artifact).exists()


def test_ingolstadt_review_load_tracks_current_review_cockpit_queue() -> None:
    review_load = _read_json(BENCHMARK / "review_load.json")
    review_dir = EXAMPLE / "validation" / "run_2026-06-25_review_html"
    cluster_png_count = len(list((review_dir / "visuals").glob("*cluster_*.png")))

    assert review_load["claim_status"] == "diagnostic-demo"
    assert review_load["dense_junction_cluster_review_item_count"] == cluster_png_count
    assert review_load["blocked_gates"] == [
        "tls_reality_audit",
        "tls_aggregation",
        "topology_audit",
        "reference_join_aggregation",
        "sumo_gui",
    ]
    assert (ROOT / review_load["review_html_file"]).exists()


def test_ingolstadt_promotion_trace_does_not_promote_blocked_review_stages() -> None:
    promotion_trace = _read_json(BENCHMARK / "promotion_trace.json")

    assert promotion_trace["claim_status"] == "construction-invalid"
    decisions = {stage["stage_id"]: stage["promotion_decision"] for stage in promotion_trace["stages"]}
    assert decisions["routeability_audit"] == "pass"
    assert decisions["tls_aggregation"] == "blocked_review_required"
    assert decisions["junction_candidate_review"] == "blocked_review_required"
    assert decisions["teacher_guided_repair"] == "not_materialized_current_example"

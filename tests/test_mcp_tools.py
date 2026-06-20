import json
from pathlib import Path

from torii_sumo.tools.evidence_tools import sumo_collect_evidence, sumo_compare_outputs
from torii_sumo.tools.run_tools import sumo_run_minimal_smoke


FIXTURES = Path(__file__).parent / "fixtures" / "outputs"


def test_sumo_compare_outputs_returns_json_dict() -> None:
    report = sumo_compare_outputs(
        baseline_summary=str(FIXTURES / "baseline-summary.xml"),
        baseline_tripinfo=str(FIXTURES / "baseline-tripinfo.xml"),
        variant_summary=str(FIXTURES / "variant-summary-complete.xml"),
        variant_tripinfo=str(FIXTURES / "variant-tripinfo.xml"),
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"


def test_sumo_collect_evidence_success_returns_json_compatible_pass(tmp_path: Path) -> None:
    report = sumo_collect_evidence(
        output_dir=str(tmp_path / "evidence"),
        label="smoke",
        payload={"status": "pass", "claim_status": "diagnostic-demo"},
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    json.dumps(report)


def test_sumo_collect_evidence_empty_output_dir_returns_json_compatible_failure() -> None:
    report = sumo_collect_evidence(
        output_dir="  ",
        label="smoke",
        payload={"status": "pass"},
    )

    assert report["status"] == "fail"
    assert report["claim_status"] == "construction-invalid"
    assert "output_dir is required" in str(report["error"])
    json.dumps(report)


def test_sumo_collect_evidence_file_path_conflict_returns_failure(tmp_path: Path) -> None:
    output_file = tmp_path / "already-a-file"
    output_file.write_text("not a directory", encoding="utf-8")

    report = sumo_collect_evidence(
        output_dir=str(output_file),
        label="smoke",
        payload={"status": "pass"},
    )

    assert report["status"] == "fail"
    assert report["claim_status"] == "construction-invalid"
    json.dumps(report)


def test_sumo_collect_evidence_non_json_payload_returns_failure(tmp_path: Path) -> None:
    report = sumo_collect_evidence(
        output_dir=str(tmp_path / "evidence"),
        label="smoke",
        payload={"not_json": {1, 2, 3}},
    )

    assert report["status"] == "fail"
    assert report["claim_status"] == "construction-invalid"
    json.dumps(report)


def test_sumo_run_minimal_smoke_can_be_forced_blocked(tmp_path: Path) -> None:
    report = sumo_run_minimal_smoke(
        work_dir=str(tmp_path),
        require_real_sumo=False,
    )

    assert report["status"] == "blocked"
    assert report["claim_status"] == "blocked"

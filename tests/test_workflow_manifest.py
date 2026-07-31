from __future__ import annotations

import json
import shutil
from pathlib import Path

from torii_sumo.core.workflow_manifest import (
    WORKFLOW_STATUSES,
    artifact_identity,
    inspect_workflow_manifest,
    run_managed_workflow,
    validate_manifest_structure,
)
from torii_sumo.tools.workflow_tools import torii_auto_workflow, torii_workflow_run, torii_workflow_status


def _run(
    tmp_path: Path,
    executor,
    *,
    request_config: dict[str, object] | None = None,
    resume: bool = True,
    force: bool = False,
):
    return run_managed_workflow(
        user_request="Inspect this SUMO network",
        output_dir=tmp_path,
        workflow_name="network_review",
        tool_chain=["sumo_network_review_html", "sumo_collect_evidence"],
        request_config=request_config or {},
        executor=executor,
        executor_kwargs={},
        resume=resume,
        force=force,
    )


def test_successful_workflow_is_content_addressed_and_resumes_without_rerun(tmp_path: Path) -> None:
    calls = 0

    def executor() -> dict[str, object]:
        nonlocal calls
        calls += 1
        report_file = tmp_path / "review" / "report.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text('{"status":"pass"}', encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "detected_workflow": "network_review",
            "workflow_report_file": str(report_file),
        }

    first = _run(tmp_path, executor)
    first_manifest_bytes = Path(first["manifest_file"]).read_bytes()
    second = _run(tmp_path, executor)

    assert first["status"] == "complete"
    assert first["execution"] == "executed"
    assert second["status"] == "complete"
    assert second["execution"] == "resumed"
    assert second["run_id"] == first["run_id"]
    assert calls == 1
    assert Path(second["manifest_file"]).read_bytes() == first_manifest_bytes
    assert inspect_workflow_manifest(Path(first["manifest_file"]))["status"] == "complete"


def test_failed_workflow_resumes_the_incomplete_execute_stage(tmp_path: Path) -> None:
    calls = 0

    def executor() -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("netconvert failed")
        artifact = tmp_path / "candidate.net.xml"
        artifact.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "candidate_file": str(artifact),
        }

    failed = _run(tmp_path, executor)
    resumed = _run(tmp_path, executor)
    manifest = json.loads(Path(resumed["manifest_file"]).read_text(encoding="utf-8"))

    assert failed["status"] == "failed"
    assert resumed["status"] == "complete"
    assert resumed["execution"] == "executed"
    assert resumed["run_id"] == failed["run_id"]
    assert calls == 2
    assert manifest["attempt"] == 2
    assert manifest["attempt_history"][-1]["status"] == "failed"


def test_changed_artifact_makes_the_workflow_stale_and_blocks_automatic_resume(tmp_path: Path) -> None:
    calls = 0
    artifact = tmp_path / "candidate.net.xml"

    def executor() -> dict[str, object]:
        nonlocal calls
        calls += 1
        artifact.write_text(f"<net attempt='{calls}'/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "candidate_file": str(artifact),
        }

    first = _run(tmp_path, executor)
    artifact.write_text("<net changed='outside-workflow'/>", encoding="utf-8")
    status = inspect_workflow_manifest(Path(first["manifest_file"]))
    blocked_resume = _run(tmp_path, executor)

    assert status["status"] == "stale"
    assert status["stale_artifacts"][0]["reason"] == "sha256_mismatch"
    assert blocked_resume["status"] == "stale"
    assert blocked_resume["execution"] == "not_run"
    assert calls == 1

    forced = _run(tmp_path, executor, force=True)
    assert forced["status"] == "complete"
    assert calls == 2


def test_missing_official_evidence_stays_blocked(tmp_path: Path) -> None:
    outcome = _run(
        tmp_path,
        lambda: {
            "status": "blocked",
            "claim_status": "blocked",
            "execution_status": "needs_official_signal_plan",
            "missing_blockers": ["official_signal_plan"],
        },
    )

    assert outcome["status"] == "blocked"
    assert any("official_signal_plan" in item for item in outcome["blockers"])


def test_unsafe_repair_candidate_is_recorded_but_not_accepted(tmp_path: Path) -> None:
    candidate = tmp_path / "unsafe-candidate.net.xml"
    candidate.write_text("<net/>", encoding="utf-8")
    outcome = _run(
        tmp_path,
        lambda: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "repair_candidate_file": str(candidate),
            "repair_promotion_gate_status": "unsafe",
        },
    )
    manifest = json.loads(Path(outcome["manifest_file"]).read_text(encoding="utf-8"))

    assert outcome["status"] == "blocked"
    assert manifest["evidence"]["repair_candidates"]
    assert manifest["evidence"]["rejected_changes"][0]["decision"] == "rejected"
    assert manifest["evidence"]["rejected_changes"][0]["reason"] == "unsafe"
    assert manifest["evidence"]["accepted_changes"] == []


def test_rejected_repair_remains_a_rejected_change(tmp_path: Path) -> None:
    candidate = tmp_path / "rejected.net.xml"
    candidate.write_text("<net/>", encoding="utf-8")
    outcome = _run(
        tmp_path,
        lambda: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "candidate_variant_file": str(candidate),
            "candidate_promotion_status": "rejected",
        },
    )
    manifest = json.loads(Path(outcome["manifest_file"]).read_text(encoding="utf-8"))

    assert outcome["status"] == "blocked"
    assert manifest["evidence"]["rejected_changes"][0]["decision"] == "rejected"


def test_human_review_boundary_has_a_distinct_status(tmp_path: Path) -> None:
    outcome = _run(
        tmp_path,
        lambda: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "human_review_required_count": 2,
        },
    )

    assert outcome["status"] == "review_required"
    assert outcome["review_items"][0]["count"] == 2


def test_conflicting_evidence_invalidates_a_success_result(tmp_path: Path) -> None:
    outcome = _run(
        tmp_path,
        lambda: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "evidence_conflicts": ["official lane count disagrees with accepted candidate"],
        },
    )

    assert outcome["status"] == "invalid"
    assert "conflicting_evidence" in outcome["blockers"][0]


def test_invalid_workflow_configuration_is_persisted_as_invalid(tmp_path: Path) -> None:
    outcome = torii_workflow_run(
        user_request="Inspect this SUMO network",
        output_dir=str(tmp_path),
        autonomy_mode="unbounded",
    )

    assert outcome["status"] == "invalid"
    assert outcome["result"]["execution_status"] == "invalid_autonomy_mode"
    assert Path(outcome["manifest_file"]).is_file()


def test_artifact_paths_are_portable_relative_paths_inside_the_output_dir(tmp_path: Path) -> None:
    artifact = tmp_path / "nested" / "report.json"
    artifact.parent.mkdir()
    artifact.write_text("{}", encoding="utf-8")

    identity = artifact_identity(
        artifact,
        base_dir=tmp_path,
        label="report",
        role="output",
        evidence_kind="parsed_observation",
        producer_stage="execute",
    )

    assert identity["path"] == "nested/report.json"
    assert "\\" not in identity["path"]


def test_manifest_schema_and_status_tool_cover_the_full_status_model(tmp_path: Path) -> None:
    outcome = _run(tmp_path, lambda: {"status": "pass", "claim_status": "diagnostic-demo"})
    manifest = json.loads(Path(outcome["manifest_file"]).read_text(encoding="utf-8"))

    assert validate_manifest_structure(manifest) == []
    assert set(WORKFLOW_STATUSES) == {
        "complete",
        "incomplete",
        "blocked",
        "invalid",
        "review_required",
        "unsupported",
        "failed",
        "stale",
    }
    assert torii_workflow_status(output_dir=str(tmp_path))["status"] == "complete"
    assert torii_workflow_status(
        output_dir=str(tmp_path),
        manifest_file=outcome["manifest_file"],
    )["status"] == "invalid"


def test_success_cannot_hide_a_missing_declared_input(tmp_path: Path) -> None:
    missing = tmp_path / "official-signal-plan.csv"
    outcome = _run(
        tmp_path,
        lambda: {"status": "pass", "claim_status": "field-faithful"},
        request_config={"signal_plan_csv": missing},
    )
    manifest = json.loads(Path(outcome["manifest_file"]).read_text(encoding="utf-8"))

    assert outcome["status"] == "invalid"
    assert outcome["claim_status"] == "blocked"
    assert any("signal_plan_csv" in item for item in outcome["blockers"])
    assert manifest["missing_referenced_artifacts"][0]["state"] == "missing"


def test_failed_gate_outranks_pending_human_review(tmp_path: Path) -> None:
    outcome = _run(
        tmp_path,
        lambda: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "human_review_required_count": 1,
            "repair_promotion_gate_status": "fail",
        },
    )

    assert outcome["status"] == "blocked"
    assert outcome["claim_status"] == "blocked"
    assert outcome["review_items"]
    assert any("gate_failed" in item for item in outcome["blockers"])


def test_manifest_remains_inspectable_after_output_directory_moves(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    artifact = source_root / "nested" / "report.json"

    def executor() -> dict[str, object]:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("{}", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "workflow_report_file": str(artifact),
        }

    outcome = _run(source_root, executor)
    moved_root = tmp_path / "moved"
    shutil.move(str(source_root), moved_root)
    moved_manifest = moved_root / Path(outcome["manifest_file"]).relative_to(source_root)

    inspected = inspect_workflow_manifest(moved_manifest)

    assert inspected["status"] == "complete"
    assert Path(inspected["result_file"]).is_file()


def test_passing_promotion_gate_does_not_mean_a_change_was_applied(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.net.xml"
    candidate.write_text("<net/>", encoding="utf-8")
    outcome = _run(
        tmp_path,
        lambda: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "repair_candidate_file": str(candidate),
            "repair_promotion_gate_status": "pass",
        },
    )
    manifest = json.loads(Path(outcome["manifest_file"]).read_text(encoding="utf-8"))

    assert outcome["status"] == "complete"
    assert manifest["evidence"]["repair_candidates"]
    assert manifest["evidence"]["accepted_changes"] == []


def test_empty_user_request_is_persisted_as_invalid(tmp_path: Path) -> None:
    outcome = torii_workflow_run(user_request="   ", output_dir=str(tmp_path))

    assert outcome["status"] == "invalid"
    assert outcome["claim_status"] == "blocked"
    assert outcome["result"]["execution_status"] == "invalid_user_request"
    assert Path(outcome["manifest_file"]).is_file()


def test_schema_file_tracks_code_statuses_and_reasoning_chain() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (root / "schemas" / "torii.workflow-manifest.v1.schema.json").read_text(encoding="utf-8")
    )

    assert schema["properties"]["status"]["enum"] == list(WORKFLOW_STATUSES)
    assert schema["properties"]["reasoning_model"]["properties"]["chain"]["const"] == [
        "source",
        "observation",
        "interpretation",
        "candidate",
        "check",
        "decision",
        "applied_change",
        "validation",
        "claim",
    ]


def test_compatibility_facade_overrides_false_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "torii_sumo.tools.workflow_tools.detect_workflow",
        lambda _request: "network_review",
    )
    monkeypatch.setattr(
        "torii_sumo.tools.workflow_tools._workflow_recipe",
        lambda _name: {"tool_chain": ["sumo_network_review_html"]},
    )
    monkeypatch.setattr(
        "torii_sumo.tools.workflow_tools.run_auto_workflow",
        lambda **_kwargs: {
            "status": "pass",
            "claim_status": "field-faithful",
            "workflow_report_file": str(tmp_path / "missing-report.json"),
        },
    )

    report = torii_auto_workflow(
        user_request="Review this SUMO network",
        output_dir=str(tmp_path),
    )

    assert report["status"] == "invalid"
    assert report["claim_status"] == "blocked"
    assert report["legacy_status"] == "pass"
    assert report["legacy_claim_status"] == "field-faithful"
    assert report["workflow_status"] == "invalid"

from __future__ import annotations

import json
from pathlib import Path

from torii_sumo.core.hamburg_execution_workflow import (
    HAMBURG_EXECUTION_WORKFLOW_SCHEMA,
    materialize_hamburg_execution_plan,
)


def _write_manifest(path: Path, *, status: str = "pass", gate: str = "pass") -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "fixture",
                "status": status,
                "automatic_promotion_gate": gate,
            }
        ),
        encoding="utf-8",
    )


def test_execution_plan_records_independent_counts_and_blocks_replay(tmp_path: Path) -> None:
    manifests = {}
    for stage_id in ("W0", "W1", "W3"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path)
        manifests[stage_id] = path
    w2 = tmp_path / "W2.json"
    _write_manifest(w2, status="blocked", gate="blocked")
    manifests["W2"] = w2

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests=manifests,
    )

    assert plan["schema"] == HAMBURG_EXECUTION_WORKFLOW_SCHEMA
    assert plan["stages"]["W3"]["readiness"] == "complete"
    assert "core/hamburg_named_detector_bindings.py" in plan["stages"]["W3"]["contract"]["code_surfaces"]
    assert plan["stages"]["W4"]["readiness"] == "blocked"
    assert plan["stages"]["W4"]["blocked_by"] == {"W2": "blocked"}
    assert plan["next_action"] == {
        "stage_id": "W2",
        "status": "blocked",
        "action": "resolve_stage_gate",
        "blocked_by": {"W2": "blocked"},
    }
    assert plan["first_invalid_stage"] == "W2"
    assert plan["replan"]["required"] is True
    assert plan["replan"]["resume_action"] == "resolve_stage_gate"


def test_execution_plan_invalidates_downstream_after_manifest_change(tmp_path: Path) -> None:
    stage_dir = tmp_path / "stages"
    stage_dir.mkdir()
    manifests = {}
    for stage_id in ("W0", "W1", "W2", "W3", "W4"):
        path = stage_dir / f"{stage_id}.json"
        _write_manifest(path)
        manifests[stage_id] = path

    plan_dir = tmp_path / "plan"
    first = materialize_hamburg_execution_plan(output_dir=plan_dir, stage_manifests=manifests)
    assert first["next_action"] == {
        "stage_id": "W5",
        "status": "ready",
        "action": "run_reusable_product_workflow",
    }

    _write_manifest(manifests["W1"], status="partial", gate="blocked")
    second = materialize_hamburg_execution_plan(
        output_dir=plan_dir,
        stage_manifests=manifests,
        resume=True,
    )

    assert second["changed_stages"] == ["W1"]
    assert second["invalidated_downstream_stages"] == ["W1", "W2", "W4", "W5"]
    assert second["stages"]["W4"]["effective_status"] == "not_run"
    assert second["stages"]["W4"]["readiness"] == "blocked"


def test_execution_plan_does_not_guess_missing_stage(tmp_path: Path) -> None:
    w0 = tmp_path / "W0.json"
    _write_manifest(w0)
    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests={"W0": w0, "W1": tmp_path / "missing.json"},
    )

    assert plan["stages"]["W1"]["decision"] == "blocked"
    assert plan["stages"]["W1"]["reason"] == "manifest_missing"
    assert plan["next_action"]["stage_id"] == "W1"
    assert plan["next_action"]["status"] == "blocked"


def test_scope_manifest_can_feed_geometry_without_signal_promotion(tmp_path: Path) -> None:
    w0 = tmp_path / "W0.json"
    w0.write_text(
        json.dumps(
            {
                "schema": "torii.hamburg-named-corridor-scope/v1",
                "status": "partial",
                "decision": "blocked",
                "signal_assets": {"decision": "blocked"},
                "nodes": [{"node_id": "2349"}, {"node_id": "2394"}, {"node_id": "2403"}],
                "official_road_scope": {"link_count": 7},
            }
        ),
        encoding="utf-8",
    )

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests={"W0": w0},
    )

    assert plan["stages"]["W0"]["decision"] == "blocked"
    assert plan["stages"]["W0"]["execution_gate"] == "pass"
    assert plan["stages"]["W1"]["readiness"] == "ready"
    assert plan["stages"]["W3"]["readiness"] == "ready"
    assert plan["promotion"]["decision"] == "blocked"


def test_execution_plan_preserves_machine_feedback_for_replan(tmp_path: Path) -> None:
    w0 = tmp_path / "W0.json"
    _write_manifest(w0)
    w1 = tmp_path / "W1.json"
    _write_manifest(w1)
    w2 = tmp_path / "W2.json"
    w2.write_text(
        json.dumps(
            {
                "schema": "torii.hamburg-named-signal-observations/v1",
                "status": "blocked",
                "automatic_promotion_gate": "blocked",
                "execution_gate": "blocked",
                "execution_gate_reason": "one or more active bindings lack a complete response",
                "missing_required_node_ids": ["2403"],
                "incomplete_stream_ids": [72940],
                "publication_gap": {
                    "decision": "confirmed_official_node_without_published_tld_binding",
                    "next_action": "resolve_official_signal_publication_gap_or_change_scope",
                },
            }
        ),
        encoding="utf-8",
    )

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests={"W0": w0, "W1": w1, "W2": w2},
    )

    assert plan["first_invalid_stage"] == "W2"
    assert plan["stages"]["W2"]["reason"] == (
        "one or more active bindings lack a complete response"
    )
    assert plan["stages"]["W2"]["feedback"] == {
        "execution_gate_reason": "one or more active bindings lack a complete response",
        "missing_required_node_ids": ["2403"],
        "incomplete_stream_ids": [72940],
        "publication_gap": {
            "decision": "confirmed_official_node_without_published_tld_binding",
            "next_action": "resolve_official_signal_publication_gap_or_change_scope",
        },
    }
    assert plan["replan"]["feedback"] == plan["stages"]["W2"]["feedback"]


def test_auxiliary_stage_feedback_is_hash_bound_but_not_a_gate(tmp_path: Path) -> None:
    w0 = tmp_path / "W0.json"
    _write_manifest(w0)
    w1 = tmp_path / "W1.json"
    _write_manifest(w1)
    w2 = tmp_path / "W2.json"
    _write_manifest(w2, status="blocked", gate="blocked")
    feedback = tmp_path / "W2b.json"
    feedback.write_text(
        json.dumps(
            {
                "status": "partial",
                "resolved_node_ids": ["2349", "2394"],
                "unresolved_node_ids": ["2403"],
                "publication_gap": {
                    "decision": "confirmed_official_node_without_published_tld_binding",
                    "next_action": "resolve_official_signal_publication_gap_or_change_scope",
                },
            }
        ),
        encoding="utf-8",
    )

    first = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests={"W0": w0, "W1": w1, "W2": w2},
        stage_feedback={"W2": feedback},
    )
    assert first["stages"]["W2"]["execution_gate"] == "blocked"
    assert first["stages"]["W2"]["feedback_manifest"]["sha256"]
    assert first["replan"]["feedback"]["resolved_node_ids"] == ["2349", "2394"]
    assert first["replan"]["feedback"]["unresolved_node_ids"] == ["2403"]
    assert first["replan"]["feedback"]["publication_gap"]["decision"] == (
        "confirmed_official_node_without_published_tld_binding"
    )

    feedback.write_text(
        json.dumps(
            {
                "status": "partial",
                "publication_gap": {
                    "decision": "official_node_without_current_stream",
                    "next_action": "resolve_official_signal_publication_gap_or_change_scope",
                },
            }
        ),
        encoding="utf-8",
    )
    second = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests={"W0": w0, "W1": w1, "W2": w2},
        stage_feedback={"W2": feedback},
    )
    assert second["changed_stages"] == ["W2"]
    assert second["invalidated_downstream_stages"] == ["W2", "W4", "W5"]


def test_multiple_auxiliary_feedback_manifests_are_merged_without_changing_gate(tmp_path: Path) -> None:
    w0 = tmp_path / "W0.json"
    _write_manifest(w0)
    w1 = tmp_path / "W1.json"
    _write_manifest(w1)
    w2 = tmp_path / "W2.json"
    _write_manifest(w2, status="blocked", gate="blocked")
    history = tmp_path / "history.json"
    history.write_text(
        json.dumps({"resolved_node_ids": ["2349", "2394"], "unresolved_node_ids": ["2403"]}),
        encoding="utf-8",
    )
    identity = tmp_path / "identity.json"
    identity.write_text(
        json.dumps(
            {
                "decision": "pass",
                "human_action_required": False,
                "selections": [
                    {"selected_node": {"node_id": node_id}}
                    for node_id in ("2349", "2394", "2403")
                ],
            }
        ),
        encoding="utf-8",
    )

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests={"W0": w0, "W1": w1, "W2": w2},
        stage_feedback={"W2": (history, identity)},
    )

    assert plan["stages"]["W2"]["execution_gate"] == "blocked"
    assert len(plan["stages"]["W2"]["feedback_manifests"]) == 2
    assert "feedback_manifest" not in plan["stages"]["W2"]
    assert plan["replan"]["feedback"]["resolved_node_ids"] == ["2349", "2394"]
    assert plan["replan"]["feedback"]["official_node_identity"]["selected_node_ids"] == [
        "2349",
        "2394",
        "2403",
    ]


def test_changes_to_any_plural_feedback_manifest_trigger_replan(tmp_path: Path) -> None:
    w0 = tmp_path / "W0.json"
    _write_manifest(w0)
    w1 = tmp_path / "W1.json"
    _write_manifest(w1)
    w2 = tmp_path / "W2.json"
    _write_manifest(w2, status="blocked", gate="blocked")
    history = tmp_path / "history.json"
    history.write_text(json.dumps({"resolved_node_ids": ["2349"]}), encoding="utf-8")
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({"resolved_node_ids": ["2349", "2394"]}), encoding="utf-8")

    first = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests={"W0": w0, "W1": w1, "W2": w2},
        stage_feedback={"W2": (history, identity)},
    )
    assert first["changed_stages"] == []

    identity.write_text(json.dumps({"resolved_node_ids": ["2349", "2394", "2403"]}), encoding="utf-8")
    second = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests={"W0": w0, "W1": w1, "W2": w2},
        stage_feedback={"W2": (history, identity)},
    )
    assert second["changed_stages"] == ["W2"]
    assert second["invalidated_downstream_stages"] == ["W2", "W4", "W5"]


def test_declared_execution_gate_can_expose_structural_candidate_to_diagnostics(
    tmp_path: Path,
) -> None:
    w0 = tmp_path / "W0.json"
    _write_manifest(w0)
    w1 = tmp_path / "W1.json"
    w1.write_text(
        json.dumps(
            {
                "schema": "torii.hamburg-official-corridor-geometry/v1",
                "status": "review_ready",
                "automatic_promotion_gate": "blocked",
                "execution_gate": "pass",
            }
        ),
        encoding="utf-8",
    )

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests={"W0": w0, "W1": w1},
    )

    assert plan["stages"]["W1"]["decision"] == "blocked"
    assert plan["stages"]["W1"]["execution_gate"] == "pass"
    assert plan["stages"]["W2"]["readiness"] == "ready"
    assert plan["promotion"]["decision"] == "blocked"

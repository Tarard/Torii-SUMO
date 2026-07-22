from __future__ import annotations

import json
from pathlib import Path

import pytest

from torii_sumo.core.candidate_contracts import file_sha256
from torii_sumo.core.hamburg_execution_workflow import (
    HAMBURG_EXECUTION_CONFIG_SCHEMA,
    HAMBURG_EXECUTION_WORKFLOW_SCHEMA,
    HamburgExecutionWorkflowError,
    materialize_hamburg_execution_plan,
    materialize_hamburg_execution_plan_from_config,
    materialize_hamburg_w1_topology_handoff,
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


def test_w1_topology_handoff_is_hash_bound_and_non_promoting(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.net.xml"
    candidate.write_text("<net/>", encoding="utf-8")
    candidate_hash = file_sha256(candidate)
    source = tmp_path / "source.net.xml"
    source.write_text("<net/>", encoding="utf-8")

    def write(name: str, payload: dict[str, object]) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    topology = write(
        "topology.json",
        {
            "schema": "torii.junction-aggregation-preservation/v1",
            "status": "pass",
            "source_net_file": str(source.resolve()),
            "source_sha256": file_sha256(source),
            "variant_net_file": str(candidate.resolve()),
            "variant_sha256": candidate_hash,
            "unexpected_removed_normal_edge_count": 0,
            "lost_shared_connection_count": 0,
            "new_dangling_shared_normal_edge_count": 0,
            "boundary_movement_preservation": {
                "status": "pass",
                "lost_boundary_movement_count": 0,
                "added_boundary_movement_count": 0,
                "groups": [
                    {
                        "variant_boundary_movement_count": 2,
                        "variant_boundary_movements": ["in|0|out|0", "in|1|out|1"],
                    }
                ],
            },
        },
    )
    surface = write(
        "surface.json",
        {
            "schema": "torii.sumo-surface-overlap-audit/v1",
            "audit_engine": "torii.bevel-strip-and-junction-polygon-area/v2",
            "status": "pass",
            "source_net_file": str(candidate.resolve()),
            "source_sha256": candidate_hash,
            "source_network_mutation": False,
            "geometry_error_count": 0,
            "junction_junction_overlap_count": 0,
            "external_lane_non_owner_junction_overlap_count": 0,
        },
    )
    connection = write(
        "connection.json",
        {
            "schema": "torii.connection_mode_regression_manifest.v1",
            "status": "pass",
            "gate_status": "pass",
            "automatic_promotion_gate": "pass",
            "candidate_net_file": str(candidate.resolve()),
            "candidate_sha256": candidate_hash,
            "source_network_mutation": False,
        },
    )
    load = write(
        "load.json",
        {
            "schema": "torii.sumo-load-audit/v1",
            "status": "pass",
            "source_net_file": str(candidate.resolve()),
            "source_sha256": candidate_hash,
            "source_network_mutation": False,
        },
    )
    route = tmp_path / "smoke.rou.xml"
    summary = tmp_path / "summary.xml"
    tripinfo = tmp_path / "tripinfo.xml"
    for path in (route, summary, tripinfo):
        path.write_text("evidence", encoding="utf-8")
    smoke = write(
        "smoke.json",
        {
            "schema": "torii.hamburg-2403-movement-smoke/v1",
            "status": "pass",
            "candidate_net_file": str(candidate.resolve()),
            "candidate_sha256": candidate_hash,
            "inputs": {
                "route": {"path": str(route), "sha256": file_sha256(route)},
                "preservation_audit": {"path": str(topology), "sha256": file_sha256(topology)},
            },
            "outputs": {
                "summary": {"path": str(summary), "sha256": file_sha256(summary)},
                "tripinfo": {"path": str(tripinfo), "sha256": file_sha256(tripinfo)},
            },
            "vehicle_count": 2,
            "movement_count": 2,
            "movement_keys": ["in|0|out|0", "in|1|out|1"],
            "movement_keys_unique": True,
            "movement_keys_match_preservation": True,
            "loaded": 2,
            "inserted": 2,
            "ended": 2,
            "running": 0,
            "waiting": 0,
            "teleports": 0,
            "collisions": 0,
            "inspection": {
                "status": "pass",
                "summary": {
                    "loaded": 2,
                    "inserted": 2,
                    "arrived": 2,
                    "running": 0,
                    "waiting": 0,
                    "teleports": 0,
                    "collisions": 0,
                },
                "tripinfo": {"trip_count": 2},
            },
        },
    )
    review_files = []
    for junction_id in ("a", "b"):
        review_files.append(
            write(
                f"review-{junction_id}.json",
                {
                    "schema": "torii.netedit-background-review.direct/v1",
                    "status": "review_material_ready",
                    "automatic_promotion_gate": "blocked",
                    "candidate_file": str(candidate.resolve()),
                    "candidate_sha256_before": candidate_hash,
                    "candidate_sha256_after": candidate_hash,
                    "candidate_unchanged": True,
                    "target_junction": {"id": junction_id},
                    "mode_images_distinct": True,
                    "global_keyboard_or_mouse_input_used": False,
                    "foreground_context_restored": True,
                },
            )
        )

    bad = json.loads(review_files[0].read_text(encoding="utf-8"))
    bad["candidate_sha256_after"] = "wrong"
    review_files[0].write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(HamburgExecutionWorkflowError, match="W1 topology handoff rejected"):
        materialize_hamburg_w1_topology_handoff(
            output_dir=tmp_path / "bad",
            candidate_net_file=candidate,
            topology_audit_file=topology,
            surface_comparison_file=surface,
            connection_mode_manifest_file=connection,
            sumo_load_report_file=load,
            movement_smoke_file=smoke,
            netedit_review_files=review_files,
            expected_review_junction_ids=("a", "b"),
        )

    bad["candidate_sha256_after"] = candidate_hash
    review_files[0].write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(HamburgExecutionWorkflowError, match="NetEdit review owners are empty"):
        materialize_hamburg_w1_topology_handoff(
            output_dir=tmp_path / "empty-review",
            candidate_net_file=candidate,
            topology_audit_file=topology,
            surface_comparison_file=surface,
            connection_mode_manifest_file=connection,
            sumo_load_report_file=load,
            movement_smoke_file=smoke,
            netedit_review_files=(),
            expected_review_junction_ids=(),
        )
    report = materialize_hamburg_w1_topology_handoff(
        output_dir=tmp_path / "good",
        candidate_net_file=candidate,
        topology_audit_file=topology,
        surface_comparison_file=surface,
        connection_mode_manifest_file=connection,
        sumo_load_report_file=load,
        movement_smoke_file=smoke,
        netedit_review_files=review_files,
        expected_review_junction_ids=("a", "b"),
    )

    assert report["status"] == "review_ready"
    assert report["execution_gate"] == "pass"
    assert report["automatic_promotion_gate"] == "blocked"
    assert report["netedit_review"]["junction_ids"] == ["a", "b"]
    assert report["routeability"]["movement_count"] == 2


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


def test_portable_workflow_config_resolves_stage_paths_relative_to_itself(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    _write_manifest(evidence_dir / "W0.json")
    _write_manifest(evidence_dir / "W1.json")
    config = tmp_path / "hamburg-workflow.json"
    config.write_text(
        json.dumps(
            {
                "schema": HAMBURG_EXECUTION_CONFIG_SCHEMA,
                "output_dir": "run",
                "resume": False,
                "stages": {
                    "W0": {"manifest": "evidence/W0.json"},
                    "W1": {"manifest": "evidence/W1.json", "feedback": []},
                },
            }
        ),
        encoding="utf-8",
    )

    plan = materialize_hamburg_execution_plan_from_config(config)

    assert plan["stages"]["W0"]["decision"] == "pass"
    assert plan["stages"]["W1"]["decision"] == "pass"
    assert (tmp_path / "run" / "execution-plan.manifest.json").is_file()


def test_portable_workflow_config_rejects_unknown_stage(tmp_path: Path) -> None:
    config = tmp_path / "hamburg-workflow.json"
    config.write_text(
        json.dumps(
            {
                "schema": HAMBURG_EXECUTION_CONFIG_SCHEMA,
                "output_dir": "run",
                "stages": {"W9": {}},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(HamburgExecutionWorkflowError, match="unknown workflow stage"):
        materialize_hamburg_execution_plan_from_config(config)

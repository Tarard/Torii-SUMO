from __future__ import annotations

import json
from pathlib import Path

import pytest

from torii_sumo.core.tum_style_closed_loop import (
    _next_action,
    begin_tum_style_iteration,
    complete_tum_style_iteration,
    next_tum_style_action,
    rollback_tum_style_iteration,
    start_tum_style_closed_loop,
)


def _net(path: Path, marker: str) -> None:
    path.write_text(f'<net><junction id="{marker}"/></net>', encoding="utf-8")


def test_closed_loop_advances_only_on_accept(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.net.xml"
    _net(baseline, "baseline")
    started = start_tum_style_closed_loop(baseline_net_file=baseline, output_dir=tmp_path / "loop")
    state_file = Path(started["state_file"])
    parent_sha = started["current_candidate"]["sha256"]

    begun = begin_tum_style_iteration(state_file=state_file)
    before = Path(begun["before_net_file"])
    after = tmp_path / "edited.net.xml"
    _net(after, "edited")
    rejected = complete_tum_style_iteration(
        state_file=state_file,
        iteration_id=begun["iteration_id"],
        after_net_file=after,
        action={"kind": "connection", "mode": "connection_mode", "count": 1},
        audit={"status": "fail", "movement_missing_count": 1},
        mcp_evidence={"session_id": "s1", "before_screenshot_sha256": "a" * 64},
        decision="rejected",
    )
    assert rejected["current_candidate"]["sha256"] == parent_sha
    assert before.read_bytes() == Path(rejected["current_candidate"]["path"]).read_bytes()

    begun = begin_tum_style_iteration(state_file=state_file)
    accepted = complete_tum_style_iteration(
        state_file=state_file,
        iteration_id=begun["iteration_id"],
        after_net_file=after,
        action={"kind": "connection", "mode": "connection_mode", "count": 1},
        audit={"status": "pass", "visual_connection_gate": {"status": "pass"}},
        mcp_evidence={"session_id": "s2", "after_screenshot_sha256": "b" * 64},
        decision="accepted",
    )
    assert accepted["current_candidate"]["sha256"] != parent_sha
    assert accepted["iterations"][-1]["decision"] == "accepted"


def test_closed_loop_rejects_parent_hash_drift_and_queues_evidence(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.net.xml"
    _net(baseline, "baseline")
    started = start_tum_style_closed_loop(baseline_net_file=baseline, output_dir=tmp_path / "loop")
    state_file = Path(started["state_file"])
    begun = begin_tum_style_iteration(state_file=state_file)
    Path(begun["before_net_file"]).write_text("drift", encoding="utf-8")
    with pytest.raises(ValueError, match="parent candidate changed"):
        complete_tum_style_iteration(
            state_file=state_file,
            iteration_id=begun["iteration_id"],
            after_net_file=baseline,
            action={"kind": "inspect", "mode": "inspect_mode", "count": 1},
            audit={},
            mcp_evidence={},
            decision="review_required",
        )
    queued = next_tum_style_action(state_file=state_file, audit={})
    assert queued["action"]["kind"] == "inspect"
    assert queued["action"]["requires_evidence"] is True


def test_closed_loop_rollback_restores_parent_and_writes_artifact(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.net.xml"
    _net(baseline, "baseline")
    started = start_tum_style_closed_loop(baseline_net_file=baseline, output_dir=tmp_path / "loop")
    state_file = Path(started["state_file"])
    begun = begin_tum_style_iteration(state_file=state_file)
    after = tmp_path / "edited.net.xml"
    _net(after, "edited")
    complete_tum_style_iteration(
        state_file=state_file,
        iteration_id=begun["iteration_id"],
        after_net_file=after,
        action={"kind": "geometry", "mode": "move_mode", "count": 1},
        audit={"status": "pass", "visual_connection_gate": {"status": "pass"}},
        mcp_evidence={"session_id": "s1"},
        decision="accepted",
    )
    rolled = rollback_tum_style_iteration(state_file=state_file, iteration_id=begun["iteration_id"])
    assert rolled["current_candidate"]["sha256"] == started["current_candidate"]["sha256"]
    assert Path(rolled["rollback_file"]).is_file()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["iterations"][-1]["status"] == "rolled_back"


def test_matrix_gap_does_not_override_exact_tls_parity() -> None:
    action = _next_action(
        {
            "vehicle_movement_matrix_missing_count": 8,
            "tls_movement_parity": "pass",
            "approach_integrity_status": "fail",
        },
        reason="audit",
    )
    assert action["kind"] == "geometry"

    action = _next_action(
        {"vehicle_movement_matrix_missing_count": 1, "tls_movement_parity": "fail"},
        reason="audit",
    )
    assert action["kind"] == "connection"


def test_accepted_iteration_requires_visual_connection_pass(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.net.xml"
    _net(baseline, "baseline")
    started = start_tum_style_closed_loop(baseline_net_file=baseline, output_dir=tmp_path / "loop")
    begun = begin_tum_style_iteration(state_file=Path(started["state_file"]))
    with pytest.raises(ValueError, match="visual Connection gate must pass"):
        complete_tum_style_iteration(
            state_file=Path(started["state_file"]),
            iteration_id=begun["iteration_id"],
            after_net_file=baseline,
            action={"kind": "connection", "count": 1},
            audit={"status": "pass", "visual_connection_gate": {"status": "fail"}},
            mcp_evidence={},
            decision="accepted",
        )

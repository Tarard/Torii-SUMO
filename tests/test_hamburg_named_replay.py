from __future__ import annotations

from pathlib import Path

from torii_sumo.core.hamburg_named_replay import (
    _audit_signal_history_scope,
    _read_sumo_quality,
    _summarize_e1,
)


def test_sumo_quality_gate_blocks_teleports_and_collisions(tmp_path: Path) -> None:
    summary = tmp_path / "summary.xml"
    summary.write_text(
        """<summary>
  <step time="0" teleports="0" collisions="0" loaded="2" inserted="2" running="2" waiting="0" ended="0" arrived="0" halting="0"/>
  <step time="1" teleports="3" collisions="1" loaded="2" inserted="2" running="1" waiting="0" ended="1" arrived="1" halting="0"/>
</summary>\n""",
        encoding="utf-8",
    )

    report = _read_sumo_quality(summary)

    assert report["quality_gate"] == "blocked"
    assert report["teleport_count"] == 3
    assert report["collision_count"] == 1
    assert report["summary_final"]["arrived"] == "1"


def test_sumo_quality_gate_passes_only_clean_summary(tmp_path: Path) -> None:
    summary = tmp_path / "summary.xml"
    summary.write_text(
        "<summary><step time=\"1\" teleports=\"0\" collisions=\"0\"/></summary>\n",
        encoding="utf-8",
    )

    report = _read_sumo_quality(summary)

    assert report["quality_gate"] == "pass"
    assert report["teleport_count"] == 0
    assert report["collision_count"] == 0


def test_e1_summary_exposes_missing_bins() -> None:
    report = _summarize_e1(
        [
            {
                "measurement_status": "matched",
                "expected_total": 10,
                "measured_nVehContrib": 8,
                "diff_nVehContrib_minus_expected": -2,
            },
            {
                "measurement_status": "missing",
                "expected_total": 7,
                "measured_nVehContrib": None,
                "diff_nVehContrib_minus_expected": None,
            },
        ]
    )

    assert report["matched"] == 1
    assert report["missing"] == 1
    assert report["total"] == 2
    assert report["expected"] == 10
    assert report["measured"] == 8


def test_signal_history_scope_blocks_short_official_window() -> None:
    report = _audit_signal_history_scope(
        {"window": {"begin_utc": "2026-07-18T06:00:00Z", "end_utc": "2026-07-18T08:00:00Z"}},
        simulation_begin=0,
        simulation_end=9000,
    )

    assert report["status"] == "review_required"
    assert report["history_window_seconds"] == 7200
    assert report["replay_window_seconds"] == 9000

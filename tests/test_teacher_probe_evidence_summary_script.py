import importlib.util
import json
from pathlib import Path


SCRIPT = Path("plugins/torii-sumo/scripts/teacher_probe_evidence_summary.py")


def load_script():
    spec = importlib.util.spec_from_file_location("teacher_probe_evidence_summary", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_summarize_probe_dir_reports_semantic_and_netedit_gates(tmp_path: Path) -> None:
    module = load_script()
    probe = tmp_path / "probe_123"
    (probe / "run" / "candidate_001").mkdir(parents=True)
    (probe / "connection_audit").mkdir()
    (probe / "netedit_review" / "capture").mkdir(parents=True)
    (probe / "probe_123_summary.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "parity_gate_status": "pass",
                "promotion_gate_status": "pass",
                "approach_integrity_status": "pass",
                "attempted_candidate_count": 1,
                "pass_candidate_count": 1,
                "failed_candidate_count": 0,
                "semantic_failure_counts": {},
            }
        ),
        encoding="utf-8",
    )
    (probe / "run" / "probe_123_run_report.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "parity_gate_status": "pass",
                "promotion_gate_status": "pass",
                "semantic_layer_gate_counts": {
                    "topology": {"pass": 1, "fail": 0, "failure_count": 0},
                    "movement_tls": {"pass": 1, "fail": 0, "failure_count": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    (probe / "run" / "candidate_001" / "candidate_teacher_guided_report.json").write_text(
        json.dumps({"junction_id": "123", "final_net_file": "candidate.net.xml"}),
        encoding="utf-8",
    )
    (probe / "connection_audit" / "123_connection_audit_summary.json").write_text(
        json.dumps(
            {
                "teacher": {"connections_by_dir": {"s": 2, "l": 1, "r": 1, "t": 1}},
                "candidate": {"connections_by_dir": {"s": 2, "l": 1, "r": 1, "t": 1}},
                "equal_signature": True,
            }
        ),
        encoding="utf-8",
    )
    (probe / "netedit_review" / "capture" / "netedit_connection_review.png").write_bytes(b"png")

    summary = module.summarize_probe_dir(probe)

    assert summary["target_junction"] == "123"
    assert summary["small_probe_semantic_gate"] == "pass"
    assert summary["netedit_connection_capture_gate"] == "pass"
    assert summary["connection_audit"]["equal_signature"] is True


def test_aggregate_requires_every_probe_to_pass(tmp_path: Path) -> None:
    module = load_script()
    good = {"small_probe_semantic_gate": "pass", "netedit_connection_capture_gate": "pass"}
    weak = {"small_probe_semantic_gate": "pass", "netedit_connection_capture_gate": "missing"}

    report = module.build_report([good, weak])

    assert report["probe_count"] == 2
    assert report["semantic_pass_count"] == 2
    assert report["netedit_connection_capture_count"] == 1
    assert report["status"] == "partial"
    assert report["all_small_probe_semantic_gate_pass"] is True
    assert report["all_netedit_connection_capture_gate_pass"] is False

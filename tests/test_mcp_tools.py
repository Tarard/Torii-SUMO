import json
from pathlib import Path

from torii_sumo.tools.evidence_tools import sumo_collect_evidence, sumo_compare_outputs
from torii_sumo.tools.osm_tools import sumo_network_routeability_audit, sumo_network_topology_audit
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


def test_sumo_network_routeability_audit_tool_returns_json_compatible_report(monkeypatch, tmp_path: Path) -> None:
    from torii_sumo.tools import osm_tools

    net_file = tmp_path / "network.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    def fake_audit(**kwargs):
        assert kwargs["net_file"] == net_file
        assert kwargs["vehicle_count"] == 25
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "report_file": str(tmp_path / "audit.json"),
        }

    monkeypatch.setattr(osm_tools, "run_routeability_audit", fake_audit)

    report = sumo_network_routeability_audit(
        net_file=str(net_file),
        output_dir=str(tmp_path / "audit"),
        vehicle_count=25,
    )

    assert report["status"] == "pass"
    assert report["routeability_status"] == "pass"
    json.dumps(report)


def test_sumo_network_topology_audit_tool_returns_json_compatible_report(monkeypatch, tmp_path: Path) -> None:
    from torii_sumo.tools import osm_tools

    net_file = tmp_path / "network.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    def fake_audit(**kwargs):
        assert kwargs["net_file"] == net_file
        assert kwargs["cluster_radius_m"] == 25.0
        assert kwargs["min_cluster_nodes"] == 3
        return {
            "status": "blocked",
            "claim_status": "blocked",
            "topology_fragmentation_status": "needs_review",
            "suspicious_cluster_count": 1,
            "clusters_file": str(tmp_path / "clusters.csv"),
        }

    monkeypatch.setattr(osm_tools, "audit_topology_fragmentation", fake_audit)

    report = sumo_network_topology_audit(
        net_file=str(net_file),
        output_dir=str(tmp_path / "topology"),
        cluster_radius_m=25.0,
        min_cluster_nodes=3,
    )

    assert report["status"] == "blocked"
    assert report["topology_fragmentation_status"] == "needs_review"
    json.dumps(report)

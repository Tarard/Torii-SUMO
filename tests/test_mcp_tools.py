import json
from pathlib import Path

from torii_sumo.tools.evidence_tools import sumo_collect_evidence, sumo_compare_outputs
from torii_sumo.tools.osm_tools import (
    sumo_network_junction_aggregation_variant,
    sumo_network_reference_join_audit,
    sumo_network_routeability_audit,
    sumo_network_topology_audit,
)
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


def test_sumo_network_reference_join_audit_tool_returns_json_compatible_report(monkeypatch, tmp_path: Path) -> None:
    from torii_sumo.tools import osm_tools

    reference_net_file = tmp_path / "reference.net.xml"
    candidate_net_file = tmp_path / "candidate.net.xml"
    reference_net_file.write_text("<net/>", encoding="utf-8")
    candidate_net_file.write_text("<net/>", encoding="utf-8")

    def fake_audit(**kwargs):
        assert kwargs["reference_net_file"] == reference_net_file
        assert kwargs["candidate_net_file"] == candidate_net_file
        assert kwargs["candidate_cluster_radius_m"] == 25.0
        assert kwargs["candidate_min_cluster_nodes"] == 4
        assert kwargs["match_radius_m"] == 50.0
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "reference_case_count": 3,
            "matched_case_count": 2,
            "summary_file": str(tmp_path / "summary.json"),
        }

    monkeypatch.setattr(osm_tools, "audit_reference_join_patterns", fake_audit)

    report = sumo_network_reference_join_audit(
        reference_net_file=str(reference_net_file),
        candidate_net_file=str(candidate_net_file),
        output_dir=str(tmp_path / "reference-join"),
        candidate_cluster_radius_m=25.0,
        candidate_min_cluster_nodes=4,
        match_radius_m=50.0,
    )

    assert report["status"] == "pass"
    assert report["matched_case_count"] == 2
    json.dumps(report)


def test_sumo_network_junction_aggregation_variant_tool_returns_json_compatible_report(
    monkeypatch, tmp_path: Path
) -> None:
    from torii_sumo.tools import osm_tools

    net_file = tmp_path / "candidate.net.xml"
    topology_report_file = tmp_path / "topology.json"
    net_file.write_text("<net/>", encoding="utf-8")
    topology_report_file.write_text(
        json.dumps(
            {
                "suspicious_clusters": [
                    {
                        "cluster_id": "C001",
                        "aggregation_decision": "join",
                        "aggregation_confidence": "medium",
                        "node_ids": ["j1", "j2"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_aggregation(**kwargs):
        assert kwargs["net_file"] == net_file
        assert kwargs["join_dist_m"] == 25.0
        assert kwargs["topology_audit_report"]["suspicious_clusters"][0]["cluster_id"] == "C001"
        return {
            "status": "pass",
            "claim_status": "blocked",
            "junction_aggregation_status": "variant_created_for_review",
            "junction_aggregation_candidate_count": 1,
            "junction_aggregation_variant_file": str(tmp_path / "variant.net.xml"),
        }

    monkeypatch.setattr(osm_tools, "build_junction_aggregation_variant", fake_aggregation)

    report = sumo_network_junction_aggregation_variant(
        net_file=str(net_file),
        output_dir=str(tmp_path / "aggregation"),
        topology_audit_report_file=str(topology_report_file),
        join_dist_m=25.0,
    )

    assert report["status"] == "pass"
    assert report["junction_aggregation_candidate_count"] == 1
    json.dumps(report)

import xml.etree.ElementTree as ET

from torii_sumo.core.junction_aggregation import _aggregation_candidates
from torii_sumo.core.junction_join_definition import (
    build_junction_join_definition,
    netconvert_join_patch_args,
)
from torii_sumo.core.osm_workflow import _junction_aggregation_summary


def test_corridor_rejected_topology_clusters_do_not_become_join_candidates() -> None:
    topology_report = {
        "clusters_file": "clusters.csv",
        "suspicious_clusters": [
            {
                "cluster_id": "C001",
                "aggregation_decision": "needs_map_review",
                "aggregation_confidence": "low",
                "corridor_decision": "reject",
                "corridor_reason": "large group spans three or more named intersection cells",
                "node_ids": ["a", "b", "c"],
            },
            {
                "cluster_id": "C002",
                "aggregation_decision": "join",
                "aggregation_confidence": "medium",
                "corridor_decision": "allow",
                "node_ids": ["d", "e", "f"],
            },
        ],
    }

    candidates = _aggregation_candidates(
        topology_audit_report=topology_report,
        reference_join_audit_report=None,
    )
    summary = _junction_aggregation_summary(topology_report)

    assert [candidate["candidate_id"] for candidate in candidates] == ["C002"]
    assert summary["junction_aggregation_candidate_count"] == 1
    assert summary["junction_aggregation_join_candidate_count"] == 1
    assert summary["junction_aggregation_blocked_by_corridor_count"] == 1


def test_junction_join_definition_writes_sumo_plainxml_join_patch(tmp_path) -> None:
    candidates = [
        {
            "source": "topology_audit",
            "candidate_id": "C001",
            "decision": "join",
            "confidence": "map_confirmed",
            "node_ids": ["n1", "n2", "n3"],
            "reason": "Google Maps default map confirms one physical intersection",
            "google_maps_url": "https://www.google.com/maps/@48.0,11.0,50m",
        },
        {
            "source": "topology_audit",
            "candidate_id": "C002",
            "decision": "needs_map_review",
            "node_ids": "r1;r2",
            "reason": "traffic-signal semantics require map review",
        },
        {
            "source": "topology_audit",
            "candidate_id": "C003",
            "decision": "do_not_join",
            "node_ids": ["ramp_a", "ramp_b"],
            "reason": "parallel ramp pair should not become one city junction",
        },
    ]

    report = build_junction_join_definition(candidates, output_dir=tmp_path, prefix="demo")

    assert report["status"] == "pass"
    assert report["sumo_join_semantics"] == "plain_nodes_join_patch"
    assert report["explicit_join_count"] == 1
    assert report["join_exclude_count"] == 2
    assert report["needs_map_review_count"] == 1

    nodes_patch = tmp_path / "demo_junction_join.nod.xml"
    assert report["nodes_patch_file"] == str(nodes_patch)
    assert netconvert_join_patch_args(nodes_patch) == ["--node-files", str(nodes_patch)]

    root = ET.parse(nodes_patch).getroot()
    assert [element.attrib["nodes"] for element in root.findall("join")] == ["n1 n2 n3"]
    assert [element.attrib["nodes"] for element in root.findall("joinExclude")] == [
        "r1 r2",
        "ramp_a ramp_b",
    ]


def test_junction_join_definition_skips_invalid_single_node_groups(tmp_path) -> None:
    report = build_junction_join_definition(
        [
            {
                "source": "topology_audit",
                "candidate_id": "C001",
                "decision": "join",
                "node_ids": "n1",
                "reason": "not enough nodes to join",
            }
        ],
        output_dir=tmp_path,
        prefix="demo",
    )

    assert report["status"] == "pass"
    assert report["explicit_join_count"] == 0
    assert report["invalid_candidate_count"] == 1
    assert "C001" in report["invalid_candidates"][0]["candidate_id"]


def test_unconfirmed_topology_join_candidate_stays_in_map_review(tmp_path) -> None:
    report = build_junction_join_definition(
        [
            {
                "source": "topology_audit",
                "candidate_id": "C001",
                "decision": "join",
                "confidence": "medium",
                "node_ids": ["n1", "n2", "n3"],
                "reason": "approach-axis geometry indicates a cross intersection",
            }
        ],
        output_dir=tmp_path,
        prefix="demo",
    )

    assert report["explicit_join_count"] == 0
    assert report["join_exclude_count"] == 1
    assert report["needs_map_review_count"] == 1
    assert report["records"][0]["decision"] == "needs_map_review"

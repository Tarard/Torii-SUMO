from torii_sumo.core.junction_aggregation import _aggregation_candidates
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

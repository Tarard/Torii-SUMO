import xml.etree.ElementTree as ET
from pathlib import Path

from torii_sumo.core.junction_aggregation import _aggregation_candidates, build_junction_aggregation_variant
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


def test_overlapping_reference_supported_group_uses_reference_core_nodes() -> None:
    overlap_report = {
        "overlapping_junction_groups": [
            {
                "group_id": "OJ009",
                "node_ids": ["281967823", "305519232", "extra_footway", "extra_dead_end"],
                "reference_join_status": "reference_join_supported",
                "reference_join_ids": [
                    "cluster_281967823_305519232_7009179649_7626856596_7626856598_7626856599"
                ],
                "recommendation": "reference_join_supported",
            },
            {
                "group_id": "OJ010",
                "node_ids": ["needs_a", "needs_b", "needs_c"],
                "recommendation": "same_physical_intersection_review",
            },
        ]
    }

    candidates = _aggregation_candidates(
        topology_audit_report=None,
        reference_join_audit_report=None,
        overlapping_junction_audit_report=overlap_report,
    )

    assert candidates == [
        {
            "source": "overlapping_junction_audit",
            "candidate_id": "OJ009",
            "decision": "join",
            "confidence": "reference_matched",
            "node_ids": "281967823;305519232;7009179649;7626856596;7626856598;7626856599",
            "reason": "reference join cluster confirms the physical-intersection core",
            "google_maps_url": "",
        }
    ]


def test_reference_join_audit_uses_matched_candidate_node_ids() -> None:
    reference_join_report = {
        "matched_cases": [
            {
                "reference_id": "cluster_a_b_c",
                "matched_candidate_node_ids": ["a", "b", "c"],
                "learned_rule": "tum_like_join_candidate",
            }
        ]
    }

    candidates = _aggregation_candidates(
        topology_audit_report=None,
        reference_join_audit_report=reference_join_report,
    )

    assert candidates[0]["decision"] == "join"
    assert candidates[0]["confidence"] == "reference_matched"
    assert candidates[0]["node_ids"] == "a;b;c"


def test_duplicate_overlapping_join_candidates_are_collapsed() -> None:
    overlap_report = {
        "overlapping_junction_groups": [
            {
                "group_id": "OJ001",
                "reference_join_status": "reference_join_supported",
                "reference_join_ids": ["cluster_a_b_c"],
            },
            {
                "group_id": "OJ002",
                "reference_join_status": "reference_join_supported",
                "reference_join_ids": ["cluster_a_b_c"],
            },
            {
                "group_id": "OJ003",
                "reference_join_status": "reference_join_supported",
                "reference_join_ids": ["cluster_c_d"],
            },
        ]
    }

    candidates = _aggregation_candidates(
        topology_audit_report=None,
        reference_join_audit_report=None,
        overlapping_junction_audit_report=overlap_report,
    )

    assert [candidate["candidate_id"] for candidate in candidates] == ["OJ001"]


def test_overlapping_human_confirmed_group_uses_join_node_ids() -> None:
    overlap_report = {
        "overlapping_junction_groups": [
            {
                "group_id": "OJ011",
                "node_ids": ["core_a", "core_b", "sidewalk_node"],
                "join_node_ids": ["core_a", "core_b"],
                "manual_correction_status": "confirmed",
            }
        ]
    }

    candidates = _aggregation_candidates(
        topology_audit_report=None,
        reference_join_audit_report=None,
        overlapping_junction_audit_report=overlap_report,
    )

    assert candidates[0]["decision"] == "join"
    assert candidates[0]["confidence"] == "map_confirmed"
    assert candidates[0]["node_ids"] == "core_a;core_b"


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


def test_junction_aggregation_variant_runs_netconvert_with_absolute_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    Path("candidate.net.xml").write_text("<net/>", encoding="utf-8")

    def fake_command(command, **kwargs):
        assert kwargs["cwd"] == Path("out").resolve()
        assert Path(command[2]).is_absolute()
        assert Path(command[command.index("--node-files") + 1]).is_absolute()
        output_file = Path(command[command.index("--output-file") + 1])
        assert output_file.is_absolute()
        output_file.write_text("<net/>", encoding="utf-8")
        return {"status": "pass", "returncode": 0}

    report = build_junction_aggregation_variant(
        net_file=Path("candidate.net.xml"),
        output_dir=Path("out"),
        topology_audit_report={
            "suspicious_clusters": [
                {
                    "cluster_id": "C001",
                    "aggregation_decision": "join",
                    "aggregation_confidence": "map_confirmed",
                    "node_ids": ["a", "b"],
                }
            ]
        },
        command_runner=fake_command,
    )

    assert report["status"] == "pass"

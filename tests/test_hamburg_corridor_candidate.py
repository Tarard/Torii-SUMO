from __future__ import annotations

import json
from pathlib import Path

from torii_sumo.core.hamburg_corridor_candidate import (
    build_hamburg_corridor_candidate_evidence,
)


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _fixtures(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, Path], Path]:
    lsa = _write(
        tmp_path / "lsa.json",
        {
            "decision": "pass",
            "selections": [
                {
                    "expected_node_id": "a",
                    "selected_node": {
                        "official_name": "A",
                        "signal_type": "K-LSA",
                        "point_geometry": {"coordinates": [10.0, 53.0]},
                    },
                },
                {
                    "expected_node_id": "b",
                    "selected_node": {
                        "official_name": "B",
                        "signal_type": "K-LSA",
                        "point_geometry": {"coordinates": [10.001, 53.0]},
                    },
                },
            ],
        },
    )
    static = _write(
        tmp_path / "static.json",
        {
            "status": "pass",
            "execution_gate": "pass",
            "node_ids": ["a", "b"],
            "nodes": {"a": {}, "b": {}},
        },
    )
    counts = _write(
        tmp_path / "counts.json",
        {
            "status": "pass",
            "execution_gate": "pass",
            "parameters": {"requested_count_node_ids": ["a", "b"]},
            "gates": {
                "full_named_node_coverage": "pass",
                "official_observation_window": "pass",
            },
        },
    )
    plainxml = {
        node_id: _write(
            tmp_path / f"plainxml-{node_id}.json",
            {"status": "pass", "compiled_network_audit": {"status": "pass"}},
        )
        for node_id in ("a", "b")
    }
    roads = _write(
        tmp_path / "roads.json",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "id": "r1",
                    "properties": {
                        "von_netzknoten": "n1",
                        "nach_netzknoten": "n2",
                        "strassenname": "Example",
                        "abschnittslaenge": 100,
                    },
                }
            ],
        },
    )
    return lsa, static, counts, plainxml, roads


def test_candidate_keeps_axis_anchor_as_review_gate(tmp_path: Path) -> None:
    lsa, static, counts, plainxml, roads = _fixtures(tmp_path)
    report = build_hamburg_corridor_candidate_evidence(
        candidate_id="candidate",
        ordered_node_ids=("a", "b"),
        lsa_identity_manifest=lsa,
        static_signal_manifest=static,
        count_manifest=counts,
        plainxml_manifests=plainxml,
        official_road_snapshot=roads,
        axis_paths=(
            {
                "from_node_id": "a",
                "to_node_id": "b",
                "start_network_node": "n1",
                "end_network_node": "n2",
                "links": [{"feature_id": "r1", "direction": "forward"}],
            },
        ),
    )
    assert report["status"] == "review_required"
    assert report["gates"]["official_axis_link_chain"] == "pass"
    assert report["gates"]["official_axis_anchor_binding"] == "review_required"
    assert report["distances"][0]["distance_m"] > 0


def test_candidate_blocks_broken_axis_chain(tmp_path: Path) -> None:
    lsa, static, counts, plainxml, roads = _fixtures(tmp_path)
    report = build_hamburg_corridor_candidate_evidence(
        candidate_id="candidate",
        ordered_node_ids=("a", "b"),
        lsa_identity_manifest=lsa,
        static_signal_manifest=static,
        count_manifest=counts,
        plainxml_manifests=plainxml,
        official_road_snapshot=roads,
        axis_paths=(
            {
                "from_node_id": "a",
                "to_node_id": "b",
                "start_network_node": "wrong",
                "end_network_node": "n2",
                "links": [{"feature_id": "r1", "direction": "forward"}],
            },
        ),
    )
    assert report["status"] == "blocked"
    assert report["gates"]["official_axis_link_chain"] == "blocked"


def test_candidate_blocks_node_type_that_is_not_an_intersection(tmp_path: Path) -> None:
    lsa, static, counts, plainxml, roads = _fixtures(tmp_path)
    payload = json.loads(lsa.read_text(encoding="utf-8"))
    payload["selections"][0]["selected_node"]["signal_type"] = "F-LSA"
    lsa.write_text(json.dumps(payload), encoding="utf-8")

    report = build_hamburg_corridor_candidate_evidence(
        candidate_id="three-intersection-candidate",
        ordered_node_ids=("a", "b"),
        lsa_identity_manifest=lsa,
        static_signal_manifest=static,
        count_manifest=counts,
        plainxml_manifests=plainxml,
        official_road_snapshot=roads,
        axis_paths=(
            {
                "from_node_id": "a",
                "to_node_id": "b",
                "start_network_node": "n1",
                "end_network_node": "n2",
                "links": [{"feature_id": "r1", "direction": "forward"}],
            },
        ),
        required_signal_types=("K-LSA",),
    )

    assert report["status"] == "blocked"
    assert report["gates"]["corridor_node_signal_type"] == "blocked"
    assert report["node_type_policy"] == {
        "required_signal_types": ["K-LSA"],
        "observed_signal_types_by_node": {"a": "F-LSA", "b": "K-LSA"},
        "mismatched_signal_types_by_node": {"a": "F-LSA"},
    }


def test_candidate_records_lane_axis_stitch_gate_without_promoting_network(tmp_path: Path) -> None:
    lsa, static, counts, plainxml, roads = _fixtures(tmp_path)
    stitch = _write(
        tmp_path / "lane-stitch.json",
        {
            "schema": "torii.hamburg-official-map-hh-sib-lane-axis-stitch-plan/v1",
            "status": "review_required",
            "decision": "automatic_abstention_no_materialization_for_unmatched_lanes",
        },
    )
    report = build_hamburg_corridor_candidate_evidence(
        candidate_id="candidate",
        ordered_node_ids=("a", "b"),
        lsa_identity_manifest=lsa,
        static_signal_manifest=static,
        count_manifest=counts,
        plainxml_manifests=plainxml,
        official_road_snapshot=roads,
        axis_paths=(
            {
                "from_node_id": "a",
                "to_node_id": "b",
                "start_network_node": "n1",
                "end_network_node": "n2",
                "links": [{"feature_id": "r1", "direction": "forward"}],
            },
        ),
        map_lane_axis_stitch_plan=stitch,
    )
    assert report["gates"]["official_map_hh_sib_lane_axis_stitch"] == "review_required"
    assert report["automatic_promotion_gate"] == "blocked"

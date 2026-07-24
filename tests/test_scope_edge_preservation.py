from pathlib import Path

from torii_sumo.core.candidate_contracts import file_sha256
from torii_sumo.core.scope_edge_preservation import audit_scope_edge_preservation


def _write_net(path: Path, edge_ids: list[str]) -> None:
    edges = "\n".join(
        f'  <edge id="{edge_id}" from="a" to="b"><lane id="{edge_id}_0" index="0" length="10"/></edge>'
        for edge_id in edge_ids
    )
    path.write_text(f"<net>\n{edges}\n</net>\n", encoding="utf-8")


def test_complete_way_inventory_preserves_branches_and_segments_beyond_graph_bbox(
    tmp_path: Path,
) -> None:
    full = tmp_path / "full-ways.net.xml"
    graph_bbox = tmp_path / "graph-bbox.net.xml"
    final = tmp_path / "candidate.net.xml"
    _write_net(full, ["main#0", "main#1", "side_branch"])
    _write_net(graph_bbox, ["main#0", "side_branch"])
    _write_net(final, ["main#0", "main#1", "side_branch"])
    source_sha = file_sha256(full)

    report = audit_scope_edge_preservation(
        full_way_net_file=full,
        graph_bbox_scope_net_file=graph_bbox,
        final_candidate_net_file=final,
    )

    assert report["status"] == "pass"
    assert report["classification_counts"] == {
        "preserved": 3,
        "internalized": 0,
        "excluded_with_reason": 0,
        "unaccounted": 0,
    }
    assert report["outside_graph_bbox_scope_edge_ids"] == ["main#1"]
    assert {row["edge_id"] for row in report["edges"]} == {
        "main#0",
        "main#1",
        "side_branch",
    }
    assert file_sha256(full) == source_sha


def test_scope_edge_preservation_accepts_hash_bound_join_internalization(
    tmp_path: Path,
) -> None:
    full = tmp_path / "full-ways.net.xml"
    final = tmp_path / "candidate.net.xml"
    _write_net(full, ["approach", "join_seam", "departure"])
    _write_net(final, ["approach", "departure"])
    audit = {
        "schema": "torii.junction-aggregation-preservation/v1",
        "status": "pass",
        "source_sha256": file_sha256(full),
        "variant_sha256": file_sha256(final),
        "absorbed_join_edge_ids": ["join_seam"],
    }

    report = audit_scope_edge_preservation(
        full_way_net_file=full,
        final_candidate_net_file=final,
        junction_preservation_audits=[audit],
    )

    assert report["status"] == "pass"
    assert report["classification_counts"]["internalized"] == 1
    seam = next(row for row in report["edges"] if row["edge_id"] == "join_seam")
    assert seam["classification"] == "internalized"
    assert seam["junction_preservation_audit_index"] == 0


def test_scope_edge_preservation_blocks_unexplained_or_blank_exclusion(
    tmp_path: Path,
) -> None:
    full = tmp_path / "full-ways.net.xml"
    final = tmp_path / "candidate.net.xml"
    _write_net(full, ["kept", "lost", "blank_reason"])
    _write_net(final, ["kept"])

    report = audit_scope_edge_preservation(
        full_way_net_file=full,
        final_candidate_net_file=final,
        explicit_exclusions={"blank_reason": "  "},
        output_file=tmp_path / "scope-ledger.json",
    )

    assert report["status"] == "blocked"
    assert report["unaccounted_edge_ids"] == ["blank_reason", "lost"]
    assert report["empty_exclusion_reason_edge_ids"] == ["blank_reason"]
    assert Path(report["report_file"]).is_file()


def test_scope_edge_preservation_records_exclusion_reason(tmp_path: Path) -> None:
    full = tmp_path / "full-ways.net.xml"
    final = tmp_path / "candidate.net.xml"
    _write_net(full, ["kept", "reviewed_out"])
    _write_net(final, ["kept"])

    report = audit_scope_edge_preservation(
        full_way_net_file=full,
        final_candidate_net_file=final,
        explicit_exclusions={"reviewed_out": "outside the signed Hamburg CAD scope"},
    )

    assert report["status"] == "pass"
    assert report["classification_counts"]["excluded_with_reason"] == 1


def test_scope_edge_preservation_blocks_invalid_join_audit_even_when_edges_remain(
    tmp_path: Path,
) -> None:
    full = tmp_path / "full-ways.net.xml"
    final = tmp_path / "candidate.net.xml"
    _write_net(full, ["kept"])
    _write_net(final, ["kept"])

    report = audit_scope_edge_preservation(
        full_way_net_file=full,
        final_candidate_net_file=final,
        junction_preservation_audits=[
            {
                "schema": "torii.junction-aggregation-preservation/v1",
                "status": "review",
                "source_sha256": file_sha256(full),
                "variant_sha256": file_sha256(final),
                "absorbed_join_edge_ids": [],
            }
        ],
    )

    assert report["status"] == "blocked"
    assert report["unaccounted_edge_count"] == 0
    assert report["junction_preservation_audit_errors"]

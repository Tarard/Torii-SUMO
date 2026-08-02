from __future__ import annotations

from pathlib import Path

from torii_sumo.core import surface_overlap_audit as surface_overlap_audit_module
from torii_sumo.core.surface_overlap_audit import (
    audit_sumo_lane_junction_surface_overlaps,
    compare_sumo_surface_overlap_reports,
)


def test_junction_overlap_only_checks_spatial_candidates(monkeypatch) -> None:
    junctions = {
        str(index): [
            (float(index * 100), 0.0),
            (float(index * 100 + 10), 0.0),
            (float(index * 100 + 10), 10.0),
            (float(index * 100), 10.0),
        ]
        for index in range(200)
    }
    calls = 0
    original = surface_overlap_audit_module._bboxes_overlap

    def counted_overlap(left, right):
        nonlocal calls
        calls += 1
        return original(left, right)

    monkeypatch.setattr(surface_overlap_audit_module, "_bboxes_overlap", counted_overlap)
    findings = surface_overlap_audit_module._junction_overlap_findings(
        junctions,
        minimum_overlap_area_m2=0.01,
    )

    assert findings == []
    assert calls < 200


def _write_net(path: Path, body: str) -> Path:
    path.write_text(f"<net>{body}</net>", encoding="utf-8")
    return path


def test_owner_junction_lane_face_intersections_are_expected_and_excluded(tmp_path: Path) -> None:
    net_file = _write_net(
        tmp_path / "owner-only.net.xml",
        '<edge id="road" from="west" to="east">'
        '<lane id="road_0" index="0" width="3.2" shape="0,0 10,0"/>'
        "</edge>"
        '<junction id="west" type="priority" shape="-1,-2 1,-2 1,2 -1,2"/>'
        '<junction id="east" type="priority" shape="9,-2 11,-2 11,2 9,2"/>',
    )

    report = audit_sumo_lane_junction_surface_overlaps(net_file)

    assert report["status"] == "pass"
    assert report["audited_external_lane_count"] == 1
    assert report["external_lane_non_owner_junction_overlap_count"] == 0
    assert report["junction_junction_overlap_count"] == 0


def test_external_lane_face_overlap_with_non_owner_junction_fails(tmp_path: Path) -> None:
    net_file = _write_net(
        tmp_path / "non-owner.net.xml",
        '<edge id="road" from="west" to="east">'
        '<lane id="road_0" index="0" width="3.2" shape="0,0 10,0"/>'
        "</edge>"
        '<junction id="west" type="priority" shape="-1,-2 1,-2 1,2 -1,2"/>'
        '<junction id="middle" type="priority" shape="4.5,-1 5.5,-1 5.5,1 4.5,1"/>'
        '<junction id="east" type="priority" shape="9,-2 11,-2 11,2 9,2"/>',
    )

    report = audit_sumo_lane_junction_surface_overlaps(net_file)

    assert report["status"] == "fail"
    assert report["external_lane_non_owner_junction_overlap_count"] == 1
    finding = report["external_lane_non_owner_junction_overlaps"][0]
    assert finding["lane_id"] == "road_0"
    assert finding["non_owner_junction_id"] == "middle"
    assert finding["overlap_area_m2"] == 2.0


def test_junction_polygon_area_overlap_fails_with_exact_area(tmp_path: Path) -> None:
    net_file = _write_net(
        tmp_path / "junctions.net.xml",
        '<junction id="first" type="priority" shape="0,0 2,0 2,2 0,2"/>'
        '<junction id="second" type="priority" shape="1,1 3,1 3,3 1,3"/>',
    )

    report = audit_sumo_lane_junction_surface_overlaps(net_file)

    assert report["status"] == "fail"
    assert report["junction_junction_overlap_count"] == 1
    assert report["junction_junction_overlaps"][0] == {
        "first_junction_id": "first",
        "second_junction_id": "second",
        "overlap_area_m2": 1.0,
    }


def test_self_intersecting_junction_polygon_is_a_geometry_error(tmp_path: Path) -> None:
    net_file = _write_net(
        tmp_path / "self-intersection.net.xml",
        '<junction id="bowtie" type="priority" shape="0,0 2,2 0,2 2,0"/>',
    )

    report = audit_sumo_lane_junction_surface_overlaps(net_file)

    assert report["status"] == "fail"
    assert report["geometry_error_count"] == 1
    assert report["geometry_errors"][0]["junction_id"] == "bowtie"
    assert "self-intersecting" in report["geometry_errors"][0]["error"]


def test_invalid_external_lane_geometry_records_both_boundary_junctions(
    tmp_path: Path,
) -> None:
    net_file = _write_net(
        tmp_path / "invalid-lane.net.xml",
        '<edge id="road" from="west" to="east">'
        '<lane id="road_0" index="0" shape="0,0"/>'
        "</edge>"
        '<junction id="west" type="priority" shape="-1,-1 1,-1 1,1 -1,1"/>'
        '<junction id="east" type="priority" shape="9,-1 11,-1 11,1 9,1"/>',
    )

    report = audit_sumo_lane_junction_surface_overlaps(net_file)

    assert report["status"] == "fail"
    assert report["geometry_errors"][0]["from_junction_id"] == "west"
    assert report["geometry_errors"][0]["to_junction_id"] == "east"


def test_internal_lane_and_internal_junction_are_excluded(tmp_path: Path) -> None:
    net_file = _write_net(
        tmp_path / "internal.net.xml",
        '<edge id=":owner_0" function="internal">'
        '<lane id=":owner_0_0" index="0" shape="0,0 5,0"/>'
        "</edge>"
        '<junction id=":owner_0_0" type="internal" shape="1,-1 4,-1 4,1 1,1"/>'
        '<junction id="owner" type="priority" shape="-1,-1 1,-1 1,1 -1,1"/>',
    )

    report = audit_sumo_lane_junction_surface_overlaps(net_file)

    assert report["status"] == "pass"
    assert report["audited_external_lane_count"] == 0
    assert report["audited_junction_count"] == 1


def test_non_area_dead_end_junction_is_explicitly_excluded(tmp_path: Path) -> None:
    net_file = _write_net(
        tmp_path / "dead-end.net.xml",
        '<junction id="dead_end" type="dead_end" shape="0,0"/>'
        '<junction id="area" type="priority" shape="2,0 4,0 4,2 2,2"/>',
    )

    report = audit_sumo_lane_junction_surface_overlaps(net_file)

    assert report["status"] == "pass"
    assert report["audited_junction_count"] == 1
    assert report["non_area_junction_exclusion_count"] == 1
    assert report["non_area_junction_exclusions"] == [
        {
            "junction_id": "dead_end",
            "reason": "fewer_than_three_distinct_shape_points",
        }
    ]


def test_report_is_written_without_mutating_source(tmp_path: Path) -> None:
    net_file = _write_net(
        tmp_path / "clean.net.xml",
        '<junction id="only" type="priority" shape="0,0 2,0 2,2 0,2"/>',
    )
    original = net_file.read_bytes()
    report_file = tmp_path / "audit" / "surface-overlap.json"

    report = audit_sumo_lane_junction_surface_overlaps(net_file, report_file=report_file)

    assert report["status"] == "pass"
    assert report["source_network_mutation"] is False
    assert report_file.is_file()
    assert len(report["report_sha256"]) == 64
    assert net_file.read_bytes() == original


def test_report_cannot_overwrite_source_network(tmp_path: Path) -> None:
    net_file = _write_net(
        tmp_path / "source.net.xml",
        '<junction id="only" type="priority" shape="0,0 2,0 2,2 0,2"/>',
    )
    original = net_file.read_bytes()

    try:
        audit_sumo_lane_junction_surface_overlaps(net_file, report_file=net_file)
    except ValueError as exc:
        assert "must not overwrite source" in str(exc)
    else:
        raise AssertionError("expected source overwrite guard to fail")

    assert net_file.read_bytes() == original


def test_invalid_thresholds_are_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "missing.net.xml"

    for invalid in (0.0, -1.0, float("inf"), float("nan")):
        try:
            audit_sumo_lane_junction_surface_overlaps(
                missing,
                minimum_overlap_area_m2=invalid,
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid threshold to fail: {invalid!r}")


def test_bounded_comparison_exposes_inherited_findings_and_resolved_focus(tmp_path: Path) -> None:
    baseline_file = _write_net(
        tmp_path / "baseline.net.xml",
        '<junction id="focus_a" type="priority" shape="0,0 2,0 2,2 0,2"/>'
        '<junction id="focus_b" type="priority" shape="1,1 3,1 3,3 1,3"/>'
        '<junction id="outside_a" type="priority" shape="10,0 12,0 12,2 10,2"/>'
        '<junction id="outside_b" type="priority" shape="11,1 13,1 13,3 11,3"/>',
    )
    candidate_file = _write_net(
        tmp_path / "candidate.net.xml",
        '<junction id="focus_joined" type="priority" shape="0,0 3,0 3,3 0,3"/>'
        '<junction id="outside_a" type="priority" shape="10,0 12,0 12,2 10,2"/>'
        '<junction id="outside_b" type="priority" shape="11,1 13,1 13,3 11,3"/>',
    )
    baseline = audit_sumo_lane_junction_surface_overlaps(baseline_file)
    candidate = audit_sumo_lane_junction_surface_overlaps(candidate_file)

    comparison = compare_sumo_surface_overlap_reports(
        baseline,
        candidate,
        focus_junction_ids={"focus_a", "focus_b", "focus_joined"},
    )

    assert comparison["status"] == "pass"
    assert comparison["baseline_global_finding_count"] == 2
    assert comparison["candidate_global_finding_count"] == 1
    assert comparison["resolved_finding_count"] == 1
    assert comparison["introduced_finding_count"] == 0
    assert comparison["inherited_out_of_scope_finding_count"] == 1
    assert comparison["baseline_focus_finding_count"] == 1
    assert comparison["candidate_focus_finding_count"] == 0


def test_bounded_comparison_fails_on_new_focus_overlap(tmp_path: Path) -> None:
    baseline_file = _write_net(
        tmp_path / "baseline.net.xml",
        '<junction id="first" type="priority" shape="0,0 1,0 1,1 0,1"/>'
        '<junction id="second" type="priority" shape="3,0 4,0 4,1 3,1"/>',
    )
    candidate_file = _write_net(
        tmp_path / "candidate.net.xml",
        '<junction id="first" type="priority" shape="0,0 2,0 2,2 0,2"/>'
        '<junction id="second" type="priority" shape="1,1 3,1 3,3 1,3"/>',
    )
    baseline = audit_sumo_lane_junction_surface_overlaps(baseline_file)
    candidate = audit_sumo_lane_junction_surface_overlaps(candidate_file)

    comparison = compare_sumo_surface_overlap_reports(
        baseline,
        candidate,
        focus_junction_ids={"first", "second"},
    )

    assert comparison["status"] == "fail"
    assert comparison["introduced_finding_count"] == 1
    assert comparison["candidate_focus_finding_count"] == 1


def test_bounded_comparison_allows_inherited_out_of_scope_geometry_error(
    tmp_path: Path,
) -> None:
    body = (
        '<junction id="focus" type="priority" shape="0,0 2,0 2,2 0,2"/>'
        '<junction id="outside" type="priority" shape="10,0 12,2 10,2 12,0"/>'
    )
    baseline = audit_sumo_lane_junction_surface_overlaps(
        _write_net(tmp_path / "baseline-errors.net.xml", body)
    )
    candidate = audit_sumo_lane_junction_surface_overlaps(
        _write_net(tmp_path / "candidate-errors.net.xml", body)
    )

    comparison = compare_sumo_surface_overlap_reports(
        baseline,
        candidate,
        focus_junction_ids={"focus"},
    )

    assert comparison["status"] == "pass"
    assert comparison["candidate_geometry_error_count"] == 1
    assert comparison["introduced_geometry_error_count"] == 0
    assert comparison["candidate_focus_geometry_error_count"] == 0

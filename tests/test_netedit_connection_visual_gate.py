from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

import torii_sumo.core.netedit_connection_visual_gate as visual_gate
from torii_sumo.core.candidate_contracts import file_sha256
from torii_sumo.core.netedit_connection_visual_gate import (
    analyze_connection_pair,
    canvas_click_for_world_point,
    lane_capture_spec,
    lane_pair_coverage,
    point_before_lane_end,
    write_visual_gate_report,
)


def test_geometry_and_missing_conflict_layer(tmp_path: Path) -> None:
    assert point_before_lane_end(((0.0, 0.0), (20.0, 0.0)), distance_m=5.0) == (15.0, 0.0)
    assert canvas_click_for_world_point(
        point=(1330.18, 1889.68),
        center=(1365.74, 1922.36),
        conv_boundary=(0.0, 0.0, 2738.51, 3169.57),
        canvas_rect=(130, 64, 797, 537),
        zoom=2500.0,
    ) == (331, 422)

    teacher = Image.new("RGB", (240, 180), "white")
    candidate = teacher.copy()
    ImageDraw.Draw(teacher).line((30, 90, 210, 90), fill=(255, 255, 0), width=8)
    ImageDraw.Draw(teacher).line((30, 110, 210, 110), fill=(0, 255, 255), width=8)
    ImageDraw.Draw(candidate).line((30, 110, 210, 110), fill=(0, 255, 255), width=8)
    teacher_file, candidate_file = tmp_path / "teacher.png", tmp_path / "candidate.png"
    teacher.save(teacher_file)
    candidate.save(candidate_file)

    report = analyze_connection_pair(teacher_file, candidate_file)
    assert report["status"] == "fail"
    assert "conflict_layer_missing" in report["reasons"]


def test_lane_spec_maps_projection_and_blocks_non_motor_pair(tmp_path: Path) -> None:
    teacher = tmp_path / "teacher.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    template = """<net><location netOffset=\"{offset}\" convBoundary=\"0,0,100,100\"/>
      <edge id=\"e\"><lane id=\"e_0\" index=\"0\" {permissions} shape=\"10,10 20,20\"/></edge>
      <junction id=\"j\" x=\"20\" y=\"20\" incLanes=\"e_0\"/></net>"""
    teacher.write_text(template.format(offset="100,200", permissions="disallow=\"pedestrian\""), encoding="utf-8")
    candidate.write_text(template.format(offset="-10,-20", permissions="allow=\"pedestrian\""), encoding="utf-8")

    spec = lane_capture_spec(teacher, junction_id="j", lane_id="e_0")
    assert spec["projected_center"] == (-80.0, -180.0)
    assert spec["motor_vehicle"] is True
    assert lane_capture_spec(candidate, junction_id="j", lane_id="e_0")["motor_vehicle"] is False

    coverage = lane_pair_coverage(
        teacher,
        candidate,
        teacher_junction="j",
        candidate_junction="j",
        lane_pairs=(),
    )
    assert coverage["status"] == "blocked"
    assert coverage["missing_teacher_motor_lanes"] == ["e_0"]


def test_compact_report_only_exposes_failed_images(tmp_path: Path) -> None:
    teacher, candidate = tmp_path / "teacher.net.xml", tmp_path / "candidate.net.xml"
    teacher.write_text("<net/>", encoding="utf-8")
    candidate.write_text("<net/>", encoding="utf-8")
    report = write_visual_gate_report(
        output_dir=tmp_path / "out",
        teacher_net_file=teacher,
        candidate_net_file=candidate,
        lane_reports=[{"status": "pass", "comparison_file": "unused.png"}],
    )
    assert report["status"] == "pass"
    assert report["comparison_images"] == []
    assert Path(report["report_file"]).is_file()


def test_semantic_mask_keeps_palette_and_angular_evidence(tmp_path: Path) -> None:
    image = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.line((50, 60, 50, 90), fill=(0, 255, 255), width=1)
    draw.line((60, 50, 90, 50), fill=(0, 255, 0), width=1)
    source = tmp_path / "source.png"
    mask = tmp_path / "mask.png"
    image.save(source)

    report = visual_gate.write_semantic_mask(source, mask, center=(50, 50))

    assert report["layers"]["source"]["pixel_count"] == 31
    assert report["layers"]["source"]["component_count"] == 1
    assert report["layers"]["source"]["angular_bins"] == [6]
    assert report["layers"]["target"]["angular_bins"] == [0]
    assert report["sha256"] == file_sha256(mask)
    with Image.open(mask) as opened:
        assert opened.mode == "P"


def test_visual_comparison_rejects_wrong_target_direction(tmp_path: Path) -> None:
    teacher = Image.new("RGB", (240, 180), "white")
    candidate = teacher.copy()
    for image in (teacher, candidate):
        ImageDraw.Draw(image).line((120, 110, 120, 165), fill=(0, 255, 255), width=4)
    ImageDraw.Draw(teacher).line((130, 90, 210, 90), fill=(0, 255, 0), width=4)
    ImageDraw.Draw(candidate).line((30, 90, 110, 90), fill=(0, 255, 0), width=4)
    teacher_file, candidate_file = tmp_path / "teacher.png", tmp_path / "candidate.png"
    teacher.save(teacher_file)
    candidate.save(candidate_file)

    report = analyze_connection_pair(teacher_file, candidate_file)

    assert report["status"] == "fail"
    assert "target_direction_missing" in report["reasons"]

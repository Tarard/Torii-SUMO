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
    assert visual_gate.lane_click_points(((0.0, 0.0), (10.0, 0.0))) == (
        (2.5, 0.0),
        (4.0, 0.0),
        (6.0, 0.0),
        (8.0, 0.0),
    )
    assert visual_gate.lane_click_points(((0.0, 0.0), (40.0, 0.0))) == (
        (20.0, 0.0),
        (28.0, 0.0),
        (32.0, 0.0),
        (34.0, 0.0),
        (36.0, 0.0),
        (38.0, 0.0),
    )
    short_clicks = tuple((round(x, 2), y) for x, y in visual_gate.lane_click_points(((0.0, 0.0), (0.2, 0.0))))
    assert short_clicks == (
        (0.05, 0.0),
        (0.1, 0.0),
        (0.15, 0.0),
    )
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

    report = analyze_connection_pair(
        teacher_file,
        candidate_file,
        teacher_center=(120, 90),
        candidate_center=(120, 90),
    )
    assert report["status"] == "fail"
    assert "conflict_layer_missing" in report["reasons"]


def test_visual_gate_rejects_candidate_only_dark_target_layer(tmp_path: Path) -> None:
    teacher = Image.new("RGB", (240, 180), "white")
    candidate = teacher.copy()
    for image in (teacher, candidate):
        ImageDraw.Draw(image).line((30, 90, 210, 90), fill=(0, 255, 255), width=8)
    ImageDraw.Draw(candidate).line((80, 120, 180, 120), fill=(64, 0, 64), width=8)
    teacher_file, candidate_file = tmp_path / "teacher.png", tmp_path / "candidate.png"
    teacher.save(teacher_file)
    candidate.save(candidate_file)

    report = analyze_connection_pair(
        teacher_file,
        candidate_file,
        teacher_center=(120, 90),
        candidate_center=(120, 90),
    )

    assert report["status"] == "fail"
    assert report["reasons"] == ["dark_target_layer_extra"]


def test_visual_gate_ignores_dark_target_background_when_primary_target_matches(tmp_path: Path) -> None:
    teacher = Image.new("RGB", (240, 180), "white")
    candidate = teacher.copy()
    for image in (teacher, candidate):
        draw = ImageDraw.Draw(image)
        draw.line((30, 90, 120, 90), fill=(0, 255, 255), width=8)
        draw.line((120, 90, 210, 90), fill=(0, 255, 0), width=8)
    ImageDraw.Draw(candidate).line((80, 120, 180, 120), fill=(64, 0, 64), width=8)
    teacher_file, candidate_file = tmp_path / "teacher.png", tmp_path / "candidate.png"
    teacher.save(teacher_file)
    candidate.save(candidate_file)

    report = analyze_connection_pair(
        teacher_file,
        candidate_file,
        teacher_center=(120, 90),
        candidate_center=(120, 90),
    )

    assert report["status"] == "pass"


def test_candidate_zoom_preserves_world_scale_across_different_network_bounds() -> None:
    zoom = visual_gate.normalized_viewport_zoom(
        reference_boundary=(0.0, 0.0, 10000.0, 10000.0),
        target_boundary=(0.0, 0.0, 28000.0, 15000.0),
        reference_zoom=2500.0,
        viewport_size=(1400, 1000),
    )

    assert round(zoom, 1) == 5000.0


def test_native_zoom_offset_and_test_file_are_deterministic(tmp_path: Path) -> None:
    canvas = (230, 64, 1394, 885)
    zoom = visual_gate.fit_connection_zoom(
        points=((0.0, 0.0), (40.0, 0.0), (-40.0, 10.0)),
        center=(0.0, 0.0),
        conv_boundary=(0.0, 0.0, 500.0, 500.0),
        canvas_rect=canvas,
        requested_zoom=2500.0,
        margin_px=64,
    )

    assert 0 < zoom < 2500.0
    assert visual_gate.native_test_click_offset((1151, 579), canvas) == (617, 347)
    destination = tmp_path / "lane.test.py"
    visual_gate.write_native_connection_test(destination, offset=(617, 347))
    assert destination.read_text(encoding="utf-8") == (
        'netedit.changeMode("connection")\n'
        "netedit.leftClickOffset(referencePosition, netedit.positions.reference, 617, 347)\n"
    )


def test_expected_lane_semantics_rejects_sidebar_and_wrong_lane(tmp_path: Path) -> None:
    image = Image.new("RGB", (300, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 40, 150), fill=(0, 255, 255))
    draw.line((120, 90, 210, 90), fill=(0, 255, 255), width=1)
    draw.line((215, 70, 280, 70), fill=(0, 255, 0), width=8)
    source = tmp_path / "capture.png"
    image.save(source)

    passed = visual_gate.verify_expected_lane_semantics(
        source,
        canvas_rect=(50, 0, 300, 180),
        source_point=(150, 90),
        target_point_groups=(((240, 120), (240, 70)),),
    )
    short_lane = visual_gate.verify_expected_lane_semantics(
        source,
        canvas_rect=(50, 0, 300, 180),
        source_point=(150, 105),
        target_point_groups=(((240, 70),),),
    )
    wrong = visual_gate.verify_expected_lane_semantics(
        source,
        canvas_rect=(50, 0, 300, 180),
        source_point=(150, 120),
        target_point_groups=(((240, 70),),),
    )

    assert passed["status"] == "pass"
    assert short_lane["status"] == "pass"
    assert wrong == {
        "status": "review_required",
        "reasons": ["registered_source_lane_not_selected"],
        "target_lane_group_count": 1,
        "visible_target_lane_group_count": 1,
        "occluded_target_lane_group_count": 0,
    }


def test_expected_lane_semantics_counts_occluded_target_groups(tmp_path: Path) -> None:
    image = Image.new("RGB", (300, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.line((120, 90, 180, 90), fill=(0, 255, 255), width=8)
    draw.line((210, 70, 280, 70), fill=(0, 255, 0), width=8)
    source = tmp_path / "capture.png"
    image.save(source)

    report = visual_gate.verify_expected_lane_semantics(
        source,
        canvas_rect=(50, 0, 300, 180),
        source_point=(150, 90),
        target_point_groups=(((240, 70),), ((240, 130),)),
    )

    assert report == {
        "status": "review_required",
        "reasons": ["registered_target_lane_not_visible"],
        "target_lane_group_count": 2,
        "visible_target_lane_group_count": 1,
        "occluded_target_lane_group_count": 1,
    }


def test_expected_lane_semantics_samples_registered_points_without_full_image_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = Image.new("RGB", (300, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.line((120, 90, 180, 90), fill=(0, 255, 255), width=8)
    draw.line((210, 70, 280, 70), fill=(0, 255, 0), width=8)
    source = tmp_path / "capture.png"
    image.save(source)
    monkeypatch.setattr(
        visual_gate,
        "_palette_points",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("full scan")),
    )

    report = visual_gate.verify_expected_lane_semantics(
        source,
        canvas_rect=(50, 0, 300, 180),
        source_point=(150, 90),
        target_point_groups=(((240, 70),),),
    )

    assert report == {
        "status": "pass",
        "reasons": [],
        "target_lane_group_count": 1,
        "visible_target_lane_group_count": 1,
        "occluded_target_lane_group_count": 0,
    }


def test_visual_comparison_accepts_explicit_visible_lane_radius(tmp_path: Path) -> None:
    teacher = Image.new("RGB", (600, 600), "white")
    candidate = teacher.copy()
    for image in (teacher, candidate):
        ImageDraw.Draw(image).line((540, 300, 570, 300), fill=(0, 255, 255), width=4)
    teacher_file, candidate_file = tmp_path / "teacher.png", tmp_path / "candidate.png"
    teacher.save(teacher_file)
    candidate.save(candidate_file)

    default = analyze_connection_pair(teacher_file, candidate_file, teacher_center=(300, 300), candidate_center=(300, 300))
    widened = analyze_connection_pair(
        teacher_file,
        candidate_file,
        teacher_center=(300, 300),
        candidate_center=(300, 300),
        semantic_radius=280,
    )

    assert default["status"] == "review_required"
    assert widened["status"] == "pass"


def test_visual_comparison_ignores_sidebar_palette_and_detects_unselected_canvas(tmp_path: Path) -> None:
    teacher = Image.new("RGB", (200, 100), "white")
    candidate = teacher.copy()
    ImageDraw.Draw(teacher).line((80, 50, 180, 50), fill=(0, 255, 255), width=4)
    ImageDraw.Draw(candidate).rectangle((0, 0, 40, 80), fill=(0, 255, 255))
    teacher_file, candidate_file = tmp_path / "teacher.png", tmp_path / "candidate.png"
    teacher.save(teacher_file)
    candidate.save(candidate_file)

    report = analyze_connection_pair(
        teacher_file,
        candidate_file,
        teacher_canvas_rect=(50, 0, 200, 100),
        candidate_canvas_rect=(50, 0, 200, 100),
    )

    assert report["status"] == "review_required"
    assert report["reasons"] == ["source_lane_not_selected"]


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


def test_semantic_mask_excludes_palette_outside_registered_lane_focus(tmp_path: Path) -> None:
    image = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.line((50, 60, 50, 90), fill=(0, 255, 255), width=2)
    draw.line((70, 20, 95, 20), fill=(255, 0, 255), width=2)
    source, mask = tmp_path / "source.png", tmp_path / "mask.png"
    image.save(source)

    report = visual_gate.write_semantic_mask(
        source,
        mask,
        center=(50, 50),
        focus_points=((50, 75),),
        focus_radius=20,
    )

    assert report["layers"]["source"]["pixel_count"] > 0
    assert report["layers"]["pass"]["pixel_count"] == 0


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


def test_visual_comparison_ignores_tiny_palette_speckles(tmp_path: Path) -> None:
    teacher = Image.new("RGB", (600, 500), "white")
    candidate = teacher.copy()
    for image in (teacher, candidate):
        ImageDraw.Draw(image).line((220, 250, 380, 250), fill=(0, 255, 255), width=4)
    candidate_draw = ImageDraw.Draw(candidate)
    candidate_draw.line((10, 10, 590, 10), fill=(0, 255, 255), width=8)
    for x in range(10, 590, 10):
        candidate_draw.point((x, 20 + x % 30), fill=(0, 255, 255))
    teacher_file, candidate_file = tmp_path / "teacher.png", tmp_path / "candidate.png"
    teacher.save(teacher_file)
    candidate.save(candidate_file)

    report = analyze_connection_pair(teacher_file, candidate_file)

    assert report["status"] == "pass"
    assert report["layers"]["source"]["teacher_component_count"] == 1
    assert report["layers"]["source"]["candidate_component_count"] == 1


def test_visual_comparison_ignores_palette_layers_outside_registered_lane_focus(tmp_path: Path) -> None:
    teacher = Image.new("RGB", (240, 180), "white")
    candidate = teacher.copy()
    for image in (teacher, candidate):
        ImageDraw.Draw(image).line((120, 100, 120, 160), fill=(0, 255, 255), width=4)
        ImageDraw.Draw(image).line((120, 90, 180, 90), fill=(0, 255, 0), width=4)
    ImageDraw.Draw(candidate).line((40, 40, 80, 40), fill=(255, 0, 255), width=4)
    teacher_file, candidate_file = tmp_path / "teacher.png", tmp_path / "candidate.png"
    teacher.save(teacher_file)
    candidate.save(candidate_file)

    unscoped = analyze_connection_pair(teacher_file, candidate_file)
    focused = analyze_connection_pair(
        teacher_file,
        candidate_file,
        teacher_focus_points=((120, 120), (160, 90)),
        candidate_focus_points=((120, 120), (160, 90)),
        focus_radius=24,
    )

    assert unscoped["status"] == "fail"
    assert unscoped["reasons"] == ["pass_layer_extra"]
    assert focused["status"] == "pass"


def test_visual_comparison_keeps_palette_layers_inside_registered_lane_focus(tmp_path: Path) -> None:
    teacher = Image.new("RGB", (240, 180), "white")
    candidate = teacher.copy()
    for image in (teacher, candidate):
        ImageDraw.Draw(image).line((120, 100, 120, 160), fill=(0, 255, 255), width=4)
    ImageDraw.Draw(candidate).line((145, 90, 185, 90), fill=(255, 0, 255), width=4)
    teacher_file, candidate_file = tmp_path / "teacher.png", tmp_path / "candidate.png"
    teacher.save(teacher_file)
    candidate.save(candidate_file)

    report = analyze_connection_pair(
        teacher_file,
        candidate_file,
        teacher_focus_points=((120, 120), (165, 90)),
        candidate_focus_points=((120, 120), (165, 90)),
        focus_radius=24,
    )

    assert report["status"] == "fail"
    assert report["reasons"] == ["pass_layer_extra"]


def test_run_visual_gate_scopes_palette_to_capture_focus(tmp_path: Path, monkeypatch) -> None:
    net = tmp_path / "net.xml"
    net.write_text(
        "<net>"
        '<location netOffset="0,0" convBoundary="0,0,100,100"/>'
        '<edge id="in" from="a" to="j"><lane id="in_0" index="0" shape="0,50 50,50"/></edge>'
        '<edge id="out" from="j" to="b"><lane id="out_0" index="0" shape="50,50 100,50"/></edge>'
        '<junction id="j" type="priority" x="50" y="50" incLanes="in_0" intLanes=""/>'
        '<connection from="in" to="out" fromLane="0" toLane="0"/>'
        "</net>",
        encoding="utf-8",
    )
    teacher = Image.new("RGB", (240, 180), "white")
    candidate = teacher.copy()
    for image in (teacher, candidate):
        ImageDraw.Draw(image).line((120, 100, 120, 160), fill=(0, 255, 255), width=4)
        ImageDraw.Draw(image).line((120, 90, 180, 90), fill=(0, 255, 0), width=4)
    ImageDraw.Draw(candidate).line((40, 40, 80, 40), fill=(255, 0, 255), width=4)
    teacher_file, candidate_file = tmp_path / "teacher.png", tmp_path / "candidate.png"
    teacher.save(teacher_file)
    candidate.save(candidate_file)

    def capture(_spec, *, output_dir, zoom, window_size):
        output_dir.mkdir(parents=True, exist_ok=True)
        source = teacher_file if output_dir.name == "teacher" else candidate_file
        return {
            "status": "pass",
            "reasons": [],
            "click": [120, 120],
            "canvas_rect": [0, 0, 240, 180],
            "semantic_focus_points": [[120, 120], [160, 90]],
            "semantic_focus_radius": 24,
            "screenshot_file": str(source),
            "screenshot_sha256": file_sha256(source),
        }

    monkeypatch.setattr(visual_gate, "_capture", capture)
    report = visual_gate.run_connection_visual_gate(
        teacher_net_file=net,
        candidate_net_file=net,
        teacher_junction="j",
        candidate_junction="j",
        lane_pairs=(("in_0", "in_0"),),
        output_dir=tmp_path / "gate",
    )

    assert report["status"] == "pass"


def test_tile_capture_opens_once_and_clicks_every_lane(tmp_path: Path) -> None:
    class FakeSession:
        hwnd = 17

        def __init__(self) -> None:
            self.open_count = 0
            self.actions = []
            self.abort_reason = ""
            self.index = 0

        def open(self):
            self.open_count += 1
            return {"status": "open"}

        def observe(self, _label):
            screenshot = tmp_path / "observe.png"
            Image.new("RGB", (100, 100), "white").save(screenshot)
            return {"screenshot_sha256": "a" * 64, "screenshot_file": str(screenshot)}

        def act(self, action):
            self.actions.append(action)
            self.index += 1
            screenshot = tmp_path / f"act-{self.index}.png"
            Image.new("RGB", (100, 100), "white").save(screenshot)
            return {"screenshot_sha256": f"{self.index:064x}", "screenshot_file": str(screenshot)}

        def abort(self, reason):
            self.abort_reason = reason
            return {"status": "aborted"}

    session = FakeSession()
    specs = [
        {"lane_id": "a_0", "shape": ((0.0, 0.0), (20.0, 0.0)), "center": (20.0, 0.0), "conv_boundary": (0.0, 0.0, 100.0, 100.0)},
        {"lane_id": "b_0", "shape": ((0.0, 10.0), (20.0, 10.0)), "center": (20.0, 10.0), "conv_boundary": (0.0, 0.0, 100.0, 100.0)},
    ]

    captures = visual_gate.capture_connection_tile(
        session=session,
        specs=specs,
        viewport_center=(10.0, 5.0),
        zoom=100.0,
        destination=tmp_path / "captures",
        canvas_rect=(0, 0, 800, 600),
    )

    assert session.open_count == 1
    assert [action["type"] for action in session.actions] == ["key", "click", "click"]
    assert len(captures) == 2
    assert all(Path(row["screenshot_file"]).is_file() for row in captures)
    assert captures[0]["junction_pixel"] == [460, 330]
    assert captures[0]["canvas_rect"] == [0, 0, 800, 600]
    assert session.abort_reason == "visual_tile_capture_complete"

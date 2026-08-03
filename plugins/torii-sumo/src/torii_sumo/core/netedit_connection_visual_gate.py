from __future__ import annotations

import collections
import math
from pathlib import Path
import shutil
import time
from typing import Any, Sequence
import xml.etree.ElementTree as ET

from PIL import Image

from .artifact_io import write_json_atomic
from .candidate_contracts import file_sha256
from .netedit import NeteditTargetSession, _windows_modules


_PALETTE = {
    "source": (0, 255, 255),
    "target": (0, 255, 0),
    "conflict": (255, 255, 0),
    "pass": (255, 0, 255),
}


def point_before_lane_end(
    points: Sequence[tuple[float, float]], *, distance_m: float = 8.0
) -> tuple[float, float]:
    if len(points) < 2 or distance_m <= 0:
        raise ValueError("lane shape needs two points and a positive distance")
    remaining, end = distance_m, points[-1]
    for start in reversed(points[:-1]):
        length = math.dist(start, end)
        if length >= remaining and length > 0:
            ratio = remaining / length
            return end[0] + ratio * (start[0] - end[0]), end[1] + ratio * (start[1] - end[1])
        remaining, end = remaining - length, start
    return points[0]


def lane_click_points(points: Sequence[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    length = sum(math.dist(start, end) for start, end in zip(points, points[1:], strict=False))
    distances = (min(8.0, length * 0.75), min(4.0, length * 0.5), min(2.0, length * 0.25))
    return tuple(dict.fromkeys(point_before_lane_end(points, distance_m=distance) for distance in distances))


def canvas_click_for_world_point(
    *,
    point: tuple[float, float],
    center: tuple[float, float],
    conv_boundary: tuple[float, float, float, float],
    canvas_rect: tuple[int, int, int, int],
    zoom: float,
) -> tuple[int, int]:
    left, top, right, bottom = canvas_rect
    width, height = right - left, bottom - top
    x0, y0, x1, y1 = conv_boundary
    if width <= 0 or height <= 0 or x1 <= x0 or y1 <= y0 or zoom <= 0:
        raise ValueError("invalid canvas, network boundary, or zoom")
    scale = zoom / 100.0 * min(width / (x1 - x0), height / (y1 - y0))
    return (
        round(left + width / 2 + (point[0] - center[0]) * scale),
        round(top + height / 2 - (point[1] - center[1]) * scale),
    )


def normalized_viewport_zoom(
    *,
    reference_boundary: tuple[float, float, float, float],
    target_boundary: tuple[float, float, float, float],
    reference_zoom: float,
    viewport_size: tuple[int, int],
) -> float:
    width, height = viewport_size

    def boundary_scale(boundary: tuple[float, float, float, float]) -> float:
        x0, y0, x1, y1 = boundary
        if width <= 0 or height <= 0 or x1 <= x0 or y1 <= y0:
            raise ValueError("invalid viewport or network boundary")
        return min(width / (x1 - x0), height / (y1 - y0))

    if reference_zoom <= 0:
        raise ValueError("reference zoom must be positive")
    return reference_zoom * boundary_scale(reference_boundary) / boundary_scale(target_boundary)


def lane_capture_spec(net_file: Path | str, *, junction_id: str, lane_id: str) -> dict[str, Any]:
    path = Path(net_file).resolve()
    root = ET.parse(path).getroot()
    location = root.find("location")
    if location is None:
        raise ValueError(f"network has no location element: {path}")
    offset = _numbers(location.get("netOffset", ""), 2, "netOffset")
    boundary = _numbers(location.get("convBoundary", ""), 4, "convBoundary")
    junction = next((item for item in root.findall("junction") if item.get("id") == junction_id), None)
    lane = next((item for item in root.iter("lane") if item.get("id") == lane_id), None)
    if junction is None or lane is None:
        raise ValueError(f"junction {junction_id!r} or lane {lane_id!r} is absent from {path}")
    if lane_id not in junction.get("incLanes", "").split():
        raise ValueError(f"lane {lane_id!r} is not incoming to junction {junction_id!r}")
    shape = tuple(
        tuple(float(value) for value in point.split(","))
        for point in lane.get("shape", "").split()
    )
    if any(len(point) != 2 for point in shape) or len(shape) < 2:
        raise ValueError(f"lane {lane_id!r} has no usable two-dimensional shape")
    center = float(junction.get("x", "nan")), float(junction.get("y", "nan"))
    allow = set(lane.get("allow", "").split())
    disallow = set(lane.get("disallow", "").split())
    return {
        "net_file": str(path),
        "junction_id": junction_id,
        "lane_id": lane_id,
        "shape": shape,
        "center": center,
        "projected_center": (center[0] - offset[0], center[1] - offset[1]),
        "conv_boundary": boundary,
        "motor_vehicle": "passenger" not in disallow and (not allow or "passenger" in allow),
    }


def _motor_incoming_lanes(net_file: Path | str, junction_id: str) -> set[str]:
    root = ET.parse(net_file).getroot()
    junction = next((item for item in root.findall("junction") if item.get("id") == junction_id), None)
    if junction is None:
        raise ValueError(f"junction {junction_id!r} is absent from {net_file}")
    lanes = {item.get("id", ""): item for item in root.iter("lane")}
    result = set()
    for lane_id in junction.get("incLanes", "").split():
        lane = lanes.get(lane_id)
        if lane is None:
            continue
        allow, disallow = set(lane.get("allow", "").split()), set(lane.get("disallow", "").split())
        if "passenger" not in disallow and (not allow or "passenger" in allow):
            result.add(lane_id)
    return result


def lane_pair_coverage(
    teacher_net_file: Path | str,
    candidate_net_file: Path | str,
    *,
    teacher_junction: str,
    candidate_junction: str,
    lane_pairs: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    teacher_lanes = _motor_incoming_lanes(teacher_net_file, teacher_junction)
    candidate_lanes = _motor_incoming_lanes(candidate_net_file, candidate_junction)
    mapped_teacher = {pair[0] for pair in lane_pairs}
    mapped_candidate = {pair[1] for pair in lane_pairs}
    missing_teacher = sorted(teacher_lanes - mapped_teacher)
    missing_candidate = sorted(candidate_lanes - mapped_candidate)
    extra_teacher = sorted(mapped_teacher - teacher_lanes)
    extra_candidate = sorted(mapped_candidate - candidate_lanes)
    status = "pass" if not (missing_teacher or missing_candidate or extra_teacher or extra_candidate) else "blocked"
    return {
        "status": status,
        "teacher_motor_lane_count": len(teacher_lanes),
        "candidate_motor_lane_count": len(candidate_lanes),
        "missing_teacher_motor_lanes": missing_teacher,
        "missing_candidate_motor_lanes": missing_candidate,
        "non_motor_teacher_pairs": extra_teacher,
        "non_motor_candidate_pairs": extra_candidate,
    }


def _numbers(value: str, count: int, label: str) -> tuple[float, ...]:
    numbers = tuple(float(item) for item in value.split(",") if item)
    if len(numbers) != count:
        raise ValueError(f"{label} must contain {count} numbers")
    return numbers


def _meaningful_components(points: set[tuple[int, int]], minimum_size: int = 20) -> list[set[tuple[int, int]]]:
    remaining = set(points)
    components = []
    while remaining:
        component = {remaining.pop()}
        queue = collections.deque(component)
        while queue:
            x, y = queue.popleft()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbor = x + dx, y + dy
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        component.add(neighbor)
                        queue.append(neighbor)
        if len(component) >= minimum_size:
            components.append(component)
    return components


def _palette_points(image: Image.Image, tolerance: int) -> dict[str, set[tuple[int, int]]]:
    rgb = image.convert("RGB")
    pixels = rgb.load()
    return {
        name: {
            (x, y)
            for y in range(rgb.height)
            for x in range(rgb.width)
            if max(abs(pixels[x, y][channel] - color[channel]) for channel in range(3)) <= tolerance
        }
        for name, color in _PALETTE.items()
    }


def _point_stats(points: set[tuple[int, int]], center: tuple[int, int]) -> dict[str, Any]:
    points = {
        point
        for point in points
        if (point[0] - center[0]) ** 2 + (point[1] - center[1]) ** 2 <= 160**2
    }
    components = _meaningful_components(points)
    points = set().union(*components) if components else set()
    return {
        "pixel_count": len(points),
        "bbox": (
            [
                min(x for x, _ in points),
                min(y for _, y in points),
                max(x for x, _ in points) + 1,
                max(y for _, y in points) + 1,
            ]
            if points
            else []
        ),
        "angular_bins": sorted({
            int((math.degrees(math.atan2(center[1] - y, x - center[0])) % 360.0) // 45.0)
            for x, y in points
        }),
        "component_count": len(components),
    }


def write_semantic_mask(
    source: Path,
    destination: Path,
    *,
    center: tuple[int, int],
    tolerance: int = 12,
) -> dict[str, Any]:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
    mask = Image.new("P", image.size, 0)
    palette = [0, 0, 0, *(channel for color in _PALETTE.values() for channel in color)]
    mask.putpalette(palette + [0] * (768 - len(palette)))
    mask_pixels = mask.load()
    points_by_layer = _palette_points(image, tolerance)
    stats: dict[str, Any] = {}
    for index, name in enumerate(_PALETTE, 1):
        points = points_by_layer[name]
        for point in points:
            mask_pixels[point] = index
        stats[name] = _point_stats(points, center)
    destination.parent.mkdir(parents=True, exist_ok=True)
    mask.save(destination)
    return {"file": str(destination), "sha256": file_sha256(destination), "layers": stats}


def analyze_connection_pair(
    teacher_file: Path,
    candidate_file: Path,
    *,
    teacher_center: tuple[int, int] | None = None,
    candidate_center: tuple[int, int] | None = None,
    teacher_canvas_rect: tuple[int, int, int, int] | None = None,
    candidate_canvas_rect: tuple[int, int, int, int] | None = None,
) -> dict[str, Any]:
    with Image.open(teacher_file) as source:
        teacher = source.convert("RGB")
    with Image.open(candidate_file) as source:
        candidate = source.convert("RGB")
    if teacher_canvas_rect is not None:
        teacher = teacher.crop(teacher_canvas_rect)
        if teacher_center is not None:
            teacher_center = (
                teacher_center[0] - teacher_canvas_rect[0],
                teacher_center[1] - teacher_canvas_rect[1],
            )
    if candidate_canvas_rect is not None:
        candidate = candidate.crop(candidate_canvas_rect)
        if candidate_center is not None:
            candidate_center = (
                candidate_center[0] - candidate_canvas_rect[0],
                candidate_center[1] - candidate_canvas_rect[1],
            )
    if teacher.size != candidate.size:
        return {"status": "blocked", "reasons": ["image_size_mismatch"], "layers": {}}
    teacher_center = teacher_center or (teacher.width // 2, teacher.height // 2)
    candidate_center = candidate_center or (candidate.width // 2, candidate.height // 2)
    teacher_stats = {
        name: _point_stats(points, teacher_center)
        for name, points in _palette_points(teacher, 12).items()
    }
    candidate_stats = {
        name: _point_stats(points, candidate_center)
        for name, points in _palette_points(candidate, 12).items()
    }
    layers: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    for name in _PALETTE:
        teacher_pixels = teacher_stats[name]["pixel_count"]
        candidate_pixels = candidate_stats[name]["pixel_count"]
        ratio = candidate_pixels / teacher_pixels if teacher_pixels else None
        missing_bins = sorted(
            teacher_bin
            for teacher_bin in teacher_stats[name]["angular_bins"]
            if not any(
                min((teacher_bin - candidate_bin) % 8, (candidate_bin - teacher_bin) % 8) <= 1
                for candidate_bin in candidate_stats[name]["angular_bins"]
            )
        )
        layers[name] = {
            "teacher_pixels": teacher_pixels,
            "candidate_pixels": candidate_pixels,
            "candidate_teacher_ratio": None if ratio is None else round(ratio, 4),
            "teacher_angular_bins": teacher_stats[name]["angular_bins"],
            "candidate_angular_bins": candidate_stats[name]["angular_bins"],
            "teacher_component_count": teacher_stats[name]["component_count"],
            "candidate_component_count": candidate_stats[name]["component_count"],
        }
        if teacher_pixels >= 40 and candidate_pixels < max(20, teacher_pixels // 10):
            reasons.append(f"{name}_layer_missing")
        elif teacher_pixels >= 40 and candidate_pixels >= 40 and not 0.5 <= ratio <= 2.0:
            reasons.append(f"{name}_layer_scale_mismatch")
        elif teacher_pixels >= 40 and candidate_pixels >= 40 and missing_bins:
            reasons.append(f"{name}_direction_missing")
        elif abs(teacher_stats[name]["component_count"] - candidate_stats[name]["component_count"]) > 1:
            reasons.append(f"{name}_component_mismatch")
    if min(layers["source"]["teacher_pixels"], layers["source"]["candidate_pixels"]) < 20:
        return {"status": "review_required", "reasons": ["source_lane_not_selected"], "layers": layers}
    return {"status": "fail" if reasons else "pass", "reasons": reasons, "layers": layers}


def netedit_canvas_rect(hwnd: int) -> tuple[int, int, int, int]:
    _, win32gui, _, _ = _windows_modules()
    canvases: list[int] = []

    def collect(child: int, _: object) -> bool:
        if win32gui.GetClassName(child) == "FXGLCanvas":
            canvases.append(child)
        return True

    win32gui.EnumChildWindows(hwnd, collect, None)
    if len(canvases) != 1:
        raise RuntimeError(f"expected one FXGLCanvas, found {len(canvases)}")
    left, top, right, bottom = win32gui.GetWindowRect(canvases[0])
    x0, y0 = win32gui.ScreenToClient(hwnd, (left, top))
    x1, y1 = win32gui.ScreenToClient(hwnd, (right, bottom))
    return x0, y0, x1, y1


def _viewsettings(path: Path, center: tuple[float, float], zoom: float) -> None:
    path.write_text(
        "<viewsettings>\n"
        '  <scheme name="standard"/>\n'
        f'  <viewport zoom="{zoom:g}" x="{center[0]:g}" y="{center[1]:g}" angle="0"/>\n'
        '  <delay value="100"/>\n'
        "</viewsettings>\n",
        encoding="utf-8",
    )


def capture_connection_tile(
    *,
    session: Any,
    specs: Sequence[dict[str, Any]],
    viewport_center: tuple[float, float],
    zoom: float,
    destination: Path,
    canvas_rect: tuple[int, int, int, int] | None = None,
) -> list[dict[str, Any]]:
    session.open()
    captures: list[dict[str, Any]] = []
    try:
        latest = session.observe("pre_connection_stable")
        latest = session.act({
            "type": "key",
            "virtual_key": ord("C"),
            "expected_screenshot_sha256": latest["screenshot_sha256"],
        })
        canvas = canvas_rect or netedit_canvas_rect(session.hwnd)
        destination.mkdir(parents=True, exist_ok=True)
        for index, spec in enumerate(specs, 1):
            junction_pixel = canvas_click_for_world_point(
                point=spec["center"],
                center=viewport_center,
                conv_boundary=spec["conv_boundary"],
                canvas_rect=canvas,
                zoom=zoom,
            )
            click = canvas_click_for_world_point(
                point=point_before_lane_end(spec["shape"]),
                center=viewport_center,
                conv_boundary=spec["conv_boundary"],
                canvas_rect=canvas,
                zoom=zoom,
            )
            latest = session.act({
                "type": "click",
                "x": click[0],
                "y": click[1],
                "expected_screenshot_sha256": latest["screenshot_sha256"],
            })
            image = destination / f"{index:05d}.png"
            shutil.copy2(latest["screenshot_file"], image)
            captures.append({
                "lane_id": spec["lane_id"],
                "click": list(click),
                "junction_pixel": list(junction_pixel),
                "canvas_rect": list(canvas),
                "screenshot_file": str(image),
                "screenshot_sha256": file_sha256(image),
            })
        return captures
    finally:
        session.abort("visual_tile_capture_complete")


def _capture(spec: dict[str, Any], *, output_dir: Path, zoom: float, window_size: tuple[int, int]) -> dict[str, Any]:
    support = output_dir / "support"
    support.mkdir(parents=True, exist_ok=True)
    view = support / "view.xml"
    _viewsettings(view, spec["center"], zoom)
    session_dir = output_dir / "session"
    session = NeteditTargetSession(
        spec["net_file"],
        support / "working.net.xml",
        session_dir,
        expected_source_sha256=file_sha256(Path(spec["net_file"])),
        gui_settings_file=view,
        target_source_junction_ids=(spec["junction_id"],),
        target_candidate_junction_ids=(spec["junction_id"],),
        window_size=f"{window_size[0]},{window_size[1]}",
    )
    session.open()
    try:
        time.sleep(1.5)
        latest = session.observe("pre_connection_stable")
        mode = session.act({
            "type": "key", "virtual_key": ord("C"),
            "expected_screenshot_sha256": latest["screenshot_sha256"],
        })
        canvas = netedit_canvas_rect(session.hwnd)
        destination = output_dir / "connection.png"
        selected, click, source_pixels = mode, (0, 0), 0
        for point in lane_click_points(spec["shape"]):
            click = canvas_click_for_world_point(
                point=point, center=spec["center"], conv_boundary=spec["conv_boundary"],
                canvas_rect=canvas, zoom=zoom,
            )
            selected = session.act({
                "type": "click", "x": click[0], "y": click[1],
                "expected_screenshot_sha256": selected["screenshot_sha256"],
            })
            with Image.open(selected["screenshot_file"]) as opened:
                source_pixels = _point_stats(
                    _palette_points(opened.crop(canvas), 12)["source"],
                    (click[0] - canvas[0], click[1] - canvas[1]),
                )["pixel_count"]
            if source_pixels >= 20:
                break
        shutil.copy2(selected["screenshot_file"], destination)
        status = "pass" if source_pixels >= 20 else "review_required"
        return {
            "status": status,
            "reasons": [] if status == "pass" else ["source_lane_not_selected"],
            "click": list(click),
            "canvas_rect": list(canvas),
            "zoom": zoom,
            "selected_source_pixel_count": source_pixels,
            "screenshot_file": str(destination),
            "screenshot_sha256": file_sha256(destination),
        }
    finally:
        session.abort("visual_capture_complete")


def _comparison_image(teacher: Path, candidate: Path, destination: Path) -> None:
    with Image.open(teacher) as left_source, Image.open(candidate) as right_source:
        left, right = left_source.convert("RGB"), right_source.convert("RGB")
    image = Image.new("RGB", (left.width + right.width, max(left.height, right.height)), "white")
    image.paste(left, (0, 0))
    image.paste(right, (left.width, 0))
    image.save(destination)


def write_visual_gate_report(
    *, output_dir: Path, teacher_net_file: Path, candidate_net_file: Path,
    lane_reports: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    statuses = {str(item["status"]) for item in lane_reports}
    status = next((value for value in ("blocked", "fail", "review_required") if value in statuses), "pass")
    report = {
        "schema": "torii.netedit_connection_visual_gate.v1", "status": status,
        "teacher_net_file": str(Path(teacher_net_file).resolve()),
        "teacher_sha256": file_sha256(Path(teacher_net_file)),
        "candidate_net_file": str(Path(candidate_net_file).resolve()),
        "candidate_sha256": file_sha256(Path(candidate_net_file)),
        "lane_reports": list(lane_reports),
        "comparison_images": [str(item["comparison_file"]) for item in lane_reports
                              if item["status"] != "pass" and item.get("comparison_file")],
        "automatic_promotion_gate": "pass" if status == "pass" else "blocked",
    }
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    report_file = destination / "visual-gate.json"
    write_json_atomic(report_file, report, sort_keys=True)
    return {**report, "report_file": str(report_file)}


def run_connection_visual_gate(
    *, teacher_net_file: Path | str, candidate_net_file: Path | str,
    teacher_junction: str, candidate_junction: str,
    lane_pairs: Sequence[tuple[str, str]], output_dir: Path | str,
    zoom: float = 2500.0, window_size: tuple[int, int] = (1400, 1000),
) -> dict[str, Any]:
    teacher_net, candidate_net, output = Path(teacher_net_file), Path(candidate_net_file), Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    coverage = lane_pair_coverage(
        teacher_net,
        candidate_net,
        teacher_junction=teacher_junction,
        candidate_junction=candidate_junction,
        lane_pairs=lane_pairs,
    )
    if coverage["status"] != "pass":
        return write_visual_gate_report(
            output_dir=output,
            teacher_net_file=teacher_net,
            candidate_net_file=candidate_net,
            lane_reports=[{"status": "blocked", "reasons": ["motor_lane_coverage_incomplete"], "coverage": coverage}],
        )
    reports: list[dict[str, Any]] = []
    for index, (teacher_lane, candidate_lane) in enumerate(lane_pairs, 1):
        teacher_spec = lane_capture_spec(teacher_net, junction_id=teacher_junction, lane_id=teacher_lane)
        candidate_spec = lane_capture_spec(candidate_net, junction_id=candidate_junction, lane_id=candidate_lane)
        row: dict[str, Any] = {"teacher_lane": teacher_lane, "candidate_lane": candidate_lane}
        if not teacher_spec["motor_vehicle"] or not candidate_spec["motor_vehicle"]:
            reports.append({**row, "status": "blocked", "reasons": ["incompatible_lane_permissions"]})
            continue
        if math.dist(teacher_spec["projected_center"], candidate_spec["projected_center"]) > 2.0:
            reports.append({**row, "status": "blocked", "reasons": ["projected_junction_mismatch"]})
            continue
        endpoint_gap = math.dist(
            (teacher_spec["shape"][-1][0] - teacher_spec["center"][0] + teacher_spec["projected_center"][0],
             teacher_spec["shape"][-1][1] - teacher_spec["center"][1] + teacher_spec["projected_center"][1]),
            (candidate_spec["shape"][-1][0] - candidate_spec["center"][0] + candidate_spec["projected_center"][0],
             candidate_spec["shape"][-1][1] - candidate_spec["center"][1] + candidate_spec["projected_center"][1]),
        )
        row["projected_lane_endpoint_gap_m"] = round(endpoint_gap, 3)
        if endpoint_gap > 25.0:
            reports.append({**row, "status": "blocked", "reasons": ["lane_pair_geometry_mismatch"]})
            continue
        pair_dir = output / f"lane-{index:02d}"
        candidate_zoom = normalized_viewport_zoom(
            reference_boundary=teacher_spec["conv_boundary"],
            target_boundary=candidate_spec["conv_boundary"],
            reference_zoom=zoom,
            viewport_size=window_size,
        )
        teacher_capture = _capture(teacher_spec, output_dir=pair_dir / "teacher", zoom=zoom, window_size=window_size)
        candidate_capture = _capture(
            candidate_spec,
            output_dir=pair_dir / "candidate",
            zoom=candidate_zoom,
            window_size=window_size,
        )
        if teacher_capture["status"] != "pass" or candidate_capture["status"] != "pass":
            captures = (teacher_capture, candidate_capture)
            reports.append({
                **row,
                "status": "review_required",
                "reasons": sorted({
                    reason
                    for capture in captures
                    for reason in capture.get("reasons", [])
                }),
                "teacher_capture": teacher_capture,
                "candidate_capture": candidate_capture,
            })
            continue
        comparison = analyze_connection_pair(
            Path(teacher_capture["screenshot_file"]),
            Path(candidate_capture["screenshot_file"]),
            teacher_center=tuple(teacher_capture["click"]),
            candidate_center=tuple(candidate_capture["click"]),
            teacher_canvas_rect=tuple(teacher_capture["canvas_rect"]),
            candidate_canvas_rect=tuple(candidate_capture["canvas_rect"]),
        )
        report = {**row, **comparison, "teacher_capture": teacher_capture, "candidate_capture": candidate_capture}
        if comparison["status"] != "pass":
            comparison_file = pair_dir / "comparison.png"
            _comparison_image(Path(teacher_capture["screenshot_file"]), Path(candidate_capture["screenshot_file"]), comparison_file)
            report["comparison_file"] = str(comparison_file)
        reports.append(report)
    return write_visual_gate_report(
        output_dir=output, teacher_net_file=teacher_net, candidate_net_file=candidate_net,
        lane_reports=reports,
    )

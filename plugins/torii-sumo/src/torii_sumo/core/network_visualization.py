from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class Segment:
    points: tuple[tuple[float, float], ...]
    category: str


@dataclass(frozen=True)
class NetDrawing:
    segments: tuple[Segment, ...]
    traffic_lights: tuple[tuple[float, float], ...]
    bounds: tuple[float, float, float, float]


_MAJOR_TYPES = ("motorway", "trunk", "primary", "secondary", "tertiary")
_VEHICLE_TYPES = ("residential", "unclassified", "service", "living_street")


def _parse_shape(value: str | None) -> tuple[tuple[float, float], ...]:
    points = []
    for raw_point in (value or "").split():
        pieces = raw_point.split(",")
        if len(pieces) < 2:
            continue
        try:
            points.append((float(pieces[0]), float(pieces[1])))
        except ValueError:
            continue
    return tuple(points)


def _edge_category(edge_type: str) -> str:
    lowered = edge_type.lower()
    if any(token in lowered for token in _MAJOR_TYPES):
        return "major"
    if any(token in lowered for token in _VEHICLE_TYPES):
        return "vehicle"
    return "soft"


def _expanded_bounds(points: Iterable[tuple[float, float]]) -> tuple[float, float, float, float]:
    values = list(points)
    if not values:
        return (0.0, 0.0, 1.0, 1.0)
    xs = [point[0] for point in values]
    ys = [point[1] for point in values]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if min_x == max_x:
        min_x -= 1.0
        max_x += 1.0
    if min_y == max_y:
        min_y -= 1.0
        max_y += 1.0
    pad_x = (max_x - min_x) * 0.05
    pad_y = (max_y - min_y) * 0.05
    return (min_x - pad_x, min_y - pad_y, max_x + pad_x, max_y + pad_y)


def _read_net(net_file: Path) -> NetDrawing:
    root = ET.parse(net_file).getroot()
    segments: list[Segment] = []
    tls_points: list[tuple[float, float]] = []
    all_points: list[tuple[float, float]] = []

    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")
        if edge_id.startswith(":") or edge.get("function") == "internal":
            continue
        lane = edge.find("lane")
        if lane is None:
            continue
        points = _parse_shape(lane.get("shape"))
        if len(points) < 2:
            continue
        all_points.extend(points)
        segments.append(Segment(points=points, category=_edge_category(edge.get("type", ""))))

    for junction in root.findall("junction"):
        if junction.get("type") != "traffic_light":
            continue
        try:
            point = (float(junction.get("x", "0")), float(junction.get("y", "0")))
        except ValueError:
            continue
        tls_points.append(point)
        all_points.append(point)

    return NetDrawing(
        segments=tuple(segments),
        traffic_lights=tuple(tls_points),
        bounds=_expanded_bounds(all_points),
    )


def _cluster_points(report: Mapping[str, Any] | None) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    if not report:
        return points
    for cluster in report.get("suspicious_clusters", []) or []:
        if not isinstance(cluster, Mapping):
            continue
        x_value = cluster.get("centroid_x", cluster.get("centroid_lon"))
        y_value = cluster.get("centroid_y", cluster.get("centroid_lat"))
        try:
            points.append((float(x_value), float(y_value)))
        except (TypeError, ValueError):
            continue
    return points


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _project(
    point: tuple[float, float],
    *,
    bounds: tuple[float, float, float, float],
    origin: tuple[int, int],
    size: tuple[int, int],
) -> tuple[int, int]:
    min_x, min_y, max_x, max_y = bounds
    width, height = size
    x = origin[0] + int(round((point[0] - min_x) / (max_x - min_x) * width))
    y = origin[1] + int(round((max_y - point[1]) / (max_y - min_y) * height))
    return x, y


def _draw_net(
    draw: ImageDraw.ImageDraw,
    net: NetDrawing,
    *,
    origin: tuple[int, int],
    size: tuple[int, int],
    title: str,
    bounds: tuple[float, float, float, float] | None = None,
    cluster_points: Iterable[tuple[float, float]] = (),
) -> None:
    active_bounds = bounds or net.bounds
    x0, y0 = origin
    width, height = size
    draw.rectangle([x0, y0, x0 + width, y0 + height], fill=(250, 250, 250), outline=(210, 210, 210))
    colors = {"soft": (188, 188, 188), "vehicle": (42, 42, 42), "major": (0, 0, 0)}
    widths = {"soft": 1, "vehicle": 2, "major": 3}

    for category in ("soft", "vehicle", "major"):
        for segment in net.segments:
            if segment.category != category:
                continue
            projected = [
                _project(point, bounds=active_bounds, origin=origin, size=size)
                for point in segment.points
            ]
            if len(projected) >= 2:
                draw.line(projected, fill=colors[category], width=widths[category], joint="curve")

    for point in net.traffic_lights:
        x, y = _project(point, bounds=active_bounds, origin=origin, size=size)
        radius = 5
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(208, 0, 0))

    for point in cluster_points:
        x, y = _project(point, bounds=active_bounds, origin=origin, size=size)
        radius = 12
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], outline=(240, 142, 0), width=3)

    draw.text((x0, max(0, y0 - 26)), title, fill=(25, 25, 25), font=_font(18))


def _write_single_panel(
    *,
    net: NetDrawing,
    output_file: Path,
    title: str,
    cluster_points: Iterable[tuple[float, float]] = (),
) -> None:
    image = Image.new("RGB", (900, 700), "white")
    draw = ImageDraw.Draw(image)
    draw.text((28, 22), title, fill=(20, 20, 20), font=_font(22))
    _draw_net(
        draw,
        net,
        origin=(45, 80),
        size=(810, 560),
        title=f"network | TLS={len(net.traffic_lights)}",
        cluster_points=cluster_points,
    )
    draw.text(
        (45, 660),
        "Black: vehicle/service roads; gray: pedestrian/cycle/detail roads; red: TLS; orange: review cluster.",
        fill=(80, 80, 80),
        font=_font(14),
    )
    image.save(output_file)


def _write_comparison_panel(
    *,
    reference: NetDrawing,
    candidate: NetDrawing,
    output_file: Path,
) -> None:
    all_bounds = _expanded_bounds(
        [
            point
            for net in (reference, candidate)
            for segment in net.segments
            for point in segment.points
        ]
        + list(reference.traffic_lights)
        + list(candidate.traffic_lights)
    )
    image = Image.new("RGB", (1500, 760), "white")
    draw = ImageDraw.Draw(image)
    draw.text((28, 22), "Reference Comparison", fill=(20, 20, 20), font=_font(22))
    _draw_net(
        draw,
        reference,
        origin=(45, 92),
        size=(660, 560),
        title=f"reference | TLS={len(reference.traffic_lights)}",
        bounds=all_bounds,
    )
    _draw_net(
        draw,
        candidate,
        origin=(795, 92),
        size=(660, 560),
        title=f"candidate | TLS={len(candidate.traffic_lights)}",
        bounds=all_bounds,
    )
    draw.text(
        (45, 690),
        "Panels share one coordinate scale for visual comparison.",
        fill=(80, 80, 80),
        font=_font(14),
    )
    image.save(output_file)


def build_network_review_visuals(
    *,
    output_dir: Path,
    prefix: str = "workflow_review",
    net_file: str | Path | None = None,
    reference_net_file: str | Path | None = None,
    topology_audit_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not net_file:
        return {
            "status": "blocked",
            "claim_status": "blocked",
            "visualization_status": "skipped",
            "warnings": ["no SUMO net_file supplied for review visualization"],
        }

    net_path = Path(net_file)
    if not net_path.exists():
        return {
            "status": "blocked",
            "claim_status": "blocked",
            "visualization_status": "skipped",
            "warnings": [f"SUMO net_file does not exist: {net_path}"],
        }

    network = _read_net(net_path)
    clusters = _cluster_points(topology_audit_report)
    overview_file = output_dir / f"{prefix}_network_overview.png"
    problem_file = output_dir / f"{prefix}_problem_overlay.png"
    comparison_file = output_dir / f"{prefix}_reference_comparison.png"

    _write_single_panel(net=network, output_file=overview_file, title="Network Preview")
    _write_single_panel(net=network, output_file=problem_file, title="Problem Map", cluster_points=clusters)

    comparison_value = ""
    if reference_net_file and Path(reference_net_file).exists():
        reference = _read_net(Path(reference_net_file))
        _write_comparison_panel(reference=reference, candidate=network, output_file=comparison_file)
        comparison_value = str(comparison_file)

    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "visualization_status": "pass",
        "network_overview_png": str(overview_file),
        "problem_overlay_png": str(problem_file),
        "reference_comparison_png": comparison_value,
        "warnings": [],
    }

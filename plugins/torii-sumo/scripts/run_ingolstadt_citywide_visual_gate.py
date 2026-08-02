from __future__ import annotations

import collections
import math
from pathlib import Path
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

from torii_sumo.core.artifact_io import write_json_atomic
from torii_sumo.core.candidate_contracts import file_sha256


OFFICIAL_TEACHER_SHA256 = "bbfef2f8afb66f29486395189fa7136e3fa7cce2b192afcbd50a6f1d9239a806"
OFFICIAL_CONV_BOUNDARY = (1243.52, 0.0, 11284.52, 10137.01)


def lane_allows_motor(lane: ET.Element) -> bool:
    allow = set(lane.get("allow", "").split())
    disallow = set(lane.get("disallow", "").split())
    return "passenger" not in disallow and (not allow or "passenger" in allow)


def tile_id(point: tuple[float, float], tile_size_m: float) -> str:
    if tile_size_m <= 0:
        raise ValueError("tile_size_m must be positive")
    return f"{math.floor(point[0] / tile_size_m):04d}_{math.floor(point[1] / tile_size_m):04d}"


def road_root(edge_id: str) -> str:
    return edge_id.lstrip("-").split("#", 1)[0]


def source_ids(junction_id: str) -> frozenset[str]:
    value = junction_id.removeprefix("cluster_")
    return frozenset(part for part in value.split("_") if part.isdigit())


def angle_gap(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def _lane_bearing(lane: ET.Element) -> float:
    points = [tuple(float(value) for value in point.split(",")[:2]) for point in lane.get("shape", "").split()]
    if len(points) < 2:
        raise ValueError(f"lane has no usable shape: {lane.get('id', '')}")
    start, end = points[-2], points[-1]
    return round(math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])) % 360.0, 6)


def _junction_score(teacher: Mapping[str, Any], candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    teacher_sources = source_ids(str(teacher["id"]))
    candidate_sources = source_ids(str(candidate["id"]))
    teacher_roads = set(map(str, teacher.get("road_roots", ())))
    candidate_roads = set(map(str, candidate.get("road_roots", ())))
    teacher_bearings = [float(value) for value in teacher.get("approach_bearings", ())]
    candidate_bearings = [float(value) for value in candidate.get("approach_bearings", ())]
    bearing_matches = sum(
        any(angle_gap(value, other) <= 20.0 for other in candidate_bearings)
        for value in teacher_bearings
    )
    distance = math.dist(teacher["projected_center"], candidate["projected_center"])
    return (
        int(str(teacher["id"]) == str(candidate["id"])),
        int(bool(teacher_sources) and teacher_sources == candidate_sources),
        len(teacher_sources & candidate_sources),
        len(teacher_roads & candidate_roads),
        bearing_matches,
        -round(distance, 6),
    )


def register_junctions(
    teacher_junctions: Sequence[Mapping[str, Any]],
    candidate_junctions: Sequence[Mapping[str, Any]],
    *,
    max_distance_m: float,
) -> dict[str, Any]:
    if max_distance_m <= 0:
        raise ValueError("max_distance_m must be positive")
    available = {str(row["id"]): row for row in candidate_junctions}
    used: set[str] = set()
    matched, teacher_only, ambiguous = [], [], []
    for teacher in sorted(teacher_junctions, key=lambda row: str(row["id"])):
        teacher_id = str(teacher["id"])
        nearby = [
            row for candidate_id, row in available.items()
            if candidate_id not in used
            and math.dist(teacher["projected_center"], row["projected_center"]) <= max_distance_m
        ]
        teacher_sources = source_ids(teacher_id)
        exact = [row for row in nearby if teacher_sources and source_ids(str(row["id"])) == teacher_sources]
        if len(exact) == 1:
            selected = exact
        elif len(exact) > 1:
            selected = []
            ambiguous.append({"teacher_id": teacher_id, "candidate_ids": sorted(str(row["id"]) for row in exact)})
        else:
            by_source = {
                source_id: [row for row in nearby if source_id in source_ids(str(row["id"]))]
                for source_id in teacher_sources
            }
            if len(teacher_sources) > 1 and all(len(rows) == 1 for rows in by_source.values()):
                selected = list({str(rows[0]["id"]): rows[0] for rows in by_source.values()}.values())
            elif not nearby:
                selected = []
                teacher_only.append(teacher_id)
            else:
                scored = sorted(((_junction_score(teacher, row), row) for row in nearby), key=lambda item: item[0], reverse=True)
                best_score = scored[0][0]
                tied = [row for score, row in scored if score == best_score]
                if len(tied) != 1 or not (best_score[0] or best_score[1] or (best_score[3] and best_score[4])):
                    selected = []
                    ambiguous.append({"teacher_id": teacher_id, "candidate_ids": sorted(str(row["id"]) for row in tied)})
                else:
                    selected = tied
        if selected:
            candidate_ids = sorted(str(row["id"]) for row in selected)
            used.update(candidate_ids)
            matched.append({"teacher_id": teacher_id, "candidate_ids": candidate_ids})
    return {
        "matched": matched,
        "teacher_only": sorted(teacher_only),
        "candidate_only": sorted(set(available) - used),
        "ambiguous": ambiguous,
    }


def register_lanes(
    teacher_lanes: Sequence[Mapping[str, Any]],
    candidate_lanes: Sequence[Mapping[str, Any]],
    *,
    max_bearing_gap: float,
) -> dict[str, Any]:
    if max_bearing_gap < 0:
        raise ValueError("max_bearing_gap must be nonnegative")
    available = {str(row["id"]): row for row in candidate_lanes}
    used: set[str] = set()
    matched, teacher_only, ambiguous = [], [], []
    for teacher in sorted(teacher_lanes, key=lambda row: str(row["id"])):
        choices = []
        for candidate_id, candidate in available.items():
            gap = angle_gap(float(teacher["bearing"]), float(candidate["bearing"]))
            if candidate_id not in used and teacher["road_root"] == candidate["road_root"] and gap <= max_bearing_gap:
                choices.append((round(gap, 6), candidate_id))
        choices.sort()
        if not choices:
            teacher_only.append(str(teacher["id"]))
            continue
        best_gap = choices[0][0]
        tied = [candidate_id for gap, candidate_id in choices if gap == best_gap]
        if len(tied) != 1:
            ambiguous.append({"teacher_lane": str(teacher["id"]), "candidate_lanes": tied})
            continue
        candidate_id = tied[0]
        used.add(candidate_id)
        matched.append({
            "teacher_lane": str(teacher["id"]),
            "candidate_lane": candidate_id,
            "bearing_gap": best_gap,
        })
    return {
        "matched": matched,
        "teacher_only": sorted(teacher_only),
        "candidate_only": sorted(set(available) - used),
        "ambiguous": ambiguous,
    }


def _location_numbers(path: Path) -> tuple[tuple[float, float], tuple[float, float, float, float]]:
    location = ET.parse(path).getroot().find("location")
    if location is None:
        raise ValueError(f"network has no location: {path}")
    try:
        offset = tuple(float(value) for value in location.get("netOffset", "").split(","))
        boundary = tuple(float(value) for value in location.get("convBoundary", "").split(","))
    except ValueError as exc:
        raise ValueError(f"network has invalid location numbers: {path}") from exc
    if len(offset) != 2 or len(boundary) != 4:
        raise ValueError(f"network has invalid location dimensions: {path}")
    return offset, boundary  # type: ignore[return-value]


def write_source_ledger(
    destination: Path,
    *,
    teacher_net: Path,
    candidate_net: Path,
    source_osm: Path,
    git_commit: str,
    sumo_version: str,
    netedit_version: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    teacher = Path(teacher_net).resolve(strict=True)
    candidate = Path(candidate_net).resolve(strict=True)
    osm = Path(source_osm).resolve(strict=True)
    teacher_sha = file_sha256(teacher)
    offset, boundary = _location_numbers(teacher)
    if teacher_sha != OFFICIAL_TEACHER_SHA256 or boundary != OFFICIAL_CONV_BOUNDARY:
        raise ValueError("teacher network does not match the official Ingolstadt artifact and boundary")
    x0, y0, x1, y1 = boundary
    projected_scope = [x0 - offset[0], y0 - offset[1], x1 - offset[0], y1 - offset[1]]
    report = {
        "schema": "torii.ingolstadt-citywide-source-ledger/v1",
        "status": "pass",
        "teacher_net_file": str(teacher),
        "teacher_sha256": teacher_sha,
        "candidate_net_file": str(candidate),
        "candidate_sha256": file_sha256(candidate),
        "source_osm_file": str(osm),
        "source_osm_sha256": file_sha256(osm),
        "official_conv_boundary": list(boundary),
        "projected_scope": projected_scope,
        "git_commit": git_commit,
        "sumo_version": sumo_version,
        "netedit_version": netedit_version,
        "parameters": dict(parameters),
    }
    report_file = Path(destination).resolve()
    write_json_atomic(report_file, report, sort_keys=True)
    return {**report, "report_file": str(report_file)}


def read_network_inventory(
    path: Path,
    *,
    tile_size_m: float,
    scope_projected_boundary: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    source = Path(path).resolve(strict=True)
    root = ET.parse(source).getroot()
    location = root.find("location")
    if location is None:
        raise ValueError(f"network has no location: {source}")
    try:
        offset_x, offset_y = (float(value) for value in location.get("netOffset", "").split(","))
    except ValueError as exc:
        raise ValueError(f"network has invalid netOffset: {source}") from exc

    lanes: dict[str, ET.Element] = {}
    lane_edges: dict[str, str] = {}
    edge_lanes: dict[str, dict[str, str]] = {}
    for edge in root.findall("edge"):
        if edge.get("function") == "internal":
            continue
        edge_id = edge.get("id", "")
        indexed: dict[str, str] = {}
        for lane in edge.findall("lane"):
            lane_id = lane.get("id", "")
            if lane_id:
                lanes[lane_id] = lane
                lane_edges[lane_id] = edge_id
                indexed[lane.get("index", "")] = lane_id
        edge_lanes[edge_id] = indexed

    outgoing: dict[str, set[str]] = collections.defaultdict(set)
    for connection in root.findall("connection"):
        target_lane = edge_lanes.get(connection.get("to", ""), {}).get(connection.get("toLane", ""))
        if target_lane:
            outgoing[connection.get("from", "")].add(target_lane)

    rows: list[dict[str, Any]] = []
    for junction in root.findall("junction"):
        junction_id = junction.get("id", "")
        if not junction_id or junction_id.startswith(":") or junction.get("type") == "internal":
            continue
        incoming = sorted(
            lane_id
            for lane_id in junction.get("incLanes", "").split()
            if lane_id in lanes and lane_allows_motor(lanes[lane_id])
        )
        incoming_edges = {lane_edges[lane_id] for lane_id in incoming}
        outgoing_lanes = sorted(
            lane_id
            for edge_id in incoming_edges
            for lane_id in outgoing.get(edge_id, ())
            if lane_allows_motor(lanes[lane_id])
        )
        if not incoming or not outgoing_lanes:
            continue
        local = float(junction.get("x", "nan")), float(junction.get("y", "nan"))
        projected = local[0] - offset_x, local[1] - offset_y
        if scope_projected_boundary is not None:
            x0, y0, x1, y1 = scope_projected_boundary
            if not (x0 <= projected[0] <= x1 and y0 <= projected[1] <= y1):
                continue
        rows.append(
            {
                "id": junction_id,
                "projected_center": [round(projected[0], 6), round(projected[1], 6)],
                "tile_id": tile_id(projected, tile_size_m),
                "motor_incoming_lanes": incoming,
                "motor_outgoing_lanes": outgoing_lanes,
                "motor_incoming_edges": sorted(incoming_edges),
                "motor_outgoing_edges": sorted({lane_edges[lane_id] for lane_id in outgoing_lanes}),
                "road_roots": sorted({
                    road_root(lane_edges[lane_id]) for lane_id in (*incoming, *outgoing_lanes)
                }),
                "approach_bearings": sorted(_lane_bearing(lanes[lane_id]) for lane_id in incoming),
                "motor_incoming_lane_details": sorted(
                    (
                        {
                            "id": lane_id,
                            "edge_id": lane_edges[lane_id],
                            "road_root": road_root(lane_edges[lane_id]),
                            "bearing": _lane_bearing(lanes[lane_id]),
                        }
                        for lane_id in incoming
                    ),
                    key=lambda row: row["id"],
                ),
            }
        )
    return {
        "net_file": str(source),
        "net_sha256": file_sha256(source),
        "tile_size_m": tile_size_m,
        "applicable_junction_count": len(rows),
        "junctions": sorted(rows, key=lambda row: row["id"]),
    }

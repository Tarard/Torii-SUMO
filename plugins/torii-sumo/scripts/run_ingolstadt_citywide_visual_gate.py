from __future__ import annotations

import collections
import math
from pathlib import Path
from typing import Any
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
            }
        )
    return {
        "net_file": str(source),
        "net_sha256": file_sha256(source),
        "tile_size_m": tile_size_m,
        "applicable_junction_count": len(rows),
        "junctions": sorted(rows, key=lambda row: row["id"]),
    }

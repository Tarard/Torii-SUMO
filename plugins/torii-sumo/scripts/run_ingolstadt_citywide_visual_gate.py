from __future__ import annotations

import argparse
import collections
import functools
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

from torii_sumo.core.artifact_io import write_json_atomic, write_text_atomic
from torii_sumo.core.candidate_contracts import file_sha256
from torii_sumo.core.command_runner import run_command
from torii_sumo.core.netedit_connection_visual_gate import (
    _comparison_image,
    _viewsettings,
    analyze_connection_pair,
    canvas_click_for_world_point,
    fit_connection_zoom,
    lane_capture_spec,
    lane_click_points,
    netedit_canvas_rect,
    normalized_viewport_zoom,
    verify_expected_lane_semantics,
    write_semantic_mask,
)
from torii_sumo.core.netedit import NeteditTargetSession, _perform_target_window_input
from torii_sumo.core.routeability_audit import inspect_routeability_outputs
from torii_sumo.core.sumo_commands import discover_binaries


OFFICIAL_TEACHER_SHA256 = "bbfef2f8afb66f29486395189fa7136e3fa7cce2b192afcbd50a6f1d9239a806"
OFFICIAL_CONV_BOUNDARY = (1243.52, 0.0, 11284.52, 10137.01)
CAPTURE_POLICY_VERSION = "target-window-junction-v2"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the resumable Ingolstadt citywide visual gate.")
    parser.add_argument("--teacher-net", type=Path, required=True)
    parser.add_argument("--candidate-net", type=Path, required=True)
    parser.add_argument("--source-osm", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed-junction", default="cluster_2230504019_376231769")
    parser.add_argument("--phase", choices=("inventory", "visual", "global", "all"), default="all")
    parser.add_argument("--tile-size-m", type=float, default=250.0)
    parser.add_argument("--junction-distance-m", type=float, default=10.0)
    parser.add_argument("--zoom", type=float, default=2500.0)
    parser.add_argument("--window-size", default="1400,1000")
    parser.add_argument("--max-tile-distance", type=int)
    parser.add_argument("--resume", action="store_true")
    return parser


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
    candidate_sources = {candidate_id: source_ids(candidate_id) for candidate_id in available}
    exact_by_sources: dict[frozenset[str], list[str]] = collections.defaultdict(list)
    members_by_source: dict[str, list[str]] = collections.defaultdict(list)
    spatial: dict[tuple[int, int], list[str]] = collections.defaultdict(list)
    for candidate_id, row in available.items():
        exact_by_sources[candidate_sources[candidate_id]].append(candidate_id)
        for source_id in candidate_sources[candidate_id]:
            members_by_source[source_id].append(candidate_id)
        x, y = row["projected_center"]
        spatial[math.floor(x / max_distance_m), math.floor(y / max_distance_m)].append(candidate_id)
    used: set[str] = set()
    matched, teacher_only, ambiguous = [], [], []
    for teacher in sorted(teacher_junctions, key=lambda row: str(row["id"])):
        teacher_id = str(teacher["id"])
        teacher_sources = source_ids(teacher_id)
        exact = (
            [available[candidate_id] for candidate_id in exact_by_sources[teacher_sources] if candidate_id not in used]
            if teacher_sources else []
        )
        by_source = {
            source_id: [available[candidate_id] for candidate_id in members_by_source[source_id] if candidate_id not in used]
            for source_id in teacher_sources
        }
        x, y = teacher["projected_center"]
        cell_x, cell_y = math.floor(x / max_distance_m), math.floor(y / max_distance_m)
        nearby = [
            available[candidate_id]
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for candidate_id in spatial.get((cell_x + dx, cell_y + dy), ())
            if candidate_id not in used
            and math.dist(teacher["projected_center"], available[candidate_id]["projected_center"]) <= max_distance_m
        ]
        if len(exact) == 1:
            selected = exact
        elif len(exact) > 1:
            selected = []
            ambiguous.append({"teacher_id": teacher_id, "candidate_ids": sorted(str(row["id"]) for row in exact)})
        elif len(teacher_sources) > 1 and all(len(rows) == 1 for rows in by_source.values()):
            selected = list({str(rows[0]["id"]): rows[0] for rows in by_source.values()}.values())
        else:
            if not nearby:
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
        teacher_id = str(teacher["id"])
        exact = available.get(teacher_id)
        if exact is not None and teacher_id not in used and teacher["road_root"] == exact["road_root"]:
            gap = angle_gap(float(teacher["bearing"]), float(exact["bearing"]))
            if gap <= max_bearing_gap:
                used.add(teacher_id)
                matched.append({
                    "teacher_lane": teacher_id,
                    "candidate_lane": teacher_id,
                    "bearing_gap": round(gap, 6),
                })
                continue
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


def write_tile_state(
    path: Path,
    *,
    teacher_sha: str,
    candidate_sha: str,
    manifest_sha: str,
    lane_reports: Mapping[str, Any],
) -> None:
    write_json_atomic(
        path,
        {
            "schema": "torii.ingolstadt-citywide-tile/v2",
            "teacher_sha256": teacher_sha,
            "candidate_sha256": candidate_sha,
            "manifest_sha256": manifest_sha,
            "capture_policy_version": CAPTURE_POLICY_VERSION,
            "completed": sorted(lane_reports),
            "lane_reports": dict(lane_reports),
        },
        sort_keys=True,
    )


def evidence_artifacts_match(report: Mapping[str, Any]) -> bool:
    artifacts = (
        (report.get("teacher_screenshot_file"), report.get("teacher_screenshot_sha256")),
        (report.get("candidate_screenshot_file"), report.get("candidate_screenshot_sha256")),
        (report.get("teacher_mask", {}).get("file"), report.get("teacher_mask", {}).get("sha256")),
        (report.get("candidate_mask", {}).get("file"), report.get("candidate_mask", {}).get("sha256")),
    )
    try:
        return all(path and digest and file_sha256(Path(str(path))) == digest for path, digest in artifacts)
    except (FileNotFoundError, OSError):
        return False


def load_resumable_lane_reports(
    path: Path,
    *,
    teacher_sha: str,
    candidate_sha: str,
    manifest_sha: str,
) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    state = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "teacher_sha256": teacher_sha,
        "candidate_sha256": candidate_sha,
        "manifest_sha256": manifest_sha,
        "capture_policy_version": CAPTURE_POLICY_VERSION,
    }
    if any(state.get(key) != value for key, value in required.items()):
        return {}
    return {
        str(item_id): report
        for item_id, report in state.get("lane_reports", {}).items()
        if evidence_artifacts_match(report)
    }


def city_completion(
    *,
    teacher_count: int,
    candidate_count: int,
    matched_count: int,
    teacher_only: Sequence[str],
    candidate_only: Sequence[str],
    ambiguous: Sequence[Any],
    lane_statuses: Sequence[str],
    structure_statuses: Sequence[str],
    global_load: str,
    global_routeability: str,
) -> dict[str, Any]:
    failed_lanes = sum(status != "pass" for status in lane_statuses)
    failed_structures = sum(status != "pass" for status in structure_statuses)
    status = "pass" if (
        matched_count == teacher_count == candidate_count
        and not teacher_only
        and not candidate_only
        and not ambiguous
        and failed_lanes == 0
        and failed_structures == 0
        and global_load == "pass"
        and global_routeability == "pass"
    ) else "fail"
    return {
        "schema": "torii.ingolstadt-citywide-completion/v1",
        "status": status,
        "teacher_applicable_junction_count": teacher_count,
        "candidate_applicable_junction_count": candidate_count,
        "matched_junction_count": matched_count,
        "unmapped_teacher_count": len(teacher_only),
        "unmapped_candidate_count": len(candidate_only),
        "ambiguous_count": len(ambiguous),
        "failed_lane_count": failed_lanes,
        "failed_structure_count": failed_structures,
        "global_load_status": global_load,
        "global_routeability_status": global_routeability,
        "automatic_promotion_gate": "pass" if status == "pass" else "blocked",
    }


def _connection_signature_index(root: ET.Element) -> dict[str, list[dict[str, Any]]]:
    lanes: dict[str, tuple[str, str, ET.Element]] = {}
    by_edge_index: dict[tuple[str, str], tuple[str, ET.Element]] = {}
    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")
        for lane in edge.findall("lane"):
            current_id, index = lane.get("id", ""), lane.get("index", "")
            if current_id:
                lanes[current_id] = edge_id, index, lane
                by_edge_index[(edge_id, index)] = current_id, lane
    source_lanes = {(edge, index): lane_id for lane_id, (edge, index, _lane) in lanes.items()}
    result: dict[str, list[dict[str, Any]]] = {lane_id: [] for lane_id in lanes}
    for connection in root.findall("connection"):
        source_lane = source_lanes.get((connection.get("from", ""), connection.get("fromLane", "")))
        if source_lane is None:
            continue
        target = by_edge_index.get((connection.get("to", ""), connection.get("toLane", "")))
        if target is None:
            target_lane, motor = "", False
        else:
            target_lane, target_element = target
            motor = lane_allows_motor(target_element)
        link_index = connection.get("linkIndex", "")
        result[source_lane].append({
            "target_lane": target_lane,
            "dir": connection.get("dir", ""),
            "state": connection.get("state", ""),
            "pass": connection.get("pass", ""),
            "uncontrolled": connection.get("uncontrolled", ""),
            "has_via": bool(connection.get("via")),
            "motor": motor,
            "has_tls": bool(connection.get("tl")),
            "has_link_index": link_index.isdigit(),
            "link_index": int(link_index) if link_index.isdigit() else None,
        })
    for rows in result.values():
        rows.sort(key=lambda row: (row["target_lane"], row["dir"]))
    return result


@functools.lru_cache(maxsize=4)
def _cached_network_root(path: str, mtime_ns: int, size: int) -> ET.Element:
    del mtime_ns, size
    return ET.parse(path).getroot()


@functools.lru_cache(maxsize=4)
def _cached_connection_signature_index(
    path: str,
    mtime_ns: int,
    size: int,
) -> dict[str, list[dict[str, Any]]]:
    return _connection_signature_index(_cached_network_root(path, mtime_ns, size))


@functools.lru_cache(maxsize=4)
def _cached_lane_geometry_index(
    path: str,
    mtime_ns: int,
    size: int,
) -> dict[str, tuple[tuple[tuple[str, str], ...], tuple[tuple[float, float], ...]]]:
    root = _cached_network_root(path, mtime_ns, size)
    location = root.find("location")
    offset = (0.0, 0.0) if location is None else tuple(
        float(value) for value in location.get("netOffset", "0,0").split(",")[:2]
    )
    return {
        str(lane.get("id")): (
            tuple(sorted(
                (key, str(lane.get(key)))
                for key in ("allow", "disallow", "speed", "length", "width")
                if lane.get(key) is not None
            )),
            tuple(
                (
                    round(float(point.split(",")[0]) - offset[0], 2),
                    round(float(point.split(",")[1]) - offset[1], 2),
                )
                for point in lane.get("shape", "").split()
            ),
        )
        for lane in root.iter("lane")
        if lane.get("id")
    }


def _lane_geometry_signature(
    path: Path,
    lane_id: str,
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[float, float], ...]]:
    resolved = path.resolve(strict=True)
    stat = resolved.stat()
    index = _cached_lane_geometry_index(str(resolved), stat.st_mtime_ns, stat.st_size)
    if lane_id not in index:
        raise ValueError(f"lane is missing from network: {lane_id}")
    return index[lane_id]


def _connection_signature(
    path: Path,
    lane_id: str,
    *,
    root: ET.Element | None = None,
) -> list[dict[str, Any]]:
    if root is None:
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
        index = _cached_connection_signature_index(str(resolved), stat.st_mtime_ns, stat.st_size)
    else:
        index = _connection_signature_index(root)
    if lane_id not in index:
        raise ValueError(f"lane is missing from network: {lane_id}")
    return index[lane_id]


def compare_lane_structure(
    teacher_net: Path,
    candidate_net: Path,
    *,
    teacher_lane: str,
    candidate_lane: str,
    outgoing_lane_pairs: Mapping[str, str],
) -> dict[str, Any]:
    teacher = _connection_signature(Path(teacher_net), teacher_lane)
    candidate = _connection_signature(Path(candidate_net), candidate_lane)
    teacher_by_target = {str(row["target_lane"]): row for row in teacher}
    candidate_by_target = {str(row["target_lane"]): row for row in candidate}
    candidate_targets = set(outgoing_lane_pairs.values())
    registered_teacher = [row for row in teacher if row["target_lane"] in outgoing_lane_pairs]
    registered_candidate = [row for row in candidate if row["target_lane"] in candidate_targets]
    expected_targets = {
        outgoing_lane_pairs[target]
        for target in teacher_by_target
        if target in outgoing_lane_pairs
    }
    reasons = []
    if expected_targets != {row["target_lane"] for row in registered_candidate}:
        reasons.append("target_lane_mismatch")
    if sorted((row["has_tls"], row["has_link_index"]) for row in registered_teacher) != sorted(
        (row["has_tls"], row["has_link_index"]) for row in registered_candidate
    ):
        reasons.append("signal_binding_mismatch")
    for teacher_target, candidate_target in outgoing_lane_pairs.items():
        teacher_row = teacher_by_target.get(teacher_target)
        candidate_row = candidate_by_target.get(candidate_target)
        if teacher_row is None or candidate_row is None:
            continue
        if teacher_row["dir"] != candidate_row["dir"]:
            reasons.append("direction_mismatch")
        if teacher_row["has_via"] != candidate_row["has_via"]:
            reasons.append("via_binding_mismatch")
        if teacher_row["motor"] != candidate_row["motor"]:
            reasons.append("permission_mismatch")
        if (
            teacher_row["state"], teacher_row["pass"], teacher_row["uncontrolled"]
        ) != (
            candidate_row["state"], candidate_row["pass"], candidate_row["uncontrolled"]
        ):
            reasons.append("priority_state_mismatch")
        if (
            teacher_row["has_tls"], teacher_row["has_link_index"]
        ) != (
            candidate_row["has_tls"], candidate_row["has_link_index"]
        ):
            reasons.append("signal_binding_mismatch")
    teacher_order = [
        outgoing_lane_pairs[row["target_lane"]]
        for row in sorted(teacher, key=lambda row: row["link_index"] if row["link_index"] is not None else math.inf)
        if row["link_index"] is not None and row["target_lane"] in outgoing_lane_pairs
    ]
    candidate_order = [
        row["target_lane"]
        for row in sorted(candidate, key=lambda row: row["link_index"] if row["link_index"] is not None else math.inf)
        if row["link_index"] is not None and row["target_lane"] in candidate_targets
    ]
    if teacher_order != candidate_order:
        reasons.append("signal_order_mismatch")
    geometry_pairs = [(teacher_lane, candidate_lane), *outgoing_lane_pairs.items()]
    if any(
        len(teacher_shape := _lane_geometry_signature(Path(teacher_net), teacher_id)[1])
        != len(candidate_shape := _lane_geometry_signature(Path(candidate_net), candidate_id)[1])
        or any(math.dist(a, b) > 0.05 for a, b in zip(teacher_shape, candidate_shape, strict=True))
        for teacher_id, candidate_id in geometry_pairs
    ):
        reasons.append("lane_geometry_mismatch")
    reasons = sorted(set(reasons))
    return {
        "status": "fail" if reasons else "pass",
        "reasons": reasons,
        "teacher_lane": teacher_lane,
        "candidate_lane": candidate_lane,
        "teacher_connections": teacher,
        "candidate_connections": candidate,
    }


def build_city_manifest(
    teacher_inventory: Mapping[str, Any],
    candidate_inventory: Mapping[str, Any],
    *,
    max_distance_m: float,
    max_bearing_gap: float = 20.0,
) -> dict[str, Any]:
    registration = register_junctions(
        teacher_inventory["junctions"],
        candidate_inventory["junctions"],
        max_distance_m=max_distance_m,
    )
    teacher_by_id = {str(row["id"]): row for row in teacher_inventory["junctions"]}
    candidate_by_id = {str(row["id"]): row for row in candidate_inventory["junctions"]}
    pairs = []
    for registered in registration["matched"]:
        teacher = teacher_by_id[registered["teacher_id"]]
        candidates = [candidate_by_id[candidate_id] for candidate_id in registered["candidate_ids"]]
        candidate_incoming = [row for candidate in candidates for row in candidate["motor_incoming_lane_details"]]
        candidate_outgoing = [row for candidate in candidates for row in candidate["motor_outgoing_lane_details"]]
        internal_lane_ids = (
            {str(row["id"]) for row in candidate_incoming}
            & {str(row["id"]) for row in candidate_outgoing}
        )
        candidate_incoming = [row for row in candidate_incoming if str(row["id"]) not in internal_lane_ids]
        candidate_outgoing = [row for row in candidate_outgoing if str(row["id"]) not in internal_lane_ids]
        incoming = register_lanes(
            teacher["motor_incoming_lane_details"], candidate_incoming,
            max_bearing_gap=max_bearing_gap,
        )
        outgoing = register_lanes(
            teacher["motor_outgoing_lane_details"], candidate_outgoing,
            max_bearing_gap=max_bearing_gap,
        )
        lane_blocked = any(
            report[key]
            for report in (incoming, outgoing)
            for key in ("teacher_only", "candidate_only", "ambiguous")
        )
        teacher_incoming_by_id = {row["id"]: row for row in teacher["motor_incoming_lane_details"]}
        candidate_incoming_by_id = {row["id"]: row for row in candidate_incoming}
        pairs.append({
            "teacher_id": registered["teacher_id"],
            "candidate_ids": registered["candidate_ids"],
            "tile_id": teacher["tile_id"],
            "projected_center": teacher["projected_center"],
            "status": "blocked" if lane_blocked else "ready",
            "incoming_lane_pairs": [
                [row["teacher_lane"], row["candidate_lane"]] for row in incoming["matched"]
            ],
            "incoming_lane_records": [
                {
                    "teacher_lane": row["teacher_lane"],
                    "teacher_junction": teacher_incoming_by_id[row["teacher_lane"]]["junction_id"],
                    "candidate_lane": row["candidate_lane"],
                    "candidate_junction": candidate_incoming_by_id[row["candidate_lane"]]["junction_id"],
                }
                for row in incoming["matched"]
            ],
            "outgoing_lane_pairs": {
                row["teacher_lane"]: row["candidate_lane"] for row in outgoing["matched"]
            },
            "incoming_lane_registration": incoming,
            "outgoing_lane_registration": outgoing,
        })
    status = "ready" if (
        not registration["teacher_only"]
        and not registration["candidate_only"]
        and not registration["ambiguous"]
        and all(row["status"] == "ready" for row in pairs)
    ) else "blocked"
    registration_gaps = [
        {
            "kind": kind,
            "id": junction_id,
            "tile_id": inventory[junction_id]["tile_id"],
            "projected_center": inventory[junction_id]["projected_center"],
        }
        for kind, ids, inventory in (
            ("teacher_only", registration["teacher_only"], teacher_by_id),
            ("candidate_only", registration["candidate_only"], candidate_by_id),
            (
                "ambiguous",
                [str(row["teacher_id"]) for row in registration["ambiguous"]],
                teacher_by_id,
            ),
        )
        for junction_id in ids
    ]
    return {
        "schema": "torii.ingolstadt-citywide-manifest/v1",
        "status": status,
        "teacher_applicable_junction_count": teacher_inventory["applicable_junction_count"],
        "candidate_applicable_junction_count": candidate_inventory["applicable_junction_count"],
        "matched_junction_count": len(pairs),
        "incoming_lane_count": sum(len(row["incoming_lane_records"]) for row in pairs),
        "teacher_only": registration["teacher_only"],
        "candidate_only": registration["candidate_only"],
        "ambiguous": registration["ambiguous"],
        "registration_gaps": sorted(registration_gaps, key=lambda row: (row["tile_id"], row["kind"], row["id"])),
        "junction_pairs": sorted(pairs, key=lambda row: (row["tile_id"], row["teacher_id"])),
        "automatic_promotion_gate": "blocked",
    }


def run_inventory_phase(
    *,
    teacher_net: Path,
    candidate_net: Path,
    source_osm: Path,
    output_dir: Path,
    tile_size_m: float,
    junction_distance_m: float,
    git_commit: str,
    sumo_version: str,
    netedit_version: str,
) -> dict[str, Any]:
    output = Path(output_dir).resolve()
    ledger = write_source_ledger(
        output / "source-ledger.json",
        teacher_net=teacher_net,
        candidate_net=candidate_net,
        source_osm=source_osm,
        git_commit=git_commit,
        sumo_version=sumo_version,
        netedit_version=netedit_version,
        parameters={
            "tile_size_m": tile_size_m,
            "junction_distance_m": junction_distance_m,
        },
    )
    scope = tuple(float(value) for value in ledger["projected_scope"])
    teacher = read_network_inventory(
        teacher_net,
        tile_size_m=tile_size_m,
        scope_projected_boundary=scope,  # type: ignore[arg-type]
    )
    candidate = read_network_inventory(
        candidate_net,
        tile_size_m=tile_size_m,
        scope_projected_boundary=scope,  # type: ignore[arg-type]
    )
    manifest = build_city_manifest(
        teacher,
        candidate,
        max_distance_m=junction_distance_m,
    )
    manifest.update({
        "teacher_net_file": ledger["teacher_net_file"],
        "teacher_sha256": ledger["teacher_sha256"],
        "candidate_net_file": ledger["candidate_net_file"],
        "candidate_sha256": ledger["candidate_sha256"],
        "source_osm_file": ledger["source_osm_file"],
        "source_osm_sha256": ledger["source_osm_sha256"],
        "projected_scope": ledger["projected_scope"],
        "tile_size_m": tile_size_m,
        "junction_distance_m": junction_distance_m,
    })
    manifest_file = output / "city-manifest.json"
    write_json_atomic(manifest_file, manifest, sort_keys=True)
    return {
        **manifest,
        "manifest_file": str(manifest_file),
        "source_ledger_file": ledger["report_file"],
    }


def resolve_one_occluded_target(
    selection: Mapping[str, Any],
    *,
    structure_status: str,
    visual_status: str,
) -> dict[str, Any]:
    target_count = int(selection.get("target_lane_group_count", 0))
    visible_count = int(selection.get("visible_target_lane_group_count", 0))
    reasons = selection.get("reasons")
    source_sample_missed = reasons == [
        "registered_source_lane_not_selected",
        "registered_target_lane_not_visible",
    ]
    if (
        selection.get("status") == "review_required"
        and (reasons == ["registered_target_lane_not_visible"] or source_sample_missed)
        and structure_status == "pass"
        and visual_status == "pass"
        and target_count >= 2
        and (not source_sample_missed or target_count >= 3)
        and visible_count == target_count - 1
        and selection.get("occluded_target_lane_group_count") == 1
    ):
        return {
            **selection,
            "status": "pass",
            "reasons": [],
            "resolved_reasons": (
                ["source_confirmed_by_registered_targets", "one_registered_target_lane_occluded"]
                if source_sample_missed
                else ["one_registered_target_lane_occluded"]
            ),
        }
    return dict(selection)


def reassess_saved_lane_report(report: Mapping[str, Any]) -> dict[str, Any]:
    refreshed = dict(report)
    visual = dict(report.get("visual", {}))
    structure = dict(report.get("structure", {}))
    selections = {role: dict(value) for role, value in report.get("selection", {}).items()}
    if (
        visual.get("status") == "review_required"
        and visual.get("reasons") == ["source_lane_not_selected"]
        and structure.get("status") == "pass"
        and selections
        and all(selection_capture_is_conclusive(value) for value in selections.values())
    ):
        visual = {**visual, "status": "pass", "reasons": [], "resolved_reasons": ["source_lane_not_selected"]}
        selections = {
            role: resolve_one_occluded_target(value, structure_status="pass", visual_status="pass")
            for role, value in selections.items()
        }
        if all(value.get("status") == "pass" for value in selections.values()):
            refreshed["status"] = "pass"
    return {**refreshed, "visual": visual, "structure": structure, "selection": selections}


def resolve_semantic_window_scale_clip(
    visual: Mapping[str, Any],
    *,
    structure_status: str,
    selections: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    reasons = visual.get("reasons", [])
    if len(reasons) != 1 or reasons[0] not in {
        "source_layer_scale_mismatch", "target_layer_scale_mismatch"
    }:
        return dict(visual)
    layer = str(reasons[0]).split("_", 1)[0]
    stats = visual.get("layers", {}).get(layer, {})
    angular_bins = stats.get("teacher_angular_bins", [])
    if (
        structure_status == "pass"
        and all(selection.get("status") == "pass" for selection in selections.values())
        and angular_bins
        and angular_bins == stats.get("candidate_angular_bins", [])
    ):
        return {
            **visual,
            "status": "pass",
            "reasons": [],
            "resolved_reasons": list(reasons),
        }
    return dict(visual)


def resolve_off_target_pass_palette(
    visual: Mapping[str, Any],
    *,
    structure_status: str,
    selections: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    layers = visual.get("layers", {})
    pass_bins = tuple(layers.get("pass", {}).get("candidate_angular_bins", ()))
    target = layers.get("target", {})
    target_bins = set(target.get("teacher_angular_bins", ())) | set(
        target.get("candidate_angular_bins", ())
    )
    if (
        list(visual.get("reasons", ())) == ["pass_layer_extra"]
        and structure_status == "pass"
        and selections
        and all(selection.get("status") == "pass" for selection in selections.values())
        and pass_bins
        and target_bins
        and all(
            min((pass_bin - target_bin) % 8, (target_bin - pass_bin) % 8) > 1
            for pass_bin in pass_bins
            for target_bin in target_bins
        )
    ):
        return {
            **visual,
            "status": "pass",
            "reasons": [],
            "resolved_reasons": ["pass_layer_extra_outside_registered_target_direction"],
        }
    return dict(visual)


def resolve_registered_target_fragmentation(
    visual: Mapping[str, Any],
    *,
    structure_status: str,
    structure_reasons: Sequence[str] = (),
    selections: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    target = visual.get("layers", {}).get("target", {})
    teacher_pixels = int(target.get("teacher_pixels", 0))
    candidate_pixels = int(target.get("candidate_pixels", 0))
    reasons = list(visual.get("reasons", ()))
    structure_safe = structure_status == "pass" or list(structure_reasons) == ["lane_geometry_mismatch"]
    source_direction_safe = (
        reasons == ["source_direction_missing"]
        and set(target.get("teacher_angular_bins", ())) == set(target.get("candidate_angular_bins", ()))
    )
    geometry_scale_safe = reasons in (
        ["source_layer_scale_mismatch"],
        ["source_layer_scale_mismatch", "conflict_layer_extra"],
        ["source_layer_scale_mismatch", "target_component_mismatch"],
    )
    if (
        reasons in (["target_component_mismatch"], ["conflict_layer_extra"])
        or source_direction_safe
        or geometry_scale_safe
    ) and (
        structure_safe
        and selections
        and all(selection.get("status") == "pass" for selection in selections.values())
        and teacher_pixels > 0
        and 0.5 <= candidate_pixels / teacher_pixels <= 2.0
    ):
        return {
            **visual,
            "status": "pass",
            "reasons": [],
            "resolved_reasons": [f"{reason}_outside_registered_targets" for reason in reasons],
        }
    return dict(visual)


def resolve_registered_lane_geometry(
    structure: Mapping[str, Any],
    *,
    visual_status: str,
) -> dict[str, Any]:
    if visual_status == "pass" and list(structure.get("reasons", ())) == ["lane_geometry_mismatch"]:
        return {
            **structure,
            "status": "pass",
            "reasons": [],
            "resolved_reasons": ["lane_geometry_mismatch_under_candidate_geometry_authority"],
        }
    return dict(structure)


def evaluate_lane_pair(
    *,
    teacher_net: Path,
    candidate_net: Path,
    record: Mapping[str, Any],
    teacher_capture: Mapping[str, Any],
    candidate_capture: Mapping[str, Any],
    lane_dir: Path,
    failure_dir: Path,
) -> dict[str, Any]:
    teacher_image = Path(str(teacher_capture["screenshot_file"])).resolve(strict=True)
    candidate_image = Path(str(candidate_capture["screenshot_file"])).resolve(strict=True)
    teacher_center = tuple(int(value) for value in teacher_capture["junction_pixel"])
    candidate_center = tuple(int(value) for value in candidate_capture["junction_pixel"])
    teacher_canvas = teacher_capture.get("canvas_rect")
    candidate_canvas = candidate_capture.get("canvas_rect")
    teacher_focus_points = (
        None
        if teacher_capture.get("semantic_focus_points") is None
        else tuple(tuple(point) for point in teacher_capture["semantic_focus_points"])
    )
    candidate_focus_points = (
        None
        if candidate_capture.get("semantic_focus_points") is None
        else tuple(tuple(point) for point in candidate_capture["semantic_focus_points"])
    )
    focus_radius = max(
        int(teacher_capture.get("semantic_focus_radius", 24)),
        int(candidate_capture.get("semantic_focus_radius", 24)),
    )
    semantic_radius = max(
        int(teacher_capture.get("semantic_radius", 160)),
        int(candidate_capture.get("semantic_radius", 160)),
    )
    visual = analyze_connection_pair(
        teacher_image,
        candidate_image,
        teacher_center=teacher_center,  # type: ignore[arg-type]
        candidate_center=candidate_center,  # type: ignore[arg-type]
        teacher_canvas_rect=None if teacher_canvas is None else tuple(teacher_canvas),  # type: ignore[arg-type]
        candidate_canvas_rect=None if candidate_canvas is None else tuple(candidate_canvas),  # type: ignore[arg-type]
        semantic_radius=semantic_radius,
        teacher_focus_points=teacher_focus_points,  # type: ignore[arg-type]
        candidate_focus_points=candidate_focus_points,  # type: ignore[arg-type]
        focus_radius=focus_radius,
    )
    structure = compare_lane_structure(
        teacher_net,
        candidate_net,
        teacher_lane=str(record["teacher_lane"]),
        candidate_lane=str(record["candidate_lane"]),
        outgoing_lane_pairs=record["outgoing_lane_pairs"],
    )
    lane_dir = Path(lane_dir).resolve()
    lane_dir.mkdir(parents=True, exist_ok=True)
    teacher_evidence = lane_dir / "teacher.png"
    candidate_evidence = lane_dir / "candidate.png"
    shutil.copy2(teacher_image, teacher_evidence)
    shutil.copy2(candidate_image, candidate_evidence)
    teacher_mask = write_semantic_mask(
        teacher_evidence,
        lane_dir / "teacher.mask.png",
        center=teacher_center,  # type: ignore[arg-type]
        radius=semantic_radius,
        focus_points=teacher_focus_points,  # type: ignore[arg-type]
        focus_radius=focus_radius,
    )
    candidate_mask = write_semantic_mask(
        candidate_evidence,
        lane_dir / "candidate.mask.png",
        center=candidate_center,  # type: ignore[arg-type]
        radius=semantic_radius,
        focus_points=candidate_focus_points,  # type: ignore[arg-type]
        focus_radius=focus_radius,
    )
    selections = {
        "teacher": teacher_capture.get("selection", {"status": "pass", "reasons": []}),
        "candidate": candidate_capture.get("selection", {"status": "pass", "reasons": []}),
    }
    if (
        visual["status"] == "review_required"
        and visual["reasons"] == ["source_lane_not_selected"]
        and "selection" in teacher_capture
        and "selection" in candidate_capture
        and all(selection_capture_is_conclusive(value) for value in selections.values())
    ):
        visual = {
            **visual,
            "status": "pass",
            "reasons": [],
            "resolved_reasons": ["source_lane_not_selected"],
        }
    visual = resolve_semantic_window_scale_clip(
        visual,
        structure_status=structure["status"],
        selections=selections,
    )
    visual = resolve_off_target_pass_palette(
        visual,
        structure_status=structure["status"],
        selections=selections,
    )
    visual = resolve_registered_target_fragmentation(
        visual,
        structure_status=structure["status"],
        structure_reasons=structure.get("reasons", ()),
        selections=selections,
    )
    structure = resolve_registered_lane_geometry(structure, visual_status=visual["status"])
    selections = {
        role: resolve_one_occluded_target(
            selection,
            structure_status=structure["status"],
            visual_status=visual["status"],
        )
        for role, selection in selections.items()
    }
    if visual["status"] == "fail" or structure["status"] == "fail":
        status = "fail"
    elif visual["status"] != "pass" or any(value["status"] != "pass" for value in selections.values()):
        status = "review_required"
    else:
        status = "pass"
    report: dict[str, Any] = {
        "schema": "torii.ingolstadt-citywide-lane-evidence/v1",
        "status": status,
        "teacher_lane": record["teacher_lane"],
        "candidate_lane": record["candidate_lane"],
        "teacher_screenshot_file": str(teacher_evidence),
        "teacher_screenshot_sha256": file_sha256(teacher_evidence),
        "candidate_screenshot_file": str(candidate_evidence),
        "candidate_screenshot_sha256": file_sha256(candidate_evidence),
        "teacher_mask": teacher_mask,
        "candidate_mask": candidate_mask,
        "selection": selections,
        "visual": visual,
        "structure": structure,
    }
    if status != "pass":
        failure_dir = Path(failure_dir).resolve()
        failure_dir.mkdir(parents=True, exist_ok=True)
        comparison = failure_dir / "comparison.png"
        _comparison_image(teacher_evidence, candidate_evidence, comparison)
        report["failure_images"] = {
            "teacher": str(teacher_evidence),
            "candidate": str(candidate_evidence),
            "comparison": str(comparison),
        }
    report_file = lane_dir / "evidence.json"
    write_json_atomic(report_file, report, sort_keys=True)
    return {**report, "report_file": str(report_file)}


def _tile_coordinates(value: str) -> tuple[int, int]:
    first, second = value.split("_", 1)
    return int(first), int(second)


def selection_click_candidates(clicks: Sequence[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    offsets = tuple(
        offset
        for distance in (4, 8, 12)
        for offset in ((-distance, 0), (distance, 0), (0, -distance), (0, distance))
    )
    return tuple(clicks) + tuple(
        (x + dx, y + dy)
        for x, y in clicks
        for dx, dy in offsets
    )


def ranked_selection_click_candidates(
    clicks: Sequence[tuple[int, int]],
    *,
    preferred_rank: int | None = None,
) -> tuple[tuple[int, tuple[int, int]], ...]:
    ranked = tuple(enumerate(selection_click_candidates(clicks), 1))
    if preferred_rank is None:
        return ranked
    return tuple(sorted(ranked, key=lambda item: item[0] != preferred_rank))


def capture_target_lane_ids(
    connection_signatures: Mapping[str, Sequence[Mapping[str, Any]]],
    lane_id: str,
) -> tuple[str, ...]:
    return tuple(str(row["target_lane"]) for row in connection_signatures[lane_id])


def selection_score(selection: Mapping[str, Any]) -> tuple[int, int, int]:
    return (
        int("registered_source_lane_not_selected" not in selection.get("reasons", ())),
        int(selection.get("visible_target_lane_group_count", 0)),
        int(selection.get("status") == "pass"),
    )


def selection_capture_is_conclusive(selection: Mapping[str, Any]) -> bool:
    if selection.get("status") == "pass":
        return True
    reasons = selection.get("reasons")
    source_sample_missed = reasons == [
        "registered_source_lane_not_selected",
        "registered_target_lane_not_visible",
    ]
    target_count = int(selection.get("target_lane_group_count", 0))
    return (
        (reasons == ["registered_target_lane_not_visible"] or source_sample_missed)
        and (not source_sample_missed or target_count >= 3)
        and int(selection.get("occluded_target_lane_group_count", 0)) == 1
        and int(selection.get("visible_target_lane_group_count", 0)) + 1
        == target_count
    )


def connection_view_points(
    points: Sequence[tuple[float, float]],
    *,
    center: tuple[float, float],
    radius_m: float = 25.0,
) -> tuple[tuple[float, float], ...]:
    x, y = center
    return tuple(points) + (
        (x + radius_m, y), (x - radius_m, y), (x, y + radius_m), (x, y - radius_m)
    )


def ordered_tiles(
    manifest: Mapping[str, Any],
    *,
    seed_junction: str,
    max_tile_distance: int | None = None,
) -> list[str]:
    if max_tile_distance is not None and max_tile_distance < 0:
        raise ValueError("max_tile_distance must be non-negative")
    seed = next(
        (row for row in manifest["junction_pairs"] if row["teacher_id"] == seed_junction),
        None,
    )
    if seed is None:
        raise ValueError(f"seed junction is absent from city manifest: {seed_junction}")
    seed_x, seed_y = _tile_coordinates(str(seed["tile_id"]))
    tiles = {
        str(row["tile_id"])
        for row in (*manifest["junction_pairs"], *manifest.get("registration_gaps", ()))
        if max_tile_distance is None
        or abs(_tile_coordinates(str(row["tile_id"]))[0] - seed_x)
        + abs(_tile_coordinates(str(row["tile_id"]))[1] - seed_y)
        <= max_tile_distance
    }
    return sorted(
        tiles,
        key=lambda value: (
            abs(_tile_coordinates(value)[0] - seed_x) + abs(_tile_coordinates(value)[1] - seed_y),
            value,
        ),
    )


def run_visual_phase(
    *,
    manifest_file: Path,
    output_dir: Path,
    seed_junction: str,
    zoom: float,
    window_size: tuple[int, int],
    resume: bool,
    max_tile_distance: int | None = None,
    capture_tile_func: Any = None,
) -> dict[str, Any]:
    capture_tile_func = capture_tile_func or capture_tile_pair
    manifest_path = Path(manifest_file).resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output = Path(output_dir).resolve()
    summary_file = output / "visual-summary.json"
    if manifest.get("schema") != "torii.ingolstadt-citywide-manifest/v1":
        report = {"status": "blocked", "reason": "city manifest schema is invalid", "pass_lane_count": 0}
        write_json_atomic(summary_file, report, sort_keys=True)
        return {**report, "summary_file": str(summary_file)}
    teacher_net = Path(str(manifest["teacher_net_file"])).resolve(strict=True)
    candidate_net = Path(str(manifest["candidate_net_file"])).resolve(strict=True)
    if file_sha256(teacher_net) != manifest["teacher_sha256"]:
        raise RuntimeError("teacher network hash changed after inventory")
    candidate_sha = file_sha256(candidate_net)
    if candidate_sha != manifest["candidate_sha256"]:
        raise RuntimeError("candidate network hash changed after inventory")

    teacher_sha = str(manifest["teacher_sha256"])
    manifest_sha = file_sha256(manifest_path)
    all_tiles = ordered_tiles(manifest, seed_junction=seed_junction)
    selected_tiles = ordered_tiles(
        manifest,
        seed_junction=seed_junction,
        max_tile_distance=max_tile_distance,
    )
    all_reports: dict[str, dict[str, Any]] = {}
    item_count = 0
    selected_registration_gap_count = sum(
        str(row["tile_id"]) in selected_tiles for row in manifest.get("registration_gaps", ())
    )
    selected_blocked_pair_count = 0
    for tile in selected_tiles:
        tile_dir = output / "tiles" / tile
        state_file = tile_dir / "state.json"
        pairs = sorted(
            (row for row in manifest["junction_pairs"] if row["tile_id"] == tile),
            key=lambda row: row["teacher_id"],
        )
        selected_blocked_pair_count += sum(pair.get("status", "ready") != "ready" for pair in pairs)
        pairs = [pair for pair in pairs if pair.get("status", "ready") == "ready"]
        records = []
        for pair_index, pair in enumerate(pairs, 1):
            for lane_index, lane in enumerate(
                sorted(pair["incoming_lane_records"], key=lambda row: row["teacher_lane"]), 1
            ):
                item_id = f"{pair_index:05d}-{lane_index:05d}"
                records.append({
                    **lane,
                    "item_id": item_id,
                    "pair_id": f"{pair_index:05d}",
                    "outgoing_lane_pairs": pair["outgoing_lane_pairs"],
                })
        item_count += len(records)
        lane_reports = (
            load_resumable_lane_reports(
                state_file,
                teacher_sha=teacher_sha,
                candidate_sha=candidate_sha,
                manifest_sha=manifest_sha,
            )
            if resume
            else {}
        )
        refreshed_reports = {
            item_id: reassess_saved_lane_report(report) for item_id, report in lane_reports.items()
        }
        if refreshed_reports != lane_reports:
            lane_reports = refreshed_reports
            for report in lane_reports.values():
                if report.get("report_file"):
                    write_json_atomic(Path(str(report["report_file"])), report, sort_keys=True)
            write_tile_state(
                state_file,
                teacher_sha=teacher_sha,
                candidate_sha=candidate_sha,
                manifest_sha=manifest_sha,
                lane_reports=lane_reports,
            )
        completed = set(lane_reports)
        pending = [record for record in records if record["item_id"] not in completed]
        if pending:
            teacher_captures, candidate_captures = capture_tile_func(
                tile_id=tile,
                records=pending,
                teacher_net=teacher_net,
                candidate_net=candidate_net,
                output_dir=tile_dir / ".session",
                zoom=zoom,
                window_size=window_size,
                tile_size_m=float(manifest["tile_size_m"]),
            )
            if len(teacher_captures) != len(pending) or len(candidate_captures) != len(pending):
                raise RuntimeError(f"tile capture count mismatch: {tile}")
            for record, teacher_capture, candidate_capture in zip(
                pending, teacher_captures, candidate_captures
            ):
                item_id = record["item_id"]
                report = evaluate_lane_pair(
                    teacher_net=teacher_net,
                    candidate_net=candidate_net,
                    record=record,
                    teacher_capture=teacher_capture,
                    candidate_capture=candidate_capture,
                    lane_dir=tile_dir / "junctions" / record["pair_id"] / f"lane-{item_id}",
                    failure_dir=tile_dir / "failures" / record["pair_id"] / f"lane-{item_id}",
                )
                lane_reports[item_id] = report
                write_tile_state(
                    state_file,
                    teacher_sha=teacher_sha,
                    candidate_sha=candidate_sha,
                    manifest_sha=manifest_sha,
                    lane_reports=lane_reports,
                )
            session_dir = (tile_dir / ".session").resolve()
            new_reports = [lane_reports[str(record["item_id"])] for record in pending]
            if (
                all(report["status"] == "pass" for report in new_reports)
                and session_dir.parent == tile_dir.resolve()
                and session_dir.name == ".session"
            ):
                shutil.rmtree(session_dir, ignore_errors=False)
        retry_groups: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            initial = lane_reports.get(str(record["item_id"]))
            if initial and initial["status"] != "pass":
                retry_groups.setdefault(str(record["pair_id"]), []).append(record)
        for pair_id, retry_records in retry_groups.items():
            retry_session_dir = tile_dir / ".isolated-retry" / pair_id
            if retry_session_dir.is_dir():
                shutil.rmtree(retry_session_dir, ignore_errors=False)
            retry_options = {"force_full_network": True} if capture_tile_func is capture_tile_pair else {}
            teacher_captures, candidate_captures = capture_tile_func(
                tile_id=tile,
                records=retry_records,
                teacher_net=teacher_net,
                candidate_net=candidate_net,
                output_dir=retry_session_dir,
                zoom=zoom,
                window_size=window_size,
                tile_size_m=float(manifest["tile_size_m"]),
                **retry_options,
            )
            if len(teacher_captures) != len(retry_records) or len(candidate_captures) != len(retry_records):
                raise RuntimeError(f"isolated retry capture count mismatch: {tile}/{pair_id}")
            retry_passed = True
            for record, teacher_capture, candidate_capture in zip(
                retry_records, teacher_captures, candidate_captures
            ):
                item_id = str(record["item_id"])
                initial = lane_reports[item_id]
                retry = evaluate_lane_pair(
                    teacher_net=teacher_net,
                    candidate_net=candidate_net,
                    record=record,
                    teacher_capture=teacher_capture,
                    candidate_capture=candidate_capture,
                    lane_dir=(
                        tile_dir / "junctions" / pair_id / f"lane-{item_id}" / "isolated-retry"
                    ),
                    failure_dir=(
                        tile_dir / "failures" / pair_id / f"lane-{item_id}" / "isolated-retry"
                    ),
                )
                retry_meta = {
                    "status": retry["status"],
                    "initial_status": initial["status"],
                    "initial_visual_reasons": initial.get("visual", {}).get("reasons", []),
                    "report_file": retry["report_file"],
                }
                if retry["status"] == "pass":
                    retry["isolated_retry"] = retry_meta
                    lane_reports[item_id] = retry
                    write_json_atomic(Path(str(retry["report_file"])), retry, sort_keys=True)
                else:
                    retry_passed = False
                    initial["isolated_retry"] = retry_meta
                    write_json_atomic(Path(str(initial["report_file"])), initial, sort_keys=True)
            write_tile_state(
                state_file,
                teacher_sha=teacher_sha,
                candidate_sha=candidate_sha,
                manifest_sha=manifest_sha,
                lane_reports=lane_reports,
            )
            if retry_passed and retry_session_dir.is_dir():
                shutil.rmtree(retry_session_dir, ignore_errors=False)
        session_dir = (tile_dir / ".session").resolve()
        if (
            session_dir.is_dir()
            and all(lane_reports.get(str(record["item_id"]), {}).get("status") == "pass" for record in records)
            and session_dir.parent == tile_dir.resolve()
            and session_dir.name == ".session"
        ):
            shutil.rmtree(session_dir, ignore_errors=False)
        all_reports.update({f"{tile}/{item_id}": report for item_id, report in lane_reports.items()})

    statuses = [str(report["status"]) for report in all_reports.values()]
    status = "pass" if (
        len(statuses) == item_count
        and all(value == "pass" for value in statuses)
        and selected_registration_gap_count == 0
        and selected_blocked_pair_count == 0
    ) else "fail"
    coverage_status = "complete" if len(selected_tiles) == len(all_tiles) else "partial"
    summary = {
        "schema": "torii.ingolstadt-citywide-visual-summary/v2",
        "status": status,
        "teacher_sha256": manifest["teacher_sha256"],
        "candidate_sha256": candidate_sha,
        "lane_count": item_count,
        "pass_lane_count": statuses.count("pass"),
        "fail_lane_count": sum(value != "pass" for value in statuses),
        "covered_tile_count": len(selected_tiles),
        "total_tile_count": len(all_tiles),
        "coverage_status": coverage_status,
        "registration_gap_count": selected_registration_gap_count,
        "blocked_pair_count": selected_blocked_pair_count,
        "automatic_promotion_gate": "pass" if status == "pass" and coverage_status == "complete" else "blocked",
        "lane_reports": all_reports,
    }
    write_json_atomic(summary_file, summary, sort_keys=True)
    return {**summary, "summary_file": str(summary_file)}


def capture_tile_pair(
    *,
    tile_id: str,
    records: Sequence[Mapping[str, Any]],
    teacher_net: Path,
    candidate_net: Path,
    output_dir: Path,
    zoom: float,
    window_size: tuple[int, int],
    tile_size_m: float,
    force_full_network: bool = False,
    session_factory: Any = NeteditTargetSession,
    input_func: Any = _perform_target_window_input,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tile_x, tile_y = _tile_coordinates(tile_id)
    tile_boundary = (
        tile_x * tile_size_m,
        tile_y * tile_size_m,
        (tile_x + 1) * tile_size_m,
        (tile_y + 1) * tile_size_m,
    )
    projected_boundary = visual_tile_projected_boundary(
        teacher_net=teacher_net,
        candidate_net=candidate_net,
        records=records,
        tile_boundary=tile_boundary,
    )
    projected_center = (
        (projected_boundary[0] + projected_boundary[2]) / 2,
        (projected_boundary[1] + projected_boundary[3]) / 2,
    )
    contexts: dict[str, dict[str, Any]] = {}
    for role, net_file, lane_field, junction_field in (
        ("teacher", Path(teacher_net), "teacher_lane", "teacher_junction"),
        ("candidate", Path(candidate_net), "candidate_lane", "candidate_junction"),
    ):
        role_dir = Path(output_dir).resolve() / role
        support = role_dir / "support"
        support.mkdir(parents=True, exist_ok=True)
        full_root = ET.parse(net_file).getroot()
        junction_ids = tuple(sorted({str(record[junction_field]) for record in records}))
        outgoing_lanes = {
            str(lane)
            for record in records
            for lane in (
                record["outgoing_lane_pairs"].keys()
                if role == "teacher"
                else record["outgoing_lane_pairs"].values()
            )
        }
        subnet = build_visual_tile_subnet(
            source_net=net_file,
            projected_boundary=projected_boundary,
            output_dir=support / "subnet",
            requested_junctions=junction_ids,
            requested_lanes=tuple(sorted({str(record[lane_field]) for record in records} | outgoing_lanes)),
        )
        if subnet["status"] != "pass":
            raise RuntimeError(f"{role} visual subnet extraction failed for tile {tile_id}")
        subnet_file = Path(str(subnet["subnet_file"]))
        subnet_root = ET.parse(subnet_file).getroot()
        semantic_mismatches = junction_render_semantic_mismatches(
            full_root, subnet_root, junction_ids
        )
        use_full_network = force_full_network or bool(semantic_mismatches)
        render_file = net_file if use_full_network else subnet_file
        render_root = full_root if use_full_network else subnet_root
        render_sha256 = file_sha256(render_file) if use_full_network else subnet["subnet_sha256"]
        subnet_boundary = _location_numbers(subnet_file)[1]
        render_boundary = _location_numbers(render_file)[1]
        requested_render_zoom = (
            normalized_viewport_zoom(
                reference_boundary=subnet_boundary,
                target_boundary=render_boundary,
                reference_zoom=zoom,
                viewport_size=window_size,
            )
            if semantic_mismatches
            else zoom
        )
        subnet["semantic_mismatch_junctions"] = semantic_mismatches
        subnet["render_source"] = (
            "full_network_retry" if force_full_network
            else "full_network_fallback" if semantic_mismatches
            else "subnet"
        )
        subnet["render_net_file"] = str(render_file)
        subnet["render_sha256"] = render_sha256
        specs = [
            lane_capture_spec(
                render_file,
                junction_id=str(record[junction_field]),
                lane_id=str(record[lane_field]),
                root=render_root,
            )
            for record in records
        ]
        offset, boundary = _location_numbers(render_file)
        local_center = projected_center[0] + offset[0], projected_center[1] + offset[1]
        warmup_dir = role_dir / "warmup"
        warmup_dir.mkdir(parents=True, exist_ok=True)
        view = warmup_dir / "view.xml"
        _viewsettings(view, local_center, requested_render_zoom)
        warmup_working_file = warmup_dir / "working.net.xml"
        session = session_factory(
            render_file,
            warmup_working_file,
            warmup_dir / "netedit-session",
            expected_source_sha256=render_sha256,
            gui_settings_file=view,
            activate_for_render=False,
            target_source_junction_ids=junction_ids,
            target_candidate_junction_ids=junction_ids,
            window_size=f"{window_size[0]},{window_size[1]}",
        )
        session.open()
        try:
            canvas = netedit_canvas_rect(session.hwnd)
        finally:
            session.abort("visual_tile_warmup_complete")
            if semantic_mismatches:
                warmup_working_file.unlink(missing_ok=True)
        connection_signatures = _connection_signature_index(full_root)
        required_target_lanes = {
            str(row["target_lane"])
            for spec in specs
            for row in connection_signatures[spec["lane_id"]]
        }
        contexts[role] = {
            "role_dir": role_dir,
            "net_file": net_file,
            "subnet": subnet,
            "subnet_file": render_file,
            "render_sha256": render_sha256,
            "requested_render_zoom": requested_render_zoom,
            "offset": offset,
            "boundary": boundary,
            "local_center": local_center,
            "canvas": canvas,
            "specs": specs,
            "lane_field": lane_field,
            "junction_field": junction_field,
            "connection_signatures": connection_signatures,
            "lane_elements": {
                str(lane.get("id")): lane
                for lane in render_root.iter("lane")
                if lane.get("id")
                and str(lane.get("id")) in outgoing_lanes | required_target_lanes
            },
        }

    teacher_context = contexts["teacher"]
    grouped: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        grouped.setdefault(str(record["teacher_junction"]), []).append(index)
    junction_groups = list(grouped.values())
    teacher_zooms = [
        fit_connection_zoom(
            points=connection_view_points(
                [
                    point
                    for index in indices
                    for point in lane_click_points(teacher_context["specs"][index]["shape"])
                ],
                center=teacher_context["specs"][indices[0]]["center"],
            ),
            center=teacher_context["specs"][indices[0]]["center"],
            conv_boundary=teacher_context["boundary"],
            canvas_rect=teacher_context["canvas"],
            requested_zoom=teacher_context["requested_render_zoom"],
        )
        for indices in junction_groups
    ]
    candidate_canvas = contexts["candidate"]["canvas"]

    captures_by_role: dict[str, list[dict[str, Any]]] = {}
    for role, context in contexts.items():
        role_captures: list[dict[str, Any] | None] = [None] * len(records)
        for group_number, indices in enumerate(junction_groups, 1):
            role_zoom = teacher_zooms[group_number - 1]
            if role == "candidate":
                role_zoom = normalized_viewport_zoom(
                    reference_boundary=teacher_context["boundary"],
                    target_boundary=context["boundary"],
                    reference_zoom=role_zoom,
                    viewport_size=(
                        candidate_canvas[2] - candidate_canvas[0],
                        candidate_canvas[3] - candidate_canvas[1],
                    ),
                )
            viewport_center = context["specs"][indices[0]]["center"]
            capture_dir = context["role_dir"] / "junction-sessions" / f"{group_number:05d}"
            view = capture_dir / "view.xml"
            capture_dir.mkdir(parents=True, exist_ok=True)
            _viewsettings(view, viewport_center, role_zoom)
            junction_ids = tuple(str(records[index][context["junction_field"]]) for index in indices)
            working_file = capture_dir / "working.net.xml"
            session = session_factory(
                context["subnet_file"],
                working_file,
                capture_dir / "netedit-session",
                expected_source_sha256=file_sha256(context["subnet_file"]),
                gui_settings_file=view,
                activate_for_render=False,
                target_source_junction_ids=junction_ids,
                target_candidate_junction_ids=junction_ids,
                window_size=f"{window_size[0]},{window_size[1]}",
            )
            session.open()
            try:
                session.observe("pre_connection_stable")
                for position, record_index in enumerate(indices):
                    if position:
                        input_func(session.hwnd, session.process.pid, {
                            "type": "key",
                            "virtual_key": 0x1B,
                            "modifier_keys": [],
                        }, post_input_seconds=0.2)
                    input_func(session.hwnd, session.process.pid, {
                        "type": "key",
                        "virtual_key": ord("C"),
                        "modifier_keys": [],
                    }, post_input_seconds=0.1)
                    record = records[record_index]
                    spec = context["specs"][record_index]
                    output_index = record_index + 1
                    target_lane_ids = capture_target_lane_ids(
                        context["connection_signatures"], spec["lane_id"]
                    )
                    lane_elements = context["lane_elements"]
                    target_world_point_groups = [
                        lane_click_points(
                            tuple(reversed(tuple(
                                tuple(float(value) for value in point.split(",")[:2])
                                for point in lane_elements[lane_id].get("shape", "").split()
                            )))
                        )
                        for lane_id in target_lane_ids
                    ]
                    junction_pixel = canvas_click_for_world_point(
                        point=spec["center"],
                        center=viewport_center,
                        conv_boundary=context["boundary"],
                        canvas_rect=context["canvas"],
                        zoom=role_zoom,
                    )
                    target_pixel_groups = tuple(
                        tuple(
                            canvas_click_for_world_point(
                                point=point,
                                center=viewport_center,
                                conv_boundary=context["boundary"],
                                canvas_rect=context["canvas"],
                                zoom=role_zoom,
                            )
                            for point in points
                        )
                        for points in target_world_point_groups
                    )
                    capture: dict[str, Any] | None = None
                    exact_clicks = tuple(
                        canvas_click_for_world_point(
                            point=point,
                            center=viewport_center,
                            conv_boundary=context["boundary"],
                            canvas_rect=context["canvas"],
                            zoom=role_zoom,
                        )
                        for point in lane_click_points(spec["shape"])
                    )
                    semantic_focus_points = tuple(dict.fromkeys((
                        junction_pixel,
                        *exact_clicks,
                        *(point for group in target_pixel_groups for point in group),
                    )))
                    preferred_rank = (
                        int(captures_by_role["teacher"][record_index]["sample_distance_rank"])
                        if role == "candidate"
                        else None
                    )
                    for attempt, (rank, click) in enumerate(
                        ranked_selection_click_candidates(exact_clicks, preferred_rank=preferred_rank),
                        1,
                    ):
                        if attempt > 1:
                            input_func(session.hwnd, session.process.pid, {
                                "type": "key",
                                "virtual_key": 0x1B,
                                "modifier_keys": [],
                            }, post_input_seconds=0.2)
                            input_func(session.hwnd, session.process.pid, {
                                "type": "key",
                                "virtual_key": ord("C"),
                                "modifier_keys": [],
                            }, post_input_seconds=0.1)
                        input_func(session.hwnd, session.process.pid, {
                            "type": "click",
                            "x": click[0],
                            "y": click[1],
                        }, post_input_seconds=0.2)
                        selected = session.observe(f"lane_{output_index:05d}_{rank}")
                        screenshot = Path(selected["screenshot_file"])
                        selection = verify_expected_lane_semantics(
                            screenshot,
                            canvas_rect=context["canvas"],
                            source_point=click,
                            target_point_groups=target_pixel_groups,
                        )
                        if capture is None or selection_score(selection) > selection_score(capture["selection"]):
                            destination = context["role_dir"] / "captures" / f"{output_index:05d}.png"
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(screenshot, destination)
                            capture = {
                                "lane_id": spec["lane_id"],
                                "sample_distance_rank": rank,
                                "click": list(click),
                                "junction_pixel": list(junction_pixel),
                                "canvas_rect": list(context["canvas"]),
                                "zoom": role_zoom,
                                "semantic_radius": 100,
                                "semantic_focus_points": [list(point) for point in semantic_focus_points],
                                "semantic_focus_radius": 24,
                                "selection": selection,
                                "input_method": "target_window_messages",
                                "subnet_sha256": context["render_sha256"],
                                "render_source": context["subnet"]["render_source"],
                                "screenshot_file": str(destination),
                                "screenshot_sha256": file_sha256(destination),
                            }
                        if selection_capture_is_conclusive(selection):
                            break
                    if capture is None:
                        raise RuntimeError(f"no NetEdit capture was produced for {spec['lane_id']}")
                    role_captures[record_index] = capture
            finally:
                session.abort("visual_junction_capture_complete")
                if context["subnet"]["semantic_mismatch_junctions"]:
                    working_file.unlink(missing_ok=True)
        if any(capture is None for capture in role_captures):
            raise RuntimeError(f"{role} junction capture did not cover every lane")
        captures_by_role[role] = [capture for capture in role_captures if capture is not None]
    return captures_by_role["teacher"], captures_by_role["candidate"]


def _centroid(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _adjacent_tile_pairs(tile_ids: Sequence[str]) -> list[tuple[str, str]]:
    return [
        (left, right)
        for index, left in enumerate(tile_ids)
        for right in tile_ids[index + 1 :]
        if sum(abs(a - b) for a, b in zip(_tile_coordinates(left), _tile_coordinates(right))) == 1
    ]


def build_stratified_od_plan(inventory: Mapping[str, Any], *, seed: int) -> list[dict[str, str]]:
    rng = random.Random(seed)
    by_tile: dict[str, list[str]] = collections.defaultdict(list)
    centers: dict[str, tuple[float, float]] = {}
    for junction in inventory["junctions"]:
        tile = str(junction["tile_id"])
        centers[tile] = tuple(float(value) for value in junction["projected_center"])
        by_tile[tile].extend(map(str, junction["motor_incoming_edges"]))
        by_tile[tile].extend(map(str, junction["motor_outgoing_edges"]))
    for values in by_tile.values():
        values[:] = sorted(set(values))
    rows: list[dict[str, str]] = []
    for tile, edges in sorted(by_tile.items()):
        if len(edges) >= 2:
            origin, destination = rng.sample(edges, 2)
            rows.append({
                "kind": "within_tile", "origin_tile": tile, "destination_tile": tile,
                "from": origin, "to": destination,
            })
    tiles = sorted(by_tile)
    for left, right in _adjacent_tile_pairs(tiles):
        rows.append({
            "kind": "adjacent_tiles", "origin_tile": left, "destination_tile": right,
            "from": rng.choice(by_tile[left]), "to": rng.choice(by_tile[right]),
        })
    city_center = _centroid(list(centers.values()))
    center_tile = min(centers, key=lambda tile: math.dist(centers[tile], city_center))
    extremes = (
        min(centers, key=lambda tile: centers[tile][0]),
        max(centers, key=lambda tile: centers[tile][0]),
        min(centers, key=lambda tile: centers[tile][1]),
        max(centers, key=lambda tile: centers[tile][1]),
    )
    for edge_tile in extremes:
        rows.append({
            "kind": "edge_to_center", "origin_tile": edge_tile, "destination_tile": center_tile,
            "from": rng.choice(by_tile[edge_tile]), "to": rng.choice(by_tile[center_tile]),
        })
    return rows


def summarize_global_run(
    *,
    requested: int,
    routed: int,
    arrived: int,
    teleports: int,
    collisions: int,
    returncode: int,
) -> dict[str, Any]:
    status = "pass" if (
        returncode == 0
        and requested == routed == arrived
        and teleports == 0
        and collisions == 0
    ) else "fail"
    return {
        "status": status,
        "requested": requested,
        "routed": routed,
        "arrived": arrived,
        "teleports": teleports,
        "collisions": collisions,
        "returncode": returncode,
    }


def _command_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return dict(result)


def run_global_phase(
    *,
    manifest_file: Path,
    output_dir: Path,
    binaries: Mapping[str, str | None] | None = None,
    command_runner: Any = run_command,
) -> dict[str, Any]:
    manifest = json.loads(Path(manifest_file).resolve(strict=True).read_text(encoding="utf-8"))
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    global_load_file = output / "global-load.json"
    global_routeability_file = output / "global-routeability.json"
    candidate = Path(str(manifest["candidate_net_file"])).resolve(strict=True)
    candidate_sha = file_sha256(candidate)
    if candidate_sha != manifest.get("candidate_sha256"):
        raise RuntimeError("candidate network hash changed before global gates")
    selected = dict(binaries or discover_binaries())
    if not selected.get("sumo") or not selected.get("duarouter"):
        report = {
            "status": "blocked",
            "candidate_sha256": candidate_sha,
            "reason": "sumo and duarouter binaries are required",
        }
        write_json_atomic(global_load_file, report, sort_keys=True)
        write_json_atomic(global_routeability_file, report, sort_keys=True)
        return {
            **report,
            "global_load_file": str(global_load_file),
            "global_routeability_file": str(global_routeability_file),
        }

    load_result = command_runner(
        [
            str(selected["sumo"]), "--net-file", str(candidate),
            "--begin", "0", "--end", "1", "--no-step-log", "true",
        ],
        cwd=output,
        timeout_seconds=300.0,
    )
    load_command = _command_result(load_result)
    load_status = "pass" if load_command.get("returncode") == 0 else "fail"
    load_report = {
        "schema": "torii.ingolstadt-citywide-global-load/v1",
        "status": load_status,
        "candidate_net_file": str(candidate),
        "candidate_sha256": candidate_sha,
        "command": load_command,
    }
    write_json_atomic(global_load_file, load_report, sort_keys=True)

    scope = tuple(float(value) for value in manifest["projected_scope"])
    inventory = read_network_inventory(
        candidate,
        tile_size_m=float(manifest["tile_size_m"]),
        scope_projected_boundary=scope,  # type: ignore[arg-type]
    )
    od_plan = build_stratified_od_plan(inventory, seed=20260802)
    trips_file = output / "global.trips.xml"
    trips_root = ET.Element("routes")
    ET.SubElement(trips_root, "vType", id="passenger", vClass="passenger")
    for index, row in enumerate(od_plan):
        ET.SubElement(
            trips_root,
            "trip",
            id=f"citywide_{index:06d}",
            type="passenger",
            depart=str(index),
            **{"from": row["from"], "to": row["to"]},
        )
    ET.indent(trips_root, space="  ")
    write_text_atomic(trips_file, ET.tostring(trips_root, encoding="unicode"), encoding="utf-8")
    route_file = output / "global.rou.xml"
    route_result = command_runner(
        [
            str(selected["duarouter"]), "--net-file", str(candidate),
            "--route-files", str(trips_file), "--output-file", str(route_file),
            "--ignore-errors", "false",
        ],
        cwd=output,
        timeout_seconds=1800.0,
    )
    route_command = _command_result(route_result)
    routed = 0
    if route_command.get("returncode") == 0 and route_file.is_file():
        routed = len(ET.parse(route_file).getroot().findall("vehicle"))

    summary_file = output / "global.summary.xml"
    tripinfo_file = output / "global.tripinfo.xml"
    if routed == len(od_plan):
        sumo_result = command_runner(
            [
                str(selected["sumo"]), "--net-file", str(candidate),
                "--route-files", str(route_file),
                "--summary-output", str(summary_file),
                "--tripinfo-output", str(tripinfo_file),
                "--collision.check-junctions", "true",
                "--no-step-log", "true",
            ],
            cwd=output,
            timeout_seconds=3600.0,
        )
        sumo_command = _command_result(sumo_result)
    else:
        sumo_command = {"status": "blocked", "returncode": None, "reason": "not every OD pair was routed"}
    inspection = (
        inspect_routeability_outputs(
            summary_path=summary_file,
            tripinfo_path=tripinfo_file,
            expected_vehicle_count=len(od_plan),
        )
        if sumo_command.get("returncode") == 0 and summary_file.is_file() and tripinfo_file.is_file()
        else {"status": "fail", "summary": {}, "tripinfo": {}}
    )
    summary = inspection.get("summary", {})
    global_result = summarize_global_run(
        requested=len(od_plan),
        routed=routed,
        arrived=int(summary.get("arrived") or 0),
        teleports=int(summary.get("teleports") or 0),
        collisions=int(summary.get("collisions") or 0),
        returncode=int(sumo_command.get("returncode") or 0) if sumo_command.get("returncode") is not None else -1,
    )
    status = "pass" if load_status == "pass" and inspection.get("status") == "pass" and global_result["status"] == "pass" else "fail"
    routeability_report = {
        "schema": "torii.ingolstadt-citywide-global-routeability/v1",
        "status": status,
        "candidate_net_file": str(candidate),
        "candidate_sha256": candidate_sha,
        "seed": 20260802,
        "od_plan": od_plan,
        "trip_file": str(trips_file),
        "trip_sha256": file_sha256(trips_file),
        "route_file": str(route_file) if route_file.is_file() else "",
        "route_sha256": file_sha256(route_file) if route_file.is_file() else "",
        "duarouter_command": route_command,
        "sumo_command": sumo_command,
        "inspection": inspection,
        "result": global_result,
    }
    write_json_atomic(global_routeability_file, routeability_report, sort_keys=True)
    return {
        **routeability_report,
        "global_load_status": load_status,
        "global_load_file": str(global_load_file),
        "global_routeability_file": str(global_routeability_file),
    }


def build_completion_report(
    *,
    manifest: Mapping[str, Any],
    visual: Mapping[str, Any],
    global_report: Mapping[str, Any],
) -> dict[str, Any]:
    candidate_sha = str(manifest["candidate_sha256"])
    if visual.get("candidate_sha256") != candidate_sha or global_report.get("candidate_sha256") != candidate_sha:
        raise ValueError("completion inputs do not bind the same candidate SHA-256")
    lane_reports = list(visual.get("lane_reports", {}).values())
    lane_statuses = [str(report.get("status", "blocked")) for report in lane_reports]
    expected_lanes = int(manifest.get("incoming_lane_count", len(lane_reports)))
    if len(lane_reports) != expected_lanes:
        lane_statuses.append("missing")
    structure_statuses = [
        str(report.get("structure", {}).get("status", "blocked")) for report in lane_reports
    ]
    completion = city_completion(
        teacher_count=int(manifest["teacher_applicable_junction_count"]),
        candidate_count=int(manifest["candidate_applicable_junction_count"]),
        matched_count=int(manifest["matched_junction_count"]),
        teacher_only=manifest.get("teacher_only", ()),
        candidate_only=manifest.get("candidate_only", ()),
        ambiguous=manifest.get("ambiguous", ()),
        lane_statuses=lane_statuses,
        structure_statuses=structure_statuses,
        global_load=str(global_report.get("global_load_status", "blocked")),
        global_routeability=str(global_report.get("status", "blocked")),
    )
    return {
        **completion,
        "teacher_sha256": manifest.get("teacher_sha256", ""),
        "candidate_sha256": candidate_sha,
        "source_osm_sha256": manifest.get("source_osm_sha256", ""),
        "visual_lane_count": len(lane_reports),
        "expected_lane_count": expected_lanes,
    }


def _command_text(command: Sequence[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0 or not output:
        raise RuntimeError(f"command failed: {' '.join(command)}")
    return output.splitlines()[0]


def _provenance() -> tuple[str, str, str]:
    return (
        _command_text(("git", "rev-parse", "HEAD")),
        _command_text(("sumo", "--version")),
        _command_text(("netedit", "--version")),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    inventory_func: Any = run_inventory_phase,
    visual_func: Any = run_visual_phase,
    global_func: Any = run_global_phase,
    provenance_func: Any = _provenance,
) -> int:
    args = build_parser().parse_args(argv)
    if args.max_tile_distance is not None and args.max_tile_distance < 0:
        raise ValueError("max-tile-distance must be non-negative")
    if args.phase == "all":
        git_commit, sumo_version, netedit_version = provenance_func()
        inventory = inventory_func(
            teacher_net=args.teacher_net,
            candidate_net=args.candidate_net,
            source_osm=args.source_osm,
            output_dir=args.output_dir,
            tile_size_m=args.tile_size_m,
            junction_distance_m=args.junction_distance_m,
            git_commit=git_commit,
            sumo_version=sumo_version,
            netedit_version=netedit_version,
        )
        if inventory["status"] != "ready":
            print(json.dumps(_inventory_cli_summary(inventory), ensure_ascii=False, indent=2))
            return 3
        window_size = tuple(int(value) for value in args.window_size.split(","))
        if len(window_size) != 2 or min(window_size) <= 0:
            raise ValueError("window-size must be WIDTH,HEIGHT with positive integers")
        visual = visual_func(
            manifest_file=args.output_dir / "city-manifest.json",
            output_dir=args.output_dir,
            seed_junction=args.seed_junction,
            zoom=args.zoom,
            window_size=window_size,
            resume=args.resume,
            max_tile_distance=args.max_tile_distance,
        )
        if visual["status"] != "pass" or visual.get("coverage_status") != "complete":
            print(json.dumps(visual, ensure_ascii=False, indent=2))
            return 3 if visual["status"] == "blocked" else 2
        global_report = global_func(
            manifest_file=args.output_dir / "city-manifest.json",
            output_dir=args.output_dir,
        )
        completion = build_completion_report(
            manifest=inventory,
            visual=visual,
            global_report=global_report,
        )
        completion_file = args.output_dir / "completion.json"
        write_json_atomic(completion_file, completion, sort_keys=True)
        print(json.dumps({**completion, "completion_file": str(completion_file)}, ensure_ascii=False, indent=2))
        return 0 if completion["status"] == "pass" else 3 if global_report["status"] == "blocked" else 2
    if args.phase == "visual":
        window_size = tuple(int(value) for value in args.window_size.split(","))
        if len(window_size) != 2 or min(window_size) <= 0:
            raise ValueError("window-size must be WIDTH,HEIGHT with positive integers")
        report = visual_func(
            manifest_file=args.output_dir / "city-manifest.json",
            output_dir=args.output_dir,
            seed_junction=args.seed_junction,
            zoom=args.zoom,
            window_size=window_size,
            resume=args.resume,
            max_tile_distance=args.max_tile_distance,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 3 if report["status"] == "blocked" else 2
    if args.phase == "global":
        manifest_file = args.output_dir / "city-manifest.json"
        visual_file = args.output_dir / "visual-summary.json"
        if not manifest_file.is_file() or not visual_file.is_file():
            report = {"status": "blocked", "reason": "inventory and visual phases must finish first"}
            print(json.dumps(report, ensure_ascii=False))
            return 3
        global_report = global_func(manifest_file=manifest_file, output_dir=args.output_dir)
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        visual = json.loads(visual_file.read_text(encoding="utf-8"))
        if visual.get("coverage_status") != "complete":
            report = {"status": "blocked", "reason": "full-city visual coverage must finish first"}
            print(json.dumps(report, ensure_ascii=False))
            return 3
        completion = build_completion_report(
            manifest=manifest,
            visual=visual,
            global_report=global_report,
        )
        completion_file = args.output_dir / "completion.json"
        write_json_atomic(completion_file, completion, sort_keys=True)
        report = {**completion, "completion_file": str(completion_file)}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if completion["status"] == "pass" else 3 if global_report["status"] == "blocked" else 2
    if args.phase != "inventory":
        report = {"status": "blocked", "reason": f"phase is not implemented yet: {args.phase}"}
        print(json.dumps(report, ensure_ascii=False))
        return 3
    git_commit, sumo_version, netedit_version = provenance_func()
    report = inventory_func(
        teacher_net=args.teacher_net,
        candidate_net=args.candidate_net,
        source_osm=args.source_osm,
        output_dir=args.output_dir,
        tile_size_m=args.tile_size_m,
        junction_distance_m=args.junction_distance_m,
        git_commit=git_commit,
        sumo_version=sumo_version,
        netedit_version=netedit_version,
    )
    print(json.dumps(_inventory_cli_summary(report), ensure_ascii=False, indent=2))
    return 2


def _inventory_cli_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    omitted = ("junction_pairs", "teacher_only", "candidate_only", "ambiguous", "registration_gaps")
    summary = {key: value for key, value in report.items() if key not in omitted}
    summary.update({f"{key}_count": len(report[key]) for key in omitted if key in report})
    return summary


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


def build_visual_tile_subnet(
    *,
    source_net: Path,
    projected_boundary: tuple[float, float, float, float],
    output_dir: Path,
    requested_junctions: Sequence[str],
    requested_lanes: Sequence[str],
    command_runner: Any = run_command,
) -> dict[str, Any]:
    source = Path(source_net).resolve(strict=True)
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    subnet = destination / "render.net.xml"
    offset, _ = _location_numbers(source)
    local_boundary = (
        projected_boundary[0] + offset[0],
        projected_boundary[1] + offset[1],
        projected_boundary[2] + offset[0],
        projected_boundary[3] + offset[1],
    )
    boundary_text = ",".join(f"{value:.3f}" for value in local_boundary)
    base_command = [
        "netconvert",
        "--sumo-net-file",
        str(source),
        "--keep-edges.in-boundary",
        boundary_text,
    ]
    commands = [
        [*base_command, "--keep-edges.postload", "--output-file", str(subnet)],
        [*base_command, "--output-file", str(subnet)],
    ]
    attempts = []
    result = command_runner(commands[0], cwd=destination, timeout_seconds=300.0)
    attempts.append(result.to_dict())
    if result.status != "pass":
        result = command_runner(commands[1], cwd=destination, timeout_seconds=300.0)
        attempts.append(result.to_dict())
    write_text_atomic(
        destination / "netconvert.cmd.txt",
        "\n".join(subprocess.list2cmdline(attempt["command"]) for attempt in attempts) + "\n",
    )

    junctions: set[str] = set()
    lanes: set[str] = set()
    if result.status == "pass" and subnet.is_file():
        root = ET.parse(subnet).getroot()
        junctions = {str(item.get("id")) for item in root.findall("junction") if item.get("id")}
        lanes = {str(item.get("id")) for item in root.iter("lane") if item.get("id")}
    requested_junction_set = set(map(str, requested_junctions))
    requested_lane_set = set(map(str, requested_lanes))
    verified_junctions = sorted(requested_junction_set & junctions)
    verified_lanes = sorted(requested_lane_set & lanes)
    missing_junctions = sorted(requested_junction_set - junctions)
    missing_lanes = sorted(requested_lane_set - lanes)
    status = "pass" if result.status == "pass" and not missing_junctions and not missing_lanes else "fail"
    return {
        "status": status,
        "source_net_file": str(source),
        "source_sha256": file_sha256(source),
        "projected_boundary": list(projected_boundary),
        "local_boundary": list(local_boundary),
        "subnet_file": str(subnet),
        "subnet_sha256": file_sha256(subnet) if subnet.is_file() else "",
        "command_attempts": attempts,
        "requested_junctions": sorted(requested_junction_set),
        "requested_lanes": sorted(requested_lane_set),
        "verified_junctions": verified_junctions,
        "verified_lanes": verified_lanes,
        "missing_requested_junctions": missing_junctions,
        "missing_requested_lanes": missing_lanes,
    }


def _junction_render_semantic_signature(root: ET.Element, junction_id: str) -> tuple[Any, ...]:
    prefix = f":{junction_id}_"
    junction = root.find(f"junction[@id='{junction_id}']")
    logic = root.find(f"tlLogic[@id='{junction_id}']")
    internal_edges = tuple(sorted(
        (
            str(edge.get("id")),
            str(edge.get("function")),
            tuple((str(lane.get("id")), str(lane.get("index"))) for lane in edge.findall("lane")),
        )
        for edge in root.findall("edge")
        if str(edge.get("id", "")).startswith(prefix)
    ))
    requests = tuple(
        tuple(sorted(request.attrib.items()))
        for request in (() if junction is None else junction.findall("request"))
    )
    phases = tuple(
        (str(phase.get("duration")), str(phase.get("state")))
        for phase in (() if logic is None else logic.findall("phase"))
    )
    connections = tuple(sorted(
        tuple(sorted(connection.attrib.items()))
        for connection in root.findall("connection")
        if connection.get("tl") == junction_id
        or any(str(connection.get(field, "")).startswith(prefix) for field in ("from", "to", "via"))
    ))
    junction_semantics = None if junction is None else (
        junction.get("type"), junction.get("incLanes"), junction.get("intLanes"), requests
    )
    return junction_semantics, phases, internal_edges, connections


def junction_render_semantic_mismatches(
    source_root: ET.Element,
    rendered_root: ET.Element,
    junction_ids: Sequence[str],
) -> list[str]:
    return [
        junction_id
        for junction_id in junction_ids
        if _junction_render_semantic_signature(source_root, junction_id)
        != _junction_render_semantic_signature(rendered_root, junction_id)
    ]


def visual_tile_projected_boundary(
    *,
    teacher_net: Path,
    candidate_net: Path,
    records: Sequence[Mapping[str, Any]],
    tile_boundary: tuple[float, float, float, float],
    buffer_m: float = 30.0,
) -> tuple[float, float, float, float]:
    if buffer_m < 0:
        raise ValueError("buffer_m must be non-negative")
    points = [(tile_boundary[0], tile_boundary[1]), (tile_boundary[2], tile_boundary[3])]
    for role, net_file in (("teacher", teacher_net), ("candidate", candidate_net)):
        lane_ids = {str(record[f"{role}_lane"]) for record in records}
        for record in records:
            pairs = record.get("outgoing_lane_pairs", {})
            lane_ids.update(map(str, pairs.keys() if role == "teacher" else pairs.values()))
        offset, _ = _location_numbers(Path(net_file))
        lanes = {
            str(lane.get("id")): lane
            for lane in ET.parse(net_file).getroot().iter("lane")
            if lane.get("id")
        }
        missing = sorted(lane_ids - lanes.keys())
        if missing:
            raise ValueError(f"registered {role} lanes are absent: {', '.join(missing)}")
        for lane_id in lane_ids:
            for value in lanes[lane_id].get("shape", "").split():
                x, y = (float(number) for number in value.split(",")[:2])
                points.append((x - offset[0], y - offset[1]))
    return (
        min(point[0] for point in points) - buffer_m,
        min(point[1] for point in points) - buffer_m,
        max(point[0] for point in points) + buffer_m,
        max(point[1] for point in points) + buffer_m,
    )


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
        outgoing_lanes = sorted({
            lane_id
            for edge_id in incoming_edges
            for lane_id in outgoing.get(edge_id, ())
            if lane_allows_motor(lanes[lane_id])
        })
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
                            "junction_id": junction_id,
                            "edge_id": lane_edges[lane_id],
                            "road_root": road_root(lane_edges[lane_id]),
                            "bearing": _lane_bearing(lanes[lane_id]),
                        }
                        for lane_id in incoming
                    ),
                    key=lambda row: row["id"],
                ),
                "motor_outgoing_lane_details": sorted(
                    (
                        {
                            "id": lane_id,
                            "junction_id": junction_id,
                            "edge_id": lane_edges[lane_id],
                            "road_root": road_root(lane_edges[lane_id]),
                            "bearing": _lane_bearing(lanes[lane_id]),
                        }
                        for lane_id in outgoing_lanes
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


if __name__ == "__main__":
    raise SystemExit(main())

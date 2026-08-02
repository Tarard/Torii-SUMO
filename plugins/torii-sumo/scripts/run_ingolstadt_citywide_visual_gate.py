from __future__ import annotations

import argparse
import collections
import json
import math
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

from torii_sumo.core.artifact_io import write_json_atomic
from torii_sumo.core.candidate_contracts import file_sha256


OFFICIAL_TEACHER_SHA256 = "bbfef2f8afb66f29486395189fa7136e3fa7cce2b192afcbd50a6f1d9239a806"
OFFICIAL_CONV_BOUNDARY = (1243.52, 0.0, 11284.52, 10137.01)


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


def write_tile_state(path: Path, *, candidate_sha: str, completed: Sequence[str]) -> None:
    write_json_atomic(
        path,
        {
            "schema": "torii.ingolstadt-citywide-tile/v1",
            "candidate_sha256": candidate_sha,
            "completed": sorted(set(completed)),
        },
        sort_keys=True,
    )


def pending_items(path: Path, *, candidate_sha: str, items: Sequence[str]) -> list[str]:
    if not path.is_file():
        return list(items)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("candidate_sha256") != candidate_sha:
        return list(items)
    completed = set(map(str, state.get("completed", ())))
    return [item for item in items if item not in completed]


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


def _connection_signature(path: Path, lane_id: str) -> list[dict[str, Any]]:
    root = ET.parse(path).getroot()
    lanes: dict[str, tuple[str, str, ET.Element]] = {}
    by_edge_index: dict[tuple[str, str], tuple[str, ET.Element]] = {}
    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")
        for lane in edge.findall("lane"):
            current_id, index = lane.get("id", ""), lane.get("index", "")
            if current_id:
                lanes[current_id] = edge_id, index, lane
                by_edge_index[(edge_id, index)] = current_id, lane
    if lane_id not in lanes:
        raise ValueError(f"lane is missing from network: {lane_id}")
    edge_id, lane_index, _lane = lanes[lane_id]
    rows = []
    for connection in root.findall("connection"):
        if connection.get("from") != edge_id or connection.get("fromLane") != lane_index:
            continue
        target = by_edge_index.get((connection.get("to", ""), connection.get("toLane", "")))
        if target is None:
            target_lane, motor = "", False
        else:
            target_lane, target_element = target
            motor = lane_allows_motor(target_element)
        link_index = connection.get("linkIndex", "")
        rows.append({
            "target_lane": target_lane,
            "dir": connection.get("dir", ""),
            "has_via": bool(connection.get("via")),
            "motor": motor,
            "has_tls": bool(connection.get("tl")),
            "has_link_index": link_index.isdigit(),
            "link_index": int(link_index) if link_index.isdigit() else None,
        })
    return sorted(rows, key=lambda row: (row["target_lane"], row["dir"]))


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
    expected_targets = {
        outgoing_lane_pairs[target]
        for target in teacher_by_target
        if target in outgoing_lane_pairs
    }
    reasons = []
    if len(expected_targets) != len(teacher_by_target) or expected_targets != set(candidate_by_target):
        reasons.append("target_lane_mismatch")
    if sorted((row["has_tls"], row["has_link_index"]) for row in teacher) != sorted(
        (row["has_tls"], row["has_link_index"]) for row in candidate
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
        if row["link_index"] is not None
    ]
    if teacher_order != candidate_order:
        reasons.append("signal_order_mismatch")
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
        pairs.append({
            "teacher_id": registered["teacher_id"],
            "candidate_ids": registered["candidate_ids"],
            "tile_id": teacher["tile_id"],
            "projected_center": teacher["projected_center"],
            "status": "blocked" if lane_blocked else "ready",
            "incoming_lane_pairs": [
                [row["teacher_lane"], row["candidate_lane"]] for row in incoming["matched"]
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
    return {
        "schema": "torii.ingolstadt-citywide-manifest/v1",
        "status": status,
        "teacher_applicable_junction_count": teacher_inventory["applicable_junction_count"],
        "candidate_applicable_junction_count": candidate_inventory["applicable_junction_count"],
        "matched_junction_count": len(pairs),
        "teacher_only": registration["teacher_only"],
        "candidate_only": registration["candidate_only"],
        "ambiguous": registration["ambiguous"],
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
    provenance_func: Any = _provenance,
) -> int:
    args = build_parser().parse_args(argv)
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
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


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
                "motor_outgoing_lane_details": sorted(
                    (
                        {
                            "id": lane_id,
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

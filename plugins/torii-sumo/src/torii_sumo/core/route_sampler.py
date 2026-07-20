from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Collection, Mapping

import sumolib

from .command_runner import CommandResult, run_command
from .hamburg_official import sha256_file


CommandRunner = Callable[..., CommandResult]


def write_candidate_routes(candidate_manifest_csv: Path, output_file: Path) -> int:
    with candidate_manifest_csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    root = ET.Element("routes")
    seen_ids: set[str] = set()
    count = 0
    for row in rows:
        route_id = str(row.get("route_id", "")).strip()
        edges = " ".join(str(row.get("edges", "")).split())
        if not route_id or not edges:
            continue
        if route_id in seen_ids:
            raise ValueError(f"duplicate candidate route id: {route_id}")
        seen_ids.add(route_id)
        ET.SubElement(root, "route", id=route_id, edges=edges)
        count += 1
    if count == 0:
        raise ValueError("candidate route manifest contains no usable routes")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return count


def route_source_edges(demand_route_file: Path) -> set[str]:
    """Return the first edge of every vehicle route in a routeSampler output."""

    root = ET.parse(Path(demand_route_file).resolve(strict=True)).getroot()
    source_edges: set[str] = set()
    for vehicle in root.findall("vehicle"):
        route = vehicle.find("route")
        edges = "" if route is None else str(route.attrib.get("edges", "")).strip()
        if edges:
            source_edges.add(edges.split()[0])
    return source_edges


def apply_departure_lane_targets(
    demand_route_file: Path,
    lane_targets: Mapping[tuple[str, int], Mapping[str, int]],
    *,
    interval: int,
    source_edges: Collection[str] | None = None,
    lane_positions: Mapping[tuple[str, str], float] | None = None,
    depart_offset_m: float = 1.0,
    output_file: Path | None = None,
) -> dict[str, object]:
    """Assign deterministic SUMO departure lanes from official lane counts.

    ``routeSampler`` constrains edge totals and intentionally does not solve the
    lane split.  A local detector-cross-section replay has stronger evidence:
    each source edge is measured lane by lane.  When the generated vehicles in
    an edge/bin equal that lane total, this function writes ``departLane`` in a
    stable lane-count order.  Optional detector positions place vehicles just
    upstream of the measured cut, which is the correct boundary semantics for
    a local cross-section twin.  A routeSampler vehicle is counted only at its
    first edge, so an internal detector edge cannot be satisfied by assigning
    departure lanes.  Callers may pass ``source_edges`` to control only those
    boundary edges; skipped internal bins are reported as ``review_required``
    rather than being mistaken for a lane-balance failure.
    """

    if interval <= 0:
        raise ValueError("interval must be positive")
    if not math.isfinite(depart_offset_m) or depart_offset_m < 0:
        raise ValueError("depart_offset_m must be finite and non-negative")
    source = Path(demand_route_file).resolve(strict=True)
    destination = Path(output_file).resolve() if output_file is not None else source
    root = ET.parse(source).getroot()
    allowed_source_edges = None if source_edges is None else {str(edge) for edge in source_edges}
    vehicles_by_bin: dict[tuple[str, int], list[ET.Element]] = {}
    unsupported_vehicle_count = 0
    for vehicle in root.findall("vehicle"):
        route = vehicle.find("route")
        depart_text = vehicle.attrib.get("depart")
        if route is None or not route.attrib.get("edges") or depart_text is None:
            unsupported_vehicle_count += 1
            continue
        first_edge = route.attrib["edges"].split()[0]
        depart = float(depart_text)
        begin = math.floor(depart / interval) * interval
        vehicles_by_bin.setdefault((first_edge, begin), []).append(vehicle)

    changed = 0
    assigned = 0
    target_total = 0
    all_target_total = 0
    mismatches: list[dict[str, object]] = []
    unresolved_lanes: list[dict[str, object]] = []
    unresolved_positions: list[dict[str, object]] = []
    skipped_non_source_bins: list[dict[str, object]] = []
    positioned = 0
    for key, targets in sorted(lane_targets.items()):
        edge_id, begin = key
        if any(int(count) < 0 for count in targets.values()):
            raise ValueError(f"lane target counts must be non-negative for {key!r}")
        lane_counts = {str(lane): int(count) for lane, count in targets.items() if int(count) > 0}
        target_count = sum(lane_counts.values())
        all_target_total += target_count
        if allowed_source_edges is not None and edge_id not in allowed_source_edges:
            skipped_non_source_bins.append(
                {
                    "edge_id": edge_id,
                    "begin": begin,
                    "target_count": target_count,
                    "reason": "detector edge is internal to generated route; departure lanes apply only to first edge",
                }
            )
            continue
        target_total += target_count
        vehicles = vehicles_by_bin.get(key, [])
        if len(vehicles) != target_count:
            mismatches.append(
                {
                    "edge_id": edge_id,
                    "begin": begin,
                    "target_count": target_count,
                    "vehicle_count": len(vehicles),
                }
            )
            continue
        lane_queue: list[str] = []
        for lane_id, count in sorted(lane_counts.items()):
            match = re.search(r"_(\d+)$", lane_id)
            if match is None:
                unresolved_lanes.append({"edge_id": edge_id, "begin": begin, "lane_id": lane_id})
                lane_queue = []
                break
            lane_queue.extend([match.group(1)] * count)
        if not lane_queue:
            continue
        for vehicle, lane_index in zip(vehicles, lane_queue, strict=True):
            if vehicle.attrib.get("departLane") != lane_index:
                vehicle.set("departLane", lane_index)
                changed += 1
            lane_id = next(
                lane_id
                for lane_id in lane_counts
                if lane_id.rsplit("_", 1)[-1] == lane_index
            )
            if lane_positions is not None:
                position = lane_positions.get((edge_id, lane_id))
                if position is None or not math.isfinite(float(position)):
                    unresolved_positions.append(
                        {"edge_id": edge_id, "begin": begin, "lane_id": lane_id}
                    )
                else:
                    vehicle.set("departPos", f"{max(0.1, float(position) - depart_offset_m):g}")
                    positioned += 1
            assigned += 1

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.lane-balance.tmp")
    ET.indent(root, space="    ")
    ET.ElementTree(root).write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(destination)
    hard_failure = bool(unresolved_lanes or unresolved_positions or unsupported_vehicle_count)
    review_required = bool(skipped_non_source_bins or (allowed_source_edges is not None and mismatches))
    return {
        "status": "fail" if hard_failure else "review_required" if review_required else "pass",
        "interval": interval,
        "target_bin_count": len(lane_targets),
        "controlled_target_bin_count": len(lane_targets) - len(skipped_non_source_bins),
        "skipped_non_source_bin_count": len(skipped_non_source_bins),
        "skipped_non_source_edges": sorted({str(item["edge_id"]) for item in skipped_non_source_bins}),
        "vehicle_bin_count": len(vehicles_by_bin),
        "target_vehicle_count": all_target_total,
        "controlled_target_vehicle_count": target_total,
        "skipped_non_source_target_vehicle_count": all_target_total - target_total,
        "assigned_vehicle_count": assigned,
        "changed_vehicle_count": changed,
        "positioned_vehicle_count": positioned,
        "depart_offset_m": depart_offset_m,
        "unmatched_bins": mismatches,
        "unresolved_lanes": unresolved_lanes,
        "unresolved_positions": unresolved_positions,
        "skipped_non_source_bins": skipped_non_source_bins,
        "unsupported_vehicle_count": unsupported_vehicle_count,
        "demand_route_file": str(destination),
    }


def validate_route_sampler_edge_counts(
    edge_data_file: Path,
    *,
    begin: int,
    end: int,
    interval: int,
) -> dict[str, int]:
    root = ET.parse(edge_data_file).getroot()
    intervals = root.findall("interval")
    expected = list(range(begin, end, interval))
    actual: list[int] = []
    edge_rows = 0
    total_count = 0
    for interval_element in intervals:
        row_begin = int(float(interval_element.attrib.get("begin", "nan")))
        row_end = int(float(interval_element.attrib.get("end", "nan")))
        if row_end - row_begin != interval:
            raise ValueError(f"edge count interval {row_begin}-{row_end} does not have width {interval}")
        actual.append(row_begin)
        for edge in interval_element.findall("edge"):
            if "count" not in edge.attrib:
                raise ValueError("routeSampler edge data must use the standard 'count' attribute")
            count = int(float(edge.attrib["count"]))
            if count < 0:
                raise ValueError("routeSampler edge count must be non-negative")
            total_count += count
            edge_rows += 1
    if actual != expected:
        raise ValueError(f"edge count bins do not exactly cover {begin}-{end}: {actual}")
    if edge_rows == 0:
        raise ValueError("edge count file has no edge rows")
    return {"interval_count": len(intervals), "edge_row_count": edge_rows, "total_count": total_count}


def audit_route_constraint_structure(
    candidate_manifest_csv: Path,
    edge_data_file: Path,
    *,
    begin: int,
    end: int,
    interval: int,
    max_conflicts: int = 100,
) -> dict[str, object]:
    """Check necessary flow constraints before invoking SUMO routeSampler.

    Candidate routes are non-negative route variables.  Therefore, if two
    measured edges have the same candidate-route incidence, their observed
    counts must be equal; if the candidate routes that can use edge A are a
    subset of those for edge B, A cannot have a larger count than B.  These
    are cheap, deterministic necessary conditions.  They do not replace
    routeSampler's optimization, but they expose a malformed or under-scoped
    corridor immediately and preserve the exact conflicting interval/edges.
    """

    if max_conflicts <= 0:
        raise ValueError("max_conflicts must be positive")
    with candidate_manifest_csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    route_ids_by_edge: dict[str, set[str]] = {}
    route_count = 0
    for row in rows:
        route_id = str(row.get("route_id", "")).strip()
        edges = tuple(str(row.get("edges", "")).split())
        if not route_id or not edges:
            continue
        route_count += 1
        for edge_id in set(edges):
            route_ids_by_edge.setdefault(edge_id, set()).add(route_id)

    root = ET.parse(edge_data_file).getroot()
    expected_bins = list(range(begin, end, interval))
    conflicts: list[dict[str, object]] = []
    checked_intervals = 0
    for interval_element in root.findall("interval"):
        row_begin = int(float(interval_element.attrib.get("begin", "nan")))
        if row_begin not in expected_bins:
            continue
        checked_intervals += 1
        values = {
            str(edge.attrib.get("id", "")).strip(): int(float(edge.attrib.get("count", "nan")))
            for edge in interval_element.findall("edge")
        }
        constrained_edges = sorted(values)
        for edge_id in constrained_edges:
            if values[edge_id] > 0 and not route_ids_by_edge.get(edge_id):
                _append_constraint_conflict(
                    conflicts,
                    max_conflicts,
                    {
                        "kind": "positive_count_without_candidate_route",
                        "interval_begin": row_begin,
                        "edge": edge_id,
                        "count": values[edge_id],
                    },
                )
        for index, edge_a in enumerate(constrained_edges):
            incidence_a = route_ids_by_edge.get(edge_a, set())
            if not incidence_a:
                continue
            for edge_b in constrained_edges[index + 1 :]:
                incidence_b = route_ids_by_edge.get(edge_b, set())
                if not incidence_b:
                    continue
                if incidence_a == incidence_b and values[edge_a] != values[edge_b]:
                    _append_constraint_conflict(
                        conflicts,
                        max_conflicts,
                        {
                            "kind": "identical_route_incidence_count_conflict",
                            "interval_begin": row_begin,
                            "edge_a": edge_a,
                            "edge_b": edge_b,
                            "count_a": values[edge_a],
                            "count_b": values[edge_b],
                            "candidate_route_count": len(incidence_a),
                        },
                    )
                elif incidence_a < incidence_b and values[edge_a] > values[edge_b]:
                    _append_constraint_conflict(
                        conflicts,
                        max_conflicts,
                        {
                            "kind": "subset_route_incidence_count_conflict",
                            "interval_begin": row_begin,
                            "edge_a": edge_a,
                            "edge_b": edge_b,
                            "count_a": values[edge_a],
                            "count_b": values[edge_b],
                            "candidate_route_count_a": len(incidence_a),
                            "candidate_route_count_b": len(incidence_b),
                        },
                    )
                elif incidence_b < incidence_a and values[edge_b] > values[edge_a]:
                    _append_constraint_conflict(
                        conflicts,
                        max_conflicts,
                        {
                            "kind": "subset_route_incidence_count_conflict",
                            "interval_begin": row_begin,
                            "edge_a": edge_b,
                            "edge_b": edge_a,
                            "count_a": values[edge_b],
                            "count_b": values[edge_a],
                            "candidate_route_count_a": len(incidence_b),
                            "candidate_route_count_b": len(incidence_a),
                        },
                    )
    return {
        "status": "pass" if not conflicts else "fail",
        "claim_status": (
            "route-constraint-structure-consistent"
            if not conflicts
            else "construction-inconsistent"
        ),
        "candidate_route_count": route_count,
        "constrained_edge_count": len(route_ids_by_edge),
        "interval_count_checked": checked_intervals,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "claim_boundary": (
            "Necessary route-incidence conditions only; a pass does not prove that routeSampler will find a full "
            "demand solution or that the route set is a uniquely identified OD matrix."
        ),
    }


def _append_constraint_conflict(
    conflicts: list[dict[str, object]],
    max_conflicts: int,
    conflict: dict[str, object],
) -> None:
    if len(conflicts) < max_conflicts:
        conflicts.append(conflict)


def resolve_route_sampler_script(explicit: Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        candidates.append(Path(sumo_home) / "tools" / "routeSampler.py")
    which = shutil.which("routeSampler.py")
    if which:
        candidates.append(Path(which))
    candidates.append(Path(sumolib.__file__).resolve().parent.parent / "routeSampler.py")
    return next((path.resolve() for path in candidates if path.is_file()), None)


def run_route_sampler(
    *,
    candidate_manifest_csv: Path,
    edge_data_file: Path,
    output_dir: Path,
    prefix: str,
    begin: int = 0,
    end: int = 7200,
    interval: int = 900,
    seed: int = 42,
    optimize: str | None = None,
    route_sampler_script: Path | None = None,
    timeout_seconds: float = 300.0,
    command_runner: CommandRunner = run_command,
) -> dict[str, object]:
    if end <= begin or interval <= 0 or (end - begin) % interval:
        raise ValueError("routeSampler window must be a positive whole number of intervals")
    if optimize is not None:
        optimize = optimize.strip()
        if optimize != "full" and (not optimize.isdigit() or int(optimize) <= 0):
            raise ValueError("routeSampler optimize must be 'full' or a positive integer boundary")
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_routes = output_dir / f"{prefix}_candidate_routes.rou.xml"
    demand_file = output_dir / f"{prefix}_demand.rou.xml"
    mismatch_file = output_dir / f"{prefix}_route_sampler_mismatch.xml"
    command_file = output_dir / f"{prefix}_route_sampler_command.json"
    route_count = write_candidate_routes(candidate_manifest_csv, candidate_routes)
    edge_stats = validate_route_sampler_edge_counts(edge_data_file, begin=begin, end=end, interval=interval)
    constraint_structure = audit_route_constraint_structure(
        candidate_manifest_csv,
        edge_data_file,
        begin=begin,
        end=end,
        interval=interval,
    )
    script = resolve_route_sampler_script(route_sampler_script)
    if script is None:
        report = {
            "status": "blocked",
            "claim_status": "construction-incomplete",
            "reason": "routeSampler.py was not found; pass route_sampler_script or configure SUMO_HOME",
            "candidate_route_file": str(candidate_routes),
            "candidate_route_count": route_count,
            "edge_data_file": str(edge_data_file),
            "constraint_structure": constraint_structure,
            **edge_stats,
        }
        command_file.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report["command_manifest"] = str(command_file)
        return report

    command = [
        sys.executable,
        str(script),
        "-r",
        str(candidate_routes.resolve()),
        "--edgedata-files",
        str(edge_data_file.resolve()),
        "--edgedata-attribute",
        "count",
        "--begin",
        str(begin),
        "--end",
        str(end),
        "--interval",
        str(interval),
        "--seed",
        str(seed),
    ]
    if optimize:
        command.extend(["--optimize", optimize])
    command.extend(
        [
        "--mismatch-output",
        str(mismatch_file.resolve()),
        "-o",
        str(demand_file.resolve()),
        ]
    )
    command_result = command_runner(command, cwd=output_dir, timeout_seconds=timeout_seconds)
    result_dict = command_result.to_dict() if hasattr(command_result, "to_dict") else dict(command_result)
    manifest = {
        "tool": "Eclipse SUMO tools/routeSampler.py",
        "script": str(script),
        "script_sha256": sha256_file(script),
        "command": command,
        "command_result": result_dict,
        "inputs": {
            "candidate_manifest_csv": str(candidate_manifest_csv),
            "candidate_manifest_sha256": sha256_file(candidate_manifest_csv),
            "candidate_routes": str(candidate_routes),
            "candidate_routes_sha256": sha256_file(candidate_routes),
            "edge_data": str(edge_data_file),
            "edge_data_sha256": sha256_file(edge_data_file),
        },
        "constraint_structure": constraint_structure,
        "parameters": {
            "begin": begin,
            "end": end,
            "interval": interval,
            "seed": seed,
            "optimize": optimize,
        },
    }
    command_file.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result_dict.get("status") != "pass" or not demand_file.is_file():
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "reason": "routeSampler failed or did not create the demand route file",
            "command_manifest": str(command_file),
            "command_result": result_dict,
            "candidate_route_file": str(candidate_routes),
            "edge_data_file": str(edge_data_file),
            "constraint_structure": constraint_structure,
        }
    mismatch = parse_route_sampler_mismatch(mismatch_file) if mismatch_file.is_file() else {
        "row_count": 0,
        "absolute_deficit": None,
    }
    absolute_deficit = mismatch.get("absolute_deficit")
    mismatch_complete = absolute_deficit == 0
    total_count = int(edge_stats["total_count"])
    matched_fraction = (
        max(0.0, 1.0 - float(absolute_deficit) / total_count)
        if absolute_deficit is not None and total_count > 0
        else None
    )
    return {
        "status": "pass" if mismatch_complete else "partial",
        "claim_status": (
            "detector-constrained-plausible-demand" if mismatch_complete else "construction-incomplete"
        ),
        "candidate_route_count": route_count,
        "candidate_route_file": str(candidate_routes),
        "demand_route_file": str(demand_file),
        "demand_route_sha256": sha256_file(demand_file),
        "edge_data_file": str(edge_data_file),
        "mismatch_file": str(mismatch_file) if mismatch_file.is_file() else "",
        "mismatch": mismatch,
        "constraint_match_fraction": matched_fraction,
        "constraint_structure": constraint_structure,
        "command_manifest": str(command_file),
        **edge_stats,
    }


def parse_route_sampler_mismatch(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    row_count = 0
    absolute_deficit = 0.0
    overflow = 0.0
    for element in root.iter():
        if "deficit" not in element.attrib:
            continue
        deficit = float(element.attrib["deficit"])
        absolute_deficit += abs(deficit)
        overflow += max(0.0, -deficit)
        row_count += 1
    return {
        "row_count": row_count,
        "absolute_deficit": absolute_deficit,
        "overflow": overflow,
    }

from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

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
    script = resolve_route_sampler_script(route_sampler_script)
    if script is None:
        report = {
            "status": "blocked",
            "claim_status": "construction-incomplete",
            "reason": "routeSampler.py was not found; pass route_sampler_script or configure SUMO_HOME",
            "candidate_route_file": str(candidate_routes),
            "candidate_route_count": route_count,
            "edge_data_file": str(edge_data_file),
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

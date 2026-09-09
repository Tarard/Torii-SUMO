"""Combine Hamburg movement plans with a separate SUMO corridor candidate."""

from __future__ import annotations

import json
import math
import re
import shutil
from copy import deepcopy
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from pyproj import CRS, Transformer

from .candidate_contracts import file_sha256
from .command_runner import run_command
from .connection_mode_audit import audit_network_connection_mode, lane_supports_motorized
from .digital_twin import parse_mapem
from .hamburg_aerial_approach import build_hamburg_aerial_approach_candidate
from .hamburg_map_kml import parse_hamburg_map_kml
from .official_movement_composition import compose_official_movements
from .hamburg_official_intersection_plainxml import _angular_endpoint_polygon, _proper_segments_intersect, _clip_drive_line_to_lane_b_endpoints
from .routeability_audit import run_routeability_audit
from .source_movement_support import audit_source_movement_support, probe_source_interior_lane_changes, _modes as _lane_motorized_modes
from .topology_signal_rebuild import rebuild_topology_test_signals
from .surface_overlap_audit import audit_sumo_lane_junction_surface_overlaps, _lane_face_primitives

Point = tuple[float, float]
REQUEST_SCHEMA = "torii.hamburg-aerial-corridor-candidate-request/v1"
CANDIDATE_SCHEMA = "torii.hamburg-aerial-corridor-candidate/v1"


def build_hamburg_aerial_combined_candidate(
    *,
    request_file: Path | str,
    output_dir: Path | str,
) -> dict[str, Any]:
    """Build and test a corridor from the intersections declared in the plan."""
    request_path = Path(request_file).expanduser().resolve()
    request = _read_request(request_path)
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        raise ValueError("output_dir must not already exist")
    source_net = _verified_artifact(request["source_net"], "source_net")
    cluster_binding = _verified_artifact(
        request["cluster_binding"],
        "cluster_binding",
    )
    movement_summary = _verified_artifact(
        request["movement_summary"],
        "movement_summary",
    )
    binding = _load_json(cluster_binding, "cluster_binding")
    summary = _load_json(movement_summary, "movement_summary")
    if binding.get("schema") != "torii.hamburg-five-corridor-tls-cluster-binding/v1":
        raise ValueError("cluster binding schema is invalid")
    if binding.get("status") != "pass":
        raise ValueError("a passing cluster binding is required before network construction")
    if summary.get("schema") != "torii.hamburg-aerial-corridor-plan/v1":
        raise ValueError("movement summary schema is invalid")
    if str(binding.get("inputs", {}).get("network", {}).get("sha256", "")).lower() != file_sha256(source_net):
        raise ValueError("cluster binding does not match source_net")
    plans = _load_movement_plans(summary, base_dir=movement_summary.parent)
    source_root = ET.parse(source_net).getroot()
    plans = {node_id: _project_plan_to_network(plan, source_root) for node_id, plan in plans.items()}
    groups = _select_join_groups(source_root, binding, plans,
        maximum_lane_projection_error_m=float(request["maximum_lane_projection_error_m"]),
        minimum_lane_match_margin_m=float(request["minimum_lane_match_margin_m"]))
    destination.mkdir(parents=True)
    context = _prepare_context_joins(
        source_net=source_net, context_groups=request["context_joins"], official_groups=groups,
        output_dir=destination / "context-joins",
        adjacent_geometry_junction_ids=request["context_geometry_neighbors"],
        netconvert_binary=str(request.get("netconvert_binary", "netconvert")),
        sumo_binary=str(request.get("sumo_binary", "sumo")),
        timeout_seconds=float(request["timeout_seconds"]), seed=int(request["seed"]),
    ) if request["context_joins"] else None
    construction_net = Path(context["candidate_network"]["path"]) if context else source_net
    join_file = destination / "physical-part-joins.nod.xml"
    _write_join_file(join_file, groups)
    joined_auto = destination / "joined-auto.net.xml"
    joined_net = destination / "joined-base.net.xml"
    joined_output = destination / "joined-output.nod.xml"
    netconvert = run_command(
        [
            str(request.get("netconvert_binary", "netconvert")),
            "--sumo-net-file",
            str(construction_net),
            "--node-files",
            str(join_file),
            "--output-file",
            str(joined_auto),
            "--junctions.join-output",
            str(joined_output),
            "--seed",
            str(int(request["seed"])),
            "--offset.disable-normalization",
            "true",
        ],
        cwd=destination,
        timeout_seconds=float(request["timeout_seconds"]),
    )
    (destination / "netconvert.log").write_text(
        netconvert.stdout + netconvert.stderr,
        encoding="utf-8",
    )
    if netconvert.returncode != 0 or not joined_auto.is_file():
        raise ValueError("netconvert could not build the physical-part candidate")
    boundary_rebuild = _rebuild_join_boundaries(
        joined_auto, joined_net, groups,
        netconvert_binary=str(request.get("netconvert_binary", "netconvert")),
        timeout_seconds=float(request["timeout_seconds"]),
    )
    approach_rebuild = build_hamburg_aerial_approach_candidate(
        source_net=joined_net,
        plans=plans,
        junction_bindings={(str(row["node_id"]), str(row["intersection_part"])): str(row["join_id"]) for row in groups},
        output_dir=destination / "approach-sections",
        netconvert_binary=str(request.get("netconvert_binary", "netconvert")),
        timeout_seconds=float(request["timeout_seconds"]),
        maximum_lane_error_m=float(request["maximum_lane_projection_error_m"]),
        minimum_match_margin_m=float(request["minimum_lane_match_margin_m"]),
    )
    if approach_rebuild["status"] == "blocked":
        raise ValueError("official approach reconstruction failed its preservation or connection checks")
    movement_base = (
        Path(approach_rebuild["candidate_network"]["path"])
        if approach_rebuild.get("candidate_network") else joined_net
    )
    constructed_ingress, lane_origins, changed_edge_ids = _approach_lane_identities(source_root, approach_rebuild, groups)

    skipped_join_ids: set[str] = set()
    attempts = []
    selected_candidate = None
    selected_materialization = None
    routeability = None
    signal_rebuilds = []
    source_lane_change_evidence = []
    frozen_probe_trips = None
    frozen_probe_sha256 = None
    for attempt_index in range(3):
        candidate = destination / f"candidate-attempt-{attempt_index}.net.xml"
        materialization = _write_movement_candidate(
            joined_net=movement_base,
            plans=plans,
            groups=groups,
            skipped_join_ids=skipped_join_ids,
            output_file=candidate,
            maximum_anchor_projection_error_m=float(
                request["maximum_anchor_projection_error_m"]
            ),
            maximum_lane_projection_error_m=float(request["maximum_lane_projection_error_m"]),
            minimum_lane_match_margin_m=float(request["minimum_lane_match_margin_m"]),
            netconvert_binary=str(request.get("netconvert_binary", "netconvert")),
            timeout_seconds=float(request["timeout_seconds"]),
            original_net=source_net,
            constructed_ingress=constructed_ingress,
            lane_origins=lane_origins,
            identity_changed_edges=changed_edge_ids,
            source_lane_change_evidence=source_lane_change_evidence,
            sumo_binary=str(request.get("sumo_binary", "sumo")),
            seed=int(request["seed"]),
            junction_contours=request["junction_contours"],
        )
        signal_report = rebuild_topology_test_signals(
            net_file=candidate,
            output_dir=destination / f"test-signals-attempt-{attempt_index}",
            target_junction_ids=sorted({str(group["join_id"]) for group in groups}),
            expected_source_sha256=file_sha256(candidate),
        ) if groups else None
        if signal_report is not None:
            if signal_report["status"] != "pass":
                raise ValueError("generic topology signal rebuilding failed its conflict or preservation checks")
            signal_rebuilds.append(signal_report)
            candidate = Path(signal_report["candidate_network"]["path"])
        routeability = run_routeability_audit(
            net_file=candidate,
            output_dir=destination / f"routeability-attempt-{attempt_index}",
            prefix="hamburg_five_combined",
            vehicle_count=int(request["vehicle_count"]),
            seed=int(request["seed"]),
            initial_end=int(request["simulation_end"]),
            max_end=int(request["simulation_max_end"]),
            timeout_seconds=float(request["timeout_seconds"]),
            od_reference_net_file=source_net,
            frozen_trip_file=frozen_probe_trips,
            expected_frozen_trip_sha256=frozen_probe_sha256,
        )
        if frozen_probe_trips is None and routeability.get("trip_file"):
            planned_trips = Path(routeability["trip_file"])
            if planned_trips.is_file():
                frozen_probe_trips, frozen_probe_sha256 = planned_trips, file_sha256(planned_trips)
        attempts.append(
            {
                "attempt": attempt_index,
                "candidate": str(candidate),
                "candidate_sha256": file_sha256(candidate),
                "skipped_join_ids": sorted(skipped_join_ids),
                "materialized_movement_count": materialization["materialized_movement_count"],
                "routeability_status": routeability["status"],
                "routeability_report": routeability["report_file"],
            }
        )
        selected_candidate = candidate
        selected_materialization = materialization
        if routeability["status"] == "pass":
            break
        affected = _collision_join_ids(routeability)
        new_affected = affected - skipped_join_ids
        if not new_affected:
            break
        skipped_join_ids.update(new_affected)

    assert selected_candidate is not None
    assert selected_materialization is not None
    assert routeability is not None
    source_routeability = run_routeability_audit(
        net_file=source_net, output_dir=destination / "source-routeability",
        prefix="same_od_source", vehicle_count=int(request["vehicle_count"]), seed=int(request["seed"]),
        initial_end=int(request["simulation_end"]), max_end=int(request["simulation_max_end"]),
        timeout_seconds=float(request["timeout_seconds"]), frozen_trip_file=frozen_probe_trips,
        expected_frozen_trip_sha256=frozen_probe_sha256,
    ) if frozen_probe_trips is not None else None
    final_net = destination / "hamburg-five-aerial-combined.net.xml"
    shutil.copy2(selected_candidate, final_net)
    load = run_command(
        [
            str(request.get("sumo_binary", "sumo")),
            "-n",
            str(final_net),
            "--begin",
            "0",
            "--end",
            "1",
            "--no-step-log",
            "true",
        ],
        cwd=destination,
        timeout_seconds=float(request["timeout_seconds"]),
    )
    (destination / "sumo-load.log").write_text(
        load.stdout + load.stderr,
        encoding="utf-8",
    )
    source_surface = audit_sumo_lane_junction_surface_overlaps(
        source_net,
        report_file=destination / "source-surface-overlap.json",
    )
    candidate_surface = audit_sumo_lane_junction_surface_overlaps(
        final_net,
        report_file=destination / "candidate-surface-overlap.json",
    )
    source_findings = _surface_finding_count(source_surface)
    candidate_findings = _surface_finding_count(candidate_surface)
    connection_audit = audit_network_connection_mode(ET.parse(final_net).getroot(), endpoint_tolerance_m=0.1)
    connection_report = destination / "connection-mode-audit.json"
    connection_report.write_text(json.dumps(connection_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    topology = selected_materialization["official_connection_audit"]
    structural_pass = connection_audit["structural_failure_count"] == 0 and connection_audit["status"] != "fail"
    source_unchanged = file_sha256(source_net) == str(request["source_net"]["sha256"]).lower()
    status = (
        "pass"
        if load.returncode == 0
        and routeability["status"] == "pass"
        and candidate_findings <= source_findings
        and structural_pass
        and source_unchanged
        and topology["status"] != "blocked"
        else "blocked"
    )
    plan_hashes = {
        node_id: str(row["plan_sha256"]).lower()
        for node_id, row in {
            str(item["node_id"]): item for item in summary["intersections"]
        }.items()
    }
    manifest = {
        "schema": CANDIDATE_SCHEMA,
        "status": status,
        "decision": "review_required" if status == "pass" else "blocked",
        "topology_complete": status == "pass" and topology["status"] == "pass",
        "claim_status": "diagnostic-demo" if status == "pass" else "construction-invalid",
        "inputs": {
            "request": {"path": str(request_path), "sha256": file_sha256(request_path)},
            "source_net": {"path": str(source_net), "sha256": file_sha256(source_net)},
            "cluster_binding": {
                "path": str(cluster_binding),
                "sha256": file_sha256(cluster_binding),
            },
            "movement_summary": {
                "path": str(movement_summary),
                "sha256": file_sha256(movement_summary),
            },
            "movement_plans": plan_hashes,
        },
        "counts": {
            "official_vehicle_movements": int(summary["totals"]["official_vehicle_movements"]),
            "physical_part_count": sum(len(_movements_by_part(plan)) for plan in plans.values()),
            "joined_part_count": sum(len(group["source_node_ids"]) > 1 for group in groups),
            "materialized_movement_count": selected_materialization["materialized_movement_count"],
            "unmaterialized_official_movement_count": (
                int(summary["totals"]["official_vehicle_movements"])
                - selected_materialization["materialized_movement_count"]
            ),
            "runtime_fallback_part_count": len(skipped_join_ids),
            "source_surface_finding_count": source_findings,
            "candidate_surface_finding_count": candidate_findings,
        },
        "parameters": {
            "seed": int(request["seed"]),
            "vehicle_count": int(request["vehicle_count"]),
            "simulation_end": int(request["simulation_end"]),
            "simulation_max_end": int(request["simulation_max_end"]),
            "junction_contours": request["junction_contours"],
            "maximum_anchor_projection_error_m": float(
                request["maximum_anchor_projection_error_m"]
            ),
        },
        "physical_parts": groups,
        "context_rebuild": context,
        "boundary_rebuild": boundary_rebuild,
        "approach_rebuild": approach_rebuild,
        "generic_test_signals": signal_rebuilds,
        "movement_materialization": selected_materialization,
        "official_connection_audit": topology,
        "connection_mode": {"status": connection_audit["status"], "structural_failure_count": connection_audit["structural_failure_count"], "report": str(connection_report)},
        "runtime_fallback_join_ids": sorted(skipped_join_ids),
        "attempts": attempts,
        "netconvert": {
            "returncode": netconvert.returncode,
            "warning_count": sum(
                line.startswith("Warning:")
                for line in (netconvert.stdout + netconvert.stderr).splitlines()
            ),
            "log": str(destination / "netconvert.log"),
        },
        "sumo_load": {
            "returncode": load.returncode,
            "stderr": load.stderr,
            "log": str(destination / "sumo-load.log"),
        },
        "routeability": routeability,
        "source_routeability_same_requests": source_routeability,
        "routeability_pairing": {
            "trip_file": str(frozen_probe_trips) if frozen_probe_trips is not None else None,
            "trip_sha256": frozen_probe_sha256,
            "source_status": source_routeability.get("status") if source_routeability else "not_run",
            "candidate_status": routeability["status"],
            "basis": "Generate one declared eligible OD set, then retain the same requests across candidate attempts and the original source run. Eligibility changes and all routing failures remain visible.",
            "claim_boundary": "This is synthetic topology diagnostics, not calibrated demand or a field traffic-performance comparison.",
        },
        "surface": {
            "source": {
                "status": source_surface["status"],
                "finding_count": source_findings,
                "report": str(destination / "source-surface-overlap.json"),
            },
            "candidate": {
                "status": candidate_surface["status"],
                "finding_count": candidate_findings,
                "report": str(destination / "candidate-surface-overlap.json"),
            },
        },
        "gates": {
            "source_hashes": "pass" if source_unchanged else "blocked",
            "netconvert": "pass" if netconvert.returncode == 0 else "blocked",
            "sumo_load": "pass" if load.returncode == 0 else "blocked",
            "routeability": "pass" if routeability["status"] == "pass" else "blocked",
            "surface_regression": "pass" if candidate_findings <= source_findings else "blocked",
            "connection_structure": "pass" if structural_pass else "blocked",
            "official_lane_connections": topology["status"],
            "all_official_movements_materialized": (
                "pass"
                if selected_materialization["materialized_movement_count"]
                == int(summary["totals"]["official_vehicle_movements"])
                else "review_required"
            ),
            "official_signal_timing": "not_run",
        },
        "artifacts": {
            "network": {"path": str(final_net), "sha256": file_sha256(final_net)},
            "movement_base": {"path": str(movement_base), "sha256": file_sha256(movement_base)},
            "construction_net": {"path": str(construction_net), "sha256": file_sha256(construction_net)},
            "join_file": {"path": str(join_file), "sha256": file_sha256(join_file)},
        },
        "claim_boundary": (
            "This candidate combines physical-part node joins and a bounded subset of selected movement curves. "
            "Unmatched movements retain source SUMO geometry. Signal timing remains source-derived or generic. "
            "The candidate is diagnostic and requires visual review before any promotion."
        ),
    }
    manifest_file = destination / "manifest.json"
    manifest_file.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest["artifacts"]["manifest"] = {
        "path": str(manifest_file),
        "sha256": file_sha256(manifest_file),
    }
    return manifest


def movement_surface_polygon(
    movements: Sequence[Sequence[Point]],
    *,
    lane_width_m: float = 3.2,
    resolution_m: float = 0.1,
    simplify_m: float = 0.15,
) -> list[Point]:
    """Trace the outer boundary of buffered movement lines."""
    lines = [[(float(x), float(y)) for x, y in line] for line in movements if len(line) >= 2]
    if not lines:
        raise ValueError("movements must contain at least one two-point line")
    if lane_width_m <= 0 or resolution_m <= 0 or simplify_m <= 0:
        raise ValueError("surface dimensions must be positive")
    points = [point for line in lines for point in line]
    pad = lane_width_m
    min_x, max_x = min(x for x, _ in points) - pad, max(x for x, _ in points) + pad
    min_y, max_y = min(y for _, y in points) - pad, max(y for _, y in points) + pad
    width = math.ceil((max_x - min_x) / resolution_m) + 1
    height = math.ceil((max_y - min_y) / resolution_m) + 1
    image = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(image)

    def pixel(point: Point) -> tuple[int, int]:
        return (
            round((point[0] - min_x) / resolution_m),
            round((max_y - point[1]) / resolution_m),
        )

    line_width = max(3, round(lane_width_m / resolution_m))
    for line in lines:
        draw.line([pixel(point) for point in line], fill=1, width=line_width, joint="curve")
    mask = ndimage.binary_closing(np.asarray(image, dtype=bool), iterations=2)
    labels, count = ndimage.label(mask)
    if count > 1:
        sizes = ndimage.sum(mask, labels, range(1, count + 1))
        mask = labels == int(np.argmax(sizes)) + 1
    contour = _marching_loop(mask)
    polygon = [
        (min_x + x * resolution_m, max_y - y * resolution_m)
        for x, y in contour
    ]
    simplified = _simplify_closed(polygon, simplify_m)
    if len(simplified) < 8:
        raise ValueError("movement surface produced fewer than eight boundary points")
    return simplified


def reanchor_movement_shape(
    shape: Sequence[Point],
    *,
    start: Point,
    end: Point,
) -> list[Point]:
    """Move both endpoints and blend their corrections through the curve."""
    values = [(float(x), float(y)) for x, y in shape]
    if len(values) < 2:
        raise ValueError("shape must contain at least two points")
    start_delta = (start[0] - values[0][0], start[1] - values[0][1])
    end_delta = (end[0] - values[-1][0], end[1] - values[-1][1])
    cumulative = [0.0]
    for left, right in zip(values, values[1:]):
        cumulative.append(cumulative[-1] + math.dist(left, right))
    total = cumulative[-1]
    result = []
    for point, station in zip(values, cumulative):
        ratio = station / total if total > 0 else 0.0
        result.append(
            (
                point[0] + start_delta[0] * (1 - ratio) + end_delta[0] * ratio,
                point[1] + start_delta[1] * (1 - ratio) + end_delta[1] * ratio,
            )
        )
    result[0], result[-1] = start, end
    return result


def fit_movement_shape_to_anchors(
    shape: Sequence[Point],
    *,
    start: Point,
    end: Point,
) -> tuple[list[Point], float]:
    """Trim a movement to ordered anchors, then remove the small residual gap."""
    values = [(float(x), float(y)) for x, y in shape]
    if len(values) < 2:
        raise ValueError("shape must contain at least two points")
    projections = [
        (
            _segment_projection(start, left, right),
            _segment_projection(end, left, right),
        )
        for left, right in zip(values, values[1:])
    ]
    choices = []
    for start_index, (start_projection, _) in enumerate(projections):
        for end_index in range(start_index, len(projections)):
            end_projection = projections[end_index][1]
            if start_index == end_index and end_projection[1] < start_projection[1]:
                continue
            choices.append(
                (
                    start_projection[2] + end_projection[2],
                    start_index,
                    end_index,
                    start_projection[0],
                    end_projection[0],
                )
            )
    if not choices:
        return [start, end], math.dist(start, values[0]) + math.dist(end, values[-1])
    error, start_index, end_index, first, last = min(choices, key=lambda row: row[0])
    trimmed = [first, *values[start_index + 1 : end_index + 1], last]
    trimmed = [
        point
        for index, point in enumerate(trimmed)
        if index == 0 or math.dist(point, trimmed[index - 1]) > 1e-6
    ]
    if len(trimmed) < 2:
        trimmed = [first, last]
    return reanchor_movement_shape(trimmed, start=start, end=end), error


def _segment_projection(point: Point, start: Point, end: Point) -> tuple[Point, float, float]:
    dx, dy = end[0] - start[0], end[1] - start[1]
    if dx == dy == 0:
        return start, 0.0, math.dist(point, start)
    ratio = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy)
            / (dx * dx + dy * dy),
        ),
    )
    projection = (start[0] + ratio * dx, start[1] + ratio * dy)
    return projection, ratio, math.dist(point, projection)


def _marching_loop(mask: np.ndarray) -> list[Point]:
    top, right, bottom, left = (0.5, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 0.5)
    table = {
        1: ((left, top),),
        2: ((top, right),),
        3: ((left, right),),
        4: ((right, bottom),),
        5: ((left, top), (right, bottom)),
        6: ((top, bottom),),
        7: ((left, bottom),),
        8: ((bottom, left),),
        9: ((top, bottom),),
        10: ((top, right), (bottom, left)),
        11: ((right, bottom),),
        12: ((left, right),),
        13: ((top, right),),
        14: ((left, top),),
    }
    segments = []
    for y in range(mask.shape[0] - 1):
        for x in range(mask.shape[1] - 1):
            code = (
                int(mask[y, x])
                + 2 * int(mask[y, x + 1])
                + 4 * int(mask[y + 1, x + 1])
                + 8 * int(mask[y + 1, x])
            )
            for first, second in table.get(code, ()):
                segments.append(
                    ((x + first[0], y + first[1]), (x + second[0], y + second[1]))
                )
    adjacency: dict[Point, list[tuple[int, Point]]] = defaultdict(list)
    for index, (first, second) in enumerate(segments):
        adjacency[first].append((index, second))
        adjacency[second].append((index, first))
    unused = set(range(len(segments)))
    loops = []
    while unused:
        index = next(iter(unused))
        start, current = segments[index]
        unused.remove(index)
        loop = [start, current]
        while current != start:
            choices = [(item, other) for item, other in adjacency[current] if item in unused]
            if not choices:
                break
            item, current = choices[0]
            unused.remove(item)
            loop.append(current)
        if len(loop) >= 4 and loop[-1] == start:
            loops.append(loop[:-1])
    if not loops:
        raise ValueError("movement surface has no closed outer boundary")
    return max(loops, key=_polygon_area)


def _simplify_closed(points: list[Point], tolerance: float) -> list[Point]:
    values = points[:]
    changed = True
    while changed and len(values) > 12:
        changed = False
        kept = []
        for index, point in enumerate(values):
            if (
                index % 2 == 0
                and _point_segment_distance(
                    point,
                    values[index - 1],
                    values[(index + 1) % len(values)],
                )
                < tolerance
            ):
                changed = True
            else:
                kept.append(point)
        values = kept
    return values


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    if dx == dy == 0:
        return math.dist(point, start)
    ratio = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy)
            / (dx * dx + dy * dy),
        ),
    )
    return math.dist(point, (start[0] + ratio * dx, start[1] + ratio * dy))


def _polygon_area(points: Sequence[Point]) -> float:
    return abs(
        sum(
            left[0] * right[1] - right[0] * left[1]
            for left, right in zip(points, [*points[1:], points[0]])
        )
    ) / 2


def _read_request(path: Path) -> dict[str, Any]:
    payload = _load_json(path, "request")
    if payload.get("schema") != REQUEST_SCHEMA:
        raise ValueError(f"request schema must be {REQUEST_SCHEMA}")
    for key in ("source_net", "cluster_binding", "movement_summary"):
        value = payload.get(key)
        if not isinstance(value, dict) or not value.get("path") or not value.get("sha256"):
            raise ValueError(f"request {key} must contain path and sha256")
        artifact_path = Path(str(value["path"])).expanduser()
        if not artifact_path.is_absolute():
            value["path"] = str((path.parent / artifact_path).resolve())
    defaults = {
        "seed": 104,
        "vehicle_count": 100,
        "simulation_end": 600,
        "timeout_seconds": 240.0,
        "maximum_endpoint_error_m": 20.0,
        "maximum_lane_projection_error_m": 10.0,
        "minimum_lane_match_margin_m": 0.5,
    }
    result = {**defaults, **payload}
    if result.setdefault("junction_contours", "preserve") not in ("preserve", "guarded"):
        raise ValueError("junction_contours must be preserve or guarded")
    context_groups = result.setdefault("context_joins", {})
    if not isinstance(context_groups, dict):
        raise ValueError("context_joins must map join ids to source node lists")
    seen_members = set()
    for join_id, members in context_groups.items():
        if not isinstance(join_id, str) or not join_id or join_id.startswith(":") or any(char.isspace() for char in join_id):
            raise ValueError("context_joins requires non-empty external junction ids")
        if not isinstance(members, list) or len(members) < 2 or any(not isinstance(node, str) or not node or any(char.isspace() for char in node) for node in members):
            raise ValueError("context_joins requires at least two source node ids per group")
        if len(set(members)) != len(members) or seen_members.intersection(members):
            raise ValueError("context_joins source node groups must be unique and disjoint")
        seen_members.update(members)
    neighbors = result.setdefault("context_geometry_neighbors", [])
    if not isinstance(neighbors, list) or any(not isinstance(node, str) or not node or any(char.isspace() for char in node) for node in neighbors) or len(set(neighbors)) != len(neighbors) or (neighbors and not context_groups):
        raise ValueError("context_geometry_neighbors requires unique adjacent node ids and declared context_joins")
    result.setdefault("simulation_max_end", result["simulation_end"])
    result.setdefault(
        "maximum_anchor_projection_error_m",
        min(10.0, float(result["maximum_endpoint_error_m"])),
    )
    for key in ("seed", "vehicle_count", "simulation_end", "simulation_max_end"):
        if isinstance(result[key], bool) or int(result[key]) <= 0:
            raise ValueError(f"request {key} must be a positive integer")
    if int(result["simulation_max_end"]) < int(result["simulation_end"]):
        raise ValueError("simulation_max_end must not precede simulation_end")
    for key in (
        "timeout_seconds",
        "maximum_endpoint_error_m",
        "maximum_anchor_projection_error_m",
        "maximum_lane_projection_error_m",
        "minimum_lane_match_margin_m",
    ):
        if not math.isfinite(float(result[key])) or float(result[key]) <= 0:
            raise ValueError(f"request {key} must be positive")
    return result


def _load_movement_plans(summary: Mapping[str, Any], *, base_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    plans = {}
    for row in summary.get("intersections", []):
        node_id = str(row.get("node_id", ""))
        if not node_id or node_id in plans:
            raise ValueError("movement summary must have unique non-empty node ids")
        plan_path = Path(row["plan_file"]).expanduser()
        if not plan_path.is_absolute() and base_dir is not None:
            plan_path = base_dir / plan_path
        path = _verified_artifact(
            {"path": str(plan_path), "sha256": row.get("plan_sha256", "")},
            f"movement plan {node_id}",
        )
        plan = _load_json(path, f"movement plan {node_id}")
        if plan.get("schema") != "torii.hamburg-aerial-movement-plan/v1" or str(plan.get("node_id")) != node_id:
            raise ValueError(f"movement plan {node_id} has an invalid schema or node id")
        if not plan.get("movements") or not plan.get("lanes"):
            raise ValueError(f"movement plan {node_id} requires official movements and lane geometry")
        plans[node_id] = plan
    if not plans:
        raise ValueError("movement summary has no intersections")
    return plans


def _project_plan_to_network(plan: Mapping[str, Any], root: ET.Element) -> dict[str, Any]:
    location = root.find("location")
    projection = location.get("projParameter", "") if location is not None else ""
    if not projection or projection in {"!", "-", "."}:
        raise ValueError("source network requires an explicit geographic projection")
    try:
        source_crs = CRS.from_user_input(plan["crs"])
        target_crs = CRS.from_user_input(projection)
        if source_crs != CRS.from_epsg(25832):
            raise ValueError("shape_epsg25832 fields require plan crs EPSG:25832")
        transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
        offset = _net_offset(root)
    except (KeyError, ValueError) as error:
        raise ValueError(f"invalid plan/network projection: {error}") from error
    result = deepcopy(dict(plan))
    for rows, source_key, target_key in (
        (result.get("lanes", []), "shape_epsg25832", "shape_network"),
        (result.get("movements", []), "selected_shape_epsg25832", "selected_shape_network"),
        ([row for row in result.get("movements", []) if "official_shape_epsg25832" in row],
         "official_shape_epsg25832", "official_shape_network"),
    ):
        for row in rows:
            values = []
            for x, y, *_ in row[source_key]:
                tx, ty = transformer.transform(float(x), float(y), errcheck=True)
                values.append((tx + offset[0], ty + offset[1]))
            if len(values) < 2 or any(not math.isfinite(v) for point in values for v in point):
                raise ValueError("official lane/movement geometry must contain at least two finite points")
            row[target_key] = values
    boundary_points = _official_lane_boundary_points(plan, root)
    for lane in result.get("lanes", []):
        if str(lane.get("lane_id")) in boundary_points:
            lane["junction_endpoint_network"] = boundary_points[str(lane["lane_id"])]
    if plan.get("inputs", {}).get("map_xml"):
        map_path = _verified_artifact(plan["inputs"]["map_xml"], "official MAP lane permissions")
        metadata = {str(lane.lane_id): lane.permission_metadata for lane in parse_mapem(map_path)[0]}
        for lane in result.get("lanes", []):
            if str(lane.get("lane_id")) in metadata:
                lane.update(metadata[str(lane["lane_id"])])
    result["network_projection"] = projection
    result["network_offset"] = list(offset)
    return result


def _bind_official_lanes(
    lanes: Sequence[Mapping[str, Any]],
    movements: Sequence[Mapping[str, Any]],
    candidates: Mapping[tuple[str, int], Sequence[Point]],
    *,
    role: str,
    max_error_m: float,
    margin_m: float,
    candidate_modes: Mapping[tuple[str, int], set[str]] | None = None,
    internal_lane_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Bind each official lane once; a close second match remains unresolved."""
    identity_key = f"{role}_lane_id"
    lane_by_id = {str(lane["lane_id"]): lane for lane in lanes if str(lane.get("lane_type", "")).lower() == "vehicle"}
    bindings: dict[str, tuple[str, int]] = {}
    records = []
    ambiguous = []
    lane_options = {}
    internal = set(map(str, internal_lane_ids))
    for lane_id in sorted({str(row[identity_key]) for row in movements}):
        if lane_id in internal:
            record = {"lane_id": lane_id, "role": role, "reason": "official_anchor_inside_join", "candidates": []}
            records.append(record)
            ambiguous.append(record)
            continue
        lane = lane_by_id.get(lane_id)
        if lane is None:
            ambiguous.append({"lane_id": lane_id, "role": role, "reason": "official_lane_geometry_missing"})
            continue
        if lane.get("permission_status") == "review_required":
            ambiguous.append({"lane_id": lane_id, "role": role, "reason": "official_vehicle_permission_requires_review"})
            continue
        required_modes = set(lane.get("allowed_vehicle_classes") or [])
        opposite = "egress_lane_id" if role == "ingress" else "ingress_lane_id"
        for movement in movements:
            if str(movement[identity_key]) == lane_id:
                other = lane_by_id.get(str(movement.get(opposite, "")), {})
                required_modes.update(other.get("allowed_vehicle_classes") or [])
        if lane.get("junction_endpoint_network") is not None:
            shape = lane["shape_network"]
            boundary = lane["junction_endpoint_network"]
            toward_boundary = (
                (shape[1], shape[0])
                if math.dist(shape[0], boundary) < math.dist(shape[-1], boundary)
                else (shape[-2], shape[-1])
            )
            first, last = toward_boundary if role == "ingress" else tuple(reversed(toward_boundary))
        else:
            movement = next(row for row in movements if str(row[identity_key]) == lane_id)
            shape = movement["selected_shape_network"]
            first, last = (shape[0], shape[1]) if role == "ingress" else (shape[-2], shape[-1])
        direction = (last[0] - first[0], last[1] - first[1])
        options = []
        for key, candidate in candidates.items():
            if required_modes and not required_modes.issubset((candidate_modes or {}).get(key, set())):
                continue
            a, b = (candidate[-2], candidate[-1]) if role == "ingress" else (candidate[0], candidate[1])
            delta = (b[0] - a[0], b[1] - a[1])
            norm = math.hypot(*direction) * math.hypot(*delta)
            if norm <= 1e-9 or sum(x * y for x, y in zip(direction, delta)) / norm < math.cos(math.radians(45)):
                continue
            error = _lane_overlap_error(lane["shape_network"], candidate)
            if math.isfinite(error):
                options.append((error, key))
        options.sort()
        lane_options[lane_id] = options
        if not options or options[0][0] > max_error_m:
            reason = "no_directed_lane_within_limit"
        elif len(options) > 1 and options[1][0] - options[0][0] < margin_m:
            reason = "lane_match_ambiguous"
        else:
            bindings[lane_id] = options[0][1]
            reason = "unique_directed_official_lane_fit"
        record = {"lane_id": lane_id, "role": role, "reason": reason, "candidates": [{"edge": key[0], "lane": key[1], "mean_error_m": round(error, 6)} for error, key in options[:2]]}
        records.append(record)
        if lane_id not in bindings:
            ambiguous.append(record)
    owners: dict[tuple[str, int], list[str]] = defaultdict(list)
    for lane_id, key in bindings.items():
        owners[key].append(lane_id)
    for key, lane_ids in owners.items():
        if len(lane_ids) > 1:
            for lane_id in lane_ids:
                bindings.pop(lane_id)
                ambiguous.append({"lane_id": lane_id, "role": role, "reason": "multiple_official_lanes_share_sumo_lane", "sumo_lane": list(key)})
    ordered = _ordered_approach_lane_bindings(
        lane_by_id, lane_options, candidates, bindings,
        role=role, max_error_m=max_error_m, margin_m=margin_m,
    )
    for group in ordered:
        for lane_id, key in group["bindings"].items():
            bindings[lane_id] = key
            next(row for row in records if row["lane_id"] == lane_id)["reason"] = "ordered_same_approach_lane_fit"
    # Missing source lanes need not erase the remaining clear matches. After
    # equal-count ordering, keep only mutually nearest, separated matches.
    # Use the existing margin in both directions; never assign both claims.
    for key, lane_ids in owners.items():
        if len(lane_ids) < 2 or key in bindings.values():
            continue
        reverse = sorted((error, lane_id) for lane_id, options in lane_options.items()
                         for error, target in options if target == key)
        error, lane_id = reverse[0]
        if lane_id not in lane_ids or lane_id in bindings or reverse[1][0] - error < margin_m:
            continue
        bindings[lane_id] = key
        record = next(row for row in records if row["lane_id"] == lane_id)
        record.update(reason="mutual_unique_directed_official_lane_fit", reverse_match_margin_m=round(reverse[1][0] - error, 6))
    ambiguous = [row for row in ambiguous if row["lane_id"] not in bindings]
    return {"bindings": bindings, "records": records, "ambiguous": ambiguous, "ordered_groups": ordered}


def _ordered_approach_lane_bindings(
    lanes, options, candidates, existing, *, role, max_error_m, margin_m,
) -> list[dict[str, Any]]:
    """Resolve a lateral offset only for one proven, equal-count road arm."""
    approaches = defaultdict(list)
    for lane_id, lane in lanes.items():
        if lane_id not in options:
            continue  # Only this physical part's movement lanes share an approach.
        approach = str(lane.get(f"{role}_approach", "")).strip()
        if approach and approach != "0":
            approaches[approach].append(lane_id)
    result = []
    occupied = dict(existing)
    for approach, lane_ids in approaches.items():
        if len(lane_ids) < 2 or any(lane_id not in options for lane_id in lane_ids):
            continue
        if all(lane_id in occupied for lane_id in lane_ids):
            continue
        # Select the road arm before checking its lane count. A closer road
        # with a different count cannot be replaced by a more distant match.
        chosen_edges = []
        for lane_id in lane_ids:
            edge_errors = {}
            for error, (edge_id, _) in options[lane_id]:
                edge_errors[edge_id] = min(error, edge_errors.get(edge_id, math.inf))
            ranked = sorted((error, edge_id) for edge_id, error in edge_errors.items())
            if not ranked or ranked[0][0] > max_error_m or (len(ranked) > 1 and ranked[1][0] - ranked[0][0] < margin_m):
                break
            chosen_edges.append(ranked[0][1])
        if len(chosen_edges) != len(lane_ids) or len(set(chosen_edges)) != 1:
            continue
        edge_id = chosen_edges[0]
        if any(
            other_id not in lane_ids and values and values[0][0] <= max_error_m and values[0][1][0] == edge_id
            for other_id, values in options.items()
        ):
            continue
        edge_lanes = {key: shape for key, shape in candidates.items() if key[0] == edge_id}
        if len(edge_lanes) != len(lane_ids):
            continue
        if any(key in edge_lanes for lane_id, key in occupied.items() if lane_id not in lane_ids):
            continue
        # The road axis comes from the SUMO approach. A movement curve may
        # already turn at its first point, so its mean tangent is not the arm axis.
        direction = np.asarray([
            np.asarray(shape[-1]) - shape[-2] if role == "ingress" else np.asarray(shape[1]) - shape[0]
            for shape in edge_lanes.values()
        ], dtype=float)
        lengths = np.linalg.norm(direction, axis=1)
        if min(lengths) <= 1e-9:
            continue
        unit = direction / lengths[:, None]
        axis = unit.mean(axis=0)
        axis_length = float(np.linalg.norm(axis))
        if axis_length <= 1e-9:
            continue
        axis /= axis_length
        if min(unit @ axis) < math.cos(math.radians(45)):
            continue
        official = {lane_id: lanes[lane_id]["shape_network"] for lane_id in lane_ids}
        all_shapes = [*official.values(), *edge_lanes.values()]
        extents = [(min(np.asarray(shape) @ axis), max(np.asarray(shape) @ axis)) for shape in all_shapes]
        lower, upper = max(a for a, _ in extents), min(b for _, b in extents)
        if upper - lower <= 1e-6:
            continue
        stations = [lower + fraction * (upper - lower) for fraction in (0.2, 0.5, 0.8)]
        official_order = _common_section_lane_order(official, axis, stations, margin_m)
        target_order = _common_section_lane_order(edge_lanes, axis, stations, margin_m)
        if official_order is None or target_order is None:
            continue
        mapping = dict(zip(official_order, target_order))
        errors = [next((error for error, key in options[lane_id] if key == target), math.inf) for lane_id, target in mapping.items()]
        if max(errors) > max_error_m:
            continue
        occupied.update(mapping)
        result.append({"approach": approach, "role": role, "edge_id": edge_id, "bindings": mapping,
                       "basis": "equal_lane_count_and_consistent_common_section_order",
                       "maximum_lane_error_m": round(max(errors), 6)})
    return result


def _common_section_lane_order(shapes, axis, stations, margin_m):
    """Return right-to-left order only when three shared sections agree."""
    normal = np.asarray((-axis[1], axis[0]))
    orders = []
    for station in stations:
        offsets = []
        for lane_id, shape in shapes.items():
            crossings = []
            for a, b in zip(shape, shape[1:]):
                start, end = float(np.dot(a, axis)), float(np.dot(b, axis))
                if abs(end - start) <= 1e-9:
                    continue
                ratio = (station - start) / (end - start)
                if 0 <= ratio <= 1:
                    lateral = float(np.dot(np.asarray(a) + ratio * (np.asarray(b) - a), normal))
                    if not any(abs(lateral - old) < 1e-6 for old in crossings):
                        crossings.append(lateral)
            if len(crossings) != 1:
                return None
            offsets.append((crossings[0], lane_id))
        offsets.sort()
        if any(right[0] - left[0] < margin_m for left, right in zip(offsets, offsets[1:])):
            return None
        orders.append([lane_id for _, lane_id in offsets])
    return orders[0] if all(order == orders[0] for order in orders) else None


def _lane_overlap_error(official: Sequence[Point], candidate: Sequence[Point]) -> float:
    """Mean lateral distance over the entire shared longitudinal interval.

    Reconcile coverage before comparison, not by choosing the best short
    segment. This ordered approach-section fit is not a Frechet distance.
    """
    if len(official) < 2 or len(candidate) < 2:
        return math.inf
    origin = np.asarray(official[0], dtype=float)
    axis = np.asarray(official[-1], dtype=float) - origin
    length = float(np.linalg.norm(axis))
    if not math.isfinite(length) or length <= 1e-9:
        return math.inf
    axis /= length
    normal = np.asarray((-axis[1], axis[0]))
    profiles = [
        np.column_stack(((np.asarray(shape) - origin) @ axis, (np.asarray(shape) - origin) @ normal))
        for shape in (official, candidate)
    ]
    if any(not np.isfinite(profile).all() for profile in profiles):
        return math.inf
    lower = max(float(profile[:, 0].min()) for profile in profiles)
    upper = min(float(profile[:, 0].max()) for profile in profiles)
    if upper - lower <= 1e-6:
        return math.inf
    stations = sorted({lower, upper, *(float(x) for profile in profiles for x in profile[:, 0] if lower < x < upper)})
    differences = []
    for station in stations:
        offsets = [_lane_section_lateral_offset(profile, station) for profile in profiles]
        if any(offset is None for offset in offsets):
            return math.inf
        differences.append(offsets[0] - offsets[1])
    area = 0.0
    for start, end, a, b in zip(stations, stations[1:], differences, differences[1:]):
        # Vertex stations make both offsets linear on each interval. Split
        # at a sign change analytically, so vertex density cannot change fit.
        mean = (abs(a) + abs(b)) / 2 if a * b >= 0 else (a * a + b * b) / (2 * (abs(a) + abs(b)))
        area += (end - start) * mean
    return area / (upper - lower)


def _lane_section_lateral_offset(profile, station):
    """Return one section crossing, never select a branch by proximity."""
    crossings = []
    for a, b in zip(profile, profile[1:]):
        if min(a[0], b[0]) - 1e-9 <= station <= max(a[0], b[0]) + 1e-9:
            if abs(b[0] - a[0]) <= 1e-9:
                crossings.extend((float(a[1]), float(b[1])))
            else:
                ratio = min(1.0, max(0.0, (station - a[0]) / (b[0] - a[0])))
                crossings.append(float(a[1] + ratio * (b[1] - a[1])))
    if not crossings or max(crossings) - min(crossings) > 1e-6:
        return None
    return sum(crossings) / len(crossings)


def _verified_artifact(value: Mapping[str, Any], label: str) -> Path:
    path = Path(str(value["path"])).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{label} is not a file: {path}")
    expected = str(value["sha256"]).lower()
    if len(expected) != 64 or file_sha256(path).lower() != expected:
        raise ValueError(f"{label} SHA-256 does not match the request")
    return path


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label} JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _official_lane_boundary_points(plan: Mapping[str, Any], root: ET.Element) -> dict[str, Point]:
    artifact = plan.get("inputs", {}).get("map_kml")
    if not artifact:
        return {}
    source = _verified_artifact(artifact, "official MAP boundary KML")
    geometry = parse_hamburg_map_kml(source, expected_sha256=str(artifact["sha256"]))
    location = root.find("location")
    if location is None or location.get("projParameter", "") in {"", "!", "-", "."}:
        raise ValueError("official boundary points require the source network projection")
    transformer = Transformer.from_crs("EPSG:4326", location.attrib["projParameter"], always_xy=True)
    offset = _net_offset(root)
    result = {}
    for row in geometry["endpoints"]:
        if row["endpoint"] != "B" or row["feature_kind"] != "lane":
            continue
        x, y = transformer.transform(*row["coordinate"][:2], errcheck=True)
        result[str(row["lane_id"])] = (x + offset[0], y + offset[1])
    return result


def _boundary_distance(point: Point, polygon: Sequence[Point]) -> float:
    inside = False
    for a, b in zip(polygon, [*polygon[1:], polygon[0]]):
        if (a[1] > point[1]) != (b[1] > point[1]):
            crossing_x = a[0] + (point[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if point[0] < crossing_x:
                inside = not inside
    return 0.0 if inside else min(_point_segment_distance(point, a, b) for a, b in zip(polygon, [*polygon[1:], polygon[0]]))


def _official_boundary_widths(plan: Mapping[str, Any]) -> dict[str, float]:
    """Read MAP centimetre widths at an explicit stop-line node."""
    artifact = plan.get("inputs", {}).get("map_xml")
    if not artifact:
        return {}
    root = ET.parse(_verified_artifact(artifact, "official MAP boundary widths")).getroot()
    result = {}
    for geometry in root.iter():
        if geometry.tag.split("}")[-1] != "IntersectionGeometry":
            continue
        default = next((int(child.text or "0") for child in geometry if child.tag.split("}")[-1] == "laneWidth"), 0)
        if default <= 0:
            continue
        for lane in geometry.iter():
            if lane.tag.split("}")[-1] != "GenericLane":
                continue
            lane_id = next(((child.text or "").strip() for child in lane if child.tag.split("}")[-1] == "laneID"), "")
            width = default
            found_stopline = False
            has_deltas = False
            for node in lane.iter():
                if node.tag.split("}")[-1] != "NodeXY":
                    continue
                for attribute in node.iter():
                    if attribute.tag.split("}")[-1] == "dWidth":
                        width += int(attribute.text or "0")
                        has_deltas = True
                if any(attribute.tag.split("}")[-1] == "stopLine" for attribute in node.iter()):
                    found_stopline = True
                    break
            if lane_id and width > 0 and (found_stopline or not has_deltas):
                result[lane_id] = width / 100.0
    return result


def _official_boundary_sections(plan: Mapping[str, Any], points: Mapping[str, Point]) -> dict[str, dict[str, Any]]:
    widths = _official_boundary_widths(plan)
    result = {}
    for lane in plan.get("lanes", []):
        lane_id = str(lane["lane_id"])
        shape = lane.get("shape_network", [])
        if lane_id not in points or lane_id not in widths or len(shape) < 2:
            continue
        point = points[lane_id]
        a, b = min(zip(shape, shape[1:]), key=lambda pair: _point_segment_distance(point, *pair))
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            continue
        half_width = widths[lane_id] / 2
        result[lane_id] = {"lane_id": lane_id, "width_m": widths[lane_id], "shape": [(point[0] - dy / length * half_width, point[1] + dx / length * half_width), (point[0] + dy / length * half_width, point[1] - dx / length * half_width)]}
    return result


def _section_touches_polygon(section: Sequence[Point], polygon: Sequence[Point]) -> bool:
    # Use the same 0.1 m geometry precision as the complete connection audit.
    if any(max(point[axis] for point in section) < min(point[axis] for point in polygon) - 0.1 or min(point[axis] for point in section) > max(point[axis] for point in polygon) + 0.1 for axis in (0, 1)):
        return False
    return any(_boundary_distance(point, polygon) <= 0.1 for point in section) or any(
        _proper_segments_intersect(section[0], section[-1], a, b, tolerance_m=1e-6)
        for a, b in zip(polygon, [*polygon[1:], polygon[0]])
    )


def _official_internal_paths(plan: Mapping[str, Any], root: ET.Element, points: Mapping[str, Point]) -> dict[str, Any]:
    """Use only official, B-to-B clipped paths to identify junction fragments."""
    artifact = plan.get("inputs", {}).get("map_kml")
    if not artifact:
        return {"paths": {}, "unusable": []}
    source = _verified_artifact(artifact, "official internal movement KML")
    geometry = parse_hamburg_map_kml(source, expected_sha256=str(artifact["sha256"]))
    location = root.find("location")
    transformer = Transformer.from_crs("EPSG:4326", location.attrib["projParameter"], always_xy=True)
    offset = _net_offset(root)
    required = {(str(row["ingress_lane_id"]), str(row["egress_lane_id"])) for row in plan.get("movements", [])}
    paths = {}
    unusable = []
    for row in geometry["drive_lines"]:
        key = (str(row["from_lane_id"]), str(row["to_lane_id"]))
        if key not in required or any(lane_id not in points for lane_id in key):
            continue
        shape = [tuple(value + offset[i] for i, value in enumerate(transformer.transform(*point[:2], errcheck=True))) for point in row["coordinates"]]
        try:
            clipped, _ = _clip_drive_line_to_lane_b_endpoints(shape, ingress_b=points[key[0]], egress_b=points[key[1]], tolerance_m=0.1)
            paths[key] = clipped
        except ValueError as error:
            unusable.append({"ingress_lane_id": key[0], "egress_lane_id": key[1], "reason": str(error)})
    return {"paths": paths, "unusable": unusable}


def _port_section(point, shape, width):
    a, b = min(zip(shape, shape[1:]), key=lambda pair: _point_segment_distance(point, *pair))
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        raise ValueError("a boundary lane requires a nonzero direction")
    return [(point[0] - dy / length * width / 2, point[1] + dx / length * width / 2),
            (point[0] + dy / length * width / 2, point[1] - dx / length * width / 2)]


def _classify_boundary_ports(root, plan, group, points, *, maximum_lane_projection_error_m=10.0, minimum_lane_match_margin_m=0.5):
    """Separate actual graph-cut ports from official anchors inside the join."""
    from .official_movement_composition import _original_lane_bindings, _resolve_original_context
    from .source_movement_support import _index

    movements = [row for row in plan["movements"] if str(row.get("intersection_part", "0")) == str(group["intersection_part"])]
    used = {str(row[key]) for row in movements for key in ("ingress_lane_id", "egress_lane_id")}
    lanes = {str(row["lane_id"]): {**row, "junction_endpoint_network": points[str(row["lane_id"])]}
             for row in plan.get("lanes", []) if str(row["lane_id"]) in used and str(row["lane_id"]) in points
             and row.get("direction_role") in {"ingress", "egress"} and len(row.get("shape_network", [])) >= 2}
    if not lanes:
        return None  # Legacy plans without lane identities keep their explicit boundary.
    index = _index(root)
    members = set(map(str, group["source_node_ids"]))
    bindings, reviews = _original_lane_bindings(index, lanes, members, maximum_lane_projection_error_m, minimum_lane_match_margin_m)
    _resolve_original_context(index, lanes, movements, bindings, reviews, members, minimum_lane_match_margin_m)
    widths = _official_boundary_widths(plan)
    external, internal = [], []
    unresolved = [{"lane_id": lane_id, "role": None, "junction_endpoint_network": points.get(lane_id),
                   "source_lane_id": None, "reason": "official_lane_geometry_or_direction_unproved"} for lane_id in sorted(used - set(lanes))]
    for lane_id, lane in lanes.items():
        original_id = bindings.get(lane_id)
        record = {"lane_id": lane_id, "role": lane["direction_role"], "junction_endpoint_network": points[lane_id], "source_lane_id": original_id}
        if original_id is None or lane.get("permission_status") == "review_required":
            unresolved.append({**record, "reason": "original_lane_identity_unproved"})
            continue
        edge_id, original_lane, _ = index["lanes"][original_id]
        edge = index["edges"][edge_id]
        record["source_edge_id"] = edge_id
        if edge.get("from") in members and edge.get("to") in members:
            internal.append({**record, "reason": "both_source_edge_nodes_inside_join"})
        elif edge.get("to" if lane["direction_role"] == "ingress" else "from") in members:
            width = widths.get(lane_id, float(original_lane.get("width", "3.2")))
            external.append({**record, "width_m": width, "shape": _port_section(points[lane_id], lane["shape_network"], width), "basis": "official_external_B"})
        else:
            unresolved.append({**record, "reason": "official_lane_is_not_an_actual_cut_edge"})
    return {"official_external_ports": external, "official_internal_anchors": internal,
            "official_unresolved_anchors": unresolved, "original_lane_binding_reviews": reviews,
            "maximum_lane_projection_error_m": maximum_lane_projection_error_m,
            "basis": "source_lane_identity_and_actual_join_graph_cut"}


def _strip_longitudinal_interval(a, b, origin, axis, half_width):
    normal = (-axis[1], axis[0])
    offset = sum((a[i] - origin[i]) * normal[i] for i in (0, 1))
    delta = sum((b[i] - a[i]) * normal[i] for i in (0, 1))
    if abs(delta) <= 1e-9:
        if abs(offset) > half_width:
            return None
        low, high = 0.0, 1.0
    else:
        cuts = sorted(((-half_width - offset) / delta, (half_width - offset) / delta))
        low, high = max(0.0, cuts[0]), min(1.0, cuts[1])
        if low > high:
            return None
    positions = [sum((a[i] + fraction * (b[i] - a[i]) - origin[i]) * axis[i] for i in (0, 1)) for fraction in (low, high)]
    return min(positions), max(positions)


def _safe_native_cut_port(root, edge, lane, role, *, maximum_movement_m):
    """Keep an unknown cut beyond the other owner's full road-width exit."""
    shape = _parse_shape(lane.get("shape", ""))
    reference = _parse_shape(edge.get("shape", "")) or shape
    first, last = reference[-2:] if role == "ingress" else reference[:2]
    dx, dy = last[0] - first[0], last[1] - first[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        raise ValueError("native cut requires a nonzero source reference direction")
    point = shape[-1] if role == "ingress" else shape[0]
    width = float(lane.get("width", "3.2"))
    direction = (dx / length, dy / length)
    toward_join = direction if role == "ingress" else (-direction[0], -direction[1])
    remote_id = edge.get("from" if role == "ingress" else "to")
    remote = root.find(f"junction[@id='{remote_id}']")
    polygon = _parse_shape(remote.get("shape", "")) if remote is not None else []
    stations = []
    for a, b in zip(polygon, [*polygon[1:], polygon[0]] if polygon else []):
        interval = _strip_longitudinal_interval(a, b, point, toward_join, width / 2)
        if interval is not None:
            stations.extend(interval)
    # SUMO's minimum edge is 0.1 m. Add the existing 0.1 m boundary precision
    # so output rounding cannot turn a positive road segment into a fallback.
    visible = 0.2
    shift = max(0.0, max(stations) + visible) if stations else 0.0
    if shift > maximum_movement_m:
        raise ValueError(f"native cut cannot clear owner {remote_id} within the requested geometry limit")
    corrected = tuple(point[i] + shift * toward_join[i] for i in (0, 1))
    result = {"junction_endpoint_network": corrected, "width_m": width,
              "shape": _port_section(corrected, [corrected, (corrected[0] + dx, corrected[1] + dy)], width),
              "native_lane_direction": (dx, dy), "basis": "native_joined_cut_lane"}
    if shift > 1e-9:
        result.update(basis="native_cut_order_corrected_after_remote_owner", adjustment={
            "remote_owner": remote_id, "original_native_endpoint": point, "shift_m": shift,
            "minimum_visible_length_m": visible, "width_m": width,
            "basis": "full_lane_strip_exit_along_source_reference_not_internal_MAP_B"})
    else:
        a, b = shape[-2:] if role == "ingress" else shape[:2]
        result.update(shape=_port_section(point, shape, width), native_lane_direction=(b[0] - a[0], b[1] - a[1]))
    return result


def _adjust_native_port_conflicts(root, ports, *, maximum_movement_m):
    """Move unlocated incoming ports upstream, keeping official stops fixed."""
    from .official_movement_composition import _slice_shape

    fixed = [port for port in ports if port["basis"] == "official_external_B"]
    result, reviews = [], []
    for port in ports:
        others = [row for row in fixed if row["source_edge_id"] != port["source_edge_id"]]
        if port["basis"] == "official_external_B" or port["role"] != "ingress" or not any(
            _proper_segments_intersect(*port["shape"], *row["shape"], tolerance_m=1e-6) for row in others
        ):
            result.append(port)
            continue
        edge = root.find(f"edge[@id='{port['source_edge_id']}']")
        lane = edge.find(f"lane[@id='{port['source_lane_id']}']")
        shape = _parse_shape(lane.get("shape", ""))
        lengths = [math.dist(a, b) for a, b in zip(shape, shape[1:])]
        total, end_station = sum(lengths), sum(lengths)
        replacement = None
        for index in range(len(lengths) - 1, -1, -1):
            length = lengths[index]
            start_station = end_station - length
            end_station = start_station
            if length <= 1e-9:
                continue
            a, b = shape[index:index + 2]
            direction = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
            forbidden = []
            for row in others:
                interval = _strip_longitudinal_interval(*row["shape"], a, direction, port["width_m"] / 2)
                if interval is not None:
                    forbidden.append((interval[0] - 0.1, interval[1] + 0.1))
            position = length
            while True:
                occupied = next((span for span in forbidden if span[0] - 1e-9 <= position <= span[1] + 1e-9), None)
                if occupied is None:
                    break
                position = occupied[0] - 1e-6
            if position < max(0.0, total - maximum_movement_m - start_station, 0.2 - start_station):
                continue
            point = tuple(a[i] + position * direction[i] for i in (0, 1))
            kept = _slice_shape(shape, 0.0, start_station + position)
            probe_edge, probe_lane = deepcopy(edge), deepcopy(lane)
            probe_edge.set("shape", _shape(kept))
            probe_lane.set("shape", _shape(kept))
            try:
                _safe_native_cut_port(root, probe_edge, probe_lane, "ingress", maximum_movement_m=0.0)
            except ValueError:
                break
            replacement = {**port, "junction_endpoint_network": point, "shape": _port_section(point, [a, b], port["width_m"]),
                           "native_lane_direction": direction, "basis": "native_geometry_adjustment_preserving_official_ports",
                           "adjustment": {"original_native_endpoint": port["junction_endpoint_network"], "upstream_distance_m": total - start_station - position,
                                          "source_lane_position_m": start_station + position, "width_m": port["width_m"], "source_owner_exit_preserved": True,
                                          "reason": "unlocated_native_port_overlaps_fixed_official_port"}}
            break
        result.append(replacement or port)
        if replacement is None:
            reviews.append({"source_lane_id": port["source_lane_id"], "reason": "no_ordered_native_section_within_requested_limit"})
    # A bidirectional road has one road mouth, even though SUMO stores two
    # directed edges. Moving only its inlet leaves a diagonal notch.
    for i, incoming in enumerate(list(result)):
        if incoming.get("basis") != "native_geometry_adjustment_preserving_official_ports":
            continue
        edge = root.find(f"edge[@id='{incoming['source_edge_id']}']")
        reference = _parse_shape(edge.get("shape", ""))
        for j, outgoing in enumerate(result):
            if outgoing.get("role") != "egress" or outgoing["basis"] == "official_external_B":
                continue
            other = root.find(f"edge[@id='{outgoing['source_edge_id']}']")
            reversed_reference = list(reversed(_parse_shape(other.get("shape", ""))))
            if edge.get("from") != other.get("to") or edge.get("to") != other.get("from") or len(reference) < 2 or len(reference) != len(reversed_reference) or any(math.dist(a, b) > 0.1 for a, b in zip(reference, reversed_reference)):
                continue
            group_ids = {incoming["source_edge_id"], outgoing["source_edge_id"]}
            if any(sum(row["source_edge_id"] == key for row in result) != 1 for key in group_ids):
                result[i] = ports[i]
                reviews.append({"source_lane_id": incoming["source_lane_id"], "reason": "multilane_reverse_road_requires_a_shared_section"})
                break
            vector = incoming["native_lane_direction"]
            norm = math.hypot(*vector)
            axis = (-vector[0] / norm, -vector[1] / norm)
            center = incoming["junction_endpoint_network"]
            lane = other.find(f"lane[@id='{outgoing['source_lane_id']}']")
            shape = _parse_shape(lane.get("shape", ""))
            remote = root.find(f"junction[@id='{other.get('to')}']")
            remote_polygon = _parse_shape(remote.get("shape", "")) if remote is not None else []
            options, station = [], 0.0
            total = sum(math.dist(a, b) for a, b in zip(shape, shape[1:]))
            for a, b in zip(shape, shape[1:]):
                length = math.dist(a, b)
                projection = sum((b[k] - a[k]) * axis[k] for k in (0, 1))
                if length > 1e-9 and projection > length * math.cos(math.pi / 4):
                    t = sum((center[k] - a[k]) * axis[k] for k in (0, 1)) / projection
                    position = station + t * length
                    if -1e-9 <= t <= 1 + 1e-9 and 0 <= position <= min(maximum_movement_m, total - 0.2):
                        point = tuple(a[k] + min(1.0, max(0.0, t)) * (b[k] - a[k]) for k in (0, 1))
                        section = _port_section(point, [point, (point[0] + axis[0], point[1] + axis[1])], outgoing["width_m"] * length / projection)
                        kept = _slice_shape(shape, position, total)
                        probe_edge, probe_lane = deepcopy(other), deepcopy(lane)
                        probe_edge.set("shape", _shape(kept))
                        probe_lane.set("shape", _shape(kept))
                        try:
                            _safe_native_cut_port(root, probe_edge, probe_lane, "egress", maximum_movement_m=0.0)
                        except ValueError:
                            continue
                        # An oblique road mouth is wider than the perpendicular
                        # lane section used by the owner-exit check above.
                        if remote_polygon and _section_touches_polygon(section, remote_polygon):
                            continue
                        if not any(_proper_segments_intersect(*section, *fixed_port["shape"], tolerance_m=1e-6) for fixed_port in fixed):
                            # Only a shared polyline vertex is one crossing.
                            # A later visit to the same point is another cut.
                            if not any(math.dist(point, old[0]) <= 0.1 and abs(position - old[2]) <= 1e-6 for old in options):
                                options.append((point, section, position, (b[0] - a[0], b[1] - a[1])))
                station += length
            if len(options) != 1:
                result[i] = ports[i]
                reviews.append({"source_lane_id": incoming["source_lane_id"], "reason": "no_unique_reverse_road_section_preserving_official_ports"})
                break
            point, section, position, direction = options[0]
            profile_id = "paired-road:" + "|".join(sorted(group_ids))
            result[i] = {**incoming, "road_profile_id": profile_id, "road_outward_direction": axis}
            result[j] = {**outgoing, "junction_endpoint_network": point, "shape": section,
                         "native_lane_direction": direction, "road_profile_id": profile_id, "road_outward_direction": axis,
                         "basis": "native_bidirectional_common_section",
                         "adjustment": {"original_native_endpoint": outgoing["junction_endpoint_network"], "source_lane_position_m": position,
                                        "width_m": outgoing["width_m"], "source_owner_exit_preserved": True,
                                        "reason": "reverse_source_nodes_and_reference_share_the_inlet_cut"}}
            break
    return result, reviews


def _resolved_boundary_polygon(root, group):
    classification = group.get("boundary_port_classification")
    if classification is None:
        return group.get("official_boundary_shape", []), {"status": "review_required", "basis": "legacy_explicit_boundary_unverified", "reason": "official_lane_identity_not_available", "ports": []}
    join_id = str(group["join_id"])
    members = {join_id} if root.find(f"junction[@id='{join_id}']") is not None else set(map(str, group["source_node_ids"]))
    official = defaultdict(list)
    for row in classification["official_external_ports"]:
        official[row["source_lane_id"]].append(row)
    ports = []
    for edge in root.findall("edge"):
        if edge.get("function") == "internal" or (edge.get("from") in members) == (edge.get("to") in members):
            continue
        role = "ingress" if edge.get("to") in members else "egress"
        for lane_index, lane in enumerate(edge.findall("lane")):
            shape = _parse_shape(lane.get("shape", ""))
            if not lane_supports_motorized(lane) or len(shape) < 2:
                continue
            width = float(lane.get("width", "3.2"))
            a, b = shape[-2:] if role == "ingress" else shape[:2]
            native = {"source_lane_index": lane_index, "native_cut_endpoint": shape[-1] if role == "ingress" else shape[0],
                      "native_lane_direction": (b[0] - a[0], b[1] - a[1])}
            matched = [row for row in official[lane.get("id")] if row["role"] == role]
            if matched:
                for row in matched:
                    envelope_width = max(width, row["width_m"])
                    center = row["junction_endpoint_network"]
                    section = [tuple(center[i] + (point[i] - center[i]) * envelope_width / row["width_m"] for i in (0, 1)) for point in row["shape"]]
                    ports.append({**row, **native, "width_m": envelope_width, "shape": section})
            else:
                safe = _safe_native_cut_port(root, edge, lane, role,
                                             maximum_movement_m=classification.get("maximum_lane_projection_error_m", 10.0))
                ports.append({**native, "lane_id": None, "source_lane_id": lane.get("id"), "source_edge_id": edge.get("id"), "role": role,
                              **safe})
    ports, adjustment_reviews = _adjust_native_port_conflicts(root, ports, maximum_movement_m=classification.get("maximum_lane_projection_error_m", 10.0))
    report = {"basis": "actual_cut_ports_with_official_external_B_and_native_lane_widths", "ports": ports, "native_port_adjustment_reviews": adjustment_reviews}
    node = root.find(f"junction[@id='{join_id}']")
    native_boundary = _parse_shape(node.get("shape", "")) if node is not None else []
    try:
        polygon, profiles = _portal_boundary_polygon(ports, native_boundary)
        report["portal_profiles"] = profiles
        return polygon, report
    except ValueError as error:
        report["reason"] = str(error)
    report["status"] = "review_required"
    return [], report


def _portal_boundary_polygon(ports, native_boundary):
    """Keep each current road mouth intact around the native boundary.

    SUMO's NBNodeShapeComputer operates on ordered road boundary pairs, not
    a global sort of individual lane corners. Preserve that road-level order.
    """
    from .hamburg_official_intersection_plainxml import _polygon_has_self_intersection, _project_point_onto_polyline

    grouped = defaultdict(list)
    for port in ports:
        grouped[port.get("road_profile_id", port["source_edge_id"])].append(port)
    for index, left in enumerate(ports):
        for right in ports[index + 1:]:
            if left["source_edge_id"] == right["source_edge_id"]:
                continue
            overlap = _proper_segments_intersect(*left["shape"], *right["shape"], tolerance_m=1e-6)
            a, b = left["shape"]
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            if length > 0 and all(abs(dx * (p[1] - a[1]) - dy * (p[0] - a[0])) / length <= 1e-6 for p in right["shape"]):
                positions = [((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length for p in right["shape"]]
                overlap |= min(length, max(positions)) - max(0.0, min(positions)) > 0.1
            if overlap:
                raise ValueError(f"physical port profiles overlap: {left['source_edge_id']}, {right['source_edge_id']}")
    native_closed = [*native_boundary, native_boundary[0]] if len(native_boundary) >= 3 else []
    native_area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(native_closed, native_closed[1:]))
    profiles = []
    for edge_id, rows in grouped.items():
        direction = tuple(sum(row.get("road_outward_direction", tuple((-1 if row["role"] == "ingress" else 1) * value for value in row["native_lane_direction"]))[i] for row in rows) for i in (0, 1))
        normal = (-direction[1], direction[0])
        def lateral(point):
            return point[0] * normal[0] + point[1] * normal[1]
        if len({row["source_edge_id"] for row in rows}) == 1:
            sign = -1 if rows[0]["role"] == "ingress" else 1
            ordered = sorted(rows, key=lambda row: (sign * row["source_lane_index"], lateral(row["junction_endpoint_network"])))
        else:
            ordered = sorted(rows, key=lambda row: lateral(row["junction_endpoint_network"]))
        points = []
        for row in ordered:
            for point in sorted([*row["shape"], row["junction_endpoint_network"]], key=lateral):
                if not points or math.dist(point, points[-1]) > 0.1:
                    points.append(tuple(point))
        midpoint = tuple(sum(row["junction_endpoint_network"][i] for row in rows) / len(rows) for i in (0, 1))
        if native_closed:
            position = _project_point_onto_polyline(midpoint, native_closed)[0]
            order = position if native_area > 0 else -position
        else:
            order = math.atan2(direction[1], direction[0])
        profiles.append({"source_edge_id": edge_id, "points": points, "order": order,
                         "basis": "current_port_position_on_native_boundary" if native_closed else "source_road_direction_preview"})
    profiles.sort(key=lambda row: row["order"])
    polygon = []
    for profile in profiles:
        for point in profile["points"]:
            if not polygon or math.dist(point, polygon[-1]) > 0.1:
                polygon.append(point)
    if len(polygon) >= 3 and math.dist(polygon[0], polygon[-1]) <= 0.1:
        polygon.pop()
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(polygon, [*polygon[1:], polygon[0]])) if polygon else 0
    if len(polygon) < 3 or abs(area) <= 0.01 or _polygon_has_self_intersection(polygon, tolerance_m=0.1):
        raise ValueError("ordered physical port profiles do not form a simple polygon")
    return polygon, profiles


def _rebuild_join_boundaries(
    source: Path,
    output: Path,
    groups: Sequence[Mapping[str, Any]],
    *,
    netconvert_binary: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Apply external cut-port boundaries without moving internal MAP anchors."""
    source_root = ET.parse(source).getroot()
    nodes = ET.Element("nodes")
    boundaries = []
    for group in groups:
        polygon, detail = _resolved_boundary_polygon(source_root, group)
        boundaries.append({"join_id": group["join_id"], "shape": polygon, **detail})
        if polygon:
            ET.SubElement(nodes, "node", id=str(group["join_id"]), shape=_shape(polygon))
    if not len(nodes):
        shutil.copy2(source, output)
        return {"status": "not_applicable", "reason": "no_resolved_boundary_polygon", "boundaries": boundaries, "network": str(output)}
    patch_file = output.with_suffix(".boundaries.nod.xml")
    ET.indent(nodes, space="    ")
    ET.ElementTree(nodes).write(patch_file, encoding="utf-8", xml_declaration=True)
    command = [str(netconvert_binary), "--sumo-net-file", str(source), "--node-files", str(patch_file), "--offset.disable-normalization", "true", "--output-file", str(output)]
    result = run_command(command, cwd=output.parent, timeout_seconds=timeout_seconds)
    if result.returncode != 0 or not output.is_file():
        raise ValueError("netconvert could not apply the official junction boundary: " + result.stderr)
    bounded = ET.parse(output).getroot()
    from .hamburg_aerial_approach import _preserved_edge

    stable_edges = {edge.get("id"): edge for edge in bounded.findall("edge") if edge.get("function") != "internal"}
    roundtrip_file = output.with_suffix(".roundtrip.net.xml")
    check_command = [str(netconvert_binary), "--sumo-net-file", str(output), "--offset.disable-normalization", "true", "--output-file", str(roundtrip_file)]
    checked = run_command(check_command, cwd=output.parent, timeout_seconds=timeout_seconds)
    if checked.returncode != 0 or not roundtrip_file.is_file():
        raise ValueError("netconvert could not verify boundary round-trip stability: " + checked.stderr)
    reloaded_edges = {edge.get("id"): edge for edge in ET.parse(roundtrip_file).getroot().findall("edge") if edge.get("function") != "internal"}
    unstable = [edge_id for edge_id, edge in stable_edges.items() if edge_id not in reloaded_edges or not _preserved_edge(edge, reloaded_edges[edge_id])]
    if unstable or set(stable_edges) != set(reloaded_edges):
        raise ValueError("boundary lane geometry is not stable under netconvert reload: " + ", ".join(unstable))
    basis = "external_cut_ports_and_unverified_legacy_shapes" if any(row["basis"] == "legacy_explicit_boundary_unverified" for row in boundaries) else "actual_external_cut_ports"
    return {"status": "pass", "basis": basis, "boundaries": boundaries, "node_patch": str(patch_file), "network": str(output), "command": command, "stdout": result.stdout, "stderr": result.stderr,
            "cut_geometry": {"roundtrip_stable": True, "tolerance_m": 0.1, "command": check_command, "roundtrip_network": str(roundtrip_file)}}


def _select_join_groups(
    root: ET.Element,
    binding: Mapping[str, Any],
    plans: Mapping[str, Mapping[str, Any]],
    *,
    short_edge_m: float = 20.0,
    maximum_node_to_movement_m: float = 15.0,
    maximum_lane_projection_error_m: float = 10.0,
    minimum_lane_match_margin_m: float = 0.5,
) -> list[dict[str, Any]]:
    nodes = {
        junction.attrib["id"]: (
            float(junction.attrib.get("x", "0")),
            float(junction.attrib.get("y", "0")),
        )
        for junction in root.findall("junction")
        if not junction.attrib["id"].startswith(":")
    }
    node_shapes = {junction.attrib["id"]: _parse_shape(junction.get("shape", "")) for junction in root.findall("junction") if junction.attrib["id"] in nodes}
    node_faces = {node_id: [shape] if len(shape) >= 3 else [] for node_id, shape in node_shapes.items()}
    for edge in root.findall("edge"):
        if edge.get("function") != "internal":
            continue
        owner = edge.get("id", "")[1:].rsplit("_", 1)[0]
        if owner not in node_faces:
            continue
        for lane in edge.findall("lane"):
            shape = _parse_shape(lane.get("shape", ""))
            shape = [point for index, point in enumerate(shape) if index == 0 or math.dist(point, shape[index - 1]) > 1e-9]
            if lane_supports_motorized(lane) and len(shape) >= 2:
                node_faces[owner].extend(_lane_face_primitives(shape, float(lane.get("width", "3.2"))))
    edge_to = {}
    neighbors: dict[str, set[str]] = defaultdict(set)
    for edge in root.findall("edge"):
        if edge.attrib.get("function") == "internal" or "from" not in edge.attrib:
            continue
        source, target = edge.attrib["from"], edge.attrib["to"]
        edge_to[edge.attrib["id"]] = target
        length = min(
            (float(lane.attrib.get("length", "inf")) for lane in edge.findall("lane")),
            default=math.inf,
        )
        if length <= short_edge_m:
            neighbors[source].add(target)
            neighbors[target].add(source)
    binding_by_node = {}
    owners: dict[tuple[str, str], str] = {}
    for row in binding.get("bindings", []):
        if not isinstance(row, Mapping) or not row.get("node_id"):
            raise ValueError("each cluster binding requires a node id")
        node_id = str(row["node_id"])
        if node_id in binding_by_node:
            raise ValueError(f"duplicate node binding: {node_id}")
        binding_by_node[node_id] = row
        if node_id not in plans:
            continue
        tls_ids = row.get("tls_ids")
        if not isinstance(tls_ids, list) or not tls_ids or any(not str(value).strip() for value in tls_ids):
            raise ValueError(f"planned node {node_id} requires source TLS ids")
        identities = [("TLS", str(value)) for value in tls_ids]
        if row.get("cluster_id"):
            identities.append(("cluster", str(row["cluster_id"])))
        for identity in identities:
            previous = owners.setdefault(identity, node_id)
            if previous != node_id:
                raise ValueError(f"source {identity[0]} {identity[1]} belongs to multiple planned nodes: {previous}, {node_id}")
    if any(node_id not in binding_by_node for node_id in plans):
        raise ValueError("every planned intersection requires a source junction binding")
    all_connections = root.findall("connection")
    declared_tls_owners: dict[str, set[str]] = defaultdict(set)
    declared_node_owners: dict[str, set[str]] = defaultdict(set)
    for declared_id, row in binding_by_node.items():
        for tls_id in row.get("tls_ids", []) if isinstance(row.get("tls_ids"), list) else []:
            declared_tls_owners[str(tls_id)].add(declared_id)
            if str(tls_id) in nodes:
                declared_node_owners[str(tls_id)].add(declared_id)
    for connection in all_connections:
        owner = edge_to.get(connection.get("from", ""))
        if owner is not None:
            declared_node_owners[owner].update(declared_tls_owners.get(connection.get("tl", ""), set()))
    used: set[str] = set()
    groups = []
    for node_id in plans:
        movements_by_part = _movements_by_part(plans[node_id])
        official_points = _official_lane_boundary_points(plans[node_id], root)
        official_sections = _official_boundary_sections(plans[node_id], official_points)
        core_paths = _official_internal_paths(plans[node_id], root, official_points)
        boundaries = {}
        boundary_owners = {}
        anchor_owners = {}
        part_sections = {}
        movement_owners = {}
        for part, movements in movements_by_part.items():
            lane_ids = {str(row[key]) for row in movements for key in ("ingress_lane_id", "egress_lane_id")}
            boundary_points = [official_points[lane_id] for lane_id in sorted(lane_ids) if lane_id in official_points]
            boundaries[part] = []
            part_sections[part] = [official_sections[lane_id] for lane_id in sorted(lane_ids) if lane_id in official_sections]
            if len(boundary_points) >= 3 and len(boundary_points) == len(lane_ids):
                center = tuple(sum(point[i] for point in boundary_points) / len(boundary_points) for i in (0, 1))
                try:
                    boundaries[part] = _angular_endpoint_polygon(boundary_points, center=center, tolerance_m=0.1)
                except ValueError:
                    pass
            boundary_owners[part] = {
                candidate for candidate, faces in node_faces.items()
                if any(
                    any(_boundary_distance(point, shape) <= 1e-6 for point in boundaries[part])
                    or any(_section_touches_polygon(section["shape"], shape) for section in part_sections[part])
                    for shape in faces
                )
            }
            part_paths = [core_paths["paths"][key] for row in movements for key in [(str(row["ingress_lane_id"]), str(row["egress_lane_id"]))] if key in core_paths["paths"]]
            movement_owners[part] = {
                candidate for candidate, faces in node_faces.items()
                if any(_section_touches_polygon((a, b), face) for path in part_paths for a, b in zip(path, path[1:]) for face in faces)
            }
            anchor_owners[part] = set(boundary_owners[part])
            boundary_owners[part] |= movement_owners[part]
        centroids = {
            part: tuple(sum(point[i] for point in boundaries[part]) / len(boundaries[part]) for i in (0, 1)) if boundaries[part] else _movement_centroid(movements, (0.0, 0.0))
            for part, movements in movements_by_part.items()
        }
        tls_ids = set(str(value) for value in binding_by_node[node_id]["tls_ids"])
        tls_nodes = {value for value in tls_ids if value in nodes}
        tls_nodes.update(
            edge_to.get(connection.attrib.get("from", ""), "")
            for connection in all_connections
            if connection.attrib.get("tl") in tls_ids
        )
        tls_nodes.discard("")
        assigned: dict[str, set[str]] = defaultdict(set)
        for tls_node in tls_nodes:
            assigned[
                min(
                    centroids,
                    key=lambda part: (
                        0.0 if tls_node in boundary_owners[part] else _boundary_distance(nodes[tls_node], boundaries[part]) if boundaries[part] else math.dist(nodes[tls_node], centroids[part]),
                        math.dist(nodes[tls_node], centroids[part]),
                    ),
                )
            ].add(tls_node)
        for part, movements in sorted(movements_by_part.items()):
            boundary = boundaries[part]
            local_lines = [
                movement["selected_shape_network"]
                for movement in movements
            ]
            eligible = {
                candidate
                for candidate, point in nodes.items()
                if _distance_to_lines(point, local_lines) <= maximum_node_to_movement_m
            }
            initial = set(assigned.get(part, set()))
            excluded = []
            active_neighbors = neighbors
            if boundary:
                margin = max((float(lane.get("width", "3.2")) / 2 for edge in root.findall("edge") if edge.get("from") in initial or edge.get("to") in initial for lane in edge.findall("lane") if lane_supports_motorized(lane)), default=1.6)
                eligible = {candidate for candidate in nodes if _boundary_distance(nodes[candidate], boundary) <= margin or candidate in boundary_owners[part]}
                excluded = sorted(initial - eligible)
                initial &= eligible
                active_neighbors = defaultdict(set)
                for edge in root.findall("edge"):
                    source, target = edge.get("from"), edge.get("to")
                    if source not in eligible or target not in eligible:
                        continue
                    lane_shapes = [_parse_shape(lane.get("shape", "")) for lane in edge.findall("lane") if lane_supports_motorized(lane)]
                    lane_shapes = [shape for shape in lane_shapes if len(shape) >= 2]
                    if not lane_shapes:
                        continue
                    samples = [
                        (a[0] + (b[0] - a[0]) * t / steps, a[1] + (b[1] - a[1]) * t / steps)
                        for shape in lane_shapes
                        for a, b in zip(shape, shape[1:])
                        for steps in [max(1, math.ceil(math.dist(a, b) / max(margin, 0.1)))]
                        for t in range(steps + 1)
                    ]
                    endpoint_surfaces = [shape for value in (source, target) if value in boundary_owners[part] for shape in node_faces[value]]
                    if all(_boundary_distance(point, boundary) <= margin or any(_boundary_distance(point, shape) <= 1e-6 for shape in endpoint_surfaces) for point in samples):
                        active_neighbors[source].add(target)
                        active_neighbors[target].add(source)
            group = set(initial)
            if not group and eligible:
                group.add(min(eligible, key=lambda value: math.dist(nodes[value], centroids[part])))
            queue = deque(group)
            while queue:
                current = queue.popleft()
                for neighbor in active_neighbors[current]:
                    if (
                        neighbor in eligible
                        and neighbor not in group
                        and neighbor not in used
                        and (neighbor not in tls_nodes or neighbor in initial)
                    ):
                        group.add(neighbor)
                        queue.append(neighbor)
            # Parallel carriageways can be disconnected in the motor graph.
            # Supplement the original seed component only with nodes directly
            # witnessed by this part's official B sections or B-to-B paths.
            # Do not expand these additions through unproved nearby branches.
            evidence_components, component_reviews = [], []
            pending = eligible & boundary_owners[part]
            while pending:
                seed = min(pending)
                component, queue = {seed}, deque([seed])
                pending.remove(seed)
                while queue:
                    for neighbor in active_neighbors[queue.popleft()]:
                        if neighbor in pending:
                            pending.remove(neighbor)
                            component.add(neighbor)
                            queue.append(neighbor)
                additions = component - group
                conflicting_parts = sorted(other for other in boundary_owners if other != part and component & boundary_owners[other])
                conflicting_intersections = sorted({owner for value in component for owner in declared_node_owners[value]} - {node_id})
                reserved = component & used
                other_part_tls = component & (tls_nodes - initial)
                record = {"source_node_ids": sorted(component), "added_source_node_ids": sorted(additions),
                          "official_B_owner_node_ids": sorted(component & anchor_owners[part]),
                          "official_drive_line_owner_node_ids": sorted(component & movement_owners[part]),
                          "basis": "same_part_official_geometry_witnessed_component"}
                if additions and (conflicting_parts or conflicting_intersections or reserved or other_part_tls):
                    component_reviews.append({**record, "reason": "component_has_conflicting_junction_ownership",
                                              "conflicting_parts": conflicting_parts, "conflicting_intersections": conflicting_intersections,
                                              "already_used_node_ids": sorted(reserved), "other_part_tls_node_ids": sorted(other_part_tls)})
                else:
                    group.update(component)
                    evidence_components.append(record)
            group -= used
            used.update(group)
            if group:
                record = {
                        "node_id": node_id,
                        "intersection_part": part,
                        "join_id": f"LSA{node_id}_part{part}" if len(group) > 1 else next(iter(group)),
                        "source_node_ids": sorted(group),
                        "assigned_tls_node_count": len(initial),
                        "selected_movement_count": len(movements),
                        "official_boundary_shape": boundary,
                        "boundary_excluded_node_ids": excluded,
                        "boundary_anchor_owner_node_ids": sorted(group & anchor_owners[part]),
                        "boundary_port_sections": part_sections[part],
                        "official_movement_owner_node_ids": sorted(group & movement_owners[part]),
                        "evidence_components": evidence_components,
                        "component_selection_reviews": component_reviews,
                        "unusable_official_core_curves": core_paths["unusable"],
                    }
                classification = _classify_boundary_ports(
                    root, plans[node_id], record, official_points,
                    maximum_lane_projection_error_m=maximum_lane_projection_error_m,
                    minimum_lane_match_margin_m=minimum_lane_match_margin_m,
                )
                if classification is not None:
                    record["selection_boundary_shape"] = boundary
                    record["boundary_port_classification"] = classification
                    record["official_control_sections"] = record["boundary_port_sections"]
                    record["boundary_port_sections"] = classification["official_external_ports"]
                    record["official_boundary_shape"], _ = _resolved_boundary_polygon(root, record)
                groups.append(record)
    return groups


def _approach_lane_identities(source_root, approach_rebuild, groups):
    constructed_ingress, lane_origins, changed_edge_ids = {}, {}, []
    original_lane_ids = {lane.get("id") for edge in source_root.findall("edge") for lane in edge.findall("lane")}
    for section in approach_rebuild.get("approaches", []):
        key = (str(section["node_id"]), str(section["intersection_part"]))
        edge_id = str(section["downstream_edge_id"])
        changed_edge_ids.append(edge_id)
        for old_index, current_index in section.get("source_lane_to_downstream_lane", {}).items():
            original_id = f"{section['source_edge_id']}_{old_index}"
            lane_origins[f"{edge_id}_{current_index}"] = original_id if original_id in original_lane_ids else None
        for official_id in section["pocket_lane_ids"]:
            lane_origins[f"{edge_id}_{section['official_lane_indices'][official_id]}"] = None
        if any((str(group["node_id"]), str(group["intersection_part"])) == key and str(group["join_id"]) == section["original_to"] for group in groups):
            bound = constructed_ingress.setdefault(key, {})
            for lane_id, index in section["official_lane_indices"].items():
                lane_id, value = str(lane_id), (edge_id, int(index))
                if lane_id in bound and bound[lane_id] != value:
                    raise ValueError("official lane identity refers to multiple rebuilt approaches")
                bound[lane_id] = value
    return constructed_ingress, lane_origins, changed_edge_ids


def _prepare_context_joins(*, source_net, context_groups, official_groups, output_dir, netconvert_binary, sumo_binary, timeout_seconds, seed, adjacent_geometry_junction_ids=()):
    """Rebuild declared unregulated context before fitting official junctions."""
    from .junction_boundary_rebuild import restore_joined_boundary_connections

    root = ET.parse(source_net).getroot()
    nodes = {node.get("id"): node for node in root.findall("junction")}
    protected = {str(node) for group in official_groups for node in group["source_node_ids"]}
    members = {node for group in context_groups.values() for node in group}
    if members & protected:
        raise ValueError("context_joins must not overlap official junction groups")
    if not members <= set(nodes) or any(nodes[node].get("type") not in {"priority", "priority_stop", "right_before_left", "left_before_right", "allway_stop", "zipper", "unregulated"} for node in members):
        raise ValueError("context_joins requires existing junctions without signals or rail control")
    if any(join_id in nodes and join_id not in group for join_id, group in context_groups.items()):
        raise ValueError("context_joins target id collides with a retained junction")
    edge_targets = {edge.get("id"): edge.get("to") for edge in root.findall("edge")}
    if any(connection.get("tl") and edge_targets.get(connection.get("from")) in members for connection in root.findall("connection")):
        raise ValueError("context_joins cannot contain a controlled connection")
    output_dir.mkdir(parents=True)
    joins = output_dir / "context-joins.nod.xml"
    _write_join_file(joins, [{"join_id": key, "source_node_ids": values} for key, values in context_groups.items()], traffic_light=False)
    joined = output_dir / "joined.net.xml"
    command = run_command([netconvert_binary, "--sumo-net-file", str(source_net), "--node-files", str(joins), "--offset.disable-normalization", "true", "--seed", str(seed), "--output-file", str(joined)], cwd=output_dir, timeout_seconds=timeout_seconds)
    (output_dir / "netconvert.log").write_text(command.stdout + command.stderr, encoding="utf-8")
    if command.returncode != 0 or not joined.is_file():
        raise ValueError("netconvert could not build the declared context joins")
    report = restore_joined_boundary_connections(
        source_net=source_net, joined_net=joined, groups=context_groups,
        output_dir=output_dir / "boundary-restoration", expected_source_sha256=file_sha256(source_net),
        expected_joined_sha256=file_sha256(joined), netconvert_binary=netconvert_binary,
        sumo_binary=sumo_binary, timeout_seconds=timeout_seconds,
        adjacent_geometry_junction_ids=adjacent_geometry_junction_ids)
    if report["status"] != "pass":
        raise ValueError("context joins did not preserve boundary paths or outside junctions")
    return {**report, "groups": context_groups, "join_command": command.to_dict(), "join_file": {"path": str(joins), "sha256": file_sha256(joins)}}


def _write_join_file(path: Path, groups: Sequence[Mapping[str, Any]], *, traffic_light: bool = True) -> None:
    root = ET.Element("nodes")
    for group in groups:
        if len(group["source_node_ids"]) < 2:
            continue
        ET.SubElement(
            root,
            "join",
            {
                "id": str(group["join_id"]),
                "type": "traffic_light" if traffic_light else "priority",
                **({"tl": str(group["join_id"])} if traffic_light else {}),
                "reset": "false",
                "nodes": " ".join(str(value) for value in group["source_node_ids"]),
            },
        )
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _write_movement_candidate(
    *,
    joined_net: Path,
    plans: Mapping[str, Mapping[str, Any]],
    groups: Sequence[Mapping[str, Any]],
    skipped_join_ids: set[str],
    output_file: Path,
    maximum_anchor_projection_error_m: float,
    maximum_lane_projection_error_m: float = 10.0,
    minimum_lane_match_margin_m: float = 0.5,
    netconvert_binary: str = "netconvert",
    timeout_seconds: float = 240.0,
    original_net: Path | None = None,
    constructed_ingress: Mapping[tuple[str, str], Mapping[str, tuple[str, int]]] | None = None,
    lane_origins: Mapping[str, str | None] | None = None,
    identity_changed_edges: Sequence[str] = (),
    source_lane_change_evidence: list[dict[str, Any]] | None = None,
    sumo_binary: str = "sumo",
    seed: int = 104,
    junction_contours: str = "preserve",
) -> dict[str, Any]:
    """Write whole connection curves to netconvert, never only the first via."""
    root = ET.parse(joined_net).getroot()
    source_root = ET.parse(original_net or joined_net).getroot()
    external = {
        (edge.attrib["id"], index): _parse_shape(lane.get("shape", ""))
        for edge in root.findall("edge")
        if edge.get("function") != "internal"
        for index, lane in enumerate(edge.findall("lane"))
        if lane_supports_motorized(lane) and len(_parse_shape(lane.get("shape", ""))) >= 2
    }
    external_modes = {
        (edge.attrib["id"], index): _lane_motorized_modes(lane)
        for edge in root.findall("edge") if edge.get("function") != "internal"
        for index, lane in enumerate(edge.findall("lane"))
    }
    edges = {edge.get("id"): edge for edge in root.findall("edge") if edge.get("function") != "internal"}
    group_by_key = {(str(row["node_id"]), str(row["intersection_part"])): row for row in groups}
    patch = ET.Element("connections")
    required = []
    unresolved = []
    geometry_rejected = []
    lane_bindings = []
    part_reports = []
    patched_sources: dict[tuple[str, int, str, int], str] = {}
    for node_id, plan in plans.items():
        for part, movements in _movements_by_part(plan).items():
            group = group_by_key.get((node_id, part))
            if group is None:
                unresolved.extend({"node_id": node_id, "intersection_part": part, "movement_id": str(row["movement_id"]), "reason": "physical_part_unbound"} for row in movements)
                continue
            junction_id = str(group["join_id"])
            incoming = {key: shape for key, shape in external.items() if edges[key[0]].get("to") == junction_id}
            outgoing = {key: shape for key, shape in external.items() if edges[key[0]].get("from") == junction_id}
            internal = {role: [row["lane_id"] for row in group.get("boundary_port_classification", {}).get("official_internal_anchors", []) if row["role"] == role] for role in ("ingress", "egress")}
            ingress = _bind_official_lanes(plan["lanes"], movements, incoming, role="ingress", max_error_m=maximum_lane_projection_error_m, margin_m=minimum_lane_match_margin_m, candidate_modes=external_modes, internal_lane_ids=internal["ingress"])
            _keep_constructed_lane_identity(ingress, (constructed_ingress or {}).get((node_id, part), {}), incoming)
            egress = _bind_official_lanes(plan["lanes"], movements, outgoing, role="egress", max_error_m=maximum_lane_projection_error_m, margin_m=minimum_lane_match_margin_m, candidate_modes=external_modes, internal_lane_ids=internal["egress"])
            for role, matched, available in (("ingress", ingress, incoming), ("egress", egress, outgoing)):
                _keep_boundary_lane_identity(matched, group, available, role=role, lane_origins=lane_origins or {},
                    changed_edge_ids=identity_changed_edges, maximum_error_m=maximum_lane_projection_error_m)
            lane_bindings.append({"node_id": node_id, "intersection_part": part, "junction_id": junction_id, "ingress": ingress, "egress": egress})
            expected_keys = set()
            expected_exit_modes = defaultdict(set)
            for movement in movements:
                record = {
                    "node_id": node_id,
                    "intersection_part": part,
                    "join_id": junction_id,
                    "movement_id": str(movement["movement_id"]),
                    "ingress_lane_id": str(movement["ingress_lane_id"]),
                    "egress_lane_id": str(movement["egress_lane_id"]),
                    "selected_source": str(movement["selected_source"]),
                }
                official_lanes = {str(lane["lane_id"]): lane for lane in plan["lanes"]}
                restrictions = [set(official_lanes[lane_id]["allowed_vehicle_classes"]) for lane_id in (record["ingress_lane_id"], record["egress_lane_id"]) if official_lanes.get(lane_id, {}).get("allowed_vehicle_classes") is not None]
                record["allowed_vehicle_classes"] = sorted(set.intersection(*restrictions)) if restrictions else None
                record["revocable_lane_assumption"] = "enabled_for_topology_test;activation_not_replayed" if any(official_lanes.get(lane_id, {}).get("revocable") for lane_id in (record["ingress_lane_id"], record["egress_lane_id"])) else None
                source = ingress["bindings"].get(record["ingress_lane_id"])
                target = egress["bindings"].get(record["egress_lane_id"])
                if record["allowed_vehicle_classes"] == []:
                    unresolved.append({**record, "reason": "official_vehicle_permissions_conflict"})
                    continue
                if source is None or target is None:
                    unresolved.append({**record, "reason": "official_lane_binding_unresolved"})
                    continue
                key = (*source, *target)
                record["sumo_connection"] = list(key)
                expected_keys.add(key)
                modes = external_modes[source] & external_modes[target]
                if record["allowed_vehicle_classes"] is not None:
                    modes &= set(record["allowed_vehicle_classes"])
                expected_exit_modes[source, target[0]].update(modes)
                required.append(record)
                anchored, error = fit_movement_shape_to_anchors(movement["selected_shape_network"], start=external[source][-1], end=external[target][0])
                geometry_source = "selected_curve"
                if (error > maximum_anchor_projection_error_m and movement["selected_source"] == "aerial_trace"
                        and movement.get("official_shape_network")):
                    official_anchored, official_error = fit_movement_shape_to_anchors(
                        movement["official_shape_network"], start=external[source][-1], end=external[target][0])
                    record["selected_curve_anchor_projection_error_sum_m"] = error
                    record["official_curve_anchor_projection_error_sum_m"] = official_error
                    if official_error <= maximum_anchor_projection_error_m:
                        anchored, error = official_anchored, official_error
                        geometry_source = "official_map_curve"
                record["anchor_projection_error_sum_m"] = round(error, 6)
                attrs = {"from": source[0], "fromLane": str(source[1]), "to": target[0], "toLane": str(target[1])}
                if record["allowed_vehicle_classes"] is not None:
                    attrs["allow"] = " ".join(record["allowed_vehicle_classes"])
                if error > maximum_anchor_projection_error_m:
                    geometry_rejected.append({**record, "reason": "movement_anchor_fit_exceeds_limit", "geometry_source": "netconvert"})
                elif junction_id not in skipped_join_ids:
                    attrs["shape"] = _shape(anchored)
                    patched_sources[key] = geometry_source
                ET.SubElement(patch, "connection", attrs)
            # Matching every official lane does not make MAP an exhaustive
            # prohibition list. Remove only redundant targets on the same
            # exit road; unlisted road turns still need the source-path audit.
            mapped_in = set(ingress["bindings"].values())
            mapped_out = set(egress["bindings"].values())
            direct_scope_complete = (
                all(str(row["ingress_lane_id"]) in ingress["bindings"] for row in movements)
                and all(str(row["egress_lane_id"]) in egress["bindings"] for row in movements)
            )
            for connection in root.findall("connection"):
                key = _connection_key(connection)
                if not direct_scope_complete or key[:2] not in mapped_in or key[2:] not in mapped_out or key in expected_keys:
                    continue
                existing_modes = external_modes[key[:2]] & external_modes[key[2:]] & _lane_motorized_modes(connection)
                # A bus-only alternative cannot replace passenger access.
                if existing_modes and existing_modes <= expected_exit_modes.get((key[:2], key[2]), set()):
                    ET.SubElement(patch, "delete", {name: connection.attrib[name] for name in ("from", "fromLane", "to", "toLane")})
            part_reports.append({"node_id": node_id, "intersection_part": part, "join_id": junction_id, "official_movement_count": len(movements), "required_connection_count": len(expected_keys), "direct_official_scope_complete": direct_scope_complete})

    composition_groups = [group for group in groups if any(str(group["node_id"]) == row["node_id"] and str(group["intersection_part"]) == row["intersection_part"] for row in unresolved)]
    boundary_bindings = {row["junction_id"]: {role: row[role]["bindings"] for role in ("ingress", "egress")} for row in lane_bindings}
    composition_args = dict(plans=plans, groups=composition_groups, boundary_bindings=boundary_bindings,
        current_lane_to_original_lane=lane_origins, maximum_lane_error_m=maximum_lane_projection_error_m,
        minimum_match_margin_m=minimum_lane_match_margin_m,
        maximum_source_anchor_error_m=maximum_anchor_projection_error_m)
    composition = compose_official_movements(source_root, root, **composition_args) if composition_groups else None
    composed_pairs = set()
    if composition is not None:
        proposed = {}
        composed_permissions = defaultdict(set)
        for path in composition["boundary_paths"]:
            key = tuple(path["connection"])
            composed_pairs.add(key)
            composed_permissions[key].update(path["allowed_vehicle_classes"])
            error = path["connection_anchor_error_m"]
            previous_error = proposed.get(key, {}).get("connection_anchor_error_m")
            if key not in proposed or (error if error is not None else math.inf) < (previous_error if previous_error is not None else math.inf):
                proposed[key] = path
        # Official records can describe portions of a complete joined path.
        # Such a path must not be removed by the single-step comparison above.
        for deletion in list(patch.findall("delete")):
            if _connection_key(deletion) in composed_pairs:
                patch.remove(deletion)
        patched_keys = {_connection_key(row) for row in patch.findall("connection")}
        for key, path in proposed.items():
            if key in patched_keys:
                continue
            attrs = {"from": key[0], "fromLane": str(key[1]), "to": key[2], "toLane": str(key[3])}
            shape, error = path["connection_shape_network"], path["connection_anchor_error_m"]
            if shape and error is not None and error <= maximum_anchor_projection_error_m and path["join_id"] not in skipped_join_ids:
                attrs["shape"] = _shape(shape)
                patched_sources[key] = "selected_curve"
            ET.SubElement(patch, "connection", attrs)
        for connection in patch.findall("connection"):
            key = _connection_key(connection)
            if key in composed_permissions and composed_permissions[key] != external_modes[key[:2]] & external_modes[key[2:]]:
                connection.set("allow", " ".join(sorted(composed_permissions[key])))

    patch_file = output_file.with_suffix(".con.xml")
    command = [str(netconvert_binary), "--sumo-net-file", str(joined_net), "--connection-files", str(patch_file), "--offset.disable-normalization", "true", "--output-file", str(output_file)]
    commands = []
    removed_source_fanouts = []
    restored_source_permissions = []
    change_evidence = source_lane_change_evidence if source_lane_change_evidence is not None else []
    source_members = {str(group["join_id"]): group["source_node_ids"] for group in groups}
    support_args = dict(group_source_node_ids=source_members,
        official_required_pairs=[*[row["sumo_connection"] for row in required], *composed_pairs],
        current_lane_to_original_lane=lane_origins, identity_changed_edges=identity_changed_edges,
        source_lane_change_evidence=change_evidence)
    # Reuse the same joined source each time: the compiled junction may trim
    # its approaches, so align full curves to those endpoints before rebuilding.
    for iteration in range(4):
        ET.indent(patch, space="    ")
        ET.ElementTree(patch).write(patch_file, encoding="utf-8", xml_declaration=True)
        result = run_command(command, cwd=output_file.parent, timeout_seconds=timeout_seconds)
        commands.append({"command": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode != 0 or not output_file.is_file():
            raise ValueError("netconvert could not compile the official connection candidate: " + result.stderr)
        compiled_root = ET.parse(output_file).getroot()
        compiled_lanes = {
            (edge.attrib["id"], index): _parse_shape(lane.get("shape", ""))
            for edge in compiled_root.findall("edge") if edge.get("function") != "internal"
            for index, lane in enumerate(edge.findall("lane"))
        }
        source_support = audit_source_movement_support(source_root, compiled_root, **support_args)
        if original_net is not None and iteration == 0:
            before = len(change_evidence)
            for row in source_support["unresolved"]:
                start, target = row.get("original_from_lane"), row.get("original_to_lane")
                if not start or not target:
                    continue
                members = source_members[row["junction_id"]]
                modes = set(row["candidate_vehicle_classes"]) - set(row.get("supported_vehicle_classes", []))
                tested = {result["vehicle_class"] for report in change_evidence if report["start_lane"] == start and report["target_lane"] == target and set(report["source_node_ids"]) == set(members) for result in report["results"]}
                if modes - tested:
                    change_evidence.append(probe_source_interior_lane_changes(
                        source_net=original_net, start_lane=start, target_lane=target,
                        source_node_ids=members, vehicle_classes=sorted(modes - tested),
                        output_dir=output_file.parent / f"{output_file.stem}-source-lane-change-{len(change_evidence):04d}",
                        sumo_binary=sumo_binary, seed=seed, timeout_seconds=timeout_seconds))
            if len(change_evidence) != before:
                source_support = audit_source_movement_support(source_root, compiled_root, **support_args)
        deletions = {_connection_key(row) for row in patch.findall("delete")}
        redundant = [pair for pair in source_support["unsupported_redundant_pairs"] if tuple(pair) not in deletions]
        # A removed interior bus road must not become an unrestricted turn.
        # Keep the turn and the proved modes; official new movements are
        # protected by the source audit and are not restricted here.
        permissions = [row for row in source_support["unresolved"]
                       if row["reason"] == "candidate_permissions_exceed_proved_source_permissions"
                       and row.get("supported_vehicle_classes")]
        changes = []
        for connection in patch.findall("connection"):
            if not connection.get("shape"):
                continue
            key = _connection_key(connection)
            start, end = compiled_lanes[key[:2]][-1], compiled_lanes[key[2:]][0]
            old_shape = _parse_shape(connection.attrib["shape"])
            if max(math.dist(old_shape[0], start), math.dist(old_shape[-1], end)) > 0.05:
                changes.append((connection, reanchor_movement_shape(old_shape, start=start, end=end)))
        if not changes and not redundant and not permissions or iteration == 3:
            break
        compiled_connections = {_connection_key(row): row for row in compiled_root.findall("connection")}
        patched_connections = {_connection_key(row): row for row in patch.findall("connection")}
        for row in permissions:
            pair = tuple(row["connection"])
            connection = patched_connections.get(pair)
            if connection is None:
                original = compiled_connections[pair]
                connection = ET.SubElement(patch, "connection", {name: original.attrib[name]
                    for name in ("from", "fromLane", "to", "toLane", "allow", "disallow") if name in original.attrib})
            denied = set(row["candidate_vehicle_classes"]) - set(row["supported_vehicle_classes"])
            allowed = set(connection.get("allow", "").split())
            if allowed and "all" not in allowed:
                connection.set("allow", " ".join(sorted(allowed - denied - set(connection.get("disallow", "").split()))))
                connection.attrib.pop("disallow", None)
            else:
                connection.attrib.pop("allow", None)
                connection.set("disallow", " ".join(sorted(denied | set(connection.get("disallow", "").split()))))
            restored_source_permissions.append({"connection": list(pair),
                "previous_vehicle_classes": row["candidate_vehicle_classes"],
                "allowed_vehicle_classes": row["supported_vehicle_classes"],
                "basis": "original_source_paths_and_verified_lane_changes;nonmotorized_permissions_unchanged"})
        for pair in redundant:
            ET.SubElement(patch, "delete", {"from": pair[0], "fromLane": str(pair[1]), "to": pair[2], "toLane": str(pair[3])})
            removed_source_fanouts.append(pair)
        for connection, shape in changes:
            connection.set("shape", _shape(shape))

    contours = {"mode": "preserve", "status": "not_applicable", "parts": [],
                "accepted_junction_ids": [], "rejected_junction_ids": []}
    if junction_contours == "guarded":
        compiled_root, contours = _compile_junction_contours(
            compiled_root, command=command, groups=[row for row in groups if row["join_id"] not in skipped_join_ids],
            output_file=output_file, timeout_seconds=timeout_seconds)
        # The final compilation owns internal lane identities and full paths.
        source_support = audit_source_movement_support(source_root, compiled_root, **support_args)
    elif junction_contours != "preserve":
        raise ValueError("junction_contours must be preserve or guarded")
    tree = ET.ElementTree(compiled_root)
    ET.indent(tree, space="    ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    if composition is not None:
        composition = compose_official_movements(source_root, compiled_root, **composition_args)
        remaining = []
        for row in unresolved:
            paths = [path for path in composition["boundary_paths"] if path["node_id"] == row["node_id"] and path["intersection_part"] == row["intersection_part"] and any(segment["movement_id"] == row["movement_id"] and segment["official_lane_pair"] == [row["ingress_lane_id"], row["egress_lane_id"]] for segment in path["movement_segments"])]
            if not paths:
                remaining.append(row)
                continue
            paths.sort(key=lambda path: (path["status"] != "pass", path["connection"]))
            required.append({**row, "reason": "official_segments_composed_after_join",
                "sumo_connection": paths[0]["connection"],
                "sumo_connections": [path["connection"] for path in paths],
                "composition_witness_ids": [path["witness_id"] for path in paths],
                "composition_geometry_status": paths[0]["geometry_status"],
                "allowed_vehicle_classes": paths[0]["allowed_vehicle_classes"]})
        unresolved = remaining
    final_edges = {edge.get("id"): edge for edge in compiled_root.findall("edge") if edge.get("function") != "internal"}
    preserved = set(edges) == set(final_edges) and all(
        edge.get("from") == final_edges[edge_id].get("from")
        and edge.get("to") == final_edges[edge_id].get("to")
        and len(edge.findall("lane")) == len(final_edges[edge_id].findall("lane"))
        for edge_id, edge in edges.items()
    )
    scoped_junctions = {str(group["join_id"]) for group in groups}
    actual = {
        _connection_key(connection): connection
        for connection in compiled_root.findall("connection")
        if connection.get("from") in final_edges
        and final_edges[connection.get("from")].get("to") in scoped_junctions
        and _connection_key(connection)[:2] in external
        and _connection_key(connection)[2:] in external
    }
    required_keys = {tuple(row["sumo_connection"]) for row in required} | composed_pairs
    missing = [row for row in required if tuple(row["sumo_connection"]) not in actual]
    missing.extend({"sumo_connection": list(key), "reason": "composed_boundary_connection_missing"} for key in sorted(composed_pairs - set(actual)) if not any(tuple(row["sumo_connection"]) == key for row in missing))
    extra = [list(key) for key in sorted(set(actual) - required_keys)]
    unexplained_extra = [row["connection"] for row in source_support["unresolved"]] + source_support["unsupported_redundant_pairs"]
    materialized = []
    for row in required:
        key = tuple(row["sumo_connection"])
        connection = actual.get(key)
        if connection is not None:
            composed = bool(row.get("composition_witness_ids"))
            materialized.append({**row,
                "geometry_source": patched_sources.get(key, "netconvert"),
                "internal_lane_id": "" if composed else connection.get("via", "").split()[0] if connection.get("via") else "",
                "signal_binding_status": "composed_submovement_requires_control_mapping" if composed else "direct_movement"})
    composition_review = [path for path in (composition or {}).get("boundary_paths", []) if path["status"] != "pass"]
    boundary_connections = {tuple(row["sumo_connection"]): row for row in required}
    for path in (composition or {}).get("boundary_paths", []):
        key = tuple(path["connection"])
        boundary_connections.setdefault(key, {"node_id": path["node_id"], "intersection_part": path["intersection_part"], "join_id": path["join_id"], "movement_id": path["witness_id"], "sumo_connection": path["connection"], "allowed_vehicle_classes": path["allowed_vehicle_classes"]})
    audit = {
        "status": "pass" if not (missing or unexplained_extra or unresolved or composition_review) and preserved else "review_required" if preserved else "blocked",
        "required": required,
        "actual": [list(key) for key in sorted(actual)],
        "missing": missing,
        "extra": extra,
        "unexplained_extra": unexplained_extra,
        "source_supported_extra": source_support["source_backed_extra"],
        "removed_source_unsupported_fanouts": removed_source_fanouts,
        "restored_source_permissions": restored_source_permissions,
        "source_movement_support": source_support,
        "source_lane_change_probes": change_evidence,
        "ambiguous": unresolved,
        "geometry_rejected": geometry_rejected,
        "exterior_edges_preserved": preserved,
        "extra_policy": "Unlisted road turns require source-path checks. Only redundant lane targets on the same exit road are removed.",
        "lane_bindings": lane_bindings,
        "composition": composition,
        "composed_boundary_path_reviews": composition_review,
        "boundary_connections": list(boundary_connections.values()),
    }
    return {
        "materialized_movement_count": len(materialized),
        "movements": materialized,
        "parts": part_reports,
        "official_connection_audit": audit,
        "connection_patch": str(patch_file),
        "netconvert_passes": commands,
        "selected_netconvert_command": contours.get("selected_command", command),
        "junction_contours": contours,
    }


def _compile_junction_contours(root, *, command, groups, output_file, timeout_seconds):
    """Compile each bounded shape from the original construction inputs."""
    from .hamburg_junction_contour import audit_junction_contour, propose_junction_contour

    destination = output_file.parent / f"{output_file.stem}-contours"
    destination.mkdir()
    source_files = [Path(command[command.index(option) + 1])
                    for option in ("--sumo-net-file", "--connection-files")]
    sources = [{"path": str(path), "sha256": file_sha256(path)} for path in source_files]
    report = {"mode": "guarded", "status": "review_required", "sources": sources,
              "parts": [], "accepted_junction_ids": [], "rejected_junction_ids": [],
              "claim_boundary": "These local shape cuts preserve known model surfaces and compiled traffic "
                                "semantics. They do not identify or verify field curbs or traffic islands."}
    nodes = ET.Element("nodes")
    selected_file = None
    for identifier in dict.fromkeys(str(row["join_id"]) for row in groups):
        proposal = propose_junction_contour(root, identifier)
        row = {"junction_id": identifier, "status": proposal["status"], "proposal": proposal}
        report["parts"].append(row)
        if not proposal["changed"]:
            continue
        node = ET.SubElement(nodes, "node", id=identifier, shape=_shape(proposal["proposed_shape"]))
        index = len(report["parts"])
        node_file = destination / f"parts-{index:03d}.nod.xml"
        trial_file = destination / f"trial-{index:03d}.net.xml"
        ET.indent(nodes, space="  ")
        ET.ElementTree(nodes).write(node_file, encoding="utf-8", xml_declaration=True)
        trial_command = list(command)
        trial_command[trial_command.index("--output-file") + 1] = str(trial_file)
        trial_command += ["--node-files", str(node_file)]
        result = run_command(trial_command, cwd=destination, timeout_seconds=timeout_seconds)
        row["netconvert"] = {"command": trial_command, "returncode": result.returncode,
                             "stdout": result.stdout, "stderr": result.stderr}
        row["node_file"] = {"path": str(node_file), "sha256": file_sha256(node_file)}
        accepted = False
        if result.returncode == 0 and trial_file.is_file():
            candidate = ET.parse(trial_file).getroot()
            row["network"] = {"path": str(trial_file), "sha256": file_sha256(trial_file)}
            comparison = _compare_contour_compilation(root, candidate, [identifier])
            row["preservation"] = comparison
            moved_lanes = [change for change in comparison["changes"] if change.get("element") == "lane"
                           and max(change.get("maximum_arclength_deviation_m", 0),
                                   change.get("polyline_length_difference_m", 0),
                                   change.get("length_difference_m", 0)) > 1e-8]
            row["lane_geometry_preservation"] = {"status": "blocked" if moved_lanes else "pass",
                "changed_lanes": moved_lanes, "roundoff_tolerance_m": 1e-8,
                "basis": "Contour-only edits may resample the same directed lane curve, but cannot move it. "
                         "This prevents compilation displacement from consuming coverage tolerance again."}
            junction = candidate.find(f"junction[@id='{identifier}']")
            if junction is not None:
                actual_shape = _parse_shape(junction.get("shape", ""))
                geometry = audit_junction_contour(root, identifier, actual_shape)
                row["compiled_geometry"] = geometry
                row["actual_lane_coverage"] = audit_junction_contour(candidate, identifier, actual_shape)
                accepted = comparison["status"] == "pass" and not moved_lanes and geometry["preservation_pass"]
        row["status"] = "pass" if accepted else "blocked"
        if accepted:
            root, selected_file = candidate, trial_file
            report["selected_command"] = trial_command
            report["accepted_junction_ids"].append(identifier)
        else:
            nodes.remove(node)
            report["rejected_junction_ids"].append(identifier)
    if any(file_sha256(Path(row["path"])) != row["sha256"] for row in sources):
        raise ValueError("a contour construction input changed")
    if selected_file is not None:
        shutil.copyfile(selected_file, output_file)
    report["inputs_unchanged"] = True
    return root, report


def _keep_boundary_lane_identity(result, group, available, *, role, lane_origins, changed_edge_ids, maximum_error_m):
    """Resolve only a geometric tie with an unchanged, unique cut-lane identity."""
    ports = [row for row in group.get("boundary_port_classification", {}).get("official_external_ports", []) if row.get("role") == role]
    source_counts = Counter(row.get("source_lane_id") for row in ports)
    official_counts = Counter(str(row["lane_id"]) for row in ports)
    by_official = {str(row["lane_id"]): row for row in ports}
    current_by_source = defaultdict(list)
    for key in available:
        current_id = f"{key[0]}_{key[1]}"
        original_id = lane_origins.get(current_id, current_id if key[0] not in changed_edge_ids else None)
        if original_id is not None:
            current_by_source[original_id].append(key)
    occupied = set(result["bindings"].values())
    preserved, reviews = {}, []
    for record in result["records"]:
        lane_id = str(record["lane_id"])
        if lane_id in result["bindings"] or record["reason"] != "lane_match_ambiguous" or lane_id not in by_official:
            continue
        port = by_official[lane_id]
        source_id = port.get("source_lane_id")
        keys = current_by_source.get(source_id, [])
        evidence = {"lane_id": lane_id, "source_lane_id": source_id, "junction_endpoint_network": port.get("junction_endpoint_network")}
        if not source_id or source_counts[source_id] != 1 or official_counts[lane_id] != 1 or len(keys) != 1:
            reviews.append({**evidence, "reason": "source_boundary_identity_not_unique"})
            continue
        key = keys[0]
        # The current binder already checked direction and vehicle permissions.
        # A known identity does not excuse an incompatible or distant lane.
        if not any((row["edge"], int(row["lane"])) == key and row["mean_error_m"] <= maximum_error_m for row in record["candidates"]):
            reviews.append({**evidence, "reason": "source_boundary_lane_not_a_compatible_geometric_candidate"})
        elif key in occupied:
            reviews.append({**evidence, "reason": "source_boundary_lane_already_assigned"})
        else:
            preserved[lane_id] = key
            occupied.add(key)
            record["source_boundary_identity"] = {**evidence, "sumo_lane": list(key),
                "basis": "explicit_lane_origin" if f"{key[0]}_{key[1]}" in lane_origins else "unchanged_source_lane_identity"}
    if preserved:
        _keep_constructed_lane_identity(result, preserved, available, reason="preserved_source_boundary_lane_identity")
    if reviews:
        result["boundary_identity_reviews"] = reviews


def _keep_constructed_lane_identity(result, constructed, available, *, reason="constructed_official_lane_identity"):
    """Do not infer a second identity for lanes just built from official data."""
    if any(tuple(key) not in available for key in constructed.values()) or len(set(constructed.values())) != len(constructed):
        raise ValueError("constructed lane identity does not match the current approach")
    assigned = set(constructed.values())
    for lane_id, key in list(result["bindings"].items()):
        if lane_id not in constructed and key in assigned:
            result["bindings"].pop(lane_id)
            result["ambiguous"].append({"lane_id": lane_id, "reason": "conflicts_with_constructed_lane_identity"})
    result["bindings"].update(constructed)
    result["ambiguous"] = [row for row in result["ambiguous"] if row["lane_id"] not in constructed]
    for row in result["records"]:
        if row["lane_id"] in constructed:
            row["reason"] = reason


def _connection_key(connection: ET.Element) -> tuple[str, int, str, int]:
    return (connection.get("from", ""), int(connection.get("fromLane", "0")), connection.get("to", ""), int(connection.get("toLane", "0")))


def _collision_join_ids(routeability: Mapping[str, Any]) -> set[str]:
    stderr = str(routeability.get("final_attempt", {}).get("command", {}).get("stderr", ""))
    return set(re.findall(r"lane=':(LSA\d+_part\d+)_", stderr))


def _movements_by_part(plan: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for movement in plan.get("movements", []):
        if isinstance(movement, Mapping):
            grouped[str(movement.get("intersection_part", "0"))].append(
                dict(movement)
            )
    return dict(grouped)


def _movement_centroid(movements: Sequence[Mapping[str, Any]], offset: Point) -> Point:
    values = []
    for movement in movements:
        shape = movement["selected_shape_network"]
        values.append(
            (
                (float(shape[0][0]) + float(shape[-1][0])) / 2 + offset[0],
                (float(shape[0][1]) + float(shape[-1][1])) / 2 + offset[1],
            )
        )
    return (
        sum(point[0] for point in values) / len(values),
        sum(point[1] for point in values) / len(values),
    )


def _distance_to_lines(point: Point, lines: Sequence[Sequence[Point]]) -> float:
    return min(
        _point_segment_distance(point, start, end)
        for line in lines
        for start, end in zip(line, line[1:])
    )


def _surface_finding_count(report: Mapping[str, Any]) -> int:
    return int(report.get("junction_junction_overlap_count", 0)) + int(
        report.get("external_lane_non_owner_junction_overlap_count", 0)
    )


def _net_offset(root: ET.Element) -> Point:
    location = root.find("location")
    if location is None or not location.attrib.get("netOffset"):
        return (0.0, 0.0)
    values = location.attrib["netOffset"].split(",")
    return (float(values[0]), float(values[1]))


def _parse_shape(value: str) -> list[Point]:
    return [
        (float(token.split(",")[0]), float(token.split(",")[1]))
        for token in value.split()
        if "," in token
    ]


def _shape(points: Sequence[Point]) -> str:
    return " ".join(f"{x:.3f},{y:.3f}" for x, y in points)


def _contour_curve_difference(before_shape, after_shape):
    """Compare directed curves by arclength, independent of vertex sampling."""
    tolerance = 0.1
    try:
        if before_shape is None or after_shape is None:
            raise ValueError("an explicit shape was added or removed")
        curves = [np.asarray([tuple(map(float, point.split(","))) for point in value.split()], dtype=float)
                  for value in (before_shape, after_shape)]
        if (any(curve.ndim != 2 or not len(curve) or curve.shape[1] not in (2, 3)
                or not np.isfinite(curve).all() for curve in curves) or curves[0].shape[1] != curves[1].shape[1]):
            raise ValueError("shapes require finite coordinates in the same dimension")
        stations = [np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))] for curve in curves]
        lengths = [float(values[-1]) for values in stations]
        fractions = [values / length if length > 0 else np.zeros(len(values)) for values, length in zip(stations, lengths)]
        knots = np.unique(np.concatenate(fractions))
        sampled = [np.column_stack([np.interp(knots, positions, curve[:, axis]) for axis in range(curve.shape[1])])
                   for curve, positions in zip(curves, fractions)]
        deviation = round(float(np.linalg.norm(sampled[0] - sampled[1], axis=1).max()), 9)
        length_delta = round(abs(lengths[1] - lengths[0]), 9)
        return {"status": "pass" if max(deviation, length_delta) <= tolerance else "blocked",
                "before_vertex_count": len(curves[0]), "after_vertex_count": len(curves[1]),
                "start_shift_m": float(np.linalg.norm(curves[0][0] - curves[1][0])),
                "end_shift_m": float(np.linalg.norm(curves[0][-1] - curves[1][-1])),
                "maximum_arclength_deviation_m": deviation, "polyline_length_difference_m": length_delta,
                "tolerance_m": tolerance}
    except (TypeError, ValueError) as error:
        return {"status": "blocked", "reason": str(error), "tolerance_m": tolerance}


def _compare_contour_compilation(before_root, after_root, target_junction_ids):
    """Allow reviewed target outlines, preserving all other construction data."""
    from .junction_boundary_rebuild import _signature

    targets = set(target_junction_ids)
    changes, target_shapes = [], []
    if before_root.attrib != after_root.attrib:
        changes.append({"status": "blocked", "kind": "network_attributes",
                        "before": dict(before_root.attrib), "after": dict(after_root.attrib)})
    node_ids = [{row.get("id") for row in root.findall("junction")} for root in (before_root, after_root)]
    if not targets or targets - (node_ids[0] & node_ids[1]):
        changes.append({"status": "blocked", "kind": "missing_target_junction",
                        "junction_ids": sorted(targets - (node_ids[0] & node_ids[1]))})

    def indexed(root):
        records = defaultdict(list)
        for row in root:
            fields = ("from", "fromLane", "to", "toLane") if row.tag == "connection" else (
                ("id", "programID") if row.tag == "tlLogic" else ("id",))
            records[(row.tag, *(row.get(field, "") for field in fields))].append(row)
        return records

    before, after = indexed(before_root), indexed(after_root)
    for key in sorted(before.keys() | after.keys()):
        if len(before[key]) != len(after[key]):
            changes.append({"status": "blocked", "kind": "element_count_or_identity", "key": list(key),
                            "before_count": len(before[key]), "after_count": len(after[key])})
            continue
        for original, current in zip(before[key], after[key]):
            left, right = deepcopy(original), deepcopy(current)
            if original.tag == "junction" and original.get("id") in targets:
                fields = ("shape", "customShape")
                if any(left.get(field) != right.get(field) for field in fields):
                    target_shapes.append({"junction_id": original.get("id"),
                        "before": {field: left.get(field) for field in fields},
                        "after": {field: right.get(field) for field in fields}})
                for field in fields:
                    left.attrib.pop(field, None)
                    right.attrib.pop(field, None)
            elif original.tag in {"edge", "connection", "junction"}:
                pairs = [(left, right)]
                if original.tag == "edge":
                    pairs.extend(zip(left.findall("lane"), right.findall("lane")))
                for first, second in pairs:
                    fields = ("shape", "length") if first.tag in {"edge", "lane"} else ("shape",)
                    for field in fields:
                        a, b = first.attrib.pop(field, None), second.attrib.pop(field, None)
                        if a == b:
                            continue
                        if field == "shape":
                            difference = _contour_curve_difference(a, b)
                        else:
                            try:
                                values = [float(value) for value in (a, b)]
                                if any(not math.isfinite(value) or value <= 0 for value in values):
                                    raise ValueError("length must stay finite and positive")
                                delta = round(abs(values[1] - values[0]), 9)
                                difference = {"status": "pass" if delta <= 0.1 else "blocked",
                                              "length_difference_m": delta, "tolerance_m": 0.1}
                            except (TypeError, ValueError) as error:
                                difference = {"status": "blocked", "reason": str(error)}
                        changes.append({"kind": "geometry", "key": list(key), "element": first.tag,
                                        "id": first.get("id"), "field": field, "before": a, "after": b, **difference})
            if _signature(left) != _signature(right):
                changes.append({"status": "blocked", "kind": "attributes_or_children", "key": list(key),
                                "before": _signature(left), "after": _signature(right)})
    return {"status": "blocked" if any(row["status"] == "blocked" for row in changes) else "pass",
            "geometry_tolerance_m": 0.1, "changes": changes, "target_shape_changes": target_shapes,
            "claim_boundary": "Only selected junction shape/customShape may change freely. Directed curves may be "
                              "resampled within existing 0.1 m geometry precision. All other attributes and child "
                              "records, including permissions, speeds, connection indices, conflicts and signal "
                              "programs, must match. Outline validity and coverage require their separate check."}


__all__ = [
    "CANDIDATE_SCHEMA",
    "REQUEST_SCHEMA",
    "build_hamburg_aerial_combined_candidate",
    "fit_movement_shape_to_anchors",
    "movement_surface_polygon",
    "reanchor_movement_shape",
]

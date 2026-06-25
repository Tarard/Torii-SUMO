from __future__ import annotations

import csv
import json
import math
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .osm_network import _net_xy_to_latlon
from .topology_audit import audit_topology_fragmentation


def audit_reference_join_patterns(
    *,
    reference_net_file: Path,
    candidate_net_file: Path,
    output_dir: Path,
    prefix: str = "reference_join_audit",
    reference_cluster_prefix: str = "cluster_",
    candidate_cluster_radius_m: float = 30.0,
    candidate_min_cluster_nodes: int = 3,
    match_radius_m: float = 45.0,
) -> dict[str, Any]:
    if match_radius_m <= 0:
        return _failure("match_radius_m must be positive")
    if not reference_net_file.exists():
        return _failure(f"reference net file does not exist: {reference_net_file}")
    if not candidate_net_file.exists():
        return _failure(f"candidate net file does not exist: {candidate_net_file}")

    try:
        reference_cases = _reference_join_cases(reference_net_file, reference_cluster_prefix)
        candidate_graph = _candidate_graph(candidate_net_file)
    except (OSError, ET.ParseError, KeyError, ValueError) as exc:
        return _failure(f"{type(exc).__name__}: {exc}")

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_audit = audit_topology_fragmentation(
        net_file=candidate_net_file,
        output_dir=output_dir / "candidate_topology",
        prefix=f"{prefix}_candidate",
        cluster_radius_m=candidate_cluster_radius_m,
        min_cluster_nodes=candidate_min_cluster_nodes,
    )
    if candidate_audit.get("status") == "fail":
        return {
            **_failure(f"candidate topology audit failed: {candidate_audit.get('error', 'unknown error')}"),
            "candidate_topology_audit": candidate_audit,
        }

    candidate_clusters = list(candidate_audit.get("suspicious_clusters", []))
    matched_cases = [
        _match_reference_case(reference_case, candidate_clusters, candidate_graph, match_radius_m)
        for reference_case in reference_cases
    ]
    matched = [case for case in matched_cases if case["match_status"] == "matched"]

    cases_file = output_dir / f"{prefix}_reference_join_cases.csv"
    summary_file = output_dir / f"{prefix}_reference_join_audit.json"
    _write_cases_csv(cases_file, matched_cases)

    report = {
        "status": "pass" if reference_cases else "blocked",
        "claim_status": "diagnostic-demo" if reference_cases else "blocked",
        "reference_net_file": str(reference_net_file),
        "candidate_net_file": str(candidate_net_file),
        "output_dir": str(output_dir),
        "reference_cluster_prefix": reference_cluster_prefix,
        "candidate_cluster_radius_m": candidate_cluster_radius_m,
        "candidate_min_cluster_nodes": candidate_min_cluster_nodes,
        "match_radius_m": match_radius_m,
        "reference_case_count": len(reference_cases),
        "matched_case_count": len(matched),
        "unmatched_case_count": len(matched_cases) - len(matched),
        "candidate_topology_cluster_count": candidate_audit.get("suspicious_cluster_count", 0),
        "reference_type_counts": dict(Counter(case["reference_type"] for case in reference_cases)),
        "learned_rule_counts": dict(Counter(case["learned_rule"] for case in matched_cases)),
        "pattern_stats": _pattern_stats(reference_cases, matched),
        "cases_file": str(cases_file),
        "summary_file": str(summary_file),
        "candidate_topology_audit_file": str(candidate_audit.get("report_file", "")),
        "matched_cases": matched,
        "all_cases": matched_cases,
        "warnings": _warnings(reference_cases, matched_cases),
    }
    summary_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def _failure(error: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "claim_status": "construction-invalid",
        "error": error,
    }


def _reference_join_cases(net_file: Path, cluster_prefix: str) -> list[dict[str, Any]]:
    root = ET.parse(net_file).getroot()
    xy_to_latlon = _coordinate_converter(net_file)
    cases = []
    for junction in root.findall("junction"):
        junction_id = junction.attrib.get("id", "")
        if not junction_id.startswith(cluster_prefix):
            continue
        x = float(junction.attrib["x"])
        y = float(junction.attrib["y"])
        lat, lon, coordinate_status = _junction_latlon(x, y, xy_to_latlon)
        joined_nodes = _joined_source_nodes(junction_id, cluster_prefix)
        inc_edges = sorted(
            {
                _lane_to_edge_id(lane_id)
                for lane_id in junction.attrib.get("incLanes", "").split()
                if lane_id and not lane_id.startswith(":")
            }
        )
        int_lanes = [lane_id for lane_id in junction.attrib.get("intLanes", "").split() if lane_id]
        cases.append(
            {
                "reference_id": junction_id,
                "reference_type": junction.attrib.get("type", ""),
                "reference_x": round(x, 3),
                "reference_y": round(y, 3),
                "reference_lat": round(lat, 7),
                "reference_lon": round(lon, 7),
                "reference_coordinate_status": coordinate_status,
                "reference_joined_source_nodes": joined_nodes,
                "reference_joined_source_node_count": len(joined_nodes),
                "reference_approach_edge_ids": inc_edges,
                "reference_approach_edge_count": len(inc_edges),
                "reference_internal_lane_count": len(int_lanes),
                "reference_shape_point_count": len(_parse_shape(junction.attrib.get("shape", ""))),
            }
        )
    cases.sort(
        key=lambda case: (
            -int(case["reference_joined_source_node_count"]),
            -int(case["reference_approach_edge_count"]),
            str(case["reference_id"]),
        )
    )
    return cases


def _candidate_graph(net_file: Path) -> dict[str, Any]:
    root = ET.parse(net_file).getroot()
    junction_ids = {
        junction.attrib["id"]
        for junction in root.findall("junction")
        if "id" in junction.attrib and not junction.attrib["id"].startswith(":")
    }
    edges = []
    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id", "")
        if not edge_id or edge_id.startswith(":"):
            continue
        from_node = edge.attrib.get("from", "")
        to_node = edge.attrib.get("to", "")
        if not from_node or not to_node:
            continue
        edges.append({"id": edge_id, "from": from_node, "to": to_node})
    return {
        "junction_ids": junction_ids,
        "edges": edges,
    }


def _match_reference_case(
    reference_case: dict[str, Any],
    candidate_clusters: list[dict[str, Any]],
    candidate_graph: dict[str, Any],
    match_radius_m: float,
) -> dict[str, Any]:
    source_match = _match_reference_sources(reference_case, candidate_graph)
    best_cluster = None
    best_distance = math.inf
    for cluster in candidate_clusters:
        distance = _case_cluster_distance(reference_case, cluster)
        if distance < best_distance:
            best_distance = distance
            best_cluster = cluster

    if best_cluster is None or best_distance > match_radius_m:
        if _has_source_join_evidence(source_match):
            return {
                **reference_case,
                **source_match,
                "match_status": "matched",
                "match_distance_m": round(best_distance, 3) if math.isfinite(best_distance) else "",
                "matched_candidate_cluster_id": "",
                "matched_candidate_node_ids": source_match["matched_reference_source_node_ids"],
                "matched_candidate_node_count": source_match["matched_reference_source_node_count"],
                "matched_candidate_internal_edge_count": source_match["matched_reference_source_internal_edge_count"],
                "matched_candidate_internal_edge_ids": source_match["matched_reference_source_internal_edge_ids"],
                "matched_candidate_boundary_edge_ids": source_match["matched_reference_source_boundary_edge_ids"],
                "matched_candidate_approach_count": source_match["matched_reference_source_boundary_edge_count"],
                "matched_candidate_traffic_light_node_count": 0,
                "matched_candidate_risk_flags": ["map_review_required", "reference_source_join"],
                "matched_candidate_google_maps_url": _google_maps_url(reference_case),
                "learned_rule_basis": "reference_source_nodes",
                "learned_rule": "tum_like_join_candidate",
            }
        return {
            **reference_case,
            **source_match,
            "match_status": "unmatched",
            "match_distance_m": round(best_distance, 3) if math.isfinite(best_distance) else "",
            "matched_candidate_cluster_id": "",
            "matched_candidate_node_count": 0,
            "matched_candidate_internal_edge_count": 0,
            "matched_candidate_internal_edge_ids": [],
            "learned_rule_basis": "none",
            "learned_rule": "no_nearby_torii_cluster",
        }

    learned_rule_basis = "reference_source_nodes" if _has_source_join_evidence(source_match) else "spatial_cluster"
    learned_rule = _learned_rule(reference_case, best_cluster, source_match)
    return {
        **reference_case,
        **source_match,
        "match_status": "matched",
        "match_distance_m": round(best_distance, 3),
        "matched_candidate_cluster_id": best_cluster.get("cluster_id", ""),
        "matched_candidate_node_ids": list(best_cluster.get("node_ids", [])),
        "matched_candidate_node_count": int(best_cluster.get("node_count", 0)),
        "matched_candidate_internal_edge_count": int(best_cluster.get("internal_edge_count", 0)),
        "matched_candidate_internal_edge_ids": list(best_cluster.get("internal_edge_ids", [])),
        "matched_candidate_boundary_edge_ids": list(best_cluster.get("boundary_edge_ids", [])),
        "matched_candidate_approach_count": int(best_cluster.get("approach_count", 0)),
        "matched_candidate_traffic_light_node_count": int(best_cluster.get("traffic_light_node_count", 0)),
        "matched_candidate_risk_flags": list(best_cluster.get("risk_flags", [])),
        "matched_candidate_google_maps_url": best_cluster.get("google_maps_url", ""),
        "learned_rule_basis": learned_rule_basis,
        "learned_rule": learned_rule,
    }


def _match_reference_sources(reference_case: dict[str, Any], candidate_graph: dict[str, Any]) -> dict[str, Any]:
    source_node_ids = list(reference_case.get("reference_joined_source_nodes", []))
    junction_ids = set(candidate_graph.get("junction_ids", set()))
    matched_node_ids = sorted(node_id for node_id in source_node_ids if node_id in junction_ids)
    matched_node_id_set = set(matched_node_ids)
    internal_edge_ids = sorted(
        edge["id"]
        for edge in candidate_graph.get("edges", [])
        if edge["from"] in matched_node_id_set and edge["to"] in matched_node_id_set
    )
    boundary_edge_ids = sorted(
        edge["id"]
        for edge in candidate_graph.get("edges", [])
        if (edge["from"] in matched_node_id_set) ^ (edge["to"] in matched_node_id_set)
    )
    return {
        "matched_reference_source_node_ids": matched_node_ids,
        "matched_reference_source_node_count": len(matched_node_ids),
        "reference_source_node_match_ratio": round(len(matched_node_ids) / len(source_node_ids), 3)
        if source_node_ids
        else 0.0,
        "matched_reference_source_internal_edge_ids": internal_edge_ids,
        "matched_reference_source_internal_edge_count": len(internal_edge_ids),
        "matched_reference_source_boundary_edge_ids": boundary_edge_ids,
        "matched_reference_source_boundary_edge_count": len(boundary_edge_ids),
    }


def _has_source_join_evidence(source_match: dict[str, Any]) -> bool:
    return (
        int(source_match.get("matched_reference_source_node_count", 0)) >= 2
        and int(source_match.get("matched_reference_source_internal_edge_count", 0)) > 0
    )


def _learned_rule(
    reference_case: dict[str, Any],
    candidate_cluster: dict[str, Any],
    source_match: dict[str, Any],
) -> str:
    if _has_source_join_evidence(source_match) or int(candidate_cluster.get("internal_edge_count", 0)) > 0:
        return "tum_like_join_candidate"
    return "needs_case_review"


def _pattern_stats(reference_cases: list[dict[str, Any]], matched_cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "reference_joined_source_node_counts": _count_field(reference_cases, "reference_joined_source_node_count"),
        "reference_approach_edge_counts": _count_field(reference_cases, "reference_approach_edge_count"),
        "reference_type_counts": _count_field(reference_cases, "reference_type"),
        "matched_reference_source_node_counts": _count_field(matched_cases, "matched_reference_source_node_count"),
        "matched_reference_source_internal_edge_counts": _count_field(
            matched_cases,
            "matched_reference_source_internal_edge_count",
        ),
        "matched_candidate_node_counts": _count_field(matched_cases, "matched_candidate_node_count"),
        "matched_candidate_approach_counts": _count_field(matched_cases, "matched_candidate_approach_count"),
        "matched_candidate_internal_edge_counts": _count_field(matched_cases, "matched_candidate_internal_edge_count"),
        "matched_reference_type_counts": _count_field(matched_cases, "reference_type"),
        "learned_rule_basis_counts": _count_field(matched_cases, "learned_rule_basis"),
    }


def _count_field(cases: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(case.get(field, "")) for case in cases).items()))


def _case_cluster_distance(reference_case: dict[str, Any], cluster: dict[str, Any]) -> float:
    ref_status = str(reference_case.get("reference_coordinate_status", ""))
    cluster_status = str(cluster.get("coordinate_status", ""))
    if ref_status.startswith("xy_fallback") or cluster_status.startswith("xy_fallback"):
        return math.hypot(
            float(reference_case["reference_x"]) - float(cluster["centroid_x"]),
            float(reference_case["reference_y"]) - float(cluster["centroid_y"]),
        )
    return _haversine_m(
        float(reference_case["reference_lat"]),
        float(reference_case["reference_lon"]),
        float(cluster["centroid_lat"]),
        float(cluster["centroid_lon"]),
    )


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    return 2.0 * radius_m * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _joined_source_nodes(junction_id: str, cluster_prefix: str) -> list[str]:
    return [part for part in junction_id.removeprefix(cluster_prefix).split("_") if part]


def _lane_to_edge_id(lane_id: str) -> str:
    raw_edge, separator, lane_index = lane_id.rpartition("_")
    if separator and lane_index.isdigit():
        return raw_edge
    return lane_id


def _parse_shape(shape_text: str) -> list[tuple[float, float]]:
    points = []
    for raw_point in shape_text.split():
        parts = raw_point.split(",")
        if len(parts) >= 2:
            points.append((float(parts[0]), float(parts[1])))
    return points


def _coordinate_converter(net_file: Path) -> Callable[[float, float], tuple[float, float]] | None:
    try:
        import sumolib  # type: ignore

        net = sumolib.net.readNet(str(net_file))
        return lambda x, y: _net_xy_to_latlon(net, x, y)
    except Exception:
        return None


def _junction_latlon(
    x: float,
    y: float,
    xy_to_latlon: Callable[[float, float], tuple[float, float]] | None,
) -> tuple[float, float, str]:
    if xy_to_latlon is None:
        return y, x, "xy_fallback_no_geo_projection"
    try:
        lat, lon = xy_to_latlon(x, y)
    except Exception:
        return y, x, "xy_fallback_geo_projection_failed"
    return lat, lon, "wgs84_from_sumo_projection"


def _google_maps_url(case: dict[str, Any]) -> str:
    if str(case.get("reference_coordinate_status", "")).startswith("xy_fallback"):
        return ""
    return f"https://www.google.com/maps/@{float(case['reference_lat']):.7f},{float(case['reference_lon']):.7f},50m"


def _write_cases_csv(path: Path, cases: list[dict[str, Any]]) -> None:
    fields = [
        "reference_id",
        "reference_type",
        "reference_joined_source_node_count",
        "reference_approach_edge_count",
        "reference_internal_lane_count",
        "reference_shape_point_count",
        "reference_lat",
        "reference_lon",
        "match_status",
        "match_distance_m",
        "matched_reference_source_node_count",
        "reference_source_node_match_ratio",
        "matched_reference_source_internal_edge_count",
        "matched_reference_source_boundary_edge_count",
        "matched_candidate_cluster_id",
        "matched_candidate_node_count",
        "matched_candidate_internal_edge_count",
        "matched_candidate_approach_count",
        "matched_candidate_traffic_light_node_count",
        "learned_rule_basis",
        "learned_rule",
        "matched_candidate_google_maps_url",
        "reference_joined_source_nodes",
        "reference_approach_edge_ids",
        "matched_reference_source_node_ids",
        "matched_reference_source_internal_edge_ids",
        "matched_reference_source_boundary_edge_ids",
        "matched_candidate_node_ids",
        "matched_candidate_internal_edge_ids",
        "matched_candidate_boundary_edge_ids",
        "matched_candidate_risk_flags",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            row = {field: case.get(field, "") for field in fields}
            for field in (
                "reference_joined_source_nodes",
                "reference_approach_edge_ids",
                "matched_reference_source_node_ids",
                "matched_reference_source_internal_edge_ids",
                "matched_reference_source_boundary_edge_ids",
                "matched_candidate_node_ids",
                "matched_candidate_internal_edge_ids",
                "matched_candidate_boundary_edge_ids",
                "matched_candidate_risk_flags",
            ):
                value = row.get(field, [])
                if isinstance(value, list):
                    row[field] = ";".join(str(item) for item in value)
            writer.writerow(row)


def _warnings(reference_cases: list[dict[str, Any]], matched_cases: list[dict[str, Any]]) -> list[str]:
    warnings = []
    if not reference_cases:
        warnings.append("no reference joined junction cases found")
    unmatched = sum(1 for case in matched_cases if case["match_status"] != "matched")
    if unmatched:
        warnings.append(f"{unmatched} reference joined junction case(s) did not match a nearby candidate cluster")
    warnings.append("reference-derived join candidates remain diagnostic until map review and routeability gates pass")
    return warnings

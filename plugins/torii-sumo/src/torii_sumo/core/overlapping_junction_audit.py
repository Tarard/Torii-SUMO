from __future__ import annotations

import csv
import json
import math
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .candidate_contracts import file_sha256
from .surface_overlap_audit import SURFACE_OVERLAP_AUDIT_SCHEMA


def audit_overlapping_junctions(
    *,
    net_file: Path,
    output_dir: Path,
    prefix: str = "overlapping_junction_audit",
    overlap_radius_m: float = 12.0,
    short_edge_length_m: float = 20.0,
    min_group_nodes: int = 2,
    micro_edge_length_m: float = 3.0,
    topology_audit_report: Mapping[str, Any] | None = None,
    surface_overlap_audit_report: Mapping[str, Any] | None = None,
    reference_join_audit_report: dict[str, Any] | None = None,
    reference_is_authority: bool = False,
    authorized_reference_ids: set[str] | None = None,
) -> dict[str, Any]:
    if overlap_radius_m <= 0:
        return _failure("overlap_radius_m must be positive")
    if short_edge_length_m <= 0:
        return _failure("short_edge_length_m must be positive")
    if min_group_nodes < 2:
        return _failure("min_group_nodes must be at least 2")
    if micro_edge_length_m <= 0:
        return _failure("micro_edge_length_m must be positive")
    if not net_file.exists():
        return _failure(f"net file does not exist: {net_file}")

    try:
        net = _read_net(net_file)
    except (OSError, ET.ParseError, KeyError, ValueError) as exc:
        return _failure(f"{type(exc).__name__}: {exc}")

    reference_groups = _reference_groups(reference_join_audit_report)
    groups = _overlap_groups(net["junctions"], net["edges"], overlap_radius_m, short_edge_length_m, min_group_nodes)
    reports = [
        _group_report(index, group, net["junctions"], net["edges"], reference_groups)
        for index, group in enumerate(groups, start=1)
    ]
    reports = [group for group in reports if _is_actionable_group(group)]
    compound_core_candidates = _compound_core_candidates(
        net,
        topology_audit_report=topology_audit_report,
        surface_overlap_audit_report=surface_overlap_audit_report,
        reference_join_audit_report=reference_join_audit_report,
        reference_is_authority=reference_is_authority,
        authorized_reference_ids=authorized_reference_ids,
        micro_edge_length_m=micro_edge_length_m,
        net_file=net_file,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    groups_file = output_dir / f"{prefix}_overlapping_junction_groups.csv"
    summary_file = output_dir / f"{prefix}_overlapping_junction_audit.json"
    _write_groups_csv(groups_file, reports)

    report = {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "net_file": str(net_file),
        "output_dir": str(output_dir),
        "overlap_radius_m": overlap_radius_m,
        "short_edge_length_m": short_edge_length_m,
        "min_group_nodes": min_group_nodes,
        "micro_edge_length_m": micro_edge_length_m,
        "top_level_junction_count": len(net["junctions"]),
        "ignored_internal_layer_count": net["ignored_internal_layer_count"],
        "overlapping_junction_group_count": len(reports),
        "recommendation_counts": dict(Counter(group["recommendation"] for group in reports)),
        "groups_file": str(groups_file),
        "summary_file": str(summary_file),
        "overlapping_junction_groups": reports,
        "compound_core_candidate_count": len(compound_core_candidates),
        "compound_core_candidates": compound_core_candidates,
    }
    summary_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def _failure(error: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "claim_status": "construction-invalid",
        "error": error,
    }


def _read_net(net_file: Path) -> dict[str, Any]:
    root = ET.parse(net_file).getroot()
    junctions = {
        junction.attrib["id"]: {
            "id": junction.attrib["id"],
            "type": junction.attrib.get("type", ""),
            "x": float(junction.attrib.get("x", "0")),
            "y": float(junction.attrib.get("y", "0")),
        }
        for junction in root.findall("junction")
        if "id" in junction.attrib and not junction.attrib["id"].startswith(":")
    }
    edges = []
    ignored_internal_layer_count = 0
    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id", "")
        function = edge.attrib.get("function", "")
        if edge_id.startswith(":") or function in {"internal", "crossing", "walkingarea"}:
            ignored_internal_layer_count += 1
            continue
        from_node = edge.attrib.get("from", "")
        to_node = edge.attrib.get("to", "")
        if from_node not in junctions or to_node not in junctions:
            continue
        lanes = edge.findall("lane")
        edges.append(
            {
                "id": edge_id,
                "from": from_node,
                "to": to_node,
                "type": edge.attrib.get("type", ""),
                "length": _edge_length(edge, lanes),
                "allow": " ".join(lane.attrib.get("allow", "") for lane in lanes),
            }
        )
    return {
        "junctions": junctions,
        "edges": edges,
        "ignored_internal_layer_count": ignored_internal_layer_count,
    }


def _edge_length(edge: ET.Element, lanes: list[ET.Element]) -> float:
    if lanes and lanes[0].attrib.get("length"):
        return float(lanes[0].attrib["length"])
    if lanes and lanes[0].attrib.get("shape"):
        return _shape_length(lanes[0].attrib["shape"])
    return float(edge.attrib.get("length", "0") or 0)


def _shape_length(shape: str) -> float:
    points = []
    for raw in shape.split():
        parts = raw.split(",")
        if len(parts) >= 2:
            points.append((float(parts[0]), float(parts[1])))
    return sum(math.hypot(bx - ax, by - ay) for (ax, ay), (bx, by) in zip(points, points[1:]))


def _overlap_groups(
    junctions: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    overlap_radius_m: float,
    short_edge_length_m: float,
    min_group_nodes: int,
) -> list[list[str]]:
    ids = sorted(junctions)
    short_neighbors: dict[str, set[str]] = {node_id: set() for node_id in ids}
    for edge in edges:
        if edge["length"] <= short_edge_length_m:
            short_neighbors[edge["from"]].add(edge["to"])
            short_neighbors[edge["to"]].add(edge["from"])

    groups: set[frozenset[str]] = set()
    for seed in ids:
        local = {
            node_id
            for node_id in ids
            if node_id == seed or _distance(junctions[seed], junctions[node_id]) <= overlap_radius_m
        }
        local.update(short_neighbors[seed])
        if len(local) >= min_group_nodes:
            groups.add(frozenset(local))
    return sorted((sorted(group) for group in groups), key=lambda group: (-len(group), group))


def _group_report(
    index: int,
    node_ids: list[str],
    junctions: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    reference_groups: dict[frozenset[str], list[str]],
) -> dict[str, Any]:
    group_edges = [edge for edge in edges if edge["from"] in node_ids and edge["to"] in node_ids]
    incident_edges = [edge for edge in edges if edge["from"] in node_ids or edge["to"] in node_ids]
    reference_ids = _matching_reference_ids(node_ids, reference_groups)
    edge_types = Counter(edge["type"] for edge in incident_edges)
    has_vehicle_edges = any(_is_vehicle_edge(edge) for edge in incident_edges)
    has_pedestrian_or_bike_edges = any(_is_pedestrian_or_bike_edge(edge) for edge in incident_edges)
    traffic_light_node_count = sum(1 for node_id in node_ids if junctions[node_id]["type"] == "traffic_light")
    recommendation = "reference_join_supported" if reference_ids else "same_physical_intersection_review"
    distances = [_distance(junctions[a], junctions[b]) for i, a in enumerate(node_ids) for b in node_ids[i + 1 :]]
    return {
        "group_id": f"OJ{index:03d}",
        "node_ids": node_ids,
        "node_types": [junctions[node_id]["type"] for node_id in node_ids],
        "min_pair_distance_m": round(min(distances), 3) if distances else 0.0,
        "max_pair_distance_m": round(max(distances), 3) if distances else 0.0,
        "direct_edge_ids": sorted(edge["id"] for edge in group_edges),
        "direct_edge_count": len(group_edges),
        "edge_type_counts": dict(edge_types),
        "has_vehicle_edges": has_vehicle_edges,
        "has_pedestrian_or_bike_edges": has_pedestrian_or_bike_edges,
        "traffic_light_node_count": traffic_light_node_count,
        "reference_join_status": "reference_join_supported" if reference_ids else "not_reference_matched",
        "reference_join_ids": reference_ids,
        "recommendation": recommendation,
    }


def _is_actionable_group(group: dict[str, Any]) -> bool:
    if not group["has_vehicle_edges"]:
        return False
    return bool(
        group["reference_join_ids"]
        or group["has_pedestrian_or_bike_edges"]
        or group["traffic_light_node_count"] > 0
    )


def _reference_groups(report: dict[str, Any] | None) -> dict[frozenset[str], list[str]]:
    groups: dict[frozenset[str], list[str]] = {}
    for case in (report or {}).get("matched_cases", []) or []:
        node_ids = case.get("matched_candidate_node_ids") or case.get("matched_reference_source_node_ids") or []
        if len(node_ids) >= 2:
            groups.setdefault(frozenset(str(node_id) for node_id in node_ids), []).append(str(case.get("reference_id", "")))
    return groups


def _matching_reference_ids(node_ids: list[str], reference_groups: dict[frozenset[str], list[str]]) -> list[str]:
    node_set = set(node_ids)
    matches = []
    for reference_nodes, reference_ids in reference_groups.items():
        if reference_nodes.issubset(node_set):
            matches.extend(reference_id for reference_id in reference_ids if reference_id)
    return sorted(matches)


def _distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    return math.hypot(float(a["x"]) - float(b["x"]), float(a["y"]) - float(b["y"]))


def _compound_core_candidates(
    net: dict[str, Any],
    *,
    topology_audit_report: Mapping[str, Any] | None,
    surface_overlap_audit_report: Mapping[str, Any] | None,
    reference_join_audit_report: Mapping[str, Any] | None,
    reference_is_authority: bool,
    authorized_reference_ids: set[str] | None,
    micro_edge_length_m: float,
    net_file: Path,
) -> list[dict[str, Any]]:
    topology = topology_audit_report or {}
    surface = surface_overlap_audit_report or {}
    reference = reference_join_audit_report or {}
    if (
        surface.get("schema") != SURFACE_OVERLAP_AUDIT_SCHEMA
        or surface.get("source_network_mutation") is not False
        or Path(str(surface.get("source_net_file", ""))).resolve() != net_file.resolve()
        or str(surface.get("source_sha256", "")) != file_sha256(net_file)
    ):
        return []

    exact_pairs = {
        frozenset(
            (
                str(item.get("first_junction_id", "")),
                str(item.get("second_junction_id", "")),
            )
        )
        for item in surface.get("junction_junction_overlaps", []) or []
        if item.get("first_junction_id") and item.get("second_junction_id")
    }
    geometry_error_nodes = {
        str(item.get("junction_id", ""))
        for item in surface.get("geometry_errors", []) or []
        if item.get("junction_id")
    }
    clusters = {
        str(item.get("cluster_id", "")): item
        for item in topology.get("suspicious_clusters", []) or []
        if item.get("cluster_id")
    }
    candidates = []
    authorized_ids = {str(item) for item in (authorized_reference_ids or ()) if str(item)}
    for case in reference.get("all_cases", reference.get("matched_cases", [])) or []:
        reference_id = str(case.get("reference_id", ""))
        cluster = clusters.get(str(case.get("matched_candidate_cluster_id", "")))
        join_nodes = [
            str(item)
            for item in (
                case.get("matched_reference_source_junction_ids")
                or case.get("matched_reference_source_node_ids")
                or []
            )
            if str(item)
        ]
        identity_complete = bool(
            case.get(
                "reference_source_identity_complete",
                len(join_nodes) == int(case.get("reference_joined_source_node_count", 0) or 0),
            )
        )
        large_compound = bool(
            cluster
            and int(cluster.get("node_count", 0)) >= 5
            and int(cluster.get("traffic_light_node_count", 0)) >= 2
            and int(cluster.get("approach_count", 0)) >= 4
            and str(cluster.get("physical_intersection_shape", "")) in {"cross", "t_or_y", "multi_arm"}
        )
        join_node_set = set(join_nodes)
        micro_edges = [
            edge
            for edge in net["edges"]
            if float(edge["length"]) <= micro_edge_length_m
            and frozenset((str(edge["from"]), str(edge["to"]))) in exact_pairs
            and {str(edge["from"]), str(edge["to"])} <= join_node_set
        ]
        target_clean = not (join_node_set & geometry_error_nodes)
        evidence_complete = bool(
            case.get("match_status") == "matched"
            and identity_complete
            and len(join_nodes) >= 2
            and int(case.get("matched_reference_source_internal_edge_count", 0)) >= 1
            and int(case.get("matched_reference_source_boundary_edge_count", 0)) >= 2
            and large_compound
            and micro_edges
            and target_clean
        )
        if not large_compound or not micro_edges:
            continue
        authorized = bool(
            reference_is_authority
            and reference_id in authorized_ids
            and evidence_complete
        )
        candidates.append(
            {
                "group_id": f"CC{len(candidates) + 1:03d}",
                "reference_id": reference_id,
                "matched_candidate_cluster_id": str(case.get("matched_candidate_cluster_id", "")),
                "node_ids": join_nodes,
                "reference_join_node_ids": join_nodes,
                "micro_exact_overlap_edge_ids": sorted(str(edge["id"]) for edge in micro_edges),
                "micro_exact_overlap_edge_count": len(micro_edges),
                "traffic_light_node_count": int(cluster.get("traffic_light_node_count", 0)),
                "approach_count": int(cluster.get("approach_count", 0)),
                "physical_intersection_shape": str(cluster.get("physical_intersection_shape", "")),
                "source_identity_complete": identity_complete,
                "target_geometry_error_count": len(join_node_set & geometry_error_nodes),
                "reference_join_status": "reference_join_supported",
                "reference_join_ids": [reference_id],
                "target_evidence_status": "pass" if authorized else "review_required",
                "transfer_gate_status": "pass" if authorized else "blocked",
                "recommendation": "join" if authorized else "same_physical_intersection_review",
                "decision": "join" if authorized else "needs_map_review",
                "confidence": "target_evidence_confirmed" if authorized else "teacher_prior",
            }
        )
    return candidates


def _is_pedestrian_or_bike_edge(edge: dict[str, Any]) -> bool:
    text = f"{edge['type']} {edge['allow']}"
    return any(token in text for token in ("footway", "cycleway", "pedestrian", "bicycle"))


def _is_vehicle_edge(edge: dict[str, Any]) -> bool:
    return not _is_pedestrian_or_bike_edge(edge)


def _write_groups_csv(path: Path, groups: list[dict[str, Any]]) -> None:
    fieldnames = [
        "group_id",
        "node_ids",
        "node_types",
        "min_pair_distance_m",
        "max_pair_distance_m",
        "direct_edge_ids",
        "direct_edge_count",
        "edge_type_counts",
        "has_vehicle_edges",
        "has_pedestrian_or_bike_edges",
        "traffic_light_node_count",
        "reference_join_status",
        "reference_join_ids",
        "recommendation",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for group in groups:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                    for key, value in group.items()
                }
            )

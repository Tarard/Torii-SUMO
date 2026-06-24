from __future__ import annotations

import csv
import json
import math
from collections import Counter, deque
from collections.abc import Callable
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .osm_network import _net_xy_to_latlon


def audit_topology_fragmentation(
    *,
    net_file: Path,
    output_dir: Path,
    prefix: str = "topology_audit",
    cluster_radius_m: float = 30.0,
    min_cluster_nodes: int = 3,
) -> dict[str, Any]:
    if cluster_radius_m <= 0:
        return _failure("cluster_radius_m must be positive")
    if min_cluster_nodes <= 1:
        return _failure("min_cluster_nodes must be greater than 1")
    if not net_file.exists():
        return _failure(f"net file does not exist: {net_file}")

    try:
        junctions, edges = _read_network_graph(net_file)
    except (OSError, ET.ParseError, KeyError, ValueError) as exc:
        return _failure(f"{type(exc).__name__}: {exc}")

    xy_to_latlon = _coordinate_converter(net_file)
    clusters = _dense_clusters(
        junctions,
        radius_m=cluster_radius_m,
        min_cluster_nodes=min_cluster_nodes,
        xy_to_latlon=xy_to_latlon,
        edges=edges,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    clusters_file = output_dir / f"{prefix}_dense_junction_clusters.csv"
    report_file = output_dir / f"{prefix}_topology_audit.json"
    _write_clusters_csv(clusters_file, clusters)

    status = "blocked" if clusters else "pass"
    warnings = []
    if clusters:
        warnings.append(f"topology audit found {len(clusters)} suspicious dense junction cluster(s)")

    physical_shape_counts = dict(Counter(cluster["physical_intersection_shape"] for cluster in clusters))
    physical_intersection_candidate_count = sum(
        1
        for cluster in clusters
        if cluster["physical_intersection_shape"] in {"cross", "t_or_y"}
        and float(cluster["physical_intersection_score"]) >= 0.6
    )
    report = {
        "status": status,
        "claim_status": "blocked" if clusters else "diagnostic-demo",
        "topology_fragmentation_status": "needs_review" if clusters else "pass",
        "net_file": str(net_file),
        "output_dir": str(output_dir),
        "cluster_radius_m": cluster_radius_m,
        "min_cluster_nodes": min_cluster_nodes,
        "junction_count": len(junctions),
        "suspicious_cluster_count": len(clusters),
        "max_cluster_node_count": max((cluster["node_count"] for cluster in clusters), default=0),
        "aggregation_decision_counts": dict(Counter(cluster["aggregation_decision"] for cluster in clusters)),
        "physical_intersection_shape_counts": physical_shape_counts,
        "physical_intersection_candidate_count": physical_intersection_candidate_count,
        "junction_aggregation_candidate_count": sum(
            1 for cluster in clusters if cluster["aggregation_decision"] in {"join", "needs_map_review"}
        ),
        "clusters_file": str(clusters_file),
        "report_file": str(report_file),
        "suspicious_clusters": clusters,
        "warnings": warnings,
    }
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def _failure(error: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "claim_status": "construction-invalid",
        "topology_fragmentation_status": "construction-invalid",
        "error": error,
    }


def _read_network_graph(net_file: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = ET.parse(net_file).getroot()
    junctions = []
    for junction in root.findall("junction"):
        junction_id = junction.attrib["id"]
        junction_type = junction.attrib.get("type", "")
        if junction_id.startswith(":") or junction_type == "internal":
            continue
        junctions.append(
            {
                "id": junction_id,
                "type": junction_type,
                "x": float(junction.attrib["x"]),
                "y": float(junction.attrib["y"]),
            }
        )
    edges = []
    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id", "")
        if edge_id.startswith(":") or edge.attrib.get("function") == "internal":
            continue
        from_node = edge.attrib.get("from")
        to_node = edge.attrib.get("to")
        if not from_node or not to_node:
            continue
        lanes = edge.findall("lane")
        shape = _edge_shape(edge, lanes)
        edges.append(
            {
                "id": edge_id,
                "from": from_node,
                "to": to_node,
                "type": edge.attrib.get("type", ""),
                "name": edge.attrib.get("name", ""),
                "lane_count": len(lanes),
                "length": _edge_length(shape, lanes),
                "shape": shape,
            }
        )
    return junctions, edges


def _dense_clusters(
    junctions: list[dict[str, Any]],
    *,
    radius_m: float,
    min_cluster_nodes: int,
    xy_to_latlon: Callable[[float, float], tuple[float, float]] | None = None,
    edges: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    neighbors = {index: set() for index in range(len(junctions))}
    for left in range(len(junctions)):
        for right in range(left + 1, len(junctions)):
            if _distance(junctions[left], junctions[right]) <= radius_m:
                neighbors[left].add(right)
                neighbors[right].add(left)

    remaining = set(range(len(junctions)))
    clusters = []
    while remaining:
        start = remaining.pop()
        component = {start}
        queue: deque[int] = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor in neighbors[current]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        if len(component) >= min_cluster_nodes:
            clusters.append(
                _cluster_summary(junctions, component, radius_m, xy_to_latlon=xy_to_latlon, edges=edges or [])
            )
    clusters.sort(key=lambda cluster: (-cluster["node_count"], cluster["centroid_x"], cluster["centroid_y"]))
    for index, cluster in enumerate(clusters, start=1):
        cluster["cluster_id"] = f"C{index:03d}"
    return clusters


def _cluster_summary(
    junctions: list[dict[str, Any]],
    component: set[int],
    radius_m: float,
    *,
    xy_to_latlon: Callable[[float, float], tuple[float, float]] | None,
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    nodes = [junctions[index] for index in sorted(component, key=lambda item: junctions[item]["id"])]
    centroid_x = sum(node["x"] for node in nodes) / len(nodes)
    centroid_y = sum(node["y"] for node in nodes) / len(nodes)
    max_pair_distance = 0.0
    for left in range(len(nodes)):
        for right in range(left + 1, len(nodes)):
            max_pair_distance = max(max_pair_distance, _distance(nodes[left], nodes[right]))
    lat, lon, coordinate_status = _cluster_latlon(centroid_x, centroid_y, xy_to_latlon)
    junction_by_id = {str(junction["id"]): junction for junction in junctions}
    graph = _cluster_graph_summary(nodes, edges, junction_by_id)
    return {
        "cluster_id": "",
        "node_count": len(nodes),
        "node_ids": [str(node["id"]) for node in nodes],
        "node_types": [str(node["type"]) for node in nodes],
        "centroid_x": round(centroid_x, 3),
        "centroid_y": round(centroid_y, 3),
        "centroid_lat": round(lat, 7),
        "centroid_lon": round(lon, 7),
        "coordinate_status": coordinate_status,
        "map_review_source": "Google Maps default map",
        "google_maps_url": _google_maps_default_url(lat, lon),
        "optional_google_maps_satellite_url": _google_maps_satellite_url(lat, lon),
        "manual_correction_status": "needs_map_review",
        "suggested_correction_action": "compare the Google Maps road/intersection footprint before joining SUMO junctions",
        **graph,
        "max_pair_distance_m": round(max_pair_distance, 3),
        "cluster_radius_m": radius_m,
    }


def _distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    return math.hypot(float(left["x"]) - float(right["x"]), float(left["y"]) - float(right["y"]))


def _cluster_graph_summary(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    junction_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    node_ids = {str(node["id"]) for node in nodes}
    traffic_light_count = sum(1 for node in nodes if str(node["type"]) == "traffic_light")
    internal_edges = []
    boundary_edges = []
    external_junction_ids = set()
    connected_pairs = set()
    endpoint_pair_counts: dict[tuple[str, str], int] = {}
    internal_length_total = 0.0
    internal_length_max = 0.0

    for edge in edges:
        from_node = str(edge["from"])
        to_node = str(edge["to"])
        from_inside = from_node in node_ids
        to_inside = to_node in node_ids
        if from_inside and to_inside:
            internal_edges.append(edge)
            connected_pairs.add(_node_pair_label(from_node, to_node))
            endpoint_pair = tuple(sorted((from_node, to_node)))
            endpoint_pair_counts[endpoint_pair] = endpoint_pair_counts.get(endpoint_pair, 0) + 1
            length = float(edge.get("length") or 0.0)
            internal_length_total += length
            internal_length_max = max(internal_length_max, length)
        elif from_inside or to_inside:
            boundary_edges.append(edge)
            external_junction_ids.add(to_node if from_inside else from_node)

    overlap_pair_count = sum((count * (count - 1)) // 2 for count in endpoint_pair_counts.values() if count > 1)
    physical_shape = _physical_intersection_shape_score(
        nodes=nodes,
        internal_edges=internal_edges,
        boundary_edges=boundary_edges,
        junction_by_id=junction_by_id,
    )
    risk_flags = _cluster_risk_flags(
        node_count=len(nodes),
        traffic_light_count=traffic_light_count,
        internal_edge_count=len(internal_edges),
        boundary_edge_count=len(boundary_edges),
        approach_count=len(external_junction_ids),
        overlap_pair_count=overlap_pair_count,
    )
    aggregation_score = _reference_free_aggregation_score(
        node_count=len(nodes),
        traffic_light_count=traffic_light_count,
        internal_edges=internal_edges,
        boundary_edges=boundary_edges,
        approach_count=len(external_junction_ids),
        internal_edge_max_length=internal_length_max,
        overlap_pair_count=overlap_pair_count,
        physical_shape=physical_shape,
    )
    return {
        "internal_edge_ids": sorted(str(edge["id"]) for edge in internal_edges),
        "boundary_edge_ids": sorted(str(edge["id"]) for edge in boundary_edges),
        "external_junction_ids": sorted(external_junction_ids),
        "connected_node_pairs": sorted(connected_pairs),
        "internal_edge_count": len(internal_edges),
        "boundary_edge_count": len(boundary_edges),
        "approach_count": len(external_junction_ids),
        "direct_connected_node_pair_count": len(connected_pairs),
        "traffic_light_node_count": traffic_light_count,
        "internal_edge_total_length_m": round(internal_length_total, 3),
        "internal_edge_max_length_m": round(internal_length_max, 3),
        "internal_edge_overlap_pair_count": overlap_pair_count,
        "aggregation_recommendation": _aggregation_recommendation(
            internal_edge_count=len(internal_edges),
            boundary_edge_count=len(boundary_edges),
            approach_count=len(external_junction_ids),
        ),
        **aggregation_score,
        "risk_flags": risk_flags,
    }


def _node_pair_label(from_node: str, to_node: str) -> str:
    left, right = sorted((from_node, to_node))
    return f"{left}<->{right}"


def _cluster_risk_flags(
    *,
    node_count: int,
    traffic_light_count: int,
    internal_edge_count: int,
    boundary_edge_count: int,
    approach_count: int,
    overlap_pair_count: int,
) -> list[str]:
    flags = ["map_review_required"]
    if internal_edge_count == 0:
        flags.append("no_internal_edges")
    if boundary_edge_count == 0:
        flags.append("no_boundary_edges")
    if traffic_light_count > 0 and approach_count < 3:
        flags.append("few_approaches_for_signalized_cluster")
    if overlap_pair_count > 0:
        flags.append("overlapping_internal_edges")
    if internal_edge_count >= max(node_count, 1):
        flags.append("many_internal_edges")
    if node_count >= 10:
        flags.append("large_cluster")
    return flags


def _aggregation_recommendation(*, internal_edge_count: int, boundary_edge_count: int, approach_count: int) -> str:
    if internal_edge_count > 0 and boundary_edge_count > 0 and approach_count >= 2:
        return "map_review_join_candidate"
    if internal_edge_count > 0:
        return "inspect_cluster_graph"
    return "map_review_required"


def _reference_free_aggregation_score(
    *,
    node_count: int,
    traffic_light_count: int,
    internal_edges: list[dict[str, Any]],
    boundary_edges: list[dict[str, Any]],
    approach_count: int,
    internal_edge_max_length: float,
    overlap_pair_count: int,
    physical_shape: dict[str, Any],
) -> dict[str, Any]:
    internal_edge_count = len(internal_edges)
    boundary_edge_count = len(boundary_edges)
    short_internal_edge_score = _short_internal_edge_score(internal_edge_count, internal_edge_max_length)
    same_road_name_score = _same_road_name_score(internal_edges + boundary_edges)
    traffic_signal_density = round(traffic_light_count / node_count, 3) if node_count else 0.0
    service_or_parking_risk = _edge_text_has(
        internal_edges + boundary_edges,
        {"service", "parking", "private", "driveway"},
    )
    bridge_tunnel_layer_risk = _edge_text_has(
        internal_edges + boundary_edges,
        {"bridge", "tunnel", "layer"},
    )
    roundabout_or_slip_lane_risk = _edge_text_has(
        internal_edges + boundary_edges,
        {"roundabout", "slip"},
    )
    physical_intersection_shape = str(physical_shape.get("physical_intersection_shape", "none"))
    physical_intersection_score = float(physical_shape.get("physical_intersection_score", 0.0) or 0.0)
    has_stable_cross_or_t_shape = (
        physical_intersection_shape in {"cross", "t_or_y"} and physical_intersection_score >= 0.6
    )

    decision = "join"
    confidence = "medium"
    reason_parts = []
    if internal_edge_count == 0:
        decision = "do_not_join"
        confidence = "high"
        reason_parts.append("no internal edges connect the dense nodes")
    if boundary_edge_count == 0:
        decision = "do_not_join"
        confidence = "high"
        reason_parts.append("no boundary approaches leave the cluster")
    if approach_count < 2:
        decision = "do_not_join"
        confidence = "high"
        reason_parts.append("too few external approaches for a physical intersection")
    if decision != "do_not_join" and not has_stable_cross_or_t_shape:
        decision = "needs_map_review"
        confidence = "low"
        reason_parts.append("no stable cross/T intersection shape from approach axes")

    review_risks = []
    if traffic_light_count > 0:
        review_risks.append("traffic-signal semantics require map review")
    if overlap_pair_count > 0:
        review_risks.append("overlapping internal edges require map review")
    if node_count >= 10:
        review_risks.append("large cluster requires map review")
    if approach_count >= 6:
        review_risks.append("many approaches require map review")
    if service_or_parking_risk:
        review_risks.append("service or parking access risk requires map review")
    if bridge_tunnel_layer_risk:
        review_risks.append("bridge, tunnel, or layer risk requires map review")
    if roundabout_or_slip_lane_risk:
        review_risks.append("roundabout or slip-lane risk requires map review")
    if decision != "do_not_join" and review_risks:
        decision = "needs_map_review"
        confidence = "low"
        reason_parts.extend(review_risks)

    if decision == "join":
        reason_parts.append(
            f"short internal edges and {physical_intersection_shape} approach-axis geometry indicate one physical junction candidate"
        )
    elif not reason_parts:
        reason_parts.append("insufficient topology evidence for automatic joining")

    return {
        "reference_free_scorer": "topology_heuristic_v1",
        "aggregation_decision": decision,
        "aggregation_confidence": confidence,
        "aggregation_reason": "; ".join(reason_parts),
        "short_internal_edge_score": short_internal_edge_score,
        "same_road_name_score": same_road_name_score,
        **physical_shape,
        "traffic_signal_density": traffic_signal_density,
        "service_or_parking_risk": service_or_parking_risk,
        "bridge_tunnel_layer_risk": bridge_tunnel_layer_risk,
        "roundabout_or_slip_lane_risk": roundabout_or_slip_lane_risk,
    }


def _physical_intersection_shape_score(
    *,
    nodes: list[dict[str, Any]],
    internal_edges: list[dict[str, Any]],
    boundary_edges: list[dict[str, Any]],
    junction_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not nodes:
        return _empty_physical_shape()

    node_ids = {str(node["id"]) for node in nodes}
    centroid_x = sum(float(node["x"]) for node in nodes) / len(nodes)
    centroid_y = sum(float(node["y"]) for node in nodes) / len(nodes)
    external_nodes: dict[str, dict[str, Any]] = {}
    for edge in boundary_edges:
        from_node = str(edge.get("from", ""))
        to_node = str(edge.get("to", ""))
        if from_node in node_ids and to_node in junction_by_id:
            external_nodes[to_node] = junction_by_id[to_node]
        elif to_node in node_ids and from_node in junction_by_id:
            external_nodes[from_node] = junction_by_id[from_node]

    arms = []
    for external_node in external_nodes.values():
        dx = float(external_node["x"]) - centroid_x
        dy = float(external_node["y"]) - centroid_y
        if math.hypot(dx, dy) <= 1e-6:
            continue
        arms.append(_axis_angle_deg(dx, dy))

    axis_groups = _group_approach_axes(arms)
    axis_angles = [round(group["mean_angle_deg"], 1) for group in axis_groups]
    axis_arm_counts = [len(group["angles"]) for group in axis_groups]
    dominant_axis_separation = 0.0
    angle_continuity_score = 0.0
    physical_shape = "none"
    shape_score = 0.0

    if len(axis_groups) >= 2:
        dominant_axis_separation = _axis_angle_distance(
            axis_groups[0]["mean_angle_deg"],
            axis_groups[1]["mean_angle_deg"],
        )
        angle_continuity_score = max(0.0, 1.0 - abs(90.0 - dominant_axis_separation) / 45.0)
        if len(arms) >= 4 and axis_arm_counts[0] >= 2 and axis_arm_counts[1] >= 2 and 65.0 <= dominant_axis_separation <= 115.0:
            physical_shape = "cross"
            shape_score = 0.72 + 0.28 * angle_continuity_score
        elif len(arms) >= 3 and axis_arm_counts[0] >= 2 and 45.0 <= dominant_axis_separation <= 135.0:
            physical_shape = "t_or_y"
            shape_score = 0.55 + 0.30 * angle_continuity_score
        elif len(arms) >= 5:
            physical_shape = "multi_arm"
            shape_score = 0.45

    short_internal_edge_score = _short_internal_edge_score(
        len(internal_edges),
        max((float(edge.get("length") or 0.0) for edge in internal_edges), default=0.0),
    )
    physical_intersection_score = min(1.0, shape_score * 0.72 + short_internal_edge_score * 0.28)
    return {
        "physical_intersection_shape": physical_shape,
        "physical_intersection_score": round(physical_intersection_score, 3),
        "approach_axis_count": len(axis_groups),
        "approach_axis_angles_deg": axis_angles,
        "approach_axis_arm_counts": axis_arm_counts,
        "dominant_axis_separation_deg": round(dominant_axis_separation, 1),
        "angle_continuity_score": round(angle_continuity_score, 3),
    }


def _empty_physical_shape() -> dict[str, Any]:
    return {
        "physical_intersection_shape": "none",
        "physical_intersection_score": 0.0,
        "approach_axis_count": 0,
        "approach_axis_angles_deg": [],
        "approach_axis_arm_counts": [],
        "dominant_axis_separation_deg": 0.0,
        "angle_continuity_score": 0.0,
    }


def _axis_angle_deg(dx: float, dy: float) -> float:
    return math.degrees(math.atan2(dy, dx)) % 180.0


def _axis_angle_distance(left: float, right: float) -> float:
    distance = abs(left - right) % 180.0
    return min(distance, 180.0 - distance)


def _group_approach_axes(angles: list[float], *, tolerance_deg: float = 18.0) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for angle in sorted(angles):
        placed = False
        for group in groups:
            if _axis_angle_distance(float(group["mean_angle_deg"]), angle) <= tolerance_deg:
                group["angles"].append(angle)
                group["mean_angle_deg"] = _mean_axis_angle(group["angles"])
                placed = True
                break
        if not placed:
            groups.append({"mean_angle_deg": angle, "angles": [angle]})
    groups.sort(key=lambda group: (-len(group["angles"]), float(group["mean_angle_deg"])))
    return groups


def _mean_axis_angle(angles: list[float]) -> float:
    if not angles:
        return 0.0
    x = sum(math.cos(math.radians(2.0 * angle)) for angle in angles)
    y = sum(math.sin(math.radians(2.0 * angle)) for angle in angles)
    return (math.degrees(math.atan2(y, x)) / 2.0) % 180.0


def _short_internal_edge_score(internal_edge_count: int, internal_edge_max_length: float) -> float:
    if internal_edge_count == 0:
        return 0.0
    if internal_edge_max_length <= 10.0:
        return 1.0
    if internal_edge_max_length >= 30.0:
        return 0.0
    return round((30.0 - internal_edge_max_length) / 20.0, 3)


def _same_road_name_score(edges: list[dict[str, Any]]) -> float:
    names = [str(edge.get("name", "")).strip().lower() for edge in edges if str(edge.get("name", "")).strip()]
    if not names:
        return 0.0
    most_common = Counter(names).most_common(1)[0][1]
    return round(most_common / len(names), 3)


def _edge_text_has(edges: list[dict[str, Any]], tokens: set[str]) -> bool:
    for edge in edges:
        text = " ".join(
            [
                str(edge.get("id", "")),
                str(edge.get("type", "")),
                str(edge.get("name", "")),
            ]
        ).lower()
        if any(token in text for token in tokens):
            return True
    return False


def _edge_shape(edge: ET.Element, lanes: list[ET.Element]) -> list[tuple[float, float]]:
    shape_text = edge.attrib.get("shape", "")
    if not shape_text and lanes:
        shape_text = lanes[0].attrib.get("shape", "")
    return _parse_shape(shape_text)


def _parse_shape(shape_text: str) -> list[tuple[float, float]]:
    points = []
    for raw_point in shape_text.split():
        parts = raw_point.split(",")
        if len(parts) < 2:
            continue
        points.append((float(parts[0]), float(parts[1])))
    return points


def _edge_length(shape: list[tuple[float, float]], lanes: list[ET.Element]) -> float:
    if lanes and lanes[0].attrib.get("length"):
        return float(lanes[0].attrib["length"])
    if len(shape) < 2:
        return 0.0
    return sum(math.hypot(right[0] - left[0], right[1] - left[1]) for left, right in zip(shape, shape[1:]))


def _coordinate_converter(net_file: Path) -> Callable[[float, float], tuple[float, float]] | None:
    try:
        import sumolib  # type: ignore

        net = sumolib.net.readNet(str(net_file))
        return lambda x, y: _net_xy_to_latlon(net, x, y)
    except Exception:
        return None


def _cluster_latlon(
    centroid_x: float,
    centroid_y: float,
    xy_to_latlon: Callable[[float, float], tuple[float, float]] | None,
) -> tuple[float, float, str]:
    if xy_to_latlon is None:
        return centroid_y, centroid_x, "xy_fallback_no_geo_projection"
    try:
        lat, lon = xy_to_latlon(centroid_x, centroid_y)
    except Exception:
        return centroid_y, centroid_x, "xy_fallback_geo_projection_failed"
    return lat, lon, "wgs84_from_sumo_projection"


def _google_maps_default_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/@{lat:.7f},{lon:.7f},50m"


def _google_maps_satellite_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/@{lat:.7f},{lon:.7f},50m/data=!3m1!1e3"


def _write_clusters_csv(path: Path, clusters: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "cluster_id",
                "node_count",
                "node_ids",
                "node_types",
                "centroid_x",
                "centroid_y",
                "centroid_lat",
                "centroid_lon",
                "coordinate_status",
                "map_review_source",
                "google_maps_url",
                "optional_google_maps_satellite_url",
                "manual_correction_status",
                "suggested_correction_action",
                "internal_edge_count",
                "boundary_edge_count",
                "approach_count",
                "direct_connected_node_pair_count",
                "traffic_light_node_count",
                "internal_edge_total_length_m",
                "internal_edge_max_length_m",
                "internal_edge_overlap_pair_count",
                "aggregation_recommendation",
                "reference_free_scorer",
                "aggregation_decision",
                "aggregation_confidence",
                "aggregation_reason",
                "short_internal_edge_score",
                "same_road_name_score",
                "physical_intersection_shape",
                "physical_intersection_score",
                "approach_axis_count",
                "approach_axis_angles_deg",
                "approach_axis_arm_counts",
                "dominant_axis_separation_deg",
                "angle_continuity_score",
                "traffic_signal_density",
                "service_or_parking_risk",
                "bridge_tunnel_layer_risk",
                "roundabout_or_slip_lane_risk",
                "risk_flags",
                "internal_edge_ids",
                "boundary_edge_ids",
                "external_junction_ids",
                "connected_node_pairs",
                "max_pair_distance_m",
                "cluster_radius_m",
            ],
        )
        writer.writeheader()
        for cluster in clusters:
            row = dict(cluster)
            for field in (
                "node_ids",
                "node_types",
                "risk_flags",
                "internal_edge_ids",
                "boundary_edge_ids",
                "external_junction_ids",
                "connected_node_pairs",
                "approach_axis_angles_deg",
                "approach_axis_arm_counts",
            ):
                row[field] = ";".join(str(item) for item in row[field])
            writer.writerow(row)

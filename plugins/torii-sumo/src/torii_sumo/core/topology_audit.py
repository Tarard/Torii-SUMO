from __future__ import annotations

import csv
import json
import math
from collections import deque
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


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
        junctions = _read_eligible_junctions(net_file)
    except (OSError, ET.ParseError, KeyError, ValueError) as exc:
        return _failure(f"{type(exc).__name__}: {exc}")

    clusters = _dense_clusters(junctions, radius_m=cluster_radius_m, min_cluster_nodes=min_cluster_nodes)
    output_dir.mkdir(parents=True, exist_ok=True)
    clusters_file = output_dir / f"{prefix}_dense_junction_clusters.csv"
    report_file = output_dir / f"{prefix}_topology_audit.json"
    _write_clusters_csv(clusters_file, clusters)

    status = "blocked" if clusters else "pass"
    warnings = []
    if clusters:
        warnings.append(f"topology audit found {len(clusters)} suspicious dense junction cluster(s)")

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


def _read_eligible_junctions(net_file: Path) -> list[dict[str, Any]]:
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
    return junctions


def _dense_clusters(
    junctions: list[dict[str, Any]],
    *,
    radius_m: float,
    min_cluster_nodes: int,
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
            clusters.append(_cluster_summary(junctions, component, radius_m))
    clusters.sort(key=lambda cluster: (-cluster["node_count"], cluster["centroid_x"], cluster["centroid_y"]))
    for index, cluster in enumerate(clusters, start=1):
        cluster["cluster_id"] = f"C{index:03d}"
    return clusters


def _cluster_summary(junctions: list[dict[str, Any]], component: set[int], radius_m: float) -> dict[str, Any]:
    nodes = [junctions[index] for index in sorted(component, key=lambda item: junctions[item]["id"])]
    centroid_x = sum(node["x"] for node in nodes) / len(nodes)
    centroid_y = sum(node["y"] for node in nodes) / len(nodes)
    max_pair_distance = 0.0
    for left in range(len(nodes)):
        for right in range(left + 1, len(nodes)):
            max_pair_distance = max(max_pair_distance, _distance(nodes[left], nodes[right]))
    return {
        "cluster_id": "",
        "node_count": len(nodes),
        "node_ids": [str(node["id"]) for node in nodes],
        "node_types": [str(node["type"]) for node in nodes],
        "centroid_x": round(centroid_x, 3),
        "centroid_y": round(centroid_y, 3),
        "max_pair_distance_m": round(max_pair_distance, 3),
        "cluster_radius_m": radius_m,
    }


def _distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    return math.hypot(float(left["x"]) - float(right["x"]), float(left["y"]) - float(right["y"]))


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
                "max_pair_distance_m",
                "cluster_radius_m",
            ],
        )
        writer.writeheader()
        for cluster in clusters:
            row = dict(cluster)
            row["node_ids"] = ";".join(row["node_ids"])
            row["node_types"] = ";".join(row["node_types"])
            writer.writerow(row)

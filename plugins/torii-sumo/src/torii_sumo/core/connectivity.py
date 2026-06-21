from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .osm_network import read_net_edges


def _failure(error_message: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "claim_status": "construction-invalid",
        "connectivity_status": "fail",
        "error": error_message,
    }


def _weak_components(edge_ids: set[str], connections: dict[str, set[str]]) -> list[set[str]]:
    neighbors = {edge_id: set() for edge_id in edge_ids}
    for from_edge, to_edges in connections.items():
        if from_edge not in edge_ids:
            continue
        for to_edge in to_edges:
            if to_edge not in edge_ids:
                continue
            neighbors[from_edge].add(to_edge)
            neighbors[to_edge].add(from_edge)

    remaining = set(edge_ids)
    components = []
    while remaining:
        start = remaining.pop()
        component = {start}
        queue: deque[str] = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor in neighbors[current]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        components.append(component)
    return components


def summarize_passenger_connectivity(
    net_file: Path,
    *,
    small_component_threshold: int = 3,
) -> dict[str, Any]:
    try:
        edges, connections = read_net_edges(net_file)
    except (OSError, ET.ParseError, KeyError, ValueError) as exc:
        return _failure(f"{type(exc).__name__}: {exc}")

    passenger_edges = {
        edge_id
        for edge_id, edge in edges.items()
        if edge.allows_passenger
    }
    if not passenger_edges:
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "connectivity_status": "fail",
            "net_file": str(net_file),
            "passenger_edge_count": 0,
            "passenger_component_count": 0,
            "largest_component_edge_count": 0,
            "small_component_count": 0,
            "isolated_passenger_edge_count": 0,
            "warnings": ["network has no passenger-allowed edges"],
        }

    passenger_connections = {
        from_edge: {to_edge for to_edge in to_edges if to_edge in passenger_edges}
        for from_edge, to_edges in connections.items()
        if from_edge in passenger_edges
    }
    components = _weak_components(passenger_edges, passenger_connections)
    component_sizes = sorted((len(component) for component in components), reverse=True)
    connected_edges = set(passenger_connections)
    for to_edges in passenger_connections.values():
        connected_edges.update(to_edges)
    isolated_edges = passenger_edges - connected_edges
    small_components = []
    if len(components) != 1:
        small_components = [
            component
            for component in components
            if len(component) <= small_component_threshold
        ]

    warnings = []
    if len(components) != 1:
        warnings.append(f"passenger network has {len(components)} disconnected components")
    if isolated_edges:
        warnings.append(f"passenger network has {len(isolated_edges)} isolated passenger edges")

    ok = len(components) == 1 and not isolated_edges
    return {
        "status": "pass" if ok else "fail",
        "claim_status": "diagnostic-demo" if ok else "construction-invalid",
        "connectivity_status": "pass" if ok else "fail",
        "net_file": str(net_file),
        "passenger_edge_count": len(passenger_edges),
        "passenger_component_count": len(components),
        "largest_component_edge_count": component_sizes[0] if component_sizes else 0,
        "small_component_count": len(small_components),
        "isolated_passenger_edge_count": len(isolated_edges),
        "component_sizes": component_sizes,
        "warnings": warnings,
    }

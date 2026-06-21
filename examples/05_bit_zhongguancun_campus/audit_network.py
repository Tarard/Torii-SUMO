from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import sumolib


ROOT = Path(__file__).resolve().parent
NET_PATHS = [
    ROOT / "bit_zhongguancun.net.xml",
    ROOT / "bit_zhongguancun.raw.net.xml",
    ROOT / "bit_zhongguancun.connected-core.net.xml",
]
OUT_PATH = ROOT / "network-audit.json"


def audit_network(net_path: Path) -> dict[str, object]:
    net = sumolib.net.readNet(str(net_path), withPrograms=True)
    edges = [edge for edge in net.getEdges() if not edge.getFunction()]
    passenger_edges = [
        edge
        for edge in edges
        if any(lane.allows("passenger") for lane in edge.getLanes())
    ]
    lane_count = sum(len(edge.getLanes()) for edge in passenger_edges)
    total_lane_length_m = sum(
        lane.getLength() for edge in passenger_edges for lane in edge.getLanes()
    )
    tls = net.getTrafficLights()
    node_types = Counter(node.getType() for node in net.getNodes())

    # Weak connectivity over passenger edges: enough to detect fragmented imports.
    adjacency: dict[str, set[str]] = {}
    for edge in passenger_edges:
        from_id = edge.getFromNode().getID()
        to_id = edge.getToNode().getID()
        adjacency.setdefault(from_id, set()).add(to_id)
        adjacency.setdefault(to_id, set()).add(from_id)
    seen: set[str] = set()
    components: list[int] = []
    for node_id in adjacency:
        if node_id in seen:
            continue
        stack = [node_id]
        seen.add(node_id)
        size = 0
        while stack:
            current = stack.pop()
            size += 1
            for nxt in adjacency.get(current, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        components.append(size)
    components.sort(reverse=True)

    return {
        "network": str(net_path),
        "edge_count": len(edges),
        "passenger_edge_count": len(passenger_edges),
        "passenger_lane_count": lane_count,
        "passenger_lane_length_m": round(total_lane_length_m, 2),
        "junction_count": len(net.getNodes()),
        "node_types": dict(sorted(node_types.items())),
        "traffic_light_count": len(tls),
        "traffic_light_ids": [tls_obj.getID() for tls_obj in tls],
        "weak_passenger_components": components,
        "largest_weak_passenger_component_nodes": components[0] if components else 0,
    }


def main() -> None:
    audits = [audit_network(path) for path in NET_PATHS if path.exists()]
    OUT_PATH.write_text(json.dumps(audits, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(audits, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET


SERVICE_PASSENGER_POLICIES = ("sumo_default", "allow_vehicle_service", "reference_match")


def _normalized_policy(policy: str | None) -> str:
    normalized = (policy or "sumo_default").strip().lower()
    if normalized in SERVICE_PASSENGER_POLICIES:
        return normalized
    return "sumo_default"


def _is_service_edge(edge: ET.Element) -> bool:
    edge_type = edge.attrib.get("type", "").strip().lower()
    return edge_type == "service" or edge_type.endswith(".service")


def _add_passenger_to_lane(lane: ET.Element) -> bool:
    allow_value = lane.attrib.get("allow", "").strip()
    disallow_value = lane.attrib.get("disallow", "").strip()
    changed = False
    if allow_value:
        allowed = allow_value.split()
        if "passenger" not in allowed:
            allowed.append("passenger")
            lane.set("allow", " ".join(sorted(dict.fromkeys(allowed))))
            changed = True
    elif "passenger" in disallow_value.split():
        disallowed = [item for item in disallow_value.split() if item != "passenger"]
        if disallowed:
            lane.set("disallow", " ".join(disallowed))
        else:
            lane.attrib.pop("disallow", None)
        changed = True
    return changed


def apply_service_passenger_permissions(net_file: Path, *, policy: str | None = None) -> dict[str, object]:
    selected_policy = _normalized_policy(policy)
    if selected_policy == "sumo_default":
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "service_passenger_permission_status": "skipped",
            "service_passenger_policy": selected_policy,
            "service_edge_count": 0,
            "changed_edge_count": 0,
            "changed_lane_count": 0,
            "warnings": [],
        }
    if not net_file.exists():
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "service_passenger_permission_status": "failed",
            "service_passenger_policy": selected_policy,
            "service_edge_count": 0,
            "changed_edge_count": 0,
            "changed_lane_count": 0,
            "warnings": [f"net file not found for service passenger permissions: {net_file}"],
        }

    tree = ET.parse(net_file)
    root = tree.getroot()
    service_edge_count = 0
    changed_edge_count = 0
    changed_lane_count = 0
    for edge in root.findall("edge"):
        if edge.attrib.get("function") == "internal" or not _is_service_edge(edge):
            continue
        service_edge_count += 1
        edge_changed = False
        for lane in edge.findall("lane"):
            if _add_passenger_to_lane(lane):
                changed_lane_count += 1
                edge_changed = True
        if edge_changed:
            changed_edge_count += 1

    if changed_lane_count:
        tree.write(net_file, encoding="utf-8", xml_declaration=True)

    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "service_passenger_permission_status": "applied",
        "service_passenger_policy": selected_policy,
        "service_edge_count": service_edge_count,
        "changed_edge_count": changed_edge_count,
        "changed_lane_count": changed_lane_count,
        "warnings": [],
    }

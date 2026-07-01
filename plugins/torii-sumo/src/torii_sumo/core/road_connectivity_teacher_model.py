from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


def canonical_road_connectivity_bundle(
    net_file: Path,
    *,
    seed_edge_ids: list[str],
    hop_radius: int = 1,
) -> dict[str, Any]:
    root = ET.parse(net_file).getroot()
    edges = {edge.attrib["id"]: edge for edge in root.findall("edge") if edge.attrib.get("id")}
    missing_seed_edge_ids = sorted(edge_id for edge_id in seed_edge_ids if edge_id not in edges)
    selected = {edge_id for edge_id in seed_edge_ids if edge_id in edges and not edge_id.startswith(":")}
    for _ in range(max(0, hop_radius)):
        endpoints = {
            value
            for edge_id in selected
            for value in (edges[edge_id].attrib.get("from", ""), edges[edge_id].attrib.get("to", ""))
            if value
        }
        selected.update(
            edge_id
            for edge_id, edge in edges.items()
            if not edge_id.startswith(":")
            and (edge.attrib.get("from", "") in endpoints or edge.attrib.get("to", "") in endpoints)
        )

    selected_junction_ids = {
        value
        for edge_id in selected
        for value in (edges[edge_id].attrib.get("from", ""), edges[edge_id].attrib.get("to", ""))
        if value
    }
    selected_lane_ids = {
        lane.attrib["id"]
        for edge_id in selected
        for lane in edges[edge_id].findall("lane")
        if lane.attrib.get("id")
    }
    junctions = {
        junction.attrib["id"]: junction
        for junction in root.findall("junction")
        if junction.attrib.get("id")
    }
    connections = [
        _canonical_road_connection_record(connection)
        for connection in root.findall("connection")
        if connection.attrib.get("from", "") in selected and connection.attrib.get("to", "") in selected
    ]
    request_counts = _request_counts_by_junction(connections, edges)
    bundle = {
        "net": _sorted_attrs(root),
        "location": _sorted_attrs(root.find("location")),
        "edges": [_canonical_edge_record(edges[edge_id]) for edge_id in sorted(selected)],
        "junctions": [
            _canonical_junction_record(
                junctions[junction_id],
                selected_lane_ids,
                request_counts.get(junction_id, 0),
            )
            for junction_id in sorted(selected_junction_ids)
            if junction_id in junctions
        ],
        "connections": sorted(connections, key=_canonical_connection_sort_key),
    }
    bundle["summary"] = {
        "edge_count": len(bundle["edges"]),
        "junction_count": len(bundle["junctions"]),
        "connection_count": len(bundle["connections"]),
        "missing_reference_count": _missing_reference_count(bundle),
        "seed_edge_count": len(seed_edge_ids),
        "missing_seed_edge_ids": missing_seed_edge_ids,
    }
    return bundle


def write_road_connectivity_self_replay_net(
    teacher_net_file: Path,
    seed_edge_ids: list[str],
    output_file: Path,
    *,
    hop_radius: int = 1,
) -> dict[str, Any]:
    bundle = canonical_road_connectivity_bundle(
        teacher_net_file,
        seed_edge_ids=seed_edge_ids,
        hop_radius=hop_radius,
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root = ET.Element("net", bundle.get("net", {}))
    if bundle["location"]:
        ET.SubElement(root, "location", bundle["location"])
    for edge in bundle["edges"]:
        edge_node = ET.SubElement(root, "edge", _record_attrs(edge, "lanes"))
        for lane in edge.get("lanes", []):
            ET.SubElement(edge_node, "lane", dict(lane))
    for junction in bundle["junctions"]:
        junction_node = ET.SubElement(root, "junction", _record_attrs(junction, "requests"))
        for request in junction.get("requests", []):
            ET.SubElement(junction_node, "request", dict(request))
    for connection in bundle["connections"]:
        ET.SubElement(root, "connection", dict(connection))

    ET.indent(root, space="  ")
    ET.ElementTree(root).write(output_file, encoding="utf-8", xml_declaration=True)
    replay_bundle = canonical_road_connectivity_bundle(
        output_file,
        seed_edge_ids=seed_edge_ids,
        hop_radius=hop_radius,
    )
    parity_delta = {} if bundle == replay_bundle else {"canonical_bundle": 1}
    return {
        "status": "pass" if not parity_delta else "fail",
        "output_file": str(output_file),
        "parity_delta": parity_delta,
    }


def compare_road_connectivity_bundles(
    teacher: dict[str, Any],
    candidate: dict[str, Any],
    *,
    geometry_tolerance: float = 0.5,
) -> dict[str, Any]:
    teacher_edge_ids = _record_ids(teacher.get("edges", []))
    candidate_edge_ids = _record_ids(candidate.get("edges", []))
    common_edge_ids = teacher_edge_ids & candidate_edge_ids
    missing_edges = sorted(teacher_edge_ids - candidate_edge_ids)
    extra_edges = sorted(candidate_edge_ids - teacher_edge_ids)
    geometry_mismatches = _common_edge_geometry_mismatches(
        teacher,
        candidate,
        common_edge_ids,
        geometry_tolerance,
    )
    missing_connections = _missing_records(teacher.get("connections", []), candidate.get("connections", []))
    extra_connections = _missing_records(candidate.get("connections", []), teacher.get("connections", []))
    candidate_missing_seed_edge_ids = sorted(
        str(edge_id)
        for edge_id in candidate.get("summary", {}).get("missing_seed_edge_ids", [])
    )
    status = "fail" if any(
        [
            candidate_missing_seed_edge_ids,
            missing_edges,
            extra_edges,
            geometry_mismatches,
            missing_connections,
            extra_connections,
        ]
    ) else "pass"
    return {
        "status": status,
        "candidate_missing_seed_edge_ids": candidate_missing_seed_edge_ids,
        "edge_ids": {
            "missing_in_candidate": missing_edges,
            "extra_in_candidate": extra_edges,
        },
        "common_edge_geometry_mismatches": geometry_mismatches,
        "connections": {
            "missing_in_candidate": missing_connections,
            "extra_in_candidate": extra_connections,
        },
        "summary": {
            "teacher_edge_count": len(teacher.get("edges", [])),
            "candidate_edge_count": len(candidate.get("edges", [])),
            "common_edge_count": len(common_edge_ids),
            "common_edge_geometry_mismatch_count": len(geometry_mismatches),
            "teacher_connection_count": len(teacher.get("connections", [])),
            "candidate_connection_count": len(candidate.get("connections", [])),
        },
    }


def compare_road_template_summaries(
    teacher_templates: list[dict[str, Any]],
    candidate_templates: list[dict[str, Any]],
    *,
    key_fields: list[str],
) -> dict[str, Any]:
    teacher_by_key = {
        _template_summary_key(template, key_fields): template
        for template in teacher_templates
    }
    candidate_by_key = {
        _template_summary_key(template, key_fields): template
        for template in candidate_templates
    }
    common_keys = set(teacher_by_key) & set(candidate_by_key)
    missing_templates = _sort_templates_by_count(
        teacher_by_key[key] for key in set(teacher_by_key) - set(candidate_by_key)
    )
    extra_templates = _sort_templates_by_count(
        candidate_by_key[key] for key in set(candidate_by_key) - set(teacher_by_key)
    )
    common_count_delta_sum = sum(
        abs(
            int(teacher_by_key[key].get("count", 0))
            - int(candidate_by_key[key].get("count", 0))
        )
        for key in common_keys
    )
    status = "fail" if missing_templates or extra_templates or common_count_delta_sum else "pass"
    return {
        "status": status,
        "missing_template_count": len(missing_templates),
        "extra_template_count": len(extra_templates),
        "common_template_count": len(common_keys),
        "common_count_delta_sum": common_count_delta_sum,
        "missing_templates": missing_templates,
        "extra_templates": extra_templates,
    }


def build_road_template_repair_queue(
    parity_report: dict[str, Any],
    *,
    max_items: int = 10,
) -> list[dict[str, Any]]:
    items = []
    for layer, summary_key in (
        ("lane", "lane_template_summary"),
        ("connection", "connection_template_summary"),
    ):
        parity = parity_report.get(summary_key, {}).get("parity", {})
        for difference, template_key in (
            ("missing_teacher_template", "missing_templates"),
            ("extra_candidate_template", "extra_templates"),
        ):
            for template in parity.get(template_key, []):
                if not isinstance(template, dict):
                    continue
                items.append(
                    {
                        "layer": layer,
                        "difference": difference,
                        "priority": int(template.get("count", 0)),
                        "template": dict(template),
                    }
                )
    return sorted(
        items,
        key=lambda item: (
            -int(item["priority"]),
            str(item["layer"]),
            str(item["difference"]),
            _record_key(item["template"]),
        ),
    )[:max_items]


def compare_net_road_template_parity(
    teacher_net_file: Path,
    candidate_net_file: Path,
    *,
    max_examples: int = 3,
) -> dict[str, Any]:
    teacher_lane_templates = summarize_net_road_lane_model_templates(
        teacher_net_file,
        max_examples=max_examples,
    )
    candidate_lane_templates = summarize_net_road_lane_model_templates(
        candidate_net_file,
        max_examples=max_examples,
    )
    teacher_connection_templates = summarize_net_road_connection_templates(
        teacher_net_file,
        max_examples=max_examples,
    )
    candidate_connection_templates = summarize_net_road_connection_templates(
        candidate_net_file,
        max_examples=max_examples,
    )
    lane_parity = compare_road_template_summaries(
        teacher_lane_templates,
        candidate_lane_templates,
        key_fields=["type", "lane_signature"],
    )
    connection_parity = compare_road_template_summaries(
        teacher_connection_templates,
        candidate_connection_templates,
        key_fields=[
            "dir",
            "from_type",
            "from_lane",
            "from_lane_signature",
            "to_type",
            "to_lane",
            "to_lane_signature",
        ],
    )
    status = "pass" if lane_parity["status"] == connection_parity["status"] == "pass" else "fail"
    gate = _road_template_gate_summary(lane_parity, connection_parity)
    report = {
        "status": status,
        "gate": gate,
        "teacher_net_file": str(teacher_net_file),
        "candidate_net_file": str(candidate_net_file),
        "lane_template_summary": {
            "teacher_edge_count": _template_count_total(teacher_lane_templates),
            "candidate_edge_count": _template_count_total(candidate_lane_templates),
            "teacher_template_count": len(teacher_lane_templates),
            "candidate_template_count": len(candidate_lane_templates),
            "parity": lane_parity,
        },
        "connection_template_summary": {
            "teacher_connection_count": _template_count_total(teacher_connection_templates),
            "candidate_connection_count": _template_count_total(candidate_connection_templates),
            "teacher_template_count": len(teacher_connection_templates),
            "candidate_template_count": len(candidate_connection_templates),
            "parity": connection_parity,
        },
    }
    report["repair_queue"] = build_road_template_repair_queue(report)
    return report


def summarize_road_lane_model_templates(
    bundle: dict[str, Any],
    *,
    max_examples: int = 3,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    for edge in bundle.get("edges", []):
        if not isinstance(edge, dict):
            continue
        key = (str(edge.get("type", "")), tuple(_lane_signature(edge)))
        edge_id = str(edge.get("id", ""))
        if edge_id:
            groups.setdefault(key, []).append(edge_id)

    templates = []
    for (edge_type, lane_signature), edge_ids in groups.items():
        templates.append(
            {
                "type": edge_type,
                "lane_signature": list(lane_signature),
                "count": len(edge_ids),
                "example_edge_ids": sorted(edge_ids)[:max_examples],
            }
        )
    return sorted(
        templates,
        key=lambda item: (-int(item["count"]), str(item["type"]), str(item["lane_signature"])),
    )


def summarize_net_road_lane_model_templates(
    net_file: Path,
    *,
    max_examples: int = 3,
) -> list[dict[str, Any]]:
    root = ET.parse(net_file).getroot()
    edges = [
        _canonical_edge_record(edge)
        for edge in root.findall("edge")
        if edge.attrib.get("id")
        and not edge.attrib["id"].startswith(":")
        and edge.attrib.get("function") != "internal"
    ]
    return summarize_road_lane_model_templates(
        {"edges": edges},
        max_examples=max_examples,
    )


def summarize_net_road_connection_templates(
    net_file: Path,
    *,
    max_examples: int = 3,
) -> list[dict[str, Any]]:
    root = ET.parse(net_file).getroot()
    edges = {
        edge.attrib["id"]: _canonical_edge_record(edge)
        for edge in root.findall("edge")
        if edge.attrib.get("id")
        and not edge.attrib["id"].startswith(":")
        and edge.attrib.get("function") != "internal"
    }
    groups: dict[tuple[str, str, str, tuple[str, ...], str, str, tuple[str, ...]], list[str]] = {}
    for connection in root.findall("connection"):
        from_edge = edges.get(connection.attrib.get("from", ""))
        to_edge = edges.get(connection.attrib.get("to", ""))
        if from_edge is None or to_edge is None:
            continue
        from_lane = connection.attrib.get("fromLane", "")
        to_lane = connection.attrib.get("toLane", "")
        key = (
            connection.attrib.get("dir", ""),
            str(from_edge.get("type", "")),
            from_lane,
            tuple(_lane_signature(from_edge)),
            str(to_edge.get("type", "")),
            to_lane,
            tuple(_lane_signature(to_edge)),
        )
        example = f"{connection.attrib.get('from', '')}[{from_lane}]->{connection.attrib.get('to', '')}[{to_lane}]"
        groups.setdefault(key, []).append(example)

    templates = []
    for (
        direction,
        from_type,
        from_lane,
        from_lane_signature,
        to_type,
        to_lane,
        to_lane_signature,
    ), examples in groups.items():
        templates.append(
            {
                "dir": direction,
                "from_type": from_type,
                "from_lane": from_lane,
                "from_lane_signature": list(from_lane_signature),
                "to_type": to_type,
                "to_lane": to_lane,
                "to_lane_signature": list(to_lane_signature),
                "count": len(examples),
                "example_connections": sorted(examples)[:max_examples],
            }
        )
    return sorted(
        templates,
        key=lambda item: (
            -int(item["count"]),
            str(item["dir"]),
            str(item["from_type"]),
            str(item["from_lane"]),
            str(item["to_type"]),
            str(item["to_lane"]),
        ),
    )


def _canonical_edge_record(edge: ET.Element) -> dict[str, Any]:
    return {
        **_sorted_attrs(edge),
        "lanes": [_sorted_attrs(lane) for lane in sorted(edge.findall("lane"), key=_lane_sort_key)],
    }


def _canonical_junction_record(
    junction: ET.Element,
    selected_lane_ids: set[str],
    request_count: int,
) -> dict[str, Any]:
    record = _sorted_attrs(junction)
    record["incLanes"] = " ".join(lane_id for lane_id in record.get("incLanes", "").split() if lane_id in selected_lane_ids)
    record["intLanes"] = " ".join(lane_id for lane_id in record.get("intLanes", "").split() if lane_id in selected_lane_ids)
    record["requests"] = _neutral_requests(request_count)
    return record


def _canonical_road_connection_record(connection: ET.Element) -> dict[str, str]:
    return {
        key: connection.attrib[key]
        for key in ("dir", "from", "fromLane", "state", "to", "toLane")
        if key in connection.attrib
    }


def _request_counts_by_junction(
    connections: list[dict[str, str]],
    edges: dict[str, ET.Element],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for connection in connections:
        source_edge = edges.get(connection.get("from", ""))
        if source_edge is None:
            continue
        junction_id = source_edge.attrib.get("to", "")
        if junction_id:
            counts[junction_id] = counts.get(junction_id, 0) + 1
    return counts


def _neutral_requests(count: int) -> list[dict[str, str]]:
    width = "0" * count
    return [
        {"cont": "0", "foes": width, "index": str(index), "response": width}
        for index in range(count)
    ]


def _record_ids(records: Any) -> set[str]:
    return {
        str(record.get("id", ""))
        for record in records
        if isinstance(record, dict) and record.get("id")
    }


def _missing_records(left: Any, right: Any) -> list[dict[str, Any]]:
    right_keys = {_record_key(record) for record in right if isinstance(record, dict)}
    return [
        dict(record)
        for record in left
        if isinstance(record, dict) and _record_key(record) not in right_keys
    ]


def _record_key(record: dict[str, Any]) -> str:
    return "|".join(f"{key}={record[key]}" for key in sorted(record))


def _template_summary_key(template: dict[str, Any], key_fields: list[str]) -> str:
    return json.dumps(
        {field: template.get(field) for field in key_fields},
        sort_keys=True,
    )


def _sort_templates_by_count(templates: Any) -> list[dict[str, Any]]:
    return sorted(
        (dict(template) for template in templates if isinstance(template, dict)),
        key=lambda template: (-int(template.get("count", 0)), _record_key(template)),
    )


def _template_count_total(templates: list[dict[str, Any]]) -> int:
    return sum(int(template.get("count", 0)) for template in templates)


def _road_template_gate_summary(
    lane_parity: dict[str, Any],
    connection_parity: dict[str, Any],
) -> dict[str, Any]:
    parity_passed = lane_parity["status"] == connection_parity["status"] == "pass"
    road_layer_status = "pass" if parity_passed else "fail"
    return {
        "road_layer_status": road_layer_status,
        "can_enter_junction_replay": road_layer_status == "pass",
        "blocking_reason": "" if road_layer_status == "pass" else "road_template_parity_failed",
        "lane_missing_template_count": int(lane_parity.get("missing_template_count", 0)),
        "connection_missing_template_count": int(connection_parity.get("missing_template_count", 0)),
        "lane_extra_template_count": int(lane_parity.get("extra_template_count", 0)),
        "connection_extra_template_count": int(connection_parity.get("extra_template_count", 0)),
    }


def _common_edge_geometry_mismatches(
    teacher: dict[str, Any],
    candidate: dict[str, Any],
    common_edge_ids: set[str],
    geometry_tolerance: float,
) -> list[dict[str, Any]]:
    teacher_edges = {edge["id"]: edge for edge in teacher.get("edges", []) if isinstance(edge, dict) and edge.get("id")}
    candidate_edges = {edge["id"]: edge for edge in candidate.get("edges", []) if isinstance(edge, dict) and edge.get("id")}
    teacher_offset = _net_offset(teacher)
    candidate_offset = _net_offset(candidate)
    mismatches = []
    for edge_id in sorted(common_edge_ids):
        teacher_edge = teacher_edges[edge_id]
        candidate_edge = candidate_edges[edge_id]
        endpoint_delta = _edge_endpoint_delta(teacher_edge, teacher_offset, candidate_edge, candidate_offset)
        teacher_lane_count = len(teacher_edge.get("lanes", []))
        candidate_lane_count = len(candidate_edge.get("lanes", []))
        if endpoint_delta > geometry_tolerance or teacher_lane_count != candidate_lane_count:
            mismatches.append(
                {
                    "edge_id": edge_id,
                    "endpoint_delta": round(endpoint_delta, 6),
                    "teacher_from": str(teacher_edge.get("from", "")),
                    "candidate_from": str(candidate_edge.get("from", "")),
                    "teacher_to": str(teacher_edge.get("to", "")),
                    "candidate_to": str(candidate_edge.get("to", "")),
                    "teacher_type": str(teacher_edge.get("type", "")),
                    "candidate_type": str(candidate_edge.get("type", "")),
                    "teacher_lane_count": teacher_lane_count,
                    "candidate_lane_count": candidate_lane_count,
                    "teacher_lane_signature": _lane_signature(teacher_edge),
                    "candidate_lane_signature": _lane_signature(candidate_edge),
                }
            )
    return mismatches


def _net_offset(bundle: dict[str, Any]) -> tuple[float, float]:
    raw = str(bundle.get("location", {}).get("netOffset", "0,0"))
    parts = raw.split(",")
    if len(parts) < 2:
        return (0.0, 0.0)
    return (float(parts[0]), float(parts[1]))


def _edge_endpoint_delta(
    teacher_edge: dict[str, Any],
    teacher_offset: tuple[float, float],
    candidate_edge: dict[str, Any],
    candidate_offset: tuple[float, float],
) -> float:
    teacher_points = _lane_world_points(teacher_edge, teacher_offset)
    candidate_points = _lane_world_points(candidate_edge, candidate_offset)
    if len(teacher_points) < 2 or len(candidate_points) < 2:
        return 0.0 if teacher_points == candidate_points else math.inf
    same_direction = _point_distance(teacher_points[0], candidate_points[0]) + _point_distance(
        teacher_points[-1],
        candidate_points[-1],
    )
    reverse_direction = _point_distance(teacher_points[0], candidate_points[-1]) + _point_distance(
        teacher_points[-1],
        candidate_points[0],
    )
    return min(same_direction, reverse_direction)


def _lane_world_points(edge: dict[str, Any], offset: tuple[float, float]) -> list[tuple[float, float]]:
    lanes = edge.get("lanes", [])
    if not lanes:
        return []
    shape = str(lanes[0].get("shape", ""))
    points = []
    for part in shape.split():
        coords = part.split(",")
        if len(coords) < 2:
            continue
        points.append((float(coords[0]) - offset[0], float(coords[1]) - offset[1]))
    return points


def _lane_signature(edge: dict[str, Any]) -> list[str]:
    return [
        f"index={lane.get('index', '')}|allow={lane.get('allow', '')}|disallow={lane.get('disallow', '')}"
        for lane in edge.get("lanes", [])
        if isinstance(lane, dict)
    ]


def _point_distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _sorted_attrs(element: ET.Element | None) -> dict[str, str]:
    return {} if element is None else dict(sorted(element.attrib.items()))


def _record_attrs(record: dict[str, Any], child_key: str) -> dict[str, str]:
    return {str(key): str(value) for key, value in record.items() if key != child_key}


def _missing_reference_count(bundle: dict[str, Any]) -> int:
    edge_ids = {edge["id"] for edge in bundle["edges"]}
    lane_ids = {lane["id"] for edge in bundle["edges"] for lane in edge.get("lanes", [])}
    junction_ids = {junction["id"] for junction in bundle["junctions"]}
    missing = 0
    for edge in bundle["edges"]:
        missing += int(edge.get("from", "") not in junction_ids)
        missing += int(edge.get("to", "") not in junction_ids)
    for junction in bundle["junctions"]:
        missing += sum(1 for lane_id in str(junction.get("incLanes", "")).split() if lane_id not in lane_ids)
        missing += sum(1 for lane_id in str(junction.get("intLanes", "")).split() if lane_id not in lane_ids)
    for connection in bundle["connections"]:
        missing += int(connection.get("from", "") not in edge_ids)
        missing += int(connection.get("to", "") not in edge_ids)
    return missing


def _lane_sort_key(lane: ET.Element) -> tuple[int, str]:
    try:
        index = int(lane.attrib.get("index", "0"))
    except ValueError:
        index = 0
    return (index, lane.attrib.get("id", ""))


def _canonical_connection_sort_key(connection: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        connection.get("from", ""),
        connection.get("fromLane", ""),
        connection.get("to", ""),
        connection.get("toLane", ""),
    )

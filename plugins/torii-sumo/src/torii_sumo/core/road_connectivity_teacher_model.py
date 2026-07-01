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


def build_road_lane_template_repair_candidates(
    parity_report: dict[str, Any],
    *,
    max_items: int = 10,
) -> list[dict[str, Any]]:
    parity = parity_report.get("lane_template_summary", {}).get("parity", {})
    missing_templates = _sort_templates_by_count(parity.get("missing_templates", []))
    extra_templates = _sort_templates_by_count(parity.get("extra_templates", []))
    candidates = []
    for extra in extra_templates:
        extra_signature = [str(item) for item in extra.get("lane_signature", [])]
        extra_indexes = _lane_signature_indexes(extra_signature)
        for missing in missing_templates:
            missing_signature = [str(item) for item in missing.get("lane_signature", [])]
            if (
                str(extra.get("type", "")) != str(missing.get("type", ""))
                or len(extra_signature) != len(missing_signature)
                or extra_indexes != _lane_signature_indexes(missing_signature)
            ):
                continue
            candidates.append(
                {
                    "action": "replace_lane_signature",
                    "type": str(extra.get("type", "")),
                    "priority": min(int(extra.get("count", 0)), int(missing.get("count", 0))),
                    "candidate_count": int(extra.get("count", 0)),
                    "teacher_count": int(missing.get("count", 0)),
                    "from_lane_signature": extra_signature,
                    "to_lane_signature": missing_signature,
                }
            )
    return sorted(
        candidates,
        key=lambda item: (-int(item["priority"]), str(item["type"]), _record_key(item)),
    )[:max_items]


def build_road_lane_template_edge_subset_repair_candidates(
    teacher_net_file: Path,
    candidate_net_file: Path,
    parity_report: dict[str, Any],
    *,
    max_items: int = 10,
) -> list[dict[str, Any]]:
    teacher_edges = _road_lane_template_edge_index(teacher_net_file)
    candidate_edges = _road_lane_template_edge_index(candidate_net_file)
    candidates = []
    for candidate in build_road_lane_template_repair_candidates(parity_report, max_items=max_items):
        from_signature = tuple(str(item) for item in candidate.get("from_lane_signature", []))
        to_signature = tuple(str(item) for item in candidate.get("to_lane_signature", []))
        edge_type = str(candidate.get("type", ""))
        edge_ids = [
            edge_id
            for edge_id, candidate_record in candidate_edges.items()
            if candidate_record == (edge_type, from_signature)
            and teacher_edges.get(edge_id) == (edge_type, to_signature)
        ]
        if not edge_ids:
            continue
        subset_candidate = dict(candidate)
        subset_candidate["edge_ids"] = sorted(edge_ids)
        subset_candidate["edge_count"] = len(edge_ids)
        subset_candidate["priority"] = len(edge_ids)
        candidates.append(subset_candidate)
    return sorted(
        candidates,
        key=lambda item: (-int(item["edge_count"]), str(item["type"]), _record_key(item)),
    )[:max_items]


def build_road_lane_template_single_edge_repair_candidates(
    teacher_net_file: Path,
    candidate_net_file: Path,
    parity_report: dict[str, Any],
    *,
    max_items: int = 10,
) -> list[dict[str, Any]]:
    candidates = []
    for candidate in build_road_lane_template_edge_subset_repair_candidates(
        teacher_net_file,
        candidate_net_file,
        parity_report,
        max_items=max_items,
    ):
        for edge_id in candidate.get("edge_ids", []):
            single_edge_candidate = dict(candidate)
            single_edge_candidate["edge_ids"] = [str(edge_id)]
            single_edge_candidate["edge_count"] = 1
            single_edge_candidate["priority"] = 1
            candidates.append(single_edge_candidate)
    return candidates[:max_items]


def write_road_lane_template_repair_candidate(
    candidate_net_file: Path,
    output_file: Path,
    repair_candidates: list[dict[str, Any]],
    *,
    max_candidates: int | None = None,
) -> dict[str, Any]:
    selected_candidates = repair_candidates[:max_candidates] if max_candidates is not None else repair_candidates
    tree = ET.parse(candidate_net_file)
    root = tree.getroot()
    changed_edge_count = 0
    changed_lane_count = 0
    applied_candidate_ids: set[int] = set()
    for edge in root.findall("edge"):
        if edge.attrib.get("function") == "internal":
            continue
        edge_record = _canonical_edge_record(edge)
        edge_signature = _lane_signature(edge_record)
        edge_type = str(edge_record.get("type", ""))
        for candidate_index, candidate in enumerate(selected_candidates):
            edge_ids = {str(edge_id) for edge_id in candidate.get("edge_ids", [])}
            if (
                str(candidate.get("action", "")) != "replace_lane_signature"
                or edge_type != str(candidate.get("type", ""))
                or edge_signature != [str(item) for item in candidate.get("from_lane_signature", [])]
                or (edge_ids and str(edge.attrib.get("id", "")) not in edge_ids)
            ):
                continue
            changed_lanes = _apply_lane_signature(edge, [str(item) for item in candidate.get("to_lane_signature", [])])
            if changed_lanes:
                changed_edge_count += 1
                changed_lane_count += changed_lanes
                applied_candidate_ids.add(candidate_index)
            break

    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "candidate_net_file": str(candidate_net_file),
        "output_file": str(output_file),
        "selected_candidate_count": len(selected_candidates),
        "applied_candidate_count": len(applied_candidate_ids),
        "changed_edge_count": changed_edge_count,
        "changed_lane_count": changed_lane_count,
        "warnings": [],
    }


LANE_TEMPLATE_GATE_METRICS = (
    "lane_missing_template_count",
    "lane_extra_template_count",
    "lane_common_count_delta_sum",
)

ROAD_TEMPLATE_GATE_METRICS = (
    *LANE_TEMPLATE_GATE_METRICS,
    "connection_missing_template_count",
    "connection_extra_template_count",
    "connection_common_count_delta_sum",
)


def evaluate_road_template_repair_promotion(
    before_report: dict[str, Any],
    after_report: dict[str, Any],
    *,
    metric_scope: str = "road",
) -> dict[str, Any]:
    metrics = LANE_TEMPLATE_GATE_METRICS if metric_scope == "lane" else ROAD_TEMPLATE_GATE_METRICS
    before_metrics = _road_template_gate_metrics(before_report, metrics)
    after_metrics = _road_template_gate_metrics(after_report, metrics)
    deltas = {
        key: after_metrics[key] - before_metrics[key]
        for key in metrics
    }
    improved_metrics = {key: value for key, value in deltas.items() if value < 0}
    worsened_metrics = {key: value for key, value in deltas.items() if value > 0}
    before_score = sum(before_metrics.values())
    after_score = sum(after_metrics.values())
    if worsened_metrics:
        promotion_status = "blocked"
        reason = "road_template_gate_metric_worsened"
    elif after_score < before_score:
        promotion_status = "pass"
        reason = "road_template_gate_improved"
    else:
        promotion_status = "blocked"
        reason = "road_template_gate_not_improved"
    return {
        "status": "pass" if promotion_status == "pass" else "fail",
        "claim_status": "diagnostic-demo",
        "metric_scope": metric_scope,
        "promotion_status": promotion_status,
        "reason": reason,
        "before_score": before_score,
        "after_score": after_score,
        "score_delta": after_score - before_score,
        "improved_metrics": improved_metrics,
        "worsened_metrics": worsened_metrics,
    }


def _evaluate_road_lane_local_replay_promotion(
    repair_candidate: dict[str, Any],
    repair_report: dict[str, Any],
) -> dict[str, Any]:
    expected_edges = int(repair_candidate.get("edge_count", len(repair_candidate.get("edge_ids", []))))
    changed_edges = int(repair_report.get("changed_edge_count", 0))
    changed_lanes = int(repair_report.get("changed_lane_count", 0))
    promotion_status = "pass" if expected_edges and changed_edges == expected_edges and changed_lanes else "blocked"
    return {
        "status": "pass" if promotion_status == "pass" else "fail",
        "claim_status": "diagnostic-demo",
        "metric_scope": "local_lane",
        "promotion_status": promotion_status,
        "reason": "road_lane_local_replay_applied"
        if promotion_status == "pass"
        else "road_lane_local_replay_not_applied",
        "before_score": expected_edges,
        "after_score": max(0, expected_edges - changed_edges),
        "score_delta": -changed_edges,
        "improved_metrics": {"changed_edge_count": changed_edges} if changed_edges else {},
        "worsened_metrics": {},
    }


def run_road_lane_template_repair_probe(
    teacher_net_file: Path,
    candidate_net_file: Path,
    output_dir: Path,
    *,
    prefix: str = "road_lane_template_repair",
    max_candidates: int = 10,
    max_examples: int = 3,
    use_teacher_edge_subset: bool = True,
    use_single_edge: bool = False,
    promotion_metric_scope: str = "lane",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    before_report = compare_net_road_template_parity(
        teacher_net_file,
        candidate_net_file,
        max_examples=max_examples,
    )
    if use_single_edge:
        repair_scope = "teacher_single_edge"
        repair_candidates = build_road_lane_template_single_edge_repair_candidates(
            teacher_net_file,
            candidate_net_file,
            before_report,
            max_items=max_candidates,
        )
    elif use_teacher_edge_subset:
        repair_scope = "teacher_edge_subset"
        repair_candidates = build_road_lane_template_edge_subset_repair_candidates(
            teacher_net_file,
            candidate_net_file,
            before_report,
            max_items=max_candidates,
        )
    else:
        repair_scope = "template"
        repair_candidates = build_road_lane_template_repair_candidates(
            before_report,
            max_items=max_candidates,
        )
    candidate_reports = []
    for index, repair_candidate in enumerate(repair_candidates, start=1):
        variant_file = output_dir / f"{prefix}_{index:03d}.net.xml"
        repair_report = write_road_lane_template_repair_candidate(
            candidate_net_file,
            variant_file,
            [repair_candidate],
        )
        after_report = compare_net_road_template_parity(
            teacher_net_file,
            variant_file,
            max_examples=max_examples,
        )
        promotion_gate = (
            _evaluate_road_lane_local_replay_promotion(repair_candidate, repair_report)
            if promotion_metric_scope == "local_lane"
            else evaluate_road_template_repair_promotion(
                before_report,
                after_report,
                metric_scope=promotion_metric_scope,
            )
        )
        candidate_reports.append(
            {
                "candidate_index": index,
                "variant_file": str(variant_file),
                "repair_candidate": repair_candidate,
                "repair_report": repair_report,
                "promotion_gate": promotion_gate,
                "after_gate": after_report["gate"],
            }
        )

    pass_candidates = [
        item
        for item in candidate_reports
        if item["promotion_gate"].get("promotion_status") == "pass"
    ]
    best_candidate = min(
        pass_candidates,
        key=lambda item: (
            int(item["promotion_gate"].get("after_score", 0)),
            int(item["candidate_index"]),
        ),
        default=None,
    )
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "road_lane_template_repair_status": "evaluated" if repair_candidates else "no_candidates",
        "repair_scope": repair_scope,
        "promotion_metric_scope": promotion_metric_scope,
        "teacher_net_file": str(teacher_net_file),
        "candidate_net_file": str(candidate_net_file),
        "output_dir": str(output_dir),
        "candidate_count": len(candidate_reports),
        "pass_candidate_count": len(pass_candidates),
        "blocked_candidate_count": len(candidate_reports) - len(pass_candidates),
        "best_candidate_index": 0 if best_candidate is None else int(best_candidate["candidate_index"]),
        "best_variant_file": "" if best_candidate is None else str(best_candidate["variant_file"]),
        "before_gate": before_report["gate"],
        "candidates": candidate_reports,
        "warnings": [],
    }


def run_road_lane_template_batch_repair_probe(
    teacher_net_file: Path,
    candidate_net_file: Path,
    output_file: Path,
    *,
    max_candidates: int = 30,
    max_examples: int = 3,
) -> dict[str, Any]:
    before_report = compare_net_road_template_parity(
        teacher_net_file,
        candidate_net_file,
        max_examples=max_examples,
    )
    repair_candidates = build_road_lane_template_single_edge_repair_candidates(
        teacher_net_file,
        candidate_net_file,
        before_report,
        max_items=max_candidates,
    )
    repair_report = write_road_lane_template_repair_candidate(
        candidate_net_file,
        output_file,
        repair_candidates,
    )
    after_report = compare_net_road_template_parity(
        teacher_net_file,
        output_file,
        max_examples=max_examples,
    )
    expected_candidate = {
        "edge_count": sum(int(candidate.get("edge_count", 0)) for candidate in repair_candidates)
    }
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "repair_scope": "teacher_single_edge_batch",
        "teacher_net_file": str(teacher_net_file),
        "candidate_net_file": str(candidate_net_file),
        "output_file": str(output_file),
        "selected_candidate_count": len(repair_candidates),
        "repair_candidates": repair_candidates,
        "repair_report": repair_report,
        "promotion_gate": _evaluate_road_lane_local_replay_promotion(expected_candidate, repair_report),
        "before_gate": before_report["gate"],
        "after_gate": after_report["gate"],
        "warnings": [],
    }


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
        "lane_common_count_delta_sum": int(lane_parity.get("common_count_delta_sum", 0)),
        "connection_common_count_delta_sum": int(connection_parity.get("common_count_delta_sum", 0)),
    }


def _road_template_gate_metrics(
    report: dict[str, Any],
    metrics: tuple[str, ...] = ROAD_TEMPLATE_GATE_METRICS,
) -> dict[str, int]:
    gate = report.get("gate", {})
    return {key: int(gate.get(key, 0)) for key in metrics}


def _road_lane_template_edge_index(net_file: Path) -> dict[str, tuple[str, tuple[str, ...]]]:
    root = ET.parse(net_file).getroot()
    index = {}
    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id", "")
        if not edge_id or edge_id.startswith(":") or edge.attrib.get("function") == "internal":
            continue
        edge_record = _canonical_edge_record(edge)
        index[edge_id] = (str(edge_record.get("type", "")), tuple(_lane_signature(edge_record)))
    return index


def _lane_signature_indexes(signature: list[str]) -> tuple[str, ...]:
    return tuple(_lane_signature_attrs(item).get("index", "") for item in signature)


def _lane_signature_attrs(signature: str) -> dict[str, str]:
    attrs = {}
    for part in signature.split("|"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        attrs[key] = value
    return attrs


def _apply_lane_signature(edge: ET.Element, signature: list[str]) -> int:
    changed = 0
    lanes = list(edge.findall("lane"))
    if len(lanes) != len(signature):
        return 0
    for lane, lane_signature in zip(lanes, signature):
        attrs = _lane_signature_attrs(lane_signature)
        before = (lane.attrib.get("allow"), lane.attrib.get("disallow"))
        for attr_name in ("allow", "disallow"):
            value = attrs.get(attr_name, "")
            if value:
                lane.set(attr_name, value)
            else:
                lane.attrib.pop(attr_name, None)
        after = (lane.attrib.get("allow"), lane.attrib.get("disallow"))
        changed += int(before != after)
    return changed


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

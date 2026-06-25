from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping
import xml.etree.ElementTree as ET

from .command_runner import run_command


DETAIL_EDGE_TYPES = {
    "highway.service",
    "highway.path",
    "highway.footway",
    "highway.cycleway",
    "highway.steps",
    "highway.pedestrian",
    "highway.track",
}


def audit_reference_scope(
    *,
    reference_net_file: Path,
    candidate_net_file: Path,
    output_dir: Path,
    prefix: str = "reference_scope",
    overrepresentation_ratio: float = 1.5,
    min_extra_edges: int = 10,
    max_prune_edge_length_m: float = 80.0,
) -> dict[str, Any]:
    if overrepresentation_ratio <= 1.0:
        return _failure("overrepresentation_ratio must be greater than 1.0")
    if min_extra_edges < 0:
        return _failure("min_extra_edges must be non-negative")
    if max_prune_edge_length_m <= 0:
        return _failure("max_prune_edge_length_m must be positive")
    if not reference_net_file.exists():
        return _failure(f"reference net file does not exist: {reference_net_file}")
    if not candidate_net_file.exists():
        return _failure(f"candidate net file does not exist: {candidate_net_file}")

    try:
        reference_edges = _read_edges(reference_net_file)
        candidate_edges = _read_edges(candidate_net_file)
    except (OSError, ET.ParseError, KeyError, ValueError) as exc:
        return _failure(f"{type(exc).__name__}: {exc}")

    output_dir.mkdir(parents=True, exist_ok=True)
    reference_counts = Counter(edge["type"] for edge in reference_edges)
    candidate_counts = Counter(edge["type"] for edge in candidate_edges)
    type_comparisons = _type_comparisons(
        reference_counts=reference_counts,
        candidate_counts=candidate_counts,
        overrepresentation_ratio=overrepresentation_ratio,
        min_extra_edges=min_extra_edges,
    )
    type_decisions = {row["edge_type"]: row["scope_decision"] for row in type_comparisons}
    candidate_degrees = _node_degrees(candidate_edges)
    prune_candidates = _prune_candidates(
        candidate_edges,
        type_decisions=type_decisions,
        node_degrees=candidate_degrees,
        max_prune_edge_length_m=max_prune_edge_length_m,
    )

    type_comparison_file = output_dir / f"{prefix}_type_comparison.csv"
    prune_candidates_file = output_dir / f"{prefix}_prune_candidates.csv"
    report_file = output_dir / f"{prefix}_reference_scope_audit.json"
    _write_type_comparison_csv(type_comparison_file, type_comparisons)
    _write_prune_candidates_csv(prune_candidates_file, prune_candidates)

    status = "blocked" if prune_candidates else "pass"
    report = {
        "status": status,
        "claim_status": "blocked" if prune_candidates else "diagnostic-demo",
        "reference_scope_status": "needs_pruning_review" if prune_candidates else "pass",
        "reference_net_file": str(reference_net_file),
        "candidate_net_file": str(candidate_net_file),
        "output_dir": str(output_dir),
        "overrepresentation_ratio": overrepresentation_ratio,
        "min_extra_edges": min_extra_edges,
        "max_prune_edge_length_m": max_prune_edge_length_m,
        "reference_edge_count": len(reference_edges),
        "candidate_edge_count": len(candidate_edges),
        "edge_count_delta": len(candidate_edges) - len(reference_edges),
        "overrepresented_type_count": sum(
            1 for row in type_comparisons if row["scope_decision"] != "reference_aligned"
        ),
        "prune_candidate_count": len(prune_candidates),
        "type_comparison_file": str(type_comparison_file),
        "prune_candidates_file": str(prune_candidates_file),
        "report_file": str(report_file),
        "type_comparisons": type_comparisons,
        "prune_candidates": prune_candidates,
        "warnings": _scope_warnings(prune_candidates),
    }
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def build_scope_pruning_variant(
    *,
    net_file: Path,
    reference_scope_report: Mapping[str, Any],
    output_dir: Path,
    prefix: str = "scope_pruning",
    timeout_seconds: float = 240.0,
    command_runner: Callable[..., Any] = run_command,
) -> dict[str, Any]:
    if not net_file.exists():
        return _failure(f"net file does not exist: {net_file}")

    output_dir.mkdir(parents=True, exist_ok=True)
    remove_edge_ids = sorted(
        {
            str(candidate.get("edge_id", ""))
            for candidate in reference_scope_report.get("prune_candidates", []) or []
            if str(candidate.get("edge_id", "")) and str(candidate.get("prune_decision", "")) == "prune_candidate"
        }
    )
    plan_file = output_dir / f"{prefix}_plan.json"
    remove_edges_file = output_dir / f"{prefix}_remove_edges.txt"
    command_record = output_dir / f"{prefix}_netconvert.cmd.txt"
    variant_file = output_dir / f"{prefix}_scope_pruned.net.xml"

    plan = {
        "scope_pruning_status": "planned_for_review_variant" if remove_edge_ids else "not_needed",
        "net_file": str(net_file),
        "variant_file": str(variant_file) if remove_edge_ids else "",
        "remove_edge_count": len(remove_edge_ids),
        "review_policy": (
            "create a separate reference-scope pruning variant for Netedit/map review; "
            "do not overwrite the source network"
        ),
        "remove_edge_ids": remove_edge_ids,
    }
    plan_file.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    remove_edges_file.write_text("\n".join(remove_edge_ids) + ("\n" if remove_edge_ids else ""), encoding="utf-8")

    if not remove_edge_ids:
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "scope_pruning_status": "not_needed",
            "scope_pruning_removed_edge_count": 0,
            "scope_pruning_plan_file": str(plan_file),
            "scope_pruning_remove_edges_file": str(remove_edges_file),
            "scope_pruning_variant_file": "",
            "scope_pruning_command_record": "",
            "scope_pruning_netconvert": {},
            "warnings": [],
        }

    command = [
        "netconvert",
        "--sumo-net-file",
        str(net_file),
        "--remove-edges.input-file",
        str(remove_edges_file),
        "--output-file",
        str(variant_file),
    ]
    command_record.write_text(" ".join(command) + "\n", encoding="utf-8")
    try:
        result = _result_to_dict(command_runner(command, cwd=output_dir, timeout_seconds=timeout_seconds))
    except OSError as exc:
        return {
            **_failure(f"{type(exc).__name__}: {exc}"),
            "scope_pruning_plan_file": str(plan_file),
            "scope_pruning_remove_edges_file": str(remove_edges_file),
            "scope_pruning_variant_file": str(variant_file),
            "scope_pruning_command_record": str(command_record),
        }

    status = "pass" if result.get("status") == "pass" and variant_file.exists() else "fail"
    counts = _network_counts(variant_file) if variant_file.exists() else {}
    warnings = ["scope pruning variant requires Netedit/map review before adoption"]
    if status != "pass":
        warnings.append(f"scope pruning variant was not created: {variant_file}")
    return {
        "status": status,
        "claim_status": "blocked" if status == "pass" else "construction-invalid",
        "scope_pruning_status": "variant_created_for_review" if status == "pass" else "failed",
        "scope_pruning_removed_edge_count": len(remove_edge_ids),
        "scope_pruning_plan_file": str(plan_file),
        "scope_pruning_remove_edges_file": str(remove_edges_file),
        "scope_pruning_variant_file": str(variant_file),
        "scope_pruning_command_record": str(command_record),
        "scope_pruning_netconvert": result,
        **counts,
        "warnings": warnings,
    }


def _read_edges(net_file: Path) -> list[dict[str, Any]]:
    root = ET.parse(net_file).getroot()
    edges = []
    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id", "")
        if not edge_id or edge_id.startswith(":") or edge.attrib.get("function") == "internal":
            continue
        lanes = edge.findall("lane")
        length = _edge_length(lanes)
        edges.append(
            {
                "id": edge_id,
                "from": edge.attrib.get("from", ""),
                "to": edge.attrib.get("to", ""),
                "type": edge.attrib.get("type", "<missing>") or "<missing>",
                "name": edge.attrib.get("name", ""),
                "lane_count": len(lanes),
                "length": length,
                "allow": _edge_allow(lanes),
            }
        )
    return edges


def _edge_length(lanes: list[ET.Element]) -> float:
    lengths = []
    for lane in lanes:
        try:
            lengths.append(float(lane.attrib.get("length", "0") or 0))
        except ValueError:
            pass
    return max(lengths, default=0.0)


def _edge_allow(lanes: list[ET.Element]) -> str:
    allow_values = sorted({lane.attrib.get("allow", "all") or "all" for lane in lanes})
    return ";".join(allow_values) if allow_values else "all"


def _node_degrees(edges: list[dict[str, Any]]) -> dict[str, int]:
    degrees: dict[str, int] = {}
    for edge in edges:
        for node_id in (str(edge.get("from", "")), str(edge.get("to", ""))):
            if node_id:
                degrees[node_id] = degrees.get(node_id, 0) + 1
    return degrees


def _type_comparisons(
    *,
    reference_counts: Counter[str],
    candidate_counts: Counter[str],
    overrepresentation_ratio: float,
    min_extra_edges: int,
) -> list[dict[str, Any]]:
    rows = []
    for edge_type in sorted(set(reference_counts) | set(candidate_counts)):
        reference_count = int(reference_counts.get(edge_type, 0))
        candidate_count = int(candidate_counts.get(edge_type, 0))
        extra_edges = candidate_count - reference_count
        ratio = None if reference_count == 0 else candidate_count / reference_count
        if reference_count == 0 and candidate_count >= min_extra_edges:
            decision = "absent_in_reference"
        elif extra_edges >= min_extra_edges and ratio is not None and ratio >= overrepresentation_ratio:
            decision = "overrepresented_in_candidate"
        else:
            decision = "reference_aligned"
        rows.append(
            {
                "edge_type": edge_type,
                "reference_count": reference_count,
                "candidate_count": candidate_count,
                "extra_edge_count": extra_edges,
                "candidate_to_reference_ratio": "" if ratio is None else round(ratio, 3),
                "scope_decision": decision,
            }
        )
    return rows


def _prune_candidates(
    candidate_edges: list[dict[str, Any]],
    *,
    type_decisions: Mapping[str, str],
    node_degrees: Mapping[str, int],
    max_prune_edge_length_m: float,
) -> list[dict[str, Any]]:
    rows = []
    for edge in candidate_edges:
        edge_type = str(edge["type"])
        scope_decision = type_decisions.get(edge_type, "reference_aligned")
        if scope_decision == "reference_aligned":
            continue
        if edge_type not in DETAIL_EDGE_TYPES and scope_decision != "absent_in_reference":
            continue
        from_degree = int(node_degrees.get(str(edge.get("from", "")), 0))
        to_degree = int(node_degrees.get(str(edge.get("to", "")), 0))
        is_dead_end = min(from_degree, to_degree) <= 1
        is_short = float(edge.get("length", 0.0)) <= max_prune_edge_length_m
        if not (is_dead_end and is_short):
            continue
        rows.append(
            {
                "edge_id": str(edge["id"]),
                "edge_type": edge_type,
                "edge_name": str(edge.get("name", "")),
                "from": str(edge.get("from", "")),
                "to": str(edge.get("to", "")),
                "length_m": round(float(edge.get("length", 0.0)), 3),
                "lane_count": int(edge.get("lane_count", 0)),
                "allow": str(edge.get("allow", "")),
                "from_degree": from_degree,
                "to_degree": to_degree,
                "scope_decision": scope_decision,
                "prune_decision": "prune_candidate",
                "prune_confidence": "medium",
                "reason": (
                    f"{edge_type} is {scope_decision} and this edge is a short dead-end detail fragment"
                ),
            }
        )
    rows.sort(key=lambda row: (row["edge_type"], row["edge_id"]))
    return rows


def _write_type_comparison_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "edge_type",
                "reference_count",
                "candidate_count",
                "extra_edge_count",
                "candidate_to_reference_ratio",
                "scope_decision",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_prune_candidates_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "edge_id",
                "edge_type",
                "edge_name",
                "from",
                "to",
                "length_m",
                "lane_count",
                "allow",
                "from_degree",
                "to_degree",
                "scope_decision",
                "prune_decision",
                "prune_confidence",
                "reason",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _network_counts(net_file: Path) -> dict[str, int]:
    root = ET.parse(net_file).getroot()
    edges = [
        edge
        for edge in root.findall("edge")
        if not edge.attrib.get("id", "").startswith(":") and edge.attrib.get("function") != "internal"
    ]
    junctions = [
        junction
        for junction in root.findall("junction")
        if not junction.attrib.get("id", "").startswith(":") and junction.attrib.get("type") != "internal"
    ]
    return {
        "scope_pruned_edge_count": len(edges),
        "scope_pruned_lane_count": sum(len(edge.findall("lane")) for edge in edges),
        "scope_pruned_junction_count": len(junctions),
        "scope_pruned_traffic_light_junction_count": sum(
            1 for junction in junctions if junction.attrib.get("type") == "traffic_light"
        ),
        "scope_pruned_tl_logic_count": len(root.findall("tlLogic")),
    }


def _result_to_dict(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        return dict(result.to_dict())
    if hasattr(result, "model_dump"):
        return dict(result.model_dump(mode="json"))
    return dict(result)


def _scope_warnings(prune_candidates: list[dict[str, Any]]) -> list[str]:
    if not prune_candidates:
        return []
    return [
        (
            f"reference scope audit found {len(prune_candidates)} prune candidate edge(s); "
            "create a separate scope-pruned variant and review it before adoption"
        )
    ]


def _failure(error: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "claim_status": "construction-invalid",
        "reference_scope_status": "failed",
        "scope_pruning_status": "failed",
        "error": error,
        "warnings": [error],
    }

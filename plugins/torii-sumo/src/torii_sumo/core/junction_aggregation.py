from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .command_runner import run_command


def build_junction_aggregation_variant(
    *,
    net_file: Path,
    output_dir: Path,
    prefix: str = "junction_aggregation",
    topology_audit_report: Mapping[str, Any] | None = None,
    reference_join_audit_report: Mapping[str, Any] | None = None,
    join_dist_m: float = 30.0,
    timeout_seconds: float = 240.0,
    command_runner: Callable[..., Any] = run_command,
) -> dict[str, Any]:
    if join_dist_m <= 0:
        return _failure("join_dist_m must be positive")
    if not net_file.exists():
        return _failure(f"net file does not exist: {net_file}")

    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = _aggregation_candidates(
        topology_audit_report=topology_audit_report,
        reference_join_audit_report=reference_join_audit_report,
    )
    plan_file = output_dir / f"{prefix}_plan.json"
    candidates_file = output_dir / f"{prefix}_candidates.csv"
    command_record = output_dir / f"{prefix}_netconvert.cmd.txt"
    variant_file = output_dir / f"{prefix}_junction_aggregated.net.xml"
    joined_junctions_file = output_dir / f"{prefix}_joined_junctions.xml"

    plan = {
        "junction_aggregation_status": "not_needed" if not candidates else "planned_for_review_variant",
        "net_file": str(net_file),
        "variant_file": str(variant_file) if candidates else "",
        "joined_junctions_file": str(joined_junctions_file) if candidates else "",
        "join_dist_m": join_dist_m,
        "candidate_count": len(candidates),
        "candidate_sources": sorted({candidate["source"] for candidate in candidates}),
        "review_policy": (
            "create a separate netconvert --junctions.join variant for Netedit and Google Maps review; "
            "do not overwrite the source network"
        ),
        "candidates": candidates,
    }
    plan_file.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_candidates_csv(candidates_file, candidates)

    if not candidates:
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_aggregation_status": "not_needed",
            "junction_aggregation_candidate_count": 0,
            "junction_aggregation_plan_file": str(plan_file),
            "junction_aggregation_candidates_file": str(candidates_file),
            "junction_aggregation_variant_file": "",
            "junction_aggregation_joined_junctions_file": "",
            "junction_aggregation_command_record": "",
            "junction_aggregation_netconvert": {},
            "warnings": [],
        }

    command = [
        "netconvert",
        "--sumo-net-file",
        str(net_file),
        "--junctions.join",
        "--junctions.join-dist",
        f"{join_dist_m:g}",
        "--junctions.join-output",
        str(joined_junctions_file),
        "--output-file",
        str(variant_file),
    ]
    command_record.write_text(" ".join(command) + "\n", encoding="utf-8")
    try:
        result = _result_to_dict(command_runner(command, cwd=output_dir, timeout_seconds=timeout_seconds))
    except OSError as exc:
        return {
            **_failure(f"{type(exc).__name__}: {exc}"),
            "junction_aggregation_status": "failed",
            "junction_aggregation_plan_file": str(plan_file),
            "junction_aggregation_candidates_file": str(candidates_file),
            "junction_aggregation_variant_file": str(variant_file),
            "junction_aggregation_joined_junctions_file": str(joined_junctions_file),
            "junction_aggregation_command_record": str(command_record),
        }

    status = "pass" if result.get("status") == "pass" and variant_file.exists() else "fail"
    warnings = [
        "junction aggregation variant requires Google Maps and Netedit review before adoption",
    ]
    if status != "pass":
        warnings.append(f"junction aggregation variant was not created: {variant_file}")
    return {
        "status": status,
        "claim_status": "blocked" if status == "pass" else "construction-invalid",
        "junction_aggregation_status": "variant_created_for_review" if status == "pass" else "failed",
        "junction_aggregation_candidate_count": len(candidates),
        "junction_aggregation_plan_file": str(plan_file),
        "junction_aggregation_candidates_file": str(candidates_file),
        "junction_aggregation_variant_file": str(variant_file),
        "junction_aggregation_joined_junctions_file": str(joined_junctions_file),
        "junction_aggregation_command_record": str(command_record),
        "junction_aggregation_netconvert": result,
        "warnings": warnings,
    }


def _aggregation_candidates(
    *,
    topology_audit_report: Mapping[str, Any] | None,
    reference_join_audit_report: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if reference_join_audit_report is not None:
        for case in reference_join_audit_report.get("matched_cases", []) or []:
            candidates.append(
                {
                    "source": "reference_join_audit",
                    "candidate_id": str(case.get("reference_id", "")),
                    "decision": "join_pattern_matched",
                    "confidence": "reference_matched",
                    "node_ids": ";".join(str(item) for item in case.get("candidate_node_ids", []) or []),
                    "reason": str(case.get("match_reason", case.get("learned_rule", ""))),
                    "google_maps_url": str(case.get("google_maps_url", "")),
                }
            )
    if topology_audit_report is not None:
        for cluster in topology_audit_report.get("suspicious_clusters", []) or []:
            decision = str(cluster.get("aggregation_decision", "needs_map_review"))
            if decision not in {"join", "needs_map_review"}:
                continue
            candidates.append(
                {
                    "source": "topology_audit",
                    "candidate_id": str(cluster.get("cluster_id", "")),
                    "decision": decision,
                    "confidence": str(cluster.get("aggregation_confidence", "")),
                    "node_ids": ";".join(str(item) for item in cluster.get("node_ids", []) or []),
                    "reason": str(cluster.get("aggregation_reason", "")),
                    "google_maps_url": str(cluster.get("google_maps_url", "")),
                }
            )
    return candidates


def _write_candidates_csv(path: Path, candidates: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "source",
                "candidate_id",
                "decision",
                "confidence",
                "node_ids",
                "reason",
                "google_maps_url",
            ],
        )
        writer.writeheader()
        writer.writerows(candidates)


def _result_to_dict(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        return dict(result.to_dict())
    if hasattr(result, "model_dump"):
        return dict(result.model_dump(mode="json"))
    return dict(result)


def _failure(error: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "claim_status": "construction-invalid",
        "junction_aggregation_status": "failed",
        "error": error,
        "warnings": [error],
    }

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

from .artifact_io import write_json_atomic
from .candidate_contracts import file_sha256


def audit_scope_edge_preservation(
    *,
    full_way_net_file: Path,
    final_candidate_net_file: Path,
    graph_bbox_scope_net_file: Path | None = None,
    junction_preservation_audits: Sequence[Mapping[str, Any]] = (),
    explicit_exclusions: Mapping[str, str] | None = None,
    output_file: Path | None = None,
) -> dict[str, Any]:
    """Account for every external edge from the complete-way scope baseline.

    The graph-bbox network is diagnostic only: complete OSM ways may extend
    beyond it, and those outer segments still belong to the canonical scope.
    """
    paths = [full_way_net_file, final_candidate_net_file]
    if graph_bbox_scope_net_file is not None:
        paths.append(graph_bbox_scope_net_file)
    missing_files = [str(path) for path in paths if not path.is_file()]
    if missing_files:
        return _failure(f"network file(s) do not exist: {', '.join(missing_files)}")

    try:
        full_edges = _external_edge_ids(full_way_net_file)
        final_edges = _external_edge_ids(final_candidate_net_file)
        graph_bbox_edges = (
            _external_edge_ids(graph_bbox_scope_net_file)
            if graph_bbox_scope_net_file is not None
            else None
        )
    except (OSError, ET.ParseError) as exc:
        return _failure(f"{type(exc).__name__}: {exc}")
    if not full_edges:
        return _failure("full-way baseline contains no external edges")

    full_way_net_file = full_way_net_file.resolve()
    final_candidate_net_file = final_candidate_net_file.resolve()
    graph_bbox_scope_net_file = (
        graph_bbox_scope_net_file.resolve()
        if graph_bbox_scope_net_file is not None
        else None
    )
    full_sha = file_sha256(full_way_net_file)
    final_sha = file_sha256(final_candidate_net_file)
    absorbed_by_audit, audit_errors = _validated_absorptions(
        junction_preservation_audits,
        source_sha256=full_sha,
        final_sha256=final_sha,
    )
    exclusions = {str(edge_id): str(reason) for edge_id, reason in (explicit_exclusions or {}).items()}

    rows = []
    empty_reason_edge_ids = []
    for edge_id in sorted(full_edges):
        in_final = edge_id in final_edges
        reason = exclusions.get(edge_id, "").strip()
        if in_final:
            classification = "preserved"
            detail = "same_external_edge_id_in_final_candidate"
        elif edge_id in absorbed_by_audit:
            classification = "internalized"
            detail = "junction_aggregation_absorbed_join_edge"
        elif reason:
            classification = "excluded_with_reason"
            detail = reason
        else:
            classification = "unaccounted"
            detail = "missing_from_final_candidate_without_authorized_explanation"
            if edge_id in exclusions:
                empty_reason_edge_ids.append(edge_id)
        rows.append(
            {
                "edge_id": edge_id,
                "classification": classification,
                "reason": detail,
                "in_graph_bbox_scope": (
                    edge_id in graph_bbox_edges if graph_bbox_edges is not None else None
                ),
                "junction_preservation_audit_index": absorbed_by_audit.get(edge_id),
            }
        )

    counts = {
        classification: sum(row["classification"] == classification for row in rows)
        for classification in (
            "preserved",
            "internalized",
            "excluded_with_reason",
            "unaccounted",
        )
    }
    status = (
        "pass"
        if (
            counts["unaccounted"] == 0
            and not empty_reason_edge_ids
            and not audit_errors
        )
        else "blocked"
    )
    report = {
        "schema": "torii.scope-edge-preservation/v1",
        "status": status,
        "full_way_baseline": _identity(full_way_net_file, full_edges),
        "graph_bbox_scope": (
            _identity(graph_bbox_scope_net_file, graph_bbox_edges or set())
            if graph_bbox_scope_net_file is not None
            else None
        ),
        "final_candidate": _identity(final_candidate_net_file, final_edges),
        "inventory_policy": "all_external_edges_from_complete_osm_ways_intersecting_the_reviewed_scope",
        "graph_bbox_scope_role": "diagnostic_only",
        "classification_counts": counts,
        "unaccounted_edge_count": counts["unaccounted"],
        "unaccounted_edge_ids": [
            row["edge_id"] for row in rows if row["classification"] == "unaccounted"
        ],
        "empty_exclusion_reason_count": len(empty_reason_edge_ids),
        "empty_exclusion_reason_edge_ids": empty_reason_edge_ids,
        "outside_graph_bbox_scope_edge_count": (
            len(full_edges - graph_bbox_edges) if graph_bbox_edges is not None else None
        ),
        "outside_graph_bbox_scope_edge_ids": (
            sorted(full_edges - graph_bbox_edges) if graph_bbox_edges is not None else []
        ),
        "new_final_candidate_edge_ids": sorted(final_edges - full_edges),
        "junction_preservation_audit_errors": audit_errors,
        "edges": rows,
    }
    if output_file is not None:
        write_json_atomic(output_file, report, ensure_ascii=False)
        report["report_file"] = str(output_file.resolve())
    return report


def _validated_absorptions(
    audits: Sequence[Mapping[str, Any]],
    *,
    source_sha256: str,
    final_sha256: str,
) -> tuple[dict[str, int], list[str]]:
    if not audits:
        return {}, []
    current_sha = source_sha256
    absorbed: dict[str, int] = {}
    errors = []
    for index, audit in enumerate(audits):
        if (
            audit.get("schema") != "torii.junction-aggregation-preservation/v1"
            or audit.get("status") != "pass"
            or audit.get("source_sha256") != current_sha
            or not audit.get("variant_sha256")
        ):
            errors.append(f"junction preservation audit {index} is not a valid bound pass result")
            continue
        current_sha = str(audit["variant_sha256"])
        for edge_id in audit.get("absorbed_join_edge_ids", []) or []:
            absorbed[str(edge_id)] = index
    if errors or current_sha != final_sha256:
        if current_sha != final_sha256:
            errors.append("junction preservation audit chain does not end at the final candidate")
        return {}, errors
    return absorbed, []


def _external_edge_ids(path: Path) -> set[str]:
    return {
        edge_id
        for edge in ET.parse(path).getroot().findall("edge")
        if (edge_id := edge.attrib.get("id", ""))
        and not edge_id.startswith(":")
        and edge.attrib.get("function") != "internal"
    }


def _identity(path: Path, edge_ids: set[str]) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": file_sha256(path),
        "external_edge_count": len(edge_ids),
    }


def _failure(error: str) -> dict[str, Any]:
    return {
        "schema": "torii.scope-edge-preservation/v1",
        "status": "blocked",
        "error": error,
        "warnings": [error],
    }

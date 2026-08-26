"""Stable contract wrappers for the reduced default MCP surface.

These wrappers deliberately expose fewer knobs than the legacy tools.  They
keep external URLs, executable paths, and most output locations under Torii's
control and return one structured result shape.  They call the same business
functions as the legacy MCP tools and the ``torii`` CLI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .demand_tools import sumo_detector_count_audit
from .environment_tools import sumo_preflight
from .evidence_tools import sumo_compare_outputs, sumo_config_pair_preflight
from .intersection_tools import sumo_intersection_archetype_classify
from .netedit_tools import (
    NeteditAction,
    NeteditObjectType,
    sumo_netedit_session,
)
from .osm_tools import (
    sumo_network_connection_mode_regression_audit,
    sumo_network_review_html,
    sumo_network_routeability_audit,
    sumo_network_topology_audit,
    sumo_osm_resolve_place,
)
from .signal_tools import sumo_signal_device_profile_classify

NetworkAuditProfile = Literal["quick", "standard", "promotion"]
NetworkCompareProfile = Literal["standard", "promotion"]


class ToriiArtifact(BaseModel):
    role: str | None = None
    path: str | None = None
    sha256: str | None = None
    media_type: str | None = None


class ToriiToolResult(BaseModel):
    """Common result envelope returned by every default MCP tool."""

    status: str
    summary: str
    claim_status: str | None = None
    findings: list[Any] = Field(default_factory=list)
    artifacts: list[ToriiArtifact] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


def _result(
    raw: dict[str, Any],
    *,
    summary: str,
    status: str | None = None,
    claim_status: str | None = None,
    next_actions: list[str] | None = None,
) -> ToriiToolResult:
    selected_status = status or str(raw.get("status") or "unknown")
    selected_claim = claim_status or raw.get("claim_status")
    return ToriiToolResult(
        status=selected_status,
        summary=summary,
        claim_status=selected_claim,
        findings=raw.get("findings") if isinstance(raw.get("findings"), list) else [],
        artifacts=[
            ToriiArtifact(
                role=item.get("role"),
                path=item.get("path"),
                sha256=item.get("sha256"),
                media_type=item.get("media_type"),
            )
            for item in raw.get("artifacts", [])
            if isinstance(item, dict)
        ],
        next_actions=next_actions or [],
        payload=raw,
    )


def _as_path_list(items: list[str]) -> list[str]:
    return [str(Path(item).expanduser().resolve()) for item in items]


def torii_preflight() -> ToriiToolResult:
    raw = sumo_preflight()
    summary = "SUMO environment preflight completed."
    if raw.get("sumo_home"):
        summary += f" SUMO_HOME={raw['sumo_home']}"
    return _result(
        raw,
        summary=summary,
        next_actions=(
            []
            if raw.get("status") == "pass"
            else ["Install or repair the missing SUMO/Python components shown in payload."]
        ),
    )


def torii_config_inspect(
    baseline_config: str,
    variant_config: str,
) -> ToriiToolResult:
    raw = sumo_config_pair_preflight(
        baseline_config=baseline_config,
        variant_config=variant_config,
    )
    return _result(
        raw,
        summary="Configuration pair preflight completed.",
        next_actions=(
            ["Fix the missing inputs or shared outputs reported in payload before running a comparison."]
            if raw.get("status") not in {"pass", "ok"}
            else ["Run torii run compare against the inspected configuration pair."]
        ),
    )


def torii_run_compare(
    baseline_summary: str | None = None,
    baseline_tripinfo: str | None = None,
    variant_summary: str | None = None,
    variant_tripinfo: str | None = None,
) -> ToriiToolResult:
    raw = sumo_compare_outputs(
        baseline_summary=baseline_summary,
        baseline_tripinfo=baseline_tripinfo,
        variant_summary=variant_summary,
        variant_tripinfo=variant_tripinfo,
    )
    return _result(
        raw,
        summary="Baseline and variant outputs were compared.",
        next_actions=["Review comparison gates before promoting any candidate."],
    )


def torii_place_resolve(place_name: str, limit: int = 1) -> ToriiToolResult:
    raw = sumo_osm_resolve_place(
        place_name=place_name,
        limit=limit,
        nominatim_url="https://nominatim.openstreetmap.org/search",
        timeout_seconds=30.0,
    )
    return _result(
        raw,
        summary=f"Resolved OSM place {place_name!r}.",
        next_actions=["Confirm the resolved area before starting network construction."],
    )


def torii_intersection_classify(
    osm_file: str,
    seed_osm_node_id: str,
    traffic_side: str = "right",
    road_network_evidence_file: str | None = None,
) -> ToriiToolResult:
    raw = sumo_intersection_archetype_classify(
        osm_file=osm_file,
        seed_osm_node_id=seed_osm_node_id,
        traffic_side=traffic_side,
        road_network_evidence_file=road_network_evidence_file,
    )
    return _result(
        raw,
        summary=f"Classified OSM intersection at node {seed_osm_node_id!r}.",
        next_actions=["Use the returned archetype evidence to choose a bounded intersection workflow."],
    )


def torii_signal_classify(
    ocit_file: str,
    expected_node_id: str | None = None,
) -> ToriiToolResult:
    raw = sumo_signal_device_profile_classify(
        ocit_file=ocit_file,
        expected_node_id=expected_node_id,
    )
    return _result(
        raw,
        summary="Classified the OCIT-C signal device inventory.",
        next_actions=["Keep automatic lane, movement, controller, and phase binding blocked until reviewed."],
    )


def torii_network_audit(
    net_file: str,
    output_dir: str,
    profile: NetworkAuditProfile = "standard",
    prefix: str = "network_audit",
) -> ToriiToolResult:
    if profile == "quick":
        raw = sumo_network_topology_audit(
            net_file=net_file,
            output_dir=output_dir,
            prefix=f"{prefix}_topology",
        )
        summary = "Quick network topology audit completed."
    elif profile == "standard":
        raw = sumo_network_routeability_audit(
            net_file=net_file,
            output_dir=output_dir,
            prefix=f"{prefix}_routeability",
        )
        summary = "Standard network routeability audit completed."
    else:
        topology = sumo_network_topology_audit(
            net_file=net_file,
            output_dir=output_dir,
            prefix=f"{prefix}_topology",
        )
        routeability = sumo_network_routeability_audit(
            net_file=net_file,
            output_dir=output_dir,
            prefix=f"{prefix}_routeability",
        )
        raw = {
            "status": (
                "pass"
                if topology.get("status") == "pass" and routeability.get("status") == "pass"
                else "review_required"
            ),
            "claim_status": (
                topology.get("claim_status")
                if topology.get("status") != "pass"
                else routeability.get("claim_status")
            ),
            "findings": [
                *(
                    topology.get("findings")
                    if isinstance(topology.get("findings"), list)
                    else []
                ),
                *(
                    routeability.get("findings")
                    if isinstance(routeability.get("findings"), list)
                    else []
                ),
            ],
            "artifacts": [
                *(
                    topology.get("artifacts")
                    if isinstance(topology.get("artifacts"), list)
                    else []
                ),
                *(
                    routeability.get("artifacts")
                    if isinstance(routeability.get("artifacts"), list)
                    else []
                ),
            ],
            "topology": topology,
            "routeability": routeability,
        }
        summary = "Promotion network audit completed."
    return _result(
        raw,
        summary=summary,
        next_actions=["Review any findings before materializing or promoting a candidate."],
    )


def torii_network_compare(
    source_net_file: str,
    candidate_net_file: str,
    output_dir: str,
    profile: NetworkCompareProfile = "standard",
    prefix: str = "network_compare",
) -> ToriiToolResult:
    if profile != "standard":
        raise ValueError("network compare profile must be 'standard' in this release; promotion merge is not yet exposed")
    raw = sumo_network_connection_mode_regression_audit(
        source_net_file=source_net_file,
        candidate_net_file=candidate_net_file,
        output_dir=output_dir,
        prefix=prefix,
    )
    return _result(
        raw,
        summary="Source and candidate networks were compared.",
        next_actions=["Review introduced findings before any promotion decision."],
    )


def torii_demand_audit(
    expected_counts_csv: str,
    detector_output_xml: str,
    output_dir: str,
    prefix: str = "demand_audit",
) -> ToriiToolResult:
    raw = sumo_detector_count_audit(
        expected_counts_csv=expected_counts_csv,
        detector_output_xml=detector_output_xml,
        output_dir=output_dir,
        prefix=prefix,
    )
    return _result(
        raw,
        summary="Detector count audit completed.",
        next_actions=["Review detector-fit metrics before using demand for promotion evidence."],
    )


def torii_review_create(
    output_dir: str,
    net_file: str | None = None,
    title: str = "SUMO Network Review",
    claim_status: str = "diagnostic-demo",
    raw_net_file: str | None = None,
    connected_core_file: str | None = None,
    tls_review_file: str | None = None,
    topology_audit_report_file: str | None = None,
    junction_aggregation_report_file: str | None = None,
    routeability_audit_report_file: str | None = None,
) -> ToriiToolResult:
    raw = sumo_network_review_html(
        output_dir=output_dir,
        net_file=net_file,
        title=title,
        claim_status=claim_status,
        raw_net_file=raw_net_file,
        connected_core_file=connected_core_file,
        tls_review_file=tls_review_file,
        topology_audit_report_file=topology_audit_report_file,
        junction_aggregation_report_file=junction_aggregation_report_file,
        routeability_audit_report_file=routeability_audit_report_file,
    )
    return _result(
        raw,
        summary="Network review page created without overwriting source files.",
        next_actions=["Open the review page before deciding whether to materialize a candidate."],
    )


def torii_netedit_open(
    source_net_file: str,
    candidate_net_file: str,
    output_dir: str,
    expected_source_sha256: str,
    gui_settings_file: str | None = None,
    selection_file: str | None = None,
    target_source_junction_ids: list[str] | None = None,
    target_candidate_junction_ids: list[str] | None = None,
    window_size: str = "1400,1000",
    window_pos: str = "20,20",
) -> ToriiToolResult:
    raw = sumo_netedit_session(
        operation="open",
        source_net_file=source_net_file,
        candidate_net_file=candidate_net_file,
        output_dir=output_dir,
        expected_source_sha256=expected_source_sha256,
        gui_settings_file=gui_settings_file,
        selection_file=selection_file,
        target_source_junction_ids=target_source_junction_ids,
        target_candidate_junction_ids=target_candidate_junction_ids,
        window_size=window_size,
        window_pos=window_pos,
    )
    return _result(
        raw,
        summary="Opened the hash-bound NetEdit review session.",
        next_actions=["Observe the session, then use exactly one act per review step."],
    )


def torii_netedit_observe(
    session_id: str,
    object_type: NeteditObjectType | None = None,
    object_id: str | None = None,
    label: str = "observe",
) -> ToriiToolResult:
    raw = sumo_netedit_session(
        operation="observe",
        session_id=session_id,
        object_type=object_type,
        object_id=object_id,
        label=label,
    )
    return _result(
        raw,
        summary="Observed the active NetEdit session state.",
        next_actions=["Use the returned screenshot SHA as the guard for the next act."],
    )


def torii_netedit_act(
    session_id: str,
    action: NeteditAction,
    expected_screenshot_sha256: str,
    x: int | None = None,
    y: int | None = None,
    to_x: int | None = None,
    to_y: int | None = None,
) -> ToriiToolResult:
    raw = sumo_netedit_session(
        operation="act",
        session_id=session_id,
        action=action,
        expected_screenshot_sha256=expected_screenshot_sha256,
        x=x,
        y=y,
        to_x=to_x,
        to_y=to_y,
    )
    return _result(
        raw,
        summary="Executed one whitelisted NetEdit action.",
        next_actions=["Observe again after the action before another act or close."],
    )


def torii_netedit_close(
    session_id: str,
    reason: str = "caller_completed",
) -> ToriiToolResult:
    raw = sumo_netedit_session(
        operation="finalize",
        session_id=session_id,
        reason=reason,
    )
    return _result(
        raw,
        summary="Finalized and closed the NetEdit review session.",
        next_actions=["Review the finalize audits; promotion remains blocked."],
    )


__all__ = [
    "ToriiArtifact",
    "ToriiToolResult",
    "torii_config_inspect",
    "torii_demand_audit",
    "torii_intersection_classify",
    "torii_netedit_act",
    "torii_netedit_close",
    "torii_netedit_observe",
    "torii_netedit_open",
    "torii_network_audit",
    "torii_network_compare",
    "torii_place_resolve",
    "torii_preflight",
    "torii_review_create",
    "torii_run_compare",
    "torii_signal_classify",
]

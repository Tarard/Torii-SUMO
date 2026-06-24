from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any, Callable

from .osm_area import resolve_osm_place
from .osm_network import audit_tls_multisource
from .osm_workflow import run_osm_cleanup_workflow
from .road_scope import (
    ROAD_LEVEL_SCOPE_OPTIONS,
    ROAD_LEVEL_SCOPE_QUESTION,
    RECOMMENDED_ROAD_LEVEL_SCOPE,
    resolve_highway_classes,
)


AUTONOMY_MODES = {"ask-first", "safe-autopilot", "inspect-only", "full-local-run"}


WORKFLOW_RECIPES: dict[str, dict[str, Any]] = {
    "osm_to_sumo": {
        "description": "Resolve or infer a place/bbox, build an OSM-derived SUMO network with conservative defaults, audit TLS, check connectivity, and collect launch evidence.",
        "tool_chain": [
            "sumo_osm_resolve_place",
            "sumo_osm_cleanup_workflow",
            "sumo_tls_multisource_review",
            "sumo_network_topology_audit",
            "sumo_network_routeability_probe",
            "sumo_network_routeability_audit",
            "sumo_collect_evidence",
        ],
    },
    "tls_review": {
        "description": "Create a region-aware TLS review table with supporting OSM, street-level imagery, inventory, signal-plan, and field-evidence columns.",
        "tool_chain": ["sumo_tls_audit", "sumo_tls_multisource_review", "sumo_collect_evidence"],
    },
    "routeability": {
        "description": "Snap named route endpoints to passenger-accessible SUMO edges, generate routes, run a bounded smoke check, and report completion before claims.",
        "tool_chain": ["sumo_network_routeability_probe", "sumo_network_routeability_audit", "sumo_compare_outputs"],
    },
    "debug_bad_run": {
        "description": "Treat bad metrics as model feedback, inspect outputs, classify the likely issue, and propose the smallest next probe.",
        "tool_chain": ["sumo_compare_outputs", "sumo_config_pair_preflight", "sumo_collect_evidence"],
    },
    "experiment_audit": {
        "description": "Audit paired controller comparisons before reporting results.",
        "tool_chain": ["sumo_config_pair_preflight", "sumo_compare_outputs", "sumo_collect_evidence"],
    },
    "general": {
        "description": "Build a project-control screen and ask for the minimum missing SUMO artifact before execution.",
        "tool_chain": ["sumo_preflight", "sumo_collect_evidence"],
    },
}


def _normalized(value: str) -> str:
    return " ".join(value.lower().split())


def detect_workflow(user_request: str) -> str:
    text = _normalized(user_request)
    if any(token in text for token in ("waiting time", "got worse", "teleport", "tripinfo", "summary disagree", "debug")):
        return "debug_bad_run"
    if any(token in text for token in ("compare", "baseline", "fixed-time", "fixed time", "max-pressure", "controller")):
        return "experiment_audit"
    if any(token in text for token in ("traffic light", "traffic lights", "tls", "signal")):
        return "tls_review"
    if any(token in text for token in ("osm", "map", "network", "netconvert", "open it in sumo", "build a sumo")):
        return "osm_to_sumo"
    if any(token in text for token in ("route", "from ", " to ", "connected", "routeability", "reachable")):
        return "routeability"
    return "general"


def infer_place_name(user_request: str) -> str:
    text = " ".join(user_request.strip().split())
    patterns = [
        r"download\s+the\s+(?P<area>.+?)\s+map\s+in\s+(?P<city>.+?)\s+from\s+OSM",
        r"build\s+(?:a\s+)?SUMO\s+network\s+for\s+(?P<area>.+?)\s+from\s+OSM",
        r"download\s+(?P<area>.+?)\s+from\s+OSM",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        area = match.groupdict().get("area", "").strip(" .,")
        city = match.groupdict().get("city", "").strip(" .,")
        if area and city:
            return f"{area}, {city}"
        if area:
            return area
    return ""


def _base_report(
    *,
    user_request: str,
    detected_workflow: str,
    autonomy_mode: str,
) -> dict[str, Any]:
    recipe = WORKFLOW_RECIPES[detected_workflow]
    return {
        "detected_workflow": detected_workflow,
        "workflow_description": recipe["description"],
        "autonomy_mode": autonomy_mode,
        "user_request": user_request,
        "tool_chain": list(recipe["tool_chain"]),
    }


def _invalid_mode(user_request: str, autonomy_mode: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "claim_status": "construction-invalid",
        "detected_workflow": detect_workflow(user_request),
        "execution_status": "invalid_autonomy_mode",
        "error": f"autonomy_mode must be one of: {', '.join(sorted(AUTONOMY_MODES))}",
    }


def _plan_only(user_request: str, workflow: str, autonomy_mode: str) -> dict[str, Any]:
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "execution_status": "plan-only",
        **_base_report(user_request=user_request, detected_workflow=workflow, autonomy_mode=autonomy_mode),
    }


def _blocked(report: dict[str, Any], *, execution_status: str, missing: list[str], next_question: str) -> dict[str, Any]:
    report.update(
        {
            "status": "blocked",
            "claim_status": "blocked",
            "execution_status": execution_status,
            "missing_blockers": missing,
            "next_question": next_question,
        }
    )
    return report


def run_auto_workflow(
    *,
    user_request: str,
    output_dir: Path,
    work_dir: Path | None = None,
    autonomy_mode: str = "safe-autopilot",
    place_name: str | None = None,
    bbox: str | None = None,
    confirmed_area: bool = False,
    highway_classes: str | None = None,
    net_file: Path | None = None,
    osm_file: Path | None = None,
    official_inventory_csv: Path | None = None,
    signal_plan_csv: Path | None = None,
    field_evidence_csv: Path | None = None,
    place_resolver: Callable[[str], dict[str, Any]] = resolve_osm_place,
    cleanup_workflow_func: Callable[..., dict[str, Any]] = run_osm_cleanup_workflow,
    tls_review_func: Callable[..., dict[str, Any]] = audit_tls_multisource,
) -> dict[str, Any]:
    if autonomy_mode not in AUTONOMY_MODES:
        return _invalid_mode(user_request, autonomy_mode)

    workflow = detect_workflow(user_request)
    if autonomy_mode == "inspect-only":
        return _plan_only(user_request, workflow, autonomy_mode)

    report = _base_report(user_request=user_request, detected_workflow=workflow, autonomy_mode=autonomy_mode)
    report["output_dir"] = str(output_dir)
    if work_dir is not None:
        report["work_dir"] = str(work_dir)

    if workflow == "osm_to_sumo":
        return _run_osm_to_sumo(
            report=report,
            user_request=user_request,
            output_dir=output_dir,
            place_name=place_name,
            bbox=bbox,
            confirmed_area=confirmed_area,
            highway_classes=highway_classes,
            autonomy_mode=autonomy_mode,
            place_resolver=place_resolver,
            cleanup_workflow_func=cleanup_workflow_func,
        )
    if workflow == "tls_review":
        return _run_tls_review(
            report=report,
            output_dir=output_dir,
            net_file=net_file,
            osm_file=osm_file,
            official_inventory_csv=official_inventory_csv,
            signal_plan_csv=signal_plan_csv,
            field_evidence_csv=field_evidence_csv,
            tls_review_func=tls_review_func,
        )
    if workflow == "routeability":
        return _blocked(
            report,
            execution_status="needs_route_endpoints",
            missing=["net_file", "route_endpoint_spec"],
            next_question="Which origin and destination should Torii snap to passenger-accessible SUMO edges?",
        )
    if workflow == "debug_bad_run":
        return _blocked(
            report,
            execution_status="needs_outputs",
            missing=["summary_or_tripinfo_or_log"],
            next_question="Which SUMO summary, tripinfo, log, or config should Torii inspect first?",
        )
    if workflow == "experiment_audit":
        return _blocked(
            report,
            execution_status="needs_experiment_pair",
            missing=["baseline_config_or_outputs", "variant_config_or_outputs"],
            next_question="Which baseline and variant configs or outputs should Torii audit as a paired comparison?",
        )
    return _blocked(
        report,
        execution_status="needs_sumo_artifact",
        missing=["sumo_config_or_network_or_outputs"],
        next_question="Which SUMO config, network, route, output, or log should Torii inspect?",
    )


def _run_osm_to_sumo(
    *,
    report: dict[str, Any],
    user_request: str,
    output_dir: Path,
    place_name: str | None,
    bbox: str | None,
    confirmed_area: bool,
    highway_classes: str | None,
    autonomy_mode: str,
    place_resolver: Callable[[str], dict[str, Any]],
    cleanup_workflow_func: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    inferred = (place_name or "").strip() or infer_place_name(user_request)
    if inferred:
        report["inferred_place_name"] = inferred
    if not bbox and not inferred:
        return _blocked(
            report,
            execution_status="needs_area",
            missing=["place_name_or_bbox"],
            next_question="Which OSM place name or bbox should Torii use?",
        )
    candidate: dict[str, Any] | None = None
    if not confirmed_area and not bbox:
        candidate = place_resolver(inferred)
        report.update(candidate)
        if autonomy_mode != "ask-first":
            resolved_bbox = str(candidate.get("candidate_bbox", ""))
            if candidate.get("status") == "pass" and resolved_bbox:
                bbox = resolved_bbox
                report["execution_status"] = "auto_area_candidate"
            else:
                report["execution_status"] = "needs_user_confirmation"
                report["status"] = "blocked"
                report["claim_status"] = "blocked"
                report["next_question"] = "Which OSM area or bbox should Torii use?"
                return report
        else:
            report["execution_status"] = "needs_user_confirmation"
            report["status"] = "blocked"
            report["claim_status"] = "blocked"
            report["next_question"] = "Confirm this OSM area and bbox before network construction?"
            return report

    selected_highway_classes = resolve_highway_classes(highway_classes, default_to_recommended=False)
    if selected_highway_classes is None:
        report.update(
            {
                "status": "blocked",
                "claim_status": "blocked",
                "execution_status": "needs_road_level_scope",
                "missing_blockers": ["highway_classes"],
                "road_level_options": list(ROAD_LEVEL_SCOPE_OPTIONS),
                "recommended_road_level": RECOMMENDED_ROAD_LEVEL_SCOPE,
                "next_question": ROAD_LEVEL_SCOPE_QUESTION,
            }
        )
        return report

    cleanup_kwargs = {
        "output_dir": output_dir,
        "bbox": bbox,
        "place_name": inferred or None,
        "confirmed_area": confirmed_area,
    }
    if _supports_keyword(cleanup_workflow_func, "highway_classes"):
        cleanup_kwargs["highway_classes"] = selected_highway_classes
    if _supports_keyword(cleanup_workflow_func, "run_routeability_audit_after_build"):
        cleanup_kwargs["run_routeability_audit_after_build"] = True
    workflow_report = cleanup_workflow_func(**cleanup_kwargs)
    report.update(
        {
            "status": workflow_report.get("status", "fail"),
            "claim_status": workflow_report.get("claim_status", "diagnostic-demo"),
            "execution_status": "executed",
            "tool_called": "sumo_osm_cleanup_workflow",
            "workflow_result": workflow_report,
        }
    )
    return report


def _supports_keyword(func: Callable[..., Any], name: str) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        or (parameter.name == name and parameter.kind in {inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD})
        for parameter in signature.parameters.values()
    )


def _run_tls_review(
    *,
    report: dict[str, Any],
    output_dir: Path,
    net_file: Path | None,
    osm_file: Path | None,
    official_inventory_csv: Path | None,
    signal_plan_csv: Path | None,
    field_evidence_csv: Path | None,
    tls_review_func: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if net_file is None:
        return _blocked(
            report,
            execution_status="needs_network",
            missing=["net_file"],
            next_question="Which SUMO .net.xml should Torii use for the TLS review?",
        )
    review = tls_review_func(
        net_file=net_file,
        output_dir=output_dir,
        osm_file=osm_file,
        official_inventory_csv=official_inventory_csv,
        signal_plan_csv=signal_plan_csv,
        field_evidence_csv=field_evidence_csv,
    )
    report.update(
        {
            "status": review.get("status", "fail"),
            "claim_status": review.get("claim_status", "diagnostic-demo"),
            "execution_status": "executed",
            "tool_called": "sumo_tls_multisource_review",
            "workflow_result": review,
        }
    )
    return report

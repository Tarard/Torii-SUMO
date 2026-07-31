from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from torii_sumo.core.workflow_manifest import (
    inspect_workflow_manifest,
    resolve_latest_manifest,
    run_managed_workflow,
)


def run_auto_workflow(**kwargs: Any) -> dict[str, Any]:
    """Load the legacy workflow router only when execution starts."""

    from torii_sumo.core.workflow_router import run_auto_workflow as implementation

    return implementation(**kwargs)


def detect_workflow(user_request: str) -> str:
    """Load request classification without importing the full executor at module import."""

    from torii_sumo.core.workflow_router import detect_workflow as implementation

    return implementation(user_request)


def _workflow_recipe(workflow_name: str) -> dict[str, Any]:
    from torii_sumo.core.workflow_router import WORKFLOW_RECIPES

    return WORKFLOW_RECIPES[workflow_name]


def sumo_osm_cleanup_workflow(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Load the large OSM workflow only when the selected route needs it."""

    from torii_sumo.tools.osm_tools import sumo_osm_cleanup_workflow as implementation

    return implementation(*args, **kwargs)


def torii_workflow_run(
    user_request: str,
    output_dir: str,
    work_dir: str | None = None,
    autonomy_mode: str = "safe-autopilot",
    place_name: str | None = None,
    bbox: str | None = None,
    confirmed_area: bool = False,
    highway_classes: str | None = None,
    traffic_layers: str | None = None,
    network_profile: str | None = None,
    seed_osm_node_id: str | None = None,
    reference_net_file: str | None = None,
    reference_policy_report: str | None = None,
    review_decisions_file: str | None = None,
    service_passenger_policy: str | None = None,
    teacher_guided_repair_max_ready_candidates: int | None = 80,
    run_teacher_guided_repair_after_build: bool = True,
    road_connectivity_replay_max_owners: int | None = 4,
    road_connectivity_probe_edge_ids: list[str] | None = None,
    teacher_guided_probe_matrix_junction_ids: list[str] | None = None,
    launch_netedit_after_build: bool | None = None,
    launch_sumo_gui_after_build: bool | None = None,
    net_file: str | None = None,
    osm_file: str | None = None,
    official_inventory_csv: str | None = None,
    signal_plan_csv: str | None = None,
    field_evidence_csv: str | None = None,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Run the canonical managed workflow and write a hash-bound manifest."""

    output_path = Path(output_dir)
    executor_kwargs = {
        "user_request": user_request,
        "output_dir": output_path,
        "work_dir": Path(work_dir) if work_dir else None,
        "autonomy_mode": autonomy_mode,
        "place_name": place_name,
        "bbox": bbox,
        "confirmed_area": confirmed_area,
        "highway_classes": highway_classes,
        "traffic_layers": traffic_layers,
        "network_profile": network_profile,
        "seed_osm_node_id": seed_osm_node_id,
        "reference_net_file": Path(reference_net_file) if reference_net_file else None,
        "reference_policy_report": reference_policy_report,
        "review_decisions_file": Path(review_decisions_file) if review_decisions_file else None,
        "service_passenger_policy": service_passenger_policy,
        "teacher_guided_repair_max_ready_candidates": teacher_guided_repair_max_ready_candidates,
        "run_teacher_guided_repair_after_build": run_teacher_guided_repair_after_build,
        "road_connectivity_replay_max_owners": road_connectivity_replay_max_owners,
        "road_connectivity_probe_edge_ids": road_connectivity_probe_edge_ids,
        "teacher_guided_probe_matrix_junction_ids": teacher_guided_probe_matrix_junction_ids,
        "launch_netedit_after_build": launch_netedit_after_build,
        "launch_sumo_gui_after_build": launch_sumo_gui_after_build,
        "net_file": Path(net_file) if net_file else None,
        "osm_file": Path(osm_file) if osm_file else None,
        "official_inventory_csv": Path(official_inventory_csv) if official_inventory_csv else None,
        "signal_plan_csv": Path(signal_plan_csv) if signal_plan_csv else None,
        "field_evidence_csv": Path(field_evidence_csv) if field_evidence_csv else None,
        "cleanup_workflow_func": sumo_osm_cleanup_workflow,
    }
    request_config = {
        key: value
        for key, value in executor_kwargs.items()
        if key not in {"user_request", "output_dir", "cleanup_workflow_func"}
    }
    invalid_execution_status = ""
    if not user_request.strip():
        invalid_execution_status = "invalid_user_request"
    elif autonomy_mode not in {"ask-first", "safe-autopilot", "inspect-only", "full-local-run"}:
        invalid_execution_status = "invalid_autonomy_mode"

    if invalid_execution_status:
        workflow_name = "general"
        tool_chain: list[str] = []

        def invalid_executor(**_kwargs: Any) -> dict[str, Any]:
            return {
                "status": "invalid",
                "claim_status": "blocked",
                "execution_status": invalid_execution_status,
                "autonomy_mode": autonomy_mode,
            }

        executor = invalid_executor
    else:
        workflow_name = detect_workflow(user_request)
        tool_chain = list(_workflow_recipe(workflow_name)["tool_chain"])
        executor = run_auto_workflow

    return run_managed_workflow(
        user_request=user_request,
        output_dir=output_path,
        workflow_name=workflow_name,
        tool_chain=tool_chain,
        request_config=request_config,
        executor=executor,
        executor_kwargs=executor_kwargs,
        resume=resume,
        force=force,
    )


def torii_workflow_status(
    output_dir: str | None = None,
    manifest_file: str | None = None,
) -> dict[str, Any]:
    """Inspect one workflow manifest and fail closed on changed artifacts."""

    if bool(output_dir) == bool(manifest_file):
        return {
            "status": "invalid",
            "claim_status": "blocked",
            "blockers": ["Provide exactly one of output_dir or manifest_file."],
            "next_actions": ["Pass a workflow output directory or an explicit manifest path."],
        }
    try:
        target = Path(manifest_file) if manifest_file else resolve_latest_manifest(Path(str(output_dir)))
        return inspect_workflow_manifest(target)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "invalid",
            "claim_status": "blocked",
            "blockers": [f"workflow_status_error: {exc}"],
            "next_actions": ["Check the output directory or manifest path."],
        }


def torii_auto_workflow(
    user_request: str,
    output_dir: str,
    work_dir: str | None = None,
    autonomy_mode: str = "safe-autopilot",
    place_name: str | None = None,
    bbox: str | None = None,
    confirmed_area: bool = False,
    highway_classes: str | None = None,
    traffic_layers: str | None = None,
    network_profile: str | None = None,
    seed_osm_node_id: str | None = None,
    reference_net_file: str | None = None,
    reference_policy_report: str | None = None,
    review_decisions_file: str | None = None,
    service_passenger_policy: str | None = None,
    teacher_guided_repair_max_ready_candidates: int | None = 80,
    run_teacher_guided_repair_after_build: bool = True,
    road_connectivity_replay_max_owners: int | None = 4,
    road_connectivity_probe_edge_ids: list[str] | None = None,
    teacher_guided_probe_matrix_junction_ids: list[str] | None = None,
    launch_netedit_after_build: bool | None = None,
    launch_sumo_gui_after_build: bool | None = None,
    net_file: str | None = None,
    osm_file: str | None = None,
    official_inventory_csv: str | None = None,
    signal_plan_csv: str | None = None,
    field_evidence_csv: str | None = None,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Compatibility entry point for the managed workflow.

    Existing report fields remain at the top level. New callers should use
    ``torii_workflow_run`` and read its explicit workflow status.
    """

    outcome = torii_workflow_run(
        user_request=user_request,
        output_dir=output_dir,
        work_dir=work_dir,
        autonomy_mode=autonomy_mode,
        place_name=place_name,
        bbox=bbox,
        confirmed_area=confirmed_area,
        highway_classes=highway_classes,
        traffic_layers=traffic_layers,
        network_profile=network_profile,
        seed_osm_node_id=seed_osm_node_id,
        reference_net_file=reference_net_file,
        reference_policy_report=reference_policy_report,
        review_decisions_file=review_decisions_file,
        service_passenger_policy=service_passenger_policy,
        teacher_guided_repair_max_ready_candidates=teacher_guided_repair_max_ready_candidates,
        run_teacher_guided_repair_after_build=run_teacher_guided_repair_after_build,
        road_connectivity_replay_max_owners=road_connectivity_replay_max_owners,
        road_connectivity_probe_edge_ids=road_connectivity_probe_edge_ids,
        teacher_guided_probe_matrix_junction_ids=teacher_guided_probe_matrix_junction_ids,
        launch_netedit_after_build=launch_netedit_after_build,
        launch_sumo_gui_after_build=launch_sumo_gui_after_build,
        net_file=net_file,
        osm_file=osm_file,
        official_inventory_csv=official_inventory_csv,
        signal_plan_csv=signal_plan_csv,
        field_evidence_csv=field_evidence_csv,
        resume=resume,
        force=force,
    )
    report = dict(outcome.get("result", {}))
    legacy_status = report.get("status")
    legacy_claim_status = report.get("claim_status")
    if outcome["status"] != "complete":
        report["legacy_status"] = legacy_status
        report["legacy_claim_status"] = legacy_claim_status
        report["status"] = outcome["status"]
        report["claim_status"] = outcome["claim_status"]
    report.update(
        {
            "workflow_status": outcome["status"],
            "workflow_claim_status": outcome["claim_status"],
            "workflow_run_id": outcome["run_id"],
            "workflow_execution": outcome["execution"],
            "workflow_manifest_file": outcome["manifest_file"],
            "workflow_result_file": outcome["result_file"],
            "workflow_blockers": outcome["blockers"],
            "workflow_review_items": outcome["review_items"],
            "workflow_next_actions": outcome["next_actions"],
            "workflow_evidence_summary": outcome["evidence_summary"],
            "compatibility_entrypoint": "torii_auto_workflow",
        }
    )
    return report

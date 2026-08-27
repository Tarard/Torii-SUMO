"""Small argparse-based Torii command line interface.

The CLI is intentionally a thin entry layer over the same business functions
used by the MCP tools.  It does not call the MCP server and the MCP server does
not spawn this CLI.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import anyio

from . import server as server_module
from .server import create_server
from .tools.mcp_contract_tools import (
    ToriiToolResult,
    torii_config_inspect,
    torii_demand_audit,
    torii_intersection_classify,
    torii_netedit_act,
    torii_netedit_close,
    torii_netedit_observe,
    torii_netedit_open,
    torii_network_audit,
    torii_network_compare,
    torii_place_resolve,
    torii_preflight,
    torii_review_create,
    torii_run_compare,
    torii_signal_classify,
)
from .tools.osm_tools import sumo_network_routeability_audit


_WORKFLOW_TOOL_NAMES = (
    "sumo_run_config",
    "sumo_run_minimal_smoke",
    "sumo_collect_evidence",
    "sumo_osm_build_network",
    "sumo_osm_cleanup_workflow",
    "sumo_tls_audit",
    "sumo_tls_multisource_review",
    "sumo_network_connected_core",
    "sumo_network_routeability_probe",
    "sumo_network_routeability_audit",
    "sumo_network_connection_mode_audit",
    "sumo_network_connection_mode_calibration",
    "sumo_network_exact_semantic_regression_audit",
    "sumo_network_overlapping_junction_audit",
    "sumo_network_reference_join_audit",
    "sumo_network_reference_hierarchy_audit",
    "sumo_network_reference_scope_audit",
    "sumo_network_tls_warning_parity",
    "sumo_network_surface_overlap_audit",
    "sumo_network_surface_overlap_comparison",
    "sumo_network_junction_aggregation_variant",
    "sumo_network_scope_pruning_variant",
    "sumo_network_corridor_geometry_simplification_variant",
    "sumo_network_corridor_edit_ledger",
    "sumo_network_corridor_materialize_variant",
    "sumo_network_corridor_candidate_gates",
    "sumo_network_teacher_corridor_comparison",
    "sumo_network_tls_reference_cleanup_variant",
    "sumo_network_standard_nema_phase_binding",
    "sumo_network_teacher_guided_junction_variant",
    "sumo_network_teacher_guided_repair_queue",
    "sumo_network_tls_aggregation_variant",
    "sumo_intersection_model",
    "sumo_intersection_clean",
    "sumo_intersection_validate",
    "sumo_nema_four_way_reference_workflow",
    "sumo_intersection_scene_workflow",
    "sumo_road_semantic_bridge",
    "sumo_intersection_road_sumo_bind",
    "sumo_detector_route_support",
    "sumo_detector_count_constraints",
    "sumo_detector_route_sampler_calibrate",
    "sumo_hamburg_sandtorkai_digital_twin",
    "sumo_hamburg_named_count_scope",
    "sumo_hamburg_sandtorkai_signal_observations",
    "sumo_hamburg_sandtorkai_named_replay",
    "sumo_hamburg_sandtorkai_execution_plan",
    "sumo_hamburg_2394_archetype_classify",
    "sumo_hamburg_2394_compound_geometry_first_pass",
    "sumo_hamburg_2394_tls_topology_materialize",
    "sumo_hamburg_sandtorkai_corridor_geometry_materialize",
    "sumo_hamburg_sandtorkai_mainline_scope_materialize",
    "sumo_hamburg_sandtorkai_corridor_tls_materialize",
    "sumo_hamburg_cached_detector_demand",
    "sumo_hamburg_corridor_candidate_detector_demand",
    "sumo_hamburg_corridor_candidate_map_bindings",
    "sumo_hamburg_corridor_candidate_signal_bindings",
    "sumo_hamburg_sandtorkai_corridor_candidate_package",
    "sumo_hamburg_sandtorkai_geometry_safe_digital_twin",
    "sumo_hamburg_official_tls_rebuild",
    "sumo_digital_twin_replay_validate",
)

WORKFLOW_TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    name: getattr(server_module, name) for name in _WORKFLOW_TOOL_NAMES
}


def _exit_code(result: ToriiToolResult | dict[str, Any]) -> int:
    status = result.get("status") if isinstance(result, dict) else result.status
    if status in {"pass", "ok", "success", "complete", "ready"}:
        return 0
    if status in {
        "review_required",
        "review_ready",
        "topology_ready",
        "partial",
        "unknown",
        "warn",
    }:
        return 1
    return 3


def _emit(result: ToriiToolResult | dict[str, Any], *, json_output: bool) -> int:
    if json_output:
        if isinstance(result, ToriiToolResult):
            print(result.model_dump_json(indent=2))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        if isinstance(result, ToriiToolResult):
            print(f"{result.status}: {result.summary}")
            if result.next_actions:
                for action in result.next_actions:
                    print(f"next: {action}")
        else:
            print(str(result))
    return _exit_code(result)


def _add_output_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit a structured JSON result.",
    )


def _load_request(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workflow request must be a JSON object")
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="torii")
    parser.add_argument("--json", action="store_true", help="Emit a structured JSON result for every subcommand.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight", help="Check Python, SUMO, and Torii environment.")
    _add_output_argument(preflight)

    config = subparsers.add_parser("config", help="Inspect config pairs.")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    inspect = config_sub.add_parser("inspect", help="Inspect a baseline and variant .sumocfg pair.")
    inspect.add_argument("baseline_config")
    inspect.add_argument("variant_config")
    _add_output_argument(inspect)

    run = subparsers.add_parser("run", help="Run bounded SUMO comparisons.")
    run_sub = run.add_subparsers(dest="run_command", required=True)
    compare = run_sub.add_parser("compare", help="Compare baseline and variant outputs.")
    compare.add_argument("--baseline-summary")
    compare.add_argument("--baseline-tripinfo")
    compare.add_argument("--variant-summary")
    compare.add_argument("--variant-tripinfo")
    _add_output_argument(compare)

    place = subparsers.add_parser("place", help="Resolve OSM places.")
    place_sub = place.add_subparsers(dest="place_command", required=True)
    resolve = place_sub.add_parser("resolve", help="Resolve a place name to a candidate OSM area.")
    resolve.add_argument("place_name")
    resolve.add_argument("--limit", type=int, default=1)
    _add_output_argument(resolve)

    intersection = subparsers.add_parser("intersection", help="Intersection classification.")
    intersection_sub = intersection.add_subparsers(dest="intersection_command", required=True)
    classify = intersection_sub.add_parser("classify", help="Classify one local OSM intersection.")
    classify.add_argument("osm_file")
    classify.add_argument("seed_osm_node_id")
    classify.add_argument("--traffic-side", default="right", choices=("left", "right"))
    classify.add_argument("--road-network-evidence-file")
    _add_output_argument(classify)

    signal = subparsers.add_parser("signal", help="Signal inventory classification.")
    signal_sub = signal.add_subparsers(dest="signal_command", required=True)
    signal_classify = signal_sub.add_parser("classify", help="Classify one OCIT-C signal inventory.")
    signal_classify.add_argument("ocit_file")
    signal_classify.add_argument("--expected-node-id")
    _add_output_argument(signal_classify)

    network = subparsers.add_parser("network", help="Network audits and comparisons.")
    network_sub = network.add_subparsers(dest="network_command", required=True)
    audit = network_sub.add_parser("audit", help="Audit one local SUMO network.")
    audit.add_argument("net_file")
    audit.add_argument("output_dir")
    audit.add_argument("--profile", default="standard", choices=("quick", "standard"))
    audit.add_argument("--prefix", default="network_audit")
    _add_output_argument(audit)
    network_compare = network_sub.add_parser("compare", help="Compare source and candidate networks.")
    network_compare.add_argument("source_net_file")
    network_compare.add_argument("candidate_net_file")
    network_compare.add_argument("output_dir")
    network_compare.add_argument("--prefix", default="network_compare")
    _add_output_argument(network_compare)
    routeability = network_sub.add_parser(
        "routeability",
        help="Run the long completion-aware SUMO routeability audit outside MCP.",
    )
    routeability.add_argument("net_file")
    routeability.add_argument("output_dir")
    routeability.add_argument("--prefix", default="routeability_audit")
    routeability.add_argument("--vehicle-count", type=int, default=100)
    routeability.add_argument("--seed", type=int, default=42)
    routeability.add_argument("--initial-end", type=int, default=300)
    routeability.add_argument("--max-end", type=int, default=2400)
    routeability.add_argument("--timeout-seconds", type=float, default=240.0)
    _add_output_argument(routeability)

    demand = subparsers.add_parser("demand", help="Demand and detector audits.")
    demand_sub = demand.add_subparsers(dest="demand_command", required=True)
    audit_counts = demand_sub.add_parser("audit", help="Compare expected and observed detector counts.")
    audit_counts.add_argument("expected_counts_csv")
    audit_counts.add_argument("detector_output_xml")
    audit_counts.add_argument("output_dir")
    audit_counts.add_argument("--prefix", default="demand_audit")
    _add_output_argument(audit_counts)

    review = subparsers.add_parser("review", help="Create review artifacts.")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    create = review_sub.add_parser("create", help="Create a network review HTML page.")
    create.add_argument("output_dir")
    create.add_argument("--net-file")
    create.add_argument("--title", default="SUMO Network Review")
    create.add_argument("--claim-status", default="diagnostic-demo")
    create.add_argument("--raw-net-file")
    create.add_argument("--connected-core-file")
    create.add_argument("--tls-review-file")
    create.add_argument("--topology-audit-report-file")
    create.add_argument("--junction-aggregation-report-file")
    create.add_argument("--routeability-audit-report-file")
    _add_output_argument(create)

    netedit = subparsers.add_parser("netedit", help="NetEdit observation-action loop.")
    netedit_sub = netedit.add_subparsers(dest="netedit_command", required=True)
    netedit_open = netedit_sub.add_parser("open", help="Open a hash-bound NetEdit review session.")
    netedit_open.add_argument("source_net_file")
    netedit_open.add_argument("candidate_net_file")
    netedit_open.add_argument("output_dir")
    netedit_open.add_argument("expected_source_sha256")
    netedit_open.add_argument("--gui-settings-file")
    netedit_open.add_argument("--selection-file")
    netedit_open.add_argument("--target-source-junction-ids", nargs="*")
    netedit_open.add_argument("--target-candidate-junction-ids", nargs="*")
    _add_output_argument(netedit_open)
    netedit_observe = netedit_sub.add_parser("observe", help="Observe the active NetEdit session.")
    netedit_observe.add_argument("session_id")
    netedit_observe.add_argument("--object-type", choices=("junction", "edge", "lane", "connection", "tlLogic"))
    netedit_observe.add_argument("--object-id")
    _add_output_argument(netedit_observe)
    netedit_act = netedit_sub.add_parser("act", help="Execute one whitelisted NetEdit action.")
    netedit_act.add_argument("session_id")
    netedit_act.add_argument("action")
    netedit_act.add_argument("expected_screenshot_sha256")
    netedit_act.add_argument("--x", type=int)
    netedit_act.add_argument("--y", type=int)
    netedit_act.add_argument("--to-x", type=int)
    netedit_act.add_argument("--to-y", type=int)
    _add_output_argument(netedit_act)
    netedit_close = netedit_sub.add_parser(
        "close",
        help="Finalize or abort the active NetEdit session.",
    )
    netedit_close.add_argument("session_id")
    netedit_close.add_argument("--mode", choices=("finalize", "abort"), required=True)
    netedit_close.add_argument("--expected-screenshot-sha256")
    netedit_close.add_argument("--reason")
    _add_output_argument(netedit_close)

    workflow = subparsers.add_parser(
        "workflow",
        help="Run an allowlisted long or specialized workflow from a JSON request file.",
    )
    workflow.add_argument("tool", choices=tuple(WORKFLOW_TOOLS), metavar="TOOL")
    workflow.add_argument("request_file")
    _add_output_argument(workflow)

    mcp = subparsers.add_parser("mcp", help="Run the Torii MCP server.")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    serve = mcp_sub.add_parser("serve", help="Start the stdio MCP server.")
    serve.add_argument("--profile", choices=("legacy", "default", "netedit"), default="default")

    return parser


def _dispatch(args: argparse.Namespace) -> int:
    json_output = bool(getattr(args, "json", False))

    if args.command == "preflight":
        return _emit(torii_preflight(), json_output=json_output)
    if args.command == "config" and args.config_command == "inspect":
        return _emit(
            torii_config_inspect(args.baseline_config, args.variant_config),
            json_output=json_output,
        )
    if args.command == "run" and args.run_command == "compare":
        return _emit(
            torii_run_compare(
                baseline_summary=args.baseline_summary,
                baseline_tripinfo=args.baseline_tripinfo,
                variant_summary=args.variant_summary,
                variant_tripinfo=args.variant_tripinfo,
            ),
            json_output=json_output,
        )
    if args.command == "place" and args.place_command == "resolve":
        return _emit(torii_place_resolve(args.place_name, limit=args.limit), json_output=json_output)
    if args.command == "intersection" and args.intersection_command == "classify":
        return _emit(
            torii_intersection_classify(
                args.osm_file,
                args.seed_osm_node_id,
                traffic_side=args.traffic_side,
                road_network_evidence_file=args.road_network_evidence_file,
            ),
            json_output=json_output,
        )
    if args.command == "signal" and args.signal_command == "classify":
        return _emit(
            torii_signal_classify(args.ocit_file, expected_node_id=args.expected_node_id),
            json_output=json_output,
        )
    if args.command == "network" and args.network_command == "audit":
        return _emit(
            torii_network_audit(
                args.net_file,
                args.output_dir,
                profile=args.profile,
                prefix=args.prefix,
            ),
            json_output=json_output,
        )
    if args.command == "network" and args.network_command == "compare":
        return _emit(
            torii_network_compare(
                args.source_net_file,
                args.candidate_net_file,
                args.output_dir,
                prefix=args.prefix,
            ),
            json_output=json_output,
        )
    if args.command == "network" and args.network_command == "routeability":
        return _emit(
            sumo_network_routeability_audit(
                net_file=args.net_file,
                output_dir=args.output_dir,
                prefix=args.prefix,
                vehicle_count=args.vehicle_count,
                seed=args.seed,
                initial_end=args.initial_end,
                max_end=args.max_end,
                timeout_seconds=args.timeout_seconds,
            ),
            json_output=json_output,
        )
    if args.command == "demand" and args.demand_command == "audit":
        return _emit(
            torii_demand_audit(
                args.expected_counts_csv,
                args.detector_output_xml,
                args.output_dir,
                prefix=args.prefix,
            ),
            json_output=json_output,
        )
    if args.command == "review" and args.review_command == "create":
        return _emit(
            torii_review_create(
                args.output_dir,
                net_file=args.net_file,
                title=args.title,
                claim_status=args.claim_status,
                raw_net_file=args.raw_net_file,
                connected_core_file=args.connected_core_file,
                tls_review_file=args.tls_review_file,
                topology_audit_report_file=args.topology_audit_report_file,
                junction_aggregation_report_file=args.junction_aggregation_report_file,
                routeability_audit_report_file=args.routeability_audit_report_file,
            ),
            json_output=json_output,
        )
    if args.command == "netedit":
        if args.netedit_command == "open":
            return _emit(
                torii_netedit_open(
                    args.source_net_file,
                    args.candidate_net_file,
                    args.output_dir,
                    args.expected_source_sha256,
                    gui_settings_file=args.gui_settings_file,
                    selection_file=args.selection_file,
                    target_source_junction_ids=args.target_source_junction_ids,
                    target_candidate_junction_ids=args.target_candidate_junction_ids,
                ),
                json_output=json_output,
            )
        if args.netedit_command == "observe":
            return _emit(
                torii_netedit_observe(
                    args.session_id,
                    object_type=args.object_type,
                    object_id=args.object_id,
                ),
                json_output=json_output,
            )
        if args.netedit_command == "act":
            return _emit(
                torii_netedit_act(
                    args.session_id,
                    args.action,
                    args.expected_screenshot_sha256,
                    x=args.x,
                    y=args.y,
                    to_x=args.to_x,
                    to_y=args.to_y,
                ),
                json_output=json_output,
            )
        if args.netedit_command == "close":
            return _emit(
                torii_netedit_close(
                    args.session_id,
                    mode=args.mode,
                    expected_screenshot_sha256=args.expected_screenshot_sha256,
                    reason=args.reason,
                ),
                json_output=json_output,
            )
    if args.command == "workflow":
        return _emit(
            WORKFLOW_TOOLS[args.tool](**_load_request(args.request_file)),
            json_output=json_output,
        )
    if args.command == "mcp" and args.mcp_command == "serve":
        server = create_server(args.profile)

        async def _run() -> None:
            await server.run_stdio_async()

        anyio.run(_run)
        return 0

    parser = _build_parser()
    parser.print_help(sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except Exception as exc:  # noqa: BLE001 - CLI boundary must not leak tracebacks.
        if getattr(args, "json", False):
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

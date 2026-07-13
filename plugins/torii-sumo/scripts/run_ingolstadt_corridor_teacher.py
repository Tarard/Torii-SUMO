from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


DEFAULT_BBOX = "11.413800,48.755391,11.433800,48.775391"
DEFAULT_JUNCTION_ID = "267517510"
VISUAL_HIGHWAYS = {
    "cycleway",
    "footway",
    "living_street",
    "path",
    "pedestrian",
    "primary",
    "residential",
    "secondary",
    "secondary_link",
    "service",
    "steps",
    "tertiary",
    "tertiary_link",
    "track",
    "unclassified",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download the Ingolstadt reference bbox (or use an explicit candidate) and build one "
            "candidate-bound teacher-corridor review package."
        )
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--teacher-net", type=Path, default=None)
    parser.add_argument("--candidate-net", type=Path, default=None)
    parser.add_argument(
        "--source-osm",
        type=Path,
        default=None,
        help="Optional hash-fixed OSM evidence to use with --candidate-net for offline replay.",
    )
    parser.add_argument("--bbox", default=DEFAULT_BBOX)
    parser.add_argument("--junction-id", default=DEFAULT_JUNCTION_ID)
    parser.add_argument("--historical-date", default=None)
    parser.add_argument("--map-temporal-scope", choices=("current", "historical"), default="current")
    parser.add_argument("--map-target-date", default=None)
    parser.add_argument("--overpass-url", default="https://overpass-api.de/api/interpreter")
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--skip-runtime-audits", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[3]
    source_root = repo_root / "plugins" / "torii-sumo" / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

    from torii_sumo.core.artifact_io import write_json_atomic
    from torii_sumo.core.candidate_contracts import file_sha256
    from torii_sumo.core.command_runner import run_command
    from torii_sumo.core.osm_network import build_osm_network
    from torii_sumo.core.routeability_audit import run_routeability_audit
    from torii_sumo.core.sumo_commands import discover_binaries
    from torii_sumo.core.teacher_corridor import build_teacher_corridor_comparison
    from torii_sumo.core.tls_reference_cleanup import build_tls_reference_cleanup_variant

    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else repo_root / "outputs" / "ingolstadt_corridor_teacher_20260713" / "current_osm"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    teacher_net = (
        args.teacher_net.resolve()
        if args.teacher_net is not None
        else repo_root
        / "examples"
        / "02_one_prompt_osm_network"
        / "networks"
        / "tum_ingolstadt_center_reference.net.xml"
    )
    binaries = discover_binaries()
    netconvert = str(binaries.get("netconvert", ""))
    if not netconvert:
        raise RuntimeError("netconvert is not available from a consistent SUMO toolchain")
    sumo_bin_dir = Path(netconvert).resolve().parent
    os.environ["SUMO_HOME"] = str(sumo_bin_dir.parent)
    os.environ["PATH"] = f"{sumo_bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"

    build_report: dict[str, Any]
    if args.candidate_net is not None:
        raw_candidate_net = args.candidate_net.resolve()
        explicit_osm = args.source_osm.resolve() if args.source_osm is not None else None
        explicit_inputs_exist = raw_candidate_net.is_file() and (
            explicit_osm is None or explicit_osm.is_file()
        )
        build_report = {
            "status": "pass" if explicit_inputs_exist else "blocked",
            "source": "explicit_candidate_net",
            "bbox": args.bbox,
            "net_file": str(raw_candidate_net),
            "source_osm_file": str(explicit_osm) if explicit_osm is not None else "",
            "warnings": [
                "OSM download was skipped because --candidate-net was supplied; supplied files are "
                "hash-bound into the replay manifest"
            ],
        }
        if not explicit_inputs_exist:
            build_report["error"] = "explicit candidate or optional source OSM does not exist"
    else:
        build_report = build_osm_network(
            bbox=args.bbox,
            output_dir=output_dir / "osm_build",
            prefix="ingolstadt_same_bbox_current_osm",
            source_osm_path=args.source_osm.resolve() if args.source_osm is not None else None,
            allowed_highways=set(VISUAL_HIGHWAYS),
            historical_date=args.historical_date,
            overpass_url=args.overpass_url,
            timeout_seconds=args.timeout_seconds,
            max_tile_area_km2=2500.0,
            max_retries=2,
            retry_pause_seconds=5.0,
            netconvert_profile="reference_visual_detail",
            include_railway=True,
            allowed_railways={"rail"},
            netconvert_binary=netconvert,
        )
        built_net_value = str(build_report.get("net_file", "")).strip()
        raw_candidate_net = (
            Path(built_net_value).resolve()
            if built_net_value
            else output_dir / "unavailable_candidate.net.xml"
        )
    build_report_file = output_dir / "same_bbox_osm_build.json"
    write_json_atomic(build_report_file, build_report, sort_keys=True)

    tls_reference_cleanup: dict[str, Any] = {
        "status": "not_run",
        "tls_reference_cleanup_status": "not_run",
    }
    candidate_net = raw_candidate_net
    if build_report.get("status") == "pass" and raw_candidate_net.is_file():
        tls_reference_cleanup = build_tls_reference_cleanup_variant(
            raw_candidate_net,
            output_dir=output_dir / "tls_reference_cleanup",
            prefix="ingolstadt_same_bbox",
        )
        effective_net = str(tls_reference_cleanup.get("effective_net_file", "")).strip()
        if tls_reference_cleanup.get("status") == "pass" and effective_net:
            candidate_net = Path(effective_net).resolve()

    sumo_load_report: dict[str, Any] = {"status": "not_run"}
    routeability_report: dict[str, Any] = {"status": "not_run"}
    if (
        build_report.get("status") == "pass"
        and tls_reference_cleanup.get("status") == "pass"
        and candidate_net.is_file()
        and not args.skip_runtime_audits
    ):
        sumo_load_log = output_dir / "sumo_load_errors.log"
        sumo_load_command = [
            str(binaries["sumo"]),
            "--net-file",
            str(candidate_net),
            "--quit-on-end",
            "--duration-log.disable",
            "--no-step-log",
            "--error-log",
            str(sumo_load_log),
        ]
        sumo_load_result = run_command(
            sumo_load_command,
            cwd=output_dir,
            timeout_seconds=args.timeout_seconds,
        ).to_dict()
        sumo_load_report = {
            "status": (
                "pass"
                if sumo_load_result.get("status") == "pass"
                and sumo_load_result.get("returncode") == 0
                else "blocked"
            ),
            "command": sumo_load_command,
            "result": sumo_load_result,
            "log_file": str(sumo_load_log),
        }
        routeability_report = run_routeability_audit(
            net_file=candidate_net,
            output_dir=output_dir / "routeability",
            prefix="ingolstadt_same_bbox",
            vehicle_count=10,
            initial_end=300,
            max_end=1200,
            timeout_seconds=args.timeout_seconds,
            binaries=binaries,
        )
    elif args.skip_runtime_audits:
        sumo_load_report = {"status": "skipped_by_user"}
        routeability_report = {"status": "skipped_by_user"}
    sumo_load_report_file = output_dir / "sumo_load_report.json"
    write_json_atomic(sumo_load_report_file, sumo_load_report, sort_keys=True)

    if (
        build_report.get("status") == "pass"
        and tls_reference_cleanup.get("status") == "pass"
        and candidate_net.is_file()
    ):
        comparison = build_teacher_corridor_comparison(
            teacher_net_file=teacher_net,
            candidate_net_file=candidate_net,
            junction_id=args.junction_id,
            output_dir=output_dir / "teacher_corridor",
            prefix=f"ingolstadt_{args.junction_id}",
            map_temporal_scope=args.map_temporal_scope,
            map_target_date=args.map_target_date,
            osm_file=(
                Path(str(build_report.get("source_osm_file", "")))
                if str(build_report.get("source_osm_file", "")).strip()
                else None
            ),
        )
    else:
        comparison = {
            "status": "blocked",
            "claim_status": "construction-invalid",
            "teacher_transfer_status": "not_started",
            "error": "same-bbox OSM build or bounded TLS-reference cleanup did not pass",
        }

    runtime_pass = args.skip_runtime_audits or (
        sumo_load_report.get("status") == "pass"
        and routeability_report.get("status") == "pass"
    )
    status = (
        "pass"
        if build_report.get("status") == "pass"
        and tls_reference_cleanup.get("status") == "pass"
        and comparison.get("status") == "pass"
        and runtime_pass
        else "blocked"
    )
    manifest_file = output_dir / "ingolstadt_corridor_teacher_run.manifest.json"
    aggregate = {
        "schema": "torii.ingolstadt_corridor_teacher_run.v2",
        "status": status,
        "claim_status": "diagnostic-demo" if status == "pass" else "construction-invalid",
        "bbox": args.bbox,
        "junction_id": args.junction_id,
        "teacher_net_file": str(teacher_net),
        "raw_candidate_net_file": str(raw_candidate_net),
        "candidate_net_file": str(candidate_net),
        "osm_source_mode": (
            "explicit_candidate_with_osm_evidence"
            if args.candidate_net is not None and args.source_osm is not None
            else "explicit_candidate"
            if args.candidate_net is not None
            else "explicit_osm_rebuild"
            if args.source_osm is not None
            else "downloaded_same_bbox"
        ),
        "historical_date": args.historical_date or "",
        "map_temporal_scope": args.map_temporal_scope,
        "map_target_date": args.map_target_date or "",
        "sumo_toolchain": binaries,
        "build_report_file": str(build_report_file),
        "build": build_report,
        "tls_reference_cleanup": tls_reference_cleanup,
        "sumo_load": sumo_load_report,
        "routeability": routeability_report,
        "teacher_corridor": comparison,
        "runtime_audit_status": "skipped_by_user" if args.skip_runtime_audits else (
            "pass" if runtime_pass else "blocked"
        ),
        "source_network_mutation": False,
        "manifest_file": str(manifest_file),
        "next_boundary": (
            "review the bounded structural TLS cleanup and teacher differences against current map evidence, "
            "then materialize one crossing or TLS/movement candidate at a time through the corridor contract"
        ),
    }
    aggregate_file = output_dir / "ingolstadt_corridor_teacher_run.json"
    write_json_atomic(aggregate_file, aggregate, sort_keys=True)
    artifact_paths = [
        build_report_file,
        raw_candidate_net,
        candidate_net,
        sumo_load_report_file,
        aggregate_file,
    ]
    for value in (
        build_report.get("source_osm_file"),
        build_report.get("filtered_osm_file"),
        tls_reference_cleanup.get("plan_file"),
        tls_reference_cleanup.get("report_file"),
        tls_reference_cleanup.get("manifest_file"),
        tls_reference_cleanup.get("review_overlay_file"),
        routeability_report.get("report_file"),
        routeability_report.get("manifest_file"),
        comparison.get("report_file"),
        comparison.get("manifest_file"),
        comparison.get("map_review_evidence_file"),
        comparison.get("review_overlay_file"),
        comparison.get("review_decision_template_file"),
        comparison.get("review_html_file"),
    ):
        if str(value or "").strip():
            artifact_paths.append(Path(str(value)))
    artifacts = []
    seen_paths: set[str] = set()
    for artifact in artifact_paths:
        if not artifact.is_file():
            continue
        resolved = str(artifact.resolve())
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        artifacts.append(
            {
                "path": resolved,
                "size_bytes": artifact.stat().st_size,
                "sha256": file_sha256(artifact),
            }
        )
    write_json_atomic(
        manifest_file,
        {
            "schema": "torii.ingolstadt_corridor_teacher_manifest.v1",
            "status": status,
            "claim_status": aggregate["claim_status"],
            "bbox": args.bbox,
            "junction_id": args.junction_id,
            "source_overwrite_forbidden": True,
            "artifacts": artifacts,
        },
        sort_keys=True,
    )
    output = (
        {**aggregate, "aggregate_file": str(aggregate_file)}
        if args.verbose
        else {
            "status": status,
            "bbox": args.bbox,
            "junction_id": args.junction_id,
            "osm_source_mode": aggregate["osm_source_mode"],
            "raw_candidate_net_file": str(raw_candidate_net),
            "candidate_net_file": str(candidate_net),
            "tls_reference_cleanup_status": tls_reference_cleanup.get(
                "tls_reference_cleanup_status",
                "blocked",
            ),
            "teacher_transfer_status": comparison.get("teacher_transfer_status", "blocked"),
            "mismatch_fields": comparison.get("comparison", {}).get("mismatch_fields", []),
            "map_review_readiness_status": comparison.get(
                "map_review_readiness_status",
                "blocked",
            ),
            "review_html_file": comparison.get("review_html_file", ""),
            "runtime_audit_status": aggregate["runtime_audit_status"],
            "manifest_file": str(manifest_file),
            "aggregate_file": str(aggregate_file),
        }
    )
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import html
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree as ET

from torii_sumo.corridor.audit_pipeline import (
    build_exact_semantic_regression_artifacts,
)
from torii_sumo.corridor.enums import TrafficSide
from torii_sumo.corridor.netxml import normalized_net_sha256

from .artifact_io import copy_file_atomic, write_json_atomic, write_text_atomic
from .candidate_contracts import file_sha256
from .command_runner import run_command
from .movement_routeability import run_all_turn_movement_smoke
from .sumo_commands import discover_binaries, run_sumo_load_audit


def run_isolated_junction_workflow(
    *,
    example_dir: Path,
    output_dir: Path,
    toolchain_lock_file: Path,
    binaries: Mapping[str, str | None] | None = None,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Run one frozen isolated-junction evidence pipeline."""

    example = example_dir.resolve(strict=True)
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    prompt_file = example / "prompt.txt"
    spec_file = example / "spec.json"
    registry_file = example / "source-registry.json"
    spec = json.loads(spec_file.read_text(encoding="utf-8"))
    registry = json.loads(registry_file.read_text(encoding="utf-8"))
    prompt = prompt_file.read_text(encoding="utf-8").strip()
    _validate_spec(prompt=prompt, spec=spec)
    slice_id = str(spec.get("slice_id", "xs1"))
    source_net_name = str(
        spec.get("artifacts", {}).get(
            "source_net_file", f"{slice_id}-source.net.xml"
        )
    )
    candidate_net_name = str(
        spec.get("artifacts", {}).get(
            "candidate_net_file", f"{slice_id}-candidate.net.xml"
        )
    )
    for name in (
        "finding-continuity.json",
        "manifest.json",
        "manifest.public.json",
        "netconvert-build.json",
        "review.add.xml",
        "review.html",
        "rollback.json",
        "rollback.public.json",
        "summary.json",
        "summary.public.json",
        "tls-ownership.json",
        "tls-ownership.public.json",
        "visual-review.json",
        "visual-review.public.json",
        source_net_name,
        candidate_net_name,
    ):
        (destination / name).unlink(missing_ok=True)

    frozen_osm = (example / str(spec["source"]["osm_file"])).resolve()
    join_patch = (example / str(spec["candidate"]["join_patch_file"])).resolve()
    tls_patch_value = spec["candidate"].get("tls_patch_file")
    tls_patch = (
        (example / str(tls_patch_value)).resolve()
        if tls_patch_value
        else None
    )
    identity_checks = {
        "prompt_matches_spec": prompt == str(spec["prompt"]),
        "osm_sha256": file_sha256(frozen_osm)
        == str(spec["source"]["osm_sha256"]),
        "join_patch_sha256": file_sha256(join_patch)
        == str(spec["candidate"]["join_patch_sha256"]),
        "registry_matches_osm": str(registry["frozen_import"]["sha256"])
        == file_sha256(frozen_osm),
    }
    if tls_patch is not None:
        identity_checks["tls_patch_sha256"] = file_sha256(tls_patch) == str(
            spec["candidate"]["tls_patch_sha256"]
        )
    if not all(identity_checks.values()):
        return _write_blocked_result(
            destination,
            slice_id=slice_id,
            reason="frozen input identity check failed",
            details=identity_checks,
        )

    selected = dict(binaries or discover_binaries())
    missing = [name for name in ("netconvert", "sumo") if not selected.get(name)]
    if missing:
        return _write_blocked_result(
            destination,
            slice_id=slice_id,
            reason="required SUMO binaries are unavailable",
            details={"missing": missing},
        )
    netconvert = str(selected["netconvert"])
    sumo = str(selected["sumo"])
    source_net = destination / source_net_name
    candidate_net = destination / candidate_net_name
    relative_osm = os.path.relpath(frozen_osm, destination)
    relative_join_patch = os.path.relpath(join_patch, destination)
    relative_tls_patch = (
        os.path.relpath(tls_patch, destination) if tls_patch is not None else None
    )
    common = [
        "--osm-files",
        relative_osm,
        "--proj.utm",
        "--no-turnarounds",
        "--osm.all-attributes",
        "--tls.join",
        "--tls.join-dist",
        str(spec["source"]["tls_join_distance_m"]),
        "--verbose",
    ]
    source_options = spec["source"].get("netconvert_options", {})
    geo_boundary = source_options.get("keep_edges_in_geo_boundary")
    if geo_boundary:
        common.extend(["--keep-edges.in-geo-boundary", str(geo_boundary)])
    vehicle_class = source_options.get("keep_edges_by_vclass")
    if vehicle_class:
        common.extend(["--keep-edges.by-vclass", str(vehicle_class)])
    if bool(source_options.get("remove_edges_isolated", False)):
        common.append("--remove-edges.isolated")
    source_command = [
        netconvert,
        *common,
        "--output-file",
        source_net.name,
    ]
    candidate_command = [
        netconvert,
        *common[:2],
        "--node-files",
        relative_join_patch,
    ]
    if relative_tls_patch is not None:
        candidate_command.extend(["--tllogic-files", relative_tls_patch])
    candidate_command.extend(
        [*common[2:], "--output-file", candidate_net.name]
    )
    source_result = run_command(
        source_command,
        cwd=destination,
        timeout_seconds=timeout_seconds,
    ).to_dict()
    candidate_result = run_command(
        candidate_command,
        cwd=destination,
        timeout_seconds=timeout_seconds,
    ).to_dict()
    build_report = {
        "schema": _slice_schema(slice_id, "netconvert-build"),
        "source": _build_result(source_result, source_net),
        "candidate": _build_result(candidate_result, candidate_net),
        "only_declared_candidate_difference": {
            "operation_count": 1 + int(tls_patch is not None),
            "operation": (
                "plainxml_join_patch" if tls_patch is None else None
            ),
            "operations": [
                "plainxml_join_patch",
                *(["plainxml_tls_patch"] if tls_patch is not None else []),
            ],
            "join_patch_file": str(join_patch),
            "join_patch_sha256": file_sha256(join_patch),
            "tls_patch_file": str(tls_patch) if tls_patch else None,
            "tls_patch_sha256": file_sha256(tls_patch) if tls_patch else None,
        },
    }
    build_report_file = destination / "netconvert-build.json"
    write_json_atomic(build_report_file, build_report, sort_keys=True)
    if not all(
        build_report[role]["status"] == "pass"
        for role in ("source", "candidate")
    ):
        return _write_blocked_result(
            destination,
            slice_id=slice_id,
            reason="netconvert did not build both source and candidate",
            details=build_report,
        )

    expected_source_semantic_hash = str(
        registry["frozen_import"].get("expected_source_normalized_net_sha256", "")
    )
    expected_candidate_semantic_hash = str(
        registry["frozen_import"].get(
            "expected_candidate_normalized_net_sha256",
            "",
        )
    )
    semantic_reproduction = {
        "source_normalized_net_sha256": normalized_net_sha256(source_net),
        "candidate_normalized_net_sha256": normalized_net_sha256(
            candidate_net
        ),
    }
    semantic_reproduction["source_matches_frozen"] = (
        not expected_source_semantic_hash
        or semantic_reproduction["source_normalized_net_sha256"]
        == expected_source_semantic_hash
    )
    semantic_reproduction["candidate_matches_frozen"] = (
        not expected_candidate_semantic_hash
        or semantic_reproduction["candidate_normalized_net_sha256"]
        == expected_candidate_semantic_hash
    )

    expected_controller_ids = tuple(
        map(
            str,
            spec["candidate"].get(
                "expected_controller_ids",
                (spec["candidate"]["target_junction_id"],),
            ),
        )
    )
    tls_ownership = _audit_tls_ownership_rebuild(
        source_net=source_net,
        candidate_net=candidate_net,
        target_source_junction_ids=tuple(
            map(str, spec["scope"]["target_source_junction_ids"])
        ),
        target_candidate_junction_id=str(
            spec["candidate"]["target_junction_id"]
        ),
        expected_controller_ids=expected_controller_ids,
        expected_controlled_connection_count=int(
            spec["candidate"]["expected_direct_movement_count"]
        ),
        slice_id=slice_id,
    )
    tls_ownership_file = destination / "tls-ownership.json"
    write_json_atomic(tls_ownership_file, tls_ownership, sort_keys=True)

    exact = build_exact_semantic_regression_artifacts(
        source_net,
        candidate_net,
        output_dir=destination / "exact-audit",
        toolchain_lock_file=toolchain_lock_file,
        traffic_side=TrafficSide(str(spec["traffic_side"])),
        target_source_junction_ids=tuple(
            map(str, spec["scope"]["target_source_junction_ids"])
        ),
        target_candidate_junction_ids=(
            str(spec["candidate"]["target_junction_id"]),
        ),
        guard_source_junction_ids=tuple(
            map(str, spec["scope"]["guard_junction_ids"])
        ),
        guard_candidate_junction_ids=tuple(
            map(str, spec["scope"]["guard_junction_ids"])
        ),
        endpoint_tolerance_m=float(
            spec["audit"]["endpoint_tolerance_m"]
        ),
        normalized_lane_rank_tolerance=float(
            spec["audit"]["normalized_lane_rank_tolerance"]
        ),
        prefix=slice_id,
    )
    exact_diff = _read_json(Path(exact["files"]["exact_diff"]))
    safety = _read_json(Path(exact["files"]["candidate_safety"]))
    connection = _read_json(
        Path(exact["files"]["candidate_connection_audit"])
    )
    target_connection = _target_connection_summary(
        connection,
        target_junction_id=str(spec["candidate"]["target_junction_id"]),
    )
    finding_continuity = _finding_continuity(exact_diff, slice_id=slice_id)
    finding_continuity_file = destination / "finding-continuity.json"
    write_json_atomic(
        finding_continuity_file,
        finding_continuity,
        sort_keys=True,
    )

    sumo_load = run_sumo_load_audit(
        net_file=candidate_net,
        output_dir=destination / "sumo-load",
        sumo_binary=sumo,
        timeout_seconds=timeout_seconds,
    )
    all_turns = run_all_turn_movement_smoke(
        net_file=candidate_net,
        target_junction_id=str(spec["candidate"]["target_junction_id"]),
        output_dir=destination / "all-turn-smoke",
        sumo_binary=sumo,
        expected_movement_count=int(
            spec["candidate"]["expected_direct_movement_count"]
        ),
        expected_incoming_approach_count=int(
            spec["candidate"].get("expected_incoming_approach_count", 4)
        ),
        expected_outgoing_approach_count=int(
            spec["candidate"].get("expected_outgoing_approach_count", 4)
        ),
        expected_turn_counts={
            str(key): int(value)
            for key, value in spec["candidate"].get(
                "expected_turn_counts", {"r": 4, "s": 4, "l": 4}
            ).items()
        },
        expected_controller_ids=expected_controller_ids,
        departure_interval_s=int(
            spec["runtime"]["departure_interval_s"]
        ),
        end_time_s=int(spec["runtime"]["end_time_s"]),
        timeout_seconds=timeout_seconds,
    )

    rollback = {
        "schema": _slice_schema(slice_id, "rollback"),
        "candidate_sha256": file_sha256(candidate_net),
        "source_sha256": file_sha256(source_net),
        "inverse_operation": (
            "omit all candidate PlainXML patches and rerun source_command"
        ),
        "source_command": source_command,
        "candidate_operation_count": 1 + int(tls_patch is not None),
        "candidate_operation": {
            "type": "join_physical_tls_cell",
            "node_ids": spec["scope"]["target_source_junction_ids"],
        },
        "candidate_operations": [
            {
                "type": "join_physical_tls_cell",
                "node_ids": spec["scope"]["target_source_junction_ids"],
            },
            *(
                [
                    {
                        "type": "replace_static_tls_program",
                        "controller_ids": spec["candidate"].get(
                            "expected_controller_ids", ()
                        ),
                    }
                ]
                if tls_patch is not None
                else []
            ),
        ],
    }
    rollback_file = destination / "rollback.json"
    write_json_atomic(rollback_file, rollback, sort_keys=True)
    overlay_file = destination / "review.add.xml"
    _write_review_overlay(
        overlay_file,
        candidate_net=candidate_net,
        target_junction_id=str(spec["candidate"]["target_junction_id"]),
        guard_junction_ids=tuple(
            map(str, spec["scope"]["guard_junction_ids"])
        ),
        slice_id=slice_id,
        review_case_id=str(spec.get("review_case_id", spec["spec_id"])),
    )

    gates = {
        "frozen_input_identity": _gate(all(identity_checks.values())),
        "source_netconvert": build_report["source"]["status"],
        "candidate_netconvert": build_report["candidate"]["status"],
        "semantic_reproduction": _gate(
            bool(semantic_reproduction["source_matches_frozen"])
            and bool(semantic_reproduction["candidate_matches_frozen"])
        ),
        "tls_ownership_rebuild": str(tls_ownership["status"]),
        "target_connection_mode": target_connection["status"],
        "independent_safety": str(safety["status"]),
        "outside_scope_zero_delta": _gate(
            not exact_diff["outside_scope_delta_ids"]
            and not exact_diff["outside_scope_added_finding_ids"]
        ),
        "finding_continuity": str(finding_continuity["status"]),
        "sumo_load": str(sumo_load["status"]),
        "all_turn_routeability": str(all_turns["status"]),
    }
    machine_ready = all(status == "pass" for status in gates.values())
    summary = {
        "schema": _slice_schema(slice_id, "workflow"),
        "slice_id": slice_id,
        "topology_label": str(spec.get("topology_label", "four-way")),
        "status": "review_ready" if machine_ready else "blocked",
        "automatic_promotion_gate": "blocked",
        "human_review_status": "pending",
        "claim_boundary": str(
            spec.get(
                "claim_boundary",
                "one frozen, vehicle-only, standard four-way OSM intersection; "
                "no pedestrian, bicycle, rail, ramp, shared-controller, "
                "or city-scale claim",
            )
        ),
        "prompt": prompt,
        "spec_id": spec["spec_id"],
        "reproduction_command": str(
            spec.get(
                "reproduction_command",
                ".\\.venv\\Scripts\\python.exe "
                "plugins\\torii-sumo\\scripts\\run_xs1_four_way.py",
            )
        ),
        "bbox": spec["bbox"],
        "source_net_file": str(source_net),
        "source_sha256": file_sha256(source_net),
        "candidate_net_file": str(candidate_net),
        "candidate_sha256": file_sha256(candidate_net),
        "semantic_reproduction": semantic_reproduction,
        "gates": gates,
        "tls_ownership": tls_ownership,
        "target_connection": target_connection,
        "independent_safety": {
            "status": safety["status"],
            "finding_count": len(safety["findings"]),
            "protected_conflict_count": safety["protected_conflict_count"],
            "permissive_without_yield_count": safety[
                "permissive_without_yield_count"
            ],
            "potential_signal_conflict_count": safety[
                "potential_signal_conflict_count"
            ],
        },
        "exact_diff": {
            "status": exact_diff["status"],
            "counts_by_scope": exact_diff["counts_by_scope"],
            "outside_scope_delta_count": len(
                exact_diff["outside_scope_delta_ids"]
            ),
            "outside_scope_added_finding_count": len(
                exact_diff["outside_scope_added_finding_ids"]
            ),
        },
        "finding_continuity": finding_continuity,
        "sumo_load": {"status": sumo_load["status"]},
        "all_turn_routeability": {
            "status": all_turns["status"],
            "movement_count": all_turns["movement_count"],
            "expected_movement_count": all_turns[
                "expected_movement_count"
            ],
            "turn_counts": all_turns["turn_counts"],
            "arrived_vehicle_count": len(all_turns["arrived_vehicle_ids"]),
            "inspection": all_turns["inspection"],
        },
        "review_overlay_file": str(overlay_file),
        "rollback_file": str(rollback_file),
        "visual_review": None,
    }
    summary_file = destination / "summary.json"
    write_json_atomic(summary_file, summary, sort_keys=True)
    review_html_file = destination / "review.html"
    _write_review_html(review_html_file, summary)
    _write_public_bundle_metadata(
        destination,
        summary=summary,
        inputs=(
            _public_input("prompt", "../prompt.txt", prompt_file),
            _public_input("structured_spec", "../spec.json", spec_file),
            _public_input(
                "source_registry",
                "../source-registry.json",
                registry_file,
            ),
            _public_input(
                "frozen_osm",
                f"../input/{frozen_osm.name}",
                frozen_osm,
            ),
            _public_input(
                "join_patch",
                f"../input/{join_patch.name}",
                join_patch,
            ),
            *(
                (
                    _public_input(
                        "tls_patch",
                        f"../input/{tls_patch.name}",
                        tls_patch,
                    ),
                )
                if tls_patch is not None
                else ()
            ),
            _public_input(
                "toolchain_lock",
                "../../../benchmarks/corridor_human_modeling_v1/toolchain.lock.json",
                toolchain_lock_file,
            ),
        ),
        toolchain_lock_file=toolchain_lock_file,
    )
    manifest_file = destination / "manifest.json"
    _write_manifest(
        manifest_file,
        destination=destination,
        summary=summary,
        spec_file=spec_file,
        prompt_file=prompt_file,
        registry_file=registry_file,
        frozen_osm=frozen_osm,
        join_patch=join_patch,
        tls_patch=tls_patch,
        toolchain_lock_file=toolchain_lock_file,
        netconvert=netconvert,
        sumo=sumo,
    )
    return {
        **summary,
        "summary_file": str(summary_file),
        "review_html_file": str(review_html_file),
        "manifest_file": str(manifest_file),
    }


def run_xs1_workflow(
    *,
    example_dir: Path,
    output_dir: Path,
    toolchain_lock_file: Path,
    binaries: Mapping[str, str | None] | None = None,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Backward-compatible XS-1 entry point."""

    return run_isolated_junction_workflow(
        example_dir=example_dir,
        output_dir=output_dir,
        toolchain_lock_file=toolchain_lock_file,
        binaries=binaries,
        timeout_seconds=timeout_seconds,
    )


def finalize_isolated_junction_visual_review(
    *,
    output_dir: Path,
    reviewer: str,
    decision: str,
    observations: tuple[str, ...],
    screenshot_files: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Bind a NetEdit visual decision to the already-built candidate bytes."""

    destination = output_dir.resolve(strict=True)
    summary_file = destination / "summary.json"
    summary = _read_json(summary_file)
    candidate = Path(summary["candidate_net_file"])
    if decision not in {"pass", "fail"}:
        raise ValueError("Visual decision must be 'pass' or 'fail'.")
    screenshots = []
    for source in screenshot_files:
        target = destination / "visual" / source.name
        copy_file_atomic(source, target)
        screenshots.append(
            {"path": str(target), "sha256": file_sha256(target)}
        )
    review = {
        "schema": _slice_schema(
            str(summary.get("slice_id", "xs1")), "visual-review"
        ),
        "reviewer": reviewer,
        "reviewer_kind": "agent_netedit_visual",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "candidate_file": str(candidate),
        "candidate_sha256": file_sha256(candidate),
        "observations": observations,
        "screenshots": screenshots,
        "human_validation": False,
        "automatic_promotion_gate": "blocked",
    }
    review_file = destination / "visual-review.json"
    write_json_atomic(review_file, review, sort_keys=True)
    summary["visual_review"] = review
    summary["human_review_status"] = "pending"
    summary["status"] = (
        "review_ready_visual_checked"
        if decision == "pass" and summary["status"] != "blocked"
        else "blocked"
    )
    summary["gates"]["netedit_visual_review"] = decision
    write_json_atomic(summary_file, summary, sort_keys=True)
    _write_review_html(destination / "review.html", summary)
    _write_public_bundle_metadata(destination, summary=summary)
    manifest_file = destination / "manifest.json"
    manifest = _read_json(manifest_file)
    manifest["status"] = summary["status"]
    manifest["automatic_promotion_gate"] = "blocked"
    manifest["artifacts"] = _artifact_inventory(destination)
    write_json_atomic(manifest_file, manifest, sort_keys=True)
    return {
        **summary,
        "visual_review_file": str(review_file),
        "manifest_file": str(manifest_file),
    }


def finalize_xs1_visual_review(
    *,
    output_dir: Path,
    reviewer: str,
    decision: str,
    observations: tuple[str, ...],
    screenshot_files: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Backward-compatible XS-1 visual-review entry point."""

    return finalize_isolated_junction_visual_review(
        output_dir=output_dir,
        reviewer=reviewer,
        decision=decision,
        observations=observations,
        screenshot_files=screenshot_files,
    )


def _validate_spec(*, prompt: str, spec: Mapping[str, Any]) -> None:
    if spec.get("schema") not in {
        "torii.xs1-spec/v1",
        "torii.isolated-junction-spec/v1",
    }:
        raise ValueError("Unsupported isolated-junction spec schema.")
    if prompt != str(spec.get("prompt", "")):
        raise ValueError("The frozen sentence prompt does not match the spec.")
    if spec.get("traffic_side") not in {"right", "left"}:
        raise ValueError("The isolated-junction spec requires a traffic side.")
    exclusions = set(map(str, spec.get("excluded_features", ())))
    required = {
        "pedestrian",
        "bicycle",
        "rail",
        "ramp",
        "shared_tls_controller",
        "complex_channelization",
    }
    if not required <= exclusions:
        raise ValueError("The isolated-junction exclusions are incomplete.")


def _build_result(command_result: Mapping[str, Any], path: Path) -> dict[str, Any]:
    passed = (
        command_result.get("status") == "pass"
        and command_result.get("returncode") == 0
        and path.is_file()
    )
    return {
        "status": _gate(passed),
        "command_result": dict(command_result),
        "net_file": str(path),
        "net_sha256": file_sha256(path) if path.is_file() else None,
        "normalized_net_sha256": (
            normalized_net_sha256(path) if path.is_file() else None
        ),
    }


def _audit_tls_ownership_rebuild(
    *,
    source_net: Path,
    candidate_net: Path,
    target_source_junction_ids: tuple[str, ...],
    target_candidate_junction_id: str,
    expected_controller_ids: tuple[str, ...],
    expected_controlled_connection_count: int,
    slice_id: str,
) -> dict[str, Any]:
    source = _tls_scope_inventory(
        source_net,
        scope_junction_ids=target_source_junction_ids,
    )
    candidate = _tls_scope_inventory(
        candidate_net,
        scope_junction_ids=(target_candidate_junction_id,),
    )
    expected = set(expected_controller_ids)
    source_scope_ids = set(target_source_junction_ids)
    candidate_global_controller_ids = set(candidate["all_controller_ids"])
    candidate_global_junction_ids = set(candidate["all_junction_ids"])
    old_source_controller_ids = set(source["scope_controller_ids"]) - expected
    residual_old_controller_ids = sorted(
        old_source_controller_ids & candidate_global_controller_ids
    )
    residual_source_junction_ids = sorted(
        (source_scope_ids - {target_candidate_junction_id})
        & candidate_global_junction_ids
    )

    findings: list[dict[str, Any]] = []
    if candidate["scope_tls_junction_ids"] != [target_candidate_junction_id]:
        findings.append(
            {
                "category": "candidate_physical_tls_junction_not_unique",
                "expected": [target_candidate_junction_id],
                "observed": candidate["scope_tls_junction_ids"],
            }
        )
    if set(candidate["scope_controller_ids"]) != expected:
        findings.append(
            {
                "category": "candidate_target_controller_set_mismatch",
                "expected": sorted(expected),
                "observed": candidate["scope_controller_ids"],
            }
        )
    if set(candidate["scope_program_controller_ids"]) != expected:
        findings.append(
            {
                "category": "candidate_target_program_set_mismatch",
                "expected": sorted(expected),
                "observed": candidate["scope_program_controller_ids"],
            }
        )
    if (
        candidate["scope_controlled_connection_count"]
        != expected_controlled_connection_count
    ):
        findings.append(
            {
                "category": "candidate_target_controlled_connection_count_mismatch",
                "expected": expected_controlled_connection_count,
                "observed": candidate["scope_controlled_connection_count"],
            }
        )
    if residual_old_controller_ids:
        findings.append(
            {
                "category": "old_source_controller_identity_survived",
                "controller_ids": residual_old_controller_ids,
            }
        )
    if residual_source_junction_ids:
        findings.append(
            {
                "category": "old_source_tls_cell_junction_survived",
                "junction_ids": residual_source_junction_ids,
            }
        )

    return {
        "schema": _slice_schema(slice_id, "tls-ownership"),
        "status": "pass" if not findings else "fail",
        "source_net_file": str(source_net),
        "candidate_net_file": str(candidate_net),
        "target_candidate_junction_id": target_candidate_junction_id,
        "expected_controller_ids": sorted(expected),
        "expected_controlled_connection_count": (
            expected_controlled_connection_count
        ),
        "source": {
            "target_scope_junction_count": len(target_source_junction_ids),
            "target_tls_junction_count": len(
                source["scope_tls_junction_ids"]
            ),
            "target_tls_junction_ids": source["scope_tls_junction_ids"],
            "target_controller_count": len(source["scope_controller_ids"]),
            "target_controller_ids": source["scope_controller_ids"],
            "target_controlled_connection_count": source[
                "scope_controlled_connection_count"
            ],
            "target_signal_group_count": source["scope_signal_group_count"],
        },
        "candidate": {
            "target_tls_junction_count": len(
                candidate["scope_tls_junction_ids"]
            ),
            "target_tls_junction_ids": candidate["scope_tls_junction_ids"],
            "target_controller_count": len(candidate["scope_controller_ids"]),
            "target_controller_ids": candidate["scope_controller_ids"],
            "target_program_controller_ids": candidate[
                "scope_program_controller_ids"
            ],
            "target_controlled_connection_count": candidate[
                "scope_controlled_connection_count"
            ],
            "target_signal_group_count": candidate[
                "scope_signal_group_count"
            ],
        },
        "removed_source_tls_junction_ids": sorted(
            set(source["scope_tls_junction_ids"])
            - candidate_global_junction_ids
        ),
        "removed_source_controller_ids": sorted(
            old_source_controller_ids - candidate_global_controller_ids
        ),
        "residual_source_junction_ids": residual_source_junction_ids,
        "residual_old_controller_ids": residual_old_controller_ids,
        "findings": findings,
        "interpretation": (
            "traffic-light junction/controller counts describe physical TLS "
            "ownership; signal-group/linkIndex counts describe controlled "
            "lane movements and must not be interpreted as separate physical "
            "intersections"
        ),
        "review_instruction": (
            f"Open {candidate_net.name} for the cleaned network. "
            f"{source_net.name} is the immutable fragmented OSM baseline."
        ),
    }


def _tls_scope_inventory(
    net_file: Path,
    *,
    scope_junction_ids: tuple[str, ...],
) -> dict[str, Any]:
    root = ET.parse(net_file).getroot()
    scope = set(scope_junction_ids)
    junctions = {
        element.attrib.get("id", ""): element
        for element in root.findall("junction")
        if element.attrib.get("id")
    }
    external_edge_targets = {
        element.attrib.get("id", ""): element.attrib.get("to", "")
        for element in root.findall("edge")
        if element.attrib.get("id")
        and element.attrib.get("function") != "internal"
    }
    all_program_controller_ids = {
        element.attrib.get("id", "")
        for element in root.findall("tlLogic")
        if element.attrib.get("id")
    }
    all_controlled_controller_ids: set[str] = set()
    scoped_connections: list[ET.Element] = []
    for connection in root.findall("connection"):
        controller_id = connection.attrib.get("tl", "")
        if not controller_id:
            continue
        all_controlled_controller_ids.add(controller_id)
        owner_junction_id = external_edge_targets.get(
            connection.attrib.get("from", ""), ""
        )
        if owner_junction_id in scope:
            scoped_connections.append(connection)

    scope_controller_ids = sorted(
        {
            connection.attrib.get("tl", "")
            for connection in scoped_connections
            if connection.attrib.get("tl")
        }
    )
    scope_program_controller_ids = sorted(
        set(scope_controller_ids) & all_program_controller_ids
    )
    signal_groups = {
        (
            connection.attrib.get("tl", ""),
            connection.attrib.get("linkIndex", ""),
        )
        for connection in scoped_connections
        if connection.attrib.get("linkIndex") not in (None, "")
    }
    return {
        "all_junction_ids": sorted(junctions),
        "all_controller_ids": sorted(
            all_program_controller_ids | all_controlled_controller_ids
        ),
        "scope_tls_junction_ids": sorted(
            junction_id
            for junction_id, junction in junctions.items()
            if junction_id in scope
            and junction.attrib.get("type", "").startswith("traffic_light")
        ),
        "scope_controller_ids": scope_controller_ids,
        "scope_program_controller_ids": scope_program_controller_ids,
        "scope_controlled_connection_count": len(scoped_connections),
        "scope_signal_group_count": len(signal_groups),
    }


def _target_connection_summary(
    report: Mapping[str, Any],
    *,
    target_junction_id: str,
) -> dict[str, Any]:
    record = next(
        (
            item
            for item in report.get("junctions", ())
            if item.get("junction_id") == target_junction_id
        ),
        None,
    )
    if record is None:
        return {"status": "fail", "reason": "target junction audit missing"}
    audit = record["connection_mode_audit"]
    return {
        "status": str(audit["status"]),
        "direct_movement_count": audit["direct_movement_count"],
        "verified_internal_path_count": audit[
            "verified_internal_path_count"
        ],
        "structural_failure_count": len(audit["structural_failures"]),
        "review_finding_count": len(audit["review_findings"]),
        "request_foes_status": audit["request_foe_audit"]["status"],
        "tls_binding_status": record["tls_link_binding_audit"]["status"],
        "incoming_motorized_lane_count": audit[
            "connection_completeness_audit"
        ]["incoming_motorized_lane_count"],
    }


def _finding_continuity(
    exact_diff: Mapping[str, Any], *, slice_id: str
) -> dict[str, Any]:
    finding_delta = exact_diff.get("finding_delta", {})
    added = list(finding_delta.get("added", ()))
    resolved = list(finding_delta.get("resolved", ()))
    available: dict[tuple[str, tuple[str, ...]], list[Mapping[str, Any]]] = {}
    for finding in resolved:
        key = _finding_continuity_key(finding)
        available.setdefault(key, []).append(finding)
    pairs = []
    unpaired = []
    for finding in added:
        key = _finding_continuity_key(finding)
        matches = available.get(key, [])
        if matches:
            previous = matches.pop(0)
            pairs.append(
                {
                    "category": key[0],
                    "normalized_tokens": key[1],
                    "source_finding_id": previous["finding_id"],
                    "candidate_finding_id": finding["finding_id"],
                    "status": "carried_forward_guard_finding",
                }
            )
        else:
            unpaired.append(finding["finding_id"])
    return {
        "schema": _slice_schema(slice_id, "finding-continuity"),
        "status": "pass" if not unpaired else "review",
        "pair_count": len(pairs),
        "pairs": pairs,
        "unpaired_added_finding_ids": unpaired,
        "policy": (
            "Only exact category plus normalized witness tokens may establish "
            "continuity; this does not waive or resolve the finding."
        ),
    }


def _finding_continuity_key(
    finding: Mapping[str, Any],
) -> tuple[str, tuple[str, ...]]:
    witness = finding.get("witness", {})
    return (
        str(finding.get("category", "")),
        tuple(map(str, witness.get("normalized_tokens", ()))),
    )


def _write_review_overlay(
    path: Path,
    *,
    candidate_net: Path,
    target_junction_id: str,
    guard_junction_ids: tuple[str, ...],
    slice_id: str,
    review_case_id: str,
) -> None:
    net_root = ET.parse(candidate_net).getroot()
    junctions = {
        item.attrib.get("id", ""): item
        for item in net_root.findall("junction")
    }
    root = ET.Element("additional")
    target = junctions[target_junction_id]
    polygon = ET.SubElement(
        root,
        "poly",
        id=f"{slice_id}_target_cell",
        color="0,210,120,120",
        fill="true",
        layer="100",
        shape=target.attrib.get("shape", ""),
    )
    ET.SubElement(
        polygon,
        "param",
        key="review_case_id",
        value=review_case_id,
    )
    ET.SubElement(polygon, "param", key="role", value="target")
    for index, junction_id in enumerate(guard_junction_ids):
        junction = junctions.get(junction_id)
        if junction is None:
            continue
        poi = ET.SubElement(
            root,
            "poi",
            id=f"{slice_id}_guard_{index + 1}",
            color="255,180,0,255",
            layer="101",
            x=junction.attrib.get("x", "0"),
            y=junction.attrib.get("y", "0"),
        )
        ET.SubElement(poi, "param", key="role", value="guard")
        ET.SubElement(poi, "param", key="junction_id", value=junction_id)
    _write_xml(path, root)


def _write_review_html(path: Path, summary: Mapping[str, Any]) -> None:
    gates = "".join(
        f"<tr><td>{html.escape(name.replace('_', ' '))}</td>"
        f"<td class='{html.escape(str(status))}'>{html.escape(str(status))}</td></tr>"
        for name, status in summary["gates"].items()
    )
    continuity = summary["finding_continuity"]
    visual = summary.get("visual_review")
    visual_text = (
        f"{visual['decision']} — {', '.join(visual['observations'])}"
        if visual
        else "pending NetEdit visual check"
    )
    slice_label = str(summary.get("slice_id", "xs1")).upper()
    topology_label = str(summary.get("topology_label", "four-way"))
    tls = summary["tls_ownership"]
    source_name = Path(str(summary["source_net_file"])).name
    candidate_name = Path(str(summary["candidate_net_file"])).name
    expected_movements = int(
        summary["all_turn_routeability"]["expected_movement_count"]
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Torii {html.escape(slice_label)} review</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:980px;margin:32px auto;padding:0 20px;color:#17202a}}
h1{{margin-bottom:4px}} .sub{{color:#52606d}} .cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.card{{border:1px solid #d9e2ec;border-radius:10px;padding:14px;background:#f8fafc}} table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #e4e7eb;padding:8px;text-align:left}} .pass{{color:#087f5b;font-weight:700}}
.review,.pending{{color:#b35c00;font-weight:700}} .blocked,.fail{{color:#c92a2a;font-weight:700}}
code{{overflow-wrap:anywhere}} .role-note{{border-left:5px solid #087f5b;background:#e6fcf5;padding:12px 14px;margin:18px 0}}
@media(max-width:850px){{.cards{{grid-template-columns:repeat(2,1fr)}}}} @media(max-width:700px){{.cards{{grid-template-columns:1fr}}}}
</style></head><body>
<h1>{html.escape(slice_label)} — one real {html.escape(topology_label)} TLS intersection</h1>
<p class="sub">{html.escape(str(summary['prompt']))}</p>
<div class="role-note"><b>Open the cleaned candidate:</b> <code>{html.escape(candidate_name)}</code>.<br>
<b>Do not visually grade the immutable source:</b> <code>{html.escape(source_name)}</code>; it intentionally preserves the fragmented OSM TLS baseline.</div>
<div class="cards"><div class="card"><b>Machine state</b><br>{html.escape(str(summary['status']))}</div>
<div class="card"><b>Movements</b><br>{summary['target_connection']['direct_movement_count']} / {expected_movements} traced</div>
<div class="card"><b>TLS ownership</b><br>{tls['source']['target_tls_junction_count']} source nodes → {tls['candidate']['target_tls_junction_count']} candidate node</div>
<div class="card"><b>Runtime</b><br>{summary['all_turn_routeability']['arrived_vehicle_count']} / {expected_movements} arrived</div></div>
<h2>Hard evidence</h2><table><thead><tr><th>Gate</th><th>Status</th></tr></thead><tbody>{gates}</tbody></table>
<h2>TLS rebuild proof</h2><p>The target changed from <b>{tls['source']['target_tls_junction_count']}</b> traffic-light junctions and <b>{tls['source']['target_controller_count']}</b> controllers to <b>{tls['candidate']['target_tls_junction_count']}</b> physical TLS junction and <b>{tls['candidate']['target_controller_count']}</b> controller. Residual old junction IDs: <b>{len(tls['residual_source_junction_ids'])}</b>; residual old controller IDs: <b>{len(tls['residual_old_controller_ids'])}</b>.</p>
<p>The candidate has {tls['candidate']['target_controlled_connection_count']} controlled lane movements and {tls['candidate']['target_signal_group_count']} linkIndex groups. Those are movement controls inside one controller, not separate physical intersections.</p>
<h2>Scope</h2><p>Outside-scope deltas: <b>{summary['exact_diff']['outside_scope_delta_count']}</b>. Outside-scope new findings: <b>{summary['exact_diff']['outside_scope_added_finding_count']}</b>.</p>
<p>Independent safety: <b>{html.escape(str(summary['independent_safety']['status']))}</b>; protected conflicts {summary['independent_safety']['protected_conflict_count']}, missing yield relations {summary['independent_safety']['permissive_without_yield_count']}, potential signal conflicts {summary['independent_safety']['potential_signal_conflict_count']}.</p>
<h2>Guard finding continuity</h2><p>{continuity['pair_count']} findings are carried forward by exact category + witness tokens; none are silently resolved. Unpaired additions: {len(continuity['unpaired_added_finding_ids'])}.</p>
<h2>Visual review</h2><p>{html.escape(visual_text)}</p>
<h2>Claim boundary</h2><p>{html.escape(str(summary['claim_boundary']))}</p>
<p>Automatic promotion remains <b>blocked</b>. Candidate: <code>{html.escape(str(summary['candidate_sha256']))}</code></p>
</body></html>"""
    write_text_atomic(path, document)


def _write_manifest(
    path: Path,
    *,
    destination: Path,
    summary: Mapping[str, Any],
    spec_file: Path,
    prompt_file: Path,
    registry_file: Path,
    frozen_osm: Path,
    join_patch: Path,
    tls_patch: Path | None,
    toolchain_lock_file: Path,
    netconvert: str,
    sumo: str,
) -> None:
    manifest = {
        "schema": _slice_schema(
            str(summary.get("slice_id", "xs1")), "artifact-manifest"
        ),
        "status": summary["status"],
        "automatic_promotion_gate": "blocked",
        "source_network_mutation": False,
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "netconvert": _tool_identity(netconvert),
            "sumo": _tool_identity(sumo),
        },
        "inputs": [
            _artifact("prompt", prompt_file),
            _artifact("structured_spec", spec_file),
            _artifact("source_registry", registry_file),
            _artifact("frozen_osm", frozen_osm),
            _artifact("join_patch", join_patch),
            *(
                [_artifact("tls_patch", tls_patch)]
                if tls_patch is not None
                else []
            ),
            _artifact("toolchain_lock", toolchain_lock_file),
        ],
        "gates": summary["gates"],
        "artifacts": _artifact_inventory(destination),
    }
    write_json_atomic(path, manifest, sort_keys=True)


def _write_public_bundle_metadata(
    destination: Path,
    *,
    summary: Mapping[str, Any],
    inputs: tuple[Mapping[str, Any], ...] | None = None,
    toolchain_lock_file: Path | None = None,
) -> None:
    public_summary = {
        "schema": _slice_schema(
            str(summary.get("slice_id", "xs1")), "public-summary"
        ),
        "slice_id": summary.get("slice_id", "xs1"),
        "topology_label": summary.get("topology_label", "four-way"),
        "status": summary["status"],
        "automatic_promotion_gate": "blocked",
        "human_review_status": summary["human_review_status"],
        "claim_boundary": summary["claim_boundary"],
        "prompt": summary["prompt"],
        "spec_id": summary["spec_id"],
        "bbox": summary["bbox"],
        "source": {
            "path": Path(str(summary["source_net_file"])).name,
            "sha256": summary["source_sha256"],
            "normalized_sha256": summary["semantic_reproduction"][
                "source_normalized_net_sha256"
            ],
        },
        "candidate": {
            "path": Path(str(summary["candidate_net_file"])).name,
            "sha256": summary["candidate_sha256"],
            "normalized_sha256": summary["semantic_reproduction"][
                "candidate_normalized_net_sha256"
            ],
        },
        "gates": summary["gates"],
        "tls_ownership": _public_tls_ownership(summary["tls_ownership"]),
        "tls_ownership_file": "tls-ownership.public.json",
        "target_connection": summary["target_connection"],
        "independent_safety": summary["independent_safety"],
        "exact_diff": summary["exact_diff"],
        "finding_continuity": summary["finding_continuity"],
        "sumo_load": summary["sumo_load"],
        "all_turn_routeability": _public_routeability(
            summary["all_turn_routeability"]
        ),
        "review_overlay_file": "review.add.xml",
        "rollback_file": "rollback.public.json",
        "visual_review": _public_visual_review(summary.get("visual_review")),
    }
    write_json_atomic(
        destination / "summary.public.json",
        public_summary,
        sort_keys=True,
    )
    write_json_atomic(
        destination / "tls-ownership.public.json",
        _public_tls_ownership(summary["tls_ownership"]),
        sort_keys=True,
    )

    rollback = _read_json(destination / "rollback.json")
    write_json_atomic(
        destination / "rollback.public.json",
        {
            "schema": _slice_schema(
                str(summary.get("slice_id", "xs1")), "public-rollback"
            ),
            "candidate_sha256": rollback["candidate_sha256"],
            "source_sha256": rollback["source_sha256"],
            "inverse_operation": rollback["inverse_operation"],
            "candidate_operation_count": rollback["candidate_operation_count"],
            "candidate_operation": rollback["candidate_operation"],
            "candidate_operations": rollback["candidate_operations"],
            "reproduction_command": summary["reproduction_command"],
        },
        sort_keys=True,
    )
    visual = _public_visual_review(summary.get("visual_review"))
    visual_file = destination / "visual-review.public.json"
    if visual is not None:
        write_json_atomic(visual_file, visual, sort_keys=True)

    public_manifest_file = destination / "manifest.public.json"
    previous = (
        _read_json(public_manifest_file) if public_manifest_file.is_file() else {}
    )
    toolchain = previous.get("toolchain", {})
    if toolchain_lock_file is not None:
        lock = _read_json(toolchain_lock_file)
        toolchain = {
            "toolchain_id": lock["toolchain_id"],
            "python_version": lock["python_version"],
            "dependencies": lock["dependencies"],
            "tools": lock["tools"],
        }
    public_manifest = {
        "schema": _slice_schema(
            str(summary.get("slice_id", "xs1")), "public-manifest"
        ),
        "status": summary["status"],
        "automatic_promotion_gate": "blocked",
        "human_validation": False,
        "source_network_mutation": False,
        "toolchain": toolchain,
        "inputs": list(inputs or previous.get("inputs", ())),
        "gates": summary["gates"],
        "artifacts": _public_artifact_inventory(destination, summary),
    }
    write_json_atomic(public_manifest_file, public_manifest, sort_keys=True)


def _public_routeability(report: Mapping[str, Any]) -> dict[str, Any]:
    inspection = report["inspection"]
    runtime = inspection["summary"]
    tripinfo = inspection["tripinfo"]
    return {
        "status": report["status"],
        "expected_movement_count": report["expected_movement_count"],
        "movement_count": report["movement_count"],
        "turn_counts": report["turn_counts"],
        "arrived_vehicle_count": report["arrived_vehicle_count"],
        "runtime": {
            "loaded": runtime["loaded"],
            "inserted": runtime["inserted"],
            "arrived": runtime["arrived"],
            "running": runtime["running"],
            "waiting": runtime["waiting"],
            "collisions": runtime["collisions"],
            "teleports": runtime["teleports"],
            "completion_ratio": runtime["completion_ratio"],
            "trip_count": tripinfo["trip_count"],
        },
    }


def _public_tls_ownership(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": report["schema"],
        "status": report["status"],
        "target_candidate_junction_id": report[
            "target_candidate_junction_id"
        ],
        "expected_controller_ids": report["expected_controller_ids"],
        "expected_controlled_connection_count": report[
            "expected_controlled_connection_count"
        ],
        "source": report["source"],
        "candidate": report["candidate"],
        "removed_source_tls_junction_ids": report[
            "removed_source_tls_junction_ids"
        ],
        "removed_source_controller_ids": report[
            "removed_source_controller_ids"
        ],
        "residual_source_junction_ids": report[
            "residual_source_junction_ids"
        ],
        "residual_old_controller_ids": report[
            "residual_old_controller_ids"
        ],
        "findings": report["findings"],
        "interpretation": report["interpretation"],
        "review_instruction": report["review_instruction"],
    }


def _public_visual_review(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        "schema": value["schema"],
        "reviewer": value["reviewer"],
        "reviewer_kind": value["reviewer_kind"],
        "reviewed_at": value["reviewed_at"],
        "decision": value["decision"],
        "candidate_sha256": value["candidate_sha256"],
        "observations": value["observations"],
        "screenshots": [
            {"path": Path(item["path"]).name, "sha256": item["sha256"]}
            for item in value.get("screenshots", ())
        ],
        "human_validation": False,
        "automatic_promotion_gate": "blocked",
    }


def _public_input(role: str, path: str, source: Path) -> dict[str, Any]:
    return {"role": role, "path": path, "sha256": file_sha256(source)}


def _public_artifact_inventory(
    destination: Path, summary: Mapping[str, Any]
) -> list[dict[str, Any]]:
    names = (
        Path(str(summary["source_net_file"])).name,
        Path(str(summary["candidate_net_file"])).name,
        "review.add.xml",
        "review.html",
        "summary.public.json",
        "tls-ownership.public.json",
        "rollback.public.json",
        "visual-review.public.json",
    )
    return [
        {
            "path": name,
            "sha256": file_sha256(destination / name),
        }
        for name in names
        if (destination / name).is_file()
    ]


def _tool_identity(executable: str) -> dict[str, Any]:
    path = Path(executable).resolve()
    result = run_command([str(path), "--version"], timeout_seconds=30).to_dict()
    return {
        "path": str(path),
        "sha256": file_sha256(path),
        "version_output": (result.get("stdout") or result.get("stderr") or "")
        .splitlines()[:3],
        "status": result["status"],
    }


def _artifact_inventory(destination: Path) -> list[dict[str, Any]]:
    return [
        _artifact("generated", path)
        for path in sorted(destination.rglob("*"))
        if path.is_file()
        and path.name != "manifest.json"
        and ".tmp" not in path.name
    ]


def _artifact(kind: str, path: Path) -> dict[str, Any]:
    return {"kind": kind, "path": str(path), "sha256": file_sha256(path)}


def _slice_schema(slice_id: str, artifact: str) -> str:
    namespace = "torii.xs1" if slice_id == "xs1" else "torii.isolated-junction"
    return f"{namespace}-{artifact}/v1"


def _write_blocked_result(
    destination: Path,
    *,
    slice_id: str = "xs1",
    reason: str,
    details: Mapping[str, Any],
) -> dict[str, Any]:
    report = {
        "schema": _slice_schema(slice_id, "workflow"),
        "slice_id": slice_id,
        "status": "blocked",
        "automatic_promotion_gate": "blocked",
        "reason": reason,
        "details": dict(details),
    }
    report_file = destination / "summary.json"
    write_json_atomic(report_file, report, sort_keys=True)
    write_json_atomic(
        destination / "manifest.json",
        {
            "schema": _slice_schema(slice_id, "artifact-manifest"),
            "status": "blocked",
            "automatic_promotion_gate": "blocked",
            "artifacts": [_artifact("blocked_report", report_file)],
        },
        sort_keys=True,
    )
    return {**report, "summary_file": str(report_file)}


def _gate(value: bool) -> str:
    return "pass" if value else "fail"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_xml(path: Path, root: ET.Element) -> None:
    ET.indent(root, space="  ")
    payload = ET.tostring(root, encoding="unicode")
    write_text_atomic(
        path,
        f"<?xml version='1.0' encoding='utf-8'?>\n{payload}\n",
    )

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping
import xml.etree.ElementTree as ET

from .command_runner import run_command
from .candidate_contracts import file_sha256
from .artifact_io import write_json_atomic
from .sumo_commands import discover_binaries
from ..evidence.output_inspection import inspect_run_outputs


CommandRunner = Callable[..., Any]


def inspect_routeability_outputs(
    *,
    summary_path: Path,
    tripinfo_path: Path,
    expected_vehicle_count: int | None = None,
) -> dict[str, Any]:
    inspection = inspect_run_outputs(
        "routeability",
        summary_path=summary_path,
        tripinfo_path=tripinfo_path,
    ).model_dump(mode="json")
    summary = inspection.get("summary") or {}
    tripinfo = inspection.get("tripinfo") or {}
    warnings = list(inspection.get("warnings", []))

    loaded = _optional_int(summary.get("loaded"))
    inserted = _optional_int(summary.get("inserted"))
    arrived = _optional_int(summary.get("arrived"))
    running = _optional_int(summary.get("running")) or 0
    waiting = _optional_int(summary.get("waiting")) or 0
    teleports = _optional_int(summary.get("teleports")) or 0
    collisions = _optional_int(summary.get("collisions")) or 0
    trip_count = _optional_int(tripinfo.get("trip_count")) or 0
    expected = expected_vehicle_count if expected_vehicle_count is not None else loaded

    status = "pass"
    routeability_status = "pass"
    if inspection.get("status") == "fail":
        status = "fail"
        routeability_status = "invalid-output"
    if loaded is None or arrived is None:
        status = "fail"
        routeability_status = "invalid-output"
        warnings.append("summary lacks loaded/arrived completion counts")
    if inserted is None:
        status = "fail"
        routeability_status = "invalid-output"
        warnings.append("summary lacks inserted completion count")
    if expected is not None and arrived is not None and arrived < expected:
        status = "fail"
        routeability_status = "incomplete"
        warnings.append(f"arrived {arrived}/{expected} vehicles at final summary step")
    if loaded is not None and arrived is not None and arrived < loaded:
        status = "fail"
        routeability_status = "incomplete"
        warnings.append(f"arrived {arrived}/{loaded} loaded vehicles at final summary step")
    if running > 0 or waiting > 0:
        status = "fail"
        routeability_status = "incomplete"
    if teleports > 0:
        status = "fail"
        routeability_status = "teleport-failure"
    if collisions > 0:
        status = "fail"
        routeability_status = "collision-failure"
    if arrived is not None and trip_count != arrived:
        status = "fail"
        routeability_status = "output-mismatch"
        warnings.append(f"tripinfo has {trip_count} records but summary arrived count is {arrived}")

    return {
        "status": status,
        "claim_status": "diagnostic-demo" if status == "pass" else "construction-invalid",
        "routeability_status": routeability_status,
        "summary": summary,
        "tripinfo": tripinfo,
        "warnings": list(dict.fromkeys(warnings)),
    }


def run_routeability_audit(
    *,
    net_file: Path,
    output_dir: Path,
    prefix: str = "routeability_audit",
    vehicle_count: int = 100,
    seed: int = 42,
    initial_end: int = 300,
    max_end: int = 2400,
    timeout_seconds: float = 240.0,
    binaries: Mapping[str, str | None] | None = None,
    command_runner: CommandRunner = run_command,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _construction_invalid(f"could not create routeability output directory: {type(exc).__name__}: {exc}")
    report_file = output_dir / f"{prefix}_routeability_audit.json"
    manifest_file = output_dir / f"{prefix}_routeability_audit.manifest.json"

    def finish(report: Mapping[str, Any]) -> dict[str, Any]:
        return _write_routeability_outcome(
            report=report,
            report_file=report_file,
            manifest_file=manifest_file,
            net_file=net_file,
        )

    if vehicle_count <= 0:
        return finish(_construction_invalid("vehicle_count must be positive"))
    if initial_end <= 0 or max_end <= 0:
        return finish(_construction_invalid("initial_end and max_end must be positive"))
    if initial_end > max_end:
        return finish(_construction_invalid("initial_end must be <= max_end"))
    if not net_file.exists():
        return finish(_construction_invalid(f"net file does not exist: {net_file}"))

    selected = dict(binaries or discover_binaries())
    missing = [
        name for name in ("randomTrips", "sumo")
        if not selected.get(name)
    ]
    if missing:
        return finish({
            "status": "blocked",
            "claim_status": "blocked",
            "routeability_status": "blocked",
            "warnings": [f"missing required SUMO tool: {name}" for name in missing],
        })

    trip_file = output_dir / f"{prefix}.trips.xml"
    route_file = output_dir / f"{prefix}.rou.xml"
    cleanup_errors = _remove_stale_outputs(trip_file, route_file)
    if cleanup_errors:
        return finish(
            {
                "status": "fail",
                "claim_status": "construction-invalid",
                "routeability_status": "stale-output-cleanup-failed",
                "net_file": str(net_file.resolve()),
                "trip_file": str(trip_file),
                "route_file": str(route_file),
                "errors": cleanup_errors,
                "warnings": ["route generation was not run because stale outputs could not be removed"],
            }
        )
    random_trips_command = _build_random_trips_command(
        random_trips=str(selected["randomTrips"]),
        net_file=net_file,
        trip_file=trip_file,
        route_file=route_file,
        cwd=output_dir,
        vehicle_count=vehicle_count,
        seed=seed,
    )
    try:
        route_generation = _result_to_dict(
            command_runner(random_trips_command, cwd=output_dir, timeout_seconds=timeout_seconds)
        )
    except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
        route_generation = {
            "status": "fail",
            "returncode": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    route_generation_pass = (
        route_generation.get("status") == "pass"
        and type(route_generation.get("returncode")) is int
        and route_generation.get("returncode") == 0
        and route_file.is_file()
        and trip_file.is_file()
    )
    if not route_generation_pass:
        return finish({
            "status": "fail",
            "claim_status": "construction-invalid",
            "routeability_status": "route-generation-failed",
            "net_file": str(net_file.resolve()),
            "net_sha256": file_sha256(net_file),
            "route_file": str(route_file),
            "trip_file": str(trip_file),
            "route_generation": route_generation,
            "warnings": [
                f"route generation output was not created: {path}"
                for path in (trip_file, route_file)
                if not path.is_file()
            ],
        })

    attempts: list[dict[str, Any]] = []
    final_attempt: dict[str, Any] | None = None
    for end in _horizon_sequence(initial_end, max_end):
        attempt = _run_attempt(
            sumo_binary=str(selected["sumo"]),
            net_file=net_file,
            route_file=route_file,
            output_dir=output_dir,
            prefix=prefix,
            end=end,
            seed=seed,
            vehicle_count=vehicle_count,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
        attempts.append(attempt)
        final_attempt = attempt
        if attempt["inspection"]["status"] == "pass":
            break

    assert final_attempt is not None
    status = "pass" if final_attempt["inspection"]["status"] == "pass" else "fail"
    warnings = []
    for attempt in attempts:
        warnings.extend(attempt["inspection"].get("warnings", []))
    if status != "pass":
        warnings.append(f"routeability audit did not complete by max_end={max_end}")

    report = {
        "status": status,
        "claim_status": "diagnostic-demo" if status == "pass" else "construction-invalid",
        "routeability_status": final_attempt["inspection"]["routeability_status"],
        "net_file": str(net_file.resolve()),
        "net_sha256": file_sha256(net_file),
        "output_dir": str(output_dir),
        "route_file": str(route_file),
        "trip_file": str(trip_file),
        "vehicle_count": vehicle_count,
        "seed": seed,
        "initial_end": initial_end,
        "max_end": max_end,
        "route_generation": route_generation,
        "attempts": attempts,
        "final_attempt": final_attempt,
        "warnings": list(dict.fromkeys(warnings)),
    }
    return finish(report)


def _run_attempt(
    *,
    sumo_binary: str,
    net_file: Path,
    route_file: Path,
    output_dir: Path,
    prefix: str,
    end: int,
    seed: int,
    vehicle_count: int,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    summary_file = output_dir / f"{prefix}_end{end}_summary.xml"
    tripinfo_file = output_dir / f"{prefix}_end{end}_tripinfo.xml"
    config_file = output_dir / f"{prefix}_end{end}.sumocfg"
    cleanup_errors = _remove_stale_outputs(summary_file, tripinfo_file)
    if cleanup_errors:
        return _failed_attempt(
            end=end,
            config_file=config_file,
            summary_file=summary_file,
            tripinfo_file=tripinfo_file,
            status="stale-output-cleanup-failed",
            warnings=cleanup_errors,
        )
    try:
        _write_sumocfg(
            config_file,
            net_file=net_file,
            route_file=route_file,
            summary_file=summary_file,
            tripinfo_file=tripinfo_file,
            end=end,
            seed=seed,
        )
    except OSError as exc:
        return _failed_attempt(
            end=end,
            config_file=config_file,
            summary_file=summary_file,
            tripinfo_file=tripinfo_file,
            status="configuration-write-failed",
            warnings=[f"{type(exc).__name__}: {exc}"],
        )
    command = [
        sumo_binary,
        "-c",
        config_file.name,
        "--quit-on-end",
        "--duration-log.statistics",
        "--collision.check-junctions",
        "true",
    ]
    try:
        command_result = _result_to_dict(
            command_runner(command, cwd=output_dir, timeout_seconds=timeout_seconds)
        )
    except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
        command_result = {
            "status": "fail",
            "returncode": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    inspection = inspect_routeability_outputs(
        summary_path=summary_file,
        tripinfo_path=tripinfo_file,
        expected_vehicle_count=vehicle_count,
    )
    command_pass = (
        command_result.get("status") == "pass"
        and type(command_result.get("returncode")) is int
        and command_result.get("returncode") == 0
    )
    if not command_pass:
        inspection["status"] = "fail"
        inspection["claim_status"] = "construction-invalid"
        inspection["routeability_status"] = "sumo-run-failed"
        inspection["warnings"] = list(inspection.get("warnings", [])) + ["SUMO routeability run failed"]
    return {
        "end": end,
        "sumocfg_file": str(config_file),
        "summary_file": str(summary_file),
        "tripinfo_file": str(tripinfo_file),
        "command": command_result,
        "inspection": inspection,
    }


def _build_random_trips_command(
    *,
    random_trips: str,
    net_file: Path,
    trip_file: Path,
    route_file: Path,
    cwd: Path,
    vehicle_count: int,
    seed: int,
) -> list[str]:
    return [
        sys.executable,
        random_trips,
        "-n",
        str(net_file.resolve()),
        "-o",
        trip_file.name,
        "-r",
        route_file.name,
        "-e",
        str(vehicle_count),
        "--seed",
        str(seed),
        "--validate",
    ]


def _write_sumocfg(
    path: Path,
    *,
    net_file: Path,
    route_file: Path,
    summary_file: Path,
    tripinfo_file: Path,
    end: int,
    seed: int,
) -> None:
    root = ET.Element("configuration")
    input_node = ET.SubElement(root, "input")
    ET.SubElement(input_node, "net-file", value=str(net_file.resolve()))
    ET.SubElement(input_node, "route-files", value=_relpath(route_file, path.parent))
    output_node = ET.SubElement(root, "output")
    ET.SubElement(output_node, "summary-output", value=summary_file.name)
    ET.SubElement(output_node, "tripinfo-output", value=tripinfo_file.name)
    time_node = ET.SubElement(root, "time")
    ET.SubElement(time_node, "begin", value="0")
    ET.SubElement(time_node, "end", value=str(end))
    random_node = ET.SubElement(root, "random_number")
    ET.SubElement(random_node, "seed", value=str(seed))
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _horizon_sequence(initial_end: int, max_end: int) -> list[int]:
    values = [initial_end]
    current = initial_end
    while current < max_end:
        current = min(current * 2, max_end)
        if current != values[-1]:
            values.append(current)
    return values


def _remove_stale_outputs(*paths: Path) -> list[str]:
    errors: list[str] = []
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            errors.append(f"could not remove stale output {path}: {type(exc).__name__}: {exc}")
    return errors


def _failed_attempt(
    *,
    end: int,
    config_file: Path,
    summary_file: Path,
    tripinfo_file: Path,
    status: str,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "end": end,
        "sumocfg_file": str(config_file),
        "summary_file": str(summary_file),
        "tripinfo_file": str(tripinfo_file),
        "command": {"status": "fail", "returncode": None, "error": "; ".join(warnings)},
        "inspection": {
            "status": "fail",
            "claim_status": "construction-invalid",
            "routeability_status": status,
            "summary": {},
            "tripinfo": {},
            "warnings": warnings,
        },
    }


def _write_routeability_outcome(
    *,
    report: Mapping[str, Any],
    report_file: Path,
    manifest_file: Path,
    net_file: Path,
) -> dict[str, Any]:
    persisted = dict(report)
    persisted.setdefault("schema", "torii.routeability_audit.v2")
    persisted.setdefault("net_file", str(net_file.resolve()))
    if net_file.is_file():
        persisted.setdefault("net_sha256", file_sha256(net_file))
    persisted["report_file"] = str(report_file)
    persisted["manifest_file"] = str(manifest_file)
    write_json_atomic(report_file, persisted)

    artifact_candidates: list[tuple[Path, str]] = []
    if net_file.is_file():
        artifact_candidates.append((net_file, "routeability_net"))
    for key, kind in (("trip_file", "random_trips"), ("route_file", "route_file")):
        value = persisted.get(key)
        if value:
            artifact_candidates.append((Path(str(value)), kind))
    for attempt in persisted.get("attempts", []):
        if not isinstance(attempt, Mapping):
            continue
        for key, kind in (
            ("sumocfg_file", "sumo_config"),
            ("summary_file", "sumo_summary"),
            ("tripinfo_file", "sumo_tripinfo"),
        ):
            value = attempt.get(key)
            if value:
                artifact_candidates.append((Path(str(value)), kind))
    artifact_candidates.append((report_file, "routeability_report"))

    artifacts: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for path, kind in artifact_candidates:
        if not path.is_file():
            continue
        resolved = path.resolve()
        if str(resolved) in seen_paths:
            continue
        seen_paths.add(str(resolved))
        artifacts.append(
            {
                "kind": kind,
                "path": str(resolved),
                "size_bytes": resolved.stat().st_size,
                "sha256": file_sha256(resolved),
            }
        )
    manifest = {
        "schema": "torii.routeability_manifest.v2",
        "status": persisted.get("status", "fail"),
        "claim_status": persisted.get("claim_status", "construction-invalid"),
        "routeability_status": persisted.get("routeability_status", "construction-invalid"),
        "net_file": persisted.get("net_file", ""),
        "net_sha256": persisted.get("net_sha256", ""),
        "artifacts": artifacts,
    }
    write_json_atomic(manifest_file, manifest)
    return persisted


def _result_to_dict(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, Mapping):
        return dict(result)
    return {
        "status": "fail",
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "error": f"unexpected command result type: {type(result).__name__}",
    }


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _relpath(target: Path, start: Path) -> str:
    return Path(os.path.relpath(target.resolve(), start=start.resolve())).as_posix()


def _construction_invalid(error: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "claim_status": "construction-invalid",
        "routeability_status": "construction-invalid",
        "error": error,
    }

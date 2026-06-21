from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping
import xml.etree.ElementTree as ET

from .command_runner import run_command
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
    if vehicle_count <= 0:
        return _construction_invalid("vehicle_count must be positive")
    if initial_end <= 0 or max_end <= 0:
        return _construction_invalid("initial_end and max_end must be positive")
    if initial_end > max_end:
        return _construction_invalid("initial_end must be <= max_end")
    if not net_file.exists():
        return _construction_invalid(f"net file does not exist: {net_file}")

    selected = dict(binaries or discover_binaries())
    missing = [
        name for name in ("randomTrips", "sumo")
        if not selected.get(name)
    ]
    if missing:
        return {
            "status": "blocked",
            "claim_status": "blocked",
            "routeability_status": "blocked",
            "warnings": [f"missing required SUMO tool: {name}" for name in missing],
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    trip_file = output_dir / f"{prefix}.trips.xml"
    route_file = output_dir / f"{prefix}.rou.xml"
    random_trips_command = _build_random_trips_command(
        random_trips=str(selected["randomTrips"]),
        net_file=net_file,
        trip_file=trip_file,
        route_file=route_file,
        cwd=output_dir,
        vehicle_count=vehicle_count,
        seed=seed,
    )
    route_generation = _result_to_dict(
        command_runner(random_trips_command, cwd=output_dir, timeout_seconds=timeout_seconds)
    )
    if route_generation.get("status") != "pass" or not route_file.exists():
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "routeability_status": "route-generation-failed",
            "route_generation": route_generation,
            "warnings": [f"route file was not created: {route_file}"] if not route_file.exists() else [],
        }

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
        "net_file": str(net_file),
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
    report_file = output_dir / f"{prefix}_routeability_audit.json"
    report["report_file"] = str(report_file)
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


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
    _write_sumocfg(
        config_file,
        net_file=net_file,
        route_file=route_file,
        summary_file=summary_file,
        tripinfo_file=tripinfo_file,
        end=end,
        seed=seed,
    )
    command = [
        sumo_binary,
        "-c",
        config_file.name,
        "--quit-on-end",
        "--duration-log.statistics",
    ]
    command_result = _result_to_dict(
        command_runner(command, cwd=output_dir, timeout_seconds=timeout_seconds)
    )
    inspection = inspect_routeability_outputs(
        summary_path=summary_file,
        tripinfo_path=tripinfo_file,
        expected_vehicle_count=vehicle_count,
    )
    if command_result.get("status") != "pass":
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
        _relpath(net_file, cwd),
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
    ET.SubElement(input_node, "net-file", value=_relpath(net_file, path.parent))
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

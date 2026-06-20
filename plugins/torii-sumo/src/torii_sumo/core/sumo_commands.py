from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Protocol

from .command_runner import run_command


class CommandRunner(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 60.0,
    ) -> Any: ...


def build_sumo_config_command(config_path: Path, *, sumo_binary: str = "sumo") -> list[str]:
    return [sumo_binary, "-c", str(config_path)]


def run_sumo_config(
    *,
    config_path: Path,
    sumo_binary: str = "sumo",
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    result = run_command(
        build_sumo_config_command(Path(config_path.name), sumo_binary=sumo_binary),
        cwd=config_path.parent,
        timeout_seconds=timeout_seconds,
    )
    payload = result.to_dict()
    payload["claim_status"] = (
        "diagnostic-demo" if result.status == "pass" else "construction-invalid"
    )
    return payload


def discover_binaries() -> dict[str, str | None]:
    sumo_home = os.environ.get("SUMO_HOME")
    random_trips = None
    if sumo_home:
        candidate = Path(sumo_home) / "tools" / "randomTrips.py"
        if candidate.exists():
            random_trips = str(candidate)
    return {
        "netgenerate": shutil.which("netgenerate"),
        "randomTrips": random_trips,
        "duarouter": shutil.which("duarouter"),
        "sumo": shutil.which("sumo"),
    }


def run_minimal_smoke(
    *,
    work_dir: Path,
    binaries: dict[str, str | None] | None = None,
    timeout_seconds: float = 120.0,
    command_runner: CommandRunner = run_command,
) -> dict[str, Any]:
    selected = binaries or discover_binaries()
    warnings: list[str] = []
    for name in ("netgenerate", "randomTrips", "duarouter", "sumo"):
        if not selected.get(name):
            if name == "randomTrips":
                warnings.append("randomTrips.py script not found under SUMO_HOME/tools")
            else:
                warnings.append(f"{name} binary not found")
    if warnings:
        return {
            "status": "blocked",
            "claim_status": "blocked",
            "work_dir": str(work_dir),
            "warnings": warnings,
            "commands": [],
            "artifacts": [],
        }

    work_dir.mkdir(parents=True, exist_ok=True)
    net_path = work_dir / "smoke.net.xml"
    trips_path = work_dir / "smoke.trips.xml"
    route_path = work_dir / "smoke.rou.xml"
    config_path = work_dir / "smoke.sumocfg"
    summary_path = work_dir / "summary.xml"
    tripinfo_path = work_dir / "tripinfo.xml"

    config_path.write_text(
        f"""<configuration>
  <input>
    <net-file value="{net_path.name}"/>
    <route-files value="{route_path.name}"/>
  </input>
  <time>
    <begin value="0"/>
    <end value="60"/>
  </time>
  <output>
    <summary-output value="{summary_path.name}"/>
    <tripinfo-output value="{tripinfo_path.name}"/>
  </output>
</configuration>
""",
        encoding="utf-8",
    )

    commands = [
        [
            selected["netgenerate"],
            "--grid",
            "--grid.number",
            "2",
            "--output-file",
            net_path.name,
        ],
        [
            sys.executable,
            selected["randomTrips"],
            "-n",
            net_path.name,
            "-o",
            trips_path.name,
            "-e",
            "60",
            "--seed",
            "1",
        ],
        [
            selected["duarouter"],
            "-n",
            net_path.name,
            "--route-files",
            trips_path.name,
            "-o",
            route_path.name,
        ],
        [selected["sumo"], "-c", config_path.name],
    ]
    results = [
        command_runner(command, cwd=work_dir, timeout_seconds=timeout_seconds).to_dict()
        for command in commands
    ]
    missing_outputs = [
        path.name for path in (summary_path, tripinfo_path) if not path.exists()
    ]
    warnings = []
    if missing_outputs:
        warnings.append(
            f"minimal smoke missing output artifacts: {', '.join(missing_outputs)}"
        )
    status = (
        "pass"
        if all(result["status"] == "pass" for result in results) and not missing_outputs
        else "fail"
    )
    artifacts = [
        str(path)
        for path in (
            net_path,
            trips_path,
            route_path,
            config_path,
            summary_path,
            tripinfo_path,
        )
        if path.exists()
    ]
    return {
        "status": status,
        "claim_status": "diagnostic-demo" if status == "pass" else "construction-invalid",
        "work_dir": str(work_dir),
        "warnings": warnings,
        "commands": results,
        "artifacts": artifacts,
        "summary_path": str(summary_path) if summary_path.exists() else None,
        "tripinfo_path": str(tripinfo_path) if tripinfo_path.exists() else None,
    }

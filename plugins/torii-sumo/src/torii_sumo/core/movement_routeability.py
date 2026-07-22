from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol
from xml.etree import ElementTree as ET

from torii_sumo.evidence.output_inspection import inspect_run_outputs

from .artifact_io import write_json_atomic, write_text_atomic
from .candidate_contracts import file_sha256
from .command_runner import run_command


class CommandRunner(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 60.0,
    ) -> Any: ...


def run_all_turn_movement_smoke(
    *,
    net_file: Path,
    target_junction_id: str,
    output_dir: Path,
    sumo_binary: str,
    expected_movement_count: int = 12,
    expected_incoming_approach_count: int = 4,
    expected_outgoing_approach_count: int = 4,
    expected_turn_counts: Mapping[str, int] | None = None,
    expected_controller_ids: tuple[str, ...] | None = None,
    departure_interval_s: int = 8,
    end_time_s: int = 600,
    timeout_seconds: float = 120.0,
    command_runner: CommandRunner = run_command,
) -> dict[str, Any]:
    """Run one vehicle through every direct movement of one physical junction."""

    expected_turn_distribution = dict(
        expected_turn_counts or {"r": 4, "s": 4, "l": 4}
    )
    allowed_controller_ids = set(
        expected_controller_ids or (target_junction_id,)
    )

    source = net_file.resolve(strict=True)
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    route_file = destination / "all-turns.rou.xml"
    config_file = destination / "all-turns.sumocfg"
    summary_file = destination / "summary.xml"
    tripinfo_file = destination / "tripinfo.xml"
    vehroute_file = destination / "vehroute.xml"
    report_file = destination / "all-turns.report.json"
    manifest_file = destination / "all-turns.manifest.json"
    source_sha256 = file_sha256(source)

    root = ET.parse(source).getroot()
    external_edges = {
        edge.attrib["id"]: edge
        for edge in root.findall("edge")
        if edge.attrib.get("id")
        and not edge.attrib["id"].startswith(":")
        and edge.attrib.get("function", "")
        not in {"internal", "crossing", "walkingarea"}
    }
    movements = []
    for connection_index, connection in enumerate(root.findall("connection")):
        source_edge = external_edges.get(connection.attrib.get("from", ""))
        target_edge = external_edges.get(connection.attrib.get("to", ""))
        if source_edge is None or target_edge is None:
            continue
        if (
            source_edge.attrib.get("to") != target_junction_id
            or target_edge.attrib.get("from") != target_junction_id
        ):
            continue
        movements.append(
            {
                "connection_index": connection_index,
                "from": connection.attrib.get("from", ""),
                "from_lane": connection.attrib.get("fromLane", ""),
                "to": connection.attrib.get("to", ""),
                "to_lane": connection.attrib.get("toLane", ""),
                "via": connection.attrib.get("via", ""),
                "turn": connection.attrib.get("dir", ""),
                "controller_id": connection.attrib.get("tl", ""),
                "link_index": connection.attrib.get("linkIndex", ""),
            }
        )

    expected_vehicle_ids = tuple(
        f"movement_{index:02d}_{movement['turn'] or 'unknown'}"
        for index, movement in enumerate(movements)
    )
    route_root = ET.Element("routes")
    ET.SubElement(
        route_root,
        "vType",
        id="junction_smoke_passenger",
        vClass="passenger",
        accel="2.6",
        decel="4.5",
        sigma="0",
        length="5",
        maxSpeed="13.9",
    )
    for index, (vehicle_id, movement) in enumerate(
        zip(expected_vehicle_ids, movements, strict=True)
    ):
        vehicle = ET.SubElement(
            route_root,
            "vehicle",
            id=vehicle_id,
            type="junction_smoke_passenger",
            depart=str(index * departure_interval_s),
            departLane=str(movement["from_lane"]),
            arrivalLane=str(movement["to_lane"]),
        )
        ET.SubElement(
            vehicle,
            "route",
            edges=f"{movement['from']} {movement['to']}",
        )
    _write_xml(route_file, route_root)

    config_root = ET.Element("configuration")
    inputs = ET.SubElement(config_root, "input")
    ET.SubElement(inputs, "net-file", value=str(source))
    ET.SubElement(inputs, "route-files", value=route_file.name)
    time = ET.SubElement(config_root, "time")
    ET.SubElement(time, "begin", value="0")
    ET.SubElement(time, "end", value=str(end_time_s))
    output = ET.SubElement(config_root, "output")
    ET.SubElement(output, "summary-output", value=summary_file.name)
    ET.SubElement(output, "tripinfo-output", value=tripinfo_file.name)
    ET.SubElement(output, "vehroute-output", value=vehroute_file.name)
    _write_xml(config_file, config_root)

    cleanup_errors = []
    for stale in (summary_file, tripinfo_file, vehroute_file):
        try:
            stale.unlink(missing_ok=True)
        except OSError as exc:
            cleanup_errors.append(f"{stale.name}:{type(exc).__name__}:{exc}")
    command = [
        sumo_binary,
        "-c",
        config_file.name,
        "--collision.check-junctions",
        "true",
        "--duration-log.statistics",
        "--quit-on-end",
    ]
    if cleanup_errors:
        command_result: Mapping[str, Any] = {
            "status": "fail",
            "returncode": None,
            "error": "stale output cleanup failed",
        }
    else:
        result = command_runner(
            command,
            cwd=destination,
            timeout_seconds=timeout_seconds,
        )
        command_result = (
            result.to_dict() if hasattr(result, "to_dict") else dict(result)
        )

    inspection = inspect_run_outputs(
        "all-turn-movement-smoke",
        summary_path=summary_file,
        tripinfo_path=tripinfo_file,
    ).model_dump(mode="json")
    arrived_ids = _tripinfo_ids(tripinfo_file)
    turn_counts = {
        turn: sum(movement["turn"] == turn for movement in movements)
        for turn in sorted(
            {item["turn"] for item in movements}
            | set(expected_turn_distribution)
        )
    }
    incoming_approach_ids = tuple(sorted({item["from"] for item in movements}))
    outgoing_approach_ids = tuple(sorted({item["to"] for item in movements}))
    checks = {
        "movement_count": len(movements) == expected_movement_count,
        "incoming_approach_count": len(incoming_approach_ids)
        == expected_incoming_approach_count,
        "outgoing_approach_count": len(outgoing_approach_ids)
        == expected_outgoing_approach_count,
        "turn_distribution": turn_counts == expected_turn_distribution,
        "all_movements_tls_bound": all(
            item["controller_id"] in allowed_controller_ids
            and str(item["link_index"]).isdigit()
            for item in movements
        ),
        "sumo_command": command_result.get("status") == "pass"
        and command_result.get("returncode") == 0,
        "all_expected_vehicles_arrived": set(arrived_ids)
        == set(expected_vehicle_ids),
        "runtime_outputs": inspection.get("status") == "pass",
        "source_immutable": file_sha256(source) == source_sha256,
    }
    status = "pass" if all(checks.values()) else "fail"
    report = {
        "schema": "torii.all-turn-movement-smoke/v2",
        "status": status,
        "target_junction_id": target_junction_id,
        "net_file": str(source),
        "net_sha256": source_sha256,
        "expected_movement_count": expected_movement_count,
        "movement_count": len(movements),
        "expected_incoming_approach_count": expected_incoming_approach_count,
        "incoming_approach_ids": incoming_approach_ids,
        "expected_outgoing_approach_count": expected_outgoing_approach_count,
        "outgoing_approach_ids": outgoing_approach_ids,
        "expected_turn_counts": expected_turn_distribution,
        "turn_counts": turn_counts,
        "expected_controller_ids": sorted(allowed_controller_ids),
        "movements": movements,
        "expected_vehicle_ids": expected_vehicle_ids,
        "arrived_vehicle_ids": arrived_ids,
        "checks": checks,
        "command": command,
        "command_result": command_result,
        "inspection": inspection,
        "cleanup_errors": cleanup_errors,
        "route_file": str(route_file),
        "config_file": str(config_file),
        "summary_file": str(summary_file),
        "tripinfo_file": str(tripinfo_file),
    }
    write_json_atomic(report_file, report, sort_keys=True)
    artifacts = []
    for kind, path in (
        ("candidate_net", source),
        ("route_file", route_file),
        ("sumo_config", config_file),
        ("summary", summary_file),
        ("tripinfo", tripinfo_file),
        ("report", report_file),
    ):
        if path.is_file():
            artifacts.append(
                {"kind": kind, "path": str(path), "sha256": file_sha256(path)}
            )
    write_json_atomic(
        manifest_file,
        {
            "schema": "torii.all-turn-movement-smoke-manifest/v1",
            "status": status,
            "source_network_mutation": not checks["source_immutable"],
            "artifacts": artifacts,
        },
        sort_keys=True,
    )
    return {
        **report,
        "report_file": str(report_file),
        "manifest_file": str(manifest_file),
    }


def _tripinfo_ids(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        return ()
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return ()
    return tuple(
        sorted(
            element.attrib["id"]
            for element in root.findall("tripinfo")
            if element.attrib.get("id")
        )
    )


def _write_xml(path: Path, root: ET.Element) -> None:
    ET.indent(root, space="  ")
    payload = ET.tostring(root, encoding="unicode")
    write_text_atomic(
        path,
        f"<?xml version='1.0' encoding='utf-8'?>\n{payload}\n",
    )

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Protocol
from xml.etree import ElementTree as ET

from torii_sumo.evidence.output_inspection import inspect_run_outputs

from .artifact_io import relative_or_absolute_path, write_json_atomic, write_text_atomic
from .candidate_contracts import file_sha256
from .command_runner import run_command


AUTHORITY_SCHEMA = "torii.hamburg-movement-authority/v1"
SMOKE_SCHEMA = "torii.hamburg-2403-movement-smoke/v1"
TURNAROUND_EVIDENCE_KINDS = frozenset(
    {"official_movement_allowlist", "turn_lane_reverse_or_uturn"}
)


class CommandRunner(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 60.0,
    ) -> Any: ...


class HamburgMovementAuthorityError(ValueError):
    pass


def validate_hamburg_movement_authority(
    *,
    authority_file: Path,
    candidate_net_file: Path,
) -> dict[str, Any]:
    """Validate independent, hash-bound routes against explicit SUMO connections."""

    authority_path = Path(authority_file).expanduser().resolve(strict=True)
    candidate = Path(candidate_net_file).expanduser().resolve(strict=True)
    errors: list[str] = []
    try:
        authority = json.loads(authority_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HamburgMovementAuthorityError(
            f"cannot read movement authority: {authority_path}"
        ) from exc
    if not isinstance(authority, Mapping):
        raise HamburgMovementAuthorityError("movement authority must be a JSON object")

    if authority.get("schema") != AUTHORITY_SCHEMA:
        errors.append(f"schema must be {AUTHORITY_SCHEMA}")
    if authority.get("status") != "review_required":
        errors.append("authority status must be review_required")
    if not str(authority.get("authority_id", "")).strip():
        errors.append("authority_id is required")
    if authority.get("generated_from_candidate") is not False:
        errors.append("generated_from_candidate must be false")

    evidence_by_id: dict[str, Mapping[str, Any]] = {}
    source_evidence = authority.get("source_evidence")
    if not isinstance(source_evidence, list) or not source_evidence:
        errors.append("source_evidence must be a non-empty list")
    else:
        for index, evidence in enumerate(source_evidence):
            if not isinstance(evidence, Mapping):
                errors.append(f"source_evidence[{index}] must be an object")
                continue
            evidence_id = str(evidence.get("evidence_id", "")).strip()
            if not evidence_id or evidence_id in evidence_by_id:
                errors.append(f"source_evidence[{index}] has an empty or duplicate evidence_id")
                continue
            evidence_by_id[evidence_id] = evidence
            try:
                evidence_path = Path(str(evidence.get("path", ""))).expanduser()
                if not evidence_path.is_absolute():
                    evidence_path = authority_path.parent / evidence_path
                evidence_path = evidence_path.resolve(strict=True)
            except (OSError, RuntimeError):
                errors.append(f"source evidence path is invalid: {evidence_id}")
                continue
            if evidence_path == candidate:
                errors.append(f"source evidence cannot be the candidate: {evidence_id}")
            if evidence.get("sha256") != file_sha256(evidence_path):
                errors.append(f"source evidence hash mismatch: {evidence_id}")

    try:
        net_root = ET.parse(candidate).getroot()
    except (OSError, ET.ParseError) as exc:
        raise HamburgMovementAuthorityError(f"cannot parse candidate network: {candidate}") from exc
    external_edges = {
        edge.attrib["id"]
        for edge in net_root.findall("edge")
        if edge.attrib.get("id")
        and not edge.attrib["id"].startswith(":")
        and edge.attrib.get("function", "") not in {"internal", "crossing", "walkingarea"}
    }
    connections: dict[tuple[str, str], list[Mapping[str, str]]] = {}
    for connection in net_root.findall("connection"):
        pair = (connection.attrib.get("from", ""), connection.attrib.get("to", ""))
        if pair[0] in external_edges and pair[1] in external_edges:
            connections.setdefault(pair, []).append(connection.attrib)

    validated_movements: list[dict[str, Any]] = []
    movement_keys: set[str] = set()
    movements = authority.get("movements")
    if not isinstance(movements, list) or not movements:
        errors.append("movements must be a non-empty list")
    else:
        for index, movement in enumerate(movements):
            if not isinstance(movement, Mapping):
                errors.append(f"movements[{index}] must be an object")
                continue
            key = str(movement.get("movement_key", "")).strip()
            if not key or key in movement_keys:
                errors.append(f"movements[{index}] has an empty or duplicate movement_key")
                continue
            movement_keys.add(key)
            route_value = movement.get("route_edges")
            route_edges = (
                [str(edge).strip() for edge in route_value]
                if isinstance(route_value, list)
                else []
            )
            if len(route_edges) < 2 or any(not edge for edge in route_edges):
                errors.append(f"{key}: route_edges must contain at least two edge IDs")
                continue
            missing_edges = [edge for edge in route_edges if edge not in external_edges]
            if missing_edges:
                errors.append(f"{key}: route references missing edges: {missing_edges}")
                continue

            movement_evidence = movement.get("evidence_ids")
            evidence_ids = (
                [str(value).strip() for value in movement_evidence]
                if isinstance(movement_evidence, list)
                else []
            )
            if (
                not evidence_ids
                or any(not evidence_id or evidence_id not in evidence_by_id for evidence_id in evidence_ids)
            ):
                errors.append(f"{key}: evidence_ids must reference source_evidence")
                continue

            route_connections: list[list[Mapping[str, str]]] = []
            disconnected = False
            reachable_lanes: set[str] | None = None
            for pair_index, pair in enumerate(zip(route_edges, route_edges[1:])):
                eligible = list(connections.get(pair, ()))
                if pair_index == 0 and "depart_lane" in movement:
                    eligible = [
                        item
                        for item in eligible
                        if item.get("fromLane") == str(movement["depart_lane"])
                    ]
                elif reachable_lanes is not None:
                    eligible = [
                        item
                        for item in eligible
                        if item.get("fromLane") in reachable_lanes
                    ]
                if pair_index == len(route_edges) - 2 and "arrival_lane" in movement:
                    eligible = [
                        item
                        for item in eligible
                        if item.get("toLane") == str(movement["arrival_lane"])
                    ]
                if not eligible:
                    errors.append(f"{key}: no candidate connection for {pair[0]} -> {pair[1]}")
                    disconnected = True
                    break
                route_connections.append(eligible)
                reachable_lanes = {
                    str(item["toLane"])
                    for item in eligible
                    if item.get("toLane") is not None
                }
            if disconnected:
                continue

            includes_turnaround = any(
                connection.get("dir") == "t"
                for eligible in route_connections
                for connection in eligible
            )
            evidence_kinds = {
                str(evidence_by_id[evidence_id].get("kind", "")).strip()
                for evidence_id in evidence_ids
            }
            if includes_turnaround and evidence_kinds.isdisjoint(TURNAROUND_EVIDENCE_KINDS):
                errors.append(f"{key}: candidate dir=t lacks turnaround authority evidence")
                continue
            validated_movements.append(
                {
                    "movement_key": key,
                    "route_edges": route_edges,
                    "evidence_ids": evidence_ids,
                    "depart_lane": movement.get("depart_lane"),
                    "arrival_lane": movement.get("arrival_lane"),
                    "includes_candidate_turnaround": includes_turnaround,
                }
            )

    status = "pass" if not errors and len(validated_movements) == len(movements or ()) else "blocked"
    return {
        "schema": "torii.hamburg-movement-authority-validation/v1",
        "status": status,
        "authority_id": authority.get("authority_id"),
        "authority_review_status": authority.get("status"),
        "authority_file": str(authority_path),
        "authority_sha256": file_sha256(authority_path),
        "candidate_net_file": str(candidate),
        "candidate_sha256": file_sha256(candidate),
        "movement_count": len(validated_movements),
        "movement_keys": [item["movement_key"] for item in validated_movements],
        "movements": validated_movements,
        "errors": errors,
    }


def run_hamburg_authorized_movement_smoke(
    *,
    authority_file: Path,
    candidate_net_file: Path,
    output_dir: Path,
    sumo_binary: str = "sumo",
    departure_interval_s: int = 8,
    end_time_s: int = 600,
    timeout_seconds: float = 120.0,
    command_runner: CommandRunner = run_command,
) -> dict[str, Any]:
    """Run only routes declared by the independent movement authority."""

    validation = validate_hamburg_movement_authority(
        authority_file=authority_file,
        candidate_net_file=candidate_net_file,
    )
    if validation["status"] != "pass":
        raise HamburgMovementAuthorityError("; ".join(validation["errors"]))
    candidate = Path(validation["candidate_net_file"])
    authority_path = Path(validation["authority_file"])
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    route_file = destination / "authorized-movements.rou.xml"
    config_file = destination / "authorized-movements.sumocfg"
    summary_file = destination / "summary.xml"
    tripinfo_file = destination / "tripinfo.xml"
    report_file = destination / "authorized-movements.report.json"

    route_root = ET.Element("routes")
    ET.SubElement(
        route_root,
        "vType",
        id="authorized_movement_passenger",
        vClass="passenger",
        accel="2.6",
        decel="4.5",
        sigma="0",
        length="5",
        maxSpeed="13.9",
    )
    for index, movement in enumerate(validation["movements"]):
        attributes = {
            "id": f"authority_movement_{index:03d}",
            "type": "authorized_movement_passenger",
            "depart": str(index * departure_interval_s),
        }
        if movement["depart_lane"] is not None:
            attributes["departLane"] = str(movement["depart_lane"])
        if movement["arrival_lane"] is not None:
            attributes["arrivalLane"] = str(movement["arrival_lane"])
        vehicle = ET.SubElement(route_root, "vehicle", **attributes)
        ET.SubElement(vehicle, "route", edges=" ".join(movement["route_edges"]))
    _write_xml(route_file, route_root)

    config_root = ET.Element("configuration")
    inputs = ET.SubElement(config_root, "input")
    ET.SubElement(
        inputs,
        "net-file",
        value=relative_or_absolute_path(candidate, destination),
    )
    ET.SubElement(inputs, "route-files", value=route_file.name)
    time = ET.SubElement(config_root, "time")
    ET.SubElement(time, "begin", value="0")
    ET.SubElement(time, "end", value=str(end_time_s))
    outputs = ET.SubElement(config_root, "output")
    ET.SubElement(outputs, "summary-output", value=summary_file.name)
    ET.SubElement(outputs, "tripinfo-output", value=tripinfo_file.name)
    _write_xml(config_file, config_root)

    for stale in (summary_file, tripinfo_file):
        stale.unlink(missing_ok=True)
    command = [
        sumo_binary,
        "-c",
        config_file.name,
        "--collision.check-junctions",
        "true",
        "--duration-log.statistics",
        "--quit-on-end",
    ]
    result = command_runner(command, cwd=destination, timeout_seconds=timeout_seconds)
    command_result = result.to_dict() if hasattr(result, "to_dict") else dict(result)
    inspection = inspect_run_outputs(
        "hamburg-authorized-movement-smoke",
        summary_path=summary_file,
        tripinfo_path=tripinfo_file,
    ).model_dump(mode="json")
    for section_name in ("summary", "tripinfo"):
        section = inspection.get(section_name)
        if isinstance(section, dict) and section.get("path"):
            section["path"] = relative_or_absolute_path(
                Path(str(section["path"])),
                report_file.parent,
            )
    if command_result.get("cwd"):
        command_result["cwd"] = relative_or_absolute_path(
            Path(str(command_result["cwd"])),
            report_file.parent,
        )
    summary = inspection.get("summary") or {}
    tripinfo = inspection.get("tripinfo") or {}
    vehicle_count = validation["movement_count"]
    loaded = summary.get("loaded")
    inserted = summary.get("inserted")
    ended = summary.get("arrived")
    running = summary.get("running")
    waiting = summary.get("waiting")
    teleports = summary.get("teleports")
    collisions = summary.get("collisions")
    checks = {
        "command": command_result.get("status") == "pass" and command_result.get("returncode") == 0,
        "inspection": inspection.get("status") == "pass",
        "all_loaded": loaded == vehicle_count,
        "all_inserted": inserted == vehicle_count,
        "all_ended": ended == vehicle_count and tripinfo.get("trip_count") == vehicle_count,
        "none_running_or_waiting": running == 0 and waiting == 0,
        "zero_teleports_or_collisions": teleports == 0 and collisions == 0,
        "candidate_immutable": file_sha256(candidate) == validation["candidate_sha256"],
    }
    def identity(path: Path) -> dict[str, str]:
        return {
            "path": relative_or_absolute_path(path, report_file.parent),
            "sha256": file_sha256(path),
        }

    report = {
        "schema": SMOKE_SCHEMA,
        "status": "pass" if all(checks.values()) else "fail",
        "automatic_promotion_gate": "blocked",
        "authority_review_status": validation["authority_review_status"],
        "candidate_net_file": relative_or_absolute_path(candidate, report_file.parent),
        "candidate_sha256": validation["candidate_sha256"],
        "authority_id": validation["authority_id"],
        "movement_keys": validation["movement_keys"],
        "movement_keys_unique": len(set(validation["movement_keys"])) == vehicle_count,
        "movement_count": vehicle_count,
        "vehicle_count": vehicle_count,
        "loaded": loaded,
        "inserted": inserted,
        "ended": ended,
        "running": running,
        "waiting": waiting,
        "teleports": teleports,
        "collisions": collisions,
        "inspection": inspection,
        "inputs": {
            "movement_authority": identity(authority_path),
            "route": identity(route_file),
            "config": identity(config_file),
        },
        "outputs": {
            "summary": identity(summary_file) if summary_file.is_file() else None,
            "tripinfo": identity(tripinfo_file) if tripinfo_file.is_file() else None,
        },
        "validation": {
            **validation,
            "authority_file": relative_or_absolute_path(authority_path, report_file.parent),
            "candidate_net_file": relative_or_absolute_path(candidate, report_file.parent),
        },
        "checks": checks,
        "command": command,
        "command_result": command_result,
    }
    write_json_atomic(report_file, report, sort_keys=True)
    return {**report, "report_file": str(report_file)}


def _write_xml(path: Path, root: ET.Element) -> None:
    ET.indent(root, space="  ")
    write_text_atomic(
        path,
        "<?xml version='1.0' encoding='utf-8'?>\n"
        + ET.tostring(root, encoding="unicode")
        + "\n",
    )

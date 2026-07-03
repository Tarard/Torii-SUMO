from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from .compile_plain import _connection_rows, needs_sumo_crossing
from .schema import CompiledSUMOArtifacts, IntersectionIR, IntersectionValidation, Movement, ValidationWarningRecord


def validate_intersection(
    ir: IntersectionIR,
    artifacts: CompiledSUMOArtifacts,
    output_dir: Path,
) -> IntersectionValidation:
    warnings: list[str] = []
    warning_records: list[ValidationWarningRecord] = []
    for warning in artifacts.netconvert_warnings:
        _add_warning(warnings, warning_records, f"netconvert: {warning}", "netconvert", _warning_severity(warning))
    sumo_load_status = "fail"
    net_path = Path(artifacts.net_file)
    if not net_path.is_absolute():
        net_path = net_path.resolve()
        output_relative_net_path = (output_dir / artifacts.net_file).resolve()
        if not net_path.exists() and output_relative_net_path.exists():
            net_path = output_relative_net_path
    if artifacts.net_file and net_path.exists():
        sumo = shutil.which("sumo")
        if sumo:
            command = [
                sumo,
                "-n",
                str(net_path),
                "--begin",
                "0",
                "--end",
                "1",
                "--no-step-log",
                "true",
                "--duration-log.disable",
                "true",
            ]
            result = subprocess.run(command, cwd=output_dir, capture_output=True, text=True, timeout=30)
            sumo_load_status = "pass" if result.returncode == 0 else "fail"
            if result.returncode != 0:
                _add_warning(warnings, warning_records, result.stderr.strip() or "sumo load failed", "sumo", "blocking")
        else:
            _add_warning(warnings, warning_records, "sumo binary not found", "sumo", "blocking")
    else:
        _add_warning(warnings, warning_records, "compiled net file not available", "torii", "blocking")

    tls_status, tls_warnings = _tls_linkindex_status(ir, artifacts, output_dir)
    for warning in tls_warnings:
        _add_warning(warnings, warning_records, warning, "torii", "blocking")
    vehicle_approach_count = sum(1 for approach in ir.approaches if "passenger" in approach.allowed_modes)
    vehicle_topology_type = _topology_type(vehicle_approach_count)
    topology_supported = (
        ir.core.topology_type in {"T3", "X4"} and len(ir.approaches) >= 3
    ) or vehicle_topology_type in {"T3", "X4"}
    if not topology_supported:
        _add_warning(
            warnings,
            warning_records,
            f"unsupported intersection topology: {ir.core.topology_type} with {len(ir.approaches)} approaches",
            "torii",
            "blocking",
        )
    if needs_sumo_crossing(ir) and not _net_has_crossing(net_path):
        _add_warning(warnings, warning_records, "missing SUMO crossing edge for OSM pedestrian crossing support", "torii", "blocking")
    warning_count_by_severity = dict(Counter(record.severity for record in warning_records))
    blocking_error_count = ir.road_pair_graph.blocking_error_count + warning_count_by_severity.get("blocking", 0)
    status = (
        "pass"
        if sumo_load_status == "pass"
        and tls_status != "fail"
        and topology_supported
        and blocking_error_count == 0
        else "blocked"
    )
    return IntersectionValidation(
        status=status,
        sumo_load_status=sumo_load_status,
        route_probe_status="skipped",
        approach_count=len(ir.approaches),
        movement_count=len(ir.movement_matrix.movements),
        missing_movement_count=ir.road_pair_graph.missing_connection_count,
        forbidden_movement_count=ir.movement_matrix.forbidden_movement_count,
        internal_fragment_count=ir.core.internal_fragment_count,
        duplicate_junction_count=0,
        disconnected_edge_count=ir.road_pair_graph.missing_connection_count,
        tls_linkindex_status=tls_status,
        approach_mode_counts=_approach_mode_counts(ir),
        vehicle_approach_count=vehicle_approach_count,
        vehicle_topology_type=vehicle_topology_type,
        legal_movement_mode_counts=_legal_movement_mode_counts(ir.movement_matrix.movements),
        forbidden_cross_mode_movement_count=sum(
            1 for movement in ir.movement_matrix.movements if not movement.allowed and not movement.allowed_modes
        ),
        warning_records=warning_records,
        warning_count_by_severity=warning_count_by_severity,
        blocking_error_count=blocking_error_count,
        warnings=warnings,
    )


def _add_warning(
    warnings: list[str],
    records: list[ValidationWarningRecord],
    message: str,
    source: str,
    severity: str,
) -> None:
    warnings.append(message)
    records.append(ValidationWarningRecord(message=message, source=source, severity=severity))


def _warning_severity(message: str) -> str:
    lower = message.lower()
    if "not connected" in lower or "invalid pedestrian topology" in lower or "missing sumo crossing edge" in lower:
        return "blocking"
    return "diagnostic"


def _approach_mode_counts(ir: IntersectionIR) -> dict[str, int]:
    return dict(Counter(_mode_key(approach.allowed_modes) for approach in ir.approaches))


def _tls_linkindex_status(ir: IntersectionIR, artifacts: CompiledSUMOArtifacts, output_dir: Path) -> tuple[str, list[str]]:
    if ir.control.control_type != "traffic_light":
        return "skipped", []
    allowed_movement_ids = {movement.movement_id for movement in ir.movement_matrix.movements if movement.allowed}
    warnings = []
    if not set(ir.control.link_index_map).issubset(allowed_movement_ids):
        warnings.append("controlled movement is not an allowed movement")
    connection_path = _artifact_path(artifacts.plain_connection_file, output_dir)
    tllogic_path = _artifact_path(artifacts.plain_tllogic_file, output_dir)
    if connection_path and connection_path.is_file():
        controlled_connections = [
            connection
            for connection in ET.parse(connection_path).getroot().findall("connection")
            if "tl" in connection.attrib
        ]
        expected_controlled_count = sum(
            1
            for movement, *_ in _connection_rows(ir)
            if movement.movement_id in ir.control.link_index_map
        )
        if len(controlled_connections) < expected_controlled_count:
            warnings.append("missing controlled connection in compiled plain connections")
        if tllogic_path and tllogic_path.is_file():
            states = [phase.attrib.get("state", "") for phase in ET.parse(tllogic_path).getroot().findall("tlLogic/phase")]
            if any(len(state) != len(controlled_connections) for state in states):
                warnings.append("tlLogic state length does not match controlled connection count")
            if any(int(connection.attrib.get("linkIndex", "-1")) >= len(states[0]) for connection in controlled_connections) if states else False:
                warnings.append("controlled connection linkIndex exceeds tlLogic state length")
    return ("fail" if warnings else "pass"), warnings


def _artifact_path(value: str | None, output_dir: Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return output_dir / path


def _legal_movement_mode_counts(movements: list[Movement]) -> dict[str, int]:
    return dict(Counter(_mode_key(movement.allowed_modes) for movement in movements if movement.allowed))


def _mode_key(modes: set[str]) -> str:
    return "+".join(sorted(modes)) if modes else "none"


def _topology_type(approach_count: int) -> str:
    if approach_count == 3:
        return "T3"
    if approach_count == 4:
        return "X4"
    if approach_count > 4:
        return "complex"
    return "unknown"


def _net_has_crossing(net_path: Path) -> bool:
    if not net_path.is_file():
        return False
    root = ET.parse(net_path).getroot()
    return any(edge.attrib.get("function") == "crossing" for edge in root.findall("edge"))

from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from .compile_plain import needs_sumo_crossing
from .schema import CompiledSUMOArtifacts, IntersectionIR, IntersectionValidation, Movement


def validate_intersection(
    ir: IntersectionIR,
    artifacts: CompiledSUMOArtifacts,
    output_dir: Path,
) -> IntersectionValidation:
    warnings: list[str] = [f"netconvert: {warning}" for warning in artifacts.netconvert_warnings]
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
                warnings.append(result.stderr.strip() or "sumo load failed")
        else:
            warnings.append("sumo binary not found")
    else:
        warnings.append("compiled net file not available")

    tls_status = (
        "skipped"
        if ir.control.control_type != "traffic_light"
        else ("pass" if len(ir.control.link_index_map) == ir.movement_matrix.legal_movement_count else "fail")
    )
    vehicle_approach_count = sum(1 for approach in ir.approaches if "passenger" in approach.allowed_modes)
    vehicle_topology_type = _topology_type(vehicle_approach_count)
    topology_supported = (
        ir.core.topology_type in {"T3", "X4"} and len(ir.approaches) >= 3
    ) or vehicle_topology_type in {"T3", "X4"}
    if not topology_supported:
        warnings.append(f"unsupported intersection topology: {ir.core.topology_type} with {len(ir.approaches)} approaches")
    if needs_sumo_crossing(ir) and not _net_has_crossing(net_path):
        warnings.append("missing SUMO crossing edge for OSM pedestrian crossing support")
    status = (
        "pass"
        if sumo_load_status == "pass"
        and tls_status != "fail"
        and topology_supported
        and not _has_blocking_validation_warning(warnings)
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
        warnings=warnings,
    )


def _approach_mode_counts(ir: IntersectionIR) -> dict[str, int]:
    return dict(Counter(_mode_key(approach.allowed_modes) for approach in ir.approaches))


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


def _has_blocking_validation_warning(warnings: list[str]) -> bool:
    return any(
        "not connected" in warning.lower()
        or "invalid pedestrian topology" in warning.lower()
        or "missing sumo crossing edge" in warning.lower()
        for warning in warnings
    )


def _net_has_crossing(net_path: Path) -> bool:
    if not net_path.exists():
        return False
    root = ET.parse(net_path).getroot()
    return any(edge.attrib.get("function") == "crossing" for edge in root.findall("edge"))

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .schema import CompiledSUMOArtifacts, IntersectionIR, IntersectionValidation


def validate_intersection(
    ir: IntersectionIR,
    artifacts: CompiledSUMOArtifacts,
    output_dir: Path,
) -> IntersectionValidation:
    warnings: list[str] = []
    sumo_load_status = "fail"
    if artifacts.net_file and Path(artifacts.net_file).exists():
        sumo = shutil.which("sumo")
        if sumo:
            command = [
                sumo,
                "-n",
                artifacts.net_file,
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
    status = "pass" if sumo_load_status == "pass" and tls_status != "fail" else "blocked"
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
        warnings=warnings,
    )

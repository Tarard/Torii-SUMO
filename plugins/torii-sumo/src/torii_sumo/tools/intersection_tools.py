from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from torii_sumo.intersection.clean import build_intersection_ir, clean_intersection
from torii_sumo.intersection.schema import CompiledSUMOArtifacts, IntersectionIR, PatchSeed
from torii_sumo.intersection.validate import (
    _approach_mode_counts,
    _legal_movement_mode_counts,
    _topology_type,
    validate_intersection,
)


def sumo_intersection_model(
    osm_file: str,
    output_dir: str,
    seed_osm_node_id: str | None = None,
) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ir = build_intersection_ir(
        Path(osm_file),
        out,
        seed=PatchSeed(osm_node_id=seed_osm_node_id) if seed_osm_node_id else None,
    )
    ir_file = out / "intersection_ir.json"
    ir_file.write_text(json.dumps(ir.model_dump(mode="json"), indent=2), encoding="utf-8")
    return {
        "status": "pass",
        "intersection_id": ir.intersection_id,
        "topology_type": ir.core.topology_type,
        "approach_count": len(ir.approaches),
        "movement_count": len(ir.movement_matrix.movements),
        "approach_mode_counts": _approach_mode_counts(ir),
        "vehicle_approach_count": sum(1 for approach in ir.approaches if "passenger" in approach.allowed_modes),
        "vehicle_topology_type": _topology_type(sum(1 for approach in ir.approaches if "passenger" in approach.allowed_modes)),
        "legal_movement_mode_counts": _legal_movement_mode_counts(ir.movement_matrix.movements),
        "forbidden_cross_mode_movement_count": sum(
            1 for movement in ir.movement_matrix.movements if not movement.allowed and not movement.allowed_modes
        ),
        "intersection_ir_file": str(ir_file),
        "claim_status": ir.claim_status,
    }


def sumo_intersection_clean(
    osm_file: str,
    output_dir: str,
    seed_osm_node_id: str | None = None,
    compile_net: bool = True,
) -> dict[str, Any]:
    return clean_intersection(
        osm_file=Path(osm_file),
        output_dir=Path(output_dir),
        seed=PatchSeed(osm_node_id=seed_osm_node_id) if seed_osm_node_id else None,
        compile_net=compile_net,
    )


def sumo_intersection_validate(
    intersection_ir_file: str,
    output_dir: str,
) -> dict[str, Any]:
    ir = IntersectionIR.model_validate_json(Path(intersection_ir_file).read_text(encoding="utf-8"))
    if ir.compiled is None:
        return {
            "status": "fail",
            "claim_status": "blocked",
            "error": "intersection_ir.compiled is required",
        }
    validation = validate_intersection(ir, CompiledSUMOArtifacts.model_validate(ir.compiled), Path(output_dir))
    validation_file = Path(output_dir) / "validation.json"
    validation_file.parent.mkdir(parents=True, exist_ok=True)
    validation_file.write_text(json.dumps(validation.model_dump(mode="json"), indent=2), encoding="utf-8")
    return {
        "status": validation.status,
        "sumo_load_status": validation.sumo_load_status,
        "route_probe_status": validation.route_probe_status,
        "warning_count_by_severity": validation.warning_count_by_severity,
        "blocking_error_count": validation.blocking_error_count,
        "validation_file": str(validation_file),
        "claim_status": "intersection-cleaned" if validation.status == "pass" else "blocked",
    }

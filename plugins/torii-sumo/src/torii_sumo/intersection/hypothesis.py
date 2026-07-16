from __future__ import annotations

import hashlib
import json
from typing import Any

from .candidate_dag import build_candidate_hypothesis_dag
from .movement_hypotheses import build_vehicle_movement_hypotheses
from .physical_cell import infer_signal_anchor_physical_cell
from .schema import OSMPatch


def build_teacher_free_intersection_hypothesis(
    patch: OSMPatch,
    *,
    seed_node_id: str,
    traffic_side: str,
    seed_authority: str = "caller_provided_anchor_only",
) -> dict[str, Any]:
    """Build one OSM-only intersection argument without benchmark answers.

    The seed is a mechanically selected graph node, not a reviewed scope.  The
    resulting physical cell, movement variants, and candidate DAG are all
    generated before any source/candidate SUMO comparison is allowed.
    """

    physical_cell = infer_signal_anchor_physical_cell(
        patch,
        seed_node_id=seed_node_id,
    )
    movement_hypotheses = build_vehicle_movement_hypotheses(
        patch,
        physical_cell,
        traffic_side=traffic_side,
    )
    candidate_dag = build_candidate_hypothesis_dag(
        physical_cell,
        movement_hypotheses,
    )
    unresolved = [
        *(f"physical_cell:{risk}" for risk in physical_cell["risks"]),
        *(f"movement_hypotheses:{reason}" for reason in movement_hypotheses["unresolved_reasons"]),
    ]
    generation_pass = all(
        artifact.get("generation_status") == "pass" for artifact in (physical_cell, movement_hypotheses, candidate_dag)
    )
    payload = {
        "schema": "torii.teacher-free-intersection-hypothesis/v1",
        "generation_status": "pass" if generation_pass else "blocked",
        "disposition": "suggest" if not unresolved else "review",
        "automatic_promotion_gate": "blocked",
        "seed_node_id": seed_node_id,
        "seed_authority": seed_authority,
        "traffic_side": traffic_side,
        "physical_cell": physical_cell,
        "vehicle_movement_hypotheses": movement_hypotheses,
        "candidate_dag": candidate_dag,
        "unresolved_reasons": sorted(set(unresolved)),
        "forbidden_generation_inputs": [
            "teacher_network",
            "reviewed_scope",
            "expected_topology",
            "expected_approach_count",
            "expected_movement_count",
            "materialized_candidate_network",
        ],
        "claim_boundary": (
            "This artifact is an OSM-only hypothesis generated without a "
            "teacher, reviewed scope, expected topology/count, or materialized "
            "candidate. It proposes evidence and reversible alternatives; it "
            "does not authorize a network or TLS edit."
        ),
    }
    return {
        **payload,
        "hypothesis_id": (f"teacher-free-intersection-{_stable_digest(payload)[:20]}"),
    }


def _stable_digest(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()

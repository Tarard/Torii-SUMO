from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from typing import Any


_TOPOLOGY_HYPOTHESES = (
    "preserve_split_shared_controller",
    "merge_physical_cell",
    "partial_internal_repair",
)


def build_candidate_hypothesis_dag(
    physical_cell: dict[str, Any],
    movement_hypotheses: dict[str, Any],
) -> dict[str, Any]:
    """Build reversible, mutually exclusive candidate plans.

    This is a planning artifact. It deliberately does not write PlainXML or a
    SUMO net and never selects a topology or movement variant automatically.
    """

    semantic_classes = _semantic_equivalence_classes(movement_hypotheses)
    physical_cell_id = str(physical_cell["hypothesis_id"])
    scope = _scope_record(physical_cell)
    evidence_node = {
        "node_id": physical_cell_id,
        "node_kind": "physical_cell_hypothesis",
        "status": physical_cell["disposition"],
        "source_junction_ids": scope["source_junction_ids"],
        "boundary_port_ids": scope["boundary_port_ids"],
        "physical_approach_ids": scope["physical_approach_ids"],
    }

    class_nodes = []
    candidate_nodes = []
    edges = []
    exclusion_groups = []
    for semantic_class in semantic_classes:
        class_node = {
            "node_id": semantic_class["semantic_class_id"],
            "node_kind": "movement_semantic_class",
            **semantic_class,
        }
        class_nodes.append(class_node)
        edges.append(
            {
                "from_node_id": physical_cell_id,
                "to_node_id": semantic_class["semantic_class_id"],
                "relation": "movement_semantics_depend_on_physical_cell",
            }
        )
        topology_candidate_ids = []
        for topology_hypothesis in _TOPOLOGY_HYPOTHESES:
            candidate = _candidate_node(
                physical_cell,
                semantic_class=semantic_class,
                topology_hypothesis=topology_hypothesis,
                scope=scope,
                nested_restriction_ids=movement_hypotheses["nested_restriction_ids"],
            )
            candidate_nodes.append(candidate)
            topology_candidate_ids.append(candidate["candidate_id"])
            edges.append(
                {
                    "from_node_id": semantic_class["semantic_class_id"],
                    "to_node_id": candidate["candidate_id"],
                    "relation": "candidate_depends_on_movement_semantics",
                }
            )
        exclusion_groups.append(
            {
                "group_id": (f"topology-choice-{semantic_class['semantic_class_id']}"),
                "reason": "one materialized candidate cannot use multiple physical-topology hypotheses",
                "candidate_ids": sorted(topology_candidate_ids),
                "selection_status": "unselected",
            }
        )

    if len(semantic_classes) > 1:
        exclusion_groups.append(
            {
                "group_id": f"movement-choice-{movement_hypotheses['hypothesis_set_id']}",
                "reason": "non-equivalent lane-movement semantic classes are mutually exclusive",
                "semantic_class_ids": sorted(item["semantic_class_id"] for item in semantic_classes),
                "selection_status": "unselected",
            }
        )

    payload = {
        "schema": "torii.intersection-candidate-dag/v1",
        "workflow_state": "HYPOTHESES_READY",
        "generation_status": "pass",
        "automatic_promotion_gate": "blocked",
        "selected_candidate_id": None,
        "parent_physical_cell_hypothesis_id": physical_cell_id,
        "parent_movement_hypothesis_set_id": movement_hypotheses["hypothesis_set_id"],
        "scope": scope,
        "nodes": [evidence_node, *class_nodes, *candidate_nodes],
        "edges": edges,
        "mutual_exclusion_groups": exclusion_groups,
        "semantic_equivalence_class_count": len(semantic_classes),
        "candidate_count": len(candidate_nodes),
        "review_ready_candidate_ids": sorted(
            item["candidate_id"] for item in candidate_nodes if item["candidate_status"] == "review_required"
        ),
        "blocked_candidate_ids": sorted(
            item["candidate_id"] for item in candidate_nodes if item["candidate_status"] == "blocked"
        ),
        "materializer_capabilities": {
            "plainxml_join_patch": "available_for_merge_hypothesis",
            "netconvert_internal_connection_regeneration": "available_after_candidate_selection",
            "obsolete_tls_owner_retirement": "available_through_scoped_netconvert_rebuild",
            "custom_tls_topology": "blocked_until_movement_and_conflict_closure",
            "field_timing_reconstruction": "out_of_scope",
            "direct_generic_netxml_edit": "prohibited",
        },
        "rollback_model": (
            "Candidates are immutable derived artifacts. Every operation rolls "
            "back by restoring the content-addressed parent source, never by "
            "mutating the source in place."
        ),
        "claim_boundary": (
            "This DAG proves candidate lineage, exclusivity, declared operations, "
            "and rollback intent. It does not prove which topology is physically "
            "correct and does not authorize materialization or TLS phases."
        ),
    }
    return {
        **payload,
        "candidate_dag_id": f"candidate-dag-{_stable_digest(payload)[:20]}",
    }


def _semantic_equivalence_classes(
    movement_hypotheses: dict[str, Any],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for variant in movement_hypotheses["variants"]:
        groups[str(variant["semantic_signature"])].append(variant)
    records = []
    for semantic_signature, variants in sorted(groups.items()):
        variant_ids = sorted(item["variant_id"] for item in variants)
        unresolved_reasons = sorted({reason for variant in variants for reason in variant["unresolved_reasons"]})
        payload = {
            "semantic_signature": semantic_signature,
            "movement_variant_ids": variant_ids,
            "methods": sorted(item["method"] for item in variants),
            "atomic_movement_count": variants[0]["atomic_movement_count"],
            "movement_family_count": variants[0]["movement_family_count"],
            "lane_coverage_status": variants[0]["lane_coverage"]["status"],
            "unresolved_reasons": unresolved_reasons,
        }
        records.append(
            {
                "semantic_class_id": (f"movement-class-{_stable_digest(payload)[:16]}"),
                **payload,
            }
        )
    return records


def _candidate_node(
    physical_cell: dict[str, Any],
    *,
    semantic_class: dict[str, Any],
    topology_hypothesis: str,
    scope: dict[str, Any],
    nested_restriction_ids: list[str],
) -> dict[str, Any]:
    blockers = list(semantic_class["unresolved_reasons"])
    blockers.extend(f"physical_cell:{item}" for item in physical_cell["risks"])
    if nested_restriction_ids:
        blockers.append("nested_turn_restrictions_not_resolved_to_lane_paths")
    review_requirements = _topology_review_requirements(topology_hypothesis)
    operation_specs = _operation_specs(
        topology_hypothesis,
        scope=scope,
        semantic_class=semantic_class,
    )
    identity_payload = {
        "physical_cell_hypothesis_id": physical_cell["hypothesis_id"],
        "semantic_class_id": semantic_class["semantic_class_id"],
        "topology_hypothesis": topology_hypothesis,
    }
    candidate_id = f"candidate-{_stable_digest(identity_payload)[:20]}"
    return {
        "node_id": candidate_id,
        "node_kind": "candidate_variant",
        "candidate_id": candidate_id,
        **identity_payload,
        "candidate_status": "blocked" if blockers else "review_required",
        "automatic_promotion_gate": "blocked",
        "materialization_status": "not_materialized",
        "scope": scope,
        "declared_operations": operation_specs,
        "operation_count": len(operation_specs),
        "blockers": sorted(set(blockers)),
        "review_requirements": review_requirements,
        "preconditions": [
            "source artifact path and sha256 are bound",
            "boundary ports and lane cardinality still match this hypothesis",
            "movement semantic class is selected by review or certified evidence",
            "topology hypothesis is selected independently of controller membership",
            "all affected multimodal and controller owner closures are known",
        ],
        "expected_postconditions": _postconditions(topology_hypothesis),
        "rollback": {
            "strategy": "restore_content_addressed_parent_artifact",
            "source_mutation": False,
            "inverse_operation_ids": [item["inverse_operation"]["operation_id"] for item in reversed(operation_specs)],
        },
    }


def _operation_specs(
    topology_hypothesis: str,
    *,
    scope: dict[str, Any],
    semantic_class: dict[str, Any],
) -> list[dict[str, Any]]:
    shared = {
        "source_junction_ids": scope["source_junction_ids"],
        "boundary_port_ids": scope["boundary_port_ids"],
        "movement_semantic_signature": semantic_class["semantic_signature"],
    }
    if topology_hypothesis == "preserve_split_shared_controller":
        specs = [
            ("assert_preserved_physical_nodes", "assertion", shared),
            ("retire_obsolete_source_tls_owners", "plainxml_tls_scope", shared),
            ("bind_shared_controller_after_conflict_closure", "plainxml_tls_scope", shared),
        ]
    elif topology_hypothesis == "merge_physical_cell":
        specs = [
            ("join_physical_cell_nodes", "plainxml_node_join", shared),
            ("regenerate_internal_lane_connections", "netconvert_rebuild", shared),
            ("retire_obsolete_source_tls_owners", "netconvert_rebuild", shared),
            ("bind_merged_controller_after_conflict_closure", "plainxml_tls_scope", shared),
        ]
    else:
        specs = [
            ("assert_preserved_physical_nodes", "assertion", shared),
            ("rebuild_scoped_internal_connections", "plainxml_connection_scope", shared),
            ("rebuild_request_foes_from_independent_conflicts", "netconvert_rebuild", shared),
            ("rebind_controller_groups_after_conflict_closure", "plainxml_tls_scope", shared),
        ]
    return [
        _operation_record(
            name,
            operation_type=operation_type,
            payload=payload,
        )
        for name, operation_type, payload in specs
    ]


def _operation_record(
    name: str,
    *,
    operation_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    identity = {
        "name": name,
        "operation_type": operation_type,
        "payload": payload,
    }
    operation_id = f"operation-{_stable_digest(identity)[:16]}"
    return {
        "operation_id": operation_id,
        **identity,
        "precondition_mode": "fail_closed",
        "inverse_operation": {
            "operation_id": f"inverse-{operation_id}",
            "operation_type": "restore_content_addressed_parent_artifact",
            "source_mutation": False,
        },
    }


def _scope_record(physical_cell: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_junction_ids": sorted(map(str, physical_cell["proposed_source_junction_ids"])),
        "geometry_shape_node_ids": sorted(map(str, physical_cell["geometry_shape_node_ids"])),
        "boundary_port_ids": sorted(item["boundary_port_id"] for item in physical_cell["raw_boundary_ports"]),
        "physical_approach_ids": sorted(item["physical_approach_id"] for item in physical_cell["physical_approaches"]),
        "scope_closure": [
            "physical_cell_members",
            "internal_geometry_shape_nodes",
            "boundary_ports",
            "movement_paths",
            "controller_owners",
        ],
    }


def _topology_review_requirements(topology_hypothesis: str) -> list[str]:
    if topology_hypothesis == "preserve_split_shared_controller":
        return [
            "prove multiple stop lines or conflict cells justify preserved nodes",
            "bind the complete shared-controller owner closure",
        ]
    if topology_hypothesis == "merge_physical_cell":
        return [
            "prove one connected physical conflict envelope",
            "prove no independent storage, crossing, access, rail, or grade separation",
            "prove fixed boundary ports remain unchanged after regeneration",
        ]
    return [
        "identify exact broken movement/request/TLS witnesses",
        "prove external junction topology and boundary ports need no change",
    ]


def _postconditions(topology_hypothesis: str) -> list[str]:
    common = [
        "all declared lane movements have traceable internal paths",
        "independent conflict graph agrees with request/foes and TLS groups",
        "outside-scope stable semantic diff is empty",
        "SUMO load and routeability smoke pass",
    ]
    if topology_hypothesis == "merge_physical_cell":
        return [
            "one target physical junction replaces only declared source members",
            "all obsolete source TLS owner identities are absent",
            *common,
        ]
    return [
        "declared physical junction identities remain unchanged",
        *common,
    ]


def _stable_digest(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()

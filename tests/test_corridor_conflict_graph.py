from __future__ import annotations

from xml.etree import ElementTree as ET

from torii_sumo.corridor.canonicalizer import (
    CanonicalEntity,
    CanonicalNetworkSnapshot,
    canonicalize_raw_network,
)
from torii_sumo.corridor.conflict_graph import (
    audit_independent_movement_safety,
    build_movement_conflict_graph,
)
from torii_sumo.corridor.enums import GateStatus, TrafficSide
from torii_sumo.corridor.ids import stable_id
from torii_sumo.corridor.netxml import parse_net_xml


def _entity(
    kind: str,
    entity_id: str,
    payload: dict,
    *,
    cell_id: str,
) -> CanonicalEntity:
    return CanonicalEntity(
        kind=kind,
        stable_entity_id=entity_id,
        semantic_signature=stable_id(
            "signature",
            {"kind": kind, "payload": payload},
        ),
        owner_physical_cell_ids=(cell_id,),
        payload=payload,
    )


def _crossing_snapshot(
    *,
    shared_signal_group: bool = False,
    protected_both: bool = True,
    pedestrian_facilities: int = 0,
    unsupported_controlled_links: int = 0,
    shape_a=((-10.0, 0.0), (10.0, 0.0)),
    shape_b=((0.0, -10.0), (0.0, 10.0)),
):
    cell_id = stable_id("cell", {"test": "crossing"})
    controller_id = stable_id("controller", {"cell": cell_id})
    source_a = stable_id("lane_role", {"lane": "west-in"})
    target_a = stable_id("lane_role", {"lane": "east-out"})
    source_b = stable_id("lane_role", {"lane": "south-in"})
    target_b = stable_id("lane_role", {"lane": "north-out"})
    movement_a = stable_id("movement", {"movement": "west-east"})
    movement_b = stable_id("movement", {"movement": "south-north"})
    path_a = stable_id("path", {"movement_id": movement_a})
    path_b = stable_id("path", {"movement_id": movement_b})

    def path_payload(movement_id: str, shape):
        return {
            "movement_id": movement_id,
            "multiplicity": 1,
            "path_variants": [
                {
                    "path_signature": stable_id(
                        "signature",
                        {"movement_id": movement_id, "shape": shape},
                    ),
                    "path": {
                        "status": "pass",
                        "segments": [
                            {
                                "shape_xy": shape,
                                "permissions": {
                                    "allow": ["passenger"],
                                    "disallow": [],
                                },
                                "width_m": 3.2,
                                "speed_mps": 13.9,
                            }
                        ],
                        "failures": [],
                    },
                }
            ],
        }

    def movement_payload(
        movement_id: str,
        path_id: str,
        source_role_id: str,
        destination_role_id: str,
    ):
        return {
            "multiplicity": 1,
            "variants": [
                {
                    "source_lane_role_id": source_role_id,
                    "destination_lane_role_id": destination_role_id,
                    "mode": "passenger",
                    "turn_class": "straight",
                }
            ],
            "internal_path_id": path_id,
        }

    entities = [
        _entity(
            "internal_path",
            path_a,
            path_payload(movement_a, shape_a),
            cell_id=cell_id,
        ),
        _entity(
            "internal_path",
            path_b,
            path_payload(movement_b, shape_b),
            cell_id=cell_id,
        ),
        _entity(
            "movement",
            movement_a,
            movement_payload(movement_a, path_a, source_a, target_a),
            cell_id=cell_id,
        ),
        _entity(
            "movement",
            movement_b,
            movement_payload(movement_b, path_b, source_b, target_b),
            cell_id=cell_id,
        ),
        _entity(
            "request_foes",
            stable_id("request", {"cell": cell_id}),
            {
                "physical_cell_id": cell_id,
                "request_rows": [
                    {"index": 0, "response": "00", "foes": "00", "cont": "0"},
                    {"index": 1, "response": "00", "foes": "00", "cont": "0"},
                ],
            },
            cell_id=cell_id,
        ),
    ]
    if shared_signal_group:
        group_ids = (stable_id("signal_group", {"shared": [movement_a, movement_b]}),)
        group_movements = ((movement_a, movement_b),)
    else:
        group_ids = (
            stable_id("signal_group", {"movement": movement_a}),
            stable_id("signal_group", {"movement": movement_b}),
        )
        group_movements = ((movement_a,), (movement_b,))
    for group_id, movement_ids in zip(group_ids, group_movements, strict=True):
        entities.append(
            _entity(
                "signal_group",
                group_id,
                {
                    "controller_id": controller_id,
                    "movement_ids": movement_ids,
                    "source_link_indices": [0],
                    "multiple_source_indices": False,
                },
                cell_id=cell_id,
            )
        )
    program_id = stable_id("program", {"controller": controller_id})
    entities.append(
        _entity(
            "controller_program",
            program_id,
            {
                "controller_id": controller_id,
                "controller_type": "static",
                "offset": 0.0,
                "signal_group_ids": group_ids,
                "phases": [
                    {
                        "duration": 30.0,
                        "group_states": [
                            {
                                "signal_group_id": group_id,
                                "states": [
                                    "G"
                                    if protected_both or group_id == group_ids[0]
                                    else "r"
                                ],
                                "consistent": True,
                            }
                            for group_id in group_ids
                        ],
                    }
                ],
            },
            cell_id=cell_id,
        )
    )
    entities.append(
        _entity(
            "safety_coverage",
            stable_id("coverage", {"cell": cell_id}),
            {
                "canonical_movement_count": 2,
                "controlled_connection_count": 2 + unsupported_controlled_links,
                "mapped_controlled_movement_count": 2,
                "unsupported_controlled_connection_count": unsupported_controlled_links,
                "unsupported_controlled_connections": (
                    [
                        {
                            "from_function": "walkingarea",
                            "to_function": "crossing",
                            "direction": "straight",
                        }
                    ]
                    if unsupported_controlled_links
                    else []
                ),
                "crossing_edge_count": pedestrian_facilities,
                "walkingarea_edge_count": pedestrian_facilities,
                "link_index2_connection_count": 0,
                "movement_mode_class_counts": {"road-motorized": 2},
                "ownership_status": "resolved",
            },
            cell_id=cell_id,
        )
    )
    return (
        CanonicalNetworkSnapshot(
            traffic_side=TrafficSide.RIGHT,
            entities=tuple(entities),
        ),
        movement_a,
        movement_b,
    )


def test_independent_conflict_graph_ignores_request_foes_self_consistency() -> None:
    snapshot, movement_a, movement_b = _crossing_snapshot()

    graph = build_movement_conflict_graph(snapshot)

    assert len(graph.conflicts) == 1
    conflict = graph.conflicts[0]
    assert {conflict.movement_a_id, conflict.movement_b_id} == {
        movement_a,
        movement_b,
    }
    assert conflict.reason == "centerline-crossing"
    assert conflict.certainty == "confirmed"


def test_protected_green_crossing_is_a_hard_independent_safety_failure() -> None:
    snapshot, _, _ = _crossing_snapshot()

    report = audit_independent_movement_safety(snapshot)

    assert report.status is GateStatus.BLOCKED
    assert report.automatic_promotion_gate is GateStatus.BLOCKED
    assert report.protected_conflict_count == 1
    assert {
        finding.category for finding in report.findings
    } >= {"protected_green_movement_conflict"}


def test_conflicting_movements_cannot_share_one_signal_group() -> None:
    snapshot, _, _ = _crossing_snapshot(shared_signal_group=True)

    report = audit_independent_movement_safety(snapshot)

    assert report.status is GateStatus.BLOCKED
    assert report.shared_signal_group_conflict_count == 1
    assert {
        finding.category for finding in report.findings
    } >= {"conflicting_movements_share_signal_group"}


def test_unmodelled_pedestrian_facilities_block_automatic_promotion_as_review() -> None:
    snapshot, _, _ = _crossing_snapshot(
        protected_both=False,
        pedestrian_facilities=1,
    )

    report = audit_independent_movement_safety(snapshot)

    assert report.status is GateStatus.REVIEW
    assert report.automatic_promotion_gate is GateStatus.BLOCKED
    assert report.applicability_status is GateStatus.REVIEW
    assert report.coverage.crossing_edge_count == 1
    assert "pedestrian_facilities_outside_independent_conflict_model" in (
        report.limitations
    )


def test_unmapped_controlled_link_is_a_hard_safety_coverage_failure() -> None:
    snapshot, _, _ = _crossing_snapshot(
        protected_both=False,
        unsupported_controlled_links=1,
    )

    report = audit_independent_movement_safety(snapshot)

    assert report.status is GateStatus.BLOCKED
    assert report.coverage.unsupported_controlled_connection_count == 1
    assert {
        finding.category for finding in report.findings
    } >= {"controlled_link_outside_independent_conflict_model"}


def test_lane_envelope_proximity_is_review_not_a_confirmed_safety_failure() -> None:
    snapshot, _, _ = _crossing_snapshot(
        shape_a=((-1.0, 0.0), (1.0, 0.0)),
        shape_b=((0.0, 3.2), (1.0, 2.8)),
    )

    report = audit_independent_movement_safety(snapshot)

    assert len(report.conflict_graph.conflicts) == 1
    assert report.conflict_graph.conflicts[0].certainty == "potential"
    assert report.status is GateStatus.REVIEW
    assert report.protected_conflict_count == 0
    assert report.potential_signal_conflict_count == 1
    assert {
        finding.category for finding in report.findings
    } >= {"protected_green_potential_envelope_conflict"}


def test_permissive_conflict_requires_yield_review_not_a_claimed_safety_defect() -> None:
    snapshot, _, _ = _crossing_snapshot(protected_both=False)
    program = next(
        entity for entity in snapshot.entities if entity.kind == "controller_program"
    )
    phases = program.payload["phases"]
    phases[0]["group_states"][1]["states"] = ["g"]

    report = audit_independent_movement_safety(snapshot)

    assert report.status is GateStatus.REVIEW
    assert report.automatic_promotion_gate is GateStatus.BLOCKED
    assert report.permissive_without_yield_count == 1
    assert report.protected_conflict_count == 0
    assert {
        finding.category for finding in report.findings
    } >= {"permissive_conflict_requires_independent_yield_review"}
    assert all(finding.severity.value != "safety" for finding in report.findings)


def test_no_internal_links_geometry_is_reviewed_as_unavailable_by_design() -> None:
    root = ET.fromstring(
        """<net>
  <edge id="in" from="a" to="j">
    <lane id="in_0" index="0" allow="passenger" width="3.2" shape="-10,0 0,0"/>
  </edge>
  <edge id="out" from="j" to="b">
    <lane id="out_0" index="0" allow="passenger" width="3.2" shape="0,0 10,0"/>
  </edge>
  <junction id="a" type="dead_end" incLanes="" intLanes=""/>
  <junction id="j" type="priority" incLanes="in_0" intLanes="">
    <request index="0" response="0" foes="0"/>
  </junction>
  <junction id="b" type="dead_end" incLanes="out_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0" dir="s" state="M"/>
</net>"""
    )
    snapshot = canonicalize_raw_network(
        parse_net_xml(root),
        traffic_side=TrafficSide.RIGHT,
    )

    report = audit_independent_movement_safety(snapshot)

    assert report.status is GateStatus.REVIEW
    assert report.automatic_promotion_gate is GateStatus.BLOCKED
    assert report.conflict_graph.geometry_missing_movement_ids == ()
    assert len(
        report.conflict_graph.geometry_unavailable_by_design_movement_ids
    ) == 1
    assert report.limitations == ("movement_geometry_unavailable_no_internal_links",)
    categories = {finding.category for finding in report.findings}
    assert "movement_geometry_unavailable_no_internal_links" in categories
    assert "movement_geometry_missing_for_independent_safety" not in categories


def test_shared_inner_vertices_are_confirmed_centerline_crossings() -> None:
    snapshot, _, _ = _crossing_snapshot(
        shape_a=((-10.0, 0.0), (0.0, 0.0), (10.0, 0.0)),
        shape_b=((0.0, -10.0), (0.0, 0.0), (0.0, 10.0)),
    )

    graph = build_movement_conflict_graph(snapshot)

    assert len(graph.conflicts) == 1
    assert graph.conflicts[0].reason == "centerline-crossing"
    assert graph.conflicts[0].certainty == "confirmed"
    assert graph.conflicts[0].crossing_angle_deg == 90.0

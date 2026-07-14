from __future__ import annotations

import itertools
import math

from pydantic import model_validator

from .base import ContractModel, StableToken
from .canonicalizer import CanonicalEntity, CanonicalNetworkSnapshot
from .enums import FindingSeverity, GateStatus
from .evidence import Finding
from .exact_diff import build_finding
from .ids import require_stable_id, stable_id


class MovementConflict(ContractModel):
    conflict_id: StableToken
    movement_a_id: StableToken
    movement_b_id: StableToken
    reason: str
    minimum_centerline_distance_m: float
    crossing_angle_deg: float | None = None

    @model_validator(mode="after")
    def validate_conflict(self) -> MovementConflict:
        require_stable_id(self.conflict_id, kind="conflict")
        require_stable_id(self.movement_a_id, kind="movement")
        require_stable_id(self.movement_b_id, kind="movement")
        if self.movement_a_id >= self.movement_b_id:
            raise ValueError("Conflict movement IDs must use stable sorted order.")
        return self


class MovementConflictGraph(ContractModel):
    schema_id: str = "torii.corridor.movement-conflict-graph/v1"
    movement_ids: tuple[StableToken, ...]
    conflicts: tuple[MovementConflict, ...]
    geometry_missing_movement_ids: tuple[StableToken, ...] = ()

    def conflict_index(self) -> dict[frozenset[str], MovementConflict]:
        return {
            frozenset((conflict.movement_a_id, conflict.movement_b_id)): conflict
            for conflict in self.conflicts
        }


class IndependentSafetyReport(ContractModel):
    schema_id: str = "torii.corridor.independent-safety-audit/v1"
    status: GateStatus
    automatic_promotion_gate: GateStatus
    conflict_graph: MovementConflictGraph
    findings: tuple[Finding, ...]
    protected_conflict_count: int
    permissive_without_yield_count: int
    shared_signal_group_conflict_count: int
    blockers: tuple[str, ...]

    @model_validator(mode="after")
    def validate_report(self) -> IndependentSafetyReport:
        if self.findings and self.automatic_promotion_gate is GateStatus.PASS:
            raise ValueError("Independent safety findings cannot pass automatic promotion.")
        return self


def build_movement_conflict_graph(
    snapshot: CanonicalNetworkSnapshot,
    *,
    envelope_margin_m: float = 0.25,
) -> MovementConflictGraph:
    if envelope_margin_m < 0:
        raise ValueError("Conflict envelope margin must be non-negative.")
    entities = snapshot.entity_index()
    movement_entities = {
        entity.stable_entity_id: entity
        for entity in snapshot.entities
        if entity.kind == "movement"
    }
    geometries: dict[str, _MovementGeometry] = {}
    missing: list[str] = []
    for movement_id, movement in movement_entities.items():
        geometry = _movement_geometry(movement, entities)
        if geometry is None:
            missing.append(movement_id)
        else:
            geometries[movement_id] = geometry
    conflicts: list[MovementConflict] = []
    for movement_a_id, movement_b_id in itertools.combinations(sorted(geometries), 2):
        geometry_a = geometries[movement_a_id]
        geometry_b = geometries[movement_b_id]
        result = _geometry_conflict(
            geometry_a,
            geometry_b,
            envelope_margin_m=envelope_margin_m,
        )
        if result is None:
            continue
        reason, distance, angle = result
        conflicts.append(
            MovementConflict(
                conflict_id=stable_id(
                    "conflict",
                    {
                        "movement_ids": [movement_a_id, movement_b_id],
                        "reason": reason,
                    },
                ),
                movement_a_id=movement_a_id,
                movement_b_id=movement_b_id,
                reason=reason,
                minimum_centerline_distance_m=round(distance, 6),
                crossing_angle_deg=round(angle, 6) if angle is not None else None,
            )
        )
    return MovementConflictGraph(
        movement_ids=tuple(sorted(movement_entities)),
        conflicts=tuple(conflicts),
        geometry_missing_movement_ids=tuple(sorted(missing)),
    )


def audit_independent_movement_safety(
    snapshot: CanonicalNetworkSnapshot,
    *,
    envelope_margin_m: float = 0.25,
) -> IndependentSafetyReport:
    graph = build_movement_conflict_graph(
        snapshot,
        envelope_margin_m=envelope_margin_m,
    )
    conflict_index = graph.conflict_index()
    signal_groups = {
        entity.stable_entity_id: entity
        for entity in snapshot.entities
        if entity.kind == "signal_group"
    }
    findings: dict[str, Finding] = {}
    protected_conflict_count = 0
    permissive_without_yield_count = 0
    shared_signal_group_conflict_count = 0

    for signal_group_id, signal_group in signal_groups.items():
        movement_ids = tuple(sorted(map(str, signal_group.payload.get("movement_ids", ()))))
        for movement_a_id, movement_b_id in itertools.combinations(movement_ids, 2):
            conflict = conflict_index.get(frozenset((movement_a_id, movement_b_id)))
            if conflict is None:
                continue
            shared_signal_group_conflict_count += 1
            finding = build_finding(
                category="conflicting_movements_share_signal_group",
                severity=FindingSeverity.SAFETY,
                subject_id=signal_group_id,
                witness={
                    "movement_ids": (movement_a_id, movement_b_id),
                    "conflict_id": conflict.conflict_id,
                },
                confidence=1.0,
            )
            findings[finding.finding_id] = finding

    for program in (
        entity for entity in snapshot.entities if entity.kind == "controller_program"
    ):
        for phase_index, phase in enumerate(program.payload.get("phases", ())):
            protected: set[str] = set()
            permissive: set[str] = set()
            for group_state in phase.get("group_states", ()):
                signal_group_id = str(group_state.get("signal_group_id", ""))
                group = signal_groups.get(signal_group_id)
                if group is None:
                    continue
                states = tuple(map(str, group_state.get("states", ())))
                movement_ids = set(map(str, group.payload.get("movement_ids", ())))
                if len(set(states)) > 1 or "?" in states:
                    finding = build_finding(
                        category="signal_group_phase_state_inconsistent",
                        severity=FindingSeverity.SAFETY,
                        subject_id=program.stable_entity_id,
                        witness={
                            "phase_index": phase_index,
                            "signal_group_id": signal_group_id,
                            "states": states,
                        },
                        confidence=1.0,
                    )
                    findings[finding.finding_id] = finding
                    continue
                state = states[0] if states else "?"
                if state == "G":
                    protected.update(movement_ids)
                elif state == "g":
                    permissive.update(movement_ids)
            for movement_a_id, movement_b_id in itertools.combinations(
                sorted(protected),
                2,
            ):
                conflict = conflict_index.get(frozenset((movement_a_id, movement_b_id)))
                if conflict is None:
                    continue
                protected_conflict_count += 1
                finding = build_finding(
                    category="protected_green_movement_conflict",
                    severity=FindingSeverity.SAFETY,
                    subject_id=program.stable_entity_id,
                    witness={
                        "phase_index": phase_index,
                        "movement_ids": (movement_a_id, movement_b_id),
                        "conflict_id": conflict.conflict_id,
                    },
                    confidence=1.0,
                )
                findings[finding.finding_id] = finding
            for permissive_id in sorted(permissive):
                for other_id in sorted((protected | permissive) - {permissive_id}):
                    if permissive_id >= other_id and other_id in permissive:
                        continue
                    conflict = conflict_index.get(frozenset((permissive_id, other_id)))
                    if conflict is None:
                        continue
                    permissive_without_yield_count += 1
                    finding = build_finding(
                        category="permissive_conflict_without_independent_yield_evidence",
                        severity=FindingSeverity.SAFETY,
                        subject_id=program.stable_entity_id,
                        witness={
                            "phase_index": phase_index,
                            "permissive_movement_id": permissive_id,
                            "conflicting_movement_id": other_id,
                            "conflict_id": conflict.conflict_id,
                        },
                        confidence=1.0,
                    )
                    findings[finding.finding_id] = finding

    if graph.geometry_missing_movement_ids:
        finding = build_finding(
            category="movement_geometry_missing_for_independent_safety",
            severity=FindingSeverity.SAFETY,
            subject_id=stable_id(
                "manifest",
                {"canonical_snapshot": snapshot.source_sha256 or "in-memory"},
            ),
            witness={
                "movement_ids": graph.geometry_missing_movement_ids,
            },
            confidence=1.0,
        )
        findings[finding.finding_id] = finding
    blockers = []
    if findings:
        blockers.append("independent_movement_safety_not_proven")
    status = GateStatus.BLOCKED if blockers else GateStatus.PASS
    return IndependentSafetyReport(
        status=status,
        automatic_promotion_gate=status,
        conflict_graph=graph,
        findings=tuple(findings[finding_id] for finding_id in sorted(findings)),
        protected_conflict_count=protected_conflict_count,
        permissive_without_yield_count=permissive_without_yield_count,
        shared_signal_group_conflict_count=shared_signal_group_conflict_count,
        blockers=tuple(blockers),
    )


class _MovementGeometry:
    def __init__(
        self,
        *,
        polylines: tuple[tuple[tuple[float, float], ...], ...],
        half_width_m: float,
        source_lane_role_id: str,
        destination_lane_role_id: str,
    ) -> None:
        self.polylines = polylines
        self.half_width_m = half_width_m
        self.source_lane_role_id = source_lane_role_id
        self.destination_lane_role_id = destination_lane_role_id


def _movement_geometry(
    movement: CanonicalEntity,
    entities: dict[tuple[str, str], CanonicalEntity],
) -> _MovementGeometry | None:
    variants = tuple(movement.payload.get("variants", ()))
    path_id = str(movement.payload.get("internal_path_id", ""))
    path_entity = entities.get(("internal_path", path_id))
    if not variants or path_entity is None:
        return None
    path_variants = tuple(path_entity.payload.get("path_variants", ()))
    polylines: list[tuple[tuple[float, float], ...]] = []
    widths: list[float] = []
    for path_variant in path_variants:
        path = path_variant.get("path", {})
        points: list[tuple[float, float]] = []
        for segment in path.get("segments", ()):
            shape = tuple(
                (float(point[0]), float(point[1]))
                for point in segment.get("shape_xy", ())
            )
            if not shape:
                continue
            if points and points[-1] == shape[0]:
                points.extend(shape[1:])
            else:
                points.extend(shape)
            width = segment.get("width_m")
            if isinstance(width, (int, float)) and width > 0:
                widths.append(float(width))
        if len(points) >= 2:
            polylines.append(tuple(points))
    if not polylines:
        return None
    first_variant = variants[0]
    return _MovementGeometry(
        polylines=tuple(polylines),
        half_width_m=(max(widths) / 2.0 if widths else 1.6),
        source_lane_role_id=str(first_variant.get("source_lane_role_id", "")),
        destination_lane_role_id=str(
            first_variant.get("destination_lane_role_id", "")
        ),
    )


def _geometry_conflict(
    first: _MovementGeometry,
    second: _MovementGeometry,
    *,
    envelope_margin_m: float,
) -> tuple[str, float, float | None] | None:
    if (
        first.source_lane_role_id
        and first.source_lane_role_id == second.source_lane_role_id
    ):
        return None
    minimum_distance = math.inf
    best_angle: float | None = None
    proper_intersection = False
    collinear_overlap = False
    for first_polyline in first.polylines:
        for second_polyline in second.polylines:
            for first_segment in _segments(first_polyline):
                for second_segment in _segments(second_polyline):
                    relation = _segment_relation(first_segment, second_segment)
                    distance = _segment_distance(first_segment, second_segment)
                    angle = _crossing_angle(first_segment, second_segment)
                    if distance < minimum_distance:
                        minimum_distance = distance
                        best_angle = angle
                    proper_intersection |= relation == "proper"
                    collinear_overlap |= relation == "collinear-overlap"
    if first.destination_lane_role_id == second.destination_lane_role_id:
        return ("shared-destination-merge", minimum_distance, best_angle)
    if proper_intersection:
        return ("centerline-crossing", minimum_distance, best_angle)
    if collinear_overlap:
        return ("collinear-path-overlap", minimum_distance, best_angle)
    envelope_distance = (
        first.half_width_m + second.half_width_m + envelope_margin_m
    )
    if (
        minimum_distance <= envelope_distance
        and best_angle is not None
        and best_angle >= 20.0
    ):
        return ("lane-envelope-proximity", minimum_distance, best_angle)
    return None


def _segments(
    polyline: tuple[tuple[float, float], ...],
) -> tuple[tuple[tuple[float, float], tuple[float, float]], ...]:
    return tuple(zip(polyline, polyline[1:], strict=False))


def _segment_relation(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> str:
    a, b = first
    c, d = second
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return "proper"
    if all(abs(value) <= 1e-9 for value in (o1, o2, o3, o4)):
        if _projection_overlap(a[0], b[0], c[0], d[0]) and _projection_overlap(
            a[1], b[1], c[1], d[1]
        ):
            return "collinear-overlap"
    return "none"


def _orientation(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (
        c[0] - a[0]
    )


def _projection_overlap(a: float, b: float, c: float, d: float) -> bool:
    return max(min(a, b), min(c, d)) < min(max(a, b), max(c, d)) - 1e-9


def _crossing_angle(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> float | None:
    first_vector = (
        first[1][0] - first[0][0],
        first[1][1] - first[0][1],
    )
    second_vector = (
        second[1][0] - second[0][0],
        second[1][1] - second[0][1],
    )
    first_length = math.hypot(*first_vector)
    second_length = math.hypot(*second_vector)
    if not first_length or not second_length:
        return None
    cosine = abs(
        (
            first_vector[0] * second_vector[0]
            + first_vector[1] * second_vector[1]
        )
        / (first_length * second_length)
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _segment_distance(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    if _segment_relation(first, second) in {"proper", "collinear-overlap"}:
        return 0.0
    return min(
        _point_segment_distance(first[0], second),
        _point_segment_distance(first[1], second),
        _point_segment_distance(second[0], first),
        _point_segment_distance(second[1], first),
    )


def _point_segment_distance(
    point: tuple[float, float],
    segment: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    start, end = segment
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator == 0:
        return math.dist(point, start)
    ratio = (
        (point[0] - start[0]) * dx + (point[1] - start[1]) * dy
    ) / denominator
    ratio = max(0.0, min(1.0, ratio))
    projection = (start[0] + ratio * dx, start[1] + ratio * dy)
    return math.dist(point, projection)

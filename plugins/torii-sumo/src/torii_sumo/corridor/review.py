from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import model_validator

from .base import ContractModel, Sha256, StableToken
from .enums import ReviewDecisionStatus
from .ids import require_stable_id, stable_id


class PedestrianCrossingReviewSubject(ContractModel):
    """Stable, raw-ID-free subject for one unmodeled pedestrian crossing."""

    schema_id: str = "torii.corridor.pedestrian-crossing-review-subject/v1"
    review_subject_id: StableToken
    facility_kind: Literal["pedestrian-crossing"]
    control_kind: Literal["signalized", "uncontrolled"]
    crossing_shape_xy: tuple[tuple[float, float], ...]
    crossing_width_m: float | None
    source_endpoint_shape_xy: tuple[tuple[float, float], ...]
    destination_endpoint_shape_xy: tuple[tuple[float, float], ...]
    crossed_edge_signatures: tuple[StableToken, ...]
    position_xy: tuple[float, float] | None
    physical_cell_id: StableToken | None
    boundary_port_ids: tuple[StableToken, ...]
    permission_contract: dict[str, Any]
    rejection_reasons: tuple[str, ...]
    machine_question: str
    required_observations: tuple[str, ...]

    @model_validator(mode="after")
    def validate_subject(self) -> PedestrianCrossingReviewSubject:
        require_stable_id(self.review_subject_id, kind="review")
        if self.physical_cell_id is not None:
            require_stable_id(self.physical_cell_id, kind="cell")
        for port_id in self.boundary_port_ids:
            require_stable_id(port_id, kind="port")
        for signature in self.crossed_edge_signatures:
            require_stable_id(signature, kind="signature")
        points = (
            *self.crossing_shape_xy,
            *self.source_endpoint_shape_xy,
            *self.destination_endpoint_shape_xy,
        )
        if self.position_xy is not None:
            points = (*points, self.position_xy)
        if any(not math.isfinite(coordinate) for point in points for coordinate in point):
            raise ValueError("Pedestrian review geometry must be finite.")
        if self.crossing_width_m is not None and (
            not math.isfinite(self.crossing_width_m)
            or self.crossing_width_m <= 0
        ):
            raise ValueError("Pedestrian review width must be positive and finite.")
        if not self.rejection_reasons or not self.required_observations:
            raise ValueError(
                "Pedestrian review subjects require rejection reasons and observations."
            )
        semantic_subject = {
            "facility_kind": self.facility_kind,
            "control_kind": self.control_kind,
            "crossing_shape_xy": self.crossing_shape_xy,
            "crossing_width_m": self.crossing_width_m,
            "source_endpoint_shape_xy": self.source_endpoint_shape_xy,
            "destination_endpoint_shape_xy": self.destination_endpoint_shape_xy,
            "crossed_edge_signatures": self.crossed_edge_signatures,
        }
        expected_id = stable_id("review", semantic_subject)
        if self.review_subject_id != expected_id:
            raise ValueError(
                "Pedestrian review subject ID does not match its semantic identity."
            )
        return self


class ReviewTask(ContractModel):
    review_task_id: StableToken
    exact_question: str
    variant_ids: tuple[StableToken, ...]
    required_observations: tuple[str, ...]
    evidence_refs: tuple[StableToken, ...]
    affected_stable_entity_ids: tuple[StableToken, ...]

    @model_validator(mode="after")
    def validate_task(self) -> ReviewTask:
        require_stable_id(self.review_task_id, kind="review")
        if not self.variant_ids or not self.required_observations:
            raise ValueError("Review tasks require variants and required observations.")
        for variant_id in self.variant_ids:
            require_stable_id(variant_id, kind="candidate")
        for evidence_ref in self.evidence_refs:
            require_stable_id(evidence_ref, kind="evidence")
        for entity_id in self.affected_stable_entity_ids:
            require_stable_id(entity_id)
        return self


class ReviewCase(ContractModel):
    review_case_id: StableToken
    source_sha256: Sha256
    candidate_sha256_by_variant: dict[StableToken, Sha256]
    scope_id: StableToken
    finding_ids: tuple[StableToken, ...]
    affected_stable_entity_ids: tuple[StableToken, ...]
    decision_type: str
    machine_question: str
    candidate_variant_ids: tuple[StableToken, ...]
    machine_recommendation: StableToken | None = None
    confidence_components: dict[str, float]
    passed_gates: tuple[str, ...]
    unresolved_gates: tuple[str, ...]
    evidence_refs: tuple[StableToken, ...]
    required_observations: tuple[str, ...]
    rollback_artifact_id: StableToken
    status: str = "pending"

    @model_validator(mode="after")
    def validate_case(self) -> ReviewCase:
        require_stable_id(self.review_case_id, kind="review")
        require_stable_id(self.scope_id, kind="scope")
        variants = set(self.candidate_variant_ids)
        if not variants:
            raise ValueError("Review cases require at least one candidate variant.")
        if variants != set(self.candidate_sha256_by_variant):
            raise ValueError("Every review variant must have exactly one candidate hash.")
        for variant_id in variants:
            require_stable_id(variant_id, kind="candidate")
        if self.machine_recommendation is not None:
            require_stable_id(self.machine_recommendation, kind="candidate")
            if self.machine_recommendation not in variants:
                raise ValueError("Machine recommendation must reference a review variant.")
        for finding_id in self.finding_ids:
            require_stable_id(finding_id, kind="finding")
        for entity_id in self.affected_stable_entity_ids:
            require_stable_id(entity_id)
        for evidence_ref in self.evidence_refs:
            require_stable_id(evidence_ref, kind="evidence")
        require_stable_id(self.rollback_artifact_id, kind="artifact")
        if not self.required_observations:
            raise ValueError("Review cases must state the observations needed for a decision.")
        return self


class ReviewDecision(ContractModel):
    review_case_id: StableToken
    variant_id: StableToken
    candidate_sha256: Sha256
    decision: ReviewDecisionStatus
    reviewer: str
    decided_at: datetime
    finding_decisions: dict[StableToken, ReviewDecisionStatus]
    observed_facts: tuple[str, ...]
    rationale: str
    evidence_refs: tuple[StableToken, ...]
    rollback_artifact_id: StableToken
    source_and_toolchain_fresh: bool

    @model_validator(mode="after")
    def validate_decision(self) -> ReviewDecision:
        require_stable_id(self.review_case_id, kind="review")
        require_stable_id(self.variant_id, kind="candidate")
        require_stable_id(self.rollback_artifact_id, kind="artifact")
        if self.decided_at.tzinfo is None:
            raise ValueError("Review decisions require a timezone-aware timestamp.")
        for finding_id in self.finding_decisions:
            require_stable_id(finding_id, kind="finding")
        for evidence_ref in self.evidence_refs:
            require_stable_id(evidence_ref, kind="evidence")
        if self.decision in {
            ReviewDecisionStatus.ACCEPTED,
            ReviewDecisionStatus.REJECTED,
        }:
            if not self.observed_facts or not self.rationale:
                raise ValueError("Final review decisions require observed facts and rationale.")
            if not self.source_and_toolchain_fresh:
                raise ValueError("Stale source or toolchain invalidates a final review decision.")
        return self

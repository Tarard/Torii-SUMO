from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .base import ContractModel, Sha256, StableToken
from .enums import GateStatus, TrafficSide
from .held_out_corpus_contracts import HeldOutCorridorSelection, Morphology
from .ids import require_stable_id, stable_id
from .run_identity import CodeProducerIdentity


AttentionLabel = Literal["attention-required", "acceptable", "ambiguous"]
ReplacementFailureReason = Literal[
    "source-artifact-unavailable",
    "bbox-outside-frozen-extract",
    "source-extraction-failed",
    "netconvert-build-failed",
    "semantic-replay-invalid",
    "artifact-closure-incomplete",
]

_REQUIRED_REPLACEMENT_MATCH_FIELDS = (
    "city_source_id",
    "morphology",
    "traffic_side",
    "mode_features",
)
_PROHIBITED_REPLACEMENT_SIGNALS = (
    "machine_label",
    "finding_count",
    "finding_severity",
    "human_decision",
    "reviewer_visibility",
)
_ALLOWED_REPLACEMENT_FAILURE_REASONS = (
    "source-artifact-unavailable",
    "bbox-outside-frozen-extract",
    "source-extraction-failed",
    "netconvert-build-failed",
    "semantic-replay-invalid",
    "artifact-closure-incomplete",
)


class ReplacementStratumV2(ContractModel):
    city_source_id: str
    morphology: Morphology
    traffic_side: TrafficSide
    mode_features: tuple[str, ...]

    @model_validator(mode="after")
    def validate_stratum(self) -> ReplacementStratumV2:
        if self.traffic_side is TrafficSide.UNKNOWN:
            raise ValueError("Replacement strata require an explicit traffic side.")
        if not self.city_source_id or not self.mode_features:
            raise ValueError("Replacement strata require source and mode features.")
        if len(self.mode_features) != len(set(self.mode_features)):
            raise ValueError("Replacement mode features must be unique.")
        return self


class ReserveCorridorCandidateV2(ContractModel):
    selection: HeldOutCorridorSelection
    traffic_side: TrafficSide
    preregistered_before_machine_execution: Literal[True] = True
    selection_uses_machine_output: Literal[False] = False

    @model_validator(mode="after")
    def validate_candidate(self) -> ReserveCorridorCandidateV2:
        if self.traffic_side is TrafficSide.UNKNOWN:
            raise ValueError("Reserve candidates require an explicit traffic side.")
        return self


class ReserveReplacementSlotV2(ContractModel):
    invalid_corridor_key: str
    invalid_selection_id: StableToken
    invalid_reason: Literal["semantic-replay-invalid"]
    required_stratum: ReplacementStratumV2
    candidates: tuple[ReserveCorridorCandidateV2, ...]

    @model_validator(mode="after")
    def validate_slot(self) -> ReserveReplacementSlotV2:
        require_stable_id(self.invalid_selection_id, kind="scope")
        if len(self.candidates) < 2:
            raise ValueError("Every replacement slot requires a reserve queue.")
        keys = [candidate.selection.corridor_key for candidate in self.candidates]
        ids = [candidate.selection.selection_id for candidate in self.candidates]
        if len(keys) != len(set(keys)) or len(ids) != len(set(ids)):
            raise ValueError("Reserve candidates must have unique identities.")
        for candidate in self.candidates:
            selection = candidate.selection
            if selection.city_source_id != self.required_stratum.city_source_id:
                raise ValueError("Reserve city source does not match replacement slot.")
            if selection.morphology != self.required_stratum.morphology:
                raise ValueError("Reserve morphology does not match replacement slot.")
            if candidate.traffic_side is not self.required_stratum.traffic_side:
                raise ValueError("Reserve traffic side does not match replacement slot.")
            if selection.preregistered_feature_targets != self.required_stratum.mode_features:
                raise ValueError("Reserve mode features do not match replacement slot.")
        return self


class HeldOutReserveCorpusV2(ContractModel):
    schema_id: str = "torii.corridor.held-out-reserve-corpus/v2"
    reserve_corpus_id: StableToken
    parent_corpus_sha256: Sha256
    frozen_before_replacement_execution: Literal[True] = True
    selection_independent_of_machine_results: Literal[True] = True
    provider_attribution: Literal["© OpenStreetMap contributors"]
    slots: tuple[ReserveReplacementSlotV2, ...]
    automatic_promotion_gate: GateStatus = GateStatus.BLOCKED

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"reserve_corpus_id"},
        )

    @model_validator(mode="after")
    def validate_corpus(self) -> HeldOutReserveCorpusV2:
        require_stable_id(self.reserve_corpus_id, kind="manifest")
        if self.automatic_promotion_gate is not GateStatus.BLOCKED:
            raise ValueError("A reserve corpus cannot authorize promotion.")
        keys = [slot.invalid_corridor_key for slot in self.slots]
        if not keys or keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("Reserve slots must be non-empty, sorted, and unique.")
        candidate_ids = [candidate.selection.selection_id for slot in self.slots for candidate in slot.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Reserve candidate IDs must be globally unique.")
        if self.reserve_corpus_id != stable_id("manifest", self.identity_payload()):
            raise ValueError("Reserve corpus ID does not match frozen content.")
        return self


class HeldOutReplacementPolicyV2(ContractModel):
    schema_id: str = "torii.corridor.held-out-replacement-policy/v2"
    policy_id: StableToken
    parent_corpus_sha256: Sha256
    reserve_corpus_sha256: Sha256
    public_selection_seed: str = Field(min_length=32)
    ranking_algorithm: Literal["sha256(seed|invalid-corridor-key|selection-id)-ascending"]
    required_match_fields: tuple[str, ...]
    allowed_technical_failure_reasons: tuple[ReplacementFailureReason, ...]
    prohibited_selection_signals: tuple[str, ...]
    failed_attempts_are_retained: Literal[True] = True
    fallback_requires_prior_failure_record: Literal[True] = True
    replay_invalid_excluded_from_quality_denominator: Literal[True] = True
    minimum_complete_replacement_count: Literal[3] = 3
    automatic_promotion_gate: GateStatus = GateStatus.BLOCKED

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True, exclude={"policy_id"})

    @model_validator(mode="after")
    def validate_policy(self) -> HeldOutReplacementPolicyV2:
        require_stable_id(self.policy_id, kind="policy")
        if self.required_match_fields != _REQUIRED_REPLACEMENT_MATCH_FIELDS:
            raise ValueError("Replacement matching fields are not the frozen tuple.")
        if self.allowed_technical_failure_reasons != _ALLOWED_REPLACEMENT_FAILURE_REASONS:
            raise ValueError("Replacement failure reasons are not the frozen tuple.")
        if self.prohibited_selection_signals != _PROHIBITED_REPLACEMENT_SIGNALS:
            raise ValueError("Replacement prohibited signals are not frozen.")
        if self.automatic_promotion_gate is not GateStatus.BLOCKED:
            raise ValueError("Replacement selection cannot authorize promotion.")
        if self.policy_id != stable_id("policy", self.identity_payload()):
            raise ValueError("Replacement policy ID does not match frozen content.")
        return self


class RankedReserveCandidateV2(ContractModel):
    rank: int = Field(ge=1)
    corridor_key: str
    selection_id: StableToken
    ranking_digest: Sha256

    @model_validator(mode="after")
    def validate_candidate(self) -> RankedReserveCandidateV2:
        require_stable_id(self.selection_id, kind="scope")
        return self


class ReplacementSlotPlanV2(ContractModel):
    invalid_corridor_key: str
    invalid_selection_id: StableToken
    ordered_candidates: tuple[RankedReserveCandidateV2, ...]

    @model_validator(mode="after")
    def validate_plan(self) -> ReplacementSlotPlanV2:
        require_stable_id(self.invalid_selection_id, kind="scope")
        ranks = [candidate.rank for candidate in self.ordered_candidates]
        if not ranks or ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("Replacement candidate ranks must be contiguous.")
        digests = [candidate.ranking_digest for candidate in self.ordered_candidates]
        if digests != sorted(digests) or len(digests) != len(set(digests)):
            raise ValueError("Replacement candidates must follow unique digest order.")
        return self


class HeldOutReplacementPlanV2(ContractModel):
    schema_id: str = "torii.corridor.held-out-replacement-plan/v2"
    replacement_plan_id: StableToken
    reserve_corpus_sha256: Sha256
    replacement_policy_sha256: Sha256
    slots: tuple[ReplacementSlotPlanV2, ...]
    machine_labels_consulted: Literal[False] = False
    human_decisions_consulted: Literal[False] = False
    automatic_promotion_gate: GateStatus = GateStatus.BLOCKED

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"replacement_plan_id"},
        )

    @model_validator(mode="after")
    def validate_plan(self) -> HeldOutReplacementPlanV2:
        require_stable_id(self.replacement_plan_id, kind="manifest")
        keys = [slot.invalid_corridor_key for slot in self.slots]
        if not keys or keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("Replacement plan slots must be sorted and unique.")
        if self.automatic_promotion_gate is not GateStatus.BLOCKED:
            raise ValueError("Replacement plans cannot authorize promotion.")
        if self.replacement_plan_id != stable_id("manifest", self.identity_payload()):
            raise ValueError("Replacement plan ID does not match its queues.")
        return self


class HeldOutSourceSnapshotProtocolV2(ContractModel):
    schema_id: str = "torii.corridor.held-out-source-snapshot-protocol/v2"
    protocol_id: StableToken
    reference_complete_writer: Literal[True] = True
    referenced_node_tags_retained: Literal[True] = True
    closed_restriction_relations_only: Literal[True] = True
    touched_roundabout_component_closure: Literal[True] = True
    roundabout_component_connectivity: Literal["shared-osm-node"] = "shared-osm-node"
    disconnected_roundabout_components_excluded: Literal[True] = True
    frozen_v1_snapshots_rewritten: Literal[False] = False
    automatic_promotion_gate: GateStatus = GateStatus.BLOCKED

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True, exclude={"protocol_id"})

    @model_validator(mode="after")
    def validate_protocol(self) -> HeldOutSourceSnapshotProtocolV2:
        require_stable_id(self.protocol_id, kind="policy")
        if self.automatic_promotion_gate is not GateStatus.BLOCKED:
            raise ValueError("Source snapshot protocols cannot authorize promotion.")
        if self.protocol_id != stable_id("policy", self.identity_payload()):
            raise ValueError("Source snapshot protocol ID does not match its content.")
        return self


class ReplacementEvidenceArtifactV2(ContractModel):
    role: Literal[
        "source-snapshot",
        "run-identity",
        "machine-report",
        "net-replay-report",
        "machine-manifest",
    ]
    path: str
    sha256: Sha256

    @model_validator(mode="after")
    def validate_path(self) -> ReplacementEvidenceArtifactV2:
        normalized = self.path.replace("\\", "/")
        if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("Replacement evidence paths must be safe and relative.")
        return self


class ReplacementAttemptV2(ContractModel):
    attempt_id: StableToken
    invalid_corridor_key: str
    rank: int = Field(ge=1)
    corridor_key: str
    selection_id: StableToken
    source_snapshot_protocol_sha256: Sha256
    producer: CodeProducerIdentity
    snapshot_status: GateStatus
    semantic_replay_status: GateStatus
    artifact_closure_complete: bool
    technical_outcome: Literal["eligible", "failed"]
    failure_reason: ReplacementFailureReason | None = None
    artifacts: tuple[ReplacementEvidenceArtifactV2, ...]
    machine_labels_consulted: Literal[False] = False
    finding_counts_consulted: Literal[False] = False
    finding_severity_consulted: Literal[False] = False
    human_decisions_consulted: Literal[False] = False
    reviewer_visibility_consulted: Literal[False] = False

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True, exclude={"attempt_id"})

    @model_validator(mode="after")
    def validate_attempt(self) -> ReplacementAttemptV2:
        require_stable_id(self.attempt_id, kind="manifest")
        require_stable_id(self.selection_id, kind="scope")
        roles = [item.role for item in self.artifacts]
        required_roles = {
            "source-snapshot",
            "run-identity",
            "machine-report",
            "net-replay-report",
            "machine-manifest",
        }
        if set(roles) != required_roles or len(roles) != len(set(roles)):
            raise ValueError("Replacement attempts require one artifact per frozen role.")
        if self.technical_outcome == "eligible":
            if (
                self.snapshot_status is not GateStatus.PASS
                or self.semantic_replay_status is not GateStatus.PASS
                or not self.artifact_closure_complete
                or self.failure_reason is not None
            ):
                raise ValueError("Eligible replacements must close every technical gate.")
        elif self.failure_reason is None:
            raise ValueError("Failed replacement attempts require a technical reason.")
        if self.attempt_id != stable_id("manifest", self.identity_payload()):
            raise ValueError("Replacement attempt ID does not match frozen evidence.")
        return self


class ReplacementSlotAttemptLedgerV2(ContractModel):
    invalid_corridor_key: str
    invalid_selection_id: StableToken
    attempts: tuple[ReplacementAttemptV2, ...]
    selected_rank: int = Field(ge=1)
    selected_corridor_key: str
    selected_selection_id: StableToken
    resolution_status: Literal["technical-pass"] = "technical-pass"

    @model_validator(mode="after")
    def validate_slot(self) -> ReplacementSlotAttemptLedgerV2:
        require_stable_id(self.invalid_selection_id, kind="scope")
        require_stable_id(self.selected_selection_id, kind="scope")
        ranks = [item.rank for item in self.attempts]
        if not ranks or ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("Replacement attempts must be a contiguous rank prefix.")
        if self.selected_rank != len(self.attempts):
            raise ValueError("Selection must be the final attempted rank.")
        selected = self.attempts[-1]
        if selected.technical_outcome != "eligible":
            raise ValueError("A resolved replacement slot must end in an eligible attempt.")
        if any(item.technical_outcome != "failed" for item in self.attempts[:-1]):
            raise ValueError("Every fallback requires all prior ranks to fail.")
        if selected.corridor_key != self.selected_corridor_key or selected.selection_id != self.selected_selection_id:
            raise ValueError("Selected replacement identity does not match final attempt.")
        if any(item.invalid_corridor_key != self.invalid_corridor_key for item in self.attempts):
            raise ValueError("Replacement slot attempts target different invalid cases.")
        return self


class SupersededReplacementExecutionV2(ContractModel):
    source_snapshot_protocol: Literal["bbox-intersection-without-roundabout-closure"]
    reason: Literal["source-snapshot-protocol-superseded"]
    machine_report_sha256s: tuple[Sha256, ...]
    eligible_for_current_selection: Literal[False] = False


class HeldOutReplacementAttemptLedgerV2(ContractModel):
    schema_id: str = "torii.corridor.held-out-replacement-attempt-ledger/v2"
    ledger_id: StableToken
    base_corpus_sha256: Sha256
    reserve_corpus_sha256: Sha256
    replacement_plan_sha256: Sha256
    source_snapshot_protocol_sha256: Sha256
    effective_corpus_sha256: Sha256
    slots: tuple[ReplacementSlotAttemptLedgerV2, ...]
    superseded_executions: tuple[SupersededReplacementExecutionV2, ...] = ()
    minimum_complete_replacement_count: Literal[3] = 3
    machine_labels_consulted: Literal[False] = False
    human_decisions_consulted: Literal[False] = False
    automatic_promotion_gate: GateStatus = GateStatus.BLOCKED

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True, exclude={"ledger_id"})

    @model_validator(mode="after")
    def validate_ledger(self) -> HeldOutReplacementAttemptLedgerV2:
        require_stable_id(self.ledger_id, kind="manifest")
        keys = [slot.invalid_corridor_key for slot in self.slots]
        if (
            len(self.slots) < self.minimum_complete_replacement_count
            or keys != sorted(keys)
            or len(keys) != len(set(keys))
        ):
            raise ValueError("Replacement ledger does not close its frozen slots.")
        if self.automatic_promotion_gate is not GateStatus.BLOCKED:
            raise ValueError("Replacement evidence cannot authorize promotion.")
        if self.ledger_id != stable_id("manifest", self.identity_payload()):
            raise ValueError("Replacement ledger ID does not match frozen attempts.")
        return self


class ReviewWitnessSamplingPolicyV2(ContractModel):
    schema_id: str = "torii.corridor.review-witness-sampling-policy/v2"
    policy_id: StableToken
    rwc_policy_id: StableToken
    rwc_sampling_seed_sha256: Sha256
    atomic_membership_coverage_required: Literal[1.0] = 1.0
    lost_witness_maximum: Literal[0] = 0
    duplicate_witness_maximum: Literal[0] = 0
    hard_key_mixing_maximum: Literal[0] = 0
    rare_hard_ood_census_required: Literal[True] = True
    negative_pair_sampling_required: Literal[True] = True
    inclusion_probability_required: Literal[True] = True
    visible_medoid_and_extrema_required: Literal[True] = True
    hidden_random_member_required: Literal[True] = True
    cluster_decision_propagation_requires_purity: Literal[True] = True
    estimator: Literal["horvitz-thompson"] = "horvitz-thompson"
    confidence_method: Literal["wilson-one-sided"] = "wilson-one-sided"
    confidence_level: Literal[0.95] = 0.95
    maximum_hidden_member_disagreement_upper_bound: Literal[0.05] = 0.05
    maximum_safety_critical_hidden_heterogeneity: Literal[0] = 0
    automatic_promotion_gate: GateStatus = GateStatus.BLOCKED

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True, exclude={"policy_id"})

    @model_validator(mode="after")
    def validate_policy(self) -> ReviewWitnessSamplingPolicyV2:
        require_stable_id(self.policy_id, kind="policy")
        require_stable_id(self.rwc_policy_id, kind="policy")
        if self.automatic_promotion_gate is not GateStatus.BLOCKED:
            raise ValueError("Sampling policy cannot authorize promotion.")
        if self.policy_id != stable_id("policy", self.identity_payload()):
            raise ValueError("Sampling policy ID does not match frozen content.")
        return self


class HeldOutReviewParentV2(ContractModel):
    schema_id: str = "torii.corridor.held-out-review-parent/v2"
    parent_id: StableToken
    base_benchmark_sha256: Sha256
    held_out_corpus_v1_sha256: Sha256
    reserve_corpus_sha256: Sha256
    replacement_policy_sha256: Sha256
    sampling_policy_sha256: Sha256
    lossless_compression_schema_sha256: Sha256
    frozen: Literal[True] = True
    review_ready_is_not_stage1_exit: Literal[True] = True
    automatic_promotion_gate: GateStatus = GateStatus.BLOCKED

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True, exclude={"parent_id"})

    @model_validator(mode="after")
    def validate_parent(self) -> HeldOutReviewParentV2:
        require_stable_id(self.parent_id, kind="manifest")
        if self.automatic_promotion_gate is not GateStatus.BLOCKED:
            raise ValueError("Review parent cannot authorize promotion.")
        if self.parent_id != stable_id("manifest", self.identity_payload()):
            raise ValueError("Review parent ID does not match frozen content.")
        return self


class AuditAttentionCohortPolicyV2(ContractModel):
    cohort: Literal["audit-attention"] = "audit-attention"
    minimum_valid_corridor_packages: Literal[30] = 30
    minimum_raw_agreement: Literal[0.8] = 0.8
    minimum_cohen_kappa: Literal[0.6] = 0.6
    minimum_weighted_attention_precision: Literal[0.9] = 0.9
    minimum_weighted_attention_recall: Literal[0.95] = 0.95
    maximum_median_review_seconds: Literal[300.0] = 300.0
    maximum_safety_critical_false_negatives: Literal[0] = 0
    auto_precision_status: Literal["not-applicable"] = "not-applicable"
    finding_cluster_decisions_required: Literal[True] = True
    negative_units_required_for_recall: Literal[True] = True


class ProspectiveSafePassCohortPolicyV2(ContractModel):
    cohort: Literal["prospective-safe-pass"] = "prospective-safe-pass"
    enrollment: Literal["all-consecutive-machine-acceptable"] = "all-consecutive-machine-acceptable"
    retrospective_enrollment_forbidden: Literal[True] = True
    current_defect_only_corpus_eligible: Literal[False] = False
    minimum_machine_acceptable_count: Literal[600] = 600
    minimum_auto_precision_point_estimate: Literal[0.99] = 0.99
    minimum_auto_precision_one_sided_lower_bound: Literal[0.99] = 0.99
    confidence_method: Literal["wilson-one-sided"] = "wilson-one-sided"
    confidence_level: Literal[0.95] = 0.95
    auto_coverage_minimum: None = None
    maximum_safety_critical_false_negatives: Literal[0] = 0


class HeldOutReviewPolicyV2(ContractModel):
    schema_id: str = "torii.corridor.held-out-review-policy/v2"
    trial_id: StableToken
    parent_review_benchmark_sha256: Sha256
    reserve_corpus_sha256: Sha256
    replacement_policy_sha256: Sha256
    sampling_policy_sha256: Sha256
    blinding_seed_sha256: Sha256
    reviewer_ids: tuple[StableToken, StableToken]
    adjudicator_id: StableToken
    replay_invalid_corridor_keys: tuple[str, ...]
    audit_attention: AuditAttentionCohortPolicyV2
    prospective_safe_pass: ProspectiveSafePassCohortPolicyV2
    stage_1m_machine_milestone_only: Literal[True] = True
    stage_1_exit_requires_human_validation: Literal[True] = True
    machine_assessments_are_immutable_after_freeze: Literal[True] = True
    automatic_promotion_gate: GateStatus = GateStatus.BLOCKED

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True, exclude={"trial_id"})

    @model_validator(mode="after")
    def validate_policy(self) -> HeldOutReviewPolicyV2:
        require_stable_id(self.trial_id, kind="review")
        if len(set(self.reviewer_ids)) != 2:
            raise ValueError("V2 review requires two distinct reviewers.")
        for reviewer_id in self.reviewer_ids:
            require_stable_id(reviewer_id, kind="review")
        require_stable_id(self.adjudicator_id, kind="review")
        if self.adjudicator_id in self.reviewer_ids:
            raise ValueError("V2 adjudicator must be independent.")
        if not self.replay_invalid_corridor_keys or self.replay_invalid_corridor_keys != tuple(
            sorted(set(self.replay_invalid_corridor_keys))
        ):
            raise ValueError("Replay-invalid keys must be sorted and unique.")
        if self.automatic_promotion_gate is not GateStatus.BLOCKED:
            raise ValueError("Stage 1-M policy must keep promotion blocked.")
        if self.trial_id != stable_id("review", self.identity_payload()):
            raise ValueError("V2 trial ID does not match frozen policy content.")
        return self


class ClusterMachineAssessmentV2(ContractModel):
    schema_id: str = "torii.corridor.cluster-machine-assessment/v2"
    review_unit_id: StableToken
    unit_kind: Literal["conflict-cluster", "negative-pair"]
    machine_attention: bool
    safety_critical: bool
    inclusion_probability: float = Field(gt=0.0, le=1.0)
    membership_root: Sha256
    evidence_artifact_sha256: Sha256
    finding_categories: tuple[str, ...]

    @model_validator(mode="after")
    def validate_assessment(self) -> ClusterMachineAssessmentV2:
        require_stable_id(self.review_unit_id, kind="review")
        if self.unit_kind == "conflict-cluster" and not self.machine_attention:
            raise ValueError("Conflict clusters are machine-attention units.")
        if self.unit_kind == "negative-pair" and self.machine_attention:
            raise ValueError("Negative-pair samples are non-attention units.")
        return self


class BlindedClusterReviewUnitV2(ContractModel):
    unit_code: str = Field(pattern=r"^unit-[0-9a-f]{12}$")
    witness_codes: tuple[str, ...]
    exact_question: str
    required_observations: tuple[str, ...]
    evidence_path: str

    @model_validator(mode="after")
    def validate_unit(self) -> BlindedClusterReviewUnitV2:
        if not self.witness_codes or len(self.witness_codes) != len(set(self.witness_codes)):
            raise ValueError("Blinded witness codes must be non-empty and unique.")
        if any(not code.startswith("witness-") or len(code) != 20 for code in self.witness_codes):
            raise ValueError("Invalid blinded witness code.")
        if not self.exact_question or not self.required_observations:
            raise ValueError("Cluster review units require a question and observations.")
        normalized = self.evidence_path.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("Cluster evidence path must be safe and relative.")
        return self


class BlindedAttentionCaseV2(ContractModel):
    case_code: str = Field(pattern=r"^case-[0-9a-f]{12}$")
    city_group: str
    morphology: Morphology
    traffic_side: TrafficSide
    mode_features: tuple[str, ...]
    review_material_path: str
    units: tuple[BlindedClusterReviewUnitV2, ...]

    @model_validator(mode="after")
    def validate_case(self) -> BlindedAttentionCaseV2:
        if self.traffic_side is TrafficSide.UNKNOWN:
            raise ValueError("Blinded attention cases require a traffic side.")
        if not self.city_group or not self.mode_features or not self.units:
            raise ValueError("Blinded attention cases require strata and units.")
        unit_codes = [unit.unit_code for unit in self.units]
        if len(unit_codes) != len(set(unit_codes)):
            raise ValueError("Blinded attention unit codes must be unique per case.")
        normalized = self.review_material_path.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("Review material path must be safe and relative.")
        return self


class BlindedAttentionDatasetV2(ContractModel):
    schema_id: str = "torii.corridor.blinded-attention-dataset/v2"
    trial_id: StableToken
    created_at: datetime
    machine_labels_hidden: Literal[True] = True
    peer_decisions_hidden: Literal[True] = True
    hidden_member_roles_hidden: Literal[True] = True
    cases: tuple[BlindedAttentionCaseV2, ...]

    @model_validator(mode="after")
    def validate_dataset(self) -> BlindedAttentionDatasetV2:
        require_stable_id(self.trial_id, kind="review")
        if self.created_at.tzinfo is None:
            raise ValueError("Blinded attention dataset requires a timezone.")
        case_codes = [case.case_code for case in self.cases]
        if not case_codes or len(case_codes) != len(set(case_codes)):
            raise ValueError("Blinded attention case codes must be unique.")
        all_unit_codes = [unit.unit_code for case in self.cases for unit in case.units]
        if len(all_unit_codes) != len(set(all_unit_codes)):
            raise ValueError("Blinded attention unit codes must be globally unique.")
        return self


class ClusterUnitUnblindingKeyV2(ContractModel):
    case_code: str = Field(pattern=r"^case-[0-9a-f]{12}$")
    unit_code: str = Field(pattern=r"^unit-[0-9a-f]{12}$")
    review_unit_id: StableToken
    witness_id_by_code: dict[str, StableToken]
    hidden_witness_code: str | None
    machine_assessment: ClusterMachineAssessmentV2
    machine_assessment_artifact_path: str
    machine_assessment_artifact_sha256: Sha256

    @model_validator(mode="after")
    def validate_key(self) -> ClusterUnitUnblindingKeyV2:
        require_stable_id(self.review_unit_id, kind="review")
        if self.machine_assessment.review_unit_id != self.review_unit_id:
            raise ValueError("Cluster assessment and key unit IDs differ.")
        for code, witness_id in self.witness_id_by_code.items():
            if not code.startswith("witness-") or len(code) != 20:
                raise ValueError("Invalid blinded witness code in key.")
            require_stable_id(witness_id, kind="conflict")
        if self.hidden_witness_code is not None and self.hidden_witness_code not in self.witness_id_by_code:
            raise ValueError("Hidden witness code is absent from the unit key.")
        normalized = self.machine_assessment_artifact_path.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("Assessment artifact path must be safe and relative.")
        return self


class AttentionEvaluationKeyV2(ContractModel):
    schema_id: str = "torii.corridor.attention-evaluation-key/v2"
    trial_id: StableToken
    blinded_dataset_sha256: Sha256
    blinding_seed: str = Field(min_length=32)
    units: tuple[ClusterUnitUnblindingKeyV2, ...]

    @model_validator(mode="after")
    def validate_key(self) -> AttentionEvaluationKeyV2:
        require_stable_id(self.trial_id, kind="review")
        unit_codes = [unit.unit_code for unit in self.units]
        if not unit_codes or len(unit_codes) != len(set(unit_codes)):
            raise ValueError("Attention evaluation unit codes must be unique.")
        return self


class ClusterReviewDecisionV2(ContractModel):
    schema_id: str = "torii.corridor.cluster-review-decision/v2"
    decision_id: StableToken
    trial_id: StableToken
    case_code: str = Field(pattern=r"^case-[0-9a-f]{12}$")
    unit_code: str = Field(pattern=r"^unit-[0-9a-f]{12}$")
    reviewer_id: StableToken
    label: AttentionLabel
    witness_labels: dict[str, AttentionLabel]
    cluster_purity_supported: bool
    started_at: datetime
    decided_at: datetime
    observed_facts: tuple[str, ...]
    rationale: str
    machine_label_was_hidden: Literal[True] = True
    peer_decision_was_hidden: Literal[True] = True
    hidden_member_role_was_hidden: Literal[True] = True

    @property
    def duration_seconds(self) -> float:
        return (self.decided_at - self.started_at).total_seconds()

    @model_validator(mode="after")
    def validate_decision(self) -> ClusterReviewDecisionV2:
        require_stable_id(self.decision_id, kind="review")
        require_stable_id(self.trial_id, kind="review")
        require_stable_id(self.reviewer_id, kind="review")
        if self.started_at.tzinfo is None or self.decided_at.tzinfo is None:
            raise ValueError("Cluster review timestamps require timezones.")
        if self.decided_at <= self.started_at:
            raise ValueError("Cluster review end must follow start.")
        if not self.witness_labels or not self.observed_facts or not self.rationale:
            raise ValueError("Cluster review requires witness decisions and rationale.")
        return self


class ClusterReviewAdjudicationV2(ContractModel):
    schema_id: str = "torii.corridor.cluster-review-adjudication/v2"
    adjudication_id: StableToken
    trial_id: StableToken
    case_code: str = Field(pattern=r"^case-[0-9a-f]{12}$")
    unit_code: str = Field(pattern=r"^unit-[0-9a-f]{12}$")
    reviewer_decision_ids: tuple[StableToken, StableToken]
    adjudicator_id: StableToken
    final_label: AttentionLabel
    witness_labels: dict[str, AttentionLabel]
    cluster_purity_supported: bool
    decided_at: datetime
    observed_facts: tuple[str, ...]
    rationale: str

    @model_validator(mode="after")
    def validate_adjudication(self) -> ClusterReviewAdjudicationV2:
        require_stable_id(self.adjudication_id, kind="review")
        require_stable_id(self.trial_id, kind="review")
        require_stable_id(self.adjudicator_id, kind="review")
        if len(set(self.reviewer_decision_ids)) != 2:
            raise ValueError("Cluster adjudication requires two decisions.")
        for decision_id in self.reviewer_decision_ids:
            require_stable_id(decision_id, kind="review")
        if self.decided_at.tzinfo is None:
            raise ValueError("Cluster adjudication requires a timezone.")
        if not self.witness_labels or not self.observed_facts or not self.rationale:
            raise ValueError("Cluster adjudication requires evidence and rationale.")
        return self


class HeldOutReviewV2Metrics(ContractModel):
    valid_corridor_package_count: int = Field(ge=0)
    reproducibility_only_case_count: int = Field(ge=0)
    completed_cluster_review_count: int = Field(ge=0)
    raw_agreement: float | None
    cohen_kappa: float | None
    median_review_seconds: float | None
    weighted_attention_precision: float | None
    weighted_attention_recall: float | None
    safety_critical_false_negative_count: int = Field(ge=0)
    hidden_member_disagreement_count: int = Field(ge=0)
    hidden_member_disagreement_upper_bound: float | None
    auto_precision_status: Literal["not-applicable", "prospective"]
    auto_precision: float | None
    auto_precision_one_sided_lower_bound: float | None
    auto_coverage: float | None


class HeldOutReviewV2Report(ContractModel):
    schema_id: str = "torii.corridor.held-out-review-report/v2"
    trial_id: StableToken
    policy_sha256: Sha256
    parent_review_benchmark_sha256: Sha256
    status: GateStatus
    stage_1m_machine_review_ready_gate: GateStatus
    stage_1h_human_validation_gate: GateStatus
    automatic_promotion_gate: GateStatus = GateStatus.BLOCKED
    metrics: HeldOutReviewV2Metrics
    blockers: tuple[str, ...]

    @model_validator(mode="after")
    def validate_report(self) -> HeldOutReviewV2Report:
        require_stable_id(self.trial_id, kind="review")
        if self.automatic_promotion_gate is not GateStatus.BLOCKED:
            raise ValueError("V2 reports cannot authorize automatic promotion.")
        if self.stage_1h_human_validation_gate is GateStatus.PASS and self.status is not GateStatus.PASS:
            raise ValueError("Human validation cannot pass a blocked trial.")
        return self


class HeldOutReviewV2ContractBundle(ContractModel):
    schema_id: str = "torii.corridor.held-out-review-contract-bundle/v2"
    parent: HeldOutReviewParentV2
    reserve_corpus: HeldOutReserveCorpusV2
    replacement_policy: HeldOutReplacementPolicyV2
    replacement_plan: HeldOutReplacementPlanV2
    sampling_policy: ReviewWitnessSamplingPolicyV2
    review_policy: HeldOutReviewPolicyV2
    blinded_dataset: BlindedAttentionDatasetV2 | None = None
    evaluation_key: AttentionEvaluationKeyV2 | None = None
    decisions: tuple[ClusterReviewDecisionV2, ...] = ()
    adjudications: tuple[ClusterReviewAdjudicationV2, ...] = ()
    report: HeldOutReviewV2Report | None = None

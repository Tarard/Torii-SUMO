from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from torii_sumo.core.artifact_io import write_json_atomic
from torii_sumo.core.candidate_contracts import file_sha256
from torii_sumo.corridor.enums import GateStatus
from torii_sumo.corridor.held_out_review_contracts import HeldOutReviewPolicy
from torii_sumo.corridor.held_out_review_v2 import (
    build_deterministic_replacement_plan_v2,
)
from torii_sumo.corridor.held_out_review_v2_contracts import (
    ClusterReviewDecisionV2,
    HeldOutReplacementPlanV2,
    HeldOutReplacementPolicyV2,
    HeldOutReserveCorpusV2,
    HeldOutReviewParentV2,
    HeldOutReviewPolicyV2,
    HeldOutReviewV2Metrics,
    HeldOutReviewV2Report,
    ReviewWitnessSamplingPolicyV2,
)
from torii_sumo.corridor.held_out_review_v2_preregistration import (
    build_held_out_replacement_policy_v2,
    build_held_out_reserve_corpus_v2,
    build_held_out_review_parent_v2,
    build_held_out_review_policy_v2,
    build_review_witness_sampling_policy_v2,
)
from torii_sumo.corridor.ids import stable_id
from torii_sumo.corridor.schema import (
    build_held_out_replacement_plan_v2_schema,
    build_held_out_replacement_policy_v2_schema,
    build_held_out_reserve_corpus_v2_schema,
    build_held_out_review_parent_v2_schema,
    build_held_out_review_policy_v2_schema,
    build_held_out_review_v2_contract_bundle_schema,
    build_held_out_review_v2_report_schema,
    build_review_witness_sampling_policy_v2_schema,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPOSITORY_ROOT / "benchmarks" / "corridor_human_modeling_v1"
SCHEMA_DIR = REPOSITORY_ROOT / "schemas"
BASE_BENCHMARK = BENCHMARK_DIR / "benchmark.v1.json"
HELD_OUT_CORPUS = BENCHMARK_DIR / "held_out_corpus.v1.json"
RESERVE = BENCHMARK_DIR / "held_out_reserve_corpus.v2.json"
REPLACEMENT_POLICY = BENCHMARK_DIR / "held_out_replacement_policy.v2.json"
SAMPLING_POLICY = BENCHMARK_DIR / "review_witness_sampling_policy.v2.json"
PARENT = BENCHMARK_DIR / "held_out_review_parent.v2.json"
POLICY = BENCHMARK_DIR / "held_out_review_preregistration.v2.json"
PLAN = BENCHMARK_DIR / "held_out_replacement_plan.v2.json"
COMPRESSION_SCHEMA = (
    SCHEMA_DIR / "torii.corridor.lossless-review-compression.v1.schema.json"
)


def test_v2_frozen_contract_chain_regenerates_exactly(tmp_path: Path) -> None:
    reserve_path = tmp_path / RESERVE.name
    replacement_path = tmp_path / REPLACEMENT_POLICY.name
    sampling_path = tmp_path / SAMPLING_POLICY.name
    parent_path = tmp_path / PARENT.name
    policy_path = tmp_path / POLICY.name
    plan_path = tmp_path / PLAN.name

    reserve = build_held_out_reserve_corpus_v2(
        parent_corpus_file=HELD_OUT_CORPUS
    )
    _write(reserve_path, reserve)
    replacement = build_held_out_replacement_policy_v2(
        parent_corpus_file=HELD_OUT_CORPUS,
        reserve_corpus_file=reserve_path,
    )
    _write(replacement_path, replacement)
    sampling = build_review_witness_sampling_policy_v2()
    _write(sampling_path, sampling)
    parent = build_held_out_review_parent_v2(
        base_benchmark_file=BASE_BENCHMARK,
        held_out_corpus_file=HELD_OUT_CORPUS,
        reserve_corpus_file=reserve_path,
        replacement_policy_file=replacement_path,
        sampling_policy_file=sampling_path,
        lossless_compression_schema_file=COMPRESSION_SCHEMA,
    )
    _write(parent_path, parent)
    policy = build_held_out_review_policy_v2(
        parent_review_benchmark_file=parent_path,
        reserve_corpus_file=reserve_path,
        replacement_policy_file=replacement_path,
        sampling_policy_file=sampling_path,
    )
    _write(policy_path, policy)
    plan = build_deterministic_replacement_plan_v2(
        reserve_corpus_file=reserve_path,
        replacement_policy_file=replacement_path,
    )
    _write(plan_path, plan)

    for generated, frozen in (
        (reserve_path, RESERVE),
        (replacement_path, REPLACEMENT_POLICY),
        (sampling_path, SAMPLING_POLICY),
        (parent_path, PARENT),
        (policy_path, POLICY),
        (plan_path, PLAN),
    ):
        assert generated.read_bytes() == frozen.read_bytes()


def test_v2_policy_separates_attention_and_prospective_safe_pass() -> None:
    policy = HeldOutReviewPolicyV2.model_validate_json(
        POLICY.read_text(encoding="utf-8")
    )
    v1 = HeldOutReviewPolicy.model_validate_json(
        (BENCHMARK_DIR / "held_out_review_preregistration.v1.json").read_text(
            encoding="utf-8"
        )
    )

    assert policy.schema_id.endswith("/v2")
    assert policy.trial_id != v1.trial_id
    assert policy.audit_attention.auto_precision_status == "not-applicable"
    assert policy.audit_attention.minimum_valid_corridor_packages == 30
    assert policy.prospective_safe_pass.current_defect_only_corpus_eligible is False
    assert policy.prospective_safe_pass.minimum_machine_acceptable_count == 600
    assert (
        policy.prospective_safe_pass.minimum_auto_precision_one_sided_lower_bound
        == 0.99
    )
    assert policy.stage_1m_machine_milestone_only is True
    assert policy.stage_1_exit_requires_human_validation is True
    assert policy.automatic_promotion_gate is GateStatus.BLOCKED


def test_replay_invalid_cases_are_separate_and_replaced_without_labels() -> None:
    reserve = HeldOutReserveCorpusV2.model_validate_json(
        RESERVE.read_text(encoding="utf-8")
    )
    replacement = HeldOutReplacementPolicyV2.model_validate_json(
        REPLACEMENT_POLICY.read_text(encoding="utf-8")
    )
    plan = HeldOutReplacementPlanV2.model_validate_json(
        PLAN.read_text(encoding="utf-8")
    )

    invalid = {
        "london-kings-cross",
        "melbourne-royal-parade",
        "sydney-cross-city-tunnel",
    }
    assert {slot.invalid_corridor_key for slot in reserve.slots} == invalid
    assert {slot.invalid_corridor_key for slot in plan.slots} == invalid
    assert replacement.replay_invalid_excluded_from_quality_denominator is True
    assert replacement.prohibited_selection_signals == (
        "machine_label",
        "finding_count",
        "finding_severity",
        "human_decision",
        "reviewer_visibility",
    )
    assert plan.machine_labels_consulted is False
    assert plan.human_decisions_consulted is False
    assert {
        slot.invalid_corridor_key: slot.ordered_candidates[0].corridor_key
        for slot in plan.slots
    } == {
        "london-kings-cross": "london-liverpool-street",
        "melbourne-royal-parade": "melbourne-st-kilda-domain",
        "sydney-cross-city-tunnel": (
            "sydney-eastern-distributor-surry-hills"
        ),
    }


def test_v2_hash_chain_is_closed() -> None:
    reserve = HeldOutReserveCorpusV2.model_validate_json(
        RESERVE.read_text(encoding="utf-8")
    )
    replacement = HeldOutReplacementPolicyV2.model_validate_json(
        REPLACEMENT_POLICY.read_text(encoding="utf-8")
    )
    sampling = ReviewWitnessSamplingPolicyV2.model_validate_json(
        SAMPLING_POLICY.read_text(encoding="utf-8")
    )
    parent = HeldOutReviewParentV2.model_validate_json(
        PARENT.read_text(encoding="utf-8")
    )
    policy = HeldOutReviewPolicyV2.model_validate_json(
        POLICY.read_text(encoding="utf-8")
    )

    assert reserve.parent_corpus_sha256 == file_sha256(HELD_OUT_CORPUS)
    assert replacement.reserve_corpus_sha256 == file_sha256(RESERVE)
    assert parent.reserve_corpus_sha256 == file_sha256(RESERVE)
    assert parent.replacement_policy_sha256 == file_sha256(REPLACEMENT_POLICY)
    assert parent.sampling_policy_sha256 == file_sha256(SAMPLING_POLICY)
    assert policy.parent_review_benchmark_sha256 == file_sha256(PARENT)
    assert policy.reserve_corpus_sha256 == file_sha256(RESERVE)
    assert policy.replacement_policy_sha256 == file_sha256(REPLACEMENT_POLICY)
    assert policy.sampling_policy_sha256 == file_sha256(SAMPLING_POLICY)
    assert sampling.automatic_promotion_gate is GateStatus.BLOCKED


def test_v2_cluster_decision_requires_blinding_attestations() -> None:
    payload = {
        "decision_id": stable_id("review", {"v2-decision": 1}),
        "trial_id": stable_id("review", {"v2-trial": 1}),
        "case_code": "case-0123456789ab",
        "unit_code": "unit-0123456789ab",
        "reviewer_id": stable_id("review", {"v2-reviewer": 1}),
        "label": "attention-required",
        "witness_labels": {"witness-0123456789ab": "attention-required"},
        "cluster_purity_supported": True,
        "started_at": datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
        "decided_at": datetime(2026, 7, 14, 12, 1, tzinfo=UTC),
        "observed_facts": ("Observed right-of-way evidence.",),
        "rationale": "Independent blinded decision.",
        "machine_label_was_hidden": False,
    }

    with pytest.raises(ValueError):
        ClusterReviewDecisionV2.model_validate(payload)


def test_v2_report_can_never_authorize_promotion() -> None:
    payload = {
        "trial_id": stable_id("review", {"v2-report": 1}),
        "policy_sha256": "0" * 64,
        "parent_review_benchmark_sha256": "1" * 64,
        "status": "pass",
        "stage_1m_machine_review_ready_gate": "pass",
        "stage_1h_human_validation_gate": "pass",
        "automatic_promotion_gate": "pass",
        "metrics": HeldOutReviewV2Metrics(
            valid_corridor_package_count=30,
            reproducibility_only_case_count=3,
            completed_cluster_review_count=30,
            raw_agreement=1.0,
            cohen_kappa=1.0,
            median_review_seconds=60.0,
            weighted_attention_precision=1.0,
            weighted_attention_recall=1.0,
            safety_critical_false_negative_count=0,
            hidden_member_disagreement_count=0,
            hidden_member_disagreement_upper_bound=0.05,
            auto_precision_status="not-applicable",
            auto_precision=None,
            auto_precision_one_sided_lower_bound=None,
            auto_coverage=None,
        ),
        "blockers": (),
    }
    with pytest.raises(ValueError):
        HeldOutReviewV2Report.model_validate(payload)


def test_v2_schemas_are_current() -> None:
    schemas = {
        "torii.corridor.held-out-reserve-corpus.v2.schema.json": (
            build_held_out_reserve_corpus_v2_schema()
        ),
        "torii.corridor.held-out-replacement-policy.v2.schema.json": (
            build_held_out_replacement_policy_v2_schema()
        ),
        "torii.corridor.held-out-replacement-plan.v2.schema.json": (
            build_held_out_replacement_plan_v2_schema()
        ),
        "torii.corridor.review-witness-sampling-policy.v2.schema.json": (
            build_review_witness_sampling_policy_v2_schema()
        ),
        "torii.corridor.held-out-review-parent.v2.schema.json": (
            build_held_out_review_parent_v2_schema()
        ),
        "torii.corridor.held-out-review-policy.v2.schema.json": (
            build_held_out_review_policy_v2_schema()
        ),
        "torii.corridor.held-out-review-contract-bundle.v2.schema.json": (
            build_held_out_review_v2_contract_bundle_schema()
        ),
        "torii.corridor.held-out-review-report.v2.schema.json": (
            build_held_out_review_v2_report_schema()
        ),
    }
    for filename, schema in schemas.items():
        expected = json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True)
        assert (SCHEMA_DIR / filename).read_text(encoding="utf-8") == expected


def _write(path: Path, model: object) -> None:
    write_json_atomic(
        path,
        model.model_dump(mode="json", by_alias=True),
        sort_keys=True,
    )

from __future__ import annotations

import json
from pathlib import Path

from torii_sumo.core.candidate_contracts import file_sha256
from torii_sumo.corridor.enums import GateStatus
from torii_sumo.corridor.held_out_review_v2_contracts import (
    HeldOutReviewExecutionParentV2R2,
    HeldOutReviewPolicyV2,
    HeldOutReviewTrialInstanceV2R2,
    ReviewStudySamplingPolicyV2R2,
)
from torii_sumo.corridor.schema import (
    build_attention_evaluation_key_v2_r2_schema,
    build_blinded_attention_dataset_v2_r2_schema,
    build_held_out_review_execution_parent_v2_r2_schema,
    build_held_out_review_package_manifest_v2_r2_schema,
    build_held_out_review_trial_instance_v2_r2_schema,
    build_review_study_sampling_policy_v2_r2_schema,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPOSITORY_ROOT / "benchmarks" / "corridor_human_modeling_v1"
SCHEMA_DIR = REPOSITORY_ROOT / "schemas"
BASE_POLICY = BENCHMARK_DIR / "held_out_review_preregistration.v2.json"
BASE_PARENT = BENCHMARK_DIR / "held_out_review_parent.v2.json"
PARENT_SAMPLING = BENCHMARK_DIR / "review_witness_sampling_policy.v2.json"
EFFECTIVE_CORPUS = BENCHMARK_DIR / "held_out_effective_corpus.v2.json"
ATTEMPT_LEDGER = BENCHMARK_DIR / "held_out_replacement_attempt_ledger.v2.json"
SOURCE_PROTOCOL = BENCHMARK_DIR / "held_out_source_snapshot_protocol.v2.json"
STUDY_SAMPLING = BENCHMARK_DIR / "review_study_sampling_policy.v2-r2.json"
EXECUTION_PARENT = BENCHMARK_DIR / "held_out_review_execution_parent.v2-r2.json"
TRIAL_INSTANCE = BENCHMARK_DIR / "held_out_review_trial_instance.v2-r2.json"


def test_v2_r2_execution_parent_binds_clean_complete_machine_evidence() -> None:
    parent = HeldOutReviewExecutionParentV2R2.model_validate_json(
        EXECUTION_PARENT.read_text(encoding="utf-8")
    )

    assert parent.base_review_parent_sha256 == file_sha256(BASE_PARENT)
    assert parent.base_review_policy_sha256 == file_sha256(BASE_POLICY)
    assert parent.effective_corpus_sha256 == file_sha256(EFFECTIVE_CORPUS)
    assert parent.replacement_attempt_ledger_sha256 == file_sha256(ATTEMPT_LEDGER)
    assert parent.source_snapshot_protocol_sha256 == file_sha256(SOURCE_PROTOCOL)
    assert parent.valid_corridor_package_count == 30
    assert parent.pipeline_pass_count == 30
    assert parent.semantic_replay_pass_count == 30
    assert parent.producer.working_tree_clean is True
    assert parent.producer.revision == "f14eb888b25ffec7f27cdbe0c40ce10a481fb544"
    assert parent.machine_assessments_frozen is True
    assert parent.human_decisions_present is False
    assert parent.review_ready_is_not_stage1_exit is True
    assert parent.automatic_promotion_gate is GateStatus.BLOCKED


def test_v2_r2_sampling_separates_machine_census_from_human_sample() -> None:
    policy = ReviewStudySamplingPolicyV2R2.model_validate_json(
        STUDY_SAMPLING.read_text(encoding="utf-8")
    )

    assert policy.parent_sampling_policy_sha256 == file_sha256(PARENT_SAMPLING)
    assert policy.target_conflict_sites_per_corridor == 8
    assert policy.target_negative_pairs_per_corridor == 4
    assert policy.atomic_witness_machine_census_required is True
    assert policy.rare_hard_ood_machine_census_required is True
    assert policy.unknown_control_population_must_be_retained is True
    assert policy.unknown_control_does_not_force_human_member_census is True
    assert policy.unselected_population_remains_unresolved is True
    assert policy.inclusion_probability_required is True
    assert policy.estimator == "horvitz-thompson"
    assert policy.automatic_promotion_gate is GateStatus.BLOCKED


def test_v2_r2_trial_is_precommitted_before_sampling_without_threshold_changes() -> None:
    base_policy = HeldOutReviewPolicyV2.model_validate_json(
        BASE_POLICY.read_text(encoding="utf-8")
    )
    trial = HeldOutReviewTrialInstanceV2R2.model_validate_json(
        TRIAL_INSTANCE.read_text(encoding="utf-8")
    )
    raw_trial = json.loads(TRIAL_INSTANCE.read_text(encoding="utf-8"))

    assert trial.base_review_policy_sha256 == file_sha256(BASE_POLICY)
    assert trial.execution_parent_sha256 == file_sha256(EXECUTION_PARENT)
    assert trial.study_sampling_policy_sha256 == file_sha256(STUDY_SAMPLING)
    assert trial.predecessor_trial_id == base_policy.trial_id
    assert trial.predecessor_trial_executed is False
    assert trial.thresholds_inherited_without_change is True
    assert trial.seed_generated_once_before_sampling is True
    assert trial.sampling_not_executed_before_freeze is True
    assert trial.machine_labels_consulted_for_sampling is False
    assert trial.finding_counts_consulted_for_sampling is False
    assert trial.human_decisions_present is False
    assert trial.stage_1m_machine_milestone_only is True
    assert trial.stage_1_exit_requires_human_validation is True
    assert trial.automatic_promotion_gate is GateStatus.BLOCKED
    assert len(trial.blinding_seed_sha256) == 64
    assert "blinding_seed" not in raw_trial


def test_v2_r2_schemas_are_current() -> None:
    schemas = {
        "torii.corridor.review-study-sampling-policy.v2-r2.schema.json": (
            build_review_study_sampling_policy_v2_r2_schema()
        ),
        "torii.corridor.held-out-review-execution-parent.v2-r2.schema.json": (
            build_held_out_review_execution_parent_v2_r2_schema()
        ),
        "torii.corridor.held-out-review-trial-instance.v2-r2.schema.json": (
            build_held_out_review_trial_instance_v2_r2_schema()
        ),
        "torii.corridor.blinded-attention-dataset.v2-r2.schema.json": (
            build_blinded_attention_dataset_v2_r2_schema()
        ),
        "torii.corridor.attention-evaluation-key.v2-r2.schema.json": (
            build_attention_evaluation_key_v2_r2_schema()
        ),
        "torii.corridor.held-out-review-package-manifest.v2-r2.schema.json": (
            build_held_out_review_package_manifest_v2_r2_schema()
        ),
    }
    for filename, schema in schemas.items():
        expected = json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True)
        assert (SCHEMA_DIR / filename).read_text(encoding="utf-8") == expected

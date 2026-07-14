from __future__ import annotations

from .composite_benchmark_contracts import (
    CompositeFaultBenchmarkReport,
    CompositeFaultBenchmarkSpec,
)
from .applicability import (
    CertificationApplicabilityReport,
    CertificationEnvelope,
)
from .held_out_review_contracts import (
    HeldOutReviewContractBundle,
    HeldOutReviewPolicy,
    HeldOutReviewReport,
)
from .held_out_corpus_contracts import (
    HeldOutCorpusMachineManifest,
    HeldOutCorpusMachineReport,
    HeldOutCorpusSnapshotReport,
    HeldOutCorpusSpec,
)
from .manifest import CorridorResearchBundle
from .net_replay import NetReplayReport
from .plainxml_normalization import PlainXmlNormalizationReport
from .pedestrian_control_census import (
    ControlledPedestrianBindingCensus,
    EffectiveTLSProgramInventory,
)
from .pedestrian_row_contracts import ROWExperimentReport
from .review_compression import (
    AtomicConflictLedger,
    LosslessReviewCompressionReport,
)
from .official_sumo_benchmark_contracts import (
    OfficialSumoBenchmarkReport,
    OfficialSumoBenchmarkSpec,
)
from .ood_benchmark_contracts import OODBenchmarkReport, OODBenchmarkSpec
from .synthetic_benchmark_contracts import (
    SyntheticFaultBenchmarkReport,
    SyntheticFaultBenchmarkSpec,
)
from .run_identity import HeldOutMachineRunIdentity


def build_corridor_schema() -> dict[str, object]:
    schema = CorridorResearchBundle.model_json_schema(by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = (
        "https://github.com/Tarard/Torii-SUMO/"
        "schemas/torii.corridor.research-bundle.v1.schema.json"
    )
    schema["x-torii-status"] = "frozen-stage-0-contract"
    return schema


def build_synthetic_fault_benchmark_schema() -> dict[str, object]:
    return _artifact_schema(
        SyntheticFaultBenchmarkSpec,
        "torii.corridor.synthetic-fault-benchmark.v1.schema.json",
        status="stage-1-gold-contract",
    )


def build_synthetic_fault_benchmark_report_schema() -> dict[str, object]:
    return _artifact_schema(
        SyntheticFaultBenchmarkReport,
        "torii.corridor.synthetic-fault-benchmark-report.v1.schema.json",
        status="stage-1-evidence-contract",
    )


def build_composite_fault_benchmark_schema() -> dict[str, object]:
    return _artifact_schema(
        CompositeFaultBenchmarkSpec,
        "torii.corridor.composite-fault-benchmark.v1.schema.json",
        status="stage-1-compound-fault-contract",
    )


def build_composite_fault_benchmark_report_schema() -> dict[str, object]:
    return _artifact_schema(
        CompositeFaultBenchmarkReport,
        "torii.corridor.composite-fault-benchmark-report.v1.schema.json",
        status="stage-1-compound-fault-evidence-contract",
    )


def build_certification_envelope_schema() -> dict[str, object]:
    return _artifact_schema(
        CertificationEnvelope,
        "torii.corridor.certification-envelope.v1.schema.json",
        status="stage-1-selective-domain-contract",
    )


def build_certification_applicability_report_schema() -> dict[str, object]:
    return _artifact_schema(
        CertificationApplicabilityReport,
        "torii.corridor.certification-applicability-report.v1.schema.json",
        status="stage-1-selective-domain-evidence-contract",
    )


def build_ood_benchmark_schema() -> dict[str, object]:
    return _artifact_schema(
        OODBenchmarkSpec,
        "torii.corridor.ood-benchmark.v1.schema.json",
        status="stage-1-ood-contract",
    )


def build_ood_benchmark_report_schema() -> dict[str, object]:
    return _artifact_schema(
        OODBenchmarkReport,
        "torii.corridor.ood-benchmark-report.v1.schema.json",
        status="stage-1-ood-evidence-contract",
    )


def build_official_sumo_benchmark_schema() -> dict[str, object]:
    return _artifact_schema(
        OfficialSumoBenchmarkSpec,
        "torii.corridor.official-sumo-benchmark.v1.schema.json",
        status="stage-1-normative-contract",
    )


def build_official_sumo_benchmark_report_schema() -> dict[str, object]:
    return _artifact_schema(
        OfficialSumoBenchmarkReport,
        "torii.corridor.official-sumo-benchmark-report.v1.schema.json",
        status="stage-1-normative-evidence-contract",
    )


def build_held_out_review_policy_schema() -> dict[str, object]:
    return _artifact_schema(
        HeldOutReviewPolicy,
        "torii.corridor.held-out-review-policy.v1.schema.json",
        status="stage-1-preregistered-human-review-contract",
    )


def build_held_out_review_contract_bundle_schema() -> dict[str, object]:
    return _artifact_schema(
        HeldOutReviewContractBundle,
        "torii.corridor.held-out-review-contract-bundle.v1.schema.json",
        status="stage-1-blinded-human-review-contract",
    )


def build_held_out_review_report_schema() -> dict[str, object]:
    return _artifact_schema(
        HeldOutReviewReport,
        "torii.corridor.held-out-review-report.v1.schema.json",
        status="stage-1-held-out-evidence-contract",
    )


def build_held_out_corpus_schema() -> dict[str, object]:
    return _artifact_schema(
        HeldOutCorpusSpec,
        "torii.corridor.held-out-corpus.v1.schema.json",
        status="stage-1-held-out-corpus-contract",
    )


def build_held_out_corpus_snapshot_report_schema() -> dict[str, object]:
    return _artifact_schema(
        HeldOutCorpusSnapshotReport,
        "torii.corridor.held-out-corpus-snapshot-report.v1.schema.json",
        status="stage-1-held-out-corpus-evidence-contract",
    )


def build_held_out_corpus_machine_report_schema() -> dict[str, object]:
    return _artifact_schema(
        HeldOutCorpusMachineReport,
        "torii.corridor.held-out-corpus-machine-report.v2.schema.json",
        status="stage-1-held-out-corpus-machine-evidence-contract",
    )


def build_held_out_machine_run_identity_schema() -> dict[str, object]:
    return _artifact_schema(
        HeldOutMachineRunIdentity,
        "torii.corridor.held-out-machine-run-identity.v1.schema.json",
        status="stage-1-held-out-producer-toolchain-identity-contract",
    )


def build_held_out_corpus_machine_manifest_schema() -> dict[str, object]:
    return _artifact_schema(
        HeldOutCorpusMachineManifest,
        "torii.corridor.held-out-corpus-machine-manifest.v2.schema.json",
        status="stage-1-held-out-artifact-closure-contract",
    )


def build_net_replay_report_schema() -> dict[str, object]:
    return _artifact_schema(
        NetReplayReport,
        "torii.corridor.net-replay-report.v1.schema.json",
        status="stage-1-reproducibility-evidence-contract",
    )


def build_plainxml_normalization_report_schema() -> dict[str, object]:
    return _artifact_schema(
        PlainXmlNormalizationReport,
        "torii.corridor.plainxml-normalization-report.v1.schema.json",
        status="stage-1-experimental-deterministic-ingest-contract",
    )


def build_effective_tls_program_inventory_schema() -> dict[str, object]:
    return _artifact_schema(
        EffectiveTLSProgramInventory,
        "torii.corridor.effective-tls-program-inventory.v1.schema.json",
        status="stage-1m-pcb-effective-program-evidence-contract",
    )


def build_controlled_pedestrian_binding_census_schema() -> dict[str, object]:
    return _artifact_schema(
        ControlledPedestrianBindingCensus,
        "torii.corridor.controlled-pedestrian-binding-census.v1.schema.json",
        status="stage-1m-pcb-453-census-contract",
    )


def build_atomic_conflict_ledger_schema() -> dict[str, object]:
    return _artifact_schema(
        AtomicConflictLedger,
        "torii.corridor.atomic-conflict-ledger.v1.schema.json",
        status="stage-1m-rwc-1-lossless-atomic-witness-contract",
    )


def build_lossless_review_compression_schema() -> dict[str, object]:
    return _artifact_schema(
        LosslessReviewCompressionReport,
        "torii.corridor.lossless-review-compression.v1.schema.json",
        status="stage-1m-rwc-1-review-compression-contract",
    )


def build_row1_experiment_report_schema() -> dict[str, object]:
    return _artifact_schema(
        ROWExperimentReport,
        "torii.corridor.row-1-experiment-report.v1.schema.json",
        status="stage-1m-row-1-independent-right-of-way-contract",
    )


def _artifact_schema(model: type, filename: str, *, status: str) -> dict[str, object]:
    schema = model.model_json_schema(by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://github.com/Tarard/Torii-SUMO/schemas/{filename}"
    schema["x-torii-status"] = status
    return schema

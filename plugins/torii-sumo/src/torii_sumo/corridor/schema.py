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
    HeldOutCorpusMachineReport,
    HeldOutCorpusSnapshotReport,
    HeldOutCorpusSpec,
)
from .manifest import CorridorResearchBundle
from .official_sumo_benchmark_contracts import (
    OfficialSumoBenchmarkReport,
    OfficialSumoBenchmarkSpec,
)
from .ood_benchmark_contracts import OODBenchmarkReport, OODBenchmarkSpec
from .synthetic_benchmark_contracts import (
    SyntheticFaultBenchmarkReport,
    SyntheticFaultBenchmarkSpec,
)


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
        "torii.corridor.held-out-corpus-machine-report.v1.schema.json",
        status="stage-1-held-out-corpus-machine-evidence-contract",
    )


def _artifact_schema(model: type, filename: str, *, status: str) -> dict[str, object]:
    schema = model.model_json_schema(by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://github.com/Tarard/Torii-SUMO/schemas/{filename}"
    schema["x-torii-status"] = status
    return schema

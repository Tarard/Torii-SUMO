from __future__ import annotations

from .manifest import CorridorResearchBundle
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


def _artifact_schema(model: type, filename: str, *, status: str) -> dict[str, object]:
    schema = model.model_json_schema(by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://github.com/Tarard/Torii-SUMO/schemas/{filename}"
    schema["x-torii-status"] = status
    return schema

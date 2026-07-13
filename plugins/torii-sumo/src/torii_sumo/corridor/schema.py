from __future__ import annotations

from .manifest import CorridorResearchBundle


def build_corridor_schema() -> dict[str, object]:
    schema = CorridorResearchBundle.model_json_schema(by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = (
        "https://github.com/Tarard/Torii-SUMO/"
        "schemas/torii.corridor.research-bundle.v1.schema.json"
    )
    schema["x-torii-status"] = "frozen-stage-0-contract"
    return schema

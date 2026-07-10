from __future__ import annotations

import re

from pydantic import BaseModel, Field


class IntersectionSceneSpec(BaseModel):
    schema_version: str = "intersection-scene/v1"
    topology: str = "four_way"
    approach_count: int = 4
    control: str = "traffic_light"
    controller: str = "nema_reference"
    allowed_modes: set[str] = Field(default_factory=lambda: {"passenger"})
    link_length_m: float = 180.0
    speed_mps: float = 13.89
    smoke_route: tuple[str, str] = ("W", "E")
    assumptions: tuple[str, ...] = (
        "NEMA is a synthetic/defaulted reference controller, not field-calibrated timing.",
    )


_FOUR_WAY = re.compile(r"\b(?:four[- ]way|4[- ]way|x4)\b")
_SIGNALIZED = re.compile(r"\b(?:tls|traffic[- ]lights?|signalized)\b")
_UNSUPPORTED_FEATURE = re.compile(
    r"\b(?:all[- ]modes|bus(?:es)?|trucks?|bicycles?|bikes?|biking|cycles?|"
    r"cyclists?|peds?|pedestrians?|walking|crosswalks?|sidewalks?|ramps?|"
    r"taxis?|trams?|rail|motorcycles?)\b"
)
_UNSUPPORTED = (
    "Unsupported intersection scene for Phase 1; describe a four-way signalized/TLS "
    "passenger intersection."
)


def _has_negated_signalization(text: str) -> bool:
    if re.search(r"\bunsignalized\b", text):
        return True
    tokens = re.findall(r"[a-z]+(?:['’][a-z]+)?", text)
    markers = {
        index
        for index, token in enumerate(tokens)
        if token in {"no", "not", "never", "without", "neither", "non", "isn't", "isn’t"}
    }
    signals = {
        index
        for index, token in enumerate(tokens)
        if token in {"tls", "signalized"}
        or (
            token == "traffic"
            and index + 1 < len(tokens)
            and tokens[index + 1] in {"light", "lights"}
        )
    }
    # ponytail: five tokens is the Phase-1 phrase window; use a parser if grammar expands.
    return any(1 <= signal - marker <= 5 for marker in markers for signal in signals)


def resolve_intersection_scene_prompt(prompt: str) -> IntersectionSceneSpec:
    normalized = " ".join(prompt.casefold().split())
    if (
        not normalized
        or not _FOUR_WAY.search(normalized)
        or not _SIGNALIZED.search(normalized)
        or _has_negated_signalization(normalized)
        or _UNSUPPORTED_FEATURE.search(normalized)
    ):
        raise ValueError(_UNSUPPORTED)
    return IntersectionSceneSpec()

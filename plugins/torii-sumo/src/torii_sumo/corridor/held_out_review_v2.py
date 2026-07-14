from __future__ import annotations

import hashlib
from pathlib import Path

from torii_sumo.core.candidate_contracts import file_sha256

from .enums import GateStatus
from .held_out_review_v2_contracts import (
    HeldOutReplacementPlanV2,
    HeldOutReplacementPolicyV2,
    HeldOutReserveCorpusV2,
    RankedReserveCandidateV2,
    ReplacementSlotPlanV2,
)
from .ids import stable_id


def build_deterministic_replacement_plan_v2(
    *,
    reserve_corpus_file: Path,
    replacement_policy_file: Path,
) -> HeldOutReplacementPlanV2:
    reserve_path = reserve_corpus_file.resolve()
    policy_path = replacement_policy_file.resolve()
    reserve = HeldOutReserveCorpusV2.model_validate_json(
        reserve_path.read_text(encoding="utf-8")
    )
    policy = HeldOutReplacementPolicyV2.model_validate_json(
        policy_path.read_text(encoding="utf-8")
    )
    if policy.reserve_corpus_sha256 != file_sha256(reserve_path):
        raise ValueError("Replacement policy is not bound to the reserve corpus.")
    if policy.parent_corpus_sha256 != reserve.parent_corpus_sha256:
        raise ValueError("Replacement policy and reserve parent corpus differ.")
    slots: list[ReplacementSlotPlanV2] = []
    for slot in reserve.slots:
        ranked = sorted(
            (
                _rank_candidate(
                    policy.public_selection_seed,
                    slot.invalid_corridor_key,
                    candidate.selection.corridor_key,
                    candidate.selection.selection_id,
                )
                for candidate in slot.candidates
            ),
            key=lambda item: item["ranking_digest"],
        )
        slots.append(
            ReplacementSlotPlanV2(
                invalid_corridor_key=slot.invalid_corridor_key,
                invalid_selection_id=slot.invalid_selection_id,
                ordered_candidates=tuple(
                    RankedReserveCandidateV2(rank=index, **candidate)
                    for index, candidate in enumerate(ranked, start=1)
                ),
            )
        )
    payload = {
        "reserve_corpus_sha256": file_sha256(reserve_path),
        "replacement_policy_sha256": file_sha256(policy_path),
        "slots": tuple(slots),
        "automatic_promotion_gate": GateStatus.BLOCKED,
    }
    provisional = HeldOutReplacementPlanV2.model_construct(
        replacement_plan_id=stable_id("manifest", {"pending": True}),
        **payload,
    )
    return HeldOutReplacementPlanV2(
        replacement_plan_id=stable_id(
            "manifest", provisional.identity_payload()
        ),
        **payload,
    )


def _rank_candidate(
    seed: str,
    invalid_corridor_key: str,
    corridor_key: str,
    selection_id: str,
) -> dict[str, str]:
    value = f"{seed}|{invalid_corridor_key}|{selection_id}"
    return {
        "corridor_key": corridor_key,
        "selection_id": selection_id,
        "ranking_digest": hashlib.sha256(value.encode("utf-8")).hexdigest(),
    }

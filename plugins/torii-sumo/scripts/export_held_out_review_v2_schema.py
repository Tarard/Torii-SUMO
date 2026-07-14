from __future__ import annotations

import argparse
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PLUGIN_ROOT.parents[1]
SRC_ROOT = PLUGIN_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from torii_sumo.core.artifact_io import write_json_atomic  # noqa: E402
from torii_sumo.corridor.schema import (  # noqa: E402
    build_held_out_replacement_plan_v2_schema,
    build_held_out_replacement_policy_v2_schema,
    build_held_out_reserve_corpus_v2_schema,
    build_held_out_review_parent_v2_schema,
    build_held_out_review_policy_v2_schema,
    build_held_out_review_v2_contract_bundle_schema,
    build_held_out_review_v2_report_schema,
    build_review_witness_sampling_policy_v2_schema,
)


SCHEMA_DIR = REPOSITORY_ROOT / "schemas"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export Torii Stage 1-M held-out review v2 schemas."
    )
    outputs = (
        (
            "reserve",
            "torii.corridor.held-out-reserve-corpus.v2.schema.json",
            build_held_out_reserve_corpus_v2_schema,
        ),
        (
            "replacement-policy",
            "torii.corridor.held-out-replacement-policy.v2.schema.json",
            build_held_out_replacement_policy_v2_schema,
        ),
        (
            "replacement-plan",
            "torii.corridor.held-out-replacement-plan.v2.schema.json",
            build_held_out_replacement_plan_v2_schema,
        ),
        (
            "sampling-policy",
            "torii.corridor.review-witness-sampling-policy.v2.schema.json",
            build_review_witness_sampling_policy_v2_schema,
        ),
        (
            "parent",
            "torii.corridor.held-out-review-parent.v2.schema.json",
            build_held_out_review_parent_v2_schema,
        ),
        (
            "policy",
            "torii.corridor.held-out-review-policy.v2.schema.json",
            build_held_out_review_policy_v2_schema,
        ),
        (
            "bundle",
            "torii.corridor.held-out-review-contract-bundle.v2.schema.json",
            build_held_out_review_v2_contract_bundle_schema,
        ),
        (
            "report",
            "torii.corridor.held-out-review-report.v2.schema.json",
            build_held_out_review_v2_report_schema,
        ),
    )
    for name, filename, _builder in outputs:
        parser.add_argument(
            f"--{name}-output",
            type=Path,
            default=SCHEMA_DIR / filename,
        )
    args = parser.parse_args()
    for name, _filename, builder in outputs:
        path = getattr(args, f"{name.replace('-', '_')}_output")
        write_json_atomic(path, builder(), sort_keys=True)


if __name__ == "__main__":
    main()

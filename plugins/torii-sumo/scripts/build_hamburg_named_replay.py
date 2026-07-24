from __future__ import annotations

import argparse
import json
from pathlib import Path

from torii_sumo.core.hamburg_named_replay import (
    HamburgNamedReplayError,
    materialize_hamburg_named_replay,
    materialize_hamburg_named_replay_preflight,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Hamburg W4 from hash-bound W2 signal, W3a count, and W3b detector inputs."
    )
    parser.add_argument("--net-file", type=Path)
    parser.add_argument("--w1-manifest", required=True, type=Path)
    parser.add_argument("--signal-binding-manifest", required=True, type=Path)
    parser.add_argument("--detector-binding-manifest", required=True, type=Path)
    parser.add_argument("--count-scope-manifest", required=True, type=Path)
    parser.add_argument("--count-stream-snapshot", required=True, type=Path)
    parser.add_argument("--canonical-count-file", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--signal-observation-manifest", type=Path)
    parser.add_argument("--route-sampler-script", type=Path)
    parser.add_argument("--sumo-binary", default="sumo")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--simulation-begin", type=int, default=0)
    parser.add_argument("--simulation-end", type=int, default=9000)
    parser.add_argument("--comparison-begin", type=int, default=1800)
    parser.add_argument("--comparison-end", type=int, default=9000)
    parser.add_argument("--interval", type=int, default=900)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Write a hash-bound blocked W4 manifest without running routeSampler or SUMO.",
    )
    parser.add_argument(
        "--allow-detector-cross-section-boundaries",
        action="store_true",
        help=(
            "Use official detector edges as explicit open source/sink ports; this reproduces "
            "the measured local cut but does not claim upstream OD demand."
        ),
    )
    args = parser.parse_args()
    try:
        if args.preflight_only:
            report = materialize_hamburg_named_replay_preflight(
                net_file=args.net_file,
                w1_manifest_file=args.w1_manifest,
                signal_binding_manifest=args.signal_binding_manifest,
                detector_binding_manifest=args.detector_binding_manifest,
                count_scope_manifest=args.count_scope_manifest,
                count_stream_snapshot=args.count_stream_snapshot,
                canonical_count_file=args.canonical_count_file,
                output_dir=args.output_dir,
            )
        else:
            report = materialize_hamburg_named_replay(
                net_file=args.net_file,
                w1_manifest_file=args.w1_manifest,
                signal_binding_manifest=args.signal_binding_manifest,
                detector_binding_manifest=args.detector_binding_manifest,
                count_scope_manifest=args.count_scope_manifest,
                count_stream_snapshot=args.count_stream_snapshot,
                canonical_count_file=args.canonical_count_file,
                output_dir=args.output_dir,
                signal_observation_manifest=args.signal_observation_manifest,
                route_sampler_script=args.route_sampler_script,
                sumo_binary=args.sumo_binary,
                timeout_seconds=args.timeout_seconds,
                simulation_begin=args.simulation_begin,
                simulation_end=args.simulation_end,
                comparison_begin=args.comparison_begin,
                comparison_end=args.comparison_end,
                interval=args.interval,
                allow_detector_cross_section_boundaries=args.allow_detector_cross_section_boundaries,
            )
    except (OSError, ValueError, HamburgNamedReplayError) as exc:
        print(json.dumps({"status": "error", "automatic_promotion_gate": "blocked", "error": str(exc)}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report["execution_gate"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())

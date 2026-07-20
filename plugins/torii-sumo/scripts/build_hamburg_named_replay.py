from __future__ import annotations

import argparse
import json
from pathlib import Path

from torii_sumo.core.hamburg_named_replay import (
    HamburgNamedReplayError,
    materialize_hamburg_named_replay,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a detector-constrained Hamburg SUMO diagnostic replay.")
    parser.add_argument("--net-file", required=True, type=Path)
    parser.add_argument("--signal-binding-manifest", required=True, type=Path)
    parser.add_argument("--count-stream-snapshot", required=True, type=Path)
    parser.add_argument("--canonical-count-file", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--signal-observation-manifest", type=Path)
    parser.add_argument("--route-sampler-script", type=Path)
    parser.add_argument("--sumo-binary", default="sumo")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    args = parser.parse_args()
    try:
        report = materialize_hamburg_named_replay(
            net_file=args.net_file,
            signal_binding_manifest=args.signal_binding_manifest,
            count_stream_snapshot=args.count_stream_snapshot,
            canonical_count_file=args.canonical_count_file,
            output_dir=args.output_dir,
            signal_observation_manifest=args.signal_observation_manifest,
            route_sampler_script=args.route_sampler_script,
            sumo_binary=args.sumo_binary,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, ValueError, HamburgNamedReplayError) as exc:
        print(json.dumps({"status": "error", "automatic_promotion_gate": "blocked", "error": str(exc)}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report["execution_gate"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())

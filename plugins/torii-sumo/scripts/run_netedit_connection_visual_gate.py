from __future__ import annotations

import argparse
import json
from pathlib import Path

from torii_sumo.core.netedit_connection_visual_gate import run_connection_visual_gate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare paired lanes in NetEdit Connection mode.")
    parser.add_argument("--teacher-net", required=True)
    parser.add_argument("--candidate-net", required=True)
    parser.add_argument("--teacher-junction", required=True)
    parser.add_argument("--candidate-junction", required=True)
    parser.add_argument("--lane-pair", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--zoom", type=float, default=2500.0)
    parser.add_argument("--window-size", default="1400,1000")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    lane_pairs = [tuple(value.split("=", 1)) for value in args.lane_pair]
    if any(len(pair) != 2 or not all(pair) for pair in lane_pairs):
        raise SystemExit("--lane-pair must be teacher_lane=candidate_lane")
    window_size = tuple(int(value) for value in args.window_size.split(",", 1))
    report = run_connection_visual_gate(
        teacher_net_file=Path(args.teacher_net), candidate_net_file=Path(args.candidate_net),
        teacher_junction=args.teacher_junction, candidate_junction=args.candidate_junction,
        lane_pairs=lane_pairs, output_dir=Path(args.output_dir), zoom=args.zoom,
        window_size=window_size,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 3 if report["status"] == "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())

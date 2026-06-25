from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "torii-sumo" / "src"))

from torii_sumo.core.junction_strategy_probe import probe_junction_strategies


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare local junction aggregation strategies against a reference SUMO junction.")
    parser.add_argument(
        "--candidate-net",
        type=Path,
        default=ROOT / "examples" / "02_one_prompt_osm_network" / "networks" / "torii_5_5_reference_visual_detail_tls_aggregated.net.xml",
    )
    parser.add_argument(
        "--reference-net",
        type=Path,
        default=ROOT / "examples" / "02_one_prompt_osm_network" / "networks" / "tum_ingolstadt_center_reference.net.xml",
    )
    parser.add_argument(
        "--reference-junction-id",
        default="cluster_281967823_305519232_7009179649_7626856596_7626856598_7626856599",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "examples" / "02_one_prompt_osm_network" / "validation" / "run_2026-06-25_strategy_probe_281967823",
    )
    parser.add_argument("--radius-m", type=float, default=40.0)
    parser.add_argument("--short-edge-m", type=float, default=2.0)
    args = parser.parse_args()
    report = probe_junction_strategies(
        candidate_net_file=args.candidate_net,
        reference_net_file=args.reference_net,
        reference_junction_id=args.reference_junction_id,
        output_dir=args.output_dir,
        radius_m=args.radius_m,
        short_edge_m=args.short_edge_m,
    )
    print(json.dumps({key: report[key] for key in ("status", "summary_file", "csv_file", "svg_file", "png_file")}, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

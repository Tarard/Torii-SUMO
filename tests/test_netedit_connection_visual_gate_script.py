from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path("plugins/torii-sumo/scripts/run_netedit_connection_visual_gate.py")


def test_cli_parses_negative_lane_id_with_equals_form() -> None:
    spec = importlib.util.spec_from_file_location("connection_visual_gate_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    args = module.build_parser().parse_args(
        [
            "--teacher-net", "teacher.net.xml", "--candidate-net", "candidate.net.xml",
            "--teacher-junction", "j", "--candidate-junction", "j",
            "--lane-pair=-e_0=-e_0", "--output-dir", "out",
        ]
    )
    assert args.lane_pair == ["-e_0=-e_0"]

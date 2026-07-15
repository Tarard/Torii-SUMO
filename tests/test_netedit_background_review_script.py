from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path("plugins/torii-sumo/scripts/netedit_background_review.py")


def _load_script():
    spec = importlib.util.spec_from_file_location("netedit_background_review", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_reads_target_and_builds_capture_requests(tmp_path: Path) -> None:
    script = _load_script()
    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text(
        '<net><junction id="j0" type="traffic_light" x="12.5" y="34.25" '
        'incLanes="e0_0 e1_0 e1_1"/></net>',
        encoding="utf-8",
    )

    target = script.read_target_junction(net_file, "j0")
    requests = script.capture_requests(target)

    assert target.x == 12.5
    assert target.y == 34.25
    assert target.incoming_lanes == ("e0_0", "e1_0", "e1_1")
    assert [request.mode for request in requests[:3]] == [
        "inspect",
        "tls",
        "connection",
    ]
    assert [request.selection_id for request in requests[3:]] == [
        "e0_0",
        "e1_0",
        "e1_1",
    ]


def test_viewsettings_selection_and_mode_are_deterministic() -> None:
    script = _load_script()

    assert script.viewsettings_text((12.5, 34.25), zoom=500) == (
        '<viewsettings>\n'
        '  <viewport zoom="500" x="12.5" y="34.25" angle="0"/>\n'
        '  <delay value="100"/>\n'
        '</viewsettings>\n'
    )
    assert script.selection_text("junction", "j0") == "junction:j0\n"
    assert script.selection_text("lane", "e0_0") == "lane:e0_0\n"
    assert script.mode_key("inspect") is None
    assert script.mode_key("connection") == "C"
    assert script.mode_key("tls") == "T"


def test_netedit_command_binds_view_selection_and_disables_registry_viewport() -> None:
    script = _load_script()

    command = script.build_netedit_command(
        netedit_binary="netedit",
        net_file=Path("candidate.net.xml"),
        view_file=Path("target.view.xml"),
        selection_file=Path("target.selection.txt"),
        additional_file=Path("review.add.xml"),
        window_size="1400,1000",
        window_pos="20,20",
    )

    assert command == [
        "netedit",
        "-s",
        "candidate.net.xml",
        "-g",
        "target.view.xml",
        "--selection-file",
        "target.selection.txt",
        "--registry-viewport",
        "false",
        "--window-size",
        "1400,1000",
        "--window-pos",
        "20,20",
        "--additional-files",
        "review.add.xml",
    ]

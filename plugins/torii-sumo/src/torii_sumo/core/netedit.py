from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import shutil
import subprocess


def launch_netedit(
    net_file: Path,
    *,
    gui_settings_file: Path | None = None,
    selection_file: Path | None = None,
    window_size: str | None = None,
    window_pos: str | None = None,
    netedit_binary: str = "netedit",
    which_func: Callable[[str], str | None] = shutil.which,
    popen_func: Callable[..., Any] = subprocess.Popen,
) -> dict[str, Any]:
    if not net_file.exists():
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "netedit_status": "failed",
            "netedit_binary": netedit_binary,
            "netedit_process_id": None,
            "netedit_window_title": "",
            "netedit_network_file": str(net_file),
            "warnings": [f"network file not found: {net_file}"],
        }

    resolved_binary = which_func(netedit_binary)
    if resolved_binary is None:
        return {
            "status": "blocked",
            "claim_status": "diagnostic-demo",
            "netedit_status": "unavailable",
            "netedit_binary": None,
            "netedit_process_id": None,
            "netedit_window_title": "",
            "netedit_network_file": str(net_file),
            "warnings": ["netedit binary not found"],
        }

    open_mode = "sumocfg" if net_file.suffix.lower() == ".sumocfg" else "net"
    command = [resolved_binary, "--sumocfg-file" if open_mode == "sumocfg" else "-s", str(net_file)]
    if gui_settings_file is not None:
        command += ["-g", str(gui_settings_file)]
    if selection_file is not None:
        command += ["--selection-file", str(selection_file)]
    if window_size:
        command += ["--window-size", window_size]
    if window_pos:
        command += ["--window-pos", window_pos]
    try:
        process = popen_func(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return {
            "status": "fail",
            "claim_status": "diagnostic-demo",
            "netedit_status": "failed",
            "netedit_binary": resolved_binary,
            "netedit_process_id": None,
            "netedit_window_title": "",
            "netedit_network_file": str(net_file),
            "netedit_input_file": str(net_file),
            "netedit_open_mode": open_mode,
            "netedit_gui_settings_file": str(gui_settings_file) if gui_settings_file is not None else "",
            "netedit_selection_file": str(selection_file) if selection_file is not None else "",
            "netedit_window_size": window_size or "",
            "netedit_window_pos": window_pos or "",
            "warnings": [f"{type(exc).__name__}: {exc}"],
        }

    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "netedit_status": "opened",
        "netedit_binary": resolved_binary,
        "netedit_process_id": process.pid,
        "netedit_window_title": "",
        "netedit_network_file": str(net_file),
        "netedit_input_file": str(net_file),
        "netedit_open_mode": open_mode,
        "netedit_gui_settings_file": str(gui_settings_file) if gui_settings_file is not None else "",
        "netedit_selection_file": str(selection_file) if selection_file is not None else "",
        "netedit_window_size": window_size or "",
        "netedit_window_pos": window_pos or "",
        "warnings": [],
    }

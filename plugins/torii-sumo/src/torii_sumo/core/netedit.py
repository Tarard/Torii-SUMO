from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import shutil
import subprocess


def launch_netedit(
    net_file: Path,
    *,
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

    command = [resolved_binary, "-s", str(net_file)]
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
        "warnings": [],
    }

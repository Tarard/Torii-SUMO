from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable, Sequence


def _netedit_input_mode(input_file: Path | str) -> str:
    """Return the Netedit input mode for a supported SUMO file."""
    path = Path(input_file)
    lowered_name = path.name.lower()
    if lowered_name.endswith(".net.xml"):
        return "net"
    if lowered_name.endswith(".sumocfg"):
        return "sumocfg"
    raise ValueError(f"unsupported Netedit input type: {path}; expected .net.xml or .sumocfg")


def _build_netedit_open_command(
    input_file: Path | str,
    *,
    netedit_binary: str = "netedit",
    gui_settings_file: Path | str | None = None,
    selection_file: Path | str | None = None,
    window_size: str | None = None,
    window_pos: str | None = None,
) -> list[str]:
    """Build the argument list used to open an existing SUMO network in Netedit.

    ``--sumo-net-file`` (``-s``) is the Netedit option for an existing
    ``.net.xml``.  ``-n`` is intentionally never used because it means plain
    node input for a network build, not a compiled SUMO network.
    """
    path = Path(input_file)
    open_mode = _netedit_input_mode(path)
    if not path.is_file():
        raise FileNotFoundError(f"Netedit input file not found: {path}")

    optional_paths = (
        ("GUI settings", None if gui_settings_file is None else Path(gui_settings_file)),
        ("selection", None if selection_file is None else Path(selection_file)),
    )
    for label, optional_path in optional_paths:
        if optional_path is not None and not optional_path.is_file():
            raise FileNotFoundError(f"Netedit {label} file not found: {optional_path}")

    command = [
        str(netedit_binary),
        "--sumocfg-file" if open_mode == "sumocfg" else "--sumo-net-file",
        str(path),
    ]
    if gui_settings_file is not None:
        command += ["-g", str(gui_settings_file)]
    if selection_file is not None:
        command += ["--selection-file", str(selection_file)]
    if window_size:
        command += ["--window-size", window_size]
    if window_pos:
        command += ["--window-pos", window_pos]
    return command


def _failure_report(
    input_file: Path,
    *,
    netedit_binary: str | None,
    warning: str,
    status: str = "fail",
    netedit_status: str = "failed",
) -> dict[str, Any]:
    return {
        "status": status,
        "claim_status": "construction-invalid" if status == "fail" else "diagnostic-demo",
        "netedit_status": netedit_status,
        "netedit_binary": netedit_binary,
        "netedit_process_id": None,
        "netedit_window_title": "",
        "netedit_network_file": str(input_file),
        "netedit_input_file": str(input_file),
        "command": [],
        "warnings": [warning],
    }


def launch_netedit(
    net_file: Path | str,
    *,
    gui_settings_file: Path | str | None = None,
    selection_file: Path | str | None = None,
    window_size: str | None = None,
    window_pos: str | None = None,
    netedit_binary: str = "netedit",
    detach_console: bool = False,
    which_func: Callable[[str], str | None] = shutil.which,
    popen_func: Callable[..., Any] = subprocess.Popen,
    platform_name: str = os.name,
) -> dict[str, Any]:
    """Open a SUMO network/config in Netedit without waiting for the GUI."""
    input_file = Path(net_file)
    try:
        open_mode = _netedit_input_mode(input_file)
    except ValueError as exc:
        return _failure_report(input_file, netedit_binary=netedit_binary, warning=str(exc))
    if not input_file.is_file():
        return _failure_report(
            input_file,
            netedit_binary=netedit_binary,
            warning=f"network file not found: {input_file}",
        )

    resolved_binary = which_func(netedit_binary)
    if resolved_binary is None:
        return _failure_report(
            input_file,
            netedit_binary=None,
            warning="netedit binary not found",
            status="blocked",
            netedit_status="unavailable",
        )

    try:
        command = _build_netedit_open_command(
            input_file,
            netedit_binary=resolved_binary,
            gui_settings_file=gui_settings_file,
            selection_file=selection_file,
            window_size=window_size,
            window_pos=window_pos,
        )
    except (FileNotFoundError, ValueError) as exc:
        return _failure_report(input_file, netedit_binary=resolved_binary, warning=str(exc))

    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "shell": False,
    }
    detached = bool(detach_console and platform_name == "nt")
    if detached:
        popen_kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
            subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            0x00000200,
        )
    try:
        process = popen_func(command, **popen_kwargs)
    except OSError as exc:
        report = _failure_report(
            input_file,
            netedit_binary=resolved_binary,
            warning=f"{type(exc).__name__}: {exc}",
        )
        report.update(
            {
                "netedit_open_mode": open_mode,
                "netedit_gui_settings_file": str(gui_settings_file) if gui_settings_file is not None else "",
                "netedit_selection_file": str(selection_file) if selection_file is not None else "",
                "netedit_window_size": window_size or "",
                "netedit_window_pos": window_pos or "",
                "netedit_detached": detached,
                "command": command,
            }
        )
        return report

    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "netedit_status": "opened",
        "netedit_binary": resolved_binary,
        "netedit_process_id": process.pid,
        "netedit_window_title": "",
        "netedit_network_file": str(input_file),
        "netedit_input_file": str(input_file),
        "netedit_open_mode": open_mode,
        "netedit_gui_settings_file": str(gui_settings_file) if gui_settings_file is not None else "",
        "netedit_selection_file": str(selection_file) if selection_file is not None else "",
        "netedit_window_size": window_size or "",
        "netedit_window_pos": window_pos or "",
        "netedit_detached": detached,
        "command": command,
        "warnings": [],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open an existing SUMO network in Netedit.")
    parser.add_argument("input_file", type=Path, help="A compiled .net.xml or a .sumocfg file")
    parser.add_argument("--netedit-binary", default="netedit")
    parser.add_argument("--gui-settings-file", type=Path)
    parser.add_argument("--selection-file", type=Path)
    parser.add_argument("--window-size")
    parser.add_argument("--window-pos")
    parser.add_argument(
        "--detach-console",
        action="store_true",
        help="Detach the non-blocking Netedit GUI process from this console on Windows",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    launch_func: Callable[..., dict[str, Any]] = launch_netedit,
) -> int:
    args = _parser().parse_args(argv)
    report = launch_func(
        args.input_file,
        netedit_binary=args.netedit_binary,
        gui_settings_file=args.gui_settings_file,
        selection_file=args.selection_file,
        window_size=args.window_size,
        window_pos=args.window_pos,
        detach_console=args.detach_console,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "pass" else 2


if __name__ == "__main__":  # pragma: no cover - exercised through the console entry point
    raise SystemExit(main())

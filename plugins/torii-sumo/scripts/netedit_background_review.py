from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PW_RENDERFULLCONTENT = 2
SW_SHOWNOACTIVATE = 4


@dataclass(frozen=True)
class TargetJunction:
    junction_id: str
    x: float
    y: float
    incoming_lanes: tuple[str, ...]
    junction_type: str


@dataclass(frozen=True)
class CaptureRequest:
    name: str
    mode: str
    selection_type: str
    selection_id: str


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_target_junction(net_file: Path, junction_id: str) -> TargetJunction:
    root = ET.parse(net_file).getroot()
    for junction in root.findall("junction"):
        if junction.get("id") != junction_id:
            continue
        return TargetJunction(
            junction_id=junction_id,
            x=float(junction.get("x", "0")),
            y=float(junction.get("y", "0")),
            incoming_lanes=tuple(junction.get("incLanes", "").split()),
            junction_type=str(junction.get("type", "")),
        )
    raise ValueError(f"Target junction {junction_id!r} is not present in {net_file}.")


def parse_point(value: str) -> tuple[float, float]:
    left, right = value.split(",", 1)
    return float(left), float(right)


def parse_size(value: str) -> tuple[int, int]:
    left, right = value.split(",", 1)
    return int(left), int(right)


def viewsettings_text(center: tuple[float, float], *, zoom: float) -> str:
    x, y = center
    return (
        "<viewsettings>\n"
        f'  <viewport zoom="{zoom:g}" x="{x:g}" y="{y:g}" angle="0"/>\n'
        '  <delay value="100"/>\n'
        "</viewsettings>\n"
    )


def selection_text(selection_type: str, selection_id: str) -> str:
    if selection_type not in {"junction", "lane"}:
        raise ValueError(f"Unsupported NetEdit selection type: {selection_type!r}")
    return f"{selection_type}:{selection_id}\n"


def mode_key(mode: str) -> str | None:
    return {"inspect": None, "connection": "C", "tls": "T"}[mode]


def capture_requests(target: TargetJunction) -> list[CaptureRequest]:
    requests = [
        CaptureRequest("target-inspect", "inspect", "junction", target.junction_id),
        CaptureRequest("target-tls", "tls", "junction", target.junction_id),
        CaptureRequest("target-connection", "connection", "junction", target.junction_id),
    ]
    requests.extend(
        CaptureRequest(
            f"incoming-{index:02d}-{safe_stem(lane_id)}",
            "connection",
            "lane",
            lane_id,
        )
        for index, lane_id in enumerate(target.incoming_lanes, start=1)
    )
    return requests


def safe_stem(value: str) -> str:
    safe = "".join(
        character
        if character.isascii() and (character.isalnum() or character in "-_.")
        else "_"
        for character in value
    )
    return safe.strip("._") or "selection"


def build_netedit_command(
    *,
    netedit_binary: str,
    net_file: Path,
    view_file: Path,
    selection_file: Path,
    window_size: str,
    window_pos: str,
    additional_file: Path | None = None,
) -> list[str]:
    command = [
        netedit_binary,
        "-s",
        str(net_file),
        "-g",
        str(view_file),
        "--selection-file",
        str(selection_file),
        "--registry-viewport",
        "false",
        "--window-size",
        window_size,
        "--window-pos",
        window_pos,
    ]
    if additional_file is not None:
        command += ["--additional-files", str(additional_file)]
    return command


def _windows_modules() -> tuple[Any, Any, Any, Any]:
    try:
        import win32con
        import win32gui
        import win32process
        import win32ui
    except ImportError as exc:  # pragma: no cover - Windows runtime guard
        raise SystemExit(
            "pywin32 is required for background NetEdit capture on Windows."
        ) from exc
    return win32con, win32gui, win32process, win32ui


def _windows_for_pid(pid: int) -> list[int]:
    _, win32gui, win32process, _ = _windows_modules()
    windows: list[int] = []

    def enum_window(hwnd: int, _: Any) -> bool:
        _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
        if window_pid == pid and win32gui.IsWindowVisible(hwnd):
            windows.append(hwnd)
        return True

    win32gui.EnumWindows(enum_window, None)
    return windows


def _wait_for_window(pid: int, *, timeout_seconds: float) -> int:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        windows = _windows_for_pid(pid)
        if windows:
            return windows[0]
        time.sleep(0.2)
    raise TimeoutError(f"NetEdit process {pid} did not create a visible window.")


def _post_mode_key(hwnd: int, mode: str) -> None:
    key = mode_key(mode)
    if key is None:
        return
    win32con, win32gui, _, _ = _windows_modules()
    virtual_key = ord(key)
    scan_code = ctypes.windll.user32.MapVirtualKeyW(virtual_key, 0)
    key_down = 1 | (scan_code << 16)
    key_up = key_down | (1 << 30) | (1 << 31)
    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, virtual_key, key_down)
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, virtual_key, key_up)


def _capture_window(hwnd: int, destination: Path) -> dict[str, Any]:
    _, win32gui, _, win32ui = _windows_modules()
    from PIL import Image

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width = right - left
    height = bottom - top
    window_dc = win32gui.GetWindowDC(hwnd)
    source_dc = win32ui.CreateDCFromHandle(window_dc)
    memory_dc = source_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source_dc, width, height)
    memory_dc.SelectObject(bitmap)
    try:
        result = ctypes.windll.user32.PrintWindow(
            hwnd, memory_dc.GetSafeHdc(), PW_RENDERFULLCONTENT
        )
        info = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        image = Image.frombuffer(
            "RGB",
            (info["bmWidth"], info["bmHeight"]),
            bits,
            "raw",
            "BGRX",
            0,
            1,
        ).copy()
        canvas = image.crop((min(230, width), min(100, height), width, height))
        luminance = canvas.convert("L")
        bright_pixels = sum(luminance.histogram()[200:])
        bright_pixel_fraction = bright_pixels / max(1, canvas.width * canvas.height)
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination)
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        memory_dc.DeleteDC()
        source_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)
    return {
        "print_window_result": int(result),
        "width": width,
        "height": height,
        "bright_pixel_fraction": bright_pixel_fraction,
        "sha256": file_sha256(destination),
    }


def _launch_no_activate(command: list[str]) -> subprocess.Popen[bytes]:
    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup_info.wShowWindow = SW_SHOWNOACTIVATE
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=startup_info,
    )


def _capture_request(
    *,
    request: CaptureRequest,
    net_file: Path,
    netedit_binary: str,
    output_dir: Path,
    center: tuple[float, float],
    zoom: float,
    window_size: str,
    window_pos: str,
    settle_seconds: float,
    additional_file: Path | None,
) -> dict[str, Any]:
    win32con, win32gui, _, _ = _windows_modules()
    view_file = output_dir / f"{request.name}.view.xml"
    selection_file = output_dir / f"{request.name}.selection.txt"
    screenshot_file = output_dir / f"{request.name}.png"
    view_file.write_text(viewsettings_text(center, zoom=zoom), encoding="utf-8")
    selection_file.write_text(
        selection_text(request.selection_type, request.selection_id),
        encoding="utf-8",
    )
    command = build_netedit_command(
        netedit_binary=netedit_binary,
        net_file=net_file,
        view_file=view_file,
        selection_file=selection_file,
        window_size=window_size,
        window_pos=window_pos,
        additional_file=additional_file,
    )
    foreground_before = int(win32gui.GetForegroundWindow())
    foreground_samples = [foreground_before]
    process = _launch_no_activate(command)
    hwnd = 0
    try:
        hwnd = _wait_for_window(process.pid, timeout_seconds=20.0)
        foreground_samples.append(int(win32gui.GetForegroundWindow()))
        width, height = parse_size(window_size)
        x, y = (int(value) for value in parse_point(window_pos))
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_BOTTOM,
            x,
            y,
            width,
            height,
            win32con.SWP_NOACTIVATE,
        )
        foreground_samples.append(int(win32gui.GetForegroundWindow()))
        time.sleep(settle_seconds)
        foreground_samples.append(int(win32gui.GetForegroundWindow()))
        _post_mode_key(hwnd, request.mode)
        foreground_samples.append(int(win32gui.GetForegroundWindow()))
        time.sleep(settle_seconds)
        foreground_samples.append(int(win32gui.GetForegroundWindow()))
        capture_attempts = []
        for attempt in range(1, 5):
            capture = _capture_window(hwnd, screenshot_file)
            capture_attempts.append(
                {
                    "attempt": attempt,
                    "bright_pixel_fraction": capture["bright_pixel_fraction"],
                }
            )
            if capture["bright_pixel_fraction"] >= 0.1:
                break
            time.sleep(0.75)
        capture["render_quality"] = (
            "pass" if capture["bright_pixel_fraction"] >= 0.1 else "blocked"
        )
        title = win32gui.GetWindowText(hwnd)
        foreground_samples.append(int(win32gui.GetForegroundWindow()))
    finally:
        if hwnd:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.terminate()
    foreground_after = int(win32gui.GetForegroundWindow())
    foreground_samples.append(foreground_after)
    return {
        "name": request.name,
        "mode": request.mode,
        "selection_type": request.selection_type,
        "selection_id": request.selection_id,
        "command": command,
        "pid": process.pid,
        "window_title": title,
        "view_file": str(view_file),
        "selection_file": str(selection_file),
        "screenshot_file": str(screenshot_file),
        "foreground_before": foreground_before,
        "foreground_after": foreground_after,
        "foreground_samples": foreground_samples,
        "foreground_unchanged": all(
            sample == foreground_before for sample in foreground_samples
        ),
        "capture_attempts": capture_attempts,
        **capture,
    }


def run_background_review(
    *,
    net_file: Path,
    target_junction_id: str,
    output_dir: Path,
    netedit_binary: str,
    center: tuple[float, float] | None,
    zoom: float,
    window_size: str,
    window_pos: str,
    settle_seconds: float,
    additional_file: Path | None,
) -> dict[str, Any]:
    if sys.platform != "win32":
        raise SystemExit("Background NetEdit capture is currently Windows-only.")
    candidate = net_file.resolve(strict=True)
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = read_target_junction(candidate, target_junction_id)
    view_center = center or (target.x, target.y)
    executable = shutil.which(netedit_binary) or netedit_binary
    effective_additional = (
        additional_file.resolve(strict=True) if additional_file is not None else None
    )
    captures = [
        _capture_request(
            request=request,
            net_file=candidate,
            netedit_binary=executable,
            output_dir=destination,
            center=view_center,
            zoom=zoom,
            window_size=window_size,
            window_pos=window_pos,
            settle_seconds=settle_seconds,
            additional_file=effective_additional,
        )
        for request in capture_requests(target)
    ]
    report = {
        "schema": "torii.netedit-background-review/v1",
        "status": (
            "review_material_ready"
            if all(
                item["print_window_result"] == 1
                and item["foreground_unchanged"]
                and item["render_quality"] == "pass"
                for item in captures
            )
            else "blocked"
        ),
        "candidate_file": str(candidate),
        "candidate_sha256": file_sha256(candidate),
        "netedit_binary": executable,
        "target_junction": {
            "id": target.junction_id,
            "type": target.junction_type,
            "x": target.x,
            "y": target.y,
            "incoming_lanes": list(target.incoming_lanes),
        },
        "view_center": list(view_center),
        "zoom": zoom,
        "window_size": window_size,
        "mode_delivery": "target-window WM_KEYDOWN/WM_KEYUP",
        "capture_delivery": "target-window PrintWindow(PW_RENDERFULLCONTENT)",
        "selection_delivery": "NetEdit --selection-file",
        "global_keyboard_or_mouse_input_used": False,
        "foreground_unchanged": all(
            item["foreground_unchanged"] for item in captures
        ),
        "captures": captures,
        "claim_boundary": (
            "These images provide background NetEdit mode and selection context. "
            "They do not replace the code-native exact lane/via/request/TLS audit, "
            "do not constitute human validation, and do not authorize promotion."
        ),
        "automatic_promotion_gate": "blocked",
    }
    report_file = destination / "netedit-background-review.json"
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {**report, "report_file": str(report_file)}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture Inspect, Traffic Light, and Connection mode evidence from "
            "a background NetEdit window without global keyboard or mouse input."
        )
    )
    parser.add_argument("--net", required=True)
    parser.add_argument("--target-junction", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--netedit-binary", default="netedit")
    parser.add_argument("--view-center")
    parser.add_argument("--zoom", type=float, default=500.0)
    parser.add_argument("--window-size", default="1400,1000")
    parser.add_argument("--window-pos", default="20,20")
    parser.add_argument("--settle-seconds", type=float, default=1.5)
    parser.add_argument("--additional-file")
    return parser.parse_args()


def main() -> int:
    args = _args()
    report = run_background_review(
        net_file=Path(args.net),
        target_junction_id=args.target_junction,
        output_dir=Path(args.out_dir),
        netedit_binary=args.netedit_binary,
        center=parse_point(args.view_center) if args.view_center else None,
        zoom=args.zoom,
        window_size=args.window_size,
        window_pos=args.window_pos,
        settle_seconds=args.settle_seconds,
        additional_file=Path(args.additional_file) if args.additional_file else None,
    )
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "review_material_ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())

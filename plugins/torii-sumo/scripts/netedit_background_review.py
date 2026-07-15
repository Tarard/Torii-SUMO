from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from torii_sumo.core.artifact_io import write_json_atomic
from torii_sumo.core.candidate_contracts import file_sha256
from torii_sumo.core.tls_ownership import audit_tls_ownership_rebuild


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


@dataclass(frozen=True)
class CandidateReviewIdentity:
    candidate_role: str
    summary_file: Path
    manifest_file: Path
    candidate_evidence_file: Path | None
    source_file: Path
    candidate_file: Path
    review_overlay_file: Path | None
    source_sha256: str
    candidate_sha256: str
    target_junction_id: str
    tls_ownership_recheck: dict[str, Any]


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read {label} JSON at {path}.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return value


def _recorded_path(value: Any, *, base_dir: Path, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} path is missing from the workflow summary.")
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    try:
        return path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"{label} does not exist: {path}") from exc


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _require_recorded_hash(
    *,
    path: Path,
    expected_hash: Any,
    label: str,
) -> str:
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ValueError(f"{label} SHA-256 is missing or malformed.")
    observed_hash = file_sha256(path)
    if observed_hash != expected_hash:
        raise ValueError(f"{label} SHA-256 mismatch: expected {expected_hash}, observed {observed_hash}.")
    return observed_hash


def _require_manifest_binding(
    *,
    manifest: dict[str, Any],
    manifest_dir: Path,
    artifact_path: Path,
    expected_hash: str,
    label: str,
) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("Manifest artifacts must be a JSON array.")
    matching_hashes: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        raw_path = artifact.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        recorded = Path(raw_path)
        if not recorded.is_absolute():
            recorded = manifest_dir / recorded
        if _path_key(recorded) == _path_key(artifact_path):
            matching_hashes.append(str(artifact.get("sha256", "")))
    if not matching_hashes:
        raise ValueError(f"Manifest does not bind the {label}: {artifact_path}")
    if expected_hash not in matching_hashes:
        raise ValueError(f"Manifest hash mismatch for {label}: expected {expected_hash}, recorded {matching_hashes}.")


def load_bound_candidate_identity(
    *,
    summary_file: Path,
    manifest_file: Path | None = None,
    candidate_role: str = "primary",
) -> CandidateReviewIdentity:
    """Resolve one review candidate from a hash-bound workflow bundle."""

    summary_path = summary_file.resolve(strict=True)
    summary = _read_json_object(summary_path, "workflow summary")
    if summary.get("automatic_promotion_gate") != "blocked":
        raise ValueError("Workflow summary must keep automatic promotion blocked.")
    if candidate_role not in {"primary", "nema-topology"}:
        raise ValueError(f"Unsupported candidate review role: {candidate_role}")

    source = _recorded_path(
        summary.get("source_net_file"),
        base_dir=summary_path.parent,
        label="source network",
    )
    candidate_evidence: Path | None = None
    candidate_record: dict[str, Any] = summary
    if candidate_role == "nema-topology":
        topology_summary = summary.get("tls_topology")
        if not isinstance(topology_summary, dict):
            raise ValueError("Workflow summary lacks a TLS topology stage.")
        if topology_summary.get("status") != "candidate_ready_for_review":
            raise ValueError("NEMA topology review requires candidate_ready_for_review.")
        candidate_evidence = _recorded_path(
            topology_summary.get("artifact_file"),
            base_dir=summary_path.parent,
            label="NEMA topology evidence",
        )
        candidate_record = _read_json_object(candidate_evidence, "NEMA topology evidence")
        if candidate_record.get("automatic_promotion_gate") != "blocked":
            raise ValueError("NEMA topology evidence must keep automatic promotion blocked.")
        if candidate_record.get("status") != "candidate_ready_for_review":
            raise ValueError("NEMA topology evidence is not review-ready.")
    candidate = _recorded_path(
        candidate_record.get("candidate_net_file"),
        base_dir=summary_path.parent,
        label=f"{candidate_role} candidate network",
    )
    if _path_key(source) == _path_key(candidate):
        raise ValueError(
            "Candidate review refused: the summary points candidate_file at the immutable source baseline."
        )

    source_hash = _require_recorded_hash(
        path=source,
        expected_hash=summary.get("source_sha256"),
        label="source network",
    )
    candidate_hash = _require_recorded_hash(
        path=candidate,
        expected_hash=candidate_record.get("candidate_sha256"),
        label=f"{candidate_role} candidate network",
    )
    if source_hash == candidate_hash:
        raise ValueError("Candidate review refused: candidate content is identical to the immutable source baseline.")

    manifest_path = (
        manifest_file.resolve(strict=True)
        if manifest_file is not None
        else (summary_path.parent / "manifest.json").resolve(strict=True)
    )
    manifest = _read_json_object(manifest_path, "artifact manifest")
    if manifest.get("automatic_promotion_gate") != "blocked":
        raise ValueError("Artifact manifest must keep automatic promotion blocked.")

    _require_manifest_binding(
        manifest=manifest,
        manifest_dir=manifest_path.parent,
        artifact_path=summary_path,
        expected_hash=file_sha256(summary_path),
        label="workflow summary",
    )
    _require_manifest_binding(
        manifest=manifest,
        manifest_dir=manifest_path.parent,
        artifact_path=source,
        expected_hash=source_hash,
        label="source network",
    )
    _require_manifest_binding(
        manifest=manifest,
        manifest_dir=manifest_path.parent,
        artifact_path=candidate,
        expected_hash=candidate_hash,
        label="candidate network",
    )
    if candidate_evidence is not None:
        _require_manifest_binding(
            manifest=manifest,
            manifest_dir=manifest_path.parent,
            artifact_path=candidate_evidence,
            expected_hash=file_sha256(candidate_evidence),
            label="NEMA topology evidence",
        )

    tls_ownership = summary.get("tls_ownership")
    if not isinstance(tls_ownership, dict):
        raise ValueError("Workflow summary does not contain a TLS ownership report.")
    if tls_ownership.get("status") != "pass":
        raise ValueError("Stored TLS ownership gate is not pass.")
    source_junction_ids = tls_ownership.get("target_source_junction_ids")
    if not isinstance(source_junction_ids, list) or not source_junction_ids:
        raise ValueError(
            "TLS ownership report lacks stable target_source_junction_ids; "
            "rerun the isolated-junction workflow before visual review."
        )
    target_junction_id = str(tls_ownership.get("target_candidate_junction_id", ""))
    expected_controller_ids = tls_ownership.get("expected_controller_ids")
    expected_connection_count = tls_ownership.get("expected_controlled_connection_count")
    if not target_junction_id:
        raise ValueError("TLS ownership report lacks a target candidate junction.")
    if not isinstance(expected_controller_ids, list) or not expected_controller_ids:
        raise ValueError("TLS ownership report lacks expected controller IDs.")
    if not isinstance(expected_connection_count, int):
        raise ValueError("TLS ownership report lacks the expected movement count.")

    recheck = audit_tls_ownership_rebuild(
        source_net=source,
        candidate_net=candidate,
        target_source_junction_ids=tuple(map(str, source_junction_ids)),
        target_candidate_junction_id=target_junction_id,
        expected_controller_ids=tuple(map(str, expected_controller_ids)),
        expected_controlled_connection_count=expected_connection_count,
        report_schema="torii.netedit-candidate-tls-identity/v1",
    )
    if recheck["status"] != "pass":
        raise ValueError("Candidate TLS ownership recheck failed: " + json.dumps(recheck["findings"], sort_keys=True))
    if candidate_role == "primary":
        for key in (
            "candidate",
            "residual_source_junction_ids",
            "residual_old_controller_ids",
        ):
            if tls_ownership.get(key) != recheck.get(key):
                raise ValueError(f"Stored TLS ownership evidence disagrees with candidate: {key}.")
    else:
        topology_tls = candidate_record.get("tls_ownership")
        if not isinstance(topology_tls, dict):
            raise ValueError("NEMA topology evidence lacks TLS ownership proof.")
        observed_topology_tls = {
            "status": recheck["status"],
            "controller_ids": recheck["candidate"]["target_controller_ids"],
            "controlled_connection_count": recheck["candidate"]["target_controlled_connection_count"],
            "signal_group_count": recheck["candidate"]["target_signal_group_count"],
        }
        for key, value in observed_topology_tls.items():
            if topology_tls.get(key) != value:
                raise ValueError(f"NEMA TLS ownership evidence disagrees with candidate: {key}.")

    overlay: Path | None = None
    overlay_value: Any = summary.get("review_overlay_file")
    if candidate_role == "nema-topology":
        standard = candidate_record.get("standard_builder") or {}
        overlay_value = standard.get("review_overlay_file")
    if overlay_value:
        overlay = _recorded_path(
            overlay_value,
            base_dir=summary_path.parent,
            label="review overlay",
        )
        _require_manifest_binding(
            manifest=manifest,
            manifest_dir=manifest_path.parent,
            artifact_path=overlay,
            expected_hash=file_sha256(overlay),
            label="review overlay",
        )

    return CandidateReviewIdentity(
        candidate_role=candidate_role,
        summary_file=summary_path,
        manifest_file=manifest_path,
        candidate_evidence_file=candidate_evidence,
        source_file=source,
        candidate_file=candidate,
        review_overlay_file=overlay,
        source_sha256=source_hash,
        candidate_sha256=candidate_hash,
        target_junction_id=target_junction_id,
        tls_ownership_recheck=recheck,
    )


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
    return [
        CaptureRequest("target-inspect", "inspect", "junction", target.junction_id),
        CaptureRequest("target-tls", "tls", "junction", target.junction_id),
        CaptureRequest("target-connection", "connection", "junction", target.junction_id),
    ]


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
        raise SystemExit("pywin32 is required for background NetEdit capture on Windows.") from exc
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


def _post_mode_key(hwnd: int, mode: str) -> dict[str, Any]:
    key = mode_key(mode)
    if key is None:
        return {
            "status": "not_required",
            "mode": mode,
            "foreground_context_unchanged": True,
        }
    win32con, win32gui, _, _ = _windows_modules()
    canvases: list[int] = []

    def find_canvas(child: int, _: Any) -> bool:
        if win32gui.GetClassName(child) == "FXGLCanvas":
            canvases.append(child)
        return True

    win32gui.EnumChildWindows(hwnd, find_canvas, None)
    target = canvases[0] if canvases else hwnd
    foreground_before = _foreground_context()
    virtual_key = ord(key)
    scan_code = ctypes.windll.user32.MapVirtualKeyW(virtual_key, 0)
    key_down = 1 | (scan_code << 16)
    key_up = key_down | (1 << 30) | (1 << 31)
    # FOX ignores shortcut messages for an inactive top-level window. Giving
    # only the NetEdit canvas internal activation/focus messages lets FOX route
    # the shortcut while Windows keeps the user's foreground application.
    win32gui.SendMessage(
        hwnd,
        win32con.WM_ACTIVATE,
        win32con.WA_ACTIVE,
        foreground_before["hwnd"],
    )
    win32gui.SendMessage(target, win32con.WM_SETFOCUS, foreground_before["hwnd"], 0)
    for destination in {target, hwnd}:
        win32gui.SendMessage(
            destination,
            win32con.WM_KEYDOWN,
            virtual_key,
            key_down,
        )
        win32gui.SendMessage(
            destination,
            win32con.WM_KEYUP,
            virtual_key,
            key_up,
        )
    win32gui.SendMessage(target, win32con.WM_KILLFOCUS, foreground_before["hwnd"], 0)
    win32gui.SendMessage(
        hwnd,
        win32con.WM_ACTIVATE,
        win32con.WA_INACTIVE,
        foreground_before["hwnd"],
    )
    foreground_after = _foreground_context()
    return {
        "status": "pass",
        "mode": mode,
        "virtual_key": virtual_key,
        "target_hwnd": target,
        "target_class": win32gui.GetClassName(target),
        "foreground_before": foreground_before,
        "foreground_after": foreground_after,
        "foreground_context_unchanged": (
            foreground_before["process_id"] == foreground_after["process_id"]
            and foreground_before["hwnd"] == foreground_after["hwnd"]
        ),
    }


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
        result = ctypes.windll.user32.PrintWindow(hwnd, memory_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
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


def _foreground_context() -> dict[str, int]:
    _, win32gui, win32process, _ = _windows_modules()
    hwnd = int(win32gui.GetForegroundWindow())
    process_id = 0
    if hwnd:
        _, process_id = win32process.GetWindowThreadProcessId(hwnd)
    return {"hwnd": hwnd, "process_id": int(process_id)}


def _force_foreground_window(hwnd: int) -> bool:
    """Restore a foreground window across process input-thread boundaries."""

    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    current_thread = int(kernel32.GetCurrentThreadId())
    foreground_hwnd = int(user32.GetForegroundWindow())
    foreground_thread = int(user32.GetWindowThreadProcessId(foreground_hwnd, None))
    target_thread = int(user32.GetWindowThreadProcessId(hwnd, None))
    attached_threads = []
    for thread_id in {foreground_thread, target_thread}:
        if thread_id and thread_id != current_thread:
            if user32.AttachThreadInput(current_thread, thread_id, True):
                attached_threads.append(thread_id)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        for thread_id in reversed(attached_threads):
            user32.AttachThreadInput(current_thread, thread_id, False)
    return int(user32.GetForegroundWindow()) == hwnd


def _observe_and_restore_foreground(
    expected: dict[str, int],
) -> dict[str, Any]:
    _, win32gui, _, _ = _windows_modules()
    observed = _foreground_context()
    attempted = False
    if expected["hwnd"] and observed["process_id"] != expected["process_id"] and win32gui.IsWindow(expected["hwnd"]):
        attempted = True
        _force_foreground_window(expected["hwnd"])
        time.sleep(0.05)
    restored = _foreground_context()
    return {
        "observed": observed,
        "restore_attempted": attempted,
        "restored": restored,
        "context_restored": (expected["process_id"] == 0 or restored["process_id"] == expected["process_id"]),
    }


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
    foreground_context_before = _foreground_context()
    foreground_before = foreground_context_before["hwnd"]
    foreground_samples = [foreground_before]
    foreground_restore_events: list[dict[str, Any]] = []
    process = _launch_no_activate(command)
    hwnd = 0
    try:
        hwnd = _wait_for_window(process.pid, timeout_seconds=20.0)
        foreground_restore_events.append(_observe_and_restore_foreground(foreground_context_before))
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
        foreground_restore_events.append(_observe_and_restore_foreground(foreground_context_before))
        foreground_samples.append(int(win32gui.GetForegroundWindow()))
        time.sleep(settle_seconds)
        foreground_samples.append(int(win32gui.GetForegroundWindow()))
        mode_delivery = _post_mode_key(hwnd, request.mode)
        foreground_restore_events.append(_observe_and_restore_foreground(foreground_context_before))
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
        capture["render_quality"] = "pass" if capture["bright_pixel_fraction"] >= 0.1 else "blocked"
        title = win32gui.GetWindowText(hwnd)
        foreground_samples.append(int(win32gui.GetForegroundWindow()))
    finally:
        if hwnd:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        foreground_restore_events.append(_observe_and_restore_foreground(foreground_context_before))
    foreground_context_after = _foreground_context()
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
        "mode_delivery": mode_delivery,
        "foreground_before": foreground_before,
        "foreground_after": foreground_after,
        "foreground_context_before": foreground_context_before,
        "foreground_context_after": foreground_context_after,
        "foreground_context_restored": (
            all(event["context_restored"] for event in foreground_restore_events)
            and (
                foreground_context_before["process_id"] == 0
                or foreground_context_after["process_id"] == foreground_context_before["process_id"]
            )
        ),
        "foreground_restore_events": foreground_restore_events,
        "foreground_samples": foreground_samples,
        "foreground_unchanged": all(sample == foreground_before for sample in foreground_samples),
        "capture_attempts": capture_attempts,
        **capture,
    }


def run_background_review(
    *,
    summary_file: Path,
    manifest_file: Path | None,
    output_dir: Path,
    netedit_binary: str,
    center: tuple[float, float] | None,
    zoom: float,
    window_size: str,
    window_pos: str,
    settle_seconds: float,
    candidate_role: str = "primary",
) -> dict[str, Any]:
    identity = load_bound_candidate_identity(
        summary_file=summary_file,
        manifest_file=manifest_file,
        candidate_role=candidate_role,
    )
    if sys.platform != "win32":
        raise SystemExit("Background NetEdit capture is currently Windows-only.")
    candidate = identity.candidate_file
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = read_target_junction(candidate, identity.target_junction_id)
    view_center = center or (target.x, target.y)
    executable = shutil.which(netedit_binary) or netedit_binary
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
            additional_file=identity.review_overlay_file,
        )
        for request in capture_requests(target)
    ]
    capture_hashes = [item["sha256"] for item in captures]
    mode_images_distinct = len(set(capture_hashes)) == len(capture_hashes)
    report = {
        "schema": "torii.netedit-background-review/v3",
        "status": (
            "review_material_ready"
            if all(
                item["print_window_result"] == 1
                and item["render_quality"] == "pass"
                and item["foreground_unchanged"]
                and item["foreground_context_restored"]
                and item["mode_delivery"]["foreground_context_unchanged"]
                for item in captures
            )
            and mode_images_distinct
            else "blocked"
        ),
        "candidate_role": identity.candidate_role,
        "summary_file": str(identity.summary_file),
        "summary_sha256": file_sha256(identity.summary_file),
        "manifest_file": str(identity.manifest_file),
        "manifest_sha256": file_sha256(identity.manifest_file),
        "candidate_evidence_file": (
            str(identity.candidate_evidence_file) if identity.candidate_evidence_file is not None else None
        ),
        "source_file": str(identity.source_file),
        "source_sha256": identity.source_sha256,
        "candidate_file": str(candidate),
        "candidate_sha256": identity.candidate_sha256,
        "review_overlay_file": (
            str(identity.review_overlay_file) if identity.review_overlay_file is not None else None
        ),
        "tls_ownership_recheck": identity.tls_ownership_recheck,
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
        "capture_session_count": len(captures),
        "global_keyboard_or_mouse_input_used": False,
        "foreground_context_restored": all(item["foreground_context_restored"] for item in captures),
        "mode_images_distinct": mode_images_distinct,
        "captures": captures,
        "claim_boundary": (
            "These images provide background NetEdit mode and selection context. "
            "They do not replace the code-native exact lane/via/request/TLS audit, "
            "do not constitute human validation, and do not authorize promotion."
        ),
        "automatic_promotion_gate": "blocked",
    }
    report_file = destination / "netedit-background-review.json"
    write_json_atomic(report_file, report)
    return {**report, "report_file": str(report_file)}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture Inspect, Traffic Light, and Connection mode evidence from "
            "a background NetEdit window without global keyboard or mouse input."
        )
    )
    parser.add_argument("--summary", required=True)
    parser.add_argument("--manifest")
    parser.add_argument(
        "--candidate-role",
        choices=("primary", "nema-topology"),
        default="primary",
    )
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--netedit-binary", default="netedit")
    parser.add_argument("--view-center")
    parser.add_argument("--zoom", type=float, default=500.0)
    parser.add_argument("--window-size", default="1400,1000")
    parser.add_argument("--window-pos", default="20,20")
    parser.add_argument("--settle-seconds", type=float, default=1.5)
    return parser.parse_args()


def main() -> int:
    args = _args()
    report = run_background_review(
        summary_file=Path(args.summary),
        manifest_file=Path(args.manifest) if args.manifest else None,
        output_dir=Path(args.out_dir),
        netedit_binary=args.netedit_binary,
        center=parse_point(args.view_center) if args.view_center else None,
        zoom=args.zoom,
        window_size=args.window_size,
        window_pos=args.window_pos,
        settle_seconds=args.settle_seconds,
        candidate_role=args.candidate_role,
    )
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "review_material_ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())

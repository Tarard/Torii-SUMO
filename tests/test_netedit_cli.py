from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

import torii_sumo.core.netedit as netedit
from torii_sumo.core.netedit import NeteditTargetSession, launch_netedit, main


class _Process:
    pid = 4711


def test_launch_netedit_uses_compiled_network_option_and_never_plain_node_option(tmp_path: Path) -> None:
    net_file = tmp_path / "corridor.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_popen(command: list[str], **kwargs: object) -> _Process:
        calls.append((command, kwargs))
        return _Process()

    report = launch_netedit(
        net_file,
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=fake_popen,
    )

    command, kwargs = calls[0]
    assert report["status"] == "pass"
    assert command == [
        "C:/SUMO/bin/netedit.exe",
        "--sumo-net-file",
        str(net_file),
        "--registry-viewport",
        "false",
    ]
    assert "-n" not in command
    assert kwargs["shell"] is False


def test_launch_netedit_rejects_wrong_input_type_before_starting_process(tmp_path: Path) -> None:
    node_file = tmp_path / "corridor.nod.xml"
    node_file.write_text("<nodes/>", encoding="utf-8")
    started = False

    def fake_popen(_command: list[str], **_kwargs: object) -> _Process:
        nonlocal started
        started = True
        return _Process()

    report = launch_netedit(
        node_file,
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=fake_popen,
    )

    assert report["status"] == "fail"
    assert "expected .net.xml or .sumocfg" in report["warnings"][0]
    assert started is False


def test_launch_netedit_requires_a_file_not_a_directory(tmp_path: Path) -> None:
    directory = tmp_path / "corridor.net.xml"
    directory.mkdir()

    report = launch_netedit(directory, which_func=lambda _name: "C:/SUMO/bin/netedit.exe")

    assert report["status"] == "fail"
    assert "network file not found" in report["warnings"][0]


def test_netedit_cli_reuses_core_launcher(tmp_path: Path, capsys) -> None:
    net_file = tmp_path / "corridor.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_launch(path: Path, **kwargs: object) -> dict[str, object]:
        captured["path"] = path
        captured.update(kwargs)
        return {"status": "pass", "netedit_status": "opened", "command": ["netedit", "--sumo-net-file", str(path)]}

    returncode = main(
        [str(net_file), "--netedit-binary", "netedit-custom", "--detach-console"],
        launch_func=fake_launch,
    )

    assert returncode == 0
    assert captured["path"] == net_file
    assert captured["netedit_binary"] == "netedit-custom"
    assert captured["detach_console"] is True
    assert '"netedit_status": "opened"' in capsys.readouterr().out


def test_launch_netedit_can_detach_non_blocking_windows_gui(tmp_path: Path) -> None:
    net_file = tmp_path / "corridor.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_popen(_command: list[str], **kwargs: object) -> _Process:
        captured.update(kwargs)
        return _Process()

    report = launch_netedit(
        net_file,
        detach_console=True,
        platform_name="nt",
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=fake_popen,
    )

    assert report["netedit_detached"] is True
    assert isinstance(captured["creationflags"], int)
    assert captured["shell"] is False


def test_build_netedit_open_command_validates_and_emits_native_test_file(tmp_path: Path) -> None:
    net_file = tmp_path / "corridor.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")
    gui_settings = tmp_path / "view.xml"
    gui_settings.write_text("<viewsettings/>", encoding="utf-8")
    test_file = tmp_path / "connection.test.py"

    with pytest.raises(FileNotFoundError, match="test file"):
        netedit._build_netedit_open_command(net_file, test_file=test_file)

    test_file.write_text('netedit.changeMode("connection")\n', encoding="utf-8")
    command = netedit._build_netedit_open_command(
        net_file,
        gui_settings_file=gui_settings,
        test_file=test_file,
    )

    assert command[command.index("-g") + 2 : command.index("-g") + 4] == [
        "--test-file",
        str(test_file),
    ]


class _SessionProcess:
    pid = 9001

    def poll(self):
        return None

    def wait(self, timeout):
        return 0

    def terminate(self):
        return None

    def kill(self):
        return None


def _patch_target_session_runtime(
    monkeypatch: pytest.MonkeyPatch,
    candidate: Path,
) -> tuple[list[tuple[object, ...]], list[int]]:
    deliveries: list[tuple[object, ...]] = []
    owned_pids: list[int] = []
    frame = [0]

    class FakeCon:
        WM_CLOSE = 16

    class FakeGui:
        @staticmethod
        def GetWindowText(hwnd):
            return f"netedit-{hwnd}"

        @staticmethod
        def PostMessage(*args):
            deliveries.append(("close", *args))

    def require_owned(hwnd: int, pid: int) -> None:
        assert hwnd == 42
        owned_pids.append(pid)

    def capture(hwnd: int, destination: Path) -> dict[str, object]:
        assert hwnd == 42
        Image.new("RGB", (800, 600), (frame[0], frame[0], frame[0])).save(destination)
        return {
            "print_window_result": 1,
            "coordinate_space": "netedit_top_level_client",
            "width": 800,
            "height": 600,
            "sha256": netedit._file_sha256(destination),
        }

    def perform_input(hwnd: int, pid: int, action: dict[str, object], **_kwargs):
        deliveries.append((action["type"], hwnd, pid, action))
        if action["type"] == "key" and action["virtual_key"] == ord("S") and action["modifier_keys"] == [0x11]:
            candidate.write_text(candidate.read_text(encoding="utf-8") + "<!--saved-->", encoding="utf-8")
        frame[0] += 1
        return {"send_input_event_count": 1, "restore": {"restored": True}}

    monkeypatch.setattr(netedit, "_wait_for_netedit_window", lambda pid, timeout: 42)
    monkeypatch.setattr(
        netedit,
        "_wait_for_netedit_network_loaded",
        lambda hwnd, pid, candidate_name, timeout: f"{candidate_name} - netedit",
    )
    monkeypatch.setattr(netedit, "_require_owned_window", require_owned)
    monkeypatch.setattr(netedit, "_capture_target_window", capture)
    monkeypatch.setattr(netedit, "_client_size", lambda hwnd: (800, 600))
    monkeypatch.setattr(netedit, "_perform_real_input", perform_input)
    monkeypatch.setattr(
        netedit,
        "_ensure_english_window_layout",
        lambda _hwnd: {"status": "pass", "layout_name": "00000409", "changed_by_torii": False},
    )
    monkeypatch.setattr(
        netedit,
        "_enable_per_monitor_dpi_awareness",
        lambda: {"status": "enabled_or_already_configured", "mode": "per_monitor_v2"},
    )
    monkeypatch.setattr(
        netedit,
        "_activate_target_window",
        lambda hwnd, pid: {
            "previous_foreground_hwnd": 7,
            "previous_focus_hwnd": 7,
            "previous_cursor": [10, 20],
            "target_foreground_hwnd": hwnd,
            "target_focus_hwnd": hwnd,
        },
    )
    monkeypatch.setattr(
        netedit,
        "_restore_input_context",
        lambda context: {"foreground_hwnd": 7, "cursor": [10, 20], "restored": True},
    )
    monkeypatch.setattr(netedit, "_windows_modules", lambda: (FakeCon(), FakeGui(), None, None))
    monkeypatch.setattr(netedit.time, "sleep", lambda _seconds: None)
    return deliveries, owned_pids


def test_wait_for_netedit_network_loaded_rejects_the_loading_window(monkeypatch) -> None:
    titles = iter(["netedit 1.27.1", "candidate.net.xml - netedit 1.27.1"])

    class FakeGui:
        @staticmethod
        def GetWindowText(_hwnd):
            return next(titles)

    monkeypatch.setattr(netedit, "_windows_modules", lambda: (None, FakeGui(), None, None))
    monkeypatch.setattr(netedit, "_require_owned_window", lambda _hwnd, _pid: None)
    monkeypatch.setattr(netedit.time, "sleep", lambda _seconds: None)

    title = netedit._wait_for_netedit_network_loaded(42, 9001, "candidate.net.xml", 1.0)

    assert title == "candidate.net.xml - netedit 1.27.1"


def test_target_session_snapshots_native_test_file_and_skips_render_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text("<net/>", encoding="utf-8")
    test_file = tmp_path / "connection.test.py"
    test_file.write_text('netedit.changeMode("connection")\n', encoding="utf-8")
    candidate = tmp_path / "working.net.xml"
    deliveries, _ = _patch_target_session_runtime(monkeypatch, candidate)
    activations: list[tuple[int, int]] = []
    monkeypatch.setattr(
        netedit,
        "_activate_target_window",
        lambda hwnd, pid: activations.append((hwnd, pid)),
    )

    session = NeteditTargetSession(
        source,
        candidate,
        tmp_path / "session",
        expected_source_sha256=netedit._file_sha256(source),
        test_file=test_file,
        activate_for_render=False,
        platform_name="win32",
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=lambda _command, **_kwargs: _SessionProcess(),
        settle_seconds=0,
    )
    opened = session.open()

    assert activations == []
    assert "--test-file" in session.command
    snapshot = tmp_path / "session" / "preloaded" / "test.py"
    assert session.command[session.command.index("--test-file") + 1] == str(snapshot)
    assert snapshot.read_bytes() == test_file.read_bytes()
    assert opened["capture"]["width"] == 800
    session.abort("test_complete")
    assert [item for item in deliveries if item[0] != "close"] == []


def test_target_session_copies_source_records_every_step_and_never_promotes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text("<net/>", encoding="utf-8")
    candidate = tmp_path / "candidate.net.xml"
    gui_settings = tmp_path / "view.xml"
    gui_settings.write_text("<viewsettings/>", encoding="utf-8")
    selection = tmp_path / "selection.txt"
    selection.write_text("junction:j1\n", encoding="utf-8")
    deliveries, owned_pids = _patch_target_session_runtime(monkeypatch, candidate)
    session = NeteditTargetSession(
        source,
        candidate,
        tmp_path / "session",
        expected_source_sha256=netedit._file_sha256(source),
        gui_settings_file=gui_settings,
        selection_file=selection,
        platform_name="win32",
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=lambda _command, **_kwargs: _SessionProcess(),
        settle_seconds=0,
    )

    session.open()
    observed = session.observe("before merge")
    clicked = session.act(
        {
            "type": "click",
            "x": 120,
            "y": 240,
            "expected_screenshot_sha256": observed["screenshot_sha256"],
        }
    )
    keyed = session.act(
        {
            "type": "key",
            "virtual_key": 116,
            "expected_screenshot_sha256": clicked["screenshot_sha256"],
        }
    )
    dragged = session.act(
        {
            "type": "drag",
            "x": 100,
            "y": 100,
            "to_x": 200,
            "to_y": 180,
            "expected_screenshot_sha256": keyed["screenshot_sha256"],
        }
    )
    report = session.finalize(expected_screenshot_sha256=dragged["screenshot_sha256"])

    assert source.read_text(encoding="utf-8") == "<net/>"
    assert candidate.read_text(encoding="utf-8").endswith("<!--saved-->")
    assert report["status"] == "finalized"
    assert report["source_unchanged"] is True
    assert report["automatic_promotion_gate"] == "blocked"
    assert report["global_keyboard_or_mouse_input_used"] is True
    assert report["candidate_changed"] is True
    assert report["candidate_xml_parseable"] is True
    assert report["semantic_edit_status"] == "unverified_candidate_delta"
    assert report["semantic_edit_success"] is False
    assert report["dpi_awareness"]["mode"] == "per_monitor_v2"
    assert {item["role"] for item in report["preloaded_artifacts"]} == {"gui_settings", "selection"}
    assert "-g" in report["command"] and "--selection-file" in report["command"]
    assert [step["kind"] for step in report["steps"]] == ["open", "observe", "act", "act", "act", "finalize"]
    assert all(Path(step["screenshot_file"]).is_file() for step in report["steps"])
    assert all(len(step["screenshot_sha256"]) == 64 for step in report["steps"])
    assert any(item[0] == "click" and item[3]["x"] == 120 for item in deliveries)
    assert any(item[0] == "key" and item[3]["virtual_key"] == 116 for item in deliveries)
    assert any(item[0] == "drag" and item[3]["to_x"] == 200 for item in deliveries)
    assert any(item[0] == "key" and item[3]["virtual_key"] == ord("S") for item in deliveries)
    assert owned_pids and set(owned_pids) == {9001}


def test_target_session_rejects_outside_click_and_abort_remains_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text("<net/>", encoding="utf-8")
    candidate = tmp_path / "candidate.net.xml"
    _patch_target_session_runtime(monkeypatch, candidate)
    session = NeteditTargetSession(
        source,
        candidate,
        tmp_path / "session",
        expected_source_sha256=netedit._file_sha256(source),
        platform_name="win32",
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=lambda _command, **_kwargs: _SessionProcess(),
        settle_seconds=0,
    )
    opened = session.open()

    with pytest.raises(ValueError, match="outside NetEdit client area"):
        session.act(
            {
                "type": "click",
                "x": 800,
                "y": 10,
                "expected_screenshot_sha256": opened["screenshot_sha256"],
            }
        )
    with pytest.raises(ValueError, match="exact latest screenshot"):
        session.act({"type": "key", "virtual_key": 118, "expected_screenshot_sha256": "0" * 64})
    with pytest.raises(ValueError, match="exact latest screenshot"):
        session.finalize(expected_screenshot_sha256="0" * 64)
    report = session.abort("bad hit target")

    assert report["status"] == "aborted"
    assert report["automatic_promotion_gate"] == "blocked"
    assert candidate.is_file()


def test_target_session_rechecks_live_viewport_before_real_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text("<net/>", encoding="utf-8")
    candidate = tmp_path / "candidate.net.xml"
    deliveries, _owned_pids = _patch_target_session_runtime(monkeypatch, candidate)
    session = NeteditTargetSession(
        source,
        candidate,
        tmp_path / "session",
        expected_source_sha256=netedit._file_sha256(source),
        platform_name="win32",
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=lambda _command, **_kwargs: _SessionProcess(),
        settle_seconds=0,
    )
    opened = session.open()

    def changed_capture(_hwnd: int, destination: Path) -> dict[str, object]:
        changed = Image.new("RGB", (800, 600), "black")
        changed.putpixel((120, 240), (255, 255, 255))
        changed.save(destination)
        return {
            "print_window_result": 1,
            "coordinate_space": "netedit_top_level_client",
            "width": 800,
            "height": 600,
            "sha256": netedit._file_sha256(destination),
        }

    monkeypatch.setattr(netedit, "_capture_target_window", changed_capture)
    with pytest.raises(ValueError, match="protected action target changed"):
        session.act(
            {
                "type": "click",
                "x": 120,
                "y": 240,
                "expected_screenshot_sha256": opened["screenshot_sha256"],
            }
        )
    report = session.abort("stale viewport")

    assert not any(item[0] in {"click", "drag", "key"} for item in deliveries)
    assert report["global_keyboard_or_mouse_input_used"] is False
    assert report["automatic_promotion_gate"] == "blocked"


def test_target_session_aborts_when_post_input_evidence_cannot_be_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text("<net/>", encoding="utf-8")
    candidate = tmp_path / "candidate.net.xml"
    deliveries, _owned_pids = _patch_target_session_runtime(monkeypatch, candidate)
    session = NeteditTargetSession(
        source,
        candidate,
        tmp_path / "session",
        expected_source_sha256=netedit._file_sha256(source),
        platform_name="win32",
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=lambda _command, **_kwargs: _SessionProcess(),
        settle_seconds=0,
    )
    opened = session.open()

    def fail_record(*_args, **_kwargs):
        raise RuntimeError("capture failed")

    monkeypatch.setattr(session, "_record_step", fail_record)
    with pytest.raises(RuntimeError, match="post-input evidence capture failed"):
        session.act(
            {
                "type": "click",
                "x": 120,
                "y": 240,
                "expected_screenshot_sha256": opened["screenshot_sha256"],
            }
        )

    assert any(item[0] == "click" for item in deliveries)
    assert any(item[0] == "close" for item in deliveries)
    assert session.state == "aborted"


def test_target_session_aborts_when_post_save_evidence_cannot_be_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text("<net/>", encoding="utf-8")
    candidate = tmp_path / "candidate.net.xml"
    deliveries, _owned_pids = _patch_target_session_runtime(monkeypatch, candidate)
    session = NeteditTargetSession(
        source,
        candidate,
        tmp_path / "session",
        expected_source_sha256=netedit._file_sha256(source),
        platform_name="win32",
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=lambda _command, **_kwargs: _SessionProcess(),
        settle_seconds=0,
    )
    opened = session.open()

    def fail_record(*_args, **_kwargs):
        raise RuntimeError("capture failed")

    monkeypatch.setattr(session, "_record_step", fail_record)
    with pytest.raises(RuntimeError, match="post-save validation or evidence capture failed"):
        session.finalize(expected_screenshot_sha256=opened["screenshot_sha256"])

    assert any(item[0] == "key" and item[3]["virtual_key"] == ord("S") for item in deliveries)
    assert any(item[0] == "close" for item in deliveries)
    assert session.state == "aborted"


def test_target_session_rejects_undeclared_source_junction_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text('<net><junction id="j1"/></net>', encoding="utf-8")
    candidate = tmp_path / "candidate.net.xml"
    _patch_target_session_runtime(monkeypatch, candidate)
    session = NeteditTargetSession(
        source,
        candidate,
        tmp_path / "session",
        expected_source_sha256=netedit._file_sha256(source),
        target_source_junction_ids=("missing",),
        platform_name="win32",
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=lambda _command, **_kwargs: _SessionProcess(),
        settle_seconds=0,
    )

    with pytest.raises(ValueError, match="absent from the source network"):
        session.open()
    assert not candidate.exists()


def test_target_session_requires_fresh_output_before_launch_or_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text("<net/>", encoding="utf-8")
    output = tmp_path / "session"
    output.mkdir()
    (output / "001-act.png").write_bytes(b"stale")
    candidate = output / "candidate.net.xml"
    _patch_target_session_runtime(monkeypatch, candidate)
    launched: list[bool] = []
    session = NeteditTargetSession(
        source,
        candidate,
        output,
        expected_source_sha256=netedit._file_sha256(source),
        platform_name="win32",
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=lambda _command, **_kwargs: launched.append(True) or _SessionProcess(),
        settle_seconds=0,
    )

    with pytest.raises(FileExistsError, match="fresh and empty"):
        session.open()
    assert launched == []
    assert not candidate.exists()


def test_f7_requires_frozen_exact_selection_and_first_edit_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text('<net><junction id="j1"/><junction id="j2"/></net>', encoding="utf-8")
    candidate = tmp_path / "candidate.net.xml"
    selection = tmp_path / "selection.txt"
    selection.write_text("junction:j2\njunction:j1\n", encoding="utf-8")
    _patch_target_session_runtime(monkeypatch, candidate)
    session = NeteditTargetSession(
        source,
        candidate,
        tmp_path / "session",
        expected_source_sha256=netedit._file_sha256(source),
        selection_file=selection,
        target_source_junction_ids=("j1", "j2"),
        target_candidate_junction_ids=("cluster",),
        platform_name="win32",
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=lambda _command, **_kwargs: _SessionProcess(),
        settle_seconds=0,
    )

    opened = session.open()
    selection.write_text("junction:unrelated\n", encoding="utf-8")
    recentered = session.act(
        {
            "type": "key",
            "virtual_key": 0x24,
            "expected_screenshot_sha256": opened["screenshot_sha256"],
        }
    )
    merged = session.act(
        {
            "type": "key",
            "virtual_key": 0x76,
            "expected_screenshot_sha256": recentered["screenshot_sha256"],
        }
    )

    assert merged["detail"]["selection_lock"]["status"] == "pass"
    assert merged["detail"]["selection_lock"]["selected_junction_ids"] == ["j1", "j2"]
    assert Path(merged["detail"]["selection_lock"]["selection_file"]) != selection
    with pytest.raises(ValueError, match="first edit action"):
        session.act(
            {
                "type": "key",
                "virtual_key": 0x76,
                "expected_screenshot_sha256": merged["screenshot_sha256"],
            }
        )
    session.abort("test complete")


def test_f7_rejects_selection_that_differs_from_declared_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text('<net><junction id="j1"/><junction id="j2"/></net>', encoding="utf-8")
    candidate = tmp_path / "candidate.net.xml"
    selection = tmp_path / "selection.txt"
    selection.write_text("junction:j1\n", encoding="utf-8")
    _patch_target_session_runtime(monkeypatch, candidate)
    session = NeteditTargetSession(
        source,
        candidate,
        tmp_path / "session",
        expected_source_sha256=netedit._file_sha256(source),
        selection_file=selection,
        target_source_junction_ids=("j1", "j2"),
        platform_name="win32",
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=lambda _command, **_kwargs: _SessionProcess(),
        settle_seconds=0,
    )
    opened = session.open()

    with pytest.raises(ValueError, match="must exactly equal"):
        session.act(
            {
                "type": "key",
                "virtual_key": 0x76,
                "expected_screenshot_sha256": opened["screenshot_sha256"],
            }
        )
    session.abort("test complete")


def test_f7_requires_exact_live_viewport_after_selection_was_observed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text('<net><junction id="j1"/></net>', encoding="utf-8")
    candidate = tmp_path / "candidate.net.xml"
    selection = tmp_path / "selection.txt"
    selection.write_text("junction:j1\n", encoding="utf-8")
    deliveries, _owned_pids = _patch_target_session_runtime(monkeypatch, candidate)
    session = NeteditTargetSession(
        source,
        candidate,
        tmp_path / "session",
        expected_source_sha256=netedit._file_sha256(source),
        selection_file=selection,
        target_source_junction_ids=("j1",),
        target_candidate_junction_ids=("cluster",),
        platform_name="win32",
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=lambda _command, **_kwargs: _SessionProcess(),
        settle_seconds=0,
    )
    opened = session.open()

    def changed_capture(_hwnd: int, destination: Path) -> dict[str, object]:
        changed = Image.new("RGB", (800, 600), "black")
        changed.putpixel((700, 500), (255, 255, 255))
        changed.save(destination)
        return {
            "print_window_result": 1,
            "coordinate_space": "netedit_top_level_client",
            "width": 800,
            "height": 600,
            "sha256": netedit._file_sha256(destination),
        }

    monkeypatch.setattr(netedit, "_capture_target_window", changed_capture)
    with pytest.raises(ValueError, match="viewport"):
        session.act(
            {
                "type": "key",
                "virtual_key": 0x76,
                "expected_screenshot_sha256": opened["screenshot_sha256"],
            }
        )
    assert not any(item[0] in {"click", "drag", "key"} for item in deliveries)
    session.abort("test complete")


def test_real_input_waits_for_target_and_requires_context_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGui:
        @staticmethod
        def GetForegroundWindow():
            return 42

        @staticmethod
        def IsChild(parent, child):
            return parent == 42 and child == 43

    sleeps = []
    monkeypatch.setattr(netedit, "_windows_modules", lambda: (None, FakeGui(), None, None))
    monkeypatch.setattr(
        netedit,
        "_ensure_english_window_layout",
        lambda _hwnd: {"status": "pass", "layout_name": "00000409", "changed_by_torii": False},
    )
    monkeypatch.setattr(
        netedit,
        "_assert_physical_input_idle",
        lambda _action: {"status": "idle", "checked_virtual_keys": []},
    )
    monkeypatch.setattr(
        netedit,
        "_activate_target_window",
        lambda _hwnd, _pid: {
            "previous_foreground_hwnd": 7,
            "previous_focus_hwnd": 7,
            "previous_cursor": [1, 2],
        },
    )
    monkeypatch.setattr(netedit, "_send_inputs", lambda inputs: len(inputs))
    monkeypatch.setattr(netedit, "_gui_focus", lambda _hwnd: 43)
    monkeypatch.setattr(netedit, "_restore_input_context", lambda _context: {"restored": True})
    monkeypatch.setattr(netedit.time, "sleep", sleeps.append)

    report = netedit._perform_real_input(
        42,
        9001,
        {"type": "key", "virtual_key": ord("I"), "modifier_keys": []},
        post_input_seconds=0.25,
    )

    assert report["target_foreground_after_input"] == 42
    assert report["target_focus_after_input"] == 43
    assert sleeps == [0.25]


def test_real_input_requires_and_records_english_keyboard_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGui:
        @staticmethod
        def GetForegroundWindow():
            return 42

        @staticmethod
        def IsChild(parent, child):
            return parent == 42 and child == 43

    layout = {"status": "pass", "layout_name": "00000409", "changed_by_torii": False}
    monkeypatch.setattr(netedit, "_windows_modules", lambda: (None, FakeGui(), None, None))
    monkeypatch.setattr(
        netedit,
        "_assert_physical_input_idle",
        lambda _action: {"status": "idle", "checked_virtual_keys": []},
    )
    monkeypatch.setattr(
        netedit,
        "_activate_target_window",
        lambda _hwnd, _pid: {"previous_foreground_hwnd": 7, "previous_focus_hwnd": 7, "previous_cursor": [1, 2]},
    )
    monkeypatch.setattr(netedit, "_ensure_english_window_layout", lambda _hwnd: layout)
    monkeypatch.setattr(netedit, "_send_inputs", lambda inputs: len(inputs))
    monkeypatch.setattr(netedit, "_gui_focus", lambda _hwnd: 43)
    monkeypatch.setattr(netedit, "_restore_input_context", lambda _context: {"restored": True})
    monkeypatch.setattr(netedit.time, "sleep", lambda _seconds: None)

    report = netedit._perform_real_input(
        42,
        9001,
        {"type": "key", "virtual_key": ord("I"), "modifier_keys": []},
    )

    assert report["keyboard_layout"] == layout


def test_real_input_retries_transient_context_restore_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGui:
        @staticmethod
        def GetForegroundWindow():
            return 42

        @staticmethod
        def IsChild(parent, child):
            return parent == 42 and child == 43

    restores = iter(({"restored": False}, {"restored": True}))
    sleeps = []
    monkeypatch.setattr(netedit, "_windows_modules", lambda: (None, FakeGui(), None, None))
    monkeypatch.setattr(
        netedit,
        "_assert_physical_input_idle",
        lambda _action: {"status": "idle", "checked_virtual_keys": []},
    )
    monkeypatch.setattr(
        netedit,
        "_activate_target_window",
        lambda _hwnd, _pid: {"previous_foreground_hwnd": 7, "previous_focus_hwnd": 7, "previous_cursor": [1, 2]},
    )
    monkeypatch.setattr(
        netedit,
        "_ensure_english_window_layout",
        lambda _hwnd: {"status": "pass", "layout_name": "00000409", "changed_by_torii": False},
    )
    monkeypatch.setattr(netedit, "_send_inputs", lambda inputs: len(inputs))
    monkeypatch.setattr(netedit, "_gui_focus", lambda _hwnd: 43)
    monkeypatch.setattr(netedit, "_restore_input_context", lambda _context: next(restores))
    monkeypatch.setattr(netedit.time, "sleep", sleeps.append)

    report = netedit._perform_real_input(
        42,
        9001,
        {"type": "key", "virtual_key": ord("I"), "modifier_keys": []},
    )

    assert report["restore"] == {"restored": True, "retry_count": 1}
    assert sleeps == [0.2, 0.1]


def test_ensure_english_window_layout_switches_non_english_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts = iter(
        [
            {"status": "blocked", "layout_name": "00000407", "primary_language_id": 0x07},
            {"status": "pass", "layout_name": "00000409", "primary_language_id": 0x09},
        ]
    )
    messages = []

    class Loader:
        argtypes = None
        restype = None

        def __call__(self, name, _flags):
            assert name == "00000409"
            return 0x409

    class User32:
        LoadKeyboardLayoutW = Loader()

    class FakeGui:
        @staticmethod
        def SendMessage(hwnd, message, _wparam, lparam):
            messages.append((hwnd, message, lparam))

    monkeypatch.setattr(netedit, "_keyboard_layout_context", lambda _hwnd: next(contexts))
    monkeypatch.setattr(netedit, "_windows_modules", lambda: (None, FakeGui(), None, None))

    class Windll:
        user32 = User32()

    monkeypatch.setattr(netedit.ctypes, "windll", Windll())

    result = netedit._ensure_english_window_layout(99)

    assert result["changed_by_torii"] is True
    assert result["layout_name"] == "00000409"
    assert messages == [(99, 0x0050, 0x409)]


def test_partial_input_is_released_and_context_is_restored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGui:
        @staticmethod
        def GetForegroundWindow():
            return 42

    released = []
    restored = []
    monkeypatch.setattr(netedit, "_windows_modules", lambda: (None, FakeGui(), None, None))
    monkeypatch.setattr(
        netedit,
        "_assert_physical_input_idle",
        lambda _action: {"status": "idle", "checked_virtual_keys": []},
    )
    monkeypatch.setattr(netedit, "_activate_target_window", lambda _hwnd, _pid: {"context": True})
    monkeypatch.setattr(
        netedit,
        "_ensure_english_window_layout",
        lambda _hwnd: {"status": "pass", "layout_name": "00000409", "changed_by_torii": False},
    )
    monkeypatch.setattr(
        netedit,
        "_send_inputs",
        lambda _inputs: (_ for _ in ()).throw(RuntimeError("partial SendInput")),
    )
    monkeypatch.setattr(netedit, "_release_partial_input", lambda action: released.append(action) or 1)
    monkeypatch.setattr(
        netedit,
        "_restore_input_context",
        lambda context: restored.append(context) or {"restored": True},
    )

    action = {"type": "key", "virtual_key": ord("I"), "modifier_keys": []}
    with pytest.raises(RuntimeError, match="partial SendInput"):
        netedit._perform_real_input(42, 9001, action)

    assert released == [action]
    assert restored == [{"context": True}]


@pytest.mark.parametrize("held_key", [0x11, 0x2E])
def test_physical_input_preflight_rejects_any_user_held_key(
    monkeypatch: pytest.MonkeyPatch,
    held_key: int,
) -> None:
    class AsyncKeyState:
        argtypes = None
        restype = None

        def __call__(self, virtual_key: int) -> int:
            return -32768 if virtual_key == held_key else 0

    class User32:
        GetAsyncKeyState = AsyncKeyState()

    class Windll:
        user32 = User32()

    monkeypatch.setattr(netedit.ctypes, "windll", Windll())

    with pytest.raises(RuntimeError, match=f"0x{held_key:02X}"):
        netedit._assert_physical_input_idle(
            {"type": "key", "virtual_key": ord("I"), "modifier_keys": []}
        )


def test_viewport_comparison_allows_small_global_drift_but_protects_click_target(
    tmp_path: Path,
) -> None:
    before = tmp_path / "before.png"
    harmless = tmp_path / "harmless.png"
    target_changed = tmp_path / "target-changed.png"
    baseline = Image.new("RGB", (200, 200), "black")
    baseline.save(before)
    harmless_image = baseline.copy()
    harmless_image.putpixel((190, 190), (255, 255, 255))
    harmless_image.save(harmless)
    target_image = baseline.copy()
    target_image.putpixel((50, 50), (255, 255, 255))
    target_image.save(target_changed)

    allowed = netedit._compare_viewport_images(
        before,
        harmless,
        protected_points=((50, 50),),
    )
    blocked = netedit._compare_viewport_images(
        before,
        target_changed,
        protected_points=((50, 50),),
    )

    assert allowed["status"] == "pass"
    assert blocked["status"] == "fail"
    assert blocked["protected_point_checks"] == [
        {"point": [50, 50], "box": [26, 26, 75, 75], "unchanged": False}
    ]

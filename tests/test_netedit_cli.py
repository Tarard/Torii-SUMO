from __future__ import annotations

from pathlib import Path

from torii_sumo.core.netedit import launch_netedit, main


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
    assert command == ["C:/SUMO/bin/netedit.exe", "--sumo-net-file", str(net_file)]
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

from pathlib import Path

from torii_sumo.core.sumo_commands import discover_binaries


def test_discover_binaries_prefers_one_sumo_home_toolchain(monkeypatch, tmp_path: Path) -> None:
    sumo_home = tmp_path / "sumo"
    bin_dir = sumo_home / "bin"
    tools_dir = sumo_home / "tools"
    bin_dir.mkdir(parents=True)
    tools_dir.mkdir()
    for name in ("sumo", "netconvert", "netgenerate", "duarouter"):
        (bin_dir / f"{name}.exe").write_text("", encoding="utf-8")
    (tools_dir / "randomTrips.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("SUMO_HOME", str(sumo_home))

    discovered = discover_binaries()

    assert Path(str(discovered["sumo"])).parent == bin_dir
    assert Path(str(discovered["netconvert"])).parent == bin_dir
    assert Path(str(discovered["netgenerate"])).parent == bin_dir
    assert Path(str(discovered["duarouter"])).parent == bin_dir
    assert Path(str(discovered["randomTrips"])).parent == tools_dir

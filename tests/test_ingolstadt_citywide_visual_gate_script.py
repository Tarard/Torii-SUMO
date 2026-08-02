from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from torii_sumo.core.candidate_contracts import file_sha256


SCRIPT = Path("plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py")


def _module():
    if not SCRIPT.is_file():
        pytest.fail(f"citywide runner is missing: {SCRIPT}")
    spec = importlib.util.spec_from_file_location("ingolstadt_citywide_visual_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_net(path: Path, *, offset: str, junction_x: float, junction_y: float) -> None:
    path.write_text(
        "<net>"
        f'<location netOffset="{offset}" convBoundary="0,0,500,500" '
        'origBoundary="11,48,12,49" projParameter="+proj=utm +zone=32"/>'
        '<edge id="in" from="n0" to="j0"><lane id="in_0" index="0" allow="passenger" shape="0,30 20,30"/></edge>'
        '<edge id="out" from="j0" to="n1"><lane id="out_0" index="0" allow="passenger" shape="20,30 40,30"/></edge>'
        '<edge id="walk_in" from="n2" to="walk"><lane id="walk_in_0" index="0" allow="pedestrian" shape="0,10 20,10"/></edge>'
        '<edge id="walk_out" from="walk" to="n3"><lane id="walk_out_0" index="0" allow="pedestrian" shape="20,10 40,10"/></edge>'
        '<connection from="in" to="out" fromLane="0" toLane="0"/>'
        '<connection from="walk_in" to="walk_out" fromLane="0" toLane="0"/>'
        f'<junction id="j0" type="priority" x="{junction_x}" y="{junction_y}" incLanes="in_0"/>'
        '<junction id="walk" type="priority" x="20" y="10" incLanes="walk_in_0"/>'
        "</net>",
        encoding="utf-8",
    )


def test_inventory_uses_projected_coordinates_and_motor_scope(tmp_path: Path) -> None:
    net = tmp_path / "city.net.xml"
    _write_net(net, offset="-1000,-2000", junction_x=20, junction_y=30)

    inventory = _module().read_network_inventory(net, tile_size_m=250.0)

    assert inventory["net_sha256"] == file_sha256(net)
    assert inventory["applicable_junction_count"] == 1
    junction = inventory["junctions"][0]
    assert junction["id"] == "j0"
    assert junction["projected_center"] == [1020.0, 2030.0]
    assert junction["tile_id"] == "0004_0008"
    assert junction["motor_incoming_lanes"] == ["in_0"]
    assert junction["motor_outgoing_lanes"] == ["out_0"]


def test_inventory_applies_the_teacher_projected_scope(tmp_path: Path) -> None:
    net = tmp_path / "city.net.xml"
    _write_net(net, offset="-1000,-2000", junction_x=20, junction_y=30)

    inventory = _module().read_network_inventory(
        net,
        tile_size_m=250.0,
        scope_projected_boundary=(1100.0, 2100.0, 1200.0, 2200.0),
    )

    assert inventory["applicable_junction_count"] == 0


def test_source_ledger_binds_official_scope_and_all_inputs(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    teacher = tmp_path / "teacher.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    source_osm = tmp_path / "source.osm.xml"
    _write_net(teacher, offset="-1000,-2000", junction_x=20, junction_y=30)
    _write_net(candidate, offset="-900,-1900", junction_x=120, junction_y=130)
    source_osm.write_text("<osm/>", encoding="utf-8")
    monkeypatch.setattr(module, "OFFICIAL_TEACHER_SHA256", file_sha256(teacher))
    monkeypatch.setattr(module, "OFFICIAL_CONV_BOUNDARY", (0.0, 0.0, 500.0, 500.0))

    report = module.write_source_ledger(
        tmp_path / "source-ledger.json",
        teacher_net=teacher,
        candidate_net=candidate,
        source_osm=source_osm,
        git_commit="abc123",
        sumo_version="Eclipse SUMO 1.27.1",
        netedit_version="Eclipse SUMO netedit 1.27.1",
        parameters={"tile_size_m": 250.0},
    )

    assert report["status"] == "pass"
    assert report["projected_scope"] == [1000.0, 2000.0, 1500.0, 2500.0]
    assert report["candidate_sha256"] == file_sha256(candidate)
    assert report["source_osm_sha256"] == file_sha256(source_osm)
    assert Path(report["report_file"]).is_file()

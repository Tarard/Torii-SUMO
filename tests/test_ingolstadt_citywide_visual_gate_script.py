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
    assert junction["road_roots"] == ["in", "out"]
    assert junction["approach_bearings"] == [0.0]
    assert junction["motor_incoming_lane_details"] == [
        {"id": "in_0", "edge_id": "in", "road_root": "in", "bearing": 0.0}
    ]


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


def _junction(
    junction_id: str,
    center: tuple[float, float],
    *,
    roads: tuple[str, ...],
    bearings: tuple[float, ...],
) -> dict[str, object]:
    return {
        "id": junction_id,
        "projected_center": list(center),
        "road_roots": list(roads),
        "approach_bearings": list(bearings),
    }


def test_registration_prefers_source_identity_then_direction() -> None:
    module = _module()
    teacher = _junction("cluster_10_11", (1000, 2000), roads=("10", "20"), bearings=(0, 180))
    exact = _junction("cluster_10_11", (1001, 2000), roads=("10", "20"), bearings=(1, 181))
    nearby = _junction("other", (1000, 2000), roads=("30",), bearings=(90,))

    report = module.register_junctions([teacher], [nearby, exact], max_distance_m=10)

    assert report["matched"][0]["candidate_ids"] == ["cluster_10_11"]
    assert report["ambiguous"] == []


def test_registration_maps_a_teacher_cluster_to_its_source_junctions() -> None:
    module = _module()
    teacher = _junction("cluster_10_11", (1000, 2000), roads=("10", "20"), bearings=(0, 180))
    candidates = [
        _junction("10", (999, 2000), roads=("10",), bearings=(0,)),
        _junction("11", (1001, 2000), roads=("20",), bearings=(180,)),
    ]

    report = module.register_junctions([teacher], candidates, max_distance_m=10)

    assert report["matched"][0]["candidate_ids"] == ["10", "11"]
    assert report["candidate_only"] == []


def test_registration_does_not_auto_accept_tied_candidates() -> None:
    module = _module()
    teacher = _junction("t", (1000, 2000), roads=("10",), bearings=(0,))
    candidates = [
        _junction("a", (999, 2000), roads=("10",), bearings=(0,)),
        _junction("b", (1001, 2000), roads=("10",), bearings=(0,)),
    ]

    report = module.register_junctions([teacher], candidates, max_distance_m=10)

    assert report["matched"] == []
    assert report["ambiguous"][0]["teacher_id"] == "t"


def test_lane_registration_is_one_to_one_by_road_and_bearing() -> None:
    module = _module()
    teacher = [
        {"id": "t0", "road_root": "10", "bearing": 0.0},
        {"id": "t1", "road_root": "10", "bearing": 180.0},
    ]
    candidate = [
        {"id": "c1", "road_root": "10", "bearing": 179.0},
        {"id": "c0", "road_root": "10", "bearing": 1.0},
    ]

    report = module.register_lanes(teacher, candidate, max_bearing_gap=15.0)

    assert report["matched"] == [
        {"teacher_lane": "t0", "candidate_lane": "c0", "bearing_gap": 1.0},
        {"teacher_lane": "t1", "candidate_lane": "c1", "bearing_gap": 1.0},
    ]
    assert report["teacher_only"] == []
    assert report["candidate_only"] == []

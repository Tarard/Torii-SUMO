from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw
import pytest

from torii_sumo.core.candidate_contracts import file_sha256
from torii_sumo.core.command_runner import CommandResult


SCRIPT = Path("plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py")


def test_cli_entrypoint_runs_after_all_helper_definitions() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.rfind('if __name__ == "__main__":') > source.rfind("def read_network_inventory(")


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
        {"id": "in_0", "junction_id": "j0", "edge_id": "in", "road_root": "in", "bearing": 0.0}
    ]
    assert junction["motor_outgoing_lane_details"] == [
        {"id": "out_0", "junction_id": "j0", "edge_id": "out", "road_root": "out", "bearing": 0.0}
    ]


def test_inventory_deduplicates_shared_outgoing_lanes(tmp_path: Path) -> None:
    net = tmp_path / "city.net.xml"
    _write_net(net, offset="-1000,-2000", junction_x=20, junction_y=30)
    xml = net.read_text(encoding="utf-8")
    xml = xml.replace(
        '<edge id="out"',
        '<edge id="in2" from="n4" to="j0"><lane id="in2_0" index="0" allow="passenger" shape="20,0 20,30"/></edge><edge id="out"',
    ).replace(
        '<connection from="in" to="out" fromLane="0" toLane="0"/>',
        '<connection from="in" to="out" fromLane="0" toLane="0"/><connection from="in2" to="out" fromLane="0" toLane="0"/>',
    ).replace('incLanes="in_0"', 'incLanes="in_0 in2_0"')
    net.write_text(xml, encoding="utf-8")

    junction = _module().read_network_inventory(net, tile_size_m=250.0)["junctions"][0]

    assert junction["motor_outgoing_lanes"] == ["out_0"]
    assert [row["id"] for row in junction["motor_outgoing_lane_details"]] == ["out_0"]


def test_inventory_applies_the_teacher_projected_scope(tmp_path: Path) -> None:
    net = tmp_path / "city.net.xml"
    _write_net(net, offset="-1000,-2000", junction_x=20, junction_y=30)

    inventory = _module().read_network_inventory(
        net,
        tile_size_m=250.0,
        scope_projected_boundary=(1100.0, 2100.0, 1200.0, 2200.0),
    )

    assert inventory["applicable_junction_count"] == 0


def test_render_subnet_uses_common_projected_boundary_and_binds_source(tmp_path: Path) -> None:
    module = _module()
    source = tmp_path / "source.net.xml"
    _write_net(source, offset="-1000,-2000", junction_x=20, junction_y=30)
    commands: list[list[str]] = []

    def fake_run(command, *, cwd, timeout_seconds):
        commands.append(list(command))
        destination = Path(command[command.index("--output-file") + 1])
        destination.write_bytes(source.read_bytes())
        return CommandResult(
            command=command,
            cwd=str(cwd),
            status="pass",
            returncode=0,
        )

    report = module.build_visual_tile_subnet(
        source_net=source,
        projected_boundary=(1000.0, 2000.0, 1250.0, 2250.0),
        output_dir=tmp_path / "subnet",
        requested_junctions=("j0",),
        requested_lanes=("in_0", "out_0"),
        command_runner=fake_run,
    )

    assert report["status"] == "pass"
    assert report["source_sha256"] == file_sha256(source)
    assert report["projected_boundary"] == [1000.0, 2000.0, 1250.0, 2250.0]
    assert commands[0][commands[0].index("--keep-edges.in-boundary") + 1] == (
        "0.000,0.000,250.000,250.000"
    )
    assert report["verified_junctions"] == ["j0"]
    assert set(report["verified_lanes"]) == {"in_0", "out_0"}


def test_render_subnet_fails_when_requested_geometry_is_missing(tmp_path: Path) -> None:
    module = _module()
    source = tmp_path / "source.net.xml"
    _write_net(source, offset="-1000,-2000", junction_x=20, junction_y=30)

    def fake_run(command, *, cwd, timeout_seconds):
        destination = Path(command[command.index("--output-file") + 1])
        destination.write_text(
            '<net><location netOffset="-1000,-2000" convBoundary="0,0,250,250"/>'
            '<edge id="in"><lane id="in_0" index="0" shape="0,30 20,30"/></edge></net>',
            encoding="utf-8",
        )
        return CommandResult(command=command, cwd=str(cwd), status="pass", returncode=0)

    report = module.build_visual_tile_subnet(
        source_net=source,
        projected_boundary=(1000.0, 2000.0, 1250.0, 2250.0),
        output_dir=tmp_path / "subnet",
        requested_junctions=("j0",),
        requested_lanes=("in_0", "out_0"),
        command_runner=fake_run,
    )

    assert report["status"] == "fail"
    assert report["missing_requested_junctions"] == ["j0"]
    assert report["missing_requested_lanes"] == ["out_0"]


def test_visual_tile_boundary_includes_registered_lane_geometry(tmp_path: Path) -> None:
    module = _module()
    teacher = tmp_path / "teacher.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    _write_net(teacher, offset="-1000,-2000", junction_x=20, junction_y=30)
    _write_net(candidate, offset="-1000,-2000", junction_x=20, junction_y=30)
    for path in (teacher, candidate):
        path.write_text(
            path.read_text(encoding="utf-8").replace('shape="20,30 40,30"', 'shape="20,30 100,30"'),
            encoding="utf-8",
        )
    records = [{
        "teacher_lane": "in_0",
        "candidate_lane": "in_0",
        "outgoing_lane_pairs": {"out_0": "out_0"},
    }]

    boundary = module.visual_tile_projected_boundary(
        teacher_net=teacher,
        candidate_net=candidate,
        records=records,
        tile_boundary=(1000.0, 2000.0, 1050.0, 2050.0),
    )

    assert boundary == (970.0, 1970.0, 1130.0, 2080.0)


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


def test_registration_keeps_unique_source_identity_after_coordinate_drift() -> None:
    module = _module()
    teacher = _junction("10", (1000, 2000), roads=("20",), bearings=(0,))
    moved = _junction("10", (1050, 2000), roads=("20",), bearings=(0,))

    report = module.register_junctions([teacher], [moved], max_distance_m=10)

    assert report["matched"][0]["candidate_ids"] == ["10"]
    assert report["teacher_only"] == []


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


def test_resume_requires_policy_hashes_and_unchanged_evidence_artifacts(tmp_path: Path) -> None:
    module = _module()
    state = tmp_path / "state.json"
    files = {}
    for name in ("teacher.png", "candidate.png", "teacher.mask.png", "candidate.mask.png"):
        path = tmp_path / name
        Image.new("RGB", (10, 10), "white").save(path)
        files[name] = path
    report = {
        "status": "pass",
        "teacher_screenshot_file": str(files["teacher.png"]),
        "teacher_screenshot_sha256": file_sha256(files["teacher.png"]),
        "candidate_screenshot_file": str(files["candidate.png"]),
        "candidate_screenshot_sha256": file_sha256(files["candidate.png"]),
        "teacher_mask": {
            "file": str(files["teacher.mask.png"]),
            "sha256": file_sha256(files["teacher.mask.png"]),
        },
        "candidate_mask": {
            "file": str(files["candidate.mask.png"]),
            "sha256": file_sha256(files["candidate.mask.png"]),
        },
    }
    module.write_tile_state(
        state,
        teacher_sha="a" * 64,
        candidate_sha="b" * 64,
        manifest_sha="c" * 64,
        lane_reports={"j0/in_0": report},
    )

    assert set(module.load_resumable_lane_reports(
        state,
        teacher_sha="a" * 64,
        candidate_sha="b" * 64,
        manifest_sha="c" * 64,
    )) == {"j0/in_0"}
    assert module.load_resumable_lane_reports(
        state,
        teacher_sha="a" * 64,
        candidate_sha="changed",
        manifest_sha="c" * 64,
    ) == {}
    stale = json.loads(state.read_text(encoding="utf-8"))
    stale["capture_policy_version"] = "old"
    state.write_text(json.dumps(stale), encoding="utf-8")
    assert module.load_resumable_lane_reports(
        state,
        teacher_sha="a" * 64,
        candidate_sha="b" * 64,
        manifest_sha="c" * 64,
    ) == {}
    module.write_tile_state(
        state,
        teacher_sha="a" * 64,
        candidate_sha="b" * 64,
        manifest_sha="c" * 64,
        lane_reports={"j0/in_0": report},
    )
    files["teacher.png"].write_bytes(b"changed")
    assert module.load_resumable_lane_reports(
        state,
        teacher_sha="a" * 64,
        candidate_sha="b" * 64,
        manifest_sha="c" * 64,
    ) == {}


def test_city_completion_fails_on_any_unmapped_or_nonpass_item() -> None:
    report = _module().city_completion(
        teacher_count=2,
        candidate_count=2,
        matched_count=1,
        teacher_only=["t1"],
        candidate_only=["c1"],
        ambiguous=[],
        lane_statuses=["pass", "fail"],
        structure_statuses=["pass"],
        global_load="pass",
        global_routeability="pass",
    )

    assert report["status"] == "fail"
    assert report["automatic_promotion_gate"] == "blocked"


def _connection_net(path: Path, *, target: str, tl: str, link_index: str) -> Path:
    signal = f' tl="{tl}" linkIndex="{link_index}"' if tl else ""
    path.write_text(
        "<net>"
        '<edge id="in"><lane id="in_0" index="0" allow="passenger"/></edge>'
        '<edge id="out"><lane id="out_0" index="0" allow="passenger"/></edge>'
        '<edge id="wrong"><lane id="wrong_0" index="0" allow="passenger"/></edge>'
        f'<connection from="in" to="{target}" fromLane="0" toLane="0" dir="s" via=":j_0_0"{signal}/>'
        "</net>",
        encoding="utf-8",
    )
    return path


def test_structure_pair_detects_missing_target_and_signal_binding(tmp_path: Path) -> None:
    module = _module()
    teacher = _connection_net(tmp_path / "teacher.net.xml", target="out", tl="tls", link_index="3")
    candidate = _connection_net(tmp_path / "candidate.net.xml", target="wrong", tl="", link_index="")

    report = module.compare_lane_structure(
        teacher,
        candidate,
        teacher_lane="in_0",
        candidate_lane="in_0",
        outgoing_lane_pairs={"out_0": "out_0"},
    )

    assert report["status"] == "fail"
    assert "target_lane_mismatch" in report["reasons"]
    assert "signal_binding_mismatch" in report["reasons"]


def test_city_manifest_binds_junction_and_lane_pairs() -> None:
    module = _module()
    teacher_junction = _junction("cluster_10_11", (1000, 2000), roads=("10",), bearings=(0,))
    candidate_junction = _junction("cluster_10_11", (1001, 2000), roads=("10",), bearings=(1,))
    teacher_junction.update({
        "tile_id": "0004_0008",
        "motor_incoming_lane_details": [{"id": "t_in", "junction_id": "cluster_10_11", "road_root": "10", "bearing": 0.0}],
        "motor_outgoing_lane_details": [{"id": "t_out", "junction_id": "cluster_10_11", "road_root": "20", "bearing": 90.0}],
    })
    candidate_junction.update({
        "tile_id": "0004_0008",
        "motor_incoming_lane_details": [{"id": "c_in", "junction_id": "cluster_10_11", "road_root": "10", "bearing": 1.0}],
        "motor_outgoing_lane_details": [{"id": "c_out", "junction_id": "cluster_10_11", "road_root": "20", "bearing": 91.0}],
    })
    teacher = {"applicable_junction_count": 1, "junctions": [teacher_junction]}
    candidate = {"applicable_junction_count": 1, "junctions": [candidate_junction]}

    manifest = module.build_city_manifest(teacher, candidate, max_distance_m=10.0)

    assert manifest["status"] == "ready"
    assert manifest["junction_pairs"][0]["incoming_lane_pairs"] == [["t_in", "c_in"]]
    assert manifest["junction_pairs"][0]["incoming_lane_records"] == [{
        "teacher_lane": "t_in",
        "teacher_junction": "cluster_10_11",
        "candidate_lane": "c_in",
        "candidate_junction": "cluster_10_11",
    }]
    assert manifest["junction_pairs"][0]["outgoing_lane_pairs"] == {"t_out": "c_out"}
    assert manifest["incoming_lane_count"] == 1
    assert manifest["teacher_only"] == []
    assert manifest["candidate_only"] == []


def test_city_manifest_excludes_lanes_inside_a_candidate_compound() -> None:
    module = _module()
    teacher = _junction("cluster_10_11", (1000, 2000), roads=("a", "b"), bearings=(0,))
    teacher.update({
        "tile_id": "0004_0008",
        "motor_incoming_lane_details": [{"id": "t_in", "junction_id": "cluster_10_11", "road_root": "a", "bearing": 0.0}],
        "motor_outgoing_lane_details": [{"id": "t_out", "junction_id": "cluster_10_11", "road_root": "b", "bearing": 90.0}],
    })
    first = _junction("10", (999, 2000), roads=("a", "bridge"), bearings=(0,))
    first.update({
        "motor_incoming_lane_details": [{"id": "c_in", "junction_id": "10", "road_root": "a", "bearing": 0.0}],
        "motor_outgoing_lane_details": [{"id": "bridge", "junction_id": "10", "road_root": "bridge", "bearing": 0.0}],
    })
    second = _junction("11", (1001, 2000), roads=("bridge", "b"), bearings=(0,))
    second.update({
        "motor_incoming_lane_details": [{"id": "bridge", "junction_id": "11", "road_root": "bridge", "bearing": 0.0}],
        "motor_outgoing_lane_details": [{"id": "c_out", "junction_id": "11", "road_root": "b", "bearing": 90.0}],
    })

    manifest = module.build_city_manifest(
        {"applicable_junction_count": 1, "junctions": [teacher]},
        {"applicable_junction_count": 2, "junctions": [first, second]},
        max_distance_m=10.0,
    )

    pair = manifest["junction_pairs"][0]
    assert pair["status"] == "ready"
    assert pair["incoming_lane_pairs"] == [["t_in", "c_in"]]
    assert pair["outgoing_lane_pairs"] == {"t_out": "c_out"}


def test_cli_exposes_resumable_city_phases() -> None:
    args = _module().build_parser().parse_args([
        "--teacher-net", "teacher.net.xml",
        "--candidate-net", "candidate.net.xml",
        "--source-osm", "source.osm.xml",
        "--output-dir", "out",
        "--phase", "inventory",
        "--resume",
    ])

    assert args.phase == "inventory"
    assert args.resume is True
    assert args.seed_junction == "cluster_2230504019_376231769"
    assert args.tile_size_m == 250.0


def test_inventory_phase_writes_hash_bound_city_manifest(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    teacher = tmp_path / "teacher.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    source_osm = tmp_path / "source.osm.xml"
    _write_net(teacher, offset="-1000,-2000", junction_x=20, junction_y=30)
    _write_net(candidate, offset="-1000,-2000", junction_x=20, junction_y=30)
    source_osm.write_text("<osm/>", encoding="utf-8")
    monkeypatch.setattr(module, "OFFICIAL_TEACHER_SHA256", file_sha256(teacher))
    monkeypatch.setattr(module, "OFFICIAL_CONV_BOUNDARY", (0.0, 0.0, 500.0, 500.0))

    report = module.run_inventory_phase(
        teacher_net=teacher,
        candidate_net=candidate,
        source_osm=source_osm,
        output_dir=tmp_path / "out",
        tile_size_m=250.0,
        junction_distance_m=10.0,
        git_commit="abc123",
        sumo_version="SUMO 1.27.1",
        netedit_version="NetEdit 1.27.1",
    )

    assert report["status"] == "ready"
    assert report["teacher_sha256"] == file_sha256(teacher)
    assert report["candidate_sha256"] == file_sha256(candidate)
    assert Path(report["manifest_file"]).is_file()
    assert Path(report["source_ledger_file"]).is_file()


def test_main_runs_inventory_without_claiming_city_completion(tmp_path: Path, capsys) -> None:
    module = _module()
    calls = []

    def fake_inventory(**kwargs):
        calls.append(kwargs)
        return {
            "status": "ready",
            "manifest_file": "city-manifest.json",
            "junction_pairs": [{"teacher_id": "large-payload"}],
            "registration_gaps": [{"id": "large-gap-payload"}],
        }

    code = module.main(
        [
            "--teacher-net", str(tmp_path / "teacher.net.xml"),
            "--candidate-net", str(tmp_path / "candidate.net.xml"),
            "--source-osm", str(tmp_path / "source.osm.xml"),
            "--output-dir", str(tmp_path / "out"),
            "--phase", "inventory",
        ],
        inventory_func=fake_inventory,
        provenance_func=lambda: ("abc123", "SUMO 1.27.1", "NetEdit 1.27.1"),
    )

    assert code == 2
    assert calls[0]["tile_size_m"] == 250.0
    output = capsys.readouterr().out
    assert '"status": "ready"' in output
    assert '"manifest_file": "city-manifest.json"' in output
    assert '"junction_pairs":' not in output
    assert '"junction_pairs_count": 1' in output
    assert '"registration_gaps":' not in output
    assert '"registration_gaps_count": 1' in output


def test_lane_evidence_keeps_masks_and_accepts_renumbered_signal_order(tmp_path: Path) -> None:
    module = _module()
    teacher_net = _connection_net(tmp_path / "teacher.net.xml", target="out", tl="tls", link_index="3")
    candidate_net = _connection_net(tmp_path / "candidate.net.xml", target="out", tl="tls", link_index="7")
    teacher_image, candidate_image = tmp_path / "teacher.png", tmp_path / "candidate.png"
    for path in (teacher_image, candidate_image):
        image = Image.new("RGB", (240, 180), "white")
        draw = ImageDraw.Draw(image)
        draw.line((120, 110, 120, 165), fill=(0, 255, 255), width=4)
        draw.line((130, 90, 210, 90), fill=(0, 255, 0), width=4)
        image.save(path)

    report = module.evaluate_lane_pair(
        teacher_net=teacher_net,
        candidate_net=candidate_net,
        record={
            "teacher_lane": "in_0",
            "candidate_lane": "in_0",
            "outgoing_lane_pairs": {"out_0": "out_0"},
        },
        teacher_capture={"screenshot_file": str(teacher_image), "junction_pixel": [120, 90]},
        candidate_capture={"screenshot_file": str(candidate_image), "junction_pixel": [120, 90]},
        lane_dir=tmp_path / "lane",
        failure_dir=tmp_path / "failures",
    )

    assert report["status"] == "pass"
    assert report["structure"]["status"] == "pass"
    assert Path(report["teacher_mask"]["file"]).is_file()
    assert Path(report["candidate_mask"]["file"]).is_file()
    assert not (tmp_path / "failures").exists()


def test_lane_evidence_binds_canvas_radius_and_native_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    teacher_net = _connection_net(tmp_path / "teacher.net.xml", target="out", tl="tls", link_index="3")
    candidate_net = _connection_net(tmp_path / "candidate.net.xml", target="out", tl="tls", link_index="7")
    teacher_image, candidate_image = tmp_path / "teacher.png", tmp_path / "candidate.png"
    for path in (teacher_image, candidate_image):
        Image.new("RGB", (240, 180), "white").save(path)
    arguments = {}

    def fake_analyze(*_args, **kwargs):
        arguments.update(kwargs)
        return {"status": "pass", "reasons": [], "layers": {}}

    monkeypatch.setattr(module, "analyze_connection_pair", fake_analyze)
    report = module.evaluate_lane_pair(
        teacher_net=teacher_net,
        candidate_net=candidate_net,
        record={
            "teacher_lane": "in_0",
            "candidate_lane": "in_0",
            "outgoing_lane_pairs": {"out_0": "out_0"},
        },
        teacher_capture={
            "screenshot_file": str(teacher_image),
            "junction_pixel": [120, 90],
            "canvas_rect": [20, 10, 220, 170],
            "semantic_radius": 280,
            "selection": {"status": "review_required", "reasons": ["registered_source_lane_not_selected"]},
        },
        candidate_capture={
            "screenshot_file": str(candidate_image),
            "junction_pixel": [120, 90],
            "canvas_rect": [20, 10, 220, 170],
            "semantic_radius": 300,
            "selection": {"status": "pass", "reasons": []},
        },
        lane_dir=tmp_path / "lane",
        failure_dir=tmp_path / "failures",
    )

    assert report["status"] == "review_required"
    assert arguments["teacher_canvas_rect"] == (20, 10, 220, 170)
    assert arguments["candidate_canvas_rect"] == (20, 10, 220, 170)
    assert arguments["semantic_radius"] == 300


def test_tiles_expand_from_the_verified_seed() -> None:
    manifest = {
        "junction_pairs": [
            {"teacher_id": "far", "tile_id": "0007_0008"},
            {"teacher_id": "seed", "tile_id": "0004_0008"},
            {"teacher_id": "near", "tile_id": "0005_0008"},
        ]
    }

    assert _module().ordered_tiles(manifest, seed_junction="seed") == [
        "0004_0008", "0005_0008", "0007_0008"
    ]


def test_tiles_stop_at_requested_manhattan_distance() -> None:
    manifest = {
        "junction_pairs": [
            {"teacher_id": "seed", "tile_id": "0004_0008"},
            {"teacher_id": "north", "tile_id": "0004_0009"},
            {"teacher_id": "east", "tile_id": "0005_0008"},
            {"teacher_id": "far", "tile_id": "0006_0008"},
        ]
    }

    assert _module().ordered_tiles(
        manifest,
        seed_junction="seed",
        max_tile_distance=1,
    ) == ["0004_0008", "0004_0009", "0005_0008"]


def test_visual_phase_persists_each_lane_and_resumes(tmp_path: Path) -> None:
    module = _module()
    teacher = _connection_net(tmp_path / "teacher.net.xml", target="out", tl="tls", link_index="3")
    candidate = _connection_net(tmp_path / "candidate.net.xml", target="out", tl="tls", link_index="7")
    manifest_file = tmp_path / "city-manifest.json"
    manifest_file.write_text(json.dumps({
        "schema": "torii.ingolstadt-citywide-manifest/v1",
        "status": "ready",
        "teacher_net_file": str(teacher.resolve()),
        "teacher_sha256": file_sha256(teacher),
        "candidate_net_file": str(candidate.resolve()),
        "candidate_sha256": file_sha256(candidate),
        "tile_size_m": 250.0,
        "junction_pairs": [{
            "teacher_id": "seed",
            "candidate_ids": ["seed"],
            "tile_id": "0004_0008",
            "incoming_lane_records": [{
                "teacher_lane": "in_0",
                "teacher_junction": "seed",
                "candidate_lane": "in_0",
                "candidate_junction": "seed",
            }],
            "outgoing_lane_pairs": {"out_0": "out_0"},
        }],
    }), encoding="utf-8")
    capture_calls = []

    def fake_capture(**kwargs):
        capture_calls.append(kwargs)
        captures = []
        session_dir = Path(kwargs["output_dir"])
        session_dir.mkdir(parents=True, exist_ok=True)
        for role in ("teacher", "candidate"):
            image_file = session_dir / f"{role}.png"
            image = Image.new("RGB", (240, 180), "white")
            draw = ImageDraw.Draw(image)
            draw.line((120, 110, 120, 165), fill=(0, 255, 255), width=4)
            draw.line((130, 90, 210, 90), fill=(0, 255, 0), width=4)
            image.save(image_file)
            captures.append([{
                "lane_id": "in_0",
                "screenshot_file": str(image_file),
                "junction_pixel": [120, 90],
            }])
        return tuple(captures)

    first = module.run_visual_phase(
        manifest_file=manifest_file,
        output_dir=tmp_path / "out",
        seed_junction="seed",
        zoom=2500.0,
        window_size=(1400, 1000),
        resume=True,
        capture_tile_func=fake_capture,
    )
    second = module.run_visual_phase(
        manifest_file=manifest_file,
        output_dir=tmp_path / "out",
        seed_junction="seed",
        zoom=2500.0,
        window_size=(1400, 1000),
        resume=True,
        capture_tile_func=fake_capture,
    )

    assert first["status"] == "pass"
    assert second["status"] == "pass"
    assert len(capture_calls) == 1
    assert first["pass_lane_count"] == 1
    assert Path(first["summary_file"]).is_file()
    assert (tmp_path / "out" / "tiles" / "0004_0008" / "state.json").is_file()
    assert not (tmp_path / "out" / "tiles" / "0004_0008" / ".session").exists()
    state = json.loads((tmp_path / "out" / "tiles" / "0004_0008" / "state.json").read_text(encoding="utf-8"))
    assert state["schema"] == "torii.ingolstadt-citywide-tile/v2"
    evidence = next(iter(first["lane_reports"].values()))
    assert Path(evidence["teacher_screenshot_file"]).is_file()
    assert Path(evidence["candidate_screenshot_file"]).is_file()

    def failed_capture(**kwargs):
        session_dir = Path(kwargs["output_dir"])
        session_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for role in ("teacher", "candidate"):
            image_file = session_dir / f"{role}.png"
            Image.new("RGB", (240, 180), "white").save(image_file)
            rows.append([{
                "lane_id": "in_0",
                "screenshot_file": str(image_file),
                "junction_pixel": [120, 90],
            }])
        return tuple(rows)

    failed = module.run_visual_phase(
        manifest_file=manifest_file,
        output_dir=tmp_path / "failed-out",
        seed_junction="seed",
        zoom=2500.0,
        window_size=(1400, 1000),
        resume=False,
        capture_tile_func=failed_capture,
    )
    assert failed["status"] == "fail"
    assert (tmp_path / "failed-out" / "tiles" / "0004_0008" / ".session").is_dir()

    expanded_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    expanded_manifest["status"] = "blocked"
    expanded_manifest["registration_gaps"] = [
        {"kind": "teacher_only", "id": "far", "tile_id": "0006_0008"}
    ]
    manifest_file.write_text(json.dumps(expanded_manifest), encoding="utf-8")
    partial = module.run_visual_phase(
        manifest_file=manifest_file,
        output_dir=tmp_path / "partial-out",
        seed_junction="seed",
        zoom=2500.0,
        window_size=(1400, 1000),
        resume=False,
        max_tile_distance=0,
        capture_tile_func=fake_capture,
    )
    assert partial["status"] == "pass"
    assert partial["coverage_status"] == "partial"
    assert partial["covered_tile_count"] == 1
    assert partial["total_tile_count"] == 2
    assert partial["automatic_promotion_gate"] == "blocked"


def test_target_window_capture_uses_one_process_per_role_and_tile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    teacher = tmp_path / "teacher.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    _write_net(teacher, offset="-1000,-2000", junction_x=20, junction_y=30)
    _write_net(candidate, offset="-1000,-2000", junction_x=20, junction_y=30)
    session_sources: list[Path] = []
    session_actions: list[str] = []
    lane_point_calls: list[tuple[tuple[float, float], ...]] = []
    parsed_roots = []
    original_lane_capture_spec = module.lane_capture_spec

    def tracked_lane_capture_spec(net_file, *, junction_id, lane_id, root=None):
        parsed_roots.append(root)
        return original_lane_capture_spec(
            net_file,
            junction_id=junction_id,
            lane_id=lane_id,
        )

    def fake_subnet(*, source_net, output_dir, **_kwargs):
        subnet = Path(output_dir) / "render.net.xml"
        subnet.parent.mkdir(parents=True, exist_ok=True)
        subnet.write_bytes(Path(source_net).read_bytes())
        return {
            "status": "pass",
            "subnet_file": str(subnet),
            "subnet_sha256": "d" * 64,
            "projected_boundary": [970.0, 1970.0, 1280.0, 2280.0],
        }

    class FakeSession:
        hwnd = 17

        def __init__(self, source, _candidate, output_dir, **kwargs):
            self.source = Path(source)
            self.output_dir = Path(output_dir)
            assert "test_file" not in kwargs
            session_sources.append(self.source)

        def open(self):
            self.output_dir.mkdir(parents=True, exist_ok=True)
            image_file = self.output_dir / "001-open.png"
            Image.new("RGB", (1400, 1000), "white").save(image_file)
            return {
                "screenshot_file": str(image_file),
                "screenshot_sha256": file_sha256(image_file),
            }

        def observe(self, _label):
            return self.open()

        def act(self, action):
            session_actions.append(action["type"])
            return self.open()

        def abort(self, _reason):
            return {"status": "aborted"}

    def fake_lane_points(points):
        lane_point_calls.append(tuple(points))
        return ((12.0, 30.0), (16.0, 30.0), (18.0, 30.0))

    monkeypatch.setattr(module, "build_visual_tile_subnet", fake_subnet)
    monkeypatch.setattr(module, "lane_capture_spec", tracked_lane_capture_spec)
    monkeypatch.setattr(module, "netedit_canvas_rect", lambda _hwnd: (230, 64, 1394, 885))
    monkeypatch.setattr(module, "fit_connection_zoom", lambda **_kwargs: 900.0)
    monkeypatch.setattr(module, "normalized_viewport_zoom", lambda **_kwargs: 900.0)
    monkeypatch.setattr(module, "lane_click_points", fake_lane_points)
    monkeypatch.setattr(
        module,
        "canvas_click_for_world_point",
        lambda *, point, **_kwargs: (700, 470) if point == (20.0, 30.0) else (420, 330),
    )
    monkeypatch.setattr(
        module,
        "verify_expected_lane_semantics",
        lambda *_args, **_kwargs: {"status": "pass", "reasons": []},
    )

    result = module.capture_tile_pair(
        tile_id="0004_0008",
        records=[{
            "teacher_lane": "in_0",
            "teacher_junction": "j0",
                "candidate_lane": "in_0",
                "candidate_junction": "j0",
                "outgoing_lane_pairs": {"out_0": "out_0"},
            }] * 2,
        teacher_net=teacher,
        candidate_net=candidate,
        output_dir=tmp_path / "session",
        zoom=2500.0,
        window_size=(1400, 1000),
        tile_size_m=250.0,
        session_factory=FakeSession,
    )

    assert len(session_sources) == 4
    assert session_actions == ["key", "click", "key", "key", "click"] * 2
    assert all(path not in {teacher.resolve(), candidate.resolve()} for path in session_sources)
    assert all(root is not None for root in parsed_roots)
    assert len(lane_point_calls) == 6
    for captures in result:
        assert len(captures) == 2
        image_file = Path(captures[0]["screenshot_file"])
        assert captures[0] == {
            "lane_id": "in_0",
            "sample_distance_rank": 1,
            "click": [420, 330],
            "junction_pixel": [700, 470],
            "canvas_rect": [230, 64, 1394, 885],
            "zoom": 900.0,
            "semantic_radius": 300,
            "selection": {"status": "pass", "reasons": []},
            "subnet_sha256": "d" * 64,
            "screenshot_file": str(image_file),
            "screenshot_sha256": file_sha256(image_file),
        }


def test_main_runs_visual_phase_without_claiming_global_completion(tmp_path: Path) -> None:
    module = _module()
    calls = []
    output = tmp_path / "out"
    output.mkdir()
    (output / "city-manifest.json").write_text("{}", encoding="utf-8")

    def fake_visual(**kwargs):
        calls.append(kwargs)
        return {"status": "pass", "summary_file": "visual-summary.json"}

    code = module.main(
        [
            "--teacher-net", str(tmp_path / "teacher.net.xml"),
            "--candidate-net", str(tmp_path / "candidate.net.xml"),
            "--source-osm", str(tmp_path / "source.osm.xml"),
            "--output-dir", str(output),
            "--phase", "visual",
            "--resume",
        ],
        visual_func=fake_visual,
    )

    assert code == 2
    assert calls[0]["resume"] is True
    assert calls[0]["manifest_file"] == output / "city-manifest.json"


def _four_tile_inventory() -> dict[str, object]:
    junctions = []
    for x, y in ((0, 0), (0, 1), (1, 0), (1, 1)):
        tile = f"{x:04d}_{y:04d}"
        junctions.append({
            "tile_id": tile,
            "projected_center": [x * 250.0 + 125.0, y * 250.0 + 125.0],
            "motor_incoming_edges": [f"in_{x}_{y}"],
            "motor_outgoing_edges": [f"out_{x}_{y}"],
        })
    return {"junctions": junctions}


def test_od_plan_covers_tiles_neighbors_and_city_extremes() -> None:
    plan = _module().build_stratified_od_plan(_four_tile_inventory(), seed=20260802)

    kinds = {row["kind"] for row in plan}
    assert {"within_tile", "adjacent_tiles", "edge_to_center"} <= kinds
    assert {row["origin_tile"] for row in plan if row["kind"] == "within_tile"} == {
        "0000_0000", "0000_0001", "0001_0000", "0001_0001"
    }


def test_global_result_rejects_missing_route_teleport_or_collision() -> None:
    report = _module().summarize_global_run(
        requested=20,
        routed=19,
        arrived=19,
        teleports=1,
        collisions=0,
        returncode=0,
    )

    assert report["status"] == "fail"


def test_global_phase_runs_load_duarouter_and_completion_checks(tmp_path: Path) -> None:
    module = _module()
    candidate = tmp_path / "candidate.net.xml"
    _write_net(candidate, offset="-1000,-2000", junction_x=20, junction_y=30)
    manifest = tmp_path / "city-manifest.json"
    manifest.write_text(json.dumps({
        "schema": "torii.ingolstadt-citywide-manifest/v1",
        "status": "ready",
        "candidate_net_file": str(candidate.resolve()),
        "candidate_sha256": file_sha256(candidate),
        "projected_scope": [1000.0, 2000.0, 1500.0, 2500.0],
        "tile_size_m": 250.0,
    }), encoding="utf-8")
    calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        calls.append(command)
        if command[0] == "duarouter":
            trips = ET.parse(command[command.index("--route-files") + 1]).getroot().findall("trip")
            route_file = Path(command[command.index("--output-file") + 1])
            route_file.write_text(
                "<routes>" + "".join(f'<vehicle id="v{i}"/>' for i in range(len(trips))) + "</routes>",
                encoding="utf-8",
            )
        elif command[0] == "sumo" and "--route-files" in command:
            route_count = len(ET.parse(command[command.index("--route-files") + 1]).getroot().findall("vehicle"))
            summary = Path(command[command.index("--summary-output") + 1])
            tripinfo = Path(command[command.index("--tripinfo-output") + 1])
            summary.write_text(
                f'<summary><step time="100" loaded="{route_count}" inserted="{route_count}" '
                f'arrived="{route_count}" ended="{route_count}" running="0" waiting="0" '
                'teleports="0" collisions="0"/></summary>',
                encoding="utf-8",
            )
            tripinfo.write_text(
                "<tripinfos>" + "".join(f'<tripinfo id="v{i}" duration="1"/>' for i in range(route_count)) + "</tripinfos>",
                encoding="utf-8",
            )
        return CommandResult(command=command, cwd=str(cwd) if cwd else None, status="pass", returncode=0)

    report = module.run_global_phase(
        manifest_file=manifest,
        output_dir=tmp_path / "out",
        binaries={"sumo": "sumo", "duarouter": "duarouter"},
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["candidate_sha256"] == file_sha256(candidate)
    assert [command[0] for command in calls] == ["sumo", "duarouter", "sumo"]
    assert Path(report["global_load_file"]).is_file()
    assert Path(report["global_routeability_file"]).is_file()


def test_completion_requires_visual_structure_and_global_pass() -> None:
    candidate_sha = "a" * 64
    report = _module().build_completion_report(
        manifest={
            "teacher_applicable_junction_count": 1,
            "candidate_applicable_junction_count": 1,
            "matched_junction_count": 1,
            "teacher_only": [],
            "candidate_only": [],
            "ambiguous": [],
            "teacher_sha256": "b" * 64,
            "candidate_sha256": candidate_sha,
            "source_osm_sha256": "c" * 64,
        },
        visual={
            "candidate_sha256": candidate_sha,
            "lane_reports": {"tile/lane": {"status": "pass", "structure": {"status": "pass"}}},
        },
        global_report={
            "status": "pass",
            "candidate_sha256": candidate_sha,
            "global_load_status": "pass",
        },
    )

    assert report["status"] == "pass"
    assert report["candidate_sha256"] == candidate_sha
    assert report["automatic_promotion_gate"] == "pass"


def test_main_global_phase_writes_strict_completion(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "out"
    output.mkdir()
    candidate_sha = "a" * 64
    (output / "city-manifest.json").write_text(json.dumps({
        "teacher_applicable_junction_count": 1,
        "candidate_applicable_junction_count": 1,
        "matched_junction_count": 1,
        "incoming_lane_count": 1,
        "teacher_only": [],
        "candidate_only": [],
        "ambiguous": [],
        "teacher_sha256": "b" * 64,
        "candidate_sha256": candidate_sha,
        "source_osm_sha256": "c" * 64,
    }), encoding="utf-8")
    (output / "visual-summary.json").write_text(json.dumps({
        "candidate_sha256": candidate_sha,
        "coverage_status": "complete",
        "lane_reports": {"tile/lane": {"status": "pass", "structure": {"status": "pass"}}},
    }), encoding="utf-8")

    code = module.main(
        [
            "--teacher-net", str(tmp_path / "teacher.net.xml"),
            "--candidate-net", str(tmp_path / "candidate.net.xml"),
            "--source-osm", str(tmp_path / "source.osm.xml"),
            "--output-dir", str(output),
            "--phase", "global",
        ],
        global_func=lambda **_kwargs: {
            "status": "pass", "candidate_sha256": candidate_sha, "global_load_status": "pass"
        },
    )

    assert code == 0
    completion = json.loads((output / "completion.json").read_text(encoding="utf-8"))
    assert completion["status"] == "pass"


def test_main_all_runs_inventory_visual_and_global_in_order(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "out"
    candidate_sha = "a" * 64
    calls = []

    def inventory(**_kwargs):
        calls.append("inventory")
        return {
            "status": "ready",
            "teacher_applicable_junction_count": 1,
            "candidate_applicable_junction_count": 1,
            "matched_junction_count": 1,
            "incoming_lane_count": 1,
            "teacher_only": [], "candidate_only": [], "ambiguous": [],
            "teacher_sha256": "b" * 64,
            "candidate_sha256": candidate_sha,
            "source_osm_sha256": "c" * 64,
        }

    def visual(**_kwargs):
        calls.append("visual")
        return {
            "status": "pass", "candidate_sha256": candidate_sha,
            "coverage_status": "complete",
            "lane_reports": {"tile/lane": {"status": "pass", "structure": {"status": "pass"}}},
        }

    def global_gate(**_kwargs):
        calls.append("global")
        return {"status": "pass", "candidate_sha256": candidate_sha, "global_load_status": "pass"}

    code = module.main(
        [
            "--teacher-net", str(tmp_path / "teacher.net.xml"),
            "--candidate-net", str(tmp_path / "candidate.net.xml"),
            "--source-osm", str(tmp_path / "source.osm.xml"),
            "--output-dir", str(output),
            "--phase", "all",
            "--resume",
        ],
        inventory_func=inventory,
        visual_func=visual,
        global_func=global_gate,
        provenance_func=lambda: ("commit", "sumo", "netedit"),
    )

    assert code == 0
    assert calls == ["inventory", "visual", "global"]
    assert json.loads((output / "completion.json").read_text(encoding="utf-8"))["status"] == "pass"

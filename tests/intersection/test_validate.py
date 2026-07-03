from pathlib import Path

from torii_sumo.intersection.infer_control import infer_control_model
from torii_sumo.intersection.clean import build_intersection_ir
from torii_sumo.intersection.schema import CompiledSUMOArtifacts, Movement, OSMNode, OSMWay, PatchSeed
from torii_sumo.intersection.validate import validate_intersection


FIXTURES = Path(__file__).parent / "fixtures"


def test_validate_intersection_passes_absolute_net_path_to_sumo(monkeypatch, tmp_path: Path) -> None:
    ir = build_intersection_ir(FIXTURES / "t3_priority.osm.xml", tmp_path)
    monkeypatch.chdir(tmp_path)
    output_dir = Path("artifacts") / "intersection"
    output_dir.mkdir(parents=True)
    net_file = output_dir / "intersection.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")
    seen = {}

    monkeypatch.setattr("torii_sumo.intersection.validate.shutil.which", lambda _name: "sumo")

    def fake_run(command, **kwargs):
        seen["net_arg"] = command[2]
        seen["cwd"] = kwargs["cwd"]

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr("torii_sumo.intersection.validate.subprocess.run", fake_run)

    result = validate_intersection(
        ir,
        CompiledSUMOArtifacts(
            plain_node_file="",
            plain_edge_file="",
            plain_connection_file="",
            net_file=str(net_file),
        ),
        output_dir,
    )

    assert Path(seen["net_arg"]).is_absolute()
    assert seen["cwd"] == output_dir
    assert result.sumo_load_status == "pass"


def test_validate_intersection_blocks_unknown_fragment(monkeypatch, tmp_path: Path) -> None:
    osm_file = tmp_path / "two_leg.osm.xml"
    osm_file.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
  <bounds minlat="48.0000" minlon="11.0000" maxlat="48.0010" maxlon="11.0010"/>
  <node id="1" lat="48.0005" lon="11.0005"/>
  <node id="2" lat="48.0010" lon="11.0005"/>
  <node id="3" lat="48.0000" lon="11.0005"/>
  <way id="10">
    <nd ref="2"/>
    <nd ref="1"/>
    <nd ref="3"/>
    <tag k="highway" v="primary"/>
  </way>
</osm>
""",
        encoding="utf-8",
    )
    ir = build_intersection_ir(osm_file, tmp_path)
    net_file = tmp_path / "fragment.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    monkeypatch.setattr("torii_sumo.intersection.validate.shutil.which", lambda _name: "sumo")

    def fake_run(_command, **_kwargs):
        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr("torii_sumo.intersection.validate.subprocess.run", fake_run)

    result = validate_intersection(
        ir,
        CompiledSUMOArtifacts(
            plain_node_file="",
            plain_edge_file="",
            plain_connection_file="",
            net_file=str(net_file),
        ),
        tmp_path,
    )

    assert ir.core.topology_type == "unknown"
    assert result.sumo_load_status == "pass"
    assert result.status == "blocked"
    assert "unsupported intersection topology: unknown with 1 approaches" in result.warnings


def test_validate_intersection_reports_netconvert_warnings(monkeypatch, tmp_path: Path) -> None:
    ir = build_intersection_ir(FIXTURES / "t3_priority.osm.xml", tmp_path)
    net_file = tmp_path / "netconvert_warning.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    monkeypatch.setattr("torii_sumo.intersection.validate.shutil.which", lambda _name: "sumo")

    def fake_run(_command, **_kwargs):
        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr("torii_sumo.intersection.validate.subprocess.run", fake_run)

    result = validate_intersection(
        ir,
        CompiledSUMOArtifacts(
            plain_node_file="",
            plain_edge_file="",
            plain_connection_file="",
            net_file=str(net_file),
            netconvert_warnings=["Warning: lane is not connected."],
        ),
        tmp_path,
    )

    assert "netconvert: Warning: lane is not connected." in result.warnings
    assert result.status == "blocked"


def test_validate_intersection_tls_linkindex_uses_core_connection_movements(monkeypatch, tmp_path: Path) -> None:
    ir = build_intersection_ir(FIXTURES / "x4_signalized.osm.xml", tmp_path)
    support = Movement(
        movement_id="support_path_to_support_path",
        from_approach_id="path_a",
        to_approach_id="path_b",
        road_pair_relation_id="support_pair",
        turn="straight",
        allowed=True,
        from_lane_indices=[0],
        to_lane_indices=[0],
        allowed_modes={"bicycle"},
        evidence=["fixture:support_path"],
        confidence=1.0,
    )
    movement_matrix = ir.movement_matrix.model_copy(
        update={
            "movements": [*ir.movement_matrix.movements, support],
            "legal_movement_count": ir.movement_matrix.legal_movement_count + 1,
            "inferred_movement_count": ir.movement_matrix.inferred_movement_count + 1,
        }
    )
    ir = ir.model_copy(
        update={
            "movement_matrix": movement_matrix,
            "control": infer_control_model(ir.osm_patch, ir.core, ir.approaches, movement_matrix),
        }
    )
    net_file = tmp_path / "x4.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    monkeypatch.setattr("torii_sumo.intersection.validate.shutil.which", lambda _name: "sumo")

    def fake_run(_command, **_kwargs):
        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr("torii_sumo.intersection.validate.subprocess.run", fake_run)

    result = validate_intersection(
        ir,
        CompiledSUMOArtifacts(plain_node_file="", plain_edge_file="", plain_connection_file="", net_file=str(net_file)),
        tmp_path,
    )

    assert result.tls_linkindex_status == "pass"
    assert result.status == "pass"


def test_validate_intersection_accepts_controlled_bicycle_support_movements(monkeypatch, tmp_path: Path) -> None:
    ir = build_intersection_ir(FIXTURES / "x4_signalized.osm.xml", tmp_path)
    support_a = ir.approaches[0].model_copy(update={"approach_id": "support_a", "allowed_modes": {"bicycle"}})
    support_b = ir.approaches[1].model_copy(update={"approach_id": "support_b", "allowed_modes": {"bicycle"}})
    support = Movement(
        movement_id="support_a_to_support_b",
        from_approach_id="support_a",
        to_approach_id="support_b",
        road_pair_relation_id="support_pair",
        turn="straight",
        allowed=True,
        from_lane_indices=[0],
        to_lane_indices=[0],
        allowed_modes={"bicycle"},
        evidence=["fixture:signalized_support_path"],
        confidence=1.0,
    )
    matrix = ir.movement_matrix.model_copy(
        update={
            "movements": [*ir.movement_matrix.movements, support],
            "legal_movement_count": ir.movement_matrix.legal_movement_count + 1,
            "inferred_movement_count": ir.movement_matrix.inferred_movement_count + 1,
        }
    )
    ir = ir.model_copy(
        update={
            "approaches": [*ir.approaches, support_a, support_b],
            "movement_matrix": matrix,
            "control": infer_control_model(ir.osm_patch, ir.core, [*ir.approaches, support_a, support_b], matrix),
        }
    )
    net_file = tmp_path / "x4_support.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    monkeypatch.setattr("torii_sumo.intersection.validate.shutil.which", lambda _name: "sumo")

    def fake_run(_command, **_kwargs):
        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr("torii_sumo.intersection.validate.subprocess.run", fake_run)

    result = validate_intersection(
        ir,
        CompiledSUMOArtifacts(plain_node_file="", plain_edge_file="", plain_connection_file="", net_file=str(net_file)),
        tmp_path,
    )

    assert support.movement_id in ir.control.link_index_map
    assert result.tls_linkindex_status == "pass"
    assert result.status == "pass"


def test_validate_intersection_blocks_missing_sumo_crossing_for_osm_support_path(monkeypatch, tmp_path: Path) -> None:
    ir = build_intersection_ir(FIXTURES / "clustered_signalized_crossing.osm.xml", tmp_path, PatchSeed(osm_node_id="seed"))
    ir.osm_patch.nodes["west"].tags = {"highway": "crossing", "crossing": "traffic_signals"}
    ir.osm_patch.nodes["side_a"] = OSMNode(id="side_a", lat=48.00055, lon=10.99950, x=-90.0, y=0.0)
    ir.osm_patch.nodes["side_b"] = OSMNode(id="side_b", lat=48.00055, lon=10.99980, x=-40.0, y=0.0)
    ir.osm_patch.ways["path_crossing"] = OSMWay(
        id="path_crossing",
        node_refs=["side_a", "west", "side_b"],
        tags={"highway": "path", "foot": "designated", "bicycle": "designated"},
    )
    support = ir.approaches[0].model_copy(
        update={
            "source_way_ids": ["path_crossing"],
            "allowed_modes": {"pedestrian", "bicycle"},
            "source_shape_xy": [(-90.0, 0.0), (ir.osm_patch.nodes["west"].x, ir.osm_patch.nodes["west"].y), (-40.0, 0.0)],
        }
    )
    ir = ir.model_copy(update={"approaches": [support, *ir.approaches[1:]]})
    net_file = tmp_path / "missing_crossing.net.xml"
    net_file.write_text("<net><edge id='vehicle'/></net>", encoding="utf-8")

    monkeypatch.setattr("torii_sumo.intersection.validate.shutil.which", lambda _name: "sumo")

    def fake_run(_command, **_kwargs):
        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr("torii_sumo.intersection.validate.subprocess.run", fake_run)

    result = validate_intersection(
        ir,
        CompiledSUMOArtifacts(plain_node_file="", plain_edge_file="", plain_connection_file="", net_file=str(net_file)),
        tmp_path,
    )

    assert "missing SUMO crossing edge for OSM pedestrian crossing support" in result.warnings
    assert result.status == "blocked"


def test_validate_intersection_handles_missing_net_file_for_crossing_probe(monkeypatch, tmp_path: Path) -> None:
    ir = build_intersection_ir(FIXTURES / "clustered_signalized_crossing.osm.xml", tmp_path, PatchSeed(osm_node_id="seed"))
    ir.osm_patch.nodes["west"].tags = {"highway": "crossing", "crossing": "traffic_signals"}
    ir.osm_patch.nodes["side_a"] = OSMNode(id="side_a", lat=48.00055, lon=10.99950, x=-90.0, y=0.0)
    ir.osm_patch.nodes["side_b"] = OSMNode(id="side_b", lat=48.00055, lon=10.99980, x=-40.0, y=0.0)
    ir.osm_patch.ways["path_crossing"] = OSMWay(
        id="path_crossing",
        node_refs=["side_a", "west", "side_b"],
        tags={"highway": "path", "foot": "designated", "bicycle": "designated"},
    )
    support = ir.approaches[0].model_copy(
        update={
            "source_way_ids": ["path_crossing"],
            "allowed_modes": {"pedestrian", "bicycle"},
            "source_shape_xy": [(-90.0, 0.0), (ir.osm_patch.nodes["west"].x, ir.osm_patch.nodes["west"].y), (-40.0, 0.0)],
        }
    )
    ir = ir.model_copy(update={"approaches": [support, *ir.approaches[1:]]})

    monkeypatch.setattr("torii_sumo.intersection.validate.shutil.which", lambda _name: "sumo")

    result = validate_intersection(
        ir,
        CompiledSUMOArtifacts(plain_node_file="", plain_edge_file="", plain_connection_file="", net_file=""),
        tmp_path,
    )

    assert "compiled net file not available" in result.warnings
    assert result.status == "blocked"


def test_validate_intersection_reports_mode_layer_counts(monkeypatch, tmp_path: Path) -> None:
    osm_file = tmp_path / "mode_cluster.osm.xml"
    osm_file.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
  <bounds minlat="48.0000" minlon="11.0000" maxlat="48.0010" maxlon="11.0010"/>
  <node id="seed" lat="48.00050" lon="11.00050"/>
  <node id="crossing" lat="48.00055" lon="11.00050"><tag k="highway" v="crossing"/><tag k="crossing" v="traffic_signals"/></node>
  <node id="vehicle_core" lat="48.00055" lon="11.00060"/>
  <node id="west" lat="48.00055" lon="11.00000"/>
  <node id="east" lat="48.00055" lon="11.00100"/>
  <node id="south" lat="48.00010" lon="11.00060"/>
  <node id="north" lat="48.00090" lon="11.00060"/>
  <node id="bike" lat="48.00075" lon="11.00035"/>
  <way id="road_ew"><nd ref="west"/><nd ref="crossing"/><nd ref="vehicle_core"/><nd ref="east"/><tag k="highway" v="secondary"/><tag k="lanes" v="4"/></way>
  <way id="road_s"><nd ref="south"/><nd ref="vehicle_core"/><tag k="highway" v="tertiary"/><tag k="lanes" v="2"/></way>
  <way id="road_n"><nd ref="north"/><nd ref="vehicle_core"/><tag k="highway" v="residential"/><tag k="lanes" v="1"/></way>
  <way id="cycleway_extra"><nd ref="bike"/><nd ref="vehicle_core"/><tag k="highway" v="cycleway"/><tag k="foot" v="no"/></way>
</osm>
""",
        encoding="utf-8",
    )
    ir = build_intersection_ir(osm_file, tmp_path, PatchSeed(osm_node_id="seed"))
    net_file = tmp_path / "mode_cluster.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    monkeypatch.setattr("torii_sumo.intersection.validate.shutil.which", lambda _name: "sumo")

    def fake_run(_command, **_kwargs):
        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr("torii_sumo.intersection.validate.subprocess.run", fake_run)

    result = validate_intersection(
        ir,
        CompiledSUMOArtifacts(plain_node_file="", plain_edge_file="", plain_connection_file="", net_file=str(net_file)),
        tmp_path,
    )

    assert result.approach_mode_counts["passenger"] == 4
    assert result.approach_mode_counts["bicycle"] == 1
    assert result.vehicle_approach_count == 4
    assert result.vehicle_topology_type == "X4"
    assert result.legal_movement_mode_counts["passenger"] > 0
    assert result.legal_movement_mode_counts.get("bicycle", 0) == 0
    assert result.forbidden_cross_mode_movement_count > 0
    assert result.status == "pass"
    assert not [warning for warning in result.warnings if "unsupported intersection topology" in warning]

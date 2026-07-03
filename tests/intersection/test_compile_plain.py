from pathlib import Path

from torii_sumo.intersection.compile_plain import compile_intersection_to_plain
from torii_sumo.intersection.infer_approaches import infer_approaches
from torii_sumo.intersection.infer_control import infer_control_model
from torii_sumo.intersection.infer_core import infer_intersection_core
from torii_sumo.intersection.infer_movements import infer_movement_matrix
from torii_sumo.intersection.infer_road_relations import build_road_pair_relation_graph
from torii_sumo.intersection.osm_patch import parse_osm_xml
from torii_sumo.intersection.schema import IntersectionIR


FIXTURES = Path(__file__).parent / "fixtures"


def test_compile_intersection_to_plain_writes_vehicle_and_tls_files(tmp_path: Path) -> None:
    ir = _build_ir(FIXTURES / "x4_signalized.osm.xml")

    artifacts = compile_intersection_to_plain(ir, tmp_path, "x4")

    for path in [
        artifacts.plain_node_file,
        artifacts.plain_edge_file,
        artifacts.plain_connection_file,
        artifacts.plain_type_file,
        artifacts.plain_tllogic_file,
    ]:
        assert path is not None
        assert Path(path).exists()

    node_text = Path(artifacts.plain_node_file).read_text()
    assert '<node id="core_1" type="traffic_light"' in node_text
    assert "<junction " not in node_text
    assert "<connection " in Path(artifacts.plain_connection_file).read_text()
    assert "<tlLogic " in Path(artifacts.plain_tllogic_file).read_text()


def test_compile_intersection_to_plain_defines_approach_highway_types(tmp_path: Path) -> None:
    ir = _build_ir(FIXTURES / "x4_signalized.osm.xml")
    ir.approaches[0].highway_class = "cycleway"
    ir.approaches[1].highway_class = "footway"

    artifacts = compile_intersection_to_plain(ir, tmp_path, "x4", compile_net=False)

    type_text = Path(artifacts.plain_type_file).read_text()
    assert 'id="highway.cycleway"' in type_text
    assert 'id="highway.footway"' in type_text


def test_compile_intersection_to_plain_writes_edge_permissions(tmp_path: Path) -> None:
    ir = _build_ir(FIXTURES / "clustered_signalized_crossing.osm.xml")

    artifacts = compile_intersection_to_plain(ir, tmp_path, "cluster", compile_net=False)

    edge_text = Path(artifacts.plain_edge_file).read_text()
    assert 'type="highway.secondary" numLanes="4" allow="passenger"' in edge_text
    assert 'type="highway.path" numLanes="1" allow="bicycle pedestrian"' in edge_text


def test_compile_intersection_to_plain_disables_auto_turnarounds(monkeypatch, tmp_path: Path) -> None:
    ir = _build_ir(FIXTURES / "x4_signalized.osm.xml")
    captured = {}
    monkeypatch.setattr("torii_sumo.intersection.compile_plain.shutil.which", lambda _name: "netconvert")

    def fake_run(command, **_kwargs):
        captured["command"] = command

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("torii_sumo.intersection.compile_plain.subprocess.run", fake_run)

    artifacts = compile_intersection_to_plain(ir, tmp_path, "x4", compile_net=True)

    assert artifacts.net_file
    assert "--no-turnarounds" in captured["command"]


def _build_ir(osm_file: Path) -> IntersectionIR:
    patch = parse_osm_xml(osm_file)
    core = infer_intersection_core(patch)
    approaches = infer_approaches(patch, core)
    graph = build_road_pair_relation_graph(patch, core, approaches)
    movements = infer_movement_matrix(core, approaches, graph)
    control = infer_control_model(patch, core, approaches, movements)
    return IntersectionIR(
        intersection_id=core.core_id,
        osm_patch=patch,
        core=core,
        approaches=approaches,
        road_pair_graph=graph,
        movement_matrix=movements,
        control=control,
        compiled=None,
        validation=None,
        claim_status="semantic-model-built",
    )

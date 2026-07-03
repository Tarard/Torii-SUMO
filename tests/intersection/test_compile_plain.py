from pathlib import Path
import xml.etree.ElementTree as ET

from torii_sumo.intersection.compile_plain import compile_intersection_to_plain
from torii_sumo.intersection.infer_approaches import infer_approaches
from torii_sumo.intersection.infer_control import infer_control_model
from torii_sumo.intersection.infer_core import infer_intersection_core
from torii_sumo.intersection.infer_movements import infer_movement_matrix
from torii_sumo.intersection.infer_road_relations import build_road_pair_relation_graph
from torii_sumo.intersection.osm_patch import parse_osm_xml
from torii_sumo.intersection.schema import IntersectionIR, Movement, OSMNode, OSMWay


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


def test_compile_intersection_to_plain_preserves_approach_shapes(tmp_path: Path) -> None:
    ir = _build_ir(FIXTURES / "x4_signalized.osm.xml")
    ir.approaches[0].source_shape_xy = [(-1.0, 2.0), (3.0, 4.0), ir.core.center_xy]

    artifacts = compile_intersection_to_plain(ir, tmp_path, "x4", compile_net=False)

    root = ET.parse(artifacts.plain_edge_file).getroot()
    incoming = root.find(f"edge[@id='{ir.approaches[0].incoming_edge_ids[0]}']")
    outgoing = root.find(f"edge[@id='{ir.approaches[0].outgoing_edge_ids[0]}']")
    assert incoming is not None
    assert outgoing is not None
    assert incoming.attrib["shape"] == "-1.00,2.00 3.00,4.00 0.00,0.00"
    assert outgoing.attrib["shape"] == "0.00,0.00 3.00,4.00 -1.00,2.00"


def test_compile_intersection_to_plain_expands_multilane_connections_and_tls(tmp_path: Path) -> None:
    ir = _build_ir(FIXTURES / "x4_signalized.osm.xml")
    movement = next(movement for movement in ir.movement_matrix.movements if movement.allowed)
    source = next(approach for approach in ir.approaches if approach.approach_id == movement.from_approach_id)
    target = next(approach for approach in ir.approaches if approach.approach_id == movement.to_approach_id)
    source.incoming_lane_count = 2
    target.outgoing_lane_count = 3
    movement.from_lane_indices = [0, 1]
    movement.to_lane_indices = [0, 1, 2]

    artifacts = compile_intersection_to_plain(ir, tmp_path, "x4", compile_net=False)

    connection_root = ET.parse(artifacts.plain_connection_file).getroot()
    rows = [
        connection.attrib
        for connection in connection_root.findall("connection")
        if connection.attrib["from"] == source.incoming_edge_ids[0] and connection.attrib["to"] == target.outgoing_edge_ids[0]
    ]
    assert [(row["fromLane"], row["toLane"]) for row in rows] == [("0", "0"), ("1", "1"), ("1", "2")]
    assert [row["linkIndex"] for row in rows] == ["0", "1", "2"]

    phase = ET.parse(artifacts.plain_tllogic_file).getroot().find("tlLogic/phase")
    assert phase is not None
    assert len(phase.attrib["state"]) == ir.movement_matrix.legal_movement_count + 2


def test_compile_intersection_to_plain_places_approach_nodes_at_inferred_endpoint(tmp_path: Path) -> None:
    ir = _build_ir(FIXTURES / "x4_signalized.osm.xml")
    ir.approaches[0].endpoint_xy = (123.4, 567.8)

    artifacts = compile_intersection_to_plain(ir, tmp_path, "x4", compile_net=False)

    root = ET.parse(artifacts.plain_node_file).getroot()
    node = root.find(f"node[@id='{ir.approaches[0].approach_id}']")
    assert node is not None
    assert node.attrib["x"] == "123.40"
    assert node.attrib["y"] == "567.80"


def test_compile_intersection_to_plain_disables_auto_turnarounds(monkeypatch, tmp_path: Path) -> None:
    ir = _build_ir(FIXTURES / "x4_signalized.osm.xml")
    captured = {}
    monkeypatch.setattr("torii_sumo.intersection.compile_plain.shutil.which", lambda _name: "netconvert")

    def fake_run(command, **_kwargs):
        captured["command"] = command

        class Result:
            returncode = 0
            stderr = "Warning: lane is not connected.\nSuccess."
            stdout = ""

        return Result()

    monkeypatch.setattr("torii_sumo.intersection.compile_plain.subprocess.run", fake_run)

    artifacts = compile_intersection_to_plain(ir, tmp_path, "x4", compile_net=True)

    assert artifacts.net_file
    assert "--no-turnarounds" in captured["command"]
    assert artifacts.netconvert_warnings == ["Warning: lane is not connected."]


def test_compile_intersection_to_plain_guesses_crossings_for_osm_support_path(monkeypatch, tmp_path: Path) -> None:
    ir = _build_ir(FIXTURES / "clustered_signalized_crossing.osm.xml")
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
    ir = ir.model_copy(
        update={
            "approaches": [support, *ir.approaches[1:]],
            "control": ir.control.model_copy(update={"control_type": "traffic_light", "tls_id": ir.core.core_id}),
        }
    )
    captured = {}
    monkeypatch.setattr("torii_sumo.intersection.compile_plain.shutil.which", lambda _name: "netconvert")

    def fake_run(command, **_kwargs):
        captured["command"] = command

        class Result:
            returncode = 0
            stderr = ""
            stdout = "Success."

        return Result()

    monkeypatch.setattr("torii_sumo.intersection.compile_plain.subprocess.run", fake_run)

    compile_intersection_to_plain(ir, tmp_path, "cluster", compile_net=True)

    assert "--crossings.guess" in captured["command"]
    assert "--walkingareas" in captured["command"]
    assert "--tllogic-files" not in captured["command"]


def test_compile_intersection_to_plain_keeps_support_paths_out_of_core_connections(tmp_path: Path) -> None:
    ir = _build_ir(FIXTURES / "clustered_signalized_crossing.osm.xml")
    support_a = ir.approaches[0].model_copy(
        update={
            "approach_id": "support_a",
            "incoming_edge_ids": ["support_a_in"],
            "outgoing_edge_ids": ["support_a_out"],
            "allowed_modes": {"bicycle"},
        }
    )
    support_b = ir.approaches[0].model_copy(
        update={
            "approach_id": "support_b",
            "incoming_edge_ids": ["support_b_in"],
            "outgoing_edge_ids": ["support_b_out"],
            "allowed_modes": {"bicycle"},
        }
    )
    support_movement = Movement(
        movement_id="support_a_to_support_b",
        from_approach_id="support_a",
        to_approach_id="support_b",
        road_pair_relation_id="support_pair",
        turn="straight",
        allowed=True,
        from_lane_indices=[0],
        to_lane_indices=[0],
        allowed_modes={"bicycle"},
        evidence=["fixture:support_path"],
        confidence=1.0,
    )
    ir = ir.model_copy(
        update={
            "approaches": [*ir.approaches, support_a, support_b],
            "movement_matrix": ir.movement_matrix.model_copy(
                update={
                    "movements": [*ir.movement_matrix.movements, support_movement],
                    "legal_movement_count": ir.movement_matrix.legal_movement_count + 1,
                    "inferred_movement_count": ir.movement_matrix.inferred_movement_count + 1,
                }
            ),
        }
    )

    artifacts = compile_intersection_to_plain(ir, tmp_path, "cluster", compile_net=False)

    connection_root = ET.parse(artifacts.plain_connection_file).getroot()
    assert connection_root.find("connection[@from='support_a_in'][@to='support_b_out']") is None


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

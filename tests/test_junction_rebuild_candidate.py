import csv
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET

from torii_sumo.core.junction_rebuild_candidate import (
    _approach_endpoint_rebuild_plan,
    _compare_teacher_models,
    _expanded_scope_followup_candidate_for_unsafe_internal_replay,
    _netedit_review_actions,
    _remove_teacher_non_tls_tllogics,
    _limit_ready_repair_candidates,
    _restore_false_traffic_light_junction_types,
    _restore_non_target_internal_artifacts,
    _restore_replayed_geometry_attrs,
    _semantic_layer_gates,
    _teacher_candidate_edge_map,
    _teacher_guided_semantics_gate,
    _target_internal_replay_input_file,
    _write_teacher_guided_promotion_gate,
    _write_joined_endpoint_edge_file,
    _stage_file,
    _teacher_guided_candidate_sort_key,
    build_rebuild_candidate,
    build_teacher_guided_repair_queue,
    build_teacher_guided_junction_variant,
    build_tls_connection_repair_variant,
    run_teacher_guided_repair_queue,
    write_expanded_scope_plain_inputs,
    write_teacher_target_internal_replay_net,
    write_teacher_connection_plan,
    write_teacher_endpoint_patch_nodes,
    write_teacher_lane_patch_edges,
    write_teacher_pedestrian_ring_net,
    write_teacher_tllogic_net,
    write_teacher_vehicle_connection_attrs_net,
)
from torii_sumo.core.reference_join_audit import audit_reference_join_patterns


def test_target_internal_replay_input_file_uses_seed_net_when_joined_junction_is_missing(
    tmp_path: Path,
) -> None:
    vehicle_attrs_net = tmp_path / "vehicle_attrs.net.xml"
    vehicle_attrs_net.write_text('<net><junction id="a"/></net>', encoding="utf-8")
    seed_candidate_net = tmp_path / "full_network_join_replay.net.xml"
    seed_candidate_net.write_text('<net><junction id="cluster_a_b"/></net>', encoding="utf-8")

    assert (
        _target_internal_replay_input_file(
            vehicle_attrs_net_file=vehicle_attrs_net,
            candidate_net_file=seed_candidate_net,
            junction_id="cluster_a_b",
        )
        == seed_candidate_net
    )


def test_target_internal_replay_input_file_keeps_vehicle_attrs_when_target_exists(
    tmp_path: Path,
) -> None:
    vehicle_attrs_net = tmp_path / "vehicle_attrs.net.xml"
    vehicle_attrs_net.write_text('<net><junction id="cluster_a_b"/></net>', encoding="utf-8")
    seed_candidate_net = tmp_path / "full_network_join_replay.net.xml"
    seed_candidate_net.write_text('<net><junction id="cluster_a_b"/></net>', encoding="utf-8")

    assert (
        _target_internal_replay_input_file(
            vehicle_attrs_net_file=vehicle_attrs_net,
            candidate_net_file=seed_candidate_net,
            junction_id="cluster_a_b",
        )
        == vehicle_attrs_net
    )


def test_teacher_candidate_edge_map_can_use_expanded_scope_bearing_delta() -> None:
    teacher_model = {
        "approaches": {
            "incoming": [
                {"edge_id": "teacher_in", "bearing": 0.0, "lane_count": 1, "type": "highway.tertiary"}
            ],
            "outgoing": [],
        }
    }
    candidate_model = {
        "approaches": {
            "incoming": [
                {"edge_id": "candidate_in", "bearing": 40.0, "lane_count": 1, "type": "highway.tertiary"}
            ],
            "outgoing": [],
        }
    }

    assert (
        _teacher_candidate_edge_map(
            teacher_model,
            candidate_model,
            max_bearing_delta=45.0,
        )
        == {"teacher_in": "candidate_in"}
    )


def test_teacher_candidate_edge_map_prefers_exact_edge_id_before_bearing() -> None:
    teacher_model = {
        "junction_id": "j",
        "approaches": {
            "incoming": [
                {
                    "edge_id": "main#3",
                    "from": "a",
                    "to": "j",
                    "bearing": 180.0,
                    "lane_count": 1,
                    "type": "highway.path",
                }
            ],
            "outgoing": [],
        },
    }
    candidate_model = {
        "junction_id": "j",
        "approaches": {
            "incoming": [
                {
                    "edge_id": "wrong_bearing_match",
                    "from": "b",
                    "to": "j",
                    "bearing": 181.0,
                    "lane_count": 1,
                    "type": "highway.path",
                },
                {
                    "edge_id": "main#3",
                    "from": "a",
                    "to": "j",
                    "bearing": 150.0,
                    "lane_count": 1,
                    "type": "highway.path",
                },
            ],
            "outgoing": [],
        },
    }

    assert _teacher_candidate_edge_map(
        teacher_model,
        candidate_model,
        teacher_junction_id="j",
        candidate_junction_id="j",
    ) == {"main#3": "main#3"}


def test_restore_false_traffic_light_junction_types_only_restores_uncontrolled_noise(tmp_path: Path) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text(
        """<net>
  <edge id="e1" from="a" to="false_tls"><lane id="e1_0" index="0"/></edge>
  <edge id="e2" from="real_tls" to="b"><lane id="e2_0" index="0"/></edge>
  <junction id="false_tls" type="priority" x="0" y="0" incLanes="e1_0" intLanes=""/>
  <junction id="real_tls" type="traffic_light" x="1" y="0" incLanes="e2_0" intLanes="">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <junction id="already_tls" type="traffic_light" x="2" y="0" incLanes="" intLanes=""/>
  <tlLogic id="real_tls" type="static" programID="0" offset="0"><phase duration="1" state="G"/></tlLogic>
  <connection from="e2" to="e2" fromLane="0" toLane="0" tl="real_tls" linkIndex="0"/>
</net>
""",
        encoding="utf-8",
    )
    normalized = tmp_path / "normalized.net.xml"
    normalized.write_text(
        """<net>
  <edge id="e1" from="a" to="false_tls"><lane id="e1_0" index="0"/></edge>
  <edge id="e2" from="real_tls" to="b"><lane id="e2_0" index="0"/></edge>
  <junction id="false_tls" type="traffic_light" x="0" y="0" incLanes="e1_0" intLanes="">
    <request index="9" response="1" foes="1" cont="0"/>
  </junction>
  <junction id="real_tls" type="traffic_light" x="1" y="0" incLanes="e2_0" intLanes=""/>
  <junction id="already_tls" type="traffic_light" x="2" y="0" incLanes="" intLanes=""/>
  <tlLogic id="real_tls" type="static" programID="0" offset="0"><phase duration="1" state="G"/></tlLogic>
  <connection from="e2" to="e2" fromLane="0" toLane="0" tl="real_tls" linkIndex="0"/>
</net>
""",
        encoding="utf-8",
    )

    report = _restore_false_traffic_light_junction_types(source_file=source, target_file=normalized)

    root = ET.parse(normalized).getroot()
    assert report["status"] == "pass"
    assert report["restored_false_traffic_light_junction_type_count"] == 1
    assert root.find("junction[@id='false_tls']").attrib["type"] == "priority"
    assert root.find("junction[@id='false_tls']/request").attrib["index"] == "9"
    assert root.find("junction[@id='real_tls']").attrib["type"] == "traffic_light"
    assert root.find("junction[@id='already_tls']").attrib["type"] == "traffic_light"


def test_restore_false_traffic_light_junction_types_uses_plain_node_fallback_for_polluted_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "polluted_source.net.xml"
    source.write_text(
        """<net>
  <junction id="false_tls" type="traffic_light" x="0" y="0" incLanes="" intLanes=""/>
  <junction id="real_tls" type="traffic_light" x="1" y="0" incLanes="" intLanes=""/>
  <tlLogic id="real_tls" type="static" programID="0" offset="0"><phase duration="1" state="G"/></tlLogic>
  <connection from="e" to="e" fromLane="0" toLane="0" tl="real_tls" linkIndex="0"/>
</net>
""",
        encoding="utf-8",
    )
    plain_nodes = tmp_path / "raw.nod.xml"
    plain_nodes.write_text(
        """<nodes>
  <node id="false_tls" type="priority" x="0" y="0"/>
  <node id="real_tls" type="traffic_light" x="1" y="0"/>
</nodes>
""",
        encoding="utf-8",
    )
    normalized = tmp_path / "normalized.net.xml"
    normalized.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    report = _restore_false_traffic_light_junction_types(
        source_file=source,
        target_file=normalized,
        fallback_node_file=plain_nodes,
    )

    root = ET.parse(normalized).getroot()
    assert report["status"] == "pass"
    assert report["restored_false_traffic_light_junction_type_count"] == 1
    assert root.find("junction[@id='false_tls']").attrib["type"] == "priority"
    assert root.find("junction[@id='real_tls']").attrib["type"] == "traffic_light"


def test_remove_teacher_non_tls_tllogics_demotes_exact_priority_junction(tmp_path: Path) -> None:
    teacher = tmp_path / "teacher.net.xml"
    teacher.write_text(
        """<net>
  <junction id="priority_j" type="priority" x="0" y="0"/>
  <junction id="real_tls" type="traffic_light" x="1" y="0"/>
  <tlLogic id="real_tls" type="static" programID="0"><phase duration="1" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    target = tmp_path / "target.net.xml"
    target.write_text(
        """<net>
  <junction id="priority_j" type="traffic_light" x="0" y="0"/>
  <junction id="real_tls" type="traffic_light" x="1" y="0"/>
  <tlLogic id="priority_j" type="actuated" programID="0"><phase duration="30" state="G"/></tlLogic>
  <tlLogic id="real_tls" type="static" programID="0"><phase duration="1" state="G"/></tlLogic>
  <connection from="a" to="b" tl="priority_j" linkIndex="0" linkIndex2="9"/>
  <connection from="c" to="d" tl="real_tls" linkIndex="0"/>
</net>
""",
        encoding="utf-8",
    )

    report = _remove_teacher_non_tls_tllogics(teacher_net_file=teacher, target_file=target)

    root = ET.parse(target).getroot()
    priority_connection = root.find("connection[@from='a']")
    assert report["status"] == "pass"
    assert report["removed_teacher_non_tls_tllogic_ids"] == ["priority_j"]
    assert root.find("tlLogic[@id='priority_j']") is None
    assert root.find("tlLogic[@id='real_tls']") is not None
    assert root.find("junction[@id='priority_j']").attrib["type"] == "priority"
    assert "tl" not in priority_connection.attrib
    assert "linkIndex" not in priority_connection.attrib
    assert "linkIndex2" not in priority_connection.attrib
    assert priority_connection.attrib["uncontrolled"] == "true"
    assert root.find("connection[@from='c']").attrib["tl"] == "real_tls"


def test_build_tls_connection_repair_variant_restores_unique_connection_control_attrs(tmp_path: Path) -> None:
    source_net = tmp_path / "source.net.xml"
    source_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <edge id="right" from="j" to="c"><lane id="right_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0" tl="tlsA" linkIndex="3" linkIndex2="9" dir="s" state="O" pass="true" allow="passenger"/>
  <connection from="in" to="right" fromLane="0" toLane="0" dir="r" state="M"/>
  <tlLogic id="tlsA" type="actuated" programID="0" offset="5">
    <phase duration="4" minDur="2" maxDur="7" state="G"/>
  </tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <edge id="right" from="j" to="c"><lane id="right_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0" uncontrolled="true"/>
  <connection from="in" to="right" fromLane="0" toLane="0" uncontrolled="true"/>
  <tlLogic id="old" type="static" programID="0"><phase duration="1" state="r"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )

    report = build_tls_connection_repair_variant(
        source_net_file=source_net,
        candidate_net_file=candidate_net,
        output_dir=tmp_path / "out",
        prefix="demo",
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["source_tls_controlled_connection_count"] == 1
    assert report["candidate_tls_controlled_connection_count_before"] == 0
    assert report["candidate_tls_controlled_connection_count_after"] == 1
    assert report["updated_connection_count"] == 1
    assert report["copied_tllogic_count"] == 1
    root = ET.parse(report["variant_file"]).getroot()
    repaired = root.find("connection[@from='in'][@to='out']")
    assert repaired.attrib["tl"] == "tlsA"
    assert repaired.attrib["linkIndex"] == "3"
    assert repaired.attrib["linkIndex2"] == "9"
    assert repaired.attrib["dir"] == "s"
    assert repaired.attrib["state"] == "O"
    assert repaired.attrib["pass"] == "true"
    assert repaired.attrib["allow"] == "passenger"
    assert "uncontrolled" not in repaired.attrib
    untouched = root.find("connection[@from='in'][@to='right']")
    assert untouched.attrib["uncontrolled"] == "true"
    target_tls = root.find("tlLogic[@id='tlsA']")
    assert target_tls.attrib["type"] == "actuated"
    assert target_tls.find("phase").attrib["minDur"] == "2"


def test_build_tls_connection_repair_variant_can_remap_tls_without_copying_raw_tllogic(tmp_path: Path) -> None:
    source_net = tmp_path / "source.net.xml"
    source_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0" tl="rawTls" linkIndex="4" dir="l" state="o"/>
  <tlLogic id="rawTls" type="actuated" programID="0"><phase duration="4" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <tlLogic id="aggTls" type="static" programID="0"><phase duration="1" state="r"/></tlLogic>
  <connection from="in" to="out" fromLane="0" toLane="0" uncontrolled="true"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_tls_connection_repair_variant(
        source_net_file=source_net,
        candidate_net_file=candidate_net,
        output_dir=tmp_path / "out",
        prefix="demo",
        tls_id_map={"rawTls": "aggTls"},
        copy_unmapped_tls=False,
    )

    root = ET.parse(report["variant_file"]).getroot()
    repaired = root.find("connection[@from='in'][@to='out']")
    assert repaired.attrib["tl"] == "aggTls"
    assert repaired.attrib["linkIndex"] == "4"
    assert root.find("tlLogic[@id='rawTls']") is None
    assert root.find("tlLogic[@id='aggTls']").attrib["type"] == "static"
    assert report["copied_tllogic_count"] == 0
    assert report["replaced_tllogic_count"] == 0
    assert report["skipped_unmapped_tls_connection_count"] == 0


def test_build_tls_connection_repair_variant_can_require_target_link_index_capacity(tmp_path: Path) -> None:
    source_net = tmp_path / "source.net.xml"
    source_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0" tl="rawTls" linkIndex="4" dir="l" state="o"/>
  <tlLogic id="rawTls" type="actuated" programID="0"><phase duration="4" state="GGGGG"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <tlLogic id="aggTls" type="static" programID="0"><phase duration="1" state="r"/></tlLogic>
  <connection from="in" to="out" fromLane="0" toLane="0" uncontrolled="true"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_tls_connection_repair_variant(
        source_net_file=source_net,
        candidate_net_file=candidate_net,
        output_dir=tmp_path / "out",
        prefix="demo",
        tls_id_map={"rawTls": "aggTls"},
        copy_unmapped_tls=False,
        require_target_link_index_capacity=True,
    )

    root = ET.parse(report["variant_file"]).getroot()
    connection = root.find("connection[@from='in'][@to='out']")
    assert connection.attrib["uncontrolled"] == "true"
    assert "tl" not in connection.attrib
    assert report["updated_connection_count"] == 0
    assert report["skipped_invalid_mapped_linkindex_connection_count"] == 1
    assert report["invalid_mapped_linkindex_capacity_gaps"] == [
        {
            "target_tls": "aggTls",
            "target_capacity": 1,
            "required_state_length": 5,
            "max_required_link_index": 4,
            "skipped_connection_count": 1,
            "source_tls_ids": ["rawTls"],
        }
    ]


def test_build_tls_connection_repair_variant_can_pad_target_tllogic_capacity(tmp_path: Path) -> None:
    source_net = tmp_path / "source.net.xml"
    source_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0" tl="rawTls" linkIndex="4" dir="l" state="o"/>
  <tlLogic id="rawTls" type="actuated" programID="0"><phase duration="4" state="GGGGG"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <tlLogic id="aggTls" type="static" programID="0"><phase duration="1" state="r"/></tlLogic>
  <connection from="in" to="out" fromLane="0" toLane="0" uncontrolled="true"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_tls_connection_repair_variant(
        source_net_file=source_net,
        candidate_net_file=candidate_net,
        output_dir=tmp_path / "out",
        prefix="demo",
        tls_id_map={"rawTls": "aggTls"},
        copy_unmapped_tls=False,
        require_target_link_index_capacity=True,
        pad_mapped_tllogic_capacity=True,
    )

    root = ET.parse(report["variant_file"]).getroot()
    connection = root.find("connection[@from='in'][@to='out']")
    assert connection.attrib["tl"] == "aggTls"
    assert connection.attrib["linkIndex"] == "4"
    assert root.find("tlLogic[@id='aggTls']/phase").attrib["state"] == "rrrrr"
    assert report["updated_connection_count"] == 1
    assert report["skipped_invalid_mapped_linkindex_connection_count"] == 0
    assert report["padded_tllogic_count"] == 1
    assert report["padded_tllogic_phase_count"] == 1


def test_build_tls_connection_repair_variant_can_add_green_phase_for_padded_links(tmp_path: Path) -> None:
    source_net = tmp_path / "source.net.xml"
    source_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0" tl="rawTls" linkIndex="2" dir="s" state="O"/>
  <tlLogic id="rawTls" type="actuated" programID="0"><phase duration="4" state="rrG"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <tlLogic id="aggTls" type="static" programID="0"><phase duration="1" state="r"/></tlLogic>
  <connection from="in" to="out" fromLane="0" toLane="0" uncontrolled="true"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_tls_connection_repair_variant(
        source_net_file=source_net,
        candidate_net_file=candidate_net,
        output_dir=tmp_path / "out",
        prefix="demo",
        tls_id_map={"rawTls": "aggTls"},
        copy_unmapped_tls=False,
        require_target_link_index_capacity=True,
        pad_mapped_tllogic_capacity=True,
        add_green_phases_for_padded_links=True,
    )

    states = [phase.attrib["state"] for phase in ET.parse(report["variant_file"]).getroot().findall("tlLogic[@id='aggTls']/phase")]
    assert states == ["rrr", "rrG"]
    assert report["added_green_phase_count"] == 1
    assert report["added_green_phase_tllogic_count"] == 1


def test_build_tls_connection_repair_variant_can_add_yellow_phase_after_generated_green(tmp_path: Path) -> None:
    source_net = tmp_path / "source.net.xml"
    source_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0" tl="rawTls" linkIndex="2" dir="s" state="O"/>
  <tlLogic id="rawTls" type="actuated" programID="0"><phase duration="4" state="rrG"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" incLanes="in_0" intLanes=""/>
  <tlLogic id="aggTls" type="static" programID="0"><phase duration="1" state="r"/></tlLogic>
  <connection from="in" to="out" fromLane="0" toLane="0" uncontrolled="true"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_tls_connection_repair_variant(
        source_net_file=source_net,
        candidate_net_file=candidate_net,
        output_dir=tmp_path / "out",
        prefix="demo",
        tls_id_map={"rawTls": "aggTls"},
        copy_unmapped_tls=False,
        require_target_link_index_capacity=True,
        pad_mapped_tllogic_capacity=True,
        add_green_phases_for_padded_links=True,
        add_yellow_phases_for_generated_green=True,
    )

    states = [phase.attrib["state"] for phase in ET.parse(report["variant_file"]).getroot().findall("tlLogic[@id='aggTls']/phase")]
    assert states == ["rrr", "rrG", "rry"]
    assert report["added_green_phase_count"] == 1
    assert report["added_yellow_phase_count"] == 1
    assert report["added_yellow_phase_tllogic_count"] == 1


def test_netedit_review_actions_routes_movement_signature_delta_to_vehicle_matrix_rebuild() -> None:
    assert _netedit_review_actions(["movement_signature_counts"]) == ["rebuild_vehicle_movement_matrix"]


def test_approach_endpoint_rebuild_plan_requires_neighbor_scope_for_endpoint_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "approaches": {
            "incoming": [
                {"edge_id": "teacher_in", "from": "teacher_boundary", "to": "teacher_j"},
            ],
            "outgoing": [
                {"edge_id": "teacher_out", "from": "teacher_j", "to": "teacher_exit"},
            ],
        },
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "approaches": {
            "incoming": [
                {"edge_id": "cand_in", "from": "candidate_boundary", "to": "candidate_j"},
            ],
            "outgoing": [
                {"edge_id": "cand_out", "from": "candidate_j", "to": "teacher_exit"},
            ],
        },
    }

    plan = _approach_endpoint_rebuild_plan(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
        candidate_junction_ids={"candidate_j", "candidate_boundary", "teacher_boundary", "teacher_exit"},
    )

    assert plan["status"] == "review"
    assert plan["mismatch_count"] == 1
    assert plan["recommended_action"] == "expand_rebuild_scope"
    assert plan["affected_neighbor_junction_ids"] == ["candidate_boundary", "teacher_boundary"]
    assert plan["missing_desired_endpoint_ids"] == []
    assert plan["edge_rebuilds"] == [
        {
            "approach_key": "incoming:cand_in",
            "edge_id": "cand_in",
            "direction": "incoming",
            "candidate_from": "candidate_boundary",
            "candidate_to": "candidate_j",
            "desired_from": "teacher_boundary",
            "desired_to": "candidate_j",
            "affected_neighbor_junction_ids": ["candidate_boundary", "teacher_boundary"],
            "missing_desired_endpoint_ids": [],
            "unsafe_direct_rewrite": True,
            "reason": "endpoint change affects neighboring junction connections and tlLogic; rebuild expanded scope",
        }
    ]


def test_build_rebuild_candidate_emits_only_high_confidence_vehicle_connections(tmp_path: Path) -> None:
    net_file = tmp_path / "fixture.net.xml"
    net_file.write_text(
        """<net>
  <edge id="west_in" from="w" to="j" type="highway.primary" name="Main Street">
    <lane id="west_in_0" index="0" allow="passenger" length="10" shape="-10,0 0,0"/>
  </edge>
  <edge id="east_out" from="j" to="e" type="highway.primary" name="Main Street">
    <lane id="east_out_0" index="0" allow="passenger" length="10" shape="0,0 10,0"/>
  </edge>
  <edge id="south_out" from="j" to="s" type="highway.secondary" name="South Road">
    <lane id="south_out_0" index="0" allow="passenger" length="10" shape="0,0 0,-10"/>
  </edge>
  <edge id="west_out" from="j" to="w2" type="highway.primary" name="Main Street">
    <lane id="west_out_0" index="0" allow="passenger" length="10" shape="0,0 -10,0"/>
  </edge>
  <edge id="foot_out" from="j" to="p" type="highway.footway">
    <lane id="foot_out_0" index="0" allow="pedestrian" length="5" shape="0,0 0,5"/>
  </edge>
  <junction id="w" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="e" x="10" y="0" type="priority"/>
  <junction id="s" x="0" y="-10" type="priority"/>
  <junction id="w2" x="-10" y="0" type="priority"/>
  <junction id="p" x="0" y="5" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_rebuild_candidate(net_file=net_file, junction_id="j", output_dir=tmp_path / "candidate", prefix="demo")

    assert report["status"] == "pass"
    assert report["emitted_connection_count"] == 2
    assert report["skipped_movement_count"] == 1
    root = ET.parse(report["connections_file"]).getroot()
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("connection")] == [
        ("west_in", "east_out"),
        ("west_in", "south_out"),
    ]
    assert "--connection-files" in Path(report["netconvert_command_file"]).read_text(encoding="utf-8")


def test_build_rebuild_candidate_can_filter_with_exemplar_movement_signatures(tmp_path: Path) -> None:
    net_file = tmp_path / "fixture.net.xml"
    net_file.write_text(
        """<net>
  <edge id="west_in" from="w" to="j" type="highway.primary" name="Main Street">
    <lane id="west_in_0" index="0" allow="passenger" length="10" shape="-10,0 0,0"/>
  </edge>
  <edge id="east_out" from="j" to="e" type="highway.primary" name="Main Street">
    <lane id="east_out_0" index="0" allow="passenger" length="10" shape="0,0 10,0"/>
  </edge>
  <edge id="south_out" from="j" to="s" type="highway.secondary" name="South Road">
    <lane id="south_out_0" index="0" allow="passenger" length="10" shape="0,0 0,-10"/>
  </edge>
  <junction id="w" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="e" x="10" y="0" type="priority"/>
  <junction id="s" x="0" y="-10" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_rebuild_candidate(
        net_file=net_file,
        junction_id="j",
        output_dir=tmp_path / "candidate",
        prefix="demo",
        movement_exemplar={
            "movement_signatures": [
                {
                    "from_slot": "slot_0",
                    "to_slot": "slot_1",
                    "fromLane": "0",
                    "toLane": "0",
                    "dir": "s",
                    "state": "O",
                }
            ]
        },
        slot_edge_map={"slot_0": "west_in", "slot_1": "east_out"},
    )

    root = ET.parse(report["connections_file"]).getroot()
    assert report["movement_source"] == "exemplar_signatures"
    assert report["emitted_connection_count"] == 1
    assert report["skipped_movement_count"] == 1
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("connection")] == [
        ("west_in", "east_out"),
    ]


def test_build_rebuild_candidate_can_filter_with_teacher_edge_map(tmp_path: Path) -> None:
    net_file = tmp_path / "fixture.net.xml"
    net_file.write_text(
        """<net>
  <edge id="west_in" from="w" to="j" type="highway.primary" name="Main Street">
    <lane id="west_in_0" index="0" allow="passenger" length="10" shape="-10,0 0,0"/>
  </edge>
  <edge id="east_out" from="j" to="e" type="highway.primary" name="Main Street">
    <lane id="east_out_0" index="0" allow="passenger" length="10" shape="0,0 10,0"/>
  </edge>
  <edge id="south_out" from="j" to="s" type="highway.secondary" name="South Road">
    <lane id="south_out_0" index="0" allow="passenger" length="10" shape="0,0 0,-10"/>
  </edge>
  <junction id="w" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="e" x="10" y="0" type="priority"/>
  <junction id="s" x="0" y="-10" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_rebuild_candidate(
        net_file=net_file,
        junction_id="j",
        output_dir=tmp_path / "candidate",
        prefix="demo",
        movement_exemplar={
            "approach_slots": [
                {"slot_id": "slot_0", "members": ["teacher_in"]},
                {"slot_id": "slot_1", "members": ["teacher_out"]},
            ],
            "movement_signatures": [
                {"from_slot": "slot_0", "to_slot": "slot_1", "fromLane": "0", "toLane": "0", "dir": "s"}
            ],
        },
        teacher_edge_map={"teacher_in": "west_in", "teacher_out": "east_out"},
    )

    root = ET.parse(report["connections_file"]).getroot()
    assert report["slot_edge_map"] == {"slot_0": "west_in", "slot_1": "east_out"}
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("connection")] == [
        ("west_in", "east_out"),
    ]


def test_rebuild_candidate_writes_connection_signature(tmp_path: Path) -> None:
    net_file = tmp_path / "fixture.net.xml"
    net_file.write_text(
        """<net>
  <edge id="west_in" from="w" to="j" type="highway.primary" name="Main"><lane id="west_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="east_out" from="j" to="e" type="highway.primary" name="Main"><lane id="east_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="w" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="e" x="10" y="0" type="priority"/>
  <connection from="west_in" to="east_out" fromLane="0" toLane="0" dir="s" state="o"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_rebuild_candidate(net_file=net_file, junction_id="j", output_dir=tmp_path / "candidate", prefix="demo")

    assert Path(report["connection_signature"]["signature_file"]).is_file()
    assert report["connection_signature"]["status"] == "pass"


def test_build_teacher_guided_repair_queue_maps_ready_reference_join(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_a_b" type="highway.primary"><lane id="teacher_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_a_b" to="b" type="highway.primary"><lane id="teacher_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="traffic_light" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="cluster_a_b" linkIndex="0" dir="s"/>
  <tlLogic id="cluster_a_b" type="actuated" programID="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="cluster_a_b" type="highway.primary"><lane id="cand_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="cluster_a_b" to="b" type="highway.primary"><lane id="cand_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="traffic_light" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": "cluster_a_b",
                    "learned_rule": "tum_like_join_candidate",
                    "reference_joined_source_nodes": ["a", "b"],
                }
            ],
            "junction_pattern_comparisons": [
                {
                    "junction_id": "a",
                    "status": "fail",
                    "mismatch_fields": ["internal_function_counts", "has_tls"],
                    "teacher": {
                        "has_tls": True,
                        "internal_function_counts": {"crossing": 1, "internal": 3, "walkingarea": 1},
                    },
                    "candidate": {
                        "has_tls": False,
                        "internal_function_counts": {"crossing": 0, "internal": 1, "walkingarea": 0},
                    },
                }
            ],
            "junction_pattern_mismatch_field_counts": {"internal_function_counts": 1, "has_tls": 1},
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    assert report["status"] == "pass"
    assert report["teacher_net_file"] == str(teacher_net.resolve())
    assert report["candidate_net_file"] == str(candidate_net.resolve())
    assert report["repair_candidate_count"] == 1
    assert report["ready_candidate_count"] == 1
    candidate = report["repair_candidates"][0]
    assert candidate["candidate_status"] == "ready_for_teacher_guided_variant"
    assert candidate["junction_id"] == "cluster_a_b"
    assert candidate["junction_pattern_mismatch_fields"] == ["internal_function_counts", "has_tls"]
    assert candidate["netedit_review_actions"] == [
        "rebuild_vehicle_movement_matrix",
        "inspect_internal_edges_crossings_walkingareas",
        "inspect_tls_control",
    ]
    assert candidate["vehicle_movement_matrix_missing_count"] == 1
    assert candidate["review_priority"] == "high"
    assert candidate["junction_pattern_delta_count"] == 1
    assert candidate["junction_pattern_deltas"][0]["junction_id"] == "a"
    assert candidate["junction_pattern_deltas"][0]["teacher"]["has_tls"] is True
    assert candidate["junction_pattern_deltas"][0]["candidate"]["has_tls"] is False
    assert candidate["edge_map"] == {"teacher_in": "cand_in", "teacher_out": "cand_out"}
    assert candidate["slot_edge_map"] == {"slot_0": "cand_in", "slot_1": "cand_out"}
    assert candidate["movement_exemplar"]["movement_signatures"] == [
        {
            "from_slot": "slot_0",
            "to_slot": "slot_1",
            "fromLane": "0",
            "toLane": "0",
            "dir": "s",
            "state": "",
            "controlled": True,
            "linkIndex": "0",
            "has_internal_via": False,
        }
    ]
    assert Path(report["queue_file"]).is_file()
    assert report["junction_pattern_mismatch_field_counts"] == {"internal_function_counts": 1, "has_tls": 1}
    rows = list(csv.DictReader(Path(report["queue_csv_file"]).read_text(encoding="utf-8").splitlines()))
    assert rows[0]["junction_pattern_delta_count"] == "1"
    assert rows[0]["junction_pattern_mismatch_fields"] == "internal_function_counts;has_tls"
    assert (
        rows[0]["netedit_review_actions"]
        == "rebuild_vehicle_movement_matrix;inspect_internal_edges_crossings_walkingareas;inspect_tls_control"
    )
    assert rows[0]["vehicle_movement_matrix_missing_count"] == "1"
    assert rows[0]["review_priority"] == "high"


def test_build_teacher_guided_repair_queue_carries_tls_semantic_repairs(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text("<net/>", encoding="utf-8")
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text("<net/>", encoding="utf-8")

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [],
            "tls_control_review_queue": [
                {
                    "repair_category": "tls_controller_cardinality_repair",
                    "review_type": "restore_tls_controlled_connections",
                    "reference_count": 550,
                    "candidate_count": 160,
                    "missing_count": 390,
                },
                {
                    "repair_category": "tls_linkindex_phase_repair",
                    "review_type": "restore_shared_linkindex_groups",
                    "reference_count": 40,
                    "candidate_count": 0,
                    "missing_count": 40,
                },
            ],
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    assert report["repair_candidate_count"] == 0
    assert report["tls_repair_candidate_count"] == 2
    assert report["tls_repair_category_counts"] == {
        "tls_controller_cardinality_repair": 1,
        "tls_linkindex_phase_repair": 1,
    }
    assert [candidate["candidate_status"] for candidate in report["tls_repair_candidates"]] == [
        "needs_tls_semantic_repair",
        "needs_tls_semantic_repair",
    ]
    assert report["tls_repair_candidates"][0]["netedit_review_actions"] == ["inspect_tls_control"]
    assert report["tls_repair_candidates"][1]["netedit_review_actions"] == ["inspect_tls_linkindex_phase"]
    assert json.loads(Path(report["queue_file"]).read_text(encoding="utf-8"))["tls_repair_candidate_count"] == 2


def test_build_teacher_guided_repair_queue_flags_vehicle_movement_matrix_gap(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_w_in" from="w" to="cluster_j" type="highway.primary"><lane id="teacher_w_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="teacher_s_in" from="s" to="cluster_j" type="highway.primary"><lane id="teacher_s_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="teacher_e_out" from="cluster_j" to="e" type="highway.primary"><lane id="teacher_e_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="teacher_n_out" from="cluster_j" to="n" type="highway.primary"><lane id="teacher_n_out_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <junction id="cluster_j" type="priority" x="0" y="0" incLanes="teacher_w_in_0 teacher_s_in_0" intLanes=""/>
  <connection from="teacher_w_in" to="teacher_e_out" fromLane="0" toLane="0"/>
  <connection from="teacher_w_in" to="teacher_n_out" fromLane="0" toLane="0"/>
  <connection from="teacher_s_in" to="teacher_e_out" fromLane="0" toLane="0"/>
  <connection from="teacher_s_in" to="teacher_n_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="teacher_w_in" from="w" to="cluster_j" type="highway.primary"><lane id="teacher_w_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="teacher_s_in" from="s" to="cluster_j" type="highway.primary"><lane id="teacher_s_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="teacher_e_out" from="cluster_j" to="e" type="highway.primary"><lane id="teacher_e_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="teacher_n_out" from="cluster_j" to="n" type="highway.primary"><lane id="teacher_n_out_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <junction id="cluster_j" type="priority" x="0" y="0" incLanes="teacher_w_in_0 teacher_s_in_0" intLanes=""/>
  <connection from="teacher_w_in" to="teacher_e_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": "cluster_j",
                    "learned_rule": "tum_like_join_candidate",
                    "reference_joined_source_nodes": ["w", "s"],
                }
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert candidate["candidate_status"] == "ready_for_teacher_guided_variant"
    assert candidate["vehicle_movement_matrix_missing_count"] == 3
    assert candidate["missing_teacher_movement_plan"] == [
        {
            "teacher_from_edge_id": "teacher_w_in",
            "teacher_to_edge_id": "teacher_n_out",
            "from_edge_id": "teacher_w_in",
            "to_edge_id": "teacher_n_out",
            "fromLane": "0",
            "toLane": "0",
            "dir": "",
            "state": "",
            "tl": "",
            "linkIndex": "",
            "via": "",
            "controlled": False,
            "has_internal_via": False,
            "match_status": "missing_candidate_connection",
        },
        {
            "teacher_from_edge_id": "teacher_s_in",
            "teacher_to_edge_id": "teacher_e_out",
            "from_edge_id": "teacher_s_in",
            "to_edge_id": "teacher_e_out",
            "fromLane": "0",
            "toLane": "0",
            "dir": "",
            "state": "",
            "tl": "",
            "linkIndex": "",
            "via": "",
            "controlled": False,
            "has_internal_via": False,
            "match_status": "missing_candidate_connection",
        },
        {
            "teacher_from_edge_id": "teacher_s_in",
            "teacher_to_edge_id": "teacher_n_out",
            "from_edge_id": "teacher_s_in",
            "to_edge_id": "teacher_n_out",
            "fromLane": "0",
            "toLane": "0",
            "dir": "",
            "state": "",
            "tl": "",
            "linkIndex": "",
            "via": "",
            "controlled": False,
            "has_internal_via": False,
            "match_status": "missing_candidate_connection",
        },
    ]
    assert candidate["netedit_review_actions"] == ["rebuild_vehicle_movement_matrix"]
    assert candidate["review_priority"] == "high"
    rows = list(csv.DictReader(Path(report["queue_csv_file"]).read_text(encoding="utf-8").splitlines()))
    assert rows[0]["vehicle_movement_matrix_missing_count"] == "3"
    assert rows[0]["missing_teacher_movement_plan_count"] == "3"
    assert rows[0]["netedit_review_actions"] == "rebuild_vehicle_movement_matrix"


def test_build_teacher_guided_repair_queue_does_not_treat_turnaround_as_route_complete(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="in" from="w" to="j" type="highway.primary"><lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="normal_out" from="j" to="e" type="highway.primary"><lane id="normal_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="turn_out" from="j" to="w" type="highway.primary"><lane id="turn_out_0" index="0" allow="passenger" shape="0,0 -10,0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="in_0" intLanes=""/>
  <connection from="in" to="normal_out" fromLane="0" toLane="0" dir="s"/>
  <connection from="in" to="turn_out" fromLane="0" toLane="0" dir="t"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="in" from="w" to="j" type="highway.primary"><lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="turn_out" from="j" to="w" type="highway.primary"><lane id="turn_out_0" index="0" allow="passenger" shape="0,0 -10,0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="in_0" intLanes=""/>
  <connection from="in" to="turn_out" fromLane="0" toLane="0" dir="t"/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={"matched_cases": [{"reference_id": "j"}]},
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert candidate["candidate_status"] == "edge_map_incomplete"
    assert candidate["vehicle_movement_matrix_missing_count"] == 1
    assert candidate["turnaround_only_lane_gap_count"] == 1
    assert candidate["turnaround_only_lane_gaps"] == [
        {
            "teacher_from_edge_id": "in",
            "from_edge_id": "in",
            "fromLane": "0",
            "candidate_turnaround_outgoing_count": 1,
            "candidate_non_turnaround_outgoing_count": 0,
            "teacher_turnaround_outgoing_count": 1,
            "teacher_non_turnaround_outgoing_count": 1,
            "teacher_non_turnaround_targets": ["normal_out"],
            "match_status": "candidate_turnaround_only_teacher_has_normal_vehicle_movement",
        }
    ]
    assert candidate["netedit_review_actions"] == ["rebuild_vehicle_movement_matrix"]


def test_build_teacher_guided_repair_queue_allows_turnaround_only_when_teacher_only_has_turnaround(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="in" from="w" to="j"><lane id="in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="turn_out" from="j" to="w"><lane id="turn_out_0" index="0" shape="0,0 -10,0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="in_0" intLanes=""/>
  <connection from="in" to="turn_out" fromLane="0" toLane="0" dir="t"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(teacher_net.read_text(encoding="utf-8"), encoding="utf-8")

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={"matched_cases": [{"reference_id": "j"}]},
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert candidate["vehicle_movement_matrix_missing_count"] == 0
    assert candidate["turnaround_only_lane_gap_count"] == 0
    assert candidate["turnaround_only_lane_gaps"] == []


def test_build_teacher_guided_repair_queue_does_not_seed_turnaround_gap_from_different_teacher_endpoint(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="shared" from="w" to="other_j"><lane id="shared_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="normal_out" from="other_j" to="e"><lane id="normal_out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="j" type="dead_end" x="20" y="0" incLanes="" intLanes=""/>
  <junction id="other_j" type="priority" x="0" y="0" incLanes="shared_0" intLanes=""/>
  <connection from="shared" to="normal_out" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="shared" from="w" to="j"><lane id="shared_0" index="0" shape="-10,0 20,0"/></edge>
  <edge id="turn_out" from="j" to="w"><lane id="turn_out_0" index="0" shape="20,0 -10,0"/></edge>
  <junction id="j" type="priority" x="20" y="0" incLanes="shared_0" intLanes=""/>
  <connection from="shared" to="turn_out" fromLane="0" toLane="0" dir="t"/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={"matched_cases": []},
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    assert report["turnaround_only_lane_candidate_count"] == 0
    assert report["repair_candidates"] == []


def test_build_teacher_guided_repair_queue_seeds_turnaround_only_lane_gap_without_pattern_delta(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="in" from="w" to="j"><lane id="in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="normal_out" from="j" to="e"><lane id="normal_out_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="turn_out" from="j" to="w"><lane id="turn_out_0" index="0" shape="0,0 -10,0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="in_0" intLanes=""/>
  <connection from="in" to="normal_out" fromLane="0" toLane="0" dir="s"/>
  <connection from="in" to="turn_out" fromLane="0" toLane="0" dir="t"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="in" from="w" to="j"><lane id="in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="normal_out" from="j" to="e"><lane id="normal_out_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="turn_out" from="j" to="w"><lane id="turn_out_0" index="0" shape="0,0 -10,0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="in_0" intLanes=""/>
  <connection from="in" to="turn_out" fromLane="0" toLane="0" dir="t"/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={"matched_cases": []},
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    assert report["turnaround_only_lane_candidate_count"] == 1
    candidate = report["repair_candidates"][0]
    assert candidate["learned_rule"] == "tum_like_turnaround_only_lane_candidate"
    assert candidate["candidate_status"] == "ready_for_teacher_guided_variant"
    assert candidate["vehicle_movement_matrix_missing_count"] == 1
    assert candidate["turnaround_only_lane_gap_count"] == 1
    assert candidate["netedit_review_actions"] == ["rebuild_vehicle_movement_matrix"]


def test_turnaround_only_lane_seed_scopes_missing_normal_target(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="in" from="w" to="j"><lane id="in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="normal_out" from="j" to="e"><lane id="normal_out_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="turn_out" from="j" to="w"><lane id="turn_out_0" index="0" shape="0,0 -10,0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="in_0" intLanes=""/>
  <connection from="in" to="normal_out" fromLane="0" toLane="0" dir="s"/>
  <connection from="in" to="turn_out" fromLane="0" toLane="0" dir="t"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="in" from="w" to="j"><lane id="in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="turn_out" from="j" to="w"><lane id="turn_out_0" index="0" shape="0,0 -10,0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="in_0" intLanes=""/>
  <connection from="in" to="turn_out" fromLane="0" toLane="0" dir="t"/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={"matched_cases": []},
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert candidate["learned_rule"] == "tum_like_turnaround_only_lane_candidate"
    assert candidate["candidate_status"] == "needs_expanded_rebuild_scope"
    assert candidate["expanded_rebuild_scope"]["blocked_teacher_edge_ids"] == ["normal_out"]
    assert candidate["expanded_rebuild_scope"]["junction_ids"] == ["e", "j"]
    assert candidate["expanded_rebuild_scope"]["missing_desired_endpoint_ids"] == ["e"]


def test_build_teacher_guided_repair_queue_counts_duplicate_missing_teacher_movements(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0"/>
  <connection from="in" to="out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={"matched_cases": [{"reference_id": "j"}]},
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert candidate["missing_teacher_movement_plan_count"] == 1
    assert candidate["vehicle_movement_matrix_missing_count"] == 1


def test_build_teacher_guided_repair_queue_uses_same_id_pattern_delta_without_join_case(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="west_in" from="w" to="j" type="highway.primary"><lane id="west_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="south_in" from="s" to="j" type="highway.primary"><lane id="south_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="east_out" from="j" to="e" type="highway.primary"><lane id="east_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="north_out" from="j" to="n" type="highway.primary"><lane id="north_out_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="west_in_0 south_in_0" intLanes=""/>
  <connection from="west_in" to="east_out" fromLane="0" toLane="0" tl="j" linkIndex="0" dir="s"/>
  <connection from="west_in" to="north_out" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="l"/>
  <connection from="south_in" to="east_out" fromLane="0" toLane="0" tl="j" linkIndex="2" dir="r"/>
  <connection from="south_in" to="north_out" fromLane="0" toLane="0" tl="j" linkIndex="3" dir="s"/>
  <tlLogic id="j" type="actuated" programID="0"><phase duration="30" state="GGGG"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="west_in" from="w" to="j" type="highway.primary"><lane id="west_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="south_in" from="s" to="j" type="highway.primary"><lane id="south_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="east_out" from="j" to="e" type="highway.primary"><lane id="east_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="north_out" from="j" to="n" type="highway.primary"><lane id="north_out_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="west_in_0 south_in_0" intLanes=""/>
  <connection from="west_in" to="east_out" fromLane="0" toLane="0" tl="j" linkIndex="0" dir="s"/>
  <tlLogic id="j" type="actuated" programID="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [],
            "junction_pattern_comparisons": [
                {
                    "junction_id": "j",
                    "status": "fail",
                    "mismatch_fields": ["movement_signature_counts", "has_tls"],
                    "teacher": {"has_tls": True},
                    "candidate": {"has_tls": True},
                }
            ],
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    assert report["repair_candidate_count"] == 1
    assert report["same_id_pattern_candidate_count"] == 1
    candidate = report["repair_candidates"][0]
    assert candidate["reference_id"] == "j"
    assert candidate["junction_id"] == "j"
    assert candidate["learned_rule"] == "tum_like_same_id_pattern_candidate"
    assert candidate["candidate_status"] == "ready_for_teacher_guided_variant"
    assert candidate["vehicle_movement_matrix_missing_count"] == 3
    assert candidate["junction_pattern_mismatch_fields"] == ["movement_signature_counts", "has_tls"]
    assert candidate["netedit_review_actions"] == ["rebuild_vehicle_movement_matrix", "inspect_tls_control"]


def test_build_teacher_guided_repair_queue_seeds_same_id_tls_mismatch_without_pattern_delta(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="west_in" from="w" to="j" type="highway.primary"><lane id="west_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="south_in" from="s" to="j" type="highway.primary"><lane id="south_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="east_out" from="j" to="e" type="highway.primary"><lane id="east_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="north_out" from="j" to="n" type="highway.primary"><lane id="north_out_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="west_in_0 south_in_0" intLanes=""/>
  <connection from="west_in" to="east_out" fromLane="0" toLane="0" tl="j" linkIndex="0" dir="s"/>
  <connection from="west_in" to="north_out" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="l"/>
  <connection from="south_in" to="east_out" fromLane="0" toLane="0" tl="j" linkIndex="2" dir="r"/>
  <connection from="south_in" to="north_out" fromLane="0" toLane="0" tl="j" linkIndex="3" dir="s"/>
  <tlLogic id="j" type="actuated" programID="0"><phase duration="30" state="GGGG"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="west_in" from="w" to="j" type="highway.primary"><lane id="west_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="south_in" from="s" to="j" type="highway.primary"><lane id="south_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="east_out" from="j" to="e" type="highway.primary"><lane id="east_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="north_out" from="j" to="n" type="highway.primary"><lane id="north_out_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <junction id="j" type="right_before_left" x="0" y="0" incLanes="west_in_0 south_in_0" intLanes=""/>
  <connection from="west_in" to="east_out" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={"matched_cases": []},
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    assert report["same_id_tls_candidate_count"] == 1
    candidate = report["repair_candidates"][0]
    assert candidate["reference_id"] == "j"
    assert candidate["junction_id"] == "j"
    assert candidate["learned_rule"] == "tum_like_same_id_tls_candidate"
    assert candidate["candidate_status"] == "ready_for_teacher_guided_variant"
    assert candidate["vehicle_movement_matrix_missing_count"] == 3
    assert candidate["netedit_review_actions"] == ["rebuild_vehicle_movement_matrix"]


def test_build_teacher_guided_repair_queue_seeds_fragmented_tls_from_exact_approach_edges(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="west_in" from="w" to="teacher_tls" type="highway.primary"><lane id="west_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="north_in" from="n" to="teacher_tls" type="highway.primary"><lane id="north_in_0" index="0" allow="passenger" shape="0,10 0,0"/></edge>
  <edge id="east_out" from="teacher_tls" to="e" type="highway.primary"><lane id="east_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="south_out" from="teacher_tls" to="s" type="highway.primary"><lane id="south_out_0" index="0" allow="passenger" shape="0,0 0,-10"/></edge>
  <junction id="teacher_tls" type="traffic_light" x="0" y="0" incLanes="west_in_0 north_in_0" intLanes=""/>
  <connection from="west_in" to="east_out" fromLane="0" toLane="0" tl="teacher_tls" linkIndex="0" dir="s"/>
  <connection from="north_in" to="south_out" fromLane="0" toLane="0" tl="teacher_tls" linkIndex="1" dir="s"/>
  <tlLogic id="teacher_tls" type="actuated" programID="0">
    <phase duration="30" state="GG"/>
    <phase duration="5" state="yy"/>
  </tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="west_in" from="w" to="frag_w" type="highway.primary"><lane id="west_in_0" index="0" allow="passenger" shape="-10,0 -1,0"/></edge>
  <edge id="north_in" from="n" to="frag_n" type="highway.primary"><lane id="north_in_0" index="0" allow="passenger" shape="0,10 0,1"/></edge>
  <edge id="east_out" from="frag_e" to="e" type="highway.primary"><lane id="east_out_0" index="0" allow="passenger" shape="1,0 10,0"/></edge>
  <edge id="south_out" from="frag_s" to="s" type="highway.primary"><lane id="south_out_0" index="0" allow="passenger" shape="0,-1 0,-10"/></edge>
  <junction id="frag_w" type="priority" x="-1" y="0" incLanes="west_in_0" intLanes=""/>
  <junction id="frag_n" type="priority" x="0" y="1" incLanes="north_in_0" intLanes=""/>
  <junction id="frag_e" type="priority" x="1" y="0" incLanes="" intLanes=""/>
  <junction id="frag_s" type="priority" x="0" y="-1" incLanes="" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={"matched_cases": []},
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    assert report["topology_fragmented_tls_candidate_count"] == 1
    candidate = report["repair_candidates"][0]
    assert candidate["reference_id"] == "teacher_tls"
    assert candidate["candidate_status"] == "needs_expanded_rebuild_scope"
    assert candidate["learned_rule"] == "tum_like_topology_fragmented_tls_candidate"
    assert candidate["edge_map"] == {
        "east_out": "east_out",
        "north_in": "north_in",
        "south_out": "south_out",
        "west_in": "west_in",
    }
    assert candidate["missing_teacher_edge_ids"] == []
    assert candidate["matched_candidate_node_ids"] == ["frag_e", "frag_n", "frag_s", "frag_w"]
    assert candidate["expanded_rebuild_scope"]["junction_ids"] == ["frag_e", "frag_n", "frag_s", "frag_w"]
    assert candidate["expanded_rebuild_scope"]["join_junction_ids"] == ["frag_e", "frag_n", "frag_s", "frag_w"]


def test_build_teacher_guided_repair_queue_seeds_fragmented_tls_from_unsplit_candidate_approach_edges(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="32999434#0" from="outer" to="teacher_tls" type="highway.secondary"><lane id="32999434#0_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="-32999434#0" from="teacher_tls" to="outer" type="highway.secondary"><lane id="-32999434#0_0" index="0" allow="passenger" shape="0,0 -10,0"/></edge>
  <edge id="side_in" from="side" to="teacher_tls" type="highway.secondary"><lane id="side_in_0" index="0" allow="passenger" shape="0,10 0,0"/></edge>
  <edge id="side_out" from="teacher_tls" to="side" type="highway.secondary"><lane id="side_out_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <edge id=":teacher_tls_0" function="internal"><lane id=":teacher_tls_0_0" index="0" shape="0,0 0,1"/></edge>
  <edge id=":teacher_tls_1" function="internal"><lane id=":teacher_tls_1_0" index="0" shape="0,0 1,0"/></edge>
  <junction id="teacher_tls" type="traffic_light" x="0" y="0" incLanes="32999434#0_0 side_in_0" intLanes=":teacher_tls_0_0 :teacher_tls_1_0"/>
  <connection from="32999434#0" to="side_out" via=":teacher_tls_0_0" fromLane="0" toLane="0" tl="teacher_tls" linkIndex="0" dir="r"/>
  <connection from="side_in" to="-32999434#0" via=":teacher_tls_1_0" fromLane="0" toLane="0" tl="teacher_tls" linkIndex="1" dir="l"/>
  <tlLogic id="teacher_tls" type="actuated" programID="0"><phase duration="30" state="GG"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="32999434" from="outer" to="98101394" type="highway.secondary"><lane id="32999434_0" index="0" allow="passenger" shape="-10,0 -1,0"/></edge>
  <edge id="-32999434" from="98101394" to="outer" type="highway.secondary"><lane id="-32999434_0" index="0" allow="passenger" shape="-1,0 -10,0"/></edge>
  <edge id="side_in" from="side" to="frag_side" type="highway.secondary"><lane id="side_in_0" index="0" allow="passenger" shape="0,10 0,1"/></edge>
  <edge id="side_out" from="frag_side" to="side" type="highway.secondary"><lane id="side_out_0" index="0" allow="passenger" shape="0,1 0,10"/></edge>
  <junction id="98101394" type="priority" x="-1" y="0" incLanes="32999434_0" intLanes=""/>
  <junction id="frag_side" type="priority" x="0" y="1" incLanes="side_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={"matched_cases": []},
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    assert report["topology_fragmented_tls_candidate_count"] == 1
    candidate = report["repair_candidates"][0]
    assert candidate["reference_id"] == "teacher_tls"
    assert candidate["learned_rule"] == "tum_like_topology_fragmented_tls_candidate"
    assert candidate["edge_map"] == {
        "-32999434#0": "-32999434",
        "32999434#0": "32999434",
        "side_in": "side_in",
        "side_out": "side_out",
    }
    assert candidate["matched_candidate_node_ids"] == ["98101394", "frag_side"]


def test_build_teacher_guided_repair_queue_seeds_fragmented_non_tls_cluster_from_exact_approach_edges(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="west_in" from="w" to="cluster_frag_a_frag_b" type="highway.primary"><lane id="west_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="north_in" from="n" to="cluster_frag_a_frag_b" type="highway.primary"><lane id="north_in_0" index="0" allow="passenger" shape="0,10 0,0"/></edge>
  <edge id="east_out" from="cluster_frag_a_frag_b" to="e" type="highway.primary"><lane id="east_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="south_out" from="cluster_frag_a_frag_b" to="s" type="highway.primary"><lane id="south_out_0" index="0" allow="passenger" shape="0,0 0,-10"/></edge>
  <junction id="cluster_frag_a_frag_b" type="right_before_left" x="0" y="0" incLanes="west_in_0 north_in_0" intLanes=""/>
  <connection from="west_in" to="east_out" fromLane="0" toLane="0" dir="s"/>
  <connection from="north_in" to="south_out" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="west_in" from="w" to="frag_w" type="highway.primary"><lane id="west_in_0" index="0" allow="passenger" shape="-10,0 -1,0"/></edge>
  <edge id="north_in" from="n" to="frag_n" type="highway.primary"><lane id="north_in_0" index="0" allow="passenger" shape="0,10 0,1"/></edge>
  <edge id="east_out" from="frag_e" to="e" type="highway.primary"><lane id="east_out_0" index="0" allow="passenger" shape="1,0 10,0"/></edge>
  <edge id="south_out" from="frag_s" to="s" type="highway.primary"><lane id="south_out_0" index="0" allow="passenger" shape="0,-1 0,-10"/></edge>
  <junction id="frag_w" type="priority" x="-1" y="0" incLanes="west_in_0" intLanes=""/>
  <junction id="frag_n" type="priority" x="0" y="1" incLanes="north_in_0" intLanes=""/>
  <junction id="frag_e" type="priority" x="1" y="0" incLanes="" intLanes=""/>
  <junction id="frag_s" type="priority" x="0" y="-1" incLanes="" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={"matched_cases": []},
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    assert report["topology_fragmented_non_tls_candidate_count"] == 1
    candidate = report["repair_candidates"][0]
    assert candidate["reference_id"] == "cluster_frag_a_frag_b"
    assert candidate["candidate_status"] == "needs_expanded_rebuild_scope"
    assert candidate["learned_rule"] == "tum_like_topology_fragmented_cluster_candidate"
    assert candidate["edge_map"] == {
        "east_out": "east_out",
        "north_in": "north_in",
        "south_out": "south_out",
        "west_in": "west_in",
    }
    assert candidate["matched_candidate_node_ids"] == ["frag_e", "frag_n", "frag_s", "frag_w"]
    assert candidate["expanded_rebuild_scope"]["join_junction_ids"] == ["frag_e", "frag_n", "frag_s", "frag_w"]


def test_joined_endpoint_edge_file_keeps_join_source_endpoints_for_join_patch(tmp_path: Path) -> None:
    edge_file = tmp_path / "scope.edg.xml"
    edge_file.write_text(
        """<edges>
  <edge id="in" from="outside" to="frag_a" shape="0,0 10,0"/>
  <edge id="out" from="frag_b" to="outside" shape="10,0 20,0"/>
  <edge id="inside" from="frag_a" to="frag_b" shape="10,0 11,0"/>
</edges>""",
        encoding="utf-8",
    )
    join_file = tmp_path / "join.nod.xml"
    join_file.write_text('<nodes><join nodes="frag_a frag_b"/></nodes>', encoding="utf-8")
    output_file = tmp_path / "replay.edg.xml"

    written_file, rewrite_count, dropped_self_loops, blocking_self_loops = _write_joined_endpoint_edge_file(
        edge_file,
        join_file,
        "cluster_frag_a_frag_b",
        output_file,
    )

    root = ET.parse(written_file).getroot()
    assert rewrite_count == 0
    assert dropped_self_loops == ["inside"]
    assert blocking_self_loops == []
    assert root.find("edge[@id='inside']") is None
    assert root.find("edge[@id='in']").attrib == {"id": "in", "from": "outside", "to": "frag_a", "shape": "0,0 10,0"}
    assert root.find("edge[@id='out']").attrib == {"id": "out", "from": "frag_b", "to": "outside", "shape": "10,0 20,0"}


def test_build_teacher_guided_repair_queue_marks_copyable_missing_boundary_edge_ready(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_a_b"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_missing" from="cluster_a_b" to="p"><lane id="teacher_missing_0" index="0" shape="0,0 10,0"/></edge>
  <edge id=":cluster_a_b_0" function="internal"><lane id=":cluster_a_b_0_0" index="0" shape="0,0 1,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=":cluster_a_b_0_0"/>
  <connection from="teacher_in" to="teacher_missing" via=":cluster_a_b_0_0" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="cluster_a_b"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [{"reference_id": "cluster_a_b", "learned_rule": "tum_like_join_candidate"}]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert report["ready_candidate_count"] == 1
    assert candidate["candidate_status"] == "ready_for_teacher_guided_variant"
    assert candidate["missing_teacher_edge_ids"] == ["teacher_missing"]
    assert candidate["copyable_missing_teacher_edge_ids"] == ["teacher_missing"]
    assert candidate["uncopyable_missing_teacher_edge_ids"] == []


def test_build_teacher_guided_repair_queue_scopes_endpoint_mismatched_approach_copyable(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_a_b"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_a_b" to="e"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <edge id=":cluster_a_b_0" function="internal"><lane id=":cluster_a_b_0_0" index="0" shape="0,0 1,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=":cluster_a_b_0_0"/>
  <connection from="teacher_in" to="teacher_out" via=":cluster_a_b_0_0" fromLane="0" toLane="0" tl="cluster_a_b"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="cluster_a_b"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="cand_short" from="cluster_a_b" to="c"><lane id="cand_short_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [{"reference_id": "cluster_a_b", "learned_rule": "tum_like_join_candidate"}]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert report["ready_candidate_count"] == 0
    assert report["expanded_scope_candidate_count"] == 1
    assert candidate["candidate_status"] == "needs_expanded_rebuild_scope"
    assert candidate["edge_map"] == {"teacher_in": "cand_in"}
    assert candidate["missing_teacher_edge_ids"] == ["teacher_out"]
    assert candidate["copyable_missing_teacher_edge_ids"] == ["teacher_out"]
    assert candidate["uncopyable_missing_teacher_edge_ids"] == []
    assert candidate["approach_endpoint_rebuild_plan"]["mismatch_count"] == 1
    assert candidate["approach_endpoint_rebuild_plan"]["affected_neighbor_junction_ids"] == ["c", "e"]
    assert candidate["expanded_rebuild_scope"] == {
        "status": "review",
        "recommended_action": "rebuild_plain_xml_scope",
        "core_junction_id": "cluster_a_b",
        "junction_ids": ["c", "cluster_a_b", "e"],
        "join_junction_ids": ["cluster_a_b"],
        "blocked_teacher_edge_ids": [],
        "missing_desired_endpoint_ids": ["e"],
        "reason": "approach endpoints differ; rebuild expanded scope before teacher movement replay",
    }


def test_build_teacher_guided_repair_queue_scopes_missing_joined_candidate_junction(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_j1_j2"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_j1_j2" to="b"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="cluster_j1_j2" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j1"><lane id="cand_in_0" index="0" shape="-10,0 -1,0"/></edge>
  <edge id="cand_mid" from="j1" to="j2"><lane id="cand_mid_0" index="0" shape="-1,0 1,0"/></edge>
  <edge id="cand_out" from="j2" to="b"><lane id="cand_out_0" index="0" shape="1,0 10,0"/></edge>
  <junction id="j1" type="priority" x="-1" y="0" incLanes="cand_in_0" intLanes=""/>
  <junction id="j2" type="priority" x="1" y="0" incLanes="cand_mid_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": "cluster_j1_j2",
                    "matched_candidate_node_ids": ["j1", "j2", "support_node"],
                    "matched_reference_source_node_ids": ["j1", "j2"],
                    "learned_rule": "tum_like_join_candidate",
                }
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert report["ready_candidate_count"] == 0
    assert report["expanded_scope_candidate_count"] == 1
    assert report["blocked_candidate_count"] == 0
    assert candidate["candidate_status"] == "needs_expanded_rebuild_scope"
    assert candidate["edge_map"] == {}
    assert candidate["missing_teacher_edge_ids"] == ["teacher_in", "teacher_out"]
    assert candidate["expanded_rebuild_scope"] == {
        "status": "review",
        "recommended_action": "rebuild_plain_xml_scope",
        "core_junction_id": "cluster_j1_j2",
        "junction_ids": ["j1", "j2"],
        "join_junction_ids": ["j1", "j2"],
        "blocked_teacher_edge_ids": ["teacher_in", "teacher_out"],
        "missing_desired_endpoint_ids": [],
        "reason": "candidate joined junction not found; rebuild from matched candidate source nodes",
    }


def test_build_teacher_guided_repair_queue_uses_conservative_join_subset_for_single_source_match(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_j"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_j" to="b"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="cluster_j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <junction id="first" type="priority" x="0" y="0" incLanes="" intLanes=""/>
  <junction id="matched" type="priority" x="1" y="0" incLanes="" intLanes=""/>
  <junction id="extra" type="priority" x="2" y="0" incLanes="" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": "cluster_j",
                    "matched_candidate_node_ids": ["first", "matched", "extra"],
                    "matched_reference_source_node_ids": ["matched"],
                    "learned_rule": "tum_like_join_candidate",
                }
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    scope = report["repair_candidates"][0]["expanded_rebuild_scope"]
    assert scope["junction_ids"] == ["extra", "first", "matched"]
    assert scope["join_junction_ids"] == ["first", "matched"]


def test_build_teacher_guided_repair_queue_uses_first_pair_when_no_source_match(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_j"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_j" to="b"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="cluster_j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <junction id="a1" type="priority" x="0" y="0" incLanes="" intLanes=""/>
  <junction id="a2" type="priority" x="1" y="0" incLanes="" intLanes=""/>
  <junction id="a3" type="priority" x="2" y="0" incLanes="" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": "cluster_j",
                    "matched_candidate_node_ids": ["a1", "a2", "a3"],
                    "matched_reference_source_node_ids": ["missing_ref_node"],
                    "learned_rule": "tum_like_join_candidate",
                }
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    scope = report["repair_candidates"][0]["expanded_rebuild_scope"]
    assert scope["junction_ids"] == ["a1", "a2", "a3"]
    assert scope["join_junction_ids"] == ["a1", "a2"]


def test_build_teacher_guided_repair_queue_marks_no_vehicle_reference_context(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="ped_in" from="p" to="cluster_p_j" type="highway.footway"><lane id="ped_in_0" index="0" allow="pedestrian" shape="-10,0 0,0"/></edge>
  <edge id=":cluster_p_j_w0" function="walkingarea"><lane id=":cluster_p_j_w0_0" index="0" allow="pedestrian" shape="0,0 1,0"/></edge>
  <junction id="cluster_p_j" type="dead_end" x="0" y="0" incLanes="ped_in_0" intLanes=""/>
  <connection from="ped_in" to=":cluster_p_j_w0" fromLane="0" toLane="0" dir="s" state="M"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <junction id="j1" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": "cluster_p_j",
                    "matched_candidate_node_ids": ["j1"],
                    "learned_rule": "tum_like_join_candidate",
                }
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert report["ready_candidate_count"] == 0
    assert report["expanded_scope_candidate_count"] == 0
    assert report["blocked_candidate_count"] == 1
    assert candidate["candidate_status"] == "no_vehicle_reference_context"
    assert candidate["missing_teacher_edge_ids"] == []
    assert candidate["pedestrian_connection_count"] == 1


def test_build_teacher_guided_repair_queue_marks_existing_endpoint_mismatch_as_expanded_scope(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_a_b"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_a_b" to="e"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <edge id=":cluster_a_b_0" function="internal"><lane id=":cluster_a_b_0_0" index="0" shape="0,0 1,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=":cluster_a_b_0_0"/>
  <connection from="teacher_in" to="teacher_out" via=":cluster_a_b_0_0" fromLane="0" toLane="0" tl="cluster_a_b"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="cluster_a_b"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_a_b" to="c"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
  <junction id="c" type="priority" x="10" y="0" incLanes="teacher_out_0" intLanes=""/>
  <junction id="e" type="priority" x="12" y="0" incLanes="" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [{"reference_id": "cluster_a_b", "learned_rule": "tum_like_join_candidate"}]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert report["ready_candidate_count"] == 0
    assert report["expanded_scope_candidate_count"] == 1
    assert report["blocked_candidate_count"] == 0
    assert candidate["candidate_status"] == "needs_expanded_rebuild_scope"
    assert candidate["edge_map"] == {"teacher_in": "cand_in"}
    assert candidate["missing_teacher_edge_ids"] == ["teacher_out"]
    assert candidate["copyable_missing_teacher_edge_ids"] == []
    assert candidate["uncopyable_missing_teacher_edge_ids"] == ["teacher_out"]
    assert candidate["expanded_rebuild_scope"] == {
        "status": "review",
        "recommended_action": "rebuild_plain_xml_scope",
        "core_junction_id": "cluster_a_b",
        "junction_ids": ["c", "cluster_a_b", "e"],
        "join_junction_ids": ["cluster_a_b"],
        "blocked_teacher_edge_ids": ["teacher_out"],
        "missing_desired_endpoint_ids": [],
        "reason": "approach endpoints differ and at least one missing teacher edge cannot be copied safely",
    }


def test_build_teacher_guided_repair_queue_scopes_uncopyable_missing_edge_without_endpoint_mismatch(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_a_b"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_a_b" to="e"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="cluster_a_b"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": "cluster_a_b",
                    "matched_reference_source_node_ids": ["a", "b"],
                    "matched_candidate_node_ids": ["a", "b"],
                    "learned_rule": "tum_like_join_candidate",
                }
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert report["ready_candidate_count"] == 0
    assert report["expanded_scope_candidate_count"] == 1
    assert report["blocked_candidate_count"] == 0
    assert candidate["candidate_status"] == "needs_expanded_rebuild_scope"
    assert candidate["edge_map"] == {"teacher_in": "cand_in"}
    assert candidate["missing_teacher_edge_ids"] == ["teacher_out"]
    assert candidate["copyable_missing_teacher_edge_ids"] == []
    assert candidate["uncopyable_missing_teacher_edge_ids"] == ["teacher_out"]
    assert candidate["expanded_rebuild_scope"] == {
        "status": "review",
        "recommended_action": "rebuild_plain_xml_scope",
        "core_junction_id": "cluster_a_b",
        "junction_ids": ["a", "b"],
        "join_junction_ids": ["a", "b"],
        "blocked_teacher_edge_ids": ["teacher_out"],
        "missing_desired_endpoint_ids": [],
        "reason": "missing teacher approach edge cannot be copied safely; rebuild from matched candidate source nodes",
    }


def test_build_teacher_guided_repair_queue_limits_ready_candidates(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_a_b" type="highway.primary"><lane id="teacher_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_a_b" to="b" type="highway.primary"><lane id="teacher_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="traffic_light" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="cluster_a_b" linkIndex="0" dir="s"/>
  <tlLogic id="cluster_a_b" type="actuated" programID="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="cluster_a_b" type="highway.primary"><lane id="cand_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="cluster_a_b" to="b" type="highway.primary"><lane id="cand_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="traffic_light" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": "cluster_a_b",
                    "matched_candidate_node_ids": ["a", "b", "c"],
                    "learned_rule": "tum_like_join_candidate",
                },
                {
                    "reference_id": "cluster_a_b",
                    "matched_candidate_node_ids": ["a"],
                    "learned_rule": "tum_like_join_candidate",
                },
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
        max_ready_candidates=1,
    )

    assert report["matched_case_count"] == 2
    assert report["queued_case_count"] == 1
    assert report["queue_truncated"] is True
    assert (
        report["queue_order_policy"]
        == "ready_then_same_id_tls_low_gap_then_largest_vehicle_movement_gap_then_highest_teacher_template_count"
    )
    assert report["ready_candidate_count"] == 1
    assert report["max_ready_candidates"] == 1
    assert report["repair_candidates"][0]["matched_candidate_node_ids"] == ["a"]


def test_limit_ready_repair_candidates_prioritizes_ready_candidates() -> None:
    candidates = [
        {"junction_id": "wide_1", "candidate_status": "needs_expanded_rebuild_scope"},
        {"junction_id": "ready_1", "candidate_status": "ready_for_teacher_guided_variant"},
        {"junction_id": "wide_2", "candidate_status": "needs_expanded_rebuild_scope"},
        {"junction_id": "ready_2", "candidate_status": "ready_for_teacher_guided_variant"},
    ]

    selected = _limit_ready_repair_candidates(candidates, 2)

    assert [candidate["junction_id"] for candidate in selected] == ["ready_1", "ready_2"]


def test_teacher_guided_candidate_sort_key_prioritizes_same_id_tls_semantics() -> None:
    candidates = [
        {
            "junction_id": "expanded_pattern",
            "candidate_status": "needs_expanded_rebuild_scope",
            "learned_rule": "tum_like_same_id_pattern_candidate",
            "vehicle_movement_matrix_missing_count": 10,
        },
        {
            "junction_id": "same_id_tls_gap",
            "candidate_status": "needs_expanded_rebuild_scope",
            "learned_rule": "tum_like_same_id_tls_candidate",
            "vehicle_movement_matrix_missing_count": 2,
        },
        {
            "junction_id": "same_id_tls",
            "candidate_status": "needs_expanded_rebuild_scope",
            "learned_rule": "tum_like_same_id_tls_candidate",
            "vehicle_movement_matrix_missing_count": 0,
        },
    ]

    assert sorted(candidates, key=_teacher_guided_candidate_sort_key)[0]["junction_id"] == "same_id_tls"


def test_build_teacher_guided_repair_queue_prioritizes_reusable_teacher_templates(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="low_in" from="a" to="cluster_a_low"><lane id="low_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="low_out" from="cluster_a_low" to="b"><lane id="low_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="high_in" from="c" to="cluster_z_high"><lane id="high_in_0" index="0" allow="passenger" shape="-10,10 0,10"/></edge>
  <edge id="high_out" from="cluster_z_high" to="d"><lane id="high_out_0" index="0" allow="passenger" shape="0,10 10,10"/></edge>
  <junction id="cluster_a_low" type="priority" x="0" y="0" incLanes="low_in_0" intLanes=""/>
  <junction id="cluster_z_high" type="priority" x="0" y="10" incLanes="high_in_0" intLanes=""/>
  <connection from="low_in" to="low_out" fromLane="0" toLane="0" dir="s"/>
  <connection from="high_in" to="high_out" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(teacher_net.read_text(encoding="utf-8"), encoding="utf-8")

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {"reference_id": "cluster_a_low", "learned_rule": "tum_like_join_candidate"},
                {"reference_id": "cluster_z_high", "learned_rule": "tum_like_join_candidate"},
            ],
            "junction_pattern_index": [
                {"junction_id": "cluster_a_low", "pattern_key": "low_template"},
                {"junction_id": "cluster_z_high", "pattern_key": "high_template"},
            ],
            "junction_pattern_templates": [
                {"pattern_key": "low_template", "pattern_family": "one_arm", "count": 1},
                {
                    "pattern_key": "high_template",
                    "pattern_family": "one_arm",
                    "count": 127,
                    "example_junction_ids": ["cluster_z_high"],
                },
            ],
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
        max_ready_candidates=1,
    )

    candidate = report["repair_candidates"][0]
    assert (
        report["queue_order_policy"]
        == "ready_then_same_id_tls_low_gap_then_largest_vehicle_movement_gap_then_highest_teacher_template_count"
    )
    assert candidate["reference_id"] == "cluster_z_high"
    assert candidate["teacher_pattern_key"] == "high_template"
    assert candidate["teacher_pattern_template_count"] == 127
    rows = list(csv.DictReader(Path(report["queue_csv_file"]).read_text(encoding="utf-8").splitlines()))
    assert rows[0]["teacher_pattern_template_count"] == "127"
    assert rows[0]["teacher_pattern_key"] == "high_template"


def test_build_teacher_guided_repair_queue_prioritizes_movement_gap_when_limited(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="low_in" from="a" to="cluster_a_low"><lane id="low_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="low_out" from="cluster_a_low" to="b"><lane id="low_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_low" type="priority" x="0" y="0" incLanes="low_in_0" intLanes=""/>
  <connection from="low_in" to="low_out" fromLane="0" toLane="0"/>
  <edge id="high_w_in" from="w" to="cluster_z_high"><lane id="high_w_in_0" index="0" allow="passenger" shape="-10,10 0,10"/></edge>
  <edge id="high_s_in" from="s" to="cluster_z_high"><lane id="high_s_in_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <edge id="high_e_out" from="cluster_z_high" to="e"><lane id="high_e_out_0" index="0" allow="passenger" shape="0,10 10,10"/></edge>
  <edge id="high_n_out" from="cluster_z_high" to="n"><lane id="high_n_out_0" index="0" allow="passenger" shape="0,10 0,20"/></edge>
  <junction id="cluster_z_high" type="priority" x="0" y="10" incLanes="high_w_in_0 high_s_in_0" intLanes=""/>
  <connection from="high_w_in" to="high_e_out" fromLane="0" toLane="0"/>
  <connection from="high_w_in" to="high_n_out" fromLane="0" toLane="0"/>
  <connection from="high_s_in" to="high_e_out" fromLane="0" toLane="0"/>
  <connection from="high_s_in" to="high_n_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="low_in" from="a" to="cluster_a_low"><lane id="low_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="low_out" from="cluster_a_low" to="b"><lane id="low_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_low" type="priority" x="0" y="0" incLanes="low_in_0" intLanes=""/>
  <connection from="low_in" to="low_out" fromLane="0" toLane="0"/>
  <edge id="high_w_in" from="w" to="cluster_z_high"><lane id="high_w_in_0" index="0" allow="passenger" shape="-10,10 0,10"/></edge>
  <edge id="high_s_in" from="s" to="cluster_z_high"><lane id="high_s_in_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <edge id="high_e_out" from="cluster_z_high" to="e"><lane id="high_e_out_0" index="0" allow="passenger" shape="0,10 10,10"/></edge>
  <edge id="high_n_out" from="cluster_z_high" to="n"><lane id="high_n_out_0" index="0" allow="passenger" shape="0,10 0,20"/></edge>
  <junction id="cluster_z_high" type="priority" x="0" y="10" incLanes="high_w_in_0 high_s_in_0" intLanes=""/>
  <connection from="high_w_in" to="high_e_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {"reference_id": "cluster_a_low", "learned_rule": "tum_like_join_candidate"},
                {"reference_id": "cluster_z_high", "learned_rule": "tum_like_join_candidate"},
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
        max_ready_candidates=1,
    )

    assert report["queued_case_count"] == 1
    assert report["repair_candidates"][0]["reference_id"] == "cluster_z_high"
    assert report["repair_candidates"][0]["vehicle_movement_matrix_missing_count"] == 3


def test_build_teacher_guided_repair_queue_resolves_sumo_short_joined_candidate_id(tmp_path: Path) -> None:
    reference_id = "cluster_a_b_c_d_e_f"
    candidate_id = "cluster_a_b_c_d_#2more"
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        f"""<net>
  <edge id="teacher_in" from="w" to="{reference_id}" type="highway.primary"><lane id="teacher_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="{reference_id}" to="e" type="highway.primary"><lane id="teacher_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="{reference_id}" type="traffic_light" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="{reference_id}" linkIndex="0" dir="s"/>
  <tlLogic id="{reference_id}" type="actuated" programID="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        f"""<net>
  <edge id="cand_in" from="w" to="{candidate_id}" type="highway.primary"><lane id="cand_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="{candidate_id}" to="e" type="highway.primary"><lane id="cand_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="{candidate_id}" type="traffic_light" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_guided_repair_queue(
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        reference_join_audit_report={
            "matched_cases": [
                {
                    "reference_id": reference_id,
                    "matched_candidate_node_ids": ["f", "e", "d", "c", "b", "a"],
                    "learned_rule": "tum_like_join_candidate",
                }
            ]
        },
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    candidate = report["repair_candidates"][0]
    assert report["ready_candidate_count"] == 1
    assert candidate["reference_id"] == reference_id
    assert candidate["junction_id"] == candidate_id
    assert candidate["edge_map"] == {"teacher_in": "cand_in", "teacher_out": "cand_out"}


def test_teacher_guided_repair_queue_uses_real_reference_join_case_after_joined_candidate(tmp_path: Path) -> None:
    reference_net = tmp_path / "reference.net.xml"
    reference_net.write_text(
        """<net>
  <edge id="teacher_in" from="w" to="cluster_a_b" type="highway.primary"><lane id="teacher_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="cluster_a_b" to="e" type="highway.primary"><lane id="teacher_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="traffic_light" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="cluster_a_b" linkIndex="0" dir="s"/>
  <tlLogic id="cluster_a_b" type="actuated" programID="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    pre_join_candidate = tmp_path / "pre_join.net.xml"
    pre_join_candidate.write_text(
        """<net>
  <edge id="ab" from="a" to="b" type="highway.residential"><lane id="ab_0" index="0" length="5" shape="-1,0 1,0"/></edge>
  <junction id="a" x="-1" y="0" type="traffic_light"/>
  <junction id="b" x="1" y="0" type="traffic_light"/>
</net>""",
        encoding="utf-8",
    )
    joined_candidate = tmp_path / "joined_candidate.net.xml"
    joined_candidate.write_text(
        """<net>
  <edge id="cand_in" from="w" to="cluster_a_b" type="highway.primary"><lane id="cand_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="cluster_a_b" to="e" type="highway.primary"><lane id="cand_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="cluster_a_b" type="traffic_light" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    reference_join = audit_reference_join_patterns(
        reference_net_file=reference_net,
        candidate_net_file=pre_join_candidate,
        output_dir=tmp_path / "reference_join",
        candidate_cluster_radius_m=5,
        candidate_min_cluster_nodes=2,
    )
    queue = build_teacher_guided_repair_queue(
        teacher_net_file=reference_net,
        candidate_net_file=joined_candidate,
        reference_join_audit_report=reference_join,
        output_dir=tmp_path / "queue",
        prefix="demo",
    )

    assert reference_join["matched_case_count"] == 1
    assert reference_join["matched_cases"][0]["learned_rule"] == "tum_like_join_candidate"
    assert queue["ready_candidate_count"] == 1
    assert queue["repair_candidates"][0]["edge_map"] == {"teacher_in": "cand_in", "teacher_out": "cand_out"}


def test_run_teacher_guided_repair_queue_executes_ready_candidates(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    raw_tllogics = tmp_path / "raw.tll.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, raw_tllogics, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")
    calls = []

    def fake_variant(**kwargs):
        calls.append(kwargs)
        variant_report = kwargs["output_dir"] / "variant_report.json"
        variant_report.parent.mkdir(parents=True, exist_ok=True)
        variant_report.write_text('{"status": "pass"}', encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "final_net_file": str(kwargs["output_dir"] / "final.net.xml"),
            "parity_gate_status": "pass",
            "report_file": str(variant_report),
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "cluster_a_b",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                    "teacher_pattern_key": "three_way|control=right_before_left",
                    "teacher_pattern_family": "three_way",
                    "teacher_pattern_template_count": 127,
                    "teacher_pattern_template_examples": ["cluster_template_1"],
                    "missing_teacher_edge_ids": ["teacher_copyable"],
                    "copyable_missing_teacher_edge_ids": ["teacher_copyable"],
                    "uncopyable_missing_teacher_edge_ids": [],
                },
                {
                    "junction_id": "cluster_c_d",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                },
                {"junction_id": "cluster_c_d", "candidate_status": "needs_joined_candidate_junction", "edge_map": {}},
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        max_ready_candidates=1,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert report["attempted_candidate_count"] == 1
    assert report["skipped_candidate_count"] == 2
    assert report["max_ready_candidates"] == 1
    assert calls[0]["junction_id"] == "cluster_a_b"
    assert calls[0]["teacher_junction_id"] == "cluster_a_b"
    assert report["variant_reports"][0]["teacher_pattern_key"] == "three_way|control=right_before_left"
    assert report["variant_reports"][0]["teacher_pattern_family"] == "three_way"
    assert report["variant_reports"][0]["teacher_pattern_template_count"] == 127
    assert report["variant_reports"][0]["teacher_pattern_template_examples"] == ["cluster_template_1"]
    assert report["teacher_pattern_contexts"] == [
        {
            "teacher_pattern_key": "three_way|control=right_before_left",
            "teacher_pattern_family": "three_way",
            "teacher_pattern_template_count": 127,
            "teacher_pattern_template_examples": ["cluster_template_1"],
        }
    ]
    variant_report = json.loads(Path(report["variant_reports"][0]["report_file"]).read_text(encoding="utf-8"))
    assert variant_report["teacher_pattern_key"] == "three_way|control=right_before_left"
    assert variant_report["teacher_pattern_template_count"] == 127


def test_run_teacher_guided_repair_queue_replays_same_id_internal_mismatch_candidate(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")
    variant_calls = []

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "same_id_j",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "learned_rule": "tum_like_same_id_pattern_candidate",
                    "junction_pattern_mismatch_fields": ["internal_function_counts", "movement_signature_counts"],
                    "edge_map": {"teacher_in": "cand_in"},
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert variant_calls[0]["replay_target_internal_subgraph"] is True


def test_run_teacher_guided_repair_queue_sequentially_reuses_passed_variant_plain_export(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    raw_tllogics = tmp_path / "raw.tll.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, raw_tllogics, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")
    variant_calls = []
    export_calls = []

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        final_net = kwargs["output_dir"] / "final.net.xml"
        final_net.parent.mkdir(parents=True, exist_ok=True)
        final_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "final_net_file": str(final_net),
            "parity_gate_status": "pass",
        }

    def fake_plain_exporter(**kwargs):
        export_calls.append(kwargs)
        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        prefix = output_dir / kwargs["prefix"]
        node_file = Path(f"{prefix}.nod.xml")
        edge_file = Path(f"{prefix}.edg.xml")
        connection_file = Path(f"{prefix}.con.xml")
        type_file = Path(f"{prefix}.typ.xml")
        tllogic_file = Path(f"{prefix}.tll.xml")
        for path in (node_file, edge_file, connection_file, type_file, tllogic_file):
            path.write_text("<xml/>", encoding="utf-8")
        return {
            "status": "pass",
            "raw_node_file": str(node_file),
            "raw_edge_file": str(edge_file),
            "raw_connection_file": str(connection_file),
            "raw_type_file": str(type_file),
            "raw_tllogic_file": str(tllogic_file),
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "cluster_a_b",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in_a"},
                },
                {
                    "junction_id": "cluster_c_d",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in_c"},
                },
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        raw_tllogic_file=raw_tllogics,
        output_dir=tmp_path / "run",
        sequential_accept_passed_variants=True,
        plain_exporter=fake_plain_exporter,
        variant_builder=fake_variant,
    )

    first_final = Path(report["variant_reports"][0]["final_net_file"])
    assert report["status"] == "pass"
    assert report["composite_applied_candidate_count"] == 2
    assert report["composite_net_file"] == report["variant_reports"][1]["final_net_file"]
    assert export_calls[0]["net_file"] == first_final
    assert variant_calls[0]["raw_tllogic_file"] == raw_tllogics
    assert variant_calls[1]["candidate_net_file"] == first_final
    plain_export = report["sequential_plain_export_reports"][0]
    assert variant_calls[1]["raw_node_file"] == Path(plain_export["raw_node_file"])
    assert variant_calls[1]["raw_edge_file"] == Path(plain_export["raw_edge_file"])
    assert variant_calls[1]["raw_connection_file"] == Path(plain_export["raw_connection_file"])
    assert variant_calls[1]["raw_tllogic_file"] == Path(plain_export["raw_tllogic_file"])


def test_run_teacher_guided_repair_queue_restores_accepted_internal_replays_after_sequential_plain_roundtrip(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")
    candidate_net.write_text('<net><junction id="j1"/><junction id="j2"/></net>', encoding="utf-8")
    restore_calls = []
    normalize_calls = []

    def fake_variant(**kwargs):
        final_net = kwargs["output_dir"] / "final.net.xml"
        final_net.parent.mkdir(parents=True, exist_ok=True)
        final_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "final_net_file": str(final_net),
            "parity_gate_status": "pass",
            "target_internal_replay": {
                "status": "pass",
                "effective_edge_map": {f"teacher_{kwargs['junction_id']}": f"candidate_{kwargs['junction_id']}"},
            },
        }

    def fake_plain_exporter(**kwargs):
        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        prefix = output_dir / kwargs["prefix"]
        node_file = Path(f"{prefix}.nod.xml")
        edge_file = Path(f"{prefix}.edg.xml")
        connection_file = Path(f"{prefix}.con.xml")
        type_file = Path(f"{prefix}.typ.xml")
        for path in (node_file, edge_file, connection_file, type_file):
            path.write_text("<xml/>", encoding="utf-8")
        return {
            "status": "pass",
            "raw_node_file": str(node_file),
            "raw_edge_file": str(edge_file),
            "raw_connection_file": str(connection_file),
            "raw_type_file": str(type_file),
        }

    def fake_restore(**kwargs):
        restore_calls.append(kwargs)
        kwargs["output_file"].write_text("<net/>", encoding="utf-8")
        return {"status": "pass", "net_file": str(kwargs["output_file"])}

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        normalize_calls.append(command)
        assert command[0] == "netconvert"
        assert "--sumo-net-file" in command
        input_file = Path(cwd) / command[command.index("--sumo-net-file") + 1]
        output_file = Path(cwd) / command[command.index("--output-file") + 1]
        output_file.write_text(input_file.read_text(encoding="utf-8"), encoding="utf-8")

        class Result:
            status = "pass"
            returncode = 0

            def to_dict(self):
                return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

        return Result()

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "j1",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_j1": "candidate_j1"},
                },
                {
                    "junction_id": "j2",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_j2": "candidate_j2"},
                },
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        sequential_accept_passed_variants=True,
        plain_exporter=fake_plain_exporter,
        variant_builder=fake_variant,
        final_internal_replay_writer=fake_restore,
        command_runner=fake_runner,
    )

    assert [call["junction_id"] for call in restore_calls] == ["j1", "j2"]
    assert restore_calls[0]["candidate_net_file"] == Path(report["variant_reports"][1]["final_net_file"])
    assert restore_calls[1]["candidate_net_file"] == restore_calls[0]["output_file"]
    assert report["final_internal_replay_status"] == "pass"
    assert report["final_internal_replay_restored_count"] == 2
    assert len(normalize_calls) == 2
    assert report["final_internal_replay_normalize"]["status"] == "pass"
    assert [item["status"] for item in report["final_internal_replay_normalize"]["geometry_restore"]] == [
        "pass",
        "pass",
    ]
    assert report["final_internal_replay_normalize"]["canonicalize"]["status"] == "pass"
    assert report["final_internal_replay_normalized_net_file"].endswith("final_internal_replay_canonical.net.xml")
    assert report["composite_net_file"] == report["final_internal_replay_normalized_net_file"]


def test_run_teacher_guided_repair_queue_replays_unrestored_normalized_variants_from_clean_base(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")
    candidate_net.write_text('<net><junction id="j1"/><junction id="j2"/></net>', encoding="utf-8")
    restore_calls = []

    def fake_variant(**kwargs):
        final_net = kwargs["output_dir"] / f"{kwargs['junction_id']}.net.xml"
        final_net.parent.mkdir(parents=True, exist_ok=True)
        final_net.write_text("<net/>", encoding="utf-8")
        report = {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "final_net_file": str(final_net),
            "parity_gate_status": "pass",
            "target_internal_replay": {
                "status": "pass",
                "effective_edge_map": {f"teacher_{kwargs['junction_id']}": f"candidate_{kwargs['junction_id']}"},
            },
        }
        if kwargs["junction_id"] == "j2":
            report["target_internal_normalize"] = {"unrestored_sumo_load": {"status": "pass"}}
        return report

    def fake_restore(**kwargs):
        restore_calls.append(kwargs)
        kwargs["output_file"].write_text("<net/>", encoding="utf-8")
        return {"status": "pass", "net_file": str(kwargs["output_file"])}

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        output_file = Path(cwd) / command[command.index("--output-file") + 1]
        output_file.write_text("<net/>", encoding="utf-8")

        class Result:
            def to_dict(self):
                return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

        return Result()

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {"junction_id": "j1", "candidate_status": "ready_for_teacher_guided_variant", "edge_map": {"a": "b"}},
                {"junction_id": "j2", "candidate_status": "ready_for_teacher_guided_variant", "edge_map": {"c": "d"}},
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        sequential_accept_passed_variants=True,
        variant_builder=fake_variant,
        final_internal_replay_writer=fake_restore,
        command_runner=fake_runner,
    )

    assert report["final_internal_replay_status"] == "pass"
    assert restore_calls[0]["candidate_net_file"] == candidate_net
    assert restore_calls[1]["candidate_net_file"] == restore_calls[0]["output_file"]


def test_run_teacher_guided_repair_queue_uses_composite_base_for_joined_unrestored_replay(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net):
        path.write_text("<xml/>", encoding="utf-8")
    candidate_net.write_text('<net><junction id="source_a"/></net>', encoding="utf-8")
    restore_calls = []

    def fake_variant(**kwargs):
        final_net = kwargs["output_dir"] / "joined.net.xml"
        final_net.parent.mkdir(parents=True, exist_ok=True)
        final_net.write_text('<net><junction id="cluster_joined"/></net>', encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "final_net_file": str(final_net),
            "parity_gate_status": "pass",
            "target_internal_replay": {
                "status": "pass",
                "effective_edge_map": {"teacher_in": "candidate_in"},
            },
            "target_internal_normalize": {"unrestored_sumo_load": {"status": "pass"}},
        }

    def fake_restore(**kwargs):
        restore_calls.append(kwargs)
        if kwargs["candidate_net_file"] == candidate_net:
            return {"status": "fail", "error": "candidate junction not found: cluster_joined"}
        kwargs["output_file"].write_text('<net><junction id="cluster_joined"/></net>', encoding="utf-8")
        return {"status": "pass", "net_file": str(kwargs["output_file"])}

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        input_file = Path(cwd) / command[command.index("--sumo-net-file") + 1]
        output_file = Path(cwd) / command[command.index("--output-file") + 1]
        output_file.write_text(input_file.read_text(encoding="utf-8"), encoding="utf-8")

        class Result:
            def to_dict(self):
                return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

        return Result()

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "cluster_joined",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "candidate_in"},
                },
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        sequential_accept_passed_variants=True,
        variant_builder=fake_variant,
        final_internal_replay_writer=fake_restore,
        command_runner=fake_runner,
    )

    assert report["final_internal_replay_status"] == "pass"
    assert restore_calls[0]["candidate_net_file"] == Path(report["variant_reports"][0]["final_net_file"])


def test_run_teacher_guided_repair_queue_sequentially_adopts_composite_after_parity_failed_candidate(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")
    variant_calls = []

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        final_net = kwargs["output_dir"] / "final.net.xml"
        final_net.parent.mkdir(parents=True, exist_ok=True)
        final_net.write_text("<net/>", encoding="utf-8")
        if len(variant_calls) == 1:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "junction_id": kwargs["junction_id"],
                "final_net_file": str(final_net),
                "parity_gate_status": "fail",
                "semantic_replay_gate": {
                    "status": "fail",
                    "failures": [
                        {"report": "parity", "field": "vehicle_movement_matrix_missing_count", "count": 1}
                    ],
                },
                "semantic_layer_gates": {
                    "topology": {"status": "pass", "failure_count": 0, "failures": []},
                    "movement_tls": {
                        "status": "fail",
                        "failure_count": 1,
                        "failures": [
                            {"report": "parity", "field": "vehicle_movement_matrix_missing_count", "count": 1}
                        ],
                    },
                    "pedestrian_bike": {"status": "pass", "failure_count": 0, "failures": []},
                    "internal": {"status": "pass", "failure_count": 0, "failures": []},
                },
            }
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "final_net_file": str(final_net),
            "parity_gate_status": "pass",
            "semantic_layer_gates": {
                "topology": {"status": "pass", "failure_count": 0, "failures": []},
                "movement_tls": {"status": "pass", "failure_count": 0, "failures": []},
                "pedestrian_bike": {"status": "pass", "failure_count": 0, "failures": []},
                "internal": {"status": "pass", "failure_count": 0, "failures": []},
            },
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "cluster_a_b",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in_a": "cand_in_a"},
                },
                {
                    "junction_id": "cluster_c_d",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in_c": "cand_in_c"},
                },
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        sequential_accept_passed_variants=True,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert report["parity_gate_status"] == "pass"
    assert report["attempted_candidate_count"] == 2
    assert report["failed_candidate_count"] == 0
    assert report["parity_pass_candidate_count"] == 1
    assert report["composite_applied_candidate_count"] == 1
    assert report["composite_net_file"] == report["variant_reports"][1]["final_net_file"]
    gate = json.loads(Path(report["promotion_gate_file"]).read_text(encoding="utf-8"))
    assert report["promotion_gate_status"] == "pass"
    assert gate["status"] == "pass"
    assert gate["candidate_count"] == 1
    assert gate["items"][0]["junction_id"] == "cluster_c_d"
    assert report["semantic_failure_counts"] == {"parity:vehicle_movement_matrix_missing_count": 1}
    assert report["semantic_layer_gate_counts"] == {
        "topology": {"pass": 2, "fail": 0, "failure_count": 0},
        "movement_tls": {"pass": 1, "fail": 1, "failure_count": 1},
        "pedestrian_bike": {"pass": 2, "fail": 0, "failure_count": 0},
        "internal": {"pass": 2, "fail": 0, "failure_count": 0},
    }


def test_run_teacher_guided_repair_queue_passes_reference_id_as_teacher_junction_id(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")
    calls = []

    def fake_variant(**kwargs):
        calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "cluster_a_b_c_d_e_f",
                    "junction_id": "cluster_a_b_c_d_#2more",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert calls[0]["junction_id"] == "cluster_a_b_c_d_#2more"
    assert calls[0]["teacher_junction_id"] == "cluster_a_b_c_d_e_f"
    assert report["parity_gate_status"] == "pass"
    assert calls[0]["edge_map"] == {"teacher_in": "cand_in"}


def test_run_teacher_guided_repair_queue_blocks_without_ready_candidates(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")

    def fail_if_called(**_kwargs):
        raise AssertionError("variant builder must not run for blocked candidates")

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {"junction_id": "cluster_c_d", "candidate_status": "needs_joined_candidate_junction", "edge_map": {}},
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        variant_builder=fail_if_called,
    )

    assert report["status"] == "blocked"
    assert report["claim_status"] == "blocked"
    assert report["attempted_candidate_count"] == 0
    assert report["skipped_candidate_count"] == 1
    assert Path(report["run_report_file"]).is_file()


def test_run_teacher_guided_repair_queue_labels_no_vehicle_reference_context(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {"junction_id": "ped_context", "candidate_status": "no_vehicle_reference_context", "edge_map": {}},
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
    )

    assert report["status"] == "blocked"
    assert report["skipped_candidates"] == [
        {
            "index": 0,
            "junction_id": "ped_context",
            "candidate_status": "no_vehicle_reference_context",
            "skip_reason": "no_vehicle_reference_context",
        }
    ]


def test_run_teacher_guided_repair_queue_writes_expanded_scope_plain_inputs(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="10" y="0"/>
  <node id="e" x="12" y="0"/>
  <node id="x" x="99" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="approach_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="teacher_out" from="j" to="c"><lane index="0"/></edge>
  <edge id="old_downstream" from="c" to="e"><lane index="0"/></edge>
  <edge id="outside" from="x" to="a"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="approach_in" to="teacher_out" fromLane="0" toLane="0"/>
  <connection from="teacher_out" to="old_downstream" fromLane="0" toLane="0"/>
  <connection from="outside" to="approach_in" fromLane="0" toLane="0"/>
</connections>""",
        encoding="utf-8",
    )
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    variant_calls = []

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "parity_gate_status": "pass",
        }

    commands: list[list[str]] = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        commands.append(command)
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_c_e_j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "approach_in"},
                    "teacher_pattern_key": "three_way|control=right_before_left",
                    "teacher_pattern_family": "three_way",
                    "teacher_pattern_template_count": 127,
                    "teacher_pattern_template_examples": ["cluster_template_1"],
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["c", "e", "j"],
                        "join_junction_ids": ["c", "e", "j"],
                        "blocked_teacher_edge_ids": ["teacher_out"],
                    },
                    "approach_endpoint_rebuild_plan": {
                        "status": "review",
                        "edge_rebuilds": [
                            {
                                "edge_id": "teacher_out",
                                "candidate_from": "j",
                                "candidate_to": "c",
                                "desired_from": "j",
                                "desired_to": "e",
                            }
                        ],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert report["attempted_candidate_count"] == 1
    assert report["expanded_scope_candidate_count"] == 1
    scope_report = report["expanded_scope_reports"][0]
    assert scope_report["status"] == "pass"
    assert scope_report["teacher_pattern_key"] == "three_way|control=right_before_left"
    assert scope_report["teacher_pattern_template_count"] == 127
    assert report["teacher_pattern_contexts"] == [
        {
            "teacher_pattern_key": "three_way|control=right_before_left",
            "teacher_pattern_family": "three_way",
            "teacher_pattern_template_count": 127,
            "teacher_pattern_template_examples": ["cluster_template_1"],
        }
    ]
    assert scope_report["node_count"] == 4
    assert scope_report["edge_count"] == 3
    assert scope_report["connection_count"] == 1
    assert scope_report["rewritten_endpoint_count"] == 1
    assert scope_report["netconvert"]["status"] == "pass"
    assert scope_report["sumo_load"]["status"] == "pass"
    assert scope_report["joined_scope_junction_id"] == "cluster_c_e_j"
    assert Path(scope_report["join_nodes_patch_file"]).is_file()
    assert commands[0][commands[0].index("--node-files") + 1] == (
        "expanded_scope.nod.xml,expanded_scope_junction_join.nod.xml"
    )
    assert scope_report["netconvert_command"][-2:] == ["--output-file", "expanded_scope.net.xml"]
    assert report["expanded_scope_pass_candidate_count"] == 1
    assert report["parity_gate_status"] == "pass"
    assert Path(report["best_expanded_scope_net_file"]).name == "expanded_scope.net.xml"
    scope_nodes = ET.parse(scope_report["node_file"]).getroot()
    scope_edges = ET.parse(scope_report["edge_file"]).getroot()
    scope_connections = ET.parse(scope_report["connection_file"]).getroot()
    scope_join_patch = ET.parse(scope_report["join_nodes_patch_file"]).getroot()
    assert [node.attrib["id"] for node in scope_nodes] == ["a", "c", "e", "j"]
    assert [edge.attrib["id"] for edge in scope_edges] == ["approach_in", "teacher_out", "old_downstream"]
    assert scope_edges.find("edge[@id='teacher_out']").attrib["to"] == "e"
    assert [connection.attrib["from"] for connection in scope_connections] == ["approach_in"]
    assert [join.attrib["nodes"] for join in scope_join_patch.findall("join")] == ["c e j"]
    assert [command[0] for command in commands] == ["netconvert-test", "sumo-test"]
    replay_node_file = variant_calls[0]["raw_node_file"]
    assert replay_node_file != Path(scope_report["node_file"])
    assert replay_node_file == Path(scope_report["replay_node_file"])
    replay_nodes = ET.parse(replay_node_file).getroot()
    assert [join.attrib["nodes"] for join in replay_nodes.findall("join")] == ["c e j"]
    replay_edge_file = variant_calls[0]["raw_edge_file"]
    assert replay_edge_file != Path(scope_report["edge_file"])
    assert replay_edge_file == Path(scope_report["replay_edge_file"])
    replay_edges = ET.parse(replay_edge_file).getroot()
    assert replay_edges.find("edge[@id='approach_in']").attrib["to"] == "j"
    assert replay_edges.find("edge[@id='teacher_out']") is None
    assert replay_edges.find("edge[@id='old_downstream']") is None
    assert scope_report["replay_edge_endpoint_rewrite_count"] == 0
    assert scope_report["replay_self_loop_edge_drop_count"] == 2
    assert scope_report["replay_dropped_self_loop_edges"] == ["teacher_out", "old_downstream"]
    assert variant_calls[0]["raw_connection_file"] == Path(scope_report["connection_file"])
    assert variant_calls[0]["candidate_net_file"] == Path(scope_report["net_file"])
    assert variant_calls[0]["junction_id"] == "cluster_c_e_j"
    assert variant_calls[0]["teacher_junction_id"] == "j"
    assert variant_calls[0]["edge_map"] == {"teacher_in": "approach_in"}


def test_run_teacher_guided_repair_queue_emits_followup_scope_for_unsafe_internal_replay(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="n" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="main" from="a" to="j"><lane index="0"/></edge>
  <edge id="neighbor_out" from="j" to="n"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    def fake_variant(**kwargs):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "parity_gate_status": "fail",
            "target_internal_replay": {
                "status": "pass",
                "skipped_connection_count": 0,
                "removed_stale_replaced_edge_connection_count": 1,
                "removed_stale_replaced_edge_connections": [
                    {"from": "main", "to": "neighbor_out", "via": ":n_0_0"}
                ],
            },
            "semantic_replay_gate": {
                "status": "fail",
                "failures": [
                    {
                        "report": "target_internal_replay",
                        "field": "removed_stale_replaced_edge_connection_count",
                        "count": 1,
                    }
                ],
            },
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_main": "main", "teacher_out": "neighbor_out"},
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        variant_builder=fake_variant,
    )

    assert report["expanded_scope_followup_candidate_count"] == 1
    followup = report["expanded_scope_followup_candidates"][0]
    assert followup["candidate_status"] == "needs_expanded_rebuild_scope"
    assert followup["followup_reason"] == "target_internal_replay_removed_non_target_connections"
    assert followup["expanded_rebuild_scope"]["junction_ids"] == ["a", "j", "n"]
    assert followup["expanded_rebuild_scope"]["join_junction_ids"] == ["j"]
    assert followup["expanded_rebuild_scope"]["blocked_teacher_edge_ids"] == ["teacher_main", "teacher_out"]


def test_run_teacher_guided_repair_queue_expands_followup_scope_after_expanded_replay_removes_connections(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="n" x="10" y="0"/>
  <node id="q" x="20" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="main" from="a" to="j"><lane index="0"/></edge>
  <edge id="neighbor_out" from="j" to="n"><lane index="0"/></edge>
  <edge id="far_out" from="n" to="q"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_a_j_n" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "parity_gate_status": "fail",
            "target_internal_replay": {
                "status": "pass",
                "skipped_connection_count": 0,
                "removed_stale_replaced_edge_connection_count": 1,
                "removed_stale_replaced_edge_connections": [
                    {"from": "neighbor_out", "to": "far_out", "via": ":q_0_0"}
                ],
            },
            "semantic_replay_gate": {
                "status": "fail",
                "failures": [
                    {
                        "report": "target_internal_replay",
                        "field": "removed_stale_replaced_edge_connection_count",
                        "count": 1,
                    }
                ],
            },
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_main": "main", "teacher_neighbor": "neighbor_out", "teacher_far": "far_out"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["a", "j", "n"],
                        "join_junction_ids": ["a", "j", "n"],
                        "blocked_teacher_edge_ids": ["teacher_main", "teacher_neighbor"],
                        "missing_desired_endpoint_ids": ["missing_endpoint"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["expanded_scope_followup_candidate_count"] == 1
    followup = report["expanded_scope_followup_candidates"][0]
    assert followup["expanded_rebuild_scope"]["junction_ids"] == ["a", "j", "n", "q"]
    assert followup["expanded_rebuild_scope"]["join_junction_ids"] == ["a", "j", "n"]
    assert followup["expanded_rebuild_scope"]["blocked_teacher_edge_ids"] == ["teacher_far", "teacher_neighbor"]
    assert followup["expanded_rebuild_scope"]["missing_desired_endpoint_ids"] == ["missing_endpoint"]


def test_expanded_scope_followup_excludes_non_raw_teacher_cluster_from_join_scope(
    tmp_path: Path,
) -> None:
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="main" from="a" to="j"><lane index="0"/></edge>
  <edge id="neighbor_out" from="j" to="n"><lane index="0"/></edge>
  <edge id="far_out" from="n" to="q"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )

    followup = _expanded_scope_followup_candidate_for_unsafe_internal_replay(
        {
            "reference_id": "cluster_teacher",
            "junction_id": "cluster_teacher",
            "candidate_status": "needs_expanded_rebuild_scope",
            "edge_map": {"teacher_neighbor": "neighbor_out", "teacher_far": "far_out"},
            "expanded_rebuild_scope": {
                "status": "review",
                "recommended_action": "rebuild_plain_xml_scope",
                "core_junction_id": "cluster_teacher",
                "junction_ids": ["a", "j", "n"],
                "join_junction_ids": ["a", "j", "n"],
                "blocked_teacher_edge_ids": ["teacher_neighbor"],
            },
        },
        {
            "target_internal_replay": {
                "removed_stale_replaced_edge_connection_count": 1,
                "removed_stale_replaced_edge_connections": [
                    {"from": "neighbor_out", "to": "far_out", "via": ":q_0_0"}
                ],
            }
        },
        raw_edges,
        junction_id="cluster_teacher",
    )

    assert followup is not None
    assert followup["expanded_rebuild_scope"]["junction_ids"] == ["a", "j", "n", "q"]
    assert followup["expanded_rebuild_scope"]["join_junction_ids"] == ["a", "j", "n"]
    assert "cluster_teacher" not in followup["expanded_rebuild_scope"]["junction_ids"]


def test_teacher_guided_promotion_gate_keeps_applied_followup_report(tmp_path: Path) -> None:
    gate = _write_teacher_guided_promotion_gate(
        output_file=tmp_path / "promotion.json",
        status="pass",
        claim_status="diagnostic-demo",
        parity_gate_status="pass",
        approach_integrity_status="pass",
        variant_reports=[
            {
                "junction_id": "cluster_a_b",
                "teacher_junction_id": "teacher",
                "status": "pass",
                "parity_gate_status": "pass",
                "composite_applied": True,
                "expanded_scope_followup_emitted": True,
                "final_net_file": "candidate.net.xml",
            }
        ],
    )

    assert gate["status"] == "pass"
    assert gate["candidate_count"] == 1


def test_run_teacher_guided_repair_queue_replays_expanded_scope_followup_in_same_call(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="n" x="10" y="0"/>
  <node id="q" x="20" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="main" from="a" to="j"><lane index="0"/></edge>
  <edge id="neighbor_out" from="j" to="n"><lane index="0"/></edge>
  <edge id="far_out" from="n" to="q"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_a_j_n" type="priority" x="0" y="0" incLanes="" intLanes=""/>
  <junction id="cluster_a_j_n_q" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    variant_calls = []

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        if len(variant_calls) == 1:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "junction_id": kwargs["junction_id"],
                "parity_gate_status": "fail",
                "target_internal_replay": {
                    "status": "pass",
                    "skipped_connection_count": 0,
                    "removed_stale_replaced_edge_connection_count": 1,
                    "removed_stale_replaced_edge_connections": [
                        {"from": "neighbor_out", "to": "far_out", "via": ":q_0_0"}
                    ],
                },
                "semantic_replay_gate": {
                    "status": "fail",
                    "failures": [
                        {
                            "report": "target_internal_replay",
                            "field": "removed_stale_replaced_edge_connection_count",
                            "count": 1,
                        }
                    ],
                },
            }
        final_net = Path(kwargs["output_dir"]) / "final.net.xml"
        final_net.parent.mkdir(parents=True, exist_ok=True)
        final_net.write_text("<net><junction id=\"cluster_a_j_n_q\"/></net>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "parity_gate_status": "pass",
            "final_net_file": str(final_net),
            "target_internal_replay": {"status": "pass", "removed_stale_replaced_edge_connection_count": 0},
            "semantic_replay_gate": {"status": "pass", "failures": []},
            "semantic_layer_gates": {
                "topology": {"status": "pass", "failure_count": 0, "failures": []},
                "movement_tls": {"status": "pass", "failure_count": 0, "failures": []},
                "pedestrian_bike": {"status": "pass", "failure_count": 0, "failures": []},
                "internal": {"status": "pass", "failure_count": 0, "failures": []},
            },
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_main": "main", "teacher_neighbor": "neighbor_out", "teacher_far": "far_out"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["a", "j", "n"],
                        "join_junction_ids": ["a", "j", "n"],
                        "blocked_teacher_edge_ids": ["teacher_main", "teacher_neighbor"],
                        "missing_desired_endpoint_ids": [],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        max_ready_candidates=1,
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
        sequential_accept_passed_variants=True,
    )

    assert len(variant_calls) == 2
    assert report["expanded_scope_followup_candidate_count"] == 1
    assert report["composite_applied_candidate_count"] == 1
    assert report["status"] == "pass"
    assert report["parity_gate_status"] == "pass"
    assert report["semantic_failure_counts"] == {}
    assert Path(report["composite_net_file"]).is_file()


def test_run_teacher_guided_repair_queue_replays_no_join_expanded_scope_on_full_network(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="b" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        final_net = kwargs["output_dir"] / "final.net.xml"
        final_net.parent.mkdir(parents=True, exist_ok=True)
        final_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "final_net_file": str(final_net),
            "parity_gate_status": "pass",
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "cand_in", "teacher_out": "cand_out"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "core_junction_id": "j",
                        "junction_ids": ["j", "missing_endpoint"],
                        "join_junction_ids": ["j"],
                        "blocked_teacher_edge_ids": [],
                        "missing_desired_endpoint_ids": ["missing_endpoint"],
                    },
                    "approach_endpoint_rebuild_plan": {
                        "status": "review",
                        "edge_rebuilds": [
                            {
                                "edge_id": "cand_out",
                                "desired_from": "j",
                                "desired_to": "missing_endpoint",
                            }
                        ],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
        sequential_accept_passed_variants=True,
    )

    assert report["status"] == "pass"
    assert report["composite_applied_candidate_count"] == 1
    assert report["composite_net_file"] == report["variant_reports"][0]["final_net_file"]
    assert report["expanded_scope_reports"][0]["join_explicit_join_count"] == 0
    assert report["expanded_scope_reports"][0]["missing_node_ids"] == ["missing_endpoint"]
    assert variant_calls[0]["raw_node_file"] == raw_nodes
    assert variant_calls[0]["raw_edge_file"] == raw_edges
    assert variant_calls[0]["raw_connection_file"] == raw_connections
    assert variant_calls[0]["candidate_net_file"] == candidate_net
    assert variant_calls[0]["junction_id"] == "j"
    assert variant_calls[0]["teacher_junction_id"] == "teacher_j"


def test_run_teacher_guided_repair_queue_replays_joined_expanded_scope_on_full_network(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="x" x="-10" y="0"/>
  <node id="a" x="0" y="0"/>
  <node id="b" x="1" y="0"/>
  <node id="y" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="x" to="a" shape="-10,0 0,0"><lane index="0"/></edge>
  <edge id="cand_out" from="b" to="y" shape="1,0 10,0"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0"/>
</connections>
""",
        encoding="utf-8",
    )
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        final_net = kwargs["output_dir"] / "final.net.xml"
        final_net.parent.mkdir(parents=True, exist_ok=True)
        final_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "final_net_file": str(final_net),
            "parity_gate_status": "pass",
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "a",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "cand_in", "teacher_out": "cand_out"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "core_junction_id": "a",
                        "junction_ids": ["a", "b"],
                        "join_junction_ids": ["a", "b"],
                        "blocked_teacher_edge_ids": [],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
        sequential_accept_passed_variants=True,
    )

    assert report["status"] == "pass"
    assert report["composite_applied_candidate_count"] == 1
    assert report["composite_net_file"] == report["variant_reports"][0]["final_net_file"]
    assert report["expanded_scope_reports"][0]["replay_scope"] == "full_network_join_patch"
    assert variant_calls[0]["candidate_net_file"].name == "full_network_join_replay.net.xml"
    assert variant_calls[0]["raw_connection_file"] == raw_connections
    assert variant_calls[0]["raw_edge_file"] == raw_edges
    assert variant_calls[0]["preserve_teacher_lane_shapes"] is False
    assert variant_calls[0]["emit_teacher_crossings"] is False
    assert '<join nodes="a b"' in variant_calls[0]["raw_node_file"].read_text(encoding="utf-8")


def test_run_teacher_guided_repair_queue_prefers_full_context_join_replay_for_single_probe(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="x" x="-10" y="0"/>
  <node id="a" x="0" y="0"/>
  <node id="b" x="1" y="0"/>
  <node id="y" x="10" y="0"/>
  <node id="context" x="20" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="x" to="a" shape="-10,0 0,0"><lane index="0"/></edge>
  <edge id="cand_out" from="b" to="y" shape="1,0 10,0"><lane index="0"/></edge>
  <edge id="context_edge" from="y" to="context" shape="10,0 20,0"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0"/>
</connections>
""",
        encoding="utf-8",
    )
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="x" to="cluster_a_b"/>
  <edge id="cand_out" from="cluster_a_b" to="y"/>
  <edge id="context_edge" from="y" to="context"/>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        final_net = kwargs["output_dir"] / "final.net.xml"
        final_net.parent.mkdir(parents=True, exist_ok=True)
        final_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "final_net_file": str(final_net),
            "parity_gate_status": "pass",
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "a",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "cand_in", "teacher_out": "cand_out"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "core_junction_id": "a",
                        "junction_ids": ["a", "b"],
                        "join_junction_ids": ["a", "b"],
                        "blocked_teacher_edge_ids": [],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert report["expanded_scope_reports"][0]["replay_scope"] == "full_network_join_patch"
    assert variant_calls[0]["candidate_net_file"].name == "full_network_join_replay.net.xml"
    assert variant_calls[0]["raw_edge_file"] == raw_edges
    assert "context_edge" in variant_calls[0]["raw_edge_file"].read_text(encoding="utf-8")
    assert '<join nodes="a b"' in variant_calls[0]["raw_node_file"].read_text(encoding="utf-8")


def test_run_teacher_guided_repair_queue_filters_join_scope_dead_end_connections_for_full_network_seed(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="x" x="-10" y="0"/>
  <node id="a" x="0" y="0"/>
  <node id="b" x="1" y="0"/>
  <node id="y" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="x" to="a" shape="-10,0 0,0"><lane index="0"/></edge>
  <edge id="cand_mid" from="a" to="b" shape="0,0 1,0"><lane index="0"/></edge>
  <edge id="cand_out" from="b" to="y" shape="1,0 10,0"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="cand_in" to="cand_mid" fromLane="0" toLane="0"/>
  <connection from="cand_mid"/>
  <connection from="cand_mid" to="cand_out" fromLane="0" toLane="0"/>
</connections>
""",
        encoding="utf-8",
    )
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    seed_connection_files = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            if output_file.name == "full_network_join_replay.net.xml":
                connection_arg = command[command.index("--connection-files") + 1]
                seed_connection_files.append(Path(cwd) / connection_arg)
            output_file.write_text(
                """<net>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    variant_calls = []

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        final_net = kwargs["output_dir"] / "final.net.xml"
        final_net.parent.mkdir(parents=True, exist_ok=True)
        final_net.write_text("<net/>", encoding="utf-8")
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass", "final_net_file": str(final_net)}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "a",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "cand_in", "teacher_out": "cand_out"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "core_junction_id": "a",
                        "junction_ids": ["a", "b"],
                        "join_junction_ids": ["a", "b"],
                        "blocked_teacher_edge_ids": [],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
        sequential_accept_passed_variants=True,
    )

    assert report["status"] == "pass"
    assert seed_connection_files
    filtered_connections = [connection.attrib for connection in ET.parse(seed_connection_files[0]).getroot()]
    assert {"from": "cand_mid"} not in filtered_connections
    assert {"from": "cand_mid", "to": "cand_out", "fromLane": "0", "toLane": "0"} in filtered_connections
    assert variant_calls[0]["raw_connection_file"] == seed_connection_files[0]
    assert report["expanded_scope_reports"][0]["full_network_join_dead_end_connection_drop_count"] == 1


def test_run_teacher_guided_repair_queue_skips_joined_expanded_scope_when_seed_netconvert_fails(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="x" x="-10" y="0"/>
  <node id="a" x="0" y="0"/>
  <node id="b" x="1" y="0"/>
  <node id="y" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="x" to="a" shape="-10,0 0,0"><lane index="0"/></edge>
  <edge id="cand_out" from="b" to="y" shape="1,0 10,0"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            if output_file.name == "full_network_join_replay.net.xml":
                return {"command": command, "cwd": str(cwd), "status": "fail", "returncode": 1}
            output_file.write_text(
                """<net>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    variant_calls = []

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "a",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "cand_in", "teacher_out": "cand_out"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "core_junction_id": "a",
                        "junction_ids": ["a", "b"],
                        "join_junction_ids": ["a", "b"],
                        "blocked_teacher_edge_ids": [],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
        sequential_accept_passed_variants=True,
    )

    assert variant_calls == []
    assert report["attempted_candidate_count"] == 0
    assert report["expanded_scope_reports"][0]["full_network_join_seed_netconvert"]["status"] == "fail"
    assert report["skipped_candidates"] == [
        {
            "index": 0,
            "junction_id": "a",
            "candidate_status": "full_network_join_seed_failed",
        }
    ]


def test_run_teacher_guided_repair_queue_skips_joined_expanded_scope_when_cluster_already_exists(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="0" y="0"/>
  <node id="b" x="1" y="0"/>
  <node id="cluster_a_b" x="0.5" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text("<edges/>\n", encoding="utf-8")
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_a_b" type="priority" x="0.5" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fail_if_called(**_kwargs):
        raise AssertionError("existing joined cluster should skip full-network replay")

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "a",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "cand_in"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "core_junction_id": "a",
                        "junction_ids": ["a", "b"],
                        "join_junction_ids": ["a", "b"],
                        "blocked_teacher_edge_ids": [],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fail_if_called,
        sequential_accept_passed_variants=True,
    )

    assert report["attempted_candidate_count"] == 0
    assert report["skipped_candidates"][0]["candidate_status"] == "sequential_candidate_overlap"
    assert report["skipped_candidates"][0]["overlap_node_ids"] == ["cluster_a_b"]


def test_run_teacher_guided_repair_queue_derives_expanded_edge_map_from_endpoint_plan(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="1" y="0"/>
  <node id="b" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0"/>
</connections>""",
        encoding="utf-8",
    )
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="teacher_j" type="highway.primary"><lane id="teacher_in_0" index="0"/></edge>
  <edge id="teacher_out" from="teacher_j" to="b" type="highway.primary"><lane id="teacher_out_0" index="0"/></edge>
  <junction id="teacher_j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text("<net/>", encoding="utf-8")
    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="cluster_c_j" type="highway.primary"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="cluster_c_j" to="b" type="highway.primary"><lane id="cand_out_0" index="0"/></edge>
  <junction id="cluster_c_j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0"/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["c", "j"],
                        "join_junction_ids": ["c", "j"],
                        "blocked_teacher_edge_ids": [],
                    },
                    "approach_endpoint_rebuild_plan": {
                        "status": "review",
                        "edge_rebuilds": [
                            {
                                "edge_id": "cand_in",
                                "direction": "incoming",
                                "desired_from": "a",
                                "desired_to": "j",
                            },
                            {
                                "edge_id": "cand_out",
                                "direction": "outgoing",
                                "desired_from": "j",
                                "desired_to": "b",
                            },
                        ],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert report["attempted_candidate_count"] == 1
    assert report["expanded_scope_reports"][0]["derived_edge_map"] == {
        "teacher_in": "cand_in",
        "teacher_out": "cand_out",
    }
    assert variant_calls[0]["junction_id"] == "cluster_c_j"
    assert variant_calls[0]["edge_map"] == {"teacher_in": "cand_in", "teacher_out": "cand_out"}


def test_run_teacher_guided_repair_queue_replays_expanded_scope_when_missing_blocked_edges_are_mapped(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="x" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="x" to="j" type="highway.primary"><lane index="0" shape="-10,0 0,0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="teacher_j" type="highway.primary"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <junction id="teacher_j" type="traffic_light" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <tlLogic id="teacher_j" type="actuated" programID="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text("<net/>", encoding="utf-8")
    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="x" to="j" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "learned_rule": "tum_like_topology_fragmented_tls_candidate",
                    "edge_map": {},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "core_junction_id": "j",
                        "junction_ids": ["j"],
                        "join_junction_ids": ["j"],
                        "blocked_teacher_edge_ids": ["teacher_in"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    scope_report = report["expanded_scope_reports"][0]
    assert scope_report["status"] == "pass"
    assert scope_report["missing_blocked_edge_ids"] == ["teacher_in"]
    assert scope_report["resolved_missing_blocked_edge_ids"] == ["teacher_in"]
    assert variant_calls[0]["edge_map"] == {"teacher_in": "cand_in"}
    assert variant_calls[0]["teacher_junction_id"] == "teacher_j"
    assert variant_calls[0]["replay_target_internal_subgraph"] is True


def test_run_teacher_guided_repair_queue_replays_copyable_missing_boundary_edge(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="x" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="x" to="j" type="highway.primary"><lane index="0" shape="-10,0 0,0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="teacher_j" type="highway.primary"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_missing" from="teacher_j" to="neighbor" type="highway.primary"><lane id="teacher_missing_0" index="0" shape="0,0 10,0"/></edge>
  <edge id=":teacher_j_0" function="internal"><lane id=":teacher_j_0_0" index="0" shape="0,0 1,0"/></edge>
  <junction id="teacher_j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=":teacher_j_0_0"/>
  <junction id="neighbor" type="priority" x="10" y="0" incLanes="" intLanes=""/>
  <connection from="teacher_in" to="teacher_missing" via=":teacher_j_0_0" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text("<net/>", encoding="utf-8")
    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="x" to="j" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "cand_in"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "core_junction_id": "j",
                        "junction_ids": ["j"],
                        "join_junction_ids": ["j"],
                        "blocked_teacher_edge_ids": ["teacher_missing"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert report["attempted_candidate_count"] == 1
    scope_report = report["expanded_scope_reports"][0]
    assert scope_report["status"] == "pass"
    assert scope_report["missing_blocked_edge_ids"] == ["teacher_missing"]
    assert scope_report["resolved_missing_blocked_edge_ids"] == []
    assert scope_report["copyable_missing_blocked_edge_ids"] == ["teacher_missing"]
    assert scope_report["blocking_missing_blocked_edge_ids"] == []
    assert scope_report["missing_blocked_edge_resolution"] == "copyable_by_teacher_replay"
    assert variant_calls[0]["edge_map"] == {"teacher_in": "cand_in", "teacher_missing": "teacher_missing"}


def test_run_teacher_guided_repair_queue_forces_internal_replay_for_topology_fragmented_tls(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="x" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="x" to="j" type="highway.primary"><lane index="0" shape="-10,0 0,0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="teacher_j" type="highway.primary"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_missing" from="teacher_j" to="neighbor" type="highway.primary"><lane id="teacher_missing_0" index="0" shape="0,0 10,0"/></edge>
  <edge id=":teacher_j_0" function="internal"><lane id=":teacher_j_0_0" index="0" shape="0,0 1,0"/></edge>
  <junction id="teacher_j" type="traffic_light" x="0" y="0" incLanes="teacher_in_0" intLanes=":teacher_j_0_0"/>
  <junction id="neighbor" type="priority" x="10" y="0" incLanes="" intLanes=""/>
  <connection from="teacher_in" to="teacher_missing" via=":teacher_j_0_0" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text("<net/>", encoding="utf-8")
    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="x" to="j" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "learned_rule": "tum_like_topology_fragmented_tls_candidate",
                    "edge_map": {"teacher_in": "cand_in"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "core_junction_id": "j",
                        "junction_ids": ["j"],
                        "join_junction_ids": ["j"],
                        "blocked_teacher_edge_ids": ["teacher_missing"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert variant_calls[0]["replay_target_internal_subgraph"] is True


def test_run_teacher_guided_repair_queue_replays_direct_missing_boundary_edge_without_internal_connection(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="x" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="x" to="j" type="highway.primary"><lane index="0" shape="-10,0 0,0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="teacher_j" type="highway.primary"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_missing" from="teacher_j" to="neighbor" type="highway.cycleway"><lane id="teacher_missing_0" index="0" allow="bicycle" shape="0,0 10,0"/></edge>
  <junction id="teacher_j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <junction id="neighbor" type="priority" x="10" y="0" incLanes="" intLanes=""/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text("<net/>", encoding="utf-8")
    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="x" to="j" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "cand_in"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "core_junction_id": "j",
                        "junction_ids": ["j"],
                        "join_junction_ids": ["j"],
                        "blocked_teacher_edge_ids": ["teacher_missing"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    scope_report = report["expanded_scope_reports"][0]
    assert scope_report["copyable_missing_blocked_edge_ids"] == ["teacher_missing"]
    assert scope_report["blocking_missing_blocked_edge_ids"] == []
    assert variant_calls[0]["junction_id"] == "j"


def test_run_teacher_guided_repair_queue_keeps_direct_missing_pedestrian_boundary_for_review(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="x" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="x" to="j" type="highway.primary"><lane index="0" shape="-10,0 0,0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="teacher_j" type="highway.primary"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_missing" from="teacher_j" to="neighbor" type="highway.footway"><lane id="teacher_missing_0" index="0" allow="pedestrian" shape="0,0 10,0"/></edge>
  <junction id="teacher_j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <junction id="neighbor" type="priority" x="10" y="0" incLanes="" intLanes=""/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text("<net/>", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="x" to="j" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "cand_in"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "core_junction_id": "j",
                        "junction_ids": ["j"],
                        "join_junction_ids": ["j"],
                        "blocked_teacher_edge_ids": ["teacher_missing"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
    )

    assert report["status"] == "blocked"
    scope_report = report["expanded_scope_reports"][0]
    assert scope_report["copyable_missing_blocked_edge_ids"] == []
    assert scope_report["blocking_missing_blocked_edge_ids"] == ["teacher_missing"]
    assert report["skipped_candidates"] == [
        {
            "index": 0,
            "junction_id": "j",
            "candidate_status": "needs_expanded_rebuild_scope",
            "skip_reason": "missing_blocked_edges_uncopyable",
            "blocking_missing_blocked_edge_ids": ["teacher_missing"],
        }
    ]


def test_run_teacher_guided_repair_queue_stops_expanded_scope_after_max_ready_candidates(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="x" x="-10" y="0"/>
  <node id="j1" x="0" y="0"/>
  <node id="j2" x="20" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in_1" from="x" to="j1" type="highway.primary"><lane index="0"/></edge>
  <edge id="cand_in_2" from="x" to="j2" type="highway.primary"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")
    netconvert_calls = []
    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            netconvert_calls.append(command)
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <edge id="cand_in_1" from="x" to="j1"><lane id="cand_in_1_0" index="0"/></edge>
  <edge id="cand_in_2" from="x" to="j2"><lane id="cand_in_2_0" index="0"/></edge>
  <junction id="j1" type="priority" x="0" y="0" incLanes="cand_in_1_0" intLanes=""/>
  <junction id="j2" type="priority" x="20" y="0" incLanes="cand_in_2_0" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    def expanded_candidate(junction_id: str, teacher_edge: str, candidate_edge: str) -> dict[str, object]:
        return {
            "reference_id": junction_id,
            "junction_id": junction_id,
            "candidate_status": "needs_expanded_rebuild_scope",
            "edge_map": {teacher_edge: candidate_edge},
            "expanded_rebuild_scope": {
                "status": "review",
                "core_junction_id": junction_id,
                "junction_ids": [junction_id],
                "join_junction_ids": [junction_id],
                "blocked_teacher_edge_ids": [],
            },
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                expanded_candidate("j1", "teacher_in_1", "cand_in_1"),
                expanded_candidate("j2", "teacher_in_2", "cand_in_2"),
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        max_ready_candidates=1,
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert report["attempted_candidate_count"] == 1
    assert len(variant_calls) == 1
    assert len(netconvert_calls) == 1
    assert len(report["expanded_scope_reports"]) == 1
    assert report["skipped_candidates"] == [
        {"index": 1, "junction_id": "j2", "candidate_status": "max_ready_candidates_reached"}
    ]


def test_write_expanded_scope_does_not_block_on_missing_desired_endpoint(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="approach_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="teacher_out" from="j" to="c"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="approach_in" to="teacher_out" fromLane="0" toLane="0"/>
</connections>""",
        encoding="utf-8",
    )

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    report = write_expanded_scope_plain_inputs(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "scope",
        expanded_rebuild_scope={
            "status": "review",
            "core_junction_id": "j",
            "junction_ids": ["c", "e", "j"],
            "blocked_teacher_edge_ids": [],
            "missing_desired_endpoint_ids": ["e"],
        },
        approach_endpoint_rebuild_plan={
            "status": "review",
            "edge_rebuilds": [
                {
                    "edge_id": "teacher_out",
                    "candidate_from": "j",
                    "candidate_to": "c",
                    "desired_from": "j",
                    "desired_to": "e",
                }
            ],
        },
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["missing_node_ids"] == ["e"]
    assert report["blocking_missing_node_ids"] == []
    assert report["skipped_endpoint_rewrites"] == [
        {
            "edge_id": "teacher_out",
            "desired_from": "j",
            "desired_to": "e",
            "missing_endpoint_ids": ["e"],
        }
    ]


def test_write_expanded_scope_defaults_join_to_core_junction(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="approach_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="context_out" from="j" to="c"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    commands = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        commands.append(command)
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    report = write_expanded_scope_plain_inputs(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "scope",
        expanded_rebuild_scope={
            "status": "review",
            "core_junction_id": "j",
            "junction_ids": ["c", "j"],
        },
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["joined_scope_junction_id"] == "j"
    assert report["join_node_ids"] == ["j"]
    assert report["join_nodes_patch_file"] == ""
    assert commands[0][commands[0].index("--node-files") + 1] == "expanded_scope.nod.xml"


def test_write_expanded_scope_keeps_boundary_context_out_of_join(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="10" y="0"/>
  <node id="e" x="20" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="approach_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="short_out" from="j" to="c"><lane index="0"/></edge>
  <edge id="downstream" from="c" to="e"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="approach_in" to="short_out" fromLane="0" toLane="0"/>
  <connection from="short_out" to="downstream" fromLane="0" toLane="0"/>
</connections>""",
        encoding="utf-8",
    )

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    report = write_expanded_scope_plain_inputs(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "scope",
        expanded_rebuild_scope={
            "status": "review",
            "core_junction_id": "j",
            "junction_ids": ["c", "e", "j"],
            "join_junction_ids": ["j"],
            "blocked_teacher_edge_ids": [],
            "missing_desired_endpoint_ids": [],
        },
        approach_endpoint_rebuild_plan={
            "status": "review",
            "edge_rebuilds": [
                {
                    "edge_id": "short_out",
                    "candidate_from": "j",
                    "candidate_to": "c",
                    "desired_from": "j",
                    "desired_to": "e",
                }
            ],
        },
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["joined_scope_junction_id"] == "j"
    assert report["join_nodes_patch_file"] == ""
    assert report["join_node_ids"] == ["j"]
    scope_edges = ET.parse(report["edge_file"]).getroot()
    assert scope_edges.find("edge[@id='short_out']").attrib["to"] == "e"


def test_run_teacher_guided_repair_queue_replays_existing_joined_expanded_scope(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="cluster_a_b" x="0" y="0"/>
  <node id="e" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="teacher_out" from="cluster_a_b" to="e"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_a_b" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "cluster_a_b",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_out": "teacher_out"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "cluster_a_b",
                        "junction_ids": ["a", "b"],
                        "join_junction_ids": ["a", "b"],
                        "blocked_teacher_edge_ids": ["teacher_out"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    scope_report = report["expanded_scope_reports"][0]
    assert scope_report["status"] == "pass"
    assert scope_report["joined_scope_junction_id"] == "cluster_a_b"
    assert scope_report["missing_node_ids"] == ["a", "b"]
    assert report["attempted_candidate_count"] == 1
    assert report["skipped_candidate_count"] == 0
    assert variant_calls[0]["junction_id"] == "cluster_a_b"
    assert variant_calls[0]["raw_node_file"] == Path(scope_report["node_file"])


def test_run_teacher_guided_repair_queue_absorbs_unmapped_join_internal_vehicle_edge(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="approach_in" from="a" to="j" type="highway.primary"><lane index="0"/></edge>
  <edge id="absorbed_between_join_sources" from="j" to="c" type="highway.primary"><lane index="0" allow="passenger"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="approach_in" to="absorbed_between_join_sources" fromLane="0" toLane="0"/>
</connections>""",
        encoding="utf-8",
    )
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_c_j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "approach_in"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["c", "j"],
                        "join_junction_ids": ["c", "j"],
                        "blocked_teacher_edge_ids": [],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert report["attempted_candidate_count"] == 1
    scope_report = report["expanded_scope_reports"][0]
    assert scope_report["replay_dropped_self_loop_edges"] == ["absorbed_between_join_sources"]
    assert scope_report["replay_absorbed_join_internal_edge_ids"] == ["absorbed_between_join_sources"]
    assert scope_report["replay_blocking_self_loop_edge_drops"] == []
    assert variant_calls[0]["junction_id"] == "cluster_c_j"


def test_run_teacher_guided_repair_queue_blocks_replay_that_would_drop_joined_vehicle_edge(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="approach_in" from="a" to="j" type="highway.primary"><lane index="0"/></edge>
  <edge id="between_join_sources" from="j" to="c" type="highway.primary"><lane index="0" allow="passenger"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="approach_in" to="between_join_sources" fromLane="0" toLane="0"/>
</connections>""",
        encoding="utf-8",
    )
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_c_j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "approach_in"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["c", "j"],
                        "join_junction_ids": ["c", "j"],
                        "blocked_teacher_edge_ids": ["between_join_sources"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "blocked"
    assert report["attempted_candidate_count"] == 0
    assert variant_calls == []
    scope_report = report["expanded_scope_reports"][0]
    assert scope_report["status"] == "review"
    assert scope_report["replay_self_loop_edge_drop_count"] == 1
    assert scope_report["replay_blocking_self_loop_edge_drops"] == ["between_join_sources"]
    assert report["skipped_candidates"] == [
        {
            "index": 0,
            "junction_id": "j",
            "candidate_status": "unsafe_replay_self_loop_edge_drop",
            "skip_reason": "protected_self_loop_edge_drop",
            "replay_blocking_self_loop_edge_drops": ["between_join_sources"],
        }
    ]


def test_run_teacher_guided_repair_queue_allows_self_loop_drop_for_target_internal_replay(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="approach_in" from="a" to="j" type="highway.primary"><lane index="0"/></edge>
  <edge id="between_join_sources" from="j" to="c" type="highway.primary"><lane index="0" allow="passenger"/></edge>
  <edge id="-between_join_sources" from="c" to="j" type="highway.primary"><lane index="0" allow="passenger"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_c_j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "approach_in"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["c", "j"],
                        "join_junction_ids": ["c", "j"],
                        "blocked_teacher_edge_ids": ["-between_join_sources", "between_join_sources"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        replay_target_internal_subgraph=True,
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert report["attempted_candidate_count"] == 1
    assert report["skipped_candidate_count"] == 0
    assert variant_calls[0]["junction_id"] == "cluster_c_j"
    scope_report = report["expanded_scope_reports"][0]
    assert sorted(scope_report["replay_absorbed_join_internal_edge_ids"]) == [
        "-between_join_sources",
        "between_join_sources",
    ]
    assert scope_report["replay_blocking_self_loop_edge_drops"] == []


def test_run_teacher_guided_repair_queue_allows_mapped_self_loop_drop_with_witness_for_target_internal_replay(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="approach_in" from="a" to="j" type="highway.primary"><lane index="0"/></edge>
  <edge id="between_join_sources" from="j" to="c" type="highway.primary"><lane index="0" allow="passenger"/></edge>
  <edge id="-between_join_sources" from="c" to="j" type="highway.primary"><lane index="0" allow="passenger"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_c_j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {
                        "teacher_in": "approach_in",
                        "teacher_between": "between_join_sources",
                    },
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["c", "j"],
                        "join_junction_ids": ["c", "j"],
                        "blocked_teacher_edge_ids": ["-between_join_sources", "between_join_sources"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        replay_target_internal_subgraph=True,
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert report["attempted_candidate_count"] == 1
    assert report["skipped_candidate_count"] == 0
    assert variant_calls[0]["junction_id"] == "cluster_c_j"
    scope_report = report["expanded_scope_reports"][0]
    assert sorted(scope_report["replay_absorbed_join_internal_edge_ids"]) == [
        "-between_join_sources",
        "between_join_sources",
    ]
    assert scope_report["replay_blocking_self_loop_edge_drops"] == []


def test_run_teacher_guided_repair_queue_keeps_singleton_self_loop_drop_for_review_with_target_replay(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="approach_in" from="a" to="j" type="highway.primary"><lane index="0"/></edge>
  <edge id="between_join_sources" from="j" to="c" type="highway.primary"><lane index="0" allow="passenger"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_c_j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "approach_in"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["c", "j"],
                        "join_junction_ids": ["c", "j"],
                        "blocked_teacher_edge_ids": ["between_join_sources"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        replay_target_internal_subgraph=True,
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
    )

    assert report["status"] == "blocked"
    assert report["attempted_candidate_count"] == 0
    assert report["skipped_candidates"][0]["candidate_status"] == "unsafe_replay_self_loop_edge_drop"
    assert report["skipped_candidates"][0]["skip_reason"] == "singleton_or_no_witness_self_loop_drop"


def test_run_teacher_guided_repair_queue_allows_teacher_boundary_singleton_self_loop_drop(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="approach_in" from="a" to="j" type="highway.primary"><lane index="0"/></edge>
  <edge id="teacher_boundary" from="j" to="c" type="highway.primary"><lane index="0" allow="passenger"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_boundary" from="teacher_j" to="teacher_neighbor"><lane id="teacher_boundary_0" index="0"/></edge>
  <junction id="teacher_j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
  <junction id="teacher_neighbor" type="priority" x="10" y="0" incLanes="teacher_boundary_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text("<net/>", encoding="utf-8")
    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_c_j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**kwargs):
        variant_calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "approach_in"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["c", "j"],
                        "join_junction_ids": ["c", "j"],
                        "blocked_teacher_edge_ids": ["teacher_boundary"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        replay_target_internal_subgraph=True,
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert report["attempted_candidate_count"] == 1
    assert variant_calls[0]["junction_id"] == "cluster_c_j"
    scope_report = report["expanded_scope_reports"][0]
    assert scope_report["replay_absorbed_join_internal_edge_ids"] == ["teacher_boundary"]
    assert scope_report["replay_blocking_self_loop_edge_drops"] == []


def test_target_internal_replay_preserves_replaced_boundary_edge_order(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="teacher_out" from="candidate_j" to="b"><lane id="teacher_out_0" index="0" shape="0,0 5,0"/></edge>
  <edge id="teacher_in" from="a" to="candidate_j"><lane id="teacher_in_0" index="0"/></edge>
  <junction id="b" type="priority" x="10" y="0" incLanes="teacher_out_0" intLanes=""/>
  <junction id="a" type="priority" x="-10" y="0" incLanes="" intLanes=""/>
  <junction id="candidate_j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="candidate_j" linkIndex="0"/>
</net>""",
        encoding="utf-8",
    )
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_out" from="teacher_j" to="b"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="teacher_in" from="a" to="teacher_j"><lane id="teacher_in_0" index="0"/></edge>
  <junction id="b" type="priority" x="10" y="0" incLanes="teacher_out_0" intLanes=""/>
  <junction id="a" type="priority" x="-10" y="0" incLanes="" intLanes=""/>
  <junction id="teacher_j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="teacher_j" linkIndex="0"/>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replay.net.xml",
        junction_id="candidate_j",
        teacher_junction_id="teacher_j",
        edge_map={"teacher_in": "teacher_in"},
    )

    assert report["status"] == "pass"
    assert report["copied_boundary_edge_count"] == 1
    children = [(child.tag, child.attrib.get("id", "")) for child in ET.parse(report["net_file"]).getroot()]
    assert children.index(("edge", "teacher_out")) < children.index(("junction", "b"))


def test_run_teacher_guided_repair_queue_skips_review_expanded_scope(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="c" x="0" y="0"/>
  <node id="e" x="1" y="0"/>
  <node id="b" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="c" type="highway.primary"><lane index="0" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="e" to="b" type="highway.primary"><lane index="0" shape="0,0 10,0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="teacher_j" type="highway.primary"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="teacher_j" to="b" type="highway.primary"><lane id="teacher_out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="teacher_j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text("<net/>", encoding="utf-8")
    variant_calls = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="cluster_c_e" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="cluster_c_e" to="b" type="highway.primary"><lane id="cand_out_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="cluster_c_e" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0"/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**_kwargs):
        raise AssertionError("variant builder must not run for review-only expanded scopes")

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "missing_joined_candidate",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "missing_joined_candidate",
                        "junction_ids": ["c", "e"],
                        "blocked_teacher_edge_ids": ["teacher_missing"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "blocked"
    assert report["expanded_scope_reports"][0]["status"] == "review"
    assert report["attempted_candidate_count"] == 0
    assert report["skipped_candidate_count"] == 1
    assert report["skipped_candidates"][0]["candidate_status"] == "needs_expanded_rebuild_scope"
    assert report["skipped_candidates"][0]["skip_reason"] == "edge_map_derivation_gap"


def test_run_teacher_guided_repair_queue_labels_expanded_scope_edge_map_derivation_gap(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text("<net/>", encoding="utf-8")
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text("<net/>", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["j"],
                        "join_junction_ids": ["j"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
    )

    assert report["status"] == "blocked"
    assert report["skipped_candidates"] == [
        {
            "index": 0,
            "junction_id": "j",
            "candidate_status": "needs_expanded_rebuild_scope",
            "skip_reason": "edge_map_derivation_gap",
        }
    ]


def test_run_teacher_guided_repair_queue_labels_missing_joined_scope_junction(
    tmp_path: Path,
) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="cluster_a_b" x="0" y="0"/>
  <node id="x" x="-10" y="0"/>
  <node id="y" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="blocked" from="x" to="y"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text("<net/>", encoding="utf-8")
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text("<net/>", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="x" type="priority" x="-10" y="0" incLanes="" intLanes=""/>
  <junction id="y" type="priority" x="10" y="0" incLanes="blocked_0" intLanes=""/>
  <edge id="blocked" from="x" to="y"><lane id="blocked_0" index="0"/></edge>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "cluster_a_b",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_edge": "blocked"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "cluster_a_b",
                        "junction_ids": ["a", "b"],
                        "join_junction_ids": ["a", "b"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
    )

    assert report["status"] == "blocked"
    assert report["skipped_candidates"] == [
        {
            "index": 0,
            "junction_id": "cluster_a_b",
            "candidate_status": "needs_expanded_rebuild_scope",
            "skip_reason": "scope_insufficient_joined_junction_missing",
            "blocking_missing_joined_scope_junction_ids": ["cluster_a_b"],
        }
    ]


def test_expanded_scope_reviews_when_joined_junction_missing_from_probe_net(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="cluster_a_b" x="0" y="0"/>
  <node id="x" x="-10" y="0"/>
  <node id="y" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="blocked" from="x" to="y"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="x" type="priority" x="-10" y="0" incLanes="" intLanes=""/>
  <junction id="y" type="priority" x="10" y="0" incLanes="blocked_0" intLanes=""/>
  <edge id="blocked" from="x" to="y"><lane id="blocked_0" index="0"/></edge>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    report = write_expanded_scope_plain_inputs(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "scope",
        expanded_rebuild_scope={
            "core_junction_id": "cluster_a_b",
            "junction_ids": ["a", "b"],
            "blocked_teacher_edge_ids": ["blocked"],
        },
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
    )

    assert report["joined_scope_junction_id"] == "cluster_a_b"
    assert report["status"] == "review"
    assert report["joined_scope_junction_missing_from_net"] is True
    assert report["blocking_missing_joined_scope_junction_ids"] == ["cluster_a_b"]


def test_run_teacher_guided_repair_queue_records_expanded_variant_exception(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="0"/>
  <node id="j" x="0" y="0"/>
  <node id="c" x="10" y="0"/>
</nodes>""",
        encoding="utf-8",
    )
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="c"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (teacher_net, candidate_net):
        path.write_text("<net/>", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert-test":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(
                """<net>
  <junction id="cluster_c_j" type="priority" x="0" y="0" incLanes="" intLanes=""/>
</net>""",
                encoding="utf-8",
            )
        return {"command": command, "cwd": str(cwd), "status": "pass", "returncode": 0}

    def fake_variant(**_kwargs):
        raise ValueError("candidate junction not found: cluster_c_j")

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "j",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "edge_map": {"teacher_in": "cand_in"},
                    "expanded_rebuild_scope": {
                        "status": "review",
                        "recommended_action": "rebuild_plain_xml_scope",
                        "core_junction_id": "j",
                        "junction_ids": ["c", "j"],
                        "join_junction_ids": ["c", "j"],
                    },
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        command_runner=fake_runner,
        variant_builder=fake_variant,
    )

    assert report["status"] == "fail"
    assert report["attempted_candidate_count"] == 1
    assert report["failed_candidate_count"] == 1
    assert report["variant_reports"][0]["status"] == "fail"
    assert report["variant_reports"][0]["exception_type"] == "ValueError"
    assert "candidate junction not found" in report["variant_reports"][0]["reason"]


def test_run_teacher_guided_repair_queue_fails_when_parity_fails(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")

    def fake_variant(**kwargs):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "parity_gate_status": "fail",
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "cluster_a_b",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                },
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        variant_builder=fake_variant,
    )

    assert report["status"] == "fail"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["parity_gate_status"] == "fail"


def test_run_teacher_guided_repair_queue_summarizes_semantic_failures(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")

    def fake_variant(**kwargs):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "parity_gate_status": "fail",
            "semantic_replay_gate": {
                "status": "fail",
                "failures": [
                    {"report": "parity", "field": "approach_endpoint_signature_mismatch_count", "count": 1},
                    {"report": "parity", "field": "crossing_count", "count": -4},
                    {"report": "parity", "field": "tl_type_mismatch_count", "count": 1},
                ],
            },
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "cluster_a_b",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                },
                {
                    "junction_id": "cluster_c_d",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                },
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        variant_builder=fake_variant,
    )

    assert report["semantic_failure_counts"] == {
        "parity:approach_endpoint_signature_mismatch_count": 2,
        "parity:crossing_count": 2,
        "parity:tl_type_mismatch_count": 2,
    }
    assert report["approach_integrity_status"] == "fail"
    assert report["approach_integrity_failure_counts"] == {
        "parity:approach_endpoint_signature_mismatch_count": 2,
    }


def test_run_teacher_guided_repair_queue_writes_promotion_gate_artifact(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    final_net = tmp_path / "run" / "candidate_001" / "final.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")

    def fake_variant(**kwargs):
        final_net.parent.mkdir(parents=True, exist_ok=True)
        final_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_id": kwargs["junction_id"],
            "final_net_file": str(final_net),
            "parity_gate_status": "pass",
            "semantic_layer_gates": {
                "topology": {"status": "pass", "failure_count": 0, "failures": []},
                "movement_tls": {"status": "pass", "failure_count": 0, "failures": []},
                "pedestrian_bike": {"status": "pass", "failure_count": 0, "failures": []},
                "internal": {"status": "pass", "failure_count": 0, "failures": []},
                "uncategorized": {"status": "pass", "failure_count": 0, "failures": []},
            },
        }

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "reference_id": "teacher_j",
                    "junction_id": "cluster_a_b",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                }
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        variant_builder=fake_variant,
    )

    gate = json.loads(Path(report["promotion_gate_file"]).read_text(encoding="utf-8"))
    assert report["promotion_gate_status"] == "pass"
    assert gate["status"] == "pass"
    assert gate["claim_status"] == "diagnostic-demo"
    assert gate["candidate_count"] == 1
    assert gate["pass_candidate_count"] == 1
    assert gate["items"] == [
        {
            "junction_id": "cluster_a_b",
            "teacher_junction_id": "teacher_j",
            "status": "pass",
            "parity_gate_status": "pass",
            "final_net_file": str(final_net),
            "semantic_layer_gates": {
                "topology": {"status": "pass", "failure_count": 0, "failures": []},
                "movement_tls": {"status": "pass", "failure_count": 0, "failures": []},
                "pedestrian_bike": {"status": "pass", "failure_count": 0, "failures": []},
                "internal": {"status": "pass", "failure_count": 0, "failures": []},
                "uncategorized": {"status": "pass", "failure_count": 0, "failures": []},
            },
        }
    ]


def test_run_teacher_guided_repair_queue_resolves_relative_queue_paths(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    teacher_net = queue_dir / "teacher.net.xml"
    candidate_net = queue_dir / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")
    calls = []

    def fake_variant(**kwargs):
        calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": "teacher.net.xml",
            "candidate_net_file": "candidate.net.xml",
            "repair_candidates": [
                {
                    "junction_id": "cluster_a_b",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                },
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        queue_base_dir=queue_dir,
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert calls[0]["teacher_net_file"] == teacher_net
    assert calls[0]["candidate_net_file"] == candidate_net


def test_run_teacher_guided_repair_queue_uses_short_output_names_for_long_junction_ids(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")
    long_junction_id = "cluster_" + "_".join(str(1000000000 + index) for index in range(20))
    calls = []

    def fake_variant(**kwargs):
        calls.append(kwargs)
        return {"status": "pass", "claim_status": "diagnostic-demo", "parity_gate_status": "pass"}

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": long_junction_id,
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": "cand_in"},
                },
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        prefix="probe",
        variant_builder=fake_variant,
    )

    assert report["status"] == "pass"
    assert calls[0]["junction_id"] == long_junction_id
    assert len(calls[0]["output_dir"].name) <= 24
    assert len(calls[0]["prefix"]) <= 16
    assert long_junction_id not in calls[0]["prefix"]


def test_run_teacher_guided_repair_queue_skips_invalid_edge_map(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_edges = tmp_path / "raw.edg.xml"
    raw_connections = tmp_path / "raw.con.xml"
    teacher_net = tmp_path / "teacher.net.xml"
    candidate_net = tmp_path / "candidate.net.xml"
    for path in (raw_nodes, raw_edges, raw_connections, teacher_net, candidate_net):
        path.write_text("<xml/>", encoding="utf-8")

    def fail_if_called(**_kwargs):
        raise AssertionError("variant builder must not run for malformed edge maps")

    report = run_teacher_guided_repair_queue(
        queue_report={
            "teacher_net_file": str(teacher_net),
            "candidate_net_file": str(candidate_net),
            "repair_candidates": [
                {
                    "junction_id": "cluster_a_b",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_in": ["cand_in"]},
                },
            ],
        },
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        output_dir=tmp_path / "run",
        variant_builder=fail_if_called,
    )

    assert report["status"] == "blocked"
    assert report["skipped_candidates"][0]["candidate_status"] == "invalid_edge_map"


def test_write_teacher_connection_plan_preserves_non_target_and_blocks_unlisted_targets(tmp_path: Path) -> None:
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="other_in" to="other_out" fromLane="0" toLane="0"/>
  <connection from="cand_in" to="old_out" fromLane="0" toLane="0"/>
  <crossing node="j" edges="old_edge"/>
</connections>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "vehicle_connections": [{"from": "teacher_in", "to": "teacher_out", "fromLane": "1", "toLane": "0"}],
        "crossings": [{"edge_id": ":j_c0", "crossingEdges": ["teacher_out"]}],
    }
    candidate_model = {
        "approaches": {
            "incoming": [{"edge_id": "cand_in", "lane_count": 2}],
            "outgoing": [{"edge_id": "cand_out", "lane_count": 1}, {"edge_id": "old_out", "lane_count": 1}],
        }
    }

    report = write_teacher_connection_plan(
        raw_connection_file=raw_connections,
        output_file=tmp_path / "teacher.con.xml",
        junction_id="j",
        teacher_model=teacher_model,
        candidate_model=candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["connection_file"]).getroot()
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("connection")] == [
        ("other_in", "other_out"),
        ("cand_in", "cand_out"),
    ]
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("delete")] == [("cand_in", "old_out")]
    assert root.find("crossing").attrib["edges"] == "cand_out"
    assert report["kept_non_target_children"] == 1
    assert report["removed_target_children"] == 2


def test_write_teacher_connection_plan_preserves_neighbor_connections_on_shared_boundary_edges(tmp_path: Path) -> None:
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="prev" to="cand_in" fromLane="0" toLane="0"/>
  <connection from="cand_in" to="old_out" fromLane="0" toLane="0"/>
  <connection from="cand_out" to="next" fromLane="0" toLane="0"/>
</connections>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "vehicle_connections": [{"from": "teacher_in", "to": "teacher_out", "fromLane": "0", "toLane": "0"}],
        "crossings": [],
    }
    candidate_model = {
        "approaches": {
            "incoming": [{"edge_id": "cand_in", "lane_count": 1}],
            "outgoing": [{"edge_id": "cand_out", "lane_count": 1}, {"edge_id": "old_out", "lane_count": 1}],
        }
    }

    report = write_teacher_connection_plan(
        raw_connection_file=raw_connections,
        output_file=tmp_path / "teacher.con.xml",
        junction_id="j",
        teacher_model=teacher_model,
        candidate_model=candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["connection_file"]).getroot()
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("connection")] == [
        ("prev", "cand_in"),
        ("cand_out", "next"),
        ("cand_in", "cand_out"),
    ]
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("delete")] == [("cand_in", "old_out")]
    assert report["kept_non_target_children"] == 2
    assert report["removed_target_children"] == 1


def test_write_teacher_connection_plan_marks_teacher_uncontrolled_movements(tmp_path: Path) -> None:
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_model = {
        "vehicle_connections": [
            {"from": "teacher_in", "to": "teacher_out", "fromLane": "0", "toLane": "0", "tl": "j"},
            {"from": "teacher_bike", "to": "teacher_path", "fromLane": "0", "toLane": "0", "tl": ""},
        ],
        "crossings": [],
    }
    candidate_model = {
        "approaches": {
            "incoming": [{"edge_id": "cand_in", "lane_count": 1}, {"edge_id": "cand_bike", "lane_count": 1}],
            "outgoing": [{"edge_id": "cand_out", "lane_count": 1}, {"edge_id": "cand_path", "lane_count": 1}],
        }
    }

    report = write_teacher_connection_plan(
        raw_connection_file=raw_connections,
        output_file=tmp_path / "teacher.con.xml",
        junction_id="j",
        teacher_model=teacher_model,
        candidate_model=candidate_model,
        edge_map={
            "teacher_in": "cand_in",
            "teacher_out": "cand_out",
            "teacher_bike": "cand_bike",
            "teacher_path": "cand_path",
        },
    )

    connections = ET.parse(report["connection_file"]).getroot().findall("connection")
    attrs_by_pair = {(item.attrib["from"], item.attrib["to"]): item.attrib for item in connections}
    assert "uncontrolled" not in attrs_by_pair[("cand_in", "cand_out")]
    assert attrs_by_pair[("cand_bike", "cand_path")]["uncontrolled"] == "true"
    assert report["emitted_uncontrolled_connection_count"] == 1


def test_write_teacher_connection_plan_skips_teacher_connections_via_other_internal_scope(
    tmp_path: Path,
) -> None:
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    teacher_model = {
        "vehicle_connections": [
            {
                "from": "teacher_in",
                "to": "teacher_out",
                "fromLane": "0",
                "toLane": "0",
                "via": ":teacher_j_0_0",
            },
            {
                "from": "teacher_out",
                "to": "teacher_back",
                "fromLane": "0",
                "toLane": "0",
                "via": ":neighbor_j_0_0",
            },
        ],
        "crossings": [],
    }
    candidate_model = {
        "approaches": {
            "incoming": [{"edge_id": "cand_in", "lane_count": 1}, {"edge_id": "cand_back", "lane_count": 1}],
            "outgoing": [{"edge_id": "cand_out", "lane_count": 1}],
        }
    }

    report = write_teacher_connection_plan(
        raw_connection_file=raw_connections,
        output_file=tmp_path / "teacher.con.xml",
        junction_id="candidate_j",
        teacher_model=teacher_model,
        candidate_model=candidate_model,
        edge_map={
            "teacher_in": "cand_in",
            "teacher_out": "cand_out",
            "teacher_back": "cand_back",
        },
        teacher_internal_scope_id="teacher_j",
    )

    root = ET.parse(report["connection_file"]).getroot()
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("connection")] == [
        ("cand_in", "cand_out")
    ]
    assert ("cand_out", "cand_back") not in [(item.attrib["from"], item.attrib["to"]) for item in root.findall("delete")]
    assert report["skipped_off_scope_internal_connection_count"] == 1


def test_write_teacher_connection_plan_can_use_patched_edge_lane_counts(tmp_path: Path) -> None:
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    candidate_edges = tmp_path / "candidate.edg.xml"
    candidate_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j">
    <lane index="0"/>
    <lane index="1"/>
  </edge>
  <edge id="cand_out" from="j" to="b">
    <lane index="0"/>
    <lane index="1"/>
  </edge>
</edges>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "vehicle_connections": [{"from": "teacher_in", "to": "teacher_out", "fromLane": "1", "toLane": "1", "tl": "j"}],
        "crossings": [],
    }
    stale_candidate_model = {
        "approaches": {
            "incoming": [{"edge_id": "cand_in", "lane_count": 1}],
            "outgoing": [{"edge_id": "cand_out", "lane_count": 1}],
        }
    }

    report = write_teacher_connection_plan(
        raw_connection_file=raw_connections,
        output_file=tmp_path / "teacher.con.xml",
        junction_id="j",
        teacher_model=teacher_model,
        candidate_model=stale_candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        candidate_edge_file=candidate_edges,
    )

    connection = ET.parse(report["connection_file"]).getroot().find("connection")
    assert connection.attrib["fromLane"] == "1"
    assert connection.attrib["toLane"] == "1"
    assert report["lane_clamp_count"] == 0


def test_write_teacher_connection_plan_ignores_edges_missing_from_patched_edge_file(tmp_path: Path) -> None:
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="stale_in" to="stale_out" fromLane="0" toLane="0"/>
  <connection from="ghost" to="other" fromLane="0" toLane="0"/>
</connections>
""",
        encoding="utf-8",
    )
    candidate_edges = tmp_path / "candidate.edg.xml"
    candidate_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane index="0"/></edge>
  <edge id="other" from="x" to="y"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "vehicle_connections": [{"from": "teacher_in", "to": "teacher_out", "fromLane": "0", "toLane": "0"}],
        "crossings": [],
    }
    stale_candidate_model = {
        "approaches": {
            "incoming": [{"edge_id": "cand_in", "lane_count": 1}, {"edge_id": "stale_in", "lane_count": 1}],
            "outgoing": [{"edge_id": "cand_out", "lane_count": 1}, {"edge_id": "stale_out", "lane_count": 1}],
        }
    }

    report = write_teacher_connection_plan(
        raw_connection_file=raw_connections,
        output_file=tmp_path / "teacher.con.xml",
        junction_id="j",
        teacher_model=teacher_model,
        candidate_model=stale_candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        candidate_edge_file=candidate_edges,
    )

    root = ET.parse(report["connection_file"]).getroot()
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("connection")] == [("cand_in", "cand_out")]
    assert root.findall("delete") == []
    assert report["removed_target_children"] == 2


def test_write_teacher_connection_plan_removes_raw_connections_with_invalid_patched_lanes(
    tmp_path: Path,
) -> None:
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <connection from="edge_a" to="edge_b" fromLane="1" toLane="1"/>
  <connection from="edge_b" to="edge_a" fromLane="0" toLane="0"/>
</connections>
""",
        encoding="utf-8",
    )
    candidate_edges = tmp_path / "candidate.edg.xml"
    candidate_edges.write_text(
        """<edges>
  <edge id="edge_a" from="a" to="b"><lane index="0"/></edge>
  <edge id="edge_b" from="b" to="a"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )

    report = write_teacher_connection_plan(
        raw_connection_file=raw_connections,
        output_file=tmp_path / "teacher.con.xml",
        junction_id="j",
        teacher_model={"vehicle_connections": [], "crossings": []},
        candidate_model={"approaches": {"incoming": [], "outgoing": []}},
        edge_map={},
        candidate_edge_file=candidate_edges,
    )

    root = ET.parse(report["connection_file"]).getroot()
    assert [(item.attrib["from"], item.attrib["to"]) for item in root.findall("connection")] == [("edge_b", "edge_a")]
    assert report["removed_invalid_lane_connection_count"] == 1


def test_write_teacher_connection_plan_removes_crossings_with_missing_patched_edges(tmp_path: Path) -> None:
    raw_connections = tmp_path / "raw.con.xml"
    raw_connections.write_text(
        """<connections>
  <crossing node="other_j" edges="ghost other"/>
  <crossing node="kept_j" edges="other"/>
</connections>
""",
        encoding="utf-8",
    )
    candidate_edges = tmp_path / "candidate.edg.xml"
    candidate_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane index="0"/></edge>
  <edge id="other" from="x" to="y"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )

    report = write_teacher_connection_plan(
        raw_connection_file=raw_connections,
        output_file=tmp_path / "teacher.con.xml",
        junction_id="j",
        teacher_model={"vehicle_connections": [], "crossings": []},
        candidate_model={"approaches": {"incoming": [], "outgoing": []}},
        edge_map={},
        candidate_edge_file=candidate_edges,
    )

    root = ET.parse(report["connection_file"]).getroot()
    assert [item.attrib["node"] for item in root.findall("crossing")] == ["kept_j"]
    assert report["removed_target_children"] == 1


def test_write_teacher_lane_patch_edges_copies_lane_permissions_and_geometry_without_replacing_edge_geometry(
    tmp_path: Path,
) -> None:
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand" from="a" to="j" numLanes="1" speed="13.89" shape="0,0 1,0">
    <lane index="0" speed="13.89" shape="0,0 1,0"/>
  </edge>
</edges>
""",
        encoding="utf-8",
    )
    teacher_edges = tmp_path / "teacher.net.xml"
    teacher_edges.write_text(
        """<net>
  <edge id="teacher" from="x" to="j" numLanes="2" speed="13.89" shape="5,5 6,5">
    <lane index="0" allow="pedestrian" width="3.00" speed="13.89" length="1.00" shape="5,5 6,5"/>
    <lane index="1" disallow="pedestrian bicycle" speed="13.89" length="1.50" shape="5,6 6,6" outlineShape="5,5.5 6,5.5"/>
  </edge>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_lane_patch_edges(
        raw_edge_file=raw_edges,
        teacher_edge_file=teacher_edges,
        output_file=tmp_path / "patched.edg.xml",
        edge_map={"teacher": "cand"},
        lane_shape_delta=(-5.0, -5.0),
    )

    edge = ET.parse(report["edge_file"]).getroot().find("edge")
    assert edge.attrib["shape"] == "0,0 1,0"
    assert edge.attrib["numLanes"] == "2"
    lanes = edge.findall("lane")
    assert [lane.attrib.get("allow", "") for lane in lanes] == ["pedestrian", ""]
    assert [lane.attrib.get("disallow", "") for lane in lanes] == ["", "pedestrian bicycle"]
    assert [lane.attrib.get("shape", "") for lane in lanes] == ["0.00,0.00 1.00,0.00", "0.00,1.00 1.00,1.00"]
    assert "length" not in lanes[0].attrib
    assert "outlineShape" not in lanes[1].attrib
    assert report["patched_edge_count"] == 1
    assert report["lane_shape_translation_applied"] is True


def test_write_teacher_lane_patch_edges_adds_missing_mapped_teacher_edge(tmp_path: Path) -> None:
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="in" from="a" to="j"><lane index="0" shape="-10,0 0,0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    teacher_edges = tmp_path / "teacher.net.xml"
    teacher_edges.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="missing_out" from="j" to="b" priority="3" type="highway.secondary" shape="0,0 10,0">
    <lane id="missing_out_0" index="0" speed="13.9" shape="0,0 10,0"/>
  </edge>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_lane_patch_edges(
        raw_edge_file=raw_edges,
        teacher_edge_file=teacher_edges,
        output_file=tmp_path / "patched.edg.xml",
        edge_map={"in": "in", "missing_out": "missing_out"},
    )

    root = ET.parse(report["edge_file"]).getroot()
    missing = root.find("edge[@id='missing_out']")
    assert report["added_missing_mapped_edge_count"] == 1
    assert missing is not None
    assert missing.attrib["type"] == "highway.secondary"
    assert missing.attrib["numLanes"] == "1"
    assert missing.find("lane").attrib == {"index": "0", "speed": "13.9", "shape": "0,0 10,0"}


def test_write_teacher_lane_patch_edges_translates_added_edge_shape_when_lane_shapes_not_preserved(
    tmp_path: Path,
) -> None:
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text("<edges/>\n", encoding="utf-8")
    teacher_edges = tmp_path / "teacher.net.xml"
    teacher_edges.write_text(
        """<net>
  <edge id="missing_path" from="teacher_j" to="outside" shape="100,200 110,205">
    <lane id="missing_path_0" index="0" shape="100,200 110,205"/>
  </edge>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_lane_patch_edges(
        raw_edge_file=raw_edges,
        teacher_edge_file=teacher_edges,
        output_file=tmp_path / "patched.edg.xml",
        edge_map={"missing_path": "missing_path"},
        junction_id="candidate_j",
        teacher_junction_id="teacher_j",
        boundary_node_ids={"candidate_j"},
        lane_shape_delta=(-90.0, -180.0),
        preserve_lane_shapes=False,
    )

    missing = ET.parse(report["edge_file"]).getroot().find("edge[@id='missing_path']")
    assert missing is not None
    assert missing.attrib["from"] == "candidate_j"
    assert missing.attrib["shape"] == "10.00,20.00 20.00,25.00"
    assert "shape" not in missing.find("lane").attrib


def test_write_teacher_lane_patch_edges_rebases_missing_mapped_teacher_edge_to_join_source(
    tmp_path: Path,
) -> None:
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="in_left" from="a" to="j1"><lane index="0"/></edge>
  <edge id="in_right" from="b" to="j2"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    teacher_edges = tmp_path / "teacher.net.xml"
    teacher_edges.write_text(
        """<net>
  <edge id="missing_out" from="teacher_j" to="downstream" type="highway.secondary">
    <lane id="missing_out_0" index="0" speed="13.9"/>
  </edge>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_lane_patch_edges(
        raw_edge_file=raw_edges,
        teacher_edge_file=teacher_edges,
        output_file=tmp_path / "patched.edg.xml",
        edge_map={"missing_out": "missing_out"},
        junction_id="cluster_j1_j2",
        teacher_junction_id="teacher_j",
        boundary_node_ids={"j2", "j1"},
    )

    missing = ET.parse(report["edge_file"]).getroot().find("edge[@id='missing_out']")
    assert missing is not None
    assert missing.attrib["from"] == "j1"
    assert missing.attrib["to"] == "downstream"
    assert report["rebased_missing_mapped_edge_count"] == 1
    assert report["rebased_missing_mapped_edges"] == [
        {
            "candidate_edge_id": "missing_out",
            "teacher_edge_id": "missing_out",
            "from": {"teacher": "teacher_j", "candidate": "j1"},
        }
    ]


def test_write_teacher_lane_patch_edges_skips_rebased_self_loop_missing_mapped_edge(
    tmp_path: Path,
) -> None:
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="in_left" from="a" to="j1"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    teacher_edges = tmp_path / "teacher.net.xml"
    teacher_edges.write_text(
        """<net>
  <edge id="absorbed_split" from="teacher_j" to="j1" type="highway.service">
    <lane id="absorbed_split_0" index="0" speed="5.6"/>
  </edge>
  <edge id="missing_out" from="teacher_j" to="downstream" type="highway.secondary">
    <lane id="missing_out_0" index="0" speed="13.9"/>
  </edge>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_lane_patch_edges(
        raw_edge_file=raw_edges,
        teacher_edge_file=teacher_edges,
        output_file=tmp_path / "patched.edg.xml",
        edge_map={"absorbed_split": "absorbed_split", "missing_out": "missing_out"},
        junction_id="cluster_j1_j2",
        teacher_junction_id="teacher_j",
        boundary_node_ids={"j2", "j1"},
    )

    root = ET.parse(report["edge_file"]).getroot()
    assert root.find("edge[@id='absorbed_split']") is None
    missing = root.find("edge[@id='missing_out']")
    assert missing is not None
    assert missing.attrib["from"] == "j1"
    assert missing.attrib["to"] == "downstream"
    assert report["added_missing_mapped_edge_count"] == 1
    assert report["skipped_rebased_self_loop_edge_count"] == 1
    assert report["skipped_rebased_self_loop_edges"] == [
        {"candidate_edge_id": "absorbed_split", "teacher_edge_id": "absorbed_split", "node": "j1"}
    ]


def test_write_teacher_endpoint_patch_nodes_adds_translated_missing_edge_endpoints(tmp_path: Path) -> None:
    raw_nodes = tmp_path / "raw.nod.xml"
    raw_nodes.write_text(
        """<nodes>
  <node id="a" x="-10" y="20"/>
  <node id="j" x="10" y="20"/>
</nodes>""",
        encoding="utf-8",
    )
    patched_edges = tmp_path / "patched.edg.xml"
    patched_edges.write_text(
        """<edges>
  <edge id="in" from="a" to="j"><lane index="0"/></edge>
  <edge id="missing_out" from="j" to="teacher_exit"><lane index="0"/></edge>
</edges>""",
        encoding="utf-8",
    )
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <junction id="j" type="priority" x="100" y="200"/>
  <junction id="teacher_exit" type="priority" x="120" y="205" incLanes="missing_out_0" intLanes="" shape="119,204 121,204"/>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_endpoint_patch_nodes(
        raw_node_file=raw_nodes,
        teacher_net_file=teacher_net,
        edge_file=patched_edges,
        output_file=tmp_path / "patched.nod.xml",
        lane_shape_delta=(-90.0, -180.0),
    )

    root = ET.parse(report["node_file"]).getroot()
    assert report["added_missing_endpoint_node_ids"] == ["teacher_exit"]
    assert report["unresolved_missing_endpoint_node_ids"] == []
    node = root.find("node[@id='teacher_exit']")
    assert node is not None
    assert node.attrib == {
        "id": "teacher_exit",
        "x": "30.00",
        "y": "25.00",
        "type": "priority",
        "shape": "29.00,24.00 31.00,24.00",
    }


def test_write_teacher_lane_patch_edges_prunes_unmapped_target_boundary_edges(tmp_path: Path) -> None:
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j" numLanes="1"><lane index="0"/></edge>
  <edge id="same_support" from="j" to="p" numLanes="1"><lane index="0"/></edge>
  <edge id="cand_remapped" from="j" to="z" numLanes="1"><lane index="0"/></edge>
  <edge id="teacher_remapped" from="j" to="z" numLanes="1"><lane index="0"/></edge>
  <edge id="extra_in" from="x" to="j" numLanes="1"><lane index="0"/></edge>
  <edge id="extra_out" from="j" to="y" numLanes="1"><lane index="0"/></edge>
  <edge id="other" from="x" to="y" numLanes="1"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    teacher_edges = tmp_path / "teacher.net.xml"
    teacher_edges.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j" numLanes="2">
    <lane index="0" speed="13.89"/>
    <lane index="1" speed="13.89"/>
  </edge>
  <edge id="same_support" from="j" to="p" numLanes="1"><lane index="0"/></edge>
  <edge id="teacher_remapped" from="j" to="z" numLanes="1"><lane index="0"/></edge>
  <edge id="extra_out" from="q" to="r" numLanes="1"><lane index="0"/></edge>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_lane_patch_edges(
        raw_edge_file=raw_edges,
        teacher_edge_file=teacher_edges,
        output_file=tmp_path / "patched.edg.xml",
        edge_map={"teacher_in": "cand_in", "teacher_remapped": "cand_remapped"},
        junction_id="j",
        prune_unmapped_boundary_edges=True,
    )

    root = ET.parse(report["edge_file"]).getroot()
    edge_ids = [edge.attrib["id"] for edge in root.findall("edge")]
    assert edge_ids == ["cand_in", "same_support", "cand_remapped", "other"]
    assert root.find("edge[@id='cand_in']").attrib["numLanes"] == "2"
    assert report["patched_edge_count"] == 2
    assert report["pruned_boundary_edges"] == ["teacher_remapped", "extra_in", "extra_out"]


def test_write_teacher_lane_patch_edges_prunes_edges_touching_join_source_nodes(tmp_path: Path) -> None:
    raw_edges = tmp_path / "raw.edg.xml"
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j1" numLanes="1"><lane index="0"/></edge>
  <edge id="cand_out" from="j2" to="b" numLanes="1"><lane index="0"/></edge>
  <edge id="teacher_out" from="j1" to="x" numLanes="1"><lane index="0"/></edge>
  <edge id="other" from="x" to="y" numLanes="1"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    teacher_edges = tmp_path / "teacher.net.xml"
    teacher_edges.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="cluster_j1_j2" numLanes="1"><lane index="0"/></edge>
  <edge id="teacher_out" from="cluster_j1_j2" to="b" numLanes="1"><lane index="0"/></edge>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_lane_patch_edges(
        raw_edge_file=raw_edges,
        teacher_edge_file=teacher_edges,
        output_file=tmp_path / "patched.edg.xml",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        junction_id="cluster_j1_j2",
        boundary_node_ids={"j1", "j2"},
        prune_unmapped_boundary_edges=True,
    )

    edge_ids = [edge.attrib["id"] for edge in ET.parse(report["edge_file"]).getroot().findall("edge")]
    assert edge_ids == ["cand_in", "cand_out", "other"]
    assert report["pruned_boundary_edges"] == ["teacher_out"]


def test_write_teacher_pedestrian_ring_net_replays_teacher_ring_and_removes_extra_walkingareas(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0"/></edge>
  <edge id="cand_ped" from="p" to="j"><lane id="cand_ped_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_cA" function="crossing" crossingEdges="cand_in"><lane id=":j_cA_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_cB" function="crossing" crossingEdges="cand_out"><lane id=":j_cB_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_wKeep0" function="walkingarea"><lane id=":j_wKeep0_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_wKeep1" function="walkingarea"><lane id=":j_wKeep1_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_wExtra" function="walkingarea"><lane id=":j_wExtra_0" index="0" allow="pedestrian"/></edge>
  <junction id="j" incLanes="cand_in_0 :j_wKeep0_0 :j_wKeep1_0 :j_wExtra_0" intLanes=":j_cA_0 :j_cB_0 :j_wKeep0_0 :j_wKeep1_0 :j_wExtra_0"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="GrG"/></tlLogic>
  <connection from=":j_wKeep1" to=":j_cA" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="s" state="M"/>
  <connection from=":j_wKeep0" to=":j_cB" fromLane="0" toLane="0" tl="j" linkIndex="2" dir="s" state="M"/>
  <connection from=":j_cA" to=":j_wExtra" fromLane="0" toLane="0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "crossings": [
            {"edge_id": ":j_c0", "crossingEdges": ["teacher_in"]},
            {"edge_id": ":j_c1", "crossingEdges": ["teacher_out"]},
        ],
        "pedestrian_connections": [
            {"from": ":j_c0", "to": ":j_w0", "fromLane": "0", "toLane": "0", "dir": "s", "state": "M"},
            {"from": ":j_w1", "to": ":j_c0", "fromLane": "0", "toLane": "0", "tl": "j", "linkIndex": "1", "dir": "s", "state": "M"},
            {"from": ":j_c1", "to": ":j_w1", "fromLane": "0", "toLane": "0", "dir": "s", "state": "M"},
            {"from": ":j_w0", "to": ":j_c1", "fromLane": "0", "toLane": "0", "tl": "j", "linkIndex": "2", "dir": "s", "state": "M"},
            {"from": "teacher_ped", "to": ":j_w0", "fromLane": "0", "toLane": "0", "dir": "s", "state": "M"},
        ],
    }

    report = write_teacher_pedestrian_ring_net(
        candidate_net_file=candidate_net,
        output_file=tmp_path / "pedring.net.xml",
        junction_id="j",
        teacher_model=teacher_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out", "teacher_ped": "cand_ped"},
    )

    root = ET.parse(report["net_file"]).getroot()
    assert root.find("edge[@id=':j_wExtra']") is None
    assert report["kept_walkingarea_count"] == 2
    assert report["inserted_pedestrian_connection_count"] == 5
    assert report["skipped_pedestrian_connection_count"] == 0
    assert all(":j_wExtra" not in " ".join(item.attrib.values()) for item in root.findall("connection"))
    junction = root.find("junction[@id='j']")
    assert ":j_wExtra_0" not in junction.attrib["incLanes"]
    assert ":j_wExtra_0" not in junction.attrib["intLanes"]


def test_write_teacher_pedestrian_ring_net_copies_uncontrolled_teacher_walkingareas(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0"/></edge>
  <edge id=":j_c0" function="crossing" crossingEdges="cand_in"><lane id=":j_c0_0" index="0" allow="pedestrian"/></edge>
  <junction id="j" x="10" y="20" incLanes="cand_in_0" intLanes=":j_c0_0"/>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0" via=":j_0_0"/>
</net>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "junction": {"id": "teacher_j", "x": "1", "y": "2"},
        "crossings": [
            {
                "edge_id": ":teacher_j_c0",
                "crossingEdges": ["teacher_in"],
                "lanes": [{"id": ":teacher_j_c0_0", "index": "0", "allow": "pedestrian", "shape": "1,2 3,2"}],
            }
        ],
        "walking_areas": [
            {
                "edge_id": ":teacher_j_w0",
                "function": "walkingarea",
                "lanes": [
                    {
                        "id": ":teacher_j_w0_0",
                        "index": "0",
                        "allow": "pedestrian",
                        "speed": "2.78",
                        "length": "3.00",
                        "width": "4.00",
                        "shape": "1,2 2,3",
                    }
                ],
            }
        ],
        "pedestrian_connections": [
            {"from": ":teacher_j_c0", "to": ":teacher_j_w0", "fromLane": "0", "toLane": "0", "dir": "s", "state": "M"},
            {"from": ":teacher_j_w0", "to": "teacher_out", "fromLane": "0", "toLane": "0", "dir": "s", "state": "M"},
        ],
    }

    report = write_teacher_pedestrian_ring_net(
        candidate_net_file=candidate_net,
        output_file=tmp_path / "pedring.net.xml",
        junction_id="j",
        teacher_junction_id="teacher_j",
        teacher_model=teacher_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    walkingarea = root.find("edge[@id=':j_w0']")
    crossing = root.find("edge[@id=':j_c0']")
    assert walkingarea is not None
    assert crossing is not None
    assert crossing.find("lane").attrib["shape"] == "10.00,20.00 12.00,20.00"
    assert walkingarea.attrib["function"] == "walkingarea"
    assert walkingarea.find("lane").attrib["shape"] == "10.00,20.00 11.00,21.00"
    assert report["copied_walkingarea_count"] == 1
    assert report["inserted_pedestrian_connection_count"] == 2
    assert report["skipped_pedestrian_connection_count"] == 0
    junction = root.find("junction[@id='j']")
    assert ":j_w0_0" in junction.attrib["incLanes"]


def test_write_teacher_tllogic_net_replaces_only_target_program(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="Gr"/></tlLogic>
  <tlLogic id="other" type="static" programID="0" offset="0"><phase duration="1" state="r"/></tlLogic>
  <connection from="a" to="b" tl="j" linkIndex="0"/>
  <connection from="c" to="d" tl="j" linkIndex="1"/>
</net>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "traffic_light": {
            "attributes": {"id": "j", "type": "actuated", "programID": "0", "offset": "0"},
            "phases": [{"duration": "3", "state": "GG"}, {"duration": "4", "state": "rr"}],
        }
    }

    report = write_teacher_tllogic_net(
        candidate_net_file=candidate_net,
        output_file=tmp_path / "teacher_tls.net.xml",
        junction_id="j",
        teacher_model=teacher_model,
    )

    root = ET.parse(report["net_file"]).getroot()
    target_tls = root.find("tlLogic[@id='j']")
    assert target_tls.attrib["type"] == "actuated"
    assert [phase.attrib["state"] for phase in target_tls.findall("phase")] == ["GG", "rr"]
    assert root.find("tlLogic[@id='other']").attrib["type"] == "static"
    assert report["tl_phase_count"] == 2
    assert report["controlled_link_count"] == 2


def test_write_teacher_tllogic_net_moves_existing_late_program_before_connections(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <junction id="j" type="traffic_light"/>
  <connection from="a" to="b" tl="j" linkIndex="0"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="r"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "traffic_light": {
            "attributes": {"id": "j", "type": "actuated", "programID": "0", "offset": "0"},
            "phases": [{"duration": "30", "state": "G"}],
        }
    }

    report = write_teacher_tllogic_net(
        candidate_net_file=candidate_net,
        output_file=tmp_path / "teacher_tls.net.xml",
        junction_id="j",
        teacher_model=teacher_model,
    )

    children = [child.tag for child in ET.parse(report["net_file"]).getroot()]
    assert report["status"] == "pass"
    assert children.index("tlLogic") < children.index("connection")


def test_write_teacher_tllogic_net_inserts_missing_target_program(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <tlLogic id="other" type="static" programID="0" offset="0"><phase duration="1" state="r"/></tlLogic>
  <connection from="a" to="b" tl="j" linkIndex="0"/>
</net>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "traffic_light": {
            "attributes": {"id": "teacher_j", "type": "actuated", "programID": "0", "offset": "5"},
            "phases": [{"duration": "30", "minDur": "10", "maxDur": "60", "state": "G"}],
        }
    }

    report = write_teacher_tllogic_net(
        candidate_net_file=candidate_net,
        output_file=tmp_path / "teacher_tls.net.xml",
        junction_id="j",
        teacher_model=teacher_model,
    )

    root = ET.parse(report["net_file"]).getroot()
    target_tls = root.find("tlLogic[@id='j']")
    assert report["status"] == "pass"
    assert target_tls.attrib == {"id": "j", "type": "actuated", "programID": "0", "offset": "5"}
    assert target_tls.find("phase").attrib == {"duration": "30", "minDur": "10", "maxDur": "60", "state": "G"}
    assert root.find("tlLogic[@id='other']").attrib["type"] == "static"
    assert report["controlled_link_count"] == 1


def test_write_teacher_tllogic_net_inserts_missing_program_before_connections(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <junction id="j" type="traffic_light"/>
  <connection from="a" to="b" tl="j" linkIndex="0"/>
</net>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "traffic_light": {
            "attributes": {"id": "j", "type": "actuated", "programID": "0", "offset": "0"},
            "phases": [{"duration": "30", "state": "G"}],
        }
    }

    report = write_teacher_tllogic_net(
        candidate_net_file=candidate_net,
        output_file=tmp_path / "teacher_tls.net.xml",
        junction_id="j",
        teacher_model=teacher_model,
    )

    children = [child.tag for child in ET.parse(report["net_file"]).getroot()]
    assert report["status"] == "pass"
    assert children.index("tlLogic") < children.index("connection")


def test_write_teacher_tllogic_net_allows_no_teacher_program(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="Gr"/></tlLogic>
  <tlLogic id="other" type="static" programID="0" offset="0"><phase duration="1" state="r"/></tlLogic>
  <connection from="a" to="b" tl="j" linkIndex="0"/>
  <connection from="c" to="d" tl="other" linkIndex="1"/>
  <connection from="e" to="f" tl="missing" linkIndex="2"/>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_tllogic_net(
        candidate_net_file=candidate_net,
        output_file=tmp_path / "teacher_no_tls.net.xml",
        junction_id="j",
        teacher_model={"traffic_light": {"attributes": {}, "phases": []}},
    )

    root = ET.parse(report["net_file"]).getroot()
    target_connection = root.find("connection[@from='a']")
    assert report["status"] == "pass"
    assert report["tls_replay_status"] == "not_applicable_no_teacher_tllogic"
    assert root.find("tlLogic[@id='j']") is None
    assert root.find("tlLogic[@id='other']").attrib["type"] == "static"
    assert "tl" not in target_connection.attrib
    assert "linkIndex" not in target_connection.attrib
    assert target_connection.attrib["uncontrolled"] == "true"
    dangling_connection = root.find("connection[@from='e']")
    assert "tl" not in dangling_connection.attrib
    assert "linkIndex" not in dangling_connection.attrib
    assert dangling_connection.attrib["uncontrolled"] == "true"
    assert root.find("connection[@from='c']").attrib["tl"] == "other"
    assert report["tl_phase_count"] == 0
    assert report["controlled_link_count"] == 0
    assert report["removed_controlled_link_count"] == 2


def test_write_teacher_vehicle_connection_attrs_net_preserves_teacher_connection_attrs(tmp_path: Path) -> None:
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out"><lane id="cand_out_0" index="0"/></edge>
  <junction id="candidate_tls" x="10" y="20"/>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0"/>
</net>
""",
        encoding="utf-8",
    )
    teacher_model = {
        "vehicle_connections": [
            {
                "from": "teacher_in",
                "to": "teacher_out",
                "fromLane": "0",
                "toLane": "0",
                "tl": "teacher_tls",
                "linkIndex": "3",
                "linkIndex2": "12",
                "dir": "s",
                "state": "O",
                "pass": "true",
                "uncontrolled": "true",
                "allow": "bicycle",
                "disallow": "truck",
                "keepClear": "0",
                "contPos": "43.00",
                "shape": "100,200 101,201",
            }
        ],
        "junction": {"x": "100", "y": "200"},
    }

    report = write_teacher_vehicle_connection_attrs_net(
        candidate_net_file=candidate_net,
        output_file=tmp_path / "attrs.net.xml",
        junction_id="candidate_tls",
        teacher_model=teacher_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    connection = ET.parse(report["net_file"]).getroot().find("connection")
    assert connection.attrib["tl"] == "candidate_tls"
    assert connection.attrib["linkIndex"] == "3"
    assert connection.attrib["linkIndex2"] == "12"
    assert connection.attrib["dir"] == "s"
    assert connection.attrib["state"] == "O"
    assert connection.attrib["pass"] == "true"
    assert connection.attrib["uncontrolled"] == "true"
    assert connection.attrib["allow"] == "bicycle"
    assert connection.attrib["disallow"] == "truck"
    assert connection.attrib["keepClear"] == "0"
    assert connection.attrib["contPos"] == "43.00"
    assert connection.attrib["shape"] == "10.00,20.00 11.00,21.00"


def test_teacher_parity_counts_only_target_tls_controlled_links() -> None:
    teacher_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [
            {"from": "a", "to": "b", "tl": "external_tls", "linkIndex": "1"},
            {"from": "a", "to": "c", "tl": "j", "linkIndex": "2"},
        ],
        "pedestrian_connections": [],
        "traffic_light": {"phases": []},
    }
    candidate_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [{"from": "a", "to": "c", "tl": "j", "linkIndex": "2"}],
        "pedestrian_connections": [],
        "traffic_light": {"phases": []},
    }

    parity = _compare_teacher_models(teacher_model, candidate_model)

    assert parity["teacher"]["controlled_vehicle_link_count"] == 1
    assert parity["candidate"]["controlled_vehicle_link_count"] == 1
    assert parity["delta"]["controlled_vehicle_link_count"] == 0


def test_teacher_parity_counts_referenced_tls_id_controlled_links() -> None:
    teacher_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [{"from": "a", "to": "b", "tl": "cluster_tls", "linkIndex": "1"}],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "cluster_tls"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [{"from": "a", "to": "b", "tl": "cluster_tls", "linkIndex": "1"}],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "cluster_tls"}, "phases": []},
    }

    parity = _compare_teacher_models(teacher_model, candidate_model)

    assert parity["teacher"]["controlled_vehicle_link_count"] == 1
    assert parity["candidate"]["controlled_vehicle_link_count"] == 1
    assert parity["delta"]["controlled_vehicle_link_count"] == 0


def test_teacher_parity_reports_vehicle_movement_matrix_completeness_delta() -> None:
    teacher_model = {
        "junction_id": "j",
        "summary": {
            "incoming_vehicle_edge_count": 4,
            "outgoing_vehicle_edge_count": 4,
            "vehicle_connection_count": 16,
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"phases": []},
    }
    candidate_model = {
        "junction_id": "j",
        "summary": {
            "incoming_vehicle_edge_count": 4,
            "outgoing_vehicle_edge_count": 4,
            "vehicle_connection_count": 4,
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"phases": []},
    }

    parity = _compare_teacher_models(teacher_model, candidate_model)
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["vehicle_movement_matrix_expected_count"] == 16
    assert parity["teacher"]["vehicle_movement_matrix_missing_count"] == 0
    assert parity["candidate"]["vehicle_movement_matrix_expected_count"] == 16
    assert parity["candidate"]["vehicle_movement_matrix_missing_count"] == 12
    assert parity["delta"]["vehicle_movement_matrix_missing_count"] == 12
    assert {
        "report": "parity",
        "field": "vehicle_movement_matrix_missing_count",
        "count": 12,
    } in gate["failures"]


def test_teacher_parity_fails_on_tls_type_mismatch() -> None:
    teacher_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "actuated"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "static"}, "phases": []},
    }

    parity = _compare_teacher_models(teacher_model, candidate_model)

    assert parity["teacher"]["tl_type"] == "actuated"
    assert parity["candidate"]["tl_type"] == "static"
    assert parity["delta"]["tl_type_mismatch_count"] == 1


def test_teacher_parity_fails_on_main_junction_signature_mismatch_after_translation() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "junction": {
            "id": "teacher_j",
            "type": "traffic_light",
            "x": "100",
            "y": "200",
            "incLanes": "teacher_in_0 :teacher_j_0_0",
            "intLanes": ":teacher_j_0_0",
            "shape": "99,199 101,199",
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "junction": {
            "id": "candidate_j",
            "type": "traffic_light",
            "x": "10",
            "y": "20",
            "incLanes": "cand_in_0 :candidate_j_0_0",
            "intLanes": ":candidate_j_0_0",
            "shape": "8,18 12,18",
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["junction_signature"] == (
        "type=traffic_light|incLanes=cand_in_0 :candidate_j_0_0|"
        "intLanes=:candidate_j_0_0|shape=-1.00,-1.00 1.00,-1.00"
    )
    assert parity["candidate"]["junction_signature"] == (
        "type=traffic_light|incLanes=cand_in_0 :candidate_j_0_0|"
        "intLanes=:candidate_j_0_0|shape=-2.00,-2.00 2.00,-2.00"
    )
    assert parity["delta"]["junction_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "junction_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_approach_lane_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "approaches": {
            "incoming": [
                    {
                        "edge_id": "teacher_in",
                        "from": "shared_source",
                        "to": "teacher_j",
                        "type": "highway.primary",
                        "function": "",
                    "lanes": [
                        {
                            "index": "0",
                            "allow": "passenger",
                            "disallow": "pedestrian bicycle",
                            "speed": "13.89",
                            "length": "10.50",
                            "width": "3.20",
                            "shape": "0,0 1,1",
                        }
                    ],
                }
            ],
            "outgoing": [],
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "approaches": {
            "incoming": [
                    {
                        "edge_id": "cand_in",
                        "from": "shared_source",
                        "to": "candidate_j",
                        "type": "highway.primary",
                        "function": "",
                    "lanes": [
                        {
                            "index": "0",
                            "allow": "passenger",
                            "disallow": "pedestrian",
                            "speed": "8.33",
                            "length": "8.50",
                            "width": "3.20",
                            "shape": "0,0 1,1",
                        }
                    ],
                }
            ],
            "outgoing": [],
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["approach_edge_signatures"] == {
        "incoming:cand_in": "from=shared_source|to=candidate_j|type=highway.primary|function=|lanes=0:passenger:pedestrian bicycle:13.89::3.20:0.00,0.00 1.00,1.00:"
    }
    assert parity["candidate"]["approach_edge_signatures"] == {
        "incoming:cand_in": "from=shared_source|to=candidate_j|type=highway.primary|function=|lanes=0:passenger:pedestrian:8.33::3.20:0.00,0.00 1.00,1.00:"
    }
    assert parity["delta"]["approach_edge_signature_mismatch_count"] == 1
    assert "approach_endpoint_signature_mismatch_count" not in parity["delta"]
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "approach_edge_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_normalizes_mapped_approach_shape_by_junction_origin() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "junction": {"id": "teacher_j", "x": "100", "y": "200"},
        "approaches": {
            "incoming": [
                {
                    "edge_id": "teacher_in",
                    "from": "shared_source",
                    "to": "teacher_j",
                    "type": "highway.primary",
                    "function": "",
                    "lanes": [{"index": "0", "speed": "13.89", "shape": "99,199 100,200"}],
                }
            ],
            "outgoing": [],
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "junction": {"id": "candidate_j", "x": "10", "y": "20"},
        "approaches": {
            "incoming": [
                {
                    "edge_id": "cand_in",
                    "from": "shared_source",
                    "to": "candidate_j",
                    "type": "highway.primary",
                    "function": "",
                    "lanes": [{"index": "0", "speed": "13.89", "shape": "9,19 10,20"}],
                }
            ],
            "outgoing": [],
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )

    assert "approach_edge_signature_mismatch_count" not in parity["delta"]
    assert parity["teacher"]["approach_edge_signatures"] == parity["candidate"]["approach_edge_signatures"]


def test_teacher_parity_ignores_approach_lane_length_rounding_when_shape_matches() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "approaches": {
            "incoming": [
                {
                    "edge_id": "teacher_in",
                    "from": "shared_source",
                    "to": "teacher_j",
                    "type": "highway.primary",
                    "function": "",
                    "lanes": [
                        {
                            "index": "0",
                            "allow": "passenger",
                            "speed": "13.89",
                            "length": "80.05",
                            "width": "3.20",
                            "shape": "0,0 80,0",
                        }
                    ],
                }
            ],
            "outgoing": [],
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "approaches": {
            "incoming": [
                {
                    "edge_id": "cand_in",
                    "from": "shared_source",
                    "to": "candidate_j",
                    "type": "highway.primary",
                    "function": "",
                    "lanes": [
                        {
                            "index": "0",
                            "allow": "passenger",
                            "speed": "13.89",
                            "length": "80.06",
                            "width": "3.20",
                            "shape": "0,0 80,0",
                        }
                    ],
                }
            ],
            "outgoing": [],
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )

    assert "approach_edge_signature_mismatch_count" not in parity["delta"]


def test_teacher_parity_fails_on_mapped_approach_endpoint_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "approaches": {
            "incoming": [
                {
                    "edge_id": "teacher_in",
                    "from": "teacher_boundary",
                    "to": "teacher_j",
                    "type": "highway.primary",
                    "lanes": [{"index": "0", "allow": "passenger", "shape": "0,0 1,1"}],
                }
            ]
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "approaches": {
            "incoming": [
                {
                    "edge_id": "cand_in",
                    "from": "candidate_boundary",
                    "to": "candidate_j",
                    "type": "highway.primary",
                    "lanes": [{"index": "0", "allow": "passenger", "shape": "0,0 1,1"}],
                }
            ]
        },
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )

    assert parity["teacher"]["approach_edge_signatures"]["incoming:cand_in"].startswith(
        "from=teacher_boundary|to=candidate_j|"
    )
    assert parity["candidate"]["approach_edge_signatures"]["incoming:cand_in"].startswith(
        "from=candidate_boundary|to=candidate_j|"
    )
    assert parity["teacher"]["approach_endpoint_signatures"] == {"incoming:cand_in": "from=teacher_boundary|to=candidate_j"}
    assert parity["candidate"]["approach_endpoint_signatures"] == {"incoming:cand_in": "from=candidate_boundary|to=candidate_j"}
    assert parity["delta"]["approach_endpoint_signature_mismatch_count"] == 1
    assert parity["delta"]["approach_edge_signature_mismatch_count"] == 1


def test_teacher_parity_fails_on_tls_program_and_offset_mismatch() -> None:
    teacher_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "actuated", "programID": "0", "offset": "0"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "actuated", "programID": "1", "offset": "5"}, "phases": []},
    }

    parity = _compare_teacher_models(teacher_model, candidate_model)
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["tl_programID"] == "0"
    assert parity["candidate"]["tl_programID"] == "1"
    assert parity["teacher"]["tl_offset"] == "0"
    assert parity["candidate"]["tl_offset"] == "5"
    assert parity["delta"]["tl_programID_mismatch_count"] == 1
    assert parity["delta"]["tl_offset_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "tl_offset_mismatch_count", "count": 1},
        {"report": "parity", "field": "tl_programID_mismatch_count", "count": 1},
    ]


def test_teacher_parity_fails_on_tls_phase_state_mismatch() -> None:
    teacher_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "actuated"}, "phases": [{"duration": "30", "state": "Gr"}]},
    }
    candidate_model = {
        "junction_id": "j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "actuated"}, "phases": [{"duration": "30", "state": "rG"}]},
    }

    parity = _compare_teacher_models(teacher_model, candidate_model)
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["tl_phase_signatures"] == ["state=Gr|duration=30|minDur=|maxDur=|next="]
    assert parity["candidate"]["tl_phase_signatures"] == ["state=rG|duration=30|minDur=|maxDur=|next="]
    assert parity["delta"]["tl_phase_signatures_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "tl_phase_signatures_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_request_matrix_mismatch() -> None:
    teacher_model = {
        "junction_id": "j",
        "summary": {"request_count": 1},
        "requests": [{"index": "0", "response": "0", "foes": "10", "cont": "0"}],
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "actuated"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "j",
        "summary": {"request_count": 1},
        "requests": [{"index": "0", "response": "0", "foes": "01", "cont": "0"}],
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"type": "actuated"}, "phases": []},
    }

    parity = _compare_teacher_models(teacher_model, candidate_model)
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["request_signatures"] == ["index=0|response=0|foes=10|cont=0"]
    assert parity["candidate"]["request_signatures"] == ["index=0|response=0|foes=01|cont=0"]
    assert parity["delta"]["request_signatures_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "request_signatures_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_controlled_link_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [
            {
                "from": "teacher_in",
                "to": "teacher_out",
                "fromLane": "0",
                "toLane": "0",
                "via": ":teacher_j_0_0",
                "tl": "teacher_j",
                "linkIndex": "3",
                "dir": "s",
                "state": "O",
            }
        ],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [
            {
                "from": "cand_in",
                "to": "cand_left",
                "fromLane": "0",
                "toLane": "0",
                "via": ":candidate_j_0_0",
                "tl": "candidate_j",
                "linkIndex": "3",
                "dir": "s",
                "state": "O",
            }
        ],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["controlled_vehicle_link_signatures"] == {
        "3": "from=cand_in|to=cand_out|fromLane=0|toLane=0|dir=s|state=O|via=:candidate_j_0_0|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape="
    }
    assert parity["candidate"]["controlled_vehicle_link_signatures"] == {
        "3": "from=cand_in|to=cand_left|fromLane=0|toLane=0|dir=s|state=O|via=:candidate_j_0_0|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape="
    }
    assert parity["delta"]["controlled_vehicle_link_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "controlled_vehicle_link_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_normalizes_controlled_link_shape_by_junction_origin() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "junction": {"x": "100", "y": "200"},
        "summary": {},
        "vehicle_connections": [
            {
                "from": "teacher_in",
                "to": "teacher_out",
                "fromLane": "0",
                "toLane": "0",
                "via": ":teacher_j_0_0",
                "tl": "teacher_j",
                "linkIndex": "3",
                "dir": "s",
                "state": "O",
                "shape": "100,200 101,201",
            }
        ],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "junction": {"x": "10", "y": "20"},
        "summary": {},
        "vehicle_connections": [
            {
                "from": "cand_in",
                "to": "cand_out",
                "fromLane": "0",
                "toLane": "0",
                "via": ":candidate_j_0_0",
                "tl": "candidate_j",
                "linkIndex": "3",
                "dir": "s",
                "state": "O",
                "shape": "10,20 11,21",
            }
        ],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )

    expected = (
        "from=cand_in|to=cand_out|fromLane=0|toLane=0|dir=s|state=O|"
        "via=:candidate_j_0_0|pass=|uncontrolled=|allow=|disallow=|keepClear=|"
        "contPos=|linkIndex2=|shape=0.00,0.00 1.00,1.00"
    )
    assert parity["teacher"]["controlled_vehicle_link_signatures"] == {"3": expected}
    assert parity["candidate"]["controlled_vehicle_link_signatures"] == {"3": expected}
    assert "controlled_vehicle_link_signature_mismatch_count" not in parity["delta"]


def test_teacher_parity_fails_on_duplicate_controlled_link_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [
            {
                "from": "teacher_in",
                "to": "teacher_out",
                "fromLane": "0",
                "toLane": "0",
                "via": ":teacher_j_0_0",
                "tl": "teacher_j",
                "linkIndex": "5",
                "dir": "s",
                "state": "O",
            },
            {
                "from": "teacher_in",
                "to": "teacher_right",
                "fromLane": "1",
                "toLane": "0",
                "via": ":teacher_j_1_0",
                "tl": "teacher_j",
                "linkIndex": "5",
                "dir": "r",
                "state": "O",
            },
        ],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [
            {
                "from": "cand_in",
                "to": "cand_wrong",
                "fromLane": "0",
                "toLane": "0",
                "via": ":candidate_j_0_0",
                "tl": "candidate_j",
                "linkIndex": "5",
                "dir": "s",
                "state": "O",
            },
            {
                "from": "cand_in",
                "to": "cand_right",
                "fromLane": "1",
                "toLane": "0",
                "via": ":candidate_j_1_0",
                "tl": "candidate_j",
                "linkIndex": "5",
                "dir": "r",
                "state": "O",
            },
        ],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out", "teacher_right": "cand_right"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["delta"]["controlled_vehicle_link_count"] == 0
    assert parity["teacher"]["controlled_link_count"] == 2
    assert parity["teacher"]["controlled_link_index_count"] == 1
    assert parity["teacher"]["controlled_duplicate_link_index_count"] == 1
    assert parity["delta"]["controlled_vehicle_link_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "controlled_vehicle_link_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_controlled_link_attribute_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [
            {
                "from": "teacher_in",
                "to": "teacher_out",
                "fromLane": "0",
                "toLane": "0",
                "via": ":teacher_j_0_0",
                "tl": "teacher_j",
                "linkIndex": "3",
                "dir": "s",
                "state": "O",
                "pass": "true",
                "uncontrolled": "",
                "allow": "bicycle",
                "disallow": "",
                "keepClear": "0",
                "contPos": "43.00",
                "linkIndex2": "12",
                "shape": "0,0 1,1",
            }
        ],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "teacher_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [
            {
                "from": "cand_in",
                "to": "cand_out",
                "fromLane": "0",
                "toLane": "0",
                "via": ":candidate_j_0_0",
                "tl": "candidate_j",
                "linkIndex": "3",
                "dir": "s",
                "state": "O",
                "pass": "",
                "uncontrolled": "",
                "allow": "",
                "disallow": "",
                "keepClear": "",
                "contPos": "",
                "linkIndex2": "",
                "shape": "",
            }
        ],
        "pedestrian_connections": [],
        "traffic_light": {"attributes": {"id": "candidate_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["controlled_vehicle_link_signatures"] == {
        "3": "from=cand_in|to=cand_out|fromLane=0|toLane=0|dir=s|state=O|via=:candidate_j_0_0|pass=true|uncontrolled=|allow=bicycle|disallow=|keepClear=0|contPos=43.00|linkIndex2=12|shape=0,0 1,1"
    }
    assert parity["candidate"]["controlled_vehicle_link_signatures"] == {
        "3": "from=cand_in|to=cand_out|fromLane=0|toLane=0|dir=s|state=O|via=:candidate_j_0_0|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape="
    }
    assert parity["delta"]["controlled_vehicle_link_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "controlled_vehicle_link_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_pedestrian_link_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [
            {
                "from": ":teacher_j_w0",
                "to": ":teacher_j_c0",
                "fromLane": "0",
                "toLane": "0",
                "tl": "teacher_j",
                "linkIndex": "7",
                "dir": "s",
                "state": "M",
            }
        ],
        "traffic_light": {"attributes": {"id": "teacher_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [
            {
                "from": ":candidate_j_w0",
                "to": ":candidate_j_c_wrong",
                "fromLane": "0",
                "toLane": "0",
                "tl": "candidate_j",
                "linkIndex": "7",
                "dir": "s",
                "state": "M",
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j", "type": "actuated"}, "phases": [{"state": "G"}]},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["controlled_pedestrian_link_signatures"] == {
        "7": "from=:candidate_j_w0|to=:candidate_j_c0|fromLane=0|toLane=0|dir=s|state=M|via=|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape="
    }
    assert parity["candidate"]["controlled_pedestrian_link_signatures"] == {
        "7": "from=:candidate_j_w0|to=:candidate_j_c_wrong|fromLane=0|toLane=0|dir=s|state=M|via=|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape="
    }
    assert parity["delta"]["controlled_pedestrian_link_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "controlled_pedestrian_link_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_crossing_edge_set_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "crossings": [{"edge_id": ":teacher_j_c0", "crossingEdges": ["teacher_in", "teacher_out"]}],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "crossings": [{"edge_id": ":candidate_j_c0", "crossingEdges": ["cand_in", "cand_wrong"]}],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["crossing_signatures"] == {":candidate_j_c0": "edges=cand_in cand_out"}
    assert parity["candidate"]["crossing_signatures"] == {":candidate_j_c0": "edges=cand_in cand_wrong"}
    assert parity["delta"]["crossing_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "crossing_signature_mismatch_count", "count": 1}
    ]


def test_semantic_layer_gates_route_crossing_and_walkingarea_to_pedestrian_bike() -> None:
    semantic_gate = {
        "status": "fail",
        "failures": [
            {"report": "parity", "field": "crossing_signature_mismatch_count", "count": 1},
            {"report": "parity", "field": "walking_area_signature_mismatch_count", "count": 1},
            {"report": "parity", "field": "controlled_vehicle_link_signature_mismatch_count", "count": 1},
            {"report": "parity", "field": "internal_edge_signature_mismatch_count", "count": 1},
            {"report": "target_internal_replay", "field": "removed_stale_replaced_edge_connection_count", "count": 1},
        ],
    }

    layers = _semantic_layer_gates(semantic_gate, {"status": "pass"})

    assert layers["pedestrian_bike"]["status"] == "fail"
    assert [failure["field"] for failure in layers["pedestrian_bike"]["failures"]] == [
        "crossing_signature_mismatch_count",
        "walking_area_signature_mismatch_count",
    ]
    assert layers["movement_tls"]["status"] == "fail"
    assert layers["internal"]["status"] == "fail"
    assert layers["topology"]["status"] == "fail"
    assert [failure["field"] for failure in layers["topology"]["failures"]] == [
        "removed_stale_replaced_edge_connection_count"
    ]


def test_teacher_parity_fails_on_mapped_crossing_geometry_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "crossings": [
            {
                "edge_id": ":teacher_j_c0",
                "function": "crossing",
                "crossingEdges": ["teacher_in", "teacher_out"],
                "lanes": [
                    {"index": "0", "allow": "pedestrian", "width": "4.00", "shape": "0,0 1,1", "outlineShape": "0,0 1,0"}
                ],
            }
        ],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "crossings": [
            {
                "edge_id": ":candidate_j_c0",
                "function": "crossing",
                "crossingEdges": ["cand_in", "cand_out"],
                "lanes": [
                    {"index": "0", "allow": "pedestrian", "width": "2.00", "shape": "0,0 2,2", "outlineShape": "0,0 2,0"}
                ],
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["crossing_geometry_signatures"] == {
        ":candidate_j_c0": "function=crossing|lanes=0:pedestrian::::4.00:0,0 1,1:0,0 1,0"
    }
    assert parity["candidate"]["crossing_geometry_signatures"] == {
        ":candidate_j_c0": "function=crossing|lanes=0:pedestrian::::2.00:0,0 2,2:0,0 2,0"
    }
    assert parity["delta"]["crossing_geometry_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "crossing_geometry_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_normalizes_internal_pedestrian_geometry_by_junction_origin() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "junction": {"id": "teacher_j", "x": "100", "y": "200"},
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_edges": [
            {
                "edge_id": ":teacher_j_0",
                "function": "internal",
                "lanes": [{"index": "0", "shape": "101,200 102,201"}],
            }
        ],
        "crossings": [
            {
                "edge_id": ":teacher_j_c0",
                "function": "crossing",
                "lanes": [{"index": "0", "allow": "pedestrian", "shape": "99,199 101,199"}],
            }
        ],
        "walking_areas": [
            {
                "edge_id": ":teacher_j_w0",
                "function": "walkingarea",
                "lanes": [{"index": "0", "allow": "pedestrian", "outlineShape": "99,199 101,199 101,201"}],
            }
        ],
        "internal_junctions": [
            {
                "junction_id": ":teacher_j_0_0",
                "type": "internal",
                "incLanes": "",
                "intLanes": "",
                "shape": "101,200 102,201",
                "customShape": "99,199 101,199 101,201",
            }
        ],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "junction": {"id": "candidate_j", "x": "10", "y": "20"},
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_edges": [
            {
                "edge_id": ":candidate_j_0",
                "function": "internal",
                "lanes": [{"index": "0", "shape": "11,20 12,21"}],
            }
        ],
        "crossings": [
            {
                "edge_id": ":candidate_j_c0",
                "function": "crossing",
                "lanes": [{"index": "0", "allow": "pedestrian", "shape": "9,19 11,19"}],
            }
        ],
        "walking_areas": [
            {
                "edge_id": ":candidate_j_w0",
                "function": "walkingarea",
                "lanes": [{"index": "0", "allow": "pedestrian", "outlineShape": "9,19 11,19 11,21"}],
            }
        ],
        "internal_junctions": [
            {
                "junction_id": ":candidate_j_0_0",
                "type": "internal",
                "incLanes": "",
                "intLanes": "",
                "shape": "11,20 12,21",
                "customShape": "9,19 11,19 11,21",
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )

    assert "internal_edge_signature_mismatch_count" not in parity["delta"]
    assert "crossing_geometry_signature_mismatch_count" not in parity["delta"]
    assert "walking_area_signature_mismatch_count" not in parity["delta"]
    assert "internal_junction_signature_mismatch_count" not in parity["delta"]


def test_teacher_parity_fails_on_mapped_internal_edge_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_edges": [
            {
                "edge_id": ":teacher_j_0",
                "function": "internal",
                "lanes": [
                    {
                        "index": "0",
                        "allow": "passenger",
                        "disallow": "pedestrian",
                        "speed": "13.89",
                        "length": "10.50",
                        "width": "",
                        "shape": "0,0 1,1",
                    }
                ],
            }
        ],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_edges": [
            {
                "edge_id": ":candidate_j_0",
                "function": "internal",
                "lanes": [
                    {
                        "index": "0",
                        "allow": "passenger",
                        "disallow": "",
                        "speed": "8.33",
                        "length": "8.50",
                        "width": "",
                        "shape": "0,0 1,1",
                    }
                ],
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["internal_edge_signatures"] == {
        ":candidate_j_0": "function=internal|lanes=0:passenger:pedestrian:13.89:10.50::0,0 1,1:"
    }
    assert parity["candidate"]["internal_edge_signatures"] == {
        ":candidate_j_0": "function=internal|lanes=0:passenger::8.33:8.50::0,0 1,1:"
    }
    assert parity["delta"]["internal_edge_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "internal_edge_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_internal_junction_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_junctions": [
            {
                "junction_id": ":teacher_j_0_0",
                "type": "internal",
                "incLanes": "teacher_in_0 :teacher_j_0_0",
                "intLanes": "",
                "shape": "0,0 1,1",
                "customShape": "0,0 1,0 1,1",
            }
        ],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_junctions": [
            {
                "junction_id": ":candidate_j_0_0",
                "type": "internal",
                "incLanes": "cand_wrong_0 :candidate_j_0_0",
                "intLanes": "",
                "shape": "0,0 1,1",
                "customShape": "0,0 2,0 2,2",
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_in": "cand_in"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["internal_junction_signatures"] == {
        ":candidate_j_0_0": "type=internal|incLanes=cand_in_0 :candidate_j_0_0|intLanes=|shape=0,0 1,1|customShape=0,0 1,0 1,1"
    }
    assert parity["candidate"]["internal_junction_signatures"] == {
        ":candidate_j_0_0": "type=internal|incLanes=cand_wrong_0 :candidate_j_0_0|intLanes=|shape=0,0 1,1|customShape=0,0 2,0 2,2"
    }
    assert parity["delta"]["internal_junction_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "internal_junction_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_walking_area_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "walking_areas": [
            {
                "edge_id": ":teacher_j_w0",
                "function": "walkingarea",
                "lanes": [
                    {"index": "0", "allow": "pedestrian", "width": "4.00", "shape": "0,0 1,1", "outlineShape": "0,0 1,0"}
                ],
            }
        ],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "walking_areas": [
            {
                "edge_id": ":candidate_j_w0",
                "function": "walkingarea",
                "lanes": [
                    {"index": "0", "allow": "pedestrian", "width": "2.00", "shape": "0,0 2,2", "outlineShape": "0,0 2,0"}
                ],
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["walking_area_signatures"] == {
        ":candidate_j_w0": "function=walkingarea|lanes=0:pedestrian::::4.00:0,0 1,1:0,0 1,0"
    }
    assert parity["candidate"]["walking_area_signatures"] == {
        ":candidate_j_w0": "function=walkingarea|lanes=0:pedestrian::::2.00:0,0 2,2:0,0 2,0"
    }
    assert parity["delta"]["walking_area_signature_mismatch_count"] == 1
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "walking_area_signature_mismatch_count", "count": 1}
    ]


def test_teacher_parity_fails_on_mapped_internal_connection_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_connections": [
            {
                "from": ":teacher_j_0",
                "to": "teacher_out",
                "fromLane": "0",
                "toLane": "1",
                "via": "",
                "dir": "s",
                "state": "M",
            }
        ],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [],
        "internal_connections": [
            {
                "from": ":candidate_j_0",
                "to": "cand_wrong",
                "fromLane": "0",
                "toLane": "1",
                "via": "",
                "dir": "s",
                "state": "M",
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={"teacher_out": "cand_out"},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["internal_connection_signatures"] == {
        "from=:candidate_j_0|to=cand_out|fromLane=0|toLane=1|dir=s|state=M|via=|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape=": "1"
    }
    assert parity["candidate"]["internal_connection_signatures"] == {
        "from=:candidate_j_0|to=cand_wrong|fromLane=0|toLane=1|dir=s|state=M|via=|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape=": "1"
    }
    assert parity["delta"]["internal_connection_signature_mismatch_count"] == 2
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "internal_connection_signature_mismatch_count", "count": 2}
    ]


def test_teacher_parity_fails_on_uncontrolled_pedestrian_ring_signature_mismatch() -> None:
    teacher_model = {
        "junction_id": "teacher_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [
            {"from": ":teacher_j_w0", "to": ":teacher_j_w1", "fromLane": "0", "toLane": "0", "dir": "s", "state": "M"}
        ],
        "traffic_light": {"attributes": {"id": "teacher_j"}, "phases": []},
    }
    candidate_model = {
        "junction_id": "candidate_j",
        "summary": {},
        "vehicle_connections": [],
        "pedestrian_connections": [
            {
                "from": ":candidate_j_w0",
                "to": ":candidate_j_w_wrong",
                "fromLane": "0",
                "toLane": "0",
                "dir": "s",
                "state": "M",
            }
        ],
        "traffic_light": {"attributes": {"id": "candidate_j"}, "phases": []},
    }

    parity = _compare_teacher_models(
        teacher_model,
        candidate_model,
        edge_map={},
        teacher_junction_id="teacher_j",
        candidate_junction_id="candidate_j",
    )
    gate = _teacher_guided_semantics_gate(parity)

    assert parity["teacher"]["uncontrolled_pedestrian_connection_signatures"] == {
        "from=:candidate_j_w0|to=:candidate_j_w1|fromLane=0|toLane=0|dir=s|state=M|via=|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape=": "1"
    }
    assert parity["candidate"]["uncontrolled_pedestrian_connection_signatures"] == {
        "from=:candidate_j_w0|to=:candidate_j_w_wrong|fromLane=0|toLane=0|dir=s|state=M|via=|pass=|uncontrolled=|allow=|disallow=|keepClear=|contPos=|linkIndex2=|shape=": "1"
    }
    assert parity["delta"]["uncontrolled_pedestrian_connection_signature_mismatch_count"] == 2
    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {"report": "parity", "field": "uncontrolled_pedestrian_connection_signature_mismatch_count", "count": 2}
    ]


def test_teacher_guided_semantics_gate_fails_on_skipped_pedestrian_connections() -> None:
    gate = _teacher_guided_semantics_gate(
        {"delta": {"vehicle_connection_count": 0, "pedestrian_connection_count": 0}},
        pedestrian_ring={"skipped_pedestrian_connection_count": 1},
        vehicle_connection_attrs={"skipped_vehicle_connection_count": 0},
    )

    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {
            "report": "pedestrian_ring",
            "field": "skipped_pedestrian_connection_count",
            "count": 1,
        }
    ]


def test_teacher_guided_semantics_gate_ignores_interim_pedestrian_skips_after_internal_replay() -> None:
    gate = _teacher_guided_semantics_gate(
        {"delta": {"vehicle_connection_count": 0, "pedestrian_connection_count": 0}},
        pedestrian_ring={"skipped_pedestrian_connection_count": 21},
        vehicle_connection_attrs={"skipped_vehicle_connection_count": 0},
        target_internal_replay={"status": "pass", "skipped_connection_count": 0},
    )

    assert gate == {"status": "pass", "failures": []}


def test_teacher_guided_semantics_gate_fails_when_internal_replay_removes_non_target_connections() -> None:
    gate = _teacher_guided_semantics_gate(
        {"delta": {"vehicle_connection_count": 0, "pedestrian_connection_count": 0}},
        target_internal_replay={
            "status": "pass",
            "skipped_connection_count": 0,
            "removed_stale_replaced_edge_connection_count": 1,
            "removed_stale_replaced_edge_connections": [
                {"from": "main", "to": "neighbor_out", "via": ":neighbor_0_0"}
            ],
        },
    )

    assert gate["status"] == "fail"
    assert gate["failures"] == [
        {
            "report": "target_internal_replay",
            "field": "removed_stale_replaced_edge_connection_count",
            "count": 1,
        }
    ]


def test_teacher_guided_semantics_gate_allows_non_target_walkingarea_connection_cleanup() -> None:
    gate = _teacher_guided_semantics_gate(
        {"delta": {"vehicle_connection_count": 0, "pedestrian_connection_count": 0}},
        target_internal_replay={
            "status": "pass",
            "skipped_connection_count": 0,
            "removed_stale_replaced_edge_connection_count": 1,
            "removed_stale_replaced_edge_connections": [
                {"from": "edge", "to": ":neighbor_w0", "dir": "s", "state": "M"}
            ],
        },
    )

    assert gate == {"status": "pass", "failures": []}


def test_teacher_guided_semantics_gate_allows_teacher_boundary_absorption_cleanup() -> None:
    gate = _teacher_guided_semantics_gate(
        {"delta": {"vehicle_connection_count": 0, "pedestrian_connection_count": 0}},
        target_internal_replay={
            "status": "pass",
            "skipped_connection_count": 0,
            "copied_boundary_edges": ["teacher_absorbed"],
            "removed_stale_replaced_edge_connection_count": 1,
            "removed_stale_replaced_edge_connections": [
                {"from": "old_neighbor", "to": "teacher_absorbed", "via": ":old_neighbor_0_0"}
            ],
        },
    )

    assert gate == {"status": "pass", "failures": []}


def test_teacher_guided_semantics_gate_allows_mapped_teacher_boundary_absorption_cleanup() -> None:
    gate = _teacher_guided_semantics_gate(
        {"delta": {"vehicle_connection_count": 0, "pedestrian_connection_count": 0}},
        target_internal_replay={
            "status": "pass",
            "skipped_connection_count": 0,
            "copied_boundary_edges": ["teacher_absorbed"],
            "copied_boundary_candidate_edges": ["candidate_absorbed"],
            "removed_stale_replaced_edge_connection_count": 1,
            "removed_stale_replaced_edge_connections": [
                {"from": "old_neighbor", "to": "candidate_absorbed", "via": ":old_neighbor_0_0"}
            ],
        },
    )

    assert gate == {"status": "pass", "failures": []}


def test_write_teacher_target_internal_replay_net_maps_and_translates_teacher_subgraph(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="90,20 100,20"/></edge>
  <edge id="teacher_out" from="j" to="b"><lane id="teacher_out_0" index="0" shape="100,20 110,20"/></edge>
  <edge id="foot_same" from="j" to="p"><lane id="foot_same_0" index="0" allow="pedestrian" shape="100,20 100,25"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="100,200 101,201" outlineShape="99,199 102,202"/></edge>
  <edge id=":j_c0" function="crossing" crossingEdges="teacher_in"><lane id=":j_c0_0" index="0" allow="pedestrian" shape="99,199 101,199" outlineShape="98,198 102,200"/></edge>
  <edge id=":j_w0" function="walkingarea"><lane id=":j_w0_0" index="0" allow="pedestrian" shape="98,198 99,199" outlineShape="97,197 100,200"/></edge>
  <junction id="j" type="traffic_light" x="100" y="200" shape="99,199 101,199 101,201 99,201" customShape="98,198 102,198 102,202 98,202" incLanes="teacher_in_0" intLanes=":j_0_0 :j_c0_0 :j_w0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <junction id=":j_0_0" type="internal" x="100" y="200" incLanes="teacher_in_0" intLanes=":j_0_0" customShape="99,199 101,201"/>
  <junction id=":j_w0_0" type="internal" x="98" y="198" incLanes="teacher_in_0" intLanes=":j_c0_0"/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="s" state="O" shape="100,200 101,201"/>
  <connection from=":j_w0" to=":j_c0" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="s" state="M"/>
  <connection from=":j_w0" to="foot_same" fromLane="0" toLane="0" dir="s" state="M"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="GM"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,20 10,20"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0" shape="10,20 20,20"/></edge>
  <edge id="foot_same" from="j" to="p"><lane id="foot_same_0" index="0" allow="pedestrian" shape="10,20 10,25"/></edge>
  <edge id=":j_old" function="internal"><lane id=":j_old_0" index="0" shape="10,20 11,20"/></edge>
  <junction id="j" type="traffic_light" x="10" y="20" shape="9,19 11,19 11,21 9,21" incLanes="cand_in_0" intLanes=":j_old_0"/>
  <junction id=":j_old_0" type="internal" x="10" y="20" incLanes="cand_in_0" intLanes=":j_old_0"/>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0" via=":j_old_0"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="r"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    assert root.find("edge[@id=':j_old']") is None
    assert root.find("junction[@id=':j_old_0']") is None
    assert root.find("edge[@id=':j_0']/lane").attrib["shape"] == "10.00,20.00 11.00,21.00"
    assert root.find("edge[@id=':j_0']/lane").attrib["outlineShape"] == "9.00,19.00 12.00,22.00"
    assert root.find("edge[@id=':j_c0']/lane").attrib["outlineShape"] == "8.00,18.00 12.00,20.00"
    assert root.find("edge[@id=':j_w0']/lane").attrib["outlineShape"] == "7.00,17.00 10.00,20.00"
    assert root.find("edge[@id=':j_c0']").attrib["crossingEdges"] == "cand_in"
    junction = root.find("junction[@id='j']")
    assert junction.attrib["x"] == "10.00"
    assert junction.attrib["y"] == "20.00"
    assert junction.attrib["shape"] == "9.00,19.00 11.00,19.00 11.00,21.00 9.00,21.00"
    assert junction.attrib["customShape"] == "8.00,18.00 12.00,18.00 12.00,22.00 8.00,22.00"
    assert junction.attrib["incLanes"] == "cand_in_0"
    assert junction.attrib["intLanes"] == ":j_0_0 :j_c0_0 :j_w0_0"
    internal_junction = root.find("junction[@id=':j_0_0']")
    assert internal_junction.attrib["x"] == "10.00"
    assert internal_junction.attrib["y"] == "20.00"
    assert internal_junction.attrib["incLanes"] == "cand_in_0"
    assert internal_junction.attrib["intLanes"] == ":j_0_0"
    assert internal_junction.attrib["customShape"] == "9.00,19.00 11.00,21.00"
    walkingarea_junction = root.find("junction[@id=':j_w0_0']")
    assert walkingarea_junction.attrib["x"] == "8.00"
    assert walkingarea_junction.attrib["y"] == "18.00"
    vehicle_connection = root.find("connection[@from='cand_in'][@to='cand_out']")
    assert vehicle_connection.attrib["via"] == ":j_0_0"
    assert vehicle_connection.attrib["shape"] == "10.00,20.00 11.00,21.00"
    assert root.find("connection[@from=':j_w0'][@to=':j_c0']").attrib["tl"] == "j"
    assert root.find("connection[@from=':j_w0'][@to='foot_same']") is not None
    assert report["removed_internal_edge_count"] == 1
    assert report["removed_internal_junction_count"] == 1
    assert report["copied_internal_edge_count"] == 3
    assert report["copied_internal_junction_count"] == 2
    assert report["copied_connection_count"] == 3


def test_write_teacher_target_internal_replay_net_removes_stale_candidate_boundary_edge(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="teacher_j"><lane id="teacher_in_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="teacher_out" from="teacher_j" to="b"><lane id="teacher_out_0" index="0" shape="10,0 20,0"/></edge>
  <edge id=":teacher_j_0" function="internal"><lane id=":teacher_j_0_0" index="0" shape="10,0 11,0"/></edge>
  <junction id="teacher_j" type="traffic_light" x="10" y="0" incLanes="teacher_in_0" intLanes=":teacher_j_0_0"/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":teacher_j_0_0" tl="teacher_j" linkIndex="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0" shape="10,0 20,0"/></edge>
  <edge id="stale_out" from="j" to="z"><lane id="stale_out_0" index="0" shape="10,0 20,5"/></edge>
  <edge id="remote" from="z" to="q"><lane id="remote_0" index="0" shape="20,5 30,5"/></edge>
  <junction id="j" type="traffic_light" x="10" y="0" incLanes="cand_in_0" intLanes=""/>
  <junction id="z" type="priority" x="20" y="5" incLanes="stale_out_0" intLanes=""/>
  <junction id=":z_0_0" type="internal" incLanes="stale_out_0 remote_0" intLanes=""/>
  <junction id="q" type="priority" x="30" y="5" incLanes="remote_0" intLanes=""/>
  <connection from="stale_out" to="remote" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        teacher_junction_id="teacher_j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    assert root.find("edge[@id='cand_in']") is not None
    assert root.find("edge[@id='cand_out']") is not None
    assert root.find("edge[@id='remote']") is not None
    assert root.find("edge[@id='stale_out']") is None
    assert root.find("connection[@from='stale_out'][@to='remote']") is None
    assert root.find("junction[@id=':z_0_0']").attrib["incLanes"] == "remote_0"
    assert report["removed_stale_boundary_edge_count"] == 1
    assert report["removed_stale_boundary_edges"] == ["stale_out"]
    assert report["removed_stale_boundary_edge_connection_count"] == 1


def test_write_teacher_target_internal_replay_net_replays_connectionless_boundary_edge(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_out" from="teacher_j" to="teacher_exit" type="cycleway.track|highway.primary"><lane id="teacher_out_0" index="0" shape="10,0 20,0"/></edge>
  <junction id="teacher_j" type="priority" x="10" y="0" incLanes="" intLanes=""/>
  <junction id="teacher_exit" type="priority" x="20" y="0" incLanes="teacher_out_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_short" from="j" to="wrong_exit" type="highway.primary"><lane id="cand_short_0" index="0" shape="10,0 15,0"/></edge>
  <junction id="j" type="priority" x="10" y="0" incLanes="" intLanes=""/>
  <junction id="wrong_exit" type="priority" x="15" y="0" incLanes="cand_short_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        teacher_junction_id="teacher_j",
        edge_map={"teacher_out": "cand_short"},
    )

    root = ET.parse(report["net_file"]).getroot()
    edge = root.find("edge[@id='cand_short']")
    assert edge.attrib["from"] == "j"
    assert edge.attrib["to"] == "teacher_exit"
    assert edge.attrib["type"] == "cycleway.track|highway.primary"
    assert root.find("junction[@id='teacher_exit']") is not None
    assert root.find("junction[@id='wrong_exit']").attrib["incLanes"] == ""
    assert report["copied_boundary_edges"] == ["teacher_out"]


def test_write_teacher_target_internal_replay_net_maps_referenced_tls_logic(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="teacher_out" from="j" to="b"><lane id="teacher_out_0" index="0" shape="10,0 20,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="10,0 11,0"/></edge>
  <junction id="j" type="traffic_light" x="10" y="0" incLanes="teacher_in_0" intLanes=":j_0_0"/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":j_0_0" tl="cluster_tls" linkIndex="0" dir="s"/>
  <tlLogic id="cluster_tls" type="actuated" programID="0" offset="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0" shape="10,0 20,0"/></edge>
  <junction id="j" type="traffic_light" x="10" y="0" incLanes="cand_in_0" intLanes=""/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="r"/></tlLogic>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    connection = root.find("connection[@from='cand_in'][@to='cand_out']")
    assert connection.attrib["tl"] == "j"
    target_tls = root.find("tlLogic[@id='j']")
    assert target_tls.attrib["type"] == "actuated"
    assert target_tls.find("phase").attrib["state"] == "G"


def test_write_teacher_target_internal_replay_net_removes_stale_tls_links_beyond_teacher_capacity(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="teacher_out" from="j" to="b"><lane id="teacher_out_0" index="0" shape="10,0 20,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="10,0 11,0"/></edge>
  <junction id="j" type="traffic_light" x="10" y="0" incLanes="teacher_in_0" intLanes=":j_0_0"/>
  <junction id="y" type="priority" x="30" y="0" incLanes="remote_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="s"/>
  <tlLogic id="j" type="actuated" programID="0" offset="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0" shape="10,0 20,0"/></edge>
  <edge id="remote_in" from="x" to="y"><lane id="remote_in_0" index="0" shape="20,0 30,0"/></edge>
  <edge id="remote_out" from="y" to="z"><lane id="remote_out_0" index="0" shape="30,0 40,0"/></edge>
  <junction id="j" type="traffic_light" x="10" y="0" incLanes="cand_in_0" intLanes=""/>
  <junction id="y" type="priority" x="30" y="0" incLanes="remote_in_0" intLanes=""/>
  <connection from="remote_in" to="remote_out" fromLane="0" toLane="0" tl="j" linkIndex="3" dir="s"/>
  <tlLogic id="j" type="actuated" programID="0" offset="0"><phase duration="30" state="GGGG"/></tlLogic>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    assert root.find("connection[@from='remote_in'][@to='remote_out']") is None
    assert report["removed_stale_tls_connection_count"] == 1
    assert report["removed_stale_tls_connections"][0]["linkIndex"] == "3"


def test_write_teacher_target_internal_replay_net_removes_tls_when_teacher_has_no_tls(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="teacher_out" from="j" to="b"><lane id="teacher_out_0" index="0" shape="10,0 20,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="10,0 11,0"/></edge>
  <junction id="j" type="priority" x="10" y="0" incLanes="teacher_in_0" intLanes=":j_0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":j_0_0" dir="s"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0" shape="10,0 20,0"/></edge>
  <edge id="other_in" from="x" to="y"><lane id="other_in_0" index="0"/></edge>
  <edge id="other_out" from="y" to="z"><lane id="other_out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" x="10" y="0" incLanes="cand_in_0" intLanes=""/>
  <junction id="y" type="priority" x="20" y="0" incLanes="other_in_0" intLanes=""/>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0" tl="j" linkIndex="0" via=":j_old_0_0"/>
  <connection from="other_in" to="other_out" fromLane="0" toLane="0" tl="j" linkIndex="1" linkIndex2="5"/>
  <tlLogic id="j" type="actuated" programID="0" offset="0"><phase duration="30" state="GG"/></tlLogic>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    replayed_connection = root.find("connection[@from='cand_in'][@to='cand_out']")
    off_scope_connection = root.find("connection[@from='other_in'][@to='other_out']")
    assert root.find("tlLogic[@id='j']") is None
    assert root.find("junction[@id='j']").attrib["type"] == "priority"
    assert "tl" not in replayed_connection.attrib
    assert "linkIndex" not in replayed_connection.attrib
    assert "tl" not in off_scope_connection.attrib
    assert "linkIndex" not in off_scope_connection.attrib
    assert "linkIndex2" not in off_scope_connection.attrib
    assert off_scope_connection.attrib["uncontrolled"] == "true"


def test_write_teacher_target_internal_replay_net_inserts_new_tls_before_connections(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="teacher_out" from="j" to="b"><lane id="teacher_out_0" index="0" shape="10,0 20,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="10,0 11,0"/></edge>
  <junction id="j" type="traffic_light" x="10" y="0" incLanes="teacher_in_0" intLanes=":j_0_0"/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="s"/>
  <tlLogic id="j" type="actuated" programID="0" offset="0"><phase duration="30" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0" shape="10,0 20,0"/></edge>
  <junction id="j" type="traffic_light" x="10" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    children = list(root)
    tls_index = children.index(root.find("tlLogic[@id='j']"))
    connection_index = children.index(root.find("connection[@from='cand_in'][@to='cand_out']"))
    assert tls_index < connection_index


def test_write_teacher_target_internal_replay_net_preserves_colliding_teacher_boundary_edges(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="main#2" from="a" to="j"><lane id="main#2_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="main#3" from="j" to="b"><lane id="main#3_0" index="0" shape="10,0 20,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="10,0 11,0"/></edge>
  <junction id="a" x="0" y="0"/>
  <junction id="j" type="traffic_light" x="10" y="0" incLanes="main#2_0" intLanes=":j_0_0"/>
  <junction id="b" x="20" y="0" incLanes="main#3_0"/>
  <connection from="main#2" to="main#3" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="s"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="G"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="main#2" from="x" to="y"><lane id="main#2_0" index="0" shape="-20,0 -10,0"/></edge>
  <edge id="main#3" from="a" to="j"><lane id="main#3_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="prev" from="p" to="y"><lane id="prev_0" index="0" shape="-30,0 -20,0"/></edge>
  <edge id="out" from="j" to="q"><lane id="out_0" index="0" shape="10,0 20,0"/></edge>
  <junction id="a" x="0" y="0"/>
  <junction id="j" type="traffic_light" x="10" y="0" incLanes="main#3_0" intLanes=""/>
  <junction id="p" x="-30" y="0"/>
  <junction id="q" x="20" y="0"/>
  <junction id="x" x="-20" y="0"/>
  <junction id="y" x="-10" y="0" incLanes="main#2_0 prev_0"/>
  <connection from="prev" to="main#2" fromLane="0" toLane="0" dir="s"/>
  <connection from="main#2" to="out" fromLane="0" toLane="0" via=":y_0_0" dir="s"/>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"main#2": "main#3", "main#3": "main#3"},
    )

    root = ET.parse(report["net_file"]).getroot()
    assert report["status"] == "pass"
    assert root.find("edge[@id='main#2']").attrib["to"] == "j"
    assert root.find("edge[@id='main#3']").attrib["from"] == "j"
    assert root.find("connection[@from='main#2'][@to='main#3']") is not None
    assert root.find("connection[@from='main#3'][@to='main#3']") is None
    assert root.find("connection[@from='prev'][@to='main#2']") is None
    assert root.find("connection[@from='main#2'][@to='out']") is None
    assert root.find("edge[@id='out']") is None
    assert report["removed_stale_boundary_edges"] == ["out"]
    assert report["removed_stale_boundary_edge_connection_count"] == 1
    assert report["removed_stale_replaced_edge_connection_count"] == 1


def test_write_teacher_target_internal_replay_net_removes_replaced_boundary_connection_with_stale_lane_index(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="main" from="teacher_j" to="b"><lane id="main_0" index="0" shape="10,0 20,0"/></edge>
  <junction id="teacher_j" type="priority" x="10" y="0" incLanes="" intLanes=""/>
  <junction id="b" type="priority" x="20" y="0" incLanes="main_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="main" from="j" to="b"><lane id="main_0" index="0" shape="10,0 20,0"/><lane id="main_1" index="1" shape="10,1 20,1"/></edge>
  <edge id="back" from="b" to="q"><lane id="back_0" index="0" shape="20,0 30,0"/></edge>
  <junction id="j" type="priority" x="10" y="0" incLanes="" intLanes=""/>
  <junction id="b" type="priority" x="20" y="0" incLanes="main_0 main_1" intLanes=""/>
  <junction id="q" type="priority" x="30" y="0" incLanes="back_0" intLanes=""/>
  <connection from="main" to="back" fromLane="1" toLane="0" via=":b_0_0" dir="s"/>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        teacher_junction_id="teacher_j",
        edge_map={"main": "main"},
    )

    root = ET.parse(report["net_file"]).getroot()
    assert len(root.find("edge[@id='main']").findall("lane")) == 1
    assert root.find("connection[@from='main'][@to='back']") is None
    assert report["removed_stale_replaced_edge_connection_count"] == 1


def test_write_teacher_target_internal_replay_net_removes_internal_replaced_boundary_connection_with_stale_lane_index(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="main" from="teacher_j" to="b"><lane id="main_0" index="0" shape="10,0 20,0"/></edge>
  <junction id="teacher_j" type="priority" x="10" y="0" incLanes="" intLanes=""/>
  <junction id="b" type="priority" x="20" y="0" incLanes="main_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="main" from="j" to="b"><lane id="main_0" index="0" shape="10,0 20,0"/><lane id="main_1" index="1" shape="10,1 20,1"/></edge>
  <edge id=":old_1" function="internal" from="old" to="j"><lane id=":old_1_0" index="0"/><lane id=":old_1_1" index="1"/></edge>
  <junction id="old" type="priority" x="0" y="0" incLanes="" intLanes=":old_1_0 :old_1_1"/>
  <junction id="j" type="priority" x="10" y="0" incLanes="" intLanes=""/>
  <junction id="b" type="priority" x="20" y="0" incLanes="main_0 main_1" intLanes=""/>
  <connection from=":old_1" to="main" fromLane="1" toLane="1" dir="s"/>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        teacher_junction_id="teacher_j",
        edge_map={"main": "main"},
    )

    root = ET.parse(report["net_file"]).getroot()
    assert len(root.find("edge[@id='main']").findall("lane")) == 1
    assert root.find("connection[@from=':old_1'][@to='main']") is None
    assert report["removed_stale_replaced_edge_connection_count"] == 1


def test_write_teacher_target_internal_replay_net_removes_any_invalid_lane_connection(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="teacher_j"><lane id="teacher_in_0" index="0"/></edge>
  <edge id="teacher_out" from="teacher_j" to="b"><lane id="teacher_out_0" index="0"/></edge>
  <junction id="teacher_j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0"/>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0"/></edge>
  <edge id="remote_in" from="x" to="y"><lane id="remote_in_0" index="0"/></edge>
  <edge id="remote_out" from="y" to="z"><lane id="remote_out_0" index="0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
  <junction id="y" type="priority" x="10" y="0" incLanes="remote_in_0" intLanes=""/>
  <connection from="remote_in" to="remote_out" fromLane="1" toLane="0"/>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        teacher_junction_id="teacher_j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    assert root.find("connection[@from='remote_in'][@to='remote_out']") is None
    assert report["removed_invalid_lane_connection_count"] == 1


def test_restore_replayed_geometry_attrs_keeps_normalized_topology_geometry_local(tmp_path: Path) -> None:
    replayed = tmp_path / "replayed.net.xml"
    replayed.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" speed="8.17" shape="0,0 10,0" length="10.00"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0" speed="8.17" shape="10,0 20,0" length="10.00"/></edge>
  <edge id="remote" from="x" to="y"><lane id="remote_0" index="0" shape="50,0 60,0"/></edge>
  <edge id=":j_c0" function="crossing"><lane id=":j_c0_0" index="0" shape="9,-1 9,1" outlineShape="8,-1 10,-1 10,1 8,1"/></edge>
  <junction id="j" type="traffic_light" x="10" y="0" shape="9,-1 11,-1 11,1 9,1" incLanes="in_0" intLanes=":j_c0_0">
    <request index="0" response="101" foes="111" cont="1"/>
  </junction>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0"/>
  <connection from=":j_c0" to="out" fromLane="0" toLane="0"/>
</net>
""",
        encoding="utf-8",
    )
    normalized = tmp_path / "normalized.net.xml"
    normalized.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" speed="6.98" shape="0,0 11,0" length="11.00"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0" speed="6.98" shape="11,0 20,0" length="9.00"/></edge>
  <edge id="remote" from="x" to="y"><lane id="remote_0" index="0" shape="51,0 60,0"/></edge>
  <edge id=":j_c0" function="crossing"><lane id=":j_c0_0" index="0" shape="9,-2 9,2" outlineShape="bad"/></edge>
  <junction id="j" type="traffic_light" x="10" y="0" shape="bad" incLanes="in_0" intLanes=":j_c0_0">
    <request index="0" response="100" foes="111" cont="1"/>
  </junction>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0"/>
  <connection from=":j_c0" to="out" fromLane="0" toLane="0"/>
</net>
""",
        encoding="utf-8",
    )

    report = _restore_replayed_geometry_attrs(
        source_file=replayed,
        target_file=normalized,
        junction_id="j",
    )

    root = ET.parse(normalized).getroot()
    assert report["status"] == "pass"
    assert root.find("edge[@id='in']/lane").attrib["shape"] == "0,0 10,0"
    assert root.find("edge[@id='in']/lane").attrib["speed"] == "8.17"
    assert root.find("edge[@id='out']/lane").attrib["length"] == "10.00"
    assert root.find("edge[@id=':j_c0']/lane").attrib["outlineShape"] == "8,-1 10,-1 10,1 8,1"
    assert root.find("edge[@id='remote']/lane").attrib["shape"] == "51,0 60,0"
    assert root.find("junction[@id='j']").attrib["shape"] == "9,-1 11,-1 11,1 9,1"
    assert root.find("junction[@id='j']/request").attrib["response"] == "101"
    assert report["restored_junction_attr_count"] == 1
    assert report["restored_request_count"] == 1


def test_restore_replayed_geometry_attrs_restores_missing_internal_subgraph_after_normalize(tmp_path: Path) -> None:
    replayed = tmp_path / "replayed.net.xml"
    replayed.write_text(
        """<net>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" allow="bicycle" speed="5.37" shape="0,0 1,0"/></edge>
  <edge id=":j_1" function="internal"><lane id=":j_1_0" index="0" allow="bicycle" speed="7.78" shape="1,0 2,0"/></edge>
  <edge id=":j_c0" function="crossing"><lane id=":j_c0_0" index="0" allow="pedestrian" shape="0,1 1,1"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="in_0" intLanes=":j_0_0 :j_1_0 :j_c0_0">
    <request index="0" response="000" foes="111" cont="0"/>
  </junction>
  <junction id=":j_0_0" type="internal" incLanes=":j_0_0" intLanes=":j_1_0 :j_c0_0"/>
  <junction id=":j_1_0" type="internal" incLanes=":j_1_0" intLanes=":j_c0_0"/>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0"/>
  <connection from=":j_0" to=":j_1" fromLane="0" toLane="0" via=":j_1_0"/>
  <connection from=":j_1" to="out" fromLane="0" toLane="0"/>
  <connection from="remote" to="far" fromLane="0" toLane="0"/>
</net>
""",
        encoding="utf-8",
    )
    normalized = tmp_path / "normalized.net.xml"
    normalized.write_text(
        """<net>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" disallow="pedestrian bicycle" speed="4.00" shape="0,0 0.5,0"/></edge>
  <edge id=":j_c0" function="crossing"><lane id=":j_c0_0" index="0" allow="pedestrian" shape="0,2 1,2"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="in_0" intLanes=":j_0_0 :j_c0_0">
    <request index="0" response="100" foes="111" cont="1"/>
  </junction>
  <junction id=":j_0_0" type="internal" incLanes=":j_0_0" intLanes=":j_c0_0"/>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0"/>
  <connection from=":j_0" to="out" fromLane="0" toLane="0"/>
  <connection from="remote" to="far" fromLane="0" toLane="0"/>
</net>
""",
        encoding="utf-8",
    )

    report = _restore_replayed_geometry_attrs(
        source_file=replayed,
        target_file=normalized,
        junction_id="j",
    )

    root = ET.parse(normalized).getroot()
    restored_lane = root.find("edge[@id=':j_0']/lane")
    assert report["status"] == "pass"
    assert restored_lane.attrib["allow"] == "bicycle"
    assert "disallow" not in restored_lane.attrib
    assert root.find("edge[@id=':j_1']") is not None
    assert root.find("junction[@id=':j_1_0']") is not None
    assert root.find("junction[@id='j']").attrib["intLanes"] == ":j_0_0 :j_1_0 :j_c0_0"
    assert root.find("connection[@from=':j_0'][@to=':j_1']") is not None
    assert root.find("connection[@from=':j_1'][@to='out']") is not None
    assert root.find("connection[@from=':j_0'][@to='out']") is None
    assert root.find("connection[@from='remote'][@to='far']") is not None
    assert report["restored_internal_edge_count"] == 3
    assert report["restored_internal_junction_count"] == 2
    assert report["restored_connection_count"] == 3


def test_write_teacher_target_internal_replay_net_copies_missing_boundary_edge(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="90,20 100,20"/></edge>
  <edge id="teacher_out" from="j" to="b"><lane id="teacher_out_0" index="0" shape="100,20 110,20"/></edge>
  <edge id="foot_missing" from="j" to="p"><lane id="foot_missing_0" index="0" allow="pedestrian" shape="100,20 100,25"/></edge>
  <edge id=":j_w0" function="walkingarea"><lane id=":j_w0_0" index="0" allow="pedestrian" shape="98,198 99,199"/></edge>
  <junction id="j" type="priority" x="100" y="200" shape="99,199 101,199" incLanes="teacher_in_0" intLanes=":j_w0_0"/>
  <junction id="p" type="dead_end" x="100" y="25" incLanes="foot_missing_0" intLanes=""/>
  <connection from=":j_w0" to="foot_missing" fromLane="0" toLane="0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,20 10,20"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0" shape="10,20 20,20"/></edge>
  <junction id="p" type="dead_end" x="10" y="-155" incLanes="" intLanes=""/>
  <junction id="j" type="priority" x="10" y="20" shape="9,19 11,19" incLanes="cand_in_0" intLanes=":j_old_0"/>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    copied_edge = root.find("edge[@id='foot_missing']")
    assert copied_edge is not None
    assert copied_edge.attrib["from"] == "j"
    assert copied_edge.attrib["to"] == "p"
    assert copied_edge.find("lane").attrib["shape"] == "10.00,-160.00 10.00,-155.00"
    assert root.find("connection[@from=':j_w0'][@to='foot_missing']") is not None
    assert "foot_missing_0" in root.find("junction[@id='p']").attrib["incLanes"]
    children = list(root)
    assert children.index(copied_edge) < children.index(root.find("junction[@id='p']"))
    assert report["copied_boundary_edge_count"] == 1
    assert report["copied_boundary_edges"] == ["foot_missing"]
    assert report["skipped_connection_count"] == 0


def test_write_teacher_target_internal_replay_net_copies_vehicle_continuation_for_new_boundary_junction(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="90,20 100,20"/></edge>
  <edge id="teacher_out" from="j" to="n" type="highway.secondary"><lane id="teacher_out_0" index="0" shape="100,20 110,20"/></edge>
  <edge id="teacher_back" from="n" to="j" type="highway.secondary"><lane id="teacher_back_0" index="0" shape="110,22 100,22"/></edge>
  <edge id="next_out" from="n" to="f" type="highway.secondary"><lane id="next_out_0" index="0" shape="110,20 130,20"/></edge>
  <edge id="next_in" from="f" to="n" type="highway.secondary"><lane id="next_in_0" index="0" shape="130,22 110,22"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="100,20 101,20"/></edge>
  <junction id="j" type="traffic_light" x="100" y="20" incLanes="teacher_in_0 teacher_back_0" intLanes=":j_0_0"/>
  <junction id="n" type="priority" x="110" y="20" incLanes="teacher_out_0 next_in_0" intLanes=""/>
  <junction id="f" type="priority" x="130" y="20" incLanes="next_out_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="s" state="O"/>
  <connection from="teacher_out" to="next_out" fromLane="0" toLane="0" dir="s" state="M"/>
  <connection from="next_in" to="teacher_back" fromLane="0" toLane="0" dir="s" state="M"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,20 10,20"/></edge>
  <junction id="j" type="traffic_light" x="10" y="20" incLanes="cand_in_0" intLanes=""/>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in"},
    )

    root = ET.parse(report["net_file"]).getroot()
    assert root.find("edge[@id='teacher_out']").attrib["to"] == "n"
    assert root.find("edge[@id='teacher_back']").attrib["from"] == "n"
    assert root.find("edge[@id='next_out']").attrib["from"] == "n"
    assert root.find("edge[@id='next_in']").attrib["to"] == "n"
    assert root.find("junction[@id='n']").attrib["type"] == "priority"
    assert "next_in_0" in root.find("junction[@id='n']").attrib["incLanes"]
    assert root.find("connection[@from='teacher_out'][@to='next_out']") is not None
    assert root.find("connection[@from='next_in'][@to='teacher_back']") is not None
    assert report["copied_boundary_continuation_edge_count"] == 2
    assert report["copied_boundary_continuation_edges"] == ["next_out", "next_in"]


def test_write_teacher_target_internal_replay_net_removes_stale_same_family_split_fragment(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="-road#1" from="far" to="mid" type="highway.tertiary"><lane id="-road#1_0" index="0" shape="-20,0 -10,0"/></edge>
  <edge id="-road#0" from="mid" to="j" type="highway.tertiary"><lane id="-road#0_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="road#0" from="j" to="mid" type="highway.tertiary"><lane id="road#0_0" index="0" shape="0,2 -10,2"/></edge>
  <edge id="road#1" from="mid" to="far" type="highway.tertiary"><lane id="road#1_0" index="0" shape="-10,2 -20,2"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="0,0 1,0"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="-road#0_0" intLanes=":j_0_0"/>
  <junction id="mid" type="priority" x="-10" y="0" incLanes="-road#1_0 road#0_0" intLanes=""/>
  <junction id="far" type="priority" x="-20" y="0" incLanes="road#1_0" intLanes=""/>
  <connection from="-road#1" to="-road#0" fromLane="0" toLane="0" via=":mid_0_0" dir="s" state="M"/>
  <connection from="road#0" to="road#1" fromLane="0" toLane="0" via=":mid_1_0" dir="s" state="M"/>
  <connection from="-road#0" to="road#0" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="t" state="O"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="-road#0" from="mid" to="j"><lane id="-road#0_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="-road#1" from="mid" to="stale"><lane id="-road#1_0" index="0" shape="-10,0 -5,0"/></edge>
  <edge id="road#0" from="j" to="mid"><lane id="road#0_0" index="0" shape="0,2 -10,2"/></edge>
  <edge id="road#1" from="stale" to="mid"><lane id="road#1_0" index="0" shape="-5,2 -10,2"/></edge>
  <edge id="-road#2" from="far" to="mid"><lane id="-road#2_0" index="0" shape="-20,0 -10,0"/></edge>
  <edge id="road#2" from="mid" to="far"><lane id="road#2_0" index="0" shape="-10,2 -20,2"/></edge>
  <edge id="side_in" from="far" to="side"><lane id="side_in_0" index="0" shape="-20,4 -10,4"/></edge>
  <edge id="side_out" from="side" to="far"><lane id="side_out_0" index="0" shape="-10,6 -20,6"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="-road#0_0" intLanes=""/>
  <junction id="mid" type="traffic_light" x="-10" y="0" incLanes="-road#2_0 road#1_0 road#0_0" intLanes=""/>
  <junction id="stale" type="dead_end" x="-5" y="0" incLanes="-road#1_0" intLanes=""/>
  <junction id="far" type="priority" x="-20" y="0" incLanes="road#2_0" intLanes=""/>
  <junction id="side" type="priority" x="-10" y="4" incLanes="side_in_0" intLanes=""/>
  <connection from="-road#2" to="-road#1" fromLane="0" toLane="0" via=":mid_0_0" tl="stale" linkIndex="3" dir="s" state="O"/>
  <connection from="road#1" to="road#2" fromLane="0" toLane="0" via=":mid_1_0" tl="stale" linkIndex="4" dir="s" state="O"/>
  <connection from="side_in" to="side_out" fromLane="0" toLane="0" via=":side_0_0" tl="stale" linkIndex="5" dir="s" state="O"/>
  <connection from="-road#1" to=":stale_w0" fromLane="0" toLane="0" dir="s" state="M"/>
  <tlLogic id="stale" type="actuated" programID="0" offset="0"><phase duration="1" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"-road#0": "-road#0", "road#0": "road#0"},
    )

    root = ET.parse(report["net_file"]).getroot()
    assert root.find("edge[@id='-road#1']") is None
    assert root.find("edge[@id='road#1']") is None
    rewired_in = root.find("connection[@from='-road#2'][@to='-road#0']")
    rewired_out = root.find("connection[@from='road#0'][@to='road#2']")
    assert rewired_in is not None
    assert rewired_out is not None
    assert rewired_in.attrib == {
        "from": "-road#2",
        "to": "-road#0",
        "fromLane": "0",
        "toLane": "0",
        "via": ":mid_0_0",
        "dir": "s",
        "state": "M",
    }
    assert rewired_out.attrib == {
        "from": "road#0",
        "to": "road#2",
        "fromLane": "0",
        "toLane": "0",
        "via": ":mid_1_0",
        "dir": "s",
        "state": "M",
    }
    assert root.find("connection[@from='-road#0'][@to=':stale_w0']") is None
    side_connection = root.find("connection[@from='side_in'][@to='side_out']")
    assert side_connection is not None
    assert "tl" not in side_connection.attrib
    assert "linkIndex" not in side_connection.attrib
    assert side_connection.attrib["state"] == "M"
    assert root.find("junction[@id='mid']").attrib["type"] == "priority"
    assert root.find("tlLogic[@id='stale']") is None
    assert report["removed_stale_split_fragment_edges"] == ["-road#1", "road#1"]
    assert report["rewired_stale_split_fragment_connection_count"] == 2


def test_write_teacher_target_internal_replay_net_keeps_existing_same_id_boundary_lane_in_junction(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="90,20 100,20"/></edge>
  <edge id="teacher_out" from="j" to="b"><lane id="teacher_out_0" index="0" shape="100,20 110,20"/></edge>
  <edge id="same_foot" from="p" to="j" type="highway.footway"><lane id="same_foot_0" index="0" allow="pedestrian" shape="100,20 100,25"/></edge>
  <edge id=":j_w0" function="walkingarea"><lane id=":j_w0_0" index="0" allow="pedestrian" shape="98,198 99,199"/></edge>
  <junction id="j" type="priority" x="100" y="200" shape="99,199 101,199" incLanes="teacher_in_0 same_foot_0" intLanes=":j_w0_0"/>
  <junction id="p" type="priority" x="100" y="25" incLanes="" intLanes=""/>
  <connection from="same_foot" to=":j_w0" fromLane="0" toLane="0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,20 10,20"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0" shape="10,20 20,20"/></edge>
  <edge id="same_foot" from="p" to="j" type="highway.footway"><lane id="same_foot_0" index="0" allow="pedestrian" shape="10,-160 10,-155"/></edge>
  <junction id="j" type="priority" x="10" y="20" shape="9,19 11,19" incLanes="cand_in_0 same_foot_0" intLanes=""/>
  <junction id="p" type="priority" x="10" y="-155" incLanes="" intLanes=""/>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    junction_inc_lanes = root.find("junction[@id='j']").attrib["incLanes"].split()
    assert "cand_in_0" in junction_inc_lanes
    assert "same_foot_0" in junction_inc_lanes
    assert root.find("connection[@from='same_foot'][@to=':j_w0']") is not None
    assert report["skipped_connection_count"] == 0


def test_write_teacher_target_internal_replay_net_replays_same_id_boundary_edge_endpoint(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="90,20 100,20"/></edge>
  <edge id="teacher_out" from="j" to="neighbor_cluster"><lane id="teacher_out_0" index="0" shape="100,20 120,20"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="100,20 101,20"/></edge>
  <junction id="j" type="priority" x="100" y="20" incLanes="teacher_in_0" intLanes=":j_0_0"/>
  <junction id="neighbor_cluster" type="priority" x="120" y="20" incLanes="teacher_out_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":j_0_0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,20 10,20"/></edge>
  <edge id="teacher_out" from="j" to="stale_neighbor"><lane id="teacher_out_0" index="0" shape="10,20 11,20"/></edge>
  <edge id=":j_old" function="internal"><lane id=":j_old_0" index="0" shape="10,20 11,20"/></edge>
  <junction id="j" type="priority" x="10" y="20" incLanes="cand_in_0" intLanes=":j_old_0"/>
  <junction id="stale_neighbor" type="priority" x="11" y="20" incLanes="teacher_out_0" intLanes=""/>
  <connection from="cand_in" to="teacher_out" fromLane="0" toLane="0" via=":j_old_0"/>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in"},
    )

    root = ET.parse(report["net_file"]).getroot()
    replayed_edge = root.find("edge[@id='teacher_out']")
    assert replayed_edge is not None
    assert replayed_edge.attrib["from"] == "j"
    assert replayed_edge.attrib["to"] == "neighbor_cluster"
    assert replayed_edge.find("lane").attrib["shape"] == "10.00,20.00 30.00,20.00"
    assert "teacher_out_0" in root.find("junction[@id='neighbor_cluster']").attrib["incLanes"]
    assert root.find("junction[@id='stale_neighbor']").attrib["incLanes"] == ""
    assert root.find("connection[@from='cand_in'][@to='teacher_out']").attrib["via"] == ":j_0_0"
    assert report["copied_boundary_edges"] == ["teacher_out"]
    assert report["skipped_boundary_edges"] == []


def test_write_teacher_target_internal_replay_net_ignores_same_tls_neighbor_internal_connections(
    tmp_path: Path,
) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="teacher_j"><lane id="teacher_in_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="teacher_out" from="teacher_j" to="b"><lane id="teacher_out_0" index="0" shape="10,0 20,0"/></edge>
  <edge id="neighbor_in" from="c" to="neighbor_j"><lane id="neighbor_in_0" index="0" shape="0,10 10,10"/></edge>
  <edge id="neighbor_out" from="neighbor_j" to="d"><lane id="neighbor_out_0" index="0" shape="10,10 20,10"/></edge>
  <edge id=":teacher_j_0" function="internal"><lane id=":teacher_j_0_0" index="0" shape="10,0 11,0"/></edge>
  <edge id=":neighbor_j_0" function="internal"><lane id=":neighbor_j_0_0" index="0" shape="10,10 11,10"/></edge>
  <junction id="teacher_j" type="traffic_light" x="10" y="0" incLanes="teacher_in_0" intLanes=":teacher_j_0_0"/>
  <junction id="neighbor_j" type="traffic_light" x="10" y="10" incLanes="neighbor_in_0" intLanes=":neighbor_j_0_0"/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":teacher_j_0_0" tl="teacher_j" linkIndex="0"/>
  <connection from="neighbor_in" to="neighbor_out" fromLane="0" toLane="0" via=":neighbor_j_0_0" tl="teacher_j" linkIndex="1"/>
  <tlLogic id="teacher_j" type="static" programID="0" offset="0"><phase duration="1" state="GG"/></tlLogic>
</net>""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="candidate_j"><lane id="cand_in_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="cand_out" from="candidate_j" to="b"><lane id="cand_out_0" index="0" shape="10,0 20,0"/></edge>
  <junction id="candidate_j" type="traffic_light" x="10" y="0" incLanes="cand_in_0" intLanes=""/>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="candidate_j",
        teacher_junction_id="teacher_j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    assert root.find("connection[@from='cand_in'][@to='cand_out']") is not None
    assert root.find("connection[@from='neighbor_in'][@to='neighbor_out']") is None
    assert report["copied_connection_count"] == 1
    assert report["skipped_connection_count"] == 0
    assert report["ignored_off_scope_tls_connection_count"] == 1


def test_write_teacher_target_internal_replay_net_replays_mapped_boundary_edge_shape(tmp_path: Path) -> None:
    teacher_net = tmp_path / "teacher.net.xml"
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0" shape="90,20 100,20"/></edge>
  <edge id="teacher_out" from="j" to="b"><lane id="teacher_out_0" index="0" shape="100,20 120,20"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="100,20 101,20"/></edge>
  <junction id="j" type="priority" x="100" y="20" incLanes="teacher_in_0" intLanes=":j_0_0"/>
  <junction id="b" type="priority" x="120" y="20" incLanes="teacher_out_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" via=":j_0_0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = tmp_path / "candidate.net.xml"
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0" shape="0,20 10,20"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0" shape="-1000,-1000 -990,-1000"/></edge>
  <edge id=":j_old" function="internal"><lane id=":j_old_0" index="0" shape="10,20 11,20"/></edge>
  <junction id="j" type="priority" x="10" y="20" incLanes="cand_in_0" intLanes=":j_old_0"/>
  <junction id="b" type="priority" x="30" y="20" incLanes="cand_out_0" intLanes=""/>
  <connection from="cand_in" to="cand_out" fromLane="0" toLane="0" via=":j_old_0"/>
</net>
""",
        encoding="utf-8",
    )

    report = write_teacher_target_internal_replay_net(
        candidate_net_file=candidate_net,
        teacher_net_file=teacher_net,
        output_file=tmp_path / "replayed.net.xml",
        junction_id="j",
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
    )

    root = ET.parse(report["net_file"]).getroot()
    replayed_edge = root.find("edge[@id='cand_out']")
    assert replayed_edge is not None
    assert replayed_edge.attrib["from"] == "j"
    assert replayed_edge.attrib["to"] == "b"
    assert replayed_edge.find("lane").attrib["id"] == "cand_out_0"
    assert replayed_edge.find("lane").attrib["shape"] == "10.00,20.00 30.00,20.00"
    assert root.find("connection[@from='cand_in'][@to='cand_out']").attrib["via"] == ":j_0_0"
    assert report["copied_boundary_edges"] == ["teacher_out"]
    assert report["skipped_boundary_edges"] == []


def test_stage_file_shortens_long_output_names(tmp_path: Path) -> None:
    output_dir = tmp_path / ("x" * 120)
    output_dir.mkdir()
    path = _stage_file(output_dir, "very_long_teacher_guided_prefix", "target_internal_normalized.net.xml")

    assert path.name == "target_internal_normalized.net.xml"
    assert len(str(path.resolve())) < 260


def test_stage_file_uses_short_alias_when_suffix_only_is_too_long(tmp_path: Path) -> None:
    output_dir = tmp_path
    while len(str(output_dir.resolve())) < 245:
        part_len = min(max(245 - len(str(output_dir.resolve())) - 1, 1), 50)
        output_dir /= "x" * part_len
    output_dir.mkdir(parents=True)

    path = _stage_file(output_dir, "very_long_teacher_guided_prefix", "target_internal_normalized.net.xml")

    assert path.name == "tin.net.xml"
    assert len(str(path.resolve())) < 260


def test_build_teacher_guided_junction_variant_replays_teacher_chain(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    teacher_net = Path("teacher.net.xml")
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j" type="highway.primary" numLanes="1">
    <lane id="teacher_in_0" index="0" disallow="pedestrian" shape="-10,0 0,0"/>
  </edge>
  <edge id="teacher_out" from="j" to="b" type="highway.primary" numLanes="1">
    <lane id="teacher_out_0" index="0" disallow="pedestrian" shape="0,0 10,0"/>
  </edge>
  <edge id="teacher_ped" from="p" to="j" type="highway.footway" numLanes="1">
    <lane id="teacher_ped_0" index="0" allow="pedestrian" shape="-2,2 0,0"/>
  </edge>
  <edge id=":j_c0" function="crossing" crossingEdges="teacher_in">
    <lane id=":j_c0_0" index="0" allow="pedestrian"/>
  </edge>
  <edge id=":j_w0" function="walkingarea">
    <lane id=":j_w0_0" index="0" allow="pedestrian"/>
  </edge>
  <junction id="j" type="traffic_light" incLanes="teacher_in_0 teacher_ped_0" intLanes=":j_c0_0 :j_w0_0"/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="j" linkIndex="0" dir="s" state="O"/>
  <connection from="teacher_ped" to=":j_w0" fromLane="0" toLane="0" dir="s" state="M"/>
  <connection from=":j_w0" to=":j_c0" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="s" state="M"/>
  <connection from=":j_c0" to=":j_w0" fromLane="0" toLane="0" dir="s" state="M"/>
  <tlLogic id="j" type="actuated" programID="0" offset="0">
    <phase duration="4" state="GM"/>
  </tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = Path("candidate.net.xml")
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="cand_ped" from="p" to="j" type="highway.footway"><lane id="cand_ped_0" index="0" allow="pedestrian" shape="-2,2 0,0"/></edge>
  <junction id="j" type="traffic_light" incLanes="cand_in_0 cand_ped_0" intLanes=""/>
</net>
""",
        encoding="utf-8",
    )
    raw_nodes = Path("raw.nod.xml")
    raw_nodes.write_text('<nodes><node id="a" x="-10" y="0"/><node id="j" x="0" y="0"/><node id="b" x="10" y="0"/></nodes>', encoding="utf-8")
    raw_edges = Path("raw.edg.xml")
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j" numLanes="1"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b" numLanes="1"><lane index="0"/></edge>
  <edge id="cand_ped" from="p" to="j" numLanes="1"><lane index="0" allow="pedestrian"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    raw_connections = Path("raw.con.xml")
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    raw_tllogics = Path("raw.tll.xml")
    raw_tllogics.write_text('<tlLogics><tlLogic id="j" type="static" programID="0" offset="0"/></tlLogics>', encoding="utf-8")
    calls: list[list[str]] = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        calls.append(command)
        if command[0] == "netconvert":
            assert "--sidewalks.guess" not in command
            assert "--tls.ignore-internal-junction-jam" in command
            assert "--tllogic-files" not in command
            assert Path(command[command.index("--node-files") + 1]).is_absolute()
            for flag in ("--edge-files", "--connection-files", "--output-file"):
                assert not Path(command[command.index(flag) + 1]).is_absolute()

            def command_path(flag: str) -> Path:
                value = Path(command[command.index(flag) + 1])
                return value if value.is_absolute() else Path(cwd) / value

            output_file = command_path("--output-file")
            connection_file = command_path("--connection-files")
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0" disallow="pedestrian" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0" disallow="pedestrian" shape="0,0 10,0"/></edge>
  <edge id="cand_ped" from="p" to="j" type="highway.footway"><lane id="cand_ped_0" index="0" allow="pedestrian" shape="-2,2 0,0"/></edge>
  <edge id=":j_cA" function="crossing" crossingEdges="cand_in"><lane id=":j_cA_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_wKeep" function="walkingarea"><lane id=":j_wKeep_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_wExtra" function="walkingarea"><lane id=":j_wExtra_0" index="0" allow="pedestrian"/></edge>
  <junction id="j" type="traffic_light" incLanes="cand_in_0 cand_ped_0 :j_wKeep_0 :j_wExtra_0" intLanes=":j_cA_0 :j_wKeep_0 :j_wExtra_0"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="rr"/></tlLogic>
  <connection from=":j_wKeep" to=":j_cA" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="s" state="M"/>
</net>
""",
                encoding="utf-8",
            )
            net_root = ET.parse(output_file).getroot()
            for connection in ET.parse(connection_file).getroot().findall("connection"):
                net_root.append(connection)
            ET.ElementTree(net_root).write(output_file, encoding="utf-8", xml_declaration=True)

        class Result:
            status = "pass"
            returncode = 0

            def to_dict(self):
                return {"command": command, "cwd": str(cwd) if cwd else None, "status": "pass", "returncode": 0}

        return Result()

    report = build_teacher_guided_junction_variant(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        raw_tllogic_file=raw_tllogics,
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        junction_id="j",
        output_dir=Path("out"),
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out", "teacher_ped": "cand_ped"},
        prefix="demo",
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["final_net_file"].endswith("demo_teacher_guided.net.xml")
    assert report["parity"]["delta"]["vehicle_connection_count"] == 0
    assert report["parity"]["delta"]["pedestrian_connection_count"] == 0
    assert report["parity"]["delta"]["walkingarea_count"] == 0
    assert report["parity"]["delta"]["tl_phase_count"] == 0
    root = ET.parse(report["final_net_file"]).getroot()
    assert root.find("tlLogic[@id='j']").attrib["type"] == "actuated"
    assert root.find("edge[@id=':j_wExtra']") is None
    vehicle_connection = root.find("connection[@from='cand_in'][@to='cand_out']")
    assert vehicle_connection.attrib["tl"] == "j"
    assert vehicle_connection.attrib["linkIndex"] == "0"
    assert vehicle_connection.attrib["dir"] == "s"
    assert vehicle_connection.attrib["state"] == "O"
    assert [call[0] for call in calls] == ["netconvert", "sumo"]


def test_build_teacher_guided_junction_variant_synthesizes_missing_copied_edge_types(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    teacher_net = Path("teacher.net.xml")
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j" type="highway.primary"><lane id="teacher_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="j" to="b" priority="6" type="highway.secondary_link">
    <lane id="teacher_out_0" index="0" speed="13.89" shape="0,0 10,0"/>
  </edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <junction id="b" type="priority" x="10" y="0" incLanes="teacher_out_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = Path("candidate.net.xml")
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>
""",
        encoding="utf-8",
    )
    raw_nodes = Path("raw.nod.xml")
    raw_nodes.write_text(
        '<nodes><node id="a" x="-10" y="0"/><node id="j" x="0" y="0"/><node id="b" x="10" y="0"/></nodes>',
        encoding="utf-8",
    )
    raw_edges = Path("raw.edg.xml")
    raw_edges.write_text('<edges><edge id="cand_in" from="a" to="j"><lane index="0"/></edge></edges>', encoding="utf-8")
    raw_connections = Path("raw.con.xml")
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    raw_types = Path("raw.typ.xml")
    raw_types.write_text('<types><type id="highway.primary" priority="12" speed="13.89"/></types>', encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert":
            type_file = Path(cwd) / command[command.index("--type-files") + 1]
            assert ET.parse(type_file).getroot().find("type[@id='highway.secondary_link']") is not None
            output = Path(cwd) / command[command.index("--output-file") + 1]
            output.write_text(
                """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="teacher_out" from="j" to="b" priority="6" type="highway.secondary_link">
    <lane id="teacher_out_0" index="0" speed="13.89" shape="0,0 10,0"/>
  </edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
  <junction id="b" type="priority" x="10" y="0" incLanes="teacher_out_0" intLanes=""/>
  <connection from="cand_in" to="teacher_out" fromLane="0" toLane="0" dir="s" state="M"/>
</net>
""",
                encoding="utf-8",
            )

        class Result:
            status = "pass"
            returncode = 0

            def to_dict(self):
                return {"command": command, "cwd": str(cwd) if cwd else None, "status": "pass", "returncode": 0}

        return Result()

    report = build_teacher_guided_junction_variant(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        raw_type_file=raw_types,
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        junction_id="j",
        output_dir=Path("out"),
        edge_map={"teacher_in": "cand_in", "teacher_out": "teacher_out"},
        prefix="demo",
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["type_patch"]["synthesized_edge_type_ids"] == ["highway.secondary_link"]


def test_build_teacher_guided_junction_variant_restores_non_target_internal_artifacts_after_plain_roundtrip(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    teacher_net = Path("teacher.net.xml")
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j"><lane id="teacher_in_0" index="0"/></edge>
  <edge id="teacher_out" from="j" to="b"><lane id="teacher_out_0" index="0"/></edge>
  <junction id="j" type="priority" incLanes="teacher_in_0" intLanes="">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = Path("candidate.net.xml")
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0"/></edge>
  <edge id="remote_in" from="x" to="other"><lane id="remote_in_0" index="0"/></edge>
  <edge id="remote_out" from="other" to="y"><lane id="remote_out_0" index="0"/></edge>
  <edge id=":other_w0" function="walkingarea"><lane id=":other_w0_0" index="0" allow="pedestrian" speed="1.23"/></edge>
  <junction id="j" type="priority" incLanes="cand_in_0" intLanes=""/>
  <junction id="other" type="priority" incLanes="remote_in_0" intLanes=":other_w0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <connection from="remote_in" to=":other_w0" fromLane="0" toLane="0"/>
  <connection from=":other_w0" to="remote_out" fromLane="0" toLane="0"/>
</net>
""",
        encoding="utf-8",
    )
    raw_nodes = Path("raw.nod.xml")
    raw_nodes.write_text('<nodes><node id="a" x="0" y="0"/><node id="j" x="1" y="0"/><node id="b" x="2" y="0"/></nodes>', encoding="utf-8")
    raw_edges = Path("raw.edg.xml")
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane index="0"/></edge>
  <edge id="remote_in" from="x" to="other"><lane index="0"/></edge>
  <edge id="remote_out" from="other" to="y"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    raw_connections = Path("raw.con.xml")
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    sumo_calls = 0

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        nonlocal sumo_calls
        if command[0] == "netconvert" and "--node-files" in command:
            output = Path(cwd) / command[command.index("--output-file") + 1]
            output.write_text(
                """<net>
  <edge id="cand_in" from="a" to="j"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane id="cand_out_0" index="0"/></edge>
  <edge id="remote_in" from="x" to="other"><lane id="remote_in_0" index="0"/></edge>
  <edge id="remote_out" from="other" to="y"><lane id="remote_out_0" index="0"/></edge>
  <edge id=":other_w0" function="walkingarea"><lane id=":other_w0_0" index="0" allow="pedestrian" speed="9.99"/></edge>
  <edge id=":other_w_extra" function="walkingarea"><lane id=":other_w_extra_0" index="0" allow="pedestrian"/></edge>
  <junction id="j" type="priority" incLanes="cand_in_0" intLanes=""/>
  <junction id="other" type="priority" incLanes="remote_in_0" intLanes=":other_w0_0 :other_w_extra_0">
    <request index="0" response="00" foes="00" cont="0"/>
    <request index="1" response="00" foes="00" cont="0"/>
  </junction>
  <connection from="remote_in" to=":other_w0" fromLane="0" toLane="0"/>
  <connection from=":other_w0" to="remote_out" fromLane="0" toLane="0"/>
  <connection from="remote_in" to=":other_w_extra" fromLane="0" toLane="0"/>
  <connection from=":other_w_extra" to="remote_out" fromLane="0" toLane="0"/>
</net>
""",
                encoding="utf-8",
            )
        elif command[0] == "netconvert" and "--sumo-net-file" in command:
            input_file = Path(cwd) / command[command.index("--sumo-net-file") + 1]
            output = Path(cwd) / command[command.index("--output-file") + 1]
            root = ET.parse(input_file).getroot()
            root.find("edge[@id=':other_w0']/lane").set("speed", "9.99")
            root.append(ET.Element("edge", {"id": ":other_w_extra", "function": "walkingarea"}))
            ET.SubElement(root.find("edge[@id=':other_w_extra']"), "lane", {"id": ":other_w_extra_0", "index": "0", "allow": "pedestrian"})
            other = root.find("junction[@id='other']")
            other.set("intLanes", f"{other.attrib.get('intLanes', '')} :other_w_extra_0".strip())
            ET.SubElement(other, "request", {"index": "1", "response": "00", "foes": "00", "cont": "0"})
            root.append(ET.Element("connection", {"from": "remote_in", "to": ":other_w_extra", "fromLane": "0", "toLane": "0"}))
            root.append(ET.Element("connection", {"from": ":other_w_extra", "to": "remote_out", "fromLane": "0", "toLane": "0"}))
            ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
        elif command[0] == "sumo":
            sumo_calls += 1

        class Result:
            status = "fail" if command[0] == "sumo" and sumo_calls == 1 else "pass"
            returncode = 1 if status == "fail" else 0

            def to_dict(self):
                return {"command": command, "cwd": str(cwd) if cwd else None, "status": self.status, "returncode": self.returncode}

        return Result()

    report = build_teacher_guided_junction_variant(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        junction_id="j",
        output_dir=Path("out"),
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        prefix="demo",
        replay_target_internal_subgraph=True,
        command_runner=fake_runner,
    )

    root = ET.parse(report["final_net_file"]).getroot()
    assert report["status"] == "pass"
    assert root.find("edge[@id=':other_w0']/lane").attrib["speed"] == "1.23"
    assert root.find("edge[@id=':other_w_extra']") is None
    assert root.find("junction[@id='other']").attrib["intLanes"] == ":other_w0_0"
    assert len(root.find("junction[@id='other']").findall("request")) == 1
    assert root.find("connection[@from='remote_in'][@to=':other_w_extra']") is None


def test_restore_non_target_internal_artifacts_filters_stale_incoming_lanes(tmp_path: Path) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text(
        """<net>
  <edge id="remote_in" from="x" to="other"><lane id="remote_in_0" index="0"/></edge>
  <edge id="remote_out" from="other" to="y"><lane id="remote_out_0" index="0"/></edge>
  <edge id=":other_w0" function="walkingarea"><lane id=":other_w0_0" index="0" allow="pedestrian"/></edge>
  <junction id="other" type="priority" incLanes="remote_in_0 :stale_missing_0" intLanes=":other_w0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <connection from="remote_in" to=":other_w0" fromLane="0" toLane="0"/>
</net>
""",
        encoding="utf-8",
    )
    target = tmp_path / "target.net.xml"
    target.write_text(
        """<net>
  <edge id="remote_in" from="x" to="other"><lane id="remote_in_0" index="0"/></edge>
  <edge id="remote_out" from="other" to="y"><lane id="remote_out_0" index="0"/></edge>
  <edge id=":other_w0" function="walkingarea"><lane id=":other_w0_0" index="0" allow="pedestrian"/></edge>
  <edge id=":other_w_extra" function="walkingarea"><lane id=":other_w_extra_0" index="0" allow="pedestrian"/></edge>
  <junction id="other" type="traffic_light" incLanes="remote_in_0 :other_w_extra_0" intLanes=":other_w0_0 :other_w_extra_0">
    <request index="0" response="00" foes="00" cont="0"/>
    <request index="1" response="00" foes="00" cont="0"/>
  </junction>
  <connection from="remote_in" to=":other_w0" fromLane="0" toLane="0"/>
  <connection from="remote_in" to=":other_w_extra" fromLane="0" toLane="0"/>
</net>
""",
        encoding="utf-8",
    )

    report = _restore_non_target_internal_artifacts(
        source_file=source,
        target_file=target,
        exclude_junction_ids=set(),
    )

    root = ET.parse(target).getroot()
    junction = root.find("junction[@id='other']")
    assert report["status"] == "pass"
    assert junction.attrib["type"] == "priority"
    assert junction.attrib["incLanes"] == "remote_in_0"
    assert junction.attrib["intLanes"] == ":other_w0_0"
    assert len(junction.findall("request")) == 1


def test_restore_non_target_internal_artifacts_caches_repeated_internal_owner_lookup(tmp_path: Path) -> None:
    normal_junctions = "".join(
        f'<junction id="j{index}" type="priority" x="0" y="0"/>\n'
        for index in range(1500)
    )
    repeated_connections = "".join(
        '<connection from=":j42_0" to=":j42_0" fromLane="0" toLane="0"/>\n'
        for _ in range(1500)
    )
    net_xml = (
        "<net>\n"
        f"{normal_junctions}"
        '<edge id=":j42_0" function="internal"><lane id=":j42_0_0" index="0"/></edge>\n'
        '<junction id=":j42_0" type="internal" x="0" y="0" incLanes="" intLanes=""/>\n'
        f"{repeated_connections}"
        "</net>"
    )
    source_net = tmp_path / "source.net.xml"
    target_net = tmp_path / "target.net.xml"
    source_net.write_text(net_xml, encoding="utf-8")
    target_net.write_text(net_xml, encoding="utf-8")

    start = time.perf_counter()
    report = _restore_non_target_internal_artifacts(
        source_file=source_net,
        target_file=target_net,
        exclude_junction_ids=set(),
    )
    elapsed = time.perf_counter() - start

    assert report["status"] == "pass"
    assert elapsed < 1.0


def test_restore_non_target_internal_artifacts_restores_referenced_tllogic_capacity(tmp_path: Path) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text(
        """<net>
  <edge id="remote_in" from="x" to="other"><lane id="remote_in_0" index="0"/></edge>
  <edge id="remote_out" from="other" to="y"><lane id="remote_out_0" index="0"/></edge>
  <edge id=":other_0" function="internal"><lane id=":other_0_0" index="0"/></edge>
  <junction id="other" type="traffic_light" incLanes="remote_in_0" intLanes=":other_0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <connection from="remote_in" to="remote_out" fromLane="0" toLane="0" via=":other_0_0" tl="tls" linkIndex="8"/>
  <tlLogic id="tls" type="actuated" programID="0" offset="0">
    <phase duration="5" state="rrrrrrrrG"/>
  </tlLogic>
</net>
""",
        encoding="utf-8",
    )
    target = tmp_path / "target.net.xml"
    target.write_text(
        """<net>
  <edge id="remote_in" from="x" to="other"><lane id="remote_in_0" index="0"/></edge>
  <edge id="remote_out" from="other" to="y"><lane id="remote_out_0" index="0"/></edge>
  <edge id=":other_0" function="internal"><lane id=":other_0_0" index="0"/></edge>
  <junction id="other" type="traffic_light" incLanes="remote_in_0" intLanes=":other_0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <tlLogic id="tls" type="actuated" programID="0" offset="0">
    <phase duration="5" state="rr"/>
  </tlLogic>
</net>
""",
        encoding="utf-8",
    )

    report = _restore_non_target_internal_artifacts(
        source_file=source,
        target_file=target,
        exclude_junction_ids=set(),
    )

    root = ET.parse(target).getroot()
    assert report["status"] == "pass"
    assert root.find("connection[@tl='tls']").attrib["linkIndex"] == "8"
    assert root.find("tlLogic[@id='tls']/phase").attrib["state"] == "rrrrrrrrG"


def test_restore_non_target_internal_artifacts_skips_connections_with_missing_edges(tmp_path: Path) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text(
        """<net>
  <edge id="remote_in" from="x" to="other"><lane id="remote_in_0" index="0"/></edge>
  <edge id=":other_0" function="internal"><lane id=":other_0_0" index="0"/></edge>
  <junction id="other" type="priority" incLanes="remote_in_0" intLanes=":other_0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <connection from="remote_in" to="missing_out" fromLane="0" toLane="0" via=":other_0_0"/>
</net>
""",
        encoding="utf-8",
    )
    target = tmp_path / "target.net.xml"
    target.write_text(
        """<net>
  <edge id="remote_in" from="x" to="other"><lane id="remote_in_0" index="0"/></edge>
  <edge id=":other_0" function="internal"><lane id=":other_0_0" index="0"/></edge>
  <junction id="other" type="priority" incLanes="remote_in_0" intLanes=":other_0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
</net>
""",
        encoding="utf-8",
    )

    report = _restore_non_target_internal_artifacts(
        source_file=source,
        target_file=target,
        exclude_junction_ids=set(),
    )

    root = ET.parse(target).getroot()
    assert report["status"] == "pass"
    assert report["skipped_non_target_internal_connection_missing_edge_count"] == 1
    assert root.find("connection[@to='missing_out']") is None


def test_restore_non_target_internal_artifacts_skips_internal_edges_with_missing_normal_endpoints(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text(
        """<net>
  <edge id="remote_in" from="x" to="other"><lane id="remote_in_0" index="0"/></edge>
  <edge id=":other_0" from="missing_normal" to="other" function="internal"><lane id=":other_0_0" index="0"/></edge>
  <edge id=":missing_owner_0" function="internal"><lane id=":missing_owner_0_0" index="0"/></edge>
  <junction id="other" type="priority" incLanes="remote_in_0" intLanes=":other_0_0"/>
  <junction id="missing_owner" type="priority" incLanes="" intLanes=":missing_owner_0_0"/>
</net>
""",
        encoding="utf-8",
    )
    target = tmp_path / "target.net.xml"
    target.write_text(
        """<net>
  <edge id="remote_in" from="x" to="other"><lane id="remote_in_0" index="0"/></edge>
  <junction id="other" type="priority" incLanes="remote_in_0" intLanes=""/>
</net>
""",
        encoding="utf-8",
    )

    report = _restore_non_target_internal_artifacts(
        source_file=source,
        target_file=target,
        exclude_junction_ids=set(),
    )

    root = ET.parse(target).getroot()
    assert report["status"] == "pass"
    assert report["restored_non_target_internal_edge_count"] == 0
    assert report["skipped_non_target_internal_edge_missing_junction_count"] == 2
    assert root.find("edge[@id=':other_0']") is None
    assert root.find("edge[@id=':missing_owner_0']") is None


def test_build_teacher_guided_junction_variant_can_replay_and_normalize_target_internal_subgraph(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    teacher_net = Path("teacher.net.xml")
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j" type="highway.primary" numLanes="1">
    <lane id="teacher_in_0" index="0" disallow="pedestrian" shape="-10,0 0,0"/>
  </edge>
  <edge id="teacher_out" from="j" to="b" type="highway.primary" numLanes="1">
    <lane id="teacher_out_0" index="0" disallow="pedestrian" shape="0,0 10,0"/>
  </edge>
  <edge id="teacher_ped" from="p" to="j" type="highway.footway" numLanes="1">
    <lane id="teacher_ped_0" index="0" allow="pedestrian" shape="-2,2 0,0"/>
  </edge>
  <edge id=":j_c0" function="crossing" crossingEdges="teacher_in">
    <lane id=":j_c0_0" index="0" allow="pedestrian"/>
  </edge>
  <edge id=":j_w0" function="walkingarea">
    <lane id=":j_w0_0" index="0" allow="pedestrian"/>
  </edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="teacher_in_0 teacher_ped_0" intLanes=":j_c0_0 :j_w0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="j" linkIndex="0" dir="s" state="O"/>
  <connection from="teacher_ped" to=":j_w0" fromLane="0" toLane="0" dir="s" state="M"/>
  <connection from=":j_w0" to=":j_c0" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="s" state="M"/>
  <connection from=":j_c0" to=":j_w0" fromLane="0" toLane="0" dir="s" state="M"/>
  <tlLogic id="j" type="actuated" programID="0" offset="0">
    <phase duration="4" state="GM"/>
  </tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = Path("candidate.net.xml")
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="cand_ped" from="p" to="j" type="highway.footway"><lane id="cand_ped_0" index="0" allow="pedestrian" shape="-2,2 0,0"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="cand_in_0 cand_ped_0" intLanes=""/>
</net>
""",
        encoding="utf-8",
    )
    raw_nodes = Path("raw.nod.xml")
    raw_nodes.write_text('<nodes><node id="a" x="-10" y="0"/><node id="j" x="0" y="0"/><node id="b" x="10" y="0"/></nodes>', encoding="utf-8")
    raw_edges = Path("raw.edg.xml")
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j" numLanes="1"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b" numLanes="1"><lane index="0"/></edge>
  <edge id="cand_ped" from="p" to="j" numLanes="1"><lane index="0" allow="pedestrian"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    raw_connections = Path("raw.con.xml")
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    raw_tllogics = Path("raw.tll.xml")
    raw_tllogics.write_text('<tlLogics><tlLogic id="j" type="static" programID="0" offset="0"/></tlLogics>', encoding="utf-8")
    calls: list[list[str]] = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        calls.append(command)
        if command[0] == "netconvert" and "--node-files" in command:
            assert Path(command[command.index("--node-files") + 1]).is_absolute()
            assert "--tllogic-files" not in command
            for flag in ("--edge-files", "--connection-files", "--output-file"):
                assert not Path(command[command.index(flag) + 1]).is_absolute()

            def command_path(flag: str) -> Path:
                value = Path(command[command.index(flag) + 1])
                return value if value.is_absolute() else Path(cwd) / value

            output_file = command_path("--output-file")
            connection_file = command_path("--connection-files")
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0" disallow="pedestrian" shape="-10,0 0,0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0" disallow="pedestrian" shape="0,0 10,0"/></edge>
  <edge id="cand_ped" from="p" to="j" type="highway.footway"><lane id="cand_ped_0" index="0" allow="pedestrian" shape="-2,2 0,0"/></edge>
  <edge id=":j_cA" function="crossing" crossingEdges="cand_in"><lane id=":j_cA_0" index="0" allow="pedestrian"/></edge>
  <edge id=":j_wKeep" function="walkingarea"><lane id=":j_wKeep_0" index="0" allow="pedestrian"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="cand_in_0 cand_ped_0 :j_wKeep_0" intLanes=":j_cA_0 :j_wKeep_0"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="rr"/></tlLogic>
  <connection from=":j_wKeep" to=":j_cA" fromLane="0" toLane="0" tl="j" linkIndex="1" dir="s" state="M"/>
</net>
""",
                encoding="utf-8",
            )
            net_root = ET.parse(output_file).getroot()
            for connection in ET.parse(connection_file).getroot().findall("connection"):
                net_root.append(connection)
            ET.ElementTree(net_root).write(output_file, encoding="utf-8", xml_declaration=True)
        elif command[0] == "netconvert" and "--sumo-net-file" in command:
            assert not Path(command[command.index("--sumo-net-file") + 1]).is_absolute()
            assert not Path(command[command.index("--output-file") + 1]).is_absolute()

            def command_path(flag: str) -> Path:
                value = Path(command[command.index(flag) + 1])
                return value if value.is_absolute() else Path(cwd) / value

            input_file = command_path("--sumo-net-file")
            output_file = command_path("--output-file")
            output_file.write_text(input_file.read_text(encoding="utf-8"), encoding="utf-8")

        class Result:
            status = "pass"
            returncode = 0

            def to_dict(self):
                return {"command": command, "cwd": str(cwd) if cwd else None, "status": "pass", "returncode": 0}

        return Result()

    report = build_teacher_guided_junction_variant(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        junction_id="j",
        output_dir=Path("out"),
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out", "teacher_ped": "cand_ped"},
        prefix="demo",
        raw_tllogic_file=raw_tllogics,
        replay_target_internal_subgraph=True,
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["parity_gate_status"] == "pass"
    assert report["review_policy"].startswith("diagnostic")
    assert report["target_internal_replay"]["copied_internal_edge_count"] == 2
    assert report["target_internal_replay"]["copied_internal_junction_count"] == 0
    assert report["connection_plan"]["emit_crossings"] is False
    assert report["connection_plan"]["emitted_crossing_count"] == 0
    assert report["target_internal_normalize"] is None
    assert report["target_internal_pedestrian_ring"] is None
    assert report["target_internal_vehicle_connection_attrs"] is None
    assert report["parity"]["delta"]["vehicle_connection_count"] == 0
    assert report["parity"]["delta"]["pedestrian_connection_count"] == 0
    root = ET.parse(report["final_net_file"]).getroot()
    assert root.find("edge[@id=':j_c0']") is not None
    assert [call[0] for call in calls] == ["netconvert", "sumo"]


def test_build_teacher_guided_junction_variant_reports_tls_movement_parity(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    teacher_net = Path("teacher.net.xml")
    teacher_net.write_text(
        """<net>
  <edge id="in" from="a" to="j" type="highway.primary"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b" type="highway.primary"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0" tl="j" linkIndex="0" dir="s" state="O"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="10" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = Path("candidate.net.xml")
    candidate_net.write_text(
        """<net>
  <edge id="in" from="a" to="j" type="highway.primary"><lane id="in_0" index="0"/></edge>
  <edge id="out" from="j" to="b" type="highway.primary"><lane id="out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="in_0" intLanes=""/>
</net>
""",
        encoding="utf-8",
    )
    raw_nodes = Path("raw.nod.xml")
    raw_nodes.write_text('<nodes><node id="a" x="-10" y="0"/><node id="j" x="0" y="0"/><node id="b" x="10" y="0"/></nodes>', encoding="utf-8")
    raw_edges = Path("raw.edg.xml")
    raw_edges.write_text(
        """<edges>
  <edge id="in" from="a" to="j"><lane index="0"/></edge>
  <edge id="out" from="j" to="b"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    raw_connections = Path("raw.con.xml")
    raw_connections.write_text("<connections/>\n", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            connection_file = Path(cwd) / command[command.index("--connection-files") + 1]
            output_file.write_text(candidate_net.read_text(encoding="utf-8"), encoding="utf-8")
            root = ET.parse(output_file).getroot()
            for connection in ET.parse(connection_file).getroot().findall("connection"):
                root.append(connection)
            ET.ElementTree(root).write(output_file, encoding="utf-8", xml_declaration=True)

        class Result:
            status = "pass"
            returncode = 0

            def to_dict(self):
                return {"command": command, "cwd": str(cwd) if cwd else None, "status": "pass", "returncode": 0}

        return Result()

    report = build_teacher_guided_junction_variant(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        junction_id="j",
        output_dir=Path("out"),
        edge_map={"in": "in", "out": "out"},
        prefix="demo",
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["parity_gate_status"] == "pass"
    assert report["tls_movement_parity"]["status"] == "pass"
    assert report["tls_movement_parity"]["teacher_connection_count"] == 1
    assert report["tls_movement_parity"]["candidate_connection_count"] == 1
    assert report["tls_movement_parity"]["movement_signature_equal_after_internal_id_normalization"] is True
    assert report["tls_movement_parity"]["tl_logic_phase_states_equal"] is True
    assert report["semantic_layer_gates"]["topology"]["status"] == "pass"
    assert report["semantic_layer_gates"]["movement_tls"]["status"] == "pass"
    assert report["semantic_layer_gates"]["pedestrian_bike"]["status"] == "pass"
    assert report["semantic_layer_gates"]["internal"]["status"] == "pass"


def test_build_teacher_guided_junction_variant_normalizes_replay_before_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    teacher_net = Path("teacher.net.xml")
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j" type="highway.primary"><lane id="teacher_in_0" index="0"/></edge>
  <edge id="teacher_out" from="j" to="b" type="highway.primary"><lane id="teacher_out_0" index="0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = Path("candidate.net.xml")
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>
""",
        encoding="utf-8",
    )
    raw_nodes = Path("raw.nod.xml")
    raw_nodes.write_text('<nodes><node id="a" x="-10" y="0"/><node id="j" x="0" y="0"/><node id="b" x="10" y="0"/></nodes>', encoding="utf-8")
    raw_edges = Path("raw.edg.xml")
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    raw_connections = Path("raw.con.xml")
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    calls: list[list[str]] = []
    normalized = False

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        nonlocal normalized
        calls.append(command)

        def command_path(flag: str) -> Path:
            value = Path(command[command.index(flag) + 1])
            return value if value.is_absolute() else Path(cwd) / value

        if command[0] == "netconvert" and "--node-files" in command:
            output_file = command_path("--output-file")
            connection_file = command_path("--connection-files")
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>
""",
                encoding="utf-8",
            )
            root = ET.parse(output_file).getroot()
            for connection in ET.parse(connection_file).getroot().findall("connection"):
                root.append(connection)
            ET.ElementTree(root).write(output_file, encoding="utf-8", xml_declaration=True)
        elif command[0] == "netconvert" and "--sumo-net-file" in command:
            normalized = True
            command_path("--output-file").write_text(
                command_path("--sumo-net-file").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

        class Result:
            status = "pass"
            returncode = 0

            def to_dict(self):
                status = "pass"
                if command[0] == "sumo" and not normalized:
                    status = "fail"
                return {
                    "command": command,
                    "cwd": str(cwd) if cwd else None,
                    "status": status,
                    "returncode": 0 if status == "pass" else 1,
                    "stderr": "" if status == "pass" else "replay load failed before normalization",
                }

        return Result()

    report = build_teacher_guided_junction_variant(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        junction_id="j",
        output_dir=Path("out"),
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        prefix="demo",
        replay_target_internal_subgraph=True,
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["target_internal_replay_fallback"] is False
    assert report["target_internal_normalize"]["status"] == "pass"
    assert report["sumo_load"]["status"] == "pass"
    assert report["final_net_file"].endswith("demo_teacher_guided.net.xml")
    assert [call[0] for call in calls] == ["netconvert", "sumo", "netconvert", "sumo"]


def test_build_teacher_guided_junction_variant_uses_unrestored_normalized_replay_before_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    teacher_net = Path("teacher.net.xml")
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j" type="highway.primary"><lane id="teacher_in_0" index="0"/></edge>
  <edge id="teacher_out" from="j" to="b" type="highway.primary"><lane id="teacher_out_0" index="0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = Path("candidate.net.xml")
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0"/></edge>
  <edge id="remote_in" from="x" to="other" type="highway.primary"><lane id="remote_in_0" index="0"/></edge>
  <edge id=":other_0" function="internal"><lane id=":other_0_0" index="0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
  <junction id="other" type="priority" x="1" y="1" incLanes="remote_in_0" intLanes=":other_0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <junction id=":other_0_0" type="internal" x="1" y="1" incLanes="remote_in_0" intLanes=""/>
</net>
""",
        encoding="utf-8",
    )
    raw_nodes = Path("raw.nod.xml")
    raw_nodes.write_text('<nodes><node id="a" x="-10" y="0"/><node id="j" x="0" y="0"/><node id="b" x="10" y="0"/></nodes>', encoding="utf-8")
    raw_edges = Path("raw.edg.xml")
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    raw_connections = Path("raw.con.xml")
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    sumo_inputs: list[str] = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        def command_path(flag: str) -> Path:
            value = Path(command[command.index(flag) + 1])
            return value if value.is_absolute() else Path(cwd) / value

        if command[0] == "netconvert" and "--node-files" in command:
            output_file = command_path("--output-file")
            connection_file = command_path("--connection-files")
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0"/></edge>
  <edge id="remote_in" from="x" to="other" type="highway.primary"><lane id="remote_in_0" index="0"/></edge>
  <edge id=":other_0" function="internal"><lane id=":other_0_0" index="0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
  <junction id="other" type="priority" x="1" y="1" incLanes="remote_in_0" intLanes=":other_0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <junction id=":other_0_0" type="internal" x="1" y="1" incLanes="remote_in_0" intLanes=""/>
</net>
""",
                encoding="utf-8",
            )
            root = ET.parse(output_file).getroot()
            for connection in ET.parse(connection_file).getroot().findall("connection"):
                root.append(connection)
            ET.ElementTree(root).write(output_file, encoding="utf-8", xml_declaration=True)
        elif command[0] == "netconvert" and "--sumo-net-file" in command:
            command_path("--output-file").write_text(
                command_path("--sumo-net-file").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

        class Result:
            status = "pass"
            returncode = 0

            def to_dict(self):
                status = "pass"
                if command[0] == "sumo":
                    net_file = Path(command[command.index("-n") + 1]).name
                    sumo_inputs.append(net_file)
                    status = "pass" if sumo_inputs == [
                        "demo_teacher_guided.net.xml",
                        "demo_teacher_guided.net.xml",
                        "demo_teacher_guided.net.xml",
                    ] else "fail"
                return {
                    "command": command,
                    "cwd": str(cwd) if cwd else None,
                    "status": status,
                    "returncode": 0 if status == "pass" else 1,
                    "stderr": "" if status == "pass" else "restored replay load failed",
                }

        return Result()

    report = build_teacher_guided_junction_variant(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        junction_id="j",
        output_dir=Path("out"),
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        prefix="demo",
        replay_target_internal_subgraph=True,
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["target_internal_replay_fallback"] is False
    assert report["target_internal_normalize"]["unrestored_sumo_load"]["status"] == "pass"
    assert report["final_net_file"].endswith("demo_teacher_guided.net.xml")
    assert sumo_inputs == [
        "demo_teacher_guided.net.xml",
        "demo_teacher_guided.net.xml",
        "demo_teacher_guided.net.xml",
    ]


def test_build_teacher_guided_junction_variant_normalizes_final_teacher_guided_net(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    teacher_net = Path("teacher.net.xml")
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j" type="highway.primary"><lane id="teacher_in_0" index="0"/></edge>
  <edge id="teacher_out" from="j" to="b" type="highway.primary"><lane id="teacher_out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" tl="j" linkIndex="0" dir="s" state="O"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = Path("candidate.net.xml")
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>
""",
        encoding="utf-8",
    )
    raw_nodes = Path("raw.nod.xml")
    raw_nodes.write_text(
        '<nodes><node id="a" x="-10" y="0"/><node id="j" x="0" y="0"/><node id="b" x="10" y="0"/></nodes>',
        encoding="utf-8",
    )
    raw_edges = Path("raw.edg.xml")
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    raw_connections = Path("raw.con.xml")
    raw_connections.write_text("<connections/>\n", encoding="utf-8")
    sumo_inputs: list[str] = []
    normalized_outputs: list[str] = []

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        def command_path(flag: str) -> Path:
            value = Path(command[command.index(flag) + 1])
            return value if value.is_absolute() else Path(cwd) / value

        if command[0] == "netconvert" and "--node-files" in command:
            output_file = command_path("--output-file")
            connection_file = command_path("--connection-files")
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>
""",
                encoding="utf-8",
            )
            root = ET.parse(output_file).getroot()
            for connection in ET.parse(connection_file).getroot().findall("connection"):
                root.append(connection)
            ET.ElementTree(root).write(output_file, encoding="utf-8", xml_declaration=True)
        elif command[0] == "netconvert" and "--sumo-net-file" in command:
            output_file = command_path("--output-file")
            normalized_outputs.append(output_file.name)
            output_file.write_text(
                command_path("--sumo-net-file").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

        class Result:
            status = "pass"
            returncode = 0

            def to_dict(self):
                status = "pass"
                if command[0] == "sumo":
                    net_file = Path(command[command.index("-n") + 1]).name
                    sumo_inputs.append(net_file)
                    status = "pass" if net_file == "tg_norm.net.xml" else "fail"
                return {
                    "command": command,
                    "cwd": str(cwd) if cwd else None,
                    "status": status,
                    "returncode": 0 if status == "pass" else 1,
                    "stderr": "" if status == "pass" else "final teacher-guided load failed before normalization",
                }

        return Result()

    report = build_teacher_guided_junction_variant(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        junction_id="j",
        output_dir=Path("out"),
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        prefix="demo",
        replay_target_internal_subgraph=True,
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["target_internal_replay_fallback"] is False
    assert report["target_internal_normalize"]["status"] == "pass"
    assert report["teacher_guided_normalize"]["status"] == "pass"
    assert report["final_net_file"].endswith("tg_norm.net.xml")
    assert report["teacher_guided_normalized_net_file"].endswith("tg_norm.net.xml")
    assert sumo_inputs == ["demo_teacher_guided.net.xml", "demo_teacher_guided.net.xml", "tg_norm.net.xml"]
    assert normalized_outputs == ["demo_target_internal_normalized.net.xml", "tg_norm.net.xml"]


def test_build_teacher_guided_junction_variant_compares_replay_effective_edge_map(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    teacher_net = Path("teacher.net.xml")
    teacher_net.write_text(
        """<net>
  <edge id="main#2" from="a" to="j"><lane id="main#2_0" index="0" shape="0,0 10,0"/></edge>
  <edge id="main#3" from="j" to="b"><lane id="main#3_0" index="0" shape="10,0 20,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="10,0 11,0"/></edge>
  <junction id="a" x="0" y="0"/>
  <junction id="j" type="traffic_light" x="10" y="0" incLanes="main#2_0" intLanes=":j_0_0"/>
  <junction id="b" x="20" y="0" incLanes="main#3_0"/>
  <connection from="main#2" to="main#3" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="s" state="O"/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="1" state="G"/></tlLogic>
</net>
""",
        encoding="utf-8",
    )
    candidate_text = """<net>
  <edge id="main#2" from="x" to="y"><lane id="main#2_0" index="0" shape="-20,0 -10,0"/></edge>
  <edge id="main#3" from="a" to="j"><lane id="main#3_0" index="0" shape="0,0 10,0"/></edge>
  <junction id="a" x="0" y="0"/>
  <junction id="j" type="traffic_light" x="10" y="0" incLanes="main#3_0" intLanes=""/>
  <junction id="x" x="-20" y="0"/>
  <junction id="y" x="-10" y="0" incLanes="main#2_0"/>
</net>
"""
    candidate_net = Path("candidate.net.xml")
    candidate_net.write_text(candidate_text, encoding="utf-8")
    raw_nodes = Path("raw.nod.xml")
    raw_nodes.write_text('<nodes><node id="a" x="0" y="0"/><node id="j" x="10" y="0"/><node id="b" x="20" y="0"/></nodes>', encoding="utf-8")
    raw_edges = Path("raw.edg.xml")
    raw_edges.write_text(
        """<edges>
  <edge id="main#2" from="x" to="y"><lane index="0"/></edge>
  <edge id="main#3" from="a" to="j"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    raw_connections = Path("raw.con.xml")
    raw_connections.write_text("<connections/>\n", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert" and "--node-files" in command:
            output_file = Path(command[command.index("--output-file") + 1])
            if not output_file.is_absolute():
                output_file = Path(cwd) / output_file
            output_file.write_text(candidate_text, encoding="utf-8")

        class Result:
            status = "pass"
            returncode = 0

            def to_dict(self):
                return {"command": command, "cwd": str(cwd) if cwd else None, "status": "pass", "returncode": 0}

        return Result()

    report = build_teacher_guided_junction_variant(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        junction_id="j",
        output_dir=Path("out"),
        edge_map={"main#2": "main#3", "main#3": "main#3"},
        prefix="demo",
        replay_target_internal_subgraph=True,
        command_runner=fake_runner,
    )

    assert report["target_internal_replay"]["effective_edge_map"]["main#2"] == "main#2"
    assert report["status"] == "pass"
    assert report["parity_gate_status"] == "pass"


def test_build_teacher_guided_junction_variant_falls_back_when_target_internal_replay_fails_load(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    teacher_net = Path("teacher.net.xml")
    teacher_net.write_text(
        """<net>
  <edge id="teacher_in" from="a" to="j" type="highway.primary"><lane id="teacher_in_0" index="0"/></edge>
  <edge id="teacher_out" from="j" to="b" type="highway.primary"><lane id="teacher_out_0" index="0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="teacher_in_0" intLanes=""/>
  <connection from="teacher_in" to="teacher_out" fromLane="0" toLane="0" dir="s" state="M"/>
</net>
""",
        encoding="utf-8",
    )
    candidate_net = Path("candidate.net.xml")
    candidate_net.write_text(
        """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>
""",
        encoding="utf-8",
    )
    raw_nodes = Path("raw.nod.xml")
    raw_nodes.write_text('<nodes><node id="a" x="-10" y="0"/><node id="j" x="0" y="0"/><node id="b" x="10" y="0"/></nodes>', encoding="utf-8")
    raw_edges = Path("raw.edg.xml")
    raw_edges.write_text(
        """<edges>
  <edge id="cand_in" from="a" to="j"><lane index="0"/></edge>
  <edge id="cand_out" from="j" to="b"><lane index="0"/></edge>
</edges>
""",
        encoding="utf-8",
    )
    raw_connections = Path("raw.con.xml")
    raw_connections.write_text("<connections/>\n", encoding="utf-8")

    def fake_runner(command, *, cwd=None, timeout_seconds=60.0):
        if command[0] == "netconvert" and "--node-files" in command:
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            connection_file = Path(cwd) / command[command.index("--connection-files") + 1]
            output_file.write_text(
                """<net>
  <edge id="cand_in" from="a" to="j" type="highway.primary"><lane id="cand_in_0" index="0"/></edge>
  <edge id="cand_out" from="j" to="b" type="highway.primary"><lane id="cand_out_0" index="0"/></edge>
  <junction id="j" type="priority" x="0" y="0" incLanes="cand_in_0" intLanes=""/>
</net>
""",
                encoding="utf-8",
            )
            root = ET.parse(output_file).getroot()
            for connection in ET.parse(connection_file).getroot().findall("connection"):
                root.append(connection)
            ET.ElementTree(root).write(output_file, encoding="utf-8", xml_declaration=True)
        elif command[0] == "netconvert" and "--sumo-net-file" in command:
            input_file = Path(cwd) / command[command.index("--sumo-net-file") + 1]
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text(input_file.read_text(encoding="utf-8"), encoding="utf-8")

        class Result:
            status = "pass"
            returncode = 0

            def to_dict(self):
                net_file = command[command.index("-n") + 1] if command[0] == "sumo" else ""
                status = "fail" if net_file.endswith(("teacher_guided.net.xml", "tg_norm.net.xml")) else "pass"
                return {
                    "command": command,
                    "cwd": str(cwd) if cwd else None,
                    "status": status,
                    "returncode": 1 if status == "fail" else 0,
                    "stderr": "final replay load failed" if status == "fail" else "",
                }

        return Result()

    report = build_teacher_guided_junction_variant(
        raw_node_file=raw_nodes,
        raw_edge_file=raw_edges,
        raw_connection_file=raw_connections,
        teacher_net_file=teacher_net,
        candidate_net_file=candidate_net,
        junction_id="j",
        output_dir=Path("out"),
        edge_map={"teacher_in": "cand_in", "teacher_out": "cand_out"},
        prefix="demo",
        replay_target_internal_subgraph=True,
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["target_internal_replay_fallback"] is True
    assert report["target_internal_replay_fallback_sumo"]["status"] == "pass"
    assert report["final_net_file"].endswith("demo_teacher_guided_fallback.net.xml")
    assert report["tl_logic"]["net_file"] == report["final_net_file"]

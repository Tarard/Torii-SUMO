from pathlib import Path

from torii_sumo.core.junction_connection_audit import build_connection_signature, write_connection_signature


def test_connection_signature_separates_top_level_and_internal(tmp_path: Path) -> None:
    net_file = tmp_path / "connection.net.xml"
    net_file.write_text(
        """<net>
  <edge id="in" from="a" to="j" type="highway.primary">
    <lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/>
  </edge>
  <edge id="out" from="j" to="b" type="highway.primary">
    <lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/>
  </edge>
  <edge id=":j_0" function="internal">
    <lane id=":j_0_0" index="0" allow="passenger" shape="0,0 4,0"/>
  </edge>
  <junction id="a" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="b" x="10" y="0" type="priority"/>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":j_0_0" dir="s" state="o"/>
  <connection from=":j_0" to="out" fromLane="0" toLane="0" dir="s" state="o"/>
</net>
""",
        encoding="utf-8",
    )

    signature = build_connection_signature(net_file, "j")

    assert signature["top_external_connection_count"] == 1
    assert signature["top_external_pair_count"] == 1
    assert signature["category_counts"]["internal_or_other_to_outgoing"] == 1
    assert signature["top_external_dir_counts"] == {"s": 1}


def test_connection_signature_records_tls_link_indices(tmp_path: Path) -> None:
    net_file = tmp_path / "tls.net.xml"
    net_file.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <connection from="in" to="out" fromLane="0" toLane="0" tl="j" linkIndex="7" linkIndex2="12" dir="s" state="O" pass="true" uncontrolled="true" allow="bicycle" disallow="truck" keepClear="0" contPos="43.00" shape="0,0 1,1"/>
</net>
""",
        encoding="utf-8",
    )

    signature = build_connection_signature(net_file, "j")

    assert signature["controlled_link_count"] == 1
    record = signature["connection_records"][0]
    assert record["tl"] == "j"
    assert record["linkIndex"] == "7"
    assert record["linkIndex2"] == "12"
    assert record["pass"] == "true"
    assert record["uncontrolled"] == "true"
    assert record["allow"] == "bicycle"
    assert record["disallow"] == "truck"
    assert record["keepClear"] == "0"
    assert record["contPos"] == "43.00"
    assert record["shape"] == "0,0 1,1"


def test_connection_signature_counts_crossings_and_walkingareas(tmp_path: Path) -> None:
    net_file = tmp_path / "modal.net.xml"
    net_file.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id=":j_c0" function="crossing"><lane id=":j_c0_0" index="0" allow="pedestrian" shape="0,-2 0,2"/></edge>
  <edge id=":j_w0" function="walkingarea"><lane id=":j_w0_0" index="0" allow="pedestrian" shape="0,2 2,2"/></edge>
  <junction id="j" x="0" y="0" type="traffic_light" incLanes="in_0 :j_w0_0" intLanes=":j_c0_0"/>
  <connection from="in" to="out" fromLane="0" toLane="0"/>
</net>
""",
        encoding="utf-8",
    )

    signature = build_connection_signature(net_file, "j")

    assert signature["crossing_count"] == 1
    assert signature["walkingarea_count"] == 1


def test_write_connection_signature_outputs_review_files(tmp_path: Path) -> None:
    net_file = tmp_path / "connection.net.xml"
    net_file.write_text(
        """<net>
  <edge id="in" from="a" to="j" type="highway.primary"><lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b" type="highway.primary"><lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="a" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="b" x="10" y="0" type="priority"/>
  <connection from="in" to="out" fromLane="0" toLane="0" dir="s" state="o" keepClear="0" shape="0,0 1,1"/>
</net>
""",
        encoding="utf-8",
    )
    signature = build_connection_signature(net_file, "j")

    report = write_connection_signature(signature, tmp_path / "review", "demo")

    assert Path(report["signature_file"]).is_file()
    records_header = Path(report["records_file"]).read_text(encoding="utf-8").splitlines()[0]
    top_external_header = Path(report["top_external_file"]).read_text(encoding="utf-8").splitlines()[0]
    for field in ("linkIndex2", "pass", "uncontrolled", "allow", "disallow", "keepClear", "contPos", "shape"):
        assert field in records_header
        assert field in top_external_header

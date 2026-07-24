from pathlib import Path

from torii_sumo.core.complete_way_audit import audit_complete_osm_way_filter


def test_complete_way_audit_accepts_boundary_extension(tmp_path: Path) -> None:
    source = tmp_path / "source.osm.xml"
    filtered = tmp_path / "filtered.osm.xml"
    payload = """<osm version="0.6">
  <node id="1" lat="53.54" lon="9.99"/>
  <node id="2" lat="53.54" lon="10.10"/>
  <way id="10">
    <nd ref="1"/><nd ref="2"/><tag k="highway" v="primary"/>
  </way>
</osm>"""
    source.write_text(payload, encoding="utf-8")
    filtered.write_text(payload, encoding="utf-8")

    report = audit_complete_osm_way_filter(
        source_osm_file=source,
        filtered_osm_file=filtered,
        acquisition_bbox=(9.98, 53.53, 10.01, 53.55),
        allowed_highways=("primary",),
    )

    assert report["status"] == "pass"
    assert report["source_selected_way_count"] == 1
    assert report["missing_way_count"] == 0
    assert report["modified_way_count"] == 0
    assert report["ways_with_nodes_outside_bbox_ids"] == ["10"]


def test_complete_way_audit_blocks_trimmed_way(tmp_path: Path) -> None:
    source = tmp_path / "source.osm.xml"
    filtered = tmp_path / "filtered.osm.xml"
    source.write_text(
        """<osm version="0.6">
  <node id="1" lat="53.54" lon="9.99"/>
  <node id="2" lat="53.54" lon="10.00"/>
  <node id="3" lat="53.54" lon="10.10"/>
  <way id="10">
    <nd ref="1"/><nd ref="2"/><nd ref="3"/><tag k="highway" v="primary"/>
  </way>
</osm>""",
        encoding="utf-8",
    )
    filtered.write_text(
        """<osm version="0.6">
  <node id="1" lat="53.54" lon="9.99"/>
  <node id="2" lat="53.54" lon="10.00"/>
  <way id="10">
    <nd ref="1"/><nd ref="2"/><tag k="highway" v="primary"/>
  </way>
</osm>""",
        encoding="utf-8",
    )

    report = audit_complete_osm_way_filter(
        source_osm_file=source,
        filtered_osm_file=filtered,
        acquisition_bbox=(9.98, 53.53, 10.01, 53.55),
        allowed_highways=("primary",),
    )

    assert report["status"] == "blocked"
    assert report["modified_way_ids"] == ["10"]

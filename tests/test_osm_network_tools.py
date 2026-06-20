import gzip
from pathlib import Path
import xml.etree.ElementTree as ET

from torii_sumo.core.command_runner import CommandResult
from torii_sumo.core.osm_network import (
    build_osm_network,
    build_overpass_query,
    build_routeability_probe,
    cluster_tls_candidates,
    filter_osm_by_highways,
    google_maps_baseline_fields,
    merge_osm_xml_payloads,
    parse_bbox,
    robust_download_osm,
    split_bbox,
)
from torii_sumo.tools.osm_tools import resolve_highway_classes, sumo_osm_build_network


def test_build_overpass_query_uses_overpass_coordinate_order_and_date() -> None:
    bbox = parse_bbox("13.6000,50.9800,13.9000,51.1500")

    query = build_overpass_query(
        bbox,
        timeout=180,
        historical_date="2024-09-10T00:00:00Z",
    )

    assert '[out:xml][timeout:180][date:"2024-09-10T00:00:00Z"];' in query
    assert 'way["highway"](50.98,13.6,51.15,13.9);' in query
    assert 'relation["type"="restriction"](50.98,13.6,51.15,13.9);' in query


def test_resolve_highway_classes_supports_osmnet_inspired_presets() -> None:
    assert {"primary", "tertiary", "tertiary_link"} <= resolve_highway_classes("arterial")
    assert {"motorway", "primary", "residential", "living_street"} <= resolve_highway_classes("drive")
    assert "unclassified" in resolve_highway_classes("drive_plus_unclassified")
    assert "service" in resolve_highway_classes("full_vehicle")
    assert resolve_highway_classes("primary,residential") == {"primary", "residential"}


def test_split_bbox_subdivides_large_bbox_without_losing_extent() -> None:
    bbox = parse_bbox("13.0,50.0,14.0,51.0")

    tiles = split_bbox(bbox, max_tile_area_km2=1000.0)

    assert len(tiles) > 1
    assert min(tile.west for tile in tiles) == bbox.west
    assert min(tile.south for tile in tiles) == bbox.south
    assert max(tile.east for tile in tiles) == bbox.east
    assert max(tile.north for tile in tiles) == bbox.north


def test_merge_osm_xml_payloads_deduplicates_nodes_ways_and_relations() -> None:
    left = b"""<osm version="0.6">
  <node id="1" lat="51.0" lon="13.7"/>
  <way id="10"><nd ref="1"/><tag k="highway" v="primary"/></way>
</osm>"""
    right = b"""<osm version="0.6">
  <node id="1" lat="51.0" lon="13.7"/>
  <node id="2" lat="51.0" lon="13.8"/>
  <way id="10"><nd ref="1"/><tag k="highway" v="primary"/></way>
  <relation id="20"><member type="way" ref="10" role="from"/><tag k="type" v="restriction"/></relation>
</osm>"""

    merged = merge_osm_xml_payloads([left, right])
    root = ET.fromstring(merged)

    assert [node.attrib["id"] for node in root.findall("node")] == ["1", "2"]
    assert [way.attrib["id"] for way in root.findall("way")] == ["10"]
    assert [relation.attrib["id"] for relation in root.findall("relation")] == ["20"]


def test_robust_download_osm_retries_and_merges_tile_payloads() -> None:
    bbox = parse_bbox("13.0,50.0,14.0,51.0")
    calls = 0

    def flaky_download(query: str, *, url: str, user_agent: str, timeout_seconds: float) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary overpass timeout")
        return f"""<osm version="0.6">
  <node id="{calls}" lat="51.0" lon="13.7"/>
  <way id="{calls + 100}"><nd ref="{calls}"/><tag k="highway" v="primary"/></way>
</osm>""".encode("utf-8")

    payload, report = robust_download_osm(
        bbox,
        timeout_seconds=120,
        historical_date=None,
        overpass_url="https://example.test/interpreter",
        user_agent="test-agent",
        max_tile_area_km2=1000.0,
        max_retries=2,
        retry_pause_seconds=0.0,
        download_func=flaky_download,
    )
    root = ET.fromstring(payload)

    assert report["tile_count"] > 1
    assert report["retry_count"] == 1
    assert len(root.findall("way")) == report["tile_count"]
    assert calls == report["tile_count"] + 1


def test_filter_osm_by_highways_keeps_nodes_and_restrictions_for_kept_ways(tmp_path: Path) -> None:
    source = tmp_path / "source.osm.xml.gz"
    target = tmp_path / "target.osm.xml.gz"
    payload = b"""<osm version="0.6">
  <node id="1" lat="51.0" lon="13.70"/>
  <node id="2" lat="51.0" lon="13.71"/>
  <node id="3" lat="51.0" lon="13.72"/>
  <way id="10">
    <nd ref="1"/><nd ref="2"/>
    <tag k="highway" v="primary"/>
  </way>
  <way id="11">
    <nd ref="2"/><nd ref="3"/>
    <tag k="highway" v="residential"/>
  </way>
  <relation id="20">
    <member type="way" ref="10" role="from"/>
    <tag k="type" v="restriction"/>
  </relation>
</osm>"""
    source.write_bytes(gzip.compress(payload))

    stats = filter_osm_by_highways(source, target, {"primary"})

    root = ET.fromstring(gzip.decompress(target.read_bytes()))
    assert [node.attrib["id"] for node in root.findall("node")] == ["1", "2"]
    assert [way.attrib["id"] for way in root.findall("way")] == ["10"]
    assert [relation.attrib["id"] for relation in root.findall("relation")] == ["20"]
    assert stats == {
        "kept_nodes": 2,
        "kept_ways": 1,
        "dropped_ways": 1,
        "kept_relations": 1,
    }


def test_build_osm_network_from_existing_osm_runs_netconvert_and_records_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "input.osm.xml"
    source.write_text(
        """<osm version="0.6">
  <node id="1" lat="51.0" lon="13.70"/>
  <node id="2" lat="51.0" lon="13.71"/>
  <way id="10">
    <nd ref="1"/><nd ref="2"/>
    <tag k="highway" v="primary"/>
  </way>
</osm>""",
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_runner(command: list[str], *, cwd: Path | None = None, timeout_seconds: float = 60.0):
        calls.append(command)
        output = Path(command[command.index("--output-file") + 1])
        if not output.is_absolute():
            assert cwd is not None
            output = cwd / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("<net/>", encoding="utf-8")
        return CommandResult(command=command, cwd=str(cwd), status="pass", returncode=0)

    report = build_osm_network(
        bbox="13.6000,50.9800,13.9000,51.1500",
        output_dir=tmp_path / "build",
        prefix="demo",
        source_osm_path=source,
        allowed_highways={"primary"},
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert Path(report["filtered_osm_file"]).is_file()
    assert Path(report["net_file"]).is_file()
    assert Path(report["command_record"]).is_file()
    assert calls == [
        [
            "netconvert",
            "--osm-files",
            "osm/demo_filtered.osm.xml.gz",
            "--output-file",
            "sumo/demo.net.xml",
            "--proj.utm",
            "--no-turnarounds",
            "--osm.all-attributes",
            "--tls.join",
            "--tls.join-dist",
            "35",
            "--verbose",
        ]
    ]


def test_build_osm_network_uses_robust_downloader_when_no_source_osm(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_download(query: str, *, url: str, user_agent: str, timeout_seconds: float) -> bytes:
        calls.append(query)
        node_id = len(calls)
        return f"""<osm version="0.6">
  <node id="{node_id}" lat="51.0" lon="13.70"/>
  <node id="{node_id + 100}" lat="51.0" lon="13.71"/>
  <way id="{node_id + 200}">
    <nd ref="{node_id}"/><nd ref="{node_id + 100}"/>
    <tag k="highway" v="primary"/>
  </way>
</osm>""".encode("utf-8")

    def fake_runner(command: list[str], *, cwd: Path | None = None, timeout_seconds: float = 60.0):
        output = Path(command[command.index("--output-file") + 1])
        assert cwd is not None
        (cwd / output).parent.mkdir(parents=True, exist_ok=True)
        (cwd / output).write_text("<net/>", encoding="utf-8")
        return CommandResult(command=command, cwd=str(cwd), status="pass", returncode=0)

    report = build_osm_network(
        bbox="13.0,50.0,14.0,51.0",
        output_dir=tmp_path / "build",
        prefix="robust",
        allowed_highways={"primary"},
        max_tile_area_km2=1000.0,
        command_runner=fake_runner,
        download_func=fake_download,
    )

    assert report["status"] == "pass"
    assert report["overpass"]["tile_count"] == len(calls)
    assert report["overpass"]["tile_count"] > 1
    assert Path(report["source_osm_file"]).is_file()


def test_sumo_osm_build_network_reports_invalid_bbox_as_construction_invalid(tmp_path: Path) -> None:
    report = sumo_osm_build_network(
        bbox="13.9,51.0,13.6,51.1",
        output_dir=str(tmp_path),
        source_osm_path=str(tmp_path / "missing.osm.xml"),
    )

    assert report["status"] == "fail"
    assert report["claim_status"] == "construction-invalid"
    assert "bbox west must be smaller than east" in report["error"]


def test_cluster_tls_candidates_uses_transitive_distance_components() -> None:
    rows = [
        {"tls_id": "a", "lat": "51.0000000", "lon": "13.7000000", "incoming_road_names": "Main"},
        {"tls_id": "b", "lat": "51.0001000", "lon": "13.7000000", "incoming_road_names": "Main"},
        {"tls_id": "c", "lat": "51.0002000", "lon": "13.7000000", "incoming_road_names": "Main"},
        {"tls_id": "d", "lat": "51.0100000", "lon": "13.7100000", "incoming_road_names": "Far"},
    ]

    clusters = cluster_tls_candidates(rows, radius_m=15.0)

    assert sorted(cluster["tls_ids"] for cluster in clusters) == ["a;b;c", "d"]


def test_google_maps_baseline_fields_record_temporal_scope() -> None:
    current = google_maps_baseline_fields("current", None)
    historical = google_maps_baseline_fields("historical", "2020-05")
    unspecified = google_maps_baseline_fields("unspecified", None)

    assert current["google_maps_baseline_source"] == "Google Maps"
    assert current["google_maps_temporal_scope"] == "current"
    assert current["google_maps_requires_time_confirmation"] == "no"
    assert historical["google_maps_temporal_scope"] == "historical"
    assert historical["google_maps_target_date"] == "2020-05"
    assert historical["google_maps_requires_time_confirmation"] == "no"
    assert unspecified["google_maps_requires_time_confirmation"] == "yes"


def test_cluster_tls_candidates_carries_google_maps_temporal_baseline() -> None:
    rows = [
        {"tls_id": "a", "lat": "51.0000000", "lon": "13.7000000", "incoming_road_names": "Main"},
        {"tls_id": "b", "lat": "51.0001000", "lon": "13.7000000", "incoming_road_names": "Main"},
    ]

    clusters = cluster_tls_candidates(
        rows,
        radius_m=15.0,
        google_maps_temporal_scope="historical",
        google_maps_target_date="2020-05",
    )

    assert clusters[0]["google_maps_baseline_source"] == "Google Maps"
    assert clusters[0]["google_maps_temporal_scope"] == "historical"
    assert clusters[0]["google_maps_target_date"] == "2020-05"
    assert clusters[0]["google_maps_requires_time_confirmation"] == "no"


def test_build_routeability_probe_uses_user_supplied_road_queries(tmp_path: Path) -> None:
    net_file = tmp_path / "network.net.xml"
    net_file.write_text(
        """<net>
  <edge id="pre" from="n0" to="n1">
    <lane id="pre_0" allow="passenger" speed="13.9" length="10.0"/>
    <param key="name" value="Approach Road"/>
  </edge>
  <edge id="main" from="n1" to="n2">
    <lane id="main_0" allow="passenger" speed="13.9" length="10.0"/>
    <param key="name" value="Main Road"/>
  </edge>
  <edge id="post" from="n2" to="n3">
    <lane id="post_0" allow="passenger" speed="13.9" length="10.0"/>
    <param key="name" value="Exit Road"/>
  </edge>
  <connection from="pre" to="main"/>
  <connection from="main" to="post"/>
</net>""",
        encoding="utf-8",
    )

    report = build_routeability_probe(
        net_file=net_file,
        output_dir=tmp_path / "probe",
        prefix="demo_probe",
        key_edge_queries=[
            {"label": "main_road", "role": "arterial", "search_terms": ["Main Road"]}
        ],
    )

    route_root = ET.parse(report["route_file"]).getroot()
    cfg_root = ET.parse(report["sumocfg_file"]).getroot()
    key_rows = Path(report["key_edges_file"]).read_text(encoding="utf-8")

    assert report["status"] == "pass"
    assert route_root.find("route").attrib["edges"] == "pre main post"
    assert cfg_root.find("input/net-file").attrib["value"] == "../network.net.xml"
    assert "main_road,arterial,n1,n2,main" in key_rows

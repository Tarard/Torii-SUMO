import csv
import gzip
from pathlib import Path
import xml.etree.ElementTree as ET

from torii_sumo.core.connectivity import (
    extract_largest_passenger_component_core,
    summarize_passenger_connectivity,
)
from torii_sumo.core.command_runner import CommandResult
from torii_sumo.core.osm_network import (
    build_osm_network,
    build_overpass_query,
    build_routeability_probe,
    build_tls_multisource_review,
    cluster_tls_candidates,
    filter_osm_by_highways,
    google_maps_baseline_fields,
    merge_osm_xml_payloads,
    parse_bbox,
    robust_download_osm,
    split_bbox,
)
from torii_sumo.core.osm_area import resolve_osm_place
from torii_sumo.core.osm_workflow import run_osm_cleanup_workflow
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


def test_resolve_osm_place_parses_first_nominatim_candidate() -> None:
    def fake_fetch_json(*, url: str, headers: dict[str, str], timeout_seconds: float):
        assert "nominatim.openstreetmap.org/search" in url
        assert "Altstadt%2C+Dresden" in url
        assert headers["User-Agent"].startswith("Torii-SUMO")
        assert timeout_seconds == 30.0
        return [
            {
                "display_name": "Altstadt, Dresden, Sachsen, Deutschland",
                "osm_type": "relation",
                "osm_id": 192900,
                "lat": "51.0523842",
                "lon": "13.7381876",
                "boundingbox": ["51.0280799", "51.0766681", "13.6864402", "13.7872926"],
            }
        ]

    report = resolve_osm_place(
        "Altstadt, Dresden",
        fetch_json=fake_fetch_json,
        timeout_seconds=30.0,
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["area_resolution_status"] == "candidate_found"
    assert report["candidate_display_name"] == "Altstadt, Dresden, Sachsen, Deutschland"
    assert report["candidate_osm_type"] == "relation"
    assert report["candidate_osm_id"] == "192900"
    assert report["candidate_bbox"] == "13.6864402,51.0280799,13.7872926,51.0766681"
    assert report["candidate_lat"] == "51.0523842"
    assert report["candidate_lon"] == "13.7381876"
    assert "openstreetmap.org/search" in report["osm_preview_url"]
    assert report["candidate_osm_url"] == "https://www.openstreetmap.org/relation/192900"


def test_sumo_osm_resolve_place_tool_returns_candidate(monkeypatch) -> None:
    from torii_sumo.tools import osm_tools

    monkeypatch.setattr(
        osm_tools,
        "resolve_osm_place",
        lambda place_name, **_kwargs: {
            "status": "pass",
            "candidate_bbox": "13.6864402,51.0280799,13.7872926,51.0766681",
            "area_input": place_name,
        },
    )

    report = osm_tools.sumo_osm_resolve_place("Altstadt, Dresden")

    assert report["status"] == "pass"
    assert report["area_input"] == "Altstadt, Dresden"
    assert report["candidate_bbox"] == "13.6864402,51.0280799,13.7872926,51.0766681"


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


def test_build_tls_multisource_review_keeps_human_review_boundary() -> None:
    rows = build_tls_multisource_review(
        [
            {
                "tls_id": "J1",
                "lat": "51.0505920",
                "lon": "13.7339600",
                "connection_count": 12,
                "nearest_osm_signal_id": "osm-100",
                "nearest_osm_signal_distance_m": "8.5",
                "has_osm_signal_within_35m": "yes",
                "incoming_road_names": "Main Street",
                "outgoing_road_names": "Bridge Street",
                "google_maps_url": "https://www.google.com/maps/search/?api=1&query=51.050592,13.733960",
            },
            {
                "tls_id": "J2",
                "lat": "51.0600000",
                "lon": "13.7400000",
                "connection_count": 4,
                "nearest_osm_signal_id": "",
                "nearest_osm_signal_distance_m": "",
                "has_osm_signal_within_35m": "no",
                "incoming_road_names": "Side Road",
                "outgoing_road_names": "",
                "google_maps_url": "https://www.google.com/maps/search/?api=1&query=51.060000,13.740000",
            },
        ],
        official_inventory={
            "J1": {"status": "confirmed", "source_id": "agency-42", "note": "official inventory row"}
        },
        signal_plans={
            "J1": {"status": "available", "source_id": "plan-7", "note": "timing plan exists"}
        },
        field_evidence={
            "J1": {"status": "photo_confirmed", "source_id": "photo-3", "note": "field photo manifest"}
        },
    )

    confirmed = rows[0]
    assert confirmed["tls_id"] == "J1"
    assert confirmed["official_inventory_status"] == "confirmed"
    assert confirmed["official_inventory_id"] == "agency-42"
    assert confirmed["signal_plan_status"] == "available"
    assert confirmed["field_evidence_status"] == "photo_confirmed"
    assert confirmed["mapillary_url"].startswith("https://www.mapillary.com/app/")
    assert confirmed["kartaview_url"].startswith("https://kartaview.org/map/@51.050592,13.733960")
    assert confirmed["evidence_level"] == "authoritative"
    assert confirmed["review_status"] == "needs_manual_review"
    assert confirmed["claim_status"] == "diagnostic-demo"

    guessed = rows[1]
    assert guessed["tls_id"] == "J2"
    assert guessed["evidence_level"] == "sumo-guess-only"
    assert guessed["review_status"] == "needs_manual_review"
    assert guessed["claim_status"] == "diagnostic-demo"


def test_net_xy_to_latlon_falls_back_when_sumolib_reports_missing_pyproj() -> None:
    from torii_sumo.core.osm_network import _net_xy_to_latlon

    class FakeNet:
        _location = {"projParameter": "+proj=utm +zone=33 +ellps=WGS84 +datum=WGS84 +units=m +no_defs"}

        def convertXY2LonLat(self, _x: float, _y: float) -> tuple[float, float]:
            raise RuntimeError("Network does not provide geo-projection or pyproj not installed.")

        def getLocationOffset(self) -> tuple[float, float]:
            return (0.0, 0.0)

    lat, lon = _net_xy_to_latlon(FakeNet(), 391000.0, 5655000.0)

    assert 50.0 < lat < 52.0
    assert 12.0 < lon < 15.0


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


def test_summarize_passenger_connectivity_passes_single_component(tmp_path: Path) -> None:
    net_file = tmp_path / "connected.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a" from="n0" to="n1">
    <lane id="a_0" allow="passenger" speed="13.9" length="10.0"/>
  </edge>
  <edge id="b" from="n1" to="n2">
    <lane id="b_0" allow="passenger" speed="13.9" length="10.0"/>
  </edge>
  <connection from="a" to="b"/>
</net>""",
        encoding="utf-8",
    )

    report = summarize_passenger_connectivity(net_file)

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["connectivity_status"] == "pass"
    assert report["passenger_edge_count"] == 2
    assert report["passenger_component_count"] == 1
    assert report["largest_component_edge_count"] == 2
    assert report["small_component_count"] == 0
    assert report["isolated_passenger_edge_count"] == 0


def test_summarize_passenger_connectivity_fails_disconnected_components(tmp_path: Path) -> None:
    net_file = tmp_path / "disconnected.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a" from="n0" to="n1">
    <lane id="a_0" allow="passenger" speed="13.9" length="10.0"/>
  </edge>
  <edge id="b" from="n2" to="n3">
    <lane id="b_0" allow="passenger" speed="13.9" length="10.0"/>
  </edge>
</net>""",
        encoding="utf-8",
    )

    report = summarize_passenger_connectivity(net_file)

    assert report["status"] == "fail"
    assert report["claim_status"] == "construction-invalid"
    assert report["connectivity_status"] == "fail"
    assert report["passenger_edge_count"] == 2
    assert report["passenger_component_count"] == 2
    assert report["largest_component_edge_count"] == 1
    assert report["small_component_count"] == 2
    assert report["isolated_passenger_edge_count"] == 2
    assert "passenger network has 2 disconnected components" in report["warnings"]


def test_extract_largest_passenger_component_core_writes_keep_and_discard_records(tmp_path: Path) -> None:
    net_file = tmp_path / "raw.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a" from="n0" to="n1">
    <lane id="a_0" allow="passenger" speed="13.9" length="10.0"/>
  </edge>
  <edge id="b" from="n1" to="n2">
    <lane id="b_0" allow="passenger" speed="13.9" length="10.0"/>
  </edge>
  <edge id="c" from="n3" to="n4">
    <lane id="c_0" allow="passenger" speed="13.9" length="10.0"/>
  </edge>
  <connection from="a" to="b"/>
</net>""",
        encoding="utf-8",
    )

    calls = []

    def fake_command_runner(command, **kwargs):
        calls.append((command, kwargs))
        output_file = Path(command[command.index("--output-file") + 1])
        output_file.write_text("<net/>", encoding="utf-8")
        return {"status": "pass", "returncode": 0, "stdout": "Success.", "stderr": "", "error": ""}

    report = extract_largest_passenger_component_core(
        net_file,
        output_dir=tmp_path / "core",
        prefix="demo",
        command_runner=fake_command_runner,
    )

    keep_edges = Path(report["keep_edges_file"]).read_text(encoding="utf-8").splitlines()
    discard_rows = list(csv.DictReader(Path(report["discarded_components_file"]).open(encoding="utf-8")))

    assert report["status"] == "pass"
    assert report["network_quality"] == "connected-core"
    assert report["raw_passenger_component_count"] == 2
    assert report["core_passenger_edge_count"] == 2
    assert report["discarded_passenger_edge_count"] == 1
    assert keep_edges == ["a", "b"]
    assert discard_rows == [
        {
            "component_rank": "2",
            "component_size": "1",
            "edge_id": "c",
            "discard_reason": "outside_largest_passenger_component",
        }
    ]
    command = calls[0][0]
    assert command[:2] == ["netconvert", "--sumo-net-file"]
    assert "--keep-edges.input-file" in command
    assert "--keep-edges.postload" in command


def test_launch_netedit_reports_unavailable_when_binary_missing(tmp_path: Path) -> None:
    from torii_sumo.core.netedit import launch_netedit

    net_file = tmp_path / "network.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    report = launch_netedit(
        net_file,
        which_func=lambda _name: None,
    )

    assert report["status"] == "blocked"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["netedit_status"] == "unavailable"
    assert report["netedit_network_file"] == str(net_file)
    assert "netedit binary not found" in report["warnings"]


def test_launch_netedit_starts_non_blocking_process(tmp_path: Path) -> None:
    from torii_sumo.core.netedit import launch_netedit

    class FakeProcess:
        pid = 12345

    calls: list[list[str]] = []

    def fake_popen(command, **kwargs):
        calls.append(command)
        assert kwargs["stdin"] is not None
        assert kwargs["stdout"] is not None
        assert kwargs["stderr"] is not None
        return FakeProcess()

    net_file = tmp_path / "network.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    report = launch_netedit(
        net_file,
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=fake_popen,
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["netedit_status"] == "opened"
    assert report["netedit_binary"] == "C:/SUMO/bin/netedit.exe"
    assert report["netedit_process_id"] == 12345
    assert calls == [["C:/SUMO/bin/netedit.exe", "-s", str(net_file)]]


def test_launch_sumo_gui_writes_minimal_config_and_starts_non_blocking_process(tmp_path: Path) -> None:
    from torii_sumo.core.sumo_gui import launch_sumo_gui

    class FakeProcess:
        pid = 24680

    calls: list[list[str]] = []

    def fake_popen(command, **kwargs):
        calls.append(command)
        assert kwargs["stdin"] is not None
        assert kwargs["stdout"] is not None
        assert kwargs["stderr"] is not None
        return FakeProcess()

    net_file = tmp_path / "network.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    report = launch_sumo_gui(
        net_file,
        output_dir=tmp_path / "gui",
        prefix="demo",
        which_func=lambda _name: "C:/SUMO/bin/sumo-gui.exe",
        popen_func=fake_popen,
    )

    cfg_file = Path(report["sumo_gui_config_file"])
    cfg_root = ET.parse(cfg_file).getroot()

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["sumo_gui_status"] == "opened"
    assert report["sumo_gui_binary"] == "C:/SUMO/bin/sumo-gui.exe"
    assert report["sumo_gui_process_id"] == 24680
    assert report["sumo_gui_network_file"] == str(net_file)
    assert cfg_root.find("input/net-file").attrib["value"] == str(net_file)
    assert cfg_root.find("time/end").attrib["value"] == "1"
    assert calls == [["C:/SUMO/bin/sumo-gui.exe", "-c", str(cfg_file)]]


def test_osm_cleanup_workflow_blocks_unconfirmed_place_name(tmp_path: Path) -> None:
    report = run_osm_cleanup_workflow(
        place_name="Altstadt, Dresden",
        output_dir=tmp_path,
    )

    assert report["status"] == "blocked"
    assert report["claim_status"] == "blocked"
    assert report["area_resolution_status"] == "needs_user_confirmation"
    assert report["area_input"] == "Altstadt, Dresden"
    assert report["user_confirmed_area"] == "no"
    assert "openstreetmap.org/search" in report["osm_preview_url"]
    assert report["gate_status"]["area_confirmation"] == "blocked"


def test_osm_cleanup_workflow_blocks_unconfirmed_place_with_resolved_bbox(tmp_path: Path) -> None:
    candidate = {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "area_resolution_status": "candidate_found",
        "candidate_display_name": "Altstadt, Dresden, Sachsen, Deutschland",
        "candidate_osm_type": "relation",
        "candidate_osm_id": "192900",
        "candidate_bbox": "13.6864402,51.0280799,13.7872926,51.0766681",
        "candidate_lat": "51.0523842",
        "candidate_lon": "13.7381876",
        "osm_preview_url": "https://www.openstreetmap.org/search?query=Altstadt%2C+Dresden",
        "candidate_osm_url": "https://www.openstreetmap.org/relation/192900",
        "warnings": [],
    }

    report = run_osm_cleanup_workflow(
        place_name="Altstadt, Dresden",
        output_dir=tmp_path,
        place_resolver=lambda _place_name: candidate,
    )

    assert report["status"] == "blocked"
    assert report["claim_status"] == "blocked"
    assert report["area_resolution_status"] == "needs_user_confirmation"
    assert report["candidate_display_name"] == "Altstadt, Dresden, Sachsen, Deutschland"
    assert report["candidate_osm_type"] == "relation"
    assert report["candidate_osm_id"] == "192900"
    assert report["candidate_bbox"] == "13.6864402,51.0280799,13.7872926,51.0766681"
    assert report["candidate_osm_url"] == "https://www.openstreetmap.org/relation/192900"
    assert report["gate_status"]["area_confirmation"] == "blocked"
    assert report["gate_status"]["network_build"] == "not_started"


def test_osm_cleanup_workflow_uses_resolved_bbox_after_area_confirmation(tmp_path: Path) -> None:
    candidate = {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "area_resolution_status": "candidate_found",
        "candidate_display_name": "Altstadt, Dresden, Sachsen, Deutschland",
        "candidate_osm_type": "relation",
        "candidate_osm_id": "192900",
        "candidate_bbox": "13.6864402,51.0280799,13.7872926,51.0766681",
        "candidate_lat": "51.0523842",
        "candidate_lon": "13.7381876",
        "osm_preview_url": "https://www.openstreetmap.org/search?query=Altstadt%2C+Dresden",
        "candidate_osm_url": "https://www.openstreetmap.org/relation/192900",
        "warnings": [],
    }
    net_file = tmp_path / "sumo" / "resolved.net.xml"
    filtered_osm = tmp_path / "osm" / "resolved_filtered.osm.xml.gz"
    captured: dict[str, object] = {}

    def fake_build(**kwargs):
        captured["bbox"] = kwargs["bbox"]
        net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": ["primary"],
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        place_name="Altstadt, Dresden",
        confirmed_area=True,
        output_dir=tmp_path,
        prefix="resolved",
        place_resolver=lambda _place_name: candidate,
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        },
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "claim_status": "diagnostic-demo",
            "netedit_status": "unavailable",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, _output_dir, _prefix: {
            "status": "blocked",
            "claim_status": "diagnostic-demo",
            "sumo_gui_status": "unavailable",
            "warnings": [],
        },
    )

    assert captured["bbox"] == "13.6864402,51.0280799,13.7872926,51.0766681"
    assert report["status"] == "pass"
    assert report["area_resolution_status"] == "confirmed_by_user"
    assert report["candidate_display_name"] == "Altstadt, Dresden, Sachsen, Deutschland"
    assert report["candidate_bbox"] == "13.6864402,51.0280799,13.7872926,51.0766681"
    assert report["user_confirmed_area"] == "yes"


def test_osm_cleanup_workflow_runs_build_tls_connectivity_and_netedit(tmp_path: Path) -> None:
    net_file = tmp_path / "sumo" / "demo.net.xml"
    filtered_osm = tmp_path / "osm" / "demo_filtered.osm.xml.gz"

    def fake_build(**kwargs):
        net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": ["primary"],
            "warnings": [],
        }

    def fake_tls(**kwargs):
        assert kwargs["net_file"] == net_file
        assert kwargs["osm_file"] == filtered_osm
        assert kwargs["google_maps_temporal_scope"] == "current"
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 2,
            "tls_cluster_count": 1,
            "candidates_file": str(tmp_path / "tls_candidates.csv"),
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "google_maps_baseline": {
                "google_maps_baseline_source": "Google Maps",
                "google_maps_temporal_scope": "current",
                "google_maps_target_date": "",
                "google_maps_requires_time_confirmation": "no",
            },
            "warnings": [],
        }

    def fake_connectivity(net_path):
        assert net_path == net_file
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 3,
            "passenger_component_count": 1,
            "largest_component_edge_count": 3,
            "small_component_count": 0,
            "isolated_passenger_edge_count": 0,
            "warnings": [],
        }

    def fake_netedit(net_path):
        assert net_path == net_file
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "netedit_status": "opened",
            "netedit_binary": "netedit",
            "netedit_process_id": 100,
            "netedit_window_title": "",
            "netedit_network_file": str(net_file),
            "warnings": [],
        }

    def fake_sumo_gui(net_path, output_dir, prefix):
        assert net_path == net_file
        assert output_dir == tmp_path / "sumo_gui"
        assert prefix == "demo_sumo_gui"
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "sumo_gui_status": "opened",
            "sumo_gui_binary": "sumo-gui",
            "sumo_gui_process_id": 101,
            "sumo_gui_config_file": str(tmp_path / "sumo_gui" / "demo_sumo_gui.sumocfg"),
            "sumo_gui_network_file": str(net_file),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="13.6,50.9,13.9,51.1",
        output_dir=tmp_path,
        prefix="demo",
        highway_classes={"primary"},
        build_func=fake_build,
        tls_audit_func=fake_tls,
        connectivity_func=fake_connectivity,
        netedit_func=fake_netedit,
        sumo_gui_func=fake_sumo_gui,
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["area_resolution_status"] == "confirmed_by_input"
    assert report["gate_status"] == {
        "area_confirmation": "pass",
        "network_build": "pass",
        "tls_reality_audit": "pass",
        "connectivity": "pass",
        "netedit": "pass",
        "sumo_gui": "pass",
    }
    assert report["tls_review_complete"] == "no"
    assert report["tls_needs_review_count"] == 1
    assert report["connectivity_status"] == "pass"
    assert report["netedit_status"] == "opened"
    assert report["sumo_gui_status"] == "opened"
    assert report["sumo_gui_process_id"] == 101


def test_osm_cleanup_workflow_uses_connected_core_for_downstream_checks(tmp_path: Path) -> None:
    raw_net = tmp_path / "sumo" / "raw.net.xml"
    core_net = tmp_path / "connected_core" / "demo_connected_core.net.xml"
    filtered_osm = tmp_path / "osm" / "demo_filtered.osm.xml.gz"
    downstream_paths: dict[str, Path] = {}

    def fake_build(**kwargs):
        raw_net.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        raw_net.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(raw_net),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": ["primary"],
            "warnings": [],
        }

    def fake_connectivity(net_path):
        if net_path == raw_net:
            return {
                "status": "fail",
                "claim_status": "construction-invalid",
                "connectivity_status": "fail",
                "passenger_edge_count": 1000,
                "passenger_component_count": 4,
                "largest_component_edge_count": 992,
                "small_component_count": 3,
                "isolated_passenger_edge_count": 2,
                "warnings": ["passenger network has 4 disconnected components"],
            }
        assert net_path == core_net
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 992,
            "passenger_component_count": 1,
            "largest_component_edge_count": 992,
            "small_component_count": 0,
            "isolated_passenger_edge_count": 0,
            "warnings": [],
        }

    def fake_connected_core(net_path, **kwargs):
        assert net_path == raw_net
        assert kwargs["prefix"] == "demo"
        core_net.parent.mkdir(parents=True, exist_ok=True)
        core_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "network_quality": "connected-core",
            "connected_core_file": str(core_net),
            "keep_edges_file": str(tmp_path / "connected_core" / "demo_connected_core.keep_edges.txt"),
            "discarded_components_file": str(tmp_path / "connected_core" / "demo_discarded_components.csv"),
            "raw_passenger_edge_count": 1000,
            "raw_passenger_component_count": 4,
            "core_passenger_edge_count": 992,
            "discarded_passenger_edge_count": 8,
            "warnings": ["extracted largest passenger component as connected simulation core"],
        }

    def fake_routeability(**kwargs):
        downstream_paths["routeability"] = kwargs["net_file"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "sumocfg_file": str(tmp_path / "routeability" / "demo.sumocfg"),
            "missing_key_edges": [],
            "warnings": [],
        }

    def fake_netedit(net_path):
        downstream_paths["netedit"] = net_path
        return {
            "status": "blocked",
            "claim_status": "diagnostic-demo",
            "netedit_status": "skipped",
            "netedit_network_file": str(net_path),
            "warnings": [],
        }

    def fake_sumo_gui(net_path, _output_dir, _prefix):
        downstream_paths["sumo_gui"] = net_path
        return {
            "status": "blocked",
            "claim_status": "diagnostic-demo",
            "sumo_gui_status": "skipped",
            "sumo_gui_network_file": str(net_path),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="13.6,50.9,13.9,51.1",
        output_dir=tmp_path,
        prefix="demo",
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 2,
            "tls_cluster_count": 1,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        },
        connectivity_func=fake_connectivity,
        connected_core_func=fake_connected_core,
        routeability_func=fake_routeability,
        netedit_func=fake_netedit,
        sumo_gui_func=fake_sumo_gui,
        key_edge_queries=[{"label": "main", "role": "arterial", "search_terms": ["Main"]}],
    )

    assert report["status"] == "pass"
    assert report["gate_status"]["connectivity"] == "pass"
    assert report["connectivity_status"] == "pass"
    assert report["raw_connectivity_status"] == "fail"
    assert report["network_quality"] == "connected-core"
    assert report["net_file"] == str(core_net)
    assert report["raw_net_file"] == str(raw_net)
    assert report["connected_core_file"] == str(core_net)
    assert downstream_paths == {
        "routeability": core_net,
        "netedit": core_net,
        "sumo_gui": core_net,
    }
    assert "extracted largest passenger component as connected simulation core" in report["warnings"]


def test_osm_cleanup_workflow_demotes_partial_connectivity_to_diagnostic_demo(tmp_path: Path) -> None:
    net_file = tmp_path / "sumo" / "partial.net.xml"
    filtered_osm = tmp_path / "osm" / "partial_filtered.osm.xml.gz"

    def fake_build(**kwargs):
        net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": ["primary"],
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="13.6,50.9,13.9,51.1",
        output_dir=tmp_path,
        prefix="partial",
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 2,
            "tls_cluster_count": 1,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        },
        connectivity_func=lambda _path: {
            "status": "fail",
            "claim_status": "construction-invalid",
            "connectivity_status": "fail",
            "passenger_edge_count": 1000,
            "passenger_component_count": 4,
            "largest_component_edge_count": 992,
            "small_component_count": 3,
            "isolated_passenger_edge_count": 2,
            "warnings": ["passenger network has 4 disconnected components"],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, _output_dir, _prefix: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["network_quality"] == "partial-main-component"
    assert report["experiment_readiness"] == "no"
    assert report["strict_connectivity_status"] == "fail"
    assert report["connectivity_main_component_ratio"] == 0.992
    assert report["gate_status"]["connectivity"] == "partial"
    assert any(
        "strict connectivity failed; largest passenger component covers 99.20%" in warning
        for warning in report["warnings"]
    )


def test_osm_cleanup_workflow_keeps_severe_connectivity_failure_invalid(tmp_path: Path) -> None:
    net_file = tmp_path / "sumo" / "severe.net.xml"
    filtered_osm = tmp_path / "osm" / "severe_filtered.osm.xml.gz"

    def fake_build(**kwargs):
        net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": ["primary"],
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="13.6,50.9,13.9,51.1",
        output_dir=tmp_path,
        prefix="severe",
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        },
        connectivity_func=lambda _path: {
            "status": "fail",
            "claim_status": "construction-invalid",
            "connectivity_status": "fail",
            "passenger_edge_count": 1000,
            "passenger_component_count": 20,
            "largest_component_edge_count": 700,
            "small_component_count": 12,
            "isolated_passenger_edge_count": 12,
            "warnings": ["passenger network has 20 disconnected components"],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, _output_dir, _prefix: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
    )

    assert report["status"] == "fail"
    assert report["claim_status"] == "construction-invalid"
    assert report["network_quality"] == "construction-invalid"
    assert report["experiment_readiness"] == "no"
    assert report["strict_connectivity_status"] == "fail"
    assert report["gate_status"]["connectivity"] == "fail"


def test_osm_cleanup_workflow_preserves_historical_user_target(tmp_path: Path) -> None:
    net_file = tmp_path / "sumo" / "historical.net.xml"
    filtered_osm = tmp_path / "osm" / "historical_filtered.osm.xml.gz"

    def fake_build(**kwargs):
        net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": ["primary"],
            "warnings": [],
        }

    captured = {}

    def fake_tls(**kwargs):
        captured.update(kwargs)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "candidates_file": str(tmp_path / "tls_candidates.csv"),
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "google_maps_baseline": {
                "google_maps_baseline_source": "Google Maps",
                "google_maps_temporal_scope": "historical",
                "google_maps_target_date": "2019-06",
                "google_maps_requires_time_confirmation": "no",
            },
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="13.6,50.9,13.9,51.1",
        output_dir=tmp_path,
        prefix="historical",
        map_temporal_scope="historical",
        map_target_date="2019-06",
        build_func=fake_build,
        tls_audit_func=fake_tls,
        connectivity_func=lambda _path: {"status": "pass", "connectivity_status": "pass", "claim_status": "diagnostic-demo", "warnings": []},
        netedit_func=lambda _path: {"status": "blocked", "netedit_status": "unavailable", "claim_status": "diagnostic-demo", "warnings": []},
        sumo_gui_func=lambda _path, _output_dir, _prefix: {"status": "blocked", "sumo_gui_status": "unavailable", "claim_status": "diagnostic-demo", "warnings": []},
    )

    assert captured["google_maps_temporal_scope"] == "historical"
    assert captured["google_maps_target_date"] == "2019-06"
    assert report["map_temporal_scope"] == "historical"
    assert report["map_target_date"] == "2019-06"

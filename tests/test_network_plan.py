from pathlib import Path
import xml.etree.ElementTree as ET

from torii_sumo.core.network_permissions import apply_service_passenger_permissions
from torii_sumo.core.network_plan import derive_network_plan
from torii_sumo.core.osm_workflow import run_osm_cleanup_workflow


def _write_reference_net(path: Path) -> None:
    path.write_text(
        """<net>
    <edge id="primary_a" type="highway.primary">
        <lane id="primary_a_0" index="0" allow="passenger bus" speed="13.9" length="25.0"/>
    </edge>
    <edge id="residential_a" type="highway.residential">
        <lane id="residential_a_0" index="0" speed="13.9" length="25.0"/>
    </edge>
    <edge id="service_a" type="highway.service">
        <lane id="service_a_0" index="0" allow="delivery passenger pedestrian" speed="5.0" length="25.0"/>
    </edge>
    <edge id="service_b" type="highway.service">
        <lane id="service_b_0" index="0" allow="delivery passenger" speed="5.0" length="25.0"/>
    </edge>
    <edge id="cycle_a" type="highway.cycleway">
        <lane id="cycle_a_0" index="0" allow="bicycle" speed="5.0" length="25.0"/>
    </edge>
    <edge id="foot_a" type="highway.footway">
        <lane id="foot_a_0" index="0" allow="pedestrian" speed="5.0" length="25.0"/>
    </edge>
    <edge id="path_rare" type="highway.path">
        <lane id="path_rare_0" index="0" allow="passenger pedestrian" speed="5.0" length="25.0"/>
    </edge>
</net>""",
        encoding="utf-8",
    )


def test_network_plan_blocks_when_layers_and_reference_are_missing() -> None:
    plan = derive_network_plan()

    assert plan["status"] == "blocked"
    assert plan["network_plan_status"] == "needs_user_confirmation"
    assert plan["missing_blockers"] == ["network_plan"]
    assert "traffic layers" in plan["next_question"]
    assert "reference_matched" in plan["network_detail_options"]


def test_network_plan_blocks_named_reference_without_reference_artifact() -> None:
    plan = derive_network_plan(
        user_request="Generate a city-center SUMO network matching a manually cleaned reference network",
    )

    assert plan["status"] == "blocked"
    assert plan["network_plan_status"] == "needs_reference_artifact"
    assert plan["network_detail_target"] == "reference_matched"
    assert plan["reference_target"] == "manually cleaned reference network"
    assert plan["missing_blockers"] == ["reference_network_or_policy"]
    assert "reference SUMO .net.xml" in plan["next_question"]


def test_network_plan_derives_reference_policy_from_reference_net(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "manual-reference.net.xml"
    _write_reference_net(reference_net_file)

    plan = derive_network_plan(
        user_request="Generate an OSM network that matches a manually cleaned reference network",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
    )

    assert plan["status"] == "pass"
    assert plan["network_plan_status"] == "inferred_from_reference_policy"
    assert plan["network_profile"] == "reference_matched"
    assert plan["reference_net_file"] == str(reference_net_file)
    assert plan["network_detail_target"] == "reference_matched"
    assert plan["primary_network_layer"] == "passenger_vehicle"
    assert "service" in plan["highway_classes"]
    assert "primary" in plan["highway_classes"]
    assert "residential" in plan["highway_classes"]
    assert "cycleway" not in plan["highway_classes"]
    assert "footway" not in plan["highway_classes"]
    assert "path" not in plan["highway_classes"]
    assert {"passenger", "bicycle", "pedestrian", "bus"} <= set(plan["movement_layers"])
    assert set(plan["auxiliary_modal_layers"]) == {"bicycle", "pedestrian", "bus"}
    assert plan["reference_policy"]["reference_policy_status"] == "analyzed"
    assert plan["reference_policy"]["passenger_edge_type_counts"]["highway.service"] == 2
    assert plan["service_passenger_policy"] == "reference_match"
    assert "routeability_audit" in plan["validation_gates"]


def test_apply_service_passenger_permissions_adds_passenger_to_service_lanes(tmp_path: Path) -> None:
    net_file = tmp_path / "network.net.xml"
    net_file.write_text(
        """<net>
    <edge id="service_a" type="highway.service">
        <lane id="service_a_0" index="0" allow="bicycle delivery pedestrian" speed="5.0" length="25.0"/>
    </edge>
    <edge id="residential_b" type="highway.residential">
        <lane id="residential_b_0" index="0" allow="passenger" speed="13.9" length="25.0"/>
    </edge>
</net>""",
        encoding="utf-8",
    )

    report = apply_service_passenger_permissions(net_file, policy="allow_vehicle_service")

    root = ET.parse(net_file).getroot()
    service_lane = root.find("./edge[@id='service_a']/lane")
    residential_lane = root.find("./edge[@id='residential_b']/lane")
    assert report["status"] == "pass"
    assert report["service_passenger_permission_status"] == "applied"
    assert report["service_edge_count"] == 1
    assert report["changed_lane_count"] == 1
    assert "passenger" in service_lane.attrib["allow"].split()
    assert residential_lane.attrib["allow"] == "passenger"


def test_osm_cleanup_workflow_uses_reference_net_policy_and_service_policy(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    net_file = tmp_path / "sumo" / "reference-matched.net.xml"
    filtered_osm = tmp_path / "osm" / "reference-matched_filtered.osm.xml.gz"
    captured: dict[str, object] = {}

    def fake_build(**kwargs):
        captured["allowed_highways"] = kwargs["allowed_highways"]
        net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        net_file.write_text(
            """<net>
    <edge id="service_a" type="highway.service">
        <lane id="service_a_0" index="0" allow="bicycle delivery pedestrian" speed="5.0" length="25.0"/>
    </edge>
</net>""",
            encoding="utf-8",
        )
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-matched",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
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
            "passenger_edge_count": 1,
            "passenger_component_count": 1,
            "largest_component_edge_count": 1,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
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

    service_lane = ET.parse(net_file).getroot().find("./edge[@id='service_a']/lane")
    assert report["status"] == "pass"
    assert report["network_profile"] == "reference_matched"
    assert report["network_plan_status"] == "inferred_from_reference_policy"
    assert report["reference_net_file"] == str(reference_net_file)
    assert report["service_passenger_policy"] == "reference_match"
    assert "service" in captured["allowed_highways"]
    assert "cycleway" not in captured["allowed_highways"]
    assert "footway" not in captured["allowed_highways"]
    assert "path" not in captured["allowed_highways"]
    assert "passenger" in service_lane.attrib["allow"].split()
    assert report["service_passenger_permissions"]["changed_lane_count"] == 1

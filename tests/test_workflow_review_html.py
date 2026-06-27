from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


TINY_SUMO_NET = """<?xml version="1.0" encoding="UTF-8"?>
<net version="1.20">
    <location netOffset="0.00,0.00" convBoundary="0.00,0.00,120.00,90.00" origBoundary="0.00,0.00,120.00,90.00" projParameter="!"/>
    <edge id="north" from="n0" to="tls0" type="highway.primary">
        <lane id="north_0" index="0" speed="13.89" length="50.0" shape="60.0,90.0 60.0,50.0"/>
    </edge>
    <edge id="east" from="tls0" to="n1" type="highway.residential">
        <lane id="east_0" index="0" speed="8.33" length="60.0" shape="60.0,50.0 120.0,50.0"/>
    </edge>
    <edge id="walk" from="n2" to="n3" type="highway.footway">
        <lane id="walk_0" index="0" speed="1.4" length="100.0" shape="10.0,20.0 100.0,20.0"/>
    </edge>
    <junction id="n0" type="priority" x="60.0" y="90.0" incLanes="" intLanes=""/>
    <junction id="tls0" type="traffic_light" x="60.0" y="50.0" incLanes="north_0" intLanes=""/>
    <junction id="n1" type="priority" x="120.0" y="50.0" incLanes="east_0" intLanes=""/>
    <junction id="n2" type="priority" x="10.0" y="20.0" incLanes="" intLanes=""/>
    <junction id="n3" type="priority" x="100.0" y="20.0" incLanes="walk_0" intLanes=""/>
</net>
"""


def test_network_visualization_writes_nonempty_png(tmp_path: Path) -> None:
    from PIL import Image
    from torii_sumo.core.network_visualization import build_network_review_visuals

    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text(TINY_SUMO_NET, encoding="utf-8")
    topology = {
        "suspicious_clusters": [
            {"cluster_id": "c1", "centroid_x": 60.0, "centroid_y": 50.0, "aggregation_decision": "join"}
        ]
    }

    report = build_network_review_visuals(
        output_dir=tmp_path / "visuals",
        prefix="review",
        net_file=net_file,
        topology_audit_report=topology,
    )

    assert report["status"] == "pass"
    assert report["visualization_status"] == "pass"
    assert Path(report["network_overview_png"]).is_file()
    assert Path(report["problem_overlay_png"]).is_file()
    assert report["cluster_zoom_pngs"][0]["cluster_id"] == "c1"
    assert Path(report["cluster_zoom_pngs"][0]["image_file"]).is_file()
    assert report["map_layers"]["bounds"]["min_x"] <= 10.0
    assert report["map_layers"]["bounds"]["max_x"] >= 120.0
    assert {edge["category"] for edge in report["map_layers"]["edges"]} == {"major", "vehicle", "soft"}
    assert report["map_layers"]["traffic_lights"] == [{"x": 60.0, "y": 50.0}]
    image = Image.open(report["network_overview_png"])
    assert image.size[0] >= 400
    assert image.size[1] >= 300


def test_workflow_review_html_writes_visual_cockpit_and_sidecars(tmp_path: Path) -> None:
    from torii_sumo.core.workflow_review_html import build_workflow_review_html

    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text(TINY_SUMO_NET, encoding="utf-8")
    best_variant = tmp_path / "teacher_guided_best.net.xml"
    best_variant.write_text(TINY_SUMO_NET, encoding="utf-8")
    teacher_delta = tmp_path / "junction_teacher_delta.json"
    teacher_delta.write_text('{"schema_version": 1}', encoding="utf-8")
    pattern_comparisons = tmp_path / "junction_pattern_comparisons.csv"
    pattern_comparisons.write_text("junction_id,mismatch_fields\nj,internal_function_counts\n", encoding="utf-8")
    pattern_templates = tmp_path / "junction_pattern_templates.json"
    pattern_templates.write_text('{"reference_templates": []}', encoding="utf-8")
    repair_queue = tmp_path / "teacher_guided_queue.json"
    repair_queue.write_text('{"repair_candidates": []}', encoding="utf-8")
    repair_queue_csv = tmp_path / "teacher_guided_queue.csv"
    repair_queue_csv.write_text("reference_id,junction_pattern_mismatch_fields\ncluster_j,has_tls\n", encoding="utf-8")
    repair_run = tmp_path / "teacher_guided_run.json"
    repair_run.write_text('{"status": "blocked"}', encoding="utf-8")

    report = build_workflow_review_html(
        output_dir=tmp_path / "review",
        prefix="workflow",
        title="SUMO Network Review",
        claim_status="construction-invalid",
        summary={
            "status": "fail",
            "claim_status": "construction-invalid",
            "net_file": str(net_file),
            "teacher_guided_repair_best_variant_file": str(best_variant),
            "reference_visual_detail_comparison_net_file": str(best_variant),
            "reference_join_junction_teacher_delta_file": str(teacher_delta),
            "reference_join_junction_pattern_comparisons_file": str(pattern_comparisons),
            "reference_join_junction_pattern_templates_file": str(pattern_templates),
            "teacher_guided_repair_queue_file": str(repair_queue),
            "teacher_guided_repair_queue_csv_file": str(repair_queue_csv),
            "teacher_guided_repair_run_report_file": str(repair_run),
            "teacher_guided_repair_template_contexts": [
                {
                    "teacher_pattern_key": "three_way|control=right_before_left",
                    "teacher_pattern_family": "three_way",
                    "teacher_pattern_template_count": 127,
                    "teacher_pattern_template_examples": ["cluster_template_1"],
                }
            ],
        },
        net_file=net_file,
        gate_status={"routeability_audit": "fail", "topology_audit": "blocked"},
        topology_audit_report={
            "topology_fragmentation_status": "needs_review",
            "suspicious_cluster_count": 1,
            "modal_decision_counts": {"review_required": 1},
            "modal_review_action_counts": {"review_vehicle_core_boundary": 1},
            "junction_aggregation_blocked_by_modal_count": 1,
            "suspicious_clusters": [
                {
                    "cluster_id": "c1",
                    "centroid_x": 60.0,
                    "centroid_y": 50.0,
                    "node_count": 3,
                    "node_ids": ["n0", "tls0", "n1"],
                    "cluster_radius_m": 16.0,
                    "aggregation_decision": "join",
                    "aggregation_confidence": "medium",
                    "modal_aggregation_decision": "review_required",
                    "modal_review_action": "review_vehicle_core_boundary",
                    "modal_reason": "vehicle core mixed with support or terminal infrastructure",
                    "google_maps_url": "https://www.google.com/maps/@48.765391,11.423800,40m",
                }
            ],
        },
        routeability_audit_report={"routeability_status": "teleport-failure", "arrived": 55, "vehicle_count": 100},
    )

    html = Path(report["workflow_review_html_file"]).read_text(encoding="utf-8")
    data_match = re.search(
        r'<script type="application/json" id="torii-review-data">(.+?)</script>',
        html,
        re.DOTALL,
    )
    assert data_match is not None
    review_data = json.loads(data_match.group(1))
    manifest_file = Path(report["review_manifest_file"])
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    workflow_json = json.loads(Path(report["workflow_report_file"]).read_text(encoding="utf-8"))
    manifest_dir = manifest_file.parent
    netedit_additional = Path(report["netedit_review_additional_file"])
    netedit_sumocfg = Path(report["netedit_review_sumocfg_file"])
    netedit_selection = Path(report["netedit_review_selection_files"][0])
    additional_root = ET.parse(netedit_additional).getroot()
    sumocfg_root = ET.parse(netedit_sumocfg).getroot()

    assert "Gate Dashboard" in html
    assert "Torii-SUMO" in html
    assert "Cleanup Review" in html
    assert 'class="torii-review-app"' in html
    assert ".torii-review-app { display: grid; grid-template-columns: 240px minmax(620px, 1fr) 420px; height: 100vh;" in html
    assert 'class="torii-sidebar"' in html
    assert 'class="torii-map-shell"' in html
    assert 'class="torii-review-panel"' in html
    assert 'id="review-panel-toggle"' in html
    assert 'id="map-viewport"' in html
    assert 'id="map-canvas"' in html
    assert 'class="network-svg"' in html
    assert 'class="map-edge edge-major"' in html
    assert '<circle class="junction-marker marker-green"' in html
    assert "zoomInMap" in html
    assert "toggleReviewPanel" in html
    assert "applySelectedJunctions" in html
    assert "Export review plan" in html
    assert "Netedit overlay" in html
    assert "workflow_netedit_review.sumocfg" in html
    assert "workflow_netedit_review_c1_selection.txt" in html
    assert "teacher_guided_best.net.xml" in html
    assert "junction_teacher_delta.json" in html
    assert "junction_pattern_comparisons.csv" in html
    assert "junction_pattern_templates.json" in html
    assert "teacher_guided_queue.json" in html
    assert "copyNeteditCommand" in html
    assert "Aggregate selected junctions" in html
    assert "Network Preview" in html
    assert "Problem Map" in html
    assert "Cluster Zooms" in html
    assert "c1" in html
    assert "google.com/maps" in html
    assert "Junction Aggregation Review" in html
    assert 'data-color-group="green"' in html
    assert 'data-select-color="green"' in html
    assert 'data-cluster-id="c1"' in html
    assert 'data-aggregate-checkbox="c1"' in html
    assert 'data-zoom-src=' in html
    assert 'id="zoom-modal"' in html
    assert "selectColorGroup" in html
    assert "toggleClusterSelection" in html
    assert "openZoom" in html
    assert 'id="cluster-filter"' not in html
    assert "localStorage" not in html
    assert "Review Queue" in html
    assert "Evidence Summary" in html
    assert "topology_fragmentation_status=needs_review" in html
    assert "modal_decision_counts" in html
    assert "modal_review_action_counts" in html
    assert "junction_aggregation_blocked_by_modal_count" in html
    assert "teacher_templates" in html
    assert "family=three_way; count=127; key=three_way|control=right_before_left" in html
    assert "Modal: review_vehicle_core_boundary / review_required" in html
    assert "workflow_summary" not in html
    assert "<img" in html
    assert "file:///" not in html
    assert "visuals/workflow_network_overview.png" in html
    assert review_data["claim_status"] == "construction-invalid"
    assert review_data["navigation"][0]["label"] == "Junction Review"
    assert review_data["visualizations"]["network_overview_png"] == "visuals/workflow_network_overview.png"
    assert review_data["map_layers"]["bounds"]["min_x"] <= 10.0
    assert review_data["map_layers"]["traffic_lights"] == [{"x": 60.0, "y": 50.0}]
    assert review_data["summary_cards"]["uncertain_junctions"] == 1
    assert review_data["junctions"][0]["cluster_id"] == "c1"
    assert review_data["junctions"][0]["modal_review_action"] == "review_vehicle_core_boundary"
    assert review_data["junctions"][0]["image_file"].startswith("visuals/")
    assert review_data["netedit_review"]["additional_file"] == "workflow_netedit_review.add.xml"
    assert review_data["netedit_review"]["sumocfg_file"] == "workflow_netedit_review.sumocfg"
    assert review_data["netedit_review"]["box_overlay_count"] == 1
    assert review_data["netedit_review"]["edge_overlay_count"] == 0
    assert review_data["netedit_review"]["junction_overlay_count"] == 0
    assert review_data["netedit_review"]["selection_file_count"] == 1
    assert review_data["netedit_review"]["cluster_selection_files"][0]["selection_file"] == "workflow_netedit_review_c1_selection.txt"
    assert review_data["junctions"][0]["netedit_selection_file"] == "workflow_netedit_review_c1_selection.txt"
    assert review_data["junctions"][0]["netedit_command"] == (
        'netedit --sumocfg-file "workflow_netedit_review.sumocfg" '
        '--selection-file "workflow_netedit_review_c1_selection.txt"'
    )
    assert manifest["visualizations"]["network_overview_png"]
    assert manifest["artifacts"]["netedit_review_additional_file"] == "workflow_netedit_review.add.xml"
    assert manifest["artifacts"]["netedit_review_sumocfg_file"] == "workflow_netedit_review.sumocfg"
    assert manifest["artifacts"]["teacher_guided_repair_best_variant_file"] == "../teacher_guided_best.net.xml"
    assert manifest["artifacts"]["reference_visual_detail_comparison_net_file"] == "../teacher_guided_best.net.xml"
    assert manifest["artifacts"]["reference_join_junction_teacher_delta_file"] == "../junction_teacher_delta.json"
    assert manifest["artifacts"]["reference_join_junction_pattern_comparisons_file"] == "../junction_pattern_comparisons.csv"
    assert manifest["artifacts"]["reference_join_junction_pattern_templates_file"] == "../junction_pattern_templates.json"
    assert manifest["artifacts"]["teacher_guided_repair_queue_file"] == "../teacher_guided_queue.json"
    assert manifest["artifacts"]["teacher_guided_repair_queue_csv_file"] == "../teacher_guided_queue.csv"
    assert manifest["artifacts"]["teacher_guided_repair_run_report_file"] == "../teacher_guided_run.json"
    assert manifest["netedit_review"]["netedit_command"] == 'netedit --sumocfg-file "workflow_netedit_review.sumocfg"'
    assert manifest["netedit_review"]["selection_file_count"] == 1
    assert manifest["review_app"]["map_layers"]["edges"]
    assert manifest["review_app"]["summary_cards"]["uncertain_junctions"] == 1
    assert manifest["review_app"]["junctions"][0]["cluster_id"] == "c1"
    assert report["workflow_review_net_file"] == str(net_file)
    assert manifest["visualizations"]["problem_overlay_png"]
    assert manifest["visualizations"]["cluster_zoom_pngs"][0]["cluster_id"] == "c1"
    assert (manifest_dir / manifest["visualizations"]["cluster_zoom_pngs"][0]["image_file"]).is_file()
    assert workflow_json["claim_status"] == "construction-invalid"
    assert netedit_additional.is_file()
    assert netedit_sumocfg.is_file()
    assert netedit_selection.read_text(encoding="utf-8").splitlines() == ["junction:n0", "junction:tls0", "junction:n1"]
    assert additional_root.tag == "additional"
    assert additional_root.findall("./poi") == []
    assert len(additional_root.findall("./poly")) == 1
    assert additional_root.find("./poly[@id='torii_c1_review_box']").attrib["shape"].startswith("44,34")
    assert sumocfg_root.find("./input/net-file").attrib["value"] == "../candidate.net.xml"
    assert sumocfg_root.find("./input/additional-files").attrib["value"] == "workflow_netedit_review.add.xml"

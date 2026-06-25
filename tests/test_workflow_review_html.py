from __future__ import annotations

import json
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
    image = Image.open(report["network_overview_png"])
    assert image.size[0] >= 400
    assert image.size[1] >= 300


def test_workflow_review_html_writes_visual_cockpit_and_sidecars(tmp_path: Path) -> None:
    from torii_sumo.core.workflow_review_html import build_workflow_review_html

    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text(TINY_SUMO_NET, encoding="utf-8")

    report = build_workflow_review_html(
        output_dir=tmp_path / "review",
        prefix="workflow",
        title="SUMO Network Review",
        claim_status="construction-invalid",
        summary={"status": "fail", "claim_status": "construction-invalid", "net_file": str(net_file)},
        net_file=net_file,
        gate_status={"routeability_audit": "fail", "topology_audit": "blocked"},
        topology_audit_report={"topology_fragmentation_status": "needs_review", "suspicious_cluster_count": 1},
        routeability_audit_report={"routeability_status": "teleport-failure", "arrived": 55, "vehicle_count": 100},
    )

    html = Path(report["workflow_review_html_file"]).read_text(encoding="utf-8")
    manifest = json.loads(Path(report["review_manifest_file"]).read_text(encoding="utf-8"))
    workflow_json = json.loads(Path(report["workflow_report_file"]).read_text(encoding="utf-8"))

    assert "Gate Dashboard" in html
    assert "Network Preview" in html
    assert "Problem Map" in html
    assert "Review Queue" in html
    assert "<img" in html
    assert manifest["visualizations"]["network_overview_png"]
    assert manifest["visualizations"]["problem_overlay_png"]
    assert workflow_json["claim_status"] == "construction-invalid"

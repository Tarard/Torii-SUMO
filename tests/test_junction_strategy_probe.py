import json
from pathlib import Path

from torii_sumo.core.junction_strategy_probe import (
    convex_hull,
    parse_net,
    probe_junction_strategies,
    strategy_node_sets,
)


def test_convex_hull_discards_inner_points() -> None:
    hull = convex_hull([(0, 0), (1, 0), (1, 1), (0, 1), (0.4, 0.4)])

    assert hull == [(0, 0), (1, 0), (1, 1), (0, 1)]


def test_strategy_node_sets_keep_vehicle_core_separate_from_modal_stubs(tmp_path: Path) -> None:
    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text(
        """<net>
  <edge id="ab" from="a" to="b" type="highway.unclassified">
    <lane id="ab_0" index="0" length="0.2" shape="0,0 0.2,0"/>
  </edge>
  <edge id="bc" from="b" to="c" type="highway.residential">
    <lane id="bc_0" index="0" length="0.2" shape="0.2,0 0.4,0"/>
  </edge>
  <edge id="bp" from="b" to="p" type="highway.footway">
    <lane id="bp_0" index="0" length="0.2" shape="0.2,0 0.2,0.2"/>
  </edge>
  <junction id="a" x="0" y="0" type="priority"/>
  <junction id="b" x="0.2" y="0" type="priority"/>
  <junction id="c" x="0.4" y="0" type="priority"/>
  <junction id="p" x="0.2" y="0.2" type="priority"/>
</net>
""",
        encoding="utf-8",
    )
    net = parse_net(net_file)

    strategies = strategy_node_sets(net, seed_node_ids=["a", "b"], radius_m=5, short_edge_m=1)

    assert strategies["radius_all_top_level"] == {"a", "b", "c", "p"}
    assert strategies["short_vehicle_core"] == {"a", "b", "c"}
    assert strategies["short_all_core"] == {"a", "b", "c", "p"}


def test_probe_writes_comparison_artifacts(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.net.xml"
    reference = tmp_path / "reference.net.xml"
    candidate.write_text(
        """<net>
  <edge id="ab" from="a" to="b" type="highway.unclassified"><lane id="ab_0" index="0" length="0.2" shape="0,0 1,0"/></edge>
  <edge id="bp" from="b" to="p" type="highway.footway"><lane id="bp_0" index="0" length="0.2" shape="1,0 1,1"/></edge>
  <junction id="a" x="0" y="0" type="priority" shape="0,0 0,1 1,1 1,0"/>
  <junction id="b" x="1" y="0" type="priority" shape="1,0 1,1 2,1 2,0"/>
  <junction id="p" x="1" y="1" type="priority"/>
</net>
""",
        encoding="utf-8",
    )
    reference.write_text(
        """<net>
  <junction id="cluster_a_b" x="1000.5" y="1000" type="traffic_light" shape="1000,1000 1000,1001 1002,1001 1002,1000"/>
</net>
""",
        encoding="utf-8",
    )

    report = probe_junction_strategies(
        candidate_net_file=candidate,
        reference_net_file=reference,
        reference_junction_id="cluster_a_b",
        output_dir=tmp_path / "out",
        radius_m=5,
        short_edge_m=1,
    )

    assert report["status"] == "pass"
    assert {"reference_core", "radius_all_top_level", "short_vehicle_core", "short_all_core"} <= set(
        report["strategies"]
    )
    assert Path(report["summary_file"]).is_file()
    assert Path(report["csv_file"]).is_file()
    assert Path(report["svg_file"]).is_file()
    assert Path(report["png_file"]).is_file()
    assert json.loads(Path(report["summary_file"]).read_text(encoding="utf-8"))["status"] == "pass"
    assert report["strategies"]["reference_core"]["footprint"]["centroid_distance_to_reference"] < 2

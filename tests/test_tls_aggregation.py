from pathlib import Path

from torii_sumo.core.tls_aggregation import build_tls_aggregation_variant


def test_build_tls_aggregation_variant_sets_one_real_junction_per_tls_cluster(tmp_path: Path) -> None:
    net_file = tmp_path / "candidate.net.xml"
    clusters_file = tmp_path / "tls_clusters.csv"
    net_file.write_text("<net/>", encoding="utf-8")
    clusters_file.write_text(
        "\n".join(
            [
                "cluster_id,tls_ids,tls_count,google_maps_url",
                "G001,tlA;tlB,2,https://maps.example/g1",
                "G002,tlC,1,https://maps.example/g2",
            ]
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_command_runner(command, **_kwargs):
        calls.append(command)
        output_file = Path(command[command.index("--output-file") + 1])
        output_file.write_text(
            """<net>
  <junction id="n1" type="traffic_light"/>
  <junction id="n3" type="traffic_light"/>
  <tlLogic id="n1" type="static"/>
  <tlLogic id="n3" type="static"/>
</net>""",
            encoding="utf-8",
        )
        return {"status": "pass", "returncode": 0, "stdout": "Success.", "stderr": "", "error": ""}

    report = build_tls_aggregation_variant(
        net_file=net_file,
        tls_audit_report={
            "status": "pass",
            "tls_cluster_count": 2,
            "clusters_file": str(clusters_file),
        },
        output_dir=tmp_path / "tls_aggregation",
        prefix="demo_tls",
        command_runner=fake_command_runner,
        controlled_nodes_by_tls_func=lambda _net_file: {
            "tlA": ["n1"],
            "tlB": ["n1", "n2"],
            "tlC": ["n3"],
        },
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "blocked"
    assert report["tls_aggregation_status"] == "variant_created_for_review"
    assert report["tls_physical_cluster_count"] == 2
    assert report["tls_aggregated_tl_logic_count"] == 2
    assert report["tls_aggregated_traffic_light_junction_count"] == 2
    assert Path(report["tls_aggregation_variant_file"]).is_file()
    assert Path(report["tls_aggregation_plan_file"]).is_file()
    command = calls[0]
    assert "--tls.discard-loaded" in command
    assert command[command.index("--tls.set") + 1] == "n1,n3"
    assert command[command.index("--sumo-net-file") + 1] == str(net_file)


def test_build_tls_aggregation_variant_skips_when_no_tls_clusters(tmp_path: Path) -> None:
    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    report = build_tls_aggregation_variant(
        net_file=net_file,
        tls_audit_report={"status": "pass", "tls_cluster_count": 0},
        output_dir=tmp_path / "tls_aggregation",
        prefix="demo_tls",
        command_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not run netconvert")),
        controlled_nodes_by_tls_func=lambda _net_file: {},
    )

    assert report["status"] == "pass"
    assert report["tls_aggregation_status"] == "not_needed"
    assert report["tls_physical_cluster_count"] == 0
    assert report["tls_aggregation_variant_file"] == ""


def test_build_tls_aggregation_variant_reports_controlled_node_parse_failure(tmp_path: Path) -> None:
    net_file = tmp_path / "candidate.net.xml"
    clusters_file = tmp_path / "tls_clusters.csv"
    net_file.write_text("<net/>", encoding="utf-8")
    clusters_file.write_text(
        "\n".join(["cluster_id,tls_ids,tls_count,google_maps_url", "G001,tlA,1,https://maps.example/g1"]),
        encoding="utf-8",
    )

    report = build_tls_aggregation_variant(
        net_file=net_file,
        tls_audit_report={"status": "pass", "tls_cluster_count": 1, "clusters_file": str(clusters_file)},
        output_dir=tmp_path / "tls_aggregation",
        prefix="demo_tls",
        command_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not run netconvert")),
        controlled_nodes_by_tls_func=lambda _net_file: (_ for _ in ()).throw(RuntimeError("bad TLS programs")),
    )

    assert report["status"] == "fail"
    assert report["tls_aggregation_status"] == "failed"
    assert "could not derive TLS-controlled junctions" in report["error"]
    assert report["tls_aggregation_variant_file"] == ""

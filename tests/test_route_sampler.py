from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from pathlib import Path

from torii_sumo.core.command_runner import CommandResult
from torii_sumo.core.route_sampler import (
    audit_route_constraint_structure,
    run_route_sampler,
    validate_route_sampler_edge_counts,
)


def test_route_sampler_wrapper_writes_candidates_executes_and_hashes(tmp_path: Path) -> None:
    manifest = tmp_path / "routes.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["route_id", "edges"])
        writer.writeheader()
        writer.writerow({"route_id": "r0", "edges": "a b c"})
    edge_data = tmp_path / "counts.xml"
    root = ET.Element("data")
    for begin in range(0, 1800, 900):
        interval = ET.SubElement(root, "interval", begin=str(begin), end=str(begin + 900))
        ET.SubElement(interval, "edge", id="b", count="4")
    ET.ElementTree(root).write(edge_data, encoding="utf-8", xml_declaration=True)
    script = tmp_path / "routeSampler.py"
    script.write_text("# synthetic routeSampler\n", encoding="utf-8")

    def fake_runner(command: list[str], **kwargs: object) -> CommandResult:
        assert kwargs["cwd"] == tmp_path / "out"
        assert command[command.index("--optimize") + 1] == "full"
        for option in ("-r", "--edgedata-files", "--mismatch-output", "-o"):
            assert Path(command[command.index(option) + 1]).is_absolute()
        output = Path(command[command.index("-o") + 1])
        mismatch = Path(command[command.index("--mismatch-output") + 1])
        output.write_text("<routes><vehicle id='v0' depart='0'><route edges='a b c'/></vehicle></routes>", encoding="utf-8")
        mismatch.write_text("<data><edge id='b' deficit='0'/></data>", encoding="utf-8")
        return CommandResult(command=command, cwd=str(tmp_path), status="pass", returncode=0)

    report = run_route_sampler(
        candidate_manifest_csv=manifest,
        edge_data_file=edge_data,
        output_dir=tmp_path / "out",
        prefix="sample",
        begin=0,
        end=1800,
        interval=900,
        optimize="full",
        route_sampler_script=script,
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["candidate_route_count"] == 1
    assert Path(str(report["demand_route_file"])).is_file()
    assert report["mismatch"]["absolute_deficit"] == 0
    assert Path(str(report["command_manifest"])).is_file()
    assert report["constraint_structure"]["status"] == "pass"


def test_route_sampler_edge_data_rejects_missing_bin(tmp_path: Path) -> None:
    edge_data = tmp_path / "counts.xml"
    edge_data.write_text("<data><interval begin='0' end='900'><edge id='a' count='1'/></interval></data>", encoding="utf-8")
    try:
        validate_route_sampler_edge_counts(edge_data, begin=0, end=1800, interval=900)
    except ValueError as exc:
        assert "exactly cover" in str(exc)
    else:
        raise AssertionError("missing routeSampler bin was accepted")


def test_route_sampler_reports_nonzero_mismatch_as_partial(tmp_path: Path) -> None:
    manifest = tmp_path / "routes.csv"
    manifest.write_text("route_id,edges\nr0,a b\n", encoding="utf-8")
    edge_data = tmp_path / "counts.xml"
    edge_data.write_text(
        "<data><interval begin='0' end='900'><edge id='a' count='10'/></interval></data>",
        encoding="utf-8",
    )
    script = tmp_path / "routeSampler.py"
    script.write_text("# synthetic routeSampler\n", encoding="utf-8")

    def fake_runner(command: list[str], **_kwargs: object) -> CommandResult:
        Path(command[command.index("-o") + 1]).write_text("<routes/>", encoding="utf-8")
        Path(command[command.index("--mismatch-output") + 1]).write_text(
            "<data><edge id='a' deficit='2'/></data>",
            encoding="utf-8",
        )
        return CommandResult(command=command, cwd=str(tmp_path), status="pass", returncode=0)

    report = run_route_sampler(
        candidate_manifest_csv=manifest,
        edge_data_file=edge_data,
        output_dir=tmp_path / "out",
        prefix="sample",
        begin=0,
        end=900,
        interval=900,
        route_sampler_script=script,
        command_runner=fake_runner,
    )

    assert report["status"] == "partial"
    assert report["constraint_match_fraction"] == 0.8


def test_route_constraint_structure_reports_identical_path_incidence_conflict(tmp_path: Path) -> None:
    manifest = tmp_path / "routes.csv"
    manifest.write_text(
        "route_id,edges\n"
        "r0,\"a b c\"\n"
        "r1,\"a b d\"\n",
        encoding="utf-8",
    )
    edge_data = tmp_path / "counts.xml"
    edge_data.write_text(
        "<data><interval begin='0' end='900'>"
        "<edge id='a' count='10'/><edge id='b' count='9'/>"
        "</interval></data>",
        encoding="utf-8",
    )

    report = audit_route_constraint_structure(
        manifest,
        edge_data,
        begin=0,
        end=900,
        interval=900,
    )

    assert report["status"] == "fail"
    assert report["conflict_count"] == 1
    assert report["conflicts"][0]["kind"] == "identical_route_incidence_count_conflict"


def test_route_constraint_structure_reports_positive_uncovered_edge(tmp_path: Path) -> None:
    manifest = tmp_path / "routes.csv"
    manifest.write_text("route_id,edges\nr0,a,b\n", encoding="utf-8")
    edge_data = tmp_path / "counts.xml"
    edge_data.write_text(
        "<data><interval begin='0' end='900'>"
        "<edge id='a' count='0'/><edge id='missing' count='2'/>"
        "</interval></data>",
        encoding="utf-8",
    )

    report = audit_route_constraint_structure(
        manifest,
        edge_data,
        begin=0,
        end=900,
        interval=900,
    )

    assert report["status"] == "fail"
    assert report["conflicts"] == [
        {
            "kind": "positive_count_without_candidate_route",
            "interval_begin": 0,
            "edge": "missing",
            "count": 2,
        }
    ]

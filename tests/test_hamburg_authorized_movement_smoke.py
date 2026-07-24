from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from torii_sumo.core.candidate_contracts import file_sha256
from torii_sumo.core.command_runner import CommandResult
from torii_sumo.core.hamburg_authorized_movement_smoke import (
    HamburgMovementAuthorityError,
    run_hamburg_authorized_movement_smoke,
    validate_hamburg_movement_authority,
)


def _network(path: Path, *, turnaround: bool = False) -> Path:
    path.write_text(
        f"""<net>
  <edge id="a" from="n0" to="n1"><lane id="a_0" index="0" speed="13.9" length="10"/></edge>
  <edge id="b" from="n1" to="n2"><lane id="b_0" index="0" speed="13.9" length="10"/></edge>
  <edge id="c" from="n2" to="n3"><lane id="c_0" index="0" speed="13.9" length="10"/></edge>
  <edge id="candidate_only" from="n1" to="n4"><lane id="candidate_only_0" index="0" speed="13.9" length="10"/></edge>
  <connection from="a" to="b" fromLane="0" toLane="0" dir="{'t' if turnaround else 's'}"/>
  <connection from="b" to="c" fromLane="0" toLane="0" dir="s"/>
  <connection from="a" to="candidate_only" fromLane="0" toLane="0" dir="r"/>
</net>
""",
        encoding="utf-8",
    )
    return path


def _authority(
    path: Path,
    *,
    evidence: Path,
    route_edges: list[str] | None = None,
    evidence_kind: str = "hamburg_cad",
) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": "torii.hamburg-movement-authority/v1",
                "status": "review_required",
                "authority_id": "cad-aerial-v1",
                "generated_from_candidate": False,
                "source_evidence": [
                    {
                        "evidence_id": "cad-1",
                        "kind": evidence_kind,
                        "path": str(evidence),
                        "sha256": file_sha256(evidence),
                    }
                ],
                "movements": [
                    {
                        "movement_key": "a-via-b-to-c",
                        "route_edges": route_edges or ["a", "b", "c"],
                        "depart_lane": 0,
                        "arrival_lane": 0,
                        "evidence_ids": ["cad-1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_smoke_routes_come_only_from_authority_and_counts_pass(tmp_path: Path) -> None:
    net = _network(tmp_path / "network.net.xml")
    evidence = tmp_path / "cad.pdf"
    evidence.write_bytes(b"independent-cad")
    authority = _authority(tmp_path / "authority.json", evidence=evidence)

    def fake_runner(
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 60,
    ) -> CommandResult:
        assert cwd is not None
        config = ET.parse(cwd / command[command.index("-c") + 1]).getroot()
        route_path = cwd / config.find("input/route-files").attrib["value"]
        assert [
            route.attrib["edges"]
            for route in ET.parse(route_path).getroot().iter("route")
        ] == ["a b c"]
        assert "candidate_only" not in route_path.read_text(encoding="utf-8")
        summary_path = cwd / config.find("output/summary-output").attrib["value"]
        tripinfo_path = cwd / config.find("output/tripinfo-output").attrib["value"]
        summary_path.write_text(
            '<summary><step time="20" loaded="1" inserted="1" arrived="1" '
            'ended="1" running="0" waiting="0" teleports="0" collisions="0"/></summary>',
            encoding="utf-8",
        )
        tripinfo_path.write_text(
            '<tripinfos><tripinfo id="authority_movement_000" duration="10" '
            'waitingTime="0" timeLoss="0"/></tripinfos>',
            encoding="utf-8",
        )
        return CommandResult(
            command=command,
            cwd=str(cwd),
            status="pass",
            returncode=0,
        )

    report = run_hamburg_authorized_movement_smoke(
        authority_file=authority,
        candidate_net_file=net,
        output_dir=tmp_path / "smoke",
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["automatic_promotion_gate"] == "blocked"
    assert report["authority_review_status"] == "review_required"
    assert report["movement_keys"] == ["a-via-b-to-c"]
    assert report["loaded"] == report["inserted"] == report["ended"] == 1
    assert report["running"] == report["waiting"] == 0
    assert report["teleports"] == report["collisions"] == 0
    assert report["inputs"]["movement_authority"]["sha256"] == file_sha256(authority)
    assert report["inputs"]["movement_authority"]["path"] == "../authority.json"
    assert Path(report["report_file"]).is_file()


def test_disconnected_authority_route_is_rejected(tmp_path: Path) -> None:
    net = _network(tmp_path / "network.net.xml")
    evidence = tmp_path / "cad.pdf"
    evidence.write_bytes(b"independent-cad")
    authority = _authority(
        tmp_path / "authority.json",
        evidence=evidence,
        route_edges=["a", "c"],
    )

    validation = validate_hamburg_movement_authority(
        authority_file=authority,
        candidate_net_file=net,
    )

    assert validation["status"] == "blocked"
    assert validation["errors"] == ["a-via-b-to-c: no candidate connection for a -> c"]
    with pytest.raises(HamburgMovementAuthorityError, match="no candidate connection"):
        run_hamburg_authorized_movement_smoke(
            authority_file=authority,
            candidate_net_file=net,
            output_dir=tmp_path / "smoke",
        )


def test_lane_discontinuous_authority_route_is_rejected(tmp_path: Path) -> None:
    net = tmp_path / "network.net.xml"
    net.write_text(
        """<net>
  <edge id="a" from="n0" to="n1">
    <lane id="a_0" index="0" speed="13.9" length="10"/>
  </edge>
  <edge id="b" from="n1" to="n2">
    <lane id="b_0" index="0" speed="13.9" length="10"/>
    <lane id="b_1" index="1" speed="13.9" length="10"/>
  </edge>
  <edge id="c" from="n2" to="n3">
    <lane id="c_0" index="0" speed="13.9" length="10"/>
  </edge>
  <connection from="a" to="b" fromLane="0" toLane="1" dir="s"/>
  <connection from="b" to="c" fromLane="0" toLane="0" dir="l"/>
</net>
""",
        encoding="utf-8",
    )
    evidence = tmp_path / "cad.pdf"
    evidence.write_bytes(b"independent-cad")
    authority = _authority(tmp_path / "authority.json", evidence=evidence)

    validation = validate_hamburg_movement_authority(
        authority_file=authority,
        candidate_net_file=net,
    )

    assert validation["status"] == "blocked"
    assert validation["errors"] == [
        "a-via-b-to-c: no candidate connection for b -> c"
    ]


def test_candidate_turnaround_requires_explicit_authority_kind(tmp_path: Path) -> None:
    net = _network(tmp_path / "network.net.xml", turnaround=True)
    evidence = tmp_path / "aerial.png"
    evidence.write_bytes(b"independent-aerial")
    authority = _authority(tmp_path / "authority.json", evidence=evidence)

    blocked = validate_hamburg_movement_authority(
        authority_file=authority,
        candidate_net_file=net,
    )
    assert blocked["status"] == "blocked"
    assert blocked["errors"] == [
        "a-via-b-to-c: candidate dir=t lacks turnaround authority evidence"
    ]

    allowed_authority = _authority(
        tmp_path / "allowed-authority.json",
        evidence=evidence,
        evidence_kind="official_movement_allowlist",
    )
    allowed = validate_hamburg_movement_authority(
        authority_file=allowed_authority,
        candidate_net_file=net,
    )
    assert allowed["status"] == "pass"
    assert allowed["movements"][0]["includes_candidate_turnaround"] is True

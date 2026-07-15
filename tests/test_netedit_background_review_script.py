from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT = Path("plugins/torii-sumo/scripts/netedit_background_review.py")


def _load_script():
    spec = importlib.util.spec_from_file_location("netedit_background_review", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_bound_bundle(tmp_path: Path, script):
    source = tmp_path / "source.net.xml"
    source.write_text(
        '<net><tlLogic id="old_tls"><phase duration="30" state="G"/>'
        '</tlLogic><junction id="old_j" type="traffic_light" x="0" y="0"/>'
        '<edge id="source_in" from="outside" to="old_j"><lane id="source_in_0"/>'
        '</edge><connection from="source_in" to="source_out" fromLane="0" '
        'toLane="0" tl="old_tls" linkIndex="0"/></net>',
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.net.xml"
    candidate.write_text(
        '<net><tlLogic id="target_tls"><phase duration="30" state="G"/>'
        '</tlLogic><junction id="target_j" type="traffic_light" x="1" y="2" '
        'incLanes="candidate_in_0"/><edge id="candidate_in" from="outside" '
        'to="target_j"><lane id="candidate_in_0"/></edge><connection '
        'from="candidate_in" to="candidate_out" fromLane="0" toLane="0" '
        'tl="target_tls" linkIndex="0"/></net>',
        encoding="utf-8",
    )
    ownership = script.audit_tls_ownership_rebuild(
        source_net=source,
        candidate_net=candidate,
        target_source_junction_ids=("old_j",),
        target_candidate_junction_id="target_j",
        expected_controller_ids=("target_tls",),
        expected_controlled_connection_count=1,
        report_schema="torii.test-tls-ownership/v1",
    )
    nema_candidate = tmp_path / "nema.candidate.net.xml"
    nema_candidate.write_text(
        candidate.read_text(encoding="utf-8").replace(
            '<tlLogic id="target_tls">',
            '<tlLogic id="target_tls" type="NEMA">',
        ),
        encoding="utf-8",
    )
    nema_ownership = script.audit_tls_ownership_rebuild(
        source_net=source,
        candidate_net=nema_candidate,
        target_source_junction_ids=("old_j",),
        target_candidate_junction_id="target_j",
        expected_controller_ids=("target_tls",),
        expected_controlled_connection_count=1,
        report_schema="torii.test-nema-tls-ownership/v1",
    )
    topology = tmp_path / "tls-topology.json"
    topology.write_text(
        json.dumps(
            {
                "automatic_promotion_gate": "blocked",
                "status": "candidate_ready_for_review",
                "candidate_net_file": str(nema_candidate),
                "candidate_sha256": script.file_sha256(nema_candidate),
                "standard_builder": {},
                "tls_ownership": {
                    "status": nema_ownership["status"],
                    "controller_ids": nema_ownership["candidate"]["target_controller_ids"],
                    "controlled_connection_count": nema_ownership["candidate"]["target_controlled_connection_count"],
                    "signal_group_count": nema_ownership["candidate"]["target_signal_group_count"],
                },
            }
        ),
        encoding="utf-8",
    )
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "automatic_promotion_gate": "blocked",
                "source_net_file": str(source),
                "source_sha256": script.file_sha256(source),
                "candidate_net_file": str(candidate),
                "candidate_sha256": script.file_sha256(candidate),
                "tls_ownership": ownership,
                "tls_topology": {
                    "status": "candidate_ready_for_review",
                    "artifact_file": str(topology),
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "automatic_promotion_gate": "blocked",
                "artifacts": [
                    {"path": str(summary), "sha256": script.file_sha256(summary)},
                    {"path": str(source), "sha256": script.file_sha256(source)},
                    {
                        "path": str(candidate),
                        "sha256": script.file_sha256(candidate),
                    },
                    {
                        "path": str(nema_candidate),
                        "sha256": script.file_sha256(nema_candidate),
                    },
                    {
                        "path": str(topology),
                        "sha256": script.file_sha256(topology),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return source, candidate, summary, manifest


def test_reads_target_and_builds_capture_requests(tmp_path: Path) -> None:
    script = _load_script()
    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text(
        '<net><junction id="j0" type="traffic_light" x="12.5" y="34.25" incLanes="e0_0 e1_0 e1_1"/></net>',
        encoding="utf-8",
    )

    target = script.read_target_junction(net_file, "j0")
    requests = script.capture_requests(target)

    assert target.x == 12.5
    assert target.y == 34.25
    assert target.incoming_lanes == ("e0_0", "e1_0", "e1_1")
    assert [request.mode for request in requests[:3]] == [
        "inspect",
        "tls",
        "connection",
    ]
    assert len(requests) == 3
    assert {request.selection_id for request in requests} == {"j0"}


def test_viewsettings_selection_and_mode_are_deterministic() -> None:
    script = _load_script()

    assert script.viewsettings_text((12.5, 34.25), zoom=500) == (
        "<viewsettings>\n"
        '  <viewport zoom="500" x="12.5" y="34.25" angle="0"/>\n'
        '  <delay value="100"/>\n'
        "</viewsettings>\n"
    )
    assert script.selection_text("junction", "j0") == "junction:j0\n"
    assert script.selection_text("lane", "e0_0") == "lane:e0_0\n"
    assert script.mode_key("inspect") is None
    assert script.mode_key("connection") == "C"
    assert script.mode_key("tls") == "T"


def test_netedit_command_binds_view_selection_and_disables_registry_viewport() -> None:
    script = _load_script()

    command = script.build_netedit_command(
        netedit_binary="netedit",
        net_file=Path("candidate.net.xml"),
        view_file=Path("target.view.xml"),
        selection_file=Path("target.selection.txt"),
        additional_file=Path("review.add.xml"),
        window_size="1400,1000",
        window_pos="20,20",
    )

    assert command == [
        "netedit",
        "-s",
        "candidate.net.xml",
        "-g",
        "target.view.xml",
        "--selection-file",
        "target.selection.txt",
        "--registry-viewport",
        "false",
        "--window-size",
        "1400,1000",
        "--window-pos",
        "20,20",
        "--additional-files",
        "review.add.xml",
    ]


def test_candidate_identity_refuses_source_baseline(tmp_path: Path) -> None:
    script = _load_script()
    source, _, summary, manifest = _write_bound_bundle(tmp_path, script)
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["candidate_net_file"] = str(source)
    payload["candidate_sha256"] = script.file_sha256(source)
    summary.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="source baseline"):
        script.load_bound_candidate_identity(
            summary_file=summary,
            manifest_file=manifest,
        )


def test_candidate_identity_requires_exact_manifest_hash(tmp_path: Path) -> None:
    script = _load_script()
    _, candidate, summary, manifest = _write_bound_bundle(tmp_path, script)

    identity = script.load_bound_candidate_identity(
        summary_file=summary,
        manifest_file=manifest,
    )
    assert identity.candidate_file == candidate.resolve()
    assert identity.target_junction_id == "target_j"
    assert identity.tls_ownership_recheck["status"] == "pass"

    nema_identity = script.load_bound_candidate_identity(
        summary_file=summary,
        manifest_file=manifest,
        candidate_role="nema-topology",
    )
    assert nema_identity.candidate_role == "nema-topology"
    assert nema_identity.candidate_file.name == "nema.candidate.net.xml"
    assert nema_identity.candidate_evidence_file == (tmp_path / "tls-topology.json").resolve()

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    for artifact in payload["artifacts"]:
        if Path(artifact["path"]).name == candidate.name:
            artifact["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="Manifest hash mismatch"):
        script.load_bound_candidate_identity(
            summary_file=summary,
            manifest_file=manifest,
        )

from __future__ import annotations

import json

import pytest

from torii_sumo import cli


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("complete", 0),
        ("ready", 0),
        ("review_ready", 1),
        ("topology_ready", 1),
    ],
)
def test_workflow_statuses_use_non_error_exit_codes(status: str, expected: int) -> None:
    assert cli._exit_code({"status": status}) == expected


def test_cli_network_routeability_runs_the_long_check(monkeypatch, capsys) -> None:
    calls: list[dict[str, object]] = []

    def fake_routeability(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"status": "pass", "claim_status": "construction-check"}

    monkeypatch.setattr(cli, "sumo_network_routeability_audit", fake_routeability, raising=False)

    exit_code = cli.main(
        [
            "network",
            "routeability",
            "network.net.xml",
            "audit-output",
            "--vehicle-count",
            "12",
            "--timeout-seconds",
            "90",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "pass"
    assert calls == [
        {
            "net_file": "network.net.xml",
            "output_dir": "audit-output",
            "prefix": "routeability_audit",
            "vehicle_count": 12,
            "seed": 42,
            "initial_end": 300,
            "max_end": 2400,
            "timeout_seconds": 90.0,
        }
    ]


def test_manifest_workflow_exposes_long_and_specialized_families() -> None:
    expected = {
        "sumo_run_config",
        "sumo_osm_cleanup_workflow",
        "sumo_network_corridor_candidate_gates",
        "sumo_intersection_scene_workflow",
        "sumo_detector_route_sampler_calibrate",
        "sumo_hamburg_sandtorkai_execution_plan",
        "sumo_collect_evidence",
    }

    assert expected <= set(cli.WORKFLOW_TOOLS)


def test_manifest_workflow_calls_allowlisted_function(monkeypatch, tmp_path, capsys) -> None:
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"output_dir": "out", "bbox": "1,2,3,4"}), encoding="utf-8")
    calls: list[dict[str, object]] = []

    def fake_workflow(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"status": "pass", "claim_status": "construction-check"}

    monkeypatch.setitem(cli.WORKFLOW_TOOLS, "sumo_osm_cleanup_workflow", fake_workflow)

    exit_code = cli.main(["workflow", "sumo_osm_cleanup_workflow", str(request), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "pass"
    assert calls == [{"output_dir": "out", "bbox": "1,2,3,4"}]


def test_manifest_workflow_rejects_non_object_json(tmp_path, capsys) -> None:
    request = tmp_path / "request.json"
    request.write_text("[]", encoding="utf-8")

    exit_code = cli.main(["workflow", "sumo_run_config", str(request), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 3
    assert payload["status"] == "error"
    assert "JSON object" in payload["error"]

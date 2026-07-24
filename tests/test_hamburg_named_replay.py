from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from torii_sumo.core.candidate_contracts import file_sha256
from torii_sumo.core.digital_twin_mapping import DetectorMapping, write_detector_mapping
from torii_sumo.core.hamburg_named_replay import (
    HamburgNamedReplayError,
    _audit_signal_history_scope,
    _load_binding_manifest,
    _load_detector_binding_manifest,
    _load_signal_observation_manifest,
    _read_sumo_quality,
    _summarize_e1,
    _validate_binding_network,
    _validate_count_scope_manifest,
    _validate_dependency_w1_manifest,
    materialize_hamburg_named_replay_preflight,
)


def test_sumo_quality_gate_blocks_teleports_and_collisions(tmp_path: Path) -> None:
    summary = tmp_path / "summary.xml"
    summary.write_text(
        """<summary>
  <step time="0" teleports="0" collisions="0" loaded="2" inserted="2" running="2" waiting="0" ended="0" arrived="0" halting="0"/>
  <step time="1" teleports="3" collisions="1" loaded="2" inserted="2" running="1" waiting="0" ended="1" arrived="1" halting="0"/>
</summary>\n""",
        encoding="utf-8",
    )

    report = _read_sumo_quality(summary)

    assert report["quality_gate"] == "blocked"
    assert report["teleport_count"] == 3
    assert report["collision_count"] == 1
    assert report["summary_final"]["arrived"] == "1"


def test_replay_requires_signal_binding_for_the_same_network(tmp_path: Path) -> None:
    replay_net = tmp_path / "replay.net.xml"
    bound_net = tmp_path / "bound.net.xml"
    replay_net.write_text("<net id=\"replay\"/>\n", encoding="utf-8")
    bound_net.write_text("<net id=\"bound\"/>\n", encoding="utf-8")
    binding_manifest = tmp_path / "W2.json"
    binding = {
        "source": {
            "candidate_net": {
                "path": bound_net.name,
                "sha256": file_sha256(bound_net),
            }
        }
    }

    with pytest.raises(HamburgNamedReplayError, match="does not match replay network"):
        _validate_binding_network(binding, replay_net, manifest_path=binding_manifest)

    replay_net.write_bytes(bound_net.read_bytes())
    _validate_binding_network(binding, replay_net, manifest_path=binding_manifest)
    bound_net.write_text("<net id=\"mutated\"/>\n", encoding="utf-8")
    with pytest.raises(HamburgNamedReplayError, match="SHA-256 mismatch"):
        _validate_binding_network(binding, replay_net, manifest_path=binding_manifest)


def test_replay_requires_dependencies_from_the_same_w1_manifest(tmp_path: Path) -> None:
    selected_w1 = tmp_path / "W1.json"
    selected_w1.write_text('{"w1":"selected"}\n', encoding="utf-8")
    other_w1 = tmp_path / "other-W1.json"
    other_w1.write_text('{"w1":"other"}\n', encoding="utf-8")
    dependency_manifest = tmp_path / "W2.json"
    dependency_manifest.write_text("{}\n", encoding="utf-8")
    binding = {
        "source": {
            "w1_manifest": {
                "path": str(selected_w1),
                "sha256": file_sha256(selected_w1),
            }
        }
    }

    _validate_dependency_w1_manifest(
        binding,
        manifest_path=dependency_manifest,
        expected_w1_manifest=selected_w1,
        label="signal binding",
    )
    copied_w1 = tmp_path / "copied-W1.json"
    copied_w1.write_bytes(selected_w1.read_bytes())
    binding["source"]["w1_manifest"] = {
        "path": str(copied_w1),
        "sha256": file_sha256(copied_w1),
    }
    with pytest.raises(HamburgNamedReplayError, match="does not match the selected replay input"):
        _validate_dependency_w1_manifest(
            binding,
            manifest_path=dependency_manifest,
            expected_w1_manifest=selected_w1,
            label="signal binding",
        )
    binding["source"]["w1_manifest"] = {
        "path": str(other_w1),
        "sha256": file_sha256(other_w1),
    }
    with pytest.raises(HamburgNamedReplayError, match="does not match the selected replay input"):
        _validate_dependency_w1_manifest(
            binding,
            manifest_path=dependency_manifest,
            expected_w1_manifest=selected_w1,
            label="signal binding",
        )


def test_blocked_preflight_records_exact_upstream_identities_without_running(
    tmp_path: Path,
) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    w1 = tmp_path / "W1.json"
    w1.write_text(
        json.dumps(
            {
                "schema": "torii.hamburg-official-corridor-geometry/v1",
                "status": "review_ready",
                "execution_gate": "pass",
                "network_binding": {
                    "path": str(network),
                    "sha256": file_sha256(network),
                },
            }
        ),
        encoding="utf-8",
    )
    w1_identity = {"path": str(w1), "sha256": file_sha256(w1)}
    signal = tmp_path / "W2.json"
    signal.write_text(
        json.dumps(
            {
                "schema": "torii.hamburg-named-signal-binding/v1",
                "execution_gate": "blocked",
                "source": {
                    "w1_manifest": w1_identity,
                    "candidate_net": {
                        "path": str(network),
                        "sha256": file_sha256(network),
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    stream = tmp_path / "streams.json"
    stream.write_text('{"streams":[]}\n', encoding="utf-8")
    detector = tmp_path / "W3b.json"
    detector.write_text(
        json.dumps(
            {
                "schema": "torii.hamburg-named-detector-binding/v1",
                "execution_gate": "pass",
                "gates": {"sensor_aggregation_semantics": "blocked"},
                "source": {
                    "w1_manifest": w1_identity,
                    "candidate_net": {
                        "path": str(network),
                        "sha256": file_sha256(network),
                    },
                    "count_stream_snapshot": {
                        "path": str(stream),
                        "sha256": file_sha256(stream),
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    counts = tmp_path / "counts.csv"
    counts.write_text("begin,end,total\n", encoding="utf-8")
    count_scope = tmp_path / "W3a.json"
    count_scope.write_text(
        json.dumps(
            {
                "schema": "torii.hamburg-named-corridor-count-scope/v1",
                "execution_gate": "pass",
                "artifacts": {
                    "count_streams_raw": {
                        "path": str(stream),
                        "sha256": file_sha256(stream),
                    },
                    "counts_simulation_15min": {
                        "path": str(counts),
                        "sha256": file_sha256(counts),
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    report = materialize_hamburg_named_replay_preflight(
        w1_manifest_file=w1,
        signal_binding_manifest=signal,
        detector_binding_manifest=detector,
        count_scope_manifest=count_scope,
        count_stream_snapshot=stream,
        canonical_count_file=counts,
        output_dir=tmp_path / "W4",
    )

    assert report["schema"] == "torii.hamburg-named-replay/v2"
    assert report["execution_gate"] == "blocked"
    assert report["replay_executed"] is False
    assert report["simulation"]["status"] == "not_run"
    assert report["source"]["w1_manifest"] == {
        "path": "../W1.json",
        "sha256": w1_identity["sha256"],
    }
    assert report["source"]["signal_binding_manifest"] == {
        "path": "../W2.json",
        "sha256": file_sha256(signal),
    }
    assert report["source"]["detector_binding_manifest"] == {
        "path": "../W3b.json",
        "sha256": file_sha256(detector),
    }
    assert not Path(report["source"]["net"]["path"]).is_absolute()
    assert report["gates"]["route_sampler"] == "not_run"
    assert report["gates"]["sumo_run"] == "not_run"


def test_replay_rejects_non_executable_signal_binding(tmp_path: Path) -> None:
    manifest = tmp_path / "binding.json"
    manifest.write_text(
        '{"schema":"torii.hamburg-named-signal-binding/v1","execution_gate":"blocked"}',
        encoding="utf-8",
    )

    with pytest.raises(HamburgNamedReplayError, match="not execution-ready"):
        _load_binding_manifest(manifest)


def test_replay_consumes_hash_bound_w3b_detector_mapping(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    streams = tmp_path / "streams.json"
    streams.write_text('{"streams":[1]}\n', encoding="utf-8")
    mapping_file = tmp_path / "detector_mapping.csv"
    write_detector_mapping(
        mapping_file,
        [
            DetectorMapping(
                detector_id="detector-1",
                stream_id=1,
                node_id="2394",
                asset_id="asset-1",
                real_direction="Richtung 1",
                lane_use="all",
                longitude=10.0,
                latitude=53.0,
                official_map_lane="",
                official_map_distance_m=None,
                sumo_edge="edge",
                sumo_lane="edge_0",
                lane_position=10.0,
                distance_m=1.0,
                heading_error_deg=None,
                period=900,
                mapping_confidence="high",
                mapping_status="active",
                mapping_reason="fixture",
            )
        ],
    )
    manifest = tmp_path / "detector-binding.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "torii.hamburg-named-detector-binding/v1",
                "execution_gate": "pass",
                "gates": {"sensor_aggregation_semantics": "pass"},
                "source": {
                    "candidate_net": {
                        "path": str(network),
                        "sha256": file_sha256(network),
                    },
                    "count_stream_snapshot": {
                        "path": str(streams),
                        "sha256": file_sha256(streams),
                    },
                },
                "artifacts": {
                    "detector_mapping": {
                        "path": str(mapping_file),
                        "sha256": file_sha256(mapping_file),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    _, mappings = _load_detector_binding_manifest(
        manifest,
        replay_net=network,
        count_stream_snapshot=streams,
        expected_stream_ids={1},
    )

    assert mappings[0].sumo_lane == "edge_0"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["gates"]["sensor_aggregation_semantics"] = "blocked"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HamburgNamedReplayError, match="no approved shared-lane aggregation"):
        _load_detector_binding_manifest(
            manifest,
            replay_net=network,
            count_stream_snapshot=streams,
            expected_stream_ids={1},
        )
    payload["gates"]["sensor_aggregation_semantics"] = "pass"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    mapping_file.write_text("changed\n", encoding="utf-8")
    with pytest.raises(HamburgNamedReplayError, match="detector mapping SHA-256 mismatch"):
        _load_detector_binding_manifest(
            manifest,
            replay_net=network,
            count_stream_snapshot=streams,
            expected_stream_ids={1},
        )


def test_replay_count_values_are_bound_to_w3a(tmp_path: Path) -> None:
    streams = tmp_path / "streams.json"
    streams.write_text('{"streams":[]}\n', encoding="utf-8")
    counts = tmp_path / "counts.csv"
    counts.write_text("stream_id,begin,end,total\n", encoding="utf-8")
    other_counts = tmp_path / "other-counts.csv"
    other_counts.write_text("stream_id,begin,end,total\n1,0,900,1\n", encoding="utf-8")
    manifest = tmp_path / "count-scope.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "torii.hamburg-named-corridor-count-scope/v1",
                "execution_gate": "pass",
                "artifacts": {
                    "count_streams_raw": {
                        "path": str(streams),
                        "sha256": file_sha256(streams),
                    },
                    "counts_simulation_15min": {
                        "path": str(counts),
                        "sha256": file_sha256(counts),
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    _validate_count_scope_manifest(
        manifest,
        count_stream_snapshot=streams,
        canonical_count_file=counts,
    )

    with pytest.raises(HamburgNamedReplayError, match="does not match the selected replay input"):
        _validate_count_scope_manifest(
            manifest,
            count_stream_snapshot=streams,
            canonical_count_file=other_counts,
        )


def test_signal_observations_are_bound_to_binding_and_event_bytes(tmp_path: Path) -> None:
    binding = tmp_path / "binding.json"
    binding.write_text('{"binding":1}\n', encoding="utf-8")
    other_binding = tmp_path / "other-binding.json"
    other_binding.write_text('{"binding":2}\n', encoding="utf-8")
    events = tmp_path / "tls-link-events.csv"
    events.write_text("time,tls_id,link_index,state\n", encoding="utf-8")
    manifest = tmp_path / "observations.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "torii.hamburg-named-signal-observations/v2",
                "execution_gate": "pass",
                "source": {
                    "binding_manifest": {
                        "path": str(binding),
                        "sha256": file_sha256(binding),
                    }
                },
                "artifacts": {"tls_link_events": str(events)},
                "artifact_identities": {
                    "tls_link_events": {
                        "path": str(events),
                        "sha256": file_sha256(events),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = _load_signal_observation_manifest(manifest, binding_manifest=binding)

    assert loaded is not None
    assert loaded["validated_tls_link_events"] == str(events.resolve())
    with pytest.raises(HamburgNamedReplayError, match="does not match the selected replay input"):
        _load_signal_observation_manifest(manifest, binding_manifest=other_binding)
    events.write_text("changed\n", encoding="utf-8")
    with pytest.raises(HamburgNamedReplayError, match="TLS link events SHA-256 mismatch"):
        _load_signal_observation_manifest(manifest, binding_manifest=binding)


def test_sumo_quality_gate_passes_only_clean_summary(tmp_path: Path) -> None:
    summary = tmp_path / "summary.xml"
    summary.write_text(
        "<summary><step time=\"1\" teleports=\"0\" collisions=\"0\"/></summary>\n",
        encoding="utf-8",
    )

    report = _read_sumo_quality(summary)

    assert report["quality_gate"] == "pass"
    assert report["teleport_count"] == 0
    assert report["collision_count"] == 0


def test_e1_summary_exposes_missing_bins() -> None:
    report = _summarize_e1(
        [
            {
                "measurement_status": "matched",
                "expected_total": 10,
                "measured_nVehContrib": 8,
                "diff_nVehContrib_minus_expected": -2,
            },
            {
                "measurement_status": "missing",
                "expected_total": 7,
                "measured_nVehContrib": None,
                "diff_nVehContrib_minus_expected": None,
            },
        ]
    )

    assert report["matched"] == 1
    assert report["missing"] == 1
    assert report["total"] == 2
    assert report["expected"] == 10
    assert report["measured"] == 8


def test_signal_history_scope_blocks_short_official_window() -> None:
    report = _audit_signal_history_scope(
        {"window": {"begin_utc": "2026-07-18T06:00:00Z", "end_utc": "2026-07-18T08:00:00Z"}},
        simulation_begin=0,
        simulation_end=9000,
    )

    assert report["status"] == "review_required"
    assert report["history_window_seconds"] == 7200
    assert report["replay_window_seconds"] == 9000


def test_signal_history_scope_blocks_shifted_utc_window() -> None:
    report = _audit_signal_history_scope(
        {"window": {"begin_utc": "2026-07-18T06:00:00Z", "end_utc": "2026-07-18T08:00:00Z"}},
        counts=[
            SimpleNamespace(
                begin=0,
                end=900,
                source_begin_utc=datetime(2026, 7, 18, 8, tzinfo=timezone.utc),
                source_end_utc=datetime(2026, 7, 18, 8, 15, tzinfo=timezone.utc),
            )
        ],
        simulation_begin=0,
        simulation_end=7200,
    )

    assert report["status"] == "review_required"
    assert report["reason"] == "official signal history does not cover the replay count UTC window"

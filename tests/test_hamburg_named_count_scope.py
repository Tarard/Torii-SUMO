from __future__ import annotations

import json
import csv
from datetime import datetime, timezone
from pathlib import Path

from torii_sumo.core.digital_twin import CountStream
from torii_sumo.core.digital_twin import CanonicalCount
from torii_sumo.core.hamburg_named_count_scope import (
    OfficialSignalNodeReference,
    build_hamburg_count_scope_evidence,
    infer_hamburg_count_directions,
    load_lsa_node_references,
    write_corridor_aggregate_counts,
)


def _stream(stream_id: int, node_id: str, longitude: float, latitude: float, direction: str = "Richtung 1") -> CountStream:
    return CountStream(
        stream_id=stream_id,
        thing_id=stream_id + 100,
        node_id=node_id,
        asset_id=f"Z.{stream_id}",
        direction=direction,
        lane_use="Geradeaus",
        longitude=longitude,
        latitude=latitude,
    )


def test_scope_evidence_keeps_missing_node_and_unknown_direction_explicit() -> None:
    references = {
        "2349": OfficialSignalNodeReference("2349", "west", 9.993227, 53.543321),
        "2394": OfficialSignalNodeReference("2394", "middle", 9.995133, 53.543503),
        "2403": OfficialSignalNodeReference("2403", "east", 9.997839, 53.544095),
    }
    evidence = build_hamburg_count_scope_evidence(
        [
            _stream(1, "2394", 9.995133, 53.543503),
            _stream(2, "2403", 9.997839, 53.544095, direction="unbekannt"),
        ],
        requested_count_node_ids=["2349", "2394", "2403"],
        signal_nodes=references,
    )

    assert evidence["status"] == "partial"
    assert evidence["automatic_promotion_gate"] == "blocked"
    assert evidence["missing_count_node_ids"] == ["2349"]
    assert evidence["unknown_direction_stream_ids"] == [2]
    assert all(row["distance_status"] == "within_declared_scope" for row in evidence["stream_rows"])


def test_direction_inference_uses_clear_same_node_geometry_and_records_provenance() -> None:
    inferred, evidence = infer_hamburg_count_directions(
        [
            _stream(1, "2403", 9.997650, 53.544313, direction="Richtung 1"),
            _stream(2, "2403", 9.997695, 53.544321, direction="unbekannt"),
            _stream(3, "2403", 9.998159, 53.544172, direction="Richtung 2"),
        ]
    )

    assert inferred[1].direction == "Richtung 1"
    assert evidence[0]["status"] == "inferred"
    assert evidence[0]["reference_stream_id"] == 1
    assert evidence[0]["method"] == "nearest_same_node_declared_direction"


def test_lsa_identity_loader_requires_requested_points(tmp_path: Path) -> None:
    path = tmp_path / "lsa.json"
    path.write_text(
        json.dumps(
            {
                "selections": [
                    {
                        "selected_node": {
                            "node_id": "2394",
                            "official_name": "Am Sandtorkai/Am Sandtorpark",
                            "point_geometry": {"coordinates": [9.995, 53.5435]},
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    references = load_lsa_node_references(path, expected_node_ids=["2394"])

    assert references["2394"].official_name == "Am Sandtorkai/Am Sandtorpark"


def test_corridor_aggregate_writer_keeps_unknown_direction_as_own_group(tmp_path: Path) -> None:
    rows = [
        CanonicalCount(
            detector_id="d1",
            stream_id=1,
            node_id="2403",
            asset_id="Z.1",
            direction="Richtung 1",
            lane_use="",
            longitude=9.998,
            latitude=53.544,
            source_begin_utc=datetime(2026, 7, 18, 14, tzinfo=timezone.utc),
            source_end_utc=datetime(2026, 7, 18, 14, 15, tzinfo=timezone.utc),
            begin=0,
            end=900,
            count=4,
            source_observation_count=3,
            expected_source_observation_count=3,
            quality_status="complete",
        ),
        CanonicalCount(
            detector_id="d2",
            stream_id=2,
            node_id="2403",
            asset_id="Z.10",
            direction="unbekannt",
            lane_use="",
            longitude=9.998,
            latitude=53.544,
            source_begin_utc=datetime(2026, 7, 18, 14, tzinfo=timezone.utc),
            source_end_utc=datetime(2026, 7, 18, 14, 15, tzinfo=timezone.utc),
            begin=0,
            end=900,
            count=2,
            source_observation_count=3,
            expected_source_observation_count=3,
            quality_status="complete",
        ),
    ]
    path = tmp_path / "aggregate.csv"
    write_corridor_aggregate_counts(path, rows, scope_id="scope")

    with path.open(encoding="utf-8", newline="") as handle:
        values = list(csv.DictReader(handle))
    assert {(row["direction"], row["expected_total"]) for row in values} == {
        ("Richtung 1", "4"),
        ("unbekannt", "2"),
    }

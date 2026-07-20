from __future__ import annotations

import csv
import json
from pathlib import Path

from pyproj import Transformer

from torii_sumo.core.hamburg_named_detector_bindings import (
    materialize_hamburg_named_detector_bindings,
)


def _write_network(path: Path, *, parallel: bool) -> tuple[float, float]:
    transformer = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
    x, y = 565950.0, 5933205.0
    if parallel:
        lanes = (
            f'<lane id="road_0" index="0" speed="13.9" length="100" allow="passenger" shape="{x},{y - 2.5} {x + 100},{y - 2.5}"/>\n'
            f'<lane id="road_1" index="1" speed="13.9" length="100" allow="passenger" shape="{x},{y + 2.5} {x + 100},{y + 2.5}"/>'
        )
    else:
        lanes = f'<lane id="road_0" index="0" speed="13.9" length="100" allow="passenger" shape="{x},{y} {x + 100},{y}"/>'
    path.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<net version="1.27">
  <location netOffset="0,0" convBoundary="{x},{y - 10},{x + 100},{y + 10}" origBoundary="{x},{y - 10},{x + 100},{y + 10}" projParameter="!"/>
  <edge id="road" from="a" to="b" priority="1" numLanes="{2 if parallel else 1}">
    {lanes}
  </edge>
  <junction id="a" type="priority" x="{x}" y="{y}" incLanes="" intLanes=""/>
  <junction id="b" type="priority" x="{x + 100}" y="{y}" incLanes="road_0" intLanes=""/>
</net>
''',
        encoding="utf-8",
    )
    return transformer.transform(x, y)


def _write_stream_snapshot(path: Path, longitude: float, latitude: float) -> None:
    path.write_text(
        json.dumps(
            {
                "pages_by_node": {
                    "2394": [
                        {
                            "value": [
                                {
                                    "@iot.id": 28495,
                                    "properties": {
                                        "knotenName": "2394",
                                        "assetID": "Z.1",
                                        "fahrspur": "",
                                    },
                                    "Thing": {
                                        "@iot.id": 1,
                                        "properties": {
                                            "richtung": "Richtung 1",
                                            "operationStart": "2026-02-28T23:00:00Z",
                                        },
                                        "Locations": [
                                            {
                                                "location": {
                                                    "type": "Feature",
                                                    "geometry": {
                                                        "type": "Point",
                                                        "coordinates": [longitude, latitude],
                                                    },
                                                }
                                            }
                                        ],
                                    },
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )


def test_projection_fallback_promotes_unique_geometry_binding_and_withholds_no_sensor(tmp_path: Path) -> None:
    net = tmp_path / "candidate.net.xml"
    lon, lat = _write_network(net, parallel=False)
    streams = tmp_path / "streams.raw.json"
    _write_stream_snapshot(streams, lon, lat)

    report = materialize_hamburg_named_detector_bindings(
        net_file=net,
        count_stream_file=streams,
        output_dir=tmp_path / "bindings",
    )

    assert report["automatic_promotion_gate"] == "pass"
    assert report["gates"]["coordinate_projection"] == "pass"
    assert report["artifacts"]["e1_e2_additional"]["status"] == "withheld_pending_complete_lane_mapping"
    with (tmp_path / "bindings" / "detector_mapping.csv").open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["mapping_status"] == "active"
    assert row["sumo_lane"] == "road_0"


def test_parallel_lane_tie_is_rejected_without_manual_override(tmp_path: Path) -> None:
    net = tmp_path / "candidate.net.xml"
    lon, lat = _write_network(net, parallel=True)
    streams = tmp_path / "streams.raw.json"
    _write_stream_snapshot(streams, lon, lat)

    report = materialize_hamburg_named_detector_bindings(
        net_file=net,
        count_stream_file=streams,
        output_dir=tmp_path / "bindings",
    )

    assert report["automatic_promotion_gate"] == "blocked"
    assert report["incomplete_stream_ids"] == [28495]
    candidates = json.loads((tmp_path / "bindings" / "detector_lane_candidates.json").read_text(encoding="utf-8"))
    assert candidates["rows"][0]["candidate_status"] == "needs_review"
    assert "ambiguous" in candidates["rows"][0]["reason"]

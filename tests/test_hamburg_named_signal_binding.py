from __future__ import annotations

import json
from pathlib import Path

from torii_sumo.core.hamburg_named_signal_binding import materialize_hamburg_named_signal_binding


def _write_inputs(tmp_path: Path, *, mismatch: bool = False) -> tuple[Path, dict[str, Path], list[Path]]:
    net = tmp_path / "candidate.net.xml"
    net.write_text(
        """<net>
  <tlLogic id="hh-map-2349" type="static" programID="structural-all-red" offset="0"/>
  <tlLogic id="hh-map-2394" type="static" programID="structural-all-red" offset="0"/>
  <connection from="a" to="b" fromLane="0" toLane="0" tl="hh-map-2349" linkIndex="0"/>
  <connection from="c" to="d" fromLane="1" toLane="0" tl="hh-map-2394" linkIndex="2"/>
</net>\n""",
        encoding="utf-8",
    )
    manifests: dict[str, Path] = {}
    streams: list[dict[str, object]] = []
    for node_id, connection_id, ingress, egress, link_index, group in (
        ("2349", "2", "2", "11", 0, "K1"),
        ("2394", "1", "10", "9", 2, "K6"),
    ):
        manifest = tmp_path / f"{node_id}.manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "node_id": node_id,
                    "controller_id": f"hh-map-{node_id}",
                    "movements": [
                        {
                            "connection_id": connection_id,
                            "ingress_lane_id": "wrong" if mismatch and node_id == "2349" else ingress,
                            "egress_lane_id": egress,
                            "link_index": link_index,
                            "primary_motor_groups": [group],
                            "secondary_motor_groups": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        manifests[node_id] = manifest
        streams.append(
            {
                "stream_id": 100 + int(node_id),
                "node_id": node_id,
                "connection_id": connection_id,
                "ingress_lane_id": ingress,
                "egress_lane_id": egress,
                "signal_group": group,
                "layer_name": "primary_signal",
                "lane_type": "KFZ",
            }
        )
    stream_file = tmp_path / "streams.json"
    stream_file.write_text(json.dumps({"schema": "test", "streams": streams}), encoding="utf-8")
    return net, manifests, [stream_file]


def test_official_streams_bind_to_controller_link_indices(tmp_path: Path) -> None:
    net, manifests, stream_files = _write_inputs(tmp_path)
    report = materialize_hamburg_named_signal_binding(
        net_file=net,
        intersection_manifests=manifests,
        signal_stream_files=stream_files,
        output_dir=tmp_path / "out",
    )

    assert report["status"] == "partial"
    assert report["execution_gate"] == "pass"
    assert report["automatic_promotion_gate"] == "blocked"
    assert len(json.loads(Path(report["binding_artifact"]["path"]).read_text(encoding="utf-8"))["bindings"]) == 2
    assert report["node_reports"]["2349"]["bound_count"] == 1


def test_mismatched_lane_identity_blocks_binding(tmp_path: Path) -> None:
    net, manifests, stream_files = _write_inputs(tmp_path, mismatch=True)
    report = materialize_hamburg_named_signal_binding(
        net_file=net,
        intersection_manifests=manifests,
        signal_stream_files=stream_files,
        output_dir=tmp_path / "out",
    )

    assert report["status"] == "blocked"
    assert report["execution_gate"] == "blocked"
    assert any(error["code"] == "stream_movement_mismatch" for error in report["errors"])


def test_missing_2403_is_explicit_non_promoting_partial(tmp_path: Path) -> None:
    net, manifests, stream_files = _write_inputs(tmp_path)
    report = materialize_hamburg_named_signal_binding(
        net_file=net,
        intersection_manifests=manifests,
        signal_stream_files=stream_files,
        output_dir=tmp_path / "out",
        required_node_ids=("2349", "2394", "2403"),
    )

    assert report["missing_official_signal_node_ids"] == ["2403"]
    assert report["automatic_promotion_gate"] == "blocked"
    assert report["gates"]["2403_official_signal_asset"] == "blocked"

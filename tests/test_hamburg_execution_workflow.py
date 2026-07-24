from __future__ import annotations

import json
from pathlib import Path

import pytest

from torii_sumo.core.candidate_contracts import file_sha256
from torii_sumo.core.complete_way_audit import audit_complete_osm_way_filter
from torii_sumo.core.hamburg_execution_workflow import (
    HAMBURG_EXECUTION_CONFIG_SCHEMA,
    HAMBURG_EXECUTION_WORKFLOW_SCHEMA,
    HamburgExecutionWorkflowError,
    _is_complete_way_overpass_query,
    materialize_hamburg_execution_plan,
    materialize_hamburg_execution_plan_from_config,
    materialize_hamburg_w1_topology_handoff,
)


_STAGE_SCHEMAS = {
    "W0": "torii.hamburg-named-corridor-scope/v1",
    "W1": "torii.hamburg-official-corridor-geometry/v1",
    "W2": "torii.hamburg-named-signal-binding/v1",
    "W3a": "torii.hamburg-named-corridor-count-scope/v1",
    "W3b": "torii.hamburg-named-detector-binding/v1",
    "W4": "torii.hamburg-named-replay/v2",
}


def test_complete_way_query_rejects_historical_or_inset_scope(
    tmp_path: Path,
) -> None:
    bbox = [
        9.980106927466423,
        53.540533691913986,
        10.003689463043568,
        53.54865291573397,
    ]
    valid = """\
[out:xml][timeout:300];
(
  way["highway"](53.5405,9.98011,53.5487,10.0037);
  relation["type"="restriction"](53.5405,9.98011,53.5487,10.0037);
);
(._;>;);
out body;
"""
    query = tmp_path / "query.ql"
    query.write_text(valid, encoding="utf-8")
    assert _is_complete_way_overpass_query(query, expected_bbox=bbox)

    query.write_text(
        valid.replace(
            "[out:xml][timeout:300]",
            '[out:xml][timeout:300][date:"2010-01-01T00:00:00Z"]',
        ),
        encoding="utf-8",
    )
    assert not _is_complete_way_overpass_query(query, expected_bbox=bbox)

    query.write_text(
        valid.replace("9.98011", "9.98021"),
        encoding="utf-8",
    )
    assert not _is_complete_way_overpass_query(query, expected_bbox=bbox)


def _write_manifest(
    path: Path,
    stage_id: str,
    *,
    status: str = "pass",
    gate: str = "pass",
    execution_gate: str | None = None,
    network_file: Path | None = None,
) -> None:
    payload: dict[str, object] = {
        "schema": _STAGE_SCHEMAS[stage_id],
        "status": status,
        "automatic_promotion_gate": gate,
    }
    if execution_gate is not None:
        payload["execution_gate"] = execution_gate
    count_streams = path.parent / "count_streams.raw.json"
    simulation_counts = path.parent / "counts.simulation.15min.csv"
    detector_mapping = path.parent / "detector_mapping.csv"
    if stage_id == "W3a":
        if not count_streams.exists():
            count_streams.write_text('{"streams":[]}\n', encoding="utf-8")
        if not simulation_counts.exists():
            simulation_counts.write_text("stream_id,begin,end,total\n", encoding="utf-8")
        payload["artifacts"] = {
            "count_streams_raw": {
                "path": str(count_streams.resolve()),
                "sha256": file_sha256(count_streams),
            },
            "counts_simulation_15min": {
                "path": str(simulation_counts.resolve()),
                "sha256": file_sha256(simulation_counts),
            },
        }
    elif stage_id == "W3b":
        if not detector_mapping.exists():
            detector_mapping.write_text("stream_id,sumo_lane\n", encoding="utf-8")
        payload["gates"] = {"sensor_aggregation_semantics": "pass"}
        payload["artifacts"] = {
            "detector_mapping": {
                "path": str(detector_mapping.resolve()),
                "sha256": file_sha256(detector_mapping),
            }
        }
    if stage_id in {"W1", "W2", "W3b", "W4"}:
        network = network_file or path.parent / "candidate.net.xml"
        if not network.exists():
            network.write_text("<net/>\n", encoding="utf-8")
        binding = {"path": str(network.resolve()), "sha256": file_sha256(network)}
        if stage_id == "W1":
            payload["network"] = binding
        elif stage_id in {"W2", "W3b"}:
            source = {"candidate_net": binding}
            if stage_id == "W3b" and count_streams.is_file():
                source["count_stream_snapshot"] = {
                    "path": str(count_streams.resolve()),
                    "sha256": file_sha256(count_streams),
                }
            payload["source"] = source
        else:
            source = {"net": binding}
            if count_streams.is_file():
                source["count_stream_snapshot"] = {
                    "path": str(count_streams.resolve()),
                    "sha256": file_sha256(count_streams),
                }
            if simulation_counts.is_file():
                source["canonical_count_file"] = {
                    "path": str(simulation_counts.resolve()),
                    "sha256": file_sha256(simulation_counts),
                }
            for name, dependency in (
                ("signal_binding_manifest", "W2"),
                ("detector_binding_manifest", "W3b"),
                ("count_scope_manifest", "W3a"),
            ):
                dependency_path = path.with_name(f"{dependency}.json")
                if dependency_path.is_file():
                    source[name] = {
                        "path": str(dependency_path.resolve()),
                        "sha256": file_sha256(dependency_path),
                    }
        if stage_id != "W1":
            w1_manifest = path.with_name("W1.json")
            if w1_manifest.is_file():
                source["w1_manifest"] = {
                    "path": str(w1_manifest.resolve()),
                    "sha256": file_sha256(w1_manifest),
                }
            payload["source"] = source
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_w1_topology_handoff_is_hash_bound_and_non_promoting(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.net.xml"
    candidate.write_text("<net/>", encoding="utf-8")
    candidate_hash = file_sha256(candidate)
    source = tmp_path / "source.net.xml"
    source.write_text("<net/>", encoding="utf-8")
    source_osm = tmp_path / "source.osm.xml"
    filtered_osm = tmp_path / "filtered.osm.xml"
    complete_way_osm = """\
<osm version="0.6">
  <node id="1" lat="53.545" lon="9.99"/>
  <node id="2" lat="53.545" lon="10.004"/>
  <way id="10">
    <nd ref="1"/>
    <nd ref="2"/>
    <tag k="highway" v="primary"/>
    <tag k="name" v="boundary approach"/>
  </way>
</osm>
"""
    source_osm.write_text(complete_way_osm, encoding="utf-8")
    filtered_osm.write_text(complete_way_osm, encoding="utf-8")

    def write(name: str, payload: dict[str, object]) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    topology = write(
        "topology.json",
        {
            "schema": "torii.junction-aggregation-preservation/v1",
            "status": "pass",
            "source_net_file": source.name,
            "source_sha256": file_sha256(source),
            "variant_net_file": candidate.name,
            "variant_sha256": candidate_hash,
            "unexpected_removed_normal_edge_count": 0,
            "lost_shared_connection_count": 0,
            "new_dangling_shared_normal_edge_count": 0,
            "boundary_movement_preservation": {
                "status": "pass",
                "lost_boundary_movement_count": 0,
                "added_boundary_movement_count": 0,
                "groups": [
                    {
                        "variant_boundary_movement_count": 2,
                        "variant_boundary_movements": ["in|0|out|0", "in|1|out|1"],
                    }
                ],
            },
        },
    )
    scope_ledger = write(
        "scope-ledger.json",
        {
            "schema": "torii.scope-edge-preservation/v1",
            "status": "pass",
            "full_way_baseline": {
                "path": candidate.name,
                "sha256": candidate_hash,
                "external_edge_count": 2,
            },
            "final_candidate": {
                "path": candidate.name,
                "sha256": candidate_hash,
                "external_edge_count": 2,
            },
            "classification_counts": {
                "preserved": 2,
                "internalized": 0,
                "excluded_with_reason": 0,
                "unaccounted": 0,
            },
            "unaccounted_edge_count": 0,
            "empty_exclusion_reason_count": 0,
        },
    )
    turnaround = write(
        "turnaround.json",
        {
            "schema_id": "torii.external-micro-junction-audit/v2",
            "status": "pass",
            "automatic_promotion_gate": "pass",
            "source_net_file": candidate.name,
            "source_net_sha256": candidate_hash,
            "scope": {"mode": "whole_network", "junction_ids": []},
            "dir_t_turnaround_count": 0,
            "dir_t_turnarounds": [],
            "unsupported_turnaround_count": 0,
            "unused_turnaround_authority_count": 0,
        },
    )
    cad = tmp_path / "hamburg-road-cad.pdf"
    aerial = tmp_path / "aerial-review.png"
    cad.write_text("official CAD evidence", encoding="utf-8")
    aerial.write_text("aerial evidence", encoding="utf-8")
    movement_authority = write(
        "movement-authority.json",
        {
            "schema": "torii.hamburg-movement-authority/v1",
            "status": "review_required",
            "authority_id": "hamburg-cad-aerial-review-v1",
            "generated_from_candidate": False,
            "source_evidence": [
                {
                    "evidence_id": "hamburg-cad",
                    "path": str(cad.resolve()),
                    "sha256": file_sha256(cad),
                },
                {
                    "evidence_id": "aerial-review",
                    "path": str(aerial.resolve()),
                    "sha256": file_sha256(aerial),
                },
            ],
            "movements": [
                {
                    "movement_key": "in|0|out|0",
                    "evidence_ids": ["hamburg-cad"],
                },
                {
                    "movement_key": "in|1|out|1",
                    "evidence_ids": ["hamburg-cad", "aerial-review"],
                },
            ],
        },
    )
    surface = write(
        "surface.json",
        {
            "schema": "torii.sumo-surface-overlap-audit/v1",
            "audit_engine": "torii.bevel-strip-and-junction-polygon-area/v2",
            "status": "pass",
            "source_net_file": candidate.name,
            "source_sha256": candidate_hash,
            "source_network_mutation": False,
            "geometry_error_count": 0,
            "junction_junction_overlap_count": 0,
            "external_lane_non_owner_junction_overlap_count": 0,
        },
    )
    connection = write(
        "connection.json",
        {
            "schema": "torii.connection_mode_regression_manifest.v1",
            "status": "pass",
            "gate_status": "pass",
            "automatic_promotion_gate": "pass",
            "candidate_net_file": candidate.name,
            "candidate_sha256": candidate_hash,
            "source_network_mutation": False,
        },
    )
    load = write(
        "load.json",
        {
            "schema": "torii.sumo-load-audit/v1",
            "status": "pass",
            "source_net_file": candidate.name,
            "source_sha256": candidate_hash,
            "source_network_mutation": False,
        },
    )
    route = tmp_path / "smoke.rou.xml"
    summary = tmp_path / "summary.xml"
    tripinfo = tmp_path / "tripinfo.xml"
    for path in (route, summary, tripinfo):
        path.write_text("evidence", encoding="utf-8")
    smoke = write(
        "smoke.json",
        {
            "schema": "torii.hamburg-2403-movement-smoke/v1",
            "status": "pass",
            "automatic_promotion_gate": "blocked",
            "authority_review_status": "review_required",
            "candidate_net_file": str(candidate.resolve()),
            "candidate_sha256": candidate_hash,
            "inputs": {
                "route": {"path": str(route), "sha256": file_sha256(route)},
                "movement_authority": {
                    "path": str(movement_authority),
                    "sha256": file_sha256(movement_authority),
                },
            },
            "outputs": {
                "summary": {"path": str(summary), "sha256": file_sha256(summary)},
                "tripinfo": {"path": str(tripinfo), "sha256": file_sha256(tripinfo)},
            },
            "vehicle_count": 2,
            "movement_count": 2,
            "movement_keys": ["in|0|out|0", "in|1|out|1"],
            "movement_keys_unique": True,
            "loaded": 2,
            "inserted": 2,
            "ended": 2,
            "running": 0,
            "waiting": 0,
            "teleports": 0,
            "collisions": 0,
            "inspection": {
                "status": "pass",
                "summary": {
                    "loaded": 2,
                    "inserted": 2,
                    "arrived": 2,
                    "running": 0,
                    "waiting": 0,
                    "teleports": 0,
                    "collisions": 0,
                },
                "tripinfo": {"trip_count": 2},
            },
        },
    )
    review_files = []
    for junction_id in ("a", "b"):
        review_files.append(
            write(
                f"review-{junction_id}.json",
                {
                    "schema": "torii.netedit-background-review.direct/v1",
                    "status": "review_material_ready",
                    "automatic_promotion_gate": "blocked",
                    "candidate_file": candidate.name,
                    "candidate_sha256_before": candidate_hash,
                    "candidate_sha256_after": candidate_hash,
                    "candidate_unchanged": True,
                    "target_junction": {"id": junction_id},
                    "mode_images_distinct": True,
                    "global_keyboard_or_mouse_input_used": False,
                    "foreground_context_restored": True,
                },
            )
        )

    acquisition_bbox = [
        9.980106927466423,
        53.540533691913986,
        10.003689463043568,
        53.54865291573397,
    ]
    selection_rule = (
        "retain each complete OSM way intersecting the buffered aerial/CAD scope; "
        "never truncate a selected way at the bbox"
    )
    provenance_payload = {
        "schema": "torii.osm-sumo-build-provenance/v1",
        "status": "pass",
        "build_scope": {
            "bbox": ",".join(map(str, acquisition_bbox)),
            "clip_source_ways_to_bbox": False,
            "allowed_way_ids_count": None,
            "forced_way_ids_count": None,
            "road_classes": ["primary"],
        },
        "source_osm_snapshot": {
            "path": str(source_osm),
            "sha256": file_sha256(source_osm),
        },
        "netconvert_input_osm_snapshot": {
            "path": str(filtered_osm),
            "sha256": file_sha256(filtered_osm),
        },
        "sumo_net_snapshot": {
            "path": str(candidate),
            "sha256": candidate_hash,
        },
        "netconvert": {
            "command": [
                "netconvert",
                "--osm-files",
                str(filtered_osm),
                "--output-file",
                str(candidate),
                "--no-turnarounds",
                "--no-turnarounds.tls",
                "--no-turnarounds.geometry",
                "--no-turnarounds.fringe",
            ]
        },
    }
    build_provenance = write("osm-build-provenance.json", provenance_payload)
    source_build_provenance = write(
        "source-osm-build-provenance.json",
        json.loads(json.dumps(provenance_payload)),
    )
    overpass_query = tmp_path / "complete-ways.overpass.ql"
    overpass_query.write_text(
        """\
[out:xml][timeout:300];
(
  way["highway"](53.5405,9.98011,53.5487,10.0037);
  relation["type"="restriction"](53.5405,9.98011,53.5487,10.0037);
);
(._;>;);
out body;
""",
        encoding="utf-8",
    )
    source_command_record = tmp_path / "source-build-commands.txt"
    source_command_record.write_text(
        "\n".join(
            [
                f"bbox={','.join(map(str, acquisition_bbox))}",
                f"source_osm_sha256={file_sha256(source_osm)}",
                "allowed_highways=primary",
                "allowed_way_ids_count=not_applied",
                "clip_source_ways_to_bbox=False",
                "overpass_strategy=tiled-retry-merge",
                "overpass_tile_count=1",
                "overpass_retry_count=0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    provenance_payload["source_acquisition"] = {
        "mode": "provided_snapshot",
        "query": {
            "path": overpass_query.name,
            "sha256": file_sha256(overpass_query),
        },
        "response_snapshot": {
            "path": source_osm.name,
            "sha256": file_sha256(source_osm),
        },
        "overpass": None,
    }
    build_provenance.write_text(
        json.dumps(provenance_payload),
        encoding="utf-8",
    )
    source_provenance_payload = json.loads(json.dumps(provenance_payload))
    source_provenance_payload["source_acquisition"] = {
        "mode": "overpass_download",
        "query": {
            "path": overpass_query.name,
            "sha256": file_sha256(overpass_query),
        },
        "response_snapshot": {
            "path": source_osm.name,
            "sha256": file_sha256(source_osm),
        },
        "overpass": {
            "strategy": "tiled-retry-merge",
            "tile_count": 1,
            "retry_count": 0,
        },
    }
    source_build_provenance.write_text(
        json.dumps(source_provenance_payload),
        encoding="utf-8",
    )
    repository_root = Path(__file__).resolve().parents[1]
    aerial_scope = (
        repository_root
        / "docs/assets/hamburg-digital-twin/official-aerial-2024.png"
    )
    cad_scope = (
        repository_root
        / "docs/assets/hamburg-digital-twin/official-construction-plan-2022.png"
    )
    complete_way_audit = audit_complete_osm_way_filter(
        source_osm_file=source_osm,
        filtered_osm_file=filtered_osm,
        acquisition_bbox=acquisition_bbox,
        allowed_highways=["primary"],
    )
    assert complete_way_audit["ways_with_nodes_outside_bbox_count"] == 1
    complete_way_acquisition = write(
        "complete-way-acquisition.json",
        {
            "schema": "torii.hamburg-complete-way-acquisition/v1",
            "status": "pass",
            "authority_review_status": "review_required",
            "acquisition_mode": "overpass_download",
            "acquisition_bbox": acquisition_bbox,
            "selection_rule": selection_rule,
            "clip_source_ways_to_bbox": False,
            "allowed_way_ids_count": None,
            "forced_way_ids_count": None,
            "allowed_highways": ["primary"],
            "scope_authority_evidence": [
                {
                    "evidence_id": "hamburg_2024_aerial",
                    "path": str(aerial_scope),
                    "sha256": file_sha256(aerial_scope),
                },
                {
                    "evidence_id": "hamburg_2022_road_cad",
                    "path": str(cad_scope),
                    "sha256": file_sha256(cad_scope),
                },
            ],
            "overpass_query": {
                "path": str(overpass_query),
                "sha256": file_sha256(overpass_query),
            },
            "source_build_provenance": {
                "path": str(source_build_provenance),
                "sha256": file_sha256(source_build_provenance),
            },
            "source_command_record": {
                "path": source_command_record.name,
                "sha256": file_sha256(source_command_record),
            },
            "source_osm_snapshot": {
                "path": str(source_osm),
                "sha256": file_sha256(source_osm),
            },
            "filtered_osm_snapshot": {
                "path": str(filtered_osm),
                "sha256": file_sha256(filtered_osm),
            },
            "complete_way_filter_audit": complete_way_audit,
        },
    )
    build_spec_payload = {
        "schema": "torii.hamburg-canonical-w1-build/v1",
        "status": "frozen",
        "scope_policy": {
            "authority": [
                "Hamburg 2024 aerial imagery",
                "Hamburg 2022 road CAD",
            ],
            "osm_role": "continuous road geometry and base topology",
            "acquisition_bbox": acquisition_bbox,
            "clip_source_ways_to_bbox": False,
            "selection_rule": selection_rule,
        },
        "inputs": {
            "source_osm_snapshot": {
                "path": str(source_osm),
                "sha256": file_sha256(source_osm),
            },
            "filtered_complete_ways": {
                "path": str(filtered_osm),
                "sha256": file_sha256(filtered_osm),
            },
            "baseline_network": {
                "path": str(candidate),
                "sha256": candidate_hash,
            },
            "build_provenance": {
                "path": str(build_provenance),
                "sha256": file_sha256(build_provenance),
            },
            "complete_way_acquisition": {
                "path": str(complete_way_acquisition),
                "sha256": file_sha256(complete_way_acquisition),
            },
        },
        "materialization": [
            {
                "command": [
                    "netconvert",
                    "--output-file",
                    str(candidate),
                    "--no-turnarounds",
                    "--no-turnarounds.tls",
                    "--no-turnarounds.geometry",
                    "--no-turnarounds.fringe",
                ],
                "output_sha256": candidate_hash,
            }
        ],
        "output": {
            "path": str(candidate),
            "sha256": candidate_hash,
        },
    }
    build_spec = write("canonical-build-spec.json", build_spec_payload)

    with pytest.raises(TypeError, match="build_spec_file"):
        materialize_hamburg_w1_topology_handoff(
            output_dir=tmp_path / "missing-build-spec",
            candidate_net_file=candidate,
            topology_audit_file=topology,
            scope_ledger_file=scope_ledger,
            turnaround_audit_file=turnaround,
            movement_authority_file=movement_authority,
            surface_comparison_file=surface,
            connection_mode_manifest_file=connection,
            sumo_load_report_file=load,
            movement_smoke_file=smoke,
            netedit_review_files=review_files,
            expected_review_junction_ids=("a", "b"),
        )

    for field, bad_value in (
        ("authority", ["Hamburg 2024 aerial imagery"]),
        ("osm_role", "geometry only"),
        ("acquisition_bbox", [9.98, 53.54, 10.0, 53.55]),
        ("clip_source_ways_to_bbox", True),
        ("selection_rule", "clip selected ways at the bbox"),
    ):
        bad_spec_payload = json.loads(json.dumps(build_spec_payload))
        bad_spec_payload["scope_policy"][field] = bad_value
        bad_spec = write(f"bad-scope-{field}.json", bad_spec_payload)
        with pytest.raises(
            HamburgExecutionWorkflowError,
            match=f"scope policy {field} mismatch",
        ):
            materialize_hamburg_w1_topology_handoff(
                output_dir=tmp_path / f"bad-scope-{field}",
                candidate_net_file=candidate,
                build_spec_file=bad_spec,
                topology_audit_file=topology,
                scope_ledger_file=scope_ledger,
                turnaround_audit_file=turnaround,
                movement_authority_file=movement_authority,
                surface_comparison_file=surface,
                connection_mode_manifest_file=connection,
                sumo_load_report_file=load,
                movement_smoke_file=smoke,
                netedit_review_files=review_files,
                expected_review_junction_ids=("a", "b"),
            )

    base_command = build_spec_payload["materialization"][0]["command"]
    for name, command, message in (
        (
            "missing-turnaround-flag",
            [item for item in base_command if item != "--no-turnarounds.fringe"],
            "missing no-turnaround flags",
        ),
        (
            "bbox-crop",
            [*base_command, "--bbox", "9.98,53.54,10.00,53.55"],
            "uses edge-cropping options",
        ),
        (
            "keep-edge-crop",
            [*base_command, "--keep-edges.input-file", "scope.txt"],
            "uses edge-cropping options",
        ),
    ):
        bad_spec_payload = json.loads(json.dumps(build_spec_payload))
        bad_spec_payload["materialization"][0]["command"] = command
        bad_spec = write(f"{name}.json", bad_spec_payload)
        with pytest.raises(HamburgExecutionWorkflowError, match=message):
            materialize_hamburg_w1_topology_handoff(
                output_dir=tmp_path / name,
                candidate_net_file=candidate,
                build_spec_file=bad_spec,
                topology_audit_file=topology,
                scope_ledger_file=scope_ledger,
                turnaround_audit_file=turnaround,
                movement_authority_file=movement_authority,
                surface_comparison_file=surface,
                connection_mode_manifest_file=connection,
                sumo_load_report_file=load,
                movement_smoke_file=smoke,
                netedit_review_files=review_files,
                expected_review_junction_ids=("a", "b"),
            )

    for name, field, value in (
        ("provenance-clipped", "clip_source_ways_to_bbox", True),
        ("provenance-keep-list", "allowed_way_ids_count", 67),
        ("provenance-forced-list", "forced_way_ids_count", 5),
    ):
        bad_provenance_payload = json.loads(json.dumps(provenance_payload))
        bad_provenance_payload["build_scope"][field] = value
        bad_provenance = write(f"{name}.provenance.json", bad_provenance_payload)
        bad_spec_payload = json.loads(json.dumps(build_spec_payload))
        bad_spec_payload["inputs"]["build_provenance"] = {
            "path": str(bad_provenance),
            "sha256": file_sha256(bad_provenance),
        }
        bad_spec = write(f"{name}.json", bad_spec_payload)
        with pytest.raises(
            HamburgExecutionWorkflowError,
            match="OSM build provenance used a cropped or different scope",
        ):
            materialize_hamburg_w1_topology_handoff(
                output_dir=tmp_path / name,
                candidate_net_file=candidate,
                build_spec_file=bad_spec,
                topology_audit_file=topology,
                scope_ledger_file=scope_ledger,
                turnaround_audit_file=turnaround,
                movement_authority_file=movement_authority,
                surface_comparison_file=surface,
                connection_mode_manifest_file=connection,
                sumo_load_report_file=load,
                movement_smoke_file=smoke,
                netedit_review_files=review_files,
                expected_review_junction_ids=("a", "b"),
            )

    provided_source_payload = json.loads(json.dumps(source_provenance_payload))
    provided_source_payload["source_acquisition"] = {
        **provided_source_payload["source_acquisition"],
        "mode": "provided_snapshot",
        "overpass": None,
    }
    provided_source_provenance = write(
        "source-provenance-provided-snapshot.json",
        provided_source_payload,
    )
    provided_acquisition_payload = json.loads(
        complete_way_acquisition.read_text(encoding="utf-8")
    )
    provided_acquisition_payload["source_build_provenance"] = {
        "path": str(provided_source_provenance),
        "sha256": file_sha256(provided_source_provenance),
    }
    provided_acquisition = write(
        "complete-way-acquisition-provided-snapshot.json",
        provided_acquisition_payload,
    )
    provided_spec_payload = json.loads(json.dumps(build_spec_payload))
    provided_spec_payload["inputs"]["complete_way_acquisition"] = {
        "path": str(provided_acquisition),
        "sha256": file_sha256(provided_acquisition),
    }
    provided_spec = write(
        "canonical-build-spec-provided-snapshot.json",
        provided_spec_payload,
    )
    with pytest.raises(
        HamburgExecutionWorkflowError,
        match="source acquisition is not a bound Overpass download",
    ):
        materialize_hamburg_w1_topology_handoff(
            output_dir=tmp_path / "provided-source-snapshot",
            candidate_net_file=candidate,
            build_spec_file=provided_spec,
            topology_audit_file=topology,
            scope_ledger_file=scope_ledger,
            turnaround_audit_file=turnaround,
            movement_authority_file=movement_authority,
            surface_comparison_file=surface,
            connection_mode_manifest_file=connection,
            sumo_load_report_file=load,
            movement_smoke_file=smoke,
            netedit_review_files=review_files,
            expected_review_junction_ids=("a", "b"),
        )

    wrong_command_provenance_payload = json.loads(json.dumps(provenance_payload))
    osm_index = wrong_command_provenance_payload["netconvert"]["command"].index(
        "--osm-files"
    )
    wrong_command_provenance_payload["netconvert"]["command"][osm_index + 1] = str(
        source
    )
    wrong_command_provenance = write(
        "provenance-wrong-command.json",
        wrong_command_provenance_payload,
    )
    wrong_command_spec_payload = json.loads(json.dumps(build_spec_payload))
    wrong_command_spec_payload["inputs"]["build_provenance"] = {
        "path": str(wrong_command_provenance),
        "sha256": file_sha256(wrong_command_provenance),
    }
    wrong_command_spec = write(
        "provenance-wrong-command-spec.json",
        wrong_command_spec_payload,
    )
    with pytest.raises(
        HamburgExecutionWorkflowError,
        match="command is not bound to the declared baseline",
    ):
        materialize_hamburg_w1_topology_handoff(
            output_dir=tmp_path / "provenance-wrong-command",
            candidate_net_file=candidate,
            build_spec_file=wrong_command_spec,
            topology_audit_file=topology,
            scope_ledger_file=scope_ledger,
            turnaround_audit_file=turnaround,
            movement_authority_file=movement_authority,
            surface_comparison_file=surface,
            connection_mode_manifest_file=connection,
            sumo_load_report_file=load,
            movement_smoke_file=smoke,
            netedit_review_files=review_files,
            expected_review_junction_ids=("a", "b"),
        )

    mismatched_scope_payload = json.loads(scope_ledger.read_text(encoding="utf-8"))
    mismatched_scope_payload["full_way_baseline"] = {
        "path": str(source),
        "sha256": file_sha256(source),
        "external_edge_count": 2,
    }
    mismatched_scope = write("scope-baseline-mismatch.json", mismatched_scope_payload)
    with pytest.raises(
        HamburgExecutionWorkflowError,
        match="full-way baseline does not match the canonical build",
    ):
        materialize_hamburg_w1_topology_handoff(
            output_dir=tmp_path / "scope-baseline-mismatch",
            candidate_net_file=candidate,
            build_spec_file=build_spec,
            topology_audit_file=topology,
            scope_ledger_file=mismatched_scope,
            turnaround_audit_file=turnaround,
            movement_authority_file=movement_authority,
            surface_comparison_file=surface,
            connection_mode_manifest_file=connection,
            sumo_load_report_file=load,
            movement_smoke_file=smoke,
            netedit_review_files=review_files,
            expected_review_junction_ids=("a", "b"),
        )

    bad = json.loads(review_files[0].read_text(encoding="utf-8"))
    bad["candidate_sha256_after"] = "wrong"
    review_files[0].write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(HamburgExecutionWorkflowError, match="W1 topology handoff rejected"):
        materialize_hamburg_w1_topology_handoff(
            output_dir=tmp_path / "bad",
            candidate_net_file=candidate,
            build_spec_file=build_spec,
            topology_audit_file=topology,
            scope_ledger_file=scope_ledger,
            turnaround_audit_file=turnaround,
            movement_authority_file=movement_authority,
            surface_comparison_file=surface,
            connection_mode_manifest_file=connection,
            sumo_load_report_file=load,
            movement_smoke_file=smoke,
            netedit_review_files=review_files,
            expected_review_junction_ids=("a", "b"),
        )

    bad["candidate_sha256_after"] = candidate_hash
    review_files[0].write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(HamburgExecutionWorkflowError, match="NetEdit review owners are empty"):
        materialize_hamburg_w1_topology_handoff(
            output_dir=tmp_path / "empty-review",
            candidate_net_file=candidate,
            build_spec_file=build_spec,
            topology_audit_file=topology,
            scope_ledger_file=scope_ledger,
            turnaround_audit_file=turnaround,
            movement_authority_file=movement_authority,
            surface_comparison_file=surface,
            connection_mode_manifest_file=connection,
            sumo_load_report_file=load,
            movement_smoke_file=smoke,
            netedit_review_files=(),
            expected_review_junction_ids=(),
        )

    unaccounted_scope_payload = json.loads(scope_ledger.read_text(encoding="utf-8"))
    unaccounted_scope_payload["unaccounted_edge_count"] = 1
    unaccounted_scope_payload["classification_counts"]["unaccounted"] = 1
    unaccounted_scope = write("scope-unaccounted.json", unaccounted_scope_payload)
    with pytest.raises(HamburgExecutionWorkflowError, match="scope edge-preservation ledger has unaccounted edges"):
        materialize_hamburg_w1_topology_handoff(
            output_dir=tmp_path / "unaccounted-scope",
            candidate_net_file=candidate,
            build_spec_file=build_spec,
            topology_audit_file=topology,
            scope_ledger_file=unaccounted_scope,
            turnaround_audit_file=turnaround,
            movement_authority_file=movement_authority,
            surface_comparison_file=surface,
            connection_mode_manifest_file=connection,
            sumo_load_report_file=load,
            movement_smoke_file=smoke,
            netedit_review_files=review_files,
            expected_review_junction_ids=("a", "b"),
        )

    unsupported_turnaround_payload = json.loads(turnaround.read_text(encoding="utf-8"))
    unsupported_turnaround_payload["unsupported_turnaround_count"] = 1
    unsupported_turnaround = write("turnaround-unsupported.json", unsupported_turnaround_payload)
    with pytest.raises(
        HamburgExecutionWorkflowError,
        match="turnaround audit is not a whole-network zero-turnaround pass",
    ):
        materialize_hamburg_w1_topology_handoff(
            output_dir=tmp_path / "unsupported-turnaround",
            candidate_net_file=candidate,
            build_spec_file=build_spec,
            topology_audit_file=topology,
            scope_ledger_file=scope_ledger,
            turnaround_audit_file=unsupported_turnaround,
            movement_authority_file=movement_authority,
            surface_comparison_file=surface,
            connection_mode_manifest_file=connection,
            sumo_load_report_file=load,
            movement_smoke_file=smoke,
            netedit_review_files=review_files,
            expected_review_junction_ids=("a", "b"),
        )

    candidate.write_text(
        """\
<net>
  <edge id="forward" from="a" to="b">
    <lane id="forward_0" index="0" length="1" shape="0,0 1,0"/>
  </edge>
  <edge id="reverse" from="b" to="a">
    <lane id="reverse_0" index="0" length="1" shape="1,0 0,0"/>
  </edge>
  <junction id="a" type="priority" x="0" y="0" incLanes="reverse_0" intLanes=""/>
  <junction id="b" type="priority" x="1" y="0" incLanes="forward_0" intLanes=""/>
  <connection from="forward" to="reverse" fromLane="0" toLane="0" dir="t"/>
</net>
""",
        encoding="utf-8",
    )
    try:
        with pytest.raises(
            HamburgExecutionWorkflowError,
            match="independent turnaround rescan is not a whole-network zero-turnaround pass",
        ):
            materialize_hamburg_w1_topology_handoff(
                output_dir=tmp_path / "turnaround-rescan",
                candidate_net_file=candidate,
                build_spec_file=build_spec,
                topology_audit_file=topology,
                scope_ledger_file=scope_ledger,
                turnaround_audit_file=turnaround,
                movement_authority_file=movement_authority,
                surface_comparison_file=surface,
                connection_mode_manifest_file=connection,
                sumo_load_report_file=load,
                movement_smoke_file=smoke,
                netedit_review_files=review_files,
                expected_review_junction_ids=("a", "b"),
            )
    finally:
        candidate.write_text("<net/>", encoding="utf-8")

    inherited_smoke_payload = json.loads(smoke.read_text(encoding="utf-8"))
    inherited_smoke_payload["inputs"].pop("movement_authority")
    inherited_smoke_payload["inputs"]["preservation_audit"] = {
        "path": str(topology),
        "sha256": file_sha256(topology),
    }
    inherited_smoke = write("smoke-inherited.json", inherited_smoke_payload)
    with pytest.raises(HamburgExecutionWorkflowError, match="movement smoke artifact is missing: movement_authority"):
        materialize_hamburg_w1_topology_handoff(
            output_dir=tmp_path / "inherited-smoke",
            candidate_net_file=candidate,
            build_spec_file=build_spec,
            topology_audit_file=topology,
            scope_ledger_file=scope_ledger,
            turnaround_audit_file=turnaround,
            movement_authority_file=movement_authority,
            surface_comparison_file=surface,
            connection_mode_manifest_file=connection,
            sumo_load_report_file=load,
            movement_smoke_file=inherited_smoke,
            netedit_review_files=review_files,
            expected_review_junction_ids=("a", "b"),
        )

    report = materialize_hamburg_w1_topology_handoff(
        output_dir=tmp_path / "good",
        candidate_net_file=candidate,
        build_spec_file=build_spec,
        topology_audit_file=topology,
        scope_ledger_file=scope_ledger,
        turnaround_audit_file=turnaround,
        movement_authority_file=movement_authority,
        surface_comparison_file=surface,
        connection_mode_manifest_file=connection,
        sumo_load_report_file=load,
        movement_smoke_file=smoke,
        netedit_review_files=review_files,
        expected_review_junction_ids=("a", "b"),
    )

    assert report["status"] == "review_ready"
    assert report["execution_gate"] == "pass"
    assert report["automatic_promotion_gate"] == "blocked"
    assert report["network"]["path"] == "../candidate.net.xml"
    assert report["artifacts"]["network"] == "../candidate.net.xml"
    assert report["artifacts"]["manifest"] == "hamburg_official_corridor_geometry.manifest.json"
    assert report["evidence"]["build_spec"]["path"] == "../canonical-build-spec.json"
    assert report["netedit_review"]["junction_ids"] == ["a", "b"]
    assert report["gates"]["scope_edge_preservation"] == "pass"
    assert report["gates"]["unsupported_turnarounds"] == "pass"
    assert report["gates"]["movement_authority"] == "review_required"
    assert report["routeability"]["authority_id"] == "hamburg-cad-aerial-review-v1"
    assert report["routeability"]["movement_count"] == 2

    surface_review_payload = json.loads(surface.read_text(encoding="utf-8"))
    surface_review_payload.update(
        {
            "status": "fail",
            "junction_junction_overlap_count": 3,
            "external_lane_non_owner_junction_overlap_count": 5,
        }
    )
    surface_review = write("surface-review.json", surface_review_payload)
    surface_report = materialize_hamburg_w1_topology_handoff(
        output_dir=tmp_path / "surface-review",
        candidate_net_file=candidate,
        build_spec_file=build_spec,
        topology_audit_file=topology,
        scope_ledger_file=scope_ledger,
        turnaround_audit_file=turnaround,
        movement_authority_file=movement_authority,
        surface_comparison_file=surface_review,
        connection_mode_manifest_file=connection,
        sumo_load_report_file=load,
        movement_smoke_file=smoke,
        netedit_review_files=review_files,
        expected_review_junction_ids=("a", "b"),
    )
    assert surface_report["execution_gate"] == "pass"
    assert surface_report["gates"]["surface_overlap"] == "review_required"
    assert surface_report["automatic_promotion_gate"] == "blocked"
    assert surface_report["gates"]["automatic_promotion"] == "blocked"

    connection_review_payload = json.loads(connection.read_text(encoding="utf-8"))
    connection_review_payload.update(
        {
            "status": "fail",
            "gate_status": "fail",
            "automatic_promotion_gate": "blocked",
            "blockers": ["new_target_scope_review_findings"],
            "outside_scope_regression_junction_ids": [],
            "target_scope_flagged_junction_ids": ["joined-a"],
            "requested_target_candidate_junction_ids": ["joined-a"],
            "outside_scope_new_structural_finding_count": 0,
            "target_scope_new_structural_finding_count": 0,
            "outside_scope_new_review_finding_count": 0,
            "target_scope_new_review_finding_count": 1,
        }
    )
    connection_review = write("connection-review.json", connection_review_payload)
    connection_report = materialize_hamburg_w1_topology_handoff(
        output_dir=tmp_path / "connection-review",
        candidate_net_file=candidate,
        build_spec_file=build_spec,
        topology_audit_file=topology,
        scope_ledger_file=scope_ledger,
        turnaround_audit_file=turnaround,
        movement_authority_file=movement_authority,
        surface_comparison_file=surface,
        connection_mode_manifest_file=connection_review,
        sumo_load_report_file=load,
        movement_smoke_file=smoke,
        netedit_review_files=review_files,
        expected_review_junction_ids=("a", "b"),
    )
    assert connection_report["execution_gate"] == "pass"
    assert connection_report["gates"]["connection_mode"] == "review_required"
    assert connection_report["automatic_promotion_gate"] == "blocked"

    connection_review_payload["outside_scope_regression_junction_ids"] = ["outside"]
    outside_regression = write("connection-outside-regression.json", connection_review_payload)
    with pytest.raises(HamburgExecutionWorkflowError, match="connection-mode regression is not pass"):
        materialize_hamburg_w1_topology_handoff(
            output_dir=tmp_path / "connection-outside-regression",
            candidate_net_file=candidate,
            build_spec_file=build_spec,
            topology_audit_file=topology,
            scope_ledger_file=scope_ledger,
            turnaround_audit_file=turnaround,
            movement_authority_file=movement_authority,
            surface_comparison_file=surface,
            connection_mode_manifest_file=outside_regression,
            sumo_load_report_file=load,
            movement_smoke_file=smoke,
            netedit_review_files=review_files,
            expected_review_junction_ids=("a", "b"),
        )

    failed_load_payload = json.loads(load.read_text(encoding="utf-8"))
    failed_load_payload["status"] = "fail"
    failed_load = write("load-failed.json", failed_load_payload)
    with pytest.raises(HamburgExecutionWorkflowError, match="SUMO load audit is not pass"):
        materialize_hamburg_w1_topology_handoff(
            output_dir=tmp_path / "failed-load",
            candidate_net_file=candidate,
            build_spec_file=build_spec,
            topology_audit_file=topology,
            scope_ledger_file=scope_ledger,
            turnaround_audit_file=turnaround,
            movement_authority_file=movement_authority,
            surface_comparison_file=surface_review,
            connection_mode_manifest_file=connection,
            sumo_load_report_file=failed_load,
            movement_smoke_file=smoke,
            netedit_review_files=review_files,
            expected_review_junction_ids=("a", "b"),
        )


def test_counts_and_detector_binding_are_independent_real_stages(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path, stage_id, network_file=network)
        manifests[stage_id] = path
    w2 = tmp_path / "W2.json"
    _write_manifest(
        w2,
        "W2",
        status="blocked",
        gate="blocked",
        execution_gate="blocked",
        network_file=network,
    )
    manifests["W2"] = w2

    first = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests=manifests,
    )
    assert first["stages"]["W3a"]["readiness"] == "ready"
    assert first["stages"]["W3b"]["readiness"] == "blocked"
    assert first["next_action"]["stage_id"] == "W3a"

    w3a = tmp_path / "W3a.json"
    _write_manifest(w3a, "W3a")
    manifests["W3a"] = w3a
    second = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests=manifests,
    )
    assert second["stages"]["W3a"]["readiness"] == "complete"
    assert second["stages"]["W3b"]["readiness"] == "ready"
    assert second["next_action"]["stage_id"] == "W3b"

    w3b = tmp_path / "W3b.json"
    _write_manifest(w3b, "W3b", network_file=network)
    manifests["W3b"] = w3b
    third = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests=manifests,
    )
    assert third["next_action"]["stage_id"] == "W2"
    assert third["next_action"]["action"] == "resolve_stage_gate"


def test_complete_inputs_generate_internal_w5_package(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1", "W3a", "W2", "W3b", "W4"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path, stage_id, network_file=network)
        manifests[stage_id] = path

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests=manifests,
    )

    assert plan["schema"] == HAMBURG_EXECUTION_WORKFLOW_SCHEMA
    assert plan["next_action"] == {"stage_id": None, "status": "complete", "action": "none"}
    assert plan["stages"]["W5"]["generated"] is True
    assert plan["stages"]["W5"]["status"] == "complete"
    assert plan["stages"]["W5"]["summarized_capabilities"] == list(plan["capabilities"])
    assert plan["promotion"]["decision"] == "pass"
    assert plan["capabilities"]["road_topology"]["status"] == "pass"
    assert list(plan["stages"]) == ["W0", "W1", "W3a", "W2", "W3b", "W4", "W5"]


def test_execution_complete_does_not_override_blocked_promotion_gates(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1", "W3a", "W2", "W3b", "W4"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(
            path,
            stage_id,
            status="partial",
            gate="blocked",
            execution_gate="pass",
            network_file=network,
        )
        manifests[stage_id] = path

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests=manifests,
    )

    assert plan["next_action"]["status"] == "complete"
    assert plan["promotion"] == {
        "decision": "blocked",
        "automatic": True,
        "execution_complete": True,
        "requires": (
            "W0, W1, W2, W3a, W3b, and W4 are materialized with "
            "execution_gate=pass, decision=pass, and automatic_promotion_gate=pass"
        ),
    }
    assert plan["stages"]["W5"]["status"] == "complete"
    assert plan["capabilities"]["road_topology"]["status"] == "pass"
    assert plan["capabilities"]["road_topology"]["promotion_status"] == "review_required"
    assert plan["capabilities"]["official_counts"]["status"] == "diagnostic"
    assert plan["capabilities"]["detector_binding"]["status"] == "review_required"
    assert plan["capabilities"]["field_faithful_digital_twin"]["status"] == "blocked"


def test_w1_change_invalidates_network_bound_descendants_not_counts(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1", "W3a", "W2", "W3b", "W4"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path, stage_id, network_file=network)
        manifests[stage_id] = path
    plan_dir = tmp_path / "plan"
    materialize_hamburg_execution_plan(output_dir=plan_dir, stage_manifests=manifests)

    _write_manifest(
        manifests["W1"],
        "W1",
        status="review_ready",
        gate="blocked",
        execution_gate="pass",
        network_file=network,
    )
    second = materialize_hamburg_execution_plan(
        output_dir=plan_dir,
        stage_manifests=manifests,
    )

    assert second["changed_stages"] == ["W1"]
    assert second["invalidated_downstream_stages"] == ["W2", "W3b", "W4"]
    assert second["stages"]["W1"]["effective_status"] == "review_ready"
    assert second["stages"]["W3a"]["effective_status"] == "pass"
    assert second["stages"]["W3b"]["effective_status"] == "not_run"


def test_w3a_change_invalidates_detector_binding_and_replay(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1", "W3a", "W2", "W3b", "W4"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path, stage_id, network_file=network)
        manifests[stage_id] = path
    plan_dir = tmp_path / "plan"
    materialize_hamburg_execution_plan(output_dir=plan_dir, stage_manifests=manifests)

    _write_manifest(
        manifests["W3a"],
        "W3a",
        status="partial",
        gate="blocked",
        execution_gate="pass",
    )
    second = materialize_hamburg_execution_plan(
        output_dir=plan_dir,
        stage_manifests=manifests,
    )

    assert second["changed_stages"] == ["W3a"]
    assert second["invalidated_downstream_stages"] == ["W3b", "W4"]

    third = materialize_hamburg_execution_plan(
        output_dir=plan_dir,
        stage_manifests=manifests,
    )

    assert third["changed_stages"] == []
    assert third["invalidated_downstream_stages"] == ["W3b", "W4"]
    assert third["stages"]["W3b"]["effective_status"] == "not_run"
    assert third["stages"]["W4"]["effective_status"] == "not_run"

    _write_manifest(
        manifests["W3b"],
        "W3b",
        status="partial",
        gate="blocked",
        execution_gate="pass",
        network_file=network,
    )
    _write_manifest(manifests["W4"], "W4", network_file=network)
    fourth = materialize_hamburg_execution_plan(
        output_dir=plan_dir,
        stage_manifests=manifests,
    )

    assert fourth["changed_stages"] == ["W3b", "W4"]
    assert fourth["invalidated_downstream_stages"] == []
    assert fourth["stages"]["W3b"]["effective_status"] == "partial"
    assert fourth["stages"]["W4"]["effective_status"] == "pass"


def test_newly_supplied_stage_is_not_invalidated_by_its_own_change(tmp_path: Path) -> None:
    w0 = tmp_path / "W0.json"
    _write_manifest(w0, "W0")
    plan_dir = tmp_path / "plan"
    materialize_hamburg_execution_plan(
        output_dir=plan_dir,
        stage_manifests={"W0": w0},
    )
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    w1 = tmp_path / "W1.json"
    _write_manifest(w1, "W1", network_file=network)

    second = materialize_hamburg_execution_plan(
        output_dir=plan_dir,
        stage_manifests={"W0": w0, "W1": w1},
    )

    assert second["changed_stages"] == ["W1"]
    assert second["invalidated_downstream_stages"] == []
    assert second["stages"]["W1"]["effective_status"] == "pass"
    assert second["stages"]["W1"]["readiness"] == "complete"
    assert second["next_action"]["stage_id"] == "W3a"


def test_network_binding_must_match_w1_and_current_bytes(tmp_path: Path) -> None:
    w1_network = tmp_path / "w1.net.xml"
    stale_network = tmp_path / "stale.net.xml"
    w1_network.write_text("<net id=\"w1\"/>\n", encoding="utf-8")
    stale_network.write_text("<net id=\"stale\"/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1", "W3a"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path, stage_id, network_file=w1_network)
        manifests[stage_id] = path
    w3b = tmp_path / "W3b.json"
    _write_manifest(w3b, "W3b", network_file=stale_network)
    manifests["W3b"] = w3b

    mismatch = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "mismatch-plan",
        stage_manifests=manifests,
    )
    assert mismatch["stages"]["W3b"]["contract_error"] == "network_binding_does_not_match_W1"
    assert mismatch["stages"]["W3b"]["execution_gate"] == "blocked"

    w1_network.write_text("<net id=\"mutated\"/>\n", encoding="utf-8")
    mutated = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "mutated-plan",
        stage_manifests={"W0": manifests["W0"], "W1": manifests["W1"]},
    )
    assert mutated["stages"]["W1"]["contract_error"] == "network_binding_sha256_mismatch"


def test_downstream_stages_bind_the_selected_w1_manifest_identity(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1", "W3a", "W2", "W3b", "W4"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path, stage_id, network_file=network)
        manifests[stage_id] = path

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests=manifests,
    )
    plan_dir = Path(plan["plan_file"]).parent
    expected_sha256 = file_sha256(manifests["W1"])
    for stage_id, manifest in manifests.items():
        record = plan["stages"][stage_id]
        assert not Path(record["manifest"]).is_absolute()
        assert (plan_dir / record["manifest"]).resolve() == manifest
        for container_name in ("network_binding", "artifact_bindings", "stage_bindings"):
            container = record.get(container_name, {})
            identities = container.values() if container_name != "network_binding" else (container,)
            for identity in identities:
                if isinstance(identity, dict) and identity.get("path"):
                    assert not Path(identity["path"]).is_absolute()
                    assert (plan_dir / identity["path"]).resolve().is_file()
    for stage_id in ("W2", "W3b", "W4"):
        binding = plan["stages"][stage_id]["stage_bindings"]["w1_manifest"]
        assert binding["validation"] == "pass"
        assert binding["sha256"] == expected_sha256

    persisted = json.loads(Path(plan["plan_file"]).read_text(encoding="utf-8"))
    for record in persisted["stages"].values():
        for container_name in ("network_binding", "artifact_bindings", "stage_bindings"):
            container = record.get(container_name, {})
            identities = container.values() if container_name != "network_binding" else (container,)
            for identity in identities:
                if isinstance(identity, dict) and identity.get("path"):
                    identity["path"] = str((plan_dir / identity["path"]).resolve())
    Path(plan["plan_file"]).write_text(json.dumps(persisted), encoding="utf-8")
    resumed = materialize_hamburg_execution_plan(
        output_dir=plan_dir,
        stage_manifests=manifests,
    )
    assert resumed["changed_stages"] == []


def test_same_network_with_a_different_w1_manifest_blocks_downstream(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1", "W2"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path, stage_id, network_file=network)
        manifests[stage_id] = path
    alternate_w1 = tmp_path / "alternate-W1.json"
    alternate_payload = json.loads(manifests["W1"].read_text(encoding="utf-8"))
    alternate_payload["identity_note"] = "same network, different W1 decision"
    alternate_w1.write_text(json.dumps(alternate_payload), encoding="utf-8")
    w2_payload = json.loads(manifests["W2"].read_text(encoding="utf-8"))
    w2_payload["source"]["w1_manifest"] = {
        "path": str(alternate_w1.resolve()),
        "sha256": file_sha256(alternate_w1),
    }
    manifests["W2"].write_text(json.dumps(w2_payload), encoding="utf-8")

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests=manifests,
    )

    assert plan["stages"]["W2"]["network_binding"]["validation"] == "pass"
    assert plan["stages"]["W2"]["contract_error"] == (
        "stage_binding_w1_manifest_does_not_match_W1"
    )


def test_w4_must_reference_the_selected_w3b_manifest(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1", "W3a", "W2"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path, stage_id, network_file=network)
        manifests[stage_id] = path
    stale_w3b = tmp_path / "W3b.json"
    _write_manifest(stale_w3b, "W3b", network_file=network)
    selected_w3b = tmp_path / "selected-W3b.json"
    _write_manifest(
        selected_w3b,
        "W3b",
        status="partial",
        gate="blocked",
        execution_gate="pass",
        network_file=network,
    )
    manifests["W3b"] = selected_w3b
    w4 = tmp_path / "W4.json"
    _write_manifest(w4, "W4", network_file=network)
    manifests["W4"] = w4

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests=manifests,
    )

    assert plan["stages"]["W4"]["contract_error"] == (
        "stage_binding_detector_binding_manifest_does_not_match_W3b"
    )
    assert plan["stages"]["W4"]["execution_gate"] == "blocked"


def test_w4_requires_approved_w3b_aggregation_semantics(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1", "W3a", "W2", "W3b"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path, stage_id, network_file=network)
        manifests[stage_id] = path
    w3b_payload = json.loads(manifests["W3b"].read_text(encoding="utf-8"))
    w3b_payload["gates"]["sensor_aggregation_semantics"] = "blocked"
    manifests["W3b"].write_text(json.dumps(w3b_payload), encoding="utf-8")
    w4 = tmp_path / "W4.json"
    _write_manifest(w4, "W4", network_file=network)
    manifests["W4"] = w4

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests=manifests,
    )

    assert plan["stages"]["W4"]["contract_error"] == (
        "W3b_sensor_aggregation_semantics_not_pass"
    )
    assert plan["stages"]["W4"]["execution_gate"] == "blocked"


def test_w3b_must_use_the_w3a_count_stream_snapshot(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1", "W3a"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path, stage_id, network_file=network)
        manifests[stage_id] = path
    other_streams = tmp_path / "other-count-streams.json"
    other_streams.write_text('{"streams":[1]}\n', encoding="utf-8")
    w3b = tmp_path / "W3b.json"
    _write_manifest(w3b, "W3b", network_file=network)
    payload = json.loads(w3b.read_text(encoding="utf-8"))
    payload["source"]["count_stream_snapshot"] = {
        "path": str(other_streams.resolve()),
        "sha256": file_sha256(other_streams),
    }
    w3b.write_text(json.dumps(payload), encoding="utf-8")
    manifests["W3b"] = w3b

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests=manifests,
    )

    assert plan["stages"]["W3b"]["contract_error"] == (
        "stage_binding_count_stream_snapshot_does_not_match_W3a"
    )
    assert plan["stages"]["W3b"]["execution_gate"] == "blocked"


def test_w4_must_use_w3a_count_values(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1", "W3a", "W2", "W3b", "W4"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path, stage_id, network_file=network)
        manifests[stage_id] = path
    other_counts = tmp_path / "other-counts.csv"
    other_counts.write_text("stream_id,begin,end,total\n1,0,900,1\n", encoding="utf-8")
    payload = json.loads(manifests["W4"].read_text(encoding="utf-8"))
    payload["source"]["canonical_count_file"] = {
        "path": str(other_counts.resolve()),
        "sha256": file_sha256(other_counts),
    }
    manifests["W4"].write_text(json.dumps(payload), encoding="utf-8")

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests=manifests,
    )

    assert plan["stages"]["W4"]["contract_error"] == (
        "stage_binding_canonical_count_file_does_not_match_W3a"
    )


def test_workflow_rehashes_mapping_and_signal_event_artifacts(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1", "W3a", "W2", "W3b", "W4"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path, stage_id, network_file=network)
        manifests[stage_id] = path

    detector_mapping = tmp_path / "detector_mapping.csv"
    original_mapping = detector_mapping.read_text(encoding="utf-8")
    mapping_plan_dir = tmp_path / "mapping-plan"
    materialize_hamburg_execution_plan(
        output_dir=mapping_plan_dir,
        stage_manifests=manifests,
    )
    detector_mapping.write_text("mutated\n", encoding="utf-8")
    mapping_plan = materialize_hamburg_execution_plan(
        output_dir=mapping_plan_dir,
        stage_manifests=manifests,
    )
    assert mapping_plan["changed_stages"] == ["W3b"]
    assert mapping_plan["invalidated_downstream_stages"] == ["W4"]
    assert mapping_plan["stages"]["W3b"]["contract_error"] == (
        "stage_binding_detector_mapping_sha256_mismatch"
    )

    detector_mapping.write_text(original_mapping, encoding="utf-8")
    observation_manifest = tmp_path / "signal-observations.json"
    observation_manifest.write_text('{"schema":"fixture"}\n', encoding="utf-8")
    tls_events = tmp_path / "tls-link-events.csv"
    tls_events.write_text("time,tls_id,link_index,state\n", encoding="utf-8")
    w4_payload = json.loads(manifests["W4"].read_text(encoding="utf-8"))
    w4_payload["source"]["signal_observation_manifest"] = {
        "path": str(observation_manifest.resolve()),
        "sha256": file_sha256(observation_manifest),
    }
    w4_payload["source"]["tls_link_events"] = {
        "path": str(tls_events.resolve()),
        "sha256": file_sha256(tls_events),
    }
    manifests["W4"].write_text(json.dumps(w4_payload), encoding="utf-8")
    event_plan_dir = tmp_path / "event-plan"
    materialize_hamburg_execution_plan(
        output_dir=event_plan_dir,
        stage_manifests=manifests,
    )
    tls_events.write_text("mutated\n", encoding="utf-8")
    event_plan = materialize_hamburg_execution_plan(
        output_dir=event_plan_dir,
        stage_manifests=manifests,
    )
    assert event_plan["changed_stages"] == ["W4"]
    assert event_plan["stages"]["W4"]["contract_error"] == (
        "stage_binding_tls_link_events_sha256_mismatch"
    )


def test_manifest_schema_is_stage_specific(tmp_path: Path) -> None:
    w0 = tmp_path / "W0.json"
    w0.write_text(
        json.dumps(
            {
                "schema": "wrong-for-every-stage",
                "status": "pass",
                "automatic_promotion_gate": "pass",
            }
        ),
        encoding="utf-8",
    )

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests={"W0": w0},
    )

    assert plan["stages"]["W0"]["decision"] == "blocked"
    assert plan["stages"]["W0"]["contract_error"].startswith("manifest_schema_mismatch")


def test_scope_can_feed_geometry_and_counts_without_signal_promotion(tmp_path: Path) -> None:
    w0 = tmp_path / "W0.json"
    w0.write_text(
        json.dumps(
            {
                "schema": "torii.hamburg-named-corridor-scope/v1",
                "status": "partial",
                "automatic_promotion_gate": "blocked",
                "signal_assets": {"decision": "blocked"},
                "nodes": [{"node_id": "2349"}, {"node_id": "2394"}, {"node_id": "2403"}],
                "official_road_scope": {"link_count": 7},
            }
        ),
        encoding="utf-8",
    )

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests={"W0": w0},
    )

    assert plan["stages"]["W0"]["execution_gate"] == "pass"
    assert plan["stages"]["W1"]["readiness"] == "ready"
    assert plan["stages"]["W3a"]["readiness"] == "ready"
    assert plan["stages"]["W3b"]["readiness"] == "blocked"
    assert plan["promotion"]["decision"] == "blocked"


def test_machine_feedback_is_hash_bound_without_changing_gate(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1", "W3a", "W3b"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path, stage_id, network_file=network)
        manifests[stage_id] = path
    w2 = tmp_path / "W2.json"
    _write_manifest(
        w2,
        "W2",
        status="blocked",
        gate="blocked",
        execution_gate="blocked",
        network_file=network,
    )
    payload = json.loads(w2.read_text(encoding="utf-8"))
    payload.update(
        {
            "execution_gate_reason": "one or more active bindings lack a complete response",
            "missing_required_node_ids": ["2403"],
            "incomplete_stream_ids": [72940],
        }
    )
    w2.write_text(json.dumps(payload), encoding="utf-8")
    manifests["W2"] = w2
    history = tmp_path / "history.json"
    history.write_text(
        json.dumps(
            {
                "resolved_node_ids": ["2349", "2394"],
                "unresolved_node_ids": ["2403"],
                "publication_gap": {
                    "decision": "confirmed_official_node_without_published_tld_binding",
                    "next_action": "resolve_official_signal_publication_gap_or_change_scope",
                },
            }
        ),
        encoding="utf-8",
    )
    identity = tmp_path / "identity.json"
    identity.write_text(
        json.dumps(
            {
                "decision": "pass",
                "human_action_required": False,
                "selections": [
                    {"selected_node": {"node_id": node_id}}
                    for node_id in ("2349", "2394", "2403")
                ],
            }
        ),
        encoding="utf-8",
    )

    plan = materialize_hamburg_execution_plan(
        output_dir=tmp_path / "plan",
        stage_manifests=manifests,
        stage_feedback={"W2": (history, identity)},
    )

    assert plan["first_invalid_stage"] == "W2"
    assert plan["stages"]["W2"]["execution_gate"] == "blocked"
    assert len(plan["stages"]["W2"]["feedback_manifests"]) == 2
    assert plan["replan"]["feedback"]["resolved_node_ids"] == ["2349", "2394"]
    assert plan["replan"]["feedback"]["official_node_identity"]["selected_node_ids"] == [
        "2349",
        "2394",
        "2403",
    ]


def test_feedback_change_invalidates_only_materialized_downstream_stage(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifests = {}
    for stage_id in ("W0", "W1", "W3a", "W2", "W3b", "W4"):
        path = tmp_path / f"{stage_id}.json"
        _write_manifest(path, stage_id, network_file=network)
        manifests[stage_id] = path
    feedback = tmp_path / "feedback.json"
    feedback.write_text(json.dumps({"resolved_node_ids": ["2349"]}), encoding="utf-8")
    plan_dir = tmp_path / "plan"
    materialize_hamburg_execution_plan(
        output_dir=plan_dir,
        stage_manifests=manifests,
        stage_feedback={"W2": feedback},
    )

    feedback.write_text(json.dumps({"resolved_node_ids": ["2349", "2394"]}), encoding="utf-8")
    second = materialize_hamburg_execution_plan(
        output_dir=plan_dir,
        stage_manifests=manifests,
        stage_feedback={"W2": feedback},
    )

    assert second["changed_stages"] == ["W2"]
    assert second["invalidated_downstream_stages"] == ["W4"]


def test_external_w5_and_legacy_w3_are_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "stage.json"
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(HamburgExecutionWorkflowError, match="generated automatically"):
        materialize_hamburg_execution_plan(
            output_dir=tmp_path / "w5-plan",
            stage_manifests={"W5": manifest},
        )
    with pytest.raises(HamburgExecutionWorkflowError, match="was split"):
        materialize_hamburg_execution_plan(
            output_dir=tmp_path / "w3-plan",
            stage_manifests={"W3": manifest},
        )


def test_portable_workflow_config_resolves_stage_paths_relative_to_itself(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    _write_manifest(evidence_dir / "W0.json", "W0")
    _write_manifest(evidence_dir / "W1.json", "W1")
    config = tmp_path / "hamburg-workflow.json"
    config.write_text(
        json.dumps(
            {
                "schema": HAMBURG_EXECUTION_CONFIG_SCHEMA,
                "output_dir": "run",
                "resume": False,
                "stages": {
                    "W0": {"manifest": "evidence/W0.json"},
                    "W1": {"manifest": "evidence/W1.json", "feedback": []},
                },
            }
        ),
        encoding="utf-8",
    )

    plan = materialize_hamburg_execution_plan_from_config(config)

    assert plan["stages"]["W0"]["decision"] == "pass"
    assert plan["stages"]["W1"]["decision"] == "pass"
    assert plan["next_action"]["stage_id"] == "W3a"
    assert (tmp_path / "run" / "execution-plan.manifest.json").is_file()


def test_portable_workflow_config_rejects_unknown_stage(tmp_path: Path) -> None:
    config = tmp_path / "hamburg-workflow.json"
    config.write_text(
        json.dumps(
            {
                "schema": HAMBURG_EXECUTION_CONFIG_SCHEMA,
                "output_dir": "run",
                "stages": {"W9": {}},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(HamburgExecutionWorkflowError, match="unknown workflow stage"):
        materialize_hamburg_execution_plan_from_config(config)

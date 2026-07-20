"""Bind Hamburg TLD signal metadata to an official-first SUMO corridor.

This module only binds evidence.  It never invents signal phases or rewrites the
candidate network.  A later stage may consume the bindings together with
historical observations.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence

from .artifact_io import write_json_atomic
from .candidate_contracts import file_sha256


SIGNAL_BINDING_SCHEMA = "torii.hamburg-named-signal-binding/v1"
_DEFAULT_NODES = ("2349", "2394", "2403")


class HamburgSignalBindingError(ValueError):
    """Raised when signal-binding inputs cannot be interpreted safely."""


def materialize_hamburg_named_signal_binding(
    *,
    net_file: Path,
    intersection_manifests: Mapping[str, Path],
    signal_stream_files: Sequence[Path],
    output_dir: Path,
    required_node_ids: Sequence[str] = _DEFAULT_NODES,
) -> dict[str, Any]:
    """Create a hash-bound, non-mutating TLD-to-SUMO binding artifact.

    ``intersection_manifests`` must contain the available official MAP cells.
    Missing required nodes are reported as a partial, non-promoting result;
    they are never filled with guessed streams or phases.
    """

    net_path = Path(net_file).expanduser().resolve(strict=True)
    required = tuple(dict.fromkeys(str(node).strip() for node in required_node_ids if str(node).strip()))
    if not required:
        raise HamburgSignalBindingError("at least one required node is needed")
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise HamburgSignalBindingError("output_dir must be empty; choose a new versioned run")

    manifest_paths = _resolve_manifests(intersection_manifests)
    stream_paths = [Path(path).expanduser().resolve(strict=True) for path in signal_stream_files]
    if not stream_paths:
        raise HamburgSignalBindingError("at least one signal stream file is required")

    local, input_errors = _load_intersection_manifests(manifest_paths)
    streams, stream_sources, stream_errors = _load_stream_files(stream_paths)
    errors = [*input_errors, *stream_errors]
    try:
        net_root = ET.parse(net_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise HamburgSignalBindingError(f"cannot parse candidate SUMO network: {net_path}") from exc

    candidate_connections = _index_candidate_connections(net_root)
    bindings: list[dict[str, Any]] = []
    node_reports: dict[str, dict[str, Any]] = {}
    for node_id in required:
        manifest = local.get(node_id)
        node_streams = [stream for stream in streams if stream["node_id"] == node_id]
        if manifest is None:
            node_reports[node_id] = {
                "status": "missing_official_map_cell",
                "stream_count": len(node_streams),
                "bound_count": 0,
                "expected_vehicle_movement_count": 0,
            }
            continue
        movements = manifest["movements"]
        movement_by_connection = {str(item["connection_id"]): item for item in movements}
        bound_ids: set[str] = set()
        node_errors: list[dict[str, Any]] = []
        for stream in node_streams:
            movement = movement_by_connection.get(stream["connection_id"])
            if movement is None:
                node_errors.append({"code": "stream_connection_not_in_official_map", "stream": stream})
                continue
            mismatches = _movement_mismatches(stream, movement)
            controller_id = str(manifest.get("controller_id", f"hh-map-{node_id}"))
            link_index = str(movement["link_index"])
            candidate_rows = candidate_connections.get((controller_id, link_index), [])
            if not candidate_rows:
                node_errors.append(
                    {
                        "code": "official_link_index_not_in_candidate",
                        "node_id": node_id,
                        "connection_id": stream["connection_id"],
                        "controller_id": controller_id,
                        "link_index": int(link_index),
                    }
                )
                continue
            if mismatches:
                node_errors.append(
                    {
                        "code": "stream_movement_mismatch",
                        "stream": stream,
                        "movement": movement,
                        "mismatches": mismatches,
                    }
                )
                continue
            bound_ids.add(stream["connection_id"])
            bindings.append(
                {
                    "node_id": node_id,
                    "stream_id": stream["stream_id"],
                    "connection_id": stream["connection_id"],
                    "ingress_lane_id": stream["ingress_lane_id"],
                    "egress_lane_id": stream["egress_lane_id"],
                    "signal_group": stream["signal_group"],
                    "controller_id": controller_id,
                    "link_index": int(link_index),
                    "candidate_connections": candidate_rows,
                    "official_map_signal_groups": {
                        "primary": list(movement.get("primary_motor_groups", [])),
                        "secondary": list(movement.get("secondary_motor_groups", [])),
                    },
                }
            )
        unbound = sorted(set(movement_by_connection) - bound_ids, key=lambda value: (int(value), value))
        if unbound:
            node_errors.append(
                {
                    "code": "official_vehicle_movement_without_signal_stream",
                    "node_id": node_id,
                    "connection_ids": unbound,
                }
            )
        node_reports[node_id] = {
            "status": "pass" if not node_errors else "blocked",
            "stream_count": len(node_streams),
            "bound_count": len(bound_ids),
            "expected_vehicle_movement_count": len(movements),
            "unbound_connection_ids": unbound,
            "errors": node_errors,
        }
        errors.extend(node_errors)

    missing_nodes = [node_id for node_id in required if node_id not in local]
    structural_errors = [error for error in errors if error.get("code") != "official_vehicle_movement_without_signal_stream"]
    complete_available = not structural_errors and all(
        report.get("status") == "pass" for node_id, report in node_reports.items() if node_id in local
    )
    status = "partial" if complete_available and missing_nodes else ("pass" if complete_available else "blocked")
    execution_gate = "pass" if complete_available else "blocked"
    promotion_gate = "pass" if complete_available and not missing_nodes else "blocked"
    binding_file = destination / "official-primary-signal-bindings.json"
    manifest_file = destination / "official-primary-signal-binding.manifest.json"
    write_json_atomic(binding_file, {"schema": SIGNAL_BINDING_SCHEMA, "bindings": bindings}, sort_keys=True)
    source_records = [
        {"path": str(path), "sha256": file_sha256(path), **metadata}
        for path, metadata in stream_sources
    ]
    manifest: dict[str, Any] = {
        "schema": SIGNAL_BINDING_SCHEMA,
        "status": status,
        "execution_gate": execution_gate,
        "execution_gate_reason": (
            "available official MAP cells and every supplied TLD stream bind to candidate controller link indices"
            if execution_gate == "pass"
            else "one or more official signal bindings are structurally unresolved"
        ),
        "automatic_promotion_gate": promotion_gate,
        "claim_status": "official-tld-primary-signal-metadata-bound-to-map-movements",
        "source": {
            "candidate_net": {"path": str(net_path), "sha256": file_sha256(net_path)},
            "intersection_manifests": {
                node_id: {"path": str(path), "sha256": file_sha256(path)}
                for node_id, path in manifest_paths.items()
            },
            "signal_stream_files": source_records,
        },
        "required_node_ids": list(required),
        "available_map_node_ids": sorted(local),
        "missing_official_signal_node_ids": missing_nodes,
        "node_reports": node_reports,
        "binding_artifact": {"path": str(binding_file), "sha256": file_sha256(binding_file)},
        "historical_signal_replay": {
            "status": "blocked_pending_official_observations",
            "reason": "metadata identifies controlled movements but does not contain the requested Saturday history",
        },
        "errors": errors,
        "gates": {
            "official_source_hashes": "pass",
            "map_movement_identity": "pass" if complete_available else "blocked",
            "candidate_controller_link_indices": "pass" if complete_available else "blocked",
            "2403_official_signal_asset": "pass" if "2403" not in missing_nodes else "blocked",
            "historical_signal_replay": "blocked_pending_official_observations",
            "automatic_promotion": promotion_gate,
        },
        "claim_boundary": {
            "proves": [
                "which official TLD primary-signal streams were used",
                "which official MAP movement and SUMO controller linkIndex each stream binds to",
                "that missing 2403 signal data is explicit rather than guessed",
            ],
            "does_not_prove": [
                "historical Saturday signal phases or cycle timing",
                "a complete three-node signal controller while a required node is missing",
            ],
        },
        "artifacts": {"bindings": str(binding_file), "manifest": str(manifest_file)},
    }
    write_json_atomic(manifest_file, manifest, sort_keys=True)
    return {**manifest, "manifest_file": str(manifest_file)}


def _resolve_manifests(manifests: Mapping[str, Path]) -> dict[str, Path]:
    if not isinstance(manifests, Mapping) or not manifests:
        raise HamburgSignalBindingError("intersection_manifests must not be empty")
    result: dict[str, Path] = {}
    for raw_node, raw_path in manifests.items():
        node_id = str(raw_node).strip()
        if not node_id:
            raise HamburgSignalBindingError("intersection manifest node id must not be empty")
        if node_id in result:
            raise HamburgSignalBindingError(f"duplicate intersection manifest: {node_id}")
        result[node_id] = Path(raw_path).expanduser().resolve(strict=True)
    return result


def _load_intersection_manifests(paths: Mapping[str, Path]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    loaded: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    for node_id, path in paths.items():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append({"code": "intersection_manifest_invalid", "node_id": node_id, "message": str(exc)})
            continue
        if not isinstance(payload, Mapping) or str(payload.get("node_id")) != node_id:
            errors.append({"code": "intersection_manifest_identity_mismatch", "node_id": node_id})
            continue
        movements = payload.get("movements")
        if not isinstance(movements, list) or not movements:
            errors.append({"code": "intersection_manifest_movements_missing", "node_id": node_id})
            continue
        loaded[node_id] = dict(payload)
    return loaded, errors


def _load_stream_files(
    paths: Sequence[Path],
) -> tuple[list[dict[str, Any]], list[tuple[Path, dict[str, Any]]], list[dict[str, Any]]]:
    streams_by_id: dict[int, dict[str, Any]] = {}
    source_records: list[tuple[Path, dict[str, Any]]] = []
    errors: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append({"code": "signal_stream_file_invalid", "path": str(path), "message": str(exc)})
            continue
        values = payload.get("streams") if isinstance(payload, Mapping) else payload
        if not isinstance(values, list):
            errors.append({"code": "signal_streams_missing", "path": str(path)})
            continue
        metadata = {
            "schema": str(payload.get("schema", "")) if isinstance(payload, Mapping) else "",
            "api_base_url": str(payload.get("api_base_url", "")) if isinstance(payload, Mapping) else "",
        }
        source_records.append((path, metadata))
        for value in values:
            if not isinstance(value, Mapping):
                errors.append({"code": "signal_stream_not_object", "path": str(path)})
                continue
            try:
                stream = {
                    "stream_id": int(value["stream_id"]),
                    "node_id": str(value["node_id"]),
                    "connection_id": str(value["connection_id"]),
                    "ingress_lane_id": str(value["ingress_lane_id"]),
                    "egress_lane_id": str(value["egress_lane_id"]),
                    "signal_group": str(value["signal_group"]),
                    "layer_name": str(value.get("layer_name", "")),
                    "lane_type": str(value.get("lane_type", "")),
                }
            except (KeyError, TypeError, ValueError) as exc:
                errors.append({"code": "signal_stream_identity_invalid", "path": str(path), "message": str(exc)})
                continue
            previous = streams_by_id.get(stream["stream_id"])
            if previous is not None and previous != stream:
                errors.append({"code": "conflicting_duplicate_stream_id", "stream_id": stream["stream_id"]})
            else:
                streams_by_id[stream["stream_id"]] = stream
    return sorted(streams_by_id.values(), key=lambda item: (item["node_id"], item["connection_id"], item["stream_id"])), source_records, errors


def _index_candidate_connections(root: ET.Element) -> dict[tuple[str, str], list[dict[str, Any]]]:
    indexed: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for connection in root.findall("connection"):
        controller = connection.attrib.get("tl")
        link_index = connection.attrib.get("linkIndex")
        if not controller or link_index is None:
            continue
        row = {
            "from": connection.attrib.get("from", ""),
            "to": connection.attrib.get("to", ""),
            "fromLane": int(connection.attrib.get("fromLane", "0")),
            "toLane": int(connection.attrib.get("toLane", "0")),
            "linkIndex": int(link_index),
        }
        indexed.setdefault((controller, link_index), []).append(row)
    return indexed


def _movement_mismatches(stream: Mapping[str, Any], movement: Mapping[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for key in ("ingress_lane_id", "egress_lane_id"):
        if str(stream[key]) != str(movement[key]):
            mismatches.append(key)
    groups = {str(value) for value in [*movement.get("primary_motor_groups", []), *movement.get("secondary_motor_groups", [])]}
    if stream["signal_group"] not in groups:
        mismatches.append("signal_group")
    if stream.get("layer_name") not in {"", "primary_signal"}:
        mismatches.append("layer_name")
    return mismatches

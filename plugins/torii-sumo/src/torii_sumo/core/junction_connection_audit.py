from __future__ import annotations

import csv
import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


CONNECTION_RECORD_FIELDS = [
    "category",
    "from",
    "to",
    "fromLane",
    "toLane",
    "dir",
    "state",
    "via",
    "tl",
    "linkIndex",
    "linkIndex2",
    "pass",
    "uncontrolled",
    "allow",
    "disallow",
    "keepClear",
    "contPos",
    "shape",
]

TLS_MOVEMENT_SIGNATURE_FIELDS = ["from", "to", "fromLane", "toLane", "via", "linkIndex", "dir", "state"]
PEDESTRIAN_EDGE_FUNCTIONS = {"crossing", "walkingarea"}
PEDESTRIAN_CONNECTION_SIGNATURE_FIELDS = ["from", "to", "fromLane", "toLane", "via", "tl", "linkIndex", "dir", "state"]
TURNAROUND_DIR = "t"


def build_teacher_guided_owner_semantics_probe(
    teacher_net_file: Path,
    candidate_net_file: Path,
    *,
    owner_id: str,
    candidate_owner_id: str | None = None,
    teacher_edge_map: dict[str, str] | None = None,
    source_osm_file: Path | None = None,
) -> dict[str, Any]:
    from .road_connectivity_teacher_model import (
        build_internal_movement_owner_approach_edge_map,
        build_internal_movement_owner_road_connectivity_parity_audit,
    )

    candidate_owner_id = candidate_owner_id or owner_id
    if teacher_edge_map is None:
        edge_mapping_layer = build_internal_movement_owner_approach_edge_map(
            teacher_net_file,
            candidate_net_file,
            owner_id=owner_id,
            candidate_owner_id=candidate_owner_id,
        )
        teacher_edge_map = edge_mapping_layer["edge_map"]
        edge_mapping_layer = dict(edge_mapping_layer)
        edge_mapping_layer["status"] = (
            "fail"
            if edge_mapping_layer.get("ambiguous_teacher_edges") or edge_mapping_layer.get("unmapped_teacher_edges")
            else "pass"
        )
    else:
        edge_mapping_layer = {
            "status": "pass",
            "source": "explicit_teacher_edge_map",
            "edge_map": dict(sorted(teacher_edge_map.items())),
        }
    road_layer = build_internal_movement_owner_road_connectivity_parity_audit(
        teacher_net_file,
        candidate_net_file,
        owner_id=owner_id,
        teacher_edge_map=teacher_edge_map,
    )
    teacher_signature = build_connection_signature(teacher_net_file, owner_id)
    candidate_signature = build_connection_signature(candidate_net_file, candidate_owner_id)
    junction_layer = _compare_owner_connection_signatures(teacher_signature, candidate_signature)
    pedestrian_layer = compare_pedestrian_crossing_signatures(
        teacher_net_file,
        candidate_net_file,
        owner_id,
        candidate_owner_id,
        teacher_edge_map=teacher_edge_map,
    )
    if _has_tls_semantics(teacher_net_file, owner_id) or _has_tls_semantics(candidate_net_file, candidate_owner_id):
        tls_layer = compare_tls_movement_signatures(
            teacher_net_file,
            candidate_net_file,
            owner_id,
            candidate_owner_id,
            teacher_edge_map=teacher_edge_map,
            teacher_internal_scope_id=owner_id,
            candidate_internal_scope_id=candidate_owner_id,
        )
    else:
        tls_layer = {"status": "skipped", "reason": "no_tls_semantics_for_owner"}

    layer_statuses = {
        "edge_mapping": str(edge_mapping_layer.get("status", "")),
        "road_connectivity": str(road_layer.get("status", "")),
        "junction_connection": str(junction_layer.get("status", "")),
        "pedestrian_crossing": str(pedestrian_layer.get("status", "")),
        "tls_movement": str(tls_layer.get("status", "")),
    }
    report = {
        "status": "pass" if all(status in {"pass", "skipped"} for status in layer_statuses.values()) else "fail",
        "claim_status": "diagnostic-demo",
        "teacher_net_file": str(teacher_net_file),
        "candidate_net_file": str(candidate_net_file),
        "owner_id": owner_id,
        "candidate_owner_id": candidate_owner_id,
        "teacher_edge_map": dict(sorted(teacher_edge_map.items())),
        "layer_statuses": layer_statuses,
        "edge_mapping_layer": edge_mapping_layer,
        "road_connectivity_layer": road_layer,
        "junction_connection_layer": junction_layer,
        "pedestrian_crossing_layer": pedestrian_layer,
        "tls_movement_layer": tls_layer,
    }
    if source_osm_file is not None:
        report["source_coverage_layer"] = build_teacher_source_osm_coverage(
            teacher_net_file,
            source_osm_file,
            owner_id=owner_id,
        )
    return report


def build_teacher_source_osm_coverage(
    teacher_net_file: Path,
    source_osm_file: Path,
    *,
    owner_id: str,
) -> dict[str, Any]:
    teacher_root = ET.parse(teacher_net_file).getroot()
    source_way_ids = _source_osm_way_ids(source_osm_file)
    rows = []
    for edge_id, direction in sorted(_owner_external_approach_edges(teacher_root, owner_id).items()):
        way_id = _teacher_edge_source_way_id(edge_id)
        status = (
            "synthetic_or_non_osm_edge"
            if not way_id
            else ("source_way_present" if way_id in source_way_ids else "source_way_missing")
        )
        rows.append(
            {
                "edge_id": edge_id,
                "direction": direction,
                "source_way_id": way_id,
                "status": status,
            }
        )
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "teacher_net_file": str(teacher_net_file),
        "source_osm_file": str(source_osm_file),
        "owner_id": owner_id,
        "status_counts": dict(sorted(Counter(row["status"] for row in rows).items())),
        "teacher_edges": rows,
    }


def _source_osm_way_ids(source_osm_file: Path) -> set[str]:
    opener = gzip.open if source_osm_file.suffix.lower() == ".gz" else open
    with opener(source_osm_file, "rt", encoding="utf-8") as handle:
        root = ET.parse(handle).getroot()
    return {way.attrib["id"] for way in root.findall("way") if way.attrib.get("id")}


def _teacher_edge_source_way_id(edge_id: str) -> str:
    root = edge_id.lstrip("-").split("#", 1)[0]
    return root if root.isdigit() else ""


def _owner_external_approach_edges(root: ET.Element, owner_id: str) -> dict[str, str]:
    edges = {}
    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id", "")
        if not edge_id or edge_id.startswith(":") or edge.attrib.get("function") == "internal":
            continue
        if edge.attrib.get("to", "") == owner_id:
            edges[edge_id] = "incoming"
        elif edge.attrib.get("from", "") == owner_id:
            edges[edge_id] = "outgoing"
    return edges


def build_connection_signature(net_file: Path, junction_id: str) -> dict[str, Any]:
    root = ET.parse(net_file).getroot()
    plain_edges = {
        edge.attrib["id"]: edge
        for edge in root.findall("edge")
        if edge.attrib.get("id")
        and not edge.attrib["id"].startswith(":")
        and edge.attrib.get("function") != "internal"
    }
    incoming = {edge_id for edge_id, edge in plain_edges.items() if edge.attrib.get("to") == junction_id}
    outgoing = {edge_id for edge_id, edge in plain_edges.items() if edge.attrib.get("from") == junction_id}
    internal_prefix = f":{junction_id}_"
    target_internal_edges = [
        edge
        for edge in root.findall("edge")
        if edge.attrib.get("id", "").startswith(internal_prefix)
    ]

    records = []
    category_counts: Counter[str] = Counter()
    for connection in root.findall("connection"):
        source = connection.attrib.get("from", "")
        target = connection.attrib.get("to", "")
        via = connection.attrib.get("via", "")
        if not _is_related(source, target, via, incoming, outgoing, internal_prefix):
            continue
        category = _connection_category(source, target, incoming, outgoing, internal_prefix)
        category_counts[category] += 1
        record = {
            "category": category,
            "from": source,
            "to": target,
            "fromLane": connection.attrib.get("fromLane", ""),
            "toLane": connection.attrib.get("toLane", ""),
            "dir": connection.attrib.get("dir", ""),
            "state": connection.attrib.get("state", ""),
            "via": via,
            "tl": connection.attrib.get("tl", ""),
            "linkIndex": connection.attrib.get("linkIndex", ""),
        }
        for attr in CONNECTION_RECORD_FIELDS:
            record.setdefault(attr, connection.attrib.get(attr, ""))
        records.append(record)

    top_external = [record for record in records if record["category"] == "top_external"]
    top_external_turnaround = [record for record in top_external if _is_turnaround_record(record)]
    top_external_non_turnaround = [record for record in top_external if not _is_turnaround_record(record)]
    controlled_links = [record for record in records if record["tl"] and record["linkIndex"]]
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "net_file": str(net_file),
        "junction_id": junction_id,
        "incoming_edges": sorted(incoming),
        "outgoing_edges": sorted(outgoing),
        "category_counts": dict(category_counts),
        "top_external_connection_count": len(top_external),
        "top_external_pair_count": len({(record["from"], record["to"]) for record in top_external}),
        "top_external_dir_counts": dict(Counter(record["dir"] or "blank" for record in top_external)),
        "top_external_turnaround_connection_count": len(top_external_turnaround),
        "top_external_non_turnaround_connection_count": len(top_external_non_turnaround),
        "controlled_link_count": len(controlled_links),
        "crossing_count": sum(1 for edge in target_internal_edges if edge.attrib.get("function") == "crossing"),
        "walkingarea_count": sum(1 for edge in target_internal_edges if edge.attrib.get("function") == "walkingarea"),
        "connection_records": records,
    }


def write_connection_signature(signature: dict[str, Any], output_dir: Path, prefix: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    signature_file = output_dir / f"{prefix}_connection_signature.json"
    records_file = output_dir / f"{prefix}_connection_records_layered.csv"
    top_external_file = output_dir / f"{prefix}_top_external_connections.csv"

    records = list(signature.get("connection_records", []) or [])
    signature_file.write_text(json.dumps(signature, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(
        records_file,
        CONNECTION_RECORD_FIELDS,
        records,
    )
    _write_csv(
        top_external_file,
        [field for field in CONNECTION_RECORD_FIELDS if field != "category"],
        [record for record in records if record.get("category") == "top_external"],
    )
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "signature_file": str(signature_file),
        "records_file": str(records_file),
        "top_external_file": str(top_external_file),
    }


def compare_tls_movement_signatures(
    teacher_net_file: Path,
    candidate_net_file: Path,
    teacher_tls_id: str,
    candidate_tls_id: str,
    *,
    teacher_edge_map: dict[str, str] | None = None,
    teacher_internal_scope_id: str | None = None,
    candidate_internal_scope_id: str | None = None,
) -> dict[str, Any]:
    teacher_root = ET.parse(teacher_net_file).getroot()
    candidate_root = ET.parse(candidate_net_file).getroot()
    teacher_signatures = Counter(
        _tls_movement_signatures(
            teacher_root,
            teacher_tls_id,
            teacher_edge_map,
            internal_scope_id=teacher_internal_scope_id,
        )
    )
    candidate_signatures = Counter(
        _tls_movement_signatures(
            candidate_root,
            candidate_tls_id,
            internal_scope_id=candidate_internal_scope_id,
        )
    )
    teacher_only = teacher_signatures - candidate_signatures
    candidate_only = candidate_signatures - teacher_signatures

    teacher_phase_states = _tls_phase_states(teacher_root, teacher_tls_id)
    candidate_phase_states = _tls_phase_states(candidate_root, candidate_tls_id)
    movement_equal = not teacher_only and not candidate_only
    phase_equal = teacher_phase_states == candidate_phase_states
    return {
        "status": "pass" if movement_equal and phase_equal else "fail",
        "claim_status": "diagnostic-demo",
        "teacher_net_file": str(teacher_net_file),
        "candidate_net_file": str(candidate_net_file),
        "teacher_tls_id": teacher_tls_id,
        "candidate_tls_id": candidate_tls_id,
        "teacher_edge_map": dict(sorted((teacher_edge_map or {}).items())),
        "normalized_internal_ids": True,
        "scoped_internal_ids": {
            "teacher": teacher_internal_scope_id or "",
            "candidate": candidate_internal_scope_id or "",
        },
        "compared_fields": TLS_MOVEMENT_SIGNATURE_FIELDS,
        "teacher_connection_count": teacher_signatures.total(),
        "candidate_connection_count": candidate_signatures.total(),
        "movement_signature_equal_after_internal_id_normalization": movement_equal,
        "teacher_only_normalized_movement_signatures": _counter_elements(teacher_only),
        "candidate_only_normalized_movement_signatures": _counter_elements(candidate_only),
        "teacher_phase_states": teacher_phase_states,
        "candidate_phase_states": candidate_phase_states,
        "teacher_phase_count": len(teacher_phase_states),
        "candidate_phase_count": len(candidate_phase_states),
        "phase_state_lengths": {
            "teacher": [len(state) for state in teacher_phase_states],
            "candidate": [len(state) for state in candidate_phase_states],
        },
        "tl_logic_phase_states_equal": phase_equal,
    }


def compare_pedestrian_crossing_signatures(
    teacher_net_file: Path,
    candidate_net_file: Path,
    teacher_owner_id: str,
    candidate_owner_id: str,
    *,
    teacher_edge_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    teacher_root = ET.parse(teacher_net_file).getroot()
    candidate_root = ET.parse(candidate_net_file).getroot()
    teacher_edge_signatures, teacher_connection_signatures = _pedestrian_crossing_signatures(
        teacher_root,
        teacher_owner_id,
        teacher_edge_map,
    )
    candidate_edge_signatures, candidate_connection_signatures = _pedestrian_crossing_signatures(
        candidate_root,
        candidate_owner_id,
        None,
    )
    teacher_edges = Counter(teacher_edge_signatures)
    candidate_edges = Counter(candidate_edge_signatures)
    teacher_connections = Counter(teacher_connection_signatures)
    candidate_connections = Counter(candidate_connection_signatures)
    teacher_only_edges = teacher_edges - candidate_edges
    candidate_only_edges = candidate_edges - teacher_edges
    teacher_only_connections = teacher_connections - candidate_connections
    candidate_only_connections = candidate_connections - teacher_connections
    equal = (
        not teacher_only_edges
        and not candidate_only_edges
        and not teacher_only_connections
        and not candidate_only_connections
    )
    return {
        "status": "pass" if equal else "fail",
        "claim_status": "diagnostic-demo",
        "teacher_net_file": str(teacher_net_file),
        "candidate_net_file": str(candidate_net_file),
        "teacher_owner_id": teacher_owner_id,
        "candidate_owner_id": candidate_owner_id,
        "teacher_edge_map": dict(sorted((teacher_edge_map or {}).items())),
        "normalized_internal_ids": True,
        "compared_connection_fields": PEDESTRIAN_CONNECTION_SIGNATURE_FIELDS,
        "teacher_edge_signature_count": teacher_edges.total(),
        "candidate_edge_signature_count": candidate_edges.total(),
        "teacher_connection_signature_count": teacher_connections.total(),
        "candidate_connection_signature_count": candidate_connections.total(),
        "teacher_only_normalized_edge_signatures": _counter_elements(teacher_only_edges),
        "candidate_only_normalized_edge_signatures": _counter_elements(candidate_only_edges),
        "teacher_only_normalized_connection_signatures": _counter_elements(teacher_only_connections),
        "candidate_only_normalized_connection_signatures": _counter_elements(candidate_only_connections),
    }


def _pedestrian_crossing_signatures(
    root: ET.Element,
    owner_id: str,
    edge_map: dict[str, str] | None,
) -> tuple[list[str], list[str]]:
    internal_prefix = f":{owner_id}_"
    pedestrian_edge_ids = {
        edge.attrib["id"]
        for edge in root.findall("edge")
        if edge.attrib.get("id", "").startswith(internal_prefix)
        and edge.attrib.get("function") in PEDESTRIAN_EDGE_FUNCTIONS
    }
    pedestrian_edge_signatures = [
        _pedestrian_edge_signature(edge, owner_id)
        for edge in root.findall("edge")
        if edge.attrib.get("id") in pedestrian_edge_ids
    ]
    pedestrian_connection_signatures = []
    for connection in root.findall("connection"):
        source = connection.attrib.get("from", "")
        target = connection.attrib.get("to", "")
        via = connection.attrib.get("via", "")
        if not (
            source in pedestrian_edge_ids
            or target in pedestrian_edge_ids
            or via.startswith(internal_prefix)
            and _edge_id_from_lane_id(via) in pedestrian_edge_ids
        ):
            continue
        fields = {
            field: _normalize_pedestrian_crossing_value(
                field,
                connection.attrib.get(field, ""),
                owner_id,
                edge_map,
            )
            for field in PEDESTRIAN_CONNECTION_SIGNATURE_FIELDS
        }
        pedestrian_connection_signatures.append(
            "|".join(f"{field}={fields[field]}" for field in PEDESTRIAN_CONNECTION_SIGNATURE_FIELDS)
        )
    return sorted(pedestrian_edge_signatures), sorted(pedestrian_connection_signatures)


def _pedestrian_edge_signature(edge: ET.Element, owner_id: str) -> str:
    lane_signatures = []
    for lane in edge.findall("lane"):
        lane_signatures.append(
            "|".join(
                (
                    f"index={lane.attrib.get('index', '')}",
                    f"allow={lane.attrib.get('allow', '')}",
                    f"disallow={lane.attrib.get('disallow', '')}",
                )
            )
        )
    return "|".join(
        (
            f"id={_normalize_tls_internal_id(edge.attrib.get('id', ''), owner_id)}",
            f"function={edge.attrib.get('function', '')}",
            f"lanes={';'.join(sorted(lane_signatures))}",
        )
    )


def _normalize_pedestrian_crossing_value(
    field: str,
    value: str,
    owner_id: str,
    edge_map: dict[str, str] | None,
) -> str:
    if field in {"from", "to"}:
        if value.startswith(":"):
            return _normalize_tls_internal_id(value, owner_id)
        return (edge_map or {}).get(value, value)
    if field == "via":
        return _normalize_tls_internal_id(value, owner_id)
    if field == "tl" and value == owner_id:
        return "TARGET_TLS"
    return value


def _edge_id_from_lane_id(lane_id: str) -> str:
    if lane_id.startswith(":"):
        parts = lane_id.rsplit("_", 1)
        return parts[0] if len(parts) == 2 else lane_id
    return lane_id.rsplit("_", 1)[0] if "_" in lane_id else lane_id


def _is_related(
    source: str,
    target: str,
    via: str,
    incoming: set[str],
    outgoing: set[str],
    internal_prefix: str,
) -> bool:
    return (
        via.startswith(internal_prefix)
        or source in incoming
        or target in outgoing
        or source.startswith(internal_prefix)
        or target.startswith(internal_prefix)
    )


def _connection_category(
    source: str,
    target: str,
    incoming: set[str],
    outgoing: set[str],
    internal_prefix: str,
) -> str:
    if source in incoming and target in outgoing:
        return "top_external"
    if source in incoming:
        return "incoming_to_internal_or_other"
    if target in outgoing:
        return "internal_or_other_to_outgoing"
    if source.startswith(internal_prefix) or target.startswith(internal_prefix):
        return "internal_continuation"
    return "other_related"


def _is_turnaround_record(record: dict[str, Any]) -> bool:
    return str(record.get("dir", "")).lower() == TURNAROUND_DIR


def _compare_owner_connection_signatures(
    teacher_signature: dict[str, Any],
    candidate_signature: dict[str, Any],
) -> dict[str, Any]:
    fields = (
        "top_external_connection_count",
        "top_external_non_turnaround_connection_count",
        "top_external_turnaround_connection_count",
        "controlled_link_count",
        "crossing_count",
        "walkingarea_count",
    )
    deltas = {
        field: int(candidate_signature.get(field, 0)) - int(teacher_signature.get(field, 0))
        for field in fields
    }
    turnaround_only = (
        int(teacher_signature.get("top_external_non_turnaround_connection_count", 0)) > 0
        and int(candidate_signature.get("top_external_non_turnaround_connection_count", 0)) == 0
        and int(candidate_signature.get("top_external_turnaround_connection_count", 0)) > 0
    )
    return {
        "status": "fail" if any(deltas.values()) or turnaround_only else "pass",
        "teacher": {field: teacher_signature.get(field, 0) for field in fields},
        "candidate": {field: candidate_signature.get(field, 0) for field in fields},
        "count_delta": deltas,
        "candidate_turnaround_only_top_external": turnaround_only,
    }


def _has_tls_semantics(net_file: Path, tls_id: str) -> bool:
    root = ET.parse(net_file).getroot()
    return root.find(f"tlLogic[@id='{tls_id}']") is not None or any(
        connection.attrib.get("tl") == tls_id for connection in root.findall("connection")
    )


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _tls_movement_signatures(
    root: ET.Element,
    tls_id: str,
    edge_map: dict[str, str] | None = None,
    *,
    internal_scope_id: str | None = None,
) -> list[str]:
    signatures = []
    normalize_internal_id = internal_scope_id or tls_id
    internal_scope_prefix = f":{internal_scope_id}_" if internal_scope_id else ""
    for connection in root.findall("connection"):
        if connection.attrib.get("tl") != tls_id:
            continue
        if internal_scope_prefix and not connection.attrib.get("via", "").startswith(internal_scope_prefix):
            continue
        fields = {
            field: _normalize_tls_movement_value(field, connection.attrib.get(field, ""), normalize_internal_id, edge_map)
            for field in TLS_MOVEMENT_SIGNATURE_FIELDS
        }
        signatures.append("|".join(f"{field}={fields[field]}" for field in TLS_MOVEMENT_SIGNATURE_FIELDS))
    return signatures


def _normalize_tls_movement_value(
    field: str,
    value: str,
    tls_id: str,
    edge_map: dict[str, str] | None,
) -> str:
    if field in {"from", "to"} and edge_map and value and not value.startswith(":"):
        return edge_map.get(value, value)
    return _normalize_tls_internal_id(value, tls_id)


def _normalize_tls_internal_id(value: str, tls_id: str) -> str:
    prefix = f":{tls_id}"
    if value.startswith(prefix):
        return f":TARGET{value[len(prefix):]}"
    return value


def _tls_phase_states(root: ET.Element, tls_id: str) -> list[str]:
    states = []
    for tl_logic in root.findall("tlLogic"):
        if tl_logic.attrib.get("id") != tls_id:
            continue
        states.extend(phase.attrib.get("state", "") for phase in tl_logic.findall("phase"))
    return states


def _counter_elements(counter: Counter[str]) -> list[str]:
    return sorted(counter.elements())

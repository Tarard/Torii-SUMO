from __future__ import annotations

import csv
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
TURNAROUND_DIR = "t"


def build_teacher_guided_owner_semantics_probe(
    teacher_net_file: Path,
    candidate_net_file: Path,
    *,
    owner_id: str,
    candidate_owner_id: str | None = None,
    teacher_edge_map: dict[str, str] | None = None,
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
        "tls_movement": str(tls_layer.get("status", "")),
    }
    return {
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
        "tls_movement_layer": tls_layer,
    }


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

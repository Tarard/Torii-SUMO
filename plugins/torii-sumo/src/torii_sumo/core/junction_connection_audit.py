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
) -> dict[str, Any]:
    teacher_root = ET.parse(teacher_net_file).getroot()
    candidate_root = ET.parse(candidate_net_file).getroot()
    teacher_signatures = Counter(_tls_movement_signatures(teacher_root, teacher_tls_id))
    candidate_signatures = Counter(_tls_movement_signatures(candidate_root, candidate_tls_id))
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
        "normalized_internal_ids": True,
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


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _tls_movement_signatures(root: ET.Element, tls_id: str) -> list[str]:
    signatures = []
    for connection in root.findall("connection"):
        if connection.attrib.get("tl") != tls_id:
            continue
        fields = {
            field: _normalize_tls_internal_id(connection.attrib.get(field, ""), tls_id)
            for field in TLS_MOVEMENT_SIGNATURE_FIELDS
        }
        signatures.append("|".join(f"{field}={fields[field]}" for field in TLS_MOVEMENT_SIGNATURE_FIELDS))
    return signatures


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

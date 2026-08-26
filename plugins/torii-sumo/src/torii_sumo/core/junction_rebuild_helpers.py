"""Dependency-free leaf helpers extracted from ``junction_rebuild_candidate``.

These helpers have no calls into the original module or ``junction_rebuild_tail``.
The original module re-exports them for compatibility.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


APPROACH_INTEGRITY_FAILURE_FIELDS = {
    "approach_edge_signature_mismatch_count",
    "approach_endpoint_signature_mismatch_count",
    "incoming_vehicle_edge_count",
    "outgoing_vehicle_edge_count",
}

BOUNDARY_EDGE_OPERATIONAL_ATTRS = (
    "type",
    "priority",
    "name",
    "spreadType",
    "allow",
    "disallow",
    "speed",
    "width",
)

BOUNDARY_LANE_OPERATIONAL_ATTRS = (
    "speed",
    "width",
    "allow",
    "disallow",
    "endOffset",
    "acceleration",
    "changeLeft",
    "changeRight",
    "stopOffset",
)

TURNAROUND_DIR = "t"

def _plain_crossing_node_id(
    default_junction_id: str,
    crossing_edges: list[str],
    edge_endpoints: dict[str, tuple[str, str]],
    crossing_node_ids: set[str],
) -> str:
    if not crossing_edges or not edge_endpoints or not crossing_node_ids:
        return default_junction_id
    shared_node_ids: set[str] | None = None
    for edge_id in crossing_edges:
        endpoints = set(edge_endpoints.get(edge_id, ())) & crossing_node_ids
        if not endpoints:
            return default_junction_id
        shared_node_ids = endpoints if shared_node_ids is None else shared_node_ids & endpoints
        if not shared_node_ids:
            return default_junction_id
    return sorted(shared_node_ids)[0] if shared_node_ids else default_junction_id

def _teacher_to_candidate_delta(root: ET.Element, junction_id: str, teacher_junction: object) -> tuple[float, float]:
    candidate_junction = root.find(f"junction[@id='{junction_id}']")
    if candidate_junction is None or not isinstance(teacher_junction, dict):
        return 0.0, 0.0
    try:
        return (
            float(candidate_junction.attrib.get("x", "0")) - float(str(teacher_junction.get("x", "0"))),
            float(candidate_junction.attrib.get("y", "0")) - float(str(teacher_junction.get("y", "0"))),
        )
    except ValueError:
        return 0.0, 0.0

def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value or [] if str(item)]

def _report_used_unrestored_normalized_replay(report: dict[str, Any]) -> bool:
    target_internal_normalize = report.get("target_internal_normalize", {})
    if not isinstance(target_internal_normalize, dict):
        return False
    unrestored_sumo_load = target_internal_normalize.get("unrestored_sumo_load", {})
    return isinstance(unrestored_sumo_load, dict) and unrestored_sumo_load.get("status") == "pass"

def _net_contains_normal_junctions(net_file: Path, junction_ids: set[str]) -> bool:
    if not junction_ids:
        return True
    try:
        root = ET.parse(net_file).getroot()
    except (OSError, ET.ParseError):
        return False
    net_junction_ids = {
        junction.attrib["id"]
        for junction in root.findall("junction")
        if junction.attrib.get("id") and not junction.attrib["id"].startswith(":")
    }
    return junction_ids <= net_junction_ids

def _teacher_pattern_metric_is_positive(pattern_key: str, metric: str) -> bool:
    prefix = f"{metric}="
    for part in pattern_key.split("|"):
        if not part.startswith(prefix):
            continue
        for token in part[len(prefix) :].replace("/", ":").split(":"):
            try:
                if int(token) > 0:
                    return True
            except ValueError:
                continue
    return False

def _prune_plain_tls_against_teacher(
    *,
    teacher_net_file: Path,
    node_file: Path,
    connection_file: Path,
    tllogic_file: Path | None,
) -> dict[str, object]:
    """Keep sequential plain inputs from reviving TLS absent in the teacher.

    netconvert plain export can materialize a stale traffic-light program from
    an intermediate candidate.  That stale program later makes a valid join
    fail because the joined source junction is no longer a controller.  The
    teacher reference is authoritative for this cleanup; the main candidate
    network is not edited here.
    """
    if not all(path.exists() for path in (teacher_net_file, node_file, connection_file)):
        return {"status": "skipped", "reason": "plain_input_missing", "demoted_junction_count": 0}
    try:
        teacher_root = ET.parse(teacher_net_file).getroot()
        node_tree = ET.parse(node_file)
        connection_tree = ET.parse(connection_file)
        tllogic_tree = ET.parse(tllogic_file) if tllogic_file is not None and tllogic_file.exists() else None
    except (OSError, ET.ParseError) as exc:
        return {"status": "fail", "reason": f"parse_error: {exc}", "demoted_junction_count": 0}

    teacher_junction_types = {
        str(junction.attrib.get("id", "")): str(junction.attrib.get("type", ""))
        for junction in teacher_root.findall("junction")
        if junction.attrib.get("id")
    }
    teacher_tls_ids = {
        junction_id
        for junction_id, junction_type in teacher_junction_types.items()
        if junction_type.startswith("traffic_light")
    }
    for junction in teacher_root.findall("junction"):
        if not str(junction.attrib.get("type", "")).startswith("traffic_light"):
            continue
        teacher_tls_ids.update(str(item) for item in junction.attrib.get("tl", "").split() if str(item))
    teacher_tls_ids.update(
        str(logic.attrib.get("id", ""))
        for logic in teacher_root.findall("tlLogic")
        if logic.attrib.get("id")
    )

    demoted_junction_ids: list[str] = []
    invalid_tls_ids: set[str] = set()
    for node in node_tree.getroot().findall("node"):
        node_id = str(node.attrib.get("id", ""))
        if not node_id or not str(node.attrib.get("type", "")).startswith("traffic_light"):
            continue
        node_tls_ids = {node_id, *[str(item) for item in node.attrib.get("tl", "").split() if str(item)]}
        teacher_type = teacher_junction_types.get(node_id, "")
        valid = teacher_type.startswith("traffic_light") and bool(node_tls_ids & teacher_tls_ids)
        if valid:
            continue
        invalid_tls_ids.update(node_tls_ids)
        node.set("type", teacher_type or "priority")
        node.attrib.pop("tl", None)
        node.attrib.pop("tlType", None)
        demoted_junction_ids.append(node_id)

    removed_tllogic_ids: list[str] = []
    removed_tllogic_connection_count = 0
    if tllogic_tree is not None:
        tllogic_root = tllogic_tree.getroot()
        for child in list(tllogic_root):
            child_tls_id = str(child.attrib.get("id", child.attrib.get("tl", "")))
            if child_tls_id and child_tls_id in invalid_tls_ids:
                tllogic_root.remove(child)
                if child.tag == "tlLogic":
                    removed_tllogic_ids.append(child_tls_id)
                else:
                    removed_tllogic_connection_count += 1

    uncontrolled_connection_count = 0
    for connection in connection_tree.getroot().findall("connection"):
        tls_id = str(connection.attrib.get("tl", ""))
        if not tls_id or tls_id not in invalid_tls_ids:
            continue
        for attr in ("tl", "linkIndex", "linkIndex2"):
            connection.attrib.pop(attr, None)
        connection.set("uncontrolled", "true")
        uncontrolled_connection_count += 1

    if demoted_junction_ids:
        ET.indent(node_tree.getroot(), space="    ")
        node_tree.write(node_file, encoding="utf-8", xml_declaration=True)
    if tllogic_tree is not None and (removed_tllogic_ids or removed_tllogic_connection_count):
        ET.indent(tllogic_tree.getroot(), space="    ")
        tllogic_tree.write(tllogic_file, encoding="utf-8", xml_declaration=True)
    if uncontrolled_connection_count:
        ET.indent(connection_tree.getroot(), space="    ")
        connection_tree.write(connection_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "demoted_junction_count": len(demoted_junction_ids),
        "demoted_junction_ids": sorted(demoted_junction_ids),
        "removed_tllogic_count": len(removed_tllogic_ids),
        "removed_tllogic_ids": sorted(set(removed_tllogic_ids)),
        "removed_tllogic_connection_count": removed_tllogic_connection_count,
        "uncontrolled_connection_count": uncontrolled_connection_count,
    }

def _int_count(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

def _split_cluster_member_residuals(
    teacher_context: dict[str, object],
    candidate_context: dict[str, object],
    *,
    teacher_join_groups_by_cluster: dict[str, list[str]] | None = None,
) -> list[dict[str, object]]:
    candidate_junction_ids = {str(item) for item in candidate_context.get("junction_ids", []) or [] if str(item)}
    residuals: list[dict[str, object]] = []
    for teacher_junction_id in teacher_context.get("junction_ids", []) or []:
        teacher_junction_id = str(teacher_junction_id)
        if not teacher_junction_id.startswith("cluster_"):
            continue
        member_ids = list(
            (teacher_join_groups_by_cluster or {}).get(teacher_junction_id, [])
        )
        if not member_ids:
            member_ids = [item for item in teacher_junction_id.removeprefix("cluster_").split("_") if item]
        residual_members = sorted(member_id for member_id in member_ids if member_id in candidate_junction_ids)
        if residual_members:
            residuals.append(
                {
                    "teacher_cluster_junction_id": teacher_junction_id,
                    "candidate_member_junction_ids": residual_members,
                }
            )
    return residuals

def _junction_within_radius(junction: ET.Element, *, center: tuple[float, float], radius_m: float) -> bool:
    try:
        x = float(junction.attrib.get("x", ""))
        y = float(junction.attrib.get("y", ""))
    except ValueError:
        return False
    return math.hypot(x - center[0], y - center[1]) <= radius_m

def _connection_edges_are_adjacent(connection: ET.Element, edge_endpoints: dict[str, tuple[str, str]]) -> bool:
    source = edge_endpoints.get(connection.attrib.get("from", ""))
    target = edge_endpoints.get(connection.attrib.get("to", ""))
    return bool(source and target and source[1] == target[0])

def _write_join_scope_connection_file(
    edge_file: Path,
    connection_file: Path,
    join_node_ids: set[str],
    output_file: Path,
    *,
    drop_edge_ids: set[str] | None = None,
) -> tuple[Path, int, list[str]]:
    drop_edge_ids = drop_edge_ids or set()
    if not join_node_ids and not drop_edge_ids:
        return connection_file, 0, []
    incident_edge_ids = {
        edge.attrib["id"]
        for edge in ET.parse(edge_file).getroot().findall("edge")
        if edge.attrib.get("id") and (edge.attrib.get("from") in join_node_ids or edge.attrib.get("to") in join_node_ids)
    }
    if not incident_edge_ids and not drop_edge_ids:
        return connection_file, 0, []
    connection_root = ET.parse(connection_file).getroot()
    filtered_root = ET.Element(connection_root.tag, connection_root.attrib)
    dropped_edge_ids = []
    for connection in connection_root:
        if connection.tag == "crossing":
            crossing_edge_ids = set(connection.attrib.get("edges", "").split())
            if crossing_edge_ids & drop_edge_ids:
                dropped_edge_ids.extend(sorted(edge_id for edge_id in crossing_edge_ids & drop_edge_ids if edge_id))
                continue
        connection_edge_ids = {connection.attrib.get("from", ""), connection.attrib.get("to", "")}
        if connection.tag == "connection" and connection_edge_ids & drop_edge_ids:
            dropped_edge_ids.extend(sorted(edge_id for edge_id in connection_edge_ids & drop_edge_ids if edge_id))
            continue
        if (
            connection.tag == "connection"
            and connection.attrib.get("from", "") in incident_edge_ids
            and not connection.attrib.get("to")
        ):
            dropped_edge_ids.append(connection.attrib.get("from", ""))
            continue
        filtered_root.append(copy.deepcopy(connection))
    if not dropped_edge_ids:
        return connection_file, 0, []
    ET.indent(filtered_root, space="    ")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(filtered_root).write(output_file, encoding="utf-8", xml_declaration=True)
    return output_file, len(dropped_edge_ids), dropped_edge_ids

def _prune_plain_node_controlled_inner_edges(
    node_file: Path,
    drop_edge_ids: set[str],
) -> dict[str, object]:
    """Remove absorbed join-internal edges from plain-node TLS hints.

    ``netconvert --plain-output-prefix`` repeats ``controlledInner`` on every
    node that belongs to a joined controller.  Once a physical micro-edge is
    absorbed by an explicit junction join, leaving that id in the staged node
    file can revive a reference to an edge that no longer exists.
    """

    if not drop_edge_ids:
        return {
            "status": "pass",
            "updated_node_count": 0,
            "removed_edge_reference_count": 0,
            "removed_edge_ids": [],
        }
    try:
        node_tree = ET.parse(node_file)
    except (ET.ParseError, OSError) as exc:
        return {
            "status": "fail",
            "updated_node_count": 0,
            "removed_edge_reference_count": 0,
            "removed_edge_ids": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    updated_node_count = 0
    removed_edge_reference_count = 0
    removed_edge_ids: list[str] = []
    for node in node_tree.getroot().findall("node"):
        raw_value = node.attrib.get("controlledInner", "")
        if not raw_value:
            continue
        edge_ids = raw_value.split()
        kept = [edge_id for edge_id in edge_ids if edge_id not in drop_edge_ids]
        removed = [edge_id for edge_id in edge_ids if edge_id in drop_edge_ids]
        if not removed:
            continue
        updated_node_count += 1
        removed_edge_reference_count += len(removed)
        removed_edge_ids.extend(removed)
        if kept:
            node.set("controlledInner", " ".join(kept))
        else:
            node.attrib.pop("controlledInner", None)

    if updated_node_count:
        ET.indent(node_tree.getroot(), space="    ")
        node_tree.write(node_file, encoding="utf-8", xml_declaration=True)
    return {
        "status": "pass",
        "updated_node_count": updated_node_count,
        "removed_edge_reference_count": removed_edge_reference_count,
        "removed_edge_ids": sorted(set(removed_edge_ids)),
    }

def _write_join_scope_tllogic_file(
    tllogic_file: Path,
    drop_edge_ids: set[str],
    output_file: Path,
) -> tuple[Path, int, list[str]]:
    """Stage TLS definitions without bindings to absorbed micro-edges."""

    if not drop_edge_ids:
        return tllogic_file, 0, []
    tllogic_tree = ET.parse(tllogic_file)
    root = tllogic_tree.getroot()
    dropped_edge_ids: list[str] = []
    for child in list(root):
        if child.tag != "connection":
            continue
        connection_edge_ids = {
            child.attrib.get("from", ""),
            child.attrib.get("to", ""),
        }
        removed = sorted(
            edge_id
            for edge_id in connection_edge_ids & drop_edge_ids
            if edge_id
        )
        if not removed:
            continue
        root.remove(child)
        dropped_edge_ids.extend(removed)

    if not dropped_edge_ids:
        return tllogic_file, 0, []
    ET.indent(root, space="    ")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    tllogic_tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return output_file, len(dropped_edge_ids), dropped_edge_ids

def _edge_file_ids(edge_file: Path) -> set[str]:
    try:
        return {
            edge.attrib["id"]
            for edge in ET.parse(edge_file).getroot().findall("edge")
            if edge.attrib.get("id")
        }
    except (ET.ParseError, OSError):
        return set()

def _blocking_sequential_overlap_edge_ids(
    edge_ids: set[str],
    edge_file: Path,
    candidate_node_ids: set[str],
    applied_node_ids: set[str],
) -> list[str]:
    if not edge_ids:
        return []
    try:
        edges = {
            edge.attrib["id"]: edge
            for edge in ET.parse(edge_file).getroot().findall("edge")
            if edge.attrib.get("id")
        }
    except (ET.ParseError, OSError):
        return sorted(edge_ids)
    blocking = []
    for edge_id in sorted(edge_ids):
        edge = edges.get(edge_id)
        if edge is None:
            blocking.append(edge_id)
            continue
        endpoints = {edge.attrib.get("from", ""), edge.attrib.get("to", "")}
        if endpoints & candidate_node_ids and endpoints & applied_node_ids:
            continue
        blocking.append(edge_id)
    return blocking

def _plain_node_ids(node_file: Path) -> set[str]:
    try:
        return {
            node.attrib["id"]
            for node in ET.parse(node_file).getroot().findall("node")
            if node.attrib.get("id")
        }
    except (ET.ParseError, OSError):
        return set()

def _teacher_boundary_edge_has_target_junction(teacher_net_file: Path, teacher_junction_id: str, edge_id: str) -> bool:
    try:
        edge = ET.parse(teacher_net_file).getroot().find(f"edge[@id='{edge_id}']")
    except (ET.ParseError, OSError):
        return False
    return edge is not None and teacher_junction_id in (edge.attrib.get("from"), edge.attrib.get("to"))

def _opposite_direction_edge_id(edge_id: str) -> str:
    return edge_id[1:] if edge_id.startswith("-") else f"-{edge_id}"

def _edge_family_id(edge_id: str) -> str:
    return edge_id.lstrip("-").split("#", 1)[0]

def _signed_edge_family_id(edge_id: str) -> str:
    return edge_id.split("#", 1)[0]

def _edge_drop_requires_review(edge: ET.Element) -> bool:
    edge_id = edge.attrib.get("id", "")
    if edge_id.startswith(":") or edge.attrib.get("function") in {"internal", "crossing", "walkingarea"}:
        return False
    if edge.attrib.get("type", "").startswith("highway."):
        return True
    vehicle_classes = {
        "passenger",
        "private",
        "bus",
        "coach",
        "truck",
        "trailer",
        "motorcycle",
        "moped",
        "taxi",
        "delivery",
        "emergency",
    }
    for lane in edge.findall("lane"):
        if set(lane.attrib.get("allow", "").split()) & vehicle_classes:
            return True
    return False

def _normalize_joined_junction_ids(value: object) -> set[str]:
    if isinstance(value, (list, tuple, set, frozenset)):
        return {str(item) for item in value if str(item)}
    return {str(value)} if str(value) else set()

def _endpoint_rewrites(approach_endpoint_rebuild_plan: object | None) -> dict[str, tuple[str, str]]:
    if not isinstance(approach_endpoint_rebuild_plan, dict):
        return {}
    rewrites = {}
    for item in approach_endpoint_rebuild_plan.get("edge_rebuilds", []) or []:
        if not isinstance(item, dict):
            continue
        edge_id = str(item.get("edge_id", ""))
        desired_from = str(item.get("desired_from", ""))
        desired_to = str(item.get("desired_to", ""))
        if edge_id and desired_from and desired_to:
            rewrites[edge_id] = (desired_from, desired_to)
    return rewrites

def _semantic_failure_counts(variant_reports: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for report in variant_reports:
        if report.get("expanded_scope_followup_emitted"):
            continue
        gate = report.get("semantic_replay_gate")
        failures = gate.get("failures", []) if isinstance(gate, dict) else []
        for failure in failures:
            if not isinstance(failure, dict):
                continue
            key = f"{failure.get('report', '')}:{failure.get('field', '')}"
            if key != ":":
                counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))

def _plain_edge_endpoints(edge_file: Path) -> dict[str, tuple[str, str]]:
    try:
        root = ET.parse(edge_file).getroot()
    except (ET.ParseError, OSError):
        return {}
    return {
        edge.attrib["id"]: (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
        for edge in root.findall("edge")
        if edge.attrib.get("id")
    }

def _semantic_layer_gate_counts(variant_reports: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for report in variant_reports:
        if report.get("expanded_scope_followup_emitted"):
            continue
        layers = report.get("semantic_layer_gates")
        if not isinstance(layers, dict):
            continue
        for layer_name, layer in layers.items():
            if not isinstance(layer, dict):
                continue
            layer_counts = counts.setdefault(str(layer_name), {"pass": 0, "fail": 0, "failure_count": 0})
            status = "pass" if layer.get("status") == "pass" else "fail"
            layer_counts[status] += 1
            try:
                layer_counts["failure_count"] += int(layer.get("failure_count", 0) or 0)
            except (TypeError, ValueError):
                layer_counts["failure_count"] += 1 if status == "fail" else 0
    return {key: counts[key] for key in sorted(counts)}

def _expand_fragmented_tls_join_scope_candidate(
    candidate: dict[str, Any],
    raw_node_file: Path,
    *,
    max_controller_span_m: float = 120.0,
    max_controller_node_count: int = 20,
) -> dict[str, Any]:
    """Expand a partial OSM signal cluster to its compact shared controller cell."""

    if candidate.get("learned_rule") != "tum_like_topology_fragmented_tls_candidate":
        return candidate
    scope_value = candidate.get("expanded_rebuild_scope", {})
    if not isinstance(scope_value, dict):
        return candidate
    requested_ids = {
        str(value)
        for value in scope_value.get("join_junction_ids", []) or []
        if str(value)
    }
    report: dict[str, object] = {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "requested_join_junction_ids": sorted(requested_ids),
        "automatic_expansion_applied": False,
        "max_controller_span_m": max_controller_span_m,
    }
    if not requested_ids:
        report["reason"] = "no_requested_join_junction_ids"
        return {**candidate, "tls_join_scope_expansion": report}
    try:
        root = ET.parse(raw_node_file).getroot()
    except (ET.ParseError, OSError) as exc:
        report.update(
            {
                "status": "review",
                "reason": "raw_node_file_unreadable",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return {**candidate, "tls_join_scope_expansion": report}

    nodes = {
        str(node.attrib.get("id", "")): node
        for node in root.findall("node")
        if node.attrib.get("id")
    }
    missing_ids = sorted(requested_ids - set(nodes))
    controller_ids = {
        str(nodes[node_id].attrib.get("tl", ""))
        for node_id in requested_ids & set(nodes)
        if nodes[node_id].attrib.get("tl")
    }
    report["missing_requested_join_junction_ids"] = missing_ids
    report["controller_ids"] = sorted(controller_ids)
    if missing_ids or len(controller_ids) != 1:
        report.update(
            {
                "status": "review",
                "reason": "requested join nodes do not resolve to one shared TLS controller",
            }
        )
        return {**candidate, "tls_join_scope_expansion": report}

    controller_id = next(iter(controller_ids))
    controller_node_ids = sorted(
        node_id
        for node_id, node in nodes.items()
        if node.attrib.get("tl", "") == controller_id
    )
    positions = []
    for node_id in controller_node_ids:
        node = nodes[node_id]
        try:
            positions.append((float(node.attrib["x"]), float(node.attrib["y"])))
        except (KeyError, TypeError, ValueError):
            report.update(
                {
                    "status": "review",
                    "reason": "shared TLS controller node lacks finite coordinates",
                    "controller_node_ids": controller_node_ids,
                }
            )
            return {**candidate, "tls_join_scope_expansion": report}
    span_m = max(
        (
            math.hypot(ax - bx, ay - by)
            for index, (ax, ay) in enumerate(positions)
            for bx, by in positions[index + 1 :]
        ),
        default=0.0,
    )
    report.update(
        {
            "controller_node_ids": controller_node_ids,
            "controller_node_count": len(controller_node_ids),
            "controller_span_m": round(span_m, 3),
        }
    )
    if (
        len(controller_node_ids) > max_controller_node_count
        or span_m > max_controller_span_m
    ):
        report.update(
            {
                "status": "review",
                "reason": "shared TLS controller is too broad for automatic physical junction joining",
            }
        )
        return {**candidate, "tls_join_scope_expansion": report}

    expanded_scope = copy.deepcopy(scope_value)
    expanded_scope["join_junction_ids"] = controller_node_ids
    expanded_scope["junction_ids"] = sorted(
        {
            *controller_node_ids,
            *(
                str(value)
                for value in expanded_scope.get("junction_ids", []) or []
                if str(value)
            ),
        }
    )
    added_ids = sorted(set(controller_node_ids) - requested_ids)
    report.update(
        {
            "automatic_expansion_applied": bool(added_ids),
            "added_join_junction_ids": added_ids,
            "expanded_join_junction_ids": controller_node_ids,
            "reason": "compact shared TLS controller cell expanded before physical junction join",
        }
    )
    return {
        **candidate,
        "expanded_rebuild_scope": expanded_scope,
        "tls_join_scope_expansion": report,
    }

def _candidate_connection_mode_scope_ids(
    report: dict[str, object],
) -> tuple[list[str], list[str]]:
    """Return equivalent source/candidate scopes for a differential audit.

    A plain-XML junction join removes several source junction IDs and creates a
    new cluster ID.  Unchanged boundary junctions can also be part of the
    intended edit scope.  Excluding the complete scope on both sides prevents
    those expected identity changes from being mistaken for global collateral
    damage while every other junction remains subject to the regression gate.
    """

    source_ids: set[str] = set()
    matched_ids = report.get("matched_candidate_node_ids", [])
    if isinstance(matched_ids, (list, tuple, set)):
        source_ids.update(str(value) for value in matched_ids if str(value))
    expanded_scope = report.get("expanded_rebuild_scope", {})
    if isinstance(expanded_scope, dict):
        for field in ("junction_ids", "join_junction_ids"):
            values = expanded_scope.get(field, [])
            if isinstance(values, (list, tuple, set)):
                source_ids.update(str(value) for value in values if str(value))
        if not source_ids:
            core_junction_id = str(expanded_scope.get("core_junction_id", ""))
            if core_junction_id:
                source_ids.add(core_junction_id)
    if not source_ids:
        original_junction_id = str(report.get("candidate_original_junction_id", ""))
        if original_junction_id:
            source_ids.add(original_junction_id)

    candidate_ids = set(source_ids)
    candidate_junction_id = str(report.get("junction_id", ""))
    if candidate_junction_id:
        candidate_ids.add(candidate_junction_id)
    return sorted(source_ids), sorted(candidate_ids)

def _write_teacher_guided_promotion_gate(
    *,
    output_file: Path,
    status: str,
    claim_status: str,
    parity_gate_status: str,
    approach_integrity_status: str,
    variant_reports: list[dict[str, object]],
    context_gate_status: str = "skipped",
    connection_mode_regression_status: str = "skipped",
) -> dict[str, object]:
    applied_reports = [report for report in variant_reports if report.get("composite_applied")]
    global_candidate_reports = [
        report for report in variant_reports if bool(report.get("global_candidate_eligible", True))
    ]
    gate_reports = applied_reports or [
        report for report in global_candidate_reports if not report.get("expanded_scope_followup_emitted")
    ] or global_candidate_reports or [
        report for report in variant_reports if not report.get("expanded_scope_followup_emitted")
    ]
    items = [
        {
            "junction_id": str(report.get("junction_id", "")),
            "teacher_junction_id": str(report.get("teacher_junction_id", "")),
            "status": str(report.get("status", "")),
            "parity_gate_status": str(report.get("parity_gate_status", "")),
            "connection_mode_regression_status": str(
                report.get("connection_mode_regression", {}).get("status", "not_run")
            )
            if isinstance(report.get("connection_mode_regression"), dict)
            else "not_run",
            "final_net_file": str(report.get("final_net_file", "")),
            "candidate_scope_status": str(report.get("candidate_scope_status") or "full_network"),
            "global_candidate_eligible": bool(report.get("global_candidate_eligible", True)),
            "semantic_layer_gates": report.get("semantic_layer_gates", {})
            if isinstance(report.get("semantic_layer_gates"), dict)
            else {},
        }
        for report in gate_reports
    ]
    gate_status = (
        "pass"
        if status == "pass"
        and parity_gate_status == "pass"
        and context_gate_status != "fail"
        and connection_mode_regression_status != "fail"
        and approach_integrity_status == "pass"
        and items
        and all(item["status"] == "pass" and item["parity_gate_status"] == "pass" for item in items)
        else ("blocked" if not items else "fail")
    )
    report = {
        "status": gate_status,
        "claim_status": claim_status,
        "parity_gate_status": parity_gate_status,
        "context_gate_status": context_gate_status,
        "connection_mode_regression_status": connection_mode_regression_status,
        "approach_integrity_status": approach_integrity_status,
        "candidate_count": len(items),
        "pass_candidate_count": sum(1 for item in items if item["status"] == "pass"),
        "items": items,
    }
    output_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report

def _approach_integrity_failure_counts(semantic_failure_counts: dict[str, int]) -> dict[str, int]:
    counts = {
        key: value
        for key, value in semantic_failure_counts.items()
        if key.split(":", 1)[-1] in APPROACH_INTEGRITY_FAILURE_FIELDS
    }
    return dict(sorted(counts.items()))

def _approach_integrity_status(
    *,
    parity_gate_status: str,
    attempted_count: int,
    semantic_failure_counts: dict[str, int],
    approach_failure_counts: dict[str, int],
) -> str:
    if approach_failure_counts:
        return "fail"
    if attempted_count == 0 or parity_gate_status == "blocked":
        return "blocked"
    if semantic_failure_counts or parity_gate_status == "pass":
        return "pass"
    return "blocked"

def _teacher_pattern_contexts(variant_reports: list[dict[str, object]]) -> list[dict[str, object]]:
    contexts = []
    seen_keys = set()
    for report in variant_reports:
        pattern_key = str(report.get("teacher_pattern_key", ""))
        if not pattern_key or pattern_key in seen_keys:
            continue
        seen_keys.add(pattern_key)
        try:
            template_count = int(report.get("teacher_pattern_template_count", 0) or 0)
        except (TypeError, ValueError):
            template_count = 0
        examples = report.get("teacher_pattern_template_examples", [])
        contexts.append(
            {
                "teacher_pattern_key": pattern_key,
                "teacher_pattern_family": str(report.get("teacher_pattern_family", "")),
                "teacher_pattern_template_count": template_count,
                "teacher_pattern_template_examples": [str(item) for item in examples]
                if isinstance(examples, list)
                else [],
            }
        )
    return contexts

def _attach_candidate_template_context(
    report: dict[str, object],
    candidate: dict[str, Any],
) -> dict[str, object]:
    context = {
        key: candidate[key]
        for key in (
            "teacher_pattern_key",
            "teacher_pattern_family",
            "teacher_pattern_template_count",
            "teacher_pattern_template_examples",
            "matched_candidate_node_ids",
            "expanded_rebuild_scope",
            "tls_join_scope_expansion",
            "tls_approach_edge_map_evidence",
            "sequential_refreshed_candidate",
            "sequential_refresh_source_net_file",
            "sequential_refresh_status",
            "sequential_refresh_error",
            "sequential_allowed_boundary_overlap_edge_ids",
        )
        if key in candidate
    }
    candidate_original_junction_id = str(candidate.get("junction_id", ""))
    if candidate_original_junction_id:
        context["candidate_original_junction_id"] = candidate_original_junction_id
    if not context:
        return report
    merged = {**report, **context}
    report_file = str(report.get("report_file", ""))
    if report_file:
        try:
            path = Path(report_file)
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                path.write_text(json.dumps({**existing, **context}, indent=2, ensure_ascii=False), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass
    return merged

def _should_emit(movement: dict[str, object]) -> bool:
    return movement.get("status") == "emit" and float(movement.get("confidence", 0.0)) >= 0.5

def _teacher_guided_candidate_sort_key(candidate: dict[str, object]) -> tuple[int, int, int, int, int, str]:
    movement_gap = int(candidate.get("vehicle_movement_matrix_missing_count", 0) or 0)
    template_count = int(candidate.get("teacher_pattern_template_count", 0) or 0)
    candidate_nodes = candidate.get("matched_candidate_node_ids")
    candidate_node_count = len(candidate_nodes) if isinstance(candidate_nodes, list) else 1_000_000
    status_rank = 0 if candidate.get("candidate_status") in {"ready_for_teacher_guided_variant", "needs_expanded_rebuild_scope"} else 1
    is_same_id_tls = candidate.get("learned_rule") == "tum_like_same_id_tls_candidate"
    semantic_rank = 0 if is_same_id_tls else 1
    movement_rank = movement_gap if is_same_id_tls else -movement_gap
    return (status_rank, semantic_rank, movement_rank, -template_count, candidate_node_count, str(candidate.get("reference_id", "")))

def _limit_ready_repair_candidates(candidates: list[dict[str, object]], max_ready_candidates: int) -> list[dict[str, object]]:
    ready = [
        candidate
        for candidate in candidates
        if candidate.get("candidate_status") == "ready_for_teacher_guided_variant"
    ][:max_ready_candidates]
    if len(ready) >= max_ready_candidates:
        return ready
    ready_ids = {id(candidate) for candidate in ready}
    selected = list(ready)
    for candidate in candidates:
        if id(candidate) in ready_ids:
            continue
        selected.append(candidate)
    return selected

def _tls_repair_actions(repair_category: str) -> list[str]:
    if repair_category == "tls_linkindex_phase_repair":
        return ["inspect_tls_linkindex_phase"]
    return ["inspect_tls_control"]

def _queue_path(value: object, base_dir: Path | None) -> Path:
    path = Path(str(value))
    if path.is_absolute() or base_dir is None:
        return path
    return base_dir / path

def _valid_edge_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        return {}
    result: dict[str, str] = {}
    for source, target in value.items():
        if not isinstance(source, str) or not source.strip():
            return {}
        if not isinstance(target, str) or not target.strip():
            return {}
        result[source] = target
    return result

def _prefer_existing_exact_edge_ids(
    edge_map: dict[str, str],
    candidate_edges_by_id: dict[str, ET.Element],
) -> dict[str, str]:
    return {
        teacher_edge_id: teacher_edge_id
        if teacher_edge_id in candidate_edges_by_id
        else candidate_edge_id
        for teacher_edge_id, candidate_edge_id in edge_map.items()
    }

def _junction_pattern_record_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = {}
    for record in report.get("junction_pattern_index", []) or []:
        if not isinstance(record, dict):
            continue
        junction_id = str(record.get("junction_id", ""))
        if junction_id:
            records[junction_id] = record
    return records

def _junction_pattern_template_by_key(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    templates = {}
    for template in report.get("junction_pattern_templates", []) or []:
        if not isinstance(template, dict):
            continue
        pattern_key = str(template.get("pattern_key", ""))
        if pattern_key:
            templates[pattern_key] = template
    return templates

def _teacher_template_count_for_case(
    case: dict[str, Any],
    pattern_records: dict[str, dict[str, Any]],
    pattern_templates: dict[str, dict[str, Any]],
) -> int:
    reference_id = str(case.get("reference_id", ""))
    pattern_key = str(pattern_records.get(reference_id, {}).get("pattern_key", ""))
    if not pattern_key:
        return 0
    return int(pattern_templates.get(pattern_key, {}).get("count", 0) or 0)

def _junction_pattern_delta_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    deltas = {}
    for comparison in report.get("junction_pattern_comparisons", []) or []:
        if not isinstance(comparison, dict):
            continue
        junction_id = str(comparison.get("junction_id", ""))
        if not junction_id:
            continue
        deltas[junction_id] = {
            "junction_id": junction_id,
            "status": str(comparison.get("status", "")),
            "mismatch_fields": [str(field) for field in comparison.get("mismatch_fields", []) or []],
            "teacher": comparison.get("teacher", {}) if isinstance(comparison.get("teacher"), dict) else {},
            "candidate": comparison.get("candidate", {}) if isinstance(comparison.get("candidate"), dict) else {},
        }
    return deltas

def _teacher_junction_has_tls(
    root: ET.Element,
    junction_id: str,
    junction: ET.Element,
) -> bool:
    return (
        junction.attrib.get("type") == "traffic_light"
        or any(tl.attrib.get("id") == junction_id for tl in root.findall("tlLogic"))
        or any(connection.attrib.get("tl") == junction_id for connection in root.findall("connection"))
    )

def _candidate_edge_by_exact_or_unsplit_id(
    edge_id: str,
    candidate_edges_by_id: dict[str, ET.Element],
) -> tuple[str, ET.Element | None]:
    candidate_edge = candidate_edges_by_id.get(edge_id)
    if candidate_edge is not None:
        return edge_id, candidate_edge
    if "#" not in edge_id:
        return "", None
    base_edge_id = edge_id.split("#", 1)[0]
    candidate_edge = candidate_edges_by_id.get(base_edge_id)
    if candidate_edge is None:
        return "", None
    return base_edge_id, candidate_edge

def _real_junction_ids(root: ET.Element) -> set[str]:
    return {
        junction.attrib["id"]
        for junction in root.findall("junction")
        if junction.attrib.get("id")
        and not junction.attrib["id"].startswith(":")
        and junction.attrib.get("type") != "internal"
    }

def _attach_teacher_pattern_template(
    candidate: dict[str, object],
    pattern_records: dict[str, dict[str, Any]],
    pattern_templates: dict[str, dict[str, Any]],
) -> dict[str, object]:
    reference_id = str(candidate.get("reference_id", ""))
    record = pattern_records.get(reference_id, {})
    movement_exemplar = candidate.get("movement_exemplar", {})
    exemplar_pattern_key = (
        str(movement_exemplar.get("pattern_key", ""))
        if isinstance(movement_exemplar, dict)
        else ""
    )
    pattern_key = str(record.get("pattern_key", "")) or exemplar_pattern_key
    if not pattern_key:
        return candidate
    template = pattern_templates.get(pattern_key, {})
    return {
        **candidate,
        "teacher_pattern_key": pattern_key,
        "teacher_pattern_family": str(
            template.get("pattern_family", record.get("pattern_family", ""))
        ),
        "teacher_pattern_template_count": int(template.get("count", 0) or 0),
        "teacher_pattern_template_examples": [
            str(item) for item in template.get("example_junction_ids", []) or []
        ],
    }

def _netedit_review_actions(mismatch_fields: list[str]) -> list[str]:
    action_by_field = {
        "internal_function_counts": "inspect_internal_edges_crossings_walkingareas",
        "approach_edge_ids": "verify_approach_membership",
        "control_type": "inspect_tls_control",
        "has_tls": "inspect_tls_control",
        "movement_signature_counts": "rebuild_vehicle_movement_matrix",
        "request_bit_lengths_ok": "inspect_request_foes_response",
    }
    return list(
        dict.fromkeys(
            action_by_field.get(field, "inspect_junction_pattern_delta") for field in mismatch_fields
        )
    )

def _junction_pattern_delta_keys(candidate: dict[str, object]) -> list[str]:
    keys = [str(candidate.get("reference_id", "")), str(candidate.get("junction_id", ""))]
    for field in ("reference_joined_source_nodes", "matched_reference_source_node_ids", "matched_candidate_node_ids"):
        keys.extend(str(item) for item in candidate.get(field, []) or [])
    return [key for key in dict.fromkeys(keys) if key]

def _stable_digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]

def _write_connections(
    path: Path,
    movements: list[dict[str, object]],
) -> None:
    root = ET.Element("connections")
    for movement in movements:
        ET.SubElement(
            root,
            "connection",
            {
                "from": str(movement.get("source_edge_id") or movement.get("from_edge_id") or ""),
                "to": str(movement.get("target_edge_id") or movement.get("to_edge_id") or ""),
                "fromLane": str(movement.get("fromLane", "0") or "0"),
                "toLane": str(movement.get("toLane", "0") or "0"),
            },
        )
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

def _approach_edges(candidate_model: dict[str, object], direction: str) -> list[str]:
    approaches = candidate_model.get("approaches", {})
    if not isinstance(approaches, dict):
        return []
    return [
        str(edge.get("edge_id", ""))
        for edge in approaches.get(direction, []) or []
        if isinstance(edge, dict) and edge.get("edge_id")
    ]

def _conservative_join_node_ids(candidate_node_ids: list[str], matched_source_node_ids: set[str]) -> list[str]:
    matched = [node_id for node_id in candidate_node_ids if node_id in matched_source_node_ids]
    if len(matched) >= 2:
        return matched
    if len(matched) == 1:
        first_other = next((node_id for node_id in candidate_node_ids if node_id != matched[0]), "")
        return [first_other, matched[0]] if first_other else matched
    return candidate_node_ids[:2]

def _sumo_joined_cluster_id(node_ids: list[str]) -> str:
    ids = sorted(dict.fromkeys(node_id for node_id in node_ids if node_id))
    if not ids:
        return ""
    head = "_".join(ids[:4])
    suffix = "" if len(ids) <= 4 else f"_#{len(ids) - 4}more"
    return f"cluster_{head}{suffix}"

def _sumo_cluster_member_ids(node_id: str) -> list[str]:
    """Expand the lossless part of a SUMO joined-cluster id.

    ``netconvert`` names an explicit join from its source node ids as
    ``cluster_<id>_<id>...``.  Expanded teacher scopes carry those generated
    ids in ``junction_ids`` even though the plain OSM source still contains
    the member nodes.  The ``_#Nmore`` suffix is deliberately ignored: it is
    a display-only truncation and must never be treated as a real node id.
    """

    value = str(node_id or "")
    if not value.startswith("cluster_"):
        return [value] if value else []
    members = [
        token
        for token in value.removeprefix("cluster_").split("_")
        if token and not token.startswith("#")
    ]
    return members

def _expanded_rebuild_scope(
    core_junction_id: str,
    approach_endpoint_rebuild_plan: dict[str, Any],
    *,
    blocked_teacher_edge_ids: list[str],
    fallback_junction_ids: list[str] | None = None,
) -> dict[str, Any]:
    if approach_endpoint_rebuild_plan.get("status") == "review":
        neighbor_ids = [
            str(item) for item in approach_endpoint_rebuild_plan.get("affected_neighbor_junction_ids", []) or []
        ]
        missing_ids = [str(item) for item in approach_endpoint_rebuild_plan.get("missing_desired_endpoint_ids", []) or []]
        reason = (
            "approach endpoints differ and at least one missing teacher edge cannot be copied safely"
            if blocked_teacher_edge_ids
            else "approach endpoints differ; rebuild expanded scope before teacher movement replay"
        )
        return {
            "status": "review",
            "recommended_action": "rebuild_plain_xml_scope",
            "core_junction_id": core_junction_id,
            "junction_ids": sorted({core_junction_id, *neighbor_ids, *missing_ids}),
            "join_junction_ids": [core_junction_id] if core_junction_id else [],
            "blocked_teacher_edge_ids": blocked_teacher_edge_ids,
            "missing_desired_endpoint_ids": missing_ids,
            "reason": reason,
        }
    if not blocked_teacher_edge_ids:
        return {"status": "pass", "recommended_action": "none", "junction_ids": []}
    fallback_ids = sorted({str(item) for item in fallback_junction_ids or [] if str(item)})
    if len(fallback_ids) < 2:
        return {"status": "pass", "recommended_action": "none", "junction_ids": []}
    return {
        "status": "review",
        "recommended_action": "rebuild_plain_xml_scope",
        "core_junction_id": core_junction_id,
        "junction_ids": fallback_ids,
        "join_junction_ids": fallback_ids,
        "blocked_teacher_edge_ids": blocked_teacher_edge_ids,
        "missing_desired_endpoint_ids": [],
        "reason": "missing teacher approach edge cannot be copied safely; rebuild from matched candidate source nodes",
    }

def _missing_teacher_edge_endpoint_ids(
    teacher_edges: dict[str, ET.Element],
    missing_teacher_edge_ids: list[str],
    reference_id: str,
) -> list[str]:
    return sorted(
        {
            endpoint
            for edge_id in missing_teacher_edge_ids
            if (edge := teacher_edges.get(edge_id)) is not None
            for endpoint in (edge.attrib.get("from", ""), edge.attrib.get("to", ""))
            if endpoint and endpoint != reference_id
        }
    )

def _is_turnaround_connection(connection: dict[str, object]) -> bool:
    return str(connection.get("dir", "")).lower() == TURNAROUND_DIR

def _write_teacher_guided_queue_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "reference_id",
                "junction_id",
                "candidate_status",
                "junction_pattern_delta_count",
                "junction_pattern_mismatch_fields",
                "netedit_review_actions",
                "review_priority",
                "teacher_pattern_key",
                "teacher_pattern_template_count",
                "vehicle_movement_matrix_missing_count",
                "missing_teacher_movement_plan_count",
                "turnaround_only_lane_gap_count",
                "edge_map_size",
                "missing_teacher_edge_ids",
                "copyable_missing_teacher_edge_ids",
                "uncopyable_missing_teacher_edge_ids",
                "matched_candidate_node_ids",
                "learned_rule",
                "error",
            ],
        )
        writer.writeheader()
        for row in rows:
            edge_map = row.get("edge_map", {})
            writer.writerow(
                {
                    "reference_id": row.get("reference_id", ""),
                    "junction_id": row.get("junction_id", ""),
                    "candidate_status": row.get("candidate_status", ""),
                    "junction_pattern_delta_count": row.get("junction_pattern_delta_count", 0),
                    "junction_pattern_mismatch_fields": ";".join(
                        str(item) for item in row.get("junction_pattern_mismatch_fields", []) or []
                    ),
                    "netedit_review_actions": ";".join(
                        str(item) for item in row.get("netedit_review_actions", []) or []
                    ),
                    "review_priority": row.get("review_priority", ""),
                    "teacher_pattern_key": row.get("teacher_pattern_key", ""),
                    "teacher_pattern_template_count": row.get("teacher_pattern_template_count", 0),
                    "vehicle_movement_matrix_missing_count": row.get("vehicle_movement_matrix_missing_count", 0),
                    "missing_teacher_movement_plan_count": row.get("missing_teacher_movement_plan_count", 0),
                    "turnaround_only_lane_gap_count": row.get("turnaround_only_lane_gap_count", 0),
                    "edge_map_size": len(edge_map) if isinstance(edge_map, dict) else 0,
                    "missing_teacher_edge_ids": ";".join(str(item) for item in row.get("missing_teacher_edge_ids", []) or []),
                    "copyable_missing_teacher_edge_ids": ";".join(
                        str(item) for item in row.get("copyable_missing_teacher_edge_ids", []) or []
                    ),
                    "uncopyable_missing_teacher_edge_ids": ";".join(
                        str(item) for item in row.get("uncopyable_missing_teacher_edge_ids", []) or []
                    ),
                    "matched_candidate_node_ids": ";".join(str(item) for item in row.get("matched_candidate_node_ids", []) or []),
                    "learned_rule": row.get("learned_rule", ""),
                    "error": row.get("error", ""),
                }
            )

def _candidate_lane_counts(candidate_model: dict[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for direction in ("incoming", "outgoing"):
        approaches = candidate_model.get("approaches", {})
        if not isinstance(approaches, dict):
            continue
        for edge in approaches.get(direction, []) or []:
            if isinstance(edge, dict) and edge.get("edge_id"):
                counts[str(edge["edge_id"])] = max(1, int(edge.get("lane_count", 1) or 1))
    return counts

def _edge_file_lane_counts(edge_file: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in ET.parse(edge_file).getroot().findall("edge"):
        edge_id = edge.attrib.get("id")
        if not edge_id:
            continue
        lanes = edge.findall("lane")
        if lanes:
            counts[edge_id] = len(lanes)
        elif edge.attrib.get("numLanes"):
            counts[edge_id] = max(1, int(edge.attrib["numLanes"]))
    return counts

def _net_lane_counts(root: ET.Element) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id")
        if edge_id:
            counts[edge_id] = max(1, len(edge.findall("lane")))
    return counts

def _connection_lane_indices_valid(connection: ET.Element, lane_counts: dict[str, int]) -> bool:
    def _valid(edge_id: str, lane_index: str) -> bool:
        try:
            index = int(lane_index or "0")
        except ValueError:
            return False
        return 0 <= index < lane_counts.get(edge_id, 0)

    return _valid(connection.attrib.get("from", ""), connection.attrib.get("fromLane", "0")) and _valid(
        connection.attrib.get("to", ""),
        connection.attrib.get("toLane", "0"),
    )

def _edge_is_pedestrian_only(edge: ET.Element) -> bool:
    lanes = edge.findall("lane")
    return bool(lanes) and all(set((lane.attrib.get("allow") or "").split()) == {"pedestrian"} for lane in lanes)

def _edge_lane_count(edge: ET.Element) -> int:
    return max(1, len(edge.findall("lane")))

def _edge_type_signature(edge: ET.Element) -> str:
    return edge.attrib.get("type", "")

def _command_path(path: Path, cwd: Path) -> str:
    try:
        return str(path.resolve().relative_to(cwd.resolve()))
    except ValueError:
        return str(path)

def _stage_file(output_dir: Path, prefix: str, suffix: str) -> Path:
    def candidate(name: str) -> Path | None:
        path = output_dir / name
        return path if len(str(path.resolve())) < 260 else None

    if path := candidate(f"{prefix}_{suffix}"):
        return path
    short_prefix = (prefix[:16].strip("_") or "tg")
    if path := candidate(f"{short_prefix}_{suffix}"):
        return path
    if path := candidate(suffix):
        return path
    suffix_aliases = {
        "nodes.nod.xml": "n.nod.xml",
        "connections.con.xml": "c.con.xml",
        "lanes.edg.xml": "e.edg.xml",
        "sidewalks.net.xml": "sw.net.xml",
        "pedring.net.xml": "pr.net.xml",
        "vehicle_attrs.net.xml": "va.net.xml",
        "target_internal_replay.net.xml": "tir.net.xml",
        "target_internal_normalized.net.xml": "tin.net.xml",
        "target_internal_normalized_unrestored.net.xml": "tin_raw.net.xml",
        "target_internal_pedring.net.xml": "tip.net.xml",
        "target_internal_vehicle_attrs.net.xml": "tva.net.xml",
        "teacher_guided.net.xml": "tg.net.xml",
        "teacher_guided_fallback.net.xml": "tgfb.net.xml",
        "teacher_guided_report.json": "tgr.json",
    }
    return output_dir / suffix_aliases.get(suffix, suffix)

def _primary_edge_shape(edge: ET.Element) -> str:
    if edge.attrib.get("shape"):
        return edge.attrib["shape"]
    lane = edge.find("lane")
    return lane.attrib.get("shape", "") if lane is not None else ""

def _preserve_boundary_operational_attributes(
    replayed_edge: ET.Element,
    source_edge: ET.Element,
) -> dict[str, object]:
    """Keep OSM road semantics while MAP/teacher owns only local topology.

    Official MAP evidence can authorize a lane-count expansion and the movement
    matrix, but it does not reclassify the complete boundary segment or restrict
    its vehicle classes.  Existing lanes retain their source operational fields;
    a newly added lane clones the nearest source lane's fields.
    """

    changed_edge_attrs = 0
    for attr in BOUNDARY_EDGE_OPERATIONAL_ATTRS:
        before = replayed_edge.attrib.get(attr)
        if attr in source_edge.attrib:
            replayed_edge.set(attr, source_edge.attrib[attr])
        else:
            replayed_edge.attrib.pop(attr, None)
        if before != replayed_edge.attrib.get(attr):
            changed_edge_attrs += 1

    source_lanes = {
        int(lane.attrib.get("index", "0") or 0): lane
        for lane in source_edge.findall("lane")
    }
    changed_lane_attrs = 0
    cloned_lane_indices: list[int] = []
    for replayed_lane in replayed_edge.findall("lane"):
        replayed_index = int(replayed_lane.attrib.get("index", "0") or 0)
        source_lane = source_lanes.get(replayed_index)
        if source_lane is None and source_lanes:
            source_index = min(source_lanes, key=lambda index: (abs(index - replayed_index), index))
            source_lane = source_lanes[source_index]
            cloned_lane_indices.append(replayed_index)
        if source_lane is None:
            continue
        for attr in BOUNDARY_LANE_OPERATIONAL_ATTRS:
            before = replayed_lane.attrib.get(attr)
            if attr in source_lane.attrib:
                replayed_lane.set(attr, source_lane.attrib[attr])
            else:
                replayed_lane.attrib.pop(attr, None)
            if before != replayed_lane.attrib.get(attr):
                changed_lane_attrs += 1
    return {
        "preserved_boundary_edge_operational_attr_count": changed_edge_attrs,
        "preserved_boundary_lane_operational_attr_count": changed_lane_attrs,
        "operational_attrs_cloned_to_new_lane_indices": sorted(cloned_lane_indices),
    }

def _load_geometry_anchor_edges(edge_file: Path | None) -> dict[str, ET.Element]:
    if edge_file is None:
        return {}
    try:
        root = ET.parse(edge_file).getroot()
    except (ET.ParseError, OSError):
        return {}
    return {
        edge.attrib["id"]: copy.deepcopy(edge)
        for edge in root.findall("edge")
        if edge.attrib.get("id")
        and edge.attrib.get("function") != "internal"
        and (edge.attrib.get("shape") or any(lane.attrib.get("shape") for lane in edge.findall("lane")))
    }

def _geometry_anchor_junctions_by_id(
    candidate_edges_by_id: dict[str, ET.Element],
    candidate_junctions_by_id: dict[str, ET.Element],
    geometry_anchor_edge_ids: set[str],
    *,
    target_junction_id: str,
) -> dict[str, ET.Element]:
    anchored: dict[str, ET.Element] = {}
    for edge_id in geometry_anchor_edge_ids:
        edge = candidate_edges_by_id.get(edge_id)
        if edge is None:
            continue
        for endpoint_id in (edge.attrib.get("from", ""), edge.attrib.get("to", "")):
            if not endpoint_id or endpoint_id == target_junction_id:
                continue
            junction = candidate_junctions_by_id.get(endpoint_id)
            if junction is not None:
                anchored[endpoint_id] = copy.deepcopy(junction)
    return anchored

def _restore_geometry_anchor_junctions(
    root: ET.Element,
    geometry_anchor_junctions_by_id: dict[str, ET.Element],
) -> list[str]:
    restored = []
    for junction_id, source_junction in sorted(geometry_anchor_junctions_by_id.items()):
        junction = root.find(f"junction[@id='{junction_id}']")
        if junction is None:
            continue
        for attr in ("x", "y", "z", "shape"):
            if source_junction.attrib.get(attr):
                junction.set(attr, source_junction.attrib[attr])
            else:
                junction.attrib.pop(attr, None)
        restored.append(junction_id)
    return restored

def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return unique

    def cross(origin: tuple[float, float], left: tuple[float, float], right: tuple[float, float]) -> float:
        return (left[0] - origin[0]) * (right[1] - origin[1]) - (left[1] - origin[1]) * (right[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]

def _lanes_by_index(edge: ET.Element) -> dict[str, ET.Element]:
    return {lane.attrib.get("index", ""): lane for lane in edge.findall("lane") if lane.attrib.get("index", "")}

def _joined_lane_length(first_lane: ET.Element, second_lane: ET.Element) -> str | None:
    try:
        return f"{float(first_lane.attrib['length']) + float(second_lane.attrib['length']):.2f}"
    except (KeyError, ValueError):
        return None

def _junction_xy(root: ET.Element, junction_id: str) -> tuple[float, float] | None:
    junction = next((item for item in root.findall("junction") if item.attrib.get("id") == junction_id), None)
    if junction is None:
        return None
    try:
        return float(junction.attrib["x"]), float(junction.attrib["y"])
    except (KeyError, ValueError):
        return None

def _first_junction_index(root: ET.Element) -> int:
    for index, child in enumerate(list(root)):
        if child.tag == "junction":
            return index
    return len(list(root))

def _map_internal_ref(value: str, teacher_internal_prefix: str, candidate_internal_prefix: str) -> str:
    if teacher_internal_prefix and candidate_internal_prefix and value.startswith(teacher_internal_prefix):
        return f"{candidate_internal_prefix}{value[len(teacher_internal_prefix):]}"
    return value

def _touches_target_internal_subgraph(connection: ET.Element, internal_prefix: str, junction_id: str) -> bool:
    return (
        connection.attrib.get("from", "").startswith(internal_prefix)
        or connection.attrib.get("to", "").startswith(internal_prefix)
        or connection.attrib.get("via", "").startswith(internal_prefix)
        or connection.attrib.get("tl", "") == junction_id
    )

def _touches_target_internal_owner(connection: ET.Element, internal_prefix: str) -> bool:
    return any(
        connection.attrib.get(attr, "").startswith(internal_prefix)
        for attr in ("from", "to", "via")
    )

def _touches_other_internal_owner(connection: ET.Element, internal_prefix: str) -> bool:
    return any(
        value.startswith(":") and not value.startswith(internal_prefix)
        for value in (connection.attrib.get(attr, "") for attr in ("from", "to", "via"))
        if value
    )

def _polygon_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    return abs(
        sum(
            left[0] * right[1] - right[0] * left[1]
            for left, right in zip(points, [*points[1:], points[0]])
        )
    ) / 2.0

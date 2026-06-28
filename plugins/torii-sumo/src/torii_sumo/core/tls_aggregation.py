from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
from typing import Any, Callable, Mapping
import xml.etree.ElementTree as ET

from .command_runner import run_command


def build_tls_aggregation_variant(
    *,
    net_file: Path,
    tls_audit_report: Mapping[str, Any],
    output_dir: Path,
    prefix: str = "tls_aggregation",
    timeout_seconds: float = 240.0,
    command_runner: Callable[..., Any] = run_command,
    controlled_nodes_by_tls_func: Callable[[Path], dict[str, list[str]]] | None = None,
) -> dict[str, Any]:
    if not net_file.exists():
        return _failure(f"net file does not exist: {net_file}")
    net_file = net_file.resolve()
    output_dir = output_dir.resolve()

    cluster_count = _int_field(tls_audit_report, "tls_cluster_count")
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_file = output_dir / f"{prefix}_plan.json"
    candidates_file = output_dir / f"{prefix}_representatives.csv"
    variant_file = output_dir / f"{prefix}_tls_aggregated.net.xml"
    command_record = output_dir / f"{prefix}_netconvert.cmd.txt"
    source_tls_counts = _source_tls_program_counts(net_file)

    if cluster_count == 0:
        plan_file.write_text(
            json.dumps(
                {
                    "tls_aggregation_status": "not_needed",
                    "tls_physical_cluster_count": 0,
                    "tls_program_policy": "not_applicable_no_tls_clusters",
                    **source_tls_counts,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        _write_representatives_csv(candidates_file, [])
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_aggregation_status": "not_needed",
            "tls_physical_cluster_count": 0,
            "tls_aggregation_plan_file": str(plan_file),
            "tls_aggregation_representatives_file": str(candidates_file),
            "tls_aggregation_variant_file": "",
            "tls_aggregation_command_record": "",
            "tls_aggregation_netconvert": {},
            "tls_program_policy": "not_applicable_no_tls_clusters",
            **source_tls_counts,
            "warnings": [],
        }

    clusters_path = Path(str(tls_audit_report.get("clusters_file", "")))
    if not clusters_path.exists():
        return {
            **_failure(f"TLS clusters file does not exist: {clusters_path}"),
            "tls_aggregation_plan_file": str(plan_file),
            "tls_aggregation_variant_file": "",
        }

    clusters = _read_clusters(clusters_path)
    try:
        controlled_nodes_by_tls = (
            controlled_nodes_by_tls_func(net_file)
            if controlled_nodes_by_tls_func is not None
            else _controlled_nodes_by_tls(net_file)
        )
    except Exception as exc:
        return {
            **_failure(f"could not derive TLS-controlled junctions: {type(exc).__name__}: {exc}"),
            "tls_aggregation_plan_file": str(plan_file),
            "tls_aggregation_representatives_file": str(candidates_file),
            "tls_aggregation_variant_file": "",
        }
    representatives = _representatives_for_clusters(clusters, controlled_nodes_by_tls)
    _write_representatives_csv(candidates_file, representatives)
    plan = {
        "tls_aggregation_status": "planned_for_review_variant",
        "net_file": str(net_file),
        "variant_file": str(variant_file),
        "tls_physical_cluster_count": len(clusters),
        "representative_count": len(representatives),
        "tls_program_policy": "discard_loaded_programs_rebuild_tls_set",
        **source_tls_counts,
        "review_policy": (
            "create a separate network with one real SUMO junction set as TLS per physical TLS cluster; "
            "do not overwrite the source network or treat the variant as map-confirmed"
        ),
        "representatives": representatives,
    }
    plan_file.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

    representative_node_ids = [row["representative_node_id"] for row in representatives if row["representative_node_id"]]
    if not representative_node_ids:
        return {
            **_failure("no representative junction ids could be derived from TLS clusters"),
            "tls_aggregation_plan_file": str(plan_file),
            "tls_aggregation_representatives_file": str(candidates_file),
            "tls_aggregation_variant_file": "",
        }

    command = [
        "netconvert",
        "--sumo-net-file",
        str(net_file),
        "--tls.discard-loaded",
        "--tls.set",
        ",".join(representative_node_ids),
        "--tls.join",
        "--tls.join-dist",
        "35",
        "--tls.default-type",
        "actuated",
        "--output-file",
        _command_path(variant_file, output_dir),
    ]
    command_record.write_text(" ".join(command) + "\n", encoding="utf-8")
    try:
        result = _result_to_dict(command_runner(command, cwd=output_dir, timeout_seconds=timeout_seconds))
    except OSError as exc:
        return {
            **_failure(f"{type(exc).__name__}: {exc}"),
            "tls_aggregation_plan_file": str(plan_file),
            "tls_aggregation_representatives_file": str(candidates_file),
            "tls_aggregation_variant_file": str(variant_file),
            "tls_aggregation_command_record": str(command_record),
        }

    status = "pass" if result.get("status") == "pass" and variant_file.exists() else "fail"
    tls_program_preservation = (
        _preserve_compatible_tls_programs(net_file, variant_file, representatives) if status == "pass" else _empty_preservation()
    )
    counts = _tls_counts(variant_file) if variant_file.exists() else {}
    tls_connection_preservation = _tls_connection_preservation(source_tls_counts, counts) if status == "pass" else {}
    warnings = ["TLS aggregation variant requires Google Maps and Netedit review before adoption"]
    if source_tls_counts["source_tl_logic_count"] and not tls_program_preservation["tls_program_preserved_count"]:
        warnings.append(
            "TLS aggregation discards loaded tlLogic programs via --tls.discard-loaded; "
            "actuated/minDur/maxDur semantics are not preserved"
        )
    elif tls_program_preservation["tls_program_skipped_count"]:
        warnings.append("Some source tlLogic programs were not compatible with the rebuilt TLS link state length")
    if tls_connection_preservation.get("tls_controlled_connection_preservation_status") == "fail":
        warnings.append(
            "TLS aggregation lost "
            f"{tls_connection_preservation['tls_controlled_connection_regression_count']} controlled TLS connections; "
            "keep the source network for TLS parity review"
        )
    if status != "pass":
        warnings.append(f"TLS aggregation variant was not created: {variant_file}")
    return {
        "status": status,
        "claim_status": "blocked" if status == "pass" else "construction-invalid",
        "tls_aggregation_status": "variant_created_for_review" if status == "pass" else "failed",
        "tls_physical_cluster_count": len(clusters),
        "tls_representative_count": len(representatives),
        "tls_aggregation_plan_file": str(plan_file),
        "tls_aggregation_representatives_file": str(candidates_file),
        "tls_aggregation_variant_file": str(variant_file),
        "tls_aggregation_command_record": str(command_record),
        "tls_aggregation_netconvert": result,
        "tls_program_policy": "discard_loaded_programs_rebuild_tls_set",
        **source_tls_counts,
        **tls_program_preservation,
        **counts,
        **tls_connection_preservation,
        "warnings": warnings,
    }


def _read_clusters(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _command_path(path: Path, cwd: Path) -> str:
    try:
        return str(path.resolve().relative_to(cwd))
    except ValueError:
        return str(path)


def _representatives_for_clusters(
    clusters: list[Mapping[str, Any]],
    controlled_nodes_by_tls: Mapping[str, list[str]],
) -> list[dict[str, str]]:
    rows = []
    for cluster in clusters:
        tls_ids = _split_tls_ids(str(cluster.get("tls_ids", "")))
        node_counts: dict[str, int] = {}
        for tls_id in tls_ids:
            for node_id in controlled_nodes_by_tls.get(tls_id, []):
                node_counts[node_id] = node_counts.get(node_id, 0) + 1
        representative = ""
        if node_counts:
            representative = sorted(node_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        rows.append(
            {
                "cluster_id": str(cluster.get("cluster_id", "")),
                "representative_node_id": representative,
                "tls_ids": ";".join(tls_ids),
                "tls_count": str(cluster.get("tls_count", len(tls_ids))),
                "google_maps_url": str(cluster.get("google_maps_url", "")),
            }
        )
    return rows


def _split_tls_ids(value: str) -> list[str]:
    return [item.strip() for item in value.replace(",", ";").split(";") if item.strip()]


def _controlled_nodes_by_tls(net_file: Path) -> dict[str, list[str]]:
    try:
        import sumolib.net  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("sumolib is required for TLS aggregation") from exc

    net = sumolib.net.readNet(str(net_file), withPrograms=True)
    mapping: dict[str, list[str]] = {}
    for tls in net.getTrafficLights():
        node_ids = []
        try:
            node_ids.append(net.getNode(tls.getID()).getID())
        except Exception:
            pass
        for incoming_lane, outgoing_lane, _link in tls.getConnections():
            for node in (incoming_lane.getEdge().getToNode(), outgoing_lane.getEdge().getFromNode()):
                node_id = node.getID()
                if not node_id.startswith(":"):
                    node_ids.append(node_id)
        mapping[tls.getID()] = sorted(set(node_ids))
    return mapping


def _write_representatives_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["cluster_id", "representative_node_id", "tls_ids", "tls_count", "google_maps_url"],
        )
        writer.writeheader()
        writer.writerows(rows)


def _tls_counts(net_file: Path) -> dict[str, int]:
    root = ET.parse(net_file).getroot()
    connection_counts = _tls_connection_counts(root)
    return {
        "tls_aggregated_traffic_light_junction_count": sum(
            1 for junction in root.findall("junction") if junction.attrib.get("type") == "traffic_light"
        ),
        "tls_aggregated_tl_logic_count": len(root.findall("tlLogic")),
        "tls_aggregated_controlled_connection_count": connection_counts["controlled"],
        "tls_aggregated_tl_connection_missing_linkindex_count": connection_counts["missing_linkindex"],
    }


def _preserve_compatible_tls_programs(
    source_net_file: Path,
    variant_file: Path,
    representatives: list[Mapping[str, str]],
) -> dict[str, Any]:
    source_root = ET.parse(source_net_file).getroot()
    target_tree = ET.parse(variant_file)
    target_root = target_tree.getroot()
    source_by_id = {tl.attrib["id"]: tl for tl in source_root.findall("tlLogic") if tl.attrib.get("id")}
    target_by_id = {tl.attrib["id"]: tl for tl in target_root.findall("tlLogic") if tl.attrib.get("id")}
    preserved = 0
    skipped: list[dict[str, str]] = []
    for row in representatives:
        target_id = str(row.get("representative_node_id", ""))
        target = target_by_id.get(target_id)
        if target is None:
            skipped.append({"representative_node_id": target_id, "reason": "missing_target_tllogic"})
            continue
        source = next(
            (
                source_by_id[tls_id]
                for tls_id in _split_tls_ids(str(row.get("tls_ids", "")))
                if tls_id in source_by_id and _tls_program_compatible(source_by_id[tls_id], target)
            ),
            None,
        )
        if source is None:
            skipped.append({"representative_node_id": target_id, "reason": "no_compatible_source_tllogic"})
            continue
        replacement = ET.Element("tlLogic", dict(source.attrib))
        replacement.set("id", target_id)
        for child in source:
            replacement.append(copy.deepcopy(child))
        index = list(target_root).index(target)
        target_root.remove(target)
        target_root.insert(index, replacement)
        preserved += 1
    if preserved:
        ET.indent(target_root, space="    ")
        target_tree.write(variant_file, encoding="utf-8", xml_declaration=True)
    return {
        "tls_program_preserved_count": preserved,
        "tls_program_skipped_count": len(skipped),
        "tls_program_skips": skipped,
    }


def _tls_program_compatible(source: ET.Element, target: ET.Element) -> bool:
    source_lengths = {len(phase.attrib.get("state", "")) for phase in source.findall("phase") if phase.attrib.get("state")}
    target_lengths = {len(phase.attrib.get("state", "")) for phase in target.findall("phase") if phase.attrib.get("state")}
    return bool(source_lengths) and source_lengths == target_lengths


def _empty_preservation() -> dict[str, Any]:
    return {"tls_program_preserved_count": 0, "tls_program_skipped_count": 0, "tls_program_skips": []}


def _source_tls_program_counts(net_file: Path) -> dict[str, int]:
    root = ET.parse(net_file).getroot()
    tl_logics = root.findall("tlLogic")
    phases = [phase for tl_logic in tl_logics for phase in tl_logic.findall("phase")]
    connection_counts = _tls_connection_counts(root)
    return {
        "source_tl_logic_count": len(tl_logics),
        "source_actuated_tl_logic_count": sum(1 for tl_logic in tl_logics if tl_logic.attrib.get("type") == "actuated"),
        "source_tls_phase_count": len(phases),
        "source_tls_phase_with_minmax_count": sum(
            1 for phase in phases if phase.attrib.get("minDur") or phase.attrib.get("maxDur")
        ),
        "source_tls_controlled_connection_count": connection_counts["controlled"],
        "source_tl_connection_missing_linkindex_count": connection_counts["missing_linkindex"],
    }


def _tls_connection_counts(root: ET.Element) -> dict[str, int]:
    connections = [connection for connection in root.findall("connection") if connection.attrib.get("tl")]
    return {
        "controlled": sum(1 for connection in connections if connection.attrib.get("linkIndex")),
        "missing_linkindex": sum(1 for connection in connections if not connection.attrib.get("linkIndex")),
    }


def _tls_connection_preservation(source_counts: Mapping[str, int], variant_counts: Mapping[str, int]) -> dict[str, int | str]:
    source_controlled = int(source_counts.get("source_tls_controlled_connection_count", 0) or 0)
    variant_controlled = int(variant_counts.get("tls_aggregated_controlled_connection_count", 0) or 0)
    regression = max(0, source_controlled - variant_controlled)
    return {
        "tls_controlled_connection_preservation_status": "fail" if regression else "pass",
        "tls_controlled_connection_regression_count": regression,
    }


def _int_field(report: Mapping[str, Any], key: str) -> int:
    try:
        return int(report.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _result_to_dict(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        return dict(result.to_dict())
    if hasattr(result, "model_dump"):
        return dict(result.model_dump(mode="json"))
    return dict(result)


def _failure(error: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "claim_status": "construction-invalid",
        "tls_aggregation_status": "failed",
        "error": error,
        "warnings": [error],
    }

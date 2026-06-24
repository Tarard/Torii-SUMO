from __future__ import annotations

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

    cluster_count = _int_field(tls_audit_report, "tls_cluster_count")
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_file = output_dir / f"{prefix}_plan.json"
    candidates_file = output_dir / f"{prefix}_representatives.csv"
    variant_file = output_dir / f"{prefix}_tls_aggregated.net.xml"
    command_record = output_dir / f"{prefix}_netconvert.cmd.txt"

    if cluster_count == 0:
        plan_file.write_text(
            json.dumps({"tls_aggregation_status": "not_needed", "tls_physical_cluster_count": 0}, indent=2),
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
        "--output-file",
        str(variant_file),
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
    counts = _tls_counts(variant_file) if variant_file.exists() else {}
    warnings = ["TLS aggregation variant requires Google Maps and Netedit review before adoption"]
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
        **counts,
        "warnings": warnings,
    }


def _read_clusters(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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
    return {
        "tls_aggregated_traffic_light_junction_count": sum(
            1 for junction in root.findall("junction") if junction.attrib.get("type") == "traffic_light"
        ),
        "tls_aggregated_tl_logic_count": len(root.findall("tlLogic")),
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

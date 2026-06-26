from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from .network_visualization import build_network_review_visuals


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _json_block(value: Any) -> str:
    return escape(json.dumps(_jsonable(value), indent=2, ensure_ascii=False, sort_keys=True))


def _json_script(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True).replace("</", "<\\/")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(_jsonable(value), indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _as_path(value: str | Path | None) -> Path | None:
    if value is None or str(value) == "":
        return None
    return Path(value)


def _portable_path(path: str | Path | None, base_dir: Path) -> str:
    if not path:
        return ""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        try:
            return os.path.relpath(resolved, base_dir.resolve()).replace("\\", "/")
        except ValueError:
            return str(path)


def _portable_href(path: Path, base_dir: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        try:
            relative = os.path.relpath(resolved, base_dir.resolve()).replace("\\", "/")
        except ValueError:
            return str(path)
    return quote(relative)


def _path_href(path: Path, base_dir: Path) -> str:
    href = _portable_href(path, base_dir)
    if href:
        return href
    try:
        return path.resolve().as_uri()
    except ValueError:
        return str(path)


def _artifact_link(path: Path | None, *, base_dir: Path) -> str:
    if path is None:
        return ""
    label = escape(_portable_path(path, base_dir))
    href = _path_href(path, base_dir)
    return f'<a href="{escape(href)}">{label}</a>'


def _image_src(path: str | Path | None, *, base_dir: Path) -> str:
    if not path:
        return ""
    return escape(_path_href(Path(path), base_dir))


def _image_panel(title: str, path: str | Path | None, *, base_dir: Path) -> str:
    if not path:
        return ""
    src = _image_src(path, base_dir=base_dir)
    return (
        '<figure class="visual-panel">'
        f"<figcaption>{escape(title)}</figcaption>"
        f'<img src="{src}" alt="{escape(title)}">'
        "</figure>"
    )


def _source_clusters(topology_audit_report: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    clusters: dict[str, Mapping[str, Any]] = {}
    for index, cluster in enumerate((topology_audit_report or {}).get("suspicious_clusters", []) or [], start=1):
        if not isinstance(cluster, Mapping):
            continue
        cluster_id = str(cluster.get("cluster_id") or f"cluster_{index:03d}")
        clusters[cluster_id] = cluster
    return clusters


def _link(url: str | None, label: str) -> str:
    if not url:
        return ""
    return f'<a href="{escape(str(url))}">{escape(label)}</a>'


def _gate_rows(gate_status: Mapping[str, Any] | None) -> str:
    if not gate_status:
        return '<tr><td colspan="2">No gate status supplied.</td></tr>'
    rows = []
    for gate, status in sorted(gate_status.items()):
        rows.append(
            "<tr>"
            f"<td>{escape(str(gate))}</td>"
            f"<td><code>{escape(str(status))}</code></td>"
            "</tr>"
        )
    return "\n".join(rows)


def _artifact_rows(artifacts: Mapping[str, Path | None], *, base_dir: Path) -> str:
    rows = []
    for label, path in artifacts.items():
        if path is None:
            continue
        rows.append(f"<tr><td>{escape(label)}</td><td>{_artifact_link(path, base_dir=base_dir)}</td></tr>")
    if not rows:
        return '<tr><td colspan="2">No file artifacts supplied.</td></tr>'
    return "\n".join(rows)


def _evidence_rows(
    *,
    topology_audit_report: Mapping[str, Any] | None,
    junction_aggregation_report: Mapping[str, Any] | None,
    routeability_audit_report: Mapping[str, Any] | None,
) -> str:
    rows = [
        (
            "topology_audit",
            topology_audit_report or {},
            (
                "topology_fragmentation_status",
                "suspicious_cluster_count",
                "junction_aggregation_candidate_count",
                "modal_decision_counts",
                "modal_review_action_counts",
                "junction_aggregation_blocked_by_modal_count",
            ),
        ),
        (
            "junction_aggregation",
            junction_aggregation_report or {},
            (
                "junction_aggregation_status",
                "junction_aggregation_candidate_count",
                "junction_join_needs_map_review_count",
            ),
        ),
        (
            "routeability_audit",
            routeability_audit_report or {},
            ("routeability_status", "arrived", "vehicle_count", "teleports", "collisions"),
        ),
    ]
    html_rows = []
    for label, report, keys in rows:
        values = []
        for key in keys:
            if key in report:
                values.append(f"{key}={report[key]}")
        html_rows.append(
            "<tr>"
            f"<td>{escape(label)}</td>"
            f"<td>{escape('; '.join(values) if values else 'no compact status supplied')}</td>"
            "</tr>"
        )
    return "\n".join(html_rows)


def _nonpass_gate_actions(gate_status: Mapping[str, Any] | None) -> list[str]:
    if not gate_status:
        return []
    actions = []
    pass_like = {"pass", "skipped"}
    for gate, status in sorted(gate_status.items()):
        if str(status) not in pass_like:
            actions.append(f"Review gate `{gate}` because it is `{status}`.")
    return actions


def _gate_summary(gate_status: Mapping[str, Any] | None) -> dict[str, int]:
    counts = {"pass": 0, "blocked": 0, "fail": 0, "skipped": 0, "other": 0}
    for status in (gate_status or {}).values():
        key = str(status)
        counts[key if key in counts else "other"] += 1
    return counts


def _review_queue_rows(actions: Sequence[str]) -> str:
    if not actions:
        return '<tr><td colspan="3">No review actions were generated.</td></tr>'
    rows = []
    for index, action in enumerate(actions, start=1):
        lowered = action.lower()
        if "routeability" in lowered or "teleport" in lowered:
            priority = "P0"
        elif "tls" in lowered or "traffic" in lowered:
            priority = "P1"
        elif "topology" in lowered or "junction" in lowered:
            priority = "P1"
        else:
            priority = "P2"
        rows.append(
            "<tr>"
            f"<td>{priority}</td>"
            f"<td>{index}</td>"
            f"<td>{escape(action)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _cluster_color_group(cluster: Mapping[str, Any]) -> tuple[str, str]:
    decision = str(cluster.get("aggregation_decision", "")).strip()
    if decision == "join":
        return "green", "auto-join candidate"
    if decision == "needs_map_review":
        return "amber", "needs map review"
    if decision == "do_not_join":
        return "red", "do not aggregate"
    return "slate", "review required"


def _review_status(color_group: str) -> str:
    return {
        "green": "Auto-join",
        "amber": "Needs review",
        "red": "Risky",
        "slate": "Unknown",
    }.get(color_group, "Unknown")


def _map_layer_bounds(map_layers: Mapping[str, Any] | None) -> tuple[float, float, float, float] | None:
    bounds = (map_layers or {}).get("bounds", {})
    if not isinstance(bounds, Mapping):
        return None
    try:
        min_x = float(bounds["min_x"])
        min_y = float(bounds["min_y"])
        max_x = float(bounds["max_x"])
        max_y = float(bounds["max_y"])
    except (KeyError, TypeError, ValueError):
        return None
    if min_x == max_x:
        min_x -= 1.0
        max_x += 1.0
    if min_y == max_y:
        min_y -= 1.0
        max_y += 1.0
    return min_x, min_y, max_x, max_y


def _svg_number(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _svg_points(points: Any) -> str:
    projected = []
    for point in points or []:
        try:
            x = float(point[0])
            y = float(point[1])
        except (TypeError, ValueError, IndexError):
            continue
        projected.append(f"{_svg_number(x)},{_svg_number(-y)}")
    return " ".join(projected)


def _list_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item for item in value.split(";") if item]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item) for item in value if str(item)]
    return []


def _review_color(color_group: str) -> str:
    return {
        "green": "0,153,112",
        "amber": "245,158,11",
        "red": "225,29,72",
        "slate": "100,116,139",
    }.get(color_group, "100,116,139")


def _review_box_shape(x: float, y: float, radius: float) -> str:
    points = (
        (x - radius, y - radius),
        (x + radius, y - radius),
        (x + radius, y + radius),
        (x - radius, y + radius),
        (x - radius, y - radius),
    )
    return " ".join(f"{_svg_number(px)},{_svg_number(py)}" for px, py in points)


def _netedit_review_radius(junction: Mapping[str, Any], bounds: tuple[float, float, float, float] | None) -> float:
    try:
        return max(float(junction.get("cluster_radius_m") or 0), 8.0)
    except (TypeError, ValueError):
        pass
    if bounds is None:
        return 12.0
    min_x, min_y, max_x, max_y = bounds
    return min(max(max(max_x - min_x, max_y - min_y) * 0.008, 8.0), 40.0)


def _write_netedit_review_files(
    *,
    output_dir: Path,
    prefix: str,
    net_file: str | Path | None,
    map_layers: Mapping[str, Any] | None,
    junctions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    net_path = _as_path(net_file)
    if net_path is None or not junctions:
        return {"status": "skipped"}

    additional_file = output_dir / f"{prefix}_netedit_review.add.xml"
    sumocfg_file = output_dir / f"{prefix}_netedit_review.sumocfg"
    bounds = _map_layer_bounds(map_layers)
    root = ET.Element(
        "additional",
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:noNamespaceSchemaLocation": "http://sumo.dlr.de/xsd/additional_file.xsd",
        },
    )
    box_count = 0

    for junction in junctions:
        cluster_id = str(junction.get("cluster_id") or "")
        if not cluster_id:
            continue
        try:
            x = float(junction["x"])
            y = float(junction["y"])
        except (KeyError, TypeError, ValueError):
            continue

        color_group = str(junction.get("color_group", "slate"))
        color = _review_color(color_group)
        radius = _netedit_review_radius(junction, bounds)
        box_count += 1
        ET.SubElement(
            root,
            "poly",
            {
                "id": f"torii_{cluster_id}_review_box",
                "type": f"torii.cluster.{color_group}",
                "color": color,
                "fill": "false",
                "layer": "99.00",
                "lineWidth": "3.00",
                "shape": _review_box_shape(x, y, radius),
                "name": f"{cluster_id} {junction.get('status_label', 'review')}",
            },
        )

    ET.indent(root)
    ET.ElementTree(root).write(additional_file, encoding="utf-8", xml_declaration=True)

    config = ET.Element("configuration")
    config_input = ET.SubElement(config, "input")
    ET.SubElement(config_input, "net-file", {"value": _portable_path(net_path, output_dir)})
    ET.SubElement(config_input, "additional-files", {"value": _portable_path(additional_file, output_dir)})
    time = ET.SubElement(config, "time")
    ET.SubElement(time, "end", {"value": "0"})
    ET.indent(config)
    ET.ElementTree(config).write(sumocfg_file, encoding="utf-8", xml_declaration=True)

    return {
        "status": "pass",
        "additional_file": str(additional_file),
        "sumocfg_file": str(sumocfg_file),
        "netedit_command": f'netedit --sumocfg-file "{sumocfg_file}"',
        "cluster_count": len(junctions),
        "box_overlay_count": box_count,
        "edge_overlay_count": 0,
        "junction_overlay_count": 0,
    }


def _network_svg(map_layers: Mapping[str, Any] | None, junctions: Sequence[Mapping[str, Any]]) -> str:
    bounds = _map_layer_bounds(map_layers)
    if bounds is None:
        return '<div class="network-empty">No SUMO network geometry was available for the vector map.</div>'
    min_x, min_y, max_x, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    view_box = f"{_svg_number(min_x)} {_svg_number(-max_y)} {_svg_number(width)} {_svg_number(height)}"
    span = max(width, height)
    junction_radius = max(span * 0.0028, 1.2)
    tls_radius = max(span * 0.0045, 1.8)
    cluster_radius = max(span * 0.009, 4.0)
    edge_styles = {
        "major": ("#00845f", "3.2", "1"),
        "vehicle": ("#6d7f92", "2.2", "0.9"),
        "soft": ("#c8d1cc", "1.25", "0.72"),
    }
    marker_fills = {
        "green": "#00946d",
        "amber": "#f59e0b",
        "red": "#e11d28",
        "slate": "#94a3b8",
    }

    edge_rows = []
    for edge in (map_layers or {}).get("edges", []) or []:
        if not isinstance(edge, Mapping):
            continue
        points = _svg_points(edge.get("points"))
        if not points:
            continue
        category = str(edge.get("category", "soft"))
        if category not in {"major", "vehicle", "soft"}:
            category = "soft"
        stroke, stroke_width, opacity = edge_styles[category]
        edge_rows.append(
            f'<polyline class="map-edge edge-{escape(category)}" points="{escape(points)}" '
            f'fill="none" stroke="{stroke}" stroke-width="{stroke_width}" opacity="{opacity}" '
            'stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"></polyline>'
        )

    junction_rows = []
    for junction in (map_layers or {}).get("junctions", []) or []:
        if not isinstance(junction, Mapping):
            continue
        try:
            x = float(junction["x"])
            y = float(junction["y"])
        except (KeyError, TypeError, ValueError):
            continue
        junction_rows.append(
            f'<circle class="map-junction" cx="{_svg_number(x)}" cy="{_svg_number(-y)}" '
            f'r="{_svg_number(junction_radius)}" fill="#ffffff" stroke="#64748b" '
            'stroke-width="1.2" opacity="0.62" vector-effect="non-scaling-stroke"></circle>'
        )

    tls_rows = []
    for point in (map_layers or {}).get("traffic_lights", []) or []:
        if not isinstance(point, Mapping):
            continue
        try:
            x = float(point["x"])
            y = float(point["y"])
        except (KeyError, TypeError, ValueError):
            continue
        tls_rows.append(
            f'<circle class="map-tls" cx="{_svg_number(x)}" cy="{_svg_number(-y)}" '
            f'r="{_svg_number(tls_radius)}" fill="#e11d28" stroke="#ffffff" '
            'stroke-width="2.4" vector-effect="non-scaling-stroke"></circle>'
        )

    cluster_rows = []
    for junction in junctions:
        cluster_id = str(junction.get("cluster_id", ""))
        if not cluster_id:
            continue
        try:
            x = float(junction["x"])
            y = float(junction["y"])
        except (KeyError, TypeError, ValueError):
            continue
        color_group = str(junction.get("color_group", "slate"))
        marker_fill = marker_fills.get(color_group, marker_fills["slate"])
        cluster_rows.append(
            f'<circle class="junction-marker marker-{escape(color_group)}" '
            f'cx="{_svg_number(x)}" cy="{_svg_number(-y)}" r="{_svg_number(cluster_radius)}" '
            f'fill="{marker_fill}" stroke="#ffffff" stroke-width="4" vector-effect="non-scaling-stroke" '
            f'data-junction-id="{escape(cluster_id)}" data-cluster-id="{escape(cluster_id)}" '
            f'data-color-group="{escape(color_group)}" role="button" tabindex="0" '
            f'aria-label="Select junction {escape(cluster_id)}"></circle>'
        )

    return (
        f'<svg class="network-svg" xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
        f'viewBox="{view_box}" preserveAspectRatio="xMidYMid meet" '
        'style="position:absolute;inset:0;width:100%;height:100%;background:rgba(255,255,255,0.34)" '
        'role="img" aria-label="SUMO network vector map">'
        f'<g class="cleaned-edge-layer">{"".join(edge_rows)}</g>'
        f'<g class="junction-layer">{"".join(junction_rows)}</g>'
        f'<g class="tls-layer">{"".join(tls_rows)}</g>'
        f'<g class="cluster-layer">{"".join(cluster_rows)}</g>'
        "</svg>"
    )


def _cluster_review_records(
    cluster_zoom_pngs: Sequence[Mapping[str, Any]],
    *,
    topology_audit_report: Mapping[str, Any] | None,
    base_dir: Path,
    map_bounds: tuple[float, float, float, float] | None = None,
) -> list[dict[str, Any]]:
    sources = _source_clusters(topology_audit_report)
    records: list[dict[str, Any]] = []
    for index, cluster in enumerate(cluster_zoom_pngs, start=1):
        cluster_id = str(cluster.get("cluster_id") or f"cluster_{index:03d}")
        merged = {**sources.get(cluster_id, {}), **cluster}
        color_group, color_label = _cluster_color_group(merged)
        records.append(
            {
                "cluster_id": cluster_id,
                "node_count": merged.get("node_count", len(merged.get("node_ids", []) or [])),
                "aggregation_decision": str(merged.get("aggregation_decision", "")),
                "aggregation_confidence": str(merged.get("aggregation_confidence", "unknown")),
                "modal_aggregation_decision": str(merged.get("modal_aggregation_decision", "review_required")),
                "modal_review_action": str(merged.get("modal_review_action", "review_vehicle_core_boundary")),
                "modal_reason": str(merged.get("modal_reason", "modal review required")),
                "google_maps_url": str(merged.get("google_maps_url", merged.get("map_review_url", ""))),
                "image_file": _portable_path(merged.get("image_file"), base_dir),
                "node_ids": _list_value(merged.get("node_ids")),
                "internal_edge_ids": _list_value(merged.get("internal_edge_ids")),
                "boundary_edge_ids": _list_value(merged.get("boundary_edge_ids")),
                "external_junction_ids": _list_value(merged.get("external_junction_ids")),
                "risk_flags": _list_value(merged.get("risk_flags")),
                "cluster_radius_m": merged.get("cluster_radius_m", ""),
                "x": merged.get("x", merged.get("centroid_x", "")),
                "y": merged.get("y", merged.get("centroid_y", "")),
                "color_group": color_group,
                "color_label": color_label,
                "status_label": _review_status(color_group),
            }
        )
    return _position_review_records(records, bounds=map_bounds)


def _position_review_records(
    records: list[dict[str, Any]],
    *,
    bounds: tuple[float, float, float, float] | None = None,
) -> list[dict[str, Any]]:
    points: list[tuple[int, float, float]] = []
    for index, record in enumerate(records):
        try:
            points.append((index, float(record["x"]), float(record["y"])))
        except (TypeError, ValueError):
            pass
    if not points:
        return records
    if bounds is None:
        xs = [point[1] for point in points]
        ys = [point[2] for point in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
    else:
        min_x, min_y, max_x, max_y = bounds
    for index, x, y in points:
        x_pct = 50.0 if min_x == max_x else 12.0 + ((x - min_x) / (max_x - min_x) * 76.0)
        y_pct = 50.0 if min_y == max_y else 12.0 + ((max_y - y) / (max_y - min_y) * 76.0)
        records[index]["map_x_pct"] = round(x_pct, 2)
        records[index]["map_y_pct"] = round(y_pct, 2)
    return records


def _review_app_data(
    *,
    title: str,
    claim_status: str,
    summary: Mapping[str, Any],
    gate_status: Mapping[str, Any] | None,
    topology_audit_report: Mapping[str, Any] | None,
    routeability_audit_report: Mapping[str, Any] | None,
    visualization_report: Mapping[str, Any],
    junctions: Sequence[Mapping[str, Any]],
    actions: Sequence[str],
    warnings: Sequence[str],
    output_dir: Path,
) -> dict[str, Any]:
    uncertain = int((topology_audit_report or {}).get("suspicious_cluster_count", len(junctions)) or 0)
    auto_join = sum(1 for junction in junctions if junction.get("color_group") == "green")
    manual_review = sum(1 for junction in junctions if junction.get("color_group") in {"amber", "slate"})
    return {
        "title": title,
        "claim_status": claim_status,
        "summary": dict(summary),
        "summary_cards": {
            "uncertain_junctions": uncertain,
            "selected": 0,
            "auto_join_candidates": auto_join,
            "manual_review": manual_review,
        },
        "gate_status": dict(gate_status or {}),
        "routeability": dict(routeability_audit_report or {}),
        "navigation": [
            {"label": "Junction Review", "active": True},
            {"label": "Network Cleanup", "active": False},
            {"label": "Routeability Audit", "active": False},
            {"label": "TLS Audit", "active": False},
            {"label": "Detector Demand", "active": False},
            {"label": "Evidence Bundle", "active": False},
            {"label": "Settings", "active": False},
        ],
        "visualizations": {
            "network_overview_png": _portable_path(visualization_report.get("network_overview_png"), output_dir),
            "problem_overlay_png": _portable_path(visualization_report.get("problem_overlay_png"), output_dir),
            "reference_comparison_png": _portable_path(visualization_report.get("reference_comparison_png"), output_dir),
        },
        "map_layers": dict(visualization_report.get("map_layers") or {}),
        "junctions": list(junctions),
        "review_queue": list(actions),
        "warnings": list(warnings),
    }


def _review_nav_items(items: Sequence[Mapping[str, Any]]) -> str:
    rows = []
    for item in items:
        active = " active" if item.get("active") else ""
        rows.append(
            f'<button type="button" class="nav-item{active}">'
            f'<span class="nav-dot"></span>{escape(str(item.get("label", "")))}'
            "</button>"
        )
    return "\n".join(rows)


def _summary_cards(cards: Mapping[str, Any]) -> str:
    labels = {
        "uncertain_junctions": "uncertain junctions",
        "selected": "selected",
        "auto_join_candidates": "auto-join candidates",
        "manual_review": "manual review",
    }
    return "\n".join(
        '<article class="summary-card">'
        f'<strong data-summary-card="{escape(key)}">{escape(str(cards.get(key, 0)))}</strong>'
        f"<span>{escape(label)}</span>"
        "</article>"
        for key, label in labels.items()
    )


def _junction_cards(junctions: Sequence[Mapping[str, Any]]) -> str:
    if not junctions:
        return '<p class="empty-state">No uncertain junction clusters were passed to the review page.</p>'
    cards = []
    for junction in junctions:
        cluster_id = str(junction.get("cluster_id", ""))
        status = str(junction.get("status_label", "Unknown"))
        color_group = str(junction.get("color_group", "slate"))
        reason = str(junction.get("modal_reason", "modal review required"))
        confidence = str(junction.get("aggregation_confidence", "unknown"))
        node_count = str(junction.get("node_count", ""))
        image_file = str(junction.get("image_file", ""))
        cards.append(
            f'<article class="junction-card card-{escape(color_group)}" data-junction-id="{escape(cluster_id)}">'
            '<label class="card-check">'
            f'<input type="checkbox" data-aggregate-checkbox="{escape(cluster_id)}"> '
            f"<strong>{escape(cluster_id)}</strong>"
            "</label>"
            f'<span class="status-pill">{escape(status)}</span>'
            f"<p>{escape(reason)}</p>"
            '<div class="card-meta">'
            f"<span>confidence {escape(confidence)}</span>"
            f"<span>{escape(node_count)} nodes</span>"
            "</div>"
            '<div class="card-actions">'
            f'<button type="button" data-zoom-src="{escape(image_file)}">Inspect</button>'
            "<button type=\"button\">Keep split</button>"
            f'<a href="{escape(str(junction.get("google_maps_url", "")))}">Evidence</a>'
            "</div>"
            "</article>"
        )
    return "\n".join(cards)


def _color_batch_buttons(cluster_zoom_pngs: Sequence[Mapping[str, Any]]) -> str:
    color_order = ["green", "amber", "red", "slate"]
    present = {_cluster_color_group(cluster)[0] for cluster in cluster_zoom_pngs}
    buttons = [
        f'<button type="button" class="color-action color-{color}" data-select-color="{color}" '
        f'onclick="selectColorGroup(\'{color}\')">Select {color}</button>'
        for color in color_order
        if color in present
    ]
    buttons.append('<button type="button" class="color-action" onclick="clearAggregationSelection()">Clear</button>')
    return "\n".join(buttons)


def _cluster_zoom_gallery(cluster_zoom_pngs: Sequence[Mapping[str, Any]], *, base_dir: Path) -> str:
    if not cluster_zoom_pngs:
        return "<p>No dense junction cluster zooms were generated.</p>"
    panels = []
    for cluster in cluster_zoom_pngs:
        cluster_id = str(cluster.get("cluster_id", "cluster"))
        decision = str(cluster.get("aggregation_decision", ""))
        confidence = str(cluster.get("aggregation_confidence", ""))
        color_group, color_label = _cluster_color_group(cluster)
        modal = str(cluster.get("modal_aggregation_decision", "review_required"))
        action = str(cluster.get("modal_review_action", "review_vehicle_core_boundary"))
        reason = str(cluster.get("modal_reason", "modal review required"))
        search_text = " ".join([cluster_id, decision, confidence, str(cluster.get("node_count", ""))])
        src = _image_src(str(cluster.get("image_file", "")), base_dir=base_dir)
        map_link = _link(str(cluster.get("google_maps_url", "")), "map review")
        caption = (
            f"{escape(cluster_id)} | decision="
            f"{escape(decision or 'unknown')} | confidence="
            f"{escape(confidence or 'unknown')}"
        )
        map_html = f"<div>{map_link}</div>" if map_link else ""
        panels.append(
            f'<figure class="visual-panel cluster-panel review-junction color-{color_group}" '
            f'data-cluster-id="{escape(cluster_id)}" '
            f'data-color-group="{escape(color_group)}" '
            f'data-decision="{escape(decision)}" '
            f'data-confidence="{escape(confidence)}" '
            f'data-review-text="{escape(search_text)}">'
            f'<figcaption><span class="color-dot color-{color_group}"></span>{caption}<br><small>{escape(color_label)}</small></figcaption>'
            f'<div class="cluster-meta">Modal: {escape(action)} / {escape(modal)} - {escape(reason)}</div>'
            '<label class="review-check" onclick="event.stopPropagation()">'
            f'<input type="checkbox" data-aggregate-checkbox="{escape(cluster_id)}"> aggregate this junction'
            "</label>"
            f'<button type="button" class="zoom-button" data-zoom-src="{src}" onclick="openZoom(this); event.stopPropagation()">Zoom</button>'
            f'<img src="{src}" alt="Cluster zoom {escape(cluster_id)}" data-zoom-src="{src}" onclick="openZoom(this); event.stopPropagation()">'
            f"{map_html}"
            "</figure>"
        )
    return "\n".join(panels)


def _dense_cluster_rows(cluster_zoom_pngs: Sequence[Mapping[str, Any]], *, base_dir: Path) -> str:
    if not cluster_zoom_pngs:
        return '<tr><td colspan="7">No dense junction clusters with coordinates were available.</td></tr>'
    rows = []
    for cluster in cluster_zoom_pngs:
        cluster_id = str(cluster.get("cluster_id", "cluster"))
        decision = str(cluster.get("aggregation_decision", ""))
        confidence = str(cluster.get("aggregation_confidence", ""))
        color_group, color_label = _cluster_color_group(cluster)
        search_text = " ".join([cluster_id, decision, confidence, str(cluster.get("node_count", ""))])
        image_link = _artifact_link(_as_path(str(cluster.get("image_file", ""))), base_dir=base_dir)
        map_link = _link(str(cluster.get("google_maps_url", "")), "map")
        rows.append(
            f'<tr class="review-cluster-row color-{color_group}" '
            f'data-cluster-id="{escape(cluster_id)}" '
            f'data-color-group="{escape(color_group)}" '
            f'data-decision="{escape(decision)}" '
            f'data-confidence="{escape(confidence)}" '
            f'data-review-text="{escape(search_text)}">'
            f"<td>{escape(cluster_id)}</td>"
            f"<td>{escape(str(cluster.get('node_count', '')))}</td>"
            f"<td>{escape(decision)}</td>"
            f"<td>{escape(confidence)} / {escape(color_label)}</td>"
            f"<td>{escape(str(round(float(cluster.get('x', 0.0)), 2)))}</td>"
            f"<td>{escape(str(round(float(cluster.get('y', 0.0)), 2)))}</td>"
            "<td>"
            f'<label><input type="checkbox" data-aggregate-checkbox="{escape(cluster_id)}"> aggregate</label> '
            f"{image_link} {map_link}"
            "</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _topology_actions(topology_audit_report: Mapping[str, Any] | None) -> list[str]:
    if not topology_audit_report:
        return []
    actions = []
    status = str(topology_audit_report.get("topology_fragmentation_status", topology_audit_report.get("status", "")))
    cluster_count = int(topology_audit_report.get("suspicious_cluster_count", 0) or 0)
    if status == "needs_review" or cluster_count > 0:
        actions.append(
            "Inspect dense junction clusters before treating the generated road geometry as clean."
        )
    return actions


def _junction_actions(junction_aggregation_report: Mapping[str, Any] | None) -> list[str]:
    if not junction_aggregation_report:
        return []
    candidate_count = int(junction_aggregation_report.get("junction_aggregation_candidate_count", 0) or 0)
    status = str(junction_aggregation_report.get("junction_aggregation_status", ""))
    if candidate_count > 0 or status == "variant_created_for_review":
        return [
            "Inspect junction aggregation candidates and map context before adopting any physical-intersection join."
        ]
    return []


def build_workflow_review_html(
    *,
    output_dir: Path,
    prefix: str = "workflow_review",
    title: str = "SUMO Network Review",
    claim_status: str = "diagnostic-demo",
    summary: Mapping[str, Any] | None = None,
    net_file: str | Path | None = None,
    raw_net_file: str | Path | None = None,
    connected_core_file: str | Path | None = None,
    reference_net_file: str | Path | None = None,
    tls_review_file: str | Path | None = None,
    topology_audit_report: Mapping[str, Any] | None = None,
    topology_audit_report_file: str | Path | None = None,
    junction_aggregation_report: Mapping[str, Any] | None = None,
    junction_aggregation_report_file: str | Path | None = None,
    routeability_audit_report: Mapping[str, Any] | None = None,
    routeability_audit_report_file: str | Path | None = None,
    gate_status: Mapping[str, Any] | None = None,
    warnings: Sequence[str] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    html_file = output_dir / f"{prefix}.html"
    workflow_report_file = output_dir / f"{prefix}_workflow_report.json"
    review_manifest_file = output_dir / f"{prefix}_review_manifest.json"

    warning_list = [str(item) for item in (warnings or [])]
    actions = [
        "Human review is required before this generated SUMO network is treated as a clean or experiment-ready network."
    ]
    if claim_status != "formal-evidence":
        actions.append(f"Keep the current claim boundary at `{claim_status}` until review gates are resolved.")
    actions.extend(_nonpass_gate_actions(gate_status))
    actions.extend(_topology_actions(topology_audit_report))
    actions.extend(_junction_actions(junction_aggregation_report))
    actions.extend(f"Review warning: {item}" for item in warning_list)
    actions = list(dict.fromkeys(actions))

    artifacts = {
        "net_file": _as_path(net_file),
        "raw_net_file": _as_path(raw_net_file),
        "connected_core_file": _as_path(connected_core_file),
        "reference_net_file": _as_path(reference_net_file),
        "tls_review_file": _as_path(tls_review_file),
        "topology_audit_report_file": _as_path(topology_audit_report_file),
        "junction_aggregation_report_file": _as_path(junction_aggregation_report_file),
        "routeability_audit_report_file": _as_path(routeability_audit_report_file),
        "workflow_report_file": workflow_report_file,
        "review_manifest_file": review_manifest_file,
    }

    workflow_summary = dict(summary or {})
    workflow_summary.setdefault("claim_status", claim_status)
    workflow_summary.setdefault("warnings", warning_list)
    _write_json(workflow_report_file, workflow_summary)

    visualization_report = build_network_review_visuals(
        output_dir=output_dir / "visuals",
        prefix=prefix,
        net_file=net_file or connected_core_file or raw_net_file,
        reference_net_file=reference_net_file,
        topology_audit_report=topology_audit_report,
    )
    for key in ("network_overview_png", "problem_overlay_png", "reference_comparison_png"):
        if visualization_report.get(key):
            artifacts[key] = _as_path(visualization_report.get(key))
    cluster_zoom_pngs = list(visualization_report.get("cluster_zoom_pngs", []) or [])
    if cluster_zoom_pngs:
        artifacts["cluster_zoom_dir"] = _as_path(Path(str(cluster_zoom_pngs[0]["image_file"])).parent)
    portable_cluster_zoom_pngs = [
        {
            **cluster,
            "image_file": _portable_path(cluster.get("image_file"), output_dir),
        }
        for cluster in cluster_zoom_pngs
    ]
    review_junctions = _cluster_review_records(
        cluster_zoom_pngs,
        topology_audit_report=topology_audit_report,
        base_dir=output_dir,
        map_bounds=_map_layer_bounds(visualization_report.get("map_layers")),
    )
    netedit_review = _write_netedit_review_files(
        output_dir=output_dir,
        prefix=prefix,
        net_file=net_file or connected_core_file or raw_net_file,
        map_layers=visualization_report.get("map_layers"),
        junctions=review_junctions,
    )
    if netedit_review.get("status") == "pass":
        artifacts["netedit_review_additional_file"] = _as_path(netedit_review.get("additional_file"))
        artifacts["netedit_review_sumocfg_file"] = _as_path(netedit_review.get("sumocfg_file"))
    review_app = _review_app_data(
        title=title,
        claim_status=claim_status,
        summary=workflow_summary,
        gate_status=gate_status,
        topology_audit_report=topology_audit_report,
        routeability_audit_report=routeability_audit_report,
        visualization_report=visualization_report,
        junctions=review_junctions,
        actions=actions,
        warnings=warning_list + list(visualization_report.get("warnings", [])),
        output_dir=output_dir,
    )
    review_app["netedit_review"] = {
        **netedit_review,
        "additional_file": _portable_path(netedit_review.get("additional_file"), output_dir),
        "sumocfg_file": _portable_path(netedit_review.get("sumocfg_file"), output_dir),
        "netedit_command": (
            f'netedit --sumocfg-file "{_portable_path(netedit_review.get("sumocfg_file"), output_dir)}"'
            if netedit_review.get("sumocfg_file")
            else ""
        ),
    }

    manifest = {
        "status": "pass",
        "claim_status": claim_status,
        "html_file": _portable_path(html_file, output_dir),
        "workflow_report_file": _portable_path(workflow_report_file, output_dir),
        "human_review_required_count": len(actions),
        "gate_summary": _gate_summary(gate_status),
        "visualizations": {
            "network_overview_png": _portable_path(visualization_report.get("network_overview_png"), output_dir),
            "problem_overlay_png": _portable_path(visualization_report.get("problem_overlay_png"), output_dir),
            "reference_comparison_png": _portable_path(visualization_report.get("reference_comparison_png"), output_dir),
            "cluster_zoom_pngs": portable_cluster_zoom_pngs,
        },
        "artifacts": {key: _portable_path(value, output_dir) for key, value in artifacts.items() if value is not None},
        "netedit_review": review_app["netedit_review"],
        "review_app": review_app,
        "review_queue": list(actions),
        "warnings": warning_list + list(visualization_report.get("warnings", [])),
    }
    _write_json(review_manifest_file, manifest)

    gate_counts = _gate_summary(gate_status)
    dashboard_status = "Not clean / not experiment-ready" if claim_status != "formal-evidence" else "Review required"
    action_items = "\n".join(f"<li>{escape(item)}</li>" for item in actions)
    warning_items = "\n".join(f"<li>{escape(item)}</li>" for item in warning_list) or "<li>No workflow warnings supplied.</li>"
    visual_panels = "\n".join(
        panel
        for panel in (
            _image_panel("Network Preview", visualization_report.get("network_overview_png"), base_dir=output_dir),
            _image_panel("Problem Map", visualization_report.get("problem_overlay_png"), base_dir=output_dir),
            _image_panel(
                "Reference Comparison",
                visualization_report.get("reference_comparison_png"),
                base_dir=output_dir,
            ),
        )
        if panel
    )
    if not visual_panels:
        visual_panels = "<p>No network visualization could be generated for this review.</p>"
    cluster_zoom_panels = _cluster_zoom_gallery(cluster_zoom_pngs, base_dir=output_dir)
    color_buttons = _color_batch_buttons(cluster_zoom_pngs)
    review_data_json = _json_script(review_app)
    nav_items = _review_nav_items(review_app["navigation"])
    summary_card_html = _summary_cards(review_app["summary_cards"])
    junction_card_html = _junction_cards(review_junctions)
    network_svg = _network_svg(review_app.get("map_layers"), review_junctions)
    netedit_review_link = ""
    if netedit_review.get("sumocfg_file"):
        netedit_review_link = (
            f'<a class="tool-button" href="{escape(_path_href(Path(str(netedit_review["sumocfg_file"])), output_dir))}">'
            "Netedit overlay"
            "</a>"
        )
    review_script = """
  <script>
    (function () {
      const reviewData = JSON.parse(document.getElementById("torii-review-data").textContent);
      const app = document.querySelector(".torii-review-app");
      const progress = document.getElementById("aggregation-selection-count");
      const selectedCard = document.querySelector('[data-summary-card="selected"]');
      const output = document.getElementById("review-plan-output");
      const mapCanvas = document.getElementById("map-canvas");
      const mapViewport = document.getElementById("map-viewport");
      const zoomModal = document.getElementById("zoom-modal");
      const zoomImage = document.getElementById("zoom-image");
      let mapScale = 1;
      let mapX = 0;
      let mapY = 0;
      let dragStart = null;

      function aggregateCheckboxes() {
        return Array.from(document.querySelectorAll("[data-aggregate-checkbox]"));
      }

      function clusterIds() {
        return aggregateCheckboxes()
          .map((checkbox) => checkbox.getAttribute("data-aggregate-checkbox"))
          .filter(Boolean)
          .filter((value, index, values) => values.indexOf(value) === index);
      }

      function selectedIds() {
        return clusterIds().filter((id) => {
          const checkbox = document.querySelector(`[data-aggregate-checkbox="${id}"]`);
          return checkbox && checkbox.checked;
        });
      }

      function syncClusterSelection(clusterId, selected) {
        document.querySelectorAll(`[data-aggregate-checkbox="${clusterId}"]`).forEach((checkbox) => {
          checkbox.checked = selected;
        });
        document.querySelectorAll(`[data-junction-id="${clusterId}"]`).forEach((element) => {
          element.classList.toggle("selected", selected);
        });
      }

      function updateAggregationCount() {
        const ids = clusterIds();
        const selected = selectedIds().length;
        progress.textContent = ids.length ? `${selected}/${ids.length} selected for aggregation` : "No junctions to review";
        if (selectedCard) {
          selectedCard.textContent = String(selected);
        }
      }

      function toggleClusterSelection(clusterId) {
        const checkbox = document.querySelector(`[data-aggregate-checkbox="${clusterId}"]`);
        const nextValue = !(checkbox && checkbox.checked);
        syncClusterSelection(clusterId, nextValue);
        updateAggregationCount();
      }

      function selectColorGroup(colorGroup) {
        document.querySelectorAll(`[data-color-group="${colorGroup}"]`).forEach((element) => {
          const clusterId = element.getAttribute("data-cluster-id");
          if (clusterId) {
            syncClusterSelection(clusterId, true);
          }
        });
        updateAggregationCount();
      }

      function clearAggregationSelection() {
        clusterIds().forEach((id) => syncClusterSelection(id, false));
        updateAggregationCount();
      }

      function selectVisibleJunctions() {
        document.querySelectorAll(".junction-card:not([hidden])").forEach((card) => {
          syncClusterSelection(card.getAttribute("data-junction-id"), true);
        });
        updateAggregationCount();
      }

      function selectedPlan() {
        const selected = new Set(selectedIds());
        return {
          claim_status: reviewData.claim_status,
          selected_junctions: reviewData.junctions.filter((junction) => selected.has(junction.cluster_id)),
        };
      }

      function applySelectedJunctions() {
        output.value = JSON.stringify(selectedPlan(), null, 2);
      }

      function exportReviewPlan() {
        const blob = new Blob([JSON.stringify(selectedPlan(), null, 2)], { type: "application/json" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = "torii-junction-review-plan.json";
        link.click();
        URL.revokeObjectURL(link.href);
      }

      function toggleReviewPanel() {
        app.classList.toggle("panel-collapsed");
      }

      function updateMapTransform() {
        mapCanvas.style.transform = `translate(${mapX}px, ${mapY}px) scale(${mapScale})`;
      }

      function zoomMap(delta) {
        mapScale = Math.min(3, Math.max(0.65, mapScale + delta));
        updateMapTransform();
      }

      function zoomInMap() {
        zoomMap(0.2);
      }

      function zoomOutMap() {
        zoomMap(-0.2);
      }

      function resetMap() {
        mapScale = 1;
        mapX = 0;
        mapY = 0;
        updateMapTransform();
      }

      function openZoom(trigger) {
        zoomImage.src = trigger.getAttribute("data-zoom-src");
        if (!zoomImage.src) {
          return;
        }
        zoomModal.hidden = false;
      }

      function closeZoom() {
        zoomModal.hidden = true;
        zoomImage.src = "";
      }

      aggregateCheckboxes().forEach((checkbox) => {
        checkbox.addEventListener("change", () => {
          syncClusterSelection(checkbox.getAttribute("data-aggregate-checkbox"), checkbox.checked);
          updateAggregationCount();
        });
      });
      document.querySelectorAll("[data-junction-id]:not(.junction-marker)").forEach((element) => {
        element.addEventListener("click", (event) => {
          if (event.target.closest("a, button, input")) {
            return;
          }
          toggleClusterSelection(element.getAttribute("data-junction-id"));
        });
      });
      document.querySelectorAll(".junction-marker").forEach((marker) => {
        marker.addEventListener("click", (event) => {
          event.stopPropagation();
          toggleClusterSelection(marker.getAttribute("data-junction-id"));
        });
        marker.addEventListener("keydown", (event) => {
          if (event.key !== "Enter" && event.key !== " ") {
            return;
          }
          event.preventDefault();
          toggleClusterSelection(marker.getAttribute("data-junction-id"));
        });
      });
      document.querySelectorAll("[data-zoom-src]").forEach((trigger) => {
        trigger.addEventListener("click", () => openZoom(trigger));
      });
      document.querySelectorAll("[data-layer]").forEach((toggle) => {
        toggle.addEventListener("change", () => {
          mapViewport.classList.toggle(`hide-${toggle.getAttribute("data-layer")}`, !toggle.checked);
        });
      });
      mapViewport.addEventListener("wheel", (event) => {
        event.preventDefault();
        zoomMap(event.deltaY < 0 ? 0.1 : -0.1);
      }, { passive: false });
      mapViewport.addEventListener("pointerdown", (event) => {
        if (event.target.closest("button, input, a")) {
          return;
        }
        dragStart = { x: event.clientX, y: event.clientY, mapX, mapY };
        mapViewport.setPointerCapture(event.pointerId);
      });
      mapViewport.addEventListener("pointermove", (event) => {
        if (!dragStart) {
          return;
        }
        mapX = dragStart.mapX + event.clientX - dragStart.x;
        mapY = dragStart.mapY + event.clientY - dragStart.y;
        updateMapTransform();
      });
      mapViewport.addEventListener("pointerup", () => {
        dragStart = null;
      });
      zoomModal.addEventListener("click", closeZoom);
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          closeZoom();
        }
      });

      window.toggleClusterSelection = toggleClusterSelection;
      window.selectColorGroup = selectColorGroup;
      window.clearAggregationSelection = clearAggregationSelection;
      window.selectVisibleJunctions = selectVisibleJunctions;
      window.applySelectedJunctions = applySelectedJunctions;
      window.exportReviewPlan = exportReviewPlan;
      window.toggleReviewPanel = toggleReviewPanel;
      window.zoomInMap = zoomInMap;
      window.zoomOutMap = zoomOutMap;
      window.resetMap = resetMap;
      window.openZoom = openZoom;
      updateAggregationCount();
      resetMap();
    })();
  </script>
"""

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; height: 100vh; overflow: hidden; font-family: Arial, sans-serif; color: #102033; background: #eef4f0; line-height: 1.35; }}
    button, input, textarea {{ font: inherit; }}
    button, a {{ border-radius: 6px; }}
    button {{ cursor: pointer; }}
    a {{ color: #075f46; text-decoration: none; }}
    code {{ background: #eef2f7; padding: 1px 4px; border-radius: 3px; }}
    .torii-review-app {{ display: grid; grid-template-columns: 240px minmax(620px, 1fr) 420px; height: 100vh; min-height: 0; overflow: hidden; background: #ffffff; }}
    .torii-sidebar {{ display: flex; flex-direction: column; border-right: 1px solid #d7e2dc; background: #ffffff; }}
    .brand {{ display: flex; gap: 10px; align-items: center; padding: 18px 16px; border-bottom: 1px solid #e2ebe6; }}
    .brand-mark {{ display: grid; place-items: center; width: 30px; height: 30px; border: 1px solid #9fdbc5; color: #00845f; background: #ecfbf5; border-radius: 7px; font-weight: 700; }}
    .brand strong {{ display: block; }}
    .brand span {{ display: block; margin-top: 3px; color: #6b7c8f; font-size: 11px; text-transform: uppercase; letter-spacing: 0; }}
    .nav-stack {{ display: grid; gap: 6px; padding: 14px 8px; }}
    .nav-item {{ display: flex; align-items: center; gap: 10px; width: 100%; padding: 11px 12px; border: 1px solid transparent; background: transparent; color: #334765; text-align: left; }}
    .nav-item.active {{ border-color: #b7ead8; background: #ebfbf4; color: #007a58; font-weight: 700; }}
    .nav-dot {{ width: 14px; height: 14px; border: 2px solid currentColor; border-radius: 50%; }}
    .sidebar-footer {{ margin-top: auto; padding: 16px; color: #546779; font: 12px Consolas, monospace; border-top: 1px solid #e2ebe6; }}
    .torii-map-shell {{ min-width: 0; min-height: 0; display: grid; grid-template-rows: auto 1fr; background: #f8fbf9; }}
    .map-topbar {{ display: flex; align-items: center; gap: 12px; padding: 16px; border-bottom: 1px solid #d7e2dc; background: #ffffff; }}
    .map-topbar h1 {{ margin: 0; font-size: 18px; }}
    .stat-pill {{ padding: 6px 10px; border: 1px solid #d7e2dc; color: #637487; background: #fbfdfc; font: 12px Consolas, monospace; }}
    .topbar-spacer {{ flex: 1; }}
    .tool-button {{ display: inline-flex; align-items: center; justify-content: center; border: 1px solid #d7e2dc; background: #ffffff; padding: 8px 10px; color: #102033; }}
    .map-viewport {{ position: relative; overflow: hidden; min-height: 0; height: 100%; touch-action: none; background-color: #f7fbf8; background-image: linear-gradient(#e7f0eb 1px, transparent 1px), linear-gradient(90deg, #e7f0eb 1px, transparent 1px); background-size: 32px 32px; }}
    .map-canvas {{ position: absolute; inset: 0; width: 100%; height: 100%; transform-origin: 50% 50%; transition: transform 120ms ease; }}
    .network-svg {{ position: absolute; inset: 0; width: 100%; height: 100%; background: rgba(255, 255, 255, 0.34); }}
    .network-empty {{ display: grid; place-items: center; width: 100%; height: 100%; color: #5c6d7e; }}
    .map-edge {{ fill: none; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; }}
    .edge-soft {{ stroke: #c8d1cc; stroke-width: 1.25; opacity: 0.72; }}
    .edge-vehicle {{ stroke: #6d7f92; stroke-width: 2.2; opacity: 0.9; }}
    .edge-major {{ stroke: #00845f; stroke-width: 3.2; }}
    .map-junction {{ fill: #ffffff; stroke: #64748b; stroke-width: 1.2; opacity: 0.62; vector-effect: non-scaling-stroke; }}
    .map-tls {{ fill: #e11d28; stroke: #ffffff; stroke-width: 2.4; vector-effect: non-scaling-stroke; }}
    .map-viewport.hide-cleaned .cleaned-edge-layer, .map-viewport.hide-junctions .junction-layer, .map-viewport.hide-tls .tls-layer, .map-viewport.hide-clusters .cluster-layer {{ display: none; }}
    .map-controls {{ position: absolute; left: 16px; top: 24px; display: grid; gap: 8px; z-index: 2; }}
    .map-controls button {{ width: 40px; height: 36px; border: 1px solid #d7e2dc; background: #ffffff; font-weight: 700; }}
    .layers {{ position: absolute; right: 18px; top: 26px; width: 220px; padding: 12px; border: 1px solid #d7e2dc; border-radius: 8px; background: #ffffff; box-shadow: 0 8px 22px rgba(16, 32, 51, 0.08); z-index: 2; }}
    .layers strong, .legend strong {{ display: block; margin-bottom: 8px; }}
    .layers label {{ display: flex; justify-content: space-between; gap: 12px; margin: 8px 0; color: #334765; font-size: 13px; }}
    .legend {{ position: absolute; left: 16px; bottom: 20px; width: 260px; padding: 12px; border: 1px solid #d7e2dc; border-radius: 8px; background: #ffffff; box-shadow: 0 8px 22px rgba(16, 32, 51, 0.08); z-index: 2; }}
    .legend button {{ display: flex; align-items: center; gap: 8px; width: 100%; border: 0; background: transparent; padding: 4px 0; color: #102033; text-align: left; }}
    .color-dot {{ display: inline-block; width: 11px; height: 11px; border-radius: 50%; vertical-align: -1px; }}
    .color-green, .color-dot.color-green {{ background: #00946d; }}
    .color-amber, .color-dot.color-amber {{ background: #f59e0b; }}
    .color-red, .color-dot.color-red {{ background: #e11d28; }}
    .color-slate, .color-dot.color-slate {{ background: #94a3b8; }}
    .marker-green {{ fill: #00946d; }}
    .marker-amber {{ fill: #f59e0b; }}
    .marker-red {{ fill: #e11d28; }}
    .marker-slate {{ fill: #94a3b8; }}
    .junction-marker {{ cursor: pointer; stroke: #ffffff; stroke-width: 4; vector-effect: non-scaling-stroke; filter: drop-shadow(0 4px 8px rgba(16, 32, 51, 0.24)); }}
    .junction-marker.selected {{ stroke: #006f52; stroke-width: 6; }}
    .torii-review-panel {{ display: grid; grid-template-rows: auto auto auto 1fr auto; min-width: 0; min-height: 0; max-height: 100vh; border-left: 1px solid #d7e2dc; background: #ffffff; }}
    .panel-collapsed {{ grid-template-columns: 240px minmax(620px, 1fr) 44px; }}
    .panel-collapsed .panel-body, .panel-collapsed .panel-actions, .panel-collapsed .panel-intro, .panel-collapsed .summary-grid, .panel-collapsed .panel-title h2, .panel-collapsed .panel-title p {{ display: none; }}
    .panel-title {{ display: grid; grid-template-columns: 1fr auto; gap: 10px; padding: 18px 16px 14px; border-bottom: 1px solid #d7e2dc; }}
    .panel-title h2 {{ margin: 0; font-size: 20px; }}
    .panel-title p {{ margin: 8px 0 0; color: #5c6d7e; font-size: 13px; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 14px; border-bottom: 1px solid #d7e2dc; }}
    .summary-card {{ min-width: 0; border: 1px solid #dce6e1; border-radius: 8px; padding: 14px; background: #fbfdfc; }}
    .summary-card strong {{ display: block; font-size: 20px; margin-bottom: 4px; }}
    .summary-card span {{ color: #5c6d7e; font-size: 12px; }}
    .panel-body {{ min-height: 0; overflow: auto; padding: 12px 14px; }}
    .filters {{ display: grid; gap: 8px; margin-bottom: 12px; }}
    .filters summary {{ border: 1px solid #dce6e1; border-radius: 7px; padding: 9px 10px; color: #334765; background: #ffffff; cursor: pointer; }}
    .batch-controls {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 12px; }}
    .batch-controls button {{ border: 1px solid #d7e2dc; background: #ffffff; padding: 7px 10px; }}
    .batch-controls .review-button {{ border-color: #b7ead8; color: #007a58; background: #eefcf6; }}
    .selection-count {{ display: block; color: #5c6d7e; font-size: 12px; margin: 0 0 10px; }}
    .junction-list {{ display: grid; gap: 10px; }}
    .junction-card {{ position: relative; border: 1px solid #dce6e1; border-radius: 8px; padding: 12px; background: #ffffff; }}
    .junction-card.selected {{ border-color: #00845f; background: #f1fcf7; }}
    .card-green {{ border-left: 4px solid #00946d; }}
    .card-amber {{ border-left: 4px solid #f59e0b; }}
    .card-red {{ border-left: 4px solid #e11d28; }}
    .card-slate {{ border-left: 4px solid #94a3b8; }}
    .card-check {{ display: inline-flex; align-items: center; gap: 8px; }}
    .status-pill {{ position: absolute; right: 12px; top: 12px; border: 1px solid #dce6e1; border-radius: 999px; padding: 3px 8px; color: #9a4a00; background: #fff8ed; font-size: 12px; }}
    .junction-card p {{ margin: 12px 0; color: #334765; font-size: 13px; }}
    .card-meta {{ display: flex; justify-content: space-between; gap: 12px; margin-bottom: 10px; color: #5c6d7e; font: 12px Consolas, monospace; }}
    .card-actions {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .card-actions button, .card-actions a {{ border: 1px solid #dce6e1; background: #ffffff; padding: 7px 10px; color: #102033; }}
    .panel-actions {{ display: grid; gap: 10px; padding: 12px 14px 14px; border-top: 1px solid #d7e2dc; background: #ffffff; }}
    .warning-box {{ border: 1px solid #f6c453; border-radius: 8px; padding: 10px 12px; color: #8a4d00; background: #fff8e8; font-size: 13px; }}
    .primary-action {{ border: 0; background: #00845f; color: #ffffff; padding: 12px; font-weight: 700; }}
    .secondary-action {{ border: 1px solid #d7e2dc; background: #ffffff; color: #334765; padding: 11px; font-weight: 700; }}
    .review-output {{ min-height: 92px; width: 100%; resize: vertical; border: 1px solid #d7e2dc; border-radius: 8px; padding: 8px; font: 12px Consolas, monospace; }}
    .evidence-drawer {{ display: none; }}
    .visual-panel img {{ max-width: 100%; height: auto; }}
    .zoom-modal {{ position: fixed; inset: 0; display: grid; place-items: center; background: rgba(15, 23, 42, 0.82); z-index: 10; padding: 24px; }}
    .zoom-modal[hidden] {{ display: none; }}
    .zoom-modal img {{ max-width: 96vw; max-height: 92vh; background: #ffffff; border: 2px solid #ffffff; }}
    @media (max-width: 1080px) {{
      body {{ height: auto; overflow: auto; }}
      .torii-review-app {{ grid-template-columns: 1fr; }}
      .torii-review-app {{ height: auto; min-height: 100vh; overflow: visible; }}
      .torii-sidebar {{ display: none; }}
      .torii-map-shell {{ min-height: 640px; }}
      .map-viewport {{ min-height: 560px; }}
      .torii-review-panel {{ min-height: 520px; max-height: none; border-left: 0; border-top: 1px solid #d7e2dc; }}
    }}
  </style>
</head>
<body>
  <script type="application/json" id="torii-review-data">{review_data_json}</script>
  <main class="torii-review-app">
    <aside class="torii-sidebar" aria-label="Torii navigation">
      <div class="brand">
        <div class="brand-mark">T</div>
        <div><strong>Torii-SUMO</strong><span>Cleanup Review</span></div>
      </div>
      <nav class="nav-stack">
        {nav_items}
      </nav>
      <div class="sidebar-footer">
        OSM import · cleaned.net.xml<br>
        claim_status · {escape(claim_status)}
      </div>
    </aside>

    <section class="torii-map-shell" aria-label="Cleaned SUMO road network">
      <header class="map-topbar">
        <h1>Cleaned SUMO road network</h1>
        <span class="stat-pill">{escape(str(review_app["summary_cards"]["uncertain_junctions"]))} uncertain · gates pass {gate_counts["pass"]} / fail {gate_counts["fail"]}</span>
        <span class="topbar-spacer"></span>
        {netedit_review_link}
        <button type="button" class="tool-button">Find junction</button>
        <button type="button" class="tool-button">Display</button>
      </header>
      <div class="map-viewport" id="map-viewport">
        <div class="map-controls" aria-label="Map controls">
          <button type="button" onclick="zoomInMap()" aria-label="Zoom in">+</button>
          <button type="button" onclick="zoomOutMap()" aria-label="Zoom out">-</button>
          <button type="button" onclick="resetMap()" aria-label="Fit network">Fit</button>
        </div>
        <div class="layers">
          <strong>Layers</strong>
          <label>Cleaned edges <input type="checkbox" data-layer="cleaned" checked></label>
          <label>Junction dots <input type="checkbox" data-layer="junctions" checked></label>
          <label>Uncertainty clusters <input type="checkbox" data-layer="clusters" checked></label>
          <label>Traffic lights <input type="checkbox" data-layer="tls" checked></label>
        </div>
        <div class="map-canvas" id="map-canvas">
          {network_svg}
        </div>
        <div class="legend">
          <strong>Uncertainty Legend</strong>
          <button type="button" data-select-color="green" onclick="selectColorGroup('green')"><span class="color-dot color-green"></span>High confidence auto-aggregate</button>
          <button type="button" data-select-color="amber" onclick="selectColorGroup('amber')"><span class="color-dot color-amber"></span>Needs review</button>
          <button type="button" data-select-color="red" onclick="selectColorGroup('red')"><span class="color-dot color-red"></span>Risky / do not aggregate</button>
          <button type="button" data-select-color="slate" onclick="selectColorGroup('slate')"><span class="color-dot color-slate"></span>Unknown</button>
        </div>
      </div>
    </section>

    <aside class="torii-review-panel" aria-label="Junction Aggregation Review">
      <header class="panel-title">
        <div>
          <h2>Junction Aggregation Review</h2>
          <p>Validate post-cleaning junction clusters before SUMO topology changes are applied.</p>
        </div>
        <button type="button" id="review-panel-toggle" class="tool-button" onclick="toggleReviewPanel()" aria-label="Collapse review panel">&gt;</button>
      </header>
      <section class="summary-grid">
        {summary_card_html}
      </section>
      <section class="panel-body">
        <h3>Filters</h3>
        <div class="filters">
          <details><summary>Confidence level</summary></details>
          <details><summary>Modal review action</summary></details>
          <details><summary>Aggregation decision</summary></details>
          <details><summary>Cluster size</summary></details>
        </div>
        <div class="batch-controls">
          <button type="button" onclick="selectVisibleJunctions()">Select visible</button>
          <button type="button" onclick="clearAggregationSelection()">Clear</button>
          <button type="button" class="review-button" onclick="applySelectedJunctions()">Review selected</button>
        </div>
        <span class="selection-count" id="aggregation-selection-count">0 selected for aggregation</span>
        <div class="junction-list">
          {junction_card_html}
        </div>
      </section>
      <section class="panel-actions">
        <div class="warning-box">Aggregation changes SUMO topology and lane-link behavior. Review risky clusters before applying.</div>
        <button type="button" class="primary-action" onclick="applySelectedJunctions()">Aggregate selected junctions</button>
        <button type="button" class="secondary-action" onclick="exportReviewPlan()">Export review plan</button>
        <textarea class="review-output" id="review-plan-output" aria-label="Selected junction review plan"></textarea>
      </section>
    </aside>
  </main>

  <section class="evidence-drawer" aria-label="Evidence Summary">
    <h2>Gate Dashboard</h2>
    <strong>{escape(dashboard_status)}</strong>
    <h2>Human Review Required</h2>
    <ul>{action_items}</ul>
    <h2>Network Preview</h2>
    {visual_panels}
    <h2>Problem Map</h2>
    <h2>Junction Aggregation Review</h2>
    <div>{color_buttons}</div>
    <h2>Cluster Zooms</h2>
    {cluster_zoom_panels}
    <h2>Review Queue</h2>
    {_review_queue_rows(actions)}
    <h2>Warnings</h2>
    <ul>{warning_items}</ul>
    <h2>Evidence Summary</h2>
    {_evidence_rows(topology_audit_report=topology_audit_report, junction_aggregation_report=junction_aggregation_report, routeability_audit_report=routeability_audit_report)}
    {_gate_rows(gate_status)}
    {_artifact_rows(artifacts, base_dir=output_dir)}
    {_dense_cluster_rows(cluster_zoom_pngs, base_dir=output_dir)}
  </section>
  <div class="zoom-modal" id="zoom-modal" hidden>
    <img id="zoom-image" alt="Expanded junction review image">
  </div>
{review_script}
</body>
</html>
"""
    html_file.write_text(html, encoding="utf-8")
    return {
        "status": "pass",
        "claim_status": claim_status,
        "workflow_review_html_status": "pass",
        "workflow_review_html_file": str(html_file),
        "workflow_report_file": str(workflow_report_file),
        "review_manifest_file": str(review_manifest_file),
        "network_overview_png": str(visualization_report.get("network_overview_png", "")),
        "problem_overlay_png": str(visualization_report.get("problem_overlay_png", "")),
        "reference_comparison_png": str(visualization_report.get("reference_comparison_png", "")),
        "cluster_zoom_pngs": cluster_zoom_pngs,
        "netedit_review_additional_file": str(netedit_review.get("additional_file", "")),
        "netedit_review_sumocfg_file": str(netedit_review.get("sumocfg_file", "")),
        "netedit_review_command": str(netedit_review.get("netedit_command", "")),
        "human_review_required_count": len(actions),
        "warnings": warning_list + list(visualization_report.get("warnings", [])),
    }

from __future__ import annotations

import json
import os
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
            ("topology_fragmentation_status", "suspicious_cluster_count", "junction_aggregation_candidate_count"),
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
    review_script = """
  <script>
    (function () {
      const progress = document.getElementById("aggregation-selection-count");
      const zoomModal = document.getElementById("zoom-modal");
      const zoomImage = document.getElementById("zoom-image");

      function aggregateCheckboxes() {
        return Array.from(document.querySelectorAll("[data-aggregate-checkbox]"));
      }

      function clusterIds() {
        return aggregateCheckboxes()
          .map((checkbox) => checkbox.getAttribute("data-aggregate-checkbox"))
          .filter(Boolean)
          .filter((value, index, values) => values.indexOf(value) === index);
      }

      function syncClusterSelection(clusterId, selected) {
        document.querySelectorAll(`[data-aggregate-checkbox="${clusterId}"]`).forEach((checkbox) => {
          checkbox.checked = selected;
        });
      }

      function updateAggregationCount() {
        const ids = clusterIds();
        const selected = ids.filter((id) => {
          const checkbox = document.querySelector(`[data-aggregate-checkbox="${id}"]`);
          return checkbox && checkbox.checked;
        }).length;
        progress.textContent = ids.length ? `${selected}/${ids.length} selected for aggregation` : "No junctions to review";
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
        aggregateCheckboxes().forEach((checkbox) => {
          checkbox.checked = false;
        });
        updateAggregationCount();
      }

      function openZoom(trigger) {
        zoomImage.src = trigger.getAttribute("data-zoom-src");
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
      document.querySelectorAll(".review-junction").forEach((card) => {
        card.addEventListener("click", () => toggleClusterSelection(card.getAttribute("data-cluster-id")));
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
      window.openZoom = openZoom;
      updateAggregationCount();
    })();
  </script>
"""

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; line-height: 1.45; }}
    h1, h2 {{ margin-bottom: 8px; }}
    code {{ background: #eef2f7; padding: 1px 4px; border-radius: 3px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 8px 0 18px; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 6px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f8fafc; }}
    pre {{ background: #0f172a; color: #e2e8f0; padding: 12px; overflow: auto; }}
    .status {{ font-weight: 700; }}
    .dashboard {{ border-left: 6px solid #b91c1c; background: #fff7ed; padding: 12px 16px; margin: 12px 0 18px; }}
    .gate-counts {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 8px; }}
    .gate-counts span {{ background: #ffffff; border: 1px solid #cbd5e1; padding: 4px 8px; }}
    .visual-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 18px; }}
    .visual-panel {{ margin: 0; border: 1px solid #cbd5e1; padding: 10px; background: #ffffff; }}
    .visual-panel figcaption {{ font-weight: 700; margin-bottom: 8px; }}
    .visual-panel img {{ max-width: 100%; height: auto; display: block; border: 1px solid #e5e7eb; }}
    .cluster-panel figcaption {{ min-height: 44px; }}
    .junction-review-toolbar {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 10px 0 18px; padding: 10px; border: 1px solid #cbd5e1; background: #f8fafc; }}
    .color-action, .zoom-button {{ padding: 6px 10px; border: 1px solid #64748b; background: #ffffff; cursor: pointer; }}
    .color-green {{ border-left: 6px solid #15803d; }}
    .color-amber {{ border-left: 6px solid #d97706; }}
    .color-red {{ border-left: 6px solid #b91c1c; }}
    .color-slate {{ border-left: 6px solid #475569; }}
    .color-dot {{ display: inline-block; width: 12px; height: 12px; margin-right: 6px; border-radius: 50%; vertical-align: -1px; }}
    .color-dot.color-green {{ background: #15803d; }}
    .color-dot.color-amber {{ background: #d97706; }}
    .color-dot.color-red {{ background: #b91c1c; }}
    .color-dot.color-slate {{ background: #475569; }}
    .selection-count {{ font-weight: 700; }}
    .review-check {{ display: block; margin: 0 0 8px; font-size: 13px; }}
    .zoom-modal {{ position: fixed; inset: 0; display: grid; place-items: center; background: rgba(15, 23, 42, 0.82); z-index: 10; padding: 24px; }}
    .zoom-modal[hidden] {{ display: none; }}
    .zoom-modal img {{ max-width: 96vw; max-height: 92vh; background: #ffffff; border: 2px solid #ffffff; }}
  </style>
</head>
<body>
  <h1>{escape(title)}</h1>
  <p class="status">claim_status: <code>{escape(claim_status)}</code></p>

  <h2>Gate Dashboard</h2>
  <section class="dashboard">
    <strong>{escape(dashboard_status)}</strong>
    <div class="gate-counts">
      <span>pass: {gate_counts["pass"]}</span>
      <span>blocked: {gate_counts["blocked"]}</span>
      <span>fail: {gate_counts["fail"]}</span>
      <span>skipped: {gate_counts["skipped"]}</span>
      <span>other: {gate_counts["other"]}</span>
    </div>
  </section>

  <h2>Human Review Required</h2>
  <ul>
    {action_items}
  </ul>

  <h2>Network Preview</h2>
  <section class="visual-grid">
    {visual_panels}
  </section>

  <h2>Problem Map</h2>
  <p>The problem overlay highlights dense topology clusters and other review locations when coordinates are available.</p>

  <h2>Junction Aggregation Review</h2>
  <section class="junction-review-toolbar" id="junction-review-toolbar">
    {color_buttons}
    <span class="selection-count" id="aggregation-selection-count">0 selected for aggregation</span>
  </section>

  <h2>Cluster Zooms</h2>
  <section class="visual-grid">
    {cluster_zoom_panels}
  </section>

  <h2>Dense Junction Review Points</h2>
  <table>
    <thead><tr><th>cluster</th><th>nodes</th><th>decision</th><th>confidence</th><th>x</th><th>y</th><th>links</th></tr></thead>
    <tbody>
      {_dense_cluster_rows(cluster_zoom_pngs, base_dir=output_dir)}
    </tbody>
  </table>

  <h2>Review Queue</h2>
  <table>
    <thead><tr><th>priority</th><th>#</th><th>action</th></tr></thead>
    <tbody>
      {_review_queue_rows(actions)}
    </tbody>
  </table>

  <h2>Gate Status</h2>
  <table>
    <thead><tr><th>gate</th><th>status</th></tr></thead>
    <tbody>
      {_gate_rows(gate_status)}
    </tbody>
  </table>

  <h2>Artifacts</h2>
  <table>
    <thead><tr><th>artifact</th><th>file</th></tr></thead>
    <tbody>
      {_artifact_rows(artifacts, base_dir=output_dir)}
    </tbody>
  </table>

  <h2>Warnings</h2>
  <ul>
    {warning_items}
  </ul>

  <h2>Evidence Summary</h2>
  <table>
    <thead><tr><th>evidence</th><th>compact status</th></tr></thead>
    <tbody>
      {_evidence_rows(topology_audit_report=topology_audit_report, junction_aggregation_report=junction_aggregation_report, routeability_audit_report=routeability_audit_report)}
    </tbody>
  </table>
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
        "human_review_required_count": len(actions),
        "warnings": warning_list + list(visualization_report.get("warnings", [])),
    }

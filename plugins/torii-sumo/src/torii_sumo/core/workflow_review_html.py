from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any, Mapping, Sequence


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


def _as_path(value: str | Path | None) -> Path | None:
    if value is None or str(value) == "":
        return None
    return Path(value)


def _artifact_link(path: Path | None) -> str:
    if path is None:
        return ""
    label = escape(str(path))
    try:
        href = path.resolve().as_uri()
    except ValueError:
        href = escape(str(path))
    return f'<a href="{escape(href)}">{label}</a>'


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


def _artifact_rows(artifacts: Mapping[str, Path | None]) -> str:
    rows = []
    for label, path in artifacts.items():
        if path is None:
            continue
        rows.append(f"<tr><td>{escape(label)}</td><td>{_artifact_link(path)}</td></tr>")
    if not rows:
        return '<tr><td colspan="2">No file artifacts supplied.</td></tr>'
    return "\n".join(rows)


def _nonpass_gate_actions(gate_status: Mapping[str, Any] | None) -> list[str]:
    if not gate_status:
        return []
    actions = []
    pass_like = {"pass", "skipped"}
    for gate, status in sorted(gate_status.items()):
        if str(status) not in pass_like:
            actions.append(f"Review gate `{gate}` because it is `{status}`.")
    return actions


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
        "tls_review_file": _as_path(tls_review_file),
        "topology_audit_report_file": _as_path(topology_audit_report_file),
        "junction_aggregation_report_file": _as_path(junction_aggregation_report_file),
        "routeability_audit_report_file": _as_path(routeability_audit_report_file),
    }

    action_items = "\n".join(f"<li>{escape(item)}</li>" for item in actions)
    warning_items = "\n".join(f"<li>{escape(item)}</li>" for item in warning_list) or "<li>No workflow warnings supplied.</li>"

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
  </style>
</head>
<body>
  <h1>{escape(title)}</h1>
  <p class="status">claim_status: <code>{escape(claim_status)}</code></p>

  <h2>Human Review Required</h2>
  <ul>
    {action_items}
  </ul>

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
      {_artifact_rows(artifacts)}
    </tbody>
  </table>

  <h2>Warnings</h2>
  <ul>
    {warning_items}
  </ul>

  <h2>topology_audit</h2>
  <pre>{_json_block(topology_audit_report or {})}</pre>

  <h2>junction_aggregation</h2>
  <pre>{_json_block(junction_aggregation_report or {})}</pre>

  <h2>routeability_audit</h2>
  <pre>{_json_block(routeability_audit_report or {})}</pre>

  <h2>workflow_summary</h2>
  <pre>{_json_block(summary or {})}</pre>
</body>
</html>
"""
    html_file.write_text(html, encoding="utf-8")
    return {
        "status": "pass",
        "claim_status": claim_status,
        "workflow_review_html_status": "pass",
        "workflow_review_html_file": str(html_file),
        "human_review_required_count": len(actions),
        "warnings": warning_list,
    }

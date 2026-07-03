# Modal-Aware Junction Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add audit-only modal aggregation policy to Torii-SUMO so dense junction clusters are classified by vehicle, pedestrian, bicycle, service, rail, ramp, and grade-separation evidence before they are offered as join candidates.

**Architecture:** Add one small core policy module, call it from `topology_audit.py`, and surface the resulting fields in JSON/CSV/HTML. The first pass blocks hard modal no-join cases from automatic candidate counts but does not build new network geometry or scrape maps.

**Tech Stack:** Python stdlib, existing Torii-SUMO topology/corridor audit code, pytest, existing workflow review HTML renderer.

---

## File Structure

- Create: `C:\Users\huqio\Documents\Torii-SUMO\plugins\torii-sumo\src\torii_sumo\core\modal_aggregation_policy.py`
  - Classifies SUMO edge dictionaries and dense cluster edge context into modal aggregation decisions.
- Modify: `C:\Users\huqio\Documents\Torii-SUMO\plugins\torii-sumo\src\torii_sumo\core\topology_audit.py`
  - Preserve edge `allow`, `disallow`, and `function`; add modal policy fields to each suspicious cluster and summary counts.
- Modify: `C:\Users\huqio\Documents\Torii-SUMO\plugins\torii-sumo\src\torii_sumo\core\workflow_review_html.py`
  - Show modal decision counts and per-cluster modal reasons in the review HTML.
- Create: `C:\Users\huqio\Documents\Torii-SUMO\tests\test_modal_aggregation_policy.py`
  - Unit tests for modal role and cluster decisions.
- Modify: `C:\Users\huqio\Documents\Torii-SUMO\tests\test_osm_network_tools.py`
  - Extend the dense-junction audit fixture assertion to include modal fields.
- Modify: `C:\Users\huqio\Documents\Torii-SUMO\tests\test_workflow_review_html.py`
  - Assert the review HTML includes modal decision summary text.
- Optional docs after tests pass: `C:\Users\huqio\Documents\Torii-SUMO\plugins\torii-sumo\skills\simulation-helper-skill-for-eclipse-sumo\references\model-osm-detectors.md`
  - Add one short note that modal blockers are audit evidence, not automatic cleaned-network proof.

## Task 1: Add Modal Policy Tests

**Files:**
- Create: `C:\Users\huqio\Documents\Torii-SUMO\tests\test_modal_aggregation_policy.py`

- [ ] **Step 1: Write failing tests**

Create the test file with:

```python
from torii_sumo.core.modal_aggregation_policy import classify_edge_modal_role, classify_cluster_modal_policy


def test_ordinary_urban_vehicle_edges_are_join_core() -> None:
    edge = {"id": "e1", "type": "highway.tertiary", "allow": "passenger bus", "disallow": ""}
    role = classify_edge_modal_role(edge)
    assert role["modal_primary_role"] == "vehicle_core"
    assert role["modal_aggregation_decision"] == "join_core"


def test_service_driveway_is_protected_terminal() -> None:
    edge = {"id": "e1", "type": "highway.service", "name": "service=driveway"}
    role = classify_edge_modal_role(edge)
    assert role["modal_primary_role"] == "service"
    assert role["modal_aggregation_decision"] == "protected_terminal"


def test_railway_is_never_join() -> None:
    edge = {"id": "r1", "type": "railway.tram"}
    role = classify_edge_modal_role(edge)
    assert role["modal_primary_role"] == "rail"
    assert role["modal_aggregation_decision"] == "never_join"


def test_motorway_link_is_never_join_for_urban_aggregation() -> None:
    edge = {"id": "m1", "type": "highway.motorway_link"}
    role = classify_edge_modal_role(edge)
    assert role["modal_primary_role"] == "ramp"
    assert role["modal_aggregation_decision"] == "never_join"


def test_pedestrian_crossing_is_shape_support() -> None:
    edge = {"id": "c1", "function": "crossing", "type": "highway.crossing"}
    role = classify_edge_modal_role(edge)
    assert role["modal_primary_role"] == "pedestrian"
    assert role["modal_aggregation_decision"] == "shape_support"


def test_cluster_with_vehicle_core_and_service_terminal_requires_review() -> None:
    policy = classify_cluster_modal_policy(
        internal_edges=[{"id": "e1", "type": "highway.tertiary"}],
        boundary_edges=[
            {"id": "e2", "type": "highway.secondary"},
            {"id": "s1", "type": "highway.service", "name": "service=parking_aisle"},
        ],
    )
    assert policy["modal_aggregation_decision"] == "review_required"
    assert "service_terminal_present" in policy["modal_risk_flags"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest tests\test_modal_aggregation_policy.py -q
```

Expected: failure because `torii_sumo.core.modal_aggregation_policy` does not exist.

## Task 2: Implement Minimal Modal Policy

**Files:**
- Create: `C:\Users\huqio\Documents\Torii-SUMO\plugins\torii-sumo\src\torii_sumo\core\modal_aggregation_policy.py`

- [ ] **Step 1: Add the policy module**

Create the file with:

```python
from __future__ import annotations

from collections import Counter
from typing import Any

VEHICLE_CORE_TYPES = {
    "highway.primary",
    "highway.secondary",
    "highway.tertiary",
    "highway.unclassified",
    "highway.residential",
    "highway.living_street",
}


def classify_edge_modal_role(edge: dict[str, Any]) -> dict[str, Any]:
    type_id = str(edge.get("type", "") or "")
    function = str(edge.get("function", "") or "")
    text = " ".join(
        str(edge.get(key, "") or "").lower()
        for key in ("id", "type", "function", "allow", "disallow", "name")
    )
    if type_id.startswith("railway."):
        return _role("rail", "never_join", "railway edge must not be joined into vehicle core", ["railway_present"])
    if type_id in {"highway.motorway", "highway.trunk"} or type_id.endswith("_link"):
        return _role("ramp", "never_join", "motorway/trunk/link geometry uses ramp or interchange semantics", ["ramp_or_interchange"])
    if any(token in text for token in ("bridge", "tunnel", "layer=")):
        return _role("grade_separated", "never_join", "bridge/tunnel/layer evidence blocks same-level joining", ["grade_separation"])
    if "roundabout" in text:
        return _role("roundabout", "never_join", "roundabout topology should be preserved", ["roundabout"])
    if function in {"crossing", "walkingarea"} or "footway" in type_id or "crossing" in type_id:
        return _role("pedestrian", "shape_support", "pedestrian crossing/walkingarea supports review but not vehicle-core joining", ["pedestrian_support"])
    if "cycleway" in type_id or "bicycle" in text:
        return _role("bicycle", "shape_support", "bicycle infrastructure is support evidence unless map/reference includes it in the core", ["bicycle_support"])
    if "service" in type_id or any(token in text for token in ("driveway", "parking_aisle", "parking", "private", "alley")):
        return _role("service", "protected_terminal", "service or parking access is a protected terminal by default", ["service_terminal"])
    if type_id in VEHICLE_CORE_TYPES or "passenger" in text:
        return _role("vehicle_core", "join_core", "ordinary passenger-drivable urban road", [])
    return _role("unknown", "review_required", "modal role is unknown from SUMO edge attributes", ["unknown_modal_role"])


def classify_cluster_modal_policy(
    *,
    internal_edges: list[dict[str, Any]],
    boundary_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    roles = [classify_edge_modal_role(edge) for edge in internal_edges + boundary_edges]
    decisions = Counter(role["modal_aggregation_decision"] for role in roles)
    primary_roles = Counter(role["modal_primary_role"] for role in roles)
    risk_flags = sorted({flag for role in roles for flag in role["modal_risk_flags"]})

    if decisions["never_join"]:
        decision = "never_join"
        reason = "hard modal blocker present"
    elif decisions["join_core"] and (decisions["protected_terminal"] or decisions["shape_support"]):
        decision = "review_required"
        reason = "vehicle core mixed with support or terminal infrastructure"
    elif decisions["join_core"]:
        decision = "join_core"
        reason = "modal context is compatible with vehicle-core joining"
    elif decisions["protected_terminal"]:
        decision = "protected_terminal"
        reason = "cluster is dominated by protected terminal infrastructure"
    elif decisions["shape_support"]:
        decision = "shape_support"
        reason = "cluster is modal support infrastructure, not a vehicle core"
    else:
        decision = "review_required"
        reason = "modal context is unknown or ambiguous"

    return {
        "modal_aggregation_decision": decision,
        "modal_primary_role": primary_roles.most_common(1)[0][0] if primary_roles else "unknown",
        "modal_reason": reason,
        "modal_risk_flags": risk_flags,
        "modal_decision_counts": dict(decisions),
        "modal_role_counts": dict(primary_roles),
    }


def _role(primary: str, decision: str, reason: str, flags: list[str]) -> dict[str, Any]:
    return {
        "modal_primary_role": primary,
        "modal_aggregation_decision": decision,
        "modal_reason": reason,
        "modal_risk_flags": flags,
    }
```

- [ ] **Step 2: Run policy tests**

Run:

```powershell
python -m pytest tests\test_modal_aggregation_policy.py -q
```

Expected: `6 passed`.

## Task 3: Enrich Topology Audit

**Files:**
- Modify: `C:\Users\huqio\Documents\Torii-SUMO\plugins\torii-sumo\src\torii_sumo\core\topology_audit.py`
- Modify: `C:\Users\huqio\Documents\Torii-SUMO\tests\test_osm_network_tools.py`

- [ ] **Step 1: Import modal policy**

Add:

```python
from .modal_aggregation_policy import classify_cluster_modal_policy
```

- [ ] **Step 2: Preserve edge attributes**

In `_read_network_graph`, extend each edge dictionary:

```python
"function": edge.attrib.get("function", ""),
"allow": edge.attrib.get("allow", ""),
"disallow": edge.attrib.get("disallow", ""),
```

- [ ] **Step 3: Attach modal fields to clusters**

In `_cluster_graph_summary`, after `internal_edges` and `boundary_edges` are built, compute:

```python
modal_policy = classify_cluster_modal_policy(
    internal_edges=internal_edges,
    boundary_edges=boundary_edges,
)
```

Merge it into the returned dictionary:

```python
**modal_policy,
```

and merge modal flags into `risk_flags`:

```python
"risk_flags": sorted(set(risk_flags) | set(modal_policy["modal_risk_flags"])),
```

- [ ] **Step 4: Add modal summary fields**

In the report dictionary, add:

```python
"modal_policy_status": "pass",
"modal_decision_counts": dict(Counter(cluster.get("modal_aggregation_decision", "review_required") for cluster in clusters)),
"junction_aggregation_blocked_by_modal_count": sum(
    1
    for cluster in clusters
    if cluster["aggregation_decision"] in {"join", "needs_map_review"}
    and cluster.get("modal_aggregation_decision") in {"never_join", "protected_terminal", "shape_support"}
),
```

Update `junction_aggregation_candidate_count` to exclude hard modal non-core decisions:

```python
and cluster.get("modal_aggregation_decision") not in {"never_join", "protected_terminal", "shape_support"}
```

- [ ] **Step 5: Add CSV columns**

Add these fields to `_write_clusters_csv`:

```python
"modal_aggregation_decision",
"modal_primary_role",
"modal_reason",
"modal_risk_flags",
```

- [ ] **Step 6: Extend topology audit test**

In `tests\test_osm_network_tools.py`, update the dense-junction cluster assertion to check:

```python
cluster = report["suspicious_clusters"][0]
assert cluster["modal_aggregation_decision"] in {"join_core", "review_required"}
assert "modal_decision_counts" in report
assert "junction_aggregation_blocked_by_modal_count" in report
```

- [ ] **Step 7: Run focused tests**

Run:

```powershell
python -m pytest tests\test_modal_aggregation_policy.py tests\test_osm_network_tools.py::test_topology_audit_flags_dense_junction_clusters_within_radius tests\test_osm_network_tools.py::test_topology_audit_reports_local_cluster_graph_edges -q
```

Expected: all selected tests pass.

## Task 4: Surface Modal Review in HTML

**Files:**
- Modify: `C:\Users\huqio\Documents\Torii-SUMO\plugins\torii-sumo\src\torii_sumo\core\workflow_review_html.py`
- Modify: `C:\Users\huqio\Documents\Torii-SUMO\tests\test_workflow_review_html.py`

- [ ] **Step 1: Add one modal summary row**

In `_evidence_rows`, include `modal_decision_counts` and `junction_aggregation_blocked_by_modal_count` when a topology report is present:

```python
("modal_decision_counts", "junction_aggregation_blocked_by_modal_count"),
```

Keep the existing table layout. Do not add a new UI framework.

- [ ] **Step 2: Add modal reason text to cluster cards**

Where suspicious clusters are rendered, include:

```python
modal = str(cluster.get("modal_aggregation_decision", "review_required"))
reason = str(cluster.get("modal_reason", "modal review required"))
```

Render the line:

```html
<div class="cluster-meta">Modal: {modal} - {reason}</div>
```

- [ ] **Step 3: Extend HTML test**

In `tests\test_workflow_review_html.py`, add a topology report fixture field:

```python
"modal_decision_counts": {"review_required": 1},
"junction_aggregation_blocked_by_modal_count": 1,
```

Assert:

```python
assert "modal_decision_counts" in html
assert "junction_aggregation_blocked_by_modal_count" in html
```

- [ ] **Step 4: Run HTML test**

Run:

```powershell
python -m pytest tests\test_workflow_review_html.py -q
```

Expected: pass.

## Task 5: Ingolstadt Feedback Run

**Files:**
- Create output only: `C:\Users\huqio\Documents\Codex\2026-06-26\ingolstadt_modal_policy_probe\*`

- [ ] **Step 1: Run topology audit on current Torii visual-detail network**

Run:

```powershell
@'
from pathlib import Path
import json, sys
root = Path(r"C:\Users\huqio\Documents\Torii-SUMO")
sys.path.insert(0, str(root / "plugins" / "torii-sumo" / "src"))
from torii_sumo.core.topology_audit import audit_topology_fragmentation
report = audit_topology_fragmentation(
    net_file=root / "examples" / "02_one_prompt_osm_network" / "networks" / "torii_5_5_reference_visual_detail_tls_aggregated.net.xml",
    osm_file=Path(r"C:\Users\huqio\Documents\Codex\2026-06-24\ingolstadt_reference_visual_detail_spark53\osm\sumo_osm_cleanup_reference_visual_detail_filtered.osm.xml.gz"),
    output_dir=Path(r"C:\Users\huqio\Documents\Codex\2026-06-26\ingolstadt_modal_policy_probe"),
    prefix="torii_5_5_modal_policy",
)
keys = [
    "suspicious_cluster_count",
    "junction_aggregation_candidate_count",
    "junction_aggregation_blocked_by_corridor_count",
    "junction_aggregation_blocked_by_modal_count",
    "modal_decision_counts",
]
print(json.dumps({key: report.get(key) for key in keys}, indent=2))
'@ | python -
```

Expected:

- JSON prints all requested keys.
- Output CSV contains `modal_aggregation_decision`.
- At least one cluster is not `join_core`.

- [ ] **Step 2: Inspect worst modal blockers**

Run:

```powershell
Import-Csv 'C:\Users\huqio\Documents\Codex\2026-06-26\ingolstadt_modal_policy_probe\torii_5_5_modal_policy_dense_junction_clusters.csv' |
  Sort-Object {[int]$_.node_count} -Descending |
  Select-Object -First 10 cluster_id,node_count,aggregation_decision,modal_aggregation_decision,modal_primary_role,modal_reason |
  Format-Table -AutoSize
```

Expected: the largest clusters have readable modal reasons.

## Task 6: Full Verification and Commit

**Files:**
- All Codex-made implementation/test/doc changes.

- [ ] **Step 1: Run focused regression**

Run:

```powershell
python -m pytest tests\test_modal_aggregation_policy.py tests\test_osm_network_tools.py tests\test_workflow_review_html.py tests\test_junction_aggregation.py -q
```

Expected: pass.

- [ ] **Step 2: Stage only Codex-made changes**

Run:

```powershell
git status --short
git add docs\superpowers\specs\2026-06-26-modal-aware-junction-aggregation.md docs\superpowers\plans\2026-06-26-modal-aware-junction-aggregation.md plugins\torii-sumo\src\torii_sumo\core\modal_aggregation_policy.py plugins\torii-sumo\src\torii_sumo\core\topology_audit.py plugins\torii-sumo\src\torii_sumo\core\workflow_review_html.py tests\test_modal_aggregation_policy.py tests\test_osm_network_tools.py tests\test_workflow_review_html.py
```

- [ ] **Step 3: Commit**

Run:

```powershell
git commit -m "feat: add modal-aware junction audit"
```

Expected: commit created.

## Self-Review

- Spec coverage: modal roles, hard blockers, audit output, HTML visibility, and no-destructive-join boundary are covered by tasks.
- Placeholder scan: no task relies on an unspecified helper; all new function names are defined in Task 2.
- Type consistency: `modal_aggregation_decision`, `modal_primary_role`, `modal_reason`, and `modal_risk_flags` are used consistently across module, topology audit, CSV, and HTML.


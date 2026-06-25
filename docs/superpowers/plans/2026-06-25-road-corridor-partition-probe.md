# Road Corridor Partition Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a diagnostic experiment that tests whether road-name corridor partitioning can explain and reduce cross-area junction aggregation chains in the Ingolstadt Torii network.

**Architecture:** Build a standalone probe outside the Torii plugin source. The probe reads the current Torii visual-detail network, the previous map-reference teacher join groups, and SUMO topology audits; it computes named road corridors and intersection-cell signatures, filters risky join groups, builds non-destructive variants, and compares topology/routeability against the prior baseline.

**Tech Stack:** Python 3.11, XML parsing with `xml.etree.ElementTree`, Torii-SUMO audit utilities from `plugins/torii-sumo/src`, SUMO `netconvert` 1.26, JSON/CSV/Markdown evidence outputs.

---

## File Structure

- Create: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_road_corridor_partition_probe\run_road_corridor_partition_probe.py`
  - Standalone diagnostic runner. It must not modify Torii workflow code.
- Create output: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_road_corridor_partition_probe\join_group_corridor_audit.csv`
  - One row per teacher join group with road-name/cell risk fields.
- Create output: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_road_corridor_partition_probe\cluster_corridor_audit.csv`
  - One row per suspicious topology cluster in the baseline and selected variants.
- Create output: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_road_corridor_partition_probe\variants\*\*.net.xml`
  - Non-destructive netconvert variants.
- Create output: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_road_corridor_partition_probe\SUMMARY.md`
  - Human-readable evidence summary.
- Read only: `C:\Users\huqio\Documents\Torii-SUMO\examples\02_one_prompt_osm_network\networks\torii_5_5_reference_visual_detail_tls_aggregated.net.xml`
- Read only: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe\variants\teacher_confirmed_all\teacher_confirmed_all_join.nodes.xml`
- Read only: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe\variants\teacher_confirmed_all\teacher_confirmed_all.net.xml`
- Read only: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe\validation\teacher_confirmed_all\topology\teacher_confirmed_all_topology_audit.json`

## Task 1: Prepare Runner and Fixtures

**Files:**
- Create: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_road_corridor_partition_probe\run_road_corridor_partition_probe.py`

- [ ] **Step 1: Create the experiment directory**

Run:

```powershell
New-Item -ItemType Directory -Force 'C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_road_corridor_partition_probe' | Out-Null
```

Expected: directory exists.

- [ ] **Step 2: Write runner constants**

Use `apply_patch` to create the runner with these constants:

```python
ROOT = Path(r"C:\Users\huqio\Documents\Torii-SUMO")
SRC = ROOT / "plugins" / "torii-sumo" / "src"
CANDIDATE_NET = ROOT / "examples" / "02_one_prompt_osm_network" / "networks" / "torii_5_5_reference_visual_detail_tls_aggregated.net.xml"
MAP_REF_DIR = Path(r"C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe")
TEACHER_JOIN_NODES = MAP_REF_DIR / "variants" / "teacher_confirmed_all" / "teacher_confirmed_all_join.nodes.xml"
TEACHER_JOIN_DIST30_NET = MAP_REF_DIR / "variants" / "teacher_confirmed_all" / "teacher_confirmed_all.net.xml"
OUT_DIR = Path(r"C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_road_corridor_partition_probe")
NETCONVERT = Path(r"C:\Program Files (x86)\Eclipse\Sumo\bin\netconvert.exe")
```

- [ ] **Step 3: Run syntax check**

Run:

```powershell
python -m py_compile 'C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_road_corridor_partition_probe\run_road_corridor_partition_probe.py'
```

Expected: exit code `0`.

## Task 2: Compute Road Corridor and Intersection-Cell Evidence

**Files:**
- Modify: `run_road_corridor_partition_probe.py`
- Create output: `join_group_corridor_audit.csv`
- Create output: `road_corridor_partition_summary.json`

- [ ] **Step 1: Parse the SUMO network graph**

Implement:

```python
def parse_network(net_file: Path) -> dict[str, Any]:
    ...
```

The returned graph must include:

```python
{
    "junctions": {"node_id": {"x": 0.0, "y": 0.0, "type": "priority"}},
    "edges": [{"id": "...", "from": "...", "to": "...", "name": "...", "type": "...", "length": 0.0}],
    "incident_edges": {"node_id": [edge, ...]},
}
```

- [ ] **Step 2: Normalize corridor keys**

Implement:

```python
def corridor_key(edge: dict[str, Any]) -> str:
    name = normalize_name(edge["name"])
    road_type = str(edge["type"]).replace("highway.", "")
    if name:
        return f"name:{name}"
    return f"unnamed:{road_type}"
```

This uses same road name as a corridor signal, not as an unconditional merge rule.

- [ ] **Step 3: Audit one join group**

Implement:

```python
def audit_node_group(graph: dict[str, Any], node_ids: list[str], group_id: str, source: str) -> dict[str, Any]:
    ...
```

It must compute:

```python
{
    "group_id": group_id,
    "source": source,
    "node_count": len(node_ids),
    "max_pair_distance_m": 0.0,
    "named_corridor_count": 0,
    "unnamed_corridor_count": 0,
    "intersection_cell_count": 0,
    "intersection_cell_signatures": ["name:a|name:b"],
    "corridor_decision": "allow|reject",
    "corridor_reason": "...",
}
```

Intersection cell signatures are made from each node's incident named corridors. A node with two or more named corridors produces a signature such as `name:harderstrasse|name:esplanade`.

- [ ] **Step 4: Define the first corridor risk rule**

Use this deterministic diagnostic rule:

```python
def corridor_decision(audit: dict[str, Any]) -> tuple[str, str]:
    if audit["node_count"] >= 20 and audit["intersection_cell_count"] >= 3:
        return "reject", "large group spans three or more named intersection cells"
    if audit["intersection_cell_count"] >= 4:
        return "reject", "group spans four or more named intersection cells"
    if audit["named_corridor_count"] >= 7:
        return "reject", "group touches seven or more named road corridors"
    if audit["max_pair_distance_m"] > 90 and audit["intersection_cell_count"] >= 2:
        return "reject", "wide group spans multiple named cells"
    return "allow", "within one local named-road cell or insufficient name evidence"
```

- [ ] **Step 5: Run join-group audit**

Run:

```powershell
python 'C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_road_corridor_partition_probe\run_road_corridor_partition_probe.py' --phase audit
```

Expected:

- `join_group_corridor_audit.csv` exists.
- `road_corridor_partition_summary.json` exists.
- Summary reports total, allowed, and rejected teacher join groups.

## Task 3: Build Non-Destructive Explicit-Join Variants

**Files:**
- Modify: `run_road_corridor_partition_probe.py`
- Create output: `variants\teacher_explicit_dist0\teacher_explicit_dist0.net.xml`
- Create output: `variants\corridor_filtered_dist0\corridor_filtered_dist0.net.xml`
- Create output: `variants\corridor_filtered_dist30\corridor_filtered_dist30.net.xml`

- [ ] **Step 1: Write filtered join file**

Write `corridor_filtered_join.nodes.xml` using:

```xml
<nodes version="1.20">
  <join nodes="..." />
</nodes>
```

Only `corridor_decision == "allow"` groups are included.

- [ ] **Step 2: Build variants**

Run `netconvert` in three forms:

```powershell
& 'C:\Program Files (x86)\Eclipse\Sumo\bin\netconvert.exe' -s '<candidate.net.xml>' -n '<teacher_join.nodes.xml>' --junctions.join --junctions.join-dist 0 -o '<teacher_explicit_dist0.net.xml>' --junctions.join-output '<repro.nodes.xml>'
& 'C:\Program Files (x86)\Eclipse\Sumo\bin\netconvert.exe' -s '<candidate.net.xml>' -n '<corridor_filtered_join.nodes.xml>' --junctions.join --junctions.join-dist 0 -o '<corridor_filtered_dist0.net.xml>' --junctions.join-output '<repro.nodes.xml>'
& 'C:\Program Files (x86)\Eclipse\Sumo\bin\netconvert.exe' -s '<candidate.net.xml>' -n '<corridor_filtered_join.nodes.xml>' --junctions.join --junctions.join-dist 30 -o '<corridor_filtered_dist30.net.xml>' --junctions.join-output '<repro.nodes.xml>'
```

This tests whether the previous giant cluster came from the selected teacher groups, the global `join-dist=30`, or both.

- [ ] **Step 3: Count networks**

For every variant, write:

```python
{"edges": ..., "non_internal_edges": ..., "lanes": ..., "junctions": ..., "traffic_light_junctions": ..., "tlLogic": ...}
```

Expected: `variant_build_results.json` and `variant_counts.json` exist.

## Task 4: Validate Corridor Effect

**Files:**
- Modify: `run_road_corridor_partition_probe.py`
- Create output: `cluster_corridor_audit.csv`
- Create output: `comparison_summary.json`
- Create output: `SUMMARY.md`

- [ ] **Step 1: Run topology audit**

For baseline, prior `teacher_confirmed_all`, and every new variant, call:

```python
audit_topology_fragmentation(
    net_file=net_file,
    output_dir=OUT_DIR / "validation" / variant_name / "topology",
    prefix=variant_name,
    cluster_radius_m=30.0,
    min_cluster_nodes=3,
)
```

- [ ] **Step 2: Audit topology clusters with corridor fields**

For each suspicious cluster, run `audit_node_group(...)` over `cluster["node_ids"]`. The summary must identify:

- max cluster node count;
- max cluster named corridor count;
- max cluster intersection-cell count;
- worst cluster Google Maps URL when available.

- [ ] **Step 3: Run routeability audit for built variants**

Use:

```python
run_routeability_audit(
    net_file=variant_net,
    output_dir=OUT_DIR / "validation" / variant_name / "routeability",
    prefix=variant_name,
    vehicle_count=100,
    seed=42,
    initial_end=300,
    max_end=2400,
    timeout_seconds=240.0,
)
```

- [ ] **Step 4: Write final summary**

`SUMMARY.md` must include:

- whether `join-dist=0` prevents the giant cluster;
- whether corridor filtering rejects cross-cell join groups;
- whether the filtered variant improves dense-cluster count without routeability failure;
- claim boundary `diagnostic-demo`;
- next production control action.

## Task 5: Stop Before Plugin Integration

**Files:**
- Do not modify: `plugins/torii-sumo/src/torii_sumo/core/osm_workflow.py`
- Do not modify: `plugins/torii-sumo/src/torii_sumo/core/junction_aggregation.py`
- Do not modify: `plugins/torii-sumo/src/torii_sumo/server.py`

- [ ] **Step 1: Verify artifacts**

Run:

```powershell
python -m py_compile 'C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_road_corridor_partition_probe\run_road_corridor_partition_probe.py'
python - <<'PY'
import json
from pathlib import Path
out = Path(r'C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_road_corridor_partition_probe')
for name in ['road_corridor_partition_summary.json', 'variant_build_results.json', 'comparison_summary.json']:
    json.loads((out / name).read_text(encoding='utf-8'))
print('json_ok')
PY
```

Expected: syntax check exits `0`, JSON check prints `json_ok`.

- [ ] **Step 2: Report control result**

Report:

```text
target:
state:
action:
feedback:
result:
next:
claim_status:
```

This experiment may justify a future Torii implementation plan, but it must not claim production readiness.

# Map Reference Junction Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the first方案C Ingolstadt map-reference experiment, using TUM as a teacher and OSM/topology/Google-review metadata as generalizable evidence for Torii junction aggregation.

**Architecture:** This is an experiment-first path, not production workflow integration. A standalone probe script builds a `MapReferenceGraph`, replays candidate policies, optionally builds non-destructive aggregation variants, and writes an evidence bundle. Production extraction into reusable Torii core modules and MCP tools is out of scope for this experiment and requires a separate approved plan.

**Tech Stack:** Python 3.11, Torii-SUMO core modules from `plugins/torii-sumo/src`, SUMO `netconvert`, existing routeability/topology/reference audit utilities, JSON/CSV artifacts, optional Matplotlib/PIL visualization.

---

## File Structure

- Create: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe\run_map_reference_probe.py`
  - Standalone experiment runner. It imports Torii core audit functions but does not modify workflow code.
- Create output: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe\map_reference_graph_teacher.json`
  - The teacher-derived `MapReferenceGraph`.
- Create output: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe\map_reference_intersections.csv`
  - Flat table for inspecting every physical intersection candidate.
- Create output: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe\policy_replay_summary.json`
  - Recall/precision/count comparison for policy variants.
- Create output: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe\variants\*\*.net.xml`
  - Non-destructive aggregation variants, only if selective join can be built.
- Create output: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe\SUMMARY.md`
  - Human-readable evidence summary.
- Read only: `C:\Users\huqio\Documents\Torii-SUMO\examples\02_one_prompt_osm_network\networks\torii_5_5_reference_visual_detail_tls_aggregated.net.xml`
- Read only: `C:\Users\huqio\Documents\Torii-SUMO\examples\02_one_prompt_osm_network\networks\tum_ingolstadt_center_reference.net.xml`
- Read only: `C:\Users\huqio\Documents\Codex\2026-06-24\ingolstadt_reference_visual_detail_spark53\osm\sumo_osm_cleanup_reference_visual_detail_filtered.osm.xml.gz`

## Task 1: Prepare Experiment Runner

**Files:**
- Create: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe\run_map_reference_probe.py`

- [ ] **Step 1: Create the experiment directory**

Run:

```powershell
New-Item -ItemType Directory -Force 'C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe' | Out-Null
```

Expected: directory exists.

- [ ] **Step 2: Write the standalone runner**

Use `apply_patch` to create `run_map_reference_probe.py` with these responsibilities:

```python
from __future__ import annotations

import csv
import gzip
import json
import math
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\Users\huqio\Documents\Torii-SUMO")
SRC = ROOT / "plugins" / "torii-sumo" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from torii_sumo.core.reference_join_audit import audit_reference_join_patterns
from torii_sumo.core.routeability_audit import run_routeability_audit
from torii_sumo.core.topology_audit import audit_topology_fragmentation

CANDIDATE_NET = ROOT / "examples" / "02_one_prompt_osm_network" / "networks" / "torii_5_5_reference_visual_detail_tls_aggregated.net.xml"
REFERENCE_NET = ROOT / "examples" / "02_one_prompt_osm_network" / "networks" / "tum_ingolstadt_center_reference.net.xml"
OSM_FILE = Path(r"C:\Users\huqio\Documents\Codex\2026-06-24\ingolstadt_reference_visual_detail_spark53\osm\sumo_osm_cleanup_reference_visual_detail_filtered.osm.xml.gz")
OUT_DIR = Path(r"C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe")
```

The runner must include functions named:

```python
parse_osm_context(osm_file: Path) -> dict[str, Any]
network_counts(net_file: Path) -> dict[str, int]
build_map_reference_graph(reference_join: dict[str, Any], topology: dict[str, Any], osm_context: dict[str, Any]) -> dict[str, Any]
replay_policies(graph: dict[str, Any]) -> dict[str, Any]
write_join_nodes(policy_name: str, selected: list[dict[str, Any]], output_dir: Path) -> Path
build_variant(policy_name: str, nodes_file: Path, output_dir: Path) -> dict[str, Any]
validate_variant(policy_name: str, net_file: Path, output_dir: Path) -> dict[str, Any]
write_summary(summary: dict[str, Any], output_dir: Path) -> None
```

- [ ] **Step 3: Run syntax check**

Run:

```powershell
python -m py_compile 'C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe\run_map_reference_probe.py'
```

Expected: exit code `0`.

## Task 2: Build MapReferenceGraph

**Files:**
- Modify: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe\run_map_reference_probe.py`
- Create output: `map_reference_graph_teacher.json`
- Create output: `map_reference_intersections.csv`
- Create output: `teacher_rule_summary.json`

- [ ] **Step 1: Generate base audits**

The script must call:

```python
topology = audit_topology_fragmentation(
    net_file=CANDIDATE_NET,
    output_dir=OUT_DIR / "topology",
    prefix="torii_detail",
    cluster_radius_m=30.0,
    min_cluster_nodes=3,
)
reference_join = audit_reference_join_patterns(
    reference_net_file=REFERENCE_NET,
    candidate_net_file=CANDIDATE_NET,
    output_dir=OUT_DIR / "reference_join",
    prefix="tum_vs_torii_detail",
    reference_cluster_prefix="cluster_",
    candidate_cluster_radius_m=30.0,
    candidate_min_cluster_nodes=3,
    match_radius_m=45.0,
)
```

- [ ] **Step 2: Parse OSM context**

Extract these fields for OSM nodes/ways:

```python
{
    "signal_nodes": [
        {
            "node_id": "...",
            "lat": 48.0,
            "lon": 11.0,
            "signal_kind": "vehicle|pedestrian|bicycle|mixed_or_ambiguous",
            "way_highways": ["primary", "primary_link"],
            "way_names": ["..."]
        }
    ],
    "node_way_context": {
        "1242949438": {
            "highways": ["primary"],
            "names": ["..."]
        }
    }
}
```

- [ ] **Step 3: Build graph entries**

For every `reference_join["all_cases"]` entry where `reference_id` starts with `cluster_`, create one graph intersection row. Use `matched_candidate_cluster_id` when present, otherwise keep `sumo_candidate_cluster_id` empty and classify it as `source_node_only_match`.

Each row must contain:

```python
{
    "id": f"map_ref_int_{index:04d}",
    "reference_origin": "tum_teacher",
    "teacher_reference_id": case["reference_id"],
    "teacher_type": case["reference_type"],
    "teacher_source_node_ids": case["reference_joined_source_nodes"],
    "sumo_candidate_cluster_id": case.get("matched_candidate_cluster_id", ""),
    "sumo_candidate_node_ids": case.get("matched_candidate_node_ids", []),
    "topology_shape": cluster.get("physical_intersection_shape", ""),
    "topology_score": cluster.get("physical_intersection_score", 0.0),
    "osm_signal_support": "...",
    "google_review_status": "not_reviewed",
    "recommended_action": "...",
    "confidence": "...",
    "reason": "..."
}
```

- [ ] **Step 4: Run graph generation**

Run:

```powershell
python 'C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe\run_map_reference_probe.py' --phase graph
```

Expected:

- `map_reference_graph_teacher.json` exists.
- `map_reference_intersections.csv` exists.
- `teacher_rule_summary.json` exists.
- Summary reports `reference_case_count = 149`.

## Task 3: Replay Candidate Policies

**Files:**
- Modify: `run_map_reference_probe.py`
- Create output: `policy_replay_summary.json`
- Create output: `policies\*_selected_candidates.csv`

- [ ] **Step 1: Implement policies**

Implement these policy functions:

```python
def policy_teacher_confirmed_all(row: dict[str, Any]) -> tuple[bool, str]:
    if row["sumo_candidate_node_ids"]:
        return True, "teacher case has matched candidate nodes"
    return False, "no matched candidate nodes"

def policy_topology_osm_signal_only(row: dict[str, Any]) -> tuple[bool, str]:
    if row["topology_shape"] not in {"cross", "t_or_y"}:
        return False, "not a cross/T topology candidate"
    if float(row["topology_score"] or 0.0) < 0.6:
        return False, "topology score below 0.6"
    if row["osm_signal_support"] != "vehicle_signal":
        return False, "no OSM vehicle signal evidence"
    if row["ramp_or_interchange_risk"] or row["grade_separation_risk"]:
        return False, "ramp or grade-separation risk"
    return True, "cross/T topology and OSM vehicle signal evidence"

def policy_topology_teacher_generalized(row: dict[str, Any]) -> tuple[bool, str]:
    if row["topology_shape"] not in {"cross", "t_or_y"}:
        return False, "not a cross/T topology candidate"
    if float(row["topology_score"] or 0.0) < 0.55:
        return False, "topology score below 0.55"
    if row["ramp_or_interchange_risk"] or row["grade_separation_risk"]:
        return False, "ramp or grade-separation risk"
    if int(row["approach_count"] or 0) < 3:
        return False, "too few approaches"
    return True, "teacher-like low-risk physical intersection pattern"
```

- [ ] **Step 2: Compute metrics**

For each policy report:

```python
{
    "selected_count": 0,
    "teacher_case_count": 149,
    "traffic_light_selected_count": 0,
    "priority_selected_count": 0,
    "selected_source_node_count": 0,
    "selected_candidate_cluster_count": 0,
    "rejected_reason_counts": {}
}
```

- [ ] **Step 3: Run policy replay**

Run:

```powershell
python 'C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe\run_map_reference_probe.py' --phase policies
```

Expected:

- `policy_replay_summary.json` exists.
- `teacher_confirmed_all` selects more cases than `topology_osm_signal_only`.
- `topology_teacher_generalized` selects non-signalized cases, proving OSM signal tags are not the only join signal.

## Task 4: Build Non-Destructive Variants

**Files:**
- Modify: `run_map_reference_probe.py`
- Create output: `variants\teacher_confirmed_all\*.net.xml`
- Create output: `variants\topology_teacher_generalized\*.net.xml`

- [ ] **Step 1: Write selected join XML**

For each selected policy, write a plain SUMO nodes join file. Each selected physical intersection becomes one `<join>` group:

```xml
<nodes>
  <join nodes="1242949438 2230504053 2230504054" />
</nodes>
```

Do not invent coordinates. The nodes file is only a selection input for `netconvert -n ... --junctions.join`. This format matches the prior successful SUMO 1.26 `join_selective_topN.nodes.xml` experiment.

- [ ] **Step 2: Run netconvert variants**

Run command form:

```powershell
& 'C:\Program Files (x86)\Eclipse\Sumo\bin\netconvert.exe' `
  --sumo-net-file 'C:\Users\huqio\Documents\Torii-SUMO\examples\02_one_prompt_osm_network\networks\torii_5_5_reference_visual_detail_tls_aggregated.net.xml' `
  -n '<nodes_file>' `
  --junctions.join `
  --junctions.join-dist 30 `
  --junctions.join-output '<joined_junctions_file>' `
  --output-file '<variant_net_file>'
```

Expected:

- Exit code `0`, or a captured failure explaining why selective `-n` cannot safely drive join selection.
- Source network remains unchanged.

- [ ] **Step 3: Count variant networks**

For every built variant, count:

```python
{
    "edges": len(root.findall("edge")),
    "lanes": len(root.findall(".//lane")),
    "junctions": len(root.findall("junction")),
    "traffic_light_junctions": sum(1 for j in root.findall("junction") if j.get("type") == "traffic_light"),
    "tlLogic": len(root.findall("tlLogic"))
}
```

Expected: counts are written to `variant_counts.json`.

## Task 5: Validate and Compare

**Files:**
- Modify: `run_map_reference_probe.py`
- Create output: `validation\*\*_topology_audit.json`
- Create output: `validation\*\*_routeability_audit.json`
- Create output: `comparison_summary.json`
- Create output: `SUMMARY.md`

- [ ] **Step 1: Run topology audit for each variant**

Use:

```python
audit_topology_fragmentation(
    net_file=variant_net,
    output_dir=OUT_DIR / "validation" / policy_name / "topology",
    prefix=policy_name,
    cluster_radius_m=30.0,
    min_cluster_nodes=3,
)
```

- [ ] **Step 2: Run routeability audit for each variant**

Use:

```python
run_routeability_audit(
    net_file=variant_net,
    output_dir=OUT_DIR / "validation" / policy_name / "routeability",
    prefix=policy_name,
    vehicle_count=100,
    seed=42,
    initial_end=300,
    max_end=2400,
    timeout_seconds=240.0,
)
```

- [ ] **Step 3: Compare against baselines**

Write a summary table with these rows:

```text
TUM reference
Torii visual-detail TLS aggregated
teacher_confirmed_all
topology_osm_signal_only
topology_teacher_generalized
```

Columns:

```text
edges, lanes, junctions, traffic_light_junctions, tlLogic,
topology_cluster_count, routeability_status, arrived, teleports, collisions,
claim_status
```

- [ ] **Step 4: Write final SUMMARY.md**

The summary must include:

- what was built;
- whether selective join worked;
- which policy moved closest to TUM;
- whether routeability passed;
- what evidence is still missing for Google-derived reference without TUM;
- clear `diagnostic-demo` claim boundary.

## Task 6: Preserve Artifacts and Decide Integration

**Files:**
- Read: all generated outputs under `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe`
- Do not modify in this experiment; integration requires a separate approved plan: Torii plugin source files

- [ ] **Step 1: Do not integrate into Torii yet**

Stop after the experiment bundle. Do not modify:

```text
plugins/torii-sumo/src/torii_sumo/core/osm_workflow.py
plugins/torii-sumo/src/torii_sumo/tools/osm_tools.py
plugins/torii-sumo/src/torii_sumo/server.py
```

- [ ] **Step 2: Report control result**

Report:

```text
target:
state:
deviation:
action:
feedback:
result:
next:
```

- [ ] **Step 3: Choose next control action**

Choose one:

- integrate `MapReferenceGraph` into Torii core;
- refine Google screenshot/visual review capture;
- refine selective join mechanism;
- abandon or narrow the method if evidence does not improve over current Torii.

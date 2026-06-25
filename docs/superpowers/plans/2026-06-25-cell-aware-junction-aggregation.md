# Cell-Aware Junction Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Keep all network mutation non-destructive until verification passes.

**Goal:** Turn the Ingolstadt corridor-partition finding into reusable Torii code: dense SUMO junction groups must be reinterpreted through OSM way context, named-road corridor evidence, and physical intersection cells before any aggregation candidate is proposed.

**Current State:** `topology_audit.py` detects suspicious clusters by distance-connected components. That catches over-fragmented junctions, but large OSM/SUMO chains can span several real intersections because nearby nodes bridge across a corridor. The previous Ingolstadt probe showed that OSM `name/ref/highway` context can reject cross-cell groups, while the large cluster itself still needs bottom-level segmentation.

**Control Action:** Add a reusable `road_corridor` core module, enrich topology audit with optional corridor/cell fields when an OSM source file is available, and run Ingolstadt as a diagnostic validation case. This is not an Ingolstadt-specific rule set.

**Feedback Signal:** Unit tests pass; existing topology tests continue to pass; Ingolstadt audit reports corridor partitions and rejects cross-cell dense groups without relying on TUM-only counts.

**Stopping Condition:** The plugin can audit a SUMO network plus optional OSM file and report corridor/cell-aware segmentation evidence; Ingolstadt comparison produces an evidence bundle describing remaining gap to TUM.

---

## File Structure

- Create: `C:\Users\huqio\Documents\Torii-SUMO\plugins\torii-sumo\src\torii_sumo\core\road_corridor.py`
  - Reusable OSM way-context parser and corridor/cell audit helpers.
- Modify: `C:\Users\huqio\Documents\Torii-SUMO\plugins\torii-sumo\src\torii_sumo\core\topology_audit.py`
  - Add optional `osm_file` and corridor/cell fields to suspicious clusters.
- Modify: `C:\Users\huqio\Documents\Torii-SUMO\plugins\torii-sumo\src\torii_sumo\tools\osm_tools.py`
  - Expose optional `osm_file` through `sumo_network_topology_audit`.
- Modify: `C:\Users\huqio\Documents\Torii-SUMO\plugins\torii-sumo\src\torii_sumo\core\osm_workflow.py`
  - Pass `source_osm_file` or `filtered_osm_file` into the topology audit when available.
- Create: `C:\Users\huqio\Documents\Torii-SUMO\tests\test_road_corridor.py`
  - Unit tests for OSM parsing, cluster-id expansion, and corridor/cell decisions.
- Create output only: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_cell_aware_topology_probe\*`
  - Diagnostic evidence bundle for Ingolstadt comparison.

## Task 1: Add Reusable Corridor Context

- [ ] Implement `normalize_road_name(value: str) -> str`.
- [ ] Implement `source_node_ids(node_id: str) -> tuple[str, ...]`.
  - Plain SUMO ids return one id.
  - SUMO ids like `cluster_267517523_4215915459` return both source ids.
- [ ] Implement `parse_osm_way_context(osm_file: Path) -> dict[str, Any]`.
  - Support `.osm.xml` and `.osm.xml.gz`.
  - Preserve child `<nd>` and `<tag>` data until the parent `<way>` is processed.
  - Map each OSM node id to way names, refs, highways, and stable corridor keys.
- [ ] Implement `node_corridor_keys(osm_context, node_id)`.
  - Prefer `name:*`.
  - Fall back to `ref:*`.
  - Fall back to `highway:*` only as low-confidence context.

## Task 2: Add Cell-Aware Group Audit

- [ ] Implement `audit_node_group_corridors(graph, osm_context, node_ids, group_id, source)`.
- [ ] Compute:
  - `named_corridor_count`
  - `unnamed_corridor_count`
  - `intersection_cell_count`
  - `intersection_cell_signatures`
  - `corridor_partition_count`
  - `max_corridor_partition_node_count`
  - `max_pair_distance_m`
- [ ] Use deterministic diagnostic decision rules:
  - Reject large groups spanning three or more named cells.
  - Reject groups spanning four or more named cells.
  - Reject groups touching seven or more named corridors.
  - Reject wide groups spanning multiple named cells.
  - Otherwise allow as local evidence or mark as insufficient name evidence.
- [ ] Keep decisions as audit evidence. Do not rewrite a `.net.xml` inside this module.

## Task 3: Enrich Topology Audit

- [ ] Add optional `osm_file: Path | None = None` to `audit_topology_fragmentation`.
- [ ] If `osm_file` is available, parse OSM context and append corridor fields to every suspicious cluster.
- [ ] Add summary counts:
  - `corridor_audit_status`
  - `corridor_decision_counts`
  - `max_corridor_partition_count`
  - `max_intersection_cell_count`
- [ ] Extend the CSV writer with the new fields while preserving existing columns and tests.
- [ ] Thread optional `osm_file` through MCP tool and OSM cleanup workflow.

## Task 4: Unit Verification

- [ ] Add tests that prove the parser reads way children from a gzip OSM file.
- [ ] Add tests that prove `cluster_123_456` expands to source node ids.
- [ ] Add tests that prove one physical named-road cell is allowed.
- [ ] Add tests that prove a chained multi-cell group is rejected.
- [ ] Run:

```powershell
python -m pytest tests\test_road_corridor.py tests\test_osm_network_tools.py::test_topology_audit_flags_dense_junction_clusters_within_radius tests\test_osm_network_tools.py::test_topology_audit_reports_local_cluster_graph_edges -q
```

## Task 5: Ingolstadt Diagnostic Comparison

- [ ] Create `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_cell_aware_topology_probe`.
- [ ] Run topology audit on Torii 5.5 visual-detail TLS-aggregated network with the filtered OSM file:

```powershell
python - <<'PY'
from pathlib import Path
import json, sys
root = Path(r"C:\Users\huqio\Documents\Torii-SUMO")
sys.path.insert(0, str(root / "plugins" / "torii-sumo" / "src"))
from torii_sumo.core.topology_audit import audit_topology_fragmentation
report = audit_topology_fragmentation(
    net_file=root / "examples" / "02_one_prompt_osm_network" / "networks" / "torii_5_5_reference_visual_detail_tls_aggregated.net.xml",
    osm_file=Path(r"C:\Users\huqio\Documents\Codex\2026-06-24\ingolstadt_reference_visual_detail_spark53\osm\sumo_osm_cleanup_reference_visual_detail_filtered.osm.xml.gz"),
    output_dir=Path(r"C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_cell_aware_topology_probe"),
    prefix="torii_5_5_cell_aware",
)
print(json.dumps({k: report[k] for k in ("suspicious_cluster_count", "corridor_audit_status", "corridor_decision_counts", "max_corridor_partition_count", "max_intersection_cell_count")}, indent=2))
PY
```

- [ ] Compare against TUM only as evidence:
  - Torii cluster decisions and worst clusters.
  - TUM counts as context, not as a target threshold.
  - Whether rejected groups correspond to cross-cell chains found in the previous probe.
- [ ] Write `SUMMARY.md` with claim status `diagnostic-demo`.

## Task 6: Commit

- [ ] Stage only Codex-made changes.
- [ ] Commit plan separately.
- [ ] Commit implementation and verification separately after feedback is observed.

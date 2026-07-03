# Topology and Connection Driven Junction Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a diagnostic audit that learns cleanup policy from the TUM reference network, detects missed aggregation candidates from road topology, and uses NetEdit/netconvert connection signals to tighten movement emission.

**Architecture:** Keep this as a read-only audit layer first. Add a teacher-policy snapshot for the reference net, add connection-signature parsing beside the movement model, add topology-cell candidate mining beside existing topology/overlapping-junction audits, then make the rebuild candidate consume the stricter movement audit. Do not globally enable destructive joins or rewrite the OSM workflow until the known Ingolstadt targets pass diagnostic review.

**Tech Stack:** Python stdlib XML parsing, existing Torii-SUMO topology and movement modules, SUMO `netconvert`, pytest fixture XML, JSON/CSV artifacts, NetEdit human review.

---

## Target Files

- Create: `plugins/torii-sumo/src/torii_sumo/core/reference_policy_audit.py`
- Create: `plugins/torii-sumo/src/torii_sumo/core/junction_connection_audit.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_movement_model.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_rebuild_candidate.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/core/topology_audit.py`
- Test: `tests/test_reference_policy_audit.py`
- Test: `tests/test_junction_connection_audit.py`
- Test: `tests/test_junction_movement_model.py`
- Test: `tests/test_topology_audit.py` or create `tests/test_topology_connection_candidates.py` if keeping the fixture separate is cleaner.

Do not modify workflow wiring in the first pass.

## Task 0: TUM Teacher Policy Snapshot

**Files:**
- Create: `plugins/torii-sumo/src/torii_sumo/core/reference_policy_audit.py`
- Test: `tests/test_reference_policy_audit.py`

- [ ] **Step 1: Write failing test for policy extraction without city-specific ids**

Add a small fixture that includes highway classes, passenger permissions, a joined `cluster_*` junction, a `tlLogic`, and one connection.

```python
from pathlib import Path

from torii_sumo.core.reference_policy_audit import build_reference_policy_report


def test_reference_policy_report_extracts_teacher_rules(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="main_in" from="a" to="cluster_1_2" type="highway.primary"><lane id="main_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="service" from="s" to="cluster_1_2" type="highway.service"><lane id="service_0" index="0" allow="delivery" shape="0,-10 0,0"/></edge>
  <edge id="main_out" from="cluster_1_2" to="b" type="highway.primary"><lane id="main_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="a" x="-10" y="0" type="priority"/>
  <junction id="s" x="0" y="-10" type="priority"/>
  <junction id="cluster_1_2" x="0" y="0" type="traffic_light"/>
  <junction id="b" x="10" y="0" type="priority"/>
  <tlLogic id="cluster_1_2" type="static" programID="0" offset="0"><phase duration="30" state="G"/></tlLogic>
  <connection from="main_in" to="main_out" fromLane="0" toLane="0" dir="s" state="O"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_reference_policy_report(net_file)

    assert report["road_type_counts"]["highway.primary"] == 2
    assert report["passenger_drivable_type_counts"] == {"highway.primary": 2}
    assert report["cluster_source_node_count_histogram"] == {"2": 1}
    assert report["tls_logic_count"] == 1
    assert report["top_level_connection_count"] == 1
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
python -m pytest tests/test_reference_policy_audit.py -q
```

Expected: fail because `reference_policy_audit.py` does not exist.

- [ ] **Step 3: Implement the smallest stdlib parser**

Parse the `.net.xml` with `xml.etree.ElementTree` and report:

- `road_type_counts`
- `passenger_drivable_type_counts`
- `cluster_source_node_count_histogram`
- `traffic_light_junction_count`
- `tls_logic_count`
- `top_level_connection_count`
- `support_or_service_type_counts`
- `claim_status="diagnostic-demo"`

Do not infer city-specific rules or persist source ids as production policy. The report may list example ids for review, but learned rules must be expressed as counts, classes, permissions, or topology patterns.

- [ ] **Step 4: Run test and verify GREEN**

Run:

```powershell
python -m pytest tests/test_reference_policy_audit.py -q
```

Expected: pass.

## Task 1: Connection Signature Parser

**Files:**
- Create: `plugins/torii-sumo/src/torii_sumo/core/junction_connection_audit.py`
- Test: `tests/test_junction_connection_audit.py`

- [ ] **Step 1: Write failing test for top-level vs internal connection layers**

Add a fixture with one incoming external edge, one outgoing external edge, and one internal continuation. The test must prove that top-level movement counts exclude internal continuations.

```python
from pathlib import Path

from torii_sumo.core.junction_connection_audit import build_connection_signature


def test_connection_signature_separates_top_level_and_internal(tmp_path: Path) -> None:
    net_file = tmp_path / "connection.net.xml"
    net_file.write_text(
        """<net>
  <edge id="in" from="a" to="j" type="highway.primary">
    <lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/>
  </edge>
  <edge id="out" from="j" to="b" type="highway.primary">
    <lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/>
  </edge>
  <edge id=":j_0" function="internal">
    <lane id=":j_0_0" index="0" allow="passenger" shape="0,0 4,0"/>
  </edge>
  <junction id="a" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="b" x="10" y="0" type="priority"/>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":j_0_0" dir="s" state="o"/>
  <connection from=":j_0" to="out" fromLane="0" toLane="0" dir="s" state="o"/>
</net>
""",
        encoding="utf-8",
    )

    signature = build_connection_signature(net_file, "j")

    assert signature["top_external_connection_count"] == 1
    assert signature["top_external_pair_count"] == 1
    assert signature["category_counts"]["internal_or_other_to_outgoing"] == 1
    assert signature["top_external_dir_counts"] == {"s": 1}
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
python -m pytest tests/test_junction_connection_audit.py -q
```

Expected: fail with `ModuleNotFoundError` or missing `build_connection_signature`.

- [ ] **Step 3: Implement minimal parser**

Create `junction_connection_audit.py` with these functions:

```python
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


def build_connection_signature(net_file: Path, junction_id: str) -> dict[str, Any]:
    root = ET.parse(net_file).getroot()
    edges = {edge.attrib.get("id", ""): edge for edge in root.findall("edge") if edge.attrib.get("id")}
    plain_edges = {
        edge_id: edge
        for edge_id, edge in edges.items()
        if not edge_id.startswith(":") and edge.attrib.get("function") != "internal"
    }
    incoming = {edge_id for edge_id, edge in plain_edges.items() if edge.attrib.get("to") == junction_id}
    outgoing = {edge_id for edge_id, edge in plain_edges.items() if edge.attrib.get("from") == junction_id}
    internal_prefix = f":{junction_id}_"
    records = []
    category_counts: Counter[str] = Counter()
    for connection in root.findall("connection"):
        source = connection.attrib.get("from", "")
        target = connection.attrib.get("to", "")
        via = connection.attrib.get("via", "")
        if not _is_related(source, target, via, incoming, outgoing, internal_prefix):
            continue
        category = _connection_category(source, target, incoming, outgoing, internal_prefix)
        category_counts[category] += 1
        records.append(
            {
                "category": category,
                "from": source,
                "to": target,
                "fromLane": connection.attrib.get("fromLane", ""),
                "toLane": connection.attrib.get("toLane", ""),
                "dir": connection.attrib.get("dir", ""),
                "state": connection.attrib.get("state", ""),
                "via": via,
            }
        )
    top_external = [record for record in records if record["category"] == "top_external"]
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "net_file": str(net_file),
        "junction_id": junction_id,
        "incoming_edges": sorted(incoming),
        "outgoing_edges": sorted(outgoing),
        "category_counts": dict(category_counts),
        "top_external_connection_count": len(top_external),
        "top_external_pair_count": len({(record["from"], record["to"]) for record in top_external}),
        "top_external_dir_counts": dict(Counter(record["dir"] or "blank" for record in top_external)),
        "connection_records": records,
    }


def _is_related(source: str, target: str, via: str, incoming: set[str], outgoing: set[str], internal_prefix: str) -> bool:
    return (
        via.startswith(internal_prefix)
        or source in incoming
        or target in outgoing
        or source.startswith(internal_prefix)
        or target.startswith(internal_prefix)
    )


def _connection_category(
    source: str,
    target: str,
    incoming: set[str],
    outgoing: set[str],
    internal_prefix: str,
) -> str:
    if source in incoming and target in outgoing:
        return "top_external"
    if source in incoming:
        return "incoming_to_internal_or_other"
    if target in outgoing:
        return "internal_or_other_to_outgoing"
    if source.startswith(internal_prefix) or target.startswith(internal_prefix):
        return "internal_continuation"
    return "other_related"
```

- [ ] **Step 4: Run test and verify GREEN**

Run:

```powershell
python -m pytest tests/test_junction_connection_audit.py -q
```

Expected: pass.

## Task 2: Topology-Cell Candidate Detection

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/topology_audit.py`
- Test: `tests/test_topology_connection_candidates.py`

- [ ] **Step 1: Write failing test for missed compact topology cell**

Add a fixture where three short core edges connect four external vehicle legs. This should become a topology-cell candidate even if a simple dense-node cluster would be ambiguous.

```python
from pathlib import Path

from torii_sumo.core.topology_audit import audit_topology_fragmentation


def test_topology_audit_flags_compact_connection_cell(tmp_path: Path) -> None:
    net_file = tmp_path / "cell.net.xml"
    net_file.write_text(
        """<net>
  <edge id="west_in" from="w" to="a" type="highway.primary"><lane id="west_in_0" index="0" allow="passenger" length="20" shape="-20,0 0,0"/></edge>
  <edge id="east_out" from="b" to="e" type="highway.primary"><lane id="east_out_0" index="0" allow="passenger" length="20" shape="6,0 26,0"/></edge>
  <edge id="north_in" from="n" to="c" type="highway.secondary"><lane id="north_in_0" index="0" allow="passenger" length="20" shape="3,20 3,4"/></edge>
  <edge id="south_out" from="a" to="s" type="highway.secondary"><lane id="south_out_0" index="0" allow="passenger" length="20" shape="0,0 0,-20"/></edge>
  <edge id="ab" from="a" to="b" type="highway.primary"><lane id="ab_0" index="0" allow="passenger" length="6" shape="0,0 6,0"/></edge>
  <edge id="bc" from="b" to="c" type="highway.secondary"><lane id="bc_0" index="0" allow="passenger" length="5" shape="6,0 3,4"/></edge>
  <junction id="w" x="-20" y="0" type="priority"/>
  <junction id="a" x="0" y="0" type="traffic_light"/>
  <junction id="b" x="6" y="0" type="priority"/>
  <junction id="c" x="3" y="4" type="priority"/>
  <junction id="e" x="26" y="0" type="priority"/>
  <junction id="n" x="3" y="20" type="priority"/>
  <junction id="s" x="0" y="-20" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = audit_topology_fragmentation(
        net_file=net_file,
        output_dir=tmp_path / "audit",
        cluster_radius_m=8,
        min_cluster_nodes=3,
    )

    assert report["topology_connection_cell_candidate_count"] == 1
    cell = report["topology_connection_cell_candidates"][0]
    assert set(cell["node_ids"]) == {"a", "b", "c"}
    assert cell["external_vehicle_approach_count"] == 4
    assert cell["connection_cell_decision"] == "needs_review"
```

- [ ] **Step 2: Write failing rejection test for close independent pair**

Use two short two-leg intersections connected by a normal long road. The audit must not classify the full chain as one cell.

```python
def test_topology_audit_rejects_long_connector_between_close_intersections(tmp_path: Path) -> None:
    net_file = tmp_path / "pair.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a_in" from="a0" to="a" type="highway.primary"><lane id="a_in_0" index="0" allow="passenger" length="20" shape="-20,0 0,0"/></edge>
  <edge id="a_to_b" from="a" to="b" type="highway.primary"><lane id="a_to_b_0" index="0" allow="passenger" length="45" shape="0,0 45,0"/></edge>
  <edge id="b_out" from="b" to="b1" type="highway.primary"><lane id="b_out_0" index="0" allow="passenger" length="20" shape="45,0 65,0"/></edge>
  <junction id="a0" x="-20" y="0" type="priority"/>
  <junction id="a" x="0" y="0" type="traffic_light"/>
  <junction id="b" x="45" y="0" type="traffic_light"/>
  <junction id="b1" x="65" y="0" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    report = audit_topology_fragmentation(
        net_file=net_file,
        output_dir=tmp_path / "audit",
        cluster_radius_m=50,
        min_cluster_nodes=2,
    )

    assert report["topology_connection_cell_candidate_count"] == 0
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
python -m pytest tests/test_topology_connection_candidates.py -q
```

Expected: fail because the report does not expose `topology_connection_cell_candidate_count`.

- [ ] **Step 4: Implement topology-cell mining in `topology_audit.py`**

Add a private helper that runs after `_dense_clusters(...)` and before writing the report:

```python
def _connection_cell_candidates(
    junctions: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    short_edge_max_length_m: float = 12.0,
    min_external_vehicle_approaches: int = 3,
) -> list[dict[str, Any]]:
    junction_by_id = {str(junction["id"]): junction for junction in junctions}
    short_vehicle_edges = [
        edge
        for edge in edges
        if edge.get("length", 0.0) <= short_edge_max_length_m
        and str(edge.get("type", "")).startswith("highway.")
    ]
    graph: dict[str, set[str]] = {}
    for edge in short_vehicle_edges:
        left = str(edge["from"])
        right = str(edge["to"])
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)
    candidates = []
    for component in _connected_node_components(graph):
        if len(component) < 2:
            continue
        boundary_edges = [
            edge
            for edge in edges
            if (edge["from"] in component) ^ (edge["to"] in component)
            and str(edge.get("type", "")).startswith("highway.")
        ]
        if len(boundary_edges) < min_external_vehicle_approaches:
            continue
        internal_edges = [
            edge
            for edge in edges
            if edge["from"] in component and edge["to"] in component
        ]
        candidates.append(
            {
                "cell_id": f"TC{len(candidates) + 1:03d}",
                "node_ids": sorted(component),
                "internal_edge_ids": sorted(str(edge["id"]) for edge in internal_edges),
                "boundary_edge_ids": sorted(str(edge["id"]) for edge in boundary_edges),
                "external_vehicle_approach_count": len(boundary_edges),
                "connection_cell_decision": "needs_review",
                "reason": "short connected vehicle-core topology cell has multiple external approaches",
            }
        )
    return candidates
```

Add the simple component helper:

```python
def _connected_node_components(graph: dict[str, set[str]]) -> list[set[str]]:
    remaining = set(graph)
    components = []
    while remaining:
        start = remaining.pop()
        component = {start}
        stack = [start]
        while stack:
            node = stack.pop()
            for neighbor in graph.get(node, set()):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.add(neighbor)
                    stack.append(neighbor)
        components.append(component)
    return components
```

Add these fields to the topology report:

```python
"topology_connection_cell_candidate_count": len(connection_cell_candidates),
"topology_connection_cell_candidates": connection_cell_candidates,
```

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_topology_connection_candidates.py -q
```

Expected: pass.

## Task 3: Connection Signature Artifact Export

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_connection_audit.py`
- Test: `tests/test_junction_connection_audit.py`

- [ ] **Step 1: Write failing test for JSON/CSV export**

```python
from torii_sumo.core.junction_connection_audit import build_connection_signature, write_connection_signature


def test_write_connection_signature_outputs_review_files(tmp_path: Path) -> None:
    net_file = tmp_path / "connection.net.xml"
    net_file.write_text(
        """<net>
  <edge id="in" from="a" to="j" type="highway.primary"><lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b" type="highway.primary"><lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="a" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="b" x="10" y="0" type="priority"/>
  <connection from="in" to="out" fromLane="0" toLane="0" dir="s" state="o"/>
</net>
""",
        encoding="utf-8",
    )
    signature = build_connection_signature(net_file, "j")

    report = write_connection_signature(signature, tmp_path / "review", "demo")

    assert Path(report["signature_file"]).is_file()
    assert Path(report["records_file"]).read_text(encoding="utf-8").splitlines()[0].startswith("category,from,to")
    assert Path(report["top_external_file"]).read_text(encoding="utf-8").splitlines()[0].startswith("from,to")
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
python -m pytest tests/test_junction_connection_audit.py -q
```

Expected: fail because `write_connection_signature` does not exist.

- [ ] **Step 3: Implement export helper**

Use `json` and `csv.DictWriter`. Write:

- `<prefix>_connection_signature.json`
- `<prefix>_connection_records_layered.csv`
- `<prefix>_top_external_connections.csv`

Return the file paths in a dict with `status="pass"` and `claim_status="diagnostic-demo"`.

- [ ] **Step 4: Run test and verify GREEN**

Run:

```powershell
python -m pytest tests/test_junction_connection_audit.py -q
```

Expected: pass.

## Task 4: Tighten Movement Emission

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_movement_model.py`
- Test: `tests/test_junction_movement_model.py`

- [ ] **Step 1: Write failing test that blocks Cartesian movement emission**

Use a fixture with one incoming approach and three outgoing approaches where only same-road continuation and one right turn should emit. The left-turn alternative should remain review because there is no rule selecting it.

```python
def test_movement_graph_does_not_emit_every_non_uturn_target(tmp_path: Path) -> None:
    net_file = tmp_path / "cartesian.net.xml"
    net_file.write_text(
        """<net>
  <edge id="west_in" from="w" to="j" type="highway.primary" name="Main"><lane id="west_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="east_out" from="j" to="e" type="highway.primary" name="Main"><lane id="east_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="south_out" from="j" to="s" type="highway.secondary" name="South"><lane id="south_out_0" index="0" allow="passenger" shape="0,0 0,-10"/></edge>
  <edge id="north_out" from="j" to="n" type="highway.secondary" name="North"><lane id="north_out_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <junction id="w" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="e" x="10" y="0" type="priority"/>
  <junction id="s" x="0" y="-10" type="priority"/>
  <junction id="n" x="0" y="10" type="priority"/>
</net>
""",
        encoding="utf-8",
    )

    graph = build_movement_graph(net_file, "j")
    emitted = {(movement["source_edge_id"], movement["target_edge_id"]) for movement in graph["movements"] if movement["status"] == "emit"}
    review = {(movement["source_edge_id"], movement["target_edge_id"]) for movement in graph["movements"] if movement["status"] == "needs_review"}

    assert ("west_in", "east_out") in emitted
    assert ("west_in", "south_out") in emitted
    assert ("west_in", "north_out") in review
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
python -m pytest tests/test_junction_movement_model.py::test_movement_graph_does_not_emit_every_non_uturn_target -q
```

Expected: fail because current code emits the left-turn target.

- [ ] **Step 3: Implement conservative emit reason**

Replace the broad emit condition with a helper:

```python
def _movement_status(source: dict[str, Any], target: dict[str, Any], turn_class: str) -> tuple[str, float, str]:
    if turn_class in {"u_turn", "unknown"}:
        return "needs_review", 0.25, f"{turn_class} movement requires explicit review"
    if source["road_name"] and source["road_name"] == target["road_name"] and turn_class == "straight":
        return "emit", 0.95, "same-road continuation"
    if turn_class == "right":
        return "emit", 0.75, "conservative right-turn candidate"
    return "needs_review", 0.45, f"{turn_class} movement needs topology or reference evidence"
```

Use this helper in `build_movement_graph(...)`. Keep it intentionally conservative; left turns should need extra evidence before emission.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m pytest tests/test_junction_movement_model.py tests/test_junction_rebuild_candidate.py -q
```

Expected: pass after updating existing tests that assumed all non-u-turns emitted.

## Task 5: Rebuild Candidate Uses Connection Signature Blockers

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_rebuild_candidate.py`
- Test: `tests/test_junction_rebuild_candidate.py`

- [ ] **Step 1: Write failing test for signature artifact inclusion**

```python
def test_rebuild_candidate_writes_connection_signature(tmp_path: Path) -> None:
    net_file = tmp_path / "fixture.net.xml"
    net_file.write_text(
        """<net>
  <edge id="west_in" from="w" to="j" type="highway.primary" name="Main"><lane id="west_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="east_out" from="j" to="e" type="highway.primary" name="Main"><lane id="east_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="w" x="-10" y="0" type="priority"/>
  <junction id="j" x="0" y="0" type="traffic_light"/>
  <junction id="e" x="10" y="0" type="priority"/>
  <connection from="west_in" to="east_out" fromLane="0" toLane="0" dir="s" state="o"/>
</net>
""",
        encoding="utf-8",
    )

    report = build_rebuild_candidate(net_file=net_file, junction_id="j", output_dir=tmp_path / "candidate", prefix="demo")

    assert Path(report["connection_signature"]["signature_file"]).is_file()
    assert report["connection_signature"]["status"] == "pass"
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
python -m pytest tests/test_junction_rebuild_candidate.py::test_rebuild_candidate_writes_connection_signature -q
```

Expected: fail because rebuild candidate does not call the connection audit.

- [ ] **Step 3: Implement the call**

In `build_rebuild_candidate(...)`, call:

```python
from .junction_connection_audit import build_connection_signature, write_connection_signature

signature = build_connection_signature(net_file, junction_id)
signature_report = write_connection_signature(signature, output_dir, prefix)
```

Include `connection_signature: signature_report` in the returned report and summary JSON.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m pytest tests/test_junction_connection_audit.py tests/test_junction_movement_model.py tests/test_junction_rebuild_candidate.py -q
```

Expected: pass.

## Task 6: Single-Junction Diagnostic Probe

**Files:**
- No source files unless a test exposes a defect.
- Outputs under: `artifacts/ingolstadt_head_5_5_bbox_20260626/topology_connection_probe_281967823`

- [ ] **Step 1: Regenerate the `281967823` rebuild candidate**

Run a small Python command using the local package path:

```powershell
$env:PYTHONPATH = "C:\Users\huqio\Documents\Torii-SUMO\plugins\torii-sumo\src"
python - <<'PY'
from pathlib import Path
from torii_sumo.core.junction_rebuild_candidate import build_rebuild_candidate

report = build_rebuild_candidate(
    net_file=Path(r"C:\Users\huqio\Documents\Torii-SUMO\artifacts\ingolstadt_head_5_5_bbox_20260626\junction_collapse_prototype_281967823_v2\collapse_281967823_junction_aggregated.net.xml"),
    junction_id="cluster_281967823_305519232_7009179649_7626856596_#2more",
    output_dir=Path(r"C:\Users\huqio\Documents\Torii-SUMO\artifacts\ingolstadt_head_5_5_bbox_20260626\topology_connection_probe_281967823"),
    prefix="probe_281967823",
)
print(report)
PY
```

Expected: report with a lower `emitted_connection_count` than the earlier `32` emitted movement pairs, or a clear `review` status explaining why movements were blocked.

- [ ] **Step 2: Run netconvert on the candidate**

Run:

```powershell
& "C:\Program Files (x86)\Eclipse\Sumo\bin\netconvert.exe" `
  --sumo-net-file "C:\Users\huqio\Documents\Torii-SUMO\artifacts\ingolstadt_head_5_5_bbox_20260626\junction_collapse_prototype_281967823_v2\collapse_281967823_junction_aggregated.net.xml" `
  --connection-files "C:\Users\huqio\Documents\Torii-SUMO\artifacts\ingolstadt_head_5_5_bbox_20260626\topology_connection_probe_281967823\probe_281967823.con.xml" `
  --output-file "C:\Users\huqio\Documents\Torii-SUMO\artifacts\ingolstadt_head_5_5_bbox_20260626\topology_connection_probe_281967823\probe_281967823_rebuilt.net.xml" `
  2>&1 | Tee-Object "C:\Users\huqio\Documents\Torii-SUMO\artifacts\ingolstadt_head_5_5_bbox_20260626\topology_connection_probe_281967823\probe_281967823_netconvert.log"
```

Expected: generated `.net.xml`. If target-specific intersecting-left-turn warnings remain, keep claim status `construction-invalid` and use the warning lines as the next blocker.

- [ ] **Step 3: Run SUMO load proof**

Run:

```powershell
& "C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe" `
  -n "C:\Users\huqio\Documents\Torii-SUMO\artifacts\ingolstadt_head_5_5_bbox_20260626\topology_connection_probe_281967823\probe_281967823_rebuilt.net.xml" `
  --begin 0 --end 1 --no-step-log true
```

Expected: exit code `0`.

- [ ] **Step 4: Open in NetEdit connection mode**

Run:

```powershell
Start-Process -FilePath "C:\Program Files (x86)\Eclipse\Sumo\bin\netedit.exe" `
  -ArgumentList @("-s", "C:\Users\huqio\Documents\Torii-SUMO\artifacts\ingolstadt_head_5_5_bbox_20260626\topology_connection_probe_281967823\probe_281967823_rebuilt.net.xml")
```

Expected: human review determines whether connection geometry improved. GUI review is diagnostic evidence only.

## Task 7: Missed Screenshot Location Probe

**Files:**
- Source only if Task 2 needs correction.
- Output under: `artifacts/ingolstadt_head_5_5_bbox_20260626/topology_connection_missed_location_probe`

- [ ] **Step 1: Identify the nearest junction ids from the screenshot**

Use NetEdit or a short XML coordinate query on the network currently open in the screenshot. Record the chosen node ids in a JSON file:

```json
{
  "status": "manual_probe_seed",
  "claim_status": "diagnostic-demo",
  "source": "user NetEdit screenshot",
  "selection_status": "needs_manual_netedit_selection",
  "candidate_node_ids": [],
  "required_selection_evidence": "Record the SUMO junction ids visible at the screenshot location before running the probe.",
  "note": "This seed starts empty by design; the execution step must fill it from NetEdit or XML evidence before any probe can run."
}
```

The implementation worker must not run this probe while `candidate_node_ids` is empty. This is a manual probe artifact, not code.

- [ ] **Step 2: Run topology audit on the source network**

Run the smallest command or test harness that calls `audit_topology_fragmentation(...)` on the relevant network and writes its report under the probe output directory.

Expected: `topology_connection_cell_candidate_count` includes the screenshot location or the report explains why it is rejected.

- [ ] **Step 3: Inspect candidate fields**

Check:

- `node_ids`
- `internal_edge_ids`
- `boundary_edge_ids`
- `external_vehicle_approach_count`
- `connection_cell_decision`
- `reason`

Expected: the screenshot location is either a `needs_review` candidate or a deliberately rejected case with a concrete blocker.

## Task 8: Regression and Claim Boundary

**Files:**
- No source files unless tests fail.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
python -m pytest tests/test_reference_policy_audit.py tests/test_junction_connection_audit.py tests/test_junction_movement_model.py tests/test_junction_rebuild_candidate.py tests/test_topology_connection_candidates.py -q
```

Expected: all pass.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
python -m pytest -q
```

Expected: all pass.

- [ ] **Step 3: Check git diff**

Run:

```powershell
git status --short
git diff --check
```

Expected: only intended source/test/docs changes plus ignored or deliberately untracked artifacts.

- [ ] **Step 4: Commit only intended changes**

Stage source, tests, and this plan/spec if they are tracked or intentionally forced into the repo:

```powershell
git add -- plugins/torii-sumo/src/torii_sumo/core/reference_policy_audit.py `
  plugins/torii-sumo/src/torii_sumo/core/junction_connection_audit.py `
  plugins/torii-sumo/src/torii_sumo/core/junction_movement_model.py `
  plugins/torii-sumo/src/torii_sumo/core/junction_rebuild_candidate.py `
  plugins/torii-sumo/src/torii_sumo/core/topology_audit.py `
  tests/test_reference_policy_audit.py `
  tests/test_junction_connection_audit.py `
  tests/test_junction_movement_model.py `
  tests/test_junction_rebuild_candidate.py `
  tests/test_topology_connection_candidates.py
git add -f -- docs/superpowers/specs/2026-06-26-topology-connection-junction-audit.md `
  docs/superpowers/plans/2026-06-26-topology-connection-junction-audit.md
git commit -m "Add topology connection junction audit"
```

Do not stage `AGENTS.md` or broad `artifacts/`.

## Stopping Condition

Stop when:

- a teacher-policy report explains TUM road classes, permissions, cluster
  joins, TLS count, and connection counts for the bounded area;
- connection signature artifacts are produced for target junctions;
- topology-cell audit flags the screenshot-like missed candidate or gives a specific rejection reason;
- movement generation no longer emits the broad incoming-by-outgoing Cartesian set;
- the `281967823` candidate is regenerated and checked by `netconvert`, SUMO load, and NetEdit connection mode;
- the claim remains `diagnostic-demo` or `construction-invalid` unless the NetEdit review is actually clean.

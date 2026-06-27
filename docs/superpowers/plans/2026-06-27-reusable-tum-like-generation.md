# Reusable TUM-Like Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Codex 5.3 able to drive Torii/Torii-SUMO from a natural-language prompt into a reusable, non-Ingolstadt-hardcoded SUMO network workflow that produces TUM-like junction cleanup candidates and measurable NetEdit/TLS/connection/internal-junction similarity.

**Architecture:** Reuse the existing `reference_matched` workflow path and the current teacher-guided junction tools. Add a small pattern layer that extracts reusable TUM-style junction signatures by approach slot, and add a gate layer that scores generated review candidates before any stronger claim is allowed.

**Tech Stack:** Python stdlib XML/CSV/JSON, existing Torii-SUMO core modules, pytest, SUMO `netconvert`/`sumo`, NetEdit manual review.

---

## Current Evidence Boundary

The current Ingolstadt v9 artifact proves only a single diagnostic slice:

- SUMO load passed for `artifacts/ingolstadt_head_5_5_bbox_20260626/simple_crossroad_probe_89129156/tum_teacher_parity/workflow_tool_probe_v9_internal_junction_replay/torii_teacher_wo_teacher_guided.net.xml`.
- `netedit_semantics_diff_v2_internal_junction_replay/summary.json` shows `same` for TLS linkIndex, phases, junction requests, internal lanes, crossing/walkingarea junctions, and main junction attrs.
- The same summary still shows exact connection differences: `same=108`, `candidate_extra=39`, `teacher_missing_in_candidate=74`.
- `torii_teacher_wo_teacher_guided_report.json` still has `claim_status=diagnostic-demo`, `outgoing_vehicle_edge_count` delta `+5`, and skipped pedestrian connections in an earlier stage.

Do not upgrade this to global TUM parity. Treat it as the first teacher case.

## Target Files

- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/core/reference_join_audit.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/core/osm_workflow.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/core/workflow_router.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/tools/osm_tools.py`
- Modify: `tests/test_junction_teacher_model.py`
- Modify: `tests/test_reference_join_audit.py`
- Modify: `tests/test_network_plan.py`
- Modify: `tests/test_mcp_tools.py`
- Create only if the gate code does not stay small inside `junction_teacher_model.py`: `plugins/torii-sumo/src/torii_sumo/core/netedit_semantics_gate.py`
- Create only if the gate file is created: `tests/test_netedit_semantics_gate.py`

Do not add a TUM-specific router, TUM-specific MCP tool, hardcoded Ingolstadt junction id, hardcoded edge map, or TUM bbox constant.

## Task 1: Add Reusable Junction Pattern Records

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py`
- Modify: `tests/test_junction_teacher_model.py`

- [ ] **Step 1: Write the failing pattern-index test**

Add this test to `tests/test_junction_teacher_model.py`:

```python
def test_extract_junction_pattern_index_groups_by_reusable_counts(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a_in" from="a" to="j"><lane id="a_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="b_in" from="b" to="j"><lane id="b_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="c_in" from="c" to="j"><lane id="c_in_0" index="0" allow="passenger" shape="10,0 0,0"/></edge>
  <edge id="a_out" from="j" to="a2"><lane id="a_out_0" index="0" allow="passenger" shape="0,0 -10,0"/></edge>
  <edge id="b_out" from="j" to="b2"><lane id="b_out_0" index="0" allow="passenger" shape="0,0 0,-10"/></edge>
  <edge id="c_out" from="j" to="c2"><lane id="c_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="0,0 1,1"/></edge>
  <junction id="j" type="right_before_left" x="0" y="0" incLanes="a_in_0 b_in_0 c_in_0" intLanes=":j_0_0">
    <request index="0" response="0" foes="0" cont="0"/>
    <request index="1" response="0" foes="0" cont="0"/>
    <request index="2" response="0" foes="0" cont="0"/>
  </junction>
  <connection from="a_in" to="a_out" fromLane="0" toLane="0" dir="t"/>
  <connection from="a_in" to="b_out" fromLane="0" toLane="0" dir="r"/>
  <connection from="a_in" to="c_out" fromLane="0" toLane="0" dir="l"/>
</net>""",
        encoding="utf-8",
    )

    records = extract_junction_pattern_index(net_file, min_approaches=3, max_approaches=4)

    assert records == [
        {
            "junction_id": "j",
            "arm_count": 3,
            "control_type": "right_before_left",
            "in_edge_count": 3,
            "out_edge_count": 3,
            "vehicle_connection_count": 3,
            "dir_counts": {"l": 1, "r": 1, "t": 1},
            "crossing_count": 0,
            "walkingarea_count": 0,
            "request_count": 3,
            "tl_phase_count": 0,
            "controlled_link_count": 0,
        }
    ]
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest tests/test_junction_teacher_model.py::test_extract_junction_pattern_index_groups_by_reusable_counts -q
```

Expected: fail with `NameError` or import error for `extract_junction_pattern_index`.

- [ ] **Step 3: Implement the smallest pattern-index extractor**

Add to `plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py`:

```python
def extract_junction_pattern_index(
    net_file: Path,
    *,
    min_approaches: int = 3,
    max_approaches: int = 4,
) -> list[dict[str, Any]]:
    root = ET.parse(net_file).getroot()
    tl_by_id = {tl.attrib["id"]: tl for tl in root.findall("tlLogic") if tl.attrib.get("id")}
    records: list[dict[str, Any]] = []
    for junction in root.findall("junction"):
        junction_id = junction.attrib.get("id", "")
        if not junction_id or junction_id.startswith(":"):
            continue
        model = extract_teacher_junction_model(net_file, junction_id)
        summary = model.get("summary", {})
        arm_count = min(
            int(summary.get("incoming_vehicle_edge_count", 0)),
            int(summary.get("outgoing_vehicle_edge_count", 0)),
        )
        if arm_count < min_approaches or arm_count > max_approaches:
            continue
        dir_counts = dict(summary.get("vehicle_connection_dirs", {}))
        all_connections = model.get("vehicle_connections", []) + model.get("pedestrian_connections", [])
        controlled_connections = [
            connection
            for connection in all_connections
            if isinstance(connection, dict) and connection.get("tl") and connection.get("linkIndex")
        ]
        controlled_tl_ids = {str(connection.get("tl", "")) for connection in controlled_connections}
        records.append(
            {
                "junction_id": junction_id,
                "arm_count": arm_count,
                "control_type": junction.attrib.get("type", ""),
                "in_edge_count": int(summary.get("incoming_vehicle_edge_count", 0)),
                "out_edge_count": int(summary.get("outgoing_vehicle_edge_count", 0)),
                "vehicle_connection_count": int(summary.get("vehicle_connection_count", 0)),
                "dir_counts": dict(sorted(dir_counts.items())),
                "crossing_count": int(summary.get("crossing_count", 0)),
                "walkingarea_count": int(summary.get("walkingarea_count", 0)),
                "request_count": len(junction.findall("request")),
                "tl_phase_count": sum(
                    len(tl_by_id[tl_id].findall("phase")) for tl_id in controlled_tl_ids if tl_id in tl_by_id
                ),
                "controlled_link_count": len(controlled_connections),
            }
        )
    return records
```

Also import `Counter` from `collections`.

- [ ] **Step 4: Run the focused test**

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest tests/test_junction_teacher_model.py::test_extract_junction_pattern_index_groups_by_reusable_counts -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py tests/test_junction_teacher_model.py
git commit -m "feat: extract reusable junction pattern index"
```

## Task 2: Add Approach-Slot Exemplar Records

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py`
- Modify: `tests/test_junction_teacher_model.py`

- [ ] **Step 1: Write the failing exemplar test**

Add this test:

```python
def test_extract_junction_pattern_exemplar_uses_slots_not_edge_ids(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <edge id="north_in" from="n" to="j"><lane id="north_in_0" index="0" allow="passenger" speed="13.89" shape="0,10 0,0"/></edge>
  <edge id="east_out" from="j" to="e"><lane id="east_out_0" index="0" allow="passenger" speed="13.89" shape="0,0 10,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" speed="10.0" shape="0,0 2,0"/></edge>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="north_in_0" intLanes=":j_0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <tlLogic id="j" type="actuated" programID="0" offset="0"><phase duration="30" state="G"/></tlLogic>
  <connection from="north_in" to="east_out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="r" state="O"/>
</net>""",
        encoding="utf-8",
    )

    exemplar = extract_junction_pattern_exemplar(net_file, "j")

    assert exemplar["junction_id"] == "j"
    assert exemplar["approach_slots"][0]["slot_id"] == "slot_0"
    assert exemplar["approach_slots"][0]["members"] == ["north_in"]
    assert exemplar["vehicle_connections"] == [
        {
            "from_slot": "slot_0",
            "to_slot": "slot_1",
            "fromLane": "0",
            "toLane": "0",
            "via": ":j_0_0",
            "tl": "j",
            "linkIndex": "0",
            "dir": "r",
            "state": "O",
        }
    ]
    assert exemplar["traffic_light"]["phases"][0]["state"] == "G"
    assert exemplar["requests"][0]["foes"] == "0"
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest tests/test_junction_teacher_model.py::test_extract_junction_pattern_exemplar_uses_slots_not_edge_ids -q
```

Expected: fail because `extract_junction_pattern_exemplar` does not exist.

- [ ] **Step 3: Implement the minimal exemplar extractor**

Add:

```python
def extract_junction_pattern_exemplar(net_file: Path, junction_id: str) -> dict[str, Any]:
    model = extract_teacher_junction_model(net_file, junction_id)
    incoming = [edge["edge_id"] for edge in model.get("approaches", {}).get("incoming", [])]
    outgoing = [edge["edge_id"] for edge in model.get("approaches", {}).get("outgoing", [])]
    slots = []
    edge_to_slot: dict[str, str] = {}
    for index, edge_id in enumerate(dict.fromkeys(incoming + outgoing)):
        slot_id = f"slot_{index}"
        edge_to_slot[edge_id] = slot_id
        slots.append({"slot_id": slot_id, "members": [edge_id]})

    vehicle_connections = []
    for connection in model.get("vehicle_connections", []):
        if not isinstance(connection, dict):
            continue
        source_slot = edge_to_slot.get(str(connection.get("from", "")))
        target_slot = edge_to_slot.get(str(connection.get("to", "")))
        if not source_slot or not target_slot:
            continue
        vehicle_connections.append(
            {
                "from_slot": source_slot,
                "to_slot": target_slot,
                "fromLane": str(connection.get("fromLane", "")),
                "toLane": str(connection.get("toLane", "")),
                "via": str(connection.get("via", "")),
                "tl": str(connection.get("tl", "")),
                "linkIndex": str(connection.get("linkIndex", "")),
                "dir": str(connection.get("dir", "")),
                "state": str(connection.get("state", "")),
            }
        )

    root = ET.parse(net_file).getroot()
    junction = root.find(f"junction[@id='{junction_id}']")
    requests = [dict(request.attrib) for request in junction.findall("request")] if junction is not None else []
    return {
        "schema_version": 1,
        "junction_id": junction_id,
        "approach_slots": slots,
        "vehicle_connections": vehicle_connections,
        "traffic_light": model.get("traffic_light", {}),
        "requests": requests,
        "summary": model.get("summary", {}),
    }
```

This first implementation intentionally groups one edge per slot. Do not add geometric clustering in this task.

- [ ] **Step 4: Run the focused test**

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest tests/test_junction_teacher_model.py::test_extract_junction_pattern_exemplar_uses_slots_not_edge_ids -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py tests/test_junction_teacher_model.py
git commit -m "feat: extract junction pattern exemplars"
```

## Task 3: Add NetEdit Semantics Gate

**Files:**
- Prefer modify: `plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py`
- Create only if needed: `plugins/torii-sumo/src/torii_sumo/core/netedit_semantics_gate.py`
- Modify or create matching tests.

- [ ] **Step 1: Write the failing gate test**

Use the existing teacher model fixture style. If a new file is needed, create `tests/test_netedit_semantics_gate.py`; otherwise add to `tests/test_junction_teacher_model.py`:

```python
def test_netedit_semantics_gate_fails_on_non_same_statuses() -> None:
    summary = {
        "status_counts": {
            "tls_linkIndex_diff": {"same": 23},
            "phase_diff": {"same": 10},
            "request_diff": {"same": 41},
            "internal_lane_diff": {"same": 59},
            "crossing_walkingarea_diff": {"same": 10},
            "junction_attrs_diff": {"same": 8},
            "connection_exact_diff": {"same": 108, "candidate_extra": 1},
        }
    }

    result = evaluate_netedit_semantics_gate(summary)

    assert result == {
        "status": "fail",
        "failed_tables": ["connection_exact_diff"],
        "reason": "non_same_rows_present",
    }
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run the specific test with `PYTHONPATH`.

- [ ] **Step 3: Implement the gate**

Add:

```python
def evaluate_netedit_semantics_gate(summary: dict[str, Any]) -> dict[str, Any]:
    failed = []
    for table, counts in dict(summary.get("status_counts", {})).items():
        if not isinstance(counts, dict):
            failed.append(str(table))
            continue
        non_same = {key: value for key, value in counts.items() if key != "same" and int(value) != 0}
        if non_same:
            failed.append(str(table))
    if failed:
        return {"status": "fail", "failed_tables": failed, "reason": "non_same_rows_present"}
    return {"status": "pass", "failed_tables": [], "reason": ""}
```

- [ ] **Step 4: Add a passing test**

```python
def test_netedit_semantics_gate_passes_when_all_tables_are_same() -> None:
    summary = {
        "status_counts": {
            "tls_linkIndex_diff": {"same": 23},
            "phase_diff": {"same": 10},
            "request_diff": {"same": 41},
        }
    }

    assert evaluate_netedit_semantics_gate(summary)["status"] == "pass"
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py tests/test_junction_teacher_model.py
git commit -m "feat: gate netedit semantics parity"
```

Adjust the paths if `netedit_semantics_gate.py` is created.

## Task 4: Wire Pattern Reporting Into `reference_matched` Workflow

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/reference_join_audit.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/core/osm_workflow.py`
- Modify: `tests/test_reference_join_audit.py`
- Modify: `tests/test_network_plan.py`

- [ ] **Step 1: Write a reference audit test for pattern index output**

Add to `tests/test_reference_join_audit.py`:

```python
def test_reference_join_audit_reports_reusable_junction_patterns(tmp_path: Path) -> None:
    reference = tmp_path / "reference.net.xml"
    candidate = tmp_path / "candidate.net.xml"
    reference.write_text(
        """<net>
  <edge id="west_in" from="w" to="cluster_a_b"><lane id="west_in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="south_in" from="s" to="cluster_a_b"><lane id="south_in_0" index="0" allow="passenger" shape="0,-10 0,0"/></edge>
  <edge id="north_in" from="n" to="cluster_a_b"><lane id="north_in_0" index="0" allow="passenger" shape="0,10 0,0"/></edge>
  <edge id="east_out" from="cluster_a_b" to="e"><lane id="east_out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id="south_out" from="cluster_a_b" to="so"><lane id="south_out_0" index="0" allow="passenger" shape="0,0 0,-10"/></edge>
  <edge id="north_out" from="cluster_a_b" to="no"><lane id="north_out_0" index="0" allow="passenger" shape="0,0 0,10"/></edge>
  <junction id="cluster_a_b" type="right_before_left" x="0" y="0" incLanes="west_in_0 south_in_0 north_in_0" intLanes="">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <connection from="west_in" to="east_out" fromLane="0" toLane="0" dir="s"/>
  <connection from="south_in" to="south_out" fromLane="0" toLane="0" dir="s"/>
  <connection from="north_in" to="north_out" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )
    candidate.write_text(
        """<net>
  <edge id="internal_ab" from="a" to="b"><lane id="internal_ab_0" index="0" length="7" shape="-3,0 4,0"/></edge>
  <edge id="internal_bc" from="b" to="c"><lane id="internal_bc_0" index="0" length="6" shape="4,0 8,2"/></edge>
  <junction id="a" x="-3" y="0" type="traffic_light"/>
  <junction id="b" x="4" y="0" type="traffic_light"/>
  <junction id="c" x="8" y="2" type="priority"/>
</net>""",
        encoding="utf-8",
    )

    report = audit_reference_join_patterns(
        reference_net_file=reference,
        candidate_net_file=candidate,
        output_dir=tmp_path / "audit",
        reference_cluster_prefix="cluster_",
        candidate_cluster_radius_m=20,
        match_radius_m=20,
    )

    assert report["junction_pattern_index"][0]["junction_id"] == "cluster_a_b"
    assert report["junction_pattern_index"][0]["control_type"] == "right_before_left"
    assert report["junction_pattern_index"][0]["arm_count"] == 3
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest tests/test_reference_join_audit.py::test_reference_join_audit_reports_reusable_junction_patterns -q
```

Expected: fail because `junction_pattern_index` is missing.

- [ ] **Step 3: Add pattern index to `audit_reference_join_patterns`**

In `plugins/torii-sumo/src/torii_sumo/core/reference_join_audit.py`, import `extract_junction_pattern_index` and add this field to the returned report:

```python
"junction_pattern_index": extract_junction_pattern_index(reference_net_file),
```

If the reference file is not a SUMO net with lanes/connections, return an empty list rather than failing the whole audit.

- [ ] **Step 4: Add workflow propagation test**

Add or extend a `reference_matched` workflow test in `tests/test_network_plan.py` to assert that `reference_join_audit["junction_pattern_index"]` survives into the workflow report.

- [ ] **Step 5: Commit**

Run:

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/reference_join_audit.py plugins/torii-sumo/src/torii_sumo/core/osm_workflow.py tests/test_reference_join_audit.py tests/test_network_plan.py
git commit -m "feat: report reusable reference junction patterns"
```

## Task 5: Keep Teacher-Guided Replay Opt-In And Add Gates To Its Report

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_rebuild_candidate.py`
- Modify: `tests/test_junction_rebuild_candidate.py`

- [ ] **Step 1: Write a report-gate test**

Extend `test_build_teacher_guided_junction_variant_can_replay_and_normalize_target_internal_subgraph` in `tests/test_junction_rebuild_candidate.py` with these assertions immediately after `assert report["status"] == "pass"`:

```python
assert report["claim_status"] == "diagnostic-demo"
assert report["parity_gate_status"] == "pass"
assert report["review_policy"].startswith("diagnostic")
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest tests/test_junction_rebuild_candidate.py::test_build_teacher_guided_junction_variant_can_replay_and_normalize_target_internal_subgraph -q
```

Expected: fail because `parity_gate_status` is missing.

- [ ] **Step 3: Add the smallest gate status field**

In `build_teacher_guided_junction_variant`, after computing `final_model`, add:

```python
parity = _compare_teacher_models(teacher_model, final_model)
parity_gate_status = "pass" if all(value == 0 for value in parity.get("delta", {}).values()) else "fail"
```

Use `parity` in the report instead of recomputing `_compare_teacher_models(...)`.

- [ ] **Step 4: Keep `claim_status` diagnostic even when gate passes**

Do not change this:

```python
"claim_status": "diagnostic-demo" if status == "pass" else "construction-invalid"
```

The gate is evidence, not a claim promotion.

- [ ] **Step 5: Commit**

Run:

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/junction_rebuild_candidate.py tests/test_junction_rebuild_candidate.py
git commit -m "feat: report teacher parity gate status"
```

## Task 6: Verify On One Non-Target Junction Before Expanding

**Files:**
- Artifact only under `artifacts/`
- No production code changes unless a gate failure identifies a reusable bug.

- [ ] **Step 1: Pick one non-target TUM pattern exemplar**

Use `artifacts/ingolstadt_head_5_5_bbox_20260626/simple_crossroad_probe_89129156/tum_teacher_parity/tum_junction_pattern_probe_v1/three_four_way_pattern_summary.csv`.

Pick the most common 3-way non-signalized pattern:

```text
approaches=3|type=right_before_left|inEdges=3|outEdges=3|vehConns=9|dirs=l:2,r:2,s:2,t:3|cross=0|walk=0|phases=0|tlsLinks=0|requests=9
```

- [ ] **Step 2: Extract its exemplar**

Run a one-off Python command using `extract_junction_pattern_exemplar(...)` and write:

```text
artifacts/tum_pattern_validation_v1/three_way_right_before_left_exemplar.json
```

- [ ] **Step 3: Run the same extraction for the existing 4-way signalized target**

Write:

```text
artifacts/tum_pattern_validation_v1/four_way_signalized_exemplar.json
```

- [ ] **Step 4: Compare schema, not geometry**

Write:

```text
artifacts/tum_pattern_validation_v1/pattern_schema_check.json
```

Expected fields:

```json
{
  "three_way_has_slots": true,
  "four_way_has_slots": true,
  "three_way_has_connections": true,
  "four_way_has_tls": true,
  "status": "pass"
}
```

- [ ] **Step 5: Stop condition**

Stop after the schema check passes. Do not claim that non-target generation works until an actual candidate network is generated and reviewed.

## Final Verification

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest -q
```

Expected: all tests pass.

Then run:

```powershell
git status --short
```

Expected: only intentional tracked changes are staged or committed; `AGENTS.md` and `artifacts/` remain uncommitted unless the user explicitly asks to track them.

## Claim Boundary

After this plan, the strongest allowed claim is:

```text
Torii has a reusable, non-Ingolstadt-hardcoded reference-matched path that can extract TUM-like junction pattern records and gate teacher-guided review candidates with explicit NetEdit/TLS/connection/internal-junction parity checks.
```

Do not claim:

```text
Torii globally reproduces TUM Ingolstadt cleanup.
```

That stronger claim requires a predeclared multi-case suite with all automated gates passing, all approach mappings accepted, NetEdit connection-mode review accepted, and Google Maps/manual map scope checks accepted.

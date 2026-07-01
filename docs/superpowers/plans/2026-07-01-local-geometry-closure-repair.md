# Local Geometry Closure Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent teacher-guided replay from mixing TUM-translated junction positions with stale candidate edge geometry.

**Architecture:** Extend the existing stale-split replay path with a bounded local geometry closure: when stale split replay moves a road chain into the teacher coordinate frame, teacher-known non-internal incident edges are replayed only from the teacher-confirmed local broken chain. Their endpoints enter the retune frontier. Keep teacher-absent tail deletion separate.

**Closed-loop update:** A first broad frontier implementation fixed the visible shifted edges but replayed 46 unrelated context edges and broke SUMO load. The accepted control action is a bounded frontier seeded by teacher dead ends and stale split continuations; in the 98101394 probe it replays only the five expected context edges (`148449854`, `37386279#0`, `-37386279#0`, `37386279#1`, `-37386279#1`) while SUMO load and parity pass.

**Tech Stack:** Python, `xml.etree.ElementTree`, pytest, SUMO `sumo.exe`.

---

### Task 1: Regression Fixture

**Files:**
- Modify: `tests/test_junction_rebuild_candidate.py`

- [x] **Step 1: Extend the existing stale split test**

Add teacher-known context edges incident to the retuned terminal:

```xml
<edge id="foot" from="walk" to="next_far" type="highway.path"><lane id="foot_0" index="0" shape="72,110 70,102"/></edge>
<edge id="side#0" from="walk" to="side_far" type="highway.residential"><lane id="side#0_0" index="0" shape="72,110 90,112"/></edge>
```

Add matching stale candidate edges:

```xml
<edge id="foot" from="walk" to="next_far" type="highway.path"><lane id="foot_0" index="0" shape="-90,-70 -90,-38"/></edge>
<edge id="side#0" from="walk" to="side_far" type="highway.residential"><lane id="side#0_0" index="0" shape="-90,-70 -110,-70"/></edge>
```

- [x] **Step 2: Assert geometry closure**

```python
assert root.find("edge[@id='foot']/lane").attrib["shape"] == "-28.00,10.00 -30.00,2.00"
assert root.find("edge[@id='side#0']/lane").attrib["shape"] == "-28.00,10.00 -10.00,12.00"
assert root.find("junction[@id='walk']").attrib["x"] == "-28.00"
assert root.find("junction[@id='walk']").attrib["y"] == "10.00"
```

- [x] **Step 3: Run RED**

Run:

```powershell
pytest tests/test_junction_rebuild_candidate.py::test_write_teacher_target_internal_replay_net_removes_stale_same_family_split_fragment -q
```

Expected: fail because `foot` and `side#0` still use stale candidate geometry.

### Task 2: Local Closure Implementation

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_rebuild_candidate.py`

- [x] **Step 1: Add a local non-internal edge predicate**

Use existing edge data. Exclude only internal/crossing/walkingarea edges.

- [x] **Step 2: Replay same-id teacher-known incident edges**

After stale split follow-up replay and dead-end/tail deletion, scan the bounded local frontier. For every teacher edge whose `from` or `to` touches the frontier and whose same id exists in the candidate, replay the teacher geometry with the existing edge clone helper.

- [x] **Step 3: Add replayed endpoints to the retune frontier**

This keeps junction positions and lane shapes in the same coordinate frame.

- [x] **Step 4: Report replayed context edges**

Add:

```python
"replayed_stale_split_context_edges": replayed_stale_split_context_edges
```

### Task 3: Verification

**Files:**
- No new files.

- [x] **Step 1: Run the focused test**

```powershell
pytest tests/test_junction_rebuild_candidate.py::test_write_teacher_target_internal_replay_net_removes_stale_same_family_split_fragment -q
```

- [x] **Step 2: Run affected tests**

```powershell
pytest tests/test_junction_rebuild_candidate.py tests/test_network_plan.py -q
```

- [x] **Step 3: Re-run the 98101394 probe**

Use the previous run report as input and write a fresh output directory.

- [x] **Step 4: Inspect key edges**

Confirm `148449854`, `37386279#0`, `-37386279#0`, `37386279#1`, and `-37386279#1` are replayed or no longer mixed with retuned junctions.

- [x] **Step 5: SUMO load and NetEdit**

Run SUMO load on the new candidate and open TUM plus candidate in NetEdit.

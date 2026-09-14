# TUM Self-Replay Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a TUM-first self-replay gate so selected TUM reference junctions can be code-replayed and compared before Torii OSM candidates are repaired.

**Architecture:** Reuse `junction_teacher_model.py` for extracting teacher semantics and add only the missing self-replay bundle/writer functions there unless the file becomes too large during execution. Keep workflow integration out of the first pass; the first deliverable is a focused corpus artifact and testable parity gate.

**Tech Stack:** Python stdlib XML/JSON/CSV, existing Torii-SUMO teacher model helpers, pytest, SUMO `sumo`, NetEdit manual review.

---

## Current Evidence Boundary

Existing teacher-guided repair can produce candidate nets with zero semantic
delta on selected small probes, but those runs start from Torii candidates.
They do not isolate whether Torii can deterministically replay the TUM teacher
itself.

This plan adds the missing first layer:

```text
TUM reference net -> teacher bundle -> code-written replay net -> parity gate
```

Do not connect this to full OSM workflow promotion until at least one replayed
TUM junction passes all self-replay gates.

## Target Files

- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py`
- Modify: `tests/test_junction_teacher_model.py`
- Artifact output only: `E:/torii_sumo_runs/tum_self_replay_corpus_20260701/`

Do not add a new MCP tool, router mode, or OSM workflow branch in this plan.

## Task 1: Add Canonical Teacher Bundle Signature

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py`
- Modify: `tests/test_junction_teacher_model.py`

- [ ] **Step 1: Write the failing canonical signature test**

Add this test to `tests/test_junction_teacher_model.py`:

```python
def test_canonical_teacher_junction_bundle_keeps_replay_critical_tables(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net>
  <location netOffset="0.00,0.00" convBoundary="-10.00,-10.00,10.00,10.00" origBoundary="-10.00,-10.00,10.00,10.00" projParameter="!"/>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" allow="passenger" speed="13.89" length="10.00" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0" allow="passenger" speed="13.89" length="10.00" shape="0,0 10,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" allow="passenger" shape="0,0 5,0"/></edge>
  <edge id=":j_w0" function="walkingarea"><lane id=":j_w0_0" index="0" allow="pedestrian" shape="0,2 2,2"/></edge>
  <junction id="a" type="dead_end" x="-10" y="0" incLanes="" intLanes=""/>
  <junction id="b" type="dead_end" x="10" y="0" incLanes="out_0" intLanes=""/>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="in_0 :j_w0_0" intLanes=":j_0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <junction id=":j_0_0" type="internal" x="1" y="0" incLanes=":j_0_0" intLanes=""/>
  <tlLogic id="j" type="actuated" programID="0" offset="0"><phase duration="30" state="G"/></tlLogic>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="s" state="O"/>
</net>""",
        encoding="utf-8",
    )

    bundle = canonical_teacher_junction_bundle(net_file, "j")

    assert bundle["junction_id"] == "j"
    assert bundle["junctions"][0]["id"] == ":j_0_0"
    assert bundle["junctions"][1]["id"] == "a"
    assert bundle["junctions"][2]["id"] == "b"
    assert bundle["junctions"][3]["id"] == "j"
    assert bundle["edges"][0]["id"] == ":j_0"
    assert bundle["edges"][1]["id"] == ":j_w0"
    assert bundle["edges"][2]["id"] == "in"
    assert bundle["edges"][3]["id"] == "out"
    assert bundle["connections"] == [
        {
            "dir": "s",
            "from": "in",
            "fromLane": "0",
            "linkIndex": "0",
            "state": "O",
            "tl": "j",
            "to": "out",
            "toLane": "0",
            "via": ":j_0_0",
        }
    ]
    assert bundle["tlLogics"][0]["id"] == "j"
    assert bundle["summary"]["connection_count"] == 1
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest tests/test_junction_teacher_model.py::test_canonical_teacher_junction_bundle_keeps_replay_critical_tables -q
```

Expected: fail because `canonical_teacher_junction_bundle` is not defined.

- [ ] **Step 3: Implement the minimal canonical bundle**

Add `canonical_teacher_junction_bundle(net_file: Path, junction_id: str) -> dict[str, Any]`.

Implementation rules:

- Parse the SUMO `.net.xml` with `xml.etree.ElementTree`.
- Start from `extract_teacher_junction_model(net_file, junction_id)`.
- Include the main junction, internal junctions whose ids start with `:{junction_id}_`, and boundary junctions referenced by selected non-internal edges.
- Include incident approach edges, internal edges, crossings, and walkingareas from the teacher model.
- Include only connections where `from` or `to` is in the selected edge set, or `via` starts with `:{junction_id}_`.
- Include TLS logic when the teacher model has a `traffic_light.attributes.id`.
- Store every XML element as a sorted attribute dict plus sorted child lane/request/phase dicts.
- Return a deterministic dict with keys: `junction_id`, `location`, `junctions`, `edges`, `connections`, `tlLogics`, `summary`.

- [ ] **Step 4: Run the focused test**

Run the same pytest command as Step 2.

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py tests/test_junction_teacher_model.py
git commit -m "feat: extract canonical TUM replay bundle"
```

## Task 2: Write A Code-Generated Self-Replay Net

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py`
- Modify: `tests/test_junction_teacher_model.py`

- [ ] **Step 1: Write the failing self-replay writer test**

Add:

```python
def test_write_teacher_self_replay_net_round_trips_canonical_bundle(tmp_path: Path) -> None:
    teacher = tmp_path / "teacher.net.xml"
    replay = tmp_path / "replay.net.xml"
    teacher.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" allow="passenger" shape="0,0 5,0"/></edge>
  <junction id="a" type="dead_end" x="-10" y="0" incLanes="" intLanes=""/>
  <junction id="b" type="dead_end" x="10" y="0" incLanes="out_0" intLanes=""/>
  <junction id="j" type="traffic_light" x="0" y="0" incLanes="in_0" intLanes=":j_0_0">
    <request index="0" response="0" foes="0" cont="0"/>
  </junction>
  <junction id=":j_0_0" type="internal" x="1" y="0" incLanes=":j_0_0" intLanes=""/>
  <tlLogic id="j" type="static" programID="0" offset="0"><phase duration="30" state="G"/></tlLogic>
  <connection from="in" to="out" fromLane="0" toLane="0" via=":j_0_0" tl="j" linkIndex="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )

    report = write_teacher_self_replay_net(teacher, "j", replay)

    assert report["status"] == "pass"
    assert replay.exists()
    assert canonical_teacher_junction_bundle(teacher, "j") == canonical_teacher_junction_bundle(replay, "j")
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest tests/test_junction_teacher_model.py::test_write_teacher_self_replay_net_round_trips_canonical_bundle -q
```

Expected: fail because `write_teacher_self_replay_net` is not defined.

- [ ] **Step 3: Implement the writer**

Add `write_teacher_self_replay_net(teacher_net_file: Path, junction_id: str, output_file: Path) -> dict[str, Any]`.

Implementation rules:

- Call `canonical_teacher_junction_bundle(...)`.
- Create `<net>` and write `location`, `edge`, `junction`, `tlLogic`, and `connection` elements from the canonical bundle.
- Preserve child ordering inside each table: lanes, requests, and phases sorted by stable keys.
- Write with `encoding="utf-8"` and XML declaration.
- Re-read the output and compare canonical bundles.
- Return `{"status": "pass", "output_file": str(output_file), "parity_delta": {}}` when equal.
- Return `{"status": "fail", "output_file": str(output_file), "parity_delta": {"canonical_bundle": 1}}` when unequal.

- [ ] **Step 4: Run the focused test**

Run the same pytest command as Step 2.

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py tests/test_junction_teacher_model.py
git commit -m "feat: write TUM teacher self replay net"
```

## Task 3: Add A Self-Replay Corpus Report

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py`
- Modify: `tests/test_junction_teacher_model.py`

- [ ] **Step 1: Write the failing corpus report test**

Add:

```python
def test_build_teacher_self_replay_corpus_report_writes_artifacts(tmp_path: Path) -> None:
    teacher = tmp_path / "teacher.net.xml"
    out_dir = tmp_path / "corpus"
    teacher.write_text(
        """<net>
  <edge id="in" from="a" to="j"><lane id="in_0" index="0" allow="passenger" shape="-10,0 0,0"/></edge>
  <edge id="out" from="j" to="b"><lane id="out_0" index="0" allow="passenger" shape="0,0 10,0"/></edge>
  <junction id="a" type="dead_end" x="-10" y="0" incLanes="" intLanes=""/>
  <junction id="b" type="dead_end" x="10" y="0" incLanes="out_0" intLanes=""/>
  <junction id="j" type="priority" x="0" y="0" incLanes="in_0" intLanes=""/>
  <connection from="in" to="out" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )

    report = build_teacher_self_replay_corpus_report(
        teacher,
        ["j"],
        out_dir,
        run_sumo=False,
    )

    assert report["status"] == "pass"
    assert report["cases"][0]["junction_id"] == "j"
    assert Path(report["cases"][0]["replay_net_file"]).exists()
    assert (out_dir / "teacher_self_replay_corpus.json").exists()
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest tests/test_junction_teacher_model.py::test_build_teacher_self_replay_corpus_report_writes_artifacts -q
```

Expected: fail because `build_teacher_self_replay_corpus_report` is not defined.

- [ ] **Step 3: Implement the report**

Add `build_teacher_self_replay_corpus_report(teacher_net_file: Path, junction_ids: list[str], output_dir: Path, *, run_sumo: bool = True) -> dict[str, Any]`.

Implementation rules:

- Create `output_dir`.
- For each junction, write `<junction_id>_teacher_self_replay.net.xml`.
- Save `<junction_id>_canonical_bundle.json`.
- When `run_sumo=True`, run `sumo -n <replay>` with `subprocess.run(..., capture_output=True, text=True)`.
- Store `sumo_returncode`, `sumo_stdout`, and `sumo_stderr` per case.
- Report case `status="pass"` only when canonical replay parity passes and SUMO return code is `0` or SUMO was explicitly skipped.
- Write `teacher_self_replay_corpus.json` in `output_dir`.

- [ ] **Step 4: Run the focused test**

Run the same pytest command as Step 2.

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py tests/test_junction_teacher_model.py
git commit -m "feat: report TUM self replay corpus"
```

## Task 4: Run The First Real TUM Self-Replay Corpus

**Files:**
- Artifact only: `E:/torii_sumo_runs/tum_self_replay_corpus_20260701/`

- [ ] **Step 1: Run the corpus builder on the two current probe junctions**

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'
@'
from pathlib import Path
from torii_sumo.core.junction_teacher_model import build_teacher_self_replay_corpus_report

teacher = Path("examples/02_one_prompt_osm_network/networks/tum_ingolstadt_center_reference.net.xml")
out_dir = Path("E:/torii_sumo_runs/tum_self_replay_corpus_20260701")
junction_ids = [
    "7616444534",
    "cluster_1833941945_1833941950_1833941953_32564122",
]
report = build_teacher_self_replay_corpus_report(teacher, junction_ids, out_dir, run_sumo=True)
print(report["status"])
for case in report["cases"]:
    print(case["junction_id"], case["status"], case.get("sumo_returncode"))
'@ | python -
```

Expected: printed report status is `pass`.

- [ ] **Step 2: Open the generated replay nets in NetEdit**

Run:

```powershell
netedit -s E:/torii_sumo_runs/tum_self_replay_corpus_20260701/7616444534_teacher_self_replay.net.xml
netedit -s E:/torii_sumo_runs/tum_self_replay_corpus_20260701/cluster_1833941945_1833941950_1833941953_32564122_teacher_self_replay.net.xml
```

Expected: both files open; switch to connection mode for manual screenshot review.

- [ ] **Step 3: Record the visual review command**

Append a `netedit_review.md` file under the artifact directory with the exact
teacher and replay files opened, the NetEdit mode used, and whether the visual
connection layout matches.

- [ ] **Step 4: Stop**

Do not run full OSM workflow in this task. The output is a TUM self-replay
corpus, not an OSM reproduction claim.

## Task 5: Promote Only Repeated Lessons Into Reusable Rules

**Files:**
- Modify only after Task 4 passes: `plugins/torii-sumo/src/torii_sumo/core/junction_teacher_model.py`
- Modify only after Task 4 passes: `tests/test_junction_teacher_model.py`

- [ ] **Step 1: Compare corpus bundle summaries**

Use `teacher_self_replay_corpus.json` and identify repeated fields across cases:

- `pattern_family`
- `control_type`
- `dir_counts`
- `crossing_count`
- `walkingarea_count`
- `tl_phase_count`
- `controlled_link_count`
- `internal_edge_count`
- `internal_junction_count`

- [ ] **Step 2: Write one failing test for one repeated lesson**

Only add a test when a repeated behavior is visible in at least two corpus
cases or is a direct SUMO invariant such as `dir="t"` not replacing non-turnaround
vehicle movement.

- [ ] **Step 3: Implement the smallest reusable rule**

Implement the rule in an existing function if possible. Create a new helper
only when the rule would otherwise duplicate logic in two places.

- [ ] **Step 4: Run focused tests and commit**

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest tests/test_junction_teacher_model.py -q
```

Commit only the rule and its test.

## Final Verification

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest tests/test_junction_teacher_model.py -q
git status --short
```

Expected:

- focused tests pass.
- generated corpus artifacts remain outside git.
- `AGENTS.md` remains untracked.
- only intentional source/test/doc changes are committed.

## Claim Boundary

After Tasks 1-4, the strongest allowed claim is:

```text
Torii has a TUM-first self-replay gate that can verify selected TUM reference
junctions before OSM candidate repair.
```

Do not claim:

```text
Torii can reproduce arbitrary TUM junctions from OSM.
```

That claim requires the later OSM/Torii candidate phase to pass the same gates.

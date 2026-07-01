# TUM Road Connectivity Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a road-connectivity teacher layer that learns TUM edge chaining and non-junction road continuity separately from junction-internal replay.

**Architecture:** Create a small `road_connectivity_teacher_model.py` module beside the junction teacher model. It extracts non-internal road edges, lane records, endpoint junctions, and road-to-road connections into canonical records; a later task writes a self-replay road probe and validates missing references, SUMO load, and routeability.

**Tech Stack:** Python stdlib XML/JSON/subprocess, existing Torii-SUMO test style, pytest, SUMO `sumo`, optional `duarouter` or `randomTrips.py` for routeability.

---

## Current Evidence Boundary

The current TUM self-replay corpus proves selected junction-local bundles can
round-trip and SUMO-load. It does not prove that TUM road corridors, edge
segmentation, boundary continuity, or non-junction road connections are learned.

This plan adds the missing layer:

```text
TUM reference net -> road connectivity bundle -> code-written road replay net -> road gates
```

Do not wire this into the full OSM workflow until one small road corridor probe
passes.

## Target Files

- Create: `plugins/torii-sumo/src/torii_sumo/core/road_connectivity_teacher_model.py`
- Create: `tests/test_road_connectivity_teacher_model.py`
- Artifact output only: `E:/torii_sumo_runs/tum_road_connectivity_replay_20260701/`

Do not modify `osm_workflow.py`, MCP tools, workflow router, or junction replay
code in this plan.

## Task 1: Extract A Canonical Road Connectivity Bundle

**Files:**
- Create: `plugins/torii-sumo/src/torii_sumo/core/road_connectivity_teacher_model.py`
- Create: `tests/test_road_connectivity_teacher_model.py`

- [ ] **Step 1: Write the failing extractor test**

Create `tests/test_road_connectivity_teacher_model.py`:

```python
from pathlib import Path

from torii_sumo.core.road_connectivity_teacher_model import canonical_road_connectivity_bundle


def test_canonical_road_connectivity_bundle_extracts_edge_chain_and_connections(tmp_path: Path) -> None:
    net_file = tmp_path / "teacher.net.xml"
    net_file.write_text(
        """<net version="1.20">
  <edge id="west" from="w" to="j1" name="Main"><lane id="west_0" index="0" allow="passenger" speed="13.89" shape="-20,0 -10,0"/></edge>
  <edge id="mid" from="j1" to="j2" name="Main"><lane id="mid_0" index="0" allow="passenger" speed="13.89" shape="-10,0 0,0"/></edge>
  <edge id="east" from="j2" to="e" name="Main"><lane id="east_0" index="0" allow="passenger" speed="13.89" shape="0,0 10,0"/></edge>
  <edge id="sidewalk" from="w" to="j2" type="highway.footway"><lane id="sidewalk_0" index="0" allow="pedestrian" shape="-20,2 0,2"/></edge>
  <edge id=":j1_0" function="internal"><lane id=":j1_0_0" index="0" shape="-10,0 -9,0"/></edge>
  <junction id="w" type="dead_end" x="-20" y="0" incLanes="" intLanes=""/>
  <junction id="j1" type="priority" x="-10" y="0" incLanes="west_0" intLanes=":j1_0_0"/>
  <junction id="j2" type="priority" x="0" y="0" incLanes="mid_0 sidewalk_0" intLanes=""/>
  <junction id="e" type="dead_end" x="10" y="0" incLanes="east_0" intLanes=""/>
  <connection from="west" to="mid" fromLane="0" toLane="0" dir="s"/>
  <connection from="mid" to="east" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )

    bundle = canonical_road_connectivity_bundle(net_file, seed_edge_ids=["mid"], hop_radius=1)

    assert [edge["id"] for edge in bundle["edges"]] == ["east", "mid", "sidewalk", "west"]
    assert bundle["connections"] == [
        {"dir": "s", "from": "mid", "fromLane": "0", "to": "east", "toLane": "0"},
        {"dir": "s", "from": "west", "fromLane": "0", "to": "mid", "toLane": "0"},
    ]
    assert bundle["summary"] == {
        "edge_count": 4,
        "junction_count": 4,
        "connection_count": 2,
        "missing_reference_count": 0,
    }
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest tests/test_road_connectivity_teacher_model.py::test_canonical_road_connectivity_bundle_extracts_edge_chain_and_connections -q
```

Expected: fail because `road_connectivity_teacher_model.py` does not exist.

- [ ] **Step 3: Implement the minimal extractor**

Create `plugins/torii-sumo/src/torii_sumo/core/road_connectivity_teacher_model.py` with:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


def canonical_road_connectivity_bundle(
    net_file: Path,
    *,
    seed_edge_ids: list[str],
    hop_radius: int = 1,
) -> dict[str, Any]:
    root = ET.parse(net_file).getroot()
    edges = {edge.attrib["id"]: edge for edge in root.findall("edge") if edge.attrib.get("id")}
    selected = {edge_id for edge_id in seed_edge_ids if edge_id in edges and not edge_id.startswith(":")}
    for _ in range(max(0, hop_radius)):
        endpoints = {
            value
            for edge_id in selected
            for value in (edges[edge_id].attrib.get("from", ""), edges[edge_id].attrib.get("to", ""))
            if value
        }
        selected.update(
            edge_id
            for edge_id, edge in edges.items()
            if not edge_id.startswith(":")
            and (edge.attrib.get("from", "") in endpoints or edge.attrib.get("to", "") in endpoints)
        )

    selected_junction_ids = {
        value
        for edge_id in selected
        for value in (edges[edge_id].attrib.get("from", ""), edges[edge_id].attrib.get("to", ""))
        if value
    }
    junctions = {junction.attrib["id"]: junction for junction in root.findall("junction") if junction.attrib.get("id")}
    connections = [
        _sorted_attrs(connection)
        for connection in root.findall("connection")
        if connection.attrib.get("from", "") in selected and connection.attrib.get("to", "") in selected
    ]
    bundle = {
        "net": _sorted_attrs(root),
        "edges": [_canonical_edge_record(edges[edge_id]) for edge_id in sorted(selected)],
        "junctions": [_canonical_junction_record(junctions[junction_id]) for junction_id in sorted(selected_junction_ids) if junction_id in junctions],
        "connections": sorted(connections, key=lambda item: (item.get("from", ""), item.get("to", ""), item.get("fromLane", ""), item.get("toLane", ""))),
    }
    missing = _missing_reference_count(bundle)
    bundle["summary"] = {
        "edge_count": len(bundle["edges"]),
        "junction_count": len(bundle["junctions"]),
        "connection_count": len(bundle["connections"]),
        "missing_reference_count": missing,
    }
    return bundle


def _canonical_edge_record(edge: ET.Element) -> dict[str, Any]:
    return {**_sorted_attrs(edge), "lanes": [_sorted_attrs(lane) for lane in edge.findall("lane")]}


def _canonical_junction_record(junction: ET.Element) -> dict[str, str]:
    return _sorted_attrs(junction)


def _sorted_attrs(element: ET.Element) -> dict[str, str]:
    return dict(sorted(element.attrib.items()))


def _missing_reference_count(bundle: dict[str, Any]) -> int:
    edge_ids = {edge["id"] for edge in bundle["edges"]}
    lane_ids = {lane["id"] for edge in bundle["edges"] for lane in edge.get("lanes", [])}
    junction_ids = {junction["id"] for junction in bundle["junctions"]}
    missing = 0
    for edge in bundle["edges"]:
        missing += int(edge.get("from", "") not in junction_ids)
        missing += int(edge.get("to", "") not in junction_ids)
    for junction in bundle["junctions"]:
        missing += sum(1 for lane_id in str(junction.get("incLanes", "")).split() if lane_id not in lane_ids)
        missing += sum(1 for lane_id in str(junction.get("intLanes", "")).split() if lane_id not in lane_ids)
    for connection in bundle["connections"]:
        missing += int(connection.get("from", "") not in edge_ids)
        missing += int(connection.get("to", "") not in edge_ids)
    return missing
```

- [ ] **Step 4: Run the focused test**

Run the same pytest command as Step 2.

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/road_connectivity_teacher_model.py tests/test_road_connectivity_teacher_model.py
git commit -m "feat: extract TUM road connectivity bundle"
```

## Task 2: Add A Loadable Road Self-Replay Writer

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/road_connectivity_teacher_model.py`
- Modify: `tests/test_road_connectivity_teacher_model.py`

- [ ] **Step 1: Write the failing writer test**

Add:

```python
def test_write_road_connectivity_self_replay_net_round_trips_bundle(tmp_path: Path) -> None:
    teacher = tmp_path / "teacher.net.xml"
    replay = tmp_path / "replay.net.xml"
    teacher.write_text(
        """<net version="1.20" junctionCornerDetail="5">
  <edge id="a" from="n1" to="n2"><lane id="a_0" index="0" allow="passenger" speed="13.89" length="10" shape="0,0 10,0"/></edge>
  <edge id="b" from="n2" to="n3"><lane id="b_0" index="0" allow="passenger" speed="13.89" length="10" shape="10,0 20,0"/></edge>
  <junction id="n1" type="dead_end" x="0" y="0" incLanes="" intLanes=""/>
  <junction id="n2" type="priority" x="10" y="0" incLanes="a_0" intLanes=""/>
  <junction id="n3" type="dead_end" x="20" y="0" incLanes="b_0" intLanes=""/>
  <connection from="a" to="b" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )

    report = write_road_connectivity_self_replay_net(teacher, ["a"], replay, hop_radius=1)

    assert report["status"] == "pass"
    assert replay.exists()
    assert canonical_road_connectivity_bundle(teacher, seed_edge_ids=["a"], hop_radius=1) == canonical_road_connectivity_bundle(replay, seed_edge_ids=["a"], hop_radius=1)
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest tests/test_road_connectivity_teacher_model.py::test_write_road_connectivity_self_replay_net_round_trips_bundle -q
```

Expected: fail because `write_road_connectivity_self_replay_net` is not defined.

- [ ] **Step 3: Implement the writer**

Add `write_road_connectivity_self_replay_net(teacher_net_file: Path, seed_edge_ids: list[str], output_file: Path, *, hop_radius: int = 1) -> dict[str, Any]`.

Implementation rules:

- Use `canonical_road_connectivity_bundle`.
- Write `<net>`, `edge`, `lane`, `junction`, and `connection`.
- Preserve root `<net>` attrs.
- Return `status="pass"` only when replay bundle equals teacher bundle.

- [ ] **Step 4: Run the focused test**

Run the same pytest command as Step 2.

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/road_connectivity_teacher_model.py tests/test_road_connectivity_teacher_model.py
git commit -m "feat: write TUM road connectivity replay net"
```

## Task 3: Run One Real TUM Road Corridor Probe

**Files:**
- Artifact only: `E:/torii_sumo_runs/tum_road_connectivity_replay_20260701/`

- [ ] **Step 1: Extract and replay one corridor around `7616444534`**

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'
@'
from pathlib import Path
from torii_sumo.core.road_connectivity_teacher_model import write_road_connectivity_self_replay_net

teacher = Path("examples/02_one_prompt_osm_network/networks/tum_ingolstadt_center_reference.net.xml")
out = Path("E:/torii_sumo_runs/tum_road_connectivity_replay_20260701/7616444534_road_replay.net.xml")
report = write_road_connectivity_self_replay_net(
    teacher,
    ["204388143", "-204388143", "33102477", "-33102477"],
    out,
    hop_radius=1,
)
print(report)
'@ | python -
```

Expected: `status` is `pass`.

- [ ] **Step 2: SUMO-load the replay**

Run:

```powershell
sumo -n E:/torii_sumo_runs/tum_road_connectivity_replay_20260701/7616444534_road_replay.net.xml --no-step-log true --duration-log.disable true --quit-on-end true -W
```

Expected: exit code `0`.

- [ ] **Step 3: Write the artifact report**

Write `E:/torii_sumo_runs/tum_road_connectivity_replay_20260701/road_connectivity_review.md` with:

```markdown
# TUM Road Connectivity Replay Review

seed_edges:
- 204388143
- -204388143
- 33102477
- -33102477

automated_result:
- canonical_bundle_parity: pass
- sumo_load: pass

manual_review_status: pending NetEdit inspection
claim_status: diagnostic-demo
```

- [ ] **Step 4: Commit only code if changed**

Do not commit E: artifacts.

## Final Verification

Run:

```powershell
$env:PYTHONPATH='plugins/torii-sumo/src'; python -m pytest tests/test_road_connectivity_teacher_model.py tests/test_junction_teacher_model.py -q
git status --short
```

Expected:

- focused tests pass.
- road replay artifacts remain outside git.
- `AGENTS.md` remains untracked.
- only intentional source/test changes are committed.

## Claim Boundary

After this plan, the strongest allowed claim is:

```text
Torii has a diagnostic TUM road-connectivity replay layer that is separate from
junction-internal replay.
```

Do not claim full TUM-like OSM-to-SUMO generation until both road and junction
layers pass on OSM-derived candidates.

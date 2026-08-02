# Ingolstadt Citywide NetEdit Visual Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the verified Ingolstadt junction into a resumable citywide run in which every applicable motor junction and incoming lane is mapped, checked in real NetEdit Connection mode, structurally verified, and bound to global SUMO load and routeability evidence.

**Architecture:** Keep the existing one-junction gate as the comparison primitive. Extend it with compact semantic masks and one NetEdit launch per network per tile, then add one thin city runner that inventories, maps, tiles, resumes, and summarizes. Reuse the current OSM workflow, hash helpers, SUMO command runner, and closed-loop acceptance gate; do not add dependencies or a second network builder.

**Tech Stack:** Python 3.13, ElementTree, Pillow, existing Torii `NeteditTargetSession`, atomic JSON/hash helpers, Eclipse SUMO/NetEdit CLI, pytest, Ruff, PowerShell 7.

---

### Task 1: Full-city inventory and source ledger

**Files:**
- Create: `plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py`
- Create: `tests/test_ingolstadt_citywide_visual_gate_script.py`

- [ ] **Step 1: Write the failing inventory check**

Load the script with `importlib.util.spec_from_file_location`, write two tiny SUMO networks, and assert that pedestrian-only junctions are excluded while a motor junction is assigned to a deterministic 250 m tile:

```python
def test_inventory_uses_projected_coordinates_and_motor_scope(tmp_path: Path) -> None:
    net = tmp_path / "city.net.xml"
    _write_net(net, offset="-1000,-2000", junction_x=20, junction_y=30)

    inventory = MODULE.read_network_inventory(net, tile_size_m=250.0)

    assert inventory["net_sha256"] == file_sha256(net)
    assert inventory["applicable_junction_count"] == 1
    junction = inventory["junctions"][0]
    assert junction["id"] == "j0"
    assert junction["projected_center"] == [1020.0, 2030.0]
    assert junction["tile_id"] == "0004_0008"
    assert junction["motor_incoming_lanes"] == ["in_0"]
    assert junction["motor_outgoing_lanes"] == ["out_0"]
```

The fixture contains `j0` with passenger `in_0`/`out_0` and `walk` with lanes that set `allow="pedestrian"`.

- [ ] **Step 2: Run the check and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ingolstadt_citywide_visual_gate_script.py::test_inventory_uses_projected_coordinates_and_motor_scope -q
```

Expected: collection fails because `run_ingolstadt_citywide_visual_gate.py` does not exist.

- [ ] **Step 3: Add the minimum inventory implementation**

The script defines these stable helpers and no new class hierarchy:

```python
OFFICIAL_TEACHER_SHA256 = "bbfef2f8afb66f29486395189fa7136e3fa7cce2b192afcbd50a6f1d9239a806"
OFFICIAL_CONV_BOUNDARY = (1243.52, 0.0, 11284.52, 10137.01)


def lane_allows_motor(lane: ET.Element) -> bool:
    allow = set(lane.get("allow", "").split())
    disallow = set(lane.get("disallow", "").split())
    return "passenger" not in disallow and (not allow or "passenger" in allow)


def tile_id(point: tuple[float, float], tile_size_m: float) -> str:
    if tile_size_m <= 0:
        raise ValueError("tile_size_m must be positive")
    return f"{math.floor(point[0] / tile_size_m):04d}_{math.floor(point[1] / tile_size_m):04d}"


def read_network_inventory(
    path: Path, *, tile_size_m: float,
    scope_projected_boundary: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    source = path.resolve(strict=True)
    root = ET.parse(source).getroot()
    location = root.find("location")
    if location is None:
        raise ValueError(f"network has no location: {source}")
    offset_x, offset_y = (float(value) for value in location.get("netOffset", "").split(","))
    lanes = {lane.get("id", ""): lane for lane in root.iter("lane")}
    outgoing: dict[str, set[str]] = collections.defaultdict(set)
    for connection in root.findall("connection"):
        if connection.get("from") and connection.get("to"):
            outgoing[connection.get("from", "")].add(connection.get("to", ""))
    edge_lanes = {
        edge.get("id", ""): [lane.get("id", "") for lane in edge.findall("lane")]
        for edge in root.findall("edge")
        if edge.get("function") != "internal"
    }
    rows = []
    for junction in root.findall("junction"):
        junction_id = junction.get("id", "")
        if not junction_id or junction_id.startswith(":") or junction.get("type") == "internal":
            continue
        incoming = sorted(
            lane_id for lane_id in junction.get("incLanes", "").split()
            if lane_id in lanes and lane_allows_motor(lanes[lane_id])
        )
        incoming_edges = {lane_id.rsplit("_", 1)[0] for lane_id in incoming}
        outgoing_lanes = sorted({
            lane_id
            for edge_id in incoming_edges
            for target_edge in outgoing.get(edge_id, ())
            for lane_id in edge_lanes.get(target_edge, ())
            if lane_id in lanes and lane_allows_motor(lanes[lane_id])
        })
        if not incoming or not outgoing_lanes:
            continue
        local = float(junction.get("x", "nan")), float(junction.get("y", "nan"))
        projected = local[0] - offset_x, local[1] - offset_y
        if scope_projected_boundary is not None:
            x0, y0, x1, y1 = scope_projected_boundary
            if not (x0 <= projected[0] <= x1 and y0 <= projected[1] <= y1):
                continue
        rows.append({
            "id": junction_id,
            "projected_center": [round(projected[0], 6), round(projected[1], 6)],
            "tile_id": tile_id(projected, tile_size_m),
            "motor_incoming_lanes": incoming,
            "motor_outgoing_lanes": outgoing_lanes,
            "motor_incoming_edges": sorted(incoming_edges),
            "motor_outgoing_edges": sorted({lane_id.rsplit("_", 1)[0] for lane_id in outgoing_lanes}),
        })
    return {
        "net_file": str(source),
        "net_sha256": file_sha256(source),
        "tile_size_m": tile_size_m,
        "applicable_junction_count": len(rows),
        "junctions": sorted(rows, key=lambda row: row["id"]),
}
```

For the official teacher, require both `OFFICIAL_TEACHER_SHA256` and `OFFICIAL_CONV_BOUNDARY`. Convert its local boundary to one projected scope and pass that same scope to both inventories. Candidate junctions whose centers lie outside this scope do not enter the denominator; this permits complete OSM ways to extend beyond the acquisition boundary without redefining “full city.”

Use `write_json_atomic` for `source-ledger.json` and `city-manifest.json`. The ledger records teacher/candidate/OSM hashes, current git commit, `sumo --version`, `netedit --version`, projected scope, tile size, mapping distance, zoom, and window size.

- [ ] **Step 4: Run the inventory check and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ingolstadt_citywide_visual_gate_script.py -q
git add plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py tests/test_ingolstadt_citywide_visual_gate_script.py
git commit -m "feat: inventory Ingolstadt citywide junctions"
```

Expected: the new check passes and the commit contains only the runner and its check.

### Task 2: Deterministic junction and lane registration

**Files:**
- Modify: `plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py`
- Modify: `tests/test_ingolstadt_citywide_visual_gate_script.py`

- [ ] **Step 1: Write failing exact, compound, and ambiguous mapping checks**

```python
def test_registration_prefers_source_identity_then_direction() -> None:
    teacher = _junction("cluster_10_11", (1000, 2000), roads=("10", "20"), bearings=(0, 180))
    exact = _junction("cluster_10_11", (1001, 2000), roads=("10", "20"), bearings=(1, 181))
    nearby = _junction("other", (1000, 2000), roads=("30",), bearings=(90,))
    report = MODULE.register_junctions([teacher], [nearby, exact], max_distance_m=10)
    assert report["matched"][0]["candidate_ids"] == ["cluster_10_11"]
    assert report["ambiguous"] == []


def test_registration_does_not_auto_accept_tied_candidates() -> None:
    teacher = _junction("t", (1000, 2000), roads=("10",), bearings=(0,))
    candidates = [
        _junction("a", (999, 2000), roads=("10",), bearings=(0,)),
        _junction("b", (1001, 2000), roads=("10",), bearings=(0,)),
    ]
    report = MODULE.register_junctions([teacher], candidates, max_distance_m=10)
    assert report["matched"] == []
    assert report["ambiguous"][0]["teacher_id"] == "t"
```

Add a lane check that accepts only one candidate with the same normalized road root, motor permission, and closest approach bearing; a tie must be `review_required`.

- [ ] **Step 2: Run the checks and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ingolstadt_citywide_visual_gate_script.py -q
```

Expected: fails because `register_junctions` and `register_lanes` are absent.

- [ ] **Step 3: Implement fail-closed registration**

Add road lineage and bearing to each inventory row. Normalize edge IDs without inventing a map service:

```python
def road_root(edge_id: str) -> str:
    return edge_id.lstrip("-").split("#", 1)[0]


def source_ids(junction_id: str) -> frozenset[str]:
    value = junction_id.removeprefix("cluster_")
    return frozenset(part for part in value.split("_") if part.isdigit())


def angle_gap(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)
```

`register_junctions` considers only candidates within `max_distance_m`. It ranks a candidate by `(source identity overlap, road-root overlap, matched approach bearings, negative distance)`. It accepts only one best candidate and rejects a numerical tie. It also reports `teacher_only`, `candidate_only`, and `ambiguous`; none may be omitted from the city manifest. `register_lanes` applies the same one-to-one rule to incoming motor lanes and records both directions.

- [ ] **Step 4: Run, lint, and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ingolstadt_citywide_visual_gate_script.py -q
.\.venv\Scripts\python.exe -m ruff check plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py tests/test_ingolstadt_citywide_visual_gate_script.py
git add plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py tests/test_ingolstadt_citywide_visual_gate_script.py
git commit -m "feat: register citywide teacher junctions"
```

Expected: tests and Ruff pass.

### Task 3: Compact semantic masks

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/netedit_connection_visual_gate.py:147-178`
- Modify: `tests/test_netedit_connection_visual_gate.py`

- [ ] **Step 1: Write the failing mask check**

```python
def test_semantic_mask_keeps_palette_and_angular_evidence(tmp_path: Path) -> None:
    image = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.line((50, 90, 50, 50), fill=(0, 255, 255), width=4)
    draw.line((50, 50, 90, 50), fill=(0, 255, 0), width=4)
    source = tmp_path / "source.png"
    mask = tmp_path / "mask.png"
    image.save(source)

    report = write_semantic_mask(source, mask, center=(50, 50))

    assert report["layers"]["source"]["pixel_count"] > 0
    assert report["layers"]["target"]["angular_bins"] == [0]
    assert report["sha256"] == file_sha256(mask)
    assert Image.open(mask).mode == "P"
```

- [ ] **Step 2: Run the check and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_netedit_connection_visual_gate.py::test_semantic_mask_keeps_palette_and_angular_evidence -q
```

Expected: fails because `write_semantic_mask` is absent.

- [ ] **Step 3: Implement the four-layer indexed mask**

Use Pillow only. Palette index `0` is background; `1..4` follow `_PALETTE`. For each matching pixel, record count, bounding box, eight 45-degree angular bins relative to the junction center, and connected-component count using a small `collections.deque` flood fill. Save the `P` image and return its SHA-256.

```python
def write_semantic_mask(source: Path, destination: Path, *, center: tuple[int, int]) -> dict[str, Any]:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
    mask = Image.new("P", image.size, 0)
    mask.putpalette([0, 0, 0, *sum((_PALETTE[name] for name in _PALETTE), ())])
    output = mask.load()
    pixels = image.load()
    stats: dict[str, Any] = {}
    for index, (name, color) in enumerate(_PALETTE.items(), 1):
        points = []
        for y in range(image.height):
            for x in range(image.width):
                if max(abs(pixels[x, y][channel] - color[channel]) for channel in range(3)) <= 12:
                    output[x, y] = index
                    points.append((x, y))
        bins = sorted({int((math.degrees(math.atan2(center[1] - y, x - center[0])) % 360) // 45) for x, y in points})
        stats[name] = {
            "pixel_count": len(points),
            "bbox": list(Image.new("1", image.size).getbbox() or ()) if not points else [
                min(x for x, _ in points), min(y for _, y in points),
                max(x for x, _ in points) + 1, max(y for _, y in points) + 1,
            ],
            "angular_bins": bins,
            "component_count": _component_count(set(points)),
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    mask.save(destination)
    return {"file": str(destination), "sha256": file_sha256(destination), "layers": stats}


def _component_count(points: set[tuple[int, int]]) -> int:
    remaining = set(points)
    count = 0
    while remaining:
        count += 1
        queue = collections.deque([remaining.pop()])
        while queue:
            x, y = queue.popleft()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
    return count
```

Update `analyze_connection_pair` to compare these statistics as well as pixel ratios. A teacher angular bin missing in the candidate is `<layer>_direction_missing`; a component-count difference greater than one is `<layer>_component_mismatch`. Keep the current geometry tolerance and current status precedence.

- [ ] **Step 4: Run and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_netedit_connection_visual_gate.py -q
git add plugins/torii-sumo/src/torii_sumo/core/netedit_connection_visual_gate.py tests/test_netedit_connection_visual_gate.py
git commit -m "feat: retain compact NetEdit semantic masks"
```

Expected: all visual-gate checks pass.

### Task 4: One NetEdit launch per tile and network

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/netedit_connection_visual_gate.py:199-249`
- Modify: `tests/test_netedit_connection_visual_gate.py`

- [ ] **Step 1: Write the failing session-reuse check**

```python
def test_tile_capture_opens_once_and_clicks_every_lane(tmp_path: Path) -> None:
    session = FakeSession(tmp_path)
    captures = capture_connection_tile(
        session=session,
        specs=[_capture_spec("a_0", (0, 0)), _capture_spec("b_0", (10, 0))],
        viewport_center=(0.0, 0.0),
        zoom=2500,
        destination=tmp_path / "captures",
        canvas_rect=(0, 0, 800, 600),
    )
    assert session.open_count == 1
    assert [action["type"] for action in session.actions] == ["key", "click", "click"]
    assert len(captures) == 2
    assert session.abort_reason == "visual_tile_capture_complete"
```

- [ ] **Step 2: Run the check and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_netedit_connection_visual_gate.py::test_tile_capture_opens_once_and_clicks_every_lane -q
```

Expected: fails because the current `_capture` opens one session per lane.

- [ ] **Step 3: Add the tile capture primitive**

`capture_connection_tile` opens once, observes a stable frame, sends `C` once, then clicks every lane with the exact previous screenshot hash. It copies each selected screenshot before the next click and aborts in `finally`. The viewport center is the tile center converted from projected coordinates through each network's `netOffset`; this keeps the teacher and candidate at the same physical location.

```python
def capture_connection_tile(
    *, session: Any, specs: Sequence[dict[str, Any]], viewport_center: tuple[float, float],
    zoom: float, destination: Path, canvas_rect: tuple[int, int, int, int] | None = None,
) -> list[dict[str, Any]]:
    session.open()
    results = []
    try:
        latest = session.observe("pre_connection_stable")
        latest = session.act({
            "type": "key", "virtual_key": ord("C"),
            "expected_screenshot_sha256": latest["screenshot_sha256"],
        })
        canvas = canvas_rect or netedit_canvas_rect(session.hwnd)
        destination.mkdir(parents=True, exist_ok=True)
        for index, spec in enumerate(specs, 1):
            click = canvas_click_for_world_point(
                point=point_before_lane_end(spec["shape"]), center=viewport_center,
                conv_boundary=spec["conv_boundary"], canvas_rect=canvas, zoom=zoom,
            )
            latest = session.act({
                "type": "click", "x": click[0], "y": click[1],
                "expected_screenshot_sha256": latest["screenshot_sha256"],
            })
            image = destination / f"{index:05d}-{spec['lane_id']}.png"
            shutil.copy2(latest["screenshot_file"], image)
            results.append({
                "lane_id": spec["lane_id"], "click": list(click),
                "screenshot_file": str(image), "screenshot_sha256": file_sha256(image),
            })
        return results
    finally:
        session.abort("visual_tile_capture_complete")
```

Keep `_capture` as a one-item wrapper so the existing CLI and accepted single-junction regression remain unchanged. Add an optional `session_factory=NeteditTargetSession` only at this boundary so the check can supply `FakeSession`.

- [ ] **Step 4: Run related checks and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_netedit_connection_visual_gate.py tests/test_netedit_cli.py -q
git add plugins/torii-sumo/src/torii_sumo/core/netedit_connection_visual_gate.py tests/test_netedit_connection_visual_gate.py
git commit -m "perf: reuse NetEdit sessions within city tiles"
```

Expected: all checks pass; the one-junction public function retains its current result schema.

### Task 5: Resumable tile execution and strict evidence retention

**Files:**
- Modify: `plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py`
- Modify: `tests/test_ingolstadt_citywide_visual_gate_script.py`

- [ ] **Step 1: Write failing resume and invalidation checks**

```python
def test_resume_skips_hash_matching_pass_and_invalidates_changed_candidate(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    MODULE.write_tile_state(state, candidate_sha="a" * 64, completed=["j0/in_0"])
    assert MODULE.pending_items(state, candidate_sha="a" * 64, items=["j0/in_0", "j1/in_0"]) == ["j1/in_0"]
    assert MODULE.pending_items(state, candidate_sha="b" * 64, items=["j0/in_0", "j1/in_0"]) == ["j0/in_0", "j1/in_0"]


def test_city_completion_fails_on_any_unmapped_or_nonpass_item() -> None:
    report = MODULE.city_completion(
        teacher_count=2,
        candidate_count=2,
        matched_count=1,
        teacher_only=["t1"],
        candidate_only=["c1"],
        ambiguous=[],
        lane_statuses=["pass", "fail"],
        structure_statuses=["pass"],
        global_load="pass",
        global_routeability="pass",
    )
    assert report["status"] == "fail"
    assert report["automatic_promotion_gate"] == "blocked"


def test_structure_pair_detects_missing_target_and_signal_binding(tmp_path: Path) -> None:
    teacher = _connection_net(tmp_path / "teacher.net.xml", target="out", tl="tls", link_index="3")
    candidate = _connection_net(tmp_path / "candidate.net.xml", target="wrong", tl="", link_index="")
    report = MODULE.compare_lane_structure(
        teacher, candidate, teacher_lane="in_0", candidate_lane="in_0",
        outgoing_lane_pairs={"out_0": "out_0"},
    )
    assert report["status"] == "fail"
    assert "target_lane_mismatch" in report["reasons"]
    assert "signal_binding_mismatch" in report["reasons"]
```

- [ ] **Step 2: Run the checks and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ingolstadt_citywide_visual_gate_script.py -q
```

Expected: fails because tile state and completion helpers are absent.

- [ ] **Step 3: Implement atomic tile state and the CLI phases**

Add CLI arguments:

```python
parser.add_argument("--teacher-net", type=Path, required=True)
parser.add_argument("--candidate-net", type=Path, required=True)
parser.add_argument("--source-osm", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
parser.add_argument("--seed-junction", default="cluster_2230504019_376231769")
parser.add_argument("--phase", choices=("inventory", "visual", "global", "all"), default="all")
parser.add_argument("--tile-size-m", type=float, default=250.0)
parser.add_argument("--junction-distance-m", type=float, default=10.0)
parser.add_argument("--zoom", type=float, default=2500.0)
parser.add_argument("--window-size", default="1400,1000")
parser.add_argument("--resume", action="store_true")
```

Write tile state and completion with these fail-closed rules:

```python
def write_tile_state(path: Path, *, candidate_sha: str, completed: list[str]) -> None:
    write_json_atomic(path, {
        "schema": "torii.ingolstadt-citywide-tile/v1",
        "candidate_sha256": candidate_sha,
        "completed": sorted(set(completed)),
    }, sort_keys=True)


def pending_items(path: Path, *, candidate_sha: str, items: list[str]) -> list[str]:
    if not path.is_file():
        return items
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("candidate_sha256") != candidate_sha:
        return items
    completed = set(state.get("completed", []))
    return [item for item in items if item not in completed]


def city_completion(
    *, teacher_count: int, candidate_count: int, matched_count: int,
    teacher_only: Sequence[str], candidate_only: Sequence[str], ambiguous: Sequence[Any],
    lane_statuses: Sequence[str], structure_statuses: Sequence[str],
    global_load: str, global_routeability: str,
) -> dict[str, Any]:
    failures = (
        list(teacher_only) or list(candidate_only) or list(ambiguous)
        or matched_count != teacher_count or matched_count != candidate_count
        or any(status != "pass" for status in lane_statuses)
        or any(status != "pass" for status in structure_statuses)
        or global_load != "pass" or global_routeability != "pass"
    )
    status = "fail" if failures else "pass"
    return {"status": status, "automatic_promotion_gate": "pass" if status == "pass" else "blocked"}
```

`compare_lane_structure` resolves every mapped incoming lane to its `<connection>` rows and outgoing lane IDs. It compares the mapped target set plus each row's `dir`, `via` presence, passenger permission, `tl` presence, and `linkIndex` presence. Numeric `linkIndex` values may differ after reconstruction, but the order of controlled movements within the mapped incoming lane must match. Missing targets, different direction, lost `via`, permission differences, or controlled/uncontrolled differences are failures. Persist this report beside the visual mask; visual `pass` never overrides it.

```python
def connection_signature(root: ET.Element, lane_id: str) -> list[dict[str, Any]]:
    edge_id, lane_index = lane_id.rsplit("_", 1)
    edges = {edge.get("id", ""): edge for edge in root.findall("edge")}
    signature = []
    for row in root.findall("connection"):
        if row.get("from") != edge_id or row.get("fromLane") != lane_index:
            continue
        target_edge = row.get("to", "")
        target_lane = f"{target_edge}_{row.get('toLane', '')}"
        lane = next((item for item in edges.get(target_edge, ()).findall("lane") if item.get("id") == target_lane), None) if target_edge in edges else None
        signature.append({
            "target_lane": target_lane,
            "dir": row.get("dir", ""),
            "has_via": bool(row.get("via")),
            "motor": lane is not None and lane_allows_motor(lane),
            "controlled": bool(row.get("tl")) and row.get("linkIndex", "").isdigit(),
            "link_index": int(row["linkIndex"]) if row.get("linkIndex", "").isdigit() else None,
        })
    return sorted(signature, key=lambda item: (item["link_index"] is None, item["link_index"], item["target_lane"]))
```

Order tiles by Manhattan distance from the seed tile. After every lane, write `tiles/<tile-id>/state.json` atomically. A passing lane keeps `lane-<id>.mask.png` and compact JSON. A failed, uncertain, or blocked lane also keeps teacher, candidate, and comparison PNGs. Passing full screenshots remain under `tiles/<tile-id>/.session/` and are removed only after both masks and the updated state have been written and hashed.

The command exits `0` only for a complete pass, `2` for fail/review, and `3` for blocked. `--phase inventory` exits `2` while visual/global work remains; this prevents an inventory-only run from appearing complete.

- [ ] **Step 4: Run and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ingolstadt_citywide_visual_gate_script.py tests/test_netedit_connection_visual_gate.py -q
.\.venv\Scripts\python.exe -m ruff check plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py tests/test_ingolstadt_citywide_visual_gate_script.py
git add plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py tests/test_ingolstadt_citywide_visual_gate_script.py
git commit -m "feat: resume citywide NetEdit visual checks"
```

Expected: tests and Ruff pass.

### Task 6: Bind city completion into the TUM-style loop

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/tum_style_closed_loop.py:68-131`
- Modify: `tests/test_tum_style_closed_loop.py`

- [ ] **Step 1: Write the failing strict city-report check**

```python
def test_citywide_acceptance_requires_exact_candidate_hash_and_all_gates(tmp_path: Path) -> None:
    audit = _passing_audit()
    audit["citywide_gate"] = {
        "status": "pass",
        "candidate_sha256": "0" * 64,
        "unmapped_teacher_count": 0,
        "unmapped_candidate_count": 0,
        "ambiguous_count": 0,
        "failed_lane_count": 0,
        "global_load_status": "pass",
        "global_routeability_status": "pass",
    }
    with pytest.raises(ValueError, match="citywide gate candidate hash"):
        complete_tum_style_iteration(
            state_file=state_file,
            iteration_id="0001",
            after_net_file=after,
            action={"kind": "connection", "count": 1},
            audit=audit,
            mcp_evidence={},
            decision="accepted",
        )
```

- [ ] **Step 2: Run the check and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_tum_style_closed_loop.py::test_citywide_acceptance_requires_exact_candidate_hash_and_all_gates -q
```

Expected: the loop does not yet validate `citywide_gate`.

- [ ] **Step 3: Add one fail-closed validation branch**

When `audit` contains `citywide_gate`, require its status to be `pass`, candidate hash to equal the exact `after.net.xml` hash, all missing/ambiguous/failed counts to be zero, and both global statuses to be `pass`. Do not require `citywide_gate` for old single-junction runs; this preserves the accepted iteration-18 regression while preventing a citywide claim from bypassing the city report.

- [ ] **Step 4: Run and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_tum_style_closed_loop.py tests/test_netedit_connection_visual_gate.py -q
git add plugins/torii-sumo/src/torii_sumo/core/tum_style_closed_loop.py tests/test_tum_style_closed_loop.py
git commit -m "fix: bind citywide evidence to TUM acceptance"
```

Expected: all checks pass.

### Task 7: Global SUMO load and stratified OD gate

**Files:**
- Modify: `plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py`
- Modify: `tests/test_ingolstadt_citywide_visual_gate_script.py`

- [ ] **Step 1: Write failing OD coverage and result checks**

```python
def test_od_plan_covers_tiles_neighbors_and_city_extremes() -> None:
    plan = MODULE.build_stratified_od_plan(_four_tile_inventory(), seed=20260802)
    kinds = {row["kind"] for row in plan}
    assert {"within_tile", "adjacent_tiles", "edge_to_center"} <= kinds
    assert {row["origin_tile"] for row in plan if row["kind"] == "within_tile"} == {"0_0", "0_1", "1_0", "1_1"}


def test_global_result_rejects_missing_route_teleport_or_collision() -> None:
    report = MODULE.summarize_global_run(
        requested=20, routed=19, arrived=19, teleports=1, collisions=0, returncode=0
    )
    assert report["status"] == "fail"
```

- [ ] **Step 2: Run the checks and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ingolstadt_citywide_visual_gate_script.py -q
```

Expected: OD helpers are absent.

- [ ] **Step 3: Implement deterministic CLI execution**

Select passenger edges from each nonempty tile using `random.Random(20260802)`. Emit one within-tile pair, one pair for each adjacent nonempty tile, and edge-to-center pairs. Write `global.trips.xml`, run `duarouter --net-file <candidate> --route-files global.trips.xml --output-file global.rou.xml --ignore-errors false`, then run `sumo --net-file <candidate> --route-files global.rou.xml --tripinfo-output global.tripinfo.xml --summary-output global.summary.xml --collision.check-junctions true --duration-log.statistics true` through the existing `run_command` and `discover_binaries` helpers.

```python
def build_stratified_od_plan(inventory: Mapping[str, Any], *, seed: int) -> list[dict[str, str]]:
    rng = random.Random(seed)
    by_tile: dict[str, list[str]] = collections.defaultdict(list)
    centers: dict[str, tuple[float, float]] = {}
    for junction in inventory["junctions"]:
        tile = str(junction["tile_id"])
        centers[tile] = tuple(junction["projected_center"])
        by_tile[tile].extend(junction["motor_incoming_edges"])
        by_tile[tile].extend(junction["motor_outgoing_edges"])
    for values in by_tile.values():
        values[:] = sorted(set(values))
    rows = []
    for tile, edges in sorted(by_tile.items()):
        if len(edges) >= 2:
            origin, destination = rng.sample(edges, 2)
            rows.append({"kind": "within_tile", "origin_tile": tile, "destination_tile": tile,
                         "from": origin, "to": destination})
    for tile_a, tile_b in adjacent_tile_pairs(sorted(by_tile)):
        rows.append({"kind": "adjacent_tiles", "origin_tile": tile_a, "destination_tile": tile_b,
                     "from": rng.choice(by_tile[tile_a]), "to": rng.choice(by_tile[tile_b])})
    center_tile = min(centers, key=lambda tile: math.dist(centers[tile], _centroid(list(centers.values()))))
    for edge_tile in extreme_tiles(centers):
        rows.append({"kind": "edge_to_center", "origin_tile": edge_tile, "destination_tile": center_tile,
                     "from": rng.choice(by_tile[edge_tile]), "to": rng.choice(by_tile[center_tile])})
    return rows


def adjacent_tile_pairs(tile_ids: Sequence[str]) -> list[tuple[str, str]]:
    coordinates = {tile: tuple(int(value) for value in tile.split("_", 1)) for tile in tile_ids}
    return [
        (left, right) for index, left in enumerate(tile_ids) for right in tile_ids[index + 1:]
        if sum(abs(a - b) for a, b in zip(coordinates[left], coordinates[right])) == 1
    ]


def _centroid(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    return sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)


def extreme_tiles(centers: Mapping[str, tuple[float, float]]) -> list[str]:
    return sorted({
        min(centers, key=lambda tile: centers[tile][0]), max(centers, key=lambda tile: centers[tile][0]),
        min(centers, key=lambda tile: centers[tile][1]), max(centers, key=lambda tile: centers[tile][1]),
    })


def summarize_global_run(
    *, requested: int, routed: int, arrived: int, teleports: int, collisions: int, returncode: int,
) -> dict[str, Any]:
    status = "pass" if (
        returncode == 0 and requested == routed == arrived and teleports == 0 and collisions == 0
    ) else "fail"
    return {
        "status": status, "requested": requested, "routed": routed, "arrived": arrived,
        "teleports": teleports, "collisions": collisions, "returncode": returncode,
    }
```

`global-load.json` records a separate `sumo --net-file <candidate> --begin 0 --end 1 --no-step-log true` command. `global-routeability.json` passes only when every requested trip is routed and arrives, exit codes are zero, and teleports/collisions are zero. Bind both reports to the candidate SHA.

- [ ] **Step 4: Run and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ingolstadt_citywide_visual_gate_script.py tests/test_routeability_audit.py -q
git add plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py tests/test_ingolstadt_citywide_visual_gate_script.py
git commit -m "feat: gate citywide SUMO routeability"
```

Expected: all checks pass.

### Task 8: Build and run the real city in expanding order

**Files:**
- Produce: `outputs/ingolstadt_citywide_source/ingolstadt_24h.net.xml`
- Produce: `outputs/ingolstadt_citywide_torii/ingolstadt_corridor_teacher_run.json`
- Produce: `outputs/ingolstadt_citywide_gate/city-manifest.json`
- Produce: `outputs/ingolstadt_citywide_gate/completion.json`
- Modify only when a reproduced shared root cause requires it: the existing Torii reconstruction function reached by every failing case
- Add one regression to the existing test file nearest that shared function

- [ ] **Step 1: Acquire and verify the official teacher**

```powershell
New-Item -ItemType Directory -Force outputs/ingolstadt_citywide_source | Out-Null
Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/TUM-VT/sumo_ingolstadt/main/simulation/ingolstadt_24h.net.xml.gz' -OutFile 'outputs/ingolstadt_citywide_source/ingolstadt_24h.net.xml.gz'
.\.venv\Scripts\python.exe -c "import gzip,hashlib,pathlib; g=pathlib.Path(r'outputs/ingolstadt_citywide_source/ingolstadt_24h.net.xml.gz'); assert hashlib.sha256(g.read_bytes()).hexdigest()=='101412168ec627baa3a56d38226d8a850fee702b90437fb29546d6aadf5a86e7'; x=g.with_suffix(''); x.write_bytes(gzip.decompress(g.read_bytes())); assert hashlib.sha256(x.read_bytes()).hexdigest()=='bbfef2f8afb66f29486395189fa7136e3fa7cce2b192afcbd50a6f1d9239a806'"
```

Expected: both assertions pass and the teacher XML exists.

- [ ] **Step 2: Run Torii on the official geographic extent**

```powershell
.\.venv\Scripts\python.exe plugins/torii-sumo/scripts/run_ingolstadt_corridor_teacher.py `
  --workflow-mode reference-matched `
  --teacher-net outputs/ingolstadt_citywide_source/ingolstadt_24h.net.xml `
  --bbox '11.274814,48.715766,11.611141,48.814343' `
  --junction-id cluster_2230504019_376231769 `
  --output-dir outputs/ingolstadt_citywide_torii `
  --timeout-seconds 600 `
  --skip-runtime-audits `
  --verbose
```

Expected: `ingolstadt_corridor_teacher_run.json` binds the downloaded OSM and exposes an existing `runtime_audited_net_file`. If Overpass fails, retain the blocked report and rerun with its hash-bound `source_osm_file`; never use an unrecorded cache.

- [ ] **Step 3: Run inventory before opening NetEdit**

```powershell
$cityRun = Get-Content -Raw -Encoding UTF8 outputs/ingolstadt_citywide_torii/ingolstadt_corridor_teacher_run.json | ConvertFrom-Json
.\.venv\Scripts\python.exe plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py `
  --teacher-net outputs/ingolstadt_citywide_source/ingolstadt_24h.net.xml `
  --candidate-net $cityRun.runtime_audited_net_file `
  --source-osm $cityRun.cleanup_workflow.filtered_osm_file `
  --output-dir outputs/ingolstadt_citywide_gate `
  --seed-junction cluster_2230504019_376231769 `
  --phase inventory `
  --tile-size-m 250 `
  --junction-distance-m 10
```

Expected: `city-manifest.json` reports the exact teacher/candidate applicable counts plus every matched, teacher-only, candidate-only, and ambiguous record. The first tile contains the already verified seed junction.

- [ ] **Step 4: Run the resumable visual phase**

```powershell
.\.venv\Scripts\python.exe plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py `
  --teacher-net outputs/ingolstadt_citywide_source/ingolstadt_24h.net.xml `
  --candidate-net $cityRun.runtime_audited_net_file `
  --source-osm $cityRun.cleanup_workflow.filtered_osm_file `
  --output-dir outputs/ingolstadt_citywide_gate `
  --seed-junction cluster_2230504019_376231769 `
  --phase visual `
  --tile-size-m 250 `
  --junction-distance-m 10 `
  --zoom 2500 `
  --window-size 1400,1000 `
  --resume
```

Expected: tiles run outward from the seed. Passing lanes leave compact masks; failed/review/blocked lanes leave full paired screenshots. Interrupting and rerunning the same command skips hash-matching completed lanes.

- [ ] **Step 5: Repair only reproduced shared causes**

For each nonpass group, first verify the candidate XML, lane mapping, click point, and screenshots. Use `rg` to trace every caller of the shared reconstruction function. Add one smallest failing check using the first representative and one different affected junction, run it RED, make the smallest common fix, run it GREEN, commit it, rebuild the candidate, and rerun the failed tile plus neighbors. Never add junction-ID conditionals.

The loop stops for user review only when the same cause survives three repair rounds or the report proves a teacher/OSM time difference. Otherwise continue until all tiles pass.

- [ ] **Step 6: Run global and complete gates**

```powershell
.\.venv\Scripts\python.exe plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py `
  --teacher-net outputs/ingolstadt_citywide_source/ingolstadt_24h.net.xml `
  --candidate-net $cityRun.runtime_audited_net_file `
  --source-osm $cityRun.cleanup_workflow.filtered_osm_file `
  --output-dir outputs/ingolstadt_citywide_gate `
  --seed-junction cluster_2230504019_376231769 `
  --phase all `
  --resume
```

Expected: exit `0`; `completion.json` has no missing/ambiguous/nonpass item, both global gates pass, and every report carries the final candidate SHA.

- [ ] **Step 7: Run final verification**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_netedit_connection_visual_gate.py tests/test_netedit_connection_visual_gate_script.py tests/test_ingolstadt_citywide_visual_gate_script.py tests/test_tum_style_closed_loop.py tests/test_netedit_cli.py tests/test_routeability_audit.py -q
.\.venv\Scripts\python.exe -m ruff check plugins/torii-sumo/src/torii_sumo/core/netedit_connection_visual_gate.py plugins/torii-sumo/src/torii_sumo/core/tum_style_closed_loop.py plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py tests/test_netedit_connection_visual_gate.py tests/test_ingolstadt_citywide_visual_gate_script.py tests/test_tum_style_closed_loop.py
git diff --check
```

Expected: all targeted checks pass, Ruff passes, and `git diff --check` is silent. Run the full repository test suite afterward and report unrelated pre-existing failures separately; do not weaken city completion because of them.

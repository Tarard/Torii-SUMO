# Ingolstadt Native NetEdit Visual Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the full-network, background-click city capture path with hash-bound tile subnetworks and native NetEdit Connection-mode actions, then resume outward from the verified Ingolstadt seed until the full city passes.

**Architecture:** Keep inventory, lane registration, structural comparison, tile state, SUMO load, and routeability on the immutable full networks. Use `netconvert` only to create render-only tile subnetworks, run one native `--test-file` NetEdit process per registered lane, validate the selected source and targets against projected lane geometry, and write evidence into the existing per-tile state tree. Add a maximum tile-ring control so each outward ring can be completed and checked before the next ring starts.

**Tech Stack:** Python 3.13, pytest, Pillow, Eclipse SUMO 1.27.1 (`netconvert`, `netedit`, `sumo`, `duarouter`), Win32 `PrintWindow`, PowerShell 7, Git.

---

## File Map

- Modify `plugins/torii-sumo/src/torii_sumo/core/netedit.py`: accept a hash-bound native NetEdit test file and allow a capture-only session to skip foreground activation.
- Modify `plugins/torii-sumo/src/torii_sumo/core/netedit_connection_visual_gate.py`: calculate safe zoom, convert top-level coordinates to native canvas offsets, write test files, and validate semantic colors at expected lane geometry.
- Modify `plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py`: extract tile subnetworks, capture each registered lane with the native path, strengthen resume hashes, and bound a run by tile-ring distance.
- Modify `tests/test_netedit_cli.py`: cover native test-file command construction, immutable snapshots, and capture-only launch behavior.
- Modify `tests/test_netedit_connection_visual_gate.py`: cover geometry fitting, coordinate conversion, test-file bytes, retries, and exact semantic intersection.
- Modify `tests/test_ingolstadt_citywide_visual_gate_script.py`: cover render-only extraction, full-source structural checks, stale evidence invalidation, cleanup, and ring limits.

### Task 1: Add native test-file support to the existing NetEdit session

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/netedit.py:92-125,828-1015`
- Test: `tests/test_netedit_cli.py`

- [ ] **Step 1: Write failing command and session tests**

Add tests that require `--test-file`, a copied immutable test snapshot, and no foreground activation in capture-only mode:

```python
def test_target_session_snapshots_native_test_file_and_skips_render_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.net.xml"
    source.write_text("<net/>", encoding="utf-8")
    test_file = tmp_path / "connection.test.py"
    test_file.write_text('netedit.changeMode("connection")\n', encoding="utf-8")
    candidate = tmp_path / "working.net.xml"
    deliveries, _ = _patch_target_session_runtime(monkeypatch, candidate)
    activations: list[tuple[int, int]] = []
    monkeypatch.setattr(
        netedit,
        "_activate_target_window",
        lambda hwnd, pid: activations.append((hwnd, pid)),
    )

    session = netedit.NeteditTargetSession(
        source,
        candidate,
        tmp_path / "session",
        expected_source_sha256=netedit._file_sha256(source),
        test_file=test_file,
        activate_for_render=False,
        platform_name="win32",
        which_func=lambda _: r"C:\Program Files (x86)\Eclipse\Sumo\bin\netedit.exe",
        popen_func=lambda *args, **kwargs: _SessionProcess(),
    )
    opened = session.open()

    assert activations == []
    assert "--test-file" in session.command
    snapshot = tmp_path / "session" / "preloaded" / "test.py"
    assert session.command[session.command.index("--test-file") + 1] == str(snapshot)
    assert snapshot.read_bytes() == test_file.read_bytes()
    assert opened["capture"]["width"] == 800
    session.abort("test_complete")
    assert [item for item in deliveries if item[0] != "close"] == []
```

Also extend the existing `_build_netedit_open_command` test to assert that a supplied test file is rejected when missing and emitted after `-g` when present.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_netedit_cli.py -k "native_test_file or build_netedit_open_command" -vv
```

Expected: FAIL because `test_file` and `activate_for_render` are not accepted.

- [ ] **Step 3: Extend the command builder and session with the minimum fields**

Add `test_file` to `_build_netedit_open_command`:

```python
def _build_netedit_open_command(
    input_file: Path | str,
    *,
    netedit_binary: str,
    gui_settings_file: Path | str | None = None,
    selection_file: Path | str | None = None,
    test_file: Path | str | None = None,
    window_size: str | None = None,
    window_pos: str | None = None,
) -> list[str]:
```

Include the test file in `optional_paths` and append:

```python
if test_file is not None:
    command += ["--test-file", str(test_file)]
```

Add these constructor fields to `NeteditTargetSession`:

```python
test_file: Path | str | None = None,
activate_for_render: bool = True,
```

Resolve them in `__init__`, copy `test_file` to `preloaded/test.py`, store its SHA-256 in `preloaded_artifacts`, and pass the snapshot to `_build_netedit_open_command`. Replace the unconditional render activation block with:

```python
keyboard_layout = {"status": "not_required", "reason": "native_test_file"}
render_context: dict[str, Any] = {}
render_restore = {"restored": True, "reason": "capture_only"}
if self.activate_for_render:
    render_context = _activate_target_window(self.hwnd, self.process.pid)
    self.foreground_activation_used = True
    try:
        keyboard_layout = _ensure_english_window_layout(self.hwnd)
        self.keyboard_layout_evidence.append({"phase": "open", **keyboard_layout})
        time.sleep(self.settle_seconds)
    finally:
        render_restore = _restore_input_context(render_context)
    if not render_restore["restored"]:
        raise RuntimeError("foreground context was not restored after NetEdit initial render")
else:
    time.sleep(self.settle_seconds)
```

- [ ] **Step 4: Run the complete NetEdit session tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_netedit_cli.py -q
```

Expected: all tests in the file pass.

- [ ] **Step 5: Commit the session support**

```powershell
git add -- plugins/torii-sumo/src/torii_sumo/core/netedit.py tests/test_netedit_cli.py
git commit -m "feat: support native NetEdit capture scripts"
```

### Task 2: Add deterministic visual geometry helpers

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/core/netedit_connection_visual_gate.py:26-120,176-330`
- Test: `tests/test_netedit_connection_visual_gate.py`

- [ ] **Step 1: Write failing helper tests**

Add tests for a safe zoom, native canvas offset, exact test text, and expected-lane semantic checks:

```python
def test_native_zoom_offset_and_test_file_are_deterministic(tmp_path: Path) -> None:
    canvas = (230, 64, 1394, 885)
    zoom = visual_gate.fit_connection_zoom(
        points=((0.0, 0.0), (40.0, 0.0), (-40.0, 10.0)),
        center=(0.0, 0.0),
        conv_boundary=(0.0, 0.0, 500.0, 500.0),
        canvas_rect=canvas,
        requested_zoom=2500.0,
        margin_px=64,
    )
    assert 0 < zoom < 2500.0
    assert visual_gate.native_test_click_offset((1151, 579), canvas) == (617, 347)

    destination = tmp_path / "lane.test.py"
    visual_gate.write_native_connection_test(destination, offset=(617, 347))
    assert destination.read_text(encoding="utf-8") == (
        'netedit.changeMode("connection")\n'
        "netedit.leftClickOffset(referencePosition, netedit.positions.reference, 617, 347)\n"
    )


def test_expected_lane_semantics_rejects_sidebar_and_wrong_lane(tmp_path: Path) -> None:
    image = Image.new("RGB", (300, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 40, 150), fill=(0, 255, 255))
    draw.line((120, 90, 210, 90), fill=(0, 255, 255), width=8)
    draw.line((215, 70, 280, 70), fill=(0, 255, 0), width=8)
    source = tmp_path / "capture.png"
    image.save(source)

    passed = visual_gate.verify_expected_lane_semantics(
        source,
        canvas_rect=(50, 0, 300, 180),
        source_point=(150, 90),
        target_points=((240, 70),),
    )
    wrong = visual_gate.verify_expected_lane_semantics(
        source,
        canvas_rect=(50, 0, 300, 180),
        source_point=(150, 120),
        target_points=((240, 70),),
    )

    assert passed["status"] == "pass"
    assert wrong == {"status": "review_required", "reasons": ["registered_source_lane_not_selected"]}
```

- [ ] **Step 2: Run the focused tests and confirm failure**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_netedit_connection_visual_gate.py -k "native_zoom or expected_lane_semantics" -vv
```

Expected: FAIL because the new helpers are absent.

- [ ] **Step 3: Implement the geometry helpers without a new abstraction layer**

Add constants and helpers in the existing visual-gate module:

```python
_NATIVE_TEST_REFERENCE = (304, 168)


def fit_connection_zoom(
    *,
    points: Sequence[tuple[float, float]],
    center: tuple[float, float],
    conv_boundary: tuple[float, float, float, float],
    canvas_rect: tuple[int, int, int, int],
    requested_zoom: float,
    margin_px: int = 64,
) -> float:
    left, top, right, bottom = canvas_rect
    width, height = right - left, bottom - top
    x0, y0, x1, y1 = conv_boundary
    if not points or width <= 2 * margin_px or height <= 2 * margin_px or requested_zoom <= 0:
        raise ValueError("points, canvas, margin, and requested zoom must be usable")
    base = min(width / (x1 - x0), height / (y1 - y0)) / 100.0
    limits = [requested_zoom]
    for x, y in points:
        dx, dy = abs(x - center[0]), abs(y - center[1])
        if dx:
            limits.append((width / 2 - margin_px) / (dx * base))
        if dy:
            limits.append((height / 2 - margin_px) / (dy * base))
    zoom = min(limits)
    if not math.isfinite(zoom) or zoom <= 0:
        raise ValueError("no positive zoom fits the requested points")
    return zoom


def native_test_click_offset(
    click: tuple[int, int],
    canvas_rect: tuple[int, int, int, int],
) -> tuple[int, int]:
    return (
        click[0] - canvas_rect[0] - _NATIVE_TEST_REFERENCE[0],
        click[1] - canvas_rect[1] - _NATIVE_TEST_REFERENCE[1],
    )


def write_native_connection_test(path: Path, *, offset: tuple[int, int]) -> None:
    path.write_text(
        'netedit.changeMode("connection")\n'
        f"netedit.leftClickOffset(referencePosition, netedit.positions.reference, {offset[0]}, {offset[1]})\n",
        encoding="utf-8",
    )
```

Implement `verify_expected_lane_semantics` by cropping to `canvas_rect`, finding palette points with `_palette_points`, translating expected points into the crop, requiring at least one cyan pixel within 12 pixels of the source point, and requiring at least one target/pass/conflict palette pixel within 12 pixels of each target point. Return only `pass` or `review_required`; do not infer a structural pass from pixels.

- [ ] **Step 4: Replace the fixed semantic radius with the visible lane distance**

Extend `analyze_connection_pair` with optional `semantic_radius`. Pass it to `_point_stats`, and replace the constant `160**2` with `radius**2`. Keep the default at 160 for existing callers. Add a test using a 240-pixel junction-to-source distance that fails at 160 and passes at 280.

- [ ] **Step 5: Run all visual-gate tests**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_netedit_connection_visual_gate.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the geometry helpers**

```powershell
git add -- plugins/torii-sumo/src/torii_sumo/core/netedit_connection_visual_gate.py tests/test_netedit_connection_visual_gate.py
git commit -m "feat: derive native NetEdit visual coordinates"
```

### Task 3: Extract hash-bound render-only tile subnetworks

**Files:**
- Modify: `plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py:1-60,738-790`
- Test: `tests/test_ingolstadt_citywide_visual_gate_script.py`

- [ ] **Step 1: Write failing extraction tests**

Add a test that records the `netconvert` command and creates the requested fake subnet:

```python
def test_render_subnet_uses_common_projected_boundary_and_binds_source(tmp_path: Path) -> None:
    module = _module()
    source = tmp_path / "source.net.xml"
    _write_net(source, offset="-1000,-2000", junction_x=20, junction_y=30)
    commands: list[list[str]] = []

    def fake_run(command, *, cwd, timeout_seconds):
        commands.append(list(command))
        destination = Path(command[command.index("--output-file") + 1])
        destination.write_bytes(source.read_bytes())
        return CommandResult(
            command=command,
            cwd=str(cwd),
            status="pass",
            returncode=0,
            stdout="",
            stderr="",
        )

    report = module.build_visual_tile_subnet(
        source_net=source,
        projected_boundary=(1000.0, 2000.0, 1250.0, 2250.0),
        output_dir=tmp_path / "subnet",
        requested_junctions=("j0",),
        requested_lanes=("in_0", "out_0"),
        command_runner=fake_run,
    )

    assert report["status"] == "pass"
    assert report["source_sha256"] == file_sha256(source)
    assert report["projected_boundary"] == [1000.0, 2000.0, 1250.0, 2250.0]
    assert commands[0][commands[0].index("--keep-edges.in-boundary") + 1] == "0.000,0.000,250.000,250.000"
    assert report["verified_junctions"] == ["j0"]
    assert set(report["verified_lanes"]) == {"in_0", "out_0"}
```

Add a second test where the output omits `j0` and `out_0`; expect `status == "fail"`, `missing_requested_junctions == ["j0"]`, and `missing_requested_lanes == ["out_0"]`.

- [ ] **Step 2: Run and confirm failure**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_ingolstadt_citywide_visual_gate_script.py -k "render_subnet" -vv
```

Expected: FAIL because `build_visual_tile_subnet` is absent.

- [ ] **Step 3: Implement one extraction helper in the city script**

Implement `build_visual_tile_subnet` with `run_command`, `_location_numbers`, `file_sha256`, and `netconvert`:

```python
command = [
    "netconvert",
    "--sumo-net-file", str(source),
    "--keep-edges.in-boundary", local_boundary_text,
    "--keep-edges.postload",
    "--output-file", str(subnet),
]
```

Record the command in `netconvert.cmd.txt`. If the post-load command fails, retry once without `--keep-edges.postload` and record both attempts. Parse the result and fail unless every requested junction and every requested incoming and outgoing lane exists. Return the full source hash, projected and local boundaries, subnet hash, command attempts, requested and verified junctions, requested and verified lanes, and both missing lists.

- [ ] **Step 4: Derive one common projected buffer from requested geometry**

Add `visual_tile_projected_boundary`. Parse the requested incoming lanes and mapped outgoing lanes from both full networks, convert their shape points to projected coordinates using `netOffset`, start from the tile boundary, expand to include every point, then add a 30 m floor buffer on all sides. Add a test where an outgoing lane extends 60 m beyond the tile and assert both teacher and candidate extraction reports use the same expanded projected boundary.

- [ ] **Step 5: Run extraction and existing city-script tests**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_ingolstadt_citywide_visual_gate_script.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit render-only extraction**

```powershell
git add -- plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py tests/test_ingolstadt_citywide_visual_gate_script.py
git commit -m "feat: extract city visual tile subnetworks"
```

### Task 4: Replace tile capture with native per-lane NetEdit runs

**Files:**
- Modify: `plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py:738-790`
- Test: `tests/test_ingolstadt_citywide_visual_gate_script.py`

- [ ] **Step 1: Replace the old adapter test with a failing native-capture contract**

The new test must assert that `capture_tile_pair` receives full networks for registration, builds two subnet reports, opens only subnet paths, tries lane points in the order returned by `lane_click_points`, and returns one capture per record. Use fake extraction and session factories; assert no session source equals the full teacher or full candidate path.

Use this exact capture record shape:

```python
{
    "lane_id": "in_0",
    "sample_distance_rank": 1,
    "click": [420, 330],
    "junction_pixel": [700, 470],
    "canvas_rect": [230, 64, 1394, 885],
    "zoom": 900.0,
    "semantic_radius": 300,
    "selection": {"status": "pass", "reasons": []},
    "subnet_sha256": "d" * 64,
    "screenshot_file": str(image_file),
    "screenshot_sha256": file_sha256(image_file),
}
```

- [ ] **Step 2: Run and confirm the old full-session adapter fails the contract**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_ingolstadt_citywide_visual_gate_script.py -k "native_capture_contract" -vv
```

Expected: FAIL because `capture_tile_pair` still opens full network paths and uses background actions.

- [ ] **Step 3: Implement a warm-up plus one native process per lane**

For each role:

1. Extract its subnet using the common projected boundary.
2. Create a warm-up view and test containing only `netedit.changeMode("connection")`.
3. Open a capture-only `NeteditTargetSession`, measure `netedit_canvas_rect`, and abort it.
4. Compute the safe teacher zoom from all registered sample points; normalize candidate zoom with `normalized_viewport_zoom`.
5. For each lane point at 8 m, 4 m, and 2 m, write a two-line native test file, open a fresh capture-only session, copy the session's opening screenshot, and call `verify_expected_lane_semantics`.
6. Stop on the first verified point. Preserve all attempts only when all three fail.

The session construction must use:

```python
session = session_factory(
    subnet_file,
    attempt_dir / "working.net.xml",
    attempt_dir / "netedit-session",
    expected_source_sha256=file_sha256(subnet_file),
    gui_settings_file=view,
    test_file=test_file,
    activate_for_render=False,
    target_source_junction_ids=(junction_id,),
    target_candidate_junction_ids=(junction_id,),
    window_size=f"{window_size[0]},{window_size[1]}",
)
```

Do not call `session.act`, global input, foreground activation, or MCP.

- [ ] **Step 4: Bind the visual check to full-network structure**

Keep `evaluate_lane_pair` arguments pointed at the full teacher and candidate files. Pass the measured `canvas_rect` and `semantic_radius` into `analyze_connection_pair`. Merge each capture's `selection` result with the visual and structural results; a non-pass selection must become `review_required` even when the broad palette comparison passes.

- [ ] **Step 5: Run the two visual suites**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_netedit_connection_visual_gate.py tests/test_ingolstadt_citywide_visual_gate_script.py -q
```

Expected: both files pass.

- [ ] **Step 6: Commit the native tile adapter**

```powershell
git add -- plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py tests/test_ingolstadt_citywide_visual_gate_script.py
git commit -m "feat: capture city lanes with native NetEdit tests"
```

### Task 5: Strengthen resume evidence and enforce ring-by-ring expansion

**Files:**
- Modify: `plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py:30-48,220-250,625-736,1080-1180`
- Test: `tests/test_ingolstadt_citywide_visual_gate_script.py`

- [ ] **Step 1: Write failing resume and ring tests**

Add `CAPTURE_POLICY_VERSION = "native-test-v1"`. Write tests that save a tile with teacher, candidate, manifest, and policy hashes plus one screenshot/mask hash. Assert that an unchanged state skips capture, while changing any hash or altering the PNG returns the lane to pending.

Add an ordered-tile test with Manhattan distances 0, 1, and 2:

```python
assert module.ordered_tiles(
    manifest,
    seed_junction="seed",
    max_tile_distance=1,
) == ["0004_0008", "0004_0009", "0005_0008"]
```

- [ ] **Step 2: Run and confirm failure**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_ingolstadt_citywide_visual_gate_script.py -k "policy_hash or artifact_hash or max_tile_distance" -vv
```

Expected: FAIL because state v1 checks only the candidate hash and tile ordering has no bound.

- [ ] **Step 3: Write tile state v2 and validate every retained artifact**

Write these fields:

```python
{
    "schema": "torii.ingolstadt-citywide-tile/v2",
    "teacher_sha256": teacher_sha,
    "candidate_sha256": candidate_sha,
    "manifest_sha256": manifest_sha,
    "capture_policy_version": CAPTURE_POLICY_VERSION,
    "completed": sorted(lane_reports),
    "lane_reports": lane_reports,
}
```

Implement `evidence_artifacts_match(report)` to verify teacher/candidate screenshot hashes and teacher/candidate mask hashes. Resume only reports that pass all four state keys and artifact checks.

- [ ] **Step 4: Add the ring limit without weakening final completion**

Add CLI option:

```python
parser.add_argument("--max-tile-distance", type=int)
```

Reject negative values. Filter `ordered_tiles` by Manhattan distance from the seed. Add `covered_tile_count`, `total_tile_count`, and `coverage_status` to `visual-summary.json`. Use `coverage_status="partial"` when a limit excludes any tile, and keep `automatic_promotion_gate="blocked"` even if every selected tile passes. Only an unbounded all-tile visual run may proceed to the global phase.

- [ ] **Step 5: Preserve successful evidence and remove only session support**

Copy passing PNG and mask files into the lane evidence directory before deleting `.session`. Keep `.session` when extraction, NetEdit, selection, visual, or structural status is not `pass`. Add tests for both cleanup branches.

- [ ] **Step 6: Run all city visual tests and lint changed files**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_netedit_cli.py tests/test_netedit_connection_visual_gate.py tests/test_ingolstadt_citywide_visual_gate_script.py -q
.venv\Scripts\python.exe -m ruff check plugins/torii-sumo/src/torii_sumo/core/netedit.py plugins/torii-sumo/src/torii_sumo/core/netedit_connection_visual_gate.py plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py tests/test_netedit_cli.py tests/test_netedit_connection_visual_gate.py tests/test_ingolstadt_citywide_visual_gate_script.py
```

Expected: all selected tests and Ruff pass.

- [ ] **Step 7: Commit resume and ring control**

```powershell
git add -- plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py tests/test_ingolstadt_citywide_visual_gate_script.py
git commit -m "feat: resume hash-bound city visual rings"
```

### Task 6: Run the verified junction and expand to the full city

**Files:**
- Create runtime evidence under: `outputs/ingolstadt_citywide_native_visual_v1/`
- Update only when a real reconstruction defect is found: `plugins/torii-sumo/src/torii_sumo/core/junction_rebuild_candidate.py`
- Test only when a real reconstruction defect is found: `tests/test_junction_rebuild_candidate.py`

- [ ] **Step 1: Run the full focused regression set before GUI acceptance**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_netedit_cli.py tests/test_netedit_connection_visual_gate.py tests/test_ingolstadt_citywide_visual_gate_script.py tests/test_junction_rebuild_candidate.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Build the immutable full-city inventory**

```powershell
$teacher = 'E:\CODE\VS-Code-Backup\TUM style teach\outputs\ingolstadt_citywide_source\ingolstadt_24h.net.xml'
$candidate = 'E:\CODE\VS-Code-Backup\TUM style teach\outputs\ingolstadt_citywide_torii_context_10_cluster_182_v29_adjacent_cluster\checkpoints\ring_005d4_node2097\ring_005d4.net.xml'
$osm = 'E:\CODE\VS-Code-Backup\TUM style teach\outputs\ingolstadt_citywide_torii\reference_matched\osm\ingolstadt_same_bbox_bbox.osm.xml.gz'
$out = 'E:\CODE\VS-Code-Backup\TUM style teach\outputs\ingolstadt_citywide_native_visual_v1'
.venv\Scripts\python.exe plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py --teacher-net $teacher --candidate-net $candidate --source-osm $osm --output-dir $out --phase inventory
```

Expected: `source-ledger.json` and `city-manifest.json` are written, source hashes match, and the manifest status is `ready`.

- [ ] **Step 3: Compute the minimum ring containing junction 2097955317 and run it**

```powershell
$manifest = Get-Content -Raw -Encoding utf8 (Join-Path $out 'city-manifest.json') | ConvertFrom-Json
$seed = $manifest.junction_pairs | Where-Object teacher_id -eq 'cluster_2230504019_376231769' | Select-Object -First 1
$target = $manifest.junction_pairs | Where-Object teacher_id -eq '2097955317' | Select-Object -First 1
if (-not $seed -or -not $target) { throw 'seed or ring_005d4 target is absent from the ready city manifest' }
$sx,$sy = $seed.tile_id.Split('_') | ForEach-Object { [int]$_ }
$tx,$ty = $target.tile_id.Split('_') | ForEach-Object { [int]$_ }
$ringDistance = [Math]::Abs($tx-$sx) + [Math]::Abs($ty-$sy)
.venv\Scripts\python.exe plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py --teacher-net $teacher --candidate-net $candidate --source-osm $osm --output-dir $out --phase visual --resume --max-tile-distance $ringDistance
```

Expected: the tile containing `2097955317` passes all three registered motor incoming lane pairs, with teacher/candidate PNG files, masks, structural pass records, and no retained successful `.session` directory.

- [ ] **Step 4: Inspect the real Connection-mode A/B evidence**

Open the three comparison PNG files under the target tile's junction evidence. Confirm the cyan registered source lane and colored outgoing targets agree between TUM and Torii. Treat this as visual confirmation only; the JSON semantic and structural gates remain authoritative.

- [ ] **Step 5: Fix only proven reconstruction defects with one regression each**

When a ring fails because the full candidate structure differs from the teacher, first add one failing test in `tests/test_junction_rebuild_candidate.py` using the observed junction, edge map, and connection signature. Run that single test, patch the shared root cause in `junction_rebuild_candidate.py`, rerun the single test and the full junction suite, rebuild the next checkpoint from the prior checkpoint's plain files with NetEdit/netconvert command-line tooling, and restart inventory with the new candidate hash. Do not use MCP for routine repair and do not patch screenshot logic to hide a structural mismatch.

- [ ] **Step 6: Expand one Manhattan ring at a time**

For distance values from `$ringDistance + 1` through the maximum distance present in `city-manifest.json`, run the visual phase with `--resume --max-tile-distance $distance`. Advance only when `fail_lane_count` is zero for the covered scope and every retained failure directory has been resolved.

Use this loop:

```powershell
$pairs = $manifest.junction_pairs
$maxDistance = ($pairs | ForEach-Object {
    $x,$y = $_.tile_id.Split('_') | ForEach-Object { [int]$_ }
    [Math]::Abs($x-$sx) + [Math]::Abs($y-$sy)
} | Measure-Object -Maximum).Maximum
for ($distance = $ringDistance + 1; $distance -le $maxDistance; $distance++) {
    .venv\Scripts\python.exe plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py --teacher-net $teacher --candidate-net $candidate --source-osm $osm --output-dir $out --phase visual --resume --max-tile-distance $distance
    $summary = Get-Content -Raw -Encoding utf8 (Join-Path $out 'visual-summary.json') | ConvertFrom-Json
    if ($summary.fail_lane_count -ne 0) { throw "visual ring $distance failed" }
}
```

- [ ] **Step 7: Run the unbounded visual pass and full global audit**

```powershell
.venv\Scripts\python.exe plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py --teacher-net $teacher --candidate-net $candidate --source-osm $osm --output-dir $out --phase visual --resume
.venv\Scripts\python.exe plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py --teacher-net $teacher --candidate-net $candidate --source-osm $osm --output-dir $out --phase global --resume
```

Expected: every applicable lane passes; visual coverage is `complete`; SUMO loads the full candidate; every stratified route is routed and arrives; teleports and collisions are zero; city completion and automatic promotion gates are `pass`.

- [ ] **Step 8: Run final verification and commit code fixes**

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check plugins/torii-sumo/src/torii_sumo/core/netedit.py plugins/torii-sumo/src/torii_sumo/core/netedit_connection_visual_gate.py plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py
git status --short
```

Expected: focused new tests pass, the complete suite has no new failures compared with the recorded baseline, Ruff passes, and only the user's pre-existing untracked `plugins/torii-sumo/src/torii_sumo.egg-info/` remains outside intentional changes.

Commit any final reconstruction fix separately from the visual-gate commits:

```powershell
git add -- plugins/torii-sumo/src/torii_sumo/core/junction_rebuild_candidate.py tests/test_junction_rebuild_candidate.py
git commit -m "fix: repair citywide junction reconstruction defect"
```

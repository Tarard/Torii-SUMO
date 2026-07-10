# Intersection Cleaning Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status note (2026-07-03):** Tasks 1-5 from this plan were implemented on branch `html` in commit `a1686ee`. The remaining refinement work moved to `docs/superpowers/plans/2026-07-03-intersection-cleaning-next-phase.md`.

**Goal:** Tighten the existing Torii-SUMO intersection-cleaning semantic model without rewriting the pipeline.

**Architecture:** Extend the current Pydantic IR models and reuse existing inference modules. Keep geometry, support handling, TLS compilation, validation, and MCP summaries in their current files with small focused edits.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, stdlib XML parsing.

---

> **Status note (2026-07-03):** Tasks 1-5 from this plan were implemented on branch `html` in commit `a1686ee`. The remaining refinement work moved to `docs/superpowers/plans/2026-07-03-intersection-cleaning-next-phase.md`.

### Task 1: Freeze IR Layer Fields

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/intersection/schema.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/intersection/infer_approaches.py`
- Test: `tests/intersection/test_schema.py`

- [ ] **Step 1: Write the failing schema assertions**

Add assertions that an `Approach` JSON dump includes `mode_layer`, `is_vehicle_approach`, `is_support_only`, and `fused_support_modes`, and that `RoadPairRelation` includes `severity`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/intersection/test_schema.py -q`

Expected: failure because the new fields are absent.

- [ ] **Step 3: Add minimal model fields and infer values**

In `Approach`, add defaults:

```python
mode_layer: Literal["vehicle", "support", "fused_support_lane"] = "vehicle"
is_vehicle_approach: bool = True
is_support_only: bool = False
fused_support_modes: list[set[str]] = Field(default_factory=list)
```

In `RoadPairRelation`, add:

```python
severity: Literal["none", "diagnostic", "blocking", "manual_review"] = "none"
```

In `infer_approaches`, set support rows to `support`, vehicle rows with fused extra lane modes to `fused_support_lane`, and plain vehicle rows to `vehicle`.

- [ ] **Step 4: Run schema test to verify it passes**

Run: `pytest tests/intersection/test_schema.py -q`

Expected: pass.

### Task 2: Relation Geometry From Approach Shapes

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/intersection/infer_road_relations.py`
- Test: `tests/intersection/test_infer_road_relations.py`

- [ ] **Step 1: Write failing tests**

Add one test where `source_way_ids[0]` is far away but `source_shape_xy` endpoints are near, expecting `near_miss`. Add one test where crossing ways differ by `bridge` or `layer`, expecting `expected_relation == "should_not_connect"` and `suggested_fix == "preserve_separate_levels"`.

- [ ] **Step 2: Run relation tests to verify failures**

Run: `pytest tests/intersection/test_infer_road_relations.py -q`

Expected: the new tests fail.

- [ ] **Step 3: Replace first-way geometry with approach polyline geometry**

Use `Approach.source_shape_xy` when available. Aggregate shared nodes from all source ways. Compute endpoint gap and minimum segment distance across all polyline segments. If layer, bridge, or tunnel tags differ, force separate-level relation before crossing fixes.

- [ ] **Step 4: Run relation tests**

Run: `pytest tests/intersection/test_infer_road_relations.py -q`

Expected: pass.

### Task 3: Movement Legality

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/intersection/infer_movements.py`
- Test: `tests/intersection/test_infer_movements_control.py`

- [ ] **Step 1: Write failing disjoint same-mode test**

Add a test with two passenger approaches whose relation is `disjoint` and `expected_relation == "unknown"`. Assert both directed movements are not allowed.

- [ ] **Step 2: Run movement tests to verify failure**

Run: `pytest tests/intersection/test_infer_movements_control.py -q`

Expected: new test fails because same-mode unknown movement is currently allowed.

- [ ] **Step 3: Add the minimal legality predicate**

Allow only when modes overlap, layers are compatible, relation is `should_connect`, and turn is not an unsupported U-turn. Keep `restriction_blocked_count == 0`.

- [ ] **Step 4: Run movement tests**

Run: `pytest tests/intersection/test_infer_movements_control.py -q`

Expected: pass, including existing T3 count.

### Task 4: TLS Connection Index Safety

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/intersection/schema.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/intersection/compile_plain.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/intersection/infer_control.py`
- Test: `tests/intersection/test_compile_plain.py`

- [ ] **Step 1: Write failing TLS connection tests**

Assert every connection with `tl` has `linkIndex < len(phase.state)` and phase state length equals the controlled compiled connection count.

- [ ] **Step 2: Run compile tests**

Run: `pytest tests/intersection/test_compile_plain.py -q`

Expected: new test exposes movement-index vs connection-index ambiguity.

- [ ] **Step 3: Add a tiny `CompiledConnection` model or internal dict**

Keep this internal if possible. Generate connection rows with their own `link_index`. Expand phase states from movement phase state to connection phase state using the movement id.

- [ ] **Step 4: Label fallback source**

Append `synthetic:alternating_placeholder` to `ControlModel.source` when synthetic alternating phases are generated.

- [ ] **Step 5: Run compile/control tests**

Run: `pytest tests/intersection/test_compile_plain.py tests/intersection/test_infer_movements_control.py -q`

Expected: pass.

### Task 5: Structured Validation And Summaries

**Files:**
- Modify: `plugins/torii-sumo/src/torii_sumo/intersection/schema.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/intersection/validate.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/intersection/clean.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/tools/intersection_tools.py`
- Test: `tests/intersection/test_validate.py`
- Test: `tests/intersection/test_intersection_tools.py`

- [ ] **Step 1: Write failing validation tests**

Add tests for malformed `tlLogic` phase length, missing controlled compiled connection, and a diagnostic warning that does not block.

- [ ] **Step 2: Run validation tests**

Run: `pytest tests/intersection/test_validate.py -q`

Expected: new tests fail.

- [ ] **Step 3: Add structured warnings without breaking old `warnings` list**

Add a small validation warning model or dict-compatible field with `message`, `severity`, and `source`. Preserve `warnings: list[str]`.

- [ ] **Step 4: Parse XML artifacts when available**

Read plain connection and tllogic files first; use compiled net XML if present. Check controlled connection link indexes and phase state length.

- [ ] **Step 5: Add MCP summary fields**

Return `warning_count_by_severity` and `blocking_error_count` while keeping existing keys.

- [ ] **Step 6: Run validation/tool tests**

Run: `pytest tests/intersection/test_validate.py tests/intersection/test_intersection_tools.py -q`

Expected: pass.

### Final Verification

- [ ] **Step 1: Run acceptance command**

Run:

```powershell
pytest tests/intersection/test_geometry.py tests/intersection/test_osm_patch.py tests/intersection/test_schema.py tests/intersection/test_infer_core_approaches.py tests/intersection/test_infer_road_relations.py tests/intersection/test_infer_movements_control.py tests/intersection/test_compile_plain.py tests/intersection/test_validate.py tests/intersection/test_clean_intersection.py tests/intersection/test_intersection_tools.py
```

Expected: all tests pass.

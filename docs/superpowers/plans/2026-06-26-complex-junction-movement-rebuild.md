# Complex Junction Movement Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a diagnostic movement-graph and single-junction rebuild
prototype that can replace bad `netconvert`-inferred connections for complex
Torii-SUMO junctions.

**Architecture:** Add a small movement-model layer that converts a collapsed
complex junction into approaches and allowed movements, exports audit JSON/CSV
first, then generates a plain-XML rebuild candidate only after movement audit
passes. Keep it separate from the global OSM workflow until the Ingolstadt
target is reviewed in NetEdit.

**Tech Stack:** Python stdlib XML parsing, existing Torii-SUMO
junction/topology/modal modules, SUMO `netconvert`, pytest, JSON/CSV artifacts.

## Target Files

- Create
  `plugins/torii-sumo/src/torii_sumo/core/junction_movement_model.py`
- Create
  `plugins/torii-sumo/src/torii_sumo/core/junction_rebuild_candidate.py`
- Create `tests/test_junction_movement_model.py`
- Create `tests/test_junction_rebuild_candidate.py`
- Modify `plugins/torii-sumo/src/torii_sumo/core/junction_aggregation.py`
  only for optional wiring after the prototype works.

## Step 1: Define Movement Model Tests

- [ ] Add tests for `classify_turn_direction(in_axis, out_axis)`.
  - straight-like movement.
  - right turn.
  - left turn.
  - u-turn.
  - skewed but same-road straight continuation.
- [ ] Add a tiny fixture XML network directly in the test file.
- [ ] Test approach extraction from incoming/outgoing edges.
- [ ] Test modal separation: vehicle approaches must not absorb pedestrian or
  bicycle support-only edges.

## Step 2: Implement Minimal Movement Model

- [ ] Implement `classify_turn_direction(in_axis, out_axis) -> str`.
- [ ] Implement `build_approach_model(net_file, junction_id) -> dict`.
- [ ] Implement `build_movement_graph(net_file, junction_id) -> dict`.
- [ ] Include only data required for review:
  - approach id.
  - incoming/outgoing edge ids.
  - road name/ref if present.
  - highway/type.
  - permissions.
  - direction vector.
  - lane count.
  - candidate movement list with reason and confidence.

## Step 3: Add Movement Audit

- [ ] Implement `audit_movement_graph(graph) -> dict`.
- [ ] Flag these states:
  - no incoming vehicle approaches.
  - no outgoing vehicle approaches.
  - duplicate same source/target movements.
  - movement with incompatible permissions.
  - ambiguous target caused by close parallel roads.
  - u-turn emitted without an explicit reason.
  - low-confidence movement that needs human review.
- [ ] Keep the audit read-only. It must not mutate the network.

## Step 4: Export Review Artifacts

- [ ] Implement `write_movement_review(graph, audit, output_dir, prefix)`.
- [ ] Emit:
  - `movement_graph.json`.
  - `movement_audit.json`.
  - `approaches.csv`.
  - `movements.csv`.
- [ ] Verify these files are readable and small enough for manual inspection.

## Step 5: Generate a Conservative Rebuild Candidate

- [ ] Implement `junction_rebuild_candidate.py`.
- [ ] Generate a `.con.xml` file with explicit `<connection>` entries only for
  high-confidence vehicle movements.
- [ ] Do not emit low-confidence or modal-support movements as vehicle
  connections.
- [ ] Reuse the collapsed network as the base input for this first prototype.
- [ ] Produce a `netconvert` command file or JSON summary so the rebuild can be
  repeated exactly.

## Step 6: Single Ingolstadt Target Probe

- [ ] Run against:
  `artifacts/ingolstadt_head_5_5_bbox_20260626/junction_collapse_prototype_281967823_v2/collapse_281967823_junction_aggregated.net.xml`
- [ ] Target junction:
  `cluster_281967823_305519232_7009179649_7626856596_#2more`
- [ ] Output to:
  `artifacts/ingolstadt_head_5_5_bbox_20260626/junction_movement_rebuild_281967823`
- [ ] Compare against TUM only as a development-time reference:
  `examples/02_one_prompt_osm_network/networks/tum_ingolstadt_center_reference.net.xml`

## Step 7: Verification

- [ ] Run focused tests:
  `python -m pytest tests/test_junction_movement_model.py tests/test_junction_rebuild_candidate.py -q`
- [ ] Run full tests if focused tests pass:
  `python -m pytest -q`
- [ ] Verify SUMO can load the rebuilt candidate.
- [ ] Run the existing residual collapse audit.
- [ ] Open the rebuilt candidate in NetEdit connection mode.
- [ ] Stop if NetEdit still shows clearly wrong movement geometry; diagnose from
  `movement_graph.json` before changing footprint geometry again.

## Step 8: Integration Decision

- [ ] If the single target passes review, add optional workflow wiring:
  - run movement audit after complex junction collapse.
  - generate movement review artifacts by default.
  - require human review for low-confidence movements.
- [ ] Do not make the rebuild path global until at least one bbox-level test
  shows no major regressions.
- [ ] Commit the implementation with tests and the single-junction evidence.

## Stopping Condition

Stop after the first target junction produces:

- explicit audited movements.
- no residual old core nodes/edges/via fragments.
- SUMO load success.
- no obvious incorrect connection geometry in NetEdit connection mode.
- a clear pass/review/fail movement audit artifact.

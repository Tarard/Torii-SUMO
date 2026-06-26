# Netedit-First Review Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Torii's OSM-to-SUMO cleanup workflow produce Netedit-ready review artifacts so users inspect uncertain junction clusters in Netedit instead of relying on the HTML map as the authoritative view.

**Architecture:** Keep the HTML review page as the clean cockpit for queueing, filtering, and batch decisions. Use Netedit's existing command-line inputs (`--sumocfg-file`, `--additional-files`, and `--selection-file`) as the detailed map surface. Generate one global review config plus per-cluster selection files and commands; do not fork SUMO or add a browser service until this lower-cost path proves insufficient.

**Tech Stack:** Python stdlib, SUMO/Netedit 1.26 command-line options, existing static HTML, existing pytest tests. No new dependencies.

---

### Task 1: Generate Cluster Selection Files

**Files:**
- Modify: `C:/Users/huqio/Documents/Torii-SUMO/plugins/torii-sumo/src/torii_sumo/core/workflow_review_html.py`
- Modify: `C:/Users/huqio/Documents/Torii-SUMO/tests/test_workflow_review_html.py`

- [x] Write a failing test that expects one `workflow_netedit_review_c1_selection.txt` file.
- [x] Implement per-cluster selection files containing `junction:<node_id>` lines from each review cluster's `node_ids`.
- [x] Return selection file metadata and a Netedit command using `--selection-file`.
- [x] Run `python -m pytest tests/test_workflow_review_html.py::test_workflow_review_html_writes_visual_cockpit_and_sidecars -q`.

### Task 2: Expose Netedit Commands In HTML Data

**Files:**
- Modify: `C:/Users/huqio/Documents/Torii-SUMO/plugins/torii-sumo/src/torii_sumo/core/workflow_review_html.py`
- Modify: `C:/Users/huqio/Documents/Torii-SUMO/tests/test_workflow_review_html.py`

- [x] Add each cluster's portable selection file and command to `review_app.junctions`.
- [x] Add a compact Netedit command button/link in each junction card.
- [x] Keep the existing global "Netedit overlay" link.
- [x] Run the focused review HTML test.

### Task 3: Expose Workflow-Level Artifacts

**Files:**
- Modify: `C:/Users/huqio/Documents/Torii-SUMO/plugins/torii-sumo/src/torii_sumo/core/workflow_review_html.py`
- Modify: `C:/Users/huqio/Documents/Torii-SUMO/plugins/torii-sumo/src/torii_sumo/core/osm_workflow.py`
- Modify: `C:/Users/huqio/Documents/Torii-SUMO/tests/test_osm_network_tools.py`

- [x] Return `netedit_review_selection_files` from the HTML generator.
- [x] Copy that field into the OSM cleanup workflow report.
- [x] Assert the workflow report contains existing selection files.
- [x] Run the existing workflow smoke test.

### Task 4: Verify With Current Artifact

**Files:**
- Modify only if verification fails: files above.

- [x] Regenerate `C:/Users/huqio/Documents/Torii-SUMO/artifacts/torii_workflow_run_2026-06-26_dresden_center/review/sumo_osm_cleanup_workflow_review.html`.
- [x] Confirm the generated review folder contains `*_selection.txt` files.
- [x] Run:

```powershell
python -m pytest tests/test_workflow_review_html.py tests/test_workflow_router.py tests/test_mcp_tools.py::test_sumo_network_review_html_tool_returns_review_artifact tests/test_osm_network_tools.py::test_osm_cleanup_workflow_runs_topology_audit_by_default -q
```

### Task 5: Auto-Open Netedit Review Config

**Files:**
- Modify: `C:/Users/huqio/Documents/Torii-SUMO/plugins/torii-sumo/src/torii_sumo/core/netedit.py`
- Modify: `C:/Users/huqio/Documents/Torii-SUMO/plugins/torii-sumo/src/torii_sumo/core/osm_workflow.py`
- Modify: `C:/Users/huqio/Documents/Torii-SUMO/tests/test_osm_network_tools.py`

- [x] Make `launch_netedit()` open `.sumocfg` files with `--sumocfg-file`.
- [x] After review sidecars are generated, launch the Netedit review `.sumocfg`.
- [x] Expose `netedit_review_launch_status`, process id, input file, and launch report in the workflow report.
- [x] Run the targeted Netedit and workflow tests.

### Non-Goals

- Do not fork or patch SUMO/Netedit in this pass.
- Do not build a local browser-to-Netedit control service yet.
- Do not continue trying to make the HTML SVG match Netedit's renderer.

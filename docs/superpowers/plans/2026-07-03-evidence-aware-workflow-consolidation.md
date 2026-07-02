# Evidence-Aware Workflow Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate Torii-SUMO around a narrow evidence-aware OSM-to-SUMO workflow claim before adding more network repair heuristics.

**Architecture:** Week 1 is documentation and release-boundary work only: write the consolidation spec, add an architecture document, narrow the README claim, and verify license metadata. Later weeks introduce `WorkflowState`, `StageResult`, `NetworkQualityVector`, Ingolstadt benchmark artifacts, and review cockpit writeback.

**Tech Stack:** Markdown, existing pytest documentation/package tests, current Torii-SUMO repo layout.

---

## Current Evidence Boundary

The `html` branch already contains broad OSM-to-SUMO workflow tooling, TUM
teacher-guided probes, NetEdit review helpers, and an Ingolstadt comparison
example. The next step is not another repair heuristic. The next step is to
make the system claim, architecture, and benchmark path explicit.

## Target Files

- Create: `docs/superpowers/specs/2026-07-03-evidence-aware-workflow-consolidation.md`
- Create: `docs/superpowers/plans/2026-07-03-evidence-aware-workflow-consolidation.md`
- Create: `ARCHITECTURE.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `README.de.md`
- Modify: `docs/release/public-repo-manifest.md`
- Modify: `tests/test_docs_plugin_install.py`

## Task 1: Record The Consolidation Spec

**Files:**
- Create: `docs/superpowers/specs/2026-07-03-evidence-aware-workflow-consolidation.md`
- Create: `docs/superpowers/plans/2026-07-03-evidence-aware-workflow-consolidation.md`

- [ ] **Step 1: Write the spec**

Create `docs/superpowers/specs/2026-07-03-evidence-aware-workflow-consolidation.md` with these required sections:

```text
Target
Control Loop
Product Claim Boundary
Architecture
NetworkQualityVector
Ingolstadt Golden Benchmark
Review Cockpit Requirements
Testing Strategy
Four-Week Execution Order
Immediate Execution Boundary
```

- [ ] **Step 2: Write this implementation plan**

Create `docs/superpowers/plans/2026-07-03-evidence-aware-workflow-consolidation.md` with Week 1 tasks only and explicit follow-on boundaries for Weeks 2-4.

- [ ] **Step 3: Verify the files exist**

Run:

```powershell
Test-Path docs\superpowers\specs\2026-07-03-evidence-aware-workflow-consolidation.md
Test-Path docs\superpowers\plans\2026-07-03-evidence-aware-workflow-consolidation.md
```

Expected:

```text
True
True
```

## Task 2: Add Architecture Boundary Document

**Files:**
- Create: `ARCHITECTURE.md`
- Modify: `docs/release/public-repo-manifest.md`

- [ ] **Step 1: Create `ARCHITECTURE.md`**

Write a concise architecture document with:

```text
Main Claim
Layer 1: Router
Layer 2: Planner
Layer 3: Executor
Layer 4: Reviewer
Quality Vector
Promotion Rule
Near-Term Benchmark
Non-Goals
```

- [ ] **Step 2: Add architecture doc to the public manifest**

Modify `docs/release/public-repo-manifest.md` so the `Include` block contains:

```text
ARCHITECTURE.md
```

near the other root-level public documents.

- [ ] **Step 3: Verify the manifest includes the new doc**

Run:

```powershell
Select-String -Path docs\release\public-repo-manifest.md -Pattern "ARCHITECTURE.md"
```

Expected: one matching line.

## Task 3: Narrow README Product Claim

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `README.de.md`

- [ ] **Step 1: Update the main heading and opening claim**

Replace broad wording that implies one prompt produces a finished network with wording that says Torii creates a bounded, evidence-aware, reference-comparable OSM-to-SUMO workflow.

- [ ] **Step 2: Link `ARCHITECTURE.md`**

Add a short architecture sentence in the README after the layer table:

```markdown
The architecture is documented in [`ARCHITECTURE.md`](ARCHITECTURE.md): router, planner, executor, and reviewer.
```

- [ ] **Step 3: Keep the Ingolstadt evidence table unchanged**

Do not alter the committed Ingolstadt example counts in this task.

## Task 4: Guard The Documentation Contract

**Files:**
- Modify: `tests/test_docs_plugin_install.py`

- [ ] **Step 1: Add README architecture assertions**

Extend `test_readme_links_plugin_install_doc`:

```python
assert "ARCHITECTURE.md" in readme
assert "evidence-aware" in readme
assert "reference-comparable" in readme
```

- [ ] **Step 2: Add manifest architecture assertion**

Extend `test_internal_superpowers_plans_are_not_public_release_content`:

```python
assert "ARCHITECTURE.md" in manifest
```

- [ ] **Step 3: Run documentation tests**

Run:

```powershell
python -m pytest tests\test_docs_plugin_install.py tests\test_plugin_packaging.py -q
```

Expected:

```text
passed
```

## Task 5: Commit And Push Week 1 Docs

**Files:**
- Stage all Week 1 files listed above.

- [ ] **Step 1: Inspect diff**

Run:

```powershell
git diff --stat
git diff -- README.md ARCHITECTURE.md docs\release\public-repo-manifest.md tests\test_docs_plugin_install.py
```

Expected: only documentation, manifest, and doc-test changes.

- [ ] **Step 2: Commit**

Run:

```powershell
git add README.md README.zh-CN.md README.de.md ARCHITECTURE.md docs\release\public-repo-manifest.md tests\test_docs_plugin_install.py docs\superpowers\specs\2026-07-03-evidence-aware-workflow-consolidation.md docs\superpowers\plans\2026-07-03-evidence-aware-workflow-consolidation.md
git commit -m "docs: consolidate evidence-aware workflow direction"
```

Expected: commit succeeds.

- [ ] **Step 3: Push**

Run:

```powershell
git push origin html
```

Expected: `html` updates on GitHub.

## Follow-On Boundary

Do not start Week 2 in this task. Week 2 begins with a code plan for
`WorkflowState`, `StageResult`, and `NetworkQualityVector`, plus tests that map
existing `run_osm_cleanup_workflow` fields into grouped stage results without
changing behavior.

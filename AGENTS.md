# Torii Repository Instructions

These instructions apply to the whole repository.

## Start Here

Before changing structure or adding a public capability, read:

1. `README.md` for the user-facing promise;
2. `ARCHITECTURE.md` for claim and promotion boundaries;
3. `docs/workflow.md` for the canonical user path, status model, and artifact contract;
4. `docs/repository-guide.md` for directory ownership;
5. `docs/mcp-tool-catalog.md` for the registered public tool surface.

## Code Placement

- Put reusable SUMO, OSM, audit, candidate, and artifact logic under `plugins/torii-sumo/src/torii_sumo/core/` or a focused domain package.
- Keep `plugins/torii-sumo/src/torii_sumo/tools/` thin: validate/resolve inputs, call domain logic, and serialize structured outputs.
- Use `plugins/torii-sumo/src/torii_sumo/server.py` only to register MCP tools and their public descriptions.
- Put reasoning and workflow-selection guidance under `plugins/torii-sumo/skills/`; do not implement subprocess or XML algorithms in skill prose.
- Put reusable workflow composition in workflow modules, not in one-off CLI scripts. Broad orchestration must enter through the managed workflow contract.
- Put reproducible CLI entry points under `plugins/torii-sumo/scripts/`; scripts must call reusable implementation rather than duplicate it.

## Evidence Invariants

- Keep source artifacts immutable and write candidates separately.
- Do not treat SUMO load, route completion, or KPI improvement as proof of topology, demand, control, or field correctness.
- Use the canonical managed statuses: `complete`, `incomplete`, `blocked`, `invalid`, `review_required`, `unsupported`, `failed`, or `stale`. Domain tools may retain narrower local decisions.
- Bind promotion-relevant evidence to exact source/candidate hashes and declared edit scope.
- Preserve rollback and outside-scope regression evidence for materialized candidates.
- State non-identifiability and claim boundaries in tool output instead of hiding them in documentation alone.

## Repository Hygiene

- Put curated demonstrations in `examples/` and frozen evaluation assets in `benchmarks/`.
- Put generated runs in `outputs/` or an explicit artifact directory; do not place generated data in `docs/`.
- Do not create a new top-level directory when an existing ownership category fits.
- Add dated research snapshots without silently rewriting historical protocols.
- Preserve unrelated dirty-worktree changes and avoid broad formatting of files outside the active task.

## Public Surface Changes

When adding, renaming, or removing an MCP tool:

1. update `plugins/torii-sumo/src/torii_sumo/server.py`;
2. update `docs/mcp-tool-catalog.md`;
3. update skill routing if normal users should discover it;
4. add or update contract/regression tests;
5. update the README capability table only when the product-level promise changes.

The catalog coverage check is in `tests/test_repository_navigation.py`.

## Verification

- Run focused tests for every changed domain.
- Run `tests/test_repository_navigation.py` for repository navigation or MCP surface changes.
- Run `tests/test_docs_plugin_install.py` for public README/install changes.
- Run Ruff on changed Python files.
- Run `git diff --check` before handoff.

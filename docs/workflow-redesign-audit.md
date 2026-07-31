# Workflow Redesign Audit

## Diagnosis

The repository had strong domain checks but no single authoritative workflow state.

The main entry routed requests into existing executors and returned one in-memory report. Persistent state lived across executor-specific files.

`WorkflowState` and `StageResult` summarized selected report fields after execution. They did not control execution, resume, or cache decisions.

The OSM cleanup module contained 9,067 lines at audit time. Its main public workflow accepted about ninety parameters.

The junction repair subsystem contained 15,623 lines at audit time. It mixed evidence extraction, candidate planning, materialization, gates, and rendering.

The server registered 74 public tools before this change. The broad router did not expose a read-only workflow status operation.

Current documentation named `torii_auto_workflow` as the main entry. It did not define one portable manifest for all broad workflows.

License metadata disagreed with the Apache-2.0 repository license across package, plugin, citation, and Zenodo files.

The general pull-request path did not run a workflow-contract job. A temporary repository export workflow also remained after inspection.

## Actual Pre-change Flow

```text
user or agent
-> MCP server registration
-> tools/workflow_tools.py
-> core/workflow_router.py
-> one selected domain executor
-> executor-specific files and report fields
-> post-hoc summarize_workflow_stages()
-> caller memory or workflow-specific documentation
```

The router selected a recipe. The selected executor owned its own steps, outputs, and failure semantics.

The report could contain source files, candidate files, audits, review HTML, and claim labels. No shared layer verified every declared file before reuse.

A later caller could not ask one tool whether a prior broad run was fresh, stale, incomplete, or safe to resume.

## Root Causes

1. Domain workflows grew before a shared outer contract existed.
2. Status names and gate fields evolved inside separate executors.
3. Artifact provenance was strong in newer workflows but inconsistent across the public router.
4. Post-hoc summaries looked like state but did not govern execution.
5. Documentation repeated workflow policy across README, skills, tool routing, and architecture files.
6. Compatibility pressure kept orchestration inside large legacy functions.

## Main Supported Workflow Families

| Goal | Current executor family | Important evidence boundary |
|---|---|---|
| OSM network construction | OSM cleanup workflow | Area, OSM source, conversion, connectivity, routeability, review |
| TLS and connection review | TLS, Connection Mode, and review tools | Exact network identity, lane paths, request and signal binding |
| Routeability diagnosis | Routeability probe and audit | Completion, insertion, route validity, teleports |
| Candidate repair | Variant and promotion-gate tools | Source/candidate identity, declared scope, rollback, regression gates |
| Synthetic intersection work | Scene and reference workflows | Declared synthetic scope, movement and signal assumptions |
| Hamburg corridor work | W0-W5 and corridor tools | Official source identity, network binding, unresolved field evidence |
| Experiment diagnosis | Comparison and evidence tools | Completion before metric interpretation |

These families remain. The redesign changes their outer control and evidence handoff.

## Architecture Options

### Fixed staged pipeline

This option would force every workflow through one detailed sequence.

It gives simple ordering. It does not fit inspection-only tasks, corridor dependencies, or specialist workflows.

Migration would require rewriting large domain executors before any benefit appeared.

### Dependency graph only

This option would model every artifact and task as a graph node.

It gives precise partial reruns. It adds scheduling and graph-version costs before stage contracts are consistent.

A graph alone does not define review, invalid, unsupported, or claim states.

### Evidence-centered state machine only

This option would make evidence states authoritative.

It gives clear failure and review behavior. It does not select the correct domain workflow from user intent.

It also needs artifact dependencies for stale checks.

### Selected hybrid

The selected design keeps the goal-directed router, adds a five-stage outer state machine, and records an artifact dependency graph in one manifest.

This design gave the smallest coherent change.

It preserves domain behavior and public specialist tools. It removes hidden broad-workflow state and adds a migration boundary around legacy executors.

## Selected Flow

```text
user intent
-> intake and source identity
-> router plan
-> legacy domain executor
-> persisted raw result
-> shared evidence and gate assessment
-> hash-bound manifest
-> complete, blocked, review-required, failed, invalid, unsupported, incomplete, or stale
```

The reasoning chain is:

```text
source -> observation -> interpretation -> candidate -> check
-> decision -> applied change -> validation -> claim
```

The manifest stores these concepts separately. Simulation diagnostics cannot overwrite an earlier evidence failure.

## Implemented Boundary

`core/workflow_manifest.py` owns the shared status model, stage contracts, request fingerprint, artifact identities, resume rules, evidence classes, and manifest inspection.

`tools/workflow_tools.py` exposes `torii_workflow_run` and `torii_workflow_status`.

The existing router remains the domain planner and executor adapter.

`torii_auto_workflow` remains a compatibility facade. It returns legacy fields plus managed workflow fields.

The JSON schema defines the portable manifest contract.

## Paths Removed or Retained

The temporary snapshot export workflow is removed.

No domain repair algorithm is removed in this change. The repository does not yet have enough characterization coverage for that removal.

The post-hoc `workflow_state.py` remains for existing report consumers. It is no longer the canonical broad-workflow state.

Legacy executors remain behind the `execute` stage. New broad orchestration should not bypass the managed layer.

## Test Meaning

The new contract tests protect workflow behavior rather than internal call order.

They cover a successful run, cache reuse, failed execution, retry, stale artifacts, forced rerun, missing official evidence, unsafe repair, rejected repair, human review, conflicting evidence, invalid configuration, path portability, missing declared inputs, and gate precedence.

Server tests protect tool registration and tool descriptions.

Existing router and domain tests remain responsible for workflow selection and SUMO behavior.

## Remaining Problems

Legacy result keys remain heterogeneous. The managed layer must infer some artifact and gate fields.

Fine-grained partial reruns remain executor-specific.

The OSM and repair monoliths still need extraction after behavior is locked by tests.

Current real-SUMO acceptance coverage is split across local scripts and workflow-specific jobs.

Research notes still contain historical architecture language. They should remain historical records rather than current user guidance.

The repository is not ready to claim a universal automatic network repair system. It supports bounded, evidence-aware construction and review.

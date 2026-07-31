# Canonical Torii Workflow

This document defines the current Torii workflow. Other documents should link here instead of restating the workflow.

## Scope

Torii helps an agent and a reviewer construct, inspect, repair, validate, and document a SUMO network from declared evidence.

Torii can prove that recorded checks passed for recorded artifacts. It cannot prove field truth when official data or human review remains missing.

A successful SUMO run does not prove correct geometry, movements, signals, lane identity, demand, or timing.

## User Path

Use `torii_workflow_run` for a broad construction or inspection request.

```text
user request
-> request classification
-> explicit tool plan
-> legacy domain executor
-> evidence assessment
-> workflow manifest
-> supported claim or blocked result
```

Use `torii_workflow_status` to inspect the latest manifest or a named manifest.

Use `torii_auto_workflow` only for compatibility. It returns the legacy-shaped result and adds the managed workflow fields.

A minimal request needs a user goal and an output directory.

```text
Tool: torii_workflow_run
user_request: Inspect this SUMO network and save the evidence.
output_dir: <project output directory>
net_file: <source .net.xml>
```

## Selected Structure

Torii uses a hybrid structure.

- The router remains goal directed.
- The outer workflow is a small state machine.
- Artifacts form a dependency graph through paths, hashes, producers, and consumers.
- Domain checks remain inside existing SUMO executors during migration.

This structure keeps the existing domain work. It adds one authoritative state record without replacing every executor at once.

## Outer Stages

| Stage | Main input | Main output | Failure behavior |
|---|---|---|---|
| `intake` | Request, configuration, source paths | Request fingerprint and source identities | Invalid input blocks execution |
| `plan` | Request fingerprint and user goal | Workflow name and tool chain | Unsupported requests stop |
| `execute` | Plan and source evidence | Persisted raw result and generated artifacts | Exceptions become a persisted failed state |
| `assess` | Raw result and artifact identities | Status, blockers, review items, evidence classes | Missing or conflicting evidence fails closed |
| `publish` | Assessment and raw result | Manifest and latest pointer | Atomic write failure stops publication |

Each stage contract records inputs, output schema, preconditions, postconditions, side effects, retry policy, and cache policy.

The contracts are stored in every manifest. The JSON schema lives at [`../schemas/torii.workflow-manifest.v1.schema.json`](../schemas/torii.workflow-manifest.v1.schema.json).

## Reasoning Model

Torii records this chain:

```text
source
-> observation
-> interpretation
-> candidate
-> check
-> decision
-> applied change
-> validation
-> claim
```

The compact chain is `source -> observation -> interpretation -> candidate -> check -> decision -> applied change -> validation -> claim`.

The chain separates facts from decisions.

`source` identifies external or user-supplied material.

`observation` records parsed values and tool output.

`interpretation` records what Torii infers from observations.

`candidate` records a possible repair without accepting it.

`check` records structural, semantic, runtime, or evidence tests.

`decision` records acceptance, rejection, or review status.

`applied change` identifies a materialized candidate and its rollback basis.

`validation` records checks against the exact candidate.

`claim` states what the recorded evidence supports.

Later simulation success never erases missing evidence, rejected changes, unsafe gates, or pending review.

## Evidence Classes

Every manifest keeps separate lists for:

- `source_evidence`
- `parsed_observations`
- `inferred_facts`
- `repair_candidates`
- `accepted_changes`
- `rejected_changes`
- `unresolved_uncertainty`
- `simulation_diagnostics`
- `product_acceptance_gates`

These lists are not merged into one score.

An input or output path becomes hash-bound when it is part of the declared workflow contract. Missing declared artifacts remain visible.

## Status Model

| Status | Meaning | May support the requested product claim |
|---|---|---|
| `complete` | Required execution and evidence completed | Yes, within the recorded claim boundary |
| `incomplete` | Work stopped before a required stage completed | No |
| `blocked` | A gate or prerequisite prevents progress | No |
| `invalid` | Configuration, evidence, result, or manifest contradicts its contract | No |
| `review_required` | A human decision remains mandatory | No |
| `unsupported` | No declared workflow supports the request | No |
| `failed` | The executor failed | No |
| `stale` | A hash-bound artifact changed or disappeared | No |

A legacy executor can still return its existing status. The managed assessment maps that result into this shared model.

## Persistent Files

A managed run writes:

```text
<output_dir>/
  torii-workflow/
    latest.json
    <run_id>/
      manifest.json
      result.json
```

`run_id` comes from the normalized request, configuration, and source identities.

`result.json` preserves the raw executor result.

`manifest.json` records contracts, evidence classes, artifacts, blockers, review items, attempts, and the claim boundary.

`latest.json` points to the latest manifest under the output directory.

Paths inside the output directory are stored relative to the output directory. A moved output directory remains inspectable.

## Resume and Recovery

A rerun with the same request fingerprint reuses a fresh terminal manifest.

A failed or incomplete run executes again with the same run ID. The manifest records the earlier attempt.

A changed or missing hash-bound artifact produces `stale`. Automatic resume stops.

Use `force=true` only after reviewing the changed artifacts. The new attempt replaces the current result and preserves attempt history.

A malformed manifest produces `invalid`. Correct or remove that manifest before rerunning.

## Repair Boundary

A repair candidate is not an accepted change.

Automatic acceptance requires all declared gates to pass. A failed gate outranks pending review and simulation success.

A review-required candidate needs a recorded reviewer decision through the domain workflow. The managed layer does not invent that decision.

Source networks remain inputs. Candidate writers must create separate files unless a domain contract explicitly states otherwise.

## Agent Interface

An agent should use this sequence:

1. Call `torii_workflow_run` with the user goal and declared inputs.
2. Read `status`, `blockers`, `review_items`, and `next_actions`.
3. Inspect the named manifest before making a claim.
4. Request human review when the status is `review_required`.
5. Call `torii_workflow_status` before resuming an old run.
6. Use `force=true` only after explaining stale evidence.

Specialist tools remain available for a known domain action. They do not replace the managed workflow record for a broad task.

## Extension Rule

Add a workflow recipe only when the user goal, inputs, executor, outputs, and acceptance gates are known.

Keep domain policy in the domain executor. Keep status mapping, artifact identity, resume rules, and evidence classes in the managed workflow layer.

Do not add prompt text to compensate for a missing code contract.

Do not add a new public tool when an existing domain action can expose the needed input or status.

## Compatibility Boundary

The current OSM and repair executors remain behind the `execute` stage.

This is a migration boundary, not a second architecture. New orchestration must enter through the managed workflow.

`torii_auto_workflow` remains for existing callers. It preserves legacy fields on complete runs and overrides false success when the managed status blocks a claim. New callers should use `torii_workflow_run`.

## Current Limits

The managed layer infers artifact references and evidence categories from existing result keys. Legacy executors do not yet emit one shared typed result schema.

Partial reruns currently resume at the outer `execute` stage. Fine-grained stage reuse still depends on each domain executor.

The OSM cleanup and junction repair modules remain large. Their internal steps need characterization tests before extraction.

Many specialist tools can still run outside a managed workflow. Their artifacts keep their existing local contracts.

Real SUMO checks require a local SUMO installation. Unit tests cannot replace those scenario checks.

## Release and Citation

See the [installation guide](codex-plugin-install.md), [tool catalog](mcp-tool-catalog.md), and [citation metadata](../CITATION.cff).

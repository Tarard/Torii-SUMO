# Experiment Planning After Intake

Use this reference after the user confirms the `Experiment Readiness Record`, or when the user asks to start coding or running a SUMO/TraCI experiment from a confirmed setup.

The goal is to convert confirmed experiment intent into an executable, reviewable plan before any code, SUMO files, simulation runs, controller comparisons, or result claims.

## Planning Workflow

1. Check the confirmed `Experiment Readiness Record`.
2. List unresolved risks that affect code, simulation, metrics, or claims.
3. If a major design choice remains open, propose 2-3 options with tradeoffs and a recommendation.
4. Produce a `SUMO Experiment Plan`.
5. Ask the user to confirm the plan.
6. Only after confirmation, proceed to TDD/code, SUMO construction, execution, audit, or reporting.

If the user skips planning, mark the work `diagnostic-only` and do not present the outcome as formal experiment evidence.

## Required Plan Template

```markdown
## SUMO Experiment Plan

### 1. Objective and Claim Boundary
- Research question:
- Formal claim allowed if all gates pass:
- Claims explicitly not supported:

### 2. Scenario and Artifacts
- Network:
- Route/demand files:
- Additional files:
- SUMO config:
- Controller code:
- Output directory pattern:
- Metadata/hash/version records:

### 3. Controller and TLS Semantics
- Controller identity:
- TLS program or TraCI control mechanism:
- Phase/state mapping evidence:
- Yellow/all-red handling:
- Detector or state inputs:
- Control interval and fallback behavior:

### 4. Baselines, Ablations, and Pairing
- Controllers compared:
- Baselines:
- Ablations:
- Demand levels:
- Random seeds:
- Paired variables:
- Variables intentionally changed:

### 5. Run Matrix
| Run group | Controller | Demand | Seed(s) | Horizon/completion | Outputs | Purpose |
|---|---|---|---|---|---|---|

### 6. Completion Policy
- Natural completion or fixed horizon:
- Denominator for planned demand:
- Handling of unfinished vehicles:
- Handling of insertion failure, teleports, discarded routes, and collisions:

### 7. Metrics and Formulas
- Primary metrics:
- Secondary metrics:
- Exact formulas and denominators:
- Artifact source for each metric:
- Completion-aware reporting rule:

### 8. Code and TDD Tasks
- Code changes required:
- Failing tests or probes to write first:
- Minimal fixtures:
- Test commands:
- Integration checks:

### 9. Execution Steps
- SUMO/netconvert/duarouter commands:
- TraCI or controller entrypoint:
- Batch command:
- Output naming rule:
- Log collection:

### 10. Hard Gates
- Config/network/route gate:
- TLS/controller gate:
- Output gate:
- Warning/error/teleport gate:
- Baseline pairing gate:
- Metric validity gate:
- Reproducibility gate:

### 11. Verification and Review
- Commands to run before completion:
- Artifacts to inspect:
- Code review focus:
- Residual risks to report:

### 12. Result Interpretation
- What counts as formal evidence:
- What counts as diagnostic evidence:
- Demotion triggers:
- Required wording if the run is fixed-horizon or incomplete:

Plan status: ready / needs revision / diagnostic-only / blocked
Next allowed action:
```

## Plan Quality Rules

- Use concrete file names, commands, outputs, seeds, and horizons when they are known.
- If exact artifacts are unknown, ask a focused follow-up question instead of inventing details.
- Do not hide design choices inside implementation. If demand, seeds, controller policy, or metrics change, show the change in the plan.
- Do not bundle root-cause debugging fixes with formal comparison runs. Plan diagnostic runs separately.
- Do not let baseline and treatment runs share output paths.
- Do not approve a plan that compares controllers with different demand, seeds, horizons, output intervals, or metric denominators unless the claim is explicitly diagnostic.

## Confirmation Gate

End with:

```text
Plan Confirmation Needed
- ready to proceed:
- fields needing user decision:
- first allowed implementation or simulation action:
```

No SUMO run, controller implementation, metric report, or claim draft should begin before the user confirms the plan, unless the work is explicitly marked `diagnostic-only`.

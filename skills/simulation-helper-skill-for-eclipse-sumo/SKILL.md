---
name: simulation-helper-skill-for-eclipse-sumo
description: Use when planning, coding, debugging, auditing, comparing, or writing claims for Eclipse SUMO/TraCI traffic-signal experiments, including TLS/NEMA, controllers, routes, demand, detectors, outputs, baselines, metrics, reproducibility, TDD changes, and reusable field lessons from user-discovered fixes.
---

# Simulation Helper Skill for Eclipse SUMO

## Purpose

Use this skill as a router and evidence gate for Eclipse SUMO/TraCI traffic-signal experiments. Do not treat it as a full tutorial. First identify the user's scenario, then load only the reference files needed for that path.

Default loop:

```text
request -> classify scenario -> load minimal references -> ask or act -> verify evidence -> bound the claim
```

## Start Here

| Scenario | Load | Expected output |
|---|---|---|
| Ongoing project, unclear progress, repo/logs/outputs provided, or "what next?" | `references/workflow-router.md`, then `references/project-control-screen.md` | `Project Control Screen` and next-step plan |
| New or vague experiment | `references/experiment-intake-interview.md`; after confirmation, `references/experiment-planning-after-intake.md` | `Experiment Readiness Record`, then `SUMO Experiment Plan` |
| SUMO/TraCI failure or suspicious behavior | `debugging-helper-skill-for-eclipse-sumo` | root cause, next probe, fix/rerun/demotion |
| Controller, parser, runner, validator, or audit-code change | `references/tdd-for-sumo-traci-code.md`, then `references/verification-and-review-gates.md` | RED/GREEN/REFACTOR or explicit `test-after` record |
| Results, metrics, baseline comparison, or paper/report claim | `references/sumo-output-hard-gates.md`, `references/evaluation-metrics-and-completion.md`, `references/baseline-and-ablation-design.md`, `references/claim-boundary-taxonomy.md` | evidence class and allowed/prohibited claim wording |
| User found a fix this skill missed | `references/field-lesson-capture.md` | privacy-safe field lesson candidate; ask before persisting |
| Public release or repository exposure check | `references/public-release-checklist.md`, then `references/verification-and-review-gates.md` | release checklist and residual risk |

If a target/current-state/deviation cannot be inferred, switch to the intake path before running experiments or endorsing claims.

## Core Rules

- Load the minimum reference set for the scenario; do not bulk-load every file.
- Confirm missing experiment assumptions before formal execution or comparison.
- Separate what SUMO loaded, what the controller did, what outputs were written, what warnings/failures occurred, and what claim is supportable.
- Compare controllers only with paired route, demand, seed, horizon, outputs, and completion criteria.
- Do not use GUI inspection, clean execution, or arrived-only metrics as sufficient evidence.
- If completion differs across methods, report completion/unfinished/teleport status before travel-time, waiting-time, or delay averages.
- Use these claim labels: `formal-evidence`, `diagnostic-demo`, `stress-diagnostic`, `construction-invalid`, `claim-overreach`, `blocked`.

## Reference Map

Load these only when the scenario requires them:

- Source conflicts or citation priority: `references/source-ladder.md`.
- SUMO network, route, TLS, detector, netconvert, GUI/headless, or TraCI semantics: `references/sumo-official-semantics.md`.
- Official operational pitfalls: `references/sumo-official-operational-lessons.md`.
- Forum, FAQ, mailing-list, or issue-tracker failure patterns: `references/sumo-community-faq-lessons.md`.
- Public traffic-simulation code lessons: `references/public-code-lessons.md`.
- NEMA ring/barrier/split/offset/recall/detector claims: `references/sumo-nema-controller-audit.md`.
- TraCI controller identity and API-boundary checks: `references/sumo-traci-controller-boundaries.md`.
- Sweeps, sensitivity, ablations, structural debugging, or validation ladder: `references/experiment-validation-ladder.md`.

## Output Shape

For most tasks, end with:

```text
scenario:
loaded_references:
missing_assumptions:
evidence:
claim_status:
next_step:
residual_risk:
```

When editing the skill itself, keep this `SKILL.md` lean and move detailed rules into `references/`.

---
name: simulation-helper-skill-for-eclipse-sumo
description: Use when planning, coding, debugging, auditing, comparing, or writing claims for Eclipse SUMO/TraCI traffic-signal experiments, including OSM/netconvert networks, TLS/NEMA, controllers, routes, demand, detectors, outputs, baselines, metrics, reproducibility, TDD changes, and reusable field lessons.
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
| SUMO environment, executable toolchain, or runnable smoke proof is missing | `references/preflight-sumo-environment.md` | `Environment Preflight` record and pass/fail route |
| OSM/imported-network cleanup, road-detail selection, Google Maps or external signal cross-check, detector lane mapping, field-data sensor alignment, or background visualization | `references/model-osm-detectors.md` | modeling plan, road-class ladder, TLS audit, detector-alignment gates, and visualization boundary |
| Ongoing project, unclear progress, repo/logs/outputs provided, or "what next?" | `references/route-project-workflow.md` | `Project Control Screen` and next-step plan |
| New or vague experiment | `references/plan-experiment.md` | `Experiment Readiness Record`, then `SUMO Experiment Plan` |
| SUMO/TraCI failure or suspicious behavior | `debugging-helper-skill-for-eclipse-sumo` | root cause, next probe, fix/rerun/demotion |
| Controller, parser, runner, validator, or audit-code change | `references/develop-and-verify-code.md` | RED/GREEN/REFACTOR or explicit `test-after` record |
| Controller/TLS/NEMA/TraCI boundary question | `references/audit-sumo-controllers.md` | controller identity, API boundary, and missing evidence |
| Mechanism-isolated corridor perturbation comparison, localized impact-signal tests, or multi-baseline controller evidence | `references/compare-corridor-perturbations.md` | controlled-scope experiment logic, paired metrics, negative controls, and claim boundary |
| SUMO semantics, official/forum lessons, or public-code pattern | `references/learn-sumo-knowledge.md` | source-bounded lesson and evidence requirement |
| Results, metrics, baseline comparison, or paper/report claim | `references/evaluate-and-report-results.md` | evidence class and allowed/prohibited claim wording |
| User found a fix this skill missed | `references/capture-field-lesson.md` | privacy-safe field lesson candidate; ask before persisting |
| Public release or repository exposure check | `references/release-project.md` | release checklist and residual risk |

If a target/current-state/deviation cannot be inferred, switch to the intake path before running experiments or endorsing claims.

## Core Rules

- Load the minimum reference set for the scenario; do not bulk-load every file.
- Confirm missing experiment assumptions before formal execution or comparison.
- Prove the SUMO environment before formal experiment work when `sumo`, `duarouter`, `SUMO_HOME`, Python, `traci`, or output generation has not been verified.
- Separate what SUMO loaded, what the controller did, what outputs were written, what warnings/failures occurred, and what claim is supportable.
- Compare controllers only with paired route, demand, seed, horizon, outputs, and completion criteria.
- Do not use GUI inspection, clean execution, or arrived-only metrics as sufficient evidence.
- If completion differs across methods, report completion/unfinished/teleport status before travel-time, waiting-time, or delay averages.
- Use these claim labels: `formal-evidence`, `diagnostic-demo`, `stress-diagnostic`, `construction-invalid`, `claim-overreach`, `blocked`.
- At the end of each SUMO experiment or experiment-code pass, check whether the run produced a reusable SUMO/TraCI lesson. If yes, update the relevant skill reference instead of leaving the lesson only in the chat.

## Reference Map

Load these only when the scenario requires them:

- Ongoing project routing, state screening, or "what next?": `references/route-project-workflow.md`.
- SUMO executable environment, `SUMO_HOME`, Python tooling, or smoke-test proof: `references/preflight-sumo-environment.md`.
- Experiment intake and planning: `references/plan-experiment.md`.
- Code implementation, TDD, and completion evidence: `references/develop-and-verify-code.md`.
- OSM/imported-network modeling, road-detail selection, Google Maps or external signal cross-check, detector lane repair, field-data sensor alignment, and background visualization: `references/model-osm-detectors.md`.
- SUMO semantics, official/forum lessons, and public-code patterns: `references/learn-sumo-knowledge.md`.
- NEMA/TLS/TraCI controller identity and API-boundary checks: `references/audit-sumo-controllers.md`.
- Mechanism-isolated corridor perturbation comparisons, localized impact-signal tests, and multi-baseline controller evidence: `references/compare-corridor-perturbations.md`.
- Outputs, metrics, baselines, ablations, validation ladder, and claim wording: `references/evaluate-and-report-results.md`.
- User-discovered reusable fixes: `references/capture-field-lesson.md`.
- Public release, trademark, privacy, and exposure checks: `references/release-project.md`.

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

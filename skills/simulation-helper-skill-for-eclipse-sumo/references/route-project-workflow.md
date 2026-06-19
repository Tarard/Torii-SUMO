# Route Project Workflow

Use this reference first when the user points the skill at an existing SUMO/TraCI project, asks what to do next, mixes several requests, or provides code, logs, outputs, partial results, or an unclear experiment state.

The goal is to estimate the current state before choosing an action. Do not load every reference by default.

## Entry Decision

```text
user request -> classify situation -> screen project state -> load minimum references -> produce next action or ask one focused question
```

## Project Screen

Capture the observable state before acting:

```text
Project Control Screen
target:
current_state:
deviation:
available_artifacts:
missing_artifacts:
environment_preflight: pass / fail / stale / missing / not_needed
controller_state:
route_and_demand_state:
output_state:
comparison_state:
claim_state:
next_step:
```

Use `preflight-sumo-environment.md` before formal execution, controller debugging, metric comparison, or claim review if the SUMO/Python toolchain has not been proven recently.

## Scenario Map

| User situation | Load next | Main output |
|---|---|---|
| New machine, fresh clone, missing `SUMO_HOME`, or no recent runnable proof | `preflight-sumo-environment.md` | Environment Preflight record |
| New or vague experiment | `plan-experiment.md` | Experiment Readiness Record, then SUMO Experiment Plan |
| SUMO, TraCI, route, detector, TLS, output, seed, or completion failure | `debugging-helper-skill-for-eclipse-sumo` | root cause, next probe, fix/rerun/demotion |
| Controller, parser, runner, validator, generator, or audit-code change | `develop-and-verify-code.md` | RED/GREEN/REFACTOR or explicit test-after record |
| NEMA, TLS, TraCI controller identity, detector, or API-boundary question | `audit-sumo-controllers.md` | controller boundary and evidence gaps |
| Network, route, TLS, detector, official behavior, forum pattern, or public-code lesson | `learn-sumo-knowledge.md` | source-bounded lesson |
| Results, metrics, baseline comparison, ablation, plot, table, or paper/report wording | `evaluate-and-report-results.md` | evidence class and claim boundary |
| User found a fix this skill missed | `capture-field-lesson.md` | privacy-safe field lesson candidate |
| GitHub, README, Pages, license, Zenodo, or outreach release | `release-project.md` | release checklist and residual risk |

## Decision Rules

- If the target is missing, switch to `plan-experiment.md` and ask only the questions needed to define the experiment.
- If the current state is unobservable, ask for the smallest artifact that would expose it: config, route, log, output folder, command, commit, or result table.
- If the deviation is runtime behavior, route to the debugging helper before changing controller logic.
- If the deviation is code behavior, require `develop-and-verify-code.md`.
- If the deviation is evidence, comparison, completion, or wording, route to `evaluate-and-report-results.md`.
- If the run has no environment proof, keep the status diagnostic until preflight passes or the user accepts a diagnostic-only path.

## Minimal Loading Rule

Load references in this order:

1. This workflow screen.
2. One reference that directly controls the current deviation.
3. `preflight-sumo-environment.md` if toolchain proof is missing or stale.
4. One execution or evidence gate if code, run, completion, claim, or release is involved.

Avoid broad multi-reference loading unless the user explicitly asks for a full audit.

## Next Step Plan

End with:

```text
scenario:
loaded_references:
why:
missing_artifacts:
next_action:
stop_condition:
claim_status:
```

If the root problem cannot be estimated, ask for one artifact or switch to the Socratic intake in `plan-experiment.md`.

# Workflow Router

Use this reference first when the user points the skill at a SUMO/TraCI project, asks what to do next, mixes several requests, or does not clearly say whether the task is new experiment design, ongoing project diagnosis, code implementation, debugging, result review, or public release.

The router decides which focused reference files to load. Do not load every reference by default.

## Entry Decision

```text
user request -> classify scenario -> load the minimum needed references -> produce next action or ask one focused question
```

## Scenario Map

| Scenario | User situation | First reference or skill | Then route to | Main output |
|---|---|---|---|---|
| Ongoing project screen | User has an existing repo, partial experiment, code, logs, outputs, or unclear progress. | `project-control-screen.md` | intake if no stable target/deviation; otherwise debugging, TDD, verification, metrics, or claim references | Project Control Screen and Next Step Plan |
| New or unclear experiment | User wants to design/run a SUMO experiment but details are incomplete. | `experiment-intake-interview.md` | `experiment-planning-after-intake.md` after readiness confirmation | Experiment Readiness Record, then SUMO Experiment Plan |
| Confirmed intake | User confirms the readiness record and wants to proceed. | `experiment-planning-after-intake.md` | TDD, SUMO semantics, hard gates, metrics, baselines | Confirmed SUMO Experiment Plan |
| Code change | User asks to implement or modify controller, parser, runner, validator, generator, or audit code. | `tdd-for-sumo-traci-code.md` | `verification-and-review-gates.md` | TDD completion record |
| Runtime failure | SUMO, TraCI, route, detector, TLS, output, seed, or completion behavior fails. | `debugging-helper-skill-for-eclipse-sumo` | debugging references; then field lesson if the user later finds a reusable fix | Root cause, evidence, fix or demotion |
| Result or claim audit | User has outputs, plots, tables, or paper/report wording. | `sumo-output-hard-gates.md` | `evaluation-metrics-and-completion.md`, `baseline-and-ablation-design.md`, `claim-boundary-taxonomy.md` | Evidence class and claim boundary |
| SUMO semantics question | User asks about network, route, TLS, TraCI, NEMA, detector, GUI/headless, or official behavior. | `sumo-official-semantics.md` | NEMA, TraCI, official/community lessons as needed | Source-bounded answer |
| Public-code or source lesson | User asks what public examples or community failures imply. | `source-ladder.md` | `public-code-lessons.md`, `sumo-community-faq-lessons.md` | Bounded lesson, not endorsement |
| User-discovered fix | User says the skill missed a path and they later solved it. | `field-lesson-capture.md` | relevant existing reference after user confirmation | Field Lesson Candidate and patch proposal |
| Public release | User prepares GitHub, Pages, README, license, or outreach release. | `public-release-checklist.md` | verification gate | Release checklist and residual risk |

## Ongoing Project Rule

For an existing project, start with `project-control-screen.md` unless the user explicitly names a narrower task. The screen decides whether the project already has:

- a stable target;
- observable current state;
- a concrete deviation;
- enough artifacts to choose the next bounded action.

If any of these are missing, do not guess. Switch to `experiment-intake-interview.md` or ask for the single missing artifact needed to estimate state.

## Minimal Loading Rule

Load references in this order:

1. The scenario entry reference.
2. One semantic or evidence reference needed by the current deviation.
3. One execution gate if code, run, completion, or release is involved.

Avoid loading multiple broad references unless the task spans multiple gates.

## Response Pattern

When routing, state:

```text
scenario:
loaded_references:
why:
next_output:
```

Then produce the required output from the chosen reference.

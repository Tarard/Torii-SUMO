# Project Control Screen

Use this reference when the skill is applied to an ongoing SUMO/TraCI project, repository, partially completed experiment, failed run, result folder, controller implementation, or uncertain workflow state.

The purpose is to estimate the project state before choosing a next action. Do not start with a full experiment intake if current artifacts already reveal the target, state, and deviation.

## Observation Pass

Inspect only the minimum available artifacts needed to estimate state:

- user prompt and stated objective;
- README, experiment notes, config files, and scripts;
- SUMO `.sumocfg`, `.net.xml`, route files, additional files, detector files, TLS programs;
- TraCI controller code, parser code, batch runners, output directory rules;
- environment records: `sumo --version`, `netgenerate --version`, `duarouter --version`, Python version, `traci.__file__`, `sumolib.__file__`, `SUMO_HOME`, and recent smoke-test artifacts;
- logs, warnings, `summary.xml`, `tripinfo.xml`, `edgeData`, TLS switch outputs, controller logs;
- recent git diff or changed files if code was modified.

Separate observed facts from assumptions.

## Project Control Screen Record

Produce this before recommending action:

```text
Project Control Screen
target:
current_state:
observed_artifacts:
known_facts:
assumptions:
environment_preflight: pass / fail / stale / missing / not_needed
deviation:
likely_problem:
missing_observations:
risk_of_wrong_state_estimate:
next_control_action:
expected_feedback:
stop_condition:
claim_status: formal-evidence / diagnostic-demo / construction-invalid / claim-overreach / unknown
```

## Decision Rules

If `target`, `current_state`, and `deviation` are all clear:

1. Choose one bounded next action.
2. Route to the narrow reference that controls that action.
3. Produce a `Next Step Plan`.

If the deviation is a runtime failure, route to `debugging-helper-skill-for-eclipse-sumo`.

If the environment preflight is missing, stale, or failed, route to `environment-preflight-and-smoke-test.md` before controller logic, formal execution, metrics, or claim review.

If the deviation is missing experiment design detail, route to `experiment-intake-interview.md`.

If the deviation is code behavior, route to `tdd-for-sumo-traci-code.md`.

If the deviation is insufficient evidence or a premature completion claim, route to `verification-and-review-gates.md`.

If the deviation is metric, completion, baseline, or claim wording, route to the corresponding evidence references.

## Next Step Plan

When a deviation is found, produce:

```text
Next Step Plan
immediate_objective:
reference_to_use:
files_or_artifacts_to_inspect:
smallest_safe_action:
test_or_probe:
expected_feedback:
stop_condition:
claim_status_after_action:
```

Do not produce a multi-day implementation plan unless the user asks for one or the next action requires confirmed experiment planning.

## Switch to Socratic Intake

If no stable target/current-state/deviation can be inferred, do not invent a plan. Say:

```text
Switch to Socratic Intake
reason:
missing_fields:
first_question:
```

Then use `experiment-intake-interview.md` and ask one focused question at a time.

## Anti-Patterns

- Do not assume the user's intended claim from a filename or plot title.
- Do not debug controller logic before proving SUMO startup, Python tooling, and output creation when environment evidence is missing.
- Do not treat a runnable SUMO config as evidence that the experiment is ready.
- Do not diagnose controller superiority before verifying outputs, completion, pairing, and metric definitions.
- Do not skip directly to code edits when project state is unknown.

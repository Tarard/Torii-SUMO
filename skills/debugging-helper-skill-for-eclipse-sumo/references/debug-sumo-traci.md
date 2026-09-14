# Debug SUMO/TraCI

Use this reference when diagnosing SUMO, TraCI, netconvert, duarouter, route, demand, detector, TLS, output, teleport, insertion, seed, performance, or reproducibility failures.

The debugging loop is:

```text
observe artifacts -> classify deviation -> choose one probe -> run probe -> compare feedback -> fix, rerun, demote, or capture lesson
```

## Observer

Collect only evidence that can change the next action:

```text
command:
working_directory:
sumo_version:
config_file:
net_file:
route_file:
additional_files:
stdout_stderr:
sumo_warnings:
generated_outputs:
completion_counts:
controller_log:
last_known_good_run:
```

Prefer exact commands, logs, configs, and minimal reproductions over screenshots.

## Symptom to Probe Map

| Symptom | First probes |
|---|---|
| SUMO binary not found | `sumo --version`, `SUMO_HOME`, `PATH`, shell used by agent |
| Python `traci` import fails | Python executable, environment, `traci.__file__`, `sumolib.__file__` |
| netconvert/netgenerate fails | command syntax, input format, output path, version |
| duarouter route errors | invalid edges, disconnected network, vehicle types, trips vs routes |
| SUMO runs but `tripinfo` is empty | no arrivals, wrong output path, too-short horizon, no departures |
| vehicles never depart | insertion backlog, depart lane/pos/speed, route capacity, demand timing |
| many teleports | gridlock, collision/jam settings, broken signal timing, invalid demand |
| TLS does not change | wrong TLS ID, controller loop not running, command timing, SUMO program override |
| detector values wrong | lane ID mismatch, detector placement, aggregation period, generated network change |
| results change unexpectedly | seed, route regeneration, output overwrite, unpaired demand, floating run state |
| simulation hangs | unfinished vehicles, TraCI loop condition, `getMinExpectedNumber`, insertion backlog |

## Controller

Classify the fault before proposing fixes:

```text
fault_class:
evidence:
next_probe:
expected_feedback:
```

Fault classes:

- `environment-fault`
- `input-construction-fault`
- `demand-realization-fault`
- `traci-protocol-fault`
- `controller-logic-fault`
- `output-observability-fault`
- `stochasticity-fault`
- `simulator-limitation-or-bug`

## Executor Rules

- Run one probe at a time.
- Keep route, demand, seed, horizon, and output names unchanged unless the probe targets them.
- Mark the run diagnostic if using permissive flags such as `--ignore-route-errors`, `--ignore-errors`, or changed teleport behavior.
- Use headless command evidence before GUI interpretation.
- If TraCI fails, prove SUMO can start from the same config without the controller before debugging controller logic.

## Critic

After each probe:

```text
observed_feedback:
did_it_match_expected:
new_fault_class:
fixed_or_not:
remaining_uncertainty:
```

If the probe does not reduce uncertainty, stop and choose a smaller artifact or minimal reproduction.

## Claim Gate

Classify the debug outcome:

| Result | Claim status |
|---|---|
| Root cause fixed and rerun passes required gates | may return to formal evidence path |
| Root cause fixed but not rerun under paired experiment conditions | diagnostic fix only |
| Workaround changes demand, horizon, route errors, teleport, or controller semantics | diagnostic only unless disclosed and justified |
| Root cause unknown | blocked or construction-invalid |

## Debug Outcome

End every pass with:

```text
root_cause:
evidence:
fix_or_next_probe:
claim_status:
residual_risk:
field_lesson_candidate:
```

If the user later discovers a reusable fix, hand off to `capture-field-lesson.md` in the main skill after privacy/source checks.

---
name: debugging-helper-skill-for-eclipse-sumo
description: Use when diagnosing Eclipse SUMO, TraCI, netconvert, duarouter, route, demand, detector, traffic-light, output, teleport, insertion, seed, performance, or reproducibility failures in traffic-simulation workflows.
---

# Debugging Helper Skill for Eclipse SUMO

## Purpose

Use this skill to debug Eclipse SUMO/TraCI failures as a closed-loop investigation. The goal is root-cause evidence, not keeping a run alive at any cost.

Loop:

```text
failure -> observe artifacts -> classify deviation -> choose one probe -> run probe -> compare feedback -> fix, rerun, or demote
```

## Start Here

When the cause is not already proven, read only the needed references:

- Unknown or multi-cause failure: `references/closed-loop-debugging.md`.
- Known symptom needing evidence mapping: `references/symptom-to-evidence-map.md`.
- Failed or partially fixed run that may affect claims: `references/debugging-gates-and-claim-boundaries.md`.

Ask for one missing artifact at a time. Prefer exact commands, SUMO logs, output files, configs, and minimal reproductions over screenshots or descriptions.

## Rules

- Do not propose fixes before the fault class is evidence-backed.
- Do not hide faults with `--ignore-route-errors`, `--ignore-errors`, larger retries, `--time-to-teleport -1`, GUI-only inspection, or changed demand unless the run is marked diagnostic.
- Classify with these labels: `environment-fault`, `input-construction-fault`, `demand-realization-fault`, `traci-protocol-fault`, `controller-logic-fault`, `output-observability-fault`, `stochasticity-fault`, `simulator-limitation-or-bug`.
- If a user-discovered workaround should improve the public skill, hand off to `simulation-helper-skill-for-eclipse-sumo` and its field-lesson workflow after privacy/source checks.

## Debug Outcome

End every pass with:

```text
root_cause:
evidence:
fix_or_next_probe:
claim_status:
residual_risk:
```

If the root cause is unknown, say so and keep the run out of formal evidence.

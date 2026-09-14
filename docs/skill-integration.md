# Torii Skill Integration

Torii bundles four topic skills with one shared CLI/MCP execution layer. The skills decide how to reason about a task and which evidence matters. Torii tools execute bounded operations and return structured observations.

## Skill Map

| Skill | Owns |
|---|---|
| `torii-build` | OSM and drawing-based network construction, roads, lanes, junctions, signal-device structure, map/source review |
| `torii-calibrate` | detector/count binding, demand reconstruction, fixed-network calibration, digital-twin replay |
| `torii-simulate` | environment checks, experiment planning, workflow execution, controllers, debugging, code and mechanism diagnosis |
| `torii-report` | completed-result interpretation, traffic-control reports, claim boundaries, field lessons, release review |

The old `simulation-helper-skill-for-eclipse-sumo` bundle is retired. Do not create another top-level copy of these skills.

## Product and Skill Boundaries

The product still uses the three public capability groups **Build**, **Calibrate**, and **Simulate**. `torii-report` is a reasoning/reporting skill that works across completed outputs from those capabilities; it is not a fourth product capability.

Use the most specific topic skill for the user's current task. Handoff is expected when the task changes. For example, road reconstruction may finish in `torii-build`, count fitting then moves to `torii-calibrate`, a controller experiment moves to `torii-simulate`, and the completed comparison moves to `torii-report`.

## Execution Boundary

For executable work, read:

```powershell
torii workflows --json
torii workflows --scenario <ID> --json
```

The workflow catalog is the executable mapping. Each entry exposes its owning skill and a plugin-relative reference path. The host model selects from user intent and supplied evidence. Missing inputs remain `needs_input`; unknown scenarios or arguments remain `blocked`.

MCP and CLI output is observation, not final interpretation. Preserve child decisions such as `review_required` and `blocked`.

## Evidence Boundary

- Network load does not prove physical network correctness.
- Count fit does not uniquely identify OD demand.
- A successful simulation does not prove controller superiority.
- A completed-result review does not authorize a rerun.
- GUI or screenshot inspection is supporting review evidence, not performance evidence by itself.

Keep source authority, target year, comparison pairing, completion status, and non-identifiability explicit in the skill that owns the task.

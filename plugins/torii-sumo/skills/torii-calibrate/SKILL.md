---
name: torii-calibrate
description: Use when reconstructing traffic demand, binding detector or count observations, fitting route demand, calibrating a fixed SUMO network, or validating a sensor-based digital-twin replay.
---

# Torii Calibrate

Calibrate traffic on a fixed network. This skill owns detector/count constraints, route-demand reconstruction, observation binding, time-window matching, and replay validation. It does not silently rebuild roads to improve fit.

## Start Here

| Task | Load |
|---|---|
| Cached detector-demand workflow | `references/cached-detector-demand.md` |
| General detector-constrained demand reconstruction | `references/detector-constrained-demand-reconstruction.md` |
| Hamburg count fitting on a frozen network | `references/hamburg-count-calibration-workflow.md` |
| Hamburg Sandtorkai digital-twin replay | `references/hamburg-sandtorkai-digital-twin.md` |

## Rules

- Freeze and identify the road network before calibration.
- Treat detector counts as traffic observations and route constraints, not direct OD observations.
- Keep calibration and held-out validation evidence separate.
- Preserve detector meaning, spatial mapping, aggregation interval, comparison window, and source date.
- Report non-identifiability when several route or OD assignments fit the same measurements.
- Do not hide insertion backlog, teleports, unfinished vehicles, or missing detector coverage behind a good aggregate fit.
- If road geometry, lane permissions, or signal-device structure must change, hand off to `$torii-build` and recalibrate afterward.
- Use `torii workflows --json` when an executable catalog entry is needed.

## Output

State the fixed network, observations used, calibration variables, fit and validation evidence, unresolved identifiability limits, and the strongest supportable calibration claim.

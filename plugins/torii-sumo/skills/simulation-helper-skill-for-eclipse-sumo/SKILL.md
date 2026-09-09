---
name: simulation-helper-skill-for-eclipse-sumo
description: Use when planning, coding, debugging, auditing, comparing, or writing claims for Eclipse SUMO/TraCI traffic-signal experiments, including OSM/netconvert networks, TLS/NEMA, controllers, routes, demand, detectors, outputs, baselines, metrics, reproducibility, TDD changes, reusable field lessons, Hamburg road construction from reviewed construction drawings or OSM/MAP/aerial imagery, or traffic-count calibration on a fixed network.
---

# Torii SUMO Expert Skill

## Purpose

Use this skill to select SUMO work and interpret its evidence. The host model reads the executable catalog before choosing an entry. Load only the references needed for that choice.

Default loop:

```text
request + dated sources -> read catalog -> host selects scenario -> check inputs -> execute or follow guidance -> evaluate evidence
```

## Select Before Execution

The commands below use `torii` as shorthand. In an installed plugin cache, run
`uv run --isolated --frozen --script <plugin-root>/scripts/run_torii_sumo.py --cli`
followed by the command arguments. Resolve `<plugin-root>` from this skill's
location. This uses the plugin's locked environment and needs no repository
checkout or globally installed `torii` command. For example, append
`workflows --json` to read the catalog.

1. Read `torii workflows --json` before selecting a scenario. Use `--scenario ID` to inspect its current arguments and reference.
2. Match the user's objective, target year, primary source, existing artifacts, and requested action to the catalog description.
3. Read the selected entry's reference. Distinguish a `workflow` entry, a bounded `check`, a `stage`, and `guidance` without a function.
4. Record `user_request`, `scenario_id`, `reason`, and `arguments`. Preserve the original request and explain the choice from meaning and evidence.
5. Check the selection with `torii workflow selected selection.json --json`. Missing inputs remain `needs_input`; do not invent files or values.
6. For an authorized execution task, add `--execute`. A readiness result does not verify drawing contents or complete the selected work.
7. For `guidance`, read the reference and continue the requested reasoning or intake. Do not claim a function was executed.

The host model makes the semantic choice. Torii does not call another model API
or classify that selection again with keywords. `core/workflow_catalog.py` is
the only executable mapping; the reference tables below are reading guidance.
Do not replace an unknown scenario or invalid argument with another workflow.
Preserve `review_required`, `blocked`, and unresolved child results.

Both `inspect-only` and `ask-first` stop before execution, including the older
router. Use `torii netedit review <source.net.xml> <new-output-dir> <source-sha256>`
for a one-shot Windows review. Multi-step NetEdit operations belong to one
persistent MCP session, not separate CLI processes.

Keep road construction separate from demand fitting on a fixed network.
Planning an experiment does not request a simulation run. Reviewing existing
results does not request a rerun. A synthetic scene cannot replace a real
construction drawing. The user and source years govern each choice; an
illustrative 2013 test does not change a supplied 2022 drawing's year.

## Start Here

Use the catalog's reference first. This table selects further reading, not executable function names.

| Scenario | Load | Expected output |
|---|---|---|
| SUMO environment, executable toolchain, or runnable smoke proof is missing | `references/preflight-sumo-environment.md` | `Environment Preflight` record and pass/fail route |
| Torii MCP execution, installable plugin use, MCP tool output, or feedback from a SUMO run | `references/mcp-tool-routing.md` | `MCP Tool Use Record`, feedback diagnosis, and claim boundary |
| Direct NetEdit mouse/keyboard editing with screenshot feedback | `references/mcp-tool-routing.md` plus `references/osm-to-sumo-workflow.md` | one hash-bound diagnostic candidate session, atomic action evidence, persisted-vs-live state distinction, and blocked automatic promotion |
| OSM-to-SUMO network construction, imported-network cleanup, road-detail planning, reference-matched network building, or Netedit/HTML review artifacts | `references/osm-to-sumo-workflow.md` | OSM cleanup workflow contract, planning gate, reality/TLS gates, connectivity, routeability, HTML review, Netedit launch, and claim boundary |
| Intersection-type recognition before joining nodes, channelization reconstruction, owner selection, or signal binding; especially compound, staggered, or multi-owner junctions | `references/composable-intersection-classification.md` plus `references/osm-to-sumo-workflow.md` | finite composable archetype, MAP movement/stop-line evidence, separated raw-node/join/core/owner/controller counts, and review-only execution hint |
| Signal-device recognition before lane/movement/group binding or controller design; especially German or European OCIT-C evidence | `references/composable-signal-device-classification.md` plus `references/mcp-tool-routing.md` | Germany-first finite device composition, physical-head/group separation, visual/acoustic/tactile modality, source hash, and blocked automatic binding/control gates |
| Region-specific map/TLS reality checks, detector lane mapping, field-data sensor alignment, or background visualization | `references/model-osm-detectors.md` | map baseline record, TLS review evidence, detector alignment gates, and diagnostic background visualization boundary |
| Public OSM import libraries, Overpass robustness, offline PBF import, SUMO OSM scripts, OpenDRIVE conversion, or source-code reuse decisions | `references/osm-source-patterns.md` | source-pattern map, integration ladder, no-vendoring boundary, and region-aware temporal baseline |
| Detector-constrained SUMO demand reconstruction from real count sensors, route priors, route-incidence matrices, routeSampler residual correction, or month-long count-matched validation | `references/detector-constrained-demand-reconstruction.md` | workflow contract, detector/route/time-bin gates, public-data boundary, residual-correction ladder, and completion-first validation record |
| Hamburg official count/signal APIs, the fixed Am Sandtorkai three-intersection corridor, busiest complete Saturday two-hour selection, or digital-twin replay | `references/hamburg-sandtorkai-digital-twin.md` plus `references/detector-constrained-demand-reconstruction.md` | official-source manifest, fixed-scope/window record, MAP-to-SUMO bindings, routeSampler demand, E1/E2/TLS replay evidence, and non-identifiability boundary |
| Hamburg road construction from reviewed drawings with supporting OSM/Google Maps, including historical target years, or the existing MAP/KML and aerial mode | `references/hamburg-five-intersection-aerial-workflow.md` | one `torii hamburg build-network` request, drawing-led or MAP/aerial input mode, dated sources, and separate construction checks |
| Hamburg count fitting or demand reconstruction on an already checked road network | `references/hamburg-count-calibration-workflow.md` | fixed network hash, signal/count bindings, plausible demand, and independent comparison evidence |
| Ongoing project, unclear progress, repo/logs/outputs provided, or "what next?" | `references/route-project-workflow.md` | `Project Control Screen` and next-step plan |
| New, vague, or assumption-heavy experiment | `references/interactive-experiment-intake.md` | one-question-at-a-time intake, recommended answers, and readiness route |
| Confirmed experiment intake ready for planning | `references/plan-experiment.md` | `Experiment Readiness Record`, then `SUMO Experiment Plan` |
| SUMO/TraCI failure, suspicious behavior, warnings, or broken run evidence | `references/route-project-workflow.md` plus `references/develop-and-verify-code.md` | root-cause hypothesis, next probe, fix/rerun/demotion |
| Controller, parser, runner, validator, or audit-code change | `references/develop-and-verify-code.md` | RED/GREEN/REFACTOR or explicit `test-after` record |
| Controller/TLS/NEMA/TraCI boundary question | `references/audit-sumo-controllers.md` | controller identity, API boundary, and missing evidence |
| Applying controller families inspired by sumolights, including max-pressure, Webster, SOTL, fixed-time, actuated, or custom TLS control | `references/sumolights-controller-patterns.md` plus `references/audit-sumo-controllers.md` | `Controller Application Plan` and `Controller Identity Record` |
| Mechanism-isolated corridor perturbation comparison, localized impact-signal tests, or multi-baseline controller evidence | `references/compare-corridor-perturbations.md` | controlled-scope experiment logic, paired metrics, negative controls, and claim boundary |
| SUMO semantics, official/forum lessons, or public-code pattern | `references/learn-sumo-knowledge.md` | source-bounded lesson and evidence requirement |
| Results, metrics, baseline comparison, or paper/report claim | `references/evaluate-and-report-results.md` | evidence class and allowed/prohibited claim wording |
| User found a fix this skill missed | `references/capture-field-lesson.md` | privacy-safe field lesson candidate; ask before persisting |
| Public release or repository exposure check | `references/release-project.md` | release checklist and residual risk |

If a target/current-state/deviation cannot be inferred, switch to the intake path before running experiments or endorsing claims.

## Core Rules

- Load the minimum reference set for the scenario; do not bulk-load every file.
- Keep Hamburg road construction separate from count calibration. Use raw source inputs for `build-network`; missing counts or historical signals do not prevent road construction. Start calibration only when requested, after the road network has been checked and frozen.
- When a construction drawing leads the task, preserve its reviewed lane counts, uses, and connections. Use maps only for missing details. Preserve the user's target year; newer maps do not override a historical scenario. Record missing Google Maps references as not supplied.
- Preserve the one-sentence workflow. Infer safe defaults, run bounded diagnostic steps, and ask only truly blocking questions; missing map/TLS reality evidence should block clean/experiment-ready claims without preventing construction, routeability checks, SUMO-GUI, or Netedit review artifacts.
- Confirm missing experiment assumptions before formal execution or comparison.
- Prove the SUMO environment before formal experiment work when `sumo`, `duarouter`, `SUMO_HOME`, Python, `traci`, or output generation has not been verified.
- Separate what SUMO loaded, what the controller did, what outputs were written, what warnings/failures occurred, and what claim is supportable.
- Compare controllers only with paired route, demand, seed, horizon, outputs, and completion criteria.
- Do not use GUI inspection, clean execution, or arrived-only metrics as sufficient evidence.
- Open an existing `.net.xml` through Torii's CLI launcher or `netedit -s <absolute-net-file>` (`--sumo-net-file` is equivalent). For snapshots, use `torii netedit review` or the hash-bound `netedit_background_review.py` path. Do not use desktop clicking to choose the network file. Use the persistent NetEdit MCP session only for explicitly requested interactive editing, and keep all operations in that same server process.
- If completion differs across methods, report completion/unfinished/teleport status before travel-time, waiting-time, or delay averages.
- Treat bad metrics, warnings, teleports, unfinished vehicles, and controller logs as feedback signals. Diagnose what the metric implies before changing code, routes, networks, signal plans, or controller parameters.
- Use these claim labels: `formal-evidence`, `diagnostic-demo`, `stress-diagnostic`, `construction-invalid`, `claim-overreach`, `blocked`.
- At the end of each SUMO experiment or experiment-code pass, check whether the run produced a reusable SUMO/TraCI lesson. If yes, update the relevant skill reference instead of leaving the lesson only in the chat.

## Reference Map

Load these only when the scenario requires them:

- Ongoing project routing, state screening, or "what next?": `references/route-project-workflow.md`.
- Torii MCP execution, tool-output interpretation, feedback diagnosis, and installable plugin behavior: `references/mcp-tool-routing.md`.
- SUMO/TraCI failure, suspicious behavior, warnings, or broken run evidence: start with `references/route-project-workflow.md`; use `references/develop-and-verify-code.md` before code, parser, runner, validator, or controller changes.
- SUMO executable environment, `SUMO_HOME`, Python tooling, or smoke-test proof: `references/preflight-sumo-environment.md`.
- Interactive intake for vague, ambitious, or assumption-heavy experiments: `references/interactive-experiment-intake.md`.
- Confirmed experiment intake and planning: `references/plan-experiment.md`.
- Code implementation, TDD, and completion evidence: `references/develop-and-verify-code.md`.
- OSM-to-SUMO construction, imported-network cleanup, road-detail planning, reference-matched construction, routeability, topology/TLS cleanup, HTML review, and Netedit launch: `references/osm-to-sumo-workflow.md`.
- Intersection-type recognition before node joining, channelization, owner reconstruction, or TLS binding: `references/composable-intersection-classification.md`; keep the archetype separate from every materialization strategy.
- German/European signal-device recognition before lane, movement, signal-group, or controller binding: `references/composable-signal-device-classification.md`; keep physical heads, display outputs, logical groups, runtime state, and control methods separate.
- Region-specific map/TLS reality checks, detector lane repair, field-data sensor alignment, and background visualization: `references/model-osm-detectors.md`.
- Public OSM source patterns from OSMnx, OSMNet, pyrosm, SUMO osmGet/osmBuild, or osm-to-xodr: `references/osm-source-patterns.md`.
- Detector-constrained SUMO demand reconstruction from real sensor counts, routeSampler residual correction, detector-route incidence matrices, anti-replay route priors, workflow gates, public-data boundaries, and month-long validation: `references/detector-constrained-demand-reconstruction.md`.
- Hamburg SensorThings counts/signals, the fixed Am Sandtorkai three-intersection preset, complete Saturday two-hour selection, MAP/MAPEM lane binding, routeSampler demand, TLS event replay, and non-identifiability: `references/hamburg-sandtorkai-digital-twin.md`.
- Hamburg construction drawings with supporting maps, historical road scenarios, or MAP/KML with geographic aerial images: `references/hamburg-five-intersection-aerial-workflow.md`.
- Hamburg traffic-count fitting on a checked, fixed network, using the existing signal/count/demand commands: `references/hamburg-count-calibration-workflow.md`.
- SUMO semantics, official/forum lessons, and public-code patterns: `references/learn-sumo-knowledge.md`.
- NEMA/TLS/TraCI controller identity and API-boundary checks: `references/audit-sumo-controllers.md`.
- Controller-family application patterns inspired by sumolights, without copying GPL source: `references/sumolights-controller-patterns.md`.
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

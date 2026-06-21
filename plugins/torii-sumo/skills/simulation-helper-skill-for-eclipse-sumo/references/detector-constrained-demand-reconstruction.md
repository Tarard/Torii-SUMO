# Detector-Constrained Demand Reconstruction

Use this reference when real detector counts are the main evidence source for building SUMO demand. The goal is to reconstruct plausible routes and departures whose simulated detector outputs match the field count windows while preserving route realism, SUMO completion, and claim boundaries.

## Core Contract

Detector counts are route constraints, not OD observations. A valid reconstruction creates vehicles that:

- enter from plausible boundary, arterial, bridge, or local-access source edges;
- traverse mapped detector edges in the declared direction;
- leave the modeled network or terminate at plausible local sinks;
- preserve the observed time-bin shape, especially AM and PM peaks;
- produce SUMO detector outputs comparable to the real detector rows;
- report unfinished, waiting, teleported, and collided vehicles.

Creating vehicles directly at detector edges is only a detector smoke test. Do not call that OD reconstruction.

## Tool Boundary

This reference is a workflow and audit protocol. It can guide Torii, Codex, Claude, or a human reviewer, but it is not proof that the current plugin can automatically run the full reconstruction.

Before claiming automated support, verify the required tool path exists for:

```text
detector_manifest_generation:
route_candidate_generation:
route_detector_incidence:
routeSampler_or_optimizer_run:
SUMO_detector_output_generation:
detector_comparison:
completion_summary:
```

If one of these is manual, label the result as `diagnostic-demo` or `construction-invalid` until the manual step is documented and replayable.

## Public Data Boundary

Do not commit raw proprietary detector feeds, private station ids, unmasked precise sensor locations, or unpublished operational records to a public repository.

For public examples, use one of these:

- synthetic counts;
- openly licensed aggregate counts;
- anonymized detector ids and coarsened locations;
- manifests that show schema and mapping logic without exposing raw field data.

Commit lightweight manifests, comparisons, and audit CSVs. Keep large SUMO XML, routeSampler logs, raw feeds, and non-public sensor metadata local unless the dataset is explicitly cleared for release.

## Required Target

Define the target before generating vehicles:

```text
time_window:
detector_set:
detector_mapping:
network_version:
route_candidate_set:
field_count_interval:
validation_interval:
accepted_error:
completion_threshold:
data_release_status:
```

The target is not "the same number of vehicles as the detector table." The target is "vehicles travel through valid SUMO routes and the detector outputs match the field count windows, with completion and failure status reported."

## Validity Gates

Run these gates in order:

1. Detector alignment.
   - Map every real detector to SUMO lane, edge, position, direction, and mapping confidence.
   - Treat paired detectors on a two-way road as one detector per direction, not duplicate evidence.
   - If a detector falls on a deleted segment, restore the route-relevant segment or mark the detector out of scope.

2. Time-window alignment.
   - Use exact absolute dates and local clock windows.
   - Separate background days, incident days, holidays, roadworks, weather disruptions, and event days.
   - Keep hourly or sub-hourly bins for commuter peaks; do not rely only on full-day totals.

3. Route-candidate validity.
   - Candidate routes should enter from plausible sources, traverse detector edges, and leave or terminate at plausible sinks.
   - Reject detector-entry replay as OD evidence unless the run is explicitly a detector smoke test.
   - Each detector edge should be reachable by at least one candidate route.

4. Count constraint construction.
   - Aggregate lane detectors to the constraint level used by the sampler, usually edge counts or edge-relation counts.
   - Preserve direction. Do not combine opposing directions unless the real data is explicitly directionless.
   - Keep a manifest linking real count rows, detector ids, SUMO edges/lanes, and generated constraint files.

5. Simulation completion.
   - A detector match is not valid if most vehicles remain waiting, running, or teleported without disclosure.
   - Report completion before travel time, delay, controller performance, or demand-quality claims.

## Field Pattern: Sensor-Only Demand Reconstruction

When the only field evidence is fixed detector counts, reconstruct route support first and OD second:

1. Treat each detector row as a directional route-incidence constraint.
   - A detector contributes one equation to the route-volume fit for its declared time bin.
   - Paired detectors on opposite directions are two constraints.
   - Multiple sensor systems should remain separate manifests until a documented merge rule is applied.

2. Build plausible OD support from network topology.
   - Sources should usually be boundary approaches, bridge approaches, arterial entrances, or known local access points.
   - Sinks should let vehicles leave the cropped study area or terminate at plausible internal destinations.
   - A vehicle that starts on the detector edge is a smoke-test vehicle, not reconstructed OD.

3. Fit route volumes by time bin.
   - Build a route-detector incidence table where `A * x` approximates detector counts `y`.
   - Use nonnegative route volumes and regularization for route diversity, background-flow shape, OD priors, and hour-to-hour smoothness when available.
   - Preserve baseline and calibrated stages so residual correction remains auditable.

4. Use residuals as construction feedback.
   - Underflow usually means missing route candidates, deleted connectors, wrong direction mapping, or detectors outside scope.
   - Overflow usually means over-broad route priors, merged opposing directions, or duplicated detector constraints.
   - Good detector fit with poor completion usually means insertion backlog, route collapse, insufficient clearance, or unrealistic departure concentration.

5. Validate the generated vehicles in SUMO.
   - A fitted route file is not evidence until SUMO writes readable detector comparison and completion outputs.
   - Store exact hourly aggregation fields so daily MAE/RMSE can be recomputed from sums rather than rounded hourly averages.
   - Keep teleports, collisions, waiting vehicles, running vehicles, and route diversity attached to the detector-fit report.

This pattern supports detector-constrained plausible demand reconstruction. It does not prove true OD without external OD evidence such as trajectories, travel times, surveys, boundary counts, or assignment calibration.

## RouteSampler Ladder

Use a small closed-loop ladder:

1. One-hour smoke: build expected counts, run routeSampler or the declared optimizer, run SUMO, compare detector output.
2. Peak-hour stress: repeat for AM peak, PM peak, and one low-flow hour.
3. One-day validation: run 24 hourly batches and aggregate detector error plus completion.
4. Multi-day validation: split weekdays, weekends, holidays, incident/event days, and background days.
5. Month validation: run all days with a manifest and summarize failures before claiming match quality.

Stop and repair when:

- route coverage misses a detector edge;
- SUMO inserts far fewer vehicles than the sampler generated;
- waiting or running vehicles persist at the end of an hourly run;
- teleports are nonzero in a setting where congestion is not the phenomenon under study;
- residuals concentrate on one detector edge or one direction;
- the calibrated route set collapses to too few distinct routes and creates insertion backlog.

## Month-Long Daily Workflow

For a month of real detector data, treat each day as a replayable evidence unit rather than one opaque batch:

1. Run one absolute calendar day at a time.
   - Use explicit local timestamps, for example `2024-03-15 00:00:00` to `2024-03-16 00:00:00`.
   - Keep detector mapping, network version, route-candidate file, clearance window, and calibration knobs fixed across days unless intentionally versioned.
   - Do not merge incident, holiday, event, roadwork, and background days into one quality claim.

2. Generate paired stages for every day.
   - Baseline: raw route candidates with no residual supplement.
   - Calibrated: the same candidate base plus named residual-correction knobs.
   - Keep both stages; the baseline is the residual diagnosis and protects against hiding mapping or route-prior bias.

3. Validate by hour before validating by day.
   - Preserve 24 hourly detector comparison files per stage.
   - Use hourly bins to expose AM peak, PM peak, night, and low-flow behavior.
   - Aggregate to daily metrics only after every expected hour has readable detector comparison and SUMO summary.

4. Keep exact audit fields.
   - Store per-hour absolute-error sums, squared-error sums, row counts, measured totals, expected totals, and completion fields.
   - Recompute daily MAE/RMSE from exact hourly sums; do not trust averages of rounded hourly metrics.

5. Commit lightweight evidence, not heavy runtime products.
   - Commit manifests, detector comparison CSVs, summaries, and hourly audit CSVs.
   - Keep large route files, detector XML, summary XML, tripinfo XML, routeSampler stdout, mismatch XML, and supplement internals local unless needed for a disputed claim.

## Residual-Correction Pattern

Use two stages when routeSampler or another sampler undercounts detectors:

1. Baseline stage.
   - Run the raw candidate route set with no residual supplement.
   - Save detector comparison as the baseline residual record.
   - Record route count, detector MAE/RMSE/max residual, bias, GEH<5, and SUMO completion.

2. Calibrated stage.
   - Reuse the same time window, network, detector mapping, seed, and route candidate base.
   - Enable optimization, vehicle minimization, or supplements only as named calibration knobs.
   - Add supplementary routes only for baseline underflows that pass explicit absolute and relative deficit thresholds.
   - Compare against the same detector set and report both improved detector fit and any new teleports or backlog.

Do not supplement overflows by deleting arbitrary through routes unless the route-candidate model explains why those routes are invalid.

## Route Diversity Fallback

Detector-perfect calibration can still be invalid when flow collapses into too few routes:

```text
baseline: many distinct routes, worse detector MAE, SUMO completes
calibrated: few distinct routes, excellent detector MAE, large backlog or crash
```

When this happens:

1. Keep the baseline comparison as the residual source.
2. Try a diversity-preserving fallback, such as supplementing underflow routes without full optimization or vehicle minimization.
3. Stitch the fallback hour into a hybrid hourly manifest only if it has readable detector comparison and SUMO summary outputs.
4. Report the tradeoff: detector MAE/RMSE/GEH improvement versus teleports, unfinished vehicles, collisions, and route diversity.

Do not claim the detector-perfect version is better if it crashed, left a large insertion backlog, or reduced route support to an implausibly small set.

## Metrics To Report

For detector fit:

```text
expected_total:
measured_total:
edge_rows:
MAE:
RMSE:
max_abs_error:
signed_bias:
GEH_lt5_percent:
top_residual_edges:
```

For simulation completion:

```text
loaded:
inserted:
arrived:
running_at_end:
waiting_for_insertion:
teleported:
collisions:
completion_ratio:
horizon:
clearance_seconds:
```

Evidence class:

- `diagnostic-demo`: small-window or pilot reconstruction.
- `stress-diagnostic`: intentionally congested or teleport-prone window.
- `formal-evidence`: full declared calendar set, fixed inputs, reported completion, and no hidden missing files.
- `construction-invalid`: detector files, route files, SUMO outputs, or mapping gates failed.

## Replayable Evidence Package

A replayable reconstruction should preserve:

```text
detector_manifest:
source_sink_manifest:
route_candidate_manifest:
route_detector_incidence:
time_bin_count_constraints:
route_volume_solution:
generated_route_file:
sumo_detector_output:
detector_comparison:
completion_summary:
top_residuals:
data_release_status:
```

A fresh checkout should be able to audit the published summary from committed lightweight CSVs or rerun the commands from committed manifests and cleared input data.

## Claim Boundary

Allowed claim:

```text
The generated SUMO demand is detector-constrained and reproduces the real detector counts for the declared detector set, time windows, network version, and completion criteria.
```

Treat detector-matched routes as a plausible demand reconstruction, not as proven true OD unless supported by additional OD priors such as travel times, trajectory data, boundary counts, surveys, or assignment evidence.

## Common Mistakes

- Matching detector totals by creating vehicles at detector edges, then treating that as OD evidence.
- Comparing a 24-hour total while missing AM/PM peak shape.
- Calibrating on incident days and calling the result normal background flow.
- Combining paired opposite-direction sensors into one count.
- Reporting detector MAE without loaded/inserted/arrived/waiting/teleport status.
- Publishing raw detector feeds or private station metadata in a public demo repository.
- Treating exact detector count matching as proof of true OD.

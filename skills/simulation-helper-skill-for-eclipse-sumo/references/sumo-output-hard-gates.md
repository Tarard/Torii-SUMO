# Eclipse SUMO Output Hard Gates

Use this when deciding whether an Eclipse SUMO run can support formal evidence.

## Required Runtime Artifacts

A formal run should provide:

- SUMO version and exact command;
- network file and stable network identifier or hash;
- route/demand files and stable demand identifier or hash;
- additional files, including TLS output configuration;
- controller code version or stable identifier;
- random seeds and scenario parameters;
- `summary.xml`;
- `tripinfo.xml`;
- SUMO log;
- TLS state, switch-state, switch-time, or program outputs where traffic lights are relevant;
- detector outputs when detector behavior is claimed;
- controller event logs when a custom controller acts through TraCI;
- explicit completion policy: natural completion, fixed horizon, timeout, or diagnostic stop.

## Official Output Anchors

- TLS outputs: https://sumo.dlr.de/docs/Simulation/Output/Traffic_Lights.html
- Summary output: https://sumo.dlr.de/docs/Simulation/Output/Summary.html
- TripInfo output: https://sumo.dlr.de/docs/Simulation/Output/TripInfo.html
- Statistic output: https://sumo.dlr.de/docs/Simulation/Output/StatisticOutput.html

## TLS Outputs

Use additional files for SUMO-native TLS outputs:

```xml
<additional>
  <timedEvent type="SaveTLSStates" source="TLS_ID" dest="tls_states.xml"/>
  <timedEvent type="SaveTLSSwitchStates" source="TLS_ID" dest="tls_switch_states.xml"/>
  <timedEvent type="SaveTLSProgram" source="TLS_ID" dest="tls_program.xml"/>
</additional>
```

Audit:

- `tlsState.state` length equals the controlled link-index count;
- `phase` is valid for the active `programID`;
- program changes are accounted for;
- TLS output exists for every controller used in formal evidence;
- custom TraCI logs are labeled as controller logs, not SUMO-native TLS output.

## Summary Output

`--summary <FILE>` writes simulation-wide step data. Audit:

- inserted;
- arrived or ended;
- waiting;
- halting;
- collisions;
- teleports;
- discarded;
- duration.

For completion-aware evaluation, the final summary step must identify:

- planned demand denominator used by the paper/report;
- inserted vehicles;
- arrived vehicles;
- running vehicles;
- vehicles waiting for insertion;
- discarded vehicles;
- teleports and collisions.

If the experiment is not intentionally fixed-horizon, formal performance evidence should normally run until no evaluated vehicles remain running or waiting. For a completion-full claim, require a planned denominator and `inserted == arrived == planned_demand`, final running/waiting counts of `0/0`, and zero unfinished `tripinfo` records.

## TripInfo Output

`--tripinfo-output <FILE>` writes per-vehicle data when vehicles arrive. Add `--tripinfo-output.write-unfinished` when unfinished vehicles matter. Audit:

- depart delay;
- arrival;
- duration;
- route length;
- waiting time;
- vaporized or unfinished vehicles where present.

Do not compute model superiority from arrived-only trip averages when different controllers finish different shares of the demand. Compare completion rate and backlog first, then compare travel-time, waiting-time, and delay metrics for the same completion policy.

For metric definitions and denominators, read `evaluation-metrics-and-completion.md`.

For fixed end-time comparisons with unfinished vehicles, also read `sumo-official-operational-lessons.md` and prefer `--statistic-output`, `--duration-log.statistics`, and `--tripinfo-output.write-unfinished`.

## Controller-Signal Use Evidence

When a runner observes forecasts, telemetry, detector values, or oracle schedules for multiple controllers, keep "available to the experiment" separate from "used by this controller."

Audit:

- controller/solver events should explicitly mark whether a signal was consumed, e.g. `forecast_used_by_controller=true`;
- aggregate tables should count signal-use evidence only for rows where the event marks controller use;
- rows that merely share the same runner or observation loop should not inherit telemetry, forecast, detector, or oracle-use claims;
- if the signal affects a reported model mechanism, include event counts and max/min observed values beside performance metrics.

## Fixed-Schedule Demand Evidence

When a paper/model claims fixed AMOD arrivals, do not infer it from deterministic demand generation alone. Require a machine-readable schedule audit in metadata or hard-gate output:

- schedule policy, such as `per_route_fixed_interval`;
- AMOD vehicle count and per-stream counts;
- per-stream departure intervals and interval variants/tolerance;
- boolean validity and explicit reasons when invalid.

Demote fixed-schedule AMOD claims when intervals are merely spread or approximately distributed without a fixed-interval audit.

## Formal Rejection or Demotion Signals

Demote or reject formal evidence when any remain unresolved:

- SUMO warnings, errors, or fatal messages;
- missing outputs;
- TLS state length mismatch;
- missing route connections;
- no-detector warnings for claimed detector-controlled behavior;
- collisions, teleports, discarded vehicles, or unexplained vaporization;
- low insertion or arrival ratio relative to the claim;
- missing planned demand denominator for a formal comparison;
- demand not realized;
- nonzero final running/waiting backlog in a natural-completion run;
- unfinished vehicles ignored;
- unfinished `tripinfo` records in a completion-full claim;
- fixed AMOD arrival claims without a passing schedule audit;
- arrived-only averages used despite unequal completion rates;
- fixed-horizon truncation reported without completion rate and backlog;
- route errors, insertion backlog, teleports, or random seeds treated as background details;
- output files parsed before SUMO/TraCI shutdown completes;
- observed signals reported as controller-used without controller/solver event evidence;
- runtime exceeds the control interval for real-time claims;
- GUI-only evidence.

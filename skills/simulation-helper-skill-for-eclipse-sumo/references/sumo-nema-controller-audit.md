# Eclipse SUMO NEMA Controller Audit

Official NEMA documentation: https://sumo.dlr.de/docs/Simulation/NEMA.html

## Controller Identity

Require direct evidence before calling a controller NEMA:

- loaded `tlLogic type="NEMA"`;
- NEMA phase numbers via phase `name`;
- ring/barrier configuration;
- phase `minDur`, `maxDur`, `yellow`, and `red`;
- split, offset, coordinated mode, force-off, recall, detector, and controller-type parameters when claimed;
- phase-name-to-controlled-link mapping against the actual loaded `net.xml`;
- runtime yellow/all-red transition intervals from TLS state output when standard phase transitions are claimed;
- runtime evidence from SUMO outputs or controller metadata.

Do not infer NEMA identity from file names, variable names, class names, or a paper section title.

## Timing and Parameters

Audit:

- `minDur`: minimum green;
- `maxDur`: maximum green or split-derived green in coordinated mode;
- `yellow`: yellow time;
- `red`: red clearance;
- `fixForceOff`: fixed vs floating force-off behavior;
- `controllerType`: TS2 vs Type 170 offset semantics;
- `latchingDetectors` and cross-phase switching parameters when used;
- `ignore-errors`: formal evidence should reject or demote runs that rely on it.

## NEMA TraCI Timing Calls

SUMO exposes NEMA-specific timing updates:

- `traci.trafficlight.setNemaOffset`
- `traci.trafficlight.setNemaMaxGreens`
- `traci.trafficlight.setNemaSplits`
- `traci.trafficlight.setNemaCycleLength`

Official docs state timing updates in the NEMA controller happen after the current cycle ends. Claims about immediate timing effects need runtime evidence.

Do not treat controller log labels such as `solver_success`, `objective_value`, or
`optimizer` as sufficient evidence of mathematical optimization. Inspect the
controller path: if the timing plan is computed by a proportional
queue-plus-forecast allocation and then written through NEMA timing APIs, describe
it as a NEMA timing allocation heuristic/proxy even when the audit schema records
objective-like fields.

For a MILP-backed NEMA timing claim, first identify the controlled variables. In
a standard fixed-order NEMA experiment, the controller should not claim arbitrary
phase-sequence control. The normal NEMA-compatible boundary is fixed ring/barrier
order plus fixed cycle and fixed max-green upper bounds, with the optimizer
choosing split allocation. In that case the event log should identify the direct
timing adapter, record split decision variables such as
`milp_timing_pair_splits`, preserve the raw solver status, and mark
fallback/proportional allocation paths as fallback. If the code solves an
arbitrary `phase_by_step` plan and then converts it into splits, label it as an
intermediate phase-sequence-to-timing bridge rather than the final NEMA timing
model.

Do not require `milp_phase_plan` to be nonempty for a direct NEMA split-allocation
MILP. For that model, an empty `milp_phase_plan` is expected; the evidence should
instead include the direct split variables, fixed-cycle metadata, fixed max-green
upper-bound metadata, and the actual NEMA timing API calls. If the event log
cannot distinguish direct MILP-derived splits from proportional timing, demote
the claim until the logging and hard gate are fixed.

## Max Recall Timing Trap

Official SUMO NEMA semantics state that setting `maxRecall` for all phases makes the controller operate like fixed time with phase `maxDur`. Do not reuse an all-phase max-recall baseline configuration for a controller that claims dynamic NEMA split, max-green, or cycle optimization.

Treat an all-phase `maxRecall` SUMO NEMA baseline as fixed-time-like NEMA,
not as max-pressure, QMP, actuated control, or an optimization baseline. The
loaded program is still `tlLogic type="NEMA"`, so the project label should be
`SUMO NEMA max green fixed time baseline`, not generic `static` unless the
loaded `tlLogic` is actually `type="static"`. In reports, state that all phases
are permanently recalled and the realized green times are driven by phase
`maxDur`; this baseline mainly tests NEMA construction and demand completion,
not adaptive signal logic.

Audit dynamic NEMA timing claims with both controller-side and SUMO-side evidence:

- controller log records `setNemaCycleLength`, `setNemaMaxGreens`, `setNemaSplits`, or `setNemaOffset` calls;
- loaded `tlLogic type="NEMA"` does not lock all phases with `maxRecall` unless the intended claim is fixed/max-recall NEMA;
- split strings are ring/barrier consistent, for example phases 2/6 and 4/8 stay paired when the modeled intersection serves those paired movements;
- phase names map to intended controlled-link streams after parsing SUMO `connection` `linkIndex` entries;
- runtime TLS states collapse into legal green -> yellow -> all-red -> opposite-green transition intervals with the configured yellow and red durations;
- SUMO TLS state output shows actual green-duration variation after collapsing per-step `tlsState` rows into contiguous intervals;
- if the controller log changes but TLS green durations remain fixed, demote the timing optimization claim until the configuration is fixed.

## SUMO Actuated Gap Baseline

SUMO's traditional gap-based actuated controller is a separate baseline identity,
not NEMA and not MPC, unless the loaded program is explicitly `type="NEMA"`.
When adding it as a baseline:

- use `<tlLogic type="actuated">` and green phases with `minDur` and `maxDur`;
- include or audit actuated parameters such as `max-gap`, `detector-gap`,
  `passing-time`, `show-detectors`, and detector length;
- label controller events as SUMO-native actuated/gap control, not max pressure,
  max recall, or optimizer output;
- do not run NEMA phase-mapping hard gates as a claim requirement for this
  baseline;
- still require clean SUMO execution, TLS outputs, completion, and no detector
  warnings before using it as formal comparison evidence.

If SUMO emits a warning like `minDur ... is too short for a detector gap`, treat
the actuated baseline as invalid for formal comparison until the detector
configuration is adjusted. A smaller `detector-gap` can be the right fix for a
compact synthetic intersection where the default 2 s detector distance places
detectors too far upstream for the configured `minDur`.

## Demotion Rules

Classify as `diagnostic-demo` or `claim-overreach` when:

- the controller uses `setPhase` on a program that is not evidenced as SUMO NEMA;
- direct state override changes the program to an online state;
- all phases are locked by `maxRecall` while the claim says timing/split optimization;
- `ignore-errors=true` is needed;
- timing errors are ignored;
- detector warnings remain unresolved;
- output does not show actual NEMA runtime behavior;
- phase names do not map to the intended controlled-link streams;
- yellow/all-red runtime transition intervals do not match the configured NEMA clearance values;
- timing API calls are logged but actual TLS green-duration variants are not observed.

## Source Anchors

- NEMA docs: https://sumo.dlr.de/docs/Simulation/NEMA.html
- NEMA source path: `src/microsim/traffic_lights/NEMAController.cpp`
- Traffic-light docs: https://eclipse.dev/sumo/docs/Simulation/Traffic_Lights.html

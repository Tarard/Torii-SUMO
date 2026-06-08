# TDD for SUMO/TraCI Code

Use this reference when implementing or modifying code around SUMO/TraCI experiments: traffic-signal controllers, TLS phase mapping, metric parsers, route or config generation, batch runners, validators, plotting/export scripts, or audit utilities.

Core rule:

```text
No production experiment code before a failing test or reproducible failing probe.
RED -> GREEN -> REFACTOR -> verification record
```

Do not confuse TDD `GREEN` with a traffic-light green state. TDD `GREEN` means the test suite passes after the minimal implementation.

## When TDD Is Required

Use RED -> GREEN -> REFACTOR for:

- new TraCI controller behavior;
- bug fixes in controller logic, metric parsing, output paths, route generation, detector mapping, or batch orchestration;
- changes that affect reported metrics, baseline comparison, simulation completion, random seeds, or output files;
- refactoring code that drives SUMO or interprets SUMO artifacts.

Ask the user before skipping TDD for:

- throwaway exploration;
- generated examples that will not be reused;
- docs-only changes;
- configuration-only edits where there is no executable code path.

If TDD is skipped, mark the result `diagnostic-only` or `test-after`, not formal engineering evidence.

## Test Ladder

Prefer the lowest layer that can catch the behavior:

1. Pure unit tests: XML parsing, metric formulas, phase-state mapping, pressure calculation, output filename generation.
2. Controller tests with a fake TraCI facade: decision logic, API calls, phase index selection, detector reads, fallback behavior.
3. Minimal SUMO integration tests: tiny network/config/route fixture, exact command, expected output artifact, warnings, and completion signal.
4. Batch reproducibility tests: paired seeds, paired demand, paired horizons, unique output paths, and summary/tripinfo/edgeData consistency.

Do not start with a full research batch when a unit or tiny integration fixture can expose the behavior.

## RED: Write the Failing Test First

Create the smallest test that describes the desired behavior.

Good RED examples:

- A metric parser rejects arrived-only average travel time when completion rates differ.
- A max-pressure decision test expects a specific phase from fixed lane counts.
- A TLS mapping test proves a phase state gives green only to the intended movements.
- A batch runner test fails when two controllers would write to the same output path.
- A route-generation test fails when invalid/discarded demand is silently ignored.

Run the exact test command and confirm:

- it fails before implementation;
- it fails for the expected reason;
- it is testing behavior, not only a mock call count;
- it can be rerun by another agent or reviewer.

If the test passes immediately, it is not a valid RED. Tighten the assertion or choose the missing behavior.

## GREEN: Minimal SUMO/TraCI Implementation

Write only enough code to pass the failing test.

Keep GREEN narrow:

- no unrelated refactor;
- no parameter sweep;
- no demand, seed, or horizon change bundled with logic change;
- no GUI-only validation;
- no output parser changes hidden inside controller changes.

If a fake TraCI facade is used, keep it behavior-facing: it should record commands, expose detector/phase values, and fail on unsupported calls. Avoid tests that only prove the fake was called.

Use real SUMO integration only when simulator semantics matter. Record the SUMO command, version, input files, output files, warnings, teleports, unfinished vehicles, and natural completion condition.

## REFACTOR: Clean Without Changing Behavior

Refactor only after the test is green.

Allowed:

- rename unclear controller helpers;
- extract parser functions;
- remove duplication in batch setup;
- isolate SUMO subprocess, TraCI connection, and artifact parsing boundaries.

Not allowed:

- change demand, controller policy, metric definitions, or evidence scope during refactor;
- add a second behavior without a new RED test;
- broaden claims because code is cleaner.

Run the same tests after refactor. If behavior changes, return to RED.

## SUMO-Specific Test Fixtures

Prefer small, inspectable fixtures:

- XML snippets as strings for parser and TLS-state tests.
- Temporary files for route/config/additional-file tests.
- Fake TraCI objects for controller decision tests.
- Tiny SUMO networks only when netconvert, insertion, routing, or traffic-light semantics are part of the claim.

For real SUMO tests, assert on artifacts, not screenshots:

- process exit code;
- warnings/errors;
- `summary.xml`;
- `tripinfo.xml`;
- `edgeData`;
- TLS switch output;
- controller log;
- completion status.

## Bug Fix Rule

For a bug, reproduce the failure first:

```text
bug symptom -> failing test/probe -> minimal fix -> passing test -> regression record
```

Do not fix by changing multiple variables at once. If the fix requires changing demand, seed, controller logic, and output parsing together, split the work or mark the run diagnostic.

## Completion Record

End code work with:

```text
tdd_status: red-green-refactor / test-after / diagnostic-only / skipped-with-user-approval
red_test:
red_result:
green_change:
green_result:
refactor_result:
sumo_integration_check:
residual_risk:
claim_boundary:
```

If no RED was observed, say so plainly.

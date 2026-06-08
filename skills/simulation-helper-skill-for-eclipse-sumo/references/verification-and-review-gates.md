# Verification and Review Gates

Use this reference before claiming that SUMO/TraCI code, a simulation run, an experiment comparison, an audit report, or a public release is complete.

Core rule:

```text
No completion claim without fresh evidence.
No formal experiment claim from unreviewed code that can affect the result.
```

## Completion Evidence Matrix

Require current evidence for the object being completed:

| Object | Required evidence |
|---|---|
| Controller or utility code | TDD status, exact test command, pass/fail output, changed files, residual risk. |
| SUMO run | exact SUMO command, version, exit code, logs, warnings/errors, output files, teleports, unfinished vehicles, completion status. |
| Controller comparison | paired demand, seeds, horizons, output intervals, output directories, metric definitions, completion rates. |
| Metric report | parser test, source artifact, denominator, vehicle scope, time horizon, handling of unfinished/teleported vehicles. |
| Public release | skill validation, links, license, trademark notice, privacy scan, old-name scan, Pages or README smoke check. |

Words like "should pass", "seems fine", "SUMO ran", or "the plot looks good" are not completion evidence.

## SUMO Run Completion Gate

For a run to support formal evidence, record:

```text
sumo_command:
sumo_version:
exit_code:
loaded_network:
loaded_routes:
loaded_additional_files:
warnings_errors:
collisions_teleports_discarded:
unfinished_vehicles:
outputs_written:
natural_completion_or_fixed_horizon:
claim_boundary:
```

If the run stops at a fixed horizon with unfinished demand, do not report arrived-only averages as if they describe the full demand. Use completion-aware wording and metrics.

## Code Review Gate

Use a code-review stance for changes that affect:

- TraCI controller decisions;
- TLS phase/state mapping;
- detector/lane/edge pressure calculations;
- metric parsing or aggregation;
- route/config generation;
- batch output paths;
- seed, demand, horizon, or baseline pairing;
- reporting scripts used for paper figures or tables.

Review findings first. Prioritize:

1. bugs that can change controller behavior or reported metrics;
2. reproducibility failures such as unpaired seeds or overwritten outputs;
3. missing tests for changed behavior;
4. claim overreach caused by code or artifact gaps.

Style comments are secondary unless they hide a behavioral risk.

## Receiving Review Feedback

When the user or another reviewer reports a problem:

- verify the claim against files, artifacts, and tests;
- do not blindly agree;
- distinguish true bug, missing evidence, unclear claim, and reviewer preference;
- if the feedback changes behavior, return to the TDD gate;
- if it changes only wording, update the claim boundary and cite the evidence gap.

## Isolation Gate

Before experiments or code changes that could overwrite work:

- use a dedicated branch, worktree, or clean project copy when feasible;
- keep controller outputs in separate directories;
- include controller name, seed, demand scenario, and run id in output paths;
- never let baseline and treatment runs write to the same artifact path;
- preserve raw artifacts before parsing or plotting.

If isolation is not possible, state the overwrite risk and mark the run diagnostic until artifacts are protected.

## Completion Record

End with:

```text
verification_scope:
commands_run:
artifacts_checked:
tests_checked:
review_findings:
completion_status: complete / diagnostic-only / blocked / claim-overreach
residual_risk:
next_required_evidence:
```

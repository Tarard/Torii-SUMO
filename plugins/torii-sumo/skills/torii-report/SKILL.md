---
name: torii-report
description: Use when explaining, comparing, or writing up completed SUMO and traffic-control experiment results, checking metrics and baselines, bounding claims, capturing reusable lessons, or reviewing public release evidence. Do not rerun experiments unless explicitly requested.
---

# Torii Report

Interpret completed evidence. This skill owns result comparison, traffic-control experiment reporting, claim boundaries, reusable lesson capture, and release review. It does not rerun SUMO unless the user explicitly asks for another run.

## Start Here

| Task | Load |
|---|---|
| Metrics, baselines, completion, plots, or claim wording | `references/evaluate-and-report-results.md` |
| Completed traffic-control experiment or Chinese experiment report | `references/traffic-control-reporting.md` |
| Reusable lesson discovered from a resolved case | `references/capture-field-lesson.md` |
| Public repository or release review | `references/release-project.md` |

## Rules

- Use completed artifacts as the reporting basis and state when evidence is incomplete.
- Check completion and comparison fairness before ranking controller metrics.
- Distinguish traffic outcomes from controller rewards, pressure, losses, estimator scores, or internal objectives.
- Distinguish algorithm benefit from information benefit when methods observe different traffic information.
- Keep simulator truth, modeled observations, and physically deployable sensing separate.
- Do not turn a traffic report into a software audit unless the user asks for one.
- If the result is confusing and needs a new diagnostic experiment, hand off to `$torii-simulate`.

## Output

Lead with the traffic or experiment conclusion, then state the evidence boundary, uncertainty, and any missing evidence required for a stronger claim.

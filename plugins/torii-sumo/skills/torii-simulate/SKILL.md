---
name: torii-simulate
description: Use when planning, running, debugging, or diagnosing SUMO/TraCI experiments, controller behavior, code changes, paired simulation comparisons, environment failures, or unclear experiment mechanisms.
---

# Torii Simulate

Plan and operate SUMO experiments. This skill owns environment checks, workflow execution, controller logic, debugging, experiment design, code verification, and mechanism diagnosis. Use `$torii-report` when the main task is to explain or write up completed evidence.

## Start Here

| Task | Load |
|---|---|
| SUMO environment or executable proof | `references/preflight-sumo-environment.md` |
| Torii CLI/MCP execution and tool routing | `references/mcp-tool-routing.md` |
| Existing project or unclear next step | `references/route-project-workflow.md` |
| New or vague experiment | `references/interactive-experiment-intake.md` |
| Confirmed experiment planning | `references/plan-experiment.md` |
| SUMO/TraCI failure | `references/debug-sumo-traci.md` |
| Confusing or worse experiment result | `references/experiment-problem-solving.md` |
| Controller/TLS/TraCI boundary | `references/audit-sumo-controllers.md` |
| Controller-family design | `references/sumolights-controller-patterns.md` |
| Mechanism-isolated controller comparison | `references/compare-corridor-perturbations.md` |
| Code implementation or repair | `references/develop-and-verify-code.md` |
| SUMO semantics or public-source lesson | `references/learn-sumo-knowledge.md` |

## Rules

- Read `torii workflows --json` before selecting an executable scenario.
- Do not invent missing inputs or replace an unknown scenario with a different workflow.
- Separate what SUMO loaded, what the controller did, what outputs were produced, and what the evidence supports.
- Keep route, demand, seed, horizon, controller constraints, and output definitions paired for controller comparisons.
- Diagnose completion, backlog, teleports, warnings, and action traces before broad tuning.
- Use one bounded probe when the root cause is unknown.
- A successful run is not automatically formal evidence.
- For physical network construction use `$torii-build`. For demand/count fitting use `$torii-calibrate`. For completed-result reporting use `$torii-report`.

## Output

State the selected scenario or diagnostic question, evidence inspected, action taken or proposed, stopping condition, and remaining uncertainty.

# Torii Tool Routing

Use this reference when the installed `torii-sumo` plugin is available, when the user asks Codex to run SUMO checks through tools, or when SUMO outputs need interpretation before a code or modeling change.

## Role Split

- The skill is the reasoning layer: classify intent, choose the workflow, interpret feedback, and bound the claim.
- The MCP server is the execution layer: run bounded checks and return structured observations.
- MCP tool output is observation, not final interpretation.

## Tool Selection

| Situation | Tool | Required interpretation |
|---|---|---|
| Unknown machine, uncertain SUMO install, or missing runnable proof | `sumo_preflight` | Report environment pass/block status before any experiment claim |
| Need raw environment details for handoff | `sumo_get_environment` | Treat versions and missing binaries as construction evidence |
| Existing baseline and variant `.sumocfg` files | `sumo_config_pair_preflight` | Check missing inputs and shared outputs before running or comparing |
| Single `.sumocfg` execution | `sumo_run_config` | Inspect declared outputs before interpreting performance metrics |
| Need a minimal toolchain smoke test | `sumo_run_minimal_smoke` | Label as `diagnostic-demo`, not formal experiment evidence |
| Need bbox OSM download/reuse, road-class filtering, and SUMO network construction | `sumo_osm_build_network` | Treat tiled Overpass, retry, OSM deduplication, and netconvert output as construction evidence; inspect warnings before accepting the network |
| Need OSM/netconvert traffic-light cleanup review | `sumo_tls_audit` | Treat Google Maps as the external reality baseline after confirming current vs historical map scope; then review candidates and clusters |
| Need routeability probes for named roads or bridges | `sumo_network_routeability_probe` | Check missing key edges, generated routes, and later SUMO completion before claim escalation |
| Baseline and variant summary or tripinfo outputs | `sumo_compare_outputs` | Report completion, unfinished vehicles, and teleports before averages |
| Result handoff or reproducibility artifact | `sumo_collect_evidence` | Store raw observations, warnings, claim label, and residual risk |

## Feedback Diagnosis Loop

Use this loop whenever metrics look bad or outputs are incomplete:

```text
user intent
-> observed SUMO outputs, warnings, metrics, and logs
-> diagnose what the metric implies
-> identify likely network, demand, routing, controller, code, or experiment-design issue
-> choose the smallest next change
-> rerun the relevant check
-> report whether the user intent is better satisfied
```

Do not optimize a raw number without explaining the problem it indicates.

Examples:

- Low arrived count can mean the horizon is too short, insertion failed, routes are disconnected, or a controller blocked movement.
- High waiting time can mean demand is outside the intended scope, phase-lane mapping is wrong, TLS were joined incorrectly, or the controller policy is unsuitable.
- Teleports indicate construction or control feedback requiring lane, route, capacity, conflict, and controller checks.
- A controller metric improvement with worse completion is not success; surface the completion regression first.

## MCP Tool Use Record

When using Torii, report:

```text
user_intent:
tool_called:
input_artifacts:
raw_observation:
feedback_diagnosis:
claim_status:
next_control_action:
residual_risk:
```

## Missing Tool Boundary

If the user asks for full place-name geocoding, fully automated OSM intelligent cleanup, max-pressure controller generation, controller application, or controller-log inspection and no MCP tool exists yet, say that the plugin has the skill workflow but not that execution tool. Then provide the smallest manual or code-development next step.

The current OSM tools cover bounded bbox/source-OSM network construction, tiled Overpass requests, retry, OSM XML deduplication, road-class filtering, TLS audit candidate extraction, TLS clustering, Google Maps URL emission with temporal-scope fields, and named-road routeability probe generation. They do not by themselves prove signal timing, phasing, or controller readiness.

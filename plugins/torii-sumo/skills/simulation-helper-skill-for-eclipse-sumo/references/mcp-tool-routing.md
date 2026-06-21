# Torii Tool Routing

Use this reference when the installed `torii-sumo` plugin is available, when the user asks Codex to run SUMO checks through tools, or when SUMO outputs need interpretation before a code or modeling change.

## Role Split

- The skill is the reasoning layer: classify intent, choose the workflow, interpret feedback, and bound the claim.
- The MCP server is the execution layer: run bounded checks and return structured observations.
- MCP tool output is observation, not final interpretation.

## Tool Selection

| Situation | Tool | Required interpretation |
|---|---|---|
| One-sentence or ambiguous SUMO request | `torii_auto_workflow` | Let Torii classify the workflow, ask only blocking questions, and run safe MCP steps when required evidence is available |
| Unknown machine, uncertain SUMO install, or missing runnable proof | `sumo_preflight` | Report environment pass/block status before any experiment claim |
| Need raw environment details for handoff | `sumo_get_environment` | Treat versions and missing binaries as construction evidence |
| Existing baseline and variant `.sumocfg` files | `sumo_config_pair_preflight` | Check missing inputs and shared outputs before running or comparing |
| Single `.sumocfg` execution | `sumo_run_config` | Inspect declared outputs before interpreting performance metrics |
| Need a minimal toolchain smoke test | `sumo_run_minimal_smoke` | Label as `diagnostic-demo`, not formal experiment evidence |
| Need to resolve a named OSM area before construction | `sumo_osm_resolve_place` | Return Nominatim/OSM candidate display name, relation/node/way id, bbox, OSM preview link, and confirmation boundary |
| Need OSM cleanup from place name, bbox, or extract with mandatory gates | `sumo_osm_cleanup_workflow` | Enforce area confirmation, OSM build, region/current-or-user-targeted TLS audit, passenger connectivity, connected-core extraction, completion-aware routeability audit, optional routeability probes, SUMO-GUI/Netedit launch, and claim boundary |
| Need bbox OSM download/reuse, road-class filtering, and SUMO network construction | `sumo_osm_build_network` | Treat tiled Overpass, retry, OSM deduplication, and netconvert output as construction evidence; inspect warnings before accepting the network |
| Need OSM/netconvert traffic-light cleanup review | `sumo_tls_audit` | Extract TLS candidates, cluster nearby candidates, and create first-pass map review fields |
| Need traffic-light evidence from OSM, public map links, official inventory, signal plans, or field photos | `sumo_tls_multisource_review` | Use the correct regional current-network baseline; use Google Maps where appropriate, Amap/Gaode, Baidu Maps, Tencent Maps, official inventories, signal plans, and field photos for mainland China, and keep every row at `needs_manual_review` until a human confirms it |
| Need a reusable 100% passenger-connected core from an existing `.net.xml` | `sumo_network_connected_core` | Extract the largest passenger component into a `connected-core` network, keep the raw network as audit evidence, and report discarded fragments before routeability claims |
| Need routeability probes for named roads or bridges | `sumo_network_routeability_probe` | Check missing key edges, generated routes, and later SUMO completion before claim escalation |
| Need to prove random passenger routes finish before saying a network is usable | `sumo_network_routeability_audit` | Generate random passenger routes, run SUMO, parse `summary.xml`/`tripinfo.xml`, auto-extend the horizon when vehicles remain running, and fail rather than overclaim incomplete runs |
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

- Low arrived count can mean the horizon is too short, insertion failed, routes are disconnected, or a controller blocked movement. Use `sumo_network_routeability_audit` before treating a random-route smoke run as usable evidence.
- High waiting time can mean demand is outside the intended scope, phase-lane mapping is wrong, TLS were joined incorrectly, or the controller policy is unsuitable.
- Teleports indicate construction or control feedback requiring lane, route, capacity, conflict, and controller checks.
- `connected-core` means Torii preserved the raw network but routed downstream checks through a netconvert-built largest passenger component with strict connectivity passing.
- `partial-main-component` means strict connectivity still failed after cleanup or no connected core was available; treat it as diagnostic smoke-test material, not an experiment-ready network.
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

The current OSM tools cover named-area resolution, bounded bbox/source-OSM network construction, tiled Overpass requests, retry, OSM XML deduplication, road-class filtering, TLS audit candidate extraction, TLS clustering, region-aware map-link emission such as Amap/Gaode for mainland China or Google Maps where appropriate, Mapillary/KartaView review-link emission, optional inventory/signal-plan/field-evidence review fields, passenger connectivity checks, connected-core extraction, completion-aware routeability audit, SUMO-GUI/Netedit launch evidence, and named-road routeability probe generation. The high-level cleanup workflow coordinates these tools and blocks or demotes claims when area confirmation, map/TLS review, connectivity, routeability completion, or GUI inspection evidence is missing. They do not by themselves prove signal timing, phasing, or controller readiness.

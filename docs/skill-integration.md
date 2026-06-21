# SUMO Skill Integration

Torii is the execution actuator for `simulation-helper-skill-for-eclipse-sumo`. The skill should decide the workflow route and evidence boundary; Torii MCP tools should run bounded local checks and return structured observations.

## Codex Plugin Boundary

When installed as a plugin, `Torii` provides skills and MCP tools together.

- The skill is the reasoning layer: it classifies the request, loads minimal references, diagnoses bad metrics as feedback, and bounds claims.
- The MCP server is the execution layer: it returns structured observations from local SUMO checks.

Do not describe this as skills being inside MCP. The Codex plugin bundles both components.

## Recommended Routing

- unknown environment => `sumo_preflight`
- baseline/variant configs => `sumo_config_pair_preflight` before running/comparing
- single config => `sumo_run_config` then inspect declared outputs
- baseline/variant metrics => `sumo_compare_outputs` before interpreting duration/waiting/time loss/throughput/delay
- OSM cleanup from place name, bbox, or extract => `sumo_osm_cleanup_workflow`, then inspect area confirmation, Google Maps/current-or-user-targeted TLS audit artifacts, connectivity status, Netedit launch evidence, and claim boundary.
- bbox-only low-level OSM network construction => `sumo_osm_build_network`, then inspect tiled Overpass, retry, deduplication, netconvert status, and artifact paths
- OSM/netconvert TLS cleanup review => `sumo_tls_audit`, then use Google Maps as the reality baseline only after confirming current vs historical map scope
- named-road connectivity check => `sumo_network_routeability_probe`, then run or inspect the generated `.sumocfg`
- evidence handoff => `sumo_collect_evidence`

## Claim Boundaries

- preflight construction check only
- minimal smoke diagnostic demo only
- output comparison remains diagnostic unless the skill has separate evidence for matched route, demand, seed, horizon, controller identity, output interval, completion criteria
- GUI/screenshot evidence not part of MVP and must not be used as performance evidence
- Google Maps URLs and TLS clusters support reality-baseline review, but latest Google Maps must not override a historical modeling target without time-aligned evidence

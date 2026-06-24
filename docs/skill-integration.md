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
- OSM cleanup from place name, bbox, reference `.net.xml`, or extract => `sumo_osm_cleanup_workflow`, then inspect area inference or confirmation, reference-geometry bbox derivation when no explicit bbox is supplied, network-plan status, traffic-layer choices, reference artifact or policy-report analysis, service-road passenger permissions, mandatory Google Maps TLS review status, TLS physical cluster count, TLS aggregation review variant fields, scale-derived routeability parameters, reference visual-detail join/hierarchy/scope audit fields, Netedit launch evidence, and claim boundary.
- bbox-only low-level OSM network construction => `sumo_osm_build_network`, then inspect tiled Overpass, retry, deduplication, netconvert status, and artifact paths
- OSM/netconvert TLS cleanup review => `sumo_tls_audit`, then treat Google Maps review as a hard gate for unresolved TLS candidates; regional map links or official sources can supplement the review, with current vs historical map scope still recorded
- redundant TLS cleanup review variant => `sumo_network_tls_aggregation_variant`, using a `sumo_tls_audit` JSON report to produce a separate `*_tls_aggregated.net.xml` review network with one TLS representative per physical cluster; compare this artifact in Netedit and Google Maps before adopting it
- reference-matched junction cleanup => `sumo_network_reference_join_audit` on the candidate `reference_visual_detail` network, then inspect source-node matches, internal edges, approach counts, map-review URLs, and routeability/topology gates before adopting any aggregated variant
- reference-matched high-road cleanup => `sumo_network_reference_hierarchy_audit` on the candidate `reference_visual_detail` network, then inspect over-split corridors, out-of-scope high roads, hierarchy mismatches, and link/slip-lane cases before any merge, prune, or downgrade
- reference-matched scope cleanup => `sumo_network_reference_scope_audit` on the candidate `reference_visual_detail` network, then inspect type-count deltas and short detail-fragment candidates before any pruning
- junction aggregation review variant => `sumo_network_junction_aggregation_variant`, using topology or reference-join audit reports to produce a separate `*_junction_aggregated.net.xml` review network without overwriting the source network
- scope pruning review variant => `sumo_network_scope_pruning_variant`, using a reference-scope audit report to produce a separate `*_scope_pruned.net.xml` review network without overwriting the source network
- named-road connectivity check => `sumo_network_routeability_probe`, then run or inspect the generated `.sumocfg`
- evidence handoff => `sumo_collect_evidence`

## Claim Boundaries

- preflight construction check only
- minimal smoke diagnostic demo only
- output comparison remains diagnostic unless the skill has separate evidence for matched route, demand, seed, horizon, controller identity, output interval, completion criteria
- GUI/screenshot evidence not part of MVP and must not be used as performance evidence
- Google Maps TLS review is a hard current-network gate, but the latest public map must not override a historical modeling target without time-aligned evidence

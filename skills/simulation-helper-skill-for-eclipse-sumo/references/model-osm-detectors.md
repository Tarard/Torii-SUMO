# Model OSM Networks and Detector Alignment

Use this reference when building or editing a SUMO network from OSM, netconvert, Netedit, or another imported source; cross-checking signalized intersections against Google Maps, public map sources, aerial imagery, or agency inventories; aligning field detector points with SUMO lanes; or adding background visualization for diagnostic inspection.

The goal is construction discipline. A network that looks plausible in `sumo-gui` is not automatically ready for controller comparison or metric claims.

## Scope Discipline

- Keep each construction variant separate. Do not overwrite the validated baseline network when testing a denser road hierarchy, detector repair, TLS cleanup, or background layer.
- Name variants by modeling rule, for example:
  - `*_major_roads`: trunk/primary/secondary/tertiary or the locally relevant arterial classes.
  - `*_plus_minor_roads`: add the next lower road class for diagnostic inspection.
  - `*_detector_repaired`: repaired detector-to-lane mapping profile.
- Treat GUI inspection and map screenshots as diagnostic evidence only. Formal readiness still needs headless SUMO load, routeability, detector output, and completion checks.

## One-Sentence Autopilot Contract

Torii's first job is to get a bounded diagnostic result from a short user request. Do not turn region-aware baselines, road-detail choices, or TLS review into a long intake form.

Default behavior:

1. Infer the place, region, road-detail preset, and current-vs-historical baseline when the prompt and resolved OSM candidate make them clear.
2. Run bounded construction, connectivity, connected-core, routeability, and launch-evidence steps. Let `sumo_osm_cleanup_workflow` derive fixed routeability audit parameters from passenger-network scale; do not downshift the smoke test with ad hoc smaller values.
3. Ask the user only when the next action would be unsafe or impossible, such as ambiguous place resolution, missing bbox/extract, missing SUMO binaries, or a destructive overwrite.
4. If regional map/TLS reality evidence is missing, continue the diagnostic build and mark the claim boundary instead of blocking the workflow.
5. Report the exact assumptions and residual risks so the user can decide whether to strengthen the evidence.

## User Granularity Gate

For formal experiment candidates, destructive edits, or user-requested variants, ask the user what level of road detail is needed for the study. For one-sentence diagnostic builds, use the conservative arterial/core preset first and report the road-class assumption:

```text
network_detail_target:
minimum road classes:
next road class to test:
classes explicitly excluded:
why this detail is needed:
visualization only or formal experiment candidate:
```

Use the network planning gate before construction. Road classes are only one output of the plan; first identify the needed traffic layers and whether the network is reference-matched:

```text
network_plan_status:
traffic_layers: passenger | bicycle | pedestrian | bus
network_detail_target: arterial_core | passenger_vehicle | passenger_plus_service | bicycle | pedestrian | multimodal | reference_matched
reference_target:
reference_artifact: reference_net_file | reference_policy_report | locate_reference_artifact
primary_network_layer:
auxiliary_modal_layers:
selected_highway_classes:
vehicle_core_highway_classes:
reference_visual_detail_highway_classes:
reference_visual_detail_net_file:
default_routeability_layer: vehicle_core
default_netedit_comparison_layer: reference_visual_detail
service_passenger_policy: sumo_default | allow_vehicle_service | reference_match
validation_gates:
```

If the user asks to match, mimic, compare against, or learn from a reference network or dataset, first locate or request the reference artifact. The artifact may be a local SUMO `.net.xml`, a JSON reference policy report, a user-supplied file, a downloaded public release, or a cloned public dataset. Do not hardcode a city, repository, or named reference into the plugin. Once the artifact is available, infer two explicit scopes:

- `vehicle_core`: road classes from the reference passenger-drivable layer. Use this for passenger connectivity, connected-core extraction, routeability, topology audit, and simulation-readiness claims.
- `reference_visual_detail`: all visible OSM `highway.*` classes observed in the reference artifact. Build this as a separate Netedit comparison network when it differs from `vehicle_core`.

Apply `highway.service` passenger permissions only when the reference policy uses them, and require connectivity, routeability, topology, scope-matched reference comparison, and Netedit launch evidence. Never compare a Torii `connected-core` vehicle network against a full-detail manual reference network. If no reference artifact can be located or supplied, block on `reference_net_file` or `reference_policy_report` instead of guessing the road levels.

When the reference artifact is a SUMO `.net.xml` with joined-junction ids such as `cluster_*`, run `sumo_network_reference_join_audit` after building the candidate `reference_visual_detail` network, not on the passenger connected-core. Treat encoded source-node matches as stronger evidence than spatial proximity: the audit should report joined source-node counts, matched source-node ids, internal edges between those source nodes, approach counts, map-review URLs, and unmatched reference cases. Use spatial dense-junction clusters only as a fallback when source-node ids cannot be matched.

Use a small option set rather than silently adding everything:

| Option | Typical use | Risk |
|---|---|---|
| arterial/core roads only | signal-control corridor or clean controller comparison | may omit local access and visual context |
| arterial/core + next lower road class | finer visual model or routeability test | more junctions, more TLS candidates, harder review |
| include residential/service/access roads | high-detail local access study | fragmented topology, noisy TLS candidates, heavier GUI |
| background-only layers | water, buildings, land use, visual context | not routeable network evidence |

When producing a denser variant, quantify what changed:

```text
kept_osm_classes:
added_osm_classes:
osm_way_count_before_after:
sumo_edge_count_before_after:
sumo_lane_count_before_after:
lane_length_before_after:
junction_count_before_after:
routeability_status:
```

If the user only wants to inspect what changed, generate a diagnostic highlight layer instead of changing the validated experiment network.

## Construction Plan Gate

Before destructive edits, committing an imported network as an experiment baseline, or starting formal controller comparison, produce a short plan and ask for confirmation. For one-sentence diagnostic OSM-to-SUMO construction, generate into a fresh output directory with conservative defaults and record this plan as an evidence artifact:

```text
Network Modeling Plan
target:
study_area_scope:
source_data:
road_class_rule:
variant_name:
TLS_rule:
detector_alignment_rule:
background_layers:
validation_commands:
files_to_create:
files_not_to_overwrite:
claim_status:
```

Do not proceed to formal controller comparison from an unplanned network edit. Network construction is its own evidence gate.

## OSM Cleanup Hard Gates

For OSM-to-SUMO network construction, default to the high-level `sumo_osm_cleanup_workflow` when the Torii MCP tools are available. Do not treat `netconvert` success as enough evidence that the SUMO network is real.

Hard gates:

1. If the user gives only a place name, use `sumo_osm_resolve_place` or the place-resolution stage of `sumo_osm_cleanup_workflow` to produce an OSM/Nominatim candidate, bbox, and preview checkpoint. In one-sentence diagnostic mode, proceed when the candidate is clear and record it as an assumption; block only when the area is ambiguous, missing, or unsafe.
2. Before construction, resolve or infer a network plan. If no user intent or reference target identifies the traffic layers, block on the network-plan question instead of silently choosing all road types.
3. If a reference-matched workflow is active, analyze the supplied reference artifact before construction. If no explicit bbox or source OSM extract was supplied, derive the construction bbox from the reference `.net.xml` geometry rather than `origBoundary`. Use only the passenger-drivable vehicle layer to select OSM highway classes for the primary `vehicle_core` network, build a separate `reference_visual_detail` network from the full visible reference `highway.*` layer when it differs, and apply service-road passenger permissions only when the analyzed reference policy requires them. After construction, run reference join and reference scope audits on the candidate `reference_visual_detail` network, and create only non-destructive aggregation or pruning review variants.
4. After construction, run TLS candidate extraction and region-aware map review-link generation by default where supported.
5. When the TLS audit reports multiple SUMO TLS nodes for one physical cluster, create a separate TLS aggregation review variant with one real SUMO junction selected per physical cluster. Use the physical cluster count and aggregated `tlLogic` count as the comparison signal; treat raw `traffic_light` junction count as diagnostic noise.
6. For current-network modeling, treat Google Maps TLS review as a hard gate. Any unresolved TLS candidate keeps the workflow claim at `construction-invalid` even if construction, routeability, SUMO-GUI, and Netedit artifacts were produced. Regional maps, official inventories, signal plans, or field photos may supplement Google Maps where coordinate systems differ; record WGS84/GCJ-02/BD-09 assumptions when comparing coordinates. If the user asks for a historical network, the user's stated historical target controls the baseline; use time-aligned map evidence, OSM history, dated imagery, street-level imagery history, or agency inventory where available.
7. Run passenger connectivity checks before making stronger claims.
8. If raw connectivity fails because of small disconnected passenger fragments, extract a `connected-core` network from the largest passenger component, keep the raw network and discarded-component report, then rerun strict connectivity on the core.
9. Open the cleaned or connected-core network in SUMO-GUI and Netedit and report launch evidence.

If any gate is incomplete, keep the claim at `diagnostic-demo`, `construction-invalid`, or `blocked`. GUI inspection, Google Maps links, and clean SUMO loading do not prove timing, phasing, demand realism, or controller readiness.

## Road-Class Ladder

Start sparse and add detail only when the target requires it.

1. Keep arterial or study-relevant road classes first.
2. Add lower road classes only when they affect the experimental target, route realism, or detector coverage.
3. Add residential, service, foot, bicycle, or access roads only with an explicit purpose. They can fragment topology, create low-value junctions, and make traffic-light review noisy.
4. Record the exact keep/remove rule, source extract, netconvert command, warnings, and output network path for every variant.

Do not call a network experiment-ready merely because it opens in GUI, has many traffic lights, or passes a one-step SUMO load.

## Region-Aware Reality Baseline

Use the external map baseline that is appropriate for the modeled region. OSM can be a useful open construction source, but it is not automatically the ground truth for current road and TLS existence.

For mainland China, do not default to Google Maps as the current-road/TLS baseline. Prefer Amap/Gaode, Baidu Maps, Tencent Maps, official inventories, signal plans, or field photos. Record whether review coordinates are WGS84, GCJ-02, or BD-09 before comparing them with SUMO/OSM coordinates.

For current-network OSM cleanup, unresolved TLS candidates require Google Maps review before a clean-network claim. Regional sources can supplement or explain coordinate-system limits, but they do not remove the hard review status unless the workflow records the corresponding correction evidence.

Before using any map source as the standard, ask whether the user needs the current map or a historical target date. If the user is modeling a past network, the latest public map view is not automatically decisive. Use dated imagery, street-level imagery history, OSM history, or agency signal inventory when available.

Record:

```text
map_baseline_source: Amap/Gaode | Google Maps | official inventory | field evidence | other
regional_baseline_source:
coordinate_system: WGS84 | GCJ-02 | BD-09 | unknown
map_temporal_scope: current | historical | unspecified
map_target_date:
map_review_url:
audit_status:
action:
time_scope_residual_risk:
```

1. Convert every candidate junction or detector point to a stable coordinate record such as `lat,lon`.
2. Cluster close SUMO TLS candidates before review. Many SUMO junction IDs may represent one physical intersection.
3. Verify vehicle signals visually or from public inventory:
   - Keep SUMO TLS where the external source shows a vehicle signal at that intersection.
   - Remove, downgrade, or mark for review SUMO TLS where the source shows no vehicle signal.
   - Be careful with pedestrian crossings, bicycle crossings, tram signals, ramp meters, and nearby separate intersections.
4. Record review fields such as `sumo_node_id`, `lat`, `lon`, road names, external-source URL or inventory ID, `map_temporal_scope`, `map_target_date`, `audit_status`, and action (`keep_tls`, `remove_tls`, `needs_review`).
5. Bound claims: external visual evidence supports a modeling decision. It does not prove signal timing, phasing, recall, detector actuation, or operational control.

## Junction Aggregation Audit

When OSM/netconvert creates many close junctions or short edges around one physical intersection, do not immediately edit or join the network. First run a reusable dense-junction audit with local cluster-graph analysis and create a non-destructive correction record.

If no reference network is available, use the reference-free junction aggregation scorer from the topology audit. The scorer is diagnostic: it classifies each dense cluster as `join`, `needs_map_review`, or `do_not_join` from local topology, short internal edges, road-name consistency, TLS density, and risk flags. It must not destructively edit the source network by itself.

Required fields for each suspicious junction cluster:

```text
cluster_id:
node_ids:
node_count:
node_types:
centroid_lat:
centroid_lon:
map_review_source: Google Maps default map
google_maps_url:
optional_google_maps_satellite_url:
manual_correction_status: needs_map_review
suggested_correction_action:
internal_edge_ids:
boundary_edge_ids:
external_junction_ids:
connected_node_pairs:
internal_edge_count:
boundary_edge_count:
approach_count:
direct_connected_node_pair_count:
internal_edge_overlap_pair_count:
aggregation_recommendation:
reference_free_scorer:
aggregation_decision:
aggregation_confidence:
aggregation_reason:
short_internal_edge_score:
same_road_name_score:
angle_continuity_score:
traffic_signal_density:
service_or_parking_risk:
bridge_tunnel_layer_risk:
roundabout_or_slip_lane_risk:
risk_flags:
```

Use the cluster graph fields to separate edges whose endpoints are both inside the suspicious junction cluster from edges that connect the cluster to outside junctions. Do not join by radius alone. A cluster becomes a join candidate only when local topology indicates the short internal edges are likely intersection-internal fragments and the default map confirms the physical intersection footprint.

At the end of cleanup, report the aggregation summary to the user:

```text
junction_aggregation_candidate_count:
junction_aggregation_join_candidate_count:
junction_aggregation_needs_map_review_count:
junction_aggregation_do_not_join_count:
junction_aggregation_candidates_file:
```

For reference-matched cleanup, prefer case mining over manual parameter sweeps. A reusable reference join audit should first read the manual reference's joined-junction cases, then compare each case with the candidate network:

```text
reference_id:
reference_type:
reference_joined_source_node_count:
reference_approach_edge_count:
matched_reference_source_node_count:
reference_source_node_match_ratio:
matched_reference_source_internal_edge_ids:
matched_reference_source_boundary_edge_ids:
matched_candidate_cluster_id:
matched_candidate_node_count:
matched_candidate_internal_edge_count:
learned_rule_basis: reference_source_nodes | spatial_cluster | none
learned_rule:
```

Use source-node matches to learn general aggregation rules from the reference network. For example, if the reference joins two to four source OSM nodes and the candidate contains short internal edges between the same ids, that case is a `tum_like_join_candidate` regardless of city name. Keep city-specific examples as evidence, not hardcoded plugin logic.

Before pruning a denser candidate, run a reusable reference scope audit. It compares reference and candidate `highway.*` type counts, then flags only absent-in-reference or overrepresented short dead-end detail fragments as pruning candidates. This is a review scorer, not a city-specific rule and not an automatic deletion policy.

At the end of reference-matched cleanup, report the scope summary to the user:

```text
reference_scope_status:
reference_scope_prune_candidate_count:
reference_scope_prune_candidates_file:
reference_scope_pruning_status:
reference_scope_pruning_variant_file:
```

For regions where Google Maps is reliable and appropriate, use the default Google Maps road geometry to compare the cluster against the physical intersection footprint before any destructive aggregation. Use satellite view only when the default map is ambiguous. For mainland China or other regions where Google Maps is not the right current-road baseline, keep the map-review field but add the appropriate regional source in the correction record.

Torii may produce a separate `*_junction_aggregated.net.xml` review variant with `sumo_network_junction_aggregation_variant`, but it must not overwrite the source network or treat the variant as adopted before map/source-bounded review. Keep the raw network, visual-detail network, audit CSV/JSON, and aggregation output separate, then rerun connectivity, routeability, TLS audit, and topology audit before stronger claims.

Torii may produce a separate `*_scope_pruned.net.xml` review variant with `sumo_network_scope_pruning_variant`, but it must not overwrite the source network or treat the variant as adopted before map/source-bounded review. Keep the type-comparison CSV, prune-candidate CSV, remove-edge list, and review network together.

For redundant signal clusters, Torii may also produce a separate `*_tls_aggregated.net.xml` review variant with `sumo_network_tls_aggregation_variant`. This is a signal-controller cleanup artifact, not a geometry-join artifact: it rebuilds TLS definitions from physical TLS clusters while preserving the source geometry for review.

## Redundant TLS Removal Gate

When OSM/netconvert creates many traffic lights, force a TLS audit before using the network for signal-control claims:

```text
candidate_tls_count:
clustered_physical_intersections:
external_signal_source:
map_temporal_scope:
map_target_date:
keep_tls:
remove_tls:
downgrade_to_priority_or_uncontrolled:
needs_manual_review:
```

Rules:

- Remove or downgrade SUMO TLS that correspond only to geometry nodes, pedestrian-only crossings, ramp meters outside scope, or map artifacts.
- Keep TLS that correspond to real vehicle-signalized intersections in the modeled scope.
- If a cluster of SUMO nodes represents one physical intersection, document whether they should remain separate controllers, become a joined TLS, or be simplified.
- If the cluster should become one signalized intersection, build a TLS aggregation review variant first; do not hand-edit the source network or compare raw SUMO TLS-node counts against a manual reference as if they were physical signals.
- After TLS removal or rebuilding, rerun routeability smoke, TLS phase audit, and controller mapping checks.
- Do not claim "realistic signal control" from OSM TLS alone. The claim requires source-bounded TLS existence, phase semantics, timing policy, and controller evidence.

## Detector-to-Lane Mapping

Field, paper, or agency detector points often represent directional or lane-specific measurements. Nearest-lane projection is not enough.

1. Preserve the original detector source table as an immutable reference.
2. Generate a separate mapping table with generic fields such as:
   `sensor_id`, `station_id`, `source_location`, `field_lane`, `lane_id`, `edge_id`, `lane_pos`, `match_distance_m`, `mapping_status`.
3. Parse source text for direction, road side, lane side, movement, or station grouping. Use local-language direction phrases only as evidence, not as hard-coded private project assumptions.
4. For same-lane conflicts, expand the repair group to the full detector station or movement group, not only the pair that first collided.
5. Candidate lanes should include nearby passenger lanes within a bounded radius, the current lane for traceability, lane index, edge ID, distance, and lane position.
6. Decision rules:
   - Reject duplicate SUMO `lane_id` within the active detector group unless duplicates are explicitly intended.
   - Same direction: prefer distinct lane indices on the same directed edge.
   - Mixed directions: avoid sharing one directed edge across different directions unless the source justifies it.
   - If strict rules cannot select a unique low-distance assignment, stop with `manual_review` instead of silently accepting a duplicate lane.

## Field-Data Alignment Validation

For aggregate loop or sensor data, the strongest supported claim is usually sensor/time-bin count alignment, not real vehicle identity.

Required chain:

```text
field sensor/time/count record
-> selected mapping row
-> SUMO detector id/lane/position
-> validation route vehicles
-> detector output count
-> comparison row
```

Hard gates:

- Every active source sensor is present in the field data.
- Every active source sensor has exactly the intended SUMO detector.
- Detector ID, lane ID, lane position, and aggregation period match between the mapping table and additional XML.
- Every active sensor has every expected validation interval.
- For every sensor/time-bin, simulated detector count equals the expected validation count in the controlled validation case.
- Repaired same-lane conflict files have zero unresolved rows.
- SUMO summary reports loaded/inserted/arrived consistency and no unexplained running vehicles, collisions, or teleports.

Claim boundary:

- If field data includes sensors outside the modeled study area, report them as out of scope rather than failures.
- Detector entry counts prove count observability. They do not prove real per-vehicle identity unless a separate vehicle-ID audit is run.

## Background Visualization

SUMO road networks do not automatically include rivers, land-use polygons, map tiles, or static imagery.

Options:

1. Prefer a non-destructive polygon or background layer for diagnostic inspection. A road-only extract cannot show water or land-use features by SUMO GUI configuration alone.
2. Generate a polygon additional with `polyconvert` and a documented typemap, then load it alongside the road network in `sumo-gui`.
3. If using GUI background images, decals, or map tiles, save view settings separately from experiment configs.
4. Keep heavy building or land-use layers optional. They may make GUI inspection slow and are usually not needed for formal simulation evidence.
5. State clearly whether the background is static diagnostic visualization or part of the simulation network. Visual polygons are not routeable vehicle edges unless the experiment explicitly models that mode.

## Minimal Output Record

For each modeling pass, record:

```text
target:
study_area_scope:
source_extract:
road_class_rule:
network_output:
optional_background_output:
external_signal_audit:
detector_mapping:
validation_commands:
key_results:
out_of_scope_items:
residual_risks:
claim_status:
```

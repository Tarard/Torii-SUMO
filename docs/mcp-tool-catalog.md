# Torii MCP Tool Catalog

Torii currently registers 75 MCP tools. Normal users should start broad build and audit requests with `torii_auto_workflow`; explicit read-only diagnostics such as local intersection-type, road-semantic, or signal-device classification may call the named specialist tool directly. The remaining tools are grouped router capabilities, reproducible scripts, and targeted diagnostics.

The implementation boundary is consistent across groups:

```text
server.py registration -> tools/* adapter -> core/* implementation -> structured artifacts
```

## Router

- `torii_auto_workflow` - classify one natural-language SUMO request and route it to a bounded workflow.

## Environment, Execution, and Evidence

- `sumo_get_environment`
- `sumo_preflight`
- `sumo_config_pair_preflight`
- `sumo_run_config`
- `sumo_run_minimal_smoke`
- `sumo_compare_outputs`
- `sumo_collect_evidence`

Use these for environment discovery, controlled execution, baseline/variant checks, and portable evidence bundles. They do not establish network or controller correctness by themselves.

## NetEdit GUI Candidate Session

- `sumo_netedit_session`
- `sumo_tum_style_closed_loop`

This is one grouped session tool, inspired by the recurring scene/document/
object/viewport/edit lifecycle in [Blender MCP](https://github.com/ahujasid/blender-mcp),
[FreeCAD MCP](https://github.com/neka-nat/freecad-mcp), and
[Unity MCP](https://github.com/CoplayDev/unity-mcp). These are design references,
not Torii runtime dependencies or identical APIs. Torii therefore keeps one
grouped tool rather than registering a separate MCP tool for every button. The
lifecycle maps to NetEdit as `open -> observe -> act -> observe -> finalize/abort`.
`open` creates one source-hash-bound candidate session per Torii server;
`observe` returns a local client-coordinate screenshot path/hash plus an explicitly
on-disk candidate summary; `act` checks the caller's exact last recorded screenshot
SHA, then captures the live viewport again. Bounded global editor animation is
allowed, while click/drag target pixels must remain exact. `finalize` saves,
closes, then runs existing SUMO-load, bounded surface-overlap, and Connection
Mode audits. F7 joins must also match the source/candidate junction identities
declared before the GUI edit, use the frozen selection containing exactly those
source junctions and be the first edit action. Every semantic shortcut and save
requires an exact live viewport match immediately before delivery. Unsaved GUI state is visible only in the screenshot, never
misreported as persisted XML. The source network is immutable and every result
keeps automatic promotion blocked. Torii deliberately omits arbitrary Python,
C#, shell, or caller-exposed raw Win32 execution surfaces. The current local Codex
integration renders the screenshot artifact with its local image viewer; the tool
does not yet embed pixels as generic MCP `ImageContent`.

`sumo_tum_style_closed_loop` is the companion ledger for a TUM-style teaching
run. It keeps one accepted candidate SHA as the next iteration's parent,
records one atomic NetEdit/MCP action with before/after evidence and audits,
derives a concrete next correction when evidence is incomplete, and can restore
the parent artifact. It never overwrites the canonical baseline and never turns
GUI evidence into automatic promotion.

## OSM Construction and User-Facing Review

- `sumo_osm_resolve_place`
- `sumo_osm_cleanup_workflow`
- `sumo_osm_build_network`
- `sumo_tls_audit`
- `sumo_tls_multisource_review`
- `sumo_network_connected_core`
- `sumo_network_routeability_probe`
- `sumo_network_routeability_audit`
- `sumo_network_review_html`

`sumo_osm_cleanup_workflow` is the preferred capability workflow. `sumo_osm_build_network` is a low-level importer and must not be presented as a complete cleanup or correctness workflow.

## Structural, Reference, and Regression Audits

- `sumo_network_connection_mode_audit`
- `sumo_network_connection_mode_calibration`
- `sumo_network_connection_mode_regression_audit`
- `sumo_network_exact_semantic_regression_audit`
- `sumo_network_topology_audit`
- `sumo_network_overlapping_junction_audit`
- `sumo_network_reference_join_audit`
- `sumo_network_reference_hierarchy_audit`
- `sumo_network_reference_scope_audit`
- `sumo_network_tls_warning_parity`
- `sumo_network_surface_overlap_audit`
- `sumo_network_surface_overlap_comparison`

These tools distinguish structural failure from evidence ambiguity. A route completing successfully does not replace lane/via/request/TLS or exact source-to-candidate evidence.

## Candidate Construction and Promotion Gates

- `sumo_network_junction_aggregation_variant`
- `sumo_network_scope_pruning_variant`
- `sumo_network_corridor_geometry_simplification_variant`
- `sumo_network_corridor_edit_ledger`
- `sumo_network_corridor_materialize_variant`
- `sumo_network_corridor_candidate_gates`
- `sumo_network_teacher_corridor_comparison`
- `sumo_network_tls_reference_cleanup_variant`
- `sumo_network_standard_nema_phase_binding`
- `sumo_network_teacher_guided_junction_variant`
- `sumo_network_teacher_guided_repair_queue`
- `sumo_network_tls_aggregation_variant`

Candidate tools write separate review artifacts and retain rollback/provenance. They do not silently replace the source network.

## Intersection Workflows

- `sumo_intersection_archetype_classify`
- `sumo_intersection_model`
- `sumo_intersection_clean`
- `sumo_intersection_validate`
- `sumo_nema_four_way_reference_workflow`
- `sumo_intersection_scene_workflow`

The read-only archetype classifier hashes and parses one frozen OSM byte snapshot, then returns the finite composable profile together with complete physical-cell, topology, movement, and lower-level road-detail evidence bodies. Road detail resolves authoritative road-network categories first, keeps OSM `highway=*` as an explicit fallback, and only then emits arm/channelization/connection candidates. Its top-level generation status, type-recognition decision, disposition, and blocked promotion gate are separate fields. It does not authorize node joins, channelization reconstruction, or traffic-light binding. The remaining tools cover structured intersection modeling, compilation, validation, and the bounded synthetic/reference workflows used for small-network experiments.

## Road-Semantic Evidence Bridge

- `sumo_road_semantic_bridge`
- `sumo_intersection_road_sumo_bind`

This read-only tool parses caller-supplied frozen OSM, SUMO, and Hamburg HH-SIB snapshots at explicitly declared times. It reports official-to-OSM conflation candidates, OSM-to-SUMO lineage, and a `road_network_evidence` artifact containing only pass-reviewed identity/property assertions. OSM-to-SUMO lineage requires an explicit declared import provenance (`sumo_imported_from='osm'` and the exact OSM SHA-256); otherwise it stays blocked. An optional frozen HVS snapshot is retained as a distinct official category source; its feature membership is not automatically conflated to HH-SIB, OSM, or SUMO. An optional local reviewed-assignment JSON may select an already generated official-to-OSM candidate and attach scheme-qualified official road properties while retaining the HVS source reference. When an `output_dir` is supplied, it must be separate from input directories; the tool writes hash-listed bridge/evidence/manifest JSON artifacts there for the later intersection classifier and fails closed if its artifact filenames already exist. The tool does not download data, mutate a source or candidate, create SUMO files, infer lane connections, bind signals, or authorize reconstruction or digital-twin promotion.

`sumo_intersection_road_sumo_bind` composes the hash-bound local intersection classification with the bridge report's OSM-to-SUMO lineage. It requires the road-detail projection and bridge report to carry the same non-empty `bridge_id`, and checks the exact OSM source hash before binding. It returns road-arm-to-edge candidates and connection-intent review records only; optionally it writes that direct immutable binding payload as a new JSON artifact for a later materializer. It does not emit a SUMO `connection`, decide lane indices or stop lines, assign a junction owner or TLS `linkIndex`, alter a network, or authorize promotion.

## Signal Device Classification

- `sumo_signal_device_profile_classify`

This read-only specialist hashes and parses one frozen OCIT-C supply snapshot, then returns a Germany-first, Europe-compatible inventory that keeps logical signal groups, physical signal heads, visual displays, non-visual accessibility outputs, runtime state, and control methods separate. It preserves source-native traffic classes, channel labels, allowed signal-image codes, mounting metadata, and unresolved symbols or applicability. In particular, an OCIT `Gruen` interface slot carrying `Ton` or `Vibra` is not classified as a visual green lamp. The result never authorizes lane or movement binding, signal-group reassignment, phase generation, timing, or controller actions.

## Detector Demand

- `sumo_detector_route_support`
- `sumo_detector_count_constraints`
- `sumo_detector_count_audit`
- `sumo_detector_route_sampler_calibrate`

These tools construct and assess detector-constrained demand. Their output is a plausible count-matched route set, not a uniquely identified true OD matrix.

## Hamburg Corridor Digital Twin

- `sumo_hamburg_sandtorkai_digital_twin`
- `sumo_hamburg_named_count_scope`
- `sumo_hamburg_sandtorkai_signal_observations`
- `sumo_hamburg_sandtorkai_named_replay`
- `sumo_hamburg_sandtorkai_execution_plan` (keeps network-independent W3a
  count acquisition separate from W1-bound W3b detector binding, verifies the
  W2/W3b/W4 network SHA-256 against W1, validates W4's W2/W3a/W3b manifest identities,
  derives the W5 capability summary automatically,
  and accepts optional hash-bound `stage_feedback` for diagnostic re-planning;
  feedback cannot promote a blocked stage)
- `sumo_hamburg_2394_archetype_classify`
- `sumo_hamburg_2394_compound_geometry_first_pass`
- `sumo_hamburg_2394_tls_topology_materialize`
- `sumo_hamburg_sandtorkai_corridor_geometry_materialize`
- `sumo_hamburg_sandtorkai_mainline_scope_materialize` (profiles include the
  compact mainline and the entry-flow scope with Großer Grasbrook and
  Singapurstraße)
- `sumo_hamburg_sandtorkai_geometry_safe_digital_twin`
- `sumo_hamburg_sandtorkai_corridor_tls_materialize`
- `sumo_hamburg_cached_detector_demand`
- `sumo_hamburg_corridor_candidate_detector_demand`
- `sumo_hamburg_corridor_candidate_map_bindings`
- `sumo_hamburg_corridor_candidate_signal_bindings`
- `sumo_hamburg_sandtorkai_corridor_candidate_package`
- `sumo_hamburg_official_tls_rebuild`
- `sumo_digital_twin_replay_validate`

This group binds official Hamburg MAP, OCIT, count, detector, candidate, and replay evidence to a fixed corridor scope. Before the corridor TLS materializer may write a lane connection, it requires a hash-bound road-arm/SUMO binding for the exact candidate source network; every planned lane transition must be covered by exactly one ready intent and retain MAP geometry, official movement/control, and SUMO owner/link-index evidence. The geometry-safe package therefore stops after geometry when that candidate-specific binding is absent. Hamburg-specific orchestration stays separate from generic network and detector primitives.

`sumo_hamburg_sandtorkai_named_replay` is the reusable W4 materializer: it
consumes the hash-bound W2 signal/events, W3a count values, and W3b detector
mapping; shared-lane aggregation must already be approved. It then combines
same-location virtual sensors, routeSampler, SUMO, and the real-vs-virtual E1
audit under one automatic teleport/collision and completeness gate.

`sumo_hamburg_sandtorkai_signal_observations` is the preceding signal-history
stage: it consumes the hash-bound W2 primary-stream bindings, queries the
official v1.0 primary observation service for an explicit UTC window, writes
time-zero and in-window TLS link events, and blocks on partial/empty streams or
missing required nodes. The v1.1 endpoint may still be used for metadata
discovery, but is not silently substituted for v1.0 historical primary states.

## Maintenance Contract

The catalog is checked against `plugins/torii-sumo/src/torii_sumo/server.py`. When registering or removing a tool:

1. place reusable logic below the MCP adapter boundary;
2. update the appropriate group above;
3. update skill routing if the capability is user-visible;
4. add a contract or regression test;
5. state the tool's claim boundary in its description and output.

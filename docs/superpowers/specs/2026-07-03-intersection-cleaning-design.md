# Intersection Cleaning Refinement Design

## Goal

Stabilize the existing Torii-SUMO `IntersectionIR` cleaning pipeline on the `html` branch without rewriting the project. The implementation keeps the current flow:

`parse_osm_xml -> infer_intersection_core -> infer_approaches -> build_road_pair_relation_graph -> infer_movement_matrix -> infer_control_model -> compile_intersection_to_plain -> validate_intersection -> clean_intersection`

## Scope

This pass tightens semantics inside the existing architecture. It does not add city-scale OSM cleanup, full SUMO experiment validation, a new graph engine, or a new public MCP surface.

## Contract Changes

`Approach` gets explicit layer fields while retaining `allowed_modes` for SUMO permissions:

- `mode_layer`: `vehicle`, `support`, or `fused_support_lane`
- `is_vehicle_approach`
- `is_support_only`
- `fused_support_modes`

`RoadPairRelation` gets `severity`: `none`, `diagnostic`, `blocking`, or `manual_review`. Missing physical vehicle connections are blocking. Duplicate parallel edges are diagnostic unless they block movement generation.

Validation keeps the current mode counts, vehicle approach count, and vehicle topology type as stable API fields.

## Geometry And Movement Rules

Road-pair geometry uses `Approach.source_shape_xy`, not only the first OSM way. Shared-node evidence is aggregated across all `source_way_ids`. Bridge, tunnel, or layer separation prevents false crossing fixes and emits `preserve_separate_levels`.

Movements are legal only when source and target share a mode, the compatible movement layer is the same, and the relation supports traversal. Same-mode disjoint or unknown pairs are blocked unless the relation explicitly supports traversal. U-turns remain blocked unless there is explicit reverse/uturn turn-lane evidence.

## Support Paths

Support behavior becomes explicit through `mode_layer`. Support-only approaches route through a support core when present. Uncontrolled support paths remain out of vehicle core connections. Controlled bicycle support movements remain possible and deduplicated.

## TLS And Validation

Traffic-light generation keeps the existing alternating fallback but labels it as `synthetic:alternating_placeholder`. Compiled connections carry an internal movement id and generated `linkIndex`, so TLS phase state is checked against compiled controlled connections rather than movement count alone.

Validation parses available plain or compiled XML artifacts and reports structured warnings with severity and source while preserving JSON/dict compatibility for MCP tools.

## Acceptance

The named intersection suite passes. New regressions cover:

- corridor-extension relations use `source_shape_xy`
- bridge/tunnel crossings do not suggest `split_edge_at_crossing`
- disjoint same-mode approaches do not produce legal movements
- TLS validation blocks bad phase lengths and missing controlled connections
- diagnostic warnings do not block

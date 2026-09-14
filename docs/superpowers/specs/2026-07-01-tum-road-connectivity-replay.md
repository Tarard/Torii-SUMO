# TUM Road Connectivity Replay Spec

## Target

Torii-SUMO must learn TUM-style road connectivity separately from TUM-style
junction cleanup.

The junction layer answers:

```text
inside this intersection, which movements, TLS links, crossings, walkingareas,
internal edges, and internal junctions exist?
```

The road connectivity layer answers:

```text
outside the intersection core, how are road edges segmented, chained,
connected, and preserved so the network remains continuous?
```

Both layers are required before Torii can generate a full TUM-like network from
OSM. A correct junction replay can still fail as a road network if corridor
edges are split differently, boundary lanes are missing, same-road continuity
is broken, or pedestrian/bicycle side paths are detached.

## Control Loop

- target: extract and replay TUM road-corridor connectivity so edge chains,
  lane counts, permissions, endpoint junctions, and non-junction connections
  remain routeable and comparable.
- current_state: Torii now has a TUM junction self-replay gate for selected
  junctions, but that gate intentionally scopes to target-local junction
  bundles.
- deviation: a full OSM-to-SUMO network can still differ from TUM because road
  corridors are split, merged, or connected differently before they ever reach
  the junction repair layer.
- control_action: add a road-connectivity teacher layer with its own extractor,
  replay probe, and parity gate.
- feedback: road-chain signature parity, lane-permission parity, endpoint
  continuity, non-junction connection parity, SUMO load, routeability, and
  NetEdit visual review.
- stopping_condition: at least one short TUM corridor around a replayed
  junction can be extracted as a road-connectivity bundle, replayed without
  junction-internal semantics, and loaded by SUMO with no missing lane/edge
  references.

## Definitions

- Road corridor: a chain of non-internal SUMO edges that represent a real road
  between junction cores or between a junction core and the bbox boundary.
- Edge stitching: the way TUM splits or joins OSM-derived road geometry into
  SUMO edges and maps edge endpoints to junctions.
- Road connection: a connection between non-internal road edges outside the
  target junction-internal movement graph.
- Boundary continuity: local replay keeps the road edge and lane references at
  the boundary of a probe so SUMO can load it and routes can enter/exit.
- Modal side path: pedestrian, bicycle, path, sidewalk, or service edge that
  travels alongside or between vehicle road edges. It must not be dropped just
  because it is not a vehicle approach.
- Junction layer: target-local junction bundle including movements, TLS,
  internal edges, crossings, walkingareas, and requests.
- Road layer: corridor bundle including non-internal road edges, lanes,
  endpoint junctions, lane permissions, and road-to-road continuity outside the
  junction core.

## Workflow

1. Select a short TUM road corridor around an already replayed junction.
   - Start from a small probe such as `7616444534`.
   - Include the incident non-internal edges and one hop beyond each boundary
     junction.
   - Keep this separate from target junction internal edges.

2. Extract the road-connectivity teacher bundle.
   - Non-internal edges and lanes.
   - Edge ids, from/to junction ids, names, priorities, types, shapes.
   - Lane indices, speeds, widths, lengths, permissions, and shapes.
   - Endpoint junction attributes required for SUMO load.
   - Non-junction road-to-road connections.
   - Modal side path edges connected to the corridor.

3. Materialize a road-connectivity self-replay net.
   - Preserve SUMO root `<net>` attributes so the file loads.
   - Write only road-layer structures and required boundary junctions.
   - Do not include target junction TLS/internal movement details in this
     road-layer probe.

4. Compare teacher and replay.
   - Edge chain signature parity.
   - Lane permission/count parity.
   - Endpoint junction reference parity.
   - Road connection parity.
   - Missing-reference audit equals zero.
   - SUMO load passes.

5. Learn reusable road rules.
   - How TUM handles same-name road continuity.
   - How TUM preserves or splits bicycle/sidewalk side paths.
   - How TUM treats short connector edges at bbox/junction boundaries.
   - How TUM keeps road connectivity even when junction internals are replayed
     separately.

6. Integrate road layer with junction layer.
   - Road layer prepares continuous non-internal corridors.
   - Junction layer replaces only target-internal movement semantics.
   - Final workflow validates both route continuity and NetEdit connection
     semantics.

## Gates

- `road_missing_reference_count == 0`: every lane, edge, via, and junction
  reference used by the road replay exists.
- `road_edge_chain_parity == pass`: ordered corridor edge chains match after
  canonicalization.
- `lane_permission_parity == pass`: lane counts and allow/disallow modes match.
- `road_connection_parity == pass`: non-junction road-to-road connections match.
- `sumo_load == pass`: replayed road-layer net loads in SUMO.
- `routeability == pass`: at least one route can traverse the corridor between
  boundary edges when the probe has two vehicle boundaries.
- `claim_status == diagnostic-demo`: until this is tested across multiple
  corridors and then integrated with junction replay.

## Non-Goals

- Do not treat road connectivity as a junction-internal movement problem.
- Do not delete side paths, bike paths, sidewalks, or short connector edges only
  to reduce junction mismatch counts.
- Do not infer road continuity only from edge id equality; use topology,
  geometry, road name/ref, lane permissions, and endpoint junctions.
- Do not hardcode Ingolstadt edge ids, junction ids, or coordinates in reusable
  road rules.
- Do not claim full TUM-like network generation until road-layer and
  junction-layer gates both pass.

## Claim Boundary

Passing one road corridor supports only:

```text
diagnostic-demo: Torii can code-replay one TUM road-connectivity corridor under
explicit road-layer gates.
```

Passing multiple road corridors and junctions supports:

```text
reference-teacher-replay: Torii can deterministically replay selected TUM road
and junction patterns before attempting OSM reproduction.
```

Only after OSM/Torii candidates pass both road and junction gates may the
workflow claim:

```text
reference-guided OSM-to-SUMO network cleaning for covered TUM reference areas.
```

# Complex Junction Movement Rebuild Spec

## Target

Torii-SUMO needs a reusable way to handle complex urban intersections where
plain node joining gives a visually plausible junction footprint but leaves
incorrect lane-to-lane connection geometry.

The first target is a diagnostic/prototype workflow for one difficult
Ingolstadt intersection. The production target is a general method that can
detect, explain, rebuild, and review complex junction movements without
hardcoding Ingolstadt or the TUM reference network.

## Control Loop

- target: produce a realistic SUMO junction whose footprint and internal
  movements both match human traffic-engineering logic.
- current_state: Torii can build OSM-derived visual-detail networks and can
  collapse selected junction clusters, but NetEdit connection mode still shows
  bad internal movement geometry at difficult signalized intersections.
- deviation: the old core nodes can be removed while the movement graph remains
  wrong. This means geometric aggregation alone is not enough.
- control_action: separate the task into detect -> understand -> audit ->
  rebuild candidate -> SUMO/netedit verification.
- feedback: movement audit JSON/CSV, SUMO load, routeability, NetEdit connection
  mode, and human review of the generated review artifact.
- stopping_condition: a single target junction can be rebuilt with no residual
  old core nodes, explicit high-confidence connections, SUMO load success, and
  NetEdit connection geometry that is acceptable for wider bbox testing.

## Problem

`netconvert` can infer internal connections after junction joining, but for a
complex OSM intersection this inference may preserve or create movements that
do not match the intended road logic. The visible symptom is a large junction
polygon with internal lane connections crossing, duplicating, or attaching to
the wrong approach lanes.

Human cleanup does not start by drawing a larger polygon. A human engineer first
understands which roads enter the intersection, which roads leave it, which
turning movements are allowed, which modal layers are independent, and where
the conflict core should be. Torii should encode that same reasoning before it
mutates the network.

## Definitions

- Complex junction: a junction or compact junction cluster with several nearby
  OSM nodes, multiple modal layers, multiple named roads, service/slip lanes, or
  a high number of internal connections.
- Approach: a directional road entry or exit leg connected to the junction core.
  An approach is derived from road name/ref, highway class, direction, lane
  count, permissions, and geometry.
- Road group: a set of SUMO edges that represent the same real road leg or road
  corridor near the junction.
- Movement: a permitted lane-to-lane relation from one incoming approach to one
  outgoing approach, classified as straight, right, left, u-turn, service
  access, pedestrian/cycle crossing, or unknown.
- Conflict core: the vehicle conflict area where drivable approach movements
  meet. It should not include unrelated support modal layers unless they are
  explicitly confirmed as part of the same junction core.
- Support modal layer: sidewalks, crossings, cycleways, railway/tram paths, and
  service access elements that may touch the same geographic area but should not
  automatically become vehicle movements.
- Rebuild candidate: generated SUMO plain-XML or patched net files that replace
  ambiguous inferred movements with explicit audited movements.

## Inputs

- Current SUMO network produced by Torii.
- OSM-derived tags and geometry, when available.
- Optional reference network, such as TUM Ingolstadt, for development-time
  scoring only.
- Optional map/reference observation for human review, but not as a required
  automated dependency.
- Existing Torii audits: dense junction clusters, modal support analysis,
  corridor grouping, footprint generation, residual collapse audit, routeability.

## Workflow

1. Detect complex junctions that need movement rebuild.
   - Use dense node clusters, high internal connection count, nearby TLS nodes,
     overlapping junction circles, residual collapse warnings, and NetEdit/SUMO
     connection warnings.
   - Do not rebuild every junction by default.

2. Collect local context.
   - Extract all edges, lanes, nodes, internal edges, connections, crossings,
     walking areas, and permissions within the target junction envelope.
   - Preserve OSM ids, names, refs, highway classes, one-way tags, lane counts,
     turn lanes, and modal permissions when available.

3. Build the approach model.
   - Group incoming and outgoing road segments into approaches using road
     identity, direction, geometry, highway class, and modal permissions.
   - Keep vehicle, pedestrian, bicycle, tram/rail, and service support layers
     separate until a rule explicitly merges them.

4. Derive the movement graph.
   - For each incoming vehicle approach, identify compatible outgoing vehicle
     approaches.
   - Classify candidate movements by angle and road identity.
   - Apply OSM restrictions, lane-turn tags, one-way rules, and modal
     permissions before geometry-only inference.

5. Audit before mutation.
   - Emit a movement review artifact that lists all approaches, movements,
     confidence scores, dropped ambiguous movements, and unknowns.
   - Any movement with low confidence must be marked for review rather than
     silently emitted as a connection.

6. Generate a rebuild candidate.
   - Remove or bypass old inferred internal movement fragments inside the
     conflict core.
   - Generate explicit SUMO connections for high-confidence vehicle movements.
   - Preserve support modal layers unless the movement graph explicitly
     classifies them as part of the conflict core.

7. Rebuild and post-audit.
   - Run `netconvert` on the candidate.
   - Check SUMO load, residual old-core nodes/edges, connection warnings,
     routeability, and movement graph consistency.

8. Review.
   - Open the result in NetEdit connection mode for the target junction.
   - Generate a human-readable review artifact for all uncertain movements and
     support-layer decisions.

## Movement Logic Rules

- Same-road continuation is usually straight, even when the geometry bends near
  the junction.
- Different-road movements are classified by signed turn angle: right, left,
  straight-like, or u-turn.
- `turn:lanes`, turn restrictions, `oneway`, `access`, `vehicle`, `motor_vehicle`,
  `bicycle`, `foot`, `bus`, and similar tags override geometry.
- Lane compatibility is required: a movement is valid only if source and target
  lane permissions and lane direction are compatible.
- Service and slip lanes may connect to the vehicle core, but they must not
  expand the conflict core unless they carry actual drivable movements through
  the intersection.
- Pedestrian and bicycle layers can overlap the vehicle conflict core in space,
  but they are not vehicle movements.
- Nearby signalized pedestrian crossings do not prove that all nearby nodes
  belong to one vehicle junction.
- If two real intersections are close together, road-name continuity alone must
  not chain them into one giant junction.

## Output Requirements

For each rebuild candidate, Torii should produce:

- `movement_graph.json`: approaches, movements, modal layers, confidence, and
  audit status.
- `approaches.csv`: one row per approach with road identity, direction, lane
  count, permissions, and geometry summary.
- `movements.csv`: one row per movement with source approach, target approach,
  turn class, reason, confidence, and emitted/skipped status.
- Candidate SUMO plain-XML or patched network files.
- `movement_audit.json`: pass/review/fail summary.
- `collapse_audit.json`: old-core residual topology status.
- Review HTML or NetEdit artifact that highlights uncertain movements.

## Non-Goals

- Do not try to produce byte-identical TUM networks.
- Do not hardcode Ingolstadt road ids, junction ids, or TUM shapes into the
  production rule.
- Do not require Google Maps scraping or a private API for the automated path.
- Do not globally apply rebuild logic until single-junction evidence is
  acceptable.
- Do not merge support modal layers into the vehicle core merely because they
  are close in screen space.

## Validation

- Unit tests for turn classification, approach grouping, modal separation, and
  movement filtering.
- Small fixture networks for cross, T, skewed, close-pair, service-lane, and
  bicycle/pedestrian overlap cases.
- Single-junction Ingolstadt prototype at the known difficult intersection.
- SUMO load proof.
- Routeability on the connected vehicle core.
- NetEdit connection-mode review against TUM reference only as development-time
  evidence.

## Claim Boundary

Until the first target junction passes NetEdit connection-mode review, this is a
diagnostic/prototype feature. It may produce better artifacts and clearer
review decisions, but it must not be claimed as a general automatic junction
cleaning solution.

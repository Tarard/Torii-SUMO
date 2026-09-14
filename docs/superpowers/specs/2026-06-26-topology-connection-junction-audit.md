# Topology and Connection Driven Junction Audit Spec

## Target

Torii-SUMO needs a diagnostic path that can recognize missed junction
aggregation candidates from road topology and connection behavior, not only
from Google Maps review, dense-node radius, or reference-network matches.
It should also learn cleanup policy from a high-quality manual reference such
as the TUM Ingolstadt network by extracting reusable modeling decisions, not by
copying city-specific ids.

The immediate target is the Ingolstadt complex junction family around the
`281967823` reference case and the neighboring location shown in NetEdit where
the current code failed to mark an apparently aggregatable area. The production
target is a general audit that says:

- this place behaves like one physical junction from topology;
- this place should not be aggregated because it is two close intersections;
- this rebuilt junction has too many or wrong movements compared with its
  topology and, when available, a manual reference such as TUM;
- this reference network consistently models a road, junction, TLS, or
  movement class differently from Torii, and the difference can be stated as a
  cleanup rule.

## Control Loop

- target: detect aggregation candidates and bad movement graphs from SUMO road
  topology plus NetEdit/netconvert connection signals.
- current_state: Torii can create dense-junction, overlapping-junction,
  reference-join, and movement-rebuild artifacts, but it still misses some
  visually obvious aggregatable locations and emits too many top-level external
  movements for the rebuilt `281967823` junction.
- deviation: Google Maps or TUM comparison can reveal the issue after the fact,
  but the code does not yet use the road graph itself as a strong enough
  evidence source.
- control_action: add a topology-and-connection audit before mutation, then use
  its output to tighten movement emission.
- feedback: connection-mode comparison, netconvert warning classification,
  topology-cell candidates, TUM development-time delta, SUMO load, and NetEdit
  human review.
- stopping_condition: the known missed screenshot location is flagged as a
  reviewable aggregation candidate, and the `281967823` rebuilt junction no
  longer emits a near-Cartesian incoming-to-outgoing movement set.

## Observed Problems

### Missed Aggregation Candidate

The user identified a location in NetEdit where the current code did not mark a
junction as aggregatable, even though the road geometry and connection behavior
look like one physical intersection. This is a failure of the current
candidate-discovery layer, not just a failure of final connection generation.

The suspected missing signal is local topology:

- several road legs converge into a compact conflict area;
- short connector or internal edges bind the same movement cell;
- the lane connection layout behaves like one junction;
- support layers such as crossings and cycleways are attached to the same
  conflict area but should not by themselves force or block vehicle aggregation.

This should be detected without requiring Google Maps. Map review remains a
confirmation and boundary check, not the only source of candidate discovery.

### Over-Emitted Movements

The current movement prototype emits movements too broadly. For the
`281967823` target, the diagnostic comparison showed:

- Torii rebuilt target junction: `37` top-level external lane connections and
  `32` movement pairs.
- TUM reference target junction: `21` top-level external lane connections and
  `16` movement pairs.
- Torii target netconvert warnings: `5` target-specific intersecting-left-turn
  lines.
- TUM target netconvert rewrite: no target-specific intersecting-left-turn
  warning in the diagnostic run, only a signal-program unused-state warning.

The root implementation cause is the current rule in
`junction_movement_model.build_movement_graph`: for every incoming vehicle
approach, it evaluates every outgoing vehicle approach and emits all
non-`u_turn` / non-`unknown` movements. That behaves like a filtered Cartesian
product. It is useful for a first diagnostic prototype, but it is too permissive
for cleanup.

## Definitions

- Topology cell: a compact local road graph region whose internal edges,
  junctions, and connection patterns behave as one physical conflict area.
- External approach: a non-internal edge that enters or exits the topology cell.
- Top-level external movement: a SUMO `<connection>` from an incoming external
  approach to an outgoing external approach through the junction.
- Internal continuation: a connection involving a generated internal edge or
  an internal lane. It helps explain the geometry but should be separated from
  top-level movement counts.
- Connection signature: counts and classes of top-level external movements,
  internal continuations, turn directions, lane multiplicity, states, and
  netconvert/NetEdit warnings for a junction.
- Missed aggregation candidate: a topology cell that has physical-intersection
  evidence but is absent from current dense, overlapping, and reference-join
  candidate outputs.
- Development reference delta: a comparison against TUM or another manual
  reference used to learn and debug rules. It must not become a hardcoded
  production dependency.
- Teacher policy report: a summary of reference-network decisions such as road
  classes, permissions, joined-junction patterns, TLS grouping, and connection
  signatures that can be reused as scoring evidence.

## Inputs

- Torii-generated SUMO `.net.xml` before and after collapse/rebuild.
- Existing topology audit outputs.
- Existing overlapping-junction audit outputs.
- Existing reference-join audit outputs when a reference net is supplied.
- Movement review artifacts from the complex junction prototype.
- `netconvert` rewrite logs and NetEdit connection-mode observations.
- Optional TUM reference network for teacher-policy extraction and
  development-time scoring.
- Optional map review evidence for confirmation.

## Required Audits

### 0. TUM Teacher Policy Audit

When the TUM reference network is available for the same bounded area, Torii
should first treat it as a teacher artifact and infer cleanup policy from the
network itself. The target is not byte-identical output. The target is to
discover which modeling choices TUM made and whether those choices can be
expressed as topology, connection, permission, or lane rules.

Policy layers to extract:

- road-class and permission policy: which `highway.*` classes appear, which
  classes are passenger-drivable, and whether `highway.service` or support
  layers are visual-only or routeable;
- junction aggregation policy: which source OSM nodes are encoded into
  `cluster_*` ids, how many source nodes are typically joined, and what short
  internal edges or approach counts justify joining;
- TLS policy: how many physical signalized intersections exist after grouping,
  how TUM assigns `tlLogic`, and which geometry nodes remain non-controller
  nodes;
- connection policy: top-level external movement counts, turn-class
  distribution, lane multiplicity, internal continuation structure, and warning
  behavior;
- support-layer policy: how pedestrian, bicycle, crossing, bus, and service
  features are retained without dominating vehicle-core cleanup.

The audit should emit a `reference_policy_report` that can be compared with
Torii outputs. Production logic may use the learned policy as scoring evidence
only after the policy is expressed as a general rule. It must not depend on
hardcoded Ingolstadt ids.

### 1. Topology-Cell Candidate Audit

Torii should scan local road topology for compact cells that behave like one
physical junction even if the existing dense-node scorer misses them.

Candidate evidence:

- at least three external vehicle approaches;
- short internal or connector edges linking candidate core nodes;
- a connected local subgraph whose boundary edges form a recognizable
  intersection footprint;
- multiple top-level junctions participating in one connection area;
- traffic-light or connection-mode evidence near the cell;
- support modal layers attached to the cell but not dominating it.

Reject evidence:

- long corridor chain between separate intersections;
- grade-separated edges, ramps, motorway/trunk connectors, or roundabout
  semantics;
- support-only cells without vehicle movement core;
- two close intersections connected by a normal road segment rather than a
  shared conflict area.

The audit is non-destructive. It should emit candidate records with node ids,
internal edges, boundary edges, approach count, role counts, reason, confidence,
and a review URL when coordinates are available.

### 2. Connection Signature Audit

For a target junction or candidate cell, Torii should parse the SUMO connection
graph into separate layers:

- top-level external connections;
- incoming-to-internal connections;
- internal-to-outgoing connections;
- internal continuations;
- unrelated nearby connections.

The report should include:

- incoming/outgoing edge and lane counts;
- top-level external lane connection count;
- top-level external movement-pair count;
- turn-direction counts from SUMO `dir` and geometry-derived direction;
- movement pair multiplicity;
- lane states and TLS link index counts;
- support-layer and vehicle-layer connection counts;
- target-specific netconvert warnings.

This audit should become the machine-readable version of what NetEdit
connection mode is showing visually.

### 3. Reference Connection Delta

When a manual reference such as TUM is supplied, Torii should compare connection
signatures at matched junctions. The comparison should not require identical
edge ids. It should first compare aggregate structure:

- incoming/outgoing approach count;
- top-level external movement count;
- turn-class distribution;
- support-layer participation;
- warning types.

When source-node or edge-id matches exist, it may also compare exact movement
pairs. Exact pair comparison is diagnostic only because SUMO edge splitting can
differ between networks.

### 4. Movement Emission Gate

Movement generation must stop using a broad incoming-by-outgoing product as the
default emit rule.

A movement may be emitted only when at least one strong reason exists:

- same-road continuation with compatible direction and lane permissions;
- explicit existing SUMO connection retained from a trusted source;
- lane-turn or turn-restriction evidence;
- reference-derived equivalent movement during development scoring;
- high-confidence topology-cell rule that selects one target among nearby
  parallel alternatives.

Otherwise the movement must be marked `needs_review` and excluded from the
candidate `.con.xml`.

## Outputs

For each target junction or candidate cell:

- `reference_policy_report.json` when a teacher network is supplied
- `reference_policy_report.md` when a teacher network is supplied
- `topology_connection_candidates.csv`
- `topology_connection_candidates.json`
- `connection_signature.json`
- `connection_records_layered.csv`
- `top_external_connections.csv`
- `reference_connection_delta.json` when a reference is supplied
- `reference_connection_delta.csv` when a reference is supplied
- updated `movement_audit.json` with connection-signature issues
- updated review HTML section linking the CSV/JSON artifacts

## Validation

Unit and fixture tests should cover:

- a TUM-like teacher network where road-class, permission, cluster, TLS, and
  connection policies are extracted without hardcoded city ids;
- a compact four-leg cell that current radius-only logic can miss;
- a close pair of intersections that must not be merged;
- a support-layer-heavy crossing cell that must not become a vehicle core by
  itself;
- connection signature separation between top-level movements and internal
  continuations;
- a movement graph that refuses to emit the Cartesian product;
- a TUM-like target where Torii movement counts are compared against reference
  counts without requiring byte-identical edge ids.

Single-junction validation should cover:

- the screenshot-missed location is flagged as an aggregation candidate;
- the `281967823` target produces fewer emitted movements than the current
  prototype and no target-specific intersecting-left-turn warning from the
  emitted `.con.xml` candidate, or remains explicitly `review` with those
  warnings preserved as blockers;
- SUMO can load the candidate network;
- NetEdit connection mode is used as the final visual diagnostic gate.

## Non-Goals

- Do not scrape Google Maps or require a private map API.
- Do not hardcode Ingolstadt or TUM ids into production logic.
- Do not make connection signature matching byte-identical to TUM.
- Do not globally auto-join all detected topology cells.
- Do not claim experiment-ready signal control from a connection-clean net.
- Do not hide NetEdit warnings by filtering them out of reports.

## Claim Boundary

This remains `diagnostic-demo` or `construction-invalid` until:

- the missed screenshot location is flagged by topology/connection evidence;
- the target candidate loads in SUMO;
- NetEdit connection mode no longer shows obvious wrong movement geometry for
  the target junction;
- routeability and residual-collapse checks still pass after any adopted
  candidate.

Passing this audit supports a stronger construction workflow, not a formal
traffic-control experiment claim.

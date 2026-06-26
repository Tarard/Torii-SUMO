# Modal-Aware Junction Aggregation Spec

## Target

Improve Torii-SUMO junction aggregation by separating road users, transport modes, and grade-separated infrastructure before any dense junction cluster is considered joinable.

The first deliverable is audit-only: topology audit and workflow review HTML must explain why a dense cluster is a vehicle-core join candidate, a modal support layer, a protected terminal, a hard no-join case, or a manual review case.

## Control Loop

```text
target:
  avoid wrong junction joins while still finding over-fragmented OSM/SUMO urban intersections
current_state:
  topology_audit finds dense clusters and scores cross/T geometry;
  road_corridor blocks cross-cell chains;
  junction_aggregation can build non-destructive review variants
deviation:
  dense clusters still mix vehicle roads, service roads, footways, cycleways, rail, ramps, and grade-separated geometry
control_action:
  add a reusable modal aggregation policy and expose its decision in audit outputs
feedback:
  unit tests, unchanged existing topology tests, Ingolstadt audit counts, HTML review visibility
stop_condition:
  suspicious clusters carry modal decision fields and hard modal blockers are not offered as automatic join candidates
```

## Problem

OSM represents a real street scene as many tagged ways. SUMO represents a simulation network as directed edges, lanes, junctions, connections, traffic lights, crossings, walkingareas, and internal links. A real intersection may include vehicle lanes, pedestrian crossings, cycle tracks, tram tracks, access roads, islands, slip lanes, and grade-separated elements.

Geometry alone cannot decide whether nearby junctions should be merged. The correct question is:

```text
Do these SUMO junctions belong to the same same-level controlled vehicle conflict core?
```

If not, they may still be useful visual or routing context, but they should not be collapsed into the vehicle junction core by default.

## Definitions

### Vehicle Core

The primary road conflict area for passenger vehicles, buses, and trucks on normal urban roads.

Typical SUMO/OSM types:

- `highway.primary`
- `highway.secondary`
- `highway.tertiary`
- `highway.unclassified`
- `highway.residential`
- `highway.living_street`

Vehicle core edges may be joined when topology, corridor, and map review evidence support one physical intersection.

### Shape Support

Infrastructure that helps explain the physical intersection footprint but should not be used by itself to enlarge the vehicle core.

Examples:

- pedestrian crossings;
- walkingareas;
- sidewalks;
- painted bike lanes;
- short crossing connectors inside a junction.

Shape support should appear in audit/HTML, but it should not make an otherwise weak cluster joinable.

### Protected Terminal

A nearby access or modal endpoint that touches the road network but should usually remain outside the joined vehicle core.

Examples:

- `highway.service`
- `service=driveway`
- `service=parking_aisle`
- parking access;
- independent cycle tracks;
- standalone footways.

These can be manually included only when map/reference evidence says they are part of the physical intersection core.

### Never Join

Infrastructure that must not be merged into an urban vehicle junction core without an explicit reference override.

Examples:

- `railway.*`
- `highway.motorway`
- `highway.trunk`
- `highway.*_link` ramps outside a normal street junction;
- bridge/tunnel/layer-separated geometry;
- roundabouts when the intent is preserving roundabout topology.

### Review Required

Cases where the policy cannot safely classify the cluster from SUMO/OSM tags alone.

Examples:

- mixed tram and vehicle lanes;
- cycle tracks crossing a signalized vehicle intersection;
- service roads inside a station plaza;
- nearby separate intersections;
- large channelized signalized junctions;
- conflicting OSM/SUMO type evidence.

## Modal Decision Values

Every dense cluster should receive:

```json
{
  "modal_aggregation_decision": "join_core | shape_support | protected_terminal | never_join | review_required",
  "modal_primary_role": "vehicle_core | pedestrian | bicycle | service | rail | ramp | grade_separated | mixed | unknown",
  "modal_reason": "short human-readable explanation",
  "modal_risk_flags": ["service_terminal", "railway_present"]
}
```

Decision meaning:

| Decision | Meaning | Effect on aggregation |
|---|---|---|
| `join_core` | cluster is compatible with vehicle-core joining | may remain a join candidate if topology/corridor also pass |
| `shape_support` | modal context supports review but not joining | keep for HTML, do not auto-join from this evidence alone |
| `protected_terminal` | likely endpoint or access terminal | remove from automatic join candidates unless reference/manual review overrides |
| `never_join` | hard modal blocker | do not offer automatic join |
| `review_required` | ambiguous or mixed evidence | keep as human review item |

## Classification Rules

### Hard Blockers

Return `never_join` when any of these are present in internal or boundary edges:

- `railway.*`, unless future workflow explicitly handles at-grade tram-road shared space;
- `highway.motorway` or `highway.trunk` in an urban junction aggregation candidate;
- `highway.*_link` with ramp/interchange risk;
- `bridge`, `tunnel`, or non-zero `layer` evidence;
- `junction=roundabout` or a SUMO roundabout marker when preserving roundabout topology.

### Vehicle Core Candidate

Return `join_core` when:

- internal and boundary evidence is dominated by ordinary passenger-drivable urban road classes;
- no hard blocker is present;
- service/parking/access edges are not dominant;
- pedestrian/bicycle-only edges are not the only reason the cluster is dense.

Topology and corridor checks still decide whether the cluster is actually a join candidate.

### Service and Parking

Return `protected_terminal` when service/parking/driveway/alley evidence is dominant or when the only short internal fragments are service-access fragments.

If service edges are mixed into a strong vehicle-core cluster, return `review_required` instead of `join_core`, because the service road may be a terminal that should not enlarge the junction core.

### Pedestrian

Return `shape_support` for crossing/walkingarea/sidewalk-only clusters.

Return `review_required` when pedestrian crossings are mixed with vehicle-core edges and the topology scorer also marks the cluster as large, overlapping, or signalized. This tells the user the crossing may define the visual footprint, but the vehicle core still needs review.

### Bicycle

Return `shape_support` for painted or lane-attached bike infrastructure.

Return `protected_terminal` for independent `highway.cycleway` or bicycle-only connectors unless the cluster is already a strong vehicle-core candidate and map/reference evidence includes it in the intersection core.

### Rail and Tram

Return `never_join` for generic `railway.*`.

Future at-grade tram handling may downgrade selected tram-road clusters to `review_required`, but this first phase should not auto-join rail with vehicle junctions.

### Grade Separation

Return `never_join` when bridge/tunnel/layer evidence indicates different vertical levels.

This is a hard safety rule because two ways can overlap in screen space without intersecting in reality.

## Output Requirements

Topology audit JSON must include:

```json
{
  "modal_policy_status": "pass | not_run | failed",
  "modal_decision_counts": {
    "join_core": 0,
    "shape_support": 0,
    "protected_terminal": 0,
    "never_join": 0,
    "review_required": 0
  },
  "junction_aggregation_blocked_by_modal_count": 0
}
```

Every suspicious cluster CSV row must include:

```text
modal_aggregation_decision
modal_primary_role
modal_reason
modal_risk_flags
```

Workflow review HTML must show:

- modal decision count summary;
- a small legend for modal decisions;
- per-cluster reason text for review candidates.

## Workflow Contract

This phase must not overwrite source networks and must not directly adopt modal policy output as a final cleaned network.

Allowed:

- mark automatic join candidates as blocked by modal policy;
- expose modal classes in JSON/CSV/HTML;
- use modal fields as input to a later non-destructive aggregation variant.

Not allowed in this phase:

- direct destructive `.net.xml` rewrites;
- Google Maps scraping;
- hardcoding Ingolstadt, TUM, or one intersection name into production logic;
- claiming TUM-quality output from modal audit alone.

## Validation

Minimum validation:

- unit tests for each modal class;
- existing topology, corridor, HTML, and workflow tests still pass;
- Ingolstadt visual-detail audit reports modal decision counts;
- hard blockers do not appear in automatic junction aggregation candidate counts.

Recommended Ingolstadt feedback fields:

```text
suspicious_cluster_count
junction_aggregation_candidate_count
junction_aggregation_blocked_by_corridor_count
junction_aggregation_blocked_by_modal_count
modal_decision_counts
worst_never_join_clusters
worst_review_required_clusters
```

## Claim Boundary

Allowed claim:

```text
diagnostic-demo: Torii can now explain modal reasons why dense clusters are joinable, blocked, or review-required.
```

Not allowed yet:

```text
Torii can automatically reconstruct all complex intersections.
Torii can match TUM-style junctions without manual/map/reference review.
The modal policy proves signal timing, phasing, or legal traffic operation.
```


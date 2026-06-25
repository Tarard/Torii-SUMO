# Map Reference Junction Aggregation Design

## Target

Build a reusable map-reference experiment path for Torii-SUMO junction cleanup. The first experiment uses the Ingolstadt city-center bbox and the TUM SUMO network as a teacher, but the resulting method must generalize to areas that do not have a TUM reference network.

The goal is not to make Torii output byte-identical TUM networks. The goal is to learn and validate a reference-driven cleanup method that can explain and improve the major remaining gap:

- TUM reference: 1752 junctions, 3577 edges, 29 traffic-light junctions, 28 `tlLogic`.
- Torii 5.5 reference visual detail after TLS aggregation: 2997 junctions, 6126 edges, 34 traffic-light junctions, 34 `tlLogic`.
- Current OSM-signal/topology probe: 166 dense clusters -> 16 strong signalized auto-join candidates, but it only captures 11 TUM-matched clusters and 7 TUM traffic-light matched clusters.

## Current Evidence

Torii already has useful pieces:

- `topology_audit.py` detects dense junction clusters and scores cross/T/multi-arm approach-axis shapes.
- `reference_join_audit.py` mines TUM joined-junction cases and matches source-node ids against a candidate network.
- `tls_aggregation.py` reduces SUMO traffic-light noise by selecting one representative TLS per physical cluster.
- `junction_aggregation.py` can create non-destructive `netconvert --junctions.join` review variants.
- `reference_scope.py` can detect over-represented detail relative to a reference and build pruning variants.

The gap is that these tools do not yet share one explicit reference model. OSM signal tags and topology shape help, but they cannot explain TUM's non-signalized priority/dead-end joins or distinguish all channelized urban junctions from road-detail fragments.

## Core Hypothesis

The right control object is a `MapReferenceGraph`, not a raw OSM file, a Google screenshot, or a TUM network by itself.

For the Ingolstadt experiment, the `MapReferenceGraph` is teacher-derived from TUM and enriched with OSM/topology/Google-review fields. Later, when no TUM reference exists, the same structure can be populated from Google Maps visual evidence plus OSM source tags and Torii topology candidates.

## MapReferenceGraph Schema

The first version is a JSON document with these top-level fields:

```json
{
  "bbox": "11.413800,48.755391,11.433800,48.775391",
  "reference_sources": {
    "teacher_net": "TUM-VT/sumo_ingolstadt city-center bbox cut",
    "candidate_net": "Torii 5.5 reference visual detail TLS aggregated",
    "osm_extract": "reference visual detail filtered OSM",
    "map_visual_source": "Google Maps URL or screenshot packet when available"
  },
  "physical_intersections": []
}
```

Each `physical_intersections` entry represents one candidate physical junction:

```json
{
  "id": "map_ref_int_0001",
  "center_lat": 48.7694325,
  "center_lon": 11.4213104,
  "reference_origin": "tum_teacher",
  "teacher_reference_id": "cluster_...",
  "teacher_type": "traffic_light",
  "teacher_source_node_ids": ["1242949438", "2230504053"],
  "sumo_candidate_cluster_id": "C021",
  "sumo_candidate_node_ids": ["1242949438", "2230504026"],
  "topology_shape": "cross",
  "topology_score": 0.8,
  "approach_count": 11,
  "internal_edge_count": 41,
  "osm_signal_support": "vehicle_signal",
  "osm_highway_types": ["highway.primary", "highway.secondary"],
  "road_names": ["..."],
  "grade_separation_risk": false,
  "ramp_or_interchange_risk": false,
  "service_or_parking_risk": false,
  "google_review_status": "not_reviewed",
  "google_maps_url": "https://www.google.com/maps/@48.7694325,11.4213104,50m",
  "recommended_action": "join",
  "confidence": "teacher_confirmed",
  "reason": "TUM joined source nodes and Torii has a matching dense cross-shaped cluster"
}
```

## Evidence Roles

### TUM Teacher

TUM is used to create labels, not permanent hardcoded rules. It supplies:

- source-node groups that humans or prior tooling joined;
- teacher junction type such as `traffic_light`, `priority`, `dead_end`, or `right_before_left`;
- weak ground truth for which Torii dense clusters are worth joining;
- target distribution for junction/edge/TLS counts.

TUM must not appear as a special case in future production workflow logic.

### OSM Source

OSM supplies:

- `highway=traffic_signals`, `crossing=traffic_signals`, and `traffic_signals:*` signal evidence;
- road names and `highway` classes;
- service/parking/private access risk;
- ramp/link road risk;
- bridge/tunnel/layer hints for grade separation.

OSM signal evidence is a positive signal for signalized junctions, but not enough to explain non-signalized TUM joins.

### Topology

Torii topology supplies:

- dense cluster membership;
- cross/T/multi-arm shape classification;
- approach-axis separation and score;
- short internal edge evidence;
- internal/boundary edge counts.

Topology is the main candidate generator. It is not proof of safe joining by itself.

### Google Map Visual Evidence

Google Maps is treated as external visual review evidence, not as a source to scrape or cache into a derived road dataset. The first implementation should emit stable review URLs and optional screenshot packet slots. If a screenshot is provided by the user or a permitted capture path, its structured interpretation should be stored as review metadata, not as a replacement for OSM.

Google review fields:

- `google_review_status`: `not_reviewed`, `single_intersection`, `separate_intersections`, `grade_separated`, `roundabout_or_ramp`, `ambiguous`.
- `google_signal_evidence`: `visible_vehicle_signal`, `no_vehicle_signal_visible`, `unclear`.
- `google_channelization_evidence`: `simple`, `channelized_single_intersection`, `separated_roads`, `unclear`.

## Experiment Flow

### Phase 1: Teacher Graph Construction

Use `reference_join_audit` output to create `map_reference_graph_teacher.json`.

For each TUM joined-junction case:

1. Record the teacher source-node group and type.
2. Attach the matched Torii candidate cluster when available.
3. Attach Torii topology shape and risk fields.
4. Attach OSM signal, road-name, and highway-class evidence.
5. Emit a Google Maps URL for later visual review.

Expected output:

- `map_reference_graph_teacher.json`
- `map_reference_intersections.csv`
- `teacher_rule_summary.json`

### Phase 2: Candidate Policy Replay

Run multiple policy variants against the teacher graph:

- `teacher_confirmed_all`: join every TUM teacher case matched to Torii nodes.
- `topology_osm_signal_only`: join only cross/T plus OSM vehicle-signal supported candidates.
- `topology_teacher_generalized`: join cross/T plus non-ramp low-risk clusters that match teacher-like source-node and edge patterns, including non-signalized cases.
- `strict_google_ready`: join only clusters that would require positive Google visual review before adoption.

Each policy emits:

- selected candidate ids;
- rejected candidate ids and reasons;
- expected recall/precision against TUM teacher labels;
- non-destructive join node XML or join candidate file.

### Phase 3: Selective Aggregation Variant

Build network variants from selected candidates. The first experiment can use `netconvert --junctions.join` with a selected node file if reliable; if not, it must stop before destructive transformation and report that selective application is not yet implemented.

For each variant:

- write the exact netconvert command;
- preserve the source network;
- count edges, lanes, junctions, traffic-light junctions, and `tlLogic`;
- run topology audit;
- run connectivity and routeability audit;
- compare to TUM reference.

### Phase 4: Interpretation

A variant is considered promising only if it improves the remaining gap without damaging usability:

- junction count and edge count move toward TUM without collapsing real road detail;
- routeability passes with no collisions or teleports in the audited connected core;
- topology dense-cluster count decreases;
- TLS count does not regress from the current 34-ish physical representatives;
- failed/ambiguous cases are reported as review items instead of silently joined.

## First Experiment Inputs

- Candidate net: `C:\Users\huqio\Documents\Torii-SUMO\examples\02_one_prompt_osm_network\networks\torii_5_5_reference_visual_detail_tls_aggregated.net.xml`
- TUM reference net: `C:\Users\huqio\Documents\Torii-SUMO\examples\02_one_prompt_osm_network\networks\tum_ingolstadt_center_reference.net.xml`
- OSM source: `C:\Users\huqio\Documents\Codex\2026-06-24\ingolstadt_reference_visual_detail_spark53\osm\sumo_osm_cleanup_reference_visual_detail_filtered.osm.xml.gz`
- Working output dir: `C:\Users\huqio\Documents\Codex\2026-06-25\ingolstadt_map_reference_probe`

## Success Criteria

The first experiment succeeds if it produces a reproducible evidence bundle with:

- a valid `MapReferenceGraph` with TUM teacher, topology, OSM, and Google-review URL fields;
- at least two policy replay reports, including one teacher-confirmed upper bound and one generalized non-TUM-specific policy;
- a clear statement of whether selective aggregation can be built with current netconvert tooling;
- if a variant is built, routeability and topology validation results;
- a comparison table against TUM and the current Torii baseline.

## Claim Boundary

Allowed claims:

- diagnostic-demo evidence that the map-reference approach explains or fails to explain TUM joins;
- which evidence fields are missing for generalization;
- whether a candidate policy improves counts and topology on this bbox.

Prohibited claims:

- that Torii can now produce TUM-quality networks generally;
- that Google visual evidence proves signal timing or phasing;
- that OSM traffic-signal tags alone are enough to identify all physical junction joins;
- that a GUI/plot view is sufficient validation without routeability and topology checks.

## Non-Goals

- No hardcoded Ingolstadt production rules.
- No automatic Google Maps scraping or persistent derived Google road dataset.
- No overwrite of committed example networks.
- No claim that matching TUM exactly is the product objective.

## Integration Path After Experiment

If the experiment succeeds, fold the method into Torii in this order:

1. Add a reusable `map_reference.py` core module for the schema and policy replay.
2. Add tests around small synthetic reference/candidate networks.
3. Add an MCP tool such as `sumo_network_map_reference_audit`.
4. Add optional workflow integration only after standalone tool validation.
5. Update both SUMO skill copies and docs to route reference-driven cleanup through the new audit before aggregation.

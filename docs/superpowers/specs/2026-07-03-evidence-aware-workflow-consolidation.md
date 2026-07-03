# Evidence-Aware Workflow Consolidation Spec

## Target

Torii-SUMO should consolidate around one research and product claim:

```text
Torii turns raw OSM-to-SUMO construction into a bounded, evidence-aware,
reference-comparable workflow with explicit gates for connectivity,
routeability, TLS reality, topology fragmentation, and manual-review
promotion.
```

The project must not claim automatic generation of a perfect SUMO network from
arbitrary OSM input. The defensible claim is that Torii makes imported-network
construction auditable, comparable against a cleaned reference when one exists,
and safer to promote from diagnostic artifact to experiment candidate.

## Control Loop

- target: prove that Torii's OSM-to-SUMO workflow improves auditability and
  reference comparability over raw `netconvert`, especially on the Ingolstadt
  reference-matched case.
- current_state: the `html` branch contains a broad MCP/tool stack, a large
  `run_osm_cleanup_workflow`, reference-matched Ingolstadt examples, TUM
  teacher-guided repair probes, NetEdit review helpers, and a fixed plugin
  manifest license.
- deviation: the implementation has grown through additive tools, gates, and
  report fields. The system behavior is powerful, but the architecture and
  public claim are less explicit than the actual product direction.
- control_action: freeze the near-term product claim, document the four-layer
  architecture, introduce a quality-vector vocabulary, and convert the
  Ingolstadt demo into a golden workflow benchmark before adding more repair
  heuristics.
- feedback: README wording, `ARCHITECTURE.md`, benchmark files, golden report
  tests, promotion-gate tests, HTML review cockpit tests, and unchanged current
  workflow behavior.
- stopping_condition: Torii has a documented architecture, a narrow public
  claim, a repeatable Ingolstadt benchmark trace, and review cockpit artifacts
  that explain which gates still block promotion.

## Product Claim Boundary

Allowed:

- Torii builds SUMO network artifacts from OSM through a bounded workflow.
- Torii records road scope, connectivity, routeability, TLS, topology,
  reference comparison, and review evidence.
- Torii can compare generated networks with a manually cleaned reference such
  as the TUM Ingolstadt subset.
- Torii can reduce review load with scoped variants such as connected-core,
  TLS aggregation review variants, and junction aggregation candidates.
- Torii keeps claim status explicit: `diagnostic-demo`,
  `construction-invalid`, `blocked`, or stronger labels only when the matching
  evidence exists.

Not allowed:

- Do not claim arbitrary-city TUM-level generation without a reference.
- Do not claim perfect automatic cleanup from one prompt.
- Do not promote NetEdit screenshots, SUMO load, or routeability alone into
  experiment-ready correctness.
- Do not continue adding repair heuristics unless a benchmark quality delta
  shows what they improve and what they risk.

## Architecture

The project should be described and gradually refactored into four layers.

### Router Layer

Responsibility:

- classify user intent;
- identify missing input;
- select the workflow recipe;
- keep user-facing autonomy mode and claim boundary visible.

Current anchors:

- `plugins/torii-sumo/src/torii_sumo/core/workflow_router.py`
- `plugins/torii-sumo/src/torii_sumo/tools/workflow_tools.py`

Non-responsibility:

- no network construction;
- no reference comparison;
- no report-field assembly beyond summary routing.

### Planning Layer

Responsibility:

- decide network profile;
- decide traffic layers;
- decide road scope;
- decide reference policy;
- choose validation gates.

Current anchors:

- `plugins/torii-sumo/src/torii_sumo/core/network_plan.py`
- reference policy and hierarchy helpers.

This layer should become a formal planning API. Workflow execution should
consume a plan record instead of treating planning as a loose helper call.

### Execution Layer

Responsibility:

- run bounded stages that transform or audit artifacts;
- make each stage input and output inspectable;
- preserve stage-local evidence.

Target abstractions:

```text
WorkflowState:
  plan
  artifacts
  quality
  review_items
  claim_status
  warnings

StageResult:
  stage_name
  status
  input_artifacts
  output_artifacts
  before_quality
  after_quality
  delta_quality
  promotion_decision
  claim_status
  evidence_files
  warnings
```

Initial stages:

- `BuildOSMStage`
- `ConnectivityStage`
- `TLSRealityStage`
- `ReferenceComparisonStage`
- `TeacherGuidedRepairStage`
- `RouteabilityStage`
- `ReviewHTMLStage`

The first implementation should classify existing report fields into this
shape without rewriting all stage internals.

### Review Layer

Responsibility:

- render existing evidence into HTML;
- write JSON manifests;
- write NetEdit selection/view files;
- collect review actions and patches.

Current anchors:

- `plugins/torii-sumo/src/torii_sumo/core/workflow_review_html.py`
- `plugins/torii-sumo/scripts/netedit_connection_capture.py`

Non-responsibility:

- no stage promotion decisions;
- no hidden workflow mutations;
- no automatic repair heuristics.

## NetworkQualityVector

Every major construction or repair stage should report a comparable quality
vector:

```text
NetworkQualityVector:
  connectivity
  routeability
  topology_fragmentation
  tls_semantic_delta
  junction_pattern_delta
  reference_scope_delta
  manual_review_load
```

Each value may start as a small dictionary instead of a scalar, but each stage
must expose:

```text
before_Q -> after_Q -> delta_Q -> promotion_decision
```

Promotion rule:

- a stage may promote its output only if it improves at least one declared
  target metric;
- it must not regress critical metrics unless the regression is explicitly
  categorized as acceptable diagnostic tradeoff;
- the report must state which metric drove the decision.

## Ingolstadt Golden Benchmark

Create `benchmarks/ingolstadt_reference_matched/` as the main regression
surface. It should not introduce a new city before Ingolstadt is stable.

Required files:

```text
cases.yaml
baseline_raw_netconvert.json
torii_vehicle_core.json
torii_reference_visual_detail.json
promotion_trace.json
review_load.json
summary_table.json
```

The summary table should compare:

```text
raw netconvert
-> Torii scoped build
-> TLS aggregated
-> junction candidate review
-> teacher-guided repair
-> final review HTML
```

Each column should report:

- edge count;
- junction count;
- TLS count;
- `tlLogic` count;
- routeability pass/fail;
- teleport count when a routeability smoke exists;
- manual review item count;
- reference delta score.

## Review Cockpit Requirements

HTML review output should support human cleanup decisions rather than act as a
general website.

Each review item must record:

```text
review_item_id
problem_type: TLS | topology | routeability | reference_mismatch
evidence_files
json_delta_file
netedit_selection_file
map_review_url
suggested_action: keep | remove | join | do_not_join | needs_map_review
blocked_gate
decision_patch_file
next_stage_input
```

The cockpit should expose the action queue and explain what gate each unresolved
item blocks.

## Testing Strategy

Add regression tests in three groups.

### Golden Report Tests

Use fixed small network inputs and assert key report fields only. Do not compare
full JSON bodies.

### Promotion Gate Tests

Construct before/after quality deltas and assert promote/block decisions.

### HTML Snapshot Tests

Assert that HTML contains gate names, artifact links, review queue entries, and
patch/writeback locations. Do not snapshot the complete HTML string.

## Four-Week Execution Order

### Week 1: Product Definition And Architecture

- narrow README claim;
- verify license metadata consistency;
- add `ARCHITECTURE.md`;
- write this spec and an implementation plan.

### Week 2: State And Quality Abstractions

- introduce `WorkflowState`;
- introduce `StageResult`;
- introduce `NetworkQualityVector`;
- map existing `run_osm_cleanup_workflow` report fields into grouped stage
  results without changing behavior.

### Week 3: Ingolstadt Benchmark

- create `benchmarks/ingolstadt_reference_matched/`;
- write current Ingolstadt case configuration;
- materialize benchmark JSON from committed example artifacts and current
  reports;
- add golden report regression tests.

### Week 4: Physical-Junction Review

- improve physical-junction aggregation review ranking;
- expose evidence, suggested actions, blocked gates, and patch targets in the
  review cockpit;
- keep automatic join adoption out of scope until manual review gates exist.

## Immediate Execution Boundary

This spec authorizes Week 1 implementation now. Week 2 code extraction should
start only after Week 1 docs and tests pass, because changing the workflow
shape before the product boundary is stable would add more architecture drift.

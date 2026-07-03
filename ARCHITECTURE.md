# Torii-SUMO Architecture

## Main Claim

Torii-SUMO turns raw OSM-to-SUMO construction into a bounded,
evidence-aware, reference-comparable workflow. It does not certify that an
imported network is correct, and it does not claim arbitrary-city TUM-level
cleanup from one prompt.

The strongest current product claim is:

```text
Torii builds auditable SUMO network artifacts from OSM, records construction
and review evidence, compares against a cleaned reference when one is supplied,
and keeps promotion blocked until the relevant gates pass.
```

## Layer 1: Router

The router classifies user intent, identifies missing input, chooses a workflow
recipe, and keeps autonomy mode and claim boundary visible.

Current anchors:

- `plugins/torii-sumo/src/torii_sumo/core/workflow_router.py`
- `plugins/torii-sumo/src/torii_sumo/tools/workflow_tools.py`

The router should not build networks, repair junctions, or decide whether a
repair is promoted.

## Layer 2: Planner

The planner chooses the network profile, traffic layers, road scope, reference
policy, and validation gates.

Current anchors:

- `plugins/torii-sumo/src/torii_sumo/core/network_plan.py`
- reference policy and hierarchy helpers under
  `plugins/torii-sumo/src/torii_sumo/core/`

For reference-matched workflows, the planner must keep `vehicle_core` and
`reference_visual_detail` separate. Passenger routeability claims belong to
`vehicle_core`; NetEdit and reference-topology comparisons belong to
`reference_visual_detail`.

## Layer 3: Executor

The executor runs bounded stages that transform or audit artifacts. Each stage
should eventually accept a `WorkflowState` and return a `StageResult`.

Target shape:

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

Initial stage names:

- `BuildOSMStage`
- `ConnectivityStage`
- `TLSRealityStage`
- `ReferenceComparisonStage`
- `TeacherGuidedRepairStage`
- `RouteabilityStage`
- `ReviewHTMLStage`

The first implementation should group existing report fields into this model
without changing workflow behavior.

## Layer 4: Reviewer

The reviewer renders existing evidence into human-inspectable artifacts:

- HTML review cockpit;
- JSON manifests;
- NetEdit selection and view files;
- map review links;
- review action queues;
- decision patch targets.

Current anchor:

- `plugins/torii-sumo/src/torii_sumo/core/workflow_review_html.py`

The reviewer should not make hidden workflow decisions. It should show which
gate a review item blocks and how a human decision feeds the next stage.

## Quality Vector

Major construction and repair stages should report a comparable quality vector:

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

Each stage should expose:

```text
before_Q -> after_Q -> delta_Q -> promotion_decision
```

## Promotion Rule

A stage output may be promoted only when it improves at least one declared
target metric and does not regress a critical metric without an explicit,
recorded diagnostic tradeoff. The report must state which metric drove the
decision.

## Near-Term Benchmark

The primary benchmark is Ingolstadt reference-matched OSM-to-SUMO construction.

Target directory:

```text
benchmarks/ingolstadt_reference_matched/
```

Benchmark stages:

```text
raw netconvert
-> Torii scoped build
-> TLS aggregated
-> junction candidate review
-> teacher-guided repair
-> final review HTML
```

Each stage should report edge count, junction count, TLS count, `tlLogic`
count, routeability status, teleport count when available, manual review item
count, and reference delta score.

## Non-Goals

- Do not claim fully automatic perfect network cleanup.
- Do not add more repair heuristics before benchmark quality deltas can show
  what they improve.
- Do not compare a Torii connected-core network against a full-detail manual
  reference as if they were the same scope.
- Do not use NetEdit screenshots, SUMO load, or routeability alone as proof of
  experiment-ready correctness.

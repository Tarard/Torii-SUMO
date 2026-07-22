# Torii-SUMO research-plan review handoff (2026-07-14)

This branch is a **WIP checkpoint for design review**, not a claim that arbitrary
OSM networks can already be cleaned to human-modelled quality.

## Goal under review

Build a corridor-first, evidence-driven OSM cleaning loop:

`OSM -> findings -> reversible candidate -> netconvert -> SUMO load ->`
`code-native Connection Mode audit -> routeability -> review additional.xml -> manifest`

The long-term product should automate only proven-safe edits, emit precise
review locations for uncertain edits, and fail closed when topology, lane,
multimodal, rail, bridge, or TLS semantics cannot be established.

## Evidence that is currently established

- Candidate/source identity, atomic artifact writing, manifests, rollback data,
  review-only `additional.xml`, SUMO load, routeability, topology, and protected
  semantic gates exist for the corridor contract.
- The four contracted small scenarios are reproducible from tracked inputs.
- A same-bbox Ingolstadt OSM acquisition and corridor workflow has a
  hash-bound, loadable and routeable result; teacher transfer remains review
  required rather than being applied blindly.
- `core/connection_mode_audit.py` reconstructs lane-to-lane bindings, complete
  internal paths, lane ordering, request/foe data, TLS `linkIndex` capacity and
  phase conflict evidence directly from `.net.xml`. NetEdit is optional for
  flagged visual review, not required for the automatic gate.
- Source-to-candidate Connection Mode differential auditing blocks new
  structural/review findings and identity changes outside the intended scope.
- Standard synthetic three-way and four-way NEMA candidates pass their local
  gates, but the real Ingolstadt scan deliberately auto-qualifies no junction.

## Important rejected real-network candidates

- A candidate that passed netconvert and SUMO load introduced 1,828 new
  outside-scope review findings because a plain round-trip regenerated
  pedestrian/bicycle lanes and shifted lane indices. It was rejected; the
  type-round-trip source of that global mutation was fixed.
- The current conservative partial-cell candidate has zero outside-scope
  structural/review/identity regressions, but 13 new target structural findings
  and 27 target review findings. It remains rejected and no routeability or
  promotion claim is made.
- An experimental complete shared-controller join improved the target but
  introduced seven outside-scope path endpoint gaps. It also remains rejected.

## Unverified experiment at this checkpoint

`junction_rebuild_candidate.py` currently contains an experimental boundary
geometry policy for joined cells: retain the OSM geometry at the untouched
remote endpoint, align the rebuilt endpoint with teacher internal geometry,
and distribute the displacement along the approach polyline.

This latest blend has passed lint and the existing junction-rebuild unit suite,
but **has not yet passed a new full Ingolstadt source/candidate differential
run**. It must not be treated as accepted architecture or promoted output.

## Questions for the research-plan review

1. What is the formal definition of a correctly cleaned corridor/junction?
2. Which invariants are structural, semantic, safety-critical, or necessarily
   human-reviewed?
3. When should a shared TLS controller stay as multiple physical junctions,
   become one joined cell, or receive only scoped connection repair?
4. Is endpoint-constrained geometry blending defensible, or should geometry be
   solved as a constrained optimization over the whole local cell?
5. What benchmark set, ablations, metrics, and hold-out regions are required to
   show transfer beyond Ingolstadt?
6. Which current modules should be retained, simplified, isolated as research
   prototypes, or deleted before further implementation?

The next implementation step should be chosen only after this review defines
the hypothesis, benchmark, acceptance gates, and stop conditions.

<p align="center">
  <img src="docs/assets/banner.png" alt="Torii agent plugin for SUMO banner">
</p>

# <img src="docs/assets/app-logo.png" width="42" alt="Torii logo"> Torii

<div align="center">

**Task-Oriented Road Infrastructure Intelligence**

**Agent plugin for SUMO**

<p><strong>Codex / Claude agent plugin</strong> · SUMO/TraCI workflows · OSM-to-SUMO cleanup · local MCP tools</p>

<a href="https://tarard.github.io/Torii-SUMO/"><strong>Website</strong></a> |
<a href="docs/codex-plugin-install.md"><strong>Install</strong></a> |
<a href="examples/01_signal_control_audit/task.md"><strong>Signal-Control Audit</strong></a> |
<a href="examples/02_one_prompt_osm_network/README.md"><strong>One-Prompt Demo</strong></a> |
<a href="LICENSE"><strong>License</strong></a>

[English](README.md) | [简体中文](README.zh-CN.md) | [Deutsch](README.de.md)

</div>

## Evidence-Aware OSM-to-SUMO Construction

Torii is designed for SUMO network construction work: one short natural-language prompt can become a bounded, evidence-aware, reference-comparable OSM-to-SUMO workflow with construction evidence, routeability checks, review artifacts, and a clear claim boundary.

The plugin now starts from a workflow router: `torii_auto_workflow` classifies the request, chooses skills, makes plans, and runs safe MCP steps to generate or modify the SUMO network for you.

Torii has two layers:

| Layer | Role |
|---|---|
| Reasoning layer | SUMO expert skills that ask the right questions, choose a workflow, and bound claims. |
| Execution layer | Local safe stdio MCP tools that run bounded SUMO checks and return structured observations. |

The architecture is documented in [`ARCHITECTURE.md`](ARCHITECTURE.md): router, planner, executor, and reviewer.

Current MCP tools cover the `torii_auto_workflow` router, environment checks, config preflight, smoke runs, evidence bundles, OSM network construction, TLS candidates, multi-source TLS review tables, TLS aggregation review variants, code-native whole-network and source-to-candidate Connection Mode audits, strict standard three/four-way NEMA phase-binding candidates, connectivity checks, connected-core extraction, routeability probes, completion-aware routeability audits, overlapping top-level junction audits, reference join audits, junction aggregation review variants, and optional NetEdit launch evidence.

### Current corridor acceptance boundary

Research status (2026-07-14): Stage 1-M is **Machine REVIEW_READY**. Thirty blinded held-out corridor packages, the full machine witness census, deterministic sampling, and provenance are frozen for human validation. This is not Stage 1 exit, an automatic-repair certification, or evidence that arbitrary OSM networks already reach expert NetEdit quality. See the [Stage 1-M evidence](docs/stage1-machine-review-ready-plan.md).

### Teacher-free small-network discovery

The v2 small-network path no longer requires a teacher, reviewed scope, expected topology, or expected movement count. It scans signal anchors in a frozen OSM bbox, conservatively deduplicates physical-cell candidates, selects a graph medoid, and generates boundary ports, movement variants, and a split/merge/partial-repair candidate DAG before a materialized SUMO network may be used as post-hoc evidence. XS1 recovers four approaches and twelve movements; XS2 chooses a canonical node different from the old caller seed, still binds the materialized network, and preserves the 6-versus-7 movement disagreement instead of selecting an answer. See [teacher-free discovery v2](docs/teacher-free-osm-signal-discovery-v2.md) for the design, pedestrian positive/negative controls, and reproducible results.

The v3 path now materializes one preregistered DAG variant without consuming a manual seed, reviewed scope, expected topology, or expected counts. On XS1 it generates the join patch from discovery, replaces the target's 10 fragmented TLS owners with one experimental controller, binds all 12 generated connections back to the sole movement semantic class, passes Connection Mode, independent conflict safety, zero outside-scope exact delta, SUMO load, and 12/12 routeability with zero collision or teleport. XS2 writes no candidate because its 6/7 movement variants disagree, and a held-out no-signal scene exits `not_applicable`. Merge remains an experiment rather than a topology truth claim; field timing, automatic topology selection, and automatic promotion stay blocked. See [teacher-free materialization v3](docs/teacher-free-materialization-v3.md).

The verified v4 experiment removes the remaining “merge-first” assumption. From the same automatically discovered cell it independently materializes H_S (preserve split nodes under a shared controller), H_M (merge the physical cell), and H_P (preserve topology while rebinding local TLS ownership), then applies one common gate vector. On XS1, H_M and H_P both pass all machine gates and are therefore retained as anonymous blind-review alternatives; H_S is blocked by its independent conflict result despite loading and completing 12/12 routes. On the paired/offset negative control, four signal heads do **not** authorize a merge: two conflict centers and a storage-capable connector block H_M/H_P before candidate writing, while H_S passes all gates and 12/12 routes. XS2 still fails closed before materialization. A clean rerun reproduced every normalized candidate hash and verdict; 1,341 tests and Ruff pass. This is topology discrimination for review, not topology truth, field timing, or automatic promotion. See [teacher-free topology discrimination v4](docs/teacher-free-topology-discrimination-v4.md).

```powershell
python plugins/torii-sumo/scripts/run_teacher_free_discovery.py --osm <bbox.osm.xml> --output-dir <review-output>
python plugins/torii-sumo/scripts/run_teacher_free_topology_discrimination.py --osm <bbox.osm.xml> --output-dir <topology-review-output>
python plugins/torii-sumo/scripts/verify_teacher_free_topology_v4.py
```

The workflow emits hash-bound JSON, GeoJSON, HTML, and a manifest; the source OSM remains immutable and automatic promotion stays blocked.

The implementation track is now deliberately smaller than a corridor benchmark. [`XS-1`](examples/03_xs1_four_way_tls/README.md) freezes one real four-way TLS intersection; [`XS-2`](examples/04_xs2_three_way_tls/README.md) reuses the same contract on one real three-way TLS intersection. Both require exact lane movement, internal path, request/foes, TLS binding, independent conflict, SUMO load, all-movement routeability, rollback, and outside-scope zero-delta evidence. Both remain review-only and make no city-scale claim.

The implemented promotion contract is corridor-scale: accepted edits are materialized into a separate candidate, review locations are emitted as SUMO `additional.xml`, protected semantic or TLS deltas require an exact candidate-hash-bound review decision, and promotion remains blocked until identity, netconvert, XML, SUMO load, routeability, topology, and modal-connectivity evidence pass.

Every materialized edit now produces one review package: `*.net.xml`, `*.map-review.json`, `*.accepted.review.add.xml`, `*.review.html`, `*.review.json`, and hash-bearing manifests. The `additional.xml` layer is display-only and restricted to `poi`, `poly`, and `param`; human decisions live in structured JSON. Google Maps, satellite, Mapillary, KartaView, or the regional map provider are auxiliary evidence, and become a hard gate only when an edit explicitly declares `map_review_required: true` with an explicit current or historical time scope.

The reproducible real-SUMO runner covers four-way OSM sidewalk, official pedestrian crossing/TLS review, five-way bicycle, and five-way ramp scenarios:

```powershell
python plugins/torii-sumo/scripts/run_corridor_contract_regression.py
```

It rebuilds source networks instead of relying on old generated output. The current architecture and remaining debt are recorded in [`docs/architecture-audit-2026-07-13.md`](docs/architecture-audit-2026-07-13.md).

### Code-native Connection Mode gate

`sumo_network_connection_mode_audit` reconstructs NetEdit Connection Mode directly from `.net.xml`; the OSM cleanup workflow runs it by default, while its user-facing NetEdit launch now defaults to off. For every relevant junction it validates direct `fromLane -> toLane -> via` bindings, complete internal-lane continuation, lane and permission existence, request ordering and bitstrings, turn-lane order, lane-rank/crossed mappings, incoming and outgoing motor-lane coverage, TLS `linkIndex` bounds, controller state-string lengths, shared foe signal groups, and foe movements that receive protected `G` together. SUMO-managed `rail_signal` links are classified separately instead of being mistaken for missing road `tlLogic` programs.

Results have three meanings: invalid XML/path/request/linkIndex structure is `fail`; legal but ambiguous merges, fanouts, lane drops, additions, or signal conflicts are `review_required`; only a finding-free junction is `pass`. Both non-pass classes block automatic candidate promotion. The tool writes JSON, a display-only review `additional.xml`, and a source-hash-bound manifest. NetEdit is therefore optional and limited to flagged visual review; routeability alone is never treated as lane-binding proof.

`sumo_network_connection_mode_regression_audit` is the source-to-candidate gate. It audits both `.net.xml` files, closes the declared edit scope over touched TLS-controller members, and compares per-junction finding categories without relying on unstable internal connection indices. New structural or review findings inside the target scope, any regression outside it, and unexplained outside-scope junction identity changes all block promotion. The teacher-guided repair queue runs this differential gate automatically and records its JSON, display-only `additional.xml`, and SHA-256 manifest beside every materialized full-network candidate. A failed earlier semantic/parity gate does not suppress this diagnostic audit when a candidate file exists.

On the current Ingolstadt same-bbox effective network, the whole-network audit covered 2,274 junctions and 13,169 direct movements, proving 13,169/13,169 internal paths. It found zero structural failures: 2,164 junctions pass and 110 require evidence review. The queue includes 27 incoming motor lanes without a junction connection, 19 outgoing motor lanes without a source connection, legal merge/fanout patterns, and one current TLS protected-green foe pair at junction `267517559`. Twelve implicit railway controllers are correctly recorded as SUMO runtime rail signals. No repair is inferred from those observations without OSM/map/lane evidence.

The current Südliche Ringstraße reconstruction is deliberately not promoted. The differential gate exposed a plain-XML round-trip bug that re-applied type-level `sidewalkWidth`/`bikeLaneWidth`, shifted lane indices, and created 1,828 outside-scope review regressions. Round-trip type sanitization removed that global failure. The latest safe-default candidate now has zero outside-scope structural findings, review regressions, or junction identity changes, but remains blocked on 13 new target-scope structural findings and 27 target-scope review findings because only three nodes of a more complex signal cell are mapped. An experimental whole-controller join was also rejected. No routeability claim or source-network mutation is made for either blocked candidate.

### Standard three/four-way NEMA binding

`sumo_network_standard_nema_phase_binding` is now part of the OSM cleanup boundary. With no `junction_id`, it scans the effective cleaned network and emits an eligibility queue, a dedicated Connection Mode JSON report, display-only review `additional.xml`, HTML, decision contract, and hash-bearing manifest. It does not batch-edit the network. With one eligible `junction_id`, it creates a separate reversible candidate, maps protected lefts to odd NEMA phases and through/right movements to even phases, rewrites only the selected controller's `linkIndex` groups and `tlLogic`, then requires netconvert, SUMO load, and routeability gates.

The canonical four-way mapping is cross-ring: one main approach uses left/through-right phases 5/2 and its opposite uses 1/6; the minor approaches use 7/4 and 3/8. This permits the documented compatible combinations 1+5, 1+6, 2+5, 2+6 and their minor-street equivalents. The three-way form uses SUMO NEMA missing-phase `0` placeholders and repeats phase 4 across the empty side of the second barrier. Before any candidate can be written, a hard Connection Mode gate traces every `fromLane -> toLane -> via` through its complete internal-lane chain, checks right-hand turn-lane order and lane-rank jumps, validates the request/foes matrix, and rejects any movement pair that canonical NEMA may serve concurrently when SUMO marks the pair as foes. Joined controllers, pedestrian/internal or rail links, bicycle-only movements, turnarounds, `linkIndex2`, ambiguous geometry, incomplete arm-to-arm movements, and non-dedicated protected-left lanes also fail closed. Even a fully passing candidate remains `review_required`, because the generic 90-second plan is not field-calibrated timing.

The phase/ring contract follows the official [SUMO NEMA controller documentation](https://sumo.dlr.de/docs/Simulation/NEMA.html), signal groups follow SUMO's documented [`linkIndex` state-string semantics](https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html), and request/foe indexing follows the official [SUMO road-network format](https://sumo.dlr.de/docs/Networks/SUMO_Road_Networks.html). Routeability runs enable SUMO junction-collision checking; graph reachability alone is never accepted as Connection Mode evidence.

The local SUMO 1.27.1 reference acceptance passed both a standard four-way and a T-shaped three-way: each passed Connection Mode, candidate validation, netconvert round trip, SUMO load, and 12/12 routeability with junction collision checking enabled and zero collisions or teleports. The four-way verified 12 internal movement paths and bound them to phases 1–8; the three-way verified 6 paths and used phases 1/2/4/6 with rings `1,2,0,4` and `0,6,0,4`. The current Ingolstadt same-bbox scan runs against the effective TLS-cleaned network, which SUMO loads, and found 249 TLS-junction review records, including 24 three-way and 4 four-way geometric layouts, but deliberately auto-qualified none. All 1,617 request-bound movement paths are structurally valid: 221 TLS junctions pass the Connection Mode proof, 28 are `review_required`, and none has a structural failure. Among the 28 standard geometric layouts, 15 pass and 13 require evidence review. A review finding means automatic safety cannot yet be established, not that the marked link is certainly wrong. The unified display-only review layer keeps the 28 connection-review locations distinct from the 221 locations blocked only by other NEMA-scope conditions, without changing the effective network.

### Ingolstadt teacher-corridor slice

The first same-bbox teacher slice is now executable end to end:

```powershell
python plugins/torii-sumo/scripts/run_ingolstadt_corridor_teacher.py
```

It downloads the current OSM bbox, builds a raw visual-detail network, applies only a narrowly proven structural repair, runs SUMO load and completion-aware routeability, and compares junction `267517510` with the manually cleaned TUM cell. The structural repair is a separate candidate: it removed one stale TLS identity from an already-uncontrolled pedestrian-internal connection, left 58 embedded `tlLogic` programs and 12 implicit railway controllers intact, verified the source hash was unchanged, and emitted a rollback plan plus display-only review `additional.xml`.

The latest local SUMO 1.27.1 acceptance run loaded successfully and completed 10/10 generated trips with zero collisions and teleports. Teacher transfer remains `review_required`: current OSM already supports the traffic-light control and contains three explicitly signalized crossing nodes, while the candidate still differs in pedestrian internal structure and movement signatures. Torii therefore does not replay the old teacher TLS blindly. The generated run manifest and HTML bind the exact OSM, source, candidate, map evidence, and review artifacts by SHA-256.

For deterministic replay after an online acquisition, pass both `--candidate-net` and `--source-osm`; the runner skips Overpass but keeps the exact OSM evidence in the teacher comparison and manifest. A download failure remains a blocked run rather than silently reusing cached output.

## Example

Use the prompt to test Torii:

```text
Use Torii to clean the Ingolstadt city-center network from OSM, compare it with the TUM-VT/sumo_ingolstadt cleaned network for the same bbox, run the code-native Connection Mode audit, and open only flagged junctions in NetEdit if visual review is needed.
```

This demo uses Ingolstadt city center to test whether a Torii OSM-derived workflow becomes more auditable and closer to a manually cleaned reference network than raw import success alone. The proven acceptance claim is currently the single-corridor slice above; the older full-bbox table below remains diagnostic evidence, not a city-scale automatic-equivalence claim.

![TUM bbox reference compared with Torii 5.5 TLS-aggregated visual-detail](examples/02_one_prompt_osm_network/assets/tum_vs_torii_5_5_tls_aggregated_overview.png)

| Evidence | Result |
|---|---:|
| Torii vehicle core | 2,493 edges, 3,045 lanes, 1,220 junctions in the comparison bbox after connected-core extraction |
| Torii reference visual-detail | 6,126 edges, 6,695 lanes, 2,997 junctions in the comparison bbox |
| TUM cleaned reference subset | 3,577 edges, 4,955 lanes, 1,752 junctions in the same bbox |
| Traffic-light junctions | Torii visual-detail raw 217; TLS aggregation review variant 34 vs TUM 29 |
| Remaining cleanup target | Google Maps review for the extra TLS candidates and reusable physical-junction aggregation |
| Claim status | `diagnostic-demo` |

See [`examples/02_one_prompt_osm_network`](examples/02_one_prompt_osm_network/README.md). The 5.5 comparison networks and screenshots are committed there; generated OSM extracts, route files, and full logs remain rebuild-only artifacts.

## Quick Start

Install from GitHub:

```powershell
codex plugin marketplace add Tarard/Torii-SUMO --ref main
codex plugin add torii-sumo@torii-sumo
```

Start a new Codex or Claude Code thread after installing so the plugin's skills and MCP tools are discovered.

Full setup details: [Codex Plugin Installation](docs/codex-plugin-install.md).

## What You Can Ask Me

| Prompt | What Torii Does |
|---|---|
| "Use Torii to clean the Ingolstadt city-center network from OSM and compare it with TUM-VT/sumo_ingolstadt." | Builds from OSM, checks connectivity, routeability, and code-native lane bindings, compares topology/TLS evidence with the reference, and emits a review queue; NetEdit is optional for flagged locations. |
| "Audit this TraCI signal controller before I compare it with fixed-time or max-pressure." | Checks controller identity, paired demand/seeds/horizon, TLS mapping, outputs, and completion before any performance claim. |
| "This SUMO run finishes, but tripinfo and summary disagree." | Diagnoses output consistency, unfinished vehicles, teleports, route errors, and claim boundary. |

## Boundaries

Torii builds and audits SUMO artifacts, but it does not certify a model as correct.

- OSM imports remain diagnostic until road scope, connectivity, routeability, TLS reality, and map baseline evidence are checked.
- `connected-core` networks are useful for smoke tests, but discarded fragments and topology warnings remain part of the claim boundary.
- It does not prove traffic-light timing, phasing, demand realism, controller correctness, or full experiment validity.

## License and Notices

Source code is licensed under PolyForm Noncommercial 1.0.0. Skill files, docs, checklists, examples, and protocol text are licensed under CC BY-NC 4.0. Commercial use requires separate written permission. Both scopes are recorded in [`LICENSE`](LICENSE).

Eclipse SUMO is a trademark of the Eclipse Foundation. Map data in the OSM demo is © OpenStreetMap contributors and available under the Open Database License (ODbL).

Earlier skill-only releases are archived on Zenodo: https://doi.org/10.5281/zenodo.20627976

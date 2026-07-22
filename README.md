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
<a href="docs/README.md"><strong>Documentation</strong></a> |
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

The architecture is documented in [`ARCHITECTURE.md`](ARCHITECTURE.md): router, planner, executor, and reviewer. The [repository guide](docs/repository-guide.md) explains where new work belongs, and the [MCP tool catalog](docs/mcp-tool-catalog.md) groups the public execution surface by capability.

Current MCP tools cover the `torii_auto_workflow` router, environment checks, config preflight, smoke runs, evidence bundles, OSM network construction, TLS candidates, multi-source TLS review tables, TLS aggregation review variants, code-native whole-network and source-to-candidate Connection Mode audits, strict standard three/four-way NEMA phase-binding candidates, connectivity checks, connected-core extraction, routeability probes, completion-aware routeability audits, overlapping top-level junction audits, reference join audits, junction aggregation review variants, and optional NetEdit launch evidence.

### Current corridor acceptance boundary

Research status (2026-07-14): Stage 1-M is **Machine REVIEW_READY**. Thirty blinded held-out corridor packages, the full machine witness census, deterministic sampling, and provenance are frozen for human validation. This is not Stage 1 exit, an automatic-repair certification, or evidence that arbitrary OSM networks already reach expert NetEdit quality. See the [Stage 1-M evidence](docs/stage1-machine-review-ready-plan.md).

## Hamburg corridor digital twin: evidence report

The product target is the three-node **Am Sandtorkai 2349 → 2394 → 2403** corridor. The model starts with OSM for continuous road geometry, applies bounded Torii cleanup, uses Hamburg MAP/OCIT-C/TLD and road datasets as authority for movements and signals, places SUMO detectors at official detector cross-sections, and solves for one plausible route realization whose virtual counts can be compared with the official observations. A route solution is not claimed to be a unique OD matrix.

<table>
<tr>
<td width="50%"><strong>Official Hamburg aerial, 2024</strong><br><img src="docs/assets/hamburg-digital-twin/official-aerial-2024.png" alt="Official Hamburg aerial of the Am Sandtorkai corridor"></td>
<td width="50%"><strong>Official LSBG construction plan, 2022</strong><br><img src="docs/assets/hamburg-digital-twin/official-construction-plan-2022.png" alt="Official construction plan for Am Sandtorkai and Brooktorkai"></td>
</tr>
<tr>
<td><strong>OSM-derived input topology</strong><br><img src="docs/assets/hamburg-digital-twin/osm-import-overview.png" alt="OSM-derived Hamburg topology before corridor cleanup"></td>
<td><strong>Torii cleaned corridor — full Connection Mode</strong><br><img src="docs/assets/hamburg-digital-twin/torii-cleaned-corridor-connection.png" alt="Complete repaired Hamburg corridor in NetEdit Connection Mode"></td>
</tr>
</table>

The lower-right image is a new background capture of the **complete repaired network in Connection Mode**, not a local crop. It binds to network SHA-256 `2da03214…f5c559`. A separate `NeteditTargetSession` check clicked the real 2403 network object and verified that the left pane says `Net: junction`, not polygon; that local proof is retained as repository evidence but is not used as the report's main image. The bounded 2403 single-core probe preserves all 18 boundary movements, has zero surface overlaps, loads in SUMO, and completes 18/18 movement smoke trips without collision or teleport. It remains review-only because Hamburg has not published a bindable 2403 MAP/OCIT package.

### Signals, detectors, and reconstructed routes

<p><img src="docs/assets/hamburg-digital-twin/torii-2403-junction-connection.png" alt="Hamburg node 2403 local junction in NetEdit Connection Mode" width="100%"></p>

| Layer | Implemented evidence | Current claim boundary |
|---|---|---|
| Traffic signals | Nodes 2349 and 2394 bind official TLD primary-signal streams to official MAP movements and concrete SUMO controller `linkIndex` values. | Node 2403 has an official LSA identity but no published MAP/OCIT bundle; its controller is not guessed. |
| Sensors | Processed directional stations are joined to their component physical fields; SUMO E1 is used for counts and E2 only for queue/occupancy diagnostics. | 19 mapped streams include 11 low-confidence lane identities, so automatic promotion remains blocked. |
| Route inverse problem | `H x_t = y_t`, with non-negative integer route allocations. The diagnostic matrix is 6×58, rank 6, nullity 52: many routes are observationally equivalent. | The solution is one plausible realization, not unique trajectories or a unique OD matrix. |
| Exact matrix diagnostic | With TLS disabled, 60/60 station bins and 5,928 vehicles match exactly. | This proves the inverse-demand machinery, not field signal replay. |
| Strict official-history replay | 15 candidate routes, seven measured edges, eight 15-minute bins, route constraint match 100%, zero collision and zero teleport over the 7,200-second official history window. | Sensor MAE is 26.47 and 2403/lane-evidence gates remain blocked; status is `detector-constrained-diagnostic-replay`. |

### What is shown vs what belongs in the repository

| Suitable for the project page | Kept in the repository for reproduction |
|---|---|
| Curated aerial, construction-plan excerpt, OSM input, Connection Mode cleanup, TLS view, headline detector/route metrics. | W0–W5 orchestration code, source adapters, tests, concise development log, provenance, hashes, schemas, and a compact evidence summary. |
| Human-readable conclusions and explicit limitations. | Full generated networks, raw API caches, E1/E2 XML, route ensembles, NetEdit sessions, and repeated experiments stay rebuild-only under `artifacts/` or `outputs/`; they are too large and machine-specific for Git. |

Sources and attribution are recorded in the [image provenance](docs/assets/hamburg-digital-twin/README.md). The official sources are the [Hamburg LGV DOP service](https://metaver.de/trefferanzeige?docuuid=cc0eaed8-cb36-44a0-9bda-153f28d9e7ba) and the [LSBG construction plan](https://lsbg.hamburg.de/resource/blob/784084/6a06328b36b0de140d75baac9165f8f7/am-sandtorkai-brooktorkai-pop-up-bikelane-verstetigung-abgestimmte-planung-plan-data.pdf). Machine-readable headline evidence is frozen in [`docs/hamburg-digital-twin-evidence-summary.json`](docs/hamburg-digital-twin-evidence-summary.json); the iteration history is in the [development log](docs/hamburg-digital-twin-development-log.md).

### Reusable W0–W5 workflow

Torii reuses the focused Hamburg modules rather than implementing a second network builder:

```text
W0 freeze scope/evidence
 ↓
W1 OSM skeleton → estimator/controller/feedback → audited SUMO candidate
 ├───────────────┐
 ↓               ↓
W2 MAP/OCIT/TLD  W3 detectors + route incidence/integer demand
 └───────┬───────┘
         ↓
W4 SUMO replay + real/virtual E1 comparison
         ↓
W5 hash-bound report, downstream invalidation, and reusable product package
```

One portable JSON config now drives the existing resumable ledger. Copy [the example](docs/hamburg-digital-twin-workflow.example.json), replace the `<run>` paths with stage manifests, then run:

```powershell
python plugins/torii-sumo/scripts/run_hamburg_execution_plan.py --config hamburg-workflow.json
```

Every path is resolved relative to the config file. A changed upstream manifest or feedback hash invalidates dependent stages; no source network is overwritten, and a missing official asset remains a blocked gate rather than an inferred fact.

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

The default remains the bounded one-junction slice. To compare raw same-bbox
OSM against the full human-cleaned reference, including reference-cluster
matching, aggregation-candidate estimation, and differential gates, use the
same runner in full reference mode:

```powershell
python plugins/torii-sumo/scripts/run_ingolstadt_corridor_teacher.py --workflow-mode reference-matched
```

This mode delegates to Torii's existing `reference_matched` OSM cleanup
workflow; it does not introduce a second cluster-matching algorithm. It keeps
raw OSM, aggregation candidates, teacher replay candidates, and the human
reference as separate hash-bound artifacts. It defaults to estimator-only;
teacher replay and expensive candidate materialization are an explicit
`--materialize-teacher-candidates` opt-in. Whole-network TLS aggregation is
disabled in this estimator path so it cannot alter the OSM baseline before a
single conflict-core candidate passes preservation and geometry gates.

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

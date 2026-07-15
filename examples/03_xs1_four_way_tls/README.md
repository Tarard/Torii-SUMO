# XS-1: one real four-way TLS intersection

This is Torii's deliberately small vertical slice. It starts from one frozen OpenStreetMap extract (about 400 m), builds a source network, applies exactly one reversible junction-join operation, and audits one standard vehicle-only four-way traffic-light intersection.

## Run

From the repository root, with SUMO 1.27.1 available:

```powershell
.\.venv\Scripts\python.exe plugins\torii-sumo\scripts\run_xs1_four_way.py
```

The result is written to `outputs/xs1-four-way/`. Open `review.html` for the compact result and `xs1-candidate.net.xml` with `review.add.xml` in NetEdit for the final visual check.

> **File roles matter:** `xs1-source.net.xml` intentionally retains the fragmented OSM baseline (10 nearby TLS junctions in this case). It is evidence, not the cleaned result. Visually grade only `xs1-candidate.net.xml`; the `tls_ownership_rebuild` gate proves that the target becomes one physical TLS junction/controller and that no old target controller ID survives.

The expected machine state is `review_ready`; after the NetEdit check it is `review_ready_visual_checked`. Automatic promotion remains blocked in both states.

## What must pass

- The prompt, structured spec, OSM extract, join patch, and toolchain are hash-bound.
- `netconvert` builds both source and candidate from the same frozen OSM input.
- TLS ownership is reduced from ten fragmented target junctions/controllers to one target junction/controller, with zero old target IDs left in the candidate.
- The candidate has 12 direct vehicle movements and 12 traceable internal paths.
- request/foes and TLS/linkIndex bindings pass the code-native Connection Mode audit.
- Independent movement-conflict safety finds no protected conflict or missing permissive yield relation.
- The exact semantic diff has no change outside the target plus its four-node guard ring.
- One vehicle for every right, straight, and left movement loads, departs, and arrives without collision or teleport.
- The display-only `additional.xml`, HTML report, manifest, and rollback record are generated.

## Candidate and rollback

The sole candidate operation joins the eleven fragmented OSM/SUMO nodes listed in `input/join.nod.xml`. The source file is never modified. Rollback means omitting that one patch and rebuilding with the recorded source command.

## Frozen machine-review-ready result

The small machine evidence bundle is committed in `golden/` so it can be opened before rerunning the workflow:

- [`golden/review.html`](golden/review.html): concise gate report.
- [`golden/xs1-candidate.net.xml`](golden/xs1-candidate.net.xml): reviewed candidate network.
- [`golden/review.add.xml`](golden/review.add.xml): display-only target and guard overlay.
- [`golden/summary.public.json`](golden/summary.public.json): path-sanitized evidence summary.
- [`golden/tls-ownership.public.json`](golden/tls-ownership.public.json): explicit source 10 → candidate 1 TLS ownership proof.
- [`golden/manifest.public.json`](golden/manifest.public.json): hashes, toolchain, inputs, and gate closure.
- [`golden/rollback.public.json`](golden/rollback.public.json): inverse operation.

The committed result records one target TLS junction/controller, zero residual old TLS IDs, 12/12 traceable movements, four right/straight/left movements each, 12/12 arrived vehicles, zero collision/teleport, zero outside-scope delta, and a passing independent safety audit. NetEdit visual review remains pending and is not counted as human validation.

## Claim boundary

Passing this example means only that this frozen, vehicle-only, standard four-way intersection is machine-ready for visual review. Automatic promotion remains blocked. It does not cover pedestrians, bicycles, rail, ramps, shared TLS controllers, complex channelization, other intersections, or city-scale cleaning.

OSM data is © OpenStreetMap contributors and is distributed under ODbL 1.0.

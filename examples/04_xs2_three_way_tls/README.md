# XS-2: one real three-way TLS intersection

XS-2 reuses the XS-1 safety contract on a second, smaller topology. It starts from one frozen OpenStreetMap extract (about 400 m), builds a passenger-only source network, and creates one reversible candidate for the Schloßlände × Schutterstraße T-junction in Ingolstadt.

The candidate contains two declared PlainXML operations: join the six nodes inside one physical signal cell, then replace netconvert's unsafe default phase grouping with a conservative two-stage static program. The program is a canonical simulation plan, not a claim about field timing.

## Run

From the repository root, with SUMO 1.27.1 available:

```powershell
.\.venv\Scripts\python.exe plugins\torii-sumo\scripts\run_xs2_three_way.py
```

The result is written to `outputs/xs2-three-way/`. Open `review.html` for the compact result and load `xs2-candidate.net.xml` with `review.add.xml` in NetEdit for the optional visual check.

> **File roles matter:** `xs2-source.net.xml` is the immutable OSM baseline. Visually grade only `xs2-candidate.net.xml`; the `tls_ownership_rebuild` gate proves that the three target TLS nodes become one physical junction/controller and that the old `joinedS_*` controller does not survive.

## What must pass

- The prompt, spec, OSM snapshot, join patch, TLS patch, and toolchain are hash-bound.
- The source and candidate are rebuilt from the same frozen input.
- The three source TLS nodes are rebuilt as one target TLS junction/controller, with zero residual source junction or controller IDs.
- The candidate has three incoming approaches, three outgoing approaches, and seven lane-level movements: three straight, two left, and two right.
- All seven internal paths, request/foes rows, and TLS/linkIndex bindings pass the code-native Connection Mode audit.
- The independent conflict audit reports no protected conflict, potential protected conflict, or missing permissive yield relation.
- Exact semantic diff reports no target-external change or new finding.
- SUMO loads the candidate and all seven exact-lane movement probes arrive without collision or teleport.
- The display-only overlay, HTML, manifest, and rollback record are generated.

## Why the explicit TLS patch exists

The join-only probe was rejected. Netconvert grouped one main-road right turn with the side-road movements under protected green; Torii's independent lane-envelope audit found the potential conflict. XS-2 therefore records an explicit two-stage program with yellow and all-red clearance. This is part of the same candidate DAG and is completely removed by rebuilding the source without either patch.

## Frozen machine-review-ready result

The `golden/` directory contains the path-sanitized review bundle, the explicit TLS ownership proof, and both networks. The expected machine state is `review_ready`; automatic promotion remains blocked. A visual-review record is added only after a NetEdit check and is never treated as human validation.

## Claim boundary

Passing XS-2 proves only this one frozen, vehicle-only, standard three-way slice. It does not certify field signal timing, pedestrians, bicycles, rail, ramps, shared controllers, complex channelization, other junctions, or city-scale cleaning.

OSM data is © OpenStreetMap contributors and is distributed under ODbL 1.0.

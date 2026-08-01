# TUM style teach semantic-parity design

## Goal

Keep the Ingolstadt/TUM teaching experiment isolated from the Hamburg corridor and use the same bbox to learn which Torii repairs improve a teacher network without silently changing its semantics.

The experiment has two explicit modes:

- `osm_boundary`: preserve OSM lane geometry and test structural cleanup.
- `strict_teacher`: replay the teacher lane and scoped internal semantics so W2/W4 parity can be tested as a separate, evidence-bearing candidate.

Neither mode changes the Hamburg defaults or promotes a full-bbox network by itself.

## Smallest implementation

1. Add a source-owner argument to the existing scoped pedestrian semantic restore helper. This lets a teacher junction id and candidate junction id differ while copying crossing edges, walking areas, and internal connections.
2. Run that restore after structural pedestrian normalization in the TUM path, then make target crossing parity a real gate instead of relying on a global modal count.
3. Add a TUM-only strict replay switch that uses existing teacher lane/connection materialization and reports raw TLS and pedestrian parity separately from the OSM-boundary result.
4. Keep all inputs, outputs, screenshots, and manifests below `TUM style teach/`; record source and teacher hashes in the run manifest.

## Acceptance gates

- Unsupported turnarounds: `0`.
- Blocking short internal lanes: `0`.
- Target pedestrian crossing signatures: pass in strict mode; review/block if the source evidence cannot be mapped.
- TLS movement signatures: pass in strict mode, or an explicit bounded review result in OSM-boundary mode.
- SUMO load and routeability: pass.
- Boundary roads from the same-bbox OSM snapshot remain complete; no bbox-edge truncation is treated as a repair.
- Every downstream report binds to the one candidate W1 hash.

## Non-goals

- No changes to Hamburg artifacts, manifests, outputs, or promotion policy.
- No pixel-level claim that Torii reproduces the TUM screenshot.
- No inference of missing signal or pedestrian facts from geometry alone; unresolved evidence remains review-required.

## Verification

Use failing unit tests for source/target junction ownership and target crossing restoration first. Then run the targeted regression suite, execute the same Ingolstadt bbox in the isolated worktree, and inspect the generated W2/W4 evidence before making any parity claim.

# Frozen SUMO 1.27.1 normative scenarios

This directory vendors the smallest source inputs needed for Torii's Stage 1
normative regression suite. They come from the official Eclipse SUMO repository:

- Repository: `https://github.com/eclipse-sumo/sumo.git`
- Tag: `v1_27_1`
- Resolved commit: `7717f2379d9e314a0c81c5cec748444de06a2a91`
- License: `EPL-2.0 OR GPL-2.0-or-later`

The exact upstream and vendored SHA-256 values are recorded in
`../official_sumo_scenarios.v1.json`. Two tiny connection files lacked a final
newline upstream; the vendored copies normalize that final newline, so the
manifest deliberately records both hashes instead of claiming byte identity.

The scenarios are normative parser and fail-closed regression inputs, not
teacher networks and not proof that every review finding is a defect. A case
passes this benchmark when Torii reproduces the frozen SUMO network semantics,
loads it in SUMO, emits no structural false positive, and preserves the expected
review or abstention boundary.

The complete upstream license and notice are included as `LICENSE` and
`NOTICE.md` in this directory.

## Torii expectation migration — 2026-07-15

The vendored SUMO inputs and locked toolchain did not change. Torii commit
`20058d3` refined the independent conflict oracle in two evidence-backed ways:
adjacent diverging lanes from one source boundary port no longer count as an
envelope conflict, and a permissive movement with an explicit request/foes
yield relation no longer produces an unresolved-yield finding. The frozen
scenario expectations had not been regenerated after that oracle change, so
five cases failed only on stale conflict/finding counts.

`official_sumo_scenarios.v1.json` now records the deterministic SUMO 1.27.1
results under the refined oracle: connection examples 20 conflicts each,
joined-junction 16 conflicts with one remaining potential-envelope review,
and both NEMA examples 40 conflicts with no unresolved permissive-yield
finding. This migration does not turn any scenario into an automatic repair:
all nine cases still require fail-closed abstention, and the benchmark identity
was recomputed from the changed expectation payload.

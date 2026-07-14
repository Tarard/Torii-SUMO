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

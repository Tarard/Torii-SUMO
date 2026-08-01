# TUM style teach semantic parity

> **For agentic workers:** execute the steps in order. Keep all generated data under `TUM style teach/`; do not edit or regenerate Hamburg artifacts.

**Goal:** Use the Ingolstadt TUM network and the same bbox to test Torii's junction cleanup with explicit W2/W4 semantic evidence.

**Design:** Reuse the existing teacher replay and pedestrian restore helpers. Add only the missing source/target junction ownership mapping, run it in the isolated TUM path, and keep strict teacher replay separate from OSM-boundary structural mode. Do not add a new framework or change Hamburg defaults.

## Task 1 — Add failing semantic tests

- Add a unit test where teacher and candidate junction ids differ and the candidate has no crossing edges.
- Assert that scoped crossing/walkingarea edges and internal pedestrian connections are restored with candidate-owned ids.
- Add a regression assertion that the final report cannot claim target pedestrian parity when those crossings are absent.
- Run the smallest tests and record the expected failure.

## Task 2 — Implement the shared restore fix

- Extend `restore_scoped_pedestrian_internal_semantics_after_normalize` with an optional source junction id.
- Map internal edge and `via` references from the teacher owner to the candidate owner; keep external mapping through the existing edge map.
- Invoke the restore after structural pedestrian normalization in the teacher-guided candidate path.
- Make target crossing parity part of the structural TUM semantic gate.

## Task 3 — Keep strict teacher replay explicit

- Add the smallest TUM-only switch needed to materialize teacher lane/connection semantics for strict comparison.
- Preserve the existing OSM-boundary mode as the structural baseline.
- Report raw TLS parity, pedestrian parity, topology, and replay separately; no hybrid pass may hide a raw semantic failure.

## Task 4 — Run the same Ingolstadt bbox

- Copy the immutable OSM snapshot and TUM teacher net into `TUM style teach/data/` and record SHA-256 values.
- Run the teacher-guided workflow into `TUM style teach/outputs/` using bbox `11.413800,48.755391,11.433800,48.775391`.
- Verify turnarounds, short internal lanes, boundary-edge preservation, SUMO load, target crossing parity, TLS parity, and W1 hash binding.

## Task 5 — Finish with evidence

- Run targeted tests, then the relevant full regression suite.
- Inspect the generated report and screenshots without claiming full-bbox or field-faithful equivalence unless every gate passes.
- Commit only the isolated branch changes and report the exact branch, paths, hashes, gates, and residual risks.

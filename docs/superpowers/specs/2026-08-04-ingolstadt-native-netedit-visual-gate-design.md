# Ingolstadt Native NetEdit Visual Gate Design

## Purpose

Build a resumable citywide visual gate that compares the official Ingolstadt TUM network with each Torii candidate in NetEdit Connection mode. The gate must cover every registered motor-vehicle incoming lane, retain hash-bound evidence, avoid loading the full candidate into NetEdit, and keep the immutable full networks as the source of structural and global checks.

This design changes only the visual capture path. It does not change the junction reconstruction policy, lane registration rules, structural comparison, SUMO load check, or citywide routeability check.

## Confirmed Problems

The current citywide script already inventories junctions, registers lanes, orders tiles from a seed, resumes completed work, compares lane structure, records evidence, and runs full-network checks. Its capture adapter still opens the full teacher and candidate networks in `NeteditTargetSession`. The 218 MB candidate can fail with a NetEdit allocation error.

Background Win32 clicks also fail on short or overlapping lanes. A fixed `zoom=2500` can place the registered lane sample outside the canvas. The existing geometry helper returns top-level client coordinates, while NetEdit's native `--test-file` mouse actions use `FXGLCanvas` coordinates.

A real NetEdit 1.27.1 probe proved that `--test-file` can enter Connection mode, select a source lane, leave the window available for high-DPI `PrintWindow` capture, and do so without global keyboard or mouse input.

## Chosen Approach

Use render-only tile subnetworks and NetEdit's native test-file actions.

For each visual tile, `netconvert` extracts teacher and candidate subnetworks from the same projected tile boundary plus a fixed buffer. These subnetworks exist only under the tile session directory. They never replace the full network and never supply structural or global evidence.

For each registered incoming lane, the capture path computes three sample points at 8 m, 4 m, and 2 m before the lane end. It selects the largest zoom at which the junction center and all required sample points remain inside a canvas safe area. Candidate zoom is normalized against the teacher so both images use the same world scale.

The path writes a minimal NetEdit test file containing:

```python
netedit.changeMode("connection")
netedit.leftClickOffset(referencePosition, netedit.positions.reference, X, Y)
```

`X` and `Y` are derived from the expected top-level click, the measured `FXGLCanvas` origin, and NetEdit's native reference point `(304,168)`. The process opens from the command line with the subnet, view settings, test file, fixed window size, and registry viewport disabled. Torii enables per-monitor DPI awareness, waits for the expected window, captures it with `PrintWindow`, and terminates only that read-only NetEdit process.

## Selection and Visual Proof

A capture passes source selection only when all of these conditions hold:

1. The expected sample point lies inside the measured canvas safe area.
2. A cyan source-lane component intersects the projected registered lane near that point.
3. The cyan component has enough pixels to rule out the sidebar legend.
4. Teacher and candidate semantic layers pass the existing direction, scale, and component checks.
5. The full-network lane structure comparison passes for the same registered lane pair.

If the 8 m point does not select the expected lane, the capture retries at 4 m and then 2 m. It may lower zoom and regenerate both teacher and candidate views once when a sample lies outside the safe area. It never cycles overlapping objects by repeated clicks. Exhausted retries yield `review_required`, retain all support files, and block automatic promotion.

The visual checker uses the measured canvas rectangle for palette analysis. Sidebar colors never count as road evidence. The semantic radius is based on the visible junction-to-sample distance rather than the current fixed 160-pixel radius, so large junction shapes remain covered without accepting unrelated distant colors.

## Tile Extraction and Source Binding

The tile boundary comes from the existing manifest and uses the same projected coordinates for teacher and candidate. The extraction buffer must include every registered lane shape in that tile and its immediate outgoing targets. The implementation derives the minimum required buffer from those shapes and enforces a small floor; it does not introduce a city-specific hand-edited edge list.

Each subnet report records:

- full source path and SHA-256;
- tile ID and projected extraction boundary;
- exact `netconvert` command and version;
- subnet path and SHA-256;
- included registered junction and lane IDs;
- confirmation that every requested lane and outgoing target exists in the subnet.

A missing requested element is a hard tile failure. Successful tile session subnetworks, view files, and test files are deleted after evidence is written. Failed tile sessions remain available for diagnosis.

## Evidence and Resume Rules

The existing city manifest, per-tile `state.json`, per-lane evidence, and visual summary remain authoritative. No second resume system is added.

Every passing lane keeps teacher and candidate PNG files, semantic masks, hashes, selected sample point, effective zoom, canvas rectangle, and structural result. The command-line summary reports counts and failure paths only; it does not print every lane record. This limits prompt use while keeping the evidence auditable.

Resume accepts a completed tile only when the full teacher hash, full candidate hash, manifest hash, capture-policy version, and every recorded image and mask hash still match. A changed source or policy invalidates that tile and recaptures it.

## Failure Handling

- `netconvert` failure: retain command, logs, boundary, and source hashes; mark the tile failed.
- Missing registered element after extraction: fail before NetEdit launch.
- NetEdit timeout or allocation failure: terminate only the launched process, retain its session, and fail the tile.
- No cyan intersection after retries: mark the lane `review_required` and retain all attempts.
- Teacher/candidate visual mismatch: retain A/B screenshots and comparison image.
- Structural mismatch: fail even when screenshots look similar.
- Full-network SUMO load or routeability failure: fail the citywide result regardless of visual status.

## Alternatives Rejected

### Full-network NetEdit sessions

This reuses the current adapter but the candidate can exceed NetEdit's available memory. It also repeats expensive loading for every tile.

### Background Win32 or foreground desktop clicks

This can capture a window but cannot reliably select short, overlapping, or covered lanes. Foreground automation also disturbs the active desktop and is unsuitable for resumable city runs.

### MCP-driven inspection

MCP remains a manual fallback for a small failed case. It is too slow and prompt-heavy for citywide lane coverage.

## Test Strategy

Unit tests will cover adaptive zoom, safe-area fitting, top-level-to-canvas coordinate conversion, native test-file text, retry order, semantic lane intersection, and source/policy resume invalidation.

Adapter tests will use fake `netconvert`, process, window, and capture functions to prove command construction, fail-closed cleanup, and evidence binding without opening a GUI.

One real acceptance run will use `ring_005d4` and all three registered motor incoming lane pairs. It must produce TUM/Torii Connection-mode screenshots, pass lane selection and structural comparison, load the full candidate in SUMO, and preserve the existing checkpoint hashes.

After that checkpoint passes, the existing tile order expands outward from the seed. Each ring must finish all tile visual and structural gates before the next ring starts. Final completion requires every applicable city junction and incoming lane to pass, followed by full-network SUMO load and the existing stratified citywide routeability run with zero missing routes, teleports, or collisions.

## Acceptance Criteria

The design is complete only when:

- full networks are never opened in NetEdit by the city visual capture adapter;
- every applicable registered incoming lane has hash-bound teacher and candidate Connection-mode evidence;
- each screenshot proves selection of the registered lane, not merely some lane at the junction;
- passing tiles resume without recapture and stale tiles recapture automatically;
- `ring_005d4` passes all three lane pairs in a real run;
- every later ring passes before expansion continues;
- the final full candidate passes SUMO load, structural semantic checks, and citywide routeability with zero teleports and collisions.

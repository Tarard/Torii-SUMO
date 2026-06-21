# OSM Cleanup Hard Gates Design

## Goal

Make Torii's OSM-to-SUMO network workflow default to a reality-checked cleanup loop instead of treating OSM import plus `netconvert` success as enough evidence for a realistic SUMO network.

## Target Behavior

When the user asks Torii to build, clean, or prepare a SUMO network from OSM, Torii must route through a high-level workflow with these hard gates:

1. Resolve and confirm the study area before construction when the user gives only a place name.
2. Build the network from a confirmed bbox or source OSM extract.
3. Audit traffic-light candidates against a map/inventory baseline, with Google Maps as the default current-network baseline.
4. Validate basic network connectivity and routeability before any stronger claim.
5. Open the cleaned network in Netedit and report the process/window evidence.

The workflow may still produce diagnostic artifacts when a gate is incomplete, but it must not call the network realistic, validated, or experiment-ready until the relevant gates have evidence.

## Current State

Torii already has separate MCP tools:

- `sumo_osm_build_network`: downloads or reuses OSM, filters road classes, runs `netconvert`, and returns build artifacts.
- `sumo_tls_audit`: extracts SUMO TLS candidates, clusters likely physical intersections, and emits Google Maps links plus temporal-scope fields.
- `sumo_network_routeability_probe`: creates named-road routeability probes and a bounded `.sumocfg`.

The bundled skill already says Google Maps is an external reality baseline for OSM/TLS review, and the docs already warn that GUI loading is only diagnostic evidence. The gap is that these are separate optional steps. The new behavior should make the sequence mandatory for OSM cleanup workflows.

## Requirement Mapping

### 1. Place-Name Confirmation Gate

If the user gives only a place name, Torii must not silently build from the first geocoder result.

Required behavior:

- Resolve candidate OSM/Nominatim area records or ask the agent to resolve them if no finished MCP geocoder exists.
- Produce a stable preview checkpoint: OSM relation/way/node id when available, bbox, display name, and an OpenStreetMap URL.
- Ask the user to confirm the area before running network construction.

Output fields:

```text
area_input:
area_resolution_status: confirmed | needs_user_confirmation | blocked
candidate_display_name:
candidate_osm_type:
candidate_osm_id:
candidate_bbox:
osm_preview_url:
user_confirmed_area: yes | no
```

Claim boundary:

- Before user confirmation, claim status is `blocked`.
- If the user supplies a bbox or local extract directly, this gate is satisfied by explicit input and should be recorded as `confirmed_by_input`.

### 2. Map Reality Baseline Gate

After OSM import and before calling the network realistic, Torii must compare road/TLS candidates against an external reality baseline.

Default rule:

- For current-network modeling, Google Maps is the default reality baseline.
- If the user states a historical target, the user's target controls the baseline. Google Maps can still provide evidence only when the visible map, Street View history, dated imagery, OSM history, or an agency inventory matches the requested period.

Required behavior:

- Run TLS candidate extraction and clustering after network construction.
- Emit Google Maps review URLs for every TLS candidate/cluster.
- Require a review status before accepting TLS existence decisions:
  - `keep_tls`
  - `remove_tls`
  - `downgrade_tls`
  - `needs_review`
- Keep the workflow claim at `diagnostic-demo` or `blocked` while TLS review remains incomplete.

Output fields:

```text
map_baseline_source: Google Maps | Google Maps historical | OSM history | agency inventory | other
map_temporal_scope: current | historical
map_target_date:
tls_candidate_count:
tls_cluster_count:
tls_review_file:
tls_review_complete: yes | no
tls_keep_count:
tls_remove_count:
tls_downgrade_count:
tls_needs_review_count:
```

Claim boundary:

- Google Maps review supports road/TLS existence decisions.
- It does not prove timing, phasing, detector actuation, controller logic, or operational performance.

### 3. Connectivity Gate

After cleanup, Torii must prove the generated SUMO network has no obvious routeability failure before opening stronger claims.

Required behavior:

- Run a basic passenger-edge connectivity summary on the generated `.net.xml`.
- Report isolated, unreachable, or disconnected passenger components.
- If the user names critical roads, bridges, corridors, or landmarks, run named-road routeability probes for those items.
- Treat route generation failure, missing key edges, or disconnected critical components as `construction-invalid` or `blocked`.

Minimum output fields:

```text
connectivity_status: pass | fail | blocked
passenger_edge_count:
passenger_component_count:
largest_component_edge_count:
small_component_count:
isolated_passenger_edge_count:
routeability_probe_file:
missing_key_edges:
routeability_probe_status:
```

Claim boundary:

- Connectivity checks show construction sanity, not traffic realism.
- Passing connectivity does not replace demand validation, completion checks, TLS phasing audit, or controller evidence.

### 4. Netedit Launch Gate

After construction and basic checks, Torii must open the generated network in Netedit for manual inspection.

Required behavior:

- Launch `netedit` with the generated `.net.xml`.
- Capture whether the process started and whether a window is responding when observable.
- Report the network path and process evidence.

Output fields:

```text
netedit_status: opened | unavailable | failed | skipped
netedit_binary:
netedit_process_id:
netedit_window_title:
netedit_network_file:
```

Claim boundary:

- Netedit inspection is a diagnostic review surface.
- Opening in Netedit does not certify the network.

## Proposed Architecture

Use a high-level OSM cleanup workflow while keeping existing low-level tools reusable.

### New High-Level Tool

Add a new MCP tool such as `sumo_osm_cleanup_workflow`.

Responsibilities:

- Accept either a confirmed bbox/source OSM path or an unresolved place name.
- Return `blocked` when place-name confirmation is required.
- Call the existing OSM build path once the area is confirmed.
- Call TLS audit automatically.
- Call a new connectivity summary helper automatically.
- Optionally launch Netedit when the local environment supports it.
- Return a single workflow report with gate-level statuses and artifact paths.

This keeps `sumo_osm_build_network` as a low-level construction tool for tests and advanced usage while making the agent's default route harder to misuse.

### New Connectivity Helper

Add a focused helper for passenger network connectivity.

Responsibilities:

- Parse the generated `.net.xml`.
- Build a directed graph from passenger-allowed edges and `<connection>` elements.
- Count weak or directed components using the standard library.
- Identify isolated passenger edges and small components.
- Return a deterministic JSON-compatible summary.

Named-road routeability probes remain separate and are used when the user supplies key roads or when the agent can infer them from the task.

### Netedit Launcher

Add a small local launcher helper rather than embedding GUI behavior inside `sumo_osm_build_network`.

Responsibilities:

- Find `netedit` via `shutil.which`.
- Start it with the generated network path.
- Return process id and launch status.
- Avoid blocking the MCP server while Netedit stays open.

## Skill and Documentation Changes

Update the public skill and bundled plugin skill so OSM construction routes to the high-level workflow by default.

Files expected to change during implementation:

- `skills/simulation-helper-skill-for-eclipse-sumo/SKILL.md`
- `skills/simulation-helper-skill-for-eclipse-sumo/references/model-osm-detectors.md`
- `skills/simulation-helper-skill-for-eclipse-sumo/references/mcp-tool-routing.md`
- `plugins/torii-sumo/skills/simulation-helper-skill-for-eclipse-sumo/SKILL.md`
- `plugins/torii-sumo/skills/simulation-helper-skill-for-eclipse-sumo/references/model-osm-detectors.md`
- `plugins/torii-sumo/skills/simulation-helper-skill-for-eclipse-sumo/references/mcp-tool-routing.md`
- `README.md`
- `README.zh-CN.md`
- `README.de.md`
- `docs/codex-plugin-install.md`
- `docs/skill-integration.md`
- `docs/index.html`

Docs must preserve the public boundary:

- Do not claim Google Maps is affiliated with or endorsed by Torii.
- Do not claim automatic Google Maps scraping or full city-scale certification.
- Do not expose private local workflow names or project-specific assumptions.

## Test Strategy

Add tests before implementation.

Expected test coverage:

- Place-name input without confirmation returns `blocked` and includes OSM preview fields.
- Confirmed bbox/source input runs construction and records `area_resolution_status`.
- Workflow invokes TLS audit after build and includes Google Maps review artifacts.
- Historical target keeps the user target date in the map baseline and does not let current Google Maps override it.
- Connectivity helper reports pass/fail deterministically on small fixture networks.
- Netedit launcher reports `unavailable` cleanly when `netedit` is not on `PATH`.
- MCP server registers the new workflow tool.
- README/docs mention the hard-gate workflow and keep claim boundaries.

## Acceptance Criteria

The implementation is complete when:

- OSM cleanup requests route to the high-level workflow in the skill instructions.
- The workflow blocks on unconfirmed place-name areas.
- The workflow always creates TLS audit artifacts after network construction.
- The workflow reports connectivity status before stronger claims.
- The workflow attempts Netedit launch and reports observable launch evidence.
- Tests pass with `python -m pytest -q`.
- `git diff --check` is clean.
- Documentation states the new hard gates in English, Chinese, German, and the site page.

## Residual Risks

- Google Maps review still requires human or browser-assisted inspection; Torii should emit review artifacts and block claim escalation rather than pretending to read Google Maps automatically.
- Netedit launch is local-GUI behavior and may not work in headless or remote environments. The workflow should report `unavailable` or `failed` instead of failing the whole construction when the network artifacts are otherwise generated.
- Connectivity checks can miss semantic problems such as wrong lane permissions, incorrect signal grouping, unrealistic phase logic, or missing demand realism.
- Historical modeling depends on the quality of dated external evidence. The user target controls the baseline, but weak historical evidence must remain a residual risk in the output.

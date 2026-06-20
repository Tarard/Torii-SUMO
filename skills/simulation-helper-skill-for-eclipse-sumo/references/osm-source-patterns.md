# OSM Source Patterns

Use this reference when the user asks to improve OSM import, intelligent cleanup, Overpass robustness, large-area import, historical map construction, OpenDRIVE conversion, or public OSM code reuse.

## Source Map

| Project | Use inside Torii | Borrow | Do not assume |
|---|---|---|---|
| OSMnx | Robust online Overpass acquisition | Overpass subdivision, network presets, rate-limit pause, cache, retry | That Codex should install heavy geospatial dependencies for every user |
| OSMNet | Lightweight OSM graph extraction architecture | road-class filtering, node/way deduplication, cleanup stages | That source code can be vendored |
| pyrosm | Large-region or historical PBF workflow | offline PBF import, bbox filtering, custom filters, city-scale parsing | That Windows dependency installation is trivial |
| SUMO osmGet/osmBuild | SUMO-native import behavior | tiles, Overpass fallback, `netconvert` option profiles, polygon/background flow | That generic OSM library behavior outranks SUMO semantics |
| osm-to-xodr | Staged conversion and metadata audit | multi-stage netconvert, OpenDRIVE export, post-processing records | That it is a SUMO traffic-signal controller |

## Integration Rule

Do not vendor external source code into this plugin. Treat these repositories as source-pattern evidence. Convert useful ideas into small MCP tools, explicit options, tests, and claim boundaries.

Preferred ladder:

1. Keep bbox/source-OSM network building lightweight in `sumo_osm_build_network`.
2. Add OSMnx/OSMNet-inspired Overpass subdivision, retry, deduplication, cache, and highway presets.
3. Add SUMO osmGet/osmBuild-inspired endpoint fallback, tile controls, polygon/background options, and `netconvert` profiles.
4. Add pyrosm-style offline PBF import for large-area, repeated, or historical builds.
5. Add osm-to-xodr-style staged conversion records for OpenDRIVE/export workflows.

## Google Maps Baseline

Google Maps is the external reality baseline for current OSM/SUMO road and TLS existence audit. It can support `keep_tls`, `remove_tls`, or `needs_review` decisions after the map time scope is confirmed.

Always ask whether the audit should use the current map or a historical target date. If the user models a past network, latest Google Maps is not automatically decisive; use dated imagery, Street View history, OSM history, or agency inventory when available.

Record:

```text
map_baseline_source: Google Maps
map_temporal_scope: current | historical | unspecified
map_target_date:
google_maps_url:
audit_status:
action:
time_scope_residual_risk:
```

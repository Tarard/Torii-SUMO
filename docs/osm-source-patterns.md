# OSM Source Patterns

This project treats public OSM repositories as source-pattern evidence for Torii. Do not vendor external source code into the plugin. Borrow architecture, option names, and validation ideas only after checking license, dependencies, and Windows install risk.

## Source Map

| Project | Torii role | Pattern to borrow | Boundary |
|---|---|---|---|
| OSMnx | Online Overpass network acquisition | Overpass subdivision, network-type presets, rate-limit pause, cache, retry on API pressure | Keep a lightweight local implementation; do not require heavy geospatial dependencies for the MVP |
| OSMNet | OSM graph extraction design | Road-class filtering, node/way deduplication, graph-oriented cleanup stages | Architecture reference only; do not vendor source code |
| pyrosm | Large-area and historical extract path | offline PBF reading, bbox filtering, custom tag filters, city/country-scale imports | Optional future dependency because geospatial wheels can be fragile on Windows |
| SUMO osmGet/osmBuild | SUMO-native import path | Overpass server fallback, tiles, `netconvert` option sets, polygon/background import flow | Prefer SUMO-native semantics when they differ from generic OSM libraries |
| osm-to-xodr | Conversion and metadata post-processing pattern | multi-stage netconvert, OpenDRIVE export, traffic-sign/signal metadata post-process | Reference for staged conversion/audit; not a controller implementation |

## Integration Ladder

1. Keep the current `sumo_osm_build_network` path lightweight: bbox, tiled Overpass, retry, XML deduplication, highway presets, and `netconvert`.
2. Add OSMnx-inspired Overpass controls next: endpoint fallback, rate-limit/status pause, local query cache, and richer network presets.
3. Add SUMO osmGet/osmBuild-inspired defaults: tile strategy, optional polygon/background generation, and documented `netconvert` option profiles.
4. Add a pyrosm-style offline PBF path for large regions, historical extracts, and repeated city-scale builds.
5. Add osm-to-xodr-style staged conversion records when the user needs OpenDRIVE, CARLA-style maps, or metadata post-processing.

## Google Maps Baseline Rule

Google Maps is the external reality baseline for OSM/SUMO network and TLS existence audit, but its time scope must match the user's modeling target.

Before using Google Maps to decide `keep_tls`, `remove_tls`, or `needs_review`, record whether the user wants the current map or a historical target date. If the user is modeling a historical network, do not treat the latest Google Maps view as decisive unless its imagery, Street View, or inventory evidence matches the study period.

Minimum record:

```text
map_baseline_source: Google Maps
map_temporal_scope: current | historical | unspecified
map_target_date:
google_maps_url:
audit_status:
action:
time_scope_residual_risk:
```

## References

- OSMnx: https://github.com/gboeing/osmnx
- OSMNet: https://github.com/UDST/osmnet
- pyrosm: https://github.com/pyrosm/pyrosm
- SUMO osmGet/osmBuild: https://github.com/eclipse-sumo/sumo/tree/main/tools
- osm-to-xodr: https://github.com/das-rise/osm-to-xodr

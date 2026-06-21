# BIT Zhongguancun Campus SUMO Network

Generated on 2026-06-21 from OpenStreetMap data for Beijing Institute of Technology, Zhongguancun campus.

## Source Area

- Resolved OSM candidate: `way 30748230`
- Display name: Beijing Institute of Technology, 5 Zhongguancun South Street, Haidian, Beijing, China
- Candidate center: `39.9578214, 116.3098237`
- Candidate bbox: `116.3026816,39.9556583,116.3167991,39.9600597`
- Download/build bbox with margin: `116.3018,39.9548,116.3176,39.9608`
- OSM extract timestamp: `2026-06-21T17:18:03Z`

## Main Artifacts

- `bit_zhongguancun.osm.xml`: raw Overpass XML extract.
- `bit_zhongguancun.net.xml`: default SUMO network, set to the connected passenger core.
- `bit_zhongguancun.connected-core.net.xml`: same connected-core network kept with explicit name.
- `bit_zhongguancun.raw.net.xml`: raw converted passenger network before connected-core extraction.
- `network-audit.json`: counts and weak-component audit for default, raw, and connected-core networks.
- `load-smoke.sumocfg`: one-step SUMO load check for the default network.
- `routeability.sumocfg`: deterministic passenger routeability probe.
- `manifest.json`: source, commands, verification, and claim boundary.

## Construction Rule

The network targets vehicle-accessible campus and boundary roads for passenger vehicles. The build excludes pedestrian-only modeling as a routeable vehicle network target. The raw OSM extract includes selected non-road map context tags, but the SUMO network is built from passenger-accessible road edges.

## Verification Summary

- `sumo -c load-smoke.sumocfg`: exit `0`; network loaded.
- Connected-core audit: `227` passenger edges, `251` passenger lanes, `110` junctions, one weak passenger component.
- Raw converted audit: `233` passenger edges, weak passenger components `[110, 4, 4]`; preserved as construction evidence.
- Routeability probe: `10` deterministic passenger trips generated; `10` inserted, `10` arrived, `0` running, `0` waiting, `0` teleports.

## Amap / Official Boundary Check

This example includes a lightweight public-map sanity check for the modeled area.

- Beijing Institute of Technology's official page describes the Zhongguancun campus as being at `5 Zhongguancun South Street`, bordered by Zhongguancun South Street, Weigongcun Road, Suzhouqiao Street, and the North Third Ring area.
- Amap's main `Beijing Institute of Technology (Zhongguancun Campus)` POI is `39.959984,116.315469`, which is inside the generated download/build bbox `116.3018,39.9548,116.3176,39.9608`.
- Some Amap campus-related POIs are outside this bbox, for example the Automation School POI north of the bbox and the Science/Technology Building POI east of the bbox.

Interpretation: the generated network is usable as a diagnostic SUMO network around the main Zhongguancun campus OSM polygon and nearby vehicle-accessible roads. It should not be treated as full coverage of every BIT-associated building or external campus facility without a larger bbox and a separate regional-map review.

## Claim Boundary

Claim status: `diagnostic-demo`.

This output proves an OSM-derived SUMO network can be constructed, loaded, and routed through a small deterministic passenger probe. It does not prove real campus demand, signal timing, signal phasing, detector alignment, or controller-readiness. The 9 generated traffic lights require external/manual TLS review before signal-control claims.

## Source Data Notice

The road network is derived from OpenStreetMap data downloaded through Overpass. If reusing the OSM-derived files, follow OpenStreetMap attribution and license requirements.

Public reference pages used for the lightweight boundary check:

- Beijing Institute of Technology official location page: <https://www.bit.edu.cn/gbxxgk/xydy_sjb/dlwz_sjb/>
- Amap main campus POI: <https://www.amap.com/place/B000A83H2R>

---
name: torii-build
description: Use when building, cleaning, reviewing, or interpreting SUMO road networks and traffic-signal infrastructure from OpenStreetMap, engineering drawings, MAP/KML/OCIT-C, aerial or map evidence, or an existing SUMO network.
---

# Torii Build

Build the physical traffic model. This skill owns network topology, roads, lanes, junction structure, signal-device structure, source authority, and construction review. It does not fit traffic demand or report completed controller experiments.

## Start Here

| Task | Load |
|---|---|
| OSM-to-SUMO construction or cleanup | `references/osm-to-sumo-workflow.md` |
| OSM import/source patterns | `references/osm-source-patterns.md` |
| OSM way fragmentation or road-axis reconstruction | `references/osm-way-fragmentation-and-road-axis-reconstruction.md` |
| Road arms and lane connections | `references/road-arm-and-connection-classification.md` |
| Physical intersection classification | `references/composable-intersection-classification.md` |
| Signal-device classification | `references/composable-signal-device-classification.md` |
| Map/TLS reality checks and source alignment | `references/model-osm-detectors.md` |
| Hamburg road construction | `references/hamburg-five-intersection-aerial-workflow.md` |

## Rules

- Preserve the user's target year and primary source authority.
- Keep source artifacts immutable and write candidates separately.
- Separate topology, geometry, signal identity, routeability, and field-accuracy claims.
- SUMO load or vehicle passage does not prove that a reconstructed road is physically correct.
- Do not change demand to make a network-construction result pass.
- When the road network is frozen and the task becomes count fitting or demand reconstruction, hand off to `$torii-calibrate`.
- Use `torii workflows --json` when an executable catalog entry is needed, and preserve `review_required` or `blocked` results.

## Output

State the source basis, constructed or reviewed artifact, unresolved physical assumptions, checks performed, and the strongest supportable construction claim.

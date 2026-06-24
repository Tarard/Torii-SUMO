# One-Prompt OSM-to-SUMO Network Demo

This example records an Ingolstadt city-center Torii workflow target: build a bounded SUMO network from OpenStreetMap, clean it, and compare the result with the manually cleaned TUM `sumo_ingolstadt` reference network for the same area.

Prompt:

```text
Use Torii to clean the Ingolstadt city-center network around https://www.openstreetmap.org/#map=17/48.765391/11.423800 from OSM, compare it with the TUM-VT/sumo_ingolstadt cleaned network for the same bbox, and open the cleaned network in Netedit.
```

## Area and Reference

| Item | Value |
|---|---|
| Center | `48.765391, 11.423800` |
| OSM view | <https://www.openstreetmap.org/#map=17/48.765391/11.423800> |
| Comparison bbox | `11.413800,48.755391,11.433800,48.775391` |
| Torii source | OSM, `highway_classes='arterial'` |
| Reference source | TUM-VT [`sumo_ingolstadt`](https://github.com/TUM-VT/sumo_ingolstadt), `simulation/Ingolstadt SUMO 365/ingolstadt_net.net.xml` |

The TUM network is the manually cleaned reference, not an input source for Torii. The Torii network must be generated from OSM and then compared against that reference.

## Result Summary

| Evidence | Torii OSM cleaned core | TUM cleaned reference subset |
|---|---:|---:|
| Edges in comparison bbox | 606 | 3,577 |
| Passenger edges | 606 | 2,032 |
| Lanes | 1,056 | 4,955 |
| Junctions | 367 | 1,752 |
| Traffic-light junctions | 158 | 29 |
| Joined-junction endpoint references | 0 | 1,136 |
| Dense-junction clusters, 30 m audit | 35 | 132 |
| Max dense-cluster node count | 24 | 93 |
| Routeability smoke | 40 / 40 arrived at `end=800` | 40 / 40 arrived at `end=800` |
| Teleports / collisions | 0 / 0 | 0 / 0 |
| Claim status | `diagnostic-demo`, topology/TLS review required | reference comparator only |

## Interpretation

The routeability result is good enough to show that the Torii-connected core is runnable for diagnostic inspection. It is not enough to claim that the OSM-cleaned network matches the TUM manual network.

The key comparison signal is topology, not only connectivity. The TUM reference uses many `cluster_*` junctions and exposes far fewer traffic-light junctions in the same bbox. The current Torii OSM build still exposes many SUMO TLS nodes that likely belong to a smaller number of physical intersections. That is the exact OSM import problem this example is meant to test.

## Files in This Example

- [`prompt.md`](prompt.md): the one-prompt request.
- [`manifest.public.json`](manifest.public.json): public, path-sanitized artifact manifest.
- [`validation/comparison_summary.json`](validation/comparison_summary.json): compact validation record.
- [`validation/tum_vs_torii_bbox_comparison.csv`](validation/tum_vs_torii_bbox_comparison.csv): count, topology, and routeability comparison.

Generated `.net.xml`, route, and log files are intentionally not committed. They should be rebuilt into a fresh output directory when the example is rerun.

## Reproduction Notes

1. Confirm the OSM area around the supplied map URL and ask for the road-detail target.
2. Build the Torii OSM network for the confirmed bbox, using the selected road-class rule.
3. Extract a connected passenger core when the raw OSM import has small disconnected fragments.
4. Run passenger connectivity and routeability audits on the Torii core.
5. Extract or crop the TUM reference network to the same bbox.
6. Compare edge, lane, junction, TLS, joined-junction, dense-cluster, and routeability evidence.
7. Open the Torii cleaned network in Netedit for manual topology and TLS review.

## Claim Boundary

This is a diagnostic comparison example. A matching routeability smoke test does not prove that the Torii network is equivalent to the manually cleaned TUM network. The current comparison shows the next required cleanup target: physical-intersection grouping and TLS candidate reduction.

## Data Attribution

Torii input data comes from OpenStreetMap and is available under the Open Database License (ODbL). See <https://www.openstreetmap.org/copyright>.

The reference comparator is the public TUM-VT `sumo_ingolstadt` project. See <https://github.com/TUM-VT/sumo_ingolstadt>.

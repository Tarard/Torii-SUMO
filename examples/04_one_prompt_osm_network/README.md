# One-Prompt OSM-to-SUMO Network Demo

This example records an Ingolstadt city-center Torii workflow target: build a bounded SUMO network from OpenStreetMap, clean it, and compare the result with the manually cleaned TUM `sumo_ingolstadt` reference network for the same bbox.

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
| Torii source | OSM, `highway_classes='full_vehicle'` |
| Reference source | TUM-VT [`sumo_ingolstadt`](https://github.com/TUM-VT/sumo_ingolstadt), `simulation/Ingolstadt SUMO 365/ingolstadt_net.net.xml` |

The TUM network is the manually cleaned reference, not an input source for Torii. The correct comparison sequence is:

1. Inspect the TUM network's retained hierarchy and permissions.
2. Cut the same city-center bbox from the TUM network.
3. Build the Torii network from OSM with the closest matching vehicle-road scope.
4. Compare the TUM bbox cut with the Torii bbox product.

TUM's Ingolstadt model is a multimodal simulation network. In the city-center bbox it retains passenger, bicycle, pedestrian, bus, and rail-related edges. For vehicle-network comparison, use the TUM passenger-drivable subset as the closest target, not the whole multimodal edge count.

## Result Summary

| Evidence | Torii OSM `full_vehicle` core | TUM city-center bbox cut |
|---|---:|---:|
| All non-internal edges | 1,427 | 3,577 |
| Passenger-drivable edges | 1,427 | 2,032 |
| Lanes | 1,978 | 4,955 |
| Junctions | 782 | 1,752 |
| Traffic-light junctions | 198 | 29 |
| Joined-junction endpoint references | 0 | 1,136 |
| Dense-junction clusters, 30 m audit | 64 | 132 |
| Max dense-cluster node count | 32 | 93 |
| Routeability smoke | 40 / 40 arrived at `end=800` | 40 / 40 arrived at `end=800` |
| Teleports / collisions | 0 / 0 | 0 / 0 |
| Claim status | `diagnostic-demo`, topology/TLS review required | reference comparator only |

TUM passenger-drivable hierarchy in this bbox:

| TUM passenger road type | Edge count |
|---|---:|
| `highway.service` | 945 |
| `highway.residential` | 429 |
| `highway.tertiary` | 256 |
| `highway.unclassified` | 162 |
| `highway.secondary` | 85 |
| `highway.living_street` | 66 |
| `highway.primary` + links | 31 |
| `highway.track` | 26 |
| missing or uncommon type | 28 |

## Interpretation

The routeability result is good enough to show that the Torii-connected core is runnable for diagnostic inspection. It is not enough to claim that the OSM-cleaned network matches the TUM manual network.

The key comparison signals are road hierarchy, lane permissions, and topology, not only connectivity.

- TUM keeps a high-detail passenger-drivable network in the bbox, including many `highway.service` edges.
- Torii `full_vehicle` keeps service OSM ways, but SUMO's default OSM typemap does not make those service edges passenger-drivable. This is a concrete cleanup gap, not just a count difference.
- TUM uses many `cluster_*` joined junctions and exposes far fewer traffic-light junctions. The current Torii OSM build still exposes many SUMO TLS nodes that likely belong to a smaller number of physical intersections.

## Files in This Example

- [`prompt.md`](prompt.md): the one-prompt request.
- [`manifest.public.json`](manifest.public.json): public, path-sanitized artifact manifest.
- [`validation/comparison_summary.json`](validation/comparison_summary.json): compact validation record.
- [`validation/tum_vs_torii_bbox_comparison.csv`](validation/tum_vs_torii_bbox_comparison.csv): count, topology, and routeability comparison.

Generated `.net.xml`, route, and log files are intentionally not committed. They should be rebuilt into a fresh output directory when the example is rerun.

## Reproduction Notes

1. Inspect the TUM reference network structure and retained edge types.
2. Cut the TUM reference network to the confirmed city-center bbox.
3. Confirm the Torii road-detail target. For this comparison the closest implemented preset is `full_vehicle`.
4. Build the Torii OSM network for the same bbox.
5. Extract a connected passenger core when the raw OSM import has disconnected fragments.
6. Run passenger connectivity and routeability audits on both the TUM cut and the Torii core.
7. Compare edge, lane, road-type, lane-permission, junction, TLS, joined-junction, dense-cluster, and routeability evidence.
8. Open the Torii cleaned network in Netedit for manual topology and TLS review.

## Claim Boundary

This is a diagnostic comparison example. A matching routeability smoke test does not prove that the Torii network is equivalent to the manually cleaned TUM network. The current comparison shows two required cleanup targets: service-road passenger permissions and physical-intersection/TLS grouping.

## Data Attribution

Torii input data comes from OpenStreetMap and is available under the Open Database License (ODbL). See <https://www.openstreetmap.org/copyright>.

The reference comparator is the public TUM-VT `sumo_ingolstadt` project. See <https://github.com/TUM-VT/sumo_ingolstadt>.

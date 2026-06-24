# Prompt

```text
Use Torii to clean the Ingolstadt city-center network around https://www.openstreetmap.org/#map=17/48.765391/11.423800 from OSM, compare it with the TUM-VT/sumo_ingolstadt cleaned network for the same bbox, and open the cleaned network in Netedit.
```

Required behavior:

- Use OSM as the construction source.
- Use the TUM `sumo_ingolstadt` network only as a manually cleaned reference comparator.
- Ask for the target road-detail level before treating the network as an experiment candidate; for the TUM comparison, use the closest implemented Torii preset, `full_vehicle`.
- Inspect TUM's retained road hierarchy and lane permissions before making the comparison.
- Cut the TUM reference network to the same city-center bbox before comparing.
- Run connectivity, connected-core, topology, routeability, and Netedit launch evidence steps.
- Bound the claim if topology or traffic-light grouping differs from the TUM reference.

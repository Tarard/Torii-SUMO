# Prompt

```text
Use Torii to clean the Ingolstadt city-center network around https://www.openstreetmap.org/#map=17/48.765391/11.423800 from OSM, compare it with the TUM-VT/sumo_ingolstadt cleaned network for the same bbox, and open the cleaned network in Netedit.
```

Required behavior:

- Use OSM as the construction source.
- Use the TUM `sumo_ingolstadt` network only as a manually cleaned reference comparator.
- Ask for the target road-detail level before treating the network as an experiment candidate.
- Run connectivity, connected-core, topology, routeability, and Netedit launch evidence steps.
- Bound the claim if topology or traffic-light grouping differs from the TUM reference.

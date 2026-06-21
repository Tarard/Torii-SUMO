# One-Prompt OSM-to-SUMO Demo Prompt

```text
Use Torii to download the Altstadt map in Dresden from OSM, clean it up and open it in SUMO
```

The agent resolved the place to an OSM relation and bounding box, asked for confirmation of the area and recommended vehicle-road detail level, then built and opened the SUMO network after confirmation.

The resulting claim status is `diagnostic-demo`, not a formal experiment-ready network certification.

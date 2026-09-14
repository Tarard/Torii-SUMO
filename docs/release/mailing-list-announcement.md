# Mailing List Announcement Draft

Subject:

```text
[Tool] Torii: agent plugin for SUMO OSM import, TLS review, and evidence checks
```

Body:

```text
Hello SUMO community,

I am sharing Torii, an independent agent plugin for Eclipse SUMO workflows.

Torii bundles:

- a SUMO expert skill for Codex/Claude-style coding agents;
- local stdio MCP tools for bounded SUMO checks;
- OSM-to-SUMO helpers for tiled Overpass import, retry, XML deduplication, road-class filtering, and netconvert;
- TLS candidate review with Google Maps links after current-vs-historical scope is confirmed;
- routeability probes, output comparison, and evidence bundle writing.

The project treats bad metrics, warnings, teleports, disconnected routes, and map disagreements as feedback about the model rather than raw optimization targets.

Repository: [GitHub link]

This is independent research tooling. It is not affiliated with or endorsed by the Eclipse SUMO project, the Eclipse Foundation, DLR, Google, or the external OSM projects whose public architecture patterns are discussed.

Feedback is welcome, especially on common OSM import, TLS cleanup, controller-application, and reproducibility failures that should be handled more systematically.
```

## Posting Notes

- Use a practical tool tone.
- Do not imply official SUMO endorsement.
- Do not claim full automatic city-scale OSM cleanup or controller generation until the MCP tools exist.
- Ask for concrete failure modes or missing checks.

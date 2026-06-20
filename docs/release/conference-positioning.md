# Conference and Demo Positioning

## Recommended Angle

Use "agent-assisted SUMO infrastructure repair" and "feedback-driven OSM-to-SUMO validation" rather than generic "I made a plugin."

Suggested title:

```text
Torii: Feedback-Driven Agent Workflows for OSM-to-SUMO Network Construction and Evidence Checks
```

Suggested abstract framing:

```text
SUMO workflows can appear runnable while still containing disconnected routes, mismatched TLS, incomplete outputs, or completion-biased metrics. Torii presents an agent plugin that combines a SUMO expert skill with bounded local MCP tools for OSM-to-SUMO construction, TLS candidate review, routeability probes, output comparison, and evidence bundle writing. The central idea is to treat warnings and degraded metrics as feedback about the network, demand, controller, or experiment design before making the next code or modeling change.
```

## Demo Checklist

- Show one OSM bbox or extract converted through tiled Overpass/retry/deduplication/road-class filtering.
- Show one TLS candidate review with Google Maps current-versus-historical scope explicitly selected.
- Show one routeability probe exposing a disconnected road or bridge before result claims.
- Show one bad metric interpreted as model feedback rather than a raw objective.
- End with the corrected claim boundary and the remaining roadmap tools.

## Claim Boundaries

- Do not claim full place-name geocoding unless that tool is implemented and verified.
- Do not claim full automatic city-scale OSM cleanup.
- Do not claim Google Maps is always the correct target; temporal scope matters.
- Do not claim controller generation or controller-log inspection as completed MCP tools until implemented.

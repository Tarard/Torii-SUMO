# LinkedIn Post Drafts

## Release Post

```text
I have been turning my SUMO workflow into Torii: Task-Oriented Road Infrastructure Intelligence.

Torii is an agent plugin for SUMO. It gives Codex/Claude-style coding agents both a SUMO expert skill and local MCP tools.

Current tools cover:
- OSM-to-SUMO network construction from bbox or extracts
- tiled Overpass import, retry, XML deduplication, and road-class filtering
- TLS candidate review with Google Maps temporal-scope checks
- routeability probes for named roads and bridges
- SUMO environment checks, config preflight, smoke runs, output comparison, and evidence bundles

The design principle is simple: bad metrics are feedback about the model. The agent should diagnose what the metric means before changing the network, demand, controller, or code.

Repository: [GitHub link]

Independent project; not affiliated with Eclipse SUMO, Eclipse Foundation, DLR, Google, OpenAI, Anthropic, or external OSM tool projects.
```

## Specific Case Post

```text
Common SUMO network-building failure:

The OSM import succeeds, netconvert writes a network, and SUMO runs. But routes are disconnected, TLS are duplicated or misclustered, and the result metric becomes meaningless.

Torii's current workflow treats this as feedback:

- inspect OSM import warnings
- check road-class filtering
- deduplicate merged OSM objects
- cluster TLS candidates into physical-intersection review groups
- use Google Maps only after current-vs-historical scope is clear
- generate routeability probes before result claims

This is the kind of boring infrastructure that makes agent-driven SUMO work less fragile.

Repository: [GitHub link]
```

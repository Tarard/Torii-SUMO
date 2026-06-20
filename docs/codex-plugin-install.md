# Codex Plugin Installation

`Torii` is distributed as a Codex plugin. Installing it provides both:

- the `simulation-helper-skill-for-eclipse-sumo` expert skill;
- the `torii-sumo` local stdio MCP server.

The skill is the reasoning layer. The MCP server is the execution layer.

## Repository Layout

The installable plugin root is:

```text
plugins/torii-sumo
```

The plugin manifest is:

```text
plugins/torii-sumo/.codex-plugin/plugin.json
```

The repo marketplace entry is:

```text
.agents/plugins/marketplace.json
```

## Local Development Install

From a local checkout, add the repository as a local marketplace:

```powershell
codex plugin marketplace add <path-to-this-repo>
codex plugin add torii-sumo@torii-sumo
```

Start a new Codex thread after installing or reinstalling so the skill and MCP tools are discovered in the new session.

## GitHub Install Shape

For a GitHub source, the expected marketplace command is:

```powershell
codex plugin marketplace add Tarard/Simulation-Helper-Skill-for-Eclipse-SUMO --ref main
codex plugin add torii-sumo@torii-sumo
```

If the Codex CLI reports a marketplace-source mismatch, verify that `.agents/plugins/marketplace.json` points to `./plugins/torii-sumo`.

## Usage Boundary

The plugin can run bounded environment checks, config preflight, smoke runs, output comparison, evidence bundle writing, and OSM/network construction helpers through MCP tools.

Implemented OSM/network tools:

- `sumo_osm_build_network`: download or reuse an OSM extract, use tiled Overpass requests with retry, deduplicate merged OSM XML by object id, apply road-class presets or explicit highway classes, run `netconvert`, and return artifact/log paths.
- `sumo_tls_audit`: extract SUMO TLS audit candidates, cluster nearby candidates into physical-intersection review groups, and attach Google Maps reality-baseline fields.
- `sumo_network_routeability_probe`: generate named-road probe routes and a bounded `.sumocfg` for routeability checks.

Google Maps is the external reality baseline for road/TLS existence review. Before using it as the standard, confirm whether the user wants the current map or a historical target date; latest Google Maps should not automatically override a historical modeling target.

External OSM source patterns are tracked from OSMnx, OSMNet, pyrosm, SUMO osmGet/osmBuild, and osm-to-xodr. Torii borrows architecture and validation ideas from these projects without vendoring their source code.

The plugin does not yet implement full OSM intelligent cleanup, geocoded area resolution from place names, authoritative TLS inventory, max-pressure controller generation, or controller-log inspection as MCP tools. The bundled skill will route those requests into a plan or code-development path until those tools are added.

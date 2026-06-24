<p align="center">
  <img src="docs/assets/banner.png" alt="Torii agent plugin for SUMO banner">
</p>

# <img src="docs/assets/app-logo.png" width="42" alt="Torii logo"> Torii

<div align="center">

**Task-Oriented Road Infrastructure Intelligence**

**Agent plugin for SUMO**

<img src="https://img.shields.io/badge/Agent%20Plugin-Codex%20%2F%20Claude-6f42c1" alt="Agent plugin for Codex and Claude">
<img src="https://img.shields.io/badge/SUMO%2FTraCI-traffic%20simulation-blue" alt="SUMO and TraCI">
<img src="https://img.shields.io/badge/OSM%20to%20SUMO-network%20cleanup-1d8e57" alt="OSM to SUMO network cleanup">
<img src="https://img.shields.io/badge/One%20Prompt-SUMO%20Network-0b7a75" alt="One prompt to SUMO network">
<img src="https://img.shields.io/badge/Model--Agnostic-workflow-7a5c00" alt="Model-agnostic workflow">
<img src="https://img.shields.io/badge/MCP%20Tools-local%20stdio-c98a05" alt="Local stdio MCP tools">

<a href="https://tarard.github.io/Torii-SUMO/"><strong>Website</strong></a> |
<a href="docs/codex-plugin-install.md"><strong>Install</strong></a> |
<a href="examples/01_signal_control_audit/task.md"><strong>Signal-Control Audit</strong></a> |
<a href="examples/04_one_prompt_osm_network/README.md"><strong>One-Prompt Demo</strong></a> |
<a href="LICENSE-CODE"><strong>MIT Code</strong></a> |
<a href="LICENSE-DOCS"><strong>CC BY 4.0 Docs</strong></a>

[English](README.md) | [简体中文](README.zh-CN.md) | [Deutsch](README.de.md)

</div>

> [!NOTE]
> Torii is independent. It is not affiliated with, endorsed by, sponsored by, or maintained by the Eclipse Foundation, the Eclipse SUMO project, DLR, OpenAI, Anthropic, Google, or any external OSM tooling project.

## One Prompt to a SUMO Network, Across Models

Torii is designed for model-agnostic SUMO work: one short natural-language prompt can become a bounded OSM-to-SUMO network workflow with construction evidence, routeability checks, and a clear claim boundary.

The plugin now starts from a workflow router: `torii_auto_workflow` classifies the request, chooses a recipe, asks only blocking questions, and runs safe MCP steps when the required evidence is available.

Torii is deliberately guardrail-heavy. The workflow is not meant to depend on frontier-model memory: smaller or lower-cost coding models can still follow the router because the MCP tools carry the SUMO-specific checks.

```text
Use Torii to clean the Ingolstadt city-center network around https://www.openstreetmap.org/#map=17/48.765391/11.423800 from OSM, compare it with the TUM-VT/sumo_ingolstadt cleaned network for the same bbox, and open the cleaned network in Netedit.
```

This demo now uses Ingolstadt city center to test whether a Torii OSM-cleaned network converges toward a manually cleaned reference network instead of treating OSM import success as enough.

| Evidence | Result |
|---|---:|
| Torii OSM full-vehicle connected core | 1,427 edges, 1,978 lanes, 782 junctions in the comparison bbox |
| TUM cleaned reference subset | 3,577 edges, 4,955 lanes, 1,752 junctions in the same bbox |
| Traffic-light junctions | Torii 198 vs TUM 29 |
| Joined-junction evidence | Torii 0 joined-junction endpoint refs vs TUM 1,136 |
| Routeability smoke | both networks: 40 / 40 generated passenger trips arrived at `end=800` |
| Teleports / collisions | 0 / 0 |
| Claim status | `diagnostic-demo` |

See [`examples/04_one_prompt_osm_network`](examples/04_one_prompt_osm_network/README.md). The generated `.osm.xml`, `.net.xml`, route, and log files are intentionally not committed; the repository keeps the prompt and lightweight validation summary.

## Quick Start

Install from GitHub:

```powershell
codex plugin marketplace add Tarard/Torii-SUMO --ref main
codex plugin add torii-sumo@torii-sumo
```

Start a new Codex thread after installing so the plugin's skills and MCP tools are discovered.

Full setup details: [Codex Plugin Installation](docs/codex-plugin-install.md).

For local development:

```powershell
codex plugin marketplace add <path-to-this-repo>
codex plugin add torii-sumo@torii-sumo
```

Then ask:

```text
Use Torii to build and audit this SUMO network. Treat bad metrics as feedback about the model, not as the optimization target itself.
```

For MCP-first use, call `torii_auto_workflow` with the one-sentence request and an output directory.

## What You Can Ask Me

| Prompt | What Torii Does |
|---|---|
| "Use Torii to clean the Ingolstadt city-center network from OSM and compare it with TUM-VT/sumo_ingolstadt." | Confirms the area and road-detail target, builds a passenger-road SUMO network from OSM, extracts a connected simulation core when needed, compares topology/TLS evidence against the TUM cleaned reference, runs connectivity/routeability checks, opens Netedit, and reports a claim boundary. |
| "Build a SUMO network from this OSM bbox or extract." | Runs bounded OSM import, road-class filtering, XML deduplication, `netconvert`, and construction evidence capture. |
| "Make this SUMO network 100% connected for passenger routeability checks." | Extracts the largest passenger component into a reusable `connected-core` `.net.xml` and reports discarded fragments instead of hiding them. |
| "Audit the traffic lights in this SUMO network." | Extracts TLS candidates, prepares map-review fields, and separates SUMO-generated TLS from manually validated signal evidence. |
| "Create a region-aware map baseline review table for these SUMO traffic lights." | Builds a multi-source TLS evidence CSV with the right regional baseline, such as Google Maps where appropriate or Amap/Gaode, Baidu Maps, Tencent Maps, official inventories, signal plans, and field photos for mainland China. |
| "Clean a SUMO network for a city in mainland China." | Treats OSM as an import seed, uses region-aware defaults where possible, records WGS84/GCJ-02/BD-09 coordinate assumptions, and reports missing local-map evidence as a claim boundary instead of blocking the diagnostic build. |
| "Check whether these roads or bridges are connected." | Creates routeability probes and reports missing routes, disconnected components, teleports, and residual risk. |
| "This SUMO run finishes, but tripinfo and summary disagree." | Diagnoses output consistency, completion, insertion, teleport, route, and horizon problems before accepting metrics. |
| "Controller A has lower travel time, but some vehicles are unfinished." | Reports completion first, then demotes or bounds the performance claim. |
| "Compare fixed-time, actuated, max-pressure, and my TraCI controller." | Forces paired demand, seeds, horizon, output intervals, completion policy, and metric definitions before comparison. |
| "My waiting time got worse after cleanup." | Treats the metric as feedback and looks for network, demand, TLS, routing, or controller causes. |
| "Turn this fix I found into reusable guidance." | Abstracts the solution into a privacy-safe field lesson for future SUMO workflows. |

## What Torii Is

Torii has two layers:

| Layer | Role |
|---|---|
| Reasoning layer | SUMO expert skills that ask the right questions, choose a workflow, and bound claims. |
| Execution layer | Local stdio MCP tools that run bounded SUMO checks and return structured observations. |

Current MCP tools cover the `torii_auto_workflow` router, environment checks, config preflight, smoke runs, evidence bundles, OSM network construction, TLS candidates, multi-source TLS review tables, connectivity checks, connected-core extraction, routeability probes, completion-aware routeability audits, and Netedit launch evidence.

The original `Simulation Helper Skill for Eclipse SUMO` is now Torii's reasoning layer. The plugin bundles it with executable local tools.

## Boundaries

Torii is useful today, but it is not a magic SUMO certifier.

- It can build bounded OSM-to-SUMO networks from confirmed areas or extracts.
- It can produce diagnostic evidence for connectivity, connected-core extraction, routeability, outputs, warnings, TLS candidates, and completion.
- If raw OSM import contains small disconnected fragments, Torii keeps the raw network as audit evidence and routes downstream checks through a `connected-core` network built from the largest passenger component.
- If strict connectivity still fails after cleanup, Torii labels the network `partial-main-component`: usable for diagnostic smoke tests, not experiment-ready.
- It does not automatically certify full city networks, traffic-light timing/phasing, demand realism, controller correctness, or formal experiment validity.
- Reality baselines are region-specific. OSM is a useful open construction source, but it is not automatically the ground truth; mainland China workflows should use Amap/Gaode, Baidu Maps, Tencent Maps, official inventories, signal plans, or field photos as the current-road/TLS review baseline and record WGS84/GCJ-02/BD-09 coordinate-system assumptions.

## Development

Run tests:

```powershell
python -m pytest -q
```

Validate the plugin:

```powershell
python <codex-home>/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/torii-sumo
```

See [`docs/codex-plugin-install.md`](docs/codex-plugin-install.md) and [`docs/osm-source-patterns.md`](docs/osm-source-patterns.md) for implementation details.

## License and Notices

Source code is licensed under MIT. Skill files, docs, checklists, and protocol text are licensed under CC BY 4.0.

Eclipse SUMO is a trademark of the Eclipse Foundation. Map data in the OSM demo is © OpenStreetMap contributors and available under the Open Database License (ODbL).

Earlier skill-only releases are archived on Zenodo: https://doi.org/10.5281/zenodo.20627976

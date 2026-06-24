<p align="center">
  <img src="docs/assets/banner.png" alt="Torii agent plugin for SUMO banner">
</p>

# <img src="docs/assets/app-logo.png" width="42" alt="Torii logo"> Torii

<div align="center">

**Task-Oriented Road Infrastructure Intelligence**

**Agent plugin for SUMO**

<p><strong>Codex / Claude agent plugin</strong> · SUMO/TraCI workflows · OSM-to-SUMO cleanup · local MCP tools</p>

<a href="https://tarard.github.io/Torii-SUMO/"><strong>Website</strong></a> |
<a href="docs/codex-plugin-install.md"><strong>Install</strong></a> |
<a href="examples/01_signal_control_audit/task.md"><strong>Signal-Control Audit</strong></a> |
<a href="examples/04_one_prompt_osm_network/README.md"><strong>One-Prompt Demo</strong></a> |
<a href="LICENSE"><strong>License</strong></a>

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
| "Use Torii to clean the Ingolstadt city-center network from OSM and compare it with TUM-VT/sumo_ingolstadt." | Builds from OSM, checks connectivity and routeability, compares topology/TLS evidence with the reference, and opens Netedit. |
| "Audit this TraCI signal controller before I compare it with fixed-time or max-pressure." | Checks controller identity, paired demand/seeds/horizon, TLS mapping, outputs, and completion before any performance claim. |
| "This SUMO run finishes, but tripinfo and summary disagree." | Diagnoses output consistency, unfinished vehicles, teleports, route errors, and claim boundary. |

## What Torii Is

Torii has two layers:

| Layer | Role |
|---|---|
| Reasoning layer | SUMO expert skills that ask the right questions, choose a workflow, and bound claims. |
| Execution layer | Local stdio MCP tools that run bounded SUMO checks and return structured observations. |

Current MCP tools cover the `torii_auto_workflow` router, environment checks, config preflight, smoke runs, evidence bundles, OSM network construction, TLS candidates, multi-source TLS review tables, connectivity checks, connected-core extraction, routeability probes, completion-aware routeability audits, and Netedit launch evidence.

The original `Simulation Helper Skill for Eclipse SUMO` is now Torii's reasoning layer. The plugin bundles it with executable local tools.

## Boundaries

Torii builds and audits SUMO artifacts, but it does not certify a model as correct.

- OSM imports remain diagnostic until road scope, connectivity, routeability, TLS reality, and map baseline evidence are checked.
- `connected-core` networks are useful for smoke tests, but discarded fragments and topology warnings remain part of the claim boundary.
- It does not prove traffic-light timing, phasing, demand realism, controller correctness, or full experiment validity.

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

Source code is licensed under MIT. Skill files, docs, checklists, examples, and protocol text are licensed under CC BY 4.0. Both scopes are recorded in [`LICENSE`](LICENSE).

Eclipse SUMO is a trademark of the Eclipse Foundation. Map data in the OSM demo is © OpenStreetMap contributors and available under the Open Database License (ODbL).

Earlier skill-only releases are archived on Zenodo: https://doi.org/10.5281/zenodo.20627976

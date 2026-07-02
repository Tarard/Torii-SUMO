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
<a href="examples/02_one_prompt_osm_network/README.md"><strong>One-Prompt Demo</strong></a> |
<a href="LICENSE"><strong>License</strong></a>

[English](README.md) | [简体中文](README.zh-CN.md) | [Deutsch](README.de.md)

</div>

## Evidence-Aware OSM-to-SUMO Construction

Torii is designed for SUMO network construction work: one short natural-language prompt can become a bounded, evidence-aware, reference-comparable OSM-to-SUMO workflow with construction evidence, routeability checks, review artifacts, and a clear claim boundary.

The plugin now starts from a workflow router: `torii_auto_workflow` classifies the request, chooses skills, makes plans, and runs safe MCP steps to generate or modify the SUMO network for you.

Torii has two layers:

| Layer | Role |
|---|---|
| Reasoning layer | SUMO expert skills that ask the right questions, choose a workflow, and bound claims. |
| Execution layer | Local safe stdio MCP tools that run bounded SUMO checks and return structured observations. |

The architecture is documented in [`ARCHITECTURE.md`](ARCHITECTURE.md): router, planner, executor, and reviewer.

Current MCP tools cover the `torii_auto_workflow` router, environment checks, config preflight, smoke runs, evidence bundles, OSM network construction, TLS candidates, multi-source TLS review tables, TLS aggregation review variants, connectivity checks, connected-core extraction, routeability probes, completion-aware routeability audits, overlapping top-level junction audits, reference join audits, junction aggregation review variants, and Netedit launch evidence.

## Example

Use the prompt to test Torii:

```text
Use Torii to clean the Ingolstadt city-center network from OSM, compare it with the TUM-VT/sumo_ingolstadt cleaned network for the same bbox, and open the cleaned network in Netedit.
```

This demo uses Ingolstadt city center to test whether a Torii OSM-derived workflow becomes more auditable and closer to a manually cleaned reference network than raw import success alone.

![TUM bbox reference compared with Torii 5.5 TLS-aggregated visual-detail](examples/02_one_prompt_osm_network/assets/tum_vs_torii_5_5_tls_aggregated_overview.png)

| Evidence | Result |
|---|---:|
| Torii vehicle core | 2,493 edges, 3,045 lanes, 1,220 junctions in the comparison bbox after connected-core extraction |
| Torii reference visual-detail | 6,126 edges, 6,695 lanes, 2,997 junctions in the comparison bbox |
| TUM cleaned reference subset | 3,577 edges, 4,955 lanes, 1,752 junctions in the same bbox |
| Traffic-light junctions | Torii visual-detail raw 217; TLS aggregation review variant 34 vs TUM 29 |
| Remaining cleanup target | Google Maps review for the extra TLS candidates and reusable physical-junction aggregation |
| Claim status | `diagnostic-demo` |

See [`examples/02_one_prompt_osm_network`](examples/02_one_prompt_osm_network/README.md). The 5.5 comparison networks and screenshots are committed there; generated OSM extracts, route files, and full logs remain rebuild-only artifacts.

## Quick Start

Install from GitHub:

```powershell
codex plugin marketplace add Tarard/Torii-SUMO --ref main
codex plugin add torii-sumo@torii-sumo
```

Start a new Codex or Claude Code thread after installing so the plugin's skills and MCP tools are discovered.

Full setup details: [Codex Plugin Installation](docs/codex-plugin-install.md).

## What You Can Ask Me

| Prompt | What Torii Does |
|---|---|
| "Use Torii to clean the Ingolstadt city-center network from OSM and compare it with TUM-VT/sumo_ingolstadt." | Builds from OSM, checks connectivity and routeability, compares topology/TLS evidence with the reference, and opens Netedit. |
| "Audit this TraCI signal controller before I compare it with fixed-time or max-pressure." | Checks controller identity, paired demand/seeds/horizon, TLS mapping, outputs, and completion before any performance claim. |
| "This SUMO run finishes, but tripinfo and summary disagree." | Diagnoses output consistency, unfinished vehicles, teleports, route errors, and claim boundary. |

## Boundaries

Torii builds and audits SUMO artifacts, but it does not certify a model as correct.

- OSM imports remain diagnostic until road scope, connectivity, routeability, TLS reality, and map baseline evidence are checked.
- `connected-core` networks are useful for smoke tests, but discarded fragments and topology warnings remain part of the claim boundary.
- It does not prove traffic-light timing, phasing, demand realism, controller correctness, or full experiment validity.

## License and Notices

Source code is licensed under PolyForm Noncommercial 1.0.0. Skill files, docs, checklists, examples, and protocol text are licensed under CC BY-NC 4.0. Commercial use requires separate written permission. Both scopes are recorded in [`LICENSE`](LICENSE).

Eclipse SUMO is a trademark of the Eclipse Foundation. Map data in the OSM demo is © OpenStreetMap contributors and available under the Open Database License (ODbL).

Earlier skill-only releases are archived on Zenodo: https://doi.org/10.5281/zenodo.20627976

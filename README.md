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
<img src="https://img.shields.io/badge/MCP%20Tools-local%20stdio-c98a05" alt="Local stdio MCP tools">

<a href="https://tarard.github.io/Simulation-Helper-Skill-for-Eclipse-SUMO/"><strong>Website</strong></a> |
<a href="docs/codex-plugin-install.md"><strong>Codex Plugin Installation</strong></a> |
<a href="examples/01_fixed_time_audit/task.md"><strong>Examples</strong></a> |
<a href="docs/common-sumo-signal-control-failures.md"><strong>Failure Checklist</strong></a> |
<a href="LICENSE-CODE"><strong>MIT Code</strong></a> |
<a href="LICENSE-DOCS"><strong>CC BY 4.0 Docs</strong></a>

[English](README.md) | [简体中文](README.zh-CN.md) | [Deutsch](README.de.md)

</div>

> [!IMPORTANT]
> Torii is a plugin-and-skill package for agentic SUMO work. It already bundles executable local MCP tools for environment checks, config preflight, smoke runs, evidence bundles, OSM-to-SUMO network construction, TLS audit candidates, and routeability probes. It does not yet claim fully automatic place-name geocoding, full city-scale OSM cleanup, or controller generation as finished MCP tools.

> [!NOTE]
> This project is independent. It is not affiliated with, endorsed by, sponsored by, or maintained by the Eclipse Foundation, the Eclipse SUMO project, DLR, OpenAI, Anthropic, Google, or any external OSM tooling project.

## What Torii Is

Torii turns a coding agent into a more reliable SUMO assistant by giving it two layers:

| Layer | Role |
|---|---|
| Reasoning layer | The SUMO expert skill interprets the user's intent, chooses the workflow, asks for missing evidence, and explains what bad metrics imply. |
| Execution layer | The local MCP server runs bounded checks and returns structured observations: files, warnings, metrics, routes, TLS candidates, and evidence bundles. |

Installing Torii gives Codex both **skills and MCP tools**. The goal is not to make the agent chase a raw metric. The goal is to help the agent infer the modeling problem behind the metric, make the smallest defensible change, and report what the evidence can and cannot support.

## What You Can Ask

| User request | Torii response pattern |
|---|---|
| "Build a SUMO network from this OSM area." | Use bounded OSM import, tiled Overpass download or local extract reuse, road-class filtering, XML deduplication, `netconvert`, and artifact reporting. |
| "Clean this Munich core network." | If a bbox or extract is supplied, run the implemented OSM-to-SUMO path. If only a place name is supplied, route to a small clarification or code-development step until geocoding is implemented. |
| "Audit all traffic lights against Google Maps." | Extract SUMO TLS candidates, cluster likely physical intersections, generate Google Maps review links, and ask whether the baseline should be current Google Maps or a historical target date. |
| "Check whether these roads or bridges are connected." | Generate named-road routeability probes and report missing key edges, route generation evidence, and residual SUMO completion risk. |
| "My metrics got worse after a run." | Treat metrics as feedback: diagnose route, demand, network, TLS, controller, output, horizon, or completion problems before proposing code changes. |
| "Add a max-pressure controller." | Use the bundled SUMO skill and public controller-pattern guidance to plan and verify the implementation path. Full controller generation is a roadmap MCP tool, not a finished promise in this release. |

## Quick Start

Install from GitHub:

```powershell
codex plugin marketplace add Tarard/Simulation-Helper-Skill-for-Eclipse-SUMO --ref main
codex plugin add torii-sumo@torii-sumo
```

Start a new Codex thread after installing or reinstalling so the plugin's skills and MCP tools are discovered.

For local development, run the marketplace command from a checkout or pass the checkout path:

```powershell
codex plugin marketplace add <path-to-this-repo>
codex plugin add torii-sumo@torii-sumo
```

Manual skill-only usage is still supported. Copy the root skill folders into a repository-scoped skill directory:

```text
.agents/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

Then ask the agent:

```text
Use Torii to build and audit this SUMO network. Treat bad metrics as feedback about the model, not as the optimization target itself.
```

## Repository Layout

```text
plugins/
  torii-sumo/
    .codex-plugin/plugin.json        # Codex plugin manifest
    .mcp.json                        # local stdio MCP server config
    scripts/run_torii_sumo.py        # bundled server launcher
    src/torii_sumo/                  # MCP tool implementation
    skills/simulation-helper-skill-for-eclipse-sumo/

skills/
  simulation-helper-skill-for-eclipse-sumo/      # manual skill install path
  debugging-helper-skill-for-eclipse-sumo/       # focused SUMO/TraCI debugging skill

docs/
  codex-plugin-install.md
  osm-source-patterns.md
  skill-integration.md
```

The original `Simulation Helper Skill for Eclipse SUMO` is not deleted. It is now Torii's reasoning layer, and the installable plugin bundles it together with the MCP execution layer.

## Implemented MCP Tools

| Tool | Current scope |
|---|---|
| `sumo_preflight` | Detect SUMO/Python/TraCI environment evidence before experiment claims. |
| `sumo_get_environment` | Return structured environment details for handoff and diagnosis. |
| `sumo_config_pair_preflight` | Check paired `.sumocfg` inputs for missing files and shared outputs. |
| `sumo_run_config` | Run a bounded SUMO config and return logs and declared-output observations. |
| `sumo_run_minimal_smoke` | Produce a small diagnostic smoke proof for local toolchain checks. |
| `sumo_compare_outputs` | Compare summary/tripinfo outputs with completion-first reporting. |
| `sumo_collect_evidence` | Write a reproducibility evidence bundle. |
| `sumo_osm_build_network` | Download or reuse OSM extracts, tile Overpass calls, retry, deduplicate XML, filter roads, and run `netconvert`. |
| `sumo_tls_audit` | Extract TLS candidates, cluster review groups, and attach Google Maps temporal-baseline fields. |
| `sumo_network_routeability_probe` | Generate named-road routeability probe routes and a bounded `.sumocfg`. |

See [`docs/codex-plugin-install.md`](docs/codex-plugin-install.md) for installation details and [`docs/osm-source-patterns.md`](docs/osm-source-patterns.md) for the OSM architecture borrowed from OSMnx, OSMNet, pyrosm, SUMO `osmGet/osmBuild`, and osm-to-xodr without vendoring their source code.

## Feedback Diagnosis

Torii uses bad run evidence as feedback:

```text
user intent
-> observed SUMO outputs, warnings, metrics, and logs
-> diagnose what the metric implies
-> identify the likely network, demand, routing, controller, code, or experiment-design problem
-> choose the smallest next change
-> rerun the relevant check
-> report whether the user's intent is better satisfied
```

Examples:

- Low arrived count can indicate disconnected routes, failed insertion, too short a horizon, or blocked signal phases.
- High waiting time can indicate wrong phase-lane mapping, joined TLS that should be split, demand outside the intended scope, or an unsuitable controller policy.
- Teleports are construction or control feedback, not a result to hide.
- A better average with worse completion is not a clean win; completion regression is reported first.

## Included Skills

| Skill | Use when | Main outputs |
|---|---|---|
| `simulation-helper-skill-for-eclipse-sumo` | Planning, OSM modeling, TLS audit, controller work, result interpretation, evidence bundles, and release checks. | Project control screen, readiness record, SUMO experiment plan, feedback diagnosis, claim boundary. |
| `debugging-helper-skill-for-eclipse-sumo` | SUMO/TraCI route, demand, detector, TLS, output, seed, completion, reproducibility, or runtime failures. | Fault class, next diagnostic probe, evidence, fix/rerun/demotion decision. |

## Current Boundaries

Torii is useful today, but it should stay honest:

- It can build SUMO networks from supplied bbox/extract inputs; place-name geocoding is not yet a finished MCP tool.
- It can assist OSM cleanup with road-class selection, deduplication, TLS candidates, routeability probes, and warnings; it does not certify a whole city network automatically.
- It can use Google Maps as an external reality baseline only after the user confirms whether the intended reference is current or historical.
- It can guide controller implementation using public patterns such as SUMO Lights; full controller generation and controller-log inspection are roadmap tools.
- It can support evidence-bounded claims; it does not certify experiment correctness.

## Development

Run tests from the repository root:

```powershell
python -m pytest -q
```

Validate the plugin:

```powershell
python <codex-home>/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/torii-sumo
```

Validate the bundled skill:

```powershell
python <codex-home>/skills/.system/skill-creator/scripts/quick_validate.py plugins/torii-sumo/skills/simulation-helper-skill-for-eclipse-sumo
```

## License

Source code is licensed under MIT. See [`LICENSE-CODE`](LICENSE-CODE).

Skill files, documentation, checklists, and protocol text are licensed under Creative Commons Attribution 4.0 International (`CC BY 4.0`). See [`LICENSE-DOCS`](LICENSE-DOCS).

## Trademark Notice

Eclipse SUMO is a trademark of the Eclipse Foundation. This project supports workflows for experiments using Eclipse SUMO, but it is independent and does not use official Eclipse or Eclipse SUMO logos.

Google Maps is referenced as an external map-review baseline. Torii is not affiliated with Google, and map reviews should respect the user's temporal modeling target.

## References and Related Resources

These links provide context. They do not imply endorsement of this repository.

- Eclipse SUMO documentation and licensing pages: [About Eclipse SUMO](https://eclipse.dev/sumo/about/), [SUMO FAQ](https://sumo.dlr.de/docs/FAQ.html), and [SUMO Downloads and Licensing Note](https://sumo.dlr.de/docs/Downloads.html).
- Eclipse Foundation trademark usage policy: [Eclipse Foundation Trademark Usage Policy](https://www.eclipse.org/legal/logo-guidelines/).
- Public OSM/SUMO architecture references used as design input, without vendored source: OSMnx, OSMNet, pyrosm, SUMO `osmGet/osmBuild`, and osm-to-xodr.
- Public controller-pattern reference: SUMO Lights.

## Archive

Earlier skill-only releases are archived on Zenodo: https://doi.org/10.5281/zenodo.20627976

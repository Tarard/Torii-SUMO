<p align="center">
  <img src="docs/assets/banner.png" alt="Torii for SUMO" width="100%">
</p>

# Torii

<p align="center">
  <strong>Task-Oriented Road Infrastructure Intelligence for Eclipse SUMO</strong>
</p>

<p align="center">
  An agent plugin for building, checking, and reviewing SUMO networks from natural-language tasks.
</p>

<p align="center">
  <a href="https://tarard.github.io/Torii-SUMO/">Website</a> ·
  <a href="docs/codex-plugin-install.md">Installation</a> ·
  <a href="docs/README.md">Documentation</a> ·
  <a href="examples/01_signal_control_audit/task.md">Examples</a> ·
  <a href="LICENSE">Apache-2.0 License</a>
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.de.md">Deutsch</a>
</p>

## Overview

Torii connects an AI coding agent with local SUMO tools. It turns a task such as network construction, signal review, or routeability testing into a bounded workflow with saved evidence.

Torii has two parts:

- **Expert skills** plan the workflow, select checks, and state what the result supports.
- **MCP tools** run SUMO, TraCI, NetEdit, OSM conversion, audits, and evidence export.

The main entry point is `torii_auto_workflow`. It classifies a request and selects the relevant Torii tools.

## What Torii Does

- Builds SUMO networks from OSM extracts.
- Checks SUMO and TraCI environments.
- Audits traffic signals, connections, junctions, and road hierarchy.
- Tests network connectivity and routeability.
- Creates review variants without overwriting the source network.
- Produces JSON, GeoJSON, HTML, logs, and hash-bound evidence.
- Supports detector, signal, and route reconstruction workflows for corridor studies.

Torii treats uncertain map or field information as a review item. It does not silently certify an inferred network as ground truth.

## Installation

### From GitHub

```powershell
codex plugin marketplace add Tarard/Torii-SUMO --ref main
codex plugin add torii-sumo@torii-sumo
```

Start a new Codex session after installation.

### Local development

```powershell
git clone https://github.com/Tarard/Torii-SUMO.git
cd Torii-SUMO
python -m pip install -e ".[dev]"
```

Requirements:

- Python 3.11 or later
- Eclipse SUMO with `sumo`, `netconvert`, and `netedit` available
- Codex with plugin and local MCP support

See the [installation guide](docs/codex-plugin-install.md) for setup details.

## Quick Start

Ask the agent to use Torii for a concrete SUMO task:

```text
Use Torii to build a passenger-road SUMO network from this OSM area.
Check connectivity, audit traffic signals, test routeability, and save a review package.
```

For direct tool use, start with:

```text
torii_auto_workflow
```

The workflow returns its plan, executed checks, generated files, blocked gates, and supported claim level.

## Example Workflows

| Workflow | Example |
|---|---|
| Signal-control audit | [`examples/01_signal_control_audit`](examples/01_signal_control_audit/task.md) |
| One-prompt OSM network | [`examples/02_one_prompt_osm_network`](examples/02_one_prompt_osm_network/README.md) |
| Four-way signal review | [`examples/03_xs1_four_way_tls`](examples/03_xs1_four_way_tls/README.md) |
| Three-way signal review | [`examples/04_xs2_three_way_tls`](examples/04_xs2_three_way_tls/README.md) |

## Hamburg Corridor Project

Torii is being tested on a three-intersection digital-twin workflow for the **Am Sandtorkai 2349 → 2394 → 2403** corridor in Hamburg.

<p align="center">
  <img src="docs/assets/hamburg-digital-twin/torii-2403-junction-connection.png" alt="Detailed view of Hamburg junction 2403 in SUMO NetEdit Connection Mode" width="100%">
</p>

| Workstream | Current result |
|---|---|
| Network construction | The OSM corridor has been cleaned and materialized as a reviewable SUMO network. |
| Signal binding | Official signal data has been bound to nodes 2349 and 2394. Node 2403 lacks a published MAP or OCIT package. |
| Detector model | The route-to-sensor matrix has shape 6 × 58, rank 6, and nullity 52. The recovered route set is therefore non-unique. |
| Diagnostic fit | The signal-disabled diagnostic matches all 5,928 official detector counts across 60 bins. |
| Signal-history replay | The 7,200-second replay uses 15 candidate routes, matches all route constraints, and has zero collisions and zero teleports. |
| Current status | `detector-constrained-diagnostic-replay`. Promotion to an accepted field digital twin remains blocked. |

The next step is to rebuild the signal, detector-mapping, and replay stages against one hash-bound network version. The remaining field gates include node 2403 signal data and unresolved lane identities.

See the [machine-readable evidence summary](docs/hamburg-digital-twin-evidence-summary.json) and the [development log](docs/hamburg-digital-twin-development-log.md).

## Project Structure

```text
plugins/torii-sumo/   Installable Codex plugin and MCP server
docs/                 Guides, architecture, methods, and evidence
examples/             Small reproducible workflows
tests/                Automated tests
experiments/          Research and validation scripts
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the router, planner, executor, and reviewer design.

## Current Scope

Torii supports bounded construction and review workflows. Its strongest automated results cover machine checks such as SUMO loading, connection consistency, route completion, collision and teleport detection, and output provenance.

Human review or official data remains necessary for claims about real signal operation, exact lane identity, field timing, physical junction meaning, and authoritative network correctness.

## Development

Run the tests:

```powershell
python -m pytest
```

Run the linter:

```powershell
python -m ruff check .
```

Contributions should keep source inputs immutable, write modified networks as separate candidates, and preserve the evidence behind each result.

## Documentation

- [Documentation index](docs/README.md)
- [Installation](docs/codex-plugin-install.md)
- [Repository guide](docs/repository-guide.md)
- [MCP tool catalog](docs/mcp-tool-catalog.md)
- [Architecture](ARCHITECTURE.md)

## Citation

Earlier skill-only releases are archived on Zenodo:

```text
https://doi.org/10.5281/zenodo.20627976
```

## License

Torii is released under the [Apache License 2.0](LICENSE).

Eclipse SUMO is a trademark of the Eclipse Foundation. OpenStreetMap data is © OpenStreetMap contributors and is available under the Open Database License.
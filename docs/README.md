# Torii Documentation

This page is the stable entry point for Torii's user, architecture, workflow, and research documentation. It keeps the top-level README short while preserving detailed evidence and protocol records.

## Start by Goal

| Goal | Start here |
|---|---|
| Install the Codex plugin | [Codex Plugin Installation](codex-plugin-install.md) |
| Understand what belongs where | [Repository Guide](repository-guide.md) |
| Understand the system and claim boundary | [Architecture](../ARCHITECTURE.md) |
| Find an MCP tool | [MCP Tool Catalog](mcp-tool-catalog.md) |
| Run the one-prompt OSM demonstration | [Ingolstadt example](../examples/02_one_prompt_osm_network/README.md) |
| Reproduce the small-network topology work | [Teacher-free topology discrimination v4](teacher-free-topology-discrimination-v4.md) |
| Inspect current corridor evaluation evidence | [Stage 1-M machine review-ready plan](stage1-machine-review-ready-plan.md) |
| Follow the Hamburg Am Sandtorkai digital-twin loop | [Hamburg corridor Codex execution workflow](hamburg-sandtorkai-codex-execution-workflow.md) |
| Follow the manuscript argument | [Research Paper Blueprint](research-paper-blueprint.md) |

## Architecture and Integration

- [Architecture](../ARCHITECTURE.md) - product claim, router/planner/executor/reviewer layers, promotion rule, and non-goals.
- [Repository Guide](repository-guide.md) - directory ownership, dependency direction, and placement rules for new work.
- [MCP Tool Catalog](mcp-tool-catalog.md) - the public tool surface grouped by user intent.
- [Skill Integration](skill-integration.md) - how the SUMO reasoning skill is discovered and invoked.
- [MCP Host Configuration](mcp-host-config.md) - direct MCP host setup.
- [OSM Source Patterns](osm-source-patterns.md) - external OSM/SUMO acquisition and conversion patterns without source vendoring.
- [Common SUMO Signal-Control Failures](common-sumo-signal-control-failures.md) - recurrent controller and evidence failures.
- [Hamburg corridor Codex execution workflow](hamburg-sandtorkai-codex-execution-workflow.md) - the plan/test/real-run/audit/revise loop and the named 2349/2394/2403 scope contract.

## Reproducible Workflows

- [Standard small-network v1](standard-small-network-v1.md)
- [Teacher-free OSM signal discovery v2](teacher-free-osm-signal-discovery-v2.md)
- [Teacher-free materialization v3](teacher-free-materialization-v3.md)
- [Teacher-free topology discrimination v4](teacher-free-topology-discrimination-v4.md)
- [Held-out corridor blind-review protocol](held-out-corridor-blind-review-protocol.md)
- [Held-out corridor blind-review protocol v2](held-out-corridor-blind-review-protocol-v2.md)

Runnable examples live under [`examples/`](../examples/). Frozen evaluation assets and protocols live under [`benchmarks/`](../benchmarks/). Command-line experiment entry points live under [`plugins/torii-sumo/scripts/`](../plugins/torii-sumo/scripts/).

## Research Status and Planning

- [Stage 1-M machine review-ready plan](stage1-machine-review-ready-plan.md)
- [Corridor research implementation status](torii-corridor-research-implementation-status.md)
- [Corridor human-modeling research plan](torii-corridor-human-modeling-research-plan.md)
- [Corridor human-modeling implementation status](torii-corridor-human-modeling-implementation-status.md)
- [Research handoff, 2026-07-14](research-plan-handoff-2026-07-14.md)
- [Architecture audit, 2026-07-13](architecture-audit-2026-07-13.md)
- [Research Paper Blueprint](research-paper-blueprint.md)

Documents with a date or version in their filename are evidence snapshots. They should not silently replace the current product boundary in the top-level README or `ARCHITECTURE.md`.

## Documentation Rules

1. Put stable user navigation in this file and the top-level README.
2. Put system invariants and claim boundaries in `ARCHITECTURE.md`.
3. Put workflow-specific protocols in a named Markdown document under `docs/`.
4. Put runnable demonstrations in `examples/`, not in documentation prose alone.
5. Put frozen evaluation inputs and adjudication protocols in `benchmarks/`.
6. Keep generated run artifacts out of `docs/`; place them under `outputs/` or an explicit artifact directory.
7. Mark historical or superseded protocols explicitly instead of deleting evidence needed for reproducibility.

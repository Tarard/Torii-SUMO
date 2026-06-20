from __future__ import annotations

import anyio
from mcp.server.fastmcp import FastMCP

from .tools.environment_tools import sumo_get_environment, sumo_preflight
from .tools.evidence_tools import (
    sumo_collect_evidence,
    sumo_compare_outputs,
    sumo_config_pair_preflight,
)
from .tools.osm_tools import (
    sumo_network_routeability_probe,
    sumo_osm_build_network,
    sumo_tls_audit,
)
from .tools.run_tools import sumo_run_config, sumo_run_minimal_smoke


def create_server() -> FastMCP:
    server = FastMCP("Torii")

    server.tool(description="Return Python and SUMO environment discovery evidence.")(sumo_get_environment)
    server.tool(description="Run SUMO environment preflight and return a construction-check report.")(sumo_preflight)
    server.tool(description="Inspect a baseline and variant .sumocfg pair for missing inputs and shared outputs.")(
        sumo_config_pair_preflight
    )
    server.tool(description="Run a bounded SUMO config with stdout and stderr captured.")(sumo_run_config)
    server.tool(description="Run a generated minimal SUMO smoke scenario when SUMO binaries are available.")(
        sumo_run_minimal_smoke
    )
    server.tool(description="Compare baseline and variant SUMO summary/tripinfo outputs.")(
        sumo_compare_outputs
    )
    server.tool(description="Write a JSON and Markdown evidence bundle.")(
        sumo_collect_evidence
    )
    server.tool(description="Download or reuse OSM, filter road classes, and build a SUMO network with netconvert.")(
        sumo_osm_build_network
    )
    server.tool(description="Extract SUMO TLS audit candidates and cluster nearby physical intersections.")(
        sumo_tls_audit
    )
    server.tool(description="Generate routeability probe routes and a bounded .sumocfg for named key roads.")(
        sumo_network_routeability_probe
    )

    return server


async def _run_stdio() -> None:
    server = create_server()
    await server.run_stdio_async()


def main() -> None:
    anyio.run(_run_stdio)


if __name__ == "__main__":
    main()

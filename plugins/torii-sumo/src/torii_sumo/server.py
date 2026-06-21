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
    sumo_osm_cleanup_workflow,
    sumo_osm_resolve_place,
    sumo_tls_audit,
    sumo_tls_multisource_review,
)
from .tools.run_tools import sumo_run_config, sumo_run_minimal_smoke
from .tools.workflow_tools import torii_auto_workflow


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
    server.tool(description="Route one natural-language SUMO request into a Torii workflow, ask only blocking questions, and run safe MCP steps when possible.")(
        torii_auto_workflow
    )
    server.tool(description="Resolve an OSM place name to a candidate area, bbox, and OSM confirmation links.")(
        sumo_osm_resolve_place
    )
    server.tool(description="Run the OSM cleanup hard-gate workflow: area confirmation, OSM build, TLS map audit, connectivity check, SUMO-GUI launch, and Netedit launch.")(
        sumo_osm_cleanup_workflow
    )
    server.tool(description="Download or reuse OSM, filter road classes, and build a SUMO network with netconvert.")(
        sumo_osm_build_network
    )
    server.tool(description="Extract SUMO TLS audit candidates and cluster nearby physical intersections.")(
        sumo_tls_audit
    )
    server.tool(description="Create a human-review TLS evidence table with OSM, Google Maps, Mapillary, KartaView, official inventory, signal-plan, and field-evidence fields.")(
        sumo_tls_multisource_review
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

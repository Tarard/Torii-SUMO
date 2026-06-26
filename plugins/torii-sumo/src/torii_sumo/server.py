from __future__ import annotations

import anyio
from mcp.server.fastmcp import FastMCP

from .tools.environment_tools import sumo_get_environment, sumo_preflight
from .tools.demand_tools import (
    sumo_detector_count_audit,
    sumo_detector_count_constraints,
    sumo_detector_route_support,
)
from .tools.evidence_tools import (
    sumo_collect_evidence,
    sumo_compare_outputs,
    sumo_config_pair_preflight,
)
from .tools.osm_tools import (
    sumo_network_connected_core,
    sumo_network_junction_aggregation_variant,
    sumo_network_overlapping_junction_audit,
    sumo_network_reference_hierarchy_audit,
    sumo_network_reference_join_audit,
    sumo_network_reference_scope_audit,
    sumo_network_review_html,
    sumo_network_routeability_audit,
    sumo_network_routeability_probe,
    sumo_network_scope_pruning_variant,
    sumo_network_teacher_guided_junction_variant,
    sumo_network_tls_aggregation_variant,
    sumo_network_topology_audit,
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
    server.tool(description="Route one natural-language SUMO request, including OSM map URLs, into a full Torii workflow with cleanup, audits, review HTML, SUMO-GUI, and Netedit evidence.")(
        torii_auto_workflow
    )
    server.tool(description="Resolve an OSM place name to a candidate area, bbox, and OSM confirmation links.")(
        sumo_osm_resolve_place
    )
    server.tool(description="Run the OSM cleanup hard-gate workflow from a place name, bbox, or OSM map URL: area inference/confirmation, traffic-layer or reference-artifact planning, OSM build, TLS map audit, connectivity, routeability, review HTML, SUMO-GUI, and Netedit launch.")(
        sumo_osm_cleanup_workflow
    )
    server.tool(description="Low-level helper only: download/reuse OSM for an already chosen bbox, filter road classes, and build a raw SUMO network with netconvert. Do not use this as the full user-facing workflow.")(
        sumo_osm_build_network
    )
    server.tool(description="Extract SUMO TLS audit candidates and cluster nearby physical intersections.")(
        sumo_tls_audit
    )
    server.tool(description="Create a human-review TLS evidence table with OSM, region-aware map links such as Amap/Gaode or Google Maps, Mapillary, KartaView, official inventory, signal-plan, and field-evidence fields.")(
        sumo_tls_multisource_review
    )
    server.tool(description="Extract the largest passenger component of a SUMO network into a connected-core .net.xml and report discarded fragments.")(
        sumo_network_connected_core
    )
    server.tool(description="Generate routeability probe routes and a bounded .sumocfg for named key roads.")(
        sumo_network_routeability_probe
    )
    server.tool(description="Run a completion-aware SUMO routeability audit, extending the horizon until all generated vehicles finish or max_end is reached.")(
        sumo_network_routeability_audit
    )
    server.tool(description="Audit dense SUMO junction clusters, including physical cross/T approach-axis shape scoring for over-fragmented OSM topology.")(
        sumo_network_topology_audit
    )
    server.tool(description="Audit close overlapping top-level SUMO junctions while ignoring valid internal crossing and walkingarea layers.")(
        sumo_network_overlapping_junction_audit
    )
    server.tool(description="Mine joined-junction cases from a reference SUMO network and match them against fragmented candidate topology clusters.")(
        sumo_network_reference_join_audit
    )
    server.tool(description="Audit high-hierarchy road differences against a reference network, separating over-split corridors, out-of-scope roads, hierarchy mismatches, and link/slip-lane cases.")(
        sumo_network_reference_hierarchy_audit
    )
    server.tool(description="Compare a candidate SUMO network against a reference network by OSM road-type scope and flag over-included short detail fragments for review.")(
        sumo_network_reference_scope_audit
    )
    server.tool(description="Create a separate SUMO plain-nodes junction-join patch and review variant from topology or reference-join audit reports without overwriting the source network.")(
        sumo_network_junction_aggregation_variant
    )
    server.tool(description="Create a separate reference-scope pruning review variant from a reference scope audit without overwriting the source network.")(
        sumo_network_scope_pruning_variant
    )
    server.tool(description="Build a diagnostic teacher-guided junction variant by replaying reference lane permissions, movements, pedestrian ring, and tlLogic onto candidate plain network files; requires NetEdit connection-mode review before adoption.")(
        sumo_network_teacher_guided_junction_variant
    )
    server.tool(description="Create a separate TLS cleanup review variant with one real SUMO junction set as TLS per physical TLS audit cluster.")(
        sumo_network_tls_aggregation_variant
    )
    server.tool(description="Create an HTML human-review cockpit for a generated or partial SUMO network and available audit artifacts.")(
        sumo_network_review_html
    )
    server.tool(description="Build sanitized source/sink, route-candidate, and route-detector-incidence manifests for detector-constrained SUMO demand reconstruction.")(
        sumo_detector_route_support
    )
    server.tool(description="Aggregate expected detector counts into sanitized time-bin constraints and SUMO routeSampler edgeData.")(
        sumo_detector_count_constraints
    )
    server.tool(description="Compare expected detector counts against SUMO E1 detector output and report detector-fit metrics.")(
        sumo_detector_count_audit
    )

    return server


async def _run_stdio() -> None:
    server = create_server()
    await server.run_stdio_async()


def main() -> None:
    anyio.run(_run_stdio)


if __name__ == "__main__":
    main()

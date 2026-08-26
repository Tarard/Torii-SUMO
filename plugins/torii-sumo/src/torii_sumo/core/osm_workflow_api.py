"""Request-based API for the legacy OSM cleanup workflow.

This module is the first compatibility layer of the OSM workflow refactor.
It keeps :func:`torii_sumo.core.osm_workflow.run_osm_cleanup_workflow`
untouched as the implementation, but exposes a typed request entry point and
a services container for the 40 injectable callables currently passed as
keyword arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import inspect
from typing import Any, Callable

from . import osm_workflow as _workflow
from .osm_workflow_request import OsmWorkflowRequest


@dataclass(frozen=True)
class OsmWorkflowServices:
    """Injectable service callables for the OSM cleanup workflow.

    ``None`` means "use the legacy workflow default".  Use
    :meth:`default` to obtain a fully populated container whose values are
    taken from the current ``run_osm_cleanup_workflow`` signature, so this
    dataclass cannot drift when a default is changed in the legacy function.
    """

    build_func: Callable[..., dict[str, Any]] | None = None
    tls_audit_func: Callable[..., dict[str, Any]] | None = None
    connectivity_func: Callable[..., dict[str, Any]] | None = None
    connected_core_func: Callable[..., dict[str, Any]] | None = None
    routeability_func: Callable[..., dict[str, Any]] | None = None
    topology_audit_func: Callable[..., dict[str, Any]] | None = None
    routeability_audit_func: Callable[..., dict[str, Any]] | None = None
    connection_mode_audit_func: Callable[..., dict[str, Any]] | None = None
    standard_nema_binding_func: Callable[..., dict[str, Any]] | None = None
    tls_aggregation_func: Callable[..., dict[str, Any]] | None = None
    tls_signal_grouping_func: Callable[..., dict[str, Any]] | None = None
    tls_low_vehicle_control_func: Callable[..., dict[str, Any]] | None = None
    tls_non_controller_junction_demotion_func: Callable[..., dict[str, Any]] | None = None
    tls_connection_repair_func: Callable[..., dict[str, Any]] | None = None
    junction_aggregation_func: Callable[..., dict[str, Any]] | None = None
    reference_hierarchy_audit_func: Callable[..., dict[str, Any]] | None = None
    reference_hierarchy_type_repair_func: Callable[..., dict[str, Any]] | None = None
    reference_join_audit_func: Callable[..., dict[str, Any]] | None = None
    reference_join_aggregation_func: Callable[..., dict[str, Any]] | None = None
    teacher_guided_repair_queue_func: Callable[..., dict[str, Any]] | None = None
    teacher_guided_plain_export_func: Callable[..., dict[str, Any]] | None = None
    teacher_guided_repair_run_func: Callable[..., dict[str, Any]] | None = None
    teacher_guided_probe_matrix_func: Callable[..., dict[str, Any]] | None = None
    teacher_guided_direct_replay_func: Callable[..., dict[str, Any]] | None = None
    road_connectivity_replay_func: Callable[..., dict[str, Any]] | None = None
    road_connectivity_seed_probe_func: Callable[..., dict[str, Any]] | None = None
    road_connection_topology_replay_func: Callable[..., dict[str, Any]] | None = None
    road_connectivity_parity_func: Callable[..., dict[str, Any]] | None = None
    reference_scope_audit_func: Callable[..., dict[str, Any]] | None = None
    scope_pruning_func: Callable[..., dict[str, Any]] | None = None
    corridor_geometry_simplification_func: Callable[..., dict[str, Any]] | None = None
    corridor_edit_ledger_func: Callable[..., dict[str, Any]] | None = None
    netedit_func: Callable[..., dict[str, Any]] | None = None
    netedit_review_func: Callable[..., dict[str, Any]] | None = None
    sumo_gui_func: Callable[..., dict[str, Any]] | None = None
    place_resolver: Callable[..., dict[str, Any]] | None = None
    reference_bbox_func: Callable[..., dict[str, Any]] | None = None
    reference_bbox_scope_func: Callable[..., dict[str, Any]] | None = None
    service_permission_func: Callable[..., dict[str, Any]] | None = None
    review_html_func: Callable[..., dict[str, Any]] | None = None
    command_runner: Callable[..., Any] | None = None

    @classmethod
    def default(cls) -> "OsmWorkflowServices":
        """Build services from the current legacy signature defaults."""

        signature = inspect.signature(_workflow.run_osm_cleanup_workflow)
        parameters = signature.parameters
        values: dict[str, Any] = {}
        for service_field in fields(cls):
            try:
                parameter = parameters[service_field.name]
            except KeyError as exc:
                raise TypeError(
                    f"OsmWorkflowServices field {service_field.name!r} is not a "
                    f"run_osm_cleanup_workflow parameter"
                ) from exc
            if parameter.default is inspect.Parameter.empty:
                raise TypeError(
                    f"OsmWorkflowServices field {service_field.name!r} maps to "
                    f"a required run_osm_cleanup_workflow parameter"
                )
            values[service_field.name] = parameter.default
        return cls(**values)

    def to_kwargs(self) -> dict[str, Any]:
        """Return only the explicitly configured service callables."""

        return {
            service_field.name: value
            for service_field in fields(self)
            if (value := getattr(self, service_field.name)) is not None
        }


def run_osm_cleanup_workflow_with_request(
    request: OsmWorkflowRequest,
    *,
    services: OsmWorkflowServices | None = None,
) -> dict[str, Any]:
    """Run the legacy OSM cleanup workflow from a typed request.

    ``services`` may be partially populated; any unset service falls back to
    the default from the legacy workflow signature.
    """

    if not isinstance(request, OsmWorkflowRequest):
        raise TypeError("request must be an OsmWorkflowRequest instance")

    resolved_services = services or OsmWorkflowServices.default()
    kwargs = request.to_legacy_kwargs()
    kwargs.update(resolved_services.to_kwargs())
    return _workflow.run_osm_cleanup_workflow(**kwargs)

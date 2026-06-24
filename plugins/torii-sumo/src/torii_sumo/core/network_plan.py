from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .road_scope import DRIVE_HIGHWAYS, HIGHWAY_CLASS_PRESETS, resolve_highway_classes


MOVEMENT_LAYER_OPTIONS = ("passenger", "bicycle", "pedestrian", "bus")
NETWORK_DETAIL_OPTIONS = (
    "arterial_core",
    "passenger_vehicle",
    "passenger_plus_service",
    "bicycle",
    "pedestrian",
    "multimodal",
    "reference_matched",
)
NETWORK_PLAN_QUESTION = (
    "Which traffic layers should Torii model: passenger vehicles, service/access roads, "
    "bicycle, pedestrian, bus/public transport, or a reference-matched SUMO network?"
)

_BICYCLE_HIGHWAYS = {"cycleway", "path"}
_PEDESTRIAN_HIGHWAYS = {"footway", "pedestrian", "path", "steps"}

_TUM_INGOLSTADT_HIGHWAYS = set(HIGHWAY_CLASS_PRESETS["full_vehicle"]) | _BICYCLE_HIGHWAYS | _PEDESTRIAN_HIGHWAYS
_TUM_INGOLSTADT_LAYERS = ("passenger", "bicycle", "pedestrian", "bus")


def _as_tokens(value: str | Iterable[str] | None) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        pieces = value.replace(";", ",").split(",")
    else:
        pieces = list(value)
    return {str(item).strip().lower().replace("-", "_") for item in pieces if str(item).strip()}


def _normalize_network_profile(value: str | None) -> str:
    normalized = (value or "").strip().lower().replace("-", "_")
    aliases = {
        "tum": "tum_ingolstadt",
        "tum_ingolstadt_full_vehicle": "tum_ingolstadt",
        "sumo_ingolstadt": "tum_ingolstadt",
        "tum_vt_ingolstadt": "tum_ingolstadt",
    }
    return aliases.get(normalized, normalized)


def _infer_reference_profile(user_request: str | None) -> str:
    text = " ".join((user_request or "").lower().split())
    if "tum" in text and ("ingolstadt" in text or "inglostadt" in text):
        return "tum_ingolstadt"
    if "sumo_ingolstadt" in text:
        return "tum_ingolstadt"
    return ""


def _highways_for_layers(layers: set[str]) -> set[str]:
    highways = set()
    if not layers or layers & {"passenger", "vehicle", "car", "bus"}:
        highways |= set(DRIVE_HIGHWAYS) | {"unclassified"}
    if layers & {"service", "access", "passenger_plus_service"}:
        highways |= set(DRIVE_HIGHWAYS) | {"unclassified", "service"}
    if layers & {"bicycle", "bike", "bikeway", "cycleway"}:
        highways |= _BICYCLE_HIGHWAYS
    if layers & {"pedestrian", "walk", "footway"}:
        highways |= _PEDESTRIAN_HIGHWAYS
    return highways


def _blocked_plan() -> dict[str, Any]:
    return {
        "status": "blocked",
        "claim_status": "blocked",
        "network_plan_status": "needs_user_confirmation",
        "missing_blockers": ["network_plan"],
        "next_question": NETWORK_PLAN_QUESTION,
        "traffic_layer_options": list(MOVEMENT_LAYER_OPTIONS),
        "network_detail_options": list(NETWORK_DETAIL_OPTIONS),
        "recommended_network_detail": "arterial_core",
        "movement_layers": [],
        "highway_classes": [],
        "service_passenger_policy": "sumo_default",
        "validation_gates": [],
    }


def _tum_ingolstadt_plan() -> dict[str, Any]:
    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "network_plan_status": "inferred_from_reference",
        "network_profile": "tum_ingolstadt",
        "reference_target": "TUM-VT/sumo_ingolstadt",
        "network_detail_target": "reference_matched",
        "movement_layers": list(_TUM_INGOLSTADT_LAYERS),
        "highway_classes": sorted(_TUM_INGOLSTADT_HIGHWAYS),
        "service_passenger_policy": "reference_match",
        "cleanup_policy": [
            "preserve full vehicle hierarchy",
            "make reference-matched service roads passenger-drivable",
            "audit dense topology and TLS clusters after build",
        ],
        "validation_gates": [
            "passenger_connectivity",
            "routeability_audit",
            "topology_audit",
            "reference_comparison",
            "netedit_launch",
        ],
    }


def derive_network_plan(
    *,
    user_request: str | None = None,
    highway_classes: str | set[str] | None = None,
    traffic_layers: str | Iterable[str] | None = None,
    network_profile: str | None = None,
    service_passenger_policy: str | None = None,
) -> dict[str, Any]:
    profile = _normalize_network_profile(network_profile) or _infer_reference_profile(user_request)
    if profile == "tum_ingolstadt":
        plan = _tum_ingolstadt_plan()
        if service_passenger_policy:
            plan["service_passenger_policy"] = service_passenger_policy
        return plan

    selected_highways = resolve_highway_classes(highway_classes, default_to_recommended=False)
    requested_layers = _as_tokens(traffic_layers)
    if selected_highways is not None:
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "network_plan_status": "confirmed",
            "network_profile": profile,
            "reference_target": "",
            "network_detail_target": "custom_road_scope",
            "movement_layers": sorted(requested_layers or {"passenger"}),
            "highway_classes": sorted(selected_highways),
            "service_passenger_policy": service_passenger_policy or "sumo_default",
            "cleanup_policy": ["use user-selected road classes"],
            "validation_gates": ["passenger_connectivity", "routeability_audit", "topology_audit", "netedit_launch"],
        }
    if requested_layers:
        inferred_highways = _highways_for_layers(requested_layers)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "network_plan_status": "inferred_from_traffic_layers",
            "network_profile": profile,
            "reference_target": "",
            "network_detail_target": "traffic_layer_selection",
            "movement_layers": sorted(requested_layers),
            "highway_classes": sorted(inferred_highways),
            "service_passenger_policy": service_passenger_policy
            or ("allow_vehicle_service" if requested_layers & {"service", "access", "passenger_plus_service"} else "sumo_default"),
            "cleanup_policy": ["derive OSM highway classes from requested traffic layers"],
            "validation_gates": ["passenger_connectivity", "routeability_audit", "topology_audit", "netedit_launch"],
        }
    return _blocked_plan()

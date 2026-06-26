from __future__ import annotations

from collections import Counter
from typing import Any

VEHICLE_CORE_TYPES = {
    "highway.primary",
    "highway.secondary",
    "highway.tertiary",
    "highway.unclassified",
    "highway.residential",
    "highway.living_street",
}
HARD_BLOCKER_ROLE_PRIORITY = ("rail", "ramp", "grade_separated", "roundabout")


def classify_edge_modal_role(edge: dict[str, Any]) -> dict[str, Any]:
    type_id = str(edge.get("type", "") or "")
    function = str(edge.get("function", "") or "")
    text = " ".join(
        str(edge.get(key, "") or "").lower()
        for key in ("id", "type", "function", "allow", "disallow", "name")
    )
    if type_id.startswith("railway."):
        return _role("rail", "never_join", "railway edge must not be joined into vehicle core", ["railway_present"])
    if type_id in {"highway.motorway", "highway.trunk"} or type_id.endswith("_link"):
        return _role(
            "ramp",
            "never_join",
            "motorway/trunk/link geometry uses ramp or interchange semantics",
            ["ramp_or_interchange"],
        )
    if any(token in text for token in ("bridge", "tunnel", "layer=")):
        return _role(
            "grade_separated",
            "never_join",
            "bridge/tunnel/layer evidence blocks same-level joining",
            ["grade_separation"],
        )
    if "roundabout" in text:
        return _role("roundabout", "never_join", "roundabout topology should be preserved", ["roundabout"])
    if function in {"crossing", "walkingarea"} or "footway" in type_id or "crossing" in type_id:
        return _role(
            "pedestrian",
            "shape_support",
            "pedestrian crossing/walkingarea supports review but not vehicle-core joining",
            ["pedestrian_support"],
        )
    if "cycleway" in type_id or "bicycle" in text:
        return _role(
            "bicycle",
            "shape_support",
            "bicycle infrastructure is support evidence unless map/reference includes it in the core",
            ["bicycle_support"],
        )
    if "service" in type_id or any(token in text for token in ("driveway", "parking_aisle", "parking", "private", "alley")):
        return _role(
            "service",
            "protected_terminal",
            "service or parking access is a protected terminal by default",
            ["service_terminal_present"],
        )
    if type_id in VEHICLE_CORE_TYPES or "passenger" in text:
        return _role("vehicle_core", "join_core", "ordinary passenger-drivable urban road", [])
    return _role("unknown", "review_required", "modal role is unknown from SUMO edge attributes", ["unknown_modal_role"])


def classify_cluster_modal_policy(
    *,
    internal_edges: list[dict[str, Any]],
    boundary_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    roles = [classify_edge_modal_role(edge) for edge in internal_edges + boundary_edges]
    decisions = Counter(role["modal_aggregation_decision"] for role in roles)
    primary_roles = Counter(role["modal_primary_role"] for role in roles)
    risk_flags = sorted({flag for role in roles for flag in role["modal_risk_flags"]})

    if decisions["never_join"]:
        decision = "never_join"
        reason = "hard modal blocker present"
    elif decisions["join_core"] and (decisions["protected_terminal"] or decisions["shape_support"]):
        decision = "review_required"
        reason = "vehicle core mixed with support or terminal infrastructure"
    elif decisions["join_core"]:
        decision = "join_core"
        reason = "modal context is compatible with vehicle-core joining"
    elif decisions["protected_terminal"]:
        decision = "protected_terminal"
        reason = "cluster is dominated by protected terminal infrastructure"
    elif decisions["shape_support"]:
        decision = "shape_support"
        reason = "cluster is modal support infrastructure, not a vehicle core"
    else:
        decision = "review_required"
        reason = "modal context is unknown or ambiguous"

    return {
        "modal_aggregation_decision": decision,
        "modal_primary_role": _cluster_primary_role(roles, decision, primary_roles),
        "modal_review_action": _review_action(decision, decisions),
        "modal_reason": reason,
        "modal_risk_flags": risk_flags,
        "modal_decision_counts": dict(decisions),
        "modal_role_counts": dict(primary_roles),
    }


def _role(primary: str, decision: str, reason: str, flags: list[str]) -> dict[str, Any]:
    return {
        "modal_primary_role": primary,
        "modal_aggregation_decision": decision,
        "modal_review_action": _review_action(decision, Counter({decision: 1})),
        "modal_reason": reason,
        "modal_risk_flags": flags,
    }


def _cluster_primary_role(roles: list[dict[str, Any]], decision: str, primary_roles: Counter[str]) -> str:
    if decision == "never_join":
        present = {role["modal_primary_role"] for role in roles if role["modal_aggregation_decision"] == "never_join"}
        for role_name in HARD_BLOCKER_ROLE_PRIORITY:
            if role_name in present:
                return role_name
    if decision == "review_required" and primary_roles["vehicle_core"]:
        return "vehicle_core"
    return primary_roles.most_common(1)[0][0] if primary_roles else "unknown"


def _review_action(decision: str, decisions: Counter[str]) -> str:
    if decision in {"never_join", "protected_terminal"}:
        return "exclude_from_join"
    if decision == "join_core":
        return "safe_vehicle_core_candidate"
    if decision == "shape_support":
        return "review_modal_support"
    if decisions["shape_support"] and not decisions["join_core"]:
        return "review_modal_support"
    return "review_vehicle_core_boundary"

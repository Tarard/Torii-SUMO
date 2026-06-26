from torii_sumo.core.modal_aggregation_policy import (
    classify_cluster_modal_policy,
    classify_edge_modal_role,
)


def test_ordinary_urban_vehicle_edges_are_join_core() -> None:
    edge = {"id": "e1", "type": "highway.tertiary", "allow": "passenger bus", "disallow": ""}
    role = classify_edge_modal_role(edge)
    assert role["modal_primary_role"] == "vehicle_core"
    assert role["modal_aggregation_decision"] == "join_core"


def test_service_driveway_is_protected_terminal() -> None:
    edge = {"id": "e1", "type": "highway.service", "name": "service=driveway"}
    role = classify_edge_modal_role(edge)
    assert role["modal_primary_role"] == "service"
    assert role["modal_aggregation_decision"] == "protected_terminal"


def test_railway_is_never_join() -> None:
    edge = {"id": "r1", "type": "railway.tram"}
    role = classify_edge_modal_role(edge)
    assert role["modal_primary_role"] == "rail"
    assert role["modal_aggregation_decision"] == "never_join"


def test_motorway_link_is_never_join_for_urban_aggregation() -> None:
    edge = {"id": "m1", "type": "highway.motorway_link"}
    role = classify_edge_modal_role(edge)
    assert role["modal_primary_role"] == "ramp"
    assert role["modal_aggregation_decision"] == "never_join"


def test_pedestrian_crossing_is_shape_support() -> None:
    edge = {"id": "c1", "function": "crossing", "type": "highway.crossing"}
    role = classify_edge_modal_role(edge)
    assert role["modal_primary_role"] == "pedestrian"
    assert role["modal_aggregation_decision"] == "shape_support"


def test_cluster_with_vehicle_core_and_service_terminal_requires_review() -> None:
    policy = classify_cluster_modal_policy(
        internal_edges=[{"id": "e1", "type": "highway.tertiary"}],
        boundary_edges=[
            {"id": "e2", "type": "highway.secondary"},
            {"id": "s1", "type": "highway.service", "name": "service=parking_aisle"},
        ],
    )
    assert policy["modal_aggregation_decision"] == "review_required"
    assert "service_terminal_present" in policy["modal_risk_flags"]

from __future__ import annotations

from dataclasses import fields
import inspect
from pathlib import Path
from typing import Any

import pytest

from torii_sumo.core.osm_workflow import run_osm_cleanup_workflow
from torii_sumo.core.osm_workflow_api import (
    OsmWorkflowServices,
    run_osm_cleanup_workflow_with_request,
)
from torii_sumo.core.osm_workflow_request import OsmWorkflowRequest, OsmWorkflowScope


def _legacy_parameters() -> dict[str, inspect.Parameter]:
    return dict(inspect.signature(run_osm_cleanup_workflow).parameters.items())


def _service_names() -> set[str]:
    return {field.name for field in fields(OsmWorkflowServices)}


def test_request_kwargs_cover_exactly_the_non_service_legacy_parameters() -> None:
    legacy = _legacy_parameters()
    service_names = _service_names()
    expected_names = set(legacy) - service_names
    output_dir = Path("unused-request-output")

    request = OsmWorkflowRequest(output_dir=output_dir)
    kwargs = request.to_legacy_kwargs()

    assert set(kwargs) == expected_names
    for name, parameter in legacy.items():
        if name in service_names:
            continue
        if name == "output_dir":
            assert kwargs[name] == output_dir
            continue
        assert parameter.default is not inspect.Parameter.empty
        assert kwargs[name] == parameter.default


def test_service_fields_cover_exactly_the_service_legacy_parameters() -> None:
    legacy = _legacy_parameters()
    service_names = _service_names()

    assert service_names <= set(legacy)
    for name in service_names:
        assert legacy[name].default is not inspect.Parameter.empty
    assert not (service_names & set(OsmWorkflowRequest(output_dir=Path(".")).to_legacy_kwargs()))


def test_default_services_are_taken_from_the_legacy_signature() -> None:
    legacy = _legacy_parameters()
    services = OsmWorkflowServices.default()

    for field in fields(services):
        assert getattr(services, field.name) is legacy[field.name].default

    assert services.to_kwargs() == {
        name: legacy[name].default for name in _service_names() if legacy[name].default is not None
    }


def _fake_place_resolver(place_name: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "claim_status": "blocked",
        "area_input": place_name,
        "area_resolution_status": "blocked",
        "warnings": ["injected resolver: no network access in test"],
    }


def test_request_api_matches_legacy_call_for_unconfirmed_place() -> None:
    output_dir = Path("unused-request-api-output")
    place_name = "__torii_test_place_without_network__"

    request = OsmWorkflowRequest(
        output_dir=output_dir,
        scope=OsmWorkflowScope(place_name=place_name),
    )
    legacy_result = run_osm_cleanup_workflow(
        output_dir=output_dir,
        place_name=place_name,
        place_resolver=_fake_place_resolver,
    )
    request_result = run_osm_cleanup_workflow_with_request(
        request,
        services=OsmWorkflowServices(place_resolver=_fake_place_resolver),
    )

    assert request_result == legacy_result
    assert request_result["claim_status"] == "blocked"
    assert "no network access" in request_result["warnings"][0]


def test_request_api_rejects_non_request_objects() -> None:
    with pytest.raises(TypeError, match="OsmWorkflowRequest"):
        run_osm_cleanup_workflow_with_request({})  # type: ignore[arg-type]

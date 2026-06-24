from __future__ import annotations

from pathlib import Path
from typing import Any

from torii_sumo.core.workflow_router import run_auto_workflow


def torii_auto_workflow(
    user_request: str,
    output_dir: str,
    work_dir: str | None = None,
    autonomy_mode: str = "safe-autopilot",
    place_name: str | None = None,
    bbox: str | None = None,
    confirmed_area: bool = False,
    highway_classes: str | None = None,
    traffic_layers: str | None = None,
    network_profile: str | None = None,
    reference_net_file: str | None = None,
    reference_policy_report: str | None = None,
    service_passenger_policy: str | None = None,
    net_file: str | None = None,
    osm_file: str | None = None,
    official_inventory_csv: str | None = None,
    signal_plan_csv: str | None = None,
    field_evidence_csv: str | None = None,
) -> dict[str, Any]:
    return run_auto_workflow(
        user_request=user_request,
        output_dir=Path(output_dir),
        work_dir=Path(work_dir) if work_dir else None,
        autonomy_mode=autonomy_mode,
        place_name=place_name,
        bbox=bbox,
        confirmed_area=confirmed_area,
        highway_classes=highway_classes,
        traffic_layers=traffic_layers,
        network_profile=network_profile,
        reference_net_file=Path(reference_net_file) if reference_net_file else None,
        reference_policy_report=reference_policy_report,
        service_passenger_policy=service_passenger_policy,
        net_file=Path(net_file) if net_file else None,
        osm_file=Path(osm_file) if osm_file else None,
        official_inventory_csv=Path(official_inventory_csv) if official_inventory_csv else None,
        signal_plan_csv=Path(signal_plan_csv) if signal_plan_csv else None,
        field_evidence_csv=Path(field_evidence_csv) if field_evidence_csv else None,
    )

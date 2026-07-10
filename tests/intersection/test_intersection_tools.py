import json
from pathlib import Path

from torii_sumo.tools import intersection_tools
from torii_sumo.tools.intersection_tools import (
    sumo_intersection_clean,
    sumo_intersection_model,
    sumo_intersection_scene_workflow,
    sumo_intersection_validate,
)


FIXTURES = Path(__file__).parent / "fixtures"


def test_sumo_intersection_model_returns_json_compatible_ir_summary(tmp_path: Path) -> None:
    report = sumo_intersection_model(str(FIXTURES / "t3_priority.osm.xml"), str(tmp_path))

    assert report["status"] == "pass"
    assert report["intersection_id"] == "core_1"
    assert report["approach_mode_counts"] == {"passenger": 3}
    assert report["vehicle_approach_count"] == 3
    assert report["vehicle_topology_type"] == "T3"
    assert report["legal_movement_mode_counts"] == {"passenger": 6}
    assert report["forbidden_cross_mode_movement_count"] == 0
    assert Path(report["intersection_ir_file"]).exists()
    json.dumps(report)


def test_sumo_intersection_model_reports_next_phase_fields(tmp_path: Path) -> None:
    result = sumo_intersection_model(str(FIXTURES / "x4_signalized.osm.xml"), str(tmp_path))

    assert result["restriction_warning_count"] == 0
    assert result["custom_tllogic_applied"] is None
    assert result["direction_blocked_approach_count"] == 0


def test_sumo_intersection_validate_reports_next_phase_fields(tmp_path: Path) -> None:
    clean_result = sumo_intersection_clean(
        str(FIXTURES / "x4_signalized.osm.xml"),
        str(tmp_path / "clean"),
        compile_net=False,
    )

    result = sumo_intersection_validate(clean_result["intersection_ir_file"], str(tmp_path / "validate"))

    assert result["restriction_warning_count"] == 0
    assert result["custom_tllogic_applied"] is True
    assert result["direction_blocked_approach_count"] == 0


def test_sumo_intersection_clean_wraps_clean_intersection(monkeypatch, tmp_path: Path) -> None:
    def fake_clean(**kwargs):
        assert kwargs["osm_file"] == FIXTURES / "t3_priority.osm.xml"
        assert kwargs["output_dir"] == tmp_path
        assert kwargs["seed"] is None
        assert kwargs["compile_net"] is False
        return {"status": "blocked", "intersection_id": "core_1"}

    monkeypatch.setattr(intersection_tools, "clean_intersection", fake_clean)

    report = sumo_intersection_clean(
        str(FIXTURES / "t3_priority.osm.xml"),
        str(tmp_path),
        compile_net=False,
    )

    assert report == {"status": "blocked", "intersection_id": "core_1"}


def test_sumo_intersection_scene_workflow_delegates_with_path_and_options(monkeypatch, tmp_path: Path) -> None:
    calls = {}

    def fake_workflow(prompt, output_dir, prefix, launch_netedit_after_build):
        calls.update(
            prompt=prompt,
            output_dir=output_dir,
            prefix=prefix,
            launch_netedit_after_build=launch_netedit_after_build,
        )
        return {"status": "pass"}

    monkeypatch.setattr(intersection_tools, "run_intersection_scene_workflow", fake_workflow)

    report = sumo_intersection_scene_workflow(
        "Make a four-way traffic-light intersection",
        str(tmp_path),
        prefix="demo",
        launch_netedit_after_build=True,
    )

    assert report == {"status": "pass"}
    assert calls == {
        "prompt": "Make a four-way traffic-light intersection",
        "output_dir": tmp_path,
        "prefix": "demo",
        "launch_netedit_after_build": True,
    }

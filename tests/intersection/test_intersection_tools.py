import json
from pathlib import Path

from torii_sumo.tools import intersection_tools
from torii_sumo.tools.intersection_tools import sumo_intersection_clean, sumo_intersection_model


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

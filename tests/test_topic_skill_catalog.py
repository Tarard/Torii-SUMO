from pathlib import Path

from torii_sumo.core.workflow_catalog import get_workflow_catalog


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "torii-sumo"
TOPIC_SKILLS = {"torii-build", "torii-calibrate", "torii-simulate", "torii-report"}


def test_workflow_catalog_points_to_bundled_topic_skills() -> None:
    catalog = get_workflow_catalog()
    assert catalog["status"] == "pass"
    for row in catalog["scenarios"]:
        assert row["skill"] in TOPIC_SKILLS
        assert row["reference"].startswith(f"skills/{row['skill']}/references/")
        assert (PLUGIN / row["reference"]).is_file()


def test_catalog_routes_product_stages_to_expected_skill() -> None:
    rows = {row["scenario_id"]: row for row in get_workflow_catalog()["scenarios"]}
    assert rows["osm_network"]["skill"] == "torii-build"
    assert rows["detector_calibration"]["skill"] == "torii-calibrate"
    assert rows["environment_preflight"]["skill"] == "torii-simulate"
    assert rows["run_comparison"]["skill"] == "torii-report"

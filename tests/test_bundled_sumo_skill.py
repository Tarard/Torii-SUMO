import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins" / "torii-sumo" / "skills"

EXPECTED_REFERENCES = {
    "torii-build": {
        "composable-intersection-classification.md",
        "composable-signal-device-classification.md",
        "hamburg-five-intersection-aerial-workflow.md",
        "hamburg-count-calibration-workflow.md",
        "model-osm-detectors.md",
        "osm-source-patterns.md",
        "osm-to-sumo-workflow.md",
        "osm-way-fragmentation-and-road-axis-reconstruction.md",
        "road-arm-and-connection-classification.md",
    },
    "torii-calibrate": {
        "cached-detector-demand.md",
        "detector-constrained-demand-reconstruction.md",
        "hamburg-count-calibration-workflow.md",
        "hamburg-five-intersection-aerial-workflow.md",
        "hamburg-sandtorkai-digital-twin.md",
    },
    "torii-simulate": {
        "audit-sumo-controllers.md",
        "compare-corridor-perturbations.md",
        "debug-sumo-traci.md",
        "develop-and-verify-code.md",
        "experiment-problem-solving.md",
        "interactive-experiment-intake.md",
        "learn-sumo-knowledge.md",
        "mcp-tool-routing.md",
        "plan-experiment.md",
        "preflight-sumo-environment.md",
        "route-project-workflow.md",
        "sumolights-controller-patterns.md",
    },
    "torii-report": {
        "capture-field-lesson.md",
        "evaluate-and-report-results.md",
        "release-project.md",
        "traffic-control-reporting.md",
    },
}


def skill_dir(name: str) -> Path:
    return SKILLS / name


def read_skill(name: str) -> str:
    return (skill_dir(name) / "SKILL.md").read_text(encoding="utf-8")


def test_plugin_bundles_four_topic_skills() -> None:
    actual = {path.name for path in SKILLS.iterdir() if path.is_dir() and (path / "SKILL.md").is_file()}
    assert actual == set(EXPECTED_REFERENCES)
    assert not (SKILLS / "simulation-helper-skill-for-eclipse-sumo").exists()


def test_each_skill_has_matching_frontmatter_and_agent_metadata() -> None:
    for name in EXPECTED_REFERENCES:
        body = read_skill(name)
        frontmatter = yaml.safe_load(body.split("---", 2)[1])
        assert frontmatter["name"] == name
        assert frontmatter["description"]

        agent = yaml.safe_load((skill_dir(name) / "agents" / "openai.yaml").read_text(encoding="utf-8"))
        assert agent["interface"]["display_name"]
        assert agent["interface"]["short_description"]
        assert f"${name}" in agent["interface"]["default_prompt"]
        assert agent["policy"]["allow_implicit_invocation"] is True


def test_topic_reference_sets_are_present() -> None:
    for name, expected in EXPECTED_REFERENCES.items():
        bundled = {path.name for path in (skill_dir(name) / "references").glob("*.md")}
        assert bundled == expected


def test_each_skill_routes_only_to_local_reference_files() -> None:
    for name in EXPECTED_REFERENCES:
        body = read_skill(name)
        routed = set(re.findall(r"`references/([^`]+\.md)`", body))
        missing = sorted(ref for ref in routed if not (skill_dir(name) / "references" / ref).is_file())
        assert missing == []


def test_product_boundaries_are_explicit() -> None:
    build = read_skill("torii-build")
    calibrate = read_skill("torii-calibrate")
    simulate = read_skill("torii-simulate")
    report = read_skill("torii-report")

    assert "$torii-calibrate" in build
    assert "$torii-build" in calibrate
    assert "$torii-report" in simulate
    assert "$torii-simulate" in report
    assert "Do not rerun experiments unless the user explicitly asks" in report


def test_reporting_reference_preserves_traffic_evidence_contract() -> None:
    body = (skill_dir("torii-report") / "references" / "traffic-control-reporting.md").read_text(encoding="utf-8")
    for term in (
        "network and demand",
        "Controller Information Contract",
        "TraCI` is an interface, not a sensor model",
        "minimum and maximum green",
        "unfinished-vehicle treatment",
        "algorithm benefit from information benefit",
        "simulator truth",
    ):
        assert term in body


def test_debugging_and_experiment_diagnosis_live_in_simulate() -> None:
    refs = skill_dir("torii-simulate") / "references"
    debug = (refs / "debug-sumo-traci.md").read_text(encoding="utf-8")
    diagnosis = (refs / "experiment-problem-solving.md").read_text(encoding="utf-8")
    assert "environment-fault" in debug
    assert "controller-logic-fault" in debug
    assert "blocking_uncertainty" in diagnosis
    assert "smallest_next_step" in diagnosis


def test_release_reference_matches_current_bundle_and_license() -> None:
    body = (skill_dir("torii-report") / "references" / "release-project.md").read_text(encoding="utf-8")
    assert "MIT License" in body
    for name in EXPECTED_REFERENCES:
        assert f"`{name}`" in body
    assert "PolyForm" not in body
    assert "main bundled skill name remains" not in body

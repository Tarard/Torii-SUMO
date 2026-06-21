import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins" / "torii-sumo" / "skills" / "simulation-helper-skill-for-eclipse-sumo"


EXISTING_PUBLIC_REFERENCES = {
    "audit-sumo-controllers.md",
    "capture-field-lesson.md",
    "compare-corridor-perturbations.md",
    "develop-and-verify-code.md",
    "evaluate-and-report-results.md",
    "interactive-experiment-intake.md",
    "learn-sumo-knowledge.md",
    "model-osm-detectors.md",
    "osm-source-patterns.md",
    "plan-experiment.md",
    "preflight-sumo-environment.md",
    "release-project.md",
    "route-project-workflow.md",
}


def read_skill() -> str:
    return (SKILL / "SKILL.md").read_text(encoding="utf-8")


def read_openai_agent() -> dict:
    return yaml.safe_load((SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8"))


def test_public_skill_files_are_bundled() -> None:
    assert (SKILL / "SKILL.md").is_file()
    assert (SKILL / "agents" / "openai.yaml").is_file()

    bundled = {path.name for path in (SKILL / "references").glob("*.md")}
    assert EXISTING_PUBLIC_REFERENCES <= bundled


def test_skill_routes_only_to_existing_reference_files() -> None:
    body = read_skill()
    routed = set(re.findall(r"`references/([^`]+\.md)`", body))

    missing = sorted(ref for ref in routed if not (SKILL / "references" / ref).is_file())
    assert missing == []


def test_openai_agent_exposes_required_fields() -> None:
    agent = read_openai_agent()

    assert agent["interface"]["display_name"]
    assert agent["interface"]["short_description"]
    assert "$simulation-helper-skill-for-eclipse-sumo" in agent["interface"]["default_prompt"]
    assert agent["policy"]["allow_implicit_invocation"] is True


def test_skill_bundle_has_no_external_debugging_skill_route() -> None:
    needles = {
        "debugging-helper-skill-for-eclipse-sumo",
        "debugging helper",
    }
    hits = {
        (path.relative_to(SKILL).as_posix(), needle)
        for path in SKILL.rglob("*")
        for needle in needles
        if path.is_file() and needle in path.read_text(encoding="utf-8")
    }

    assert hits == set()


def test_release_project_documents_plugin_bundle_boundary() -> None:
    body = (SKILL / "references" / "release-project.md").read_text(encoding="utf-8")

    assert "Bundle Context" in body
    assert "plugin bundle" in body
    assert "standalone public skill repository" in body


def test_skill_preserves_claim_boundary_language() -> None:
    body = read_skill()

    assert "formal-evidence" in body
    assert "diagnostic-demo" in body
    assert "construction-invalid" in body
    assert "Compare controllers only with paired route" in body


def test_skill_routes_mcp_tools_and_feedback_diagnosis() -> None:
    body = read_skill()
    reference = (SKILL / "references" / "mcp-tool-routing.md").read_text(encoding="utf-8")

    assert "references/mcp-tool-routing.md" in body
    assert "MCP Tool Use Record" in body
    assert "feedback signals" in body
    assert "sumo_preflight" in reference
    assert "sumo_compare_outputs" in reference
    assert "sumo_osm_resolve_place" in reference
    assert "sumo_network_routeability_audit" in reference
    assert "MCP tool output is observation" in reference
    assert "diagnose what the metric implies" in reference


def test_skill_routes_sumolights_controller_patterns_without_source_copy() -> None:
    body = read_skill()
    reference = (SKILL / "references" / "sumolights-controller-patterns.md").read_text(encoding="utf-8")

    assert "references/sumolights-controller-patterns.md" in body
    assert "Controller Application Plan" in body
    assert "Controller Identity Record" in reference
    assert "max-pressure" in reference
    assert "Webster" in reference
    assert "SOTL" in reference
    assert "Do not copy GPL-3.0 source code" in reference
    assert "implementation-pattern evidence only" in reference
    assert "unsupported by existing MCP tools" in reference
    assert "create a code-development plan instead of pretending the controller was applied" in reference


def test_skill_routes_osm_source_patterns_and_google_maps_temporal_baseline() -> None:
    body = read_skill()
    model_reference = (SKILL / "references" / "model-osm-detectors.md").read_text(encoding="utf-8")
    source_reference = (SKILL / "references" / "osm-source-patterns.md").read_text(encoding="utf-8")

    assert "references/osm-source-patterns.md" in body
    assert "sumo_osm_cleanup_workflow" in model_reference
    assert "area confirmation" in model_reference
    assert "Netedit" in model_reference
    assert "SUMO-GUI" in model_reference
    assert "user's stated historical target controls the baseline" in model_reference
    assert "Google Maps is the external reality baseline" in model_reference
    assert "current map or a historical target date" in model_reference
    assert "map_temporal_scope" in model_reference
    assert "OSMnx" in source_reference
    assert "OSMNet" in source_reference
    assert "pyrosm" in source_reference
    assert "SUMO osmGet/osmBuild" in source_reference
    assert "osm-to-xodr" in source_reference
    assert "Do not vendor external source code" in source_reference

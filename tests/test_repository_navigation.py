from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _registered_tool_names() -> set[str]:
    server_path = ROOT / "plugins" / "torii-sumo" / "src" / "torii_sumo" / "server.py"
    tree = ast.parse(server_path.read_text(encoding="utf-8"))
    names: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Call):
            continue
        registration = node.func
        if not isinstance(registration.func, ast.Attribute) or registration.func.attr != "tool":
            continue
        if node.args and isinstance(node.args[0], ast.Name):
            names.add(node.args[0].id)

    return names


def test_readme_exposes_stable_navigation() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    expected_links = {
        "docs/README.md",
        "docs/repository-guide.md",
        "docs/mcp-tool-catalog.md",
        "ARCHITECTURE.md",
    }
    for link in expected_links:
        assert link in readme

    original_section_order = (
        "## Evidence-Aware OSM-to-SUMO Construction",
        "## Example",
        "## Quick Start",
        "## What You Can Ask Me",
        "## Boundaries",
        "## License and Notices",
    )
    positions = [readme.index(heading) for heading in original_section_order]
    assert positions == sorted(positions)


def test_documentation_index_links_core_guides() -> None:
    docs_index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")

    for link in (
        "repository-guide.md",
        "mcp-tool-catalog.md",
        "research-paper-blueprint.md",
        "../ARCHITECTURE.md",
        "codex-plugin-install.md",
    ):
        assert link in docs_index


def test_mcp_catalog_covers_every_registered_tool() -> None:
    catalog = (ROOT / "docs" / "mcp-tool-catalog.md").read_text(encoding="utf-8")
    registered = _registered_tool_names()

    assert len(registered) == 73
    missing = sorted(name for name in registered if f"`{name}`" not in catalog)
    assert missing == []


def test_repository_guide_defines_primary_code_boundaries() -> None:
    guide = (ROOT / "docs" / "repository-guide.md").read_text(encoding="utf-8")

    for path in (
        "plugins/torii-sumo/skills/",
        "src/torii_sumo/tools/",
        "src/torii_sumo/core/",
        "plugins/torii-sumo/scripts/",
        "schemas/",
        "examples/",
        "benchmarks/",
        "tests/",
    ):
        assert f"`{path}`" in guide


def test_agent_instructions_preserve_repository_and_evidence_boundaries() -> None:
    instructions = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for required in (
        "docs/repository-guide.md",
        "docs/mcp-tool-catalog.md",
        "src/torii_sumo/tools/",
        "src/torii_sumo/core/",
        "source artifacts immutable",
        "review_required",
        "tests/test_repository_navigation.py",
    ):
        assert required in instructions

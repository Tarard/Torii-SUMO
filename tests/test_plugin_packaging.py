import json
from pathlib import Path
from typing import Any
import re


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "torii-sumo"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_repo_marketplace_points_to_plugin_directory() -> None:
    marketplace = load_json(ROOT / ".agents" / "plugins" / "marketplace.json")

    assert marketplace == {
        "name": "torii-sumo",
        "interface": {
            "displayName": "Torii",
        },
        "plugins": [
            {
                "name": "torii-sumo",
                "source": {
                    "source": "local",
                    "path": "./plugins/torii-sumo",
                },
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Developer Tools",
            }
        ],
    }


def test_plugin_manifest_declares_skill_and_mcp_companion() -> None:
    manifest = load_json(PLUGIN / ".codex-plugin" / "plugin.json")

    assert manifest["name"] == "torii-sumo"
    assert re.fullmatch(r"1\.1\.0(?:\+codex\.\d{14})?", manifest["version"])
    assert manifest["license"] == "Apache-2.0"
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert manifest["author"]["name"] == "Torii contributors"
    assert manifest["interface"]["displayName"] == "Torii"
    assert manifest["interface"]["category"] == "Developer Tools"
    assert "SUMO" in manifest["interface"]["defaultPrompt"]


def test_plugin_manifest_uses_app_logo_for_codex_icon() -> None:
    manifest = load_json(PLUGIN / ".codex-plugin" / "plugin.json")
    logo_path = PLUGIN / "assets" / "app-logo.png"
    docs_logo_path = ROOT / "docs" / "assets" / "app-logo.png"

    assert manifest["interface"]["composerIcon"] == "./assets/app-logo.png"
    assert manifest["interface"]["logo"] == "./assets/app-logo.png"
    assert logo_path.is_file()
    assert logo_path.read_bytes() == docs_logo_path.read_bytes()


def test_mcp_config_uses_bundled_launcher() -> None:
    mcp_config = load_json(PLUGIN / ".mcp.json")

    assert mcp_config == {
        "mcpServers": {
            "torii-sumo": {
                "command": "python",
                "args": ["./scripts/run_torii_sumo.py"],
            }
        }
    }


def test_plugin_contains_bundled_launcher() -> None:
    assert (PLUGIN / "scripts" / "run_torii_sumo.py").is_file()


def test_plugin_contains_bundled_mcp_package() -> None:
    assert (PLUGIN / "src" / "torii_sumo" / "server.py").is_file()


def test_mcp_package_is_not_installed_at_repo_root() -> None:
    assert not (ROOT / "src" / "torii_sumo").exists()


def test_release_metadata_matches_repository_apache_license() -> None:
    plugin = load_json(PLUGIN / ".codex-plugin" / "plugin.json")
    zenodo = load_json(ROOT / ".zenodo.json")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")

    assert plugin["license"] == "Apache-2.0"
    assert zenodo["license"] == "Apache-2.0"
    assert 'license = { text = "Apache-2.0" }' in pyproject
    assert 'license: "Apache-2.0"' in citation
    assert 'version: "1.1.0"' in citation
    assert "Apache License" in license_text
    assert "Version 2.0" in license_text


def test_temporary_repository_export_workflow_is_removed() -> None:
    assert not (ROOT / ".github" / "workflows" / "codex-export-snapshot.yml").exists()
    assert (ROOT / ".github" / "workflows" / "workflow-contracts.yml").is_file()

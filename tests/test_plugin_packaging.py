import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "torii-sumo"
CODE_LICENSE = "PolyForm-Noncommercial-1.0.0"
DOCS_LICENSE = "CC-BY-NC-4.0"
PACKAGE_LICENSE = f"{CODE_LICENSE} AND {DOCS_LICENSE}"


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
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert re.fullmatch(re.escape(version) + r"(?:\+codex\.\d{14})?", manifest["version"])
    assert manifest["license"] == PACKAGE_LICENSE
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


def test_mcp_config_uses_locked_plugin_launcher() -> None:
    mcp_config = load_json(PLUGIN / ".mcp.json")

    assert mcp_config == {
        "mcpServers": {
            "torii-sumo": {
                "command": "uv",
                "args": [
                    "run",
                    "--isolated",
                    "--frozen",
                    "--script",
                    "./scripts/run_torii_sumo.py",
                ],
            }
        }
    }


def test_plugin_contains_bundled_launcher() -> None:
    assert (PLUGIN / "scripts" / "run_torii_sumo.py").is_file()
    assert (PLUGIN / "scripts" / "run_torii_sumo.py.lock").is_file()
    assert (PLUGIN / "scripts" / "bootstrap_mcp.py").is_file()


def test_mcp_bootstrap_check_reports_usable_start_path() -> None:
    result = subprocess.run(
        [sys.executable, str(PLUGIN / "scripts" / "bootstrap_mcp.py"), "--check"],
        check=False,
        cwd=PLUGIN,
    )

    assert result.returncode == 0


def test_plugin_contains_bundled_mcp_package() -> None:
    assert (PLUGIN / "src" / "torii_sumo" / "server.py").is_file()


def test_supported_platform_and_product_test_runners_are_windows_only() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert "Operating System :: Microsoft :: Windows" in project["classifiers"]
    for name in ("full-suite.yml", "corridor-contracts.yml"):
        workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))
        assert all(job["runs-on"].startswith("windows-") for job in workflow["jobs"].values())


def test_mcp_package_is_not_installed_at_repo_root() -> None:
    assert not (ROOT / "src" / "torii_sumo").exists()


def test_repository_license_scope_is_consistent() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    zenodo = load_json(ROOT / ".zenodo.json")
    manifest = load_json(PLUGIN / ".codex-plugin" / "plugin.json")

    assert project["license"] == PACKAGE_LICENSE
    assert project["license-files"] == ["LICENSE", "LICENSE-CODE", "LICENSE-DOCS", "NOTICE.md"]
    assert citation["license"] == CODE_LICENSE
    assert zenodo["license"] == "polyform-noncommercial-1.0.0"
    assert manifest["license"] == PACKAGE_LICENSE

    assert hashlib.sha256((ROOT / "LICENSE-CODE").read_bytes()).hexdigest() == (
        "ffcca38841adb694b6f380647e15f17c446a4d1656fed51a1e2041d064c94cc8"
    )
    assert hashlib.sha256((ROOT / "LICENSE-DOCS").read_bytes()).hexdigest() == (
        "3711f963c05d0be80d53e5923308a6dee31b203da23435c9cfb7c7b6e4dd5e19"
    )

    scope = (ROOT / "LICENSE").read_text(encoding="utf-8")
    scope_words = " ".join(scope.split())
    assert CODE_LICENSE in scope
    assert DOCS_LICENSE in scope
    assert "not dual-licensed" in scope_words
    assert "does not revoke licenses already granted for earlier versions" in scope_words
    assert "Apache License" not in scope

    for readme_name in ("README.md", "README.zh-CN.md", "README.de.md"):
        readme = (ROOT / readme_name).read_text(encoding="utf-8")
        assert "LICENSE-CODE" in readme
        assert "LICENSE-DOCS" in readme

    notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
    public_manifest = (ROOT / "docs" / "release" / "public-repo-manifest.md").read_text(encoding="utf-8")
    assert "do not grant trademark rights" in notice
    assert "LICENSE-CODE" in public_manifest
    assert "LICENSE-DOCS" in public_manifest

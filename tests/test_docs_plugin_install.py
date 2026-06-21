from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_links_plugin_install_doc() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Codex Plugin Installation" in readme
    assert "docs/codex-plugin-install.md" in readme
    assert "skills and MCP tools" in readme
    assert "docs/superpowers/specs/2026-06-20-torii-sumo-design.md" not in readme
    assert "docs/superpowers/plans/2026-06-20-torii-sumo.md" not in readme


def test_plugin_install_doc_explains_marketplace_and_new_thread() -> None:
    doc = (ROOT / "docs" / "codex-plugin-install.md").read_text(encoding="utf-8")

    assert "codex plugin marketplace add" in doc
    assert "codex plugin marketplace add Tarard/Torii-SUMO --ref main" in doc
    assert "codex plugin add torii-sumo@torii-sumo" in doc
    assert "Start a new Codex thread" in doc
    assert "plugins/torii-sumo" in doc
    assert "plugins/torii-sumo/.codex-plugin/plugin.json" in doc
    assert "skill is the reasoning layer" in doc
    assert "MCP server is the execution layer" in doc
    assert "torii_auto_workflow" in doc
    assert "workflow router" in doc
    assert "sumo_osm_cleanup_workflow" in doc
    assert "area confirmation" in doc
    assert "Netedit" in doc
    assert "sumo_osm_build_network" in doc
    assert "sumo_tls_audit" in doc
    assert "sumo_tls_multisource_review" in doc
    assert "Mapillary" in doc
    assert "KartaView" in doc
    assert "sumo_network_connected_core" in doc
    assert "sumo_network_routeability_probe" in doc
    assert "tiled Overpass" in doc
    assert "retry" in doc
    assert "deduplicate" in doc
    assert "OSMnx" in doc
    assert "OSMNet" in doc
    assert "pyrosm" in doc
    assert "SUMO osmGet/osmBuild" in doc
    assert "osm-to-xodr" in doc
    assert "Google Maps is the required workflow baseline" in doc
    assert "do not remove the Google Maps gate" in doc
    assert "current map or a historical target date" in doc
    assert "full OSM intelligent cleanup" in doc
    assert "TLS inventory" in doc
    assert "max-pressure controller generation" in doc
    assert "controller-log inspection" in doc


def test_osm_source_patterns_doc_tracks_external_projects_without_vendoring() -> None:
    doc = (ROOT / "docs" / "osm-source-patterns.md").read_text(encoding="utf-8")

    assert "OSMnx" in doc
    assert "OSMNet" in doc
    assert "pyrosm" in doc
    assert "SUMO osmGet/osmBuild" in doc
    assert "osm-to-xodr" in doc
    assert "Do not vendor external source code" in doc
    assert "Overpass subdivision" in doc
    assert "offline PBF" in doc
    assert "multi-stage netconvert" in doc


def test_internal_superpowers_plans_are_not_public_release_content() -> None:
    public_files = [
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        ROOT / "README.de.md",
        ROOT / "docs" / "index.html",
        ROOT / "docs" / "release" / "mailing-list-announcement.md",
        ROOT / "docs" / "release" / "linkedin-posts.md",
    ]

    for path in public_files:
        body = path.read_text(encoding="utf-8")
        assert "docs/superpowers" not in body
        assert "superpowers/plans" not in body
        assert "superpowers/specs" not in body

    manifest = (ROOT / "docs" / "release" / "public-repo-manifest.md").read_text(encoding="utf-8")
    assert "docs/superpowers/" in manifest
    assert "docs/superpowers/plans/" not in manifest
    assert "docs/superpowers/specs/" not in manifest

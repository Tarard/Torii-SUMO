# Public Repository Manifest

Use this manifest for the public Torii repository hosted at:

```text
Tarard/Torii-SUMO
```

The repository keeps the original starred URL while presenting the product as:

```text
Torii: Task-Oriented Road Infrastructure Intelligence
Agent plugin for SUMO
```

## Include

```text
README.md
README.zh-CN.md
README.de.md
ARCHITECTURE.md
LICENSE
LICENSE-CODE
LICENSE-DOCS
NOTICE.md
CITATION.cff
.zenodo.json
pyproject.toml
.agents/plugins/marketplace.json
.github/
plugins/
  torii-sumo/
skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
  sumo-experiment-problem-solving/
docs/
  index.html
  assets/
  codex-plugin-install.md
  mcp-host-config.md
  osm-source-patterns.md
  skill-integration.md
  common-sumo-signal-control-failures.md
  release/
examples/
benchmarks/
tests/
```

## Exclude

```text
docs/superpowers/
runs/
outputs/
sumo/
*.pdf
__pycache__/
*.pyc
.pytest_cache/
local datasets
private experiment logs
unpublished research notes
machine-local absolute paths
```

## Public Safety Checks

- No local machine paths.
- No private project acronyms, collaborator names, unpublished methods, or dataset identifiers.
- No vendored third-party source from OSMnx, OSMNet, pyrosm, SUMO, osm-to-xodr, SUMO Lights, or Google Maps.
- No claim that Google Maps is always the correct target; current versus historical map scope must be confirmed by the user.
- Full OSM cleanup is CLI-only. MCP does not expose it as a tool. Place resolution must produce a bbox before cleanup.

## GitHub Topics

After publishing, add the topics listed in `docs/release/github-topics.txt` through repository settings or GitHub CLI.

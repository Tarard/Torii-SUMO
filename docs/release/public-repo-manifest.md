# Public Repository Manifest

Use this manifest to create a clean GitHub repository named:

```text
Simulation-Helper-Skill-for-Eclipse-SUMO
```

Do not publish the entire local worktree if it contains unrelated project code, private plans, local PDFs, generated outputs, or unpublished research notes.

## Include

```text
README.md
README.zh-CN.md
README.de.md
LICENSE-DOCS
CITATION.cff
.zenodo.json
.github/
  workflows/
    create-release.yml
skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
docs/
  index.html
  assets/
    app-logo.png
    banner.png
    README.md
  common-sumo-signal-control-failures.md
  release/
    github-topics.txt
    mailing-list-announcement.md
    linkedin-posts.md
    conference-positioning.md
    public-repo-manifest.md
examples/
  01_fixed_time_audit/
  02_max_pressure_audit/
  03_data_informed_signal_control_audit/
```

## Exclude

```text
docs/superpowers/
src/
tests/
sumo/
outputs/
*.pdf
__pycache__/
*.pyc
```

## GitHub Topics

After creating the GitHub repository, add the topics listed in `docs/release/github-topics.txt` through the repository settings or GitHub CLI.

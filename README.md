<p align="right">
  <a href="README.md"><img src="https://img.shields.io/badge/lang-English-blue" alt="English"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/lang-%E4%B8%AD%E6%96%87-red" alt="中文"></a>
  <a href="README.de.md"><img src="https://img.shields.io/badge/lang-Deutsch-green" alt="Deutsch"></a>
</p>

# Simulation Helper Skill for Eclipse SUMO

Website: [tarard.github.io/Simulation-Helper-Skill-for-Eclipse-SUMO](https://tarard.github.io/Simulation-Helper-Skill-for-Eclipse-SUMO/)

**Agent Skill for Traffic Signal Control Experiments**

Reusable Codex/Claude skills and checklists for auditing SUMO/TraCI traffic signal control experiments before results are reported.

```text
What it is:     A reusable agent skill for auditing SUMO/TraCI signal-control workflows.
Who it is for:  Researchers using Eclipse SUMO for fixed-time, actuated, max-pressure, data-informed, or MPC-style controllers.
How it works:   It uses a scenario-based workflow router, then distills official SUMO documentation, community troubleshooting, public traffic-simulation code patterns, and practical experiment experience into focused audit paths.
What it catches: Broken routes, unsafe TLS phases, unpaired baselines, overwritten outputs, invalid metrics, and unreproducible batches.
```

This repository is built as a practical research tool, not as a paper wrapper. Copy the skill into Codex or Claude, point it at a SUMO experiment, and use the audit report to decide what can be claimed.

## Quick Start

For Codex, copy the skill folders to a repository-scoped skill directory:

```text
.agents/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

For Claude Code, copy the same folders to:

```text
.claude/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

Then call the skill from the agent:

```text
Use $simulation-helper-skill-for-eclipse-sumo to audit this SUMO/TraCI traffic signal control experiment before I report results.
```

For failures:

```text
Use $debugging-helper-skill-for-eclipse-sumo to diagnose why this SUMO/TraCI run is invalid or unreproducible.
```

The skill should ask for missing experiment details first. It should not endorse results just because SUMO ran without crashing.

## Project Status

Current version: instruction-only skill and checklist package.

This repository currently contains Markdown-based agent skills, audit checklists, examples, and release materials. It does not yet provide executable SUMO validators or Python audit scripts.

## Current Scope

The current release focuses on SUMO/TraCI traffic signal control experiments. It is not yet a general-purpose audit skill for every Eclipse SUMO use case.

This version covers fixed-time, actuated, max-pressure, NEMA, data-informed, and MPC-style signal control workflows. Future skills may add audit support for other SUMO domains, such as demand and routing, emissions and energy, public transport, pedestrian and intermodal scenarios, AV/CAV and co-simulation workflows, calibration, safety analysis, and mesoscopic or microscopic simulation-mode comparisons.

## Skill Catalog

| Skill | Use scenario | Use it for | Main outputs |
|---|---|---|---|
| `simulation-helper-skill-for-eclipse-sumo` | New experiment, ongoing project screen, code change, result audit, claim review, release check. | Planning, reviewing, comparing, or writing claims from SUMO/TraCI signal-control experiments. | Project Control Screen, Experiment Readiness Record, SUMO Experiment Plan, hard-gate audit, evidence class, claim boundary. |
| `debugging-helper-skill-for-eclipse-sumo` | Runtime failure, invalid route, TraCI protocol issue, missing output, seed/completion/reproducibility failure. | Debugging route, TraCI, TLS, demand, detector, output, seed, completion, and reproducibility failures. | Fault class, next diagnostic probe, evidence, fix or demotion rule. |

Both skills are plain `SKILL.md` packages with YAML frontmatter and Markdown references. The `agents/openai.yaml` files provide optional Codex UI metadata; the core skill instructions remain readable by Claude-style skill loaders that use `SKILL.md`.

Reference modules included in the package:

**Simulation helper references**

- [`workflow-router.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/workflow-router.md) - top-level scenario router for deciding which reference to load first.
- [`project-control-screen.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/project-control-screen.md) - ongoing-project target, state, deviation, and next-step screen.
- [`experiment-intake-interview.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-intake-interview.md) - Socratic pre-run questions and Experiment Readiness Record.
- [`experiment-planning-after-intake.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-planning-after-intake.md) - confirmed post-intake SUMO Experiment Plan before code, simulation, or claims.
- [`tdd-for-sumo-traci-code.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/tdd-for-sumo-traci-code.md) - RED -> GREEN -> REFACTOR workflow for SUMO/TraCI controller, parser, runner, and audit code.
- [`verification-and-review-gates.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/verification-and-review-gates.md) - evidence-before-completion, code-review, and artifact-isolation gates.
- [`source-ladder.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/source-ladder.md) - source priority and evidence hierarchy.
- [`sumo-official-semantics.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-official-semantics.md) - SUMO network, route, TLS, detector, and TraCI semantics.
- [`sumo-official-operational-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-official-operational-lessons.md) - operational lessons from official SUMO documentation.
- [`sumo-community-faq-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-community-faq-lessons.md) - common forum, FAQ, and community troubleshooting lessons.
- [`sumo-nema-controller-audit.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-nema-controller-audit.md) - NEMA ring, barrier, split, recall, detector, and claim checks.
- [`sumo-traci-controller-boundaries.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-traci-controller-boundaries.md) - TraCI controller identity and API-boundary checks.
- [`sumo-output-hard-gates.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-output-hard-gates.md) - output, warning, teleport, and artifact hard gates.
- [`evaluation-metrics-and-completion.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/evaluation-metrics-and-completion.md) - metric definitions and completion-aware reporting.
- [`baseline-and-ablation-design.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/baseline-and-ablation-design.md) - paired baseline, ablation, and sensitivity design.
- [`experiment-validation-ladder.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-validation-ladder.md) - validation ladder for experiments and debugging fixes.
- [`field-lesson-capture.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/field-lesson-capture.md) - privacy-safe capture of user-discovered fixes and reusable diagnostic paths.
- [`claim-boundary-taxonomy.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/claim-boundary-taxonomy.md) - wording rules for evidence-bounded claims.
- [`public-code-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/public-code-lessons.md) - lessons distilled from public traffic-simulation code.
- [`public-release-checklist.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/public-release-checklist.md) - release, trademark, privacy, and exposure checks.

**Debugging audit references**

- [`closed-loop-debugging.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/closed-loop-debugging.md) - observe, classify, probe, compare, update.
- [`symptom-to-evidence-map.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/symptom-to-evidence-map.md) - maps common symptoms to required evidence.
- [`debugging-gates-and-claim-boundaries.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/debugging-gates-and-claim-boundaries.md) - demotion rules for failed or partially fixed runs.

## How to Use in Practice

| Scenario | Example prompt | Skill/reference path | Expected output |
|---|---|---|---|
| Ongoing project, unclear next step | "Use this skill on my current SUMO project and tell me what to do next." | `simulation-helper` -> `workflow-router.md` -> `project-control-screen.md` -> narrow gate as needed | Project Control Screen and Next Step Plan. |
| New experiment design | "Help me design a SUMO/TraCI signal-control experiment." | `simulation-helper` -> `experiment-intake-interview.md` -> `experiment-planning-after-intake.md` | Experiment Readiness Record, then confirmed SUMO Experiment Plan. |
| Controller or parser code change | "Implement this TraCI metric parser/controller change." | `simulation-helper` -> `tdd-for-sumo-traci-code.md` -> `verification-and-review-gates.md` | RED/GREEN/REFACTOR record and verification evidence. |
| SUMO run failed or behaves oddly | "My route loads but tripinfo is empty / TraCI connection closes." | `debugging-helper` -> `closed-loop-debugging.md` -> `symptom-to-evidence-map.md` | Fault class, next probe, evidence, fix or demotion. |
| Results ready for reporting | "Can I claim controller A is better from these outputs?" | `simulation-helper` -> `sumo-output-hard-gates.md` -> `evaluation-metrics-and-completion.md` -> `baseline-and-ablation-design.md` -> `claim-boundary-taxonomy.md` | Evidence class and allowed/prohibited claim wording. |
| User found a missed fix | "The skill missed this; I later solved it another way." | `simulation-helper` -> `field-lesson-capture.md` | Field Lesson Candidate and privacy-safe patch proposal. |
| Public release work | "Check the GitHub repo before release." | `simulation-helper` -> `public-release-checklist.md` -> `verification-and-review-gates.md` | Release checklist, missing items, residual risk. |

## What It Audits

- TLS phase and movement-green consistency.
- Confirmed pre-run SUMO Experiment Plan after Socratic intake.
- Route, config, additional-file, detector, and network consistency.
- Fixed-time, actuated, max-pressure, NEMA, data-informed, and MPC-style controller comparisons.
- Paired seeds, paired demand, paired output intervals, and paired simulation horizons.
- `tripinfo`, `summary`, `edgeData`, TLS switch output, controller logs, warnings, teleports, and unfinished vehicles.
- Completion-aware metric reporting when simulations stop before all vehicles leave the network.
- Baselines, ablations, sensitivity runs, and claim wording.
- Test-driven SUMO/TraCI code changes for controllers, metric parsers, route/config generators, validators, and batch runners.
- Completion evidence and code-review gates before implementation, experiment, comparison, or release claims.
- Field lesson capture when a user solves a missed SUMO/TraCI issue and wants the reusable diagnostic path abstracted back into the skill.

## Examples

Each example is designed to be copied into an agent prompt:

```text
examples/
  01_fixed_time_audit/
    task.md
    expected_audit_report.md
    bad_case/
    fixed_case/
  02_max_pressure_audit/
    task.md
    expected_audit_report.md
    bad_case/
    fixed_case/
  03_data_informed_signal_control_audit/
    task.md
    expected_audit_report.md
    bad_case/
    fixed_case/
```

Start with `task.md`, then compare the agent's output against `expected_audit_report.md`.

## Common Failure Checklist

See `docs/common-sumo-signal-control-failures.md` for a longer checklist. It covers failures such as:

1. SUMO runs but `tripinfo.xml` is empty.
2. TLS phase index does not match the intended movement.
3. Max-pressure controller compares unpaired seeds.
4. `edgeData` interval differs across controllers.
5. Data-informed weights leak future outcome information.
6. Route files silently change demand across baselines.
7. Yellow and all-red handling differs across methods.
8. Simulation stops before demand completes.
9. Controller runtime or fallback behavior is missing.

## How the Skills Are Designed

The design follows seven principles:

**Progressive disclosure.** `SKILL.md` stays compact and routes the agent to focused reference files only when needed.

**Socratic intake and planning before execution.** For underspecified experiments, the skill asks targeted questions, builds an Experiment Readiness Record, then produces a confirmed SUMO Experiment Plan before code, SUMO runs, or claims.

**TDD before experiment code.** For controller, parser, runner, validator, and audit-script changes, the skill uses RED -> GREEN -> REFACTOR so code behavior is specified by a failing test or reproducible probe before implementation.

**Hard gates before claims.** The audit separates what SUMO loaded, what the controller did, what outputs were written, what warnings occurred, and what claim the evidence can support.

**Evidence before completion.** The skill requires fresh commands, artifacts, tests, review findings, and residual-risk statements before declaring code, runs, comparisons, audits, or releases complete.

**Debugging as a closed loop.** The debugging skill uses observe -> classify -> probe -> compare -> update, so fixes are based on artifacts rather than trial-and-error parameter changes.

**Self-evolution through field lessons.** When users solve a missed SUMO/TraCI issue by another path, the skill can reconstruct the evidence path, abstract the reusable rule, redact private details, and propose a skill update after user confirmation.

## Limitations

This repository provides agent instructions, checklists, and audit procedures. It does not certify that a SUMO experiment is correct.

The skills do not replace manual review, SUMO documentation, controller-specific validation, or independent reproduction. They are intended to reduce common workflow errors and to make claim boundaries explicit.

The audit output should be treated as review support, not as a formal verification result.

## Design Influences

This repository borrows patterns from the broader agent-skill ecosystem:

- Agent Skills convention: self-contained folders with a required `SKILL.md`, YAML frontmatter, and optional resources.
- Public skill repositories such as `anthropics/skills`: repository-level README, skill catalog, examples, and clear disclaimers.
- Skill-authoring patterns from `skill-creator` and `writing-skills`: lean frontmatter, compact `SKILL.md`, one-level references, and validation before release.
- Superpowers-style engineering discipline such as `test-driven-development`, `verification-before-completion`, `requesting-code-review`, and `receiving-code-review`: failing test first, minimal implementation, refactor only after green, evidence before completion, and review feedback handled by verification rather than blind agreement.
- Academic workflow skills such as `academic-paper`, `academic-paper-reviewer`, and `deep-research`: intake records, source hierarchy, evidence boundaries, and claim calibration.
- Debugging and control-loop skills such as `systematic-debugging` and `control-theory`: explicit target, observed state, deviation, next probe, feedback, and residual risk.

No external skill is required at runtime. These influences shaped the structure; the usable package is contained in this repository.

## Repository Layout

```text
README.md
README.zh-CN.md
README.de.md
LICENSE-DOCS
skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
docs/
  common-sumo-signal-control-failures.md
  release/
examples/
  01_fixed_time_audit/
  02_max_pressure_audit/
  03_data_informed_signal_control_audit/
```

Use `docs/release/public-repo-manifest.md` when preparing a clean public repository from a larger local worktree.

## GitHub Topics

Suggested topics:

```text
sumo eclipse-sumo traci traffic-simulation traffic-signal-control transportation intelligent-transportation-systems max-pressure-control reproducibility research-software agent-skills codex claude
```

## Outreach Materials

Draft release materials are included under `docs/release/`:

- `github-topics.txt`
- `mailing-list-announcement.md`
- `linkedin-posts.md`
- `conference-positioning.md`
- `public-repo-manifest.md`

The recommended positioning is "reproducibility and error auditing for SUMO/TraCI signal-control experiments", not "a new academic result".

## Trademark Notice

Eclipse SUMO is a trademark of the Eclipse Foundation. This project is an independent academic resource and is not affiliated with, endorsed by, sponsored by, or maintained by the Eclipse Foundation, the Eclipse SUMO project, or DLR.

This project is intended for academic and research workflow support for experiments using Eclipse SUMO. It does not use official Eclipse or Eclipse SUMO logos.

## No Warranty or Certification

This resource is provided as-is, without warranty of correctness, completeness, or fitness for a particular purpose. Passing an audit checklist does not imply that a SUMO experiment is valid, publishable, or officially certified.

## Citing Eclipse SUMO

This project supports experiments using Eclipse SUMO. If your research uses SUMO, cite the official SUMO reference recommended by the SUMO project:

- Pablo Alvarez Lopez, Michael Behrisch, Laura Bieker-Walz, Jakob Erdmann, Yun-Pang Floetteroed, Robert Hilbrich, Leonhard Luecken, Johannes Rummel, Peter Wagner, and Evamarie Wiessner. "Microscopic Traffic Simulation using SUMO." IEEE Intelligent Transportation Systems Conference, 2018. DOI: `10.1109/ITSC.2018.8569938`.

The Eclipse SUMO about page also notes that release-specific DOIs are available for SUMO releases starting with version 1.2.0.

## License

The skill files, documentation, checklists, and protocol text in this repository are licensed under Creative Commons Attribution 4.0 International (`CC BY 4.0`). See `LICENSE-DOCS`.

If future releases add Python audit scripts or other source code, add a separate code license such as MIT and document the split clearly, for example `LICENSE-CODE` for source code and `LICENSE-DOCS` for text.

## References and Related Resources

These links are provided for context and do not imply endorsement of this repository.

- Eclipse SUMO documentation and licensing pages: [About Eclipse SUMO](https://eclipse.dev/sumo/about/), [SUMO FAQ](https://sumo.dlr.de/docs/FAQ.html), and [SUMO Downloads and Licensing Note](https://sumo.dlr.de/docs/Downloads.html).
- Eclipse Foundation trademark usage policy: [Eclipse Foundation Trademark Usage Policy](https://www.eclipse.org/legal/logo-guidelines/).
- Public agent-skill examples and conventions: [Anthropic public skills repository](https://github.com/anthropics/skills).

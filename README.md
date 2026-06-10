<p align="center">
  <img src="docs/assets/banner.png" alt="Simulation Helper Skill for Eclipse SUMO banner">
</p>

# <img src="docs/assets/app-logo.png" width="42" alt="App logo"> Simulation Helper Skill for Eclipse SUMO

<div align="center">

**Ask. Plan. Build. Debug. Verify. Report.**

**The full SUMO/TraCI experiment workflow, guided by Codex and Claude.**

<img src="https://img.shields.io/badge/SUMO%2FTraCI-signal%20control-blue" alt="SUMO/TraCI signal control">
<img src="https://img.shields.io/badge/Agent-Codex%20%2F%20Claude-6f42c1" alt="Codex and Claude">
<img src="https://img.shields.io/badge/Skill%20Files-2-1d8e57" alt="Two skills">
<img src="https://img.shields.io/badge/Reference%20Modules-23-c98a05" alt="23 reference modules">

<a href="https://tarard.github.io/Simulation-Helper-Skill-for-Eclipse-SUMO/"><strong>Website</strong></a> |
<a href="examples/01_fixed_time_audit/task.md"><strong>Examples</strong></a> |
<a href="docs/common-sumo-signal-control-failures.md"><strong>Failure Checklist</strong></a> |
<a href="LICENSE-DOCS"><strong>CC BY 4.0</strong></a>

[English](README.md) | [简体中文](README.zh-CN.md) | [Deutsch](README.de.md)

</div>

> [!IMPORTANT]
> Current scope: this release focuses on **SUMO/TraCI traffic-signal control experiments**. It is not yet a general-purpose audit package for every Eclipse SUMO use case.

> [!NOTE]
> This is an independent academic workflow resource. It is not affiliated with, endorsed by, sponsored by, or maintained by the Eclipse Foundation, the Eclipse SUMO project, or DLR.

## 🔥 Why This Exists

SUMO can run without crashing while the experiment is still not valid evidence.

This skill is built for the mistakes that often appear late:

- routes or demand silently differ across baselines
- TLS phase indexes do not match intended movements
- `tripinfo`, `summary`, or `edgeData` outputs are missing or overwritten
- controller comparisons are not paired by seed, horizon, demand, and outputs
- simulations stop before demand completes
- arrived-only metrics hide unfinished vehicles
- result claims become stronger than the evidence supports

## 🧠 What It Does

```text
What it is:      A reusable Codex/Claude skill package for the full SUMO/TraCI signal-control experiment workflow.
Who it is for:   Researchers using Eclipse SUMO for fixed-time, actuated, max-pressure, NEMA, data-informed, or MPC-style controllers.
How it works:    A compact SKILL.md acts as a scenario router and loads focused reference modules only when needed.
Where it comes from:
                 Official SUMO documentation, SUMO FAQ/forum lessons, public traffic-simulation code patterns, and the author's own experiment practice.
What it catches: Broken routes, unsafe TLS phases, unpaired baselines, overwritten outputs, invalid metrics, and unreproducible batches.
```

The package is intentionally not a Python validator yet. It is a **workflow protocol and agent skill**: copy it into Codex or Claude, point it at a SUMO experiment repository, and use the structured checks to plan, debug, verify, and report with clear evidence boundaries.

## ⚡ Quick Start

For **Codex**, copy the skill folders into a repository-scoped skill directory:

```text
.agents/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

For **Claude Code**, copy the same folders into:

```text
.claude/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

Then call the skill from the agent:

```text
Use $simulation-helper-skill-for-eclipse-sumo to audit this SUMO/TraCI traffic signal control experiment before I report results.
```

For a failed or suspicious run:

```text
Use $debugging-helper-skill-for-eclipse-sumo to diagnose why this SUMO/TraCI run is invalid or unreproducible.
```

The skill should ask for missing experiment details first. It should not endorse results just because SUMO ran without crashing.

## 🧩 Included Skills

| Skill | Use When | Main Outputs |
|---|---|---|
| `simulation-helper-skill-for-eclipse-sumo` | Planning, auditing, comparing, coding, release checks, and evidence-bounded claim writing for SUMO/TraCI signal-control experiments. | Project Control Screen, Experiment Readiness Record, SUMO Experiment Plan, evidence class, claim boundary, next-step plan. |
| `debugging-helper-skill-for-eclipse-sumo` | SUMO/TraCI route, demand, detector, TLS, output, seed, completion, reproducibility, or runtime failures. | Fault class, next diagnostic probe, evidence, fix/rerun/demotion decision. |

Both skills keep `SKILL.md` deliberately lean. The agent first classifies the scenario, then loads only the relevant reference modules.

## 🗺️ Scenario Router

| Scenario | Load | Expected Output |
|---|---|---|
| Ongoing project, unclear progress, or "what next?" | `workflow-router.md` -> `project-control-screen.md` | Project Control Screen and next-step plan |
| New or vague experiment | `experiment-intake-interview.md` -> `experiment-planning-after-intake.md` | Experiment Readiness Record, then SUMO Experiment Plan |
| Failed or suspicious run | `debugging-helper-skill-for-eclipse-sumo` | root cause, next probe, fix/rerun/demotion |
| Controller, parser, runner, validator, or audit-code change | `tdd-for-sumo-traci-code.md` -> `verification-and-review-gates.md` | RED/GREEN/REFACTOR or explicit `test-after` record |
| Results, metrics, baseline comparison, or paper/report claim | output, metric, baseline, and claim-boundary references | evidence class and allowed/prohibited claim wording |
| User found a fix the skill missed | `field-lesson-capture.md` | privacy-safe field lesson candidate |
| Public release check | `public-release-checklist.md` -> `verification-and-review-gates.md` | release checklist and residual risk |

## 🔗 Skill Structure

The package uses a compact entry-point plus deep-reference format. `SKILL.md` stays lean enough for Codex and Claude to load quickly; focused reference files hold the detailed SUMO/TraCI experiment workflow.

```text
skills/
├─ simulation-helper-skill-for-eclipse-sumo/      # Main workflow skill
│  ├─ SKILL.md                                    # Scenario router and activation rules
│  │  ├─ when to use the skill
│  │  ├─ Ask -> Plan -> Build -> Debug -> Verify -> Report
│  │  ├─ required outputs and claim boundaries
│  │  └─ links to focused references
│  ├─ agents/
│  │  └─ openai.yaml                             # Codex/OpenAI metadata
│  └─ references/                                # Deep workflow documentation
│     ├─ workflow-router.md                      # Route by user scenario
│     ├─ project-control-screen.md               # Target, state, deviation, next step
│     ├─ experiment-intake-interview.md          # Socratic pre-run intake
│     ├─ experiment-planning-after-intake.md     # SUMO experiment plan
│     ├─ tdd-for-sumo-traci-code.md              # RED/GREEN/REFACTOR for code changes
│     ├─ verification-and-review-gates.md        # Evidence-before-completion gates
│     ├─ sumo-official-*.md                      # Official SUMO semantics and lessons
│     ├─ sumo-community-faq-lessons.md           # Forum and FAQ lessons
│     ├─ public-code-lessons.md                  # Lessons from public traffic code
│     └─ *metrics*, *baseline*, *claim-boundary* # Reporting and evidence boundaries
│
├─ debugging-helper-skill-for-eclipse-sumo/       # Focused debug subskill
│  ├─ SKILL.md                                    # Debug activation and workflow
│  ├─ agents/openai.yaml                          # Codex/OpenAI metadata
│  └─ references/
│     ├─ closed-loop-debugging.md                 # Observe, classify, probe, update
│     ├─ symptom-to-evidence-map.md              # Symptom -> required evidence
│     └─ debugging-gates-and-claim-boundaries.md # Fix, rerun, or demote
│
└─ examples/                                      # Prompt-ready audit scenarios
   ├─ 01_fixed_time_audit/
   ├─ 02_max_pressure_audit/
   └─ 03_data_informed_signal_control_audit/
```

<details>
<summary><strong> Simulation helper references</strong></summary>

- [`workflow-router.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/workflow-router.md) - top-level scenario router.
- [`project-control-screen.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/project-control-screen.md) - target, state, deviation, and next-step screen for ongoing projects.
- [`experiment-intake-interview.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-intake-interview.md) - Socratic pre-run questions and Experiment Readiness Record.
- [`experiment-planning-after-intake.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-planning-after-intake.md) - confirmed SUMO Experiment Plan before code, simulation, or claims.
- [`tdd-for-sumo-traci-code.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/tdd-for-sumo-traci-code.md) - RED -> GREEN -> REFACTOR workflow for SUMO/TraCI code changes.
- [`verification-and-review-gates.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/verification-and-review-gates.md) - evidence-before-completion and review gates.
- [`source-ladder.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/source-ladder.md) - source priority and evidence hierarchy.
- [`sumo-official-semantics.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-official-semantics.md) - SUMO network, route, TLS, detector, and TraCI semantics.
- [`sumo-official-operational-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-official-operational-lessons.md) - operational lessons from official SUMO documentation.
- [`sumo-community-faq-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-community-faq-lessons.md) - forum, FAQ, and community troubleshooting lessons.
- [`sumo-nema-controller-audit.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-nema-controller-audit.md) - NEMA ring, barrier, split, recall, detector, and claim checks.
- [`sumo-traci-controller-boundaries.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-traci-controller-boundaries.md) - TraCI controller identity and API-boundary checks.
- [`sumo-output-hard-gates.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-output-hard-gates.md) - output, warning, teleport, and artifact gates.
- [`evaluation-metrics-and-completion.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/evaluation-metrics-and-completion.md) - metric definitions and completion-aware reporting.
- [`baseline-and-ablation-design.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/baseline-and-ablation-design.md) - paired baseline, ablation, and sensitivity design.
- [`experiment-validation-ladder.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-validation-ladder.md) - validation ladder for experiments and debugging fixes.
- [`field-lesson-capture.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/field-lesson-capture.md) - privacy-safe capture of user-discovered fixes.
- [`claim-boundary-taxonomy.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/claim-boundary-taxonomy.md) - evidence-bounded claim wording.
- [`public-code-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/public-code-lessons.md) - lessons distilled from public traffic-simulation code.
- [`public-release-checklist.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/public-release-checklist.md) - release, trademark, privacy, and exposure checks.

</details>

<details>
<summary><strong> Debugging references</strong></summary>

- [`closed-loop-debugging.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/closed-loop-debugging.md) - observe, classify, probe, compare, update.
- [`symptom-to-evidence-map.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/symptom-to-evidence-map.md) - maps common symptoms to required evidence.
- [`debugging-gates-and-claim-boundaries.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/debugging-gates-and-claim-boundaries.md) - demotion rules for failed or partially fixed runs.

</details>

## 🧪 Examples

Each example is prompt-ready:

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

Try:

```text
Use $simulation-helper-skill-for-eclipse-sumo on examples/02_max_pressure_audit/task.md and produce an evidence-bounded audit report.
```

## ✅ What It Audits

- network, routes, configs, detectors, and additional files
- TLS phase, movement-green, yellow, all-red, and NEMA evidence
- paired seeds, demand, outputs, simulation horizons, and baselines
- `tripinfo`, `summary`, `edgeData`, TLS switch output, controller logs, warnings, teleports, and unfinished vehicles
- travel time, delay, stops, throughput, queue, emissions, fairness, and completion-aware reporting
- fixed-time, actuated, max-pressure, NEMA, data-informed, and MPC-style controller comparisons
- TDD records for SUMO/TraCI controller, metric parser, runner, validator, and audit-code changes
- field lessons from user-discovered fixes that should become reusable guidance

See [`docs/common-sumo-signal-control-failures.md`](docs/common-sumo-signal-control-failures.md) for a longer failure checklist.

## 🛠️ Design Principles

- **Progressive disclosure:** `SKILL.md` stays compact and routes the agent to focused references only when needed.
- **Socratic intake:** unclear experiments become an Experiment Readiness Record before execution.
- **TDD before experiment code:** behavior-changing code starts from a failing test or reproducible probe when feasible.
- **Hard gates before claims:** outputs, warnings, completion, and baseline pairing must support the claim.
- **Evidence before completion:** no completion claim without fresh commands, artifacts, tests, and residual risk.
- **Debugging as a closed loop:** observe -> classify -> probe -> compare -> update.
- **Self-evolution:** missed real-world fixes can become privacy-safe field lesson candidates.

## 🧭 Project Status

Current version: **instruction-only skill and checklist package**.

This repository contains Markdown-based agent skills, audit checklists, examples, documentation, and release materials. It does not yet provide executable SUMO validators or Python audit scripts.

### Roadmap

- keep improving signal-control audit coverage
- add more bad-case/fixed-case examples
- add optional Python validators when patterns stabilize
- later expand to other SUMO domains such as routing and demand, emissions and energy, public transport, pedestrian/intermodal scenarios, AV/CAV and co-simulation, calibration, safety analysis, and simulation-mode comparison

## ❓ FAQ

**Do I need to call the skill manually?**

Usually yes for predictable behavior. Use `$simulation-helper-skill-for-eclipse-sumo` when you want the audit path explicitly.

**Does it certify my SUMO experiment?**

No. It provides review support, not formal verification or official certification.

**Why keep `SKILL.md` short?**

Because agents have limited context. The skill should route to the right evidence rules instead of loading every checklist at once.

**Can it debug failed SUMO runs?**

Yes. Use `$debugging-helper-skill-for-eclipse-sumo` for route, TraCI, TLS, output, seed, completion, and reproducibility failures.

**Can it learn from fixes users find later?**

Yes. The field-lesson workflow can abstract a reusable diagnostic path, redact private details, and ask before any update is persisted.

## ⚠️ Limitations

This repository provides agent instructions, checklists, and audit procedures. It does not certify that a SUMO experiment is correct.

The skills do not replace manual review, SUMO documentation, controller-specific validation, or independent reproduction. The audit output should be treated as review support, not as a formal verification result.

## ™️ Trademark Notice

Eclipse SUMO is a trademark of the Eclipse Foundation. This project is independent and is not affiliated with, endorsed by, sponsored by, or maintained by the Eclipse Foundation, the Eclipse SUMO project, or DLR.

This project supports academic and research workflows for experiments using Eclipse SUMO. It does not use official Eclipse or Eclipse SUMO logos.

## 📚 Citing Eclipse SUMO

If your research uses SUMO, cite the official SUMO reference recommended by the SUMO project:

- Pablo Alvarez Lopez, Michael Behrisch, Laura Bieker-Walz, Jakob Erdmann, Yun-Pang Floetteroed, Robert Hilbrich, Leonhard Luecken, Johannes Rummel, Peter Wagner, and Evamarie Wiessner. "Microscopic Traffic Simulation using SUMO." IEEE Intelligent Transportation Systems Conference, 2018. DOI: `10.1109/ITSC.2018.8569938`.

The Eclipse SUMO about page also notes that release-specific DOIs have been provided since SUMO 1.2.0.

## 📄 License

The skill files, documentation, checklists, and protocol text in this repository are licensed under Creative Commons Attribution 4.0 International (`CC BY 4.0`). See [`LICENSE-DOCS`](LICENSE-DOCS).

If future versions add Python audit scripts or other source code, add a separate code license such as MIT and clearly split `LICENSE-CODE` for source code from `LICENSE-DOCS` for text.

## 🔗 References and Related Resources

These links provide context. They do not imply endorsement of this repository.

- Eclipse SUMO documentation and licensing pages: [About Eclipse SUMO](https://eclipse.dev/sumo/about/), [SUMO FAQ](https://sumo.dlr.de/docs/FAQ.html), and [SUMO Downloads and Licensing Note](https://sumo.dlr.de/docs/Downloads.html).
- Eclipse Foundation trademark usage policy: [Eclipse Foundation Trademark Usage Policy](https://www.eclipse.org/legal/logo-guidelines/).
- Public agent-skill examples and conventions: [Anthropic public skills repository](https://github.com/anthropics/skills).

## ⭐ Support

If this checklist helps you avoid a broken SUMO/TraCI experiment, star the repository and adapt the examples for your own research workflow.

## 🔖 Archive

Versioned releases are archived on Zenodo: https://doi.org/10.5281/zenodo.20627976

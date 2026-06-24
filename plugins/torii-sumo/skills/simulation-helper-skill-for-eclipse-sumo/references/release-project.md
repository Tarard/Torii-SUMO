# Public Release Checklist

Use this before publishing the skill to GitHub.

## Bundle Context

This reference can be used from either the standalone public skill repository or the bundled plugin. For the bundled plugin, treat README, website, examples, and release-documentation checks as repository-level checks for the release target, not files that must exist inside this skill directory. Do not require standalone website, examples, or release docs inside the plugin bundle unless the release target is the standalone public skill repository.

## Content Safety

- No local machine paths.
- No non-public notes.
- No non-public datasets or corpora.
- No raw field-lesson logs, private diagnostic transcripts, local paths, collaborator names, or unpublished project facts.
- No private project acronyms or collaborator-specific method names.
- No named-person provenance from unpublished collaboration notes.
- No copied third-party code.
- No claims that all SUMO source code or all forum posts have been exhaustively reviewed.

## Source Hygiene

- Official Eclipse SUMO URLs are listed for NEMA, traffic lights, TraCI, TLS outputs, Summary, TripInfo, FAQ, and the official repository.
- Public codebase lessons cite repository or project URLs.
- Verbatim quotation is avoided or kept short.
- Source-derived facts are paraphrased and bounded.

## Trademark Hygiene

- The public display title is `Torii` and the expansion is `Task-Oriented Road Infrastructure Intelligence`.
- The repository slug is `Torii-SUMO`; the product name remains `Torii` for readability and `SUMO` is kept in the slug for searchability.
- Skill slugs use the `<product name>-for-eclipse-sumo` pattern, not `sumo-*` or `eclipse-sumo-*`.
- README includes a trademark notice stating that the project is independent and not affiliated with, endorsed by, sponsored by, or maintained by the Eclipse Foundation, the Eclipse SUMO project, or DLR.
- README does not use official, certified, endorsed, sponsored, maintained, or similar wording for this project except inside a negative non-affiliation disclaimer.
- No official Eclipse or Eclipse SUMO logos are included.
- Publication titles should treat Eclipse SUMO as the compatible research platform, not as this project's brand.

## Skill Hygiene

- `SKILL.md` frontmatter has `name` and `description`.
- `agents/openai.yaml` has display name, short description, default prompt, and implicit invocation policy.
- Every reference named in `SKILL.md` exists.
- Mixed or ongoing-project requests are routed through `references/route-project-workflow.md`.
- Confirmed intake is routed through `references/plan-experiment.md` before implementation, simulation, comparison, or claims.
- SUMO/TraCI code-change and completion work is routed through `references/develop-and-verify-code.md`.
- Result, metric, baseline, and claim review work is routed through `references/evaluate-and-report-results.md`.
- Self-evolution lessons are captured through `references/capture-field-lesson.md` and require user confirmation plus privacy/source checks before persistence.
- The skill has no README or extra auxiliary docs inside the skill directory.
- The main bundled skill name remains `simulation-helper-skill-for-eclipse-sumo` for install compatibility.
- Companion debugging packages are standalone-skill-release scope only and are not required inside this plugin bundle.

## Exposure Hygiene For Standalone Skill Repository Releases

- README first screen reads like a tool, not a personal note.
- README has language-switch badges linking between `README.md`, `README.zh-CN.md`, and `README.de.md`.
- README links to the GitHub Pages language-switch page at `https://tarard.github.io/Torii-SUMO/`.
- `docs/index.html` exists as a no-build GitHub Pages landing page with in-place English, Chinese, and German language switching.
- README states what it is, who it is for, and what failures it prevents.
- README includes a scenario-based usage table that maps user situations to skills/references and expected outputs.
- README Skill Catalog lists the packaged reference Markdown modules with clickable relative links.
- README includes the repository slug `Torii-SUMO`.
- README quick start uses concrete repository-scoped install paths for Codex (`.agents/skills/`) and Claude Code (`.claude/skills/`).
- README includes current boundaries, clarifying which MCP tools are implemented and which roadmap tools are not complete.
- README includes `## Limitations`, clarifying that the audit does not certify experiment correctness.
- README includes `## No Warranty or Certification`.
- README includes suggested GitHub topics:
  `sumo`, `eclipse-sumo`, `traci`, `traffic-simulation`, `traffic-signal-control`, `transportation`, `intelligent-transportation-systems`, `max-pressure-control`, `reproducibility`, `research-software`, `agent-skills`, `codex`, `claude`.
- `examples/01_signal_control_audit/` contains `task.md`, `README.md`, and the `fixed_time/`, `max_pressure/`, and `data_informed/` subcases.
- `examples/04_one_prompt_osm_network/` contains the Ingolstadt OSM-to-SUMO prompt plus a public TUM-reference comparison summary.
- `docs/common-sumo-signal-control-failures.md` exists and emphasizes practical failure modes.
- `docs/release/` contains GitHub topics, mailing-list announcement draft, LinkedIn post drafts, conference/demo positioning, and a public repository manifest.

## Smoke Prompts

Run these after installation:

1. "Help me run an Eclipse SUMO NEMA experiment."
   - Expected: asks intake questions before commands.
2. "Audit this toy TraCI setPhase controller as a NEMA result."
   - Expected: demotes NEMA claim unless NEMA program evidence is supplied.
3. "Can I use an Eclipse SUMO GUI run screenshot as validation?"
   - Expected: requires headless outputs and classifies GUI as inspection.
4. "My run has summary and tripinfo but no TLS output."
   - Expected: identifies missing TLS evidence for traffic-light claims.
5. "Controller A has lower average travel time, but the simulation stopped at 3600s with vehicles unfinished."
   - Expected: requires completion rate, backlog, and fixed-horizon wording before any superiority claim.
6. "My TraCI co-simulation has two clients and sometimes hangs or changes order."
   - Expected: asks for `--num-clients`, `setOrder`, every-client `simulationStep`, logs, and shutdown evidence.
7. "randomTrips.py produced demand and I used --ignore-route-errors to keep running."
   - Expected: treats invalid/discarded routes as a construction or demand-transformation issue, not formal evidence.
8. "My Eclipse SUMO GUI run works, but TraCI says connection closed or could not connect."
   - Expected: asks for exact command, SUMO logs, environment/version check, port/run-protocol evidence, and classifies as diagnostic until startup is proven.
9. "My Eclipse SUMO experiment improved travel time after I changed three settings at once."
   - Expected: invokes the debugging loop, separates root cause from workaround, and rejects formal claims until one-variable evidence exists.
10. "The skill missed this SUMO/TraCI failure, but I later solved it by changing the diagnostic path."
   - Expected: creates a field lesson candidate, abstracts the reusable rule, redacts private details, and asks before persisting any skill update.
11. "Quickly implement this TraCI metric parser; no need to write tests."
   - Expected: invokes the TDD code gate, asks for approval before skipping TDD, or writes and runs a failing parser test before implementation.
12. "The SUMO controller comparison is done; just say it is complete."
   - Expected: refuses a completion claim without fresh verification evidence, required artifacts, and residual-risk statement.
13. "I confirm the Experiment Readiness Record. Start running SUMO now."
   - Expected: produces a SUMO Experiment Plan and asks for confirmation before code, SUMO file edits, simulation runs, comparisons, or claims.
14. "Here is my existing SUMO repo. Tell me what to do next."
   - Expected: invokes the workflow router and project control screen, estimates target/current state/deviation from artifacts, and produces a Next Step Plan or switches to Socratic intake if state cannot be inferred.

## Publication Gate

Before publishing:

- add `LICENSE` with scoped MIT terms for source code and Creative Commons Attribution 4.0 International (`CC BY 4.0`) terms for skill files, documentation, checklists, examples, and protocol text;
- decide whether to publish the skill alone or as part of a skills collection;
- include `## Trademark Notice` and `## Citing Eclipse SUMO` in the repository README;
- include `## References and Related Resources` without implying endorsement by Eclipse SUMO, Eclipse Foundation, DLR, Anthropic, or any agent-skill project;
- add the suggested GitHub topics in the repository settings after creating the GitHub repository;
- publish only the files listed in `docs/release/public-repo-manifest.md`, not unrelated local project files or private PDFs;
- run a non-public-content scan;
- test installation with Codex skill installer or manual copy;
- note that users should restart Codex after installing.

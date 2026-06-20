# Field Lesson Capture

Use this reference when a user reports that the skill missed a SUMO/TraCI issue, failed to solve a case, or that the user later found a working diagnostic path, workaround, or fix. The goal is to convert the resolved path into a reusable, privacy-safe skill improvement.

## Trigger Conditions

Capture a field lesson when any of these are true:

- The user says the agent or skill was blocked, wrong, incomplete, or too narrow.
- The user solved the issue manually after changing diagnostic path, artifacts, command sequence, environment, controller logic, route generation, or output parsing.
- A failed SUMO/TraCI diagnostic later became resolved and the resolution suggests a reusable workflow.
- A public SUMO issue, forum answer, official document, or public code example explains a failure mode not covered by the current skill.

Do not capture a field lesson when the event is only a one-off project preference, private dataset fact, unpublished collaborator method, or unverified guess.

## Field Lesson Record

Produce this record before proposing any skill edit:

```text
field_lesson_record:
  original_goal:
  observed_failure_or_gap:
  failed_agent_assumptions:
  user_discovered_path:
  decisive_artifacts:
  successful_intervention:
  why_it_worked:
  generalized_rule:
  applies_when:
  does_not_apply_when:
  risk_if_overgeneralized:
  privacy_redactions:
  source_status: official / public-community / public-code / user-experience / mixed
  proposed_skill_update:
```

## Abstraction Rules

- Preserve the diagnostic sequence, not the private case.
- Convert local paths, project names, scenario names, collaborator names, unpublished methods, and dataset identifiers into generic SUMO/TraCI terms.
- Separate simulator semantics, controller logic, environment/protocol behavior, output observability, and claim/reporting consequences.
- Keep exact commands only when they are generic, public-safe, and reusable.
- Store links to public sources when available; do not store raw private logs, screenshots, unpublished data, or full transcripts.
- If the lesson rests on a single anecdotal workaround, mark it as a heuristic and state the risk of overgeneralization.

## Persistence Rules

Before writing, ask the user to confirm whether the lesson should be stored and where:

- `project-scoped`: update the local repository skill copy such as `.agents/skills/...` or `.claude/skills/...` for the current project only.
- `public-repository`: update this public skill repository only after privacy, trademark, source, and claim-boundary checks pass.
- `patch-only`: output a patch proposal without editing files.
- `do-not-store`: summarize the reusable lesson for the current conversation only.

When running in Codex Cloud or another repository-capable agent, create the smallest patch that preserves the one-level `references/` structure. Prefer updating the most relevant existing reference. Add a new reference only when the lesson introduces a distinct repeated workflow.

Never persist:

- private project names, local machine paths, unpublished paper details, collaborator names, private datasets, or private controller variants;
- claims that the lesson is officially endorsed by Eclipse SUMO, Eclipse Foundation, DLR, Codex, Claude, or any public code project;
- a fix that has not been tied to observable artifacts.

## Output Format

End the capture pass with:

```text
Field Lesson Candidate
- reusable problem:
- evidence path:
- generalized rule:
- confidence:

Skill Patch Proposal
- destination:
- file(s):
- change:
- privacy/source checks:

User Confirmation Needed
- store / patch-only / do-not-store:
```

# Torii Research Paper Blueprint

This document translates the effective structural choices in the ChatSUMO paper into a Torii-specific manuscript plan. It borrows presentation order, not technical claims or unsupported evaluation logic.

Reference studied:

- Shuyang Li, Talha Azfar, and Ruimin Ke, “ChatSUMO: Large Language Model for Automating Traffic Scenario Generation in Simulation of Urban MObility,” *IEEE Transactions on Intelligent Vehicles*, DOI: [10.1109/TIV.2024.3508471](https://doi.org/10.1109/TIV.2024.3508471).
- Successor repository pattern reviewed separately: [ChatSUMO-Agent](https://github.com/ChrisLi1221/ChatSUMO-Agent). It is not treated as the implementation repository of the 2024 paper.

## What the ChatSUMO Structure Does Well

The 12-page paper uses a simple narrative sequence:

1. **Introduction:** traffic simulation is useful but expert-heavy; natural language can lower the setup barrier; contributions are stated as user-facing capabilities.
2. **Literature Review:** broad LLM foundations narrow into transportation and traffic-scenario applications.
3. **Methodology:** one overview figure defines the whole system, followed by a prompt-to-dictionary-to-script trace and descriptions of generation, modification, and analysis modules.
4. **Experimental Results:** setup first, then one subsection per advertised capability: generation, edge modification, traffic-light optimization, vehicle editing, and user experience.
5. **Conclusion and Future Work:** restates accessibility gains, then acknowledges data quality, dynamic-event, and trustworthiness limits.

Its figure order is equally deliberate:

| Figure role | Purpose |
|---|---|
| System overview | Lets readers understand the product before reading implementation prose. |
| One prompt trace | Makes the natural-language-to-executable transformation concrete. |
| Capability demonstrations | Gives each headline feature visible evidence. |
| Quantitative result plot | Shows one interpretable response trend. |
| User survey | Supports the accessibility claim separately from simulation metrics. |

The main weakness to avoid is using generated edge counts, runtime success, or aggregate KPI changes as stronger correctness evidence than they warrant.

## Torii's One-Sentence Argument

> Agentic SUMO systems can generate runnable networks, but real-world infrastructure reconstruction requires evidence-bound candidates, structural verification, calibrated abstention, and review-gated promotion so that execution success is not mistaken for model correctness.

Every section, figure, experiment, and repository artifact should support this sentence.

## Proposed Manuscript Structure

### Abstract

Use five moves in order:

1. **Problem:** natural-language automation lowers SUMO effort but can silently turn incomplete map evidence into plausible-looking model errors.
2. **Method:** Torii is an evidence-constrained agent architecture for OSM-to-SUMO construction and repair.
3. **Mechanism:** it separates source and candidate artifacts, applies structural/runtime/reference gates, and may abstain or require review.
4. **Evaluation:** state the frozen scenarios, held-out review design, baselines, and metrics.
5. **Result and boundary:** report only verified effects and explicitly state what remains unproven.

### I. Introduction

1. Establish the distinction between **runnable**, **behaviorally plausible**, and **evidence-supported** SUMO models.
2. Explain why OSM topology, lane semantics, TLS ownership, pedestrian structure, and historical signal data make automated reconstruction difficult.
3. Position language agents and MCP as enabling infrastructure, not the novelty by themselves.
4. State the research questions.
5. State three contributions:
   - an evidence and decision contract for agentic network engineering;
   - a reversible construct-audit-review-promotion architecture with abstention;
   - a benchmark combining machine gates, fault cases, held-out human review, and reproducible artifacts.

### II. Related Work

Organize by the gap Torii closes, not by a chronological tool list:

1. natural-language and agentic traffic simulation, including ChatSUMO and MCP-based systems;
2. OSM-to-SUMO generation and manual network cleanup;
3. traffic-signal, lane-connection, and topology validation;
4. digital-twin demand and signal replay from public observations;
5. human-in-the-loop review, abstention, provenance, and artifact-level reproducibility.

End with a comparison matrix showing which systems support construction, execution, iterative optimization, structural evidence, source/candidate separation, abstention, and review-bound promotion.

### III. Torii Methodology

#### A. Problem Formulation and Claim Tiers

Define source artifacts, candidate artifacts, observations, findings, decisions, promotion, and the difference between structural, behavioral, and reality evidence.

#### B. Agent Architecture

Present router, planning/scope, bounded workflows, tool adapters, domain core, and evidence/reviewer layers. Make the state transition explicit:

```text
discover -> construct -> audit -> propose -> materialize -> verify -> review
                                                        -> promote | abstain
```

#### C. Evidence Contract

Describe hashes, immutable sources, differential scope, exact witnesses, manifests, rollback, and four-valued decisions (`pass`, `review_required`, `blocked`, `not_applicable`).

#### D. Candidate Generation and Abstention

Explain how Torii retains competing topology hypotheses, blocks unsafe candidates before writing, and refuses to infer field truth from SUMO load or routeability alone.

#### E. Implementation

Summarize the skill/MCP/core separation, SUMO and OSM interfaces, schemas, review HTML, and reproducible scripts. Keep function inventories in supplementary material or the repository tool catalog.

### IV. Experimental Design

#### A. Research Questions

- **RQ1:** Does Torii detect structural and semantic defects that runnable-only validation misses?
- **RQ2:** Does evidence-constrained candidate generation reduce unsupported automatic repairs?
- **RQ3:** Is Torii's abstention/review decision calibrated to ambiguity and negative controls?
- **RQ4:** How much expert review effort is retained or reduced without increasing unsafe promotion?
- **RQ5:** Are decisions and artifacts reproducible across clean reruns?

#### B. Cases and Splits

Separate development demonstrations from evaluation evidence:

- XS-1 four-way positive case;
- XS-2 ambiguous three-way case;
- paired/offset negative control;
- Ingolstadt reference corridor;
- synthetic and composite fault benchmarks;
- frozen 30-package held-out human-review corpus;
- Hamburg public-data corridor as a distinct digital-twin validation track.

#### C. Baselines

At minimum compare:

- raw or standard `netconvert` construction;
- runnable-only SUMO validation;
- a language/tool workflow without Torii evidence gates;
- relevant manual/reference decisions where available;
- Torii ablations without differential audit, abstention, or reference evidence.

Do not claim a ChatSUMO implementation baseline unless its code, prompts, environment, and task compatibility are reproducibly controlled.

#### D. Metrics

Report separate metric families:

| Family | Example measures |
|---|---|
| Structural | movement-path completeness, new regression findings, outside-scope delta, conflict violations |
| Runtime | SUMO load, completed routes, collisions, teleports, warnings |
| Decision | unsafe-promotion rate, abstention precision/recall, review-required calibration |
| Human review | agreement, adjudication rate, review time, defect discovery, replacement attempts |
| Reproducibility | normalized candidate hashes, manifest closure, deterministic verdict agreement |
| Digital twin | detector residuals, temporal coverage, signal-stream completeness, non-identifiability boundary |

Never collapse these families into one “accuracy” number.

### V. Results

Order results by research question rather than implementation chronology:

1. structural defects missed by runnable-only checks;
2. candidate safety and outside-scope preservation;
3. ambiguity, negative controls, and abstention behavior;
4. held-out human-review outcomes;
5. reproducibility and failure recovery;
6. digital-twin results, if mature enough for the same manuscript.

Each subsection should contain one claim, one primary table/figure, the relevant uncertainty, and a pointer to exact repository evidence.

### VI. Discussion

Discuss why agentic convenience and engineering validity are different objectives. Compare Torii with performance-driven refinement systems, explain when human review remains necessary, and analyze costs introduced by conservative gates.

### VII. Limitations and Threats to Validity

Cover geographic scope, incomplete/historical map evidence, reference-network age, SUMO-version dependence, human-review sample size, fault-benchmark representativeness, model/provider dependence, and the difference between topology validation and demand/control calibration.

### VIII. Conclusion

Answer each research question briefly. Do not introduce a new product claim. End with the strongest supported boundary: Torii provides auditable candidate engineering, not automatic truth or universal expert-equivalent cleanup.

## Figure Plan

| Figure | Message | Repository evidence |
|---|---|---|
| Fig. 1 | Torii end-to-end architecture and decisions | `ARCHITECTURE.md`, `server.py`, workflow state |
| Fig. 2 | One prompt traced through plan, tools, artifacts, and verdict | one-prompt example plus manifest |
| Fig. 3 | Source/candidate/evidence/promotion contract | schemas and corridor gate artifacts |
| Fig. 4 | Competing H_S/H_M/H_P topology candidates and abstention | teacher-free v4 outputs |
| Fig. 5 | Runnable-only validation versus Torii structural findings | fault and Connection Mode benchmarks |
| Fig. 6 | Held-out human-review design and outcomes | frozen 30-package corpus |
| Fig. 7 | One failure case showing why Torii blocks promotion | Südliche Ringstraße or a preregistered benchmark case |
| Fig. 8 | Optional public-data digital-twin evidence chain | Hamburg MAP/count/TLS/replay manifests |

## Table Plan

1. Related-system capability matrix.
2. Evidence classes, gates, and allowed claims.
3. Dataset/case split with development versus held-out status.
4. Main structural and decision results by RQ.
5. Human-review results and uncertainty.
6. Failure and abstention taxonomy.
7. Reproducibility and artifact-closure summary.

## Writing Rules

- Introduce a concept before its implementation name.
- Give each advertised contribution a matching experiment.
- Keep product usability evidence separate from model-validity evidence.
- Report denominators, seeds, versions, and uncertainty beside headline values.
- Use “detected,” “blocked,” “retained for review,” and “supported within scope” precisely.
- Avoid “correct,” “accurate,” “fully automatic,” or “expert-equivalent” unless a declared reference and validation design support the exact claim.
- Keep detailed tool inventories in the repository, not the paper body.

<p align="center">
  <img src="docs/assets/banner.png" alt="Simulation Helper Skill for Eclipse SUMO banner">
</p>

# <img src="docs/assets/app-logo.png" width="42" alt="App logo"> Simulation Helper Skill for Eclipse SUMO

<div align="center">

**Ein schlankes Codex/Claude-Skill-Paket zur Prüfung von SUMO/TraCI-Verkehrssignal-Experimenten, bevor Ergebnisse zu Aussagen werden.**

<img src="https://img.shields.io/badge/SUMO%2FTraCI-signal%20control-blue" alt="SUMO/TraCI signal control">
<img src="https://img.shields.io/badge/Agent-Codex%20%2F%20Claude-6f42c1" alt="Codex and Claude">
<img src="https://img.shields.io/badge/Skill%20Files-2-1d8e57" alt="Two skills">
<img src="https://img.shields.io/badge/Reference%20Modules-23-c98a05" alt="23 reference modules">

<a href="https://tarard.github.io/Simulation-Helper-Skill-for-Eclipse-SUMO/"><strong>Website</strong></a> |
<a href="examples/01_fixed_time_audit/task.md"><strong>Beispiele</strong></a> |
<a href="docs/common-sumo-signal-control-failures.md"><strong>Fehler-Checkliste</strong></a> |
<a href="LICENSE-DOCS"><strong>CC BY 4.0</strong></a>

[English](README.md) | [简体中文](README.zh-CN.md) | [Deutsch](README.de.md)

</div>

> [!IMPORTANT]
> Der aktuelle Umfang konzentriert sich auf **SUMO/TraCI-Experimente zur Verkehrssignalsteuerung**. Dies ist noch kein allgemeines Audit-Paket für alle Eclipse-SUMO-Anwendungsfälle.

> [!NOTE]
> Dies ist eine unabhängige akademische Workflow-Ressource. Sie ist nicht mit der Eclipse Foundation, dem Eclipse-SUMO-Projekt oder DLR verbunden und wird von diesen nicht unterstützt, gesponsert oder gepflegt.

## 🔥 Warum es existiert

SUMO kann ohne Absturz laufen, während das Experiment trotzdem keine belastbare Evidenz liefert.

Dieser Skill zielt auf Fehler, die oft erst spät sichtbar werden:

- Routen oder Nachfrage unterscheiden sich still zwischen Baselines
- TLS-Phasenindizes passen nicht zu den beabsichtigten Bewegungen
- `tripinfo`, `summary` oder `edgeData` fehlen oder werden überschrieben
- Controller-Vergleiche sind nicht nach Seed, Horizont, Nachfrage und Outputs gepaart
- Simulationen stoppen, bevor die Nachfrage vollständig abgearbeitet ist
- Nur angekommene Fahrzeuge werden ausgewertet, unfertige Fahrzeuge verschwinden aus der Metrik
- Aussagen im Paper oder Bericht sind stärker als die Evidenz

## 🧠 Was es macht

```text
Was es ist:       Ein wiederverwendbares Codex/Claude-Skill-Paket zur Prüfung von SUMO/TraCI-Signalsteuerungs-Workflows.
Für wen:          Forschende, die Eclipse SUMO für fixed-time, actuated, max-pressure, NEMA, data-informed oder MPC-style Controller nutzen.
Wie es arbeitet:  Eine kompakte SKILL.md dient als Szenario-Router und lädt fokussierte Referenzmodule nur bei Bedarf.
Woher es kommt:   Offizielle SUMO-Dokumentation, SUMO-FAQ/Forum-Erfahrungen, Muster aus öffentlichem Verkehrssimulationscode und eigene Experimentpraxis des Autors.
Was es findet:    Fehlerhafte Routen, unsichere TLS-Phasen, ungepaarte Baselines, überschriebene Outputs, ungültige Metriken und nicht reproduzierbare Batch-Läufe.
```

Das Paket ist bewusst noch kein Python-Validator. Es ist ein **Review-Protokoll und Agent Skill**: Kopieren Sie es in Codex oder Claude, richten Sie es auf ein SUMO-Experiment-Repository und nutzen Sie den Audit-Output, um belastbare Aussagen von zu starken Aussagen zu trennen.

## ⚡ Schnellstart

Für **Codex** kopieren Sie die Skill-Ordner in ein repository-spezifisches Skill-Verzeichnis:

```text
.agents/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

Für **Claude Code** kopieren Sie dieselben Ordner nach:

```text
.claude/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

Rufen Sie den Skill dann im Agent auf:

```text
Use $simulation-helper-skill-for-eclipse-sumo to audit this SUMO/TraCI traffic signal control experiment before I report results.
```

Für einen fehlgeschlagenen oder verdächtigen Lauf:

```text
Use $debugging-helper-skill-for-eclipse-sumo to diagnose why this SUMO/TraCI run is invalid or unreproducible.
```

Der Skill sollte zuerst fehlende Experimentdetails erfragen. Dass SUMO ohne Absturz läuft, bedeutet noch nicht, dass die Ergebnisse belastbar sind.

## 🧩 Enthaltene Skills

| Skill | Wann nutzen | Hauptausgaben |
|---|---|---|
| `simulation-helper-skill-for-eclipse-sumo` | Planung, Audit, Vergleich, Codeänderungen, Release-Checks und evidenzbegrenzte Claims für SUMO/TraCI-Signalsteuerungs-Experimente. | Project Control Screen, Experiment Readiness Record, SUMO Experiment Plan, evidence class, claim boundary, next-step plan. |
| `debugging-helper-skill-for-eclipse-sumo` | SUMO/TraCI-Route-, Nachfrage-, Detektor-, TLS-, Output-, Seed-, Completion-, Reproduzierbarkeits- oder Laufzeitfehler. | Fault class, next diagnostic probe, evidence, fix/rerun/demotion decision. |

Beide `SKILL.md`-Dateien bleiben bewusst schlank. Der Agent klassifiziert zuerst das Szenario und lädt dann nur die relevanten Referenzmodule.

## 🗺️ Szenario-Router

| Szenario | Laden | Erwartete Ausgabe |
|---|---|---|
| Laufendes Projekt, unklarer Fortschritt oder "was als Nächstes?" | `workflow-router.md` -> `project-control-screen.md` | Project Control Screen und next-step plan |
| Neues oder vages Experiment | `experiment-intake-interview.md` -> `experiment-planning-after-intake.md` | Experiment Readiness Record, danach SUMO Experiment Plan |
| Fehlgeschlagener oder verdächtiger Lauf | `debugging-helper-skill-for-eclipse-sumo` | root cause, next probe, fix/rerun/demotion |
| Controller-, Parser-, Runner-, Validator- oder Audit-Code-Änderung | `tdd-for-sumo-traci-code.md` -> `verification-and-review-gates.md` | RED/GREEN/REFACTOR oder expliziter `test-after` record |
| Ergebnisse, Metriken, Baseline-Vergleich oder Paper-/Berichtsclaim | Output-, Metric-, Baseline- und Claim-Boundary-Referenzen | evidence class und erlaubte/verbotene claim wording |
| Nutzer findet eine Lösung, die der Skill verfehlt hat | `field-lesson-capture.md` | privacy-safe field lesson candidate |
| Öffentlicher Release-Check | `public-release-checklist.md` -> `verification-and-review-gates.md` | release checklist und residual risk |

## 📦 Referenzmodule

<details>
<summary><strong> Simulation-helper references</strong></summary>

- [`workflow-router.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/workflow-router.md) - oberster Szenario-Router.
- [`project-control-screen.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/project-control-screen.md) - Ziel, Zustand, Abweichung und nächster Schritt für laufende Projekte.
- [`experiment-intake-interview.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-intake-interview.md) - sokratische Vorabfragen und Experiment Readiness Record.
- [`experiment-planning-after-intake.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-planning-after-intake.md) - bestätigter SUMO Experiment Plan vor Code, Simulation oder Claims.
- [`tdd-for-sumo-traci-code.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/tdd-for-sumo-traci-code.md) - RED -> GREEN -> REFACTOR für SUMO/TraCI-Codeänderungen.
- [`verification-and-review-gates.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/verification-and-review-gates.md) - evidence-before-completion und Review-Gates.
- [`source-ladder.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/source-ladder.md) - Quellenpriorität und Evidenzhierarchie.
- [`sumo-official-semantics.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-official-semantics.md) - SUMO network, route, TLS, detector und TraCI semantics.
- [`sumo-official-operational-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-official-operational-lessons.md) - operative Lehren aus offizieller SUMO-Dokumentation.
- [`sumo-community-faq-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-community-faq-lessons.md) - Forum-, FAQ- und Community-Troubleshooting-Lektionen.
- [`sumo-nema-controller-audit.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-nema-controller-audit.md) - NEMA ring, barrier, split, recall, detector und claim checks.
- [`sumo-traci-controller-boundaries.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-traci-controller-boundaries.md) - TraCI controller identity und API-boundary checks.
- [`sumo-output-hard-gates.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-output-hard-gates.md) - Output-, Warning-, Teleport- und Artifact-Gates.
- [`evaluation-metrics-and-completion.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/evaluation-metrics-and-completion.md) - Metrikdefinitionen und completion-aware reporting.
- [`baseline-and-ablation-design.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/baseline-and-ablation-design.md) - paired baseline, ablation und sensitivity design.
- [`experiment-validation-ladder.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-validation-ladder.md) - Validierungsleiter für Experimente und Debugging-Fixes.
- [`field-lesson-capture.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/field-lesson-capture.md) - datenschutzfreundliche Abstraktion von Nutzer-Fixes.
- [`claim-boundary-taxonomy.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/claim-boundary-taxonomy.md) - evidenzbegrenzte Claim-Formulierung.
- [`public-code-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/public-code-lessons.md) - Lehren aus öffentlichem Verkehrssimulationscode.
- [`public-release-checklist.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/public-release-checklist.md) - Release-, Trademark-, Privacy- und Exposure-Checks.

</details>

<details>
<summary><strong> Debugging references</strong></summary>

- [`closed-loop-debugging.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/closed-loop-debugging.md) - observe, classify, probe, compare, update.
- [`symptom-to-evidence-map.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/symptom-to-evidence-map.md) - ordnet häufige Symptome der nötigen Evidenz zu.
- [`debugging-gates-and-claim-boundaries.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/debugging-gates-and-claim-boundaries.md) - Demotionsregeln für fehlgeschlagene oder nur teilweise behobene Läufe.

</details>

## 🧪 Beispiele

Jedes Beispiel ist prompt-ready:

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

Beispielaufruf:

```text
Use $simulation-helper-skill-for-eclipse-sumo on examples/02_max_pressure_audit/task.md and produce an evidence-bounded audit report.
```

## ✅ Was geprüft wird

- network, routes, configs, detectors und additional files
- TLS phase, movement-green, yellow, all-red und NEMA evidence
- paired seeds, demand, outputs, simulation horizons und baselines
- `tripinfo`, `summary`, `edgeData`, TLS switch output, controller logs, warnings, teleports und unfinished vehicles
- travel time, delay, stops, throughput, queue, emissions, fairness und completion-aware reporting
- fixed-time, actuated, max-pressure, NEMA, data-informed und MPC-style controller comparisons
- TDD records für SUMO/TraCI controller, metric parser, runner, validator und audit-code changes
- Feldlektionen aus Nutzer-Fixes, die zu wiederverwendbarer Guidance werden können

Siehe [`docs/common-sumo-signal-control-failures.md`](docs/common-sumo-signal-control-failures.md) für eine längere Fehler-Checkliste.

## 🛠️ Designprinzipien

- **Progressive disclosure:** `SKILL.md` bleibt kompakt und routet nur bei Bedarf zu fokussierten Referenzen.
- **Socratic intake:** Unklare Experimente werden vor der Ausführung in einen Experiment Readiness Record überführt.
- **TDD before experiment code:** Verhaltensändernder Code beginnt nach Möglichkeit mit einem failing test oder reproduzierbaren probe.
- **Hard gates before claims:** Outputs, Warnings, Completion und Baseline-Pairing müssen den Claim tragen.
- **Evidence before completion:** Keine Abschlussbehauptung ohne frische Commands, Artefakte, Tests und Restrisiko.
- **Debugging as a closed loop:** observe -> classify -> probe -> compare -> update.
- **Self-evolution:** Nicht abgedeckte reale Fixes können zu privacy-safe field lesson candidates werden.

## 🧭 Projektstatus

Aktuelle Version: **reines Instruktions- und Checklistenpaket**.

Dieses Repository enthält Markdown-basierte Agent Skills, Audit-Checklisten, Beispiele, Dokumentation und Release-Materialien. Es enthält noch keine ausführbaren SUMO-Validatoren oder Python-Audit-Skripte.

### Roadmap

- Signal-Control-Audit-Coverage weiter verbessern
- mehr bad-case/fixed-case examples ergänzen
- optionale Python-Validatoren hinzufügen, sobald Muster stabil sind
- später weitere SUMO-Domänen abdecken, etwa routing and demand, emissions and energy, public transport, pedestrian/intermodal scenarios, AV/CAV and co-simulation, calibration, safety analysis und simulation-mode comparison

## ❓ FAQ

**Muss ich den Skill manuell aufrufen?**

Meist ja. Nutzen Sie `$simulation-helper-skill-for-eclipse-sumo`, wenn der Audit-Pfad explizit verwendet werden soll.

**Zertifiziert der Skill mein SUMO-Experiment?**

Nein. Er bietet Review-Unterstützung, keine formale Verifikation und keine offizielle Zertifizierung.

**Warum ist `SKILL.md` kurz gehalten?**

Weil Agenten begrenzten Kontext haben. Der Skill soll zu den passenden Evidenzregeln routen, statt alle Checklisten gleichzeitig zu laden.

**Kann er fehlgeschlagene SUMO-Läufe debuggen?**

Ja. Für route-, TraCI-, TLS-, output-, seed-, completion- und reproducibility-Fehler nutzen Sie `$debugging-helper-skill-for-eclipse-sumo`.

**Kann er aus später gefundenen Nutzer-Fixes lernen?**

Ja. Der Field-Lesson-Workflow abstrahiert einen wiederverwendbaren Diagnosepfad, entfernt private Details und fragt vor jeder dauerhaften Aktualisierung nach.

## ⚠️ Grenzen

Dieses Repository stellt Agent-Instruktionen, Checklisten und Audit-Verfahren bereit. Es zertifiziert nicht, dass ein SUMO-Experiment korrekt ist.

Die Skills ersetzen keine manuelle Prüfung, SUMO-Dokumentation, controller-spezifische Validierung oder unabhängige Reproduktion. Der Audit-Output ist Review-Unterstützung, kein formales Verifikationsergebnis.

## ™️ Trademark-Hinweis

Eclipse SUMO ist eine Marke der Eclipse Foundation. Dieses Projekt ist unabhängig und nicht mit der Eclipse Foundation, dem Eclipse-SUMO-Projekt oder DLR verbunden, unterstützt, gesponsert oder gepflegt.

Dieses Projekt unterstützt akademische und forschungsbezogene Workflows für Experimente mit Eclipse SUMO. Es verwendet keine offiziellen Eclipse- oder Eclipse-SUMO-Logos.

## 📚 Eclipse SUMO zitieren

Wenn Ihre Forschung SUMO verwendet, zitieren Sie die vom SUMO-Projekt empfohlene offizielle Referenz:

- Pablo Alvarez Lopez, Michael Behrisch, Laura Bieker-Walz, Jakob Erdmann, Yun-Pang Floetteroed, Robert Hilbrich, Leonhard Luecken, Johannes Rummel, Peter Wagner, and Evamarie Wiessner. "Microscopic Traffic Simulation using SUMO." IEEE Intelligent Transportation Systems Conference, 2018. DOI: `10.1109/ITSC.2018.8569938`.

Die Eclipse-SUMO-About-Seite weist außerdem darauf hin, dass seit SUMO 1.2.0 release-spezifische DOIs bereitgestellt werden.

## 📄 Lizenz

Die Skill-Dateien, Dokumentation, Checklisten und Protokolltexte in diesem Repository stehen unter Creative Commons Attribution 4.0 International (`CC BY 4.0`). Siehe [`LICENSE-DOCS`](LICENSE-DOCS).

Falls spätere Versionen Python-Audit-Skripte oder anderen Quellcode ergänzen, sollte eine separate Code-Lizenz wie MIT hinzugefügt und klar zwischen `LICENSE-CODE` und `LICENSE-DOCS` unterschieden werden.

## 🔗 References and Related Resources

Diese Links liefern Kontext. Sie bedeuten keine Unterstützung dieses Repositorys.

- Eclipse SUMO documentation and licensing pages: [About Eclipse SUMO](https://eclipse.dev/sumo/about/), [SUMO FAQ](https://sumo.dlr.de/docs/FAQ.html), and [SUMO Downloads and Licensing Note](https://sumo.dlr.de/docs/Downloads.html).
- Eclipse Foundation trademark usage policy: [Eclipse Foundation Trademark Usage Policy](https://www.eclipse.org/legal/logo-guidelines/).
- Public agent-skill examples and conventions: [Anthropic public skills repository](https://github.com/anthropics/skills).

## ⭐ Support

Wenn diese Checkliste hilft, ein fehlerhaftes SUMO/TraCI-Experiment zu vermeiden, geben Sie dem Repository einen Star und passen Sie die Beispiele an den eigenen Forschungsworkflow an.

<p align="right">
  <a href="README.md"><img src="https://img.shields.io/badge/lang-English-blue" alt="English"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/lang-%E4%B8%AD%E6%96%87-red" alt="中文"></a>
  <a href="README.de.md"><img src="https://img.shields.io/badge/lang-Deutsch-green" alt="Deutsch"></a>
</p>

# Simulation Helper Skill for Eclipse SUMO

Website: [tarard.github.io/Simulation-Helper-Skill-for-Eclipse-SUMO](https://tarard.github.io/Simulation-Helper-Skill-for-Eclipse-SUMO/)

**Agent Skill fuer Verkehrssignalsteuerungs-Experimente**

Wiederverwendbare Codex/Claude Skills und Checklisten zur Pruefung von SUMO/TraCI-Experimenten zur Verkehrssignalsteuerung, bevor Ergebnisse berichtet werden.

```text
Was es ist:       Ein wiederverwendbarer Agent Skill zur Pruefung von SUMO/TraCI-Signalsteuerungs-Workflows.
Fuer wen:         Forschende, die Eclipse SUMO fuer fixed-time, actuated, max-pressure, data-informed oder MPC-style Controller nutzen.
Wie es arbeitet:  Es verdichtet offizielle SUMO-Dokumentation, SUMO-Forum- und Community-Troubleshooting, Muster aus oeffentlichem Verkehrssimulationscode und praktische Experimenterfahrung des Autors zu einem Agent-Audit-Workflow.
Was es findet:    Fehlerhafte Routen, unsichere TLS-Phasen, ungepaarte Baselines, ueberschriebene Outputs, ungueltige Metriken und nicht reproduzierbare Batch-Experimente.
```

Dieses Repository ist als praktisches Forschungswerkzeug gedacht, nicht als Verpackung fuer ein Paper. Kopieren Sie den Skill in Codex oder Claude, wenden Sie ihn auf ein SUMO-Experiment an und nutzen Sie den Audit-Bericht, um zu entscheiden, welche Aussagen belastbar sind.

## Schnellstart

Fuer Codex kopieren Sie die Skill-Ordner in ein repository-spezifisches Skill-Verzeichnis:

```text
.agents/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

Fuer Claude Code kopieren Sie dieselben Ordner nach:

```text
.claude/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

Rufen Sie den Skill dann im Agent auf:

```text
Use $simulation-helper-skill-for-eclipse-sumo to audit this SUMO/TraCI traffic signal control experiment before I report results.
```

Fuer Fehleranalyse:

```text
Use $debugging-helper-skill-for-eclipse-sumo to diagnose why this SUMO/TraCI run is invalid or unreproducible.
```

Der Skill sollte zuerst fehlende Experimentdetails erfragen. Dass SUMO ohne Absturz laeuft, bedeutet noch nicht, dass die Ergebnisse belastbar sind.

## Projektstatus

Aktuelle Version: reines Instruktions- und Checklistenpaket.

Dieses Repository enthaelt derzeit Markdown-basierte Agent Skills, Audit-Checklisten, Beispiele und Release-Materialien. Es enthaelt noch keine ausfuehrbaren SUMO-Validatoren oder Python-Audit-Skripte.

## Aktueller Umfang

Die aktuelle Version konzentriert sich auf SUMO/TraCI-Experimente zur Verkehrssignalsteuerung. Sie ist noch kein allgemeiner Audit-Skill fuer alle Eclipse SUMO-Anwendungsfaelle.

Diese Version deckt fixed-time, actuated, max-pressure, NEMA, data-informed und MPC-style Signalsteuerungs-Workflows ab. Kuenftige Skills koennen Audit-Unterstuetzung fuer weitere SUMO-Domaenen ergaenzen, zum Beispiel demand and routing, emissions and energy, public transport, pedestrian and intermodal scenarios, AV/CAV and co-simulation workflows, calibration, safety analysis sowie mesoscopic oder microscopic simulation-mode comparisons.

## Skill-Katalog

| Skill | Einsatzbereich | Hauptausgaben |
|---|---|---|
| `simulation-helper-skill-for-eclipse-sumo` | Planung, Review, Vergleich oder Formulierung von Aussagen aus SUMO/TraCI-Signalsteuerungs-Experimenten. | Experiment Readiness Record, hard-gate audit, evidence class, claim boundary. |
| `debugging-helper-skill-for-eclipse-sumo` | Debugging von route-, TraCI-, TLS-, demand-, detector-, output-, seed-, completion- und reproducibility-Problemen. | Fault class, next diagnostic probe, evidence, fix or demotion rule. |

Beide Skills sind einfache `SKILL.md`-Pakete mit YAML-Frontmatter und Markdown-Referenzen. Die Dateien `agents/openai.yaml` liefern optionale Codex-UI-Metadaten; die Kernanweisungen bleiben fuer Claude-style Skill Loader lesbar, die `SKILL.md` verwenden.

Enthaltene Referenzmodule:

**Simulation helper references**

- [`experiment-intake-interview.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-intake-interview.md) - sokratische Vorabfragen und Experiment Readiness Record.
- [`source-ladder.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/source-ladder.md) - Quellenprioritaet und Evidenzhierarchie.
- [`sumo-official-semantics.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-official-semantics.md) - SUMO network-, route-, TLS-, detector- und TraCI-Semantik.
- [`sumo-official-operational-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-official-operational-lessons.md) - operative Hinweise aus offizieller SUMO-Dokumentation.
- [`sumo-community-faq-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-community-faq-lessons.md) - Forum-, FAQ- und Community-Troubleshooting-Lektionen.
- [`sumo-nema-controller-audit.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-nema-controller-audit.md) - NEMA ring-, barrier-, split-, recall-, detector- und claim-Pruefungen.
- [`sumo-traci-controller-boundaries.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-traci-controller-boundaries.md) - TraCI-Controller-Identitaet und API-Grenzen.
- [`sumo-output-hard-gates.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-output-hard-gates.md) - output-, warning-, teleport- und artifact-hard-gates.
- [`evaluation-metrics-and-completion.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/evaluation-metrics-and-completion.md) - Metrikdefinitionen und completion-aware reporting.
- [`baseline-and-ablation-design.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/baseline-and-ablation-design.md) - paired baseline-, ablation- und sensitivity-Design.
- [`experiment-validation-ladder.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-validation-ladder.md) - Validierungsleiter fuer Experimente und Debugging-Fixes.
- [`field-lesson-capture.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/field-lesson-capture.md) - datenschutzsichere Erfassung nutzergefundener Fixes und wiederverwendbarer Diagnosepfade.
- [`claim-boundary-taxonomy.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/claim-boundary-taxonomy.md) - Formulierungsregeln fuer evidenzgebundene Aussagen.
- [`public-code-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/public-code-lessons.md) - Lektionen aus oeffentlichem Verkehrssimulationscode.
- [`public-release-checklist.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/public-release-checklist.md) - Release-, Marken-, Datenschutz- und Exposure-Pruefungen.

**Debugging audit references**

- [`closed-loop-debugging.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/closed-loop-debugging.md) - observe, classify, probe, compare, update.
- [`symptom-to-evidence-map.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/symptom-to-evidence-map.md) - ordnet haeufige Symptome den notwendigen Evidenzen zu.
- [`debugging-gates-and-claim-boundaries.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/debugging-gates-and-claim-boundaries.md) - Abstufungsregeln fuer fehlgeschlagene oder teilweise korrigierte Laeufe.

## Was geprueft wird

- Konsistenz zwischen TLS-Phasen und movement-green-Zuordnung.
- Konsistenz von route, config, additional file, detector und network.
- Vergleiche von fixed-time, actuated, max-pressure, NEMA, data-informed und MPC-style Controllern.
- Gepaarte seeds, demand, output intervals und simulation horizons.
- `tripinfo`, `summary`, `edgeData`, TLS switch output, controller logs, warnings, teleports und unfinished vehicles.
- Completion-aware Metriken, wenn Simulationen stoppen, bevor alle Fahrzeuge das Netz verlassen.
- Baselines, Ablations, Sensitivity Runs und Formulierung von Aussagen.
- Field-Lesson-Erfassung, wenn Nutzer ein vom Skill verfehltes SUMO/TraCI-Problem loesen und den wiederverwendbaren Diagnosepfad in den Skill zurueckfuehren wollen.

## Beispiele

Jedes Beispiel ist so aufgebaut, dass es direkt in einen Agent Prompt kopiert werden kann:

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

Beginnen Sie mit `task.md` und vergleichen Sie die Agent-Ausgabe mit `expected_audit_report.md`.

## Checkliste haeufiger Fehler

Eine laengere Checkliste steht in `docs/common-sumo-signal-control-failures.md`. Sie behandelt unter anderem:

1. SUMO laeuft, aber `tripinfo.xml` ist leer.
2. Der TLS phase index passt nicht zur beabsichtigten movement.
3. Ein Max-Pressure Controller wird mit ungepaarten seeds verglichen.
4. Das `edgeData` interval unterscheidet sich zwischen Controllern.
5. Data-informed weights enthalten Informationen aus zukuenftigen Ergebnissen.
6. Route files veraendern demand stillschweigend zwischen Baselines.
7. Yellow- und all-red-Behandlung unterscheiden sich zwischen Methoden.
8. Die Simulation stoppt, bevor die Nachfrage abgeschlossen ist.
9. Controller runtime oder fallback behavior fehlt.

## Wie die Skills entworfen sind

Das Design folgt fuenf Prinzipien:

**Progressive disclosure.** `SKILL.md` bleibt kompakt und verweist den Agent nur bei Bedarf auf fokussierte Referenzdateien.

**Sokratische Aufnahme vor der Ausfuehrung.** Bei unterspezifizierten Experimenten fragt der Skill gezielt nach network, demand, controller, outputs, baselines, seeds und metrics und erstellt einen Experiment Readiness Record.

**Hard gates vor Aussagen.** Das Audit trennt, was SUMO tatsaechlich geladen hat, was der Controller tatsaechlich getan hat, welche Outputs geschrieben wurden, welche Warnungen auftraten und welche Aussage die Evidenz tragen kann.

**Debugging als geschlossener Regelkreis.** Der Debugging-Skill nutzt observe -> classify -> probe -> compare -> update, damit Korrekturen auf Artefakten beruhen und nicht auf Trial-and-Error.

**Selbstentwicklung durch Field Lessons.** Wenn Nutzer ein vom Skill verfehltes SUMO/TraCI-Problem auf einem anderen Weg loesen, kann der Skill den Evidenzpfad rekonstruieren, die wiederverwendbare Regel abstrahieren, private Details entfernen und nach Nutzerbestaetigung eine Skill-Aktualisierung vorschlagen.

## Grenzen

Dieses Repository stellt Agent-Anweisungen, Checklisten und Audit-Prozeduren bereit. Es zertifiziert nicht, dass ein SUMO-Experiment korrekt ist.

Die Skills ersetzen keine manuelle Pruefung, keine SUMO-Dokumentation, keine controller-spezifische Validierung und keine unabhaengige Reproduktion. Sie sollen haeufige Workflow-Fehler reduzieren und claim boundaries explizit machen.

Die Audit-Ausgabe sollte als Review-Unterstuetzung behandelt werden, nicht als formales Verifikationsergebnis.

## Design-Einfluesse

Dieses Repository uebernimmt Muster aus dem weiteren Agent-Skill-Oekosystem:

- Agent Skills convention: selbststaendige Ordner mit einer erforderlichen `SKILL.md`, YAML-Frontmatter und optionalen Ressourcen.
- Oeffentliche Skill-Repositories wie `anthropics/skills`: README auf Repository-Ebene, Skill-Katalog, Beispiele und klare Disclaimer.
- Skill-Authoring-Muster aus `skill-creator` und `writing-skills`: schlankes Frontmatter, kompakte `SKILL.md`, einstufige Referenzen und Validierung vor Release.
- Akademische Workflow-Skills wie `academic-paper`, `academic-paper-reviewer` und `deep-research`: intake records, source hierarchy, evidence boundaries und claim calibration.
- Debugging- und Control-Loop-Skills wie `systematic-debugging` und `control-theory`: explizite target, observed state, deviation, next probe, feedback und residual risk.

Zur Laufzeit ist kein externer Skill erforderlich. Diese Einfluesse praegen die Struktur; das nutzbare Paket ist in diesem Repository enthalten.

## Repository-Struktur

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

Wenn ein sauberes oeffentliches Repository aus einem groesseren lokalen Worktree vorbereitet wird, nutzen Sie `docs/release/public-repo-manifest.md`.

## GitHub Topics

Empfohlene Topics:

```text
sumo eclipse-sumo traci traffic-simulation traffic-signal-control transportation intelligent-transportation-systems max-pressure-control reproducibility research-software agent-skills codex claude
```

## Outreach-Materialien

Entwuerfe befinden sich unter `docs/release/`:

- `github-topics.txt`
- `mailing-list-announcement.md`
- `linkedin-posts.md`
- `conference-positioning.md`
- `public-repo-manifest.md`

Die empfohlene Positionierung ist "reproducibility and error auditing for SUMO/TraCI signal-control experiments", nicht "ein neues wissenschaftliches Ergebnis".

## Markenhinweis

Eclipse SUMO ist eine Marke der Eclipse Foundation. Dieses Projekt ist eine unabhaengige akademische Ressource und ist nicht mit der Eclipse Foundation, dem Eclipse SUMO project oder DLR verbunden, von ihnen unterstuetzt, gesponsert oder gepflegt.

Dieses Projekt dient der Unterstuetzung akademischer und forschungsbezogener Workflows fuer Experimente mit Eclipse SUMO. Es verwendet keine offiziellen Eclipse- oder Eclipse SUMO-Logos.

## Keine Gewaehrleistung oder Zertifizierung

Diese Ressource wird wie besehen bereitgestellt, ohne Gewaehr fuer Richtigkeit, Vollstaendigkeit oder Eignung fuer einen bestimmten Zweck. Das Bestehen einer Audit-Checkliste bedeutet nicht, dass ein SUMO-Experiment gueltig, publizierbar oder offiziell zertifiziert ist.

## Eclipse SUMO zitieren

Dieses Projekt unterstuetzt Experimente mit Eclipse SUMO. Wenn Ihre Forschung SUMO verwendet, zitieren Sie die offizielle SUMO-Referenz, die vom SUMO project empfohlen wird:

- Pablo Alvarez Lopez, Michael Behrisch, Laura Bieker-Walz, Jakob Erdmann, Yun-Pang Floetteroed, Robert Hilbrich, Leonhard Luecken, Johannes Rummel, Peter Wagner, and Evamarie Wiessner. "Microscopic Traffic Simulation using SUMO." IEEE Intelligent Transportation Systems Conference, 2018. DOI: `10.1109/ITSC.2018.8569938`.

Die Eclipse SUMO About-Seite weist ausserdem darauf hin, dass fuer SUMO-Releases ab Version 1.2.0 release-specific DOIs verfuegbar sind.

## Lizenz

Die Skill-Dateien, Dokumentation, Checklisten und Protokolltexte in diesem Repository stehen unter Creative Commons Attribution 4.0 International (`CC BY 4.0`). Siehe `LICENSE-DOCS`.

Falls kuenftige Releases Python-Audit-Skripte oder anderen Source Code enthalten, sollte eine separate Code-Lizenz wie MIT hinzugefuegt und die Trennung klar dokumentiert werden, zum Beispiel `LICENSE-CODE` fuer Source Code und `LICENSE-DOCS` fuer Text.

## Referenzen und verwandte Ressourcen

Diese Links dienen nur als Kontext und bedeuten keine Unterstuetzung dieses Repositories.

- Eclipse SUMO documentation and licensing pages: [About Eclipse SUMO](https://eclipse.dev/sumo/about/), [SUMO FAQ](https://sumo.dlr.de/docs/FAQ.html), and [SUMO Downloads and Licensing Note](https://sumo.dlr.de/docs/Downloads.html).
- Eclipse Foundation trademark usage policy: [Eclipse Foundation Trademark Usage Policy](https://www.eclipse.org/legal/logo-guidelines/).
- Public agent-skill examples and conventions: [Anthropic public skills repository](https://github.com/anthropics/skills).

<p align="center">
  <img src="docs/assets/banner.png" alt="Banner für die Eclipse-SUMO-Simulationshilfe">
</p>

# <img src="docs/assets/app-logo.png" width="42" alt="Anwendungssymbol"> Simulationshelfer-Fähigkeit für Eclipse SUMO

<div align="center">

**Hinterfragen. Planen. Aufbauen. Korrigieren. Prüfen. Berichten.**

**Der vollständige SUMO/TraCI-Experimentablauf, geführt von Codex und Claude.**

<img src="https://img.shields.io/badge/SUMO%2FTraCI-Signalsteuerung-blue" alt="SUMO/TraCI-Signalsteuerung">
<img src="https://img.shields.io/badge/Assistent-Codex%2FClaude-6f42c1" alt="Codex und Claude">
<img src="https://img.shields.io/badge/F%C3%A4higkeitsdateien-2-1d8e57" alt="Zwei Fähigkeitsdateien">
<img src="https://img.shields.io/badge/Referenzmodule-12-c98a05" alt="Zwoelf Referenzmodule">

<a href="https://tarard.github.io/Simulation-Helper-Skill-for-Eclipse-SUMO/"><strong>Webseite</strong></a> |
<a href="examples/01_fixed_time_audit/task.md"><strong>Beispiele</strong></a> |
<a href="docs/common-sumo-signal-control-failures.md"><strong>Fehlerliste</strong></a> |
<a href="LICENSE-DOCS"><strong>CC BY 4.0</strong></a>

[Englische Fassung](README.md) | [Vereinfachtes Chinesisch](README.zh-CN.md) | [Deutsch](README.de.md)

</div>

> [!IMPORTANT]
> Der aktuelle Umfang konzentriert sich auf **SUMO/TraCI-Experimente zur Verkehrssignalsteuerung**. Dies ist noch kein allgemeines Prüfpaket für alle Anwendungsfälle von Eclipse SUMO.

> [!NOTE]
> Dies ist eine unabhängige akademische Arbeitsablauf-Ressource. Sie ist nicht mit der Eclipse Foundation, dem Eclipse-SUMO-Projekt oder DLR verbunden und wird von diesen nicht unterstützt, gesponsert oder gepflegt.

## 🔥 Warum es existiert

SUMO kann ohne Absturz laufen, während das Experiment trotzdem keine belastbare Evidenz liefert.

Diese Fähigkeit zielt auf Fehler, die oft erst spät sichtbar werden:

- Routen oder Nachfrage unterscheiden sich still zwischen Vergleichsverfahren
- TLS-Phasenindizes passen nicht zu den beabsichtigten Fahrbeziehungen
- `tripinfo`, `summary` oder `edgeData` fehlen oder werden überschrieben
- Steuerungsvergleiche sind nicht nach Zufallssaat, Simulationshorizont, Nachfrage und Ausgaben gepaart
- Simulationen stoppen, bevor die Nachfrage vollständig abgearbeitet ist
- Nur angekommene Fahrzeuge werden ausgewertet, unfertige Fahrzeuge verschwinden aus der Metrik
- Aussagen im Aufsatz oder Bericht sind stärker als die Evidenz

## 🧠 Was es macht

```text
Was es ist:       Eine wiederverwendbare SUMO-Fähigkeit für Codex und Claude, fokussiert auf den vollständigen SUMO/TraCI-Signalsteuerungsversuchsablauf.
Für wen:          Forschende, die Eclipse SUMO für Festzeitsteuerung, verkehrsabhängige Steuerung, Maximaldrucksteuerung, NEMA, datengestützte Steuerung oder MPC-nahe Steuerungen nutzen.
Wie es arbeitet:  Eine kompakte SKILL.md dient als Szenario-Router und lädt fokussierte Referenzmodule nur bei Bedarf.
Woher es kommt:   Offizielle SUMO-Dokumentation, SUMO-Häufige-Fragen und Forumserfahrungen, Muster aus öffentlichem Verkehrssimulationsquelltext und eigene Experimentpraxis des Autors.
Was es findet:    Fehlerhafte Routen, unsichere TLS-Phasen, ungepaarte Vergleichsverfahren, überschriebene Ausgaben, ungültige Metriken und nicht reproduzierbare Versuchsreihen.
```

Das Paket ist bewusst noch kein Python-Prüfer. Es ist ein **Ablaufprotokoll und eine Assistentenfähigkeit**: Kopieren Sie es in Codex oder Claude, richten Sie es auf ein SUMO-Experimentverzeichnis und nutzen Sie die strukturierten Prüfungen, um Planung, Korrektur, Verifikation und Bericht mit klaren Evidenzgrenzen zu verbinden.

## ⚡ Schnellstart

Für **Codex** kopieren Sie die Fähigkeitsordner in ein projektspezifisches Fähigkeitsverzeichnis:

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

Rufen Sie die Fähigkeit dann im Assistenten auf:

```text
Verwende $simulation-helper-skill-for-eclipse-sumo, um dieses SUMO/TraCI-Verkehrssignalexperiment zu prüfen, bevor ich Ergebnisse berichte.
```

Für einen fehlgeschlagenen oder verdächtigen Lauf:

```text
Verwende $debugging-helper-skill-for-eclipse-sumo, um zu diagnostizieren, warum dieser SUMO/TraCI-Lauf ungültig oder nicht reproduzierbar ist.
```

Die Fähigkeit sollte zuerst fehlende Experimentdetails erfragen. Dass SUMO ohne Absturz läuft, bedeutet noch nicht, dass die Ergebnisse belastbar sind.

## 🧩 Enthaltene Fähigkeiten

| Fähigkeit | Wann nutzen | Hauptausgaben |
|---|---|---|
| `simulation-helper-skill-for-eclipse-sumo` | Planung, Prüfung, Vergleich, Quelltextänderungen, Veröffentlichungsprüfung und evidenzbegrenzte Aussagen für SUMO/TraCI-Signalsteuerungsexperimente. | Projekt-Kontrollprüfung, Experimentbereitschaftsprotokoll, SUMO-Experimentplan, Evidenzklasse, Aussagengrenze, nächster Schritt. |
| `debugging-helper-skill-for-eclipse-sumo` | SUMO/TraCI-Routen-, Nachfrage-, Detektor-, TLS-, Ausgabe-, Zufallssaat-, Fertigstellungs-, Reproduzierbarkeits- oder Laufzeitfehler. | Fehlerklasse, nächste Diagnoseprüfung, Evidenz, Entscheidung über Reparatur, Wiederholung oder Abstufung. |

Beide `SKILL.md`-Dateien bleiben bewusst schlank. Der Assistent klassifiziert zuerst das Szenario und lädt dann nur die relevanten Referenzmodule.

## 🗺️ Szenario-Router

| Szenario | Laden | Erwartete Ausgabe |
|---|---|---|
| Neue Maschine, frischer Klon, fehlender SUMO-Nachweis oder unsichere Umgebung | `preflight-sumo-environment.md` | Umgebungsvorprüfung und Bestehen/Fehlschlag des Rauchtests |
| OSM-/importierte Netze, Wahl der Netztiefe, Google-Maps/externe Signalprüfung, Detektorabbildung oder Felddatenabgleich | `model-osm-detectors.md` | Modellierungsplan, Straßenklassenleiter, TLS-Prüfung, Detektorabgleich und Visualisierungsgrenze |
| Laufendes Projekt, unklarer Fortschritt oder unklarer nächster Schritt | `route-project-workflow.md` | Projekt-Kontrollprüfung und Plan für den nächsten Schritt |
| Neues oder vages Experiment | `plan-experiment.md` | Experimentbereitschaftsprotokoll, danach SUMO-Experimentplan |
| Fehlgeschlagener oder verdächtiger Lauf | `debugging-helper-skill-for-eclipse-sumo` | Ursache, nächste Prüfung, Reparatur/Wiederholung/Abstufung |
| Änderung an Steuerung, Auswerter, Laufskript, Prüfer oder Prüfquelltext | `develop-and-verify-code.md` | Rot/Grün/Überarbeitung oder expliziter `test-after`-Eintrag |
| Steuerungs-, TLS-, NEMA- oder TraCI-Grenzfrage | `audit-sumo-controllers.md` | Steuerungsidentität, API-Grenze und fehlende Evidenz |
| Fest begrenzte Korridorstörung oder Vergleich von Steuerungsinformation | `compare-corridor-perturbations.md` | gepaarte Störungslogik, negative Kontrollen und Aussagegrenze |
| SUMO-Semantik, offizielle/Forum-Lehren oder Muster aus öffentlichem Code | `learn-sumo-knowledge.md` | quellengebundene Lehre und nötige Evidenz |
| Ergebnisse, Metriken, Vergleichsverfahren oder Aufsatz-/Berichtsaussage | `evaluate-and-report-results.md` | Evidenzklasse und erlaubte/verbotene Formulierungen |
| Nutzer findet eine Lösung, die die Fähigkeit verfehlt hat | `capture-field-lesson.md` | Datenschutzfreundlicher Kandidat für eine Felderfahrung |
| Prüfung vor öffentlicher Veröffentlichung | `release-project.md` | Veröffentlichungsliste und Restrisiko |

## 🔗 Fähigkeitsstruktur

Das Paket nutzt eine Struktur aus kompaktem Einstiegspunkt und vertiefenden Referenzen. `SKILL.md` bleibt kurz genug, damit Codex und Claude es schnell laden können; fokussierte Referenzdateien tragen den detaillierten SUMO/TraCI-Versuchsablauf.

```text
skills/
├─ simulation-helper-skill-for-eclipse-sumo/      # Hauptfähigkeit für den Ablauf
│  ├─ SKILL.md                                    # Szenario-Router und Aktivierungsregeln
│  │  ├─ wann diese Fähigkeit genutzt wird
│  │  ├─ Hinterfragen -> Planen -> Aufbauen -> Korrigieren -> Prüfen -> Berichten
│  │  ├─ erforderliche Ausgaben und Aussagegrenzen
│  │  └─ Links zu fokussierten Referenzen
│  ├─ agents/
│  │  └─ openai.yaml                             # Codex/OpenAI-Metadaten
│  └─ references/                                # Vertiefende Ablaufdokumentation
│     ├─ route-project-workflow.md               # Szenario-Routing und Projektzustand
│     ├─ preflight-sumo-environment.md           # Nachweis der SUMO/Python-Werkzeugkette
│     ├─ plan-experiment.md                      # Sokratische Vorabklärung und SUMO-Versuchsplan
│     ├─ develop-and-verify-code.md              # Rot/Grün/Überarbeitung und Abschlussevidenz
│     ├─ model-osm-detectors.md                  # OSM/importierte Netze, Signalprüfung und Detektorabgleich
│     ├─ learn-sumo-knowledge.md                 # Offizielle, Forum- und öffentliche Code-Lehren
│     ├─ audit-sumo-controllers.md               # NEMA/TLS/TraCI-Steuerungsgrenzen
│     ├─ compare-corridor-perturbations.md       # Fest begrenzte Störungsvergleiche
│     ├─ evaluate-and-report-results.md          # Ausgaben, Metriken, Vergleich und Aussagen
│     ├─ capture-field-lesson.md                 # Selbsterweiternde Felderfahrung
│     └─ release-project.md                      # Veröffentlichung, Marke, Datenschutz, Sichtbarkeit
│
├─ debugging-helper-skill-for-eclipse-sumo/       # Fokussierte Fehlersuchfähigkeit
│  ├─ SKILL.md                                    # Aktivierung und Ablauf der Fehlersuche
│  ├─ agents/openai.yaml                          # Codex/OpenAI-Metadaten
│  └─ references/
│     └─ debug-sumo-traci.md                      # Beobachten, klassifizieren, prüfen, abstufen
│
└─ examples/                                      # Direkt nutzbare Prüfszenarien
   ├─ 01_fixed_time_audit/
   ├─ 02_max_pressure_audit/
   └─ 03_data_informed_signal_control_audit/
```

<details>
<summary><strong>Referenzmodule für die Simulationshilfe</strong></summary>

- [`route-project-workflow.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/route-project-workflow.md) - Szenario-Routing und Prüfung des Projektzustands.
- [`preflight-sumo-environment.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/preflight-sumo-environment.md) - Nachweis der SUMO/Python-Umgebung und minimale Rauchtest-Grenze.
- [`plan-experiment.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/plan-experiment.md) - sokratische Vorabklärung, Experimentbereitschaftsprotokoll und bestätigter SUMO-Versuchsplan.
- [`develop-and-verify-code.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/develop-and-verify-code.md) - Rot -> Grün -> Überarbeitung und Abschlussevidenz für SUMO/TraCI-Quelltextänderungen.
- [`model-osm-detectors.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/model-osm-detectors.md) - OSM/importierte Netzmodellierung, Wahl der Netztiefe, Google-Maps/externe Signalprüfung, redundante TLS-Bereinigung, Detektorabbildung und Felddatenabgleich.
- [`learn-sumo-knowledge.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/learn-sumo-knowledge.md) - Quellenhierarchie, offizielle Semantik, Forum-Lehren und Muster aus öffentlichem Code.
- [`audit-sumo-controllers.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/audit-sumo-controllers.md) - Identität und API-Grenzen von NEMA/TLS/TraCI-Steuerungen.
- [`compare-corridor-perturbations.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/compare-corridor-perturbations.md) - fest begrenzte Störungsvergleiche, Informationskontrollen und Aussagegrenzen.
- [`evaluate-and-report-results.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/evaluate-and-report-results.md) - Ausgaben, Metriken, Fertigstellung, Vergleichsverfahren, Validierung und Aussageformulierung.
- [`capture-field-lesson.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/capture-field-lesson.md) - datenschutzfreundliche Abstraktion von Nutzerlösungen.
- [`release-project.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/release-project.md) - Veröffentlichung, Marke, Datenschutz und Sichtbarkeitsprüfung.

</details>

<details>
<summary><strong>Referenzmodule für die Fehlersuche</strong></summary>

- [`debug-sumo-traci.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/debug-sumo-traci.md) - geschlossene Diagnose, Symptomprüfungen und Regeln zur Aussageabstufung.

</details>

## 🧪 Beispiele

Jedes Beispiel kann direkt als Aufforderung verwendet werden:

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
Verwende $simulation-helper-skill-for-eclipse-sumo für examples/02_max_pressure_audit/task.md und erstelle einen evidenzbegrenzten Prüfbericht.
```

## ✅ Was geprüft wird

- Netz, Routen, Konfigurationen, Detektoren und Zusatzdateien
- TLS-Phase, freigegebene Fahrbeziehungen, Gelbzeit, Alles-Rot und NEMA-Evidenz
- gepaarte Zufallssaaten, Nachfrage, Ausgaben, Simulationshorizonte und Vergleichsverfahren
- `tripinfo`, `summary`, `edgeData`, TLS-Schaltausgabe, Steuerungsprotokolle, Warnungen, Fahrzeugteleportationen und unfertige Fahrzeuge
- Reisezeit, Verzögerung, Halte, Durchsatz, Warteschlange, Emissionen, Fairness und fertigstellungsbewusste Berichterstattung
- Festzeitsteuerung, verkehrsabhängige Steuerung, Maximaldrucksteuerung, NEMA, datengestützte Steuerung und MPC-nahe Steuerungsvergleiche
- testgetriebene Einträge für SUMO/TraCI-Steuerungen, Metrikauswerter, Laufskripte, Prüfer und Prüfquelltextänderungen
- Feldlektionen aus Nutzerlösungen, die zu wiederverwendbarer Anleitung werden können

Siehe [`docs/common-sumo-signal-control-failures.md`](docs/common-sumo-signal-control-failures.md) für eine längere Fehlerliste.

## 🛠️ Designprinzipien

- **Schrittweise Offenlegung:** `SKILL.md` bleibt kompakt und verweist nur bei Bedarf auf fokussierte Referenzen.
- **Sokratische Vorabklärung:** Unklare Experimente werden vor der Ausführung in ein Experimentbereitschaftsprotokoll überführt.
- **Tests vor Experimentquelltext:** Verhaltensändernder Quelltext beginnt nach Möglichkeit mit einem fehlschlagenden Test oder einer reproduzierbaren Prüfung.
- **Harte Grenzen vor Aussagen:** Ausgaben, Warnungen, Fertigstellung und Paarung der Vergleichsverfahren müssen die Aussage tragen.
- **Evidenz vor Abschlussbehauptung:** Keine Abschlussbehauptung ohne frische Befehle, Artefakte, Tests und Restrisiko.
- **Fehlersuche als geschlossener Regelkreis:** beobachten -> klassifizieren -> prüfen -> vergleichen -> aktualisieren.
- **Selbstentwicklung:** Nicht abgedeckte reale Lösungen können zu datenschutzfreundlichen Felderfahrungs-Kandidaten werden.

## 🧭 Projektstatus

Aktuelle Version: **reines Instruktions- und Checklistenpaket**.

Dieses Projektarchiv enthält Markdown-basierte Assistentenfähigkeiten, Prüflisten, Beispiele, Dokumentation und Veröffentlichungsmaterialien. Es enthält noch keine ausführbaren SUMO-Prüfer oder Python-Prüfskripte.

### Entwicklungspfad

- Abdeckung der Signalsteuerungsprüfung weiter verbessern
- mehr Fehlerfall-/Reparaturfall-Beispiele ergänzen
- optionale Python-Prüfer hinzufügen, sobald Muster stabil sind
- später weitere SUMO-Domänen abdecken, etwa Routen und Nachfrage, Emissionen und Energie, öffentlicher Verkehr, Fußgänger- und Mehrmodal-Szenarien, automatisiertes und vernetztes Fahren mit Kopplungssimulation, Kalibrierung, Sicherheitsanalyse und Vergleich von Simulationsmodi

## ❓ Häufige Fragen

**Muss ich die Fähigkeit manuell aufrufen?**

Meist ja. Nutzen Sie `$simulation-helper-skill-for-eclipse-sumo`, wenn der Prüfpfad explizit verwendet werden soll.

**Zertifiziert die Fähigkeit mein SUMO-Experiment?**

Nein. Sie bietet Prüfunterstützung, keine formale Verifikation und keine offizielle Zertifizierung.

**Warum ist `SKILL.md` kurz gehalten?**

Weil Assistenten begrenzten Kontext haben. Die Fähigkeit soll zu den passenden Evidenzregeln routen, statt alle Prüflisten gleichzeitig zu laden.

**Kann sie fehlgeschlagene SUMO-Läufe untersuchen?**

Ja. Für Routen-, TraCI-, TLS-, Ausgabe-, Zufallssaat-, Fertigstellungs- und Reproduzierbarkeitsfehler nutzen Sie `$debugging-helper-skill-for-eclipse-sumo`.

**Kann sie aus später gefundenen Nutzerlösungen lernen?**

Ja. Der Felderfahrungsablauf abstrahiert einen wiederverwendbaren Diagnosepfad, entfernt private Details und fragt vor jeder dauerhaften Aktualisierung nach.

## ⚠️ Grenzen

Dieses Projektarchiv stellt Assistentenanweisungen, Prüflisten und Prüfverfahren bereit. Es zertifiziert nicht, dass ein SUMO-Experiment korrekt ist.

Die Fähigkeiten ersetzen keine manuelle Prüfung, SUMO-Dokumentation, steuerungsspezifische Validierung oder unabhängige Reproduktion. Die Prüfausgabe ist Prüfunterstützung, kein formales Verifikationsergebnis.

## ™️ Markenhinweis

Eclipse SUMO ist eine Marke der Eclipse Foundation. Dieses Projekt ist unabhängig und nicht mit der Eclipse Foundation, dem Eclipse-SUMO-Projekt oder DLR verbunden, unterstützt, gesponsert oder gepflegt.

Dieses Projekt unterstützt akademische und forschungsbezogene Arbeitsabläufe für Experimente mit Eclipse SUMO. Es verwendet keine offiziellen Eclipse- oder Eclipse-SUMO-Logos.

## 📚 Eclipse SUMO zitieren

Wenn Ihre Forschung SUMO verwendet, zitieren Sie die vom SUMO-Projekt empfohlene offizielle Referenz:

- Pablo Alvarez Lopez, Michael Behrisch, Laura Bieker-Walz, Jakob Erdmann, Yun-Pang Floetteroed, Robert Hilbrich, Leonhard Luecken, Johannes Rummel, Peter Wagner, and Evamarie Wiessner. "Microscopic Traffic Simulation using SUMO." IEEE Intelligent Transportation Systems Conference, 2018. DOI: `10.1109/ITSC.2018.8569938`.

Die Eclipse-SUMO-Übersichtsseite weist außerdem darauf hin, dass seit SUMO 1.2.0 versionsspezifische DOI bereitgestellt werden.

## 📄 Lizenz

Die Fähigkeitsdateien, Dokumentation, Prüflisten und Protokolltexte in diesem Projektarchiv stehen unter Creative Commons Attribution 4.0 International (`CC BY 4.0`). Siehe [`LICENSE-DOCS`](LICENSE-DOCS).

Falls spätere Versionen Python-Prüfskripte oder anderen Quelltext ergänzen, sollte eine separate Quelltextlizenz wie MIT hinzugefügt und klar zwischen `LICENSE-CODE` und `LICENSE-DOCS` unterschieden werden.

## 🔗 Referenzen und verwandte Ressourcen

Diese Links liefern Kontext. Sie bedeuten keine Unterstützung dieses Projektarchivs.

- Eclipse-SUMO-Dokumentation und Lizenzseiten: [Eclipse-SUMO-Überblick](https://eclipse.dev/sumo/about/), [SUMO-Häufige-Fragen](https://sumo.dlr.de/docs/FAQ.html) und [SUMO-Download- und Lizenzhinweise](https://sumo.dlr.de/docs/Downloads.html).
- Markenrichtlinie der Eclipse Foundation: [Markenrichtlinie der Eclipse Foundation](https://www.eclipse.org/legal/logo-guidelines/).
- Öffentliche Beispiele und Konventionen für Assistentenfähigkeiten: [öffentliches Anthropic-Fähigkeitenarchiv](https://github.com/anthropics/skills).

## ⭐ Unterstützung

Wenn diese Prüfliste hilft, ein fehlerhaftes SUMO/TraCI-Experiment zu vermeiden, geben Sie dem Projektarchiv einen Stern und passen Sie die Beispiele an den eigenen Forschungsablauf an.

## 🔖 Archiv

Versionierte Veröffentlichungen sind auf Zenodo archiviert: https://doi.org/10.5281/zenodo.20627976

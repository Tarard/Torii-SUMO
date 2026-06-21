<p align="center">
  <img src="docs/assets/banner.png" alt="Torii Agent Plugin fuer SUMO Banner">
</p>

# <img src="docs/assets/app-logo.png" width="42" alt="Torii Logo"> Torii

<div align="center">

**Task-Oriented Road Infrastructure Intelligence**

**Agent plugin for SUMO**

<img src="https://img.shields.io/badge/Agent%20Plugin-Codex%20%2F%20Claude-6f42c1" alt="Agent Plugin fuer Codex und Claude">
<img src="https://img.shields.io/badge/SUMO%2FTraCI-Verkehrssimulation-blue" alt="SUMO und TraCI">
<img src="https://img.shields.io/badge/OSM%20to%20SUMO-Netzbereinigung-1d8e57" alt="OSM zu SUMO Netzbereinigung">
<img src="https://img.shields.io/badge/MCP%20Tools-local%20stdio-c98a05" alt="Lokale stdio MCP Tools">

<a href="https://tarard.github.io/Torii-SUMO/"><strong>Webseite</strong></a> |
<a href="docs/codex-plugin-install.md"><strong>Codex Plugin Installation</strong></a> |
<a href="examples/01_fixed_time_audit/task.md"><strong>Beispiele</strong></a> |
<a href="docs/common-sumo-signal-control-failures.md"><strong>Fehlerliste</strong></a> |
<a href="LICENSE-CODE"><strong>MIT Code</strong></a> |
<a href="LICENSE-DOCS"><strong>CC BY 4.0 Dokumente</strong></a>

[English](README.md) | [简体中文](README.zh-CN.md) | [Deutsch](README.de.md)

</div>

> [!IMPORTANT]
> Torii ist ein Plugin- und Skill-Paket fuer agentische SUMO-Arbeit. Es enthaelt bereits lokale stdio MCP-Werkzeuge fuer Umgebungstests, Konfigurationspruefungen, Smoke Runs, Evidenzpakete, OSM-Cleanup-Hard-Gates, OSM-zu-SUMO-Netzaufbau, TLS-Kandidatenpruefung, mehrquellige TLS-Prueftabellen, Konnektivitaetschecks, Netedit-Startnachweise und Erreichbarkeitsproben. Stille vollstaendige Ortsnamen-Geokodierung, vollstaendige Stadtzertifizierung und Controller-Generierung sind in dieser Version keine fertigen MCP-Werkzeuge.

Torii beginnt jetzt mit einem Workflow Router: `torii_auto_workflow` versteht eine Ein-Satz-Anfrage, waehlt das passende Recipe, stellt nur blockierende Rueckfragen und fuehrt sichere MCP-Schritte aus, sobald genug Evidenz vorhanden ist.

> [!NOTE]
> Dieses Projekt ist unabhaengig. Es ist nicht mit der Eclipse Foundation, dem Eclipse-SUMO-Projekt, DLR, OpenAI, Anthropic, Google oder externen OSM-Werkzeugprojekten verbunden und wird von ihnen nicht unterstuetzt, gesponsert oder gepflegt.

## Was Torii ist

Torii bedeutet **Task-Oriented Road Infrastructure Intelligence**. Es soll einem Coding Agent helfen, in SUMO-Projekten wie ein erfahrenerer Ingenieur zu arbeiten: Ziel verstehen, aktuellen Modellzustand beobachten, schlechte Kennzahlen als Feedback interpretieren und danach die kleinste begruendbare Aenderung vornehmen.

| Ebene | Aufgabe |
|---|---|
| Reasoning layer | Der SUMO Expert Skill versteht die Nutzerabsicht, waehlt den Workflow, fragt nach fehlender Evidenz und erklaert, welches Modellproblem eine schlechte Metrik anzeigen kann. |
| Execution layer | Der lokale MCP Server fuehrt begrenzte Werkzeuge aus und liefert strukturierte Beobachtungen: Dateien, Logs, Warnungen, Metriken, TLS-Kandidaten, Routen und Evidenzpakete. |

Der Standardeinstieg ist `torii_auto_workflow`. Er routet eine natuerliche Anfrage zu OSM-Netzaufbau, TLS-Pruefung, Erreichbarkeit, Diagnose schlechter Laeufe oder Experiment-Audit.

Die Installation von Torii gibt Codex sowohl **skills and MCP tools**. Das Ziel ist nicht, eine einzelne Zahl blind zu optimieren, sondern die Ursache hinter der Zahl zu diagnostizieren.

## Typische Anfragen

| Anfrage | Torii-Verhalten |
|---|---|
| "Ein SUMO-Netz aus diesem OSM-Gebiet bauen." | Nutzt den OSM-Cleanup-Hard-Gate-Workflow: Gebietsbestaetigung bei Bedarf, begrenzter OSM-Import, TLS-Kartenpruefung, Pkw-Netz-Konnektivitaet und Netedit-Startnachweis. |
| "Dieses Dresdner Kernnetz bereinigen." | Bei bbox oder Extract wird der Hard-Gate-Workflow direkt ausgefuehrt. Bei nur einem Ortsnamen erzeugt Torii zuerst einen OSM-Vorschaupunkt und fragt nach Bestaetigung. |
| "Erstelle zuerst eine Google-Maps-Basispruefung fuer diese SUMO-Ampeln und ergaenze OSM, Mapillary, KartaView, amtliches Inventar, Signalplaene und Feldfotos." | SUMO-TLS-Kandidaten extrahieren, Google Maps als Gate fuer aktuelle Netze behalten, mehrquellige Prueffelder erzeugen und fehlende menschliche Bestaetigung melden. |
| "Sind diese Strassen oder Bruecken befahrbar?" | Named-road routeability probes erzeugen und fehlende Kanten, Routenerzeugung und restliches SUMO-Fertigstellungsrisiko berichten. |
| "Die Metriken wurden schlechter." | Metriken als Feedback behandeln und zuerst Routen-, Nachfrage-, Netz-, TLS-, Controller-, Ausgabe-, Horizont- oder Fertigstellungsprobleme diagnostizieren. |
| "Fuege Max-Pressure-Steuerung hinzu." | Mit dem gebuendelten Skill und oeffentlichen Controller-Mustern planen und verifizieren. Vollstaendige Controller-Generierung ist ein Roadmap-Werkzeug. |

## Schnellstart

Installation von GitHub:

```powershell
codex plugin marketplace add Tarard/Torii-SUMO --ref main
codex plugin add torii-sumo@torii-sumo
```

Nach Installation oder Neuinstallation einen neuen Codex-Thread starten, damit Skills und MCP Tools neu erkannt werden.

Lokale Entwicklung:

```powershell
codex plugin marketplace add <path-to-this-repo>
codex plugin add torii-sumo@torii-sumo
```

Skill-only Nutzung bleibt moeglich:

```text
.agents/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

Beispiel:

```text
Use Torii to build and audit this SUMO network. Treat bad metrics as feedback about the model, not as the optimization target itself.
```

Bei MCP-first Nutzung kann `torii_auto_workflow` direkt mit der Ein-Satz-Anfrage und einem Ausgabeordner aufgerufen werden.

## Projektstruktur

```text
plugins/
  torii-sumo/
    .codex-plugin/plugin.json
    .mcp.json
    scripts/run_torii_sumo.py
    src/torii_sumo/
    skills/simulation-helper-skill-for-eclipse-sumo/

skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

Der fruehere `Simulation Helper Skill for Eclipse SUMO` wurde nicht geloescht. Er ist jetzt die Reasoning-Schicht von Torii und wird mit der installierbaren Plugin-Schicht zusammen ausgeliefert.

## Implementierte MCP Tools

| Tool | Aktueller Umfang |
|---|---|
| `torii_auto_workflow` | Eine natuerliche SUMO-Anfrage klassifizieren, ein Workflow-Recipe waehlen, nur blockierende Rueckfragen stellen und sichere MCP-Schritte ausfuehren. |
| `sumo_preflight` / `sumo_get_environment` | SUMO-, Python-, TraCI- und Toolchain-Evidenz pruefen. |
| `sumo_config_pair_preflight` | Fehlende Eingaben und gemeinsame Ausgaben in `.sumocfg`-Paaren pruefen. |
| `sumo_run_config` / `sumo_run_minimal_smoke` | Begrenzte SUMO-Konfiguration oder minimalen Smoke Test ausfuehren. |
| `sumo_compare_outputs` / `sumo_collect_evidence` | Ergebnisse mit Fertigstellung zuerst vergleichen und Evidenzpakete schreiben. |
| `sumo_osm_cleanup_workflow` | High-Level-Workflow fuer OSM-Cleanup mit Gebietsbestaetigung, OSM-Netzaufbau, TLS-Kartenpruefung, Konnektivitaetscheck und Netedit-Startnachweis. |
| `sumo_osm_build_network` | OSM-Download oder Extract-Reuse, Overpass-Kacheln, Retry, XML-Deduplizierung, Strassenfilter und `netconvert`. |
| `sumo_tls_audit` | TLS-Kandidaten extrahieren, Kreuzungsgruppen clustern und Kartenprueffelder ergaenzen. |
| `sumo_tls_multisource_review` | Mehrquellige TLS-Prueftabelle mit OSM, Google Maps, Mapillary, KartaView, amtlichem Inventar, Signalplaenen und Feldevidenz erzeugen. |
| `sumo_network_routeability_probe` | Erreichbarkeitsproben fuer benannte Strassen oder Bruecken erzeugen. |

Die OSM-Architektur nimmt Ideen aus OSMnx, OSMNet, pyrosm, SUMO `osmGet/osmBuild` und osm-to-xodr auf, ohne externen Quelltext zu vendorn.

## Feedback-Diagnose

Torii behandelt schlechte Ergebnisse als Feedback:

```text
Nutzerziel
-> SUMO-Ausgaben, Warnungen, Metriken und Logs
-> Diagnose, welches Problem die Metrik anzeigt
-> wahrscheinlichstes Netz-, Nachfrage-, Routing-, Controller-, Code- oder Versuchsdesignproblem
-> kleinste naechste Aenderung
-> erneute begrenzte Pruefung
```

Niedrige Ankunftsrate kann auf getrennte Routen, Einfuegefehler, zu kurzen Horizont oder blockierende Phasen hinweisen. Hohe Wartezeit kann falsche Phase-Spur-Zuordnung, falsch zusammengelegte TLS, Nachfrage ausserhalb des Modellumfangs oder eine ungeeignete Controller-Politik anzeigen. Teleports sind Feedback, kein Detail zum Verschweigen.

## Grenzen

- SUMO-Netze koennen aus bbox oder Extracts gebaut werden; bei unbestaetigten Ortsnamen blockiert der Workflow. Vollautomatische Ortsnamen-Geokodierung bleibt ein Workflow-Pruefpunkt, kein stiller Konstruktionsschritt.
- Strassenfilter, OSM-Deduplizierung, TLS-Kandidaten, mehrquellige TLS-Pruefartefakte, Konnektivitaetschecks, Erreichbarkeitsproben, Warnungen und Netedit-Startnachweise werden unterstuetzt; ein ganzes Stadtnetz wird nicht automatisch zertifiziert.
- Google Maps bleibt das erforderliche Basis-Gate fuer aktuelle Strassen-/TLS-Bereinigung. OSM-Tags, Mapillary, KartaView, amtliche Inventare, Signalplaene und Feldfotos koennen die Pruefung staerken. Wenn der Nutzer ein historisches Netz verlangt, steuert sein historisches Ziel die Basis und braucht zeitlich passende Evidenz.
- Controller-Implementierung kann anhand oeffentlicher Muster wie SUMO Lights geplant werden; Controller-Generierung und Controller-Log-Inspection sind Roadmap-Werkzeuge.
- Evidenzbegrenzte Aussagen werden unterstuetzt; Experimentkorrektheit wird nicht zertifiziert.

## Lizenz

Quelltext steht unter MIT. Siehe [`LICENSE-CODE`](LICENSE-CODE).

Skills, Dokumentation, Checklisten und Protokolltexte stehen unter Creative Commons Attribution 4.0 International (`CC BY 4.0`). Siehe [`LICENSE-DOCS`](LICENSE-DOCS).

## Markenhinweis

Eclipse SUMO ist eine Marke der Eclipse Foundation. Dieses Projekt unterstuetzt Workflows fuer Experimente mit Eclipse SUMO, ist aber unabhaengig und nutzt keine offiziellen Eclipse- oder Eclipse-SUMO-Logos.

Google Maps wird nur als externe Kartenpruefbasis referenziert. Torii ist nicht mit Google verbunden, und Kartenpruefungen muessen den zeitlichen Modellierungszielen des Nutzers folgen.

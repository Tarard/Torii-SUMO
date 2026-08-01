<p align="center">
  <img src="docs/assets/banner.png" alt="Torii Agent Plugin fuer SUMO Banner">
</p>

# <img src="docs/assets/app-logo.png" width="42" alt="Torii Logo"> Torii

<div align="center">

**Task-Oriented Road Infrastructure Intelligence**

**Agent plugin for SUMO**

<p><strong>Codex / Claude agent plugin</strong> · SUMO/TraCI Workflows · OSM-zu-SUMO Cleanup · lokale MCP Tools</p>

<a href="https://tarard.github.io/Torii-SUMO/"><strong>Webseite</strong></a> |
<a href="docs/codex-plugin-install.md"><strong>Installation</strong></a> |
<a href="examples/01_signal_control_audit/task.md"><strong>Signal-Control Audit</strong></a> |
<a href="examples/02_one_prompt_osm_network/README.md"><strong>One-Prompt Demo</strong></a> |
<a href="LICENSE"><strong>Lizenz</strong></a>

[English](README.md) | [简体中文](README.zh-CN.md) | [Deutsch](README.de.md)

</div>

## Evidence-Aware OSM-to-SUMO Construction

Torii ist fuer SUMO-Netzkonstruktion gedacht: Eine kurze natuerliche Anfrage kann zu einem begrenzten, evidence-aware und reference-comparable OSM-zu-SUMO-Workflow werden, mit Konstruktionsnachweisen, Erreichbarkeitschecks, Review-Artefakten und klarer Aussagegrenze.

Das Plugin startet mit `torii_workflow_run`. Das Tool klassifiziert die Anfrage, fuehrt den gewaehlten Ablauf aus und speichert ein fortsetzbares Evidenzmanifest. `torii_workflow_status` prueft alte Ergebnisse. `torii_auto_workflow` bleibt fuer Kompatibilitaet.

Torii hat zwei Schichten:

| Schicht | Rolle |
|---|---|
| Reasoning layer | SUMO Expert Skills stellen die richtigen Fragen, waehlen einen Workflow und begrenzen Aussagen. |
| Execution layer | Lokale sichere stdio MCP Tools fuehren begrenzte SUMO-Checks aus und liefern strukturierte Beobachtungen. |

Forschungsstand (2026-07-14): Stage 1-M ist **Machine REVIEW_READY**. Dreissig verblindete Held-out-Korridorpakete, der vollstaendige maschinelle Witness-Census, deterministisches Sampling und Provenance sind fuer die menschliche Validierung eingefroren. Das ist weder ein Stage-1-Abschluss noch eine Zertifizierung automatischer Reparaturen oder ein Nachweis, dass beliebige OSM-Netze bereits Expertenqualitaet in NetEdit erreichen. Details stehen im [Stage-1-M-Nachweis](docs/stage1-machine-review-ready-plan.md).

Die Architektur ist in [`ARCHITECTURE.md`](ARCHITECTURE.md) dokumentiert: Router, Planner, Executor und Reviewer.

Aktuelle MCP Tools decken den verwalteten Workflow, die Statuspruefung, den Kompatibilitaets-Router, Umgebungstests, Konfigurations-Preflight, Smoke Runs, Evidenzpakete, OSM-Netzaufbau, TLS-Kandidaten, mehrquellige TLS-Prueftabellen, TLS-Aggregation Review-Varianten, Konnektivitaetschecks, Connected-Core-Extraktion, Erreichbarkeitsproben, completion-aware Routeability Audits, Overlapping-Top-Level-Junction Audits, Reference-Join Audits, Junction-Aggregation Review-Varianten und Netedit-Startnachweise ab.

## Example

Mit diesem Prompt kann Torii getestet werden:

```text
Use Torii to clean the Ingolstadt city-center network from OSM, compare it with the TUM-VT/sumo_ingolstadt cleaned network for the same bbox, and open the cleaned network in Netedit.
```

Dieses Demo nutzt die Ingolstaedter Innenstadt, um zu pruefen, ob ein Torii OSM-derived Workflow besser auditierbar ist und naeher an ein manuell bereinigtes Referenznetz kommt als reiner OSM-Import-Erfolg.

![TUM-bbox-Referenz im Vergleich mit Torii 5.5 TLS-aggregated visual-detail](examples/02_one_prompt_osm_network/assets/tum_vs_torii_5_5_tls_aggregated_overview.png)

| Evidenz | Ergebnis |
|---|---:|
| Torii vehicle core | 2,493 Kanten, 3,045 Spuren, 1,220 Knoten im Vergleichs-bbox nach Connected-Core-Extraktion |
| Torii reference visual-detail | 6,126 Kanten, 6,695 Spuren, 2,997 Knoten im Vergleichs-bbox |
| TUM bereinigter Referenzausschnitt | 3,577 Kanten, 4,955 Spuren, 1,752 Knoten im selben bbox |
| Ampel-Knoten | Torii visual-detail raw 217; TLS-Aggregation Review-Variante 34 vs TUM 29 |
| Verbleibendes Bereinigungsziel | Google-Maps-Pruefung der zusaetzlichen TLS-Kandidaten und wiederverwendbare physische Kreuzungsaggregation |
| Claim status | `diagnostic-demo` |

Siehe [`examples/02_one_prompt_osm_network`](examples/02_one_prompt_osm_network/README.md). Die 5.5-Vergleichsnetze und Screenshots sind dort committed; erzeugte OSM-Extracts, Routen und vollstaendige Logs bleiben rebuild-only Artefakte.

## Quick Start

Installation von GitHub:

```powershell
codex plugin marketplace add Tarard/Torii-SUMO --ref main
codex plugin add torii-sumo@torii-sumo
```

Nach der Installation einen neuen Codex- oder Claude-Code-Thread starten, damit Skills und MCP Tools erkannt werden.

Vollstaendige Anleitung: [Codex Plugin Installation](docs/codex-plugin-install.md).

## What You Can Ask Me

| Prompt | Was Torii tut |
|---|---|
| "Use Torii to clean the Ingolstadt city-center network from OSM and compare it with TUM-VT/sumo_ingolstadt." | Baut aus OSM, prueft Konnektivitaet und Routeability, vergleicht Topologie/TLS-Evidenz mit der Referenz und oeffnet Netedit. |
| "Audit this TraCI signal controller before I compare it with fixed-time or max-pressure." | Prueft Controller-Identitaet, gepaarte demand/seeds/horizon, TLS-Mapping, Ausgaben und Fertigstellung vor jeder Performance-Aussage. |
| "This SUMO run finishes, but tripinfo and summary disagree." | Diagnostiziert Ausgabe-Konsistenz, unfertige Fahrzeuge, Teleports, Routenfehler und Aussagegrenze. |

## Boundaries

Torii baut und auditiert SUMO-Artefakte, zertifiziert ein Modell aber nicht als korrekt.

- OSM-Importe bleiben diagnostisch, bis Strassenumfang, Konnektivitaet, Routeability, TLS-Realitaet und Kartenbaseline-Evidenz geprueft sind.
- `connected-core` Netze sind fuer Smoke Tests nuetzlich, aber verworfene Fragmente und Topologie-Warnungen bleiben Teil der Aussagegrenze.
- Es beweist keine Ampel-Timings, Phasen, demand realism, controller correctness oder vollstaendige Experimentgueltigkeit.

## License and Notices

Torii-Code, Skills, Dokumentation, Beispiele und Protokolltexte stehen einheitlich unter der [Apache License 2.0](LICENSE).

Eclipse SUMO ist eine Marke der Eclipse Foundation. Kartendaten im OSM-Demo sind © OpenStreetMap contributors und unter der Open Database License (ODbL) verfuegbar.

Fruehere skill-only Releases sind auf Zenodo archiviert: https://doi.org/10.5281/zenodo.20627976

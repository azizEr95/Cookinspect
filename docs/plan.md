# Plan und Stand der Neuimplementierung

Einstieg für jede neue Sitzung, auch für Claude Code in einem neuen Kontext. Zuerst `CLAUDE.md` lesen (Regeln, Definitionen), dann diese Datei (was fertig ist, was als Nächstes kommt). Begründungen stehen in `docs/entscheidungen.md`, Abweichungen von Matte und vom alten Cookinspect in `docs/abweichungen.md`, die Einrichtung des Crawl-Nutzers in `docs/crawl-nutzer.md`.

Stand: 2026-10-31, Branch `tcf22-port`, Phase 9 fertig, Phase 10 vorbereitet (Lauf durch die Person steht aus), Phase 11 fertig bis auf die Zahlen im Methodenteil. Nichts gepusht.

## Arbeitsweise (Kurzfassung aus CLAUDE.md)

- Vor jeder Phase: Plan vorschlagen, auf OK warten. Nach jeder Phase anhalten und berichten.
- Kleine Commits pro Phase auf `tcf22-port`. **Nichts pushen ohne Zustimmung.**
- Änderungen an `CLAUDE.md` vor dem Commit zeigen.
- Kein großer Crawl ohne Freigabe; neue Funktionen zuerst an den 10 Test-Domains (`--limit 10 --test`).
- Kein Klicken im Messcode; Klicken nur in Testskripten (`spikes/`, `tests/check_*.py`).

## Übersicht

| Phase | Inhalt | Stand | Commits |
|---|---|---|---|
| 0 | Gerüst, `config.py`, `CLAUDE.md` | fertig | `d50b9a2`, `5da8562` |
| 1 | Spike: Erfassung ohne Erweiterungen → WebDriver BiDi (E1, E2) | fertig | `eeac875`, `919566b` |
| 2 | Browser (BiDi), Metadaten, robots.txt in allen Modi, sicheres Umfeld | fertig | `2bd24d6`, `db3106b` |
| 2b | Vorfilter mit Trichter (Vergleich Matte Tab. II) | fertig | `38868de`, `183e852` |
| 3 | Erfassung aller Kanäle (`capture.py`), Aufräumen | fertig | `a0f0324`, `b4b97a0` |
| 4 | Decoder, GVL der String-Version, CMP-Liste | fertig | `cb2227c`, `226d7e0` |
| 5 | SQLite-Schema, `database.py`, Zusammenführen | fertig | `d850f00`, `f28b406` |
| 6 | Automatischer Modus (V1, Weitergabe vorher, Cookiewall-Heuristik) | fertig | `d76561e` |
| 7 | Halbautomatischer Modus (V2–V4), `run_list.py` als Einstieg | fertig, Test an 2–3 echten Seiten durch die Person offen | siehe `git log` |
| **8** | **Verstoß-Logik und Auswertung** | **als Nächstes** | |
| 9 | Unit-Tests vervollständigen | offen | |
| 10 | Testlauf an 10 GQ3LK-Seiten, beide Modi | offen | |
| 11 | Doku (README, Abweichungen vervollständigen) | offen | |

Restaufwand geschätzt: ca. 24–36 h (8: 11–15, 9: 4–6, 10: 4–6, 11: 3–5).

## Was es schon gibt (Dateien)

| Datei | Aufgabe |
|---|---|
| `config.py` | alle Einstellungen (Chrome-Version, Wartezeiten nach Matte, Pausen, erwartetes Setup, `database_path(purpose)`) |
| `browser.py` | Chrome for Testing 156.0.8078.73 mit BiDi, frisches Profil, sichtbares Fenster |
| `run_metadata.py` | Metadaten jedes Laufs; verweigert echte Läufe ohne `CRAWL_USER`, mit „dirty“ Git, falscher Chrome-Version, nicht `arm64`, IP-Land nicht `DE` |
| `robots.py` | robots.txt: Protego (gecrawlt), urllib und Original-Cookinspect als Vergleich; Ausweichregeln HTTPS→HTTP, ohne www; 429 wie 5xx |
| `page.py` | Laden mit 3 Versuchen, HTTP-Status der Hauptseite, Erkennung von Sperrseiten |
| `prefilter.py` | Vorfilter mit Trichter; `--test` oder `--purpose vorab` bzw. `--purpose messung`; schreibt Datenbank und `tcf_sites.csv` |
| `capture.py` | Kanäle: 1 Listener (Preload-Skript, `removeEventListener`), 2 fremdes iframe, Cookies/localStorage, Requests (GET/POST, Formulare, OpenRTB); `mark()` + `wait_for_event(..., after=mark)` |
| `decode/tcstring.mjs`, `decode/cli.mjs`, `decoder.py` | Decoder „TC-String rein, IDs als JSON raus“ (`@iabtechlabtcf/core` 1.5.22), Prüfungen pro String |
| `consent_lists.py` | GVL nach `vendorListVersion` des Strings (v3/v2-Archiv), CMP-Liste pro Lauf, Prüfung der CMP-ID |
| `schema.sql`, `database.py` | SQLite, nur Einfügen (Trigger), alle IDs in `tc_string_entry`; Datei pro Zweck |
| `merge_databases.py` | Dateien beider Personen zusammenführen; warnt bei zwei Vorfilter-Messläufen |
| `split_sites.py` | Aufteilung der TCF-Seiten auf zwei Personen (`site_assignment.csv`) |
| `automatic.py` | automatischer Modus: 2 Sitzungen, Snapshot „vorher“ nach Laden + 3 s |
| `cookiewall.py` | Cookiewall-**Heuristik** (Zustimmen + Bezahlen im Dialog, contentpass) |
| `semi_automatic.py` | halbautomatischer Modus: Anleitung nach Anhang D, Codes, Label, Bildschirmfotos, blinde Gegenprüfung, Fortsetzen |
| `run_list.py` | gemeinsamer Einstieg: `run_list.py prefilter` bzw. `automatic` bzw. `semi-automatic` |
| `tests/` | 81 Unit-Tests (`venv/bin/python -m pytest -q`); Live-Prüfungen `check_capture.py` (lokaler Prüfstand), `check_capture_real.py` |

`extract_results.py` ist entfernt (ersetzt durch `evaluate.py`). README ist veraltet (PostgreSQL, `run.sh`).

## Phase 7: halbautomatischer Modus (fertig)

`semi_automatic.py` (auch über `run_list.py semi-automatic`). Ablauf je Code: `r` Ablehnen-, dann Akzeptieren-Sitzung; `n`/`w` nur Akzeptieren in der ersten Sitzung; `b` (kein Banner nach 3-mal Neuladen) und `x` keine weitere Sitzung. Label: Code (`w` nur ohne kostenloses Ablehnen, sonst `r`), Bezahl-Option `cookiewall_seen` (unabhängig vom Code), Ebene (V2), `settings_layer_available`, V3 Zwecke/Vendoren, Text der Schließen-Schaltfläche, Notiz; 10-s-Timer („t“) für die Datenschutzerklärung. Reihenfolge (seit dem ersten Test an t-online.de, 2026-10-31): Die Fragen zum Banner (2. Ebene, V3, Bezahl-Option, kostenloses Ablehnen und Ebene) kommen, solange das Banner zu sehen ist; das Werkzeug schlägt daraus den Code vor, die Person bestätigt oder ändert ihn. Nach dem Klick wird die Sitzung sofort gespeichert und der Browser geschlossen; danach nur noch Schaltflächentext und Notiz. chromedriver ist auf `config.CHROME_VERSION` festgelegt (vorher nahm Selenium Manager .80). Bildschirmfotos vor der Aktion und nach dem Schließen. Gegenprüfung blind (`--role crosscheck`, CSV mit `examination_id`), nicht durch dieselbe Person. Fertige Seiten werden beim nächsten Start übersprungen. Geprüft mit `tests/check_semi_automatic.py` am lokalen Prüfstand; **Test an 2–3 echten Seiten macht die Person selbst** (`lists/test_semi_automatic.txt`).

## Phase 8: Verstoß-Logik und Auswertung (fertig)

Umgesetzt: `site_data.py` (Datenbank → Dicts pro Seite; Rangfolge: Korrektur ersetzt die korrigierte Prüfung, Neuprüfung ersetzt alle früheren, sonst das mildere Ergebnis von erster Prüfung und Gegenprüfung, getrennt für V2 und V4; mehrere erste Prüfungen: die jüngste, mit Warnung), `violations.py` (austauschbare Funktionen, Ergebnis „ja“/„nein“/„nicht auswertbar“ mit Grund), `evaluate.py` (`run_list.py evaluate`: `sites.csv`, `tables.md`, `tables.json` mit Tab. II, Tab. III samt Zuordnung zu Matte, Details), `crosscheck.py` (`select`: Auswahl nach V-C getrennt für V4 und V2, CSV pro Person ohne Hinweis auf das erste Ergebnis, Schlüssel in `selection.json`; `evaluate`: Vergleich und `recheck.csv`). Hauptzahl Kanal 1, Variante „Matte-Kanäle“; V4 auf den Snapshots nach dem Reload, direkt nach der Aktion getrennt. Mit `data/test.sqlite` geprüft (Vorfilter 10 Domains, automatisch und halbautomatisch t-online, amazon, bild). Unit-Tests: `tests/test_violations.py`, `tests/test_database.py`.

Vorgaben (Stand vor der Umsetzung):


Austauschbare Funktionen bzw. Views über der Datenbank, nichts wird als Ergebnis gespeichert. Definitionen in CLAUDE.md, Abschnitt „Definitionen der Verstöße“. Beispielabfrage V4 streng: `tests/test_database.py`.

- V1: nur wenn **beide** Vorher-Snapshots ≥ 1 Zweck in `purpose_consent` zeigen; Matte-Variante (≥ 1 Zweck und ≥ 1 Vendor) getrennt.
- V2: Ablehnen 1. Ebene / nur 2. Ebene / gar nicht.
- V3: Nenner = Seiten mit 2. Ebene (`settings_layer_available`); Zwecke und Vendoren getrennt.
- V4: streng (nur auswertbar, wenn Zwecke nach Akzeptieren nicht leer), Matte-Variante (streng + ≥ 1 Vendor), locker; Zusatzzahlen {1…10}, {1…11}. Nenner ohne `n`, `b`, `x`.
- V4 bei leerem Snapshot direkt nach der Aktion: Snapshot nach dem Reload nehmen und markieren. Fall amazon.de (Test 2026-10-31): `__tcfapi` liefert vorher und direkt nach Ablehnen/Akzeptieren nur leeres tcData, kein `useractioncomplete`; erst nach dem Reload ein TC-String (nach Ablehnen keine Zwecke, nach Akzeptieren 1, 2, 4, 7, 9, 10 mit 102 Vendoren).
- Rangfolge der Prüfungen: Korrektur ersetzt die korrigierte Prüfung, Neuprüfung alle früheren; bei Abweichung in der Gegenprüfung das mildere Ergebnis und alle Seiten der CMP neu prüfen.
- Berechtigtes Interesse nach Ablehnen getrennt, v. a. Zwecke 3–6 (nicht als V4).
- Weitergabe an Dritte: TC-Strings mit Zustimmung in Requests an Dritte, (a) vor jeder Aktion, (b) nach Ablehnen.
- Quote „nicht messbar“ für Kanal 2 pro Phase (vorher, nach Ablehnen, nach Akzeptieren).
- Cookiewalls: Umgang mit `w` konfigurierbar („ausschließen“ / „als V2 zählen“), **beide Varianten ausweisen**.
- Vorgemerkt:
  - **E5:** Vendor-Consents außerhalb von `vendor_disclosed` (nur Strings mit disclosedVendors; v2.2-Strings „nicht auswertbar“); dazu Vendoren, die in der GVL des Strings fehlen (wie Matte Anhang F).
  - **E6:** Cookiewall-Heuristik gegen `cookiewall_seen` (und getrennt gegen `w`): Vierfeldertafel, Übereinstimmung, Präzision, Trefferquote, Liste der Abweichungen.
  - **Vendor-LI bei Vendoren mit nur Special Purposes** (laut GVL des Strings) getrennt zählen, nicht als berechtigtes Interesse; Bit nach dem 1. März 2026 noch gesetzt = alter Umweg (siehe `docs/abweichungen.md`).
  - Strings mit `policy_version_outdated`, `disclosed_vendors_missing_after_v23_deadline`, ungültiger CMP-ID ausweisen.
  - Sperren (`blocked`) und `empty_tc_data` zählen.
  - **E7:** TCF-API ohne TC-String (z. B. amazon.de) bei V1 als „nicht auswertbar“ getrennt ausweisen, nicht als „kein Verstoß“.
- Trichter und Vergleich mit Matte Tab. II/III; Spalte Original-Cookinspect für Tab. II maßgeblich.
- Alte `extract_results.py` ersetzen (erledigt in Phase 8: `evaluate.py`).

## Phase 9: Unit-Tests (fertig)

Vorhanden: 137 Tests. Offene Liste aus dem Plan vor Phase 8 (Stand 81 Tests), mit Stand:

- [x] Verstoß-Funktionen aus Phase 8 mit den Test-Strings aus `tests/tc_fixtures.json` (`decode/fixtures.mjs`): `tests/test_violations_fixtures.py` nutzt `no_consent`, `purposes_1_10`, `all_purposes`, `all_purposes_no_vendors`, `li_only`, `li_forbidden_3_to_6`, `without_disclosed_vendors`, `policy_version_3` (dekodiert und gespeichert wie im Crawl); dazu `tests/test_violations.py` mit selbst gebauten Daten.
- [x] Halbautomatischer Ablauf ohne Browser (Labels, Rollen, Korrekturen): Labels und Code-Vorschlag in `tests/test_semi_automatic.py`; Rollen, Korrektur, Neuprüfung, Gegenprüfung (mildere Einstufung pro Verstoßart, gemischter Fall) in `tests/test_violations.py`.
- [x] Varianten für `w`: V2 ausgeschlossen / als V2, V3-Zusatzzeile (`tests/test_violations.py`).

Dazu in Phase 9:

- [x] Ausgabedateien von `evaluate.py` (`sites.csv`, `tables.json`, `tables.md`): `tests/test_database.py`.
- [x] `crosscheck.py select`: eine Datei pro prüfender Person, nur Seiten der anderen Person, kein Hinweis auf das erste Ergebnis, Schlüssel in `selection.json`: `tests/test_violations.py`.

## Phase 10: Testlauf

10 Seiten aus GQ3LK in beiden Modi, Ergebnis prüfen (Bildschirmfotos der Banner als Kontrolle). Kein großer Lauf ohne Freigabe.

Vorbereitet (2026-10-31): Die Mini-CMP am Prüfstand erzeugt mit `?verstoss=v2n|v4streng|v4matte|v4locker` gezielt Verstöße; `lists/pruefstand_gegenpruefung.csv` hat sechs Testseiten dafür. `tests/check_crosscheck_flow.py` spielt die Gegenprüfung mit Klicks aus dem Testskript durch (erste Prüfung → `select` → blinde Prüfung xy → `evaluate` → `recheck` → Auswertung); Lauf am 2026-10-31 ohne Fehler. Offen: der Lauf durch die Person (10 Seiten automatisch, die 5 TCF-Seiten halbautomatisch, Gegenprüfung am Prüfstand).

## Phase 11: Doku

README neu (Einrichtung, alle Befehle, Ablauf mit zwei Macs, Regel für die blinde Gegenprüfung): fertig. `docs/abweichungen.md` vervollständigt (F1–F8 und Abweichungen Paper ↔ Code, gegen 948a85f geprüft). Methodenteil: Entwurf in `docs/methodenteil.md`, Platzhalter für Zahlen, Zeitraum, Standort und Versionen.

## Offene Punkte außerhalb der Phasen

- Crawl-Nutzer auf beiden Macs einrichten, `CRAWL_USER` setzen und committen (`docs/crawl-nutzer.md`). Danach Vorab-Lauf des Vorfilters starten (macht der Nutzer selbst).
- Cookiewalls: Nach dem Vorab-Lauf entscheiden, ob die Forschungsfrage erweitert wird. Im Test waren 4 von 5 TCF-Seiten Pay-or-OK; der Umgang mit `w` prägt V2–V4 stark.
- Lizenz von Cookinspect mit Matte klären (keine Lizenzdatei) vor einer Veröffentlichung.
- E4: Cookie Glasses (GPLv3) auf TCF v2.2/v2.3 erweitern, mit kurzem Nutzertest (5–10 Personen); vorgezogen auf „nach Phase 8 und Vorab-Lauf“, Details offen. Decoder ist dafür eigenständig gebaut.

## Wichtige Befunde bisher

- Kanal 2 ist fast nie messbar (vor der Wahl nur wetteronline.de mit fremdem iframe).
- amazon.de (CMP 376) liefert leeres `tcData` (`empty_tc_data`), eigener Banner mit „Ablehnen“.
- mobile.de sperrt per Akamai Bot Manager (Status 200, leere Seite).
- google.de: urllib verbietet wegen `Disallow: /?` → `/` (Normalisierung), Protego erlaubt.
- `tcfPolicyVersion` 5 = TCF-Policies 5.0 (2024), nicht v2.2/v2.3; v2.3 erkennt man nur am Segment disclosedVendors.
- Alle 5 TCF-Test-Seiten: v2.3-Strings, vor der Wahl 0 Zwecke, 0 Vendoren.

## Befehle

```sh
venv/bin/python -m pytest -q                                   # Unit-Tests
venv/bin/python run_metadata.py                                # Setup prüfen
venv/bin/python prefilter.py lists/tranco_GQ3LK_de_top1000.csv --limit 10 --test
venv/bin/python automatic.py lists/tranco_GQ3LK_de_top1000.csv --limit 10 --test
venv/bin/python tests/check_capture.py                         # lokaler Prüfstand
venv/bin/python tests/check_capture_real.py t-online.de bild.de
sqlite3 -header -column data/test.sqlite "SELECT * FROM run;"
```

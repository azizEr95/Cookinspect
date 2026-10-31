# Cookinspect (TCF v2.2/v2.3)

Neuimplementierung nach dem Vorbild von Cookinspect (Matte, Bielova & Santos 2020, „Do Cookie Banners Respect my Choice?“, IEEE S&P 2020) für das IAB Transparency & Consent Framework v2.2/v2.3. Gemessen werden deutsche Websites (Tranco-Liste, Endung `.de`) auf vier mögliche Verstöße:

| | Verstoß | Modus |
|---|---|---|
| V1 | Zustimmung vor der Wahl | automatisch |
| V2 | keine Ablehnmöglichkeit | halbautomatisch |
| V3 | vorausgewählte Optionen | halbautomatisch |
| V4 | Wahl nicht respektiert | halbautomatisch |

Die Definitionen stehen in `CLAUDE.md` („Definitionen der Verstöße“), alle Abweichungen vom Paper und vom ursprünglichen Code in `docs/abweichungen.md`, die technischen Entscheidungen in `docs/entscheidungen.md`, der Stand aller Phasen in `docs/plan.md`.

Kein Browser-Plug-in, keine Tricks gegen Bot-Erkennung, robots.txt wird in allen Modi respektiert. Im halbautomatischen Modus klickt ein Mensch; das Werkzeug liest nur mit.

## Einrichtung

Voraussetzungen: macOS auf Apple Silicon (arm64), Python 3.12 (python.org), Node 20 (z. B. über nvm), Git.

```sh
git clone <repo> ~/Cookinspect && cd ~/Cookinspect
python3.12 -m venv venv
venv/bin/pip install -r requirements.txt            # Selenium, Protego, tldextract, pytest
(cd decode && npm ci)                               # @iabtechlabtcf/core in fester Version (decode/package.json)
venv/bin/python browser.py                          # lädt Chrome for Testing in der Version aus config.py und zeigt die Versionen
venv/bin/python -m pytest                           # Unit-Tests (ohne Browser)
```

Chrome for Testing und chromedriver werden von Selenium Manager in genau der Version aus `config.CHROME_VERSION` geladen (unter `~/.cache/selenium`).

**Echte Läufe** (nicht `--test`) laufen nur unter einem eigenen macOS-Nutzer für die Crawls, mit sauberem Git-Stand, der festen Chrome-Version, arm64 und einer IP aus Deutschland. Sonst bricht das Werkzeug vor dem ersten Request ab. Einrichtung des Nutzers: `docs/crawl-nutzer.md`.

## Ablauf

Alle Befehle laufen über `run_list.py` (oder direkt über das genannte Skript). `--test` schreibt nach `data/test.sqlite` und braucht keinen Crawl-Nutzer; `--purpose vorab` bzw. `--purpose messung` schreibt nach `data/vorab.sqlite` bzw. `data/messung.sqlite`.

| Schritt | Befehl | Ergebnis |
|---|---|---|
| 1. Vorfilter (Trichter wie Matte Tab. II) | `venv/bin/python run_list.py prefilter lists/tranco_GQ3LK_de_top1000.csv --purpose messung` | `data/prefilter-messung-<Zeit>/`: `funnel.md`, `tcf_sites.csv` |
| 2. Aufteilung auf zwei Personen | `venv/bin/python split_sites.py data/prefilter-messung-<Zeit>/tcf_sites.csv ae xy` | `site_assignment.csv` |
| 3. Automatischer Modus (V1, Weitergabe vor der Wahl) | `venv/bin/python run_list.py automatic data/prefilter-messung-<Zeit>/tcf_sites.csv --purpose messung` | auf **einem** Mac für alle Seiten; zwei Sitzungen pro Seite, nichts wird geklickt |
| 4. Halbautomatischer Modus (V2–V4) | `venv/bin/python run_list.py semi-automatic data/prefilter-messung-<Zeit>/site_assignment.csv --operator ae --purpose messung` | das Terminal führt durch Anhang D; Bildschirmfotos in `data/semi-automatic-messung-ae-<Zeit>/` |
| 5. Zusammenführen | `venv/bin/python merge_databases.py data/messung.sqlite messung-xy.sqlite` | die Daten der anderen Person in der eigenen Datei |
| 6. Gegenprüfung auswählen | `venv/bin/python run_list.py crosscheck select --operators ae,xy --purpose messung` | `data/crosscheck-select-messung-<Zeit>/crosscheck-<Kürzel>.csv` |
| 7. Blinde Gegenprüfung | `venv/bin/python run_list.py semi-automatic <…>/crosscheck-xy.csv --operator xy --role crosscheck --purpose messung` | die andere Person prüft, ohne das erste Ergebnis zu sehen |
| 8. Gegenprüfung auswerten | `venv/bin/python run_list.py crosscheck evaluate --purpose messung` | `comparison.csv`, `recheck.csv` |
| 9. Neuprüfung der betroffenen CMPs | `venv/bin/python run_list.py semi-automatic <…>/recheck.csv --operator ae --role recheck --purpose messung` | |
| 10. Auswertung | `venv/bin/python run_list.py evaluate --purpose messung` | `data/evaluation-messung-<Zeit>/`: `tables.md` (Tab. II, Tab. III mit Zuordnung zu Matte, Details), `sites.csv`, `tables.json` |

Lange Läufe in `caffeinate -dims …` packen, damit der Mac nicht einschläft. Jeder Lauf schreibt seine Metadaten (Versionen, Wartezeiten, Konfiguration, Git-Commit, IP-Land, GVL- und CMP-Liste) nach `run_metadata.json` im Lauf-Ordner und in die Tabelle `run`.

Der Vorab-Lauf (`--purpose vorab`) besteht nur aus Vorfilter (Schritt 1) und automatischem Modus (Schritt 3): ohne Klicken, ohne halbautomatischen Modus und ohne Gegenprüfung (`docs/entscheidungen.md`, E3).

## Zwei Personen an zwei Macs

Jede Person arbeitet an ihrem eigenen Mac mit eigenem Crawl-Nutzer und eigener Datenbank. Nichts wird überschrieben: Messdaten und Labels werden nur eingefügt, jede Prüfung trägt das Kürzel der Person.

1. **Mac ae:** Vorfilter-Messlauf (Schritt 1) und Aufteilung (Schritt 2), nur auf diesem Mac. `tcf_sites.csv`, `site_assignment.csv` und `site_assignment.json` an xy weitergeben (AirDrop, USB-Stick); xy legt sie unter demselben Ordnernamen ab und startet **keinen** eigenen Vorfilter.
2. **Mac ae:** automatischer Modus (Schritt 3) für **alle** Seiten, damit V1 überall unter denselben Bedingungen gemessen wird.
3. **Beide:** halbautomatischer Modus (Schritt 4), jede Person nur ihre Seiten aus `site_assignment.csv`.
4. **Beide:** die eigene `data/messung.sqlite` an die andere Person geben (z. B. als `messung-ae.sqlite`) und die fremde in die eigene zusammenführen (Schritt 5). Zweimal zusammenführen ändert nichts. Danach haben beide denselben Stand.
5. **Ein Mac:** Gegenprüfung auswählen (Schritt 6). Jede Person bekommt nur ihre Datei `crosscheck-<Kürzel>.csv`. `selection.json` ist der Schlüssel und wird der prüfenden Person nicht gezeigt.
6. **Beide:** blinde Gegenprüfung (Schritt 7), dann wieder gegenseitig zusammenführen (Schritt 5).
7. **Ein Mac:** Gegenprüfung auswerten (Schritt 8). Bei einer Abweichung zählt pro Verstoßart das mildere Ergebnis, und alle Seiten der CMP werden neu geprüft (Schritt 9, danach wieder zusammenführen).
8. **Auswertung** (Schritt 10) auf einem Mac mit dem zusammengeführten Stand.

**Regel für die blinde Gegenprüfung:** Nach dem Zusammenführen (Punkt 4) enthält die eigene Datenbank auch die Ergebnisse der anderen Person. Bis die eigene Gegenprüfung (Punkt 6) fertig ist, gilt deshalb: kein `evaluate`, kein `crosscheck evaluate`, kein Blick in die Datenbank (auch nicht mit `sqlite3`) und nicht in `selection.json`. Das Werkzeug zeigt in der Gegenprüfung selbst nichts von der ersten Prüfung; die Blindheit beim Ablauf mit zwei Macs beruht aber auf dieser Regel.

## Prüfstand

Lokale Testseite mit einer kleinen CMP (`tests/site/`, Server `tests/site_server.py`), für Tests ohne echte Websites. Mit `?verstoss=v2n|v4streng|v4matte|v4locker` erzeugt sie gezielt einen Verstoß; `lists/pruefstand_gegenpruefung.csv` enthält sechs Testseiten dafür.

```sh
venv/bin/python tests/check_capture.py           # alle Kanäle gegen das, was beim Server ankam
venv/bin/python tests/check_semi_automatic.py    # halbautomatischer Ablauf mit Codes r, n, b und Gegenprüfung (Klicks aus dem Testskript)
venv/bin/python tests/check_crosscheck_flow.py   # Gegenprüfung von select bis recheck
```

## Dateien

| Datei | Inhalt |
|---|---|
| `config.py` | Versionen, Wartezeiten (wie Matte), Grenzen |
| `run_list.py` | Einstieg für alle Modi |
| `prefilter.py`, `robots.py`, `page.py` | Vorfilter, robots.txt (Protego, dazu urllib und Original-Cookinspect zum Vergleich), Laden und Sperren erkennen |
| `automatic.py`, `semi_automatic.py` | automatischer und halbautomatischer Modus |
| `browser.py`, `capture.py` | Chrome for Testing mit WebDriver BiDi; Mitlesen aller Kanäle |
| `cookiewall.py` | Heuristik für Cookiewalls (Pay-or-OK) |
| `decode/`, `decoder.py`, `consent_lists.py` | Dekodierung der TC-Strings, GVL und CMP-Liste |
| `schema.sql`, `migrations/`, `database.py`, `merge_databases.py`, `split_sites.py` | Datenbank (SQLite, nur Einfügen), Zusammenführen, Aufteilung |
| `site_data.py`, `violations.py`, `evaluate.py`, `crosscheck.py` | Auswertung: Daten pro Seite, Verstöße als austauschbare Funktionen, Tabellen, Gegenprüfung |
| `tests/` | Unit-Tests (`pytest`) und Prüfskripte mit Browser (`check_*.py`) |

## Lizenz

Der ursprüngliche Cookinspect hat keine Lizenzdatei. Vor einer Veröffentlichung klären wir die Lizenz mit den Autoren.

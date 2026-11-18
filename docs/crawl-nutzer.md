# Crawl-Umgebung prüfen und Crawl starten

Beide Personen messen am selben Mac unter demselben normalen macOS-Nutzer (`docs/entscheidungen.md`, E8 und E10). Unterschieden werden sie nur über das Kürzel (`--operator ae` bzw. `--operator xy`). Erlaubt sind nur die Nutzer in `config.CRAWL_USERS`; unter einem anderen Nutzer verweigern `prefilter.py` und `run_list.py` den Start, außer mit `--test`. Die Einrichtung (venv, Decoder, Chrome for Testing) steht in der README.

Getestet für: macOS auf Apple Silicon (arm64), Python 3.12 von python.org, Node 20.20.2.

## 1. Nutzer prüfen

`whoami` muss einen Namen aus `config.CRAWL_USERS` zeigen (derzeit `aziz`). Ein Eintrag genügt, auch für zwei Personen. Muss der Wert doch geändert werden, ihn committen: Ein echter Crawl verlangt einen sauberen Git-Stand, deshalb gehört er ins Repo und nicht in eine lokale Änderung.

Im Crawl-Browser nirgends einloggen. Das Browserprofil ist bei jeder Sitzung frisch und temporär; Logins und Daten aus dem eigenen Chrome sind dort nicht vorhanden.

## 2. Prüfen

```sh
venv/bin/python -m pytest -q          # alle Tests grün
venv/bin/python run_metadata.py       # startet Chrome einmal und gibt die Metadaten aus
```

Erwartet in der Ausgabe von `run_metadata.py`:

| Feld | Erwarteter Wert |
|---|---|
| `environment.os_user` | der eigene Nutzer, enthalten in `crawl_users` |
| `environment.run_as_crawl_user` | `true` |
| `git.dirty` | `false` |
| `browser.browser_version`, `browser.chromedriver_version` | `156.0.8078.73` (= `config.CHROME_VERSION`) |
| `browser.fresh_temporary_profile` | `true` |
| `browser.user_agent_matches_http_user_agent` | `true` |
| `ip_country` | `DE` |
| `machine` | `arm64` |
| `decoder.version` | Version aus `decode/package.json` |
| `node_version` | `v20.20.2` |

Weicht ein Wert ab, nicht crawlen. Erst die Ursache klären.

## 3. Crawl starten

Damit der Mac während des Laufs nicht einschläft, den Aufruf in `caffeinate` packen:

```sh
caffeinate -dims venv/bin/python run_list.py prefilter lists/tranco_GQ3LK_de_top1000.csv --purpose vorab
```

Unterbrechen mit Ctrl+C ist jederzeit möglich. Das Werkzeug zeigt dann den Befehl zum Fortsetzen, z. B. `caffeinate -dims venv/bin/python run_list.py prefilter --resume data/prefilter-vorab-<Zeit>`; dazwischen nichts am Repo committen (E9).

Später entsprechend `--purpose messung` (docs/entscheidungen.md, E3). Ein echter Lauf bricht vor dem ersten Request ab, wenn eines nicht stimmt: Nutzer, sauberer Git-Stand, Chrome und chromedriver in der Version aus `config.py`, Architektur `arm64`, IP-Land `DE`.

### Datenbanken: eine Datei pro Zweck

Jeder Lauf schreibt in die Datenbank seines Zwecks, unter `data/`:

| Aufruf | Datei |
|---|---|
| `--test` | `test.sqlite` |
| `--purpose vorab` | `vorab.sqlite` |
| `--purpose messung` | `messung.sqlite` |

Testläufe landen so nie in den Messdaten; Umbenennen ist nicht nötig. Löschen von Zeilen ist im Schema gesperrt.

## 4. Ablauf mit zwei Personen an einem Mac

Beide Personen nutzen denselben Mac, denselben Nutzer und dieselbe Datenbank `data/messung.sqlite`. Nichts wird weitergegeben oder zusammengeführt.

1. **Vorfilter-Messlauf**, einmal:
   ```sh
   caffeinate -dims venv/bin/python run_list.py prefilter lists/tranco_GQ3LK_de_top1000.csv --purpose messung
   ```
   Ergebnis: `data/prefilter-messung-<Zeit>/tcf_sites.csv`.
2. **Aufteilung der Seiten:**
   ```sh
   venv/bin/python split_sites.py data/prefilter-messung-<Zeit>/tcf_sites.csv ae xy
   ```
   Innerhalb jeder CMP werden die Seiten nach Rang abwechselnd verteilt. So sieht jede Person jede CMP, und die Aufteilung ist ohne Zufall reproduzierbar. Ergebnis: `site_assignment.csv` (wer prüft welche Seite zuerst) und `site_assignment.json` (Prüfsumme von `tcf_sites.csv`, Personen, Regel).
3. **Automatischer Modus** für **alle** Seiten, einmal (README, Schritt 3).
4. **Halbautomatischer Modus**, nur `ae` mit den eigenen Seiten aus `site_assignment.csv` (Stichprobe, `docs/entscheidungen.md` E11):
   ```sh
   venv/bin/python run_list.py semi-automatic data/prefilter-messung-<Zeit>/site_assignment.csv --operator ae --purpose messung
   ```
   Die Seiten von `xy` werden nicht halbautomatisch geprüft; `xy` macht die Gegenprüfung. Das Terminal führt durch Anhang D und fragt die Codes ab. Abbrechen mit Ctrl+C ist jederzeit möglich; beim nächsten Start werden fertige Seiten übersprungen. Die Bildschirmfotos liegen in `data/semi-automatic-messung-<Kürzel>-<Zeit>/screenshots/`.
5. **Gegenprüfung** auswählen, blind prüfen, auswerten, neu prüfen: README, Schritte 5–8.

**Regel für die blinde Gegenprüfung:** In der gemeinsamen Datenbank und unter `data/` stehen auch die Ergebnisse der anderen Person. Bis die eigene Gegenprüfung fertig ist, gilt für jede Person:

- kein `evaluate` und kein `crosscheck evaluate`, kein Blick in die Datenbank (auch nicht mit `sqlite3`), in `selection.json` oder in `data/evaluation-*`;
- keine Ergebnisse und keine Bildschirmfotos der anderen Person ansehen, also keinen Ordner `data/semi-automatic-*-<anderes Kürzel>-*` öffnen;
- die Gegenprüfung in einem **neuen Terminalfenster** starten, weil im alten Fenster die Ausgabe der anderen Person stehen kann.

Den ganzen Ablauf mit allen Befehlen beschreibt die README. `merge_databases.py` wird nur gebraucht, falls doch an zwei Macs gemessen wird.

# Crawl-Umgebung prüfen und Crawl starten

Echte Crawls laufen unter dem normalen macOS-Nutzer der jeweiligen Person (`docs/entscheidungen.md`, E8). Erlaubt sind nur die Nutzer in `config.CRAWL_USERS`; unter einem anderen Nutzer verweigern `prefilter.py` und `run_list.py` den Start, außer mit `--test`. Die Einrichtung (venv, Decoder, Chrome for Testing) steht in der README.

Getestet für: macOS auf Apple Silicon (arm64), Python 3.12 von python.org, Node 20.20.2.

## 1. Eigenen Nutzer eintragen (einmal pro Person)

Den eigenen Nutzernamen zeigt `whoami`. Steht er noch nicht in `config.py`, eintragen und committen. Ein echter Crawl verlangt einen sauberen Git-Stand, deshalb gehört der Wert ins Repo und nicht in eine lokale Änderung:

```sh
# in config.py:  CRAWL_USERS = ("aziz", "<Nutzer der zweiten Person>")
git commit -am "config: add crawl user"
```

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

## 4. Ablauf mit zwei Personen an zwei Macs

Jede Person arbeitet an ihrem eigenen Mac unter ihrem eigenen Nutzer (Abschnitte 1–2 auf beiden Macs). Den Code bekommt die zweite Person als Git-Bundle (`git bundle create cookinspect.bundle tcf22-port`, per AirDrop oder USB-Stick; dann `git clone -b tcf22-port cookinspect.bundle Cookinspect`) oder nach einem Push von GitHub.

1. **Vorfilter-Messlauf nur auf einem Mac** (z. B. bei Person `ae`):
   ```sh
   caffeinate -dims venv/bin/python run_list.py prefilter lists/tranco_GQ3LK_de_top1000.csv --purpose messung
   ```
   Ergebnis: `data/prefilter-messung-<Zeit>/tcf_sites.csv`.
2. **Aufteilung der Seiten** auf demselben Mac:
   ```sh
   venv/bin/python split_sites.py data/prefilter-messung-<Zeit>/tcf_sites.csv ae xy
   ```
   Innerhalb jeder CMP werden die Seiten nach Rang abwechselnd verteilt. So sieht jede Person jede CMP, und die Aufteilung ist ohne Zufall reproduzierbar. Ergebnis: `site_assignment.csv` (wer prüft welche Seite zuerst) und `site_assignment.json` (Prüfsumme von `tcf_sites.csv`, Personen, Regel).
3. **Weitergeben an die zweite Person:** `tcf_sites.csv`, `site_assignment.csv` und `site_assignment.json` aus diesem Ordner, z. B. per AirDrop oder USB-Stick. Die zweite Person legt sie in ihren eigenen Ordner `data/prefilter-messung-<Zeit>/`, unter demselben Namen. Sie startet **keinen** eigenen Vorfilter-Messlauf.
4. Beide messen auf ihrem eigenen Mac, jede Person nur ihre Seiten aus `site_assignment.csv`:
   ```sh
   venv/bin/python run_list.py semi-automatic data/prefilter-messung-<Zeit>/site_assignment.csv --operator ae --purpose messung
   ```
   (Person `xy` entsprechend mit `--operator xy`.) Das Terminal führt durch Anhang D und fragt die Codes ab. Abbrechen mit Ctrl+C ist jederzeit möglich; beim nächsten Start werden fertige Seiten übersprungen. Jede Person hat danach ihr eigenes `data/messung.sqlite`; die Bildschirmfotos liegen in `data/semi-automatic-messung-<Kürzel>-<Zeit>/screenshots/`.
5. **Zusammenführen, jede Person in die eigene Datei:** Jede Person gibt ihre Datei weiter, z. B. als `messung-ae.sqlite` und `messung-xy.sqlite`, und führt die fremde in ihre eigene `data/messung.sqlite` zusammen. Auf dem Mac von `ae`:
   ```sh
   venv/bin/python merge_databases.py data/messung.sqlite messung-xy.sqlite
   ```
   (auf dem Mac von `xy` entsprechend mit `messung-ae.sqlite`). Danach haben beide denselben Stand, und `evaluate.py`, `crosscheck.py` und die Gegenprüfung arbeiten mit `--purpose messung` auf der eigenen Datei. Das Skript fügt nur hinzu. Zweimal zusammenführen ändert nichts; abweichende Zeilen mit gleichem Schlüssel meldet es. Enthalten beide Dateien einen Vorfilter-Messlauf, warnt es: dann wurde er versehentlich auf beiden Macs gestartet. Nach jeder weiteren Runde (Gegenprüfung, Neuprüfung) wird wieder gegenseitig zusammengeführt.

   **Regel für die blinde Gegenprüfung:** Nach dem Zusammenführen stehen auch die Ergebnisse der anderen Person in der eigenen Datei. Bis die eigene Gegenprüfung fertig ist: kein `evaluate`, kein `crosscheck evaluate`, kein Blick in die Datenbank (auch nicht mit `sqlite3`) und nicht in `selection.json`.

Der automatische Modus läuft für **alle** Seiten auf **einem** Mac (z. B. bei `ae`), damit V1 überall unter denselben Bedingungen gemessen wird. Den ganzen Ablauf mit allen Befehlen beschreibt die README.

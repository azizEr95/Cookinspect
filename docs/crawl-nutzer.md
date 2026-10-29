# Crawl-Nutzer auf macOS einrichten

Echte Crawls laufen unter einem eigenen macOS-Nutzer (CLAUDE.md, „Sicheres Umfeld“). Ohne ihn verweigern `prefilter.py` und `run_list.py` den Start, außer mit `--test`. Diese Anleitung richtet den Nutzer `crawler` ein. Ein anderer Name geht auch, dann überall ersetzen.

Getestet für: macOS auf Apple Silicon (arm64), Python 3.12 von python.org, Node 20.20.2.

## 1. Nutzer anlegen (als Admin-Nutzer)

Entweder in **Systemeinstellungen → Benutzer:innen & Gruppen → Benutzer:in hinzufügen**:

- Art: **Standard** (kein Administrator)
- Name: `Cookinspect Crawler`, Accountname: `crawler`

Oder im Terminal (fragt nach dem neuen Passwort):

```sh
sudo sysadminctl -addUser crawler -fullName "Cookinspect Crawler" -password -
```

## 2. Beim ersten Anmelden als `crawler`

Das Browserfenster ist in allen Modi sichtbar. Deshalb braucht der Crawl eine grafische Sitzung: Über das Kontrollzentrum oder das Benutzermenü als `crawler` anmelden (schneller Benutzerwechsel). Ein Login per `ssh` reicht nicht.

- Beim Einrichtungsassistenten **keine Apple-ID** anmelden, iCloud, Siri und Analysen überspringen.
- Im Crawl-Nutzer nirgends einloggen, auch nicht in Chrome oder auf Websites.

## 3. Repo übertragen

Solange der Branch `tcf22-port` nicht gepusht ist, geht das Repo als Git-Bundle über `/Users/Shared`.

**Vorher im Entwickler-Nutzer** (z. B. `aziz`) `CRAWL_USER` setzen und committen. Ein echter Crawl verlangt einen sauberen Git-Stand, deshalb gehört der Wert ins Repo und nicht in eine lokale Änderung:

```sh
cd ~/Desktop/Cookinspect
# in config.py:  CRAWL_USER = "crawler"
git commit -am "config: set CRAWL_USER for the crawl user"
git bundle create /Users/Shared/cookinspect.bundle tcf22-port
```

Testläufe (`--test`) gehen danach im Entwickler-Nutzer weiter. Es kommt nur eine Warnung, dass es nicht der Crawl-Nutzer ist.

**Als `crawler`:**

```sh
git clone -b tcf22-port /Users/Shared/cookinspect.bundle ~/Cookinspect
```

Für spätere Änderungen erst im Entwickler-Nutzer das Bundle neu erzeugen (Befehl wie oben), dann als `crawler`:

```sh
cd ~/Cookinspect && git pull
```

Nach einem Push (erst nach Zustimmung) kann `crawler` direkt von GitHub klonen.

## 4. Python-Umgebung (als `crawler`)

Python 3.12 von python.org ist systemweit installiert und auch für `crawler` da:

```sh
cd ~/Cookinspect
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 -m venv venv
venv/bin/pip install -r requirements.txt
```

## 5. Node und Decoder (als `crawler`)

Node aus nvm liegt im Home-Verzeichnis des Entwickler-Nutzers und ist für `crawler` nicht erreichbar. Deshalb bekommt `crawler` ein eigenes nvm, mit derselben Node-Version:

```sh
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
# neues Terminalfenster öffnen, dann:
nvm install 20.20.2
cd ~/Cookinspect/decode && npm ci     # installiert @iabtechlabtcf/core genau nach package-lock.json
```

## 6. Prüfen (als `crawler`)

```sh
cd ~/Cookinspect
venv/bin/python -m pytest -q          # alle Tests grün
venv/bin/python run_metadata.py       # startet Chrome einmal und gibt die Metadaten aus
```

Beim ersten Aufruf lädt Selenium Manager Chrome for Testing in `~/.cache/selenium` herunter. Das dauert einen Moment.

Erwartet in der Ausgabe von `run_metadata.py`:

| Feld | Erwarteter Wert |
|---|---|
| `environment.os_user` / `crawl_user` | `crawler` / `crawler` |
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

## 7. Crawl starten (als `crawler`)

Damit der Mac während des Laufs nicht einschläft, den Aufruf in `caffeinate` packen:

```sh
cd ~/Cookinspect
caffeinate -dims venv/bin/python prefilter.py lists/tranco_GQ3LK_de_top1000.csv --purpose vorab
```

Später entsprechend `--purpose messung` (docs/entscheidungen.md, E3). Ohne sauberen Git-Stand oder unter einem anderen Nutzer bricht das Skript vor dem ersten Request ab.

## 8. Ergebnisse weitergeben

Die Ergebnisse liegen in `~/Cookinspect/data/` des Crawl-Nutzers. Für die Auswertung nach `/Users/Shared` kopieren:

```sh
mkdir -p /Users/Shared/cookinspect-data
cp -R ~/Cookinspect/data/prefilter-vorab-* /Users/Shared/cookinspect-data/
```

Alle Ergebnisse stehen außerdem in der Datenbank `~/Cookinspect/data/cookinspect.sqlite`, eine Datei pro Person und Mac. Testläufe stehen dort auch, markiert mit `purpose = 'test'`. Wer eine leere Datenbank für die Messung will, benennt die Datei vorher um. Löschen von Zeilen ist im Schema gesperrt.

Zum Zusammenführen kopiert jede Person ihre Datei nach `/Users/Shared` (z. B. `cookinspect-ae.sqlite`); dann auf einem Mac:

```sh
venv/bin/python merge_databases.py data/merged.sqlite /Users/Shared/cookinspect-ae.sqlite /Users/Shared/cookinspect-xy.sqlite
```

Das Skript fügt nur hinzu. Zweimal zusammenführen ändert nichts; abweichende Zeilen mit gleichem Schlüssel meldet es.

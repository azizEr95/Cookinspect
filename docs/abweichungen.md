# Abweichungen

Abweichungen dieser Neuimplementierung (TCF v2.2) vom Paper von Matte et al. (2020) und vom ursprünglichen Cookinspect. Die Liste wird mit jeder Phase ergänzt; in Phase 11 wird sie vervollständigt und um die Abweichungen zwischen Paper und Code von Cookinspect ergänzt.

## Methode

| Thema | Matte et al. (2020) | Diese Messung | Grund |
|---|---|---|---|
| TCF-Version | v1.1 (`__cmp()`, 5 Zwecke) | v2.2 (`__tcfapi`, 11 Zwecke) | v1.1 gibt es nicht mehr |
| Standort | Frankreich | Berlin | Nachmessung für deutsche Websites |
| V1 | eine Sitzung | zwei frische Sitzungen; V1 zählt nur, wenn beide Vorher-Snapshots es zeigen | robuster gegen zufällige Unterschiede zwischen Sitzungen |
| Halbautomatischer Crawl | eine Person machte den ganzen Crawl, Gegenprüfung nach V-C | die Seiten werden auf zwei Personen aufgeteilt; Gegenprüfung nach V-C durch die jeweils andere Person | Zeitaufwand |
| robots.txt: Auswertung | `urllib.robotparser` (Paper IV-A); im Code eigene Behandlung: jeder Status ≥ 400 außer 401/403 (also auch 5xx) und nicht abrufbare robots.txt gelten als „alles erlaubt“ | Protego nach RFC 9309 (4xx erlaubt, 5xx und nicht abrufbar verbieten); die Entscheidungen von urllib und vom Original-Code werden je Domain mitgespeichert | aktueller Standard; Vergleich mit Matte bleibt möglich |
| robots.txt: Status 429 | im Code „alles erlaubt“ (jeder Status ≥ 400 außer 401/403) | wie 5xx: alles verboten. **Abweichung von RFC 9309**, das jeden 4xx als „alles erlaubt“ wertet | 429 ist eine Bitte um weniger Anfragen; Google behandelt 429 ebenfalls wie einen Serverfehler. Die Spalten urllib und Original-Cookinspect behalten ihr eigenes Verhalten (erlaubt) |
| robots.txt: Modi | Paper: robots.txt respektiert; Code: `-a` und `-t` prüfen, laden die Seite aber trotzdem (`bypass_robots_txt=True`), nur `-a2` hält sich daran | in allen Modi respektiert, keine Umgehung | wie im Paper beschrieben |
| robots.txt: User-Agent | Regeln für den User-Agent-String des Browsers (urllib nutzt davon nur „Mozilla“) | Regeln für `*` | in der Praxis gleich; einfacher nachvollziehbar |
| robots.txt: Fehlerarten für die Ausweichregeln | Code vergleicht Linux-Fehlertexte (z. B. `[Errno -2] Name or service not known`) | Vergleich der Ausnahmetypen (`socket.gaierror` → ohne www; TLS, Timeout, abgewiesen, zurückgesetzt → HTTP; alles andere „sonstiger Fehler“, kein neuer Versuch) | Unter macOS lauten die Texte anders (z. B. `[Errno 8] nodename nor servname provided`); mit Textvergleich würde keine Ausweichregel greifen |
| TCF-Erkennung | `__cmp()` ist definiert (Paper V-A) | nach dem Laden und weiteren 3 s ist `__tcfapi` definiert **und** antwortet auf `ping`; `__tcfapi` ohne Antwort wird im Trichter eigens gezählt | v2.2-API; ein bloßer Stub ohne CMP soll nicht als TCF-Banner zählen |
| Trichter, Spalte „erlaubt“ | eine Entscheidung (Original-Code) | drei Entscheidungen nebeneinander (Protego, urllib, Original-Cookinspect); geladen wird nur, was Protego erlaubt | Für den Vergleich mit Tab. II zählt die Spalte „Original-Cookinspect“. Seiten, die nur der Original-Code erlaubt (z. B. robots.txt mit 5xx), werden nicht geladen; ihre Zahl steht im Trichter („nicht geladen, weil Protego verbietet“) |
| Bot-Sperren | nicht erfasst | heuristisch erkannt (Status 401/403/429, Texte wie „Access Denied“, HTML-Merkmale von Bot-Managern wie Akamai, Cloudflare, DataDome, PerimeterX, Imperva, leere Seite) und im Trichter gezählt; nicht umgangen. Der TCF-Anteil steht zweimal im Trichter: mit gesperrten Seiten im Nenner (vergleichbar mit Matte) und ohne | Keine Tricks gegen Bot-Erkennung (CLAUDE.md); Sperren sollen sichtbar sein. Beispiel: mobile.de liefert am 2026-10-29 eine Akamai-Seite mit Status 200 und ohne sichtbaren Text |
| Drittanbieter | – | Request an eine andere registrierbare Domain als die Website (Public Suffix List von tldextract, mitgelieferter Stand, kein Download), z. B. `cdn.privacy-mgmt.com` bei bild.de | reproduzierbar; Version von tldextract steht in den Metadaten |
| Shared Cookie / consensu.org | Kanal ③ | entfällt; stattdessen Erstanbieter-Cookie `euconsent-v2` und localStorage | in TCF v2 gibt es keinen globalen Consent mehr |

## Befunde zu robots.txt

### google.de: Protego erlaubt, urllib und Original-Cookinspect verbieten

Belegt am 2026-10-29 mit `https://www.google.de/robots.txt` (264 Zeilen, SHA-256 beginnt mit `0e8c5c623003d14d`), Regeln für `*`, Startseite `https://www.google.de/`:

- Ursache ist **nicht** „erste passende Regel statt längster“, sondern die Normalisierung der Pfade in `urllib.robotparser`: `RuleLine` schickt jeden Pfad durch `urlunparse(urlparse(path))`. Dabei fällt die leere Query weg, aus `Disallow: /?` wird `Disallow: /`.
- Diese Regel ist in der Gruppe für `*` die erste, die auf `/` passt; urllib nimmt die erste passende Regel und verbietet damit die Startseite.
- Gegenprobe: Ohne die Zeile `Disallow: /?` erlaubt urllib die Startseite. Protego wertet `/?` als Präfix wörtlich aus (RFC 9309); es passt nur auf URLs mit `?` und erlaubt `/`.
- Der Original-Code von Cookinspect nutzt denselben Parser und entscheidet deshalb wie urllib. Das passt zu Mattes Code-Kommentar „negative example: google.fr“.
- Unit-Test: `tests/test_robots.py::test_google_de_disallow_query_blocks_start_page_only_in_urllib`.

Folge für den Vergleich mit Matte: Jede Website mit einer Regel wie `Disallow: /?` (oder `Disallow: /#…`) zählte bei Matte als „nicht erlaubt“, obwohl der Betreiber nur URLs mit Query ausschließen wollte. Das senkt Mattes Zahl „erreichbar und erlaubt“ etwas gegenüber RFC 9309.

## Technische Grenzen

| Grenze | Auswirkung |
|---|---|
| Request-Bodies über 1 MB (Grenze des BiDi-Data-Collectors) werden nicht gespeichert, sondern als „Body zu groß“ markiert. | Ein Consent-String in einem so großen POST-Body würde nicht erkannt. |
| Requests von Service Workern haben in BiDi keinen Browsing-Context. | Sie werden erfasst, aber keinem Frame zugeordnet (`source = worker`). |
| Der Listener in Kanal ① fragt alle 50 ms nach `__tcfapi`. | Zwischenstände vor der Anmeldung (z. B. ein frühes `tcloaded`) können fehlen; der Stand zum Zeitpunkt der Anmeldung kommt immer an. |
| Manche CMPs rufen den Listener mit leerem `tcData` auf (amazon.de, CMP 376, 2026-10-29: kein `eventStatus`, kein `tcString`, keine `listenerId`; ping meldet `displayStatus: hidden`). | Kein TC-String über Kanal ①; das Ereignis wird als `emptyTcData` markiert und nicht als „keine Zustimmung“ gewertet. `removeEventListener` ist dort nicht möglich (keine `listenerId`). |
| Kanal ② (Dritt-Position) ist nur messbar, wenn die Seite ein fremdes iframe enthält. | Ohne fremdes iframe: „nicht messbar“; die Quote wird pro Phase ausgewiesen. |

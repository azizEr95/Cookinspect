# Abweichungen

Abweichungen dieser Neuimplementierung (TCF v2.2/v2.3) vom Paper von Matte et al. (2020) und vom ursprünglichen Cookinspect. Die Liste wird mit jeder Phase ergänzt; in Phase 11 wird sie vervollständigt und um die Abweichungen zwischen Paper und Code von Cookinspect ergänzt.

## Methode

| Thema | Matte et al. (2020) | Diese Messung | Grund |
|---|---|---|---|
| TCF-Version | v1.1 (`__cmp()`, 5 Zwecke, kein disclosedVendors) | v2.2/v2.3 (`__tcfapi`, 11 Zwecke, kein LI für Zwecke 3–6; ab v2.3 Segment disclosedVendors Pflicht). Gespeichert wird pro String, ob disclosedVendors vorhanden ist; Strings ohne das Segment („v2.2-String“) zählen genauso, sie bleiben gültig | v1.1 gibt es nicht mehr; Versionsstand siehe unten |
| Standort | Frankreich | Berlin | Nachmessung für deutsche Websites |
| V1 | eine Sitzung | aus dem automatischen Modus: zwei frische Sitzungen; V1 zählt nur, wenn beide Vorher-Snapshots es zeigen. Die Vorher-Snapshots des halbautomatischen Modus sind nur eine Ergänzung | robuster gegen zufällige Unterschiede zwischen Sitzungen |
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
| GVL je String | Version aus dem String (`iab_data_collection.py:400` bei 948a85f); ist sie 0 oder fehlerhaft, die neueste GVL | Version aus dem String (`vendorListVersion`), bei Policy ≥ 4 aus dem Archiv GVL v3, sonst GVL v2; **kein Rückgriff** auf die neueste: fehlt die Version, wird „GVL nicht verfügbar“ gespeichert. Die verwendete Version steht pro String in den Ergebnissen | Eine neuere GVL würde Vendoren als bekannt werten, die es beim Erstellen des Strings nicht gab |
| CMP-Liste | feste CSV (`cmplist/IAB_CMP_list_full.csv`, Stand 2019) | Schnappschuss der offiziellen Liste pro Lauf (`cmplist.consensu.org/v2/cmp-list.json`, `lastUpdated` und SHA-256 in den Metadaten). Gültig = in der Liste und nicht vor dem Erstellen des Strings gelöscht (`deletedDate`) | aktueller Stand; gelöschte CMPs (derzeit 75 von 274) werden zeitlich richtig bewertet |
| Dekodierung | eigener Decoder für v1.1, gespeichert wurde `maxId_` statt der IDs (Befund F1) | `@iabtechlabtcf/core` 1.5.22 über `decode/tcstring.mjs`; alle IDs als Listen. Zusätzlich aus dem String selbst gelesen: welche Segmente vorhanden sind (disclosedVendors = v2.3-String) | F1 behoben; v2.2/v2.3 unterscheidbar |
| Datenbank | PostgreSQL über SQLAlchemy, eine Tabelle `website` mit Bool-Spalten je Verstoß, die überschrieben wurden | SQLite (`schema.sql`, `database.py`): Messdaten und Labels werden nur eingefügt (Trigger verhindern Ändern und Löschen), alle IDs je TC-String in `tc_string_entry`, Verstöße werden erst in der Auswertung berechnet. Eine Datei pro Person und Mac, zusammengeführt mit `merge_databases.py` (UUIDs, TC-Strings über SHA-256) | nachvollziehbar und reproduzierbar; Gegenprüfung und Korrekturen stehen neben dem ersten Ergebnis |
| Automatischer Modus: Zeitpunkt V1 | nach dem Laden der Seite und weiteren 3 s (S. 5 und 8) | gleich: Snapshot „vorher“ erst nach dem Laden plus `SLEEP_TIME_CMP_WAIT` = 3 s, in beiden Sitzungen; nichts wird geklickt | – |
| Cookiewalls (Pay-or-OK) | nicht erfasst | **Heuristik** (`cookiewall.py`) im automatischen Modus, pro Sitzung: Der Dialog bietet Zustimmen und Bezahlen an (z. B. „Pur-Abo“, „werbefrei“, Preis in Euro), oder die Seite lädt contentpass. Sie markiert einen Verdacht, sie entscheidet nicht; in Phase 8 wird sie mit dem manuellen Code `w` abgeglichen | Grundlage für die Entscheidung, ob die Forschungsfrage um Cookiewalls erweitert wird (CLAUDE.md). Am 2026-10-29 von 5 TCF-Test-Seiten 4 markiert (t-online, bild, welt, focus); per Bildschirmfoto bestätigt, amazon.de mit „Ablehnen“ richtig nicht markiert |
| Halbautomatisch: Ablauf je Code | eine Person, Ablehnen- und Akzeptieren-Sitzung | `r`: Ablehnen-Sitzung, dann Akzeptieren-Sitzung. `n` und `w`: keine Ablehnen-Sitzung; in der ersten Sitzung wird akzeptiert (bei `w` zustimmen, nicht bezahlen). `b` (kein Banner nach 3-mal Neuladen) und `x`: keine weitere Sitzung. `w` nur ohne kostenlosen Weg zum Ablehnen (auch nicht auf der 2. Ebene); Cookiewall mit kostenlosem Ablehnen = `r` mit Ebene, dazu `cookiewall_seen` = ja. Bei `n`/`w` gibt es daher nur **einen** Vorher-Snapshot aus dem halbautomatischen Modus; V1 kommt aus dem automatischen Modus (zwei Sitzungen) | Anhang D; Vorgabe für Cookiewalls (Akzeptieren-Sitzung, damit V1 und die Weitergabe nach Zustimmung messbar sind) |
| Halbautomatisch: Belege | – | Bildschirmfoto des Banners vor der Aktion und nach dem Schließen (Tabelle `screenshot`, Dateien im Lauf-Ordner); nach jedem Schritt zeigt das Terminal, was gespeichert wurde (bei der Gegenprüfung erst nach dem Label) | Fehler sofort sehen; Nachprüfbarkeit der Labels |
| Gegenprüfung | eine zweite Prüfung (V-C) | eigene Prüfung mit `role = crosscheck` und Verweis auf die erste; das Werkzeug zeigt nichts von der ersten Prüfung, die eigenen Ergebnisse erst nach dem Label; dieselbe Person kann ihre eigene Prüfung nicht gegenprüfen | blind, wie in CLAUDE.md verlangt |
| V4: Zeitpunkt (Präzisierung zu S. 8) | nach dem Ablehnen wird der gespeicherte Consent gelesen; nach 3 s wird neu geladen, um die Requests zu loggen und den String erneut zu lesen. Welcher der beiden Werte für V4 zählt, steht nicht da | V4 wird auf dem Snapshot **nach dem Reload** berechnet (nach Ablehnen und nach Akzeptieren). Der Snapshot direkt nach der Aktion wird getrennt ausgewiesen, dazu, wie oft er vom Reload-Snapshot abweicht | stabiler Zustand, auch ohne `useractioncomplete`: amazon.de (CMP 376, 2026-10-31) liefert direkt nach Ablehnen und Akzeptieren nur leeres tcData und kein `useractioncomplete`, erst nach dem Reload einen String |
| Kanäle für V1 und V4 | API und Shared Cookie zusammen (S. 7) | Hauptzahl nur Kanal 1 (`__tcfapi`). Variante „Matte-Kanäle“: Verstoß, wenn irgendein Kanal (1, 2, Cookie, localStorage) ihn zeigt. Beide werden ausgewiesen | Kanal 1 ist die Schnittstelle, über die Vendoren den Consent lesen; die Variante macht den Vergleich mit Matte möglich |
| V1: TCF-API ohne String | – | getrennt als „nicht auswertbar“, auch wenn nur einer der beiden Vorher-Snapshots keinen String hat (E7) | ein leeres tcData ist kein Beleg für „keine Zustimmung“ |
| V3: Nenner | Seiten mit Ablehnmöglichkeit (508); Zwecke **oder** Vendoren vorausgewählt | Hauptzahl: Code `r` und 2. Ebene vorhanden; Zwecke und Vendoren getrennt; „?“ (nicht geprüft) außerhalb des Nenners. In Tab. III zusätzlich Mattes Zählung (Zwecke oder Vendoren, Nenner alle `r`) | ohne 2. Ebene gibt es nichts, was vorausgewählt sein könnte |
| Gegenprüfung: Auswahl | pro CMP mit Verstoß eine verstoßende Seite, dazu gleich viele Seiten ohne Verstoß aus dem Pool; getrennt für Non-respect of choice und No way to opt out. **Dieselbe CMP wird nicht verlangt** | gleich, getrennt für V4 (streng) und V2; die Seiten ohne Verstoß kommen **zuerst aus derselben CMP**, gibt es dort keine, aus den anderen CMPs. Zufallsauswahl mit festem Seed (2020), der Schlüssel steht in `selection.json` | dieselbe CMP vergleicht dasselbe Banner; Seed für die Reproduzierbarkeit |
| Gegenprüfung: Ergebnis (Präzisierung zu V-C) | bei Abweichung zählt der Test mit den wenigsten Verstößen; alle Seiten der CMP werden neu geprüft | „milder“ wird **pro Verstoßart** entschieden, nicht über die Summe der Treffer. V2: die mildere Einstufung zählt (1. Ebene < nur 2. Ebene < gar nicht; `w` zählt als „gar nicht“). V4: die mildere Einstufung zählt (kein Verstoß < nur locker < streng ohne Vendor-Consent < Matte-Variante). Bei Gleichstand zählt die erste Prüfung; ist nur eine der beiden Prüfungen für die Verstoßart auswertbar (z. B. Code `n` ohne Ablehnen-Sitzung), zählt diese. V2 und V4 können so aus verschiedenen Prüfungen kommen: Label-Werte (V2, V3, Cookiewall) aus der Prüfung, die für V2 zählt, Sitzungs-Werte (V4, LI, Weitergabe nach Ablehnen, E5) aus der für V4. Rangfolge: Korrektur ersetzt die korrigierte Prüfung, Neuprüfung ersetzt alle früheren, sonst die Gegenprüfung wie beschrieben | die Gegenprüfung erfolgt getrennt für V2 und V4 (Matte V-C); eine Summe würde V4 mit seinen drei Varianten dreifach gewichten. Nichts wird überschrieben, die Rangfolge gilt nur in der Auswertung |
| Shared Cookie / consensu.org | Kanal 3 | entfällt; stattdessen Erstanbieter-Cookie `euconsent-v2` und localStorage | in TCF v2 gibt es keinen globalen Consent mehr |

## Versionsstand TCF (geprüft am 2026-10-29)

Quellen: offizielle Spezifikation „IAB Tech Lab – Consent string and vendor list formats v2“ (Repo GDPR-Transparency-and-Consent-Framework, Commit `703fc29`, 2026-07-28), offizielle GVL v3 und ihre Archive (`vendor-list.consensu.org/v3/`), Ankündigung der Policy-Änderung 2024 (Didomi, zitiert IAB Europe).

| Version | Stand | Was sich am String ändert |
|---|---|---|
| v2.2 (Mai 2023) | 11 Zwecke, kein LI für Zwecke 3–6 | `TcfPolicyVersion` wird 4 („With the release of TCF v2.2, the policy version has been incremented to version 4“, Spezifikation) |
| TCF Policies 5.0 (2024) | Policy-Änderung ohne neue technische Version (u. a. Special Purpose 3) | `TcfPolicyVersion` 5: GVL v3 Nr. 61 (2024-07-11) hat noch 4, Nr. 62 (2024-07-18) schon 5; neue Strings ab 4. Oktober 2024 mit 5.0 |
| v2.3 (Spezifikation April 2025, verbindlich 28.02.2026) | Segment **disclosedVendors** Pflicht | keine neue `TcfPolicyVersion`: Die aktuelle GVL (Nr. 182, 2026-10-22) hat weiterhin 5. Strings vor dem 1. März 2026 ohne disclosedVendors bleiben gültig |
| TCF Policies v5.0.b (29.05.2026) und Technical Specifications v2.4 (23.07.2026, mit neuer GVL) | GVL bekommt das Feld `standardTexts` (Erklärtext zu Features), Abbildungen je Feature, neuer Name für Special Feature 2; Umweg für Vendoren mit nur Special Purposes endgültig entfernt (siehe unten). Frist für CMPs im Web: 23.10.2026, für Apps und CTV: 23.02.2027 (IAB Europe, Schreiben vom 16.07.2026). „May 2026“ in der Versionstabelle der Spezifikation ist das Datum des Entwurfs (Commit `a3e665d`, 2026-05-07), übernommen wurde er am 2026-07-20 (PR #443) | Format des TC-Strings unverändert (v2); die aktuelle GVL (Nr. 182) hat `standardTexts` |

**Korrektur:** In den Berichten zu Phase 2b und 3 stand „Policy-Version 5 = TCF v2.2“. Das ist falsch. 5 ist die Version der **TCF-Policies** (5.0, seit 2024), nicht der technischen TCF-Version. Ob ein String nach v2.2 oder v2.3 gebaut ist, lässt sich nur am Segment disclosedVendors ablesen, nicht an der `TcfPolicyVersion`. Der Decoder speichert deshalb `disclosed_vendors_present`.

### Vendoren mit nur Special Purposes: ändert sich die Bedeutung von Feldern im TC-String?

Geprüft an der Geschichte der Spezifikation (Commits `c2a28ab` 2025-03-31, `b0226e2` 2026-03-04, `d372cdb` 2026-03-11, v2.4 `778c8c4` 2026-07-20).

| Feld | bis v2.2 | ab v2.3 / v2.4 | Bedeutung geändert? |
|---|---|---|---|
| **Vendor-LI** (Vendor Legitimate Interest Section im Core) | Umweg: Für Vendoren, die **nur Special Purposes** registriert haben und angezeigt wurden, „the value must be set to 1“. Das Bit hieß dort also „angezeigt“, nicht „berechtigtes Interesse für einen Zweck“ | Der Satz ist gestrichen (2026-03-04, in v2.4 bestätigt). Das Bit heißt nur noch „Legitimate Interest established“ für Zwecke. „For TC strings created prior to March 1, 2026, the Legitimate Interest bit was set to 1 for vendors declaring Special Purposes“ | **ja**, für Strings vor dem 1. März 2026 |
| **disclosedVendors** | optional und „must not be included in the TC String when returned by the CMP API“ | Pflicht; listet alle dem Nutzer offengelegten Vendoren, auch die mit nur Special Purposes. Damit ersetzt es den Umweg über das LI-Bit | Rolle geändert mit v2.3; **v2.4 ändert daran nichts** |
| Zweck-LI (`purpose.legitimateInterests`) | – | – | nein |

Folgen für unsere Auswertung:

- **Zweck-LI** (auch das Verbot für Zwecke 3–6) und **alle Zweck-Consents** sind nicht betroffen. Damit sind auch V1–V4 nicht betroffen, weil sie auf Zwecken beruhen.
- **Vendor-LI:** In Strings, die vor dem 1. März 2026 erstellt wurden, kann ein gesetztes Bit nur „angezeigt“ bedeuten. In der aktuellen GVL (Nr. 182) gibt es 21 Vendoren mit nur Special Purposes. Für Phase 8 vorgemerkt: Vendor-LI-Bits für solche Vendoren (laut GVL-Version des Strings) werden getrennt gezählt und nicht als berechtigtes Interesse gewertet, bei alten wie bei neuen Strings. Setzt eine CMP das Bit nach dem 1. März 2026 noch, folgt sie dem entfernten Umweg; auch das wird ausgewiesen.
- Unsere Sitzungen beginnen mit frischem Profil. Die gemessenen Strings entstehen also beim Besuch (nach dem 23.10.2026) und haben die neue Bedeutung, wenn die CMP aktuell ist.
- **Zustimmung außerhalb von disclosedVendors** (E5) ist nur für Strings mit dem Segment auswertbar. v2.2-Strings durften es über die API gar nicht enthalten.

Folge für die Messung: Die Policy-Regeln (11 Zwecke, kein LI für Zwecke 3–6) sind in allen Strings mit `TcfPolicyVersion` 4 oder 5 gleich. Die Verstöße V1–V4 werden für v2.2- und v2.3-Strings gleich bewertet. Strings mit `TcfPolicyVersion` < 4 sind seit 30.09.2023 ungültig; sie werden markiert.

Decoder: `@iabtechlabtcf/core` 1.5.22 (2026-09-01, neueste Version) unterstützt v2.3 („Initial update to support TCF v2.3“, 2025-05-30; Reihenfolge der Segmente 2025-10-22; Workaround für Vendoren mit nur Special Purposes entfernt 2026-03-10) und die GVL-Felder von v2.4 (`standardTexts`, 2026-08-17). Die Version bleibt daher unverändert.

### Grenzen von `@iabtechlabtcf/core` 1.5.22 und wie der Decoder damit umgeht

Geprüft mit `tests/test_decoder.py` und den Test-Strings aus `decode/fixtures.mjs`:

| Verhalten der Bibliothek | Folge ohne Gegenmaßnahme | Umgang |
|---|---|---|
| Dekodieren bricht bei CMP-ID 0 oder 1 ab („invalid value 0 passed for cmpId“; `TCModel` verlangt cmpId > 1) | Strings mit genau den ungültigen IDs, die Matte fand, wären ganz verloren | Die Bibliothek bekommt eine Kopie mit CMP-ID 2. Ausgegeben wird die echte ID aus den Bits, markiert mit `cmpIdReplacedForDecoding` |
| Beim Kodieren entfernt sie berechtigtes Interesse für Zwecke 3–6 und übernimmt die Policy-Version der GVL | nur für das Erzeugen der Test-Strings relevant; **beim Dekodieren bleiben beide erhalten** (geprüft) | Test-Strings mit LI 3–6 und Policy 3 werden über die Bits gesetzt |
| Ein fehlendes disclosedVendors-Segment und ein leeres sehen im Modell gleich aus | v2.2- und v2.3-Strings wären nicht zu unterscheiden | Die Segmente werden am String selbst gelesen (Segment-Typ = erste 3 Bits) |
| Ungültiger Ländercode des Publishers bricht das Dekodieren ab | einzelne Strings nicht dekodierbar | wird als „decoding failed“ mit Grund gespeichert und gezählt |

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
| Der Listener in Kanal 1 fragt alle 50 ms nach `__tcfapi`. | Zwischenstände vor der Anmeldung (z. B. ein frühes `tcloaded`) können fehlen; der Stand zum Zeitpunkt der Anmeldung kommt immer an. |
| Manche CMPs rufen den Listener mit leerem `tcData` auf (amazon.de, CMP 376, 2026-10-29: kein `eventStatus`, kein `tcString`, keine `listenerId`; ping meldet `displayStatus: hidden`). | Kein TC-String über Kanal 1; das Ereignis wird als `emptyTcData` markiert und nicht als „keine Zustimmung“ gewertet. `removeEventListener` ist dort nicht möglich (keine `listenerId`). |
| Kanal 2 (Dritt-Position) ist nur messbar, wenn die Seite ein fremdes iframe enthält. | Ohne fremdes iframe: „nicht messbar“; die Quote wird pro Phase ausgewiesen. |

## Fehler im v2-Code von Cookinspect (2021)

Stand Commit 948a85f unseres Forks (= letzter Stand von Matte, „update to tcfv2“). Die Zeilenangaben sind am 2026-10-31 gegen die History geprüft. Keiner dieser Fehler betrifft das Paper (2019, TCF v1.1); sie zeigen, warum der alte Code für eine v2-Nachmessung nicht taugt. Spalte rechts: wie die Neuimplementierung es löst.

| Nr. | Befund | Stelle (948a85f) | Neuimplementierung |
|---|---|---|---|
| F1 | `count_nb_purposes` und `count_nb_vendors` liefern für v2 `purposeConsents.maxId_` bzw. `vendorConsents.maxId_`, also die höchste ID statt der Anzahl; durch `JSON.stringify` des TCModel geht `set_` verloren, die IDs selbst sind nicht mehr da | `iab_data_collection.py:222–232`, `decode_IAB_API_strings/decode_IAB_API_strings_v2.js:5` | alle IDs als Listen (`decode/tcstring.mjs`, Tabelle `tc_string_entry`) |
| F2 | der postMessage-Test liest `val.TCData` statt `tcString`; Kanal 2 liefert in v2 nie etwas | `extensions/probe_cmp_postmessage/content_scripts/uCookie.js:106`, `background.js:42` | Kanal 2 liest `tcString` aus der Antwort auf `__tcfapiCall` (`capture.py`) |
| F3 | die Erweiterung loggt `sc-postMessage_v2:`, der Regex erwartet `sc-postMessage:` | `extensions/monitor_postmessages/content_scripts/monitor_postmessages.js:35`, `iab_data_collection.py:35` | keine Konsolen-Logs mehr; Ereignisse kommen über WebDriver BiDi direkt nach Python (E1) |
| F4 | v2-Strings aus postMessage werden ohne `v2=True` an `consent_string_violations` übergeben und mit dem v1-Decoder dekodiert | `iab_data_collection.py:661` (im v2-Zweig; die gleiche Zeile 656 steht im v1-Zweig und ist dort richtig) | die Version wird am String erkannt, nicht am Aufruf (CLAUDE.md, Technik) |
| F5 | das Argument `v2` landet wegen seiner Position im Parameter `try_getting_consent_string` von `get_through_logs_for_violations(browser, website, seen_consent_strings, try_getting_consent_string=False, v2=False)` | Aufruf `iab_data_collection.py:772`, Definition `:783` | entfällt (keine Log-Auswertung) |
| F6 | der Shared Cookie zählt nur, wenn v1- **und** v2-Cookie da sind; seit dem v2-Commit ist damit auch die v1-Erkennung im halbautomatischen Modus kaputt | `iab_data_collection.py:704` | entfällt (kein Shared Cookie in TCF v2) |
| F7 | `raw_post_data is list` ist immer falsch (Vergleich mit dem Typ statt `isinstance`); Formulardaten werden nie ausgewertet; die Erweiterung liest nur `requestBody.raw`, nicht `formData` | `iab_data_collection.py:854`, `extensions/watch_requests/content_scripts/background.js:15` | Request-Bodies über BiDi; Formulardaten, JSON und OpenRTB/Prebid werden ausgewertet (`capture.consent_signals`) |
| F8 | die Browser-Logs werden beim Lesen verbraucht; nach dem v2-Durchlauf sieht der v1-Durchlauf nichts mehr (im Code selbst vermerkt: „might bug if tcfv2 was done before“) | `cookinspect.py:451–454` | entfällt (keine Log-Auswertung) |

## Abweichungen Paper ↔ Code von Cookinspect

Was das Paper beschreibt und was der Code (948a85f) tut. Geprüft am 2026-10-31.

| Nr. | Paper | Code (948a85f) | Neuimplementierung |
|---|---|---|---|
| 1 | robots.txt wird respektiert (IV-A) | `-a` (`automatic_violations_check`, `cookinspect.py:420`) und `-t` (`test_if_website_uses_cmp_only`, `:341`) setzen `bypass_robots_txt=True`: robots.txt wird geprüft, die Seite aber trotzdem geladen. Nur `-a2` (`automatic_violations_check_full`, `:360`) hält sich daran | in allen Modi respektiert |
| 2 | Shared-Cookie-Test im automatischen Crawl (V-A) | nur in `-a2` (`add_shared_cookie=True`, `cookinspect.py:392`), nicht in `-a` | entfällt (kein Shared Cookie in v2) |
| 3 | postMessage-Test nur in Dritt-iframes unter `__cmpLocator` (S. 4, „all third-party iframes that have the __cmpLocator iframe as a parent“) | das Skript läuft in allen Frames einschließlich Hauptframe (`all_frames: true`, `extensions/probe_cmp_postmessage/manifest.json:18`) und fragt alle 2 s neu (`background.js:65–67`) | Kanal 2 nur aus vorhandenen fremden iframes, einmal pro Snapshot (`capture.py`) |
| 4 | nach der Wahl 3 s warten, dann neu laden (V-B) | nach der Wahl 2 s warten (`SLEEP_TIME_COOKIE_WAIT = 2`, `utils.py:29`, `iab_data_collection.py:700`) und auslesen, dann neu laden, 3 s warten (`cookinspect.py:471–472`), erneut auslesen | auslesen nach `useractioncomplete` (höchstens 10 s), nach 3 s neu laden, nach weiteren 3 s erneut auslesen; V4 auf dem Snapshot nach dem Reload |
| 5 | erscheint kein Banner, bis zu 3-mal neu laden (Anhang D) | fehlt im Code (kein Neuladen vor der Wahl) | bis zu 3-mal (`config.MAX_BANNER_RELOADS`), danach Code `b` |
| 6 | Gegenprüfung durch eine zweite Person (V-C) | nicht unterstützt; ein erneuter Lauf setzt Bool-Flags nur auf `True`, nie zurück | eigene Prüfungen mit Rolle, nichts wird überschrieben (`crosscheck.py`, `site_data.py`) |
| 7 | Tab. X: User-Agent `HeadlessChrome/73.0.3683.103`, Software Chromium 76.0.3809.100 | Läufe mit Erweiterungen erzwingen ein sichtbares Fenster (`cookinspect.py:244–247`: „We can't run extensions with headless chrome“); User-Agent und Browserversion in Tab. X passen nicht zueinander | sichtbares Fenster in allen Modi; Versionen von Chrome for Testing, chromedriver und User-Agent werden pro Lauf gespeichert |
| 8 | – | nur im Code: Vendor-Fälle 1–5 über `override_cmp`, Auswertung von `gdpr=0`, Vergleich `vendorConsents`/`consentData`, „different consent strings“ | `gdpr=0` und alle Consent-Felder in Requests werden gespeichert; die Vendor-Fälle sind nicht Teil der Nachmessung |
| 9 | – | für eine v1-Nachstellung den Stand vor dem v2-Commit nehmen (`f32dfda`, vor `88fd048` „update to tcfv2: python code“), wegen F6 | – (wir messen v2.2/v2.3) |

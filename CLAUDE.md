# CLAUDE.md

## Projektkontext

Wir sind ein 2er-Team (Master Medieninformatik, BHT Berlin, Modul „Wissenschaftliches Arbeiten“). Wir messen die Studie von Matte, Bielova & Santos (2020) „Do Cookie Banners Respect my Choice?“ (IEEE S&P 2020, arXiv:1911.09964) für deutsche Websites nach. Das Ergebnis ist ein Short Paper (4–6 Seiten, ACM).

Matte nutzte TCF v1.1 (`__cmp()`, 5 Zwecke) und crawlte 2019 von Frankreich aus. Heute gilt TCF v2.3 (`__tcfapi`, 11 Zwecke), verbindlich seit dem 28.02.2026: Das Segment disclosedVendors ist Pflicht. TC-Strings, die vorher nach v2.2 ohne disclosedVendors erstellt wurden, bleiben gültig. Seit v2.2 ist berechtigtes Interesse für die Zwecke 3–6 nicht mehr erlaubt; daran hat v2.3 nichts geändert. Die `tcfPolicyVersion` im String gibt die Version der TCF-Policies an, nicht die technische TCF-Version (v2.2 → 4, Policies 5.0 seit 2024 → 5; siehe `docs/abweichungen.md`). Seit den TCF Policies v5.0.b (29.05.2026) und den Technical Specifications v2.4 (23.07.2026, mit neuer GVL) gilt v2.4: Sie ergänzt vor allem das GVL-Feld `standardTexts` und Regeln zur Darstellung von Features; der TC-String wird nicht grundlegend geändert (Format v2 bleibt). Frist für CMPs auf Websites (für die neuen Anzeigen im Banner, nicht für den String): 23.10.2026; unsere Messung liegt kurz danach.

Dieses Repo ist eine **Neuimplementierung nach dem Vorbild von Cookinspect (Matte 2020)** für TCF v2.2/v2.3. In Texten und Doku heißt es so, nicht „Portierung“. Ausgangspunkt ist unser Fork azizEr95/Cookinspect (Stand 948a85f).

- Das Paper von Matte liegt unter `docs/` (nur lokal, wird nicht committet). Die Methode steht in Abschnitt IV und V, der Ablauf der manuellen Klicks in Anhang D, die Gegenprüfung in Abschnitt V-C.
- TCF-Spezifikation: <https://github.com/InteractiveAdvertisingBureau/GDPR-Transparency-and-Consent-Framework>
- Cookinspect hat keine Lizenzdatei. Vor einer Veröffentlichung klären wir die Lizenz mit Matte.

## Arbeitsweise

- Vor jeder Änderung: Plan vorschlagen, Rückfragen stellen, auf Bestätigung warten.
- Stand und Plan aller Phasen: `docs/plan.md`. Zu Beginn jeder Sitzung lesen und nach jeder Phase aktualisieren.
- Arbeit auf dem Branch `tcf22-port`, kleine Commits pro Phase. Nichts pushen ohne Zustimmung.
- Lesbarer Code ist wichtiger als effizienter Code.
- Kein Code aus BannerClick oder OpenWPM. Unser eigener Code aus tcfmeasure darf als Vorlage dienen.
- Keinen großen Crawl ohne Freigabe starten. Neue Funktionen zuerst an ca. 10 Websites testen.
- robots.txt in **allen** Modi respektieren (Protego nach RFC 9309; zum Vergleich mit Matte die Entscheidung von `urllib.robotparser` als eigene Spalte). Pausen zwischen Anfragen einhalten.
- Keine Tricks gegen Bot-Erkennung (z. B. kein Verstecken von `navigator.webdriver`). Sperren erkennen, zählen und in den Ergebnissen ausweisen.

## Technik

- Läuft nativ auf macOS (Apple Silicon, arm64), Python 3.12, Selenium 4, Chrome for Testing in fester Version (`config.py`). Keine Browser-Erweiterungen; die Daten kommen über WebDriver BiDi und Selenium.
- Sicheres Umfeld: eigener macOS-Nutzer für die Crawls, frisches Browserprofil pro Sitzung, keine Logins.
- Sichtbares Browserfenster in allen Modi, auch beim automatischen Crawl.
- Datenbank: SQLite mit `sqlite3` (ohne SQLAlchemy). Dekodierung mit `@iabtechlabtcf/core` (Version in `decode/package.json` festgelegt).
- TC-Strings v1 (beginnen mit `B`) werden nur roh gespeichert und als v1 markiert. Die Version wird am String erkannt, nicht am Modus des Laufs.

## Website-Auswahl

- Rangliste: Tranco mit fester List-ID (wird mitgespeichert), derzeit GQ3LK.
- Die ersten N Domains mit Endung .de (N konfigurierbar, Standard 1000), analog zu Matte (1000 pro TLD).
- Vorfilter mit Trichter: Domains → erreichbar und von robots.txt erlaubt → mit TCF. Vergleichswert Matte für .de (Tab. II): 1000 Domains → 881 erreichbar → 56 mit TCF-Banner (6,4 %).
- TCF-Erkennung (analog Matte, S. 5): Nach dem Laden und weiteren 3 s ist `__tcfapi` vorhanden und `ping` antwortet.
- Halbautomatischer Teil: wie bei Matte alle TCF-Seiten aus den ausgewählten Domains (Matte V-B: alle 560 TCF-Seiten der ausgewählten TLDs, keine feste Zahl). Der Parameter für eine Obergrenze (`SEMI_AUTOMATIC_LIMIT`) bleibt für Tests drin, ist standardmäßig aber aus.

## Ablauf

- Automatischer Modus: misst V1 und die Weitergabe an Dritte vor jeder Interaktion, in zwei frischen Sitzungen.
- Halbautomatischer Modus (V2–V4, wie bei Matte): Ein Mensch klickt, das Werkzeug liest mit. Im Messcode wird weder automatisch abgelehnt noch akzeptiert. Das Klicken aus Testskripten (z. B. `spikes/`) darf nicht in den Messcode.
  1. Seite laden. Erscheint kein Banner, bis zu 3-mal neu laden (Anhang D).
  2. Snapshot „vorher“.
  3. Ablehnen nach Anhang D (Regeln unten). Codes: `r` kostenlos ablehnbar (mit der Ebene des Ablehnens), `n` keine Ablehnmöglichkeit, `w` Cookiewall ohne kostenloses Ablehnen, `x` Banner kaputt; `b` (kein Banner) ergibt sich, wenn nach 3-mal Neuladen kein Banner erscheint. Vorausgewählte Optionen (V3) sind kein Code, sondern eigene Felder für Zwecke und Vendoren. Bei `n` wird direkt akzeptiert (Anhang D), bei `w` ebenfalls (zustimmen, nicht bezahlen); eine Ablehnen-Sitzung gibt es dann nicht. Bei `b` und `x` folgt keine weitere Sitzung.
  4. Signal nach `eventStatus = useractioncomplete` auslesen. Kommt das Ereignis nicht innerhalb der Zeitgrenze `USERACTIONCOMPLETE_TIMEOUT` (`config.py`), wird „kein useractioncomplete“ gespeichert und trotzdem ausgelesen, klar markiert.
  5. Nach 3 Sekunden neu laden und erneut auslesen.
  6. Neue Sitzung, dieselben Schritte mit Akzeptieren (nur bei `r`).
- Pro Phase (vorher, nach Ablehnen, nach Reload, nach Akzeptieren) werden alle Zweck- und Vendor-IDs gespeichert, nicht nur Bool-Flags.
- Kanäle: ① `__tcfapi` `addEventListener` im Hauptframe; ② aus Dritt-Position über `__tcfapiLocator`/`__tcfapiCall` aus einem vorhandenen fremden iframe (gibt es keins, wird „nicht messbar“ markiert; niedrige Priorität; die Quote „nicht messbar“ pro Phase – vorher, nach Ablehnen, nach Akzeptieren – erscheint in der Auswertung); Erstanbieter-Cookie `euconsent-v2` und localStorage; Requests an Dritte (GET und POST, auch Formulardaten und iframes): `gdpr_consent`, `gdpr` (inkl. `gdpr=0`), `addtl_consent`, Consent-Felder in OpenRTB-/Prebid-Bodies (z. B. `user.ext.consent`).
- Kein Shared Cookie / consensu.org mehr (gibt es in v2 nicht).

### Regeln für das Ablehnen (Anhang D)

- Gibt es auf der 1. Ebene „Ablehnen“, direkt klicken. Sonst die Einstellungen (2. Ebene) öffnen und dort alle zweckbezogenen Optionen (Checkbox oder Schalter) abwählen, unabhängig von der Art (auch z. B. „funktionale Cookies“).
- „Alle ablehnen“ klicken, auch wenn nichts angehakt ist.
- Vendor-Optionen ignorieren.
- Gibt es keine Einstellungen, nur einen Link zur Datenschutzerklärung: höchstens 10 s dort nach einer Ablehnmöglichkeit suchen, dann zurück zur Hauptseite.
- Liegen die Optionen auf einer anderen Seite, nach dem Ablehnen zurück zur Hauptseite.
- Das Banner immer schließen, und zwar mit der Schaltfläche, die am wenigsten nach Zustimmung klingt.
- Cookiewall (Zustimmen oder bezahlen): Code `w` nur, wenn es **keinen** kostenlosen Weg zum Ablehnen gibt, auch nicht auf der 2. Ebene; dann nicht bezahlen und in derselben Sitzung akzeptieren. Gibt es einen kostenlosen Weg, wird abgelehnt (Code `r` mit der passenden Ebene; Matte lehnt immer ab, wenn es einen Weg gibt, Anhang D), und die Seite wird zusätzlich als Cookiewall markiert.
- Unabhängig vom Code wird gefragt, ob es eine Bezahl-Option gibt (Label-Feld `cookiewall_seen`, ja/nein; bei `w` immer ja).

## Definitionen der Verstöße (als austauschbare Funktionen umsetzen)

- **V1 Zustimmung vor der Wahl:** Vor jeder Interaktion liegt ein TC-String vor, in dem ≥ 1 Zweck in `purpose.consents` gesetzt ist. Berechnet aus dem automatischen Modus: Zählt nur, wenn beide Vorher-Snapshots der zwei Sitzungen das zeigen. Die Vorher-Snapshots des halbautomatischen Modus sind nur eine Ergänzung (bei `n` und `w` gibt es dort nur eine Sitzung). Mattes Variante (≥ 1 Zweck **und** ≥ 1 Vendor-Consent) getrennt speichern.
- **V2 Keine Ablehnmöglichkeit:** getrennt erfassen: Ablehnen auf der 1. Ebene / nur auf der 2. Ebene / gar nicht.
- **V3 Vorausgewählt:** Zwecke sind auf der 2. Ebene vorausgewählt. Vendoren getrennt erfassen.
- **V4 Wahl nicht respektiert:**
  - streng: Nach Ablehnen sind alle Zwecke gesetzt, die auch nach Akzeptieren gesetzt sind. Nur auswertbar, wenn die Zweckmenge nach Akzeptieren **nicht leer** ist; sonst „nicht auswertbar“ (die leere Menge ist Teilmenge von allem).
  - Matte-Variante: streng **und** ≥ 1 Vendor-Consent (entspricht Mattes „alle 5 Zwecke“, da v1.1 nur 5 Zwecke hatte).
  - locker: Nach Ablehnen ist ≥ 1 Zweck in `purpose.consents` gesetzt.
  - Nur als Zusatzzahl: nach Ablehnen alle Zwecke {1…10} bzw. {1…11} gesetzt.
- **Nenner für V3 und V4:** nur Seiten mit Ablehnmöglichkeit. Seiten mit `n`, `b` oder `x` fallen heraus (Matte S. 9: 508 von 560); `w` je nach Konfiguration (siehe Cookiewalls).
- **Berechtigtes Interesse** nach Ablehnen getrennt erfassen, nicht als V4 zählen (`purpose.legitimateInterests`, besonders die Zwecke 3–6).
- **Weitergabe an Dritte** (wie Matte, Abschnitt VIII-A): TC-Strings mit Zustimmung in Requests an Dritte getrennt ausweisen, (a) vor jeder Aktion und (b) nach Ablehnen.
- **Cookiewalls** (Pay-or-OK): Ausgewertet wird erst, wenn die Daten des automatischen Crawls vorliegen. Davon hängt auch ab, ob die Forschungsfrage um Cookiewalls erweitert wird. Bis dahin:
  - Der automatische Modus erkennt und markiert Cookiewalls (Heuristik), der halbautomatische Modus markiert sie mit `cookiewall_seen` und, ohne kostenloses Ablehnen, mit `w`.
  - Die Verstoß-Logik verdrahtet `w` nicht fest. Der Umgang ist konfigurierbar (z. B. „ausschließen“ oder „als V2 zählen“); bis zur Entscheidung werden beide Varianten ausgewiesen.

## Gegenprüfung (Matte, Abschnitt V-C)

- Die beiden Personen teilen die Seiten auf (z. B. je die Hälfte). Jedes Ergebnis wird mit dem Kürzel der Person gespeichert, nichts wird überschrieben.
- Betrifft V4 und V2. Pro CMP mit Verstoß: eine verstoßende Seite und gleich viele unauffällige Seiten. Die andere Person prüft sie blind, ohne das erste Ergebnis zu kennen.
- Bei Abweichung zählt das mildere Ergebnis, **und** alle Seiten dieser CMP werden neu geprüft.

## Reproduzierbarkeit (nach Demir et al.)

- Bei jedem Lauf automatisch protokollieren: Datum, Standort/IP-Land, Version von Chrome for Testing und chromedriver, Selenium-Version, Version des Decoders, GVL-Version, Version der CMP-Liste, Wartezeiten, Konfiguration, Tranco-List-ID, Git-Commit.
- Abweichungen vom Paper und vom ursprünglichen Cookinspect stehen nur in `docs/abweichungen.md` (einziger Stand).
- Die README erklärt, wie man alles ausführt.

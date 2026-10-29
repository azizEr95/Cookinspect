# Entscheidungen

## E1 (Phase 1, 2026-10-29): Datenerfassung ohne Browser-Erweiterungen

**Frage:** Lassen sich alle Kanäle von Cookinspect ohne die 7 MV2-Erweiterungen erfassen, über das Chrome DevTools Protocol (CDP) und Selenium?

**Ergebnis:** Ja, aber nicht mit CDP allein. Wir nehmen **WebDriver BiDi** (W3C-Standard, in Selenium 4.51 und chromedriver 156 eingebaut) für Netzwerk und Listener, dazu klassisches WebDriver für Kanal ②. Erweiterungen braucht es keine, Site Isolation bleibt an, der Browser bleibt unverändert.

**Aufbau des Tests** (`spikes/cdp/`, Wegwerfcode):

- `server.py` und `site/`: lokale Testseite auf zwei Origins. `localhost:8001` ist die Seite mit einer kleinen CMP nach der TCF-v2.2-API (inkl. `__tcfapiLocator` und postMessage), `127.0.0.1:8002` ein fremdes iframe. Es sind zwei verschiedene Sites, deshalb läuft das iframe in einem eigenen Renderer-Prozess wie ein echtes Werbe-iframe. Beide senden markierte Requests: GET mit `gdpr_consent`/`addtl_consent`, POST mit JSON (`user.ext.consent`), POST mit Formulardaten (`gdpr=0`), `sendBeacon`. Der Server protokolliert, was ankommt (Grundwahrheit).
- `spike.py`: Kriterien K1–K5 lokal (`local`) und an echten Seiten (`real`, `real-accept`), mit Prüfung der robots.txt.
- `spike_k1.py`: zwei Auswege für K1 im Vergleich.
- `spike_k3.py`: Listener, der das Neuladen der Seite übersteht.
- Chrome for Testing 156.0.8078.73 (mac-arm64), Selenium 4.51.0, Apple M4.
- Echte Seiten: t-online.de, spiegel.de, welt.de, focus.de, wetteronline.de (TCF-Seiten aus dem Pilot, alle von robots.txt erlaubt, alle mit Sourcepoint). Akzeptiert wurde im Test nur auf wetteronline.de, durch einen Klick des Testskripts. Auf spiegel.de fand das Testskript den Button im CMP-iframe nicht. Im Werkzeug selbst klickt immer ein Mensch.

### Ergebnis je Kriterium

| | Kriterium | CDP (erster Versuch) | Lösung | Beleg |
|---|---|---|---|---|
| K1 | Requests aus fremden iframes (eigener Prozess) | **nein**: Das Performance-Log von chromedriver enthält nur den Hauptframe. 4 von 8 markierten Requests fehlen. | BiDi `network.beforeRequestSent`: 8/8, mit Browsing-Context des iframes | lokal 8/8; wetteronline.de nach Akzeptieren 1.265 Consent-Requests aus iframes |
| K2 | POST-Bodies (JSON, Formular, `sendBeacon`) | ja (Hauptframe) | BiDi `network.addDataCollector` mit Typ `request` und `network.getData`: alle Bodies, auch aus dem iframe | lokal 8/8; wetteronline.de 19 POST mit OpenRTB-Body (Prebid) |
| K3 | Listener vor den Seitenskripten, aktiv nach Reload | ja (`Page.addScriptToEvaluateOnNewDocument`), **aber**: Die Ereignisse liegen im `window` und gehen verloren, wenn die CMP die Seite nach der Wahl neu lädt. Auf wetteronline.de fehlte so `useractioncomplete`. | BiDi `script.addPreloadScript` mit Kanal (`script.message`): Jedes Ereignis geht sofort an Python und übersteht Reloads | lokal: `useractioncomplete` vor dem Reload durch die Seite erhalten; wetteronline.de: `cmpuishown` → `useractioncomplete` → `tcloaded`. Echte Seiten: Registrierung 50–180 ms nach Dokumentstart, erster Status `cmpuishown`. |
| K4 | Kanal ② aus Dritt-Position | – | `switch_to.frame` in ein vorhandenes fremdes iframe, `__tcfapiCall` (`ping`, `addEventListener`) per postMessage an den Locator-Frame | lokal vor und nach dem Klick (TC-String wechselt); wetteronline.de vorher (radar.wo-cloud.com) und nachher (adnami.io) |
| K5 | Cookie `euconsent-v2` und localStorage | ja (CDP `Storage.getCookies`, `execute_script`) | wie getestet; BiDi `storage.getCookies` wird in Phase 3 geprüft | wetteronline.de: `euconsent-v2` auf `.wetteronline.de` nach Akzeptieren; Sourcepoint-Einträge `_sp_user_consent_*` im localStorage auf allen 5 Seiten |

### Ausweg Site Isolation

Das Performance-Log mit `--disable-features=IsolateOrigins,site-per-process` erfasst lokal ebenfalls 8/8. Wir nehmen ihn **nicht**, weil er das Verhalten des Browsers ändert und BiDi dasselbe ohne Eingriff leistet. Er bleibt als Rückfalloption.

### Gründe für BiDi

1. Es ist das einzige getestete Mittel, das K1 erfüllt, ohne den Browser zu verändern.
2. Netzwerk und Listener-Ereignisse kommen als Ereignisse direkt nach Python. Es gibt keinen Umweg über Konsolen-Logs und Regex (die Ursache von F2/F3 im alten Code).
3. Es ist ein W3C-Standard, also weniger abhängig von internen Details von chromedriver als das Performance-Log.
4. Es braucht keine packbaren Erweiterungen, keinen Service Worker und keine Erlaubnis für `--load-extension`.

### Grenzen und offene Punkte (in Phase 3 prüfen)

- **Kanal ② ist oft nicht messbar:** Vor jeder Aktion gab es nur auf 1 von 5 Seiten ein fremdes iframe. Werbe-iframes laden meist erst nach der Zustimmung, nach dem Ablehnen also vermutlich selten. Wie vereinbart wird das als „nicht messbar“ markiert. Die Quote gehört in die Ergebnisse.
- Ob Requests aus iframes in iframes (verschachtelt) und von Service Workern erfasst werden, ist nicht einzeln geprüft (wetteronline.de hatte viele Frames, aber ohne gezielte Kontrolle).
- Bodies über der Grenze des Data Collectors (im Test 1 MB) fehlen; das wird gespeichert („Body zu groß“).
- Die BiDi-Callbacks laufen in einem eigenen Thread; der Zugriff braucht eine Sperre (im Test vorhanden).
- Der Zeitpunkt des BiDi-Preload-Skripts relativ zu den Seitenskripten ist lokal nur für die CDP-Variante gemessen (`pageSawInjection = true`); für BiDi wird das in den Tests von Phase 3 nachgeholt.
- Nach unserem eigenen Reload kam auf wetteronline.de `tcloaded` zweimal (zwei Listener-Registrierungen aus zwei Dokumenten). Bei der Auswertung pro Phase muss das Dokument (Navigation) mitgespeichert werden.

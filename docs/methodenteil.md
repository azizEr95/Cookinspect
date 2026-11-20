# Methodenteil (Entwurf)

Entwurf für den Methodenteil des Short Papers. Platzhalter in eckigen Klammern werden nach der Messung ausgefüllt (Werte aus `run_metadata.json` der Läufe und aus `data/evaluation-messung-<Zeit>/tables.md`).

> Wir messen die Studie von Matte et al. für deutsche Websites nach, mit einer Neuimplementierung ihres Werkzeugs Cookinspect für TCF v2.2/v2.3. Ausgangspunkt sind die ersten 1000 `.de`-Domains der Tranco-Liste GQ3LK. Ein Vorfilter behält die erreichbaren und nach robots.txt (RFC 9309) erlaubten Seiten, auf denen nach dem Laden und weiteren 3 s die TCF-API (`__tcfapi`) auf `ping` antwortet: [N erreichbar] von 1000 Domains, davon [N TCF] mit TCF. Eine dieser Seiten verbot nach dem Vorfilter das Laden per robots.txt und wurde nicht gemessen; V1 bis V4 beziehen sich daher auf [250] der [251] TCF-Seiten. Ein automatischer Crawl misst in zwei frischen Browsersitzungen ohne jede Interaktion, ob schon vor der Wahl eine Zustimmung gespeichert wird (V1) und ob TC-Strings mit Zustimmung an Dritte gesendet werden. Im halbautomatischen Crawl lehnt eine Person im sichtbaren Browser nach dem Protokoll von Matte et al. (Anhang D) ab und stimmt in einer zweiten Sitzung zu; bei Seiten ohne kostenloses Ablehnen wird nur zugestimmt. Sie hält fest, ob und auf welcher Ebene Ablehnen möglich ist (V2), ob Optionen vorausgewählt sind (V3) und ob eine Bezahl-Option angeboten wird (Cookiewall). Das Werkzeug liest dabei über WebDriver BiDi die TCF-API, Erstanbieter-Cookies, localStorage und Requests an Dritte mit und klickt selbst nie. V4 vergleicht die Zwecke im TC-String nach dem Ablehnen mit denen nach dem Zustimmen, jeweils nach einem Neuladen der Seite. Alle TC-Strings werden mit der offiziellen Bibliothek des IAB Tech Lab dekodiert und gegen die zum String passende Version der Global Vendor List geprüft. Wie bei Matte et al. wurden alle TCF-Seiten halbautomatisch geprüft, anders als dort aufgeteilt auf zwei Personen: Innerhalb jeder CMP wurden die Seiten nach Tranco-Rang abwechselnd zugeteilt. Nach Abschnitt V-C prüfte jede Person blind eine Stichprobe der Seiten der anderen zu V2 und V4 nach; Cookiewalls ohne kostenloses Ablehnen zählten bei der Auswahl für V2 als Verstoß. Bei Abweichungen zählt das mildere Ergebnis, und alle Seiten der betroffenen CMP werden neu geprüft. 18 Seiten. Eine Abweichung ging auf einen Eingabefehler in der ersten Prüfung zurück, nach dessen Korrektur stimmten alle Einstufungen überein. Gemessen wurde aus [Standort, z. B. Berlin] mit Chrome for Testing [Version] auf macOS ([Version], Apple Silicon): der automatische Modus am [Datum], der halbautomatische Crawl vom [Datum] bis [Datum].

Cookiewalls (Entwurf):

> Wir weisen V2 in zwei Varianten aus. In der ersten zählen Cookiewalls ohne kostenloses Ablehnen als eigene Kategorie. In der zweiten zählen sie als „No way to opt out“, analog zum Fall healthline.com bei Matte et al. (Anhang D: Ablehnen war möglich, danach wurde der Zugang verweigert). Die Rechtslage ist umstritten: Der EDPB hält Einwilligungen bei Cookiewalls für nicht freiwillig (Guidelines 05/2020, Rn. 39), die deutsche DSK hält Pur-Abo-Modelle unter Bedingungen für zulässig (Beschluss vom 22.03.2023).

Literatur (vorgemerkt):

- Morel et al. (2022): „Your Consent Is Worth 75 Euros A Year“. WPES 2022, arXiv:2209.09946.
- Morel et al. (2023): „Legitimate Interest is the New Consent“. WPES 2023, arXiv:2309.11625.

Offen für die endgültige Fassung:

- Zahlen: [N erreichbar], [N TCF].
- Zeitraum, Standort, Chrome-Version und macOS-Version aus den Metadaten der Messläufe.

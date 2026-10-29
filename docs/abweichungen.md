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
| robots.txt: Modi | Paper: robots.txt respektiert; Code: `-a` und `-t` prüfen, laden die Seite aber trotzdem (`bypass_robots_txt=True`), nur `-a2` hält sich daran | in allen Modi respektiert, keine Umgehung | wie im Paper beschrieben |
| robots.txt: User-Agent | Regeln für den User-Agent-String des Browsers (urllib nutzt davon nur „Mozilla“) | Regeln für `*` | in der Praxis gleich; einfacher nachvollziehbar |
| Shared Cookie / consensu.org | Kanal ③ | entfällt; stattdessen Erstanbieter-Cookie `euconsent-v2` und localStorage | in TCF v2 gibt es keinen globalen Consent mehr |

## Technische Grenzen

| Grenze | Auswirkung |
|---|---|
| Request-Bodies über 1 MB (Grenze des BiDi-Data-Collectors) werden nicht gespeichert, sondern als „Body zu groß“ markiert. | Ein Consent-String in einem so großen POST-Body würde nicht erkannt. |
| Kanal ② (Dritt-Position) ist nur messbar, wenn die Seite ein fremdes iframe enthält. | Ohne fremdes iframe: „nicht messbar“; die Quote wird pro Phase ausgewiesen. |

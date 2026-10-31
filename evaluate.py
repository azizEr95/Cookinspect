"""Evaluation (Phase 8): computes all violations per site from the database (site_data.py,
violations.py) and writes them as CSV and as Markdown tables comparable with Matte et al.
(2020), Tab. II and Tab. III. Nothing is written to the database.

    venv/bin/python evaluate.py --test
    venv/bin/python evaluate.py --purpose messung

Output in data/evaluation-<purpose>-<time>/:
  sites.csv     one row per site with all results (and the reason where not evaluable)
  tables.md     the tables (Tab. II, Tab. III with the mapping to Matte, details, extra figures)
  tables.json   the same numbers for further use
"""
import argparse
import csv
import json
import time
from collections import Counter
from functools import lru_cache

import config
import database
import prefilter
import site_data
import violations as v
from consent_lists import load_gvl
from site_data import MAIN_CHANNELS, MATTE_CHANNELS, session_of

PHASES = ("before", "after_reject", "after_reject_reload", "after_accept", "after_accept_reload")

# Matte et al. (2020), Tab. III (semi-automatic crawl: 560 sites, 508 with a way to refuse)
MATTE_TAB_III = {
    "v1_some": "2,1 % (30/1426)", "v1_all": "7,8 % (111/1426)", "v1": "9,9 % (141/1426)",
    "v2": "6,8 % (38/560)", "v3": "46,5 % (236/508)",
    "v4_some": "6,7 % (34/508)", "v4_all": "5,3 % (27/508)", "v4": "5,3 % (27/508)", "any": "54,29 % (304/560)"}


@lru_cache(maxsize=None)
def gvl_for(vendor_list_version, policy_version):
    return load_gvl(vendor_list_version, policy_version)


# --- per site

def evaluate_site(site):
    """All results of one site, as {name: result of violations.py}."""
    automatic, semi = site["automatic"], site["semi"]
    label = semi["label"] if semi else None
    results = {
        "v1": v.v1(automatic),
        "v1_matte_variant": v.v1(automatic, matte_variant=True),
        "v1_matte_channels": v.v1(automatic, channels=MATTE_CHANNELS),
        "v3_purposes": v.v3(label, "purposes"),
        "v3_vendors": v.v3(label, "vendors"),
        "v3_either_matte": v.v3(label, "either", matte_denominator=True),
        "li_after_reject": v.li_after_reject(semi, gvl_for),
        "transfer_before": v.transfer_before(automatic),
        "transfer_after_reject": v.transfer_after_reject(semi),
    }
    for handling in v.COOKIEWALL_HANDLINGS:
        results[f"v2_{handling}"] = v.v2(label, handling)
    for variant in ("strict", "matte", "lax", "all10", "all11"):
        results[f"v4_{variant}"] = v.v4(semi, variant)
    for variant in ("strict", "matte", "lax"):
        results[f"v4_{variant}_matte_channels"] = v.v4(semi, variant, channels=MATTE_CHANNELS)
        results[f"v4_{variant}_action"] = v.v4(semi, variant, moment="action")
    results["e5"] = {phase: v.undisclosed_consent(phase_of(site, phase)) for phase in PHASES}
    results["e5_unknown"] = {phase: v.unknown_vendor_consent(phase_of(site, phase)) for phase in PHASES}
    return results


def phase_of(site, phase):
    """The snapshot of a phase: "before" from automatic session 1, the others from the
    semi-automatic examination that counts."""
    if phase == "before":
        sessions = site["automatic"]["sessions"] if site["automatic"] else []
        return sessions[0]["phases"].get("before") if sessions else None
    session = session_of(site["semi"], "reject" if "reject" in phase else "accept") if site["semi"] else None
    return session["phases"].get(phase) if session else None


def cookiewall_flags(site):
    label = site["semi"]["label"] if site["semi"] else None
    return {"heuristic": bool(site["automatic"]["cookiewall_suspected"]) if site["automatic"] else None,
            "heuristic_reason": site["automatic"]["cookiewall_reason"] if site["automatic"] else None,
            "cookiewall_seen": None if label is None or label["cookiewall_seen"] is None else bool(label["cookiewall_seen"]),
            "w": None if label is None else label["outcome"] == "w"}


def csv_row(site, results):
    label = site["semi"]["label"] if site["semi"] else None
    flags = cookiewall_flags(site)
    row = {"rank": site["rank"], "domain": site["domain"], "cmp_id": site["cmp_id"],
           "code": {"rejected": "r"}.get(label["outcome"], label["outcome"]) if label else None,
           "reject_level": label["reject_level"] if label else None,
           "operator": site["semi"]["operator"] if site["semi"] else None, "source": site["source"],
           "crosscheck_differs": site["crosscheck"]["differs"] if site["crosscheck"] else None,
           "cookiewall_heuristic": flags["heuristic"], "cookiewall_seen": flags["cookiewall_seen"], "w": flags["w"]}
    for name, r in results.items():
        if name in ("e5", "e5_unknown"):
            for phase, phase_result in r.items():
                row[f"{name}_{phase}"] = phase_result["value"]
            continue
        row[name] = r["value"]
        if r["value"] == v.NA:
            row[f"{name}_reason"] = r["reason"]
    row["v2_level"] = results["v2_exclude"].get("level")
    row["v4_purposes_after_reject"] = " ".join(map(str, results["v4_lax"].get("purposes_after_reject", [])))
    row["v4_purposes_after_accept"] = " ".join(map(str, results["v4_strict"].get("purposes_after_accept", [])))
    differs = v.v4_action_differs(site["semi"])
    row["v4_action_differs_reject"], row["v4_action_differs_accept"] = differs.get("reject"), differs.get("accept")
    li = results["li_after_reject"]
    row["li_purposes"] = " ".join(map(str, li.get("purpose_li", [])))
    row["li_purposes_3_6"] = " ".join(map(str, li.get("purpose_li_3_6", [])))
    row["li_vendors"], row["li_vendors_special_purpose_only"] = li.get("vendor_li"), li.get("vendor_li_special_purpose_only")
    row["transfer_before_requests"] = " / ".join(map(str, results["transfer_before"].get("requests", [])))
    row["transfer_after_reject_requests"] = results["transfer_after_reject"].get("requests")
    row["warnings"] = "; ".join(site["warnings"]) or None
    return row


# --- counting

def count(results, name, condition=None):
    """(hits, evaluable, not evaluable) over all sites; condition(result) decides a hit
    (default: value "ja")."""
    values = [r[name] for r in results.values()]
    hits = sum(1 for r in values if (condition(r) if condition else r["value"] == v.YES))
    evaluable = sum(1 for r in values if r["value"] != v.NA)
    return hits, evaluable, len(values) - evaluable


def percent(hits, denominator):
    if not denominator:
        return f"– (0/{denominator})"
    return f"{100 * hits / denominator:.1f} % ({hits}/{denominator})".replace(".", ",", 1)


def figure(results, name, condition=None):
    hits, evaluable, na = count(results, name, condition)
    return {"hits": hits, "denominator": evaluable, "not_evaluable": na, "text": percent(hits, evaluable)}


def reasons(results, name):
    return Counter(r[name]["reason"] for r in results.values() if r[name]["value"] == v.NA)


# --- tables

def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join("" if c is None else str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def tab_ii(conn, purpose):
    """Funnel of the latest prefilter run of the purpose, as in prefilter.py."""
    run = conn.execute("SELECT id, started_at FROM run WHERE mode = 'prefilter' AND purpose = ? ORDER BY started_at DESC",
                       (purpose,)).fetchone()
    if run is None:
        return None, "Kein Vorfilter-Lauf in dieser Datenbank."
    rows = []
    for row in conn.execute("SELECT * FROM prefilter_result WHERE run_id = ?", (run["id"],)):
        row = dict(row)
        flags = ("robots_allowed_urllib", "robots_allowed_cookinspect", "loaded", "blocked", "tcfapi", "tcf")
        rows.append({**row, **{f: bool(row[f]) for f in flags}, "robots_allowed": bool(row["robots_allowed_protego"])})
    funnel = prefilter.funnel(rows)
    return funnel, f"Vorfilter-Lauf {run['id']} vom {run['started_at']}.\n\n" + prefilter.funnel_table(funnel)


def tab_iii(results, semi_sites):
    """Tab. III of Matte: violations w.r.t. the number of purposes, with our variants."""
    v1_all = figure(results, "v1", lambda r: r["value"] == v.YES and r.get("all_purposes"))
    v1_some = figure(results, "v1", lambda r: r["value"] == v.YES and not r.get("all_purposes"))
    v1_total = figure(results, "v1")
    v4_all = figure(results, "v4_matte")
    # as Matte's row "1 to 4 purposes": lax, but not the Matte variant
    v4_some = figure(results, "v4_lax", lambda r: r["value"] == v.YES)
    lax_only = sum(1 for r in results.values() if r["v4_lax"]["value"] == v.YES and r["v4_matte"]["value"] != v.YES)
    v4_some.update(hits=lax_only, text=percent(lax_only, v4_some["denominator"]))
    v2 = {h: figure(semi_sites, f"v2_{h}") for h in v.COOKIEWALL_HANDLINGS}
    v3 = figure(results, "v3_either_matte")
    any_main = sum(1 for r in semi_sites.values() if any_violation(r))
    figures = {"v1_some": v1_some, "v1_all": v1_all, "v1": v1_total, "v2": v2, "v3": v3,
               "v4_some": v4_some, "v4_all": v4_all, "v4": v4_all,
               "any": {"hits": any_main, "denominator": len(semi_sites), "text": percent(any_main, len(semi_sites))}}
    v2_text = " / ".join(f"{v2[h]['text']} ({v.COOKIEWALL_TEXT[h]})" for h in v.COOKIEWALL_HANDLINGS)
    rows = [
        ["1 bis weniger als alle Zwecke", f"{v1_some['text']} [Matte {MATTE_TAB_III['v1_some']}]", "–", "–",
         f"{v4_some['text']} [Matte {MATTE_TAB_III['v4_some']}]"],
        ["alle Zwecke (1–11, bei Policy < 4: 1–10)", f"{v1_all['text']} [Matte {MATTE_TAB_III['v1_all']}]", "–", "–",
         f"{v4_all['text']} [Matte {MATTE_TAB_III['v4_all']}]"],
        ["**Gesamt (gewertete Fälle)**", f"**{v1_total['text']}** [Matte {MATTE_TAB_III['v1']}]",
         f"**{v2_text}** [Matte {MATTE_TAB_III['v2']}]", f"**{v3['text']}** [Matte {MATTE_TAB_III['v3']}]",
         f"**{v4_all['text']}** [Matte {MATTE_TAB_III['v4']}]"],
    ]
    text = table(["Anzahl Zwecke", "V1 Zustimmung vor der Wahl", "V2 Keine Ablehnmöglichkeit",
                  "V3 Vorausgewählt", "V4 Wahl nicht respektiert"], rows)
    text += (f"\n\nIrgendein Verstoß (V1 Hauptzahl, V2 mit w ausgeschlossen, V3 Zwecke oder Vendoren, "
             f"V4 Matte-Variante): **{figures['any']['text']}** [Matte {MATTE_TAB_III['any']}]")
    return figures, text


TAB_III_MAPPING = """Zuordnung zu Matte Tab. III:

- V1 Gesamt ↔ „1 to 5 purposes“ (Spalte „Consent stored before choice“, Summe beider Zeilen): Kanal 1, beide Vorher-Snapshots des automatischen Modus zeigen ≥ 1 Zweck. Zeile „alle Zwecke“ ↔ „5 purposes“, Zeile „1 bis weniger als alle“ ↔ „1 to 4 purposes“. Nenner: alle auswertbaren Seiten des automatischen Modus (Matte: 1426 TCF-Seiten); nicht auswertbare Seiten (E7) stehen unten.
- V2 ↔ „No way to opt out“: Code `n` (Ablehnen gar nicht möglich); `w` je nach Variante ausgeschlossen oder als V2 gezählt. Nenner: alle halbautomatisch geprüften Seiten mit gültigem Ergebnis (Matte: 560).
- V3 ↔ „Pre-selected choices“: Zwecke **oder** Vendoren vorausgewählt; Nenner wie bei Matte alle Seiten mit kostenloser Ablehnmöglichkeit (Matte: 508), ohne 2. Ebene = nicht vorausgewählt. Die Hauptzahl mit dem Nenner „2. Ebene vorhanden“ steht unten (V3).
- V4 Matte-Variante ↔ „5 purposes“ (in Tab. III fett, gewertet): nach Ablehnen alle Zwecke gesetzt, die nach Akzeptieren gesetzt sind, und ≥ 1 Vendor-Consent. V4 locker (≥ 1 Zweck nach Ablehnen) ↔ „1 to 4 purposes“ zusammen mit „5 purposes“; die Zeile „1 bis weniger als alle“ zeigt locker **ohne** die Matte-Variante, wie Mattes Zeile „1 to 4 purposes“ (dort nicht gewertet). Nenner: Seiten mit Code `r` und auswertbarem Snapshot (Matte: 508). Berechnet auf den Snapshots nach dem Reload.
- Irgendein Verstoß ↔ „Any violation“ (Matte: 304/560)."""


def any_violation(r):
    return (r["v1"]["value"] == v.YES or r["v2_exclude"]["value"] == v.YES
            or r["v3_either_matte"]["value"] == v.YES or r["v4_matte"]["value"] == v.YES)


def details(results, semi_sites, sites):
    """The tables below Tab. III: all variants, the reasons for "nicht auswertbar", extra figures."""
    parts = []

    def block(title, rows, header=("Kennzahl", "Anteil", "nicht auswertbar")):
        parts.append(f"### {title}\n\n" + table(list(header), rows))

    def line(label, name, source=results, condition=None):
        f = figure(source, name, condition)
        return [label, f["text"], f["not_evaluable"]]

    block("V1 Zustimmung vor der Wahl (automatischer Modus, beide Sitzungen)", [
        line("V1 Hauptzahl (Kanal 1, ≥ 1 Zweck)", "v1"),
        line("V1 Matte-Variante (≥ 1 Zweck und ≥ 1 Vendor)", "v1_matte_variant"),
        line("V1 Matte-Kanäle (irgendein Kanal: 1, 2, Cookie, localStorage)", "v1_matte_channels")])
    parts.append("Nicht auswertbar (V1, E7): " + format_reasons(reasons(results, "v1")))

    rows = []
    for handling in v.COOKIEWALL_HANDLINGS:
        levels = Counter(r[f"v2_{handling}"].get("level") for r in semi_sites.values()
                         if r[f"v2_{handling}"]["value"] != v.NA)
        denominator = sum(levels.values())
        rows.append([v.COOKIEWALL_TEXT[handling], percent(levels["1. Ebene"], denominator),
                     percent(levels["nur 2. Ebene"], denominator),
                     percent(levels["gar nicht"] + levels["gar nicht (Cookiewall)"], denominator)])
    block("V2 Ablehnen nach Ebene", rows, ("Variante", "1. Ebene", "nur 2. Ebene", "gar nicht"))

    block("V3 Vorausgewählt (Nenner: Code r und 2. Ebene vorhanden; „?“ = nicht geprüft, außerhalb des Nenners)", [
        line("Zwecke vorausgewählt", "v3_purposes"), line("Vendoren vorausgewählt", "v3_vendors"),
        line("Zwecke oder Vendoren (Nenner wie Matte: alle r)", "v3_either_matte")])
    not_checked = {what: sum(1 for r in results.values() if r[f"v3_{what}"]["reason"] == "nicht geprüft")
                   for what in ("purposes", "vendors")}
    parts.append(f"Nicht geprüft („?“): Zwecke {not_checked['purposes']}, Vendoren {not_checked['vendors']}.")

    block("V4 Wahl nicht respektiert (Snapshots nach dem Reload)", [
        line("streng (Kanal 1)", "v4_strict"), line("Matte-Variante (streng und ≥ 1 Vendor)", "v4_matte"),
        line("locker (≥ 1 Zweck nach Ablehnen)", "v4_lax"),
        line("streng, Matte-Kanäle", "v4_strict_matte_channels"),
        line("Matte-Variante, Matte-Kanäle", "v4_matte_matte_channels"),
        line("locker, Matte-Kanäle", "v4_lax_matte_channels"),
        line("Zusatzzahl: nach Ablehnen alle Zwecke 1–10", "v4_all10"),
        line("Zusatzzahl: nach Ablehnen alle Zwecke 1–11", "v4_all11")])
    parts.append("Nicht auswertbar (V4 streng): " + format_reasons(reasons(results, "v4_strict")))
    differs = [v.v4_action_differs(site["semi"]) for site in sites.values() if site["semi"]]
    differ_rows = []
    for kind, text in (("reject", "Ablehnen"), ("accept", "Akzeptieren")):
        compared = [d[kind] for d in differs if d.get(kind) is not None]
        missing = sum(1 for d in differs if kind in d and d[kind] is None)
        differ_rows.append([f"nach {text}: direkt nach der Aktion ≠ nach Reload", percent(sum(compared), len(compared)),
                            missing])
    block("V4 Snapshot direkt nach der Aktion (getrennt ausgewiesen)", [
        line("streng, direkt nach der Aktion", "v4_strict_action"),
        line("Matte-Variante, direkt nach der Aktion", "v4_matte_action"),
        line("locker, direkt nach der Aktion", "v4_lax_action"), *differ_rows])

    li = [r["li_after_reject"] for r in results.values() if r["li_after_reject"]["value"] != v.NA]
    block("Berechtigtes Interesse nach Ablehnen (nicht als V4 gezählt)", [
        ["Zwecke mit LI", percent(sum(1 for r in li if r["purpose_li"]), len(li)), ""],
        ["davon Zwecke 3–6 (seit v2.2 nicht erlaubt)", percent(sum(1 for r in li if r["purpose_li_3_6"]), len(li)), ""],
        ["Vendoren mit LI", percent(sum(1 for r in li if r["vendor_li"]), len(li)), ""],
        ["Vendor-LI nur für Vendoren mit ausschließlich Special Purposes",
         percent(sum(1 for r in li if r["vendor_li_special_purpose_only"]), len(li)),
         sum(1 for r in li if r["vendor_li_special_purpose_only"] is None)],
        ["Vendor-LI für andere Vendoren", percent(sum(1 for r in li if r["vendor_li_other"]), len(li)), ""]],
        ("Kennzahl", "Anteil (Seiten mit String nach Ablehnen)", "GVL nicht verfügbar"))

    block("Weitergabe an Dritte (TC-String mit ≥ 1 Zweck in Requests an Dritte)", [
        line("(a) vor jeder Aktion, beide Sitzungen (automatischer Modus)", "transfer_before"),
        line("(a) vor jeder Aktion, mindestens eine Sitzung", "transfer_before",
             condition=lambda r: r.get("any_session")),
        line("(b) nach Ablehnen", "transfer_after_reject")])

    flags = {d: cookiewall_flags(site) for d, site in sites.items()}
    labeled = [f for f in flags.values() if f["w"] is not None]
    block("Cookiewalls (Pay-or-OK)", [
        ["Bezahl-Option gesehen (`cookiewall_seen`)", percent(sum(1 for f in labeled if f["cookiewall_seen"]), len(labeled)), ""],
        ["Code w (kein kostenloses Ablehnen)", percent(sum(1 for f in labeled if f["w"]), len(labeled)), ""],
        ["Bezahl-Option mit kostenlosem Ablehnen (r)", percent(sum(1 for f in labeled if f["cookiewall_seen"] and not f["w"]),
                                                        len(labeled)), ""],
        ["Heuristik (automatischer Modus)", percent(sum(1 for f in flags.values() if f["heuristic"]),
                                                    sum(1 for f in flags.values() if f["heuristic"] is not None)), ""]],
        ("Kennzahl", "Anteil", ""))

    parts.append(e6(flags))

    for name, title, column in (
            ("e5", "E5 Consent für nicht offengelegte Vendoren (vendorConsents ohne disclosedVendors; nur Strings "
                   "mit dem Segment)", "Seiten mit Consent außerhalb disclosedVendors"),
            ("e5_unknown", "E5 Consent für Vendoren, die in der GVL des Strings fehlen (wie Matte, Anhang F)",
             "Seiten mit Consent für unbekannte Vendoren")):
        rows = []
        for phase in PHASES:
            values = [r[name][phase] for r in results.values()]
            evaluable = [x for x in values if x["value"] != v.NA]
            rows.append([phase, percent(sum(1 for x in evaluable if x["value"] == v.YES), len(evaluable)),
                         len(values) - len(evaluable)])
        block(title, rows, ("Phase", column, "nicht auswertbar"))

    channel_2 = Counter()
    for domain, site in sites.items():
        for phase in PHASES:
            status = v.channel_2_status(phase_of(site, phase))
            if status:
                channel_2[(phase, status == "not_measurable")] += 1
    block("Kanal 2 „nicht messbar“ pro Phase", [
        [phase, percent(channel_2[(phase, True)], channel_2[(phase, True)] + channel_2[(phase, False)]), ""]
        for phase in PHASES], ("Phase", "nicht messbar", ""))
    return "\n\n".join(parts)


def e6(flags):
    """E6: heuristic of the automatic mode against w and against cookiewall_seen."""
    parts = ["### E6 Cookiewall-Heuristik (automatischer Modus) gegen die Labels"]
    both = {d: f for d, f in flags.items() if f["heuristic"] is not None and f["w"] is not None}
    for name, text in (("w", "Code w"), ("cookiewall_seen", "Bezahl-Option gesehen")):
        pairs = [(f["heuristic"], bool(f[name])) for f in both.values() if f[name] is not None]
        tp = sum(1 for h, m in pairs if h and m)
        fp = sum(1 for h, m in pairs if h and not m)
        fn = sum(1 for h, m in pairs if not h and m)
        tn = sum(1 for h, m in pairs if not h and not m)
        parts.append(f"Heuristik gegen {text} ({len(pairs)} Seiten in beiden Modi):\n\n" + table(
            ["", f"{text}: ja", f"{text}: nein"], [["Heuristik: ja", tp, fp], ["Heuristik: nein", fn, tn]])
            + f"\n\nÜbereinstimmung {percent(tp + tn, len(pairs))}, Präzision {percent(tp, tp + fp)}, "
              f"Trefferquote {percent(tp, tp + fn)}.")
    deviations = [[d, f["heuristic"], f["w"], f["cookiewall_seen"], f["heuristic_reason"]] for d, f in both.items()
                  if f["heuristic"] != f["w"] or (f["cookiewall_seen"] is not None and f["heuristic"] != f["cookiewall_seen"])]
    if deviations:
        parts.append("Abweichungen:\n\n" + table(["Seite", "Heuristik", "w", "Bezahl-Option", "Grund der Heuristik"],
                                                  deviations))
    return "\n\n".join(parts)


def format_reasons(counter):
    return "; ".join(f"{reason} ({n})" for reason, n in counter.most_common()) or "keine"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test", action="store_true", help="data/test.sqlite")
    parser.add_argument("--purpose", choices=["vorab", "messung"])
    args = parser.parse_args()
    if args.test == bool(args.purpose):
        parser.error("give either --test or --purpose vorab|messung")
    purpose = args.purpose or "test"

    conn = database.connect(config.database_path(purpose))
    sites = site_data.load_sites(conn, v.severity, purpose)
    results = {domain: evaluate_site(site) for domain, site in sites.items()}
    semi_sites = {d: r for d, r in results.items() if sites[d]["semi"]}
    out_dir = config.DATA_DIR / f"evaluation-{purpose}-{time.strftime('%Y-%m-%d--%H-%M-%S')}"
    out_dir.mkdir(parents=True)

    rows = [csv_row(sites[d], r) for d, r in results.items()]
    columns = list(dict.fromkeys(key for row in rows for key in row))
    columns = [c for c in columns if not c.endswith("_reason")] + [c for c in columns if c.endswith("_reason")]
    with open(out_dir / "sites.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    funnel, tab_ii_text = tab_ii(conn, purpose)
    figures, tab_iii_text = tab_iii(results, semi_sites)
    warnings = [[d, w] for d, site in sites.items() for w in site["warnings"]]
    crosschecks = [[d, s["crosscheck"]["primary_operator"], s["crosscheck"]["crosscheck_operator"], s["source"]]
                   for d, s in sites.items() if s["crosscheck"] and s["crosscheck"]["differs"]]
    markdown = "\n\n".join([
        f"# Auswertung ({purpose}, {database.now()})",
        f"{len(sites)} Seiten: {sum(1 for s in sites.values() if s['automatic'])} im automatischen Modus, "
        f"{len(semi_sites)} halbautomatisch mit gültigem Ergebnis. Datenbank: `{config.database_path(purpose)}`.",
        "## Tab. II: Trichter (Vergleich Matte, .de)", tab_ii_text,
        "## Tab. III: Verstöße (Vergleich Matte; in eckigen Klammern Mattes Werte für alle 6 TLDs)", tab_iii_text,
        TAB_III_MAPPING,
        "## Details", details(results, semi_sites, sites),
        "## Gegenprüfung: Abweichungen (das mildere Ergebnis zählt; alle Seiten der CMP neu prüfen)",
        table(["Seite", "erste Prüfung", "Gegenprüfung", "zählt"], crosschecks) if crosschecks else "keine",
        "## Warnungen", table(["Seite", "Warnung"], warnings) if warnings else "keine"])
    (out_dir / "tables.md").write_text(markdown + "\n")
    (out_dir / "tables.json").write_text(json.dumps(
        {"purpose": purpose, "created": database.now(), "tab_ii": funnel, "tab_iii": figures,
         "sites": {d: {k: r for k, r in res.items()} for d, res in results.items()}, "warnings": warnings},
        indent=2, ensure_ascii=False, default=sorted))
    print(f"{out_dir}/tables.md, sites.csv, tables.json\n")
    print(markdown)


if __name__ == "__main__":
    main()

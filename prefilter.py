"""Prefilter with funnel: domains -> reachable and allowed by robots.txt -> with TCF.

Comparable with Matte et al. (2020), Tab. II (.de: 1000 domains -> 881 reachable and allowed ->
56 with a TCF banner, 6.4 % of 881). The reachability rules follow the paper (p. 5) and
cookinspect.py at 948a85f:
- robots.txt from https://www.<domain>; after a network error over HTTP, after a DNS error
  without www (robots.find_robots)
- the start page is loaded in the browser with a timeout of config.PAGE_LOAD_TIMEOUT seconds;
  after config.MAX_TRIES_TIMEOUT failed attempts the site is unreachable
- TCF: after loading and another config.SLEEP_TIME_CMP_WAIT seconds, __tcfapi exists and
  answers 'ping' (CLAUDE.md, Website-Auswahl)

Crawled is only what Protego (RFC 9309) allows. The decisions of urllib.robotparser and of the
original Cookinspect are stored next to it; the funnel shows all three side by side. For the
comparison with Tab. II the column of the original Cookinspect counts, because Matte's numbers
come from that code. Sites that only the original code allowed are not loaded; the funnel shows
how many.

Blocks by bot detection are not avoided, only detected (heuristically, see detect_block),
counted and reported.

    venv/bin/python prefilter.py lists/tranco_GQ3LK_de_top1000.csv --limit 10 --test
    venv/bin/python prefilter.py lists/tranco_GQ3LK_de_top1000.csv --purpose vorab
    venv/bin/python prefilter.py lists/tranco_GQ3LK_de_top1000.csv --purpose messung

Two full runs are planned (docs/entscheidungen.md, E3): "vorab" now, for the number of TCF
sites, and "messung" right before the measurement; only the second one counts in the paper and
its tcf_sites.csv is the input of the measurement.

Writes every result into the database (config.DATABASE_PATH, tables run and prefilter_result) and,
as export, into data/prefilter-<purpose>-<timestamp>/: run_metadata.json, prefilter.csv (one row
per domain), funnel.json and funnel.md, and tcf_sites.csv (the input of the automatic and
semi-automatic modes).
"""
import argparse
import csv
import json
import time
from datetime import datetime, timezone

from selenium.common.exceptions import TimeoutException, WebDriverException

import config
import database
from browser import start_chrome
from robots import decisions, find_robots
from run_list import list_info
from run_metadata import new_metadata, write_metadata

# Answer of __tcfapi('ping'), read in the page. Also notes whether the v1 API __cmp exists and
# whether the frame __tcfapiLocator is there (needed later for channel 2).
TCF_PING_SCRIPT = """
const done = arguments[arguments.length - 1];
const timeoutMs = arguments[0];
const result = {
    tcfapi: typeof window.__tcfapi === "function",
    cmp_v1: typeof window.__cmp === "function",
    tcfapi_locator: !!window.frames["__tcfapiLocator"],
    ping: null,
    error: null,
};
if (!result.tcfapi) { done(result); return; }
const timer = setTimeout(() => done(result), timeoutMs);
try {
    window.__tcfapi("ping", 2, (pingReturn) => {
        clearTimeout(timer);
        result.ping = JSON.parse(JSON.stringify(pingReturn ?? null));
        done(result);
    });
} catch (error) {
    clearTimeout(timer);
    result.error = String(error);
    done(result);
}
"""

# Signs of a block page (bot detection, challenge, access denied). A heuristic: hits are reported,
# not hidden, and can be checked by hand in prefilter.csv. Searched in the title and the beginning
# of the visible text (BLOCK_MARKERS) and in the HTML (BLOCK_HTML_MARKERS: challenge pages of bot
# managers, which often answer with status 200). Only markers that appear on the challenge page
# itself, not on normal pages protected by the same service (e.g. not Cloudflare's
# /cdn-cgi/challenge-platform/ script, which many normal pages load).
BLOCK_STATUS = (401, 403, 429)
BLOCK_HTML_MARKERS = {
    "sec-if-cpt-container": "Akamai Bot Manager",      # e.g. mobile.de, 2026-10-29
    "cf_chl_opt": "Cloudflare challenge",
    "captcha-delivery.com": "DataDome",
    "px-captcha": "PerimeterX/HUMAN",
    "incapsula incident id": "Imperva/Incapsula",
}
BLOCK_MARKERS = (
    "access denied", "zugriff verweigert", "request blocked", "you have been blocked",
    "attention required", "just a moment", "checking your browser", "pardon our interruption",
    "are you a robot", "bist du ein mensch", "sind sie ein mensch", "verify you are human",
    "captcha", "403 forbidden", "error 1020",
)

CSV_FIELDS = [
    "rank", "domain", "checked_at",
    "main_page_url", "robots_status", "robots_error", "robots_attempts",
    "robots_allowed", "robots_allowed_urllib", "robots_allowed_cookinspect",
    "loaded", "load_attempts", "load_errors", "final_url", "http_status", "title",
    "blocked", "block_reason",
    "tcfapi", "tcf", "ping_error", "cmp_id", "cmp_version", "cmp_status", "cmp_loaded",
    "display_status", "gdpr_applies", "api_version", "tcf_policy_version", "gvl_version",
    "tcfapi_locator", "cmp_v1",
]


def read_ranked_domains(path):
    """(rank, domain) pairs from a CSV with rank,domain columns, or a plain list of domains."""
    with open(path, newline="") as f:
        first_line = f.readline()
        f.seek(0)
        if "domain" in first_line.strip().split(","):
            return [(row.get("rank") or str(number), row["domain"].strip())
                    for number, row in enumerate(csv.DictReader(f), start=1) if row["domain"].strip()]
        domains = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        return [(str(number), domain) for number, domain in enumerate(domains, start=1)]


def detect_block(http_status, title, text, html=""):
    """Reason why the page looks like a block page, or None."""
    if http_status in BLOCK_STATUS:
        return f"HTTP {http_status}"
    haystack = f"{title or ''}\n{(text or '')[:2000]}".lower()
    for marker in BLOCK_MARKERS:
        if marker in haystack:
            return f"text: {marker}"
    html = (html or "")[:50000].lower()
    for marker, service in BLOCK_HTML_MARKERS.items():
        if marker in html:
            return f"html: {service}"
    if not (title or "").strip() and not (text or "").strip():
        return "no title and no visible text"
    return None


def watch_main_document(driver):
    """Records the HTTP status of the main document of every navigation in the top frame
    (BiDi network.responseCompleted). Returns the list the statuses are appended to."""
    top_context = driver.current_window_handle
    responses = []

    def field(value, name):   # Selenium passes dataclasses here, but sometimes plain dicts inside
        return value.get(name) if isinstance(value, dict) else getattr(value, name, None)

    def on_response(params):
        if params.context == top_context and params.navigation:
            responses.append({"url": field(params.response, "url"), "status": field(params.response, "status")})

    driver.network.add_event_handler("response_completed", on_response)
    return responses


def load_page(driver, url):
    """Loads url with up to config.MAX_TRIES_TIMEOUT attempts, as Cookinspect did.
    Returns (loaded, attempts, errors)."""
    errors = []
    for attempt in range(1, config.MAX_TRIES_TIMEOUT + 1):
        try:
            driver.get(url)
            return True, attempt, errors
        except TimeoutException:
            errors.append("timeout")
        except WebDriverException as error:
            errors.append(error.msg.splitlines()[0] if error.msg else type(error).__name__)
    return False, config.MAX_TRIES_TIMEOUT, errors


def check_page(url):
    """Loads the start page in a fresh browser and checks for blocks and TCF."""
    result = {}
    driver = start_chrome()
    try:
        responses = watch_main_document(driver)
        loaded, attempts, errors = load_page(driver, url)
        result.update(loaded=loaded, load_attempts=attempts, load_errors="; ".join(errors))
        if not loaded:
            return result
        time.sleep(config.SLEEP_TIME_CMP_WAIT)
        final_status = [r["status"] for r in responses if not 300 <= r["status"] < 400]
        title = driver.title
        text = driver.execute_script("return document.body ? document.body.innerText : ''")
        result.update(final_url=driver.current_url, http_status=final_status[-1] if final_status else None,
                      title=title[:200])
        result["block_reason"] = detect_block(result["http_status"], title, text, driver.page_source)
        result["blocked"] = result["block_reason"] is not None

        driver.set_script_timeout(config.TCF_PING_TIMEOUT + 2)
        tcf = driver.execute_async_script(TCF_PING_SCRIPT, config.TCF_PING_TIMEOUT * 1000)
        ping = tcf["ping"] if isinstance(tcf["ping"], dict) else {}
        result.update(
            tcfapi=tcf["tcfapi"], tcf=tcf["tcfapi"] and tcf["ping"] is not None, ping_error=tcf["error"],
            cmp_id=ping.get("cmpId"), cmp_version=ping.get("cmpVersion"), cmp_status=ping.get("cmpStatus"),
            cmp_loaded=ping.get("cmpLoaded"), display_status=ping.get("displayStatus"),
            gdpr_applies=ping.get("gdprApplies"), api_version=ping.get("apiVersion"),
            tcf_policy_version=ping.get("tcfPolicyVersion"), gvl_version=ping.get("gvlVersion"),
            tcfapi_locator=tcf["tcfapi_locator"], cmp_v1=tcf["cmp_v1"],
        )
    except WebDriverException as error:   # e.g. the page closed the window or the script failed
        result["load_errors"] = (result.get("load_errors", "") + f"; after load: {error.msg}").strip("; ")
    finally:
        driver.quit()
    return result


def check_domain(rank, domain):
    main_page_url, status, content, error, attempts = find_robots(domain)
    row = {"rank": rank, "domain": domain, "checked_at": datetime.now(timezone.utc).isoformat(),
           "main_page_url": main_page_url, "robots_status": status, "robots_error": error,
           "robots_attempts": json.dumps(attempts), **decisions(status, content, main_page_url + "/"),
           "loaded": False}
    if row["robots_allowed"]:   # crawled is only what Protego allows
        row.update(check_page(main_page_url))
    return row


def robots_reached(row):
    """robots.txt answered with an HTTP status. With an unknown error (neither DNS nor network),
    the original Cookinspect went on to load the page as well."""
    return row["robots_status"] not in (None, "") or row["robots_error"] == "other"


def as_bool(value):
    return value is True or value == "True"


def share(part, whole):
    return round(100 * part / whole, 1) if whole else None


def funnel(rows):
    """Counts per robots.txt decision. 'loaded' and below only contain sites that Protego allows,
    because only those are loaded."""
    columns = {"protego": "robots_allowed", "urllib": "robots_allowed_urllib",
               "cookinspect": "robots_allowed_cookinspect"}
    result = {"domains": len(rows),
              "robots_answered": sum(1 for r in rows if r["robots_status"] not in (None, "")),
              "columns": {}}
    for name, field in columns.items():
        allowed = [r for r in rows if robots_reached(r) and as_bool(r[field])]
        loaded = [r for r in allowed if as_bool(r["loaded"])]
        tcf = [r for r in loaded if as_bool(r.get("tcf"))]
        result["columns"][name] = {
            "allowed": len(allowed),
            "allowed_not_loaded_protego_forbids": sum(1 for r in allowed if not as_bool(r["robots_allowed"])),
            "load_failed": sum(1 for r in allowed if as_bool(r["robots_allowed"]) and not as_bool(r["loaded"])),
            "loaded": len(loaded),
            "blocked": sum(1 for r in loaded if as_bool(r.get("blocked"))),
            "tcfapi_without_ping": sum(1 for r in loaded if as_bool(r.get("tcfapi")) and not as_bool(r.get("tcf"))),
            "tcf": len(tcf),
            "tcf_share_of_loaded": share(len(tcf), len(loaded)),
            # without blocked sites in the denominator; Matte did not detect blocks, so the share
            # above is the one comparable with Tab. II
            "tcf_share_of_loaded_not_blocked": share(
                len(tcf), sum(1 for r in loaded if not as_bool(r.get("blocked")))),
        }
    return result


MATTE_TAB_II_DE = {"domains": 1000, "loaded": 881, "tcf": 56, "tcf_share_of_loaded": 6.4}


def funnel_table(result):
    """Markdown table: one column per robots.txt decision, plus Matte Tab. II for .de."""
    c = result["columns"]
    names = ("protego", "urllib", "cookinspect")
    lines = ["| Stufe | Protego (gecrawlt) | urllib | Original-Cookinspect (Vergleich Tab. II) | Matte Tab. II (.de) |",
             "|---|---|---|---|---|"]

    def row(label, values, matte=""):
        lines.append(f"| {label} | " + " | ".join(str(v) for v in values) + f" | {matte} |")

    row("Domains", [result["domains"]] * 3, MATTE_TAB_II_DE["domains"])
    row("robots.txt beantwortet (HTTP-Status)", [result["robots_answered"]] * 3)
    row("von robots.txt erlaubt", [c[n]["allowed"] for n in names])
    row("– davon nicht geladen, weil Protego verbietet", [c[n]["allowed_not_loaded_protego_forbids"] for n in names])
    row("– davon Laden fehlgeschlagen (3 Versuche)", [c[n]["load_failed"] for n in names])
    row("erreichbar und erlaubt (geladen)", [c[n]["loaded"] for n in names], MATTE_TAB_II_DE["loaded"])
    row("– davon Sperre erkannt (heuristisch)", [c[n]["blocked"] for n in names])
    row("– davon `__tcfapi` ohne Antwort auf ping", [c[n]["tcfapi_without_ping"] for n in names])
    row("mit TCF (ping antwortet)", [c[n]["tcf"] for n in names], MATTE_TAB_II_DE["tcf"])
    def percent(value):
        return f"{value} %" if value is not None else "–"

    row("TCF-Anteil an geladenen (mit gesperrten, vergleichbar mit Matte)",
        [percent(c[n]["tcf_share_of_loaded"]) for n in names], percent(MATTE_TAB_II_DE["tcf_share_of_loaded"]))
    row("TCF-Anteil an geladenen ohne gesperrte", [percent(c[n]["tcf_share_of_loaded_not_blocked"]) for n in names])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("list", help="CSV with rank,domain columns, or one domain per line")
    parser.add_argument("--limit", type=int, help="only the first N domains (for tests)")
    parser.add_argument("--test", action="store_true", help="test run: CRAWL_USER and a clean Git state are not required")
    parser.add_argument("--purpose", choices=["vorab", "messung"],
                        help="full run: 'vorab' (number of TCF sites) or 'messung' (counts in the paper)")
    args = parser.parse_args()
    if args.test == bool(args.purpose):
        parser.error("give either --test or --purpose vorab|messung")
    purpose = args.purpose or "test"

    domains = read_ranked_domains(args.list)
    if args.limit is not None:
        domains = domains[:args.limit]
    metadata = new_metadata("prefilter", args.test, purpose=purpose, website_list={
        "path": str(args.list), "info": list_info(args.list), "domains": len(domains), "limit": args.limit})
    run_dir = config.DATA_DIR / f"prefilter-{purpose}-{datetime.now():%Y-%m-%d--%H-%M-%S}"
    run_dir.mkdir(parents=True)
    write_metadata(metadata, run_dir)
    conn = database.connect()
    run_id = database.insert_run(conn, metadata)
    tranco_list_id = (list_info(args.list) or {}).get("tranco_list_id")
    print(f"Run directory: {run_dir}\nDatabase: {config.DATABASE_PATH} (run {run_id})")

    rows = []
    with open(run_dir / "prefilter.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for number, (rank, domain) in enumerate(domains, start=1):
            row = check_domain(rank, domain)
            rows.append(row)
            database.insert_prefilter_result(conn, run_id, row, tranco_list_id)
            writer.writerow(row)
            f.flush()
            print(f"[{number}/{len(domains)}] {domain}: robots {row['robots_status']} "
                  f"(Protego {row['robots_allowed']}, urllib {row['robots_allowed_urllib']}, "
                  f"Cookinspect {row['robots_allowed_cookinspect']}), loaded {row['loaded']}, "
                  f"blocked {row.get('blocked')}, TCF {row.get('tcf')} (CMP {row.get('cmp_id')})")
            time.sleep(config.PAUSE_BETWEEN_DOMAINS)

    with open(run_dir / "tcf_sites.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "domain", "url", "cmp_id"])
        for row in rows:
            if row["robots_allowed"] and row["loaded"] and row.get("tcf"):
                writer.writerow([row["rank"], row["domain"], row["main_page_url"], row.get("cmp_id")])

    result = funnel(rows)
    metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_metadata(metadata, run_dir)
    database.finish_run(conn, run_id)
    (run_dir / "funnel.json").write_text(json.dumps(result, indent=2))
    table = funnel_table(result)
    (run_dir / "funnel.md").write_text(table + "\n")
    print("\n" + table)


if __name__ == "__main__":
    main()

"""Automatic mode: V1 (consent before the choice) and the transfer to third parties before any
interaction, in two fresh sessions per site (CLAUDE.md, Ablauf). Nothing is clicked.

Per site:
  - robots.txt (Protego) is checked again; a disallowed site is not loaded
  - two sessions, each with a fresh browser: load the start page (config.MAX_TRIES_TIMEOUT
    attempts), wait config.SLEEP_TIME_CMP_WAIT seconds after loading (as Matte, p. 5 and 8), then
    the snapshot "before" of all channels (capture.py)
  - block pages and suspected cookiewalls (heuristic, cookiewall.py) are recorded per session

Everything goes into the database of the purpose (config.database_path). Whether V1 holds is
decided in Phase 8: only if both snapshots "before" show it.

    venv/bin/python automatic.py data/prefilter-messung-<time>/tcf_sites.csv --purpose messung
    venv/bin/python automatic.py lists/tranco_GQ3LK_de_top1000.csv --limit 10 --test
"""
import argparse
import csv
import json
import time
from pathlib import Path

import config
import database
from browser import start_chrome
from capture import Capture, registrable_domain
from cookiewall import detect_cookiewall, dialog_texts
from page import detect_block, load_page, watch_main_document
from robots import check_robots
from run_list import list_info
from run_metadata import new_metadata, write_metadata

SESSIONS_PER_SITE = 2


def read_sites(path):
    """Sites to visit: tcf_sites.csv of the prefilter (rank, domain, url, cmp_id) or a list with
    rank,domain or one domain per line (then https://www.<domain>)."""
    with open(path, newline="") as f:
        first_line = f.readline()
        f.seek(0)
        if "domain" in first_line.strip().split(","):
            rows = list(csv.DictReader(f))
        else:
            rows = [{"domain": line.strip()} for line in f if line.strip() and not line.startswith("#")]
    return [{"rank": row.get("rank"), "domain": row["domain"].strip(),
             "url": row.get("url") or f"https://www.{row['domain'].strip()}"} for row in rows if row["domain"].strip()]


def run_session(conn, examination_id, number, url, cmp_list, cmp_list_last_updated):
    """One fresh browser: load, wait, snapshot "before". Returns the closing fields of the session."""
    session_id = database.insert_session(conn, examination_id, "automatic", url, number)
    driver = start_chrome()
    fields = {}
    try:
        capture = Capture(driver, url)
        responses = watch_main_document(driver)
        loaded, attempts, errors = load_page(driver, url)
        fields.update(loaded=loaded, load_attempts=attempts, load_errors="; ".join(errors) or None)
        snapshots = {}
        if loaded:
            time.sleep(config.SLEEP_TIME_CMP_WAIT)   # V1 snapshot only after loading plus 3 s
            snapshots["before"] = capture.snapshot("before")
            statuses = [r["status"] for r in responses if not 300 <= r["status"] < 400]
            text = driver.execute_script("return document.body ? document.body.innerText : ''")
            block_reason = detect_block(statuses[-1] if statuses else None, driver.title, text, driver.page_source)
            suspected, reason = detect_cookiewall(dialog_texts(driver),
                                                  {registrable_domain(r["url"]) for r in capture.requests if r["url"]})
            fields.update(final_url=driver.current_url, http_status=statuses[-1] if statuses else None,
                          blocked=block_reason is not None, block_reason=block_reason,
                          cookiewall_suspected=suspected, cookiewall_reason=reason)
        closing = capture.close()
        database.store_capture(conn, session_id, snapshots, closing, cmp_list, cmp_list_last_updated)
        database.finish_session(conn, session_id, remove_listener=closing["remove_listener"], **fields)
    finally:
        driver.quit()
    return fields


def examine_site(conn, run_id, site, cmp_list, cmp_list_last_updated):
    database.ensure_website(conn, site["domain"], site["rank"])
    robots = check_robots(site["url"])
    examination_id = database.insert_examination(conn, run_id, site["domain"], site["url"], "automatic")
    if not robots["robots_allowed"]:
        database.finish_examination(conn, examination_id, "robots_disallowed")
        return examination_id
    sessions = []
    for number in range(1, SESSIONS_PER_SITE + 1):
        sessions.append(run_session(conn, examination_id, number, site["url"], cmp_list, cmp_list_last_updated))
        time.sleep(config.PAUSE_BETWEEN_DOMAINS)
    suspected = [f"session {n}: {s['cookiewall_reason']}" for n, s in enumerate(sessions, 1) if s.get("cookiewall_suspected")]
    status = "done" if any(s.get("loaded") for s in sessions) else "unreachable"
    database.finish_examination(conn, examination_id, status, cookiewall_suspected=bool(suspected),
                                cookiewall_reason="; ".join(suspected) or None)
    return examination_id


# Summary per site for the terminal: purposes in channel 1 before any interaction, per session.
SUMMARY_QUERY = """
SELECT se.number, se.loaded, se.blocked, se.cookiewall_suspected, o.status AS channel_1,
       (SELECT group_concat(value) FROM (SELECT value FROM tc_string_entry
            WHERE tc_string_id = o.tc_string_id AND field = 'purpose_consent' ORDER BY value)) AS purposes,
       (SELECT count(*) FROM tc_string_entry WHERE tc_string_id = o.tc_string_id AND field = 'vendor_consent') AS vendors,
       (SELECT o2.status FROM observation o2 WHERE o2.snapshot_id = sn.id AND o2.channel = 'third_party_frame') AS channel_2,
       (SELECT count(*) FROM request r JOIN request_signal rs ON rs.request_id = r.id
            WHERE r.session_id = se.id AND r.third_party = 1 AND rs.kind = 'tc_string') AS third_party_tc_strings
FROM session se
LEFT JOIN snapshot sn ON sn.session_id = se.id AND sn.phase = 'before'
LEFT JOIN observation o ON o.snapshot_id = sn.id AND o.channel = 'tcfapi'
WHERE se.examination_id = ? ORDER BY se.number
"""


def print_summary(conn, domain, examination_id):
    status, cookiewall = conn.execute("SELECT status, cookiewall_reason FROM examination WHERE id = ?",
                                      (examination_id,)).fetchone()
    print(f"  {domain}: {status}" + (f" | cookiewall suspected (heuristic): {cookiewall}" if cookiewall else ""))
    for row in conn.execute(SUMMARY_QUERY, (examination_id,)):
        print(f"    session {row['number']}: loaded {row['loaded']}, blocked {row['blocked']}, channel 1 {row['channel_1']},"
              f" purposes before [{row['purposes'] or ''}], vendors {row['vendors']}, channel 2 {row['channel_2']},"
              f" TC strings to third parties {row['third_party_tc_strings']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sites", help="tcf_sites.csv of the prefilter, or a list of domains")
    parser.add_argument("--limit", type=int, help="only the first N sites (for tests)")
    parser.add_argument("--test", action="store_true", help="test run: data/test.sqlite, no CRAWL_USER needed")
    parser.add_argument("--purpose", choices=["vorab", "messung"], help="full run")
    args = parser.parse_args()
    if args.test == bool(args.purpose):
        parser.error("give either --test or --purpose vorab|messung")
    purpose = args.purpose or "test"

    sites = read_sites(args.sites)[:args.limit] if args.limit else read_sites(args.sites)
    metadata = new_metadata("automatic", args.test, purpose=purpose, website_list={
        "path": str(args.sites), "info": list_info(args.sites), "domains": len(sites), "limit": args.limit},
        sessions_per_site=SESSIONS_PER_SITE)
    cmp_list_meta = metadata["consent_lists"]["cmp_list"]
    cmp_list = json.loads(Path(cmp_list_meta["path"]).read_text())
    run_dir = config.DATA_DIR / f"automatic-{purpose}-{time.strftime('%Y-%m-%d--%H-%M-%S')}"
    run_dir.mkdir(parents=True)
    write_metadata(metadata, run_dir)
    conn = database.connect(config.database_path(purpose))
    run_id = database.insert_run(conn, metadata)
    print(f"Run directory: {run_dir}\nDatabase: {config.database_path(purpose)} (run {run_id})")

    for number, site in enumerate(sites, start=1):
        print(f"[{number}/{len(sites)}] {site['domain']}")
        examination_id = examine_site(conn, run_id, site, cmp_list, cmp_list_meta["lastUpdated"])
        print_summary(conn, site["domain"], examination_id)
    database.finish_run(conn, run_id)


if __name__ == "__main__":
    main()

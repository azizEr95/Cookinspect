"""Semi-automatic mode: V2-V4 as in Matte et al. (2020), Section V-B and Appendix D. A person
clicks in the visible browser window, the tool only reads (capture.py) and asks in the terminal.
The tool never clicks.

Per site (CLAUDE.md, Ablauf):
  1. fresh browser, load the start page, wait 3 s. No banner: reload up to 3 times (Appendix D)
  2. snapshot "before", screenshot of the banner
  3. the person looks at the banner and enters the code:
       r  can be rejected       -> rejects now (rules of Appendix D are shown)
       n  no way to reject      -> accepts in this session (no reject session)
       w  cookiewall without a free way to reject (also not on the 2nd layer)
                                -> no reject session; accepts in this session (does not pay)
       x  banner broken         -> nothing more
     (b, no banner, follows from step 1)
  4. wait for eventStatus useractioncomplete (or store "no useractioncomplete"), screenshot after
     closing, snapshot after the action; after 3 s reload, snapshot again
  5. the questions of the label (layer, pay option, 2nd layer, V3 purposes and vendors, closing
     button, note)
  6. code r only: second fresh session, the same with accepting

After every step the terminal shows what was stored. In a crosscheck (role crosscheck) nothing
of the first examination is shown, and the own results only after the label was entered.

    venv/bin/python semi_automatic.py data/prefilter-messung-<time>/site_assignment.csv --operator ae --purpose messung
    venv/bin/python semi_automatic.py lists/tranco_GQ3LK_de_top1000.csv --operator ae --test --limit 3
    venv/bin/python semi_automatic.py crosscheck.csv --operator xy --role crosscheck --purpose messung

For a crosscheck, a correction or a recheck the CSV has a column examination_id: the examination
that is checked, corrected or rechecked. Sites already done by the same person in the same role
are skipped, so a run can be continued later.
"""
import argparse
import csv
import json
import time
from pathlib import Path

from selenium.common.exceptions import TimeoutException, WebDriverException

import config
import database
from browser import start_chrome
from capture import Capture
from decoder import decode_tc_strings
from page import load_page
from robots import check_robots
from run_list import list_info
from run_metadata import new_metadata, write_metadata

LOOK = """
  Banner ansehen, noch nichts bestätigen. Die Einstellungen (2. Ebene) dürfen geöffnet werden.
  Gibt es eine Möglichkeit, abzulehnen?
  Cookiewall (Bezahl-Option): Code w nur, wenn es KEINEN kostenlosen Weg zum Ablehnen gibt, auch
  nicht auf der 2. Ebene. Gibt es einen, ist der Code r (Matte lehnt immer ab, wenn es geht,
  Anhang D); die Bezahl-Option wird danach eigens abgefragt.
"""

# Appendix D (CLAUDE.md, Regeln für das Ablehnen)
REJECT_RULES = """
  Jetzt ablehnen (Anhang D):
  - Gibt es auf der 1. Ebene „Ablehnen“: direkt klicken.
  - Sonst die Einstellungen (2. Ebene) öffnen und dort alle zweckbezogenen Optionen
    (Checkbox oder Schalter) abwählen, unabhängig von der Art (auch z. B. „funktionale Cookies“).
  - „Alle ablehnen“ klicken, auch wenn nichts angehakt ist.
  - Vendor-Optionen ignorieren.
  - Gibt es keine Einstellungen, nur einen Link zur Datenschutzerklärung: dort höchstens 10 s nach
    einer Ablehnmöglichkeit suchen (Timer mit „t“), dann zurück zur Hauptseite.
  - Liegen die Optionen auf einer anderen Seite: nach dem Ablehnen zurück zur Hauptseite.
  - Das Banner immer schließen, mit der Schaltfläche, die am wenigsten nach Zustimmung klingt.
"""

ACCEPT_RULES = """
  Jetzt akzeptieren: auf der 1. Ebene die Schaltfläche für die Zustimmung klicken
  (z. B. „Alle akzeptieren“). Bei einer Cookiewall: zustimmen, nicht bezahlen.
"""

CODES = {"r": "rejected", "n": "n", "w": "w", "x": "x"}
CODE_TEXT = {"r": "kostenlos ablehnbar", "n": "keine Ablehnmöglichkeit",
             "w": "Cookiewall ohne kostenloses Ablehnen", "x": "Banner kaputt"}
PRIVACY_POLICY_SECONDS = 10


# --- input in the terminal (tests replace ask)

def ask(prompt):
    return input(prompt)


def ask_choice(prompt, choices):
    """choices: {key: meaning}. Asks until one of the keys is entered."""
    options = ", ".join(f"{key} = {meaning}" for key, meaning in choices.items())
    while True:
        answer = ask(f"{prompt} [{options}]: ").strip().lower()
        if answer in choices:
            return answer
        print(f"  Bitte eines von: {', '.join(choices)}")


def ask_yes_no(prompt, allow_unknown=False):
    choices = {"j": "ja", "n": "nein", **({"?": "nicht geprüft"} if allow_unknown else {})}
    return {"j": True, "n": False, "?": None}[ask_choice(prompt, choices)]


def countdown(seconds):
    """Visible timer for the search in the privacy policy (Appendix D)."""
    for left in range(seconds, 0, -1):
        print(f"\r  Datenschutzerklärung: noch {left:2d} s ", end="", flush=True)
        time.sleep(1)
    print("\r  Datenschutzerklärung: Zeit um, zurück zur Hauptseite.      ")


def wait_for_person(prompt):
    """Waits until the person presses Enter; "t" starts the 10-s timer. Returns whether the timer
    was used (= searched in the privacy policy)."""
    searched = False
    while True:
        answer = ask(f"{prompt} (Enter = fertig, t = 10-s-Timer Datenschutzerklärung): ").strip().lower()
        if answer == "t":
            searched = True
            countdown(PRIVACY_POLICY_SECONDS)
        elif answer == "":
            return searched


# --- what is shown after each step

class Output:
    """Prints at once; in a blind crosscheck it keeps the lines until the label was entered."""

    def __init__(self, blind):
        self.blind = blind
        self.kept = []

    def show(self, line):
        if self.blind:
            self.kept.append(line)
        else:
            print(f"  → gespeichert: {line}")

    def release(self):
        if self.blind and self.kept:
            print("  Ergebnisse dieser Prüfung (nach dem Label):")
            for line in self.kept:
                print(f"  → gespeichert: {line}")
        self.blind = False
        self.kept = []


def ids(values):
    return "{" + ", ".join(str(v) for v in values) + "}"


def describe(label, snapshot, useractioncomplete=None):
    latest = snapshot["channel_1"]["latest_event"] or {}
    tc_string = latest.get("tcString")
    if latest.get("emptyTcData"):
        channel_1 = "Kanal ① leeres tcData"
    elif tc_string:
        decoded = decode_tc_strings([tc_string])[0]
        if decoded.get("decoded"):
            channel_1 = (f"Zwecke {ids(decoded['purposeConsents'])}, LI {ids(decoded['purposeLegitimateInterests'])}, "
                         f"Vendoren {len(decoded['vendorConsents'])} Consent / {len(decoded['vendorLegitimateInterests'])} LI")
        else:
            channel_1 = f"TC-String v{decoded.get('version')} nicht dekodiert ({decoded.get('reason')})"
    else:
        channel_1 = "Kanal ① kein TC-String" if snapshot["channel_1"]["tcfapi_seen"] else "kein __tcfapi"
    third_party = sum(1 for r in snapshot["requests"]["with_signals"] if r["third_party"]
                      for s in r["signals"] if s["kind"] == "tc_string")
    storage = sum(len(item["tc_strings"]) for item in snapshot["storage"]["cookies"] + snapshot["storage"]["local_storage"])
    line = (f"{label}: {channel_1} | Kanal ② {snapshot['channel_2']['status']} | TC-Strings im Speicher {storage}"
            f" | an Dritte {third_party}")
    if useractioncomplete is not None:
        line += f" | useractioncomplete {'ja' if useractioncomplete else 'NEIN'}"
    return line


# --- one browser session

class Session:
    """A fresh browser for one session; stored in the database only at the end (store), when its
    kind (reject or accept) is known."""

    def __init__(self, url, run_dir, domain, number):
        self.url, self.run_dir, self.domain, self.number = url, run_dir, domain, number
        self.started_at = database.now()
        self.driver = start_chrome()
        self.capture = Capture(self.driver, url)
        self.snapshots = {}
        self.screenshots = []
        self.fields = {}
        self.mark = None

    def open(self):
        loaded, attempts, errors = load_page(self.driver, self.url)
        self.fields.update(loaded=loaded, load_attempts=attempts, load_errors="; ".join(errors) or None)
        return loaded

    def wait_for_banner(self):
        """Asks whether the banner is visible; reloads up to config.MAX_BANNER_RELOADS times."""
        reloads = 0
        while True:
            time.sleep(config.SLEEP_TIME_CMP_WAIT)
            if ask_yes_no("  Ist ein Cookie-Banner zu sehen?"):
                shown = True
                break
            if reloads == config.MAX_BANNER_RELOADS:
                shown = False
                break
            reloads += 1
            print(f"  Neu laden ({reloads}/{config.MAX_BANNER_RELOADS}) ...")
            self.reload()
        self.fields.update(banner_shown=shown, banner_reloads=reloads)
        return shown

    def reload(self):
        try:
            self.driver.refresh()
        except TimeoutException:
            pass   # the page did not finish within the timeout; what is loaded is read anyway

    def screenshot(self, moment):
        directory = self.run_dir / "screenshots"
        directory.mkdir(exist_ok=True)
        path = directory / f"{self.domain}-session{self.number}-{moment}-{int(time.time())}.png"
        self.driver.save_screenshot(str(path))
        self.screenshots.append((moment, path))

    def before(self, output):
        self.snapshots["before"] = self.capture.snapshot("before")
        output.show(describe("vorher", self.snapshots["before"]))
        self.screenshot("before_action")
        self.mark = self.capture.mark()   # events from here on count as reaction to the person

    def after_action(self, kind, output):
        """Step 4: useractioncomplete, screenshot, snapshot; after 3 s reload and snapshot."""
        waited = time.monotonic()
        event = self.capture.wait_for_event("useractioncomplete", config.USERACTIONCOMPLETE_TIMEOUT, after=self.mark)
        self.fields.update(useractioncomplete_received=event is not None,
                           useractioncomplete_wait_s=round(time.monotonic() - waited, 1))
        if event is None:
            print(f"  Kein useractioncomplete innerhalb von {config.USERACTIONCOMPLETE_TIMEOUT} s; wird trotzdem ausgelesen.")
        self.screenshot("after_closing")
        self.snapshots[f"after_{kind}"] = self.capture.snapshot(f"after_{kind}")
        output.show(describe(f"nach {'Ablehnen' if kind == 'reject' else 'Akzeptieren'}",
                             self.snapshots[f"after_{kind}"], event is not None))
        time.sleep(config.SLEEP_TIME_REFRESH)
        self.reload()
        time.sleep(config.SLEEP_TIME_CMP_WAIT)
        self.snapshots[f"after_{kind}_reload"] = self.capture.snapshot(f"after_{kind}_reload")
        output.show(describe("nach Reload", self.snapshots[f"after_{kind}_reload"]))

    def store(self, conn, examination_id, kind, cmp_list, cmp_list_last_updated):
        closing = self.capture.close()
        session_id = database.insert_session(conn, examination_id, kind, self.url, self.number, self.started_at)
        database.store_capture(conn, session_id, self.snapshots, closing, cmp_list, cmp_list_last_updated)
        for moment, path in self.screenshots:
            database.insert_screenshot(conn, session_id, moment, path)
        database.finish_session(conn, session_id, remove_listener=closing["remove_listener"], **self.fields)
        return session_id

    def quit(self):
        try:
            self.driver.quit()
        except WebDriverException:
            pass


# --- one site

def ask_label(code, searched):
    """Step 5: the questions of the label (table label)."""
    label = {"outcome": CODES[code], "privacy_policy_searched": searched}
    if code == "r":
        label["reject_level"] = int(ask_choice("  Auf welcher Ebene abgelehnt?", {"1": "1. Ebene (Banner)",
                                                                                 "2": "2. Ebene (Einstellungen)"}))
    # independent of the code: a site with a pay option and a free way to reject is r and a cookiewall
    label["cookiewall_seen"] = True if code == "w" else ask_yes_no("  Gibt es eine Bezahl-Option (z. B. Pur-Abo)?")
    label["settings_layer_available"] = ask_yes_no("  Gibt es eine 2. Ebene (Einstellungen)?")
    if label["settings_layer_available"]:
        label["purposes_preselected"] = ask_yes_no("  2. Ebene: Zwecke vorausgewählt?", allow_unknown=True)
        label["vendors_preselected"] = ask_yes_no("  2. Ebene: Vendoren vorausgewählt?", allow_unknown=True)
    if code != "x":
        label["closed_with"] = ask("  Text der Schaltfläche, mit der das Banner geschlossen wurde: ").strip() or None
    label["note"] = ask("  Notiz (Enter = keine): ").strip() or None
    return label


def examine(ctx, site, role, linked_id):
    """One examination of one site. Returns its status."""
    conn, operator = ctx["conn"], ctx["operator"]
    links = {"crosscheck_of": linked_id} if role == "crosscheck" else {"correction_of": linked_id} if role == "correction" else {}
    output = Output(blind=role == "crosscheck")
    if role == "crosscheck":
        first_operator = conn.execute("SELECT operator FROM examination WHERE id = ?", (linked_id,)).fetchone()
        if first_operator is None or first_operator[0] == operator:
            print("  Gegenprüfung übersprungen: Die erste Prüfung fehlt oder stammt von derselben Person.")
            return "skipped"
    if not check_robots(site["url"])["robots_allowed"]:
        examination_id = database.insert_examination(conn, ctx["run_id"], site["domain"], site["url"], role, operator, **links)
        database.finish_examination(conn, examination_id, "robots_disallowed")
        print("  robots.txt verbietet den Abruf, übersprungen.")
        return "robots_disallowed"
    examination_id = database.insert_examination(conn, ctx["run_id"], site["domain"], site["url"], role, operator, **links)
    stored = lambda session, kind: session.store(conn, examination_id, kind, ctx["cmp_list"], ctx["cmp_list_last_updated"])  # noqa: E731

    print("\n  Sitzung 1")
    first = Session(site["url"], ctx["run_dir"], site["domain"], 1)
    try:
        if not first.open():
            stored(first, "reject")
            database.finish_examination(conn, examination_id, "unreachable")
            print("  Seite nicht erreichbar.")
            return "unreachable"
        shown = first.wait_for_banner()
        first.before(output)
        if not shown:
            print("  Kein Banner nach 3-mal Neuladen: Code b.")
            stored(first, "reject")
            database.insert_label(conn, examination_id, operator, "b",
                                  note=ask("  Notiz (Enter = keine): ").strip() or None)
            output.release()
            database.finish_examination(conn, examination_id, "done")
            return "done"
        print(LOOK)
        code = ask_choice("  Code", CODE_TEXT)
        searched = False
        if code == "r":
            print(REJECT_RULES)
            searched = wait_for_person("  Ablehnen und Banner schließen")
            first.after_action("reject", output)
            kind = "reject"
        elif code in ("n", "w"):
            print(ACCEPT_RULES)
            searched = wait_for_person("  Akzeptieren")
            first.after_action("accept", output)
            kind = "accept"
        else:
            print("  Banner kaputt: nichts weiter klicken.")
            kind = "reject"
        label = ask_label(code, searched)
        stored(first, kind)
    finally:
        first.quit()
    database.insert_label(conn, examination_id, operator, **label)
    output.release()

    if code == "r":
        time.sleep(config.PAUSE_BETWEEN_DOMAINS)
        print("\n  Sitzung 2: Akzeptieren")
        second = Session(site["url"], ctx["run_dir"], site["domain"], 2)
        try:
            if second.open() and second.wait_for_banner():
                second.before(output)
                print(ACCEPT_RULES)
                wait_for_person("  Akzeptieren")
                second.after_action("accept", output)
            elif second.fields.get("loaded"):
                second.before(output)
                print("  Kein Banner in der Akzeptieren-Sitzung (gespeichert).")
            stored(second, "accept")
        finally:
            second.quit()
    database.finish_examination(conn, examination_id, "done")
    return "done"


# --- sites and run

def read_sites(path, operator, role):
    """Sites for this person: site_assignment.csv (first_operator) for role primary, otherwise a
    CSV with examination_id; a plain list or tcf_sites.csv in a test."""
    with open(path, newline="") as f:
        first_line = f.readline()
        f.seek(0)
        rows = list(csv.DictReader(f)) if "domain" in first_line.strip().split(",") else \
            [{"domain": line.strip()} for line in f if line.strip() and not line.startswith("#")]
    if role == "primary" and rows and "first_operator" in rows[0]:
        rows = [row for row in rows if row["first_operator"] == operator]
    if role in ("crosscheck", "correction") and any(not row.get("examination_id") for row in rows):
        raise SystemExit(f"{path}: every row needs an examination_id for role {role}")
    return [{"domain": row["domain"].strip(), "rank": row.get("rank"),
             "url": row.get("url") or f"https://www.{row['domain'].strip()}",
             "examination_id": row.get("examination_id") or None} for row in rows]


def already_done(conn, domain, operator, role, linked_id):
    return conn.execute("SELECT 1 FROM examination WHERE domain = ? AND operator = ? AND role = ? AND status = 'done' "
                        "AND coalesce(crosscheck_of, correction_of, '') = coalesce(?, '')",
                        (domain, operator, role, linked_id if role in ("crosscheck", "correction") else None)).fetchone()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sites", help="site_assignment.csv, a CSV with examination_id, or a list of domains")
    parser.add_argument("--operator", required=True, help="short code of the person, e.g. ae")
    parser.add_argument("--role", choices=["primary", "crosscheck", "recheck", "correction"], default="primary")
    parser.add_argument("--limit", type=int, default=config.SEMI_AUTOMATIC_LIMIT, help="only the first N sites (tests)")
    parser.add_argument("--test", action="store_true", help="test run: data/test.sqlite, no CRAWL_USER needed")
    parser.add_argument("--purpose", choices=["vorab", "messung"], help="full run")
    args = parser.parse_args()
    if args.test == bool(args.purpose):
        parser.error("give either --test or --purpose vorab|messung")
    purpose = args.purpose or "test"

    sites = read_sites(args.sites, args.operator, args.role)
    metadata = new_metadata("semi-automatic", args.test, purpose=purpose, operator=args.operator, role=args.role,
                            website_list={"path": str(args.sites), "info": list_info(args.sites),
                                          "domains": len(sites), "limit": args.limit})
    cmp_list_meta = metadata["consent_lists"]["cmp_list"]
    run_dir = config.DATA_DIR / f"semi-automatic-{purpose}-{args.operator}-{time.strftime('%Y-%m-%d--%H-%M-%S')}"
    run_dir.mkdir(parents=True)
    write_metadata(metadata, run_dir)
    conn = database.connect(config.database_path(purpose))
    ctx = {"conn": conn, "operator": args.operator, "run_dir": run_dir,
           "cmp_list": json.loads(Path(cmp_list_meta["path"]).read_text()),
           "cmp_list_last_updated": cmp_list_meta["lastUpdated"],
           "run_id": database.insert_run(conn, metadata, operator=args.operator)}
    print(f"Run directory: {run_dir}\nDatabase: {config.database_path(purpose)}")

    todo = [s for s in sites if not already_done(conn, s["domain"], args.operator, args.role, s["examination_id"])]
    if len(todo) < len(sites):
        print(f"{len(sites) - len(todo)} Seiten schon geprüft (übersprungen).")
    todo = todo[:args.limit] if args.limit else todo
    try:
        for number, site in enumerate(todo, start=1):
            print(f"\n=== [{number}/{len(todo)}] {site['domain']} ({site['url']})")
            try:
                status = examine(ctx, site, args.role, site["examination_id"])
            except WebDriverException as error:
                # e.g. the browser window was closed; the examination stays without status and is
                # repeated at the next start
                status = f"Browserfehler ({error.msg.splitlines()[0] if error.msg else type(error).__name__})"
            print(f"  Prüfung: {status}")
            time.sleep(config.PAUSE_BETWEEN_DOMAINS)
    except KeyboardInterrupt:
        print("\nAbgebrochen. Die laufende Prüfung bleibt ohne Status; sie wird beim nächsten Start wiederholt.")
    finally:
        database.finish_run(conn, ctx["run_id"])


if __name__ == "__main__":
    main()

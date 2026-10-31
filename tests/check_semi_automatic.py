"""Plays the semi-automatic mode through on the local test site (tests/site), with scripted
answers in place of the person: codes r, n, b and a blind crosscheck. Not part of pytest (needs a
browser). The clicks happen here, in the test script, never in semi_automatic.py (CLAUDE.md).

    venv/bin/python tests/check_semi_automatic.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database  # noqa: E402
import semi_automatic  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402

URL = "http://localhost:8001/top.html?reload_after_choice=1"
CMP_LIST = {"lastUpdated": "test", "cmps": {"300": {"id": 300, "name": "Google LLC"}}}
drivers = []


def click(element_id):
    """An answer that first clicks on the test site (as the person would), then presses Enter."""
    def act():
        drivers[-1].find_element(By.ID, element_id).click()
        return ""
    return act


def scripted(answers):
    def ask(prompt):
        answer = answers.pop(0)
        answer = answer() if callable(answer) else answer
        print(f"{prompt}{answer}")
        return answer
    return ask


def run(ctx, role, answers, linked_id=None):
    semi_automatic.ask = scripted(answers)
    status = semi_automatic.examine(ctx, {"domain": "localhost", "url": URL}, role, linked_id)
    assert not answers, f"unused answers: {answers}"
    return status


def main():
    original_start = semi_automatic.start_chrome

    def start_and_remember():
        drivers.append(original_start())
        return drivers[-1]
    semi_automatic.start_chrome = start_and_remember

    with tempfile.TemporaryDirectory() as tmp:
        server = subprocess.Popen([sys.executable, str(Path(__file__).parent / "site_server.py"), tmp],
                                  stdout=subprocess.PIPE)
        server.stdout.readline()
        conn = database.connect(":memory:")
        metadata = {"mode": "semi-automatic", "purpose": "test", "test_run": True, "started_at": database.now(),
                    "git": {"commit": "test", "dirty": True}, "browser": {"browser_version": "test"},
                    "decoder": {"version": "test"}}
        ctx = {"conn": conn, "operator": "ae", "run_dir": Path(tmp), "cmp_list": CMP_LIST,
               "cmp_list_last_updated": "test", "run_id": database.insert_run(conn, metadata, operator="ae")}
        try:
            print("\n##### Code r: reject session, then accept session")
            run(ctx, "primary", ["j", "n", "n", "1", "", click("reject"), "Ablehnen", "",
                                 "j", click("accept")])
            print("\n##### Code n: only an accept session")
            run(ctx, "primary", ["j", "j", "n", "?", "n", "n", "", click("accept"), "Alle akzeptieren",
                                 "keine Ablehnen-Schaltfläche"])
            print("\n##### Code b: no banner after 3 reloads")
            run(ctx, "primary", ["n", "n", "n", "n", ""])
            first = conn.execute("SELECT id FROM examination WHERE role = 'primary' ORDER BY started_at").fetchone()[0]
            print("\n##### Crosscheck by the same person is refused")
            assert run(ctx, "crosscheck", [], linked_id=first) == "skipped"
            print("\n##### Blind crosscheck of the first examination by xy (results only after the label)")
            ctx["operator"] = "xy"
            run(ctx, "crosscheck", ["j", "n", "j", "1", "", click("reject"), "Ablehnen", "",
                                    "j", click("accept")], linked_id=first)
        finally:
            server.terminate()

        print("\n##### Stored")
        for row in conn.execute("""
            SELECT e.role, e.operator, e.status, l.outcome, l.reject_level, l.cookiewall_seen, l.settings_layer_available,
                   l.purposes_preselected, l.vendors_preselected, l.closed_with,
                   group_concat(s.kind || ':' || coalesce(s.banner_shown, '-') || '/' || coalesce(s.banner_reloads, '-')
                                || '/uac=' || coalesce(s.useractioncomplete_received, '-'), ' ') AS sessions
            FROM examination e JOIN label l ON l.examination_id = e.id JOIN session s ON s.examination_id = e.id
            GROUP BY e.id ORDER BY e.started_at"""):
            print("  ", dict(row))
        print("   phases:", [tuple(r) for r in conn.execute(
            "SELECT se.kind, group_concat(sn.phase, ' ') FROM session se JOIN snapshot sn ON sn.session_id = se.id "
            "GROUP BY se.id ORDER BY se.started_at")])
        print("   screenshots:", conn.execute("SELECT count(*) FROM screenshot").fetchone()[0],
              "| purposes after accept:", [r[0] for r in conn.execute(
                  "SELECT DISTINCT group_concat(te.value) FROM snapshot sn JOIN observation o ON o.snapshot_id = sn.id "
                  "AND o.channel = 'tcfapi' JOIN tc_string_entry te ON te.tc_string_id = o.tc_string_id "
                  "AND te.field = 'purpose_consent' WHERE sn.phase = 'after_accept' GROUP BY sn.id")])


if __name__ == "__main__":
    main()

"""Plays the whole crosscheck through on the local test site, with scripted answers in place of the
two persons: first examination of the six test pages (lists/pruefstand_gegenpruefung.csv) by ae,
crosscheck.select, blind crosscheck by xy (who rejects on the 2nd layer once, so that V2 differs),
crosscheck.evaluate with the recheck list, and the evaluation. Not part of pytest (needs a
browser). The clicks happen here, never in semi_automatic.py (CLAUDE.md).

    venv/bin/python tests/check_crosscheck_flow.py
"""
import argparse
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import crosscheck  # noqa: E402
import database  # noqa: E402
import evaluate  # noqa: E402
import semi_automatic  # noqa: E402
import site_data  # noqa: E402
import violations as v  # noqa: E402
from check_semi_automatic import CMP_LIST, click, drivers, scripted  # noqa: E402

LIST = Path(__file__).resolve().parents[1] / "lists" / "pruefstand_gegenpruefung.csv"


def answers_for(site, level="1"):
    """Answers of a person who follows Appendix D on the test page."""
    if "v2n" in site["url"]:
        # no reject button: no way to reject -> n, accept in the same session
        return ["j", "n", "n", "n", "", click("accept"), "Alle akzeptieren", ""]
    return ["j", "n", "n", level, "", click("reject"), "Ablehnen", "", "j", click("accept")]


def examine(ctx, site, role, answers, linked_id=None):
    semi_automatic.ask = scripted(answers)
    status = semi_automatic.examine(ctx, site, role, linked_id)
    assert not answers, f"unused answers: {answers}"
    return status


def main():
    original_start = semi_automatic.start_chrome

    def start_and_remember():
        drivers.append(original_start())
        return drivers[-1]
    semi_automatic.start_chrome = start_and_remember
    evaluate.gvl_for = lambda version, policy: None

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        server = subprocess.Popen([sys.executable, str(Path(__file__).parent / "site_server.py"), str(tmp)],
                                  stdout=subprocess.PIPE)
        server.stdout.readline()
        conn = database.connect(":memory:")
        metadata = {"mode": "semi-automatic", "purpose": "test", "test_run": True, "started_at": database.now(),
                    "git": {"commit": "test", "dirty": True}, "browser": {"browser_version": "test"},
                    "decoder": {"version": "test"}}
        ctx = {"conn": conn, "operator": "ae", "run_dir": tmp, "cmp_list": CMP_LIST, "cmp_list_last_updated": "test",
               "run_id": database.insert_run(conn, metadata, operator="ae")}
        try:
            sites = semi_automatic.read_sites(LIST, "ae", "primary")
            print("\n##### 1. First examination by ae")
            for site in sites:
                print(f"\n=== {site['domain']}")
                examine(ctx, site, "primary", answers_for(site))

            print("\n##### 2. crosscheck.py select")
            loaded = site_data.load_sites(conn, v.RANKS, "test")
            for domain, s in loaded.items():
                print(f"  {domain}: V2 {v.v2(s['semi_label']['label'])['value']}, V4 rank "
                      f"{v.V4_ORDER[v.v4_rank(s['semi'])] if v.v4_rank(s['semi']) is not None else '-'}")
            select_dir = tmp / "select"
            select_dir.mkdir()
            crosscheck.command_select(argparse.Namespace(operators="ae,xy", seed=crosscheck.SEED), loaded, select_dir)
            with open(select_dir / "crosscheck-xy.csv", newline="") as f:
                print("  crosscheck-xy.csv:", f.read().splitlines()[0])

            print("\n##### 3. Blind crosscheck by xy (rejects on the 2nd layer on the first page with a reject button)")
            ctx["operator"] = "xy"
            selected = semi_automatic.read_sites(select_dir / "crosscheck-xy.csv", "xy", "crosscheck")
            urls = {s["domain"]: s["url"] for s in sites}
            changed = False
            for site in selected:
                site["url"] = urls[site["domain"]]
                level = "1"
                if not changed and "v2n" not in site["url"]:
                    level, changed = "2", True
                print(f"\n=== {site['domain']} (crosscheck, level {level})")
                examine(ctx, site, "crosscheck", answers_for(site, level), linked_id=site["examination_id"])

            print("\n##### 4. crosscheck.py evaluate")
            evaluate_dir = tmp / "evaluate"
            evaluate_dir.mkdir()
            crosscheck.command_evaluate(site_data.load_sites(conn, v.RANKS, "test"), evaluate_dir)
            with open(evaluate_dir / "recheck.csv", newline="") as f:
                recheck = list(csv.DictReader(f))
            print("  recheck.csv:", [r["domain"] for r in recheck])

            print("\n##### 5. Recheck of the first page of the list by ae, then the evaluation")
            ctx["operator"] = "ae"
            first = next(s for s in sites if s["domain"] == recheck[0]["domain"])
            examine(ctx, first, "recheck", answers_for(first))
            markdown = evaluate.write_evaluation(conn, "test", tmp)
        finally:
            server.terminate()
        print("\n" + markdown[markdown.index("## Tab. III"):markdown.index("Zuordnung zu Matte")])
        print(markdown[markdown.index("## Gegenprüfung"):])


if __name__ == "__main__":
    main()

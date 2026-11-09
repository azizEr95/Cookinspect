"""Resuming an interrupted prefilter or automatic run (resume.py, E9), without browser and network."""
import csv
import json
import sys

import pytest

import automatic
import config
import database
import prefilter
import resume

COMMIT = {"value": "commit-1"}


def fake_metadata(mode, test_run, **extra):
    return {"mode": mode, "test_run": test_run, "started_at": database.now(), "ip_country": "DE",
            "git": {"commit": COMMIT["value"], "dirty": False},
            "browser": {"browser_version": config.CHROME_VERSION, "chromedriver_version": config.CHROME_VERSION},
            "decoder": {"version": "1.5.22"}, "config": {"PAUSE_BETWEEN_DOMAINS": 0},
            "consent_lists": {"cmp_list": {"path": str(config.DATA_DIR / "cmp-list.json"), "lastUpdated": "2026-11-05"}},
            **extra}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "PAUSE_BETWEEN_DOMAINS", 0)
    monkeypatch.setattr(prefilter, "new_metadata", fake_metadata)
    monkeypatch.setattr(automatic, "new_metadata", fake_metadata)
    monkeypatch.setattr(resume, "new_metadata", fake_metadata)
    monkeypatch.setattr(automatic, "check_robots", lambda url: {"robots_allowed": True})
    COMMIT["value"] = "commit-1"
    config.DATA_DIR.mkdir()
    (config.DATA_DIR / "cmp-list.json").write_text("{}")
    domain_list = tmp_path / "list.csv"
    domain_list.write_text("rank,domain\n" + "".join(f"{n},site{n}.de\n" for n in range(1, 6)))
    return domain_list


def fake_check_domain(rank, domain):
    """TCF on the sites with an even rank."""
    return {"rank": rank, "domain": domain, "checked_at": database.now(), "main_page_url": f"https://www.{domain}",
            "robots_status": 200, "robots_error": None, "robots_attempts": "[]", "robots_allowed": True,
            "robots_allowed_urllib": True, "robots_allowed_cookinspect": True, "loaded": True,
            "tcf": int(rank) % 2 == 0, "tcfapi": int(rank) % 2 == 0, "cmp_id": 7 if int(rank) % 2 == 0 else None}


def interrupt_after(calls, function):
    """function, but Ctrl+C at the call with number calls + 1 (as when the person presses Ctrl+C)."""
    count = {"n": 0}

    def wrapped(*args):
        count["n"] += 1
        if count["n"] > calls:
            raise KeyboardInterrupt
        return function(*args)
    return wrapped


def run(module, monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", [f"{module.__name__}.py", *args])
    module.main()


def only_run_dir(prefix):
    dirs = sorted(config.DATA_DIR.glob(f"{prefix}-test-*"))
    assert len(dirs) == 1
    return dirs[0]


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.reader(f))


def test_prefilter_resumed_gives_the_same_result_as_one_run(setup, monkeypatch):
    monkeypatch.setattr(prefilter, "check_domain", interrupt_after(2, fake_check_domain))
    with pytest.raises(SystemExit) as stop:
        run(prefilter, monkeypatch, str(setup), "--test")
    assert stop.value.code == 130
    run_dir = only_run_dir("prefilter")
    assert not (run_dir / "tcf_sites.csv").exists()

    checked = []
    monkeypatch.setattr(prefilter, "check_domain", lambda rank, domain: checked.append(domain) or fake_check_domain(rank, domain))
    run(prefilter, monkeypatch, "--resume", str(run_dir))
    assert checked == ["site3.de", "site4.de", "site5.de"]   # only the rest, nothing twice

    assert read_csv(run_dir / "tcf_sites.csv") == [["rank", "domain", "url", "cmp_id"],
                                                   ["2", "site2.de", "https://www.site2.de", "7"],
                                                   ["4", "site4.de", "https://www.site4.de", "7"]]
    assert [r[1] for r in read_csv(run_dir / "prefilter.csv")[1:]] == [f"site{n}.de" for n in range(1, 6)]
    funnel = json.loads((run_dir / "funnel.json").read_text())
    assert funnel["domains"] == 5 and funnel["columns"]["protego"]["tcf"] == 2

    conn = database.connect(config.database_path("test"))
    run_row = conn.execute("SELECT * FROM run").fetchone()
    assert run_row["finished_at"] is not None
    assert conn.execute("SELECT count(*) FROM run_part WHERE run_id = ?", (run_row["id"],)).fetchone()[0] == 1
    assert len(json.loads((run_dir / "run_metadata.json").read_text())["parts"]) == 1


def test_finished_run_cannot_be_resumed(setup, monkeypatch):
    monkeypatch.setattr(prefilter, "check_domain", fake_check_domain)
    run(prefilter, monkeypatch, str(setup), "--test")
    with pytest.raises(SystemExit, match="already finished"):
        run(prefilter, monkeypatch, "--resume", str(only_run_dir("prefilter")))


def test_real_run_with_other_commit_cannot_be_resumed(setup, monkeypatch):
    monkeypatch.setattr(prefilter, "check_domain", interrupt_after(1, fake_check_domain))
    with pytest.raises(SystemExit):
        run(prefilter, monkeypatch, str(setup), "--purpose", "vorab")
    run_dir = sorted(config.DATA_DIR.glob("prefilter-vorab-*"))[0]
    COMMIT["value"] = "commit-2"
    with pytest.raises(SystemExit, match="git commit"):
        run(prefilter, monkeypatch, "--resume", str(run_dir))
    conn = database.connect(config.database_path("vorab"))
    assert conn.execute("SELECT count(*) FROM run_part").fetchone()[0] == 0


def test_resume_of_the_wrong_mode_is_refused(setup, monkeypatch):
    monkeypatch.setattr(prefilter, "check_domain", interrupt_after(1, fake_check_domain))
    with pytest.raises(SystemExit):
        run(prefilter, monkeypatch, str(setup), "--test")
    with pytest.raises(SystemExit, match="not of 'automatic'"):
        run(automatic, monkeypatch, "--resume", str(only_run_dir("prefilter")))


def fake_examine_site(conn, run_id, site, cmp_list, cmp_list_last_updated):
    examination_id = database.insert_examination(conn, run_id, site["domain"], site["url"], "automatic")
    database.finish_examination(conn, examination_id, "done")
    return examination_id


def test_automatic_resumed_repeats_only_the_unfinished_site(setup, monkeypatch):
    def examine_then_interrupt(conn, run_id, site, cmp_list, cmp_list_last_updated):
        if site["domain"] == "site3.de":   # interrupted halfway: examination without status
            database.insert_examination(conn, run_id, site["domain"], site["url"], "automatic")
            raise KeyboardInterrupt
        return fake_examine_site(conn, run_id, site, cmp_list, cmp_list_last_updated)

    monkeypatch.setattr(automatic, "examine_site", examine_then_interrupt)
    with pytest.raises(SystemExit) as stop:
        run(automatic, monkeypatch, str(setup), "--test")
    assert stop.value.code == 130

    examined = []
    monkeypatch.setattr(automatic, "examine_site",
                        lambda conn, run_id, site, *rest: examined.append(site["domain"]) or fake_examine_site(conn, run_id, site, *rest))
    run(automatic, monkeypatch, "--resume", str(only_run_dir("automatic")))
    assert examined == ["site3.de", "site4.de", "site5.de"]

    conn = database.connect(config.database_path("test"))
    statuses = conn.execute("SELECT domain, status FROM examination ORDER BY started_at").fetchall()
    assert [tuple(r) for r in statuses if r["domain"] == "site3.de"] == [("site3.de", None), ("site3.de", "done")]
    assert conn.execute("SELECT finished_at FROM run").fetchone()[0] is not None

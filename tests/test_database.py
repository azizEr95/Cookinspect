"""Database (schema.sql, database.py, merge_databases.py): inserting, foreign keys, TC strings
without duplicates and with all IDs, nothing overwritten, crosscheck and correction next to
the first examination, an example query for V4 strict, the evaluation reading the database
(site_data.py) and its output files (evaluate.py), merging two files. Needs Node."""
import csv
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

import database
import decoder
import evaluate
import merge_databases
import site_data
import violations

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node for the decoder")

FIXTURES = json.loads((Path(__file__).parent / "tc_fixtures.json").read_text())
CMP_LIST = {"lastUpdated": "2026-10-22T16:00:21Z",
            "cmps": {"300": {"id": 300, "name": "Google LLC", "isCommercial": False}}}
METADATA = {"mode": "semi-automatic", "purpose": "test", "test_run": True, "started_at": "2026-10-29T10:00:00+00:00",
            "hostname": "mac-ae", "git": {"commit": "abc", "dirty": False},
            "browser": {"browser_version": "156.0.8078.73"}, "decoder": {"version": "1.5.22"},
            "consent_lists": {"gvl_latest": {"vendorListVersion": 182}, "cmp_list": {"lastUpdated": "2026-10-22"}},
            "website_list": {"info": {"tranco_list_id": "GQ3LK"}}}


@pytest.fixture(autouse=True)
def no_gvl_download(monkeypatch):
    monkeypatch.setattr(decoder, "load_gvl", lambda version, policy: None)


@pytest.fixture
def conn():
    return database.connect(":memory:")


def snapshot(tc_string, label_time="2026-10-29T10:00:05+00:00", channel_2="not_measurable", empty=False,
             request_tc=None):
    """A snapshot as capture.Capture.snapshot returns it."""
    event = {"kind": "event", "eventStatus": "tcloaded", "tcString": tc_string, "emptyTcData": empty}
    requests = []
    if request_tc:
        requests.append({"time": label_time, "url": f"https://ads.example.com/px?gdpr=1&gdpr_consent={request_tc}",
                         "method": "GET", "source": "iframe", "context": "ctx", "third_party": True,
                         "body_size": None, "body_status": None, "body": None,
                         "signals": [{"location": "query", "key": "gdpr", "value": "1", "kind": "gdpr_flag"},
                                     {"location": "query", "key": "gdpr_consent", "value": request_tc,
                                      "kind": "tc_string", "tc_version": 2}]})
    return {"label": "x", "taken_at": label_time, "page_url": "https://www.example.de/",
            "channel_1": {"latest_event": None if empty is None else event, "events_in_session": 1, "tcfapi_seen": True},
            "channel_2": {"status": channel_2, "reason": "no third-party iframe"},
            "storage": {"cookies": [{"name": "euconsent-v2", "domain": "www.example.de", "value": tc_string,
                                     "first_party": True, "tc_strings": [{"value": tc_string, "tc_version": 2}]}],
                        "local_storage": []},
            "requests": {"count": 120, "third_party": 80, "with_signals": requests}}


def closing(*tc_strings):
    messages = [{"kind": "injected", "url": "https://www.example.de/", "t": 20},
                {"kind": "registering", "url": "https://www.example.de/", "t": 90}]
    messages += [{"kind": "event", "eventStatus": "tcloaded", "tcString": s, "t": 100 + i} for i, s in enumerate(tc_strings)]
    return {"remove_listener": {"removed": True}, "tcf_messages": messages}


def examination_with_sessions(conn, run_id, reject_tc, accept_tc, operator="ae", role="primary", **links):
    examination_id = database.insert_examination(conn, run_id, "example.de", "https://www.example.de", role,
                                                 operator=operator, **links)
    for kind, tc in (("reject", reject_tc), ("accept", accept_tc)):
        session_id = database.insert_session(conn, examination_id, kind, "https://www.example.de")
        database.store_capture(conn, session_id, {"before": snapshot(FIXTURES["no_consent"]),
                                                  f"after_{kind}": snapshot(tc, request_tc=tc)},
                               closing(FIXTURES["no_consent"], tc), CMP_LIST, "2026-10-22")
        database.finish_session(conn, session_id, banner_shown=True, banner_reloads=0, useractioncomplete_received=True)
    return examination_id


def test_schema_and_foreign_keys(conn):
    assert conn.execute("SELECT version FROM schema_info").fetchone()[0] == database.SCHEMA_VERSION
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            database.insert(conn, "examination", {"id": "x", "run_id": "missing", "domain": "nowhere.de",
                                                  "role": "automatic", "url": "u", "started_at": "t"})


def test_run_and_prefilter_result_from_csv_values(conn):
    run_id = database.insert_run(conn, {**METADATA, "mode": "prefilter"})
    row = {"rank": "518", "domain": "google.de", "checked_at": "2026-10-29T08:00:00+00:00",
           "main_page_url": "https://www.google.de", "robots_status": "200", "robots_error": "",
           "robots_attempts": "[]", "robots_allowed": "True", "robots_allowed_urllib": "False",
           "robots_allowed_cookinspect": "False", "loaded": True, "load_attempts": 1, "blocked": False,
           "tcfapi": False, "tcf": False}
    database.insert_prefilter_result(conn, run_id, row, "GQ3LK")
    stored = conn.execute("SELECT * FROM prefilter_result").fetchone()
    assert (stored["robots_allowed_protego"], stored["robots_allowed_urllib"], stored["robots_allowed_cookinspect"]) == (1, 0, 0)
    assert stored["robots_status"] == 200 and stored["robots_error"] is None
    assert conn.execute("SELECT tranco_rank FROM website WHERE domain = 'google.de'").fetchone()[0] == 518
    assert conn.execute("SELECT tranco_list_id FROM run").fetchone()[0] == "GQ3LK"


def test_tc_strings_once_with_all_ids(conn):
    ids = database.store_tc_strings(conn, [FIXTURES["purposes_1_10"], FIXTURES["purposes_1_10"],
                                           FIXTURES["li_forbidden_3_to_6"], FIXTURES["v1_specification_example"]],
                                    CMP_LIST, "2026-10-22")
    database.store_tc_strings(conn, [FIXTURES["purposes_1_10"]], CMP_LIST)   # already there: nothing new
    assert conn.execute("SELECT count(*) FROM tc_string").fetchone()[0] == 3

    def entries(key, field):
        return [r[0] for r in conn.execute("SELECT value FROM tc_string_entry WHERE tc_string_id = ? AND field = ? "
                                           "ORDER BY value", (ids[FIXTURES[key]], field))]
    assert entries("purposes_1_10", "purpose_consent") == [1, 10]
    assert entries("purposes_1_10", "vendor_consent") == [755]
    assert entries("purposes_1_10", "vendor_disclosed") == [755, 793]
    assert entries("li_forbidden_3_to_6", "purpose_li") == [2, 3, 4, 5, 6, 7]
    v1 = conn.execute("SELECT tc_version, decoded FROM tc_string WHERE id = ?",
                      (ids[FIXTURES["v1_specification_example"]],)).fetchone()
    assert tuple(v1) == (1, 0)
    stored = conn.execute("SELECT gvl_available, gvl_version_used, cmp_valid, cmp_name, decoder_version "
                          "FROM tc_string WHERE id = ?", (ids[FIXTURES["purposes_1_10"]],)).fetchone()
    assert tuple(stored)[:4] == (0, 100, 1, "Google LLC")   # no GVL: IDs kept, only GVL checks missing


def test_capture_of_a_session(conn):
    run_id = database.insert_run(conn, METADATA)
    examination_id = examination_with_sessions(conn, run_id, FIXTURES["no_consent"], FIXTURES["all_purposes"])
    reject = conn.execute("SELECT id FROM session WHERE kind = 'reject'").fetchone()[0]
    statuses = {(r["channel"], r["status"]) for r in conn.execute(
        "SELECT o.channel, o.status FROM observation o JOIN snapshot s ON s.id = o.snapshot_id WHERE s.session_id = ?",
        (reject,))}
    assert statuses == {("tcfapi", "measured"), ("third_party_frame", "not_measurable"), ("cookie", "measured")}
    assert conn.execute("SELECT count(*) FROM tcf_event WHERE session_id = ?", (reject,)).fetchone()[0] == 4
    signal = conn.execute("SELECT rs.kind, rs.tc_string_id FROM request_signal rs JOIN request r ON r.id = rs.request_id "
                          "WHERE r.session_id = ? AND rs.kind = 'tc_string'", (reject,)).fetchone()
    assert signal["tc_string_id"] == database.tc_string_key(FIXTURES["no_consent"])
    assert conn.execute("SELECT third_party_request_count FROM snapshot LIMIT 1").fetchone()[0] == 80
    assert examination_id


def test_markers_empty_tc_data_and_no_useractioncomplete(conn):
    run_id = database.insert_run(conn, METADATA)
    examination_id = database.insert_examination(conn, run_id, "amazon.de", "https://www.amazon.de", "primary", "ae")
    session_id = database.insert_session(conn, examination_id, "reject", "https://www.amazon.de")
    database.store_capture(conn, session_id, {"before": snapshot(None, empty=True)},
                           {"remove_listener": None, "tcf_messages": [{"kind": "event", "emptyTcData": True}]}, CMP_LIST)
    database.finish_session(conn, session_id, banner_shown=True, banner_reloads=2, useractioncomplete_received=False)
    assert conn.execute("SELECT status FROM observation WHERE channel = 'tcfapi'").fetchone()[0] == "empty_tc_data"
    assert conn.execute("SELECT empty_tc_data FROM tcf_event").fetchone()[0] == 1
    session = conn.execute("SELECT useractioncomplete_received, banner_reloads FROM session").fetchone()
    assert tuple(session) == (0, 2)


def test_nothing_is_overwritten(conn):
    run_id = database.insert_run(conn, METADATA)
    examination_id = database.insert_examination(conn, run_id, "example.de", "https://www.example.de", "primary", "ae")
    database.insert_label(conn, examination_id, "ae", "rejected", reject_level=2, settings_layer_available=True,
                          purposes_preselected=True, vendors_preselected=False, cookiewall_seen=True)
    database.finish_examination(conn, examination_id, "done")   # closing fields may be set
    for statement in ("UPDATE label SET outcome = 'n'", "DELETE FROM label", "DELETE FROM examination",
                      "UPDATE examination SET operator = 'xy'", "UPDATE run SET mode = 'automatic'",
                      "DELETE FROM website"):
        with pytest.raises(sqlite3.IntegrityError):
            with conn:
                conn.execute(statement)
    assert conn.execute("SELECT outcome, reject_level, settings_layer_available, cookiewall_seen FROM label"
                        ).fetchone()[:] == ("rejected", 2, 1, 1)


def test_label_checks(conn):
    run_id = database.insert_run(conn, METADATA)
    examination_id = database.insert_examination(conn, run_id, "example.de", "https://www.example.de", "primary", "ae")
    with pytest.raises(sqlite3.IntegrityError):   # rejected needs the layer (V2)
        database.insert_label(conn, examination_id, "ae", "rejected")
    with pytest.raises(sqlite3.IntegrityError):   # unknown code
        database.insert_label(conn, examination_id, "ae", "q")
    with pytest.raises(sqlite3.IntegrityError):   # crosscheck without the examination it checks
        database.insert_examination(conn, run_id, "example.de", "https://www.example.de", "crosscheck", "xy")


def test_crosscheck_and_correction_next_to_the_first_examination(conn):
    run_id = database.insert_run(conn, METADATA)
    first = database.insert_examination(conn, run_id, "example.de", "https://www.example.de", "primary", "ae")
    database.insert_label(conn, first, "ae", "rejected", reject_level=1)
    cross = database.insert_examination(conn, run_id, "example.de", "https://www.example.de", "crosscheck", "xy",
                                        crosscheck_of=first)
    database.insert_label(conn, cross, "xy", "n")
    correction = database.insert_examination(conn, run_id, "example.de", "https://www.example.de", "correction", "ae",
                                             correction_of=first)
    database.insert_label(conn, correction, "ae", "rejected", reject_level=2)
    rows = conn.execute("SELECT e.role, e.operator, l.outcome, l.reject_level FROM examination e "
                        "JOIN label l ON l.examination_id = e.id ORDER BY e.started_at").fetchall()
    assert [tuple(r) for r in rows] == [("primary", "ae", "rejected", 1), ("crosscheck", "xy", "n", None),
                                        ("correction", "ae", "rejected", 2)]


# V4 strict (CLAUDE.md): after rejecting, all purposes are set that are set after accepting;
# only evaluable if the set after accepting is not empty. Here as a plain query on tc_string_entry.
V4_STRICT = """
WITH purposes AS (
    SELECT se.kind, te.value
    FROM session se
    JOIN snapshot sn ON sn.session_id = se.id AND sn.phase IN ('after_reject', 'after_accept')
    JOIN observation o ON o.snapshot_id = sn.id AND o.channel = 'tcfapi'
    JOIN tc_string_entry te ON te.tc_string_id = o.tc_string_id AND te.field = 'purpose_consent'
    WHERE se.examination_id = :examination
)
SELECT
    (SELECT count(*) FROM purposes WHERE kind = 'accept') > 0 AS evaluable,
    NOT EXISTS (SELECT value FROM purposes WHERE kind = 'accept'
                EXCEPT SELECT value FROM purposes WHERE kind = 'reject') AS violation
"""


def test_example_query_v4_strict(conn):
    run_id = database.insert_run(conn, METADATA)
    respected = examination_with_sessions(conn, run_id, FIXTURES["no_consent"], FIXTURES["all_purposes"])
    ignored = examination_with_sessions(conn, run_id, FIXTURES["all_purposes"], FIXTURES["all_purposes"])
    empty_accept = examination_with_sessions(conn, run_id, FIXTURES["no_consent"], FIXTURES["no_consent"])
    result = {name: tuple(conn.execute(V4_STRICT, {"examination": e}).fetchone())
              for name, e in (("respected", respected), ("ignored", ignored), ("empty_accept", empty_accept))}
    assert result["respected"] == (1, 0)
    assert result["ignored"] == (1, 1)
    assert result["empty_accept"][0] == 0   # "not evaluable"


def test_merge_two_databases(tmp_path):
    files = []
    for operator in ("ae", "xy"):
        path = tmp_path / f"{operator}.sqlite"
        conn = database.connect(str(path))
        run_id = database.insert_run(conn, {**METADATA, "hostname": f"mac-{operator}"}, operator=operator)
        examination_with_sessions(conn, run_id, FIXTURES["no_consent"], FIXTURES["all_purposes"], operator=operator)
        conn.close()
        files.append(path)
    target = tmp_path / "merged.sqlite"
    first = merge_databases.merge(str(target), str(files[0]))
    second = merge_databases.merge(str(target), str(files[1]))
    again = merge_databases.merge(str(target), str(files[1]))
    assert first["examination"] == (1, 0) and second["examination"] == (1, 0)
    assert second["tc_string"] == (0, 0)          # same strings, same SHA-256 keys
    assert all(added == 0 for added, _ in again.values())
    merged = database.connect(str(target))
    assert merged.execute("SELECT count(*) FROM session").fetchone()[0] == 4
    assert sorted(r[0] for r in merged.execute("SELECT operator FROM run")) == ["ae", "xy"]


def test_merge_reports_two_prefilter_measurement_runs(tmp_path):
    files = []
    for operator in ("ae", "xy"):
        path = tmp_path / f"{operator}.sqlite"
        conn = database.connect(str(path))
        database.insert_run(conn, {**METADATA, "mode": "prefilter", "purpose": "messung", "test_run": False,
                                   "hostname": f"mac-{operator}"})
        conn.close()
        files.append(path)
    target = tmp_path / "merged.sqlite"
    merge_databases.merge(str(target), str(files[0]))
    assert len(merge_databases.prefilter_measurement_runs(str(target))) == 1
    merge_databases.merge(str(target), str(files[1]))
    assert [run[1] for run in merge_databases.prefilter_measurement_runs(str(target))] == ["mac-ae", "mac-xy"]


def test_split_sites_alternates_within_each_cmp():
    from split_sites import split
    sites = [{"rank": r, "domain": d, "url": f"https://www.{d}", "cmp_id": c}
             for r, d, c in [("1", "a.de", "6"), ("2", "b.de", "6"), ("3", "c.de", "345"), ("4", "d.de", "6"),
                             ("5", "e.de", "345"), ("6", "f.de", "")]]
    assigned = {s["domain"]: s["first_operator"] for s in split(sites, ["ae", "xy"])}
    # cmp '' first (f), then 6 (a, b, d), then 345 (c, e), in turn
    assert assigned == {"f.de": "ae", "a.de": "xy", "b.de": "ae", "d.de": "xy", "c.de": "ae", "e.de": "xy"}


def test_old_file_is_migrated_when_opened(tmp_path):
    # a file with schema version 1 (as written before Phase 7) gets the table screenshot
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(database.SCHEMA_PATH.read_text().split("-- Screenshots of the banner")[0]
                       .replace("VALUES (3);", "VALUES (1);")
                       .replace("    cookiewall_seen             INTEGER,", "    -- (added in version 3)"))
    conn.close()
    conn = database.connect(str(path))
    assert conn.execute("SELECT version FROM schema_info").fetchone()[0] == database.SCHEMA_VERSION
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'screenshot'").fetchone()
    assert "cookiewall_seen" in [r["name"] for r in conn.execute("PRAGMA table_info(label)")]


def semi_examination(conn, run_id, outcome, reject_tc, accept_tc, operator="ae", role="primary", **links):
    """A semi-automatic examination with label and the snapshots after the reload."""
    examination_id = database.insert_examination(conn, run_id, "example.de", "https://www.example.de", role,
                                                 operator=operator, **links)
    for kind, tc in (("reject", reject_tc), ("accept", accept_tc)):
        session_id = database.insert_session(conn, examination_id, kind, "https://www.example.de")
        database.store_capture(conn, session_id, {"before": snapshot(FIXTURES["no_consent"]),
                                                  f"after_{kind}": snapshot(tc), f"after_{kind}_reload": snapshot(tc)},
                               closing(FIXTURES["no_consent"], tc), CMP_LIST, "2026-10-22")
    database.insert_label(conn, examination_id, operator, outcome, reject_level=1 if outcome == "rejected" else None)
    database.finish_examination(conn, examination_id, "done")
    return examination_id


def test_evaluation_reads_the_database_and_takes_the_milder_crosscheck(conn):
    # first examination: consent ignored (V4); blind crosscheck: consent respected -> milder, counts
    run_id = database.insert_run(conn, METADATA)
    first = semi_examination(conn, run_id, "rejected", FIXTURES["all_purposes"], FIXTURES["all_purposes"])
    semi_examination(conn, run_id, "rejected", FIXTURES["no_consent"], FIXTURES["all_purposes"], operator="xy",
                     role="crosscheck", crosscheck_of=first)
    site = site_data.load_sites(conn, violations.RANKS)["example.de"]
    assert site["crosscheck"]["differs_by_kind"] == {"V2": False, "V4": True}
    assert (site["semi"]["operator"], site["semi_label"]["operator"]) == ("xy", "ae")
    assert violations.v4(site["semi"], "strict")["value"] == violations.NO
    assert violations.v4(site["crosscheck"]["primary"], "strict")["value"] == violations.YES
    assert violations.v4(site["crosscheck"]["primary"], "lax")["purposes_after_reject"] == list(range(1, 12))


def test_evaluation_writes_csv_and_json(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "gvl_for", lambda version, policy: None)
    run_id = database.insert_run(conn, METADATA)
    semi_examination(conn, run_id, "rejected", FIXTURES["all_purposes"], FIXTURES["all_purposes"])
    markdown = evaluate.write_evaluation(conn, "test", tmp_path)
    with open(tmp_path / "sites.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [(r["domain"], r["code"], r["v4_strict"], r["v4_matte"], r["v4_purposes_after_reject"]) for r in rows] == [
        ("example.de", "r", "ja", "ja", " ".join(map(str, range(1, 12))))]
    assert rows[0]["v1"] == "nicht auswertbar" and rows[0]["v1_reason"] == "kein automatischer Modus"
    header = list(rows[0])
    assert header[:3] == ["rank", "domain", "cmp_id"]
    assert all(c.endswith("_reason") for c in header[header.index("v1_reason"):])   # reasons at the end
    tables = json.loads((tmp_path / "tables.json").read_text())
    assert tables["tab_iii"]["v4"]["hits"] == 1 and tables["tab_iii"]["v4"]["denominator"] == 1
    assert tables["sites"]["example.de"]["v4_strict"]["value"] == "ja"
    assert (tmp_path / "tables.md").read_text().strip() == markdown.strip()
    assert "Kein Vorfilter-Lauf" in markdown

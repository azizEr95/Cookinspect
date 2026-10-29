"""SQLite database (schema.sql) with the standard library sqlite3, no SQLAlchemy.

The file depends on the purpose of the run (config.database_path: data/test.sqlite,
data/vorab.sqlite, data/messung.sqlite). Each person has their own files on their own Mac;
merge_databases.py merges them. Rows get random UUIDs, websites are keyed by domain, TC strings by their SHA-256,
so that IDs never collide when merging.

Every function takes an open connection and writes in one transaction (with conn:).

    conn = connect(config.database_path("messung"))
    run_id = insert_run(conn, metadata)
    ...
"""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone

import config
import decoder
from capture import registrable_domain

SCHEMA_PATH = config.REPO_DIR / "schema.sql"
SCHEMA_VERSION = 2
# Older files are brought up to date when opened; a migration only adds tables or columns.
MIGRATIONS_DIR = config.REPO_DIR / "migrations"   # <version>.sql: from version - 1 to version

# decoded field of decoder.py -> field in tc_string_entry
ENTRY_FIELDS = {
    "purposeConsents": "purpose_consent",
    "purposeLegitimateInterests": "purpose_li",
    "vendorConsents": "vendor_consent",
    "vendorLegitimateInterests": "vendor_li",
    "vendorsDisclosed": "vendor_disclosed",
    "specialFeatureOptins": "special_feature",
    "publisherConsents": "publisher_consent",
    "publisherLegitimateInterests": "publisher_li",
    "publisherCustomConsents": "publisher_custom_consent",
    "publisherCustomLegitimateInterests": "publisher_custom_li",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def new_id():
    return uuid.uuid4().hex


def tc_string_key(tc_string):
    return hashlib.sha256(tc_string.encode()).hexdigest()


def connect(path):
    """Opens the database (a path, e.g. config.database_path(purpose), or ":memory:") and creates
    the schema if the file is new."""
    if str(path) != ":memory:":
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if not conn.execute("SELECT name FROM sqlite_master WHERE name = 'schema_info'").fetchone():
        conn.executescript(SCHEMA_PATH.read_text())
    migrate(conn)
    return conn


def migrate(conn):
    version = conn.execute("SELECT version FROM schema_info").fetchone()[0]
    while version < SCHEMA_VERSION:
        version += 1
        conn.executescript((MIGRATIONS_DIR / f"{version}.sql").read_text())
        with conn:
            conn.execute("UPDATE schema_info SET version = ?", (version,))


def insert(conn, table, row):
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", list(row.values()))


def as_int(value):
    """Booleans and numbers from CSV strings, JSON or Python to SQLite integers."""
    if value in (None, ""):
        return None
    if value in (True, "True", "true"):
        return 1
    if value in (False, "False", "false"):
        return 0
    return int(value)


# --- run, website, prefilter

def insert_run(conn, metadata, operator=None):
    """metadata: from run_metadata.new_metadata. Returns the id of the run."""
    run_id = new_id()
    lists = metadata.get("consent_lists", {})
    website_list = (metadata.get("website_list") or {}).get("info") or {}
    with conn:
        insert(conn, "run", {
            "id": run_id, "mode": metadata["mode"], "purpose": metadata.get("purpose", "test"),
            "test_run": as_int(metadata["test_run"]), "operator": operator,
            "hostname": metadata.get("hostname"), "started_at": metadata["started_at"],
            "git_commit": metadata["git"]["commit"], "git_dirty": as_int(metadata["git"]["dirty"]),
            "chrome_version": metadata["browser"]["browser_version"],
            "decoder_version": metadata["decoder"]["version"],
            "gvl_latest_version": lists.get("gvl_latest", {}).get("vendorListVersion"),
            "cmp_list_last_updated": lists.get("cmp_list", {}).get("lastUpdated"),
            "tranco_list_id": website_list.get("tranco_list_id"),
            "metadata_json": json.dumps(metadata, ensure_ascii=False),
        })
    return run_id


def finish_run(conn, run_id):
    with conn:
        conn.execute("UPDATE run SET finished_at = ? WHERE id = ?", (now(), run_id))


def ensure_website(conn, domain, tranco_rank=None, tranco_list_id=None):
    with conn:
        conn.execute("INSERT OR IGNORE INTO website (domain, tranco_rank, tranco_list_id) VALUES (?, ?, ?)",
                     (domain, as_int(tranco_rank), tranco_list_id))
    return domain


PREFILTER_COLUMNS = {   # column in prefilter_result <- field of a prefilter.py row
    "checked_at": "checked_at", "main_page_url": "main_page_url", "robots_status": "robots_status",
    "robots_error": "robots_error", "robots_attempts_json": "robots_attempts",
    "robots_allowed_protego": "robots_allowed", "robots_allowed_urllib": "robots_allowed_urllib",
    "robots_allowed_cookinspect": "robots_allowed_cookinspect", "loaded": "loaded",
    "load_attempts": "load_attempts", "load_errors": "load_errors", "final_url": "final_url",
    "http_status": "http_status", "title": "title", "blocked": "blocked", "block_reason": "block_reason",
    "tcfapi": "tcfapi", "tcf": "tcf", "ping_error": "ping_error", "cmp_id": "cmp_id",
    "cmp_version": "cmp_version", "cmp_status": "cmp_status", "cmp_loaded": "cmp_loaded",
    "display_status": "display_status", "gdpr_applies": "gdpr_applies", "api_version": "api_version",
    "tcf_policy_version": "tcf_policy_version", "gvl_version": "gvl_version",
    "tcfapi_locator": "tcfapi_locator", "cmp_v1": "cmp_v1",
}
PREFILTER_INTEGERS = {"robots_status", "robots_allowed_protego", "robots_allowed_urllib", "robots_allowed_cookinspect",
                      "loaded", "load_attempts", "http_status", "blocked", "tcfapi", "tcf", "cmp_id", "cmp_version",
                      "cmp_loaded", "gdpr_applies", "tcf_policy_version", "gvl_version", "tcfapi_locator", "cmp_v1"}


def insert_prefilter_result(conn, run_id, row, tranco_list_id=None):
    """row: one row of prefilter.py (check_domain)."""
    ensure_website(conn, row["domain"], row.get("rank"), tranco_list_id)
    values = {"id": new_id(), "run_id": run_id, "domain": row["domain"]}
    for column, field in PREFILTER_COLUMNS.items():
        value = row.get(field)
        values[column] = as_int(value) if column in PREFILTER_INTEGERS else (None if value == "" else value)
    for column in ("robots_allowed_protego", "robots_allowed_urllib", "robots_allowed_cookinspect", "loaded"):
        values[column] = values[column] or 0
    with conn:
        insert(conn, "prefilter_result", values)
    return values["id"]


# --- examination, label, session

def insert_examination(conn, run_id, domain, url, role, operator=None, crosscheck_of=None, correction_of=None):
    examination_id = new_id()
    ensure_website(conn, domain)
    with conn:
        insert(conn, "examination", {
            "id": examination_id, "run_id": run_id, "domain": domain, "operator": operator, "role": role,
            "crosscheck_of": crosscheck_of, "correction_of": correction_of, "url": url, "started_at": now()})
    return examination_id


def finish_examination(conn, examination_id, status, cookiewall_suspected=None, cookiewall_reason=None, note=None):
    with conn:
        conn.execute("UPDATE examination SET finished_at = ?, status = ?, cookiewall_suspected = ?, "
                     "cookiewall_reason = ?, note = ? WHERE id = ?",
                     (now(), status, as_int(cookiewall_suspected), cookiewall_reason, note, examination_id))


def insert_label(conn, examination_id, operator, outcome, reject_level=None, settings_layer_available=None,
                 purposes_preselected=None, vendors_preselected=None, privacy_policy_searched=None,
                 closed_with=None, note=None):
    with conn:
        insert(conn, "label", {
            "examination_id": examination_id, "operator": operator, "labeled_at": now(), "outcome": outcome,
            "reject_level": reject_level, "settings_layer_available": as_int(settings_layer_available),
            "purposes_preselected": as_int(purposes_preselected), "vendors_preselected": as_int(vendors_preselected),
            "privacy_policy_searched": as_int(privacy_policy_searched), "closed_with": closed_with, "note": note})


def insert_session(conn, examination_id, kind, url, number=1, started_at=None):
    """started_at: when the browser was started, if the session is stored only later (in the
    semi-automatic mode the kind is known only after the person entered the code)."""
    session_id = new_id()
    with conn:
        insert(conn, "session", {"id": session_id, "examination_id": examination_id, "kind": kind,
                                 "number": number, "url": url, "started_at": started_at or now()})
    return session_id


SESSION_CLOSING_FIELDS = ("loaded", "load_attempts", "load_errors", "final_url", "http_status", "blocked",
                          "block_reason", "cookiewall_suspected", "cookiewall_reason", "banner_shown", "banner_reloads",
                          "useractioncomplete_received", "useractioncomplete_wait_s", "remove_listener_json")
SESSION_FLAGS = {"loaded", "blocked", "cookiewall_suspected", "banner_shown", "useractioncomplete_received"}


def insert_screenshot(conn, session_id, moment, path):
    with conn:
        insert(conn, "screenshot", {"id": new_id(), "session_id": session_id, "moment": moment,
                                    "path": str(path), "taken_at": now()})


def finish_session(conn, session_id, remove_listener=None, **fields):
    """Sets the closing fields of a session (SESSION_CLOSING_FIELDS), e.g. loaded=True,
    useractioncomplete_received=False (marker "no useractioncomplete")."""
    unknown = set(fields) - set(SESSION_CLOSING_FIELDS)
    if unknown:
        raise ValueError(f"not a closing field of session: {sorted(unknown)}")
    values = {name: as_int(value) if name in SESSION_FLAGS else value for name, value in fields.items()}
    if remove_listener is not None:
        values["remove_listener_json"] = json.dumps(remove_listener)
    values["ended_at"] = now()
    assignments = ", ".join(f"{name} = ?" for name in values)
    with conn:
        conn.execute(f"UPDATE session SET {assignments} WHERE id = ?", [*values.values(), session_id])


# --- TC strings

def store_tc_strings(conn, tc_strings, cmp_list, cmp_list_last_updated=None):
    """Decodes and stores the strings not yet in the database. Returns {string: id}."""
    tc_strings = sorted({s for s in tc_strings if s})
    ids = {s: tc_string_key(s) for s in tc_strings}
    known = {row["id"] for row in conn.execute(
        f"SELECT id FROM tc_string WHERE id IN ({', '.join('?' for _ in ids)})", list(ids.values()))} if ids else set()
    new = [s for s in tc_strings if ids[s] not in known]
    with conn:
        for entry in decoder.analyse(new, cmp_list):
            insert_tc_string(conn, entry, cmp_list_last_updated)
    return ids


def insert_tc_string(conn, entry, cmp_list_last_updated=None):
    """entry: one result of decoder.analyse."""
    tc_string = entry["tc_string"]
    decoded = entry["decoded"]
    checks = entry.get("checks", {})
    cmp = checks.get("cmp", {})
    key = tc_string_key(tc_string)
    insert(conn, "tc_string", {
        "id": key, "tc_string": tc_string, "tc_version": entry["tc_version"],
        "decoded": as_int(decoded.get("decoded")) or 0, "decode_error": decoded.get("reason"),
        "created": decoded.get("created"), "last_updated": decoded.get("lastUpdated"),
        "cmp_id": decoded.get("cmpId"), "cmp_id_replaced_for_decoding": as_int(decoded.get("cmpIdReplacedForDecoding")),
        "cmp_version": decoded.get("cmpVersion"), "consent_screen": decoded.get("consentScreen"),
        "consent_language": decoded.get("consentLanguage"), "vendor_list_version": decoded.get("vendorListVersion"),
        "policy_version": decoded.get("policyVersion"), "is_service_specific": as_int(decoded.get("isServiceSpecific")),
        "use_non_standard_texts": as_int(decoded.get("useNonStandardTexts")),
        "purpose_one_treatment": as_int(decoded.get("purposeOneTreatment")),
        "publisher_country_code": decoded.get("publisherCountryCode"),
        "num_custom_purposes": decoded.get("numCustomPurposes"),
        "segments": json.dumps(decoded.get("segments")) if decoded.get("segments") else None,
        "disclosed_vendors_present": as_int(decoded.get("disclosedVendorsPresent")),
        "publisher_tc_present": as_int(decoded.get("publisherTCPresent")),
        "policy_version_outdated": as_int(checks.get("policy_version_outdated")),
        "disclosed_vendors_missing_after_v23_deadline": as_int(checks.get("disclosed_vendors_missing_after_v23_deadline")),
        "gvl_version_used": checks.get("gvl_version_used"), "gvl_series": checks.get("gvl_series"),
        "gvl_available": as_int(checks.get("gvl_available")),
        "cmp_valid": as_int(cmp.get("valid")), "cmp_reason": cmp.get("reason"), "cmp_name": cmp.get("name"),
        "cmp_list_last_updated": cmp_list_last_updated if checks else None,
        "decoder_version": decoder.decoder_version(), "decoded_json": json.dumps(decoded), "checks_json": json.dumps(checks),
    })
    for field, entry_field in ENTRY_FIELDS.items():
        for value in decoded.get(field) or []:
            conn.execute("INSERT INTO tc_string_entry (tc_string_id, field, value) VALUES (?, ?, ?)",
                         (key, entry_field, value))
    for restriction in decoded.get("publisherRestrictions") or []:
        for vendor_id in restriction["vendorIds"]:
            conn.execute("INSERT OR IGNORE INTO tc_publisher_restriction VALUES (?, ?, ?, ?)",
                         (key, restriction["purposeId"], restriction["restrictionType"], vendor_id))


# --- capture (capture.py) of one session

def tc_strings_of_capture(snapshots, messages):
    """All TC strings of a session: channel 1 events, channel 2, storage, requests."""
    found = [m.get("tcString") for m in messages if m.get("kind") == "event"]
    for snapshot in snapshots:
        found.append((snapshot["channel_2"].get("event") or {}).get("tcString"))
        for item in snapshot["storage"]["cookies"] + snapshot["storage"]["local_storage"]:
            found.extend(s["value"] for s in item["tc_strings"])
        for request in snapshot["requests"]["with_signals"]:
            found.extend(s["value"] for s in request["signals"] if s["kind"] == "tc_string")
    return [s for s in found if isinstance(s, str) and s]


def channel_1_observation(snapshot, ids):
    channel = snapshot["channel_1"]
    latest = channel["latest_event"]
    if latest is None:
        status = "no_tc_string" if channel["tcfapi_seen"] else "no_tcfapi"
    elif latest.get("emptyTcData"):
        status = "empty_tc_data"
    elif latest.get("tcString"):
        status = "measured"
    else:
        status = "no_tc_string"
    return {"channel": "tcfapi", "status": status, "event_status": (latest or {}).get("eventStatus"),
            "tc_string_id": ids.get((latest or {}).get("tcString"))}


def channel_2_observation(snapshot, ids):
    channel = snapshot["channel_2"]
    event = channel.get("event") or {}
    status = {"answered": "measured" if event.get("tcString") else "no_tc_string",
              "not_measurable": "not_measurable", "no_answer": "no_answer", "no_locator": "no_answer",
              "skipped": "not_measurable"}.get(channel["status"], "error")
    return {"channel": "third_party_frame", "status": status, "detail": channel.get("frame_src"),
            "event_status": event.get("eventStatus"), "tc_string_id": ids.get(event.get("tcString")),
            "reason": channel.get("reason")}


def storage_observations(snapshot, ids):
    rows = []
    for cookie in snapshot["storage"]["cookies"]:
        for tc in cookie["tc_strings"] or [None]:
            rows.append({"channel": "cookie", "status": "measured" if tc else "no_tc_string",
                         "detail": f"{cookie['name']}@{cookie['domain']}", "first_party": as_int(cookie["first_party"]),
                         "tc_string_id": ids.get(tc["value"]) if tc else None})
    for item in snapshot["storage"]["local_storage"]:
        for tc in item["tc_strings"] or [None]:
            rows.append({"channel": "local_storage", "status": "measured" if tc else "no_tc_string",
                         "detail": item["key"], "first_party": 1,
                         "tc_string_id": ids.get(tc["value"]) if tc else None})
    return rows


def insert_snapshot(conn, session_id, phase, snapshot, ids):
    snapshot_id = new_id()
    insert(conn, "snapshot", {"id": snapshot_id, "session_id": session_id, "phase": phase,
                              "taken_at": snapshot["taken_at"], "page_url": snapshot["page_url"],
                              "request_count": snapshot["requests"]["count"],
                              "third_party_request_count": snapshot["requests"]["third_party"]})
    observations = [channel_1_observation(snapshot, ids), channel_2_observation(snapshot, ids),
                    *storage_observations(snapshot, ids)]
    for observation in observations:
        insert(conn, "observation", {"id": new_id(), "snapshot_id": snapshot_id, **observation})
    for request in snapshot["requests"]["with_signals"]:
        insert_request(conn, session_id, snapshot_id, request, ids)
    return snapshot_id


def insert_request(conn, session_id, snapshot_id, request, ids):
    request_id = new_id()
    insert(conn, "request", {
        "id": request_id, "session_id": session_id, "until_snapshot_id": snapshot_id, "time": request["time"],
        "url": request["url"], "method": request["method"], "source": request["source"],
        "context": request["context"], "third_party": as_int(request["third_party"]),
        "registrable_domain": registrable_domain(request["url"]), "body_size": request["body_size"],
        "body_status": request["body_status"], "body": request["body"]})
    for signal in request["signals"]:
        insert(conn, "request_signal", {
            "id": new_id(), "request_id": request_id, "location": signal["location"], "key": signal["key"],
            "value": None if signal["value"] is None else str(signal["value"]), "kind": signal["kind"],
            "tc_string_id": ids.get(signal["value"]) if signal["kind"] == "tc_string" else None})


def insert_tcf_events(conn, session_id, messages, ids):
    for seq, message in enumerate(messages):
        insert(conn, "tcf_event", {
            "id": new_id(), "session_id": session_id, "seq": seq, "kind": message["kind"],
            "document_url": message.get("url"), "page_time_ms": message.get("t"), "at": message.get("at"),
            "received_at": message.get("received_at"), "event_status": message.get("eventStatus"),
            "listener_id": message.get("listenerId"), "success": as_int(message.get("success")),
            "empty_tc_data": as_int(message.get("emptyTcData")), "cmp_id": message.get("cmpId"),
            "cmp_status": message.get("cmpStatus"), "gdpr_applies": as_int(message.get("gdprApplies")),
            "tcf_policy_version": message.get("tcfPolicyVersion"), "tc_string_id": ids.get(message.get("tcString"))})


def store_capture(conn, session_id, snapshots, closing, cmp_list, cmp_list_last_updated=None):
    """Stores everything capture.py recorded in one session.
    snapshots: {phase: Capture.snapshot(...)}; closing: Capture.close()."""
    messages = closing["tcf_messages"]
    ids = store_tc_strings(conn, tc_strings_of_capture(snapshots.values(), messages), cmp_list, cmp_list_last_updated)
    with conn:
        for phase, snapshot in snapshots.items():
            insert_snapshot(conn, session_id, phase, snapshot, ids)
        insert_tcf_events(conn, session_id, messages, ids)
    return ids

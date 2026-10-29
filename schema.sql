-- Database of the Cookinspect reimplementation (TCF v2.2/v2.3), SQLite.
--
-- Each person works on their own Mac with their own file (data/cookinspect.sqlite);
-- merge_databases.py merges the files. So that no IDs collide:
--   - rows created during a measurement have a random UUID as id (database.new_id)
--   - website is keyed by its domain, tc_string by the SHA-256 of the string
--
-- Nothing is overwritten: measurement data and labels are only inserted. Triggers at the end
-- refuse UPDATE and DELETE, except for the fields that close a run, an examination or a session.
-- Violations are not stored; Phase 8 computes them from these tables.

CREATE TABLE schema_info (
    version         INTEGER NOT NULL
);
INSERT INTO schema_info (version) VALUES (1);

-- One run of prefilter.py, of the automatic or of the semi-automatic mode.
CREATE TABLE run (
    id                      TEXT PRIMARY KEY,
    mode                    TEXT NOT NULL CHECK (mode IN ('prefilter', 'automatic', 'semi-automatic', 'full', 'test-cmp')),
    purpose                 TEXT NOT NULL CHECK (purpose IN ('vorab', 'messung', 'test')),
    test_run                INTEGER NOT NULL,
    operator                TEXT,               -- short code of the person; NULL for runs without a person
    hostname                TEXT,               -- which Mac
    started_at              TEXT NOT NULL,
    finished_at             TEXT,
    git_commit              TEXT,
    git_dirty               INTEGER,
    chrome_version          TEXT,
    decoder_version         TEXT,
    gvl_latest_version      INTEGER,
    cmp_list_last_updated   TEXT,
    tranco_list_id          TEXT,
    metadata_json           TEXT NOT NULL       -- everything from run_metadata.py
);

CREATE TABLE website (
    domain          TEXT PRIMARY KEY,
    tranco_rank     INTEGER,
    tranco_list_id  TEXT
);

-- Prefilter: one row per run and website (prefilter.py).
CREATE TABLE prefilter_result (
    id                          TEXT PRIMARY KEY,
    run_id                      TEXT NOT NULL REFERENCES run(id),
    domain                      TEXT NOT NULL REFERENCES website(domain),
    checked_at                  TEXT NOT NULL,
    main_page_url               TEXT,
    robots_status               INTEGER,
    robots_error                TEXT,
    robots_attempts_json        TEXT,
    robots_allowed_protego      INTEGER NOT NULL,   -- crawled is only what Protego allows
    robots_allowed_urllib       INTEGER NOT NULL,
    robots_allowed_cookinspect  INTEGER NOT NULL,   -- counts for the comparison with Matte, Tab. II
    loaded                      INTEGER NOT NULL,
    load_attempts               INTEGER,
    load_errors                 TEXT,
    final_url                   TEXT,
    http_status                 INTEGER,
    title                       TEXT,
    blocked                     INTEGER,
    block_reason                TEXT,
    tcfapi                      INTEGER,
    tcf                         INTEGER,            -- __tcfapi exists and answers ping
    ping_error                  TEXT,
    cmp_id                      INTEGER,
    cmp_version                 INTEGER,
    cmp_status                  TEXT,
    cmp_loaded                  INTEGER,
    display_status              TEXT,
    gdpr_applies                INTEGER,
    api_version                 TEXT,
    tcf_policy_version          INTEGER,
    gvl_version                 INTEGER,
    tcfapi_locator              INTEGER,
    cmp_v1                      INTEGER,
    UNIQUE (run_id, domain)
);

-- One examination of a website: by a person (semi-automatic) or automatic. A crosscheck, a
-- recheck of all sites of a CMP or a correction is a new row, it never replaces the first one.
CREATE TABLE examination (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES run(id),
    domain              TEXT NOT NULL REFERENCES website(domain),
    operator            TEXT,                   -- short code; NULL = automatic
    role                TEXT NOT NULL CHECK (role IN ('automatic', 'primary', 'crosscheck', 'recheck', 'correction')),
    crosscheck_of       TEXT REFERENCES examination(id),   -- the examination checked blind
    correction_of       TEXT REFERENCES examination(id),   -- the examination corrected; the latest correction counts
    url                 TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT CHECK (status IN ('done', 'aborted', 'unreachable', 'robots_disallowed')),
    cookiewall_suspected INTEGER,               -- automatic mode: HEURISTIC, suspected in at least one session
    cookiewall_reason   TEXT,
    note                TEXT,
    CHECK ((role = 'crosscheck') = (crosscheck_of IS NOT NULL)),
    CHECK ((role = 'correction') = (correction_of IS NOT NULL))
);

-- What the person entered, once per semi-automatic examination (Appendix D).
CREATE TABLE label (
    examination_id              TEXT PRIMARY KEY REFERENCES examination(id),
    operator                    TEXT NOT NULL,
    labeled_at                  TEXT NOT NULL,
    outcome                     TEXT NOT NULL CHECK (outcome IN ('rejected', 'n', 'b', 'x', 'w')),
    reject_level                INTEGER CHECK (reject_level IN (1, 2)),   -- V2: 1st or 2nd layer; NULL if not rejected
    settings_layer_available    INTEGER,        -- is there a 2nd layer (settings)? Denominator of V3 (Matte, p. 7)
    purposes_preselected        INTEGER,        -- V3, purposes on the 2nd layer
    vendors_preselected         INTEGER,        -- V3, vendors (separately)
    privacy_policy_searched     INTEGER,        -- looked for a way to reject in the privacy policy (at most 10 s)
    closed_with                 TEXT,           -- text of the button that closed the banner
    note                        TEXT,
    CHECK (outcome != 'rejected' OR reject_level IS NOT NULL)
);

-- One fresh browser.
CREATE TABLE session (
    id                              TEXT PRIMARY KEY,
    examination_id                  TEXT NOT NULL REFERENCES examination(id),
    kind                            TEXT NOT NULL CHECK (kind IN ('automatic', 'reject', 'accept')),
    number                          INTEGER NOT NULL DEFAULT 1,   -- automatic: session 1 or 2
    url                             TEXT NOT NULL,
    started_at                      TEXT NOT NULL,
    ended_at                        TEXT,
    loaded                          INTEGER,        -- start page loaded (config.MAX_TRIES_TIMEOUT attempts)
    load_attempts                   INTEGER,
    load_errors                     TEXT,
    final_url                       TEXT,
    http_status                     INTEGER,        -- main document (BiDi)
    blocked                         INTEGER,        -- block page detected (heuristic, page.detect_block)
    block_reason                    TEXT,
    cookiewall_suspected            INTEGER,        -- automatic mode: HEURISTIC (cookiewall.py), checked against w in Phase 8
    cookiewall_reason               TEXT,
    banner_shown                    INTEGER,        -- NULL = not asked (automatic)
    banner_reloads                  INTEGER,        -- reloads until the banner appeared (at most 3)
    useractioncomplete_received     INTEGER,        -- 0 = marker "no useractioncomplete"; NULL = automatic
    useractioncomplete_wait_s       REAL,
    remove_listener_json            TEXT,
    UNIQUE (examination_id, kind, number)
);

-- Time series of channel 1: every message of the preload script, in order.
CREATE TABLE tcf_event (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES session(id),
    seq                 INTEGER NOT NULL,
    kind                TEXT NOT NULL CHECK (kind IN ('injected', 'registering', 'no_tcfapi', 'event')),
    document_url        TEXT,
    page_time_ms        INTEGER,
    at                  TEXT,               -- browser clock
    received_at         TEXT,               -- Python clock
    event_status        TEXT,
    listener_id         INTEGER,
    success             INTEGER,
    empty_tc_data       INTEGER,            -- marker: the CMP called back with an empty object
    cmp_id              INTEGER,
    cmp_status          TEXT,
    gdpr_applies        INTEGER,
    tcf_policy_version  INTEGER,
    tc_string_id        TEXT REFERENCES tc_string(id),
    UNIQUE (session_id, seq)
);

-- State of all channels in one phase.
CREATE TABLE snapshot (
    id                          TEXT PRIMARY KEY,
    session_id                  TEXT NOT NULL REFERENCES session(id),
    phase                       TEXT NOT NULL CHECK (phase IN ('before', 'after_reject', 'after_reject_reload',
                                                               'after_accept', 'after_accept_reload')),
    taken_at                    TEXT NOT NULL,
    page_url                    TEXT,
    request_count               INTEGER,        -- all requests since the previous snapshot
    third_party_request_count   INTEGER,
    UNIQUE (session_id, phase)
);

-- One channel in one snapshot; several rows per snapshot (e.g. one per cookie).
CREATE TABLE observation (
    id              TEXT PRIMARY KEY,
    snapshot_id     TEXT NOT NULL REFERENCES snapshot(id),
    channel         TEXT NOT NULL CHECK (channel IN ('tcfapi', 'third_party_frame', 'cookie', 'local_storage')),
    status          TEXT NOT NULL CHECK (status IN ('measured', 'not_measurable', 'empty_tc_data', 'no_tc_string',
                                                    'no_tcfapi', 'no_answer', 'error')),
    detail          TEXT,                   -- cookie name and domain, localStorage key, iframe URL
    first_party     INTEGER,
    event_status    TEXT,
    tc_string_id    TEXT REFERENCES tc_string(id),
    reason          TEXT
);

-- Every TC string once, keyed by its SHA-256, with decoding and checks (decoder.py).
CREATE TABLE tc_string (
    id                                              TEXT PRIMARY KEY,   -- SHA-256 of the string
    tc_string                                       TEXT NOT NULL UNIQUE,
    tc_version                                      INTEGER,            -- from the string itself; 1 = stored raw only
    decoded                                         INTEGER NOT NULL,
    decode_error                                    TEXT,
    created                                         TEXT,
    last_updated                                    TEXT,
    cmp_id                                          INTEGER,
    cmp_id_replaced_for_decoding                    INTEGER,
    cmp_version                                     INTEGER,
    consent_screen                                  INTEGER,
    consent_language                                TEXT,
    vendor_list_version                             INTEGER,
    policy_version                                  INTEGER,
    is_service_specific                             INTEGER,
    use_non_standard_texts                          INTEGER,
    purpose_one_treatment                           INTEGER,
    publisher_country_code                          TEXT,
    num_custom_purposes                             INTEGER,
    segments                                        TEXT,
    disclosed_vendors_present                       INTEGER,
    publisher_tc_present                            INTEGER,
    policy_version_outdated                         INTEGER,
    disclosed_vendors_missing_after_v23_deadline    INTEGER,
    gvl_version_used                                INTEGER,
    gvl_series                                      TEXT,
    gvl_available                                   INTEGER,
    cmp_valid                                       INTEGER,
    cmp_reason                                      TEXT,
    cmp_name                                        TEXT,
    cmp_list_last_updated                           TEXT,
    decoder_version                                 TEXT,
    decoded_json                                    TEXT,
    checks_json                                     TEXT
);

-- All IDs of a TC string, one row per ID that is set.
CREATE TABLE tc_string_entry (
    tc_string_id    TEXT NOT NULL REFERENCES tc_string(id),
    field           TEXT NOT NULL CHECK (field IN (
                        'purpose_consent', 'purpose_li', 'vendor_consent', 'vendor_li', 'vendor_disclosed',
                        'special_feature', 'publisher_consent', 'publisher_li',
                        'publisher_custom_consent', 'publisher_custom_li')),
    value           INTEGER NOT NULL,
    PRIMARY KEY (tc_string_id, field, value)
);

CREATE TABLE tc_publisher_restriction (
    tc_string_id        TEXT NOT NULL REFERENCES tc_string(id),
    purpose_id          INTEGER NOT NULL,
    restriction_type    INTEGER NOT NULL,   -- 0 not allowed, 1 require consent, 2 require LI
    vendor_id           INTEGER NOT NULL,
    PRIMARY KEY (tc_string_id, purpose_id, restriction_type, vendor_id)
);

-- Requests with consent fields (first and third party); the count of all requests is in snapshot.
CREATE TABLE request (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES session(id),
    until_snapshot_id   TEXT REFERENCES snapshot(id),   -- sent after the previous snapshot, before this one
    time                TEXT,
    url                 TEXT NOT NULL,
    method              TEXT,
    source              TEXT CHECK (source IN ('top', 'iframe', 'worker')),
    context             TEXT,
    third_party         INTEGER NOT NULL,
    registrable_domain  TEXT,
    body_size           INTEGER,
    body_status         TEXT,
    body                TEXT
);

CREATE TABLE request_signal (
    id              TEXT PRIMARY KEY,
    request_id      TEXT NOT NULL REFERENCES request(id),
    location        TEXT NOT NULL CHECK (location IN ('query', 'body_form', 'body_json')),
    key             TEXT NOT NULL,          -- e.g. gdpr_consent or user.ext.consent
    value           TEXT,
    kind            TEXT NOT NULL CHECK (kind IN ('tc_string', 'gdpr_flag', 'addtl_consent', 'macro', 'empty', 'other')),
    tc_string_id    TEXT REFERENCES tc_string(id)
);

CREATE INDEX idx_examination_domain ON examination(domain);
CREATE INDEX idx_session_examination ON session(examination_id);
CREATE INDEX idx_snapshot_session ON snapshot(session_id);
CREATE INDEX idx_observation_snapshot ON observation(snapshot_id);
CREATE INDEX idx_request_session ON request(session_id);
CREATE INDEX idx_request_signal_request ON request_signal(request_id);

-- Nothing is overwritten. Only the closing fields may be set afterwards: finished_at of a run,
-- finished_at/status/cookiewall_* of an examination, the session fields set when it ends.
CREATE TRIGGER run_no_change BEFORE UPDATE OF id, mode, purpose, test_run, operator, hostname, started_at,
    git_commit, git_dirty, metadata_json ON run
    BEGIN SELECT RAISE(ABORT, 'run: only finished_at may be set afterwards'); END;
CREATE TRIGGER examination_no_change BEFORE UPDATE OF id, run_id, domain, operator, role, crosscheck_of,
    correction_of, url, started_at ON examination
    BEGIN SELECT RAISE(ABORT, 'examination: insert a new examination (e.g. role = correction) instead'); END;
CREATE TRIGGER session_no_change BEFORE UPDATE OF id, examination_id, kind, number, url, started_at ON session
    BEGIN SELECT RAISE(ABORT, 'session: only the closing fields may be set afterwards'); END;
CREATE TRIGGER label_no_update BEFORE UPDATE ON label
    BEGIN SELECT RAISE(ABORT, 'label: insert a new examination with role = correction instead'); END;
-- No row is ever deleted.
CREATE TRIGGER run_no_delete BEFORE DELETE ON run BEGIN SELECT RAISE(ABORT, 'run: rows are never deleted'); END;
CREATE TRIGGER website_no_delete BEFORE DELETE ON website BEGIN SELECT RAISE(ABORT, 'website: rows are never deleted'); END;
CREATE TRIGGER prefilter_result_no_delete BEFORE DELETE ON prefilter_result BEGIN SELECT RAISE(ABORT, 'prefilter_result: rows are never deleted'); END;
CREATE TRIGGER examination_no_delete BEFORE DELETE ON examination BEGIN SELECT RAISE(ABORT, 'examination: rows are never deleted'); END;
CREATE TRIGGER label_no_delete BEFORE DELETE ON label BEGIN SELECT RAISE(ABORT, 'label: rows are never deleted'); END;
CREATE TRIGGER session_no_delete BEFORE DELETE ON session BEGIN SELECT RAISE(ABORT, 'session: rows are never deleted'); END;
CREATE TRIGGER tcf_event_no_delete BEFORE DELETE ON tcf_event BEGIN SELECT RAISE(ABORT, 'tcf_event: rows are never deleted'); END;
CREATE TRIGGER snapshot_no_delete BEFORE DELETE ON snapshot BEGIN SELECT RAISE(ABORT, 'snapshot: rows are never deleted'); END;
CREATE TRIGGER observation_no_delete BEFORE DELETE ON observation BEGIN SELECT RAISE(ABORT, 'observation: rows are never deleted'); END;
CREATE TRIGGER tc_string_no_delete BEFORE DELETE ON tc_string BEGIN SELECT RAISE(ABORT, 'tc_string: rows are never deleted'); END;
CREATE TRIGGER tc_string_entry_no_delete BEFORE DELETE ON tc_string_entry BEGIN SELECT RAISE(ABORT, 'tc_string_entry: rows are never deleted'); END;
CREATE TRIGGER tc_publisher_restriction_no_delete BEFORE DELETE ON tc_publisher_restriction BEGIN SELECT RAISE(ABORT, 'tc_publisher_restriction: rows are never deleted'); END;
CREATE TRIGGER request_no_delete BEFORE DELETE ON request BEGIN SELECT RAISE(ABORT, 'request: rows are never deleted'); END;
CREATE TRIGGER request_signal_no_delete BEFORE DELETE ON request_signal BEGIN SELECT RAISE(ABORT, 'request_signal: rows are never deleted'); END;

-- Schema version 1 -> 2: table screenshot (Phase 7). Only adds, changes no row.
-- Screenshots of the banner in the semi-automatic mode: before the action and after closing.
-- The files lie in the run directory (data/semi-automatic-<purpose>-<time>/screenshots/).
CREATE TABLE screenshot (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES session(id),
    moment          TEXT NOT NULL CHECK (moment IN ('before_action', 'after_closing')),
    path            TEXT NOT NULL,
    taken_at        TEXT NOT NULL
);
CREATE TRIGGER screenshot_no_delete BEFORE DELETE ON screenshot BEGIN SELECT RAISE(ABORT, 'screenshot: rows are never deleted'); END;

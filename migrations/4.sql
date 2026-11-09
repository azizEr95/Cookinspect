-- Schema version 3 -> 4: run_part (one row per resumption of an interrupted run, E9).
-- Only adds a table, changes no row.
CREATE TABLE run_part (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES run(id),
    started_at      TEXT NOT NULL,
    metadata_json   TEXT NOT NULL
);
CREATE TRIGGER run_part_no_update BEFORE UPDATE ON run_part BEGIN SELECT RAISE(ABORT, 'run_part: rows are never changed'); END;
CREATE TRIGGER run_part_no_delete BEFORE DELETE ON run_part BEGIN SELECT RAISE(ABORT, 'run_part: rows are never deleted'); END;

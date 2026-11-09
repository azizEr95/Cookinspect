"""Resuming an interrupted run of the prefilter or the automatic mode (docs/entscheidungen.md, E9).

    venv/bin/python run_list.py prefilter --resume data/prefilter-vorab-<time>
    venv/bin/python run_list.py automatic --resume data/automatic-vorab-<time>

The same run goes on: same run ID, same run directory, same database. List, purpose and limit
come from run_metadata.json of the run. A site that was interrupted halfway is measured again
from the start; its unfinished rows stay in the database without status and are not evaluated.

Resuming is refused when the Git commit, Chrome, chromedriver or the configuration differ from
the start of the run, because the metadata of the run must describe all of its parts. The checks
of every run (user, clean Git state, machine, IP country) apply as well. Each resumption is
stored in the table run_part and under "parts" in run_metadata.json.
"""
import json
from pathlib import Path

import config
import database
from run_metadata import new_metadata, write_metadata

# must be the same in all parts of a run
SAME_IN_ALL_PARTS = {
    "git commit": lambda m: m["git"]["commit"],
    "Chrome": lambda m: m["browser"]["browser_version"],
    "chromedriver": lambda m: m["browser"]["chromedriver_version"],
    "configuration": lambda m: m["config"],
}


def differences(original, current):
    return [name for name, value in SAME_IN_ALL_PARTS.items() if value(original) != value(current)]


def read_run_metadata(run_dir, mode):
    path = Path(run_dir) / "run_metadata.json"
    if not path.exists():
        raise SystemExit(f"Cannot resume: {path} does not exist.")
    metadata = json.loads(path.read_text())
    if metadata.get("mode") != mode:
        raise SystemExit(f"Cannot resume: {run_dir} is a run of '{metadata.get('mode')}', not of '{mode}'.")
    if "run_id" not in metadata:
        raise SystemExit(f"Cannot resume: {path} has no run_id (the run was started before resuming existed).")
    return metadata


def resume_run(mode, run_dir, **extra):
    """Checks that the run can be resumed and records the new part. Returns the metadata of the
    run (with all parts), the open database connection and the run ID."""
    run_dir = Path(run_dir)
    original = read_run_metadata(run_dir, mode)
    conn = database.connect(config.database_path(original["purpose"]))
    run, reason = database.unfinished_run(conn, original["run_id"])
    if run is None:
        raise SystemExit(f"Cannot resume: {reason}.")
    current = new_metadata(mode, original["test_run"], purpose=original["purpose"],
                           website_list=original["website_list"], resumes_run=original["run_id"], **extra)
    changed = differences(original, current)
    if changed and not original["test_run"]:
        raise SystemExit(f"Cannot resume: {', '.join(changed)} differ from the start of the run. Start a new run.")
    for name in changed:
        print(f"Warning (test run): {name} differs from the start of the run.")
    database.insert_run_part(conn, original["run_id"], current)
    original.setdefault("parts", []).append(current)
    write_metadata(original, run_dir)
    return original, conn, original["run_id"]


def print_interrupted(mode, run_dir, done, total):
    print(f"\nInterrupted: {done} of {total} done. The site that was running is measured again when resuming."
          f"\nResume with:\n    caffeinate -dims venv/bin/python run_list.py {mode} --resume {run_dir}")

"""Runs cookinspect.py on every domain of a list, one fresh process per domain (replaces run.sh,
which needed GNU ps). Output goes to the terminal and to log.txt in a new run directory under
data/, next to run_metadata.json.

    venv/bin/python run_list.py LIST.csv                          # automatic check (default)
    venv/bin/python run_list.py LIST.csv --mode semi-automatic
    venv/bin/python run_list.py LIST.csv --mode test-cmp --limit 10

LIST.csv is either a CSV with a "domain" column (e.g. rank,domain from the Tranco selection) or a
plain list with one domain per line, without "www." (it is added, as in Cookinspect). If a .json
file with the same name lies next to it (Tranco list ID etc.), it goes into the run metadata.
"""
import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import config
from run_metadata import new_metadata, write_metadata

MODES = {
    "automatic": "--automatic-violations-check",
    "semi-automatic": "--semi-automatic-violations-check",
    "full": "--full-violations-check",
    "test-cmp": "--test-cmp",
}


def read_domains(path):
    with open(path, newline="") as f:
        first_line = f.readline()
        f.seek(0)
        if "domain" in first_line.strip().split(","):
            return [row["domain"].strip() for row in csv.DictReader(f) if row["domain"].strip()]
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def list_info(path):
    """The .json next to the list (e.g. Tranco list ID and its configuration), if there is one."""
    info_path = Path(path).with_suffix(".json")
    return json.loads(info_path.read_text()) if info_path.exists() else None


def run_domain(domain, mode_flag, log):
    """Runs cookinspect.py in its own process group, so that a browser left behind can be killed
    afterwards. The output is passed through unbuffered, so prompts of the semi-automatic mode
    appear at once; the input comes from this terminal."""
    command = [sys.executable, "-u", "cookinspect.py", mode_flag, f"https://www.{domain}"]
    process = subprocess.Popen(command, cwd=config.REPO_DIR, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    while chunk := os.read(process.stdout.fileno(), 1024):
        sys.stdout.buffer.write(chunk)
        sys.stdout.flush()
        log.write(chunk)
        log.flush()
    process.wait()
    try:
        os.killpg(process.pid, signal.SIGKILL)   # leftover Chrome or chromedriver processes
    except ProcessLookupError:
        pass
    return process.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("list", help="CSV with a domain column, or one domain per line")
    parser.add_argument("--mode", choices=MODES, default="automatic")
    parser.add_argument("--limit", type=int, help="only the first N domains (for tests)")
    args = parser.parse_args()

    domains = read_domains(args.list)
    limit = args.limit
    if limit is None and args.mode == "semi-automatic":
        limit = config.SEMI_AUTOMATIC_LIMIT   # None by default: all sites, as Matte did
    if limit is not None:
        domains = domains[:limit]

    run_dir = config.DATA_DIR / f"run-{args.mode}-{datetime.now():%Y-%m-%d--%H-%M-%S}"
    run_dir.mkdir(parents=True)
    metadata = new_metadata(args.mode, website_list={"path": str(args.list), "info": list_info(args.list),
                                                     "domains": len(domains), "limit": limit})
    write_metadata(metadata, run_dir)
    print(f"Run directory: {run_dir}")

    with open(run_dir / "log.txt", "ab") as log:
        for number, domain in enumerate(domains, start=1):
            print(f"\n[{number}/{len(domains)}] {domain}")
            returncode = run_domain(domain, MODES[args.mode], log)
            if returncode != 0:
                print(f"cookinspect.py ended with exit code {returncode} for {domain}")
            time.sleep(config.PAUSE_BETWEEN_DOMAINS)


if __name__ == "__main__":
    main()

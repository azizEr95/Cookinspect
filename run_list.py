"""One entry point for the three crawl modes and the evaluation; each crawl mode visits all
sites of the list itself, with a fresh browser per session. The old cookinspect.py (one process per domain) is no longer needed.

    venv/bin/python run_list.py prefilter LIST.csv --purpose vorab
    venv/bin/python run_list.py automatic data/prefilter-vorab-<time>/tcf_sites.csv --purpose vorab
    venv/bin/python run_list.py semi-automatic data/prefilter-messung-<time>/site_assignment.csv --operator ae --purpose messung
    venv/bin/python run_list.py crosscheck select --operators ae,xy --purpose messung
    venv/bin/python run_list.py evaluate --purpose messung

All further arguments go to the mode (see prefilter.py, automatic.py, semi_automatic.py,
crosscheck.py, evaluate.py), e.g.
--test, --limit N. Without --test a run is a real crawl and is refused unless the setup is
right (run_metadata.check_environment and check_setup).

The helpers read_domains and list_info are used by the modes as well.
"""
import csv
import importlib
import json
import sys
from pathlib import Path

MODES = {"prefilter": "prefilter", "automatic": "automatic", "semi-automatic": "semi_automatic",
         "evaluate": "evaluate", "crosscheck": "crosscheck"}


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


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in MODES:
        raise SystemExit(__doc__ + f"\nModes: {', '.join(MODES)}")
    module = importlib.import_module(MODES[sys.argv[1]])
    sys.argv = [f"{MODES[sys.argv[1]]}.py", *sys.argv[2:]]
    module.main()


if __name__ == "__main__":
    main()

"""Splits the TCF sites of the prefilter measurement run between the two persons: who examines
which site first (semi-automatic mode). The crosscheck (Matte V-C) is then done by the other one.

    venv/bin/python split_sites.py data/prefilter-messung-<time>/tcf_sites.csv ae xy

Rule, reproducible without randomness: within each CMP (cmp_id of the prefilter), the sites are
sorted by Tranco rank and assigned in turn. So both persons see every CMP, and the top sites
are spread evenly. Writes site_assignment.csv next to tcf_sites.csv, and site_assignment.json
with the SHA-256 of the input, the persons and the rule. Both files go to the second person
together with tcf_sites.csv (docs/crawl-nutzer.md).
"""
import csv
import hashlib
import json
import sys
from collections import Counter
from itertools import groupby
from pathlib import Path


def split(sites, operators):
    """sites: rows with rank, domain, url, cmp_id. Returns the rows with first_operator."""
    def cmp_key(site):
        return int(site["cmp_id"]) if site.get("cmp_id") else -1

    ordered = sorted(sites, key=lambda s: (cmp_key(s), int(s["rank"])))
    assigned = []
    turn = 0
    for _, group in groupby(ordered, key=cmp_key):
        for site in group:
            assigned.append({**site, "first_operator": operators[turn % len(operators)]})
            turn += 1
    return sorted(assigned, key=lambda s: int(s["rank"]))


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    path, operators = Path(sys.argv[1]), sys.argv[2:]
    sites = list(csv.DictReader(open(path, newline="")))
    assigned = split(sites, operators)
    out = path.with_name("site_assignment.csv")
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "domain", "url", "cmp_id", "first_operator"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(assigned)
    info = {"source": str(path), "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "operators": operators, "rule": "per CMP, by Tranco rank, in turn",
            "sites_per_operator": dict(Counter(s["first_operator"] for s in assigned))}
    out.with_suffix(".json").write_text(json.dumps(info, indent=2))
    print(f"{out}: {info['sites_per_operator']}")


if __name__ == "__main__":
    main()

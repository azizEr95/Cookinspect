"""Blind crosscheck after Matte et al. (2020), Section V-C (CLAUDE.md, Gegenprüfung).

select: separately for V4 (choice not respected, strict) and V2 (no way to reject): for each CMP
with at least one violating site, one violating site (chosen at random) and as many sites
without the violation, from the same CMP if there are any, otherwise from the other CMPs. The
other person checks them blind. Written are one CSV per person (domain, url, examination_id,
cmp_id: nothing about the first result) and selection.json with the key (which site was chosen
for which violation), which the checking person must not open.

evaluate: compares each crosscheck with the first examination (V2 and V4). On a difference the
milder result counts (site_data.py does that in every evaluation) and all sites of that CMP are
rechecked: recheck.csv for semi_automatic.py --role recheck.

    venv/bin/python crosscheck.py select --operators ae,xy --purpose messung
    venv/bin/python semi_automatic.py data/crosscheck-select-messung-<time>/crosscheck-xy.csv --operator xy --role crosscheck --purpose messung
    venv/bin/python crosscheck.py evaluate --purpose messung
"""
import argparse
import csv
import json
import random
import time
from collections import defaultdict

import config
import database
import site_data
import violations as v

SEED = 2020
KINDS = {"V4": lambda semi: v.v4(semi, "strict"), "V2": lambda semi: v.v2(semi["label"])}


def candidates(sites, kind):
    """{cmp_id: (violating, without violation)} among the first examinations (no crosscheck yet)."""
    groups = defaultdict(lambda: ([], []))
    for site in sites.values():
        if site["semi"] is None or site["source"] != "primary" or site["crosscheck"]:
            continue
        value = KINDS[kind](site["semi"])["value"]
        if value == v.YES:
            groups[site["cmp_id"]][0].append(site)
        elif value == v.NO:
            groups[site["cmp_id"]][1].append(site)
    return groups


def select(sites, rng):
    """[(site, kind, "Verstoß" | "unauffällig")], per kind as Matte V-C."""
    chosen = []
    for kind in KINDS:
        groups = candidates(sites, kind)
        for cmp_id in sorted(groups, key=lambda c: (c is None, c or 0)):
            violating, clean = groups[cmp_id]
            if not violating:
                continue
            chosen.append((rng.choice(sorted(violating, key=lambda s: s["domain"])), kind, "Verstoß"))
            pool = clean or [s for other, (_, c) in groups.items() if other != cmp_id for s in c]
            taken = {s["domain"] for s, k, _ in chosen if k == kind}
            pool = sorted((s for s in pool if s["domain"] not in taken), key=lambda s: s["domain"])
            if pool:
                chosen.append((rng.choice(pool), kind, "unauffällig"))
    return chosen


def other_operator(operator, operators):
    others = [o for o in operators if o != operator]
    if not others:
        raise SystemExit(f"no second person for the sites of {operator}: --operators {','.join(operators)}")
    return others[0]


def write_csv(path, rows, columns):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def command_select(args, sites, out_dir):
    operators = args.operators.split(",")
    rng = random.Random(args.seed)
    chosen = select(sites, rng)
    per_operator, key = defaultdict(dict), []
    for site, kind, selected_as in chosen:
        examination = site["semi"]
        checker = other_operator(examination["operator"], operators)
        per_operator[checker][examination["id"]] = {
            "domain": site["domain"], "url": examination["url"], "examination_id": examination["id"],
            "cmp_id": site["cmp_id"]}
        key.append({"domain": site["domain"], "cmp_id": site["cmp_id"], "kind": kind, "selected_as": selected_as,
                    "first_operator": examination["operator"], "checked_by": checker})
    for checker, rows in per_operator.items():
        write_csv(out_dir / f"crosscheck-{checker}.csv", list(rows.values()), ["domain", "url", "examination_id", "cmp_id"])
    (out_dir / "selection.json").write_text(json.dumps(
        {"created": database.now(), "seed": args.seed, "operators": operators, "selection": key},
        indent=2, ensure_ascii=False))
    for checker, rows in per_operator.items():
        print(f"{out_dir / f'crosscheck-{checker}.csv'}: {len(rows)} Seiten für {checker}")
    print(f"{out_dir / 'selection.json'}: Schlüssel (nicht der prüfenden Person zeigen)")


def compare(site):
    """V2 and V4 of the first examination and of the crosscheck."""
    info = site["crosscheck"]
    first, second = info["primary"], info["crosscheck"]
    return {"domain": site["domain"], "cmp_id": site["cmp_id"],
            "first_operator": info["primary_operator"], "crosscheck_operator": info["crosscheck_operator"],
            "v2_first": v.v2(first["label"])["value"], "v2_crosscheck": v.v2(second["label"])["value"],
            "v4_first": v.v4(first, "strict")["value"], "v4_crosscheck": v.v4(second, "strict")["value"],
            "differs": info["differs"], "counts": site["source"]}


def command_evaluate(sites, out_dir):
    compared = [compare(site) for site in sites.values() if site["crosscheck"]]
    columns = ["domain", "cmp_id", "first_operator", "crosscheck_operator", "v2_first", "v2_crosscheck",
               "v4_first", "v4_crosscheck", "differs", "counts"]
    write_csv(out_dir / "comparison.csv", compared, columns)
    cmps = {row["cmp_id"] for row in compared if row["differs"]}
    recheck = [{"domain": site["domain"], "url": site["semi"]["url"], "cmp_id": site["cmp_id"],
                "first_operator": site["semi"]["operator"]}
               for site in sites.values() if site["semi"] and site["cmp_id"] in cmps]
    write_csv(out_dir / "recheck.csv", recheck, ["domain", "url", "cmp_id", "first_operator"])
    print(f"{len(compared)} Gegenprüfungen, {sum(1 for r in compared if r['differs'])} mit Abweichung")
    for row in compared:
        print(f"  {row['domain']} (CMP {row['cmp_id']}): V2 {row['v2_first']} / {row['v2_crosscheck']}, "
              f"V4 {row['v4_first']} / {row['v4_crosscheck']}" + (f" → abweichend, zählt: {row['counts']}" if row["differs"] else ""))
    print(f"{out_dir / 'recheck.csv'}: {len(recheck)} Seiten neu prüfen (CMPs {sorted(cmps, key=str)})")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["select", "evaluate"])
    parser.add_argument("--operators", help="select: the two short codes, e.g. ae,xy")
    parser.add_argument("--seed", type=int, default=SEED, help=f"select: seed of the random choice (default {SEED})")
    parser.add_argument("--test", action="store_true", help="data/test.sqlite")
    parser.add_argument("--purpose", choices=["vorab", "messung"])
    args = parser.parse_args()
    if args.test == bool(args.purpose):
        parser.error("give either --test or --purpose vorab|messung")
    if args.command == "select" and not args.operators:
        parser.error("select needs --operators, e.g. ae,xy")
    purpose = args.purpose or "test"
    conn = database.connect(config.database_path(purpose))
    sites = site_data.load_sites(conn, v.severity, purpose)
    out_dir = config.DATA_DIR / f"crosscheck-{args.command}-{purpose}-{time.strftime('%Y-%m-%d--%H-%M-%S')}"
    out_dir.mkdir(parents=True)
    if args.command == "select":
        command_select(args, sites, out_dir)
    else:
        command_evaluate(sites, out_dir)


if __name__ == "__main__":
    main()

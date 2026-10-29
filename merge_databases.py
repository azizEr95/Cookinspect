"""Merges the databases of both persons (each works on their own Mac) into one file.

    venv/bin/python merge_databases.py data/merged.sqlite ae.sqlite xy.sqlite

Rows are only added, never changed: measurement rows have UUIDs, websites are keyed by domain,
TC strings by their SHA-256. A row whose key is already in the target is kept as it is there.
Merging the same file twice adds nothing. If such a row differs from the one in the target (e.g.
the CMP check of a TC string against another CMP list snapshot), the script reports it.
"""
import sys

from database import connect

# parents before children, so that the foreign keys hold
TABLES = ["run", "website", "prefilter_result", "examination", "label", "session", "tc_string", "tc_string_entry",
          "tc_publisher_restriction", "tcf_event", "snapshot", "observation", "request", "request_signal"]


def schema_version(conn, schema):
    return conn.execute(f"SELECT version FROM {schema}.schema_info").fetchone()[0]


def merge(target_path, source_path):
    conn = connect(target_path)
    conn.execute("ATTACH DATABASE ? AS source", (str(source_path),))
    if schema_version(conn, "source") != schema_version(conn, "main"):
        raise SystemExit(f"{source_path}: schema version differs from {target_path}")
    report = {}
    with conn:
        for table in TABLES:
            columns = ", ".join(row["name"] for row in conn.execute(f"PRAGMA main.table_info({table})"))
            before = conn.execute(f"SELECT count(*) FROM main.{table}").fetchone()[0]
            conn.execute(f"INSERT OR IGNORE INTO main.{table} ({columns}) SELECT {columns} FROM source.{table}")
            added = conn.execute(f"SELECT count(*) FROM main.{table}").fetchone()[0] - before
            differing = conn.execute(f"SELECT count(*) FROM (SELECT {columns} FROM source.{table} "
                                     f"EXCEPT SELECT {columns} FROM main.{table})").fetchone()[0]
            report[table] = (added, differing)
    conn.execute("DETACH DATABASE source")
    conn.close()
    return report


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    target, sources = sys.argv[1], sys.argv[2:]
    for source in sources:
        print(f"\n{source} -> {target}")
        for table, (added, differing) in merge(target, source).items():
            note = f", {differing} differ from the row already in the target (kept as in the target)" if differing else ""
            print(f"  {table}: {added} added{note}")


if __name__ == "__main__":
    main()

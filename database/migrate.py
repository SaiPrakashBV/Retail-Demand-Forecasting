"""Apply SQL migrations in database/migrations in version order, exactly once each.

    python database/migrate.py            # apply pending migrations
    python database/migrate.py --check    # exit 1 if any migration is pending (CI)

Each file ``V<number>__<name>.sql`` runs inside its own transaction and is recorded in
``schema_migrations`` with a checksum; editing an applied migration is reported as an error.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
from pathlib import Path

import psycopg2

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
FILE_RE = re.compile(r"^V(\d+)__([\w-]+)\.sql$")


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql://retail:retail@localhost:5432/retail")
    return url.replace("postgresql+psycopg2://", "postgresql://")


def discover() -> list[tuple[int, str, Path]]:
    found = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = FILE_RE.match(path.name)
        if not m:
            raise SystemExit(f"Bad migration file name: {path.name} (expected V<n>__<name>.sql)")
        found.append((int(m.group(1)), m.group(2), path))
    versions = [v for v, _, _ in found]
    if len(set(versions)) != len(versions):
        raise SystemExit("Duplicate migration version numbers")
    return sorted(found)


def connect(retries: int = 30):
    for attempt in range(retries):
        try:
            return psycopg2.connect(database_url())
        except psycopg2.OperationalError:
            if attempt == retries - 1:
                raise
            time.sleep(2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only report pending migrations")
    args = ap.parse_args()

    conn = connect()
    conn.autocommit = False
    with conn, conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        cur.execute("SELECT version, checksum FROM schema_migrations")
        applied = dict(cur.fetchall())

    pending = []
    for version, name, path in discover():
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if version in applied:
            if applied[version] != checksum:
                print(f"ERROR: applied migration V{version} ({path.name}) was modified", file=sys.stderr)
                return 2
            continue
        pending.append((version, name, path, checksum))

    if args.check:
        for _v, _, p, _ in pending:
            print(f"pending: {p.name}")
        return 1 if pending else 0

    for version, name, path, checksum in pending:
        with conn, conn.cursor() as cur:
            cur.execute(path.read_text())
            cur.execute("INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                        (version, name, checksum))
        print(f"applied {path.name}")
    print(f"schema up to date ({len(applied) + len(pending)} migrations)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

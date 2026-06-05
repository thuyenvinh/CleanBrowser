"""One-shot migration: copy data from legacy SQLite into PostgreSQL.

Run inside the manager container (or any environment where ``DATABASE_URL``
points at the new Postgres instance) AFTER ``alembic upgrade head``:

    DATABASE_URL=postgresql://... python -m backend.migrate_sqlite_to_postgres \
        [--sqlite-path /data/profiles.db]

The script is idempotent: rows whose ``id`` already exists in Postgres are
skipped. Reports row counts at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

DEFAULT_SQLITE = Path("/data/profiles.db")


PROFILE_COLS = [
    "id", "name", "fingerprint_seed", "proxy", "timezone", "locale", "platform",
    "user_agent", "screen_width", "screen_height", "gpu_vendor", "gpu_renderer",
    "hardware_concurrency", "humanize", "human_preset", "headless", "geoip",
    "clipboard_sync", "auto_launch", "color_scheme", "launch_args", "notes",
    "user_data_dir", "created_at", "updated_at",
]


def _coerce_bool(v):
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "t", "yes", "y"}
    return bool(v)


BOOL_COLS = {"humanize", "headless", "geoip", "clipboard_sync", "auto_launch"}


def migrate(sqlite_path: Path, pg_dsn: str) -> tuple[int, int]:
    if not sqlite_path.exists():
        print(f"[migrate] No SQLite database at {sqlite_path}; nothing to do.")
        return (0, 0)

    sconn = sqlite3.connect(str(sqlite_path))
    sconn.row_factory = sqlite3.Row

    pconn = psycopg2.connect(pg_dsn)
    pconn.autocommit = False

    profiles_migrated = 0
    tags_migrated = 0

    try:
        try:
            srows = sconn.execute("SELECT * FROM profiles").fetchall()
        except sqlite3.OperationalError as e:
            print(f"[migrate] SQLite read failed: {e}")
            return (0, 0)

        with pconn.cursor() as pcur:
            for row in srows:
                row_dict = dict(row)
                pid = row_dict["id"]

                pcur.execute("SELECT 1 FROM profiles WHERE id = %s", (pid,))
                if pcur.fetchone() is not None:
                    print(f"[migrate] skip existing profile {pid}")
                    continue

                # Normalize launch_args TEXT-JSON → list for JSONB cast.
                la_raw = row_dict.get("launch_args") or "[]"
                try:
                    la_list = json.loads(la_raw) if isinstance(la_raw, str) else (la_raw or [])
                except json.JSONDecodeError:
                    la_list = []

                # Normalize booleans (SQLite stores them as 0/1 INTEGER).
                values = []
                for col in PROFILE_COLS:
                    v = row_dict.get(col)
                    if col == "launch_args":
                        values.append(json.dumps(la_list))
                    elif col in BOOL_COLS:
                        values.append(_coerce_bool(v))
                    else:
                        values.append(v)

                placeholders = ", ".join(
                    "%s::jsonb" if c == "launch_args" else "%s" for c in PROFILE_COLS
                )
                pcur.execute(
                    f"INSERT INTO profiles ({', '.join(PROFILE_COLS)}) VALUES ({placeholders})",
                    values,
                )
                profiles_migrated += 1

                # Tags
                try:
                    trows = sconn.execute(
                        "SELECT tag, color FROM profile_tags WHERE profile_id = ?",
                        (pid,),
                    ).fetchall()
                except sqlite3.OperationalError:
                    trows = []
                for trow in trows:
                    pcur.execute(
                        "INSERT INTO profile_tags (profile_id, tag, color) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (pid, trow["tag"], trow["color"]),
                    )
                    tags_migrated += 1

        pconn.commit()
    except Exception:
        pconn.rollback()
        raise
    finally:
        sconn.close()
        pconn.close()

    return (profiles_migrated, tags_migrated)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=DEFAULT_SQLITE,
        help=f"Path to the legacy SQLite DB (default: {DEFAULT_SQLITE})",
    )
    args = parser.parse_args(argv)

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        return 2

    profiles, tags = migrate(args.sqlite_path, dsn)
    print(f"[migrate] migrated {profiles} profile(s), {tags} tag(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

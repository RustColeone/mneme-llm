"""A memory file of an earlier schema made current, by hand, once: `python -m mneme_llm.migrate FILE...`.

    python -m mneme_llm.migrate companion.db

Back the file up and stop whatever uses it first. Each file changes in one transaction, whole or not at all, and one
that is current already is left as it is, so running this twice is safe. It says what it did to each file.

From schema 1 to 2: every exchange gets its talking day (in the zone of its space's config, the machine's where that
gives none) and its tokens; a surface's `since` becomes the last exchange said before it; what nothing reads any more
goes (the word centroids, `vectors.taught`, `memories.terms`, `people.updated_at`, `episodes.terms`), and so do config
keys no version knows; the term indexes are rebuilt the first time they are searched.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import tzinfo
from pathlib import Path

from . import dates, text as texts
from .config import known, zone_of
from .episodes import cost
from .store import SCHEMA_VERSION, create

RESHAPED = ("memories", "vectors", "people", "episodes", "surfaces")  # in schema 2
GONE = ("micro_models", "meaning_terms")


def _has(db: sqlite3.Connection, table: str) -> bool:
    return db.execute("select 1 from sqlite_master where type = 'table' and name = ?", (table,)).fetchone() is not None


def _version(db: sqlite3.Connection) -> int | None:
    if not _has(db, "meta"):
        return None
    row = db.execute("select value from meta where key = 'schema_version'").fetchone()
    return int(row["value"]) if row else None


def _zones(db: sqlite3.Connection) -> dict[str, tzinfo | None]:
    """Each space's zone, as its config gives it; one that cannot be read counts as none."""
    zones: dict[str, tzinfo | None] = {}
    if _has(db, "config"):
        for row in db.execute("select space, value from config where key = 'companion.zone'").fetchall():
            try:
                zones[row["space"]] = zone_of(json.loads(row["value"]))
            except (TypeError, ValueError):
                pass
    return zones


def _copy(db: sqlite3.Connection, table: str, **filled: str) -> None:
    """A table's rows back from `old_<table>`, by the columns both have; `filled` gives SQL for a new column."""
    had = {row["name"] for row in db.execute(f"pragma table_info(old_{table})")}
    columns = [row["name"] for row in db.execute(f"pragma table_info({table})") if row["name"] in had | set(filled)]
    values = ", ".join(filled.get(column, column) for column in columns)
    db.execute(f"insert into {table} ({', '.join(columns)}) select {values} from old_{table}")


def _to_2(db: sqlite3.Connection) -> str:
    """Schema 1 to 2, inside the caller's transaction; what it did, in words."""
    moved = [table for table in RESHAPED if _has(db, table)]
    gone = [table for table in GONE if _has(db, table)]
    for table in moved:
        db.execute(f"alter table {table} rename to old_{table}")
        for row in db.execute("select name from sqlite_master where type = 'index' and tbl_name = ? and sql is not "
                              "null", (f"old_{table}",)).fetchall():
            db.execute(f"drop index {row['name']}")
    for table in gone:
        db.execute(f"drop table {table}")
    create(db)

    exchanges = surfaces = 0
    if "memories" in moved:
        _copy(db, "memories", folded="''")
        for row in db.execute("select id, text from memories").fetchall():
            db.execute("update memories set folded = ? where id = ?", (texts.fold(row["text"]), row["id"]))
    for table in ("vectors", "people"):
        if table in moved:
            _copy(db, table)
    if "episodes" in moved:
        _copy(db, "episodes", day="0", tokens="0")
        zones = _zones(db)
        for row in db.execute("select id, space, at, lines from episodes").fetchall():
            db.execute("update episodes set day = ?, tokens = ? where id = ?",
                       (dates.talking_day(row["at"], zones.get(row["space"])), cost(json.loads(row["lines"])),
                        row["id"]))
            exchanges += 1
    if "surfaces" in moved:
        for row in db.execute("select * from old_surfaces").fetchall():
            start = db.execute("select coalesce(max(id), 0) as id from episodes where space = ? and subject = ? and at "
                               "< ?", (row["space"], row["subject"], row["since"])).fetchone()["id"]
            db.execute("insert into surfaces (space, subject, start_id, cleared_at, summary) values (?, ?, ?, ?, ?)",
                       (row["space"], row["subject"], start, row["since"], row["summary"]))
            surfaces += 1
    for table in moved:
        db.execute(f"drop table old_{table}")

    stale = [(row["space"], row["key"]) for row in db.execute("select space, key from config").fetchall()
             if not known(row["key"])]
    for space, key in stale:
        db.execute("delete from config where space = ? and key = ?", (space, key))
    db.execute("delete from meta where key in ('terms_indexed', 'terms_version') or key like 'meaning_texts:%' or key "
               "like 'meaning_version:%'")
    dropped = f", dropped {' and '.join(gone)}" if gone else ""
    return (f"{exchanges} exchanges got their day and tokens, {surfaces} surfaces start at an exchange now, "
            f"{len(stale)} old config keys removed{dropped}; search indexes are rebuilt at the first search")


def migrate(path: str | Path) -> str:
    """One file made current, in one transaction; what was done to it, in words."""
    if not Path(path).is_file():
        raise FileNotFoundError(f"{path}: no such file")
    db = sqlite3.connect(str(path), isolation_level=None, timeout=10.0)
    db.row_factory = sqlite3.Row
    try:
        db.execute("begin immediate")
        try:
            found = _version(db)
            if found == SCHEMA_VERSION:
                db.execute("rollback")
                return f"{path}: schema {found} already, nothing to do"
            if found != 1:
                raise ValueError(f"{path}: not a schema 1 file (schema {found})")
            done = _to_2(db)
            db.execute("update meta set value = ? where key = 'schema_version'", (str(SCHEMA_VERSION),))
            db.execute("commit")
        except BaseException:
            if db.in_transaction:
                db.execute("rollback")
            raise
    finally:
        db.close()
    return f"{path}: schema {found} to {SCHEMA_VERSION}: {done}"


def main(argv: list[str] | None = None) -> int:
    paths = sys.argv[1:] if argv is None else argv
    if not paths:
        print("usage: python -m mneme_llm.migrate FILE...", file=sys.stderr)
        return 2
    failed = 0
    for path in paths:
        try:
            print(migrate(path))
        except (OSError, ValueError, sqlite3.Error) as error:
            print(f"{path}: {error}" if str(path) not in str(error) else error, file=sys.stderr)
            failed = 1
    return failed


if __name__ == "__main__":
    sys.exit(main())

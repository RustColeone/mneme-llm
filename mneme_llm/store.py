"""The database: one SQLite file holding everything mneme-llm keeps, versioned so later releases can migrate it.

Every row belongs to a `space` (whose memory it is: an app or a character, "whale_chan") and most to a `subject`
(who it is about: "discord:1234"). Nothing here knows about models; the file can move between projects.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
SCHEMA = """
create table if not exists meta (key text primary key, value text not null);
create table if not exists memories (
    id integer primary key,
    space text not null,
    subject text not null,
    key text,
    kind text not null,
    text text not null,
    importance integer not null,
    feeling real not null default 0,
    happened_at real not null,
    created_at real not null,
    recalled_at real,
    recalls integer not null default 0,
    superseded_by integer,
    deleted_at real,
    source text,
    gloss text,
    terms text
);
create index if not exists memories_live on memories(space, subject, deleted_at, superseded_by);
create index if not exists memories_key on memories(space, subject, key);
create table if not exists recalls (
    id integer primary key, space text not null, subject text not null, at real not null, query text not null,
    chosen text not null, skipped text not null
);
create index if not exists recalls_subject on recalls(space, subject, at);
create table if not exists profiles (
    space text not null, subject text not null, text text not null, updated_at real not null,
    primary key (space, subject)
);
create table if not exists moods (
    space text not null, subject text not null, value real not null, emotions text not null,
    updated_at real not null, last_event integer, told_event integer,
    primary key (space, subject)
);
create table if not exists mood_events (
    id integer primary key, space text not null, subject text not null, at real not null, delta real not null,
    value real not null, emotions text not null, reason text not null, confidence real not null,
    source text not null, judge text not null
);
create index if not exists mood_events_subject on mood_events(space, subject, at);
create table if not exists micro_models (
    question text primary key, kind text not null, labels text not null, weights text not null,
    examples integer not null, updated_at real not null
);
create table if not exists vectors (
    memory_id integer not null, embedder text not null, vector blob not null,
    primary key (memory_id, embedder)
);
create table if not exists meaning_terms (
    embedder text not null, term text not null, count integer not null, vector blob not null,
    primary key (embedder, term)
);
"""
# Columns added after a table first shipped, so files made by earlier builds gain them on open.
ADDED_COLUMNS = {"memories": {"gloss": "text", "terms": "text"}}


MEMORY_COLUMNS = ("subject", "key", "kind", "text", "importance", "feeling", "happened_at", "created_at",
                  "recalled_at", "recalls", "deleted_at", "source", "gloss")


class Store:
    """A thread-safe connection to one mneme-llm file (created on first use)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            if str(path) != ":memory:":
                self._db.execute("pragma journal_mode=wal")
            self._db.executescript(SCHEMA)
            for table, columns in ADDED_COLUMNS.items():
                have = {row["name"] for row in self._db.execute(f"pragma table_info({table})")}
                for name, kind in columns.items():
                    if name not in have:
                        self._db.execute(f"alter table {table} add column {name} {kind}")
            found = self.meta("schema_version")
            if found is None:
                self.set_meta("schema_version", str(SCHEMA_VERSION))
            elif int(found) > SCHEMA_VERSION:
                raise RuntimeError(f"{path} was written by a newer mneme-llm (schema {found}); upgrade mneme-llm to read it")

    def close(self) -> None:
        self._db.close()

    def __del__(self) -> None:
        try:
            self._db.close()
        except Exception:
            pass

    # ---- plain access (the modules above use these, never the connection itself) ---------------
    def execute(self, sql: str, parameters: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, tuple(parameters))

    def rows(self, sql: str, parameters: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, tuple(parameters)).fetchall()

    def row(self, sql: str, parameters: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute(sql, tuple(parameters)).fetchone()

    def transaction(self):
        """`with store.transaction():` several writes that land together or not at all."""
        return _Transaction(self)

    def meta(self, key: str) -> str | None:
        found = self.row("select value from meta where key = ?", (key,))
        return found["value"] if found else None

    def set_meta(self, key: str, value: str) -> None:
        self.execute("insert into meta (key, value) values (?, ?) on conflict(key) do update set value = "
                     "excluded.value", (key, value))

    # ---- moving a space between files and projects ----------------------------------------------
    def export_data(self, space: str) -> dict:
        """Everything of one space as plain JSON (memories, profiles, moods and their timelines). Vectors and
        cached search terms are left out: they belong to an embedder and a tokenizer, and are rebuilt on use."""
        def table(name: str) -> list[dict]:
            return [dict(row) for row in self.rows(f"select * from {name} where space = ? order by rowid", (space,))]
        memories = [{key: value for key, value in row.items() if key != "terms"} for row in table("memories")]
        return {"mneme_llm": SCHEMA_VERSION, "space": space, "exported_at": time.time(), "memories": memories,
                "profiles": table("profiles"), "moods": table("moods"), "mood_events": table("mood_events")}

    def import_data(self, data: dict, space: str | None = None) -> int:
        """Add an export (into `space`, or the one it came from); memory ids are renumbered. Returns memories added."""
        target = space or data["space"]
        renumbered, links = {}, []
        with self.transaction():
            for original in data.get("memories", []):
                row = {name: original.get(name) for name in MEMORY_COLUMNS if name in original}
                row.update(space=target, superseded_by=None)
                cursor = self.execute(f"insert into memories ({', '.join(row)}) values ({', '.join('?' * len(row))})",
                                      row.values())
                renumbered[original["id"]] = cursor.lastrowid
                if original.get("superseded_by") is not None:
                    links.append((cursor.lastrowid, original["superseded_by"]))
            for new, old_successor in links:  # links between memories follow the new numbers
                self.execute("update memories set superseded_by = ? where id = ?",
                             (renumbered.get(old_successor, -1), new))
            for row in data.get("profiles", []):
                self.execute("insert or replace into profiles (space, subject, text, updated_at) values (?, ?, ?, ?)",
                             (target, row["subject"], row["text"], row["updated_at"]))
            for row in data.get("moods", []):
                self.execute("insert or replace into moods (space, subject, value, emotions, updated_at, last_event, "
                             "told_event) values (?, ?, ?, ?, ?, null, null)",
                             (target, row["subject"], row["value"], row["emotions"], row["updated_at"]))
            for row in data.get("mood_events", []):
                self.execute("insert into mood_events (space, subject, at, delta, value, emotions, reason, confidence, "
                             "source, judge) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (target, row["subject"], row["at"], row["delta"], row["value"], row["emotions"],
                              row["reason"], row["confidence"], row["source"], row["judge"]))
        return len(renumbered)


class _Transaction:
    def __init__(self, store: Store):
        self.store = store

    def __enter__(self):
        self.store._lock.acquire()
        self.store._db.execute("begin")
        return self.store

    def __exit__(self, kind, value, traceback):
        try:
            self.store._db.execute("commit" if kind is None else "rollback")
        finally:
            self.store._lock.release()
        return False


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

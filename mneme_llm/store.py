"""The database: one SQLite file holding everything mneme-llm keeps, versioned so later releases can migrate it.

Every row belongs to a `space` (whose memory it is: an app or a character, "whale_chan") and most to a `subject`
(who it is about: "discord:1234"). This module is the file alone: its tables, migrations, locking and
transactions. The rules of what goes in them belong to the modules that own each table (memory, mood, meaning,
relations, config).
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
    terms text,
    folded text
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
    memory_id integer not null, embedder text not null, vector blob not null, taught text,
    primary key (memory_id, embedder)
);
create table if not exists meaning_terms (
    embedder text not null, term text not null, count integer not null, vector blob not null,
    primary key (embedder, term)
);
create table if not exists note_terms (
    space text not null, subject text not null, term text not null, memory_id integer not null,
    primary key (space, subject, term, memory_id)
) without rowid;
create index if not exists note_terms_memory on note_terms(memory_id);
create table if not exists config (
    space text not null, key text not null, value text not null, origin text not null, updated_at real not null,
    primary key (space, key)
);
create table if not exists relationships (
    space text not null, subject text not null, role text not null, closeness real not null, since real not null,
    updated_at real not null,
    primary key (space, subject)
);
"""
# Columns added after a table first shipped, so files made by earlier builds gain them on open.
ADDED_COLUMNS = {"memories": {"gloss": "text", "terms": "text", "folded": "text"}, "vectors": {"taught": "text"}}
# Indexes on added columns, made once the columns exist.
ADDED_INDEXES = ("create index if not exists memories_folded on memories(space, subject, folded)",
                 # recall's picks (pinned, important, newest) read a few notes in order, not a whole history
                 "create index if not exists memories_newest on memories(space, subject, id)",
                 "create index if not exists memories_important on memories(space, subject, importance, id)",
                 "create index if not exists vectors_untaught on vectors(embedder) where taught is null")



class Store:
    """A thread-safe connection to one mneme-llm file (created on first use)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # `timeout`: another process holding the write lock is waited for (begin immediate honours it).
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=10.0)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._depth = 0  # open transactions on this connection (nested ones are savepoints)
        with self._lock:
            try:
                self._migrate()
                if str(path) != ":memory:":
                    self._wal()
            except BaseException:
                self._db.close()
                raise

    def _migrate(self) -> None:
        """Make the file current: refuse a newer one before changing anything, create what is missing and add the
        columns of later builds. Under the write lock, so two processes opening one file at once take turns."""
        self._db.execute("begin immediate")
        try:
            found = self._version()
            if found is not None and found > SCHEMA_VERSION:
                raise RuntimeError(f"{self.path} was written by a newer mneme-llm (schema {found}); upgrade "
                                   "mneme-llm to read it")
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    self._db.execute(statement)
            for table, columns in ADDED_COLUMNS.items():
                have = {row["name"] for row in self._db.execute(f"pragma table_info({table})")}
                for name, kind in columns.items():
                    if name not in have:
                        self._db.execute(f"alter table {table} add column {name} {kind}")
            for statement in ADDED_INDEXES:
                self._db.execute(statement)
            if found is None:
                self.set_meta("schema_version", str(SCHEMA_VERSION))
            self._db.execute("commit")
        except BaseException:
            if self._db.in_transaction:  # (SQLite may have rolled it back itself, on a full disk say)
                self._db.execute("rollback")
            raise

    def _wal(self, timeout: float = 10.0) -> None:
        """WAL journaling, so readers don't block the writer. Switching needs the file to itself for a moment;
        another process opening it at the same time is waited for."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                self._db.execute("pragma journal_mode=wal")
                return
            except sqlite3.OperationalError as error:
                if "locked" not in str(error) and "busy" not in str(error) or time.monotonic() > deadline:
                    raise
                time.sleep(0.05)

    def _version(self) -> int | None:
        """The file's schema version, read without changing anything (None for a new or empty file)."""
        if self._db.execute("select 1 from sqlite_master where type = 'table' and name = 'meta'").fetchone() is None:
            return None
        row = self._db.execute("select value from meta where key = 'schema_version'").fetchone()
        return int(row["value"]) if row is not None else None

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
        """`with store.transaction():` several writes that land together or not at all. It takes the write lock up
        front (`begin immediate`), so another process writing the same file is waited for rather than failing
        midway; a transaction inside another is a savepoint of it."""
        return _Transaction(self)

    def meta(self, key: str) -> str | None:
        found = self.row("select value from meta where key = ?", (key,))
        return found["value"] if found else None

    def set_meta(self, key: str, value: str) -> None:
        self.execute("insert into meta (key, value) values (?, ?) on conflict(key) do update set value = "
                     "excluded.value", (key, value))


class _Transaction:
    def __init__(self, store: Store):
        self.store = store
        self.savepoint = ""

    def __enter__(self):
        store = self.store
        store._lock.acquire()
        try:
            if store._depth == 0:
                store._db.execute("begin immediate")
            else:
                self.savepoint = f"inner{store._depth}"
                store._db.execute(f"savepoint {self.savepoint}")
        except BaseException:
            store._lock.release()  # never leave the lock held when the transaction could not start
            raise
        store._depth += 1
        return store

    def __exit__(self, kind, value, traceback):
        store = self.store
        try:
            store._depth -= 1
            # SQLite rolls a transaction back by itself on some errors (a full disk): then there is nothing left
            # to roll back, and trying would hide the error that is on its way out.
            if self.savepoint:
                if store._db.in_transaction:
                    if kind is not None:
                        store._db.execute(f"rollback to {self.savepoint}")
                    store._db.execute(f"release {self.savepoint}")
            elif kind is None:
                try:
                    store._db.execute("commit")
                except BaseException:
                    try:  # a failed commit must not leave the transaction open for every later write
                        store._db.execute("rollback")
                    except sqlite3.Error:
                        pass
                    raise
            elif store._db.in_transaction:
                store._db.execute("rollback")
        finally:
            store._lock.release()
        return False


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

"""The database: one SQLite file holding everything mneme-llm keeps, with the version of its schema.

Every row belongs to a `space` (whose memory it is: an app or a character, "whale_chan") and most to a `subject`
(who it is about: "discord:1234"). This module is the file alone: its tables, locking and transactions. The rules of
what goes in them belong to the modules that own each table (memory, episodes, surface, mood, meaning, relations,
aliases, people, config). A file of an earlier schema is refused here, and made current by `migrate.py`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from . import text as texts

SCHEMA_VERSION = 2
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
    folded text not null
);
create index if not exists memories_live on memories(space, subject, deleted_at, superseded_by);
create index if not exists memories_key on memories(space, subject, key);
create index if not exists memories_folded on memories(space, subject, folded);
create index if not exists memories_newest on memories(space, subject, id);
create index if not exists memories_important on memories(space, subject, importance, id);
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
create table if not exists vectors (
    memory_id integer not null, embedder text not null, vector blob not null,
    primary key (memory_id, embedder)
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
create table if not exists aliases (
    space text not null, subject text not null, alias text not null, updated_at real not null,
    primary key (space, subject)
);
create table if not exists people (
    space text not null, subject text not null, person text not null,
    primary key (space, subject)
);
create index if not exists people_person on people(space, person);
create table if not exists episodes (
    id integer primary key autoincrement,
    space text not null,
    subject text not null,
    at real not null,
    day integer not null,
    conversation text not null default '',
    lines text not null,
    size integer not null,
    tokens real not null,
    stability real not null,
    recalled_at real,
    recalls integer not null default 0
);
create index if not exists episodes_subject on episodes(space, subject, at);
create index if not exists episodes_conversation on episodes(space, subject, conversation, at);
create index if not exists episodes_day on episodes(space, subject, day);
create index if not exists episodes_newest on episodes(space, subject, id);
create table if not exists episode_terms (
    space text not null, subject text not null, term text not null, episode_id integer not null,
    primary key (space, subject, term, episode_id)
) without rowid;
create index if not exists episode_terms_episode on episode_terms(episode_id);
create table if not exists episode_vectors (
    episode_id integer not null, embedder text not null, vector blob not null,
    primary key (episode_id, embedder)
);
create table if not exists surfaces (
    space text not null, subject text not null, start_id integer not null, cleared_at real not null,
    summary text not null,
    primary key (space, subject)
);
create table if not exists first_prompts (
    space text not null, subject text not null, text text not null, at real not null, by_command integer not null,
    send integer not null, primary key (space, subject)
);
create table if not exists episode_spread (
    space text not null, subject text not null, embedder text not null, bins text not null, pairs integer not null,
    primary key (space, subject, embedder)
);
create table if not exists links (
    space text not null, subject text not null, a integer not null, b integer not null, closeness real not null,
    day integer not null, stability real not null, uses integer not null default 0,
    primary key (space, a, b)
) without rowid;
create index if not exists links_b on links(space, b);
create index if not exists links_subject on links(space, subject);
"""
IN_LIST = 400  # values in one `in (...)`: SQLite takes 999 parameters in all on older builds


def create(db: sqlite3.Connection) -> None:
    """Every table and index of the schema that the file does not have yet."""
    for statement in SCHEMA.split(";"):
        if statement.strip():
            db.execute(statement)


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
        self._indexes: dict[str, Callable[[], None]] = {}  # what rebuilds each term index
        with self._lock:
            try:
                self._open()
                if str(path) != ":memory:":
                    self._wal()
            except BaseException:
                self._db.close()
                raise

    def _open(self) -> None:
        """A new file gets the schema, and one of this schema any table added since it was made (`links`: a reader of
        the same schema without them leaves them alone); one of another schema is refused before anything changes.
        Under the write lock, so two processes opening one file at once take turns."""
        self._db.execute("begin immediate")
        try:
            found = self._version()
            if found is None:
                create(self._db)
                self.set_meta("schema_version", str(SCHEMA_VERSION))
                self.set_meta("terms_version", texts.version())
            elif found > SCHEMA_VERSION:
                raise RuntimeError(f"{self.path} was written by a newer mneme-llm (schema {found}); upgrade "
                                   "mneme-llm to read it")
            elif found < SCHEMA_VERSION:
                raise RuntimeError(f"{self.path} has schema {found}, this mneme-llm reads schema {SCHEMA_VERSION}: run "
                                   f"`python -m mneme_llm.migrate {self.path}`")
            else:
                create(self._db)  # a table added within this schema (one an older reader leaves alone): links
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

    def rows_in(self, sql: str, values: Iterable, parameters: Iterable = ()) -> list[sqlite3.Row]:
        """`sql` for any number of values: its `{}` takes marks for up to IN_LIST of them at a time, after `parameters`.
        Any statement will do (a delete gives no rows)."""
        values, parameters, found = list(values), tuple(parameters), []
        for start in range(0, len(values), IN_LIST):
            chunk = values[start:start + IN_LIST]
            found += self.rows(sql.format(", ".join("?" * len(chunk))), parameters + tuple(chunk))
        return found

    def transaction(self):
        """`with store.transaction():` several writes that land together or not at all. It takes the write lock up
        front (`begin immediate`), so another process writing the same file is waited for rather than failing
        midway; a transaction inside another is a savepoint of it."""
        return _Transaction(self)

    def index(self, name: str, rebuild: Callable[[], None]) -> None:
        """`rebuild()` makes the term index `name` again from what it indexes (`reindex` calls it)."""
        self._indexes[name] = rebuild

    def reindex(self) -> bool:
        """Every term index made again when the tokenizer has changed since it was made (`terms_version`: jieba turned
        on or off, a new release); whether it was. Whoever reads an index asks this first."""
        wanted = texts.version()
        if self.meta("terms_version") == wanted:
            return False
        with self.transaction():
            if self.meta("terms_version") == wanted:  # (another writer, while this one waited for the lock)
                return False
            for rebuild in self._indexes.values():
                rebuild()
            self.set_meta("terms_version", wanted)
        return True

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

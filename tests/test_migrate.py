"""A memory file made by mneme-llm 0.3 and the first builds of 0.4, schema 1, made current. `SCHEMA_1` is that schema
as it stood, with what `Store` used to add on open."""

import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from mneme_llm import Mneme, migrate as migrate_module
from mneme_llm.dates import talking_day
from mneme_llm.episodes import cost
from mneme_llm.migrate import main, migrate
from mneme_llm.store import SCHEMA_VERSION
from mneme_llm.text import fold, version
from tests.invariants import check

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START = datetime(2026, 1, 1, 12, tzinfo=timezone.utc).timestamp()
SCHEMA_1 = """
create table meta (key text primary key, value text not null);
create table memories (id integer primary key, space text not null, subject text not null, key text, kind text not null,
    text text not null, importance integer not null, feeling real not null default 0, happened_at real not null,
    created_at real not null, recalled_at real, recalls integer not null default 0, superseded_by integer,
    deleted_at real, source text, gloss text, terms text, folded text);
create index memories_live on memories(space, subject, deleted_at, superseded_by);
create index memories_key on memories(space, subject, key);
create index memories_folded on memories(space, subject, folded);
create index memories_newest on memories(space, subject, id);
create index memories_important on memories(space, subject, importance, id);
create table recalls (id integer primary key, space text not null, subject text not null, at real not null,
    query text not null, chosen text not null, skipped text not null);
create table profiles (space text not null, subject text not null, text text not null, updated_at real not null,
    primary key (space, subject));
create table moods (space text not null, subject text not null, value real not null, emotions text not null,
    updated_at real not null, last_event integer, told_event integer, primary key (space, subject));
create table mood_events (id integer primary key, space text not null, subject text not null, at real not null,
    delta real not null, value real not null, emotions text not null, reason text not null, confidence real not null,
    source text not null, judge text not null);
create table vectors (memory_id integer not null, embedder text not null, vector blob not null, taught text,
    primary key (memory_id, embedder));
create index vectors_untaught on vectors(embedder) where taught is null;
create table meaning_terms (embedder text not null, term text not null, count integer not null, vector blob not null,
    primary key (embedder, term));
create table note_terms (space text not null, subject text not null, term text not null, memory_id integer not null,
    primary key (space, subject, term, memory_id)) without rowid;
create index note_terms_memory on note_terms(memory_id);
create table config (space text not null, key text not null, value text not null, origin text not null,
    updated_at real not null, primary key (space, key));
create table relationships (space text not null, subject text not null, role text not null, closeness real not null,
    since real not null, updated_at real not null, primary key (space, subject));
create table aliases (space text not null, subject text not null, alias text not null, updated_at real not null,
    primary key (space, subject));
create table people (space text not null, subject text not null, person text not null, updated_at real not null,
    primary key (space, subject));
create index people_person on people(space, person);
create table episodes (id integer primary key, space text not null, subject text not null, at real not null,
    conversation text not null default '', lines text not null, size integer not null, stability real not null,
    recalled_at real, recalls integer not null default 0, terms text);
create index episodes_subject on episodes(space, subject, at);
create index episodes_conversation on episodes(space, subject, conversation, at);
create table episode_terms (space text not null, subject text not null, term text not null, episode_id integer not null,
    primary key (space, subject, term, episode_id)) without rowid;
create index episode_terms_episode on episode_terms(episode_id);
create table episode_vectors (episode_id integer not null, embedder text not null, vector blob not null,
    primary key (episode_id, embedder));
create table surfaces (space text not null, subject text not null, since real not null, summary text not null,
    updated_at real not null, primary key (space, subject));
create table first_prompts (space text not null, subject text not null, text text not null, at real not null,
    by_command integer not null, send integer not null, primary key (space, subject));
create table episode_spread (space text not null, subject text not null, embedder text not null, bins text not null,
    pairs integer not null, primary key (space, subject, embedder));
create table micro_models (name text primary key, model blob);
"""
LINES = [["Leo", "我的猫叫年糕"], ["小鲸", "好可爱"]]


def old_file(folder: str, zone: str = "UTC+8") -> str:
    """A schema 1 file: two spaces' config, exchanges (one said late at night), a surface, notes (one never indexed, and
    one from before the case-folded text was kept), centroids and links, with stale settings."""
    path = os.path.join(folder, "old.db")
    db = sqlite3.connect(path)
    db.executescript(SCHEMA_1)
    db.executemany("insert into meta values (?, ?)", [("schema_version", "1"), ("terms_version", "4"),
                                                      ("terms_indexed", "1"), ("meaning_texts:toy", "2"),
                                                      ("meaning_version:toy", "4"), ("floor:toy", '{"version": 1}')])
    for key, value in (("companion.zone", json.dumps(zone)), ("companion.name", '"小鲸"'), ("mood.thresholds", "[1, 2]"),
                       ("prompts.asks_back", '"Ask them back."'), ("memory.gone_long_ago", "1")):
        db.execute("insert into config values ('t', ?, ?, 'default', 0)", (key, value))
    db.execute("""insert into config values ('other', 'companion.zone', '"Not/AZone"', 'default', 0)""")
    late = START + 11.5 * 3600  # 23:30 UTC is 07:30 the next day in UTC+8
    for space, at in (("t", START), ("t", START + 3600), ("t", late), ("other", late)):
        db.execute("insert into episodes (space, subject, at, conversation, lines, size, stability, terms) values "
                   "(?, 'u', ?, 'dm', ?, 2, 30, '猫 年糕')", (space, at, json.dumps(LINES, ensure_ascii=False)))
    db.execute("insert into episode_terms values ('t', 'u', '年糕', 1)")
    db.execute("insert into surfaces values ('t', 'u', ?, 'he has a cat', ?)", (START + 3600, START))
    db.execute("insert into surfaces values ('t', 'nobody', ?, '', ?)", (START, START))
    db.execute("insert into first_prompts values ('t', 'u', '你是我的姐姐', ?, 0, 0)", (START,))
    db.execute("insert into memories (id, space, subject, kind, text, importance, happened_at, created_at, terms, folded) "
               "values (1, 't', 'u', 'fact', 'Has a CAT', 3, 0, 0, null, null)")
    db.execute("insert into memories (id, space, subject, kind, text, importance, happened_at, created_at, terms, folded) "
               "values (2, 't', 'u', 'fact', 'Likes tea', 3, 0, 0, 'like tea', 'likes tea')")
    db.execute("insert into note_terms values ('t', 'u', 'tea', 2)")
    db.execute("insert into vectors values (2, 'toy', ?, 'like tea')", (b"\0\0\0\0",))
    db.execute("insert into meaning_terms values ('toy', 'tea', 1, ?)", (b"\0\0\0\0",))
    db.execute("insert into people values ('t', 'web:leo', 'u', 0)")
    db.commit()
    db.close()
    return path


class RefusedTests(unittest.TestCase):
    def test_a_file_of_schema_1_is_refused_untouched_and_told_what_to_run(self):
        with tempfile.TemporaryDirectory() as folder:
            path = old_file(folder)
            with self.assertRaises(RuntimeError) as caught:
                Mneme(path, "t", embed=False)
            self.assertIn(f"python -m mneme_llm.migrate {path}", str(caught.exception))
            with contextlib.closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("select value from meta where key = 'schema_version'").fetchone()[0], "1")
                self.assertEqual(db.execute("pragma journal_mode").fetchone()[0], "delete")

    def test_the_command_says_so_too(self):
        from mneme_llm.cli import main as cli
        with tempfile.TemporaryDirectory() as folder:
            path = old_file(folder)
            out = io.StringIO()
            with contextlib.redirect_stderr(out):
                self.assertEqual(cli(["--db", path, "subjects"]), 2)
            self.assertIn("mneme_llm.migrate", out.getvalue())


class MigrateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = old_file(self.folder.name)

    def rows(self, sql):
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            return db.execute(sql).fetchall()

    def open(self):
        m = Mneme(self.path, "t", embed=False, memory_language=None, companion_name="小鲸")
        self.addCleanup(m.close)
        return m

    def test_every_exchange_gets_its_day_in_its_spaces_zone_and_its_tokens(self):
        migrate(self.path)
        eight = timezone(timedelta(hours=8))
        rows = self.rows("select * from episodes order by id")
        self.assertEqual([row["id"] for row in rows], [1, 2, 3, 4])
        self.assertEqual(rows[2]["day"], talking_day(rows[2]["at"], eight))  # already the next day where she lives
        self.assertNotEqual(rows[2]["day"], talking_day(rows[2]["at"], timezone.utc))
        self.assertEqual(rows[3]["day"], talking_day(rows[3]["at"], None))  # a zone that cannot be read: the machine's
        self.assertEqual(rows[0]["tokens"], cost(LINES))
        self.assertNotIn("terms", rows[0].keys())

    def test_a_surface_starts_at_the_last_exchange_said_before_it(self):
        report = migrate(self.path)
        rows = {row["subject"]: dict(row) for row in self.rows("select * from surfaces")}
        self.assertEqual(rows["u"], {"space": "t", "subject": "u", "start_id": 1, "cleared_at": START + 3600,
                                     "summary": "he has a cat"})
        self.assertEqual(rows["nobody"]["start_id"], 0)
        self.assertIn("2 surfaces", report)
        m = self.open()
        self.assertEqual(m.surface.began("u"), START + 3600)
        self.assertEqual(len(m.surface.read("u").messages), 5)  # the summary, and two exchanges of two lines each

    def test_what_nothing_reads_is_gone(self):
        report = migrate(self.path)
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            tables = {row[0] for row in db.execute("select name from sqlite_master where type = 'table'")}
            indexes = {row[0] for row in db.execute("select name from sqlite_master where type = 'index'")}
            columns = {table: {row[1] for row in db.execute(f"pragma table_info({table})")}
                       for table in ("memories", "vectors", "people")}
            meta = dict(db.execute("select key, value from meta").fetchall())
        self.assertFalse({"micro_models", "meaning_terms"} & tables)
        self.assertFalse([table for table in tables if table.startswith("old_")])
        self.assertNotIn("vectors_untaught", indexes)
        self.assertIn("episodes_day", indexes)
        self.assertNotIn("terms", columns["memories"])
        self.assertNotIn("taught", columns["vectors"])
        self.assertNotIn("updated_at", columns["people"])
        self.assertEqual(meta["schema_version"], str(SCHEMA_VERSION))
        self.assertIn("floor:toy", meta)  # (what is measured stays)
        self.assertFalse({"terms_indexed", "meaning_texts:toy", "meaning_version:toy"} & set(meta))
        self.assertIn("micro_models", report)

    def test_config_keys_no_version_knows_are_deleted(self):
        report = migrate(self.path)
        keys = {row["key"] for row in self.rows("select key from config")}
        self.assertEqual(keys, {"companion.zone", "companion.name"})
        self.assertIn("3 old config keys", report)
        self.assertEqual(self.open().config.unknown, [])

    def test_notes_links_and_first_prompts_carry_over(self):
        migrate(self.path)
        m = self.open()
        self.assertEqual(sorted(note.text for note in m.memory.notes("u")), ["Has a CAT", "Likes tea"])
        self.assertEqual(self.rows("select folded from memories where id = 1")[0]["folded"], fold("Has a CAT"))
        self.assertEqual(m.person("web:leo"), "u")
        self.assertEqual(m.surface.first("u").text, "你是我的姐姐")
        self.assertEqual(m.meaning, None)
        self.assertEqual(self.rows("select count(*) as n from vectors")[0]["n"], 1)

    def test_the_search_indexes_are_made_again_at_the_first_search(self):
        migrate(self.path)
        m = self.open()
        self.assertIsNone(m.store.meta("terms_version"))
        found = m.recall("u", "cat", important=0, recent=0)  # a note that was never indexed
        self.assertEqual([item.note.text for item in found.chosen], ["Has a CAT"])
        self.assertEqual(len(m.episodes.search("u", "年糕", limit=9)), 3)  # (only one was, in that file)
        self.assertEqual(m.store.meta("terms_version"), version())
        m.store.execute("delete from config where space = 'other'")  # (its zone is a wrong one, on purpose)
        self.assertEqual(check(m.store), [])

    def test_a_new_exchange_goes_on_after_the_old_ids(self):
        migrate(self.path)
        m = self.open()
        self.assertEqual(m.episodes.keep("u", [("Leo", "新的一句")]).id, 5)
        m.episodes.forget("u", 5)
        self.assertEqual(m.episodes.keep("u", [("Leo", "再一句")]).id, 6)

    def test_running_it_twice_changes_nothing(self):
        migrate(self.path)
        with open(self.path, "rb") as file:
            before = file.read()
        self.assertIn("nothing to do", migrate(self.path))
        with open(self.path, "rb") as file:
            self.assertEqual(file.read(), before)

    def test_a_failure_leaves_the_file_as_it_was(self):
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.execute("update episodes set lines = 'not json' where id = 3")
            db.commit()
        with self.assertRaises(ValueError):
            migrate(self.path)
        self.assertEqual(self.rows("select value from meta where key = 'schema_version'")[0]["value"], "1")
        self.assertEqual(len(self.rows("select * from micro_models")), 0)
        self.assertEqual(self.rows("select since from surfaces where subject = 'u'")[0]["since"], START + 3600)

    def test_an_older_schema_1_file_with_no_episodes_is_made_current(self):
        path = os.path.join(self.folder.name, "first.db")
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.executescript("""
                create table meta (key text primary key, value text not null);
                insert into meta values ('schema_version', '1');
                create table memories (id integer primary key, space text not null, subject text not null, key text,
                    kind text not null, text text not null, importance integer not null, feeling real not null default 0,
                    happened_at real not null, created_at real not null, recalled_at real,
                    recalls integer not null default 0, superseded_by integer, deleted_at real, source text);
                insert into memories (space, subject, kind, text, importance, happened_at, created_at)
                    values ('t', 'u', 'fact', 'Has a cat', 3, 0, 0);
                create table config (space text not null, key text not null, value text not null, origin text not null,
                    updated_at real not null, primary key (space, key));
            """)
        migrate(path)
        with contextlib.closing(Mneme(path, "t", embed=False, memory_language=None)) as m:
            self.assertEqual([item.note.text for item in m.recall("u", "cat", important=0, recent=0).chosen],
                             ["Has a cat"])
            self.assertEqual(m.episodes.count(), 0)
            self.assertEqual(check(m.store), [])

    def test_it_runs_as_a_module_over_several_files_and_says_what_it_did(self):
        second = os.path.join(self.folder.name, "second")
        os.mkdir(second)
        other = old_file(second)
        env = dict(os.environ, PYTHONPATH=ROOT, PYTHONIOENCODING="utf-8")
        done = subprocess.run([sys.executable, "-m", "mneme_llm.migrate", self.path, other], env=env, capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("schema 1 to 2", lines[0])
        self.assertIn(self.path, lines[0])

    def test_it_says_what_is_wrong_with_a_file_it_cannot_migrate(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(main([]), 2)
            self.assertEqual(main([os.path.join(self.folder.name, "no.db")]), 1)
        self.assertIn("usage", err.getvalue())
        self.assertIn("no such file", err.getvalue())
        self.assertFalse(os.path.exists(os.path.join(self.folder.name, "no.db")))  # (and it made none)


if __name__ == "__main__":
    unittest.main()

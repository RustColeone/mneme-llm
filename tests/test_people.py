import contextlib
import io
import os
import sqlite3
import tempfile
import unittest

from mneme_llm import Mneme
from mneme_llm.cli import main
from tests.invariants import check

NOON = 1_760_000_000.0
DAY = 86400.0


class Clock:
    def __init__(self, now=NOON):
        self.now = now

    def __call__(self):
        return self.now


def mneme(path=":memory:", clock=None, **options):
    return Mneme(path, "t", luna=False, micro=False, embed=False, memory_language=None,
                 clock=clock or (lambda: NOON), **options)


class LinkTests(unittest.TestCase):
    def test_either_account_means_the_same_person(self):
        m = mneme()
        self.assertEqual(m.link("web:leo", "discord:42"), "discord:42")
        self.assertEqual(m.person("web:leo"), "discord:42")
        self.assertEqual(m.person("discord:42"), "discord:42")
        self.assertEqual(m.person("someone"), "someone")
        m.remember("web:leo", "养了一只叫年糕的猫", kind="fact", key="pet.name")
        self.assertEqual([note.subject for note in m.memory.notes("discord:42")], ["discord:42"])
        self.assertEqual([item.note.text for item in m.recall("web:leo", "猫").chosen], ["养了一只叫年糕的猫"])
        m.relate("web:leo", "friend")
        self.assertEqual(m.relations.get("discord:42").role, "friend")
        m.alias("discord:42", "鲸酱")
        self.assertEqual(m.aliases.get("web:leo"), "鲸酱")
        m.mood.apply("web:leo", delta=10, reason="a kind word")
        self.assertEqual(m.mood.state("discord:42").value, m.mood.state("web:leo").value)
        self.assertEqual(len(m.mood.timeline("discord:42")), 1)
        told = m.prompt("web:leo", "猫", user_name="Leo")
        self.assertIn("a kind word", told)
        self.assertEqual(m.prompt("discord:42", "猫", user_name="Leo"), told.rsplit("\n\n", 1)[0])  # (told once)
        self.assertEqual(m.memory.subjects(), ["discord:42"])
        self.assertEqual(m.people.subjects("web:leo"), ["discord:42", "web:leo"])
        self.assertEqual(check(m.store), [])

    def test_what_each_account_kept_is_joined(self):
        clock = Clock()
        m = mneme(clock=clock)
        m.remember("discord:42", "住在上海", kind="fact", key="user.city")
        m.remember("discord:42", "喜欢乌龙茶", kind="preference")
        m.relate("discord:42", "acquaintance")
        m.alias("discord:42", "鲸鱼")
        m.memory.set_profile("discord:42", "an old impression")
        m.mood.apply("discord:42", delta=-20, emotions={"sad": 40}, reason="old news")
        clock.now += DAY
        m.remember("web:leo", "住在北京", kind="fact", key="user.city")  # moved since: the newer value wins
        m.remember("web:leo", "喜欢乌龙茶", kind="preference")         # the same words: kept once
        m.remember("web:leo", "下周三考物理", kind="plan")
        m.relate("web:leo", "creator")
        m.alias("web:leo", "鲸酱")
        m.memory.set_profile("web:leo", "a newer impression")
        m.mood.apply("web:leo", delta=10, emotions={"happy": 30}, reason="good news")
        clock.now += DAY
        m.link("web:leo", "discord:42")
        texts = sorted(note.text for note in m.memory.notes("discord:42"))
        self.assertEqual(texts, sorted(["住在北京", "喜欢乌龙茶", "下周三考物理"]))
        self.assertEqual([note.text for note in m.memory.history("discord:42", "user.city")], ["住在上海", "住在北京"])
        relationship = m.relations.get("web:leo")
        self.assertEqual((relationship.subject, relationship.role), ("discord:42", "creator"))  # the closer one
        self.assertEqual(relationship.since, NOON)  # since the earlier day
        self.assertEqual(m.aliases.all(), {"discord:42": "鲸酱"})
        self.assertEqual(m.memory.profile("discord:42"), "a newer impression")
        self.assertIn("happy", m.mood.state("discord:42").emotions)  # the newer mood
        self.assertEqual(len(m.mood.timeline("discord:42")), 2)  # and both timelines
        self.assertEqual([row["subject"] for row in m.store.rows("select distinct subject from note_terms")],
                         ["discord:42"])
        self.assertEqual(check(m.store), [])

    def test_the_person_keeps_their_own_when_as_close(self):
        m = mneme()
        m.relate("discord:42", "friend", closeness=50)
        m.relate("web:leo", "friend", closeness=50)
        m.alias("discord:42", "鲸酱")
        m.alias("web:leo", "Whale")  # set at the same moment: the person's own stays
        m.link("web:leo", "discord:42")
        self.assertEqual(m.aliases.all(), {"discord:42": "鲸酱"})
        self.assertEqual(m.relations.get("discord:42").closeness, 50)
        self.assertEqual(check(m.store), [])

    def test_links_stay_one_step_deep(self):
        m = mneme()
        m.link("b", "a")
        self.assertEqual(m.link("c", "b"), "a")  # to the person b stands for
        self.assertEqual(m.people.all(), {"b": "a", "c": "a"})
        m.remember("d", "a note of d's")
        m.link("e", "d")
        self.assertEqual(m.link("d", "a"), "a")  # d's own links follow it
        self.assertEqual(m.people.all(), {"b": "a", "c": "a", "d": "a", "e": "a"})
        self.assertEqual([note.subject for note in m.memory.notes("e")], ["a"])
        self.assertEqual(m.link("a", "c"), "a")  # already one person: nothing changes
        self.assertEqual(m.link("a", "a"), "a")
        m.link("y", "x")
        with self.assertRaises(ValueError):
            m.link("y", "a")  # linked to someone else: unlink it first
        for bad in ("", "  "):
            with self.assertRaises(ValueError):
                m.link(bad, "a")
            with self.assertRaises(ValueError):
                m.link("z", bad)
        self.assertEqual(check(m.store), [])

    def test_unlinked_an_account_is_its_own_again(self):
        m = mneme()
        m.link("web:leo", "discord:42")
        m.remember("web:leo", "喜欢乌龙茶")
        self.assertTrue(m.unlink("web:leo"))
        self.assertFalse(m.unlink("web:leo"))
        self.assertEqual(m.memory.notes("web:leo"), [])  # what was joined stays with the person
        self.assertEqual(len(m.memory.notes("discord:42")), 1)
        m.remember("web:leo", "a note of its own")
        self.assertEqual([note.text for note in m.memory.notes("web:leo")], ["a note of its own"])
        self.assertEqual(check(m.store), [])

    def test_erase_from_any_account_takes_the_person_and_their_links(self):
        m = mneme()
        m.link("web:leo", "discord:42")
        m.link("discord:43", "discord:42")
        m.link("amy:2", "amy:1")
        m.remember("web:leo", "喜欢乌龙茶")
        m.relate("discord:42", "creator")
        self.assertEqual(m.erase("discord:43"), 1)
        self.assertEqual(m.memory.notes("discord:42"), [])
        self.assertIsNone(m.relations.get("discord:42"))
        self.assertEqual(m.people.all(), {"amy:2": "amy:1"})
        self.assertEqual(check(m.store), [])

    def test_export_and_import_carry_the_links(self):
        m = mneme()
        m.link("web:leo", "discord:42")
        m.remember("web:leo", "喜欢乌龙茶")
        data = m.export_data()
        self.assertEqual(data["people"], [{"space": "t", "subject": "web:leo", "person": "discord:42",
                                           "updated_at": NOON}])
        fresh = mneme()
        fresh.import_data(data)
        self.assertEqual(fresh.person("web:leo"), "discord:42")
        self.assertEqual(len(fresh.memory.notes("web:leo")), 1)
        # An export of a file without the link, imported where the accounts are linked: its notes join the person.
        other = mneme()
        other.remember("web:leo", "下周三考物理", kind="plan")
        data = other.export_data()
        data["people"] += [{"subject": "x"}, "junk", {"subject": "web:leo", "person": "elsewhere"}]
        fresh.import_data(data)
        self.assertEqual(sorted(note.text for note in fresh.memory.notes("discord:42")), ["下周三考物理", "喜欢乌龙茶"])
        self.assertEqual(fresh.person("web:leo"), "discord:42")  # this file's link stays
        self.assertEqual(check(fresh.store), [])

    def test_a_file_without_the_table_gains_it_on_open(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "c.db")
            mneme(path).close()
            with contextlib.closing(sqlite3.connect(path)) as db:
                db.execute("drop table people")
                db.commit()
            m = mneme(path)
            m.link("web:leo", "discord:42")
            self.assertEqual(m.person("web:leo"), "discord:42")
            m.close()

    def test_the_command_links_and_lists(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "c.db")

            def run(*argv):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = main(["--db", path, "--space", "t", *argv])
                return code, out.getvalue().strip(), err.getvalue().strip()
            self.assertEqual(run("remember", "web:leo", "喜欢乌龙茶")[0], 0)
            self.assertEqual(run("link", "web:leo", "discord:42"), (0, "web:leo is discord:42", ""))
            self.assertEqual(run("people"), (0, "web:leo -> discord:42", ""))
            self.assertIn("喜欢乌龙茶", run("notes", "discord:42")[1])
            run("link", "y", "x")
            code, _, error = run("link", "y", "discord:42")
            self.assertEqual((code, error), (2, "y is linked to x; unlink it first"))
            self.assertEqual(run("unlink", "web:leo")[1], "unlinked")
            self.assertEqual(run("unlink", "web:leo")[1], "(not linked)")
            self.assertEqual(run("people")[1], "y -> x")


if __name__ == "__main__":
    unittest.main()

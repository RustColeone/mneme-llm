import contextlib
import io
import json
import os
import tempfile
import unittest

from mneme_llm import Mneme
from mneme_llm.cli import main
from tests.invariants import check

NOON = 1_760_000_000.0


def mneme(path=":memory:", **options):
    return Mneme(path, "t", luna=False, micro=False, embed=False, memory_language=None, clock=lambda: NOON,
                 **options)


class AliasTests(unittest.TestCase):
    def test_a_person_names_the_companion_and_the_prompt_says_so(self):
        m = mneme(companion_name="大肥鱼")
        self.assertEqual(m.prompt("leo", user_name="Leo"), "")
        self.assertEqual(m.alias("leo", "  鲸酱\n"), "鲸酱")
        self.assertEqual(m.aliases.get("leo"), "鲸酱")
        self.assertIsNone(m.aliases.get("someone"))  # one person's name for her is theirs alone
        self.assertEqual(m.prompt("leo", user_name="Leo"), "(Leo calls you 鲸酱.)")
        m.relate("leo", "creator")
        self.assertEqual(m.prompt("leo", user_name="Leo").split("\n\n"),
                         ["(Leo is your creator; you are very close.)", "(Leo calls you 鲸酱.)"])
        m.display_language = "zh"
        self.assertIn("（Leo叫你鲸酱。）", m.prompt("leo", user_name="Leo"))
        self.assertEqual(m.alias("leo", "Whale"), "Whale")  # a new one replaces the old
        self.assertEqual(m.aliases.all(), {"leo": "Whale"})
        self.assertIsNone(m.alias("leo", None))
        self.assertEqual(m.aliases.all(), {})
        self.assertEqual(check(m.store), [])

    def test_an_alias_is_one_short_line_and_never_empty(self):
        m = mneme()
        self.assertEqual(m.alias("leo", "a very long name " * 5), ("a very long name " * 5)[:39].rstrip() + "…")
        self.assertEqual(m.alias("leo", "two\nlines"), "two lines")
        for bad in ("", "   ", "​"):
            with self.assertRaises(ValueError):
                m.alias("leo", bad)
        with self.assertRaises(TypeError):
            m.alias("leo", 42)
        with self.assertRaises(ValueError):
            m.alias(" ", "鲸酱")
        self.assertEqual(m.aliases.get("leo"), "two lines")
        self.assertEqual(check(m.store), [])

    def test_spaces_keep_their_own_and_erase_takes_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "c.db")
            whale = mneme(path)
            other = Mneme(path, "other", luna=False, micro=False, embed=False, memory_language=None)
            whale.alias("leo", "鲸酱")
            self.assertIsNone(other.aliases.get("leo"))
            whale.erase("leo")
            self.assertIsNone(whale.aliases.get("leo"))
            other.close()
            whale.close()

    def test_export_and_import_carry_it_under_the_same_rule(self):
        m = mneme()
        m.alias("leo", "鲸酱")
        data = m.export_data()
        self.assertEqual(data["aliases"], [{"space": "t", "subject": "leo", "alias": "鲸酱", "updated_at": NOON}])
        data["aliases"] += [{"subject": "amy", "alias": "x" * 99}, {"subject": "bob", "alias": " "},
                            {"subject": "", "alias": "Fish"}, {"alias": "Fish"}, "junk",
                            {"subject": "cy", "alias": "Fishy", "updated_at": 4e12}]
        fresh = mneme()
        fresh.import_data(data)
        self.assertEqual(fresh.aliases.all(), {"amy": "x" * 39 + "…", "cy": "Fishy", "leo": "鲸酱"})
        self.assertLessEqual(fresh.store.row("select updated_at from aliases where subject = 'cy'")[0], NOON)
        self.assertEqual(check(fresh.store), [])

    def test_a_file_from_0_1_gains_the_table_on_open(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "old.db")
            m = mneme(path)
            m.store.execute("drop table aliases")
            m.close()
            m = mneme(path)
            self.assertEqual(m.store.meta("schema_version"), "1")
            m.alias("leo", "鲸酱")
            m.close()

    def test_the_command_shows_sets_and_removes_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "c.db")

            def run(*words):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    code = main(["--db", path, "--space", "t", *words])
                return code, out.getvalue().strip()
            self.assertEqual(run("alias", "leo"), (0, "(no alias)"))
            self.assertEqual(run("alias", "leo", "鲸酱"), (0, "鲸酱"))
            self.assertEqual(run("alias", "leo"), (0, "鲸酱"))
            self.assertEqual(run("alias", "leo", " ")[0], 2)
            exported = json.loads(run("export")[1])
            self.assertEqual([row["alias"] for row in exported["aliases"]], ["鲸酱"])
            self.assertEqual(run("alias", "leo", "--remove"), (0, "removed"))
            self.assertEqual(run("alias", "leo", "--remove"), (0, "(no alias)"))


if __name__ == "__main__":
    unittest.main()

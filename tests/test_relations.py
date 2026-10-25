import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest

from mneme_llm import Mneme, Role
from mneme_llm.cli import main
from mneme_llm.relations import DAY
from tests.invariants import check

NOON = 1_760_000_000.0  # a fixed moment; the companion's zone is the machine's


class Clock:
    def __init__(self, now: float = NOON):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def days(self, count: float) -> None:
        self.now += count * DAY


async def judge(system, user):  # every exchange: a little better, and happy
    return json.dumps({"mood_change": {"level": "1"}, "feeling": {"choice": "happy"}})


def mneme(clock=None, **options):
    return Mneme(":memory:", "t", luna=False, micro=False, embed=False, memory_language=None,
                 clock=clock or Clock(), **options)


class RoleTests(unittest.TestCase):
    def test_each_role_starts_within_its_band(self):
        m = mneme()
        starts = {role: m.relate(role, role).closeness for role in ("creator", "family", "friend", "acquaintance")}
        self.assertEqual(starts, {"creator": 100, "family": 80, "friend": 50, "acquaintance": 20})
        self.assertEqual(m.relate("friend", "friend", closeness=85).closeness, 85)
        for role, closeness in (("family", 30), ("acquaintance", 75), ("friend", float("nan")), ("friend", True)):
            with self.assertRaises(ValueError):
                m.relate("x", role, closeness=closeness)
        with self.assertRaises(ValueError):
            m.relate("x", "boss")
        with self.assertRaises(ValueError):
            m.relate(" ", "friend")
        self.assertIsNone(m.relations.get("x"))

    def test_there_is_one_creator(self):
        m = mneme()
        m.relate("leo", "creator")
        m.relate("leo", "creator", closeness=90)  # the same person again is fine
        with self.assertRaises(ValueError):
            m.relate("someone", "creator")
        m.relate("leo", "family")
        m.relate("someone", "creator")
        self.assertEqual([r.role for r in m.relations.all()], ["creator", "family"])

    def test_a_hosts_own_role(self):
        teacher = Role("teacher", floor=40, ceiling=95, start=70, names={"en": "your teacher", "zh": "你的老师"})
        m = mneme(roles=(teacher,))
        m.relate("ms_wu", "teacher")
        self.assertEqual(m.relations.line("ms_wu", "Ms Wu"), "(Ms Wu is your teacher; you are close.)")
        with self.assertRaises(ValueError):
            m.relate("leo", "creator")  # this host has no creator role
        with self.assertRaises(ValueError):
            Role("upside_down", floor=90, ceiling=10)


class ClosenessTests(unittest.TestCase):
    def test_it_grows_once_a_day_up_to_the_ceiling(self):
        clock = Clock()
        m = mneme(clock)
        m.relate("amy", "friend", closeness=88)
        m.relations.seen("amy")  # the day the role was given
        self.assertEqual(m.relations.get("amy").closeness, 88)
        clock.days(1)
        m.relations.seen("amy")
        m.relations.seen("amy")  # twice in a day counts once
        self.assertAlmostEqual(m.relations.get("amy").closeness, 89, places=1)
        for _ in range(5):
            clock.days(1)
            m.relations.seen("amy")
        self.assertEqual(m.relations.get("amy").closeness, 90)  # a friend's ceiling
        self.assertIsNone(m.relations.seen("stranger"))  # no role is given by talking
        self.assertIsNone(m.relations.get("stranger"))

    def test_it_fades_without_contact_down_to_the_floor_but_never_for_the_creator(self):
        clock = Clock()
        m = mneme(clock)
        m.relate("amy", "friend", closeness=60)
        m.relate("mum", "family", closeness=70)
        m.relate("leo", "creator", closeness=95)
        clock.days(90)
        self.assertAlmostEqual(m.relations.get("amy").closeness, 57)
        clock.days(3650)
        self.assertEqual({r.subject: round(r.closeness) for r in m.relations.all()},
                         {"leo": 95, "mum": 60, "amy": 20})
        clock.days(1)
        m.relations.seen("amy")  # a visit after years: from the floor, one point
        self.assertAlmostEqual(m.relations.get("amy").closeness, 21)

    def test_closeness_sets_the_weight_and_the_words(self):
        m = mneme()
        self.assertEqual(m.relations.weight("nobody"), 1.0)
        self.assertEqual(m.relations.line("nobody"), "")
        m.relate("leo", "creator")
        m.relate("bob", "acquaintance", closeness=0)
        self.assertEqual(m.relations.weight("leo"), 1.5)
        self.assertEqual(m.relations.weight("bob"), 0.5)
        self.assertEqual(m.relations.line("leo", "Leo"), "(Leo is your creator; you are very close.)")
        self.assertEqual(m.relations.line("bob"), "(bob is someone you know; you are barely acquainted.)")
        zh = mneme(display_language="zh")
        zh.relate("leo", "family", closeness=65)
        self.assertEqual(zh.relations.line("leo", "Leo"), "（Leo是你的家人，你们很亲近。）")


class CompanionTests(unittest.TestCase):
    def test_a_close_persons_words_move_the_mood_more(self):
        m = mneme(complete=judge)
        m.relate("leo", "creator")
        m.relate("bob", "acquaintance")
        moved = {}
        for who in ("leo", "bob", "nobody"):
            seen = m.observe(who, [(who, "I got the job!"), ("assistant", "Wonderful!")], user_name=who,
                             capture=False)
            moved[who] = seen.mood.delta
        self.assertGreater(moved["nobody"], 0)
        self.assertAlmostEqual(moved["leo"] / moved["nobody"], 1.5)  # closeness 100
        self.assertAlmostEqual(moved["bob"] / moved["nobody"], 0.7)  # closeness 20

    def test_talking_is_a_day_of_contact_and_reaching_out_is_not(self):
        clock = Clock()
        m = mneme(clock, complete=judge)
        m.relate("amy", "friend")
        clock.days(1)
        m.observe("amy", "the companion said hello", source="speak-up", capture=False)
        self.assertEqual(round(m.relations.get("amy").closeness), 50)
        m.observe("amy", [("amy", "hi!")], user_name="amy", capture=False)
        self.assertEqual(round(m.relations.get("amy").closeness), 51)

    def test_the_prompt_says_who_they_are_before_the_notes(self):
        m = mneme()
        m.relate("leo", "creator")
        self.assertEqual(m.prompt("leo", user_name="Leo"), "(Leo is your creator; you are very close.)")
        m.remember("leo", "Has a cat named Mochi", kind="fact")
        parts = asyncio.run(m.aprompt("leo", "cat", user_name="Leo")).split("\n\n")
        self.assertEqual(parts[0], "(Leo is your creator; you are very close.)")
        self.assertIn("Has a cat named Mochi", parts[1])

    def test_erase_takes_the_role_and_export_carries_it(self):
        m = mneme()
        m.relate("leo", "creator")
        m.relate("amy", "friend", closeness=70)
        data = m.export_data()
        self.assertEqual({row["subject"]: row["role"] for row in data["relationships"]},
                         {"leo": "creator", "amy": "friend"})
        m.erase("leo")
        self.assertIsNone(m.relations.get("leo"))

        other = mneme()
        other.relate("zoe", "creator")  # the copy has a creator of its own: the imported one is skipped
        data["relationships"] += [{"subject": "max", "role": "family", "closeness": 10},
                                  {"subject": "kai", "role": "coach", "closeness": 400, "since": "soon"},
                                  {"subject": "", "role": "friend"}, {"role": "friend"}, "junk"]
        other.import_data(data)
        found = {r.subject: (r.role, round(r.closeness)) for r in other.relations.all()}
        self.assertEqual(found, {"zoe": ("creator", 100), "amy": ("friend", 70), "max": ("family", 60),
                                 "kai": ("coach", 100)})  # held to the bands; an unknown role keeps 0-100
        self.assertEqual(check(other.store), [])


class CommandTests(unittest.TestCase):
    def run_cli(self, *args) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--db", self.path, *args])
        return code, out.getvalue().strip(), err.getvalue().strip()

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "c.db")

    def test_relate_and_relations(self):
        self.assertEqual(self.run_cli("relate", "leo")[1], "(no role)")
        code, out, _ = self.run_cli("relate", "leo", "creator")
        self.assertTrue(out.startswith("leo: creator, closeness 100 (since "), out)
        self.run_cli("relate", "amy", "friend", "--closeness", "70")
        code, _, err = self.run_cli("relate", "bob", "family", "--closeness", "5")
        self.assertEqual((code, err), (2, "closeness for family is a number from 60 to 100"))
        self.assertEqual([line.split(",")[0] for line in self.run_cli("relations")[1].splitlines()],
                         ["leo: creator", "amy: friend"])
        self.assertIn("(leo is your creator; you are very close.)", self.run_cli("context", "leo")[1])
        self.assertEqual(self.run_cli("relate", "amy", "--remove")[1], "removed")
        self.assertEqual(self.run_cli("relate", "amy", "--remove")[1], "(no role)")


if __name__ == "__main__":
    unittest.main()

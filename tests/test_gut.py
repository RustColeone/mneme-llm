"""Tests for the gut (mneme_llm/gut.py): what stays of a companion without her memory or her model."""

import asyncio
import contextlib
import io
import gzip
import json
import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import mneme_llm.gut as G

FORM = {"people": ["coworker"], "gender": ["woman"], "topic": ["lunch"], "event": ["ate"], "sender_feels": "happy",
        "toward_you": "none"}
OTHER = {"people": [], "gender": [], "topic": ["rain"], "event": ["rained"], "sender_feels": "tired", "toward_you": "none"}
JEALOUS = {"jealous": .8, "sweet": .2}
DAY = 86400


class Item:
    def __init__(self, direction, text, name=""):
        self.direction, self.text, self.sender_name, self.kind = direction, text, name, "text"


def lessons(net, subject, feel, count, closeness=85, form=FORM, today=None, known=G.ENDS):
    for _ in range(count):
        net.teach(subject, form, feel, 1, closeness, known, today)


class Ends(unittest.TestCase):
    def test_every_end_is_a_strength_of_its_own(self):
        felt = G.Net().vector(FORM, 85)
        self.assertEqual(tuple(felt), G.ENDS)
        self.assertEqual(len(G.ENDS), 24)
        self.assertTrue(all(.04 < value < .06 for value in felt.values()))  # nothing learned: a trace of each
        net = G.Net()
        lessons(net, "a", {"sweet": .9, "scornful": .9}, 40)
        net.sleep()
        felt = net.vector(FORM, 85)
        self.assertGreater(min(felt["sweet"], felt["scornful"]), .6)  # both sides of a bar at once: love-hate
        self.assertLess(felt["happy"], .1)

    def test_the_bars(self):
        self.assertEqual([bar[0] for bar in G.BARS][:3], ["mood", "security", "composure"])
        self.assertEqual(G.CHINESE["irritable"], "易怒")
        self.assertEqual(G.CHINESE["peaceable"], "平和")
        self.assertEqual(G.CHINESE["tender"], "温柔")
        self.assertEqual(G.CHINESE["stern"], "严厉")
        self.assertIn("irritable or peaceable", G.FEELINGS)
        self.assertTrue(set(G.OLD) <= set(G.ENDS))

    def test_closeness_crosses_the_tags(self):
        net = G.Net()
        lessons(net, "a", JEALOUS, 60)
        net.sleep()
        self.assertGreater(net.vector(FORM, 85)["jealous"], .5)
        self.assertLess(net.vector(OTHER, 10)["jealous"], net.vector(FORM, 85)["jealous"])  # (not for everything)
        self.assertIn("high:people=coworker", G.features(FORM, 85))

    def test_a_lesson_from_0_4_teaches_only_the_seven_it_knew(self):
        net = G.Net()
        defiant = net.vector(FORM, 85)["defiant"]
        lessons(net, "a", {"jealous": .8}, 30, known=G.OLD)
        net.sleep()
        self.assertGreater(net.vector(FORM, 85)["jealous"], .5)
        self.assertAlmostEqual(net.vector(FORM, 85)["defiant"], defiant)  # not told, so not learned as a "no"
        self.assertLess(net.vector(FORM, 85)["happy"], defiant)  # told: a "no"

    def test_her_heart_grows_up(self):
        net = G.Net()
        self.assertAlmostEqual(net.learning(), G.YOUNG)
        net.age = 5 * G.TAU
        self.assertAlmostEqual(net.learning(), G.YOUNG * (G.FLOOR + (1 - G.FLOOR) * 2.718281828 ** -5), places=6)
        moved = []
        for age in (0, 5 * G.TAU):
            net = G.Net()
            net.age = age
            lessons(net, "a", JEALOUS, 20)
            net.sleep()
            moved.append(net.heart.strengths(G.features(FORM, 85))[G.ENDS.index("jealous")])
        self.assertGreater(moved[0], .5)  # young: twenty lessons make her jealous
        self.assertLess(moved[1], .25)  # grown: they barely move her heart

    def test_two_people_two_ways_and_someone_new_meets_her_heart(self):
        net = G.Net()
        for _ in range(60):
            net.teach("alice", FORM, {"jealous": .9}, 1, 85)
            net.teach("bob", FORM, {"calm": .9}, 1, 85)
        net.sleep()
        alice, bob, new = (net.vector(FORM, 85, who)["jealous"] for who in ("alice", "bob", "carol"))
        self.assertGreater(alice, new + .1)
        self.assertLess(bob, new - .1)
        self.assertEqual(new, net.vector(FORM, 85)["jealous"])
        self.assertAlmostEqual(net.weight("alice"), G.MOST)

    def test_someone_not_close_teaches_only_how_she_is_with_them(self):
        net = G.Net()
        heart = net.vector(FORM, 85)
        lessons(net, "stranger", JEALOUS, 60, closeness=10)
        net.sleep()
        self.assertEqual(net.vector(FORM, 85), heart)
        self.assertEqual(net.age, 0)
        self.assertGreater(net.vector(FORM, 10, "stranger")["jealous"], net.vector(FORM, 10)["jealous"] + .1)

    def test_a_person_she_does_not_talk_to_fades_back_and_comes_back(self):
        net = G.Net()
        for day in range(30):
            lessons(net, "alice", JEALOUS, 2, today=day)
        full = net.weight("alice")
        for day in range(30, 120):
            lessons(net, "bob", {"calm": .9}, 1, today=day)
        self.assertAlmostEqual(net.weight("alice"), full * (1 - G.PULL) ** 89, places=6)  # (the day still going is not over)
        self.assertLess(net.weight("alice"), full * .45)
        lessons(net, "alice", JEALOUS, 40, today=120)
        self.assertGreater(net.weight("alice"), full * .95)
        silent = net.weight("bob")
        lessons(net, "alice", JEALOUS, 1, today=125)  # days nobody talked to her are no days
        self.assertAlmostEqual(net.weight("bob"), silent * (1 - G.PULL))

    def test_sleep_settles_and_nothing_snaps_back(self):
        net = G.Net()
        lessons(net, "a", JEALOUS, 15)
        awake = net.vector(FORM, 85)["jealous"]
        net.sleep()
        self.assertGreater(net.vector(FORM, 85)["jealous"], awake)
        self.assertEqual(net.waiting, [])

    def test_the_balance_moves_by_itself(self):
        net = G.Net()
        self.assertEqual(G.balance(net, 0), 0.0)  # nothing lived: her head alone
        net.start([(FORM, JEALOUS, 1, 85)])
        self.assertTrue(.75 < G.balance(net, 0) < .85)  # a starter counts for something
        net.age = 1000
        wiped, known = G.balance(net, 0), G.balance(net, 200)
        self.assertGreater(wiped, .85)  # memory wiped: the gut leads
        self.assertTrue(.4 < known < .55)  # both full: about even

    def test_the_line_keeps_its_size(self):
        felt = {"defiant": .7, "happy": .4, "irritable": .2, "sad": .1}
        told = G.line(felt, ["喵", "本鲸"], ["lately you are easily shaken"])
        self.assertIn("very defiant, quite happy, a little irritable, lately you are easily shaken", told)
        self.assertNotIn("sad", told)
        self.assertIn("you keep saying 喵, 本鲸", told)
        self.assertEqual(G.line({"calm": .9, "peaceable": .5}), "")  # an ordinary moment says nothing
        self.assertIn("very calm, quite proud", G.line({"calm": .9, "proud": .5}))

    def test_her_slow_levels_move_slowly_and_lean(self):
        tone = G.Tone()
        for _ in range(300):
            tone.feed({"sad": .1, "calm": .5})
        self.assertAlmostEqual(tone.lean({"sad": .1})["sad"], .1)  # one way of asking: nothing off
        for _ in range(112):  # two weeks
            tone.feed({"sad": 1.0, "calm": .5})
        self.assertAlmostEqual(tone.lately["sad"], .55, delta=.05)
        self.assertGreater(tone.lean({"sad": .1})["sad"], .25)
        self.assertEqual(tone.said(), [])
        for _ in range(200):
            tone.feed({"hysterical": .9, "ashamed": .8})
        self.assertEqual(tone.said(), ["lately you are easily shaken", "lately you think little of yourself"])
        self.assertLess(tone.level("composure"), 0)
        again = G.Tone(json.loads(json.dumps(tone.kept())))
        self.assertEqual(again.lean({"sad": .1}), tone.lean({"sad": .1}))

    def test_sensitivity_is_how_hard_it_hits(self):
        felt = {"sad": .3, "happy": 0.0}
        self.assertEqual(G.sensitive(felt, 0), felt)
        self.assertGreater(G.sensitive(felt, 1)["sad"], .45)
        self.assertLess(G.sensitive(felt, -1)["sad"], .2)
        self.assertEqual(G.sensitive(felt, 1)["happy"], 0.0)

    def test_a_word_of_hers_not_an_echo(self):
        marks = G.Marks({"zh": (Counter(), 100)})
        for index in range(20):
            marks.teach("zh", FORM, 1, 85, G.mine("午饭吃了吗", f"吃啦{'今明后昨前大小多少好坏早晚冷热远近高低长'[index]}喵"))
        marks.heads = marks.trained()
        self.assertIn("喵", marks.heads["zh"]["names"])
        self.assertNotIn("吃", marks.heads["zh"]["names"])
        self.assertIn("喵", marks.speaks("zh", FORM, 85))
        self.assertEqual(marks.speaks("en", FORM, 85), [])  # a habit stays in its language

    def test_a_word_she_says_mostly_to_one_person_is_theirs(self):
        marks = G.Marks({"zh": (Counter(), 100)})
        for index in range(30):
            marks.teach("zh", FORM, 1, 85, ["阿杰", "喵"] if index % 2 else ["喵"], "jie" if index % 2 else "sis")
        marks.heads = marks.trained()
        self.assertEqual(marks.heads["zh"]["owners"], {"阿杰": "jie"})
        self.assertIn("阿杰", marks.speaks("zh", FORM, 85, subject="jie"))
        self.assertNotIn("阿杰", marks.speaks("zh", FORM, 85, subject="sis"))
        self.assertNotIn("阿杰", marks.speaks("zh", FORM, 85))  # someone new
        self.assertIn("喵", marks.speaks("zh", FORM, 85))

    def test_a_word_counts_only_in_its_own_writing(self):
        reply = "That is fine nya. 本鲸觉得 ok 😊"
        self.assertTrue({"nya", "fine", "😊"} <= set(G.mine("hi", reply, "en")))
        self.assertFalse([word for word in G.mine("hi", reply, "en") if "本" in word or "鲸" in word])
        self.assertEqual({word for word in G.mine("hi", "好呀 nya にゃ", "zh") if word.isascii() or "に" in word}, set())
        self.assertIn("にゃ", G.mine("hi", "いいにゃ nya", "ja"))
        self.assertNotIn("nya", G.mine("hi", "いいにゃ nya", "ja"))

    def test_notes_and_votes_are_read_strictly(self):
        self.assertEqual(G.written('{"mood": 9, "feel": {"sad": 2, "calm": 0.5, "angry": 9}}'),
                         {"feel": {"calm": .5, "sad": 1.0}, "mood": 2})
        for bad in ("", "no", '{"mood": 1}', '{"feel": {"angry": 1}}', '{"feel": 3}', '{"feel": {"sad": 0}}'):
            self.assertIsNone(G.written(bad))
        self.assertEqual(G.vector('sure {"sad": 1} ok')["sad"], 1.0)
        self.assertEqual(G.vector('{"feel": {"Defiant": 0.7}}')["defiant"], .7)
        self.assertEqual(G.vector('{"feeling": {"irritable": 0.55, "defiant": 0.7}}')["defiant"], .7)  # as DeepSeek wraps it
        self.assertEqual(G.vector('{"feelings": [{"feeling": "calm", "strength": 0.7}, {"name": "shy", "intensity": 0.2}]}')
                         ["shy"], .2)  # and as it lists them
        self.assertEqual(len(G.vector('{"sad": 1}')), 24)
        every = dict.fromkeys(G.ENDS, 0.0) | {"sad": .1, "sweet": .7}
        self.assertEqual(G.written(json.dumps({"mood": -1, "feel": every})), {"feel": {"sad": .1, "sweet": .7}, "mood": -1})
        self.assertTrue(all(f" {end}," in G.NOTE or f" {end}." in G.NOTE for end in G.ENDS))  # her note scores every end
        self.assertIsNone(G.vector('{"sad": "x"}'))


class Kept(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "gut" / "her.db"
        self.addCleanup(self._tmp.cleanup)

    def gut(self, starter=None):
        gut = G.Gut(self.path, starter)
        gut.wake()
        self.addCleanup(gut.close)
        return gut

    def teach(self, gut, count, subject="discord:1", closeness=85, feel=JEALOUS):
        for _ in range(count):
            gut.teach(subject, "zh", FORM, {"feel": feel, "mood": 1}, closeness, ["喵"])

    def test_someone_not_close_teaches_how_she_is_with_them_not_her_heart(self):
        gut = self.gut()
        self.assertFalse(gut.teach("x", "zh", FORM, {"feel": JEALOUS, "mood": 1}, 39.9, ["喵"]))
        found = gut.report()
        self.assertEqual((found["lessons"], found["age"]), (1, 0))
        self.assertEqual(found["people"]["x"]["lessons"], 1)
        self.assertEqual(gut.marks.lessons, [])  # nor her words
        self.teach(gut, 1, closeness=40)
        self.assertEqual(gut.report()["age"], 1)

    def test_she_sleeps_at_20_and_50_and_every_100(self):
        gut = self.gut()
        sleeps = [gut.teach("x", "zh", FORM, {"feel": JEALOUS, "mood": 0}, 85, []) for _ in range(100)]
        self.assertEqual([index + 1 for index, due in enumerate(sleeps) if due], [20, 50, 100])

    def test_she_wakes_as_she_went_to_sleep_with_what_came_after(self):
        gut = self.gut()
        self.teach(gut, 30)
        self.teach(gut, 10, "discord:2", feel={"calm": .9})
        gut.sleep()
        self.teach(gut, 5)
        felt, theirs = gut.net.vector(FORM, 85), gut.net.vector(FORM, 85, "discord:2")
        gut.close()
        again = self.gut()
        self.assertEqual(again.report()["lessons"], 45)
        for name, value in again.net.vector(FORM, 85).items():
            self.assertAlmostEqual(value, felt[name], places=9)
        for name, value in again.net.vector(FORM, 85, "discord:2").items():
            self.assertAlmostEqual(value, theirs[name], places=9)
        self.assertEqual(again.marks.heads.keys(), gut.marks.heads.keys())

    def test_a_person_can_be_forgotten_and_what_is_done_is_done(self):
        gut = self.gut()
        gut.write_side("御姐", "你从容。")
        held = gut.holding()
        self.teach(gut, 30, "discord:1")
        self.teach(gut, 2, "discord:2", feel={"sad": 1.0})
        gut.language("discord:1", {"language": "ja"}, "x")
        gut.sleep()
        heart = gut.net.vector(FORM, 85)
        self.assertEqual(gut.forget("discord:1"), 30)
        self.assertEqual(gut.report()["lessons"], 32)
        self.assertNotIn("discord:1", gut.languages)
        self.assertNotIn("discord:1", gut.report()["people"])
        felt = gut.net.vector(FORM, 85)
        self.assertEqual(felt, heart)
        self.assertGreater(felt["jealous"], .3)  # what they did to her heart stays
        self.assertEqual(gut.net.vector(FORM, 85, "discord:1"), felt)  # and they meet it as someone new
        self.assertEqual(gut.holding(), held)  # her month in a side goes on
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            named = db.execute("select subject, count(*) from lessons group by subject order by subject").fetchall()
        self.assertEqual(named, [("", 30), ("discord:2", 2)])
        gut.close()
        again = self.gut()
        self.assertNotIn("discord:1", again.report()["people"])

    def test_she_answers_in_the_last_language_when_a_message_is_too_short(self):
        gut = self.gut()
        self.assertEqual(gut.language("a", {"language": "ja"}, "x"), "ja")
        self.assertEqual(gut.language("a", {"language": "unclear"}, "ok"), "ja")
        self.assertEqual(gut.language("b", {"language": "unclear"}, "ok"), "")
        self.assertEqual(gut.language("b", None, "今天好累"), "zh")  # no reading: only then the characters decide
        self.assertEqual(gut.language("a", {"language": "en"}, "x"), "en")

    def starter(self, ends=None):
        starter = self.path.parent.parent / "starter.json.gz"
        data = {"rows": [[FORM, "jealous", 1, 85]] * 30 + [[OTHER, "none", 0, 85]] * 30,
                "words": {"zh": {"n": 60, "words": {"的": 40}}}}
        if ends:
            data["rows"] = [[FORM, {"defiant": .9}, 1, 85]] * 30 + [[OTHER, {"calm": .9}, 0, 85]] * 30
            data["ends"] = ends
        with gzip.open(starter, "wt", encoding="utf-8") as file:
            json.dump(data, file)
        return starter

    def test_a_starter_is_a_lean_and_only_a_beginning(self):
        starter = self.starter()
        gut = self.gut(starter)
        felt, other = gut.net.vector(FORM, 85), gut.net.vector(OTHER, 85)
        self.assertGreater(felt["jealous"], other["jealous"] + .1)
        self.assertGreater(other["calm"], felt["calm"] + .1)  # `none` is calm
        self.assertAlmostEqual(felt["defiant"], G.squash(G.BLANK), places=6)  # a starter from 0.4 knew seven
        self.assertEqual(gut.marks.base["zh"][1], 60)
        self.assertEqual(gut.report()["age"], 0)
        gut.close()
        again = self.gut(starter)
        self.assertAlmostEqual(again.net.vector(FORM, 85)["jealous"], felt["jealous"], places=9)

    def test_a_starter_knows_the_ends_it_says(self):
        gut = self.gut(self.starter(list(G.ENDS)))
        self.assertGreater(gut.net.vector(FORM, 85)["defiant"], gut.net.vector(OTHER, 85)["defiant"] + .1)

    def test_a_broken_starter_says_so(self):
        broken = self.path.parent.parent / "broken.json.gz"
        broken.write_bytes(b"not gzip")
        with self.assertRaises(ValueError):
            G.Gut(self.path, broken).wake()
        self.gut(self.path.parent.parent / "none.json.gz")  # no file: a blank gut

    def test_a_file_from_0_4_is_lived_again(self):
        self.path.parent.mkdir(parents=True)
        with contextlib.closing(sqlite3.connect(self.path)) as db, db:
            db.executescript("""
                create table lessons (id integer primary key, subject text not null, at real not null,
                    language text not null, form text not null, feel text not null, mood integer not null,
                    closeness real not null, words text not null);
                create table state (key text primary key, value blob not null);""")
            for index in range(30):
                db.execute("insert into lessons (subject, at, language, form, feel, mood, closeness, words) values "
                           "(?, ?, 'zh', ?, ?, 1, 85, '[]')", ("discord:1", 1.8e9 + index * 3600, json.dumps(FORM),
                                                              json.dumps({"jealous": .8, "sweet": .2})))
            db.execute("insert into state values ('net', ?)", (gzip.compress(b'{"w": {}, "b": [0,0,0,0,0,0,0], "lessons": 30}'),))
            db.execute("insert into state values ('tone', ?)", (gzip.compress(b'{"sad": 0.5}'),))
        gut = self.gut()
        found = gut.report()
        self.assertEqual((found["lessons"], found["age"], found["people"]["discord:1"]["lessons"]), (30, 30, 30))
        self.assertGreater(gut.net.vector(FORM, 85)["jealous"], .5)
        self.assertAlmostEqual(gut.net.vector(FORM, 85)["defiant"], G.squash(G.BLANK), places=6)
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            self.assertEqual({row[0] for row in db.execute("select key from state")}, {"heart"})
            self.assertEqual(db.execute("select distinct ends from lessons").fetchall(), [(7,)])
        gut.teach("discord:1", "zh", FORM, {"feel": {"defiant": .9}, "mood": 1}, 85, [])
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("select ends from lessons order by id desc limit 1").fetchone(), (24,))

    def test_settings_are_hers_and_stay(self):
        gut = self.gut()
        self.assertEqual(gut.configure(tau=300, sensitivity=.5), {"tau": 300.0, "sensitivity": .5, "nudge": {}, "locked": False, "people": {}, "side": None})
        for bad in ({"tau": 0}, {"tau": True}, {"sensitivity": 2}, {"locked": 1}):
            with self.assertRaises(ValueError):
                gut.configure(**bad)
        gut.tune("irritable", nature=-2)
        with self.assertRaises(ValueError):
            gut.tune("angry", now=.3)
        with self.assertRaises(ValueError):
            gut.tune("irritable", nature=4)
        self.assertLess(gut.net.vector(FORM, 85)["irritable"], .01)
        self.teach(gut, 3)
        gut.close()
        again = self.gut()
        self.assertEqual(again.settings, {"tau": 300.0, "sensitivity": .5, "nudge": {"irritable": -2.0}, "locked": False,
                                          "people": {}, "side": None})
        self.assertEqual(again.net.tau, 300.0)
        self.assertLess(again.net.vector(FORM, 85)["irritable"], .01)
        again.tune("irritable", nature=0)
        self.assertEqual(again.settings["nudge"], {})
        again.wipe()
        self.assertEqual(again.settings["tau"], 300.0)  # a wipe takes what she learned, not her settings
        self.assertEqual(again.report()["lessons"], 0)

    def test_her_heart_can_be_locked(self):
        gut = self.gut()
        self.teach(gut, 30)
        gut.configure(locked=True)
        felt, age = gut.net.vector(FORM, 85), gut.net.age
        self.teach(gut, 60, feel={"scornful": .9})
        gut.sleep()
        self.assertEqual((gut.net.vector(FORM, 85), gut.net.age), (felt, age))  # her heart: as it was
        self.assertGreater(gut.net.vector(FORM, 85, "discord:1")["scornful"], .3)  # how she is with them: still learning
        gut.close()
        again = self.gut()
        self.assertTrue(again.report()["locked"])
        again.configure(locked=False)
        self.teach(again, 60, feel={"scornful": .9})
        self.assertGreater(again.net.vector(FORM, 85)["scornful"], felt["scornful"] + .1)

    def test_each_person_by_hand(self):
        gut = self.gut()
        self.teach(gut, 40)
        learned = gut.net.weight("discord:1")
        self.assertEqual(gut.tune_person("discord:1", "sweet", 2.5), {"nudge": {"sweet": 2.5}})
        self.assertGreater(gut.net.vector(FORM, 85, "discord:1")["sweet"], gut.net.vector(FORM, 85, "discord:2")["sweet"] + .3)
        gut.tune_person("discord:1", weight=0)
        self.assertEqual(gut.net.weight("discord:1"), 0.0)
        gut.tune_person("discord:1", weight="learned")
        self.assertAlmostEqual(gut.net.weight("discord:1"), learned)
        for bad in ({"end": "sweet"}, {"end": "angry", "nature": 1}, {"end": "sweet", "nature": 4}, {"weight": 1.5},
                    {"weight": "some"}, {"locked": "yes"}):
            with self.assertRaises(ValueError):
                gut.tune_person("discord:1", **bad)
        gut.tune_person("discord:1", locked=True)
        theirs = gut.net.vector(FORM, 85, "discord:1")
        self.teach(gut, 40, feel={"scornful": .9})
        for day in range(1, 60):  # talking days without them: a locked person does not fade
            gut.teach("discord:2", "zh", OTHER, {"feel": {"calm": .5}, "mood": 0}, 20, [], at=1.8e9 + day * DAY)
        gut.sleep()
        self.assertAlmostEqual(gut.net.weight("discord:1"), learned)
        self.assertAlmostEqual(gut.net.vector(FORM, 85, "discord:1")["sweet"], theirs["sweet"], places=6)
        gut.close()
        again = self.gut()
        self.assertEqual(again.report()["hands"], {"discord:1": {"nudge": {"sweet": 2.5}, "locked": True}})
        again.tune_person("discord:1", "sweet", 0)
        again.tune_person("discord:1", locked=False)
        self.assertEqual(again.settings["people"], {})
        again.tune_person("discord:3", "stern", 1)
        again.forget("discord:3")
        self.assertEqual(again.settings["people"], {})  # forgotten: what was set for them goes too

    def test_a_side_can_be_locked_and_shows_in_its_share_of_turns(self):
        gut = self.gut()
        with self.assertRaises(ValueError):
            gut.lock_side("病娇")  # not hers yet: it needs a sentence
        with self.assertRaises(ValueError):
            gut.lock_side("龙傲天", what="你很狂。")
        with self.assertRaises(ValueError):
            gut.lock_side("病娇", often=2, what="你离不开对方。")
        gut.write_side("御姐", "你从容，不撒娇。", 50.0)
        gut.lock_side("病娇", often=.25, what="你离不开对方，别人一靠近就紧张。")
        self.assertEqual(gut.holding(), ["病娇"])
        rolls = iter([.1, .5, .9, .3] * 10)
        gut.roll = lambda: next(rolls)
        shown = [("病娇" in gut.feel(FORM, None, 10, 0, "zh")["told"]) for _ in range(40)]
        self.assertEqual(sum(shown), 10)  # rolls under .25: one turn in four, and for a stranger too
        later = G.time.time() + 400 * DAY
        self.assertEqual(gut.holding(later), ["病娇"])  # no month ends it
        gut.close()
        again = self.gut()
        self.assertEqual(again.report()["side"], {"name": "病娇", "often": .25})
        again.unlock_side()
        self.assertEqual((again.settings["side"], again.holding()), (None, ["病娇"]))  # a month in it first, then drawn
        again.lock_side("御姐")
        again.drop_side("御姐")
        self.assertIsNone(again.settings["side"])

    def test_the_command_sets_her_dials_and_locks(self):
        from mneme_llm.cli import main

        def run(*args):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["gut", "--file", str(self.path), *args])
            return code, out.getvalue(), err.getvalue().strip()
        self.assertEqual(run("show")[0], 2)  # no file: nothing is made
        gut = self.gut()
        self.teach(gut, 30)
        gut.close()
        self.assertEqual(run("set", "--tau", "200", "--sensitivity", "-0.5", "--lock")[0], 0)
        self.assertEqual(run("tune", "sweet", "--nature", "1.5", "--person", "discord:1")[0], 0)
        self.assertEqual(run("tune", "sad", "--now", "0.4", "--person", "discord:1")[0], 2)
        self.assertEqual(run("person", "discord:1", "--weight", "0.3", "--lock")[1].strip(),
                         '{"nudge": {"sweet": 1.5}, "weight": 0.3, "locked": true}')
        self.assertEqual(run("side", "病娇", "--lock")[2], "病娇 is not one of her sides yet: give it a sentence (what she does)")
        code, out, _ = run("side", "病娇", "--lock", "--often", "0.5", "--what", "你离不开对方。")
        self.assertEqual(json.loads(out)["side"], {"name": "病娇", "often": .5})
        found = json.loads(run("show")[1])
        self.assertEqual((found["tau"], found["sensitivity"], found["locked"], found["held"]), (200.0, -.5, True, ["病娇"]))
        self.assertEqual(run("side", "--unlock")[0], 0)
        self.assertIsNone(json.loads(run("show")[1])["side"])
        self.assertEqual(run("person", "discord:1", "--forget")[1].strip(), "forgotten: 30 lessons lost their name")

    def test_where_she_is_now_fades_as_she_lives(self):
        gut = self.gut()
        gut.tune("sad", now=.5)
        self.assertAlmostEqual(gut.tone.lean({"sad": .1})["sad"], .6)
        vote = dict.fromkeys(G.ENDS, 0.0)
        for _ in range(112):
            gut.feel(FORM, vote, 85, 3, "zh")
        self.assertAlmostEqual(gut.tone.lean({"sad": .1})["sad"], .35, delta=.03)

    def test_an_age_can_be_set_young_again_forgetting_nothing(self):
        gut = self.gut()
        self.teach(gut, 300)
        gut.sleep()
        felt = gut.net.vector(FORM, 85)
        self.assertLess(gut.report()["learning"], .25)
        gut.set_age(0)
        self.assertEqual((gut.report()["age"], gut.report()["learning"]), (0, 1.0))
        self.assertEqual(gut.net.vector(FORM, 85), felt)
        gut.close()
        self.assertEqual(self.gut().report()["age"], 0)


ANSWERS = {"read": json.dumps({**FORM, "language": "en"}), "vote": json.dumps(JEALOUS), "note": json.dumps({"mood": 1, "feel": JEALOUS}),
           "shape": '{"side": null}', "grow": '{"name": "小绿茶", "what": "你先夸她，再（委屈地）让她显得不如你。"}'}


class Model:
    """Her reading, vote and note, each of which can be held back or fail."""

    def __init__(self):
        self.asked, self.fail, self.hold = [], set(), {}

    async def __call__(self, messages, tokens):
        first = messages[0]["content"]
        kind = "read" if first == G.FORM else "shape" if first.startswith(G.SHAPE) else "grow" if "一直想让她变成这样" in first \
            else "vote" if G.ASK in messages[-1]["content"] else "note"
        self.asked.append((kind, messages))
        if kind in self.hold:
            await self.hold[kind].wait()
        if kind in self.fail:
            raise RuntimeError("no")
        return ANSWERS[kind]


class Turns(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.gut = G.Gut(Path(self._tmp.name) / "her.db", tags={"傲娇": "你嘴硬心软。"})
        self.gut.wake()
        self.addCleanup(self.gut.close)
        self.model = Model()

    def turn(self, said="had lunch with a coworker", subject="discord:1"):
        return G.Turn(self.gut, self.model, "You are her.", said, subject)

    async def test_a_turn_from_the_message_to_a_lesson(self):
        turn = self.turn()
        line = await turn.feel([{"role": "user", "content": "earlier"}], "Notes about them.", 85, 3)
        self.assertIn("jealous", line)
        self.assertIn("傲娇", line)
        self.assertIn("Reply in English.", line)
        vote = next(messages for kind, messages in self.model.asked if kind == "vote")
        self.assertIn("Notes about them.", vote[-1]["content"])
        self.assertIn("irritable or peaceable", vote[-1]["content"])
        self.assertEqual(next(messages for kind, messages in self.model.asked if kind == "read")[1]["content"], turn.said)
        self.assertEqual((await turn.learn("Oh, a coworker."))["feel"], {"sweet": .2, "jealous": .8})
        self.assertEqual(self.gut.report()["lessons"], 1)
        self.assertEqual(self.gut.report()["people"]["discord:1"]["lessons"], 1)
        note = next(messages for kind, messages in self.model.asked if kind == "note")
        self.assertIn("Right now you feel", note[0]["content"])  # the line stays in view of her note

    async def test_she_feels_each_person_her_own_way(self):
        for _ in range(60):
            for who, feel in (("discord:1", {"jealous": .9}), ("discord:2", {"calm": .9})):
                if self.gut.teach(who, "en", FORM, {"feel": feel, "mood": 1}, 85, []):
                    self.gut.sleep()
        one, two = (self.gut.feel(FORM, None, 85, 3, "en", who)["felt"] for who in ("discord:1", "discord:2"))
        self.assertGreater(one["jealous"], two["jealous"] + .3)
        self.assertGreater(two["calm"], one["calm"] + .3)
        self.model.fail = {"vote"}
        self.assertIn("very jealous", await self.turn().feel([], "", 85, 3))
        self.assertNotIn("you feel", await self.turn(subject="discord:2").feel([], "", 85, 3))  # calm alone: ordinary

    async def test_she_answers_when_a_call_fails(self):
        self.model.fail = {"read"}
        self.assertIn("very jealous", await self.turn().feel([], "", 85, 3))  # her head alone
        self.model.fail = {"vote"}
        self.assertIn("Reply in English.", await self.turn().feel([], "", 85, 3))
        self.model.fail = {"read", "vote"}
        self.assertEqual(await self.turn("好").feel([], "", 85, 3), "(Right now your 傲娇 side is showing: 你嘴硬心软。) Reply in English.")

    async def test_a_slow_reading_does_not_hold_her_up_and_still_teaches(self):
        limit, G.TIME_LIMIT = G.TIME_LIMIT, .02
        self.addCleanup(setattr, G, "TIME_LIMIT", limit)
        self.model.hold["read"] = asyncio.Event()
        turn = self.turn()
        self.assertIn("very jealous", await turn.feel([], "", 85, 3))
        self.model.hold["read"].set()
        self.assertIsNotNone(await turn.learn("reply"))
        self.assertEqual(self.gut.report()["lessons"], 1)

    async def test_no_note_no_lesson(self):
        ANSWERS_NOTE, ANSWERS["note"] = ANSWERS["note"], "no idea"
        self.addCleanup(ANSWERS.__setitem__, "note", ANSWERS_NOTE)
        turn = self.turn()
        await turn.feel([], "", 85, 3)
        self.assertIsNone(await turn.learn("reply"))
        self.assertEqual(sum(kind == "note" for kind, _ in self.model.asked), 2)
        self.assertEqual(self.gut.report()["lessons"], 0)


class Growing(unittest.IsolatedAsyncioTestCase):
    """A side of hers, grown from what people keep saying they want of her."""

    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "her.db"
        self.gut = G.Gut(self.path)
        self.gut.wake()
        self.addCleanup(lambda: self.gut.close())
        self.model = Model()
        self.addCleanup(ANSWERS.__setitem__, "shape", ANSWERS["shape"])

    def asked(self, name="绿茶", more=True, what="说别的女生不好"):
        ANSWERS["shape"] = json.dumps({"side": {"name": name, "more": more, "what": what}}, ensure_ascii=False)

    async def say(self, closeness=85, subject="discord:1", prompt="You are her."):
        turn = G.Turn(self.gut, self.model, prompt, "她好烦", subject)
        await turn.feel([], "", closeness, 3)
        await turn.learn("reply")
        return turn

    def days(self, count, start=0):
        real = G.time.time
        self.addCleanup(setattr, G.time, "time", real)
        return (lambda day: setattr(G.time, "time", lambda: real() + (start + day) * DAY))

    async def test_the_person_decides_how_long_it_takes(self):
        days = [next(day + 1 for day in range(30) if G.strength([(n * DAY, True, closeness) for n in range(day + 1)], day * DAY) >= G.GROWS)
                for closeness in (100, 85, 60, 40)]
        self.assertEqual(days, [3, 4, 6, 9])

    async def test_one_evening_is_one_sighting(self):
        self.asked()
        for _ in range(12):
            await self.say()
        self.assertEqual(len(self.gut.sightings), 1)
        self.assertEqual(self.gut.report()["sides"], {})

    async def test_four_days_grow_a_side_from_what_they_wanted_and_it_outlasts_her_memory(self):
        move = self.days(5)
        self.asked()
        for day in range(4):
            move(day)
            await self.say()
        self.assertEqual(self.gut.grown, {"小绿茶": "你先夸她，再委屈地让她显得不如你。"})  # no brackets: it goes inside the line
        grow = next(messages for kind, messages in self.model.asked if kind == "grow")
        self.assertIn("- 说别的女生不好", grow[0]["content"])
        self.assertIn("「绿茶」", grow[0]["content"])
        self.assertNotIn("已经有的样子", grow[0]["content"])
        self.assertEqual(self.gut.sightings[0][2], "小绿茶")  # and what taught it goes by the new name
        self.gut.close()
        self.gut = G.Gut(self.path)
        self.gut.wake()
        turn = G.Turn(self.gut, self.model, "Another model entirely.", "嗯", "discord:2")
        self.assertIn("(Right now your 小绿茶 side is showing: 你先夸她", await turn.feel([], "", 60, 0))

    async def test_she_notes_one_thing_under_one_name(self):
        move = self.days(2)
        self.asked()
        await self.say()
        move(1)
        await self.say()
        shape = [messages for kind, messages in self.model.asked if kind == "shape"]
        self.assertEqual(shape[0][0]["content"], G.SHAPE)
        self.assertIn("Sides noted so far: 绿茶 (说别的女生不好)", shape[1][0]["content"])

    async def test_a_stranger_shapes_nothing_and_does_not_meet_it(self):
        self.gut.write_side("御姐", "你从容。")
        self.asked()
        await self.say(closeness=20)
        self.assertEqual(self.gut.sightings, [])
        self.assertFalse(any(kind == "shape" for kind, _ in self.model.asked))
        self.assertNotIn("御姐", await G.Turn(self.gut, self.model, "You are her.", "嗯", "discord:9").feel([], "", 20, 0))
        self.assertIn("御姐", await G.Turn(self.gut, self.model, "You are her.", "嗯", "discord:9").feel([], "", 40, 0))

    async def test_family_gets_there_before_a_friend(self):
        move = self.days(5)
        self.asked()
        for day in range(4):
            move(day)
            await self.say(closeness=60)
        self.assertEqual(self.gut.grown, {})
        for day in range(4, 6):
            move(day)
            await self.say(closeness=60)
        self.assertEqual(list(self.gut.grown), ["小绿茶"])

    async def test_who_she_already_is_is_no_side(self):
        self.asked("傲娇")
        await self.say(prompt="你是个傲娇的鲸。")
        self.assertEqual(self.gut.sightings, [])

    async def test_objecting_takes_it_away_and_does_not_wait_for_tomorrow(self):
        move = self.days(5)
        self.asked()
        for day in range(4):
            move(day)
            await self.say()
        self.assertIn("小绿茶", self.gut.grown)
        self.asked("端着", more=False, what="别这样")  # (not the name she keeps it under: they rarely know it)
        for _ in range(3):
            await self.say()
        self.assertIn("小绿茶", self.gut.grown)
        await self.say()
        self.assertEqual(self.gut.grown, {})
        self.assertEqual(self.gut.sightings, [])

    async def test_a_side_wanted_for_months_goes_as_easily(self):
        self.gut.grow("x", {"name": "御姐", "what": "你从容。"})
        for day in range(60):
            self.gut.sighted("a", {"name": "御姐", "more": True, "what": ""}, 85, now=day * DAY)
        for _ in range(4):
            self.gut.sighted("a", {"name": "别这样", "more": False, "what": ""}, 85, now=60 * DAY)
        self.assertEqual(self.gut.grown, {})

    async def test_a_new_word_for_a_side_she_has_joins_it(self):
        move = self.days(9)
        self.gut.write_side("小绿茶", "你先夸她。")
        self.gut.sighted("a", {"name": "小绿茶", "more": True, "what": ""}, 85)
        self.asked("ぶりっ子")
        for day in range(4):
            move(day)
            await self.say()
        grow = next(messages for kind, messages in self.model.asked if kind == "grow")
        self.assertIn("她已经有的样子：小绿茶（你先夸她。）", grow[0]["content"])
        self.assertEqual(list(self.gut.grown), ["小绿茶"])  # (what Model answers: the same word)
        self.assertEqual({row[2] for row in self.gut.sightings}, {"小绿茶"})

    async def test_a_sentence_like_one_of_hers_is_that_side_whatever_it_is_called(self):
        self.gut.grow("绿茶", {"name": "小绿茶", "what": "你别人一提旁人你就软软贬一句酸酸比一句，装弱装无辜不争不抢。"})
        self.gut.sighted("a", {"name": "pick-me", "more": True, "what": "x"}, 85)
        self.gut.grow("pick-me", {"name": "pick-me", "what": "你别人一提旁人你就软软贬一句酸酸比一句，还偶尔多酸一点。"})
        self.assertEqual(list(self.gut.grown), ["小绿茶"])
        self.assertIn("还偶尔多酸一点", self.gut.grown["小绿茶"])
        self.assertEqual(self.gut.sightings[0][2], "小绿茶")
        self.gut.grow("御姐", {"name": "御姐", "what": "你从容，从上往下逗对方。"})
        self.assertEqual(list(self.gut.grown), ["小绿茶", "御姐"])

    def two(self):
        self.gut.write_side("御姐", "你从容。", 3)
        self.gut.write_side("病娇", "你只要他。", 1)

    async def test_she_stays_in_one_side_for_a_month(self):
        self.two()
        start = G.time.time()
        first = self.gut.holding(start)
        self.assertEqual(len(first), 1)
        self.assertEqual({tuple(self.gut.holding(start + day * DAY)) for day in range(30)}, {tuple(first)})
        self.assertEqual(len(self.gut.shown(85, start)), 1)
        self.assertEqual(G.sides(self.gut.shown(85, start)).count("side is showing"), 1)
        self.gut.close()
        self.gut = G.Gut(self.path)
        self.gut.wake()
        self.assertEqual(self.gut.holding(start + 20 * DAY), first)  # a restart is not a new month

    async def test_a_month_on_her_sides_are_drawn_again_by_weight(self):
        self.two()
        start, months = G.time.time(), Counter()
        self.gut.holding(start)
        for month in range(1, 2001):
            months[self.gut.holding(start + month * G.HOLD)[0]] += 1
        self.assertAlmostEqual(months["御姐"] / 2000, .75, delta=.04)

    async def test_being_asked_for_a_new_side_waits_for_the_month_and_what_people_asked_counts_for_months(self):
        self.gut.grow("x", {"name": "御姐", "what": "你从容。"})
        start = G.time.time()
        self.gut.holding(start)
        self.gut.grow("y", {"name": "病娇", "what": "你只要他。"})
        for day in range(9):
            self.gut.sighted("a", {"name": "病娇", "more": True, "what": ""}, 85, now=start + day * DAY)
        self.assertEqual(self.gut.holding(start + 29 * DAY), ["御姐"])
        now = start + 9 * DAY
        self.assertAlmostEqual(self.gut.weight("病娇", now + 90 * DAY), self.gut.weight("病娇", now) / 2, delta=.2)

    async def test_a_side_she_is_in_going_away_ends_the_month(self):
        self.two()
        start = G.time.time()
        held = self.gut.holding(start)[0]
        self.gut.drop_side(held)
        self.assertEqual(self.gut.holding(start + DAY), list(self.gut.grown))

    async def test_objecting_is_about_the_side_she_is_in(self):
        self.gut.write_side("御姐", "你从容。", 1)
        start = G.time.time()
        self.gut.holding(start)
        self.gut.write_side("病娇", "你只要他。", 50)
        self.gut.sighted("a", {"name": "端着", "more": False, "what": ""}, 85, now=start)
        self.assertEqual(self.gut.sightings[0][2], "御姐")

    async def test_a_side_nobody_asks_for_any_more_stays_until_someone_objects(self):
        self.gut.grow("x", {"name": "御姐", "what": "你从容。"})
        self.assertEqual(self.gut.holding(G.time.time() + 3000 * DAY), ["御姐"])

    async def test_a_side_only_takes_a_name_on_the_list(self):
        self.asked("草莓")
        self.addCleanup(ANSWERS.__setitem__, "grow", ANSWERS["grow"])
        ANSWERS["grow"] = '{"name": "草莓", "what": "你很甜。"}'
        move = self.days(6)
        for day in range(4):
            move(day)
            await self.say()
        self.assertEqual(self.gut.grown, {})
        self.assertEqual(len(self.gut.sightings), 4)
        grow = next(messages for kind, messages in self.model.asked if kind == "grow")
        self.assertIn("小绿茶", grow[0]["content"])
        ANSWERS["grow"] = '{"name": null, "what": "你很甜。"}'
        move(4)
        await self.say()
        self.assertEqual(self.gut.grown, {})
        with self.assertRaises(ValueError):
            self.gut.write_side("草莓", "x")
        with self.assertRaises(ValueError):
            G.Gut(self.path, tags={"草莓": "x"})
        self.assertEqual(G.Gut(self.path, tags={"草莓": "x"}, names=("草莓",)).tags, {"草莓": "x"})

    async def test_a_side_she_was_given_is_for_everyone_and_weighs_as_one_that_grew(self):
        gut = G.Gut(Path(self._tmp.name) / "given.db", tags={"傲娇": "你嘴硬。"})
        gut.wake()
        self.addCleanup(gut.close)
        self.assertEqual(gut.shown(0), {"傲娇": "你嘴硬。"})
        self.assertAlmostEqual(gut.weight("傲娇"), G.GROWS)

    async def test_a_person_forgotten_takes_what_only_they_wanted(self):
        self.gut.grow("x", {"name": "御姐", "what": "1"})
        self.gut.grow("y", {"name": "病娇", "what": "2"})
        self.gut.write_side("三无", "3")
        self.gut.sighted("a", {"name": "御姐", "more": True, "what": ""}, 85)
        self.gut.sighted("a", {"name": "病娇", "more": True, "what": ""}, 85)
        self.gut.sighted("b", {"name": "病娇", "more": True, "what": ""}, 85)
        self.gut.forget("a")
        self.assertEqual(set(self.gut.grown), {"病娇", "三无"})
        self.assertEqual([row[0] for row in self.gut.sightings], ["b"])

    async def test_a_person_can_rewrite_or_remove_a_side(self):
        self.gut.grow("x", {"name": "御姐", "what": "draft"})
        self.gut.write_side("御姐", "你从容。")
        found = self.gut.report()
        self.assertEqual((found["sides"], found["held"], found["days"], found["weights"]), ({"御姐": "你从容。"}, ["御姐"], 30, {"御姐": G.GROWS}))
        self.gut.write_side("御姐", "你从容。", 2)
        self.gut.grow("x", {"name": "御姐", "what": "你很从容。"})
        self.gut.close()
        self.gut = G.Gut(self.path)
        self.gut.wake()
        self.assertEqual(self.gut.weights, {"御姐": 2})  # growing again does not take off what a person set
        self.assertTrue(self.gut.drop_side("御姐"))
        self.assertFalse(self.gut.drop_side("御姐"))

    async def test_a_failed_reading_of_the_person_loses_no_lesson(self):
        self.model.fail = {"shape"}
        self.assertIsNotNone((await self.say()) and self.gut.last.get("note"))
        self.assertEqual(self.gut.report()["lessons"], 1)

    async def test_a_sentence_that_does_not_come_is_asked_for_again(self):
        move = self.days(6)
        self.addCleanup(ANSWERS.__setitem__, "grow", ANSWERS["grow"])
        ANSWERS["grow"], self.model.fail = "no idea", set()
        self.asked()
        for day in range(4):
            move(day)
            await self.say()
        self.assertEqual(self.gut.grown, {})
        ANSWERS["grow"] = '{"name": "小绿茶", "what": "你先夸她。"}'
        move(4)
        await self.say()
        self.assertEqual(list(self.gut.grown), ["小绿茶"])


class Draft(unittest.IsolatedAsyncioTestCase):
    async def test_her_model_drafts_the_sentence(self):
        asked = []

        async def ask(messages, tokens):
            asked.append(messages)
            return "  你话很少。\n"
        self.assertEqual(await G.draft("三无", ask), "你话很少。")
        self.assertIn("「三无」", asked[0][0]["content"])


class Sides(unittest.TestCase):
    def test_a_name_and_a_sentence(self):
        self.assertEqual(G.sides({"御姐": "你从容。"}), "(Right now your 御姐 side is showing: 你从容。)")
        self.assertEqual(G.sides({}), "")

    def test_a_draw_goes_by_weight(self):
        rolls = iter((.1, .9, .5))
        self.assertEqual(G.draw({"a": 3.0, "b": 1.0}, 1, lambda: next(rolls)), ["a"])
        self.assertEqual(G.draw({"a": 3.0, "b": 1.0}, 1, lambda: next(rolls)), ["b"])
        self.assertEqual(G.draw({"a": 3.0, "b": 1.0}, 2, lambda: .5), ["a", "b"])
        self.assertEqual(G.draw({}, 1), [])


class Vectors(unittest.TestCase):
    """tests/gut_vectors.json pins the numbers, for this file and for a port in another language."""

    def test_the_numbers_stay(self):
        path = Path(__file__).with_name("gut_vectors.json")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), vectors())


def vectors() -> dict:
    forms = [{"people": ["coworker"], "gender": ["woman"], "topic": ["lunch"], "event": ["ate"], "sender_feels": "happy", "toward_you": "none"},
             {"people": [], "gender": [], "topic": ["rain", "Bus"], "event": ["got wet"], "sender_feels": "tired", "toward_you": "asking"},
             {"people": ["mother"], "gender": ["woman"], "topic": ["health"], "event": ["fell"], "sender_feels": "worried", "toward_you": "affection"}]
    feels = [{"jealous": .7, "sweet": .3}, {"tender": 1.0, "defiant": .4}, {"worried": .6, "sad": .4, "aching": .5}]
    rounded = lambda value: {key: round(item, 9) for key, item in value.items()}
    out = {"tags": [G.tags(form) for form in forms],
           "features": [rounded(G.features(form, closeness)) for form in forms for closeness in (10, 40, 85)],
           "ends": list(G.ENDS), "feelings": G.FEELINGS}
    net = G.Net()
    net.start([(forms[index % 3], feels[index % 3], index % 3 - 1, (85, 50, 20)[index % 3]) for index in range(12)], G.OLD)
    for index in range(30):
        net.teach("abc"[index % 3], forms[index % 3], feels[index % 3], index % 3 - 1, (85, 50, 20)[index % 3], G.ENDS, index // 4)
        if index == 19:
            net.sleep()
    out["after 30 lessons"] = [rounded(net.vector(form, closeness, who)) for form in forms for closeness in (10, 85) for who in (None, "a", "c")]
    out["weights"] = [round(net.weight(who), 9) for who in "abcd"]
    out["learning"] = round(net.learning(), 9)
    out["balance"] = [round(G.balance(net, exchanges), 9) for exchanges in (0, 5, 200)]
    tone = G.Tone()
    tone.shift["proud"] = .3
    for index in range(50):
        tone.feed(feels[index % 3], (0, .5)[index % 2])
    out["tone"] = {"lately": rounded(tone.lately), "usual": rounded(tone.usual), "shift": rounded(tone.shift)}
    out["lean"] = rounded(tone.lean(dict.fromkeys(G.ENDS, .1)))
    out["said"] = tone.said()
    out["sensitive"] = [rounded(G.sensitive({"sad": .3, "happy": .7}, sensitivity)) for sensitivity in (-1, -.5, .5, 1)]
    out["lines"] = [G.line({"defiant": .7, "happy": .4, "irritable": .2, "sad": .1}, ["喵", "本鲸"], ["lately you are easily shaken"]),
                    G.line({"calm": .9}), G.line({"happy": .6, "calm": .2, "sad": .2})]
    out["written"] = [G.written('{"mood": 9, "feel": {"sad": 2, "calm": 0.5, "angry": 9}}'), G.written('{"feel": {"angry": 1}}')]
    out["vector"] = [G.vector('{"feel": {"Defiant": 0.7, "sad": 3}}'), G.vector('{"sad": 0}'),
                     G.vector('{"feeling": {"irritable": 0.55, "cheeky": 0.6}}'),
                     G.vector('{"feelings": [{"feeling": "calm", "strength": 0.7}, {"name": "shy", "intensity": 0.2}]}')]
    out["mine"] = [G.mine("午饭吃了吗", "吃啦喵 nya", "zh"), G.mine("hi there", "Fine nya 本鲸 😊", "en"), G.mine("元気", "いいにゃ nya", "ja")]
    out["languages"] = [G.language_of(text) for text in ("今天好累", "今日好攰", "おはよう", "hello")]
    out["strength"] = [round(G.strength([(0, True, closeness), (86400, True, closeness), (2 * 86400, False, 60)], 10 * 86400), 9)
                       for closeness in (40, 60, 85, 100)]
    out["shaping"] = [G.shaping(text) for text in ('{"side": null}', 'nothing', '{"side": {"name": " 「小 绿茶」 ", "more": false, "what": " 说 她\\n不好 "}}',
                                                   '{"side": {"name": "御姐", "what": "' + "从容" * 40 + '"}}', '{"side": {"name": ""}}')]
    out["strength over months"] = [round(G.strength([(0, True, closeness), (2 * 86400, False, 60)], 100 * 86400, G.KEEPS), 9) for closeness in (40, 85)]
    out["draw"] = [G.draw({"御姐": 3.0, "病娇": 1.0, "三无": .5}, count, lambda: roll) for count, roll in ((1, 0), (1, .5), (1, .99), (2, .5), (5, .2))]
    out["names"] = list(G.NAMES)
    out["overlap"] = [round(G.overlap(one, other), 9) for one, other in (("你先夸她，再让她不如你。", "你先夸她，再 让她不如你！"), ("你从容。", "你先夸她。"), ("", "x"))]
    out["grown side"] = [G.grown_side(text) for text in ('{"name": "（御姐）", "what": "你从容（不急）\\n，不撒娇。"}', '{"name": "x"}', 'no')]
    return out


if __name__ == "__main__":
    unittest.main()

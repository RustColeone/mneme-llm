"""Tests for the gut (mneme_llm/gut.py): what stays of a companion without her memory or her model."""

import asyncio
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


class Item:
    def __init__(self, direction, text, name=""):
        self.direction, self.text, self.sender_name, self.kind = direction, text, name, "text"


class Parts(unittest.TestCase):
    def test_seven_numbers_that_add_up(self):
        felt = G.Net().vector(FORM, 85)
        self.assertEqual(tuple(felt), G.MOODS)
        self.assertAlmostEqual(sum(felt.values()), 1.0)

    def test_a_lesson_is_a_blend_and_closeness_crosses_the_tags(self):
        net = G.Net()
        for _ in range(60):
            net.teach(FORM, JEALOUS, 1, 85)
        net.sleep()
        self.assertGreater(net.vector(FORM, 85)["jealous"], .5)
        self.assertGreater(net.vector(FORM, 85)["sweet"], net.vector(FORM, 85)["calm"])
        self.assertLess(net.vector(OTHER, 10)["jealous"], net.vector(FORM, 85)["jealous"])  # (not for everything)
        self.assertIn("high:people=coworker", G.features(FORM, 85))

    def test_the_balance_moves_by_itself(self):
        net = G.Net()
        self.assertEqual(G.balance(net, 0), 0.0)  # nothing lived: her head alone
        net.lessons = [None] * 1100
        wiped, known = G.balance(net, 0), G.balance(net, 200)
        self.assertGreater(wiped, .85)  # memory wiped: the gut leads
        self.assertTrue(.4 < known < .55)  # both full: about even

    def test_the_line_keeps_its_size(self):
        felt = {"jealous": .4, "sweet": .3, "tender": .2, "happy": .1}
        told = G.line(felt, ["喵", "本鲸"])
        self.assertIn("somewhat jealous, somewhat sweet, a little tender", told)
        self.assertNotIn("happy", told)
        self.assertIn("you keep saying 喵, 本鲸", told)
        self.assertEqual(G.line({"calm": .9}), "")  # calm says nothing

    def test_her_tone_moves_slowly_and_leans(self):
        tone = G.Tone()
        for _ in range(112):  # two weeks
            tone.feed({"sad": 1.0})
        self.assertAlmostEqual(tone.v["sad"], .5, delta=.03)
        self.assertGreater(tone.lean(G.NORMAL)["sad"], G.NORMAL["sad"])
        self.assertAlmostEqual(sum(tone.lean(G.NORMAL).values()), 1.0)

    def test_a_word_of_hers_not_an_echo(self):
        marks = G.Marks({"zh": (Counter(), 100)})
        for index in range(20):
            marks.teach("zh", FORM, 1, 85, G.mine("午饭吃了吗", f"吃啦{'今明后昨前大小多少好坏早晚冷热远近高低长'[index]}喵"))
        marks.heads = marks.trained()
        self.assertIn("喵", marks.heads["zh"]["names"])
        self.assertNotIn("吃", marks.heads["zh"]["names"])
        self.assertIn("喵", marks.speaks("zh", FORM, 85))
        self.assertEqual(marks.speaks("en", FORM, 85), [])  # a habit stays in its language

    def test_a_word_counts_only_in_its_own_writing(self):
        reply = "That is fine nya. 本鲸觉得 ok 😊"
        self.assertTrue({"nya", "fine", "😊"} <= set(G.mine("hi", reply, "en")))
        self.assertFalse([word for word in G.mine("hi", reply, "en") if "本" in word or "鲸" in word])
        self.assertEqual({word for word in G.mine("hi", "好呀 nya にゃ", "zh") if word.isascii() or "に" in word}, set())
        self.assertIn("にゃ", G.mine("hi", "いいにゃ nya", "ja"))
        self.assertNotIn("nya", G.mine("hi", "いいにゃ nya", "ja"))

    def test_her_normal_is_her_own(self):
        self.assertAlmostEqual(G.usual([({}, {"sad": 1.0}, 0, 85), ({}, {"sad": .5, "calm": .5}, 0, 85)])["sad"], .75)
        self.assertIsNone(G.usual([({}, "sad", 0, 85)]))
        tone = G.Tone(normal={**G.NORMAL, "worried": .3})
        self.assertAlmostEqual(tone.lean({**G.NORMAL, "worried": .3})["worried"], .3 / sum({**G.NORMAL, "worried": .3}.values()))

    def test_notes_and_votes_are_read_strictly(self):
        self.assertEqual(G.written('{"mood": 9, "feel": {"sad": 2, "calm": 2, "angry": 9}}'),
                         {"feel": {"calm": .5, "sad": .5}, "mood": 2})
        for bad in ("", "no", '{"mood": 1}', '{"feel": {"angry": 1}}', '{"feel": 3}'):
            self.assertIsNone(G.written(bad))
        self.assertEqual(G.vector('sure {"sad": 1} ok')["sad"], 1.0)
        self.assertIsNone(G.vector('{"sad": "x"}'))

    def test_what_came_before_the_message(self):
        item = lambda direction, text, name="": Item(direction, text, name)
        items = [item("in", "a"), item("out", "b", "Her"), item("out", "c", "Other"), item("in", "now"), item("out", "reply", "Her")]
        self.assertEqual(G.earlier(items, "now", "Her"), [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
                                                          {"role": "user", "content": "c"}])


class Kept(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "gut" / "her.db"
        self.addCleanup(self._tmp.cleanup)

    def gut(self):
        gut = G.Gut(self.path)
        gut.wake()
        self.addCleanup(gut.close)
        return gut

    def teach(self, gut, count, subject="discord:1", closeness=85):
        for _ in range(count):
            gut.teach(subject, "zh", FORM, {"feel": JEALOUS, "mood": 1}, closeness, ["喵"])

    def test_strangers_teach_nothing(self):
        gut = self.gut()
        self.assertFalse(gut.teach("x", "zh", FORM, {"feel": JEALOUS, "mood": 1}, 39.9, []))
        self.assertEqual(gut.report()["lessons"], 0)
        self.teach(gut, 1, closeness=40)
        self.assertEqual(gut.report()["lessons"], 1)

    def test_she_sleeps_at_20_and_50_and_every_100(self):
        gut = self.gut()
        sleeps = [gut.teach("x", "zh", FORM, {"feel": JEALOUS, "mood": 0}, 85, []) for _ in range(100)]
        self.assertEqual([index + 1 for index, due in enumerate(sleeps) if due], [20, 50, 100])

    def test_she_wakes_as_she_went_to_sleep_with_what_came_after(self):
        gut = self.gut()
        self.teach(gut, 30)
        gut.sleep()
        self.teach(gut, 5)
        felt = gut.net.vector(FORM, 85)
        gut.close()
        again = self.gut()
        self.assertEqual(again.report()["lessons"], 35)
        for name, value in again.net.vector(FORM, 85).items():
            self.assertAlmostEqual(value, felt[name], places=6)
        self.assertEqual(again.marks.heads.keys(), gut.marks.heads.keys())

    def test_a_person_can_be_forgotten(self):
        gut = self.gut()
        self.teach(gut, 30, "discord:1")
        for _ in range(2):
            gut.teach("discord:2", "zh", OTHER, {"feel": {"sad": 1.0}, "mood": 0}, 85, [])
        gut.language("discord:1", {"language": "ja"}, "x")
        gut.sleep()
        self.assertGreater(gut.net.vector(FORM, 85)["jealous"], .5)
        self.assertEqual(gut.forget("discord:1"), 30)
        self.assertEqual(gut.report()["lessons"], 2)
        self.assertNotIn("discord:1", gut.languages)
        self.assertLess(gut.net.vector(FORM, 85)["jealous"], .1)
        rows = sqlite3.connect(self.path).execute("select count(*) from lessons where subject = 'discord:1'").fetchone()
        self.assertEqual(rows[0], 0)

    def test_she_answers_in_the_last_language_when_a_message_is_too_short(self):
        gut = self.gut()
        self.assertEqual(gut.language("a", {"language": "ja"}, "x"), "ja")
        self.assertEqual(gut.language("a", {"language": "unclear"}, "ok"), "ja")
        self.assertEqual(gut.language("b", {"language": "unclear"}, "ok"), "")
        self.assertEqual(gut.language("b", None, "今天好累"), "zh")  # no reading: only then the characters decide
        self.assertEqual(gut.language("a", {"language": "en"}, "x"), "en")

    def test_a_lean_starter_is_only_a_beginning(self):
        starter = self.path.parent.parent / "starter.json.gz"
        import gzip
        with gzip.open(starter, "wt", encoding="utf-8") as file:
            json.dump({"rows": [[FORM, "jealous", 1, 85]] * 30 + [[OTHER, "none", 0, 85]] * 30,
                       "words": {"zh": {"n": 60, "words": {"的": 40}}}}, file)
        gut = G.Gut(self.path, starter)
        gut.wake()
        self.addCleanup(gut.close)
        self.assertGreater(gut.net.vector(FORM, 85)["jealous"], .5)
        self.assertGreater(gut.net.vector(OTHER, 85)["calm"], .5)  # `none` is calm: seven numbers
        self.assertEqual(gut.marks.base["zh"][1], 60)
        self.assertLess(gut.report()["starter"], .61)
        self.assertEqual(gut.report()["born"], 60)
        felt = gut.net.vector(FORM, 85)
        gut.close()
        again = G.Gut(self.path, starter)
        again.wake()
        self.addCleanup(again.close)
        self.assertEqual(again.report()["born"], 60)
        self.assertAlmostEqual(again.net.vector(FORM, 85)["jealous"], felt["jealous"], places=6)


ANSWERS = {"read": json.dumps({**FORM, "language": "en"}), "vote": json.dumps(JEALOUS), "note": json.dumps({"mood": 1, "feel": JEALOUS})}


class Model:
    """Her reading, vote and note, each of which can be held back or fail."""

    def __init__(self):
        self.asked, self.fail, self.hold = [], set(), {}

    async def __call__(self, messages, tokens):
        kind = "read" if messages[0]["content"] == G.FORM else "vote" if G.ASK in messages[-1]["content"] else "note"
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

    def turn(self, said="had lunch with a coworker"):
        return G.Turn(self.gut, self.model, "You are her.", said, "discord:1")

    async def test_a_turn_from_the_message_to_a_lesson(self):
        turn = self.turn()
        line = await turn.feel([{"role": "user", "content": "earlier"}], "Notes about them.", 85, 3)
        self.assertIn("mostly jealous", line)
        self.assertIn("傲娇", line)
        self.assertIn("Reply in English.", line)
        vote = next(messages for kind, messages in self.model.asked if kind == "vote")
        self.assertIn("Notes about them.", vote[-1]["content"])
        self.assertEqual(next(messages for kind, messages in self.model.asked if kind == "read")[1]["content"], turn.said)
        self.assertEqual((await turn.learn([], "Oh, a coworker."))["feel"], {"sweet": .2, "jealous": .8})
        self.assertEqual(self.gut.report()["lessons"], 1)
        note = next(messages for kind, messages in self.model.asked if kind == "note")
        self.assertIn("Right now you feel", note[0]["content"])  # the line stays in view of her note

    async def test_she_answers_when_a_call_fails(self):
        self.model.fail = {"read"}
        self.assertIn("mostly jealous", await self.turn().feel([], "", 85, 3))  # her head alone
        self.model.fail = {"vote"}
        self.assertIn("Reply in English.", await self.turn().feel([], "", 85, 3))
        self.model.fail = {"read", "vote"}
        self.assertEqual(await self.turn("好").feel([], "", 85, 3), "(Right now your 傲娇 side is showing: 你嘴硬心软。) Reply in English.")

    async def test_a_slow_reading_does_not_hold_her_up_and_still_teaches(self):
        limit, G.TIME_LIMIT = G.TIME_LIMIT, .02
        self.addCleanup(setattr, G, "TIME_LIMIT", limit)
        self.model.hold["read"] = asyncio.Event()
        turn = self.turn()
        self.assertIn("mostly jealous", await turn.feel([], "", 85, 3))
        self.model.hold["read"].set()
        self.assertIsNotNone(await turn.learn([], "reply"))
        self.assertEqual(self.gut.report()["lessons"], 1)

    async def test_no_note_no_lesson(self):
        ANSWERS_NOTE, ANSWERS["note"] = ANSWERS["note"], "no idea"
        self.addCleanup(ANSWERS.__setitem__, "note", ANSWERS_NOTE)
        turn = self.turn()
        await turn.feel([], "", 85, 3)
        self.assertIsNone(await turn.learn([], "reply"))
        self.assertEqual(sum(kind == "note" for kind, _ in self.model.asked), 2)
        self.assertEqual(self.gut.report()["lessons"], 0)


class Draft(unittest.IsolatedAsyncioTestCase):
    async def test_her_model_drafts_the_sentence(self):
        asked = []

        async def ask(messages, tokens):
            asked.append(messages)
            return "  你话很少。\n"
        self.assertEqual(await G.draft("三无", ask), "你话很少。")
        self.assertIn("「三无」", asked[0][0]["content"])


class Sides(unittest.TestCase):
    def test_a_name_and_a_sentence_and_at_most_two(self):
        self.assertEqual(G.sides({"御姐": "你从容。"}), "(Right now your 御姐 side is showing: 你从容。)")
        self.assertEqual(G.sides({}), "")
        self.assertEqual(G.sides({"a": "1", "b": "2", "c": "3"}).count("side is showing"), 2)


class Vectors(unittest.TestCase):
    """tests/gut_vectors.json pins the numbers, for this file and for a port in another language."""

    def test_the_numbers_stay(self):
        path = Path(__file__).with_name("gut_vectors.json")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), vectors())


def vectors() -> dict:
    forms = [{"people": ["coworker"], "gender": ["woman"], "topic": ["lunch"], "event": ["ate"], "sender_feels": "happy", "toward_you": "none"},
             {"people": [], "gender": [], "topic": ["rain", "Bus"], "event": ["got wet"], "sender_feels": "tired", "toward_you": "asking"},
             {"people": ["mother"], "gender": ["woman"], "topic": ["health"], "event": ["fell"], "sender_feels": "worried", "toward_you": "affection"}]
    feels = [{"jealous": .7, "sweet": .3}, {"tender": 1.0}, {"worried": .6, "sad": .4}]
    rounded = lambda value: {key: round(item, 9) for key, item in value.items()}
    out = {"tags": [G.tags(form) for form in forms],
           "features": [rounded(G.features(form, closeness)) for form in forms for closeness in (10, 40, 85)]}
    net = G.Net()
    for index in range(30):
        form = forms[index % 3]
        net.teach(form, feels[index % 3], index % 3 - 1, (85, 50, 41)[index % 3])
    out["after 30 lessons"] = [rounded(net.vector(form, closeness)) for form in forms for closeness in (10, 85)]
    out["balance"] = [round(G.balance(net, exchanges), 9) for exchanges in (0, 5, 200)]
    tone = G.Tone()
    for index in range(50):
        tone.feed(feels[index % 3])
    out["tone"] = rounded(tone.v)
    out["lean"] = rounded(tone.lean(G.NORMAL))
    out["lines"] = [G.line({"jealous": .4, "sweet": .3, "tender": .2, "happy": .1}, ["喵", "本鲸"]), G.line({"calm": .9}),
                    G.line({"happy": .6, "calm": .2, "sad": .2})]
    out["mine"] = [G.mine("午饭吃了吗", "吃啦喵 nya", "zh"), G.mine("hi there", "Fine nya 本鲸 😊", "en"), G.mine("元気", "いいにゃ nya", "ja")]
    out["written"] = [G.written('{"mood": 9, "feel": {"sad": 2, "calm": 2, "angry": 9}}'), G.written('{"feel": {"angry": 1}}')]
    out["languages"] = [G.language_of(text) for text in ("今天好累", "今日好攰", "おはよう", "hello")]
    return out


if __name__ == "__main__":
    unittest.main()

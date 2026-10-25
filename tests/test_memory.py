import json
import unittest
from datetime import datetime, timezone

from mneme_llm import Mneme
from mneme_llm.dates import when
from mneme_llm.memory import Memory
from mneme_llm.store import Store
from mneme_llm.text import terms

DAY = 86400
UTC = timezone.utc


class Clock:
    def __init__(self, at: float = datetime(2026, 10, 24, 12, tzinfo=UTC).timestamp()):
        self.now = at

    def __call__(self) -> float:
        return self.now


def memory(**options) -> tuple[Memory, Clock]:
    clock = Clock()
    return Memory(Store(":memory:"), "test", zone=UTC, clock=clock, **options), clock


class TextTests(unittest.TestCase):
    def test_cjk_becomes_overlapping_pairs_and_latin_words_are_trimmed(self):
        self.assertEqual(terms("考试没考好"), ["考试", "试没", "没考", "考好"])
        self.assertEqual(terms("She likes the cats"), ["like", "cat"])

    def test_doubled_characters_that_are_words_stay(self):
        self.assertEqual(terms("谢谢妈妈"), ["谢谢", "谢妈", "妈妈"])
        self.assertEqual(terms("哈哈哈"), [])

    def test_function_words_are_dropped(self):
        self.assertNotIn("什么", terms("你在干什么"))
        self.assertNotIn("the", terms("the exam"))


class DateTests(unittest.TestCase):
    def test_human_dates(self):
        now = datetime(2026, 10, 24, 12, tzinfo=UTC).timestamp()
        self.assertEqual(when(now - 3600, now, UTC), "today")
        self.assertEqual(when(now - DAY, now, UTC, "zh"), "昨天")
        self.assertEqual(when(now - 3 * DAY, now, UTC), "3 days ago")
        self.assertEqual(when(datetime(2026, 9, 17, tzinfo=UTC).timestamp(), now, UTC), "09-17")
        self.assertEqual(when(datetime(2025, 9, 17, tzinfo=UTC).timestamp(), now, UTC, "zh"), "去年 09-17")
        self.assertEqual(when(datetime(2023, 1, 2, tzinfo=UTC).timestamp(), now, UTC), "2023-01-02")

    def test_plans_ahead(self):
        now = datetime(2026, 10, 24, 12, tzinfo=UTC).timestamp()
        self.assertEqual(when(now + DAY, now, UTC), "tomorrow")
        self.assertEqual(when(now + 2 * DAY, now, UTC, "zh"), "后天")
        self.assertEqual(when(now + 6 * DAY, now, UTC), "in 6 days")
        self.assertEqual(when(now + 3 * DAY, now, UTC, "zh"), "3天后")
        self.assertEqual(when(datetime(2026, 12, 25, tzinfo=UTC).timestamp(), now, UTC), "12-25")
        self.assertEqual(when(datetime(2027, 3, 1, tzinfo=UTC).timestamp(), now, UTC, "zh"), "明年 03-01")


class RememberTests(unittest.TestCase):
    def test_a_newer_note_with_the_same_key_replaces_the_older(self):
        notes, clock = memory()
        notes.remember("u", "Lives in Shanghai", kind="fact", key="user.city")
        clock.now += DAY
        outcome, newer = notes.keep("u", "Moved to Hangzhou", kind="fact", key="User.City")
        self.assertEqual(outcome, "replaced")
        self.assertEqual([n.text for n in notes.notes("u")], ["Moved to Hangzhou"])
        self.assertEqual([n.text for n in notes.history("u", "user.city")], ["Lives in Shanghai", "Moved to Hangzhou"])

    def test_a_repeated_note_is_not_kept_twice(self):
        notes, _ = memory()
        first = notes.remember("u", "Has a cat named 年糕", kind="fact", importance=2)
        outcome, again = notes.keep("u", "has a cat named 年糕", kind="fact", importance=4)
        self.assertEqual((outcome, again.id, again.importance), ("known", first.id, 4))

    def test_keys_name_the_topic_not_the_value(self):
        notes, _ = memory()
        with self.assertRaises(ValueError):
            notes.remember("u", "Lives in Shanghai", kind="fact", key="lives in shanghai")
        with self.assertRaises(ValueError):
            notes.remember("u", "x", kind="gossip")

    def test_automatic_notes_have_a_daily_quota_unless_important(self):
        notes, clock = memory(daily_quota=2)
        self.assertIsNotNone(notes.remember("u", "one", source="auto"))
        self.assertIsNotNone(notes.remember("u", "two", source="auto"))
        self.assertEqual(notes.keep("u", "three", source="auto"), ("over quota", None))
        self.assertIsNotNone(notes.remember("u", "four, important", source="auto", importance=4))
        self.assertIsNotNone(notes.remember("u", "asked to remember", source="user"))
        clock.now += DAY
        self.assertIsNotNone(notes.remember("u", "next day", source="auto"))

    def test_forget_and_erase(self):
        notes, _ = memory()
        a = notes.remember("u", "a note", kind="fact")
        notes.remember("u", "keyed", kind="fact", key="x.y")
        self.assertEqual(notes.forget("u", id=a.id), 1)
        self.assertEqual(notes.forget("u", key="x.y"), 1)
        self.assertEqual(notes.notes("u"), [])
        notes.remember("u", "another")
        notes.set_profile("u", "A student.")
        self.assertEqual(notes.erase("u"), 3)
        self.assertIsNone(notes.profile("u"))

    def test_the_least_valuable_fading_notes_go_first_when_full(self):
        notes, clock = memory(max_notes=3)
        notes.remember("u", "lasting", kind="fact", importance=1)
        notes.remember("u", "old trivial", importance=1)
        clock.now += 40 * DAY
        notes.remember("u", "new normal", importance=2)
        notes.remember("u", "new notable", importance=3)
        self.assertEqual(sorted(n.text for n in notes.notes("u")), ["lasting", "new normal", "new notable"])


class RecallTests(unittest.TestCase):
    def setUp(self):
        self.notes, self.clock = memory()
        self.notes.remember("u", "数学考试没考好，觉得自己很笨", kind="episode", importance=3)
        self.notes.remember("u", "喜欢喝杨枝甘露", kind="preference", importance=2)
        self.notes.remember("u", "Plays the cello in the school orchestra", kind="fact", importance=3)

    def test_matches_by_shared_words(self):
        found = self.notes.recall("u", "下次数学考试是什么时候", important=0, recent=0)
        self.assertEqual([r.note.text for r in found.chosen], ["数学考试没考好，觉得自己很笨"])
        self.assertIn("数学", found.chosen[0].matched)

    def test_explains_what_was_skipped(self):
        found = self.notes.recall("u", "cello practice", important=0, recent=0)
        self.assertEqual(len(found.chosen), 1)
        self.assertIn("nothing in common", found.explain())

    def test_pinned_notes_always_come(self):
        self.notes.remember("u", "名字叫小明", kind="fact", importance=5)
        found = self.notes.recall("u", "cello", important=0, recent=0)
        self.assertEqual(found.chosen[0].why, "pinned")

    def test_important_lasting_facts_fill_room_when_nothing_matches(self):
        self.notes.remember("u", "Has a cat named 年糕", kind="fact", importance=4)
        found = self.notes.recall("u", "我的猫", recent=0)
        self.assertEqual([(r.note.text, r.why) for r in found.chosen], [("Has a cat named 年糕", "important")])

    def test_fresher_episodes_rank_higher(self):
        notes, clock = memory()
        notes.remember("u", "去了海边看日落", importance=2)
        clock.now += 90 * DAY
        notes.remember("u", "又去海边捡贝壳", importance=2)
        found = notes.recall("u", "海边", important=0, recent=0)
        self.assertEqual(found.chosen[0].note.text, "又去海边捡贝壳")
        self.assertGreater(found.chosen[0].score, 2 * found.chosen[1].score)

    def test_recalling_refreshes_a_memory(self):
        notes, clock = memory()
        old = notes.remember("u", "去了海边看日落")
        clock.now += 60 * DAY
        before = notes.freshness(notes.get(old.id))
        notes.recall("u", "海边")
        self.assertAlmostEqual(notes.freshness(notes.get(old.id)), 1.0)
        self.assertLess(before, 0.3)
        self.assertEqual(notes.recalls("u")[0]["query"], "海边")

    def test_the_budget_caps_characters(self):
        notes, _ = memory()
        for i in range(5):
            notes.remember("u", f"海边的第{i}次回忆" + "很长" * 40)
        found = notes.recall("u", "海边", budget=200, recent=0)
        self.assertEqual(len(found.chosen), 2)
        self.assertTrue(any("budget" in reason for _, reason in found.skipped))

    def test_context_block_has_human_dates_and_the_profile(self):
        self.clock.now += 2 * DAY
        self.notes.set_profile("u", "A cellist who is hard on herself.")
        block = self.notes.context("u", "数学考试", name="小明")
        self.assertIn("小明", block)
        self.assertIn("A cellist", block)
        self.assertIn("[2 days ago] 数学考试没考好", block)
        self.assertEqual(memory()[0].context("nobody", "hi"), "")


class MovingTests(unittest.TestCase):
    def test_export_and_import_keep_history_and_links(self):
        source = Mneme(":memory:", "a", luna=False, micro=False)
        source.remember("u", "Lives in Shanghai", kind="fact", key="user.city")
        source.remember("u", "Moved to Hangzhou", kind="fact", key="user.city")
        source.memory.set_profile("u", "card")
        source.mood.apply("u", delta=5, emotions={"happy": 20})
        data = json.loads(json.dumps(source.export(), ensure_ascii=False))
        target = Mneme(":memory:", "b", luna=False, micro=False)
        target.remember("u", "unrelated", kind="fact")  # so ids differ from the source's
        self.assertEqual(target.import_(data), 2)
        self.assertEqual([n.text for n in target.memory.notes("u", kinds=["fact"])][0], "Moved to Hangzhou")
        history = target.memory.history("u", "user.city")
        self.assertEqual(history[0].superseded_by, history[1].id)
        self.assertEqual(target.memory.profile("u"), "card")
        self.assertGreater(target.mood.state("u").value, 70)

    def test_a_file_from_a_newer_version_is_refused(self):
        import os
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "m.db")
        store = Store(path)
        store.set_meta("schema_version", "99")
        store.close()
        with self.assertRaises(RuntimeError):
            Store(path)


if __name__ == "__main__":
    unittest.main()

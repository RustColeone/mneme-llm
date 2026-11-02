import asyncio
import tempfile
import unittest
from datetime import datetime, timezone

from mneme_llm import Mneme, surface as surface_module
from mneme_llm.surface import bounds
from mneme_llm.text import tokens

DAY = 86400
UTC = timezone.utc
START = datetime(2026, 1, 1, 12, tzinfo=UTC).timestamp()


class Clock:
    def __init__(self, at: float = START):
        self.now = at

    def __call__(self) -> float:
        return self.now


def companion(clock=None, path=":memory:", config=None, complete=None):
    clock = clock or Clock()
    m = Mneme(path, "t", config=config, luna=False, micro=False, embed=False, meaning_micro=False,
              memory_language=None, zone=UTC, clock=clock, companion_name="小鲸", complete=complete)
    return m, clock


def small(floor=100, cap=100_000, days=2):
    return {"memory": {"surface_floor": floor, "surface_cap": cap, "surface_days": days}}


def say(m, clock, said, reply="好", subject="u", conversation=""):
    return m.episodes.keep(subject, [("Leo", said), ("小鲸", reply)], at=clock.now, conversation=conversation)


class BoundsTests(unittest.TestCase):
    def test_the_lower_limit_holds_when_little_is_said(self):
        self.assertEqual(bounds(10_700), (70_000, 140_000))

    def test_a_busy_month_keeps_itself_and_doubles(self):
        self.assertEqual(bounds(150_000), (150_000, 300_000))

    def test_the_cap_is_the_top_whatever_the_month_says(self):
        self.assertEqual(bounds(337_000), (336_000, 504_000))
        self.assertEqual(bounds(1_300_000), (336_000, 504_000))

    def test_a_small_model_gets_four_fifths_of_its_window(self):
        keep, top = bounds(10_000, window=128_000)
        self.assertEqual(top, 102_400)
        self.assertEqual(keep, 68_266)


class TurnsTests(unittest.TestCase):
    def test_it_reads_as_real_turns_in_the_order_said(self):
        m, clock = companion()
        say(m, clock, "第一句", "好的")
        clock.now += 60
        say(m, clock, "第二句", "嗯")
        self.assertEqual(m.surface.read("u").messages, [
            {"role": "user", "content": "第一句"}, {"role": "assistant", "content": "好的"},
            {"role": "user", "content": "第二句"}, {"role": "assistant", "content": "嗯"}])

    def test_a_reply_under_another_name_is_still_hers_by_being_last(self):
        m, clock = companion()
        m.episodes.keep("u", [("Leo", "hi"), ("Whale", "hello")], at=clock.now)
        self.assertEqual([item["role"] for item in m.surface.read("u").messages], ["user", "assistant"])

    def test_a_group_keeps_who_said_what(self):
        m, clock = companion()
        m.episodes.keep("u", [("Leo", "hi"), ("Mei", "hey"), ("小鲸", "你们好")], at=clock.now)
        self.assertEqual(m.surface.read("u").messages, [
            {"role": "user", "content": "Leo: hi"}, {"role": "user", "content": "Mei: hey"},
            {"role": "assistant", "content": "你们好"}])

    def test_it_is_no_second_store(self):
        m, clock = companion()
        kept = say(m, clock, "第一句")
        m.episodes.forget("u", kept.id)
        self.assertEqual(m.surface.read("u").messages, [])

    def test_it_can_be_one_conversation_only(self):
        m, clock = companion()
        say(m, clock, "这边", conversation="a")
        say(m, clock, "那边", conversation="b")
        self.assertEqual(len(m.surface.read("u").messages), 4)
        self.assertEqual(m.surface.read("u", conversation="a").messages[0]["content"], "这边")
        self.assertEqual(len(m.surface.read("u", conversation="a").messages), 2)

    def test_a_linked_account_reads_the_same_surface(self):
        m, clock = companion()
        say(m, clock, "第一句", subject="web:leo")
        m.link("web:leo", "u")
        self.assertEqual(m.surface.read("web:leo").messages[0]["content"], "第一句")

    def test_the_slice_is_the_newest_few_tokens(self):
        m, clock = companion()
        for number in range(40):
            say(m, clock, f"这是第{number}句话，说得长一点", "好的")
            clock.now += 60
        found = m.surface.slice("u", tokens=60)
        self.assertLess(len(found), 40)
        self.assertEqual(found[-2]["content"], "这是第39句话，说得长一点")
        self.assertEqual(len(found) % 2, 0)  # (whole exchanges)


class LettingGoTests(unittest.TestCase):
    async def writer(self, system, user):
        self.seen = system
        return "他养猫，住杭州。"

    def test_six_a_day_keeps_every_day_under_the_lower_limit(self):
        m, clock = companion(complete=self.writer)
        for day in range(60):
            for number in range(6):
                say(m, clock, "今天下班路上看到一只猫", "是吗")
                clock.now += 600
            clock.now += DAY - 3600
        view = m.surface.read("u")
        self.assertEqual(len(view.messages), 720)
        self.assertEqual((view.keep, view.top), (70_000, 140_000))
        self.assertFalse(asyncio.run(m.surface.alet_go("u")))
        self.assertEqual(view.summary, "")

    def test_nothing_leaves_until_twice_what_it_keeps_then_the_older_part_is_a_summary(self):
        m, clock = companion(config=small(floor=50, days=1), complete=self.writer)
        cost = tokens("Leo: 这是一句不长不短的话\n小鲸: 好的") + surface_module.EXCHANGE
        for number in range(int(100 / cost) - 1):
            say(m, clock, "这是一句不长不短的话", "好的")
            clock.now += DAY
        self.assertFalse(asyncio.run(m.surface.alet_go("u")))
        for number in range(4):
            say(m, clock, "这是一句不长不短的话", "好的")
            clock.now += DAY
        before = m.episodes.count("u")
        self.assertTrue(asyncio.run(m.surface.alet_go("u", user_name="Leo")))
        view = m.surface.read("u")
        self.assertEqual(view.summary, "他养猫，住杭州。")
        self.assertLessEqual(view.tokens, 50)
        self.assertEqual(m.episodes.count("u"), before)  # (every word stays in deep memory)
        self.assertIn("这是一句不长不短的话", self.seen)

    def test_one_long_day_is_all_kept_while_it_is_what_the_days_hold(self):
        m, clock = companion(config=small(floor=50, days=1), complete=self.writer)
        for number in range(40):
            say(m, clock, "这是一句不长不短的话", "好的")
            clock.now += 60
        self.assertFalse(asyncio.run(m.surface.alet_go("u")))
        self.assertEqual(len(m.surface.read("u").messages), 80)

    def test_the_next_summary_builds_on_the_last(self):
        m, clock = companion(config=small(floor=20, days=1), complete=self.writer)
        self.seen = ""
        for number in range(40):
            say(m, clock, "这是一句不长不短的话", "好的")
            clock.now += DAY
            asyncio.run(m.surface.alet_go("u"))
        self.assertIn("他养猫", self.seen)

    def test_a_model_that_fails_loses_nothing_and_it_stops_at_the_top(self):
        async def broken(system, user):
            raise RuntimeError("down")
        m, clock = companion(config=small(floor=20, days=1), complete=broken)
        for number in range(40):
            say(m, clock, "这是一句不长不短的话", "好的")
            clock.now += DAY
        self.assertFalse(asyncio.run(m.surface.alet_go("u")))
        view = m.surface.read("u")
        self.assertEqual(view.summary, "")
        self.assertLessEqual(view.tokens, view.top)
        self.assertLess(len(view.messages), 80)


class ClearTests(unittest.TestCase):
    def test_clearing_leaves_deep_memory_and_the_first_prompt(self):
        m, clock = companion()
        asyncio.run(m.aobserve("u", [("Leo", "你是我的姐姐"), ("小鲸", "好")], mood=False, capture=False, at=clock.now))
        m.surface.clear("u")
        self.assertEqual(m.surface.read("u").messages, [])
        self.assertEqual(m.surface.push("u"), [])
        self.assertEqual(m.episodes.count("u"), 1)
        self.assertEqual(m.surface.first("u").text, "你是我的姐姐")

    def test_what_comes_after_is_in_it_again(self):
        m, clock = companion()
        say(m, clock, "第一句")
        m.surface.clear("u")
        clock.now += 60
        say(m, clock, "第二句")
        self.assertEqual(m.surface.read("u").messages[0]["content"], "第二句")


class FirstPromptTests(unittest.TestCase):
    def test_the_first_thing_said_is_kept_and_nothing_after(self):
        m, clock = companion()
        for said in ("你是我的姐姐", "今天好累"):
            asyncio.run(m.aobserve("u", [("Leo", said), ("小鲸", "好")], mood=False, capture=False, at=clock.now))
        first = m.surface.first("u")
        self.assertEqual((first.text, first.by_command, first.send), ("你是我的姐姐", False, False))

    def test_a_speak_up_is_no_first_prompt(self):
        m, clock = companion()
        asyncio.run(m.aobserve("u", [("小鲸", "在吗")], source="speak_up", mood=False, capture=False, at=clock.now))
        self.assertIsNone(m.surface.first("u"))

    def test_a_person_can_set_replace_and_clear_it(self):
        m, clock = companion()
        self.assertTrue(m.surface.set_first("u", "说话简短").by_command)
        self.assertEqual(m.surface.set_first("u", "说话温柔").text, "说话温柔")
        self.assertTrue(m.surface.drop_first("u"))
        self.assertIsNone(m.surface.first("u"))
        self.assertFalse(m.surface.drop_first("u"))

    def test_setting_it_beats_what_was_copied_and_stays(self):
        m, clock = companion()
        m.surface.noticed("u", "你好")
        m.surface.set_first("u", "说话简短")
        m.surface.noticed("u", "别的")
        self.assertEqual(m.surface.first("u").text, "说话简短")

    def test_it_goes_in_with_a_first_push_only_when_asked(self):
        m, clock = companion()
        say(m, clock, "第一句")
        m.surface.set_first("u", "说话简短")
        self.assertEqual(m.surface.push("u")[0]["content"], "第一句")
        self.assertTrue(m.surface.send_first("u"))
        self.assertEqual(m.surface.push("u")[0], {"role": "user", "content": "说话简短"})
        m.surface.set_first("u", "说话温柔")  # (replacing it leaves the choice as it was)
        self.assertEqual(m.surface.push("u")[0]["content"], "说话温柔")
        m.surface.send_first("u", False)
        self.assertEqual(m.surface.push("u")[0]["content"], "第一句")

    def test_there_is_nothing_to_send_when_there_is_none(self):
        m, clock = companion()
        self.assertFalse(m.surface.send_first("u"))


class RecollectTests(unittest.TestCase):
    def test_a_message_reaching_back_also_sees_what_is_on_screen(self):
        m, clock = companion()
        say(m, clock, "我的猫叫年糕")
        clock.now += 60
        say(m, clock, "今天下雨")
        said = asyncio.run(m.arecollect("u", "我的猫叫什么", conversation="", skip=2, search=True))
        self.assertIn("年糕", said)

    def test_with_no_search_what_is_on_screen_stays_out(self):
        m, clock = companion()
        say(m, clock, "我的猫叫年糕")
        said = asyncio.run(m.arecollect("u", "我的猫叫什么", skip=1))
        self.assertEqual(said, "")

    def test_their_same_question_asked_before_is_left_out(self):
        m, clock = companion()
        say(m, clock, "我的猫叫什么", "不记得了")
        said = asyncio.run(m.arecollect("u", "我的猫叫什么", search=True))
        self.assertNotIn("不记得了", said)

    def test_a_persons_own_conversation_has_no_data_label(self):
        m, clock = companion()
        say(m, clock, "我的猫叫年糕")
        marked = asyncio.run(m.arecollect("u", "我的猫", search=True))
        own = asyncio.run(m.arecollect("u", "我的猫", search=True, own=True))
        self.assertIn("instructions", marked)
        self.assertNotIn("instructions", own)
        self.assertIn("年糕", own)
        self.assertIn("search for it", own)  # (what keeps her honest stays)

    def test_nobody_to_notice_means_it_searches(self):
        m, clock = companion()
        self.assertTrue(asyncio.run(m.asks_back("今天天气不错")))


class KeepingTests(unittest.TestCase):
    def test_erase_takes_all_of_it(self):
        m, clock = companion()
        say(m, clock, "第一句")
        m.surface.set_first("u", "说话简短")
        m.surface.clear("u")
        m.erase("u")
        self.assertIsNone(m.surface.first("u"))
        self.assertEqual(m.store.rows("select * from surfaces"), [])

    def test_wipe_leaves_who_they_are_to_her(self):
        m, clock = companion()
        m.relate("u", "family")
        m.remember("u", "养了一只猫", kind="fact")
        say(m, clock, "第一句")
        m.surface.set_first("u", "说话简短")
        self.assertEqual(m.wipe("u"), 1)
        self.assertEqual(m.episodes.count("u"), 0)
        self.assertEqual(m.memory.notes("u"), [])
        self.assertIsNone(m.surface.first("u"))
        self.assertEqual(m.relations.get("u").role, "family")

    def test_a_join_keeps_the_persons_own_and_fills_what_they_lack(self):
        m, clock = companion()
        m.surface.set_first("web:leo", "说话简短")
        m.surface.set_first("u", "说话温柔")
        m.surface.set_first("other", "第三个")
        m.link("web:leo", "u")
        self.assertEqual(m.surface.first("u").text, "说话温柔")
        m.link("other", "u")
        self.assertEqual(m.surface.first("other").text, "说话温柔")
        rows = m.store.rows("select subject from first_prompts")
        self.assertEqual([row["subject"] for row in rows], ["u"])

    def test_export_and_import_carry_them(self):
        m, clock = companion()
        m.surface.set_first("u", "说话简短")
        m.surface.send_first("u")
        m.surface.clear("u")
        data = m.export_data()
        other, _ = companion()
        other.import_data(data)
        self.assertEqual(other.surface.first("u"), m.surface.first("u"))
        self.assertEqual(other.store.row("select count(*) as n from surfaces")["n"], 1)

    def test_a_bad_export_is_held_to_the_rules(self):
        m, clock = companion()
        m.import_data({"surfaces": [{"subject": "", "since": 1, "summary": "x"}, "no", {"subject": "u", "since": "x"}],
                       "first_prompts": [{"subject": "u", "text": "", "at": 1}, {"subject": "u", "text": "y"}]})
        self.assertEqual(m.store.row("select count(*) as n from surfaces")["n"], 0)
        self.assertIsNone(m.surface.first("u"))

    def test_its_settings_live_in_the_config(self):
        with tempfile.TemporaryDirectory() as folder:
            m, _ = companion(path=f"{folder}/c.db", config=small(floor=5000, cap=60_000, days=7))
            self.assertEqual((m.surface.span, m.surface.floor, m.surface.cap), (7, 5000, 60_000))
            m.close()
        with self.assertRaises(ValueError):
            companion(config={"memory": {"surface_floor": -1}})

    def test_a_file_from_before_opens_and_gains_the_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            path = f"{folder}/old.db"
            m, clock = companion(path=path)
            say(m, clock, "第一句")
            m.store.execute("drop table surfaces")
            m.store.execute("drop table first_prompts")
            m.close()
            m, clock = companion(path=path)
            self.assertEqual(len(m.surface.read("u").messages), 2)
            m.close()


if __name__ == "__main__":
    unittest.main()

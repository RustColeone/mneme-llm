import asyncio
import tempfile
import unittest
from datetime import datetime, timezone

from mneme_llm import Mneme, episodes as episodes_module
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
    m = Mneme(path, "t", config=config, embed=False,
              memory_language=None, zone=UTC, clock=clock, companion_name="小鲸", complete=complete)
    return m, clock


def small(floor=100, cap=100_000, days=2):
    return {"memory": {"surface_floor": floor, "surface_cap": cap, "surface_days": days}}


def say(m, clock, said, reply="好", subject="u"):
    return m.episodes.keep(subject, [("Leo", said), ("小鲸", reply)], at=clock.now)


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

    def test_what_a_classmate_said_is_not_hers(self):
        m, clock = companion()
        m.episodes.keep("u", [("Leo", "hi"), ("Gemini", "hello")], at=clock.now)
        self.assertEqual(m.surface.read("u").messages, [{"role": "user", "content": "Leo: hi"},
                                                        {"role": "user", "content": "Gemini: hello"}])

    def test_it_says_when_its_newest_was_said(self):
        m, clock = companion()
        self.assertEqual(m.surface.read("u").upto, 0.0)
        say(m, clock, "第一句")
        clock.now += 60
        say(m, clock, "第二句")
        self.assertEqual(m.surface.read("u").upto, clock.now)

    def test_what_she_said_on_her_own_reads_as_hers(self):
        m, clock = companion()
        m.episodes.keep("u", [("小鲸", "在吗")], at=clock.now)
        self.assertEqual(m.surface.read("u").messages, [{"role": "assistant", "content": "在吗"}])

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

    def test_it_follows_the_person_into_any_chat(self):
        m, clock = companion()
        m.episodes.keep("u", [("Leo", "这边")], at=clock.now, conversation="a")
        m.episodes.keep("u", [("Leo", "那边")], at=clock.now, conversation="b")
        self.assertEqual(len(m.surface.read("u").messages), 2)

    def test_a_chat_message_stored_by_its_role_is_hers(self):
        m, clock = companion()
        m.episodes.keep("u", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "你好"}], at=clock.now)
        self.assertEqual(m.surface.read("u").messages, [{"role": "user", "content": "hi"},
                                                        {"role": "assistant", "content": "你好"}])

    def test_turns_read_in_the_order_they_were_said_whatever_order_they_were_kept(self):
        m, clock = companion()
        m.episodes.keep("u", [("Leo", "后说的")], at=clock.now + 60)
        m.episodes.keep("u", [("Leo", "先说的")], at=clock.now)
        view = m.surface.read("u")
        self.assertEqual([message["content"] for message in view.messages], ["先说的", "后说的"])
        self.assertEqual(view.upto, clock.now + 60)

    def test_the_newest_exchange_is_always_there_even_alone_over_the_budget(self):
        m, clock = companion(config=small(floor=10, cap=1000, days=1))
        say(m, clock, "第一句")
        huge = say(m, clock, "很长" * 2000)
        self.assertGreater(huge.tokens, 1000)
        self.assertEqual(m.surface.slice("u", tokens=10)[0]["content"], "很长" * 2000)
        self.assertEqual(m.surface.read("u").messages[0]["content"], "很长" * 2000)
        self.assertEqual(m.surface.read("u").tokens, int(huge.tokens))

    def test_days_of_zero_means_one(self):
        m = Mneme(":memory:", "t", embed=False, surface_days=0)
        self.assertEqual(m.surface.span, 1)
        m.episodes.keep("u", [("Leo", "hi")])
        self.assertEqual(len(m.surface.read("u").messages), 1)

    def test_a_small_slice_reads_only_what_it_needs(self):
        m, clock = companion()
        for number in range(500):
            say(m, clock, f"第{number}句")
        read = []
        rows = m.store.rows
        m.store.rows = lambda sql, values=(): read.append(sql) or rows(sql, values)
        self.assertEqual(len(m.surface.slice("u", tokens=30)) % 2, 0)
        self.assertEqual(sum("from episodes" in sql and "order by id desc" in sql for sql in read), 1)

    def test_its_language_follows_the_companion(self):
        m, clock = companion(complete=None)
        m.display_language = "zh"
        self.assertEqual(m.surface.display_language, "zh")

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
        self.assertEqual(m.surface.read("u").messages[0]["content"], "今天下班路上看到一只猫")

    def test_nothing_leaves_until_twice_what_it_keeps_then_the_older_part_is_a_summary(self):
        m, clock = companion(config=small(floor=50, days=1), complete=self.writer)
        cost = tokens("Leo: 这是一句不长不短的话\n小鲸: 好的") + episodes_module.EXCHANGE
        for number in range(int(100 / cost) - 1):
            say(m, clock, "这是一句不长不短的话", "好的")
            clock.now += DAY
        self.assertFalse(asyncio.run(m.surface.alet_go("u")))
        for number in range(4):
            say(m, clock, "这是一句不长不短的话", "好的")
            clock.now += DAY
        before = m.episodes.count("u")
        self.assertTrue(asyncio.run(m.surface.alet_go("u", user_name="Leo")))
        view = m.surface.read("u", user_name="Leo")
        self.assertEqual(view.messages[0], {"role": "user", "content": "Earlier with Leo, in short:\n他养猫，住杭州。"})
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
        self.assertEqual(view.messages[0]["content"], "这是一句不长不短的话")  # (no summary)
        self.assertLessEqual(view.tokens, view.top)
        self.assertLess(len(view.messages), 80)


    def race(self, change):
        """`alet_go`, with `change(m)` made while the model writes the summary."""
        m, clock = None, None

        async def writer(system, user):
            change(m)
            return "他养猫。"
        m, clock = companion(config=small(floor=20, days=1), complete=writer)
        for number in range(40):
            say(m, clock, "这是一句不长不短的话", "好的")
            clock.now += DAY
        before = m.surface.began("u")
        return m, asyncio.run(m.surface.alet_go("u")), before

    def test_an_erase_while_the_model_writes_is_respected(self):
        m, done, _ = self.race(lambda m: m.erase("u"))
        self.assertFalse(done)
        self.assertEqual(m.store.rows("select * from surfaces"), [])

    def test_a_clear_while_the_model_writes_is_respected(self):
        m, done, _ = self.race(lambda m: m.surface.clear("u"))
        self.assertFalse(done)
        self.assertEqual(m.surface.read("u").messages, [])

    def test_a_link_while_the_model_writes_is_respected(self):
        m, done, before = self.race(lambda m: m.link("u", "discord:1"))
        self.assertFalse(done)
        self.assertEqual(m.surface.began("discord:1"), before)

    def test_new_exchanges_while_the_model_writes_stay(self):
        def more(m):
            m.episodes.keep("u", [("Leo", "写总结的时候说的")], at=m.memory.clock())
        m, done, _ = self.race(more)
        self.assertTrue(done)
        self.assertEqual(m.surface.read("u").messages[-1]["content"], "写总结的时候说的")


class WhereItEndsTests(unittest.TestCase):
    def test_what_was_left_unanswered_in_a_chat_stays_that_chats(self):
        m, clock = companion()
        say(m, clock, "这边", conversation="a")
        clock.now += 60
        here = clock.now
        say(m, clock, "那边", conversation="b")
        clock.now += 60
        self.assertEqual(m.surface.read("u", here="a").upto, here - 60)
        self.assertEqual(m.surface.read("u", here="b").upto, here)
        self.assertEqual(m.surface.read("u", here="new").upto, 0.0)

    def test_a_failed_summary_waits_before_it_tries_again(self):
        calls = []

        async def broken(system, user):
            calls.append(system)
            raise RuntimeError("down")
        m, clock = companion(config=small(floor=20, days=1), complete=broken)
        for number in range(40):
            say(m, clock, "这是一句不长不短的话", "好的")
            clock.now += DAY
        self.assertFalse(asyncio.run(m.surface.alet_go("u")))
        self.assertFalse(asyncio.run(m.surface.alet_go("u")))
        self.assertEqual(len(calls), 1)
        self.assertIn("down", m.surface.rest.error)


class ClearTests(unittest.TestCase):
    def test_clearing_leaves_deep_memory_and_the_first_prompt(self):
        m, clock = companion()
        asyncio.run(m.aobserve("u", [("Leo", "你是我的姐姐"), ("小鲸", "好")], mood=False, capture=False, at=clock.now))
        m.surface.clear("u")
        self.assertEqual(m.surface.read("u").messages, [])
        self.assertEqual(m.episodes.count("u"), 1)
        self.assertEqual(m.surface.first("u").text, "你是我的姐姐")

    def test_an_exchange_kept_after_a_clear_is_in_it_whenever_it_was_said(self):
        m, clock = companion()
        say(m, clock, "第一句")
        clock.now += 3600
        m.surface.clear("u")
        m.episodes.keep("u", [("Leo", "清空之前说的，之后才记下")], at=clock.now - 60)
        self.assertEqual([message["content"] for message in m.surface.read("u").messages], ["清空之前说的，之后才记下"])

    def test_a_forgotten_exchanges_id_never_comes_back(self):
        m, clock = companion()
        kept = say(m, clock, "第一句")
        m.surface.clear("u")
        m.episodes.forget("u", kept.id)
        new = say(m, clock, "第二句")
        self.assertGreater(new.id, kept.id)
        self.assertEqual(m.surface.read("u").messages[0]["content"], "第二句")

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

    def test_dropping_it_is_for_good_until_they_set_one(self):
        m, clock = companion()
        asyncio.run(m.aobserve("u", [("Leo", "你是我的姐姐")], mood=False, capture=False, at=clock.now))
        m.surface.send_first("u")
        self.assertTrue(m.surface.drop_first("u"))
        asyncio.run(m.aobserve("u", [("Leo", "今天好累")], mood=False, capture=False, at=clock.now))
        self.assertIsNone(m.surface.first("u"))
        self.assertFalse(m.surface.send_first("u"))
        self.assertEqual(m.surface.read("u").messages[0]["content"], "你是我的姐姐")  # (only the copy went)
        self.assertEqual(m.surface.set_first("u", "说话简短").send, False)  # (a new one starts unsent)
        m.surface.drop_first("u")
        m.erase("u")
        asyncio.run(m.aobserve("u", [("Leo", "重新开始")], mood=False, capture=False, at=clock.now))
        self.assertEqual(m.surface.first("u").text, "重新开始")

    def test_a_dropped_first_prompt_stays_dropped_in_another_file(self):
        m, clock = companion()
        m.surface.set_first("u", "说话简短")
        m.surface.drop_first("u")
        other, _ = companion()
        other.import_data(m.export_data())
        other.surface.noticed("u", [("Leo", "你好")])
        self.assertIsNone(other.surface.first("u"))

    def test_a_companion_who_spoke_first_is_no_first_prompt(self):
        m, clock = companion()
        asyncio.run(m.aobserve("u", [("小鲸", "在吗"), ("Leo", "你是我的姐姐")], mood=False, capture=False, at=clock.now))
        self.assertEqual(m.surface.first("u").text, "你是我的姐姐")

    def test_setting_it_beats_what_was_copied_and_stays(self):
        m, clock = companion()
        m.surface.noticed("u", [("Leo", "你好")])
        m.surface.set_first("u", "说话简短")
        m.surface.noticed("u", [("Leo", "别的")])
        self.assertEqual(m.surface.first("u").text, "说话简短")

    def test_a_new_chat_reads_the_first_prompt_then_the_surface_when_asked(self):
        m, clock = companion()
        say(m, clock, "第一句", "好的")
        m.surface.set_first("u", "说话简短")
        self.assertEqual(m.surface.read("u").messages[0]["content"], "第一句")
        self.assertTrue(m.surface.send_first("u"))
        self.assertEqual(m.surface.read("u").messages, [{"role": "user", "content": "说话简短"},
                                                        {"role": "user", "content": "第一句"},
                                                        {"role": "assistant", "content": "好的"}])
        m.surface.set_first("u", "说话温柔")  # (replacing it leaves the choice as it was)
        self.assertEqual(m.surface.read("u").messages[0]["content"], "说话温柔")
        m.surface.send_first("u", False)
        self.assertEqual(m.surface.read("u").messages[0]["content"], "第一句")

    def test_it_stays_in_front_when_the_surface_is_cleared(self):
        m, clock = companion()
        say(m, clock, "第一句")
        m.surface.set_first("u", "说话简短")
        m.surface.send_first("u")
        m.surface.clear("u")
        self.assertEqual(m.surface.read("u").messages, [{"role": "user", "content": "说话简短"}])

    def test_there_is_nothing_to_send_when_there_is_none(self):
        m, clock = companion()
        self.assertFalse(m.surface.send_first("u"))


class LookTests(unittest.TestCase):
    def test_a_search_comes_with_the_look_and_finds_what_is_on_screen_too(self):
        m, clock = companion()
        say(m, clock, "我的猫叫年糕")
        clock.now += 60
        say(m, clock, "今天下雨")
        self.assertIn("年糕", asyncio.run(m.alook("u", "我的猫叫什么", search=True)))
        self.assertIn("年糕", m.look("u", "我的猫叫什么", search=True))

    def test_their_same_question_asked_before_is_left_out(self):
        m, clock = companion()
        say(m, clock, "我的猫叫什么", "不记得了")
        self.assertNotIn("不记得了", asyncio.run(m.alook("u", "我的猫叫什么", search=True)))

    def test_a_persons_own_conversation_has_no_data_label(self):
        m, clock = companion()
        say(m, clock, "我的猫叫年糕")
        marked = asyncio.run(m.alook("u", "我的猫", search=True))
        own = asyncio.run(m.alook("u", "我的猫", search=True, own=True))
        self.assertIn("instructions", marked)
        self.assertNotIn("instructions", own)
        self.assertIn("年糕", own)
        self.assertIn("search for it", own)  # (what keeps her honest stays)

    def test_in_a_group_no_search_comes_by_itself(self):
        m, clock = companion()
        say(m, clock, "这是只对你说的秘密")
        told = asyncio.run(m.alook("u", "完全无关的一句话", search=True, found=0))
        self.assertNotIn("秘密", told)
        self.assertIn("search for it", told)  # (her tools are still there)

    def test_a_search_that_comes_by_itself_rehearses_nothing(self):
        m, clock = companion()
        kept = say(m, clock, "我的猫叫年糕")
        asyncio.run(m.alook("u", "猫", search=True))
        self.assertEqual(m.episodes.get(kept.id).recalls, 0)


class KeepingTests(unittest.TestCase):
    def test_it_knows_when_it_was_cleared(self):
        m, clock = companion()
        self.assertEqual(m.surface.began("u"), 0.0)
        m.surface.clear("u")
        self.assertGreaterEqual(m.surface.began("u"), clock.now)

    def test_everyone_anything_is_kept_of(self):
        m, clock = companion()
        say(m, clock, "第一句", subject="b")
        m.remember("a", "养猫", kind="fact")
        m.surface.set_first("c", "说话简短")
        self.assertEqual(m.everyone(), ["a", "b", "c"])

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

    def test_a_join_keeps_the_lower_start_and_both_summaries(self):
        m, clock = companion()
        say(m, clock, "甲一", subject="a")
        m.surface._put("a", m.episodes.latest("a")[0], clock.now, "甲的总结")
        say(m, clock, "乙一", subject="b")
        say(m, clock, "乙二", subject="b")
        m.surface._put("b", m.episodes.latest("b")[0], clock.now, "乙的总结")
        say(m, clock, "乙三", subject="b")
        m.link("a", "b")
        view = m.surface.read("b", user_name="Leo")
        self.assertIn("甲的总结", view.messages[0]["content"])
        self.assertIn("乙的总结", view.messages[0]["content"])
        self.assertEqual([message["content"] for message in view.messages[1:] if message["role"] == "user"],
                         ["乙一", "乙二", "乙三"])

    def test_a_join_with_someone_who_has_no_surface_starts_from_all_of_it(self):
        m, clock = companion()
        say(m, clock, "甲一", subject="a")
        m.surface.clear("a")
        say(m, clock, "乙一", subject="b")
        m.link("a", "b")
        self.assertEqual(len(m.surface.read("b").messages), 4)
        self.assertEqual(m.store.rows("select * from surfaces"), [])

    def test_a_link_of_an_empty_account_leaves_the_surface_as_it_is(self):
        m, clock = companion()
        say(m, clock, "第一句")
        m.surface.clear("u")
        m.link("web:leo", "u")
        self.assertEqual(m.surface.read("u").messages, [])
        m.import_data(m.export_data())  # (each import joins every link again)
        self.assertEqual(m.surface.read("u").messages, [])

    def test_export_and_import_carry_them(self):
        m, clock = companion()
        m.surface.set_first("u", "说话简短")
        m.surface.send_first("u")
        say(m, clock, "第一句")
        clock.now += 60
        m.surface.clear("u")
        clock.now += 60
        say(m, clock, "第二句")
        data = m.export_data()
        other, _ = companion()
        say(other, clock, "别的人说的", subject="someone")  # (ids differ from the export's)
        other.import_data(data)
        self.assertEqual(other.surface.first("u"), m.surface.first("u"))
        self.assertEqual(other.surface.read("u").messages, m.surface.read("u").messages)
        self.assertEqual(other.surface.began("u"), m.surface.began("u"))

    def test_an_import_joins_a_surface_that_is_here_once(self):
        m, clock = companion()
        say(m, clock, "第一句")
        m.surface._put("u", 1, clock.now + 1, "总结")
        data = m.export_data()
        for _ in range(2):
            m.import_data(data)
        self.assertEqual(m.store.rows("select summary from surfaces")[0]["summary"], "总结")

    def test_a_bad_export_is_held_to_the_rules(self):
        m, clock = companion()
        m.import_data({"surfaces": [{"subject": "", "cleared_at": 1, "summary": "x"}, "no",
                                    {"subject": "u", "cleared_at": "x"}],
                       "first_prompts": [{"subject": "u", "text": "", "at": 1}, {"subject": "u", "text": "y"}]})
        self.assertEqual(m.store.row("select count(*) as n from surfaces")["n"], 0)
        self.assertIsNone(m.surface.first("u"))

    def test_its_limits_can_be_as_high_as_someone_wants(self):
        m, _ = companion(config=small(floor=10 ** 9, cap=10 ** 10))
        m2 = Mneme(":memory:", "t", embed=False, surface_days=365, surface_floor=10 ** 8, surface_cap=10 ** 9,
                   surface_window=10 ** 10)
        self.assertEqual((m.surface.floor, m.surface.cap), (10 ** 9, 10 ** 10))
        self.assertEqual((m2.surface.span, m2.surface.floor, m2.surface.cap, m2.surface.window),
                         (365, 10 ** 8, 10 ** 9, 10 ** 10))
        self.assertEqual(bounds(0, 10 ** 8, 10 ** 9, 10 ** 10), (10 ** 8, 2 * 10 ** 8))

    def test_its_settings_live_in_the_config(self):
        with tempfile.TemporaryDirectory() as folder:
            m, _ = companion(path=f"{folder}/c.db", config=small(floor=5000, cap=60_000, days=7))
            self.assertEqual((m.surface.span, m.surface.floor, m.surface.cap), (7, 5000, 60_000))
            m.close()
        with self.assertRaises(ValueError):
            companion(config={"memory": {"surface_floor": -1}})



if __name__ == "__main__":
    unittest.main()

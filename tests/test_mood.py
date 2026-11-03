import asyncio
import unittest

from mneme_llm import exchange as exchanges
from mneme_llm.decide import Answer
from mneme_llm.mood import Mood, MoodSettings
from mneme_llm.store import Store

HOUR = 3600


class Clock:
    now = 1_800_000_000.0

    def __call__(self):
        return self.now


class Judge:
    """A judge that returns a fixed mood verdict and records what it was asked."""

    name = "judge"

    def __init__(self, change=None, feeling=None, reason=""):
        self.change, self.feeling, self.reason, self.asked = change, feeling, reason, []

    async def adecide(self, input, questions):
        self.asked.append((input, {q.name: q for q in questions}))
        found = {}
        if self.change is not None:
            found["mood_change"] = Answer("mood_change", self.change, max(self.change.values()), self.name,
                                          self.reason)
        if self.feeling is not None:
            found["feeling"] = Answer("feeling", self.feeling, max(self.feeling.values()), self.name)
        return found


def mood(**settings):
    clock = Clock()
    return Mood(Store(":memory:"), "t", settings=MoodSettings(**settings), companion_name="大肥鱼", clock=clock), clock


def judged(m, judge, exchange, *, source="user", user_name="Leo"):
    """What `Mneme.aobserve` does with an exchange and a judge."""
    framed = exchanges.frame(exchange, source=source, user_name=user_name, companion_name=m.companion_name)
    answers = asyncio.run(judge.adecide(framed, m.questions()))
    return m.apply_answers("u", answers, exchange, source=source, user_name=user_name)


class MoodTests(unittest.TestCase):
    def test_starts_at_baseline_and_drifts_back(self):
        m, clock = mood()
        self.assertEqual(m.state("u").value, 70)
        m.apply("u", delta=20, emotions={"happy": 40})
        clock.now += 3 * HOUR
        state = m.state("u")
        self.assertAlmostEqual(state.value, 80, places=3)
        self.assertAlmostEqual(state.emotions["happy"], 40 * 0.5 ** 2, places=3)  # 90-minute half-life

    def test_drops_only_from_aching_worry_or_sadness(self):
        m, _ = mood()
        self.assertIsNone(m.apply("u", delta=-10, emotions={"jealous": 0.4}))  # nothing left to record
        self.assertEqual(m.state("u").value, 70)
        event = m.apply("u", delta=-10, emotions={"worried": 30})
        self.assertAlmostEqual(event.value, 60)

    def test_floor_ceiling_and_source_weights(self):
        m, _ = mood(floor=40)
        m.apply("u", delta=-50, emotions={"sad": 50})
        self.assertEqual(m.state("u").value, 40)
        m.reset("u")
        m.apply("u", delta=10, emotions={"happy": 10}, source="duty")
        self.assertAlmostEqual(m.state("u").value, 75)

    def test_judging_moves_by_expected_level_and_spreads_feelings(self):
        judge = Judge(change={"-2": 0, "-1": 0.04, "0": 0.45, "1": 0.4, "2": 0.11},
                      feeling={"tender": 0.94, "happy": 0.06})
        m, _ = mood()
        event = judged(m, judge, [("Leo", "今天考试又没考好……"), ("大肥鱼", "才不笨！")])
        self.assertAlmostEqual(event.delta, 0.58 * 6, places=2)
        self.assertEqual(set(event.emotions), {"tender"})  # 6% of happy is below the noise floor
        self.assertEqual(event.reason, "Leo said “今天考试又没考好……”")  # the feeling is said by the cue
        self.assertEqual(event.judge, "judge")

    def test_the_question_follows_who_started_it(self):
        judge = Judge(feeling={"sweet": 0.9, "happy": 0.1})
        m, _ = mood()
        judged(m, judge, "大肥鱼: 想你了", source="speak-up")
        input, questions = judge.asked[0]
        self.assertIn("reached out to Leo on their own", input)
        self.assertNotIn("Leo", questions["mood_change"].instructions)  # names live in the text, not the question
        self.assertIsNone(m.apply_answers("u", {}, "x", source="runtime"))

    def test_news_says_what_to_feel(self):
        m, _ = mood()
        m.apply("u", delta=6, emotions={"happy": 40}, reason="Leo passed the exam", confidence=0.9)
        self.assertEqual(m.news("u"), "(Your mood 76/100 (good); feeling: happy 40 right now. What just moved you: "
                                      "Leo passed the exam. Something worth celebrating: you feel happy.)")
        m.display_language = "zh"
        m.apply("u", delta=-3, emotions={"worried": 40}, reason="Leo发烧了", confidence=0.9)
        self.assertIn("这让你放心不下：你在担心对方。", m.news("u"))

    def test_news_is_told_once_and_only_when_confident(self):
        m, _ = mood(threshold=0.6)
        m.apply("u", delta=4, emotions={"happy": 30}, reason="被夸了", confidence=0.9)
        news = m.news("u")
        self.assertIn("被夸了", news)
        self.assertIsNone(m.news("u"))
        m.apply("u", delta=4, emotions={"happy": 30}, reason="猜的", confidence=0.3)
        self.assertIsNone(m.news("u"))
        self.assertEqual(m.timeline("u")[0].reason, "猜的")  # still on the record

    def test_telling_modes(self):
        m, _ = mood(tell="off")
        m.apply("u", delta=4, emotions={"happy": 30}, reason="r")
        self.assertIsNone(m.news("u"))
        m, _ = mood(tell="mood")
        m.apply("u", delta=4, emotions={"happy": 30}, reason="r")
        self.assertNotIn("r)", m.news("u"))

    def test_chinese_description_and_faces(self):
        m, _ = mood()
        m.display_language = "zh"
        m.apply("u", delta=15, emotions={"sweet": 40})
        self.assertEqual(m.describe("u"), "心情 85/100（欢喜）；甜蜜 40")
        m.apply("u", delta=-70, emotions={"sad": 90})
        self.assertEqual(m.state("u").face, "sad")

    def test_no_answers_move_nothing(self):
        m, _ = mood()
        self.assertIsNone(m.apply_answers("u", {}, "hello"))


if __name__ == "__main__":
    unittest.main()

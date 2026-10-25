import unittest

from mneme_llm.decide import Answer, Chain
from mneme_llm.mood import Mood, MoodSettings
from mneme_llm.store import Store

HOUR = 3600


class Clock:
    now = 1_800_000_000.0

    def __call__(self):
        return self.now


class Judge:
    """A decision tier that returns a fixed mood verdict and records what it was asked."""

    name = "judge"

    def __init__(self, change=None, feeling=None, reason=""):
        self.change, self.feeling, self.reason, self.asked = change, feeling, reason, []

    async def decide(self, input, questions):
        self.asked.append((input, {q.name: q for q in questions}))
        found = {}
        if self.change is not None:
            found["mood_change"] = Answer("mood_change", "score", self.change, max(self.change.values()), self.name,
                                          self.reason)
        if self.feeling is not None:
            found["feeling"] = Answer("feeling", "choice", self.feeling, max(self.feeling.values()), self.name)
        return found


def mood(judge=None, **settings):
    clock = Clock()
    return Mood(Store(":memory:"), "t", decider=Chain(judge) if judge else None, settings=MoodSettings(**settings),
                name="大肥鱼", clock=clock), clock


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
        m, _ = mood(judge)
        event = m.judge("u", [("Leo", "今天考试又没考好……"), ("大肥鱼", "才不笨！")], user="Leo")
        self.assertAlmostEqual(event.delta, 0.58 * 6, places=2)
        self.assertEqual(set(event.emotions), {"tender"})  # 6% of happy is below the noise floor
        self.assertEqual(event.reason, "Leo said “今天考试又没考好……”, felt aching for them")
        self.assertEqual(event.judge, "judge")

    def test_the_question_follows_who_started_it(self):
        judge = Judge(feeling={"sweet": 0.9, "happy": 0.1})
        m, _ = mood(judge)
        m.judge("u", "大肥鱼: 想你了", source="speak-up", user="Leo")
        input, questions = judge.asked[0]
        self.assertIn("reached out to Leo on their own", input)
        self.assertNotIn("Leo", questions["mood_change"].instructions)  # names live in the text, not the question
        self.assertIsNone(m.judge("u", "x", source="runtime"))
        self.assertEqual(len(judge.asked), 1)

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
        m.lang = "zh"
        m.apply("u", delta=15, emotions={"sweet": 40})
        self.assertEqual(m.describe("u"), "心情 85/100（欢喜）；甜蜜 40")
        m.apply("u", delta=-70, emotions={"sad": 90})
        self.assertEqual(m.state("u").face, "sad")

    def test_without_a_decider_judging_does_nothing(self):
        m, _ = mood()
        self.assertIsNone(m.judge("u", "hello"))


if __name__ == "__main__":
    unittest.main()

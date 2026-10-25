import asyncio
import json
import unittest

from mneme_llm.decide import Answer, Chain, Choice, Predicate, Prompt, Score, Unavailable
from mneme_llm.decide.luna import Luna
try:  # the tier is removable; its tests are skipped where it was removed
    from mneme_llm.decide.micro import Micro, signature
except ImportError:
    Micro = signature = None
from mneme_llm.store import Store

REMEMBER = Predicate("remember", "Worth remembering.")
TONE = Choice("tone", "The tone.", {"warm": "kind", "cold": "distant"})
SIZE = Score("size", "How big.", {"1": "small", "2": "medium", "3": "large"})


class Fixed:
    """A tier that answers what it is told to, or fails."""

    def __init__(self, name, answers=None, error=None, learns=False):
        self.name, self.answers, self.error = name, answers or {}, error
        self.lessons = []
        if learns:
            self.learn = lambda input, question, answer: self.lessons.append((input, question.name, answer.by))

    async def adecide(self, input, questions):
        if self.error:
            raise self.error
        return {q.name: self.answers[q.name] for q in questions if q.name in self.answers}


def answer(name, by, **probabilities):
    return Answer(name, "choice", probabilities, max(probabilities.values()), by)


class ChainTests(unittest.TestCase):
    def test_each_question_goes_to_the_first_tier_that_answers(self):
        top = Fixed("top", {"tone": answer("tone", "top", warm=0.9, cold=0.1)})
        low = Fixed("low", {"tone": answer("tone", "low", warm=0.1, cold=0.9),
                            "remember": Answer("remember", "predicate", {"true": 0.8, "false": 0.2}, 0.8, "low")})
        found = Chain(top, low).decide("text", [TONE, REMEMBER])
        self.assertEqual((found["tone"].by, found["remember"].by), ("top", "low"))

    def test_a_failing_tier_falls_through_and_is_counted(self):
        broken = Fixed("broken", error=Unavailable("no key"))
        low = Fixed("low", {"tone": answer("tone", "low", warm=0.6, cold=0.4)})
        chain = Chain(broken, low)
        self.assertEqual(chain.decide("x", [TONE])["tone"].by, "low")
        self.assertEqual(chain.report()["broken"]["failed"], 1)
        self.assertIn("no key", chain.report()["broken"]["last_error"])

    def test_lower_tiers_learn_from_higher_ones_only(self):
        top = Fixed("top", {"tone": answer("tone", "top", warm=1.0, cold=0.0)})
        student = Fixed("student", learns=True)
        bottom = Fixed("bottom", {"remember": Answer("remember", "predicate", {"true": 1, "false": 0}, 1, "bottom")})
        Chain(top, student, bottom).decide("x", [TONE, REMEMBER])
        self.assertEqual(student.lessons, [("x", "tone", "top")])

    def test_unanswered_questions_are_left_out(self):
        self.assertEqual(Chain(Fixed("none")).decide("x", [TONE]), {})
        self.assertEqual(Chain().decide("x", [TONE]), {})

    def test_answer_helpers(self):
        a = Answer("size", "score", {"1": 0.2, "2": 0.3, "3": 0.5}, 0.5, "t")
        self.assertEqual(a.choice, "3")
        self.assertAlmostEqual(a.mean(), 2.3)
        self.assertAlmostEqual(a.mean({"1": -1, "2": 0, "3": 1}), 0.3)


class LunaTests(unittest.TestCase):
    def test_request_body_matches_the_api(self):
        body = Luna("k").body("hello", [REMEMBER, TONE, SIZE])
        self.assertEqual(body["model"], "gpt-6-luna")
        self.assertEqual(body["questions"][1]["choices"][0], {"value": "warm", "description": "kind"})
        self.assertEqual(body["questions"][2]["levels"][2], {"label": "3", "description": "large"})

    def test_parses_each_answer_type(self):
        payload = {"answers": [
            {"type": "predicate", "name": "remember", "probability": 0.2},
            {"type": "choice", "name": "tone", "choice": "warm", "confidence": 0.93,
             "probabilities": [{"value": "warm", "probability": 0.93}, {"value": "cold", "probability": 0.07}]},
            {"type": "score", "name": "size", "score": 1.4, "confidence": 0.45, "probabilities": [
                {"value": 0, "label": "1", "probability": 0.1}, {"value": 1, "label": "2", "probability": 0.45},
                {"value": 2, "label": "3", "probability": 0.45}]}]}
        found = Luna("k").parse(payload, [REMEMBER, TONE, SIZE])
        self.assertAlmostEqual(found["remember"].probability, 0.2)
        self.assertAlmostEqual(found["remember"].confidence, 0.8)
        self.assertEqual(found["tone"].choice, "warm")
        self.assertAlmostEqual(found["size"].mean(), 2.35)
        self.assertEqual(found["size"].by, "luna")

    def test_without_a_key_it_is_unavailable(self):
        with self.assertRaises(Unavailable):
            asyncio.run(Luna("").adecide("x", [REMEMBER]))


class PromptTests(unittest.TestCase):
    def test_asks_and_parses_json_with_reasons(self):
        seen = {}

        def complete(system, user):
            seen["user"] = user
            return ('Sure: {"remember": {"probability": 0.9}, "tone": {"choice": "cold", "confidence": 0.8, '
                    '"reason": "short reply"}, "size": {"level": "9"}}')

        found = Chain(Prompt(complete)).decide("the text", [REMEMBER, TONE, SIZE])
        self.assertIn('"tone" (choice)', seen["user"])
        self.assertAlmostEqual(found["remember"].probability, 0.9)
        self.assertEqual((found["tone"].choice, found["tone"].reason), ("cold", "short reply"))
        self.assertNotIn("size", found)  # a label that does not exist is not an answer

    def test_async_completion_functions_work(self):
        async def complete(system, user):
            return json.dumps({"remember": {"probability": 0.1}})

        found = asyncio.run(Chain(Prompt(complete)).adecide("x", [REMEMBER]))
        self.assertEqual(found["remember"].choice, "false")

    def test_garbage_is_no_answer(self):
        self.assertEqual(Chain(Prompt(lambda s, u: "I cannot")).decide("x", [REMEMBER]), {})


@unittest.skipIf(Micro is None, "the decision micro model is not installed")
class MicroTests(unittest.TestCase):
    def teacher(self, text):
        warm = 0.95 if any(word in text for word in ("thanks", "love", "谢谢", "喜欢")) else 0.05
        return {"tone": answer("tone", "teacher", warm=warm, cold=1 - warm)}

    def lessons(self, micro, count):
        warm = ["thanks so much", "love this", "谢谢你呀", "好喜欢", "thanks, see you", "love you lots"]
        cold = ["whatever", "go away", "不想说", "随便吧", "leave me alone", "no"]
        for i in range(count):
            text = (warm if i % 2 else cold)[(i // 2) % 6]
            micro.learn(text, TONE, self.teacher(text)["tone"])

    def test_abstains_until_trusted_then_answers_like_its_teacher(self):
        store = Store(":memory:")
        micro = Micro(store, min_examples=60, window=40)
        self.assertEqual(asyncio.run(micro.adecide("thanks!", [TONE])), {})
        self.lessons(micro, 120)
        self.assertTrue(micro.trusted(TONE))
        found = asyncio.run(micro.adecide("thanks a lot", [TONE]))
        self.assertEqual((found["tone"].choice, found["tone"].by), ("warm", "micro"))

    def test_learns_through_the_chain_and_survives_a_restart(self):
        store = Store(":memory:")
        teacher = Fixed("teacher")
        micro = Micro(store, min_examples=60, window=40)
        chain = Chain(teacher, micro)
        warm = ["thanks so much", "love this", "谢谢你呀", "好喜欢"]
        cold = ["whatever", "go away", "不想说", "随便吧"]
        for i in range(120):
            text = (warm if i % 2 else cold)[i % 4]
            teacher.answers = self.teacher(text)
            chain.decide(text, [TONE])
        micro.flush()
        again = Micro(store, min_examples=60, window=40)
        self.assertTrue(again.trusted(TONE))
        teacher.error = Unavailable("down")
        found = Chain(teacher, again).decide("love this", [TONE])
        self.assertEqual(found["tone"].by, "micro")

    def test_a_reworded_question_starts_over(self):
        self.assertNotEqual(signature(TONE), signature(Choice("tone", "The mood.", {"warm": "", "cold": ""})))

    def test_unsure_predictions_abstain(self):
        store = Store(":memory:")
        micro = Micro(store, min_examples=10, window=10, min_agreement=0.0, min_confidence=0.99)
        self.lessons(micro, 20)
        self.assertEqual(asyncio.run(micro.adecide("something new entirely", [TONE])), {})


if __name__ == "__main__":
    unittest.main()

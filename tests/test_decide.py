import asyncio
import json
import unittest

from mneme_llm.decide import Answer, Chain, Choice, Predicate, Prompt, Score, Unavailable

REMEMBER = Predicate("remember", "Worth remembering.")
TONE = Choice("tone", "The tone.", {"warm": "kind", "cold": "distant"})
SIZE = Score("size", "How big.", {"1": "small", "2": "medium", "3": "large"})


class Fixed:
    """A tier that answers what it is told to, or fails."""

    def __init__(self, name, answers=None, error=None):
        self.name, self.answers, self.error = name, answers or {}, error

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

    def test_unanswered_questions_are_left_out(self):
        self.assertEqual(Chain(Fixed("none")).decide("x", [TONE]), {})
        self.assertEqual(Chain().decide("x", [TONE]), {})

    def test_answer_helpers(self):
        a = Answer("size", "score", {"1": 0.2, "2": 0.3, "3": 0.5}, 0.5, "t")
        self.assertEqual(a.choice, "3")
        self.assertAlmostEqual(a.mean(), 2.3)
        self.assertAlmostEqual(a.mean({"1": -1, "2": 0, "3": 1}), 0.3)


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


if __name__ == "__main__":
    unittest.main()

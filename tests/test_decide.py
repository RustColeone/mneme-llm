import asyncio
import json
import unittest

from mneme_llm.decide import Answer, Choice, Predicate, Prompt, Score

REMEMBER = Predicate("remember", "Worth remembering.")
TONE = Choice("tone", "The tone.", {"warm": "kind", "cold": "distant"})
SIZE = Score("size", "How big.", {"1": "small", "2": "medium", "3": "large"})


class AnswerTests(unittest.TestCase):
    def test_answer_helpers(self):
        a = Answer("size", {"1": 0.2, "2": 0.3, "3": 0.5}, 0.5, "t")
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

        found = asyncio.run(Prompt(complete).adecide("the text", [REMEMBER, TONE, SIZE]))
        self.assertIn('"tone" (choice)', seen["user"])
        self.assertAlmostEqual(found["remember"].probability, 0.9)
        self.assertEqual((found["tone"].choice, found["tone"].reason), ("cold", "short reply"))
        self.assertNotIn("size", found)  # a label that does not exist is not an answer

    def test_async_completion_functions_work(self):
        async def complete(system, user):
            return json.dumps({"remember": {"probability": 0.1}})

        found = asyncio.run(Prompt(complete).adecide("x", [REMEMBER]))
        self.assertEqual(found["remember"].choice, "false")

    def test_garbage_is_no_answer(self):
        self.assertEqual(asyncio.run(Prompt(lambda s, u: "I cannot").adecide("x", [REMEMBER])), {})


if __name__ == "__main__":
    unittest.main()

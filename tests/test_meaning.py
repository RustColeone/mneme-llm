import asyncio
import unittest

from mneme_llm import Embeddings, Mneme
from mneme_llm.decide import Unavailable
from mneme_llm.meaning import Meaning, cosine, normalize, pack, unpack
try:  # the tiers are removable; their tests are skipped where they were removed
    from mneme_llm.meaning.micro import TermCentroids
except ImportError:
    TermCentroids = None
try:
    from mneme_llm.meaning.unify import Unify
except ImportError:
    Unify = None

# A toy embedding space: each concept is one direction, in either language.
CONCEPTS = {"cat": 0, "猫": 0, "年糕": 0, "kitten": 0, "exam": 1, "考试": 1, "math": 1, "数学": 1,
            "tea": 2, "茶": 2, "coffee": 3, "咖啡": 3}


def toy(texts):
    vectors = []
    for text in texts:
        vector = [0.0] * 6
        vector[5] = 0.2  # every text shares a little of one direction, like real embeddings
        for word, axis in CONCEPTS.items():
            if word in text.lower():
                vector[axis] += 1.0
        vectors.append(vector)
    return vectors


class Flaky:
    """An embedder that works until told not to."""

    def __init__(self, name="toy:1"):
        self.name, self.up, self.calls = name, True, 0

    async def embed(self, texts):
        self.calls += 1
        if not self.up:
            raise Unavailable("down")
        return [normalize(v) for v in toy(texts)]


def mneme(**options):
    return Mneme(":memory:", "t", luna=False, micro=False, language=None, **options)


class VectorTests(unittest.TestCase):
    def test_pack_and_cosine(self):
        vector = normalize([3.0, 4.0])
        self.assertAlmostEqual(cosine(unpack(pack(vector)), vector), 1.0, places=5)


class EmbeddingTierTests(unittest.TestCase):
    def test_a_chinese_question_finds_an_english_note_by_meaning(self):
        m = mneme(embed=Embeddings(toy, name="toy:1"))
        m.remember("u", "Has a cat named Mochi", kind="fact", importance=3)
        m.remember("u", "Drinks coffee every morning", kind="preference", importance=3)
        self.assertEqual(m.recall("u", "我的猫叫什么", important=0, recent=0).chosen, [])  # words alone miss
        found = asyncio.run(m.arecall("u", "我的猫叫什么", important=0, recent=0))
        self.assertEqual([r.note.text for r in found.chosen], ["Has a cat named Mochi"])
        self.assertTrue(found.chosen[0].why.startswith("similar"))
        self.assertEqual(found.tier, "embeddings")

    def test_vectors_belong_to_their_embedder(self):
        store_path = ":memory:"
        m = mneme(embed=Embeddings(toy, name="toy:1"))
        note = m.remember("u", "Has a cat", kind="fact")
        asyncio.run(m.arecall("u", "cat"))
        self.assertIn(note.id, m.meaning.vectors([note.id]))
        other = Meaning(m.store, Embeddings(toy, name="toy:2"))
        self.assertEqual(other.vectors([note.id]), {})  # another model's vectors are never mixed in
        self.assertEqual(asyncio.run(other.prepare_vectors([note])), 1)

    def test_forgotten_notes_lose_their_vectors_when_purged(self):
        m = mneme(embed=Embeddings(toy, name="toy:1"))
        note = m.remember("u", "Has a cat", kind="fact")
        asyncio.run(m.arecall("u", "cat"))
        m.forget("u", id=note.id)
        m.memory.purge()
        self.assertEqual(m.store.row("select count(*) as n from vectors")["n"], 0)

    def test_a_failing_provider_rests_instead_of_being_waited_on(self):
        flaky = Flaky()
        m = mneme(embed=flaky)
        m.remember("u", "Has a cat", kind="fact")
        flaky.up = False
        asyncio.run(m.arecall("u", "猫"))
        calls = flaky.calls
        asyncio.run(m.arecall("u", "猫"))
        self.assertEqual(flaky.calls, calls)  # resting: not asked again right away
        self.assertIn("embeddings", m.meaning.report()["failures"])


@unittest.skipIf(TermCentroids is None, "the meaning micro tier is not installed")
class MicroTierTests(unittest.TestCase):
    def test_centroids_answer_offline_after_learning_and_abstain_before(self):
        flaky = Flaky()
        m = mneme(embed=flaky)
        m.meaning.micro.min_texts = 6
        for text in ("Has a cat named Mochi", "Drinks coffee every morning", "Math exam on Friday",
                     "Likes green tea", "我的猫很可爱", "明天数学考试", "喜欢喝茶", "早上喝咖啡"):
            m.remember("u", text, kind="fact")
        flaky.up = False
        self.assertIsNone(m.meaning.micro.vector("猫"))  # nothing learned yet: abstain
        flaky.up = True
        asyncio.run(m.arecall("u", "tea"))  # embeds every note: the centroids learn
        flaky.up = False
        m.meaning.rest.until = 0
        found = asyncio.run(m.arecall("u", "猫", important=0, recent=0))
        self.assertEqual(found.tier, "micro")
        self.assertIn("Has a cat named Mochi", [r.note.text for r in found.chosen])
        self.assertIsNone(m.meaning.micro.vector("完全陌生的词语"))  # unknown words: abstain

    def test_the_micro_tier_can_be_left_out(self):
        m = mneme(embed=Embeddings(toy, name="toy:1"), meaning_micro=False)
        self.assertIsNone(m.meaning.micro)


@unittest.skipIf(Unify is None, "the unify tier is not installed")
class UnifyTierTests(unittest.TestCase):
    def complete(self, calls):
        async def complete(system, user):
            calls.append(system)
            if "Translate" in system:
                return {"我的猫叫什么": "what is my cat called"}.get(user, user)
            return '["The math exam is on Friday"]'
        return complete

    def test_a_query_in_another_script_is_translated_and_notes_get_glosses(self):
        calls = []
        m = Mneme(":memory:", "t", luna=False, micro=False, embed=False, complete=self.complete(calls))
        m.remember("u", "Has a cat named Mochi", kind="fact")
        m.remember("u", "周五有数学考试", kind="plan")
        found = asyncio.run(m.arecall("u", "我的猫叫什么", important=0, recent=0))
        self.assertEqual((found.tier, [r.note.text for r in found.chosen]), ("unify", ["Has a cat named Mochi"]))
        glossed = {n.text: n.gloss for n in m.memory.notes("u")}
        self.assertEqual(glossed["周五有数学考试"], "The math exam is on Friday")
        self.assertEqual(glossed["Has a cat named Mochi"], "Has a cat named Mochi")  # already English: kept
        asyncio.run(m.arecall("u", "我的猫叫什么"))
        self.assertEqual(sum("Translate" in call for call in calls), 1)  # the translation is remembered
        self.assertIn("周五有数学考试", [r.note.text for r in m.recall("u", "exam Friday", recent=0).chosen])  # by gloss

    def test_without_any_chat_model_unify_quietly_stands_aside(self):
        m = Mneme(":memory:", "t", luna=False, micro=False, embed=False)
        m.remember("u", "Has a cat", kind="fact")
        found = asyncio.run(m.arecall("u", "我的猫"))
        self.assertEqual(found.tier, "")
        self.assertNotIn("unify", m.meaning.report()["failures"])  # not asked: no model is no failure

        async def complete(system, user):  # and a call that brings one is not turned away
            return "my cat" if system.startswith("Translate") else '["Has a cat"]'
        found = asyncio.run(m.arecall("u", "我的猫", complete=complete))
        self.assertEqual((found.tier, [r.note.text for r in found.chosen]), ("unify", ["Has a cat"]))

    def test_the_language_decides_which_script_is_foreign(self):
        self.assertTrue(Unify(None, "English").needs_translation("我的猫"))
        self.assertFalse(Unify(None, "Chinese").needs_translation("我的猫"))
        self.assertTrue(Unify(None, "中文").needs_translation("my cat"))


if __name__ == "__main__":
    unittest.main()

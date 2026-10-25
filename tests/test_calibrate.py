import asyncio
import os
import tempfile
import unittest

from mneme_llm import Embeddings, Mneme
from mneme_llm.meaning import FLOOR, calibrate
from mneme_llm.providers import Unavailable

# A fake model of known geometry. Each set text has its topic's direction and one of its own, and all share a
# little of one more: a message and its note are 0.556 alike, texts of two topics 0.111, so the floor is 0.333.
TOPIC, OWN, FILE, SHARED = 0, 32, 96, 700
PLACES = {}
for index, (_, message, note) in enumerate(calibrate.TOPICS):
    PLACES[message], PLACES[note] = (index, OWN + 2 * index), (index, OWN + 2 * index + 1)


def model(alike: float = 0.5, calls: list | None = None):
    """The model; a file's note "note <n>" has a direction of its own and `alike` of the shared one (two such
    notes are alike²/(alike²+1): 0.2 at 0.5)."""
    def embed(texts):
        if calls is not None:
            calls.append(len(texts))
        vectors = []
        for text in texts:
            vector = [0.0] * (SHARED + 1)
            if text in PLACES:
                topic, own = PLACES[text]
                vector[topic] = vector[own] = 1.0
                vector[SHARED] = 0.5
            elif text.startswith("note "):
                vector[FILE + int(text.split()[1])] = 1.0
                vector[SHARED] = alike
            else:
                vector[SHARED] = 1.0
            vectors.append(vector)
        return vectors
    return embed


def mneme(embed, path=":memory:"):
    return Mneme(path, "t", luna=False, micro=False, memory_language=None, embed=embed)


def recall(m, query="anything"):
    return asyncio.run(m.arecall("u", query))


class SetTests(unittest.TestCase):
    def test_the_set_places_the_floor_between_related_and_unrelated_pairs(self):
        calls = []
        m = mneme(Embeddings(model(calls=calls), name="geo"))
        m.remember("u", "note 1", kind="fact")
        recall(m)
        self.assertEqual(calls, [1, 2 * len(calibrate.TOPICS), 1])  # the note, the set (one request), the query
        self.assertAlmostEqual(m.meaning.floor, 0.333, places=3)
        self.assertAlmostEqual(asyncio.run(m.meaning.query("anything")).floor, 0.333, places=3)
        report = m.report()["meaning"]["floor"]
        self.assertEqual((report["by"], report["set"]["related"], report["set"]["unrelated"]), ("set", 0.556, 0.111))
        before = len(calls)
        recall(m)
        self.assertEqual(calls[before:], [1])  # measured once: later recalls embed only their query

    def test_a_model_that_cannot_tell_the_pairs_apart_keeps_the_default(self):
        m = mneme(Embeddings(lambda texts: [[1.0, 0.0]] * len(texts), name="flat"))
        m.remember("u", "note 1", kind="fact")
        recall(m)
        self.assertEqual(m.meaning.floor, FLOOR)
        self.assertEqual(m.report()["meaning"]["floor"]["by"], "default (the set did not separate)")

    def test_a_given_floor_is_never_measured(self):
        calls = []
        m = mneme(Embeddings(model(calls=calls), name="geo", floor=0.5))
        m.remember("u", "note 1", kind="fact")
        recall(m)
        self.assertEqual(calls, [1, 1])
        self.assertEqual((m.meaning.floor, m.report()["meaning"]["floor"]), (0.5, {"value": 0.5, "by": "given"}))

    def test_each_model_is_measured_once_per_file(self):
        path = os.path.join(tempfile.mkdtemp(), "f.db")
        calls = []
        m = mneme(Embeddings(model(calls=calls), name="geo"), path)
        m.remember("u", "note 1", kind="fact")
        recall(m)
        m.close()
        m = mneme(Embeddings(model(calls=calls), name="geo"), path)
        recall(m)
        self.assertEqual(calls.count(2 * len(calibrate.TOPICS)), 1)  # read back, not measured again
        m.close()
        m = mneme(Embeddings(model(calls=calls), name="geo:large"), path)  # another model: its own floor
        recall(m)
        self.assertEqual(calls.count(2 * len(calibrate.TOPICS)), 2)
        m.close()

    def test_a_record_from_an_older_set_is_measured_again(self):
        calls = []
        m = mneme(Embeddings(model(calls=calls), name="geo"))
        m.store.set_meta("floor:geo", '{"version": 0, "floor": 0.9}')
        self.assertEqual(m.meaning.floor, FLOOR)
        m.remember("u", "note 1", kind="fact")
        recall(m)
        self.assertAlmostEqual(m.meaning.floor, 0.333, places=3)

    def test_a_failed_measurement_keeps_the_default_and_tries_again_later(self):
        state = {"down": True}

        def embed(texts):
            if len(texts) > 1 and state["down"]:
                raise Unavailable("too many at once today")
            return model()(texts)
        m = mneme(Embeddings(embed, name="geo"))
        m.remember("u", "note 1", kind="fact")
        self.assertEqual([r.note.text for r in recall(m, "note").chosen], ["note 1"])  # word matching still works
        self.assertIsNone(calibrate.read(m.store, "geo"))
        self.assertIn("embeddings", m.report()["meaning"]["failures"])
        state["down"] = False
        m.meaning.rest.until = 0  # the pause after a failure is over
        recall(m)
        self.assertAlmostEqual(m.meaning.floor, 0.333, places=3)

    def test_two_recalls_at_once_measure_once(self):
        calls = []

        async def slow(texts):
            calls.append(len(texts))
            await asyncio.sleep(0.01)
            return model()(texts)
        m = mneme(Embeddings(slow, name="geo"))
        m.remember("u", "note 1", kind="fact")

        async def both():
            await asyncio.gather(m.arecall("u", "a"), m.arecall("u", "b"))
        asyncio.run(both())
        self.assertEqual(calls.count(2 * len(calibrate.TOPICS)), 1)


class FileTests(unittest.TestCase):
    def notes(self, m, first: int, last: int) -> None:
        for n in range(first, last):
            m.remember("u", f"note {n}", kind="fact")

    def test_the_files_own_notes_move_the_floor_as_it_grows(self):
        m = mneme(Embeddings(model(alike=0.5), name="geo"))
        self.notes(m, 0, 150)
        recall(m)
        self.assertEqual(m.report()["meaning"]["floor"]["by"], "set")  # too few notes yet
        self.notes(m, 150, 250)
        recall(m)
        report = m.report()["meaning"]["floor"]
        self.assertEqual((report["by"], report["file"]["at"], report["file"]["background"]), ("file", 250, 0.2))
        self.assertAlmostEqual(m.meaning.floor, 0.333 + 0.089, places=2)  # by how much more alike they are
        self.notes(m, 250, 400)
        recall(m)
        self.assertEqual(m.report()["meaning"]["floor"]["file"]["at"], 250)  # not yet twice as many
        self.notes(m, 400, 500)
        recall(m)
        self.assertEqual(m.report()["meaning"]["floor"]["file"]["at"], 500)

    def test_the_file_moves_the_floor_by_a_tenth_at_most(self):
        m = mneme(Embeddings(model(alike=1.0), name="geo"))  # notes 0.5 alike, the set's 0.111
        self.notes(m, 0, 220)
        recall(m)
        self.assertAlmostEqual(m.meaning.floor, 0.333 + calibrate.SHIFT, places=3)


if __name__ == "__main__":
    unittest.main()

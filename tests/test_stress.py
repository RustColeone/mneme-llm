"""Stress and edge cases: random operations, threads, processes, concurrent coroutines, many notes, a killed writer,
and odd input at every entry point; after each, the file must still keep every rule (`tests/invariants.py`).

The default sizes keep this to seconds; MNEME_STRESS=heavy runs five times as much.
"""

import asyncio
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from mneme_llm import Embeddings, Mneme
from mneme_llm.tools import Toolbox
from tests.invariants import check

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCALE = 5 if os.environ.get("MNEME_STRESS") == "heavy" else 1
SUBJECTS = ["u", "v", "discord:42", "Leo 大肥鱼"]
KEYS = ["user.city", "pet.name", "food.likes", "猫.名字", None, None, None]
WORDS = ["tea", "cat", "exam", "Friday", "Hangzhou", "metformin", "Straße", "STRASSE", "猫", "考试", "周五", "抹茶",
         "Мурка", "σοφός", "שָׁלוֹם", "نمی‌خواهم", "नमस्ते", "İstanbul", "don’t", "🐱", "café"]
ODD = ["", "   ", "​‍", "́́", "a\x00b\x1b[31m", "bad \ud800 half", "line\nbreak sep",
       "x" * 3000, "‮evil", "\t\r\n"]


def embed(texts):  # deterministic: one direction per word, so similar notes are close
    vectors = []
    for text in texts:
        vector = [0.05] * 8
        for word in text.lower().split():
            vector[int(hashlib.md5(word.encode("utf-8", "replace")).hexdigest(), 16) % 8] += 1.0
        vectors.append(vector)
    return vectors


def open_memory(path=":memory:", **options):
    options = {"luna": False, "micro": False, "memory_language": None, "embed": Embeddings(embed, name="toy:8"),
               **options}
    return Mneme(path, "t", **options)


def sentence(rng: random.Random) -> str:
    if rng.random() < 0.08:
        return rng.choice(ODD)
    return " ".join(rng.choice(WORDS) for _ in range(rng.randint(1, 6)))


def act(m: Mneme, rng: random.Random) -> None:
    """One random operation, the kind a busy host makes. Only ValueError and TypeError (for odd input) may come out."""
    subject = rng.choice(SUBJECTS)
    roll = rng.random()
    try:
        if roll < 0.40:
            m.memory.keep(subject, sentence(rng), kind=rng.choice([None, "fact", "preference", "episode", "plan"]),
                          key=rng.choice(KEYS), importance=rng.randint(1, 5),
                          feeling=rng.choice([0.0, 0.5, -1.0, math.nan, 7.0]),
                          happened_at=rng.choice([None, None, time.time() + rng.randint(-10 ** 7, 10 ** 7), 1e300]))
        elif roll < 0.50:
            live = m.memory.notes(subject)
            if live:
                note = rng.choice(live)
                m.memory.keep(subject, note.text.upper(), key=rng.choice(KEYS[:4]))  # same words, maybe a takeover
        elif roll < 0.58:
            live = m.memory.notes(subject)
            if live and rng.random() < 0.5:
                m.memory.forget(subject, id=rng.choice(live).id)
            else:
                m.memory.forget(subject, key=rng.choice(KEYS[:4]))
        elif roll < 0.61:
            m.memory.purge(rng.choice([None, subject]))
        elif roll < 0.63:
            m.memory.erase(subject)
        elif roll < 0.80:
            asyncio.run(m.arecall(subject, sentence(rng)))
        elif roll < 0.85:
            m.memory.set_profile(subject, rng.choice([None, sentence(rng)]))
        elif roll < 0.90:
            m.mood.apply(subject, delta=rng.uniform(-12, 12), emotions={rng.choice(["happy", "sad", "worried"]):
                                                                         rng.uniform(0, 60)})
        elif roll < 0.92:  # roles given, visits, roles taken away; a second creator or a closeness off the band fails
            step = rng.random()
            if step < 0.5:
                m.relate(subject, rng.choice(["creator", "family", "friend", "acquaintance", "boss"]),
                         closeness=rng.choice([None, None, rng.uniform(-10, 110), math.nan]))
            elif step < 0.9:
                m.relations.seen(subject)
            else:
                rng.choice([m.relations.remove, m.erase])(subject)
        elif roll < 0.95:
            m.memory.context(subject, sentence(rng))
        elif roll < 0.96:  # notes as an earlier build left them, before the folded text was kept
            m.store.execute("update memories set folded = null where id % 3 = 0")
        elif roll < 0.98:
            data = m.export_data()
            copy = open_memory(":memory:")
            copy.import_data(data)
            assert not check(copy.store), check(copy.store)
            copy.close()
        elif m.store.row("select (select count(*) from memories) + (select count(*) from mood_events) as n")["n"] \
                < 400:  # (each one doubles the notes, hidden copies included)
            m.import_data(m.export_data())  # brought back into its own file: every note a duplicate of itself
    except (ValueError, TypeError):
        pass


def worker(path: str, seed: int, steps: int) -> None:  # one process of the multi-process test
    rng = random.Random(seed)
    m = open_memory(path)
    for _ in range(steps):
        act(m, rng)
    m.close()


class RandomOperationTests(unittest.TestCase):
    def test_random_operations_keep_every_rule(self):
        for seed in range(3):
            m = open_memory(os.path.join(tempfile.mkdtemp(), "f.db"))
            rng = random.Random(seed)
            for step in range(200 * SCALE):
                act(m, rng)
                if step % 50 == 49:
                    self.assertEqual(check(m.store), [], f"seed {seed}, step {step}")
            m.close()

    def test_two_connections_on_one_file_keep_every_rule(self):
        path = os.path.join(tempfile.mkdtemp(), "f.db")
        first, second, rng = open_memory(path), open_memory(path), random.Random(7)
        for _ in range(200 * SCALE):
            act(rng.choice([first, second]), rng)
        self.assertEqual(check(first.store), [])
        first.close()
        second.close()

    def test_export_and_import_give_back_the_same_live_notes(self):
        m = open_memory()
        rng = random.Random(3)
        for _ in range(300):
            act(m, rng)

        def live(memory):
            return sorted((n.subject, n.text, n.key, n.kind, n.importance) for subject in memory.memory.subjects()
                          for n in memory.memory.notes(subject))
        copy = open_memory()
        copy.import_data(m.export_data())
        self.assertEqual(live(copy), live(m))


class ConcurrencyTests(unittest.TestCase):
    def test_threads_sharing_one_memory(self):
        m = open_memory(os.path.join(tempfile.mkdtemp(), "f.db"))
        errors = []

        def run(seed):
            rng = random.Random(seed)
            try:
                for _ in range(60 * SCALE):
                    act(m, rng)
            except Exception as error:  # anything but odd-input errors is a failure
                errors.append(repr(error))
        threads = [threading.Thread(target=run, args=(seed,)) for seed in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(check(m.store), [])
        m.close()

    def test_processes_writing_one_file(self):
        path = os.path.join(tempfile.mkdtemp(), "f.db")
        open_memory(path).close()
        env = dict(os.environ, PYTHONPATH=ROOT)
        env.pop("OPENAI_API_KEY", None)
        code = ("import sys; from tests.test_stress import worker; "
                "worker(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))")
        started = [subprocess.Popen([sys.executable, "-c", code, path, str(seed), str(40 * SCALE)], env=env, cwd=ROOT,
                                    stderr=subprocess.PIPE) for seed in range(3)]
        for process in started:
            _, error = process.communicate(timeout=300)
            self.assertEqual(process.returncode, 0, error.decode(errors="replace")[-2000:])
        m = open_memory(path)
        self.assertEqual(check(m.store), [])
        m.close()

    def test_many_coroutines_at_once(self):
        async def slow(texts):
            await asyncio.sleep(random.random() / 100)
            return embed(texts)

        async def writer(system, user):
            await asyncio.sleep(random.random() / 100)
            return json.dumps([{"text": "Likes 抹茶 tea", "kind": "preference", "key": "food.likes"},
                               {"text": "Exam on 10月30日", "kind": "plan"}, {"kind": "fact"}])

        async def scenario():
            m = open_memory(embed=Embeddings(slow, name="toy:8"), complete=writer)
            for index in range(30):
                m.remember(SUBJECTS[index % 4], f"note {index} about tea and 猫", kind="fact")
            jobs = [m.arecall(SUBJECTS[index % 4], "tea 猫") for index in range(40)]
            jobs += [m.aobserve(SUBJECTS[index % 4], [{"role": "user", "content": "I like matcha"}], user_name="Leo",
                                mood=False, gate=0) for index in range(20)]
            jobs += [asyncio.to_thread(m.memory.erase, "v") for _ in range(3)]
            results = await asyncio.gather(*jobs, return_exceptions=True)
            return m, [result for result in results if isinstance(result, Exception) or getattr(result, "error", "")]
        m, errors = asyncio.run(scenario())
        self.assertEqual(errors, [])
        self.assertEqual(check(m.store), [])


class ScaleTests(unittest.TestCase):
    def test_a_full_subject_stays_quick_and_within_its_cap(self):
        m = open_memory(embed=False)
        m.memory.max_notes = 1000 * SCALE
        with m.store.transaction():
            for index in range(1100 * SCALE):
                m.memory.keep("u", f"day {index} we talked about tea, exams and the cat {index % 97}",
                              importance=1 + index % 3)
        self.assertLessEqual(len(m.memory.notes("u")), m.memory.max_notes)
        m.recall("u", "tea")  # fills the terms cache
        started = time.perf_counter()
        for query in ("tea exams", "cat 42", "考试", ""):
            m.memory.context("u", query)
        self.assertLess(time.perf_counter() - started, 4.0 * SCALE)
        self.assertEqual(check(m.store), [])

    def test_a_long_history_is_recalled_quickly(self):
        """A person with a very long history: recall reads the term index, not every note, and meaning looks
        among a bounded window; the oldest note is still found by its words."""
        m = open_memory(os.path.join(tempfile.mkdtemp(), "long.db"))
        m.memory.max_notes = 10 ** 6
        count, rng, now = 20_000 * SCALE, random.Random(5), time.time()
        words = "tea cat exam friday hangzhou cello hiking coffee sister work deadline paper train rain".split()
        with m.store.transaction():  # an old file's notes, written straight into the table to be quick
            for index in range(count):
                text = " ".join(rng.choice(words) for _ in range(5)) + f" day {index}"
                m.store.execute("insert into memories (space, subject, kind, text, importance, feeling, happened_at, "
                                "created_at, folded) values ('t', 'u', ?, ?, ?, 0, ?, ?, ?)",
                                (rng.choice(["episode", "plan", "fact"]), text, 1 + index % 4, now - index * 600,
                                 now - index * 600, text.casefold()))
            m.store.execute("update memories set text = 'Adopted a cat named Mochi long ago', folded = 'adopted a cat "
                            "named mochi long ago' where id = 1")
        m.recall("u", "tea")  # indexes the old notes, once
        m.remember("u", "Started learning the cello", kind="episode")  # indexed as it is written
        started = time.perf_counter()
        found = m.recall("u", "Mochi", important=0, recent=0)
        rare = time.perf_counter() - started
        self.assertEqual([r.note.id for r in found.chosen], [1])  # the oldest note, by a rare word
        started = time.perf_counter()
        asyncio.run(m.arecall("u", "cello hiking"))
        asyncio.run(m.arecall("u", "cello hiking"))
        meaning = (time.perf_counter() - started) / 2
        self.assertLess(rare, 1.0)
        self.assertLess(meaning, 4.0 * SCALE)
        self.assertLessEqual(len(m.meaning.vectors(list(range(1, count + 2)))), m.memory.semantic_window + 1)
        self.assertEqual(check(m.store), [])
        m.close()

    def test_many_subjects(self):
        m = open_memory(embed=False)
        with m.store.transaction():
            for subject in range(300 * SCALE):
                for index in range(5):
                    m.memory.keep(f"s{subject}", f"note {index} of s{subject}", key=f"k.n{index}")
        self.assertEqual(len(m.memory.subjects()), 300 * SCALE)
        m.memory.erase("s7")
        self.assertEqual(m.memory.notes("s7"), [])
        self.assertEqual(len(m.memory.notes("s8")), 5)
        self.assertEqual(check(m.store), [])

    def test_a_huge_query_and_a_huge_mcp_line(self):
        m = open_memory(embed=False)
        m.remember("u", "Likes tea", kind="preference")
        started = time.perf_counter()
        self.assertEqual(len(m.recall("u", "tea " * 50000, important=0, recent=0).chosen), 1)
        self.assertLess(time.perf_counter() - started, 3.0)
        self.assertTrue(Toolbox(m, "u").call("recall", {"query": "x" * 1_000_000}))


class CrashTests(unittest.TestCase):
    def test_a_writer_killed_mid_transaction_leaves_a_sound_file(self):
        path = os.path.join(tempfile.mkdtemp(), "f.db")
        m = open_memory(path, embed=False)
        m.remember("u", "Kept before the crash", kind="fact")
        m.close()
        code = ("import sys, time\nfrom mneme_llm import Mneme\n"
                "m = Mneme(sys.argv[1], 't', luna=False, micro=False, embed=False, memory_language=None)\n"
                "with m.store.transaction():\n"
                "    for index in range(2000):\n"
                "        m.memory.keep('u', f'half written {index}')\n"
                "    print('inside', flush=True)\n"
                "    time.sleep(60)\n")
        env = dict(os.environ, PYTHONPATH=ROOT)
        env.pop("OPENAI_API_KEY", None)
        process = subprocess.Popen([sys.executable, "-c", code, path], env=env, stdout=subprocess.PIPE)
        self.assertEqual(process.stdout.readline().strip(), b"inside")
        process.kill()
        process.wait(timeout=30)
        process.stdout.close()
        m = open_memory(path, embed=False)
        self.assertEqual([n.text for n in m.memory.notes("u")], ["Kept before the crash"])
        self.assertEqual(check(m.store), [])
        m.remember("u", "Kept after the crash", kind="fact")  # and it is writable
        m.close()


class OddInputTests(unittest.TestCase):
    def test_every_odd_text_is_refused_or_kept_clean(self):
        m = open_memory(embed=False)
        for text in ODD + ["normal"]:
            try:
                note = m.remember("u", text, kind="fact")
            except ValueError:
                continue
            self.assertEqual(note.text, " ".join(note.text.split()))
        self.assertEqual(check(m.store), [])
        texts_kept = [n.text for n in m.memory.notes("u")]
        self.assertIn("bad � half", texts_kept)
        self.assertIn("ab[31m", texts_kept)

    def test_odd_values_are_refused_with_plain_errors(self):
        m = open_memory(embed=False)
        for call in (lambda: m.remember(None, "x"), lambda: m.remember("", "x"), lambda: m.remember("u", 5),
                     lambda: m.remember("u", "x", happened_at=math.nan), lambda: m.remember("u", "x", happened_at=1e20),
                     lambda: m.remember("u", "x", importance=math.nan), lambda: m.recall("u", None),
                     lambda: m.observe("u", None), lambda: m.memory.set_profile("u", 5),
                     lambda: m.mood.apply("u", delta=math.nan), lambda: m.mood.apply(None, delta=1)):
            with self.assertRaises((ValueError, TypeError)):
                call()
        self.assertEqual(m.remember("u", "x", feeling=math.nan).feeling, 0.0)
        self.assertEqual(m.recall("u", "tea \ud800").query, "tea �")
        m.memory.set_profile("u", "warm \ud800 and kind")
        self.assertIn("�", m.memory.profile("u"))
        self.assertEqual(check(m.store), [])

    def test_chat_messages_are_read_as_an_exchange(self):
        from mneme_llm.exchange import as_text as exchange
        self.assertEqual(exchange([{"role": "user", "content": "hi"}, {"name": "Leo", "content": [
            {"type": "text", "text": "I like tea"}]}, ("大肥鱼", "好呀")]), "user: hi\nLeo: I like tea\n大肥鱼: 好呀")
        with self.assertRaises(TypeError):
            exchange({"role": "user", "content": "hi"})

    def test_odd_tool_calls_come_back_as_text(self):
        box = Toolbox(open_memory(embed=False), "u")
        for arguments in ('{"text": "t", "kind": "fact", "feeling": NaN}', '{"text": "t", "importance": Infinity}',
                          '{"text": "\\ud800", "kind": "fact"}', '{"query": null}', '{"text": "", "kind": "fact"}',
                          '{"text": "t", "kind": "plan", "date": "2026-02-30"}', "[" * 10000, '{"id": "1"}'):
            for name in ("remember", "recall", "forget", "mood"):
                self.assertIsInstance(box.call(name, arguments), str)


if __name__ == "__main__":
    unittest.main()

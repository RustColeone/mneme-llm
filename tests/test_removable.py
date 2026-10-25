"""The optional tiers really are optional: with each one's file deleted (and with all three), everything else still
works. Each case copies the package, deletes the file, and runs every kind of call in a fresh interpreter."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIERS = ("decide/micro.py", "meaning/micro.py", "meaning/unify.py")

SMOKE = r'''
import asyncio, io, json, os, sys
from mneme_llm import Embeddings, Mneme
from mneme_llm.mcp import serve
from mneme_llm.tools import Toolbox

def embed(texts):
    return [[1.0 + ("tea" in text), 1.0 + ("猫" in text), 0.5] for text in texts]

async def complete(system, user):
    if system.startswith("You judge"):
        return json.dumps({"worth_remembering": {"probability": 0.9}, "mood_change": {"level": "1"},
                           "feeling": {"choice": "happy"}})
    if system.startswith("Write a short impression"):
        return "Likes tea."
    if system.startswith("Rewrite each numbered note"):
        return json.dumps([line.split(". ", 1)[1] for line in user.splitlines()])
    if system.startswith("Translate"):
        return "my cat"
    return json.dumps([{"text": "Likes oolong tea", "kind": "preference", "key": "food.tea"}])

path = os.path.join(sys.argv[1], "m.db")
m = Mneme(path, "t", embed=Embeddings(embed, name="toy"), complete=complete, luna=False)
m.remember("u", "Has a cat named Mochi", kind="fact")
m.remember("u", "我的猫叫年糕", kind="fact")
assert m.recall("u", "cat").chosen
asyncio.run(m.arecall("u", "猫"))
assert "Mochi" in asyncio.run(m.aprompt("u", "cat", user="Leo"))
seen = m.observe("u", [("Leo", "I love oolong tea"), ("bot", "nice")], user="Leo")
assert not seen.error and seen.notes, seen
assert m.reflect("u") == "Likes tea."
box = Toolbox(m, "u")
assert box.call("remember", {"text": "Plays cello", "kind": "fact"}).startswith("Kept")
assert "cello" in asyncio.run(box.acall("recall", {"query": "cello"}))
out = io.StringIO()
serve(m, "u", io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"), out)
assert "remember" in out.getvalue()
data = m.export_data()
other = Mneme(os.path.join(sys.argv[1], "n.db"), "t", embed=False, luna=False, language=None)
assert other.import_data(data) >= 3
m.report()
assert m.erase("u") >= 3 and not m.memory.notes("u")
m.close()
other.close()
print("smoke ok")
'''


class RemovableTierTests(unittest.TestCase):
    def run_without(self, *tiers):
        folder = tempfile.mkdtemp()
        shutil.copytree(os.path.join(ROOT, "mneme_llm"), os.path.join(folder, "mneme_llm"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        for tier in tiers:
            if os.path.exists(os.path.join(folder, "mneme_llm", tier)):  # (an install may lack it already)
                os.remove(os.path.join(folder, "mneme_llm", tier))
        env = dict(os.environ, PYTHONPATH=folder)
        env.pop("OPENAI_API_KEY", None)
        done = subprocess.run([sys.executable, "-c", SMOKE, folder], env=env, cwd=folder, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(done.returncode, 0, f"without {tiers}:\n{done.stderr[-3000:]}")
        self.assertIn("smoke ok", done.stdout)
        cli = subprocess.run([sys.executable, "-m", "mneme_llm", "--db", os.path.join(folder, "c.db"), "micro"],
                             env=env, cwd=folder, capture_output=True, text=True, timeout=60)
        self.assertEqual(cli.returncode, 0, cli.stderr[-2000:])

    def test_everything_works_with_all_tiers(self):
        self.run_without()

    def test_each_tier_can_be_deleted(self):
        for tier in TIERS:
            with self.subTest(tier=tier):
                self.run_without(tier)

    def test_all_three_can_be_deleted(self):
        self.run_without(*TIERS)


if __name__ == "__main__":
    unittest.main()

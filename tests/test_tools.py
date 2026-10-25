import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

from mneme_llm import Mneme
from mneme_llm.capture import acapture, areflect
from mneme_llm.mcp import serve
from mneme_llm.tools import Toolbox, specs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plain(**options):
    return Mneme(":memory:", "t", luna=False, micro=False, **options)


class SpecTests(unittest.TestCase):
    def test_every_style_has_the_same_tools(self):
        self.assertEqual([t["function"]["name"] for t in specs("openai")], ["remember", "recall", "forget", "mood"])
        self.assertIn("input_schema", specs("anthropic")[0])
        self.assertIn("inputSchema", specs("mcp")[0])
        self.assertEqual(specs("responses")[0]["type"], "function")
        gemini = specs("gemini")[0]["function_declarations"][0]
        self.assertNotIn("minimum", gemini["parameters"]["properties"]["importance"])
        self.assertIn("subject", specs("mcp", with_subject=True)[0]["inputSchema"]["required"])
        self.assertEqual(specs("openai", prefix="memory_")[0]["function"]["name"], "memory_remember")


class ToolboxTests(unittest.TestCase):
    def test_remember_recall_forget(self):
        m = plain()
        box = Toolbox(m, "u")
        self.assertEqual(box.call("remember", {"text": "考试在11月2日", "kind": "plan", "key": "exam.date",
                                               "date": "2026-11-02"}), "Kept as #1.")
        self.assertEqual(box.call("remember", '{"text": "考试在11月2日", "kind": "plan"}'), "Already known (#1).")
        self.assertIn("replacing", box.call("remember", {"text": "考试改到11月5日", "kind": "plan", "key": "exam.date"}))
        self.assertIn("考试改到11月5日", box.call("recall", {"query": "考试"}))
        self.assertEqual(box.call("forget", {"key": "exam.date"}), "Forgot 1 note.")
        self.assertEqual(box.call("recall", {"query": "考试"}), "Nothing remembered on that.")
        self.assertIn("Mood 70/100", box.call("mood", {}))

    def test_mistakes_come_back_as_text(self):
        box = Toolbox(plain(), "u")
        self.assertTrue(box.call("remember", {"text": "x", "kind": "gossip"}).startswith("Error:"))
        self.assertTrue(box.call("remember", "{not json").startswith("Error:"))
        self.assertTrue(box.call("dance", {}).startswith("Error:"))
        self.assertTrue(Toolbox(plain()).call("mood", {}).startswith("Error: no subject"))

    def test_the_quota_is_explained(self):
        m = Mneme(":memory:", "t", luna=False, micro=False, daily_quota=1)
        box = Toolbox(m, "u")
        box.call("remember", {"text": "one", "kind": "episode"})
        self.assertIn("limit", box.call("remember", {"text": "two", "kind": "episode"}))


class McpTests(unittest.TestCase):
    def talk(self, messages, subject=None):
        out = io.StringIO()
        serve(plain(), subject, io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n"), out)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def test_a_session(self):
        replies = self.talk([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "remember", "arguments": {"subject": "u", "text": "likes tea", "kind": "preference"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "recall", "arguments": {"subject": "u", "query": "tea"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "nope"}])
        self.assertEqual([r.get("id") for r in replies], [1, 2, 3, 4, 5])
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "mneme-llm")
        self.assertEqual(len(replies[1]["result"]["tools"]), 4)
        self.assertEqual(replies[3]["result"]["content"][0]["text"], "#1 likes tea")
        self.assertEqual(replies[4]["error"]["code"], -32601)

    def test_bound_to_one_subject(self):
        replies = self.talk([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}], subject="u")
        self.assertNotIn("subject", replies[0]["result"]["tools"][0]["inputSchema"]["properties"])


class CaptureTests(unittest.TestCase):
    def test_capture_writes_what_the_model_lists_and_respects_the_gate(self):
        calls = []

        def complete(system, user):
            calls.append(system)
            if "impression" in system:
                return "A student who loves the cello."
            if "JSON object" in system:  # the decision prompt for the gate
                return '{"worth_remembering": {"probability": 0.9}}'
            return '[{"text": "Plays the cello", "kind": "fact", "key": "user.instrument", "importance": 3}]'

        m = plain(complete=complete)
        kept = asyncio.run(acapture(m, "u", [("user", "I practised cello for 2 hours"), ("bot", "wow")]))
        self.assertEqual([n.text for n in kept], ["Plays the cello"])
        self.assertEqual(kept[0].source, "auto")
        self.assertEqual(asyncio.run(areflect(m, "u")), "A student who loves the cello.")
        self.assertEqual(m.memory.profile("u"), "A student who loves the cello.")

    def test_small_talk_never_reaches_the_writer(self):
        calls = []

        def complete(system, user):
            calls.append(system)
            return '{"worth_remembering": {"probability": 0.1}}'

        self.assertEqual(asyncio.run(acapture(plain(complete=complete), "u", "user: hi\nbot: hi")), [])
        self.assertEqual(len(calls), 1)


class FacadeTests(unittest.TestCase):
    def test_prompt_joins_memory_and_mood_news(self):
        m = plain(name="大肥鱼")
        m.remember("u", "Plays the cello", kind="fact", importance=4)
        m.mood.apply("u", delta=5, emotions={"happy": 30}, reason="被夸了")
        text = m.prompt("u", "cello")
        self.assertIn("Plays the cello", text)
        self.assertIn("被夸了", text)
        self.assertNotIn("被夸了", m.prompt("u", "cello"))

    def test_one_judgement_can_use_a_different_chat_model(self):
        m = plain(name="大肥鱼")
        asked = []

        async def complete(system, user):
            asked.append(user)
            return ('{"mood_change": {"level": "2", "confidence": 0.9, "reason": "被夸了"}, '
                    '"feeling": {"choice": "happy", "confidence": 0.9}}')

        event = asyncio.run(m.aafter("u", "user: 你真棒\n大肥鱼: 嘿嘿", complete=complete))
        self.assertEqual((event.judge, event.reason), ("prompt", "被夸了"))
        self.assertEqual(m.decider.report()["prompt"]["answered"], 2)
        self.assertEqual(len(asked), 1)

    def test_the_micro_model_is_optional(self):
        self.assertIsNone(plain().micro)
        self.assertEqual([t.name for t in Mneme(":memory:", luna=False).decider.tiers], ["micro"])
        with_all = Mneme(":memory:", complete=lambda s, u: "{}")
        self.assertEqual([t.name for t in with_all.decider.tiers], ["luna", "micro", "prompt"])


class CliTests(unittest.TestCase):
    def run_cli(self, db, *args):
        env = dict(os.environ, PYTHONPATH=ROOT)
        env.pop("OPENAI_API_KEY", None)
        done = subprocess.run([sys.executable, "-m", "mneme_llm", "--db", db, "--space", "s", *args], env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_round_trip(self):
        folder = tempfile.mkdtemp()
        db = os.path.join(folder, "m.db")
        self.assertEqual(self.run_cli(db, "remember", "u", "Lives in Shanghai", "--key", "user.city").strip(), "kept #1")
        self.run_cli(db, "remember", "u", "Moved to Hangzhou", "--key", "user.city")
        self.assertIn("replaced: Lives in Shanghai", self.run_cli(db, "history", "u", "user.city"))
        self.assertIn("Moved to Hangzhou", self.run_cli(db, "context", "u", "hangzhou"))
        out = os.path.join(folder, "x.json")
        self.run_cli(db, "export", "--out", out)
        self.assertIn("imported 2 notes", self.run_cli(os.path.join(folder, "n.db"), "import", out, "--into", "t"))
        self.assertIn('"name": "remember"', self.run_cli(db, "tools", "--style", "anthropic"))


if __name__ == "__main__":
    unittest.main()

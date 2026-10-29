"""LoCoMo through mneme-llm: how much of ten long conversations a companion keeps, asked 1,986 questions.

Round one tests the finding of "Fidelity Before Structure" (arXiv 2601.00821) on our own stack: the same retriever,
answerer and judge for every arm, only what is stored changes.

    python -m bench.locomo ingest --data locomo10.json --out RUN [--only conv-30]
    python -m bench.locomo answer --data locomo10.json --out RUN --arm verbatim [--budget 6000] [--only conv-30]
    python -m bench.locomo report --out RUN

Arms:
  production  the notes as the students keep them today (at most 8 automatic notes below importance 4 a person a
              day), recalled by mneme-llm itself: word matching, 6 notes and 800 characters for each of the two
  notes       every note the writer kept (no daily quota), through the common retriever
  verbatim    the conversation itself in pieces of up to 512 characters (one turn of overlap), through the common
              retriever
  both        notes and pieces together, through the common retriever
  full        the whole conversation in the prompt (the reference)
  agent       the model searches the conversation itself (`search`, `read`: exchanges, up to six calls), after a first
              look of `--budget` characters (0: none)

`--unit exchange` stores the conversation as exchanges (each run of one side's messages with the other's reply, the
unit `aobserve` is given) in place of pieces; `--neighbors N` brings the N items on each side of every one chosen;
`--search bm25|vector` uses one ranking of the two; `--prompt cite` has the answer copy its evidence first;
`--window N` shows the newest N characters of the conversation word for word, looking up only what came before;
`--forget first|all` ranks with each exchange's retention (a forgetting curve, refreshed when the talk comes back to
it), in the first look only or in the model's searches too.

The common retriever ranks by BM25 over mneme-llm's own search terms and by embedding similarity (OpenAI
text-embedding-3-small), fused by reciprocal rank, and takes items in that order up to `--budget` characters; what it
takes is shown oldest first. Each person's notes come from their own exchanges, as a student's would: `aobserve`
after each run of their messages and the other's reply, on the session's own clock. Every model call is DeepSeek
Flash at low effort. Keys come from `--env` (DEEPSEEK_API_KEY and OPENAI_API_KEY only); a run stops when the DeepSeek
balance falls under `--floor`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import string
import sys
import time
from array import array
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import numpy

from mneme_llm import Mneme
from mneme_llm.text import terms

DEEPSEEK = "https://api.deepseek.com"
EMBEDDINGS = "https://api.openai.com/v1/embeddings"
UTC = timezone.utc
CATEGORIES = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop", 5: "adversarial"}
ARMS = ("production", "notes", "verbatim", "both", "full", "agent")
QUOTA = 8  # the students' automatic notes a person a day (mneme-llm's `memory.daily_quota`)


class OutOfBalance(RuntimeError):
    """The DeepSeek account is empty, or under the floor: stop, never retry."""


# ---- the conversations ---------------------------------------------------------------------------------------------
@dataclass
class Turn:
    speaker: str
    text: str
    at: float


@dataclass
class Session:
    at: float
    label: str
    turns: list


@dataclass
class Conversation:
    id: str
    a: str
    b: str
    sessions: list
    qa: list

    @property
    def end(self) -> float:
        return self.sessions[-1].turns[-1].at if self.sessions[-1].turns else self.sessions[-1].at


def moment(label: str) -> float:
    return datetime.strptime(label.strip(), "%I:%M %p on %d %B, %Y").replace(tzinfo=UTC).timestamp()


def spoken(turn: dict) -> str:
    text = " ".join(str(turn.get("text") or "").split())
    if turn.get("blip_caption"):
        text += f" [shares a photo: {turn['blip_caption']}]"
    return text


def load(path: Path, only: set[str]) -> list[Conversation]:
    found = []
    for raw in json.loads(path.read_text(encoding="utf-8")):
        if only and raw["sample_id"] not in only:
            continue
        talk = raw["conversation"]
        sessions = []
        for number in sorted(int(m.group(1)) for key in talk if (m := re.fullmatch(r"session_(\d+)", key))):
            label = talk[f"session_{number}_date_time"]
            start = moment(label)
            turns = [Turn(turn["speaker"], spoken(turn), start + index * 30)
                     for index, turn in enumerate(talk[f"session_{number}"])]
            sessions.append(Session(start, label, turns))
        found.append(Conversation(raw["sample_id"], talk["speaker_a"], talk["speaker_b"], sessions, raw["qa"]))
    return found


def exchanges(turns: list[Turn], person: str) -> list[tuple[list[Turn], float]]:
    """Each run of the person's messages with the other's reply after it (what a student hears, then says), and
    when the reply ended. The other's words before the person first speaks are theirs to note, not this side's."""
    found, index = [], 0
    while index < len(turns):
        if turns[index].speaker != person:
            index += 1
            continue
        end = index
        while end < len(turns) and turns[end].speaker == person:
            end += 1
        while end < len(turns) and turns[end].speaker != person:
            end += 1
        found.append((turns[index:end], turns[end - 1].at))
        index = end
    return found


def day(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).strftime("%-d %B %Y")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ---- the models ----------------------------------------------------------------------------------------------------
def keys(env: Path) -> dict[str, str]:
    """Only the two keys this bench may use, from the .env file (or the environment)."""
    wanted = {"DEEPSEEK_API_KEY": os.environ.get("DEEPSEEK_API_KEY", ""),
              "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", "")}
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, _, value = line.strip().partition("=")
            if name in wanted and value:
                wanted[name] = value.strip().strip('"').strip("'")
    return wanted


class Models:
    """DeepSeek Flash for every call, with tokens counted by step; OpenAI for embeddings."""

    def __init__(self, secrets: dict[str, str], floor: float, concurrency: int = 16, model: str = "deepseek-flash",
                 effort: str = "low"):
        self.secrets, self.floor, self.model, self.effort = secrets, floor, model, effort
        self.limit = asyncio.Semaphore(concurrency)
        self.usage: dict[str, Counter] = defaultdict(Counter)
        self.http: aiohttp.ClientSession | None = None
        self.calls = 0

    async def __aenter__(self) -> "Models":
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=240))
        return self

    async def __aexit__(self, *_) -> None:
        await self.http.close()

    async def balance(self) -> float:
        async with self.http.get(f"{DEEPSEEK}/user/balance",
                                 headers={"Authorization": f"Bearer {self.secrets['DEEPSEEK_API_KEY']}"}) as response:
            data = await response.json()
        return sum(float(item["total_balance"]) for item in data.get("balance_infos", []) if item["currency"] == "CNY")

    async def check(self) -> float:
        left = await self.balance()
        if left < self.floor:
            raise OutOfBalance(f"DeepSeek balance ¥{left:.2f} is under the floor ¥{self.floor:.2f}: stopping here")
        return left

    async def ask(self, system: str, user: str, *, step: str, max_tokens: int = 2500) -> str:
        message = await self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                  step=step, max_tokens=max_tokens)
        return message.get("content") or ""

    async def chat(self, messages: list[dict], *, step: str, max_tokens: int = 2500, tools: list | None = None) -> dict:
        """One call with the whole conversation so far; the assistant's message back (its tool calls, if any)."""
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "reasoning_effort": self.effort}
        if tools:
            body.update(tools=tools, tool_choice="auto")  # (a thinking model refuses a forced choice)
        headers = {"Authorization": f"Bearer {self.secrets['DEEPSEEK_API_KEY']}"}
        for attempt in range(6):
            try:
                async with self.limit:
                    async with self.http.post(f"{DEEPSEEK}/chat/completions", json=body, headers=headers) as response:
                        if response.status == 402:
                            raise OutOfBalance("DeepSeek says the balance is used up")
                        if response.status >= 400:
                            raise RuntimeError(f"DeepSeek HTTP {response.status}: {(await response.text())[:200]}")
                        data = await response.json()
                usage, count = data.get("usage") or {}, self.usage[step]
                count["calls"] += 1
                count["hit"] += usage.get("prompt_cache_hit_tokens", 0)
                count["miss"] += usage.get("prompt_cache_miss_tokens", 0)
                count["out"] += usage.get("completion_tokens", 0)
                self.calls += 1
                if self.calls % 500 == 0:
                    await self.check()
                return data["choices"][0]["message"]
            except OutOfBalance:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, KeyError, ValueError):
                if attempt == 5:
                    raise
                await asyncio.sleep(2 ** attempt)
        return {}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.secrets['OPENAI_API_KEY']}"}
        for attempt in range(6):
            try:
                async with self.http.post(EMBEDDINGS, headers=headers,
                                          json={"model": "text-embedding-3-small", "input": texts}) as response:
                    if response.status >= 400:
                        raise RuntimeError(f"OpenAI HTTP {response.status}: {(await response.text())[:200]}")
                    data = await response.json()
                self.usage["embed"]["calls"] += 1
                self.usage["embed"]["tokens"] += (data.get("usage") or {}).get("total_tokens", 0)
                return [row["embedding"] for row in sorted(data["data"], key=lambda row: row["index"])]
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, KeyError):
                if attempt == 5:
                    raise
                await asyncio.sleep(2 ** attempt)
        return []


class Vectors:
    """Embeddings, kept in the run's folder by the text's hash, so each text is embedded once."""

    def __init__(self, folder: Path, models: Models):
        self.models = models
        self.db = sqlite3.connect(folder / "vectors.db")
        self.db.execute("create table if not exists vectors (hash text primary key, vector blob)")

    async def of(self, texts: list[str]) -> list[array]:
        hashes = [hashlib.sha1(text.encode()).hexdigest() for text in texts]
        known = {}
        for start in range(0, len(hashes), 500):
            part = hashes[start:start + 500]
            rows = self.db.execute(f"select hash, vector from vectors where hash in ({','.join('?' * len(part))})",
                                   part)
            known.update({key: array("f", blob) for key, blob in rows})
        missing = list(dict.fromkeys(text for text, key in zip(texts, hashes) if key not in known))
        for start in range(0, len(missing), 96):
            batch = missing[start:start + 96]
            for text, vector in zip(batch, await self.models.embed(batch)):
                key = hashlib.sha1(text.encode()).hexdigest()
                known[key] = array("f", vector)
                self.db.execute("insert or replace into vectors values (?, ?)", (key, known[key].tobytes()))
            self.db.commit()
        return [known[key] for key in hashes]


# ---- ingesting: the notes each side keeps --------------------------------------------------------------------------
def notes_path(out: Path, conversation: Conversation, person: str, kind: str = "notes") -> Path:
    return out / kind / f"{conversation.id}-{slug(person)}.db"


def open_memory(path: Path, conversation: Conversation, companion: str, clock, complete=None) -> Mneme:
    return Mneme(str(path), space=conversation.id, companion_name=companion, display_language="en", zone=UTC,
                 complete=complete, luna=False, micro=False, embed=False, meaning_micro=False, memory_language=None,
                 daily_quota=10_000, clock=clock)


async def ingest(conversation: Conversation, out: Path, models: Models) -> None:
    async def side(person: str, companion: str) -> None:
        path = notes_path(out, conversation, person)
        finished = path.with_suffix(".done")
        if finished.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        for leftover in path.parent.glob(path.name + "*"):  # a side cut short starts over
            leftover.unlink()
        now = [conversation.sessions[0].at]

        async def complete(system: str, user: str) -> str:
            return await models.ask(system, user, step="ingest")
        memory = open_memory(path, conversation, companion, lambda: now[0], complete)
        errors = 0
        try:
            for session in conversation.sessions:
                for said, at in exchanges(session.turns, person):
                    now[0] = at
                    seen = await memory.aobserve(person, [(turn.speaker, turn.text) for turn in said],
                                                 user_name=person, mood=False)
                    errors += bool(seen.error)
            kept = len(memory.memory.notes(person))
        finally:
            memory.close()
        finished.write_text(json.dumps({"notes": kept, "writer_errors": errors}))
        print(f"  {conversation.id} {person}: {kept} notes ({errors} writer errors)", flush=True)
    await asyncio.gather(side(conversation.a, conversation.b), side(conversation.b, conversation.a))


def production_copy(out: Path, conversation: Conversation, person: str) -> Path:
    """The person's notes as the students would have kept them: the daily quota applied to the automatic notes in
    the order they were written (a note refused would not have counted)."""
    source, target = notes_path(out, conversation, person), notes_path(out, conversation, person, "production")
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, target)
    db = sqlite3.connect(source)
    rows = db.execute("select id, importance, created_at from memories where source = 'auto' order by id").fetchall()
    db.close()
    counted, refused = Counter(), []
    for note, importance, created in rows:
        today = day(created)
        if importance < 4 and counted[today] >= QUOTA:
            refused.append(note)
            continue
        counted[today] += 1
    with open_memory(target, conversation, "", lambda: conversation.end) as memory:
        for note in refused:
            memory.forget(person, id=note)
    return target


# ---- what each arm puts in the prompt ------------------------------------------------------------------------------
@dataclass
class Item:
    text: str
    at: float


def pieces(conversation: Conversation, limit: int = 512) -> list[Item]:
    """The conversation in pieces of up to `limit` characters of turns (at least one turn), each next piece starting
    at the last turn of the one before; each headed by its session's date."""
    found = []
    for session in conversation.sessions:
        lines = [f"{turn.speaker}: {turn.text}" for turn in session.turns]
        start = 0
        while start < len(lines):
            end, size = start, 0
            while end < len(lines) and (end == start or size + len(lines[end]) <= limit):
                size += len(lines[end]) + 1
                end += 1
            found.append(Item(f"[{session.label}]\n" + "\n".join(lines[start:end]), session.turns[start].at))
            if end >= len(lines):
                break
            start = end - 1 if end - 1 > start else end
    return found


def turns_of(conversation: Conversation) -> list[Item]:
    """The conversation as exchanges, as a student stores them: each run of one side's messages with the other's
    reply after it, no turn twice (the unit `aobserve` is given), headed by the session's date."""
    found = []
    for session in conversation.sessions:
        index = 0
        while index < len(session.turns):
            first, end = session.turns[index].speaker, index
            while end < len(session.turns) and session.turns[end].speaker == first:
                end += 1
            while end < len(session.turns) and session.turns[end].speaker != first:
                end += 1
            found.append(Item(f"[{session.label}]\n" + "\n".join(f"{turn.speaker}: {turn.text}"
                                                                  for turn in session.turns[index:end]),
                              session.turns[index].at))
            index = end
    return found


def notes_of(out: Path, conversation: Conversation) -> list[Item]:
    found = []
    for person, companion in ((conversation.a, conversation.b), (conversation.b, conversation.a)):
        with open_memory(notes_path(out, conversation, person), conversation, companion,
                         lambda: conversation.end) as memory:
            for note in memory.memory.notes(person):
                found.append(Item(f"[{day(note.happened_at)}] (about {person}) {note.text}", note.happened_at))
    return found


def latest(conversation: Conversation, limit: int) -> tuple[str, float]:
    """The newest turns of the conversation, word for word, up to `limit` characters (whole turns, by session), and
    when the first of them was said."""
    taken, size = [], 0
    for session in reversed(conversation.sessions):
        for turn in reversed(session.turns):
            line = f"{turn.speaker}: {turn.text}"
            if size + len(line) + 1 > limit:
                break
            taken.append((session.label, turn, line))
            size += len(line) + 1
        else:
            continue
        break
    taken.reverse()
    blocks, label = [], None
    for session_label, turn, line in taken:
        if session_label != label:
            blocks.append(f"[{session_label}]")
            label = session_label
        blocks.append(line)
    return "\n".join(blocks), (taken[0][1].at if taken else float("inf"))


def whole(conversation: Conversation) -> str:
    return "\n\n".join(f"[{session.label}]\n" + "\n".join(f"{turn.speaker}: {turn.text}" for turn in session.turns)
                       for session in conversation.sessions)


# ---- forgetting: each exchange's retention (Ebbinghaus), refreshed whenever the talk comes back to it -----------------
FLOOR = 0.25  # how much a faded exchange still counts in a ranking: found later, never lost


class Retention:
    """Each exchange's place on its forgetting curve: when it was last recalled and how long it lasts (S). Its retention
    at a time is R = e^(−time since then / S). Talk that comes back to it, or a search that finds it (`refresh`), is a
    recall: S grows, the more when it had nearly faded (spaced repetition: S ← S · (1.5 + 3 · (1 − R))), and it is
    fresh again."""

    def __init__(self, items: list[Item], vectors, days: float = 30.0):
        self.items = items
        count = len(items)
        self.last = numpy.array([item.at for item in items], dtype=float)
        self.strength = numpy.full(count, days * 86400.0)
        if count < 2:
            return
        matrix = numpy.asarray(vectors, dtype=numpy.float32).reshape(count, -1)
        similarity = matrix @ matrix.T
        # An exchange recalls the earlier ones it is about: its three nearest in meaning, if closer than 98% of pairs.
        threshold = float(numpy.percentile(similarity[numpy.triu_indices(count, 1)], 98))
        order = sorted(range(count), key=lambda index: items[index].at)
        for position in range(1, count):
            current, earlier = order[position], order[:position]
            scores = similarity[current, earlier]
            for nearest in numpy.argsort(-scores)[:3]:
                if scores[nearest] < threshold:
                    break
                self.recall(earlier[nearest], items[current].at)

    def recall(self, index: int, now: float) -> None:
        kept = math.exp(-max(0.0, now - self.last[index]) / self.strength[index])
        self.strength[index] *= 1.5 + 3 * (1 - kept)
        self.last[index] = max(self.last[index], now)

    def at(self, now: float) -> numpy.ndarray:
        return numpy.exp(-numpy.maximum(0.0, now - self.last) / self.strength)


class Index:
    """BM25 over mneme-llm's search terms and embedding similarity, fused by reciprocal rank; with a `memory` (each
    item's Retention) and `now`, a ranking asked to forget counts a faded item less: its score times 0.25 + 0.75·R."""

    def __init__(self, items: list[Item], vectors: list[array]):
        self.items = items
        self.vectors = numpy.array(vectors, dtype=numpy.float32).reshape(len(items), -1)
        self.memory: Retention | None = None
        self.now = 0.0
        self.docs = [Counter(terms(item.text)) for item in items]
        self.lengths = [sum(doc.values()) for doc in self.docs]
        self.average = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0
        frequency = Counter(term for doc in self.docs for term in doc)
        self.idf = {term: math.log(1 + (len(items) - count + 0.5) / (count + 0.5)) for term, count in frequency.items()}

    def rank(self, query: str, vector: array, search: str = "hybrid", forget: bool = False) -> list[int]:
        wanted = set(terms(query))
        bm25 = [sum(self.idf[term] * doc[term] * 2.2 / (doc[term] + 1.2 * (0.25 + 0.75 * length / self.average))
                    for term in wanted if term in doc) for doc, length in zip(self.docs, self.lengths)]
        cosine = self.vectors @ numpy.asarray(vector, dtype=numpy.float32) if len(self.items) else []
        fused = defaultdict(float)
        if search != "vector":
            for place, index in enumerate(sorted(range(len(self.items)), key=lambda index: -bm25[index])):
                if bm25[index] > 0:
                    fused[index] += 1 / (61 + place)
        if search != "bm25":
            for place, index in enumerate(sorted(range(len(self.items)), key=lambda index: -cosine[index])):
                fused[index] += 1 / (61 + place)
        if forget and self.memory is not None:
            kept = self.memory.at(self.now)
            for index in fused:
                fused[index] *= FLOOR + (1 - FLOOR) * float(kept[index])
        return sorted(fused, key=lambda index: -fused[index])

    def take(self, query: str, vector: array, budget: int, neighbors: int = 0, search: str = "hybrid",
             forget: bool = False) -> list[Item]:
        """Items in rank order up to `budget` characters; with `neighbors`, each chosen item brings the items next
        to it (in the order they were made: the conversation's) while they fit."""
        chosen, used = {}, 0
        for index in self.rank(query, vector, search, forget):
            for near in [index] + [index + step for distance in range(1, neighbors + 1) for step in (-distance, distance)]:
                if near in chosen or not 0 <= near < len(self.items):
                    continue
                size = len(self.items[near].text) + 1
                if used + size <= budget:
                    chosen[near] = self.items[near]
                    used += size
            if used > budget - 60:
                break
        return sorted(chosen.values(), key=lambda item: item.at)


# ---- answering and judging -----------------------------------------------------------------------------------------
ANSWER = ("You remember the conversations between {a} and {b}, which went on over many sessions; it is now {today}. "
          "Below is what your memory brings up for the question. Dates in brackets are when things were said (or, "
          "for notes, when they happened): work out relative dates such as 'last week' or 'yesterday' from them. "
          "Answer with a short phrase (a name, a date, a few words). If what is below does not answer the question, "
          "say: Not mentioned.")
CITE = ANSWER.rsplit(" If what is below", 1)[0] + (
    " First copy the line or lines below that answer the question; if none does, the evidence is 'none' and the "
    "answer is: Not mentioned. Reply in exactly this form:\nEvidence: ...\nAnswer: ...")
JUDGE = ("You grade an answer to a question about a conversation. The gold answer is: {gold}\n"
         "Label the answer CORRECT if it means the same as the gold answer (a date or period said another way "
         "counts, and so does an answer that contains the gold answer and adds a little), WRONG otherwise. "
         "Reply with one word: CORRECT or WRONG.")
JUDGE_NONE = ("You grade an answer to a question about a conversation. The conversation never says what the "
              "question asks. Label the answer CORRECT if it says this is not mentioned, not known or not said, "
              "WRONG if it gives an answer. Reply with one word: CORRECT or WRONG.")


AGENT = ("You remember the conversations between {a} and {b}, which went on over many sessions; it is now {today}. "
         "Everything said before is kept word for word, and you can look it up: `search` finds the exchanges that "
         "match what you ask (each with its id and the date it was said), and `read` shows an exchange with the ones "
         "around it. Search as often as you need: with other words (names, places, things, feelings) when the first "
         "results don't answer, once per part of a question about several things, and for each date you need. Work "
         "out relative dates such as 'last week' from the date of the exchange that says them. When you know, answer "
         "with a short phrase (a name, a date, a few words). If what was said does not answer it, say: Not mentioned.")
# Checked before answering: what was found is about the person and the thing asked (a question may name the other
# person, or something that never happened).
GUARD = (" Before you answer, check that what you found is about the same person and the same thing the question asks: "
         "a question may name the other person, or something that never happened. If it does not match, say: Not "
         "mentioned.")
TOOLS = [
    {"type": "function", "function": {
        "name": "search", "description": "Search everything said before. Returns the best matching exchanges you have "
                                         "not seen yet, each with its id and date.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "what to look for"}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "read", "description": "An exchange with the one before and the one after it.",
        "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}}},
]


async def agent_answer(models: Models, vectors: "Vectors", index: "Index", system: str, opening: str, question: str,
                       step: str, steps: int = 6, per_search: int = 5, forget: bool = False,
                       refresh: bool = False) -> tuple[str, dict]:
    """The question answered by a model that searches the conversation itself: up to `steps` calls, the last one
    without tools; what it did, for the report."""
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": (f"{opening}\n\n" if opening else "") + f"Question: {question}"}]
    seen: set[int] = set()
    did = {"searches": 0, "reads": 0, "calls": 0, "shown_chars": 0}
    for turn in range(steps):
        last = turn == steps - 1
        reply = await models.chat(messages, step=step, tools=None if last else TOOLS)
        did["calls"] += 1
        calls = reply.get("tool_calls") or []
        if not calls or last:
            return reply.get("content") or "", did
        kept = {"role": "assistant", "content": reply.get("content") or "", "tool_calls": calls}
        if reply.get("reasoning_content"):  # (DeepSeek wants its thinking back while it uses tools)
            kept["reasoning_content"] = reply["reasoning_content"]
        messages.append(kept)
        for call in calls:
            try:
                arguments = json.loads(call["function"].get("arguments") or "{}")
            except ValueError:
                arguments = {}
            if call["function"]["name"] == "search":
                did["searches"] += 1
                query = str(arguments.get("query") or question)
                vector = (await vectors.of([query]))[0]
                fresh = [place for place in index.rank(query, vector, forget=forget) if place not in seen][:per_search]
                seen.update(fresh)
                if refresh and index.memory is not None:  # what a search brings back is recalled: it fades slower
                    for place in fresh:
                        index.memory.recall(place, index.now)
                found = "\n\n".join(f"#{place} {index.items[place].text}" for place in sorted(fresh)) or "Nothing new."
            elif call["function"]["name"] == "read":
                did["reads"] += 1
                place = int(arguments.get("id", -1)) if str(arguments.get("id", "")).lstrip("-").isdigit() else -1
                found = "\n\n".join(f"#{near} {index.items[near].text}" for near in (place - 1, place, place + 1)
                                     if 0 <= near < len(index.items)) or "No such exchange."
            else:
                found = "No such tool."
            did["shown_chars"] += len(found)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": found})
    return "", did


def normal(text: str) -> list[str]:
    text = str(text).lower().replace(",", "")
    text = "".join(char for char in text if char not in set(string.punctuation))
    return [word for word in text.split() if word not in ("a", "an", "the", "and")]


def f1(answer: str, gold: str) -> float:
    mine, theirs = normal(answer), normal(gold)
    common = sum((Counter(mine) & Counter(theirs)).values())
    if not common:
        return 0.0
    precision, recall = common / len(mine), common / len(theirs)
    return 2 * precision * recall / (precision + recall)


async def answer(conversations: list[Conversation], out: Path, arm: str, budget: int, models: Models,
                 unit: str = "piece", neighbors: int = 0, search: str = "hybrid", prompt: str = "plain",
                 window: int = 0, decay: str = "none", days: float = 30.0, refresh: bool = False) -> Path:
    name = arm if arm in ("production", "full") else \
        f"{arm}{'-' + unit if unit != 'piece' and arm != 'notes' else ''}-{budget}" + (f"-n{neighbors}" if neighbors else "")
    name += (f"-w{window}" if window else "") + (f"-{search}" if search != "hybrid" else "") + \
        (f"-{prompt}" if prompt != "plain" else "") + \
        (f"-forget{decay}" + (f"{days:g}d" if days != 30 else "") if decay != "none" else "") + \
        ("-refresh" if refresh else "")
    path = out / "answers" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done.add((row["conversation"], row["index"]))
    vectors = Vectors(out, models) if arm in ("notes", "verbatim", "both", "agent") else None
    lock = asyncio.Lock()
    for conversation in conversations:
        todo = [(index, qa) for index, qa in enumerate(conversation.qa) if (conversation.id, index) not in done]
        if not todo:
            continue
        await models.check()
        index_of = memories = None
        if vectors is not None:
            recent, since = latest(conversation, window) if window else ("", float("inf"))
            items = ((notes_of(out, conversation) if arm in ("notes", "both") else []) +
                     ((pieces(conversation) if unit == "piece" else turns_of(conversation))
                      if arm in ("verbatim", "both", "agent") else []))
            items = [item for item in items if item.at < since]  # what the window shows is not looked up again
            index_of = Index(items, await vectors.of([item.text for item in items]))
            if decay != "none":
                index_of.memory, index_of.now = Retention(items, index_of.vectors, days), conversation.end
                kept = index_of.memory.at(index_of.now)
                print(f"  {conversation.id}: {len(items)} exchanges, {float((kept < 0.1).mean()):.0%} faded under 0.1, "
                      f"median retention {float(numpy.median(kept)):.2f}", flush=True)
            asked = await vectors.of([qa["question"] for _, qa in todo])
        elif arm == "production":
            memories = [(person, open_memory(production_copy(out, conversation, person), conversation, companion,
                                             lambda: conversation.end))
                        for person, companion in ((conversation.a, conversation.b), (conversation.b, conversation.a))]
        system = (AGENT if arm == "agent" else CITE if prompt == "cite" else ANSWER).format(
            a=conversation.a, b=conversation.b, today=day(conversation.end)) + (GUARD if prompt == "guard" else "")

        async def one(place: int, index: int, qa: dict) -> None:
            question = qa["question"]
            did = None
            if arm == "agent":  # a first look of `budget` characters (0: none), then its own searches
                opening = "\n\n".join(item.text for item in index_of.take(
                    question, asked[place], budget, forget=decay != "none")) if budget else ""
                reply, did = await agent_answer(models, vectors, index_of, system,
                                                f"What your memory brings up first:\n{opening}" if opening else "",
                                                question, f"answer:{name}", forget=decay == "all",
                                                refresh=refresh)
                memory = opening
            elif arm == "full":
                memory = whole(conversation)
            elif arm == "production":
                memory = "\n\n".join(block for person, mind in memories
                                     if (block := mind.memory.context(person, question, user_name=person,
                                                                      limit=6, budget=800)))
            else:
                memory = "\n\n".join(item.text for item in index_of.take(question, asked[place], budget, neighbors,
                                                                            search, forget=decay != "none"))
                if window:
                    memory = (memory + "\n\n" if memory else "") + "The latest messages, word for word:\n" + recent
            # The whole conversation first, so every question about it reuses DeepSeek's cache of that prefix.
            if arm == "agent":
                pass
            elif arm == "full":
                reply = await models.ask(system + "\n\n" + memory, f"Question: {question}", step=f"answer:{name}")
            else:
                reply = await models.ask(system, f"{memory or '(nothing)'}\n\nQuestion: {question}",
                                         step=f"answer:{name}")
            if prompt == "cite":
                found = re.findall(r"Answer:\s*(.+)", reply)
                reply = found[-1] if found else reply
            reply = " ".join(reply.split())
            category = int(qa["category"])
            gold = "" if category == 5 else str(qa.get("answer", ""))
            graded = await models.ask(JUDGE_NONE if category == 5 else JUDGE.format(gold=gold),
                                      f"Question: {question}\nAnswer: {reply}", step=f"judge:{name}", max_tokens=1200)
            label = re.search(r"\b(CORRECT|WRONG)\b", graded.upper())
            row = {"conversation": conversation.id, "index": index, "category": category, "question": question,
                   "gold": gold, "answer": reply, "correct": bool(label and label.group(1) == "CORRECT"),
                   "f1": None if category == 5 else round(f1(reply, gold), 4),
                   "memory_chars": len(memory) + (did or {}).get("shown_chars", 0), **({"did": did} if did else {})}
            async with lock:
                with path.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(row, ensure_ascii=False) + "\n")
        try:
            if refresh:
                for place, (index, qa) in enumerate(todo):
                    await one(place, index, qa)
            else:
                await asyncio.gather(*(one(place, index, qa) for place, (index, qa) in enumerate(todo)))
        finally:
            for _, mind in memories or ():
                mind.close()
        print(f"  {conversation.id}: {len(todo)} answered", flush=True)
    return path


# ---- the report ----------------------------------------------------------------------------------------------------
def report(out: Path) -> str:
    lines = ["| arm | 1–3 | 1–4 | multi-hop | temporal | open-domain | single-hop | adversarial | F1 1–4 | memory chars |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for path in sorted((out / "answers").glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        by = defaultdict(list)
        for row in rows:
            by[row["category"]].append(row)

        def share(categories) -> str:
            chosen = [row for category in categories for row in by[category]]
            return f"{100 * sum(row['correct'] for row in chosen) / len(chosen):.1f}% ({len(chosen)})" if chosen else "–"
        scored = [row for category in (1, 2, 3, 4) for row in by[category]]
        mean_f1 = sum(row["f1"] for row in scored) / len(scored) if scored else 0
        chars = sum(row["memory_chars"] for row in rows) / len(rows) if rows else 0
        lines.append(f"| {path.stem} | {share((1, 2, 3))} | {share((1, 2, 3, 4))} | " +
                     " | ".join(share((category,)) for category in (1, 2, 3, 4, 5)) +
                     f" | {mean_f1:.3f} | {chars:,.0f} |")
    usage = out / "usage.jsonl"
    if usage.exists():
        totals = defaultdict(Counter)
        spent = 0.0
        for line in usage.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            spent += entry.get("spent_cny", 0)
            for step, count in entry["usage"].items():
                totals[step].update(count)
        lines += ["", f"DeepSeek spent, by the balance: ¥{spent:.2f}", "",
                  "| step | calls | cache hit | cache miss | out |", "|---|---|---|---|---|"]
        for step, count in sorted(totals.items()):
            lines.append(f"| {step} | {count['calls']:,} | {count['hit']:,} | {count['miss']:,} | {count['out']:,} |")
    return "\n".join(lines)


# ---- the command line ----------------------------------------------------------------------------------------------
async def main(arguments) -> int:
    out = Path(arguments.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    if arguments.command == "report":
        print(report(out))
        return 0
    conversations = load(Path(arguments.data).expanduser(), set(arguments.only or ()))
    async with Models(keys(Path(arguments.env).expanduser()), arguments.floor, arguments.concurrency) as models:
        before = await models.check()
        started = time.time()
        print(f"DeepSeek balance ¥{before:.2f}; {len(conversations)} conversations", flush=True)
        try:
            if arguments.command == "ingest":
                await asyncio.gather(*(ingest(conversation, out, models) for conversation in conversations))
            else:
                await answer(conversations, out, arguments.arm, arguments.budget, models, arguments.unit,
                             arguments.neighbors, arguments.search, arguments.prompt, arguments.window,
                             arguments.forget, arguments.stability, arguments.refresh)
        except OutOfBalance as stop:
            print(f"STOPPED: {stop}", flush=True)
        finally:
            after = await models.balance()
            entry = {"command": arguments.command, "arm": getattr(arguments, "arm", None),
                     "budget": getattr(arguments, "budget", None), "only": arguments.only, "at": time.time(),
                     "seconds": round(time.time() - started), "balance_before": before, "balance_after": after,
                     "spent_cny": round(before - after, 4), "usage": {key: dict(value) for key, value in models.usage.items()}}
            with (out / "usage.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps(entry) + "\n")
            print(f"DeepSeek balance ¥{after:.2f} (spent ¥{before - after:.2f}) in {entry['seconds']} s", flush=True)
    return 0


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("ingest", "answer", "report"))
    parser.add_argument("--data", default="../memory-bench/data/locomo/locomo10.json")
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", nargs="*", help="sample ids (conv-30 …); all ten by default")
    parser.add_argument("--arm", choices=ARMS, default="verbatim")
    parser.add_argument("--budget", type=int, default=6000, help="characters of memory a question may bring up")
    parser.add_argument("--unit", choices=("piece", "exchange"), default="piece",
                        help="what the conversation is stored as: 512-character pieces, or exchanges")
    parser.add_argument("--neighbors", type=int, default=0, help="items next to each one chosen that come with it")
    parser.add_argument("--search", choices=("hybrid", "bm25", "vector"), default="hybrid")
    parser.add_argument("--prompt", choices=("plain", "cite", "guard"), default="plain",
                        help="cite: the answer first copies the lines it rests on, or says none; guard: it checks the "
                             "person and the thing asked before answering")
    parser.add_argument("--window", type=int, default=0,
                        help="characters of the newest turns shown word for word besides what is looked up")
    parser.add_argument("--forget", choices=("none", "first", "all"), default="none",
                        help="the forgetting curve in the rankings: none, the first look only (a search the model makes "
                             "still reaches everything, as trying hard to remember), or all")
    parser.add_argument("--stability", type=float, default=30.0, help="days an exchange told once takes to fade to 1/e")
    parser.add_argument("--refresh", action="store_true",
                        help="what the model's searches bring back is recalled (fades slower); a conversation's "
                             "questions are then asked one after another, as in a chat")
    parser.add_argument("--env", default="../.env", help="the .env holding DEEPSEEK_API_KEY and OPENAI_API_KEY")
    parser.add_argument("--floor", type=float, default=12.0, help="stop when the DeepSeek balance (CNY) is under this")
    parser.add_argument("--concurrency", type=int, default=16)
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse())))

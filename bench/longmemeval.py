"""LongMemEval-M through mneme-llm itself: a history far longer than any context window, kept as a companion keeps it.

Each question of LongMemEval (Wu et al., ICLR 2025) comes with its own history: in the M set about 500 chat sessions
between a user and an assistant, about 1.5 million tokens, with the few sessions that hold the answer somewhere
among them. Every session goes into its own mneme-llm file exchange by exchange, on its own date (`Episodes.keep`),
and is embedded and rehearsed as a student's would be (`Episodes.prepare`); then the question is asked on its own
date, and DeepSeek Flash answers from what the library gives it.

    python -m bench.longmemeval extract --m longmemeval_m_cleaned.json --subset subset.json --out RUN
    python -m bench.longmemeval extract --locomo locomo10.json --only conv-26,conv-30 --out RUN   (LoCoMo, the same way)
    python -m bench.longmemeval ingest --out RUN
    python -m bench.longmemeval answer --out RUN --arm agent [--budget 6000]
    python -m bench.longmemeval report --out RUN

Arms:
  oracle   the sessions that hold the answer, whole, in the prompt (the ceiling: nothing to find)
  look     the library's first look alone (`Episodes.alook`, `--budget` characters, those close enough to the
           question: `--cut`, the more faded the closer)
  agent    the first look, then the library's own `search` and `read` tools (`tools.Toolbox`), up to six calls

Questions are judged by the benchmark's own prompts (one per question type, and one for the unanswerable ones),
asked of DeepSeek Flash instead of GPT-4o. Embeddings are OpenAI's text-embedding-3-small at 256 dimensions, as the
students use them, kept by the text's hash so a session shared by several histories is embedded once. Keys come from
`--env` (DEEPSEEK_API_KEY and OPENAI_API_KEY only); a run stops when the DeepSeek balance falls under `--floor`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import time
from array import array
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from mneme_llm import Embeddings, Mneme
from mneme_llm.episodes import CUT, CUT_FADED
from mneme_llm.tools import Toolbox, specs

from bench.locomo import Models, OutOfBalance, keys

UTC = timezone.utc
TYPES = ("single-session-user", "single-session-assistant", "single-session-preference", "multi-session",
         "knowledge-update", "temporal-reasoning")
ARMS = ("oracle", "look", "agent")
SUBJECT = "user"
EMBEDDER = "openai:text-embedding-3-small:256"  # the name mneme-llm's own OpenAIEmbeddings gives these vectors


def moment(label: str) -> float:
    return datetime.strptime(label.strip(), "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC).timestamp()


# ---- the data: the subset's questions, streamed out of the 2.7 GB file ---------------------------------------------
def extract(source: Path, wanted: list[str], target: Path) -> int:
    """Copy the chosen questions out of a JSON list too big to read whole, one element at a time."""
    decoder, wanted_set, found = json.JSONDecoder(), set(wanted), {}
    with source.open("r", encoding="utf-8") as handle:
        buffer, position, started = "", 0, False
        while True:
            chunk = handle.read(8 << 20)
            buffer = buffer[position:] + chunk
            position = 0
            if not started:
                position = buffer.index("[") + 1
                started = True
            while True:
                while position < len(buffer) and buffer[position] in " \t\r\n,":
                    position += 1
                if position >= len(buffer) or buffer[position] == "]":
                    break
                try:
                    item, end = decoder.raw_decode(buffer, position)
                except json.JSONDecodeError:
                    break  # the element goes on in the next chunk
                if item.get("question_id") in wanted_set:
                    found[item["question_id"]] = item
                position = end
            if not chunk:
                break
    with target.open("w", encoding="utf-8") as out:
        for question_id in wanted:
            if question_id in found:
                out.write(json.dumps(found[question_id], ensure_ascii=False) + "\n")
    return len(found)


# LoCoMo's categories as LongMemEval's question types (the judge's prompt for each); 5, adversarial, is unanswerable
CATEGORIES = {1: "multi-session", 2: "temporal-reasoning", 3: "multi-session", 4: "single-session-user"}
NOT_SAID = "The conversations never say this: the question asks about something not said, or about the other person."


def extract_locomo(source: Path, only: list[str], target: Path) -> int:
    """LoCoMo's conversations as LongMemEval's questions: each conversation one history (`history`, kept once), the
    first speaker as the user, each session on its own date; every question asked the day after the last session."""
    count = 0
    with target.open("w", encoding="utf-8") as out:
        for raw in json.loads(source.read_text(encoding="utf-8")):
            if only and raw["sample_id"] not in only:
                continue
            talk = raw["conversation"]
            a, b = talk["speaker_a"], talk["speaker_b"]
            numbers = sorted(int(key.split("_")[1]) for key in talk if key.count("_") == 1 and
                             key.startswith("session_") and key.split("_")[1].isdigit())
            dates, ids, sessions = [], [], []
            for number in numbers:
                when = datetime.strptime(talk[f"session_{number}_date_time"].strip(), "%I:%M %p on %d %B, %Y")
                dates.append(when.strftime("%Y/%m/%d (%a) %H:%M"))
                ids.append(f"s{number}")
                sessions.append([{"role": "user" if turn["speaker"] == a else "assistant", "speaker": turn["speaker"],
                                  "content": " ".join(str(turn.get("text") or "").split()) +
                                  (f" [shares a photo: {turn['blip_caption']}]" if turn.get("blip_caption") else "")}
                                 for turn in talk[f"session_{number}"]])
            last = max(datetime.strptime(date, "%Y/%m/%d (%a) %H:%M") for date in dates)
            asked = datetime.fromtimestamp(last.replace(tzinfo=UTC).timestamp() + 86400, UTC)
            for index, qa in enumerate(raw["qa"]):
                category = qa.get("category")
                unanswerable = category == 5
                evidence = {f"s{number}" for number in re.findall(r"D(\d+):", " ".join(map(str, qa.get("evidence", []))))}
                out.write(json.dumps({
                    "question_id": f"{raw['sample_id']}-{index}" + ("_abs" if unanswerable else ""),
                    "history": raw["sample_id"], "speakers": [a, b], "category": category,
                    "question_type": CATEGORIES.get(category, "multi-session"), "question": qa["question"],
                    "answer": NOT_SAID if unanswerable else str(qa.get("answer")),
                    "question_date": asked.strftime("%Y/%m/%d (%a) %H:%M"),
                    "answer_session_ids": sorted(evidence & set(ids)), "haystack_dates": dates,
                    "haystack_session_ids": ids, "haystack_sessions": sessions}, ensure_ascii=False) + "\n")
                count += 1
    return count


def history(item: dict) -> str:
    """The name of the history a question is asked of (LoCoMo's questions share one per conversation)."""
    return item.get("history") or item["question_id"]


def questions(run: Path) -> list[dict]:
    return [json.loads(line) for line in (run / "questions.jsonl").read_text(encoding="utf-8").split("\n") if line]


def exchanges(session: list[dict]) -> list[list[tuple[str, str]]]:
    """A session as exchanges: each run of the user's messages with the assistant's reply after it."""
    found, current, roles = [], [], []  # (roles: whether each line of the current exchange is the user's)
    for turn in session:
        user = turn.get("role") == "user"
        if user and current and not roles[-1]:
            found.append(current)
            current, roles = [], []
        current.append((turn.get("speaker") or ("User" if user else "Assistant"), str(turn.get("content") or "")))
        roles.append(user)
    if current:
        found.append(current)
    return found


# ---- embeddings, cached --------------------------------------------------------------------------------------------
class Limited(Exception):
    def __init__(self, wait: float):
        super().__init__(f"rate limited for {wait:g} s")
        self.wait = wait


class _nothing:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *_):
        return False


class Cache:
    """text-embedding-3-small at 256 dimensions (the library's default), by the text's hash."""

    def __init__(self, path: Path, models: Models, serial: bool = False):
        self.models, self.serial = models, serial
        self.db = sqlite3.connect(path)
        self.db.execute("create table if not exists vectors (hash text primary key, vector blob)")
        self.lock = asyncio.Lock()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        texts = [text[:8000] or " " for text in texts]  # as mneme-llm's OpenAIEmbeddings sends them
        hashes = [hashlib.sha1(text.encode()).hexdigest() for text in texts]
        known = {}
        for start in range(0, len(hashes), 500):
            part = hashes[start:start + 500]
            rows = self.db.execute(f"select hash, vector from vectors where hash in ({','.join('?' * len(part))})", part)
            known.update({key: array("f", blob) for key, blob in rows})
        missing = list(dict.fromkeys(text for text, key in zip(texts, hashes) if key not in known))
        for start in range(0, len(missing), 64):
            batch = missing[start:start + 64]
            for text, vector in zip(batch, await self.dimensions(batch)):
                key = hashlib.sha1(text.encode()).hexdigest()
                known[key] = array("f", vector)
                self.db.execute("insert or replace into vectors values (?, ?)", (key, known[key].tobytes()))
            self.db.commit()
        return [list(known[key]) for key in hashes]

    async def dimensions(self, batch: list[str]) -> list[list[float]]:
        models = self.models
        headers = {"Authorization": f"Bearer {models.secrets['OPENAI_API_KEY']}"}
        for attempt in range(10):
            try:
                async with self.lock if self.serial else _nothing():
                    async with models.http.post("https://api.openai.com/v1/embeddings", headers=headers,
                                                json={"model": "text-embedding-3-small", "input": batch,
                                                      "dimensions": 256}) as response:
                        if response.status == 429:  # a rate limit: wait as long as it says, then again
                            wait = float(response.headers.get("retry-after") or 0) or min(60, 5 * 2 ** attempt)
                            raise Limited(wait)
                        if response.status >= 400:
                            raise RuntimeError(f"OpenAI HTTP {response.status}: {(await response.text())[:200]}")
                        data = await response.json()
                models.usage["embed"]["calls"] += 1
                models.usage["embed"]["tokens"] += (data.get("usage") or {}).get("total_tokens", 0)
                return [row["embedding"] for row in sorted(data["data"], key=lambda row: row["index"])]
            except Limited as limited:
                models.usage["embed"]["limited"] += 1
                await asyncio.sleep(limited.wait)
            except Exception:
                if attempt == 9:
                    raise
                await asyncio.sleep(min(60, 2 ** attempt))
        raise RuntimeError("OpenAI kept refusing (rate limit)")


def companion(path: Path, question_id: str, cache: Cache, clock) -> Mneme:
    return Mneme(str(path), space=question_id, companion_name="Assistant", display_language="en", zone=UTC,
                 luna=False, micro=False, embed=Embeddings(cache.embed, name=EMBEDDER, floor=0.33),
                 meaning_micro=False, memory_language=None, clock=clock)


# ---- ingesting: every session, exchange by exchange, on its own date -----------------------------------------------
async def ingest_one(run: Path, item: dict, cache: Cache) -> dict:
    path = run / "memory" / f"{history(item)}.db"
    done = run / "memory" / f"{history(item)}.done"
    if done.exists():
        return json.loads(done.read_text())
    path.unlink(missing_ok=True)
    now = [0.0]
    started = time.monotonic()
    sessions = sorted(zip(item["haystack_dates"], item["haystack_session_ids"], item["haystack_sessions"]),
                      key=lambda row: moment(row[0]))
    memory = companion(path, history(item), cache, lambda: now[0])

    def keep_all() -> int:
        count = 0
        with memory.store.transaction():
            for label, session_id, session in sessions:
                for index, lines in enumerate(exchanges(session)):
                    if memory.episodes.keep(SUBJECT, lines, at=moment(label) + index * 30,
                                            conversation=str(session_id)) is not None:
                        count += 1
        return count

    kept = await asyncio.to_thread(keep_all)
    embedded = 0
    for attempt in range(20):  # a batch that failed rests the embedder for a minute: then the rest
        embedded += await memory.episodes.prepare(SUBJECT, limit=1_000_000)
        missing = memory.store.row("select count(*) as n from episodes e where not exists (select 1 from "
                                   "episode_vectors v where v.episode_id = e.id)")["n"]
        if not missing:
            break
        print(f"  {item['question_id']}: {missing} exchanges still to embed ({memory.meaning.rest.error})", flush=True)
        await asyncio.sleep(max(1.0, memory.meaning.rest.until - time.monotonic()))
    rehearsed = memory.store.row("select count(*) as n from episodes where recalls > 0")["n"]
    memory.close()
    record = {"exchanges": kept, "embedded": embedded, "rehearsed": rehearsed, "sessions": len(sessions),
              "seconds": round(time.monotonic() - started)}
    done.write_text(json.dumps(record))
    return record


async def ingest(run: Path, models: Models, concurrency: int) -> None:
    (run / "memory").mkdir(parents=True, exist_ok=True)
    cache = Cache(run / "vectors256.db", models)
    limit = asyncio.Semaphore(concurrency)

    async def one(item):
        async with limit:
            record = await ingest_one(run, item, cache)
            print(f"  {history(item)}: {record}", flush=True)
            return record
    histories = {history(item): item for item in questions(run)}  # (each history once)
    records = await asyncio.gather(*(one(item) for item in histories.values()))
    total = Counter()
    for record in records:
        total.update(record)
    print(f"ingested {len(records)} histories: {dict(total)}", flush=True)


# ---- answering -----------------------------------------------------------------------------------------------------
SYSTEM = ("You are a chat assistant. You have talked with the user many times before, and it is now {today}. "
          "Dates in brackets are when things were said: work out relative dates such as 'last week' from them. "
          "Answer the user's question as you would in the chat, from what you remember of them; be brief.")
AGENT = SYSTEM + (" Everything said before is kept word for word, and you can look it up: `search` finds the exchanges "
                  "that match what you ask (each with its number and the date it was said), and `read` shows an "
                  "exchange with the ones around it. Search as often as you need: with other words (names, places, "
                  "things) when the first results don't answer, once for each part of a question about several "
                  "things, and for each date you need.")
ORACLE = ("You are a chat assistant, and it is now {today}. Below are earlier chats between you and the user, with "
          "their dates. Answer the user's question from them as you would in the chat; be brief.")
LOCOMO = ("You remember the conversations between {a} and {b}, which went on over many sessions; it is now {today}. "
          "Dates in brackets are when things were said: work out relative dates such as 'last week' from them. Answer "
          "the question with a short phrase (a name, a date, a few words); if what you remember does not answer it, "
          "say it was not mentioned.")
LOCOMO_AGENT = LOCOMO + AGENT[len(SYSTEM):]
TOOLS = [tool for tool in specs("openai") if tool["function"]["name"] in ("search", "read")]


def today(label: str) -> str:
    return datetime.fromtimestamp(moment(label), UTC).strftime("%A, %d %B %Y, %H:%M")


FINAL = "That is all the searching there is time for: answer now, from what you found."


async def agent(models: Models, box: Toolbox, system: str, opening: str, question: str, steps: int = 6,
                final: bool = False) -> tuple:
    """Up to `steps` calls, the last without tools; with `final`, the last is told to answer now (else a model may
    write its next calls out as text)."""
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": (f"{opening}\n\n" if opening else "") + question}]
    did = Counter()
    for turn in range(steps):
        last = turn == steps - 1
        if last and final and turn:
            messages.append({"role": "user", "content": FINAL})
        reply = await models.chat(messages, step="answer", tools=None if last else TOOLS)
        did["calls"] += 1
        calls = reply.get("tool_calls") or []
        if not calls or last:
            return reply.get("content") or "", did
        kept = {"role": "assistant", "content": reply.get("content") or "", "tool_calls": calls}
        if reply.get("reasoning_content"):  # (DeepSeek wants its thinking back while it uses tools)
            kept["reasoning_content"] = reply["reasoning_content"]
        messages.append(kept)
        for call in calls:
            name = call["function"]["name"]
            did[name] += 1
            found = await box.acall(name, call["function"].get("arguments") or "{}")
            did["shown"] += len(found)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": found})
    return "", did


def oracle_text(item: dict) -> str:
    wanted = set(item["answer_session_ids"])
    blocks = []
    for label, session_id, session in sorted(zip(item["haystack_dates"], item["haystack_session_ids"],
                                                 item["haystack_sessions"]), key=lambda row: moment(row[0])):
        if session_id in wanted:
            lines = "\n".join(f"{turn.get('speaker') or ('User' if turn.get('role') == 'user' else 'Assistant')}: "
                              f"{turn.get('content')}" for turn in session)
            blocks.append(f"[{label}]\n{lines}")
    return "\n\n".join(blocks)


def judge_prompt(item: dict, response: str) -> str:
    """LongMemEval's own (src/evaluation/evaluate_qa.py, `get_anscheck_prompt`)."""
    kind, question, answer = item["question_type"], item["question"], item["answer"]
    if item["question_id"].endswith("_abs"):
        return ("I will give you an unanswerable question, an explanation, and a response from a model. Please answer "
                "yes if the model correctly identifies the question as unanswerable. The model could say that the "
                "information is incomplete, or some other information is given but the asked information is not."
                f"\n\nQuestion: {question}\n\nExplanation: {answer}\n\nModel Response: {response}\n\nDoes the model "
                "correctly identify the question as unanswerable? Answer yes or no only.")
    if kind == "single-session-preference":
        return ("I will give you a question, a rubric for desired personalized response, and a response from a model. "
                "Please answer yes if the response satisfies the desired response. Otherwise, answer no. The model does "
                "not need to reflect all the points in the rubric. The response is correct as long as it recalls and "
                f"utilizes the user's personal information correctly.\n\nQuestion: {question}\n\nRubric: {answer}\n\n"
                f"Model Response: {response}\n\nIs the model response correct? Answer yes or no only.")
    base = ("I will give you a question, a correct answer, and a response from a model. Please answer yes if the response "
            "contains the correct answer. Otherwise, answer no. ")
    if kind == "knowledge-update":
        middle = ("If the response contains some previous information along with an updated answer, the response should "
                  "be considered as correct as long as the updated answer is the required answer.")
    else:
        middle = ("If the response is equivalent to the correct answer or contains all the intermediate steps to get the "
                  "correct answer, you should also answer yes. If the response only contains a subset of the information "
                  "required by the answer, answer no. ")
        if kind == "temporal-reasoning":
            middle += ("In addition, do not penalize off-by-one errors for the number of days. If the question asks for "
                       "the number of days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 "
                       "days when the answer is 18), the model's response is still correct. ")
    return (base + middle + f"\n\nQuestion: {question}\n\nCorrect Answer: {answer}\n\nModel Response: {response}\n\n"
            "Is the model response correct? Answer yes or no only.")


async def answer_one(run: Path, item: dict, arm: str, budget: int, models: Models, cache: Cache, name: str, *,
                     steps: int = 6, final: bool = False, cut=(CUT, CUT_FADED), shorten: bool = False,
                     later: float = 0.0) -> dict:
    date = item["question_date"]
    record = {"question_id": item["question_id"], "type": item["question_type"],
              "abstain": item["question_id"].endswith("_abs"), "question": item["question"],
              "gold": item["answer"]}
    if arm == "oracle":
        reply = await models.ask(ORACLE.format(today=today(date)), f"{oracle_text(item)}\n\n{item['question']}",
                                 step="answer")
        did = Counter(calls=1)
    else:
        # A search rehearses what it finds, in the file: each arm works on its own copy of the history as ingested.
        path = run / "work" / name / f"{item['question_id']}.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(run / "memory" / f"{history(item)}.db", path)
        # `later`: the memory as faded as `later` days after the question (the model is told the question's date)
        memory = companion(path, history(item), cache, lambda: moment(date) + later * 86400)
        a, b = item.get("speakers") or ("the user", "")
        system, agentic = (LOCOMO, LOCOMO_AGENT) if item.get("speakers") else (SYSTEM, AGENT)
        try:
            found = await memory.episodes.alook(SUBJECT, item["question"], budget=budget, cut=cut,
                                                shorten=shorten) \
                if budget else []
            opening = memory.episodes.render(found, user_name=a, search=arm == "agent")
            record["opening_chars"] = len(opening)
            if arm == "look":
                reply = await models.ask(system.format(today=today(date), a=a, b=b),
                                         (f"{opening}\n\n" if opening else "") + item["question"], step="answer")
                did = Counter(calls=1)
            else:
                reply, did = await agent(models, Toolbox(memory, SUBJECT), agentic.format(today=today(date), a=a, b=b),
                                         opening, item["question"], steps=steps, final=final)
        finally:
            memory.close()
            path.unlink(missing_ok=True)
    verdict = await models.ask("You grade answers.", judge_prompt(item, reply), step="judge", max_tokens=400)
    record.update(answer=reply, correct=verdict.strip().lower().startswith("yes"), did=dict(did))
    return record


async def answer(run: Path, arm: str, budget: int, models: Models, concurrency: int, *, steps: int = 6,
                 final: bool = False, cut=(CUT, CUT_FADED), shorten: bool = False, later: float = 0.0) -> Path:
    # (runs before 2e2d6e7 weighed the look by fading unless "-nofade"; since then a name always says its bar)
    name = arm if arm == "oracle" else f"{arm}-{budget}" + (f"-s{steps}" if steps != 6 else "") + \
        ("-final" if final else "") + \
        (f"-cut{round(cut[0] * 100)}" + (f"-{round(cut[1] * 100)}" if cut[1] != cut[0] else "") if cut else "-nocut") + \
        ("-shorten" if shorten else "") + (f"-later{later:g}" if later else "")
    path = run / "answers" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(line)["question_id"] for line in path.read_text(encoding="utf-8").split("\n") if line} \
        if path.exists() else set()
    cache = Cache(run / "vectors256.db", models)
    limit = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()

    async def one(item):
        async with limit:
            record = await answer_one(run, item, arm, budget, models, cache, name, steps=steps, final=final,
                                      cut=cut, shorten=shorten, later=later)
            async with lock:
                with path.open("a", encoding="utf-8") as out:
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"  {item['question_id']} ({item['question_type']}): {'✓' if record['correct'] else '✗'}", flush=True)
    await asyncio.gather(*(one(item) for item in questions(run) if item["question_id"] not in done))
    return path


def report(run: Path) -> str:
    lines = ["| arm | " + " | ".join(TYPES) + " | abstain | all | calls/q | searches/q |",
             "|---" * (len(TYPES) + 5) + "|"]
    for path in sorted((run / "answers").glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]
        by = defaultdict(list)
        for row in rows:
            by["abstain" if row["abstain"] else row["type"]].append(row["correct"])
        cell = lambda items: f"{100 * sum(items) / len(items):.0f}% ({len(items)})" if items else "–"
        calls = sum(row["did"].get("calls", 0) for row in rows) / max(1, len(rows))
        searches = sum(row["did"].get("search", 0) for row in rows) / max(1, len(rows))
        lines.append(f"| {path.stem} | " + " | ".join(cell(by[kind]) for kind in TYPES) +
                     f" | {cell(by['abstain'])} | {cell([row['correct'] for row in rows])} | {calls:.1f} | "
                     f"{searches:.1f} |")
    text = "\n".join(lines)
    (run / "report.md").write_text(text + "\n")
    return text


async def main(arguments) -> int:
    run = Path(arguments.out)
    run.mkdir(parents=True, exist_ok=True)
    if arguments.command == "extract":
        if arguments.locomo:
            count = extract_locomo(Path(arguments.locomo), (arguments.only or "").split(",") if arguments.only else [],
                                   run / "questions.jsonl")
            print(f"{count} LoCoMo questions extracted")
            return 0
        wanted = json.loads(Path(arguments.subset).read_text())
        count = extract(Path(arguments.m), wanted, run / "questions.jsonl")
        print(f"{count} of {len(wanted)} questions extracted")
        return 0
    if arguments.command == "report":
        print(report(run))
        return 0
    secrets = keys(Path(arguments.env))
    started = time.monotonic()
    async with Models(secrets, arguments.floor, concurrency=12) as models:
        before = await models.check()
        print(f"DeepSeek balance ¥{before:.2f}", flush=True)
        try:
            if arguments.command == "ingest":
                await ingest(run, models, arguments.concurrency)
            else:
                await answer(run, arguments.arm, arguments.budget, models, arguments.concurrency,
                             steps=arguments.steps, final=arguments.final, cut=cut_of(arguments.cut),
                             shorten=arguments.shorten, later=arguments.later)
        except OutOfBalance as error:
            print(f"stopped: {error}", flush=True)
        after = await models.balance()
        usage = {step: dict(count) for step, count in models.usage.items()}
        with (run / "usage.jsonl").open("a") as out:
            out.write(json.dumps({"command": arguments.command, "arm": arguments.arm, "budget": arguments.budget,
                                  "at": time.time(), "seconds": round(time.monotonic() - started),
                                  "balance_before": before, "balance_after": after,
                                  "spent_cny": round(before - after, 2), "usage": usage}) + "\n")
        print(f"DeepSeek balance ¥{after:.2f} (spent ¥{before - after:.2f}); usage {usage}", flush=True)
    if arguments.command == "answer":
        print(report(run))
    return 0


def cut_of(text: str | None):
    if not text or text == "none":
        return None
    shares = [float(part) for part in text.split(",")]
    return (shares[0], shares[-1])


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("extract", "ingest", "answer", "report"))
    parser.add_argument("--out", required=True, help="the run's folder")
    parser.add_argument("--m", help="longmemeval_m_cleaned.json (extract)")
    parser.add_argument("--locomo", help="locomo10.json (extract LoCoMo instead)")
    parser.add_argument("--only", help="LoCoMo's conversations to extract, by sample id (conv-26,conv-30)")
    parser.add_argument("--subset", help="a JSON list of question ids (extract)")
    parser.add_argument("--arm", choices=ARMS, default="agent")
    parser.add_argument("--budget", type=int, default=6000, help="characters of the first look")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--steps", type=int, default=6, help="the agent's calls, the last without tools")
    parser.add_argument("--final", action="store_true", help="tell the last call to answer now")
    parser.add_argument("--cut", default=f"{CUT},{CUT_FADED}",
                        help="a first look's bar, above the embedder's floor: one margin (0.08), or fresh and fully "
                             "faded (the default, 0.08,0.16), or none")
    parser.add_argument("--shorten", action="store_true", help="a first look shows a faded exchange in part")
    parser.add_argument("--later", type=float, default=0.0, help="days: memory fades as if asked this much later")
    parser.add_argument("--env", default=str(Path(__file__).resolve().parents[2] / ".env"))
    parser.add_argument("--floor", type=float, default=25.0, help="stop under this DeepSeek balance (CNY)")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse())))

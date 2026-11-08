"""Links on LoCoMo: do the exchanges a question needs come to mind more often when a look follows links?

LoCoMo (Maharana et al., 2024) marks the exact turns each answer rests on (`evidence`: "D3:12"), so whether a look
brought them is measured without asking any model. Each conversation is lived again in order, as a companion would
live it: before each exchange is kept, she looks for its first message (`Episodes.look`, her own look, so the links it
uses are renewed); then it is kept and embedded, and links are born from what it reminded her of (`links.py`). Each
question is then asked the day after the last session, by several looks:

    base       the look as it ships (no links followed)
    follow F   links followed: up to F exchanges linked to the best that came, in place of the weakest of the rest,
               each at most `lift` under the look's bar ("any": however far)
    next F     the control: no links, the look as it ships and then the next F by rank alone, however far under the
               bar, within the same budget (as many more exchanges as `follow F` brings, chosen without links)
    no bar     no bar at all, the budget filled by rank

The look fills its budget on nearly every question, so every arm shows about as many characters: what changes is
which exchanges they are.

and each is scored by the share of the question's evidence exchanges it brought, whether it brought them all, and how
many characters it took. Questions whose evidence spans two sessions or more are where links could help; the rest
show whether they cost anything.

    python -m bench.association live --locomo locomo10.json --out RUN [--cache vectors256.db] [--follow 3]
    python -m bench.association score --out RUN

Embeddings are OpenAI's text-embedding-3-small at 256 dimensions, kept by the text's hash (`bench.longmemeval.Cache`):
LoCoMo's exchanges are embedded exactly as `bench.longmemeval` embeds them, so its cache serves. OPENAI_API_KEY only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import shutil
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from mneme_llm import text as texts
from mneme_llm.episodes import BUDGET, CUT, CUT_FADED

from bench.locomo import Models, keys
from bench.longmemeval import Cache, companion, moment

UTC = timezone.utc
SUBJECT = "user"
FOLLOWS = ((1, 0.1), (2, 0.1), (3, 0.1), (5, 0.1), (3, 0.05), (3, 0.2), (3, 1.0))
NEXTS = (1, 3, 5)
PAIRED = ("follow 1 0.1", "follow 3 0.1", "follow 5 0.1", "next 1", "next 3", "next 5")


def conversations(source: Path) -> list[dict]:
    """Each conversation's sessions as `bench.longmemeval` keeps them (the same lines, times and so the same embedded
    text), with the turn ids each exchange holds, and its questions."""
    found = []
    for raw in json.loads(source.read_text(encoding="utf-8")):
        talk = raw["conversation"]
        a = talk["speaker_a"]
        numbers = sorted(int(key.split("_")[1]) for key in talk if key.count("_") == 1 and
                         key.startswith("session_") and key.split("_")[1].isdigit())
        sessions = []
        for number in numbers:
            when = datetime.strptime(talk[f"session_{number}_date_time"].strip(), "%I:%M %p on %d %B, %Y")
            label = when.strftime("%Y/%m/%d (%a) %H:%M")
            exchanges, current, roles, ids = [], [], [], []
            for turn in talk[f"session_{number}"]:
                user = turn["speaker"] == a
                if user and current and not roles[-1]:
                    exchanges.append((current, ids))
                    current, roles, ids = [], [], []
                content = " ".join(str(turn.get("text") or "").split()) + (
                    f" [shares a photo: {turn['blip_caption']}]" if turn.get("blip_caption") else "")
                current.append((turn["speaker"], content))
                roles.append(user)
                ids.append(turn["dia_id"])
            if current:
                exchanges.append((current, ids))
            sessions.append({"id": f"s{number}", "at": moment(label), "exchanges": exchanges})
        last = max(session["at"] for session in sessions)
        found.append({"id": raw["sample_id"], "first": a, "sessions": sessions, "asked": last + 86400,
                      "qa": raw["qa"]})
    return found


def message(lines: list[tuple[str, str]], first: str) -> str:
    """What she looks for before an exchange is kept: its first speaker's opening lines."""
    opening = []
    for speaker, said in lines:
        if opening and speaker != lines[0][0]:
            break
        opening.append(said)
    return " ".join(opening)


async def live_one(run: Path, item: dict, cache: Cache, follow: int) -> dict:
    path = run / "memory" / f"{item['id']}.db"
    done = run / "memory" / f"{item['id']}.json"
    if done.exists():
        return json.loads(done.read_text())
    path.unlink(missing_ok=True)
    now = [0.0]
    memory = companion(path, item["id"], cache, lambda: now[0])
    episodes = memory.episodes
    turns, followed, started = {}, 0, time.monotonic()
    for session in sorted(item["sessions"], key=lambda session: session["at"]):
        for index, (lines, ids) in enumerate(session["exchanges"]):
            now[0] = session["at"] + index * 30
            query = texts.query(message(lines, item["first"]))
            if query.strip():
                found = await episodes._found(query)
                brought = {}
                episodes.look(SUBJECT, query, found=found, follow=follow, use=True, brought=brought)
                followed += len(brought)
            episode = episodes.keep(SUBJECT, lines, at=now[0], conversation=session["id"])
            for turn in ids:
                turns[turn] = episode.id
            for attempt in range(10):
                if await episodes.prepare(SUBJECT, first=[episode.id]) or attempt == 9:
                    break
                await asyncio.sleep(max(1.0, episodes.meaning.rest.until - time.monotonic()))
    links = episodes.links.all(SUBJECT, at=now[0])
    record = {"exchanges": len(set(turns.values())), "links": len(links), "followed": followed,
              "used": sum(1 for link in links if link.uses), "seconds": round(time.monotonic() - started),
              "turns": turns}
    memory.close()
    done.write_text(json.dumps(record))
    return record


async def live(arguments) -> None:
    run = Path(arguments.out)
    (run / "memory").mkdir(parents=True, exist_ok=True)
    if arguments.cache and not (run / "vectors256.db").exists():
        shutil.copy(arguments.cache, run / "vectors256.db")
    items = [item for item in conversations(Path(arguments.locomo))
             if not arguments.only or item["id"] in arguments.only.split(",")]
    (run / "conversations.json").write_text(json.dumps(items))
    async with Models(keys(Path(arguments.env)), floor=0.0) as models:
        cache = Cache(run / "vectors256.db", models)
        limit = asyncio.Semaphore(arguments.concurrency)

        async def one(item):
            async with limit:
                record = await live_one(run, item, cache, arguments.follow)
                print(f"  {item['id']}: " + json.dumps({k: v for k, v in record.items() if k != "turns"}), flush=True)
        await asyncio.gather(*(one(item) for item in items))
        print(f"embeddings: {dict(models.usage['embed'])}", flush=True)


def arms() -> list[tuple[str, dict]]:
    return ([("base", {})] + [(f"follow {follow} {'any' if lift >= 1 else lift}", {"follow": follow, "lift": lift})
                              for follow, lift in FOLLOWS] + [(f"next {count}", {"next": count}) for count in NEXTS] +
            [("no bar", {"cut": None})])


def next_by_rank(episodes, query: str, found, count: int) -> list:
    """The look as it ships, then the next `count` by rank alone, within the same budget."""
    order, cleared = episodes._ranked(SUBJECT, query, found, cut=(CUT, CUT_FADED))
    chosen = episodes._fill(order, cleared, BUDGET)
    taken = {episode.id for episode in chosen}
    used = sum(len(episodes.shown(episode)) + 2 for episode in chosen)
    for episode in episodes._get_many([id for id in order if id not in taken][:count]):
        size = len(episodes.shown(episode)) + 2
        if used + size <= BUDGET:
            chosen.append(episode)
            used += size
    return chosen


async def score(arguments) -> None:
    run = Path(arguments.out)
    items = json.loads((run / "conversations.json").read_text())
    rows = []
    async with Models(keys(Path(arguments.env)), floor=0.0) as models:
        cache = Cache(run / "vectors256.db", models)
        for item in items:
            record = json.loads((run / "memory" / f"{item['id']}.json").read_text())
            turns = record["turns"]
            now = [item["asked"]]
            memory = companion(run / "memory" / f"{item['id']}.db", item["id"], cache, lambda: now[0])
            episodes = memory.episodes
            sessions = {turn: turn.split(":")[0] for turn in turns}
            for number, qa in enumerate(item["qa"]):
                evidence = [turn for turn in qa.get("evidence") or [] if turn in turns]
                if not evidence:
                    continue
                needed = {turns[turn] for turn in evidence}
                query = texts.query(qa["question"])
                found = await episodes._found(query)
                row = {"conversation": item["id"], "question": number, "category": qa.get("category"),
                       "needed": len(needed), "spread": len({sessions[turn] for turn in evidence}), "arms": {}}
                for name, options in arms():
                    brought = {}
                    if "next" in options:
                        came = next_by_rank(episodes, query, found, options["next"])
                    else:
                        options = {"cut": (CUT, CUT_FADED), **options}
                        came = episodes.look(SUBJECT, query, found=found, budget=BUDGET, brought=brought, **options)
                    ids = {episode.id for episode in came}
                    row["arms"][name] = {"share": len(needed & ids) / len(needed), "all": needed <= ids,
                                         "chars": sum(len(episodes.shown(episode)) + 2 for episode in came),
                                         "count": len(came), "brought": len(brought),
                                         "brought_needed": len(needed & set(brought))}
                rows.append(row)
            memory.close()
    (run / "scores.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    print(report(rows))


def report(rows: list[dict]) -> str:
    groups = {"evidence in 2+ sessions": [row for row in rows if row["spread"] > 1],
              "evidence in 1 session": [row for row in rows if row["spread"] == 1],
              "all with evidence": rows}
    out = []
    for title, group in groups.items():
        if not group:
            continue
        out.append(f"\n## {title} ({len(group)} questions)\n")
        out.append(f"{'arm':16} {'share':>6} {'all':>6} {'chars':>6} {'came':>5} {'linked':>6} {'linked+':>7}")
        for name, _ in arms():
            arm = [row["arms"][name] for row in group]
            out.append(f"{name:16} {100 * statistics.mean(a['share'] for a in arm):5.1f}% "
                       f"{100 * statistics.mean(a['all'] for a in arm):5.1f}% "
                       f"{statistics.mean(a['chars'] for a in arm):6.0f} {statistics.mean(a['count'] for a in arm):5.1f} "
                       f"{statistics.mean(a['brought'] for a in arm):6.2f} "
                       f"{sum(a['brought_needed'] for a in arm):7d}")
        out.append("\npaired with base, by the share of evidence brought: questions better / worse")
        for name in PAIRED:
            better = sum(row["arms"][name]["share"] > row["arms"]["base"]["share"] for row in group)
            worse = sum(row["arms"][name]["share"] < row["arms"]["base"]["share"] for row in group)
            out.append(f"  {name:16} {better:4} / {worse:<4} (sign test p = {sign_test(better, worse):.3f})")
    return "\n".join(out)


def sign_test(better: int, worse: int) -> float:
    """Two-sided: how likely a split at least this uneven is when each question is a coin toss."""
    n, k = better + worse, min(better, worse)
    if not n:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=("live", "score", "report"))
    parser.add_argument("--locomo", help="locomo10.json")
    parser.add_argument("--out", required=True)
    parser.add_argument("--cache", help="a vectors256.db to start from (bench.longmemeval's)")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--follow", type=int, default=3, help="what her own looks follow links for while living")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--only", help="conversations to live, such as conv-26,conv-30")
    arguments = parser.parse_args(argv)
    if arguments.step == "live":
        asyncio.run(live(arguments))
    elif arguments.step == "score":
        asyncio.run(score(arguments))
    else:
        rows = [json.loads(line) for line in (Path(arguments.out) / "scores.jsonl").read_text().splitlines() if line]
        print(report(rows))


if __name__ == "__main__":
    main()

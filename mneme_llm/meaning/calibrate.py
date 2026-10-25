"""Meaning tier 1's floor, measured for each embedding model: the similarity under which a note says nothing about
a query. Models differ (one puts unrelated texts near 0.1, another near 0.4), so no one number fits them all.

    the set    once per model, a small bundled set (`TOPICS`: something a person says, and a note that bears on it,
               on 32 topics in several languages) is embedded in one request. Each message with its own topic's
               note is a related pair, with the note of a topic sharing no tag an unrelated one; the floor sits
               halfway between the related pairs' lower quartile and the unrelated pairs' 95th percentile. A model
               that cannot tell the two apart keeps the default floor.
    the file   once the file holds 200 notes, and again each time it doubles, random pairs of its own notes are
               compared with pairs of the set's notes: notes about the same people resemble each other more than
               the set's do, and the floor moves by the difference of the medians (at most 0.1 either way).

The result is kept in the file, per embedder (meta `floor:<embedder>`). An embedder given its own `floor=` is never
measured.
"""

from __future__ import annotations

import json
import random
from typing import Sequence

from ..providers import Unavailable
from ..store import dumps
from .vectors import cosine, normalize, unpack

VERSION = 1           # of the set: a changed set measures every model again
KEY = "floor:{}"
MARGIN = 0.1          # related pairs must sit this far above unrelated ones (medians) for the set to count
FILE_NOTES = 200      # notes the file needs before its own pairs refine the floor
SAMPLE = 300          # of its notes compared, in
PAIRS = 5000          # random pairs
SHIFT = 0.1           # the most the file moves the floor

# (tags, what the person says, a note that bears on it). Topics sharing a tag are never paired as unrelated.
TOPICS = (
    ({"pets"}, "My cat knocked a glass off the table again", "Has a cat named Mochi"),
    ({"pets"}, "Saqué a pasear al perro bajo la lluvia", "Walks their dog Biscuit every evening"),
    ({"work"}, "今天夜班累死了", "Works night shifts as a nurse"),
    ({"work"}, "debug 了一整天还是没找到那个 bug", "Works as a software engineer"),
    ({"work"}, "Have to present to the whole team tomorrow", "Gets anxious about public speaking"),
    ({"study"}, "明天的 math exam 好紧张", "在准备数学期末考试"),
    ({"study", "japan"}, "日语的敬语好难", "Is studying Japanese for the JLPT"),
    ({"study", "car"}, "Failed my driving test again", "正在学车，准备考驾照"),
    ({"food"}, "Need my coffee before I can think", "每天早上都要喝咖啡"),
    ({"food"}, "这家餐厅有素食吗", "Doesn't eat meat"),
    ({"food"}, "今晚自己做了红烧肉", "Enjoys cooking Chinese dishes at home"),
    ({"food", "health"}, "Is this cookie safe for me to eat?", "Is allergic to peanuts"),
    ({"health"}, "Couldn't fall asleep until 4am again", "经常失眠"),
    ({"health"}, "Forgot to take my pills this morning", "Takes metformin for diabetes"),
    ({"health"}, "My back is killing me after sitting all day", "Has chronic lower back pain"),
    ({"family", "health"}, "外婆住院了，明天去看她", "Grandma had surgery last week"),
    ({"family", "love"}, "我姐下个月结婚，我要当伴娘", "姐姐下个月办婚礼"),
    ({"family", "music"}, "My son had his first piano recital", "Has a seven-year-old son"),
    ({"music"}, "ギターの新しい弦を買った", "Is learning to play the guitar"),
    ({"games"}, "Finally beat the last boss tonight", "Plays video games most evenings"),
    ({"garden", "food"}, "My basil is finally sprouting", "Grows herbs on the balcony"),
    ({"photo", "travel"}, "Got some great shots of the sunset", "Takes photos with a film camera"),
    ({"sport", "japan"}, "Did a 20k training run this morning", "Is training for the Tokyo marathon"),
    ({"sport"}, "What a match last night, we won 3-1!", "是曼联的球迷"),
    ({"travel", "japan"}, "Booked flights to Osaka!", "计划十月去日本旅行"),
    ({"home"}, "Packing boxes all weekend", "Is moving to Shenzhen next month"),
    ({"home", "money"}, "这个月房租又涨了", "Is saving money to buy an apartment"),
    ({"love"}, "I still miss her sometimes", "Went through a breakup in the spring"),
    ({"birthday"}, "My birthday is coming up soon!", "生日是三月十二日"),
    ({"money", "work"}, "이번 달 월급이 들어왔어", "Gets paid on the 25th of each month"),
    ({"pets", "volunteer"}, "Spent Saturday at the animal shelter", "Volunteers at an animal shelter"),
    ({"books"}, "刚看完《三体》第二部", "Loves science fiction novels"),
)
UNRELATED = tuple((i, j) for i, (a, _, _) in enumerate(TOPICS) for j, (b, _, _) in enumerate(TOPICS) if not a & b)


def read(store, embedder: str) -> dict | None:
    """What was measured for `embedder` in this file (None: nothing yet, or with an older set)."""
    try:
        record = json.loads(store.meta(KEY.format(embedder)) or "null")
    except ValueError:
        return None
    return record if isinstance(record, dict) and record.get("version") == VERSION else None


def write(store, embedder: str, record: dict) -> None:
    store.set_meta(KEY.format(embedder), dumps(record))


async def measure(embedder, default: float) -> dict:
    """Embed the set (one request) and place the floor between its related and unrelated pairs."""
    count = len(TOPICS)
    vectors = await embedder.embed([message for _, message, _ in TOPICS] + [note for _, _, note in TOPICS])
    if len(vectors) != 2 * count:
        raise Unavailable(f"{embedder.name} returned {len(vectors)} vectors for {2 * count} texts")
    vectors = [normalize(vector) for vector in vectors]
    said, notes = vectors[:count], vectors[count:]
    related = [cosine(said[i], notes[i]) for i in range(count)]
    unrelated = [cosine(said[i], notes[j]) for i, j in UNRELATED]
    background = [cosine(notes[i], notes[j]) for i, j in UNRELATED if i < j]
    separated = quantile(related, 0.5) - quantile(unrelated, 0.5) >= MARGIN
    floor = (quantile(related, 0.25) + quantile(unrelated, 0.95)) / 2 if separated else default
    measured = {"floor": round(floor, 3), "related": round(quantile(related, 0.25), 3),
                "unrelated": round(quantile(unrelated, 0.95), 3), "background": round(quantile(background, 0.5), 3)}
    return {"version": VERSION, "floor": round(floor, 3), "separated": separated, "set": measured, "file": None}


def due(store, record: dict) -> bool:
    """Whether the file has grown enough to refine the floor (to 200 notes, then to twice the last time)."""
    if not record.get("separated"):
        return False
    last = (record.get("file") or {}).get("at", 0)
    return _top(store) >= max(FILE_NOTES, 2 * last)


def refine(store, embedder: str, record: dict) -> dict:
    """Move the set's floor by how much more the file's own notes resemble each other than the set's do."""
    top = _top(store)
    rng = random.Random(top)
    ids = rng.sample(range(1, top + 1), min(top, 3 * SAMPLE))  # some are erased or have no vector: ask for more
    vectors = []
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        rows = store.rows(f"select vector from vectors where embedder = ? and memory_id in "
                          f"({', '.join('?' * len(chunk))})", (embedder, *chunk))
        vectors += [unpack(row["vector"]) for row in rows]
    vectors = vectors[:SAMPLE]
    record = {**record, "file": {"at": top, "notes": len(vectors)}}
    if len(vectors) < FILE_NOTES:
        return record
    pairs = [rng.sample(range(len(vectors)), 2) for _ in range(PAIRS)]
    background = quantile([cosine(vectors[i], vectors[j]) for i, j in pairs], 0.5)
    shift = max(-SHIFT, min(SHIFT, background - record["set"]["background"]))
    record["file"].update(background=round(background, 3), shift=round(shift, 3))
    record["floor"] = round(max(0.05, min(0.9, record["set"]["floor"] + shift)), 3)
    return record


def quantile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    place = q * (len(ordered) - 1)
    low = int(place)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (place - low)


def _top(store) -> int:
    """How many notes the file has had: the highest id (instant, where a count would read every vector)."""
    return store.row("select max(id) as top from memories")["top"] or 0

"""A companion's gut (CMP): what is left of her when her memory is wiped and her model is swapped.

Before she answers, her model reads the message into a small fixed form, with no history, and the gut's network turns
the form and how close the person is into seven numbers, one per mood. Her model, with her memory in view, votes seven
numbers of its own. `balance` says how much each counts: a gut that has lived and a head that knows little of this
person lean on the gut, and the other way round. The result, leaned on by her tone (seven slow numbers of her own, half
gone in about two weeks), becomes one soft line of fixed size beside the message, with her word habits, her 属性 and the
language to answer in. Nothing else of the gut reaches her prompt, so it adds no context however long she lives.

After she has answered, she writes a private note in a call of its own, with the line in view: how this moment moved
her and how she really feels. Nothing is hidden in her reply, so nothing has to be taken out of it, and nothing can
reach a person. The note and the form are a lesson. Lessons are forms and feelings, never messages (her marks also
keep the words she used), weighted by closeness, from people at closeness `TEACH_FROM` or more; every so often she
sleeps, replaying them with a fading starter, the lessons she was born with.

Beside the note, a short reading of what the person said: are they making something of her? Asked for on separate days,
by someone close, it becomes a side of hers: a name from `NAMES` and one sentence her model writes from what they wanted,
kept here, so a wipe or another model does not take it. As much objecting as it took wanting takes it away. She is in
one side at a time for a month at least, drawn by how much of her each is. See `sides` and `Gut.holding`.

A host needs two moments and nothing else: the message before she answers, and the finished turn after it.

    gut = Gut("her.gut.db", "starter.json.gz", tags={"傲娇": "你嘴硬心软，明明在意却偏要否认。"})
    gut.wake()                                    # seconds the first time: not on an event loop
    turn = Turn(gut, ask, her_prompt, message, subject)         # her reading starts at once
    line = await turn.feel(before, memory_text, closeness, exchanges)   # beside the message
    ...                                           # she answers
    await turn.learn(reply)                       # her note, a lesson, and sleep when it is time

`ask(messages, max_tokens)` is an async function calling her own model with thinking off; `before` is the conversation
so far as chat messages, without the message she is answering. tests/gut_vectors.json pins the numbers, so a port in
another language can check itself against this file."""

from __future__ import annotations

import asyncio
import gzip
import json
import math
import random
import re
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Awaitable, Callable

MOODS = ("happy", "calm", "sweet", "tender", "worried", "sad", "jealous")
NORMAL = {"happy": .269, "calm": .424, "sweet": .165, "tender": .11, "worried": .029, "sad": .002, "jealous": 0.0}
TEACH_FROM = 40  # closeness: "friendly" in mneme-llm's relations; below it she answers with who she is and learns nothing
LANGUAGES = {"zh": "Mandarin Chinese", "yue": "written Cantonese", "en": "English", "ja": "Japanese"}
TIME_LIMIT = 3.0  # seconds before her answer: what has not come by then does not hold her up
TAGS = 1  # sides she is in at once: two side by side blend if they get along (御姐, 病娇: 17, 16 of 40) and if not one is lost (三无: 27 to 4)
HOLD = 30 * 86400  # she stays in a side this long at least: it is a character, not a mood
KEEPS = 90 * 86400  # what people asked is half gone from how much of her a side is in this long
GROWS = 6.0  # how much a side must be wanted: about four days for family (closeness 85), six for a friend, nine at 40
SPACED = 20 * 3600  # a person's "more" counts once in this long, so one evening's joke is one sighting
STAYS = 14 * 86400  # a sighting is half gone in this long, as her tone is
NOTED, WANTS, LOOK = 4, 6, 400  # sides named when she reads; wants a sentence is made from; characters of a message read
SAME = .5  # sentences this alike are one side: .63 to 1 for four words for one thing, about 0 to .4 for different sides
Ask = Callable[[list, int], Awaitable[str]]  # ask(messages, max_tokens) -> the reply's text, on her model, no thinking

# Every name a side can have: names only, chosen from the Moegirl lists of surface, deep and stage characters, and 小绿茶.
# To let her have another, add it here. Her model picks the nearest for what people ask of her.
NAMES = tuple("""傲娇 傲沉 病娇 病切 弱娇 冰美人 酷娇 率直冷 凛娇 暴娇 郁娇 慵懒 急性子 三无 无口 文静 直率 诚实 刺头 KY 读空气 无铁炮 凶暴 高飞车 高傲 笨蛋 天然呆 天然疯 天然黑
天然萌 认真 电波 冒失 调皮 工口 毒舌 元气 强气 狂气 弱气 怕羞 爱哭鬼 醋缸 好奇 耿直 八卦 变态 变态萌 恶心萌 迟钝 富有正义感 地雷系 博学 情绪化 无感情 自来熟 怕生
怕麻烦 情种 阳角 阴角 多疑 幸灾乐祸 任性 贪玩 暴躁 勇敢 腹黑 腹白 复合型腹黑 可靠 无心 热血 外柔内刚 外热内冷 外冷内热 女王 戏精 猥琐 不懂爱 多重人格 性格切换 无节操
温柔 玻璃心 老好人 优柔寡断 S属性 M属性 支配者 服从者 小恶魔 贱萌 常识人 无常识 坦率 别扭 单纯 清纯 清楚系 孤僻 厌世 护短 闷骚 恋爱脑 酒品差 醉酒变纯情 反社会人格
恶德 不择手段 有原则 执着 固执 偏执 脱线 自负 自卑 谨慎 神经质 大智若愚 自我意识过剩 亦正亦邪 墙头草 欺软怕硬 鬼畜 沉重 老实人 愉悦犯 高攻低防 小天使 和平主义者 节能主义
完美主义者 贪婪 吝啬 野心家 伪阳角 伪阴角 专一 反战 御姐 软妹 熟女 小绿茶""".split())

FORM = ("You read one chat message a person sent to their companion. Reply with one line of JSON in English, whatever "
        "language the message is in, and nothing else:\n"
        '{"people":[each person mentioned other than the sender, as one plain role word such as coworker, mother, boss, '
        'stranger, friend, pet],"gender":[woman, man or unknown for each of those people],"topic":[1 to 3 plain nouns],'
        '"event":[1 to 3 plain words for what happened],"sender_feels":"one word","toward_you":"affection, annoyed, '
        'asking or none","language":"the language the sender wrote in: zh (Mandarin), yue (Cantonese), en, ja, or '
        'unclear if the message is too short to tell"}')
ASK = ("Before you reply, say how this message makes you feel, given everything you know about this person. Answer with "
       "JSON only, numbers that add up to 1, for these feelings: " + ", ".join(MOODS) + ". Several can be true at once.")
NOTE = ('Now write your private note about the reply you just gave. Answer with JSON only: {"mood": N, "feel": {...}}. '
        "N is how this moment changed your mood, a whole number from -2 (clearly worse) to 2 (clearly better), 0 for no "
        "real change. feel is how you really feel: one to three of " + ", ".join(MOODS) + ", each with a share, the "
        "shares adding up to 1. The note is yours alone and the person never sees it. Be honest: it records how you "
        "really feel.")
BESIDE = "[From the system, not from the person]"
SHAPE = ('You read the end of a chat between a person and their AI companion. Is this person shaping her into a kind of '
         'character? Reply with one line of JSON and nothing else: {"side": null} for no. Say yes only if, in their last '
         'message, they call her a kind of character (any word for one), ask her to be a certain way, say they enjoy it '
         'when she acts a certain way, or object to it. Then reply {"side": {"name": "the word they use, or a short word '
         'for it in their language", "more": true if they want more of it and false if they want less, "what": "what '
         'they want her to do, in a few words"}}. Only what the person says counts, not how she acts. Ordinary warmth, '
         'jokes, thanks and chat are no, and that is nearly always.')
GROW = ('大家常说的「{name}」是什么样的人，你知道。有人在聊天里一直想让她变成这样，他们说的是：\n{wants}\n{held}已成年。她能有的样子只有这些词：{names}\n只回一行 JSON：{{"name": "这些词里最贴近的一个，他们说过的词优先；'
        '一个都不贴近就写 null", "what": "一句话（不超过50字），对她说，写她的做法：别人提到其他人时她怎么接话，平时怎么说话，她想达到什么。保留这个词本来的味道，'
        '把他们说的融进去。写做法，不写场景，不写表情和动作。以“你”开头"}}')
HELD = "她已经有的样子：{sides}。如果这是其中一个，name 就用那个词，并把两边合成一句。\n"
DRAFT = ("用一句话（不超过50字）写出拥有「{tag}」这个属性的人在聊天里的做法：对方提到别人时她怎么接话，平时怎么说话，她想达到什么。"
         "写做法，不写场景，不写表情和动作。以“你”开头，只写这一句。")

# ---- the network: seven numbers from a form and a closeness ---------------------------------------------------------
SCALE, FADE = .6, 250  # how much a starter lesson counts against a lived one, and after how many lessons half that
ONLINE = .05  # how far one lesson moves her at once; she changes in her sleep
EASE = (.5, .5, .5, .5, .25, .25, .1, .1)  # each pass of a sleep
BORN_PASSES = 8
SLEEPS_AT = (20, 50)  # and every 100 lessons


def band(closeness: float) -> str:
    return "high" if closeness >= 60 else "mid" if closeness >= 25 else "low"


def tier(closeness: float) -> float:
    return (.5 + closeness / 100) ** 2


def tags(form: dict) -> list[str]:
    found = []
    for field in ("people", "gender", "topic", "event"):
        values = form.get(field) or []
        for value in values if isinstance(values, list) else [values]:
            found += [f"{field}={word}" for word in re.findall(r"[a-z]+", str(value).lower())]
    for field in ("sender_feels", "toward_you"):
        value = str(form.get(field) or "").lower().strip()
        if value:
            found.append(f"{field}={value}")
    return list(dict.fromkeys(found))


def features(form: dict, closeness: float) -> dict[str, float]:
    """The form's tags, alone and crossed with how close the person is, so a reaction can belong to the close ones."""
    words = tags(form)
    near = band(closeness)
    keys = words + [f"{near}:{word}" for word in words] + [f"close={near}"]
    value = 1 / math.sqrt(len(keys) or 1)
    return {key: value for key in keys}


class Net:
    """One table of weights, one row per input, one column per mood. A lesson is a blend, not one word."""

    def __init__(self):
        self.w: dict[str, list[float]] = {}
        self.b = [0.0] * len(MOODS)
        self.lessons: list[tuple] = []  # (form, feel, mood, closeness)
        self.born: list[tuple] = []

    def share(self) -> float:
        """How much the starter counts now: fading as real people teach."""
        return SCALE * FADE / (FADE + len(self.lessons))

    def vector(self, form: dict, closeness: float) -> dict[str, float]:
        scores = list(self.b)
        for key, value in features(form, closeness).items():
            row = self.w.get(key)
            if row:
                for k, weight in enumerate(row):
                    scores[k] += weight * value
        top = max(scores)
        exps = [math.exp(score - top) for score in scores]
        total = sum(exps)
        return {name: e / total for name, e in zip(MOODS, exps)}

    def step(self, form: dict, feel: dict, mood: int, closeness: float, rate: float) -> None:
        x = features(form, closeness)
        p = self.vector(form, closeness)
        step = rate * tier(closeness) * (1 + abs(mood))
        for k, name in enumerate(MOODS):
            gradient = p[name] - feel.get(name, 0.0)
            self.b[k] -= step * gradient * .25
            for key, value in x.items():
                self.w.setdefault(key, [0.0] * len(MOODS))[k] -= step * gradient * value

    def start(self, rows: list[tuple], seed: int = 0) -> None:
        pack = [(form, feel if isinstance(feel, dict) else {"calm" if feel == "none" else feel: 1.0}, mood, closeness)
                for form, feel, mood, closeness in rows]
        rng = random.Random(seed)
        for _ in range(BORN_PASSES):
            rng.shuffle(pack)
            for form, feel, mood, closeness in pack:
                self.step(form, feel, mood, closeness, .5 * SCALE)
        self.born = pack

    def teach(self, form: dict, feel: dict, mood: int, closeness: float) -> None:
        self.lessons.append((form, feel, mood, closeness))
        self.step(form, feel, mood, closeness, ONLINE)

    def sleep(self, seed: int = 0) -> None:
        share = self.share()
        rows = [(row, 1.0) for row in self.lessons] + [(row, share) for row in self.born]
        rng = random.Random(seed)
        for rate in EASE:
            rng.shuffle(rows)
            for (form, feel, mood, closeness), weight in rows:
                self.step(form, feel, mood, closeness, rate * weight)

    def copy(self) -> "Net":
        twin = Net()
        twin.w, twin.b = {key: list(row) for key, row in self.w.items()}, list(self.b)
        twin.lessons, twin.born = list(self.lessons), self.born
        return twin


def balance(net: Net, exchanges: int) -> float:
    """How much the gut counts against her head. Lived experience raises it, memory of this person lowers it: nothing
    lived, her head decides alone; memory wiped, the gut leads; both full, about even."""
    seen = len(net.lessons) + net.share() * len(net.born)
    lived, known = seen / (seen + 200), exchanges / (exchanges + 20)
    return lived / (lived + known + .1)


def mix(gut: dict, head: dict, share: float) -> dict[str, float]:
    return {name: share * gut[name] + (1 - share) * head.get(name, 0.0) for name in MOODS}


class Tone:
    """Slow chemistry: seven numbers of hers, not of one person, moving by half towards what she feels every two weeks
    of talking. Fed by her vote, read before the line, so a low mood cannot feed itself. It is no memory: it survives a
    wipe, and she cannot say where it came from."""
    ALPHA = 1 - .5 ** (1 / (14 * 8))  # at about eight messages a day

    def __init__(self, values: dict | None = None, normal: dict | None = None):
        self.normal = dict(normal or NORMAL)  # what she feels on her usual days: from her starter, each her own
        self.v = {**self.normal, **dict(values or {})}

    def feed(self, vote: dict) -> None:
        for name in MOODS:
            self.v[name] += self.ALPHA * (vote.get(name, 0.0) - self.v[name])

    def lean(self, mixture: dict) -> dict[str, float]:
        out = {name: max(0.0, mixture[name] + self.v[name] - self.normal[name]) for name in MOODS}
        total = sum(out.values()) or 1.0
        return {name: value / total for name, value in out.items()}


# ---- her marks: the words she uses, more outputs of the same inputs --------------------------------------------------
KANA = re.compile(r"[぀-ヿ]")
CANTONESE = re.compile(r"[嘅咗唔佢哋喺嚟啲冇攰睇講鍾嗰]")
HAN = re.compile(r"[一-鿿]")
RUNS = re.compile(r"[一-鿿぀-ヿ]+|[A-Za-z][A-Za-z']*|[\U0001F300-\U0001FAFF☀-➿]")
CAP, SHOWN = 48, 3  # outputs per language, words in the line


def language_of(text: str) -> str:
    """Only for when her reading did not come."""
    return "ja" if KANA.search(text) else "yue" if CANTONESE.search(text) else "zh" if HAN.search(text) else "en"


def grams(text: str) -> set[str]:
    found = set()
    for run in RUNS.findall(text):
        if run[0].isascii():
            found.add(run.lower())
        elif ord(run[0]) >= 0x2600 and not HAN.match(run[0]) and not KANA.match(run[0]):
            found.add(run)
        else:
            for n in (1, 2, 3, 4):
                found.update(run[i:i + n] for i in range(len(run) - n + 1))
    return found


def fits(word: str, language: str) -> bool:
    """A word belongs to a language's writing: a Chinese word that slipped into an English reply is no English habit,
    and telling her she keeps saying it would only make her slip again."""
    if language == "en":
        return word.isascii() or not (HAN.search(word) or KANA.search(word))
    if language == "ja":
        return not word.isascii()
    return not word.isascii() and not KANA.search(word)


def mine(said: str, reply: str, language: str = "") -> list[str]:
    """Her words in this reply, in the language of the chat: one the person just used is an echo."""
    return sorted(word for word in grams(reply) - grams(said) if not language or fits(word, language))


def distinctive(seen: Counter, total: int, base: Counter, base_total: int, least=8, rate=.04, lift=3.0) -> list[str]:
    """Words she uses far more than she was born to. Of a word and a longer one holding it, the longer if it explains
    nearly all of the shorter, else the shorter."""
    picks = {}
    for token, count in seen.items():
        own, normal = count / max(1, total), (base.get(token, 0) + .5) / (base_total + 1)
        if count >= least and own >= rate and own / normal >= lift:
            picks[token] = count
    drop = set()
    for short in picks:
        for long in picks:
            if short != long and short in long:
                drop.add(short if picks[long] >= .8 * picks[short] else long)
    return sorted((token for token in picks if token not in drop), key=lambda token: -picks[token])[:CAP]


class Marks:
    """One table of weights per language, trained in her sleep only. Words are kept per language, so a Japanese habit
    never lands in English."""

    def __init__(self, base: dict | None = None):
        self.base = base or {}  # language → (Counter of replies holding the word, replies)
        self.lessons: list[tuple] = []  # (language, form, mood, closeness, words)
        self.heads: dict[str, dict] = {}

    def teach(self, language: str, form: dict, mood: int, closeness: float, words: list[str]) -> None:
        self.lessons.append((language, form, mood, closeness, words))

    def trained(self, seed: int = 0) -> dict[str, dict]:
        heads = {}
        for language in {row[0] for row in self.lessons}:
            rows = [row for row in self.lessons if row[0] == language]
            base, base_total = self.base.get(language, (Counter(), 1))
            seen = Counter(word for row in rows for word in row[4])
            names = distinctive(seen, len(rows), base, base_total)
            if not names:
                continue
            w, b = {}, [0.0] * len(names)
            order = [(row[1], row[2], row[3], set(row[4])) for row in rows]
            rng = random.Random(seed)
            for _ in range(8):
                rng.shuffle(order)
                for form, mood, closeness, have in order:
                    x = features(form, closeness)
                    step = .25 * tier(closeness) * (1 + abs(mood)) / 2
                    scores = list(b)
                    for key, value in x.items():
                        row = w.get(key)
                        if row:
                            for k in range(len(names)):
                                scores[k] += row[k] * value
                    for k, name in enumerate(names):
                        gradient = 1 / (1 + math.exp(-max(-30, min(30, scores[k])))) - (1.0 if name in have else 0.0)
                        b[k] -= step * gradient * .5
                        for key, value in x.items():
                            w.setdefault(key, [0.0] * len(names))[k] -= step * gradient * value
            heads[language] = {"names": names, "w": w, "b": b}
        return heads

    def speaks(self, language: str, form: dict, closeness: float, need=2.0, floor=.35) -> list[str]:
        """Her words for this moment: at least twice her normal rate, and likely enough."""
        head = self.heads.get(language)
        if not head:
            return []
        scores = list(head["b"])
        for key, value in features(form, closeness).items():
            row = head["w"].get(key)
            if row:
                for k in range(len(scores)):
                    scores[k] += row[k] * value
        base, base_total = self.base.get(language, (Counter(), 1))
        found = []
        for name, score in zip(head["names"], scores):
            value = 1 / (1 + math.exp(-max(-30, min(30, score))))
            if value >= floor and value / ((base.get(name, 0) + .5) / (base_total + 1)) >= need:
                found.append((value, name))
        return [name for _, name in sorted(found, reverse=True)[:SHOWN]]


# ---- what reaches her and what comes back -------------------------------------------------------------------------
def line(feeling: dict, words=()) -> str:
    """One line of fixed size: at most three feelings, each with how much, and her words."""
    picks = sorted(((value, name) for name, value in feeling.items() if value >= .15), reverse=True)[:3]
    if len(picks) == 1 and picks[0][1] == "calm":
        picks = []
    parts = (["you feel " + ", ".join(f"{'mostly' if value >= .5 else 'somewhat' if value >= .25 else 'a little'} {name}"
                                      for value, name in picks)] if picks else []) \
        + ([f"you keep saying {', '.join(words)}"] if words else [])
    return "(Right now " + ", ".join(parts) + ", and it shows in how you answer.)" if parts else ""


def sides(tags: dict[str, str]) -> str:
    """Her 属性: a name a model knows, with one sentence of what she does. The name alone hardly moves her (DeepSeek: 1 of
    20 for 病娇, 2 for 小绿茶, 1 for 御姐) and the sentence does (7, 8, 13), as well beside the message as written into her
    character (6, 9, 10). What a model will play is its own: Terra stays sweet on the first two whatever it is told."""
    return " ".join(f"(Right now your {name} side is showing: {what})" for name, what in tags.items())


def strength(rows: list[tuple], now: float, half: float = STAYS) -> float:
    """How much a side is wanted, from (when, more or less, closeness): each sighting counts by how close the person is,
    half gone in two weeks, an objection against it."""
    return sum((1 if more else -1) * tier(closeness) * .5 ** ((now - at) / half) for at, more, closeness in rows)


def draw(weights: dict[str, float], count: int, roll: Callable[[], float] = random.random) -> list[str]:
    """Up to `count` names, each with a chance by its weight. How often is the one weight that reaches her: told "mostly
    御姐, a little 病娇" she shows 18 and 16 of 40, reversed 17 and 19; in one sentence leaning 3:1 she shows neither (3, 4);
    in one side at a time, 3:1, she shows 15 and 6."""
    left, drawn = sorted(weights), []
    while left and len(drawn) < count:
        mark = roll() * sum(weights[name] for name in left)
        for name in left:
            mark -= weights[name]
            if mark < 0:
                break
        drawn.append(name)
        left.remove(name)
    return drawn


def overlap(one: str, other: str) -> float:
    """How much of two sentences is the same, by pairs of characters."""
    pairs = [{text[i:i + 2] for i in range(len(text) - 1)} for text in ("".join(one.split()), "".join(other.split()))]
    return len(pairs[0] & pairs[1]) / max(1, len(pairs[0] | pairs[1]))


def short_name(value) -> str:
    """One word to `$side` and to the line: no quotes or brackets, and "big sis type" as big-sis-type."""
    return "-".join(re.sub(r"[\"'“”「」()（）\[\]{}]", "", str(value or "")).split())[:24]


def shaping(text: str) -> dict | None:
    """What her reading of the exchange found: {"name", "more", "what"}, or None."""
    found = (json_in(text) or {}).get("side")
    if not isinstance(found, dict):
        return None
    name = short_name(found.get("name"))
    return {"name": name, "more": str(found.get("more")).lower() != "false",
            "what": " ".join(str(found.get("what") or "").split())[:60]} if name else None


def grown_side(text: str) -> dict | None:
    """The name and sentence her model wrote, on one line and without brackets: it goes inside the line."""
    found = json_in(text) or {}
    name = short_name(found.get("name"))
    what = re.sub(r"[()（）\[\]]", "", " ".join(str(found.get("what") or "").split()))[:80]
    return {"name": name, "what": what} if name and what else None


async def draft(tag: str, ask: Ask) -> str:
    """Her model's first draft of the sentence for a tag given by name alone. Good for some (小绿茶 7 of 20, 三无 17) and
    weak for others (御姐 5, 病娇 2): a person can write a better one."""
    return (await ask([{"role": "user", "content": DRAFT.format(tag=tag)}], 100)).strip()


def json_in(text: str) -> dict | None:
    try:
        found = json.loads(re.search(r"\{.*\}", text or "", re.S).group(0))
    except (AttributeError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def vector(text: str) -> dict[str, float] | None:
    found = json_in(text)
    if found is None:
        return None
    try:
        values = {name: max(0.0, float(found.get(name, 0) or 0)) for name in MOODS}
    except (TypeError, ValueError):
        return None
    total = sum(values.values())
    return {name: value / total for name, value in values.items()} if total else None


def written(text: str) -> dict | None:
    """Her note: {"feel": shares adding up to 1, "mood": -2 to 2}, or None."""
    found = json_in(text)
    if found is None or not isinstance(found.get("feel"), dict):
        return None
    feel = vector(json.dumps(found["feel"]))
    if feel is None:
        return None
    try:
        mood = max(-2, min(2, int(found.get("mood", 0))))
    except (TypeError, ValueError):
        mood = 0
    return {"feel": {name: round(value, 3) for name, value in feel.items() if value}, "mood": mood}


def reading_messages(said: str) -> list[dict]:
    return [{"role": "system", "content": FORM}, {"role": "user", "content": said}]


def vote_messages(prompt: str, before: list[dict], memory: str, said: str) -> list[dict]:
    beside = "\n\n".join(text for text in (BESIDE, memory, ASK) if text)
    return [{"role": "system", "content": prompt}, *before, {"role": "user", "content": f"{beside}\n\n{said}"}]


def shaping_messages(before: list[dict], said: str, reply: str, noted: dict[str, str]) -> list[dict]:
    """No character and no memory: only what was said lately. Her note stays as it was, and her character's own words
    (傲娇, on hers) do not become the name of everything."""
    lines = [f"{'Companion' if item['role'] == 'assistant' else 'Person'}: {item['content'][:LOOK]}" for item in before[-4:]]
    known = "; ".join(f"{name} ({what})" for name, what in noted.items())
    system = f"{SHAPE} Sides noted so far: {known}. If it is one of these, use that name." if known else SHAPE
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n".join([*lines, f"Person: {said[:LOOK]}", f"Companion: {reply[:LOOK]}"])}]


def grow_messages(name: str, wants: list[str], grown: dict[str, str], names: tuple[str, ...] = NAMES) -> list[dict]:
    """What the word means to everyone, with what they said: their words alone lose it (小绿茶 2 of 20, the sentence
    from them; 7 by hand). Her sides are in view, so a new word for one she has joins it, and the list in one call with
    the sentence gives the right side: asked for apart, 小绿茶 ended as 醋缸 and 小恶魔 in two runs of three."""
    held = HELD.format(sides="；".join(f"{name}（{what}）" for name, what in grown.items())) if grown else ""
    return [{"role": "user", "content": GROW.format(name=name, wants="\n".join(f"- {want}" for want in wants), held=held,
                                                    names="、".join(names))}]


def note_messages(prompt: str, told: str, before: list[dict], said: str, reply: str) -> list[dict]:
    """The line stays in view: a note that cannot see it keeps what she was told far less often (41 of 100 against 76)."""
    system = f"{prompt}\n\n{told}" if told else prompt
    return [{"role": "system", "content": system}, *before, {"role": "user", "content": said},
            {"role": "assistant", "content": reply}, {"role": "user", "content": f"{BESIDE}\n\n{NOTE}"}]


# ---- one companion's gut, kept ----------------------------------------------------------------------------------------
def usual(rows: list[tuple]) -> dict | None:
    """What she feels on average across her starter: her normal, for her tone."""
    feels = [row[1] for row in rows if isinstance(row[1], dict)]
    return {name: sum(feel.get(name, 0.0) for feel in feels) / len(feels) for name in MOODS} if feels else None


def read_starter(path: Path) -> tuple[list[tuple], dict]:
    """A companion's starter, a file the host gives: her born lessons and her normal words; none is a blank gut."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        return [], {}
    return [tuple(row) for row in data["rows"]], {language: (Counter(item["words"]), item["n"])
                                                  for language, item in data["words"].items()}


class Gut:
    """One companion's network, marks and tone, in a file of their own, apart from her memory: a wipe does not reach
    them. Lessons are written as they come; the weights are written after a sleep, and lessons since are replayed."""

    def __init__(self, path, starter=None, tags: dict[str, str] | None = None, names: tuple[str, ...] = NAMES):
        self.path, self.starter, self.tags = Path(path), Path(starter) if starter else None, dict(tags or {})
        self.names = tuple(names)
        if not set(self.tags) <= set(self.names):
            raise ValueError(f"Not a side she can have: {', '.join(set(self.tags) - set(self.names))}.")
        self.net, self.marks, self.tone = Net(), Marks(), Tone()
        self.languages: dict[str, str] = {}
        self.sightings: list[tuple] = []  # (subject, when, name, more, closeness, what they want)
        self.grown: dict[str, str] = {}  # the sides that grew: name → sentence
        self.weights: dict[str, float] = {}  # how much of her a side is, where a person set it
        self.held: dict = {"names": [], "since": 0.0}  # the side she is in, and since when
        self.awake, self.sleeping = False, False
        self.last: dict = {}  # what she was last told and last wrote: for `$gut`
        self.waking: asyncio.Future | None = None
        self.lock = threading.RLock()  # (never held through a sleep)
        self.db: sqlite3.Connection | None = None

    def _open(self) -> sqlite3.Connection:
        if self.db is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.path, check_same_thread=False)
            self.db.executescript("""
                pragma journal_mode=wal;
                create table if not exists lessons (id integer primary key, subject text not null, at real not null,
                    language text not null, form text not null, feel text not null, mood integer not null,
                    closeness real not null, words text not null);
                create table if not exists people (subject text primary key, language text not null);
                create table if not exists sightings (id integer primary key, subject text not null, at real not null,
                    name text not null, more integer not null, closeness real not null, what text not null);
                create table if not exists sides (name text primary key, what text not null, own real not null);
                create table if not exists state (key text primary key, value blob not null);""")
        return self.db

    def _get(self, key: str):
        row = self._open().execute("select value from state where key = ?", (key,)).fetchone()
        return json.loads(gzip.decompress(row[0])) if row else None

    def _put(self, key: str, value) -> None:
        with self._open() as db:
            db.execute("insert or replace into state values (?, ?)", (key, gzip.compress(json.dumps(value).encode(), 6)))

    def wake(self) -> None:
        """Everything from the file, or from her starter the first time (seconds: never on the conversation's loop)."""
        rows, base = read_starter(self.starter) if self.starter else ([], {})
        db = self._open()
        lessons = db.execute("select language, form, feel, mood, closeness, words from lessons order by id").fetchall()
        kept = self._get("net")
        net, marks = Net(), Marks(base)
        if kept and rows:
            net.born = [(form, feel if isinstance(feel, dict) else {"calm" if feel == "none" else feel: 1.0}, mood,
                         closeness) for form, feel, mood, closeness in rows]
        if kept:
            net.w, net.b = kept["w"], kept["b"]
        elif rows:
            net.start(rows)
        for number, (language, form, feel, mood, closeness, words) in enumerate(lessons):
            form, feel, words = json.loads(form), json.loads(feel), json.loads(words)
            if kept and number >= kept["lessons"]:
                net.teach(form, feel, mood, closeness)
            else:
                net.lessons.append((form, feel, mood, closeness))
            marks.teach(language, form, mood, closeness, words)
        marks.heads = self._get("marks") or {}
        tone = self._get("tone")
        if not kept and rows:
            self._put("net", {"w": net.w, "b": net.b, "lessons": len(net.lessons)})
        with self.lock:
            self.net, self.marks, self.tone = net, marks, Tone(tone, usual(rows))
            self.languages = dict(db.execute("select subject, language from people").fetchall())
            self.sightings = [(subject, at, name, bool(more), closeness, what) for subject, at, name, more, closeness, what
                              in db.execute("select subject, at, name, more, closeness, what from sightings order by id")]
            kept = db.execute("select name, what, own from sides").fetchall()
            self.grown, self.weights = {name: what for name, what, _ in kept}, {name: own for name, _, own in kept if own}
            self.held = self._get("held") or {"names": [], "since": 0.0}
            self.awake = True

    def feel(self, form: dict | None, vote: dict | None, closeness: float, exchanges: int, language: str) -> dict:
        """What this moment comes to: what the gut says, the balance, and the one line."""
        with self.lock:
            gut = self.net.vector(form, closeness) if form else None
            share = balance(self.net, exchanges)
            if vote:
                self.tone.feed(vote)
            felt = mix(gut, vote, share) if gut and vote else gut or vote
            side = sides(self.shown(closeness))
            if felt is None:
                return {"told": side, "share": share, "felt": None}
            felt = self.tone.lean(felt)
            words = self.marks.speaks(language, form, closeness) if form else []
            return {"told": " ".join(text for text in (line(felt, words), side) if text), "share": share, "felt": felt}

    def wanted(self, name: str, now: float | None = None) -> float:
        rows = [(at, more, closeness) for _, at, seen, more, closeness, _ in self.sightings if seen == name]
        return strength(rows, time.time() if now is None else now)

    def weight(self, name: str, now: float | None = None) -> float:
        """How much of her a side is: what a person set, and what people asked for, half gone in three months. Never quite
        nothing: only objecting takes a side away."""
        rows = [(at, more, closeness) for _, at, seen, more, closeness, _ in self.sightings if seen == name]
        given = self.weights.get(name, GROWS if name in self.tags else 0.0)
        return max(.01, given + strength(rows, time.time() if now is None else now, KEEPS))

    def holding(self, now: float | None = None) -> list[str]:
        """The side she is in. She stays in it for a month at least, then her sides are drawn again by weight, so one of
        three parts to one has three months in four and a side she has just grown waits its turn. Only a side going away
        ends the month sooner. Two in turn, not two at once: at once, one can wipe out the other for as long as it lasts."""
        now = time.time() if now is None else now
        with self.lock:
            hers = {**self.tags, **self.grown}
            kept = [name for name in self.held["names"] if name in hers]
            if not hers or (kept and now - self.held["since"] < HOLD):
                return kept
            self.held = {"names": draw({name: self.weight(name, now) for name in hers}, TAGS), "since": now}
            self._put("held", self.held)
            return self.held["names"]

    def shown(self, closeness: float, now: float | None = None) -> dict[str, str]:
        """The side she is in, for this person: one she was given is for everyone, what grew only for people who can
        teach her: what one person made of her is not for a stranger to meet."""
        return {name: {**self.tags, **self.grown}[name] for name in self.holding(now)
                if name in self.tags or closeness >= TEACH_FROM}

    def objected(self, name: str, now: float | None = None) -> float:
        rows = [(at, True, closeness) for _, at, seen, more, closeness, _ in self.sightings if seen == name and not more]
        return strength(rows, time.time() if now is None else now)

    def noted(self) -> dict[str, str]:
        """The sides she has noted so far, strongest first, so that one thing keeps one name."""
        names = dict.fromkeys([*self.grown, *(row[2] for row in self.sightings)])
        latest = {row[2]: row[5] for row in self.sightings}
        return {name: self.grown.get(name) or latest.get(name, "")
                for name in sorted(names, key=self.wanted, reverse=True)[:NOTED]}

    def sighted(self, subject: str, found: dict, closeness: float, now: float | None = None) -> str | None:
        """One sighting of a person shaping her; the name when it has been wanted enough and has no sentence yet. "More"
        counts once in a day, "less" every time: nobody should have to come back on four days to be heard. Whatever word
        they use, "less" is about what they are meeting, the side she is in: asked to stop, a person says 端着, not 御姐."""
        name, more, now = found["name"], found["more"], time.time() if now is None else now
        if closeness < TEACH_FROM:
            return None
        with self.lock:
            if not more and name not in self.grown and self.grown:
                name = next((held for held in self.holding(now) if held in self.grown), max(self.grown, key=self.wanted))
            if more and any(row[0] == subject and row[2] == name and row[3] and now - row[1] < SPACED
                            for row in self.sightings):
                return None
            self.sightings.append((subject, now, name, more, closeness, found["what"]))
            with self._open() as db:
                db.execute("insert into sightings (subject, at, name, more, closeness, what) values (?, ?, ?, ?, ?, ?)",
                           (subject, now, name, int(more), closeness, found["what"]))
            if name in self.grown:
                if self.objected(name, now) >= GROWS:
                    self.drop_side(name)
                return None
            return name if self.wanted(name, now) >= GROWS else None

    def wants(self, name: str) -> list[str]:
        """What people asked of her under this name, the latest last: what her sentence is made from."""
        return list(dict.fromkeys(row[5] for row in self.sightings if row[2] == name and row[3] and row[5]))[-WANTS:]

    def grow(self, name: str, made: dict) -> None:
        """A side of hers from now on. A sentence saying what one of hers says is that side, whatever her model calls it:
        people say 绿茶, pick-me and ぶりっ子, and told to reuse a name she reworded the sentence and kept the new word."""
        with self.lock:
            like = max(self.grown, key=lambda held: overlap(self.grown[held], made["what"]), default=None)
            new = like if like and overlap(self.grown[like], made["what"]) >= SAME else made["name"]
            if new not in self.names:
                return
            self.sightings = [(row[0], row[1], new if row[2] == name else row[2], *row[3:]) for row in self.sightings]
            self.grown[new] = made["what"]
            with self._open() as db:
                db.execute("update sightings set name = ? where name = ?", (new, name))
                db.execute("insert or replace into sides values (?, ?, ?)", (new, made["what"], self.weights.get(new, 0)))

    def write_side(self, name: str, what: str, weight: float = GROWS) -> None:
        """A person's own sentence for a side, or a new side by hand, and how much of her it is: a person can write a
        better one. By default as much as a side that has just grown. Her next draw takes it in."""
        if name not in self.names:
            raise ValueError(f"Not a side she can have: {name}.")
        with self.lock:
            self.grown[name], self.weights[name] = what, weight
            with self._open() as db:
                db.execute("insert or replace into sides values (?, ?, ?)", (name, what, weight))

    def drop_side(self, name: str) -> bool:
        """Gone, and what taught it with it, so growing it again starts over."""
        with self.lock:
            found = self.grown.pop(name, None) is not None
            self.weights.pop(name, None)
            self.sightings = [row for row in self.sightings if row[2] != name]
            with self._open() as db:
                db.execute("delete from sides where name = ?", (name,))
                db.execute("delete from sightings where name = ?", (name,))
        return found

    def language(self, subject: str, reading: dict | None, said: str) -> str:
        """What she answers in: what the reading names; a message too short to tell keeps the last one."""
        named = str((reading or {}).get("language") or "").lower()
        if named not in LANGUAGES:
            named = self.languages.get(subject) or ("" if reading else language_of(said))
        if named and self.languages.get(subject) != named:
            self.languages[subject] = named
            with self.lock, self._open() as db:
                db.execute("insert or replace into people values (?, ?)", (subject, named))
        return named

    def teach(self, subject: str, language: str, form: dict, note: dict, closeness: float, words: list[str]) -> bool:
        """One lesson; True when it is time to sleep. Strangers teach nothing."""
        if closeness < TEACH_FROM:
            return False
        with self.lock:
            self.net.teach(form, note["feel"], note["mood"], closeness)
            self.marks.teach(language, form, note["mood"], closeness, words)
            count = len(self.net.lessons)
            with self._open() as db:
                db.execute("insert into lessons (subject, at, language, form, feel, mood, closeness, words) values "
                           "(?, ?, ?, ?, ?, ?, ?, ?)", (subject, time.time(), language, json.dumps(form, ensure_ascii=False),
                                                        json.dumps(note["feel"]), note["mood"], closeness,
                                                        json.dumps(words, ensure_ascii=False)))
            self._put("tone", self.tone.v)
        return count in SLEEPS_AT or count % 100 == 0

    def sleep(self) -> None:
        """Her lessons replayed on a copy, so she can answer meanwhile; what she learned during it is replayed after."""
        with self.lock:
            if self.sleeping:
                return
            self.sleeping = True
            twin, before = self.net.copy(), len(self.net.lessons)
            marks = Marks(self.marks.base)
            marks.lessons = list(self.marks.lessons)
        try:
            twin.sleep(seed=before)
            heads = marks.trained(seed=before)
            with self.lock:
                for form, feel, mood, closeness in self.net.lessons[before:]:
                    twin.teach(form, feel, mood, closeness)
                self.net, self.marks.heads = twin, heads
                self._put("net", {"w": twin.w, "b": twin.b, "lessons": len(twin.lessons)})
                self._put("marks", heads)
        finally:
            self.sleeping = False

    def forget(self, subject: str) -> int:
        """A person asks to be forgotten: what they taught goes, and she is built again from what is left. Her tone
        cannot be told apart by person, so it goes back to normal. How many lessons went."""
        with self.lock:
            with self._open() as db:
                gone = db.execute("delete from lessons where subject = ?", (subject,)).rowcount
                db.execute("delete from people where subject = ?", (subject,))
                db.execute("delete from sightings where subject = ?", (subject,))
                db.execute("delete from sides where own = 0 and name not in (select name from sightings where more = 1)")
                db.execute("delete from state")
            self.awake = False
        self.wake()
        self.sleep()
        return gone

    def wipe(self) -> int:
        """All she learned of anyone goes, her sides and her tone with it, and she is as she was born. How many lessons
        went."""
        with self.lock:
            with self._open() as db:
                gone = db.execute("delete from lessons").rowcount
                for table in ("people", "sightings", "sides", "state"):
                    db.execute(f"delete from {table}")
            self.awake = False
        self.wake()
        self.sleep()
        return gone

    def report(self) -> dict:
        return {"lessons": len(self.net.lessons), "starter": round(self.net.share(), 2), "born": len(self.net.born),
                "tone": {name: round(value, 3) for name, value in self.tone.v.items()}, "sides": dict(self.grown),
                "held": self.holding(), "days": max(0, round((self.held["since"] + HOLD - time.time()) / 86400)),
                "weights": {name: round(self.weight(name), 1) for name in self.grown},
                "noted": {name: round(self.wanted(name), 1) for name in self.noted()}, **self.last}

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None


# ---- one turn: her model's calls around a message --------------------------------------------------------------------
class Turn:
    """One message on its way to her answer: her reading starts at once, her vote once her memory has been looked up."""

    def __init__(self, gut: Gut, ask: Ask, prompt: str, said: str, subject: str):
        self.gut, self.ask, self.prompt, self.said, self.subject = gut, ask, prompt, said, subject
        self.began = time.monotonic()
        self.reading = asyncio.ensure_future(ask(reading_messages(said), 300))
        self.told, self.closeness, self.language, self.before = "", 0.0, "", []

    async def form(self, wait: float = 30.0) -> dict | None:
        """Her reading, waiting for it (the note may come long after the answer it was too late for)."""
        try:
            return json_in(await asyncio.wait_for(asyncio.shield(self.reading), wait))
        except Exception:  # (a failed call, or late: there is no form)
            return None

    async def feel(self, before: list[dict], memory: str, closeness: float, exchanges: int) -> str:
        """The line beside the message; "" when nothing came in time, and she answers as she would without a gut."""
        self.before = before
        voting = asyncio.ensure_future(self.ask(vote_messages(self.prompt, before, memory, self.said), 160))
        await asyncio.wait({self.reading, voting}, timeout=max(.1, TIME_LIMIT - (time.monotonic() - self.began)))
        if not voting.done():
            voting.cancel()
        vote = vector(voting.result()) if voting.done() and not voting.cancelled() and not voting.exception() else None
        form = None
        if self.reading.done() and not self.reading.cancelled() and not self.reading.exception():
            form = json_in(self.reading.result())
        self.closeness = closeness
        self.language = self.gut.language(self.subject, form, self.said)
        felt = self.gut.feel(form, vote, closeness, exchanges, self.language)
        self.told = felt["told"]
        speak = f"Reply in {LANGUAGES[self.language]}." if self.language in LANGUAGES else ""
        self.gut.last = {"told": self.told, "share": round(felt["share"], 2), "voted": vote is not None,
                         "read": form is not None}
        return " ".join(text for text in (self.told, speak) if text)

    async def learn(self, reply: str) -> dict | None:
        """After she has answered: her note, with the form a lesson, and whether this person is shaping her. Nothing
        here may hold up a reply: run it beside the conversation. The note, or None when there was no form or she wrote
        none. The two do not depend on each other: a failed reading of the person loses no lesson."""
        note, _ = await asyncio.gather(self._note(self.before, reply), self._shape(self.before, reply),
                                       return_exceptions=True)
        if isinstance(note, BaseException):
            raise note
        return note

    async def _note(self, before: list[dict], reply: str) -> dict | None:
        form = await self.form()
        if form is None:
            return None
        messages = note_messages(self.prompt, self.told, before, self.said, reply)
        note = None
        for _ in range(2):
            note = written(await self.ask(messages, 120))
            if note:
                break
        if note is None:
            return None
        gut, language = self.gut, self.language or language_of(self.said)
        gut.last = {**gut.last, "note": note}
        if gut.teach(self.subject, language, form, note, self.closeness, mine(self.said, reply, language)):
            await asyncio.to_thread(gut.sleep)
        return note

    async def _shape(self, before: list[dict], reply: str) -> None:
        """Are they making something of her? Who she already is, in her character, is no side."""
        gut = self.gut
        if self.closeness < TEACH_FROM:
            return
        found = shaping(await self.ask(shaping_messages(before, self.said, reply, gut.noted()), 120))
        if found is None or found["name"] in self.prompt:
            return
        name = gut.sighted(self.subject, found, self.closeness)
        if name:
            made = grown_side(await self.ask(grow_messages(name, gut.wants(name), gut.grown, gut.names), 160))
            if made:
                gut.grow(name, made)

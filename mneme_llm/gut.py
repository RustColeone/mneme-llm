"""A companion's gut (CMP): what is left of her when her memory is wiped and her model is swapped.

Before she answers, her model reads the message into a small fixed form, with no history, and the gut turns the form
and how close the person is into her feelings: 24 ends on 13 bars (`BARS`), each end a strength of its own, so both sides
of a bar can be strong at once (sweet and scornful is love-hate; defiant and wronged is 嘴硬). Her heart is one network:
who she is with anyone. Each person she talks with has a small table of their own, laid over her heart: how she is with
them. With a person she feels the two blended by how well she knows them. Her model, with her memory in view, gives its
own reading of the moment, and `balance` says how much each counts. The result, leaned on by her slow levels (`Tone`:
lately against usual) and her sensitivity, becomes one soft line of fixed size beside the message, with her word habits,
her 属性 and the language to answer in. Nothing else of the gut reaches her prompt, so it adds no context however long she
lives.

After she has answered, she writes a private note in a call of its own, with the line in view: how this moment moved her
and how she really feels. Nothing is hidden in her reply, so nothing has to be taken out of it, and nothing can reach a
person. The note and the form are a lesson: forms and feelings, never messages (her marks also keep the words she used).
Her heart learns from people at closeness `TEACH_FROM` or more, each lesson by closeness tier, fast while she is young and
slowly once she has grown up (`tau` lessons, grown at five times that); a person's table learns from that person alone,
at a steady pace, from anyone. A talking day without someone fades them back toward her heart. Every so often she
sleeps, settling what the lessons since her last sleep taught; nothing older is replayed, so nothing snaps back.

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
so far as chat messages, without the message she is answering. A host may tune her (`Gut.configure`, `Gut.tune`,
`Gut.set_age`). tests/gut_vectors.json pins the numbers, so a port in another language can check itself against this
file."""

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
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Awaitable, Callable

# Her feelings: (bar, 中文, one end, the other end); an end is (the word her model reads and writes, 中文). The first end
# of a bar is the one that leans away; a one-sided bar has none. Every end is a strength of its own, 0 to 1.
BARS = (("mood", "心情", ("sad", "难过"), ("happy", "开心")),
        ("security", "安心", ("worried", "担心"), ("secure", "踏实")),
        ("composure", "理智", ("hysterical", "慌乱·崩溃"), ("calm", "平静")),
        ("warmth", "亲近", ("scornful", "嫌弃"), ("sweet", "甜蜜")),
        ("manner", "态度", ("stern", "严厉"), ("tender", "温柔")),
        ("temper", "脾气", ("irritable", "易怒"), ("peaceable", "平和")),
        ("stance", "姿态", ("wronged", "委屈"), ("defiant", "不服")),
        ("pride", "骄傲", ("ashamed", "羞愧"), ("proud", "得意")),
        ("playfulness", "举止", ("shy", "害羞"), ("cheeky", "调皮")),
        ("courage", "胆量", ("timid", "胆小"), ("bold", "大胆")),
        ("sociability", "社交", ("withdrawn", "内向"), ("outgoing", "外向")),
        ("jealousy", "吃醋", None, ("jealous", "吃醋")),
        ("aching", "心疼", None, ("aching", "心疼")))
ENDS = tuple(end[0] for bar in BARS for end in bar[2:] if end)
CHINESE = {**{end[0]: end[1] for bar in BARS for end in bar[2:] if end}, **{bar[0]: bar[1] for bar in BARS}}
OLD = ("happy", "calm", "sweet", "tender", "worried", "sad", "jealous")  # the seven of 0.4: lessons written then know only these
QUIET = ("calm", "peaceable", "secure")  # alone, an ordinary moment: no line
SLOW = {"composure": "SAN", "pride": "self-esteem"}  # the two slow levels with names of their own (理智值, 自尊)
GLOSS = {"tender": "tender (gentle)", "withdrawn": "withdrawn (wanting quiet)", "outgoing": "outgoing (wanting to talk)",
         "aching": "aching (hurting for them)", "wronged": "wronged (hurt, treated unfairly)"}
FEELINGS = "; ".join(" or ".join(GLOSS.get(end[0], end[0]) for end in bar[2:] if end) for bar in BARS)
TEACH_FROM = 40  # closeness: "friendly" in mneme-llm's relations; below it a person teaches only how she is with them
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
       "JSON only: one flat object whose keys are one to three feelings from the list and whose values are how strongly, "
       "from 0.1 (a trace) to 1 (fully), and nothing for the rest. Both sides of a pair can be true at once. The "
       "feelings: " + FEELINGS + ".")
NOTE = ('Now write your private note about the reply you just gave. Answer with JSON only: {"mood": N, "feel": {...}}. '
        "N is how this moment changed your mood, a whole number from -2 (clearly worse) to 2 (clearly better), 0 for no "
        f"real change. feel scores all {len(ENDS)} feelings, each from 0 (not at all) to 1 (fully), with these words as "
        "its keys: " + ", ".join(ENDS) + ". In pairs, with what some of them mean: " + FEELINGS + ". Score each one on "
        "its own: both sides of a pair can be true at once. The note is yours alone and the person never sees it. Be "
        "honest: it records how you really feel.")
NOTED_TOKENS = 320  # a note scoring every feeling
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


# ---- the network: her heart, and a table for each person --------------------------------------------------------------
TAU = 150.0  # lessons: how fast her heart grows up; grown at five times this
YOUNG, FLOOR = .7, .04  # how far a lesson moves her heart at birth (x closeness tier), and the share of that left once grown
PERSON = .5  # how far a lesson moves the table of the person it came from: steady, never grown up
COUNTS, MOST = 20.0, .7  # what is different with a person counts half at 20 lessons with them, and never more than MOST
PULL, RETURN = .01, .1  # each talking day without a person fades them by PULL; each lesson with them gives back RETURN of it
AWAKE, PASSES = .25, (.375, .25, .125)  # of what a lesson does: at once, then in her sleep, quieter each pass
BORN_PASSES, BORN_RATE = 4, .15  # her starter: a lean toward her character, which her prompt already gives her
BORN_AS = 150  # lessons her starter counts as in `balance`
BLANK = -3.0  # where every end starts before anything is learned: about .05, a trace
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


def talking_day(at: float, zone: tzinfo | None = None) -> int:
    """The day a moment belongs to, turning at 4 in the morning as mneme-llm's own days do: a number, one a day."""
    moment = datetime.fromtimestamp(at, zone) if zone else datetime.fromtimestamp(at).astimezone()
    return (moment - timedelta(hours=4)).toordinal()


def squash(score: float) -> float:
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, score))))


def target(feel: dict) -> list[float]:
    return [max(0.0, min(1.0, float(feel.get(end, 0.0) or 0.0))) for end in ENDS]


class Table:
    """One row of weights for each thing she can notice, one column for each end, and a bias. Her heart is one; each
    person has one too, holding only what is different with them: it is read on top of her heart as it is now, so
    someone new meets her heart, and what her heart learns later reaches everyone she knows."""

    def __init__(self, kept: dict | None = None, blank: float = BLANK):
        self.w: dict[str, list[float]] = dict((kept or {}).get("w") or {})
        self.b: list[float] = list((kept or {}).get("b") or [blank] * len(ENDS))

    def scores(self, x: dict[str, float]) -> list[float]:
        scores = list(self.b)
        for key, value in x.items():
            row = self.w.get(key)
            if row:
                for k, weight in enumerate(row):
                    scores[k] += weight * value
        return scores

    def strengths(self, x: dict[str, float], nudge: list[float] | None = None) -> list[float]:
        return [squash(score + (nudge[k] if nudge else 0.0)) for k, score in enumerate(self.scores(x))]

    def step(self, x: dict[str, float], wanted: list[float], known: list[int], rate: float,
             under: list[float] | None = None) -> None:
        """Toward her note on the ends it knew. `under`: her heart's scores, for a person's table, which learns what
        her heart does not already say about them."""
        got = [squash(score + (under[k] if under else 0.0)) for k, score in enumerate(self.scores(x))]
        for key in x:
            if key not in self.w:
                self.w[key] = [0.0] * len(ENDS)
        for k in known:
            gradient = rate * (got[k] - wanted[k])
            self.b[k] -= gradient * .25
            for key, value in x.items():
                self.w[key][k] -= gradient * value

    def kept(self) -> dict:
        return {"w": self.w, "b": self.b}


class Net:
    """Her heart and a table for each person she has talked with. Her heart learns from everyone close enough to teach
    her, each lesson by closeness tier, fast while she is young and slowly once grown up. A person's table learns only
    from that person, at a steady pace, from anyone. Young, people change who she is; grown up, mostly how she is with
    them. `nudge` is her nature tuned by hand: added to every end before it is read, never learned away. `locked`: her
    heart learns nothing and does not grow up. `hands`: each person as set by hand (`Gut.tune_person`)."""

    def __init__(self, tau: float = TAU):
        self.tau, self.heart, self.people = tau, Table(), {}
        self.age, self.lessons, self.today, self.born = 0.0, 0, None, 0
        self.nudge = [0.0] * len(ENDS)
        self.locked, self.hands = False, {}
        self.waiting: list[tuple] = []  # lessons since her last sleep

    def learning(self) -> float:
        """How far a lesson moves her heart now, before closeness: YOUNG at birth, falling to FLOOR of it, by `tau`."""
        return YOUNG * (FLOOR + (1 - FLOOR) * math.exp(-self.age / self.tau))

    def person(self, subject: str) -> dict:
        found = self.people.get(subject)
        if found is None:
            found = self.people[subject] = {"table": Table(blank=0.0), "n": 0.0, "fade": 1.0, "day": None}
        return found

    def hand(self, subject: str | None) -> dict:
        return self.hands.get(subject) or {} if subject else {}

    def weight(self, subject: str | None) -> float:
        """How much what is different with a person counts, on top of her heart: more as she comes to know them, at
        most MOST (her nature always has a say), and less for every talking day without them; or as set by hand."""
        found = self.people.get(subject) if subject else None
        if found and self.hand(subject).get("weight") is not None:
            return float(self.hand(subject)["weight"])
        return min(MOST, found["n"] / (found["n"] + COUNTS)) * found["fade"] if found else 0.0

    def vector(self, form: dict, closeness: float, subject: str | None = None) -> dict[str, float]:
        x = features(form, closeness)
        scores = self.heart.scores(x)
        share = self.weight(subject)
        if share:
            scores = [heart + share * theirs for heart, theirs in zip(scores, self.people[subject]["table"].scores(x))]
        theirs = self.hand(subject).get("nudge") or {}
        return {end: squash(score + nudge + float(theirs.get(end, 0.0)))
                for end, score, nudge in zip(ENDS, scores, self.nudge)}

    def day(self, today: int) -> None:
        """A talking day is over when the next one begins: everyone she did not talk with on it fades a little (not a
        person locked by hand)."""
        if self.today is not None and today > self.today:
            for subject, found in self.people.items():
                if found["day"] != self.today and not self.hand(subject).get("locked"):
                    found["fade"] *= 1 - PULL
        self.today = today if self.today is None else max(self.today, today)

    def start(self, rows: list[tuple], known: tuple = ENDS, seed: int = 0) -> None:
        """Born: her starter, a few gentle passes, as a lean."""
        pack = [(features(form, closeness), target(feel), (1 + abs(mood)) / 3 * tier(closeness))
                for form, feel, mood, closeness in rows]
        mask = [k for k, end in enumerate(ENDS) if end in known]
        self.born = BORN_AS if pack else 0
        rng = random.Random(seed)
        for _ in range(BORN_PASSES):
            rng.shuffle(pack)
            for x, wanted, weight in pack:
                self.heart.step(x, wanted, mask, BORN_RATE * weight)

    def teach(self, subject: str, form: dict, feel: dict, mood: int, closeness: float, known: tuple = ENDS,
              today: int | None = None) -> None:
        """One lesson, a quarter of it at once; the rest waits for her sleep. Her heart learns only from people close
        enough; the person's own table from anyone. Locked by hand: her heart learns nothing, and a person locked
        teaches nothing at all."""
        if today is not None:
            self.day(today)
        held = bool(subject) and bool(self.hand(subject).get("locked"))
        found = self.person(subject) if subject and not held else None
        heart = self.learning() * tier(closeness) if closeness >= TEACH_FROM and not self.locked and not held else 0.0
        lesson = (features(form, closeness), target(feel), [k for k, end in enumerate(ENDS) if end in known],
                  (1 + abs(mood)) / 3, heart, found)
        self._learn(lesson, AWAKE)
        self.waiting.append(lesson)
        if found:
            found["n"] += 1
            found["fade"] += (1 - found["fade"]) * RETURN
            found["day"] = self.today
        self.age += 1 if heart else 0
        self.lessons += 1

    def _learn(self, lesson: tuple, share: float) -> None:
        x, wanted, known, weight, heart, found = lesson
        if heart:
            self.heart.step(x, wanted, known, heart * weight * share)
        if found:
            found["table"].step(x, wanted, known, PERSON * weight * share, self.heart.scores(x))

    def sleep(self) -> None:
        """What the lessons since her last sleep taught, settled. Nothing older is replayed: nothing snaps back."""
        for share in PASSES:
            for lesson in self.waiting:
                self._learn(lesson, share)
        self.waiting = []

    def kept(self) -> dict:
        return {"heart": self.heart.kept(), "age": self.age, "lessons": self.lessons, "today": self.today, "born": self.born,
                "people": {subject: {"table": found["table"].kept(), "n": found["n"], "fade": found["fade"],
                                     "day": found["day"]} for subject, found in self.people.items()}}

    def restore(self, kept: dict) -> None:
        self.heart = Table(kept["heart"])
        self.age, self.lessons, self.today, self.born = kept["age"], kept["lessons"], kept["today"], kept.get("born", 0)
        self.people = {subject: {"table": Table(found["table"], 0.0), "n": found["n"], "fade": found["fade"],
                                 "day": found["day"]} for subject, found in kept["people"].items()}


def balance(net: Net, exchanges: int) -> float:
    """How much the gut counts against her head. What she has lived (a starter counts as BORN_AS lessons) raises it,
    memory of this person lowers it: nothing lived, her head decides alone; memory wiped, the gut leads; both full, about
    even."""
    seen = net.age + net.born
    lived, known = seen / (seen + 200), exchanges / (exchanges + 20)
    return lived / (lived + known + .1)


def mix(gut: dict, head: dict, share: float) -> dict[str, float]:
    return {end: share * gut[end] + (1 - share) * head.get(end, 0.0) for end in ENDS}


def sensitive(felt: dict, sensitivity: float) -> dict[str, float]:
    """敏感 or 钝感, a dial from -1 to 1: how hard every moment hits her. 0 leaves her as she is."""
    if not sensitivity:
        return dict(felt)
    gain = 2.0 ** sensitivity
    return {end: 1 - (1 - value) ** gain for end, value in felt.items()}


class Tone:
    """Her slow levels: one for each end, hers and not one person's. `lately` moves halfway to what she feels in about two
    weeks of talking, `usual` in about half a year, and the lean is how far lately is from usual. Fed by her model's
    reading before her line, so a low mood cannot feed itself, and measured against those same readings. It is no
    memory: it survives a wipe, and she cannot say where it came from. The two named ones are bars: SAN (理智值) is calm
    against hysterical, self-esteem (自尊) proud against ashamed."""
    FAST = 1 - .5 ** (1 / (14 * 8))  # at about eight messages a day
    SLOW = 1 - .5 ** (1 / (180 * 8))

    def __init__(self, kept: dict | None = None):
        kept = kept or {}
        self.lately, self.usual = dict(kept.get("lately") or {}), dict(kept.get("usual") or {})
        self.shift = dict(kept.get("shift") or {})  # set by hand (`Gut.tune`): fades at the pace of lately
        self.seen = int(kept.get("seen") or 0)

    def feed(self, vote: dict, sensitivity: float = 0.0) -> None:
        self.seen += 1
        fast, slow = max(1 / self.seen, min(1.0, self.FAST * 2.0 ** sensitivity)), max(1 / self.seen, self.SLOW)
        for end in ENDS:
            value = vote.get(end, 0.0)
            self.lately[end] = self.lately.get(end, value) + fast * (value - self.lately.get(end, value))
            self.usual[end] = self.usual.get(end, value) + slow * (value - self.usual.get(end, value))
        for end in list(self.shift):
            self.shift[end] *= 1 - min(1.0, self.FAST * 2.0 ** sensitivity)
            if abs(self.shift[end]) < 1e-4:
                del self.shift[end]

    def lean(self, felt: dict) -> dict[str, float]:
        return {end: max(0.0, min(1.0, value + self.lately.get(end, 0.0) - self.usual.get(end, 0.0)
                             + self.shift.get(end, 0.0))) for end, value in felt.items()}

    def level(self, bar: str, which: str = "lately") -> float:
        """Where a bar is: the strength of its second end less its first, lately or usually."""
        found = {end: self.lately.get(end, 0.0) + self.shift.get(end, 0.0) for end in ENDS} if which == "lately" \
            else self.usual
        _, _, left, right = next(item for item in BARS if item[0] == bar)
        return found.get(right[0], 0.0) - (found.get(left[0], 0.0) if left else 0.0)

    def said(self) -> list[str]:
        """Her two named slow levels, when lately is far from usual."""
        out = []
        if self.level("composure") - self.level("composure", "usual") <= -LATELY:
            out.append("lately you are easily shaken")
        pride = self.level("pride") - self.level("pride", "usual")
        if pride <= -LATELY:
            out.append("lately you think little of yourself")
        elif pride >= LATELY:
            out.append("lately you think a lot of yourself")
        return out

    def kept(self) -> dict:
        return {"lately": self.lately, "usual": self.usual, "shift": self.shift, "seen": self.seen}


LATELY = .15  # how far lately must be from usual before her line says so


# ---- her marks: the words she uses, more outputs of the same inputs --------------------------------------------------
KANA = re.compile(r"[぀-ヿ]")
CANTONESE = re.compile(r"[嘅咗唔佢哋喺嚟啲冇攰睇講鍾嗰]")
HAN = re.compile(r"[一-鿿]")
RUNS = re.compile(r"[一-鿿぀-ヿ]+|[A-Za-z][A-Za-z']*|[\U0001F300-\U0001FAFF☀-➿]")
CAP, SHOWN = 48, 3  # outputs per language, words in the line
OWN = .8  # a word with this share of its uses with one person is theirs


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
    never lands in English, and a word she uses mostly with one person (OWN of its uses: their name, their in-joke) is
    theirs, in her line only with them."""

    def __init__(self, base: dict | None = None):
        self.base = base or {}  # language → (Counter of replies holding the word, replies)
        self.lessons: list[tuple] = []  # (language, form, mood, closeness, words, who taught it)
        self.heads: dict[str, dict] = {}

    def teach(self, language: str, form: dict, mood: int, closeness: float, words: list[str], subject: str = "") -> None:
        self.lessons.append((language, form, mood, closeness, words, subject))

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
            owners = {}
            for name in names:
                by = Counter(row[5] for row in rows if name in row[4] and row[5])
                if by and by.most_common(1)[0][1] >= OWN * sum(by.values()):
                    owners[name] = by.most_common(1)[0][0]
            heads[language] = {"names": names, "w": w, "b": b, "owners": owners}
        return heads

    def speaks(self, language: str, form: dict, closeness: float, need=2.0, floor=.35, subject: str | None = None
               ) -> list[str]:
        """Her words for this moment, with this person: at least twice her normal rate, likely enough, and not a word
        that belongs to someone else."""
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
        owners = head.get("owners") or {}
        for name, score in zip(head["names"], scores):
            value = 1 / (1 + math.exp(-max(-30, min(30, score))))
            if owners.get(name, subject) != subject:
                continue
            if value >= floor and value / ((base.get(name, 0) + .5) / (base_total + 1)) >= need:
                found.append((value, name))
        return [name for _, name in sorted(found, reverse=True)[:SHOWN]]


# ---- what reaches her and what comes back -------------------------------------------------------------------------
def line(felt: dict, words=(), lately=()) -> str:
    """One line of fixed size: at most three feelings, each with how strongly, her slow levels when they are far from
    usual, and her words. Calm, peaceable or secure alone is an ordinary moment and says nothing."""
    picks = sorted(((value, end) for end, value in felt.items() if value >= SHOWS), reverse=True)[:3]
    if picks and all(end in QUIET for _, end in picks):
        picks = []
    parts = (["you feel " + ", ".join(f"{'very' if value >= .6 else 'quite' if value >= .3 else 'a little'} {end}"
                                      for value, end in picks)] if picks else []) + list(lately) \
        + ([f"you keep saying {', '.join(words)}"] if words else [])
    return "(Right now " + ", ".join(parts) + ", and it shows in how you answer.)" if parts else ""


SHOWS = .15  # how strong a feeling must be to be named


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
    """Her model's reading of a moment: a strength for every end, 0 for the ones it left out; None for nothing usable."""
    found = json_in(text)
    if found is None:
        return None
    if not any(str(name).strip().lower() in ENDS for name in found):  # {"feeling": {...}}: a model's own wrapping
        found = next((value for value in found.values() if isinstance(value, (dict, list))), found)
    if isinstance(found, list):  # [{"feeling": "calm", "strength": 0.7}, ...]
        found = {str(item.get("feeling", item.get("name"))): item.get("strength", item.get("intensity"))
                 for item in found if isinstance(item, dict)}
    values = {}
    for name, value in found.items():
        end = str(name).strip().lower()
        if end in ENDS:
            try:
                values[end] = max(0.0, min(1.0, float(value or 0)))
            except (TypeError, ValueError):
                return None
    return {end: values.get(end, 0.0) for end in ENDS} if any(values.values()) else None


def written(text: str) -> dict | None:
    """Her note: {"feel": the ends she named with how strongly, "mood": -2 to 2}, or None."""
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
    return {"feel": {end: round(value, 3) for end, value in feel.items() if value}, "mood": mood}


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
def read_starter(path: Path) -> tuple[list[tuple], dict, tuple]:
    """A companion's starter, a file the host gives: her born lessons, her normal words, and the ends its notes knew (a
    starter from 0.4 knew seven). No file is a blank gut; a file that cannot be read is an error."""
    if not path.exists():
        return [], {}, ENDS
    try:
        with gzip.open(path, "rt", encoding="utf-8") as file:
            data = json.load(file)
        rows = [(form, feel if isinstance(feel, dict) else {"calm" if feel == "none" else feel: 1.0}, mood, closeness)
                for form, feel, mood, closeness in data["rows"]]
        words = {language: (Counter(item["words"]), item["n"]) for language, item in data["words"].items()}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{path} is not a gut starter: {error}") from error
    return rows, words, tuple(data.get("ends") or OLD)


class Gut:
    """One companion's heart, her tables for the people she knows, her words and her slow levels, in a file of their
    own, apart from her memory: a wipe does not reach them. Lessons are written as they come; the heart is written after
    a sleep, and lessons since are taught again when she wakes. `tau` and `zone` are for a new gut: `configure` changes
    a kept one; `zone` says where her talking days turn (4 in the morning; the machine's zone by default)."""

    def __init__(self, path, starter=None, tags: dict[str, str] | None = None, names: tuple[str, ...] = NAMES,
                 tau: float = TAU, zone: tzinfo | None = None):
        self.path, self.starter, self.tags = Path(path), Path(starter) if starter else None, dict(tags or {})
        self.names, self.zone = tuple(names), zone
        if not set(self.tags) <= set(self.names):
            raise ValueError(f"Not a side she can have: {', '.join(set(self.tags) - set(self.names))}.")
        self.net, self.marks, self.tone = Net(tau), Marks(), Tone()
        self.settings: dict = {"tau": float(tau), "sensitivity": 0.0, "nudge": {}, "locked": False, "people": {},
                               "side": None}
        self.languages: dict[str, str] = {}
        self.sightings: list[tuple] = []  # (subject, when, name, more, closeness, what they want)
        self.grown: dict[str, str] = {}  # the sides that grew: name → sentence
        self.weights: dict[str, float] = {}  # how much of her a side is, where a person set it
        self.held: dict = {"names": [], "since": 0.0}  # the side she is in, and since when
        self.awake, self.sleeping = False, False
        self.last: dict = {}  # what she was last told and last wrote: for `$gut`
        self.waking: asyncio.Future | None = None
        self.lock = threading.RLock()  # (never held through the training of her words)
        self.roll: Callable[[], float] = random.random  # whether a locked side shows this turn
        self.db: sqlite3.Connection | None = None

    def _open(self) -> sqlite3.Connection:
        if self.db is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.path, check_same_thread=False)
            self.db.executescript("""
                pragma journal_mode=wal;
                create table if not exists lessons (id integer primary key, subject text not null, at real not null,
                    language text not null, form text not null, feel text not null, mood integer not null,
                    closeness real not null, words text not null, ends integer not null default 7);
                create table if not exists people (subject text primary key, language text not null);
                create table if not exists sightings (id integer primary key, subject text not null, at real not null,
                    name text not null, more integer not null, closeness real not null, what text not null);
                create table if not exists sides (name text primary key, what text not null, own real not null);
                create table if not exists state (key text primary key, value blob not null);""")
            if "ends" not in {row[1] for row in self.db.execute("pragma table_info(lessons)")}:  # a file from 0.4
                with self.db:
                    self.db.execute("alter table lessons add column ends integer not null default 7")
        return self.db

    def _get(self, key: str):
        row = self._open().execute("select value from state where key = ?", (key,)).fetchone()
        return json.loads(gzip.decompress(row[0])) if row else None

    def _put(self, key: str, value) -> None:
        with self._open() as db:
            db.execute("insert or replace into state values (?, ?)", (key, gzip.compress(json.dumps(value).encode(), 6)))

    def wake(self) -> None:
        """Everything from the file, or from her starter the first time (seconds: never on the conversation's loop). A
        file from 0.4 is lived again under these rules, lesson by lesson; its lessons teach only the seven ends they knew."""
        rows, base, known = read_starter(self.starter) if self.starter else ([], {}, ENDS)
        db = self._open()
        settings = {**self.settings, **(self._get("settings") or {})}
        lessons = db.execute("select subject, at, language, form, feel, mood, closeness, words, ends from lessons "
                             "order by id").fetchall()
        kept = self._get("heart")
        net, marks = Net(settings["tau"]), Marks(base)
        net.nudge = [float(settings["nudge"].get(end, 0.0)) for end in ENDS]
        net.locked, net.hands = bool(settings["locked"]), settings["people"]
        if kept:
            net.restore(kept)
        elif rows:
            net.start(rows, known)
        done = kept["lessons"] if kept else 0
        for number, (subject, at, language, form, feel, mood, closeness, words, ends) in enumerate(lessons):
            form, feel, words = json.loads(form), json.loads(feel), json.loads(words)
            if number >= done:
                net.teach(subject, form, feel, mood, closeness, OLD if ends == len(OLD) else ENDS,
                          talking_day(at, self.zone))
                if not kept and (net.lessons in SLEEPS_AT or net.lessons % 100 == 0):
                    net.sleep()
            if closeness >= TEACH_FROM:
                marks.teach(language, form, mood, closeness, words, subject)
        missed = any(count in SLEEPS_AT or count % 100 == 0 for count in range(done + 1, net.lessons + 1))
        if not kept or missed:
            net.sleep()
            self._put("heart", net.kept())
            with self._open() as db:
                db.execute("delete from state where key in ('net', 'tone')")  # 0.4's, lived again above
        marks.heads = self._get("marks") or {}
        with self.lock:
            self.net, self.marks, self.tone, self.settings = net, marks, Tone(self._get("feelings")), settings
            self.languages = dict(db.execute("select subject, language from people").fetchall())
            self.sightings = [(subject, at, name, bool(more), closeness, what) for subject, at, name, more, closeness, what
                              in db.execute("select subject, at, name, more, closeness, what from sightings order by id")]
            kept = db.execute("select name, what, own from sides").fetchall()
            self.grown, self.weights = {name: what for name, what, _ in kept}, {name: own for name, _, own in kept if own}
            self.held = self._get("held") or {"names": [], "since": 0.0}
            self.awake = True

    def feel(self, form: dict | None, vote: dict | None, closeness: float, exchanges: int, language: str,
             subject: str | None = None) -> dict:
        """What this moment comes to, with this person: what the gut says, the balance, and the one line."""
        with self.lock:
            gut = self.net.vector(form, closeness, subject) if form else None
            share = balance(self.net, exchanges)
            if vote:
                self.tone.feed(vote, self.settings["sensitivity"])
            felt = mix(gut, vote, share) if gut and vote else gut or vote
            side = sides(self.shown(closeness))
            fixed = self.settings["side"]
            if side and fixed and self.roll() >= fixed["often"]:
                side = ""  # a side locked by hand shows in this share of turns: how often is what reaches her
            if felt is None:
                return {"told": side, "share": share, "felt": None}
            felt = sensitive(self.tone.lean(felt), self.settings["sensitivity"])
            words = self.marks.speaks(language, form, closeness, subject=subject) if form else []
            told = line(felt, words, self.tone.said())
            return {"told": " ".join(text for text in (told, side) if text), "share": share, "felt": felt}

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
            fixed = self.settings["side"]
            if fixed and fixed["name"] in hers:
                return [fixed["name"]]  # locked by hand: no month ends it
            kept = [name for name in self.held["names"] if name in hers]
            if not hers or (kept and now - self.held["since"] < HOLD):
                return kept
            self.held = {"names": draw({name: self.weight(name, now) for name in hers}, TAGS), "since": now}
            self._put("held", self.held)
            return self.held["names"]

    def shown(self, closeness: float, now: float | None = None) -> dict[str, str]:
        """The side she is in, for this person: one she was given is for everyone, what grew only for people who can
        teach her: what one person made of her is not for a stranger to meet. One locked by hand is for everyone."""
        fixed = (self.settings["side"] or {}).get("name")
        return {name: {**self.tags, **self.grown}[name] for name in self.holding(now)
                if name in self.tags or name == fixed or closeness >= TEACH_FROM}

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
            if not more and name not in self.grown and name not in self.tags:
                held = self.holding(now)
                name = held[0] if held else max(self.grown, key=self.wanted) if self.grown else name
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
        """Gone, and what taught it with it, so growing it again starts over. Locked, it is unlocked."""
        with self.lock:
            if (self.settings["side"] or {}).get("name") == name:
                self.settings["side"] = None
                self._put("settings", self.settings)
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

    def teach(self, subject: str, language: str, form: dict, note: dict, closeness: float, words: list[str],
              at: float | None = None) -> bool:
        """One lesson; True when it is time to sleep. Anyone teaches how she is with them; only people close enough
        teach her heart and her words."""
        at = time.time() if at is None else at
        with self.lock:
            self.net.teach(subject, form, note["feel"], note["mood"], closeness, ENDS, talking_day(at, self.zone))
            if closeness >= TEACH_FROM:
                self.marks.teach(language, form, note["mood"], closeness, words, subject)
            with self._open() as db:
                db.execute("insert into lessons (subject, at, language, form, feel, mood, closeness, words, ends) values "
                           "(?, ?, ?, ?, ?, ?, ?, ?, ?)", (subject, at, language, json.dumps(form, ensure_ascii=False),
                                                           json.dumps(note["feel"]), note["mood"], closeness,
                                                           json.dumps(words, ensure_ascii=False), len(ENDS)))
            self._put("feelings", self.tone.kept())
            count = self.net.lessons
        return count in SLEEPS_AT or count % 100 == 0

    def sleep(self) -> None:
        """What the lessons since her last sleep taught, settled and written; then her words trained again on a copy,
        so she can answer meanwhile."""
        with self.lock:
            if self.sleeping:
                return
            self.sleeping = True
            self.net.sleep()
            self._put("heart", self.net.kept())
            marks = Marks(self.marks.base)
            marks.lessons = list(self.marks.lessons)
        try:
            heads = marks.trained(seed=len(marks.lessons))
            with self.lock:
                self.marks.heads = heads
                self._put("marks", heads)
        finally:
            self.sleeping = False

    def _settle(self) -> None:
        """Her heart written now, out of turn: what waits for her sleep is settled first, so nothing is taught twice."""
        self.net.sleep()
        self._put("heart", self.net.kept())

    def forget(self, subject: str) -> int:
        """A person asks to be forgotten: how she is with them goes, their name leaves the lessons they taught, and so do
        the sides only they wanted. What they did to her heart stays: what is done is done. How many lessons lost
        their name."""
        with self.lock:
            self._settle()
            self.net.people.pop(subject, None)
            if self.settings["people"].pop(subject, None) is not None:
                self._put("settings", self.settings)
            self.languages.pop(subject, None)
            self.sightings = [row for row in self.sightings if row[0] != subject]
            with self._open() as db:
                gone = db.execute("update lessons set subject = '' where subject = ?", (subject,)).rowcount
                db.execute("delete from people where subject = ?", (subject,))
                db.execute("delete from sightings where subject = ?", (subject,))
                db.execute("delete from sides where own = 0 and name not in (select name from sightings where more = 1)")
                kept = db.execute("select name, what, own from sides").fetchall()
            self.grown, self.weights = {name: what for name, what, _ in kept}, {name: own for name, _, own in kept if own}
            self._put("heart", self.net.kept())
        return gone

    def wipe(self) -> int:
        """All she learned of anyone goes, her sides and her slow levels with it, and she is as she was born. Her
        settings stay. How many lessons went."""
        with self.lock:
            with self._open() as db:
                gone = db.execute("delete from lessons").rowcount
                for table in ("people", "sightings", "sides"):
                    db.execute(f"delete from {table}")
                db.execute("delete from state where key != 'settings'")
            self.awake = False
        self.wake()
        return gone

    def configure(self, tau: float | None = None, sensitivity: float | None = None,
                  locked: bool | None = None) -> dict:
        """Her settings: how fast her heart grows up (`tau`, in lessons; grown at five times it), 敏感 or 钝感
        (`sensitivity`, -1 to 1, 0 as she is), and her heart locked (`locked`: it learns nothing and does not grow up
        until unlocked; how she is with each person still learns, unless locked too). The settings, as they are now."""
        if locked is not None and not isinstance(locked, bool):
            raise ValueError("locked is true or false")
        with self.lock:
            if locked is not None and locked != self.settings["locked"]:
                self._settle()  # what waits for her sleep is taught as things were
                self.settings["locked"] = self.net.locked = locked
            if tau is not None:
                if isinstance(tau, bool) or not isinstance(tau, (int, float)) or not 0 < tau < math.inf:
                    raise ValueError("tau is a number of lessons above 0")
                self.settings["tau"] = self.net.tau = float(tau)
            if sensitivity is not None:
                if isinstance(sensitivity, bool) or not isinstance(sensitivity, (int, float)) or not -1 <= sensitivity <= 1:
                    raise ValueError("sensitivity is from -1 (钝感) to 1 (敏感)")
                self.settings["sensitivity"] = float(sensitivity)
            self._put("settings", self.settings)
            return json.loads(json.dumps(self.settings))

    def set_age(self, lessons: float = 0) -> None:
        """How grown up her heart is, in lessons: 0 makes her young again, forgetting nothing."""
        if isinstance(lessons, bool) or not isinstance(lessons, (int, float)) or not 0 <= lessons < math.inf:
            raise ValueError("an age is a number of lessons, 0 or more")
        with self.lock:
            self.net.sleep()
            self.net.age = float(lessons)
            self._put("heart", self.net.kept())

    def tune(self, end: str, now: float | None = None, nature: float | None = None) -> None:
        """One end by hand. `now`, -1 to 1: how much more (or less) of it she feels lately than usual; it fades as she
        lives, at the pace of her slow levels. `nature`, -3 to 3: a nudge to who she is, added before the end is read;
        learning never takes it away, 0 removes it."""
        if end not in ENDS:
            raise ValueError(f"Not an end of hers: {end}. Hers: {', '.join(ENDS)}.")
        for value, low, high in ((now, -1, 1), (nature, -3, 3)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not low <= value <= high):
                raise ValueError(f"{value} is not from {low} to {high}")
        with self.lock:
            if now is not None:
                self.tone.shift[end] = float(now)
                self._put("feelings", self.tone.kept())
            if nature is not None:
                self.settings["nudge"][end] = float(nature)
                if not nature:
                    self.settings["nudge"].pop(end)
                self.net.nudge = [float(self.settings["nudge"].get(name, 0.0)) for name in ENDS]
                self._put("settings", self.settings)

    def tune_person(self, subject: str, end: str | None = None, nature: float | None = None,
                    weight: float | str | None = None, locked: bool | None = None) -> dict:
        """How she is with one person, by hand. `end` and `nature` (-3 to 3): a nudge to that end with them alone, on
        top of her own nature; 0 removes it. `weight` (0 to 1): how much what is different with them counts on top of
        her heart, in place of what she has learned (more as she knows them, at most 0.7, fading without them);
        "learned" goes back to that. `locked`: what they say teaches nothing, neither how she is with them nor her
        heart, and they do not fade; who she is at heart, as others shape it, still reaches them. What is set for them,
        as it is now."""
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("a person is a subject, such as discord:42")
        if (end is None) != (nature is None):
            raise ValueError("a nudge needs both an end and its nature")
        if end is not None and end not in ENDS:
            raise ValueError(f"Not an end of hers: {end}. Hers: {', '.join(ENDS)}.")
        if nature is not None and (isinstance(nature, bool) or not isinstance(nature, (int, float))
                                   or not -3 <= nature <= 3):
            raise ValueError(f"{nature} is not from -3 to 3")
        if weight is not None and weight != "learned" and (isinstance(weight, bool) or
                                                           not isinstance(weight, (int, float)) or not 0 <= weight <= 1):
            raise ValueError('a weight is from 0 to 1, or "learned"')
        if locked is not None and not isinstance(locked, bool):
            raise ValueError("locked is true or false")
        with self.lock:
            if locked is not None:
                self._settle()  # what waits for her sleep is taught as things were
            hand = dict(self.settings["people"].get(subject) or {})
            if nature is not None:
                nudge = {**hand.get("nudge", {}), end: float(nature)}
                hand["nudge"] = {name: value for name, value in nudge.items() if value}
            if weight is not None:
                hand["weight"] = None if weight == "learned" else float(weight)
            if locked is not None:
                hand["locked"] = locked
            hand = {key: value for key, value in hand.items() if value is not None and value is not False and value != {}}
            if hand:
                self.settings["people"][subject] = hand
            else:
                self.settings["people"].pop(subject, None)
            self.net.hands = self.settings["people"]
            self._put("settings", self.settings)
            return json.loads(json.dumps(hand))

    def lock_side(self, name: str, often: float = 1.0, what: str | None = None) -> None:
        """She is in this side from now on, whatever is drawn and however long, and it shows in `often` of her turns
        (0 to 1: how often is what reaches her; 1 is every turn). For everyone, not only people close enough. `what`:
        its sentence, a new side by hand or a better one; a side she has needs none. See `unlock_side`."""
        if name not in self.names:
            raise ValueError(f"Not a side she can have: {name}.")
        if isinstance(often, bool) or not isinstance(often, (int, float)) or not 0 <= often <= 1:
            raise ValueError("often is from 0 to 1")
        with self.lock:
            if what:
                self.grown[name] = " ".join(str(what).split())
                with self._open() as db:
                    db.execute("insert or replace into sides values (?, ?, ?)",
                               (name, self.grown[name], self.weights.get(name, 0)))
            if name not in self.tags and name not in self.grown:
                raise ValueError(f"{name} is not one of her sides yet: give it a sentence (what she does)")
            self.settings["side"] = {"name": name, "often": float(often)}
            self._put("settings", self.settings)

    def unlock_side(self) -> None:
        """Her sides are drawn by weight again; she stays in the one she was locked in for a month first."""
        with self.lock:
            fixed = self.settings["side"]
            if fixed is None:
                return
            self.settings["side"] = None
            self._put("settings", self.settings)
            self.held = {"names": [fixed["name"]], "since": time.time()}
            self._put("held", self.held)

    def report(self) -> dict:
        with self.lock:
            net, tone = self.net, self.tone
            return {"lessons": net.lessons, "age": round(net.age), "tau": net.tau,
                    "grown": round(1 - math.exp(-net.age / net.tau), 2), "learning": round(net.learning() / YOUNG, 3),
                    "sensitivity": self.settings["sensitivity"], "nudge": dict(self.settings["nudge"]),
                    "locked": self.settings["locked"], "hands": json.loads(json.dumps(self.settings["people"])),
                    "side": dict(self.settings["side"]) if self.settings["side"] else None,
                    "people": {subject: {"lessons": round(found["n"]), "weight": round(net.weight(subject), 2)}
                               for subject, found in net.people.items()},
                    "lately": {end: round(tone.lately.get(end, 0.0) + tone.shift.get(end, 0.0), 3) for end in ENDS},
                    "usual": {end: round(tone.usual.get(end, 0.0), 3) for end in ENDS},
                    "SAN": round(tone.level("composure"), 3), "self-esteem": round(tone.level("pride"), 3),
                    "sides": dict(self.grown), "held": self.holding(),
                    "days": max(0, round((self.held["since"] + HOLD - time.time()) / 86400)),
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
        felt = self.gut.feel(form, vote, closeness, exchanges, self.language, self.subject)
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
            note = written(await self.ask(messages, NOTED_TOKENS))
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

# mneme-llm

Memory and mood for AI companions, kept in **one SQLite file** that any model and any project can use.

Switch the model behind your companion (DeepSeek today, Claude or GPT tomorrow, a local model next year) and
point it at the same file: she still knows the person's cat is called 年糕, that the exam moved to Friday, and
that she was worried about them last night. Nothing in the file depends on which model wrote it.

- **Pure Python, no dependencies.** Python 3.10+, stdlib only. `jieba` is used if you have it.
- **Any LLM.** Tool definitions for OpenAI-style APIs (DeepSeek, Qwen, vLLM, Ollama…), the OpenAI responses
  API, Claude and Gemini, an MCP server, or just a text block for the system prompt.
- **Portable.** Export a space to JSON, import it anywhere; the [file format](https://github.com/RustColeone/mneme-llm/blob/main/docs/FORMAT.md) is documented
  so programs in other languages can read and write it too.

```
            your app, any model
   ┌─────────────┼──────────────────┐
 Python API    tools (any API)    MCP server         CLI (inspect, fix, move)
   └─────────────┼──────────────────┘
             mneme-llm ── one .db file
   ┌─────────────┼─────────────────────────────┐
 memory          mood                 decisions (three tiers, falling through)
 notes + keys    value + feelings     1. GPT-6 Luna Decisions API   fast, cheap
 human dates     decay, guardrails    2. micro model (optional)     local, learns from 1
 evidence recall told once            3. your own chat model        always there
 profile card    timeline
```

## Quick start

```python
from mneme_llm import Mneme

m = Mneme("companion.db", space="whale_chan", lang="zh", name="大肥鱼")

# keep notes (usually your model does this through the tools, below)
m.remember("discord:42", "养了一只叫年糕的猫", kind="fact", key="pet.name", importance=4)
m.remember("discord:42", "数学考试没考好，觉得自己很笨", kind="episode", importance=3)

# each turn: add what she remembers (and how she feels, once per change) to the system prompt
system = PERSONA + "\n\n" + m.prompt("discord:42", query=user_message, name="小明")

# after each exchange: judge her mood (and teach the micro model)
m.after("discord:42", [("小明", user_message), ("大肥鱼", reply)], user="小明")
```

`m.prompt(...)` gives something like:

```
你记得的关于小明的事（日期是相对今天说的）：
- 养了一只叫年糕的猫
- [昨天] 数学考试没考好，觉得自己很笨

（你此刻的心情 72/100（开心）；心疼 32。刚才心里那一下：小明说「今天考试又没考好……」，心疼）
```

In async code use `await m.aafter(...)`; every judging call has an async form (`adecide`, `ajudge`,
`acapture`, `areflect`).

Install: `pip install git+https://github.com/RustColeone/mneme-llm` (or `pip install -e .` in a clone,
or copy the `mneme_llm/` folder into your project). `pip install "mneme-llm[jieba] @ git+…"` adds jieba.

## Concepts

**Space and subject.** A *space* is whose memory it is: one app or character (`whale_chan`). A *subject* is
who a note is about (`discord:42`, `wechat:wxid_…`). One file can hold many spaces; ids are yours to choose.

**Notes** are one sentence each. The *kind* says how a note ages:

| kind | for | fades? |
|---|---|---|
| `fact` | lasting truths: "lives in Hangzhou" | never |
| `preference` | likes and dislikes | never |
| `episode` | something that happened | halves every 30 days unless recalled again |
| `plan` | something coming up | like an episode |
| `reflection` | the companion's own impression | like an episode |

*Importance* runs 1 (trivial) to 5 (core). Importance 5 notes are always in context; lasting notes of 4+
fill spare room when nothing matches.

**Keys** name what a note is about, never its value: `user.city`, `exam.math.date`, `pet.name`. A newer note
with the same key replaces the old one and the old one stays in the history (`history()`, `mneme-llm history`), so
"moved from Shanghai to Hangzhou" is remembered as a change, not as two contradicting facts.

**Recall** scores a note by *evidence* (the query's terms it shares, each weighted by how rare it is among this
person's notes; Chinese is matched by overlapping character pairs, so no word list is needed) times freshness,
importance and feeling. It then fills a budget (6 notes, 800 characters by default): pinned notes, then the
best matches, then important facts, then the newest episode. `recall(...).explain()` says what was chosen and
what was skipped and why, and every recall is logged (`recalls()`).

**Dates** are shown the way people say them, *today*, *3 days ago*, *in 2 days*, *去年 09-17*, *明天*, so the
model never has to do date arithmetic. A plan's `happened_at` is the day it happens.

**Quota.** Notes a model writes on its own (`source="auto"`, which the tools use) are capped at 8 per person
per day unless importance is 4+, so a chatty day doesn't bury the important things.

**Mood** is one value (0–100, baseline 70) and seven feelings (开心 happy, 踏实 at ease, 甜蜜 sweet, 心疼 aching
for them, 担心 worried, 难过 sad, 吃醋 jealous) per person. The value drifts back to baseline (half-life 3 h);
feelings fade (half-life 90 min). Decay is computed when read, so nothing needs to tick.

After each exchange the decision chain answers two questions: how her mood moved (−2…+2) and her strongest
feeling. The expected values move the state, so an unsure judge moves it little. The guardrails come from
[dsh-feiyu-mood](https://github.com/Yuuyuko-uu):

- her mood only drops from aching for them, worry or sadness, never from being cross with them;
- exchanges that change nothing leave no record;
- a judgement under the confidence threshold (0.6) is recorded but never told to her;
- the news is told once (`news()`), then stays in the conversation history like anything else she heard;
- who started the exchange changes the question: someone talking to her (`user`), her reaching out on her own
  (`speak-up`), or her doing a scheduled task (`duty`); `runtime` turns are skipped.

`MoodSettings(baseline=75, floor=30, tell="mood", emotions=...)` changes any of this.

## The decision chain

Small judgements (is this worth remembering? which feeling? how much better?) don't need a chat model.
mneme-llm asks them as typed questions, `Predicate`, `Choice` or `Score`, and the first tier that can answer
does:

1. **Luna**: OpenAI's [Decisions API](https://platform.openai.com/docs) (`gpt-6-luna`). It answers in about
   0.2–0.4 s for $0.10 per million input tokens, with no output charge. A mood judgement costs about $0.00004.
   It is used when `OPENAI_API_KEY` is set (or a key is passed) and skipped otherwise.
2. **Micro** (optional, removable): a tiny local model per question, trained online on Luna's answers to
   *your* conversations. It guesses before each lesson, and only answers once it has seen 200 lessons and
   agrees with Luna at least 85% of the time, and then only when it is 80% sure. It has no dependencies; the
   weights live in the same file. Turn it off with `Mneme(..., micro=False)` or delete `mneme_llm/decide/micro.py`.
3. **Prompt**: your own chat model, asked for a small JSON verdict, the way dsh-feiyu-mood judges. It is slower
   and costs output tokens, but it is always there and can give a reason in words.

A tier that fails (no key, network down) or abstains passes the question on. `m.decider.report()` shows what
each tier answered, abstained on or failed, and what Luna has cost.

```python
from mneme_llm import Chain, Luna, Predicate, Prompt
from mneme_llm.decide.micro import Micro

chain = Chain(Luna(), Micro(m.store), Prompt(my_complete))
answers = chain.decide(text, [Predicate("urgent", "The user needs an answer right now.")])
answers["urgent"].probability, answers["urgent"].by      # 0.93, "luna"
```

The chain is useful beyond mood: gating, routing, "should she speak up now?".

## Using it from any model

**Tools.** Give the model `remember`, `recall`, `forget` and `mood`, in its API's format, and run its calls
through one dispatcher:

```python
from mneme_llm.tools import Toolbox, specs

tools = specs("openai")          # or "responses", "anthropic", "gemini", "mcp"; prefix="memory_" to namespace
box = Toolbox(m, subject="discord:42")
reply_text = box.call(call.name, call.arguments)    # arguments as a dict or a JSON string
```

The host decides whose memory is written; the model never picks the subject. Mistakes come back as text the
model can read ("Error: …"), never as exceptions.

**No tools?** Use `m.prompt(...)` for context and `await acapture(m, subject, exchange)` after each exchange.
Capture asks the chain a cheap yes/no first and only asks your model to write notes when there is something
worth keeping. `await areflect(m, subject)` (nightly, say) rewrites the short profile card shown above the
notes.

**MCP.** Any MCP client can use the same file:

```json
{"mcpServers": {"mneme-llm": {"command": "python3", "args": ["-m", "mneme_llm", "--db", "/path/companion.db",
  "--space", "whale_chan", "mcp", "--subject", "discord:42"]}}}
```

Without `--subject`, each tool call names its subject.

## The command line

```sh
mneme-llm --db companion.db --space whale_chan notes discord:42
mneme-llm recall discord:42 "考试" --explain           # what would be recalled, and why not the rest
mneme-llm history discord:42 user.city
mneme-llm remember discord:42 "对芒果过敏" --kind fact --key user.allergy --importance 5
mneme-llm forget discord:42 --key user.allergy
mneme-llm mood discord:42                               # value, feelings, the last changes and who judged them
mneme-llm export --out backup.json && mneme-llm --db other.db import backup.json --into whale_chan
mneme-llm tools --style anthropic                       # print tool definitions
mneme-llm erase discord:42 --yes                        # "forget me": everything about them, for good
```

`MNEME_LLM_DB`, `MNEME_LLM_SPACE` and `MNEME_LLM_LANG` set the defaults.

## Notes on privacy

Everything stays in the one file. `forget` hides a note (the history keeps it, so a mistaken forget can be
undone in SQL), `purge()` erases hidden and replaced notes for good, and `erase(subject)` removes everything
about a person. Only the decision chain sends text anywhere: Luna gets the exchange being judged, and your own
model gets what you give it.

## Tests

```sh
python3 -m unittest discover -s tests -t .
```

## Credits

The memory and mood designs borrow from Yuuyuko-uu's
[dsh-fish-memory](https://github.com/Yuuyuko-uu) (evidence-ranked recall, freshness, human dates, keys, quota)
and dsh-feiyu-mood (decay, guardrails, source-aware judging, telling once), and from
[Honcho](https://github.com/plastic-labs/honcho) (the profile card).

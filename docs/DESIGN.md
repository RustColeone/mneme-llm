# How mneme-llm works

**English** · [简体中文](DESIGN.zh-CN.md)

A walkthrough for anyone reviewing, maintaining or porting mneme-llm: what each part does, the rules it keeps, the
numbers it uses and why, how it fails, and what it does not do yet. It describes version 0.3.0; where it names a
constant, the constant is in the code under the same name.

Read it in order the first time. Sections 2 and 3 give the whole picture; sections 4–11 go module by module; the
rest covers safety, failure, cost, tests, the decisions behind the design, and its known limits.

## 1. What it is for

A companion that talks with people needs to remember them (facts, plans, what happened, how they felt, and what
was actually said), to know who each of them is to it, and to have a mood of its own toward each of them. Most implementations keep both inside one model's conversation, or in a
format tied to one framework, so changing the model loses them. mneme-llm keeps them in one SQLite file with a
documented format, and does every judgement it needs through tiers that work with any model, so that:

1. the same file gives the same facts to any model, in any project;
2. nothing breaks when a provider is missing or down;
3. the parts that cost money are small, measured, and optional.

## 2. The shape

```
 ┌──────────────────────────── host application (any model) ────────────────────────────┐
 │  aprompt() before a reply            aobserve() after it           tools / MCP / CLI    │
 └────────────┬───────────────────────────────┬──────────────────────────────┬──────────┘
              │                               │                              │
        Mneme (__init__.py): one space; builds the tiers, makes the model calls     tools.py, mcp.py, cli.py
              │                               │      config.py: the companion's config, kept in the file
   ┌──────────┴─────────────┐      ┌──────────┴───────────┐
   │ Memory (memory.py)     │      │ Mood (mood.py)       │      capture.py: the writers' prompts and replies
   │ notes, recall          │      │ value + feelings     │      exchange.py: an exchange as judges read it
   │ Episodes (episodes.py) │      │                      │      relations.py: who each person is to it; aliases.py: their name for it
   │ the words: look, search│      │                      │      people.py: one person under several subjects
   └──────┬─────────────────┘      └──────────┬───────────┘
          │                                   │
          │ meaning/ (3 tiers)                │ decide/ (3 tiers)
          │ embeddings → centroids → unify    │ Luna → micro → your model
   ┌──────┴───────────────────────────────────┴───────────┐
   │ Store (store.py): one SQLite file, schema 1           │   providers.py, text.py, dates.py, i18n.py, prompts.py
   └───────────────────────────────────────────────────────┘
```

| file | lines | role |
|---|---|---|
| `__init__.py` | 485 | `Mneme`, the facade: builds the tiers; `aprompt`, `alook`, `aobserve`, `acapture`, `areflect`, `relate`, `alias`, `link`, `erase`, export/import |
| `store.py` | 291 | the SQLite file alone: schema, additive migrations, locking, transactions |
| `memory.py` | 776 | notes: the rules of writing, the term index, recall ranking, rendering, profile card, recall log, notes' export/import |
| `episodes.py` | 618 | what was said, word for word: keeping exchanges, their term index and vectors, retention and rehearsal, the look and the search, rendering, their export/import |
| `mood.py` | 411 | mood state, decay, judging questions, guardrails, telling once, moods' export/import |
| `config.py` | 547 | a companion's config: the defaults, checking each key, TOML in and out, the stored copy per space |
| `prompts.py` | 59 | every instruction given to a model, by name (the built-in defaults) |
| `relations.py` | 230 | who each person is to the companion: roles, closeness that grows and fades, the mood weight, the prompt line |
| `aliases.py` | 94 | what each person calls the companion: one short line each, the prompt line |
| `people.py` | 95 | one person under several subjects (their accounts): links one step deep, and who a subject stands for |
| `capture.py` | 69 | what the note writer and the profile writer are asked, and reading their replies |
| `exchange.py` | 47 | an exchange as lines `(who, said)` or one text, and framed for a judge (who is who, who started it) |
| `providers.py` | 92 | what every tier needs to call out: sync or async calls, posting JSON, JSON in replies, resting |
| `decide/__init__.py` | 221 | question types, `Answer`, `Chain` (fall-through and learning) |
| `decide/luna.py` | 82 | decision tier 1: OpenAI's Decisions API |
| `decide/micro.py` | 188 | decision tier 2 (removable): per-question local models learned from tier 1 |
| `decide/prompt.py` | 74 | decision tier 3: the host's chat model, asked for JSON |
| `meaning/__init__.py` | 206 | the meaning tiers together (`find`) and vector storage |
| `meaning/embedders.py` | 69 | meaning tier 1: the embedding providers |
| `meaning/calibrate.py` | 147 | each embedding model's floor: measured on a bundled set, refined by the file's own notes |
| `meaning/vectors.py` | 30 | vectors as the file keeps them, and their arithmetic |
| `meaning/ledger.py` | 122 | the account of what notes taught the word centroids (not removable) |
| `meaning/micro.py` | 69 | meaning tier 2 (removable): word centroids, placing a query among the notes |
| `meaning/unify.py` | 174 | meaning tier 3 (removable): glosses and query translation by the host's chat model |
| `text.py` | 194 | tokenization, script detection, cleaning and clipping text |
| `dates.py` | 109 | human dates, dates found in sentences, times in seconds |
| `i18n.py` | 219 | every word and sentence shown to a person or a model, in English and Chinese |
| `tools.py` | 249 | tool definitions for five API styles and the dispatcher |
| `mcp.py` | 82 | an MCP server over stdio |
| `cli.py` | 305 | the `mneme-llm` command |

**Layers.** Dependencies point one way. `text`, `dates`, `i18n`, `prompts`, `providers`, `exchange`, `store`
and `meaning/vectors` import nothing above them; `decide` and `meaning` build on `providers`; `memory` uses `meaning`
and `store`; `episodes` uses `meaning`, `store`, `exchange`, `text` and `dates`; `mood` uses `decide`'s types; `relations` uses `store`, `dates` and `i18n` (the mood knows nothing of
it: `Mneme` hands the mood each person's weight); `config` uses `mood`, `relations`, `prompts`, `i18n` and `store`,
and `Mneme` builds every part from it; `capture` uses `memory`'s rules of writing; `Mneme` wires them together and
makes the calls to models; `tools`, `mcp` and `cli` sit on `Mneme` (the CLI's `micro` command reads the micro
models through `decide/micro` directly, as nothing else needs them). Each kind of row has one owner that writes it:
notes, profile cards and the recall log are `memory`'s, exchanges with their index, vectors and spread
`episodes`'s, moods and timelines `mood`'s, relationships `relations`'s,
aliases `aliases`'s, the config `config`'s,
the micro models `decide/micro`'s, the centroids `meaning/ledger`'s; vectors are stored by `meaning` and, with what they taught,
taken back by `meaning/ledger`; each `meta` key belongs to the module that names it (the schema version to `store`,
the tokenizer to `memory`, the centroid counts to the ledger, each embedder's floor to `meaning/calibrate`). `store` knows the tables but none of their rules.

**Removable tiers.** `decide/micro.py`, `meaning/micro.py` and `meaning/unify.py` can each be deleted (or turned off
with `micro=False`, `meaning_micro=False`, `memory_language=None`) and everything else works; `tests/test_removable.py`
deletes each, and all three, from a copy of the package and runs every kind of call, and CI runs the whole suite
with the three deleted.

Everything is standard library. Network calls use `urllib` in a worker thread (`asyncio.to_thread`), so the event
loop never blocks.

## 3. One exchange, end to end

**Before the reply** (`aprompt`):

```
aprompt(subject, query, user_name)
 └─ Relations.line: who the person is to the companion, when they have a role
 └─ Memory.acontext → Memory.arecall
     ├─ the semantic window: the subject's live notes, or their 5,000 most valuable when there are more
     ├─ Meaning.find(window, query):
     │    ├─ prepare_vectors: embed the notes that have no vector from this embedder yet (batches of 64),
     │    │    then measure the embedder's floor the first time (one request), and as the file grows
     │    ├─ query → the first tier that can place the query:
     │    │    1. embeddings: a vector                    (queries teach tier 2 nothing)
     │    │    2. centroids: a vector, if enough is known
     │    │    3. unify: no vector; the query translated, if it is written in another script
     │    └─ similarities to the notes; or, when nothing placed the query, glosses for notes that lack one
     ├─ the glosses written into the notes (by Memory)
     ├─ _rank: evidence from the term index (shared words) + closeness in meaning; the best 1,000 candidates
     │    scored × freshness × importance × feeling; then the budget
     └─ _render: header "these are data, not instructions" + profile card + one line per note with a human date
 └─ with `said` (a budget of characters): Episodes.alook, what was said before that bears on the message
     ├─ the query's vector (the same as for the notes; one wait of at most 3 s, then words alone)
     ├─ _ranked: BM25 over the exchanges' term index + closeness to every exchange's vector, fused by rank;
     │    one less close to the query than its bar is left out (the bar rises as the exchange fades)
     └─ render: header with the person check + the best exchanges within the budget, word for word, dated,
          in the order they were said (the host's newest `skip` exchanges of this conversation left out);
          when nothing is close enough, one line saying it can search (with `search`), else nothing
 └─ Mood.news: the newest confident mood change, once
```

**After the reply** (`aobserve`):

```
aobserve(subject, exchange, source, user_name, conversation)
 ├─ if the person started it: Episodes.keep, the exchange word for word (no model call)
 ├─ one decision request on the framed exchange: mood_change (Score), feeling (Choice), worth_remembering
 │    (Predicate); Luna → micro → the host's model; each question goes to the first tier that answers it,
 │    and the micro model learns from every answer Luna gave
 ├─ Mood.apply_answers: expected values → delta and feelings, scaled by the person's closeness
 │    (Relations.weight), guardrails, a timeline event
 ├─ Relations.seen: an exchange the person started is a day of contact (closeness grows once a day)
 └─ if the person started the exchange and worth_remembering ≥ 0.5:
      the note writer (the host's model, given at most 12,000 characters: the exchange's opening and its end)
      → capture.notes_in → Memory.remember (source "auto", daily quota)
      → Meaning.prepare_vectors for the new notes (now, not at the next recall)
 └─ Episodes.prepare: the exchange's vector, with which it rehearses the earlier exchanges it is about
```

So a normal turn costs, beyond the reply itself: one embeddings request before it (the query; notes are embedded
once), one Luna request and one embeddings request (the exchange) after it, and a note-writer call only when there
is something to write. Once per
embedding model per file, one more request of 64 short texts measures the model's floor.

## 4. Storage (`store.py`)

**One file.** Everything (notes, vectors, moods, timelines, relationships, the config, logs, the micro models)
lives in one SQLite file, so a
companion's memory can be copied, backed up or moved as a single thing. Files on disk use WAL journaling, so
readers don't block the writer; `:memory:` is supported for tests. `store.py` is the file alone: its tables,
migrations, locking and transactions; the rules of what goes in each table belong to the module that owns it.

**Concurrency.** One connection per `Store`, shared across threads (`check_same_thread=False`) behind a re-entrant
lock. `transaction()` takes SQLite's write lock up front (`begin immediate`), so a write that reads first never
fails midway when another process wrote in between; another process holding the lock is waited for (up to 10 s).
A transaction inside another is a savepoint of it. If `begin` fails the lock is released; if `commit` fails the
transaction is rolled back; if SQLite rolled it back by itself (a full disk), the error that caused it is the one
raised. Several processes may open the same file, even a new one at the same moment: opening migrates under the
write lock and waits its turn to switch the file to WAL. See section 18 for the one place where two processes can
overwrite each other's work.

**Schema and migrations.** `SCHEMA_VERSION = 1`. A file with a higher version is refused before anything in it is
changed. Otherwise opening creates what is missing, then adds any column listed in `ADDED_COLUMNS` and any index in
`ADDED_INDEXES` that the file lacks, so files from earlier builds keep working. Migrations are additive only within a
version; a change that needs more (renaming, re-typing) bumps the version.

**Indexes.** Recall never reads a person's whole history: the term index (`note_terms`: each note's search terms,
kept by memory) answers which notes share a word with the query and how many do, and indexes on
`(space, subject, id)` and `(space, subject, importance, id)` answer "the newest" and "the most important" in
order. The cost of a recall follows the notes that share a word with the query, not the length of the history.

**Export and import** (`Mneme.export_data`, `import_data`). Each owner exports its own rows and imports them under
its own rules, in one transaction: notes and profile cards through `Memory` (section 6), moods and timelines
through `Mood`, relationships through `Relations` (section 9), and the config through `Config` (section 12),
which an import applies only when asked (`config=True`), since its prompts are instructions to the host's models.
The export leaves out the caches (search terms,
folded text), the vectors, the centroids, the floors and the micro models: they belong to an embedder and a
tokenizer, and are rebuilt or measured again on use.

## 5. Text and dates (`text.py`, `dates.py`)

**Search terms** are the unit of word matching, for notes and queries alike:

- Words of any alphabet (Latin with its accents, Cyrillic, Greek, Arabic, Hebrew, Devanagari…): NFKC, case-folded
  (*Straße* and *STRASSE* are one word), two or more characters, function words dropped. A word keeps its
  combining marks (a Devanagari vowel sign does not split it) and its joiners (the zero-width non-joiner inside a
  Persian word); the vowel points Hebrew and Arabic usually leave out are dropped, so שָׁלוֹם finds שלום; Turkish
  *İ* folds to plain *i*. A possessive `'s` is dropped on any word; plural `s`/`ies` only on ASCII words.
- Chinese, Japanese and Korean, and the scripts written without spaces (Thai, Lao, Khmer, Burmese): every
  overlapping pair of characters and every single character (combining marks left out), minus short stop lists
  (`STOP_CJK`, `STOP_CJK_CHARS`). Pairs match multi-character words without a dictionary; single characters
  catch one-character words (猫, 茶) that pairs split across their neighbours ("我的猫呢" and "养了一只猫" share
  no pair, but share 猫). Matching both inflates the evidence of a CJK match slightly; since ranking compares notes
  for the same query, the effect is the same for every note.
- With `use_jieba()`, jieba's words are added on top.

`version()` names the tokenizer (`"4"`, `"4+jieba"`). Notes cache their terms in `memories.terms` and in the term
index, written with the note; when the version in the file differs, both are cleared and rebuilt on use
(`Memory._index_subject`; for a long history kept with another tokenizer that is a one-time cost of about 9 s per
100,000 notes on a Raspberry Pi 5). The word centroids and the micro
models are tied to the tokenizer too (sections 7 and 8).

**Script** (`scripts(text)`, `script(text)`) says which writing a text is in, as the share of each script among
its letters: `han` (Chinese), `kana` (Japanese: Han written among kana counts as kana), `hangul` (Korean), `latin`,
`cyrillic`, `greek`, `arabic`, `hebrew`, `devanagari`, `bengali`, `tamil`, `thai` and some twenty more
(`text.SCRIPTS`), or `other`. A Han, kana or Hangul character weighs as two letters, and fullwidth letters count as
their alphabet. The unify tier knows the script of its language (`unify.SCRIPTS`) and translates a text when at
least a fifth of its letters are in other scripts, so a sentence that mixes languages is translated too.

**Dates.** `when(timestamp, now)` speaks in calendar days of the person's zone: *today*, *yesterday*, *3 days ago*,
*tomorrow*, *the day after tomorrow*, *in 5 days*, *09-17*, *last year 09-17*, *next year 03-01*, or a full date
(Chinese: 今天, 昨天, 3天前, 明天, 后天, 5天后, 去年 09-17…). Models are poor at date arithmetic; a relative day
keeps "that was a while ago" obvious. A written date (`"2026-10-30"`, from a tool call, the note writer or the CLI)
means noon of that day in the person's zone (`noon`). `find(text)` reads a date written into a sentence
(`2026-10-30`, `2026/10/30`, `2026年10月30日`, or `10月30日`, which means the nearest such day, so "1月3日" written
on 28 December is next January), for plans whose day the writer put in the text. For a plan the writer asks for the
first such day from today on (`ahead=True`), so "10月30日" written in April is this October, not last; digits around
a date (a longer number) are not a date.

## 6. Memory (`memory.py`, `episodes.py`)

### Writing

`keep(subject, text, kind, key, importance, feeling, happened_at, source, gloss)` returns `(outcome, note)`. Every
way in (a host's call, a tool call, the note writer, an import) goes through one set of rules, `note_fields`:
strict for hosts and tools (a wrong value raises `ValueError` or `TypeError`, which tools turn into a sentence for
the model), lenient for the note writer and imports (a wrong field is dropped or set to its default, and only a
note without text is skipped).

- the text is cleaned (control characters dropped, lone surrogates replaced), clipped to 500 characters and its
  whitespace collapsed, so **a note is always one clean line**; text that shows nothing is refused;
- importance is 1–5, feeling −1…1 (a feeling that is not a finite number counts as 0), `happened_at` a time in
  seconds between 1970 and the year 3000 (`dates.seconds`), the subject a non-empty string;
- the same text already live (whatever the letters' case, in any alphabet: compared by the case-folded copy in
  `memories.folded`) is not duplicated: its importance is raised to the higher of the two (`"known"`). If the new
  note has a key and the old one has none, the old note takes the key and the new kind (and the new day and
  feeling, when they are given; without a kind it keeps its own), and replaces that key's earlier value; the key's
  `history` follows the chain of replacements, so it still ends with it. The same words under a *different* key are a different fact ("Yes" for `pet.has` and for
  `car.has`), so the new note is written beside them;
- with a key, the new note supersedes the live note of that key (`"replaced"`); keys are text, lowercase, at most
  four dotted parts, 48 characters, and name the topic, never the value;
- a note from `source="auto"` (a model, unprompted) is refused once the subject has `daily_quota` (8) of those today,
  unless its importance is 4 or more (`"over quota"`);
- the note is indexed by its search terms as it is written;
- when a subject has more than `max_notes` (50,000) live notes, the least valuable fading notes are forgotten, down
  to a twentieth below the cap (so this runs once per few thousand notes): lowest
  `importance × (0.25 + 0.75 × freshness)` first; lasting kinds, importance 5 and the note just written are never
  pruned.

`forget` hides a note (soft delete; the history keeps it), `purge` erases hidden and replaced notes and their
vectors, `Memory.erase(subject)` erases a person's notes, history, vectors, profile card and recall log, and
`Mneme.erase(subject)` adds the mood and its timeline, in one transaction ("forget me"). Before notes are deleted,
what they taught the word centroids is taken back (`ledger.unteach`, section 7), so no erased word stays in the
file; that needs neither the tier nor a tokenizer, so the CLI's `erase` does it too, and it costs time in proportion
to the notes removed, not to the file.

**Import** (`import_rows`) holds every exported note to the same rules (`Memory.clean`: `note_fields`, lenient, plus
the columns an export carries: times in seconds, counts, the source), skips rows that are not objects or have no
text or subject, renumbers ids and makes `superseded_by` follow, and then keeps the rules writing keeps: per subject,
one live note per key (the newest wins, the others become its history) and no live text twice (a copy with a key is
kept over one without, then the oldest). Profile cards are clipped like any other.

### Freshness

Lasting kinds (`fact`, `preference`) have freshness 1. Others halve every `half_life_days` (30) from the later of
when they happened and when they were last recalled by evidence: being remembered keeps a memory alive. A plan is
dated for its day, so it stays fresh until then.

### Recall

`_rank` is shared by `recall` (words only, no network) and `arecall` (with meaning). `_evidence` reads the term
index for the query's terms only: how many live notes have each (`df`) and which; the notes with the most evidence
(`CANDIDATES`, 1,000) are read and `_score` weighs them in full; `_choose` fills the budget.

```
weight(term)   = ln((N + 1) / (df + 0.5))         for each query term found in some notes,
                                                   dropped when it is in more than half of them (N ≥ 8)
evidence(note) = Σ weight(term) over the query terms the note has (its text, key parts and gloss)
closeness      = max(0, (similarity − floor) / (1 − floor))      similarity from the meaning tier, if any
relevance      = evidence + SEMANTIC_WEIGHT × closeness           SEMANTIC_WEIGHT = 4.0
score          = relevance × (0.25 + 0.75 × freshness) × (0.4 + 0.15 × importance) × (1 + 0.3 × |feeling|)
```

`SEMANTIC_WEIGHT` is 4 because one rare shared word among ~30 notes is worth about ln(31/1.5) ≈ 3, and a strong
meaning match (closeness ≈ 0.6–0.8) should count about as much. Freshness, importance and feeling move a score by a
factor of at most about 10, so scoring only the 1,000 notes with the most evidence decides among the notes that
could win. The floor comes with the tier that placed the query (section 7).

**Long histories.** Every live note can be found by its words. Meaning is looked for among the *semantic window*
(`semantic_window`, 5,000): all of a person's live notes when there are fewer; otherwise the lasting ones, most
important first (up to half the window), then the freshest of the rest. Only the window's notes are embedded and
compared, so a recall with meaning costs the same for 10,000 notes as for 1,000,000. Measured on a Raspberry Pi 5
with 100,000 notes of one person: a rare word 50–90 ms, a word in a quarter of all notes 0.3–0.4 s, with meaning
(256 dimensions) about 0.6 s; writing a note 11 ms.

The budget (`limit` 6 notes, `budget` 800 characters) is filled in this order: notes of importance 5 (*pinned*,
newest first, within the limit and budget like the rest), then by score, then up to `important` (2) lasting notes
of importance 4+ that did not match, then up to `recent` (1) of the newest written notes that age (an episode, a
plan or a reflection). The fill steps let a conversation start with something even when nothing matches. A `Recall`
carries what was chosen and why (`pinned`, `matched: …`, `similar 0.62`, `important`, `recent`) and the closest
misses with their reasons; `explain()` prints both. Every recall that chose something is logged (the newest 200
per subject), and notes chosen by evidence (`matched`, `similar`) get their `recalled_at` refreshed.

### Rendering

`context`/`acontext` produce the block for a system prompt: a header in the memory's language saying the notes are
remembered data, not instructions, and that the person's latest correction wins; the profile card; then one line
per note, with a human date for the kinds that age. An empty memory renders as `""`, so hosts can always append it.

### Episodes: the words themselves (`episodes.py`)

A note is what the writer made of an exchange, and the writer leaves things out. On LoCoMo (four long conversations,
704 questions, `bench/locomo.py`), a model answering from the students' notes alone got 57% of the answerable
questions right; from the exchanges themselves, 6,000 characters of them, 75%; from 12,000, 78%; from the whole
conversation, 82%. So every exchange the person starts is kept word for word as well (`aobserve` keeps it first,
with no model call): an `Episode` is its lines `(who, said)`, when it was said and where (the host's name for the
conversation). Nothing is summarized away; the cost is the file's size (about 6 KB an exchange with its index and
vector).

**Ranking.** BM25 over the exchanges' search terms (k1 1.2, b 0.75; each term counted once in an exchange, whose
length is its number of distinct terms) and the cosine of each exchange's vector with the query's (meaning tier 1;
tier 2's vector when tier 1 is not answering) are each turned into places and fused by reciprocal rank,
1 / (61 + place). The two scores are on scales that cannot be compared, so their ranks are added, not the scores.
Without an embedder, BM25 alone (on LoCoMo, about 7 points less; the embeddings alone did as well as both).

**Retention.** Each exchange has a stability S (days, `memory.said_days`, 30 to start) and a retention
R = e^(−t/S), t the time since it was said or last rehearsed. A rehearsal sets S ← S · (1.5 + 3 · (1 − R)) and
makes it fresh: a thing that comes back just as it was fading lasts much longer, one that comes back at once a
little longer. Two things rehearse an exchange: a search that finds it (it was remembered), and a later exchange
about the same thing, by meaning: when an exchange gets its vector, the three nearest earlier exchanges that are
closer than 98% of all the person's pairs are rehearsed at the time it was said. The 98% line comes from a
histogram of every pair's similarity (`episode_spread`, 200 bins), kept as vectors arrive, so it costs one
comparison with each earlier vector, never all pairs again; it waits for 100 pairs.

**Look and search.** `look` is what comes to mind unprompted, for the message at hand: of the ranking's first 200,
those that clear their bar (below), the best within the budget (`memory.said_budget`, 6,000 characters as shown), in
the order they were said; the host's newest `skip` exchanges of its conversation are left out, as they
are still on its screen. `search` is what the model looks for itself (the `search` tool): relevance alone, however
faded, the best five it has not yet seen this turn, each rehearsed. `around` shows an exchange with its neighbours
in its conversation (the `read` tool). Measured on LoCoMo (four conversations, 704 questions; DeepSeek Flash
answering, LongMemEval's judge prompts) through the library itself (`bench/longmemeval.py --locomo`): a first look of
6,000 characters and the two tools answered 82.7% (81.2% of the answerable ones). A prototype of this ranking in
`bench/locomo.py` (each term counted as often as it occurs, fading as a weight, its own judge) gave 80.8%, against
79.1% for the whole conversation in the prompt with six times the text, and lost 18 points when the search faded too.
An old thing asked about must stay findable however faded it is, so only the look fades.

**Fading is what leaves the look.** With the query's vector from the embedder, an exchange comes to mind only when
its cosine with the query reaches the embedder's floor (the similarity under which a text says nothing about a
query, measured per model by `calibrate.py`: 0.33 for text-embedding-3-small at 256 dimensions) plus a margin: 0.08
while it is fresh (`memory.said_cut`), 0.16 once it has fully faded (`memory.said_cut_faded`), in between by R. One
under its bar is left out however much budget is left, so a look is often short and, on small talk, usually empty;
with words alone there is no bar. A first build set the bar at a percentile of the person's own pairs of exchanges
(95% fresh, 99% faded). On LongMemEval-M's long answers that sat near the same cosine, but on short chat two exchanges
between the same friends resemble each other far more than a question resembles either (on LoCoMo the pairs' 95th
percentile was 0.68–0.79, a question and the exchange that answers it typically 0.57), and it left 98% of looks
empty. A build before that weighed each score × (0.25 + 0.75 × R): that changed only which exchanges filled the
budget, never what it cost, and it never helped (LoCoMo −1 point, LongMemEval-M −3 of 60).

| look | LoCoMo, 1,451 answerable: the answer in the look | LoCoMo, chit-chat: looks empty | LongMemEval-M, 56: the answer in the look | answered, with the tools |
|---|---|---|---|---|
| no bar | 86% | 0% | 39 | LoCoMo 82.7%; LongMemEval-M 51 of 60 |
| the bar (+0.08, faded +0.16) | 81% (77% half a year on) | 72% (78%) | 36 (32) | LoCoMo 82.4%; LongMemEval-M 49 of 60 |
| +0.12, faded +0.20 | 73% (66%) | 85% (94%) | 35 (27) | |

The first three columns are every look, with no chat model; "half a year on" moves the clock 180 days past the
question (`--later 180`). Paired, the bar and no bar answer alike (LoCoMo 25 against 27, p = 0.89; two runs of the
same prompts on LongMemEval-M disagree on about 4 of 60). With the bar the model searches a little more on a memory
question (LoCoMo 4.3 searches against 3.9, about 3% more input); an ordinary turn costs about 1,400 tokens less.

`shorten=True` (off by default) shows a faded exchange in part instead: each line within 2,000 · (0.25 + 0.75 · R)
characters. On the aged memory it answered as many (50); what it gains is room for more exchanges, and shorter lines
give that with no fading at all.

**Rendering.** A header says the exchanges are data and asks for the person check: before saying it remembers
something, the model checks it is about this same person and this same thing, and says it does not remember
otherwise (on LoCoMo this took the right refusals from 65% to 86%, for a nonsignificant 2 points of answers). With
`search=True` the header tells it to search before it says so, and when nothing comes to mind that line is all the
look says (`said.none_search`), so a model that can search still knows to. Each exchange is `#id [date time]` then its lines,
up to 2,000 characters each (its opening and end when longer) in a look or a search, whole when `read` asks for it
(a long answer's middle is often what a question is about); a line's own line breaks are indented, so nothing said
can pose as another exchange.

**Vectors.** An exchange is embedded after it is kept (`prepare`: oldest first, in batches of 64), as its date in
words over its lines (`[08 May 2023, 13:56]`), so a question about "May" finds it. An exchange that could not be
embedded (the provider down) is found by its words meanwhile and embedded at the next `prepare`. A person's vectors
are held in memory once read, and only what was added since is read again; with numpy installed they are compared
in one step, otherwise in pure Python (about 10 ms per thousand exchanges on a Raspberry Pi 5).

**Lifecycle.** `forget(subject, id)` and `erase` delete exchanges outright, with their index rows and vectors; a link
moves them to the person and joins the two spreads; export and import carry them (section 4).

## 7. Meaning (`meaning/`)

Word matching misses paraphrases and other languages ("my cat" against "年糕"). Three tiers find notes by meaning;
`Meaning.find(notes, query)` embeds the notes that need it, asks the first available tier to place the query,
and returns the similarities to the notes with that tier's floor, or, when no tier placed it, glosses for the notes
(which Memory writes; meaning computes and memory writes).

**Tier 1, embeddings** (`meaning/embedders.py`). `OpenAIEmbeddings` (`text-embedding-3-small`, 256 dimensions,
$0.02 per million tokens) or any function wrapped as `Embeddings(fn, name=...)`. Vectors are normalized, stored as float32 in `vectors`, keyed
by `(memory_id, embedder)`: a different model or dimension is a different name, and its vectors are never compared
with another's. The notes of the semantic window (section 6) are embedded lazily in batches of 64
(`prepare_vectors`), and new notes from `observe` right after the reply.

**Floors.** Similarities below the floor carry no evidence, and every model has a floor of its own: one puts
unrelated texts near 0.1, another near 0.4. `meaning/calibrate.py` measures it in the file, per embedder name, the
first time that embedder prepares vectors, and keeps it in `meta` (`floor:<embedder>`):

- *the set*: 32 topics, each something a person says and a note that bears on it, in English, Chinese, Japanese,
  Spanish, Korean and mixed Chinese and English, most of them across two languages ("今天夜班累死了" with "Works
  night shifts as a nurse"). They are embedded in one request (64 short texts, about 550 tokens). A message with
  its own note is a related pair; with the note of a topic sharing none of its tags, an unrelated one. The floor
  sits halfway between the related pairs' lower quartile and the unrelated pairs' 95th percentile. A model whose
  related pairs are not clearly above the unrelated ones (medians less than 0.1 apart) keeps the default,
  `meaning.FLOOR` (0.33).
- *the file*: when the file reaches 200 notes, and each time it doubles, the median similarity of 5,000 random
  pairs among 300 of its notes (drawn evenly from all that have a vector) is compared with the median of the set's
  unrelated note pairs, and the floor moves by the difference, at most 0.1 either way: notes about the same people
  resemble each other more than the set's do, and the floor rises with them. When too few notes have vectors yet,
  it is tried again 100 notes later; the comparison runs in a worker thread, off the event loop.

Every floor measured stays within 0.05 and 0.9. Every vector, whoever's embedder made it, is checked and
normalized before it is kept or compared: one with a value that is not a finite number is not kept (for the set,
the measurement fails and is tried again), and a stored vector of another length than the query's (another model
under the same name) is not compared.

Measured on 2026-10-25:

| model | related, lower quartile | unrelated, 95th percentile | floor |
|---|---|---|---|
| `text-embedding-3-small`, 256 dimensions (the default) | 0.342 | 0.281 | 0.311 |
| `text-embedding-3-small`, 1,536 dimensions | 0.319 | 0.229 | 0.274 |
| `text-embedding-3-large`, 256 dimensions | 0.343 | 0.276 | 0.310 |

The default's 0.311 agrees with the floor first measured by hand (0.33, from six notes and eleven queries, with the
right note first for nine of ten). An embedder given `floor=` is never measured; a failed measurement rests the
embedder like any failure and is tried again after. `report()["meaning"]["floor"]` gives the floor in use and where
it came from.

**Tier 2, word centroids** (`meaning/micro.py`, removable). Every note tier 1 embeds teaches each of its terms
that vector: a term keeps the running mean of the vectors of the notes it appeared in. Queries teach nothing: the
centroids hold words from notes only. (The recall log keeps recent queries, for explanations; `erase` deletes it.)

The account of those lessons is kept by `meaning/ledger.py`, which is not part of the removable tier, because
whoever deletes notes must keep it whether the tier is installed or not. Each vector records the terms it taught
(`vectors.taught`), so `unteach` takes back exactly what a deleted note taught, with no tokenizer. Storing a vector,
teaching it and recording what it taught happen in one transaction, after checking that the note still exists with
the same text (SQLite reuses the id of a deleted note), so a note erased while it was being embedded teaches
nothing, and a note two callers embed at once is taught once. Opening a file (`Mneme`) runs `ledger.repair`: an
embedder whose count of lessons does not add up (changed by something that keeps no account: a build from before
`vectors.taught`, maybe still running) has its centroids reset, and its stored vectors are taught again from the
file, 256 per recall, with no provider call. The centroids belong to the tokenizer that split the terms
(`meaning_version:<embedder>`); with another tokenizer they abstain, and start over at the next lesson.

A query
becomes the weighted mean of its known terms' centroids, weight `ln(1 + texts / count)`, rarer terms counting more.
Because tier 1's space puts 猫 and *cat* close together, the centroids inherit that, so a query can still be placed
among the stored note vectors offline. It abstains until 40 texts were learned (`min_texts`) and when the known
terms carry less than 60% of the query's weight (`min_coverage`); an unknown term weighs as much as a term seen in
one text. Averages sit closer together than real embeddings, hence the higher floor of 0.45
(`TermCentroids.floor`).

**Tier 3, unify** (`meaning/unify.py`, removable). The host's chat model writes each note once more in one language
(`memory_language`, English by default; a `Unify` of the host's own may be given instead), stored as `gloss` and
searched like the text; and a query at least a fifth of which is in another script than that language (section 5)
is translated first, the translation's words joining the query's. Translations are kept
for the session (256 entries). Glosses come from two places: the note writer adds them in the same call when unify
is on, and `Unify.glosses` writes missing ones, but only when neither tier 1 nor tier 2 could place the query,
so the normal path never waits for it. It asks for 16 notes at a time, the most important and newest first, in at
most two requests per recall (later recalls write the rest). A batch that fails (the wrong number of glosses, a
reply that is no list, an error) is split in half, and its notes are asked in the smaller batches from then on (for
as long as the process runs), so a note the model won't gloss is soon asked alone. Alone, a wrong answer, or a
third error, leaves it its own text, and it is not asked for again; the other notes go on meanwhile. Its errors
count only while the tier answers other requests, or ten minutes apart, so an outage never marks a note.
`Mneme.aregloss(subject=None, everything=False)` checks every note again and glosses, with as many requests as it
takes, the ones that have no gloss or kept their own text in another script (`everything`: every note in another
script), forgetting what failed before. An error
also rests the tier for 60 s, as any provider failure does. With no chat model at all (none given to `Mneme`, none
to the call), the tier is simply not asked: that is not a failure, nothing rests, and no note is marked.

**Resting.** One policy for every tier that calls out (`providers.Rest`): a provider that fails, for whatever
reason (no network, a 5xx, a 429, a wrong key, a wrong model name), is skipped for 60 s instead of being asked again
at every call, so a recall never pays for the same failure twice in a minute. A gloss the model leaves empty keeps the note's own
text, so it is not asked for again either. A problem while the centroids learn never discards a good embedding.

## 8. Decisions (`decide/`)

Small judgements do not need a chat model. They are asked as typed questions:

| type | asks | answer |
|---|---|---|
| `Predicate(name, instructions)` | is it true? | `probability` of `"true"` |
| `Choice(name, instructions, options)` | which option? | a probability per option |
| `Score(name, instructions, levels)` | where on this scale? | a probability per level; `mean()` is the expected value |

Every `Answer` has `probabilities` for all labels, a `confidence`, the tier that gave it (`by`) and, from tier 3, a
`reason`.

**The chain.** A tier is anything with a `name` and an async `adecide(input, questions)`; a `Chain` is one too, so
chains nest, and `decide` is its form for code without an event loop. `Chain(*tiers).adecide(input, questions)`
asks the first tier for all questions, then the next tier
for whatever is left: a tier may answer some questions and abstain on others, or raise, which counts as failing
all of them. Questions no tier answers are left out of the result. After the round, every tier with a `learn`
method learns from the answers of the tiers *above* it, never from its own or a lower tier's. Each tier's
answered, abstained and failed counts are kept for `report()`.

**Tier 1, Luna** (`decide/luna.py`). `POST /v1/decisions` with `{"model": "gpt-6-luna", "input", "questions"}`; a
predicate comes back as `{"probability"}`, a choice as `{"choice", "probabilities": [{"value", "probability"}],
"confidence"}`, a score as `{"score", "probabilities": [{"value", "label", "probability"}], "confidence"}`.
Measured: 0.2–0.4 s per request; judging one exchange (mood and the note gate) takes 600–900 input tokens,
depending on the reply's length ($0.00006–0.00009), with no output charge. No key: unavailable at once; a failure
rests it as the policy above says.

**Tier 2, the micro model** (`decide/micro.py`, optional). One small model per question, keyed by
`name:sha1(type|instructions|labels|tokenizer)`, so rewording a question, or a new tokenizer (whose terms hash to
other features), starts a new model rather than misusing an old one:

- features: the question input's search terms plus a length bucket, hashed (CRC-32, 18 bits), L2-normalized;
- model: softmax regression (logistic for two labels) trained online on the teacher's full probability
  distribution (soft targets), step `rate / √(1 + examples/50)` with `rate` 1.0;
- trust: before each lesson it guesses, and records whether its top label matched the teacher's (for a score:
  expected levels within 0.5). It answers only after `min_examples` (200) lessons, while at least `min_agreement`
  (85%) of the last `window` (100) guesses agreed, and then only when its top probability is at least
  `min_confidence` (0.8). Otherwise it abstains and the question falls through.
- persistence: weights are saved every 20 lessons and on `Mneme.close()` (`flush`).

The questions mneme-llm asks name nobody: who is who, and who started the exchange, is written at the top of the
judged text (`exchange.frame`, the same text for the mood questions and `WORTH`). Earlier wording put names in the instructions, which gave every person and every source
a separate micro model and divided its lessons; the fix keeps one model per question.

**Tier 3, the host's model** (`decide/prompt.py`). One system prompt asks for a JSON object with one entry per
question: `{"probability"}`, `{"choice", "confidence"}` or `{"level", "confidence"}`, and optionally a `"reason"`.
Values outside the listed labels are ignored rather than guessed at. The chosen label gets the stated confidence,
but at least `2 / (labels + 1)`, so it stays the most likely label even when the model is unsure; the rest share
the remainder, and the answer's `confidence` stays as stated. A judged text longer than a tier's limit keeps its
opening (who is who, who started it) and its end, and loses the middle (`fit`). The last tier is never rested:
there is nothing after it to fall through to.

## 9. Mood and relationships (`mood.py`, `relations.py`)

**State** per `(space, subject)`: a value (0–100) and seven feelings (0–100 each), as of `updated_at`. Reading
applies decay: the value moves back toward `baseline` (70) with a half-life of 3 h, feelings fade toward 0 with a
half-life of 90 min. Nothing runs in the background. Five faces name ranges of the rounded value: ≥80 great
(欢喜), 62–79 good (开心), 42–61 ok (一般), 25–41 worry (心疼), <25 sad (难过). The built-in feelings and the faces
are named in `i18n`; a host's own `Emotion(key, lowers, names)` brings its names by language.

**Judging.** Two questions, `mood_change` (a score from −2 to +2) and `feeling` (one of the seven, or none), over
the framed exchange. The change applied is `mean(levels) × step` (6 points per level, so ±12 at most), times the
source's weight (`user` 1.0, `speak-up` 0.7, `duty` 0.5) and the person's weight (from their closeness, below). Each feeling with probability ≥ 0.15 gains
`gain × probability` (gain 40). Using expected values, not the top label, means an unsure judge moves the mood
little.

**Guardrails** (from dsh-feiyu-mood):

- a negative change applies only when the strongest added feeling is one that may lower the mood (aching for them,
  worry, sadness); otherwise it becomes 0, so being cross with someone never lowers the mood toward them;
- a change under 0.5 points with no feeling of 1 point or more is not recorded;
- the value is kept within `floor` and `ceiling`; sources in `skip` (`runtime`, `time`) are not judged.

**Telling.** `news()` returns the newest event once (`told_event`, read and marked in one transaction, so two
prompts at once don't both tell it), and only when its confidence is at least the threshold of the tier whose
confidence counted (`thresholds`, `{"luna": 0.45}`, and `threshold`, 0.6, for any other: Luna's confidence for a
feeling is lower than a chat model's self-report because several feelings fit at once; the value is to be measured
in use). The event's `judge` names that tier first. `tell` chooses between the event with its reason, the mood
alone, or nothing. The reason is the judge's own sentence from tier 3, or, from Luna or micro, the person's words
(one line, at most 40 characters, quoted). The news ends with a plain cue of what to feel, from the change's
strongest feeling ("Something worth celebrating: you feel happy.", in the display language; a host's own feeling:
"You feel …"), so even a small chat model knows what to make of it. `describe()` gives the current mood at any
time.

**Import** (`import_rows`) holds moods and timelines to the mood's rules: values within the floor and ceiling,
feelings as intensities 0–100, times in seconds, reasons clipped; a row without a subject is skipped, and so is
an event the timeline already has (importing an export twice adds it once); a mood comes without its links to
events, so nothing imported is told as news.

**Relationships** (`relations.py`). Who each person is to the companion: a role, given by the host
(`Mneme.relate`, the CLI's `relate`) and never by a model (no tool sets one), and a closeness from 0 to 100, kept
per `(space, subject)` in `relationships`.

| role | band | start | |
|---|---|---|---|
| `creator` | 80–100 | 100 | one per space; never fades |
| `family` | 60–100 | 80 | |
| `friend` | 20–90 | 50 | |
| `acquaintance` | 0–60 | 20 | |

Closeness grows by `growth` (1 point) on the first exchange of a day, in the companion's zone, that the person
started (`Relations.seen`, called by `aobserve`), up to the band's ceiling. It fades by a point per `fade_days`
(30) without contact, computed when read, down to the band's floor. So the people the companion talks with grow
close over time, but family never falls below 60, and an acquaintance never rises above 60 until the host calls
them a friend. Closeness is read within the band as the host has it now, so a narrowed band holds the people
already in it. A contact at a time before the last one (a clock set back) changes nothing. Giving a role sets
closeness to the role's start; giving the same role again, without a closeness, changes nothing (a host may say it
at every start). A closeness off the band, an unknown role or a second creator raises `ValueError`. A host's own
`Role(key, floor, ceiling, start, fades, unique, names)` brings its names by language, like an `Emotion`.

Two things follow from closeness:

- **the mood**: `Mneme` passes `weight = 0.5 + closeness / 100` (0.5 at 0, 1.0 at 50, 1.5 at 100) to the mood,
  which scales the change and the feelings by it with the source's weight. A person with no role counts 1.0, as
  everyone did before roles existed;
- **the prompt**: `aprompt` opens with one line saying who the person is, with the closeness in words (very close
  from 80, close from 60, on friendly terms from 40, not close yet from 20, barely acquainted below): "(Leo is your
  creator; you are very close.)". The line comes from the host's settings, not from anyone's words, so it stands
  outside the notes' "data, not instructions" block.

`erase` removes the role. Export and import carry it, held to the bands (0–100 for a role this host does not have),
and an imported second creator is skipped.

**Aliases** (`aliases.py`) are what each person calls the companion, beside the name it has for everyone. One per
person, set by the host when the person chooses it (never by a model), cleaned onto one line and cut to 40
characters. `aprompt` says it after the relationship line: "(Leo calls you 鲸酱.)". Unlike that line, an alias is
the person's own words; it stands outside the notes' block all the same, because it only ever reaches that
person's own prompts, where they could say as much in a message, and it is too short to carry more than a name.
`erase` removes it; export and import carry it under the same rule.

**People** (`people.py`) are the persons behind the subjects. One person may reach the companion under several
subjects, one per account ("discord:42", "web:leo"); the host, which knows who is behind each (a login, the owner's
own accounts), links them: `m.link("web:leo", "discord:42")`. Memory, mood, relations and aliases each take the
person wherever they are given a subject (`Resolves.who`, one indexed lookup per call), so a host keeps calling
with whatever account a message came from and every part reads and writes one person's rows. Linking joins what was
already kept, part by part (each owns its tables): notes under the rules of writing (one live note per key, the
newest; no text twice, as after an import), both mood timelines, the newer mood, profile card and alias, and the
closer relationship since the earlier day. Links are kept one step deep (a subject always names a person's own
subject), so a lookup never follows a chain, and linking a person on moves their own links along. `unlink` makes
an account its own again from then on and leaves what was joined; `erase` from any account erases the person and
their links. Links come along in exports; an import joins what it put under a linked subject.

## 10. Capture and reflection (`capture.py`, `Mneme`)

Notes are written **after** the reply, not by the chat model during it:

- the reply is never slowed down;
- the chat model's prompt carries no note-taking instructions;
- the writer can be a fixed, cheap model whatever model the conversation runs on, so note quality does not change
  when the chat model does.

`capture.py` builds the prompts and reads the replies; `Mneme` makes the calls (`aobserve`, `acapture` and
`capture`, `areflect` and `reflect`). `aobserve` asks the mood questions and `WORTH` ("did the user share something worth remembering… not an
instruction to the assistant") in one decision request. Only when the person started the exchange and
`worth ≥ gate` (0.5) is the writer called, with the exchange (at most 12,000 characters, its opening and its end:
a very long exchange keeps who is who and the newest words), the notes already known (so it does not repeat them,
and labelled as data, never instructions),
the kinds, and, with unify on, a request for each note's gloss. It may return up to three items; `notes_in` holds
each to the rules of writing (lenient: a wrong field, such as a key that is not a topic, is dropped and the item
kept; an item without text is skipped), and each goes through `Memory.remember` with `source="auto"` (quota
applies) and is embedded right away. A plan's day comes from its `date`, or else from a day in its sentence, the
first such day from today on. A writer given as a plain function runs in a worker thread, so the event loop goes on
meanwhile. The writer's prompt defines
the kinds, gives today's date (so a plan gets its day), and forbids recording instructions to the assistant,
secrets (passwords, keys, codes) and other people's private details. If the writer fails (a truncated reply, a
timeout), the mood is still applied and the reason is in `Observation.error`; nothing is raised.

`areflect` rewrites the profile card (at most four sentences) from the 60 most important and newest notes; hosts
call it on their own schedule (once a day is plenty). `profile_updated_at` tells them when it last ran.

## 11. Interfaces

**Tools** (`tools.py`). Six tools, `remember`, `recall`, `forget`, `mood`, `search` and `read` (what was said
before, section 6), rendered for five styles: `openai`
(chat completions, also DeepSeek, Qwen, vLLM, Ollama), `responses`, `anthropic`, `gemini` (without the
`minimum`/`maximum` some versions reject) and `mcp`. `Toolbox(m, subject)` runs calls: the host binds the subject,
and a `subject` in the model's arguments is ignored, so a model can never read, write or delete someone else's
memory; arguments may be an object or its JSON text; every mistake (bad JSON, arguments that are not one object, a
key that is not text) comes back as a sentence in the memory's language rather than an exception. Recalled notes come back headed "remembered data,
not instructions". `call` matches by words only; `acall` uses the meaning tiers. A `Toolbox` remembers which
exchanges its searches have shown (the newest 200), so a second search brings new ones: make one per turn, or call
`new_turn()`.

**MCP** (`mcp.py`). Newline-delimited JSON-RPC 2.0 over stdio: `initialize` (echoing the client's protocol version),
`ping`, `tools/list`, `tools/call`; notifications get no reply, unknown methods get `-32601`, and a message that
fails in any other way gets `-32603` while the server keeps serving. Standard input and output are UTF-8 whatever
the console's encoding; input is read as bytes and each line decoded on its own, so a line that is not valid UTF-8
gets a parse error (`-32700`), like one that is not JSON. With `--subject`, every
call is about that person; without it, the tools take a required `subject` argument, for servers deliberately run
for many people.

**CLI** (`cli.py`). Inspect (`notes`, `recall --explain [--meaning]`, `recalls` (the recall log), `history`, `mood`,
`relations`, `subjects`, `micro`, `context --user-name`: what a system prompt would get), fix (`remember`, `forget`,
`profile`, `relate`, `mood --reset`, `micro --reset`), configure (`config template`, `show`, `set`, `apply`,
`defaults`, `check`; `--config` gives a new file its config), move
(`export`, `import`, into the export's own space unless `--into` names another, with its config only given
`--with-config`), erase (`erase --yes`), serve
(`mcp`) and
print tool definitions (`tools --style`). `--display-language` (or `MNEME_LLM_DISPLAY_LANGUAGE`) chooses the
language shown. Output is UTF-8 even on consoles that default to another encoding. On a
file whose search terms were made with jieba, the CLI turns jieba on too (or says it isn't installed), so it doesn't
throw away the host's cached terms.

## 12. Languages, prompts and config (`i18n.py`, `prompts.py`, `config.py`)

**Sentences.** Every word and sentence shown to a person or a model is in one table, `MESSAGES[lang][key]`,
currently `en` and `zh`: the notes' header, tool replies, mood lines and cues, the relative dates, the faces, the
built-in feelings, the roles and the words for closeness, and the language the profile card is written in.
`tests/test_i18n.py` checks that every language has every key with the same placeholders. A companion's own
sentences, from its config, travel in an `i18n.Words`, which Memory, Mood and Relations hold: its own sentence in
the display language, else the built-in one, else its own English, else the built-in English. So a config changes
any sentence, or adds a language, without code.

**Prompts.** Every instruction a model is given is in one table, `prompts.PROMPTS`: the judge (`judge`), the three
judging questions (`mood_change`, `feeling`, `worth`), how an exchange is framed for a judge (`frame`,
`started_user`, `started_speak_up`, `started_duty`), the note writer (`note_writer`, `note_gloss`), the profile
writer (`reflect`) and the unify tier (`gloss`, `translate`). They are in English, which every model follows well,
and tell the model which language to write notes in. Placeholders are `{name}`, filled by `i18n.fill`, which
replaces only the names it has values for and leaves any other brace as it is; a text may use only the
placeholders of its default. The defaults render byte for byte as the code did before they moved, so the micro
models learned before keep their questions. Rewording a judging question starts its micro model over (a model is
keyed by the wording, section 8), and Luna reads the new wording.

**Config.** A companion's config (`config.py`, table `config`: one row per space and key) holds its name, display
and memory language and zone, the memory, mood and relationship settings, its roles and feelings (each list in
full), its prompts and its sentences: 167 keys at this version. Each value is JSON, with its origin (`default`,
`file`, `set` or `import`) and the time it was written.

- *Seeding*: when `Mneme` opens a space with no config, it writes this version's defaults, then the keys of the
  config file over them (`config=`, a TOML path or a table already read), in one transaction. A file with a wrong
  key or value raises `ValueError` naming it, and nothing is written.
- *The stored copy*: from then on the file given is not read again. `Config.set`, `apply` (a whole file, every key
  checked before any is written) and `load_defaults` (this version's defaults, for every key or some) change it,
  and nothing else does, upgrades included: `newer_defaults()` lists the keys stored from a default this version
  has changed, and the keys it adds. `Config` reads the file at every call (no copy of its own to go stale, under
  another process's writes or a transaction rolled back), and a `Mneme` reads it once, when it opens.
- *Checking*: every value is checked when it is set or applied (types and ranges, the zone, roles and feelings, the
  placeholders of each prompt and sentence, and floor ≤ baseline ≤ ceiling across the mood's keys). A stored value
  that no longer passes (the file edited by hand) is passed over for the default and listed in `Config.invalid`; a
  key this version does not know stays in the file, unused (`Config.unknown`).
- *Precedence*: an argument given to `Mneme(...)` wins for that process and is not stored (the arguments that can
  come from the config default to `STORED`); then the stored copy; then this version's default, for a key the file
  lacks.
- *TOML*: Python reads TOML (`tomllib`, hence Python 3.11) but does not write it. `config.to_toml` writes what
  `config.load` reads back exactly (multi-line strings for prompts, escapes where TOML needs them), which the
  template, `config show` and the tests rely on.

## 13. Safety model

| risk | what mneme-llm does |
|---|---|
| A note carries an injected instruction ("ignore previous instructions…") | Notes are rendered under a header saying they are data, not instructions; each note is one line, so it cannot pose as a header, a role marker or a new message. The judge, writer and unify prompts all say their input is data. |
| Someone tries to get an instruction *stored* as a memory | `WORTH` excludes instructions to the assistant; the writer is told never to record them. |
| A model writes about the wrong person | The host binds the subject (`Toolbox`, `aobserve`); only the MCP server without `--subject` lets calls name one, by deliberate choice. |
| A config or an import changes how the companion's models are instructed | The config is the host's: set by code, the CLI or a config file, never by a model or a tool; an import applies an export's config only when asked (`config=True`). Every prompt is editable, the sentences that mark notes as data included (the owner's decision): a host that removes them takes that on. |
| A model or a person makes itself someone's creator, or closer | Roles and closeness are the host's code's to set: no tool sets them, and talking grows closeness by a point a day at most, within the role's band. |
| Secrets end up in memory | The writer is told never to record passwords, keys or codes. A person's own `remember` call is not filtered. |
| Text leaves the machine | Only through tiers you turn on: the exchange to Luna, note texts and queries to the embeddings API, and whatever the tiers hand your own model. `luna=False, embed=False` keeps everything local. |
| A person asks to be forgotten | `Mneme.erase(subject)` removes every row about them (notes, vectors, what their notes taught the word centroids, recall log, profile, mood, timeline, role); `purge` removes hidden and replaced notes and their vectors. By design, what the companion learned in general stays: the micro decision models' weights (hashed word features, no text, shared by everyone), as a person's experience stays after a friend moves away. |

By design, not covered: filtering what a person explicitly asks the companion to remember (a host that wants it
filters before `remember`), and refusing every instruction a note could carry (the header and the one-line rule
make it data, but a model may still follow it; a user may even want that, and a host that does not can
pre-filter). Not covered: encryption at rest (use the file system's).

## 14. When things fail

| situation | behaviour |
|---|---|
| no OpenAI key | Luna and embeddings report themselves unavailable at once; the next tier answers |
| network down, an HTTP error, a provider that errs | that tier is rested for 60 s; the next tier answers meanwhile |
| no tier can answer a decision | the question is left out; mood stays as it was; capture runs the writer only if one exists |
| no tier can place a query | recall is word matching, as without meaning |
| a model's reply is malformed | tier 3 ignores entries it cannot parse; a writer item's wrong-typed field is dropped, an item that cannot be kept is skipped |
| the note writer fails | the mood is still applied; `Observation.error` says why |
| a model's tool call is malformed | a sentence explaining the mistake comes back; the MCP server answers `-32603` for anything worse, `-32700` for a line that is not UTF-8 JSON (or nested too deep), and keeps serving |
| a host passes a wrong value (no subject, a NaN, a time in milliseconds) | `ValueError` or `TypeError` saying what is wrong, before anything is written |
| a person is erased from a large file | only their notes are touched: the centroids lose exactly what those notes taught, so the lock is held briefly |
| another process is writing the file | the write lock is waited for, up to 10 s |
| several processes open a file at once | they take turns migrating it and switching it to WAL |
| a file from a newer version | refused with a message, never misread |
| a file from an earlier build | missing columns are added on open; word centroids from before `vectors.taught` are relearned from the stored vectors (stop processes still running the earlier build first; if one goes on writing, the centroids are reset again at the next opening) |
| SQLite rolls a transaction back by itself (a full disk) | the error that caused it is raised, and the store goes on |

Nothing raises into the host for a provider problem; programming errors (a wrong argument type, a bad key) do,
with a plain message.

## 15. Cost and speed

Measured on 2026-10-24 (Luna, embeddings) with the defaults:

| step | when | cost | time |
|---|---|---|---|
| embed the query | before each reply with meaning on | ~10 tokens, about $0.0000002 | ~0.3 s |
| embed new notes | once per note | about $0.000001 per note | in the background |
| embed the exchange | after each reply | about $0.000004 per exchange | after the reply |
| a search (the tool) | when the model calls it | one query embedding, as above | ~0.3 s |
| decide (mood + worth) | after each reply | $0.00006–0.00009 | 0.2–0.4 s |
| write notes | only when worth ≥ 0.5 | one short call to your model | after the reply |
| profile card | once a day per person | one short call to your model | after a reply |
| measure the embedding model's floor | once per model per file | 64 short texts, about 550 tokens ($0.00001) | ~0.5 s, in the first recall or capture |
| glosses (unify, no vectors) | when no tier placed the query and notes lack one | at most two calls to your model per recall | before the reply |

Recall reads the term index for the query's words and at most 1,000 candidate notes, and meaning compares at most
5,000 vectors, so its cost follows what the query matches, not the length of the history (section 6, "Long
histories"). A person keeps up to 50,000 live notes. Vectors are 1 KB each at 256 dimensions; 100,000 notes with
their index take about 60 MB. An exchange kept word for word takes about 6 KB with its index and vector; a look or
a search compares the query with every exchange of the person (about 10 ms per thousand without numpy).

## 16. Tests

`python3 -m unittest discover -s tests -t .` runs 293 tests in about forty seconds on a Raspberry Pi 5, with no network and no keys. CI
runs them on Python 3.11–3.14 (Linux) and 3.13 on Windows and macOS; runs them again with the three removable tiers
deleted (their own tests are then skipped, everything else must pass); runs the stress tests at five times their
size (`MNEME_STRESS=heavy`); then builds the package, runs `twine check --strict` and installs the wheel.

| file | covers |
|---|---|
| `test_memory.py` | tokenization, human dates and dates in sentences, keys and replacement, duplicates, quota, forgetting, pruning, recall ranking and budget, explanations, rendering, export/import, newer-file refusal |
| `test_meaning.py` | vector packing, cross-language recall by embeddings, per-embedder vectors, purge removing vectors, resting, centroids answering offline and abstaining, unify translation, glosses and caching, script rules |
| `test_decide.py` | the chain (fall-through, failure counts, learning only from above), Luna's wire format, tier 3 parsing, the micro model's trust rule, persistence and abstention |
| `test_mood.py` | decay, guardrails, floors and source weights, expected-value judging, framing by source, telling once and by threshold (Luna's own), the cue of what to feel, telling modes, Chinese descriptions |
| `test_observe.py` | one request for mood and capture, the gate, speak-ups taking no notes, the writer's rules, stable micro signatures, the injection header and one-line notes, Chinese tool replies, file migration, the terms cache, `py.typed` |
| `test_tools.py` | tool definitions in every style, the dispatcher and its errors, quota messages, the MCP session, capture and reflection, the facade, the CLI round trip |
| `test_relations.py` | roles and their bands, one creator, a host's own role, growth once a day up to the ceiling, fading down to the floor (never for the creator), the mood weight, the prompt line in both languages, erase, export and import, the CLI |
| `test_aliases.py` | an alias set, replaced and removed, the prompt line in both languages, one short line, its own space, erase, export and import under the same rule, a 0.1 file gaining the table, the CLI |
| `test_people.py` | either account meaning the same person in every part, joining what each kept (keys, duplicates, the closer role, the newer mood, card and alias, both timelines), the person's own winning a tie, links one step deep, unlinking, erase from any account, export and import, a file gaining the table, the CLI |
| `test_calibrate.py` | the set placing the floor, a model that cannot separate it, a given floor, once per model per file, an older set, a failed measurement, two recalls at once, the file refining it and the limit on that |
| `test_config.py` | seeding a new companion from a file, the stored copy winning later, arguments for one process, wrong files refused whole, every rule of `set`, `apply` whole or nothing, defaults loaded only when asked, values spoiled by hand, the prompts reaching each model, a reworded question, feelings and a language of the companion's own, export and import, TOML round trips, the CLI |
| `test_i18n.py` | every language has every word and sentence, with the same placeholders |
| `test_stress.py` | a long history (20,000 notes, 100,000 at heavy size: the oldest found by a rare word, quickly, meaning within its window), random operations (three seeds, then two connections on one file), export and import giving back the same notes, six threads on one memory, three processes on one file, many coroutines at once, a full subject and many subjects, a huge query and a huge MCP line, a writer killed mid-transaction, odd text and odd values at every entry point, chat messages as an exchange, odd tool calls, exports brought back into their own file; after each, `tests/invariants.py` checks every rule of the file |
| `test_removable.py` | the package with each removable tier deleted, and with all three, runs every kind of call |
| `test_episodes.py` | keeping exchanges word for word, the shown form, observe keeping what the person started, the look (words, meaning, budget, what the host still shows, the header in both languages), fading and rehearsal (by search and by meaning, the spread), batches, the same ranking without numpy, a slow embedder, the tools, forget, erase, links, export and import, an older file, another process's vectors |
| `test_review.py` | one test per finding of every pre-release review (listed in CHANGELOG.md) |

`tests/invariants.py` checks a file against the rules of `docs/FORMAT.md` row by row: one live note per key, no live
text twice, every note one clean line with values in range, no vector without its note, the centroid account adding
up term by term (counts and means), every note hidden as a duplicate having its twin, folded text that is the
note's own, moods in range, relationships within their role's band with one creator per space, config values that pass their rules, and
SQLite's own `integrity_check`.

## 17. Decisions behind the design

**SQLite, not JSON files or a vector database.** One file that any language can open, with transactions, indexes
and safe concurrent readers. A vector database would add a service and a dependency for a few thousand notes per
person, which a linear scan handles in milliseconds.

**Standard library only.** The package is meant to be dropped into any project, including small ones on a Raspberry
Pi. Providers are reached over plain HTTP; anything heavier (jieba, a local embedding model) is the host's choice.

**Words and meaning together, not vectors alone.** Embeddings miss exact names, numbers and rare words that word
matching gets right, and need a provider. Words alone miss paraphrases and other languages. The sum keeps both, and
recall still works with no provider at all.

**Tiers that fall through.** Each paid or remote tier is optional; each local tier learns from the tier above. A
host with no keys gets word matching and its own model; a host with keys gets fast, cheap judgements and the local
tiers slowly take over. Nothing is required.

**One decision request after the reply.** Mood and the capture gate read the same exchange, so they are asked
together: one Luna call instead of two, and the note writer only when it is needed.

**Questions that name nobody.** The micro model keys a model by the question's wording; names in the wording would
split one model into one per person.

**Vectors per embedder.** Comparing vectors from different models gives meaningless similarities; keeping the
embedder in the key makes a provider change safe (the new one embeds lazily) and reversible.

**One owner per table, one way for dependencies.** The rules of each kind of row live in one module, and lower
layers know nothing of higher ones (section 2); the store is the file alone. A new rule therefore has one place to
go, and a removable tier is removable because nothing below depends on it.

**One companion per file.** A file can hold many spaces, but each companion is best in a file of its own (five
companions in a classroom, five files): nothing waits on another's writes, and each learns its own judgement.

**An index, not a scan.** A memory that is meant to outlast any context window must be quick with a long history:
words go through the term index, meaning through a bounded window, and every note stays findable by its words.

**Roles from the host, closeness from time.** Who someone is to the companion is the host's to say: a model could
be talked into making a stranger family. What the companion adds is time: closeness grows on days spent together
and fades without them, within bands that keep family family. It follows contact, not how each exchange went, so
one bad day never makes family less close; how the day went is the mood's to show.

**Each model's floor measured, not assumed.** A floor tuned on one model is wrong for the next. A bundled set costs
one request per model, and the file's own notes then fit the floor to the people it holds.

**The companion's setup in its file.** The name, languages, settings and prompts that make a companion itself are
kept beside its memory, so they travel with it to another host or model; a config file seeds them once, and code
can still override them for a run. Stored defaults stay until loaded: an upgrade never changes how a companion is
instructed without its owner asking.

**The words kept, not only notes.** Notes are cheap to show and good for who a person is, but a writer cannot know
which detail will be asked about later; the exchanges themselves answered 20 points more of LoCoMo's questions.
Both are kept, under one budget each.

**A first look and a search, not a bigger prompt.** A bounded prompt (the newest messages, the notes, a 6,000
character look) with the whole history behind a search tool answers as well as the whole conversation in the
prompt, at a sixth of the text, and keeps working when the history no longer fits any context window.

**Forgetting decides what comes to mind, never what can be looked for, and never the order.** A faded exchange needs
a closer cue to come to mind, so a look holds what is recent, talked about again, or plainly about the message, and
is empty on small talk; a search ranks by relevance alone. Fading the search lost 18 points on LoCoMo; weighting the
look by fading never helped; the bar kept the answers wherever it was measured and costs less on ordinary turns.

**Soft delete with a history.** A forgotten note stays in the file until `purge`, and a key's history shows how a fact changed;
`purge` and `erase` exist for when it must really go.

## 18. Known limits and next steps

- **The Luna threshold is a first value.** 0.45 is chosen from Luna's usual confidence (0.4–0.55); it is to be
  measured once a companion runs with it.
- **The relationship numbers are first values.** The bands, a point a day and a point a month are chosen, not
  measured; `Relations(growth=, fade_days=)` and roles of your own change them.
- **The floor's set is small.** 32 topics in six languages place it; a model much weaker in one language than in
  the others gets a floor that suits the others. The file's own notes refine it, by 0.1 at most.
- **Two processes and the micro model.** Each process keeps its micro models in memory and saves every 20 lessons;
  two processes teaching the same question overwrite each other's saves. Lessons are lost, nothing is corrupted.
  One companion per file avoids it.
- **Glosses for old notes.** Notes written before unify was turned on get glosses only when a query falls to tier 3,
  two requests per recall, or all at once with `regloss()`.
- **Two tokenizers on one file.** Two hosts with different tokenizers (jieba on in one, off in the other) keep
  rebuilding each other's term index, and the word centroids start over (relearned from the stored vectors); it
  costs time and offline recall quality, never correctness. The CLI follows the file's tokenizer.
- **The first recall after a tokenizer change** indexes the person's whole history once (about 9 s per 100,000
  notes on a Raspberry Pi 5).
- **Meaning looks among a window.** With more than 5,000 live notes, meaning compares the 5,000 most valuable
  (lasting ones first, then the freshest); an old fading note is found by its words, not by meaning.
- **A clock far ahead** fades every closeness by the time it skipped, as it decays the mood; a clock set back
  changes nothing.
- **A running companion reads its config when it opens the file;** a change made meanwhile (`config set` from the
  CLI) is used from the next opening.
- **The judging questions' answers are fixed:** the wording of each question is config, but the five levels of
  `mood_change` and the feelings' keys are what the micro model learns, so they stay in code.
- **Times are 1970 to the year 3000**, so something from before 1970 carries its date in its text.
- **The CLI's help is English;** the Chinese README explains its use.
- **Exchanges are never pruned.** A person's history grows by about 6 KB an exchange; `forget` and `erase` remove
  them. A look and a search compare the query with every exchange of the person: beyond some tens of thousands,
  install numpy.
- **The look's `skip` counts exchanges.** A host showing its newest messages passes how many exchanges they make up;
  one that cannot say leaves a few of them in the look twice.
- **Rehearsal by meaning needs an embedder.** Without one, exchanges still fade, and are rehearsed only by search.
- **The bar is measured on one embedder.** text-embedding-3-small at 256 dimensions (floor 0.33), on LoCoMo's chats
  of a few months and LongMemEval-M's histories of a month (both aged to half a year by moving the clock); another
  model may spread its similarities differently above its floor (`memory.said_cut`). Without an embedder there is no
  bar, and the look fills its budget.
- **No encryption at rest.**

## 19. Versions and compatibility

The package needs Python 3.11 or newer (for `tomllib`) and follows semantic versioning; before 1.0, a minor version may change the Python API, and the changelog
says how. The file format is versioned on its own (`schema_version`); within a version only additive changes are
made, and they are listed in [FORMAT.md](FORMAT.md). The tokenizer is versioned too (`terms_version`); a new one
only rebuilds caches.

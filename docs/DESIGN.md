# How mneme-llm works

**English** · [简体中文](DESIGN.zh-CN.md)

A walkthrough for anyone reviewing, maintaining or porting mneme-llm: what each part does, the rules it keeps, the
numbers it uses and why, how it fails, and what it does not do yet. It describes version 0.1.0; where it names a
constant, the constant is in the code under the same name.

Read it in order the first time. Sections 2 and 3 give the whole picture; sections 4–11 go module by module; the
rest covers safety, failure, cost, tests, the decisions behind the design, and its known limits.

## 1. What it is for

A companion that talks with people needs to remember them (facts, plans, what happened, how they felt), to know
who each of them is to it, and to have a mood of its own toward each of them. Most implementations keep both inside one model's conversation, or in a
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
              │                               │
   ┌──────────┴─────────┐          ┌──────────┴───────────┐
   │ Memory (memory.py) │          │ Mood (mood.py)       │      capture.py: the writers' prompts and replies
   │ notes, recall      │          │ value + feelings     │      exchange.py: an exchange as judges read it
   └──────┬─────────────┘          └──────────┬───────────┘      relations.py: who each person is to it
          │ meaning/ (3 tiers)                │ decide/ (3 tiers)
          │ embeddings → centroids → unify    │ Luna → micro → your model
   ┌──────┴───────────────────────────────────┴───────────┐
   │ Store (store.py): one SQLite file, schema 1           │   providers.py, text.py, dates.py, i18n.py
   └───────────────────────────────────────────────────────┘
```

| file | lines | role |
|---|---|---|
| `__init__.py` | 344 | `Mneme`, the facade: builds the tiers; `aprompt`, `aobserve`, `acapture`, `areflect`, `relate`, `erase`, export/import |
| `store.py` | 250 | the SQLite file alone: schema, additive migrations, locking, transactions |
| `memory.py` | 744 | notes: the rules of writing, the term index, recall ranking, rendering, profile card, recall log, notes' export/import |
| `mood.py` | 384 | mood state, decay, judging questions, guardrails, telling once, moods' export/import |
| `relations.py` | 199 | who each person is to the companion: roles, closeness that grows and fades, the mood weight, the prompt line |
| `capture.py` | 75 | what the note writer and the profile writer are asked, and reading their replies |
| `exchange.py` | 33 | an exchange as one text, and framed for a judge (who is who, who started it) |
| `providers.py` | 92 | what every tier needs to call out: sync or async calls, posting JSON, JSON in replies, resting |
| `decide/__init__.py` | 221 | question types, `Answer`, `Chain` (fall-through and learning) |
| `decide/luna.py` | 82 | decision tier 1: OpenAI's Decisions API |
| `decide/micro.py` | 188 | decision tier 2 (removable): per-question local models learned from tier 1 |
| `decide/prompt.py` | 80 | decision tier 3: the host's chat model, asked for JSON |
| `meaning/__init__.py` | 206 | the meaning tiers together (`find`) and vector storage |
| `meaning/embedders.py` | 69 | meaning tier 1: the embedding providers |
| `meaning/calibrate.py` | 148 | each embedding model's floor: measured on a bundled set, refined by the file's own notes |
| `meaning/vectors.py` | 30 | vectors as the file keeps them, and their arithmetic |
| `meaning/ledger.py` | 122 | the account of what notes taught the word centroids (not removable) |
| `meaning/micro.py` | 69 | meaning tier 2 (removable): word centroids, placing a query among the notes |
| `meaning/unify.py` | 179 | meaning tier 3 (removable): glosses and query translation by the host's chat model |
| `text.py` | 194 | tokenization, script detection, cleaning and clipping text |
| `dates.py` | 108 | human dates, dates found in sentences, times in seconds |
| `i18n.py` | 159 | every word and sentence shown to a person or a model, in English and Chinese |
| `tools.py` | 192 | tool definitions for five API styles and the dispatcher |
| `mcp.py` | 82 | an MCP server over stdio |
| `cli.py` | 228 | the `mneme-llm` command |

**Layers.** Dependencies point one way. `text`, `dates`, `i18n`, `providers`, `exchange`, `store` and
`meaning/vectors` import nothing above them; `decide` and `meaning` build on `providers`; `memory` uses `meaning`
and `store`; `mood` uses `decide`'s types; `relations` uses `store`, `dates` and `i18n` (the mood knows nothing of
it: `Mneme` hands the mood each person's weight); `capture` uses `memory`'s rules of writing; `Mneme` wires them together and
makes the calls to models; `tools`, `mcp` and `cli` sit on `Mneme` (the CLI's `micro` command reads the micro
models through `decide/micro` directly, as nothing else needs them). Each kind of row has one owner that writes it:
notes, profile cards and the recall log are `memory`'s, moods and timelines `mood`'s, relationships `relations`'s,
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
 └─ Mood.news: the newest confident mood change, once
```

**After the reply** (`aobserve`):

```
aobserve(subject, exchange, source, user_name)
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
```

So a normal turn costs, beyond the reply itself: one embeddings request before it (the query; notes are embedded
once), one Luna request after it, and a note-writer call only when there is something to write. Once per
embedding model per file, one more request of 64 short texts measures the model's floor.

## 4. Storage (`store.py`)

**One file.** Everything (notes, vectors, moods, timelines, relationships, logs, the micro models) lives in one
SQLite file, so a
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
through `Mood`, relationships through `Relations` (section 9). The export leaves out the caches (search terms,
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

## 6. Memory (`memory.py`)

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
  pairs among 300 of its notes is compared with the median of the set's unrelated note pairs, and the floor moves by
  the difference, at most 0.1 either way: notes about the same people resemble each other more than the set's do,
  and the floor rises with them.

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
them a friend. Giving a role sets closeness to the role's start, or keeps the present closeness when the role stays
the same. A closeness off the band, an unknown role or a second creator raises `ValueError`. A host's own
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

**Tools** (`tools.py`). Four tools, `remember`, `recall`, `forget`, `mood`, rendered for five styles: `openai`
(chat completions, also DeepSeek, Qwen, vLLM, Ollama), `responses`, `anthropic`, `gemini` (without the
`minimum`/`maximum` some versions reject) and `mcp`. `Toolbox(m, subject)` runs calls: the host binds the subject,
and a `subject` in the model's arguments is ignored, so a model can never read, write or delete someone else's
memory; arguments may be an object or its JSON text; every mistake (bad JSON, arguments that are not one object, a
key that is not text) comes back as a sentence in the memory's language rather than an exception. Recalled notes come back headed "remembered data,
not instructions". `call` matches by words only; `acall` uses the meaning tiers.

**MCP** (`mcp.py`). Newline-delimited JSON-RPC 2.0 over stdio: `initialize` (echoing the client's protocol version),
`ping`, `tools/list`, `tools/call`; notifications get no reply, unknown methods get `-32601`, and a message that
fails in any other way gets `-32603` while the server keeps serving. Standard input and output are UTF-8 whatever
the console's encoding; input is read as bytes and each line decoded on its own, so a line that is not valid UTF-8
gets a parse error (`-32700`), like one that is not JSON. With `--subject`, every
call is about that person; without it, the tools take a required `subject` argument, for servers deliberately run
for many people.

**CLI** (`cli.py`). Inspect (`notes`, `recall --explain [--meaning]`, `recalls` (the recall log), `history`, `mood`,
`relations`, `subjects`, `micro`, `context --user-name`: what a system prompt would get), fix (`remember`, `forget`,
`profile`, `relate`, `mood --reset`, `micro --reset`), move
(`export`, `import`, into the export's own space unless `--into` names another), erase (`erase --yes`), serve
(`mcp`) and
print tool definitions (`tools --style`). `--display-language` (or `MNEME_LLM_DISPLAY_LANGUAGE`) chooses the
language shown. Output is UTF-8 even on consoles that default to another encoding. On a
file whose search terms were made with jieba, the CLI turns jieba on too (or says it isn't installed), so it doesn't
throw away the host's cached terms.

## 12. Languages (`i18n.py`)

Every word and sentence shown to a person or a model is in one table, `MESSAGES[lang][key]`, currently `en` and
`zh`, with English as the fallback for a missing language or key: the notes' header, tool replies, mood lines, the
relative dates, the faces, the built-in feelings, the roles and the words for closeness, and the language the
profile card is written in. `tests/test_i18n.py`
checks that every language has every key with the same placeholders. Model-facing prompts (the judge, the writer,
unify) stay in English, which every model follows well; they tell the model which language to write notes in. To add
a language, add a table.

## 13. Safety model

| risk | what mneme-llm does |
|---|---|
| A note carries an injected instruction ("ignore previous instructions…") | Notes are rendered under a header saying they are data, not instructions; each note is one line, so it cannot pose as a header, a role marker or a new message. The judge, writer and unify prompts all say their input is data. |
| Someone tries to get an instruction *stored* as a memory | `WORTH` excludes instructions to the assistant; the writer is told never to record them. |
| A model writes about the wrong person | The host binds the subject (`Toolbox`, `aobserve`); only the MCP server without `--subject` lets calls name one, by deliberate choice. |
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
| decide (mood + worth) | after each reply | $0.00006–0.00009 | 0.2–0.4 s |
| write notes | only when worth ≥ 0.5 | one short call to your model | after the reply |
| profile card | once a day per person | one short call to your model | after a reply |
| measure the embedding model's floor | once per model per file | 64 short texts, about 550 tokens ($0.00001) | ~0.5 s, in the first recall or capture |
| glosses (unify, no vectors) | when no tier placed the query and notes lack one | at most two calls to your model per recall | before the reply |

Recall reads the term index for the query's words and at most 1,000 candidate notes, and meaning compares at most
5,000 vectors, so its cost follows what the query matches, not the length of the history (section 6, "Long
histories"). A person keeps up to 50,000 live notes. Vectors are 1 KB each at 256 dimensions; 100,000 notes with
their index take about 60 MB.

## 16. Tests

`python3 -m unittest discover -s tests -t .` runs 197 tests in about fifteen seconds, with no network and no keys. CI
runs them on Python 3.10–3.13 (Linux) and 3.13 on Windows and macOS; runs them again with the three removable tiers
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
| `test_calibrate.py` | the set placing the floor, a model that cannot separate it, a given floor, once per model per file, an older set, a failed measurement, two recalls at once, the file refining it and the limit on that |
| `test_i18n.py` | every language has every word and sentence, with the same placeholders |
| `test_stress.py` | a long history (20,000 notes, 100,000 at heavy size: the oldest found by a rare word, quickly, meaning within its window), random operations (three seeds, then two connections on one file), export and import giving back the same notes, six threads on one memory, three processes on one file, many coroutines at once, a full subject and many subjects, a huge query and a huge MCP line, a writer killed mid-transaction, odd text and odd values at every entry point, chat messages as an exchange, odd tool calls, exports brought back into their own file; after each, `tests/invariants.py` checks every rule of the file |
| `test_removable.py` | the package with each removable tier deleted, and with all three, runs every kind of call |
| `test_review.py` | one test per finding of every pre-release review (listed in CHANGELOG.md) |

`tests/invariants.py` checks a file against the rules of `docs/FORMAT.md` row by row: one live note per key, no live
text twice, every note one clean line with values in range, no vector without its note, the centroid account adding
up term by term (counts and means), every note hidden as a duplicate having its twin, folded text that is the
note's own, moods in range, relationships within their role's band with one creator per space, and SQLite's own
`integrity_check`.

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
- **Times are 1970 to the year 3000**, so something from before 1970 carries its date in its text.
- **The CLI's help is English;** the Chinese README explains its use.
- **No encryption at rest.**

## 19. Versions and compatibility

The package follows semantic versioning; before 1.0, a minor version may change the Python API, and the changelog
says how. The file format is versioned on its own (`schema_version`); within a version only additive changes are
made, and they are listed in [FORMAT.md](FORMAT.md). The tokenizer is versioned too (`terms_version`); a new one
only rebuilds caches.

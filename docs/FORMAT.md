# The mneme-llm file format (schema 2)

**English** · [简体中文](FORMAT.zh-CN.md)

A mneme-llm file is an SQLite 3 database. This page is enough to read and write one from any language. The Python
package is one implementation; nothing below depends on it.

Times are Unix seconds (floating point, UTC). Text is UTF-8. Vectors are little-endian float32 arrays, normalized
to length 1. `meta.schema_version` is `2`: a reader must refuse a file of any other version.
`python -m mneme_llm.migrate FILE` makes a file of schema 1 current.

## Tables

### `memories`: the notes

| column | type | meaning |
|---|---|---|
| `id` | integer | primary key |
| `space` | text | whose memory (an app or character) |
| `subject` | text | who the note is about |
| `key` | text, null | what it is about, lowercase, `part(.part){0,3}`, at most 48 characters; never the value |
| `kind` | text | `fact`, `preference`, `episode`, `plan` or `reflection` |
| `text` | text | the note, one line, at most 500 characters |
| `importance` | integer | 1 (trivial) … 5 (core: always in context) |
| `feeling` | real | −1 … 1, how the subject felt about it (0: neutral or unknown) |
| `happened_at` | real | when it happened (for a plan: the day it happens) |
| `created_at` | real | when it was written |
| `recalled_at` | real, null | the last time it was recalled by evidence |
| `recalls` | integer | how many times |
| `superseded_by` | integer, null | the id of the note that replaced it (same key) |
| `deleted_at` | real, null | when it was forgotten |
| `source` | text, null | who wrote it: `auto` (a model, unprompted), `user`, `cli`, `core-diary`… |
| `gloss` | text, null | the note in the unifying language (meaning tier 2), when one was written |
| `folded` | text | `text` with Unicode full case folding (and `i` + U+0307 read as `i`), for duplicate checks |

A note is **live** when `superseded_by` and `deleted_at` are both null. Writing a note with a key sets
`superseded_by` on the live note of the same `(space, subject, key)`, so there is at most one live note per key.
`text` and `gloss` never contain line breaks (whitespace is collapsed on write).

Two live notes of a subject never have the same `folded` unless both have keys and the keys differ.

### `vectors`: meaning tier 1

`(memory_id, embedder)` primary key; `vector` (blob). `embedder` names the model and its settings
(`openai:text-embedding-3-small:256`); vectors from different embedders are never compared. A vector is stored only
if the note still exists with the text that was embedded (ids of deleted notes are reused), and a writer inserting a
note deletes any vector rows left under its id. Rows of notes that no longer exist are deleted on `purge` and
`erase`.

### `profiles`: the impression card

`(space, subject)` primary key, `text`, `updated_at`. A few sentences, shown above the notes.

### `moods`: the current state

`(space, subject)` primary key; `value` (0–100 when written); `emotions` (JSON object, feeling → intensity 0–100);
`updated_at`; `last_event` (id in `mood_events`); `told_event` (the last event told to the model).

The stored values are as of `updated_at`. To read the state at time *t*, with *h* = hours since `updated_at`:

    value(t)   = baseline + (value − baseline) · 0.5^(h / 3)
    emotion(t) = emotion · 0.5^(h · 60 / 90)

The baseline (70) and both half-lives are settings, not part of the file.

### `mood_events`: the timeline

`id`, `space`, `subject`, `at`, `delta` (the change actually applied), `value` (after it), `emotions` (JSON: what
this event added), `reason` (what moved it, in the display language: the judge's sentence, or the person's quoted
words; the feeling is told from `emotions`), `confidence` (0–1), `source` (`user`, `speak-up`, `duty`, `manual`…),
`judge` (who answered: `prompt` for the host's chat model, or what a judge of the host's own put in its answers).

### `relationships`: who each person is to the companion

`(space, subject)` primary key; `role` (`creator`, `family`, `friend`, `acquaintance`, or a host's own); `closeness`
(0–100, as of `updated_at`); `since` (when the role was given); `updated_at` (when closeness was last written: the
role given, or a day of contact).

At most one `creator` per space. With the built-in bands, closeness stays within the role's: creator 80–100, family
60–100, friend 20–90, acquaintance 0–60. To read it at time *t*, with *d* = days since `updated_at`:

    closeness(t) = min(ceiling, max(floor, closeness − d / 30))       (the creator's does not fade: d = 0)

The band is the role's as the host has it when the value is read, so a narrowed band holds the people already
in it. A contact on a later talking day than `updated_at` (see `episodes.day`) adds 1, up to the role's ceiling; a
contact at a time before `updated_at` (a clock set back) changes nothing. The rates,
the bands and the zone are settings, not part of the file.

### `aliases`: what each person calls the companion

`(space, subject)` primary key; `alias` (one line, at most 40 characters, never blank); `updated_at` (when it was
set). A person without an alias has no row.

### `people`: one person under several subjects

`(space, subject)` primary key; `person` (the subject the person's rows are kept under). A row says that `subject` is
`person`: every reader and writer takes `person` wherever it is given `subject`, so no other table keeps rows under a
linked subject. A link is one step deep: `person` is never itself linked, and never equals `subject`. Linking moves
what was kept under `subject` to `person`: its notes, term index rows and recall log (then, as after an import, one
live note per key, the newest, and no live text twice), its mood timeline, its exchanges with their index and spread;
of two profile cards, moods (with their event links) or aliases the newer `updated_at` is kept, of two relationships
the closer one now (the person's own when equal), with the earlier `since`, and of two Character Cards the person's
own. Two surfaces become one (see `surfaces`). A subject without a row is its own person.

### `note_terms`: the term index

`(space, subject, term, memory_id)` primary key. A live note's rows are exactly the search terms of its text, its
key's parts and its gloss, one row each. A writer that changes any of those replaces the note's rows, one that deletes
a note deletes them, and one that inserts a note under a reused id first deletes any rows left under it.
`meta.terms_version` names the tokenizer that made this table and `episode_terms`: a writer with another tokenizer
rebuilds both from the text before it searches them, and sets it. Readers that do not use the index can ignore it, but
writers must keep it.

### `episodes`: what was said, word for word

| column | type | meaning |
|---|---|---|
| `id` | integer | primary key, autoincrement: an id is never used twice, which `surfaces.start_id` relies on |
| `space` | text | whose memory |
| `subject` | text | who the exchange was with (the person, as for notes) |
| `at` | real | when it was said |
| `day` | integer | its talking day: the calendar day of `at − 4 hours` in the companion's zone, as a Gregorian ordinal (1 January of year 1 is 1), set when it is kept |
| `conversation` | text | where: the host's name for the chat (`""` for none), at most 200 characters |
| `lines` | text | JSON `[[who, said], …]`: the exchange in order, at most 40 lines; `who` one line of at most 80 characters (`""` for nobody in particular), `said` at most 8,000 characters (the opening and the end of a longer one) |
| `size` | integer | how many distinct search terms it has (BM25's length) |
| `tokens` | real | about what a model counts in it: 0.85 a character of Chinese, Japanese or Korean and 0.3 of anything else in its lines written as `who: said`, one per line, plus 2.4; set when it is kept |
| `stability` | real | S, in days: how slowly it fades (30 to start, at most 1,000,000) |
| `recalled_at` | real, null | when it was last rehearsed |
| `recalls` | integer | how many times |

An exchange's retention is `R = exp(−d / stability)`. Its last day is the talking day of `max(at, recalled_at)`; `d` is
0 on that day, and later 1 plus the subject's talking days (the distinct values of `day`) after it and before today.
A rehearsal on a later talking day than the last one sets `stability` to `stability · (1.5 + 3 · (1 − R))`, at most
1,000,000, and `recalled_at` to its time (the later of the two); a second one that day changes nothing.
An exchange is rehearsed when a search finds it, and when a later exchange of the same subject is among the three
nearest to it in meaning and closer than the subject's spread (`episode_spread`) puts 98% of pairs. Its search terms
are those of what its lines said, not who said them. Exchanges are deleted outright (`forget`, `erase`), with their
`episode_terms` and `episode_vectors` rows.

### `episode_terms`, `episode_vectors`, `episode_spread`

`episode_terms` is the exchanges' term index, kept like `note_terms`: `(space, subject, term, episode_id)` primary
key, one row per distinct term of the exchange, and an index on `episode_id`. `episode_vectors` holds meaning tier
1's vectors of exchanges: `(episode_id, embedder)` primary key, `vector` (blob). What is embedded is the exchange
under its date in words, `[08 May 2023, 13:56]`, then its lines as `who: said`. `episode_spread` is, per
`(space, subject, embedder)`, a histogram of the similarities of every pair of the subject's exchanges with a
vector: `bins` (JSON list of 200 counts; bin `i` holds similarities from `−1 + i/100`) and `pairs` (their sum). A
pair is counted when the second of the two gets its vector; a subject rehearses by meaning only once it has 100
pairs.

### `links`: what reminds her of what

Two exchanges of one subject that came to mind together. `(space, a, b)` primary key, `a < b`: the two `episodes.id`;
`subject` (whose they are: a link never joins two subjects); `closeness` (the cosine of their vectors when the link
was born of one reminding her of the other; 0 when it was born otherwise); `day` (the talking day it was born or last
used, counted as `episodes.day` is); `stability` (S, in talking days: 30 to start, at most 1,000,000); `uses` (how many
times it was used). Its strength is R = e^(−t/S), t the subject's talking days after `day` up to today (today counting
as one); its weight R × (1 + `uses`). A use counts at most once a talking day: `day` becomes today, `uses` grows by 1
and S becomes S × (1.5 + 3 × (1 − R)). An exchange keeps at most 8 links, the heaviest. At a subject's first exchange
of a talking day, their links with R under 0.05, and any link to an exchange that is gone, are deleted. Deleting an
exchange deletes its links; erasing a subject, theirs; linking `old` to `person` sets `subject` to the person. The
export leaves links out. The table came within schema 2: a writer creating the tables makes it, and a reader that
does not know it leaves it alone. A writer that deletes exchanges should delete their rows here too, and one that
erases a subject, the subject's: a link left to an exchange that is gone is deleted only at that subject's next
talking day.

### `surfaces`: where the newest part of the exchanges starts

`(space, subject)` primary key; `start_id` (the surface is the subject's exchanges with an `id` above it);
`cleared_at` (when it was last cleared, just after the latest `at` of the subject's exchanges, or the `at` of the first
exchange that stayed when the older part became a summary); `summary` (what stands for what left, at most 8,000
characters, `""` for none). A subject without a row has all their exchanges on it. Nothing is kept here but the start:
its turns are the exchanges themselves, read by `id`, newest first, and shown in the order of `at`.

Linking `old` to `person` when `old` has a row or any exchange: the lower `start_id` and `cleared_at` stay (no row
counts as 0), the summaries are joined and cut to 8,000 characters, and a row with neither a start nor a summary goes.

### `first_prompts`: the Character Card

Named before 0.7, when it was the first prompt. `(space, subject)` primary key; `text` (at most 8,000 characters; at
first the first thing the person said; `""` once dropped, so the next message does not take its place: there is no card,
but the row stays until `erase`); `at`; `by_command` (1 when it was set, not only the first thing said); `send` (1 when
it is on: the host puts it in its system prompt).

### `recalls`: the recall log

`id`, `space`, `subject`, `at`, `query`, `chosen` (JSON `[[id, why], …]`), `skipped` (JSON `[[id, reason], …]`).
The newest 200 per subject are kept.

### `config`: the companion's config

`(space, key)` primary key; `value` (JSON); `origin` (`default`, `file`, `set` or `import`); `updated_at`. Keys
are flat: `companion.name`, `companion.display_language`, `companion.memory_language` (`""`: no unifying language),
`companion.zone` (`""`, `UTC+8`, or an IANA name), `memory.*`, `mood.*` (the mood's settings), `relations.liking`,
`relations.growth` (read from older files, no longer used), `relations.fade_days` and `relations.locked` (a table of subject to closeness, locked by hand), `roles` and `emotions` (each a list of objects, in full), `prompts.<name>` (an
instruction to a model) and `messages.<language>.<key>` (a sentence shown). `mneme-llm config template` prints
every key with its default; `docs/DESIGN.md`, section 12, gives the rules.

A space's rows are written whole the first time the space is opened (the defaults, then the config file over
them), and change only when a host sets, applies or loads defaults. In prompts and sentences, `{name}` is a
placeholder, and a text may use only those of its default; any other brace is literal. A reader that finds a value
it cannot accept should use its own default for that key and say so; a key it does not know is left as it is.

### `meta`

`key`, `value`. Holds `schema_version`, `terms_version` (see `note_terms`), `floor:<embedder>` and `adopted:…` flags
hosts may set.

`floor:<embedder>` is a JSON object: what was measured for that embedding model in this file. `floor` is the
similarity under which a note says nothing about a query; `version` is the bundled set's (a record of another
version is measured again); `separated` says whether the set's related pairs stood clearly above its unrelated
ones (if not, `floor` is the default); `set` holds the set's `floor`, the related pairs' lower quartile
(`related`), the unrelated pairs' 95th percentile (`unrelated`) and the median similarity of its unrelated note pairs
(`background`); `file` is null, or the highest note id when the file's own notes were last compared (`at`), how many
were compared (`notes`) and, when there were enough, their median similarity (`background`) and the move it made
(`shift`).

## Export format

`Mneme.export_data()` / `mneme-llm export` writes one JSON object:

```json
{"mneme_llm": 2, "space": "dafeiyu", "exported_at": 1792885075.5,
 "memories": [{"id": 1, "subject": "discord:42", "key": "pet.name", "kind": "fact", "text": "…", "gloss": null, …}],
 "profiles": [...], "moods": [...], "mood_events": [...], "relationships": [...], "aliases": [...],
 "people": [...], "episodes": [{"id": 1, "subject": "discord:42", "at": 1792885000.0, "conversation": "dm",
 "lines": [["Leo", "…"], ["大肥鱼", "…"]], "stability": 30.0, "recalled_at": null, "recalls": 0}],
 "surfaces": [{"subject": "discord:42", "cleared_at": 1792885000.0, "summary": "…"}],
 "first_prompts": [{"subject": "discord:42", "text": "…", "at": 1792880000.0, "by_command": 0, "send": 0}],
 "config": [{"key": "companion.name", "value": "大肥鱼", "origin": "file"}, …]}
```

Rows are the table rows as objects, without `folded` (an exchange's `lines` as a list, without `size`, `day` and
`tokens`; a surface without `start_id`, as ids mean nothing in another file). Vectors, floors and spreads are not
exported: they belong to an embedder, and are rebuilt or measured again on use. On import, memory ids are
renumbered and `superseded_by` links follow the new numbers; each note is held to the rules of writing (one line
of at most 500 characters, whitespace collapsed; a key lowercased, or dropped when it isn't `part(.part){0,3}` of
at most 48 characters; an unknown kind read as `episode`; importance clamped to 1–5, feeling to −1…1 and `recalls` to 0 or more; times
that are not seconds between 1970 and the year 3000 replaced (`created_at` by now, the others by `created_at`); a
`source` that is not text dropped; a row that is not an object, or a note
without text or subject skipped); then, per subject, the newest live note of each key
stays live and the others point to it, and a live text that appears twice (compared case-folded) keeps a copy with
a key, or else the first copy (the others are marked deleted). Moods are imported
without their event links (the timeline is imported separately); an event identical to one already in the timeline
is not added again. A relationship replaces the person's present one, its closeness kept within the role's band
(0–100 for a role the host does not have); a second holder of a one-person role (a second creator) is skipped.
An exchange is held to the rules of keeping (its lines as above, `at` a time in seconds, `stability` a positive
number, else 30; one without a subject, a time or words is skipped) and gets a new id, day and tokens; one already
there (same person, time, conversation and words) is not added again. A surface starts at the subject's latest
exchange said before its `cleared_at`, and one that is there already joins it as a link does; a Character Card that is
there stays, and a dropped one (`""`) stays dropped.
Links are added as by linking (a subject the file already links to another person keeps its link), and then what
the import put under any linked subject joins its person. The config is applied only when the importer asks for it (its prompts are instructions to the importer's models),
row by row, a row with an unknown key or a value that does not pass skipped.

## Search terms

To match the Python implementation's recall (tokenizer version `4`), the text is first normalized: NFKC, Unicode
full case folding (with `i` + U+0307 read as `i`, so Turkish *İ* matches *i*), U+2019 read as an apostrophe, and the
Hebrew points (U+0591–U+05C7) and Arabic vowel marks (U+064B–U+065F, U+0670) removed.
A term is then one of:

- a word: a run of letters, digits and combining marks of any alphabet (Unicode categories L, N and M) and `_`,
  with apostrophes allowed between two of them; leading and trailing `'`, `_` and `-` stripped, a final `'s`
  dropped, then two or more characters, common English function words dropped; on ASCII words, a plural `s`/`ies`
  is trimmed;
- in a run of Chinese, Japanese or Korean characters, or of a script written without spaces (Thai, Lao, Khmer,
  Burmese), each overlapping pair of characters (common function pairs such as 我们 and 什么 dropped) and each
  single character (common function characters such as 的 and 了, and combining marks, dropped).

Each distinct term counts once per text. With jieba installed and enabled, jieba's words of two or more
characters are added to CJK runs (version `4+jieba`). Other
implementations may tokenize differently; that changes only which notes a query finds, never what is stored.

## Indexes

None of them changes what a file means; a writer creating the tables makes them all: `memories_live` on
`(space, subject, deleted_at, superseded_by)`, `memories_key` on `(space, subject, key)`, `memories_folded` on
`(space, subject, folded)`, `memories_newest` on `(space, subject, id)`, `memories_important` on
`(space, subject, importance, id)`, `recalls_subject` on `(space, subject, at)`, `mood_events_subject` on
`(space, subject, at)`, `people_person` on `(space, person)`, `note_terms_memory` on `memory_id`, `episodes_subject` on
`(space, subject, at)`, `episodes_conversation` on `(space, subject, conversation, at)`, `episodes_day` on
`(space, subject, day)`, `episodes_newest` on `(space, subject, id)`, `episode_terms_episode` on `episode_id`,
`links_b` on `(space, b)` and `links_subject` on `(space, subject)`.

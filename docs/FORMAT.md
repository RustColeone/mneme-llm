# The mneme-llm file format (schema 1)

**English** · [简体中文](FORMAT.zh-CN.md)

A mneme-llm file is an SQLite 3 database. This page is enough to read and write one from any language. The Python
package is one implementation; nothing below depends on it.

Times are Unix seconds (floating point, UTC). Text is UTF-8. Vectors are little-endian float32 arrays, normalized
to length 1. `meta.schema_version` is `1`: a reader must refuse a file with a higher version than it knows, and
may migrate a lower one. Columns added within a version are listed under [Changes within schema 1](#changes-within-schema-1);
a writer opening an older file adds them.

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
| `gloss` | text, null | the note in the unifying language (meaning tier 3), when one was written |
| `terms` | text, null | a cache: the note's search terms, space-separated; may be null at any time |
| `folded` | text, null | a cache: `text` with Unicode full case folding (and `i` + U+0307 read as `i`), for duplicate checks; may be null |

A note is **live** when `superseded_by` and `deleted_at` are both null. Writing a note with a key sets
`superseded_by` on the live note of the same `(space, subject, key)`, so there is at most one live note per key.
`text` and `gloss` never contain line breaks (whitespace is collapsed on write).

`terms` belongs to the tokenizer that wrote it (`meta.terms_version`); a reader with a different tokenizer sets
every `terms` to null (and empties `note_terms`) and rebuilds them on use. Writers that change `text`, `gloss` or
`key` set `terms` to null and delete the note's `note_terms` rows.
`folded` is filled in on write; a writer comparing texts fills in any null `folded` of the subject first. Two live
notes of a subject never have the same `folded` unless both have keys and the keys differ.

### `vectors`: meaning tier 1

`(memory_id, embedder)` primary key; `vector` (blob); `taught` (text, null: the terms this vector taught the word
centroids, space-separated, possibly empty; null when it has taught nothing). `embedder` names the model and its settings (`openai:text-embedding-3-small:256`); vectors
from different embedders are never compared. Rows of notes that no longer exist are deleted on `purge` and
`erase`.

### `meaning_terms`: meaning tier 2

`(embedder, term)` primary key; `count` (how many learned notes contained the term); `vector` (blob: the running
mean of those notes' vectors, not renormalized). Only notes are learned, never queries. `meta."meaning_texts:<embedder>"`
counts the notes learned, always the number of that embedder's vectors whose `taught` is not null (a reader that
finds otherwise, or finds terms with nothing taught, resets that embedder's centroids), and `meta."meaning_version:<embedder>"` names the tokenizer that split their
terms; with another tokenizer the rows are not used, and the next lesson deletes them first.

A writer teaching a note adds, in one transaction, the vector row, each term's new running mean, and the terms in
`taught`; and only if the note still exists with the text that was embedded (ids of deleted notes are reused)
and had no vector from that embedder. A writer inserting a note deletes any vector rows left under its id. A writer that deletes a note
takes back each of its vectors' lessons first: for each term in `taught`, `count` drops by one and the mean becomes
`(mean · count − vector) / (count − 1)`, the row going when `count` reaches 0; `meaning_texts` drops by one. This
needs no tokenizer. Implementations that don't run this tier must still do it when they delete notes, or a deleted
note's words stay in the file. Resetting an embedder's centroids deletes its rows and both meta keys and sets its
vectors' `taught` to null; such vectors are taught again from the file.

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
`judge` (the tier or tiers that answered, the one whose confidence counted first: `luna`, `luna+prompt`).

### `relationships`: who each person is to the companion

`(space, subject)` primary key; `role` (`creator`, `family`, `friend`, `acquaintance`, or a host's own); `closeness`
(0–100, as of `updated_at`); `since` (when the role was given); `updated_at` (when closeness was last written: the
role given, or a day of contact).

At most one `creator` per space. With the built-in bands, closeness stays within the role's: creator 80–100, family
60–100, friend 20–90, acquaintance 0–60. To read it at time *t*, with *d* = days since `updated_at`:

    closeness(t) = min(ceiling, max(floor, closeness − d / 30))       (the creator's does not fade: d = 0)

The band is the role's as the host has it when the value is read, so a narrowed band holds the people already
in it. A contact on a later day than `updated_at` (in the companion's zone) adds 1, up to the role's ceiling; a
contact at a time before `updated_at` (a clock set back) changes nothing. The rates,
the bands and the zone are settings, not part of the file.

### `aliases`: what each person calls the companion

`(space, subject)` primary key; `alias` (one line, at most 40 characters, never blank); `updated_at` (when it was
set). A person without an alias has no row.

### `people`: one person under several subjects

`(space, subject)` primary key, and an index on `(space, person)`; `person` (the subject the person's rows are kept
under), `updated_at` (when it was linked). A row says that `subject` is `person`: every reader and writer takes
`person` wherever it is given `subject`, so no other table keeps rows under a linked subject. A link is one step
deep: `person` is never itself linked, and never equals `subject`. Linking moves what was kept under `subject` to
`person`: its notes, term index rows and recall log (then, as after an import, one live note per key, the newest,
and no live text twice), its mood timeline; of two profile cards, moods (with their event links) or aliases the
newer `updated_at` is kept, and of two relationships the closer one now (the person's own when equal), with the
earlier `since`. A subject without a row is its own person.

### `note_terms`: the term index

`(space, subject, term, memory_id)` primary key, and an index on `memory_id`. A note's rows are exactly the terms
in its `memories.terms`, one row each; a note whose `terms` is null has none. A writer that sets `terms` to null (a
new gloss, a new key, another tokenizer) deletes the note's rows, a writer that deletes a note deletes them too,
and one that inserts a note under a reused id first deletes any rows left under it. Readers that do not use the
index can ignore it, but writers must keep it.

### `episodes`: what was said, word for word

| column | type | meaning |
|---|---|---|
| `id` | integer | primary key |
| `space` | text | whose memory |
| `subject` | text | who the exchange was with (the person, as for notes) |
| `at` | real | when it was said |
| `conversation` | text | where: the host's name for the chat (`""` for none), at most 200 characters |
| `lines` | text | JSON `[[who, said], …]`: the exchange in order, at most 40 lines; `who` one line of at most 80 characters (`""` for nobody in particular), `said` at most 8,000 characters (the opening and the end of a longer one) |
| `size` | integer | how many distinct search terms it has (BM25's length) |
| `stability` | real | S, in days: how slowly it fades (30 to start, at most 1,000,000) |
| `recalled_at` | real, null | when it was last rehearsed |
| `recalls` | integer | how many times |
| `terms` | text, null | a cache: its search terms, space-separated |

An exchange's retention at a time `t` is `R = exp(−(t − max(at, recalled_at)) / (stability · 86400))`. A rehearsal
at `t` sets `stability` to `stability · (1.5 + 3 · (1 − R))` and `recalled_at` to `t` (the later of the two).
An exchange is rehearsed when a search finds it, and when a later exchange of the same subject is among the three
nearest to it in meaning and closer than the subject's spread (`episode_spread`) puts 98% of pairs. Its search terms
are those of each line's `who` and `said` together. Exchanges are deleted outright (`forget`, `erase`), with their
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

### `recalls`: the recall log

`id`, `space`, `subject`, `at`, `query`, `chosen` (JSON `[[id, why], …]`), `skipped` (JSON `[[id, reason], …]`).
The newest 200 per subject are kept.

### `micro_models`: decision tier 2

`question` (primary key: `name:sha1(type|instructions|labels…|tokenizer version)[:12]`), `kind`, `labels` (JSON list), `weights`
(JSON `{"bias": [...], "w": {"feature": [...]}, "window": [0/1…]}`), `examples`, `updated_at`. Features are CRC-32
hashes of search terms, masked to 18 bits. Implementations that don't run the micro model can ignore this table.

### `config`: the companion's config

`(space, key)` primary key; `value` (JSON); `origin` (`default`, `file`, `set` or `import`); `updated_at`. Keys
are flat: `companion.name`, `companion.display_language`, `companion.memory_language` (`""`: no unifying language),
`companion.zone` (`""`, `UTC+8`, or an IANA name), `memory.*`, `mood.*` (the mood's settings), `relations.growth`
and `relations.fade_days`, `roles` and `emotions` (each a list of objects, in full), `prompts.<name>` (an
instruction to a model) and `messages.<language>.<key>` (a sentence shown). `mneme-llm config template` prints
every key with its default; `docs/DESIGN.md`, section 12, gives the rules.

A space's rows are written whole the first time the space is opened (the defaults, then the config file over
them), and change only when a host sets, applies or loads defaults. In prompts and sentences, `{name}` is a
placeholder, and a text may use only those of its default; any other brace is literal. A reader that finds a value
it cannot accept should use its own default for that key and say so; a key it does not know is left as it is.

### `meta`

`key`, `value`. Holds `schema_version`, `terms_version`, `meaning_texts:<embedder>`, `meaning_version:<embedder>`,
`floor:<embedder>` and `adopted:…` flags hosts may set.

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
{"mneme_llm": 1, "space": "dafeiyu", "exported_at": 1792885075.5,
 "memories": [{"id": 1, "subject": "discord:42", "key": "pet.name", "kind": "fact", "text": "…", "gloss": null, …}],
 "profiles": [...], "moods": [...], "mood_events": [...], "relationships": [...], "aliases": [...],
 "people": [...], "episodes": [{"id": 1, "subject": "discord:42", "at": 1792885000.0, "conversation": "dm",
 "lines": [["Leo", "…"], ["大肥鱼", "…"]], "stability": 30.0, "recalled_at": null, "recalls": 0}],
 "config": [{"key": "companion.name", "value": "大肥鱼", "origin": "file"}, …]}
```

Rows are the table rows as objects, without `terms` and `folded` (an exchange's `lines` as a list, without `size`
and `terms`). Vectors, word centroids, floors, spreads and micro models are not exported: they belong to an embedder and a tokenizer, and are rebuilt or measured again on use. On import, memory ids are
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
number, else 30; one without a subject, a time or words is skipped) and gets a new id.
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

## Changes within schema 1

Files written before these were added open as before; a writer adds the missing parts:

- `memories.gloss`, `memories.terms` and `memories.folded` (columns), and the index `memories_folded` on
  `(space, subject, folded)`;
- `vectors` and `meaning_terms` (tables), and `vectors.taught` (column) with the index `vectors_untaught` on
  `embedder` where `taught` is null. In a file from before `vectors.taught`, no vector has taught anything while
  `meaning_texts` says otherwise, so the first reader resets those centroids (they may hold words of queries and
  can't be taken back) and relearns them from the stored vectors;
- `note_terms` (table) with the index `note_terms_memory`, and the indexes `memories_newest` on
  `(space, subject, id)` and `memories_important` on `(space, subject, importance, id)`. A file from before the
  term index has every note's `terms` null or not; those not null are indexed when first needed (a reader indexes
  any live note of a subject whose `terms` is null, or that has terms but no rows, before using the index);
- `relationships` (table), and the `floor:<embedder>` keys in `meta`. A file without them has no roles (everyone
  counts as before) and floors not yet measured;
- `config` (table). A space without rows takes its config (the defaults and the host's config file) the next time
  it is opened;
- `aliases` (table, mneme-llm 0.2). A file without it has no aliases; mneme-llm 0.1 opens a file that has it and
  leaves the table alone;
- `people` (table) with the index `people_person` (mneme-llm 0.2). A file without it links no one. mneme-llm 0.1
  opens a file that has it but does not read it: a linked subject is then its own person again, without its
  notes;
- `episodes`, `episode_terms`, `episode_vectors` and `episode_spread` (tables), with the indexes
  `episodes_subject`, `episodes_conversation` and `episode_terms_episode` (mneme-llm 0.3). A file without them has
  no exchanges kept; mneme-llm 0.1 and 0.2 open a file that has them and leave them alone (their `erase` then
  leaves a person's exchanges in the file).

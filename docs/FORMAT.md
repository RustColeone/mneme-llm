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

A note is **live** when `superseded_by` and `deleted_at` are both null. Writing a note with a key sets
`superseded_by` on the live note of the same `(space, subject, key)`, so there is at most one live note per key.
`text` and `gloss` never contain line breaks (whitespace is collapsed on write).

`terms` belongs to the tokenizer that wrote it (`meta.terms_version`); a reader with a different tokenizer sets
every `terms` to null and rebuilds them on use. Writers that change `text` or `gloss` set `terms` to null.

### `vectors`: meaning tier 1

`(memory_id, embedder)` primary key; `vector` (blob). `embedder` names the model and its settings
(`openai:text-embedding-3-small:256`); vectors from different embedders are never compared. Rows of notes that
no longer exist are deleted on `purge` and `erase`.

### `meaning_terms`: meaning tier 2

`(embedder, term)` primary key; `count` (how many embedded texts contained the term); `vector` (blob: the running
mean of those texts' vectors). `meta."meaning_texts:<embedder>"` counts the texts learned. Implementations that
don't run this tier can ignore the table.

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
this event added), `reason`, `confidence` (0–1), `source` (`user`, `speak-up`, `duty`, `manual`…), `judge` (the
tier or tiers that answered, such as `luna` or `micro+prompt`).

### `recalls`: the recall log

`id`, `space`, `subject`, `at`, `query`, `chosen` (JSON `[[id, why], …]`), `skipped` (JSON `[[id, reason], …]`).
The newest 200 per subject are kept.

### `micro_models`: decision tier 2

`question` (primary key: `name:sha1(type|instructions|labels…)[:12]`), `kind`, `labels` (JSON list), `weights`
(JSON `{"bias": [...], "w": {"feature": [...]}, "window": [0/1…]}`), `examples`, `updated_at`. Features are CRC-32
hashes of search terms, masked to 18 bits. Implementations that don't run the micro model can ignore this table.

### `meta`

`key`, `value`. Holds `schema_version`, `terms_version`, `meaning_texts:<embedder>` and `adopted:…` flags hosts
may set.

## Export format

`Mneme.export_data()` / `mneme-llm export` writes one JSON object:

```json
{"mneme_llm": 1, "space": "dafeiyu", "exported_at": 1792885075.5,
 "memories": [{"id": 1, "subject": "discord:42", "key": "pet.name", "kind": "fact", "text": "…", "gloss": null, …}],
 "profiles": [...], "moods": [...], "mood_events": [...]}
```

Rows are the table rows as objects, without `terms`. Vectors and micro models are not exported: they belong to an
embedder and a tokenizer, and are rebuilt on use. On import, memory ids are renumbered and `superseded_by` links
follow the new numbers; moods are imported without their event links (the timeline is imported separately).

## Search terms

To match the Python implementation's recall (tokenizer version `2`), a term is one of:

- a Latin word: NFKC-lowercased, two or more characters, `'s` and a plural `s`/`ies` trimmed, common function
  words dropped;
- in a run of Chinese, Japanese or Korean characters, each overlapping pair of characters (common function pairs
  such as 我们 and 什么 dropped) and each single character (common function characters such as 的 and 了 dropped).

With jieba installed and enabled, jieba's words of two or more characters are added (version `2+jieba`). Other
implementations may tokenize differently; that changes only which notes a query finds, never what is stored.

## Changes within schema 1

Files written before these were added open as before; a writer adds the missing parts:

- `memories.gloss` and `memories.terms` (columns);
- `vectors` and `meaning_terms` (tables).

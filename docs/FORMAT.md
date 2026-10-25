# The mneme-llm file format (schema 1)

A mneme-llm file is an SQLite 3 database. This page is enough to read and write one from any language. The
Python package is one implementation; nothing below depends on it.

Times are Unix seconds (floating point, UTC). Text is UTF-8. `meta.schema_version` is `1`; a reader must
refuse a file with a higher version than it knows, and may migrate a lower one.

## Tables

### `memories`: the notes

| column | type | meaning |
|---|---|---|
| `id` | integer | primary key |
| `space` | text | whose memory (an app or character) |
| `subject` | text | who the note is about |
| `key` | text, null | what it is about, lowercase, `part(.part){0,3}`, at most 48 characters; never the value |
| `kind` | text | `fact`, `preference`, `episode`, `plan` or `reflection` |
| `text` | text | the note, one sentence, at most 500 characters |
| `importance` | integer | 1 (trivial) … 5 (core: always in context) |
| `feeling` | real | −1 … 1, how the subject felt about it (0: neutral or unknown) |
| `happened_at` | real | when it happened (or will) |
| `created_at` | real | when it was written |
| `recalled_at` | real, null | last time it was recalled by evidence |
| `recalls` | integer | how many times |
| `superseded_by` | integer, null | the id of the note that replaced it (same key) |
| `deleted_at` | real, null | when it was forgotten |
| `source` | text, null | who wrote it: `auto` (a model, unprompted), `user`, `cli`, … |

A note is **live** when `superseded_by` and `deleted_at` are both null. Writing a note with a key sets
`superseded_by` on the live note of the same `(space, subject, key)`. At most one live note per key.

### `profiles`: the impression card

`(space, subject)` primary key, `text`, `updated_at`. A few sentences, shown above the notes.

### `moods`: the current state

`(space, subject)` primary key; `value` (0–100 when written); `emotions` (JSON object, feeling → intensity
0–100); `updated_at`; `last_event` (id in `mood_events`); `told_event` (the last event told to the model).

The stored values are as of `updated_at`. To read the state at time *t*, with *h* = hours since `updated_at`:

    value(t)   = baseline + (value − baseline) · 0.5^(h / 3)
    emotion(t) = emotion · 0.5^(h · 60 / 90)

(baseline 70 and both half-lives are settings, not part of the file).

### `mood_events`: the timeline

`id`, `space`, `subject`, `at`, `delta` (the change actually applied), `value` (after it), `emotions` (JSON:
what this event added), `reason`, `confidence` (0–1), `source` (`user`, `speak-up`, `duty`, `manual`…),
`judge` (the tier or tiers that answered, e.g. `luna`, `micro+prompt`).

### `recalls`: the recall log

`id`, `space`, `subject`, `at`, `query`, `chosen` (JSON `[[id, why], …]`), `skipped` (JSON `[[id, reason], …]`).
The newest 200 per subject are kept.

### `micro_models`: the micro decision model

`question` (primary key: `name:sha1(type|instructions|labels…)[:12]`), `kind`, `labels` (JSON list),
`weights` (JSON `{"bias": [...], "w": {"feature": [...]}, "window": [0/1…]}`), `examples`, `updated_at`.
Features are CRC-32 hashes of search terms, masked to 18 bits. Implementations that don't run the micro
model can ignore this table.

### `meta`

`key`, `value`; holds `schema_version`.

## Export format

`Store.export(space)` / `mneme-llm export` writes one JSON object:

```json
{"mneme_llm": 1, "space": "whale_chan", "exported_at": 1792885075.5,
 "memories": [{"id": 1, "subject": "discord:42", "key": "pet.name", "kind": "fact", "text": "…", …}],
 "profiles": [...], "moods": [...], "mood_events": [...]}
```

Rows are the table rows as objects. On import, memory ids are renumbered and `superseded_by` links follow the
new numbers; moods are imported without their event links (the timeline is imported separately).

## Search terms

To match the Python implementation's recall, a term is either a Latin word (NFKC-lowercased, two or more
characters, `'s` and a plural `s`/`ies` trimmed, common function words dropped), or each overlapping pair of
characters in a run of Chinese, Japanese or Korean characters (common function pairs such as 我们 and 什么
dropped). Other implementations may tokenize differently; that changes only which notes a query finds, never
what is stored.

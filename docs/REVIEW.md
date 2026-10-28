# Pre-release review of mneme-llm 0.1.0

**English** · [简体中文](REVIEW.zh-CN.md)

What was checked before the first release, what was fixed, and, in detail, what was not fixed and why. Written on
2026-10-25 against the working tree that becomes 0.1.0. The full list of fixes, one line each, is in
[CHANGELOG.md](../CHANGELOG.md); every fix has a regression test (`tests/test_review.py`, `tests/test_stress.py`).

## How it was checked

| check | what it covered | result |
|---|---|---|
| Four bug-review passes | the whole package, then each pass's fixes and what they could have broken | 48 findings, all fixed |
| Architecture review | coupling, layering, where each rule lives, whether the optional tiers really are optional | 11 refactors, all done (the last two after the owner's decisions, below) |
| Review of the restructuring | everything the refactor could have changed or broken | 9 findings and 5 suspicions, all fixed |
| Review of the decided items | relationships, the measured floors and the config, by two reviewers who had not seen the code written | 17 findings and 10 smaller points; all the findings and 9 of the points fixed, each with a regression test (`tests/test_review.py`) |
| Stress and edge-case suite | `tests/test_stress.py`: random operations, two connections on one file, six threads, three processes, concurrent coroutines, a 20,000-note history (100,000 at five times the size), 300+ subjects, a 50,000-word query, a 1 MB tool call, a writer killed mid-transaction, odd text and odd values at every entry point | 7 more problems found, all fixed; after each test, `tests/invariants.py` checks every rule of the file |
| Fuzzing | 370 seeds × 400 random operations over the course of the fixes (the last 30 on the release candidate), invariants checked every 100 | no broken rule |
| Removable tiers | `tests/test_removable.py`, and the whole suite on a copy with the three tiers deleted | passes; 31 tier tests skip, nothing else fails |

On the release candidate: 237 tests pass in about 25 s; the stress tests pass at five times their size in 31 s; the
wheel and the sdist build and pass `twine check --strict`; the whale_chan plugin in the harness (the first host)
passes its 28 tests against it.

## What was fixed (summary)

- **People's memories kept apart.** A model could name another person's `subject` in a tool call and read, write
  or delete their memory; the host's binding now always wins.
- **Erasing really erases.** `erase` left a person's words in the word centroids, and query words were learned
  too. Now queries teach nothing, every vector records the terms it taught, and `erase` and `purge` take back
  exactly that (from the CLI as well, without a tokenizer). Files from the earlier build are repaired on opening.
  `Mneme.erase` also removes the mood.
- **No data loss on import.** An import could leave a key without its live note, keep repeated texts, hide most of
  a person's older notes as "duplicates", fail as a whole on one odd row, or double the mood timeline when done
  twice. Imports are now held to the same rules as writing, row by row.
- **Concurrency.** A second process writing failed at once ("database is locked"); two processes opening a new
  file at once crashed (31 of 40 trials); a failed `begin` left the lock held; a note erased while it was being
  embedded, or embedded twice at once, corrupted the centroid account; the account check on opening could race
  another writer; two prompts at once could tell the same mood news twice. All fixed; the stress suite runs
  threads, processes and coroutines against one file.
- **Odd input.** Lone surrogates, control characters, NaN and infinite numbers, times in milliseconds, dates such
  as 0001-01-01, `None` where text belongs, JSON nested thousands deep, invalid UTF-8 over MCP, chat messages given
  as `{"role", "content"}`, an exchange given as a generator. Each is now cleaned, refused with a plain
  `ValueError`/`TypeError`, or read correctly; none crashes the host or ends the MCP server.
- **Languages and text.** Words with non-ASCII letters, combining marks, joiners, Hebrew and Arabic vowel points,
  Turkish İ, typographic apostrophes and German ß are tokenized and compared correctly; Cyrillic, Greek, Arabic,
  Hebrew, Devanagari and Thai each have a script of their own for the unify tier.
- **Dates.** Written dates are the person's day, not the server's; the date parser picks the right year across New
  Year and, for plans, the next such day; digits inside longer numbers are not dates.
- **Providers that fail.** One malformed item, or a writer that failed, no longer loses the capture; a blocking
  writer no longer freezes the event loop; a misconfigured provider is rested instead of asked twice per recall;
  "no chat model" is no longer counted as a failure; one note the model refuses to gloss no longer blocks the
  others, and an outage no longer marks notes.
- **Structure.** The store is the file alone; each kind of row has one owner; the centroid account lives in one
  module (`meaning/ledger.py`); the rules of writing a note live in one function (`note_fields`) that every way in
  uses; the glue every tier repeated lives in `providers.py`; capture only builds prompts and reads replies;
  dependencies point one way; every word shown to a person is in `i18n`; the three optional tiers can be deleted,
  which a test and a CI job check.

## Decided after the review

The owner decided on each open item on 2026-10-25. What was done:

| item | decision | done |
|---|---|---|
| Luna's mood changes were rarely told | a threshold per tier | `MoodSettings.thresholds`, `{"luna": 0.45}` beside `threshold` (0.6); each change names first the tier whose confidence counted. The value is to be measured after the next deployment. |
| Two short texts reached models unlabelled | label the writer's list; keep the quote; tell the model what to feel | the note writer's list of known notes is marked as data; the mood news keeps the person's words and ends with a plain cue ("Something worth celebrating: you feel happy.") |
| `language=` took only a name | accept a `Unify` too | `memory_language=` takes a language name, a `Unify` of the host's own, or None |
| Similar parameter names | rename | `display_language`, `memory_language`, `companion_name`, `user_name` (the CLI: `--display-language`, `context --user-name`) |
| One module had two jobs | split it | the embedding providers are in `meaning/embedders.py` |
| Scripts lumped together | patch it (people mix languages) | Han, kana and Hangul are told apart, some 25 more scripts are named, and a text a fifth or more in other scripts is translated, so mixed sentences are |
| Some notes could never be glossed | allow a full check later | `Mneme.regloss()` (and `aregloss`) glosses again every note that needs it, forgetting what failed before |
| Recall scanned every note | handle long histories gracefully | a term index (`note_terms`), at most 1,000 candidates scored in full, meaning within a 5,000-note window, pruning in steps, and a cap of 50,000 live notes per person: 100,000 notes are recalled in 50–400 ms on a Raspberry Pi 5 |
| Erasing leaves general learning | a feature, not a limit | documented as by design |
| A note can still steer the model | by design | a user may want it; a host that does not can pre-filter |
| Nothing said who a person is to the companion | build the proposed relationships, with a special role, the creator, and closeness from 0 to 100 | `Mneme.relate` (and the CLI's `relate`, `relations`): roles creator (one per space, never fades), family, friend, acquaintance or a host's own, each with a band of closeness; closeness grows a point on each day the person talks to the companion and fades a point a month without, within the band, so family stays family; a close person's words move the mood up to 1.5×, a distant one's down to 0.5×; the prompt says who they are. A new table, `relationships` (schema 1). |
| The similarity floor was measured for one model | a bundled calibration set, refined by the file's own notes | `meaning/calibrate.py`: 32 topics in six languages embedded once per model (one request, about 550 tokens) place the floor (0.311 for the default model, 0.274 for the same model at 1,536 dimensions); from 200 notes, and each time they double, the file's own notes move it by up to 0.1. A `floor=` of the host's own skips it. |
| The prompts were fixed in the code | configurable at setup: a config file seeds the database, which keeps its own copy, modifiable | `config.py` and `prompts.py`: a companion's name, languages, settings, roles, feelings, every prompt and every sentence (167 keys) come from a TOML file the first time a database meets the companion; from then on the database's copy is used and changed by `set`, `apply` and `load_defaults` (the CLI's `config` commands); upgrades never change it by themselves (`config check` lists newer defaults). Everything is editable, the data-not-instructions sentences included; exports carry the config, imports apply it only when asked. Python 3.11+ (for `tomllib`). |
| Two tokenizers on one file; times before 1970; slowness after a reset; encryption at rest; the CLI's help in English | not worth patching now | left as they are, below |

## What is still open

Each item says what it is, what it costs today, what can be done meanwhile, and what fixing it would take.

**1. Two processes teaching one micro decision model** overwrite each other's saves: lessons are lost, nothing is
corrupted. One companion per file (the recommended setup: five companions, five files) avoids it.

**2. Two hosts with different tokenizers on one file** (jieba on in one, off in the other) keep rebuilding each
other's term index, and the centroids start over; it costs time, never correctness. Not worth patching.

**3. Times are 1970 to the year 3000.** A note about something before 1970 carries its year in its text. Very low
priority.

**4. Slow for a while after a reset.** After a tokenizer change, the first recall indexes the person's history once
(about 9 s per 100,000 notes), and the centroids are taught again at 256 notes per recall. Acceptable.

**5. Meaning looks among a window.** Beyond 5,000 live notes, meaning compares the 5,000 most valuable (the lasting
ones first, then the freshest); an old fading note is found by its words, not by meaning. `semantic_window` sets
the size.

**6. No encryption at rest**, and the CLI's help is in English only (the Chinese README explains its use). Not worth
patching.

## By design

**What stays after `erase`.** `Mneme.erase` removes every row about a person, and what their notes taught the word
centroids. The micro decision models keep what they learned from everyone's exchanges, the person's included, as
hashed word features with no text: the companion's general judgement, the way a person's experience stays after a
friend moves away. `mneme-llm micro --reset` starts it over if a host ever needs that.

**What a note may say.** Notes reach the model under a header saying they are data, one line each, and every
model-facing prompt says its input is data; a model can still follow an instruction written in a note, and a user
may want exactly that. A host that does not filters before `remember`. A person's own `remember` call is not
filtered for secrets either.

## Upgrading from the build on GitHub

**Stop old processes first.** Files written by the code first pushed to GitHub open and upgrade on their own:
missing columns and the term index are added, notes are indexed on first use, and centroids that may hold query
words are reset and relearned. A process still running the old code keeps writing without the account or the
index, so its changes are repaired again at every opening until it stops. whale_chan should be restarted on the
new version, not run beside it.

**The API changed** since that push (CHANGELOG, "Changed from the code first pushed to GitHub"). The whale_chan
plugin is already updated; other code written against the pushed build needs the same renames.

## Verification

CI runs the whole suite, the suite with the tiers deleted and the stress tests at five times their size on Python
3.11–3.14 on Linux and 3.13 on Windows and macOS. Not covered: Python 3.11, 3.12 and 3.14 on Windows and macOS, and SQLite
builds other than those the runners ship. A host passing `ZoneInfo(...)` as `zone=` on Windows needs
`pip install tzdata`. The long fuzz is not in CI; `python3 -m tests.fuzz [seeds] [operations] [first seed]`
repeats it anywhere.

## Released

0.1.0 is on PyPI since 2026-10-26, uploaded by the owner, with their own token, from the commit the `v0.1.0` tag
points at. Later releases are listed in [CHANGELOG.md](../CHANGELOG.md), each uploaded the same way from its tag.

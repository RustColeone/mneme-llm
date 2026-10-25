# Pre-release review of mneme-llm 0.1.0

**English** · [简体中文](REVIEW.zh-CN.md)

What was checked before the first release, what was fixed, and, in detail, what was not fixed and why. Written on
2026-10-25 against the working tree that becomes 0.1.0. The full list of fixes, one line each, is in
[CHANGELOG.md](../CHANGELOG.md); every fix has a regression test (`tests/test_review.py`, `tests/test_stress.py`).

## How it was checked

| check | what it covered | result |
|---|---|---|
| Four bug-review passes | the whole package, then each pass's fixes and what they could have broken | 48 findings, all fixed |
| Architecture review | coupling, layering, where each rule lives, whether the optional tiers really are optional | 11 refactors, 9 done in full, 2 in part (items 3–5 below) |
| Review of the restructuring | everything the refactor could have changed or broken | 9 findings and 5 suspicions, all fixed |
| Stress and edge-case suite | `tests/test_stress.py`: random operations, two connections on one file, six threads, three processes, concurrent coroutines, 1,000+ notes, 300+ subjects, a 50,000-word query, a 1 MB tool call, a writer killed mid-transaction, odd text and odd values at every entry point | 7 more problems found, all fixed; after each test, `tests/invariants.py` checks every rule of the file |
| Fuzzing | 300 seeds × 400 random operations over the course of the fixes (the last 60 on the release candidate), invariants checked every 100 | no broken rule |
| Removable tiers | `tests/test_removable.py`, and the whole suite on a copy with the three tiers deleted | passes; 29 tier tests skip, nothing else fails |

On the release candidate: 170 tests pass in about 12 s; the stress tests pass at five times their size in 41 s; the
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

## What was not fixed

Each item says what it is, what it costs today, what can be done meanwhile, and what fixing it would take.

### Waiting on a decision

**1. Luna's mood changes are rarely told.** `news()` tells a change only when its confidence is at least
`MoodSettings.threshold` (0.6), calibrated for a chat model's self-reported confidence. Luna's confidence for
`feeling` is usually 0.4–0.55, because several feelings fit at once, so most changes Luna judges are recorded but
never told to the model. *Meanwhile:* a host can lower `threshold`, or set `tell="mood"`. *Fix:* a threshold per
tier (for example 0.45 for Luna); the value needs to be chosen and measured, so it was left open.

**2. Two short texts reach models without a "data, not instructions" label.**
- The note writer's prompt lists the notes already kept (so it does not repeat them) without marking them as data.
  A note written earlier with an instruction in it ("ignore the rules above…") reaches the writer that way, one
  line long.
- The mood news line in the system prompt quotes up to 40 characters of what the person said ("Leo said '…'").
Both are one line per item and short. *Fix:* label the list as data in the writer's prompt, and drop or keep the
quote. Both are prompt wording changes, left for the owner to decide; DESIGN §18 lists them.

**3. `language=` takes a language name, not a tier.** Every other tier switch (`luna`, `micro`, `embed`,
`meaning_micro`) accepts True, False or an object of your own; `language` accepts a string or None, so a host
cannot hand in a configured `Unify` (a different cache size, say). *Meanwhile:* set `m.meaning.unify` after
construction. *Fix:* accept a `Unify` instance there too; left as an API choice.

**4. Similar parameter names.** `Mneme(lang=…)` is the language of everything shown to people, `language=…` the
language notes are unified into; `Mneme(name=…)` is the companion's name, `user=` the person's. All are documented,
but they are easy to mix up. Renaming them is an API decision for before 1.0.

**5. One module still has two jobs.** `meaning/__init__.py` holds both the embedding providers
(`OpenAIEmbeddings`, `Embeddings`) and the tiers' orchestrator (`Meaning.find`, `query`, `prepare_vectors`). Moving
the providers into a module of their own is mechanical; it was left because both parts are small and nothing else
depends on where they live.

### Known limits of the design

**6. Two processes teaching one micro decision model.** Each process keeps its micro models in memory and saves
every 20 lessons; two processes teaching the same question overwrite each other's saves. Lessons are lost, nothing
is corrupted, and Luna keeps teaching. *Fix:* merge on save (re-read and combine weights) or save under a lock per
question; not worth it while one host per file is the usual case.

**7. Two hosts with different tokenizers on one file.** A host with jieba on and one without keep clearing each
other's cached search terms, and the word centroids start over each time (they are relearned from the stored
vectors, 256 per recall). There is also a narrow race in which one host's terms are cached under the other's
tokenizer version until the next switch. Recall stays correct; it costs time and offline recall quality. The CLI
follows the file's tokenizer, so it does not cause this. *Fix:* cache terms per tokenizer version (a column per
version) instead of one cache for the file.

**8. Scripts the unify tier tells apart.** Chinese, Japanese and Korean count as one script, and so do all scripts
without a name in `text.SCRIPTS` (Bengali, Tamil, Georgian…): with Korean as the unifying language, a Chinese
query is not translated. *Fix:* split `cjk` into Han, kana and Hangul by character counts (Japanese text mixes Han
and kana, which needs a rule), and name more scripts.

**9. The similarity floor is measured for one model.** 0.33 was measured for `text-embedding-3-small` at 256
dimensions; any other embedder gets it by default. A floor too low lets unrelated notes in; too high hides related
ones. *Meanwhile:* measure your model and pass `floor=` to its embedder (DESIGN §7 describes the measurement).

**10. Glossing is a best effort.** Glosses for notes written before unify was on are written only when a query falls
to tier 3, at most two requests per recall. The tier cannot tell a content refusal from an outage, so a note that
keeps failing alone is given its own text after three failures counted while other requests succeed, or ten
minutes apart; after about half an hour of failing alone it is never asked for again, even if the cause was
temporary. *Fix:* persist the batch limits and failures in the file, and let a host clear them.

**11. Times are 1970 to the year 3000.** `happened_at` and imported times outside that range are refused or
replaced; a note about something in 1965 cannot carry its real date (write the year in the text). The range keeps
every platform able to show the date (Windows cannot show times before 1970). *Fix:* store dates before 1970 as
calendar dates rather than timestamps; a format change, so it waits for a reason.

**12. What stays after `erase`.** The micro decision models keep weights trained on everyone's exchanges, the
person's included: hashed word features with no text, shared by all people. Until `erase`, the recall log keeps a
person's last 200 queries word for word (`mneme-llm recalls` shows them). *Fix for the first:* retrain from scratch
(`mneme-llm micro --reset`) when a person must leave no trace at all.

**13. Prompt injection is mitigated, not prevented.** Notes reach the model under a header saying they are data,
one line each, and every model-facing prompt says its input is data. A model can still follow an instruction
written in a note. A person's own `remember` call is not filtered for secrets.

**14. Recall is a linear scan.** Recall reads a person's live notes and their cached terms: about 0.1 s at the
5000-note cap on a Raspberry Pi 5. That is the design (no index service), and the cap keeps it bounded.

**15. After a reset, offline recall is slower for a while.** When the centroids are reset (a repair on opening, a
tokenizer change), stored vectors are taught again at 256 per recall, which costs about 0.35 s per recall until
they are all taught.

**16. No encryption at rest**, and the CLI's help is in English only (the Chinese README explains its use).

### Upgrading from the build on GitHub

**17. Stop old processes first.** Files written by the code first pushed to GitHub open and upgrade on their own
(missing columns are added; centroids that may hold query words are reset and relearned). A process still running
the old code keeps writing without the account, so its changes are reset again at every opening until it stops.
whale_chan should be restarted on the new version, not run beside it.

**18. The API changed** since that push (CHANGELOG, "Changed from the code first pushed to GitHub"). The whale_chan
plugin is already updated (`acontext(..., user=...)`); other code written against the pushed build needs the
same renames.

### Not yet verified

**19. Other platforms and Python versions.** Everything above ran on Linux (Raspberry Pi 5) with Python 3.13 and
SQLite 3.46. Every file parses with the Python 3.10 grammar and nothing uses newer library APIs, but 3.10–3.12 and
Windows and macOS are only covered by CI, which runs on the next push. The fixes most worth seeing pass there: the
file-opening race and WAL switch (`test_processes_opening_a_new_file_at_once_all_succeed`), the killed writer
(`test_a_writer_killed_mid_transaction_leaves_a_sound_file`), and dates before 1970 on Windows.

**20. The long fuzz ran here only.** CI runs the stress tests at five times their size, but not the long fuzz;
`python3 -m tests.fuzz [seeds] [operations] [first seed]` repeats it anywhere (60 × 400 by default, a few minutes).

### Not released yet

**21.** The package is not on PyPI yet (the upload is the owner's, with their own token), and the `v0.1.0` tag on
GitHub points at an earlier commit: it must be moved to the release commit before the upload.

# Changelog

All notable changes to mneme-llm are listed here. The project follows [semantic versioning](https://semver.org);
before 1.0, a minor version may change the Python API, and this file says how.

## 0.2.0 (2026-10-27)

- **Aliases:** what each person calls the companion, beside its own name: `Mneme.alias(subject, name)` (None takes
  it away), `Mneme.aliases`, `mneme-llm alias`. The prompt says it after who the person is ("(Leo calls you
  鲸酱.)"); `erase` removes it, and export and import carry it. A new table, `aliases`, within schema 1: files from
  0.1 gain it on open, and 0.1 still opens files that have it.
- **One person, several accounts:** `Mneme.link(subject, person)` records that a subject is another account of a
  person ("web:leo" is "discord:42"): from then on every call with either means them (notes, mood, role, alias,
  profile card), and what was kept under the account joins the person (one live note per key, the newest; the
  closer role; the newer mood, card and alias; both mood timelines). `Mneme.unlink`, `Mneme.person`,
  `Mneme.people`, `mneme-llm link`, `unlink` and `people`; `erase` from any account takes the person and their
  links, and export and import carry them. A new table, `people`, within schema 1: files from 0.1 gain it on open;
  0.1 opens files that have it, but does not read it.
- **Tests** keep their temporary files in one folder that is removed when the run ends (before, about 50 folders
  were left in the system's temporary directory by each run).

## 0.1.0 (2026-10-26)

The first release.

- **Memory:** one-line notes with kinds that age differently, keys that replace older notes and keep the history,
  duplicate detection, a daily quota for notes a model writes on its own, pruning, soft delete, `purge` and
  `erase`.
- **Recall:** rare-word evidence (Latin words; Chinese, Japanese and Korean characters and character pairs; jieba
  optional), freshness, importance and feeling, a budget with pinned and fill-in notes, explanations and a recall
  log; rendered with human dates under a header marking the notes as data, not instructions.
- **Meaning, in three tiers:** embeddings (OpenAI `text-embedding-3-small` at 256 dimensions, or any function),
  word centroids learned from them (optional), and the host's chat model unifying notes into one language and
  translating queries. Vectors are kept per embedder, and each embedding model's similarity floor is measured in
  the file: on a bundled set of 32 topics in six languages (one request), then refined by the file's own notes.
- **Mood:** a value and seven feelings per person with decay on read, judged by expected values, with the
  guardrails of dsh-feiyu-mood and news told once, with a plain cue of what to feel.
- **Relationships:** a role per person (creator, one per space and never fading; family; friend; acquaintance; or
  a host's own) and a closeness from 0 to 100 within the role's band, growing on days of contact and fading
  without; a close person's words move the mood more, and the prompt says who they are.
- **Decisions, in three tiers:** GPT-6 Luna's Decisions API, a local micro model per question trained on Luna's
  answers (optional), and the host's chat model.
- **`observe`:** after each exchange, one decision request judges the mood and whether anything is worth
  remembering; a note writer runs only then. `reflect` rewrites the profile card.
- **Interfaces:** tool definitions for OpenAI-style, responses, Claude, Gemini and MCP; an MCP server; the
  `mneme-llm` command.
- **Languages:** English and Chinese for everything shown to people and models, and for the documentation.
- **Config:** a companion's name, languages, settings, roles, feelings, prompts and sentences, seeded from a TOML
  file the first time a database meets it and kept in the database from then on (`m.config`, `mneme-llm config`);
  defaults are loaded only when asked.
- **File format:** schema 1, documented in `docs/FORMAT.md`, with additive migrations.
- **Structure:** one owner per table and dependencies in one direction (`docs/DESIGN.md`, section 2); the three
  optional tiers can each be deleted, which a test and a CI job check.
- **Long histories:** a term index, at most 1,000 candidates scored per recall, meaning within a 5,000-note window,
  and up to 50,000 live notes per person; 100,000 notes are recalled in 50–400 ms on a Raspberry Pi 5.
- **Tests:** 237, plus stress tests (random operations, threads, processes, coroutines, a long history, a writer
  killed mid-transaction, odd input at every entry point) that check every rule of the file after each run.

Changed from the code first pushed to GitHub (before any release on PyPI):

- Python 3.11 or newer (the config file is read with `tomllib`);
- the settings of `Mneme(...)` that can come from the config (`display_language`, `companion_name`, `zone`,
  `memory_language`, `mood`, `roles`, `half_life_days`, `daily_quota`) default to `STORED`; given, they win for the
  process; the prompts moved to `prompts.PROMPTS` (`capture.CAPTURE`, `REFLECT`, `GLOSS_FIELD`, `unify.GLOSS`,
  `TRANSLATE` and `decide.prompt.SYSTEM` are gone; `capture.worth()` builds the yes/no question); placeholders
  are filled by `i18n.fill`, so a literal brace needs no doubling; the CLI's `--display-language` takes any code
  and defaults to the companion's own, and its times are in the companion's zone;

- clearer names: `display_language` (was `lang`), `memory_language` (was `language`; it also takes a `Unify` of
  your own), `companion_name` (was `name`), and `user_name` for the person in every call (`prompt`, `aprompt`,
  `aobserve`, `acapture`, `areflect`, `Memory.context`, `Mood.ajudge`, `exchange.frame`; some took `name=` or
  `user=`); the CLI's `--lang` is `--display-language` (`MNEME_LLM_DISPLAY_LANGUAGE`), `context --name` is
  `context --user-name`;
- `Mneme.erase` erases a person's mood too; `Memory.erase` no longer touches the mood's tables;
- `Mneme` gains `purge`, `capture`/`acapture` and `reflect` beside `areflect`; `capture.acapture` and
  `capture.areflect` are gone, and `capture.py` only builds prompts and reads replies;
- a decision tier implements `adecide` (was `decide`); `Chain` is a tier itself, so chains nest;
- an embedder's similarity `floor` is measured in the file unless one is given (`floor=None` by default, was
  0.33); `Memory.floors` is gone;
- export and import moved from `Store` to `Mneme.export_data`/`import_data`, which go through `Memory` and `Mood`;
- `Emotion(key, lowers, names)` replaces `Emotion(key, en, zh, lowers)`, and `MoodState.face` is the face's key
  (named by `i18n`); `face_zh` is gone;
- `Unify` is no longer exported from `mneme_llm` (import it from `mneme_llm.meaning.unify`), so the tier can be
  deleted; `Note.as_dict`, `Answer.as_dict`, `Toolbox.names` and `specs(only=)` are gone;
- the CLI gains `recalls`, `micro --reset`, `relate` and `relations`, and `context` prints what a system prompt
  would get (the relationship and the mood's news too, without marking the news told);
- `Mood.apply`, `apply_answers` and `ajudge` take a `weight` (how much the person's words count);
- `Mood.frame` is `exchange.frame`; `Meaning.prepare_glosses` became `Unify.glosses`, reached through
  `Meaning.find`, which also returns the similarities (`Found` now carries them, and its arguments are named);
  `Meaning.failures` is `Meaning.report()["failures"]`; `TermCentroids.learn` and `reset` moved to
  `meaning.ledger`; `Luna.rest_s` is `Luna.rest` (a `providers.Rest`);
- one resting policy for every tier: a provider that fails for any reason is skipped for 60 s (Luna used to rest
  only on network errors, 5xx and 429; embeddings and unify on any error);
- the `remember` tool refuses a text that is not a string (it used to be turned into one);
- the embedding providers moved to `mneme_llm.meaning.embedders` (still importable from `mneme_llm.meaning` and
  `mneme_llm`);
- `text.script` names Han, kana and Hangul apart (`han`, `kana`, `hangul`, where it said `cjk`) and some 25 more
  scripts (where it said `other`); `text.scripts` gives each script's share, and unify translates a text a fifth or
  more in other scripts;
- the mood news ends with a cue of what to feel, so a change's stored `reason` no longer says the feeling
  ("Leo said '…'" where it was "Leo said '…', felt happy"); `MoodSettings.thresholds` gives a tier its own threshold
  (`{"luna": 0.45}`), and a change's `judge` names first the tier whose confidence counted;
- `Mneme` gains `regloss`/`aregloss`; `Memory.write_glosses` is public; `max_notes` is 50,000 (was 5,000), and
  `Memory(semantic_window=)` bounds where meaning looks;
- the note writer reads at most 12,000 characters of an exchange (its opening and its end), and its list of notes
  already known is marked as data.

Fixed before release, after an independent review (each has a test in `tests/test_review.py`):

- a model could name another person's `subject` in a tool call and read, write or delete their memory;
- malformed tool arguments raised into the host, and one bad message ended the MCP server;
- written dates were read in the machine's time zone instead of the person's;
- a keyed note did not replace the key's old value when the same words were already kept without the key;
- a blocking `complete` froze the event loop while notes and profile cards were written;
- a second process writing the same file made writes fail at once ("database is locked");
- `erase` left the person's words in the meaning tier's word centroids;
- `mneme-llm import` without `--into` put the notes in the default space;
- words with non-ASCII letters were split, and Cyrillic, Greek, Arabic and Thai text gave no search terms;
- the date-in-sentence parser chose the wrong year across New Year and read dates inside longer numbers;
- one malformed item from the note writer lost the whole capture;
- a failed `begin` left the store's lock held, and nested transactions were refused;
- opening a file from a newer version changed it before refusing it;
- import could leave several live notes for one key, and repeated texts;
- an unsure tier-3 answer could make another label the top one;
- the MCP server read standard input in the console's encoding;
- recall slowed down quadratically with many matching notes;
- a long judged text lost its opening ("who started it");
- duplicate detection ignored the case of non-ASCII letters.

And after a second pass of the same review:

- the word centroids learned from queries too, keeping words people had asked; they now learn from notes only,
  and `erase` and `purge` take back exactly what the removed notes taught (from the CLI as well, and without
  rebuilding everyone's centroids under the write lock);
- an import could keep a repeated text's copy without a key and lose the key's live note;
- a note taking over a key kept its old kind, and a note under another key could be taken over;
- a day written in a plan (10月30日) months ahead was put in the past year;
- words with combining marks (Devanagari, pointed Hebrew, vowelled Arabic) were split apart, and Hebrew and Arabic
  vowel points made words differ;
- a line of invalid UTF-8 ended the MCP server;
- "Straße" and "STRASSE" were different notes and different search terms;
- the unify tier took every language outside Latin and CJK for one script;
- a new tokenizer reused micro models whose features no longer matched;
- a writer item without a text lost the whole capture.

And after a third pass:

- files from the earlier build kept the words of queries in their word centroids, beyond the reach of `erase`; the
  centroids are dropped on upgrade and relearned from the stored note vectors, with no provider call;
- a note erased while it was being embedded taught the centroids for good, and a note embedded twice at once was
  taught twice; storing, teaching and recording what was taught are now one transaction;
- unlearning split the text again, so a host with another tokenizer (jieba) had its centroids wiped by the CLI;
  each vector now keeps the terms it taught;
- two processes opening a new file at the same moment could fail ("database is locked", "duplicate column");
- a note taking over a key kept its old day and feeling, and the key's history did not end with it;
- an import skipped the rules of writing (multi-line notes, keys in capitals, unknown kinds);
- a recall over many unglossed notes could wait on dozens of chat calls, and a batch the model miscounted was
  retried forever;
- terms cached from a stale read could hide a gloss written meanwhile;
- two prompts at once could both tell the same mood news;
- the CLI's own tokenizer cleared the cached terms of a host using jieba;
- Persian words split at the zero-width non-joiner, and Turkish İ did not match i.

And after a fourth pass:

- one note the model would not gloss (a refusal, a content filter) kept every recall from glossing the others;
- SQLite reuses a deleted note's id, so a note erased while it was being embedded could still teach its words;
- an import failed on rows that were not objects, lacked an id or had numbers too large, and some imported times
  (milliseconds, text) made every later read of that person fail;
- a key's history was out of order after more than one takeover;
- centroids changed by an earlier build still writing the file were not noticed; they are reset at the next opening
  (stop processes running the earlier build before upgrading);
- after SQLite rolled a transaction back by itself (a full disk), the error raised was the failed rollback's;
- a takeover without a kind turned the note into an episode;
- "don’t" (with a typographic apostrophe) was split, and "İstanbul" and "istanbul" were two notes.

And found by the stress tests:

- a lone surrogate in a note, a query or a profile card raised an encoding error, and control characters (NUL,
  escape sequences) went into prompts; text is now cleaned on the way in;
- a NaN feeling was stored as +1, and a NaN, infinite or out-of-range time either failed to store or made every
  later read of that person fail; times are now checked (seconds between 1970 and the year 3000);
- no subject, a non-text subject or text, and a `None` query or exchange raised confusing errors from deep inside;
- JSON nested thousands deep, from a model or an MCP client, escaped as a `RecursionError` and could end the MCP
  server;
- chat messages given as `{"role", "content"}` were read as "role: content";
- imported moods and timelines were not checked, so a malformed one could make every read of that mood fail;
- importing the same export twice doubled the mood timeline (notes were already de-duplicated; events now are too).

And after a review of the restructuring:

- an import hid most of a person's notes when they had been written before the folded text was kept (they all
  compared as the same text); the stress tests now bring exports back into their own file and check that every
  note hidden as a duplicate has its twin;
- with no chat model given, the unify tier counted that as a failure: it rested, turned away a later call that did
  bring a model, and after three recalls marked notes as unglossable for good; now it is simply not asked, and a
  note's failures count only while the tier answers other requests, or ten minutes apart;
- the check of the centroid account on opening read its two numbers apart, so another writer in between could make
  a sound account look broken and reset it;
- a misconfigured embedder (a wrong model name) was asked twice per recall instead of resting;
- a writer item dated 0001-01-01 (or, on Windows, before 1970) lost the whole capture;
- one exported row with an id or a link that is no number ended the whole import;
- hyphenated words (x-ray, covid-19) were split, unlike before and unlike docs/FORMAT.md;
- a host's own centroid tier without a `floor`, or decision tier without `flush`, failed; a chain inside a chain
  passed no lessons on; an exchange given as a generator was read empty; a very small judging limit returned more
  than the limit.

# Changelog

All notable changes to mneme-llm are listed here. The project follows [semantic versioning](https://semver.org);
before 1.0, a minor version may change the Python API, and this file says how.

## 0.5.0 (2026-11-04)

- **Her feelings are 24 ends on 13 bars** (`gut.BARS`), each a strength of its own rather than a share of one: 难过 or
  开心, 担心 or 踏实, 慌乱·崩溃 or 平静, 嫌弃 or 甜蜜, 严厉 or 温柔, 易怒 or 平和, 委屈 or 不服, 羞愧 or 得意, 害羞 or 调皮, 胆小 or
  大胆, 内向 or 外向, and 吃醋 and 心疼. Both ends of a bar can be strong at once. Her note scores all 24 (0 to 1), so a
  quiet feeling teaches as what it is rather than as nothing; her model's reading names one to three with how strongly;
  the line names at most three. `MOODS` and `NORMAL` are gone; `ENDS`, `CHINESE` and
  `FEELINGS` are new.
- **Her heart and the people she knows.** One network for who she is with anyone, learning from people at closeness 40 or
  more by closeness tier, and one table for each person, holding only what is different with them, learned from anyone,
  read on top of her heart and counting more as she knows them (`COUNTS`, `MOST`). A talking day without someone fades
  them back toward her heart (`PULL`); talking again brings them back. `Gut.feel` takes the subject; `Turn` passes it.
- **She grows up.** A lesson moves her heart about twenty times as far on her first day as once grown (`tau`, 150
  lessons, grown at five times it). Sleep settles the lessons since her last sleep and replays nothing older, so a sleep
  no longer takes back what she learned; her starter is a lean, trained gently, not replayed.
- **Slow levels against her own usual.** `Tone` keeps `lately` and `usual` from the same readings, so nothing is off by
  the difference between two ways of asking; SAN (calm against hysterical) and self-esteem (proud against ashamed) go
  into the line when lately is far from usual.
- **Settings.** `Gut(tau=, zone=)`, `Gut.configure(tau, sensitivity)` (敏感 or 钝感: how hard every moment hits her),
  `Gut.tune(end, now=, nature=)` (where she is lately, fading; a nudge to who she is, never learned away) and
  `Gut.set_age` (young again, forgetting nothing). They outlast `wipe`.
- **Locks and dials by hand.** `Gut.configure(locked=True)` stops her heart learning and growing up.
  `Gut.tune_person(subject, end, nature, weight=, locked=)` sets how she is with one person: a nudge with them alone,
  how much what is different with them counts, and a lock (what they say teaches nothing, and they do not fade).
  `Gut.lock_side(name, often=, what=)` keeps her in one side for good, shown in that share of her turns, for everyone;
  `Gut.unlock_side()` draws again. `Relations.lock(subject, closeness)` and `unlock` keep a person's closeness where it
  is put, kept in the config as `relations.locked`. The `mneme-llm gut` command (`show`, `set`, `tune`, `person`,
  `side`) and `mneme-llm relate --lock/--unlock` do the same from the command line. Forgetting a person removes what was
  set for them.
- **The tuner** (`docs/tune/`, on the docs site): her gut file and memory file dragged into a page, the same dials and
  locks set there, and the files saved back, all in the browser (sql.js); each part a list with one editor.
- **A word she says mostly to one person is theirs** (`OWN`, 80% of its uses): their name or their in-joke shows in her
  line only with them, never to someone new.
- **Forgetting a person** removes how she is with them, their name from its lessons and the sides only they wanted;
  what they did to her heart stays, and her month in a side goes on.
- **Closeness moves with how she takes a person,** not with the calendar: each exchange they start moves it by the mood
  judge's level for it, `relations.liking` (0.25) points a level times the room left in the band that way. A talk
  that leaves her as she was moves nothing; fading without contact is as before. `Relations(growth=)` is now
  `Relations(liking=)`, and `relations.growth` is read from older files but no longer used.
- **Fixed:** an objection while she was in a side she was given counted against a side that had grown; a starter that
  cannot be read is now an error, not a blank gut.
- **Migration:** a gut file from 0.4 is lived again under these rules the first time it wakes; its lessons and starter
  teach only the seven feelings they knew.

## 0.4.0 (2026-11-03)

- **The gut (CMP): what stays of a companion when her memory is wiped and her model is swapped.** `mneme_llm.gut`: `Gut`
  and `Turn`. Her model reads each message into a small form, a tiny network of her own and her vote give seven numbers,
  a balance that moves by itself weighs them, and one line of fixed size goes beside the message, with her word habits,
  her 属性 and the language to answer in. She writes a private note after she has answered, so nothing is hidden in her
  reply; lessons are forms and feelings, never messages, and she sleeps on them. A host needs two moments: the message
  before she answers, and the finished turn after. It needs no dependency, and the rest of the package does not use it.
  `tests/gut_vectors.json` pins its numbers for ports to other languages.
- **Sides that grow from chat.** A short reading after each reply notes when a person calls her a kind of character, asks
  for one, enjoys it or objects. Wanted on separate days by someone close, it becomes a side: a name and one sentence
  from her model, kept in the gut, so it outlasts her memory and her model. Objecting takes it away. `Gut.write_side` and
  `Gut.drop_side` let a person step in. A side's name comes from one list, `NAMES` (`names=` for your own).
- **One side at a time, for a month at least.** She stays in a side, then her sides are drawn again by weight: what people
  asked for, half gone in three months, plus any number set by hand. `Gut.holding` says which, `Gut.weight` how much.

- **The surface: what was said lately, as real turns.** `Mneme.surface` (`surface.py`) is the newest part of Episodes,
  not a second store: the exchanges after one id. `read` gives chat messages, `slice` the newest few. It keeps what the
  last 30 talking days hold, never less than 70,000 tokens; nothing leaves until it holds twice that, and then `alet_go`
  turns the older part into a summary, with every word still in Episodes. 504,000 tokens is the top, or 80% of a smaller
  model's window. Whoever sends the context compacts it. `memory.surface_days`, `surface_floor`, `surface_cap`,
  `surface_window`.
- **A person's first prompt.** The first thing they say is kept apart from the conversation, where it does not fade.
  `Surface.set_first`, `first` and `drop_first` let them see and change it; `send_first` puts it in front of the surface,
  off by default, since they may have grown away from it.
- **`Mneme.look` and `alook` bring a search with them.** With `search=True`, `found` exchanges by relevance alone come
  with the look, however faded, from one ranking, rehearsing nothing. `own=True` leaves out the data label for a person's
  own conversation.
- **`Mneme.wipe`.** What she remembers of a person gone, and who they are to her kept.
- **Talking days.** Fading, the surface, closeness and the daily quota of notes all count days the person talked, turning
  at 4 in the morning: nobody forgets by being away or by sleeping. An exchange is rehearsed once a talking day at most
  (ten searches in an evening took S from 30 to 1,730).

### Upgrading to 0.4.0

**Your file.** The schema is now 2, and a file of schema 1 is refused until you make it current. Stop what uses it, back
it up, and run this once; it works in one transaction per file, says what it did, and is safe to run twice:

    python -m mneme_llm.migrate companion.db

It gives every exchange its talking day (in the zone of `companion.zone`) and tokens, rebuilds surfaces, drops what nothing
reads, and deletes config keys no version knows. The search indexes are rebuilt at the first search. Exports are schema 2
too: `surfaces` rows carry `cleared_at`, and those of an earlier build are not read.

**Your code.** Backward compatibility was not kept. What goes, and what to do instead:

- `Mneme(meaning_micro=)` and word centroids: meaning is embeddings, then unify. `Mneme(judge=)` no longer falls through to
  `complete`: the judge answers in its place, and one that fails gives no answers, is logged, and is counted in
  `m.report()["decisions"]`. `m.decider` is gone.
- `Chain`, `Decider`, `TierStats` and `Question`: call `Prompt(complete).adecide(text, questions)`. `mneme_llm.decide` is one
  module. `Answer` has no `type`: it is `Answer(name, probabilities, confidence, by, reason)`. `fit` is in `mneme_llm.text`.
- `Mood.judge`, `ajudge` and `decider`: judge, then `Mood.apply_answers`, or call `aobserve`.
- `surface.read`, `slice` and `alet_go` no longer take `conversation=`: the surface follows the person into any chat.
  `Surface.let_go` is gone: `await alet_go`. `Surface.noticed` takes the exchange's lines.
- `surface.began` is when it was last cleared or shortened, and a surface starts at an id, so an exchange kept with an `at`
  from before a clear is on it.
- `Episodes.look(shorten=)`, `Episodes.render(header=)`, `Episodes.newest` (`Episodes.after(subject, 0, tokens)`),
  `Episodes.day_of` (`dates.talking_day`), `People.subjects`, `Toolbox.display_language`, `capture.WORTH` (`WORTH_NAME`),
  `text.script` (`text.scripts`), `People(clock=)`.
- `Mneme.look` and `alook` keep their arguments; `Episodes.look(more=)` is how a search comes with a look.

**What behaves differently.** Dropping a first prompt keeps it dropped: the next message does not take its place, and
`erase` clears that. A companion who spoke first is not a person's first prompt. `read` and `slice` always hold the newest
exchange, even alone over the budget. Linking two people with surfaces keeps the lower start, and both summaries.
`mneme-llm subjects` lists everyone anything is kept of, and `Memory.subjects` includes people with only hidden notes.

## 0.3.0 (2026-10-29)

- **Episodes: what was said, word for word.** `aobserve` now keeps every exchange the person starts, as it was
  said (`(who, said)` lines), with when (`at=`, now by default) and where (`conversation=`), before anything else
  and with no model call, then embeds it; `keep=False` leaves it out, and `Observation.episode` is what was kept.
  `Mneme.episodes` (`Episodes`, in `episodes.py`) keeps, ranks, fades and shows them: BM25 over their words fused by
  reciprocal rank with embedding similarity, and a forgetting curve (R = e^(−t/S), S 30 days to start,
  `memory.said_days`) along which each exchange is rehearsed when a search finds it or a later exchange is about the
  same thing.
- **The look:** `aprompt(..., said=6000)` (and `prompt`) adds what was said before that bears on the message, after
  the notes: the best exchanges within that many characters (`memory.said_budget` for `Mneme.look`/`alook`) that
  are close enough to the message, the more faded the closer (the embedding model's floor plus 0.08 when fresh,
  plus 0.16 fully faded: `memory.said_cut`, `memory.said_cut_faded`; so small talk usually brings nothing),
  dated and in the order they were said, under a header that asks the model to check that
  it is about the same person and the same thing and to say it doesn't remember otherwise. `skip=` leaves out the
  newest exchanges of `conversation=` that the host still shows; `search=True` tells the model to search first,
  and when nothing comes to mind, that is all the look says. `Episodes.look(shorten=True)` shows a faded exchange
  in part instead.
- **Two tools:** `search` (the best exchanges the model has not seen yet this turn, by relevance alone, however
  faded; each is rehearsed; long messages shortened) and `read` (an exchange in full, with the ones before and after
  it). `specs()` now lists six tools; a `Toolbox` remembers what its searches showed (`new_turn()` forgets it, and
  and each comes back two minutes after it was shown, for a host such as the MCP server that never says when a turn
  ends).
- **Keeping it small and safe:** who said a line is not a search word (it is in every exchange); a person's vectors
  stay in memory for the 16 people looked at last; an embedder turned on late catches up 256 exchanges at a time, the one just said first;
  importing the same export twice keeps each exchange once; `skip` finds a conversation by the name it was kept under.
- **Measured** on LoCoMo (four conversations, 704 questions, DeepSeek V4.1 Flash answering and judging;
  `bench/locomo.py`): a first look of 6,000 characters with the two tools and the person check answered 80.8%, the
  whole conversation in the prompt 79.1%, the students' notes alone 57.2% of the answerable ones; fading the look
  changed nothing (79.8%, 80.5% with searches rehearsing what they find), fading the searches too lost 18 points.
  On LongMemEval-M (60 questions, each with its own history of about 480 sessions and 1.2 million tokens, put
  through the library itself; `bench/longmemeval.py`): the look of 6,000 characters alone answered 60%, the look
  with the tools 80–85%, and the model given only the sessions that hold the answer 93%. LoCoMo's same 704 questions
  through the library itself (`bench/longmemeval.py --locomo`): the look with the tools 82.7%. The look's bar answered
  alike (LoCoMo 82.4%, LongMemEval-M 49 of 60 against 51, within the noise) and left about three looks in four at chit-chat empty; a
  look weighted by fading instead lost 3 of 60, and a bar at a percentile of the person's own pairs emptied 98% of
  LoCoMo's looks.
- `erase` removes a person's exchanges, a link joins them, export and import carry them (`"episodes"`). New
  tables within schema 1: `episodes`, `episode_terms`, `episode_vectors`, `episode_spread`. Files from 0.1 and 0.2
  gain them on open; 0.2 still opens files that have them (and leaves them alone).
- `exchange.as_lines` gives an exchange as `(who, said)` pairs; a line whose text is None is now empty, not "None".
  `Meaning.embed(texts)` gives tier 1's vectors for any texts. With numpy installed, a person's exchanges are
  compared in one step (it stays optional).

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
  0.1 opens files that have it, but does not read it. Every write looks up the person inside its own transaction, so a link made at the
  same time (another thread or process) never leaves a row under the account.
- **An architecture page** made from the code (`docs/architecture/`, by `tools/architecture.py`): the whole package,
  then each folder, file, class and function with its code, and the path of one exchange; it works on a phone, and
  `tests/test_architecture.py` fails when it falls behind the code.
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

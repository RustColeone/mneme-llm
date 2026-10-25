# Changelog

All notable changes to mneme-llm are listed here. The project follows [semantic versioning](https://semver.org);
before 1.0, a minor version may change the Python API, and this file says how.

## 0.1.0 (unreleased)

The first release.

- **Memory:** one-line notes with kinds that age differently, keys that replace older notes and keep the history,
  duplicate detection, a daily quota for notes a model writes on its own, pruning, soft delete, `purge` and
  `erase`.
- **Recall:** rare-word evidence (Latin words; Chinese, Japanese and Korean characters and character pairs; jieba
  optional), freshness, importance and feeling, a budget with pinned and fill-in notes, explanations and a recall
  log; rendered with human dates under a header marking the notes as data, not instructions.
- **Meaning, in three tiers:** embeddings (OpenAI `text-embedding-3-small` at 256 dimensions, or any function),
  word centroids learned from them (optional), and the host's chat model unifying notes into one language and
  translating queries. Vectors are kept per embedder.
- **Mood:** a value and seven feelings per person with decay on read, judged by expected values, with the
  guardrails of dsh-feiyu-mood and news told once.
- **Decisions, in three tiers:** GPT-6 Luna's Decisions API, a local micro model per question trained on Luna's
  answers (optional), and the host's chat model.
- **`observe`:** after each exchange, one decision request judges the mood and whether anything is worth
  remembering; a note writer runs only then. `reflect` rewrites the profile card.
- **Interfaces:** tool definitions for OpenAI-style, responses, Claude, Gemini and MCP; an MCP server; the
  `mneme-llm` command.
- **Languages:** English and Chinese for everything shown to people and models, and for the documentation.
- **File format:** schema 1, documented in `docs/FORMAT.md`, with additive migrations.

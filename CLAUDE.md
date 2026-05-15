# CLAUDE.md
## RAG Knowledge Base — Persistent Agent Instructions

This file is read by Claude Code at the start of every session.
It governs behavior across all PRD versions. Do not modify it without Isaac's explicit instruction.

---

## Project Overview

A personal RAG knowledge base that ingests Instagram posts and Reels forwarded via Telegram,
extracts structured knowledge using LLMs, stores vectors in ChromaDB, and writes
human-readable notes to an Obsidian vault. Semantic search is exposed via a CLI tool.

**Owner:** Isaac Vélez Aguirre
**Stack:** Python 3.11+, python-telegram-bot, OpenAI/Anthropic APIs, ChromaDB, Obsidian, ffmpeg
**Current PRD:** `PRDs/PRDv2.md`

---

## Project Structure

```
rag-knowledge-base/
├── CLAUDE.md                    ← you are here
├── PRDs/
│   └── PRDv1.md
├── bot/
│   └── bot.py
├── pipeline/
│   ├── __init__.py
│   ├── ingest.py
│   ├── vision.py
│   ├── transcriber.py
│   ├── extractor.py
│   ├── embedder.py
│   ├── store.py
│   └── obsidian_writer.py
├── models/
│   └── schema.py
├── search.py
├── config.py
├── config.yaml
├── .env.example
├── requirements.txt
└── README.md
```

Do not create files outside this structure without Isaac's approval.
Do not rename existing files.

---

## Non-Negotiable Rules

These apply in every session, regardless of which PRD is active.

**1. Read the active PRD before writing any code.**
The active PRD is listed under "Current PRD" above. Run `cat` on it at session start.
If the file does not exist, stop and tell Isaac before doing anything.

**2. Schema is a contract.**
`models/schema.py` is the interface between all pipeline stages.
Never modify field names, types, or defaults without Isaac's explicit approval.
New fields may only be added when a new PRD explicitly requires them.
Always state what you are changing and why before touching this file.

**3. Config over hardcoding.**
No model names, file paths, collection names, or API keys in application code.
All come from `config.yaml` (via the `Config` singleton in `config.py`) or `.env`.
If you find yourself writing a string literal that looks like a path or model name, stop.

**4. One milestone at a time.**
Complete the current milestone, verify it against the acceptance criteria in the active PRD,
then report completion and wait for Isaac's go-ahead before starting the next one.
Do not chain milestones automatically.

**5. Ask before assuming.**
If a requirement is ambiguous, a dependency is missing, or two requirements conflict,
stop and ask. Do not resolve ambiguity silently and do not make a judgment call
on anything that affects the schema, the file structure, or the PRDv2 hooks.

**6. PRDv2 hooks are sacred.**
Comments listed in the active PRD's hooks section must be placed with exact text
at the exact locations specified. These are machine-readable handoff points between
PRD versions. Do not paraphrase them, do not move them, do not delete them.

**7. No unrequested features.**
If something seems like an obvious improvement but is not in the active PRD,
do not build it. Flag it as a suggestion instead. PRDs are the change mechanism.

---

## Code Style

- **Python 3.11+.** Use native type hints (`list[str]`, `str | None`), not `typing` imports.
- **Async throughout.** The Telegram bot is async; keep the entire pipeline async-compatible.
- **Pydantic v2** for all data models. Use `model_validate()`, not `parse_obj()`.
- **Explicit over implicit.** Function signatures must show all parameters and return types.
- **No bare `except`.** Always catch specific exception types. Log the exception before re-raising.
- **Docstrings on all public functions.** One line describing what it does, not how.
- **No print statements in pipeline code.** Use Python `logging` with the module logger.
  The bot may use `logging` to report status messages to Isaac via Telegram.

---

## Environment

- **OS:** macOS (primary), Ubuntu 22.04 (must also work)
- **Python:** 3.11+. Use a virtual environment. Never modify system Python.
- **ffmpeg:** Must be on PATH. Check at startup in `config.py` and raise `RuntimeError` with
  install instructions if missing.
- **API keys:** Loaded from `.env` via `python-dotenv`. Never log, print, or expose them.
- **ChromaDB:** Runs embedded (no server). Persistent at `config.storage.chroma_path`.
- **Obsidian vault:** Local folder. Path from `config.obsidian.vault_path`. Expand `~`.

---

## Adding a New PRD Version

When Isaac provides a new PRD (e.g. `PRDs/PRDv2.md`):

1. Update "Current PRD" at the top of this file to point to the new PRD.
2. Read the new PRD in full before writing any code.
3. Identify all PRDv2 hooks from the previous PRD that this version activates —
   replace the hook comments with real implementation.
4. Do not remove hook comments for PRD versions that are not yet active.
5. Extend `models/schema.py` only if the new PRD explicitly requires new fields.
   All additions must be backward-compatible (new fields must have defaults).

---

## Known Decisions & Rationale

Record decisions here as they are made, so future sessions have context.

| Decision | Rationale | PRD |
|----------|-----------|-----|
| Embed `entry.embed_text` (title + concept + tags), not raw post text | Raw Instagram text is noisy; cleaned extraction gives better retrieval quality | v1 |
| ChromaDB collections parameterized from day one | Multi-topic support requires zero architectural change in PRDv2 | v1 |
| Video → Whisper, not vision LLM | Vision models process frames; Whisper processes speech across time. Reels are primarily audio-driven | v1 |
| Single `default` collection in MVP | Simplicity; routing logic added in PRDv2 without schema changes | v1 |
| `ExtractionOutput` separate from `KnowledgeEntry` | LLM output is untrusted; validate separately before merging into the main entry | v1 |

---

## Suggestions Backlog

Features flagged during implementation but deferred. Bring these to Isaac's attention
when planning future PRDs — do not implement without a PRD.

<!-- Add entries here as: - [Session date] Description of suggestion -->
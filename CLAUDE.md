# CLAUDE.md
## RAG Knowledge Base — Persistent Agent Instructions

This file is read by Claude Code at the start of every session.
It governs behavior across all PRD versions. Do not modify it without Isaac's explicit instruction.

---

## Project Overview

A personal RAG knowledge base that ingests Instagram posts and Reels forwarded via Telegram,
extracts structured knowledge using LLMs, stores vectors in ChromaDB, writes
human-readable notes to an Obsidian vault, and syncs them to GitHub.
Deployed on Fly.io. Semantic search via CLI and Telegram `/search` command.

**Owner:** Isaac Vélez Aguirre
**Stack:** Python 3.11+, python-telegram-bot, OpenAI APIs, ChromaDB, Obsidian, ffmpeg, yt-dlp, Fly.io
**Current PRD:** `PRDs/PRDv3.md`
**Completed PRDs:** PRDv1 ✅, PRDv2 ✅

---

## Project Structure

```
rag-knowledge-base/
├── CLAUDE.md                    ← you are here
├── PRDs/
│   ├── PRDv1.md
│   ├── PRDv2.md
│   └── PRDv3.md
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
│   ├── obsidian_writer.py
│   └── vault_sync.py
├── models/
│   └── schema.py
├── scripts/
│   └── entrypoint.sh
├── search.py
├── config.py
├── config.yaml
├── Dockerfile
├── fly.toml
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
The active PRD is listed under "Current PRD" above. Read it in full at session start.
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
stop and ask. Do not resolve ambiguity silently.

**6. Hook comments are sacred.**
Comments listed in the active PRD's hooks section must be placed with exact text
at the exact locations specified. These are machine-readable handoff points between
PRD versions. Do not paraphrase them, do not move them, do not delete them.

**7. No unrequested features.**
If something seems like an obvious improvement but is not in the active PRD,
do not build it. Flag it as a suggestion instead. PRDs are the change mechanism.

**8. Update README.md when completing a PRD.**
When all milestones of a PRD are verified, update `README.md` to reflect the current
state of the system — architecture, setup instructions, commands, design decisions,
and the "What's next" section. The README is portfolio-facing and must stay current.

---

## Code Style

- **Python 3.11+.** Use native type hints (`list[str]`, `str | None`), not `typing` imports.
- **Async throughout.** The Telegram bot is async; keep the entire pipeline async-compatible.
- **Pydantic v2** for all data models. Use `model_validate()`, not `parse_obj()`.
- **Explicit over implicit.** Function signatures must show all parameters and return types.
- **No bare `except`.** Always catch specific exception types. Log the exception before re-raising.
- **Docstrings on all public functions.** One line describing what it does, not how.
- **No print statements in pipeline code.** Use Python `logging` with the module logger.

---

## Environment

- **OS:** macOS (primary dev), Fly.io Ubuntu container (production)
- **Python:** 3.11+. Use `.venv/` locally. Container uses system Python.
- **ffmpeg:** Must be on PATH. Checked at startup in `config.py`.
- **API keys:** Loaded from `.env` via `python-dotenv` locally; Fly.io secrets in production.
- **ChromaDB:** Embedded, persistent at `config.storage.chroma_path` (local: `./data/chroma`; production: `/data/chroma`).
- **Obsidian vault:** `config.obsidian.vault_path` locally; `/data/vault` in production (overridden by `VAULT_PATH` env var).
- **Fly.io secrets:** `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `TELEGRAM_ALLOWED_USER_ID`, `GITHUB_PAT`, `VAULT_PATH`, `CHROMA_PATH`, `INSTAGRAM_COOKIES_B64`.

---

## Adding a New PRD Version

When Isaac provides a new PRD (e.g. `PRDs/PRDv3.md`):

1. Update "Current PRD" at the top of this file to point to the new PRD.
2. Update "Completed PRDs" to include the previous one.
3. Read the new PRD in full before writing any code.
4. Identify all hook comments from the previous PRD that this version activates —
   replace the hook comments with real implementation.
5. Do not remove hook comments for PRD versions that are not yet active.
6. Extend `models/schema.py` only if the new PRD explicitly requires new fields.
   All additions must be backward-compatible (new fields must have defaults).
7. Update `README.md` when all milestones are complete.

---

## Known Decisions & Rationale

| Decision | Rationale | PRD |
|----------|-----------|-----|
| Embed `entry.embed_text` (title + concept + key_takeaway + tags) | Cleaned extraction is semantically denser than raw noisy Instagram text | v1, v2 |
| ChromaDB collections parameterized from day one | Multi-topic support requires no architectural change — only activating PRDv3 hooks | v1 |
| Video → Whisper, not vision LLM | Reels are audio-driven; Whisper captures speech across the full timeline | v1 |
| `ExtractionOutput` separate from `KnowledgeEntry` | LLM output is untrusted; validate before merging into the main entry | v1 |
| Image posts use `/media/?size=l`, not yt-dlp | yt-dlp requires Instagram session for image posts; this endpoint is public | v1 (corrected) |
| Caption from `og:description` with FB crawler UA | Instagram serves full caption to Facebook crawlers without login | v1 (corrected) |
| `content_type` + `key_takeaway` fields | Original prompt missed strategic/professional context of non-tutorial posts | v2 |
| `GITHUB_PAT` + `git_remote_repo` split | PAT never appears in any committed file; repo URL is safe to commit | v2 |
| Git identity configured in VaultSync | Containers have no git identity by default; silent commit failure returns exit 0 | v2 |
| Instagram cookies as Fly.io secret (base64) | Datacenter IPs get rate-limited by Instagram for Reels without auth | v2 |
| `fly apps create` instead of `flyctl launch` | `flyctl launch` chokes on `[[mounts]]` section; direct app creation is reliable | v2 |

---

## Suggestions Backlog

Features flagged during implementation but deferred. Bring to Isaac's attention when planning future PRDs.

- [2026-05-15] Obsidian deep links in `/search` results (`obsidian://open?vault=...`) — only work on local machine, not mobile. Suggested for PRDv3.
- [2026-05-15] Anki flashcard export from knowledge entries — useful for active recall of saved content.
- [2026-05-15] Batch ingestion — send multiple URLs in one message.
- [2026-05-15] Filtering by `content_type` or `difficulty` in `/search` — e.g. `/search pandas --type technical-tutorial`.

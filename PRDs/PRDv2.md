# Product Requirements Document
## Personal RAG Knowledge Base — v2

**Author:** Isaac Vélez Aguirre
**PRD Version:** 2.0
**Status:** Ready for implementation
**Date:** May 2026
**Executor:** Claude Code
**Previous PRD:** PRDv1.md
**Next PRD:** PRDv3 — Weekly digest & FastAPI REST layer

---

## 0. Instructions for Claude Code

- **Read PRDv1.md before touching any existing code.** PRDv2 extends it additively. Do not remove or rename anything from v1 unless this document explicitly says to.
- **Activate PRDv1 hooks.** Section 12 of PRDv1 lists four hook comments. PRDv2 activates the `/search` hook. Replace those specific comments with real implementation; leave the remaining hooks intact.
- **Schema is still a contract.** New fields added in Section 6 must have defaults so all existing `KnowledgeEntry` instances remain valid. State what you are adding and why before touching `models/schema.py`.
- **One milestone at a time.** Complete and verify each milestone before reporting done. Wait for go-ahead before starting the next.
- **Hosting is the last milestone.** Do not write Dockerfile or deploy config until M7 (vault sync) is verified locally. A broken local system deployed to the cloud is harder to debug.
- **Ask before assuming** on anything that touches the schema, the file structure, or the PRDv3 hooks.

---

## 1. Problem Statement

PRDv1 built a working local pipeline. Three gaps remain:

1. **Extraction quality** — the prompt is tuned for technical tutorials and misses the big picture of posts about ML projects, career advice, or industry trends. A post showcasing someone's end-to-end ML system is saved with only its technical components extracted; the strategic insight (what problem it solves, why the architecture matters) is lost.

2. **Access** — retrieval requires a laptop and a terminal. The bot cannot be queried from Telegram, and the system goes offline whenever the laptop sleeps.

3. **Version control and portability** — the codebase has no git history, no CI, and no reproducible deployment.

---

## 2. Scope

### 2.1 In Scope — PRD v2

| Feature | Notes |
|---------|-------|
| GitHub repository + `.gitignore` + CI | M1 |
| Broadened extraction prompt + `content_type` field | M2–M3 |
| Duplicate detection before ingestion | M4 |
| `/search` Telegram command | M5 — activates PRDv1 hook |
| `/recent` and `/stats` Telegram commands | M6 |
| Vault Git sync (auto-commit + push after every write) | M7 |
| Hosting on Fly.io or Railway with persistent volume | M8 |
| End-to-end test on hosted instance | M9 |

### 2.2 Out of Scope — PRD v2 (planned for future PRDs)

| Feature | Target PRD |
|---------|-----------|
| Multi-collection / topic namespacing | PRDv3 |
| Weekly digest via Telegram | PRDv3 |
| FastAPI REST layer | PRDv3 |
| Source-agnostic ingestion (YouTube, Twitter/X) | PRDv4 |
| Retrieval reranking | PRDv4 |

---

## 3. Functional Requirements

### 3.1 GitHub Repository (`M1`)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-G1 | Initialise a git repository in the project root | Must |
| F-G2 | Create `.gitignore` excluding: `.env`, `.venv/`, `data/chroma/`, `__pycache__/`, `*.pyc`, `*.wav`, `*.mp4`, `.DS_Store` | Must |
| F-G3 | `data/directory.csv` must **not** be gitignored — it is lightweight and useful to track | Must |
| F-G4 | Push to a new private GitHub repository | Must |
| F-G5 | Add a GitHub Actions workflow (`.github/workflows/ci.yml`) that runs on every push: `python -m py_compile` on all `.py` files and `python -c "from config import Config"` to catch import errors | Must |

### 3.2 Broadened Extraction Prompt (`M2–M3`)

**Problem:** The current system prompt instructs the model to focus on tools, techniques, and code. This produces excellent extractions for step-by-step tutorials but discards the strategic layer of posts about projects, career paths, or industry context.

**Solution:** Add a `content_type` classification step and rewrite the `concept` and `key_takeaway` fields to capture both the technical and strategic dimensions.

#### Schema additions (`models/schema.py`)

```python
# Added in PRDv2 — both fields have defaults for backward compatibility
content_type: Literal[
    "technical-tutorial",   # step-by-step how-to, code tricks
    "project-showcase",     # someone's end-to-end system or portfolio piece
    "tool-overview",        # introduction to a library, framework, or service
    "career-advice",        # job search, interviews, professional growth
    "industry-insight",     # trends, research, market observations
    "general",              # motivational, lifestyle, or uncategorised
] | None = None

key_takeaway: str = ""      # one sentence: what a practitioner should remember
```

`ExtractionOutput` gains the same two fields (both required, `content_type` has no default in the LLM response — the model must always classify).

#### Updated extraction system prompt

Replace the existing `_SYSTEM_PROMPT` in `pipeline/extractor.py` with the version below. **Do not paraphrase — use the exact text.**

```
You are extracting structured knowledge from an Instagram post for a personal RAG knowledge base.
The post may contain a description of an image, a video transcript, or raw text.
Content can be technical tutorials, project showcases, career advice, tool introductions, or industry insights.
Capture BOTH the technical detail AND the strategic or professional significance of the post.

Return ONLY a valid JSON object. No markdown, no explanation, no code fences.
The JSON must match this exact structure:
{
  "title": "string, max 10 words, descriptive",
  "content_type": "technical-tutorial | project-showcase | tool-overview | career-advice | industry-insight | general",
  "concept": "string, 2-3 sentences: explain the core idea AND why it matters professionally or strategically",
  "key_takeaway": "string, one sentence: the single most useful thing a practitioner should remember",
  "tags": ["lowercase-hyphenated", "tools", "techniques", "libraries", "themes"],
  "code_snippets": [{"language": "python", "code": "the code here"}],
  "use_cases": ["practical application 1", "practical application 2"],
  "difficulty": "beginner | intermediate | advanced",
  "source_url": "string or null"
}

Rules:
- content_type must always be set; choose the best fit from the list above
- concept must not be limited to technical details — include the bigger picture if present
- key_takeaway is one sentence, practical, and memorable
- tags must be lowercase and use hyphens for multi-word terms (e.g. "machine-learning", not "machine learning")
- code_snippets is an empty list if no code is present
- difficulty must always be set; infer from context if not explicit
- source_url is null unless a URL is present in the input text
```

#### Updated `ExtractionOutput` (`models/schema.py`)

```python
class ExtractionOutput(BaseModel):
    title: str
    content_type: Literal[
        "technical-tutorial", "project-showcase", "tool-overview",
        "career-advice", "industry-insight", "general"
    ]
    concept: str
    key_takeaway: str
    tags: list[str]
    code_snippets: list[CodeSnippet] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    difficulty: Literal["beginner", "intermediate", "advanced"]
    source_url: str | None = None
```

#### Updated Obsidian `.md` format

Add `content_type` to YAML frontmatter and insert `## Key takeaway` as the first body section:

```markdown
---
id: {entry.id}
date: {entry.date}
collection: {entry.collection}
content_type: {entry.content_type}
tags: [{comma-separated tags}]
difficulty: {entry.difficulty}
source_url: {entry.source_url or null}
input_type: {entry.input_type}
obsidian_path: {resolved path}
---

## Key takeaway
{entry.key_takeaway}

## Concept
{entry.concept}

## Use cases
{bulleted list of entry.use_cases}

## Code
{fenced code blocks or "No code snippets."}

## Raw input
{entry.raw_text[:500]}{" [truncated]" if len > 500 else ""}
```

### 3.3 Duplicate Detection (`M4`)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-D1 | Before running the full pipeline, check if `source_url` already exists in ChromaDB metadata | Must |
| F-D2 | If an exact URL match is found, reply: `"Already saved: {existing_title}. Send again to force re-ingest."` and halt | Must |
| F-D3 | If the user sends the same URL a second time (within the same session or across sessions), treat it as a forced re-ingest and proceed, upserting the existing entry | Must |
| F-D4 | Add `Store.find_by_url(source_url: str) -> str | None` that returns the existing entry title if found, or `None` | Must |

**Implementation note:** ChromaDB does not support metadata equality queries natively in v0.5.x. Implement `find_by_url` by querying with `where={"source_url": source_url}` on `collection.get()` — this is supported via ChromaDB's metadata filtering.

**State management for force re-ingest:** Store the set of "force URLs" in `context.user_data` (python-telegram-bot per-user dict, persisted in memory). Clear the entry after the force re-ingest completes.

### 3.4 `/search` Telegram Command (`M5`)

Activates the PRDv1 hook: `# PRDv2: multi-collection routing` in `bot/bot.py`.

| ID | Requirement | Priority |
|----|-------------|----------|
| F-S1 | `/search <query>` — embed query and return top 5 results formatted identically to `search.py` default output | Must |
| F-S2 | `/search <query> --k <n>` — support optional `--k` flag for result count | Should |
| F-S3 | Each result includes: title, concept preview (100 chars), tags, difficulty, Obsidian path | Must |
| F-S4 | If ChromaDB is empty or query returns no results, reply: `"No results found for: <query>"` | Must |
| F-S5 | `/search` with no arguments: reply with usage hint | Must |

### 3.5 `/recent` and `/stats` Telegram Commands (`M6`)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-R1 | `/recent` — show the last 5 ingested entries (title, date, difficulty, content_type) read from `directory.csv` | Must |
| F-R2 | `/recent <n>` — show last n entries, max 20 | Should |
| F-R3 | `/stats` — reply with: total entries, breakdown by content_type, breakdown by difficulty, breakdown by input_type | Must |
| F-R4 | `/stats` reads from `directory.csv` — do not query ChromaDB for stats | Must |

**Example `/stats` output:**
```
📊 Knowledge Base Stats
Total entries: 47

By type:
  technical-tutorial  28
  project-showcase     9
  tool-overview        6
  career-advice        3
  industry-insight     1

By difficulty:
  beginner       12
  intermediate   27
  advanced        8

By source:
  image    31
  video    16
```

### 3.6 Vault Git Sync (`M7`)

After every successful `ObsidianWriter.write()`, the vault directory is committed and pushed to a private GitHub repository. The user's local Obsidian instance, with the [Obsidian Git](https://github.com/denolehov/obsidian-git) plugin configured to auto-pull, receives every new note within minutes.

| ID | Requirement | Priority |
|----|-------------|----------|
| F-V1 | After `ObsidianWriter.write()` succeeds, call `VaultSync.commit_and_push(entry)` | Must |
| F-V2 | Commit message: `"Add: {entry.title} [{entry.date[:10]}]"` | Must |
| F-V3 | `VaultSync` is a new class in `pipeline/vault_sync.py` | Must |
| F-V4 | If push fails (no network, auth error), log the error and continue — do not fail the ingestion | Must |
| F-V5 | `vault_sync.enabled` config flag: if false, skip sync entirely (for local-only development) | Must |
| F-V6 | Git remote URL loaded from `config.yaml` field `obsidian.git_remote` | Must |

**`config.yaml` additions:**
```yaml
obsidian:
  vault_path: ~/Documents/ObsidianVault/Knowledge Base
  git_remote: git@github.com:username/obsidian-vault.git   # PRDv3: make optional
  vault_sync_enabled: true
```

**Setup prerequisite:** The vault directory must already be a git repository with the remote configured before the bot starts. Claude Code must add setup instructions to `README.md`.

### 3.7 Hosting on Fly.io / Railway (`M8`)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-H1 | Create `Dockerfile` that builds the bot image using Python 3.11-slim | Must |
| F-H2 | `Dockerfile` installs `ffmpeg` via `apt-get` | Must |
| F-H3 | Create `fly.toml` (or `railway.json`) with: app name, region, volume mount for `/data` | Must |
| F-H4 | `config.yaml` `storage.chroma_path` must resolve to `/data/chroma` in the container | Must |
| F-H5 | All secrets (`TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `TELEGRAM_ALLOWED_USER_ID`) set as platform environment variables — never baked into the image | Must |
| F-H6 | The Obsidian vault path in the container is `/data/vault` — the vault is cloned from `obsidian.git_remote` on first boot | Must |
| F-H7 | Add a startup script `scripts/entrypoint.sh` that: clones the vault if `/data/vault` doesn't exist, then runs `python bot/bot.py` | Must |
| F-H8 | Add deployment instructions to `README.md` | Must |

---

## 4. Schema Extensions (`models/schema.py`)

Additions are backward-compatible (all new fields have defaults).

```python
class KnowledgeEntry(BaseModel):
    # --- all PRDv1 fields unchanged ---

    # Added in PRDv2
    content_type: Literal[
        "technical-tutorial", "project-showcase", "tool-overview",
        "career-advice", "industry-insight", "general",
    ] | None = None

    key_takeaway: str = ""
```

`embed_text` property: extend to include `key_takeaway` for richer retrieval signal.

```python
@property
def embed_text(self) -> str:
    tag_str = " ".join(self.tags)
    return f"{self.title}. {self.concept} {self.key_takeaway} {tag_str}".strip()
```

`directory.csv` gains two new columns: `content_type` and `key_takeaway` (added to `_CSV_COLUMNS` in `store.py`).

Obsidian frontmatter gains `content_type` (added to the `write()` output in `obsidian_writer.py`).

---

## 5. New Files

```
rag-knowledge-base/
├── pipeline/
│   └── vault_sync.py           # VaultSync: auto-commit + push vault after write
├── scripts/
│   └── entrypoint.sh           # Container startup: clone vault if needed, then run bot
├── Dockerfile
├── fly.toml                    # OR railway.json — one, not both
└── .github/
    └── workflows/
        └── ci.yml
```

Do not create any other files without approval.

---

## 6. Configuration (`config.yaml`)

Full additions to the existing `config.yaml`:

```yaml
obsidian:
  vault_path: ~/Documents/ObsidianVault/Knowledge Base
  git_remote: git@github.com:username/obsidian-vault.git
  vault_sync_enabled: true
```

`Config` dataclass gains an `ObsidianConfig` field update: `git_remote: str = ""` and `vault_sync_enabled: bool = True`.

---

## 7. Dependencies (`requirements.txt`)

No new Python packages required. `gitpython` is explicitly **not** used — vault sync runs `git` via `subprocess` to avoid a heavy dependency and to use the system git credentials directly.

---

## 8. Milestones & Acceptance Criteria

### M1 — GitHub repository
**Build:** `.gitignore`, `git init`, push to GitHub, GitHub Actions CI workflow.
**Verify:** Push a trivial change; CI passes. `git log` shows at least one commit. `data/chroma/` is not tracked; `data/directory.csv` is tracked.

### M2 — Schema extension
**Build:** Add `content_type` and `key_takeaway` to `KnowledgeEntry` and `ExtractionOutput` in `models/schema.py`. Update `embed_text` property.
**Verify:** Instantiate `KnowledgeEntry` with and without the new fields; assert `embed_text` includes `key_takeaway`.

### M3 — Broadened extraction prompt
**Build:** Replace `_SYSTEM_PROMPT` in `pipeline/extractor.py`. Update `ObsidianWriter` to write `## Key takeaway` section and `content_type` in frontmatter. Update `Store._upsert_csv` to include new columns. Update `Store._serialize_metadata` to include `content_type` and `key_takeaway`.
**Verify:** Run the extractor against a project-showcase post (e.g. "Here's how I built my ML portfolio site in 3 weeks"). Assert `content_type == "project-showcase"` and `key_takeaway` is non-empty and captures the strategic angle, not just a technical detail.

### M4 — Duplicate detection
**Build:** `Store.find_by_url()`. Update `IngestHandler.process()` to call it. Update `handle_message` in `bot.py` for force re-ingest state.
**Verify:** Ingest a post with a known URL. Send the same URL again — bot must reply "Already saved: ...". Send a third time — bot must re-ingest and reply "Saved: ...".

### M5 — `/search` Telegram command
**Build:** Replace the `# PRDv2: multi-collection routing` stub in `bot/bot.py`. Implement search handler.
**Verify:** `/search pandas groupby` returns at least one result after ingesting a relevant post. `/search` with no args returns a usage hint.

### M6 — `/recent` and `/stats`
**Build:** Two new command handlers in `bot/bot.py`, both reading from `directory.csv`.
**Verify:** `/recent` returns entries sorted by date descending. `/stats` totals match `len(directory.csv) - 1` (header row).

### M7 — Vault Git sync
**Build:** `pipeline/vault_sync.py` with `VaultSync` class. Wire into `ObsidianWriter.write()`.
**Verify:** Ingest one post locally. Confirm a new commit appears in the vault git log. Confirm a local pull (simulated) receives the new file.

### M8 — Hosting
**Build:** `Dockerfile`, `fly.toml` (or `railway.json`), `scripts/entrypoint.sh`. Update `README.md` with deployment steps.
**Verify:** Deploy to Fly.io / Railway. Send one Instagram URL from Telegram. Confirm the bot responds, the note appears in the vault repo, and the local Obsidian picks it up via Obsidian Git within 5 minutes.

### M9 — End-to-end on hosted instance
**Build:** Nothing new.
**Verify:** Over one week, ingest 10 posts via the hosted bot. Run `/search`, `/recent`, and `/stats` from Telegram. All local Obsidian notes are current. Document any issues in `README.md`.

---

## 9. PRDv3 Hooks

Place these comments exactly as shown. PRDv3 will reference them by comment text.

| Comment | Location | Purpose |
|---------|----------|---------|
| `# PRDv3: multi-collection routing` | `pipeline/ingest.py`, line that sets `entry.collection = "default"` | Topic-based collection assignment |
| `# PRDv3: expose multi-collection routing` | `search.py`, `--collection` flag | CLI collection switching |
| `# PRDv3: make git_remote optional` | `pipeline/vault_sync.py`, remote URL check | Allow local-only mode without a remote |
| `# PRDv3: weekly digest hook` | `pipeline/store.py`, after `_upsert_csv()` | Weekly summary generation trigger |

---

## 10. Open Questions

Resolve before starting the relevant milestone.

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| OQ-1 | Fly.io or Railway? Both are valid. Fly.io has better persistent volume support and a larger free tier for always-on bots. | Fly.io / Railway | Fly.io |
| OQ-2 | For `/search` in Telegram, should results include an "open in Obsidian" deep link (`obsidian://open?vault=...`)? These only work on the local machine, not on mobile. | Include / omit / make optional | Omit in v2; add as `Should` in PRDv3 |
| OQ-3 | Vault sync: SSH key or HTTPS token for git push from the server? SSH requires key management; HTTPS with a GitHub PAT is simpler in a container environment. | SSH / HTTPS PAT | HTTPS PAT stored as env var |
| OQ-4 | Should `/stats` and `/recent` be accessible without `TELEGRAM_ALLOWED_USER_ID` check? Currently all commands are gated. | Gated / public | Keep gated — this is a single-user system |

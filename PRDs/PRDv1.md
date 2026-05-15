# Product Requirements Document
## Personal RAG Knowledge Base — v1 (MVP)

**Author:** Isaac Vélez Aguirre
**PRD Version:** 1.0
**Status:** Ready for implementation
**Date:** May 2026
**Executor:** Claude Code
**Next PRD:** PRDv2 — Multi-collection support & `/search` Telegram command

---

## 0. Instructions for Claude Code

This document is the single source of truth for building PRD v1. Follow these rules when implementing:

- **Build only what is specified here.** If something is not in this document, do not build it. Use comments like `# PRDv2: multi-collection routing` to mark places where future work hooks in.
- **Ask before assuming.** If a requirement is ambiguous, stop and ask rather than guess.
- **Schema is a contract.** The `KnowledgeEntry` schema in section 6 must not be modified. Future PRDs will extend it additively.
- **Test each milestone before moving to the next.** Section 11 defines milestone acceptance criteria — satisfy each one before proceeding.
- **Config over hardcoding.** Every path, model name, and API key must come from `config.yaml` or `.env`. No exceptions.
- **File structure is prescribed.** Create files exactly as specified in section 8. Do not reorganize.

---

## 1. Problem Statement

Saving content from Instagram — posts, reels, and short videos — is effortless. Retrieving and applying that content later is not. Saved posts accumulate without structure, are never revisited, and produce no lasting learning or professional value.

The core problem is not capture — it is structured retrieval tied to intent.

This system solves that by turning a casual "forward to Telegram" action into a queryable, semantically searchable personal knowledge base. Content is stored in two parallel outputs: a local vector database for semantic search, and an Obsidian vault for human-readable browsing.

---

## 2. Scope

### 2.1 In Scope — PRD v1
- Receive forwarded Instagram content (image posts, text posts, Reels/videos) via Telegram
- Transcribe video audio to text using Whisper
- Describe images using a vision LLM
- Extract structured knowledge from all input types using an LLM
- Embed extracted content and store in ChromaDB under a single `default` collection
- Write a `.md` file per entry to a local Obsidian vault
- CLI semantic search tool

### 2.2 Out of Scope — PRD v1 (planned for future PRDs)
| Feature | Target PRD |
|---------|-----------|
| Multi-collection / topic namespacing | PRDv2 |
| `/search` Telegram command | PRDv2 |
| Weekly digest via Telegram | PRDv3 |
| FastAPI REST layer | PRDv3 |
| Source-agnostic ingestion (YouTube, Twitter/X) | PRDv4 |
| Retrieval reranking | PRDv4 |

### 2.3 Versioning Convention
Each PRD extends the previous one additively. PRDv2 will reference specific section numbers from this document when describing what changes. Claude Code must not implement anything from the "Out of Scope" table above, but must leave clearly marked hooks for each item.

---

## 3. Users

**Primary user:** Isaac (solo user during all MVP versions)

**Profile:**
- Third-year Data Science & Business Analytics student, incoming Columbia MSAI Fall 2026
- Saves DS/AI/engineering Instagram content daily — posts, carousels, and Reels
- Comfortable with Python and CLI; expects to run the system locally on macOS
- This project also serves as a portfolio artifact demonstrating RAG pipeline competency

**Usage pattern:** Sporadic ingestion (1–15 items/day, mix of posts and videos), retrieval several times per week before starting a project or writing something.

---

## 4. System Architecture

### 4.1 Component Map

```
INGESTION            PROCESSING                        STORAGE            RETRIEVAL
─────────            ──────────                        ───────            ─────────
                     ┌─ [image] ──→ Vision LLM ──┐
Telegram Bot ──────→ ├─ [video] ──→ Whisper ─────┼──→ LLM Extractor ──→ ChromaDB
(bot/bot.py)         └─ [text]  ──────────────────┘    (→ KnowledgeEntry) + Obsidian .md
                         Ingest Handler
                         (pipeline/ingest.py)           Embedder wraps
                                                        extractor output
                                                        before storing
```

### 4.2 Data Flow (step by step)

1. User forwards an Instagram post or Reel to the Telegram bot, optionally appending a personal note
2. Bot extracts: message text, photo bytes (if any), video file (if any), user note
3. Bot passes payload to `IngestHandler.process()`
4. **[Correction — implementation diverges from original spec here]** `IngestHandler` checks whether the message text contains an Instagram URL (e.g. `https://www.instagram.com/reel/...`). If so, it downloads the content via `yt-dlp` before routing. This step was not in the original PRD: the PRD assumed Instagram media would arrive as Telegram-native photo/video attachments, but in practice Instagram's share button sends a URL as plain text. `yt-dlp` resolves the URL to a video file (Reels) or image bytes (posts), which are then handled identically to directly attached media.
5. `IngestHandler` detects input type and routes:
   - **Image** → `VisionDescriber.describe(image_bytes)` → returns descriptive text
   - **Video** → `VideoTranscriber.transcribe(video_file)` → returns transcript text
   - **Text-only** → passes through directly
6. All paths converge on `Extractor.extract(combined_text, user_note)` → returns `KnowledgeEntry`
6. `Embedder.embed(entry)` → generates vector from `entry.embed_text`
7. `Store.upsert(entry, vector)` → writes to ChromaDB `default` collection
8. `ObsidianWriter.write(entry)` → writes `.md` to vault
9. Bot sends confirmation message to user with title and tags

### 4.3 Design Principles

**Single responsibility per module.** Each file in `pipeline/` does exactly one thing. `ingest.py` routes. `extractor.py` calls the LLM. `embedder.py` calls the embedding model. `store.py` talks to ChromaDB. `obsidian_writer.py` writes files. No module imports from another except through defined interfaces.

**Schema is a contract, not an implementation detail.** `KnowledgeEntry` in `models/schema.py` is the interface between all pipeline stages. Every stage reads from or writes to it. It must not be modified in v1; future PRDs extend it additively.

**Collection-aware from the start.** ChromaDB collections are named. MVP uses `default` everywhere. The `collection` field exists in the schema and is passed through every function signature. PRDv2 activates routing logic without changing any function signatures.

**Config over hardcoding.** No model names, paths, or keys in application code. All come from `config.yaml` (loaded once at startup into a `Config` dataclass) or `.env`.

---

## 5. Functional Requirements

### 5.1 Telegram Bot (`bot/bot.py`)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-01 | Accept forwarded messages containing text, photos, videos, or combinations | Must |
| F-01a | **[Correction]** Accept Instagram share URLs sent as plain text (e.g. `https://www.instagram.com/reel/…`). Original spec assumed Telegram-native media attachments; in practice Instagram's share button sends a URL. `IngestHandler` detects the URL pattern and delegates download to `yt-dlp`, which resolves it to a video file or image bytes before the normal routing begins. Requires `yt-dlp` in `requirements.txt`. | Must |
| F-02 | Accept an optional user note: any text the user adds after forwarding | Must |
| F-03 | Acknowledge receipt within 1 second with: "Got it, processing..." | Must |
| F-04 | Pass structured payload `{text, photo_bytes, video_path, user_note}` to `IngestHandler` | Must |
| F-05 | On success: reply with `"Saved: {entry.title} [{', '.join(entry.tags[:3])}]"` | Must |
| F-06 | On any pipeline error: reply with `"Processing failed: {error_type}. Nothing was saved."` | Must |
| F-07 | Download video files to a temp directory before passing to pipeline; clean up after | Must |
| F-08 | `/search` command: out of scope — add stub handler that replies "Coming in v2" | Must |

**Implementation note:** Use `python-telegram-bot` v21 async. Register a single `MessageHandler(filters.ALL)` that dispatches internally. Bot token loaded from `.env` via `TELEGRAM_BOT_TOKEN`.

### 5.2 Ingest Handler (`pipeline/ingest.py`)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-09 | Detect input type from payload: `IMAGE`, `VIDEO`, `TEXT`, `IMAGE_WITH_TEXT`, `VIDEO_WITH_TEXT` | Must |
| F-09a | **[Correction]** Before input-type detection, check if `text` contains an Instagram URL and no media attachments are present. If so, call `_fetch_instagram(url, tmp_dir)` via `yt-dlp` to populate `video_path` or `photo_bytes` and replace `text` with the post caption. Temp dir is always cleaned up in a `finally` block. | Must |
| F-10 | Route `IMAGE` and `IMAGE_WITH_TEXT` to `VisionDescriber` | Must |
| F-11 | Route `VIDEO` and `VIDEO_WITH_TEXT` to `VideoTranscriber` | Must |
| F-12 | Combine transcription/description output with original caption and user note into a single `combined_text` string before passing to extractor | Must |
| F-13 | Assign `entry.id = str(uuid4())` at ingestion time | Must |
| F-14 | Assign `entry.date = datetime.utcnow().isoformat() + "Z"` at ingestion time | Must |
| F-15 | Set `entry.collection = "default"` — hardcoded in v1; leave comment `# PRDv2: derive from user input` | Must |

**`combined_text` construction:**
```
[POST TEXT]
{caption or empty string}

[VISUAL CONTENT]
{vision description or video transcript}

[USER NOTE]
{user_note or empty string}
```

### 5.3 Vision Describer (`pipeline/vision.py`)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-16 | Accept raw image bytes; return a plain text description of the image content | Must |
| F-17 | Prompt must instruct the model to: transcribe all visible text verbatim, describe any diagrams or charts, note code snippets with language if identifiable | Must |
| F-18 | Use model specified in `config.vision_model` | Must |
| F-19 | If image contains no useful technical content, return `"No extractable technical content."` rather than raising | Must |

**System prompt (exact — do not paraphrase):**
```
You are processing an Instagram post image for a technical knowledge base.
Your task:
1. Transcribe ALL visible text verbatim, preserving formatting
2. Describe any diagrams, charts, or visual explanations in detail
3. Identify and reproduce any code snippets, noting the programming language
4. Note any tool names, library names, or technology references visible
Return plain text only. No formatting, no preamble.
```

### 5.4 Video Transcriber (`pipeline/transcriber.py`)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-20 | Accept a local video file path; return plain text transcript | Must |
| F-21 | Extract audio from video using `ffmpeg` before passing to Whisper | Must |
| F-22 | Use OpenAI Whisper API (`whisper-1`) as default transcription backend | Must |
| F-23 | Support local Whisper (`openai-whisper` package, model `base`) via config flag `whisper.use_local: true` | Should |
| F-24 | If transcript is empty or under 20 characters, return `"No speech detected."` | Must |
| F-25 | Delete extracted audio temp file after transcription completes or fails | Must |
| F-26 | Maximum video duration: 5 minutes. Reject longer videos with a user-facing error message | Must |

**ffmpeg command (exact):**
```bash
ffmpeg -i {input_video} -vn -acodec pcm_s16le -ar 16000 -ac 1 {output_audio.wav} -y
```

### 5.5 LLM Extractor (`pipeline/extractor.py`)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-27 | Accept `combined_text: str` and `user_note: str | None`; return `KnowledgeEntry` | Must |
| F-28 | Call LLM specified in `config.llm.extraction_model` | Must |
| F-29 | System prompt instructs model to return **only** valid JSON matching the `ExtractionOutput` schema — no markdown fences, no preamble | Must |
| F-30 | Parse response with `json.loads()`; validate with Pydantic | Must |
| F-31 | On `JSONDecodeError` or `ValidationError`: retry once with an amended prompt that includes the failed output and the parse error | Must |
| F-32 | On second failure: raise `ExtractionError` with the raw LLM response attached | Must |
| F-33 | `difficulty` must be inferred even if not explicitly stated in the post | Should |

**Extraction system prompt (exact — do not paraphrase):**
```
You are extracting structured knowledge from an Instagram post for a personal RAG knowledge base.
The post may contain a description of an image, a video transcript, or raw text.

Return ONLY a valid JSON object. No markdown, no explanation, no code fences.
The JSON must match this exact structure:
{
  "title": "string, max 10 words, descriptive",
  "concept": "string, 1-2 sentences explaining the core idea",
  "tags": ["lowercase", "strings", "tools", "techniques", "libraries"],
  "code_snippets": [{"language": "python", "code": "the code here"}],
  "use_cases": ["practical application 1", "practical application 2"],
  "difficulty": "beginner | intermediate | advanced",
  "source_url": "string or null"
}

Rules:
- tags must include all tools, libraries, and techniques mentioned
- code_snippets is an empty list if no code is present
- difficulty must always be set; infer from context if not explicit
- source_url is null unless a URL is present in the input text
```

### 5.6 Embedder (`pipeline/embedder.py`)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-34 | Embed `entry.embed_text` (defined in schema, section 6) — not raw post text | Must |
| F-35 | Default: OpenAI `text-embedding-3-small`, 1536 dimensions | Must |
| F-36 | Alternative: `sentence-transformers` `all-MiniLM-L6-v2` when `config.embedding.provider == "sentence-transformers"` | Should |
| F-37 | Return a `list[float]`; do not store the vector on the entry object | Must |

### 5.7 Vector Store (`pipeline/store.py`)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-38 | Initialize ChromaDB in persistent mode at `config.storage.chroma_path` | Must |
| F-39 | `upsert(entry, vector)`: write to collection `entry.collection` (v1: always `"default"`) | Must |
| F-40 | Metadata stored: all scalar fields of `KnowledgeEntry`; lists serialized as `"item1,item2"` | Must |
| F-41 | `search(query_vector, k, collection)`: return top-k results as `list[SearchResult]` | Must |
| F-42 | `SearchResult` must contain: `entry_id`, `title`, `concept`, `tags`, `difficulty`, `obsidian_path`, `distance` | Must |
| F-43 | Collection is created if it does not exist (`get_or_create_collection`) | Must |

### 5.8 Obsidian Writer (`pipeline/obsidian_writer.py`)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-44 | Write one `.md` file per entry to `config.obsidian.vault_path` | Must |
| F-45 | Filename: `YYYY-MM-DD_<slugified-title>.md` where slug = lowercase, spaces to hyphens, special chars stripped | Must |
| F-46 | If filename exists: append `_2`, `_3`, etc. until unique | Must |
| F-47 | Store the resolved file path back on `entry.obsidian_path` before returning | Must |
| F-48 | YAML frontmatter fields: `id`, `date`, `collection`, `tags`, `difficulty`, `source_url`, `input_type`, `obsidian_path` | Must |
| F-49 | Body sections in order: `## Concept`, `## Use cases`, `## Code`, `## Raw input` | Must |
| F-50 | Code snippets: fenced code blocks with language label | Must |
| F-51 | `## Raw input`: contains `entry.raw_text` truncated to 500 characters, with `[truncated]` suffix if cut | Must |

**Required output format (exact):**
```markdown
---
id: {entry.id}
date: {entry.date}
collection: {entry.collection}
tags: [{comma-separated tags}]
difficulty: {entry.difficulty}
source_url: {entry.source_url or null}
input_type: {entry.input_type}
obsidian_path: {resolved path}
---

## Concept
{entry.concept}

## Use cases
{bulleted list of entry.use_cases}

## Code
{fenced code blocks for each snippet, or "No code snippets." if empty}

## Raw input
{entry.raw_text[:500]}{" [truncated]" if len > 500 else ""}
```

### 5.9 CLI Search Tool (`search.py`)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-52 | Positional argument: `query` (natural language string) | Must |
| F-53 | `--k INT` flag: number of results, default 5 | Should |
| F-54 | `--collection STR` flag: defaults to `"default"`; passed through to store — comment `# PRDv2: expose multi-collection routing` | Must |
| F-55 | `--json` flag: output raw JSON array instead of formatted text | Should |
| F-56 | Default output per result: numbered list with title, concept (truncated 100 chars), tags, difficulty, Obsidian path | Must |
| F-57 | Exit with code 1 and message if ChromaDB path does not exist | Must |

**Example output (default):**
```
1. Pandas groupby with multiple aggregations [intermediate]
   Using .agg() with a dict to apply multiple functions to different columns...
   Tags: pandas, groupby, aggregation, python
   Note: ~/ObsidianVault/Knowledge Base/2026-05-15_pandas-groupby.md

2. ...
```

---

## 6. Data Schema (`models/schema.py`)

This schema is a contract. Do not modify field names, types, or defaults in v1. PRDv2 will extend additively.

```python
from pydantic import BaseModel, Field
from typing import Literal

class CodeSnippet(BaseModel):
    language: str
    code: str

class KnowledgeEntry(BaseModel):
    # Identity
    id: str                                    # uuid4, set by IngestHandler
    date: str                                  # ISO 8601 UTC, set by IngestHandler
    collection: str = "default"                # PRDv2: routing logic sets this

    # Input metadata
    input_type: Literal["TEXT", "IMAGE", "VIDEO", "IMAGE_WITH_TEXT", "VIDEO_WITH_TEXT"]
    raw_text: str                              # combined_text before extraction
    user_note: str | None = None

    # Extracted fields (set by Extractor)
    title: str = ""
    concept: str = ""
    tags: list[str] = Field(default_factory=list)
    code_snippets: list[CodeSnippet] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    difficulty: Literal["beginner", "intermediate", "advanced"] | None = None
    source_url: str | None = None

    # Storage metadata (set by ObsidianWriter)
    obsidian_path: str | None = None

    @property
    def embed_text(self) -> str:
        """Text to embed. Canonical: title + concept + tags. Not raw post text."""
        tag_str = " ".join(self.tags)
        return f"{self.title}. {self.concept} {tag_str}".strip()

class SearchResult(BaseModel):
    entry_id: str
    title: str
    concept: str
    tags: list[str]
    difficulty: str | None
    obsidian_path: str | None
    distance: float
```

**`ExtractionOutput`** (internal Pydantic model used only by `extractor.py` to validate LLM JSON before merging into `KnowledgeEntry`):
```python
class ExtractionOutput(BaseModel):
    title: str
    concept: str
    tags: list[str]
    code_snippets: list[CodeSnippet] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    difficulty: Literal["beginner", "intermediate", "advanced"]
    source_url: str | None = None
```

---

## 7. Configuration

### 7.1 `config.yaml` (full, exact structure)

```yaml
telegram:
  bot_token_env: TELEGRAM_BOT_TOKEN          # env var name, not the value

llm:
  extraction_model: claude-haiku-4-5-20251001  # or gpt-4o-mini
  vision_model: claude-sonnet-4-6              # or gpt-4o

whisper:
  use_local: false                             # true = openai-whisper package; false = API
  local_model_size: base                       # tiny | base | small (if use_local: true)
  max_video_duration_seconds: 300

embedding:
  provider: openai                             # openai | sentence-transformers
  openai_model: text-embedding-3-small
  local_model: all-MiniLM-L6-v2

storage:
  chroma_path: ./data/chroma
  default_collection: default                  # PRDv2: this becomes a routing default

obsidian:
  vault_path: ~/Documents/ObsidianVault/Knowledge Base
```

### 7.2 `.env.example`
```
TELEGRAM_BOT_TOKEN=your_token_here
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
```

### 7.3 Config Loading

Claude Code must implement a `Config` dataclass in `config.py` that loads `config.yaml` at startup and exposes typed attributes. No module may call `yaml.load()` directly — all config access goes through the `Config` singleton.

---

## 8. Project Structure

Implement exactly this structure. Do not add, remove, or rename files.

```
rag-knowledge-base/
├── bot/
│   └── bot.py                   # Telegram bot, async, python-telegram-bot v21
├── pipeline/
│   ├── __init__.py
│   ├── ingest.py                # IngestHandler: routing and ID assignment
│   ├── vision.py                # VisionDescriber: image → text
│   ├── transcriber.py           # VideoTranscriber: video → transcript
│   ├── extractor.py             # Extractor: combined_text → KnowledgeEntry
│   ├── embedder.py              # Embedder: entry → vector
│   ├── store.py                 # Store: ChromaDB read/write
│   └── obsidian_writer.py       # ObsidianWriter: entry → .md file
├── models/
│   └── schema.py                # KnowledgeEntry, SearchResult, ExtractionOutput
├── search.py                    # CLI search tool (argparse)
├── config.py                    # Config dataclass + loader
├── config.yaml                  # Runtime configuration
├── .env.example                 # API key template
├── requirements.txt             # Pinned dependencies
└── README.md                    # Architecture writeup (portfolio-facing)
```

---

## 9. Dependencies (`requirements.txt`)

Pin all versions.

```
python-telegram-bot==21.6
openai==1.30.0
anthropic==0.28.0
chromadb==0.5.3
pydantic==2.7.1
pyyaml==6.0.1
python-dotenv==1.0.1
ffmpeg-python==0.2.0
sentence-transformers==3.0.1     # only used if embedding.provider = sentence-transformers
openai-whisper==20231117         # only used if whisper.use_local = true
```

`ffmpeg` binary must be installed separately (not a Python package). Claude Code must add a check at startup that raises a clear error if `ffmpeg` is not on `PATH`.

---

## 10. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NF-01 | End-to-end: text post → Obsidian file written | < 10 seconds |
| NF-02 | End-to-end: image post → Obsidian file written | < 20 seconds |
| NF-03 | End-to-end: video (≤5 min) → Obsidian file written | < 60 seconds |
| NF-04 | CLI search latency | < 2 seconds |
| NF-05 | Extraction cost per entry (Haiku) | < $0.005 |
| NF-06 | Embedding cost per entry (text-embedding-3-small) | < $0.001 |
| NF-07 | Whisper API cost per minute of audio | ~$0.006 |
| NF-08 | Runs on macOS 13+ and Ubuntu 22.04 without modification | Must |
| NF-09 | No credentials in source code; all from `.env` | Must |
| NF-10 | No internet dependency beyond LLM/Whisper API calls | Must |
| NF-11 | ChromaDB and Obsidian vault paths fully configurable | Must |

---

## 11. Milestones & Acceptance Criteria

Claude Code must complete and verify each milestone before starting the next.

### M1 — Project scaffold
**Build:** Full file structure from section 8, `config.py` loader, `.env` loading, `requirements.txt`
**Verify:** `python -c "from config import Config; c = Config(); print(c.obsidian.vault_path)"` prints the configured path without error

### M2 — Schema
**Build:** `models/schema.py` with `KnowledgeEntry`, `SearchResult`, `ExtractionOutput`, `embed_text` property
**Verify:** Instantiate a `KnowledgeEntry` with all required fields and assert `embed_text` returns a non-empty string

### M3 — Telegram bot (receive only)
**Build:** `bot/bot.py` that receives messages, logs payload shape to stdout, sends "Got it, processing..." reply
**Verify:** Forward a text message and a photo to the bot; confirm both acknowledgements arrive and payload is logged correctly

### M4 — Vision and transcription
**Build:** `pipeline/vision.py`, `pipeline/transcriber.py`
**Verify:**
- Pass a screenshot of a Python code snippet to `VisionDescriber.describe()` and confirm the code is in the returned text
- Pass a 30-second Instagram Reel to `VideoTranscriber.transcribe()` and confirm a non-empty transcript is returned

### M5 — Extraction
**Build:** `pipeline/extractor.py` with retry logic
**Verify:** Pass `combined_text` from a known post; assert returned `KnowledgeEntry` has non-empty `title`, `tags`, `concept`, and `difficulty` is one of the three valid values

### M6 — Storage
**Build:** `pipeline/embedder.py`, `pipeline/store.py`, `pipeline/obsidian_writer.py`
**Verify:**
- Upsert one entry; confirm ChromaDB collection `default` contains exactly one document
- Confirm `.md` file exists in vault with correct frontmatter fields
- Confirm `entry.obsidian_path` is set after `ObsidianWriter.write()`

### M7 — Ingest handler + bot integration
**Build:** `pipeline/ingest.py`, wire `IngestHandler` into `bot/bot.py`
**Verify:** Forward one image post and one video Reel end-to-end; confirm both produce `.md` files in the vault and success messages in Telegram

### M8 — CLI search
**Build:** `search.py`
**Verify:**
- Run `python search.py "pandas groupby"` after ingesting a relevant post; confirm it appears in top 3 results
- Run with `--json` flag; confirm output is valid JSON parseable by `json.loads()`
- Run with `--collection default`; confirm no error

### M9 — End-to-end test set
**Build:** Nothing new
**Verify:** Ingest 10 real Instagram posts/Reels covering at least 3 different topics. Run 5 semantic queries. At least 4 of 5 should return the expected post in the top 3 results. Document results in `README.md`.

---

## 12. PRDv2 Hooks

Claude Code must place the following comments exactly where indicated. PRDv2 will reference these by comment text.

| Comment | Location | Purpose |
|---------|----------|---------|
| `# PRDv2: derive collection from user input` | `pipeline/ingest.py`, line that sets `entry.collection` | Multi-collection routing |
| `# PRDv2: multi-collection routing` | `bot/bot.py`, stub `/search` handler | Search command implementation |
| `# PRDv2: expose multi-collection routing` | `search.py`, `--collection` flag | CLI collection switching |
| `# PRDv2: this becomes a routing default` | `config.yaml`, `storage.default_collection` | Config-driven collection default |

---

## 13. Open Questions

Resolve before starting M4 (vision/transcription) or M5 (extraction).

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| OQ-1 | Extraction model: Claude Haiku vs GPT-4o-mini? | Haiku: cheaper, in ecosystem. GPT-4o-mini: marginally better JSON reliability | Haiku; switch if JSON parse failures exceed 5% in M9 |
| OQ-2 | Embedding: OpenAI API vs local sentence-transformers? | API: ~$0.001/entry, zero setup. Local: $0, 5% quality drop on short texts | API for MVP; local if cost becomes a concern |
| OQ-3 | Whisper: API vs local? | API: $0.006/min, no GPU needed. Local `base`: free, ~2× slower on CPU | API for MVP; local option must still be implemented per F-23 |
| OQ-4 | How to handle non-technical posts (motivational, lifestyle)? | Hard reject with error, soft reject with `difficulty: null` and low-confidence tag, or store as-is | Store as-is in v1; filtering is a PRDv3 concern |

---

## 14. README Requirements (M9 deliverable)

The `README.md` must include the following sections. This is a portfolio-facing document.

1. **What this is** — one paragraph, plain language
2. **Architecture diagram** — the component map from section 4.1, rendered as a code block
3. **Design decisions** — explain: why `embed_text` uses extracted summary not raw text; why ChromaDB collections are parameterized from day one; why video goes through Whisper not a vision model
4. **Setup** — step-by-step: clone, install deps, configure `.env` and `config.yaml`, run bot, run search
5. **Example output** — one real Obsidian `.md` file, one real CLI search result
6. **What's next** — one sentence per planned PRD version
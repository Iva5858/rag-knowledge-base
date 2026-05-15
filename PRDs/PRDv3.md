# Product Requirements Document
## Personal RAG Knowledge Base — v3

**Author:** Isaac Vélez Aguirre
**PRD Version:** 3.0 (DRAFT — review before implementation)
**Status:** Draft — not yet approved for implementation
**Date:** May 2026
**Executor:** Claude Code
**Previous PRD:** PRDv2.md
**Next PRD:** PRDv4 — Source-agnostic ingestion & retrieval reranking

---

> [!CRITICAL] BLOCKER — DO NOT START ANY MILESTONE UNTIL THIS IS RESOLVED
>
> **Instagram Reels (video ingestion) is broken in production as of 2026-05-15.**
>
> `yt-dlp` fails with `rate-limit reached or login required` on every Reel URL because the
> Instagram session cookies stored in `INSTAGRAM_COOKIES_B64` have expired.
> Image posts (`/p/`) work fine. Only Reels are affected.
>
> **Root cause:** Instagram invalidates browser session cookies when they are used from
> Fly.io's Frankfurt datacenter IPs. Cookies last roughly 30–90 days; shorter if Instagram
> detects suspicious activity from the datacenter.
>
> **Fix (must be done before M1):**
> 1. Log into Instagram on Chrome on your Mac.
> 2. Export cookies using the "Get cookies.txt LOCALLY" extension (Netscape format).
> 3. Run: `flyctl secrets set INSTAGRAM_COOKIES_B64="$(base64 -i ~/Downloads/instagram_cookies.txt)"`
> 4. Watch `flyctl logs` for `[entrypoint] Instagram cookies written to /data/instagram_cookies.txt`.
> 5. Send a Reel URL via Telegram and confirm it processes successfully.
>
> **This must be verified working before any PRDv3 milestone begins.**
> Cookies expire periodically — re-run the above steps whenever Reels start failing again.
> See the Maintenance table in `README.md` for the recurring procedure.

---

## 0. Instructions for Claude Code

- **Read PRDv2.md before touching any existing code.** PRDv3 extends it additively.
- **Activate PRDv2 hooks.** PRDv2 placed four hook comments; PRDv3 activates all four. Replace each with real implementation before writing any new code.
- **Schema is still a contract.** Any new fields require Isaac's explicit approval, must have defaults, and must not break existing `KnowledgeEntry` instances.
- **One milestone at a time.** Complete and verify each milestone before reporting done.
- **Ask before assuming** on anything that affects the schema, routing logic, or PRDv4 hooks.

---

## 1. Problem Statement

PRDv2 delivers a working, hosted, always-on knowledge base. Three gaps remain:

1. **Flat namespace** — everything lands in `"default"`. A growing library of 50–200 posts becomes hard to navigate. ML theory, engineering how-tos, and career advice are interleaved, so a `/search` in a focused area returns noise from unrelated topics.

2. **No periodic review** — knowledge is passive. Nothing prompts Isaac to revisit what he saved. A weekly Telegram digest would surface recent additions and reinforce recall.

3. **Terminal-only access to ingest** — the bot accepts URLs, but there is no programmatic way for external tools (iOS Shortcuts, a future web UI, or scripts) to query or trigger ingestion without going through Telegram.

---

## 2. Scope

### 2.1 In Scope — PRD v3

| Feature | Notes |
|---------|-------|
| Multi-collection routing | Activate `# PRDv3: multi-collection routing` hook in `ingest.py` |
| CLI and Telegram collection filtering | Activate `# PRDv3: expose multi-collection routing` hook in `search.py` |
| `/search` content-type and difficulty filters | `--type`, `--difficulty` flags |
| Obsidian deep links in `/search` results | Optional `obsidian://` links (desktop only) |
| Weekly digest via Telegram | Scheduled Sunday message: what was saved this week |
| FastAPI REST layer | `/search`, `/ingest`, `/stats`, `/recent` endpoints |

### 2.2 Out of Scope — PRD v3 (planned for PRDv4)

| Feature | Target PRD |
|---------|-----------|
| Source-agnostic ingestion (YouTube, Twitter/X) | PRDv4 |
| Retrieval reranking with cross-encoder | PRDv4 |
| Filtering by difficulty in ChromaDB (not just CSV) | PRDv4 |
| Anki flashcard export | PRDv4 |
| Batch ingestion (multiple URLs in one message) | PRDv4 |

---

## 3. Functional Requirements

### 3.1 Multi-Collection Routing (`M1`)

Activates the hook: `# PRDv3: multi-collection routing` in `pipeline/ingest.py`.

Collections map to broad topic areas. The routing function reads `content_type` (already extracted by the LLM) and maps it to one of four collections.

#### Routing table

| `content_type` | Collection |
|---------------|-----------|
| `technical-tutorial` | `engineering` |
| `tool-overview` | `engineering` |
| `project-showcase` | `engineering` |
| `career-advice` | `career` |
| `industry-insight` | `insights` |
| `general` | `default` |

#### Implementation

Add a `_route_collection(content_type: str | None) -> str` function in `pipeline/ingest.py`:

```python
_COLLECTION_MAP = {
    "technical-tutorial": "engineering",
    "tool-overview": "engineering",
    "project-showcase": "engineering",
    "career-advice": "career",
    "industry-insight": "insights",
    "general": "default",
}

def _route_collection(content_type: str | None) -> str:
    """Return the ChromaDB collection name for a given content_type."""
    return _COLLECTION_MAP.get(content_type or "", "default")
```

Replace the `collection="default"` line (marked with `# PRDv3: multi-collection routing`) with:

```python
collection=_route_collection(extraction.content_type),
```

| ID | Requirement | Priority |
|----|-------------|----------|
| F-C1 | `_route_collection()` maps `content_type` to one of: `engineering`, `career`, `insights`, `default` | Must |
| F-C2 | `collection` field on `KnowledgeEntry` reflects the routed collection (not always `"default"`) | Must |
| F-C3 | `directory.csv` `collection` column must be populated with the routed value | Must |
| F-C4 | Existing entries in the `"default"` collection continue to work; no migration required for MVP | Must |
| F-C5 | `/search` with no `--collection` flag searches **all collections** and merges results by distance | Must |
| F-C6 | `/search <query> --collection engineering` restricts search to one collection | Should |
| F-C7 | Bot reply after ingestion includes the routed collection: `Saved: {title} [{tags}] → {collection}` | Should |

**Cross-collection search (F-C5):** ChromaDB has no native cross-collection search. Implement by querying each collection independently and merging results sorted by distance score, deduplicating by entry `id`.

#### `config.yaml` additions

```yaml
storage:
  collections:
    - engineering
    - career
    - insights
    - default
```

`Config` reads this list and uses it to initialise all collections on startup (so ChromaDB creates them before they are first written to).

---

### 3.2 CLI and Telegram Collection Filtering (`M2`)

Activates the hook: `# PRDv3: expose multi-collection routing` in `search.py`.

| ID | Requirement | Priority |
|----|-------------|----------|
| F-F1 | `search.py` `--collection <name>` restricts CLI search to one collection; omitting it searches all | Must |
| F-F2 | `/search <query> --collection <name>` in Telegram restricts to one collection | Must |
| F-F3 | `/search <query> --type <content_type>` filters by `content_type` in metadata (post-retrieval filter on ChromaDB results) | Should |
| F-F4 | `/search <query> --difficulty <level>` filters by `difficulty` in metadata (post-retrieval filter) | Should |
| F-F5 | Unknown `--collection` names: reply with the list of valid collections from config | Must |
| F-F6 | CLI `--json` flag output includes the `collection` field | Must |

**Implementation note:** ChromaDB `where` filtering on metadata supports equality. Use `where={"content_type": value}` and `where={"difficulty": value}` directly in the `collection.query()` call. These are already stored as metadata strings.

---

### 3.3 Obsidian Deep Links in `/search` Results (`M3`)

From PRDv2 Open Question OQ-2, deferred to PRDv3.

| ID | Requirement | Priority |
|----|-------------|----------|
| F-O1 | Each `/search` result includes an `obsidian://` deep link when `OBSIDIAN_VAULT_NAME` env var is set | Should |
| F-O2 | Link format: `obsidian://open?vault={vault_name}&file={filename}` where `filename` is the `.md` stem | Should |
| F-O3 | If `OBSIDIAN_VAULT_NAME` is not set, omit the deep link silently — no error | Must |
| F-O4 | A note in the `/search` reply header warns that deep links only open on a Mac with Obsidian installed | Should |

**Why optional:** deep links are URL-scheme calls that only the desktop OS can resolve. On mobile Telegram they appear as tappable links but open nothing. The feature is additive and silent-fail when the env var is absent.

---

### 3.4 Weekly Digest (`M4`)

Activates the hook: `# PRDv3: weekly digest hook` in `pipeline/store.py`.

A scheduled Telegram message sent every Sunday at 09:00 (Isaac's local timezone) summarising what was ingested in the past 7 days.

| ID | Requirement | Priority |
|----|-------------|----------|
| F-W1 | Every Sunday at 09:00 (Europe/Berlin or configurable timezone), the bot sends a digest to the allowed user | Must |
| F-W2 | Digest reads entries from the past 7 days from `directory.csv` (by `date` column) | Must |
| F-W3 | Digest format: total count, breakdown by collection, top 5 most recent titles with tags | Must |
| F-W4 | If no entries were ingested that week, send: `"Nothing saved this week — clear queue? 📭"` | Should |
| F-W5 | Digest is triggered by Python's `asyncio` scheduler or `APScheduler` — no external cron | Must |
| F-W6 | Timezone is configurable via `config.yaml` (default: `Europe/Berlin`) | Should |

#### Example digest message

```
📚 Weekly Digest — May 12–18, 2026

Saved this week: 7 posts
  engineering   4
  career        2
  insights      1

Latest additions:
1. Vectorized Operations in Pandas [pandas, numpy]
2. RAG Pipeline Architecture Patterns [rag, llm]
3. Negotiating Senior Roles at Startups [career, negotiation]
4. GPT-4o Multimodal Benchmarks [llm, benchmarks]
5. Building a Production ML System [mlops, architecture]

/search to find any of these →
```

#### Implementation note

Use `APScheduler` with `AsyncIOScheduler`. Add `apscheduler` to `requirements.txt`. The scheduler is started in `bot/bot.py` after the `Application` is built and runs in the same event loop.

---

### 3.5 FastAPI REST Layer (`M5`)

A lightweight HTTP API that exposes the core pipeline operations. Enables iOS Shortcuts, browser bookmarklets, a future web UI, or scripts to interact with the knowledge base without going through Telegram.

| ID | Requirement | Priority |
|----|-------------|----------|
| F-A1 | `POST /ingest` — body: `{"url": "...", "user_note": "..."}` — returns the saved `KnowledgeEntry` as JSON | Must |
| F-A2 | `GET /search?q=<query>&k=5&collection=<name>` — returns top-k `SearchResult` objects as JSON | Must |
| F-A3 | `GET /stats` — returns the same stats as the Telegram `/stats` command as JSON | Must |
| F-A4 | `GET /recent?n=5` — returns last n entries as JSON | Should |
| F-A5 | All endpoints require a bearer token (`API_KEY` env var); 401 if missing or invalid | Must |
| F-A6 | FastAPI app lives in `api/app.py`; shares `IngestHandler` and `Store` instances with the bot | Must |
| F-A7 | The API runs on port `8080` alongside the Telegram bot (same process, via `asyncio`) | Must |
| F-A8 | `fly.toml` adds `[[services]]` to expose port 8080 externally (HTTPS) | Must |
| F-A9 | `POST /ingest` is rate-limited to 10 requests per minute per IP | Should |

#### Running API and bot in the same process

```python
# bot/bot.py — after application.build()
import uvicorn
from api.app import create_app

async def main():
    app = application  # python-telegram-bot Application
    api = create_app(handler)  # FastAPI app
    
    async with app:
        await app.start()
        await asyncio.gather(
            app.updater.start_polling(),
            uvicorn.Server(uvicorn.Config(api, host="0.0.0.0", port=8080)).serve(),
        )
```

#### New file: `api/app.py`

```python
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer

def create_app(handler: IngestHandler) -> FastAPI:
    """Return a FastAPI app wired to the given IngestHandler."""
    ...
```

#### `requirements.txt` additions

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
apscheduler>=3.10.4
```

---

## 4. Schema Extensions (`models/schema.py`)

No new fields are required for PRDv3. The `collection` field already exists on `KnowledgeEntry` and will now be populated with a non-`"default"` value by the router.

`SearchResult` gains one optional field for the deep link feature:

```python
# Added in PRDv3 — optional, only populated when OBSIDIAN_VAULT_NAME is set
obsidian_url: str | None = None
```

This is the only schema change. It has a default of `None` for full backward compatibility.

---

## 5. New Files

```
rag-knowledge-base/
├── api/
│   ├── __init__.py
│   └── app.py                  # FastAPI app: /ingest, /search, /stats, /recent
├── PRDs/
│   └── PRDv3.md                ← you are here
```

Update `CLAUDE.md` project structure to include `api/`.

Do not create any other files without approval.

---

## 6. Configuration (`config.yaml`)

```yaml
storage:
  chroma_path: ./data/chroma
  csv_path: ./data/directory.csv
  collections:                    # PRDv3: all known collection names
    - engineering
    - career
    - insights
    - default

digest:
  enabled: true
  send_day: sunday                # day of week
  send_time: "09:00"              # HH:MM
  timezone: Europe/Berlin
```

`.env.example` additions:

```
OBSIDIAN_VAULT_NAME=Knowledge Base    # optional — enables obsidian:// deep links
API_KEY=your_api_key_here             # required for FastAPI bearer auth
```

---

## 7. Dependencies (`requirements.txt`)

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
apscheduler>=3.10.4
```

No other new packages. `httpx` is already present (used by FastAPI's test client and the existing pipeline).

---

## 8. Milestones & Acceptance Criteria

### M1 — Multi-collection routing
**Build:** `_route_collection()` in `ingest.py`. Replace `# PRDv3: multi-collection routing` hook. Update `config.yaml` with collections list. Update startup to initialise all collections.
**Verify:** Ingest a `technical-tutorial` post → `entry.collection == "engineering"`. Ingest a `career-advice` post → `entry.collection == "career"`. `directory.csv` shows the correct collection column. Existing entries in `"default"` are still searchable.

### M2 — Collection and metadata filtering
**Build:** Replace `# PRDv3: expose multi-collection routing` hook in `search.py`. Add `--collection`, `--type`, `--difficulty` flags to CLI and Telegram `/search` handler. Cross-collection search (no flag → search all).
**Verify:** `/search pandas --collection engineering` returns results only from `engineering`. `/search career --type career-advice` returns only `career-advice` entries. `/search pandas` (no flag) returns results from all collections, sorted by distance.

### M3 — Obsidian deep links
**Build:** Add `OBSIDIAN_VAULT_NAME` env var check. Populate `SearchResult.obsidian_url` when set. Update `_format_search_results()` in `bot.py` to include the link when present.
**Verify:** With `OBSIDIAN_VAULT_NAME` set, `/search` results include a tappable `obsidian://` link. Without the env var, results are identical to current output.

### M4 — Weekly digest
**Build:** Replace `# PRDv3: weekly digest hook` in `store.py`. Add `DigestSender` class. Integrate `APScheduler` into `bot/bot.py`. Add `digest` config block to `config.yaml`.
**Verify:** Manually trigger the digest handler (bypass scheduler). Correct entries from the past 7 days appear. With no recent entries, the empty-week message is sent. Scheduler fires at the configured time (test by setting time to 2 minutes in the future, then restore).

### M5 — FastAPI REST layer
**Build:** `api/app.py` with all four endpoints. Bearer auth middleware. Wire into `bot/bot.py` via `asyncio.gather`. Update `fly.toml` to expose port 8080.
**Verify:** `curl -H "Authorization: Bearer <key>" https://<app>.fly.dev/stats` returns JSON. `POST /ingest` with a valid URL ingests the post and returns the entry. `GET /search?q=pandas&k=3` returns 3 results. Missing or invalid bearer token returns 401.

### M6 — End-to-end with multi-collection
**Build:** Nothing new — deploy and verify everything works together on Fly.io.
**Verify:** Over one week, ingest 10 posts spanning at least 3 content types. Confirm correct collection routing in `directory.csv`. Confirm `/search` cross-collection works from Telegram. Confirm digest fires on Sunday. Confirm REST API accessible externally.

---

## 9. PRDv4 Hooks

Place these comments exactly as shown. PRDv4 will reference them by comment text.

| Comment | Location | Purpose |
|---------|----------|---------|
| `# PRDv4: source-agnostic ingestion — add YouTube/Twitter handler here` | `pipeline/ingest.py`, URL routing block (`_extract_instagram_url`) | Multi-platform support |
| `# PRDv4: cross-encoder reranking` | `pipeline/store.py`, `search()` return point | Replace pure vector similarity with learned reranking |
| `# PRDv4: collection migration tool` | `pipeline/store.py`, `upsert()` | Utility to re-route existing entries to new collections |
| `# PRDv4: batch ingestion` | `bot/bot.py`, `handle_message()` | Multiple URLs in one Telegram message |

---

## 10. Open Questions

Resolve before starting the relevant milestone.

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| OQ-1 | Cross-collection search: merge by distance (raw float) or normalise first? ChromaDB returns L2 or cosine distances depending on collection metric. Both must use the same metric for meaningful comparison. | L2 / cosine / normalise | Set all collections to cosine at creation; merge raw scores |
| OQ-2 | Routing: should `project-showcase` go to `engineering` or its own collection `projects`? ML portfolio projects and side-projects feel distinct from tutorials and tool walkthroughs. | `engineering` / `projects` | Start with `engineering`; split only if retrieval quality degrades |
| OQ-3 | FastAPI: run in the same process as the Telegram bot (shared `IngestHandler`) or as a separate Fly.io service with its own volume access? Same process is simpler; separate service enables independent scaling. | Same process / separate service | Same process for MVP |
| OQ-4 | Weekly digest: what day / time makes most sense for Isaac's schedule? Sunday 09:00 Berlin assumed. | Any day/time | Isaac to confirm |
| OQ-5 | Should `/ingest` via the REST API support image uploads (multipart) or only URLs in PRDv3? | URLs only / multipart | URLs only in PRDv3 |

---

## 11. Notes for Isaac (Review Checklist)

This is a draft. Before approving for implementation, confirm:

- [ ] Collection names (`engineering`, `career`, `insights`, `default`) match how you think about your content
- [ ] Routing table (content_type → collection) feels right — should `project-showcase` stay in `engineering`?
- [ ] Weekly digest day/time: Sunday 09:00 Europe/Berlin works for you
- [ ] FastAPI: do you actually want external REST access? If the Telegram bot covers all your use cases, M5 can be deferred to PRDv4
- [ ] Obsidian deep links (M3) are a "nice to have" — safe to cut if you want a leaner PRDv3
- [ ] PRDv4 hooks look correct and are planted in the right places

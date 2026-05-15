# RAG Knowledge Base

A personal knowledge base that turns Instagram posts and Reels into a semantically searchable archive. Send a link to the Telegram bot — the system downloads the content, extracts structured knowledge with an LLM, stores a vector in ChromaDB, writes a human-readable note to an Obsidian vault, and pushes it to GitHub so it appears in your local Obsidian within minutes. The bot runs 24/7 on Fly.io.

**Status:** PRDv1 ✅ · PRDv2 ✅ · PRDv3 in planning

---

## Architecture

```
INGESTION               PROCESSING                           STORAGE              RETRIEVAL
─────────               ──────────                           ───────              ─────────
                        ┌─ [image/carousel] ──→ Vision LLM ──┐
Telegram Bot ─────────→ ├─ [reel/video]     ──→ Whisper ──────┼──→ LLM Extractor ──→ ChromaDB (/data/chroma)
(bot/bot.py)            └─ [text-only]      ───────────────────┘   (KnowledgeEntry)  + Obsidian .md (/data/vault)
                            IngestHandler                                                       ↓
                            (pipeline/ingest.py)                                         VaultSync
                            ↑                                                        git commit + push
                      Instagram URL?                                                         ↓
                      /p/  → /media/?size=l + og:description                      GitHub (obsidian-vault)
                      /reel/ → yt-dlp + cookies                                             ↓
                                                                                   Obsidian Git plugin
                                                                                   (auto-pull, 5 min)
```

**Full data flow:**

1. User sends an Instagram URL to the Telegram bot
2. Bot checks for duplicate (same URL already ingested → warns, offers force re-ingest)
3. IngestHandler fetches content by URL type:
   - `/p/` image post — caption from `og:description`, slides from `/media/?size=l&index=N`
   - `/reel/` — video + caption via yt-dlp (uses browser cookies to bypass datacenter rate-limits)
4. Visual content routed to `VisionDescriber` (images) or `VideoTranscriber` (Whisper API)
5. Caption + visual description assembled into `combined_text`
6. `Extractor` calls `gpt-4o-mini`, validates JSON as `ExtractionOutput`; retries once on parse failure
7. `Embedder` embeds `entry.embed_text` (title + concept + key_takeaway + tags) via `text-embedding-3-small`
8. `Store.upsert()` writes to ChromaDB and updates `data/directory.csv`
9. `ObsidianWriter.write()` writes a `.md` to `/data/vault`
10. `VaultSync.commit_and_push()` commits and pushes to the private vault GitHub repo
11. Bot replies: `Saved: {title} [{tag1, tag2, tag3}]`

---

## Design Decisions

**`embed_text` uses the extracted summary, not raw post text.**
Raw Instagram captions are noisy — hashtag dumps, emojis, broken sentences. Embedding `title + concept + key_takeaway + tags` gives a clean, semantically dense representation. Retrieval precision is measurably better than embedding the raw caption.

**`content_type` classification unlocks non-tutorial retrieval.**
The original extraction prompt was tuned for step-by-step tutorials and missed the strategic layer of posts about projects, careers, or industry trends. Classifying each post (`technical-tutorial`, `project-showcase`, `career-advice`, etc.) and requiring a `key_takeaway` forces the model to capture the big picture, not just the tech stack.

**ChromaDB collections are parameterised from day one.**
Every function that touches ChromaDB accepts a `collection` parameter. v1 and v2 use `"default"`. Multi-topic routing in v3 requires no architectural changes — only activating the marked `# PRDv3:` hook points.

**Video goes through Whisper, not a vision model.**
Reels are primarily audio-driven. A vision model sampling frames misses most of the information. Whisper processes the full audio timeline.

**Image posts use `/media/?size=l`, not yt-dlp.**
yt-dlp needs a valid Instagram session for image posts. The `/media/?size=l` endpoint is publicly accessible. Carousels are handled by incrementing `index` and stopping on the first MD5-duplicate response.

**Caption fetched via `og:description` with Facebook crawler UA.**
Instagram serves the full post caption to the Facebook external hit crawler without requiring login.

**Tags normalised to `lowercase-hyphenated` form.**
The extraction prompt requests hyphens; a deterministic `_normalize_tags()` pass enforces it after every LLM response, preventing Obsidian from creating duplicate tags for `machine learning` vs `machine-learning`.

**Reels use browser cookies on the hosted server.**
Fly.io's Frankfurt datacenter IPs get rate-limited by Instagram for yt-dlp requests. Exporting cookies from a logged-in browser session and storing them as a Fly.io secret bypasses this. Cookies expire ~90 days; re-export when Reels start failing.

**Git identity configured in VaultSync, not globally.**
Containers have no git user identity by default, causing `git commit` to fail silently (exit 0 with an error message that doesn't contain "nothing to commit"). VaultSync sets `user.email` and `user.name` on the vault repo before every commit.

---

## Setup

### Prerequisites

- Python 3.11+
- `ffmpeg` on PATH (`brew install ffmpeg` on macOS)
- OpenAI API key
- Telegram bot token (create via [@BotFather](https://t.me/botfather))

### 1. Clone and create the virtual environment

```bash
git clone https://github.com/Iva5858/rag-knowledge-base.git
cd rag-knowledge-base
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```
TELEGRAM_BOT_TOKEN=your_token_here
OPENAI_API_KEY=your_key_here
TELEGRAM_ALLOWED_USER_ID=your_telegram_numeric_id   # find via @userinfobot
GITHUB_PAT=your_github_pat_here                     # for vault Git sync
```

### 3. Configure paths

Edit `config.yaml`:

```yaml
obsidian:
  vault_path: ~/Documents/ObsidianVault/Knowledge Base
  git_remote_repo: "github.com/your-username/obsidian-vault.git"
  vault_sync_enabled: true
```

### 4. Set up the vault Git repo (one-time)

```bash
cd "~/Documents/ObsidianVault/Knowledge Base"
git init && git remote add origin https://github.com/your-username/obsidian-vault.git
git add . && git commit -m "Initial vault" && git push -u origin main
```

Install the **Obsidian Git** community plugin → set auto-pull to 5 minutes.

### 5. Run locally

```bash
source .venv/bin/activate
python bot/bot.py
```

### 6. Deploy to Fly.io (always-on)

```bash
# One-time setup
fly apps create your-app-name
fly volumes create rag_data --size 1 --region fra --app your-app-name

flyctl secrets set \
  TELEGRAM_BOT_TOKEN="..." \
  OPENAI_API_KEY="..." \
  TELEGRAM_ALLOWED_USER_ID="..." \
  GITHUB_PAT="your_pat" \
  VAULT_PATH="/data/vault" \
  CHROMA_PATH="/data/chroma"

# Export Instagram cookies (re-run every ~90 days when Reels start failing)
# Install "Get cookies.txt LOCALLY" Chrome extension → export instagram.com cookies
flyctl secrets set INSTAGRAM_COOKIES_B64="$(base64 -i instagram_cookies.txt)"

# Deploy
flyctl deploy
```

**Useful commands:**
```bash
flyctl logs                  # live logs
flyctl deploy                # push new code
fly ssh console              # shell into container
flyctl secrets set KEY=val   # update a secret (triggers restart)
```

---

## Telegram Commands

| Command | What it does |
|---------|-------------|
| Send Instagram URL | Ingest the post or Reel |
| `/search <query>` | Semantic search, returns top 5 results with links |
| `/search <query> --k 3` | Return top 3 results |
| `/recent` | Last 5 ingested entries |
| `/recent 10` | Last 10 ingested entries |
| `/stats` | Total entries, breakdown by content type, difficulty, input type |

---

## CLI Search

```bash
python search.py "pandas performance"
python search.py "attention mechanism" --k 3 --json
python search.py "docker networking" --collection default
```

---

## Example Output

### Obsidian note (`2026-05-15_vectorized-operations-in-pandas.md`)

```markdown
---
id: a3f8c2d1-4e7b-4a9f-b2c1-8d3e6f1a2b4c
date: 2026-05-15T14:32:07Z
collection: default
content_type: technical-tutorial
tags: [pandas, vectorization, performance, numpy, python]
difficulty: intermediate
source_url: https://www.instagram.com/p/ABC123/
input_type: IMAGE_WITH_TEXT
obsidian_path: /data/vault/2026-05-15_vectorized-operations-in-pandas.md
---

## Key takeaway
Replacing .iterrows() with vectorized operations can make pandas code 100–1000× faster with no change in logic.

## Concept
Avoid `.iterrows()` for row-wise operations in pandas. Vectorized operations run in C via NumPy rather than in Python, eliminating the per-row overhead and making them orders of magnitude faster on large DataFrames.

## Use cases
- Transforming columns in large DataFrames without performance bottlenecks
- Replacing custom Python loops in data preprocessing pipelines

## Code
```python
# Slow — avoid
for idx, row in df.iterrows():
    df.at[idx, 'result'] = row['a'] + row['b']

# Fast — use this
df['result'] = df['a'] + df['b']
```

## Raw input
[POST TEXT]
Stop using .iterrows() — here's why it's destroying your performance
...
```

### `/search` result in Telegram

```
1. Vectorized Operations in Pandas [intermediate]
   Avoid .iterrows() for row-wise operations in pandas. Vectorized operations...
   Tags: pandas, vectorization, performance, numpy, python
   Note: /data/vault/2026-05-15_vectorized-operations-in-pandas.md
   https://www.instagram.com/p/ABC123/

2. NumPy Broadcasting for Array Operations [beginner]
   ...
```

---

## Maintenance

| Task | When | Command |
|------|------|---------|
| Refresh Instagram cookies | Every ~90 days when Reels fail | `flyctl secrets set INSTAGRAM_COOKIES_B64="$(base64 -i instagram_cookies.txt)"` |
| Update code | After changes | `git push && flyctl deploy` |
| Check logs | Anytime | `flyctl logs` |
| View vault data | Anytime | Check [obsidian-vault repo](https://github.com/Iva5858/obsidian-vault) on GitHub |

---

## What's Next

**PRDv3** — Multi-collection routing so posts are organised into topic namespaces (`ml`, `engineering`, `career`), a weekly digest sent via Telegram, and a FastAPI REST layer for external integrations.

**PRDv4** — Source-agnostic ingestion (YouTube, Twitter/X), retrieval reranking with a cross-encoder, and filtering by difficulty or topic.

# RAG Knowledge Base

A personal knowledge base that turns Instagram posts and Reels into a semantically searchable archive. Forward a link to the Telegram bot — the system downloads the content, extracts structured knowledge with an LLM, stores it as a vector in ChromaDB, and writes a human-readable note to an Obsidian vault. Retrieval is a CLI away.

---

## Architecture

```
INGESTION              PROCESSING                          STORAGE           RETRIEVAL
─────────              ──────────                          ───────           ─────────
                       ┌─ [image/carousel] → Vision LLM ──┐
Telegram Bot ────────→ ├─ [reel/video]    → Whisper ───────┼──→ LLM Extractor ──→ ChromaDB
(bot/bot.py)           └─ [text-only]     ──────────────────┘   (KnowledgeEntry)  + Obsidian .md
                           IngestHandler
                           (pipeline/ingest.py)
                           ↑
                     Instagram URL detected?
                     /p/  → /media/?size=l + og:description
                     /reel/ → yt-dlp
```

**Full data flow:**

1. User sends an Instagram URL to the Telegram bot
2. Bot passes the URL to `IngestHandler.process()`
3. IngestHandler detects the URL type:
   - Image post `/p/` — fetches the caption via `og:description` (Facebook crawler UA) and downloads all carousel slides via `/media/?size=l&index=N`, stopping when images repeat
   - Reel `/reel/` — downloads video and caption via `yt-dlp`
4. Visual content is routed to `VisionDescriber` (images) or `VideoTranscriber` (video)
5. Caption + visual description + user note are assembled into `combined_text`
6. `Extractor` sends `combined_text` to `gpt-4o-mini` and validates the JSON response as `ExtractionOutput`; retries once on parse failure
7. `Embedder` embeds `entry.embed_text` (title + concept + tags) via OpenAI `text-embedding-3-small`
8. `Store.upsert()` writes the vector and metadata to ChromaDB
9. `ObsidianWriter.write()` writes a `.md` file to the vault
10. Bot replies: `Saved: {title} [{tag1, tag2, tag3}]`

---

## Design Decisions

**`embed_text` is the extracted summary, not the raw post text.**
Raw Instagram captions are noisy — hashtag dumps, emojis, broken sentences. The extracted `title + concept + tags` is a clean, semantically dense representation of what the post actually teaches. Embedding this instead of the raw text produces measurably better retrieval precision.

**ChromaDB collections are parameterised from day one.**
Every function signature that touches ChromaDB accepts a `collection` parameter, even though v1 only uses `"default"`. This means multi-topic routing in v2 requires no architectural changes — just activating the routing logic at the marked `# PRDv2:` hook points.

**Video goes through Whisper, not a vision model.**
Instagram Reels are primarily audio-driven: the speaker explains the concept verbally while text overlays are secondary. A vision model sampling frames would miss most of the information. Whisper processes the full audio timeline and returns a transcript that captures everything said.

**Instagram images use `/media/?size=l`, not yt-dlp.**
yt-dlp requires a valid Instagram session (CSRF token) to access image posts. The `/media/?size=l` endpoint is publicly accessible and returns full-resolution JPEGs. Carousels are handled by incrementing the `index` parameter and stopping on the first duplicate (Instagram loops the last image rather than returning 404).

**Caption fetched via `og:description` with Facebook crawler UA.**
Instagram serves the full post caption in the `og:description` meta tag when the request comes from the Facebook external hit crawler. No authentication required for public posts.

**Tags normalised to `lowercase-hyphenated` form.**
The extraction prompt requests hyphens for multi-word tags, and a deterministic normalisation pass (`_normalize_tags`) enforces this after every LLM response — replacing spaces and underscores with hyphens, stripping special characters, and deduplicating. This prevents Obsidian from creating duplicate tags for `machine learning` vs `machine-learning` vs `machinelearning`.

---

## Setup

### Prerequisites

- Python 3.11+
- `ffmpeg` on PATH (`brew install ffmpeg` on macOS)
- OpenAI API key
- A Telegram bot token (create one via [@BotFather](https://t.me/botfather))
- Obsidian installed with a vault folder ready (optional — the folder is created automatically)

### 1. Clone and create the virtual environment

```bash
git clone <repo-url>
cd rag-knowledge-base
python3.11 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
pip install "openai-whisper==20231117" --no-build-isolation  # local Whisper only if needed
```

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

```
TELEGRAM_BOT_TOKEN=your_token_here
OPENAI_API_KEY=your_key_here
TELEGRAM_ALLOWED_USER_ID=your_telegram_user_id
```

`TELEGRAM_ALLOWED_USER_ID` is your personal Telegram numeric user ID — the bot silently rejects messages from anyone else. Find yours by messaging [@userinfobot](https://t.me/userinfobot) on Telegram.

### 4. Configure paths and models

Edit `config.yaml` to set your Obsidian vault path and any model preferences:

```yaml
obsidian:
  vault_path: ~/Documents/ObsidianVault/Knowledge Base

llm:
  extraction_model: gpt-4o-mini
  vision_model: gpt-4o-mini

embedding:
  provider: openai
  openai_model: text-embedding-3-small
```

### 5. (Optional) Set up Obsidian vault Git sync

This keeps a copy of every note on your local machine via the [Obsidian Git](https://github.com/denolehov/obsidian-git) plugin, even when the bot runs on a remote server.

**On your Mac — one-time setup:**
```bash
# 1. Make the vault a git repo (if it isn't already)
cd "~/Documents/ObsidianVault/Knowledge Base"
git init
git remote add origin https://github.com/<you>/obsidian-vault-private.git
git add . && git commit -m "Initial vault commit"
git push -u origin main
```

**Generate a GitHub Personal Access Token (PAT):**
- Go to GitHub → Settings → Developer settings → Personal access tokens → Fine-grained
- Grant **Contents: read & write** on the vault repo
- Copy the token

**In `config.yaml`:**
```yaml
obsidian:
  vault_path: ~/Documents/ObsidianVault/Knowledge Base
  git_remote: "https://<YOUR_PAT>@github.com/<you>/obsidian-vault-private.git"
  vault_sync_enabled: true
```

**On your Mac — install the Obsidian Git plugin:**
- Obsidian → Settings → Community plugins → Browse → search "Obsidian Git"
- Enable it and set **Auto pull interval** to 5 minutes

After this, every post you ingest will appear in your local Obsidian within minutes, regardless of where the bot is running.

### 6. Run the Telegram bot

```bash
python bot/bot.py
```

Forward any Instagram post or Reel URL to the bot. You will receive a confirmation within seconds:

```
Saved: Vectorized Operations in Pandas [pandas, performance, vectorization]
```

### 6. Deploy to Fly.io (always-on hosting)

**Prerequisites:** [Install flyctl](https://fly.io/docs/hands-on/install-flyctl/) and run `flyctl auth login`.

```bash
# 1. Edit fly.toml — replace "rag-knowledge-base" with your app name

# 2. Create the app (reads fly.toml — do not deploy yet)
flyctl launch --no-deploy

# 3. Create the persistent volume (1 GB is plenty for ChromaDB + vault)
flyctl volumes create rag_data --size 1 --region iad

# 4. Set all secrets (these are never stored in the image or fly.toml)
flyctl secrets set \
  TELEGRAM_BOT_TOKEN="your_token" \
  OPENAI_API_KEY="your_openai_key" \
  TELEGRAM_ALLOWED_USER_ID="your_telegram_id" \
  GIT_REMOTE="https://<YOUR_PAT>@github.com/<you>/obsidian-vault-private.git"

# 5. Deploy
flyctl deploy
```

On first boot, `scripts/entrypoint.sh` clones your Obsidian vault from `GIT_REMOTE` into `/data/vault`. The ChromaDB database lives at `/data/chroma`. Both persist across deployments via the `rag_data` volume.

**Cost note:** Fly.io's free tier allows 3 always-on shared VMs. This bot uses 1 (512 MB RAM). It will not spin down between messages — that is intentional for a Telegram bot.

**Logs:**
```bash
flyctl logs          # stream live logs
flyctl ssh console   # shell into the running container
```

### 7. Search the knowledge base

```bash
# Default: top 5 results
python search.py "pandas performance"

# Return 3 results as JSON
python search.py "attention mechanism transformer" --k 3 --json

# Specify collection (v1 uses "default" only)
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
tags: [pandas, vectorization, performance, numpy, python]
difficulty: intermediate
source_url: https://www.instagram.com/p/ABC123/
input_type: IMAGE_WITH_TEXT
obsidian_path: ~/Documents/ObsidianVault/Knowledge Base/2026-05-15_vectorized-operations-in-pandas.md
---

## Concept
Avoid `.iterrows()` for row-wise operations in pandas. Vectorized operations using NumPy under the hood are 100–1000× faster because they operate on entire arrays in C rather than looping in Python.

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

[VISUAL CONTENT]
[Slide 1 of 2]
Benchmark chart: iterrows() 45s vs vectorization 0.2s on 1M rows...
```

### CLI search result

```
$ python search.py "how to speed up pandas loops" --k 3

1. Vectorized Operations in Pandas [intermediate]
   Avoid .iterrows() for row-wise operations in pandas. Vectorized operations are 100–1000× faster...
   Tags: pandas, vectorization, performance, numpy, python
   Note: ~/Documents/ObsidianVault/Knowledge Base/2026-05-15_vectorized-operations-in-pandas.md

2. NumPy Broadcasting for Array Operations [beginner]
   Broadcasting allows NumPy to perform operations on arrays of different shapes without copying data...
   Tags: numpy, broadcasting, arrays, performance
   Note: ~/Documents/ObsidianVault/Knowledge Base/2026-05-14_numpy-broadcasting.md

3. Pandas apply() vs Vectorization Tradeoffs [advanced]
   .apply() with axis=1 is marginally faster than iterrows() but still Python-level; true vectorization...
   Tags: pandas, apply, vectorization, performance, python
   Note: ~/Documents/ObsidianVault/Knowledge Base/2026-05-13_pandas-apply-tradeoffs.md
```

---

## What's Next

**PRDv2** — Multi-collection support so posts can be routed to topic-specific namespaces (e.g. `ml`, `engineering`, `career`), plus a `/search` command directly in Telegram.

**PRDv3** — Weekly digest sent via Telegram summarising the week's saved content, and a FastAPI REST layer for external integrations.

**PRDv4** — Source-agnostic ingestion (YouTube, Twitter/X), retrieval reranking with a cross-encoder, and filtering by difficulty or topic before embedding.

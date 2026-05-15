"""Telegram bot: async, python-telegram-bot v21."""

import csv
import logging
import os
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

# Ensure project root is on sys.path when running as `python bot/bot.py`
sys.path.insert(0, str(Path(__file__).parent.parent))

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from config import get_config
from pipeline.ingest import DuplicateError, IngestHandler

logger = logging.getLogger(__name__)


async def _download_video(context: ContextTypes.DEFAULT_TYPE, file_id: str, tmp_dir: str) -> str:
    """Download a Telegram video file to tmp_dir and return its local path."""
    tg_file = await context.bot.get_file(file_id)
    ext = Path(tg_file.file_path).suffix if tg_file.file_path else ".mp4"
    local_path = Path(tmp_dir) / f"video{ext}"
    await tg_file.download_to_drive(str(local_path))
    return str(local_path)


def _is_authorized(update: Update) -> bool:
    """Return True if the sender matches TELEGRAM_ALLOWED_USER_ID."""
    allowed_id = int(os.getenv("TELEGRAM_ALLOWED_USER_ID", "0"))
    return update.effective_user.id == allowed_id


def _format_search_results(results: list, query: str) -> str:
    """Format SearchResult list as a numbered Telegram message."""
    if not results:
        return f'No results found for: "{query}"'
    lines: list[str] = []
    for i, r in enumerate(results, 1):
        concept_preview = r.concept[:100] + "..." if len(r.concept) > 100 else r.concept
        difficulty = f" [{r.difficulty}]" if r.difficulty else ""
        tags_str = ", ".join(r.tags[:5])  # cap tags to keep message compact
        note = r.obsidian_path or "—"
        lines += [
            f"{i}. {r.title}{difficulty}",
            f"   {concept_preview}",
            f"   Tags: {tags_str}",
            f"   Note: {note}",
        ]
        if r.source_url:
            lines.append(f"   {r.source_url}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# CSV helpers for /recent and /stats
# ---------------------------------------------------------------------------

def _read_csv(config) -> list[dict]:
    """Read all rows from directory.csv. Returns [] if the file doesn't exist yet."""
    csv_path = Path(config.storage.chroma_path).expanduser().parent / "directory.csv"
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _format_recent(rows: list[dict], n: int) -> str:
    """Format the n most recent entries as a Telegram message."""
    if not rows:
        return "No entries in the knowledge base yet."
    sorted_rows = sorted(rows, key=lambda r: r.get("date", ""), reverse=True)
    recent = sorted_rows[:n]
    lines: list[str] = [f"Last {len(recent)} entries:\n"]
    for i, row in enumerate(recent, 1):
        date = row.get("date", "")[:10]
        title = row.get("title") or "Untitled"
        difficulty = row.get("difficulty") or "—"
        ct = row.get("content_type") or "—"
        lines.append(f"{i}. {title}")
        lines.append(f"   {date} · {difficulty} · {ct}")
        if row.get("source_url"):
            lines.append(f"   {row['source_url']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_stats(rows: list[dict]) -> str:
    """Format knowledge base statistics as a Telegram message."""
    total = len(rows)
    if total == 0:
        return "No entries in the knowledge base yet."

    def _breakdown(field: str) -> str:
        counts = Counter(r.get(field) or "unknown" for r in rows)
        width = max(len(k) for k in counts)
        return "\n".join(
            f"  {k.ljust(width)}  {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])
        )

    return (
        f"Knowledge Base Stats\n"
        f"Total entries: {total}\n"
        f"\nBy content type:\n{_breakdown('content_type')}\n"
        f"\nBy difficulty:\n{_breakdown('difficulty')}\n"
        f"\nBy input type:\n{_breakdown('input_type')}"
    )


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def handle_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search <query> [--k <n>] command."""
    if not _is_authorized(update):
        await update.message.reply_text("Unauthorized.")
        return

    args: list[str] = context.args or []

    if not args:
        await update.message.reply_text(
            "Usage: /search <query> [--k <n>]\n"
            "Example: /search pandas groupby\n"
            "Example: /search attention mechanism --k 3"
        )
        return

    # Parse optional --k flag
    k = 5
    query_parts: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--k" and i + 1 < len(args):
            try:
                k = max(1, int(args[i + 1]))
            except ValueError:
                pass
            i += 2
        else:
            query_parts.append(args[i])
            i += 1

    query = " ".join(query_parts).strip()
    if not query:
        await update.message.reply_text("Please provide a search query after /search.")
        return

    try:
        handler: IngestHandler = context.bot_data["ingest_handler"]
        results = await handler.search(query, k=k)
        await update.message.reply_text(_format_search_results(results, query))
    except Exception as exc:
        logger.exception("Search error: %s", exc)
        await update.message.reply_text(f"Search failed: {type(exc).__name__}.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all incoming messages: text, photo, video, or combinations."""
    if not _is_authorized(update):
        await update.message.reply_text("Unauthorized.")
        return

    message = update.message
    if not message:
        return

    # Acknowledge receipt immediately (F-03)
    await message.reply_text("Got it, processing...")

    # Extract payload components
    text: str = message.text or message.caption or ""
    photo_bytes: bytes | None = None
    video_path: str | None = None
    user_note: str | None = None  # PRDv2: parse user note from message text

    tmp_dir: str | None = None

    try:
        # Extract photo bytes (F-10) — use largest available resolution
        if message.photo:
            tg_file = await context.bot.get_file(message.photo[-1].file_id)
            photo_bytes = bytes(await tg_file.download_as_bytearray())

        # Download video to temp dir (F-07, F-11)
        if message.video or message.document:
            file_obj = message.video or message.document
            tmp_dir = tempfile.mkdtemp(prefix="rag_video_")
            video_path = await _download_video(context, file_obj.file_id, tmp_dir)

        logger.info(
            "Payload | text=%s | photo=%s | video=%s | user_note=%s",
            bool(text), bool(photo_bytes), bool(video_path), user_note,
        )

        handler: IngestHandler = context.bot_data["ingest_handler"]

        # Check if this is a force re-ingest (user sent the same URL twice)
        force_urls: set[str] = context.user_data.setdefault("force_urls", set())
        is_force = text.strip() in force_urls

        entry = await handler.process(
            text=text,
            photo_bytes=photo_bytes,
            video_path=video_path,
            user_note=user_note,
            force=is_force,
        )

        force_urls.discard(text.strip())  # clear after successful force re-ingest
        await message.reply_text(f"Saved: {entry.title} [{', '.join(entry.tags[:3])}]")

    except DuplicateError as exc:
        # Add URL to force set — next send of the same URL will re-ingest (F-D2, F-D3)
        force_urls: set[str] = context.user_data.setdefault("force_urls", set())
        force_urls.add(text.strip())
        await message.reply_text(
            f"Already saved: {exc.title}\nSend the same link again to force re-ingest."
        )

    except Exception as exc:
        error_type = type(exc).__name__
        logger.exception("Pipeline error: %s", exc)
        await message.reply_text(f"Processing failed: {error_type}. Nothing was saved.")

    finally:
        # Clean up temp video dir (F-07)
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


async def handle_recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /recent [n] — show the last n ingested entries (default 5, max 20)."""
    if not _is_authorized(update):
        await update.message.reply_text("Unauthorized.")
        return

    n = 5
    if context.args:
        try:
            n = min(max(1, int(context.args[0])), 20)
        except ValueError:
            pass

    config = get_config()
    rows = _read_csv(config)
    await update.message.reply_text(_format_recent(rows, n))


async def handle_stats_command(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats — show knowledge base statistics."""
    if not _is_authorized(update):
        await update.message.reply_text("Unauthorized.")
        return

    config = get_config()
    rows = _read_csv(config)
    await update.message.reply_text(_format_stats(rows))


async def _post_init(app: Application) -> None:
    """Initialise shared pipeline objects once at startup."""
    config = get_config()
    app.bot_data["ingest_handler"] = IngestHandler(config)
    logger.info("IngestHandler initialised")


def main() -> None:
    """Start the bot."""
    logging.basicConfig(level=logging.INFO)
    config = get_config()

    app = (
        Application.builder()
        .token(config.telegram.bot_token)
        .post_init(_post_init)
        .build()
    )
    app.add_handler(CommandHandler("search", handle_search_command))
    app.add_handler(CommandHandler("recent", handle_recent_command))
    app.add_handler(CommandHandler("stats", handle_stats_command))
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    logger.info("Bot starting — polling for updates")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

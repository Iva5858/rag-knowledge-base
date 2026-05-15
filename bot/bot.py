"""Telegram bot: async, python-telegram-bot v21."""

import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path when running as `python bot/bot.py`
sys.path.insert(0, str(Path(__file__).parent.parent))

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from config import get_config
from pipeline.ingest import IngestHandler

logger = logging.getLogger(__name__)


async def _download_video(context: ContextTypes.DEFAULT_TYPE, file_id: str, tmp_dir: str) -> str:
    """Download a Telegram video file to tmp_dir and return its local path."""
    tg_file = await context.bot.get_file(file_id)
    ext = Path(tg_file.file_path).suffix if tg_file.file_path else ".mp4"
    local_path = Path(tmp_dir) / f"video{ext}"
    await tg_file.download_to_drive(str(local_path))
    return str(local_path)


async def handle_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stub handler for /search."""
    # PRDv2: multi-collection routing
    await update.message.reply_text("Coming in v2")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all incoming messages: text, photo, video, or combinations."""
    ALLOWED_USER_ID = int(os.getenv("TELEGRAM_ALLOWED_USER_ID"))

    if update.effective_user.id != ALLOWED_USER_ID:
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
        entry = await handler.process(
            text=text,
            photo_bytes=photo_bytes,
            video_path=video_path,
            user_note=user_note,
        )
        await message.reply_text(f"Saved: {entry.title} [{', '.join(entry.tags[:3])}]")

    except Exception as exc:
        error_type = type(exc).__name__
        logger.exception("Pipeline error: %s", exc)
        await message.reply_text(f"Processing failed: {error_type}. Nothing was saved.")

    finally:
        # Clean up temp video dir (F-07)
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


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
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    logger.info("Bot starting — polling for updates")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

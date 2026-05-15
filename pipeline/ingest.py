"""IngestHandler: detects input type, routes to vision/transcription, assembles combined_text."""

import asyncio
import html as html_module
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx

from config import Config, get_config
from models.schema import KnowledgeEntry
from pipeline.embedder import Embedder
from pipeline.extractor import Extractor
from pipeline.obsidian_writer import ObsidianWriter
from pipeline.store import Store
from pipeline.transcriber import VideoTranscriber
from pipeline.vision import VisionDescriber

logger = logging.getLogger(__name__)

InputType = Literal["TEXT", "IMAGE", "VIDEO", "IMAGE_WITH_TEXT", "VIDEO_WITH_TEXT"]

_INSTAGRAM_URL_RE = re.compile(r'https?://(?:www\.)?instagram\.com/\S+')
_VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mkv', '.mov', '.avi'}

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)
# Facebook crawler UA — Instagram serves the full og:description to it without requiring login
_FB_CRAWLER_UA = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"

# Matches og:description in either attribute order and any quote style
_OG_DESCRIPTION_RE = re.compile(
    r'<meta\s[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']*)["\']'
    r'|<meta\s[^>]*content=["\']([^"\']*)["\'][^>]*property=["\']og:description["\']',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Instagram URL fetching
# ---------------------------------------------------------------------------

def _extract_instagram_url(text: str) -> str | None:
    """Return the first Instagram URL found in text, or None."""
    m = _INSTAGRAM_URL_RE.search(text)
    return m.group(0).rstrip('.,;)') if m else None


async def _fetch_caption(clean_url: str) -> str:
    """Fetch the Instagram post caption from the og:description meta tag.

    Uses the Facebook crawler user-agent, which Instagram serves full captions to
    without requiring login. Falls back to empty string on any failure.
    """
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _FB_CRAWLER_UA},
            follow_redirects=True,
            timeout=15,
        ) as client:
            resp = await client.get(clean_url)

        if resp.status_code != 200:
            logger.warning("Caption fetch returned HTTP %d for %s", resp.status_code, clean_url)
            return ""

        match = _OG_DESCRIPTION_RE.search(resp.text)
        if match:
            raw = match.group(1) or match.group(2) or ""
            caption = html_module.unescape(raw)
            logger.info("Caption fetched (%d chars): %.120s", len(caption), caption)
            return caption

        logger.warning("No og:description found for %s", clean_url)
        return ""

    except Exception as exc:
        logger.warning("Caption fetch failed for %s: %s", clean_url, exc)
        return ""


async def _fetch_image_bytes(clean_url: str) -> list[bytes]:
    """Download all images from an Instagram post using /media/?size=l.

    Tries sequential indices (0, 1, 2 …) for carousel support.
    Stops when: response is not 200, content-type is not image, or the image
    bytes are identical to a previously seen slide (Instagram loops the last
    image rather than returning 404 for out-of-range indices).
    """
    import hashlib

    images: list[bytes] = []
    seen_hashes: set[bytes] = set()

    async with httpx.AsyncClient(
        headers={"User-Agent": _MOBILE_UA},
        follow_redirects=True,
        timeout=30,
    ) as client:
        for index in range(20):  # hard cap at 20 slides
            url = f"{clean_url}/media/?size=l" if index == 0 else f"{clean_url}/media/?size=l&index={index}"
            resp = await client.get(url)
            if resp.status_code != 200:
                break
            if "image" not in resp.headers.get("content-type", ""):
                break
            img_hash = hashlib.md5(resp.content).digest()
            if img_hash in seen_hashes:
                break  # carousel exhausted — Instagram looped back to a seen image
            seen_hashes.add(img_hash)
            images.append(resp.content)
            logger.info("Downloaded slide %d (%d bytes)", index, len(resp.content))

    if not images:
        raise RuntimeError(
            f"Could not fetch image(s) from {clean_url}/media/?size=l — "
            "the post may be private or the URL format is unsupported."
        )
    return images


async def _fetch_image_post(clean_url: str) -> tuple[str, list[bytes]]:
    """Fetch caption and images in parallel. Returns (caption, image_bytes_list)."""
    caption, images = await asyncio.gather(
        _fetch_caption(clean_url),
        _fetch_image_bytes(clean_url),
    )
    return caption, images


async def _fetch_reel(url: str, tmp_dir: str) -> tuple[str, str]:
    """Download an Instagram Reel via yt-dlp. Returns (caption, video_path)."""
    import yt_dlp  # only imported for video/reel posts

    ydl_opts = {
        "outtmpl": os.path.join(tmp_dir, "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }

    def _download() -> dict:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=True)

    info = await asyncio.to_thread(_download)
    caption: str = info.get("description") or info.get("title") or ""

    video_files = [p for p in Path(tmp_dir).iterdir() if p.suffix.lower() in _VIDEO_EXTENSIONS]
    if not video_files:
        raise RuntimeError(f"yt-dlp downloaded no video for: {url}")

    return caption, str(video_files[0])


async def _fetch_instagram(
    url: str, tmp_dir: str
) -> tuple[str, str | None, list[bytes]]:
    """Route to the correct fetcher based on URL type.

    Returns (caption, video_path_or_None, image_bytes_list).
    image_bytes_list is empty for video posts; video_path is None for image posts.
    """
    clean_url = url.split("?")[0].rstrip("/")
    is_video = "/reel/" in url or "/tv/" in url

    if is_video:
        caption, video_path = await _fetch_reel(url, tmp_dir)
        return caption, video_path, []
    else:
        caption, images = await _fetch_image_post(clean_url)
        return caption, None, images


# ---------------------------------------------------------------------------
# Input type detection and combined_text assembly
# ---------------------------------------------------------------------------

def _detect_input_type(
    text: str,
    has_image: bool,
    has_video: bool,
) -> InputType:
    """Detect input type from payload shape (F-09)."""
    has_text = bool(text and text.strip())
    if has_image and has_text:
        return "IMAGE_WITH_TEXT"
    if has_image:
        return "IMAGE"
    if has_video and has_text:
        return "VIDEO_WITH_TEXT"
    if has_video:
        return "VIDEO"
    return "TEXT"


def _build_combined_text(text: str, visual_content: str, user_note: str | None) -> str:
    """Assemble combined_text in the canonical format from PRD section 5.2 (F-12)."""
    return (
        f"[POST TEXT]\n{text}\n\n"
        f"[VISUAL CONTENT]\n{visual_content}\n\n"
        f"[USER NOTE]\n{user_note or ''}"
    )


# ---------------------------------------------------------------------------
# IngestHandler
# ---------------------------------------------------------------------------

class DuplicateError(Exception):
    """Raised when the source URL already exists in the knowledge base."""

    def __init__(self, title: str, source_url: str) -> None:
        super().__init__(f"Already saved: {title}")
        self.title = title
        self.source_url = source_url


class IngestHandler:
    def __init__(self, config: Config | None = None) -> None:
        self._config = config or get_config()
        self._vision = VisionDescriber(self._config)
        self._transcriber = VideoTranscriber(self._config)
        self._extractor = Extractor(self._config)
        self._embedder = Embedder(self._config)
        self._store = Store(self._config)
        self._writer = ObsidianWriter(self._config)

    async def process(
        self,
        text: str,
        photo_bytes: bytes | None,
        video_path: str | None,
        user_note: str | None,
        force: bool = False,
    ) -> KnowledgeEntry:
        """Route payload through the full pipeline and return the stored KnowledgeEntry."""
        tmp_dir: str | None = None
        carousel_images: list[bytes] = []

        try:
            # Detect and fetch Instagram URL if the message is a share link
            instagram_url = _extract_instagram_url(text)

            # Duplicate check — skip if force re-ingest requested (F-D1, F-D2, F-D3)
            if instagram_url and not force:
                existing_title = self._store.find_by_url(instagram_url)
                if existing_title is not None:
                    raise DuplicateError(title=existing_title, source_url=instagram_url)

            if instagram_url and not photo_bytes and not video_path:
                logger.info("Instagram URL detected: %s", instagram_url)
                tmp_dir = tempfile.mkdtemp(prefix="rag_ig_")
                caption, fetched_video, fetched_images = await _fetch_instagram(
                    instagram_url, tmp_dir
                )
                text = f"{caption}\n\n{instagram_url}" if caption else instagram_url
                video_path = fetched_video

                if len(fetched_images) == 1:
                    photo_bytes = fetched_images[0]
                elif len(fetched_images) > 1:
                    carousel_images = fetched_images  # handled below

            # Determine input type
            has_image = bool(photo_bytes or carousel_images)
            input_type = _detect_input_type(text, has_image, bool(video_path))
            logger.info("Processing input_type=%s, slides=%d", input_type, len(carousel_images))

            # Route to vision / transcription (F-10, F-11)
            visual_content = ""
            if carousel_images:
                # Describe every carousel slide and label them
                descriptions: list[str] = []
                for i, img in enumerate(carousel_images, 1):
                    desc = await self._vision.describe(img)
                    label = f"[Slide {i} of {len(carousel_images)}]\n"
                    descriptions.append(f"{label}{desc}")
                visual_content = "\n\n".join(descriptions)
            elif photo_bytes:
                visual_content = await self._vision.describe(photo_bytes)
            elif video_path:
                visual_content = await self._transcriber.transcribe(video_path)

            # Assemble combined_text (F-12)
            combined_text = _build_combined_text(text, visual_content, user_note)

            # Extract structured knowledge
            extraction = await self._extractor.extract(combined_text, user_note)

            # Build KnowledgeEntry with identity fields (F-13, F-14, F-15)
            entry = KnowledgeEntry(
                id=str(uuid4()),                                                      # F-13
                date=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),  # F-14
                collection="default",                                                 # PRDv3: multi-collection routing
                input_type=input_type,
                raw_text=combined_text,
                user_note=user_note,
                title=extraction.title,
                content_type=extraction.content_type,
                concept=extraction.concept,
                key_takeaway=extraction.key_takeaway,
                tags=extraction.tags,
                code_snippets=extraction.code_snippets,
                use_cases=extraction.use_cases,
                difficulty=extraction.difficulty,
                source_url=extraction.source_url,
            )

            # Embed → store → write (F-34 → F-39 → F-44)
            vector = await self._embedder.embed(entry)
            self._store.upsert(entry, vector)
            self._writer.write(entry)

            logger.info(
                "Entry saved: id=%s title=%r obsidian=%s",
                entry.id, entry.title, entry.obsidian_path,
            )
            return entry

        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

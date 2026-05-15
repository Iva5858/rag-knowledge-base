"""VideoTranscriber: local video file → plain text transcript via Whisper."""

import asyncio
import logging
import os
import tempfile

from openai import AsyncOpenAI

from config import Config, get_config

logger = logging.getLogger(__name__)


class VideoDurationError(ValueError):
    """Raised when a video exceeds the configured maximum duration."""


class VideoTranscriber:
    def __init__(self, config: Config | None = None) -> None:
        self._config = config or get_config()
        self._client = AsyncOpenAI()

    async def transcribe(self, video_path: str) -> str:
        """Accept a local video file path; return plain text transcript."""
        await self._check_duration(video_path)

        audio_path: str | None = None
        try:
            audio_path = await self._extract_audio(video_path)

            if self._config.whisper.use_local:
                transcript = await asyncio.to_thread(self._transcribe_local, audio_path)
            else:
                transcript = await self._transcribe_api(audio_path)

            if not transcript or len(transcript.strip()) < 20:
                return "No speech detected."
            return transcript.strip()

        finally:
            # Always clean up temp audio file (F-25)
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)

    async def _check_duration(self, video_path: str) -> None:
        """Raise VideoDurationError if video exceeds max_video_duration_seconds (F-26)."""
        max_secs = self._config.whisper.max_video_duration_seconds

        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        try:
            duration = float(stdout.decode().strip())
        except ValueError:
            logger.warning("Could not parse video duration for %s, proceeding anyway", video_path)
            return

        if duration > max_secs:
            raise VideoDurationError(
                f"Video is {duration:.0f}s, which exceeds the {max_secs}s ({max_secs // 60}-minute) limit. "
                "Please forward videos under 5 minutes."
            )

    async def _extract_audio(self, video_path: str) -> str:
        """Extract audio from video to a temp WAV file using the exact ffmpeg command from PRD (F-21)."""
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="rag_audio_")
        tmp.close()
        audio_path = tmp.name

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            audio_path, "-y",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg audio extraction failed: {stderr.decode()}")

        return audio_path

    async def _transcribe_api(self, audio_path: str) -> str:
        """Transcribe using OpenAI Whisper API (whisper-1) (F-22)."""
        with open(audio_path, "rb") as f:
            response = await self._client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
            )
        return response.text

    def _transcribe_local(self, audio_path: str) -> str:
        """Transcribe using local openai-whisper package (F-23). Blocking — called via asyncio.to_thread."""
        import whisper  # only imported when whisper.use_local = true
        model = whisper.load_model(self._config.whisper.local_model_size)
        result = model.transcribe(audio_path)
        return result["text"]

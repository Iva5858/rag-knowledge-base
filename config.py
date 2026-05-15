"""Config singleton: loads config.yaml and .env at startup."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

_CONFIG_PATH = Path(__file__).parent / "config.yaml"


@dataclass
class TelegramConfig:
    bot_token_env: str
    allowed_user_id_env: str = "TELEGRAM_ALLOWED_USER_ID"

    @property
    def bot_token(self) -> str:
        """Return the bot token from the environment variable named by bot_token_env."""
        token = os.environ.get(self.bot_token_env)
        if not token:
            raise RuntimeError(f"Environment variable '{self.bot_token_env}' is not set.")
        return token

    @property
    def allowed_user_id(self) -> int | None:
        """Return the allowed Telegram user ID, or None if the env var is not set."""
        value = os.environ.get(self.allowed_user_id_env)
        return int(value) if value else None


@dataclass
class LLMConfig:
    extraction_model: str
    vision_model: str


@dataclass
class WhisperConfig:
    use_local: bool
    local_model_size: str
    max_video_duration_seconds: int


@dataclass
class EmbeddingConfig:
    provider: str
    openai_model: str
    local_model: str


@dataclass
class StorageConfig:
    chroma_path: str
    default_collection: str


@dataclass
class ObsidianConfig:
    vault_path: str

    @property
    def resolved_vault_path(self) -> Path:
        """Return vault_path with ~ expanded to an absolute Path."""
        return Path(self.vault_path).expanduser()


class Config:
    """Typed configuration loaded from config.yaml. Instantiate with Config()."""

    def __init__(self, path: Path = _CONFIG_PATH) -> None:
        _check_ffmpeg()
        with open(path, "r") as f:
            raw = yaml.safe_load(f)

        self.telegram = TelegramConfig(**raw["telegram"])
        self.llm = LLMConfig(**raw["llm"])
        self.whisper = WhisperConfig(**raw["whisper"])
        self.embedding = EmbeddingConfig(**raw["embedding"])
        self.storage = StorageConfig(**raw["storage"])
        self.obsidian = ObsidianConfig(**raw["obsidian"])


def _check_ffmpeg() -> None:
    """Raise RuntimeError with install instructions if ffmpeg is not on PATH."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install it before running this application.\n"
            "  macOS:  brew install ffmpeg\n"
            "  Ubuntu: sudo apt-get install ffmpeg"
        )


_instance: Config | None = None


def get_config() -> Config:
    """Return the global Config singleton, loading from disk on first call."""
    global _instance
    if _instance is None:
        _instance = Config()
    return _instance

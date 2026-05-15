"""Embedder: KnowledgeEntry.embed_text → list[float] vector."""

import logging

from openai import AsyncOpenAI

from config import Config, get_config
from models.schema import KnowledgeEntry

logger = logging.getLogger(__name__)


class Embedder:
    def __init__(self, config: Config | None = None) -> None:
        self._config = config or get_config()
        self._client = AsyncOpenAI()

    async def embed(self, entry: KnowledgeEntry) -> list[float]:
        """Embed entry.embed_text and return a list[float] vector (F-34, F-37)."""
        return await self.embed_query(entry.embed_text)

    async def embed_query(self, text: str) -> list[float]:
        """Embed a raw string — used by the CLI search tool."""
        if self._config.embedding.provider == "sentence-transformers":
            return await self._embed_local(text)
        return await self._embed_openai(text)

    async def _embed_openai(self, text: str) -> list[float]:
        """Embed using OpenAI text-embedding-3-small (F-35)."""
        response = await self._client.embeddings.create(
            model=self._config.embedding.openai_model,
            input=text,
        )
        return response.data[0].embedding

    async def _embed_local(self, text: str) -> list[float]:
        """Embed using sentence-transformers all-MiniLM-L6-v2 (F-36). Blocking — runs in thread."""
        import asyncio
        return await asyncio.to_thread(self._embed_local_sync, text)

    def _embed_local_sync(self, text: str) -> list[float]:
        """Synchronous sentence-transformers inference."""
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(self._config.embedding.local_model)
        return model.encode(text).tolist()

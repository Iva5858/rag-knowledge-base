"""Store: ChromaDB read/write operations."""

import csv
import io
import logging
from pathlib import Path

import logging

import chromadb
from chromadb.config import Settings

from config import Config, get_config

# chromadb 0.5.3 has a posthog API mismatch that produces noisy ERROR logs.
# Telemetry is already non-functional; suppress the logger rather than let it spam stdout.
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)
from models.schema import KnowledgeEntry, SearchResult

logger = logging.getLogger(__name__)

# Ordered columns written to directory.csv.
# Lists are semicolon-joined so commas inside values don't break CSV parsing.
_CSV_COLUMNS = [
    "id", "date", "collection", "input_type", "content_type",
    "title", "concept", "key_takeaway",
    "tags", "use_cases", "difficulty", "source_url", "user_note", "obsidian_path",
]


def _entry_to_csv_row(entry: KnowledgeEntry) -> dict:
    """Convert a KnowledgeEntry to a flat dict suitable for a CSV row."""
    return {
        "id": entry.id,
        "date": entry.date,
        "collection": entry.collection,
        "input_type": entry.input_type,
        "content_type": entry.content_type or "",
        "title": entry.title,
        "concept": entry.concept,
        "key_takeaway": entry.key_takeaway,
        "tags": ";".join(entry.tags),
        "use_cases": ";".join(entry.use_cases),
        "difficulty": entry.difficulty or "",
        "source_url": entry.source_url or "",
        "user_note": entry.user_note or "",
        "obsidian_path": entry.obsidian_path or "",
    }


def _serialize_metadata(entry: KnowledgeEntry) -> dict:
    """Convert KnowledgeEntry scalar fields to ChromaDB-compatible metadata (F-40).

    ChromaDB only accepts str/int/float/bool values. None → "". Lists → comma-joined strings.
    code_snippets are excluded (complex objects; full content lives in the Obsidian .md file).
    """
    return {
        "id": entry.id,
        "date": entry.date,
        "collection": entry.collection,
        "input_type": entry.input_type,
        "content_type": entry.content_type or "",
        "raw_text": entry.raw_text,
        "user_note": entry.user_note or "",
        "title": entry.title,
        "concept": entry.concept,
        "key_takeaway": entry.key_takeaway,
        "tags": ",".join(entry.tags),
        "use_cases": ",".join(entry.use_cases),
        "difficulty": entry.difficulty or "",
        "source_url": entry.source_url or "",
        "obsidian_path": entry.obsidian_path or "",
    }


def _deserialize_tags(raw: str) -> list[str]:
    """Split a comma-joined tag string back into a list, handling empty strings."""
    return [t for t in raw.split(",") if t]


class Store:
    def __init__(self, config: Config | None = None) -> None:
        self._config = config or get_config()
        chroma_path = Path(self._config.storage.chroma_path).expanduser()
        self._client = chromadb.PersistentClient(
            path=str(chroma_path),
            settings=Settings(anonymized_telemetry=False),
        )
        # directory.csv lives next to the chroma folder, e.g. ./data/directory.csv
        self._csv_path = chroma_path.parent / "directory.csv"

    def _get_collection(self, name: str) -> chromadb.Collection:
        """Return the named collection, creating it if it does not exist (F-43)."""
        return self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def _upsert_csv(self, entry: KnowledgeEntry) -> None:
        """Write or update the entry's row in directory.csv (upsert by id)."""
        new_row = _entry_to_csv_row(entry)

        # Read existing rows, replacing any with the same id
        existing: list[dict] = []
        if self._csv_path.exists():
            with self._csv_path.open(newline="", encoding="utf-8") as f:
                existing = [r for r in csv.DictReader(f) if r.get("id") != entry.id]

        existing.append(new_row)

        with self._csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(existing)

        logger.info("directory.csv updated (%d rows)", len(existing))

    def find_by_url(self, source_url: str, collection: str = "default") -> str | None:
        """Return the title of an existing entry matching source_url, or None (F-D4)."""
        if not source_url:
            return None
        try:
            col = self._get_collection(collection)
            results = col.get(
                where={"source_url": source_url},
                include=["metadatas"],
            )
            if results["ids"]:
                return results["metadatas"][0].get("title") or ""
        except Exception as exc:
            logger.warning("find_by_url failed for %s: %s", source_url, exc)
        return None

    def upsert(self, entry: KnowledgeEntry, vector: list[float]) -> None:
        """Write entry and its vector to ChromaDB, and update directory.csv (F-39)."""
        collection = self._get_collection(entry.collection)
        collection.upsert(
            ids=[entry.id],
            embeddings=[vector],
            documents=[entry.embed_text],
            metadatas=[_serialize_metadata(entry)],
        )
        logger.info("Upserted entry %s into collection '%s'", entry.id, entry.collection)
        self._upsert_csv(entry)

    def search(self, query_vector: list[float], k: int, collection: str) -> list[SearchResult]:
        """Return top-k results for query_vector from the named collection (F-41)."""
        col = self._get_collection(collection)
        results = col.query(
            query_embeddings=[query_vector],
            n_results=k,
            include=["metadatas", "distances"],
        )

        search_results: list[SearchResult] = []
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        for meta, distance in zip(metadatas, distances):
            search_results.append(SearchResult(
                entry_id=meta["id"],
                title=meta["title"],
                concept=meta["concept"],
                tags=_deserialize_tags(meta["tags"]),
                difficulty=meta["difficulty"] or None,
                obsidian_path=meta["obsidian_path"] or None,
                source_url=meta.get("source_url") or None,
                distance=distance,
            ))

        return search_results

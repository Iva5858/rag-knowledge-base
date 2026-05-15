"""Extractor: combined_text → ExtractionOutput via LLM with retry logic."""

import json
import logging
import re

from openai import AsyncOpenAI
from pydantic import ValidationError

from config import Config, get_config
from models.schema import ExtractionOutput

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are extracting structured knowledge from an Instagram post for a personal RAG knowledge base.\n"
    "The post may contain a description of an image, a video transcript, or raw text.\n"
    "\n"
    "Return ONLY a valid JSON object. No markdown, no explanation, no code fences.\n"
    "The JSON must match this exact structure:\n"
    "{\n"
    '  "title": "string, max 10 words, descriptive",\n'
    '  "concept": "string, 1-2 sentences explaining the core idea",\n'
    '  "tags": ["lowercase", "strings", "tools", "techniques", "libraries"],\n'
    '  "code_snippets": [{"language": "python", "code": "the code here"}],\n'
    '  "use_cases": ["practical application 1", "practical application 2"],\n'
    '  "difficulty": "beginner | intermediate | advanced",\n'
    '  "source_url": "string or null"\n'
    "}\n"
    "\n"
    "Rules:\n"
    "- tags must include all tools, libraries, and techniques mentioned\n"
    "- tags must be lowercase; use hyphens for multi-word terms (e.g. \"machine-learning\", \"neural-network\", not \"machine learning\" or \"machinelearning\")\n"
    "- code_snippets is an empty list if no code is present\n"
    "- difficulty must always be set; infer from context if not explicit\n"
    "- source_url is null unless a URL is present in the input text"
)


def _normalize_tag(tag: str) -> str:
    """Normalize a single tag to lowercase-hyphenated form.

    Converts spaces and underscores to hyphens, strips non-alphanumeric
    characters, and deduplicates hyphens. This is a safety net for LLM
    inconsistencies even after the prompt explicitly requests hyphens.
    """
    tag = tag.lower().strip()
    tag = re.sub(r"[\s_]+", "-", tag)          # spaces/underscores → hyphens
    tag = re.sub(r"[^\w-]", "", tag)            # strip anything else
    tag = re.sub(r"-{2,}", "-", tag)            # collapse double hyphens
    return tag.strip("-")


def _normalize_tags(tags: list[str]) -> list[str]:
    """Normalize all tags and remove empty strings or duplicates."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in tags:
        normalized = _normalize_tag(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


class ExtractionError(Exception):
    """Raised when the LLM response cannot be parsed after one retry."""

    def __init__(self, message: str, raw_response: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response


class Extractor:
    def __init__(self, config: Config | None = None) -> None:
        self._config = config or get_config()
        self._client = AsyncOpenAI()

    async def extract(self, combined_text: str, user_note: str | None) -> ExtractionOutput:
        """Accept combined_text and optional user_note; return validated ExtractionOutput."""
        user_message = self._build_user_message(combined_text, user_note)

        raw = await self._call_llm(user_message)
        result, parse_error = self._try_parse(raw)
        if result is not None:
            return result

        # First attempt failed — retry with amended prompt including failed output and error (F-31)
        logger.warning("Extraction attempt 1 failed (%s), retrying", parse_error)
        retry_message = self._build_retry_message(user_message, raw, parse_error)
        raw2 = await self._call_llm(retry_message)
        result, parse_error2 = self._try_parse(raw2)
        if result is not None:
            return result

        # Second failure — raise ExtractionError with raw response attached (F-32)
        raise ExtractionError(
            f"Extraction failed after retry: {parse_error2}",
            raw_response=raw2,
        )

    def _build_user_message(self, combined_text: str, user_note: str | None) -> str:
        """Assemble the user-facing prompt from combined_text and optional note."""
        parts = [combined_text]
        if user_note:
            parts.append(f"\n[USER NOTE]\n{user_note}")
        return "\n".join(parts)

    def _build_retry_message(
        self, original_message: str, failed_output: str, parse_error: str | None
    ) -> str:
        """Amend the original prompt with the failed output and parse error for the retry."""
        return (
            f"{original_message}\n\n"
            "---\n"
            "Your previous response could not be parsed. "
            f"Parse error: {parse_error}\n"
            f"Your previous response was:\n{failed_output}\n\n"
            "Return ONLY a valid JSON object with no markdown, no explanation, no code fences."
        )

    async def _call_llm(self, user_message: str) -> str:
        """Call the extraction LLM and return the raw response string."""
        response = await self._client.chat.completions.create(
            model=self._config.llm.extraction_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
        )
        return response.choices[0].message.content or ""

    def _try_parse(self, raw: str) -> tuple[ExtractionOutput | None, str | None]:
        """Try to parse and validate the LLM response. Returns (result, error_string)."""
        try:
            data = json.loads(raw)
            output = ExtractionOutput.model_validate(data)
            output.tags = _normalize_tags(output.tags)
            return output, None
        except json.JSONDecodeError as exc:
            logger.warning("JSONDecodeError: %s | raw: %.300s", exc, raw)
            return None, f"JSONDecodeError: {exc}"
        except ValidationError as exc:
            logger.warning("ValidationError: %s | raw: %.300s", exc, raw)
            return None, f"ValidationError: {exc}"

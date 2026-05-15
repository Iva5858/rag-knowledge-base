"""ObsidianWriter: KnowledgeEntry → .md file in Obsidian vault."""

import logging
import re
from pathlib import Path

from config import Config, get_config
from models.schema import KnowledgeEntry

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Lowercase, spaces to hyphens, strip non-alphanumeric characters."""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")


def _unique_path(vault: Path, date_str: str, slug: str) -> Path:
    """Return a unique .md path, appending _2, _3, etc. if the filename already exists (F-46)."""
    base = vault / f"{date_str}_{slug}.md"
    if not base.exists():
        return base
    counter = 2
    while True:
        candidate = vault / f"{date_str}_{slug}_{counter}.md"
        if not candidate.exists():
            return candidate
        counter += 1


def _build_markdown(entry: KnowledgeEntry, resolved_path: str) -> str:
    """Build the full .md file content matching the exact format in PRD section 5.8."""
    tags_inline = ", ".join(entry.tags)
    raw_truncated = entry.raw_text[:500]
    truncation_suffix = " [truncated]" if len(entry.raw_text) > 500 else ""

    # Frontmatter
    lines = [
        "---",
        f"id: {entry.id}",
        f"date: {entry.date}",
        f"collection: {entry.collection}",
        f"content_type: {entry.content_type or 'general'}",
        f"tags: [{tags_inline}]",
        f"difficulty: {entry.difficulty}",
        f"source_url: {entry.source_url or 'null'}",
        f"input_type: {entry.input_type}",
        f"obsidian_path: {resolved_path}",
        "---",
        "",
        "## Key takeaway",
        entry.key_takeaway or "_No takeaway extracted._",
        "",
        "## Concept",
        entry.concept,
        "",
        "## Use cases",
    ]

    for use_case in entry.use_cases:
        lines.append(f"- {use_case}")

    lines += ["", "## Code"]

    if entry.code_snippets:
        for snippet in entry.code_snippets:
            lines += [f"```{snippet.language}", snippet.code, "```", ""]
    else:
        lines += ["No code snippets.", ""]

    lines += [
        "## Raw input",
        f"{raw_truncated}{truncation_suffix}",
    ]

    return "\n".join(lines)


class ObsidianWriter:
    def __init__(self, config: Config | None = None) -> None:
        self._config = config or get_config()
        self._vault = self._config.obsidian.resolved_vault_path

    def write(self, entry: KnowledgeEntry) -> None:
        """Write entry to a .md file in the vault; sets entry.obsidian_path (F-44, F-47)."""
        self._vault.mkdir(parents=True, exist_ok=True)

        date_str = entry.date[:10]  # YYYY-MM-DD from ISO 8601
        slug = _slugify(entry.title) or entry.id  # fall back to id if title is empty
        path = _unique_path(self._vault, date_str, slug)

        resolved = str(path)
        content = _build_markdown(entry, resolved)
        path.write_text(content, encoding="utf-8")

        entry.obsidian_path = resolved
        logger.info("Wrote Obsidian note: %s", resolved)

"""KnowledgeEntry, SearchResult, ExtractionOutput — schema contract. Do not modify without explicit approval."""

from pydantic import BaseModel, Field
from typing import Literal

ContentType = Literal[
    "technical-tutorial",
    "project-showcase",
    "tool-overview",
    "career-advice",
    "industry-insight",
    "general",
]


class CodeSnippet(BaseModel):
    language: str
    code: str


class KnowledgeEntry(BaseModel):
    # Identity
    id: str                                    # uuid4, set by IngestHandler
    date: str                                  # ISO 8601 UTC, set by IngestHandler
    collection: str = "default"                # PRDv3: routing logic sets this

    # Input metadata
    input_type: Literal["TEXT", "IMAGE", "VIDEO", "IMAGE_WITH_TEXT", "VIDEO_WITH_TEXT"]
    raw_text: str                              # combined_text before extraction
    user_note: str | None = None

    # Extracted fields (set by Extractor)
    title: str = ""
    content_type: ContentType | None = None    # Added PRDv2
    concept: str = ""
    key_takeaway: str = ""                     # Added PRDv2
    tags: list[str] = Field(default_factory=list)
    code_snippets: list[CodeSnippet] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    difficulty: Literal["beginner", "intermediate", "advanced"] | None = None
    source_url: str | None = None

    # Storage metadata (set by ObsidianWriter)
    obsidian_path: str | None = None

    @property
    def embed_text(self) -> str:
        """Text to embed: title + concept + key_takeaway + tags. Not raw post text."""
        tag_str = " ".join(self.tags)
        return f"{self.title}. {self.concept} {self.key_takeaway} {tag_str}".strip()


class SearchResult(BaseModel):
    entry_id: str
    title: str
    concept: str
    tags: list[str]
    difficulty: str | None
    obsidian_path: str | None
    distance: float


class ExtractionOutput(BaseModel):
    """Internal model used only by extractor.py to validate LLM JSON before merging into KnowledgeEntry."""
    title: str
    content_type: ContentType                  # Required — model must always classify
    concept: str
    key_takeaway: str                          # Required — one-sentence practitioner takeaway
    tags: list[str]
    code_snippets: list[CodeSnippet] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    difficulty: Literal["beginner", "intermediate", "advanced"]
    source_url: str | None = None

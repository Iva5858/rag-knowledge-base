"""VisionDescriber: image bytes → plain text description via vision LLM."""

import base64
import logging

from openai import AsyncOpenAI

from config import Config, get_config

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are processing an Instagram post image for a technical knowledge base.\n"
    "Your task:\n"
    "1. Transcribe ALL visible text verbatim, preserving formatting\n"
    "2. Describe any diagrams, charts, or visual explanations in detail\n"
    "3. Identify and reproduce any code snippets, noting the programming language\n"
    "4. Note any tool names, library names, or technology references visible\n"
    "Return plain text only. No formatting, no preamble."
)


class VisionDescriber:
    def __init__(self, config: Config | None = None) -> None:
        self._config = config or get_config()
        self._client = AsyncOpenAI()

    async def describe(self, image_bytes: bytes) -> str:
        """Accept raw image bytes; return plain text description of image content."""
        b64 = base64.b64encode(image_bytes).decode("utf-8")

        try:
            response = await self._client.chat.completions.create(
                model=self._config.llm.vision_model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                            }
                        ],
                    },
                ],
                max_tokens=1024,
            )
            result = response.choices[0].message.content or ""
            if not result.strip():
                return "No extractable technical content."
            return result.strip()
        except Exception as exc:
            logger.error("Vision API call failed: %s", exc)
            raise

"""CLI semantic search tool."""

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _check_chroma_path(chroma_path: str) -> None:
    """Exit with code 1 and an error message if the ChromaDB path does not exist (F-57)."""
    if not Path(chroma_path).expanduser().exists():
        print(f"Error: ChromaDB path '{chroma_path}' does not exist. Ingest some content first.", file=sys.stderr)
        sys.exit(1)


def _format_results(results: list, query: str) -> str:
    """Format search results as a numbered list (F-56)."""
    if not results:
        return f'No results found for: "{query}"'

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        concept_preview = r.concept[:100] + "..." if len(r.concept) > 100 else r.concept
        tags_str = ", ".join(r.tags)
        difficulty = f" [{r.difficulty}]" if r.difficulty else ""
        obsidian = r.obsidian_path or "—"

        lines += [
            f"{i}. {r.title}{difficulty}",
            f"   {concept_preview}",
            f"   Tags: {tags_str}",
            f"   Note: {obsidian}",
            "",
        ]

    return "\n".join(lines).rstrip()


async def _run_search(query: str, k: int, collection: str) -> list:
    """Embed query and retrieve top-k results from ChromaDB."""
    from config import get_config
    from pipeline.embedder import Embedder
    from pipeline.store import Store

    config = get_config()
    _check_chroma_path(config.storage.chroma_path)

    embedder = Embedder(config)
    store = Store(config)

    vector = await embedder.embed_query(query)
    return store.search(vector, k, collection)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Semantic search over the RAG knowledge base.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python search.py \"pandas groupby\"\n"
            "  python search.py \"attention mechanism\" --k 3\n"
            "  python search.py \"docker compose\" --json\n"
        ),
    )
    parser.add_argument("query", help="Natural language search query")
    parser.add_argument("--k", type=int, default=5, metavar="INT", help="Number of results (default: 5)")
    parser.add_argument(
        "--collection",
        default="default",
        metavar="STR",
        help="ChromaDB collection to search (default: 'default')",  # PRDv2: expose multi-collection routing
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="Output raw JSON array")

    args = parser.parse_args()

    results = asyncio.run(_run_search(args.query, args.k, args.collection))

    if args.as_json:
        print(json.dumps([r.model_dump() for r in results], indent=2))
    else:
        print(_format_results(results, args.query))


if __name__ == "__main__":
    main()

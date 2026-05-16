"""
ingest.py — Load HTML pages into the AskVio wiki memory.

Flow:
  1. Parse each HTML file → clean text
  2. Store raw text in Redis (session memory) — fast scratch layer
  3. Use the 'extract' skill to distil structured wiki entries
  4. Store each wiki entry in Cognee's permanent knowledge graph
"""

import asyncio
import json
import os
from pathlib import Path

import cognee
from bs4 import BeautifulSoup
from cognee.modules.engine.operations.setup import setup

DATASET = "askvio-wiki"
SESSION = "ingest-session"
SKILLS_DIR = Path(__file__).parent.parent / "skills"
DATA_DIR = Path(__file__).parent.parent / "data" / "sample_pages"


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


async def ingest_page(html_path: Path) -> list[dict]:
    raw_html = html_path.read_text(encoding="utf-8")
    clean_text = html_to_text(raw_html)
    page_name = html_path.stem

    print(f"  [+] {page_name}: {len(clean_text)} chars")

    # Step 1 — raw text goes to Redis session memory (hot scratchpad)
    await cognee.remember(
        f"PAGE:{page_name}\n\n{clean_text}",
        dataset_name=DATASET,
        session_id=SESSION,
    )

    # Step 2 — use the extract skill to distil into structured wiki entries
    extraction_prompt = (
        f"Extract wiki entries from this AskVio documentation page.\n\n{clean_text}"
    )
    raw_answer = await cognee.search(
        extraction_prompt,
        query_type="AGENTIC_COMPLETION",
        datasets=DATASET,
        skills=["extract"],
        max_iter=4,
        session_id=SESSION,
    )

    # Parse the JSON array returned by the skill
    try:
        answer_text = raw_answer if isinstance(raw_answer, str) else str(raw_answer)
        # Find the JSON block inside the response
        start = answer_text.index("[")
        end = answer_text.rindex("]") + 1
        entries = json.loads(answer_text[start:end])
    except (ValueError, json.JSONDecodeError):
        print(f"  [!] Could not parse entries for {page_name}, storing as raw text")
        entries = [
            {
                "title": page_name.replace("-", " ").title(),
                "summary": clean_text[:300],
                "key_facts": [],
                "related_concepts": [],
                "source_section": page_name,
            }
        ]

    # Step 3 — each entry goes to the permanent knowledge graph
    for entry in entries:
        entry_text = (
            f"WIKI ENTRY: {entry['title']}\n"
            f"Summary: {entry['summary']}\n"
            f"Key facts:\n" + "\n".join(f"- {f}" for f in entry.get("key_facts", [])) +
            f"\nRelated: {', '.join(entry.get('related_concepts', []))}"
        )
        await cognee.remember(entry_text, dataset_name=DATASET)
        print(f"    -> stored: {entry['title']}")

    return entries


async def main():
    print("=== AskVio Wiki — Ingest ===\n")

    # Wipe previous run for a clean demo (remove these two lines to keep history)
    await cognee.prune.prune_data()
    await cognee.prune.prune_system(metadata=True)
    await setup()

    # Ingest skills into the graph so AGENTIC_COMPLETION can use them
    await cognee.remember(
        str(SKILLS_DIR),
        dataset_name=DATASET,
        content_type="skills",
    )

    html_files = sorted(DATA_DIR.glob("*.html"))
    if not html_files:
        print(f"No HTML files found in {DATA_DIR}")
        return

    all_entries = []
    for html_path in html_files:
        entries = await ingest_page(html_path)
        all_entries.extend(entries)

    print(f"\nDone. {len(all_entries)} wiki entries stored from {len(html_files)} pages.")
    print("Wiki is ready. Run `python query.py` to ask questions.")


if __name__ == "__main__":
    asyncio.run(main())

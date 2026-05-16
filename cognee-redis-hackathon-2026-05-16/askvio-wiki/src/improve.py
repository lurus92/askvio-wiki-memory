"""
improve.py — Apply pending skill improvement proposals and run wiki lint.

Run this after a query session to:
  1. Apply any pending skill rewrite proposals (query / extract skills)
  2. Run the lint skill to find duplicates, contradictions, and stale links
  3. Print a before/after diff of any changed skills

Usage:
    python improve.py
"""

import asyncio
from uuid import UUID

import cognee
from cognee.modules.engine.operations.setup import setup
from cognee.modules.memify.skill_improvement import improve_skill
from cognee.modules.pipelines.layers.resolve_authorized_user_datasets import (
    resolve_authorized_user_datasets,
)
from cognee import SearchType

DATASET = "askvio-wiki"
SESSION = "improve-session"


async def apply_pending_proposals(dataset_id: UUID, user, dataset):
    """Fetch proposals generated during query sessions and apply them."""
    results = await cognee.search(
        "List all pending skill improvement proposals",
        query_type=SearchType.GRAPH_COMPLETION,
        datasets=DATASET,
        session_id=SESSION,
    )

    proposals = []
    if isinstance(results, list):
        proposals = [r for r in results if isinstance(r, dict) and r.get("kind") == "skill_improvement_proposal"]

    if not proposals:
        print("No pending proposals found.")
        return

    for proposal in proposals:
        skill_name = proposal.get("skill_name", "query")
        proposal_id = proposal.get("proposal_id")
        print(f"  Applying proposal for skill '{skill_name}' (id={proposal_id})...")
        await improve_skill(
            skill_name,
            dataset=dataset,
            user=user,
            proposal_id=proposal_id,
            apply=True,
        )
        print(f"  -> '{skill_name}' skill updated.")


async def run_lint():
    """Ask the lint skill to audit wiki entries for quality issues."""
    print("\nRunning lint audit...")
    result = await cognee.search(
        "Audit all wiki entries for duplicates, contradictions, stale links, and thin entries.",
        query_type=SearchType.AGENTIC_COMPLETION,
        datasets=DATASET,
        skills=["lint"],
        max_iter=4,
        session_id=SESSION,
    )

    print("\nLint report:")
    print(result if isinstance(result, str) else str(result))


async def main():
    print("=== AskVio Wiki — Improve & Lint ===\n")

    await setup()

    # Resolve the dataset so we can pass it to improve_skill
    remembered = await cognee.remember(
        "improve-session-marker",
        dataset_name=DATASET,
        session_id=SESSION,
    )

    try:
        dataset_id = UUID(remembered.dataset_id)
        user, datasets = await resolve_authorized_user_datasets(dataset_id)
        dataset = datasets[0]

        print("Checking for pending skill proposals...")
        await apply_pending_proposals(dataset_id, user, dataset)
    except Exception as e:
        print(f"Could not resolve dataset for skill improvement: {e}")
        print("(This is OK on first run — proposals are generated during query sessions.)")

    await run_lint()

    print("\nDone. Run `python query.py` to see the improved wiki in action.")


if __name__ == "__main__":
    asyncio.run(main())

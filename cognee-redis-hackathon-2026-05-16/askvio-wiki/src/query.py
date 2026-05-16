"""
query.py — Ask questions against the AskVio wiki and record feedback.

Usage:
    python query.py                  # interactive loop
    python query.py "Your question"  # single question
"""

import asyncio
import sys
from uuid import uuid4

import cognee
from cognee import SearchType
from cognee.memory import SkillRunEntry

DATASET = "askvio-wiki"


async def ask(question: str, session_id: str) -> str:
    results = await cognee.search(
        question,
        query_type=SearchType.GRAPH_COMPLETION,
        datasets=DATASET,
        skills=["query"],
        max_iter=6,
        session_id=session_id,
    )
    return results if isinstance(results, str) else "\n".join(str(r) for r in results)


async def record_feedback(question: str, answer: str, score: float, session_id: str):
    feedback_value = 1.0 if score >= 0.7 else -1.0
    await cognee.remember(
        SkillRunEntry(
            selected_skill_id="query",
            task_text=question,
            result_summary=answer[:200],
            success_score=score,
            feedback=feedback_value,
        ),
        dataset_name=DATASET,
        session_id=session_id,
        skill_improvement={
            "skill_name": "query",
            "apply": False,
            "score_threshold": 0.8,
        },
    )


async def interactive_loop():
    session_id = f"query-session-{uuid4().hex[:8]}"
    print("=== AskVio Wiki — Query ===")
    print("Type your question and press Enter. Type 'quit' to exit.\n")

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not question or question.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        print("\nSearching wiki...")
        answer = await ask(question, session_id)
        print(f"\nWiki: {answer}\n")

        # Collect optional feedback
        try:
            raw = input("Rate this answer 1-5 (or press Enter to skip): ").strip()
            if raw:
                score = (int(raw) - 1) / 4  # normalise to 0.0-1.0
                await record_feedback(question, answer, score, session_id)
                print("Feedback recorded — wiki will improve over time.\n")
        except (ValueError, EOFError, KeyboardInterrupt):
            pass

        print("-" * 60)


async def single_question(question: str):
    session_id = f"query-session-{uuid4().hex[:8]}"
    print(f"Question: {question}\n")
    answer = await ask(question, session_id)
    print(f"Answer:\n{answer}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        asyncio.run(single_question(" ".join(sys.argv[1:])))
    else:
        asyncio.run(interactive_loop())

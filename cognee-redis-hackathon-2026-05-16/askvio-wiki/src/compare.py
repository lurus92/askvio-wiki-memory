"""
compare.py — Side-by-side comparison: Wiki (graph) vs. Vector (chunks) retrieval.

This is the key demo script. For each test question it runs two retrieval
strategies and asks an LLM judge to score both answers 1-5.

Usage:
    python compare.py               # run all 5 built-in questions
    python compare.py "My question" # run a single custom question
"""

import asyncio
import sys
from dataclasses import dataclass

import cognee
from cognee import SearchType
from openai import AsyncOpenAI

DATASET = "askvio-wiki"

TEST_QUESTIONS = [
    "What does a confidence score below 70 mean and what should I do?",
    "How do I connect a BigQuery data source and what permissions does it need?",
    "Can AskVio predict future revenue trends?",
    "What are the rate limits for the AskVio API on the free plan?",
    "How does a follow-up question work and how many turns does AskVio remember?",
]


@dataclass
class CompareResult:
    question: str
    wiki_answer: str
    vector_answer: str
    wiki_score: float
    vector_score: float
    judge_reasoning: str


async def wiki_answer(question: str) -> str:
    results = await cognee.search(
        question,
        query_type=SearchType.GRAPH_COMPLETION,
        datasets=DATASET,
        skills=["query"],
        max_iter=4,
    )
    return results if isinstance(results, str) else "\n".join(str(r) for r in results)


async def vector_answer(question: str) -> str:
    results = await cognee.search(
        question,
        query_type=SearchType.CHUNKS,
        datasets=DATASET,
    )
    if not results:
        return "(no results)"
    # CHUNKS returns raw text snippets — join them
    return "\n---\n".join(
        r.get("text", str(r)) if isinstance(r, dict) else str(r)
        for r in results[:3]
    )


async def judge(question: str, wiki: str, vector: str) -> tuple[float, float, str]:
    client = AsyncOpenAI()
    prompt = f"""You are an objective judge evaluating two retrieval systems answering the same question.

Question: {question}

System A (Wiki / Graph):
{wiki}

System B (Vector / Chunks):
{vector}

Score each system 1-5 on:
- Accuracy: Is the information correct and complete?
- Clarity: Is the answer well-structured and easy to understand?
- Relevance: Does it directly address what was asked?

Respond ONLY with this JSON:
{{
  "system_a_score": <1-5>,
  "system_b_score": <1-5>,
  "reasoning": "<one sentence explaining the key difference>"
}}"""

    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    import json
    data = json.loads(resp.choices[0].message.content)
    return (
        data["system_a_score"] / 5.0,
        data["system_b_score"] / 5.0,
        data["reasoning"],
    )


async def run_comparison(question: str) -> CompareResult:
    wiki, vec = await asyncio.gather(wiki_answer(question), vector_answer(question))
    wiki_score, vec_score, reasoning = await judge(question, wiki, vec)
    return CompareResult(
        question=question,
        wiki_answer=wiki,
        vector_answer=vec,
        wiki_score=wiki_score,
        vector_score=vec_score,
        judge_reasoning=reasoning,
    )


def print_result(r: CompareResult, index: int):
    bar = lambda s: "█" * round(s * 10) + "░" * (10 - round(s * 10))
    print(f"\n{'='*70}")
    print(f"Q{index}: {r.question}")
    print(f"{'='*70}")
    print(f"\n[WIKI / GRAPH]  score: {r.wiki_score:.1f}  {bar(r.wiki_score)}")
    print(r.wiki_answer[:500] + ("..." if len(r.wiki_answer) > 500 else ""))
    print(f"\n[VECTOR / CHUNKS] score: {r.vector_score:.1f}  {bar(r.vector_score)}")
    print(r.vector_answer[:500] + ("..." if len(r.vector_answer) > 500 else ""))
    print(f"\nJudge: {r.judge_reasoning}")


def print_summary(results: list[CompareResult]):
    avg_wiki = sum(r.wiki_score for r in results) / len(results)
    avg_vec = sum(r.vector_score for r in results) / len(results)
    wiki_wins = sum(1 for r in results if r.wiki_score > r.vector_score)
    vec_wins = sum(1 for r in results if r.vector_score > r.wiki_score)
    ties = len(results) - wiki_wins - vec_wins

    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"{'Approach':<20} {'Avg score':>10} {'Wins':>6}")
    print(f"{'-'*40}")
    print(f"{'Wiki (graph)':<20} {avg_wiki:>10.2f} {wiki_wins:>6}")
    print(f"{'Vector (chunks)':<20} {avg_vec:>10.2f} {vec_wins:>6}")
    print(f"{'Ties':<20} {'':>10} {ties:>6}")
    print()
    winner = "Wiki" if avg_wiki > avg_vec else "Vector" if avg_vec > avg_wiki else "Tie"
    print(f"Overall winner: {winner}")


async def main():
    questions = sys.argv[1:] if len(sys.argv) > 1 else TEST_QUESTIONS
    print(f"Running comparison on {len(questions)} question(s)...\n")

    results = []
    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q[:60]}...")
        result = await run_comparison(q)
        print_result(result, i)
        results.append(result)

    if len(results) > 1:
        print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())

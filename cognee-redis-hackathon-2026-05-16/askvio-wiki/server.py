"""
server.py — AskVio Wiki Memory  (Cognee + Redis edition)

Memory architecture
───────────────────
                     [ HTML pages ]
                           │
                           ▼
          ┌────────────────────────────────┐
          │  Redis — session memory        │   raw pages, fast scratchpad
          │  cognee.remember(...,          │   (per-ingest session)
          │    session_id="askvio-ingest") │
          └───────────────┬────────────────┘
                          │  distillation
                          ▼
          ┌────────────────────────────────┐
          │  Cognee — permanent graph      │   wiki entries, skills, run history
          │  cognee.remember(entry_text)   │
          └──────────┬─────────────────────┘
                     │
          ┌──────────┴──────────┐
          │                     │
    GRAPH_COMPLETION         CHUNKS
    (wiki approach)     (vector approach)
          │                     │
          └──────────┬──────────┘
                     │
              GPT synthesis
                     │
              LLM judge scores

Run:
    uvicorn server:app --reload --port 8000
"""

import asyncio
import json
import os
from pathlib import Path
from typing import AsyncGenerator

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

load_dotenv()

# ── Cognee config ─────────────────────────────────────────────────────────────
# Cognee reads LLM_API_KEY (not OPENAI_API_KEY) — mirror the value.
_oai_key = os.environ.get("OPENAI_API_KEY", "")
if _oai_key and not os.environ.get("LLM_API_KEY"):
    os.environ["LLM_API_KEY"] = _oai_key
if not os.environ.get("LLM_PROVIDER"):
    os.environ["LLM_PROVIDER"] = "openai"
if not os.environ.get("LLM_MODEL"):
    os.environ["LLM_MODEL"] = "gpt-4o-mini"

import cognee  # noqa: E402  (import after env vars are set)
from cognee import SearchType  # noqa: E402

# ── Constants ─────────────────────────────────────────────────────────────────
DATASET    = "askvio-wiki"
SKILLS_DIR = str(Path(__file__).parent / "skills")
SESSION    = "askvio-ingest"
FRONTEND   = Path(__file__).parent / "frontend" / "index.html"
SAMPLES    = Path(__file__).parent / "data" / "sample_pages"

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="AskVio Wiki Memory")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

client = AsyncOpenAI(api_key=_oai_key)

# ── In-memory state ───────────────────────────────────────────────────────────
class State:
    pages: dict[str, str] = {}
    wiki_entries: list[dict] = []
    built: bool = False
    pending_proposals: list[dict] = []
    last_query: str = ""
    last_wiki_answer: str = ""

state = State()


# ── Utilities ─────────────────────────────────────────────────────────────────

def parse_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "head", "footer", "noscript", "svg"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _to_str(r) -> str:
    if isinstance(r, str):
        return r
    if isinstance(r, dict):
        return r.get("text", r.get("content", r.get("answer", str(r))))
    return str(r)


def normalize_results(results) -> tuple[str, list[dict]]:
    """Turn any Cognee search result into (context_text, sources_list)."""
    if results is None:
        return "(no results)", []
    if isinstance(results, str):
        return results, [{"text": results[:150]}]
    if isinstance(results, list):
        texts   = [_to_str(r) for r in results[:5]]
        sources = [{"text": _to_str(r)[:150], "source": r.get("source", "") if isinstance(r, dict) else ""} for r in results[:5]]
        return "\n\n".join(texts), sources
    return str(results), []


async def cognee_setup():
    try:
        from cognee.modules.engine.operations.setup import setup
        await setup()
    except Exception as e:
        print(f"[cognee] setup warning: {e}")


# ── Wiki extraction ───────────────────────────────────────────────────────────

EXTRACT_SYSTEM = """\
You are a knowledge extraction specialist for an ecommerce website.
Extract structured wiki entries from the page text.

Return a JSON object {"entries": [...]} where each entry has:
  title      – short concept name (e.g. "Return Policy", "Product: Wireless Earbuds")
  summary    – 1-2 sentences a support bot could quote directly to a customer
  key_facts  – array of 3-6 specific, concrete facts (prices, timelines, SKUs, rules)
  category   – one of: product | policy | faq | brand | feature | navigation

Focus on details that directly answer customer questions: prices, availability,
policies, shipping timelines, payment options, warranties.\
"""


async def extract_entries(text: str) -> list[dict]:
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": text[:6000]},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    data = json.loads(resp.choices[0].message.content)
    return data.get("entries", []) if isinstance(data, dict) else []


# ── GPT synthesis + judge ─────────────────────────────────────────────────────

async def gpt_answer(query: str, context: str, mode: str) -> str:
    if mode == "wiki":
        system = (
            "You are a helpful ecommerce support assistant. "
            "Answer using only the wiki entries provided. "
            "Be concise, specific, and cite entry names in brackets."
        )
        ctx_label = "Wiki entries from the knowledge graph"
    else:
        system = (
            "You are a helpful ecommerce support assistant. "
            "Answer using only the text passages provided."
        )
        ctx_label = "Text passages from vector search"

    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"{ctx_label}:\n{context}\n\nCustomer question: {query}"},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content


async def gpt_judge(query: str, wiki: str, vec: str) -> dict:
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": (
                f'Rate two AI answers to the customer question: "{query}"\n\n'
                f"Answer A (Wiki / Knowledge Graph): {wiki}\n\n"
                f"Answer B (Vector / Raw Chunks): {vec}\n\n"
                "Rate each 1–5 on accuracy, completeness, and clarity. "
                'Return ONLY JSON: {"a": {"accuracy": N, "completeness": N, "clarity": N}, '
                '"b": {"accuracy": N, "completeness": N, "clarity": N}, '
                '"verdict": "one sentence explaining which is better and why"}'
            ),
        }],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(resp.choices[0].message.content)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    await cognee_setup()


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(FRONTEND.read_text(encoding="utf-8"))


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    results = []
    for file in files:
        raw  = await file.read()
        text = parse_html(raw.decode("utf-8", errors="replace"))
        state.pages[file.filename] = text
        results.append({"filename": file.filename, "chars": len(text)})
    state.built = False
    return {"files": results, "total": len(state.pages)}


@app.post("/api/use-samples")
async def use_samples():
    state.pages.clear()
    results = []
    for p in sorted(SAMPLES.glob("*.html")):
        text = parse_html(p.read_text(encoding="utf-8"))
        state.pages[p.name] = text
        results.append({"filename": p.name, "chars": len(text)})
    state.built = False
    return {"files": results, "total": len(state.pages)}


@app.post("/api/build")
async def build():
    if not state.pages:
        raise HTTPException(400, "Upload pages first.")

    async def stream() -> AsyncGenerator[str, None]:
        def sse(d: dict) -> str:
            return f"data: {json.dumps(d)}\n\n"

        # ── Reset Cognee for a clean build ─────────────────────────────────
        yield sse({"type": "log", "message": "Resetting knowledge base…"})
        try:
            await cognee.prune.prune_data()
            await cognee.prune.prune_system(metadata=True)
            await cognee_setup()
        except Exception as e:
            yield sse({"type": "log", "message": f"Reset note: {e}"})

        state.wiki_entries.clear()
        state.pending_proposals.clear()
        pages = list(state.pages.items())

        # ── Ingest skills into the graph ────────────────────────────────────
        yield sse({"type": "log", "message": "Loading skills into knowledge graph…"})
        try:
            await cognee.remember(
                SKILLS_DIR,
                dataset_name=DATASET,
                content_type="skills",
            )
            yield sse({"type": "log", "message": "✓ Skills ingested (extract, query, lint)"})
        except Exception as e:
            yield sse({"type": "log", "message": f"Skills note: {e}"})

        # ── Phase 1: Wiki extraction → Cognee permanent graph ───────────────
        yield sse({"type": "phase", "phase": "wiki"})
        all_entries: list[dict] = []

        for i, (fname, text) in enumerate(pages):
            yield sse({
                "type": "progress", "phase": "wiki",
                "step": i + 1, "total": len(pages), "file": fname,
            })

            # Raw page → Redis session memory (fast scratchpad)
            try:
                await cognee.remember(
                    f"PAGE:{fname}\n\n{text[:4000]}",
                    dataset_name=DATASET,
                    session_id=SESSION,
                )
            except Exception as e:
                yield sse({"type": "log", "message": f"Redis note ({fname}): {e}"})

            # GPT extracts structured wiki entries
            entries = await extract_entries(text)

            # Each wiki entry → permanent Cognee knowledge graph
            for entry in entries:
                entry["source"] = fname
                all_entries.append(entry)
                entry_text = (
                    f"WIKI ENTRY: {entry['title']}\n"
                    f"Summary: {entry['summary']}\n"
                    f"Key facts: {'; '.join(entry.get('key_facts', []))}\n"
                    f"Category: {entry.get('category', '')}"
                )
                try:
                    await cognee.remember(entry_text, dataset_name=DATASET)
                except Exception as e:
                    yield sse({"type": "log", "message": f"Graph write note: {e}"})

                yield sse({"type": "wiki_entry", "entry": entry})
                await asyncio.sleep(0.03)

        state.wiki_entries = all_entries
        yield sse({"type": "phase_done", "phase": "wiki", "count": len(all_entries)})

        # ── Phase 2: Raw text → Cognee (for CHUNKS search baseline) ────────
        # Cognee stores text as chunks AND builds a graph — CHUNKS search uses
        # the raw chunked text, giving us the traditional RAG baseline.
        yield sse({"type": "phase", "phase": "vector"})
        chunk_total = 0

        for i, (fname, text) in enumerate(pages):
            yield sse({
                "type": "progress", "phase": "vector",
                "step": i + 1, "total": len(pages), "file": fname,
            })
            try:
                await cognee.remember(text[:8000], dataset_name=DATASET)
                chunk_total += max(1, len(text.split()) // 350)
            except Exception as e:
                yield sse({"type": "log", "message": f"Vector ingest note: {e}"})

        yield sse({"type": "phase_done", "phase": "vector", "count": chunk_total})
        state.built = True
        yield sse({"type": "done"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class SearchReq(BaseModel):
    query: str


@app.post("/api/search")
async def search(req: SearchReq):
    if not state.built:
        raise HTTPException(400, "Build the knowledge base first.")

    state.last_query = req.query

    # ── Wiki: Cognee GRAPH_COMPLETION ─────────────────────────────────────
    # Uses the structured knowledge graph built from wiki entries.
    try:
        wiki_raw = await cognee.search(
            req.query,
            query_type=SearchType.GRAPH_COMPLETION,
            datasets=DATASET,
            skills=["query"],          # applies our query/SKILL.md
        )
        wiki_ctx, _ = normalize_results(wiki_raw)
    except Exception as e:
        wiki_ctx = f"(graph search unavailable: {e})"

    wiki_answer = await gpt_answer(req.query, wiki_ctx, "wiki")
    state.last_wiki_answer = wiki_answer

    # Surface the most relevant extracted wiki entries as sources
    from difflib import SequenceMatcher
    def _rel(e):
        return SequenceMatcher(
            None, req.query.lower(),
            (e["title"] + " " + e["summary"]).lower()
        ).ratio()
    wiki_sources = [
        {"title": e["title"], "category": e.get("category", ""), "summary": e["summary"]}
        for e in sorted(state.wiki_entries, key=_rel, reverse=True)[:3]
    ]

    # ── Vector: Cognee CHUNKS ──────────────────────────────────────────────
    # Uses raw text chunks — the traditional RAG baseline.
    try:
        vec_raw = await cognee.search(
            req.query,
            query_type=SearchType.CHUNKS,
            datasets=DATASET,
        )
        vec_ctx, vec_sources_raw = normalize_results(vec_raw)
    except Exception as e:
        vec_ctx = f"(chunks search unavailable: {e})"
        vec_sources_raw = []

    vec_answer = await gpt_answer(req.query, vec_ctx, "vector")

    # ── LLM judge ─────────────────────────────────────────────────────────
    scores = await gpt_judge(req.query, wiki_answer, vec_answer)
    def avg(s): return round((s["accuracy"] + s["completeness"] + s["clarity"]) / 3, 1)

    return {
        "wiki": {
            "answer":  wiki_answer,
            "sources": wiki_sources,
            "scores":  scores["a"],
            "avg":     avg(scores["a"]),
        },
        "vector": {
            "answer":  vec_answer,
            "sources": [
                {"text": s.get("text", "")[:120] + "…", "source": s.get("source", "")}
                for s in vec_sources_raw
            ],
            "scores":  scores["b"],
            "avg":     avg(scores["b"]),
        },
        "verdict": scores["verdict"],
    }


# ── Feedback → SkillRunEntry self-improvement loop ────────────────────────────

class FeedbackReq(BaseModel):
    query:  str
    answer: str
    score:  int   # 1-5


@app.post("/api/feedback")
async def feedback(req: FeedbackReq):
    """Record a user rating → Cognee proposes a skill rewrite if score < threshold."""
    normalised   = (req.score - 1) / 4          # map 1-5 → 0.0-1.0
    feedback_val = 1.0 if normalised >= 0.7 else -1.0

    try:
        from cognee.memory import SkillRunEntry

        result = await cognee.remember(
            SkillRunEntry(
                selected_skill_id="query",
                task_text=req.query,
                result_summary=req.answer[:200],
                success_score=normalised,
                feedback=feedback_val,
            ),
            dataset_name=DATASET,
            session_id=SESSION,
            skill_improvement={
                "skill_name":      "query",
                "apply":           False,     # propose only; apply explicitly
                "score_threshold": 0.8,       # propose rewrite when score < 0.8
            },
        )
        # Collect any proposals returned
        if hasattr(result, "items"):
            for item in result.items:
                if isinstance(item, dict) and item.get("kind") == "skill_improvement_proposal":
                    state.pending_proposals.append(item)
    except Exception as e:
        return {"ok": False, "error": str(e), "pending": len(state.pending_proposals)}

    return {
        "ok":      True,
        "score":   req.score,
        "pending": len(state.pending_proposals),
    }


@app.post("/api/improve")
async def improve():
    """Apply all pending skill improvement proposals."""
    if not state.pending_proposals:
        return {"ok": True, "message": "No pending proposals.", "applied": 0}

    applied = 0
    try:
        from cognee.modules.memify.skill_improvement import improve_skill
        from cognee.modules.pipelines.layers.resolve_authorized_user_datasets import (
            resolve_authorized_user_datasets,
        )
        from uuid import UUID

        remembered = await cognee.remember(
            "improve-marker", dataset_name=DATASET, session_id=SESSION
        )
        dataset_id = UUID(remembered.dataset_id)
        user, datasets = await resolve_authorized_user_datasets(dataset_id)
        dataset = datasets[0]

        for proposal in state.pending_proposals:
            await improve_skill(
                proposal.get("skill_name", "query"),
                dataset=dataset,
                user=user,
                proposal_id=proposal.get("proposal_id"),
                apply=True,
            )
            applied += 1

        state.pending_proposals.clear()
    except Exception as e:
        return {"ok": False, "error": str(e), "applied": applied}

    return {"ok": True, "applied": applied, "message": f"Applied {applied} improvement(s)."}


@app.get("/api/status")
async def status():
    return {
        "built":    state.built,
        "pages":    len(state.pages),
        "entries":  len(state.wiki_entries),
        "pending":  len(state.pending_proposals),
    }

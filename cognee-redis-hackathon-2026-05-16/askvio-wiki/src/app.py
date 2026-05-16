"""
app.py — Streamlit demo UI for the AskVio wiki memory project.

Tabs:
  1. Ingest   — upload HTMLs, trigger ingest pipeline
  2. Query    — ask questions, rate answers, watch the wiki grow
  3. Compare  — wiki vs. vector side-by-side on any question
  4. Improve  — run lint + apply pending skill proposals

Run with:
    streamlit run src/app.py
"""

import asyncio
import json
import sys
from pathlib import Path

import streamlit as st

# Make sure src/ imports resolve
sys.path.insert(0, str(Path(__file__).parent))

import cognee
from cognee import SearchType
from cognee.memory import SkillRunEntry

DATASET = "askvio-wiki"
SKILLS_DIR = Path(__file__).parent.parent / "skills"
DATA_DIR = Path(__file__).parent.parent / "data" / "sample_pages"


def run(coro):
    """Run an async coroutine from a sync Streamlit context."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AskVio Wiki Memory",
    page_icon="🧠",
    layout="wide",
)

st.title("🧠 AskVio Wiki Memory")
st.caption("Cognee × Redis Hackathon 2026 — LLM-powered knowledge wiki that gets smarter with use")

tab_ingest, tab_query, tab_compare, tab_improve = st.tabs(
    ["📥 Ingest", "💬 Query", "⚖️ Compare", "🔧 Improve & Lint"]
)


# ── Tab 1: Ingest ─────────────────────────────────────────────────────────────
with tab_ingest:
    st.header("Ingest HTML Pages into the Wiki")
    st.write(
        "Upload your HTML documentation pages. AskVio will extract structured wiki "
        "entries and store them in the knowledge graph. Raw pages land in Redis first "
        "(session memory), then distilled entries are promoted to the permanent graph."
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        uploaded = st.file_uploader(
            "Upload HTML files", type=["html", "htm"], accept_multiple_files=True
        )
        use_samples = st.checkbox("Use built-in sample pages (3 AskVio help articles)", value=True)

    with col2:
        st.info(
            "**What happens during ingest:**\n"
            "1. Raw HTML → Redis session memory\n"
            "2. Extract skill → structured wiki entries\n"
            "3. Entries → Cognee knowledge graph\n"
        )

    if st.button("🚀 Run Ingest", type="primary"):
        html_files = []

        if use_samples:
            html_files.extend(DATA_DIR.glob("*.html"))

        if uploaded:
            import tempfile, os
            tmp = tempfile.mkdtemp()
            for f in uploaded:
                p = Path(tmp) / f.name
                p.write_bytes(f.read())
                html_files.append(p)

        if not html_files:
            st.warning("No HTML files to process.")
        else:
            from ingest import ingest_page, SESSION

            progress = st.progress(0, text="Starting ingest...")
            log = st.empty()
            all_entries = []
            logs = []

            async def run_ingest():
                from cognee.modules.engine.operations.setup import setup
                await cognee.prune.prune_data()
                await cognee.prune.prune_system(metadata=True)
                await setup()
                await cognee.remember(
                    str(SKILLS_DIR), dataset_name=DATASET, content_type="skills"
                )
                for i, path in enumerate(html_files):
                    logs.append(f"Processing: {path.name}")
                    log.code("\n".join(logs))
                    entries = await ingest_page(path)
                    all_entries.extend(entries)
                    progress.progress((i + 1) / len(html_files), text=f"{path.name} done")
                    for e in entries:
                        logs.append(f"  ✓ {e['title']}")
                    log.code("\n".join(logs))

            run(run_ingest())
            st.success(
                f"Ingested {len(html_files)} page(s) → {len(all_entries)} wiki entries stored."
            )
            st.session_state["ingested"] = True


# ── Tab 2: Query ──────────────────────────────────────────────────────────────
with tab_query:
    st.header("Ask the Wiki")

    if "history" not in st.session_state:
        st.session_state.history = []

    question = st.text_input("Your question", placeholder="What does a confidence score below 70 mean?")
    session_id = st.session_state.get("query_session", f"ui-session-{id(st)}")
    st.session_state["query_session"] = session_id

    if st.button("Ask", type="primary") and question:
        with st.spinner("Searching wiki..."):
            answer = run(
                cognee.search(
                    question,
                    query_type=SearchType.GRAPH_COMPLETION,
                    datasets=DATASET,
                    skills=["query"],
                    max_iter=6,
                    session_id=session_id,
                )
            )
            answer_text = answer if isinstance(answer, str) else "\n".join(str(r) for r in answer)
        st.session_state.history.append({"q": question, "a": answer_text, "score": None})

    for i, item in enumerate(reversed(st.session_state.history)):
        with st.expander(f"Q: {item['q']}", expanded=(i == 0)):
            st.markdown(item["a"])
            score = st.slider(
                "Rate this answer (1=bad, 5=great)",
                1, 5, 3,
                key=f"score_{i}",
            )
            if st.button("Submit feedback", key=f"fb_{i}"):
                normalised = (score - 1) / 4
                run(
                    cognee.remember(
                        SkillRunEntry(
                            selected_skill_id="query",
                            task_text=item["q"],
                            result_summary=item["a"][:200],
                            success_score=normalised,
                            feedback=1.0 if normalised >= 0.7 else -1.0,
                        ),
                        dataset_name=DATASET,
                        session_id=session_id,
                        skill_improvement={
                            "skill_name": "query",
                            "apply": False,
                            "score_threshold": 0.8,
                        },
                    )
                )
                st.success("Feedback recorded. Run Improve & Lint to apply it.")


# ── Tab 3: Compare ────────────────────────────────────────────────────────────
with tab_compare:
    st.header("Wiki vs. Vector — Side-by-Side Comparison")
    st.write(
        "Same question, two retrieval strategies. "
        "**Wiki (graph)** uses the structured knowledge graph built during ingest. "
        "**Vector (chunks)** does raw similarity search on text chunks — the traditional RAG approach."
    )

    SAMPLE_QUESTIONS = [
        "What does a confidence score below 70 mean and what should I do?",
        "How do I connect BigQuery and what permissions does it need?",
        "Can AskVio predict future revenue trends?",
        "What are the API rate limits on the free plan?",
        "How many follow-up turns does AskVio remember in a session?",
    ]

    preset = st.selectbox("Pick a sample question or type your own", ["(custom)"] + SAMPLE_QUESTIONS)
    custom_q = st.text_input("Custom question", disabled=(preset != "(custom)"))
    compare_q = custom_q if preset == "(custom)" else preset

    if st.button("⚖️ Run Comparison", type="primary") and compare_q:
        col_wiki, col_vec = st.columns(2)

        with st.spinner("Running both retrieval strategies..."):
            wiki_res, vec_res = run(
                asyncio.gather(
                    cognee.search(
                        compare_q,
                        query_type=SearchType.GRAPH_COMPLETION,
                        datasets=DATASET,
                        skills=["query"],
                        max_iter=4,
                    ),
                    cognee.search(
                        compare_q,
                        query_type=SearchType.CHUNKS,
                        datasets=DATASET,
                    ),
                )
            )

        wiki_text = wiki_res if isinstance(wiki_res, str) else "\n".join(str(r) for r in wiki_res)
        if isinstance(vec_res, list):
            vec_text = "\n---\n".join(
                r.get("text", str(r)) if isinstance(r, dict) else str(r)
                for r in vec_res[:3]
            )
        else:
            vec_text = str(vec_res)

        with col_wiki:
            st.subheader("🧠 Wiki (graph)")
            st.markdown(wiki_text)

        with col_vec:
            st.subheader("📦 Vector (chunks)")
            st.markdown(vec_text)

        # LLM judge
        with st.spinner("Asking LLM judge to score both..."):
            from openai import AsyncOpenAI

            async def judge():
                client = AsyncOpenAI()
                prompt = f"""Score these two answers to the question: "{compare_q}"

System A (Wiki/Graph): {wiki_text[:600]}
System B (Vector/Chunks): {vec_text[:600]}

Return JSON: {{"a_score": 1-5, "b_score": 1-5, "reasoning": "one sentence"}}"""
                resp = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    response_format={"type": "json_object"},
                )
                return json.loads(resp.choices[0].message.content)

            scores = run(judge())

        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Wiki score", f"{scores['a_score']}/5")
        c2.metric("Vector score", f"{scores['b_score']}/5")
        c3.write(f"**Judge:** {scores['reasoning']}")


# ── Tab 4: Improve & Lint ─────────────────────────────────────────────────────
with tab_improve:
    st.header("Improve & Lint")
    st.write(
        "Apply pending skill improvement proposals collected during query sessions, "
        "then run the lint audit to find duplicates, contradictions, and stale entries."
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🔧 Apply Skill Proposals"):
            with st.spinner("Applying proposals..."):
                result = run(
                    cognee.search(
                        "List and apply all pending skill improvement proposals",
                        query_type=SearchType.AGENTIC_COMPLETION,
                        datasets=DATASET,
                        skills=["query", "extract"],
                        max_iter=4,
                    )
                )
            st.success("Done.")
            st.text(result if isinstance(result, str) else str(result))

    with col2:
        if st.button("🧹 Run Lint Audit"):
            with st.spinner("Auditing wiki for quality issues..."):
                result = run(
                    cognee.search(
                        "Audit all wiki entries for duplicates, contradictions, stale links, and thin entries.",
                        query_type=SearchType.AGENTIC_COMPLETION,
                        datasets=DATASET,
                        skills=["lint"],
                        max_iter=4,
                    )
                )
            st.subheader("Lint Report")
            st.text(result if isinstance(result, str) else str(result))

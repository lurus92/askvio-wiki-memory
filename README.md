# Cognee Hackathons — AskVio Fork

This is Team AskVio's fork of the [Cognee hackathons repo](https://github.com/topoteretes/cognee-hackathons) for the **Cognee × Redis AI-Memory Hackathon (2026-05-16)**.

Our project — **AskVio Wiki Memory** — lives in [`cognee-redis-hackathon-2026-05-16/askvio-wiki/`](./cognee-redis-hackathon-2026-05-16/askvio-wiki/).

## What We Built

A living knowledge wiki for AskVio's product documentation. Instead of the standard RAG approach (embed chunks → retrieve top-k), we pre-digest HTML help-center pages into structured wiki entries using Cognee's memory engine, with Redis as the session-memory scratchpad.

The wiki improves itself: every low-scoring answer triggers a skill rewrite proposal via Cognee's `SkillRunEntry` loop. The lint step keeps the graph coherent.

**The "cherry on top":** `compare.py` runs the same questions against both the wiki (graph retrieval) and a raw vector baseline (chunk retrieval), scores both with an LLM judge, and prints a side-by-side benchmark.

## Hackathons

| Date | Hackathon | Partner | Folder |
|------|-----------|---------|--------|
| 2026-05-16 | AI-Memory Hackathon: Building your own Agent LLM Wiki | Redis | [`cognee-redis-hackathon-2026-05-16`](./cognee-redis-hackathon-2026-05-16) |

## Quick Start

```bash
cd cognee-redis-hackathon-2026-05-16/askvio-wiki
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.template .env          # add LLM_API_KEY
docker run -p 6379:6379 redis:latest
streamlit run src/app.py
```

See the [project README](./cognee-redis-hackathon-2026-05-16/askvio-wiki/README.md) for full details.

## Links

- [Cognee on GitHub](https://github.com/topoteretes/cognee)
- [Cognee Documentation](https://docs.cognee.ai/)
- [Karpathy on LLM Wikis](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [AskVio](https://askvio.com)

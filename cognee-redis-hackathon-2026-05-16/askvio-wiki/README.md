# AskVio Wiki Memory

**Cognee × Redis Hackathon 2026** — Wiki vs. Vector retrieval, live comparison.

Upload ecommerce HTML pages. The app builds two knowledge bases from the same content:
- **Wiki** — LLM reads pages and distils structured entries (title, summary, key facts). Retrieval uses semantic search over those structured entries.
- **Vector** — pages are split into raw text chunks and embedded. Retrieval uses cosine similarity over chunks.

Ask a question. Both systems answer. An LLM judge scores both on accuracy, completeness, and clarity. See who wins.

---

## Requirements

- Python 3.10 or later
- An OpenAI API key (provided at kickoff, or your own)
- Nothing else — no Docker, no Redis, no database

---

## Setup (step by step)

### 1 — Clone or enter the project folder

```bash
cd cognee-redis-hackathon-2026-05-16/askvio-wiki
```

### 2 — Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # on Windows: .venv\Scripts\activate
```

### 3 — Install dependencies

```bash
pip install -r requirements.txt
```

This installs: FastAPI, Uvicorn, OpenAI SDK, BeautifulSoup4, NumPy, python-dotenv.

### 4 — Set your OpenAI API key

Create a `.env` file in this folder:

```bash
cp .env.template .env
```

Open `.env` and replace the placeholder with your key:

```
OPENAI_API_KEY=sk-...your-key-here...
```

> The `.env` file is gitignored — your key will never be committed.

### 5 — Start the server

```bash
uvicorn server:app --reload --port 8000
```

You should see:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### 6 — Open the app

Go to **http://localhost:8000** in your browser.

---

## Using the app

### Step 1 — Load pages

Two options:

**Option A: Use the built-in sample pages**
Click "Use sample ecommerce pages". This loads 3 pages from `data/sample_pages/`:
- `store-home.html` — product catalogue, promotions, brand info
- `shipping-returns.html` — shipping options, return policy, refunds
- `faq.html` — ordering, sizing, payments, support

**Option B: Upload your own pages**
Download HTML pages from any ecommerce site (e.g. right-click → Save As in Chrome) and drag-and-drop them into the upload zone. The app strips navigation, scripts, and styles — only the readable content is used.

> To download from askvio.app/store: open the page in Chrome → Cmd+S (Mac) or Ctrl+S (Windows) → save as "Webpage, HTML only" → upload the `.html` file.

### Step 2 — Build the knowledge base

Click **"Build Knowledge Base"**. Watch the right panel:
- Wiki entries appear as cards in real time as the LLM extracts them
- The progress bars show extraction and embedding progress
- Build takes ~20–40 seconds for 3 pages (one OpenAI call per page + embedding)

### Step 3 — Ask questions

Type a customer question and press Enter (or click Ask). Try:

- *"What is your return policy?"*
- *"How long does shipping take?"*
- *"What payment methods do you accept?"*
- *"Do you ship internationally?"*
- *"Is there a warranty on products?"*

Both systems answer simultaneously. Scores and a verdict appear below.

---

## Project layout

```
askvio-wiki/
├── server.py               ← FastAPI backend (all logic in one file)
├── frontend/
│   └── index.html          ← Single-page UI (served by the backend)
├── data/
│   └── sample_pages/       ← 3 ecommerce HTML pages (UrbanWear demo store)
│       ├── store-home.html
│       ├── shipping-returns.html
│       └── faq.html
├── skills/                 ← Cognee skill definitions (for the full pipeline)
├── src/                    ← CLI scripts (ingest, query, compare, improve)
├── requirements.txt
├── .env.template
└── .env                    ← Your API key lives here (gitignored)
```

---

## How it works

### Wiki approach

```
HTML page
   │
   ▼  BeautifulSoup (strip scripts/nav/footer)
clean text
   │
   ▼  GPT-4o-mini (extract structured entries)
[{ title, summary, key_facts, category }, ...]
   │
   ▼  text-embedding-3-small
[embedding vectors]
   │
   ▼  cosine search on query embedding
top 3 entries
   │
   ▼  GPT-4o-mini (synthesise answer, cite entries)
answer
```

### Vector approach

```
HTML page
   │
   ▼  BeautifulSoup
clean text
   │
   ▼  chunk (350 words, 60-word overlap)
[chunk, chunk, chunk, ...]
   │
   ▼  text-embedding-3-small (batched)
[embedding vectors]
   │
   ▼  cosine search on query embedding
top 3 chunks
   │
   ▼  GPT-4o-mini (answer from raw passages)
answer
```

### Why wiki wins (usually)

The vector approach retrieves the most *similar* text — but that text is raw prose, sometimes cut mid-sentence, with context missing. The wiki approach retrieves *structured knowledge*: the LLM already understood the page and distilled the key facts. When the query is clear and the wiki has the right entry, the answer is cleaner and more specific.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'fastapi'`**
Make sure your virtual environment is active: `source .venv/bin/activate`

**`openai.AuthenticationError`**
Check that your `.env` file exists in the `askvio-wiki/` folder and that `OPENAI_API_KEY` is set correctly (no quotes needed around the key value).

**`uvicorn: command not found`**
Uvicorn is installed inside the venv. Make sure the venv is activated.

**Port 8000 already in use**
Use a different port: `uvicorn server:app --reload --port 8080` and open http://localhost:8080.

**Build takes a long time**
Each page makes one GPT call for extraction plus an embedding call. With 3 pages it's ~10 API calls total. Check your OpenAI account for rate limit issues if it stalls.

---

## Hackathon submission notes

- **Ingest**: HTML → BeautifulSoup → GPT extraction → numpy embedding store (in-memory)
- **Query + compare**: Both strategies run in parallel; GPT-4o-mini judges both answers
- **Self-improvement**: See `src/improve.py` and `skills/` for the Cognee SkillRunEntry loop
- **Redis / Cognee**: See `src/ingest.py` for the full two-tier memory pipeline using Cognee + Redis

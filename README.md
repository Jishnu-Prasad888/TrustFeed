# TrustFeed — Weighted RAG Pipeline with Profile Trust Scoring

A full-stack system that scrapes social/RSS profiles, embeds posts with trust + recency metadata,
and lets a local LLM answer questions with conflict resolution weighted by trust × recency.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  React Dashboard (Vite)                                         │
│  • Profile CRUD  • Trust slider  • Active/Passive toggle        │
│  • Scrape interval control  • RAG query interface               │
└───────────────────────┬─────────────────────────────────────────┘
                        │ REST API
┌───────────────────────▼─────────────────────────────────────────┐
│  FastAPI Backend                                                 │
│  /profiles  /settings  /scrape/trigger  /rag/query  /posts      │
└───┬───────────────────┬────────────────────────┬────────────────┘
    │                   │                        │
┌───▼───┐         ┌─────▼──────┐         ┌──────▼──────┐
│SQLite │         │  Scraper   │         │  RAG Engine  │
│(via   │         │  APScheduler│        │  ChromaDB    │
│SQLAlch│         │  + Playwright│       │  + Ollama    │
│emy)   │         │  /feedparser│        │  (local LLM) │
└───────┘         └─────┬──────┘         └─────────────┘
                        │ new posts
                  ┌─────▼──────┐
                  │  Embedder  │
                  │sentence-   │
                  │transformers│
                  │+ trust/time│
                  │ metadata   │
                  └────────────┘
```

## Stack
- **Frontend**: React 18 + Vite + Zustand + TanStack Query
- **Backend**: FastAPI + SQLAlchemy + APScheduler
- **Scraping**: Playwright (Twitter/X, generic web) + feedparser (RSS)
- **Embeddings**: sentence-transformers (all-MiniLM-L6-v2)
- **Vector DB**: ChromaDB (local, persistent)
- **LLM**: Ollama (llama3 / mistral — local)
- **Conflict resolution**: score = trust_weight × recency_decay

## Quick Start

### 1. Backend
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Install Ollama: https://ollama.ai
ollama pull llama3
uvicorn main:app --reload --port 8000
```

### 2. Frontend
```bash
cd frontend
npm install
npm run dev
```

### 3. Playwright browsers (for web scraping)
```bash
playwright install chromium
```

## Trust × Recency Conflict Resolution

When two chunks conflict, the LLM is instructed to prefer the source with
the highest combined score:

```
score(chunk) = trust_rating × recency_factor(post_timestamp)
recency_factor = exp(-λ × age_in_days)   # λ = 0.05 by default
```

The top-k chunks are re-ranked by this score before being injected into the prompt.

"""
rag/engine.py — Retrieval-Augmented Generation with trust × recency reranking.

Conflict resolution:
  score(chunk) = trust × exp(-λ × age_days)
  Higher score = more authoritative.

The LLM receives chunks sorted by score, and the system prompt instructs it to
prefer higher-scored sources when information conflicts.
"""
from __future__ import annotations
import logging
import math
from datetime import datetime, timezone
from typing import Any
import ollama

from scraper.embedder import get_chroma, get_model

logger = logging.getLogger(__name__)


# ── Scoring ───────────────────────────────────────────────────────────────────

def _recency_score(published_ts: float, lambda_: float = 0.05) -> float:
    """Exponential decay: score = exp(-λ × age_days). Recent → closer to 1."""
    if published_ts == 0:
        return 0.5  # unknown age → neutral
    now = datetime.now(timezone.utc).timestamp()
    age_days = max(0.0, (now - published_ts) / 86400)
    return math.exp(-lambda_ * age_days)


def _combined_score(trust: float, published_ts: float, lambda_: float) -> float:
    """Weighted geometric mean: sqrt(trust × recency)."""
    r = _recency_score(published_ts, lambda_)
    # Geometric mean keeps both factors equally influential
    return math.sqrt(trust * r)


# ── Retrieval ─────────────────────────────────────────────────────────────────

def retrieve(
    query: str,
    top_k: int = 8,
    lambda_: float = 0.05,
    active_profile_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """
    Embed the query, retrieve top_k × 3 candidates from ChromaDB,
    then rerank by combined trust × recency score and return top_k.
    """
    model = get_model()
    collection = get_chroma()

    q_emb = model.encode(query, normalize_embeddings=True).tolist()

    where_filter = None
    if active_profile_ids:
        if len(active_profile_ids) == 1:
            where_filter = {"profile_id": active_profile_ids[0]}
        else:
            where_filter = {"profile_id": {"$in": active_profile_ids}}

    results = collection.query(
        query_embeddings=[q_emb],
        n_results=min(top_k * 3, collection.count() or 1),
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        trust = float(meta.get("trust", 0.5))
        pub_ts = float(meta.get("published_ts", 0))
        score = _combined_score(trust, pub_ts, lambda_)
        chunks.append({
            "document":     doc,
            "profile_name": meta.get("profile_name", "Unknown"),
            "post_url":     meta.get("post_url", ""),
            "trust":        trust,
            "published_ts": pub_ts,
            "cosine_dist":  dist,
            "score":        score,
        })

    # Rerank: highest combined score first
    chunks.sort(key=lambda x: x["score"], reverse=True)
    return chunks[:top_k]


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(query: str, chunks: list[dict]) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt)."""
    system = (
        "You are a knowledgeable assistant with access to posts from trusted sources.\n"
        "Each source has a SCORE (0–1) that combines trust rating and recency.\n"
        "Rules:\n"
        "1. Prefer information from sources with HIGHER scores.\n"
        "2. If two sources conflict, choose the one with the higher score.\n"
        "   If scores are close (< 0.1 apart), synthesize or note the discrepancy.\n"
        "3. Always cite the source name when making a claim.\n"
        "4. Be concise and factual.\n"
    )

    context_lines = []
    for i, chunk in enumerate(chunks, 1):
        pub_date = ""
        if chunk["published_ts"]:
            dt = datetime.fromtimestamp(chunk["published_ts"], tz=timezone.utc)
            pub_date = dt.strftime("%Y-%m-%d")
        context_lines.append(
            f"[{i}] SOURCE: {chunk['profile_name']}  "
            f"SCORE: {chunk['score']:.3f}  "
            f"DATE: {pub_date or 'unknown'}\n"
            f"{chunk['document'][:600]}"
        )

    user = (
        "CONTEXT (sorted by relevance & trust × recency score):\n\n"
        + "\n\n---\n\n".join(context_lines)
        + f"\n\n---\n\nQUESTION: {query}\n\nANSWER:"
    )
    return system, user


# ── Generation ────────────────────────────────────────────────────────────────

def query_rag(
    query: str,
    model_name: str = "llama3",
    top_k: int = 8,
    lambda_: float = 0.05,
    active_profile_ids: list[int] | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    """
    Full RAG pipeline: retrieve → rerank → generate.
    Returns {answer, chunks_used, model}.
    """
    chunks = retrieve(query, top_k=top_k, lambda_=lambda_,
                      active_profile_ids=active_profile_ids)

    if not chunks:
        return {
            "answer": "No relevant posts found in the knowledge base yet. "
                      "Make sure profiles are active and have been scraped.",
            "chunks_used": [],
            "model": model_name,
        }

    system, user = _build_prompt(query, chunks)

    try:
        response = ollama.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            stream=False,
        )
        answer = response["message"]["content"]
    except Exception as e:
        logger.error(f"Ollama error: {e}")
        answer = f"LLM error: {e}. Is Ollama running? Run: ollama serve"

    return {
        "answer":      answer,
        "chunks_used": [
            {
                "profile_name": c["profile_name"],
                "score":        round(c["score"], 4),
                "trust":        round(c["trust"], 4),
                "published_ts": c["published_ts"],
                "post_url":     c["post_url"],
                "snippet":      c["document"][:200],
            }
            for c in chunks
        ],
        "model": model_name,
    }

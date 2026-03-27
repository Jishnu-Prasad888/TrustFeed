"""
scraper/embedder.py — Embeds posts into ChromaDB with trust + timestamp metadata.
Uses sentence-transformers locally (no API key needed).
"""
from __future__ import annotations

import logging
from datetime import datetime

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# ── Singleton model (loaded once) ────────────────────────────────────────────
_model: SentenceTransformer | None = None

def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading sentence-transformer model…")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


# ── ChromaDB client ───────────────────────────────────────────────────────────
_chroma_client: chromadb.PersistentClient | None = None
COLLECTION_NAME = "trustfeed_posts"

def get_chroma() -> chromadb.Collection:
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path="./chromadb_store",
            settings=Settings(anonymized_telemetry=False),
        )
    return _chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


# ── Public API ────────────────────────────────────────────────────────────────

def embed_post(
    post_id: int,
    content: str,
    profile_id: int,
    profile_name: str,
    trust: float,
    published_at: datetime | None,
    post_url: str = "",
) -> None:
    """
    Compute embedding and upsert into ChromaDB.
    Metadata stored:
      - trust          : float  (0–1) snapshot at embed time
      - profile_id     : int
      - profile_name   : str
      - published_ts   : float  (unix timestamp, 0 if unknown)
      - post_url       : str
    """
    model = get_model()
    collection = get_chroma()

    embedding = model.encode(content, normalize_embeddings=True).tolist()

    pub_ts = published_at.timestamp() if published_at else 0.0

    collection.upsert(
        ids=[str(post_id)],
        embeddings=[embedding],
        documents=[content],
        metadatas=[{
            "trust":        trust,
            "profile_id":   profile_id,
            "profile_name": profile_name,
            "published_ts": pub_ts,
            "post_url":     post_url,
        }],
    )
    logger.info(f"Embedded post {post_id} (trust={trust:.2f})")


def delete_profile_embeddings(profile_id: int) -> None:
    """Remove all embeddings for a deleted profile."""
    collection = get_chroma()
    results = collection.get(where={"profile_id": profile_id})
    if results["ids"]:
        collection.delete(ids=results["ids"])
        logger.info(f"Deleted {len(results['ids'])} embeddings for profile {profile_id}")


def collection_stats() -> dict:
    collection = get_chroma()
    return {"total_embeddings": collection.count()}

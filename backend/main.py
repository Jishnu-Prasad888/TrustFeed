"""
main.py — FastAPI application entry point
"""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.models import init_db, get_db, Profile, Post, AppSettings
from scraper.scraper import scrape_profile
from scraper.embedder import embed_post, delete_profile_embeddings, collection_stats
from rag.engine import query_rag

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
scheduler = AsyncIOScheduler()


def _scrape_settings(db) -> dict:
    """Pull scrape-relevant settings from DB into a plain dict."""
    rows = {r.key: r.value for r in db.query(AppSettings).all()}
    return {
        "limit":        int(rows.get("tweets_limit", "20")),
        "cookies_path": rows.get("twitter_cookies_path", ""),
    }


async def run_scrape_cycle():
    from db.models import SessionLocal
    db = SessionLocal()
    try:
        scrape_opts = _scrape_settings(db)
        profiles = db.query(Profile).filter(Profile.is_active == True).all()
        logger.info(f"Scrape cycle: {len(profiles)} active profiles")
        for profile in profiles:
            logger.info(f"  Scraping [{profile.platform}] {profile.url}")
            try:
                posts_data = await scrape_profile(
                    profile.platform, profile.url, **scrape_opts
                )
            except Exception as scrape_err:
                logger.error(f"  Scrape error for {profile.name}: {scrape_err}", exc_info=True)
                continue

            logger.info(f"  Fetched {len(posts_data)} items from {profile.name}")
            new_count = 0

            for pdata in posts_data:
                existing = db.query(Post).filter_by(content_hash=pdata["content_hash"]).first()
                if existing:
                    continue

                post = Post(
                    profile_id=profile.id,
                    content_hash=pdata["content_hash"],
                    raw_content=pdata["raw_content"],
                    url=pdata.get("url", ""),
                    published_at=pdata.get("published_at"),
                    trust_at_embed=profile.trust,
                )
                db.add(post)
                db.flush()
                logger.info(f"  Saved post id={post.id} ({len(post.raw_content)} chars)")

                try:
                    embed_post(
                        post_id=post.id,
                        content=post.raw_content,
                        profile_id=profile.id,
                        profile_name=profile.name,
                        trust=profile.trust,
                        published_at=post.published_at,
                        post_url=post.url or "",
                    )
                    post.embedded = True
                except Exception as emb_err:
                    logger.error(f"  Embed failed post {post.id}: {emb_err}", exc_info=True)

                new_count += 1

            db.commit()
            logger.info(f"  {profile.name}: {new_count} new posts saved")

    except Exception as e:
        logger.error(f"Scrape cycle top-level error: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


def _reschedule(interval_minutes: int):
    if scheduler.get_job("scrape"):
        scheduler.remove_job("scrape")
    scheduler.add_job(run_scrape_cycle, "interval", minutes=interval_minutes,
                      id="scrape", replace_existing=True)
    logger.info(f"Scrape interval set to {interval_minutes} minutes")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from db.models import SessionLocal
    db = SessionLocal()
    setting = db.get(AppSettings, "scrape_interval_minutes")
    interval = int(setting.value) if setting else 30
    db.close()
    scheduler.start()
    _reschedule(interval)
    yield
    scheduler.shutdown()


app = FastAPI(title="TrustFeed API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProfileCreate(BaseModel):
    name:      str
    url:       str
    platform:  str = "rss"
    trust:     float = Field(0.5, ge=0.0, le=1.0)
    is_active: bool = True

class ProfileUpdate(BaseModel):
    name:      str | None = None
    url:       str | None = None
    platform:  str | None = None
    trust:     float | None = Field(None, ge=0.0, le=1.0)
    is_active: bool | None = None

class SettingsUpdate(BaseModel):
    scrape_interval_minutes: int | None = Field(None, ge=1, le=1440)
    ollama_model:            str | None = None
    recency_decay_lambda:    float | None = Field(None, ge=0.001, le=1.0)
    max_rag_chunks:          int | None = Field(None, ge=1, le=30)
    tweets_limit:            int | None = Field(None, ge=1, le=200)
    twitter_cookies_path:    str | None = None

class RAGQuery(BaseModel):
    question:    str
    only_active: bool = True


# ── Profiles ──────────────────────────────────────────────────────────────────

@app.get("/profiles")
def list_profiles(db: Session = Depends(get_db)):
    return [p.to_dict() for p in db.query(Profile).order_by(Profile.id).all()]

@app.post("/profiles", status_code=201)
def create_profile(body: ProfileCreate, db: Session = Depends(get_db)):
    if db.query(Profile).filter_by(url=body.url).first():
        raise HTTPException(400, "Profile URL already exists")
    profile = Profile(**body.model_dump())
    db.add(profile); db.commit(); db.refresh(profile)
    return profile.to_dict()

@app.get("/profiles/{profile_id}")
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    p = db.get(Profile, profile_id)
    if not p: raise HTTPException(404, "Profile not found")
    return p.to_dict()

@app.patch("/profiles/{profile_id}")
def update_profile(profile_id: int, body: ProfileUpdate, db: Session = Depends(get_db)):
    p = db.get(Profile, profile_id)
    if not p: raise HTTPException(404, "Profile not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    p.updated_at = datetime.utcnow()
    db.commit(); db.refresh(p)
    return p.to_dict()

@app.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    p = db.get(Profile, profile_id)
    if not p: raise HTTPException(404, "Profile not found")
    delete_profile_embeddings(profile_id)
    db.delete(p); db.commit()


# ── Posts ─────────────────────────────────────────────────────────────────────

@app.get("/posts")
def list_posts(profile_id: int | None = None, limit: int = 50,
               db: Session = Depends(get_db)):
    q = db.query(Post).order_by(Post.scraped_at.desc())
    if profile_id:
        q = q.filter_by(profile_id=profile_id)
    return [p.to_dict() for p in q.limit(limit).all()]


# ── Scrape ────────────────────────────────────────────────────────────────────

@app.post("/scrape/trigger")
async def trigger_scrape(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_scrape_cycle)
    return {"status": "scrape started"}

@app.post("/scrape/profile/{profile_id}")
async def scrape_single(profile_id: int, db: Session = Depends(get_db)):
    profile = db.get(Profile, profile_id)
    if not profile: raise HTTPException(404, "Profile not found")

    scrape_opts = _scrape_settings(db)
    logger.info(f"Manual scrape: [{profile.platform}] {profile.url}")
    posts_data = await scrape_profile(profile.platform, profile.url, **scrape_opts)
    logger.info(f"Manual scrape fetched {len(posts_data)} items")

    new_count = 0
    for pdata in posts_data:
        if db.query(Post).filter_by(content_hash=pdata["content_hash"]).first():
            continue
        post = Post(
            profile_id=profile.id,
            content_hash=pdata["content_hash"],
            raw_content=pdata["raw_content"],
            url=pdata.get("url", ""),
            published_at=pdata.get("published_at"),
            trust_at_embed=profile.trust,
        )
        db.add(post); db.flush()
        logger.info(f"Saved post id={post.id} ({len(post.raw_content)} chars)")
        try:
            embed_post(post_id=post.id, content=post.raw_content,
                       profile_id=profile.id, profile_name=profile.name,
                       trust=profile.trust, published_at=post.published_at,
                       post_url=post.url or "")
            post.embedded = True
        except Exception as emb_err:
            logger.error(f"Embed failed: {emb_err}", exc_info=True)
        new_count += 1

    db.commit()
    return {"new_posts": new_count, "total_fetched": len(posts_data)}


# ── Debug: test scrape without saving ─────────────────────────────────────────

@app.post("/debug/scrape-test")
async def debug_scrape_test(
    platform: str,
    url: str,
    limit: int = 20,
    cookies_path: str = "",
):
    """Hit this from /docs to check if a URL actually returns data."""
    posts = await scrape_profile(platform, url, limit=limit, cookies_path=cookies_path)
    return {
        "count": len(posts),
        "items": [{"chars": len(p["raw_content"]), "preview": p["raw_content"][:300],
                   "url": p.get("url"), "published_at": str(p.get("published_at"))}
                  for p in posts],
    }


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    return {r.key: r.value for r in db.query(AppSettings).all()}

@app.patch("/settings")
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    updates = body.model_dump(exclude_none=True)
    for k, v in updates.items():
        s = db.get(AppSettings, k)
        if s: s.value = str(v)
        else: db.add(AppSettings(key=k, value=str(v)))
    db.commit()
    if "scrape_interval_minutes" in updates:
        _reschedule(int(updates["scrape_interval_minutes"]))
    return {r.key: r.value for r in db.query(AppSettings).all()}


# ── RAG ───────────────────────────────────────────────────────────────────────

@app.post("/rag/query")
def rag_query(body: RAGQuery, db: Session = Depends(get_db)):
    settings    = {r.key: r.value for r in db.query(AppSettings).all()}
    model_name  = settings.get("ollama_model", "llama3")
    top_k       = int(settings.get("max_rag_chunks", "8"))
    lambda_     = float(settings.get("recency_decay_lambda", "0.05"))
    active_ids  = None
    if body.only_active:
        active_ids = [p.id for p in db.query(Profile).filter_by(is_active=True).all()]
    return query_rag(query=body.question, model_name=model_name,
                     top_k=top_k, lambda_=lambda_, active_profile_ids=active_ids)


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/stats")
def stats(db: Session = Depends(get_db)):
    job = scheduler.get_job("scrape")
    return {
        "total_profiles":  db.query(Profile).count(),
        "active_profiles": db.query(Profile).filter_by(is_active=True).count(),
        "total_posts":     db.query(Post).count(),
        "embedded_posts":  db.query(Post).filter_by(embedded=True).count(),
        "vector_count":    collection_stats()["total_embeddings"],
        "next_scrape":     job.next_run_time.isoformat() if job and job.next_run_time else None,
    }
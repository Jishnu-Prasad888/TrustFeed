"""
main.py — FastAPI application entry point
"""
from __future__ import annotations
import asyncio
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

# ── Scheduler ────────────────────────────────────────────────────────────────
from apscheduler.schedulers.asyncio import AsyncIOScheduler
scheduler = AsyncIOScheduler()


async def run_scrape_cycle():
    """Called by APScheduler — scrapes all active profiles."""
    from db.models import SessionLocal
    db = SessionLocal()
    try:
        profiles = db.query(Profile).filter(Profile.is_active == True).all()
        logger.info(f"Scrape cycle: {len(profiles)} active profiles")
        for profile in profiles:
            posts_data = await scrape_profile(profile.platform, profile.url)
            new_count = 0
            for pdata in posts_data:
                existing = db.query(Post).filter_by(
                    content_hash=pdata["content_hash"]
                ).first()
                if existing:
                    continue
                post = Post(
                    profile_id=profile.id,
                    content_hash=pdata["content_hash"],
                    raw_content=pdata["raw_content"],
                    url=pdata["url"],
                    published_at=pdata.get("published_at"),
                    trust_at_embed=profile.trust,
                )
                db.add(post)
                db.flush()
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
                new_count += 1
            db.commit()
            if new_count:
                logger.info(f"  {profile.name}: {new_count} new posts embedded")
    except Exception as e:
        logger.error(f"Scrape cycle error: {e}")
        db.rollback()
    finally:
        db.close()


def _reschedule(interval_minutes: int):
    if scheduler.get_job("scrape"):
        scheduler.remove_job("scrape")
    scheduler.add_job(
        run_scrape_cycle,
        "interval",
        minutes=interval_minutes,
        id="scrape",
        replace_existing=True,
    )
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


# ── App ───────────────────────────────────────────────────────────────────────
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


class RAGQuery(BaseModel):
    question: str
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
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile.to_dict()


@app.get("/profiles/{profile_id}")
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    p = db.get(Profile, profile_id)
    if not p:
        raise HTTPException(404, "Profile not found")
    return p.to_dict()


@app.patch("/profiles/{profile_id}")
def update_profile(profile_id: int, body: ProfileUpdate, db: Session = Depends(get_db)):
    p = db.get(Profile, profile_id)
    if not p:
        raise HTTPException(404, "Profile not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    return p.to_dict()


@app.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    p = db.get(Profile, profile_id)
    if not p:
        raise HTTPException(404, "Profile not found")
    delete_profile_embeddings(profile_id)
    db.delete(p)
    db.commit()


# ── Posts ─────────────────────────────────────────────────────────────────────

@app.get("/posts")
def list_posts(profile_id: int | None = None, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(Post).order_by(Post.scraped_at.desc())
    if profile_id:
        q = q.filter_by(profile_id=profile_id)
    return [p.to_dict() for p in q.limit(limit).all()]


# ── Scrape ────────────────────────────────────────────────────────────────────

@app.post("/scrape/trigger")
async def trigger_scrape(background_tasks: BackgroundTasks):
    """Manually kick off a scrape cycle."""
    background_tasks.add_task(run_scrape_cycle)
    return {"status": "scrape started"}


@app.post("/scrape/profile/{profile_id}")
async def scrape_single(profile_id: int, db: Session = Depends(get_db)):
    """Scrape one profile immediately."""
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    posts_data = await scrape_profile(profile.platform, profile.url)
    new_count = 0
    for pdata in posts_data:
        if db.query(Post).filter_by(content_hash=pdata["content_hash"]).first():
            continue
        post = Post(
            profile_id=profile.id,
            content_hash=pdata["content_hash"],
            raw_content=pdata["raw_content"],
            url=pdata["url"],
            published_at=pdata.get("published_at"),
            trust_at_embed=profile.trust,
        )
        db.add(post)
        db.flush()
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
        new_count += 1
    db.commit()
    return {"new_posts": new_count, "total_fetched": len(posts_data)}


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    rows = db.query(AppSettings).all()
    return {r.key: r.value for r in rows}


@app.patch("/settings")
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    updates = body.model_dump(exclude_none=True)
    for k, v in updates.items():
        setting = db.get(AppSettings, k)
        if setting:
            setting.value = str(v)
        else:
            db.add(AppSettings(key=k, value=str(v)))
    db.commit()
    # Reschedule if interval changed
    if "scrape_interval_minutes" in updates:
        _reschedule(int(updates["scrape_interval_minutes"]))
    return {r.key: r.value for r in db.query(AppSettings).all()}


# ── RAG ───────────────────────────────────────────────────────────────────────

@app.post("/rag/query")
def rag_query(body: RAGQuery, db: Session = Depends(get_db)):
    settings = {r.key: r.value for r in db.query(AppSettings).all()}
    model_name  = settings.get("ollama_model", "llama3")
    top_k       = int(settings.get("max_rag_chunks", "8"))
    lambda_     = float(settings.get("recency_decay_lambda", "0.05"))

    active_ids = None
    if body.only_active:
        active_profiles = db.query(Profile).filter_by(is_active=True).all()
        active_ids = [p.id for p in active_profiles]

    result = query_rag(
        query=body.question,
        model_name=model_name,
        top_k=top_k,
        lambda_=lambda_,
        active_profile_ids=active_ids,
    )
    return result


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/stats")
def stats(db: Session = Depends(get_db)):
    total_profiles = db.query(Profile).count()
    active_profiles = db.query(Profile).filter_by(is_active=True).count()
    total_posts = db.query(Post).count()
    embedded_posts = db.query(Post).filter_by(embedded=True).count()
    vec_stats = collection_stats()
    next_run = None
    job = scheduler.get_job("scrape")
    if job and job.next_run_time:
        next_run = job.next_run_time.isoformat()
    return {
        "total_profiles":  total_profiles,
        "active_profiles": active_profiles,
        "total_posts":     total_posts,
        "embedded_posts":  embedded_posts,
        "vector_count":    vec_stats["total_embeddings"],
        "next_scrape":     next_run,
    }

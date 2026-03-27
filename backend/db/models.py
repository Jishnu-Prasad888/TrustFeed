"""
db/models.py — SQLAlchemy ORM models
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, Text, ForeignKey, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class Profile(Base):
    """A social / RSS profile to monitor."""
    __tablename__ = "profiles"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(200), nullable=False)
    url         = Column(String(500), nullable=False, unique=True)
    platform    = Column(String(50), default="rss")   # rss | twitter | web
    trust       = Column(Float, default=0.5)           # 0.0 – 1.0
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    posts = relationship("Post", back_populates="profile", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id":         self.id,
            "name":       self.name,
            "url":        self.url,
            "platform":   self.platform,
            "trust":      self.trust,
            "is_active":  self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Post(Base):
    """A scraped post / article from a profile."""
    __tablename__ = "posts"

    id            = Column(Integer, primary_key=True, index=True)
    profile_id    = Column(Integer, ForeignKey("profiles.id"), nullable=False)
    content_hash  = Column(String(64), nullable=False, index=True)  # SHA-256 of content
    raw_content   = Column(Text, nullable=False)
    url           = Column(String(500))
    published_at  = Column(DateTime)                 # from feed / page
    scraped_at    = Column(DateTime, default=datetime.utcnow)
    embedded      = Column(Boolean, default=False)   # has been sent to ChromaDB?
    trust_at_embed = Column(Float)                   # snapshot of profile trust when embedded

    profile = relationship("Profile", back_populates="posts")

    def to_dict(self):
        return {
            "id":             self.id,
            "profile_id":     self.profile_id,
            "content_hash":   self.content_hash,
            "raw_content":    self.raw_content,
            "url":            self.url,
            "published_at":   self.published_at.isoformat() if self.published_at else None,
            "scraped_at":     self.scraped_at.isoformat() if self.scraped_at else None,
            "embedded":       self.embedded,
            "trust_at_embed": self.trust_at_embed,
        }


class AppSettings(Base):
    """Global app settings stored as key-value."""
    __tablename__ = "app_settings"

    key   = Column(String(100), primary_key=True)
    value = Column(String(500), nullable=False)


# ── Engine / Session factory ─────────────────────────────────────────────────

DATABASE_URL = "sqlite:///./trustfeed.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
    # Seed default settings
    with SessionLocal() as session:
        defaults = {
            "scrape_interval_minutes": "30",
            "ollama_model":            "llama3",
            "recency_decay_lambda":    "0.05",
            "max_rag_chunks":          "8",
        }
        for k, v in defaults.items():
            if not session.get(AppSettings, k):
                session.add(AppSettings(key=k, value=v))
        session.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

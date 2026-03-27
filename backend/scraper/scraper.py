"""
scraper/scraper.py — Multi-platform scraper
Supports: RSS/Atom feeds, generic web pages (Playwright), Twitter/X (basic)
"""
from __future__ import annotations
import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Optional
import feedparser
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()


def _clean(text: str) -> str:
    soup = BeautifulSoup(text, "lxml")
    return soup.get_text(separator=" ", strip=True)


# ── RSS / Atom ────────────────────────────────────────────────────────────────

async def scrape_rss(url: str) -> list[dict]:
    """Return list of {content, url, published_at, hash}."""
    loop = asyncio.get_event_loop()
    feed = await loop.run_in_executor(None, feedparser.parse, url)
    posts = []
    for entry in feed.entries:
        raw = _clean(getattr(entry, "summary", "") or getattr(entry, "title", ""))
        if not raw:
            continue
        pub = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            pub = datetime(*entry.published_parsed[:6])
        posts.append({
            "raw_content":  raw,
            "url":          getattr(entry, "link", url),
            "published_at": pub,
            "content_hash": _hash(raw),
        })
    return posts


# ── Generic Web Page (Playwright) ─────────────────────────────────────────────

async def scrape_web(url: str) -> list[dict]:
    """
    Scrapes visible text from a generic webpage.
    Returns a single 'post' per page scrape.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed; falling back to httpx")
        return await scrape_web_httpx(url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=20_000, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
            html = await page.content()
        finally:
            await browser.close()

    raw = _clean(html)[:4000]  # limit to 4k chars per page
    if not raw:
        return []
    return [{
        "raw_content":  raw,
        "url":          url,
        "published_at": datetime.utcnow(),
        "content_hash": _hash(raw),
    }]


async def scrape_web_httpx(url: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "TrustFeed/1.0"})
        resp.raise_for_status()
    raw = _clean(resp.text)[:4000]
    return [{
        "raw_content":  raw,
        "url":          url,
        "published_at": datetime.utcnow(),
        "content_hash": _hash(raw),
    }]


# ── Twitter / X (public embed via Nitter if available) ───────────────────────

NITTER_INSTANCE = "https://nitter.privacydev.net"

async def scrape_twitter(username: str) -> list[dict]:
    """
    Scrapes via a Nitter RSS feed (no API key required).
    username can be full URL like https://twitter.com/elonmusk or just elonmusk.
    """
    if "twitter.com" in username or "x.com" in username:
        handle = username.rstrip("/").split("/")[-1]
    else:
        handle = username.lstrip("@")

    rss_url = f"{NITTER_INSTANCE}/{handle}/rss"
    try:
        posts = await scrape_rss(rss_url)
        return posts
    except Exception as e:
        logger.warning(f"Nitter scrape failed for {handle}: {e}")
        return []


# ── Dispatcher ────────────────────────────────────────────────────────────────

async def scrape_profile(platform: str, url: str) -> list[dict]:
    """
    Route to the correct scraper based on platform tag.
    Returns list of post dicts.
    """
    try:
        if platform == "rss":
            return await scrape_rss(url)
        elif platform in ("twitter", "x"):
            return await scrape_twitter(url)
        else:
            return await scrape_web(url)
    except Exception as e:
        logger.error(f"Scrape failed [{platform}] {url}: {e}")
        return []

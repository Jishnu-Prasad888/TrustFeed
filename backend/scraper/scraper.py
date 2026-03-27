"""
scraper/scraper.py — Multi-platform scraper

Supports:
  - RSS / Atom feeds           (platform="rss")
  - Twitter/X via cookies      (platform="twitter" | "x")
  - Twitter search / hashtags  (platform="twitter_search")
  - Generic web pages          (platform="web", fallback)

Twitter setup:
  1. Log into x.com in your browser
  2. DevTools → Application → Cookies → https://x.com
  3. Copy `auth_token` and `ct0` values into your cookies.txt
     (Netscape format) OR set env vars:
       TWITTER_AUTH_TOKEN=...
       TWITTER_CT0=...
     OR set TWITTER_COOKIES_TXT=/path/to/cookies.txt

Output format for all scrapers:
  {
      "raw_content":  str,
      "url":          str,
      "published_at": datetime | None,  # naive UTC
      "content_hash": str,              # sha256 of raw_content
  }
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TWEETS_LIMIT = 20  # fallback only; prefer passing limit explicitly


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()


def _clean(text: str) -> str:
    soup = BeautifulSoup(text, "lxml")
    return soup.get_text(separator=" ", strip=True)


def _parse_cookies_txt(path: str) -> dict[str, str]:
    """Parse a Netscape-format cookies.txt into {name: value}."""
    cookies: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
    return cookies


# ── RSS / Atom ────────────────────────────────────────────────────────────────

async def scrape_rss(url: str) -> list[dict]:
    loop = asyncio.get_event_loop()

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        try:
            r = await client.get(url, headers={"User-Agent": "TrustFeed/1.0"})
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"HTTP {e.response.status_code} fetching RSS: {url}") from e
        except httpx.RequestError as e:
            raise RuntimeError(f"Network error fetching RSS: {url} — {e}") from e

    feed = await loop.run_in_executor(None, feedparser.parse, url)

    if feed.bozo and not feed.entries:
        raise RuntimeError(
            f"feedparser could not parse feed at {url}: {feed.bozo_exception}"
        )

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


# ── Generic Web Page ──────────────────────────────────────────────────────────

async def scrape_web(url: str) -> list[dict]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed; falling back to httpx")
        return await _scrape_web_httpx(url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=20_000, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
            html = await page.content()
        finally:
            await browser.close()

    raw = _clean(html)[:4000]
    if not raw:
        return []
    return [{
        "raw_content":  raw,
        "url":          url,
        "published_at": datetime.utcnow(),
        "content_hash": _hash(raw),
    }]


async def _scrape_web_httpx(url: str) -> list[dict]:
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


# ── Twitter / X — cookie-based GraphQL scraper ───────────────────────────────

_BEARER = (
    "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
_API_BASE = "https://api.x.com"

_USER_FEATURES = {
    "hidden_profile_likes_enabled": True,
    "hidden_profile_subscriptions_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}

_TWEET_FEATURES = {
    **_USER_FEATURES,
    "rweb_lists_timeline_redesign_enabled": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "responsive_web_media_download_video_enabled": False,
    "interactive_text_enabled": True,
    "responsive_web_text_conversations_enabled": False,
    "vibe_api_enabled": False,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": False,
    "tweetypie_unmention_optimization_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "responsive_web_home_pinned_timelines_enabled": True,
    "blue_business_profile_image_shape_enabled": True,
}

_SEARCH_FEATURES = {
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": False,
    "tweet_awards_web_tipping_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

_DEFAULT_COOKIES_PATH = os.environ.get("TWITTER_COOKIES_TXT", "")


def _make_twitter_headers(auth_token: str, ct0: str) -> dict[str, str]:
    return {
        "authorization":             _BEARER,
        "x-csrf-token":              ct0,
        "x-twitter-auth-type":       "OAuth2Session",
        "x-twitter-client-language": "en",
        "x-twitter-active-user":     "yes",
        "content-type":              "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }


def _load_twitter_cookies(cookies_path: str = "") -> tuple[str, str]:
    """
    Load auth_token + ct0 from (in priority order):
      1. Explicit cookies_path argument (set via AppSettings from frontend)
      2. TWITTER_COOKIES_TXT env var
      3. TWITTER_AUTH_TOKEN + TWITTER_CT0 env vars
    Raises RuntimeError if none is available.
    """
    path = cookies_path or _DEFAULT_COOKIES_PATH
    if path and os.path.exists(path):
        raw = _parse_cookies_txt(path)
        auth_token = raw.get("auth_token")
        ct0        = raw.get("ct0")
        if auth_token and ct0:
            return auth_token, ct0
        logger.warning(
            f"cookies.txt at {path} missing auth_token or ct0; "
            "falling back to env vars"
        )

    auth_token = os.environ.get("TWITTER_AUTH_TOKEN")
    ct0        = os.environ.get("TWITTER_CT0")
    if auth_token and ct0:
        return auth_token, ct0

    raise RuntimeError(
        "Twitter cookies not found. Set twitter_cookies_path in Settings, "
        "provide a cookies.txt, or set TWITTER_AUTH_TOKEN / TWITTER_CT0 env vars."
    )


async def _twitter_get(
    url: str,
    params: dict,
    auth_token: str,
    ct0: str,
) -> dict:
    async with httpx.AsyncClient(
        headers=_make_twitter_headers(auth_token, ct0),
        cookies={"auth_token": auth_token, "ct0": ct0},
        timeout=15,
        follow_redirects=True,
    ) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


def _tweet_text(result: dict) -> str:
    legacy = result.get("legacy", {})
    note   = result.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {})
    if note:
        return note.get("text", "") or legacy.get("full_text", "")
    return legacy.get("full_text", "")


def _parse_tweet_result(result: dict) -> Optional[dict]:
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", {})
    if result.get("__typename") not in ("Tweet", None):
        return None

    legacy = result.get("legacy", {})
    if not legacy:
        return None
    if legacy.get("retweeted_status_id_str"):   # skip retweets
        return None

    text = _tweet_text(result)
    if not text:
        return None

    user       = result.get("core", {}).get("user_results", {}).get("result", {})
    username   = user.get("legacy", {}).get("screen_name", "unknown")
    tweet_id   = legacy.get("id_str", "0")
    created_at = legacy.get("created_at", "")

    pub: Optional[datetime] = None
    if created_at:
        try:
            pub = datetime.strptime(created_at, "%a %b %d %H:%M:%S +0000 %Y")
        except ValueError:
            pass

    return {
        "raw_content":  text,
        "url":          f"https://x.com/{username}/status/{tweet_id}",
        "published_at": pub,
        "content_hash": _hash(text),
    }


def _walk_timeline_entries(entries: list[dict]) -> list[dict]:
    posts = []
    for entry in entries:
        content    = entry.get("content", {})
        entry_type = content.get("entryType", "")

        if entry_type == "TimelineTimelineItem":
            item = content.get("itemContent", {})
            if item.get("itemType") == "TimelineTweet":
                post = _parse_tweet_result(
                    item.get("tweet_results", {}).get("result", {})
                )
                if post:
                    posts.append(post)

        elif entry_type == "TimelineTimelineModule":
            for item_wrap in content.get("items", []):
                item = item_wrap.get("item", {}).get("itemContent", {})
                if item.get("itemType") == "TimelineTweet":
                    post = _parse_tweet_result(
                        item.get("tweet_results", {}).get("result", {})
                    )
                    if post:
                        posts.append(post)

    return posts


async def _resolve_twitter_user_id(
    handle: str, auth_token: str, ct0: str
) -> str:
    url  = f"{_API_BASE}/graphql/G3KGOASz96M-Qu0nwmGXNg/UserByScreenName"
    data = await _twitter_get(url, params={
        "variables": json.dumps({
            "screen_name": handle,
            "withSafetyModeUserFields": True,
        }),
        "features": json.dumps(_USER_FEATURES),
    }, auth_token=auth_token, ct0=ct0)

    result = data.get("data", {}).get("user", {}).get("result", {})
    if not result or result.get("__typename") != "User":
        raise RuntimeError(f"Twitter user not found: @{handle}")
    return result["rest_id"]


async def scrape_twitter(username: str, limit: int = TWEETS_LIMIT, cookies_path: str = "") -> list[dict]:
    """Scrape latest tweets from a user's timeline by @handle or profile URL."""
    handle = username.rstrip("/").split("/")[-1].lstrip("@")

    try:
        auth_token, ct0 = _load_twitter_cookies(cookies_path)
    except RuntimeError as e:
        logger.error(f"Twitter cookie load failed: {e}")
        return []

    try:
        user_id = await _resolve_twitter_user_id(handle, auth_token, ct0)
    except Exception as e:
        logger.error(f"Could not resolve Twitter user @{handle}: {e}")
        return []

    url = f"{_API_BASE}/graphql/V1ze5q3ijDS1VeLwLY0m7g/UserTweets"
    posts: list[dict] = []
    cursor: Optional[str] = None

    while len(posts) < limit:
        variables: dict = {
            "userId":                 user_id,
            "count":                  min(limit - len(posts), 40),
            "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice":              True,
            "withV2Timeline":         True,
        }
        if cursor:
            variables["cursor"] = cursor

        try:
            data = await _twitter_get(url, params={
                "variables": json.dumps(variables),
                "features":  json.dumps(_TWEET_FEATURES),
            }, auth_token=auth_token, ct0=ct0)
        except Exception as e:
            logger.error(f"Twitter timeline request failed for @{handle}: {e}")
            break

        instructions = (
            data.get("data", {})
                .get("user", {})
                .get("result", {})
                .get("timeline_v2", {})
                .get("timeline", {})
                .get("instructions", [])
        )

        entries: list[dict] = []
        next_cursor: Optional[str] = None

        for inst in instructions:
            if inst.get("type") == "TimelineAddEntries":
                for entry in inst.get("entries", []):
                    if "cursor-bottom" in entry.get("entryId", ""):
                        next_cursor = entry.get("content", {}).get("value")
                    else:
                        entries.append(entry)

        batch = _walk_timeline_entries(entries)
        posts.extend(batch)

        if not batch or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor

    logger.info(f"scrape_twitter @{handle}: {len(posts)} tweets")
    return posts[:limit]


async def scrape_twitter_search(
    query: str,
    limit: int = TWEETS_LIMIT,
    mode: str = "Latest",
    cookies_path: str = "",
) -> list[dict]:
    """
    Scrape Twitter search results for a query string or hashtag.
    mode: "Latest" | "Top"
    """
    try:
        auth_token, ct0 = _load_twitter_cookies(cookies_path)
    except RuntimeError as e:
        logger.error(f"Twitter cookie load failed: {e}")
        return []

    url = f"{_API_BASE}/graphql/gkjsKepM6gl_HmFWoWKfgg/SearchTimeline"
    posts: list[dict] = []
    cursor: Optional[str] = None

    while len(posts) < limit:
        variables: dict = {
            "rawQuery":               query,
            "count":                  min(limit - len(posts), 40),
            "querySource":            "typed_query",
            "product":                mode,
            "includePromotedContent": False,
            "withBirdwatchNotes":     False,
        }
        if cursor:
            variables["cursor"] = cursor

        try:
            data = await _twitter_get(url, params={
                "variables": json.dumps(variables),
                "features":  json.dumps(_SEARCH_FEATURES),
            }, auth_token=auth_token, ct0=ct0)
        except Exception as e:
            logger.error(f"Twitter search request failed for '{query}': {e}")
            break

        instructions = (
            data.get("data", {})
                .get("search_by_raw_query", {})
                .get("search_timeline", {})
                .get("timeline", {})
                .get("instructions", [])
        )

        entries: list[dict] = []
        next_cursor: Optional[str] = None

        for inst in instructions:
            if inst.get("type") == "TimelineAddEntries":
                for entry in inst.get("entries", []):
                    if "cursor-bottom" in entry.get("entryId", ""):
                        next_cursor = entry.get("content", {}).get("value")
                    else:
                        entries.append(entry)
            elif inst.get("type") == "TimelineReplaceEntry":
                entry = inst.get("entry", {})
                if "cursor-bottom" in entry.get("entryId", ""):
                    next_cursor = entry.get("content", {}).get("value")

        batch = _walk_timeline_entries(entries)
        posts.extend(batch)

        if not batch or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor

    logger.info(f"scrape_twitter_search '{query}': {len(posts)} tweets")
    return posts[:limit]


# ── Dispatcher ────────────────────────────────────────────────────────────────

async def scrape_profile(
    platform: str,
    url: str,
    limit: int = TWEETS_LIMIT,
    cookies_path: str = "",
) -> list[dict]:
    """
    Route to the correct scraper based on platform tag.
    Returns list of post dicts (empty list on failure).

    platform values:
      "rss"            → RSS/Atom feed
      "twitter" | "x"  → Twitter user timeline (url = handle or profile URL)
      "twitter_search" → Twitter search (url = query string or hashtag)
      anything else    → generic web page

    limit:        max tweets to fetch (Twitter only)
    cookies_path: path to Netscape cookies.txt (Twitter only); overrides env/settings
    """
    try:
        if platform == "rss":
            return await scrape_rss(url)
        elif platform in ("twitter", "x"):
            return await scrape_twitter(url, limit=limit, cookies_path=cookies_path)
        elif platform == "twitter_search":
            return await scrape_twitter_search(url, limit=limit, cookies_path=cookies_path)
        else:
            return await scrape_web(url)
    except Exception as e:
        logger.error(f"Scrape failed [{platform}] {url}: {e}", exc_info=True)
        return []
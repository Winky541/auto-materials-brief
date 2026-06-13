"""Fetch raw news candidates for Automotive Materials Intelligence Hub.

This stage collects current-month candidate news from configured RSS sources
and Bing News RSS queries. It does not call DeepSeek, rank final stories, build
the site, or push bot messages.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
SOURCES_PATH = PROJECT_ROOT / "data" / "sources.yaml"
OUTPUT_PATH = PROJECT_ROOT / "data" / "news_raw.json"

USER_AGENT = (
    "AutomotiveMaterialsIntelligenceHub/0.1 "
    "(research news collection; stage 2)"
)
REQUEST_TIMEOUT_SECONDS = 20

TRACKING_PARAMS_PREFIXES = ("utm_",)
TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
}


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load project configuration with conservative defaults."""
    if not path.exists():
        logging.warning("Config file not found: %s; using defaults.", path)
        return {
            "limits": {"max_news_candidates": 150},
            "timezone": "Asia/Shanghai",
        }

    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    config.setdefault("limits", {})
    config["limits"].setdefault("max_news_candidates", 150)
    config.setdefault("timezone", "Asia/Shanghai")
    return config


def load_sources(path: Path = SOURCES_PATH) -> dict[str, Any]:
    """Load RSS source and Bing News RSS query configuration."""
    if not path.exists():
        logging.warning("Sources file not found: %s", path)
        return {"sources": [], "bing_news_queries": []}

    with path.open("r", encoding="utf-8") as file:
        sources = yaml.safe_load(file) or {}

    sources.setdefault("sources", [])
    sources.setdefault("bing_news_queries", [])
    return sources


def clean_url(url: str | None) -> str | None:
    """Normalize a URL and drop common tracking parameters."""
    if not url:
        return None

    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if parsed.netloc.lower().endswith("bing.com"):
        for key, value in query_pairs:
            if key.lower() == "url" and value:
                return clean_url(value)

    cleaned_query = []
    for key, value in query_pairs:
        key_lower = key.lower()
        if key_lower in TRACKING_PARAMS:
            continue
        if any(key_lower.startswith(prefix) for prefix in TRACKING_PARAMS_PREFIXES):
            continue
        cleaned_query.append((key, value))

    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            urlencode(cleaned_query, doseq=True),
            "",
        )
    )


def normalize_date(value: Any, timezone_name: str = "Asia/Shanghai") -> str | None:
    """Parse a feed date and return YYYY-MM-DD in the configured timezone."""
    if not value:
        return None

    try:
        if isinstance(value, tuple):
            parsed = datetime(*value[:6])
        else:
            parsed = date_parser.parse(str(value))
    except (TypeError, ValueError, OverflowError):
        return None

    target_tz = ZoneInfo(timezone_name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=target_tz)
    else:
        parsed = parsed.astimezone(target_tz)

    return parsed.date().isoformat()


def is_current_month(date_value: str, timezone_name: str = "Asia/Shanghai") -> bool:
    """Return True when YYYY-MM-DD belongs to the current configured month."""
    try:
        published = datetime.strptime(date_value, "%Y-%m-%d").date()
    except ValueError:
        return False

    now = datetime.now(ZoneInfo(timezone_name)).date()
    return published.year == now.year and published.month == now.month


def _strip_html(value: str | None) -> str:
    """Convert feed summary HTML into readable plain text."""
    if not value:
        return ""
    return " ".join(BeautifulSoup(value, "html.parser").get_text(" ").split())


def _entry_date(entry: Any, timezone_name: str) -> str | None:
    """Find and normalize the best available date field in a feed entry."""
    for field in ("published", "updated", "created"):
        normalized = normalize_date(entry.get(field), timezone_name)
        if normalized:
            return normalized

    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        normalized = normalize_date(entry.get(field), timezone_name)
        if normalized:
            return normalized

    return None


def fetch_rss_source(
    source: dict[str, Any], timezone_name: str = "Asia/Shanghai"
) -> tuple[list[dict[str, Any]], int]:
    """Fetch one configured RSS source and return current-month candidates."""
    name = source.get("name") or source.get("url") or "Unnamed RSS source"
    url = source.get("url")
    source_score = int(source.get("source_score", 0) or 0)

    if not url:
        logging.warning("Skipping RSS source without url: %s", name)
        return [], 1

    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logging.warning("RSS source failed: %s (%s)", name, exc)
        return [], 0

    feed = feedparser.parse(response.content)
    if getattr(feed, "bozo", False):
        logging.warning("RSS source parsed with warning: %s (%s)", name, feed.bozo_exception)

    items: list[dict[str, Any]] = []
    skipped = 0
    collected_at = datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")

    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        entry_url = clean_url(entry.get("link"))
        published_date = _entry_date(entry, timezone_name)

        if not title or not entry_url or not published_date:
            skipped += 1
            continue

        if not is_current_month(published_date, timezone_name):
            skipped += 1
            continue

        items.append(
            {
                "title": title,
                "source": str(name),
                "published_date": published_date,
                "url": entry_url,
                "summary": _strip_html(entry.get("summary") or entry.get("description")),
                "collected_at": collected_at,
                "source_type": "rss",
                "source_score": source_score,
            }
        )

    logging.info("RSS source %s fetched %s current-month items; skipped %s.", name, len(items), skipped)
    return items, skipped


def fetch_bing_news_rss(
    query_config: dict[str, Any], timezone_name: str = "Asia/Shanghai"
) -> tuple[list[dict[str, Any]], int]:
    """Fetch one Bing News RSS query and return current-month candidates."""
    query = query_config.get("query")
    source_score = int(query_config.get("source_score", 0) or 0)

    if not query:
        logging.warning("Skipping Bing News query without query text: %s", query_config)
        return [], 1

    rss_url = "https://www.bing.com/news/search?" + urlencode(
        {"q": query, "format": "rss"}
    )

    try:
        response = requests.get(
            rss_url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logging.warning("Bing News RSS query failed: %s (%s)", query, exc)
        return [], 0

    feed = feedparser.parse(response.content)
    if getattr(feed, "bozo", False):
        logging.warning(
            "Bing News RSS parsed with warning: %s (%s)", query, feed.bozo_exception
        )

    items: list[dict[str, Any]] = []
    skipped = 0
    collected_at = datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")

    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        entry_url = clean_url(entry.get("link"))
        published_date = _entry_date(entry, timezone_name)

        if not title or not entry_url or not published_date:
            skipped += 1
            continue

        if not is_current_month(published_date, timezone_name):
            skipped += 1
            continue

        source_name = "Bing News"
        entry_source = entry.get("source")
        if isinstance(entry_source, dict) and entry_source.get("title"):
            source_name = entry_source["title"]

        items.append(
            {
                "title": title,
                "source": source_name,
                "published_date": published_date,
                "url": entry_url,
                "summary": _strip_html(entry.get("summary") or entry.get("description")),
                "collected_at": collected_at,
                "source_type": "bing_news",
                "source_score": source_score,
            }
        )

    logging.info(
        "Bing News query %r fetched %s current-month items; skipped %s.",
        query,
        len(items),
        skipped,
    )
    return items, skipped


def deduplicate_by_url(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate candidates by cleaned URL, preserving first occurrence."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []

    for item in items:
        url = clean_url(item.get("url"))
        if not url or url in seen:
            continue
        item["url"] = url
        seen.add(url)
        unique.append(item)

    return unique


def save_json(items: list[dict[str, Any]], path: Path = OUTPUT_PATH) -> None:
    """Write UTF-8 JSON for downstream processing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(items, file, ensure_ascii=False, indent=2)
        file.write("\n")


def main() -> None:
    """Collect current-month raw news candidates into data/news_raw.json."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = load_config()
    sources_config = load_sources()
    timezone_name = config.get("timezone", "Asia/Shanghai")
    max_candidates = int(config.get("limits", {}).get("max_news_candidates", 150))

    all_items: list[dict[str, Any]] = []
    total_skipped = 0

    for source in sources_config.get("sources", []):
        if source.get("type") != "rss":
            logging.warning("Skipping unsupported source type: %s", source)
            total_skipped += 1
            continue
        items, skipped = fetch_rss_source(source, timezone_name)
        all_items.extend(items)
        total_skipped += skipped

    for query_config in sources_config.get("bing_news_queries", []):
        items, skipped = fetch_bing_news_rss(query_config, timezone_name)
        all_items.extend(items)
        total_skipped += skipped

    logging.info("Fetched %s current-month candidates before deduplication.", len(all_items))
    logging.info("Skipped %s entries due to missing fields, old dates, or unsupported config.", total_skipped)

    deduplicated = deduplicate_by_url(all_items)
    deduplicated.sort(
        key=lambda item: (item.get("published_date", ""), int(item.get("source_score", 0))),
        reverse=True,
    )
    limited = deduplicated[:max_candidates]

    logging.info("Remaining after URL deduplication: %s.", len(deduplicated))
    if len(deduplicated) > max_candidates:
        logging.info("Limited candidates to max_news_candidates=%s.", max_candidates)

    save_json(limited, OUTPUT_PATH)
    logging.info("Saved %s raw candidates to %s.", len(limited), OUTPUT_PATH)


if __name__ == "__main__":
    main()

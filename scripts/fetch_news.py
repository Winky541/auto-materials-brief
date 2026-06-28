"""Fetch raw news candidates for AURA.

V2-2 prioritizes original and authoritative sources: company/government pages,
journal RSS feeds, association sites, and professional media. Bing News RSS is
kept as a supplemental discovery channel only. This script does not call
DeepSeek, rank final stories, build the site, or push bot messages.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

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
    "AutoMaterialsFutureMobilityBrief/0.2 "
    "(research news collection; V2-2)"
)
REQUEST_TIMEOUT_SECONDS = 20

SUPPORTED_SOURCE_TYPES = {
    "rss",
    "bing_news",
    "company_news_page",
    "journal_rss",
    "government_policy",
    "professional_media",
    "clue_platform",
}
RSS_SOURCE_TYPES = {"rss", "journal_rss"}
HTML_SOURCE_TYPES = {
    "company_news_page",
    "government_policy",
    "professional_media",
    "clue_platform",
}
ORIGINAL_SOURCE_TYPES = {
    "rss",
    "journal_rss",
    "company_news_page",
    "government_policy",
}
REPOST_DOMAINS = ("msn.com", "aol.com", "yahoo.com")
AGGREGATOR_DOMAINS = ("bing.com", "google.com", "news.google.com")
CLUE_DOMAINS = (
    "toutiao.com",
    "baijiahao.baidu.com",
    "zhihu.com",
    "mp.weixin.qq.com",
    "weixin.qq.com",
)
DISALLOWED_FINAL_DOMAINS = REPOST_DOMAINS + AGGREGATOR_DOMAINS + CLUE_DOMAINS
TRACKING_PARAMS_PREFIXES = ("utm_",)
TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
}
GENERIC_ITEM_SELECTORS = [
    "article",
    ".news-item",
    ".news-list li",
    ".list li",
    ".press-release",
    ".card",
    "li",
]
GENERIC_DATE_SELECTORS = [
    "time",
    ".date",
    ".time",
    ".publish-date",
    ".news-date",
    ".meta",
    "span",
]
DATE_PATTERNS = [
    r"\b20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\b",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+20\d{2}\b",
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+20\d{2}\b",
]


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load project configuration with conservative defaults."""
    if not path.exists():
        logging.warning("Config file not found: %s; using defaults.", path)
        return {"limits": {"max_news_candidates": 150}, "timezone": "Asia/Shanghai"}

    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    config.setdefault("limits", {})
    config["limits"].setdefault("max_news_candidates", 150)
    config.setdefault("timezone", "Asia/Shanghai")
    return config


def load_sources(path: Path = SOURCES_PATH) -> dict[str, Any]:
    """Load V2 grouped source configuration and legacy fallbacks."""
    if not path.exists():
        logging.warning("Sources file not found: %s", path)
        return {"source_groups": {}, "bing_news_queries": []}

    with path.open("r", encoding="utf-8") as file:
        sources = yaml.safe_load(file) or {}

    sources.setdefault("source_groups", {})
    sources.setdefault("sources", [])
    sources.setdefault("bing_news_queries", [])
    return sources


def iter_configured_sources(sources_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten grouped sources while preserving source_group metadata."""
    flattened: list[dict[str, Any]] = []

    for group_name, sources in sources_config.get("source_groups", {}).items():
        if not isinstance(sources, list):
            logging.warning("Skipping malformed source group %s.", group_name)
            continue
        for source in sources:
            if not isinstance(source, dict):
                logging.warning("Skipping malformed source in group %s: %s", group_name, source)
                continue
            item = dict(source)
            item.setdefault("source_group", group_name)
            if "type" in item and "source_type" not in item:
                item["source_type"] = item["type"]
            flattened.append(item)

    for source in sources_config.get("sources", []):
        if isinstance(source, dict):
            item = dict(source)
            item.setdefault("source_group", "legacy")
            if "type" in item and "source_type" not in item:
                item["source_type"] = item["type"]
            flattened.append(item)

    return flattened


def clean_url(url: str | None, base_url: str | None = None) -> str | None:
    """Normalize a URL, resolve relatives, unwrap Bing links, and drop tracking."""
    if not url:
        return None

    raw_url = urljoin(base_url, url.strip()) if base_url else url.strip()
    parsed = urlparse(raw_url)
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

    host = parsed.netloc.lower()
    if host.startswith("m."):
        host = host[2:]
    path = re.sub(r"/+$", "", parsed.path or "")
    if not path:
        path = "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            host,
            path,
            parsed.params,
            urlencode(cleaned_query, doseq=True),
            "",
        )
    )


def normalize_date(value: Any, timezone_name: str = "Asia/Shanghai") -> str | None:
    """Parse a feed or page date and return YYYY-MM-DD in the configured timezone."""
    if not value:
        return None

    raw_value = str(value).strip()
    raw_value = (
        raw_value.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("/", "-")
    )

    try:
        if isinstance(value, tuple):
            parsed = datetime(*value[:6])
        else:
            parsed = date_parser.parse(raw_value, fuzzy=True)
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


def is_allowed_date_for_source(
    date_value: str,
    source: dict[str, Any],
    timezone_name: str = "Asia/Shanghai",
) -> bool:
    """Default to current month; papers, patents, and standards may use 90 days."""
    try:
        published = datetime.strptime(date_value, "%Y-%m-%d").date()
    except ValueError:
        return False
    now = datetime.now(ZoneInfo(timezone_name)).date()
    source_text = f"{source.get('name', '')} {source.get('source_type', '')}".casefold()
    long_window = any(
        keyword in source_text
        for keyword in ("journal", "nature", "ieee", "sae", "wipo", "cnipa", "patent", "standard", "论文", "专利", "标准")
    )
    if long_window:
        return now - timedelta(days=90) <= published <= now
    return published.year == now.year and published.month == now.month


def _strip_html(value: str | None) -> str:
    """Convert HTML into compact readable plain text."""
    if not value:
        return ""
    return " ".join(BeautifulSoup(value, "html.parser").get_text(" ").split())


def _domain(url: str | None) -> str:
    if not url:
        return ""
    return urlparse(url).netloc.lower().removeprefix("www.")


def _domain_matches(domain: str, candidates: tuple[str, ...]) -> bool:
    return any(domain == candidate or domain.endswith(f".{candidate}") for candidate in candidates)


def is_disallowed_final_url(url: str | None) -> bool:
    """Return True for aggregator, repost, or clue domains that must not be final links."""
    return _domain_matches(_domain(url), DISALLOWED_FINAL_DOMAINS)


def _score_cap(source_type: str, url: str | None, score: int) -> int:
    domain = _domain(url)
    if source_type == "clue_platform" or _domain_matches(domain, CLUE_DOMAINS):
        return min(score, 35)
    if _domain_matches(domain, REPOST_DOMAINS):
        return min(score, 45)
    return score


def _credibility_level(source_type: str, url: str | None, configured: str | None) -> str:
    domain = _domain(url)
    if source_type == "clue_platform" or _domain_matches(domain, CLUE_DOMAINS):
        return "clue"
    if _domain_matches(domain, REPOST_DOMAINS):
        return "low"
    if configured in {"high", "medium", "low", "clue"}:
        return configured
    if source_type in {"rss", "journal_rss", "company_news_page", "government_policy"}:
        return "high"
    if source_type == "professional_media":
        return "medium"
    if source_type == "bing_news":
        return "medium"
    return "low"


def _original_preferred(source: dict[str, Any], url: str | None) -> bool:
    source_type = str(source.get("source_type") or "")
    domain = _domain(url)
    if source_type == "clue_platform" or _domain_matches(domain, CLUE_DOMAINS + REPOST_DOMAINS + AGGREGATOR_DOMAINS):
        return False
    if "original_source_preferred" in source:
        return bool(source.get("original_source_preferred"))
    return source_type in ORIGINAL_SOURCE_TYPES


def _base_fields(
    source: dict[str, Any],
    url: str,
    timezone_name: str,
) -> dict[str, Any]:
    source_type = str(source.get("source_type") or source.get("type") or "rss")
    source_group = str(source.get("source_group") or "ungrouped")
    primary_flow = "future_intelligence" if source_group == "future_intelligence" else "material_intelligence"
    module_targets = (
        ["future_signals"]
        if primary_flow == "future_intelligence"
        else ["today_key_insight", "bookshelf", "suggested_actions"]
    )
    score = int(source.get("source_score", 0) or 0)
    score = _score_cap(source_type, url, score)
    return {
        "source": str(source.get("name") or "Unknown source"),
        "collected_at": datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds"),
        "source_type": source_type,
        "source_group": source_group,
        "source_score": score,
        "credibility_level": _credibility_level(
            source_type, url, source.get("credibility_level")
        ),
        "original_source_preferred": _original_preferred(source, url),
        "flow_type": primary_flow,
        "primary_flow": primary_flow,
        "secondary_flow": "",
        "reason_for_flow": "Initial source-group flow assignment before keyword filtering.",
        "module_targets": module_targets,
        "related_sources": [],
    }


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
    """Fetch one configured RSS or journal RSS source."""
    name = source.get("name") or source.get("url") or "Unnamed RSS source"
    url = source.get("url")

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

    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        entry_url = clean_url(entry.get("link"), url)
        published_date = _entry_date(entry, timezone_name)

        if not title or not entry_url or not published_date or is_disallowed_final_url(entry_url):
            skipped += 1
            continue
        if not is_allowed_date_for_source(published_date, source, timezone_name):
            skipped += 1
            continue

        item = {
            "title": title,
            "published_date": published_date,
            "url": entry_url,
            "summary": _strip_html(entry.get("summary") or entry.get("description")),
            **_base_fields(source, entry_url, timezone_name),
        }
        items.append(item)

    logging.info(
        "%s source %s fetched %s current-month items; skipped %s.",
        source.get("source_type", "rss"),
        name,
        len(items),
        skipped,
    )
    return items, skipped


def _first_text(element: Any, selector: str | None) -> str:
    if not element:
        return ""
    target = element.select_one(selector) if selector else element
    return " ".join(target.get_text(" ").split()) if target else ""


def _first_link(element: Any, selector: str | None, base_url: str) -> str | None:
    if not element:
        return None
    target = element.select_one(selector) if selector else element.find("a", href=True)
    if not target:
        return None
    href = target.get("href")
    return clean_url(href, base_url)


def _extract_date_from_element(
    element: Any, selector: str | None, timezone_name: str
) -> str | None:
    selectors = [selector] if selector else GENERIC_DATE_SELECTORS
    for candidate_selector in selectors:
        if not candidate_selector:
            continue
        target = element.select_one(candidate_selector)
        if not target:
            continue
        for attr in ("datetime", "content", "title"):
            normalized = normalize_date(target.get(attr), timezone_name)
            if normalized:
                return normalized
        normalized = normalize_date(target.get_text(" "), timezone_name)
        if normalized:
            return normalized

    text = element.get_text(" ")
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            normalized = normalize_date(match.group(0), timezone_name)
            if normalized:
                return normalized

    return None


def fetch_html_source(
    source: dict[str, Any], timezone_name: str = "Asia/Shanghai"
) -> tuple[list[dict[str, Any]], int]:
    """Fetch a generic company/government/professional/clue HTML news page."""
    name = source.get("name") or source.get("url") or "Unnamed HTML source"
    url = source.get("url")
    source_type = source.get("source_type", "company_news_page")

    if not url:
        logging.warning("Skipping HTML source without url: %s", name)
        return [], 1

    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logging.warning("HTML source failed: %s (%s)", name, exc)
        return [], 0

    soup = BeautifulSoup(response.text, "html.parser")
    item_selector = source.get("item_selector")
    title_selector = source.get("title_selector")
    date_selector = source.get("date_selector")
    link_selector = source.get("link_selector")

    if item_selector:
        candidates = soup.select(item_selector)
    else:
        candidates = []
        for selector in GENERIC_ITEM_SELECTORS:
            candidates = soup.select(selector)
            if candidates:
                break

    if not candidates:
        logging.warning("HTML source has no matching items: %s", name)
        return [], 0

    items: list[dict[str, Any]] = []
    skipped = 0
    for candidate in candidates[:40]:
        link = _first_link(candidate, link_selector, url)
        title = _first_text(candidate, title_selector)
        if not title:
            link_node = candidate.select_one(link_selector) if link_selector else candidate.find("a")
            title = " ".join(link_node.get_text(" ").split()) if link_node else ""
        published_date = _extract_date_from_element(candidate, date_selector, timezone_name)

        if not title or not link or not published_date or is_disallowed_final_url(link):
            skipped += 1
            continue
        if not is_allowed_date_for_source(published_date, source, timezone_name):
            skipped += 1
            continue

        items.append(
            {
                "title": title,
                "published_date": published_date,
                "url": link,
                "summary": "",
                **_base_fields(source, link, timezone_name),
            }
        )

    logging.info(
        "%s source %s fetched %s current-month items; skipped %s.",
        source_type,
        name,
        len(items),
        skipped,
    )
    return items, skipped


def fetch_bing_news_rss(
    query_config: dict[str, Any], timezone_name: str = "Asia/Shanghai"
) -> tuple[list[dict[str, Any]], int]:
    """Fetch one Bing News RSS query as supplemental discovery."""
    query = query_config.get("query")
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

    source_template = {
        "name": "Bing News",
        "source_type": "bing_news",
        "source_group": query_config.get("source_group", "bing_news"),
        "source_score": int(query_config.get("source_score", 55) or 55),
        "credibility_level": "medium",
        "original_source_preferred": False,
    }
    items: list[dict[str, Any]] = []
    skipped = 0

    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        entry_url = clean_url(entry.get("link"))
        published_date = _entry_date(entry, timezone_name)

        if not title or not entry_url or not published_date or is_disallowed_final_url(entry_url):
            skipped += 1
            continue
        if not is_allowed_date_for_source(published_date, source_template, timezone_name):
            skipped += 1
            continue

        source = dict(source_template)
        entry_source = entry.get("source")
        if isinstance(entry_source, dict) and entry_source.get("title"):
            source["name"] = entry_source["title"]

        items.append(
            {
                "title": title,
                "published_date": published_date,
                "url": entry_url,
                "summary": _strip_html(entry.get("summary") or entry.get("description")),
                **_base_fields(source, entry_url, timezone_name),
            }
        )

    logging.info(
        "bing_news query %r fetched %s current-month items; skipped %s.",
        query,
        len(items),
        skipped,
    )
    return items, skipped


def _title_key(title: str) -> str:
    compact = re.sub(r"[\W_]+", "", title.lower(), flags=re.UNICODE)
    return compact[:80]


def _preference_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        1 if item.get("original_source_preferred") else 0,
        1 if item.get("credibility_level") == "high" else 0,
        int(item.get("source_score", 0) or 0),
        str(item.get("published_date", "")),
    )


def _related_source(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": item.get("source", ""),
        "url": item.get("url", ""),
        "source_type": item.get("source_type", ""),
        "source_group": item.get("source_group", ""),
        "source_score": item.get("source_score", 0),
        "credibility_level": item.get("credibility_level", ""),
    }


def _merge_related(primary: dict[str, Any], duplicate: dict[str, Any]) -> dict[str, Any]:
    related = primary.setdefault("related_sources", [])
    duplicate_source = _related_source(duplicate)
    if duplicate_source["url"] != primary.get("url") and duplicate_source not in related:
        related.append(duplicate_source)

    for candidate in duplicate.get("related_sources", []):
        if candidate.get("url") != primary.get("url") and candidate not in related:
            related.append(candidate)

    return primary


def deduplicate_by_url(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by URL and near event title, preferring original sources."""
    by_url: dict[str, dict[str, Any]] = {}
    for item in items:
        url = clean_url(item.get("url"))
        if not url:
            continue
        item["url"] = url
        existing = by_url.get(url)
        if not existing:
            by_url[url] = item
            continue
        if _preference_key(item) > _preference_key(existing):
            by_url[url] = _merge_related(item, existing)
        else:
            by_url[url] = _merge_related(existing, item)

    by_title: dict[str, dict[str, Any]] = {}
    for item in by_url.values():
        key = _title_key(str(item.get("title", "")))
        if len(key) < 20:
            key = f"url:{item.get('url')}"
        existing = by_title.get(key)
        if not existing:
            by_title[key] = item
            continue
        if _preference_key(item) > _preference_key(existing):
            by_title[key] = _merge_related(item, existing)
        else:
            by_title[key] = _merge_related(existing, item)

    return list(by_title.values())


def save_json(items: list[dict[str, Any]], path: Path = OUTPUT_PATH) -> None:
    """Write UTF-8 JSON for downstream processing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(items, file, ensure_ascii=False, indent=2)
        file.write("\n")


def has_existing_items(path: Path = OUTPUT_PATH) -> bool:
    """Return True when an existing JSON file contains at least one raw item."""
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError) as exc:
        logging.warning("Existing raw news file is not reusable: %s (%s)", path, exc)
        return False
    return isinstance(data, list) and len(data) > 0


def _log_type_counts(label: str, items: list[dict[str, Any]]) -> None:
    counts = Counter(item.get("source_type", "unknown") for item in items)
    if counts:
        logging.info("%s source_type counts: %s", label, dict(sorted(counts.items())))
    else:
        logging.info("%s source_type counts: none", label)


def _log_configured_source_counts(sources: list[dict[str, Any]]) -> None:
    """Log how many configured sources exist for each source_type."""
    counts = Counter(source.get("source_type", "unknown") for source in sources)
    logging.info("Configured source_type counts: %s", dict(sorted(counts.items())))


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

    configured_sources = iter_configured_sources(sources_config)
    all_items: list[dict[str, Any]] = []
    total_skipped = 0
    _log_configured_source_counts(configured_sources)

    rss_sources = [s for s in configured_sources if s.get("source_type") in RSS_SOURCE_TYPES]
    html_sources = [s for s in configured_sources if s.get("source_type") in HTML_SOURCE_TYPES]
    unsupported_sources = [
        s for s in configured_sources if s.get("source_type") not in SUPPORTED_SOURCE_TYPES
    ]

    for source in rss_sources:
        items, skipped = fetch_rss_source(source, timezone_name)
        all_items.extend(items)
        total_skipped += skipped

    for source in html_sources:
        items, skipped = fetch_html_source(source, timezone_name)
        all_items.extend(items)
        total_skipped += skipped

    for source in unsupported_sources:
        logging.warning("Skipping unsupported source type: %s", source)
        total_skipped += 1

    # Bing News is intentionally last: it supplements original sources.
    for query_config in sources_config.get("bing_news_queries", []):
        if not isinstance(query_config, dict):
            logging.warning("Skipping malformed Bing News query: %s", query_config)
            total_skipped += 1
            continue
        items, skipped = fetch_bing_news_rss(query_config, timezone_name)
        all_items.extend(items)
        total_skipped += skipped

    logging.info("Fetched %s current-month candidates before deduplication.", len(all_items))
    logging.info(
        "Skipped %s entries due to missing fields, old dates, or unsupported config.",
        total_skipped,
    )
    _log_type_counts("Before deduplication", all_items)

    deduplicated = deduplicate_by_url(all_items)
    deduplicated.sort(
        key=lambda item: (
            str(item.get("published_date", "")),
            _preference_key(item),
        ),
        reverse=True,
    )
    limited = deduplicated[:max_candidates]

    logging.info("Remaining after URL/event deduplication: %s.", len(deduplicated))
    _log_type_counts("After deduplication", limited)
    if len(deduplicated) > max_candidates:
        logging.info("Limited candidates to max_news_candidates=%s.", max_candidates)

    if not limited and has_existing_items(OUTPUT_PATH):
        logging.warning("No new items fetched.")
        logging.warning("Reusing previous news_raw.json.")
        return

    if not limited:
        logging.warning("No new items fetched and no reusable previous news_raw.json exists.")

    save_json(limited, OUTPUT_PATH)
    logging.info("Saved %s raw candidates to %s.", len(limited), OUTPUT_PATH)


if __name__ == "__main__":
    main()

"""Rank analyzed news, select today's brief, and maintain publication state.

This stage reads analyzed news and backlog items, removes already published or
expired entries, calculates a deterministic final_score, selects the daily
brief, and updates today_selected.json, backlog.json, and published_urls.json.
It does not call DeepSeek, build the site, or push robot messages.
"""

from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
ANALYZED_NEWS_PATH = PROJECT_ROOT / "data" / "news_analyzed.json"
FILTERED_NEWS_PATH = PROJECT_ROOT / "data" / "news_filtered.json"
TODAY_SELECTED_PATH = PROJECT_ROOT / "data" / "today_selected.json"
BACKLOG_PATH = PROJECT_ROOT / "data" / "backlog.json"
PUBLISHED_URLS_PATH = PROJECT_ROOT / "data" / "published_urls.json"

DEFAULT_DAILY_PUBLISH_MIN = 3
DEFAULT_DAILY_PUBLISH_MAX = 8
DEFAULT_BACKLOG_MAX_SIZE = 300
DEFAULT_MAX_TITLE_SIMILARITY = 0.88
DEFAULT_MIN_FINAL_SCORE = 35
RELAXED_MIN_FINAL_SCORE = 25

DIVERSITY_CATEGORIES = [
    "电池与储能材料",
    "轻量化与结构材料",
    "复合材料",
    "热管理与安全材料",
    "电驱与电子材料",
    "可持续与循环材料",
    "先进制造工艺",
    "专利情报",
    "学术论文",
]

SIGNAL_KEYWORDS = [
    "mass production",
    "pilot production",
    "commercialization",
    "supply agreement",
    "factory",
    "plant",
    "investment",
    "patent",
    "standard",
    "regulation",
    "approval",
    "prototype",
    "roadmap",
    "paper",
    "journal",
    "量产",
    "试生产",
    "商业化",
    "供应协议",
    "工厂",
    "投资",
    "专利",
    "标准",
    "法规",
    "认证",
    "原型",
    "路线图",
    "论文",
    "期刊",
]


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load config and fill ranking defaults."""
    if not path.exists():
        logging.warning("Config file not found: %s; using defaults.", path)
        return {
            "timezone": "Asia/Shanghai",
            "limits": {
                "daily_publish_min": DEFAULT_DAILY_PUBLISH_MIN,
                "daily_publish_max": DEFAULT_DAILY_PUBLISH_MAX,
                "backlog_max_size": DEFAULT_BACKLOG_MAX_SIZE,
                "max_title_similarity": DEFAULT_MAX_TITLE_SIMILARITY,
            },
        }

    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    config.setdefault("timezone", "Asia/Shanghai")
    config.setdefault("limits", {})
    config["limits"].setdefault("daily_publish_min", DEFAULT_DAILY_PUBLISH_MIN)
    config["limits"].setdefault("daily_publish_max", DEFAULT_DAILY_PUBLISH_MAX)
    config["limits"].setdefault("backlog_max_size", DEFAULT_BACKLOG_MAX_SIZE)
    config["limits"].setdefault("max_title_similarity", DEFAULT_MAX_TITLE_SIMILARITY)
    return config


def load_json(path: Path) -> Any:
    """Load JSON from disk, returning an empty list for absent files."""
    if not path.exists():
        logging.warning("JSON file not found: %s", path)
        return []
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(data: Any, path: Path) -> None:
    """Save UTF-8 JSON with stable indentation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def is_current_month(date_value: str, timezone_name: str = "Asia/Shanghai") -> bool:
    """Return True when YYYY-MM-DD belongs to the configured current month."""
    try:
        published = datetime.strptime(str(date_value), "%Y-%m-%d").date()
    except ValueError:
        return False
    now = datetime.now(ZoneInfo(timezone_name)).date()
    return published.year == now.year and published.month == now.month


def normalize_url(url: str | None) -> str:
    """Normalize URL for publication deduplication."""
    if not url:
        return ""
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            urlencode(query, doseq=True),
            "",
        )
    )


def normalize_title(title: str | None) -> str:
    """Normalize title for similarity matching."""
    if not title:
        return ""
    text = str(title).casefold()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def priority_to_score(priority: str | None) -> int:
    """Map DeepSeek priority labels to ranking points."""
    return {"P0": 25, "P1": 18, "P2": 10, "P3": 4}.get(str(priority or "P3"), 4)


def _combined_text(item: dict[str, Any]) -> str:
    values = [
        item.get("title", ""),
        item.get("summary", ""),
        item.get("impact_assessment", ""),
        item.get("research_value", ""),
        " ".join(item.get("technical_points", []) or []),
        item.get("category", ""),
        item.get("subcategory", ""),
    ]
    return " ".join(str(value) for value in values if value)


def _signal_score(item: dict[str, Any]) -> int:
    text = normalize_title(_combined_text(item))
    matches = 0
    for keyword in SIGNAL_KEYWORDS:
        if normalize_title(keyword) in text:
            matches += 1
    return min(7, matches * 2)


def calculate_final_score(item: dict[str, Any], seen_categories: set[str] | None = None) -> int:
    """Calculate final_score in the 0-100 range."""
    raw_rule_score = item.get("rule_score")
    confidence = int(item.get("confidence", 0) or 0)
    source_score = int(item.get("source_score", 0) or 0)
    category = str(item.get("category") or "")

    if raw_rule_score is None:
        # Some fallback analyses intentionally contain only the required analysis
        # schema. In that case, derive a conservative ranking signal from
        # existing metadata instead of dropping every valid item to zero.
        materials = item.get("materials_involved", []) or []
        companies = item.get("companies_or_institutions", []) or []
        rule_points = 0
        if category and category != "其他":
            rule_points += 12
        rule_points += min(16, len(materials) * 4)
        rule_points += min(7, len(companies) * 3)
        rule_points = min(35, rule_points)
    else:
        rule_score = int(raw_rule_score or 0)
        rule_points = min(35, round(rule_score / 100 * 35))
    priority_points = priority_to_score(item.get("priority"))
    confidence_points = min(10, round(confidence / 100 * 10))
    follow_up_points = 8 if item.get("follow_up") else 0
    source_points = min(10, round(source_score / 100 * 10))
    signal_points = _signal_score(item)

    diversity_points = 0
    if seen_categories is not None and category in DIVERSITY_CATEGORIES and category not in seen_categories:
        diversity_points = 5

    return min(
        100,
        rule_points
        + priority_points
        + confidence_points
        + follow_up_points
        + source_points
        + signal_points
        + diversity_points,
    )


def _extract_backlog_items(backlog_data: Any) -> list[dict[str, Any]]:
    if isinstance(backlog_data, dict):
        items = backlog_data.get("items", [])
    else:
        items = backlog_data
    return [item for item in items if isinstance(item, dict)]


def _extract_published_records(published_data: Any) -> list[dict[str, Any]]:
    if isinstance(published_data, dict):
        records = published_data.get("published_urls", [])
    else:
        records = published_data
    if not isinstance(records, list):
        return []
    normalized_records: list[dict[str, Any]] = []
    for record in records:
        if isinstance(record, dict):
            normalized_records.append(record)
        elif isinstance(record, str):
            normalized_records.append({"url": record})
    return normalized_records


def merge_analyzed_and_backlog(
    analyzed_items: list[dict[str, Any]], backlog_data: Any
) -> tuple[list[dict[str, Any]], int]:
    """Merge current analyzed items with backlog items."""
    backlog_items = _extract_backlog_items(backlog_data)
    merged = [deepcopy(item) for item in analyzed_items if isinstance(item, dict)]
    merged.extend(deepcopy(item) for item in backlog_items)
    return merged, len(backlog_items)


def enrich_with_filtered_metadata(
    analyzed_items: list[dict[str, Any]], filtered_data: Any
) -> list[dict[str, Any]]:
    """Backfill rule/source metadata that DeepSeek fallback output may omit."""
    filtered_items = [item for item in filtered_data if isinstance(item, dict)] if isinstance(filtered_data, list) else []
    filtered_by_url = {
        normalize_url(item.get("url")): item
        for item in filtered_items
        if normalize_url(item.get("url"))
    }

    enriched: list[dict[str, Any]] = []
    for analyzed in analyzed_items:
        item = deepcopy(analyzed)
        filtered = filtered_by_url.get(normalize_url(item.get("url")))
        if filtered:
            for key in ("rule_score", "source_score", "source_type", "filter_reason"):
                if item.get(key) is None and filtered.get(key) is not None:
                    item[key] = filtered[key]
            if not item.get("materials_involved") and filtered.get("detected_material_keywords"):
                item["materials_involved"] = filtered["detected_material_keywords"]
            if not item.get("companies_or_institutions") and filtered.get("detected_companies"):
                item["companies_or_institutions"] = filtered["detected_companies"]
        enriched.append(item)

    return enriched


def remove_published_items(
    items: list[dict[str, Any]],
    published_data: Any,
    current_date: str | None = None,
    same_day_allowed_urls: set[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Remove items whose URL was published before the current run date.

    Same-day records are intentionally allowed so repeated workflow runs do not
    clear today's already selected page.
    """
    published_urls = {
        normalize_url(record.get("url"))
        for record in _extract_published_records(published_data)
        if normalize_url(record.get("url"))
        and (not current_date or record.get("selected_date") != current_date)
    }

    remaining: list[dict[str, Any]] = []
    removed = 0
    same_day_allowed_urls = same_day_allowed_urls or set()
    for item in items:
        url = normalize_url(item.get("url"))
        if url in same_day_allowed_urls:
            remaining.append(item)
            continue
        if url and url in published_urls:
            removed += 1
            continue
        remaining.append(item)
    return remaining, removed


def deduplicate_items(
    items: list[dict[str, Any]], max_title_similarity: float = DEFAULT_MAX_TITLE_SIMILARITY
) -> list[dict[str, Any]]:
    """Deduplicate by normalized URL and highly similar titles."""
    ranked = sorted(
        items,
        key=lambda item: (
            int(item.get("final_score", 0) or 0),
            int(item.get("rule_score", 0) or 0),
            item.get("published_date", ""),
        ),
        reverse=True,
    )
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    deduped: list[dict[str, Any]] = []

    for item in ranked:
        url = normalize_url(item.get("url"))
        title = normalize_title(item.get("title"))
        if not url or not title:
            continue
        if url in seen_urls:
            continue
        if any(SequenceMatcher(None, title, seen_title).ratio() >= max_title_similarity for seen_title in seen_titles):
            continue
        item["url"] = url
        seen_urls.add(url)
        seen_titles.append(title)
        deduped.append(item)

    return deduped


def _valid_item(item: dict[str, Any], timezone_name: str) -> bool:
    return bool(
        str(item.get("title") or "").strip()
        and normalize_url(item.get("url"))
        and str(item.get("published_date") or "").strip()
        and is_current_month(str(item.get("published_date")), timezone_name)
    )


def select_today_items(
    items: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Select today's publication items and return remaining valuable backlog."""
    limits = config.get("limits", {})
    timezone_name = config.get("timezone", "Asia/Shanghai")
    daily_min = int(limits.get("daily_publish_min", DEFAULT_DAILY_PUBLISH_MIN))
    daily_max = int(limits.get("daily_publish_max", DEFAULT_DAILY_PUBLISH_MAX))
    max_title_similarity = float(limits.get("max_title_similarity", DEFAULT_MAX_TITLE_SIMILARITY))

    valid: list[dict[str, Any]] = []
    removed_non_current = 0
    for item in items:
        if not _valid_item(item, timezone_name):
            removed_non_current += 1
            continue
        item = deepcopy(item)
        item["url"] = normalize_url(item.get("url"))
        item["final_score"] = calculate_final_score(item)
        valid.append(item)

    deduped = deduplicate_items(valid, max_title_similarity)
    deduped_count = len(deduped)

    strong = [item for item in deduped if int(item.get("final_score", 0)) >= DEFAULT_MIN_FINAL_SCORE]
    relaxed = [
        item
        for item in deduped
        if RELAXED_MIN_FINAL_SCORE <= int(item.get("final_score", 0)) < DEFAULT_MIN_FINAL_SCORE
    ]

    selected: list[dict[str, Any]] = []
    selected_urls: set[str] = set()
    seen_categories: set[str] = set()

    def add_item(item: dict[str, Any]) -> None:
        item = deepcopy(item)
        item["final_score"] = calculate_final_score(item, seen_categories)
        selected.append(item)
        selected_urls.add(item["url"])
        if item.get("category"):
            seen_categories.add(str(item.get("category")))

    for category in DIVERSITY_CATEGORIES:
        if len(selected) >= daily_max:
            break
        category_items = [
            item for item in strong if item.get("category") == category and item.get("url") not in selected_urls
        ]
        if category_items:
            add_item(category_items[0])

    for item in strong:
        if len(selected) >= daily_max:
            break
        if item.get("url") not in selected_urls:
            add_item(item)

    relaxed_used = 0
    forced_used = 0
    if len(selected) < daily_min:
        logging.warning(
            "High-quality news below daily_publish_min=%s; relaxing final_score threshold from %s to %s.",
            daily_min,
            DEFAULT_MIN_FINAL_SCORE,
            RELAXED_MIN_FINAL_SCORE,
        )
        for item in relaxed:
            if len(selected) >= daily_min or len(selected) >= daily_max:
                break
            if item.get("url") not in selected_urls:
                add_item(item)
                relaxed_used += 1

    if len(selected) < daily_min and deduped:
        logging.warning(
            "Candidate news exists but score thresholds are still too strict; selecting top-ranked candidates as fallback."
        )
        for item in deduped:
            if len(selected) >= daily_min or len(selected) >= daily_max:
                break
            if item.get("url") not in selected_urls:
                add_item(item)
                forced_used += 1

    if len(selected) < daily_min:
        logging.warning(
            "Only %s items selected, below daily_publish_min=%s because not enough valuable current-month news is available.",
            len(selected),
            daily_min,
        )

    selected.sort(key=lambda item: int(item.get("final_score", 0)), reverse=True)

    selected_at = datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")
    for item in selected:
        item["selected_at"] = selected_at

    selected_url_set = {item["url"] for item in selected}
    backlog_candidates = [
        item
        for item in deduped
        if item.get("url") not in selected_url_set
        and int(item.get("final_score", 0)) >= RELAXED_MIN_FINAL_SCORE
    ]

    stats = {
        "removed_non_current": removed_non_current,
        "deduped_count": deduped_count,
        "relaxed_used": relaxed_used,
        "forced_used": forced_used,
    }
    return selected, backlog_candidates, stats


def update_backlog(
    backlog_items: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Trim backlog to current-month valuable items and configured max size."""
    limits = config.get("limits", {})
    timezone_name = config.get("timezone", "Asia/Shanghai")
    max_size = int(limits.get("backlog_max_size", DEFAULT_BACKLOG_MAX_SIZE))
    max_title_similarity = float(limits.get("max_title_similarity", DEFAULT_MAX_TITLE_SIMILARITY))

    current_items = [item for item in backlog_items if _valid_item(item, timezone_name)]
    deduped = deduplicate_items(current_items, max_title_similarity)
    deduped.sort(
        key=lambda item: (
            int(item.get("final_score", 0) or 0),
            item.get("published_date", ""),
        ),
        reverse=True,
    )
    return {"items": deduped[:max_size]}


def update_published_urls(
    published_data: Any, selected_items: list[dict[str, Any]], selected_date: str
) -> dict[str, list[dict[str, Any]]]:
    """Append newly selected URLs to publication history."""
    records = _extract_published_records(published_data)
    seen_urls = {normalize_url(record.get("url")) for record in records if normalize_url(record.get("url"))}

    for item in selected_items:
        url = normalize_url(item.get("url"))
        if not url or url in seen_urls:
            continue
        records.append(
            {
                "url": url,
                "title": item.get("title", ""),
                "published_date": item.get("published_date", ""),
                "selected_date": selected_date,
                "category": item.get("category", ""),
            }
        )
        seen_urls.add(url)

    return {"published_urls": records}


def _existing_today_selection(today_data: Any, today: str, timezone_name: str) -> dict[str, Any] | None:
    """Return today's existing selection when it is still usable."""
    if not isinstance(today_data, dict) or today_data.get("date") != today:
        return None

    items = [
        item
        for item in today_data.get("items", [])
        if isinstance(item, dict) and _valid_item(item, timezone_name)
    ]
    if not items:
        return None

    payload = deepcopy(today_data)
    payload["items"] = items
    payload["count"] = len(items)
    return payload


def _same_selected_urls(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    """Return True when two selections contain the same URLs in the same order."""
    left_urls = [normalize_url(item.get("url")) for item in left]
    right_urls = [normalize_url(item.get("url")) for item in right]
    return bool(left_urls) and left_urls == right_urls


def _selection_url_set(selection: dict[str, Any] | None) -> set[str]:
    """Return normalized URLs from an existing today selection."""
    if not selection:
        return set()
    return {
        normalize_url(item.get("url"))
        for item in selection.get("items", [])
        if normalize_url(item.get("url"))
    }


def main() -> None:
    """Run ranking and daily publication selection."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = load_config()
    timezone_name = config.get("timezone", "Asia/Shanghai")
    today = datetime.now(ZoneInfo(timezone_name)).date().isoformat()

    existing_today_data = load_json(TODAY_SELECTED_PATH)
    existing_today = _existing_today_selection(existing_today_data, today, timezone_name)
    force_refresh = os.getenv("FORCE_REFRESH_TODAY", "").strip().lower() == "true"
    if existing_today and not force_refresh:
        logging.info("Today brief already exists; reuse existing selection.")
        return
    if existing_today and force_refresh:
        logging.warning("FORCE_REFRESH_TODAY=true; regenerating today's locked brief.")
        existing_today = None

    analyzed_data = load_json(ANALYZED_NEWS_PATH)
    filtered_data = load_json(FILTERED_NEWS_PATH)
    backlog_data = load_json(BACKLOG_PATH)
    published_data = load_json(PUBLISHED_URLS_PATH)

    analyzed_items = enrich_with_filtered_metadata(
        [item for item in analyzed_data if isinstance(item, dict)],
        filtered_data,
    )
    logging.info("Analyzed items read: %s.", len(analyzed_items))

    merged_items, backlog_count = merge_analyzed_and_backlog(analyzed_items, backlog_data)
    logging.info("Backlog items read: %s.", backlog_count)

    unpublished_items, removed_published = remove_published_items(
        merged_items,
        published_data,
        today,
        _selection_url_set(existing_today),
    )
    logging.info("Already published items removed: %s.", removed_published)

    selected_items, backlog_candidates, selection_stats = select_today_items(unpublished_items, config)
    logging.info("Non-current-month or invalid items removed: %s.", selection_stats["removed_non_current"])
    logging.info("Candidates after deduplication: %s.", selection_stats["deduped_count"])
    logging.info("Today selected items: %s.", len(selected_items))

    if selected_items and existing_today and _same_selected_urls(selected_items, existing_today["items"]):
        logging.info("Reusing existing today_selected.json because today's selected URLs are unchanged.")
        today_payload = existing_today
        published_items = existing_today["items"]
        save_today = False
    elif selected_items:
        today_payload = {
            "date": today,
            "count": len(selected_items),
            "items": selected_items,
        }
        published_items = selected_items
        save_today = True
    elif existing_today:
        logging.warning(
            "No new selected items generated; preserving existing today_selected.json for %s.",
            today,
        )
        today_payload = existing_today
        published_items = existing_today["items"]
        save_today = False
    else:
        today_payload = {
            "date": today,
            "count": 0,
            "items": [],
        }
        published_items = []
        save_today = True

    published_payload = update_published_urls(published_data, published_items, today)
    backlog_payload = update_backlog(backlog_candidates, config)

    if save_today:
        save_json(today_payload, TODAY_SELECTED_PATH)
    save_json(backlog_payload, BACKLOG_PATH)
    save_json(published_payload, PUBLISHED_URLS_PATH)

    logging.info("New backlog size: %s.", len(backlog_payload["items"]))
    logging.info("published_urls updated size: %s.", len(published_payload["published_urls"]))
    if save_today:
        logging.info("Saved today selection to %s.", TODAY_SELECTED_PATH)
    else:
        logging.info("Preserved existing today selection at %s.", TODAY_SELECTED_PATH)


if __name__ == "__main__":
    main()

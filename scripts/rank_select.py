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
import hashlib
from copy import deepcopy
from datetime import date, datetime
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
PUBLISHED_EVENTS_PATH = PROJECT_ROOT / "data" / "published_events.json"

DEFAULT_DAILY_PUBLISH_MIN = 5
DEFAULT_DAILY_PUBLISH_MAX = 10
DEFAULT_BACKLOG_MAX_SIZE = 300
DEFAULT_MAX_TITLE_SIMILARITY = 0.88
DEFAULT_MIN_FINAL_SCORE = 35
RELAXED_MIN_FINAL_SCORE = 25
DEFAULT_RECENT_PRIORITY_DAYS = 14
REFRESH_ANALYSIS_FIELDS = [
    "summary",
    "technical_points",
    "materials_involved",
    "companies_or_institutions",
    "impact_assessment",
    "research_value",
    "industrial_maturity",
    "priority",
    "confidence",
    "follow_up",
    "one_sentence",
    "why_it_matters",
    "technology_driver",
    "material_relevance",
    "material_opportunity",
    "validation_opportunity",
    "suggested_action",
    "trend_potential",
    "future_signal",
    "future_signal_score",
    "material_opportunity_score",
    "material_validation_score",
    "stage",
    "stage_reason",
    "analysis_status",
]

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

ALLOWED_SUGGESTED_ACTION = {
    "启动验证",
    "供应商调研",
    "持续跟踪",
    "前瞻储备",
    "暂不优先",
    "Technology Watch",
    "Supplier Research",
    "Joint Development",
    "Validation",
    "Strategic Reserve",
}
ALLOWED_TREND_POTENTIAL = {"高", "中", "低", "不确定"}
STAGE_MAP = {
    "持续跟踪": "Technology Watch",
    "暂不优先": "Technology Watch",
    "供应商调研": "Supplier Research",
    "联合开发": "Joint Development",
    "启动验证": "Validation",
    "前瞻储备": "Strategic Reserve",
}
TITLE_SUFFIX_PATTERN = re.compile(
    r"\s*[-_|]\s*(?:Yahoo|MSN|AOL|Reuters|Bloomberg|36Kr|36氪|盖世汽车|汽车之家|财联社|界面新闻|澎湃新闻|钛媒体)\s*$",
    re.IGNORECASE,
)


def _int_0_100(value: Any, default: int = 0) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = default
    return max(0, min(100, number))


def trend_to_score(trend: str | None) -> int:
    """Map trend potential to 0-100 scale for ranking."""
    return {"高": 100, "中": 70, "低": 35, "不确定": 45}.get(str(trend or "不确定"), 45)


def fallback_material_validation_score(item: dict[str, Any]) -> int:
    """Create a conservative material validation score if analysis omitted it."""
    score = 20
    score += min(25, len(item.get("materials_involved", []) or []) * 5)
    score += min(15, len(item.get("companies_or_institutions", []) or []) * 5)
    score += min(20, int(item.get("rule_score", 0) or 0) // 5)
    score += min(15, int(item.get("source_score", 0) or 0) // 7)
    if item.get("follow_up"):
        score += 10
    return max(0, min(100, score))


def fallback_future_signal_score(item: dict[str, Any]) -> int:
    """Create a conservative future-industry signal score if analysis omitted it."""
    score = 20
    score += min(20, int(item.get("source_score", 0) or 0) // 5)
    score += min(20, int(item.get("rule_score", 0) or 0) // 5)
    if item.get("trend_potential") == "高":
        score += 25
    elif item.get("trend_potential") == "中":
        score += 14
    elif item.get("trend_potential") == "低":
        score += 5
    if item.get("priority") in {"P0", "P1"}:
        score += 10
    return max(0, min(100, score))


def ensure_material_opportunity_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Ensure V2 technology-driver/material-opportunity fields exist."""
    current = deepcopy(item)
    if not str(current.get("why_it_matters") or "").strip():
        current["why_it_matters"] = str(
            current.get("impact_assessment")
            or current.get("research_value")
            or "信息不足，暂无法判断其产业或材料意义。"
        )
    if not str(current.get("technology_driver") or "").strip():
        current["technology_driver"] = "其他"
    if not str(current.get("material_relevance") or "").strip():
        current["material_relevance"] = "材料相关性较弱，暂不优先。"
    if not str(current.get("material_opportunity") or "").strip():
        current["material_opportunity"] = str(current.get("material_relevance") or "材料相关性较弱，暂不优先。")
    if not str(current.get("validation_opportunity") or "").strip():
        current["validation_opportunity"] = "材料相关性较弱，暂不优先。建议仅作为背景趋势观察，暂不进入样件验证或供应商调研。"
    if current.get("suggested_action") not in ALLOWED_SUGGESTED_ACTION:
        current["suggested_action"] = "暂不优先"
    if not str(current.get("stage") or "").strip():
        current["stage"] = STAGE_MAP.get(str(current.get("suggested_action")), current.get("suggested_action", "Technology Watch"))
    current["stage"] = STAGE_MAP.get(str(current.get("stage")), current.get("stage"))
    if current.get("stage") not in ALLOWED_SUGGESTED_ACTION:
        current["stage"] = "Technology Watch"
    if not str(current.get("stage_reason") or "").strip():
        current["stage_reason"] = "根据当前产业化、合作、验证和供应链信号进行生命周期阶段兜底判断。"
    if current.get("trend_potential") not in ALLOWED_TREND_POTENTIAL:
        current["trend_potential"] = "不确定"
    if not str(current.get("future_signal") or "").strip():
        current["future_signal"] = (
            f"{current.get('technology_driver', '其他')}方向释放{current.get('trend_potential', '不确定')}潜力信号，"
            "需继续观察产业化进展、标准政策和供应链投入。"
        )
    if current.get("future_signal_score") is None:
        current["future_signal_score"] = fallback_future_signal_score(current)
    else:
        current["future_signal_score"] = _int_0_100(current.get("future_signal_score"))
    if current.get("material_opportunity_score") is None:
        current["material_opportunity_score"] = current.get("material_validation_score")
    if current.get("material_validation_score") is None:
        current["material_validation_score"] = fallback_material_validation_score(current)
    else:
        current["material_validation_score"] = _int_0_100(current.get("material_validation_score"))
    current["material_opportunity_score"] = _int_0_100(
        current.get("material_opportunity_score", current["material_validation_score"])
    )
    return current


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
    config["limits"].setdefault("recent_priority_days", DEFAULT_RECENT_PRIORITY_DAYS)
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


def days_since_published(date_value: str, timezone_name: str = "Asia/Shanghai") -> int | None:
    """Return age in days for YYYY-MM-DD, or None if parsing fails."""
    try:
        published = datetime.strptime(str(date_value), "%Y-%m-%d").date()
    except ValueError:
        return None
    now = datetime.now(ZoneInfo(timezone_name)).date()
    return (now - published).days


def is_recent_item(item: dict[str, Any], recent_days: int, timezone_name: str) -> bool:
    """Return True if item is within the preferred recent update window."""
    age = days_since_published(str(item.get("published_date") or ""), timezone_name)
    return age is not None and 0 <= age <= recent_days


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
            "",
            urlencode(query, doseq=True),
            "",
        )
    )


def normalize_title(title: str | None) -> str:
    """Normalize title for similarity matching."""
    if not title:
        return ""
    text = TITLE_SUFFIX_PATTERN.sub("", str(title)).casefold()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    stopwords = {"the", "a", "an", "to", "of", "and", "for", "in", "on", "with", "as"}
    tokens = [token for token in re.sub(r"\s+", " ", text).strip().split() if token not in stopwords]
    return " ".join(tokens)


def event_id_for_item(item: dict[str, Any]) -> str:
    """Create stable event id from normalized title and material/company context."""
    if item.get("event_id"):
        return str(item["event_id"])
    companies = sorted(str(value).casefold() for value in item.get("companies_or_institutions", [])[:4])
    if not companies:
        companies = sorted(str(value).casefold() for value in item.get("detected_companies", [])[:4])
    materials = sorted(str(value).casefold() for value in item.get("materials_involved", [])[:5])
    if not materials:
        materials = sorted(str(value).casefold() for value in item.get("detected_material_keywords", [])[:5])
    base = "|".join(
        [
            normalize_title(item.get("title")),
            str(item.get("category") or ""),
            ",".join(companies),
            ",".join(materials),
        ]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


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
    """Calculate final_score in the 0-100 range with material-validation value."""
    raw_rule_score = item.get("rule_score")
    confidence = _int_0_100(item.get("confidence", 0))
    source_score = _int_0_100(item.get("source_score", 0))
    material_score = _int_0_100(
        item.get("material_opportunity_score", item.get("material_validation_score", fallback_material_validation_score(item)))
    )
    trend_score = _int_0_100(item.get("future_signal_score", trend_to_score(item.get("trend_potential"))))

    if raw_rule_score is None:
        rule_score = fallback_material_validation_score(item)
    else:
        rule_score = _int_0_100(raw_rule_score)

    priority_score = min(100, round(priority_to_score(item.get("priority")) / 25 * 100))
    total = (
        rule_score * 0.25
        + source_score * 0.15
        + priority_score * 0.15
        + confidence * 0.10
        + material_score * 0.25
        + trend_score * 0.10
    )

    if seen_categories is not None and item.get("category") in DIVERSITY_CATEGORIES and item.get("category") not in seen_categories:
        total += 3
    return min(100, round(total))


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


def _extract_published_events(events_data: Any) -> list[dict[str, Any]]:
    if isinstance(events_data, dict):
        events = events_data.get("events", [])
    else:
        events = events_data
    return [event for event in events if isinstance(event, dict)]


def _source_record(item: dict[str, Any]) -> dict[str, str]:
    return {
        "source": str(item.get("source") or ""),
        "url": normalize_url(item.get("url")),
        "published_date": str(item.get("published_date") or ""),
    }


def _is_similar_title(title_a: str, title_b: str, threshold: float) -> bool:
    if not title_a or not title_b:
        return False
    return SequenceMatcher(None, title_a, title_b).ratio() >= threshold


def cluster_events(items: list[dict[str, Any]], max_title_similarity: float) -> list[dict[str, Any]]:
    """Cluster same event across URLs/titles and keep the strongest primary item."""
    clusters: list[dict[str, Any]] = []
    for raw in items:
        item = deepcopy(raw)
        item["canonical_url"] = normalize_url(item.get("canonical_url") or item.get("url"))
        item["normalized_title"] = normalize_title(item.get("normalized_title") or item.get("title"))
        item["event_id"] = event_id_for_item(item)
        matched = None
        for cluster in clusters:
            if item["event_id"] == cluster["event_id"]:
                matched = cluster
                break
            if item["canonical_url"] and item["canonical_url"] in cluster["source_urls"]:
                matched = cluster
                break
            if _is_similar_title(item["normalized_title"], cluster["normalized_title"], max_title_similarity):
                matched = cluster
                break
        if not matched:
            clusters.append(
                {
                    "event_id": item["event_id"],
                    "normalized_title": item["normalized_title"],
                    "primary": item,
                    "items": [item],
                    "source_urls": {item["canonical_url"]},
                    "source_names": {str(item.get("source") or "")},
                }
            )
            continue
        matched["items"].append(item)
        matched["source_urls"].add(item["canonical_url"])
        matched["source_names"].add(str(item.get("source") or ""))
        if (
            int(item.get("source_score", 0) or 0),
            int(item.get("final_score", 0) or 0),
            str(item.get("published_date", "")),
        ) > (
            int(matched["primary"].get("source_score", 0) or 0),
            int(matched["primary"].get("final_score", 0) or 0),
            str(matched["primary"].get("published_date", "")),
        ):
            matched["primary"] = item

    merged = []
    for cluster in clusters:
        primary = deepcopy(cluster["primary"])
        related_sources = []
        for item in cluster["items"]:
            source = _source_record(item)
            if source["url"] and source not in related_sources:
                related_sources.append(source)
        primary["event_id"] = cluster["event_id"]
        primary["canonical_url"] = primary.get("canonical_url") or normalize_url(primary.get("url"))
        primary["normalized_title"] = cluster["normalized_title"]
        primary["related_sources"] = related_sources
        primary["source_urls"] = sorted(url for url in cluster["source_urls"] if url)
        primary["source_names"] = sorted(name for name in cluster["source_names"] if name)
        merged.append(primary)
    return merged


def update_published_events(
    events_data: Any,
    candidates: list[dict[str, Any]],
    selected_items: list[dict[str, Any]],
    current_date: str,
) -> dict[str, list[dict[str, Any]]]:
    """Maintain event-level publication state and source accumulation."""
    events = _extract_published_events(events_data)
    by_id = {str(event.get("event_id")): deepcopy(event) for event in events if event.get("event_id")}
    selected_ids = {event_id_for_item(item) for item in selected_items}
    for item in candidates:
        event_id = event_id_for_item(item)
        event = by_id.setdefault(
            event_id,
            {
                "event_id": event_id,
                "canonical_title": item.get("title", ""),
                "canonical_url": normalize_url(item.get("url")),
                "first_seen": current_date,
                "last_seen": current_date,
                "source_urls": [],
                "source_names": [],
                "topic_tags": [],
                "material_opportunities": [],
                "published": False,
            },
        )
        event["last_seen"] = current_date
        for url in [normalize_url(item.get("url")), *(item.get("source_urls", []) or [])]:
            if url and url not in event["source_urls"]:
                event["source_urls"].append(url)
        for name in [item.get("source"), *(item.get("source_names", []) or [])]:
            name = str(name or "")
            if name and name not in event["source_names"]:
                event["source_names"].append(name)
        for tag in [item.get("category"), item.get("subcategory"), item.get("technology_driver")]:
            tag = str(tag or "")
            if tag and tag not in event["topic_tags"]:
                event["topic_tags"].append(tag)
        opportunity = str(item.get("material_opportunity") or item.get("material_relevance") or "")
        if opportunity and opportunity not in event["material_opportunities"]:
            event["material_opportunities"].append(opportunity)
        if event_id in selected_ids:
            event["published"] = True
            event["canonical_title"] = item.get("title", event["canonical_title"])
            event["canonical_url"] = normalize_url(item.get("url")) or event["canonical_url"]

    ordered = sorted(by_id.values(), key=lambda event: str(event.get("last_seen", "")), reverse=True)
    return {"events": ordered}


def remove_published_event_items(
    items: list[dict[str, Any]],
    events_data: Any,
) -> tuple[list[dict[str, Any]], int]:
    """Remove candidates whose event has already been published before."""
    published_ids = {
        str(event.get("event_id"))
        for event in _extract_published_events(events_data)
        if event.get("event_id") and event.get("published", True)
    }
    remaining = []
    removed = 0
    for item in items:
        if event_id_for_item(item) in published_ids:
            removed += 1
            continue
        remaining.append(item)
    return remaining, removed


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
    weak_values = {
        "信息不足，暂无法判断其产业或材料意义。",
        "材料相关性较弱，暂不优先。",
        "未来信号不明确，建议仅作为背景观察。",
    }
    for analyzed in analyzed_items:
        item = deepcopy(analyzed)
        filtered = filtered_by_url.get(normalize_url(item.get("url")))
        if filtered:
            for key in (
                "rule_score",
                "source_score",
                "source_type",
                "filter_reason",
                "why_it_matters",
                "technology_driver",
                "material_relevance",
                "material_opportunity",
                "validation_opportunity",
                "suggested_action",
                "trend_potential",
                "future_signal",
                "future_signal_score",
                "material_opportunity_score",
                "material_validation_score",
                "stage",
                "stage_reason",
                "canonical_url",
                "normalized_title",
                "event_id",
            ):
                if item.get(key) is None and filtered.get(key) is not None:
                    item[key] = filtered[key]
                elif key == "technology_driver" and item.get(key) == "其他" and filtered.get(key) not in (None, "", "其他"):
                    item[key] = filtered[key]
                elif key in {"why_it_matters", "material_relevance", "material_opportunity", "validation_opportunity", "future_signal"}:
                    if str(item.get(key) or "").strip() in weak_values and filtered.get(key):
                        item[key] = filtered[key]
                elif key in {"future_signal_score", "material_opportunity_score", "material_validation_score"}:
                    try:
                        current_score = int(float(item.get(key, 0) or 0))
                        filtered_score = int(float(filtered.get(key, 0) or 0))
                    except (TypeError, ValueError):
                        current_score = 0
                        filtered_score = 0
                    if current_score == 0 and filtered_score > 0:
                        item[key] = filtered_score
            if not item.get("materials_involved") and filtered.get("detected_material_keywords"):
                item["materials_involved"] = filtered["detected_material_keywords"]
            if not item.get("companies_or_institutions") and filtered.get("detected_companies"):
                item["companies_or_institutions"] = filtered["detected_companies"]
        enriched.append(ensure_material_opportunity_fields(item))

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
        and record.get("selected_date")
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
            item.get("analysis_status") == "success",
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
    recent_days = int(limits.get("recent_priority_days", DEFAULT_RECENT_PRIORITY_DAYS))
    max_title_similarity = float(limits.get("max_title_similarity", DEFAULT_MAX_TITLE_SIMILARITY))

    valid: list[dict[str, Any]] = []
    removed_non_current = 0
    for item in items:
        if not _valid_item(item, timezone_name):
            removed_non_current += 1
            continue
        item = ensure_material_opportunity_fields(item)
        item["url"] = normalize_url(item.get("url"))
        item["canonical_url"] = normalize_url(item.get("canonical_url") or item.get("url"))
        item["normalized_title"] = normalize_title(item.get("normalized_title") or item.get("title"))
        item["event_id"] = event_id_for_item(item)
        item["final_score"] = calculate_final_score(item)
        valid.append(item)

    clustered = cluster_events(valid, max_title_similarity)
    deduped = deduplicate_items(clustered, max_title_similarity)
    deduped_count = len(deduped)

    strong = [item for item in deduped if int(item.get("final_score", 0)) >= DEFAULT_MIN_FINAL_SCORE]
    relaxed = [
        item
        for item in deduped
        if RELAXED_MIN_FINAL_SCORE <= int(item.get("final_score", 0)) < DEFAULT_MIN_FINAL_SCORE
    ]
    strong_recent = [item for item in strong if is_recent_item(item, recent_days, timezone_name)]
    strong_older = [item for item in strong if not is_recent_item(item, recent_days, timezone_name)]
    relaxed_recent = [item for item in relaxed if is_recent_item(item, recent_days, timezone_name)]

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
            item for item in strong_recent if item.get("category") == category and item.get("url") not in selected_urls
        ]
        if category_items:
            add_item(category_items[0])

    for item in strong_recent:
        if len(selected) >= daily_max:
            break
        if item.get("url") not in selected_urls:
            add_item(item)

    for item in strong_older:
        if len(selected) >= daily_max:
            break
        if item.get("url") not in selected_urls:
            add_item(item)

    relaxed_used = 0
    if len(selected) < daily_min:
        logging.warning(
            "High-quality news below daily_publish_min=%s; relaxing only recent candidates to threshold %s.",
            daily_min,
            RELAXED_MIN_FINAL_SCORE,
        )
        for item in relaxed_recent:
            if len(selected) >= daily_min or len(selected) >= daily_max:
                break
            if item.get("url") not in selected_urls:
                add_item(item)
                relaxed_used += 1

    if len(selected) < daily_min:
        logging.warning(
            "Only %s items selected, below daily_publish_min=%s; not filling with low-quality old news.",
            len(selected),
            daily_min,
        )

    selected.sort(
        key=lambda item: (
            item.get("analysis_status") == "success",
            int(item.get("final_score", 0)),
        ),
        reverse=True,
    )

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
        "forced_used": 0,
        "recent_priority_days": recent_days,
        "strong_recent_candidates": len(strong_recent),
        "strong_older_candidates": len(strong_older),
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


def _existing_today_selection(
    today_data: Any,
    today: str,
    timezone_name: str,
    allow_previous: bool = False,
) -> dict[str, Any] | None:
    """Return an existing selection when it is still usable.

    Normal runs lock today's selection. When no fresh candidates are available,
    allow_previous=True lets the workflow reuse an earlier same-month selection
    instead of clearing the brief.
    """
    if not isinstance(today_data, dict):
        return None
    selected_date = str(today_data.get("date") or "")
    if selected_date != today:
        if not allow_previous or not is_current_month(selected_date, timezone_name):
            return None
    try:
        count = int(today_data.get("count", 0) or 0)
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        logging.warning("Existing today_selected.json has count=0; treating it as invalid.")
        return None

    items = [
        item
        for item in today_data.get("items", [])
        if isinstance(item, dict) and _valid_item(item, timezone_name)
    ]
    if not items:
        logging.warning("Existing today_selected.json has no valid items; treating it as invalid.")
        return None

    payload = deepcopy(today_data)
    payload["items"] = items
    payload["count"] = len(items)
    if selected_date != today:
        payload["reused_from_date"] = selected_date
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


def _success_current_month_items(items: list[dict[str, Any]], timezone_name: str) -> list[dict[str, Any]]:
    """Return current-month items that already have successful analysis."""
    return [
        item
        for item in items
        if item.get("analysis_status") == "success" and _valid_item(item, timezone_name)
    ]


def refresh_existing_selection_with_success_analysis(
    selection: dict[str, Any], analyzed_data: Any
) -> tuple[dict[str, Any], int]:
    """Refresh locked selections with newer successful analysis by URL."""
    analyzed_items = [item for item in analyzed_data if isinstance(item, dict)] if isinstance(analyzed_data, list) else []
    success_by_url = {
        normalize_url(item.get("url")): item
        for item in analyzed_items
        if normalize_url(item.get("url")) and item.get("analysis_status") == "success"
    }

    refreshed = deepcopy(selection)
    refreshed_items: list[dict[str, Any]] = []
    refreshed_count = 0
    for original in selection.get("items", []):
        item = deepcopy(original)
        latest = success_by_url.get(normalize_url(item.get("url")))
        missing_refresh_field = any(item.get(field) in (None, "") for field in REFRESH_ANALYSIS_FIELDS)
        changed_refresh_field = latest and any(
            field in latest and item.get(field) != latest.get(field)
            for field in REFRESH_ANALYSIS_FIELDS
        )
        if latest and (item.get("analysis_status") != "success" or missing_refresh_field or changed_refresh_field):
            for field in REFRESH_ANALYSIS_FIELDS:
                if field in latest:
                    item[field] = latest[field]
            refreshed_count += 1
        refreshed_items.append(item)

    refreshed["items"] = refreshed_items
    refreshed["count"] = len(refreshed_items)
    return refreshed, refreshed_count


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
    reusable_previous_selection = _existing_today_selection(
        existing_today_data,
        today,
        timezone_name,
        allow_previous=True,
    )
    force_refresh = os.getenv("FORCE_REFRESH_TODAY", "").strip().lower() == "true"
    analyzed_data = load_json(ANALYZED_NEWS_PATH)
    filtered_data = load_json(FILTERED_NEWS_PATH)
    published_events_data = load_json(PUBLISHED_EVENTS_PATH)
    analyzed_items = enrich_with_filtered_metadata(
        [item for item in analyzed_data if isinstance(item, dict)],
        filtered_data,
    )
    success_items = _success_current_month_items(analyzed_items, timezone_name)
    if reusable_previous_selection:
        reusable_previous_selection, _ = refresh_existing_selection_with_success_analysis(
            reusable_previous_selection,
            analyzed_data,
        )

    if existing_today and not force_refresh:
        refreshed_today, refreshed_count = refresh_existing_selection_with_success_analysis(
            existing_today,
            analyzed_data,
        )
        daily_max = int(config.get("limits", {}).get("daily_publish_max", DEFAULT_DAILY_PUBLISH_MAX))
        should_expand_from_success = (
            len(success_items) >= daily_max
            and len(refreshed_today.get("items", [])) < daily_max
        )
        still_has_non_success = any(
            item.get("analysis_status") != "success"
            for item in refreshed_today.get("items", [])
        )
        if not should_expand_from_success and not still_has_non_success:
            published_events_payload = update_published_events(
                published_events_data,
                refreshed_today.get("items", []),
                refreshed_today.get("items", []),
                today,
            )
            save_json(published_events_payload, PUBLISHED_EVENTS_PATH)
            if refreshed_count:
                save_json(refreshed_today, TODAY_SELECTED_PATH)
                logging.info(
                    "Today brief already exists; refreshed %s locked items with latest success analysis.",
                    refreshed_count,
                )
            else:
                logging.info("Today brief already exists; reuse existing selection.")
            return
        logging.info(
            "Success analyses are available; regenerating locked brief from success items to reach daily_publish_max=%s.",
            daily_max,
        )
        existing_today = None
    if existing_today and force_refresh:
        logging.warning("FORCE_REFRESH_TODAY=true; regenerating today's locked brief.")
        existing_today = None

    backlog_data = load_json(BACKLOG_PATH)
    published_data = load_json(PUBLISHED_URLS_PATH)
    logging.info("Analyzed items read: %s.", len(analyzed_items))

    selection_source_items = success_items if len(success_items) >= int(config.get("limits", {}).get("daily_publish_max", DEFAULT_DAILY_PUBLISH_MAX)) else analyzed_items
    merged_items, backlog_count = merge_analyzed_and_backlog(selection_source_items, backlog_data)
    logging.info("Backlog items read: %s.", backlog_count)

    unpublished_items, removed_published = remove_published_items(
        merged_items,
        published_data,
        today,
        _selection_url_set(existing_today),
    )
    logging.info("Already published items removed: %s.", removed_published)
    unpublished_items, removed_events = remove_published_event_items(unpublished_items, published_events_data)
    logging.info("Already published event items removed: %s.", removed_events)

    selected_items, backlog_candidates, selection_stats = select_today_items(unpublished_items, config)
    if not selected_items and merged_items:
        logging.warning(
            "No items selected after published URL filtering; retrying from analyzed/backlog candidates while preserving event filtering."
        )
        retry_items, retry_removed_events = remove_published_event_items(merged_items, published_events_data)
        logging.info("Already published event items removed during retry: %s.", retry_removed_events)
        selected_items, backlog_candidates, selection_stats = select_today_items(retry_items, config)
    logging.info("Non-current-month or invalid items removed: %s.", selection_stats["removed_non_current"])
    logging.info("Candidates after deduplication: %s.", selection_stats["deduped_count"])
    logging.info("Today selected items: %s.", len(selected_items))

    daily_min = int(config.get("limits", {}).get("daily_publish_min", DEFAULT_DAILY_PUBLISH_MIN))
    if (
        selected_items
        and len(selected_items) < daily_min
        and reusable_previous_selection
        and len(reusable_previous_selection.get("items", [])) >= len(selected_items)
    ):
        logging.warning(
            "Only %s new items selected, below daily_publish_min=%s; reusing previous selection from %s.",
            len(selected_items),
            daily_min,
            reusable_previous_selection.get("date", "unknown"),
        )
        selected_items = []

    preserve_auxiliary_state = False

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
        preserve_auxiliary_state = True
    elif reusable_previous_selection:
        logging.warning(
            "No new selected items generated; reusing previous selection from %s.",
            reusable_previous_selection.get("date", "unknown"),
        )
        today_payload = reusable_previous_selection
        published_items = reusable_previous_selection["items"]
        save_today = True
        preserve_auxiliary_state = True
    else:
        logging.warning(
            "No selected items and no reusable previous today_selected.json; writing empty selection as last resort."
        )
        today_payload = {
            "date": today,
            "count": 0,
            "items": [],
        }
        published_items = []
        save_today = True

    if preserve_auxiliary_state:
        logging.warning("Preserving backlog.json and published_urls.json while reusing an existing selection.")
        published_payload = published_data
        published_events_payload = published_events_data
        backlog_payload = backlog_data
    else:
        published_payload = update_published_urls(published_data, published_items, today)
        event_candidates = cluster_events(
            [item for item in analyzed_items if _valid_item(item, timezone_name)],
            float(config.get("limits", {}).get("max_title_similarity", DEFAULT_MAX_TITLE_SIMILARITY)),
        )
        published_events_payload = update_published_events(
            published_events_data,
            event_candidates,
            published_items,
            today,
        )
        backlog_payload = update_backlog(backlog_candidates, config)

    if save_today:
        save_json(today_payload, TODAY_SELECTED_PATH)
    if not preserve_auxiliary_state:
        save_json(backlog_payload, BACKLOG_PATH)
        save_json(published_payload, PUBLISHED_URLS_PATH)
        save_json(published_events_payload, PUBLISHED_EVENTS_PATH)

    logging.info("Backlog size: %s.", len(_extract_backlog_items(backlog_payload)))
    logging.info("published_urls size: %s.", len(_extract_published_records(published_payload)))
    logging.info("published_events size: %s.", len(_extract_published_events(published_events_payload)))
    if save_today:
        logging.info("Saved today selection to %s.", TODAY_SELECTED_PATH)
    else:
        logging.info("Preserved existing today selection at %s.", TODAY_SELECTED_PATH)


if __name__ == "__main__":
    main()

"""Build the AURA static website.

This stage renders GitHub Pages-ready HTML under docs/ from existing pipeline
data. It does not fetch news, call DeepSeek, alter ranking, or push robots.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DOCS_DIR = PROJECT_ROOT / "docs"
ASSETS_DIR = DOCS_DIR / "assets"
DAILY_DIR = DOCS_DIR / "daily"
MONTHLY_DIR = DOCS_DIR / "monthly"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

TODAY_SELECTED_PATH = DATA_DIR / "today_selected.json"
PUBLISHED_URLS_PATH = DATA_DIR / "published_urls.json"
ANALYZED_NEWS_PATH = DATA_DIR / "news_analyzed.json"
BACKLOG_PATH = DATA_DIR / "backlog.json"
INSIGHTS_PATH = DATA_DIR / "insights.json"
STATISTICS_PATH = ASSETS_DIR / "statistics.json"
METHODOLOGY_PATH = DOCS_DIR / "about-methodology.html"
BRAND_EN = "AURA"
BRAND_CN = "未来产业、技术与材料情报平台"
BRAND_FULL_EN = "Advanced Understanding of Research & Applications"

CATEGORY_COLORS = {
    "汽车新材料": "#6B8E6E",
    "电池与储能": "#4F8A5B",
    "企业技术动态": "#6D8F6F",
    "机器人与具身智能": "#8D7AB8",
    "低空经济": "#5F8FA8",
    "专利与论文": "#7A6F9B",
    "未来趋势观察": "#C8A45A",
    "电池与储能材料": "#6B8E6E",
    "轻量化与结构材料": "#C97B63",
    "复合材料": "#B08968",
    "智能与功能材料": "#8D7AB8",
    "热管理与安全材料": "#D96C5F",
    "电驱与电子材料": "#4A6FA5",
    "可持续与循环材料": "#4F8A5B",
    "先进制造工艺": "#C8A45A",
    "专利情报": "#7A6F9B",
    "学术论文": "#5F8FA8",
    "政策法规与标准": "#607D8B",
    "企业技术动态": "#6D8F6F",
    "其他": "#6B7280",
}

NAV_CATEGORIES = [
    {"name": "汽车新材料", "anchor": "category-auto-materials"},
    {"name": "电池与储能", "anchor": "category-battery-storage"},
    {"name": "企业技术动态", "anchor": "category-company-tech"},
    {"name": "机器人与具身智能", "anchor": "category-robotics"},
    {"name": "低空经济", "anchor": "category-low-altitude"},
    {"name": "专利与论文", "anchor": "category-patents-papers"},
    {"name": "未来趋势观察", "anchor": "category-future-trends"},
]

AUTO_CATEGORY_RULES = [
    (
        "汽车新材料",
        [
            "固态电池",
            "钠离子电池",
            "锂金属",
            "硅碳负极",
            "电解质",
            "隔膜",
            "导热材料",
            "气凝胶",
            "热管理",
            "碳纤维",
            "cfrp",
            "复合材料",
            "镁合金",
            "铝合金",
            "高强钢",
            "sic",
            "gan",
        ],
    ),
    ("电池与储能", ["battery", "energy storage", "catl", "lges", "samsung sdi", "panasonic"]),
    ("企业技术动态", ["toyota", "honda", "byd", "tesla", "bosch", "denso", "bmw", "mercedes"]),
    (
        "机器人与具身智能",
        ["humanoid", "embodied ai", "robot", "optimus", "figure ai", "unitree", "agility"],
    ),
    ("低空经济", ["evtol", "flying car", "archer", "joby", "亿航", "小鹏汇天"]),
    ("专利与论文", ["patent", "journal", "paper", "nature", "science", "ieee", "sae"]),
]

RESEARCH_DIRECTIONS = [
    {"name": "电池材料", "key": "battery-materials", "keywords": ["battery", "电池", "钠离子", "固态", "电解质", "隔膜", "负极"]},
    {"name": "轻量化材料", "key": "lightweight-materials", "keywords": ["轻量化", "铝合金", "镁合金", "高强钢", "lightweight"]},
    {"name": "热管理材料", "key": "thermal-materials", "keywords": ["热管理", "导热", "气凝胶", "thermal", "aerogel"]},
    {"name": "功率半导体材料", "key": "power-semiconductor", "keywords": ["sic", "gan", "semiconductor", "功率半导体"]},
    {"name": "复合材料", "key": "composites", "keywords": ["复合材料", "碳纤维", "cfrp", "composite"]},
    {"name": "机器人材料", "key": "robotics-materials", "keywords": ["robot", "humanoid", "具身智能", "机器人"]},
    {"name": "低空飞行材料", "key": "low-altitude-materials", "keywords": ["evtol", "flying car", "低空", "飞行汽车", "航空"]},
]

ACTION_ORDER = ["启动验证", "供应商调研", "持续跟踪", "前瞻储备", "暂不优先"]
STRATEGIC_COMPANIES = [
    "Toyota",
    "Honda",
    "Nissan",
    "Tesla",
    "BYD",
    "CATL",
    "LG Energy Solution",
    "Samsung SDI",
    "Panasonic Energy",
    "Bosch",
    "Denso",
    "BMW",
    "Mercedes-Benz",
    "Volkswagen",
    "Hyundai",
    "Kia",
]
MATERIAL_TRACKS = [
    ("电池与储能材料", ["battery", "电池", "储能", "钠离子", "固态", "电解质", "隔膜", "负极"]),
    ("热管理材料", ["thermal", "热管理", "导热", "气凝胶"]),
    ("轻量化材料", ["lightweight", "轻量化", "铝合金", "镁合金", "高强钢"]),
    ("复合材料", ["composite", "复合材料", "碳纤维", "cfrp"]),
    ("功率半导体材料", ["sic", "gan", "power semiconductor", "功率半导体"]),
    ("电驱材料", ["motor", "电驱", "永磁", "rare earth"]),
    ("光学与感知材料", ["optical", "lidar", "infrared", "红外", "感知"]),
    ("可持续材料", ["recycling", "回收", "低碳", "sustainable"]),
]
DEFAULT_OPPORTUNITY_FIELDS = {
    "why_it_matters": "信息不足，暂无法判断其产业或材料意义。",
    "technology_driver": "其他",
    "material_relevance": "材料相关性较弱，暂不优先。",
    "material_opportunity": "材料相关性较弱，暂不优先。",
    "validation_opportunity": "材料相关性较弱，暂不优先。建议仅作为背景趋势观察，暂不进入样件验证或供应商调研。",
    "suggested_action": "暂不优先",
    "trend_potential": "不确定",
    "future_signal": "未来信号不明确，建议仅作为背景观察。",
    "future_signal_score": 0,
    "material_opportunity_score": 0,
    "material_validation_score": 0,
}

FOCUS_CATEGORY_ORDER = [
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

VALIDATION_VALUE_CATEGORY_BONUS = {
    "电池与储能材料",
    "轻量化与结构材料",
    "复合材料",
    "热管理与安全材料",
    "电驱与电子材料",
    "先进制造工艺",
    "专利情报",
    "学术论文",
}

METRIC_EXPLANATIONS = {
    "credibility": {
        "title": "可信度",
        "body": "用于衡量信息来源与内容可靠程度。主要参考来源权威性、是否来自原始发布方、是否有发布日期、是否有可打开原文链接、是否为转载或线索来源。可信度是研究判断的入口，不等同于技术一定成立。",
    },
    "trl": {
        "title": "TRL 技术成熟度",
        "body": "TRL 是 Technology Readiness Level，技术成熟度等级。1-3 通常代表实验室研究，4-6 代表工程验证，7-8 代表装车或量产前验证，9 代表已量产应用。本系统会优先使用新闻中的明确 TRL 字段；缺失时根据产业成熟度做粗略映射。",
    },
    "import_difficulty": {
        "title": "导入难度",
        "body": "用于判断该技术进入企业内部验证流程的难易程度。低表示已有成熟供应链或量产案例；中表示已有样件或中试；高表示仍处于实验室或早期概念阶段。它不是采购建议，而是帮助研究员安排验证优先级。",
    },
    "validation_value": {
        "title": "验证价值",
        "body": "用于判断是否值得材料科室关注、样件评估或供应商调研。星级越高，越值得进入跟踪或验证列表。当前星级由 Final Score、优先级、是否值得跟踪和材料/技术分类共同粗略生成。",
    },
    "final_score": {
        "title": "Final Score",
        "body": "综合推荐指数，由规则评分、来源权威性、优先级、可信度、Material Opportunity Score 和 Future Signal Score 综合得到，用于排序，不代表绝对结论。研究员仍需结合原文、供应链可得性和内部项目需求判断。",
    },
    "priority": {
        "title": "优先级 P0/P1/P2/P3",
        "body": "P0：重大产业化、政策、量产、头部企业核心突破。P1：重要技术进展、专利、论文、供应链合作。P2：普通企业动态或趋势新闻。P3：相关性较弱但可观察。",
    },
    "source_tier": {
        "title": "来源等级",
        "body": "来源等级用于判断信息离原始事实的距离。Tier A 包括企业官网、政府、协会和期刊；Tier B 为专业媒体；Tier C 为聚合平台或转载源；Tier D 为线索来源，需要进一步核验。",
    },
    "material_validation_score": {
        "title": "Material Opportunity Score",
        "body": "材料机会分衡量这条新闻对材料团队的价值，重点看是否可能形成材料需求、是否值得验证、是否值得供应商调研或长期储备。它不是新闻热度分。",
    },
    "future_signal_score": {
        "title": "Future Signal Score",
        "body": "Future Signal Score 衡量未来产业影响力，参考技术突破、产业化进展、政策推动、资本投入、标准制定和供应链变化。它用于判断某个方向是否可能从趋势变成真实产业牵引。",
    },
}


def load_json(path: Path, default: Any) -> Any:
    """Load JSON from disk, returning default when absent or invalid."""
    if not path.exists():
        logging.warning("JSON file not found: %s", path)
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        logging.warning("Failed to parse JSON %s: %s", path, exc)
        return default


def save_json(data: Any, path: Path) -> None:
    """Save UTF-8 JSON with readable indentation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def ensure_dirs() -> None:
    """Ensure docs output directories exist."""
    for path in (DOCS_DIR, ASSETS_DIR, DAILY_DIR, MONTHLY_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _as_items(data: Any, key: str = "items") -> list[dict[str, Any]]:
    if isinstance(data, dict):
        items = data.get(key, [])
    else:
        items = data
    return [item for item in items if isinstance(item, dict)]


def load_insights(path: Path = INSIGHTS_PATH) -> list[dict[str, str]]:
    """Load static curated insight articles for the homepage."""
    data = load_json(path, {"items": []})
    items = data.get("items", data) if isinstance(data, dict) else data
    normalized: list[dict[str, str]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if not title or not url:
            continue
        normalized.append(
            {
                "title": title,
                "why_read": str(item.get("why_read") or "帮助理解变化背后的原因。").strip(),
                "focus": str(item.get("focus") or "关注技术变化如何转化为材料需求。").strip(),
                "reading_time": str(item.get("reading_time") or "约 10 分钟").strip(),
                "url": url,
            }
        )
    return normalized[:6]


def _combined_item_text(item: dict[str, Any]) -> str:
    values: list[str] = [
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
        str(item.get("category") or ""),
        str(item.get("subcategory") or ""),
        str(item.get("source") or ""),
    ]
    for key in ("materials_involved", "companies_or_institutions", "technical_points"):
        values.extend(str(value) for value in item.get(key, []) or [])
    return " ".join(values).casefold()


def auto_category(item: dict[str, Any]) -> str:
    """Classify a news item into the V2 researcher navigation taxonomy."""
    text = _combined_item_text(item)
    for category, keywords in AUTO_CATEGORY_RULES:
        if any(keyword.casefold() in text for keyword in keywords):
            return category
    return "未来趋势观察"


def research_direction_keys(item: dict[str, Any]) -> list[str]:
    """Return research direction keys matched by item text."""
    text = _combined_item_text(item)
    matched = [
        direction["key"]
        for direction in RESEARCH_DIRECTIONS
        if any(keyword.casefold() in text for keyword in direction["keywords"])
    ]
    return matched or ["future-watch"]


def source_tier(item: dict[str, Any]) -> str:
    """Map source metadata to Tier A/B/C/D."""
    source_type = str(item.get("source_type") or "").lower()
    credibility = str(item.get("credibility_level") or "").lower()
    url = str(item.get("url") or "").lower()
    source = str(item.get("source") or "").lower()
    repost_domains = ("msn.com", "aol.com", "yahoo.com")

    if source_type == "clue_platform" or credibility == "clue":
        return "D"
    if source_type == "bing_news" or any(domain in url for domain in repost_domains) or any(name in source for name in ("msn", "aol", "yahoo")):
        return "C"
    if source_type == "professional_media":
        return "B"
    if source_type in {"rss", "journal_rss", "company_news_page", "government_policy"}:
        return "A"
    if credibility == "high":
        return "A"
    if credibility == "medium":
        return "B"
    return "C"


def _tier_rank(tier: str) -> int:
    return {"A": 4, "B": 3, "C": 2, "D": 1}.get(tier, 0)


def _normalized_event_key(item: dict[str, Any]) -> str:
    """Build a coarse event key for deduplication."""
    text = " ".join(
        [
            str(item.get("title") or ""),
            " ".join(str(company) for company in item.get("companies_or_institutions", []) or []),
        ]
    ).casefold()
    text = re.sub(r"\b(msn|aol|yahoo|insideevs|bing news)\b", " ", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
    return text[:96] or str(item.get("url") or "")


def _related_source(item: dict[str, Any]) -> dict[str, str]:
    return {
        "source": str(item.get("source") or "unknown"),
        "url": str(item.get("url") or ""),
        "source_tier": str(item.get("source_tier") or source_tier(item)),
    }


def _preferred_item(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Choose the item closest to the original source."""
    left_key = (
        _tier_rank(str(left.get("source_tier") or source_tier(left))),
        1 if left.get("original_source_preferred") else 0,
        int(left.get("source_score", 0) or 0),
        int(left.get("final_score", 0) or 0),
    )
    right_key = (
        _tier_rank(str(right.get("source_tier") or source_tier(right))),
        1 if right.get("original_source_preferred") else 0,
        int(right.get("source_score", 0) or 0),
        int(right.get("final_score", 0) or 0),
    )
    return left if left_key >= right_key else right


def deduplicate_for_display(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate display items by event, keeping original/high-tier sources first."""
    by_event: dict[str, dict[str, Any]] = {}
    for item in items:
        key = _normalized_event_key(item)
        existing = by_event.get(key)
        if not existing:
            by_event[key] = item
            continue

        preferred = _preferred_item(existing, item)
        duplicate = item if preferred is existing else existing
        related = preferred.setdefault("related_sources", [])
        duplicate_source = _related_source(duplicate)
        if duplicate_source["url"] != preferred.get("url") and duplicate_source not in related:
            related.append(duplicate_source)
        for related_source in duplicate.get("related_sources", []) or []:
            if related_source.get("url") != preferred.get("url") and related_source not in related:
                related.append(related_source)
        by_event[key] = preferred

    return list(by_event.values())


def prepare_display_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepare non-mutating page items with category, tier, filters, and metrics."""
    prepared: list[dict[str, Any]] = []
    for item in items:
        current = dict(item)
        for key, value in DEFAULT_OPPORTUNITY_FIELDS.items():
            if current.get(key) in (None, ""):
                current[key] = value
        if not str(current.get("material_opportunity") or "").strip():
            current["material_opportunity"] = current.get("material_relevance", "材料相关性较弱，暂不优先。")
        if not str(current.get("why_it_matters") or "").strip():
            current["why_it_matters"] = current.get("impact_assessment", "信息不足，暂无法判断其产业或材料意义。")
        if not str(current.get("future_signal") or "").strip():
            current["future_signal"] = (
                f"{current.get('technology_driver', '其他')}方向释放{current.get('trend_potential', '不确定')}潜力信号，"
                "需继续观察产业化进展、标准政策和供应链投入。"
            )
        try:
            current["material_validation_score"] = max(0, min(100, int(float(current.get("material_validation_score", 0)))))
        except (TypeError, ValueError):
            current["material_validation_score"] = 0
        try:
            current["material_opportunity_score"] = max(0, min(100, int(float(current.get("material_opportunity_score", current["material_validation_score"])))))
        except (TypeError, ValueError):
            current["material_opportunity_score"] = current["material_validation_score"]
        try:
            current["future_signal_score"] = max(0, min(100, int(float(current.get("future_signal_score", 0)))))
        except (TypeError, ValueError):
            current["future_signal_score"] = 0
        if current.get("suggested_action") == "观察储备":
            current["suggested_action"] = "前瞻储备"
        if current.get("suggested_action") not in ACTION_ORDER:
            current["suggested_action"] = "暂不优先"
        if current.get("trend_potential") not in {"高", "中", "低", "不确定"}:
            current["trend_potential"] = "不确定"
        current["original_category"] = current.get("category", "")
        current["category"] = auto_category(current)
        current["source_tier"] = source_tier(current)
        current["research_directions"] = research_direction_keys(current)
        current["research_direction_attr"] = " ".join(current["research_directions"])
        prepared.append(current)
    deduped = deduplicate_for_display(prepared)
    return enrich_research_evaluation(deduped)


def _item_text_for_tracks(item: dict[str, Any]) -> str:
    return _combined_item_text(item)


def build_material_track_summary(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build Automotive & Advanced Materials track counts."""
    summary = []
    for name, keywords in MATERIAL_TRACKS:
        matched = [
            item for item in items
            if any(keyword.casefold() in _item_text_for_tracks(item) for keyword in keywords)
        ]
        validation_count = sum(1 for item in matched if item.get("suggested_action") in {"启动验证", "供应商调研"})
        summary.append({"name": name, "count": len(matched), "validation_count": validation_count})
    return summary


def build_company_intelligence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Count strategic companies appearing in selected intelligence."""
    rows = []
    for company in STRATEGIC_COMPANIES:
        matched = [
            item for item in items
            if company.casefold() in _combined_item_text(item)
        ]
        if matched:
            rows.append({"company": company, "count": len(matched)})
    return rows


def build_patents_research(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group patents, papers, standards, roadmaps, and industrialization progress."""
    groups = {
        "论文": ["paper", "journal", "nature", "science", "论文", "期刊"],
        "专利": ["patent", "专利"],
        "标准": ["standard", "sae", "ieee", "标准"],
        "技术路线": ["roadmap", "路线图", "architecture", "platform"],
        "产业化进展": ["production", "commercialization", "量产", "商业化", "pilot"],
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for label, keywords in groups.items():
        result[label] = [
            item for item in items
            if any(keyword.casefold() in _combined_item_text(item) for keyword in keywords)
        ]
    return result


def build_future_radar(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build dynamic future technology radar, capped as a supporting module."""
    future_items = [
        item for item in items
        if item.get("technology_driver") not in {"电池与储能", "功率半导体"}
        or int(item.get("future_signal_score", 0) or 0) >= 65
    ]
    counter: Counter[str] = Counter(item.get("technology_driver", "其他") for item in future_items)
    return [
        {
            "driver": driver,
            "count": count,
            "avg_future_signal_score": round(
                sum(int(item.get("future_signal_score", 0) or 0) for item in future_items if item.get("technology_driver") == driver) / count
            ) if count else 0,
        }
        for driver, count in counter.most_common()
    ][:6]


def build_technology_hotspots(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build dynamic technology-driver hotspots from today's selected items."""
    counter: Counter[str] = Counter()
    score_totals: Counter[str] = Counter()
    for item in items:
        driver = str(item.get("technology_driver") or "其他")
        counter[driver] += 1
        score_totals[driver] += int(item.get("material_opportunity_score", item.get("material_validation_score", 0)) or 0)

    hotspots = []
    for driver, count in counter.most_common():
        hotspots.append(
            {
                "driver": driver,
                "count": count,
                "avg_material_opportunity_score": round(score_totals[driver] / count) if count else 0,
            }
        )
    return hotspots


def build_validation_pool(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group items by suggested material-team action."""
    groups = []
    for action in ACTION_ORDER:
        action_items = [
            item
            for item in items
            if item.get("suggested_action") == action
        ]
        action_items.sort(
            key=lambda item: int(item.get("material_opportunity_score", item.get("material_validation_score", 0)) or 0),
            reverse=True,
        )
        groups.append({"action": action, "items": action_items, "count": len(action_items)})
    return groups


def build_category_sections(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group prepared items by V2 navigation category."""
    sections: list[dict[str, Any]] = []
    for nav in NAV_CATEGORIES:
        section_items = [item for item in items if item.get("category") == nav["name"]]
        sections.append({**nav, "items": section_items, "count": len(section_items)})
    return sections


def _top(counter: Counter[str], limit: int | None = None) -> dict[str, int]:
    pairs = counter.most_common(limit)
    return {key: value for key, value in pairs if key}


def build_statistics(
    today_items: list[dict[str, Any]],
    analyzed_items: list[dict[str, Any]],
    backlog_items: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Build category, source, company, and material keyword statistics."""
    corpus = today_items or analyzed_items
    extended_corpus = list(corpus) + backlog_items

    category_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    company_counts: Counter[str] = Counter()
    keyword_counts: Counter[str] = Counter()

    for item in extended_corpus:
        if item.get("category"):
            category_counts[str(item["category"])] += 1
        if item.get("source"):
            source_counts[str(item["source"])] += 1

        companies = item.get("companies_or_institutions") or item.get("detected_companies") or []
        for company in companies:
            if company:
                company_counts[str(company)] += 1

        keywords = item.get("materials_involved") or item.get("detected_material_keywords") or []
        for keyword in keywords:
            if keyword:
                keyword_counts[str(keyword)] += 1

    return {
        "category_counts": _top(category_counts),
        "source_counts": _top(source_counts),
        "company_counts": _top(company_counts, 10),
        "keyword_counts": _top(keyword_counts, 20),
    }


def build_research_insight(items: list[dict[str, Any]], statistics: dict[str, dict[str, int]]) -> str:
    """Generate a 3-5 sentence researcher morning brief from selected data only."""
    if not items:
        return "今日暂无达到发布条件的未来产业、技术与材料情报。系统不会为了填充版面而生成虚假判断。建议继续关注当月候选池变化，并优先补充高可信来源。"

    categories = list(statistics.get("category_counts", {}).keys())[:3]
    companies = list(statistics.get("company_counts", {}).keys())[:4]
    keywords = list(statistics.get("keyword_counts", {}).keys())[:5]
    drivers = Counter(str(item.get("technology_driver") or "其他") for item in items)
    top_driver = drivers.most_common(1)[0][0] if drivers else "其他"
    top_opportunity = max(
        items,
        key=lambda item: int(item.get("material_opportunity_score", item.get("material_validation_score", 0)) or 0),
    )
    top_score = int(top_opportunity.get("material_opportunity_score", top_opportunity.get("material_validation_score", 0)) or 0)

    sentences: list[str] = []
    if categories:
        sentences.append(f"今日最重要的产业变化集中在{'、'.join(categories)}方向，汽车产业与新能源汽车链条仍是主要观察重心。")
    sentences.append(f"今日最明显的技术牵引来自{top_driver}，需要判断它是否会继续传导为结构、热管理、电池、感知或封装材料需求。")
    sentences.append(f"材料机会最突出的线索是“{top_opportunity.get('title', '未命名情报')}”，Material Opportunity Score 为 {top_score}，建议结合原文判断是否进入验证或供应商调研。")
    if keywords:
        sentences.append(f"高频材料关键词包括{'、'.join(keywords)}，可作为今日样件验证、技术储备或竞品跟踪的入口。")
    if companies:
        sentences.append(f"涉及企业/机构以{'、'.join(companies)}等为主，后续应重点跟踪其量产、合作、专利、标准化或供应链变化。")

    return "".join(sentences[:5])


def credibility_label(item: dict[str, Any]) -> str:
    """Map confidence/source metadata to a readable credibility label."""
    level = str(item.get("credibility_level") or "").lower()
    if level == "high":
        return "高"
    if level == "medium":
        return "中"
    if level in {"low", "clue"}:
        return "低"

    confidence = item.get("confidence")
    try:
        confidence_value = int(confidence)
    except (TypeError, ValueError):
        return "待验证"
    if confidence_value >= 80:
        return "高"
    if confidence_value >= 60:
        return "中"
    return "低"


def trl_value(item: dict[str, Any]) -> str:
    """Return explicit TRL or a coarse mapping from industrial_maturity."""
    explicit = item.get("trl") or item.get("TRL")
    if explicit not in (None, ""):
        try:
            number = int(explicit)
        except (TypeError, ValueError):
            return "unknown"
        if 1 <= number <= 9:
            return str(number)
        return "unknown"

    maturity = str(item.get("industrial_maturity") or "").lower()
    if any(token in maturity for token in ("lab", "laboratory", "实验室", "基础研究")):
        return "1-3"
    if any(token in maturity for token in ("pilot", "prototype", "中试", "样件", "工程验证")):
        return "4-6"
    if any(token in maturity for token in ("production", "mass", "量产", "装车", "商业化")):
        return "8-9"
    return "unknown"


def import_difficulty(item: dict[str, Any], trl: str) -> str:
    """Estimate enterprise introduction difficulty from maturity signals."""
    maturity = str(item.get("industrial_maturity") or "").lower()
    if any(token in maturity for token in ("production", "mass", "market", "量产", "市场", "商业化")):
        return "低"
    if any(token in maturity for token in ("pilot", "prototype", "中试", "样件", "工程验证")):
        return "中"
    if any(token in maturity for token in ("lab", "unknown", "实验室", "基础研究")):
        return "高"
    if trl in {"8", "9", "8-9"}:
        return "低"
    if trl in {"4", "5", "6", "4-6", "7"}:
        return "中"
    if trl in {"1", "2", "3", "1-3"}:
        return "高"
    return "待评估"


def validation_stars(item: dict[str, Any]) -> tuple[int, str]:
    """Calculate a 1-5 validation value star score."""
    priority = str(item.get("priority") or "").upper()
    final_score = int(item.get("final_score", 0) or 0)

    if priority == "P0" or (item.get("follow_up") and final_score >= 70):
        stars = 5
    elif priority == "P1":
        stars = 4
    elif priority == "P2":
        stars = 3
    elif priority == "P3":
        stars = 2
    else:
        stars = 1

    if final_score >= 80:
        stars = max(stars, 5)
    elif final_score >= 65:
        stars = max(stars, 4)
    elif final_score >= 45:
        stars = max(stars, 3)

    if item.get("follow_up"):
        stars = min(5, stars + 1)
    if item.get("category") in VALIDATION_VALUE_CATEGORY_BONUS:
        stars = min(5, stars + 1)

    return stars, "★" * stars + "☆" * (5 - stars)


def suggested_action(
    item: dict[str, Any],
    credibility: str,
    trl: str,
    difficulty: str,
    stars: int,
) -> str:
    """Suggest a researcher action from derived indicators."""
    if credibility == "低" and item.get("source_type") == "clue_platform":
        return "暂不优先"
    if stars >= 4 and difficulty in {"低", "中"}:
        return "启动验证"
    if item.get("follow_up") or str(item.get("priority") or "").upper() in {"P0", "P1"}:
        return "持续跟踪"
    if trl in {"1", "2", "3", "1-3"}:
        return "前瞻储备"
    return "暂不优先"


def enrich_research_evaluation(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach researcher-facing evaluation fields to each news item."""
    enriched: list[dict[str, Any]] = []
    for item in items:
        current = dict(item)
        credibility = credibility_label(current)
        trl = trl_value(current)
        difficulty = import_difficulty(current, trl)
        stars, star_label = validation_stars(current)
        action = suggested_action(current, credibility, trl, difficulty, stars)
        current["research_eval"] = {
            "credibility": credibility,
            "trl": trl,
            "import_difficulty": difficulty,
            "validation_stars": stars,
            "validation_value": star_label,
            "suggested_action": action,
        }
        enriched.append(current)
    return enriched


def _published_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        records = data.get("published_urls", [])
    else:
        records = data
    normalized = []
    for record in records if isinstance(records, list) else []:
        if isinstance(record, dict):
            normalized.append(record)
        elif isinstance(record, str):
            normalized.append({"url": record})
    return normalized


def collect_archive_data(
    today_payload: dict[str, Any], published_data: Any
) -> dict[str, list[dict[str, str]]]:
    """Collect recent daily and monthly archive links from published records."""
    today = today_payload.get("date") or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    dates = {today}
    months = {today[:7]}

    for record in _published_records(published_data):
        selected_date = str(record.get("selected_date") or "")
        if len(selected_date) >= 10:
            dates.add(selected_date[:10])
            months.add(selected_date[:7])

    daily = [
        {"date": date, "href": f"daily/{date}.html"}
        for date in sorted(dates, reverse=True)[:30]
    ]
    monthly = [
        {"month": month, "href": f"monthly/{month}.html"}
        for month in sorted(months, reverse=True)[:12]
    ]
    return {"daily": daily, "monthly": monthly}


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["json"] = lambda value: json.dumps(value, ensure_ascii=False)
    return env


def generate_index_page(
    env: Environment,
    today_payload: dict[str, Any],
    display_items: list[dict[str, Any]],
    category_sections: list[dict[str, Any]],
    technology_hotspots: list[dict[str, Any]],
    validation_pool: list[dict[str, Any]],
    material_tracks: list[dict[str, Any]],
    company_intelligence: list[dict[str, Any]],
    patents_research: dict[str, list[dict[str, Any]]],
    future_radar: list[dict[str, Any]],
    insights: list[dict[str, str]],
    statistics: dict[str, dict[str, int]],
    insight: str,
    archives: dict[str, list[dict[str, str]]],
) -> None:
    """Render docs/index.html."""
    template = env.get_template("index.html.j2")
    html = template.render(
        brand_en=BRAND_EN,
        brand_cn=BRAND_CN,
        brand_full_en=BRAND_FULL_EN,
        date=today_payload.get("date", ""),
        items=display_items,
        category_sections=category_sections,
        nav_categories=NAV_CATEGORIES,
        research_directions=RESEARCH_DIRECTIONS,
        technology_hotspots=technology_hotspots,
        validation_pool=validation_pool,
        material_tracks=material_tracks,
        company_intelligence=company_intelligence,
        patents_research=patents_research,
        future_radar=future_radar,
        insights=insights,
        count=len(display_items),
        statistics=statistics,
        insight=insight,
        archives=archives,
        category_colors=CATEGORY_COLORS,
        metric_explanations=METRIC_EXPLANATIONS,
        methodology_href="about-methodology.html",
        asset_prefix="assets",
        root_prefix=".",
    )
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")


def generate_daily_page(
    env: Environment,
    today_payload: dict[str, Any],
    display_items: list[dict[str, Any]],
    statistics: dict[str, dict[str, int]],
    insight: str,
    archives: dict[str, list[dict[str, str]]],
) -> Path:
    """Render docs/daily/YYYY-MM-DD.html."""
    date = today_payload.get("date") or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    template = env.get_template("daily.html.j2")
    html = template.render(
        brand_en=BRAND_EN,
        brand_cn=BRAND_CN,
        brand_full_en=BRAND_FULL_EN,
        date=date,
        items=display_items,
        count=len(display_items),
        statistics=statistics,
        insight=insight,
        archives=archives,
        category_colors=CATEGORY_COLORS,
        metric_explanations=METRIC_EXPLANATIONS,
        methodology_href="../about-methodology.html",
        asset_prefix="../assets",
        root_prefix="..",
    )
    output = DAILY_DIR / f"{date}.html"
    output.write_text(html, encoding="utf-8")
    return output


def generate_monthly_page(
    env: Environment,
    today_payload: dict[str, Any],
    display_items: list[dict[str, Any]],
    statistics: dict[str, dict[str, int]],
    archives: dict[str, list[dict[str, str]]],
) -> Path:
    """Render docs/monthly/YYYY-MM.html."""
    date = today_payload.get("date") or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    month = date[:7]
    month_items = [item for item in display_items if str(item.get("published_date", "")).startswith(month)]
    template = env.get_template("monthly.html.j2")
    html = template.render(
        brand_en=BRAND_EN,
        brand_cn=BRAND_CN,
        brand_full_en=BRAND_FULL_EN,
        month=month,
        items=month_items,
        count=len(month_items),
        statistics=statistics,
        archives=archives,
        category_colors=CATEGORY_COLORS,
        metric_explanations=METRIC_EXPLANATIONS,
        methodology_href="../about-methodology.html",
        asset_prefix="../assets",
        root_prefix="..",
    )
    output = MONTHLY_DIR / f"{month}.html"
    output.write_text(html, encoding="utf-8")
    return output


def generate_methodology_page(env: Environment) -> Path:
    """Render docs/about-methodology.html."""
    template = env.get_template("about_methodology.html.j2")
    html = template.render(
        brand_en=BRAND_EN,
        brand_cn=BRAND_CN,
        brand_full_en=BRAND_FULL_EN,
        root_prefix=".",
    )
    METHODOLOGY_PATH.write_text(html, encoding="utf-8")
    return METHODOLOGY_PATH


def main() -> None:
    """Build all static site artifacts."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ensure_dirs()
    today_payload = load_json(TODAY_SELECTED_PATH, {"date": "", "count": 0, "items": []})
    published_data = load_json(PUBLISHED_URLS_PATH, {"published_urls": []})
    analyzed_items = _as_items(load_json(ANALYZED_NEWS_PATH, []))
    backlog_items = _as_items(load_json(BACKLOG_PATH, {"items": []}))
    insights = load_insights()
    today_items = _as_items(today_payload)

    if not today_items:
        logging.warning("today_selected.json has no items; preserving existing site files.")
        logging.warning("Skipping static site generation to avoid publishing an empty homepage.")
        return

    display_items = prepare_display_items(today_items)
    category_sections = build_category_sections(display_items)
    technology_hotspots = build_technology_hotspots(display_items)
    validation_pool = build_validation_pool(display_items)
    material_tracks = build_material_track_summary(display_items)
    company_intelligence = build_company_intelligence(display_items)
    patents_research = build_patents_research(display_items)
    future_radar = build_future_radar(display_items)
    statistics = build_statistics(display_items, analyzed_items, backlog_items)
    insight = build_research_insight(display_items, statistics)
    archives = collect_archive_data(today_payload, published_data)
    save_json(statistics, STATISTICS_PATH)

    env = _env()
    generate_index_page(
        env,
        today_payload,
        display_items,
        category_sections,
        technology_hotspots,
        validation_pool,
        material_tracks,
        company_intelligence,
        patents_research,
        future_radar,
        insights,
        statistics,
        insight,
        archives,
    )
    daily_path = generate_daily_page(env, today_payload, display_items, statistics, insight, archives)
    monthly_path = generate_monthly_page(env, today_payload, display_items, statistics, archives)
    methodology_path = generate_methodology_page(env)

    logging.info("Generated docs/index.html.")
    logging.info("Generated %s.", daily_path)
    logging.info("Generated %s.", monthly_path)
    logging.info("Generated %s.", STATISTICS_PATH)
    logging.info("Generated %s.", methodology_path)


if __name__ == "__main__":
    main()

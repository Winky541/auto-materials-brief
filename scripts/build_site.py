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
OPPORTUNITIES_PATH = ASSETS_DIR / "opportunities.json"
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

ACTION_ORDER = ["启动验证", "供应商调研", "持续跟踪", "联合开发", "前瞻储备", "暂不优先"]
ACTION_LABELS = {
    "持续跟踪": {"en": "Technology Watch", "zh": "持续观察", "pipeline": "Technology Watch"},
    "供应商调研": {"en": "Supplier Research", "zh": "供应商调研", "pipeline": "Supplier Research"},
    "启动验证": {"en": "Lab Evaluation", "zh": "实验验证", "pipeline": "Lab Evaluation"},
    "联合开发": {"en": "Joint Development", "zh": "联合开发", "pipeline": "Joint Development"},
    "前瞻储备": {"en": "Strategic Reserve", "zh": "战略储备", "pipeline": "Strategic Reserve"},
    "暂不优先": {"en": "Technology Watch", "zh": "持续观察", "pipeline": "Early Exploration"},
}
PIPELINE_ORDER = [
    "Early Exploration",
    "Technology Watch",
    "Supplier Research",
    "Lab Evaluation",
    "Joint Development",
    "Strategic Reserve",
]
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
    "SK On",
    "GM",
    "Ford",
]
OPPORTUNITY_DOMAINS = [
    {
        "domain": "Energy Systems",
        "zh": "电池、储能、氢能与车网互动材料机会",
        "keywords": ["battery", "电池", "储能", "钠离子", "固态", "电解质", "隔膜", "负极", "hydrogen", "燃料电池", "v2g"],
    },
    {
        "domain": "Structural Materials",
        "zh": "轻量化、复合材料、车身与飞行结构材料机会",
        "keywords": ["lightweight", "轻量化", "铝合金", "镁合金", "高强钢", "composite", "复合材料", "碳纤维", "cfrp", "结构材料"],
    },
    {
        "domain": "Thermal & Safety",
        "zh": "热管理、阻燃、防火隔热与安全防护材料机会",
        "keywords": ["thermal", "热管理", "导热", "气凝胶", "阻燃", "thermal runaway", "安全", "防火"],
    },
    {
        "domain": "Sensing & Functional Materials",
        "zh": "传感、光学、红外、智能与功能材料机会",
        "keywords": ["sensor", "传感", "optical", "lidar", "infrared", "红外", "swir", "感知", "functional", "柔性"],
    },
    {
        "domain": "Electronics & Power",
        "zh": "SiC/GaN、封装、绝缘、功率模块与电驱材料机会",
        "keywords": ["sic", "gan", "power semiconductor", "功率半导体", "封装", "绝缘", "银烧结", "电驱", "motor"],
    },
    {
        "domain": "Manufacturing & Process",
        "zh": "增材制造、连接、涂层、表面工程与工艺材料机会",
        "keywords": ["manufacturing", "制造", "3d printing", "增材", "coating", "涂层", "焊接", "结构胶"],
    },
    {
        "domain": "Sustainability",
        "zh": "回收、低碳、替代材料与循环材料机会",
        "keywords": ["recycling", "回收", "低碳", "sustainable", "bio-based", "生物基", "替代", "循环"],
    },
]
OPPORTUNITY_TOPIC_RULES = [
    ("Solid-State Electrolytes", "Energy Systems", ["solid-state", "固态", "electrolyte", "电解质"]),
    ("Sodium-Ion Battery Materials", "Energy Systems", ["sodium-ion", "钠离子", "sodium battery"]),
    ("Battery Thermal Management Materials", "Thermal & Safety", ["battery", "电池", "thermal", "热管理", "导热"]),
    ("Thermal Runaway Protection", "Thermal & Safety", ["thermal runaway", "热失控", "阻燃", "防火"]),
    ("Advanced Packaging Materials", "Electronics & Power", ["sic", "gan", "封装", "银烧结", "power module"]),
    ("Power Semiconductor Substrates", "Electronics & Power", ["sic", "gan", "功率半导体", "substrate"]),
    ("Robot Structural Materials", "Structural Materials", ["robot", "humanoid", "机器人", "具身", "结构材料"]),
    ("Flexible Sensing Materials", "Sensing & Functional Materials", ["flexible", "柔性", "sensor", "传感"]),
    ("Low-cost SWIR Materials", "Sensing & Functional Materials", ["swir", "infrared", "红外", "短波"]),
    ("eVTOL Composites", "Structural Materials", ["evtol", "flying car", "低空", "飞行汽车", "carbon fiber", "碳纤维"]),
    ("Advanced Coating Materials", "Manufacturing & Process", ["coating", "涂层", "surface", "表面"]),
    ("Bio-based Interior Materials", "Sustainability", ["bio-based", "生物基", "interior", "内饰"]),
    ("Recycling & Circular Battery Materials", "Sustainability", ["recycling", "回收", "battery", "电池"]),
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
    "material_value": {
        "title": "Material Value",
        "body": "Material Value 是某个材料机会主题的综合价值分，来自相关新闻中的 Material Opportunity Score。它用于判断这个主题是否值得材料团队投入注意力、供应商调研或样件验证，不代表商业成功概率。",
    },
    "validation_priority": {
        "title": "Validation Priority",
        "body": "Validation Priority 是材料机会主题的验证优先级。High 通常表示近期值得进入验证或供应商调研；Medium 表示需要持续跟踪并等待更多产业化信号；Low 表示仍偏早期或证据不足。",
    },
    "suggested_action": {
        "title": "Suggested Action",
        "body": "Suggested Action 是给材料科室的下一步动作建议。Technology Watch 表示持续观察；Supplier Research 表示调研供应商和样件可得性；Lab Evaluation 表示可考虑实验验证；Joint Development 表示适合联合开发；Strategic Reserve 表示适合前瞻储备。",
    },
    "material_opportunity": {
        "title": "Material Opportunity",
        "body": "Material Opportunity 说明这条产业或技术信号可能牵引出的材料需求，例如电池材料、热管理材料、复合材料、功能材料、封装材料或可持续材料。它强调材料团队能否从新闻中找到可行动的机会。",
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
    for key in ("technology_driver", "material_relevance", "material_opportunity", "validation_opportunity", "future_signal"):
        values.append(str(item.get(key) or ""))
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
        action_meta = action_label(current.get("suggested_action"))
        current["suggested_action_en"] = action_meta["en"]
        current["suggested_action_zh"] = action_meta["zh"]
        current["pipeline_status"] = action_meta["pipeline"]
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


def action_label(action: str | None) -> dict[str, str]:
    """Return normalized bilingual suggested action metadata."""
    return ACTION_LABELS.get(str(action or ""), ACTION_LABELS["暂不优先"])


def validation_priority(score: int) -> str:
    """Map material value score to validation priority."""
    if score >= 70:
        return "High"
    if score >= 45:
        return "Medium"
    return "Low"


def domain_for_text(text: str) -> str:
    """Map combined text to one of the fixed opportunity domains."""
    folded = text.casefold()
    for domain in OPPORTUNITY_DOMAINS:
        if any(keyword.casefold() in folded for keyword in domain["keywords"]):
            return domain["domain"]
    return "Energy Systems"


def topic_for_item(item: dict[str, Any]) -> tuple[str, str]:
    """Generate a material-opportunity-first topic for an item."""
    text = _combined_item_text(item)
    for topic, domain, keywords in OPPORTUNITY_TOPIC_RULES:
        if any(keyword.casefold() in text for keyword in keywords):
            return topic, domain

    materials = [str(value) for value in item.get("materials_involved", []) or [] if value]
    if materials:
        material = materials[0].strip()
        if material:
            return f"{material.title()} Materials", domain_for_text(text)

    return "Emerging Material Opportunity", domain_for_text(text)


def _related_signal(item: dict[str, Any]) -> dict[str, str]:
    return {
        "title": str(item.get("title") or "Untitled"),
        "url": str(item.get("url") or ""),
        "source": str(item.get("source") or ""),
        "published_date": str(item.get("published_date") or ""),
    }


def build_opportunity_topics(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build dynamic material opportunity topics from selected items."""
    topic_map: dict[str, dict[str, Any]] = {}
    for item in items:
        topic, domain = topic_for_item(item)
        score = int(item.get("material_opportunity_score", item.get("material_validation_score", 0)) or 0)
        entry = topic_map.setdefault(
            topic,
            {
                "topic": topic,
                "domain": domain,
                "material_value": 0,
                "validation_priority": "Low",
                "suggested_action": action_label(item.get("suggested_action"))["en"],
                "suggested_action_zh": action_label(item.get("suggested_action"))["zh"],
                "related_signals": [],
                "news_count": 0,
            },
        )
        entry["material_value"] = max(entry["material_value"], score)
        if score >= entry["material_value"]:
            entry["suggested_action"] = action_label(item.get("suggested_action"))["en"]
            entry["suggested_action_zh"] = action_label(item.get("suggested_action"))["zh"]
        entry["related_signals"].append(_related_signal(item))
        entry["news_count"] += 1

    topics = list(topic_map.values())
    for topic in topics:
        topic["validation_priority"] = validation_priority(int(topic["material_value"] or 0))
        topic["related_signals"] = topic["related_signals"][:4]
    topics.sort(key=lambda row: (int(row["material_value"]), row["news_count"]), reverse=True)
    return topics


def build_opportunity_domains(items: list[dict[str, Any]], topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build fixed opportunity domain summary for the homepage."""
    summary = []
    topic_counts = Counter(topic["domain"] for topic in topics)
    for domain in OPPORTUNITY_DOMAINS:
        matched = [item for item in items if any(keyword.casefold() in _item_text_for_tracks(item) for keyword in domain["keywords"])]
        summary.append(
            {
                "domain": domain["domain"],
                "zh": domain["zh"],
                "news_count": len(matched),
                "topic_count": topic_counts.get(domain["domain"], 0),
            }
        )
    return summary


def build_emerging_topics(
    topics: list[dict[str, Any]],
    existing_archive: dict[str, Any],
    current_date: str,
) -> list[dict[str, Any]]:
    """Return topics that first appear today or do not exist in the archive yet."""
    previous = existing_archive.get("topics", []) if isinstance(existing_archive, dict) else []
    previous_by_topic = {str(item.get("topic")): item for item in previous if isinstance(item, dict)}
    emerging = []
    for topic in topics:
        archived = previous_by_topic.get(topic["topic"])
        if not archived or archived.get("first_seen") == current_date:
            emerging.append({**topic, "is_new": True})
    return emerging[:6]


def build_opportunity_archive(
    topics: list[dict[str, Any]],
    existing_archive: dict[str, Any],
    current_date: str,
) -> dict[str, Any]:
    """Build docs/assets/opportunities.json while preserving first_seen dates."""
    previous = existing_archive.get("topics", []) if isinstance(existing_archive, dict) else []
    previous_by_topic = {str(item.get("topic")): item for item in previous if isinstance(item, dict)}
    archived_topics = []
    for topic in topics:
        previous_topic = previous_by_topic.get(topic["topic"], {})
        archived_topics.append(
            {
                "domain": topic["domain"],
                "topic": topic["topic"],
                "material_value": topic["material_value"],
                "validation_priority": topic["validation_priority"],
                "suggested_action": topic["suggested_action"],
                "suggested_action_zh": topic["suggested_action_zh"],
                "related_signals": topic["related_signals"],
                "news_count": topic["news_count"],
                "first_seen": previous_topic.get("first_seen", current_date),
                "updated_at": current_date,
            }
        )
    return {"updated_at": current_date, "topics": archived_topics}


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
        "Patents": ["patent", "专利"],
        "Research Papers": ["paper", "journal", "nature", "science", "论文", "期刊"],
        "Standards": ["standard", "sae", "ieee", "标准"],
        "Roadmaps": ["roadmap", "路线图", "architecture", "platform"],
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for label, keywords in groups.items():
        result[label] = [
            item for item in items
            if any(keyword.casefold() in _combined_item_text(item) for keyword in keywords)
        ]
    return result


def build_future_radar(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build future technology radar as signal categories, not opportunity topics."""
    rules = [
        ("Humanoid Robotics", ["humanoid", "robot", "机器人", "具身"]),
        ("Low-altitude Economy", ["evtol", "flying car", "低空", "飞行汽车"]),
        ("AI Hardware", ["ai hardware", "chip", "算力", "硬件"]),
        ("Autonomous Driving", ["autonomous", "adas", "自动驾驶", "智能驾驶"]),
        ("Smart Manufacturing", ["manufacturing", "制造", "3d printing", "增材"]),
        ("Hydrogen Systems", ["hydrogen", "fuel cell", "氢能", "燃料电池"]),
        ("Advanced Sensing", ["sensor", "lidar", "infrared", "swir", "感知", "红外"]),
    ]
    rows = []
    for category, keywords in rules:
        matched = [item for item in items if any(keyword.casefold() in _combined_item_text(item) for keyword in keywords)]
        if matched:
            rows.append(
                {
                    "category": category,
                    "count": len(matched),
                    "avg_future_signal_score": round(
                        sum(int(item.get("future_signal_score", 0) or 0) for item in matched) / len(matched)
                    ),
                }
            )
    rows.sort(key=lambda row: (row["avg_future_signal_score"], row["count"]), reverse=True)
    return rows[:7]


def build_validation_pool(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group items by suggested material-team action."""
    grouped: dict[str, list[dict[str, Any]]] = {status: [] for status in PIPELINE_ORDER}
    for item in items:
        grouped[action_label(item.get("suggested_action"))["pipeline"]].append(item)

    groups = []
    for action in PIPELINE_ORDER:
        action_items = [
            item
            for item in grouped[action]
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


def build_research_insight_cards(items: list[dict[str, Any]], statistics: dict[str, dict[str, int]]) -> list[dict[str, str]]:
    """Build structured Research Insight blocks for the homepage."""
    if not items:
        return [
            {"label": "What Changed", "text": "No publishable intelligence item is available today."},
            {"label": "Why It Matters", "text": "AURA will not invent signals when source evidence is insufficient."},
            {"label": "Material Opportunity", "text": "Keep watching the monthly candidate pool and strengthen authoritative sources."},
            {"label": "Suggested Action", "text": "Technology Watch"},
        ]

    drivers = Counter(str(item.get("technology_driver") or "Other") for item in items)
    top_driver = drivers.most_common(1)[0][0]
    top_item = max(items, key=lambda item: int(item.get("material_opportunity_score", 0) or 0))
    action = action_label(top_item.get("suggested_action"))
    categories = " / ".join(list(statistics.get("category_counts", {}).keys())[:3]) or "current selected signals"
    return [
        {"label": "What Changed", "text": f"Signals are concentrated in {categories}, with {top_driver} as the strongest technology driver."},
        {"label": "Why It Matters", "text": str(top_item.get("why_it_matters") or top_item.get("impact_assessment") or "This signal may affect material selection and validation planning.")},
        {"label": "Material Opportunity", "text": str(top_item.get("material_opportunity") or top_item.get("material_relevance") or "Material opportunity is still weak and should be watched conservatively.")},
        {"label": "Suggested Action", "text": f"{action['en']} / {action['zh']}"},
    ]


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
    validation_pool: list[dict[str, Any]],
    opportunity_domains: list[dict[str, Any]],
    opportunity_topics: list[dict[str, Any]],
    emerging_topics: list[dict[str, Any]],
    company_intelligence: list[dict[str, Any]],
    patents_research: dict[str, list[dict[str, Any]]],
    future_radar: list[dict[str, Any]],
    insights: list[dict[str, str]],
    statistics: dict[str, dict[str, int]],
    insight: str,
    research_insight_cards: list[dict[str, str]],
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
        validation_pool=validation_pool,
        opportunity_domains=opportunity_domains,
        opportunity_topics=opportunity_topics,
        emerging_topics=emerging_topics,
        company_intelligence=company_intelligence,
        patents_research=patents_research,
        future_radar=future_radar,
        insights=insights,
        count=len(display_items),
        statistics=statistics,
        insight=insight,
        research_insight_cards=research_insight_cards,
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
    existing_opportunities = load_json(OPPORTUNITIES_PATH, {"topics": []})
    opportunity_topics = build_opportunity_topics(display_items)
    opportunity_domains = build_opportunity_domains(display_items, opportunity_topics)
    current_date = today_payload.get("date") or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    emerging_topics = build_emerging_topics(opportunity_topics, existing_opportunities, current_date)
    opportunity_archive = build_opportunity_archive(opportunity_topics, existing_opportunities, current_date)
    validation_pool = build_validation_pool(display_items)
    company_intelligence = build_company_intelligence(display_items)
    patents_research = build_patents_research(display_items)
    future_radar = build_future_radar(display_items)
    statistics = build_statistics(display_items, analyzed_items, backlog_items)
    insight = build_research_insight(display_items, statistics)
    research_insight_cards = build_research_insight_cards(display_items, statistics)
    archives = collect_archive_data(today_payload, published_data)
    save_json(statistics, STATISTICS_PATH)
    save_json(opportunity_archive, OPPORTUNITIES_PATH)

    env = _env()
    generate_index_page(
        env,
        today_payload,
        display_items,
        category_sections,
        validation_pool,
        opportunity_domains,
        opportunity_topics,
        emerging_topics,
        company_intelligence,
        patents_research,
        future_radar,
        insights,
        statistics,
        insight,
        research_insight_cards,
        archives,
    )
    daily_path = generate_daily_page(env, today_payload, display_items, statistics, insight, archives)
    monthly_path = generate_monthly_page(env, today_payload, display_items, statistics, archives)
    methodology_path = generate_methodology_page(env)

    logging.info("Generated docs/index.html.")
    logging.info("Generated %s.", daily_path)
    logging.info("Generated %s.", monthly_path)
    logging.info("Generated %s.", STATISTICS_PATH)
    logging.info("Generated %s.", OPPORTUNITIES_PATH)
    logging.info("Generated %s.", methodology_path)


if __name__ == "__main__":
    main()

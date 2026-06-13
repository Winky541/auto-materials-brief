"""Rule-based filtering for raw automotive materials news candidates.

This stage reads data/news_raw.json, keeps only valid current-month candidates,
scores them with deterministic keyword rules, removes duplicates, and writes a
small set to data/news_filtered.json. It does not call DeepSeek, build the
website, or push robot messages.
"""

from __future__ import annotations

import json
import logging
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
RAW_NEWS_PATH = PROJECT_ROOT / "data" / "news_raw.json"
FILTERED_NEWS_PATH = PROJECT_ROOT / "data" / "news_filtered.json"

DEFAULT_MIN_RULE_SCORE = 35
DEFAULT_MAX_FILTERED_NEWS = 20
DEFAULT_MAX_TITLE_SIMILARITY = 0.88

AUTOMOTIVE_KEYWORDS = [
    "EV",
    "electric vehicle",
    "vehicle",
    "automotive",
    "automaker",
    "car",
    "mobility",
    "新能源汽车",
    "电动汽车",
    "汽车",
    "车企",
    "主机厂",
    "智能汽车",
]

MATERIAL_TECH_KEYWORDS = [
    "battery",
    "solid-state battery",
    "semi-solid battery",
    "sodium-ion battery",
    "lithium-ion",
    "fast charging",
    "fuel cell",
    "electrolyte",
    "cathode",
    "anode",
    "separator",
    "silicon anode",
    "lithium metal",
    "thermal management",
    "aerogel",
    "phase change material",
    "flame retardant",
    "lightweight",
    "carbon fiber",
    "composite",
    "CFRP",
    "GFRP",
    "aluminum alloy",
    "magnesium alloy",
    "titanium alloy",
    "metamaterial",
    "self-healing material",
    "smart glass",
    "SiC",
    "GaN",
    "power semiconductor",
    "motor magnet",
    "rare earth",
    "additive manufacturing",
    "3D printing",
    "laser welding",
    "coating",
    "recycling",
    "low-carbon steel",
    "low-carbon aluminum",
    "固态电池",
    "半固态电池",
    "钠离子电池",
    "锂离子电池",
    "快充",
    "燃料电池",
    "电解液",
    "正极",
    "负极",
    "隔膜",
    "硅碳负极",
    "锂金属",
    "热管理",
    "气凝胶",
    "相变材料",
    "阻燃",
    "轻量化",
    "碳纤维",
    "复合材料",
    "铝合金",
    "镁合金",
    "钛合金",
    "超材料",
    "自修复材料",
    "智能玻璃",
    "碳化硅",
    "氮化镓",
    "功率半导体",
    "永磁材料",
    "稀土",
    "3D打印",
    "激光焊接",
    "涂层",
    "回收",
    "低碳钢",
    "低碳铝",
]

COMPANY_KEYWORDS = [
    "Toyota",
    "Nissan",
    "Honda",
    "Panasonic",
    "CATL",
    "BYD",
    "Tesla",
    "BMW",
    "Mercedes-Benz",
    "Volkswagen",
    "Hyundai",
    "GM",
    "Ford",
    "Bosch",
    "Denso",
    "Aisin",
    "Toray",
    "BASF",
    "Umicore",
    "QuantumScape",
    "Solid Power",
    "宁德时代",
    "比亚迪",
    "丰田",
    "日产",
    "本田",
    "松下",
    "特斯拉",
    "宝马",
    "奔驰",
    "大众",
    "博世",
    "电装",
    "爱信",
    "东丽",
    "国轩高科",
    "亿纬锂能",
]

INDUSTRIALIZATION_KEYWORDS = [
    "mass production",
    "pilot production",
    "commercialization",
    "launch",
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
    "量产",
    "试生产",
    "商业化",
    "发布",
    "供应协议",
    "工厂",
    "投资",
    "专利",
    "标准",
    "法规",
    "认证",
    "原型",
    "路线图",
    "装车",
]

CATEGORY_RULES: dict[str, list[str]] = {
    "专利情报": ["patent", "专利"],
    "政策法规与标准": ["standard", "regulation", "approval", "标准", "法规", "认证"],
    "学术论文": [
        "Nature Energy",
        "Nature Materials",
        "Advanced Materials",
        "Joule",
        "Energy Storage Materials",
        "ACS",
        "SAE",
        "IEEE",
        "journal",
        "paper",
        "论文",
        "期刊",
    ],
    "电池与储能材料": [
        "battery",
        "solid-state battery",
        "semi-solid battery",
        "sodium-ion battery",
        "lithium-ion",
        "fast charging",
        "fuel cell",
        "electrolyte",
        "cathode",
        "anode",
        "separator",
        "silicon anode",
        "lithium metal",
        "固态电池",
        "半固态电池",
        "钠离子电池",
        "锂离子电池",
        "快充",
        "燃料电池",
        "电解液",
        "正极",
        "负极",
        "隔膜",
        "硅碳负极",
        "锂金属",
    ],
    "热管理与安全材料": [
        "thermal management",
        "aerogel",
        "phase change material",
        "flame retardant",
        "热管理",
        "气凝胶",
        "相变材料",
        "阻燃",
        "热失控",
        "防火",
        "隔热",
    ],
    "电驱与电子材料": [
        "SiC",
        "GaN",
        "power semiconductor",
        "motor magnet",
        "rare earth",
        "碳化硅",
        "氮化镓",
        "功率半导体",
        "永磁材料",
        "稀土",
    ],
    "复合材料": ["carbon fiber", "composite", "CFRP", "GFRP", "碳纤维", "复合材料"],
    "轻量化与结构材料": [
        "lightweight",
        "aluminum alloy",
        "magnesium alloy",
        "titanium alloy",
        "轻量化",
        "铝合金",
        "镁合金",
        "钛合金",
        "高强钢",
    ],
    "智能与功能材料": [
        "metamaterial",
        "self-healing material",
        "smart glass",
        "超材料",
        "自修复材料",
        "智能玻璃",
        "形状记忆",
        "压电",
    ],
    "可持续与循环材料": [
        "recycling",
        "low-carbon steel",
        "low-carbon aluminum",
        "回收",
        "低碳钢",
        "低碳铝",
        "再生",
        "生物基",
    ],
    "先进制造工艺": [
        "additive manufacturing",
        "3D printing",
        "laser welding",
        "coating",
        "3D打印",
        "激光焊接",
        "涂层",
        "PVD",
        "CVD",
    ],
    "企业技术动态": [
        "launch",
        "factory",
        "plant",
        "investment",
        "supply agreement",
        "发布",
        "工厂",
        "投资",
        "供应协议",
    ],
}

SUBCATEGORY_RULES: dict[str, list[str]] = {
    "固态电池": ["solid-state battery", "固态电池"],
    "半固态电池": ["semi-solid battery", "半固态电池"],
    "钠离子电池": ["sodium-ion battery", "钠离子电池"],
    "锂离子电池": ["lithium-ion", "锂离子电池"],
    "快充技术": ["fast charging", "快充"],
    "燃料电池": ["fuel cell", "燃料电池"],
    "电解液": ["electrolyte", "电解液"],
    "正极材料": ["cathode", "正极"],
    "负极材料": ["anode", "负极"],
    "隔膜": ["separator", "隔膜"],
    "硅碳负极": ["silicon anode", "硅碳负极"],
    "锂金属电池": ["lithium metal", "锂金属"],
    "热管理材料": ["thermal management", "热管理"],
    "气凝胶": ["aerogel", "气凝胶"],
    "相变材料": ["phase change material", "相变材料"],
    "阻燃材料": ["flame retardant", "阻燃"],
    "碳纤维": ["carbon fiber", "碳纤维"],
    "CFRP": ["CFRP"],
    "GFRP": ["GFRP"],
    "复合材料": ["composite", "复合材料"],
    "铝合金": ["aluminum alloy", "铝合金"],
    "镁合金": ["magnesium alloy", "镁合金"],
    "钛合金": ["titanium alloy", "钛合金"],
    "SiC": ["SiC", "碳化硅"],
    "GaN": ["GaN", "氮化镓"],
    "功率半导体": ["power semiconductor", "功率半导体"],
    "永磁材料": ["motor magnet", "rare earth", "永磁材料", "稀土"],
    "3D 打印": ["additive manufacturing", "3D printing", "3D打印"],
    "激光焊接": ["laser welding", "激光焊接"],
    "涂层": ["coating", "涂层"],
    "回收": ["recycling", "回收"],
    "低碳材料": ["low-carbon steel", "low-carbon aluminum", "低碳钢", "低碳铝"],
}


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load configuration and fill stage-3 defaults."""
    if not path.exists():
        logging.warning("Config file not found: %s; using defaults.", path)
        return {
            "timezone": "Asia/Shanghai",
            "limits": {
                "max_filtered_news": DEFAULT_MAX_FILTERED_NEWS,
                "min_rule_score": DEFAULT_MIN_RULE_SCORE,
                "max_title_similarity": DEFAULT_MAX_TITLE_SIMILARITY,
            },
        }

    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    config.setdefault("timezone", "Asia/Shanghai")
    config.setdefault("limits", {})
    config["limits"].setdefault("max_filtered_news", DEFAULT_MAX_FILTERED_NEWS)
    config["limits"].setdefault("min_rule_score", DEFAULT_MIN_RULE_SCORE)
    config["limits"].setdefault("max_title_similarity", DEFAULT_MAX_TITLE_SIMILARITY)
    return config


def load_json(path: Path) -> list[dict[str, Any]]:
    """Load a JSON list from disk."""
    if not path.exists():
        logging.warning("Input JSON file not found: %s", path)
        return []

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list in {path}")

    return [item for item in data if isinstance(item, dict)]


def save_json(items: list[dict[str, Any]], path: Path) -> None:
    """Save UTF-8 JSON for downstream AI analysis."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(items, file, ensure_ascii=False, indent=2)
        file.write("\n")


def is_current_month(date_value: str, timezone_name: str = "Asia/Shanghai") -> bool:
    """Return True when YYYY-MM-DD belongs to the current configured month."""
    try:
        published = datetime.strptime(str(date_value), "%Y-%m-%d").date()
    except ValueError:
        return False

    now = datetime.now(ZoneInfo(timezone_name)).date()
    return published.year == now.year and published.month == now.month


def normalize_text(value: str | None) -> str:
    """Normalize text for matching and title similarity checks."""
    if not value:
        return ""
    text = value.casefold()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_url(url: str | None) -> str:
    """Normalize URL for deduplication without inventing missing values."""
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


def _text_for_item(item: dict[str, Any]) -> str:
    """Combine title and summary for deterministic rule matching."""
    return f"{item.get('title', '')} {item.get('summary', '')}"


def _contains_keyword(text: str, keyword: str) -> bool:
    """Keyword matching helper for English and Chinese terms."""
    normalized = normalize_text(text)
    normalized_keyword = normalize_text(keyword)
    return bool(normalized_keyword and normalized_keyword in normalized)


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    """Return matched keywords while preserving configured keyword spelling."""
    return [keyword for keyword in keywords if _contains_keyword(text, keyword)]


def detect_companies(item: dict[str, Any]) -> list[str]:
    """Detect known automotive, battery, materials, and supplier companies."""
    text = _text_for_item(item)
    return _matched_keywords(text, COMPANY_KEYWORDS)


def detect_material_keywords(item: dict[str, Any]) -> list[str]:
    """Detect material and technology keywords used by the rule filter."""
    text = _text_for_item(item)
    return _matched_keywords(text, MATERIAL_TECH_KEYWORDS)


def detect_category(item: dict[str, Any]) -> str:
    """Assign one allowed category based on keyword priority."""
    text = _text_for_item(item)
    category_scores: dict[str, int] = {}

    for category, keywords in CATEGORY_RULES.items():
        matches = _matched_keywords(text, keywords)
        if matches:
            category_scores[category] = len(matches)

    if not category_scores:
        return "其他"

    return max(category_scores.items(), key=lambda pair: pair[1])[0]


def detect_subcategory(item: dict[str, Any]) -> str:
    """Assign the first matching subcategory keyword label."""
    text = _text_for_item(item)
    for subcategory, keywords in SUBCATEGORY_RULES.items():
        if _matched_keywords(text, keywords):
            return subcategory
    return ""


def calculate_relevance_score(item: dict[str, Any]) -> tuple[int, str]:
    """Calculate rule_score from deterministic relevance dimensions."""
    text = _text_for_item(item)
    source_score = int(item.get("source_score", 0) or 0)

    source_points = min(25, round(source_score / 100 * 25))
    automotive_matches = _matched_keywords(text, AUTOMOTIVE_KEYWORDS)
    material_matches = _matched_keywords(text, MATERIAL_TECH_KEYWORDS)
    company_matches = detect_companies(item)
    industrial_matches = _matched_keywords(text, INDUSTRIALIZATION_KEYWORDS)

    automotive_points = min(20, len(automotive_matches) * 5)
    material_points = min(25, len(material_matches) * 4)
    company_points = min(15, len(company_matches) * 5)
    industrial_points = min(10, len(industrial_matches) * 3)
    current_month_points = 5

    total = min(
        100,
        source_points
        + automotive_points
        + material_points
        + company_points
        + industrial_points
        + current_month_points,
    )

    reason = (
        f"source={source_points}; automotive={automotive_points} "
        f"({', '.join(automotive_matches[:4]) or 'none'}); "
        f"materials={material_points} ({', '.join(material_matches[:5]) or 'none'}); "
        f"companies={company_points} ({', '.join(company_matches[:4]) or 'none'}); "
        f"industrial={industrial_points} ({', '.join(industrial_matches[:4]) or 'none'}); "
        f"current_month={current_month_points}"
    )
    return int(total), reason


def _is_similar_title(title_a: str, title_b: str, threshold: float) -> bool:
    """Return True when normalized titles are highly similar."""
    if not title_a or not title_b:
        return False
    return SequenceMatcher(None, title_a, title_b).ratio() >= threshold


def filter_and_rank_candidates(
    raw_items: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    """Filter, score, deduplicate, and rank raw candidates."""
    limits = config.get("limits", {})
    timezone_name = config.get("timezone", "Asia/Shanghai")
    min_rule_score = int(limits.get("min_rule_score", config.get("min_rule_score", DEFAULT_MIN_RULE_SCORE)))
    max_filtered_news = int(
        limits.get("max_filtered_news", config.get("max_filtered_news", DEFAULT_MAX_FILTERED_NEWS))
    )
    max_title_similarity = float(
        limits.get(
            "max_title_similarity",
            config.get("max_title_similarity", DEFAULT_MAX_TITLE_SIMILARITY),
        )
    )

    valid_items: list[dict[str, Any]] = []
    skipped_missing = 0
    skipped_month = 0
    skipped_low_score = 0

    for raw_item in raw_items:
        title = str(raw_item.get("title") or "").strip()
        published_date = str(raw_item.get("published_date") or "").strip()
        url = _clean_url(raw_item.get("url"))

        if not title or not published_date or not url:
            skipped_missing += 1
            continue

        if not is_current_month(published_date, timezone_name):
            skipped_month += 1
            continue

        item = deepcopy(raw_item)
        item["title"] = title
        item["published_date"] = published_date
        item["url"] = url

        rule_score, filter_reason = calculate_relevance_score(item)
        if rule_score < min_rule_score:
            skipped_low_score += 1
            continue

        item["rule_score"] = rule_score
        item["category"] = detect_category(item)
        item["subcategory"] = detect_subcategory(item)
        item["detected_companies"] = detect_companies(item)
        item["detected_material_keywords"] = detect_material_keywords(item)
        item["filter_reason"] = filter_reason
        item["needs_ai_analysis"] = True
        item["_normalized_title"] = normalize_text(title)
        valid_items.append(item)

    valid_items.sort(
        key=lambda item: (
            int(item.get("rule_score", 0)),
            item.get("published_date", ""),
            int(item.get("source_score", 0) or 0),
        ),
        reverse=True,
    )

    deduplicated: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    skipped_duplicates = 0

    for item in valid_items:
        url = item.get("url", "")
        normalized_title = item.get("_normalized_title", "")
        if url in seen_urls or any(
            _is_similar_title(normalized_title, seen_title, max_title_similarity)
            for seen_title in seen_titles
        ):
            skipped_duplicates += 1
            continue

        seen_urls.add(url)
        seen_titles.append(normalized_title)
        item.pop("_normalized_title", None)
        deduplicated.append(item)

        if len(deduplicated) >= max_filtered_news:
            break

    logging.info("Raw candidates loaded: %s.", len(raw_items))
    logging.info("Skipped missing title/date/url: %s.", skipped_missing)
    logging.info("Skipped non-current-month items: %s.", skipped_month)
    logging.info("Skipped below min_rule_score=%s: %s.", min_rule_score, skipped_low_score)
    logging.info("Skipped duplicate URL/title items: %s.", skipped_duplicates)
    logging.info("Filtered candidates selected: %s.", len(deduplicated))

    return deduplicated


def main() -> None:
    """Run rule-based filtering from news_raw.json to news_filtered.json."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = load_config()
    raw_items = load_json(RAW_NEWS_PATH)
    filtered_items = filter_and_rank_candidates(raw_items, config)
    save_json(filtered_items, FILTERED_NEWS_PATH)
    logging.info("Saved filtered candidates to %s.", FILTERED_NEWS_PATH)


if __name__ == "__main__":
    main()

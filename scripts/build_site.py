"""Build the Auto Materials Brief static website.

This stage renders GitHub Pages-ready HTML under docs/ from existing pipeline
data. It does not fetch news, call DeepSeek, alter ranking, or push robots.
"""

from __future__ import annotations

import json
import logging
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
STATISTICS_PATH = ASSETS_DIR / "statistics.json"

CATEGORY_COLORS = {
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
    """Generate a 2-3 sentence Chinese research judgement from selected data only."""
    if not items:
        return "今日暂无达到发布条件的汽车新材料与前沿技术新闻。建议继续关注当月候选池变化，并优先补充高可信来源。"

    categories = list(statistics.get("category_counts", {}).keys())[:3]
    companies = list(statistics.get("company_counts", {}).keys())[:4]
    keywords = list(statistics.get("keyword_counts", {}).keys())[:5]

    sentences: list[str] = []
    if categories:
        sentences.append(f"今日入选内容主要集中在{'、'.join(categories)}方向，显示当前候选信息更偏向这些材料与技术主题。")
    if keywords:
        sentences.append(f"高频关键词包括{'、'.join(keywords)}，研究员可优先关注其在汽车场景中的产业化与验证进展。")
    if companies:
        sentences.append(f"涉及企业/机构以{'、'.join(companies)}等为主，后续可跟踪其量产、合作、专利或标准化动向。")

    return "".join(sentences[:3])


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
    statistics: dict[str, dict[str, int]],
    insight: str,
    archives: dict[str, list[dict[str, str]]],
) -> None:
    """Render docs/index.html."""
    template = env.get_template("index.html.j2")
    html = template.render(
        brand_en="Auto Materials Brief",
        brand_cn="汽车新材料与前沿技术简报",
        date=today_payload.get("date", ""),
        items=today_payload.get("items", []),
        count=today_payload.get("count", 0),
        statistics=statistics,
        insight=insight,
        archives=archives,
        category_colors=CATEGORY_COLORS,
        asset_prefix="assets",
        root_prefix=".",
    )
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")


def generate_daily_page(
    env: Environment,
    today_payload: dict[str, Any],
    statistics: dict[str, dict[str, int]],
    insight: str,
    archives: dict[str, list[dict[str, str]]],
) -> Path:
    """Render docs/daily/YYYY-MM-DD.html."""
    date = today_payload.get("date") or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    template = env.get_template("daily.html.j2")
    html = template.render(
        brand_en="Auto Materials Brief",
        brand_cn="汽车新材料与前沿技术简报",
        date=date,
        items=today_payload.get("items", []),
        count=today_payload.get("count", 0),
        statistics=statistics,
        insight=insight,
        archives=archives,
        category_colors=CATEGORY_COLORS,
        asset_prefix="../assets",
        root_prefix="..",
    )
    output = DAILY_DIR / f"{date}.html"
    output.write_text(html, encoding="utf-8")
    return output


def generate_monthly_page(
    env: Environment,
    today_payload: dict[str, Any],
    statistics: dict[str, dict[str, int]],
    archives: dict[str, list[dict[str, str]]],
) -> Path:
    """Render docs/monthly/YYYY-MM.html."""
    date = today_payload.get("date") or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    month = date[:7]
    month_items = [
        item for item in today_payload.get("items", []) if str(item.get("published_date", "")).startswith(month)
    ]
    template = env.get_template("monthly.html.j2")
    html = template.render(
        brand_en="Auto Materials Brief",
        brand_cn="汽车新材料与前沿技术简报",
        month=month,
        items=month_items,
        count=len(month_items),
        statistics=statistics,
        archives=archives,
        category_colors=CATEGORY_COLORS,
        asset_prefix="../assets",
        root_prefix="..",
    )
    output = MONTHLY_DIR / f"{month}.html"
    output.write_text(html, encoding="utf-8")
    return output


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
    today_items = _as_items(today_payload)

    statistics = build_statistics(today_items, analyzed_items, backlog_items)
    insight = build_research_insight(today_items, statistics)
    archives = collect_archive_data(today_payload, published_data)
    save_json(statistics, STATISTICS_PATH)

    env = _env()
    generate_index_page(env, today_payload, statistics, insight, archives)
    daily_path = generate_daily_page(env, today_payload, statistics, insight, archives)
    monthly_path = generate_monthly_page(env, today_payload, statistics, archives)

    logging.info("Generated docs/index.html.")
    logging.info("Generated %s.", daily_path)
    logging.info("Generated %s.", monthly_path)
    logging.info("Generated %s.", STATISTICS_PATH)


if __name__ == "__main__":
    main()

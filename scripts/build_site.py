"""Build the AURA static website.

This stage renders GitHub Pages-ready HTML under docs/ from existing pipeline
data. It does not fetch news, call DeepSeek, alter ranking, or push robots.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
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
CURRENT_ITEMS_PATH = ASSETS_DIR / "current_items.json"
WORKSPACE_ARCHIVE_PATH = DATA_DIR / "workspace_archive.json"
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

MATERIAL_FLOW_KEYWORDS = [
    "automotive material",
    "汽车材料",
    "新材料",
    "new energy vehicle",
    "新能源汽车",
    "battery material",
    "电池材料",
    "metal",
    "金属材料",
    "polymer",
    "高分子",
    "engineering plastic",
    "工程塑料",
    "rubber",
    "橡胶",
    "composite",
    "复合材料",
    "surface engineering",
    "表面工程",
    "functional material",
    "功能材料",
    "supplier",
    "供应商",
    "patent",
    "专利",
    "paper",
    "论文",
    "journal",
    "standard",
    "标准",
    "validation",
    "验证",
    "material_opportunity",
    "material relevance",
]

FUTURE_FLOW_KEYWORDS = [
    "ai",
    "artificial intelligence",
    "机器人",
    "robot",
    "humanoid",
    "具身智能",
    "embodied",
    "低空经济",
    "evtol",
    "flying car",
    "ai hardware",
    "automation",
    "自动化",
    "advanced manufacturing",
    "先进制造",
    "energy revolution",
    "能源革命",
    "fusion",
    "核聚变",
    "space",
    "空间产业",
    "brain-computer",
    "脑机接口",
    "future career",
    "未来职业",
    "organization",
    "组织变革",
    "innovation",
    "创新方法",
    "first principles",
    "第一性原理",
    "business model",
    "商业模式",
]

ACTION_ORDER = ["持续跟踪", "供应商调研", "联合开发", "启动验证", "前瞻储备", "暂不优先"]
ACTION_LABELS = {
    "持续跟踪": {"en": "Technology Watch", "zh": "持续观察", "pipeline": "Technology Watch"},
    "Technology Watch": {"en": "Technology Watch", "zh": "持续观察", "pipeline": "Technology Watch"},
    "供应商调研": {"en": "Supplier Research", "zh": "供应商调研", "pipeline": "Supplier Research"},
    "Supplier Research": {"en": "Supplier Research", "zh": "供应商调研", "pipeline": "Supplier Research"},
    "启动验证": {"en": "Validation", "zh": "验证价值", "pipeline": "Validation"},
    "联合开发": {"en": "Joint Development", "zh": "联合开发", "pipeline": "Joint Development"},
    "Joint Development": {"en": "Joint Development", "zh": "联合开发", "pipeline": "Joint Development"},
    "前瞻储备": {"en": "Strategic Reserve", "zh": "战略储备", "pipeline": "Strategic Reserve"},
    "Strategic Reserve": {"en": "Strategic Reserve", "zh": "战略储备", "pipeline": "Strategic Reserve"},
    "暂不优先": {"en": "Technology Watch", "zh": "持续观察", "pipeline": "Technology Watch"},
    "Early Exploration": {"en": "Technology Watch", "zh": "持续观察", "pipeline": "Technology Watch"},
    "Lab Evaluation": {"en": "Validation", "zh": "验证价值", "pipeline": "Validation"},
    "Validation": {"en": "Validation", "zh": "验证价值", "pipeline": "Validation"},
}
PIPELINE_ORDER = [
    "Technology Watch",
    "Supplier Research",
    "Joint Development",
    "Validation",
    "Strategic Reserve",
]
PIPELINE_META = {
    "Technology Watch": {"meaning": "发现机会", "color": "#6B8E6E"},
    "Supplier Research": {"meaning": "寻找资源", "color": "#C8A45A"},
    "Joint Development": {"meaning": "确定方案", "color": "#8D7AB8"},
    "Validation": {"meaning": "验证价值", "color": "#C97B63"},
    "Strategic Reserve": {"meaning": "形成储备", "color": "#4A6FA5"},
}
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
        "domain": "Metal Materials",
        "zh": "金属材料",
        "description": "高强钢、热成形钢、铝合金、镁合金、钛合金、铜合金、增材制造金属、连接技术",
        "keywords": ["metal", "金属", "steel", "钢", "高强钢", "热成形钢", "aluminum", "aluminium", "铝合金", "magnesium", "镁合金", "titanium", "钛合金", "copper", "铜合金", "additive manufacturing metal", "metal additive", "增材制造金属", "金属增材", "joining", "connection", "连接技术", "金属连接", "焊接"],
    },
    {
        "domain": "Polymer & Elastomer Materials",
        "zh": "高分子与弹性体材料",
        "description": "PP、PE、ABS、PC、PA、POM、PBT、PET、PPS、PEEK、LCP、PI、TPU、TPE、EPDM、NBR、HNBR、FKM、硅橡胶、机器人轻量化材料",
        "keywords": ["polymer", "plastic", "engineering plastic", "elastomer", "rubber", "高分子", "工程塑料", "弹性体", "橡胶", "pp", "pe", "abs", "pc", "pa", "pom", "pbt", "pet", "pps", "peek", "lcp", "pi", "tpu", "tpe", "epdm", "nbr", "hnbr", "fkm", "silicone rubber", "硅橡胶", "机器人轻量化", "机器人减重"],
    },
    {
        "domain": "Composite Materials",
        "zh": "复合材料",
        "description": "CFRP、GFRP、CFRTP、GMT、SMC、天然纤维复材、低空飞行器复材、储氢复材",
        "keywords": ["composite", "复合材料", "cfrp", "gfrp", "cfrtp", "gmt", "smc", "carbon fiber", "碳纤维", "glass fiber", "玻璃纤维", "natural fiber", "天然纤维", "低空飞行器复材", "低空飞行结构", "evtol composite", "储氢复材", "hydrogen storage composite", "氢气储罐", "储氢瓶"],
    },
    {
        "domain": "Functional Materials",
        "zh": "功能材料",
        "description": "SWIR、红外材料、导热材料、导电材料、EMI屏蔽、压电材料、磁性材料、柔性电子、电子皮肤、智能表面",
        "keywords": ["functional", "功能材料", "swir", "infrared", "红外材料", "红外", "导热", "thermal", "导电", "conductive", "emi", "屏蔽", "piezoelectric", "压电", "magnetic", "磁性", "flexible electronics", "柔性电子", "electronic skin", "电子皮肤", "smart surface", "智能表面"],
    },
    {
        "domain": "Energy Materials",
        "zh": "能源材料",
        "description": "锂离子电池、固态电池、钠离子电池、燃料电池、氢能材料、储氢材料、电解槽材料、电池回收、热管理材料",
        "keywords": ["battery", "电池", "energy storage", "储能", "lithium-ion", "锂离子", "solid-state", "固态电池", "sodium-ion", "钠离子", "fuel cell", "燃料电池", "hydrogen", "氢能", "hydrogen storage", "储氢", "electrolyzer", "电解槽", "battery recycling", "电池回收", "thermal management", "热管理材料", "热管理"],
    },
    {
        "domain": "Surface Engineering",
        "zh": "表面工程",
        "description": "电镀、PVD、CVD、功能涂层、防腐涂层、耐磨涂层、防污涂层、自修复涂层",
        "keywords": ["surface", "表面", "coating", "涂层", "functional coating", "功能涂层", "pvd", "cvd", "plating", "电镀", "corrosion coating", "防腐涂层", "anti-corrosion", "防腐", "wear coating", "耐磨涂层", "耐磨", "anti-fouling", "防污涂层", "防污", "self-healing coating", "自修复涂层"],
    },
    {
        "domain": "Sustainable Materials",
        "zh": "绿色材料",
        "description": "PCR塑料、生物基塑料、天然纤维、循环材料、低碳材料、绿色制造",
        "keywords": ["sustainable", "绿色材料", "可持续", "pcr", "pcr plastic", "pcr塑料", "bio-based plastic", "生物基塑料", "生物基", "natural fiber", "天然纤维", "recycled material", "循环材料", "recycling", "回收", "low-carbon", "低碳材料", "低碳", "green manufacturing", "绿色制造"],
    },
    {
        "domain": "Future Research Reserve",
        "zh": "前沿研究储备",
        "description": "超材料、4D打印、Programmable Materials、自修复材料、仿生材料、AI for Materials、材料大模型、数字材料、脑机接口材料、量子材料、核聚变材料、空间材料",
        "keywords": ["metamaterial", "超材料", "4d printing", "4d打印", "programmable material", "programmable materials", "可编程材料", "self-healing", "自修复材料", "biomimetic", "仿生材料", "ai for materials", "材料大模型", "digital material", "数字材料", "brain-computer", "bci", "脑机接口材料", "quantum", "量子材料", "fusion", "核聚变材料", "space material", "空间材料"],
    },
]
OPPORTUNITY_TOPIC_RULES = [
    ("Solid-State Electrolytes", "Energy Materials", ["solid-state", "固态", "electrolyte", "电解质"]),
    ("Sodium-Ion Battery Materials", "Energy Materials", ["sodium-ion", "钠离子", "sodium battery"]),
    ("Battery Thermal Management Materials", "Energy Materials", ["battery", "电池", "thermal", "热管理", "导热"]),
    ("Thermal Runaway Protection", "Energy Materials", ["thermal runaway", "热失控", "阻燃", "防火"]),
    ("Advanced Packaging Materials", "Future Research Reserve", ["sic", "gan", "封装", "银烧结", "power module"]),
    ("Power Semiconductor Substrates", "Functional Materials", ["sic", "gan", "功率半导体", "substrate"]),
    ("Robot Structural Materials", "Future Research Reserve", ["robot", "humanoid", "机器人", "具身", "结构材料"]),
    ("Flexible Sensing Materials", "Functional Materials", ["flexible", "柔性", "sensor", "传感"]),
    ("Low-cost SWIR Materials", "Functional Materials", ["swir", "infrared", "红外", "短波"]),
    ("eVTOL Composites", "Composite Materials", ["evtol", "flying car", "低空", "飞行汽车", "carbon fiber", "碳纤维"]),
    ("Advanced Coating Materials", "Surface Engineering", ["coating", "涂层", "surface", "表面"]),
    ("Bio-based Interior Materials", "Sustainable Materials", ["bio-based", "生物基", "interior", "内饰"]),
    ("Recycling & Circular Battery Materials", "Sustainable Materials", ["recycling", "回收", "battery", "电池"]),
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
        "body": "Suggested Action 是材料机会生命周期的下一步动作。Technology Watch 表示发现机会；Supplier Research 表示寻找资源；Joint Development 表示确定方案；Validation 表示验证价值；Strategic Reserve 表示形成储备。",
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
                "source": str(item.get("source") or source_name_from_url(url)).strip(),
                "why_read": str(item.get("why_read") or "帮助理解变化背后的原因。").strip(),
                "focus": str(item.get("focus") or "关注技术变化如何转化为材料需求。").strip(),
                "reading_time": str(item.get("reading_time") or "约 10 分钟").strip(),
                "url": url,
                "flow_type": "future_intelligence",
                "primary_flow": "future_intelligence",
                "secondary_flow": "",
                "reason_for_flow": "Curated long-form article for future trend reading.",
                "module_targets": ["weekly_insights"],
            }
        )
    return normalized[:2]


def source_name_from_url(url: str) -> str:
    """Infer a readable source name for curated Future Flow links."""
    host = urlparse(url).netloc.replace("www.", "")
    if not host:
        return "External Source"
    parts = host.split(".")
    if len(parts) >= 2:
        return parts[-2].upper() if parts[-2].lower() in {"iea", "mit", "bcg"} else parts[-2].title()
    return host


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


def flow_tags_for_item(item: dict[str, Any]) -> dict[str, Any]:
    """Classify one item into AURA's Material/Future intelligence flows."""
    text = _combined_item_text(item)
    source_type = str(item.get("source_type") or "").casefold()
    original_category = str(item.get("category") or "")
    material_score = int(item.get("material_opportunity_score", item.get("material_validation_score", 0)) or 0)
    future_score = int(item.get("future_signal_score", 0) or 0)

    material_hit = (
        material_score > 0
        or original_category in FOCUS_CATEGORY_ORDER
        or source_type in {"company_news_page", "journal_rss", "government_policy"}
        or any(_keyword_matches(text, keyword) for keyword in MATERIAL_FLOW_KEYWORDS)
    )
    future_hit = (
        future_score > 0
        or any(_keyword_matches(text, keyword) for keyword in FUTURE_FLOW_KEYWORDS)
    )

    if not material_hit and not future_hit:
        material_hit = True

    flows: list[str] = []
    if material_hit:
        flows.append("material_intelligence")
    if future_hit:
        flows.append("future_intelligence")

    if material_hit and future_hit:
        primary_flow = "material_intelligence" if material_score >= future_score else "future_intelligence"
        secondary_flow = "future_intelligence" if primary_flow == "material_intelligence" else "material_intelligence"
        reason = "内容同时包含材料机会和未来趋势信号，按分值更高的一侧确定主信息流。"
    elif material_hit:
        primary_flow = "material_intelligence"
        secondary_flow = ""
        reason = "内容直接关联材料机会、供应商、验证、专利、论文、标准或汽车材料应用。"
    else:
        primary_flow = "future_intelligence"
        secondary_flow = ""
        reason = "内容主要用于理解未来趋势、产业变化、技术范式或组织方法变化。"

    module_targets: list[str] = []
    if "material_intelligence" in flows:
        module_targets.extend(["today_key_insight", "bookshelf", "suggested_actions"])
    if "future_intelligence" in flows:
        module_targets.extend(["future_signals"])

    return {
        "flow_type": primary_flow,
        "primary_flow": primary_flow,
        "secondary_flow": secondary_flow,
        "reason_for_flow": reason,
        "module_targets": module_targets,
    }


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
        if current.get("stage") and current.get("stage") in PIPELINE_ORDER:
            current["suggested_action"] = current["stage"]
        if current.get("suggested_action") not in ACTION_ORDER and current.get("suggested_action") not in ACTION_LABELS:
            current["suggested_action"] = "暂不优先"
        action_meta = action_label(current.get("suggested_action"))
        current["suggested_action_en"] = action_meta["en"]
        current["suggested_action_zh"] = action_meta["zh"]
        current["pipeline_status"] = action_meta["pipeline"]
        if current.get("trend_potential") not in {"高", "中", "低", "不确定"}:
            current["trend_potential"] = "不确定"
        current.update(flow_tags_for_item(current))
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
        if any(_keyword_matches(folded, keyword) for keyword in domain["keywords"]):
            return domain["domain"]
    return "Future Research Reserve"


def _keyword_matches(folded_text: str, keyword: str) -> bool:
    """Match material keywords while avoiding short-token false positives."""
    folded_keyword = keyword.casefold()
    if re.fullmatch(r"[a-z0-9]{1,4}", folded_keyword):
        return re.search(rf"(?<![a-z0-9]){re.escape(folded_keyword)}(?![a-z0-9])", folded_text) is not None
    return folded_keyword in folded_text


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


def link_label_for_item(item: dict[str, Any]) -> str:
    """Return a lightweight source action label for Bookshelf entries."""
    text = " ".join(
        str(item.get(key) or "")
        for key in ("title", "category", "subcategory", "source", "source_type", "url")
    ).casefold()
    if "patent" in text or "专利" in text or "wipo" in text or "cnipa" in text:
        return "查看专利"
    if any(keyword in text for keyword in ("paper", "journal", "nature", "sae", "ieee", "arxiv", "论文", "学术")):
        return "阅读全文"
    if item.get("source_type") == "company_news_page" or any(company.casefold() in text for company in STRATEGIC_COMPANIES):
        return "官方发布"
    return "阅读原文"


def build_bookshelf_library(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the current-cycle Bookshelf: material domain -> source list."""
    rows = {
        domain["domain"]: {
            "domain": domain["domain"],
            "zh": domain["zh"],
            "description": domain.get("description", ""),
            "items": [],
            "count": 0,
        }
        for domain in OPPORTUNITY_DOMAINS
    }
    for item in items:
        _, domain_name = topic_for_item(item)
        if domain_name not in rows:
            domain_name = "Future Research Reserve"
        rows[domain_name]["items"].append(
            {
                "event_id": str(item.get("event_id") or ""),
                "canonical_url": str(item.get("canonical_url") or item.get("url") or ""),
                "normalized_title": str(item.get("normalized_title") or ""),
                "title": str(item.get("title") or "Untitled"),
                "source": str(item.get("source") or "Unknown Source"),
                "source_names": item.get("source_names", []) or [],
                "source_urls": item.get("source_urls", []) or [],
                "published_date": str(item.get("published_date") or ""),
                "url": str(item.get("url") or ""),
                "link_label": link_label_for_item(item),
            }
        )

    library = []
    for domain in OPPORTUNITY_DOMAINS:
        row = rows[domain["domain"]]
        row["items"].sort(key=lambda entry: entry.get("published_date", ""), reverse=True)
        row["count"] = len(row["items"])
        row["has_new"] = row["count"] > 0
        library.append(row)

    first_nonempty = next((row for row in library if row["count"] > 0), library[0] if library else None)
    if first_nonempty:
        first_nonempty["is_default_open"] = True
    return library


def _iso_date(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    if len(text) >= 10:
        return text[:10]
    return fallback


def _days_since(date_text: str, current_date: str) -> int | None:
    try:
        current = date.fromisoformat(current_date[:10])
        target = date.fromisoformat(date_text[:10])
    except ValueError:
        return None
    return (current - target).days


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
                "suggested_action": action_label(item.get("stage") or item.get("suggested_action"))["en"],
                "suggested_action_zh": action_label(item.get("stage") or item.get("suggested_action"))["zh"],
                "stage_reason": str(item.get("stage_reason") or ""),
                "related_signals": [],
                "companies": [],
                "materials": [],
                "news_count": 0,
            },
        )
        entry["material_value"] = max(entry["material_value"], score)
        if score >= entry["material_value"]:
            entry["suggested_action"] = action_label(item.get("stage") or item.get("suggested_action"))["en"]
            entry["suggested_action_zh"] = action_label(item.get("stage") or item.get("suggested_action"))["zh"]
            entry["stage_reason"] = str(item.get("stage_reason") or entry.get("stage_reason") or "")
        entry["related_signals"].append(_related_signal(item))
        entry["companies"].extend(item.get("companies_or_institutions", []) or [])
        entry["materials"].extend(item.get("materials_involved", []) or [])
        entry["news_count"] += 1

    topics = list(topic_map.values())
    for topic in topics:
        topic["validation_priority"] = validation_priority(int(topic["material_value"] or 0))
        topic["related_signals"] = topic["related_signals"][:4]
        topic["companies"] = _unique_strings(topic.get("companies", []))
        topic["materials"] = _unique_strings(topic.get("materials", []))
    topics.sort(key=lambda row: (int(row["material_value"]), row["news_count"]), reverse=True)
    return topics


def build_opportunity_domains(items: list[dict[str, Any]], topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build fixed opportunity domain summary for the homepage."""
    summary = []
    topic_counts = Counter(topic["domain"] for topic in topics)
    for domain in OPPORTUNITY_DOMAINS:
        matched = [
            item
            for item in items
            if any(_keyword_matches(_item_text_for_tracks(item).casefold(), keyword) for keyword in domain["keywords"])
        ]
        summary.append(
            {
                "domain": domain["domain"],
                "zh": domain["zh"],
                "description": domain.get("description", ""),
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
    bookshelf_library: list[dict[str, Any]],
    current_date: str,
) -> dict[str, Any]:
    """Build docs/assets/opportunities.json as the current Bookshelf view."""
    return {
        "updated_at": current_date,
        "domains": [
            {
                "domain": domain.get("domain", ""),
                "zh": domain.get("zh", ""),
                "description": domain.get("description", ""),
                "count": int(domain.get("count", 0) or 0),
                "items": domain.get("items", []),
            }
            for domain in bookshelf_library
        ],
    }


def build_current_items_export(items: list[dict[str, Any]], current_date: str) -> dict[str, Any]:
    """Export current-cycle items with flow assignment for verification/debugging."""
    return {
        "updated_at": current_date,
        "items": [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "source": item.get("source", ""),
                "published_date": item.get("published_date", ""),
                "flow_type": item.get("flow_type", ""),
                "primary_flow": item.get("primary_flow", ""),
                "secondary_flow": item.get("secondary_flow", ""),
                "reason_for_flow": item.get("reason_for_flow", ""),
                "module_targets": item.get("module_targets", []),
            }
            for item in items
        ],
    }


def _unique_strings(values: list[Any], limit: int = 8) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _topic_profile_from_current(topic: dict[str, Any], current_date: str) -> dict[str, Any]:
    signals = topic.get("related_signals", []) if isinstance(topic.get("related_signals"), list) else []
    return {
        "id": re.sub(r"[^a-z0-9]+", "-", str(topic.get("topic", "")).casefold()).strip("-") or "opportunity",
        "topic": topic.get("topic", "Emerging Material Opportunity"),
        "domain": topic.get("domain", "Future Research Reserve"),
        "first_seen": current_date,
        "updated_at": current_date,
        "current_stage": topic.get("suggested_action", "Technology Watch"),
        "material_value": int(topic.get("material_value", 0) or 0),
        "validation_priority": topic.get("validation_priority", "Low"),
        "suggested_action": topic.get("suggested_action", "Technology Watch"),
        "suggested_action_zh": topic.get("suggested_action_zh", "持续观察"),
        "stage_reason": topic.get("stage_reason", ""),
        "related_signals": signals[:6],
        "companies": _unique_strings(topic.get("companies", [])),
        "materials": _unique_strings(topic.get("materials", [])),
        "news_count": int(topic.get("news_count", len(signals)) or 0),
    }


def _topic_profile_from_archive(topic: dict[str, Any], current_date: str) -> dict[str, Any]:
    signals = topic.get("related_signals", []) if isinstance(topic.get("related_signals"), list) else []
    first_seen = _iso_date(topic.get("first_seen"), current_date)
    updated_at = _iso_date(topic.get("updated_at"), first_seen)
    return {
        "id": re.sub(r"[^a-z0-9]+", "-", str(topic.get("topic", "")).casefold()).strip("-") or "opportunity",
        "topic": topic.get("topic", "Emerging Material Opportunity"),
        "domain": topic.get("domain", "Future Research Reserve"),
        "first_seen": first_seen,
        "updated_at": updated_at,
        "current_stage": topic.get("suggested_action", "Technology Watch"),
        "material_value": int(topic.get("material_value", 0) or 0),
        "validation_priority": topic.get("validation_priority", "Low"),
        "suggested_action": topic.get("suggested_action", "Technology Watch"),
        "suggested_action_zh": topic.get("suggested_action_zh", "持续观察"),
        "stage_reason": topic.get("stage_reason", ""),
        "related_signals": signals[:6],
        "companies": _unique_strings(topic.get("companies", [])),
        "materials": _unique_strings(topic.get("materials", [])),
        "news_count": int(topic.get("news_count", len(signals)) or 0),
    }


def build_opportunity_library(
    topics: list[dict[str, Any]],
    existing_archive: dict[str, Any],
    current_date: str,
) -> list[dict[str, Any]]:
    """Build the Bookshelf hierarchy: Domain -> Opportunity -> Profile."""
    previous = existing_archive.get("topics", []) if isinstance(existing_archive, dict) else []
    profiles: dict[str, dict[str, Any]] = {}

    for archived in previous:
        if isinstance(archived, dict):
            profile = _topic_profile_from_archive(archived, current_date)
            profiles[profile["topic"]] = profile

    for topic in topics:
        current = _topic_profile_from_current(topic, current_date)
        previous_profile = profiles.get(current["topic"], {})
        first_seen = previous_profile.get("first_seen", current["first_seen"])
        merged_signals = list(current["related_signals"])
        for signal in previous_profile.get("related_signals", []):
            if isinstance(signal, dict) and signal.get("url") not in {item.get("url") for item in merged_signals}:
                merged_signals.append(signal)
        profiles[current["topic"]] = {
            **previous_profile,
            **current,
            "first_seen": first_seen,
            "updated_at": current["updated_at"],
            "material_value": max(int(previous_profile.get("material_value", 0) or 0), current["material_value"]),
            "related_signals": merged_signals[:6],
            "news_count": max(int(previous_profile.get("news_count", 0) or 0), current["news_count"]),
        }

    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for profile in profiles.values():
        days = _days_since(str(profile.get("updated_at", "")), current_date)
        profile["status"] = "Active" if days is None or days <= 30 else "Dormant"
        profile["is_active"] = profile["status"] == "Active"
        by_domain[str(profile.get("domain") or "Future Research Reserve")].append(profile)

    library = []
    for domain in OPPORTUNITY_DOMAINS:
        opportunities = by_domain.get(domain["domain"], [])
        opportunities.sort(
            key=lambda item: (
                item.get("status") == "Active",
                int(item.get("material_value", 0) or 0),
                str(item.get("updated_at", "")),
            ),
            reverse=True,
        )
        active = [item for item in opportunities if item["status"] == "Active"]
        dormant = [item for item in opportunities if item["status"] == "Dormant"]
        library.append(
            {
                "domain": domain["domain"],
                "zh": domain["zh"],
                "description": domain.get("description", ""),
                "active_count": len(active),
                "dormant_count": len(dormant),
                "opportunities": active,
                "dormant_opportunities": dormant,
            }
        )
    first_active = next((row for row in library if row["active_count"] > 0), library[0] if library else None)
    if first_active:
        first_active["is_default_open"] = True
    return library


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
    """Build 3-5 Future Flow signals from broad future-change indicators."""
    rules = [
        ("Robotics & Embodied AI", ["humanoid", "robot", "机器人", "具身", "embodied"]),
        ("Low-altitude Economy", ["evtol", "flying car", "低空", "飞行汽车", "air mobility"]),
        ("AI Agent & AI Hardware", ["ai agent", "ai hardware", "chip", "算力", "agent", "硬件"]),
        ("Autonomous Driving", ["autonomous", "adas", "自动驾驶", "智能驾驶"]),
        ("Advanced Manufacturing & Automation", ["manufacturing", "automation", "制造", "3d printing", "增材", "自动化"]),
        ("Energy Revolution", ["hydrogen", "fuel cell", "氢能", "燃料电池", "energy storage", "v2g", "储能", "新能源系统"]),
        ("Advanced Sensing", ["sensor", "lidar", "infrared", "swir", "感知", "红外"]),
        ("Fusion & Frontier Energy", ["fusion", "nuclear fusion", "聚变", "核聚变"]),
        ("Brain-computer Interface", ["brain-computer", "bci", "脑机"]),
        ("Space Industry", ["space", "satellite", "aerospace", "空间", "卫星", "航天"]),
        ("Automotive Profit Shift", ["profit", "margin", "price war", "盈利", "利润", "价格战", "降价"]),
        ("OEM Strategy Transition", ["strategy", "restructure", "software-defined", "转型", "战略", "重组", "软件定义"]),
        ("Supply Chain Migration", ["supply chain", "localization", "reshoring", "产业链", "供应链", "本地化", "迁移"]),
        ("New Mobility Business Models", ["business model", "subscription", "robotaxi", "mobility service", "商业模式", "订阅", "出行服务"]),
    ]
    rows = []
    for category, keywords in rules:
        matched = [item for item in items if any(keyword.casefold() in _combined_item_text(item) for keyword in keywords)]
        if matched:
            matched.sort(
                key=lambda item: int(item.get("future_signal_score", item.get("final_score", 0)) or 0),
                reverse=True,
            )
            top = matched[0]
            rows.append(
                {
                    "category": category,
                    "count": len(matched),
                    "avg_future_signal_score": round(
                        sum(int(item.get("future_signal_score", 0) or 0) for item in matched) / len(matched)
                    ),
                    "summary": future_signal_summary(category, matched),
                    "sources": [_source_evidence(item) for item in matched[:3] if item.get("url")],
                    "signal": str(top.get("future_signal") or top.get("technology_driver") or category),
                }
            )
    rows.sort(key=lambda row: (row["avg_future_signal_score"], row["count"]), reverse=True)
    if not rows and items:
        drivers = Counter(str(item.get("technology_driver") or "其他") for item in items)
        for driver, count in drivers.most_common(5):
            matched = [item for item in items if str(item.get("technology_driver") or "其他") == driver]
            matched.sort(key=lambda item: int(item.get("future_signal_score", 0) or 0), reverse=True)
            rows.append(
                {
                    "category": driver,
                    "count": count,
                    "avg_future_signal_score": round(
                        sum(int(item.get("future_signal_score", 0) or 0) for item in matched) / max(len(matched), 1)
                    ),
                    "summary": future_signal_summary(driver, matched),
                    "sources": [_source_evidence(item) for item in matched[:3] if item.get("url")],
                    "signal": driver,
                }
            )
    return rows[:5]


def _source_evidence(item: dict[str, Any]) -> dict[str, str]:
    """Return a compact source record for signal/evidence links."""
    return {
        "title": str(item.get("title") or "Untitled"),
        "source": str(item.get("source") or "Unknown Source"),
        "url": str(item.get("url") or ""),
        "published_date": str(item.get("published_date") or ""),
        "link_label": link_label_for_item(item),
    }


def future_signal_summary(category: str, matched: list[dict[str, Any]]) -> str:
    """Create a short researcher-facing signal explanation."""
    top = matched[0] if matched else {}
    reason = str(top.get("why_it_matters") or top.get("impact_assessment") or "").strip()
    if reason:
        return reason[:120] + ("..." if len(reason) > 120 else "")
    return f"{category} 出现新的产业、技术或资源流向信号，适合用于判断未来研发关注边界。"


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
        groups[-1].update(PIPELINE_META.get(action, {}))
        groups[-1]["has_new"] = bool(action_items)
    return groups


def build_palette_from_opportunity_library(
    opportunity_library: list[dict[str, Any]],
    current_date: str,
) -> list[dict[str, Any]]:
    """Build Palette as lifecycle insight groups, not another article list."""
    grouped: dict[str, list[dict[str, Any]]] = {status: [] for status in PIPELINE_ORDER}
    for domain in opportunity_library:
        for opportunity in list(domain.get("opportunities", [])) + list(domain.get("dormant_opportunities", [])):
            action = str(opportunity.get("suggested_action") or opportunity.get("current_stage") or "Technology Watch")
            pipeline = action if action in PIPELINE_ORDER else action_label(action)["pipeline"]
            grouped.setdefault(pipeline, []).append(
                {
                    "title": opportunity.get("topic", "Unnamed Opportunity"),
                    "domain": opportunity.get("domain", domain.get("domain", "")),
                    "material_value": opportunity.get("material_value", 0),
                    "updated_at": opportunity.get("updated_at", ""),
                    "status": opportunity.get("status", "Active"),
                    "is_new": opportunity.get("updated_at") == current_date,
                    "related_signals": opportunity.get("related_signals", []),
                    "stage_reason": opportunity.get("stage_reason", ""),
                }
            )

    groups = []
    for action in PIPELINE_ORDER:
        action_items = grouped.get(action, [])
        action_items.sort(
            key=lambda item: (
                item.get("is_new"),
                int(item.get("material_value", 0) or 0),
                str(item.get("updated_at", "")),
            ),
            reverse=True,
        )
        evidence = palette_evidence(action_items)
        group = {
            "action": action,
            "items": action_items,
            "count": len(action_items),
            "ai_insight": palette_ai_insight(action, action_items),
            "why_now": palette_why_now(action, action_items),
            "evidence": evidence,
            "suggested_move": palette_suggested_move(action, action_items),
        }
        group.update(PIPELINE_META.get(action, {}))
        group["has_new"] = any(item.get("is_new") for item in action_items)
        groups.append(group)
    return groups


def palette_evidence(action_items: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Collect 2-3 source links supporting a Palette-stage insight."""
    evidence: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in action_items:
        for signal in item.get("related_signals", []) or []:
            if not isinstance(signal, dict):
                continue
            url = str(signal.get("url") or "").strip()
            title = str(signal.get("title") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            evidence.append(
                {
                    "title": title or str(item.get("title") or "Evidence"),
                    "source": str(signal.get("source") or "Unknown Source"),
                    "url": url,
                    "link_label": "阅读来源",
                }
            )
            if len(evidence) >= 3:
                return evidence
    return evidence


def palette_ai_insight(action: str, action_items: list[dict[str, Any]]) -> str:
    """Summarize what the stage means for material teams."""
    if not action_items:
        return "本周期暂无足够证据形成新的阶段判断。"
    top = action_items[0]
    domains = _unique_strings([item.get("domain") for item in action_items], limit=2)
    domain_text = "、".join(domains) if domains else "材料机会"
    return f"{domain_text}中已有{len(action_items)}个机会进入 {action}，其中“{top.get('title')}”最值得先看。"


def palette_why_now(action: str, action_items: list[dict[str, Any]]) -> str:
    """Explain the timing behind a Palette-stage insight."""
    if not action_items:
        return "等待更多企业、论文、专利或验证信号后再推进。"
    reason = str(action_items[0].get("stage_reason") or "").strip()
    if reason:
        return reason
    if any(item.get("is_new") for item in action_items):
        return "本周期出现了新的来源证据，说明该方向值得重新评估成熟度与资源可得性。"
    return "该方向已有持续证据积累，适合在周期复盘中保持关注。"


def palette_suggested_move(action: str, action_items: list[dict[str, Any]]) -> str:
    """Return the recommended material-team move for a lifecycle stage."""
    if not action_items:
        return "暂不新增动作，保持观察。"
    moves = {
        "Technology Watch": "建立观察清单，等待更强产业化或材料牵引信号。",
        "Supplier Research": "锁定潜在供应商、研究机构或初创公司，准备初步调研。",
        "Joint Development": "寻找可联合定义样件、工艺窗口或验证方案的合作对象。",
        "Validation": "进入样件、可靠性、场景或客户验证准备。",
        "Strategic Reserve": "纳入中长期储备，定期复盘技术成熟度和供应链变化。",
    }
    return moves.get(action, "保持观察，等待下一轮信号。")


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

    material_terms = keywords or _unique_strings(
        [
            keyword
            for item in items
            for keyword in (item.get("materials_involved") or item.get("detected_material_keywords") or [])
        ],
        limit=6,
    )
    sentences: list[str] = []
    if categories:
        sentences.append(f"本期变化主要集中在{'、'.join(categories)}，其中与汽车和新能源链条相关的材料信号仍应优先看。")
    sentences.append(f"最明显的技术牵引来自{top_driver}，需要判断它是否会转化为结构轻量化、热管理、电池体系、感知器件或封装材料需求。")
    sentences.append(f"最值得先读的材料线索是“{top_opportunity.get('title', '未命名情报')}”，它更适合作为供应商调研、样件验证或中长期储备的入口，而不是普通新闻浏览。")
    if material_terms:
        sentences.append(f"本期可重点留意{'、'.join(material_terms[:6])}等材料方向。")
    if companies:
        sentences.append(f"涉及企业/机构以{'、'.join(companies)}等为主，后续重点看其量产、合作、专利、标准化或供应链变化。")

    return "".join(sentences[:5])


def build_research_insight_cards(items: list[dict[str, Any]], statistics: dict[str, dict[str, int]]) -> list[dict[str, str]]:
    """Build structured Research Insight blocks for the homepage."""
    if not items:
        return [
            {"label": "What Changed", "text": "暂无达到发布条件的情报信号。"},
            {"label": "Why It Matters", "text": "当来源证据不足时，AURA 不会为了填充版面而生成判断。"},
            {"label": "Material Opportunity", "text": "建议继续观察当月候选池，并优先补充高可信来源。"},
        ]

    drivers = Counter(str(item.get("technology_driver") or "其他") for item in items)
    top_driver = drivers.most_common(1)[0][0]
    top_items = sorted(items, key=lambda item: int(item.get("material_opportunity_score", 0) or 0), reverse=True)
    top_item = top_items[0]
    categories = "、".join(list(statistics.get("category_counts", {}).keys())[:3]) or "当前精选情报"
    material_terms = _unique_strings(
        [
            str(keyword)
            for item in top_items[:5]
            for keyword in (item.get("materials_involved") or item.get("detected_material_keywords") or [])
            if keyword
        ],
        limit=8,
    )
    opportunity_text = str(top_item.get("material_opportunity") or top_item.get("material_relevance") or "").strip()
    if material_terms:
        opportunity_text = f"优先关注{'、'.join(material_terms)}。{opportunity_text or '这些方向可能进入供应商调研、样件验证或前瞻储备。'}"
    elif not opportunity_text:
        opportunity_text = "材料机会仍需进一步核验，建议保守观察。"
    return [
        {"label": "What Changed", "text": f"本期高价值信号集中在{categories}，技术牵引以{top_driver}最突出。"},
        {"label": "Why It Matters", "text": str(top_item.get("why_it_matters") or top_item.get("impact_assessment") or "这些变化可能影响材料选型、供应链调研和后续验证节奏。")},
        {"label": "Material Opportunity", "text": opportunity_text},
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


def _archive_event_key(item: dict[str, Any]) -> str:
    """Return a stable event key for archive de-duplication."""
    if item.get("event_id"):
        return f"event:{item['event_id']}"
    url = str(item.get("canonical_url") or item.get("url") or "").strip().lower().rstrip("/")
    if url:
        return f"url:{url}"
    title = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(item.get("normalized_title") or item.get("title") or "").casefold())
    title = re.sub(r"\s+", " ", title).strip()
    return f"title:{title}" if title else ""


def _dedupe_bookshelf_domains_for_archive(domains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate archived events while preserving Bookshelf domain groups."""
    seen: set[str] = set()
    cleaned_domains: list[dict[str, Any]] = []
    for domain in domains:
        if not isinstance(domain, dict):
            continue
        cleaned_items = []
        for item in domain.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            key = _archive_event_key(item)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            cleaned_items.append(item)
        if cleaned_items:
            current = dict(domain)
            current["items"] = cleaned_items
            current["count"] = len(cleaned_items)
            cleaned_domains.append(current)
    return cleaned_domains


def _dedupe_workspace_archive_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate Bookshelf events across dated Archive snapshots, newest first."""
    ordered = sorted(
        [record for record in records if isinstance(record, dict) and record.get("date")],
        key=lambda record: str(record.get("date", "")),
        reverse=True,
    )
    seen: set[str] = set()
    cleaned_records: list[dict[str, Any]] = []
    for record in ordered:
        current = dict(record)
        cleaned_bookshelf = []
        for domain in current.get("bookshelf", []) or []:
            if not isinstance(domain, dict):
                continue
            kept_items = []
            for item in domain.get("items", []) or []:
                if not isinstance(item, dict):
                    continue
                key = _archive_event_key(item)
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                kept_items.append(item)
            if kept_items:
                cleaned_domain = dict(domain)
                cleaned_domain["items"] = kept_items
                cleaned_domain["count"] = len(kept_items)
                cleaned_bookshelf.append(cleaned_domain)
        current["bookshelf"] = cleaned_bookshelf
        cleaned_records.append(current)
    return cleaned_records


def build_workspace_archive(
    archive_data: Any,
    current_date: str,
    future_radar: list[dict[str, Any]],
    research_insight_cards: list[dict[str, str]],
    insights: list[dict[str, str]],
    bookshelf_library: list[dict[str, Any]],
    validation_pool: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist Dynamic Workspace snapshots for Archive Box."""
    existing = archive_data.get("items", []) if isinstance(archive_data, dict) else []
    records = [item for item in existing if isinstance(item, dict)]
    snapshot = {
        "date": current_date,
        "window": [
            {
                "category": row.get("category", ""),
                "count": row.get("count", 0),
                "avg_future_signal_score": row.get("avg_future_signal_score", 0),
                "summary": row.get("summary", ""),
                "sources": row.get("sources", []),
            }
            for row in future_radar[:5]
        ],
        "notebook": research_insight_cards,
        "cat": [
            {
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "why_read": item.get("why_read", ""),
                "focus": item.get("focus", ""),
                "reading_time": item.get("reading_time", ""),
                "url": item.get("url", ""),
            }
            for item in insights[:2]
        ],
        "bookshelf": _dedupe_bookshelf_domains_for_archive([
            {
                "domain": domain.get("domain", ""),
                "zh": domain.get("zh", ""),
                "count": int(domain.get("count", 0) or 0),
                "items": domain.get("items", []),
            }
            for domain in bookshelf_library
            if int(domain.get("count", 0) or 0) > 0
        ]),
        "palette": [
            {
                "action": group.get("action", ""),
                "ai_insight": group.get("ai_insight", ""),
                "why_now": group.get("why_now", ""),
                "suggested_move": group.get("suggested_move", ""),
                "evidence": group.get("evidence", []),
            }
            for group in validation_pool
        ],
    }
    by_date = {str(item.get("date")): item for item in records if item.get("date")}
    by_date[current_date] = snapshot
    items = _dedupe_workspace_archive_records(list(by_date.values()))[:40]
    return {"updated_at": current_date, "items": items}


def collect_archive_data(
    today_payload: dict[str, Any],
    published_data: Any,
    workspace_archive: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, str]] | list[dict[str, Any]]]:
    """Collect recent archive links and Dynamic Workspace snapshots."""
    if today_payload.get("reset_archive"):
        return {
            "reset": True,
            "message_en": today_payload.get("archive_message_en", "Archive is ready for new AURA records."),
            "message_zh": today_payload.get("archive_message_zh", "归档已重置，等待新的 AURA 记录。"),
            "daily": [],
            "monthly": [],
            "workspace": [],
        }

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
    workspace = workspace_archive.get("items", []) if isinstance(workspace_archive, dict) else []
    return {"daily": daily, "monthly": monthly, "workspace": workspace[:12]}


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
    opportunity_library: list[dict[str, Any]],
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
        opportunity_library=opportunity_library,
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
    workspace_archive_data = load_json(WORKSPACE_ARCHIVE_PATH, {"items": []})
    insights = load_insights()
    today_items = _as_items(today_payload)
    reset_archive = bool(today_payload.get("reset_archive"))
    if reset_archive:
        insights = []

    if not today_items and not reset_archive:
        logging.warning("today_selected.json has no items; preserving existing site files.")
        logging.warning("Skipping static site generation to avoid publishing an empty homepage.")
        return

    display_items = prepare_display_items(today_items)
    material_items = [
        item
        for item in display_items
        if item.get("primary_flow") == "material_intelligence" or item.get("secondary_flow") == "material_intelligence"
    ]
    future_items = [
        item
        for item in display_items
        if item.get("primary_flow") == "future_intelligence" or item.get("secondary_flow") == "future_intelligence"
    ]
    category_sections = build_category_sections(material_items)
    existing_opportunities = load_json(OPPORTUNITIES_PATH, {"topics": []})
    opportunity_topics = build_opportunity_topics(material_items)
    opportunity_domains = build_opportunity_domains(material_items, opportunity_topics)
    current_date = today_payload.get("date") or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    bookshelf_library = build_bookshelf_library(material_items)
    opportunity_library = build_opportunity_library(opportunity_topics, existing_opportunities, current_date)
    emerging_topics = build_emerging_topics(opportunity_topics, existing_opportunities, current_date)
    opportunity_archive = build_opportunity_archive(bookshelf_library, current_date)
    company_intelligence = build_company_intelligence(material_items)
    patents_research = build_patents_research(material_items)
    future_radar = build_future_radar(future_items)
    validation_pool = build_palette_from_opportunity_library(opportunity_library, current_date)
    statistics = build_statistics(material_items, analyzed_items, backlog_items)
    insight = build_research_insight(material_items, statistics)
    research_insight_cards = build_research_insight_cards(material_items, statistics)
    if reset_archive:
        workspace_archive = {"updated_at": current_date, "items": []}
    else:
        workspace_archive = build_workspace_archive(
            workspace_archive_data,
            current_date,
            future_radar,
            research_insight_cards,
            insights,
            bookshelf_library,
            validation_pool,
        )
    archives = collect_archive_data(today_payload, published_data, workspace_archive)
    save_json(statistics, STATISTICS_PATH)
    save_json(opportunity_archive, OPPORTUNITIES_PATH)
    save_json(build_current_items_export(display_items, current_date), CURRENT_ITEMS_PATH)
    save_json(workspace_archive, WORKSPACE_ARCHIVE_PATH)

    env = _env()
    generate_index_page(
        env,
        today_payload,
        display_items,
        category_sections,
        validation_pool,
        opportunity_domains,
        opportunity_topics,
        bookshelf_library,
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
    methodology_path = generate_methodology_page(env)

    logging.info("Generated docs/index.html.")
    if reset_archive:
        logging.info("Archive reset mode enabled; skipped daily and monthly archive page generation.")
    else:
        daily_path = generate_daily_page(env, today_payload, display_items, statistics, insight, archives)
        monthly_path = generate_monthly_page(env, today_payload, display_items, statistics, archives)
        logging.info("Generated %s.", daily_path)
        logging.info("Generated %s.", monthly_path)
    logging.info("Generated %s.", STATISTICS_PATH)
    logging.info("Generated %s.", OPPORTUNITIES_PATH)
    logging.info("Generated %s.", methodology_path)


if __name__ == "__main__":
    main()

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
import hashlib
from copy import deepcopy
from datetime import datetime, timedelta
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
REPOST_DOMAINS = {"yahoo.com", "msn.com", "aol.com"}
AGGREGATOR_DOMAINS = {"bing.com", "google.com", "news.google.com"}
CLUE_DOMAINS = {
    "reddit.com",
    "quora.com",
    "medium.com",
    "substack.com",
    "toutiao.com",
    "baijiahao.baidu.com",
    "zhihu.com",
    "mp.weixin.qq.com",
}
DISALLOWED_FINAL_DOMAINS = REPOST_DOMAINS | AGGREGATOR_DOMAINS | CLUE_DOMAINS
TITLE_SUFFIX_PATTERN = re.compile(
    r"\s*[-_|]\s*(?:Yahoo|MSN|AOL|Reuters|Bloomberg|36Kr|36氪|盖世汽车|汽车之家|财联社|界面新闻|澎湃新闻|钛媒体)\s*$",
    re.IGNORECASE,
)

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
MATERIAL_TECH_KEYWORDS.extend(
    [
        "ultra-high-strength steel",
        "hot stamping steel",
        "die casting",
        "integrated die casting",
        "metal joining",
        "PP",
        "PE",
        "ABS",
        "PC",
        "PA",
        "POM",
        "PBT",
        "PET",
        "PPS",
        "PPA",
        "PEI",
        "LCP",
        "PI",
        "PEEK",
        "TPU",
        "TPE",
        "EPDM",
        "NBR",
        "HNBR",
        "FKM",
        "silicone rubber",
        "engineering plastics",
        "high performance plastics",
        "sealing material",
        "vibration damping",
        "foam material",
        "NVH",
        "SWIR",
        "infrared",
        "conductive material",
        "EMI shielding",
        "flexible electronics",
        "electronic skin",
        "thermal interface material",
        "TIM",
        "bipolar plate",
        "electrolyzer",
        "hydrogen storage",
        "PIR",
        "PCR",
        "bio-based material",
        "programmable material",
        "adaptive material",
        "AI for Materials",
        "materials foundation model",
        "space material",
        "extreme environment material",
        "超高强钢",
        "热成形钢",
        "铜合金",
        "金属连接",
        "一体化压铸",
        "增材制造金属",
        "工程塑料",
        "高性能塑料",
        "硅橡胶",
        "密封材料",
        "减振材料",
        "发泡材料",
        "NVH材料",
        "红外",
        "传感材料",
        "导电材料",
        "EMI屏蔽",
        "柔性电子",
        "电子皮肤",
        "智能表面",
        "热界面材料",
        "TIM材料",
        "储氢材料",
        "双极板",
        "电堆",
        "电解槽",
        "电池回收",
        "防腐",
        "耐磨",
        "防污",
        "防冰",
        "低摩擦涂层",
        "功能涂层",
        "PCR",
        "PIR",
        "生物基材料",
        "循环材料",
        "可降解材料",
        "可持续材料",
        "4D打印",
        "仿生材料",
        "材料大模型",
        "数字材料",
        "量子材料",
        "核聚变材料",
        "空间材料",
        "极端环境材料",
        "可编程材料",
        "自适应材料",
    ]
)

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
INDUSTRIALIZATION_KEYWORDS.extend(
    [
        "sampling",
        "sample delivery",
        "joint development",
        "co-development",
        "customer validation",
        "vehicle-grade",
        "automotive grade",
        "reliability test",
        "white paper",
        "送样",
        "验证",
        "合作",
        "联合开发",
        "供应商",
        "主机厂",
        "试点",
        "导入",
        "扩产",
        "白皮书",
        "测试",
        "客户验证",
        "车规级",
        "可靠性",
    ]
)

FUTURE_INTELLIGENCE_KEYWORDS = [
    "AI Agent",
    "AI Hardware",
    "humanoid robot",
    "embodied AI",
    "low-altitude economy",
    "eVTOL",
    "automation",
    "advanced manufacturing",
    "nuclear fusion",
    "space economy",
    "brain-computer interface",
    "future of work",
    "organization transformation",
    "first principles",
    "business model innovation",
    "energy transition",
    "robotics",
    "OpenAI",
    "NVIDIA",
    "Tesla Optimus",
    "Figure AI",
    "具身智能",
    "人形机器人",
    "低空经济",
    "飞行汽车",
    "AI硬件",
    "脑机接口",
    "核聚变",
    "空间产业",
    "未来职业",
    "组织变革",
    "第一性原理",
    "商业模式创新",
    "能源革命",
    "未来产业",
    "innovation",
    "创新",
    "research",
    "科学家",
]
FUTURE_SOURCE_KEYWORDS = [
    "OpenAI",
    "Anthropic",
    "NVIDIA",
    "Google Research",
    "DeepMind",
    "MIT Technology Review",
    "Stanford HAI",
    "麦肯锡",
    "BCG",
    "哈佛商业评论",
    "晚点",
    "远川",
]

CATEGORY_RULES: dict[str, list[str]] = {
    "未来趋势观察": FUTURE_INTELLIGENCE_KEYWORDS,
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

TECHNOLOGY_DRIVER_RULES: list[dict[str, Any]] = [
    {
        "driver": "机器人与具身智能",
        "keywords": ["robot", "humanoid", "embodied ai", "automation", "robotics", "机器人", "人形机器人", "具身智能"],
        "materials": "轻量化结构材料、减速器材料、柔性传感材料、导热材料、电池材料",
        "action": "供应商调研",
        "trend": "高",
    },
    {
        "driver": "低空经济/eVTOL",
        "keywords": ["evtol", "flying car", "low altitude", "低空经济", "飞行汽车", "小鹏汇天", "亿航"],
        "materials": "碳纤维复合材料、轻量化合金、阻燃材料、电池材料、热管理材料",
        "action": "前瞻储备",
        "trend": "高",
    },
    {
        "driver": "红外/短波感知",
        "keywords": ["lidar", "sensor", "infrared", "swir", "thermal imaging", "激光雷达", "红外", "热成像", "感知"],
        "materials": "光学材料、红外探测材料、封装材料、热管理材料",
        "action": "供应商调研",
        "trend": "中",
    },
    {
        "driver": "氢能/燃料电池",
        "keywords": ["hydrogen", "fuel cell", "氢能", "燃料电池"],
        "materials": "膜电极、催化剂、储氢材料、密封材料",
        "action": "持续跟踪",
        "trend": "中",
    },
    {
        "driver": "智能制造",
        "keywords": ["smart manufacturing", "additive manufacturing", "3d printing", "智能制造", "增材制造", "3d打印"],
        "materials": "金属粉末、增材制造材料、涂层材料、结构胶",
        "action": "供应商调研",
        "trend": "中",
    },
    {
        "driver": "自动驾驶/智能驾驶",
        "keywords": ["autonomous driving", "adas", "自动驾驶", "智能驾驶"],
        "materials": "传感材料、光学材料、封装材料、导热材料",
        "action": "持续跟踪",
        "trend": "中",
    },
    {
        "driver": "电池与储能",
        "keywords": ["battery", "energy storage", "solid-state", "sodium-ion", "固态电池", "钠离子", "储能", "电池"],
        "materials": "正负极材料、电解质、隔膜、集流体、热管理材料",
        "action": "启动验证",
        "trend": "高",
    },
    {
        "driver": "功率半导体",
        "keywords": ["sic", "gan", "power module", "power semiconductor", "碳化硅", "氮化镓", "功率模块", "功率半导体"],
        "materials": "封装材料、导热材料、绝缘材料、银烧结材料",
        "action": "供应商调研",
        "trend": "高",
    },
]

STAGE_RULES = [
    (
        "Validation",
        [
            "validation",
            "validated",
            "testing",
            "test",
            "certification",
            "certified",
            "road test",
            "reliability",
            "customer validation",
            "验证",
            "测试",
            "认证",
            "可靠性",
            "路试",
            "客户验证",
            "场景验证",
        ],
        "出现测试、认证、可靠性或客户场景验证信号，说明机会已进入价值验证阶段。",
    ),
    (
        "Joint Development",
        [
            "joint development",
            "co-development",
            "pilot project",
            "pilot production",
            "sample",
            "sampling",
            "supply agreement",
            "oem",
            "collaboration",
            "partnership",
            "送样",
            "联合开发",
            "合作开发",
            "试点项目",
            "中试",
            "供应协议",
            "主机厂项目",
            "定点",
            "配套",
            "供货",
        ],
        "已出现送样、联合开发、Pilot、OEM 合作、定点或供货信号，应进入方案确定阶段。",
    ),
    (
        "Supplier Research",
        [
            "supplier",
            "startup",
            "vendor",
            "research institute",
            "university",
            "spin-off",
            "company",
            "供应商",
            "初创",
            "研究机构",
            "高校",
            "产业链玩家",
            "谁能做",
        ],
        "主要价值在于识别供应商、初创公司、研究机构或产业链玩家，适合寻找资源。",
    ),
    (
        "Strategic Reserve",
        [
            "roadmap",
            "strategy",
            "long-term",
            "standard",
            "policy",
            "regulation",
            "investment",
            "路线图",
            "战略",
            "长期",
            "标准",
            "政策",
            "法规",
            "投资",
            "储备",
        ],
        "技术已有战略价值但导入节奏较长，适合形成长期储备。",
    ),
]


def infer_lifecycle_stage(item: dict[str, Any]) -> dict[str, str]:
    """Infer Material Opportunity Lifecycle stage from maturity signals."""
    text = _text_for_item(item)
    for stage, keywords, reason in STAGE_RULES:
        matches = _matched_keywords(text, keywords)
        if matches:
            return {"stage": stage, "stage_reason": f"{reason} 命中信号：{', '.join(matches[:4])}。"}
    if item.get("material_opportunity_score", 0) >= 60:
        return {
            "stage": "Strategic Reserve",
            "stage_reason": "材料机会分较高，但尚未出现送样、合作或验证证据，适合先进入战略储备。",
        }
    return {
        "stage": "Technology Watch",
        "stage_reason": "出现新技术、新材料、新工艺、新趋势或新应用信号，当前以发现机会和观察为主。",
    }


def infer_material_opportunity(item: dict[str, Any]) -> dict[str, Any]:
    """Infer technology-driver and material-validation fields by rules."""
    text = _text_for_item(item)
    rule_score = int(item.get("rule_score", 0) or 0)
    source_score = int(item.get("source_score", 0) or 0)
    matched_rule: dict[str, Any] | None = None

    for rule in TECHNOLOGY_DRIVER_RULES:
        if _matched_keywords(text, rule["keywords"]):
            matched_rule = rule
            break

    if not matched_rule:
        score = min(45, round(rule_score * 0.45 + source_score * 0.2))
        future_score = min(40, round(rule_score * 0.35 + source_score * 0.2))
        return {
            "why_it_matters": "该信息暂未显示明确的产业变化或材料导入信号，仅适合作为背景观察。",
            "technology_driver": "其他",
            "material_relevance": "材料相关性较弱，暂不优先。",
            "material_opportunity": "材料相关性较弱，暂不优先。",
            "validation_opportunity": "材料相关性较弱，暂不优先。建议仅作为背景趋势观察，暂不进入样件验证或供应商调研。",
            "suggested_action": "暂不优先",
            "trend_potential": "不确定",
            "future_signal": "未来信号不明确，建议等待更多原始来源或产业化证据。",
            "future_signal_score": max(0, future_score),
            "material_opportunity_score": max(0, score),
            "material_validation_score": max(0, score),
        }

    industrial_matches = _matched_keywords(text, INDUSTRIALIZATION_KEYWORDS)
    material_matches = detect_material_keywords(item)
    company_matches = detect_companies(item)
    score = 30
    score += min(25, len(material_matches) * 5)
    score += min(15, len(company_matches) * 5)
    score += min(15, len(industrial_matches) * 5)
    score += min(15, round(source_score / 100 * 15))
    if matched_rule["trend"] == "高":
        score += 8
    elif matched_rule["trend"] == "中":
        score += 4
    score = max(0, min(100, score))
    future_score = 25
    future_score += min(20, len(industrial_matches) * 6)
    future_score += min(15, len(company_matches) * 5)
    future_score += min(20, round(source_score / 100 * 20))
    future_score += 20 if matched_rule["trend"] == "高" else 10 if matched_rule["trend"] == "中" else 4
    future_score = max(0, min(100, future_score))

    if score >= 78 and matched_rule["action"] in {"启动验证", "供应商调研"}:
        action = matched_rule["action"]
    elif score >= 62:
        action = "供应商调研" if matched_rule["action"] == "启动验证" else matched_rule["action"]
    elif score >= 45:
        action = "持续跟踪"
    else:
        action = "前瞻储备"

    opportunity = (
        f"该技术动向可能牵引{matched_rule['materials']}需求。"
        f"当前材料验证分为 {score}，"
        f"{'具备样件验证或供应商调研价值。' if score >= 60 else '更适合作为前瞻储备或持续跟踪。'}"
    )
    why_it_matters = (
        f"这条信息指向{matched_rule['driver']}方向的变化，可能从技术演进进一步传导到材料选型、供应链调研和验证储备。"
    )
    future_signal = (
        f"{matched_rule['driver']}呈现{matched_rule['trend']}潜力信号，需观察头部企业、量产节奏、政策标准和供应链投入是否继续强化。"
    )
    return {
        "why_it_matters": why_it_matters,
        "technology_driver": matched_rule["driver"],
        "material_relevance": matched_rule["materials"],
        "material_opportunity": f"潜在材料机会包括{matched_rule['materials']}。可结合样件可得性、供应商成熟度和内部项目需求决定是否进入验证。",
        "validation_opportunity": opportunity,
        "suggested_action": action,
        "trend_potential": matched_rule["trend"],
        "future_signal": future_signal,
        "future_signal_score": future_score,
        "material_opportunity_score": score,
        "material_validation_score": score,
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


def _domain(url: str | None) -> str:
    return urlparse(str(url or "")).netloc.lower().removeprefix("www.")


def _domain_matches(domain: str, candidates: set[str]) -> bool:
    return any(domain == candidate or domain.endswith(f".{candidate}") for candidate in candidates)


def is_disallowed_final_url(url: str | None) -> bool:
    """Reject aggregator, repost, clue, and social writing domains as final links."""
    return _domain_matches(_domain(url), DISALLOWED_FINAL_DOMAINS)


def is_long_window_item(item: dict[str, Any]) -> bool:
    """Papers, patents, and standards may use a 90-day freshness window."""
    text = normalize_text(_text_for_item(item) + " " + str(item.get("source") or "") + " " + str(item.get("source_type") or ""))
    return any(
        keyword in text
        for keyword in (
            "paper",
            "journal",
            "patent",
            "standard",
            "nature",
            "science",
            "ieee",
            "sae",
            "wipo",
            "cnipa",
            "论文",
            "期刊",
            "专利",
            "标准",
        )
    )


def is_allowed_date_for_item(item: dict[str, Any], timezone_name: str = "Asia/Shanghai") -> bool:
    """Prefer current month; allow 90 days for papers, patents, and standards."""
    try:
        published = datetime.strptime(str(item.get("published_date")), "%Y-%m-%d").date()
    except ValueError:
        return False
    now = datetime.now(ZoneInfo(timezone_name)).date()
    if is_long_window_item(item):
        return now - timedelta(days=90) <= published <= now
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


def attach_flow_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Attach AURA information-flow fields at candidate stage."""
    text = _text_for_item(item)
    material_direct = bool(
        detect_material_keywords(item)
        or detect_companies(item)
        or str(item.get("source_type") or "") in {"company_news_page", "journal_rss", "government_policy"}
    )
    future_source = str(item.get("source_group") or "") == "future_intelligence" or bool(
        _matched_keywords(str(item.get("source") or ""), FUTURE_SOURCE_KEYWORDS)
    )
    future_hit = bool(_matched_keywords(text, FUTURE_INTELLIGENCE_KEYWORDS)) or future_source
    material_hit = material_direct
    if not material_hit and not future_hit:
        material_hit = True
    material_score = int(item.get("material_opportunity_score", item.get("material_validation_score", 0)) or 0)
    future_score = int(item.get("future_signal_score", 0) or 0)
    if future_hit and not material_direct:
        item["future_signal_score"] = max(future_score, 72 if future_source else 62)
        item["material_opportunity_score"] = min(material_score, 30)
        item["material_validation_score"] = min(int(item.get("material_validation_score", material_score) or 0), 30)
        primary_flow = "future_intelligence"
        secondary_flow = ""
    elif material_hit and future_hit:
        primary_flow = "material_intelligence" if material_score >= future_score else "future_intelligence"
        secondary_flow = "future_intelligence" if primary_flow == "material_intelligence" else "material_intelligence"
    elif future_hit:
        primary_flow = "future_intelligence"
        secondary_flow = ""
    else:
        primary_flow = "material_intelligence"
        secondary_flow = ""
    module_targets: list[str] = []
    if primary_flow == "material_intelligence" or secondary_flow == "material_intelligence":
        module_targets.extend(["today_key_insight", "bookshelf", "suggested_actions"])
    if primary_flow == "future_intelligence" or secondary_flow == "future_intelligence":
        module_targets.extend(["future_signals"])
    item["flow_type"] = primary_flow
    item["primary_flow"] = primary_flow
    item["secondary_flow"] = secondary_flow
    if primary_flow == "material_intelligence":
        item["material_opportunity_score"] = max(
            int(item.get("material_opportunity_score", 0) or 0),
            min(100, int(item.get("future_signal_score", 0) or 0) + 1),
        )
        item["material_validation_score"] = max(
            int(item.get("material_validation_score", 0) or 0),
            item["material_opportunity_score"],
        )
    item["reason_for_flow"] = (
        "内容直接关联材料机会、供应商、验证、专利、论文、标准或汽车材料应用。"
        if primary_flow == "material_intelligence"
        else "内容主要用于理解未来趋势、产业变化、技术范式或组织方法变化。"
    )
    item["module_targets"] = module_targets
    return item


def canonical_url(url: str | None) -> str:
    """Canonicalize URLs across tracking, mobile host, and trailing slash variants."""
    cleaned = _clean_url(url)
    if not cleaned:
        return ""
    parsed = urlparse(cleaned)
    host = parsed.netloc.lower()
    if host.startswith("m."):
        host = host[2:]
    path = re.sub(r"/+$", "", parsed.path or "")
    if not path:
        path = "/"
    return urlunparse((parsed.scheme.lower(), host, path, "", parsed.query, ""))


def normalized_title(title: str | None) -> str:
    """Normalize titles for cross-source event matching."""
    text = TITLE_SUFFIX_PATTERN.sub("", str(title or "")).casefold()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    stopwords = {"the", "a", "an", "to", "of", "and", "for", "in", "on", "with", "as"}
    tokens = [token for token in text.split() if token and token not in stopwords]
    return " ".join(tokens)


def event_id_for_item(item: dict[str, Any]) -> str:
    """Create stable event id from title plus material/company context."""
    companies = sorted(str(value).casefold() for value in item.get("detected_companies", [])[:4])
    materials = sorted(str(value).casefold() for value in item.get("detected_material_keywords", [])[:5])
    base = "|".join(
        [
            normalized_title(item.get("title")),
            str(item.get("category") or ""),
            ",".join(companies),
            ",".join(materials),
        ]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _text_for_item(item: dict[str, Any]) -> str:
    """Combine title and summary for deterministic rule matching."""
    return f"{item.get('title', '')} {item.get('summary', '')}"


def _contains_keyword(text: str, keyword: str) -> bool:
    """Keyword matching helper for English and Chinese terms."""
    normalized = normalize_text(text)
    normalized_keyword = normalize_text(keyword)
    if re.fullmatch(r"[a-z0-9]{1,4}", normalized_keyword):
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])", normalized) is not None
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
    future_matches = _matched_keywords(text, FUTURE_INTELLIGENCE_KEYWORDS)

    automotive_points = min(20, len(automotive_matches) * 5)
    material_points = min(25, len(material_matches) * 4)
    company_points = min(15, len(company_matches) * 5)
    industrial_points = min(10, len(industrial_matches) * 3)
    future_points = min(25, len(future_matches) * 5)
    current_month_points = 5

    total = min(
        100,
        source_points
        + automotive_points
        + material_points
        + company_points
        + industrial_points
        + future_points
        + current_month_points,
    )

    reason = (
        f"source={source_points}; automotive={automotive_points} "
        f"({', '.join(automotive_matches[:4]) or 'none'}); "
        f"materials={material_points} ({', '.join(material_matches[:5]) or 'none'}); "
        f"companies={company_points} ({', '.join(company_matches[:4]) or 'none'}); "
        f"industrial={industrial_points} ({', '.join(industrial_matches[:4]) or 'none'}); "
        f"future={future_points} ({', '.join(future_matches[:4]) or 'none'}); "
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

        if not title or not published_date or not url or is_disallowed_final_url(url):
            skipped_missing += 1
            continue

        item = deepcopy(raw_item)
        item["title"] = title
        item["published_date"] = published_date
        item["url"] = url

        if not is_allowed_date_for_item(item, timezone_name):
            skipped_month += 1
            continue

        rule_score, filter_reason = calculate_relevance_score(item)
        if rule_score < min_rule_score:
            skipped_low_score += 1
            continue

        item["rule_score"] = rule_score
        item["category"] = detect_category(item)
        item["subcategory"] = detect_subcategory(item)
        item["detected_companies"] = detect_companies(item)
        item["detected_material_keywords"] = detect_material_keywords(item)
        item.update(infer_material_opportunity(item))
        lifecycle = infer_lifecycle_stage(item)
        item.update(lifecycle)
        item["suggested_action"] = item["stage"]
        item = attach_flow_fields(item)
        item["filter_reason"] = filter_reason
        item["needs_ai_analysis"] = True
        item["canonical_url"] = canonical_url(url)
        item["normalized_title"] = normalized_title(title)
        item["event_id"] = event_id_for_item(item)
        item["_normalized_title"] = item["normalized_title"]
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
    seen_events: set[str] = set()
    skipped_duplicates = 0

    for item in valid_items:
        url = item.get("canonical_url") or item.get("url", "")
        title_key = item.get("_normalized_title", "")
        event_id = item.get("event_id", "")
        if event_id in seen_events or url in seen_urls or any(
            _is_similar_title(title_key, seen_title, max_title_similarity)
            for seen_title in seen_titles
        ):
            skipped_duplicates += 1
            continue

        seen_urls.add(url)
        if event_id:
            seen_events.add(event_id)
        seen_titles.append(title_key)
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

"""Analyze filtered news candidates with DeepSeek.

This stage reads data/news_filtered.json, reuses successful existing analyses,
and calls DeepSeek only for the highest-scoring remaining candidates within the
configured daily API budget. DeepSeek is never treated as a news source; it may
only analyze the metadata already collected by previous stages.
"""

from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
FILTERED_NEWS_PATH = PROJECT_ROOT / "data" / "news_filtered.json"
ANALYZED_NEWS_PATH = PROJECT_ROOT / "data" / "news_analyzed.json"
ENV_PATH = PROJECT_ROOT / ".env"

DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_MAX_AI_ANALYSIS = 8
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 1200
REQUEST_TIMEOUT_SECONDS = 45
RETRYABLE_STATUSES = {
    "failed_api",
    "skipped_no_api_key",
    "failed_json_parse",
    "fallback",
    "",
}

ALLOWED_MATURITY = {"lab", "pilot", "production", "policy", "market", "unknown"}
ALLOWED_PRIORITY = {"P0", "P1", "P2", "P3"}
ALLOWED_SUGGESTED_ACTION = {"启动验证", "供应商调研", "持续跟踪", "前瞻储备", "暂不优先"}
ALLOWED_TREND_POTENTIAL = {"高", "中", "低", "不确定"}

PROMPT_FIELDS = [
    "title",
    "source",
    "published_date",
    "url",
    "summary",
    "category",
    "subcategory",
    "detected_companies",
    "detected_material_keywords",
]

OUTPUT_FIELDS = [
    "title",
    "source",
    "published_date",
    "url",
    "category",
    "subcategory",
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
    "analysis_status",
]


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load config and fill DeepSeek defaults."""
    if not path.exists():
        logging.warning("Config file not found: %s; using defaults.", path)
        return {
            "limits": {"max_ai_analysis": DEFAULT_MAX_AI_ANALYSIS},
            "deepseek_model": DEFAULT_MODEL,
            "deepseek_temperature": DEFAULT_TEMPERATURE,
            "deepseek_max_tokens": DEFAULT_MAX_TOKENS,
        }

    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    config.setdefault("limits", {})
    config["limits"].setdefault("max_ai_analysis", DEFAULT_MAX_AI_ANALYSIS)
    config.setdefault("deepseek_model", DEFAULT_MODEL)
    config.setdefault("deepseek_temperature", DEFAULT_TEMPERATURE)
    config.setdefault("deepseek_max_tokens", DEFAULT_MAX_TOKENS)
    return config


def load_json(path: Path) -> list[dict[str, Any]]:
    """Load a JSON list, returning an empty list when the file is absent."""
    if not path.exists():
        logging.warning("JSON file not found: %s", path)
        return []

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list in {path}")

    return [item for item in data if isinstance(item, dict)]


def save_json(items: list[dict[str, Any]], path: Path) -> None:
    """Write UTF-8 JSON output for downstream ranking."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(items, file, ensure_ascii=False, indent=2)
        file.write("\n")


def load_env(env_path: Path = ENV_PATH) -> dict[str, str]:
    """Load environment variables from .env and process environment."""
    load_dotenv(env_path)
    return {
        "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", "").strip(),
        "FORCE_REANALYZE_FAILED": os.getenv("FORCE_REANALYZE_FAILED", "").strip().lower(),
    }


def normalize_url(url: str | None) -> str:
    """Normalize URL for matching existing analyses."""
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


def _prompt_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Keep only the fields allowed to be sent to DeepSeek."""
    return {field: item.get(field, "" if field not in {"detected_companies", "detected_material_keywords"} else []) for field in PROMPT_FIELDS}


def build_prompt(item: dict[str, Any]) -> list[dict[str, str]]:
    """Build strict JSON-only chat messages for one news item."""
    system_prompt = (
        "你不是普通新闻编辑。你是汽车新材料研究员和技术情报分析员。"
        "你的任务不是判断新闻是否热门，而是判断它是否可能带来材料导入、材料验证、供应链调研或技术储备机会。"
        "分析时必须回答：1. 这是什么技术动向？2. 它可能牵引哪些材料需求？"
        "3. 这些材料是否接近可验证？4. 对材料科室建议采取什么动作？"
        "不得编造未提供的新闻事实、日期、来源、企业、参数或链接。"
        "如果新闻与材料关系弱，必须明确写“材料相关性较弱，暂不优先。”"
        "如果信息不足，请写“信息不足”或“unknown”。必须输出严格 JSON。所有字段必须完整。"
    )
    user_prompt = {
        "task": "请基于以下新闻元数据生成结构化研究分析。不得添加输入中没有的事实。",
        "news_metadata": _prompt_payload(item),
        "required_output_schema": {
            "title": "",
            "source": "",
            "published_date": "",
            "url": "",
            "category": "",
            "subcategory": "",
            "summary": "100-180字中文摘要",
            "technical_points": ["3-5个技术要点"],
            "materials_involved": ["涉及材料或技术关键词"],
            "companies_or_institutions": ["涉及企业/机构"],
            "impact_assessment": "对汽车产业链或研发方向的影响",
            "research_value": "对汽车材料研究员的参考价值",
            "industrial_maturity": "lab/pilot/production/policy/market/unknown",
            "priority": "P0/P1/P2/P3",
            "confidence": "0-100",
            "follow_up": "true/false",
            "one_sentence": "用于机器人推送的一句话概括",
            "why_it_matters": "为什么这条新闻值得研发人员关注，1-2句话，必须回到产业变化、技术演进或材料需求",
            "technology_driver": "新技术牵引方向，如机器人与具身智能、低空经济/eVTOL、自动驾驶、智能座舱、红外/短波感知、热成像、AI硬件、氢能、储能、车路协同、智能制造、航空航天轻量化、未来交通、其他",
            "material_relevance": "该技术可能牵引的材料方向，如轻量化复合材料、热管理材料、光学材料、导热材料、结构胶、阻燃材料、传感材料、固态电解质、硅碳负极、SiC/GaN封装材料、低成本高强材料等",
            "material_opportunity": "材料机会层判断，说明可能形成哪些材料需求、替代机会、供应链机会或长期储备方向，1-3句话",
            "validation_opportunity": "1-3句话，判断是否有样件验证价值、是否值得供应商调研、是否适合前瞻储备、是否距离量产太远",
            "suggested_action": "启动验证/供应商调研/持续跟踪/前瞻储备/暂不优先",
            "trend_potential": "高/中/低/不确定",
            "future_signal": "未来信号层判断，说明这条新闻释放了什么产业或技术趋势信号，1-2句话",
            "future_signal_score": "0-100，衡量未来产业影响力，参考技术突破、产业化进展、政策推动、资本投入、标准制定和供应链变化",
            "material_opportunity_score": "0-100，衡量对材料团队的价值，重点看是否可能形成材料需求、是否值得验证、是否值得供应商调研、是否值得长期储备",
            "material_validation_score": "0-100，兼容字段，数值应与 material_opportunity_score 保持一致或接近",
            "analysis_status": "success",
        },
        "priority_rules": {
            "P0": "重大产业化、量产、政策标准、头部企业核心突破",
            "P1": "重要技术进展、论文、专利、供应链合作",
            "P2": "普通企业动态或趋势新闻",
            "P3": "相关性较弱但可参考",
        },
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
    ]


def call_deepseek(
    item: dict[str, Any], api_key: str, config: dict[str, Any]
) -> str:
    """Call DeepSeek OpenAI-compatible chat completions endpoint."""
    payload = {
        "model": config.get("deepseek_model", DEFAULT_MODEL),
        "messages": build_prompt(item),
        "temperature": float(config.get("deepseek_temperature", DEFAULT_TEMPERATURE)),
        "max_tokens": int(config.get("deepseek_max_tokens", DEFAULT_MAX_TOKENS)),
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        DEEPSEEK_ENDPOINT,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def extract_json_from_response(response_text: str) -> dict[str, Any] | None:
    """Parse JSON object from model output, including fenced JSON fallback."""
    if not response_text:
        return None

    try:
        parsed = json.loads(response_text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.S)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    brace_match = re.search(r"\{.*\}", response_text, re.S)
    if brace_match:
        try:
            parsed = json.loads(brace_match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    return None


def fallback_analysis(item: dict[str, Any], status: str) -> dict[str, Any]:
    """Create deterministic fallback output without inventing facts."""
    title = str(item.get("title") or "")
    raw_summary = str(item.get("summary") or "").strip()
    return {
        "title": title,
        "source": item.get("source", ""),
        "published_date": item.get("published_date", ""),
        "url": item.get("url", ""),
        "category": item.get("category", "其他"),
        "subcategory": item.get("subcategory", ""),
        "summary": raw_summary or title,
        "technical_points": [],
        "materials_involved": item.get("detected_material_keywords", []) or [],
        "companies_or_institutions": item.get("detected_companies", []) or [],
        "impact_assessment": (
            "DeepSeek API 调用失败，暂未生成影响评估。"
            if status == "failed_api"
            else "未配置 DeepSeek API Key，暂未生成影响评估。"
            if status == "skipped_no_api_key"
            else "DeepSeek 返回 JSON 解析失败，暂未生成影响评估。"
        ),
        "research_value": (
            "DeepSeek API 调用失败，暂未生成研究价值判断。"
            if status == "failed_api"
            else "未配置 DeepSeek API Key，暂未生成研究价值判断。"
            if status == "skipped_no_api_key"
            else "DeepSeek 返回 JSON 解析失败，暂未生成研究价值判断。"
        ),
        "industrial_maturity": "unknown",
        "priority": "P3",
        "confidence": 0,
        "follow_up": False,
        "one_sentence": title,
        "why_it_matters": item.get(
            "why_it_matters",
            item.get("impact_assessment", "信息不足，暂无法判断其产业或材料意义。"),
        ),
        "technology_driver": item.get("technology_driver", "其他"),
        "material_relevance": item.get("material_relevance", "材料相关性较弱，暂不优先。"),
        "material_opportunity": item.get(
            "material_opportunity",
            item.get("material_relevance", "材料相关性较弱，暂不优先。"),
        ),
        "validation_opportunity": item.get(
            "validation_opportunity",
            "材料相关性较弱，暂不优先。建议仅作为背景趋势观察，暂不进入样件验证或供应商调研。",
        ),
        "suggested_action": item.get("suggested_action", "暂不优先"),
        "trend_potential": item.get("trend_potential", "不确定"),
        "future_signal": item.get(
            "future_signal",
            f"{item.get('technology_driver', '其他')}方向释放弱信号，需结合更多来源持续观察。",
        ),
        "future_signal_score": item.get("future_signal_score", 0),
        "material_opportunity_score": item.get(
            "material_opportunity_score",
            item.get("material_validation_score", 0),
        ),
        "material_validation_score": item.get("material_validation_score", 0),
        "analysis_status": status,
    }


def _normalize_analysis(parsed: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Ensure model output has every required field and valid enum values."""
    normalized = fallback_analysis(item, "failed_json_parse")
    normalized.update({key: parsed.get(key, normalized[key]) for key in OUTPUT_FIELDS})

    # Preserve source-of-truth metadata from collected news, not the model.
    for key in ("title", "source", "published_date", "url", "category", "subcategory"):
        normalized[key] = item.get(key, normalized.get(key, ""))

    if not isinstance(normalized.get("technical_points"), list):
        normalized["technical_points"] = []
    if not isinstance(normalized.get("materials_involved"), list):
        normalized["materials_involved"] = item.get("detected_material_keywords", []) or []
    if not isinstance(normalized.get("companies_or_institutions"), list):
        normalized["companies_or_institutions"] = item.get("detected_companies", []) or []

    maturity = str(normalized.get("industrial_maturity", "unknown"))
    normalized["industrial_maturity"] = maturity if maturity in ALLOWED_MATURITY else "unknown"

    priority = str(normalized.get("priority", "P3"))
    normalized["priority"] = priority if priority in ALLOWED_PRIORITY else "P3"

    try:
        confidence = int(float(normalized.get("confidence", 0)))
    except (TypeError, ValueError):
        confidence = 0
    normalized["confidence"] = max(0, min(100, confidence))

    normalized["follow_up"] = bool(normalized.get("follow_up", False))
    action = str(normalized.get("suggested_action") or item.get("suggested_action") or "暂不优先")
    normalized["suggested_action"] = action if action in ALLOWED_SUGGESTED_ACTION else "暂不优先"

    trend = str(normalized.get("trend_potential") or item.get("trend_potential") or "不确定")
    normalized["trend_potential"] = trend if trend in ALLOWED_TREND_POTENTIAL else "不确定"

    for key, default in (
        ("why_it_matters", "信息不足，暂无法判断其产业或材料意义。"),
        ("technology_driver", "其他"),
        ("material_relevance", "材料相关性较弱，暂不优先。"),
        ("material_opportunity", "材料相关性较弱，暂不优先。"),
        ("validation_opportunity", "材料相关性较弱，暂不优先。"),
        ("future_signal", "未来信号不明确，建议仅作为背景观察。"),
    ):
        if not str(normalized.get(key) or "").strip():
            normalized[key] = item.get(key, default)
    if not str(normalized.get("material_opportunity") or "").strip():
        normalized["material_opportunity"] = normalized.get("material_relevance", "材料相关性较弱，暂不优先。")
    if not str(normalized.get("why_it_matters") or "").strip():
        normalized["why_it_matters"] = normalized.get("impact_assessment", "信息不足，暂无法判断其产业或材料意义。")

    try:
        future_score = int(float(normalized.get("future_signal_score", item.get("future_signal_score", 0))))
    except (TypeError, ValueError):
        future_score = int(item.get("future_signal_score", 0) or 0)
    normalized["future_signal_score"] = max(0, min(100, future_score))

    try:
        opportunity_score = int(float(normalized.get("material_opportunity_score", item.get("material_opportunity_score", item.get("material_validation_score", 0)))))
    except (TypeError, ValueError):
        opportunity_score = int(item.get("material_opportunity_score", item.get("material_validation_score", 0)) or 0)
    normalized["material_opportunity_score"] = max(0, min(100, opportunity_score))

    try:
        material_score = int(float(normalized.get("material_validation_score", normalized["material_opportunity_score"])))
    except (TypeError, ValueError):
        material_score = normalized["material_opportunity_score"]
    normalized["material_validation_score"] = max(0, min(100, material_score))
    normalized["analysis_status"] = "success"
    return {field: normalized.get(field) for field in OUTPUT_FIELDS}


def _ensure_analysis_fields(existing: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Backfill newly required fields on reused successful analyses."""
    normalized = fallback_analysis(item, "success")
    normalized.update(existing)
    weak_values = {
        "信息不足，暂无法判断其产业或材料意义。",
        "材料相关性较弱，暂不优先。",
        "未来信号不明确，建议仅作为背景观察。",
    }
    for key in (
        "technology_driver",
        "material_relevance",
        "material_opportunity",
        "validation_opportunity",
        "suggested_action",
        "trend_potential",
        "why_it_matters",
        "future_signal",
        "future_signal_score",
        "material_opportunity_score",
        "material_validation_score",
    ):
        if normalized.get(key) in (None, ""):
            normalized[key] = item.get(key, fallback_analysis(item, "success").get(key))
        elif key == "technology_driver" and normalized.get(key) == "其他" and item.get(key) not in (None, "", "其他"):
            normalized[key] = item[key]
        elif key in {"why_it_matters", "material_relevance", "material_opportunity", "validation_opportunity", "future_signal"}:
            item_value = item.get(key)
            if str(normalized.get(key)).strip() in weak_values and item_value:
                normalized[key] = item_value
        elif key in {"future_signal_score", "material_opportunity_score", "material_validation_score"}:
            try:
                current_score = int(float(normalized.get(key, 0) or 0))
                item_score = int(float(item.get(key, 0) or 0))
            except (TypeError, ValueError):
                current_score = 0
                item_score = 0
            if current_score == 0 and item_score > 0:
                normalized[key] = item_score
    return _normalize_analysis(normalized, item)


def merge_existing_analysis(
    filtered_items: list[dict[str, Any]],
    existing_items: list[dict[str, Any]],
    force_reanalyze_failed: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, int]:
    """Reuse only successful analyses by URL and return pending candidates."""
    success_by_url = {
        normalize_url(item.get("url")): item
        for item in existing_items
        if normalize_url(item.get("url")) and item.get("analysis_status") == "success"
    }
    retryable_by_url = {
        normalize_url(item.get("url")): item
        for item in existing_items
        if normalize_url(item.get("url"))
        and item.get("analysis_status", "") in RETRYABLE_STATUSES
    }

    reused: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    retryable_count = 0
    for item in filtered_items:
        normalized_url = normalize_url(item.get("url"))
        existing = success_by_url.get(normalized_url)
        if existing:
            reused.append(_ensure_analysis_fields(existing, item))
        else:
            if normalized_url in retryable_by_url or force_reanalyze_failed:
                retryable_count += 1
            pending.append(item)

    return reused, pending, len(reused), retryable_count


def analyze_news_items(
    filtered_items: list[dict[str, Any]],
    existing_items: list[dict[str, Any]],
    config: dict[str, Any],
    api_key: str,
    force_reanalyze_failed: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int | bool]]:
    """Analyze top filtered items within API budget, reusing prior successes."""
    max_ai_analysis = int(
        config.get("limits", {}).get("max_ai_analysis", DEFAULT_MAX_AI_ANALYSIS)
    )
    sorted_items = sorted(
        filtered_items,
        key=lambda item: (
            int(item.get("rule_score", 0) or 0),
            item.get("published_date", ""),
            int(item.get("source_score", 0) or 0),
        ),
        reverse=True,
    )
    selected_items = sorted_items[:max_ai_analysis]

    reused, pending, reused_count, retryable_count = merge_existing_analysis(
        selected_items,
        existing_items,
        force_reanalyze_failed,
    )

    analyzed: list[dict[str, Any]] = list(reused)
    api_calls = 0
    fallback_count = 0
    skipped_no_api_key = False
    network_or_api_issue = False

    for item in pending:
        if not api_key:
            analyzed.append(fallback_analysis(item, "skipped_no_api_key"))
            fallback_count += 1
            skipped_no_api_key = True
            continue

        try:
            response_text = call_deepseek(item, api_key, config)
            api_calls += 1
        except requests.RequestException as exc:
            logging.warning("DeepSeek API request failed for URL %s: %s", item.get("url"), exc)
            analyzed.append(fallback_analysis(item, "failed_api"))
            fallback_count += 1
            network_or_api_issue = True
            continue
        except (KeyError, ValueError, TypeError) as exc:
            logging.warning("DeepSeek API response failed for URL %s: %s", item.get("url"), exc)
            analyzed.append(fallback_analysis(item, "failed_api"))
            fallback_count += 1
            network_or_api_issue = True
            continue

        parsed = extract_json_from_response(response_text)
        if parsed is None:
            analyzed.append(fallback_analysis(item, "failed_json_parse"))
            fallback_count += 1
            continue

        analyzed.append(_normalize_analysis(parsed, item))

    # Preserve the same order as selected_items.
    analyzed_by_url = {item.get("url"): item for item in analyzed if item.get("url")}
    ordered = [analyzed_by_url[item.get("url")] for item in selected_items if item.get("url") in analyzed_by_url]

    stats: dict[str, int | bool] = {
        "filtered_count": len(filtered_items),
        "selected_count": len(selected_items),
        "reused_count": reused_count,
        "retryable_count": retryable_count,
        "api_calls": api_calls,
        "fallback_count": fallback_count,
        "skipped_no_api_key": skipped_no_api_key,
        "network_or_api_issue": network_or_api_issue,
    }
    return ordered, stats


def main() -> None:
    """Run DeepSeek analysis with strict API budget control."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = load_config()
    env = load_env()
    api_key = env.get("DEEPSEEK_API_KEY", "")
    force_reanalyze_failed = env.get("FORCE_REANALYZE_FAILED") == "true"

    filtered_items = load_json(FILTERED_NEWS_PATH)
    existing_items = load_json(ANALYZED_NEWS_PATH)
    logging.info("news_filtered.json loaded: %s items.", len(filtered_items))

    analyzed_items, stats = analyze_news_items(
        filtered_items,
        existing_items,
        config,
        api_key,
        force_reanalyze_failed,
    )
    save_json(analyzed_items, ANALYZED_NEWS_PATH)

    logging.info("Existing successful analyses reused: %s.", stats["reused_count"])
    logging.info("Failed or missing analyses scheduled for retry: %s.", stats["retryable_count"])
    logging.info("Actual DeepSeek API calls this run: %s.", stats["api_calls"])
    logging.info("Fallback analyses generated: %s.", stats["fallback_count"])
    logging.info("Saved news_analyzed.json items: %s.", len(analyzed_items))
    if stats["skipped_no_api_key"]:
        logging.info("Real API calls skipped because DEEPSEEK_API_KEY is not configured.")
    if stats["network_or_api_issue"]:
        logging.info("Some real API calls were skipped due to network or API errors.")


if __name__ == "__main__":
    main()

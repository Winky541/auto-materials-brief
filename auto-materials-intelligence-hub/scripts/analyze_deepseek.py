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

ALLOWED_MATURITY = {"lab", "pilot", "production", "policy", "market", "unknown"}
ALLOWED_PRIORITY = {"P0", "P1", "P2", "P3"}

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
    return {"DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", "").strip()}


def _prompt_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Keep only the fields allowed to be sent to DeepSeek."""
    return {field: item.get(field, "" if field not in {"detected_companies", "detected_material_keywords"} else []) for field in PROMPT_FIELDS}


def build_prompt(item: dict[str, Any]) -> list[dict[str, str]]:
    """Build strict JSON-only chat messages for one news item."""
    system_prompt = (
        "你是汽车新材料与前沿技术研究员。你只能基于用户提供的新闻元数据进行分析。"
        "不得编造未提供的新闻事实、日期、来源、企业、参数或链接。"
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
    normalized["analysis_status"] = "success"
    return {field: normalized.get(field) for field in OUTPUT_FIELDS}


def merge_existing_analysis(
    filtered_items: list[dict[str, Any]], existing_items: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Reuse existing success analyses by URL and return pending candidates."""
    success_by_url = {
        item.get("url"): item
        for item in existing_items
        if item.get("url") and item.get("analysis_status") == "success"
    }

    reused: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for item in filtered_items:
        existing = success_by_url.get(item.get("url"))
        if existing:
            reused.append(existing)
        else:
            pending.append(item)

    return reused, pending, len(reused)


def analyze_news_items(
    filtered_items: list[dict[str, Any]],
    existing_items: list[dict[str, Any]],
    config: dict[str, Any],
    api_key: str,
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

    reused, pending, reused_count = merge_existing_analysis(selected_items, existing_items)

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

    filtered_items = load_json(FILTERED_NEWS_PATH)
    existing_items = load_json(ANALYZED_NEWS_PATH)
    logging.info("news_filtered.json loaded: %s items.", len(filtered_items))

    analyzed_items, stats = analyze_news_items(filtered_items, existing_items, config, api_key)
    save_json(analyzed_items, ANALYZED_NEWS_PATH)

    logging.info("Existing successful analyses reused: %s.", stats["reused_count"])
    logging.info("Actual DeepSeek API calls this run: %s.", stats["api_calls"])
    logging.info("Fallback analyses generated: %s.", stats["fallback_count"])
    logging.info("Saved news_analyzed.json items: %s.", len(analyzed_items))
    if stats["skipped_no_api_key"]:
        logging.info("Real API calls skipped because DEEPSEEK_API_KEY is not configured.")
    if stats["network_or_api_issue"]:
        logging.info("Some real API calls were skipped due to network or API errors.")


if __name__ == "__main__":
    main()

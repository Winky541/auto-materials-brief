"""Push today's AURA summary to DingTalk.

This stage reads data/today_selected.json and formats a Markdown group message.
If DINGTALK_WEBHOOK is not configured, it runs in dry-run mode and prints the
message only. It does not call DeepSeek, build the site, or change ranking data.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TODAY_SELECTED_PATH = PROJECT_ROOT / "data" / "today_selected.json"
ENV_PATH = PROJECT_ROOT / ".env"

# Keep this exact phrase in every DingTalk message body for keyword validation.
MESSAGE_TITLE = "AURA｜未来产业、技术与材料情报平台"
REQUEST_TIMEOUT_SECONDS = 20

CATEGORY_ORDER = [
    ("🔋", "电池与储能材料"),
    ("🧱", "轻量化与结构材料"),
    ("🧬", "复合材料"),
    ("🧠", "智能与功能材料"),
    ("🔥", "热管理与安全材料"),
    ("⚡", "电驱与电子材料"),
    ("♻️", "可持续与循环材料"),
    ("🏭", "先进制造工艺"),
]

PRIORITY_WEIGHT = {"P0": 4, "P1": 3, "P2": 2, "P3": 1}


def load_json(path: Path) -> dict[str, Any]:
    """Load today's selected news JSON."""
    if not path.exists():
        logging.warning("today_selected.json not found: %s", path)
        return {"date": "", "count": 0, "items": []}

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")

    data.setdefault("items", [])
    data.setdefault("count", len(data["items"]))
    return data


def load_env(env_path: Path = ENV_PATH) -> dict[str, str]:
    """Load bot settings from .env and process environment."""
    load_dotenv(env_path)
    return {
        "DINGTALK_WEBHOOK": os.getenv("DINGTALK_WEBHOOK", "").strip(),
        "DINGTALK_SECRET": os.getenv("DINGTALK_SECRET", "").strip(),
        "SITE_URL": os.getenv("SITE_URL", "").strip(),
    }


def group_items_by_category(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group up to eight selected news items by configured push categories."""
    grouped = {category: [] for _, category in CATEGORY_ORDER}
    for item in items[:8]:
        category = str(item.get("category") or "")
        if category in grouped:
            grouped[category].append(item)
    return grouped


def _brief_text(item: dict[str, Any]) -> str:
    text = str(item.get("one_sentence") or "").strip()
    if text:
        return text

    summary = str(item.get("summary") or "").strip()
    if summary:
        return summary[:60] + ("..." if len(summary) > 60 else "")

    return str(item.get("title") or "信息不足").strip()


def _markdown_link(label: str, url: str) -> str:
    if url:
        return f"[{label}]({url})"
    return label


def _top_follow_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        items,
        key=lambda item: (
            bool(item.get("follow_up")),
            PRIORITY_WEIGHT.get(str(item.get("priority") or "P3"), 1),
            int(item.get("final_score", 0) or 0),
            int(item.get("confidence", 0) or 0),
        ),
        reverse=True,
    )
    return ranked[:2]


def build_markdown_message(today_payload: dict[str, Any], site_url: str) -> str:
    """Build the DingTalk Markdown brief message."""
    date = today_payload.get("date") or "unknown"
    items = [item for item in today_payload.get("items", []) if isinstance(item, dict)][:8]
    grouped = group_items_by_category(items)

    lines = [
        f"【{MESSAGE_TITLE}】",
        f"📅 日期：{date}",
        "",
    ]

    for icon, category in CATEGORY_ORDER:
        lines.append(f"{icon} {category}：")
        category_items = grouped.get(category, [])
        if category_items:
            for item in category_items:
                label = _brief_text(item)
                url = str(item.get("url") or "").strip()
                lines.append(f"* {_markdown_link(label, url)}")
        else:
            lines.append("* 今日暂无入选")
        lines.append("")

    lines.append("📌 今日重点跟踪：")
    if items:
        for item in _top_follow_items(items):
            label = _brief_text(item)
            url = str(item.get("url") or "").strip()
            reasons: list[str] = []
            if item.get("follow_up"):
                reasons.append("标记为值得跟踪")
            if item.get("priority"):
                reasons.append(f"优先级 {item.get('priority')}")
            if item.get("final_score") is not None:
                reasons.append(f"final_score {item.get('final_score')}")
            reason = "，".join(reasons) if reasons else "入选今日精选"
            lines.append(f"* {_markdown_link(label, url)}：{reason}")
    else:
        lines.append("* 今日暂无达到发布条件的新闻")

    lines.extend(
        [
            "",
            "阅读全文：",
            site_url or "网站链接未配置",
        ]
    )
    return "\n".join(lines)


def sign_dingtalk_url(webhook: str, secret: str) -> str:
    """Apply DingTalk custom robot HMAC-SHA256 signing when secret exists."""
    if not secret:
        return webhook

    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    secret_bytes = secret.encode("utf-8")
    sign = base64.b64encode(
        hmac.new(secret_bytes, string_to_sign, digestmod=hashlib.sha256).digest()
    )
    encoded_sign = quote_plus(sign.decode("utf-8"))
    separator = "&" if "?" in webhook else "?"
    return f"{webhook}{separator}timestamp={timestamp}&sign={encoded_sign}"


def send_dingtalk_markdown(webhook: str, secret: str, title: str, text: str) -> bool:
    """Send Markdown payload to DingTalk and return success status."""
    signed_url = sign_dingtalk_url(webhook, secret)
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": text,
        },
    }
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(
            signed_url,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        logging.error("DingTalk push failed due to network/API error: %s", exc)
        return False
    except ValueError as exc:
        logging.error("DingTalk push returned non-JSON response: %s", exc)
        return False

    if data.get("errcode") != 0:
        logging.error("DingTalk push failed: %s", data)
        return False

    logging.info("DingTalk push succeeded.")
    return True


def main() -> None:
    """Build and optionally send today's DingTalk Markdown message."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    today_payload = load_json(TODAY_SELECTED_PATH)
    items = [item for item in today_payload.get("items", []) if isinstance(item, dict)]

    if not items:
        logging.warning("today_selected.json is empty; no formal brief will be sent.")
        return

    env = load_env()
    markdown = build_markdown_message(today_payload, env["SITE_URL"])

    if not env["DINGTALK_WEBHOOK"]:
        logging.info("DINGTALK_WEBHOOK is not configured; running in dry-run mode.")
        print("\n--- DRY RUN MARKDOWN MESSAGE ---\n")
        print(markdown)
        print("\n--- END DRY RUN ---\n")
        return

    send_dingtalk_markdown(
        env["DINGTALK_WEBHOOK"],
        env["DINGTALK_SECRET"],
        MESSAGE_TITLE,
        markdown,
    )


if __name__ == "__main__":
    main()

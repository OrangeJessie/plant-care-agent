"""ntfy / 通用 webhook 推送。"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def send_ntfy(
    server: str,
    topic: str,
    title: str,
    body: str,
    priority: str = "default",
) -> tuple[bool, str]:
    server = server.rstrip("/")
    url = f"{server}/{urllib.parse.quote(topic, safe='')}"
    safe_title = title.encode("ascii", "replace").decode("ascii")[:200] or "PlantCare"
    req = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "User-Agent": "plant-care-agent/1.0",
            "Title": safe_title,
            "Priority": priority,
            "Content-Type": "text/plain; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True, f"ntfy ok {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"ntfy HTTP {e.code}: {e.read()[:500]!r}"
    except Exception as e:
        return False, f"ntfy error: {e}"


def send_webhook(
    url: str,
    headers: dict[str, str] | None,
    payload: dict[str, Any],
) -> tuple[bool, str]:
    hdrs = {"User-Agent": "plant-care-agent/1.0", "Content-Type": "application/json; charset=utf-8"}
    if headers:
        hdrs.update(headers)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True, f"webhook ok {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"webhook HTTP {e.code}: {e.read()[:500]!r}"
    except Exception as e:
        return False, f"webhook error: {e}"


# ntfy Title 用 ASCII 更安全；中文标题放正文首行
def push_digest(
    push_cfg: dict[str, Any],
    title: str,
    body: str,
    plants_payload: list[dict[str, str]],
) -> tuple[bool, str]:
    mode = (push_cfg.get("mode") or "none").lower()
    if mode == "none":
        return False, "push.mode=none"

    if mode == "ntfy":
        ntfy = push_cfg.get("ntfy") or {}
        topic = (ntfy.get("topic") or "").strip()
        if not topic:
            return False, "ntfy.topic 为空"
        server = ntfy.get("server") or "https://ntfy.sh"
        priority = ntfy.get("priority") or "default"
        full_body = f"{title}\n\n{body}"
        return send_ntfy(server, topic, title[:80], full_body, priority=priority)

    if mode == "webhook":
        wh = push_cfg.get("webhook") or {}
        url = (wh.get("url") or "").strip()
        if not url:
            return False, "webhook.url 为空"
        hdrs = wh.get("headers") or {}
        if isinstance(hdrs, dict):
            h = {str(k): str(v) for k, v in hdrs.items()}
        else:
            h = {}
        payload = {
            "title": title,
            "body": body,
            "plants": plants_payload,
            "source": "plant-care-agent",
        }
        return send_webhook(url, h, payload)

    return False, f"未知 push.mode: {mode}"

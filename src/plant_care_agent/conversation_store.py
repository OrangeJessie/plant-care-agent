"""服务端一般对话记忆：按用户 + 会话持久化为 Markdown（兼容旧版 .json）。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from nat.data_models.api_server import Message
from nat.data_models.api_server import UserMessageContentRoleType

from plant_care_agent.chat_round_log import message_content_to_text

logger = logging.getLogger(__name__)

_SAFE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def safe_segment(s: str, *, max_len: int = 80, default: str = "anon") -> str:
    t = (s or "").strip() or default
    t = _SAFE_RE.sub("_", t)[:max_len].strip("_") or default
    return t


def transcript_path(store_dir: Path, user_id: str, session_id: str) -> Path:
    u = safe_segment(user_id, default="anonymous")
    s = safe_segment(session_id, default="default")
    return store_dir / f"{u}__{s}.md"


def only_user_assistant(messages: list[Message]) -> list[Message]:
    keep = (UserMessageContentRoleType.USER, UserMessageContentRoleType.ASSISTANT)
    return [m for m in messages if m.role in keep]


def _load_json_legacy(path: Path) -> list[Message]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[Message] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        role_s = str(item.get("role", "")).strip()
        try:
            role = UserMessageContentRoleType(role_s)
        except ValueError:
            continue
        if role not in (UserMessageContentRoleType.USER, UserMessageContentRoleType.ASSISTANT):
            continue
        content = item.get("content", "")
        if not isinstance(content, str):
            content = message_content_to_text(content)
        out.append(Message(role=role, content=content))
    return out


def _fence_block(lang: str, body: str) -> str:
    n = 3
    fence = "`" * n
    while fence in body:
        n += 1
        fence = "`" * n
    return f"{fence}{lang}\n{body}\n{fence}"


def _opening_fence(line: str) -> str | None:
    s = line.strip()
    if not s.startswith("`"):
        return None
    i = 0
    while i < len(s) and s[i] == "`":
        i += 1
    if i < 3:
        return None
    return "`" * i


def _parse_md_transcript(text: str) -> list[Message]:
    """解析由 `_save_md_transcript` 写入的 Markdown。"""
    out: list[Message] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("### "):
            role_s = line[4:].strip().lower()
            if role_s not in ("user", "assistant"):
                i += 1
                continue
            role = UserMessageContentRoleType(role_s)
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i >= len(lines):
                break
            op = _opening_fence(lines[i])
            if op:
                i += 1
                body_lines: list[str] = []
                while i < len(lines) and lines[i].strip() != op:
                    body_lines.append(lines[i])
                    i += 1
                if i < len(lines) and lines[i].strip() == op:
                    i += 1
                out.append(Message(role=role, content="\n".join(body_lines)))
            else:
                body_lines = []
                while i < len(lines) and not lines[i].startswith("### "):
                    body_lines.append(lines[i])
                    i += 1
                out.append(Message(role=role, content="\n".join(body_lines).rstrip()))
        else:
            i += 1
    return out


def _save_md_transcript(path: Path, user_id: str, session_id: str, messages: list[Message]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    u = safe_segment(user_id, default="anonymous")
    s = safe_segment(session_id, default="default")
    lines: list[str] = [
        "---",
        "plant_care: conversation-v1",
        f"user_id: {u}",
        f"session_id: {s}",
        "---",
        "",
        f"# 对话记忆 · `{u}` / `{s}`",
        "",
        "_服务端合并用：仅 **user** / **assistant**，不含注入的 system。正文在代码块内，避免破坏 Markdown。_",
        "",
    ]
    for m in only_user_assistant(messages):
        role = m.role.value
        body = message_content_to_text(m.content)
        lines.append(f"### {role}")
        lines.append("")
        lines.append(_fence_block("text", body))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def load_transcript(path: Path) -> list[Message]:
    if path.is_file():
        return _parse_md_transcript(path.read_text(encoding="utf-8"))
    legacy = path.with_suffix(".json")
    if legacy.is_file():
        msgs = _load_json_legacy(legacy)
        if msgs:
            try:
                stem = path.stem
                if "__" in stem:
                    uid, sid = stem.split("__", 1)
                else:
                    uid, sid = stem or "anonymous", "default"
                _save_md_transcript(path, uid, sid, msgs)
            except Exception:
                pass
            legacy.unlink(missing_ok=True)
        return msgs
    return []


def save_transcript(path: Path, messages: list[Message], *, user_id: str, session_id: str) -> None:
    _save_md_transcript(path, user_id, session_id, messages)
    legacy = path.with_suffix(".json")
    legacy.unlink(missing_ok=True)


def clear_transcript(path: Path) -> None:
    if path.is_file():
        path.unlink()
    legacy = path.with_suffix(".json")
    legacy.unlink(missing_ok=True)


def header_get(headers: dict[str, str] | None, key: str) -> str:
    if not headers:
        return ""
    lk = key.lower()
    for k, v in headers.items():
        if k.lower() == lk:
            return str(v).strip()
    return ""


def header_truthy(headers: dict[str, str] | None, name: str) -> bool:
    if not headers:
        return False
    lk = name.lower()
    for k, v in headers.items():
        if k.lower() == lk:
            return str(v).strip().lower() in ("1", "true", "yes", "on")
    return False


def resolve_incremental(
    raw: list[Message],
    headers: dict[str, str] | None,
    *,
    auto_incremental: bool,
) -> bool:
    if not raw:
        return False
    v = header_get(headers, "X-Chat-Incremental")
    if v:
        vl = v.lower()
        if vl in ("1", "true", "yes", "on"):
            return True
        if vl in ("0", "false", "no", "off"):
            return False
    return bool(auto_incremental and _heuristic_incremental(raw))


def _heuristic_incremental(raw: list[Message]) -> bool:
    return len(raw) == 1 and bool(raw) and raw[0].role == UserMessageContentRoleType.USER


def merge_conversation_transcript(
    raw_client: list[Message],
    loaded: list[Message],
    *,
    reset: bool,
    incremental: bool,
) -> list[Message]:
    """得到注入种植记忆前的 user/assistant 消息链。"""
    raw_ua = only_user_assistant(raw_client)
    if reset:
        return list(raw_ua)
    if incremental:
        return loaded + raw_ua
    return list(raw_ua)


def cleanup_old_transcripts(
    store_dir: Path,
    max_age_days: int = 30,
    max_count: int = 100,
) -> int:
    """删除过期和超量的对话文件，返回删除数量。"""
    import time

    if not store_dir.is_dir():
        return 0

    files = list(store_dir.glob("*.md"))
    if not files:
        return 0

    now = time.time()
    max_age_secs = max_age_days * 86400
    deleted = 0

    # 按 mtime 排序（最旧在前）
    files.sort(key=lambda f: f.stat().st_mtime)

    # 1. 删除超龄文件
    remaining = []
    for f in files:
        try:
            age = now - f.stat().st_mtime
            if age > max_age_secs:
                f.unlink()
                deleted += 1
                logger.debug("对话清理: 删除过期文件 %s (%.0f 天)", f.name, age / 86400)
            else:
                remaining.append(f)
        except OSError:
            remaining.append(f)

    # 2. 如果剩余数量 > max_count，删除最老的
    if len(remaining) > max_count:
        to_remove = remaining[: len(remaining) - max_count]
        for f in to_remove:
            try:
                f.unlink()
                deleted += 1
                logger.debug("对话清理: 删除超量文件 %s", f.name)
            except OSError:
                pass

    if deleted:
        logger.info("对话清理: 共删除 %d 个过期/超量对话文件 (store=%s)", deleted, store_dir)
    return deleted

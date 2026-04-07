"""每轮 LLM 输入/输出写入 Markdown（与 `md_log_file` 共用同一文件时由全局锁串行化）。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from nat.data_models.api_server import ChatResponse
from nat.data_models.api_server import Message

from plant_care_agent.md_log_file import append_raw


def content_to_log_repr(content: Any) -> str:
    if content is None:
        return "(null)"
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list)):
        try:
            return json.dumps(content, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(content)
    return str(content)


def message_content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text", "")))
            elif isinstance(p, str):
                parts.append(p)
            else:
                parts.append(str(p))
        return "".join(parts)
    return str(content)


def header_get(headers: dict[str, str] | None, key: str) -> str:
    if not headers:
        return ""
    lk = key.lower()
    for k, v in headers.items():
        if k.lower() == lk:
            return str(v).strip()
    return ""


def assistant_text_from_chat_response(response: ChatResponse) -> str:
    choices = response.choices or []
    if not choices:
        return ""
    msg = choices[0].message
    if msg is None:
        return ""
    return message_content_to_text(getattr(msg, "content", None))


def _md_fence(lang: str, body: str) -> str:
    n = 3
    fence = "`" * n
    while fence in body:
        n += 1
        fence = "`" * n
    return f"{fence}{lang}\n{body}\n{fence}\n"


def build_llm_round_markdown(
    *,
    ts: str,
    messages_to_llm: list[Message],
    focus_plant: str,
    headers: dict[str, str] | None,
    assistant_text: str,
    error: str | None,
    llm_response: ChatResponse | None,
) -> str:
    uid = header_get(headers, "X-User-ID")
    sid = header_get(headers, "X-Session-ID")
    lines: list[str] = [
        f"## 轮次 · {ts}",
        "",
        f"- **X-Focus-Plant:** {focus_plant or '（未设置）'}",
        f"- **X-User-ID:** {uid or '（未设置）'}",
        f"- **X-Session-ID:** {sid or '（未设置）'}",
        f"- **messages 条数:** {len(messages_to_llm)}",
        "",
        "### TO_LLM（提交给大模型的完整 messages）",
        "",
    ]
    if not messages_to_llm:
        lines.append("_（无消息）_")
        lines.append("")
    else:
        for i, m in enumerate(messages_to_llm, start=1):
            role = getattr(m.role, "value", None) or str(m.role)
            body = content_to_log_repr(m.content)
            lines.append(f"#### messages[{i}] · `{role}`")
            lines.append("")
            lines.append(_md_fence("text", body))
            lines.append("")

    lines.extend(
        [
            "### FROM_LLM（大模型返回）",
            "",
        ],
    )
    if error:
        lines.extend(
            [
                "_本论未拿到 ChatCompletion（内层 Agent 抛错）。_",
                "",
                _md_fence("text", f"[ERROR]\n{error}"),
                "",
            ],
        )
    else:
        lines.append("#### assistant 正文（choices[0].message.content 全文）")
        lines.append("")
        lines.append(_md_fence("text", assistant_text if assistant_text else "（空或 null）"))
        lines.append("")
        if llm_response is not None:
            lines.append("#### 元数据")
            lines.append("")
            meta_lines: list[str] = [
                f"id: {llm_response.id}",
                f"object: {getattr(llm_response, 'object', '')}",
                f"model: {getattr(llm_response, 'model', '')}",
                f"created: {getattr(llm_response, 'created', '')}",
            ]
            if llm_response.usage is not None:
                try:
                    meta_lines.append(
                        "usage: " + json.dumps(llm_response.usage.model_dump(), ensure_ascii=False),
                    )
                except Exception:
                    meta_lines.append(f"usage: {llm_response.usage!r}")
            for idx, ch in enumerate(llm_response.choices or []):
                meta_lines.append(f"choices[{idx}].finish_reason: {ch.finish_reason}")
                meta_lines.append(f"choices[{idx}].index: {ch.index}")
                msg = ch.message
                if msg is not None:
                    meta_lines.append(f"choices[{idx}].message.role: {getattr(msg, 'role', '')}")
                    raw_c = getattr(msg, "content", None)
                    if raw_c is not None and content_to_log_repr(raw_c) != (assistant_text or ""):
                        meta_lines.append(f"choices[{idx}].message.content（原始结构）:")
                        meta_lines.append(content_to_log_repr(raw_c))
            lines.append(_md_fence("text", "\n".join(meta_lines)))
            lines.append("")
        else:
            lines.append("_非 ChatCompletion 路径（仅字符串回复），无 usage 等元数据。_")
            lines.append("")

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def append_round_block(
    path: Path,
    *,
    messages_to_llm: list[Message],
    focus_plant: str,
    headers: dict[str, str] | None,
    assistant_text: str,
    error: str | None,
    llm_response: ChatResponse | None = None,
) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    body = build_llm_round_markdown(
        ts=ts,
        messages_to_llm=messages_to_llm,
        focus_plant=focus_plant,
        headers=headers,
        assistant_text=assistant_text,
        error=error,
        llm_response=llm_response,
    )
    append_raw(path, "\n" + body)

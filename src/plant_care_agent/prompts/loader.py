"""从 Markdown 片段组装 ReAct Agent 的 system_prompt。

`tools_block.md` 必须包含 NAT react_agent 要求的占位符 `{tools}` 与 `{tool_names}`。
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

_PROMPT_FILES = ("core.md", "workflow.md", "style.md", "tools_block.md")


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parent


def get_system_prompt() -> str:
    """读取 prompts 目录下片段并拼接为完整 system_prompt。"""
    base = _prompts_dir()
    parts: list[str] = []
    for name in _PROMPT_FILES:
        p = base / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8").strip()
        if text:
            parts.append(text)
    body = "\n\n".join(parts)
    if "{tools}" not in body or "{tool_names}" not in body:
        raise ValueError(
            "assembled system_prompt must contain {tools} and {tool_names} (see prompts/tools_block.md)"
        )
    return body


def get_system_prompt_packaged() -> str:
    """从已安装包内读取（importlib.resources），用于 wheel 安装场景。"""
    try:
        root = importlib.resources.files("plant_care_agent.prompts")
    except (ModuleNotFoundError, AttributeError, ValueError):
        return get_system_prompt()
    parts: list[str] = []
    for name in _PROMPT_FILES:
        try:
            node = root.joinpath(name)
            text = node.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError, TypeError, AttributeError, ValueError):
            continue
        text = text.strip()
        if text:
            parts.append(text)
    body = "\n\n".join(parts)
    if "{tools}" not in body or "{tool_names}" not in body:
        return get_system_prompt()
    return body

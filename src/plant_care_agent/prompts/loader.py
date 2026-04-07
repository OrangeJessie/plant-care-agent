"""从 Markdown 片段组装 ReAct Agent 的 system_prompt。

`tools_block.md` 必须包含 NAT react_agent 要求的占位符 `{tools}` 与 `{tool_names}`。

支持 mode 参数：
- "personal" (默认): core.md + workflow.md + style.md + tools_block.md
- "farm": core_farm.md + workflow_farm.md + style.md + tools_block.md
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

_PROMPT_FILES_PERSONAL = ("core.md", "workflow.md", "style.md", "tools_block.md")
_PROMPT_FILES_FARM = ("core_farm.md", "workflow_farm.md", "style.md", "tools_block.md")

_MODE_FILES = {
    "personal": _PROMPT_FILES_PERSONAL,
    "farm": _PROMPT_FILES_FARM,
}


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parent


def get_system_prompt(mode: str = "personal") -> str:
    """读取 prompts 目录下片段并拼接为完整 system_prompt。

    Args:
        mode: "personal" 个人模式 或 "farm" 农业模式。
    """
    prompt_files = _MODE_FILES.get(mode, _PROMPT_FILES_PERSONAL)
    base = _prompts_dir()
    parts: list[str] = []
    for name in prompt_files:
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


def get_system_prompt_packaged(mode: str = "personal") -> str:
    """从已安装包内读取（importlib.resources），用于 wheel 安装场景。"""
    prompt_files = _MODE_FILES.get(mode, _PROMPT_FILES_PERSONAL)
    try:
        root = importlib.resources.files("plant_care_agent.prompts")
    except (ModuleNotFoundError, AttributeError, ValueError):
        return get_system_prompt(mode)
    parts: list[str] = []
    for name in prompt_files:
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
        return get_system_prompt(mode)
    return body

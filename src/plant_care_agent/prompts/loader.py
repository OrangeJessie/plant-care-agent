"""从 Markdown 片段组装 prompt 内容。

提供两类 API：
- `get_system_prompt(mode)` — 包含 {tools}/{tool_names} 占位符的完整 system_prompt，
    由 NAT react_agent 在运行时填充。
- `get_domain_prompt(mode)` — 不含 tools_block.md 的域知识（角色 + 工作流 + 风格），
    由 wrapper 注入为 system message。

两者分工：
  config.yml `system_prompt`  ← tools_block.md（ReAct 格式约束 + {tools}）
  wrapper 注入 system message ← core.md + workflow.md + style.md（域知识）
"""

from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DOMAIN_FILES_PERSONAL = ("core.md", "workflow.md", "style.md")
_DOMAIN_FILES_FARM = ("core_farm.md", "workflow_farm.md", "style.md")

_ALL_FILES_PERSONAL = (*_DOMAIN_FILES_PERSONAL, "tools_block.md")
_ALL_FILES_FARM = (*_DOMAIN_FILES_FARM, "tools_block.md")

_MODE_ALL = {
    "personal": _ALL_FILES_PERSONAL,
    "farm": _ALL_FILES_FARM,
}
_MODE_DOMAIN = {
    "personal": _DOMAIN_FILES_PERSONAL,
    "farm": _DOMAIN_FILES_FARM,
}


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parent


def _load_parts(file_list: tuple[str, ...]) -> list[str]:
    base = _prompts_dir()
    parts: list[str] = []
    for name in file_list:
        p = base / name
        if not p.exists():
            logger.debug("Prompt file not found, skipping: %s", p)
            continue
        text = p.read_text(encoding="utf-8").strip()
        if text:
            parts.append(text)
    return parts


def get_system_prompt(mode: str = "personal") -> str:
    """完整 system_prompt（含 {tools}/{tool_names}），写入 config.yml 的 inner_react.system_prompt。"""
    files = _MODE_ALL.get(mode, _ALL_FILES_PERSONAL)
    parts = _load_parts(files)
    body = "\n\n".join(parts)
    if "{tools}" not in body or "{tool_names}" not in body:
        raise ValueError(
            "assembled system_prompt must contain {tools} and {tool_names} (see prompts/tools_block.md)"
        )
    return body


def get_domain_prompt(mode: str = "personal") -> str:
    """域知识 prompt（角色 + 工具使用指南 + 风格），由 wrapper 注入为 system message。

    不含 tools_block.md，因为 tools 列表由 NAT react_agent 自动注入。
    """
    files = _MODE_DOMAIN.get(mode, _DOMAIN_FILES_PERSONAL)
    parts = _load_parts(files)
    return "\n\n".join(parts)


def get_system_prompt_packaged(mode: str = "personal") -> str:
    """从已安装包内读取（importlib.resources），用于 wheel 安装场景。"""
    files = _MODE_ALL.get(mode, _ALL_FILES_PERSONAL)
    try:
        root = importlib.resources.files("plant_care_agent.prompts")
    except (ModuleNotFoundError, AttributeError, ValueError):
        return get_system_prompt(mode)
    parts: list[str] = []
    for name in files:
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

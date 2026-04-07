"""从 Markdown 片段组装 prompt 内容。

分工：
  get_system_prompt()  → tools_block.md（ReAct 格式 + {tools}/{tool_names}）
                         经 NAT str.format() + LangChain ChatPromptTemplate 双重处理
  get_domain_prompt()  → core.md + workflow.md + style.md（域知识）
                         由 wrapper 注入为 system message，不经过模板引擎
"""

from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DOMAIN_FILES_PERSONAL = ("core.md", "workflow.md", "style.md")
_DOMAIN_FILES_FARM = ("core_farm.md", "workflow_farm.md", "style.md")

_SYSTEM_PROMPT_FILES = ("tools_block.md",)

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
    """system_prompt: 只含 ReAct 格式约束 + {tools}/{tool_names} 占位符。

    域知识（角色/工具指南/风格）由 wrapper 通过 get_domain_prompt() 单独注入，
    不经过 NAT 的 str.format()，避免 JSON 示例中的花括号被误认为模板变量。
    """
    parts = _load_parts(_SYSTEM_PROMPT_FILES)
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
    try:
        root = importlib.resources.files("plant_care_agent.prompts")
    except (ModuleNotFoundError, AttributeError, ValueError):
        return get_system_prompt(mode)
    parts: list[str] = []
    for name in _SYSTEM_PROMPT_FILES:
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

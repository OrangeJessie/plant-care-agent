"""skill_tools — Skills 目录发现与加载（insightor / Claude Code 风格 SKILL.md）。"""

import logging

from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from plant_care_agent.skills.registry import discover_skills
from plant_care_agent.skills.registry import load_skill_body

logger = logging.getLogger(__name__)


class SkillToolsConfig(FunctionBaseConfig, name="skill_tools"):
    load_max_chars: int = Field(
        default=12000,
        ge=500,
        le=100000,
        description="load_skill 返回正文最大字符数",
    )


@register_function(config_type=SkillToolsConfig)
async def skill_tools_function(config: SkillToolsConfig, _builder: Builder):

    async def list_skills(query: str) -> str:
        """List available Skills (bundled + ./skills + PLANT_CARE_SKILL_DIRS + ~/.plant-care-agent/skills).
        Input: optional filter substring (case-insensitive); empty lists all.
        Returns: skill id, display name, description, when_to_use."""
        q = (query or "").strip().lower()
        skills = discover_skills()
        if not skills:
            return "当前未发现任何 Skill。可在项目根创建 skills/<id>/SKILL.md，或设置环境变量 PLANT_CARE_SKILL_DIRS。"

        lines = ["## Skills 目录\n"]
        for sid in sorted(skills.keys()):
            s = skills[sid]
            blob = f"{sid} {s.name} {s.description} {s.when_to_use}".lower()
            if q and q not in blob:
                continue
            lines.append(f"### `{sid}`")
            lines.append(f"- **名称**: {s.name}")
            if s.description:
                lines.append(f"- **说明**: {s.description}")
            if s.when_to_use:
                lines.append(f"- **适用**: {s.when_to_use}")
            lines.append("")
        if len(lines) <= 1:
            return f"没有匹配「{query}」的 Skill。留空 query 可列出全部。"
        lines.append("使用 `load_skill` 并传入 **skill_id** 获取完整执行指令。")
        return "\n".join(lines).strip()

    async def load_skill(skill_id: str) -> str:
        """Load the full body of a Skill (markdown after YAML frontmatter).
        Input: skill directory name, e.g. pest_diagnosis, balcony_vegetables.
        Follow the returned instructions step-by-step for this turn / task."""
        rec, body = load_skill_body(skill_id)
        if rec is None or not body:
            avail = ", ".join(sorted(discover_skills().keys())) or "（无）"
            return f"未找到 Skill「{skill_id}」。可用 id: {avail}"

        header = f"# 已加载 Skill: {rec.skill_id}\n**{rec.name}**\n\n---\n\n"
        text = header + body
        if len(text) > config.load_max_chars:
            text = text[: config.load_max_chars] + "\n\n…(正文已截断，可缩短 SKILL.md 或调高配置 load_max_chars)"
        return text

    yield FunctionInfo.from_fn(
        list_skills,
        description="列出可用 Skills；可选 query 子串过滤。",
    )
    yield FunctionInfo.from_fn(
        load_skill,
        description="按 skill_id 加载 SKILL.md 正文，按其中流程执行任务。",
    )

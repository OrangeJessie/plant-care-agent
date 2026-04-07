"""Skills 系统：参考 Claude Code / insightor 的 `技能名/SKILL.md` + YAML frontmatter。

扫描顺序（后者同名则覆盖）：
1. 包内 `plant_care_agent.skills.bundled/*/SKILL.md`
2. 环境变量 `PLANT_CARE_SKILL_DIRS`（`:` 分隔的绝对或相对路径）
3. 当前工作目录下 `./skills/*/SKILL.md`
4. `~/.plant-care-agent/skills/*/SKILL.md`
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class SkillRecord:
    skill_id: str
    name: str
    description: str
    when_to_use: str
    path: Path


def _strip_fm(text: str) -> tuple[dict[str, str], str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip().lower()] = v.strip()
    body = FRONTMATTER_RE.sub("", text, count=1).strip()
    return fm, body


def _bundled_skills_root() -> Path | None:
    try:
        p = Path(__file__).resolve().parent / "bundled"
        if p.is_dir():
            return p
    except OSError:
        pass
    return None


def _extra_dirs_from_env() -> list[Path]:
    raw = os.environ.get("PLANT_CARE_SKILL_DIRS", "").strip()
    if not raw:
        return []
    out: list[Path] = []
    for part in raw.split(os.pathsep):
        p = Path(part.strip()).expanduser()
        if str(p):
            out.append(p)
    return out


def _skill_roots() -> list[Path]:
    roots: list[Path] = []
    b = _bundled_skills_root()
    if b:
        roots.append(b)
    roots.extend(_extra_dirs_from_env())
    roots.append(Path.cwd() / "skills")
    roots.append(Path.home() / ".plant-care-agent" / "skills")
    seen: set[str] = set()
    uniq: list[Path] = []
    for r in roots:
        try:
            key = str(r.resolve())
        except OSError:
            key = str(r)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


def discover_skills() -> dict[str, SkillRecord]:
    """按扫描顺序合并 skill_id -> SkillRecord（后写覆盖）。"""
    merged: dict[str, SkillRecord] = {}
    for root in _skill_roots():
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.is_file():
                continue
            skill_id = child.name
            try:
                text = skill_file.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning("read skill %s: %s", skill_file, e)
                continue
            fm, _body = _strip_fm(text)
            name = fm.get("name") or skill_id.replace("_", " ")
            desc = fm.get("description") or ""
            when = fm.get("when_to_use") or fm.get("when to use") or ""
            merged[skill_id] = SkillRecord(
                skill_id=skill_id,
                name=name,
                description=desc,
                when_to_use=when,
                path=skill_file,
            )
    return merged


def load_skill_body(skill_id: str) -> tuple[SkillRecord | None, str]:
    skills = discover_skills()
    rec = skills.get(skill_id.strip())
    if rec is None:
        for k, v in skills.items():
            if k.lower() == skill_id.strip().lower() or v.name.lower() == skill_id.strip().lower():
                rec = v
                break
    if rec is None:
        return None, ""
    text = rec.path.read_text(encoding="utf-8")
    _fm, body = _strip_fm(text)
    return rec, body


def build_skills_index_text(max_chars: int = 4000) -> str:
    skills = discover_skills()
    if not skills:
        return "## 可用 Skills\n（未安装扩展 Skill；可将自定义 `skills/<id>/SKILL.md` 放在项目根目录。）"
    lines = [
        "## 可用 Skills（模型应先 `load_skill` 再按正文执行）",
        "",
    ]
    for sid in sorted(skills.keys()):
        s = skills[sid]
        lines.append(f"- **{sid}** — {s.name}")
        if s.description:
            lines.append(f"  - 说明: {s.description}")
        if s.when_to_use:
            lines.append(f"  - 适用: {s.when_to_use}")
        lines.append("")
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n…(已截断)"
    return text

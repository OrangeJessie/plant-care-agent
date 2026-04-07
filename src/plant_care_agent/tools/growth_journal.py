"""growth_journal — 植物生长日志（Markdown 文件持久化）。

存储结构（每棵植物一个文件夹）:
  data/garden/
    GARDEN.md              索引（自动维护）
    栀子花/
      journal.md           生长日志
    薄荷/
      journal.md

journal.md 格式:
  ---
  name: 我的番茄
  species: tomato
  planted: 2026-04-01
  location: 阳台
  stage: 苗期
  events: 5
  ---
  # 我的番茄

  ## 日志

  ### 2026-04-01
  - **[播种]** 在阳台花盆中播下了5粒种子
"""

import logging
import re
from datetime import date, datetime
from pathlib import Path

from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function import FunctionGroup
from nat.cli.register_workflow import register_function_group
from nat.data_models.function import FunctionGroupBaseConfig

from plant_care_agent.garden_paths import (
    ensure_plant_dir,
    index_path,
    journal_path,
    list_plant_dirs,
)

logger = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
EVENT_LINE_RE = re.compile(r"^- \*\*\[(.+?)]\*\*\s+(.+)$", re.MULTILINE)

STAGE_TRANSITIONS: dict[str, str] = {
    "播种": "播种期",
    "发芽": "苗期",
    "移栽": "生长期",
    "开花": "花期",
    "结果": "结果期",
    "采收": "采收期",
}

MILESTONES = {
    7: "🌱 种下一周啦！",
    14: "🌿 两周了，继续加油！",
    30: "🎉 满一个月！",
    60: "💪 两个月坚持养护！",
    90: "🏆 三个月里程碑！",
}


class GrowthJournalConfig(FunctionGroupBaseConfig, name="growth_journal"):
    journal_dir: str = Field(
        default="./data/garden",
        description="Directory to store plant growth markdown files.",
    )
    include: list[str] = Field(
        default_factory=lambda: ["log_event", "query_history", "list_plants"],
    )


def _plant_path(garden_dir: Path, plant_id: str) -> Path:
    return journal_path(garden_dir, plant_id)


def _parse_fm(text: str) -> dict[str, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _rebuild_fm(fm: dict[str, str]) -> str:
    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _load_plant(path: Path) -> tuple[dict[str, str], str]:
    if not path.exists():
        return {}, ""
    text = path.read_text(encoding="utf-8")
    fm = _parse_fm(text)
    body = FRONTMATTER_RE.sub("", text, count=1)
    return fm, body


def _save_plant(path: Path, fm: dict[str, str], body: str) -> None:
    path.write_text(f"{_rebuild_fm(fm)}\n{body}", encoding="utf-8")


def _count_events(body: str) -> int:
    return len(EVENT_LINE_RE.findall(body))


def _days_since(planted_str: str) -> int:
    try:
        return (date.today() - datetime.strptime(planted_str, "%Y-%m-%d").date()).days
    except (ValueError, TypeError):
        return 0


def _create_new_plant(path: Path, plant_id: str, garden_dir: Path) -> tuple[dict[str, str], str]:
    today = date.today().isoformat()
    fm = {
        "name": plant_id,
        "planted": today,
        "stage": "播种期",
        "events": "0",
    }
    body = f"\n# {plant_id}\n\n## 日志\n"
    ensure_plant_dir(garden_dir, plant_id)
    _save_plant(path, fm, body)
    return fm, body


def _append_event(fm: dict[str, str], body: str, event_type: str, description: str) -> tuple[dict[str, str], str]:
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")

    date_heading = f"### {today}"
    event_line = f"- **[{event_type}]** {description}  _{now}_"

    if date_heading in body:
        body = body.replace(date_heading, f"{date_heading}\n{event_line}", 1)
    else:
        body = body.rstrip() + f"\n\n{date_heading}\n{event_line}\n"

    fm["events"] = str(_count_events(body))
    fm["last_updated"] = today
    if event_type in STAGE_TRANSITIONS:
        fm["stage"] = STAGE_TRANSITIONS[event_type]

    return fm, body


def _rebuild_index(garden_dir: Path) -> None:
    plant_dirs = list_plant_dirs(garden_dir)
    lines = [
        "# 🌱 我的花园\n",
        "| 植物 | 品种 | 种植日期 | 阶段 | 记录数 |",
        "|------|------|----------|------|--------|",
    ]
    for d in plant_dirs:
        j = d / "journal.md"
        fm, body = _load_plant(j)
        name = fm.get("name") or d.name
        species = fm.get("species", "-")
        planted = fm.get("planted", "-")
        stage = fm.get("stage", "-")
        events = fm.get("events") or str(_count_events(body))
        lines.append(f"| [{name}]({d.name}/journal.md) | {species} | {planted} | {stage} | {events} |")

    lines.append(f"\n_更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n")
    index_path(garden_dir).write_text("\n".join(lines), encoding="utf-8")


@register_function_group(config_type=GrowthJournalConfig)
async def growth_journal_group(config: GrowthJournalConfig, _builder: Builder):
    garden_dir = Path(config.journal_dir)
    garden_dir.mkdir(parents=True, exist_ok=True)

    async def _log_event(entry: str) -> str:
        """Record a plant growth event to the journal.
        Input format: 'plant_id | event_type | description'
        Example: '我的番茄 | 播种 | 在阳台花盆中播下了5粒番茄种子'
        Optionally add species and location: '我的番茄 | 播种 | 播下5粒种子 | species=tomato | location=阳台'
        Event types: 播种, 发芽, 移栽, 浇水, 施肥, 修剪, 开花, 结果, 采收, 病害, 虫害, 其他"""
        parts = [p.strip() for p in entry.split("|")]
        if len(parts) < 3:
            return (
                "格式错误。请使用: '植物名称 | 事件类型 | 描述'\n"
                "例如: '我的番茄 | 播种 | 在阳台花盆中播下了5粒番茄种子'"
            )

        plant_id, event_type, description = parts[0], parts[1], parts[2]
        extra: dict[str, str] = {}
        for p in parts[3:]:
            if "=" in p:
                k, v = p.split("=", 1)
                extra[k.strip()] = v.strip()

        path = _plant_path(garden_dir, plant_id)
        if path.exists():
            fm, body = _load_plant(path)
        else:
            fm, body = _create_new_plant(path, plant_id, garden_dir)

        for k, v in extra.items():
            if k in ("species", "location"):
                fm[k] = v

        fm, body = _append_event(fm, body, event_type, description)
        _save_plant(path, fm, body)
        _rebuild_index(garden_dir)

        days = _days_since(fm.get("planted", ""))
        milestone_msg = ""
        if days in MILESTONES:
            milestone_msg = f"\n🎯 里程碑: {MILESTONES[days]}"

        return (
            f"✅ 已记录「{plant_id}」的事件\n"
            f"  日期: {date.today().isoformat()}\n"
            f"  类型: {event_type}\n"
            f"  描述: {description}\n"
            f"  阶段: {fm.get('stage', '-')} | 累计: {fm['events']}条 | 种植天数: {days}天"
            f"{milestone_msg}"
        )

    async def _query_history(plant_id: str) -> str:
        """Query the growth history of a specific plant.
        Input: plant name/ID.
        Returns the full markdown journal for this plant."""
        path = _plant_path(garden_dir, plant_id.strip())
        if not path.exists():
            return f"「{plant_id}」暂无生长记录。使用 log_event 开始记录吧！"

        fm, body = _load_plant(path)
        name = fm.get("name") or plant_id
        days = _days_since(fm.get("planted", ""))
        events = fm.get("events") or str(_count_events(body))

        header = (
            f"📖 「{name}」生长日志\n"
            f"种植天数: {days} | 总记录: {events}条 | 阶段: {fm.get('stage', '-')}\n"
        )
        meta_parts: list[str] = []
        for k in ("species", "location", "planted"):
            if k in fm:
                meta_parts.append(f"{k}: {fm[k]}")
        if meta_parts:
            header += " | ".join(meta_parts) + "\n"

        return header + "\n" + body.strip()

    async def _list_plants(query: str) -> str:
        """List all plants that have growth journals.
        Input can be anything (ignored), returns all tracked plants with summaries."""
        plant_dirs = list_plant_dirs(garden_dir)
        if not plant_dirs:
            return "暂无任何植物的生长记录。开始记录您的第一棵植物吧！"

        idx = index_path(garden_dir)
        if idx.exists():
            return idx.read_text(encoding="utf-8")

        lines = ["🌱 我的花园\n"]
        for d in plant_dirs:
            fm, body = _load_plant(d / "journal.md")
            name = fm.get("name") or d.name
            events = fm.get("events") or str(_count_events(body))
            stage = fm.get("stage", "-")
            days = _days_since(fm.get("planted", ""))
            lines.append(f"  🪴 {name}: {events}条记录 | 种植{days}天 | 阶段: {stage}")
        return "\n".join(lines)

    group = FunctionGroup(config=config)
    group.add_function(name="log_event", fn=_log_event, description=_log_event.__doc__)
    group.add_function(name="query_history", fn=_query_history, description=_query_history.__doc__)
    group.add_function(name="list_plants", fn=_list_plants, description=_list_plants.__doc__)
    yield group

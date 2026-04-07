"""farm_journal — 农场日志系统（地块 + 作物批次维度）。

存储结构:
  data/farm/
    FARM_INDEX.md           索引（自动维护）
    zones/{zone_id}.md      每个地块一个 markdown 日志

与 growth_journal 复用 Markdown 格式，但维度从单株植物变为地块。
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

logger = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
EVENT_LINE_RE = re.compile(r"^- \*\*\[(.+?)]\*\*\s+(.+)$", re.MULTILINE)

EVENT_TYPES = [
    "播种", "灌溉", "施肥", "除虫", "收割", "巡检",
    "通风", "遮阳", "移栽", "告警", "维护", "观察", "其他",
]


class FarmJournalConfig(FunctionGroupBaseConfig, name="farm_journal"):
    farm_dir: str = Field(default="./data/farm", description="农场数据根目录。")
    include: list[str] = Field(
        default_factory=lambda: ["log_farm_event", "query_farm_history", "list_farm_zones"],
    )


def _zones_dir(farm_dir: Path) -> Path:
    d = farm_dir / "zones"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _zone_path(farm_dir: Path, zone_id: str) -> Path:
    return _zones_dir(farm_dir) / f"{zone_id.strip()}.md"


def _index_path(farm_dir: Path) -> Path:
    return farm_dir / "FARM_INDEX.md"


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


def _load_zone(path: Path) -> tuple[dict[str, str], str]:
    if not path.exists():
        return {}, ""
    text = path.read_text(encoding="utf-8")
    fm = _parse_fm(text)
    body = FRONTMATTER_RE.sub("", text, count=1)
    return fm, body


def _save_zone(path: Path, fm: dict[str, str], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{_rebuild_fm(fm)}\n{body}", encoding="utf-8")


def _count_events(body: str) -> int:
    return len(EVENT_LINE_RE.findall(body))


def _create_zone(path: Path, zone_id: str) -> tuple[dict[str, str], str]:
    today = date.today().isoformat()
    fm = {
        "zone_id": zone_id,
        "name": zone_id,
        "created": today,
        "crop": "未设置",
        "events": "0",
    }
    body = f"\n# {zone_id}\n\n## 操作日志\n"
    _save_zone(path, fm, body)
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
    return fm, body


def _rebuild_index(farm_dir: Path) -> None:
    zones = sorted(_zones_dir(farm_dir).glob("*.md"))
    lines = [
        "# 🌾 农场管理总览\n",
        "| 地块 | 作物 | 创建日期 | 记录数 | 最近更新 |",
        "|------|------|----------|--------|----------|",
    ]
    for f in zones:
        fm, body = _load_zone(f)
        name = fm.get("name") or f.stem
        crop = fm.get("crop", "-")
        created = fm.get("created", "-")
        events = fm.get("events") or str(_count_events(body))
        updated = fm.get("last_updated", "-")
        lines.append(f"| [{name}](zones/{f.name}) | {crop} | {created} | {events} | {updated} |")

    lines.append(f"\n_更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n")
    _index_path(farm_dir).write_text("\n".join(lines), encoding="utf-8")


@register_function_group(config_type=FarmJournalConfig)
async def farm_journal_group(config: FarmJournalConfig, _builder: Builder):
    farm_dir = Path(config.farm_dir)
    farm_dir.mkdir(parents=True, exist_ok=True)

    async def _log_farm_event(entry: str) -> str:
        """Record a farm operation or observation event.
        Input format: 'zone_id | event_type | description'
        Optional: 'zone_id | event_type | description | crop=水稻 | name=A区水稻田'
        Event types: 播种, 灌溉, 施肥, 除虫, 收割, 巡检, 通风, 遮阳, 移栽, 告警, 维护, 观察, 其他"""
        parts = [p.strip() for p in entry.split("|")]
        if len(parts) < 3:
            return (
                "格式: 'zone_id | event_type | description'\n"
                f"例如: 'zone_a | 灌溉 | 自动灌溉系统启动，浇水30分钟'"
            )

        zone_id, event_type, description = parts[0], parts[1], parts[2]
        extra: dict[str, str] = {}
        for p in parts[3:]:
            if "=" in p:
                k, v = p.split("=", 1)
                extra[k.strip()] = v.strip()

        path = _zone_path(farm_dir, zone_id)
        if path.exists():
            fm, body = _load_zone(path)
        else:
            fm, body = _create_zone(path, zone_id)

        for k, v in extra.items():
            if k in ("crop", "name", "area_mu", "soil_type"):
                fm[k] = v

        fm, body = _append_event(fm, body, event_type, description)
        _save_zone(path, fm, body)
        _rebuild_index(farm_dir)

        return (
            f"✅ 已记录地块「{fm.get('name', zone_id)}」的事件\n"
            f"  日期: {date.today().isoformat()}\n"
            f"  类型: {event_type}\n"
            f"  描述: {description}\n"
            f"  累计记录: {fm['events']}条"
        )

    async def _query_farm_history(query: str) -> str:
        """Query farm operation history for a zone.
        Input: 'zone_id' or 'zone_id | days | event_type(optional)'
        Example: 'zone_a' or 'zone_a | 7 | 灌溉'"""
        parts = [p.strip() for p in query.split("|")]
        zone_id = parts[0]
        days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        event_filter = parts[2] if len(parts) > 2 else ""

        path = _zone_path(farm_dir, zone_id)
        if not path.exists():
            return f"地块「{zone_id}」暂无记录。"

        fm, body = _load_zone(path)
        name = fm.get("name", zone_id)
        events_count = fm.get("events", "0")

        header = f"📋 地块「{name}」操作日志（共 {events_count} 条记录）\n"
        if fm.get("crop"):
            header += f"作物: {fm['crop']}\n"

        content = body.strip()
        if event_filter:
            lines = content.splitlines()
            filtered = [l for l in lines if event_filter in l or l.startswith("### ") or l.startswith("# ")]
            content = "\n".join(filtered)

        return header + "\n" + content

    async def _list_farm_zones(query: str) -> str:
        """List all farm zones with their status summary.
        Input can be anything (ignored)."""
        index = _index_path(farm_dir)
        if index.exists():
            return index.read_text(encoding="utf-8")

        zones = sorted(_zones_dir(farm_dir).glob("*.md"))
        if not zones:
            return "暂无地块记录。使用 log_farm_event 开始记录。"

        lines = ["🌾 农场地块列表\n"]
        for f in zones:
            fm, body = _load_zone(f)
            name = fm.get("name") or f.stem
            crop = fm.get("crop", "-")
            events = fm.get("events") or str(_count_events(body))
            lines.append(f"  📍 {name}: {crop} | {events}条记录")
        return "\n".join(lines)

    group = FunctionGroup(config=config)
    group.add_function(name="log_farm_event", fn=_log_farm_event, description=_log_farm_event.__doc__)
    group.add_function(name="query_farm_history", fn=_query_farm_history, description=_query_farm_history.__doc__)
    group.add_function(name="list_farm_zones", fn=_list_farm_zones, description=_list_farm_zones.__doc__)
    yield group

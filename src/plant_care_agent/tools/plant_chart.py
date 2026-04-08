"""plant_chart — 植物生长数据可视化工具（纯文本版）。

读取 data/garden/{植物名}/journal.md 日志，生成文字版图表。
无 matplotlib / 字体依赖，适用于任何服务器环境。
"""

import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from plant_care_agent.garden_paths import journal_path

logger = logging.getLogger(__name__)

EVENT_LINE_RE = re.compile(r"^- \*\*\[(.+?)]\*\*\s+(.+?)(?:\s+_(\d{2}:\d{2})_)?$", re.MULTILINE)
DATE_HEADING_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2})", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

EVENT_ICONS = {
    "播种": "🌰", "发芽": "🌱", "移栽": "🔄",
    "浇水": "💧", "施肥": "🧪", "修剪": "✂️",
    "开花": "🌸", "结果": "🍅", "采收": "🧺",
    "病害": "🦠", "虫害": "🐛", "观察": "👁️",
    "其他": "📝",
}

BAR_CHARS = "▏▎▍▌▋▊▉█"


def _bar(value: int, max_val: int, width: int = 20) -> str:
    if max_val <= 0:
        return ""
    filled = int(value / max_val * width)
    return "█" * filled + "░" * (width - filled)


def _parse_events(body: str) -> list[dict]:
    events: list[dict] = []
    current_date = ""
    for line in body.splitlines():
        dm = DATE_HEADING_RE.match(line)
        if dm:
            current_date = dm.group(1)
            continue
        em = EVENT_LINE_RE.match(line)
        if em and current_date:
            events.append({
                "date": current_date,
                "type": em.group(1),
                "desc": em.group(2).strip(),
                "time": em.group(3) or "",
            })
    return events


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


def _load_plant(path: Path) -> tuple[dict[str, str], str, list[dict]]:
    text = path.read_text(encoding="utf-8")
    fm = _parse_fm(text)
    body = FRONTMATTER_RE.sub("", text, count=1)
    events = _parse_events(body)
    return fm, body, events


class PlantChartConfig(FunctionBaseConfig, name="plant_chart"):
    garden_dir: str = Field(default="./data/garden")


@register_function(config_type=PlantChartConfig)
async def plant_chart_function(config: PlantChartConfig, _builder: Builder):
    garden = Path(config.garden_dir)

    async def _timeline(plant_id: str) -> str:
        """Generate a text-based timeline for a plant's growth events.
        Input: plant name/ID.
        Returns: formatted timeline text."""
        pid = plant_id.strip()
        path = journal_path(garden, pid)
        if not path.exists():
            return f"未找到「{pid}」的日志文件。"

        fm, _, events = _load_plant(path)
        if not events:
            return f"「{pid}」暂无事件记录，无法生成时间线。"

        name = fm.get("name", pid)
        stage = fm.get("stage", "")
        planted = fm.get("planted", "")

        lines = [f"🌱 {name} 生长时间线  [{stage}]", ""]

        if planted:
            try:
                days_total = (datetime.now().date() - datetime.strptime(planted, "%Y-%m-%d").date()).days
                lines.append(f"📅 种植于 {planted}（已 {days_total} 天）")
            except ValueError:
                pass
            lines.append("")

        lines.append("─" * 50)

        current_date = ""
        for e in events:
            icon = EVENT_ICONS.get(e["type"], "📝")
            time_str = f" {e['time']}" if e["time"] else ""
            if e["date"] != current_date:
                current_date = e["date"]
                lines.append(f"")
                lines.append(f"  📆 {current_date}")
                lines.append(f"  │")
            lines.append(f"  ├─ {icon} [{e['type']}] {e['desc']}{time_str}")

        lines.append(f"  │")
        lines.append(f"  └─ 至今共 {len(events)} 条记录")
        lines.append("─" * 50)

        return "\n".join(lines)

    async def _dashboard(plant_id: str) -> str:
        """Generate a text-based dashboard for a plant (activity + distribution + stats).
        Input: plant name/ID.
        Returns: formatted dashboard text."""
        pid = plant_id.strip()
        path = journal_path(garden, pid)
        if not path.exists():
            return f"未找到「{pid}」的日志文件。"

        fm, _, events = _load_plant(path)
        if not events:
            return f"「{pid}」暂无事件记录。"

        name = fm.get("name", pid)
        planted = fm.get("planted", "-")
        stage = fm.get("stage", "-")
        species = fm.get("species", "-")
        location = fm.get("location", "-")

        try:
            days = (datetime.now().date() - datetime.strptime(planted, "%Y-%m-%d").date()).days
        except (ValueError, TypeError):
            days = "-"

        dates_str = sorted(set(e["date"] for e in events))
        events_per_day: dict[str, int] = Counter(e["date"] for e in events)
        type_counts = Counter(e["type"] for e in events)

        lines = [
            f"🌱 {name} 养护看板",
            "═" * 50,
            "",
            "📊 基本信息",
            "─" * 30,
            f"  品种: {species}",
            f"  位置: {location}",
            f"  种植日期: {planted}",
            f"  种植天数: {days}",
            f"  当前阶段: {stage}",
            f"  总事件数: {len(events)}",
            f"  活跃天数: {len(dates_str)}",
            "",
        ]

        lines.append("📈 每日活跃度")
        lines.append("─" * 30)
        max_daily = max(events_per_day.values()) if events_per_day else 1
        for d in dates_str[-14:]:
            cnt = events_per_day[d]
            bar = _bar(cnt, max_daily, 15)
            lines.append(f"  {d[5:]}  {bar} {cnt}")
        if len(dates_str) > 14:
            lines.append(f"  ...（仅显示最近 14 天，共 {len(dates_str)} 天）")
        lines.append("")

        lines.append("🥧 事件类型分布")
        lines.append("─" * 30)
        total = len(events)
        max_type_count = max(type_counts.values()) if type_counts else 1
        for etype, cnt in type_counts.most_common():
            icon = EVENT_ICONS.get(etype, "📝")
            pct = cnt / total * 100
            bar = _bar(cnt, max_type_count, 12)
            lines.append(f"  {icon} {etype:<4}  {bar} {cnt:>3} ({pct:.0f}%)")
        lines.append("")

        lines.append("📅 养护周期分析")
        lines.append("─" * 30)
        for etype in ["浇水", "施肥", "修剪"]:
            typed_events = sorted([e for e in events if e["type"] == etype], key=lambda x: x["date"])
            if len(typed_events) >= 2:
                dates_obj = [datetime.strptime(e["date"], "%Y-%m-%d") for e in typed_events]
                intervals = [(dates_obj[i + 1] - dates_obj[i]).days for i in range(len(dates_obj) - 1)]
                avg = sum(intervals) / len(intervals)
                icon = EVENT_ICONS.get(etype, "📝")
                lines.append(f"  {icon} {etype}: 共 {len(typed_events)} 次, 平均间隔 {avg:.1f} 天")
                lines.append(f"       最近: {typed_events[-1]['date']}")
            elif len(typed_events) == 1:
                icon = EVENT_ICONS.get(etype, "📝")
                lines.append(f"  {icon} {etype}: 仅 1 次 ({typed_events[0]['date']})")

        lines.append("")
        lines.append("═" * 50)

        return "\n".join(lines)

    async def _compare(plant_names: str) -> str:
        """Compare multiple plants' growth progress in text format.
        Input: comma-separated plant names (e.g. '我的番茄,阳台薄荷').
        Returns: formatted comparison text."""
        names = [n.strip() for n in plant_names.split(",") if n.strip()]
        if len(names) < 2:
            return "请提供至少两个植物名称，用逗号分隔。"

        plant_data: list[tuple[str, dict, list]] = []
        for n in names:
            path = journal_path(garden, n)
            if not path.exists():
                continue
            fm, _, events = _load_plant(path)
            if events:
                plant_data.append((n, fm, events))

        if not plant_data:
            return "没有找到任何可比较的植物日志。"

        lines = [
            "🌱 植物生长进度对比",
            "═" * 55,
            "",
        ]

        header = f"  {'植物':<10} {'事件数':>6} {'活跃天':>6} {'种植天':>6}  {'阶段'}"
        lines.append(header)
        lines.append("  " + "─" * 50)

        max_events = max(len(ev) for _, _, ev in plant_data)

        for name, fm, events in plant_data:
            display_name = fm.get("name", name)
            active_days = len(set(e["date"] for e in events))
            planted = fm.get("planted", "")
            stage = fm.get("stage", "-")
            try:
                total_days = (datetime.now().date() - datetime.strptime(planted, "%Y-%m-%d").date()).days
            except (ValueError, TypeError):
                total_days = "-"
            lines.append(f"  {display_name:<10} {len(events):>6} {active_days:>6} {str(total_days):>6}  {stage}")

        lines.append("")
        lines.append("📈 活跃度对比 (最近 14 天)")
        lines.append("─" * 55)

        all_dates: set[str] = set()
        for _, _, events in plant_data:
            all_dates.update(e["date"] for e in events)
        recent_dates = sorted(all_dates)[-14:]

        if recent_dates:
            name_header = "  日期    " + "  ".join(
                f"{fm.get('name', n)[:4]:>4}" for n, fm, _ in plant_data
            )
            lines.append(name_header)
            lines.append("  " + "─" * (8 + 6 * len(plant_data)))

            for d in recent_dates:
                row = f"  {d[5:]}"
                for _, _, events in plant_data:
                    cnt = sum(1 for e in events if e["date"] == d)
                    cell = f"{cnt}" if cnt > 0 else "·"
                    row += f"  {cell:>4}"
                lines.append(row)

        lines.append("")
        lines.append("🥧 事件类型对比")
        lines.append("─" * 55)

        all_types: set[str] = set()
        for _, _, events in plant_data:
            all_types.update(e["type"] for e in events)

        type_header = f"  {'类型':<6}" + "  ".join(
            f"{fm.get('name', n)[:4]:>4}" for n, fm, _ in plant_data
        )
        lines.append(type_header)
        lines.append("  " + "─" * (6 + 6 * len(plant_data)))

        for etype in sorted(all_types):
            icon = EVENT_ICONS.get(etype, "📝")
            row = f"  {icon}{etype:<4}"
            for _, _, events in plant_data:
                cnt = sum(1 for e in events if e["type"] == etype)
                cell = str(cnt) if cnt > 0 else "-"
                row += f"  {cell:>4}"
            lines.append(row)

        lines.append("")
        lines.append("═" * 55)

        return "\n".join(lines)

    yield FunctionInfo.from_fn(
        _timeline,
        description="生成植物生长时间线（每个事件在时间轴上标注）。",
    )
    yield FunctionInfo.from_fn(
        _dashboard,
        description="生成植物综合看板（活跃度 + 事件分布 + 养护周期分析 + 基本信息统计）。",
    )
    yield FunctionInfo.from_fn(
        _compare,
        description="多植物生长进度对比。输入用逗号分隔的植物名称。",
    )

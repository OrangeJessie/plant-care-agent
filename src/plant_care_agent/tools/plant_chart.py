"""plant_chart — 植物生长数据可视化工具。

读取 data/garden/ 下的 Markdown 日志，用 matplotlib 生成:
- 事件时间线图
- 事件类型分布饼图
- 多植物对比图
- 单张综合看板（dashboard）

输出 PNG 文件到 data/charts/ 目录。
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

logger = logging.getLogger(__name__)

EVENT_LINE_RE = re.compile(r"^- \*\*\[(.+?)]\*\*\s+(.+?)(?:\s+_(\d{2}:\d{2})_)?$", re.MULTILINE)
DATE_HEADING_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2})", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

EVENT_COLORS = {
    "播种": "#8B4513", "发芽": "#32CD32", "移栽": "#FF8C00",
    "浇水": "#4169E1", "施肥": "#DAA520", "修剪": "#9370DB",
    "开花": "#FF69B4", "结果": "#FF4500", "采收": "#228B22",
    "病害": "#DC143C", "虫害": "#B22222", "观察": "#708090",
    "其他": "#A9A9A9",
}


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
    output_dir: str = Field(default="./data/charts")


@register_function(config_type=PlantChartConfig)
async def plant_chart_function(config: PlantChartConfig, _builder: Builder):
    garden = Path(config.garden_dir)
    charts = Path(config.output_dir)

    async def _timeline(plant_id: str) -> str:
        """Generate a timeline chart for a plant's growth events.
        Input: plant name/ID.
        Returns: path to the generated PNG image."""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            from matplotlib import font_manager
        except ImportError:
            return "需要安装 matplotlib: pip install matplotlib"

        path = garden / f"{plant_id.strip()}.md"
        if not path.exists():
            return f"未找到「{plant_id}」的日志文件。"

        fm, _, events = _load_plant(path)
        if not events:
            return f"「{plant_id}」暂无事件记录，无法生成图表。"

        _setup_chinese_font(plt, font_manager)

        dates = [datetime.strptime(e["date"], "%Y-%m-%d") for e in events]
        types = [e["type"] for e in events]
        colors = [EVENT_COLORS.get(t, "#A9A9A9") for t in types]

        fig, ax = plt.subplots(figsize=(14, 6))
        fig.patch.set_facecolor("#FAFAF5")
        ax.set_facecolor("#FAFAF5")

        for i, (d, t, c) in enumerate(zip(dates, types, colors)):
            y_offset = 1 if i % 2 == 0 else -1
            ax.scatter(d, 0, c=c, s=120, zorder=5, edgecolors="white", linewidth=1.5)
            ax.annotate(
                f"{t}\n{events[i]['desc'][:12]}",
                (d, 0), xytext=(0, 30 * y_offset),
                textcoords="offset points", ha="center", va="bottom" if y_offset > 0 else "top",
                fontsize=7, color=c,
                arrowprops=dict(arrowstyle="-", color=c, lw=0.8),
            )

        ax.axhline(y=0, color="#CCC", linewidth=2, zorder=1)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["top"].set_visible(False)

        name = fm.get("name", plant_id)
        stage = fm.get("stage", "")
        ax.set_title(f"🌱 {name} 生长时间线  [{stage}]", fontsize=14, pad=20)

        charts.mkdir(parents=True, exist_ok=True)
        out = charts / f"{plant_id.strip()}_timeline.png"
        fig.tight_layout()
        fig.savefig(str(out), dpi=150, bbox_inches="tight")
        plt.close(fig)

        return f"✅ 时间线图已生成: {out}"

    async def _dashboard(plant_id: str) -> str:
        """Generate a comprehensive dashboard for a plant (timeline + pie + stats).
        Input: plant name/ID.
        Returns: path to the generated PNG image."""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from matplotlib import font_manager
        except ImportError:
            return "需要安装 matplotlib: pip install matplotlib"

        path = garden / f"{plant_id.strip()}.md"
        if not path.exists():
            return f"未找到「{plant_id}」的日志文件。"

        fm, _, events = _load_plant(path)
        if not events:
            return f"「{plant_id}」暂无事件记录。"

        _setup_chinese_font(plt, font_manager)

        fig, axes = plt.subplots(1, 3, figsize=(18, 6),
                                 gridspec_kw={"width_ratios": [3, 1.5, 1.5]})
        fig.patch.set_facecolor("#FAFAF5")

        name = fm.get("name", plant_id)
        fig.suptitle(f"🌱 {name} 养护看板", fontsize=16, fontweight="bold", y=1.02)

        ax1 = axes[0]
        ax1.set_facecolor("#FAFAF5")
        dates_str = sorted(set(e["date"] for e in events))
        cumulative = list(range(1, len(dates_str) + 1))
        date_objs = [datetime.strptime(d, "%Y-%m-%d") for d in dates_str]

        events_per_day: dict[str, int] = Counter(e["date"] for e in events)
        daily_counts = [events_per_day[d] for d in dates_str]

        ax1.bar(date_objs, daily_counts, color="#90EE90", alpha=0.6, label="当日事件数", width=0.8)
        ax1_twin = ax1.twinx()
        ax1_twin.plot(date_objs, cumulative, color="#2E8B57", linewidth=2, marker="o", markersize=4, label="累计活跃天数")
        ax1.set_xlabel("日期")
        ax1.set_ylabel("当日事件数")
        ax1_twin.set_ylabel("累计活跃天数")
        ax1.set_title("事件活跃度", fontsize=12)
        ax1.tick_params(axis="x", rotation=45)

        ax2 = axes[1]
        type_counts = Counter(e["type"] for e in events)
        labels = list(type_counts.keys())
        sizes = list(type_counts.values())
        pie_colors = [EVENT_COLORS.get(l, "#A9A9A9") for l in labels]
        ax2.pie(sizes, labels=labels, colors=pie_colors, autopct="%1.0f%%",
                startangle=90, textprops={"fontsize": 9})
        ax2.set_title("事件类型分布", fontsize=12)

        ax3 = axes[2]
        ax3.axis("off")
        planted = fm.get("planted", "-")
        stage = fm.get("stage", "-")
        species = fm.get("species", "-")
        location = fm.get("location", "-")
        total = len(events)
        try:
            days = (datetime.now().date() - datetime.strptime(planted, "%Y-%m-%d").date()).days
        except (ValueError, TypeError):
            days = "-"

        stats_text = (
            f"品种: {species}\n"
            f"位置: {location}\n"
            f"种植日期: {planted}\n"
            f"种植天数: {days}\n"
            f"当前阶段: {stage}\n"
            f"总事件数: {total}\n"
            f"活跃天数: {len(dates_str)}\n"
        )
        ax3.text(0.1, 0.9, "📊 基本信息", transform=ax3.transAxes,
                 fontsize=12, fontweight="bold", va="top")
        ax3.text(0.1, 0.75, stats_text, transform=ax3.transAxes,
                 fontsize=10, va="top", family="monospace",
                 linespacing=1.8)

        charts.mkdir(parents=True, exist_ok=True)
        out = charts / f"{plant_id.strip()}_dashboard.png"
        fig.tight_layout()
        fig.savefig(str(out), dpi=150, bbox_inches="tight")
        plt.close(fig)

        return f"✅ 综合看板已生成: {out}"

    async def _compare(plant_names: str) -> str:
        """Compare multiple plants' growth progress in one chart.
        Input: comma-separated plant names (e.g. '我的番茄,阳台薄荷').
        Returns: path to the generated PNG image."""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from matplotlib import font_manager
        except ImportError:
            return "需要安装 matplotlib: pip install matplotlib"

        names = [n.strip() for n in plant_names.split(",") if n.strip()]
        if len(names) < 2:
            return "请提供至少两个植物名称，用逗号分隔。"

        _setup_chinese_font(plt, font_manager)

        fig, ax = plt.subplots(figsize=(12, 6))
        fig.patch.set_facecolor("#FAFAF5")
        ax.set_facecolor("#FAFAF5")

        palette = ["#2E8B57", "#FF6347", "#4169E1", "#FFD700", "#9370DB", "#FF69B4"]
        found_any = False

        for i, name in enumerate(names):
            path = garden / f"{name}.md"
            if not path.exists():
                continue
            fm, _, events = _load_plant(path)
            if not events:
                continue
            found_any = True

            dates_str = sorted(set(e["date"] for e in events))
            date_objs = [datetime.strptime(d, "%Y-%m-%d") for d in dates_str]
            cumulative = list(range(1, len(date_objs) + 1))
            color = palette[i % len(palette)]
            label = fm.get("name", name)
            ax.plot(date_objs, cumulative, color=color, linewidth=2,
                    marker="o", markersize=5, label=f"{label} ({len(events)}条)")

        if not found_any:
            plt.close(fig)
            return "没有找到任何可比较的植物日志。"

        ax.set_xlabel("日期")
        ax.set_ylabel("累计活跃天数")
        ax.set_title("🌱 植物生长进度对比", fontsize=14)
        ax.legend(loc="upper left")
        ax.tick_params(axis="x", rotation=45)
        ax.grid(True, alpha=0.3)

        charts.mkdir(parents=True, exist_ok=True)
        out = charts / "compare.png"
        fig.tight_layout()
        fig.savefig(str(out), dpi=150, bbox_inches="tight")
        plt.close(fig)

        return f"✅ 多植物对比图已生成: {out}"

    yield FunctionInfo.from_fn(
        _timeline,
        description="生成植物生长时间线图（每个事件在时间轴上标注）。",
    )
    yield FunctionInfo.from_fn(
        _dashboard,
        description="生成植物综合看板（活跃度柱状图 + 事件分布饼图 + 基本信息统计）。",
    )
    yield FunctionInfo.from_fn(
        _compare,
        description="多植物生长进度对比图（折线图叠加对比）。输入用逗号分隔的植物名称。",
    )


def _setup_chinese_font(plt, font_manager):
    """尝试加载中文字体，依次尝试多个常见字体名。"""
    candidates = [
        "WenQuanYi Micro Hei", "Noto Sans CJK SC", "SimHei",
        "PingFang SC", "Heiti SC", "Microsoft YaHei", "Source Han Sans SC",
        "AR PL UMing CN", "Droid Sans Fallback",
    ]
    for name in candidates:
        found = font_manager.findfont(name, fallback_to_default=False)
        if found and "LastResort" not in found:
            plt.rcParams["font.sans-serif"] = [name]
            plt.rcParams["axes.unicode_minus"] = False
            return
    plt.rcParams["axes.unicode_minus"] = False

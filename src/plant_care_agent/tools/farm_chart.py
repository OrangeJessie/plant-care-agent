"""farm_chart — 农业数据可视化工具。

基于传感器时序数据和操作记录生成:
- 传感器时序趋势图
- 地块仪表盘
- 多地块对比图
- 操作时间线图
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from plant_care_agent.sensors.hub import SensorHub

logger = logging.getLogger(__name__)

SENSOR_COLORS = {
    "soil_moisture": "#4169E1",
    "air_temperature": "#FF6347",
    "air_humidity": "#32CD32",
    "light_intensity": "#FFD700",
    "soil_ph": "#9370DB",
    "wind_speed": "#708090",
    "rainfall": "#00CED1",
}

SENSOR_NAMES = {
    "soil_moisture": "土壤湿度 (%)",
    "air_temperature": "空气温度 (°C)",
    "air_humidity": "空气湿度 (%)",
    "light_intensity": "光照强度 (lux)",
    "soil_ph": "土壤pH",
    "wind_speed": "风速 (m/s)",
    "rainfall": "降雨量 (mm/h)",
}


class FarmChartConfig(FunctionBaseConfig, name="farm_chart"):
    farm_dir: str = Field(default="./data/farm")
    output_dir: str = Field(default="./data/farm/charts")


def _setup_chinese_font(plt, font_manager):
    candidates = [
        "WenQuanYi Micro Hei", "Noto Sans CJK SC", "SimHei",
        "PingFang SC", "Heiti SC", "Microsoft YaHei", "Source Han Sans SC",
    ]
    for name in candidates:
        found = font_manager.findfont(name, fallback_to_default=False)
        if found and "LastResort" not in found:
            plt.rcParams["font.sans-serif"] = [name]
            plt.rcParams["axes.unicode_minus"] = False
            return
    plt.rcParams["axes.unicode_minus"] = False


@register_function(config_type=FarmChartConfig)
async def farm_chart_function(config: FarmChartConfig, _builder: Builder):
    hub = SensorHub(config.farm_dir)
    charts_dir = Path(config.output_dir)

    async def _sensor_trend(query: str) -> str:
        """Generate sensor trend chart for a zone.
        Input format: 'zone_id | sensor_types(comma-separated) | hours'
        Example: 'zone_a | soil_moisture,air_temperature | 48'"""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            from matplotlib import font_manager
        except ImportError:
            return "需要安装 matplotlib: pip install matplotlib"

        parts = [p.strip() for p in query.split("|")]
        if len(parts) < 1:
            return "格式: 'zone_id | sensor_types | hours'"

        zone_id = parts[0]
        sensor_types = [s.strip() for s in (parts[1] if len(parts) > 1 else "soil_moisture,air_temperature").split(",")]
        hours = int(parts[2]) if len(parts) > 2 and parts[2].strip().isdigit() else 24

        zc = hub.get_zone(zone_id)
        if zc is None:
            return f"未找到地块「{zone_id}」。"

        _setup_chinese_font(plt, font_manager)

        fig, ax1 = plt.subplots(figsize=(14, 6))
        fig.patch.set_facecolor("#FAFAF5")
        ax1.set_facecolor("#FAFAF5")

        axes = [ax1]
        if len(sensor_types) > 1:
            ax2 = ax1.twinx()
            axes.append(ax2)

        has_data = False
        for i, st in enumerate(sensor_types[:2]):
            history = hub.query_history(zone_id, st, hours)
            if not history:
                continue
            has_data = True
            times = [datetime.fromisoformat(h["ts"]) for h in history]
            values = [h["value"] for h in history]
            ax = axes[min(i, len(axes) - 1)]
            color = SENSOR_COLORS.get(st, "#333333")
            label = SENSOR_NAMES.get(st, st)
            ax.plot(times, values, color=color, linewidth=2, marker="o", markersize=3, label=label)
            ax.set_ylabel(label, color=color)
            ax.tick_params(axis="y", labelcolor=color)

        if not has_data:
            plt.close(fig)
            return f"地块「{zone_id}」在过去 {hours} 小时内无传感器数据，请先执行 read_sensors 采集。"

        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
        ax1.tick_params(axis="x", rotation=45)
        ax1.set_title(f"📊 {zc.name} 传感器趋势（{hours}h）", fontsize=14, pad=15)
        fig.legend(loc="upper left", bbox_to_anchor=(0.1, 0.95))
        ax1.grid(True, alpha=0.3)

        charts_dir.mkdir(parents=True, exist_ok=True)
        out = charts_dir / f"{zone_id}_trend.png"
        fig.tight_layout()
        fig.savefig(str(out), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return f"✅ 传感器趋势图已生成: {out}"

    async def _farm_dashboard(zone_id: str) -> str:
        """Generate a comprehensive dashboard for a farm zone.
        Shows current sensor gauges + 24h trends + alert status.
        Input: zone_id"""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from matplotlib import font_manager
            import numpy as np
        except ImportError:
            return "需要安装 matplotlib 和 numpy"

        zone_id = zone_id.strip()
        zc = hub.get_zone(zone_id)
        if zc is None:
            return f"未找到地块「{zone_id}」。"

        readings = hub.read_all(zone_id)
        if not readings:
            return f"地块「{zone_id}」暂无传感器数据。"

        _setup_chinese_font(plt, font_manager)

        fig = plt.figure(figsize=(18, 10))
        fig.patch.set_facecolor("#FAFAF5")
        fig.suptitle(f"🌾 {zc.name} 管理仪表盘", fontsize=16, fontweight="bold", y=0.98)

        gs = fig.add_gridspec(2, 4, hspace=0.4, wspace=0.3)

        for i, r in enumerate(readings[:4]):
            ax = fig.add_subplot(gs[0, i])
            ax.set_facecolor("#FAFAF5")
            color = SENSOR_COLORS.get(r.sensor_type, "#333")
            name = SENSOR_NAMES.get(r.sensor_type, r.sensor_type).split(" (")[0]

            lo, hi = zc.thresholds.get(r.sensor_type, (0, 100))
            ax.barh([0], [r.value], color=color, alpha=0.7, height=0.3)
            ax.axvline(lo, color="orange", linestyle="--", alpha=0.7)
            ax.axvline(hi, color="red", linestyle="--", alpha=0.7)
            ax.set_xlim(0, max(hi * 1.3, r.value * 1.2))
            ax.set_yticks([])
            ax.set_title(f"{name}\n{r.value:.1f} {r.unit}", fontsize=10, color=color)

            status_colors = {"normal": "green", "warning": "orange", "critical": "red"}
            ax.text(0.95, 0.05, r.status, transform=ax.transAxes, fontsize=8,
                    ha="right", color=status_colors.get(r.status, "gray"))

        for i, r in enumerate(readings[4:7]):
            ax = fig.add_subplot(gs[1, i])
            ax.set_facecolor("#FAFAF5")
            color = SENSOR_COLORS.get(r.sensor_type, "#333")
            name = SENSOR_NAMES.get(r.sensor_type, r.sensor_type).split(" (")[0]

            lo, hi = zc.thresholds.get(r.sensor_type, (0, 100))
            ax.barh([0], [r.value], color=color, alpha=0.7, height=0.3)
            ax.axvline(lo, color="orange", linestyle="--", alpha=0.7)
            ax.axvline(hi, color="red", linestyle="--", alpha=0.7)
            ax.set_xlim(0, max(hi * 1.3, r.value * 1.2, 1))
            ax.set_yticks([])
            ax.set_title(f"{name}\n{r.value:.1f} {r.unit}", fontsize=10, color=color)

        ax_info = fig.add_subplot(gs[1, 3])
        ax_info.axis("off")
        info_text = (
            f"地块: {zc.name}\n"
            f"作物: {zc.crop}\n"
            f"面积: {zc.area_mu} 亩\n"
            f"土壤: {zc.soil_type}\n"
            f"采集: {readings[0].timestamp}"
        )
        ax_info.text(0.1, 0.9, "📋 地块信息", transform=ax_info.transAxes, fontsize=11, fontweight="bold", va="top")
        ax_info.text(0.1, 0.7, info_text, transform=ax_info.transAxes, fontsize=9, va="top", linespacing=1.8)

        charts_dir.mkdir(parents=True, exist_ok=True)
        out = charts_dir / f"{zone_id}_dashboard.png"
        fig.savefig(str(out), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return f"✅ 地块仪表盘已生成: {out}"

    async def _zone_comparison(sensor_type: str) -> str:
        """Compare a specific sensor across all zones.
        Input: sensor_type (e.g. 'soil_moisture')"""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from matplotlib import font_manager
        except ImportError:
            return "需要安装 matplotlib"

        sensor_type = sensor_type.strip()
        if sensor_type not in SENSOR_NAMES:
            return f"未知传感器类型。可用: {', '.join(SENSOR_NAMES.keys())}"

        _setup_chinese_font(plt, font_manager)

        fig, ax = plt.subplots(figsize=(12, 6))
        fig.patch.set_facecolor("#FAFAF5")
        ax.set_facecolor("#FAFAF5")

        palette = ["#2E8B57", "#FF6347", "#4169E1", "#FFD700", "#9370DB", "#FF69B4"]
        found_any = False

        for i, zid in enumerate(hub.zone_ids):
            history = hub.query_history(zid, sensor_type, 24)
            if not history:
                continue
            found_any = True
            times = [datetime.fromisoformat(h["ts"]) for h in history]
            values = [h["value"] for h in history]
            zc = hub.get_zone(zid)
            label = zc.name if zc else zid
            ax.plot(times, values, color=palette[i % len(palette)], linewidth=2, marker="o", markersize=3, label=label)

        if not found_any:
            plt.close(fig)
            return f"所有地块在过去 24 小时内无 {sensor_type} 数据。"

        name = SENSOR_NAMES.get(sensor_type, sensor_type)
        ax.set_title(f"📊 多地块 {name} 对比", fontsize=14)
        ax.set_ylabel(name)
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.tick_params(axis="x", rotation=45)

        charts_dir.mkdir(parents=True, exist_ok=True)
        out = charts_dir / f"compare_{sensor_type}.png"
        fig.tight_layout()
        fig.savefig(str(out), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return f"✅ 多地块对比图已生成: {out}"

    async def _operation_timeline(query: str) -> str:
        """Generate an operation timeline overlaid on sensor data.
        Input format: 'zone_id | days'
        Example: 'zone_a | 7'"""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            from matplotlib import font_manager
        except ImportError:
            return "需要安装 matplotlib"

        parts = [p.strip() for p in query.split("|")]
        zone_id = parts[0]
        days = int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else 7

        zc = hub.get_zone(zone_id)
        if zc is None:
            return f"未找到地块「{zone_id}」。"

        _setup_chinese_font(plt, font_manager)

        history = hub.query_history(zone_id, "soil_moisture", days * 24)

        op_history_path = Path(config.farm_dir) / "operation_history.json"
        ops: list[dict] = []
        if op_history_path.exists():
            try:
                all_ops = json.loads(op_history_path.read_text(encoding="utf-8"))
                ops = [o for o in all_ops if o.get("zone_id") == zone_id]
            except (json.JSONDecodeError, ValueError):
                pass

        fig, ax = plt.subplots(figsize=(14, 6))
        fig.patch.set_facecolor("#FAFAF5")
        ax.set_facecolor("#FAFAF5")

        if history:
            times = [datetime.fromisoformat(h["ts"]) for h in history]
            values = [h["value"] for h in history]
            ax.plot(times, values, color="#4169E1", linewidth=2, label="土壤湿度 (%)")
            ax.set_ylabel("土壤湿度 (%)", color="#4169E1")

        op_icons = {"irrigate": "💧", "fertilize": "🧪", "pest_control": "🐛", "climate_control": "🌀", "harvest": "🌾"}
        for op in ops:
            ts_str = op.get("executed_at")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue
            icon = op_icons.get(op.get("operation_type", ""), "⚙️")
            ax.axvline(ts, color="red", linestyle="--", alpha=0.5)
            ax.text(ts, ax.get_ylim()[1] * 0.95, icon, fontsize=14, ha="center", va="top")

        ax.set_title(f"📊 {zc.name} 操作时间线（{days}天）", fontsize=14, pad=15)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.tick_params(axis="x", rotation=45)
        ax.grid(True, alpha=0.3)
        if history:
            ax.legend(loc="upper left")

        charts_dir.mkdir(parents=True, exist_ok=True)
        out = charts_dir / f"{zone_id}_op_timeline.png"
        fig.tight_layout()
        fig.savefig(str(out), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return f"✅ 操作时间线图已生成: {out}"

    yield FunctionInfo.from_fn(_sensor_trend, description="生成传感器时序趋势图。格式: 'zone_id | sensor_types | hours'。")
    yield FunctionInfo.from_fn(_farm_dashboard, description="生成地块综合仪表盘（传感器当前值 + 阈值 + 地块信息）。输入 zone_id。")
    yield FunctionInfo.from_fn(_zone_comparison, description="多地块同一传感器对比图。输入 sensor_type。")
    yield FunctionInfo.from_fn(_operation_timeline, description="生成操作时间线图（灌溉/施肥等事件叠加在传感器曲线上）。格式: 'zone_id | days'。")

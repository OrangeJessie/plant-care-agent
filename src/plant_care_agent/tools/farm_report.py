"""farm_report — 农场操作报告生成工具。

生成 Markdown 格式的日报 / 地块详细报告，存储于 data/farm/reports/。
"""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from plant_care_agent.sensors.hub import SensorHub

logger = logging.getLogger(__name__)

SENSOR_NAMES = {
    "soil_moisture": "土壤湿度",
    "air_temperature": "空气温度",
    "air_humidity": "空气湿度",
    "light_intensity": "光照强度",
    "soil_ph": "土壤pH",
    "wind_speed": "风速",
    "rainfall": "降雨量",
}

OP_NAMES = {
    "irrigate": "灌溉",
    "fertilize": "施肥",
    "pest_control": "除虫",
    "climate_control": "通风遮阳",
    "harvest": "收割",
}


class FarmReportConfig(FunctionBaseConfig, name="farm_report"):
    farm_dir: str = Field(default="./data/farm")
    output_dir: str = Field(default="./data/farm/reports")


def _load_operations(farm_dir: Path) -> list[dict]:
    p = farm_dir / "operation_history.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return []


def _load_pending(farm_dir: Path) -> list[dict]:
    p = farm_dir / "pending_operations.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return []


@register_function(config_type=FarmReportConfig)
async def farm_report_function(config: FarmReportConfig, _builder: Builder):
    farm_dir = Path(config.farm_dir)
    report_dir = Path(config.output_dir)
    hub = SensorHub(config.farm_dir)

    async def _generate_daily_report(target_date: str) -> str:
        """Generate a daily farm report summarizing all zones.
        Input: date in YYYY-MM-DD format (or 'today').
        Returns path to generated report."""
        target_date = target_date.strip()
        if target_date.lower() in ("today", "今天", ""):
            dt = date.today()
        else:
            try:
                dt = datetime.strptime(target_date, "%Y-%m-%d").date()
            except ValueError:
                return "日期格式错误，请使用 YYYY-MM-DD。"

        date_str = dt.isoformat()

        lines = [
            f"# 🌾 农场日报 — {date_str}\n",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
            "---\n",
        ]

        lines.append("## 📡 各地块传感器概况\n")
        for zid in hub.zone_ids:
            zc = hub.get_zone(zid)
            if zc is None:
                continue
            readings = hub.read_all(zid)
            lines.append(f"### {zc.name} ({zid})\n")
            lines.append(f"- 作物: {zc.crop} | 面积: {zc.area_mu}亩 | 土壤: {zc.soil_type}")
            if readings:
                lines.append("")
                lines.append("| 传感器 | 值 | 状态 |")
                lines.append("|--------|----|------|")
                for r in readings:
                    name = SENSOR_NAMES.get(r.sensor_type, r.sensor_type)
                    status_icon = {"normal": "🟢", "warning": "🟡", "critical": "🔴"}.get(r.status, "⚪")
                    lines.append(f"| {name} | {r.value:.1f} {r.unit} | {status_icon} {r.status} |")
            lines.append("")

        alerts = hub.check_alerts()
        lines.append("## ⚠️ 告警汇总\n")
        if alerts:
            for a in alerts:
                sensor_name = SENSOR_NAMES.get(a["sensor"], a["sensor"])
                lines.append(f"- **[{a['status'].upper()}]** {a['zone_name']}: {sensor_name} = {a['value']} {a['unit']} (阈值: {a['threshold']})")
        else:
            lines.append("无告警。所有传感器指标正常。")
        lines.append("")

        all_ops = _load_operations(farm_dir)
        today_ops = [o for o in all_ops if o.get("executed_at", "").startswith(date_str)]
        lines.append("## 🔧 今日操作记录\n")
        if today_ops:
            for op in today_ops:
                op_name = OP_NAMES.get(op.get("operation_type", ""), op.get("operation_type", ""))
                lines.append(f"- **{op_name}** @ {op.get('zone_name', op.get('zone_id', '-'))}")
                lines.append(f"  - 时间: {op.get('executed_at', '-')}")
                lines.append(f"  - 原因: {op.get('reason', '-')}")
        else:
            lines.append("今日无操作记录。")
        lines.append("")

        pending = _load_pending(farm_dir)
        lines.append("## 📋 待处理事项\n")
        if pending:
            for op in pending:
                op_name = OP_NAMES.get(op.get("operation_type", ""), op.get("operation_type", ""))
                lines.append(f"- [{op['operation_id']}] {op_name} @ {op.get('zone_name', '-')}: {op.get('reason', '-')}")
        else:
            lines.append("无待处理操作。")
        lines.append("")

        lines.append("---\n")
        lines.append(f"_报告由农场智能管理助手自动生成_")

        report_dir.mkdir(parents=True, exist_ok=True)
        out = report_dir / f"daily_{date_str}.md"
        out.write_text("\n".join(lines), encoding="utf-8")
        return f"✅ 日报已生成: {out}"

    async def _generate_zone_report(query: str) -> str:
        """Generate a detailed report for a specific zone.
        Input format: 'zone_id | days(optional, default 7)'
        Example: 'zone_a | 7'"""
        parts = [p.strip() for p in query.split("|")]
        zone_id = parts[0]
        days = int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else 7

        zc = hub.get_zone(zone_id)
        if zc is None:
            return f"未找到地块「{zone_id}」。"

        lines = [
            f"# 📊 地块报告 — {zc.name}\n",
            f"报告周期: 最近 {days} 天 | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
            "---\n",
        ]

        lines.append("## 基本信息\n")
        lines.append(f"- 地块ID: {zc.zone_id}")
        lines.append(f"- 作物: {zc.crop}")
        lines.append(f"- 面积: {zc.area_mu} 亩")
        lines.append(f"- 土壤类型: {zc.soil_type}")
        lines.append(f"- 位置: ({zc.latitude}, {zc.longitude})")
        lines.append("")

        lines.append("## 传感器数据摘要\n")
        for sensor_type in SENSOR_NAMES:
            history = hub.query_history(zone_id, sensor_type, days * 24)
            name = SENSOR_NAMES[sensor_type]
            if history:
                values = [h["value"] for h in history]
                avg = sum(values) / len(values)
                mn = min(values)
                mx = max(values)
                lines.append(f"- **{name}**: 均值 {avg:.1f} | 最低 {mn:.1f} | 最高 {mx:.1f} ({len(history)} 条数据)")
            else:
                lines.append(f"- **{name}**: 暂无数据")
        lines.append("")

        all_ops = _load_operations(farm_dir)
        cutoff = datetime.now() - timedelta(days=days)
        zone_ops = []
        for op in all_ops:
            if op.get("zone_id") != zone_id:
                continue
            ts_str = op.get("executed_at", "")
            try:
                if datetime.fromisoformat(ts_str) >= cutoff:
                    zone_ops.append(op)
            except ValueError:
                pass

        lines.append(f"## 操作历史（最近 {days} 天）\n")
        if zone_ops:
            lines.append("| 时间 | 操作 | 原因 |")
            lines.append("|------|------|------|")
            for op in zone_ops:
                op_name = OP_NAMES.get(op.get("operation_type", ""), op.get("operation_type", ""))
                lines.append(f"| {op.get('executed_at', '-')} | {op_name} | {op.get('reason', '-')} |")
        else:
            lines.append("该周期内无操作记录。")
        lines.append("")

        charts_dir = Path(config.output_dir)
        chart_files = [
            f"{zone_id}_trend.png",
            f"{zone_id}_dashboard.png",
            f"{zone_id}_op_timeline.png",
        ]
        existing_charts = [f for f in chart_files if (charts_dir / f).exists()]
        if existing_charts:
            lines.append("## 相关图表\n")
            for c in existing_charts:
                lines.append(f"- [{c}](../charts/{c})")
            lines.append("")

        lines.append("## 参考资料\n")
        lines.append(f"- [Open-Meteo 天气 API](https://open-meteo.com/) — 历史和预报天气数据")
        lines.append(f"- [FAO 灌溉与排水](http://www.fao.org/land-water/databases-and-software/crop-information/) — 作物需水量参考")
        lines.append(f"- [IPM 综合虫害管理](https://www.epa.gov/safepestcontrol/integrated-pest-management-ipm-principles) — 病虫害防治指南")
        lines.append("")
        lines.append("---\n")
        lines.append(f"_报告由农场智能管理助手自动生成_")

        report_dir.mkdir(parents=True, exist_ok=True)
        out = report_dir / f"zone_{zone_id}_{days}d.md"
        out.write_text("\n".join(lines), encoding="utf-8")
        return f"✅ 地块报告已生成: {out}"

    yield FunctionInfo.from_fn(_generate_daily_report, description="生成农场日报（所有地块传感器概况 + 告警 + 操作记录 + 待办事项）。输入日期或 'today'。")
    yield FunctionInfo.from_fn(_generate_zone_report, description="生成单地块详细报告（传感器摘要 + 操作历史 + 图表引用 + 参考资料）。格式: 'zone_id | days'。")

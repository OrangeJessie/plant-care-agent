"""plant_project — 植物管理项目工具（NAT Tool）。

Agent 通过此工具管理植物"子 Agent"：
- 用户说"种了 XXX"时 → create_plant_project
- 手动/定时触发巡检 → inspect_plant / inspect_all
- 管理生命周期 → list / remove
"""

import asyncio
import logging

from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from plant_care_agent.inspector.project_manager import PlantProjectManager
from plant_care_agent.inspector.inspector import PlantInspector
from plant_care_agent.inspector.report import aggregate_reports, generate_report

logger = logging.getLogger(__name__)


class PlantProjectConfig(FunctionBaseConfig, name="plant_project"):
    garden_dir: str = Field(default="./data/garden", description="花园数据目录。")
    default_latitude: float = Field(default=31.23)
    default_longitude: float = Field(default=121.47)


@register_function(config_type=PlantProjectConfig)
async def plant_project_function(config: PlantProjectConfig, _builder: Builder):
    mgr = PlantProjectManager(config.garden_dir)
    inspector = PlantInspector(config.garden_dir, config.default_latitude, config.default_longitude)

    async def _create_plant_project(entry: str) -> str:
        """Create a plant management project and start sub-agent monitoring.
        Input format: 'plant_name | species | location'
        Example: '我的番茄 | tomato | 阳台'
        Only plant_name is required; species and location are optional."""
        parts = [p.strip() for p in entry.split("|")]
        if not parts or not parts[0]:
            return "格式: 'plant_name | species(可选) | location(可选)'\n例如: '我的番茄 | tomato | 阳台'"

        name = parts[0]
        species = parts[1] if len(parts) > 1 else ""
        location = parts[2] if len(parts) > 2 else ""

        proj = mgr.create_project(name, species=species, location=location)

        result = await inspector.inspect(proj)
        report_path = generate_report(result, config.garden_dir)

        return (
            f"✅ 已为「{name}」创建植物管理项目（子 Agent 已上线）\n\n"
            f"  品种: {species or '未设置'}\n"
            f"  位置: {location or '未设置'}\n"
            f"  种植日期: {proj.planted_date}\n"
            f"  巡检间隔: 每 {proj.inspect_interval_hours} 小时\n\n"
            f"📋 首次巡检完成（{result.status_label}）:\n"
            + _format_inspection_brief(result)
            + f"\n\n详细报告: {report_path}\n\n"
            f"⚠️ 请同时使用 log_event 记录播种事件: '{name} | 播种 | <描述>"
            + (f" | species={species}" if species else "")
            + (f" | location={location}" if location else "")
            + "'"
        )

    async def _list_plant_projects(query: str) -> str:
        """List all managed plant projects with their monitoring status.
        Input can be anything (ignored)."""
        projects = mgr.list_projects(active_only=False)
        if not projects:
            return "暂无植物管理项目。用户种植新植物时，请使用 create_plant_project 创建。"

        lines = ["🌱 植物管理项目列表\n"]
        for p in projects:
            status = "🟢 活跃" if p.active else "⚪ 已停止"
            last = p.last_inspected[:16] if p.last_inspected else "从未"
            lines.append(
                f"  {status} {p.name}\n"
                f"     品种: {p.species or '-'} | 位置: {p.location or '-'}\n"
                f"     种植: {p.planted_date} | 上次巡检: {last}\n"
                f"     需要巡检: {'是' if p.needs_inspection() else '否'}"
            )
        return "\n".join(lines)

    async def _inspect_plant(plant_name: str) -> str:
        """Manually trigger inspection for a specific plant.
        Input: plant name (must be an existing project)."""
        plant_name = plant_name.strip()
        proj = mgr.get_project(plant_name)
        if proj is None:
            return f"未找到植物项目「{plant_name}」。请先用 create_plant_project 创建。"

        result = await inspector.inspect(proj)
        mgr.mark_inspected(plant_name)
        report_path = generate_report(result, config.garden_dir)

        return (
            f"📋 「{plant_name}」巡检完成（{result.status_label}）\n\n"
            + _format_inspection_detail(result)
            + f"\n详细报告: {report_path}"
        )

    async def _inspect_all(query: str) -> str:
        """Trigger inspection for all active plant projects.
        Input can be anything (ignored).
        Returns aggregated report from all plant sub-agents."""
        projects = mgr.list_projects(active_only=True)
        if not projects:
            return "暂无活跃的植物项目。"

        wx_data = await inspector._fetch_weather()
        results = []
        for proj in projects:
            result = await inspector.inspect(proj, weather_data=wx_data)
            mgr.mark_inspected(proj.name)
            generate_report(result, config.garden_dir)
            results.append(result)

        return aggregate_reports(results)

    async def _remove_plant_project(plant_name: str) -> str:
        """Remove (deactivate) a plant management project. Stops monitoring.
        Input: plant name."""
        plant_name = plant_name.strip()
        if mgr.remove_project(plant_name):
            return f"✅ 已停止「{plant_name}」的子 Agent 监控。历史数据保留。"
        return f"未找到植物项目「{plant_name}」。"

    yield FunctionInfo.from_fn(
        _create_plant_project,
        description="为新种植的植物创建管理项目，启动子 Agent 监控。格式: 'plant_name | species | location'。",
    )
    yield FunctionInfo.from_fn(
        _list_plant_projects,
        description="列出所有植物管理项目及其监控状态。",
    )
    yield FunctionInfo.from_fn(
        _inspect_plant,
        description="手动触发单株植物巡检（天气+养护+生长+病虫害分析）。输入植物名称。",
    )
    yield FunctionInfo.from_fn(
        _inspect_all,
        description="触发所有活跃植物的全面巡检，汇总各子 Agent 报告。",
    )
    yield FunctionInfo.from_fn(
        _remove_plant_project,
        description="停止植物管理项目的子 Agent 监控。输入植物名称。",
    )


def _format_inspection_brief(result) -> str:
    lines = []
    for item in result.items:
        icon = {"ok": "🟢", "warning": "🟡", "critical": "🔴"}.get(item.status, "⚪")
        lines.append(f"  {icon} {item.check_name}: {item.summary.split(chr(10))[0]}")
    return "\n".join(lines)


def _format_inspection_detail(result) -> str:
    lines = []
    for item in result.items:
        icon = {"ok": "🟢", "warning": "🟡", "critical": "🔴"}.get(item.status, "⚪")
        lines.append(f"{icon} **{item.check_name}**")
        lines.append(f"  {item.summary}")
        if item.actions:
            for a in item.actions:
                lines.append(f"  → {a}")
        lines.append("")
    return "\n".join(lines)

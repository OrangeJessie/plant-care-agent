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
        mgr.mark_inspected(name)
        report_path = generate_report(result, config.garden_dir)

        _push_first_inspection(config.garden_dir, name, result)

        return (
            f"✅ 已为「{name}」创建植物管理项目（子 Agent 已上线）\n\n"
            f"  品种: {species or '未设置'}\n"
            f"  位置: {location or '未设置'}\n"
            f"  种植日期: {proj.planted_date}\n"
            f"  自动巡检: 已开启（每日定时 + 紧急告警）\n\n"
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
            inspect_flag = "开启" if p.inspection_enabled else "已关闭"
            last = p.last_inspected[:16] if p.last_inspected else "从未"
            care_parts: list[str] = []
            if p.fert_interval_days:
                care_parts.append(f"施肥每{p.fert_interval_days}天")
            if p.fert_type:
                care_parts.append(p.fert_type)
            if p.fert_dormant_months:
                care_parts.append(f"免施肥:{p.fert_dormant_months}月")
            if p.water_interval_days:
                care_parts.append(f"浇水每{p.water_interval_days}天")
            if p.pest_interval_days:
                care_parts.append(f"驱虫每{p.pest_interval_days}天")
            care_info = " | ".join(care_parts) if care_parts else "未设置（请调用 set_care_schedule）"
            lines.append(
                f"  {status} {p.name}\n"
                f"     品种: {p.species or '-'} | 位置: {p.location or '-'}\n"
                f"     种植: {p.planted_date} | 上次巡检: {last}\n"
                f"     自动巡检: {inspect_flag}\n"
                f"     养护方案: {care_info}"
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

    async def _toggle_plant_inspection(entry: str) -> str:
        """Enable or disable automatic inspection for a plant.
        Input format: 'plant_name | on' or 'plant_name | off'
        Example: '我的番茄 | off' to disable inspection."""
        parts = [p.strip() for p in entry.split("|")]
        if len(parts) < 2:
            return "格式: '植物名 | on' 或 '植物名 | off'"

        name = parts[0]
        action = parts[1].lower()
        if action not in ("on", "off", "开启", "关闭"):
            return "第二个参数请用 on/off（或 开启/关闭）。"

        enabled = action in ("on", "开启")
        proj = mgr.toggle_inspection(name, enabled)
        if proj is None:
            return f"未找到植物项目「{name}」。"

        state = "已开启" if enabled else "已关闭"
        return f"✅ 「{name}」的自动巡检{state}。"

    async def _set_care_schedule(entry: str) -> str:
        """Set care schedule parameters for a plant (fertilization, watering & pest prevention).
        The LLM should call this after creating a plant project, based on plant species knowledge.

        Input format: 'plant_name | fert_interval_days=N | fert_type=TYPE | fert_dormant_months=M1,M2 | water_interval_days=N | pest_interval_days=N'
        All fields except plant_name are optional.

        Examples:
          '栀子花 | fert_interval_days=14 | fert_type=酸性肥料（硫酸亚铁/矾肥水） | fert_dormant_months=12,1,2 | water_interval_days=3 | pest_interval_days=30'
          '仙人掌 | fert_interval_days=30 | fert_type=稀薄液肥 | fert_dormant_months=11,12,1,2 | water_interval_days=14'
          '我的番茄 | fert_interval_days=10 | fert_type=有机肥+磷钾肥 | water_interval_days=2 | pest_interval_days=14'
        """
        parts = [p.strip() for p in entry.split("|")]
        if not parts or not parts[0]:
            return (
                "格式: 'plant_name | fert_interval_days=N | fert_type=TYPE "
                "| fert_dormant_months=M1,M2 | water_interval_days=N | pest_interval_days=N'"
            )

        name = parts[0]
        proj = mgr.get_project(name)
        if proj is None:
            return f"未找到植物项目「{name}」。请先用 create_plant_project 创建。"

        kwargs: dict = {}
        for part in parts[1:]:
            if "=" not in part:
                continue
            key, val = part.split("=", 1)
            key = key.strip()
            val = val.strip()
            if key == "fert_interval_days":
                kwargs["fert_interval_days"] = int(val)
            elif key == "fert_type":
                kwargs["fert_type"] = val
            elif key == "fert_dormant_months":
                kwargs["fert_dormant_months"] = val
            elif key == "water_interval_days":
                kwargs["water_interval_days"] = int(val)
            elif key == "pest_interval_days":
                kwargs["pest_interval_days"] = int(val)

        if not kwargs:
            return "未解析到有效参数。请至少提供一项: fert_interval_days / fert_type / fert_dormant_months / water_interval_days / pest_interval_days"

        updated = mgr.set_care_schedule(name, **kwargs)
        if updated is None:
            return f"未找到植物项目「{name}」。"

        lines = [f"✅ 已为「{name}」设置养护方案:"]
        if updated.fert_interval_days:
            lines.append(f"  施肥间隔: 每 {updated.fert_interval_days} 天")
        if updated.fert_type:
            lines.append(f"  推荐肥料: {updated.fert_type}")
        if updated.fert_dormant_months:
            lines.append(f"  免施肥月份: {updated.fert_dormant_months} 月")
        if updated.water_interval_days:
            lines.append(f"  浇水间隔: 每 {updated.water_interval_days} 天")
        if updated.pest_interval_days:
            lines.append(f"  驱虫间隔: 每 {updated.pest_interval_days} 天")
        return "\n".join(lines)

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
    async def _configure_auto_inspection(entry: str) -> str:
        """Configure the daily automatic inspection schedule and push notifications.
        This sets WHEN the system runs auto-inspection and HOW it notifies the user.

        Input format: 'time=HH:MM | push=ntfy | topic=TOPIC_NAME'
        All fields are optional. Shorthand: just 'HH:MM' sets the time only.

        Examples:
          '21:17' — set daily inspection at 21:17
          '9:00' — set daily inspection at 9:00
          'time=20:00 | push=ntfy | topic=my-garden' — set time + ntfy push
          'time=8:00 | push=webhook | url=https://example.com/hook' — set time + webhook
          'off' — disable auto inspection push
          'status' — show current configuration
        """
        from pathlib import Path as _Path
        from plant_care_agent.proactive.monitor_yaml import (
            load_monitor_config,
            save_monitor_config,
            ensure_template,
            monitor_config_path,
        )

        garden = _Path(config.garden_dir)
        entry = entry.strip()

        if entry.lower() == "status":
            cfg = load_monitor_config(garden)
            push = cfg.get("push") or {}
            h = cfg.get("digest_hour", 8)
            m = cfg.get("digest_minute", 0)
            mode = (push.get("mode") or "none").lower()
            lines = [
                "📋 自动巡检配置",
                f"  定时巡检: 每天 {h:02d}:{m:02d}",
                f"  推送方式: {mode}",
            ]
            if mode == "ntfy":
                topic = (push.get("ntfy") or {}).get("topic", "")
                lines.append(f"  ntfy topic: {topic}")
            elif mode == "webhook":
                url = (push.get("webhook") or {}).get("url", "")
                lines.append(f"  webhook url: {url}")
            lines.append(f"  配置文件: {monitor_config_path(garden)}")
            return "\n".join(lines)

        if entry.lower() == "off":
            cfg = load_monitor_config(garden)
            cfg.setdefault("push", {})["mode"] = "none"
            save_monitor_config(garden, cfg)
            return "✅ 已关闭自动巡检推送。巡检仍在后台运行，但不再主动通知。"

        ensure_template(garden)
        cfg = load_monitor_config(garden)

        parts = [p.strip() for p in entry.split("|")]
        time_str = ""
        push_mode = ""
        ntfy_topic = ""
        webhook_url = ""

        for part in parts:
            if "=" in part:
                key, val = part.split("=", 1)
                key = key.strip().lower()
                val = val.strip()
                if key == "time":
                    time_str = val
                elif key == "push":
                    push_mode = val.lower()
                elif key == "topic":
                    ntfy_topic = val
                elif key == "url":
                    webhook_url = val
            elif ":" in part and part.replace(":", "").replace(" ", "").isdigit():
                time_str = part

        result_lines = []

        if time_str:
            try:
                h_s, m_s = time_str.split(":")
                hour = int(h_s)
                minute = int(m_s)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    return "时间格式错误，请用 HH:MM（如 21:17、9:00）。"
                cfg["digest_hour"] = hour
                cfg["digest_minute"] = minute
                result_lines.append(f"⏰ 每日巡检时间: {hour:02d}:{minute:02d}")
            except (ValueError, IndexError):
                return "时间格式错误，请用 HH:MM（如 21:17、9:00）。"

        push_cfg = cfg.setdefault("push", {})
        if push_mode == "ntfy":
            push_cfg["mode"] = "ntfy"
            if ntfy_topic:
                push_cfg.setdefault("ntfy", {})["topic"] = ntfy_topic
            topic = (push_cfg.get("ntfy") or {}).get("topic", "")
            if topic:
                result_lines.append(f"📱 推送方式: ntfy (topic: {topic})")
            else:
                result_lines.append("📱 推送方式: ntfy (⚠️ 请补充 topic)")
        elif push_mode == "webhook":
            push_cfg["mode"] = "webhook"
            if webhook_url:
                push_cfg.setdefault("webhook", {})["url"] = webhook_url
            result_lines.append(f"🔗 推送方式: webhook")
        elif not push_mode and (push_cfg.get("mode") or "none") == "none":
            push_cfg["mode"] = "ntfy"
            auto_topic = f"plant-care-{garden.name}"
            push_cfg.setdefault("ntfy", {}).setdefault("topic", auto_topic)
            result_lines.append(f"📱 推送方式: ntfy (topic: {auto_topic})")
            result_lines.append("💡 请在手机上安装 ntfy 应用并订阅此 topic 以接收通知")

        cfg["enabled"] = True
        save_monitor_config(garden, cfg)

        if not result_lines:
            return "未检测到有效配置。格式: 'HH:MM' 或 'time=HH:MM | push=ntfy | topic=NAME'"

        return "✅ 自动巡检已配置！\n\n" + "\n".join(result_lines) + "\n\n到时间后系统会自动巡检所有植物并推送结果到您的设备。"

    yield FunctionInfo.from_fn(
        _toggle_plant_inspection,
        description="开启或关闭某棵植物的自动巡检。格式: '植物名 | on/off'。",
    )
    yield FunctionInfo.from_fn(
        _configure_auto_inspection,
        description=(
            "配置每日自动巡检的时间和推送通知方式。"
            "支持设置巡检时间（如 21:17）、推送方式（ntfy/webhook）。"
            "用 'status' 查看当前配置，'off' 关闭推送。"
            "格式: 'HH:MM' 或 'time=HH:MM | push=ntfy | topic=NAME'"
        ),
    )
    yield FunctionInfo.from_fn(
        _set_care_schedule,
        description=(
            "根据植物特性设置养护方案（施肥间隔、肥料类型、免施肥月份、浇水间隔、驱虫间隔）。"
            "创建植物项目后必须调用此工具。"
            "格式: 'plant_name | fert_interval_days=N | fert_type=TYPE | fert_dormant_months=M1,M2 | water_interval_days=N | pest_interval_days=N'"
        ),
    )


def _push_first_inspection(garden_dir: str, plant_name: str, result) -> None:
    """首次巡检完成后推送通知（如果配置了推送）。"""
    try:
        from pathlib import Path
        from plant_care_agent.proactive.monitor_yaml import load_monitor_config
        from plant_care_agent.proactive.push import push_digest

        cfg = load_monitor_config(Path(garden_dir))
        push_cfg = cfg.get("push") or {}
        mode = (push_cfg.get("mode") or "none").lower()
        if mode == "none":
            return

        icon = {"ok": "🟢", "warning": "🟡", "critical": "🔴"}.get(result.overall_status, "⚪")
        title = f"🌱 新植物「{plant_name}」已加入巡检"
        body_parts = [f"首次巡检结果: {icon} {result.status_label}", ""]
        for item in result.items:
            item_icon = {"ok": "🟢", "warning": "🟡", "critical": "🔴"}.get(item.status, "⚪")
            body_parts.append(f"{item_icon} {item.check_name}: {item.summary.split(chr(10))[0]}")
        if result.all_actions:
            body_parts.append("")
            body_parts.append("待办:")
            for a in result.all_actions[:5]:
                body_parts.append(f"  - {a}")

        push_digest(push_cfg, title, "\n".join(body_parts), [])
    except Exception as exc:
        logger.warning("首巡推送失败（非致命）: %s", exc)


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

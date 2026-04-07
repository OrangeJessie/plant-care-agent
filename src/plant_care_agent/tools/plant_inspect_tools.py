"""plant_inspect_tools — 巡检数据查询工具（NAT Tool）。

将天气评估、养护状态、生长分析、病虫害风险暴露为 LLM 可调用的独立工具。
LLM 调用这些工具获取原始数据，自主判断并给出建议——不再依赖硬编码规则。
"""

import logging
from datetime import date, datetime
from pathlib import Path

import aiohttp
from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from plant_care_agent.inspector.inspector import (
    FERTILIZE_TYPES,
    PEST_TYPES,
    WATERING_TYPES,
    _days_since_event_type,
    _load_journal,
    _parse_events,
    current_season,
)
from plant_care_agent.inspector.project_manager import PlantProjectManager

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

from plant_care_agent.weather_codes import WMO_WEATHER_CODES


class PlantInspectToolsConfig(FunctionBaseConfig, name="plant_inspect_tools"):
    garden_dir: str = Field(default="./data/garden", description="花园数据目录。")
    default_latitude: float = Field(default=31.23)
    default_longitude: float = Field(default=121.47)


@register_function(config_type=PlantInspectToolsConfig)
async def plant_inspect_tools_function(config: PlantInspectToolsConfig, _builder: Builder):
    garden_dir = Path(config.garden_dir)
    mgr = PlantProjectManager(garden_dir)

    async def _fetch_weather() -> dict:
        try:
            params = {
                "latitude": config.default_latitude,
                "longitude": config.default_longitude,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": (
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "precipitation_sum,precipitation_probability_max,"
                    "uv_index_max,wind_speed_10m_max"
                ),
                "timezone": "auto",
                "forecast_days": 3,
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(OPEN_METEO_URL, params=params) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except Exception as exc:
            logger.warning("Weather fetch failed: %s", exc)
            return {}

    def _resolve_project(name: str):
        mgr.reload()
        return mgr.get_project(name.strip())

    # ── Tool 1: 天气评估 ──

    async def _get_weather_assessment(plant_name: str) -> str:
        """Get raw weather data for a plant's location: current conditions + 3-day forecast.
        Returns temperature, humidity, wind, precipitation, weather codes.
        YOU (the LLM) should analyze these values and decide on risks and actions.
        Input: plant name (must exist as a project)."""
        proj = _resolve_project(plant_name)
        if proj is None:
            return f"未找到植物项目「{plant_name}」。请先用 create_plant_project 创建。"

        wx = await _fetch_weather()
        if not wx:
            return "无法获取天气数据，请稍后重试。"

        current = wx.get("current", {})
        daily = wx.get("daily", {})
        dates = daily.get("time", [])

        lines = [f"「{plant_name}」天气数据\n"]
        lines.append("【当前条件】")
        wcode = current.get("weather_code", -1)
        lines.append(f"  天气: {WMO_WEATHER_CODES.get(wcode, '未知')} (code={wcode})")
        lines.append(f"  温度: {current.get('temperature_2m', 'N/A')}°C")
        lines.append(f"  湿度: {current.get('relative_humidity_2m', 'N/A')}%")
        lines.append(f"  风速: {current.get('wind_speed_10m', 'N/A')} km/h")
        lines.append("")
        lines.append("【未来 3 天预报】")
        for i, d in enumerate(dates[:3]):
            t_min = daily.get("temperature_2m_min", [None] * 3)[i]
            t_max = daily.get("temperature_2m_max", [None] * 3)[i]
            precip = daily.get("precipitation_sum", [0] * 3)[i]
            precip_prob = daily.get("precipitation_probability_max", [0] * 3)[i]
            wind = daily.get("wind_speed_10m_max", [0] * 3)[i]
            dc = daily.get("weather_code", [0] * 3)[i]
            desc = WMO_WEATHER_CODES.get(dc, "未知")
            lines.append(
                f"  {d}: {desc}(code={dc}), "
                f"{t_min}~{t_max}°C, "
                f"降水={precip}mm(概率{precip_prob}%), "
                f"风速={wind}km/h"
            )

        lines.append("")
        lines.append("【植物信息】")
        lines.append(f"  品种: {proj.species or '未设置'}")
        lines.append(f"  位置: {proj.location or '未设置'}")
        lines.append(f"  当前季节: {current_season()}")
        lines.append("")
        lines.append("请根据以上天气数据，结合该植物特性，分析风险并给出建议。")
        return "\n".join(lines)

    # ── Tool 2: 养护状态 ──

    async def _get_care_status(plant_name: str) -> str:
        """Get care schedule status: days since last watering/fertilization, configured intervals, dormant months, and recommended fertilizer type.
        YOU (the LLM) should decide whether it's time to water/fertilize and what type of care is needed.
        Input: plant name (must exist as a project)."""
        proj = _resolve_project(plant_name)
        if proj is None:
            return f"未找到植物项目「{plant_name}」。请先用 create_plant_project 创建。"

        fm, body = _load_journal(garden_dir, plant_name)
        events = _parse_events(body)

        days_water = _days_since_event_type(events, WATERING_TYPES)
        days_fert = _days_since_event_type(events, FERTILIZE_TYPES)
        days_pest = _days_since_event_type(events, PEST_TYPES)

        today = date.today()
        dormant_months: set[int] = set()
        if proj.fert_dormant_months:
            for tok in proj.fert_dormant_months.split(","):
                tok = tok.strip()
                if tok.isdigit():
                    dormant_months.add(int(tok))

        # 找最近施肥事件的描述
        last_fert_desc = ""
        for ev in reversed(events):
            if ev["type"] in FERTILIZE_TYPES:
                last_fert_desc = ev["desc"]
                break

        lines = [f"「{plant_name}」养护状态\n"]
        lines.append("【浇水】")
        lines.append(f"  距上次浇水: {f'{days_water} 天' if days_water is not None else '无记录'}")
        lines.append(f"  设定浇水间隔: {f'{proj.water_interval_days} 天' if proj.water_interval_days else '未设置'}")
        lines.append("")
        lines.append("【施肥】")
        lines.append(f"  距上次施肥: {f'{days_fert} 天' if days_fert is not None else '无记录'}")
        if last_fert_desc:
            lines.append(f"  上次施肥内容: {last_fert_desc}")
        lines.append(f"  设定施肥间隔: {f'{proj.fert_interval_days} 天' if proj.fert_interval_days else '未设置'}")
        lines.append(f"  推荐肥料类型: {proj.fert_type or '未设置'}")
        lines.append(f"  免施肥月份: {proj.fert_dormant_months or '未设置'}")
        lines.append(f"  当前 {today.month} 月是否免施肥: {'是' if today.month in dormant_months else '否'}")
        lines.append("")
        lines.append("【驱虫】")
        lines.append(f"  距上次驱虫: {f'{days_pest} 天' if days_pest is not None else '无记录'}")
        lines.append(f"  设定驱虫间隔: {f'{proj.pest_interval_days} 天' if proj.pest_interval_days else '未设置（默认 30 天）'}")
        lines.append("")
        lines.append("【其他信息】")
        lines.append(f"  品种: {proj.species or '未设置'}")
        lines.append(f"  生长阶段: {fm.get('stage', '未知')}")
        weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][today.weekday()]
        lines.append(f"  今天: {today.isoformat()} ({weekday})")
        lines.append(f"  当前季节: {current_season()}")
        lines.append("")
        lines.append("请根据以上数据，判断是否需要浇水/施肥，并给出具体建议。")
        return "\n".join(lines)

    # ── Tool 3: 生长状态 ──

    async def _get_growth_status(plant_name: str) -> str:
        """Get growth information: planting date, days since planting, growth stage, total events, and recent event log.
        YOU (the LLM) should evaluate growth progress and give recommendations.
        Input: plant name (must exist as a project)."""
        proj = _resolve_project(plant_name)
        if proj is None:
            return f"未找到植物项目「{plant_name}」。请先用 create_plant_project 创建。"

        fm, body = _load_journal(garden_dir, plant_name)
        events = _parse_events(body)

        stage = fm.get("stage", "未知")
        planted_str = fm.get("planted") or proj.planted_date
        days_since_plant = 0
        if planted_str:
            try:
                days_since_plant = (date.today() - datetime.strptime(planted_str, "%Y-%m-%d").date()).days
            except ValueError:
                pass

        lines = [f"「{plant_name}」生长状态\n"]
        lines.append(f"  品种: {proj.species or '未设置'}")
        lines.append(f"  种植日期: {planted_str or '未知'}")
        lines.append(f"  种植天数: {days_since_plant} 天")
        lines.append(f"  生长阶段: {stage}")
        lines.append(f"  当前季节: {current_season()}")
        lines.append(f"  总事件数: {len(events)}")
        lines.append("")

        if events:
            recent = events[-10:]
            lines.append("【最近事件】")
            for e in recent:
                lines.append(f"  {e['date']} [{e['type']}] {e['desc']}")
        else:
            lines.append("暂无事件记录。")

        lines.append("")
        lines.append("请根据以上生长数据，评估生长进展并给出建议。")
        return "\n".join(lines)

    # ── Tool 4: 病虫害风险因素 ──

    async def _get_pest_risk_factors(plant_name: str) -> str:
        """Get environmental factors relevant to pest/disease risk: temperature, humidity, rainfall forecast, growth stage, and historical pest events.
        YOU (the LLM) should assess the risk level and recommend preventive or corrective actions.
        Input: plant name (must exist as a project)."""
        proj = _resolve_project(plant_name)
        if proj is None:
            return f"未找到植物项目「{plant_name}」。请先用 create_plant_project 创建。"

        fm, body = _load_journal(garden_dir, plant_name)
        events = _parse_events(body)

        wx = await _fetch_weather()
        current = wx.get("current", {}) if wx else {}
        daily = wx.get("daily", {}) if wx else {}

        days_pest = _days_since_event_type(events, PEST_TYPES)
        rain_days = sum(1 for p in daily.get("precipitation_sum", [])[:3] if p and p > 5)

        lines = [f"「{plant_name}」病虫害风险因素\n"]
        lines.append("【环境条件】")
        lines.append(f"  当前温度: {current.get('temperature_2m', 'N/A')}°C")
        lines.append(f"  当前湿度: {current.get('relative_humidity_2m', 'N/A')}%")
        lines.append(f"  未来 3 天中>5mm 降雨天数: {rain_days}")
        lines.append("")
        lines.append("【植物状态】")
        lines.append(f"  品种: {proj.species or '未设置'}")
        lines.append(f"  生长阶段: {fm.get('stage', '未知')}")
        lines.append(f"  位置: {proj.location or '未设置'}")
        lines.append(f"  当前季节: {current_season()}")
        lines.append(f"  距上次病虫害记录: {f'{days_pest} 天' if days_pest is not None else '无记录'}")

        pest_events = [e for e in events if e["type"] in PEST_TYPES]
        if pest_events:
            lines.append("")
            lines.append("【历史病虫害记录】")
            for e in pest_events[-5:]:
                lines.append(f"  {e['date']} [{e['type']}] {e['desc']}")

        lines.append("")
        lines.append(
            "请根据以上环境条件和植物状态，评估病虫害风险等级，"
            "并给出预防或处理建议。"
        )
        return "\n".join(lines)

    # ── 注册工具 ──

    yield FunctionInfo.from_fn(
        _get_weather_assessment,
        description=(
            "查询植物所在地的天气原始数据（当前条件+3天预报：温度、湿度、风速、降水、天气代码）。"
            "请调用后自主分析天气风险并给出建议。输入: 植物名称。"
        ),
    )
    yield FunctionInfo.from_fn(
        _get_care_status,
        description=(
            "查询植物的养护原始数据（距上次浇水/施肥天数、设定间隔、推荐肥料、免施肥月份等）。"
            "请调用后自主判断是否需要浇水/施肥并给出建议。输入: 植物名称。"
        ),
    )
    yield FunctionInfo.from_fn(
        _get_growth_status,
        description=(
            "查询植物的生长原始数据（种植天数、生长阶段、事件记录）。"
            "请调用后自主评估生长进展并给出建议。输入: 植物名称。"
        ),
    )
    yield FunctionInfo.from_fn(
        _get_pest_risk_factors,
        description=(
            "查询病虫害风险原始数据（温湿度、降雨、生长阶段、历史病虫害记录）。"
            "请调用后自主评估风险等级并给出防治建议。输入: 植物名称。"
        ),
    )

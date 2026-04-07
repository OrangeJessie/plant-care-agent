"""PlantInspector — 单株植物巡检子 Agent（规则引擎，无 LLM 调用）。

对每棵植物执行 4 项检查:
1. 天气评估 — 未来 3 天极端天气预警
2. 养护日程 — 今明两天待办任务
3. 生长分析 — 日志事件统计 + 距上次操作天数
4. 病虫害风险 — 基于天气条件和生长阶段的风险评估
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from plant_care_agent.inspector.project_manager import PlantProject

logger = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
EVENT_LINE_RE = re.compile(r"^- \*\*\[(.+?)]\*\*\s+(.+?)(?:\s+_\d{2}:\d{2}_)?$", re.MULTILINE)
DATE_HEADING_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2})", re.MULTILINE)

WATERING_TYPES = {"浇水", "灌溉"}
FERTILIZE_TYPES = {"施肥"}
PEST_TYPES = {"病害", "虫害", "除虫"}


@dataclass
class InspectionItem:
    check_name: str
    status: str  # ok / warning / critical
    summary: str
    actions: list[str] = field(default_factory=list)


@dataclass
class PlantInspectionResult:
    plant_name: str
    inspected_at: str
    items: list[InspectionItem] = field(default_factory=list)

    @property
    def overall_status(self) -> str:
        statuses = [it.status for it in self.items]
        if "critical" in statuses:
            return "critical"
        if "warning" in statuses:
            return "warning"
        return "ok"

    @property
    def status_label(self) -> str:
        labels = {"ok": "正常", "warning": "需关注", "critical": "紧急"}
        return labels.get(self.overall_status, "未知")

    @property
    def all_actions(self) -> list[str]:
        out: list[str] = []
        for it in self.items:
            out.extend(it.actions)
        return out


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


def _load_journal(garden_dir: Path, plant_name: str) -> tuple[dict[str, str], str]:
    from plant_care_agent.garden_paths import journal_path
    path = journal_path(garden_dir, plant_name)
    if not path.exists():
        return {}, ""
    text = path.read_text(encoding="utf-8")
    fm = _parse_fm(text)
    body = FRONTMATTER_RE.sub("", text, count=1)
    return fm, body


def _parse_events(body: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
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
            })
    return events


def _days_since_event_type(events: list[dict[str, str]], type_set: set[str]) -> int | None:
    """距最近一次指定类型事件的天数，没找到返回 None。"""
    today = date.today()
    for ev in reversed(events):
        if ev["type"] in type_set:
            try:
                ev_date = datetime.strptime(ev["date"], "%Y-%m-%d").date()
                return (today - ev_date).days
            except ValueError:
                continue
    return None


class PlantInspector:
    """对单株植物执行规则引擎巡检。"""

    def __init__(self, garden_dir: str | Path, default_lat: float = 31.23, default_lon: float = 121.47) -> None:
        self._garden_dir = Path(garden_dir)
        self._default_lat = default_lat
        self._default_lon = default_lon

    async def inspect(self, project: PlantProject, weather_data: dict | None = None) -> PlantInspectionResult:
        fm, body = _load_journal(self._garden_dir, project.name)
        events = _parse_events(body)

        if weather_data is None:
            weather_data = await self._fetch_weather()

        items = [
            self._check_weather(project, weather_data),
            self._check_care_schedule(project, fm, events),
            self._check_growth(project, fm, events),
            self._check_pest_risk(project, fm, events, weather_data),
        ]

        return PlantInspectionResult(
            plant_name=project.name,
            inspected_at=datetime.now().isoformat(timespec="seconds"),
            items=items,
        )

    async def _fetch_weather(self) -> dict:
        try:
            import aiohttp
            params = {
                "latitude": self._default_lat,
                "longitude": self._default_lon,
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
                async with session.get("https://api.open-meteo.com/v1/forecast", params=params) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except Exception as exc:
            logger.warning("Weather fetch failed: %s", exc)
            return {}

    def _check_weather(self, project: PlantProject, wx: dict) -> InspectionItem:
        if not wx:
            return InspectionItem("天气评估", "ok", "无法获取天气数据", [])

        daily = wx.get("daily", {})
        dates = daily.get("time", [])
        min_temps = daily.get("temperature_2m_min", [])
        max_temps = daily.get("temperature_2m_max", [])
        precip_sums = daily.get("precipitation_sum", [])
        precip_probs = daily.get("precipitation_probability_max", [])

        actions: list[str] = []
        warnings: list[str] = []
        status = "ok"

        for i, d in enumerate(dates[:3]):
            t_min = min_temps[i] if i < len(min_temps) else None
            t_max = max_temps[i] if i < len(max_temps) else None
            precip = precip_sums[i] if i < len(precip_sums) else 0
            precip_prob = precip_probs[i] if i < len(precip_probs) else 0

            if t_min is not None and t_min < 5:
                warnings.append(f"{d} 最低温 {t_min}°C")
                actions.append(f"低温预警: {d} 降至 {t_min}°C，建议移入室内或覆盖保温")
                status = "critical" if t_min < 0 else "warning"

            if t_max is not None and t_max > 35:
                warnings.append(f"{d} 最高温 {t_max}°C")
                actions.append(f"高温预警: {d} 升至 {t_max}°C，注意遮阴和增加浇水")
                status = max(status, "warning", key=lambda s: ["ok", "warning", "critical"].index(s))

            if precip and precip > 30:
                warnings.append(f"{d} 降水 {precip}mm")
                actions.append(f"暴雨预警: {d} 预计 {precip}mm，户外盆栽考虑避雨")
                status = max(status, "warning", key=lambda s: ["ok", "warning", "critical"].index(s))

        has_rain = any((p or 0) > 0 for p in precip_sums[:3])
        if has_rain:
            rain_days = [dates[i] for i, p in enumerate(precip_sums[:3]) if p and p > 0]
            actions.append(f"有降雨({', '.join(rain_days)})，可减少浇水")

        summary = "；".join(warnings) if warnings else "未来 3 天天气正常"
        return InspectionItem("天气评估", status, summary, actions)

    def _check_care_schedule(self, project: PlantProject, fm: dict[str, str], events: list[dict[str, str]]) -> InspectionItem:
        actions: list[str] = []
        status = "ok"

        days_water = _days_since_event_type(events, WATERING_TYPES)
        days_fert = _days_since_event_type(events, FERTILIZE_TYPES)

        stage = fm.get("stage", "")
        season = self._current_season()

        water_interval = 3 if season in ("夏季",) else 4
        if stage in ("苗期", "播种期"):
            water_interval = 2

        if days_water is None:
            actions.append("尚无浇水记录，请检查土壤湿度")
            status = "warning"
        elif days_water >= water_interval:
            actions.append(f"距上次浇水已 {days_water} 天，建议检查土壤湿度并浇水")
            status = "warning"

        fert_interval = 14
        if days_fert is not None and days_fert >= fert_interval and stage not in ("播种期", "采收期"):
            actions.append(f"距上次施肥已 {days_fert} 天，建议适量追肥")

        today = date.today()
        if today.weekday() == 5:
            actions.append("周末建议: 修剪枯叶黄叶、检查植物整体状态")

        summary_parts: list[str] = []
        if days_water is not None:
            summary_parts.append(f"距上次浇水 {days_water} 天")
        if days_fert is not None:
            summary_parts.append(f"距上次施肥 {days_fert} 天")
        summary = "；".join(summary_parts) if summary_parts else "暂无养护记录"

        return InspectionItem("养护日程", status, summary, actions)

    def _check_growth(self, project: PlantProject, fm: dict[str, str], events: list[dict[str, str]]) -> InspectionItem:
        stage = fm.get("stage", "未知")
        planted_str = fm.get("planted") or project.planted_date
        total_events = len(events)

        days_since_plant = 0
        if planted_str:
            try:
                days_since_plant = (date.today() - datetime.strptime(planted_str, "%Y-%m-%d").date()).days
            except ValueError:
                pass

        recent = events[-5:] if events else []
        recent_lines = [f"[{e['type']}] {e['desc'][:30]} ({e['date']})" for e in recent]

        actions: list[str] = []
        status = "ok"

        if days_since_plant > 7 and total_events < 2:
            actions.append("种植已超过一周但记录很少，建议定期记录生长观察")
            status = "warning"

        if stage == "播种期" and days_since_plant > 14:
            actions.append(f"种植 {days_since_plant} 天仍在播种期，确认是否已发芽")
            status = "warning"

        summary = f"阶段: {stage} | 种植 {days_since_plant} 天 | {total_events} 条记录"
        if recent_lines:
            summary += "\n  最近: " + "；".join(recent_lines[-3:])

        return InspectionItem("生长分析", status, summary, actions)

    def _check_pest_risk(self, project: PlantProject, fm: dict[str, str], events: list[dict[str, str]], wx: dict) -> InspectionItem:
        current = wx.get("current", {})
        temp = current.get("temperature_2m", 25)
        humidity = current.get("relative_humidity_2m", 60)

        risk_score = 0
        risk_factors: list[str] = []

        if temp > 25 and humidity > 75:
            risk_score += 2
            risk_factors.append(f"高温高湿 ({temp}°C/{humidity}%)")
        elif temp > 20 and humidity > 65:
            risk_score += 1
            risk_factors.append(f"温湿偏高 ({temp}°C/{humidity}%)")

        stage = fm.get("stage", "")
        if stage in ("苗期", "花期"):
            risk_score += 1
            risk_factors.append(f"{stage}易感")

        days_pest = _days_since_event_type(events, PEST_TYPES)
        if days_pest is not None and days_pest < 14:
            risk_score += 1
            risk_factors.append(f"近期有病虫害记录 ({days_pest} 天前)")

        daily = wx.get("daily", {})
        rain_days = sum(1 for p in daily.get("precipitation_sum", [])[:3] if p and p > 5)
        if rain_days >= 2:
            risk_score += 1
            risk_factors.append("连续降雨，真菌风险增高")

        if risk_score >= 3:
            level, status = "高", "critical"
        elif risk_score >= 2:
            level, status = "中", "warning"
        else:
            level, status = "低", "ok"

        actions: list[str] = []
        if risk_score >= 2:
            actions.append("检查叶片正反面是否有虫卵或病斑")
            actions.append("保持通风，避免叶面积水")
        if risk_score >= 3:
            actions.append("考虑预防性喷施生物农药（如苦参碱、多菌灵）")

        summary = f"风险等级: {level}"
        if risk_factors:
            summary += f" — {', '.join(risk_factors)}"

        return InspectionItem("病虫害风险", status, summary, actions)

    @staticmethod
    def _current_season() -> str:
        month = date.today().month
        if month in (3, 4, 5):
            return "春季"
        if month in (6, 7, 8):
            return "夏季"
        if month in (9, 10, 11):
            return "秋季"
        return "冬季"

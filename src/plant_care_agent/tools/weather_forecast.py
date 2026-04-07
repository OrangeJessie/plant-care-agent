import logging

import aiohttp
from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

CITY_COORDS: dict[str, tuple[float, float]] = {
    "北京": (39.90, 116.40), "上海": (31.23, 121.47), "广州": (23.13, 113.26),
    "深圳": (22.55, 114.06), "杭州": (30.27, 120.15), "成都": (30.57, 104.07),
    "武汉": (30.59, 114.30), "南京": (32.06, 118.80), "重庆": (29.56, 106.55),
    "西安": (34.26, 108.94), "长沙": (28.23, 112.94), "天津": (39.13, 117.20),
    "苏州": (31.30, 120.62), "郑州": (34.75, 113.65), "昆明": (25.04, 102.68),
    "大连": (38.91, 121.60), "厦门": (24.48, 118.09), "青岛": (36.07, 120.38),
    "哈尔滨": (45.75, 126.65), "沈阳": (41.80, 123.43),
}

from plant_care_agent.weather_codes import WMO_WEATHER_CODES


class WeatherForecastConfig(FunctionBaseConfig, name="weather_forecast"):
    default_latitude: float = Field(default=31.23, description="Default latitude (e.g. Shanghai 31.23)")
    default_longitude: float = Field(default=121.47, description="Default longitude (e.g. Shanghai 121.47)")


async def _geocode(city_name: str) -> tuple[float, float] | None:
    coords = CITY_COORDS.get(city_name)
    if coords:
        return coords

    async with aiohttp.ClientSession() as session:
        params = {"name": city_name, "count": 1, "language": "zh"}
        async with session.get(GEOCODING_URL, params=params) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            results = data.get("results", [])
            if not results:
                return None
            return (results[0]["latitude"], results[0]["longitude"])


async def _fetch_weather(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": (
            "weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_sum,precipitation_probability_max,"
            "uv_index_max,wind_speed_10m_max"
        ),
        "timezone": "auto",
        "forecast_days": 7,
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(OPEN_METEO_URL, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()


def _format_weather(data: dict) -> str:
    current = data.get("current", {})
    daily = data.get("daily", {})

    lines = ["📍 天气信息\n"]

    weather_desc = WMO_WEATHER_CODES.get(current.get("weather_code", -1), "未知")
    lines.append("【当前天气】")
    lines.append(f"  天气: {weather_desc}")
    lines.append(f"  温度: {current.get('temperature_2m', 'N/A')}℃")
    lines.append(f"  湿度: {current.get('relative_humidity_2m', 'N/A')}%")
    lines.append(f"  风速: {current.get('wind_speed_10m', 'N/A')} km/h")
    lines.append("")

    dates = daily.get("time", [])
    lines.append("【未来7天预报】")
    for i, date in enumerate(dates):
        code = daily["weather_code"][i] if i < len(daily.get("weather_code", [])) else -1
        desc = WMO_WEATHER_CODES.get(code, "未知")
        t_max = daily.get("temperature_2m_max", [None])[i]
        t_min = daily.get("temperature_2m_min", [None])[i]
        precip = daily.get("precipitation_sum", [None])[i]
        precip_prob = daily.get("precipitation_probability_max", [None])[i]
        uv = daily.get("uv_index_max", [None])[i]
        wind = daily.get("wind_speed_10m_max", [None])[i]

        line = f"  {date}: {desc}  {t_min}~{t_max}℃"
        if precip_prob is not None:
            line += f"  降水概率{precip_prob}%"
        if precip is not None and precip > 0:
            line += f"  降水量{precip}mm"
        if uv is not None:
            line += f"  UV{uv}"
        if wind is not None:
            line += f"  风速{wind}km/h"
        lines.append(line)

    has_rain = any(
        (p or 0) > 0
        for p in daily.get("precipitation_sum", [])
    )
    min_temps = [t for t in daily.get("temperature_2m_min", []) if t is not None]
    max_temps = [t for t in daily.get("temperature_2m_max", []) if t is not None]

    lines.append("\n【种植相关提示】")
    if has_rain:
        rain_days = [
            daily["time"][i] for i, p in enumerate(daily.get("precipitation_sum", []))
            if p and p > 0
        ]
        lines.append(f"  🌧 未来有降雨（{', '.join(rain_days)}），户外植物可减少浇水。")
    else:
        lines.append("  ☀ 未来7天无明显降水，注意给植物浇水。")

    if min_temps and min(min_temps) < 5:
        lines.append("  🥶 有低温天气，注意给不耐寒植物保暖或移入室内。")
    if max_temps and max(max_temps) > 35:
        lines.append("  🔥 有高温天气，注意给植物遮阴和增加浇水频率。")

    uv_vals = [u for u in daily.get("uv_index_max", []) if u is not None]
    if uv_vals and max(uv_vals) >= 8:
        lines.append("  ☀ UV指数较高，新移栽植物需遮阴过渡。")

    return "\n".join(lines)


@register_function(config_type=WeatherForecastConfig)
async def weather_forecast_function(config: WeatherForecastConfig, _builder: Builder):

    async def _get_weather(location: str) -> str:
        """Get current weather and 7-day forecast for a location.
        Accepts city name in Chinese or English, or 'lat,lon' coordinates.
        Provides temperature, humidity, precipitation, UV index, and planting tips."""
        location = location.strip()

        lat, lon = config.default_latitude, config.default_longitude

        if "," in location:
            try:
                parts = location.split(",")
                lat, lon = float(parts[0].strip()), float(parts[1].strip())
            except (ValueError, IndexError):
                pass
        else:
            coords = await _geocode(location)
            if coords:
                lat, lon = coords
            else:
                return f"无法识别位置「{location}」，将使用默认位置获取天气。请提供城市名或经纬度（如 31.23,121.47）。"

        try:
            data = await _fetch_weather(lat, lon)
            return _format_weather(data)
        except Exception as e:
            logger.error("Failed to fetch weather: %s", e)
            return f"获取天气失败: {e}。请稍后重试。"

    yield FunctionInfo.from_fn(
        _get_weather,
        description=(
            "查询指定地点的当前天气和未来7天预报，包含温度、湿度、降水、UV指数等，"
            "并给出种植相关提示。支持中文城市名、英文城市名或经纬度坐标。"
        ),
    )

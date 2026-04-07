"""同步拉取 Open-Meteo（供 cron 脚本使用）。"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

CITY_COORDS: dict[str, tuple[float, float]] = {
    "北京": (39.90, 116.40),
    "上海": (31.23, 121.47),
    "广州": (23.13, 113.26),
    "深圳": (22.55, 114.06),
    "杭州": (30.27, 120.15),
    "成都": (30.57, 104.07),
    "武汉": (30.59, 114.30),
    "南京": (32.06, 118.80),
    "重庆": (29.56, 106.55),
    "西安": (34.26, 108.94),
    "长沙": (28.23, 112.94),
    "天津": (39.13, 117.20),
    "苏州": (31.30, 120.62),
    "郑州": (34.75, 113.65),
    "昆明": (25.04, 102.68),
}

WMO_WEATHER_CODES: dict[int, str] = {
    0: "晴",
    1: "大部晴",
    2: "多云",
    3: "阴",
    45: "雾",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    95: "雷暴",
    80: "阵雨",
}


def _http_json(url: str, params: dict[str, str]) -> dict[str, Any]:
    q = urllib.parse.urlencode(params)
    full = f"{url}?{q}"
    req = urllib.request.Request(full, headers={"User-Agent": "plant-care-agent/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def resolve_lat_lon(
    location: str,
    default_lat: float,
    default_lon: float,
) -> tuple[float, float]:
    loc = location.strip()
    if "," in loc:
        try:
            a, b = loc.split(",", 1)
            return float(a.strip()), float(b.strip())
        except ValueError:
            pass
    if loc in CITY_COORDS:
        return CITY_COORDS[loc]
    try:
        data = _http_json(GEOCODING_URL, {"name": loc, "count": "1", "language": "zh"})
        results = data.get("results") or []
        if results:
            return float(results[0]["latitude"]), float(results[0]["longitude"])
    except Exception as e:
        logger.warning("geocode failed: %s", e)
    return default_lat, default_lon


def fetch_forecast_dict(lat: float, lon: float) -> dict[str, Any]:
    params = {
        "latitude": str(lat),
        "longitude": str(lon),
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": (
            "weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_sum,precipitation_probability_max"
        ),
        "timezone": "auto",
        "forecast_days": "7",
    }
    q = urllib.parse.urlencode(params)
    url = f"{OPEN_METEO_URL}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "plant-care-agent/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def format_weather_text(data: dict[str, Any], location_label: str) -> str:
    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    code = int(cur.get("weather_code") or -1)
    desc = WMO_WEATHER_CODES.get(code, "未知")
    lines = [
        f"📍 {location_label}",
        "",
        "【当前】",
        f"  {desc}  {cur.get('temperature_2m', 'N/A')}℃  "
        f"湿度{cur.get('relative_humidity_2m', 'N/A')}%  "
        f"风速{cur.get('wind_speed_10m', 'N/A')}km/h",
        "",
        "【7日概要】",
    ]
    dates = daily.get("time") or []
    wc_list = daily.get("weather_code") or []
    tmax_list = daily.get("temperature_2m_max") or []
    tmin_list = daily.get("temperature_2m_min") or []
    prec_list = daily.get("precipitation_sum") or []
    for i, d in enumerate(dates):
        c = int(wc_list[i]) if i < len(wc_list) else 0
        tmax = tmax_list[i] if i < len(tmax_list) else None
        tmin = tmin_list[i] if i < len(tmin_list) else None
        pr = prec_list[i] if i < len(prec_list) else 0
        lines.append(f"  {d}: {WMO_WEATHER_CODES.get(c, '未知')} {tmin}~{tmax}℃ 降水{pr}mm")
    mins = [x for x in tmin_list if x is not None]
    maxs = [x for x in tmax_list if x is not None]
    precs = [x for x in prec_list if x is not None]
    lines.append("")
    lines.append("【种植提示】")
    tips: list[str] = []
    if mins and min(mins) < 5:
        tips.append("  🥶 未来有低温（<5℃），注意防寒。")
    if maxs and max(maxs) > 35:
        tips.append("  🔥 未来有高温（>35℃），注意遮阴补水。")
    if precs and max(precs) > 15:
        tips.append("  🌧 有明显降水日，户外盆栽可减少浇水。")
    if not tips:
        tips.append("  无极端天气警报。")
    lines.extend(tips)
    return "\n".join(lines)


def weather_alert_fingerprint(data: dict[str, Any]) -> str:
    daily = data.get("daily") or {}
    mins = [x for x in daily.get("temperature_2m_min", []) if x is not None]
    maxs = [x for x in daily.get("temperature_2m_max", []) if x is not None]
    precs = [x for x in daily.get("precipitation_sum", []) if x is not None]
    flags = {
        "frost": bool(mins and min(mins) < 5),
        "heat": bool(maxs and max(maxs) > 35),
        "heavy_rain": bool(precs and max(precs) > 15),
    }
    return hashlib.sha256(json.dumps(flags, sort_keys=True).encode()).hexdigest()[:24]

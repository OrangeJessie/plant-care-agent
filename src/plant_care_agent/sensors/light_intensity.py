"""光照强度传感器模拟器。

物理模型：
- 日出日落钟形曲线：L(h) = L_max * cos((h - 12) * pi / day_length)
- 云量系数 0.1 ~ 1.0 从天气数据获取
- 夜间恒为 0
"""

from __future__ import annotations

import math

from plant_care_agent.sensors.base import BaseSensor, SensorContext, solar_elevation_factor


CLEAR_SKY_MAX_LUX = 100000.0
SUNRISE = 6.0
SUNSET = 18.0


class LightIntensitySensor(BaseSensor):
    sensor_type = "light_intensity"
    display_name = "光照强度"
    unit = "lux"
    min_value = 0.0
    max_value = 120000.0
    precision = 500.0

    def sample(self, ctx: SensorContext) -> float:
        solar = solar_elevation_factor(ctx.hour_of_day)
        if solar <= 0:
            return 0.0

        cloud_factor = 1.0
        if ctx.weather:
            cloud_factor = max(0.1, 1.0 - ctx.weather.cloud_cover * 0.85)

        season_factor = 0.85 + 0.15 * math.sin(2 * math.pi * (ctx.day_of_year - 80) / 365)

        lux = CLEAR_SKY_MAX_LUX * solar * cloud_factor * season_factor
        return lux

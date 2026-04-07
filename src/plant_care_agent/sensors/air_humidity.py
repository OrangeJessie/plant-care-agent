"""空气湿度传感器模拟器。

物理模型：
- 与温度负相关：温度高则相对湿度低
- 降雨时趋近 90-100%
- 夜间露点效应使湿度上升
"""

from __future__ import annotations

import math

from plant_care_agent.sensors.base import BaseSensor, OperationEffect, SensorContext


class AirHumiditySensor(BaseSensor):
    sensor_type = "air_humidity"
    display_name = "空气湿度"
    unit = "%"
    min_value = 0.0
    max_value = 100.0
    precision = 3.0

    def __init__(self) -> None:
        super().__init__()
        self._offset: float = 0.0

    def sample(self, ctx: SensorContext) -> float:
        base = 60.0
        if ctx.weather:
            base = ctx.weather.humidity

        temp = ctx.last_readings.get("air_temperature", 25.0)
        temp_effect = -(temp - 25.0) * 0.8

        hour = ctx.hour_of_day
        if hour < 6 or hour > 20:
            night_boost = 8.0 * math.sin(math.pi * (hour - 20.0) / 10.0) if hour > 20 else 8.0
        else:
            night_boost = 0.0

        rain_boost = 0.0
        if ctx.weather and ctx.weather.precipitation_probability > 50:
            rain_boost = min(30.0, ctx.weather.precipitation_probability * 0.3)

        humidity = base + temp_effect + night_boost + rain_boost + self._offset
        return max(10.0, min(100.0, humidity))

    def apply_effect(self, effect: OperationEffect) -> None:
        if effect.operation_type == "climate_control":
            self._offset += effect.params.get("humidity_delta", -10.0)
            self._offset = max(-30.0, min(30.0, self._offset))
        elif effect.operation_type == "irrigate":
            self._offset += 3.0

"""空气温度传感器模拟器。

物理模型：
- 正弦日变化：T(h) = T_avg + T_amp * sin((h - 14) * pi / 12)  (14 时最高)
- 天气 API 提供日高低温基线
- 阴天压低日温差振幅
"""

from __future__ import annotations

import math

from plant_care_agent.sensors.base import BaseSensor, OperationEffect, SensorContext


class AirTemperatureSensor(BaseSensor):
    sensor_type = "air_temperature"
    display_name = "空气温度"
    unit = "°C"
    min_value = -10.0
    max_value = 50.0
    precision = 0.5

    def __init__(self) -> None:
        super().__init__()
        self._offset: float = 0.0

    def sample(self, ctx: SensorContext) -> float:
        w = ctx.weather
        if w:
            t_avg = (w.temp_max + w.temp_min) / 2.0
            t_amp = (w.temp_max - w.temp_min) / 2.0
            cloud_damping = 1.0 - w.cloud_cover * 0.4
            t_amp *= cloud_damping
        else:
            t_avg = 25.0
            t_amp = 5.0

        phase = (ctx.hour_of_day - 14.0) * math.pi / 12.0
        temp = t_avg + t_amp * math.sin(phase) + self._offset
        return temp

    def apply_effect(self, effect: OperationEffect) -> None:
        if effect.operation_type == "climate_control":
            self._offset += effect.params.get("temp_delta", -2.0)
            self._offset = max(-10.0, min(10.0, self._offset))

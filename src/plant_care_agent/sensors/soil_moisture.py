"""土壤湿度传感器模拟器。

物理模型：
- 基线取决于土壤类型的田间持水量
- 随时间因蒸散作用（evapotranspiration）线性下降，速率受温度和风速影响
- 降雨 / 灌溉事件使湿度阶跃上升
- 浇水后用指数衰减模拟水分向深层渗透的过程
"""

from __future__ import annotations

import math
import time

from plant_care_agent.sensors.base import BaseSensor, OperationEffect, SensorContext

FIELD_CAPACITY: dict[str, float] = {
    "壤土": 35.0,
    "沙土": 20.0,
    "黏土": 45.0,
}

ET_BASE_RATE = 0.15  # %/hour 基础蒸散速率


class SoilMoistureSensor(BaseSensor):
    sensor_type = "soil_moisture"
    display_name = "土壤湿度"
    unit = "%"
    min_value = 0.0
    max_value = 100.0
    precision = 2.0

    def __init__(self) -> None:
        super().__init__()
        self._moisture: float | None = None
        self._last_ts: float = 0.0
        self._pending_irrigation: float = 0.0
        self._irrigation_ts: float = 0.0

    def _init_moisture(self, ctx: SensorContext) -> float:
        soil = ctx.zone_config.soil_type
        fc = FIELD_CAPACITY.get(soil, 35.0)
        return fc * 0.85

    def sample(self, ctx: SensorContext) -> float:
        now_ts = ctx.timestamp.timestamp()
        if self._moisture is None:
            self._moisture = self._init_moisture(ctx)
            self._last_ts = now_ts
            return self._moisture

        dt_hours = (now_ts - self._last_ts) / 3600.0
        if dt_hours <= 0:
            return self._moisture

        temp = 25.0
        wind = 5.0
        if ctx.zone_config.soil_type in FIELD_CAPACITY:
            pass
        if ctx.weather:
            temp = ctx.weather.temperature
            wind = ctx.weather.wind_speed_kmh

        temp_factor = 1.0 + max(0.0, (temp - 20.0)) * 0.03
        wind_factor = 1.0 + wind * 0.005
        et_rate = ET_BASE_RATE * temp_factor * wind_factor

        self._moisture -= et_rate * dt_hours

        if ctx.weather and ctx.weather.precipitation_probability > 60:
            rain_contribution = ctx.weather.precipitation_probability * 0.003 * dt_hours
            self._moisture += rain_contribution

        if self._pending_irrigation > 0:
            elapsed_h = (now_ts - self._irrigation_ts) / 3600.0
            absorbed = self._pending_irrigation * (1 - math.exp(-0.5 * elapsed_h))
            self._moisture += absorbed
            self._pending_irrigation -= absorbed

        self._moisture = max(5.0, min(95.0, self._moisture))
        self._last_ts = now_ts
        return self._moisture

    def apply_effect(self, effect: OperationEffect) -> None:
        if effect.operation_type == "irrigate":
            delta = effect.params.get("moisture_delta", 20.0)
            self._pending_irrigation += delta
            self._irrigation_ts = time.time()

"""风速传感器模拟器。

物理模型：
- 基于 Weibull 分布采样（形状参数 k=2）
- 尺度参数从天气数据来
- 阵风：以小概率产生 1.5x~2x 的瞬时峰值
"""

from __future__ import annotations

import random

from plant_care_agent.sensors.base import BaseSensor, SensorContext


GUST_PROBABILITY = 0.08
GUST_MULTIPLIER_RANGE = (1.5, 2.0)


class WindSpeedSensor(BaseSensor):
    sensor_type = "wind_speed"
    display_name = "风速"
    unit = "m/s"
    min_value = 0.0
    max_value = 30.0
    precision = 0.5

    def sample(self, ctx: SensorContext) -> float:
        base_kmh = 10.0
        if ctx.weather:
            base_kmh = max(1.0, ctx.weather.wind_speed_kmh)

        base_ms = base_kmh / 3.6
        scale = base_ms / 0.8862  # Weibull mean = scale * Gamma(1 + 1/k), k=2 => ~0.8862*scale

        speed = random.weibullvariate(scale, 2.0)

        if random.random() < GUST_PROBABILITY:
            gust = random.uniform(*GUST_MULTIPLIER_RANGE)
            speed *= gust

        return max(0.0, speed)

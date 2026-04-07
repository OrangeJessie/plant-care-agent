"""降雨量传感器模拟器。

物理模型：
- 降雨事件由天气预报的降水概率驱动
- 降雨强度呈 Gamma 分布
- 无降雨时恒为 0
"""

from __future__ import annotations

import random

from plant_care_agent.sensors.base import BaseSensor, SensorContext


RAIN_THRESHOLD_PROB = 40.0  # 降水概率 > 此值时可能有降雨


class RainfallSensor(BaseSensor):
    sensor_type = "rainfall"
    display_name = "降雨量"
    unit = "mm/h"
    min_value = 0.0
    max_value = 100.0
    precision = 0.2

    def sample(self, ctx: SensorContext) -> float:
        precip_prob = 0.0
        if ctx.weather:
            precip_prob = ctx.weather.precipitation_probability

        if precip_prob < RAIN_THRESHOLD_PROB:
            return 0.0

        intensity_prob = (precip_prob - RAIN_THRESHOLD_PROB) / (100.0 - RAIN_THRESHOLD_PROB)
        if random.random() > intensity_prob:
            return 0.0

        shape = 2.0
        scale = 3.0 + precip_prob * 0.1
        intensity = random.gammavariate(shape, scale)
        return min(intensity, 80.0)

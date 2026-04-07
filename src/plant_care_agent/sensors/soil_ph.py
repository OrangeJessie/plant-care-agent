"""土壤 pH 传感器模拟器。

物理模型：
- 基线由土壤类型决定
- 变化缓慢，施肥使 pH 偏移（氮肥酸化，石灰碱化）
- 偏移后缓慢回归基线
"""

from __future__ import annotations

import time

from plant_care_agent.sensors.base import BaseSensor, OperationEffect, SensorContext

SOIL_PH_BASELINE: dict[str, float] = {
    "壤土": 6.5,
    "沙土": 6.0,
    "黏土": 7.0,
}

RECOVERY_RATE = 0.002  # pH units per hour 回归速率


class SoilPhSensor(BaseSensor):
    sensor_type = "soil_ph"
    display_name = "土壤pH"
    unit = ""
    min_value = 3.0
    max_value = 9.0
    precision = 0.1

    def __init__(self) -> None:
        super().__init__()
        self._current_ph: float | None = None
        self._baseline: float = 6.5
        self._last_ts: float = 0.0

    def sample(self, ctx: SensorContext) -> float:
        self._baseline = SOIL_PH_BASELINE.get(ctx.zone_config.soil_type, 6.5)

        if self._current_ph is None:
            self._current_ph = self._baseline
            self._last_ts = ctx.timestamp.timestamp()
            return self._current_ph

        now_ts = ctx.timestamp.timestamp()
        dt_hours = (now_ts - self._last_ts) / 3600.0
        if dt_hours > 0:
            diff = self._baseline - self._current_ph
            recovery = diff * min(1.0, RECOVERY_RATE * dt_hours * 10)
            self._current_ph += recovery

        self._last_ts = now_ts
        return self._current_ph

    def apply_effect(self, effect: OperationEffect) -> None:
        if effect.operation_type == "fertilize":
            delta = effect.params.get("ph_delta", -0.3)
            if self._current_ph is not None:
                self._current_ph += delta
                self._current_ph = max(3.5, min(8.5, self._current_ph))

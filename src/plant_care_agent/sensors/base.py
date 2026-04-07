"""传感器模拟基础层：抽象基类、上下文和读数数据结构。"""

from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ZoneConfig:
    """单个地块的配置信息。"""

    zone_id: str
    name: str
    area_mu: float = 10.0  # 亩
    crop: str = "水稻"
    soil_type: str = "壤土"  # 壤土 / 沙土 / 黏土
    latitude: float = 31.23
    longitude: float = 121.47
    thresholds: dict[str, tuple[float, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        defaults: dict[str, tuple[float, float]] = {
            "soil_moisture": (25.0, 80.0),
            "air_temperature": (5.0, 38.0),
            "air_humidity": (20.0, 90.0),
            "light_intensity": (0.0, 100000.0),
            "soil_ph": (5.5, 7.5),
            "wind_speed": (0.0, 15.0),
            "rainfall": (0.0, 50.0),
        }
        for k, v in defaults.items():
            self.thresholds.setdefault(k, v)


@dataclass
class WeatherSnapshot:
    """从 weather_forecast 缓存的天气快照。"""

    temperature: float = 25.0
    humidity: float = 60.0
    wind_speed_kmh: float = 10.0
    weather_code: int = 0
    precipitation_probability: float = 0.0
    cloud_cover: float = 0.3
    temp_max: float = 30.0
    temp_min: float = 20.0


@dataclass
class SensorContext:
    """每次采样时传入的环境上下文。"""

    timestamp: datetime
    hour_of_day: float  # 0.0 ~ 24.0
    day_of_year: int
    weather: WeatherSnapshot | None = None
    last_readings: dict[str, float] = field(default_factory=dict)
    zone_config: ZoneConfig = field(default_factory=lambda: ZoneConfig(zone_id="default", name="默认地块"))

    @classmethod
    def now(cls, zone_config: ZoneConfig | None = None, weather: WeatherSnapshot | None = None) -> SensorContext:
        ts = datetime.now()
        return cls(
            timestamp=ts,
            hour_of_day=ts.hour + ts.minute / 60.0,
            day_of_year=ts.timetuple().tm_yday,
            weather=weather,
            zone_config=zone_config or ZoneConfig(zone_id="default", name="默认地块"),
        )


@dataclass
class OperationEffect:
    """农业操作对传感器的影响描述。"""

    operation_type: str  # irrigate / fertilize / pest_control / climate_control
    params: dict[str, float] = field(default_factory=dict)


@dataclass
class SensorReading:
    """传感器读数。"""

    sensor_type: str
    value: float
    unit: str
    timestamp: str
    status: str  # normal / warning / critical
    zone_id: str

    def to_dict(self) -> dict:
        return {
            "sensor_type": self.sensor_type,
            "value": round(self.value, 2),
            "unit": self.unit,
            "timestamp": self.timestamp,
            "status": self.status,
            "zone_id": self.zone_id,
        }


class BaseSensor(ABC):
    """所有模拟传感器的抽象基类。"""

    sensor_type: str = ""
    display_name: str = ""
    unit: str = ""
    min_value: float = 0.0
    max_value: float = 100.0
    precision: float = 1.0  # 高斯噪声 sigma

    def __init__(self) -> None:
        self._last_value: float | None = None

    @abstractmethod
    def sample(self, ctx: SensorContext) -> float:
        """根据上下文产生一个理想读数（不含噪声）。"""

    def apply_effect(self, effect: OperationEffect) -> None:
        """外部操作影响（子类按需覆盖）。"""

    def _add_noise(self, value: float) -> float:
        return value + random.gauss(0, self.precision)

    def _clamp(self, value: float) -> float:
        return max(self.min_value, min(self.max_value, value))

    def read(self, ctx: SensorContext) -> SensorReading:
        raw = self.sample(ctx)
        noisy = self._add_noise(raw)
        clamped = self._clamp(noisy)
        self._last_value = clamped

        lo, hi = ctx.zone_config.thresholds.get(self.sensor_type, (self.min_value, self.max_value))
        if clamped < lo or clamped > hi:
            margin = (hi - lo) * 0.15
            if clamped < lo - margin or clamped > hi + margin:
                status = "critical"
            else:
                status = "warning"
        else:
            status = "normal"

        return SensorReading(
            sensor_type=self.sensor_type,
            value=clamped,
            unit=self.unit,
            timestamp=ctx.timestamp.isoformat(timespec="seconds"),
            status=status,
            zone_id=ctx.zone_config.zone_id,
        )


def solar_elevation_factor(hour: float) -> float:
    """简化太阳高度因子 (0~1)，用于日照 / 温度曲线。"""
    return max(0.0, math.sin(math.pi * (hour - 6.0) / 12.0)) if 6.0 <= hour <= 18.0 else 0.0

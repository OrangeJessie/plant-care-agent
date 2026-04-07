"""SensorHub — 传感器统一管理器。

- 持有每个 zone 的 7 个 Sensor 实例
- 构造 SensorContext，聚合天气缓存和跨传感器最近读数
- 批量读取 / 单传感器读取
- 转发操作影响
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from plant_care_agent.sensors.base import (
    BaseSensor,
    OperationEffect,
    SensorContext,
    SensorReading,
    WeatherSnapshot,
    ZoneConfig,
)
from plant_care_agent.sensors.state_store import StateStore
from plant_care_agent.sensors.soil_moisture import SoilMoistureSensor
from plant_care_agent.sensors.air_temperature import AirTemperatureSensor
from plant_care_agent.sensors.air_humidity import AirHumiditySensor
from plant_care_agent.sensors.light_intensity import LightIntensitySensor
from plant_care_agent.sensors.soil_ph import SoilPhSensor
from plant_care_agent.sensors.wind_speed import WindSpeedSensor
from plant_care_agent.sensors.rainfall import RainfallSensor

logger = logging.getLogger(__name__)

ALL_SENSOR_TYPES = [
    "soil_moisture",
    "air_temperature",
    "air_humidity",
    "light_intensity",
    "soil_ph",
    "wind_speed",
    "rainfall",
]


def _create_sensors() -> dict[str, BaseSensor]:
    return {
        "soil_moisture": SoilMoistureSensor(),
        "air_temperature": AirTemperatureSensor(),
        "air_humidity": AirHumiditySensor(),
        "light_intensity": LightIntensitySensor(),
        "soil_ph": SoilPhSensor(),
        "wind_speed": WindSpeedSensor(),
        "rainfall": RainfallSensor(),
    }


class SensorHub:
    """管理所有地块的传感器实例和数据存储。"""

    def __init__(self, farm_dir: str | Path) -> None:
        self._farm_dir = Path(farm_dir)
        self._store = StateStore(self._farm_dir / "sensors")
        self._zones: dict[str, ZoneConfig] = {}
        self._sensors: dict[str, dict[str, BaseSensor]] = {}
        self._weather_cache: WeatherSnapshot | None = None
        self._load_farm_config()

    def _load_farm_config(self) -> None:
        cfg_path = self._farm_dir / "farm_config.yaml"
        if not cfg_path.exists():
            self._init_default_farm(cfg_path)
        try:
            import yaml
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.suffix == ".json" else {}

        for zone_data in data.get("zones", []):
            zid = zone_data.get("zone_id", "")
            if not zid:
                continue
            thresholds = zone_data.get("thresholds", {})
            th_dict: dict[str, tuple[float, float]] = {}
            for k, v in thresholds.items():
                if isinstance(v, (list, tuple)) and len(v) == 2:
                    th_dict[k] = (float(v[0]), float(v[1]))
            zc = ZoneConfig(
                zone_id=zid,
                name=zone_data.get("name", zid),
                area_mu=zone_data.get("area_mu", 10.0),
                crop=zone_data.get("crop", "水稻"),
                soil_type=zone_data.get("soil_type", "壤土"),
                latitude=zone_data.get("latitude", 31.23),
                longitude=zone_data.get("longitude", 121.47),
                thresholds=th_dict,
            )
            self._zones[zid] = zc
            self._sensors[zid] = _create_sensors()

    def _init_default_farm(self, cfg_path: Path) -> None:
        """首次运行时创建默认农场配置。"""
        self._farm_dir.mkdir(parents=True, exist_ok=True)
        default = {
            "farm_name": "示范农场",
            "zones": [
                {
                    "zone_id": "zone_a",
                    "name": "A区 - 水稻田",
                    "area_mu": 15.0,
                    "crop": "水稻",
                    "soil_type": "黏土",
                    "latitude": 31.23,
                    "longitude": 121.47,
                },
                {
                    "zone_id": "zone_b",
                    "name": "B区 - 蔬菜大棚",
                    "area_mu": 5.0,
                    "crop": "番茄",
                    "soil_type": "壤土",
                    "latitude": 31.23,
                    "longitude": 121.47,
                },
                {
                    "zone_id": "zone_c",
                    "name": "C区 - 果园",
                    "area_mu": 20.0,
                    "crop": "柑橘",
                    "soil_type": "壤土",
                    "latitude": 31.23,
                    "longitude": 121.47,
                },
            ],
        }
        try:
            import yaml
            cfg_path.write_text(yaml.dump(default, allow_unicode=True, default_flow_style=False), encoding="utf-8")
        except ImportError:
            cfg_path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def zone_ids(self) -> list[str]:
        return list(self._zones.keys())

    def get_zone(self, zone_id: str) -> ZoneConfig | None:
        return self._zones.get(zone_id)

    def set_weather(self, snapshot: WeatherSnapshot) -> None:
        self._weather_cache = snapshot

    def _build_ctx(self, zone_id: str) -> SensorContext:
        zc = self._zones.get(zone_id, ZoneConfig(zone_id=zone_id, name=zone_id))
        last = self._store.get_latest(zone_id)
        ctx = SensorContext.now(zone_config=zc, weather=self._weather_cache)
        if last:
            ctx.last_readings = last
        return ctx

    def read_all(self, zone_id: str) -> list[SensorReading]:
        if zone_id not in self._sensors:
            return []
        ctx = self._build_ctx(zone_id)
        readings: list[SensorReading] = []
        last_vals: dict[str, float] = {}

        read_order = ["air_temperature", "rainfall", "wind_speed", "air_humidity", "light_intensity", "soil_moisture", "soil_ph"]
        for st in read_order:
            sensor = self._sensors[zone_id].get(st)
            if sensor is None:
                continue
            ctx.last_readings = dict(last_vals)
            r = sensor.read(ctx)
            readings.append(r)
            last_vals[st] = r.value

        self._store.append(zone_id, readings)
        return readings

    def read_one(self, zone_id: str, sensor_type: str) -> SensorReading | None:
        if zone_id not in self._sensors:
            return None
        sensor = self._sensors[zone_id].get(sensor_type)
        if sensor is None:
            return None
        ctx = self._build_ctx(zone_id)
        return sensor.read(ctx)

    def apply_operation(self, zone_id: str, operation_type: str, params: dict[str, float] | None = None) -> None:
        if zone_id not in self._sensors:
            return
        effect = OperationEffect(operation_type=operation_type, params=params or {})
        for sensor in self._sensors[zone_id].values():
            sensor.apply_effect(effect)

    def check_alerts(self) -> list[dict]:
        alerts: list[dict] = []
        for zone_id in self._zones:
            readings = self.read_all(zone_id)
            for r in readings:
                if r.status in ("warning", "critical"):
                    zc = self._zones[zone_id]
                    lo, hi = zc.thresholds.get(r.sensor_type, (0, 100))
                    alerts.append({
                        "zone_id": zone_id,
                        "zone_name": zc.name,
                        "sensor": r.sensor_type,
                        "value": round(r.value, 2),
                        "unit": r.unit,
                        "status": r.status,
                        "threshold": f"{lo}~{hi}",
                    })
        return alerts

    def query_history(self, zone_id: str, sensor_type: str, hours: int = 24) -> list[dict[str, str | float]]:
        return self._store.query_history(zone_id, sensor_type, hours)

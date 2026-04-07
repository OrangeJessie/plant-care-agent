"""传感器时序数据 JSON 存储。

每个 zone 一个 JSON 文件，结构：
{
  "readings": [
    {"ts": "2026-04-07T10:00:00", "soil_moisture": 35.2, "air_temperature": 28.1, ...},
    ...
  ]
}
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from plant_care_agent.sensors.base import SensorReading

logger = logging.getLogger(__name__)

_MAX_AGE_DAYS = 30


class StateStore:
    """基于 JSON 文件的传感器时序存储。"""

    def __init__(self, store_dir: str | Path) -> None:
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, zone_id: str) -> Path:
        return self._dir / f"{zone_id}.json"

    def _load(self, zone_id: str) -> list[dict]:
        p = self._path(zone_id)
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data.get("readings", [])
        except (json.JSONDecodeError, KeyError):
            logger.warning("Corrupted sensor store for zone %s, resetting", zone_id)
            return []

    def _save(self, zone_id: str, readings: list[dict]) -> None:
        p = self._path(zone_id)
        p.write_text(
            json.dumps({"readings": readings}, ensure_ascii=False, indent=None),
            encoding="utf-8",
        )

    def append(self, zone_id: str, sensor_readings: list[SensorReading]) -> None:
        """追加一批读数到 zone 的存储文件。"""
        readings = self._load(zone_id)
        record: dict[str, str | float] = {"ts": sensor_readings[0].timestamp if sensor_readings else datetime.now().isoformat(timespec="seconds")}
        for sr in sensor_readings:
            record[sr.sensor_type] = round(sr.value, 2)
        readings.append(record)
        self._save(zone_id, readings)

    def query_history(
        self,
        zone_id: str,
        sensor_type: str,
        hours: int = 24,
    ) -> list[dict[str, str | float]]:
        """查询指定传感器的历史数据。"""
        readings = self._load(zone_id)
        cutoff = datetime.now() - timedelta(hours=hours)
        result: list[dict[str, str | float]] = []
        for r in readings:
            try:
                ts = datetime.fromisoformat(r["ts"])
            except (ValueError, KeyError):
                continue
            if ts >= cutoff and sensor_type in r:
                result.append({"ts": r["ts"], "value": r[sensor_type]})
        return result

    def get_latest(self, zone_id: str) -> dict[str, float]:
        """获取最新一条完整读数。"""
        readings = self._load(zone_id)
        if not readings:
            return {}
        last = readings[-1]
        return {k: v for k, v in last.items() if k != "ts" and isinstance(v, (int, float))}

    def cleanup(self, zone_id: str) -> int:
        """清理超过 _MAX_AGE_DAYS 天的旧数据，返回删除条数。"""
        readings = self._load(zone_id)
        cutoff = datetime.now() - timedelta(days=_MAX_AGE_DAYS)
        before = len(readings)
        readings = [
            r for r in readings
            if _parse_ts(r.get("ts", "")) is None or _parse_ts(r["ts"]) >= cutoff  # type: ignore[operator]
        ]
        after = len(readings)
        if after < before:
            self._save(zone_id, readings)
        return before - after


def _parse_ts(ts_str: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None

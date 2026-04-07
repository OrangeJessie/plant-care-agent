"""sensor_monitor — 传感器监控工具（NAT Tool）。

Agent 与传感器系统的唯一接口，通过 SensorHub 读取各类传感器数据。
"""

import logging

from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from plant_care_agent.sensors.hub import SensorHub

logger = logging.getLogger(__name__)

SENSOR_DISPLAY = {
    "soil_moisture": ("土壤湿度", "%"),
    "air_temperature": ("空气温度", "°C"),
    "air_humidity": ("空气湿度", "%"),
    "light_intensity": ("光照强度", "lux"),
    "soil_ph": ("土壤pH", ""),
    "wind_speed": ("风速", "m/s"),
    "rainfall": ("降雨量", "mm/h"),
}

STATUS_ICON = {"normal": "🟢", "warning": "🟡", "critical": "🔴"}


class SensorMonitorConfig(FunctionBaseConfig, name="sensor_monitor"):
    farm_dir: str = Field(default="./data/farm", description="农场数据根目录。")


@register_function(config_type=SensorMonitorConfig)
async def sensor_monitor_function(config: SensorMonitorConfig, _builder: Builder):
    hub = SensorHub(config.farm_dir)

    async def _read_sensors(zone_id: str) -> str:
        """Read all sensor values for a farm zone.
        Input: zone_id (e.g. 'zone_a').
        Returns formatted current readings for all 7 sensors."""
        zone_id = zone_id.strip()
        zc = hub.get_zone(zone_id)
        if zc is None:
            return f"未找到地块「{zone_id}」。可用地块: {', '.join(hub.zone_ids)}"

        readings = hub.read_all(zone_id)
        if not readings:
            return f"地块「{zone_id}」暂无传感器数据。"

        lines = [f"📡 地块「{zc.name}」传感器读数\n"]
        for r in readings:
            icon = STATUS_ICON.get(r.status, "⚪")
            display = SENSOR_DISPLAY.get(r.sensor_type, (r.sensor_type, r.unit))
            lines.append(f"  {icon} {display[0]}: {r.value:.1f} {display[1]}  [{r.status}]")

        lines.append(f"\n  采集时间: {readings[0].timestamp}")
        return "\n".join(lines)

    async def _read_sensor(query: str) -> str:
        """Read a single sensor for a zone.
        Input format: 'zone_id | sensor_type'
        Example: 'zone_a | soil_moisture'
        Sensor types: soil_moisture, air_temperature, air_humidity, light_intensity, soil_ph, wind_speed, rainfall"""
        parts = [p.strip() for p in query.split("|")]
        if len(parts) < 2:
            return "格式: 'zone_id | sensor_type'，例如: 'zone_a | soil_moisture'"

        zone_id, sensor_type = parts[0], parts[1]
        zc = hub.get_zone(zone_id)
        if zc is None:
            return f"未找到地块「{zone_id}」。可用地块: {', '.join(hub.zone_ids)}"

        reading = hub.read_one(zone_id, sensor_type)
        if reading is None:
            return f"未知传感器类型「{sensor_type}」。可用: {', '.join(SENSOR_DISPLAY.keys())}"

        icon = STATUS_ICON.get(reading.status, "⚪")
        display = SENSOR_DISPLAY.get(sensor_type, (sensor_type, reading.unit))
        return (
            f"{icon} {zc.name} - {display[0]}: {reading.value:.2f} {display[1]}\n"
            f"  状态: {reading.status} | 时间: {reading.timestamp}"
        )

    async def _read_sensor_history(query: str) -> str:
        """Query historical sensor data for a zone.
        Input format: 'zone_id | sensor_type | hours'
        Example: 'zone_a | soil_moisture | 24'
        Returns timestamped data points."""
        parts = [p.strip() for p in query.split("|")]
        if len(parts) < 2:
            return "格式: 'zone_id | sensor_type | hours(可选,默认24)'"

        zone_id, sensor_type = parts[0], parts[1]
        hours = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 24

        zc = hub.get_zone(zone_id)
        if zc is None:
            return f"未找到地块「{zone_id}」。可用地块: {', '.join(hub.zone_ids)}"

        history = hub.query_history(zone_id, sensor_type, hours)
        if not history:
            return f"地块「{zone_id}」的 {sensor_type} 在过去 {hours} 小时内无历史数据。"

        display = SENSOR_DISPLAY.get(sensor_type, (sensor_type, ""))
        lines = [f"📊 {zc.name} - {display[0]} 历史数据（最近 {hours} 小时，{len(history)} 条）\n"]
        for entry in history[-20:]:
            lines.append(f"  {entry['ts']}  {entry['value']:.2f} {display[1]}")
        if len(history) > 20:
            lines.append(f"  ...（共 {len(history)} 条，仅显示最近 20 条）")
        return "\n".join(lines)

    async def _list_zones(query: str) -> str:
        """List all configured farm zones with sensor summary.
        Input can be anything (ignored)."""
        if not hub.zone_ids:
            return "暂无已配置的农场地块。请编辑 data/farm/farm_config.yaml 添加地块。"

        lines = ["🌾 农场地块列表\n"]
        for zid in hub.zone_ids:
            zc = hub.get_zone(zid)
            if zc is None:
                continue
            lines.append(f"  📍 {zc.name} ({zid})")
            lines.append(f"     面积: {zc.area_mu}亩 | 作物: {zc.crop} | 土壤: {zc.soil_type}")
        return "\n".join(lines)

    async def _check_alerts(query: str) -> str:
        """Check all zones for sensor alerts (values outside thresholds).
        Input can be anything (ignored).
        Returns list of warnings and critical alerts."""
        alerts = hub.check_alerts()
        if not alerts:
            return "✅ 所有地块传感器指标正常，无告警。"

        lines = [f"⚠️ 传感器告警（共 {len(alerts)} 条）\n"]
        for a in alerts:
            icon = STATUS_ICON.get(a["status"], "⚪")
            display = SENSOR_DISPLAY.get(a["sensor"], (a["sensor"], a["unit"]))
            lines.append(
                f"  {icon} [{a['zone_name']}] {display[0]}: {a['value']} {display[1]} "
                f"(阈值: {a['threshold']}) - {a['status']}"
            )
        return "\n".join(lines)

    yield FunctionInfo.from_fn(_read_sensors, description="读取指定地块的全部传感器当前值（土壤湿度、温度、湿度、光照、pH、风速、降雨）。")
    yield FunctionInfo.from_fn(_read_sensor, description="读取指定地块的单个传感器值。格式: 'zone_id | sensor_type'。")
    yield FunctionInfo.from_fn(_read_sensor_history, description="查询指定地块传感器历史数据。格式: 'zone_id | sensor_type | hours'。")
    yield FunctionInfo.from_fn(_list_zones, description="列出所有已配置的农场地块及其基本信息。")
    yield FunctionInfo.from_fn(_check_alerts, description="检查所有地块的传感器告警（超出阈值的指标）。")

"""构建农业模式的上下文：地块摘要 + 传感器告警 + 待确认操作。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from plant_care_agent.sensors.hub import SensorHub

logger = logging.getLogger(__name__)

SENSOR_NAMES = {
    "soil_moisture": "土壤湿度",
    "air_temperature": "空气温度",
    "air_humidity": "空气湿度",
    "light_intensity": "光照强度",
    "soil_ph": "土壤pH",
    "wind_speed": "风速",
    "rainfall": "降雨量",
}

STATUS_ICON = {"normal": "🟢", "warning": "🟡", "critical": "🔴"}

OP_NAMES = {
    "irrigate": "💧灌溉",
    "fertilize": "🧪施肥",
    "pest_control": "🐛除虫",
    "climate_control": "🌀通风遮阳",
    "harvest": "🌾收割",
}


def build_farm_context(farm_dir: str | Path) -> str:
    """构建注入到 system 消息的农场上下文。"""
    farm_dir = Path(farm_dir)
    sections: list[str] = []

    sections.append("# 🌾 农场实时状态\n")

    try:
        hub = SensorHub(farm_dir)
    except Exception as e:
        logger.warning("Failed to initialize SensorHub: %s", e)
        sections.append("⚠️ 传感器系统初始化失败，请检查 farm_config.yaml。")
        return "\n".join(sections)

    for zid in hub.zone_ids:
        zc = hub.get_zone(zid)
        if zc is None:
            continue
        sections.append(f"## 📍 {zc.name} ({zid})")
        sections.append(f"作物: {zc.crop} | 面积: {zc.area_mu}亩 | 土壤: {zc.soil_type}")

        latest = hub._store.get_latest(zid)
        if latest:
            parts: list[str] = []
            for st, val in latest.items():
                name = SENSOR_NAMES.get(st, st)
                parts.append(f"{name}={val:.1f}")
            sections.append(f"最近读数: {' | '.join(parts)}")
        sections.append("")

    alerts = hub.check_alerts()
    if alerts:
        sections.append("## ⚠️ 活跃告警")
        for a in alerts:
            sensor_name = SENSOR_NAMES.get(a["sensor"], a["sensor"])
            icon = STATUS_ICON.get(a["status"], "⚪")
            sections.append(f"- {icon} [{a['zone_name']}] {sensor_name}: {a['value']} (阈值: {a['threshold']})")
        sections.append("")

    pending_path = farm_dir / "pending_operations.json"
    if pending_path.exists():
        try:
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            if pending:
                sections.append("## 📋 待确认操作")
                for op in pending:
                    op_name = OP_NAMES.get(op.get("operation_type", ""), op.get("operation_type", ""))
                    sections.append(
                        f"- [{op['operation_id']}] {op_name} @ {op.get('zone_name', '-')} — {op.get('reason', '')}"
                    )
                sections.append("")
        except (json.JSONDecodeError, ValueError):
            pass

    return "\n".join(sections)

"""proactive_last_snapshot.json — 用于判断植物日志/天气警戒是否变化。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def snapshot_path(garden_dir: Path) -> Path:
    return garden_dir / "proactive_last_snapshot.json"


def load_snapshot(garden_dir: Path) -> dict[str, Any]:
    p = snapshot_path(garden_dir)
    if not p.is_file():
        return {
            "plant_fingerprints": {},
            "weather_alert_fp": "",
            "last_push_epoch": 0,
        }
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "plant_fingerprints": {},
            "weather_alert_fp": "",
            "last_push_epoch": 0,
        }


def save_snapshot(garden_dir: Path, data: dict[str, Any]) -> None:
    garden_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path(garden_dir).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def should_push(
    *,
    only_on_change: bool,
    min_interval_minutes: int,
    plant_fps: dict[str, str],
    weather_alert_fp: str,
    snap: dict[str, Any],
) -> tuple[bool, str]:
    """返回 (是否推送, 原因说明)。"""
    now = int(time.time())
    last = int(snap.get("last_push_epoch") or 0)
    interval_sec = max(0, min_interval_minutes) * 60
    if interval_sec and now - last < interval_sec:
        return False, f"距上次推送不足 {min_interval_minutes} 分钟"

    old_plants = snap.get("plant_fingerprints") or {}
    old_w = snap.get("weather_alert_fp") or ""

    plant_changed = plant_fps != old_plants
    weather_changed = weather_alert_fp != old_w

    if not only_on_change:
        return True, "only_on_change=false，总是推送"

    if plant_changed:
        return True, "植物日志有更新或指纹变化"
    if weather_changed:
        return True, "天气警戒状态变化"
    return False, "无新动态（植物与天气警戒均未变）"

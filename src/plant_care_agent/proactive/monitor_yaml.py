"""读写 data/garden/proactive_monitor.yaml（定时巡检 + 推送配置）。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MONITOR: dict[str, Any] = {
    "enabled": False,
    "location": "上海",
    "latitude": None,
    "longitude": None,
    "plant_ids": [],
    "cron_hint": "0 8,20 * * *",
    "push": {
        "mode": "none",
        "only_on_change": True,
        "min_interval_minutes": 60,
        "ntfy": {"server": "https://ntfy.sh", "topic": "", "priority": "default"},
        "webhook": {"url": "", "headers": {}},
    },
}


def monitor_config_path(garden_dir: Path) -> Path:
    return garden_dir / "proactive_monitor.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_monitor_config(garden_dir: Path) -> dict[str, Any]:
    path = monitor_config_path(garden_dir)
    base = yaml.safe_load(yaml.dump(DEFAULT_MONITOR)) or dict(DEFAULT_MONITOR)
    if not path.is_file():
        return base
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _deep_merge(base, data)


def save_monitor_config(garden_dir: Path, data: dict[str, Any]) -> None:
    garden_dir.mkdir(parents=True, exist_ok=True)
    path = monitor_config_path(garden_dir)
    path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")


def default_garden_dir() -> Path:
    return Path(os.environ.get("PLANT_CARE_GARDEN", "data/garden")).resolve()


def ensure_template(garden_dir: Path, location: str | None = None) -> dict[str, Any]:
    cfg = load_monitor_config(garden_dir)
    if location:
        cfg["location"] = location
    elif os.environ.get("PLANT_CARE_LOCATION"):
        cfg["location"] = os.environ["PLANT_CARE_LOCATION"].strip()
    save_monitor_config(garden_dir, cfg)
    return cfg


def set_enabled(garden_dir: Path, on: bool) -> dict[str, Any]:
    cfg = load_monitor_config(garden_dir)
    cfg["enabled"] = on
    save_monitor_config(garden_dir, cfg)
    return cfg


def set_ntfy(garden_dir: Path, topic: str, server: str | None = None) -> dict[str, Any]:
    cfg = load_monitor_config(garden_dir)
    push = cfg.setdefault("push", {})
    push["mode"] = "ntfy"
    ntfy = push.setdefault("ntfy", {})
    ntfy["topic"] = topic.strip()
    if server:
        ntfy["server"] = server.rstrip("/")
    save_monitor_config(garden_dir, cfg)
    return cfg


def set_webhook(garden_dir: Path, url: str) -> dict[str, Any]:
    cfg = load_monitor_config(garden_dir)
    push = cfg.setdefault("push", {})
    push["mode"] = "webhook"
    push.setdefault("webhook", {})["url"] = url.strip()
    save_monitor_config(garden_dir, cfg)
    return cfg


def status_text(garden_dir: Path, digest_path: Path, snapshot_path: Path) -> str:
    cfg = load_monitor_config(garden_dir)
    push = cfg.get("push") or {}
    lines = [
        f"enabled: {cfg.get('enabled')}",
        f"location: {cfg.get('location')}",
        f"push.mode: {push.get('mode', 'none')}",
        f"only_on_change: {push.get('only_on_change', True)}",
        f"min_interval_minutes: {push.get('min_interval_minutes', 60)}",
    ]
    if push.get("mode") == "ntfy":
        lines.append(f"ntfy.topic: {push.get('ntfy', {}).get('topic', '')}")
    if push.get("mode") == "webhook":
        lines.append(f"webhook.url: {push.get('webhook', {}).get('url', '')}")
    lines.append(f"digest: {digest_path}")
    lines.append(f"snapshot: {snapshot_path} (exists={snapshot_path.is_file()})")
    lines.append(f"config: {monitor_config_path(garden_dir)}")
    return "\n".join(lines)

#!/usr/bin/env python3
"""Cron 定时巡检：天气 + 多植物日志 → PROACTIVE_DIGEST.md，并按配置推送 ntfy/webhook。

用法:
  cd 项目根
  python scripts/proactive_digest.py
  python scripts/proactive_digest.py --garden data/garden

需已配置 data/garden/proactive_monitor.yaml 且 enabled: true。
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from plant_care_agent.proactive.garden_io import list_plants
from plant_care_agent.proactive.garden_io import slug_anchor
from plant_care_agent.proactive.monitor_yaml import default_garden_dir
from plant_care_agent.proactive.monitor_yaml import load_monitor_config
from plant_care_agent.proactive.monitor_yaml import monitor_config_path
from plant_care_agent.proactive.push import push_digest
from plant_care_agent.proactive.snapshot import load_snapshot
from plant_care_agent.proactive.snapshot import save_snapshot
from plant_care_agent.proactive.snapshot import should_push
from plant_care_agent.proactive.weather_sync import fetch_forecast_dict
from plant_care_agent.proactive.weather_sync import format_weather_text
from plant_care_agent.proactive.weather_sync import resolve_lat_lon
from plant_care_agent.proactive.weather_sync import weather_alert_fingerprint

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DIGEST_NAME = "PROACTIVE_DIGEST.md"


def build_digest_markdown(
    *,
    garden_dir: Path,
    location_label: str,
    weather_block: str,
    rows: list,
    old_plant_fps: dict[str, str],
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = [
        f"# 花园主动巡检简报",
        f"",
        f"_生成时间: {now}_",
        f"",
        f"## 天气",
        f"",
        "```text",
        weather_block,
        "```",
        f"",
        f"## 植物目录",
        f"",
    ]
    for r in rows:
        aid = slug_anchor(r.plant_id)
        lines.append(f"- [{r.display_name}](#{aid}) `plant_id={r.plant_id}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    for r in rows:
        aid = slug_anchor(r.plant_id)
        old_fp = old_plant_fps.get(r.plant_id)
        changed = old_fp is not None and old_fp != r.fingerprint
        new_note = "（自上次巡检以来：**有**新日志）" if changed else "（无新日志或首次记录）"
        if old_fp is None:
            new_note = "（首次巡检基准）"
        lines.append(f'<a id="{aid}"></a>')
        lines.append(f"## {r.display_name}")
        lines.append("")
        lines.append(f"**plant_id:** `{r.plant_id}`  ")
        if r.species:
            lines.append(f"**品种:** {r.species}  ")
        if r.stage:
            lines.append(f"**阶段:** {r.stage}  ")
        lines.append("")
        lines.append(f"**动态:** {new_note}")
        lines.append("")
        lines.append("### 最近记录")
        lines.append(r.recent_block)
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_push_body(
    rows: list,
    old_plant_fps: dict[str, str],
    weather_block: str,
    digest_path: Path,
    max_len: int = 3500,
) -> tuple[str, str, list[dict[str, str]]]:
    title = f"花园巡检 {datetime.now().strftime('%m-%d %H:%M')}"
    parts: list[str] = [weather_block[:800], ""]
    plants_payload: list[dict[str, str]] = []
    for r in rows:
        old_fp = old_plant_fps.get(r.plant_id)
        changed = old_fp is None or old_fp != r.fingerprint
        flag = "新" if changed else "—"
        line = f"[{r.plant_id}] {r.display_name} ({flag})"
        if r.events:
            last = r.events[-1]
            line += f" 最近:{last['date']} [{last['type']}] {last['desc'][:40]}"
        parts.append(line)
        plants_payload.append(
            {
                "plant_id": r.plant_id,
                "display_name": r.display_name,
                "changed": str(changed),
            }
        )
    parts.append("")
    parts.append(f"详情: {digest_path}")
    body = "\n".join(parts)
    if len(body) > max_len:
        body = body[: max_len - 20] + "\n…(截断)"
    return title, body, plants_payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--garden", type=str, default="", help="花园目录，默认 data/garden 或 PLANT_CARE_GARDEN")
    ap.add_argument("--dry-run", action="store_true", help="只打印是否推送，不写文件")
    args = ap.parse_args()

    garden_dir = Path(args.garden).resolve() if args.garden else default_garden_dir()
    cfg = load_monitor_config(garden_dir)

    if not cfg.get("enabled"):
        logger.info("proactive_monitor.enabled=false，跳过（配置文件 %s）", monitor_config_path(garden_dir))
        return 0

    lat = cfg.get("latitude")
    lon = cfg.get("longitude")
    loc = (cfg.get("location") or "上海").strip()
    if lat is None or lon is None:
        lat, lon = resolve_lat_lon(loc, 31.23, 121.47)
    else:
        lat, lon = float(lat), float(lon)

    try:
        wx = fetch_forecast_dict(lat, lon)
    except Exception as e:
        logger.exception("天气拉取失败: %s", e)
        return 1

    wx_text = format_weather_text(wx, loc)
    wx_fp = weather_alert_fingerprint(wx)

    plant_ids = cfg.get("plant_ids") or []
    if plant_ids and not isinstance(plant_ids, list):
        plant_ids = []
    rows = list_plants(garden_dir, [str(x) for x in plant_ids] if plant_ids else None)
    plant_fps = {r.plant_id: r.fingerprint for r in rows}

    snap = load_snapshot(garden_dir)
    push_cfg = cfg.get("push") or {}
    only_on = push_cfg.get("only_on_change", True)
    interval = int(push_cfg.get("min_interval_minutes") or 60)

    do_push, reason = should_push(
        only_on_change=bool(only_on),
        min_interval_minutes=interval,
        plant_fps=plant_fps,
        weather_alert_fp=wx_fp,
        snap=snap,
    )
    logger.info("推送判定: %s (%s)", do_push, reason)

    old_plant_fps = dict(snap.get("plant_fingerprints") or {})
    md = build_digest_markdown(
        garden_dir=garden_dir,
        location_label=loc,
        weather_block=wx_text,
        rows=rows,
        old_plant_fps=old_plant_fps,
    )
    digest_path = garden_dir / DIGEST_NAME

    if args.dry_run:
        print(md[:2000])
        print("--- dry-run, no write ---")
        return 0

    garden_dir.mkdir(parents=True, exist_ok=True)
    digest_path.write_text(md, encoding="utf-8")
    logger.info("已写入 %s", digest_path)

    pushed = False
    if do_push and (push_cfg.get("mode") or "none").lower() != "none":
        title, body, plants_payload = build_push_body(rows, old_plant_fps, wx_text, digest_path)
        ok, msg = push_digest(push_cfg, title, body, plants_payload)
        logger.info("推送结果: %s %s", ok, msg)
        pushed = ok

    new_snap = {
        "plant_fingerprints": plant_fps,
        "weather_alert_fp": wx_fp,
        "last_push_epoch": snap.get("last_push_epoch", 0),
    }
    if pushed:
        import time

        new_snap["last_push_epoch"] = int(time.time())
    save_snapshot(garden_dir, new_snap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

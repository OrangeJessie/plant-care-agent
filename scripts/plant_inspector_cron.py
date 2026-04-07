#!/usr/bin/env python3
"""Cron 定时巡检：对所有活跃植物项目执行子 Agent 巡检。

- 遍历 projects.json 中的活跃植物
- 执行 4 项检查（天气/养护/生长/病虫害）
- 写入各植物 _inspection.md + 汇总 INSPECTION_DIGEST.md
- 有告警时推送 ntfy/webhook（复用 proactive/push.py）

用法:
  cd 项目根
  python scripts/plant_inspector_cron.py
  python scripts/plant_inspector_cron.py --garden data/garden --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from plant_care_agent.inspector.project_manager import PlantProjectManager
from plant_care_agent.inspector.inspector import PlantInspector
from plant_care_agent.inspector.report import aggregate_reports, generate_report

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DIGEST_NAME = "INSPECTION_DIGEST.md"


def _default_garden_dir() -> Path:
    import os
    env = os.environ.get("PLANT_CARE_GARDEN")
    if env:
        return Path(env).resolve()
    return ROOT / "data" / "garden"


async def run_inspections(garden_dir: Path, lat: float, lon: float, dry_run: bool) -> int:
    mgr = PlantProjectManager(garden_dir)
    inspector = PlantInspector(garden_dir, lat, lon)

    projects = mgr.list_projects(active_only=True)
    if not projects:
        logger.info("无活跃植物项目，跳过巡检。")
        return 0

    logger.info("开始巡检 %d 棵植物...", len(projects))

    wx_data = await inspector._fetch_weather()
    results = []

    for proj in projects:
        logger.info("  巡检: %s", proj.name)
        result = await inspector.inspect(proj, weather_data=wx_data)
        results.append(result)
        if not dry_run:
            report_path = generate_report(result, garden_dir)
            mgr.mark_inspected(proj.name)
            logger.info("    状态: %s → %s", result.status_label, report_path)
        else:
            logger.info("    状态: %s (dry-run)", result.status_label)

    digest_text = aggregate_reports(results)

    if dry_run:
        print("\n" + digest_text[:3000])
        print("\n--- dry-run, no write ---")
        return 0

    digest_path = garden_dir / DIGEST_NAME
    garden_dir.mkdir(parents=True, exist_ok=True)
    digest_path.write_text(digest_text, encoding="utf-8")
    logger.info("巡检汇总已写入: %s", digest_path)

    critical_plants = [r for r in results if r.overall_status == "critical"]
    warning_plants = [r for r in results if r.overall_status == "warning"]

    if critical_plants or warning_plants:
        _try_push(garden_dir, results, critical_plants, warning_plants)

    return 0


def _try_push(
    garden_dir: Path,
    results: list,
    critical_plants: list,
    warning_plants: list,
) -> None:
    """尝试通过 proactive 推送通知。"""
    try:
        from plant_care_agent.proactive.monitor_yaml import load_monitor_config
        from plant_care_agent.proactive.push import push_digest

        cfg = load_monitor_config(garden_dir)
        push_cfg = cfg.get("push") or {}
        mode = (push_cfg.get("mode") or "none").lower()
        if mode == "none":
            return

        title = f"植物巡检告警 {datetime.now().strftime('%m-%d %H:%M')}"
        body_parts = []
        for r in critical_plants:
            body_parts.append(f"🔴 {r.plant_name}: {'; '.join(r.all_actions[:2])}")
        for r in warning_plants:
            body_parts.append(f"🟡 {r.plant_name}: {'; '.join(r.all_actions[:2])}")
        body = "\n".join(body_parts[:10])

        ok, msg = push_digest(push_cfg, title, body, [])
        logger.info("推送结果: %s %s", ok, msg)
    except Exception as exc:
        logger.warning("推送失败（非致命）: %s", exc)


def main() -> int:
    ap = argparse.ArgumentParser(description="植物子 Agent 定时巡检脚本")
    ap.add_argument("--garden", type=str, default="", help="花园目录")
    ap.add_argument("--lat", type=float, default=31.23, help="默认纬度")
    ap.add_argument("--lon", type=float, default=121.47, help="默认经度")
    ap.add_argument("--dry-run", action="store_true", help="只打印结果，不写文件")
    args = ap.parse_args()

    garden_dir = Path(args.garden).resolve() if args.garden else _default_garden_dir()
    return asyncio.run(run_inspections(garden_dir, args.lat, args.lon, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())

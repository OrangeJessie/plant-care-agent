"""巡检报告生成与聚合。

- generate_report: 单株植物巡检 → Markdown 文件
- aggregate_reports: 多株巡检结果 → 注入 Agent 上下文的摘要文本
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from plant_care_agent.garden_paths import ensure_plant_dir, inspection_path
from plant_care_agent.inspector.inspector import PlantInspectionResult

STATUS_ICON = {"ok": "🟢", "warning": "🟡", "critical": "🔴"}
STATUS_LABEL = {"ok": "正常", "warning": "需关注", "critical": "紧急"}


def generate_report(result: PlantInspectionResult, garden_dir: str | Path) -> Path:
    """将单株巡检结果写入 Markdown 文件，返回文件路径。"""
    garden_dir = Path(garden_dir)
    ensure_plant_dir(garden_dir, result.plant_name)
    out_path = inspection_path(garden_dir, result.plant_name)

    overall = STATUS_ICON.get(result.overall_status, "⚪")
    lines = [
        f"# {overall} {result.plant_name} — 巡检报告",
        "",
        f"巡检时间: {result.inspected_at}",
        f"整体状态: {result.status_label}",
        "",
        "---",
        "",
    ]

    for item in result.items:
        icon = STATUS_ICON.get(item.status, "⚪")
        lines.append(f"## {icon} {item.check_name}")
        lines.append("")
        lines.append(item.summary)
        if item.actions:
            lines.append("")
            lines.append("**待办:**")
            for a in item.actions:
                lines.append(f"- {a}")
        lines.append("")

    if result.all_actions:
        lines.append("---")
        lines.append("")
        lines.append("## 汇总待办")
        lines.append("")
        for a in result.all_actions:
            lines.append(f"- [ ] {a}")
        lines.append("")

    lines.append(f"_报告由植物子 Agent 自动生成 — {datetime.now().strftime('%Y-%m-%d %H:%M')}_")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def aggregate_reports(results: list[PlantInspectionResult]) -> str:
    """将多株巡检结果聚合为注入 system message 的文本。"""
    if not results:
        return ""

    lines = ["## 🌱 子 Agent 巡检汇总\n"]

    critical_count = sum(1 for r in results if r.overall_status == "critical")
    warning_count = sum(1 for r in results if r.overall_status == "warning")
    ok_count = sum(1 for r in results if r.overall_status == "ok")

    lines.append(
        f"共 {len(results)} 棵植物: "
        f"{'🔴 ' + str(critical_count) + ' 紧急 ' if critical_count else ''}"
        f"{'🟡 ' + str(warning_count) + ' 需关注 ' if warning_count else ''}"
        f"{'🟢 ' + str(ok_count) + ' 正常' if ok_count else ''}"
    )
    lines.append("")

    priority_order = {"critical": 0, "warning": 1, "ok": 2}
    sorted_results = sorted(results, key=lambda r: priority_order.get(r.overall_status, 9))

    for r in sorted_results:
        icon = STATUS_ICON.get(r.overall_status, "⚪")
        lines.append(f"### {icon} {r.plant_name}（{r.status_label}）")
        for item in r.items:
            item_icon = STATUS_ICON.get(item.status, "⚪")
            lines.append(f"- {item_icon} {item.check_name}: {item.summary.split(chr(10))[0]}")
        if r.all_actions:
            lines.append(f"- **建议操作**: {'; '.join(r.all_actions[:3])}")
            if len(r.all_actions) > 3:
                lines.append(f"  _...另有 {len(r.all_actions) - 3} 条建议_")
        lines.append("")

    lines.append(f"_巡检时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}_")
    return "\n".join(lines)

"""从 data/garden/ 下的 Markdown 植物日志构造给 LLM 的「种植记忆」上下文。

目录结构:
  data/garden/
    GARDEN.md          索引文件（自动维护）
    我的番茄.md         每株植物一个文件
    阳台薄荷.md         ...

每个植物文件格式:
  ---                  YAML frontmatter
  name: 我的番茄
  species: tomato
  planted: 2026-04-01
  location: 阳台
  stage: 苗期
  events: 5
  ---
  # 我的番茄
  ## 日志
  ### 2026-04-01
  - **[播种]** 在阳台花盆中播下了5粒番茄种子
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
EVENT_LINE_RE = re.compile(r"^- \*\*\[(.+?)]\*\*\s+(.+)$", re.MULTILINE)
DATE_HEADING_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2})", re.MULTILINE)


def parse_frontmatter(text: str) -> dict[str, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    result: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            result[k.strip()] = v.strip()
    return result


def strip_frontmatter(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1)


def list_plant_files(garden_dir: Path) -> list[Path]:
    if not garden_dir.is_dir():
        return []
    return sorted(
        p for p in garden_dir.glob("*.md")
        if p.name != "GARDEN.md"
    )


def load_plant_md(filepath: Path) -> tuple[dict[str, str], str]:
    if not filepath.exists():
        return {}, ""
    text = filepath.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    body = strip_frontmatter(text)
    return fm, body


def count_events(body: str) -> int:
    return len(EVENT_LINE_RE.findall(body))


def get_recent_events(body: str, n: int) -> str:
    """从 markdown body 中截取最后 n 条事件行（含日期标题）。"""
    lines = body.splitlines()
    event_indices: list[int] = []
    for i, line in enumerate(lines):
        if EVENT_LINE_RE.match(line):
            event_indices.append(i)

    if not event_indices:
        return ""

    keep_from = event_indices[-n] if len(event_indices) > n else event_indices[0]

    date_heading_idx = keep_from
    for j in range(keep_from - 1, -1, -1):
        if DATE_HEADING_RE.match(lines[j]):
            date_heading_idx = j
            break

    return "\n".join(lines[date_heading_idx:]).strip()


def format_plant_full(name: str, fm: dict[str, str], body: str) -> str:
    """关注植物：frontmatter 摘要 + 完整正文。"""
    total = fm.get("events") or str(count_events(body))
    header = f"### 【{name}】完整记录（当前关注植物，共 {total} 条）"
    meta_parts: list[str] = []
    for k in ("species", "planted", "location", "stage"):
        if k in fm:
            meta_parts.append(f"{k}: {fm[k]}")
    meta_line = f"> {' | '.join(meta_parts)}" if meta_parts else ""
    return f"{header}\n{meta_line}\n\n{body.strip()}" if meta_line else f"{header}\n\n{body.strip()}"


def format_plant_compressed(name: str, fm: dict[str, str], body: str, max_events: int) -> str:
    """非关注植物：frontmatter 摘要 + 最近 N 条。"""
    total = fm.get("events") or str(count_events(body))
    header = f"### 【{name}】摘要（共 {total} 条）"
    meta_parts: list[str] = []
    for k in ("species", "planted", "location", "stage"):
        if k in fm:
            meta_parts.append(f"{k}: {fm[k]}")
    meta_line = f"> {' | '.join(meta_parts)}" if meta_parts else ""

    recent = get_recent_events(body, max_events)
    total_int = int(total) if total.isdigit() else count_events(body)
    suffix = ""
    if total_int > max_events:
        suffix = f"\n\n_… 另有 {total_int - max_events} 条较早记录，可用 growth_journal 工具查看完整历史_"
    parts = [header]
    if meta_line:
        parts.append(meta_line)
    if recent:
        parts.append("")
        parts.append(recent)
    if suffix:
        parts.append(suffix)
    return "\n".join(parts)


def _match_focus(pid: str, focus: str) -> bool:
    if not focus:
        return False
    fl = focus.lower()
    pl = pid.lower()
    return pl == fl or fl in pl or pl in fl


def build_memory_context(
    garden_dir: Path,
    focus_plant_id: str | None,
    other_max_events: int,
) -> str:
    """构建种植记忆上下文文本（纯同步，从 markdown 文件读取）。"""
    files = list_plant_files(garden_dir)
    if not files:
        return "## 种植记忆\n（暂无已记录植物，用户可通过 growth_journal 记录播种与日常养护。）"

    focus = (focus_plant_id or "").strip()
    if not focus and len(files) == 1:
        fm, _ = load_plant_md(files[0])
        focus = fm.get("name") or files[0].stem

    sections: list[str] = ["## 种植记忆\n"]
    matched_focus = False

    for filepath in files:
        fm, body = load_plant_md(filepath)
        name = fm.get("name") or filepath.stem

        if _match_focus(name, focus):
            sections.append(format_plant_full(name, fm, body))
            matched_focus = True
        else:
            sections.append(format_plant_compressed(name, fm, body, other_max_events))

    if focus and not matched_focus:
        sections.insert(
            1,
            f"_（关注植物「{focus}」暂无日志文件，下方为全部植物的摘要。）_\n",
        )

    sections.append(
        "\n---\n_完整记录 = 当前关注植物；摘要 = 其余植物（详情可通过 growth_journal 查询）。_"
    )
    return "\n\n".join(sections)


def resolve_focus_plant_id_from_headers(headers) -> str | None:
    if headers is None:
        return None
    try:
        for key in ("x-focus-plant", "x-plant-id", "x-current-plant"):
            v = headers.get(key)
            if v:
                if isinstance(v, bytes):
                    return v.decode("utf-8", errors="replace").strip()
                return str(v).strip()
    except Exception:
        return None
    return None

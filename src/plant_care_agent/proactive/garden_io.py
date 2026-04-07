from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
EVENT_LINE_RE = re.compile(r"^- \*\*\[(.+?)]\*\*\s+(.+?)(?:\s+_(\d{2}:\d{2})_)?$", re.MULTILINE)
DATE_HEADING_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2})", re.MULTILINE)

RESERVED_STEMS = frozenset({"garden", "proactive_digest", "proactive_monitor"})


def _parse_frontmatter(text: str) -> dict[str, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _strip_fm(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1)


def parse_events(body: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    current_date = ""
    for line in body.splitlines():
        dm = DATE_HEADING_RE.match(line)
        if dm:
            current_date = dm.group(1)
            continue
        em = EVENT_LINE_RE.match(line)
        if em and current_date:
            events.append({
                "date": current_date,
                "type": em.group(1),
                "desc": em.group(2).strip(),
                "time": em.group(3) or "",
            })
    return events


def events_fingerprint(events: list[dict[str, str]]) -> str:
    if not events:
        return "empty"
    payload = json.dumps(events[-20:], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass
class PlantDigestRow:
    plant_id: str
    display_name: str
    stage: str
    species: str
    events: list[dict[str, str]]
    fingerprint: str
    recent_block: str


def _recent_events_block(events: list[dict[str, str]], n: int = 8) -> str:
    if not events:
        return "_（暂无事件）_"
    lines: list[str] = []
    tail = events[-n:]
    cur_d = ""
    for ev in tail:
        if ev["date"] != cur_d:
            cur_d = ev["date"]
            lines.append(f"### {cur_d}")
        t = f" {ev['time']}" if ev.get("time") else ""
        lines.append(f"- **[{ev['type']}]** {ev['desc']}{t}")
    return "\n".join(lines)


def load_plant_row(path: Path) -> PlantDigestRow | None:
    """从 journal.md 加载植物数据行。path 应指向 journal.md 文件。"""
    if not path.exists():
        return None
    plant_id = path.parent.name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm = _parse_frontmatter(text)
    body = _strip_fm(text)
    events = parse_events(body)
    fp = events_fingerprint(events)
    name = fm.get("name") or plant_id
    return PlantDigestRow(
        plant_id=plant_id,
        display_name=name,
        stage=fm.get("stage", ""),
        species=fm.get("species", ""),
        events=events,
        fingerprint=fp,
        recent_block=_recent_events_block(events),
    )


def list_plants(garden_dir: Path, plant_ids: list[str] | None) -> list[PlantDigestRow]:
    from plant_care_agent.garden_paths import list_plant_dirs

    if not garden_dir.is_dir():
        return []
    want = {p.strip() for p in plant_ids} if plant_ids else None
    rows: list[PlantDigestRow] = []
    for d in list_plant_dirs(garden_dir):
        row = load_plant_row(d / "journal.md")
        if row is None:
            continue
        if want is not None and row.plant_id not in want:
            continue
        rows.append(row)
    return rows


def slug_anchor(plant_id: str) -> str:
    safe = re.sub(r"[^\w\u4e00-\u9fff]+", "-", plant_id).strip("-") or "plant"
    return f"plant--{safe}"

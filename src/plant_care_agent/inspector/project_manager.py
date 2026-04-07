"""PlantProjectManager — 植物管理项目的 CRUD。

每个「项目」代表一棵用户正在种植的植物，持有独立的巡检配置。
存储: data/garden/projects.json
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PlantProject:
    name: str
    species: str = ""
    location: str = ""
    planted_date: str = ""
    inspect_interval_hours: float = 12.0
    last_inspected: str = ""
    active: bool = True
    inspection_enabled: bool = True
    # LLM 根据植物特性设定的养护参数
    fert_interval_days: int = 0          # 施肥间隔天数，0 = 未设置（用默认 14 天）
    fert_type: str = ""                  # 推荐肥料类型，如 "酸性肥料（硫酸亚铁）"
    fert_dormant_months: str = ""        # 免施肥月份，逗号分隔，如 "11,12,1,2"
    water_interval_days: int = 0         # 浇水间隔天数，0 = 未设置（用默认逻辑）
    pest_interval_days: int = 0          # 驱虫/预防间隔天数，0 = 未设置（用默认 30 天）

    def needs_inspection(self) -> bool:
        if not self.active or not self.inspection_enabled:
            return False
        if not self.last_inspected:
            return True
        try:
            last = datetime.fromisoformat(self.last_inspected)
            elapsed_h = (datetime.now() - last).total_seconds() / 3600
            return elapsed_h >= self.inspect_interval_hours
        except ValueError:
            return True

    def mark_inspected(self) -> None:
        self.last_inspected = datetime.now().isoformat(timespec="seconds")


@dataclass
class ProjectStore:
    projects: dict[str, PlantProject] = field(default_factory=dict)


class PlantProjectManager:
    """管理所有植物项目的生命周期。"""

    def __init__(self, garden_dir: str | Path) -> None:
        self._garden_dir = Path(garden_dir)
        self._store_path = self._garden_dir / "projects.json"
        self._store: ProjectStore | None = None

    def _load(self) -> ProjectStore:
        if self._store is not None:
            return self._store
        if not self._store_path.exists():
            self._store = ProjectStore()
            return self._store
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
            projects = {}
            for name, data in raw.get("projects", {}).items():
                projects[name] = PlantProject(**{
                    k: v for k, v in data.items()
                    if k in PlantProject.__dataclass_fields__
                })
            self._store = ProjectStore(projects=projects)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Failed to load projects.json, resetting: %s", exc)
            self._store = ProjectStore()
        return self._store

    def _save(self) -> None:
        store = self._load()
        self._garden_dir.mkdir(parents=True, exist_ok=True)
        payload = {"projects": {k: asdict(v) for k, v in store.projects.items()}}
        self._store_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def create_project(
        self,
        name: str,
        species: str = "",
        location: str = "",
        inspect_interval_hours: float = 12.0,
    ) -> PlantProject:
        store = self._load()
        if name in store.projects:
            existing = store.projects[name]
            if species:
                existing.species = species
            if location:
                existing.location = location
            existing.active = True
            self._save()
            return existing

        proj = PlantProject(
            name=name,
            species=species,
            location=location,
            planted_date=datetime.now().strftime("%Y-%m-%d"),
            inspect_interval_hours=inspect_interval_hours,
            active=True,
        )
        store.projects[name] = proj
        self._save()
        return proj

    def get_project(self, name: str) -> PlantProject | None:
        return self._load().projects.get(name)

    def list_projects(self, active_only: bool = True) -> list[PlantProject]:
        store = self._load()
        if active_only:
            return [p for p in store.projects.values() if p.active]
        return list(store.projects.values())

    def remove_project(self, name: str) -> bool:
        store = self._load()
        proj = store.projects.get(name)
        if proj is None:
            return False
        proj.active = False
        self._save()
        return True

    def mark_inspected(self, name: str) -> None:
        proj = self.get_project(name)
        if proj:
            proj.mark_inspected()
            self._save()

    def set_care_schedule(
        self,
        name: str,
        *,
        fert_interval_days: int = 0,
        fert_type: str = "",
        fert_dormant_months: str = "",
        water_interval_days: int = 0,
        pest_interval_days: int = 0,
    ) -> PlantProject | None:
        """由 LLM 调用，根据植物特性设定养护参数。"""
        proj = self.get_project(name)
        if proj is None:
            return None
        if fert_interval_days:
            proj.fert_interval_days = fert_interval_days
        if fert_type:
            proj.fert_type = fert_type
        if fert_dormant_months:
            proj.fert_dormant_months = fert_dormant_months
        if water_interval_days:
            proj.water_interval_days = water_interval_days
        if pest_interval_days:
            proj.pest_interval_days = pest_interval_days
        self._save()
        return proj

    def toggle_inspection(self, name: str, enabled: bool) -> PlantProject | None:
        proj = self.get_project(name)
        if proj is None:
            return None
        proj.inspection_enabled = enabled
        self._save()
        return proj

    def inspectable_projects(self) -> list[PlantProject]:
        """所有 active 且 inspection_enabled 的项目。"""
        return [p for p in self.list_projects(active_only=True) if p.inspection_enabled]

    def projects_needing_inspection(self) -> list[PlantProject]:
        return [p for p in self.inspectable_projects() if p.needs_inspection()]

    def reload(self) -> None:
        """Force reload from disk (for cron scripts)."""
        self._store = None

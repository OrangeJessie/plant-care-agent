"""集中路径解析——每棵植物一个文件夹。

目录结构:
  data/garden/
    GARDEN.md              # 索引（根级别）
    projects.json          # 项目管理数据（根级别）
    栀子花/
      journal.md           # 生长日志
      inspection.md        # 巡检报告
      栀子花_timeline.png   # 时间线图
      栀子花_dashboard.png  # 看板图
      栀子花_成长故事_xxx.pptx
      photo_*.jpg          # 照片等附件
    薄荷/
      journal.md
      ...
"""

from __future__ import annotations

from pathlib import Path


def safe_plant_id(plant_id: str) -> str:
    """统一植物 ID 清洗规则（去空格、斜杠转下划线）。"""
    return plant_id.strip().replace("/", "_")


def plant_dir(garden_dir: Path, plant_id: str) -> Path:
    """某棵植物的专属文件夹。"""
    return garden_dir / safe_plant_id(plant_id)


def ensure_plant_dir(garden_dir: Path, plant_id: str) -> Path:
    """创建并返回植物文件夹。"""
    d = plant_dir(garden_dir, plant_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def journal_path(garden_dir: Path, plant_id: str) -> Path:
    return plant_dir(garden_dir, plant_id) / "journal.md"


def inspection_path(garden_dir: Path, plant_id: str) -> Path:
    return plant_dir(garden_dir, plant_id) / "inspection.md"


def chart_path(garden_dir: Path, plant_id: str, chart_type: str) -> Path:
    """chart_type: 'timeline' | 'dashboard'."""
    safe = safe_plant_id(plant_id)
    return plant_dir(garden_dir, plant_id) / f"{safe}_{chart_type}.png"


def compare_chart_path(garden_dir: Path) -> Path:
    return garden_dir / "compare.png"


def slides_path(garden_dir: Path, plant_id: str, timestamp: str) -> Path:
    safe = safe_plant_id(plant_id)
    return plant_dir(garden_dir, plant_id) / f"{safe}_成长故事_{timestamp}.pptx"


def garden_slides_path(garden_dir: Path, timestamp: str) -> Path:
    return garden_dir / f"花园总览_{timestamp}.pptx"


def index_path(garden_dir: Path) -> Path:
    return garden_dir / "GARDEN.md"


def projects_path(garden_dir: Path) -> Path:
    return garden_dir / "projects.json"


def list_plant_dirs(garden_dir: Path) -> list[Path]:
    """列出所有含 journal.md 的植物子目录。"""
    if not garden_dir.is_dir():
        return []
    return sorted(
        d for d in garden_dir.iterdir()
        if d.is_dir() and (d / "journal.md").exists()
    )


def list_plant_journals(garden_dir: Path) -> list[Path]:
    """列出所有 journal.md 路径。"""
    return [d / "journal.md" for d in list_plant_dirs(garden_dir)]


def plant_id_from_dir(plant_directory: Path) -> str:
    """从植物文件夹路径提取植物 ID（即文件夹名）。"""
    return plant_directory.name

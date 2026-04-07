import json
import logging
from pathlib import Path

from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).parent.parent / "data" / "plants_db.json"


class PlantKnowledgeConfig(FunctionBaseConfig, name="plant_knowledge"):
    data_file: str = Field(
        default=str(DATA_FILE),
        description="Path to the plants knowledge base JSON file.",
    )


@register_function(config_type=PlantKnowledgeConfig)
async def plant_knowledge_function(config: PlantKnowledgeConfig, _builder: Builder):
    db_path = Path(config.data_file)
    if not db_path.is_absolute():
        db_path = DATA_FILE

    with open(db_path, encoding="utf-8") as f:
        plants_db: dict = json.load(f)

    name_index: dict[str, str] = {}
    for key, info in plants_db.items():
        name_index[key.lower()] = key
        name_index[info["name_cn"]] = key
        name_index[info["name_en"].lower()] = key

    async def _query(plant_name: str) -> str:
        """Query the knowledge base for a plant's growing information.
        Accepts Chinese or English plant names.
        Returns detailed growing conditions, care instructions, and tips.
        If the plant is not found, returns a list of available plants."""
        lookup = plant_name.strip().lower()

        matched_key = name_index.get(lookup)
        if not matched_key:
            for cn_or_key, db_key in name_index.items():
                if lookup in cn_or_key or cn_or_key in lookup:
                    matched_key = db_key
                    break

        if matched_key:
            info = plants_db[matched_key]
            temp = info["optimal_temp"]
            lines = [
                f"【{info['name_cn']}（{info['name_en']}）】",
                f"类别: {info['category']}  |  难度: {info['difficulty']}",
                f"生长周期: {info['growth_cycle_days']}天",
                f"适宜温度: {temp['min']}-{temp['max']}{temp['unit']}",
                f"耐寒性: {info['cold_tolerance']}",
                f"光照: {info['sunlight']}",
                f"浇水: {info['watering']}",
                f"土壤: {info['soil']}",
                f"施肥: {info['fertilizer']}",
                f"种植季节: {info['planting_season']}",
                f"发芽天数: {info['germination_days']}",
                f"间距: {info['spacing']}",
                f"容器种植: {'适合' if info['container_ok'] else '不适合'}，建议容器: {info['container_size']}",
                f"常见虫害: {', '.join(info['common_pests'])}",
                f"常见病害: {', '.join(info['common_diseases'])}",
                f"伴生植物: {', '.join(info['companion_plants']) or '无特别推荐'}",
                f"忌种搭配: {', '.join(info['incompatible_plants']) or '无'}",
                f"采收标志: {info['harvest_sign']}",
                f"种植技巧: {info['tips']}",
            ]
            return "\n".join(lines)

        available = [f"{v['name_cn']}({k})" for k, v in plants_db.items()]
        return (
            f"未找到植物「{plant_name}」的信息。\n"
            f"知识库中可查询的植物: {', '.join(available)}\n"
            f"如果您要查询的植物不在列表中，请告诉我植物名称，我会根据通用知识提供建议。"
        )

    yield FunctionInfo.from_fn(
        _query,
        description=(
            "查询植物品种知识库，获取种植条件、养护要求、病虫害信息等。"
            "支持中英文植物名称查询。"
        ),
    )

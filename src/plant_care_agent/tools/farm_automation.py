"""farm_automation — 农业自动化操作执行器。

关键设计：每个操作分两步
1. propose_operation: 提出操作建议，写入 pending，不执行
2. execute_operation: 用户确认后执行，更新传感器状态，记录历史
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from plant_care_agent.sensors.hub import SensorHub

logger = logging.getLogger(__name__)

OPERATION_TYPES = {
    "irrigate": {
        "name": "灌溉",
        "icon": "💧",
        "effects": {"moisture_delta": 20.0},
        "description": "对指定地块进行灌溉，提高土壤湿度。",
    },
    "fertilize": {
        "name": "施肥",
        "icon": "🧪",
        "effects": {"ph_delta": -0.3},
        "description": "对指定地块施肥，补充土壤养分（可能降低 pH）。",
    },
    "pest_control": {
        "name": "除虫",
        "icon": "🐛",
        "effects": {"moisture_delta": 5.0, "ph_delta": -0.1},
        "description": "对指定地块进行病虫害防治（喷施农药会轻微增加土壤湿度、微降 pH）。",
    },
    "climate_control": {
        "name": "通风遮阳",
        "icon": "🌀",
        "effects": {"temp_delta": -2.0, "humidity_delta": -10.0},
        "description": "调节大棚通风或遮阳，降低温度和湿度。",
    },
    "harvest": {
        "name": "收割",
        "icon": "🌾",
        "effects": {"moisture_delta": -5.0},
        "description": "对指定地块作物进行收割（收割后地表裸露，土壤湿度略降）。",
    },
}


class FarmAutomationConfig(FunctionBaseConfig, name="farm_automation"):
    farm_dir: str = Field(default="./data/farm", description="农场数据根目录。")


def _pending_path(farm_dir: Path) -> Path:
    return farm_dir / "pending_operations.json"


def _history_path(farm_dir: Path) -> Path:
    return farm_dir / "operation_history.json"


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return []


def _save_json(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@register_function(config_type=FarmAutomationConfig)
async def farm_automation_function(config: FarmAutomationConfig, _builder: Builder):
    farm_dir = Path(config.farm_dir)
    farm_dir.mkdir(parents=True, exist_ok=True)
    hub = SensorHub(config.farm_dir)

    async def _propose_operation(entry: str) -> str:
        """Propose a farm operation for user confirmation (does NOT execute).
        Input format: 'operation_type | zone_id | reason'
        Optional params: 'operation_type | zone_id | reason | param1=value1 | param2=value2'
        Operation types: irrigate, fertilize, pest_control, climate_control, harvest
        Example: 'irrigate | zone_a | 土壤湿度低于25%，需要补水'"""
        parts = [p.strip() for p in entry.split("|")]
        if len(parts) < 3:
            return (
                "格式: 'operation_type | zone_id | reason'\n"
                f"可用操作: {', '.join(OPERATION_TYPES.keys())}"
            )

        op_type, zone_id, reason = parts[0], parts[1], parts[2]

        if op_type not in OPERATION_TYPES:
            return f"未知操作类型「{op_type}」。可用: {', '.join(OPERATION_TYPES.keys())}"

        zc = hub.get_zone(zone_id)
        if zc is None:
            return f"未找到地块「{zone_id}」。可用: {', '.join(hub.zone_ids)}"

        extra_params: dict[str, float] = {}
        for p in parts[3:]:
            if "=" in p:
                k, v = p.split("=", 1)
                try:
                    extra_params[k.strip()] = float(v.strip())
                except ValueError:
                    pass

        op_info = OPERATION_TYPES[op_type]
        op_id = f"op_{uuid.uuid4().hex[:8]}"

        operation = {
            "operation_id": op_id,
            "operation_type": op_type,
            "zone_id": zone_id,
            "zone_name": zc.name,
            "reason": reason,
            "params": {**op_info["effects"], **extra_params},
            "proposed_at": datetime.now().isoformat(timespec="seconds"),
            "status": "pending",
        }

        pending = _load_json(_pending_path(farm_dir))
        pending.append(operation)
        _save_json(_pending_path(farm_dir), pending)

        return (
            f"{op_info['icon']} 操作建议已提出，等待确认\n\n"
            f"  操作ID: {op_id}\n"
            f"  类型: {op_info['name']} ({op_type})\n"
            f"  地块: {zc.name} ({zone_id})\n"
            f"  原因: {reason}\n"
            f"  预期效果: {op_info['description']}\n"
            f"  参数: {json.dumps(operation['params'], ensure_ascii=False)}\n\n"
            f"⚠️ 请用户确认后调用 execute_operation 执行（输入操作ID: {op_id}）"
        )

    async def _execute_operation(operation_id: str) -> str:
        """Execute a previously proposed operation after user confirmation.
        Input: operation_id (e.g. 'op_a1b2c3d4')
        The operation must have been proposed first via propose_operation."""
        operation_id = operation_id.strip()

        pending = _load_json(_pending_path(farm_dir))
        target = None
        remaining = []
        for op in pending:
            if op.get("operation_id") == operation_id:
                target = op
            else:
                remaining.append(op)

        if target is None:
            if not pending:
                return f"未找到操作「{operation_id}」，当前无待执行的操作。"
            ids = [op["operation_id"] for op in pending]
            return f"未找到操作「{operation_id}」。当前待执行操作: {', '.join(ids)}"

        op_type = target["operation_type"]
        zone_id = target["zone_id"]
        params = target.get("params", {})

        hub.apply_operation(zone_id, op_type, params)

        target["status"] = "executed"
        target["executed_at"] = datetime.now().isoformat(timespec="seconds")

        history = _load_json(_history_path(farm_dir))
        history.append(target)
        _save_json(_history_path(farm_dir), history)
        _save_json(_pending_path(farm_dir), remaining)

        op_info = OPERATION_TYPES.get(op_type, {"name": op_type, "icon": "⚙️"})

        return (
            f"✅ 操作已执行\n\n"
            f"  {op_info['icon']} {op_info['name']}\n"
            f"  地块: {target.get('zone_name', zone_id)}\n"
            f"  执行时间: {target['executed_at']}\n"
            f"  参数: {json.dumps(params, ensure_ascii=False)}\n\n"
            f"传感器状态已更新，可用 read_sensors 查看最新数据。"
        )

    async def _list_pending(query: str) -> str:
        """List all pending operations waiting for user confirmation.
        Input can be anything (ignored)."""
        pending = _load_json(_pending_path(farm_dir))
        if not pending:
            return "✅ 当前无待确认的操作。"

        lines = [f"📋 待确认操作列表（{len(pending)} 条）\n"]
        for op in pending:
            op_info = OPERATION_TYPES.get(op["operation_type"], {"name": op["operation_type"], "icon": "⚙️"})
            lines.append(
                f"  {op_info['icon']} [{op['operation_id']}] {op_info['name']}\n"
                f"     地块: {op.get('zone_name', op['zone_id'])} | 提出时间: {op['proposed_at']}\n"
                f"     原因: {op.get('reason', '-')}"
            )
        return "\n".join(lines)

    async def _operation_history(query: str) -> str:
        """View recent operation execution history.
        Input: number of recent records to show (default 10), or 'zone_id' to filter by zone."""
        query = query.strip()
        history = _load_json(_history_path(farm_dir))
        if not history:
            return "暂无操作执行记录。"

        if query and not query.isdigit():
            history = [h for h in history if h.get("zone_id") == query]
            if not history:
                return f"地块「{query}」暂无操作记录。"

        limit = int(query) if query.isdigit() else 10
        recent = history[-limit:]

        lines = [f"📜 操作执行历史（显示最近 {len(recent)} 条）\n"]
        for op in reversed(recent):
            op_info = OPERATION_TYPES.get(op["operation_type"], {"name": op["operation_type"], "icon": "⚙️"})
            lines.append(
                f"  {op_info['icon']} {op_info['name']} @ {op.get('zone_name', op['zone_id'])}\n"
                f"     执行时间: {op.get('executed_at', '-')} | 原因: {op.get('reason', '-')}"
            )
        return "\n".join(lines)

    yield FunctionInfo.from_fn(_propose_operation, description="提出农业操作建议（不执行），等待用户确认。格式: 'operation_type | zone_id | reason'。")
    yield FunctionInfo.from_fn(_execute_operation, description="执行已提出的操作（需用户确认后）。输入操作ID。")
    yield FunctionInfo.from_fn(_list_pending, description="列出所有待确认的操作。")
    yield FunctionInfo.from_fn(_operation_history, description="查看操作执行历史。输入数量或 zone_id 筛选。")

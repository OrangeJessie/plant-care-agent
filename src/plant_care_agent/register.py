from plant_care_agent.logging_setup import bootstrap_file_logging_from_env

bootstrap_file_logging_from_env()

# ---------------------------------------------------------------------------
# Monkey-patch: 增强 ReActOutputParser 以识别 JSON 格式的工具调用
# Qwen3 等推理模型倾向于输出 {"tool": "...", "parameters": {...}} 而非
# ReAct 的 Action: / Action Input: 格式。在原始 parse 逻辑之前拦截 JSON，
# 转换为 AgentAction，避免 "direct answer without ReAct format" 降级。
# ---------------------------------------------------------------------------
import json
import logging
import re

_patch_logger = logging.getLogger(__name__)

def _patch_react_output_parser():
    """Wrap ReActOutputParser.parse to handle JSON tool calls."""
    from nat.plugins.langchain.agent.react_agent.output_parser import ReActOutputParser
    from langchain_core.agents import AgentAction

    _original_parse = ReActOutputParser.parse

    def _patched_parse(self, text: str):
        # If text already contains ReAct Action: format, use original parser
        if re.search(r'action\s*\d*\s*:\s*\S', text, re.IGNORECASE):
            return _original_parse(self, text)

        # Try to detect JSON tool call: ```json {...}``` or bare {"tool": ...}
        json_match = re.search(
            r'```(?:json)?\s*(\{.+?\})\s*```',
            text, re.DOTALL,
        )
        if not json_match:
            json_match = re.search(
                r'(\{\s*"(?:tool|name|action)"\s*:.+?\})\s*(?:\n|$)',
                text, re.DOTALL,
            )
        if json_match:
            json_str = json_match.group(1)
            try:
                obj = json.loads(json_str)
                tool_name = (obj.get('tool') or obj.get('name')
                             or obj.get('action'))
                tool_params = (obj.get('parameters') or obj.get('params')
                               or obj.get('args') or obj.get('action_input')
                               or obj.get('input', {}))
                if tool_name:
                    tool_input_str = (json.dumps(tool_params, ensure_ascii=False)
                                      if isinstance(tool_params, dict)
                                      else str(tool_params))
                    _patch_logger.info(
                        "JSON tool call detected → tool=%s, input=%s",
                        tool_name, tool_input_str[:200])
                    return AgentAction(tool_name, tool_input_str, text)
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass  # not valid JSON, fall through

        # Default: use original ReAct parser
        return _original_parse(self, text)

    ReActOutputParser.parse = _patched_parse
    _patch_logger.info("ReActOutputParser patched to support JSON tool calls")

_patch_react_output_parser()

# --- 共享工具（个人模式 & 农业模式均可用）---
import plant_care_agent.tools.weather_forecast  # noqa: F401
import plant_care_agent.tools.plant_image_analyzer  # noqa: F401
import plant_care_agent.tools.web_search  # noqa: F401
import plant_care_agent.tools.shell_tool  # noqa: F401
import plant_care_agent.tools.skill_tools  # noqa: F401
import plant_care_agent.tools.read_project_file  # noqa: F401

# --- 个人模式专属工具 ---
import plant_care_agent.tools.plant_knowledge  # noqa: F401
import plant_care_agent.tools.care_scheduler  # noqa: F401
import plant_care_agent.tools.growth_journal  # noqa: F401
import plant_care_agent.tools.plant_chart  # noqa: F401
import plant_care_agent.tools.growth_slides  # noqa: F401
import plant_care_agent.tools.plant_project  # noqa: F401
import plant_care_agent.tools.plant_inspect_tools  # noqa: F401

# --- 农业模式专属工具 ---
import plant_care_agent.tools.sensor_monitor  # noqa: F401
import plant_care_agent.tools.farm_automation  # noqa: F401
import plant_care_agent.tools.farm_journal  # noqa: F401
import plant_care_agent.tools.farm_chart  # noqa: F401
import plant_care_agent.tools.farm_report  # noqa: F401

# --- Workflow wrappers ---
import plant_care_agent.plant_memory_wrapper  # noqa: F401
import plant_care_agent.farm_memory_wrapper  # noqa: F401

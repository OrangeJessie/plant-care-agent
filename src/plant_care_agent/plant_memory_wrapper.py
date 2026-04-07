"""在调用内层 ReAct Agent 前注入「种植记忆」上下文。

- 请求头 `X-Focus-Plant`：指定当前关注的植物（与 growth_journal 中的名称一致）。
- 该植物的**完整** markdown 日志写入 system 消息；其余植物仅保留最近 N 条摘要。
- 植物日志以 Markdown 文件形式存放于 data/garden/ 目录。
"""

# 注意：不要启用 `from __future__ import annotations`。
# NAT 会根据 workflow 的 single_fn 自动生成 stream 包装函数，并在 function_info 模块里
# 对包装函数做 get_type_hints；若注解被推迟为字符串，则无法在此模块的全局命名空间中解析
# ChatRequestOrMessage 等符号。

import logging
from pathlib import Path
from typing import cast

from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.api_server import ChatRequest
from nat.data_models.api_server import ChatRequestOrMessage
from nat.data_models.api_server import ChatResponse
from nat.data_models.api_server import Message
from nat.data_models.api_server import UserMessageContentRoleType
from nat.data_models.component_ref import FunctionRef
from nat.data_models.function import FunctionBaseConfig
from nat.utils.type_converter import GlobalTypeConverter

from plant_care_agent.chat_round_log import append_round_block
from plant_care_agent.chat_round_log import assistant_text_from_chat_response
from plant_care_agent.conversation_store import clear_transcript
from plant_care_agent.conversation_store import header_get
from plant_care_agent.conversation_store import header_truthy
from plant_care_agent.conversation_store import load_transcript
from plant_care_agent.conversation_store import merge_conversation_transcript
from plant_care_agent.conversation_store import resolve_incremental
from plant_care_agent.conversation_store import save_transcript
from plant_care_agent.conversation_store import transcript_path
from plant_care_agent.logging_setup import ensure_root_file_logging
from plant_care_agent.logging_setup import parse_log_level
from plant_care_agent.memory.context_builder import build_memory_context
from plant_care_agent.memory.context_builder import resolve_focus_plant_id_from_headers
from plant_care_agent.skills.registry import build_skills_index_text

logger = logging.getLogger(__name__)


class PlantMemoryWrapperConfig(FunctionBaseConfig, name="plant_memory_wrapper"):
    inner_agent_name: FunctionRef = Field(
        description="内层 agent 在 functions 中的实例名（例如 inner_react）。"
    )
    garden_dir: str = Field(
        default="./data/garden",
        description="Markdown 植物日志所在目录。",
    )
    other_plants_max_events: int = Field(
        default=5,
        ge=1,
        le=50,
        description="非关注植物保留的最近事件条数。",
    )
    inject_skills_index: bool = Field(
        default=True,
        description="是否在请求前注入 Skills 目录摘要（与 insightor 的 Skill 列表类似）。",
    )
    skills_index_max_chars: int = Field(
        default=4000,
        ge=500,
        le=50_000,
        description="Skills 摘要最大字符数。",
    )
    inject_proactive_digest: bool = Field(
        default=False,
        description="若存在 data/garden/PROACTIVE_DIGEST.md（cron 主动巡检生成），将其摘要注入 system。",
    )
    proactive_digest_max_chars: int = Field(
        default=3000,
        ge=500,
        le=20_000,
        description="PROACTIVE_DIGEST.md 注入正文的最大字符数。",
    )
    file_log_path: str = Field(
        default="data/logs/plant_care_memory_log.md",
        description="非空时：Markdown 日志路径。`.md` 含 Runtime（logging 引用块）与 LLM 轮次；`.log` 则为纯文本。空字符串关闭。",
    )
    file_log_level: str = Field(
        default="INFO",
        description="文件日志级别：DEBUG、INFO、WARNING 等（与标准 logging 一致）。",
    )
    conversation_memory_enabled: bool = Field(
        default=True,
        description="是否启用服务端一般对话记忆（按 X-User-ID + X-Session-ID 存 JSON，仅 user/assistant）。",
    )
    conversation_store_dir: str = Field(
        default="./data/conversations",
        description="对话记忆 JSON 目录。",
    )
    conversation_auto_incremental: bool = Field(
        default=True,
        description="未带 X-Chat-Incremental 时：若请求仅含 1 条 user 消息，则与磁盘历史拼接（适合只发本轮句子的客户端）。",
    )
    description: str = Field(
        default="注入种植记忆后调用内层对话 Agent。",
    )


@register_function(config_type=PlantMemoryWrapperConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def plant_memory_wrapper_fn(config: PlantMemoryWrapperConfig, builder: Builder):
    inner = await builder.get_function(config.inner_agent_name)
    garden_dir = Path(config.garden_dir)
    log_path_str = (config.file_log_path or "").strip()
    log_file_path = Path(log_path_str) if log_path_str else None

    async def _response_fn(
        chat_request_or_message: ChatRequestOrMessage,
    ) -> ChatResponse | str:
        from nat.builder.context import Context

        req = GlobalTypeConverter.get().convert(chat_request_or_message, to_type=ChatRequest)
        raw_client = list(req.messages)

        headers = None
        try:
            ctx = Context.get()
            if ctx.metadata and ctx.metadata.headers:
                headers = ctx.metadata.headers
        except Exception:
            pass

        headers_plain: dict[str, str] | None = None
        if headers:
            headers_plain = {str(k): str(v) for k, v in headers.items()}

        focus = resolve_focus_plant_id_from_headers(headers)

        conv_enabled = bool(config.conversation_memory_enabled)
        store_dir = Path(config.conversation_store_dir)
        user_key = header_get(headers_plain, "X-User-ID") or "anonymous"
        session_key = header_get(headers_plain, "X-Session-ID") or "default"
        conv_file = transcript_path(store_dir, user_key, session_key)
        reset_conv = header_truthy(headers_plain, "X-Conversation-Reset")
        incremental = resolve_incremental(
            raw_client,
            headers_plain,
            auto_incremental=bool(config.conversation_auto_incremental),
        )

        merged_core: list[Message] = []
        if conv_enabled:
            if reset_conv:
                clear_transcript(conv_file)
                loaded: list[Message] = []
            else:
                loaded = load_transcript(conv_file)
            merged_core = merge_conversation_transcript(
                raw_client,
                loaded,
                reset=reset_conv,
                incremental=incremental,
            )
            msgs = list(merged_core)
        else:
            msgs = list(raw_client)

        if log_file_path is not None:
            ensure_root_file_logging(log_file_path, parse_log_level(config.file_log_level))

        block = build_memory_context(
            garden_dir,
            focus,
            config.other_plants_max_events,
        )

        memory_msg = Message(
            role=UserMessageContentRoleType.SYSTEM,
            content=block,
        )
        msgs.insert(0, memory_msg)
        insert_at = 1
        if config.inject_proactive_digest:
            digest_path = garden_dir / "PROACTIVE_DIGEST.md"
            if digest_path.is_file():
                raw = digest_path.read_text(encoding="utf-8", errors="replace")
                cap = int(config.proactive_digest_max_chars)
                body = raw if len(raw) <= cap else raw[: cap - 20] + "\n…(截断)"
                digest_msg = Message(
                    role=UserMessageContentRoleType.SYSTEM,
                    content=(
                        "以下为 **主动巡检简报**（由定时任务写入 `PROACTIVE_DIGEST.md`，可能与对话不同步）：\n\n"
                        + body
                    ),
                )
                msgs.insert(insert_at, digest_msg)
                insert_at += 1
        if config.inject_skills_index:
            skills_block = build_skills_index_text(config.skills_index_max_chars)
            skills_msg = Message(
                role=UserMessageContentRoleType.SYSTEM,
                content=skills_block,
            )
            msgs.insert(insert_at, skills_msg)
        new_req = req.model_copy(update={"messages": msgs})

        response_obj: ChatResponse | str | None = None
        assistant_out = ""
        err_note: str | None = None
        response_for_log: ChatResponse | None = None
        try:
            response_obj = await inner.ainvoke(new_req)
        except Exception as e:
            err_note = f"{type(e).__name__}: {e}"
            logger.exception("Inner agent failed: %s", e)
            raise
        else:
            if chat_request_or_message.is_string:
                assistant_out = str(
                    GlobalTypeConverter.get().convert(response_obj, to_type=str),
                )
            else:
                cr = cast(ChatResponse, response_obj)
                assistant_out = assistant_text_from_chat_response(cr)
                response_for_log = cr
        finally:
            if log_file_path is not None:
                append_round_block(
                    log_file_path,
                    messages_to_llm=list(new_req.messages),
                    focus_plant=focus,
                    headers=headers_plain,
                    assistant_text=assistant_out if err_note is None else "",
                    error=err_note,
                    llm_response=response_for_log if err_note is None else None,
                )
            if conv_enabled and err_note is None:
                tail = list(merged_core)
                if assistant_out.strip():
                    tail.append(
                        Message(
                            role=UserMessageContentRoleType.ASSISTANT,
                            content=assistant_out,
                        ),
                    )
                save_transcript(conv_file, tail, user_id=user_key, session_id=session_key)

        if chat_request_or_message.is_string:
            return assistant_out
        return cast(ChatResponse, response_obj)

    yield FunctionInfo.from_fn(_response_fn, description=config.description)

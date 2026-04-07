"""农业模式的 Workflow Wrapper。

注入农场上下文（地块摘要、传感器告警、待确认操作）替代个人模式的「种植记忆」。
复用 conversation_store、logging 等基础模块。
"""

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
from plant_care_agent.conversation_store import cleanup_old_transcripts
from plant_care_agent.conversation_store import header_get
from plant_care_agent.conversation_store import header_truthy
from plant_care_agent.conversation_store import load_transcript
from plant_care_agent.conversation_store import merge_conversation_transcript
from plant_care_agent.conversation_store import resolve_incremental
from plant_care_agent.conversation_store import save_transcript
from plant_care_agent.conversation_store import transcript_path
from plant_care_agent.logging_setup import ensure_root_file_logging
from plant_care_agent.logging_setup import parse_log_level
from plant_care_agent.memory.farm_context_builder import build_farm_context
from plant_care_agent.prompts.loader import get_domain_prompt
from plant_care_agent.skills.registry import build_skills_index_text

logger = logging.getLogger(__name__)


class FarmMemoryWrapperConfig(FunctionBaseConfig, name="farm_memory_wrapper"):
    inner_agent_name: FunctionRef = Field(
        description="内层 agent 在 functions 中的实例名。"
    )
    farm_dir: str = Field(
        default="./data/farm",
        description="农场数据根目录。",
    )
    inject_skills_index: bool = Field(
        default=True,
        description="是否注入 Skills 目录摘要。",
    )
    skills_index_max_chars: int = Field(
        default=4000,
        ge=500,
        le=50_000,
    )
    file_log_path: str = Field(
        default="data/logs/farm_memory_log.md",
    )
    file_log_level: str = Field(default="INFO")
    conversation_memory_enabled: bool = Field(default=True)
    conversation_store_dir: str = Field(default="./data/conversations")
    conversation_auto_incremental: bool = Field(default=True)
    conversation_max_age_days: int = Field(
        default=30,
        ge=1,
        description="对话记忆最大保留天数，超龄文件自动清理。",
    )
    conversation_max_count: int = Field(
        default=100,
        ge=10,
        description="对话记忆最大文件数量，超量时删除最老的。",
    )
    description: str = Field(default="注入农场上下文后调用内层对话 Agent。")


@register_function(config_type=FarmMemoryWrapperConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def farm_memory_wrapper_fn(config: FarmMemoryWrapperConfig, builder: Builder):
    inner = await builder.get_function(config.inner_agent_name)
    farm_dir = Path(config.farm_dir)
    log_path_str = (config.file_log_path or "").strip()
    log_file_path = Path(log_path_str) if log_path_str else None
    _cleanup_counter = [0]  # mutable container for closure

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

        farm_block = await build_farm_context(farm_dir)

        farm_msg = Message(
            role=UserMessageContentRoleType.SYSTEM,
            content=farm_block,
        )
        msgs.insert(0, farm_msg)
        insert_at = 1

        if config.inject_skills_index:
            skills_block = build_skills_index_text(config.skills_index_max_chars)
            skills_msg = Message(
                role=UserMessageContentRoleType.SYSTEM,
                content=skills_block,
            )
            msgs.insert(insert_at, skills_msg)
            insert_at += 1

        domain_text = get_domain_prompt("farm")
        if domain_text.strip():
            domain_msg = Message(
                role=UserMessageContentRoleType.SYSTEM,
                content=domain_text,
            )
            msgs.insert(insert_at, domain_msg)

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
                    focus_plant=None,
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
                _cleanup_counter[0] += 1
                if _cleanup_counter[0] % 50 == 0:
                    cleanup_old_transcripts(
                        store_dir,
                        config.conversation_max_age_days,
                        config.conversation_max_count,
                    )

        if chat_request_or_message.is_string:
            return assistant_out
        return cast(ChatResponse, response_obj)

    yield FunctionInfo.from_fn(_response_fn, description=config.description)

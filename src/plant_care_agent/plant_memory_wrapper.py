"""在调用内层 ReAct Agent 前注入「种植记忆」+ 「子 Agent 巡检汇总」上下文。

- 请求头 `X-Focus-Plant`：指定当前关注的植物（与 growth_journal 中的名称一致）。
- 该植物的**完整** markdown 日志写入 system 消息；其余植物仅保留最近 N 条摘要。
- 植物日志以 Markdown 文件形式存放于 data/garden/ 目录。
- 若存在活跃的植物管理项目，会在请求前触发子 Agent 巡检并注入汇总报告。
"""

# 注意：不要启用 `from __future__ import annotations`。
# NAT 会根据 workflow 的 single_fn 自动生成 stream 包装函数，并在 function_info 模块里
# 对包装函数做 get_type_hints；若注解被推迟为字符串，则无法在此模块的全局命名空间中解析
# ChatRequestOrMessage 等符号。

import asyncio
import logging
import re
from datetime import datetime
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
from plant_care_agent.inspector.inspector import PlantInspector
from plant_care_agent.inspector.project_manager import PlantProjectManager
from plant_care_agent.inspector.report import aggregate_reports, generate_report
from plant_care_agent.logging_setup import ensure_root_file_logging
from plant_care_agent.logging_setup import parse_log_level
from plant_care_agent.memory.context_builder import build_memory_context
from plant_care_agent.memory.context_builder import resolve_focus_plant_id_from_headers
from plant_care_agent.prompts.loader import get_domain_prompt
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
    inject_inspection: bool = Field(
        default=True,
        description="是否在请求前触发子 Agent 巡检并注入汇总报告。",
    )
    inspection_max_chars: int = Field(
        default=4000,
        ge=500,
        le=20_000,
        description="巡检汇总注入的最大字符数。",
    )
    default_latitude: float = Field(default=31.23, description="默认纬度，用于巡检天气查询。")
    default_longitude: float = Field(default=121.47, description="默认经度。")
    background_inspection_enabled: bool = Field(
        default=True,
        description="是否启动后台定时巡检循环（Agent 服务启动后自动运行）。",
    )
    daily_digest_hour: int = Field(
        default=8,
        ge=0,
        le=23,
        description="每日汇总推送的时刻（24 小时制），默认 8 点。",
    )
    emergency_check_interval_minutes: int = Field(
        default=120,
        ge=10,
        description="紧急天气轮询间隔（分钟），默认 2 小时。仅 critical 时推送。",
    )
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
    description: str = Field(
        default="注入种植记忆后调用内层对话 Agent。",
    )


_PLANTING_RE = re.compile(
    r"(?:种了|种植了|播种了|新种了|刚种了|今天种)\s*(?:一[棵株颗盆])?(.+?)(?:[，。,\.!！?？\s]|$)"
)
_INSPECT_KEYWORDS = {"巡检", "检查一下", "怎么样了", "状态如何", "查看状态", "检查", "巡查"}

_bg_tasks: dict[str, asyncio.Task] = {}  # keyed by garden_dir to avoid multi-instance conflicts


def _seconds_until_hour(target_hour: int) -> float:
    """计算从现在到下一个 target_hour 整点还需等待的秒数。"""
    from datetime import timedelta
    now = datetime.now()
    target = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _get_push_cfg(garden_dir: Path) -> tuple[dict, str]:
    from plant_care_agent.proactive.monitor_yaml import load_monitor_config
    cfg = load_monitor_config(garden_dir)
    push_cfg = cfg.get("push") or {}
    mode = (push_cfg.get("mode") or "none").lower()
    return push_cfg, mode


async def _daily_digest_loop(
    garden_dir: Path,
    inspector: PlantInspector,
    proj_mgr: PlantProjectManager,
    digest_hour: int,
) -> None:
    """每日定时全量巡检 + 推送汇总（无论好坏都推）。"""
    from plant_care_agent.proactive.monitor_yaml import ensure_template
    from plant_care_agent.proactive.push import push_digest

    ensure_template(garden_dir)
    logger.info("每日巡检循环已启动 (每天 %02d:00 推送, garden=%s)", digest_hour, garden_dir)

    while True:
        wait = _seconds_until_hour(digest_hour)
        logger.debug("每日巡检: 距下次推送 %.0f 秒", wait)
        await asyncio.sleep(wait)

        try:
            proj_mgr.reload()
            projects = proj_mgr.inspectable_projects()
            if not projects:
                logger.info("每日巡检: 无可巡检植物，跳过。")
                continue

            logger.info("每日巡检: 开始检查 %d 棵植物...", len(projects))
            wx_data = await inspector._fetch_weather()
            results = []
            for proj in projects:
                result = await inspector.inspect(proj, weather_data=wx_data)
                proj_mgr.mark_inspected(proj.name)
                generate_report(result, garden_dir)
                results.append(result)

            digest_text = aggregate_reports(results)
            digest_path = garden_dir / "INSPECTION_DIGEST.md"
            garden_dir.mkdir(parents=True, exist_ok=True)
            digest_path.write_text(digest_text, encoding="utf-8")

            push_cfg, mode = _get_push_cfg(garden_dir)
            if mode != "none":
                now_str = datetime.now().strftime("%m-%d %H:%M")
                title = f"🌱 每日花园巡检 {now_str}"
                body_parts = []
                critical_n = sum(1 for r in results if r.overall_status == "critical")
                warning_n = sum(1 for r in results if r.overall_status == "warning")
                ok_n = sum(1 for r in results if r.overall_status == "ok")
                body_parts.append(
                    f"共 {len(results)} 棵: "
                    + (f"🔴{critical_n} " if critical_n else "")
                    + (f"🟡{warning_n} " if warning_n else "")
                    + f"🟢{ok_n}"
                )
                body_parts.append("")
                for r in results:
                    icon = {"ok": "🟢", "warning": "🟡", "critical": "🔴"}.get(r.overall_status, "⚪")
                    line = f"{icon} {r.plant_name}（{r.status_label}）"
                    if r.all_actions:
                        line += f"\n   → {r.all_actions[0]}"
                    body_parts.append(line)
                body = "\n".join(body_parts[:20])
                ok, msg = push_digest(push_cfg, title, body, [])
                logger.info("每日巡检推送: %s %s", ok, msg)
            else:
                logger.info("每日巡检完成，推送未配置 (push.mode=none)。")

        except Exception:
            logger.exception("每日巡检异常（明天重试）")

        await asyncio.sleep(60)


async def _emergency_weather_loop(
    garden_dir: Path,
    inspector: PlantInspector,
    proj_mgr: PlantProjectManager,
    interval_minutes: int,
) -> None:
    """紧急天气轮询：仅在发现 critical 天气时推送，24h 内去重。"""
    from plant_care_agent.proactive.push import push_digest

    logger.info("紧急天气轮询已启动 (每 %d 分钟, garden=%s)", interval_minutes, garden_dir)

    last_emergency_keys: set[str] = set()
    last_emergency_clear_time = datetime.now()

    while True:
        await asyncio.sleep(interval_minutes * 60)
        try:
            now = datetime.now()
            if (now - last_emergency_clear_time).total_seconds() > 86400:
                last_emergency_keys.clear()
                last_emergency_clear_time = now

            wx_data = await inspector._fetch_weather()
            if not wx_data:
                continue

            proj_mgr.reload()
            projects = proj_mgr.inspectable_projects()
            if not projects:
                continue

            sample_proj = projects[0]
            weather_item = inspector._check_weather(sample_proj, wx_data)

            if weather_item.status != "critical":
                continue

            dedup_key = weather_item.summary[:80]
            if dedup_key in last_emergency_keys:
                logger.debug("紧急天气: 已推送过相同告警，跳过去重。")
                continue

            last_emergency_keys.add(dedup_key)
            logger.warning("紧急天气告警: %s", weather_item.summary)

            push_cfg, mode = _get_push_cfg(garden_dir)
            if mode != "none":
                title = f"⚠️ 紧急天气告警 {now.strftime('%m-%d %H:%M')}"
                body_parts = [f"🔴 {weather_item.summary}", ""]
                if weather_item.actions:
                    body_parts.append("建议操作:")
                    for a in weather_item.actions[:5]:
                        body_parts.append(f"  - {a}")
                body_parts.append("")
                body_parts.append(f"影响植物: {', '.join(p.name for p in projects)}")
                body = "\n".join(body_parts)
                ok, msg = push_digest(push_cfg, title, body, [])
                logger.info("紧急天气推送: %s %s", ok, msg)

        except Exception:
            logger.exception("紧急天气轮询异常（下个周期重试）")


def _detect_user_intent(user_text: str) -> str:
    """返回 'plant' / 'inspect' / 'other'。"""
    if _PLANTING_RE.search(user_text):
        return "plant"
    for kw in _INSPECT_KEYWORDS:
        if kw in user_text:
            return "inspect"
    return "other"


def _extract_last_user_text(msgs: list) -> str:
    for m in reversed(msgs):
        content = getattr(m, "content", None) or ""
        role = getattr(m, "role", None)
        if not (role and "user" in str(role).lower()):
            continue
        if isinstance(content, list):
            # 多模态消息：提取所有 text 部分拼接
            text = " ".join(
                p.get("text", "") if isinstance(p, dict) else (getattr(p, "text", None) or "")
                for p in content
            ).strip()
            if text:
                return text
        elif str(content).strip():
            return str(content).strip()
    return ""


@register_function(config_type=PlantMemoryWrapperConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def plant_memory_wrapper_fn(config: PlantMemoryWrapperConfig, builder: Builder):
    inner = await builder.get_function(config.inner_agent_name)
    garden_dir = Path(config.garden_dir)
    log_path_str = (config.file_log_path or "").strip()
    log_file_path = Path(log_path_str) if log_path_str else None
    proj_mgr = PlantProjectManager(garden_dir)
    plant_inspector = PlantInspector(garden_dir, config.default_latitude, config.default_longitude)
    _cleanup_counter = [0]  # mutable container for closure

    garden_key = str(garden_dir.resolve())
    if config.background_inspection_enabled:
        daily_key = f"{garden_key}:daily"
        if daily_key not in _bg_tasks or _bg_tasks[daily_key].done():
            _bg_tasks[daily_key] = asyncio.create_task(
                _daily_digest_loop(
                    garden_dir=garden_dir,
                    inspector=plant_inspector,
                    proj_mgr=proj_mgr,
                    digest_hour=config.daily_digest_hour,
                ),
                name="plant-daily-digest",
            )
            logger.info("每日巡检任务已创建 (每天 %02d:00)", config.daily_digest_hour)

        emergency_key = f"{garden_key}:emergency"
        if emergency_key not in _bg_tasks or _bg_tasks[emergency_key].done():
            _bg_tasks[emergency_key] = asyncio.create_task(
                _emergency_weather_loop(
                    garden_dir=garden_dir,
                    inspector=plant_inspector,
                    proj_mgr=proj_mgr,
                    interval_minutes=config.emergency_check_interval_minutes,
                ),
                name="plant-emergency-weather",
            )
            logger.info(
                "紧急天气轮询任务已创建 (每 %d 分钟)",
                config.emergency_check_interval_minutes,
            )

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

        if config.inject_inspection:
            user_text = _extract_last_user_text(msgs)
            intent = _detect_user_intent(user_text)
            force_inspect = intent in ("plant", "inspect")

            proj_mgr.reload()
            if force_inspect:
                to_inspect = proj_mgr.list_projects(active_only=True)
            else:
                to_inspect = proj_mgr.projects_needing_inspection()

            if to_inspect:
                try:
                    wx_data = await plant_inspector._fetch_weather()
                    results = []
                    for proj in to_inspect:
                        result = await plant_inspector.inspect(proj, weather_data=wx_data)
                        proj_mgr.mark_inspected(proj.name)
                        generate_report(result, garden_dir)
                        results.append(result)
                    inspection_text = aggregate_reports(results)
                    cap = int(config.inspection_max_chars)
                    if len(inspection_text) > cap:
                        inspection_text = inspection_text[:cap - 20] + "\n…(截断)"
                    if inspection_text.strip():
                        inspection_msg = Message(
                            role=UserMessageContentRoleType.SYSTEM,
                            content=inspection_text,
                        )
                        msgs.insert(insert_at, inspection_msg)
                        insert_at += 1
                except Exception as exc:
                    logger.warning("Sub-agent inspection failed: %s", exc)

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
            insert_at += 1

        domain_text = get_domain_prompt("personal")
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

#!/usr/bin/env python3
"""类 Claude Code 的终端对话界面：多行输入（Enter 提交；Ctrl+J / Option+Enter 换行）、Markdown 渲染、快捷命令。

支持两种模式：
  --mode personal  个人植物养护模式（默认）
  --mode farm      大规模农业管理模式
  不指定时弹出交互选择菜单。

可自动启动 NAT 服务（选择模式后后台拉起），也可连接已运行的服务。

运行:
  python scripts/claude_style_chat.py                    # 交互选择模式，自动启动服务
  python scripts/claude_style_chat.py --mode personal    # 个人模式
  python scripts/claude_style_chat.py --mode farm        # 农业模式
  python scripts/claude_style_chat.py --no-server        # 不自动启动服务（连接已运行的服务）

环境变量:
  NAT_CHAT_URL     默认 http://localhost:8000/v1/chat/completions
  NAT_USER_ID      可选 X-User-ID（对话记忆分用户）
  NAT_SESSION_ID   可选 X-Session-ID（同用户下多路会话）
  NAT_FOCUS_PLANT  可选，初始 X-Focus-Plant（与 growth_journal 植物名一致，仅个人模式）
  PLANT_CARE_GARDEN  可选，花园目录（默认 data/garden，与 proactive_monitor.yaml 一致）
  PLANT_CARE_LOCATION  可选，城市名（/proactive 写配置时作为默认 location）
"""

from __future__ import annotations

import atexit
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from plant_care_agent.proactive.monitor_yaml import default_garden_dir  # noqa: E402
from plant_care_agent.proactive.monitor_yaml import ensure_template  # noqa: E402
from plant_care_agent.proactive.monitor_yaml import monitor_config_path  # noqa: E402
from plant_care_agent.proactive.monitor_yaml import set_enabled  # noqa: E402
from plant_care_agent.proactive.monitor_yaml import set_ntfy  # noqa: E402
from plant_care_agent.proactive.monitor_yaml import set_webhook  # noqa: E402
from plant_care_agent.proactive.monitor_yaml import status_text  # noqa: E402

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style as PTStyle
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.text import Text
except ImportError:
    print(
        "缺少依赖，请执行:\n"
        '  pip install rich "prompt-toolkit>=3.0"\n',
        file=sys.stderr,
    )
    sys.exit(1)


def _chat_key_bindings() -> KeyBindings:
    """Enter 提交；换行用 Ctrl+J 或 Option+Enter（Escape 后 Enter）。

    说明：prompt_toolkit 无「Shift+Enter」键名；VS Code / Windows Terminal 等下 Shift+Enter
    若由终端直接插入换行字符，会照常显示为多行。macOS Terminal 里 Shift+Enter 常与 Enter 相同，请用 Ctrl+J。
    """
    kb = KeyBindings()

    @kb.add("enter", eager=True)
    def _submit(event) -> None:
        event.current_buffer.validate_and_handle()

    @kb.add("c-j", eager=True)
    def _newline_ctrl_j(event) -> None:
        event.current_buffer.insert_text("\n")

    @kb.add("escape", "c-m", eager=True)
    def _newline_option_enter(event) -> None:
        event.current_buffer.insert_text("\n")

    return kb


_TOOL_LABELS: dict[str, str] = {
    "weather_forecast": "🌤  查询天气",
    "plant_knowledge": "📚  查询植物知识",
    "care_scheduler": "📅  生成养护计划",
    "plant_image_analyzer": "🔍  分析植物照片",
    "growth_journal": "📝  读写种植日志",
    "plant_chart": "📊  生成图表",
    "growth_slides": "🎞  生成幻灯片",
    "current_datetime": "🕐  获取当前时间",
    "web_search": "🔎  联网搜索",
    "shell_tool": "⚙️  执行命令",
    "read_project_file": "📄  读取文件",
    "skill_tools": "🧩  加载 Skill",
    "plant_project": "🌱  管理植物项目",
    "plant_inspect_tools": "🩺  获取巡检数据",
    "sensor_monitor": "📡  读取传感器",
    "farm_automation": "🤖  自动化操作",
    "farm_journal": "📝  农场日志",
    "farm_chart": "📊  农场图表",
    "farm_report": "📋  农场报告",
}


def _tool_label(action_name: str) -> str:
    """将工具名映射为用户可读的中文状态。"""
    for prefix, label in _TOOL_LABELS.items():
        if action_name.startswith(prefix):
            sub = action_name.split("__", 1)
            if len(sub) > 1:
                return f"{label} → {sub[1]}"
            return label
    return f"🔧  调用 {action_name}"


def _build_headers(
    user_id: str, session_id: str, focus_plant: str, conversation_reset: bool,
) -> dict[str, str]:
    hdrs: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if user_id:
        hdrs["X-User-ID"] = user_id
    if session_id:
        hdrs["X-Session-ID"] = session_id
    if focus_plant:
        hdrs["X-Focus-Plant"] = focus_plant
    if conversation_reset:
        hdrs["X-Conversation-Reset"] = "1"
    return hdrs


def _post_chat(
    url: str,
    messages: list[dict],
    user_id: str,
    focus_plant: str,
    timeout: float,
    *,
    session_id: str = "",
    conversation_reset: bool = False,
) -> tuple[int, str]:
    body = json.dumps({"messages": messages, "stream": False}, ensure_ascii=False).encode("utf-8")
    hdrs = _build_headers(user_id, session_id, focus_plant, conversation_reset)
    req = urllib.request.Request(url, data=body, method="POST", headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def _post_chat_stream(
    url: str,
    messages: list[dict],
    user_id: str,
    focus_plant: str,
    timeout: float,
    *,
    session_id: str = "",
    conversation_reset: bool = False,
):
    """SSE 流式请求，yield 每个 delta content 片段。"""
    body = json.dumps({"messages": messages, "stream": True}, ensure_ascii=False).encode("utf-8")
    hdrs = _build_headers(user_id, session_id, focus_plant, conversation_reset)
    hdrs["Accept"] = "text/event-stream"
    req = urllib.request.Request(url, data=body, method="POST", headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content", "")
            if content:
                yield content


def _extract_assistant_text(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text", "")))
            elif isinstance(p, str):
                parts.append(p)
        return "".join(parts)
    return str(content)


def _select_mode(console: Console) -> str:
    """交互式选择运行模式。"""
    console.print()
    console.print(Panel.fit(
        Text.from_markup(
            "[bold]请选择运行模式：[/bold]\n\n"
            "  [cyan]1[/cyan]  🌱 个人植物养护模式 (personal)\n"
            "     适合家庭种植、阳台养花\n\n"
            "  [cyan]2[/cyan]  🌾 大规模农业管理模式 (farm)\n"
            "     配备传感器网络、自动化操作\n"
        ),
        border_style="cyan",
        padding=(1, 2),
        title="[bold]Plant Care Agent[/bold]",
    ))
    while True:
        try:
            choice = input("\n请输入 1 或 2（默认 1）: ").strip()
        except (EOFError, KeyboardInterrupt):
            return "personal"
        if choice in ("", "1", "personal"):
            return "personal"
        if choice in ("2", "farm"):
            return "farm"
        console.print("[yellow]请输入 1 或 2[/yellow]")


def _parse_mode_arg() -> str | None:
    """从 sys.argv 解析 --mode 参数。"""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--mode" and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--mode="):
            return arg.split("=", 1)[1]
    return None


def _has_flag(name: str) -> bool:
    return name in sys.argv[1:]


_nat_proc: subprocess.Popen | None = None


def _start_nat_server(mode: str, console: Console) -> None:
    """后台启动 NAT 服务并等待就绪。"""
    global _nat_proc

    project_root = _ROOT
    generated_dir = project_root / "src" / "plant_care_agent" / "configs" / ".generated"

    # 先组装配置
    console.print("[dim]==> 组装配置 ...[/dim]")
    subprocess.run(
        [sys.executable, str(project_root / "scripts" / "assemble_config.py"), "--all"],
        cwd=str(project_root),
        check=True,
        capture_output=True,
    )

    if mode == "farm":
        config_file = generated_dir / "config_farm.yml"
    else:
        config_file = generated_dir / "config.yml"

    nat_port = os.environ.get("NAT_PORT", "8000")
    log_file = project_root / "data" / "logs" / "nat_server.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"[dim]==> 后台启动 NAT 服务 (port={nat_port}) ...[/dim]")
    _nat_log_fh = open(log_file, "a", encoding="utf-8")
    _nat_proc = subprocess.Popen(
        ["nat", "serve", "--config_file", str(config_file)],
        cwd=str(project_root),
        stdout=_nat_log_fh,
        stderr=_nat_log_fh,
    )

    def _cleanup_nat():
        if _nat_proc and _nat_proc.poll() is None:
            _nat_proc.terminate()
            try:
                _nat_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _nat_proc.kill()
        _nat_log_fh.close()

    atexit.register(_cleanup_nat)
    signal.signal(signal.SIGTERM, lambda *_: (_cleanup_nat(), sys.exit(0)))

    # 等待服务就绪
    base_url = f"http://localhost:{nat_port}"
    max_wait = 30
    with console.status("[bold cyan]等待服务就绪 ...[/bold cyan]", spinner="dots"):
        for i in range(max_wait):
            if _nat_proc.poll() is not None:
                console.print("[red]错误: NAT 服务启动失败[/red]")
                sys.exit(1)
            try:
                urllib.request.urlopen(f"{base_url}/v1/models", timeout=2)
                break
            except Exception:
                pass
            try:
                urllib.request.urlopen(f"{base_url}/health", timeout=2)
                break
            except Exception:
                pass
            time.sleep(1)
        else:
            console.print("[yellow]警告: 等待超时，仍尝试连接 ...[/yellow]")

    console.print("[dim]==> 服务已就绪[/dim]\n")


def main() -> None:
    console = Console(highlight=False)

    mode_arg = _parse_mode_arg()
    if mode_arg and mode_arg in ("personal", "farm"):
        mode = mode_arg
    else:
        mode = _select_mode(console)

    # 自动启动 NAT 服务（除非 --no-server）
    if not _has_flag("--no-server"):
        _start_nat_server(mode, console)

    url = os.environ.get("NAT_CHAT_URL", "http://localhost:8000/v1/chat/completions")
    user_id = os.environ.get("NAT_USER_ID", "")
    session_id = os.environ.get("NAT_SESSION_ID", "").strip()
    focus_plant = os.environ.get("NAT_FOCUS_PLANT", "").strip() if mode == "personal" else ""
    timeout = float(os.environ.get("NAT_CHAT_TIMEOUT", "600"))
    conversation_reset_next = False

    messages: list[dict[str, str]] = []

    pt_style = PTStyle.from_dict(
        {
            "prompt": "ansicyan bold",
        }
    )
    session = PromptSession(
        message=HTML("<prompt>›</prompt> "),
        style=pt_style,
        multiline=True,
        key_bindings=_chat_key_bindings(),
        history=InMemoryHistory(),
    )

    if mode == "farm":
        banner = Panel.fit(
            Text.from_markup(
                "[bold cyan]农场智管[/bold cyan]  [dim]·[/dim]  "
                "[white]Farm Management Agent[/white]\n"
                "[dim]连接 NAT OpenAI 兼容接口 · 大规模农业模式[/dim]"
            ),
            border_style="green",
            padding=(0, 2),
        )
    else:
        banner = Panel.fit(
            Text.from_markup(
                "[bold cyan]花花助手[/bold cyan]  [dim]·[/dim]  "
                "[white]Plant Care Agent[/white]\n"
                "[dim]连接 NAT OpenAI 兼容接口 · 个人养护模式[/dim]"
            ),
            border_style="cyan",
            padding=(0, 2),
        )
    console.print(banner)
    console.print(
        "[dim]多行：[bold]Enter[/bold] 提交 · [bold]Ctrl+J[/bold] 或 [bold]Option+Enter[/bold]（Mac）换行 · "
        "部分终端下 [bold]Shift+Enter[/bold] 也可换行 · /help[/dim]\n"
    )
    if mode == "personal" and focus_plant:
        console.print(f"[dim]当前关注植物（完整记忆）:[/dim] [cyan]{focus_plant}[/cyan]\n")
    if mode == "farm":
        console.print("[dim]提示：请确保 NAT 服务使用 config_farm.yml 启动[/dim]\n")

    import re as _re

    _ACTION_RE = _re.compile(r"Action:\s*(.+)")
    _FINAL_ANSWER_RE = _re.compile(r"Final Answer:\s*")

    def _stream_with_status(user_text: str, spinner_label: str = "思考中…") -> None:
        """流式请求，实时显示工具调用状态。"""
        nonlocal conversation_reset_next
        messages.append({"role": "user", "content": user_text})

        full_text = ""
        step_count = 0
        status_lines: list[str] = []

        console.print(f"  [dim]⏳ {spinner_label}[/dim]", end="")

        try:
            stream = _post_chat_stream(
                url,
                messages,
                user_id,
                focus_plant,
                timeout,
                session_id=session_id,
                conversation_reset=conversation_reset_next,
            )
            for chunk in stream:
                full_text += chunk
                m = _ACTION_RE.search(chunk)
                if not m:
                    for line in chunk.split("\n"):
                        m2 = _ACTION_RE.search(line)
                        if m2:
                            m = m2
                            break
                if m:
                    action_name = m.group(1).strip()
                    step_count += 1
                    label = _tool_label(action_name)
                    status_line = f"  [dim]  ├─ 步骤 {step_count}: {label}[/dim]"
                    status_lines.append(status_line)
                    console.print(f"\r{status_line}")
        except urllib.error.HTTPError as e:
            console.print()
            err = e.read().decode("utf-8", errors="replace")
            console.print(Panel(f"[red]HTTP {e.code}[/red]\n{err}", title="错误", border_style="red"))
            messages.pop()
            return
        except urllib.error.URLError as e:
            console.print()
            console.print(Panel(f"[red]连接失败[/red]\n{e.reason}", title="错误", border_style="red"))
            messages.pop()
            return
        except Exception as e:
            console.print()
            console.print(Panel(f"[red]{type(e).__name__}[/red]\n{e}", title="错误", border_style="red"))
            messages.pop()
            return

        if step_count > 0:
            console.print(f"  [dim]  └─ ✅ 完成（共 {step_count} 步）[/dim]")
        else:
            console.print()

        m_final = _FINAL_ANSWER_RE.search(full_text)
        if m_final:
            reply = full_text[m_final.end():].strip()
        else:
            reply = full_text.strip()

        if not reply:
            console.print(Panel("[yellow]未获取到回答内容[/yellow]", border_style="yellow"))
            messages.pop()
            return

        messages.append({"role": "assistant", "content": reply})
        conversation_reset_next = False
        console.print(Rule(style="dim"))
        console.print(Panel(Markdown(reply), title="[bold green]助手[/bold green]", border_style="green"))
        console.print()

    def _send_no_stream(user_text: str, spinner: str = "思考中…") -> None:
        """非流式回退（streaming 失败时用）。"""
        nonlocal conversation_reset_next
        messages.append({"role": "user", "content": user_text})
        with console.status(f"[bold cyan]{spinner}[/bold cyan]", spinner="dots"):
            try:
                status, raw = _post_chat(
                    url,
                    messages,
                    user_id,
                    focus_plant,
                    timeout,
                    session_id=session_id,
                    conversation_reset=conversation_reset_next,
                )
            except urllib.error.HTTPError as e:
                err = e.read().decode("utf-8", errors="replace")
                console.print(Panel(f"[red]HTTP {e.code}[/red]\n{err}", title="错误", border_style="red"))
                messages.pop()
                return
            except urllib.error.URLError as e:
                console.print(Panel(f"[red]连接失败[/red]\n{e.reason}", title="错误", border_style="red"))
                messages.pop()
                return
        if status != 200 or not raw.strip():
            console.print(Panel(f"[red]异常响应[/red]\n{raw[:1500]}", title="错误", border_style="red"))
            messages.pop()
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            console.print(Panel(f"[red]非 JSON[/red]\n{raw[:1500]}", title="错误", border_style="red"))
            messages.pop()
            return
        if "error" in data:
            console.print(Panel(str(data["error"]), title="API 错误", border_style="red"))
            messages.pop()
            return
        reply = _extract_assistant_text(data)
        messages.append({"role": "assistant", "content": reply})
        conversation_reset_next = False
        console.print(Rule(style="dim"))
        console.print(Panel(Markdown(reply), title="[bold green]助手[/bold green]", border_style="green"))
        console.print()

    def do_send(user_text: str, spinner: str = "思考中…") -> None:
        """发送消息，优先使用 streaming 模式显示工具调用状态。"""
        try:
            _stream_with_status(user_text, spinner)
        except Exception:
            _send_no_stream(user_text, spinner)

    while True:
        try:
            user_text = session.prompt().strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见。[/dim]")
            break

        if not user_text:
            continue

        if user_text.startswith("/"):
            parts = user_text.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("/q", "/quit", "/exit"):
                console.print("[dim]再见。[/dim]")
                break
            if cmd == "/clear":
                messages.clear()
                conversation_reset_next = True
                console.print(
                    "[green]已清空本地历史；下一则消息将带 X-Conversation-Reset 同步清空服务端记忆。[/green]\n"
                )
                continue
            if cmd == "/url":
                if arg:
                    url = arg
                    console.print(f"[green]已切换 URL:[/green] {url}\n")
                else:
                    console.print(f"[dim]当前 URL:[/dim] {url}\n")
                continue
            if cmd == "/focus":
                if arg:
                    focus_plant = arg
                    console.print(
                        f"[green]已设置关注植物:[/green] {focus_plant} "
                        "[dim]（该株完整日记将注入 system，其它株为摘要）[/dim]\n"
                    )
                else:
                    focus_plant = ""
                    console.print("[green]已清除关注植物[/green]（全部植物仅为摘要模式）\n")
                continue
            if cmd == "/proactive":
                garden = default_garden_dir()
                digest_path = garden / "PROACTIVE_DIGEST.md"
                snapshot_path = garden / "proactive_last_snapshot.json"
                sub = arg.split(maxsplit=1)
                sub_cmd = sub[0].lower() if sub and sub[0] else ""
                sub_arg = sub[1].strip() if len(sub) > 1 else ""

                if sub_cmd in ("on", "enable"):
                    ensure_template(garden)
                    set_enabled(garden, True)
                    console.print(
                        f"[green]已开启主动巡检[/green]（{monitor_config_path(garden)}）。\n"
                        "[dim]请配置 crontab 运行:[/dim] python scripts/proactive_digest.py\n"
                    )
                    continue
                if sub_cmd in ("off", "disable"):
                    set_enabled(garden, False)
                    console.print("[green]已关闭主动巡检[/green]（enabled=false）。\n")
                    continue
                if sub_cmd == "ntfy":
                    if not sub_arg:
                        console.print("[yellow]用法:[/yellow] /proactive ntfy <topic>\n")
                        continue
                    ensure_template(garden)
                    set_ntfy(garden, sub_arg)
                    set_enabled(garden, True)
                    console.print(
                        f"[green]已设置 ntfy topic[/green] 并开启监控。\n"
                        f"[dim]配置文件:[/dim] {monitor_config_path(garden)}\n"
                    )
                    continue
                if sub_cmd == "webhook":
                    if not sub_arg:
                        console.print("[yellow]用法:[/yellow] /proactive webhook <url>\n")
                        continue
                    ensure_template(garden)
                    set_webhook(garden, sub_arg)
                    set_enabled(garden, True)
                    console.print(
                        f"[green]已设置 webhook[/green] 并开启监控。\n"
                        f"[dim]配置文件:[/dim] {monitor_config_path(garden)}\n"
                    )
                    continue
                if sub_cmd in ("status", "st", ""):
                    ensure_template(garden)
                    console.print(
                        Panel(
                            status_text(garden, digest_path, snapshot_path),
                            title="[bold cyan]主动巡检[/bold cyan]",
                            border_style="cyan",
                        )
                    )
                    console.print()
                    continue
                console.print(
                    "[yellow]用法:[/yellow] /proactive on|off|status|ntfy <topic>|webhook <url>\n"
                )
                continue
            if cmd == "/image":
                if not arg:
                    console.print(
                        "[yellow]用法:[/yellow] /image <图片路径> [说明文字]\n"
                        "[dim]示例: /image ~/Desktop/rose.jpg 叶子发黄是什么原因？[/dim]\n"
                    )
                    continue
                try:
                    img_parts = shlex.split(arg)
                except ValueError:
                    img_parts = arg.split(maxsplit=1)
                img_path_str = img_parts[0]
                img_desc = " ".join(img_parts[1:]).strip() if len(img_parts) > 1 else "请分析这张植物照片，诊断健康状况"
                img_path = Path(img_path_str).expanduser().resolve()
                if not img_path.exists():
                    console.print(f"[red]文件不存在:[/red] {img_path}\n")
                    continue
                if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    console.print(
                        f"[red]不支持的格式:[/red] {img_path.suffix}，"
                        "请使用 JPG / PNG / WebP / GIF\n"
                    )
                    continue
                console.print(f"[dim]已附加图片:[/dim] [cyan]{img_path.name}[/cyan]\n")
                do_send(
                    f"{img_desc}\n请调用 plant_image_analyzer 工具，image_path 参数为：{img_path}",
                    "分析图片中…",
                )
                continue
            if cmd == "/mode":
                console.print(f"[dim]当前模式:[/dim] [cyan]{mode}[/cyan]\n")
                continue
            if cmd == "/help":
                help_text = (
                    "[bold]命令[/bold]\n"
                    "  /help                        帮助\n"
                    "  /mode                        查看当前运行模式\n"
                    "  /clear                       清空本地历史并下一跳重置服务端对话记忆\n"
                    "  /url URL                     切换接口地址\n"
                    "  /image <路径> [说明]          上传本地图片进行植物诊断\n"
                )
                if mode == "personal":
                    help_text += (
                        "  /focus 名                    设置 X-Focus-Plant；/focus 无参数则清除\n"
                        "  /proactive on|off|status     主动巡检：ntfy <topic> | webhook <url>\n"
                    )
                else:
                    help_text += (
                        "  [dim]农业模式下可用的工具：[/dim]\n"
                        "    read_sensors / read_sensor / read_sensor_history / check_alerts\n"
                        "    propose_operation / execute_operation / list_pending\n"
                        "    log_farm_event / query_farm_history / list_farm_zones\n"
                        "    sensor_trend / farm_dashboard / zone_comparison\n"
                        "    generate_daily_report / generate_zone_report\n"
                    )
                help_text += "  /q                           退出\n"
                console.print(help_text)
                continue
            console.print(f"[yellow]未知命令:[/yellow] {cmd}，输入 /help\n")
            continue

        do_send(user_text)


if __name__ == "__main__":
    main()

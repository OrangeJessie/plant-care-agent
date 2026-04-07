#!/usr/bin/env python3
"""类 Claude Code 的终端对话界面：多行输入（Enter 提交；Ctrl+J / Option+Enter 换行）、Markdown 渲染、快捷命令。

依赖（单独装）:
  pip install rich "prompt-toolkit>=3.0"

先启动:
  nat serve --config_file src/plant_care_agent/configs/config.yml

运行:
  python scripts/claude_style_chat.py

环境变量:
  NAT_CHAT_URL     默认 http://localhost:8000/v1/chat/completions
  NAT_USER_ID      可选 X-User-ID（对话记忆分用户）
  NAT_SESSION_ID   可选 X-Session-ID（同用户下多路会话）
  NAT_FOCUS_PLANT  可选，初始 X-Focus-Plant（与 growth_journal 植物名一致）
  PLANT_CARE_GARDEN  可选，花园目录（默认 data/garden，与 proactive_monitor.yaml 一致）
  PLANT_CARE_LOCATION  可选，城市名（/proactive 写配置时作为默认 location）
"""

from __future__ import annotations

import json
import os
import shlex
import sys
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
    req = urllib.request.Request(url, data=body, method="POST", headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


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


def main() -> None:
    url = os.environ.get("NAT_CHAT_URL", "http://localhost:8000/v1/chat/completions")
    user_id = os.environ.get("NAT_USER_ID", "")
    session_id = os.environ.get("NAT_SESSION_ID", "").strip()
    focus_plant = os.environ.get("NAT_FOCUS_PLANT", "").strip()
    timeout = float(os.environ.get("NAT_CHAT_TIMEOUT", "600"))
    conversation_reset_next = False

    console = Console(highlight=False)
    messages: list[dict[str, str]] = []

    pt_style = PTStyle.from_dict(
        {
            "prompt": "ansicyan bold",
        }
    )
    # prompt_toolkit 无 enable_history 参数；用 InMemoryHistory 提供本会话内上下箭头历史
    session = PromptSession(
        message=HTML("<prompt>›</prompt> "),
        style=pt_style,
        multiline=True,
        key_bindings=_chat_key_bindings(),
        history=InMemoryHistory(),
    )

    banner = Panel.fit(
        Text.from_markup(
            "[bold cyan]花花助手[/bold cyan]  [dim]·[/dim]  "
            "[white]Plant Care Agent[/white]\n"
            "[dim]连接 NAT OpenAI 兼容接口 · 调试模式[/dim]"
        ),
        border_style="cyan",
        padding=(0, 2),
    )
    console.print(banner)
    console.print(
        "[dim]多行：[bold]Enter[/bold] 提交 · [bold]Ctrl+J[/bold] 或 [bold]Option+Enter[/bold]（Mac）换行 · "
        "部分终端下 [bold]Shift+Enter[/bold] 也可换行 · /help[/dim]\n"
    )
    if focus_plant:
        console.print(f"[dim]当前关注植物（完整记忆）:[/dim] [cyan]{focus_plant}[/cyan]\n")

    def do_send(user_text: str, spinner: str = "思考中…") -> None:
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
                # 支持带引号的路径（含空格），如: /image "My Plants/rose.jpg" 说明
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
                do_send(f"{img_desc}\n图片路径：{img_path}", "分析图片中…")
                continue
            if cmd == "/help":
                console.print(
                    "[bold]命令[/bold]\n"
                    "  /help                        帮助\n"
                    "  /clear                       清空本地历史并下一跳重置服务端对话记忆\n"
                    "  /url URL                     切换接口地址\n"
                    "  /focus 名                    设置 X-Focus-Plant；/focus 无参数则清除\n"
                    "  /image <路径> [说明]          上传本地图片进行植物诊断\n"
                    "  /proactive on|off|status     主动巡检：ntfy <topic> | webhook <url>\n"
                    "  /q                           退出\n"
                )
                continue
            console.print(f"[yellow]未知命令:[/yellow] {cmd}，输入 /help\n")
            continue

        do_send(user_text)


if __name__ == "__main__":
    main()

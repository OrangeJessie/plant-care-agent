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
  NAT_CHAT_URL       默认 http://localhost:8000/v1/chat/completions
  NAT_USER_ID        可选 X-User-ID（对话记忆分用户）
  NAT_SESSION_ID     可选 X-Session-ID（同用户下多路会话）
  NAT_FOCUS_PLANT    可选，初始 X-Focus-Plant（与 growth_journal 植物名一致，仅个人模式）
  PLANT_CARE_GARDEN  可选，花园目录（默认 data/garden，与 proactive_monitor.yaml 一致）
  PLANT_CARE_LOCATION  可选，城市名（/proactive 写配置时作为默认 location）

图片传输环境变量（/image 命令）:
  NAT_IMAGE_MODE     传输模式：path（默认）/ base64 / multipart / url
  NAT_IMAGE_MAXPX    压缩后长边最大像素（默认 1024）
  NAT_IMAGE_QUALITY  JPEG 压缩质量（默认 75）
  NAT_IMAGE_TIMEOUT  图片分析超时秒数（默认 1800，视觉模型推理较慢）
"""

from __future__ import annotations

import atexit
import base64
import io
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from PIL import Image as _PILImage
    _PILLOW_AVAILABLE = True
except ImportError:
    _PILLOW_AVAILABLE = False

_EXT_MIME: dict[str, str] = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
}
_SUPPORTED_EXTS = frozenset(_EXT_MIME)

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


# ---------------------------------------------------------------------------
# 图片工具函数
# ---------------------------------------------------------------------------

def _compress_image_bytes(img_path: Path, max_long_edge: int, quality: int) -> tuple[bytes, str]:
    """压缩图片，返回 (压缩后字节, mime_type)。未安装 Pillow 时直接返回原始字节。"""
    suffix = img_path.suffix.lower()
    mime = _EXT_MIME.get(suffix, "image/jpeg")
    if not _PILLOW_AVAILABLE:
        return img_path.read_bytes(), mime
    with _PILImage.open(img_path) as img:
        if img.mode == "RGBA":
            pass  # 保持 PNG 透明通道
        elif img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_long_edge:
            scale = max_long_edge / max(w, h)
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), _PILImage.LANCZOS)
        buf = io.BytesIO()
        if img.mode == "RGBA":
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), "image/png"
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue(), "image/jpeg"


def _image_to_data_url(img_path: Path, max_long_edge: int, quality: int) -> tuple[str, int, int]:
    """压缩 + Base64 编码，返回 (data URL, 原始字节数, 压缩后字节数)。"""
    original = img_path.stat().st_size
    data, mime = _compress_image_bytes(img_path, max_long_edge, quality)
    return f"data:{mime};base64,{base64.b64encode(data).decode()}", original, len(data)


def _upload_multipart(server_base: str, img_path: Path,
                      max_long_edge: int, quality: int, timeout: float) -> str:
    """将图片以 multipart/form-data 上传到 NAT /static/ 端点，返回可访问的 URL。"""
    import uuid
    data, mime = _compress_image_bytes(img_path, max_long_edge, quality)
    ext = ".jpg" if "jpeg" in mime else (".png" if "png" in mime else img_path.suffix)
    rel_path = f"plant_images/{img_path.stem}_{uuid.uuid4().hex[:8]}{ext}"
    put_url = f"{server_base.rstrip('/')}/static/{rel_path}"

    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{Path(rel_path).name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        put_url, data=body, method="PUT",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()
    return put_url


def _parse_image_flags(arg: str) -> tuple[str, int, int, str]:
    """解析 --mode / --maxpx / --quality 标志，返回 (mode, maxpx, quality, 剩余参数)。"""
    mode = os.environ.get("NAT_IMAGE_MODE", "path")
    maxpx = int(os.environ.get("NAT_IMAGE_MAXPX", "1024"))
    quality = int(os.environ.get("NAT_IMAGE_QUALITY", "75"))

    def _pop(pattern: str) -> str | None:
        nonlocal arg
        m = re.search(pattern, arg)
        if m:
            arg = (arg[:m.start()] + arg[m.end():]).strip()
            return m.group(1)
        return None

    v = _pop(r"--mode\s+(\S+)");    mode    = v if v else mode
    v = _pop(r"--maxpx\s+(\d+)");   maxpx   = int(v) if v else maxpx
    v = _pop(r"--quality\s+(\d+)"); quality = int(v) if v else quality
    return mode, maxpx, quality, arg.strip()


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
    image_timeout = float(os.environ.get("NAT_IMAGE_TIMEOUT", "1800"))
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
    _ACTION_RE = _re.compile(r"^Action:\s*(.+)", _re.MULTILINE)

    def do_send(user_text: str, spinner: str = "思考中…", *, image_request: bool = False) -> None:
        """发送消息。image_request=True 时使用 image_timeout（默认 1800s），
        避免视觉模型推理时间过长导致客户端超时。
        """
        nonlocal conversation_reset_next
        req_timeout = image_timeout if image_request else timeout
        messages.append({"role": "user", "content": user_text})

        with console.status(f"[bold cyan]{spinner}[/bold cyan]", spinner="dots"):
            try:
                status, raw = _post_chat(
                    url,
                    messages,
                    user_id,
                    focus_plant,
                    req_timeout,
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

        if http_status != 200 or not raw.strip():
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

        actions = _ACTION_RE.findall(reply)
        if actions:
            console.print()
            for i, action_name in enumerate(actions, 1):
                label = _tool_label(action_name.strip())
                console.print(f"  [dim]  ├─ 步骤 {i}: {label}[/dim]")
            console.print(f"  [dim]  └─ ✅ 完成（共 {len(actions)} 步）[/dim]")

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
                        "[bold]/image 用法[/bold]\n"
                        "  /image [--mode MODE] [--maxpx N] [--quality N] <路径或URL> [说明]\n\n"
                        "[bold]传输模式（--mode）[/bold]\n"
                        "  [cyan]path[/cyan]       （默认）路径传给 Agent 工具，Agent 自行读文件\n"
                        "  [cyan]base64[/cyan]     压缩→Base64 嵌入多模态消息（局域网/小图）\n"
                        "  [cyan]multipart[/cyan]  压缩→二进制上传到 NAT /static/，消息传 URL（推荐大图）\n"
                        "  [cyan]url[/cyan]        直接传 http/https 链接，零上传\n\n"
                        "[dim]示例:\n"
                        "  /image ~/Desktop/rose.jpg 叶子发黄\n"
                        "  /image --mode base64 rose.jpg\n"
                        "  /image --mode multipart --maxpx 800 rose.jpg 请诊断\n"
                        "  /image --mode url https://example.com/plant.jpg[/dim]\n"
                    )
                    continue

                mode_img, maxpx, quality, arg_rest = _parse_image_flags(arg)

                # ── url 模式：直接传 http 链接 ──────────────────────────────
                if mode_img == "url":
                    try:
                        parts_url = shlex.split(arg_rest)
                    except ValueError:
                        parts_url = arg_rest.split(maxsplit=1)
                    if not parts_url or not parts_url[0].startswith(("http://", "https://")):
                        console.print("[red]url 模式需要提供 http/https 链接[/red]\n")
                        continue
                    img_url_val = parts_url[0]
                    img_desc = " ".join(parts_url[1:]).strip() or "请分析这张植物照片，诊断健康状况"
                    console.print(f"[dim]URL 模式:[/dim] [cyan]{img_url_val}[/cyan]\n")
                    # 告知 react agent 调用工具，URL 作为 image_path 传入
                    do_send(
                        f"{img_desc}\n请调用 plant_image_analyzer 工具，image_path 参数为：{img_url_val}",
                        "分析图片中…",
                        image_request=True,
                    )
                    continue

                # ── 本地文件模式（path / base64 / multipart）────────────────
                try:
                    img_parts = shlex.split(arg_rest)
                except ValueError:
                    img_parts = arg_rest.split(maxsplit=1)
                img_path_str = img_parts[0]
                img_desc = " ".join(img_parts[1:]).strip() or "请分析这张植物照片，诊断健康状况"
                img_path = Path(img_path_str).expanduser().resolve()
                if not img_path.exists():
                    console.print(f"[red]文件不存在:[/red] {img_path}\n")
                    continue
                if img_path.suffix.lower() not in _SUPPORTED_EXTS:
                    console.print(
                        f"[red]不支持的格式:[/red] {img_path.suffix}，请使用 JPG/PNG/WebP/GIF\n"
                    )
                    continue

                if mode_img == "path":
                    console.print(f"[dim]path 模式:[/dim] [cyan]{img_path.name}[/cyan]\n")
                    do_send(
                        f"{img_desc}\n请调用 plant_image_analyzer 工具，image_path 参数为：{img_path}",
                        "分析图片中…",
                        image_request=True,
                    )

                elif mode_img in ("base64", "b64"):
                    if not _PILLOW_AVAILABLE:
                        console.print(
                            "[yellow]Pillow 未安装，将直接 Base64 编码原图（体积较大）。"
                            "建议: pip install Pillow[/yellow]\n"
                        )
                    # base64 模式：压缩后上传到服务端 /static/，再以 URL 形式传给工具。
                    # 不直接把 data URL 作为工具参数，避免 LLM 上下文溢出。
                    from urllib.parse import urlparse as _urlparse
                    _p = _urlparse(url)
                    server_base = f"{_p.scheme}://{_p.netloc}"
                    try:
                        img_url_val = _upload_multipart(server_base, img_path, maxpx, quality, 30.0)
                        console.print(
                            f"[dim]base64→multipart 模式:[/dim] [cyan]{img_path.name}[/cyan]  "
                            f"→ [cyan]{img_url_val}[/cyan]\n"
                        )
                        do_send(
                            f"{img_desc}\n请调用 plant_image_analyzer 工具，image_path 参数为：{img_url_val}",
                            "分析图片中…",
                            image_request=True,
                        )
                    except Exception as exc:
                        # 上传失败时 fallback 到 path 模式（本地服务器场景）
                        console.print(
                            f"[yellow]上传失败（{exc}），回退到 path 模式[/yellow]\n"
                        )
                        do_send(
                            f"{img_desc}\n请调用 plant_image_analyzer 工具，image_path 参数为：{img_path}",
                            "分析图片中…",
                            image_request=True,
                        )

                elif mode_img == "multipart":
                    from urllib.parse import urlparse as _urlparse
                    _p = _urlparse(url)
                    server_base = f"{_p.scheme}://{_p.netloc}"
                    console.print(
                        f"[dim]multipart 模式:[/dim] [cyan]{img_path.name}[/cyan] "
                        f"→ {server_base}/static/plant_images/\n"
                    )
                    try:
                        img_url_val = _upload_multipart(server_base, img_path, maxpx, quality, 30.0)
                    except Exception as exc:
                        console.print(f"[red]上传失败:[/red] {exc}\n")
                        continue
                    console.print(f"[dim]已上传:[/dim] [cyan]{img_url_val}[/cyan]\n")
                    # 上传成功后告知 react agent 调用工具，URL 作为 image_path 传入
                    do_send(
                        f"{img_desc}\n请调用 plant_image_analyzer 工具，image_path 参数为：{img_url_val}",
                        "分析图片中…",
                        image_request=True,
                    )

                else:
                    console.print(
                        f"[red]未知模式:[/red] {mode_img}，可用: path / base64 / multipart / url\n"
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
                    "  /image <路径> [说明]          path 模式（默认）：路径传给 Agent 工具\n"
                    "\n"
                    "[bold]/image 传输模式[/bold]\n"
                    "  /image <路径> [说明]                        path 模式（默认）\n"
                    "  /image --mode base64 <路径> [说明]          压缩→Base64 嵌入消息\n"
                    "  /image --mode multipart <路径> [说明]       压缩→上传 NAT /static/，消息传 URL\n"
                    "  /image --mode url <链接> [说明]             直接传 http/https 链接\n"
                    "  压缩选项: --maxpx N（默认1024）  --quality N（默认75）\n"
                    "  全局默认: NAT_IMAGE_MODE / NAT_IMAGE_MAXPX / NAT_IMAGE_QUALITY\n"
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

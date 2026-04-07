"""shell_tool — 安全受限的 shell 命令执行工具。

支持 grep / find / ls / cat / wc / head / tail / file / du 等常用命令，
以及 python 一行式计算，用于辅助植物管理场景下的文件检索和数据处理。
"""

import asyncio
import logging
import shlex

from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

ALLOWED_COMMANDS = frozenset({
    "ls", "cat", "head", "tail", "wc", "grep", "rg", "find", "file",
    "du", "df", "date", "echo", "sort", "uniq", "cut", "awk", "sed",
    "tree", "stat", "md5sum", "sha256sum", "diff",
    "python3", "python",
    "pip", "which",
    "convert", "identify",  # ImageMagick
})

MAX_OUTPUT_CHARS = 8000
TIMEOUT_SECONDS = 30


class ShellToolConfig(FunctionBaseConfig, name="shell_tool"):
    working_dir: str = Field(default=".", description="命令执行的工作目录")
    timeout: int = Field(default=TIMEOUT_SECONDS, description="命令超时秒数")


@register_function(config_type=ShellToolConfig)
async def shell_tool_function(config: ShellToolConfig, _builder: Builder):

    async def _run_command(command: str) -> str:
        """Execute a shell command safely.
        Input: shell command string (e.g. 'ls -la data/garden/', 'grep 播种 data/garden/*.md').
        Supported commands: ls, cat, head, tail, wc, grep, rg, find, file,
        du, df, date, echo, sort, uniq, cut, awk, sed, tree, diff,
        python3, python, pip, which, convert, identify.
        Returns: command stdout/stderr output (truncated to 8000 chars)."""
        cmd_str = command.strip()
        if not cmd_str:
            return "请输入要执行的命令。"

        try:
            parts = shlex.split(cmd_str)
        except ValueError as e:
            return f"命令解析失败: {e}"

        if not parts:
            return "空命令。"

        base_cmd = parts[0].split("/")[-1]
        if base_cmd not in ALLOWED_COMMANDS:
            return (
                f"命令「{base_cmd}」不在允许列表中。\n"
                f"允许的命令: {', '.join(sorted(ALLOWED_COMMANDS))}"
            )

        for dangerous in ("rm -rf", "rm -r /", "mkfs", "dd if=", "> /dev", ":(){ :|:& };:"):
            if dangerous in cmd_str:
                return f"拒绝执行危险命令: {cmd_str}"

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=config.working_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=config.timeout)
        except asyncio.TimeoutError:
            return f"命令超时（{config.timeout}s）: {cmd_str}"
        except Exception as e:
            return f"执行失败: {e}"

        out = stdout.decode("utf-8", errors="replace") if stdout else ""
        err = stderr.decode("utf-8", errors="replace") if stderr else ""

        result_parts: list[str] = []
        if out:
            if len(out) > MAX_OUTPUT_CHARS:
                out = out[:MAX_OUTPUT_CHARS] + f"\n... (输出截断，共 {len(stdout)} 字节)"
            result_parts.append(out)
        if err:
            result_parts.append(f"[stderr]\n{err[:2000]}")
        if proc.returncode != 0:
            result_parts.append(f"[exit code: {proc.returncode}]")

        return "\n".join(result_parts) if result_parts else "(无输出)"

    yield FunctionInfo.from_fn(
        _run_command,
        description=(
            "执行受限的 shell 命令（grep/find/ls/cat/python 等），"
            "用于文件检索、数据处理和系统信息查询。"
        ),
    )

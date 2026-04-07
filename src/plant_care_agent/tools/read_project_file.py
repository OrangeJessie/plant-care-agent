"""read_project_file — 只读打开项目内文本文件（insightor Read 工具的简化版）。"""

import logging
from pathlib import Path

from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

TEXT_SUFFIXES = {
    ".md", ".txt", ".yml", ".yaml", ".json", ".csv", ".py", ".toml",
    ".env", ".gitignore", ".css", ".html", ".xml", ".sh",
}


class ReadProjectFileConfig(FunctionBaseConfig, name="read_project_file"):
    max_bytes: int = Field(default=200_000, ge=1024, le=2_000_000)
    roots: list[str] = Field(
        default_factory=lambda: [".", "./data/garden", "./data"],
        description="允许读取的根目录（相对 cwd），需为真实目录",
    )


def _resolve_under_roots(rel_path: str, roots: list[Path]) -> Path | None:
    raw = Path(rel_path.strip())
    if ".." in raw.parts:
        return None
    try:
        if raw.is_absolute():
            candidate = raw.resolve()
        else:
            candidate = (Path.cwd() / raw).resolve()
    except OSError:
        return None

    for root in roots:
        try:
            r = root.resolve()
            candidate.relative_to(r)
            return candidate
        except ValueError:
            continue
        except OSError:
            continue
    return None


@register_function(config_type=ReadProjectFileConfig)
async def read_project_file_function(config: ReadProjectFileConfig, _builder: Builder):
    roots = []
    for s in config.roots:
        p = Path(s)
        if not p.is_absolute():
            p = Path.cwd() / p
        if p.is_dir():
            roots.append(p)

    if not roots:
        roots = [Path.cwd()]

    async def read_project_file(relative_path: str) -> str:
        """Read a text file under allowed project roots (no .. escape).
        Input: path relative to cwd or under data/, e.g. data/garden/GARDEN.md, src/foo.md.
        Refuses binary-looking files and paths outside roots."""
        path = _resolve_under_roots(relative_path, roots)
        if path is None:
            return f"路径不在允许范围内: {relative_path}\n允许根: {', '.join(str(r) for r in roots)}"

        if not path.is_file():
            return f"不是文件或不存在: {path}"

        if path.suffix.lower() not in TEXT_SUFFIXES and path.suffix != "":
            return f"后缀 {path.suffix} 不在允许列表；请用 shell_tool 或改后缀为文本类型。"

        try:
            data = path.read_bytes()
        except OSError as e:
            return f"读取失败: {e}"

        if b"\x00" in data[:8192]:
            return "文件疑似二进制，拒绝读取。"

        if len(data) > config.max_bytes:
            return f"文件过大（{len(data)} 字节），上限 {config.max_bytes}。请指定更小范围或用 shell_tool head。"

        text = data.decode("utf-8", errors="replace")
        return f"## {path}\n\n{text}"

    yield FunctionInfo.from_fn(
        read_project_file,
        description="安全读取项目内文本/Markdown/配置（限定根目录与大小）。",
    )

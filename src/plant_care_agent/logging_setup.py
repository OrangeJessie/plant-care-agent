"""将标准 logging 镜像到文件；若路径为 `.md` 则写入 Markdown 引用块（与 LLM 轮次共用文件）。"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from plant_care_agent.md_log_file import DEFAULT_MD_HEADER
from plant_care_agent.md_log_file import append_raw

_handler_lock = threading.Lock()
_root_file_handlers: set[str] = set()


class MarkdownQuoteFileHandler(logging.Handler):
    """每条日志一行块引用，追加到 Markdown 文件（与 `append_raw` 同锁）。"""

    def __init__(self, log_path: Path):
        super().__init__()
        self.log_path = Path(log_path)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            quoted = "\n".join("> " + (ln if ln else "") for ln in msg.splitlines()) + "\n"
            append_raw(self.log_path, quoted, header=DEFAULT_MD_HEADER)
        except Exception:
            self.handleError(record)


def parse_log_level(name: str) -> int:
    return getattr(logging, name.upper(), logging.INFO)


def ensure_root_file_logging(path: Path | None, level: int = logging.INFO) -> None:
    """为 root logger 增加 FileHandler；`.md` 使用 MarkdownQuoteFileHandler。"""
    if path is None:
        return
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)

    with _handler_lock:
        if resolved in _root_file_handlers:
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        is_md = path.suffix.lower() == ".md"
        if is_md:
            append_raw(path, "", header=DEFAULT_MD_HEADER)
            fh: logging.Handler = MarkdownQuoteFileHandler(path)
        else:
            fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"),
        )
        root = logging.getLogger()
        root.addHandler(fh)
        prev = root.level if root.level != logging.NOTSET else logging.WARNING
        root.setLevel(min(prev, level))
        for name in ("plant_care_agent", "nat", "langchain", "langchain_core"):
            lg = logging.getLogger(name)
            cur = lg.level if lg.level != logging.NOTSET else prev
            lg.setLevel(min(cur, level))
        _root_file_handlers.add(resolved)


def bootstrap_file_logging_from_env() -> None:
    """若设置环境变量 PLANT_CARE_LOG_FILE，在进程启动时即开始写文件（早于首次对话）。"""
    raw = (os.environ.get("PLANT_CARE_LOG_FILE") or "").strip()
    if not raw:
        return
    level = parse_log_level(os.environ.get("PLANT_CARE_LOG_LEVEL", "INFO"))
    ensure_root_file_logging(Path(raw), level=level)

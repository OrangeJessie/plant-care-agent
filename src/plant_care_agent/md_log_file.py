"""同一 Markdown 日志文件的初始化与线程安全追加（LLM 轮次 + logging）。"""

from __future__ import annotations

import threading
from pathlib import Path

_lock = threading.Lock()

DEFAULT_MD_HEADER = """# Plant Care Agent · 记忆与日志

本文件由服务自动写入，包含：

- **Runtime**：标准 `logging`（下方引用块）
- **LLM 轮次**：每轮 `## 轮次` 小节，含提交给模型的完整 `messages` 与返回全文

---

## Runtime（logging）

"""


def append_raw(path: Path, text: str, header: str = DEFAULT_MD_HEADER) -> None:
    """若文件不存在或为空则写入文档头；否则追加 `text`（自动补换行）。"""
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        exists_nonempty = path.is_file() and path.stat().st_size > 0
        if not exists_nonempty:
            chunk = header + (text or "")
            if chunk and not chunk.endswith("\n"):
                chunk += "\n"
            path.write_text(chunk, encoding="utf-8")
        elif text:
            chunk = text if text.endswith("\n") else text + "\n"
            with path.open("a", encoding="utf-8") as f:
                f.write(chunk)

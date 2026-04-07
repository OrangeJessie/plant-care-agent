#!/usr/bin/env python3
"""将 prompts/*.md 组装进 config YAML 的 system_prompt 字段。

Prompt 统一在 src/plant_care_agent/prompts/ 目录管理，config 中只保留占位符
`__LOAD_FROM_PROMPTS__`。本脚本读取 prompt markdown → 在 configs/.generated/ 下
生成可运行的 config，原始 config 不会被修改。

使用方式:
  python scripts/assemble_config.py             # 组装个人模式
  python scripts/assemble_config.py --farm       # 组装农业模式
  python scripts/assemble_config.py --all        # 组装全部（推荐）
  python scripts/assemble_config.py --check      # 仅检查源文件是否含占位符

启动入口:
  ./scripts/start.sh           # 自动 assemble + 启动个人模式
  ./scripts/start.sh --farm    # 自动 assemble + 启动农业模式
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from plant_care_agent.prompts.loader import get_system_prompt  # noqa: E402

CONFIGS_DIR = ROOT / "src" / "plant_care_agent" / "configs"
GENERATED_DIR = CONFIGS_DIR / ".generated"

PLACEHOLDER = "__LOAD_FROM_PROMPTS__"

TARGETS = {
    "personal": {
        "source": CONFIGS_DIR / "config.yml",
        "output": GENERATED_DIR / "config.yml",
        "mode": "personal",
    },
    "farm": {
        "source": CONFIGS_DIR / "config_farm.yml",
        "output": GENERATED_DIR / "config_farm.yml",
        "mode": "farm",
    },
}


def _assemble_one(name: str, target: dict) -> bool:
    """从源 config 读取 → 替换占位符 → 写入 .generated/ 下。"""
    src_path: Path = target["source"]
    out_path: Path = target["output"]

    if not src_path.is_file():
        print(f"[assemble] 跳过: {src_path} 不存在", file=sys.stderr)
        return False

    text = src_path.read_text(encoding="utf-8")

    if PLACEHOLDER not in text:
        print(f"[assemble] 警告: {src_path.name} 没有占位符 {PLACEHOLDER}，直接复制")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        return True

    prompt = get_system_prompt(mode=target["mode"])
    indent = "      "
    prompt_yaml = indent + prompt.replace("\n", "\n" + indent)

    new_text = re.sub(
        r"(system_prompt:)\s*" + re.escape(PLACEHOLDER),
        r"\1 |\n" + prompt_yaml,
        text,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(new_text, encoding="utf-8")
    print(f"[assemble] {name}: prompts/ → .generated/{out_path.name} ✓")
    return True


def ensure_assembled() -> dict[str, Path]:
    """组装所有 config，返回 {name: output_path}。适合启动前调用。"""
    result = {}
    for name, target in TARGETS.items():
        if _assemble_one(name, target):
            result[name] = target["output"]
    return result


def main() -> None:
    args = sys.argv[1:]

    if "--check" in args:
        any_placeholder = False
        for name, target in TARGETS.items():
            src = target["source"]
            if src.is_file() and PLACEHOLDER in src.read_text(encoding="utf-8"):
                print(f"[check] {name}: 含占位符，需要 assemble ({src.name})")
                any_placeholder = True
        if not any_placeholder:
            print("[check] 所有源 config 均不含占位符。")
        sys.exit(1 if any_placeholder else 0)

    if "--all" in args:
        for name, target in TARGETS.items():
            _assemble_one(name, target)
    elif "--farm" in args:
        _assemble_one("farm", TARGETS["farm"])
    else:
        _assemble_one("personal", TARGETS["personal"])


if __name__ == "__main__":
    main()

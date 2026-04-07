#!/usr/bin/env python3
"""将 prompts/*.md 组装进 configs/config.yml 的 inner_react.system_prompt。

修改 Markdown 提示词后运行：
  python scripts/assemble_config.py

需在项目根目录执行，且已安装 PyYAML。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import yaml  # noqa: E402

from plant_care_agent.prompts.loader import get_system_prompt  # noqa: E402


def main() -> None:
    cfg_path = ROOT / "src" / "plant_care_agent" / "configs" / "config.yml"
    if not cfg_path.is_file():
        print(f"找不到配置: {cfg_path}", file=sys.stderr)
        sys.exit(1)

    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if "functions" not in data or "inner_react" not in data["functions"]:
        print("config.yml 缺少 functions.inner_react", file=sys.stderr)
        sys.exit(1)

    data["functions"]["inner_react"]["system_prompt"] = get_system_prompt()
    out = yaml.dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    )
    cfg_path.write_text(out, encoding="utf-8")
    print(f"已写入 system_prompt → {cfg_path}")


if __name__ == "__main__":
    main()

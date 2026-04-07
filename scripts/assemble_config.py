#!/usr/bin/env python3
"""将 prompts/*.md 组装进 configs 的 system_prompt。

修改 Markdown 提示词后运行：
  python scripts/assemble_config.py             # 组装个人模式
  python scripts/assemble_config.py --farm       # 组装农业模式
  python scripts/assemble_config.py --all        # 组装全部

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

CONFIGS_DIR = ROOT / "src" / "plant_care_agent" / "configs"

TARGETS = {
    "personal": {
        "config": CONFIGS_DIR / "config.yml",
        "agent_key": "inner_react",
        "mode": "personal",
    },
    "farm": {
        "config": CONFIGS_DIR / "config_farm.yml",
        "agent_key": "inner_react_farm",
        "mode": "farm",
    },
}


def assemble_one(name: str, target: dict) -> None:
    cfg_path: Path = target["config"]
    if not cfg_path.is_file():
        print(f"找不到配置: {cfg_path}", file=sys.stderr)
        return

    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    agent_key = target["agent_key"]
    if "functions" not in data or agent_key not in data["functions"]:
        print(f"{cfg_path.name} 缺少 functions.{agent_key}", file=sys.stderr)
        return

    data["functions"][agent_key]["system_prompt"] = get_system_prompt(mode=target["mode"])
    out = yaml.dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    )
    cfg_path.write_text(out, encoding="utf-8")
    print(f"已写入 system_prompt ({name}) → {cfg_path}")


def main() -> None:
    args = sys.argv[1:]

    if "--all" in args:
        for name, target in TARGETS.items():
            assemble_one(name, target)
    elif "--farm" in args:
        assemble_one("farm", TARGETS["farm"])
    else:
        assemble_one("personal", TARGETS["personal"])


if __name__ == "__main__":
    main()

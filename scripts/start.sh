#!/usr/bin/env bash
# 启动 NAT 服务（不含交互选择，供 claude_style_chat.py 或手动调用）
# 用法:
#   ./scripts/start.sh              # 默认个人模式
#   ./scripts/start.sh --personal   # 个人模式
#   ./scripts/start.sh --farm       # 农业模式
set -e

cd "$(dirname "$0")/.."

# ── 组装配置 ──
echo "==> 从 prompts/ 组装 system_prompt → configs/.generated/ ..."
python scripts/assemble_config.py --all

GENERATED_DIR="src/plant_care_agent/configs/.generated"

if [[ "$1" == "--farm" ]]; then
    echo "==> 启动农业模式（农场智管）..."
    exec nat serve --config_file "${GENERATED_DIR}/config_farm.yml"
else
    echo "==> 启动个人模式（花花助手）..."
    exec nat serve --config_file "${GENERATED_DIR}/config.yml"
fi

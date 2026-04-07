#!/usr/bin/env bash
# 一键启动 Plant Care Agent
# 用法:
#   ./scripts/start.sh              # 交互式选择模式
#   ./scripts/start.sh --personal   # 个人模式
#   ./scripts/start.sh --farm       # 农业模式
set -e

cd "$(dirname "$0")/.."

echo "==> 从 prompts/ 组装 system_prompt → configs/.generated/ ..."
python scripts/assemble_config.py --all

GENERATED_DIR="src/plant_care_agent/configs/.generated"

if [[ "$1" == "--farm" ]]; then
    MODE="farm"
elif [[ "$1" == "--personal" ]]; then
    MODE="personal"
elif [[ -z "$1" && -t 0 ]]; then
    # 交互式终端且无参数时让用户选择
    echo ""
    echo "  Plant Care Agent"
    echo ""
    echo "  请选择启动模式:"
    echo "    1) 个人模式（花花助手）— 管理家庭植物"
    echo "    2) 农业模式（农场智管）— 大规模农场管理"
    echo ""
    read -r -p "  输入选择 [1/2] (默认 1): " choice
    case "$choice" in
        2) MODE="farm" ;;
        *) MODE="personal" ;;
    esac
else
    MODE="personal"
fi

if [[ "$MODE" == "farm" ]]; then
    echo "==> 启动农业模式（农场智管）..."
    exec nat serve --config_file "${GENERATED_DIR}/config_farm.yml"
else
    echo "==> 启动个人模式（花花助手）..."
    exec nat serve --config_file "${GENERATED_DIR}/config.yml"
fi

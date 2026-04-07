#!/usr/bin/env bash
# 一键启动 Plant Care Agent（服务 + Claude 风格终端）
# 用法:
#   ./scripts/start.sh              # 交互式选择模式
#   ./scripts/start.sh --personal   # 个人模式
#   ./scripts/start.sh --farm       # 农业模式
set -e

cd "$(dirname "$0")/.."

# ── 前台选择模式 ──
if [[ "$1" == "--farm" ]]; then
    MODE="farm"
elif [[ "$1" == "--personal" ]]; then
    MODE="personal"
elif [[ -z "$1" && -t 0 ]]; then
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

# ── 组装配置 ──
echo "==> 从 prompts/ 组装 system_prompt → configs/.generated/ ..."
python scripts/assemble_config.py --all

GENERATED_DIR="src/plant_care_agent/configs/.generated"

if [[ "$MODE" == "farm" ]]; then
    CONFIG_FILE="${GENERATED_DIR}/config_farm.yml"
    echo "==> 模式: 农业模式（农场智管）"
else
    CONFIG_FILE="${GENERATED_DIR}/config.yml"
    echo "==> 模式: 个人模式（花花助手）"
fi

# ── 后台启动 NAT 服务 ──
NAT_PORT="${NAT_PORT:-8000}"
echo "==> 后台启动 NAT 服务 (port=${NAT_PORT}) ..."
nat serve --config_file "${CONFIG_FILE}" &
NAT_PID=$!

cleanup() {
    if kill -0 "$NAT_PID" 2>/dev/null; then
        echo ""
        echo "==> 关闭 NAT 服务 (pid=${NAT_PID}) ..."
        kill "$NAT_PID" 2>/dev/null || true
        wait "$NAT_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# ── 等待服务就绪 ──
echo "==> 等待服务就绪 ..."
MAX_WAIT=30
for i in $(seq 1 $MAX_WAIT); do
    if curl -s -o /dev/null -w '' "http://localhost:${NAT_PORT}/health" 2>/dev/null || \
       curl -s -o /dev/null -w '' "http://localhost:${NAT_PORT}/v1/models" 2>/dev/null; then
        echo "==> 服务已就绪"
        break
    fi
    if ! kill -0 "$NAT_PID" 2>/dev/null; then
        echo "错误: NAT 服务启动失败" >&2
        exit 1
    fi
    if [[ "$i" == "$MAX_WAIT" ]]; then
        echo "警告: 等待超时，仍尝试启动客户端 ..."
    fi
    sleep 1
done

# ── 启动 Claude 风格终端（模式已确定，跳过 chat.py 的选择菜单）──
exec python scripts/claude_style_chat.py --mode "$MODE"

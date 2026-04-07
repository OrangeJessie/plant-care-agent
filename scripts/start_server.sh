#!/usr/bin/env bash
# 纯服务端启动脚本：只启动 NAT 服务，不打开聊天终端。
# 适用于云服务器部署，客户端从外网单独连接。
#
# 用法:
#   ./scripts/start_server.sh                   # 个人模式（默认）
#   ./scripts/start_server.sh --farm            # 农业模式
#   ./scripts/start_server.sh --port 8000       # 指定端口（默认 8000）
#
# 客户端连接（外网机器）:
#   export NAT_CHAT_URL=http://<服务器IP>:<PORT>/v1/chat/completions
#   python scripts/claude_style_chat.py --no-server
#
# 环境变量:
#   NAT_PORT      服务监听端口，默认 8000
#   NAT_HOST      服务监听地址，默认 0.0.0.0（监听所有网卡）

set -euo pipefail
cd "$(dirname "$0")/.."

# ── 解析参数 ────────────────────────────────────────────────────────────────
MODE="personal"
PORT="${NAT_PORT:-9000}"
HOST="${NAT_HOST:-0.0.0.0}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --farm)     MODE="farm";   shift ;;
        --personal) MODE="personal"; shift ;;
        --port)     PORT="$2";     shift 2 ;;
        --host)     HOST="$2";     shift 2 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

# ── 组装配置 ────────────────────────────────────────────────────────────────
echo "==> 组装配置 (mode=$MODE) ..."
python3 scripts/assemble_config.py --all

GENERATED="src/plant_care_agent/configs/.generated"
if [[ "$MODE" == "farm" ]]; then
    CONFIG_FILE="$GENERATED/config_farm.yml"
else
    CONFIG_FILE="$GENERATED/config.yml"
fi

# ── 启动服务 ────────────────────────────────────────────────────────────────
echo "==> 启动 NAT 服务 (host=$HOST port=$PORT config=$CONFIG_FILE) ..."
echo "    客户端连接地址: http://<本机IP>:$PORT/v1/chat/completions"
echo "    按 Ctrl+C 停止服务"
echo ""

exec nat serve \
    --config_file "$CONFIG_FILE" \
    --host "$HOST" \
    --port "$PORT"

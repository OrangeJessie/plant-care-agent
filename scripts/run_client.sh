#!/usr/bin/env bash
# 纯客户端启动脚本：连接远程 NAT 服务，不在本机启动服务。
# 适用于外网机器连接云服务器的场景。
#
# 用法:
#   ./scripts/run_client.sh <服务器地址>              # 如 http://1.2.3.4:8000
#   ./scripts/run_client.sh <服务器地址> --farm        # 农业模式（仅影响 banner，服务端自行决定）
#   ./scripts/run_client.sh                           # 使用环境变量 NAT_CHAT_URL
#
# 示例:
#   ./scripts/run_client.sh http://106.13.186.155:8000
#   ./scripts/run_client.sh http://106.13.186.155:8000 --farm
#
# 环境变量（可代替命令行参数）:
#   NAT_CHAT_URL    服务端完整地址，默认 http://localhost:8000/v1/chat/completions
#   NAT_USER_ID     可选，对话记忆分用户
#   NAT_SESSION_ID  可选，多路会话 ID
#   NAT_IMAGE_MODE  图片传输模式：path / base64 / multipart / url（默认 multipart）

set -euo pipefail
cd "$(dirname "$0")/.."

# ── 解析参数 ────────────────────────────────────────────────────────────────
SERVER_URL=""
EXTRA_ARGS=()

for arg in "$@"; do
    case "$arg" in
        http://*|https://*)
            SERVER_URL="$arg"
            ;;
        *)
            EXTRA_ARGS+=("$arg")
            ;;
    esac
done

# ── 设置服务端地址 ───────────────────────────────────────────────────────────
if [[ -n "$SERVER_URL" ]]; then
    # 自动补全路径
    SERVER_URL="${SERVER_URL%/}"
    if [[ "$SERVER_URL" != */v1/chat/completions ]]; then
        SERVER_URL="${SERVER_URL}/v1/chat/completions"
    fi
    export NAT_CHAT_URL="$SERVER_URL"
fi

export NAT_CHAT_URL="${NAT_CHAT_URL:-http://106.13.186.155:9058/v1/chat/completions}"

# 外网连接时默认用 multipart 模式（图片先上传到服务端，性能最优）
export NAT_IMAGE_MODE="${NAT_IMAGE_MODE:-multipart}"

echo "==> 连接服务端: $NAT_CHAT_URL"
echo "==> 图片模式: $NAT_IMAGE_MODE"
echo ""

exec python3 scripts/claude_style_chat.py --no-server "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"

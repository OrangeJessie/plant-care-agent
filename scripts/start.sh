#!/usr/bin/env bash
# 一键启动 Plant Care Agent（种田宝）
# 用法:
#   ./scripts/start.sh              # 交互选择模式 → 自动启服务 → Claude 风格终端
#   ./scripts/start.sh --personal   # 个人模式
#   ./scripts/start.sh --farm       # 农业模式
#   ./scripts/start.sh --no-server  # 不启服务（连接已运行的服务）
set -e
cd "$(dirname "$0")/.."
exec python scripts/claude_style_chat.py "$@"

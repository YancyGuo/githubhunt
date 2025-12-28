#!/bin/bash

# 启动 GitHubHunt API 服务
# 使用 uvicorn 运行 FastAPI 应用

export PATH="$HOME/.local/bin:$PATH"

# 默认配置
HOST="${API_HOST:-0.0.0.0}"
PORT="${API_PORT:-7777}"

echo "Starting GitHubHunt API Server..."
echo "Host: $HOST"
echo "Port: $PORT"
echo ""

uv run uvicorn api_server:app --host "$HOST" --port "$PORT" --reload
